"""Re-encode already-finalized recordings whose video track carries more than one
resolution to a single resolution, so players stop freezing/zooming at each switch.

A live source that changes resolution mid-broadcast (adaptive bitrate on the streamer's
side) produces HLS segments of differing sizes; the recorder stream-copies them into one
mp4, baking multiple resolutions into a single track. That file is technically valid but
many players (e.g. MPC-BE) stutter or jump at every switch point. The recorder now
normalizes such recordings at finalize; this script back-fills the fix for recordings made
before that, detecting mixed resolution directly from the mp4 (their HLS segments are
usually gone).

Each frame is fitted onto the largest resolution seen, preserving the original frame
timestamps (``-fps_mode passthrough``) so the companion timing map stays valid. Idempotent
(a recording already at a single resolution is skipped) and best-effort (on failure the
original mp4 is kept). The normalized mp4 replaces the original in place.

Usage (run from the TicTok directory, in the venv):
    python scripts/normalize_mixed_resolution.py                     # dry-run, report only
    python scripts/normalize_mixed_resolution.py --apply             # write changes
    python scripts/normalize_mixed_resolution.py --file recordings/NAME.mp4 --apply
    python scripts/normalize_mixed_resolution.py --record-dir other/recordings --apply
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tictok.core import config
from tictok.core.config import get_db_path, record_dir_from_db
from tictok.record.recorder import (
    ffmpeg_available,
    ffprobe_available,
    probe_mp4_resolutions,
    commit_normalized,
    normalize_marker_path,
    normalize_tmp_path,
    reencode_single_resolution,
    timing_path,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("normalize_mixed_resolution")


async def normalize_one(mp4_path: Path, apply: bool, backup_dir: Path = None) -> bool:
    """Report (and, when apply, perform) normalization for one recording. Returns True
    when the file was (or would be) changed."""
    resolutions = await probe_mp4_resolutions(mp4_path)
    if len(resolutions) <= 1:
        return False
    target_w = max(w for w, _ in resolutions)
    target_h = max(h for _, h in resolutions)
    target_w += target_w % 2
    target_h += target_h % 2
    mode = config.get_normalize_scale_mode()
    summary = ", ".join(f"{w}x{h}" for w, h in sorted(resolutions))
    logger.info(
        "%s: %d resolutions (%s) -> %dx%d%s",
        mp4_path.name, len(resolutions), summary, target_w, target_h,
        "" if apply else "  [dry-run]",
    )
    if not apply:
        return True
    tmp = normalize_tmp_path(mp4_path)
    ok = await reencode_single_resolution(
        mp4_path, tmp, target_w, target_h, mode,
        config.get_normalize_codec(), config.get_normalize_quality(),
    )
    if not ok:
        logger.error("  re-encode failed; keeping original %s", mp4_path.name)
        tmp.unlink(missing_ok=True)
        return False
    if backup_dir is not None:
        # Preserve the original instead of overwriting it: move it into the backup dir,
        # then move the re-encode into its place. Only after a confirmed-good re-encode,
        # so a failure above never disturbs the original.
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / mp4_path.name
        n = 1
        while backup_path.exists():
            backup_path = backup_dir / f"{mp4_path.stem}.{n}{mp4_path.suffix}"
            n += 1
        try:
            shutil.move(str(mp4_path), str(backup_path))
        except OSError:
            logger.error("  could not back up original %s; keeping it and discarding re-encode",
                         mp4_path.name)
            tmp.unlink(missing_ok=True)
            normalize_marker_path(tmp).unlink(missing_ok=True)
            return False
        try:
            shutil.move(str(tmp), str(mp4_path))
        except OSError:
            # Roll back so the recording is never left without its file.
            shutil.move(str(backup_path), str(mp4_path))
            tmp.unlink(missing_ok=True)
            normalize_marker_path(tmp).unlink(missing_ok=True)
            logger.error("  could not place re-encode for %s; restored original", mp4_path.name)
            return False
        normalize_marker_path(tmp).unlink(missing_ok=True)
        _drop_timing_if_cfr(mp4_path, ok)
        logger.info("  done: %s -> %dx%d (original backed up to %s)",
                    mp4_path.name, target_w, target_h, backup_path)
        return True
    if not await commit_normalized(tmp, mp4_path, ok):
        # Keep the completed re-encode rather than discard it to a transient lock (a
        # media player or AV scanner holding the mp4 open). It carries a completion
        # marker, so the server's startup sweep swaps it in on its own; closing the file
        # and re-running this script also works.
        logger.error(
            "  could not replace %s (file locked — is it open in a player?); normalized "
            "output kept at %s and will be reclaimed at the next server startup",
            mp4_path.name, tmp.name,
        )
        return False
    if ok == "cfr":
        logger.warning("  used CFR fallback for %s; dropped timing map (comment sync approximate)",
                       mp4_path.name)
    logger.info("  done: %s -> %dx%d", mp4_path.name, target_w, target_h)
    return True


def _drop_timing_if_cfr(mp4_path: Path, mode) -> None:
    """When the re-encode fell back to CFR the media->pts timing map no longer matches, so
    remove the sidecar; the comment burn-in then approximates rather than using a wrong map."""
    if mode == "cfr":
        timing_path(mp4_path).unlink(missing_ok=True)
        logger.warning("  used CFR fallback for %s; dropped timing map (comment sync approximate)",
                       mp4_path.name)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    parser.add_argument("--file", help="normalize a single mp4 instead of scanning a dir")
    parser.add_argument("--record-dir", help="recordings dir to scan (default: server's configured dir)")
    parser.add_argument("--backup-dir", help="move each original mp4 here on success instead of "
                                             "overwriting it in place")
    args = parser.parse_args()
    backup_dir = Path(args.backup_dir) if args.backup_dir else None

    if not (ffmpeg_available() and ffprobe_available()):
        logger.error("ffmpeg/ffprobe not found on PATH")
        return 2

    if args.file:
        targets = [Path(args.file)]
    else:
        record_dir = Path(args.record_dir) if args.record_dir else Path(record_dir_from_db(get_db_path()))
        # Exclude burn-in outputs (raw recordings never contain ".overlay"; outputs are
        # named "<stem>.overlay.mp4" or a user-labelled "<stem>.overlay_<label>.mp4").
        # They are already single-resolution, so this only avoids wasting a scan on them.
        targets = sorted(p for p in record_dir.glob("*.mp4") if ".overlay" not in p.name)
    if not targets:
        logger.info("no recordings found")
        return 0

    changed = 0
    total = len(targets)
    start = time.monotonic()
    for i, mp4_path in enumerate(targets, 1):
        if not mp4_path.is_file():
            logger.warning("skip (missing): %s", mp4_path)
            continue
        # Progress before each scan: each probe reads the whole file (keyframes span it),
        # so a multi-hour recording takes tens of seconds on spinning disk. Report count,
        # elapsed and a running ETA so a long back-fill does not look hung.
        elapsed = time.monotonic() - start
        eta = elapsed / (i - 1) * (total - i + 1) if i > 1 else 0.0
        logger.info(
            "[%d/%d] scanning %s (elapsed %dm%02ds, eta %dm%02ds)",
            i, total, mp4_path.name,
            int(elapsed) // 60, int(elapsed) % 60, int(eta) // 60, int(eta) % 60,
        )
        if await normalize_one(mp4_path, args.apply, backup_dir):
            changed += 1
    logger.info(
        "%s %d of %d recording(s) with mixed resolution",
        "normalized" if args.apply else "would normalize", changed, len(targets),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
