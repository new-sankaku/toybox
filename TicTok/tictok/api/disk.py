"""容量・空き・退避(final dirへの移送)・保持policyの計算。

「今どれだけ使っているか」「何をどの順で消すか」「どれを最終保管先へ移すか」を、
routeから切り離して置く。route側(``tictok.api.routes.storage``)は lock と job台帳と
応答整形だけを持つ。

依存は runtime / files / fsfacts。
"""

import json
import shutil
import time
from pathlib import Path
from typing import Optional
from fastapi import HTTPException
from tictok.paths import PROJECT_ROOT
from tictok.core.config import get_db_path, get_log_dir
from tictok.core import layout
from tictok.record.recorder import disk_free_by_volume, is_finalizing, Recorder
from tictok.record import mirror
from tictok.record import retention
from tictok.record.upscale import cleanup_upscale_files
from tictok.core import cancel, capacity
from tictok.storage import OPS_WARNING
from tictok.record.video_overlay import cleanup_overlay_files
from tictok.api import files as api_files
from tictok.api import fsfacts
from tictok.api import runtime


def _disk_volume_paths() -> list:
    """Every volume the running install writes to: the working dir (HLS + capture),
    the final dirs (relocation targets and where outputs are generated), the DB and the
    logs. These routinely sit on different drives, so only a per-volume reading says
    which one is about to fill up.

    最終保存先は全系統を並べる。2系統は相互mirrorで**両方へ同じ量を書く**ので、片方だけを
    測っていると、もう一方が満杯に近づいていても誰も気付かない(移送はその時点で両系統とも
    行われなくなる)。"""
    return [runtime.RECORD_DIR, *_final_dirs(), get_db_path(), get_log_dir()]


def _disk_min_free_bytes() -> int:
    """Free-space floor below which heavy outputs are refused. Deliberately separate
    from the log-only preflight threshold (get_log_disk_low_bytes): that one warns,
    this one blocks, and an operator who wants a louder warning must not thereby
    change what is allowed to run."""
    return int(runtime.settings.get("disk_min_free_gb")) * 1024 * 1024 * 1024


def _disk_report(paths=None) -> dict:
    """Per-volume free space with the volumes that are already below the floor named.
    ``low_volumes`` is empty when the gate is disabled (floor 0), which keeps the
    "blocked" state and the "measured" state distinguishable in the UI."""
    report = disk_free_by_volume(_disk_volume_paths() if paths is None else paths)
    floor = _disk_min_free_bytes()
    low = sorted(v for v, info in report.items() if info["free_bytes"] < floor) if floor else []
    return {"volumes": report, "min_free_bytes": floor, "low_volumes": low}


def _require_disk_space(paths, stage: str, **ctx) -> None:
    """Refuse to start a job that writes a large intermediate when a volume it needs is
    below the configured floor. Disk exhaustion has surfaced here as symptoms with no
    visible relation to disk (avatars vanishing from a burn-in, emoji turning
    monochrome), so the check runs before the work rather than after the damage."""
    floor = _disk_min_free_bytes()
    if floor <= 0:
        return
    report = disk_free_by_volume(paths)
    low = sorted(v for v, info in report.items() if info["free_bytes"] < floor)
    if not low:
        return
    runtime.logger.warning(
        "%s を拒否しました: %s の空き容量が設定の下限を下回っています", stage, ", ".join(low),
        extra={"event": "disk.gate_blocked",
               "ctx": {"volumes": report, "low_volumes": low, "min_free_bytes": floor,
                       "stage": stage, **ctx}},
    )
    shortest = min(report[v]["free_bytes"] for v in low)
    raise HTTPException(
        status_code=507,
        detail=(f"空き容量が不足しています（{', '.join(low)}: 残り{shortest / (1024 ** 3):.1f}GB / "
                f"下限{floor / (1024 ** 3):.0f}GB）。不要なfileを削除するか、設定の"
                f"「出力を拒否する空き容量の下限（GB）」を見直してください。"),
    )


# ---- 容量の時系列と予測 ------------------------------------------------------------
# 日次のsnapshotを貯めて増加速度から満杯までを見積もる。sampleはfilesystemを走査しない:
# drive空きはO(1)、録画量とDB行数はDBから引ける(実測 全部で48ms)。分単位かかる
# /api/storage/scan とは別物で、あちらを日次で回すことはしない。

def _backup_dir_bytes() -> dict:
    """backups/ の合計。DBのbackupは1本が数百MB規模まで育ち、消し忘れると効いてくる。
    走査対象はbackup先の直下だけなので件数は数十で、日次sampleに含めても安い。"""
    root = PROJECT_ROOT / "backups"
    if not root.is_dir():
        return {"bytes": 0, "files": 0}
    total = 0
    files = 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
                files += 1
        except OSError:
            # 走査中に消えたbackupは数えないだけでよい。容量sampleを失敗させる理由はない。
            continue
    return {"bytes": total, "files": files}


def _capacity_snapshot() -> dict:
    """1時点ぶんの容量snapshot。filesystem走査なしで採れるものだけで構成する。"""
    return {
        "disk": _disk_report(),
        "db_files": runtime.storage.db_file_bytes(),
        "backups": _backup_dir_bytes(),
        **runtime.storage.capacity_db_counts(),
    }


def _volume_series(samples: list) -> dict:
    """volume別に (時刻, 空きbytes) の列へ組み替える。"""
    series: dict = {}
    for sample in samples:
        volumes = ((sample.get("payload") or {}).get("disk") or {}).get("volumes") or {}
        for name, info in volumes.items():
            free = info.get("free_bytes")
            if free is None:
                continue
            series.setdefault(name, []).append((sample["sampled_at"], float(free)))
    return series


