"""backupの状況。「守りが効いているか」を1 requestで返す。

状態が散らばっているのは仕組みの都合である —— DBのsnapshotは退避先のfolder、一次保存の
写しは台帳json、設定値と手入力データは各保存先の ``_config/``、二重化は2つのdrive。見る人の
都合ではないので、ここで1つに束ねる。壊れているときほど「どこを見ればよいか」を思い出す
余裕は無い。

**判定はここで作らない。** 走らせる条件は :mod:`tictok.api.startup` に、世代と行数の
見張りは :mod:`tictok.core.dbmaint` に、写しの結果は台帳に在る。ここがやるのは、それらを
同じ形へ揃えて経路(lane)ごとに並べることだけである。判定を書き写すと、周期や閾値を直した
ときに画面だけが古い答えを出し続ける。

経路は4本ある。左(守る対象)と右(退避先)を結ぶ線が4本、という以上の意味は持たせない ——
種別を増やすほど、1本が止まったときにどれが止まったのか読めなくなる。
"""

import asyncio
import time
from pathlib import Path

from fastapi import APIRouter

from tictok.api import runtime
from tictok.api import startup
from tictok.api import disk
from tictok.api.disk import _final_dirs
from tictok.core import dbmaint, ops_labels, settings_export, tables_export
from tictok.core.config import (get_db_backup_keep, get_db_path, get_journal_dir,
                                get_journal_enabled, get_journal_retention_days,
                                record_backup_dir_from_db)
from tictok.record import primary_backup
from tictok.store._common import OPS_ERROR, OPS_WARNING
from tictok.record.recorder import disk_free_by_volume, _volume_key

router = APIRouter()

# 経路の状態。**順序が優先順位**である(上ほど強い)。1つの経路が同時に複数当てはまることは
# あり、そのとき人が知りたいのは常に重い方だからである。
STATE_OFF = "off"                # 設定で止めてある / 写す先が無い
STATE_UNREACHABLE = "unreachable"  # 退避先に届かない(driveが外れた・pathが無い)
STATE_FAILING = "failing"        # 直近の記録が失敗
STATE_LATE = "late"              # 済んでいない録画が猶予を越えて残っている
# 走ったが一部が写せなかった。**成功として数えない。** 「写した11件/失敗3件」は成功の記録
# (kindはjob_completed)として残るので、kindだけを見ると緑になる ―― 3件は控えに無いのに。
STATE_DEGRADED = "degraded"
STATE_WORKING = "working"        # 控えが在る(次の周期が写す)
STATE_OK = "ok"

# 経路の定義。``step`` は退避の印(``startup._BACKUP_MARK_KEYS``)の名前で、二重化だけは
# 印を持たない —— 人が画面から実行する操作で、周期に乗っていないためである。
_LANES = (
    {
        "key": "db",
        "settings_keys": ("db_backup_on_recording_finished", "db_backup_dir"),
        "step": startup.BACKUP_STEP_DB,
        "label": "DB",
        "source": "tictok.db",
        "source_note": "配信・録画の台帳",
        "ok_kinds": ("maintenance.backup_completed",),
        "fail_kinds": ("maintenance.backup_failed",),
    },
    {
        "key": "config",
        "settings_keys": (),
        "step": startup.BACKUP_STEP_SETTINGS,
        "label": "設定",
        "source": "settings ほか7表",
        "source_note": "settings / bookmarks ほか",
        "ok_kinds": ("backup.settings_exported", "backup.tables_exported"),
        "fail_kinds": ("backup.settings_export_failed", "backup.tables_export_failed"),
    },
    {
        "key": "files",
        "settings_keys": ("record_backup_enabled", "record_backup_dir"),
        "step": startup.BACKUP_STEP_FILES,
        "label": "録画ファイル",
        "source": "録画の原本",
        "source_note": "seg*.ts / avatar / mp4",
        "ok_kinds": ("record_backup.job_completed",),
        "fail_kinds": ("record_backup.job_failed", "record_backup.stopped"),
    },
    {
        "key": "mirror",
        "settings_keys": ("record_dir_final", "record_dir_final2"),
        "step": None,
        "label": "ミラー",
        "source": "移送済みの録画",
        "source_note": "移送した実体",
        "ok_kinds": ("storage.relocated", "storage.mirror_resynced"),
        "fail_kinds": ("storage.mirror_diverged", "storage.mirror_unavailable"),
    },
)


