"""手入力データ(:data:`tictok.store.row_trash.ROW_TRASH_TABLES`)を、DBの外の**人が読める
JSON**として各保存先へ退避する。

対象は「人がやり直すしか復旧手段の無い表」―― 見どころ・グループ・切り出しの型・字幕の直し・
設定値・監視対象・省略形・サブアカウントの束ねの8表である。収集data(events / viewer_samples)は実配信からしか
採れないが、DBのsnapshot(``core/dbmaint.py``)とjournalが守っている。この8表はsnapshotにも入るが、
snapshotはSQLiteを開ける環境が無ければ中身を読めず、1.65GBを開いて数百KBを取り出す作業に
なる。ここが作るのは、**DBが無くても・このserverが無くても読める数百KBのJSON 1枚**で、
設定値の退避(``core/settings_export.py``)と同じ場所(``<root>/_config/``)へ並べて置く。
録画の入ったdriveを1台拾えば、その時点の人手の入力が一緒に手元にある。

設定値の退避と分けるのは、**読む人が違う**からである。設定値は「serverをどう動かしていたか」
で、復旧の最初に読む。こちらは「人が何を選び・何を直したか」で、serverが動いた後に戻す。
1枚にまとめると、数百KBの見どころの中から設定値を探すことになる。

世代の置き方(命名・並べ方・同じ内容なら作らない・刈り取り・partial→rename)は設定値の退避と
同じ規則を ``prefix`` 違いで使う。置き方が2通りあると、driveを拾った人がfile名の新旧を
2つの規則で読むことになる。

**行はそのまま載せる。** 列名も値も表に在るままで、加工・名寄せ・省略をしない。戻すときの
材料であり、加工した瞬間に「元の値」は失われる。実測(2026-09-02、実DB)で当時の7表は
bookmarks 192行 / clip_groups 19行 / clip_presets 2行 / transcript_corrections 1,070行 /
settings 121行 / monitored_targets 3行、JSONで約340KBである。

読み取りはserverのStorageではなく別connectionで行う(``settings_export._stored_settings`` と
同じ流儀)。退避はloop上から呼ばれ得るので、収集が使っているwriter lockを掴まない。
"""
import hashlib
import json
import logging
import platform
import socket
import sqlite3
from datetime import datetime

from tictok.core import settings_export
from tictok.store.row_trash import ROW_TRASH_TABLES
from tictok.storage import OPS_ERROR, OPS_WARNING

logger = logging.getLogger("tictok.tables_export")

EXPORT_PREFIX = "tables"
FAILED_EVENT = "backup.tables_export_failed"
EXPORTED_EVENT = "backup.tables_exported"

# 残す世代の数。1枚は数百KBで、世代は退避が走るたび(録画の確定ごと)に中身が変わっていれば
# 増える。見どころを1件直しただけでも新しい世代になるので、設定値(変える回数が少ない)より
# 早く窓が埋まる。30枚で数日〜数週間ぶん。それより前は別driveのDB snapshotが持っている。
KEEP_GENERATIONS = 30


class TablesExportError(RuntimeError):
    """退避の材料が揃わなかった(表を読めない)。書き出し先の失敗は戻り値の ``failed``。"""


def list_exports(root) -> list:
    return settings_export.list_exports(root, EXPORT_PREFIX)


def latest_export(root):
    return settings_export.latest_export(root, EXPORT_PREFIX)


def _read_tables(db_path) -> dict:
    """8表の全行。``{表名: {"columns": [...], "rows": [{列: 値}, ...]}}``。

    並びは ``rowid`` 順で固定する。指紋(:func:`_digest`)は中身から作るので、並びが走る
    たびに変わると同じ内容でも新しい世代になる。"""
    tables = {}
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            for table in ROW_TRASH_TABLES:
                rows = conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                columns = [column[1] for column in conn.execute(f"PRAGMA table_info({table})")]
                tables[table] = {
                    "columns": columns,
                    "rows": [dict(row) for row in rows],
                }
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.error(
            "手入力データの退避: 表を読めません（%s）", db_path,
            extra={"event": FAILED_EVENT, "ctx": {"db_path": str(db_path), "reason": str(exc)}},
            exc_info=True,
        )
        raise TablesExportError(f"手入力データを読めません: {db_path} ({exc})") from exc
    return tables


