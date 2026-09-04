"""設定値を、DBの外の**人が読めるfile**として各保存先へ退避する。

設定値は ``settings`` 表にしか無い。DBを失うと録画の台帳と一緒に設定値も消え、復旧した人は
「どの保存先を使っていたか」「録画の間隔をいくつにしていたか」を思い出すところから始めること
になる。DBの退避(``core/dbmaint.py``)はDB本体の複製なので、SQLiteを開ける環境が無ければ中身を
読むことすらできない。ここが作るのはそれとは別物で、**DBが無くても・このserverが無くても
読めるJSON 1枚**である。置き場はrecordの保存先そのものなので、録画が入ったdriveを1台拾えば
その時点の設定値も一緒に手元にある。

書き出す先は一次保存先(work root)と二次保存先(final root)の**全部**で、それぞれの直下の
:data:`tictok.core.layout.CONFIG_DIRNAME` の中へ置く。

**書けない保存先があっても、書ける保存先には書く。** これは録画の移送(``tictok.api.disk``)が
「両方へ書けたときだけ移動する」としているのと逆の判断である。移送は元を消す操作なので、片系統
だけが最新という状態を作ると次の障害でdataを失う。こちらは元(DBのsettings表)を消さない写しで、
かつfileには時刻が入っている —— 2台のdriveの世代が食い違っていても、読む人は新しい方を採れば
よいだけで、害が無い。むしろ「1台が繋がっていないから、繋がっている台にも設定値を残さない」方が
失うものが大きい。書けなかった保存先は運用log(``backup.settings_export_failed``)と戻り値の
``failed`` で名乗る。

**``.env`` の中身は書かない。** .env には署名serverのAPI keyのような秘密が入っており、ここは
複数のdriveへ平文を撒く経路である。DBを失った人が知りたいのは「どのkeyを設定し直す必要が
あるか」であって値そのものではないので、**key名だけ**を ``dotenv_keys`` に載せる(値は書かない)。

世代は上書きせずに積む。この機能の目的は「設定を誤って変えたときに前の値へ戻せること」なので、
最新1枚だけでは誤った値で上書きされて終わる。ただし**中身が前回と同じなら新しい世代を作らない**
—— server再起動のたびに同じ内容の世代が積み上がると、``KEEP_GENERATIONS`` 枚の窓が数日で
埋まり、戻したい過去の値が押し出される。

書き込みは ``.partial`` へ書いてから rename する(``core/dbmaint.py`` と同じ流儀)。最終名で
在るfileは必ず書き切れたfileで、途中で落ちた回の残骸を「読める設定値」として掴むことはない。

世代の置き方(命名・並べ方・同じ内容なら作らない・刈り取り・partial→rename)は
``prefix`` で切り替えられるようにしてある。手入力データの退避(``core/tables_export``)が同じ
``_config/`` へ ``tables-<時刻>.json`` を置くのに使う ―― 置き方が2通りあると、driveを
拾った人が「どちらのfile名が新しいか」を2つの規則で読むことになる。
"""
import hashlib
import json
import logging
import os
import platform
import re
import socket
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from tictok.core import config, layout
from tictok.core.settings import SETTING_DEFS, Settings
from tictok.storage import OPS_ERROR, OPS_WARNING

logger = logging.getLogger("tictok.settings_export")

_EXPORT_PREFIX = "settings"
_EXPORT_SUFFIX = ".json"
_PARTIAL_SUFFIX = ".partial"
_STAMP_FORMAT = "%Y%m%d-%H%M%S"
_NAME_PATTERNS: dict = {}


def _name_pattern(prefix: str):
    """``<prefix>-<時刻>[-連番].json`` に合う正規表現(prefixごとに1つ)。"""
    pattern = _NAME_PATTERNS.get(prefix)
    if pattern is None:
        pattern = re.compile(
            rf"^{re.escape(prefix)}-(?P<stamp>\d{{8}}-\d{{6}})(?:-(?P<seq>\d+))?"
            rf"{re.escape(_EXPORT_SUFFIX)}$")
        _NAME_PATTERNS[prefix] = pattern
    return pattern

