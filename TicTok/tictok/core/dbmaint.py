"""Database snapshots and health checks.

Copying a live SQLite database with a file copy is wrong: in WAL mode the newest
committed data sits in tictok.db-wal, so a copy of tictok.db alone is a torn image of an
older state, and a copy of both files taken at different instants is worse than either.
SQLite's own backup API reads the database through a read transaction — WAL included —
and produces a standalone file that is consistent as of the moment it started, while the
server keeps collecting. That is the only mechanism used here.

The snapshot is written to a .partial name, verified with PRAGMA integrity_check, and
only then renamed into place. A file under the final name is therefore always a snapshot
that has been proven readable; a failed run leaves no usable-looking wreck behind.

VACUUM is not here. It rebuilds the whole file under an exclusive lock and blocks every
writer for the duration, so it belongs to the live connection (Storage.vacuum) and to an
explicit operator action, never to an automatic path.

誤ったDELETE/DROPへの構えも、退避と同じくこのmoduleが持つ。**外部process(sqlite3.exe や
DB browser)からのDELETE/DROPは、このserverからは原理的に防げない**。防げないことを前提に、
「事故があっても戻せる」ことだけを保証する ——
  * 世代を**暦で**層化して残す(:func:`prune_scheduled_backups`)。誤りに人が気付くまでの
    猶予は日単位なので、世代を回数で数えると配信が続いた日に事故の**前**の姿が押し出される。
  * snapshotの直前に主要な表の行数を数え、急減していたら**刈り取りを凍結**する
    (:func:`check_row_guard`)。backupがあるのに戻せない状態を作る唯一の経路は、事故に
    気付かないまま世代が回転することである。
  * server自身の接続には authorizer を掛けてDROPを既定で拒否する
    (:func:`attach_drop_guard`)。外部は防げないが、この codebase 自身のbugや、後から書かれる
    migrationがうっかり表を落とすことは防げる。
"""
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from tictok.core.config import (
    get_db_backup_dir,
    get_db_backup_keep,
    get_db_backup_keep_daily,
    get_db_backup_keep_weekly,
    get_db_backup_min_free_ratio,
    get_db_guard_drop_min_rows,
    get_db_guard_drop_ratio,
    get_db_guard_drop_rows,
    get_db_integrity_check_max_errors,
)

logger = logging.getLogger("tictok.dbmaint")

_BACKUP_PREFIX = "tictok"
_BACKUP_SUFFIX = ".db"
_PARTIAL_SUFFIX = ".partial"
_STAMP_FORMAT = "%Y%m%d-%H%M%S"
# reason is part of a filename and of the retention grouping key, so it is reduced to a
# character set that is legal on both Windows and POSIX and that the name parser can
# split unambiguously (the stamp is separated by the last '-' group).
_REASON_ILLEGAL = re.compile(r"[^a-z0-9]+")
# 連番は stamp と**別のgroup**として取る。1つに畳むと数値として比べられず、並べる鍵を
# file名の文字列順に落とすしかなくなる(list_backups の説明を参照)。
_NAME_PATTERN = re.compile(
    rf"^{_BACKUP_PREFIX}-(?P<reason>[a-z0-9_]+)-(?P<stamp>\d{{8}}-\d{{6}})"
    rf"(?:-(?P<seq>\d+))?\{_BACKUP_SUFFIX}$"
)
# 同じ秒に取れる世代の数の上限。使い切ったら失敗にする(空きを埋めに戻らない)。
_MAX_SEQ = 99

REASON_MANUAL = "manual"
REASON_PRE_MIGRATION = "premigration"
# 録画の確定を合図に自動で取る世代。manual / premigration と違い**暦で**刈る
# (:func:`prune_scheduled_backups`)。
REASON_SCHEDULED = "scheduled"

# 行数の台帳と凍結状態を置くfile名。**DBの中ではなく退避先に置く**。
# DBの中(db_maintenance表)へ置くと、そのDBが壊れた・落とされた・戻された瞬間に「事故の前は
# 何行だったか」と「凍結中である」という情報が一緒に失われる。事故の直後こそこの2つが要る
# のだから、守る対象と同じfileへ入れてはならない。退避先はDB本体とは別のdiskへ向けられる
# (get_db_backup_dir)ので、diskごと落ちる事故でも退避と一緒に生き残る。
_LEDGER_NAME = "row-ledger.json"
_LEDGER_VERSION = 1