def _capacity_report() -> dict:
    """容量の現況・時系列・予測・完了率を1つにまとめる。

    予測は必ず区間で返す(core.capacity)。観測が数日しかない段階で「あとX日」と言い切ると、
    それは観測から出た値ではなく作った値になる。
    """
    now_snapshot = _capacity_snapshot()
    samples = runtime.storage.list_capacity_samples(limit=runtime.CAPACITY_HISTORY_LIMIT)
    min_samples = int(runtime.settings.get("capacity_forecast_min_samples"))
    max_extrapolation = float(runtime.settings.get("capacity_forecast_max_extrapolation"))

    forecasts = {}
    volumes_now = now_snapshot["disk"]["volumes"]
    for name, points in _volume_series(samples).items():
        free_now = volumes_now.get(name, {}).get("free_bytes")
        if free_now is None:
            continue
        forecasts[name] = capacity.forecast_days_to_full(
            points, float(free_now),
            min_samples=min_samples, max_extrapolation=max_extrapolation,
        )
    # sampleがまだ無いvolumeも「予測不能」として必ず出す。行が消えていると、
    # 「予測が出ていない」のか「そのvolumeを見ていない」のか区別できない。
    for name, info in volumes_now.items():
        forecasts.setdefault(name, {
            "status": capacity.STATUS_INSUFFICIENT, "n": 0, "observed_days": 0.0,
            "free_bytes": info.get("free_bytes"), "min_samples": min_samples,
            "max_extrapolation": max_extrapolation,
        })

    counts = now_snapshot
    completed = next(
        (r["n"] for r in counts["recordings_by_status"] if r["status"] == "completed"), 0)
    transcribed = counts["transcribed_completed"]
    overlay_done = sum(
        j["n"] for j in counts["media_jobs"]
        if j["kind"] == "overlay" and j["state"] == "completed")
    return {
        "now": now_snapshot,
        "sampled_at": samples[-1]["sampled_at"] if samples else None,
        "samples": samples,
        "forecasts": forecasts,
        # 録画の増加実績はsampleを待たずに遡って出せる(recordingsが最初から持っている)。
        # sample由来の系列とは由来が違うので、payloadでも分けて返す。
        "recording_daily": runtime.storage.recording_bytes_by_day(runtime.CAPACITY_HISTORY_LIMIT),
        # 完了録画がどちらの保存先に何本あるかと、一時保存先の取り残し。容量の話なので
        # ここに載せる。常時見えていれば「移動が呼ばれていない」状態に気付ける。
        "placement": _relocation_summary(),
        "completion": {
            "completed_recordings": completed,
            "transcribed": transcribed,
            "transcribed_rate": capacity.completion_rate(transcribed, completed),
            "overlay_done": overlay_done,
            "overlay_rate": capacity.completion_rate(overlay_done, completed),
        },
    }


def _capacity_alert_check(report: dict) -> None:
    """満杯が近いvolumeをops_eventとして記録する。

    通知経路は新設しない。ops_eventはstorage.set_ops_observer経由で既存の通知rule
    (notify_rule_ops)がそのまま拾うので、severityを正しく付けるだけでよい。
    """
    threshold_days = float(runtime.settings.get("capacity_alert_days"))
    if threshold_days <= 0:
        return
    for name, forecast in report["forecasts"].items():
        if forecast.get("status") != capacity.STATUS_OK:
            continue
        # 区間の下限(最も早く尽きる側)で判定する。点推定で判定すると、区間の下限が
        # 既に閾値を割っていても黙ることになる。
        days_low = forecast.get("days_low")
        if days_low is None or days_low >= threshold_days:
            continue
        runtime.storage.record_ops_event(
            runtime.logger, "capacity.forecast_low",
            "{name} は {low:.0f}〜{high:.0f}日で満杯になる見通しです"
            "（観測 {obs:.1f}日）".format(
                name=name, low=days_low, high=forecast.get("days_high", days_low),
                obs=forecast.get("observed_days", 0.0)),
            severity=OPS_WARNING,
            detail={"volume": name, "days_low": days_low,
                    "days_high": forecast.get("days_high"),
                    "observed_days": forecast.get("observed_days"),
                    "free_bytes": forecast.get("free_bytes"),
                    "threshold_days": threshold_days},
        )


# ---- 最終保存先への移動 ------------------------------------------------------------
# 移送はここが唯一の入口である。finalizeは移送しない: 確定した録画は一時保存先に残り、
# いつ最終保存先へ移すかはこの画面から人が決める。移送の実体は recorder の
# _move_recording_files を使う(moverを二重に持たない)。自動で動く経路が無い以上、
# 一時保存先は放っておけば増え続けるので、本数と容量を容量画面に常時出して気付けるようにする。
#
# 最終保存先が2つ設定されているとき、それらは**振り分け先ではなく相互mirror**である。1台の
# diskが壊れても退避済みのdataが残るようにするためのもので、両系統は常に同じ内容でなければ
# ならない。したがって移送は「どちらかへ移す」ではなく「全系統へ複製してから元を消す」で、
# 片系統にでも書けないなら移送そのものを行わない(``tictok.record.mirror``)。

def _final_dirs() -> list:
    """移送で**書き込む**最終保存先の全系統。1つも無ければ空list。

    代表値 ``runtime.FINAL_DIR`` を先頭に置き、``runtime.FINAL_DIRS`` の残りを続ける。
    代表値も必ず書き込み対象に含めるのは、「読み出し・表示が指すroot」と「書き込むroot」が
    別々の名前で別々の集合を指すと、読む側は在ると言い書く側は書かない、という食い違いが
    起きるためである(``runtime`` の定義では FINAL_DIR は FINAL_DIRS[0] なので、実運用では
    両者は完全に一致する)。

    一時保存先そのものは外す —— 同じrootへ2度書くのはmirrorではなく同じfileへの二重書き込み
    であり、そもそも移す先が無い状態である。
    """
    dirs: list = []
    for root in (runtime.FINAL_DIR, *runtime.FINAL_DIRS):
        if root != runtime.RECORD_DIR and root not in dirs:
            dirs.append(root)
    return dirs


def _relocation_enabled() -> bool:
    """退避先が別に設定されているときだけ機能を出す。同一なら移す先が無い。"""
    return bool(_final_dirs())


def _mirror_enabled() -> bool:
    """再同期(2系統の突き合わせ)を出すか。相手が居るのは2系統以上のときだけ。"""
    return len(_final_dirs()) >= 2


def _unavailable_final_dirs() -> list:
    """今この瞬間に見えていない最終保存先。外付けHDDがbusから落ちれば丸ごと消える。

    見えないrootを「空」と読むと、そこに在るはずのdataが全部欠けていることになり、再同期は
    最終保存先の中身を丸ごと(実測2026-09-02で ``K:\\80_Tiktok`` の 12,340 file / 0.59TB)複製し
    始め、移送は「退避先に同名は無い」と判断して片系統だけへ書く。どちらも、
    diskが戻ってきた瞬間に食い違いとして現れる。だからrootが1つでも見えないなら、突き合わせも
    移送も行わない。
    """
    return [root for root in _final_dirs() if not root.is_dir()]


def _relocation_ready() -> bool:
    """移送・随伴・突き合わせを行ってよい状態か(退避先が在り、全系統が見えている)。"""
    return _relocation_enabled() and not _unavailable_final_dirs()