def _dest_facts(path) -> dict:
    """退避先1つの素性。``exists`` と ``reachable`` を分けるのは、この仕組みが
    **親folderを作らない**からである(driveが外れている間にsystem driveへ空folderが
    生まれ、そこへ世代が積み上がるのを避けるため)。指定folderが未作成なだけなら次の退避が
    自分で作るので障害ではないが、親ごと無いのは届いていないという意味になる。"""
    target = Path(path)
    return {
        "path": str(target),
        "parent": str(target.parent),
        "exists": target.is_dir(),
        "reachable": target.parent.is_dir(),
        "volume": _volume_key(target),
    }


def _dest_group(paths) -> list:
    return [_dest_facts(path) for path in paths if path]


def _latest_of(latest: dict, kinds) -> dict:
    """``kinds`` のうち最も新しい1件。無ければ空。"""
    found = [latest[kind] for kind in kinds if kind in latest]
    if not found:
        return {}
    return max(found, key=lambda item: item["ts"])


def _lane_step(lane: dict, schedule: dict, final_dirs) -> dict:
    """経路の予定。二重化だけは周期に乗らないので、印を持たない形をここで作る ——
    「済んでいない」と読ませないために、有効(2系統とも設定済み)かどうかだけを名乗る。"""
    step = schedule["steps"].get(lane["step"]) if lane["step"] else None
    if step is not None:
        return step
    return {"enabled": len(final_dirs) > 1, "pending": 0, "overdue": False,
            "failures": 0, "retry_in_seconds": 0.0, "mark_at": None,
            "pending_oldest_at": None, "grace_seconds": None}


def _lane_state(step: dict, dests: list, ok: dict, fail: dict, gap: bool = False) -> str:
    """経路1本の状態。``dests`` が空のときは退避先へ届くかを見ない。

    届くかの確認はfileを触る(外れたdriveでは待たされる)ので、badgeのような軽い問い合わせ
    では省く。省いても取りこぼさない —— 退避先が外れれば次の周期が失敗するか、写せない
    録画が猶予を越えて残るかのどちらかになり、どちらもfileを触らずに読める。

    ``gap`` は「控えが欠けていると**確かめてある**」という事実で、実行の記録とは別の口から
    入る。二重化がそれで、移送は必ず全系統へ書くので成功の記録だけを見ている限り片方が
    古いことは永久に現れない —— 実際に突き合わせた結果を入れない限り、543GB欠けた系統を
    抱えたまま「追いついている」と名乗り続ける。"""
    if not step["enabled"]:
        return STATE_OFF
    if dests and not any(dest["reachable"] for dest in dests):
        return STATE_UNREACHABLE
    if step["failures"] or (fail and fail["ts"] > (ok.get("ts") or 0.0)):
        return STATE_FAILING
    if step["overdue"]:
        return STATE_LATE
    if gap:
        return STATE_DEGRADED
    # 成功のkindでもseverityがinfoでない回は、一部が写せていない。kindだけを見て緑にすると、
    # 「写した11件・失敗3件」が完了として通り、写せなかった3件を誰も追わない。
    if ok and ok.get("severity") in (OPS_WARNING, OPS_ERROR):
        return STATE_DEGRADED
    if step["pending"]:
        return STATE_WORKING
    return STATE_OK


def _mirror_gap(check: dict) -> bool:
    """突き合わせた結果、2系統が揃っていないと分かっているか。

    **確かめていない回は偽にする。** 未確認を欠けとして立てると、突き合わせを一度も回して
    いない構成が常時赤になり、本当に欠けた日の警報と見分けが付かなくなる(未確認であることは
    画面が別に名乗る)。再同期の直後(``stale``)も同じ扱いで、あの件数は実行前の姿である。"""
    if not check.get("at") or check.get("stale"):
        return False
    return bool(check.get("missing_items") or check.get("diverged"))


# 止まっている理由。**状態(state)とは別に持つ。** 「止まっている」だけでは直しに行けない ——
# 退避先が未設定なのか、driveが外れたのか、設定で止めたのかで、次にやることが全部違う。
REASON_NO_PATH = "no_path"        # 写す先が設定されていない
REASON_DISABLED = "disabled"      # 設定で止めてある
REASON_SINGLE = "single"          # 2系統でないので二重化になっていない
REASON_UNREACHABLE = "unreachable"  # 設定はあるが届かない
REASON_FAILED = "failed"          # 直近の実行が失敗した
REASON_OVERDUE = "overdue"        # 猶予を越えて済んでいない録画が残っている
REASON_PARTIAL = "partial"        # 走ったが一部が写せなかった
REASON_UNSYNCED = "unsynced"      # 突き合わせた結果、2系統が揃っていない