# 行数を見張る表。条件は1つだけ ——「消えたら二度と戻らない」。実配信からしか採れない収集
# data、fileへの索引、長時間の計算の結果、そして**人がやり直すしか復旧手段が無い**もの。
# 件数が小さいことは守らなくてよい理由にならないので、大きさでは絞らない(物差しの側を
# :func:`check_row_guard` で3本立てにして、小さい表でも誤検知しないようにしてある)。
#
# 除いた表とその理由:
#   ops_events           retentionが日次で刈る
#   event_strings        参照が消えれば消えて正しい(internのGCが刈る)
#   analytics_session_cache / search_hits / search_fts / storage_scan / asset_scan /
#   asset_avatar_freq    派生。元が在れば作り直せる
#   league_queue / transcribe_queue / media_job_queue   捌けば減るのが正常
#   db_maintenance / capacity_samples / discovery_dismissed   内部markerと観測sample
#
# 表が無いDB(古いschema・別のDB)では、その表だけを黙って飛ばす —— 数えられないことと
# 0行であることを混同すると、schemaが増えた日に全件が「急減」に見える。
GUARDED_TABLES = (
    # 実配信からしか採れない収集data。sessionの削除でcascadeする。
    "sessions",
    "events",
    "users",
    "buckets",
    "markers",
    "battles",
    "collab_windows",
    "envelopes",
    "viewer_samples",
    # fileへの索引と、長時間のGPU計算の結果。
    "recordings",
    "transcripts",
    # 人がやり直すしか復旧手段が無いもの。件数は小さいが、失えば手作業が丸ごと消える。
    "settings",
    "monitored_targets",
    "bookmarks",
    "clip_groups",
    "clip_presets",
    "transcript_corrections",
    "user_aliases",
    "user_merges",
)

# 検知した理由。どの物差しが鳴ったのかをlogとops_eventが名乗れないと、operatorは
# 「正常な操作なのか事故なのか」を判断する材料を持てない。
GUARD_EMPTIED = "emptied"
GUARD_ROWS = "rows"
GUARD_RATIO = "ratio"


class MaintenanceError(RuntimeError):
    """A snapshot or health check could not be completed. Raised rather than returning a
    degraded result: an operator who asked for a backup must never be told it succeeded
    when the file is missing, short, or unreadable."""


def normalize_reason(reason: str) -> str:
    text = _REASON_ILLEGAL.sub("_", str(reason or "").strip().lower()).strip("_")
    if not text:
        raise MaintenanceError(f"backup reasonが空です: {reason!r}")
    return text


def backup_dir() -> Path:
    return Path(get_db_backup_dir()).resolve()


def wal_path(db_path) -> Path:
    db = Path(db_path)
    return db.with_name(db.name + "-wal")


def source_bytes(db_path) -> int:
    """Bytes the snapshot has to materialize: the database plus whatever is still only in
    the WAL. Sizing the free-space check on tictok.db alone understates it by the WAL."""
    db = Path(db_path)
    total = db.stat().st_size if db.is_file() else 0
    wal = wal_path(db)
    return total + (wal.stat().st_size if wal.is_file() else 0)


def _stamp_epoch(stamp: str) -> float:
    """file名の時刻(``%Y%m%d-%H%M%S``、書いた側と同じlocal time)をepoch秒へ戻す。"""
    return time.mktime(time.strptime(stamp, _STAMP_FORMAT))


def list_backups(reason: Optional[str] = None) -> list:
    """Existing snapshots, newest first. Only files matching the naming scheme are
    listed; anything else in the folder is left alone and never pruned.

    並べる鍵は**file名の時刻と連番**で、時刻と連番は分けて数値で比べる。
    file名の文字列順では並べられない —— 同じ秒の2本目には ``-2`` が付き、その ``-`` は
    ``.db`` の ``.`` より前に来るので、連番なしの1本目が最新に化ける。
    mtimeでも並べない —— 退避先を別driveへcopyし直したfileが最新に回り、「最新の世代」が
    実際に最後に書かれたsnapshotと一致しなくなる(まさに復元したい時にそうなる)。

    ``taken_at`` はそのfile名の時刻をepoch秒へ戻したもので、暦の層化
    (:func:`plan_scheduled_prune`)はこちらを見る。``created_at`` は従来どおりmtime
    (画面の表示用)で、copyし直せば動く値なので判断には使わない。"""
    directory = backup_dir()
    if not directory.is_dir():
        return []
    wanted = normalize_reason(reason) if reason else None
    found = []
    for path in directory.iterdir():
        match = _NAME_PATTERN.match(path.name)
        if match is None or not path.is_file():
            continue
        if wanted is not None and match.group("reason") != wanted:
            continue
        stat = path.stat()
        stamp = match.group("stamp")
        seq = int(match.group("seq") or 1)
        found.append(((stamp, seq), {
            "name": path.name,
            "path": str(path),
            "reason": match.group("reason"),
            "stamp": stamp,
            "seq": seq,
            "taken_at": _stamp_epoch(stamp),
            "bytes": stat.st_size,
            "created_at": stat.st_mtime,
        }))
    found.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in found]