def _require_mirrors_available(stage: str) -> None:
    """最終保存先が1つでも見えないなら、その操作を始めさせない。

    ``_require_disk_space`` と同じ位置付けで、始めてから壊すのではなく始める前に断る。
    見えないrootが在る状態で移送すれば片系統だけが最新になり、それは次の障害で気付かずに
    dataを失う唯一の経路である。運用logに残すのは、diskが外れていた事実そのものが、後から
    「なぜあの日から片方が古いのか」を答える唯一の手掛かりになるためである。
    """
    missing = _unavailable_final_dirs()
    if not missing:
        return
    runtime.storage.record_ops_event(
        runtime.logger, "storage.mirror_unavailable",
        "{stage}を中止しました: 最終保存先 {dirs} が見つかりません".format(
            stage=stage, dirs="、".join(str(root) for root in missing)),
        severity=OPS_WARNING,
        detail={"stage": stage, "missing": [str(root) for root in missing],
                "final_dirs": [str(root) for root in _final_dirs()]},
    )
    raise HTTPException(
        status_code=409,
        detail=("最終保存先 {dirs} が見つかりません（driveが外れている可能性があります）。"
                "両系統が揃うまで移送・再同期は行いません。".format(
                    dirs="、".join(str(root) for root in missing))),
    )