def _snapshot(db_path, tables: dict) -> dict:
    return {
        "db_path": str(db_path),
        "runtime": {
            "host": socket.gethostname(),
            "python": platform.python_version(),
        },
        "tables": tables,
    }


def _digest(snapshot: dict) -> str:
    """世代を作るかどうかの判定に使う内容の指紋。退避した時刻は含めない(``settings_export``
    と同じ理由: 含めると毎回違う指紋になる)。"""
    text = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      default=str)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def export_tables(storage, roots, db_path) -> dict:
    """手入力データを全ての保存先へ1世代ぶん書き出す。

    ``roots`` は書き出し先(一次保存先と全ての二次保存先)。``storage`` は運用logの記録先で、
    設定値の退避が ``settings.storage`` を使うのと同じく、退避した表とその事実を記録する
    DBを別物にしない。loopもscheduleも持たない(``settings_export.export_settings`` と同じ)。"""
    tables = _read_tables(db_path)
    snapshot = _snapshot(db_path, tables)
    digest = _digest(snapshot)
    payload = {
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "digest": digest,
        "counts": {table: len(entry["rows"]) for table, entry in tables.items()},
        "export": snapshot,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=1, default=str) + "\n"

    targets = settings_export.unique_roots(roots)
    pending = [root for root in targets
               if settings_export.previous_digest(root, EXPORT_PREFIX, FAILED_EVENT) != digest]
    result = {
        "digest": digest,
        "created": bool(pending),
        "name": None,
        "counts": payload["counts"],
        "bytes": len(text.encode("utf-8")),
        "written": [],
        "failed": [],
        "unchanged": [str(root) for root in targets if root not in pending],
    }
    if not pending:
        logger.debug(
            "手入力データの退避: 内容が前回と同じなので新しい世代を作りません（%d件の保存先）",
            len(targets),
            extra={"ctx": {"digest": digest, "roots": [str(root) for root in targets]}},
        )
        return result

    name = settings_export.next_name(pending, EXPORT_PREFIX)
    result["name"] = name
    for root in pending:
        try:
            written = settings_export.write_one(
                root, name, text, EXPORT_PREFIX, KEEP_GENERATIONS, FAILED_EVENT)
        except OSError as exc:
            result["failed"].append({"root": str(root), "error": str(exc)})
            logger.warning(
                "手入力データを %s へ退避できませんでした", root,
                extra={"event": FAILED_EVENT,
                       "ctx": {"root": str(root), "name": name, "reason": str(exc)}},
                exc_info=True,
            )
            continue
        result["written"].append({"root": str(root), **written})

    if result["written"]:
        storage.record_ops_event(
            logger,
            EXPORTED_EVENT,
            "手入力データを退避しました（%s / %s行 / 保存先%d件）" % (
                name, format(sum(payload["counts"].values()), ","), len(result["written"])),
            detail={"name": name, "digest": digest, "counts": payload["counts"],
                    "bytes": result["bytes"], "written": result["written"],
                    "failed": result["failed"], "unchanged": result["unchanged"]},
        )
    if result["failed"]:
        storage.record_ops_event(
            logger,
            FAILED_EVENT,
            "手入力データを退避できない保存先があります: %s" % (
                ", ".join(item["root"] for item in result["failed"])),
            severity=OPS_WARNING if result["written"] else OPS_ERROR,
            detail={"name": name, "digest": digest, "failed": result["failed"],
                    "written": result["written"]},
        )
    return result