def integrity_check_file(path) -> dict:
    """PRAGMA integrity_check against a database file on disk.

    'ok' as the single returned row is SQLite's own contract for an undamaged file.
    Anything else is reported verbatim: the wording names the damaged page or index and
    is the only material a recovery decision can be made from.

    Damage bad enough that SQLite refuses to run the pragma at all raises instead of
    answering, and that is the strongest possible failing verdict — so it is turned into
    one rather than being allowed to escape as an unhandled error. Letting it propagate
    would mean the one case this check exists for is the one case it cannot report."""
    limit = max(1, get_db_integrity_check_max_errors())
    try:
        conn = sqlite3.connect(str(path))
        try:
            rows = conn.execute(f"PRAGMA integrity_check({limit})").fetchall()
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return {"ok": False, "problems": [f"{type(exc).__name__}: {exc}"],
                "max_errors": limit}
    problems = [row[0] for row in rows if row and row[0] != "ok"]
    return {"ok": not problems, "problems": problems, "max_errors": limit}


def _require_backup_dir(directory: Path) -> None:
    """退避folderが在ることを確かめる。無ければ**在る親の直下にだけ**作る。

    親までは作らない(``primary_backup._require_destination_available`` と同じ規則)。
    ``parents=True`` で作ると、退避先のdriveが外れている間にsystem driveの同じpathへ空の
    folderが生まれ、そこへ世代が積み上がる ―― driveを挿し直したときには、本物の退避先が
    古いまま止まっているのに画面は「退避は続いていた」と見える。既定の退避先(DBの隣の
    ``backups``)は親がDBのfolderなので、この規則で困ることはない。"""
    if directory.is_dir():
        return
    if not directory.parent.is_dir():
        raise MaintenanceError(
            f"退避先 {directory} の親folderが見つかりません（driveが外れている可能性があります）")
    try:
        directory.mkdir()
    except OSError as exc:
        raise MaintenanceError(f"退避先 {directory} を作れません: {exc}") from exc


def _sweep_stale_partials(directory: Path) -> list:
    """前回の書きかけ(``*.db.partial``)を掃く。

    snapshotの途中でprocessが落ちると(``run.bat`` は同じvenvのpythonを全て止める)、次の
    世代は別の名前(秒の刻印+連番)を取るので、残った書きかけを誰も上書きしない。1本が
    DBと同じ大きさなので、掃かないと落ちた回数ぶん退避先を食う。最終名の世代は
    integrity_checkを通った物しか無く、書きかけは名前で見分けられる。"""
    removed = []
    for path in directory.glob(f"{_BACKUP_PREFIX}-*{_BACKUP_SUFFIX}{_PARTIAL_SUFFIX}"):
        try:
            path.unlink()
        except OSError:
            logger.warning(
                "前回の書きかけ %s を消せませんでした", path, exc_info=True,
                extra={"event": "dbmaint.partial_sweep_failed", "ctx": {"path": str(path)}},
            )
            continue
        removed.append(path.name)
    if removed:
        logger.info(
            "前回の書きかけの退避を %d 件消しました", len(removed),
            extra={"event": "dbmaint.partials_swept", "ctx": {"removed": removed}},
        )
    return removed


def _ensure_free_space(db_path, directory: Path) -> dict:
    needed = source_bytes(db_path)
    ratio = get_db_backup_min_free_ratio()
    required = int(needed * ratio)
    free = shutil.disk_usage(directory).free
    if free < required:
        raise MaintenanceError(
            f"退避先の空き容量が不足しています: 必要 {required:,} bytes"
            f"(DB+WAL {needed:,} × {ratio}) / 空き {free:,} bytes ({directory})"
        )
    return {"source_bytes": needed, "required_bytes": required, "free_bytes": free}


# ---- 行数の台帳と刈り取りの凍結 ------------------------------------------------------


def ledger_path() -> Path:
    return backup_dir() / _LEDGER_NAME


def read_ledger() -> dict:
    """行数の台帳。壊れていても・無くても、空の台帳として読む。

    ここで例外にしてはならない。台帳はsnapshotの**前**に読まれるので、読めないことを失敗に
    すると「台帳が壊れている間はbackupが取れない」になる —— 守る仕組みが守る対象を止める。
    読めなければ前回の記録が無い扱い(=今回の行数を基準として書き直す)になるだけで、次回から
    また比較できる。"""
    path = ledger_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_ledger(data: dict) -> None:
    """台帳を書く。中身を失わないよう、同じfolderへ書いてからreplaceで差し替える。

    書けないこと自体は失敗にしない(read_ledgerと同じ理由)。ただしlogには残す ——
    「凍結したのに次回また凍結していない」の原因はここにしか無い。"""
    directory = backup_dir()
    try:
        _require_backup_dir(directory)
        tmp = directory / f"{_LEDGER_NAME}.{os.getpid()}{_PARTIAL_SUFFIX}"
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(directory / _LEDGER_NAME)
    except (OSError, MaintenanceError):
        logger.warning(
            "行数の台帳 %s を書けませんでした", ledger_path(), exc_info=True,
            extra={"event": "dbmaint.ledger_write_failed",
                   "ctx": {"path": str(ledger_path())}},
        )


def is_frozen() -> Optional[dict]:
    """刈り取りが凍結されていればその記録、されていなければNone。"""
    frozen = read_ledger().get("frozen")
    return frozen if isinstance(frozen, dict) else None