def _is_under(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return resolved == root or root in resolved.parents


def _relocation_plan() -> dict:
    """working dir に残っている完了録画の一覧(dry-run)と、完了録画の所在の内訳。

    mp4が在る録画の容量は**DBのbytesではなく実fileのsize**で出す。実測では16本がDB値と1KB
    以上ずれており、移送量として読むならディスク上の実体が正しい(素材だけの録画は後述の
    とおりDB値で出す)。

    「実体が無い」の判定はmp4の実在では行わない。finalizeはmp4を作らなくなり、録画の実体は
    session dirの ``.ts`` である。mp4だけを見ていたため、**素材しか無い録画は移送計画に一度も
    載らなかった**(実測2026-07-26、finalizeの移送に失敗した1本が作業先に残ったまま、画面の
    「まだ移していない」にも現れなかった)。mp4も素材も無い行だけを除く。実測では working dir
    を指す完了録画132本のうち82本がこれ(retention削除済み)で、件数に混ぜると「82本移せる」
    という嘘になる。

    最終保存先が2系統あるときの ``dst`` は代表(``final_dir``)のもので、実際に書く先は
    ``dsts`` の全部である。退避先の同名判定も**全系統**で行う: 片方にだけ在る録画を「まだ
    移していない」として数えると、移送は片方へ書けず失敗し続ける(埋めるのは再同期の役目)。

    最終保存先が1つでも見えないときは対象を1本も出さない(``unavailable_dirs``)。見えない
    rootは空に見えるので、そのまま計画を組めば「向こうには何も無い」と読んで全部を移送対象に
    してしまう。
    """
    plan: list = []
    total_bytes = 0
    skipped_missing = 0
    skipped_bytes_unknown = 0
    enabled = _relocation_enabled()
    final_dirs = _final_dirs()
    unavailable = _unavailable_final_dirs()
    ready = enabled and not unavailable
    # 所在の内訳(どちらの保存先に何本あるか)はDBのbytesで出し、fileのstatは取らない。
    # 完了録画は数千本あり、画面を開くたび全件statすると容量画面が数秒待たされる。実測が
    # 要るのは移動対象(作業先の取り残し)だけで、そちらは下で実sizeを測る。
    locations = {key: {"items": 0, "bytes": 0, "unknown_bytes": 0}
                 for key in ("work", "final", "outside")}

    for row in runtime.storage.completed_recordings_with_paths():
        src = Path(row["path"])
        under_work = _is_under(src, runtime.RECORD_DIR)
        if under_work:
            where = "work"
        elif any(_is_under(src, root) for root in final_dirs):
            # どの系統に在っても「最終保存先に在る」で1件。2系統は同じ内容なので、系統ごとに
            # 数え上げると完了録画の総本数が実体の2倍を名乗ることになる。
            where = "final"
        else:
            # record root の外を指す行。移動もretentionも触らないので、内訳では別に数える。
            where = "outside"
        bucket = locations[where]
        bucket["items"] += 1
        if row["bytes"]:
            bucket["bytes"] += int(row["bytes"])
        else:
            # bytes未記録の行。0として足すと内訳が実態より小さく見えるので件数で断る。
            bucket["unknown_bytes"] += 1
        if not ready or not under_work:
            continue
        stem = Path(row["filename"]).stem
        try:
            size = src.stat().st_size
        except OSError:
            size = 0
        if not size:
            # mp4が無くても素材(.ts)が在れば移す対象である。見るのは**作業先の**session dir
            # だけで、両rootを見る ``_recording_media_dirs`` は使わない(素材が既に最終保存先に
            # 在る録画まで対象に混ざる)。素材だけの録画のsizeはDBのbytesで出す: session dirは
            # 束ね前で数千fileあり、候補ぶん走査すると容量画面が待たされる(所在の内訳をDB値で
            # 出しているのと同じ理由)。
            media_dir = layout.session_dir(runtime.RECORD_DIR, stem)
            if not api_files._has_usable_media(media_dir):
                # mp4も素材も無い(retention削除など)。移すものが無いので数えない。
                skipped_missing += 1
                continue
            size = int(row["bytes"] or 0)
            if not size:
                # bytesを持たない行だけは実測する。0のまま出すと移送量が桁で狂う(実測:
                # bytes未記録の5本に2.7〜4.4時間の録画が混じっていた)。走査するのはこの
                # 数本だけなので、候補ぶん走査するのとは費用が違う。
                size = api_files._dir_usage(media_dir)[0]
        dsts = [layout.mp4_path(root, stem) for root in final_dirs]
        if any(dst.exists() or layout.has_media(layout.session_dir(root, stem))
               for root, dst in zip(final_dirs, dsts)):
            # 退避先に同名が既に居る。上書きすると既に退避済みの実体を壊すので触らない
            # (素材だけの録画では衝突するのはmp4ではなくsession dirの方である)。
            skipped_bytes_unknown += 1
            continue
        plan.append({
            "recording_id": row["id"],
            "unique_id": row["unique_id"],
            "filename": row["filename"],
            "src": str(src),
            # dst は代表1つ(画面と既存の呼び出し互換)。実際に書くのは dsts の全部である。
            "dst": str(dsts[0]),
            "dsts": [str(dst) for dst in dsts],
            "bytes": size,
            "started_at": row["started_at"],
        })
        total_bytes += size

    by_streamer: dict = {}
    for item in plan:
        entry = by_streamer.setdefault(
            item["unique_id"], {"unique_id": item["unique_id"], "items": 0, "bytes": 0})
        entry["items"] += 1
        entry["bytes"] += item["bytes"]
    # 切り出しは録画に随伴する。今回移す録画のぶんも含めて数えないと、dry-runの量と実際に
    # 動く量が食い違う(録画を移した直後に、その録画の成果物も移動対象になるため)。
    clip_items, clip_orphans = _clip_relocation_items({Path(i["src"]).stem for i in plan})
    return {
        "enabled": enabled,
        "items": plan,
        "total_items": len(plan),
        "total_bytes": total_bytes,
        "clip_items": clip_items,
        "clip_total_items": sum(item["count"] for item in clip_items),
        "clip_total_bytes": sum(item["bytes"] for item in clip_items),
        "clip_orphans": clip_orphans,
        "skipped_missing": skipped_missing,
        "skipped_existing_at_destination": skipped_bytes_unknown,
        "by_streamer": sorted(by_streamer.values(), key=lambda e: -e["bytes"]),
        "locations": locations,
        "record_dir": str(runtime.RECORD_DIR),
        # final_dir は代表1つ(既存の画面が読んでいるkey)。書き込む先の全部は final_dirs。
        "final_dir": str(runtime.FINAL_DIR),
        "final_dirs": [str(root) for root in final_dirs],
        "unavailable_dirs": [str(root) for root in unavailable],
    }


# ---- 切り出し成果物の随伴 ----------------------------------------------------------
# 切り出し・reel・作品・スクショは常に一時保存先へ出る(``layout.clip_output_dir``)。
# 最終保存先へ運ぶ口はここ1つで、録画の移動と同じ操作にぶら下げる: その録画が最終保存先に
# 在るなら、そこから作った成果物も同じ側へ置く。録画より先に成果物だけが移ることはない。

def _match_clip_owner(name: str, stems) -> Optional[tuple]:
    """成果物のfile名から持ち主の録画を当てる。当たらなければ None。

    名前の解析はしない。切り出しの名前は種別(clip/reel/work/still)ごとに続きが違うが、
    **必ず録画のstemで始まる**という一点だけは全種別で共通で、作品が横に置くJSONにも同じ
    規約が効く。種別ごとの規則を持ち込むと、種別が増えるたびに移動から漏れるfileが出る。
    """
    if not stems:
        return None
    for stem, info in stems.items():
        if name.startswith(stem):
            return stem, info
    return None


def _clip_relocation_items(pending_final_stems=()) -> tuple:
    """一時保存先の置き場(``_clips``/``_screenshots``)に在る成果物のうち、最終保存先へ運ぶ
    ものを録画ごとに束ねる。

    戻り値は ``(items, orphan_files)``。``pending_final_stems`` は同じ計画でこれから最終保存先へ
    移る録画で、dry-runが「録画を移したあとに続けて動く量」まで出せるように受け取る(実行側は
    録画を先に移し終えてから、その時点のDBで引き直す)。

    持ち主が分からないfileは動かさずに数だけ返す。録画の行が消えても成果物は実在するので
    (切り出しはretentionにも録画削除にも載らない)、当てずっぽうで最終保存先へ送らない。
    """
    if not _relocation_ready():
        return [], 0
    final_dirs = _final_dirs()
    owners: dict = {}
    for row in runtime.storage.completed_recordings_with_paths():
        stem = Path(row["filename"] or "").stem
        if not stem:
            # file名を持たない行。空のstemは名前の先頭一致で**全部の成果物に当たる**ため、
            # 1行あるだけで一時保存先の成果物が丸ごとその録画の持ち物になる。
            continue
        owners.setdefault(row["unique_id"] or "", {})[stem] = {
            "recording_id": row["id"],
            "unique_id": row["unique_id"],
            "to_final": (any(_is_under(Path(row["path"]), root) for root in final_dirs)
                         or stem in pending_final_stems),
        }
    flat = {stem: info for bucket in owners.values() for stem, info in bucket.items()}

    base = Path(runtime.RECORD_DIR)
    groups: dict = {}
    orphans = 0
    for path in layout.iter_clip_files(runtime.RECORD_DIR):
        # 相対はrootから採る(``<配信者>/_clips/<file名>``・``<配信者>/_screenshots/<file名>``)。
        # 最終保存先の**同じ相対位置**へ置けば、配信者folderの下という置き場の規約も、動画と
        # 静止画を分ける規約も、そのまま向こう側でも成り立つ。
        rel = path.relative_to(base)
        # 置き場は配信者別なので、dir名で候補を絞ってから当てる。当たらないときだけ全件を
        # 見る(配信者名を変えた・置き場が読めない旧い成果物のため)。
        bucket = owners.get(layout.clip_streamer_of(base, path) or "")
        found = _match_clip_owner(path.name, bucket) or _match_clip_owner(path.name, flat)
        if found is None:
            orphans += 1
            continue
        stem, info = found
        if not info["to_final"]:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        group = groups.setdefault(stem, {
            "stem": stem, "recording_id": info["recording_id"],
            "unique_id": info["unique_id"], "files": [], "bytes": 0,
        })
        group["files"].append(rel.as_posix())
        group["bytes"] += size
    items = sorted(groups.values(), key=lambda g: (g["unique_id"] or "", g["stem"]))
    for group in items:
        group["count"] = len(group["files"])
    return items, orphans


def _relocate_clip_group(item: dict) -> tuple:
    """1録画ぶんの成果物を最終保存先の**同じ相対位置**へ移す。

    戻り値は ``(移せた本数, 移したbytes, 失敗の理由list)``。1本の失敗で残りを諦めない
    (録画本体と違い、成果物どうしは互いに依存しない)。

    最終保存先が2系統あるときは、1本ごとに**全系統へ複製してから元を消す**。録画本体と同じ
    順序で、理由も同じである(途中で失敗しても元が残っている)。全系統へ書けなかった1本は、
    書けた側を消して元を残す —— 成果物はDBに行を持たず台帳がfile systemだけなので、片系統
    だけに在る1本は誰も居場所を辿れない。
    """
    src_base = Path(runtime.RECORD_DIR)
    dst_bases = _final_dirs()
    moved = 0
    moved_bytes = 0
    errors: list = []
    for rel in item["files"]:
        src = src_base / rel
        dsts = [base / rel for base in dst_bases]
        if not src.is_file():
            # 走査から実行までの間に消えた(利用者が一覧から削除した)。失敗ではない。
            continue
        if any(dst.exists() for dst in dsts):
            errors.append(f"{Path(rel).name}: 移動先に同名のfileがあります")
            continue
        try:
            size = src.stat().st_size
            if len(dsts) == 1:
                # 1系統だけの構成は今までどおりのmove。同一volume内なら実体を書き直さない。
                dsts[0].parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dsts[0]))
            else:
                written: list = []
                try:
                    for dst in dsts:
                        written.append(dst)
                        mirror.copy_file(src, dst)
                except OSError:
                    mirror.undo(written)
                    raise
                src.unlink()
        except OSError as exc:
            runtime.logger.warning(
                "切り出し %s を最終保存先へ移せませんでした", rel,
                extra={"event": "clip.relocation_failed",
                       "ctx": {"recording_id": item["recording_id"], "src": str(src),
                               "dsts": [str(dst) for dst in dsts]}},
                exc_info=True,
            )
            errors.append(f"{Path(rel).name}: {exc}")
            continue
        moved += 1
        moved_bytes += size
    return moved, moved_bytes, errors