# 人へ知らせる状態(重い順)。badgeを出すかどうかはこの並びだけで決める。
_ALERT_STATES = (STATE_UNREACHABLE, STATE_FAILING, STATE_LATE, STATE_DEGRADED)


def _off_reason(lane_key: str, final_dirs) -> dict:
    """止めてある経路が「未設定」なのか「無効」なのかを分ける。

    どちらも走らないという点では同じだが、直し方は正反対である —— 前者はpathを決める話、
    後者は決まっているpathへ走らせる話。画面が同じ言葉で出すと、設定を開いてから
    どちらなのかを人が探し直すことになる。"""
    if lane_key == "db":
        return {"key": REASON_DISABLED, "settings": ["db_backup_on_recording_finished"]}
    if lane_key == "files":
        if not record_backup_dir_from_db(get_db_path()):
            return {"key": REASON_NO_PATH, "settings": ["record_backup_dir"]}
        return {"key": REASON_DISABLED, "settings": ["record_backup_enabled"]}
    if lane_key == "mirror":
        if not final_dirs:
            return {"key": REASON_NO_PATH,
                    "settings": ["record_dir_final", "record_dir_final2"]}
        return {"key": REASON_SINGLE, "settings": ["record_dir_final2"]}
    return {}


def _lane_reason(lane: dict, state: str, dests: list, final_dirs) -> dict:
    """経路が ok でないときの理由。ok のときは空。

    ``paths`` には**実際に問題のあるpathだけ**を入れる。全部の退避先を並べると、3つのうち
    1つだけ外れている状況で人が突き合わせを強いられる —— そこが一番読み違える場面である。"""
    if state == STATE_OFF:
        return _off_reason(lane["key"], final_dirs)
    if state == STATE_UNREACHABLE:
        return {"key": REASON_UNREACHABLE,
                "settings": list(lane["settings_keys"]),
                "paths": [d["path"] for d in dests if not d["reachable"]]}
    if state == STATE_FAILING:
        return {"key": REASON_FAILED, "settings": list(lane["settings_keys"])}
    if state == STATE_LATE:
        return {"key": REASON_OVERDUE, "settings": []}
    if state == STATE_DEGRADED:
        # 二重化の「一部が写せていない」は、実行の失敗ではなく突き合わせで分かった欠けで
        # ある。同じ言葉で出すと、次にやること(再同期を回す)が読めない。
        if lane["key"] == "mirror":
            return {"key": REASON_UNSYNCED, "settings": []}
        return {"key": REASON_PARTIAL, "settings": []}
    return {}


def _with_label(event: dict) -> dict:
    """ops_eventのkindへ日本語の名前を添える。画面がkindの対応表を持つと、増えたkindが
    生のままそこにだけ出る(名前の出所は ``core.ops_labels`` 1つに保つ)。"""
    if not event:
        return {}
    return {**event, "label": ops_labels.KIND_LABELS.get(event["kind"], event["kind"])}


async def _latest_lane_events() -> dict:
    return await asyncio.to_thread(
        runtime.storage.latest_ops_events_by_kind,
        [kind for lane in _LANES for kind in lane["ok_kinds"] + lane["fail_kinds"]],
    )


def _config_generations(roots) -> list:
    """保存先ごとの ``_config/`` の世代。設定値と手入力データを**同じ行**に並べる ——
    2つは同じ印で進むので、片方だけが新しい保存先は「書けなかった回がある」という意味に
    なり、それは並べて初めて読める。"""
    out = []
    for root in settings_export.unique_roots(roots):
        settings_items = settings_export.list_exports(root)
        table_items = tables_export.list_exports(root)
        out.append({
            "root": str(root),
            "dir": str(settings_export.export_dir(root)),
            "exists": settings_export.export_dir(root).is_dir(),
            "settings": {
                "count": len(settings_items),
                "latest": settings_items[0] if settings_items else None,
            },
            "tables": {
                "count": len(table_items),
                "latest": table_items[0] if table_items else None,
            },
        })
    return out


def _snapshot_generations() -> dict:
    """DBのsnapshotの世代と、それが暦のどの層で残っているか。

    層(日次/週次)を名前で引けるようにして返す。層が読めないと「なぜこの世代だけ古いのに
    残っているのか」が画面から分からない —— 保持の規則は回数ではなく暦だからである。"""
    items = dbmaint.list_backups()
    layers = dbmaint.scheduled_layers()
    by_name = {}
    for entry in layers.get("daily", []):
        by_name[entry["name"]] = "daily"
    for entry in layers.get("weekly", []):
        by_name[entry["name"]] = "weekly"
    for name in layers.get("expiring", []):
        by_name.setdefault(name, "expiring")
    for item in items:
        item["layer"] = by_name.get(item["name"], "")
    return {
        "dir": str(dbmaint.backup_dir()),
        "items": items,
        "bytes": sum(int(item.get("bytes") or 0) for item in items),
        "keep": get_db_backup_keep(),
        "daily": layers.get("daily", []),
        "weekly": layers.get("weekly", []),
        "expiring": layers.get("expiring", []),
        "keep_daily": layers.get("keep_daily"),
        "keep_weekly": layers.get("keep_weekly"),
    }