def freeze_prune(reason: str, drops: list) -> dict:
    """刈り取りを凍結する。解除は人の操作(:func:`unfreeze_prune`)だけ。

    自動で解けてはならない。行が減った理由が正常だったのか事故だったのかを決められるのは
    人だけで、時間で自動解除すると「気付く前に解けて、気付く前に回転する」——凍結を置いた
    理由がそのまま消える。"""
    ledger = read_ledger()
    existing = ledger.get("frozen")
    if isinstance(existing, dict):
        # 既に凍結中なら最初の検知を上書きしない。事故の最初の姿を指しているのは1回目の記録。
        return existing
    frozen = {"since": time.time(), "reason": reason, "drops": drops}
    ledger["frozen"] = frozen
    _write_ledger(ledger)
    return frozen


def unfreeze_prune() -> dict:
    """凍結を解除する。人が「この減り方は正常だった」と判断したときにだけ呼ばれる。"""
    ledger = read_ledger()
    previous = ledger.pop("frozen", None)
    if previous is not None:
        _write_ledger(ledger)
    return {"was_frozen": isinstance(previous, dict), "frozen": previous}


def count_guarded_rows(db_path) -> dict:
    """:data:`GUARDED_TABLES` の行数。読み取り専用接続で数えるので収集は止まらない。

    存在しない表は結果に載せない(0を入れない)。理由は GUARDED_TABLES の説明を参照。"""
    source = Path(db_path).resolve()
    if not source.is_file():
        raise MaintenanceError(f"database fileが見つかりません: {source}")
    counts: dict = {}
    conn = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        present = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        for table in GUARDED_TABLES:
            if table not in present:
                continue
            counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()
    return counts


def _guard_verdict(table: str, before: int, after: int, ratio: float,
                   rows: int, min_rows: int) -> Optional[dict]:
    """1つの表の減り方を3つの物差しで見る。事故なら理由つきの記録、そうでなければNone。

    **物差しが3本あるのは、1本ではどの大きさの表も守れないからである。**

    * 0行化(``GUARD_EMPTIED``): 行が在った表が0行になった。閾値を持たない。``DROP TABLE``
      して作り直しても ``DELETE FROM <表>`` でも最終形は同じ「0行」で、これは表の大小に
      関係なく起きる。割合にも行数にも取りこぼす設定値が在り得るので独立した条件として置く。
      件数の小さい手入力データ(settings / monitored_targets / clip_groups)を実際に守るのは
      ほぼこの条件である —— それらは大きい表の物差しには決して届かない。
    * 行数(``GUARD_ROWS``): ``rows`` 件以上減った。割合の許容量はDBが育つほど増えるので、
      その天井を固定する。
    * 割合(``GUARD_ROWS`` ではなく ``GUARD_RATIO``): ``ratio`` を超えて減った。ただし
      ``min_rows`` 未満の減少には当てない —— 割合は小さい表では成立せず、そこで当てると
      通常運用の1操作(実測: markers 1 session 351行 / bookmarks のグループ一括 59行)の
      たびに凍結し、凍結そのものが「またか」になって意味を失う。

    閾値0はその物差しを使わない意味(この設定群の規約)。"""
    lost = before - after
    if lost <= 0:
        return None
    record = {"table": table, "before": before, "after": after, "lost": lost,
              "ratio": round(lost / before, 6)}
    if after == 0:
        return {**record, "why": GUARD_EMPTIED}
    if rows > 0 and lost >= rows:
        return {**record, "why": GUARD_ROWS}
    if ratio > 0 and lost / before > ratio and lost >= min_rows:
        return {**record, "why": GUARD_RATIO}
    return None


_GUARD_REASON_TEXT = {
    GUARD_EMPTIED: "0行になりました",
    GUARD_ROWS: "行数の閾値を超えて減りました",
    GUARD_RATIO: "割合の閾値を超えて減りました",
}


