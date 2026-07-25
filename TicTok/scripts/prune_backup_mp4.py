"""再mp4化・音量正規化が残した ``_backup/`` の退避mp4を、安全な分だけ削除する。

再mp4化(reprocess)と音量正規化(audionorm)は、元mp4を上書きせず ``<root>/_backup/`` へ
moveしてから新しいmp4を置く。成功しても退避は消さない設計で、retentionにも容量policyにも
削除経路が無いため、走らせた分だけ永久に積み上がる。

このscriptは退避1本ごとに「作り直した現行mp4が本当に使える状態か」を確かめてから消す。
確認はfileの有無だけでは足りない。再mp4化が途中で壊れたmp4を残していた場合、退避が
その録画の唯一の原本だからである。次を全て満たしたものだけを削除対象にする:

  1. 退避名から録画のstemが解ける(命名規則どおり)
  2. 現行mp4が record root のどちらかに実在し、0byteでない
  3. DBの録画行が completed で、その行が実在するmp4を指している
  4. 現行mp4にffprobeがvideo streamを見つけられる(=再生できる)
  5. 現行mp4のvideo frame数が退避と同じだけある(=途中で切れていない)。判定は
     ``tictok.record.backups.supersedes`` に一本化してあり、serverが差し替え直後に
     行う自動掃除とまったく同じ基準になる

5の物差しに尺(container duration)を使ってはいけない。旧経路(concat demuxer)で作った
mp4は幻の音声穴でtimestampが伸びており、同じ内容を再mp4化すると尺だけが数%縮む
(実測: 4151秒 -> 4000秒、frame数は87652で同一)。尺で見ると、正しく作り直せた録画が
軒並み「短くなった」と読めてしまう。frame数は再mp4化(結合し直し)でも音量正規化
(映像stream copy)でも変わらないので、内容が欠けたときだけ減る。

1つでも欠ければ残し、理由を出す。録画行が消えている(=UIから録画を削除した)退避は
既定では残し、``--include-orphans`` を付けたときだけ削除対象にする。

既定はdry-run。実行前にserverを止めるか、少なくとも再mp4化・音量正規化のjobが走って
いないことを確認すること(実行中のjobは元mp4を退避した直後の状態にある)。

Usage (TicTok directory から venv で実行):
    python scripts/prune_backup_mp4.py                      # dry-run、判定のみ
    python scripts/prune_backup_mp4.py --apply              # 削除する
    python scripts/prune_backup_mp4.py --root K:/80_Tiktok  # rootを1つに絞る
    python scripts/prune_backup_mp4.py --min-age-days 7 --apply
    python scripts/prune_backup_mp4.py --include-orphans --apply
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tictok.core import layout
from tictok.core.config import (
    final_record_dir_from_db,
    get_db_path,
    record_dir_from_db,
)
from tictok.record import backups
from tictok.record.recorder import Recorder, ffprobe_available

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("prune_backup_mp4")

BACKUP_DIRNAME = backups.BACKUP_DIRNAME

KEEP_UNPARSEABLE = "命名規則外(stemが解けない)"
KEEP_NO_CURRENT = "現行mp4が無い"
KEEP_EMPTY_CURRENT = "現行mp4が0byte"
KEEP_NO_ROW = "録画行が無い(削除済み)"
KEEP_ROW_NOT_COMPLETED = "録画行がcompletedでない"
KEEP_ROW_PATH_MISSING = "録画行が実fileを指していない"
KEEP_UNPLAYABLE = "現行mp4にvideo streamが無い"


def _record_roots(explicit: str | None) -> list[Path]:
    """走査対象のrecord root。serverと同じ解決(DB設定 > 環境変数 > 既定)を辿る。"""
    if explicit:
        return [Path(explicit).resolve()]
    db_path = get_db_path()
    roots = []
    for raw in (record_dir_from_db(db_path), final_record_dir_from_db(db_path)):
        root = Path(raw).resolve()
        if root not in roots:
            roots.append(root)
    return roots


def _recording_rows(db_path: str) -> dict:
    """``{filename: 行}``。同じfilenameが複数あれば、実fileを指す行を優先する。

    Storageを開くとmigrationやbackupまで走るので、読むだけのここはsqlite3で直接引く。"""
    rows: dict = {}
    # 読み取り専用で開く。通常のconnectはDBが無いと空のfileを作ってしまい、path指定を
    # 間違えたときに黙って0件で通ってしまう。URIはPOSIX区切りでないとWindowsで開けない。
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5)
    except sqlite3.Error as exc:
        logger.error("DBを開けません(%s): %s", db_path, exc)
        return rows
    try:
        conn.row_factory = sqlite3.Row
        for row in conn.execute("SELECT id, status, path, filename FROM recordings"):
            name = row["filename"] or ""
            if not name:
                continue
            current = rows.get(name)
            if current is None or (not _row_points_at_file(current)
                                   and _row_points_at_file(row)):
                rows[name] = row
    except sqlite3.Error as exc:
        logger.error("recordings表を読めません: %s", exc)
    finally:
        conn.close()
    return rows


def _row_points_at_file(row) -> bool:
    raw = row["path"] or ""
    return bool(raw) and Path(raw).is_file()


def _current_mp4(stem: str, row, roots: list[Path]) -> Path | None:
    """この録画の現行mp4。DB行のpathを最優先し、行が古い場合に備えて両rootも探す。"""
    if row is not None and _row_points_at_file(row):
        return Path(row["path"])
    for root in roots:
        candidate = layout.mp4_path(root, stem)
        if candidate.is_file():
            return candidate
    return None


async def _has_video_stream(mp4_path: Path) -> bool:
    """ffprobeでvideo streamを確認する。判定はfinalizeが使うものと同じ実装を借りる
    (ここで別のffprobe呼び出しを書くと、合格の基準が2つに割れる)。"""
    probe = Recorder("", str(mp4_path.parent), None)
    probe.base = mp4_path.stem
    return await probe._validate_mp4(mp4_path)


async def _judge(backup: Path, roots: list[Path], rows: dict,
                 include_orphans: bool) -> tuple[bool, str, Path | None]:
    """(削除してよいか, 理由, 現行mp4) を返す。"""
    stem, _streamer = layout.artifact_owner(backup.name)
    if not stem:
        return False, KEEP_UNPARSEABLE, None
    row = rows.get(f"{stem}.mp4")
    current = _current_mp4(stem, row, roots)
    if current is None or current == backup:
        return False, KEEP_NO_CURRENT, None
    if current.stat().st_size <= 0:
        return False, KEEP_EMPTY_CURRENT, current
    if row is None:
        # 録画行ごと消えている。現行mp4が残っていても、この退避が誰のものか台帳で
        # 裏を取れないので既定では消さない。
        if not include_orphans:
            return False, KEEP_NO_ROW, current
    else:
        if row["status"] != "completed":
            return False, KEEP_ROW_NOT_COMPLETED, current
        if not _row_points_at_file(row):
            return False, KEEP_ROW_PATH_MISSING, current
    if not await _has_video_stream(current):
        return False, KEEP_UNPLAYABLE, current
    # 消してよいかの本判定はserverと同じ関数を通す。ここに独自の基準を書くと、片方だけが
    # 厳しくなって「scriptは残すのにserverは消す」という食い違いになる。
    ok, reason = await backups.supersedes(current, backup)
    return ok, reason, current


def _gb(size: int) -> float:
    return size / (1024 ** 3)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="実際に削除する(既定はdry-run)")
    parser.add_argument("--root", help="走査するrecord root(既定: 設定の1次と2次の両方)")
    parser.add_argument("--min-age-days", type=float, default=0.0,
                        help="この日数より新しい退避は触らない(既定: 0=制限なし)")
    parser.add_argument("--include-orphans", action="store_true",
                        help="録画行が消えている退避も削除対象にする")
    args = parser.parse_args()

    if not ffprobe_available():
        logger.error("ffprobeがPATHにありません。再生可否と尺を確認できないため中止します。")
        return 2

    roots = _record_roots(args.root)
    rows = _recording_rows(get_db_path())
    cutoff = time.time() - args.min_age_days * 86400 if args.min_age_days > 0 else None

    targets = []
    for root in roots:
        backup_dir = root / BACKUP_DIRNAME
        if not backup_dir.is_dir():
            logger.info("%s: 退避dirはありません", backup_dir)
            continue
        found = sorted(p for p in backup_dir.glob("*.mp4") if p.is_file())
        logger.info("%s: %d件", backup_dir, len(found))
        targets.extend(found)
    if not targets:
        logger.info("退避mp4はありません")
        return 0

    deletable: list[tuple[Path, int]] = []
    kept: dict = {}
    kept_bytes = 0
    skipped_new = 0
    start = time.monotonic()
    for i, backup in enumerate(targets, 1):
        size = backup.stat().st_size
        if cutoff is not None and backup.stat().st_mtime > cutoff:
            skipped_new += 1
            continue
        ok, reason, current = await _judge(backup, roots, rows, args.include_orphans)
        if ok:
            deletable.append((backup, size))
            logger.info("[%d/%d] 削除可 %s (%.1fGB) <- 現行 %s",
                        i, len(targets), backup.name, _gb(size), current)
        else:
            kept[reason] = kept.get(reason, 0) + 1
            kept_bytes += size
            logger.info("[%d/%d] 保留 %s (%.1fGB): %s",
                        i, len(targets), backup.name, _gb(size), reason)

    total_bytes = sum(size for _, size in deletable)
    logger.info("")
    logger.info("判定: 削除可 %d件 %.1fGB / 保留 %d件 %.1fGB%s (%.0f秒)",
                len(deletable), _gb(total_bytes), sum(kept.values()), _gb(kept_bytes),
                f" / 新しすぎて対象外 {skipped_new}件" if skipped_new else "",
                time.monotonic() - start)
    for reason, count in sorted(kept.items(), key=lambda kv: -kv[1]):
        logger.info("  保留理由 %s: %d件", reason, count)

    if not args.apply:
        logger.info("dry-runです。削除するには --apply を付けて再実行してください。")
        return 0

    freed = 0
    failed = 0
    for backup, size in deletable:
        try:
            backup.unlink()
        except OSError as exc:
            failed += 1
            logger.error("削除できません %s: %s", backup, exc)
            continue
        freed += size
    logger.info("削除しました: %d件 %.1fGB%s",
                len(deletable) - failed, _gb(freed),
                f" (失敗 {failed}件)" if failed else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
