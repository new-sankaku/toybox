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
"""
import logging
import re
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Optional

from tictok.core.config import (
    get_db_backup_dir,
    get_db_backup_keep,
    get_db_backup_min_free_ratio,
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
_NAME_PATTERN = re.compile(
    rf"^{_BACKUP_PREFIX}-(?P<reason>[a-z0-9_]+)-(?P<stamp>\d{{8}}-\d{{6}}(?:-\d+)?)"
    rf"\{_BACKUP_SUFFIX}$"
)

REASON_MANUAL = "manual"
REASON_PRE_MIGRATION = "premigration"


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


def list_backups(reason: Optional[str] = None) -> list:
    """Existing snapshots, newest first. Only files matching the naming scheme are
    listed; anything else in the folder is left alone and never pruned."""
    directory = backup_dir()
    if not directory.is_dir():
        return []
    wanted = normalize_reason(reason) if reason else None
    items = []
    for path in directory.iterdir():
        match = _NAME_PATTERN.match(path.name)
        if match is None or not path.is_file():
            continue
        if wanted is not None and match.group("reason") != wanted:
            continue
        stat = path.stat()
        items.append({
            "name": path.name,
            "path": str(path),
            "reason": match.group("reason"),
            "bytes": stat.st_size,
            "created_at": stat.st_mtime,
        })
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return items


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


def prune_backups(reason: str, keep: Optional[int] = None) -> list:
    """Delete the oldest snapshots of one reason beyond the retention count.

    Retention is counted per reason on purpose. A pre-migration snapshot is the only
    image of the data as it was before rows were rewritten in place, and a shared count
    would let a few routine manual backups push it out of the folder."""
    limit = get_db_backup_keep() if keep is None else int(keep)
    if limit <= 0:
        return []
    existing = list_backups(reason)
    removed = []
    for item in existing[limit:]:
        try:
            Path(item["path"]).unlink()
        except OSError:
            # 古い世代を1つ消せなくても、新しい世代は既に出来ている。退避そのものを失敗
            # 扱いにすると、消せないfileがある間ずっとbackupが取れなくなる。
            logger.warning(
                "could not prune the old database snapshot %s", item["path"], exc_info=True,
                extra={"event": "dbmaint.prune_failed", "ctx": {"path": item["path"]}},
            )
            continue
        removed.append(item["name"])
    return removed


def _free_target(directory: Path, reason_key: str) -> Path:
    """まだ使われていない退避file名。stampは秒までなので、同じ秒に2回退避すると衝突する
    (画面のbuttonを続けて押せば普通に起きる)。連番を足して避ける: ここで失敗にすると、
    operatorから見れば「押しても取れないことがある」という理由の分からない挙動になる。"""
    stamp = time.strftime(_STAMP_FORMAT, time.localtime())
    for suffix in ("", *(f"-{n}" for n in range(2, 100))):
        candidate = directory / f"{_BACKUP_PREFIX}-{reason_key}-{stamp}{suffix}{_BACKUP_SUFFIX}"
        if not candidate.exists() and not candidate.with_name(
                candidate.name + _PARTIAL_SUFFIX).exists():
            return candidate
    raise MaintenanceError(f"同じ時刻の退避file名が使い切られています: {directory}")


def create_backup(db_path, *, reason: str = REASON_MANUAL, keep: Optional[int] = None) -> dict:
    """Snapshot a live database through the SQLite backup API. Blocking; run it off the
    event loop.

    The copy is done in a single step (pages<=0). SQLite restarts a stepwise backup every
    time another connection writes the source, and this server writes the database
    continuously while collecting, so a stepwise copy of a multi-hundred-MB file could
    restart indefinitely and never converge. One step cannot be invalidated: it holds a
    read transaction, which in WAL mode does not block the writers."""
    source = Path(db_path).resolve()
    if not source.is_file():
        raise MaintenanceError(f"database fileが見つかりません: {source}")
    reason_key = normalize_reason(reason)
    directory = backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    space = _ensure_free_space(source, directory)

    final = _free_target(directory, reason_key)
    partial = final.with_name(final.name + _PARTIAL_SUFFIX)
    partial.unlink(missing_ok=True)

    started = time.monotonic()
    logger.info(
        "database snapshot started (reason=%s)", reason_key,
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
        # 退避」として掴んでしまう。
        partial.unlink(missing_ok=True)
        raise

    pruned = prune_backups(reason_key, keep)
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
    }
    logger.info(
        "database snapshot completed (reason=%s, %d bytes)", reason_key, size,
        extra={"event": "dbmaint.backup_completed", "ctx": result},
    )
    return result