def check_row_guard(db_path) -> dict:
    """snapshotの直前に行数を数え、前回の記録からの急減を検知する。

    **止めない。** 行が減ること自体は正常にも起きる(録画の削除・sessionの削除・孤児userの
    回収)。減ったからといって収集やbackupを止めれば、正常な運用のほうが壊れる。行うのは
    2つだけ —— 古い世代の刈り取りを凍結して事故の**前**の姿を守り、logとops_eventで名乗る。

    判定は表ごとに3本の物差しで行う(:func:`_guard_verdict`)。

    台帳は毎回**今回の行数で**更新する。減った側へ基準を追従させないと、1度減ったあとは
    毎回の比較が同じ差分を検知し続け、以後どの凍結も情報を持たなくなる。凍結は残るので、
    最初の検知が消えるわけではない。"""
    ratio = get_db_guard_drop_ratio()
    rows = get_db_guard_drop_rows()
    min_rows = get_db_guard_drop_min_rows()
    counts = count_guarded_rows(db_path)
    ledger = read_ledger()
    source = str(Path(db_path).resolve())
    previous = ledger.get("counts") if ledger.get("db") == source else None
    previous = previous if isinstance(previous, dict) else {}

    drops = []
    for table, before in previous.items():
        after = counts.get(table)
        if after is None or not isinstance(before, int) or before <= 0:
            continue
        verdict = _guard_verdict(table, before, after, ratio, rows, min_rows)
        if verdict is not None:
            drops.append(verdict)

    ledger["version"] = _LEDGER_VERSION
    ledger["db"] = source
    ledger["counts"] = counts
    ledger["updated_at"] = time.time()
    _write_ledger(ledger)

    thresholds = {"ratio": ratio, "rows": rows, "min_rows": min_rows}
    frozen = is_frozen()
    if drops:
        summary = " / ".join(
            "{table} {before:,}→{after:,}行(-{pct:.1f}%・{why})".format(
                table=d["table"], before=d["before"], after=d["after"],
                pct=d["ratio"] * 100, why=_GUARD_REASON_TEXT[d["why"]])
            for d in drops)
        message = (
            f"DBの行数が急減しました（割合 {ratio * 100:.1f}% / 行数 {rows:,} / "
            f"割合の最小幅 {min_rows:,}）: {summary}")
        logger.warning(
            "%s。古い退避の刈り取りを凍結します（解除は /api/maintenance/unfreeze）", message,
            extra={"event": "dbmaint.row_guard_tripped",
                   "ctx": {**thresholds, "drops": drops}},
        )
        frozen = freeze_prune(message, drops)
    return {**thresholds, "counts": counts, "previous": previous,
            "drops": drops, "tripped": bool(drops), "frozen": frozen}


def guard_status() -> dict:
    """画面へ返す見張りの状態。台帳が無ければ空の記録として答える。"""
    ledger = read_ledger()
    counts = ledger.get("counts")
    return {
        "ratio": get_db_guard_drop_ratio(),
        "rows": get_db_guard_drop_rows(),
        "min_rows": get_db_guard_drop_min_rows(),
        "tables": list(GUARDED_TABLES),
        "counts": counts if isinstance(counts, dict) else {},
        "updated_at": ledger.get("updated_at"),
        "db": ledger.get("db"),
        "frozen": is_frozen(),
        "ledger_path": str(ledger_path()),
    }


# ---- 世代の刈り取り ------------------------------------------------------------------


def _unlink_backup(item: dict) -> bool:
    try:
        Path(item["path"]).unlink()
    except OSError:
        # 古い世代を1つ消せなくても、新しい世代は既に出来ている。退避そのものを失敗
        # 扱いにすると、消せないfileがある間ずっとbackupが取れなくなる。
        logger.warning(
            "古いDBの退避file %s を削除できませんでした", item["path"], exc_info=True,
            extra={"event": "dbmaint.prune_failed", "ctx": {"path": item["path"]}},
        )
        return False
    return True


def prune_backups(reason: str, keep: Optional[int] = None) -> list:
    """Delete the oldest snapshots of one reason beyond the retention count.

    Retention is counted per reason on purpose. A pre-migration snapshot is the only
    image of the data as it was before rows were rewritten in place, and a shared count
    would let a few routine manual backups push it out of the folder.

    凍結中は1つも消さない。凍結が守ろうとしているのは「事故の前の姿」であり、それは暦で層化
    した世代(scheduled)だけでなく premigration の1本でもある —— 凍結中に手動退避を数回押せば
    回数の世代が回り、まさに守りたい像が押し出される。"""
    if is_frozen():
        return []
    limit = get_db_backup_keep() if keep is None else int(keep)
    if limit <= 0:
        return []
    return [item["name"] for item in list_backups(reason)[limit:] if _unlink_backup(item)]


def _local_date(ts: float) -> date:
    lt = time.localtime(ts)
    return date(lt.tm_year, lt.tm_mon, lt.tm_mday)


