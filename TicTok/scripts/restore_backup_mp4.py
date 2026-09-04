"""壊れた録画を ``_backup/`` の原本へ戻す。

再mp4化・音量正規化は元mp4を `_backup/` へ退避してから差し替える。差し替えた側が壊れて
いた場合(途中で切れた・moovが無い)、原本はそこにしか無い。これはその復旧経路である。

戻す版は**中身で選ぶ**。同じstemの退避が複数世代ある場合、既定では「ffprobeが読めて、
最も長いもの」を採る。file名の世代(.1 .2)は新しさであって良さではない — 実測では
`.1.mp4`(178.3分・720x1280統一)が最良で、その後の世代`.2.mp4`は14.5分の断片だった。

現行mp4は消さずに `_backup/` の新しい世代として残す(戻す判断が誤っていても引き返せる)。

**timing map(.timing.json)は消す。** 中身は差し替えられた側のmp4のためのwall→media対応で、
戻した版とは尺が違う(実測 872秒 vs 10696秒)。残すと焼き込みがそのズレたmapを信じて
コメントを全編ずらす。消せば焼き込みはwall時計の概算へ落ちる。

Usage (TicTok directory から venv で実行):
    python scripts/restore_backup_mp4.py --stem 00243_streamer_a_20260706_215757
    python scripts/restore_backup_mp4.py --stem <stem> --apply
    python scripts/restore_backup_mp4.py --stem <stem> --from K:/80_Tiktok/_backup/x.mp4 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
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
from tictok.record.recorder import ffprobe_available, timing_path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("restore_backup_mp4")

BACKUP_DIRNAME = "_backup"


def _roots() -> list[Path]:
    db_path = get_db_path()
    roots = []
    for raw in (record_dir_from_db(db_path), final_record_dir_from_db(db_path)):
        root = Path(raw).resolve()
        if root not in roots:
            roots.append(root)
    return roots


async def _probe(path: Path) -> tuple[float | None, int | None]:
    """(尺秒, video frame数)。読めなければ (None, None)。"""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=nb_frames:format=duration",
        "-of", "default=noprint_wrappers=1", str(path),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    seconds = frames = None
    for line in out.decode("ascii", "replace").splitlines():
        key, _, value = line.partition("=")
        try:
            if key == "duration":
                seconds = float(value)
            elif key == "nb_frames":
                frames = int(value)
        except ValueError:
            continue
    return seconds, frames


def _candidates(stem: str, roots: list[Path]) -> list[Path]:
    """この録画の退避file。`<stem>.mp4` と `<stem>.<n>.mp4` を両rootから集める。"""
    found = []
    for root in roots:
        backup_dir = root / BACKUP_DIRNAME
        if not backup_dir.is_dir():
            continue
        for path in sorted(backup_dir.glob(f"{stem}*.mp4")):
            candidate_stem, _ = layout.artifact_owner(path.name)
            if candidate_stem == stem:
                found.append(path)
    return found


def _current_mp4(stem: str, row, roots: list[Path]) -> Path | None:
    if row is not None and row["path"] and Path(row["path"]).is_file():
        return Path(row["path"])
    for root in roots:
        candidate = layout.mp4_path(root, stem)
        if candidate.is_file():
            return candidate
    return None


def _recording_row(db_path: str, stem: str):
    conn = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True, timeout=5)
    try:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT id, status, path, filename, bytes FROM recordings WHERE filename = ?",
            (f"{stem}.mp4",),
        ).fetchone()
    finally:
        conn.close()


def _update_row(db_path: str, recording_id: int, path: Path, size: int,
                mark_reprocessed: bool) -> None:
    """DBを戻したfileへ向ける。serverが動いていてもよい(SQLiteのlockが直列化する)が、
    書けなければ復旧そのものを止める — fileだけ戻してDBが古いpathを指すのが最悪の状態。

    ``mark_reprocessed`` は「これが最終形」の印。戻した版は人が中身を見て選んだ最良の
    成果物なので、次の一括再mp4化がそれを作り直して劣化させないよう対象から外す
    (実測: 戻した720x1280統一の178分を、作り直すと混在解像度に戻してしまう)。"""
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(recordings)")]
        sql = ("UPDATE recordings SET status = 'completed', path = ?, filename = ?,"
               " bytes = ?, error = NULL")
        params: list = [str(path), path.name, size]
        if mark_reprocessed and "reprocessed_at" in columns:
            sql += ", reprocessed_at = ?"
            params.append(time.time())
        conn.execute(sql + " WHERE id = ?", (*params, recording_id))
        conn.commit()
    finally:
        conn.close()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stem", required=True, help="録画のstem(拡張子なしのfile名)")
    parser.add_argument("--from", dest="source", help="戻す退避fileを明示する(既定: 最長のもの)")
    parser.add_argument("--apply", action="store_true", help="実際に戻す(既定はdry-run)")
    parser.add_argument("--no-mark", action="store_true",
                        help="「作り直し済み」の印を付けない(次の一括再mp4化の対象に戻す)")
    parser.add_argument("--mark-only", action="store_true",
                        help="fileは触らず「作り直し済み」の印だけ付ける(既に手で戻した録画用)")
    args = parser.parse_args()

    if not ffprobe_available():
        logger.error("ffprobeがPATHにありません。中身を確かめられないため中止します。")
        return 2

    stem = Path(args.stem).stem
    roots = _roots()
    db_path = get_db_path()
    row = _recording_row(db_path, stem)
    if row is None:
        logger.error("録画行が見つかりません: %s", stem)
        return 2
    current = _current_mp4(stem, row, roots)
    current_seconds, current_frames = await _probe(current) if current else (None, None)
    logger.info("現行: %s", current or "(無し)")
    logger.info("      %s / %s frame",
                f"{current_seconds / 60:.1f}分" if current_seconds else "読めない",
                current_frames if current_frames else "?")

    if args.mark_only:
        if current is None:
            logger.error("現行mp4がありません。印だけ付けても指す先がありません。")
            return 2
        if not args.apply:
            logger.info("dry-run: 現行をそのまま最終形とし、一括再mp4化の対象から外します。")
            return 0
        _update_row(db_path, row["id"], current, current.stat().st_size, True)
        logger.info("印を付けました: recording id=%s は一括再mp4化の対象から外れます。", row["id"])
        return 0

    if args.source:
        chosen = Path(args.source)
        if not chosen.is_file():
            logger.error("指定された退避fileがありません: %s", chosen)
            return 2
        chosen_seconds, chosen_frames = await _probe(chosen)
    else:
        scored = []
        for path in _candidates(stem, roots):
            seconds, frames = await _probe(path)
            logger.info("退避: %s (%.2fGB) -> %s / %s frame", path.name,
                        path.stat().st_size / 1024 ** 3,
                        f"{seconds / 60:.1f}分" if seconds else "読めない",
                        frames if frames else "?")
            if seconds:
                scored.append((seconds, frames or 0, path))
        if not scored:
            logger.error("戻せる退避fileがありません(読めるものが1つも無い): %s", stem)
            return 2
        scored.sort(key=lambda item: (item[0], item[1]))
        chosen_seconds, chosen_frames, chosen = scored[-1]

    if current_seconds and chosen_seconds and chosen_seconds <= current_seconds:
        logger.error(
            "戻す版(%.1f分)が現行(%.1f分)より長くありません。戻す意味が無いので中止します。",
            chosen_seconds / 60, current_seconds / 60)
        return 2

    destination = current or layout.mp4_path(roots[-1], stem)
    logger.info("")
    logger.info("戻す: %s (%.1f分 / %s frame)", chosen, chosen_seconds / 60, chosen_frames)
    logger.info("  -> %s", destination)
    if current:
        logger.info("現行は退避へ移す(消さない): %s", destination.parent.parent.parent / BACKUP_DIRNAME)
    stale_timing = timing_path(destination)
    if stale_timing.is_file():
        logger.info("timing mapを削除: %s（差し替えられた側の尺で作られているため）",
                    stale_timing.name)
    if not args.apply:
        logger.info("dry-runです。戻すには --apply を付けて再実行してください。")
        return 0

    if current:
        backup_dir = layout.record_root_of(current) / BACKUP_DIRNAME
        backup_dir.mkdir(parents=True, exist_ok=True)
        aside = backup_dir / f"{stem}.mp4"
        n = 1
        while aside.exists():
            aside = backup_dir / f"{stem}.{n}.mp4"
            n += 1
        shutil.move(str(current), str(aside))
        logger.info("現行を退避しました: %s", aside)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(chosen), str(destination))
    stale_timing.unlink(missing_ok=True)
    size = destination.stat().st_size
    _update_row(db_path, row["id"], destination, size, not args.no_mark)
    logger.info("戻しました: %s (%.2fGB) / recording id=%s を更新",
                destination, size / 1024 ** 3, row["id"])
    logger.info("焼き込み済みの出力(.overlay.mp4)がある場合は、元動画が変わったので作り直してください。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