# 残す世代の数。1枚は数十KBなので容量ではなく「どこまで遡れるか」で決める。設定を誤って
# 変えたことに気付くまでには日数がかかる種類の事故なので、同じ内容の世代を作らない規則と
# 合わせて、この枚数はそのまま「設定を変えた回数」ぶん遡れることを意味する。
KEEP_GENERATIONS = 30


class SettingsExportError(RuntimeError):
    """退避の材料が揃わなかった。書き出し先の失敗はこれではなく戻り値の ``failed`` で表す。

    materialが無い(=settings表を読めない)場合だけ例外にする。書き出す中身が存在しないので、
    どの保存先へ何を書くかを決められない。"""


def _stored_settings(db_path) -> dict:
    """``settings`` 表に**実際に保存されている生の値**。

    実行値(``Settings.get``)ではなく生の行を載せるのは、これが復元の材料だからである。
    実行値はSETTING_DEFSのtype/min/maxを通した後の値で、定義が後から変われば同じDBからでも
    別の値になる。表に在った文字列そのものを残しておけば、定義が変わった後でも「operatorが
    何を保存したか」は読める。

    SETTING_DEFSに無いkey(``_migration:<name>`` のmarker等)も落とさずに載せる。表を丸ごと
    写すのが目的で、載せるkeyをこちら側の定義で絞ると、定義から消した設定の値が退避からも
    同時に消える —— 消した判断が誤りだった時に戻す先が無くなる。

    serverのStorageではなく読み取り専用の別connectionで読む(``config._setting_from_db`` と
    同じ流儀)。退避はloop上から呼ばれ得るので、収集が使っているwriter lockを掴まない。"""
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        try:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.error(
            "設定値の退避: settings表を読めません（%s）", db_path,
            extra={"event": "backup.settings_export_failed",
                   "ctx": {"db_path": str(db_path), "reason": str(exc)}},
            exc_info=True,
        )
        raise SettingsExportError(f"settings表を読めません: {db_path} ({exc})") from exc
    return {str(key): str(value) for key, value in rows}


def _value_source(key: str, stored: dict) -> str:
    """その設定の実行値がどこから来たか。``Settings._load`` と同じ順序(DB > env > 既定)。

    値だけを残すと、復元した人は「この値はoperatorが画面で決めたのか、.envがそう言って
    いるだけなのか」を区別できない。前者はDBを戻せば復活するが、後者はDBを戻しても
    .envが無ければ別の値になる。"""
    if key in stored:
        return "db"
    if os.environ.get(SETTING_DEFS[key]["env"]) is not None:
        return "env"
    return "default"


def _snapshot(settings: Settings, db_path, stored: dict) -> dict:
    """退避1世代の中身(時刻とdigestを除いた部分)。

    ``describe()`` をそのまま使わずlabel/noteとdefault系だけを引き継ぐのは、画面用の
    field(step/options/option_image)が復元にも読解にも要らないためである。逆にlabelとnoteは
    必ず載せる —— SETTING_DEFSが将来書き換われば、退避したときにその設定が何を意味していたかは
    このfileにしか残らない。"""
    described = {entry["key"]: entry for entry in settings.describe()}
    items = []
    for key in SETTING_DEFS:
        entry = described[key]
        item = {
            "key": key,
            "value": entry["value"],
            "source": _value_source(key, stored),
            "label": entry["label"],
            "note": entry["note"],
            "category": entry["category"],
            "category_label": entry["category_label"],
            "env": entry["env"],
            "builtin_default": entry["builtin_default"],
        }
        if "invalid" in entry:
            # 起動時に現在の定義へ適合しなかった値。実行値としては走っているので、
            # 「なぜこの値なのか」を読む人のために理由ごと残す。
            item["invalid"] = entry["invalid"]
        items.append(item)
    return {
        "db_path": str(db_path),
        # このprojectはapplication versionを持たない。退避を書いた実行環境を後から名指し
        # できるよう、在る物(machine名とpython)だけを載せる。無い物を作らない。
        "runtime": {
            "host": socket.gethostname(),
            "python": platform.python_version(),
        },
        # key名だけ(値は載せない)。grammarの出所は ``config`` 1箇所で、実際に os.environ へ
        # 流し込む側と同じ解析を通る —— ここで書き直すと、退避が「設定されている」と名乗るkeyと
        # serverが読み込んだkeyが静かにずれる。
        "dotenv_keys": config.dotenv_key_names(),
        "stored": stored,
        "settings": items,
    }