def plan_scheduled_prune(items: list, now: Optional[float] = None) -> dict:
    """自動世代(scheduled)のうち、どれを残しどれを消すかを暦で決める。純関数。

    **回数ではなく暦で数える。** 誤ったDELETE/DROPは気付くまでに日数がかかる種類の事故で、
    世代を回数で数えると、配信が続いた日に事故の**前**の姿が押し出される —— 3世代は配信3本
    でしかなく、忙しい日なら数時間で一巡する。暦で数えれば、押し出す速さを決めるのは配信の
    本数ではなく日付になり、「何日前まで戻れるか」が運用と無関係に保証される。

    層は2つ。直近 ``get_db_backup_keep_daily()`` 日は**1日1つ**(その日の最初のもの)、それより
    古い分は ``get_db_backup_keep_weekly()`` 週について**1週1つ**。その日の「最初」を残すのは、
    1日の活動が始まる前の姿だからである(その日の操作で壊れたなら、残すべきは操作の前)。

    どちらの層にも属さない物は消す。ただし**最新の1本だけは常に残す**: 復元の起点として最新の
    姿は必ず要り、かつ今取ったばかりのsnapshotを同じ呼び出しで消すのは、呼んだ側から見れば
    退避が成功していないのと同じである。

    両方の保持数が0なら刈り取りそのものを行わない(0=無効という、この設定群の規約)。"""
    keep_daily = get_db_backup_keep_daily()
    keep_weekly = get_db_backup_keep_weekly()
    ordered = sorted(items, key=lambda item: (item["stamp"], item["seq"]))
    plan = {"keep_daily": keep_daily, "keep_weekly": keep_weekly,
            "daily": [], "weekly": [], "keep": [], "delete": []}
    if not ordered:
        return plan
    if keep_daily <= 0 and keep_weekly <= 0:
        plan["keep"] = [item["name"] for item in ordered]
        return plan

    today = _local_date(time.time() if now is None else now)
    daily_floor = today - timedelta(days=keep_daily - 1) if keep_daily > 0 else None
    monday = today - timedelta(days=today.weekday())
    weekly_floor = monday - timedelta(weeks=keep_weekly - 1) if keep_weekly > 0 else None

    daily: dict = {}
    weekly: dict = {}
    for item in ordered:
        day = _local_date(item["taken_at"])
        if daily_floor is not None and day >= daily_floor:
            daily.setdefault(day.isoformat(), item)
        elif weekly_floor is not None and day >= weekly_floor:
            iso = day.isocalendar()
            weekly.setdefault(f"{iso[0]}-W{iso[1]:02d}", item)

    kept_names = {item["name"] for item in daily.values()}
    kept_names |= {item["name"] for item in weekly.values()}
    kept_names.add(ordered[-1]["name"])
    plan["daily"] = [{"key": key, "name": item["name"]} for key, item in sorted(daily.items())]
    plan["weekly"] = [{"key": key, "name": item["name"]} for key, item in sorted(weekly.items())]
    plan["keep"] = [item["name"] for item in ordered if item["name"] in kept_names]
    plan["delete"] = [item for item in ordered if item["name"] not in kept_names]
    return plan


def prune_scheduled_backups(now: Optional[float] = None) -> dict:
    """自動世代を暦で刈る。凍結中は1つも消さない。"""
    if is_frozen():
        return {"frozen": True, "removed": [], "daily": [], "weekly": []}
    plan = plan_scheduled_prune(list_backups(REASON_SCHEDULED), now)
    removed = [item["name"] for item in plan["delete"] if _unlink_backup(item)]
    return {"frozen": False, "removed": removed,
            "daily": plan["daily"], "weekly": plan["weekly"],
            "keep_daily": plan["keep_daily"], "keep_weekly": plan["keep_weekly"]}


def scheduled_layers(now: Optional[float] = None) -> dict:
    """画面へ返す自動世代の内訳。刈らずに、いま何がどの層で残っているかだけを答える。"""
    plan = plan_scheduled_prune(list_backups(REASON_SCHEDULED), now)
    return {"daily": plan["daily"], "weekly": plan["weekly"],
            "keep_daily": plan["keep_daily"], "keep_weekly": plan["keep_weekly"],
            "expiring": [item["name"] for item in plan["delete"]]}


def _next_target(directory: Path, reason_key: str) -> Path:
    """次の世代の退避file名。stampは秒までなので、同じ秒に2回退避すると衝突する(画面の
    buttonを続けて押せば普通に起きる)。連番を足して避ける: ここで失敗にすると、operatorから
    見れば「押しても取れないことがある」という理由の分からない挙動になる。

    **「空いている名前」を拾ってはならない。** 刈り取り(:func:`prune_backups` /
    :func:`prune_scheduled_backups`)は古い世代を消すので、同じ秒の中で連番の**若い**名前が
    後から空く。そこを埋めると、いま書いた最新の内容が最も古い名前を名乗ることになり、直後の
    刈り取りがそれを最古と見なして消す —— 「退避は成功しているのに、直後に読むと古い内容が
    最新として出てくる」という、backupがあるのに戻せない状態そのものである。再現条件は
    ``keep=3`` で同一秒に5回で、4回目の刈り取りが連番なしの1本目を消して名前を空け、5回目が
    そこへ書いて即座に自分を消した(``tests/test_dbmaint_guard.py`` の
    ``test_same_second_generations_keep_the_newest_content``)。

    だから採るのは**既存のどれよりも必ず後の連番**(max+1)。並べる側
    (:func:`list_backups`)が時刻と連番を分けて数値で比べるのも同じ理由である。
    ``tictok/core/settings_export.py`` の ``_next_name`` が同じ形をしているが、命名規則が
    別物(理由を含む/含まない)なので共通化はしない。"""
    stamp = time.strftime(_STAMP_FORMAT, time.localtime())
    used = 0
    for item in list_backups(reason_key):
        if item["stamp"] == stamp:
            used = max(used, item["seq"])
    seq = used + 1
    if seq > _MAX_SEQ:
        raise MaintenanceError(f"同じ時刻の退避file名が使い切られています: {directory}")
    suffix = "" if seq == 1 else f"-{seq}"
    return directory / f"{_BACKUP_PREFIX}-{reason_key}-{stamp}{suffix}{_BACKUP_SUFFIX}"


