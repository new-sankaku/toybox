"""Re-run the recorder's real finalize pipeline (.ts concat -> timing map -> single-
resolution normalize) for an already-finalized recording, straight from its retained HLS
segments. This is the same code path a live recording takes on stop, so the result is
identical to a freshly recorded file — unlike a plain mp4 re-encode, it drops PTS-
discontinuity segments and regenerates timestamps, which is the only way to fix recordings
whose stream-copied mp4 has a baked-in timestamp glitch.

The existing mp4 is moved to a backup dir first (never overwritten in place); on any
failure it is moved back so the recording is never left without a playable file. The HLS
segments are kept (keep_hls) so the source stays available for verification.

Usage (from the TicTok dir, in the venv):
    python scripts/reprocess_from_ts.py --base <stem> --record-dir K:/80_Tiktok --backup-dir K:/80_Tiktok/_backup
    python scripts/reprocess_from_ts.py --base <stem> --record-dir K:/80_Tiktok --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tictok.record.recorder import Recorder, ffmpeg_available, ffprobe_available

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("reprocess_from_ts")


async def reprocess_one(base: str, record_dir: Path, backup_dir: Path, dry_run: bool) -> bool:
    """Re-finalize ``base`` from its HLS segments under ``record_dir``. Returns True on a
    successful, validated regeneration."""
    hls_dir = record_dir / base
    mp4_path = record_dir / f"{base}.mp4"
    segs = sorted(hls_dir.glob("seg*.ts")) if hls_dir.is_dir() else []
    if not segs:
        logger.error("no HLS segments at %s; cannot reprocess from .ts", hls_dir)
        return False
    logger.info("%s: %d segments, m3u8=%s, mp4=%s",
                base, len(segs), (hls_dir / "index.m3u8").is_file(),
                "present" if mp4_path.is_file() else "absent")
    if dry_run:
        logger.info("[dry-run] would re-finalize %s from .ts (backup existing mp4 to %s)", base, backup_dir)
        return True

    # Move the existing mp4 out of the way (finalize writes <base>.mp4 in place). Keep it
    # as a backup on success; restore it if the re-finalize fails so nothing is lost.
    backup_path = backup_dir / f"{base}.mp4"
    backed_up = False
    if mp4_path.is_file():
        backup_dir.mkdir(parents=True, exist_ok=True)
        # Avoid clobbering an earlier backup of the same name.
        if backup_path.exists():
            backup_path = backup_dir / f"{base}.prev.mp4"
        shutil.move(str(mp4_path), str(backup_path))
        backed_up = True
        logger.info("backed up original mp4 -> %s", backup_path)

    recorder = Recorder(base, str(record_dir), None, keep_hls=True, final_dir=str(record_dir))
    try:
        await recorder.finalize_recovered_hls(base)
    except Exception:
        logger.exception("re-finalize crashed for %s", base)
        if backed_up and not mp4_path.is_file():
            shutil.move(str(backup_path), str(mp4_path))
            logger.info("restored original mp4 after crash")
        return False

    snap = recorder.snapshot()
    ok = (recorder.output_path is not None and Path(recorder.output_path).is_file()
          and snap.get("bytes", 0) > 0 and recorder.state == "completed")
    if not ok:
        logger.error("re-finalize did not produce a valid mp4 for %s (state=%s); restoring original",
                     base, recorder.state)
        if backed_up and not mp4_path.is_file():
            shutil.move(str(backup_path), str(mp4_path))
            logger.info("restored original mp4")
        return False
    logger.info("re-finalized %s -> %s (%d bytes, state=%s)",
                base, recorder.output_path, snap.get("bytes", 0), recorder.state)
    return True


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="recording stem (dir name of its seg*.ts)")
    parser.add_argument("--record-dir", required=True, help="dir holding <base>/seg*.ts and <base>.mp4")
    parser.add_argument("--backup-dir", help="where the original mp4 is moved (default: <record-dir>/_backup)")
    parser.add_argument("--dry-run", action="store_true", help="report only, do not re-encode")
    args = parser.parse_args()

    if not (ffmpeg_available() and ffprobe_available()):
        logger.error("ffmpeg/ffprobe not found on PATH")
        return 2
    record_dir = Path(args.record_dir)
    backup_dir = Path(args.backup_dir) if args.backup_dir else record_dir / "_backup"
    ok = await reprocess_one(args.base, record_dir, backup_dir, args.dry_run)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