def _mirror_recording(src: Path, dsts: list) -> None:
    """1本を全系統へ複製し、全部が揃ってから元を消す。失敗はOSErrorで送出する。

    途中で失敗したら、それまでに書けた系統も消す。片系統だけに実体が在る状態を作らないという
    一点のためだけの処理で、元はまだ消していないので消して失う物は無い。巻き戻しにも失敗した
    ときは、残ったpathを添えて例外にする —— 自動で片付けられない食い違いは、人が知らなければ
    次の障害まで残る。
    """
    done: list = []
    for dst in dsts:
        try:
            mirror.copy_recording_files(src, dst)
        except OSError as exc:
            stuck: list = []
            for written in done:
                _removed, remains = mirror.remove_recording_files(written)
                stuck.extend(remains)
            if stuck:
                raise OSError(
                    "{error}（巻き戻せなかったfileが残っています: {paths}）".format(
                        error=exc, paths="、".join(str(path) for path in stuck[:3]))
                ) from exc
            raise
        done.append(dst)
    mirror.remove_recording_files(src)


def _relocate_one(item: dict) -> Optional[str]:
    """1本を退避する。成功でNone、失敗で理由の文字列。

    status='recording' への再確認はここでは行わない(呼び出し側が実行直前に見る)。
    移送に成功したときだけDBのpathを書き換える。順序が逆だと、移送に失敗した録画のpathが
    存在しないfileを指す。

    最終保存先が**1系統**のときは今までどおり ``Recorder._move_recording_files`` のmoveで、
    挙動は1bitも変えない(同一volumeならrenameで済む経路をcopyへ置き換える理由が無い)。

    **2系統**のときは「全系統へ複製 → 検証 → 元を消す」の順で行う(``tictok.record.mirror``)。
    1系統目へmoveしてから2系統目へcopyする形にしないのは、2系統目で失敗した時点で元がもう
    無く、片系統だけが実体を持つ状態が確定してしまうためである。

    **片方にでも書けなければ、既に書けた側を消して移送そのものを無かったことにする。** 元は
    まだ手元に在るので、消して失うdataは無い —— 消さずに残す方が危険で、その1本だけが片系統に
    在る状態は、次にそのdiskが壊れたときまで誰も気付かない。巻き戻しにも失敗した場合だけ、
    残ったpathを理由の文字列に載せて人へ渡す(自動で片付けられない以上、黙って成功を名乗る
    わけにはいかない)。
    """
    src = Path(item["src"])
    dsts = [Path(path) for path in item["dsts"]]
    # mp4は録画の身元で、実在するとは限らない(finalizeはもう作らない)。移す実体は素材の
    # session dirなので、在るかどうかは両方で見る。
    if not src.is_file() and not layout.has_media(
            layout.session_dir(layout.record_root_of(src), src.stem)):
        return "移送元が見つかりません"
    for dst in dsts:
        if dst.exists() or layout.has_media(
                layout.session_dir(layout.record_root_of(dst), dst.stem)):
            return "退避先に同名のfileが既にあります"
    try:
        if len(dsts) == 1:
            Recorder._move_recording_files(src, dsts[0])
        else:
            _mirror_recording(src, dsts)
    except OSError as exc:
        # working dirに残す。working dirも許可されたrecord rootなので再生も出力も続く。
        runtime.logger.warning(
            "%s の移送に失敗したため %s に残しました", item["filename"], src,
            extra={"event": "recording.manual_relocation_failed",
                   "ctx": {"recording_id": item["recording_id"], "path": str(src),
                           "dsts": [str(dst) for dst in dsts],
                           "size_bytes": item["bytes"]}},
            exc_info=True,
        )
        return str(exc)
    dst = dsts[0]
    if not runtime.storage.update_recording_path(item["recording_id"], str(dst)):
        # 行が消えている(session削除と競合)。fileは既に移動済みなので位置だけ記録に残す。
        runtime.logger.warning(
            "%s を移送しましたがrecordingの行が消えています（fileの位置: %s）",
            item["filename"], dst,
            extra={"event": "recording.manual_relocation_orphaned",
                   "ctx": {"recording_id": item["recording_id"], "path": str(dst)}},
        )
    return None