def create_backup(db_path, *, reason: str = REASON_MANUAL, keep: Optional[int] = None) -> dict:
    """Snapshot a live database through the SQLite backup API. Blocking; run it off the
    event loop.

    The copy is done in a single step (pages<=0). SQLite restarts a stepwise backup every
    time another connection writes the source, and this server writes the database
    continuously while collecting, so a stepwise copy of a multi-hundred-MB file could
    restart indefinitely and never converge. One step cannot be invalidated: it holds a
    read transaction, which in WAL mode does not block the writers.

    ``reason=REASON_SCHEDULED`` は録画の確定を合図に取る自動世代で、刈り取りだけが違う
    (回数ではなく暦。:func:`plan_scheduled_prune`)。

    戻り値の ``guard`` は行数の見張りの結果、``prune_frozen`` は刈り取りを凍結したまま
    素通りしたかどうか。呼び出し側は :func:`record_backup_ops_events` へそのまま渡すこと
    —— ops_eventsへ残すのは呼び出し側の仕事である(このmoduleはstorageを知らない)。"""
    source = Path(db_path).resolve()
    if not source.is_file():
        raise MaintenanceError(f"database fileが見つかりません: {source}")
    reason_key = normalize_reason(reason)
    directory = backup_dir()
    _require_backup_dir(directory)
    swept = _sweep_stale_partials(directory)
    space = _ensure_free_space(source, directory)
    # 行数の見張りはsnapshotの**前**に置く。後ろに置くと、事故のあとに取ったsnapshotを
    # 基準として台帳へ書き込んでから比較することになり、その回の急減は永久に見えない。
    try:
        guard = check_row_guard(source)
    except sqlite3.Error as exc:
        # 数えられなくてもsnapshotは取る。見張りはbackupを守るための仕組みであって、
        # backupを止めてよい理由ではない —— 数えられない状態(DBが壊れかけている)は、
        # backupが最も要る状態そのものである。
        logger.error(
            "退避前の行数を数えられませんでした: %s", exc, exc_info=True,
            extra={"event": "dbmaint.row_guard_failed", "ctx": {"db": str(source)}},
        )
        guard = {"ratio": get_db_guard_drop_ratio(), "rows": get_db_guard_drop_rows(),
                 "min_rows": get_db_guard_drop_min_rows(), "counts": {}, "previous": {},
                 "drops": [], "tripped": False, "frozen": is_frozen(),
                 "error": f"{type(exc).__name__}: {exc}"}

    final = _next_target(directory, reason_key)
    partial = final.with_name(final.name + _PARTIAL_SUFFIX)
    partial.unlink(missing_ok=True)

    started = time.monotonic()
    logger.info(
        "DBの退避を開始しました（reason=%s）", reason_key,
        extra={"event": "dbmaint.backup_started",
               "ctx": {"reason": reason_key, "target": str(final), **space}},
    )
    try:
        src = sqlite3.connect(str(source))
        try:
            dest = sqlite3.connect(str(partial))
            try:
                src.backup(dest)
            finally:
                dest.close()
        finally:
            src.close()
        copied_ms = (time.monotonic() - started) * 1000.0
        verdict = integrity_check_file(partial)
        if not verdict["ok"]:
            raise MaintenanceError(
                "退避fileのintegrity_checkが通りませんでした: "
                + "; ".join(verdict["problems"])
            )
        size = partial.stat().st_size
        partial.replace(final)
    except Exception:
        # 検証を通っていないfileを最終名で残さない。残すと、次に復元へ使う人が「検証済みの
        # 退避」として掴んでしまう。消せない(driveごと外れた)ときは元の例外を通す ――
        # ここでOSErrorに差し替わると、記録に残る理由が「書きかけを消せない」になり、
        # 退避が失敗した本当の理由が読めない。残った書きかけは次回の頭で掃く。
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "失敗した退避の書きかけ %s を消せませんでした", partial, exc_info=True,
                extra={"event": "dbmaint.partial_unlink_failed", "ctx": {"path": str(partial)}},
            )
        raise

    frozen = is_frozen()
    if reason_key == REASON_SCHEDULED:
        prune = prune_scheduled_backups()
        pruned = prune["removed"]
        layers = {"daily": prune["daily"], "weekly": prune["weekly"]}
    else:
        pruned = prune_backups(reason_key, keep)
        layers = {}
    if frozen:
        logger.warning(
            "刈り取りを凍結中のため、古い退避を1つも消しませんでした（%s）",
            frozen.get("reason", ""),
            extra={"event": "dbmaint.prune_frozen", "ctx": {"frozen": frozen}},
        )
    result = {
        "path": str(final),
        "name": final.name,
        "reason": reason_key,
        "bytes": size,
        "source_bytes": space["source_bytes"],
        "copy_ms": round(copied_ms, 1),
        "duration_ms": round((time.monotonic() - started) * 1000.0, 1),
        "integrity_ok": True,
        "pruned": pruned,
        "prune_frozen": bool(frozen),
        "layers": layers,
        "guard": guard,
        "swept_partials": swept,
    }
    logger.info(
        "DBの退避が完了しました（reason=%s, %d bytes）", reason_key, size,
        extra={"event": "dbmaint.backup_completed", "ctx": result},
    )
    return result