def _digest(snapshot: dict) -> str:
    """世代を作るかどうかの判定に使う内容の指紋。

    退避した時刻はここに含めない。含めると毎回違う指紋になり、「中身が同じなら世代を作らない」
    という規則がそもそも成立しない。"""
    text = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def export_dir(root) -> Path:
    """その保存先の設定値の置き場(``<root>/_config``)。

    folder名は ``layout.CONFIG_DIRNAME`` ただ1つを引く。ここで独自に持つと、片方だけを直した
    ときに容量の内訳(``record.disk_scan``)と削除の対象(``scripts/purge_streamers.py``)が
    食い違い、退避した設定値が配信者folderとして消される。"""
    return Path(root) / layout.CONFIG_DIRNAME


def list_exports(root, prefix: str = _EXPORT_PREFIX) -> list:
    """その保存先に在る世代の一覧。新しい順。

    命名規約に合うfileだけを数える。folderに置かれた他のfileは一覧にも刈り取りにも入れない
    (``dbmaint.list_backups`` と同じ約束)。"""
    directory = export_dir(root)
    if not directory.is_dir():
        return []
    pattern = _name_pattern(prefix)
    found = []
    for path in directory.iterdir():
        match = pattern.match(path.name)
        if match is None or not path.is_file():
            continue
        stat = path.stat()
        # 並べる鍵は時刻と連番に分ける。file名の文字列順では並べられない —— 同じ秒の2枚目は
        # ``-2`` が付き、その ``-`` は ``.json`` の ``.`` より前に来るので、連番なしの1枚目が
        # 最新に化ける。mtimeでも並べない: driveへcopyし直したfileが新しい方へ回り、
        # 「最新の世代」が実際に最後に書かれた設定値と一致しなくなる。
        order = (match.group("stamp"), int(match.group("seq") or 1))
        found.append((order, {
            "name": path.name,
            "path": str(path),
            "bytes": stat.st_size,
            "created_at": stat.st_mtime,
        }))
    found.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in found]


def latest_export(root, prefix: str = _EXPORT_PREFIX):
    """その保存先の最新世代を読む。1つも無ければ None。

    戻り値はfileの中身(``exported_at`` / ``digest`` / ``export``)に、どのfileだったかを
    足したもの。読む人が「いつ・どの保存先の・どのfile」を名乗れないと、driveを跨いで
    見比べたときにどちらを採るか決められない。"""
    items = list_exports(root, prefix)
    if not items:
        return None
    newest = items[0]
    payload = json.loads(Path(newest["path"]).read_text(encoding="utf-8"))
    return {"name": newest["name"], "path": newest["path"],
            "created_at": newest["created_at"], **payload}


def previous_digest(root, prefix: str = _EXPORT_PREFIX, failed_event: str = "backup.settings_export_failed"):
    """最新世代の指紋。世代が無い・読めない場合は None(=新しい世代を作る)。

    読めない世代を例外にしないのは、その1枚が壊れている間ずっと退避が止まるためである。
    黙って握り潰すのではなくwarningを残した上で新しい世代を書く —— 壊れたfileの隣に、
    読める最新の設定値が出来る方が復旧の役に立つ。"""
    try:
        latest = latest_export(root, prefix)
    except (OSError, ValueError) as exc:
        logger.warning(
            "%s の退避: 直前の世代を読めません（%s）。新しい世代を書きます", prefix, root,
            extra={"event": failed_event,
                   "ctx": {"root": str(root), "reason": str(exc)}},
            exc_info=True,
        )
        return None
    return latest.get("digest") if latest else None