def _run_relocation(plan: dict, on_item=None) -> dict:
    """planを順に移送する。1本の失敗で全体を止めない。

    1本がlockされているだけで残り全部を諦めるのは、この機能の目的(取り残しを減らす)に
    反する。失敗は数えて報告し、次へ進む。

    録画を全部運んでから切り出しを運ぶ。順序が逆だと、これから移す録画の成果物だけが先に
    最終保存先へ着き、録画の移送が失敗した場合に成果物と録画が別のdriveへ分かれる。
    """
    moved = 0
    moved_bytes = 0
    failures: list = []
    total = len(plan["items"]) + len(plan.get("clip_items") or [])
    for index, item in enumerate(plan["items"]):
        cancel.check_cancelled()
        if on_item is not None:
            on_item(index, total, item)
        # 実行直前に status を見る。dry-run から実行までの間に録画が始まった録画IDを
        # 掴んでいた場合、書き込み中のfileを動かすことになる。
        current = runtime.storage.get_recording(item["recording_id"])
        if current is None or current["status"] != "completed":
            failures.append({"filename": item["filename"], "reason": "状態が変わりました"})
            continue
        # 素材(.ts)ごと動かすので、その素材を読み書きしている処理が居る間は触らない。
        # 移送は元を消す片道の操作で、読み手の足元を抜くと双方が壊れる。
        if is_finalizing(item["recording_id"]):
            failures.append({"filename": item["filename"], "reason": "確定処理中です"})
            continue
        if item["recording_id"] in {rid for _kind, rid in runtime.storage.pending_media_job_keys()}:
            failures.append({"filename": item["filename"], "reason": "他の処理が使用中です"})
            continue
        error = _relocate_one(item)
        if error is None:
            moved += 1
            moved_bytes += item["bytes"]
        else:
            failures.append({"filename": item["filename"], "reason": error})

    # 成果物は録画を運び終えた時点のDBで引き直す。計画時の一覧をそのまま使うと、移送に失敗
    # して一時保存先に残った録画の成果物まで最終保存先へ送ることになる。
    clip_items, _orphans = _clip_relocation_items()
    clips_moved = 0
    clips_moved_bytes = 0
    busy = {rid for _kind, rid in runtime.storage.pending_media_job_keys()}
    for offset, item in enumerate(clip_items):
        cancel.check_cancelled()
        label = f"{item['stem']} の切り出し {item['count']}本"
        if on_item is not None:
            on_item(len(plan["items"]) + offset, total, {"filename": label})
        if item["recording_id"] in busy:
            # 出力中のfileを動かすと、書いている側が「移動元が消えた」で落ちる。
            failures.append({"filename": label, "reason": "他の処理が使用中です"})
            continue
        count, size, errors = _relocate_clip_group(item)
        clips_moved += count
        clips_moved_bytes += size
        for reason in errors:
            failures.append({"filename": item["stem"], "reason": reason})

    if on_item is not None:
        on_item(total, total, None)
    return {"moved": moved, "moved_bytes": moved_bytes, "failures": failures,
            "clips_moved": clips_moved, "clips_moved_bytes": clips_moved_bytes}


def _relocation_summary() -> dict:
    """容量画面へ常時出す所在の内訳と取り残しの要約。録画の一覧は含めない。"""
    plan = _relocation_plan()
    return {
        "enabled": plan["enabled"],
        "items": plan["total_items"],
        "bytes": plan["total_bytes"],
        # 録画が0本でも成果物だけが残ることがある(録画を移した後に切り出した分)。件数を
        # 出さないと、移すものが在るのに「移していない録画はありません」だけが並ぶ。
        "clip_items": plan["clip_total_items"],
        "clip_bytes": plan["clip_total_bytes"],
        "locations": plan["locations"],
        "skipped_missing": plan["skipped_missing"],
        "skipped_existing_at_destination": plan["skipped_existing_at_destination"],
        "record_dir": plan["record_dir"],
        "final_dir": plan["final_dir"],
        "final_dirs": plan["final_dirs"],
        # 見えていない系統は容量画面へ常時出す。「移していない録画は0本」と「移せる状態に
        # ない」は同じ表示になってはならない(前者は片付いている、後者は止まっている)。
        "unavailable_dirs": plan["unavailable_dirs"],
    }


# ---- 最終保存先の再同期 ------------------------------------------------------------
# 2系統は相互mirrorなので、片方にしか無いfileは「まだ揃っていない」状態である。移送は必ず
# 全系統へ書くので新しく増えることはないが、2系統目を後から設定したとき・片系統が外れている
# 間に何かが書かれたときは揃っていない。それを埋めるのがここである。
#
# 行うのはcopyだけで、元は消さない。移送(relocate)は一時保存先を空けるための片道の操作だが、
# 再同期は両系統を同じにするための操作で、消してよいfileは1つも無い。
#
# 同名でsizeが違うfileは**触らない**。どちらが正しいかはここでは決められず(新しい方が正しい
# とは限らない —— 途中で切れた書き込みの方が新しいこともある)、上書きは取り返しがつかない。

# 応答へ載せる明細の上限。初回の再同期では片系統が丸ごと欠けており、明細は実測(2026-09-02)の
# 12,340 file をdir単位に束ねた件数になる。件数(total_items)は常に実数を返し、明細だけを畳む。
_MIRROR_REPORT_LIMIT = 200

# 突き合わせた結果を**確かめた時刻とともに**残すkey。走査は両rootの全dirを辿るので画面を
# 開くたびには回せず、残さなければ「最後に揃っていると確かめたのはいつか」に誰も答えられない
# —— 二重化が効いているかは、空き容量ではなくその1点でしか読めない。
#
# 置き場が ``db_maintenance`` なのは、失っても困らない記録だからである(失えば次に突き合わせる
# までの間「未確認」に戻るだけで、実体は1byteも変わらない)。
_MIRROR_CHECK_KEY = "mirror_compare_result"


def _store_mirror_check(report: dict) -> None:
    """実際に走査した回の要約を残す。明細は残さない —— 後から効くのは件数と時刻だけで、
    file名の一覧は次の走査で作り直せる。

    欠けている件数は**系統ごと**に分けて残す。合計だけでは「どちらのdriveに無いのか」が
    読めず、片方だけが古い状態(二重化が実際に破れている唯一の形)を人が名指しできない。"""
    by_dst: dict = {}
    for group in report["items"]:
        entry = by_dst.setdefault(group["dst"], {"count": 0, "bytes": 0})
        entry["count"] += group["count"]
        entry["bytes"] += group["bytes"]
    runtime.storage.set_maintenance_value(_MIRROR_CHECK_KEY, json.dumps({
        "at": time.time(),
        "final_dirs": list(report["final_dirs"]),
        "missing_items": report["total_items"],
        "missing_bytes": report["total_bytes"],
        "missing_by_dst": by_dst,
        "diverged": report["diverged_count"],
        "errors": len(report["errors"]),
        "stale": False,
    }, ensure_ascii=False))


def invalidate_mirror_check() -> None:
    """再同期でfileを書いた後、残っている要約は**実行前の姿**になる。

    0件へ書き換えない —— 複製に失敗した分まで「揃った」と読ませることになる。取り直すには
    全走査をもう一度回すしかないので、消さずに古いと名乗らせる(``_mirror_report`` の
    ``current`` と同じ考え方)。"""
    raw = runtime.storage.get_maintenance_value(_MIRROR_CHECK_KEY)
    if not raw:
        return
    try:
        saved = json.loads(raw)
    except ValueError:
        return
    saved["stale"] = True
    runtime.storage.set_maintenance_value(_MIRROR_CHECK_KEY, json.dumps(saved, ensure_ascii=False))