def record_backup_ops_events(storage, log, result: dict, *, job_id=None) -> None:
    """:func:`create_backup` の結果のうち、運用が知らなければならない2件をops_eventsへ残す。

    このmoduleがstorageを直接importしないのは循環になるためで(tictok.store.maintenance が
    core.dbmaint をimportしている)、severity定数だけを関数の中で遅延importしている。
    storageはduck typingで受ける —— 必要なのは ``record_ops_event`` 1つだけ。

    退避を呼ぶ経路は複数ある(画面のbutton・起動時のmigration前・録画確定の自動)。どの経路
    から取っても同じ2件が残るよう、記録はこの1関数に集める。"""
    from tictok.storage import OPS_WARNING

    guard = result.get("guard") or {}
    if guard.get("drops"):
        summary = " / ".join(
            f"{d['table']} {d['before']:,}→{d['after']:,}行" for d in guard["drops"])
        storage.record_ops_event(
            log, "maintenance.row_guard_tripped",
            f"DBの行数が急減しました: {summary}。古い退避の刈り取りを凍結しました",
            severity=OPS_WARNING, job_id=job_id,
            detail={"ratio": guard.get("ratio"), "drops": guard["drops"]},
        )
    if result.get("prune_frozen"):
        frozen = guard.get("frozen") or {}
        storage.record_ops_event(
            log, "maintenance.prune_frozen",
            "刈り取りを凍結中のため、古い退避を残しました: {reason}".format(
                reason=frozen.get("reason", "")),
            severity=OPS_WARNING, job_id=job_id,
            detail={"frozen": frozen, "backup": result.get("name")},
        )


# ---- server自身の接続へのDROP防御 ----------------------------------------------------
# **外部process(sqlite3.exe / DB browser / 手で書いたscript)からのDELETE・DROPは、この
# serverからは原理的に防げない。** それらは自分でDB fileを開くので、こちらが接続へ何を
# 掛けても通らない。防げるのは「このcodebase自身の接続を通る操作」だけである。それでも
# 掛ける価値があるのは、実際に表を落とし得るのがそこだからで —— migrationは cut_list を
# DROPし、intern移行は旧列を落とす —— 条件を1つ間違えた版が、在るdataの上で走る。

_DROP_ACTIONS = frozenset({
    sqlite3.SQLITE_DROP_TABLE,
    sqlite3.SQLITE_DROP_INDEX,
    sqlite3.SQLITE_DROP_TRIGGER,
    sqlite3.SQLITE_DROP_VIEW,
})
# 許可区間はthread単位で持つ。接続は check_same_thread=False で複数threadが共有するので、
# process全体のflagにすると、migrationが開けた窓を無関係なthreadのDROPが通り抜ける。
_drop_guard_state = threading.local()


@contextmanager
def allow_schema_drops():
    """DROPを明示的に許可する区間。

    使い方(migrationの中だけで、落とす対象が分かっている区間を包む)::

        with dbmaint.allow_schema_drops():
            conn.execute("DROP TABLE cut_list")

    区間はこれを呼んだthreadにだけ開く。入れ子は数える(内側を抜けても外側の許可は続く)。"""
    depth = getattr(_drop_guard_state, "depth", 0)
    _drop_guard_state.depth = depth + 1
    try:
        yield
    finally:
        _drop_guard_state.depth = depth


def _drop_authorizer(action, arg1, arg2, db_name, trigger_name):
    if action in _DROP_ACTIONS and getattr(_drop_guard_state, "depth", 0) <= 0:
        logger.error(
            "schemaのDROPを拒否しました: %s（%s）。意図した操作なら "
            "dbmaint.allow_schema_drops() の中で行ってください", arg1, db_name,
            extra={"event": "dbmaint.drop_denied",
                   "ctx": {"action": action, "name": arg1, "db": db_name}},
        )
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def attach_drop_guard(conn) -> None:
    """接続へDROP防御を取り付ける。``conn.set_authorizer`` は1接続に1つなので、書き込み
    接続を作った直後に1度だけ呼ぶ。

    authorizerはstatementの**prepare時**に呼ばれる(実行のたびではない)。sqlite3 moduleは
    prepare済みstatementをcacheするので、同じSQLを繰り返す取り込み経路では2回目以降は
    呼ばれない —— 実測は本file末尾ではなく報告に記載。

    DROP以外は素通しする。DELETEを拒否しないのは意図的で、行の削除はUIの正常な機能
    (録画の削除・sessionの削除・retention)そのものだからである。DELETEの事故に対しては、
    拒否ではなく :func:`check_row_guard` の「気付いて世代を凍結する」側で構える。"""
    conn.set_authorizer(_drop_authorizer)