def prune(root, prefix: str = _EXPORT_PREFIX, keep=None,
          failed_event: str = "backup.settings_export_failed") -> list:
    """``keep`` (無指定なら :data:`KEEP_GENERATIONS`)を超えた古い世代を消す。消したfile名を返す。"""
    if keep is None:
        keep = KEEP_GENERATIONS
    if keep <= 0:
        return []
    removed = []
    for item in list_exports(root, prefix)[keep:]:
        try:
            Path(item["path"]).unlink()
        except OSError:
            # 古い世代を1枚消せなくても、新しい世代は既に出来ている(``dbmaint.prune_backups``
            # と同じ判断)。退避そのものを失敗扱いにすると、消せないfileが在る間ずっと
            # 設定値が残らなくなる。
            logger.warning(
                "古い退避 %s を削除できませんでした", item["path"],
                extra={"event": failed_event, "ctx": {"path": item["path"]}},
                exc_info=True,
            )
            continue
        removed.append(item["name"])
    return removed


def next_name(roots, prefix: str = _EXPORT_PREFIX) -> str:
    """次の世代のfile名。

    **全ての保存先で同じ名前**にする。driveを跨いで並べたときに、同じ内容の世代が同じ名前で
    並んでいなければ、人は2台の食い違いを名前では見分けられない。

    時刻は秒までなので、同じ秒に内容の違う退避が2回走ると衝突する(設定を続けて保存した時に
    起きる)。連番で避ける —— ここで失敗にすると、operatorから見れば理由の分からない欠落に
    なる(``dbmaint._free_target`` と同じ理由)。

    **``dbmaint._free_target`` の「空いている名前を拾う」実装をここへ真似ると壊れる。**
    揃えたくなるが戻さないこと。こちらは刈り取り(:func:`_prune`)が古い世代を消すので、同じ秒の
    中で連番の若い名前が後から空く。空きを埋めると、最新の内容が最も古い名前を名乗ることになり、
    その直後の刈り取りが「今書いた世代」を最古と見なして消す。再現条件は
    ``KEEP_GENERATIONS=3`` で同一秒に5回で、4回目の刈り取りが連番なしの1枚目を消して名前を
    空け、5回目がそこへ書いて即座に自分を消した(``tests/test_settings_export.py`` の
    ``test_generations_are_pruned_to_the_limit``)。だから**空きではなく既存より必ず後の連番**を
    採る。並べる側(:func:`list_exports`)が時刻と連番を分けて数値で並べるのも同じ理由である。"""
    stamp = time.strftime(_STAMP_FORMAT, time.localtime())
    pattern = _name_pattern(prefix)
    used = 0
    for root in roots:
        for item in list_exports(root, prefix):
            match = pattern.match(item["name"])
            if match.group("stamp") == stamp:
                used = max(used, int(match.group("seq") or 1))
    seq = used + 1
    if seq > 99:
        raise SettingsExportError(f"同じ時刻の退避file名が使い切られています: {stamp}")
    suffix = "" if seq == 1 else f"-{seq}"
    return f"{prefix}-{stamp}{suffix}{_EXPORT_SUFFIX}"


def unique_roots(roots) -> list:
    """重複を畳んだ保存先。一次と二次が同じdirを指す構成(二次未設定)では1つになる。"""
    unique = []
    for root in roots:
        resolved = Path(root).resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def write_one(root: Path, name: str, text: str, prefix: str = _EXPORT_PREFIX,
              keep=None,
              failed_event: str = "backup.settings_export_failed") -> dict:
    """1つの保存先へ1世代を書く。書けたら {"path", "pruned"}、書けなければ例外。

    ``.partial`` へ書いてから rename する。最終名のfileは常に書き切れたfileであり、途中で
    落ちた回の残骸を後から「読める設定値」として掴むことはない。"""
    if not root.is_dir():
        # 存在しないrootは作らない。drive自体が繋がっていない時に階層を作ると、後で本物の
        # driveが戻ったときに「設定値だけが入った別の保存先」が残る。
        raise OSError(f"保存先がありません: {root}")
    directory = export_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / name
    partial = directory / (name + _PARTIAL_SUFFIX)
    try:
        partial.write_text(text, encoding="utf-8")
        partial.replace(final)
    except OSError:
        partial.unlink(missing_ok=True)
        raise
    return {"path": str(final), "pruned": prune(root, prefix, keep, failed_event)}