def mirror_check_status() -> dict:
    """最後に突き合わせた結果。一度も走っていなければ ``at`` は None。

    今の系統と違う組み合わせで採った結果は捨てる。別の2 driveについての答えを「最後に
    確かめた日」として出すと、設定を変えた日から誰も確かめていないことが隠れる。"""
    dirs = [str(root) for root in _final_dirs()]
    blank = {"at": None, "final_dirs": dirs, "missing_items": 0, "missing_bytes": 0,
             "missing_by_dst": {}, "diverged": 0, "errors": 0, "stale": False,
             "enabled": _mirror_enabled()}
    raw = runtime.storage.get_maintenance_value(_MIRROR_CHECK_KEY)
    if not raw:
        return blank
    try:
        saved = json.loads(raw)
    except ValueError:
        return blank
    if not isinstance(saved, dict) or list(saved.get("final_dirs") or []) != dirs:
        return blank
    return {**blank, **saved, "enabled": _mirror_enabled()}


def _mirror_plan() -> dict:
    """2系統の最終保存先を突き合わせた結果(dry-run)。実行は ``_run_mirror_resync``。

    突き合わせは両rootの全dirを辿る走査である(``/api/storage/scan`` と同じ性質のblocking
    I/O)。DBには二次保存先に何が在るかの台帳が無いので、実体を見る以外に答えを出す方法は無い。
    読むのはmetadataだけ(比べるのはsizeである)なので費用はfile数に比例し、実測(2026-09-02)で
    ``K:\\80_Tiktok`` は 12,340 file —— 複製そのもの(同じ実測で0.59TB)とは桁が違う。

    最終保存先が1つでも見えないときは走査そのものを行わない。見えないrootは空に見えるため、
    そのまま突き合わせれば「向こうには何も無い」と読んで、最終保存先の中身を丸ごと
    (12,340 file / 0.59TB)複製する計画を出すことになる。
    """
    dirs = _final_dirs()
    unavailable = _unavailable_final_dirs()
    base = {
        "enabled": _mirror_enabled(),
        "final_dirs": [str(root) for root in dirs],
        "unavailable_dirs": [str(root) for root in unavailable],
        "items": [], "total_items": 0, "total_bytes": 0,
        "diverged": [], "diverged_count": 0, "errors": [],
    }
    if not base["enabled"] or unavailable:
        return base
    diff = mirror.compare_roots(dirs)
    report = {
        **base,
        "items": diff["groups"],
        "total_items": sum(group["count"] for group in diff["groups"]),
        "total_bytes": sum(group["bytes"] for group in diff["groups"]),
        "diverged": diff["diverged"],
        "diverged_count": len(diff["diverged"]),
        "errors": diff["errors"],
    }
    # 走査を回した回だけ残す。系統が見えない・2系統でないときの ``base`` を残すと、
    # 突き合わせていないことが「揃っている」として記録に残る。
    _store_mirror_check(report)
    return report


def _mirror_report(plan: dict, current: bool) -> dict:
    """planをAPI応答の形へ畳む。実行に使うfile名の一覧は落とし、件数と先頭だけを返す。

    file名の一覧をそのまま返すと、初回の再同期(片方が空)の応答には最終保存先のfileがそのまま
    並ぶ(実測2026-09-02で12,340 file)。畳むのは明細だけで、件数・容量は実数のままにする
    (そこを丸めると、操作の規模を人が見誤る)。

    ``current`` は「この突き合わせが今の状態か」である。**再同期の実行後に返すplanは実行前に
    採ったもの**で(取り直すには全走査をもう一度回すことになる)、そのまま「残り」として描くと、
    複製し終えた直後の画面が実行前の件数を「まだ残っている」と名乗る。逆に0件を「揃った」と
    読むのも同じ誤りなので、現在の状態かどうかは応答自身が名乗る。
    """
    return {
        **plan,
        "items": [{key: value for key, value in group.items() if key != "files"}
                  for group in plan["items"][:_MIRROR_REPORT_LIMIT]],
        "listed_items": min(len(plan["items"]), _MIRROR_REPORT_LIMIT),
        "group_count": len(plan["items"]),
        "diverged": plan["diverged"][:_MIRROR_REPORT_LIMIT],
        "current": current,
    }


def _run_mirror_resync(plan: dict, on_item=None) -> dict:
    """planに沿って、欠けている側へfileを複製する。1件の失敗で全体を止めない。

    1 fileがlockされているだけで残りを諦めるのは、この機能の目的(2系統を揃える)に反する。
    失敗は数えて報告し、次へ進む。

    走査から実行までの間に埋まったfile(別経路の移送など)は飛ばす。**既に在るfileは決して
    上書きしない** —— 同名でsizeが違うなら、それは人の判断を待つべき食い違いである。
    """
    copied = 0
    copied_bytes = 0
    failures: list = []
    total = len(plan["items"])
    for index, group in enumerate(plan["items"]):
        cancel.check_cancelled()
        if on_item is not None:
            on_item(index, total, group)
        rel = group["rel"]
        src_dir = Path(group["src"]) / rel if rel else Path(group["src"])
        dst_dir = Path(group["dst"]) / rel if rel else Path(group["dst"])
        for name in group["files"]:
            cancel.check_cancelled()
            src = src_dir / name
            dst = dst_dir / name
            if not src.is_file():
                # 走査から実行までの間に消えた。失敗ではない。
                continue
            if dst.exists():
                continue
            try:
                copied_bytes += mirror.copy_file(src, dst)
            except OSError as exc:
                runtime.logger.warning(
                    "再同期で %s を %s へ複製できませんでした", name, dst_dir,
                    extra={"event": "storage.mirror_copy_failed",
                           "ctx": {"src": str(src), "dst": str(dst)}},
                    exc_info=True,
                )
                failures.append({"filename": f"{rel}/{name}" if rel else name,
                                 "reason": str(exc)})
                continue
            copied += 1
    if on_item is not None:
        on_item(total, total, None)
    return {"copied": copied, "copied_bytes": copied_bytes, "failures": failures,
            "diverged_count": plan["diverged_count"]}


def _retention_rules() -> dict:
    """保持policyの設定値。閾値はすべてSETTING_DEFS側にあり、ここは読み替えのみ。"""
    return {
        "transient_hours": int(runtime.settings.get("retention_transient_hours")),
        "derived_days": int(runtime.settings.get("retention_derived_days")),
        "source_days": int(runtime.settings.get("retention_source_days")),
        "source_enabled": bool(runtime.settings.get("retention_source_enabled")),
    }


def _retention_path(recording: dict) -> Optional[Path]:
    """録画pathをrecord root配下へ解決する。範囲外・不正pathは削除候補にしない。"""
    raw = recording.get("path")
    if not raw:
        return None
    try:
        return api_files._safe_recording_path(raw)
    except HTTPException:
        return None


def _retention_free_target_bytes() -> int:
    return int(runtime.settings.get("retention_free_target_gb")) * 1024 * 1024 * 1024