def _primary_facts() -> dict:
    """一次保存の控えの素性。台帳が持つ直前の回の結果と、pool archiveの成否。

    ``root_id`` まで返すのは、drive letterの入れ替わりで**別のdriveへ丸ごと写し始める**事故が
    この値の一致だけで止まっているためである。突き合わせに失敗した回は1byteも写さずに
    経路が失敗として立つので、ここでは「いまどの識別子の先へ写しているか」を名乗るだけで
    足りる —— 名乗らないと、一致していること自体を誰も確かめられない。"""
    configured = primary_backup.is_configured()
    facts = {"configured": configured, "root": "", "last_run": None,
             "pools": [], "root_id": ""}
    if not configured:
        return facts
    try:
        facts["root"] = str(primary_backup.backup_root())
    except primary_backup.PrimaryBackupError:
        return facts
    last = primary_backup.last_run()
    facts["last_run"] = last
    facts["pools"] = list((last or {}).get("pools") or [])
    facts["root_id"] = str((last or {}).get("root_id") or "")
    return facts


def _journal_facts() -> dict:
    """journalは退避ではない。DBのwriterが止まってもeventが残るための防波堤で、守って
    いる失敗が退避と違う。だから経路には入れず、別の1項目として素性だけ返す。"""
    directory = Path(get_journal_dir())
    files = sorted(directory.glob("events-*.jsonl")) if directory.is_dir() else []
    newest = max((path.stat().st_mtime for path in files), default=None)
    return {
        "enabled": get_journal_enabled(),
        "dir": str(directory),
        "files": len(files),
        "bytes": sum(path.stat().st_size for path in files),
        "newest_at": newest,
        "retention_days": get_journal_retention_days(),
    }


def _defenses(guard: dict, trash: dict) -> list:
    """誤削除に対する3段と、その外側のsnapshot。**互いの代わりにならない**ので、1つでも
    欠けていれば守れない失敗が在るという形で並べる(``doc/BACKUP.md`` の対応表)。"""
    frozen = guard.get("frozen") or None
    return [
        {
            "key": "authorizer",
            "label": "DROP拒否",
            "covers": "serverの接続",
            "misses": "外部process",
            "state": STATE_OK,
            "value": None,
        },
        {
            "key": "guard",
            "label": "行数監視",
            "covers": "大量削除・0行化",
            "misses": "小さい表の部分削除",
            "state": STATE_FAILING if frozen else STATE_OK,
            "value": len(guard.get("tables") or []),
            "frozen": frozen,
        },
        {
            "key": "trash",
            "label": "削除行の保管",
            "covers": "行1本の誤削除",
            "misses": "DB fileの喪失",
            "state": STATE_OK,
            "value": trash.get("rows"),
        },
        {
            "key": "snapshot",
            "label": "別driveへコピー",
            "covers": "DB fileの喪失・破損",
            "misses": "1行だけ戻すこと",
            "state": STATE_OK,
            "value": None,
        },
    ]