def export_settings(settings: Settings, roots, db_path) -> dict:
    """設定値を全ての保存先へ1世代ぶん書き出す。

    ``roots`` は書き出し先(一次保存先と全ての二次保存先)。呼び出し側が解決した実物を渡す
    —— この関数がDBから保存先を引き直すと、serverが実際に使っているrootと食い違い得る
    (``layout.set_record_roots`` と同じ約束)。

    loopもscheduleも持たない。いつ退避するか(起動時・設定変更後・録画確定後)は、その事情を
    知っている呼び出し側が決める。"""
    stored = _stored_settings(db_path)
    snapshot = _snapshot(settings, db_path, stored)
    digest = _digest(snapshot)
    payload = {
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "digest": digest,
        "export": snapshot,
    }
    # 人が読むfileなので indent を付け、日本語のlabel/noteをescapeしない。key順は
    # ``_snapshot`` が組んだ順(=SETTING_DEFSの並び)のまま置く —— 画面と同じ並びで読める。
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    targets = unique_roots(roots)
    # 世代を作る必要があるrootだけを相手にする。判定は保存先ごとに行う —— 前回どちらかへ
    # 書けなかった構成では、片方だけが古い内容のままになっている。
    pending = [root for root in targets if previous_digest(root) != digest]
    result = {
        "digest": digest,
        "created": bool(pending),
        "name": None,
        "written": [],
        "failed": [],
        "unchanged": [str(root) for root in targets if root not in pending],
    }
    if not pending:
        logger.debug(
            "設定値の退避: 内容が前回と同じなので新しい世代を作りません（%d件の保存先）",
            len(targets),
            extra={"ctx": {"digest": digest, "roots": [str(root) for root in targets]}},
        )
        return result

    name = next_name(pending)
    result["name"] = name
    for root in pending:
        try:
            written = write_one(root, name, text)
        except OSError as exc:
            result["failed"].append({"root": str(root), "error": str(exc)})
            logger.warning(
                "設定値を %s へ退避できませんでした", root,
                extra={"event": "backup.settings_export_failed",
                       "ctx": {"root": str(root), "name": name, "reason": str(exc)}},
                exc_info=True,
            )
            continue
        result["written"].append({"root": str(root), **written})

    # 運用logの記録先は、渡された ``settings`` が読み込みに使ったStorageそのもの。storageを
    # 別引数で受けると、退避した設定値とその事実を記録するDBが別物になり得る。
    storage = settings.storage
    if result["written"]:
        storage.record_ops_event(
            logger,
            "backup.settings_exported",
            "設定値を退避しました（%s / 保存先%d件）" % (name, len(result["written"])),
            detail={"name": name, "digest": digest, "written": result["written"],
                    "failed": result["failed"], "unchanged": result["unchanged"]},
        )
    if result["failed"]:
        # 1つでも書けていれば warning。読む人はfileの時刻を見て新しい方を採れるので、
        # 片方が古いままでも設定値そのものは失われていない。1つも書けなかった場合だけ
        # error —— その回の設定値はDBの外のどこにも残っていない。
        storage.record_ops_event(
            logger,
            "backup.settings_export_failed",
            "設定値を退避できない保存先があります: %s" % (
                ", ".join(item["root"] for item in result["failed"])),
            severity=OPS_WARNING if result["written"] else OPS_ERROR,
            detail={"name": name, "digest": digest, "failed": result["failed"],
                    "written": result["written"]},
        )
    return result