def _retention_free_reached() -> bool:
    """全volumeが打ち切り目標の空き容量に達したか。目標0(=打ち切らない)は常にFalse。

    読めなかったvolumeは判定へ入れない。空き容量が不明なものを「足りている」とみなすと、
    削除を止めるべき場面で止まらなくなる。"""
    target = _retention_free_target_bytes()
    if target <= 0:
        return False
    report = disk_free_by_volume(_disk_volume_paths())
    if not report:
        return False
    return all(info["free_bytes"] >= target for info in report.values())


def _retention_media_usage(recording: dict) -> dict:
    """この録画の素材(.ts)がdiskに占める実体量。原本phaseの候補にだけ効く。

    dir丸ごとの走査を伴うため、素材を原本と見なした録画に限って呼ぶ(既定OFFの③が有効に
    なったときだけ通る)。"""
    total = files = 0
    newest = 0.0
    for seg_dir in api_files._recording_media_dirs(recording):
        size, count, mtime = api_files._dir_usage(seg_dir)
        total += size
        files += count
        newest = max(newest, mtime)
    return {"bytes": total, "files": files, "mtime": newest}


def _build_retention_plan() -> dict:
    recordings = runtime.storage.recordings_for_retention()
    # 素材の有無は録画ごとにdirを叩くと重い(数千本)。一括画面と同じ、配信者ごとのts/を1回
    # scandirする経路で先に埋め、判定そのものは _bulk_classify(delete_mp4) と同じ事実を使う。
    facts_by_id = fsfacts._bulk_fs_facts_batch(recordings)
    fsfacts._bulk_hls_batch(recordings, facts_by_id)

    def has_media(recording: dict) -> bool:
        facts = facts_by_id.get(recording["id"])
        return bool(facts and facts.get("has_hls"))

    plan = retention.build_plan(
        recordings, runtime._RECORD_ROOTS, _retention_path, _retention_rules(), time.time(),
        has_media=has_media, media_usage=_retention_media_usage,
    )
    plan["rules"] = _retention_rules()
    plan["free_target_bytes"] = _retention_free_target_bytes()
    plan["protected_count"] = sum(1 for rec in recordings if rec.get("protected"))
    return plan


def _delete_transient_item(item: dict) -> int:
    """中断したrenderの残骸を1件削除し、解放bytesを返す。個々の失敗は握り潰さずlogへ残す。"""
    path = Path(item["path"])
    try:
        path.unlink(missing_ok=True)
    except OSError:
        runtime.logger.warning(
            "孤児になったrenderの中間file %s を削除できません", path.name,
            extra={"event": "retention.remove_failed",
                   "ctx": {"path": str(path), "phase": retention.PHASE_TRANSIENT}},
            exc_info=True,
        )
        return 0
    return int(item["bytes"])


def _delete_derived_item(item: dict) -> int:
    """1録画分の派生物(焼き込み・Up出力)を、削除endpointと同じcleanup関数で消す。

    素材(.ts)が残る録画ではmp4本体も派生物なので、一括削除(delete-mp4)と同じ
    ``_delete_source_mp4`` で消す。**planを組んだ時点の判定は使わず、消す直前にもう一度
    素材を確かめる** — その間に素材が消えていれば、そのmp4はもう最後の1本である。job が
    掴んでいる録画を外すのも一括削除と同じ理由で、走っているffmpegの入力を抜くことになる。"""
    src = Path(item["path"])
    freed = int(item["bytes"])
    cleanup_overlay_files(src)
    cleanup_upscale_files(src)
    if not item.get("includes_source"):
        return freed
    source_bytes = int(item.get("source_bytes") or 0)
    recording = runtime.storage.get_recording(item["recording_id"])
    reason = ""
    if recording is None:
        reason = "gone"
    elif not api_files._recording_media_dirs(recording):
        reason = "no_media"
    elif item["recording_id"] in runtime.storage.busy_recording_ids():
        reason = "busy"
    else:
        _, reason = api_files._delete_source_mp4(recording)
    if reason:
        runtime.logger.warning(
            "自動削除でrecording %s のmp4を残しました: %s",
            item["recording_id"], reason,
            extra={"event": "retention.source_kept",
                   "ctx": {"recording_id": item["recording_id"], "path": item["path"],
                           "reason": reason, "phase": retention.PHASE_DERIVED}},
        )
        return freed - source_bytes
    return freed


def _delete_source_item(item: dict) -> int:
    """再取得不能な原本を消し、録画行も落とす(単体削除endpointと同じ後始末)。

    素材(.ts)が残る録画では原本は素材の方なので、mp4と派生物に加えて素材dirも消す。
    ここまで来た時点でこの録画は復元手段を持たなくなる — ②までと違い、実行は設定の明示的な
    有効化とoperatorの確認を経たときだけである。"""
    recording = runtime.storage.get_recording(item["recording_id"])
    if recording is None:
        return 0
    api_files._remove_recording_files(recording)
    if item.get("media"):
        api_files._remove_recording_ts(recording)
    runtime.storage.delete_recording(item["recording_id"])
    return int(item["bytes"])


_RETENTION_DELETERS = {
    retention.PHASE_TRANSIENT: _delete_transient_item,
    retention.PHASE_DERIVED: _delete_derived_item,
    retention.PHASE_SOURCE: _delete_source_item,
}


def _apply_retention(plan: dict, on_item=None) -> dict:
    """planを実行順(transient -> derived -> source)に消す。打ち切り目標に達したら停止する。

    実行のたびにfileが消えて空きが増えるので、目標判定はphaseの区切りで測り直す。

    ``on_item(phase, done, total)`` は同期callback(この関数自体がto_threadの中で回る)。
    以前はjob行を作るだけで進捗を一度も報告せず、画面に永久に0%の行が残っていた。"""
    removed = {phase: {"items": 0, "bytes": 0} for phase in retention.PHASE_ORDER}
    stopped = ""
    for phase in plan["phases"]:
        key = phase["phase"]
        if not phase["enabled"]:
            continue
        deleter = _RETENTION_DELETERS[key]
        total = len(phase["items"])
        for index, item in enumerate(phase["items"]):
            if on_item is not None:
                on_item(key, index, total)
            if _retention_free_reached():
                stopped = key
                break
            freed = deleter(item)
            if freed:
                removed[key]["items"] += 1
                removed[key]["bytes"] += freed
        if on_item is not None:
            on_item(key, total, total)
        if stopped:
            break
    return {"removed": removed, "stopped_at": stopped,
            "freed_bytes": sum(entry["bytes"] for entry in removed.values()),
            "removed_items": sum(entry["items"] for entry in removed.values())}