@router.get("/api/backup/overview")
async def backup_overview_api() -> dict:
    """退避4経路の状態を1枚に束ねて返す。

    fileを触る読み取り(退避先の一覧・台帳・保存先のfolder)はすべてthreadへ逃がす。退避先は
    network driveや外付けである前提で、event loopの上で開くと1台外れているだけで画面全体が
    止まる。"""
    schedule = await startup.backup_schedule_status()
    latest = await _latest_lane_events()
    snapshots = await asyncio.to_thread(_snapshot_generations)
    guard = await asyncio.to_thread(dbmaint.guard_status)
    primary = await asyncio.to_thread(_primary_facts)
    final_dirs = _final_dirs()
    roots = [runtime.RECORD_DIR, *final_dirs]
    configs = await asyncio.to_thread(_config_generations, roots)
    trash = await asyncio.to_thread(runtime.storage.row_trash_summary)
    journal = await asyncio.to_thread(_journal_facts)
    # 二重化の「どこまで写したか」。空き容量では1byteも答えられない —— 最終保存先に何本
    # 在って作業先に何本残っているかはDBが持っており(容量画面と同じ関数を呼ぶ。判定を写すと
    # 2画面が別々の本数を名乗る)、2系統が同じ中身かは走査した回の記録が持つ。
    relocation = await asyncio.to_thread(disk._relocation_summary)
    mirror_check = await asyncio.to_thread(disk.mirror_check_status)

    dests = {
        "db": _dest_group([snapshots["dir"]]),
        # 設定値の退避先は世代の一覧と**同じpath文字列**から作る。別々に組み立てると、
        # 画面が両者を突き合わせられない(2つの最終保存先はどちらも末尾が同じ
        # ``80_Tiktok\_config`` なので、末尾で照合すると片方の世代がもう片方に出る)。
        "config": _dest_group([entry["dir"] for entry in configs]),
        "files": _dest_group([primary["root"]] if primary["root"] else []),
        "mirror": _dest_group(final_dirs),
    }
    volumes = await asyncio.to_thread(
        disk_free_by_volume,
        [dest["path"] for group in dests.values() for dest in group],
    )

    lanes = []
    for lane in _LANES:
        step = _lane_step(lane, schedule, final_dirs)
        ok = _latest_of(latest, lane["ok_kinds"])
        fail = _latest_of(latest, lane["fail_kinds"])
        state = _lane_state(step, dests[lane["key"]], ok, fail,
                            gap=lane["key"] == "mirror" and _mirror_gap(mirror_check))
        lanes.append({
            "key": lane["key"],
            "label": lane["label"],
            "source": lane["source"],
            "source_note": lane["source_note"],
            "state": state,
            "reason": _lane_reason(lane, state, dests[lane["key"]], final_dirs),
            "dests": dests[lane["key"]],
            "schedule": step,
            "last_ok": _with_label(ok) or None,
            "last_fail": _with_label(fail) or None,
        })

    return {
        "now": time.time(),
        "lanes": lanes,
        "schedule": schedule,
        "snapshots": snapshots,
        "configs": configs,
        "primary": primary,
        "guard": guard,
        "row_trash": trash,
        "journal": journal,
        "relocation": relocation,
        "mirror_check": mirror_check,
        "defenses": _defenses(guard, trash),
        "volumes": volumes,
        # 守る対象がどのvolumeに在るか。退避先と同じdriveなら、それは控えではなく複製で
        # しかない —— 画面がvolumeを名乗らないと、設定した本人でも気付けない。
        "sources": {
            "db": {"path": str(get_db_path()), "volume": _volume_key(get_db_path())},
            "record": {"path": str(runtime.RECORD_DIR),
                       "volume": _volume_key(runtime.RECORD_DIR)},
        },
        "record_dir": str(runtime.RECORD_DIR),
        "final_dirs": [str(path) for path in final_dirs],
    }


@router.get("/api/backup/health")
async def backup_health_api() -> dict:
    """全画面のnavに出すbadgeのための軽い問い合わせ。**fileを1つも触らない。**

    状況画面(:func:`backup_overview_api`)を全画面から1分ごとに引くわけにはいかない ——
    退避先の一覧・台帳・保存先のfolderを毎回開くことになり、外付けdriveが1台外れている
    だけで全画面が待たされる。ここが読むのはDBの2 queryだけで、答えるのは
    「知らせるべき経路があるか」だけである。"""
    schedule = await startup.backup_schedule_status()
    latest = await _latest_lane_events()
    final_dirs = _final_dirs()
    # 突き合わせの結果はDBの1行で、fileは1つも触らない。ここを読まないと、揃っていないと
    # 分かっている系統を抱えたままbadgeだけが緑のままになる。
    mirror_check = await asyncio.to_thread(disk.mirror_check_status)
    alerts = []
    for lane in _LANES:
        state = _lane_state(
            _lane_step(lane, schedule, final_dirs), [],
            _latest_of(latest, lane["ok_kinds"]), _latest_of(latest, lane["fail_kinds"]),
            gap=lane["key"] == "mirror" and _mirror_gap(mirror_check),
        )
        if state in _ALERT_STATES:
            alerts.append({"key": lane["key"], "label": lane["label"], "state": state,
                           "reason": _lane_reason(lane, state, [], final_dirs)})
    # 最も重い状態を名乗る。badgeは1つしか出せないので、軽い方を採ると重い方が隠れる。
    worst = next((state for state in _ALERT_STATES
                  if any(item["state"] == state for item in alerts)), "")
    return {"now": time.time(), "state": worst, "alerts": alerts}
