"""Remove phantom PTS-discontinuity gaps from already-finalized recordings.

A glitched source timestamp can inflate a single HLS segment's media span (EXTINF)
far beyond the real wall-clock time it took to capture; concatenating it bakes a
phantom multi-minute frozen frame into the mp4 and makes the comment burn-in's time
map drift. The recorder now drops such segments at concat time, so new recordings
are clean — this script repairs existing ones whose retained HLS segments still
exist (i.e. recorded while "録画: HLS中間data(.ts)を保持する" was on).

For each recording dir that still has its segments, it detects discontinuity
segments by the same rule as the recorder (EXTINF dwarfs the segment's file-mtime
delta), and when any are found re-muxes the mp4 from the surviving segments (stream
copy, no re-encode), rewrites the wall->media timing map without the phantom, and
removes the stale burn-in cache so it re-renders against the clean mp4.

Safe-by-construction: a recording is only touched when a discontinuity is detected
AND the re-muxed mp4 validates (decodable video, the large gap is gone, duration
shrank); the new mp4 is written to a temp file and atomically swapped in. The HLS
segments are the complete source and are left in place, so a repair can always be
re-run. Idempotent: a recording with no discontinuity is skipped.

Usage (run from the TicTok directory):
    python scripts/repair_pts_gaps.py            # dry-run, report only
    python scripts/repair_pts_gaps.py --apply    # write changes
    python scripts/repair_pts_gaps.py --record-dir other/recordings --apply
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tictok.core import layout
from tictok.core.config import get_db_path, record_dir_from_db
from tictok.record.recorder import (
    PTS_DISCONTINUITY_MIN_SECONDS,
    ffprobe_available,
    is_pts_discontinuity,
    sidecar_path,
    timing_path,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("tictok.repair_pts")


def _read_playlist(hls_dir: Path) -> list:
    """[(segment_path, extinf_seconds)] in playlist order, or [] if unreadable."""
    playlist = hls_dir / "index.m3u8"
    if not playlist.is_file():
        return []
    out: list = []
    pending = None
    try:
        lines = playlist.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if line.startswith("#EXTINF:"):
            try:
                pending = float(line[len("#EXTINF:"):].split(",", 1)[0])
            except ValueError:
                pending = None
        elif line and not line.startswith("#"):
            seg = hls_dir / line
            if pending is not None and seg.is_file():
                out.append((seg, pending))
            pending = None
    return out


def _classify(segments: list) -> tuple[list, list]:
    """Split [(seg, extinf)] into (kept, dropped) by the recorder's discontinuity
    rule: a segment whose EXTINF dwarfs its file-mtime delta from the previous
    segment carries a glitched timestamp. dropped is [(name, extinf, wall)]."""
    kept: list = []
    dropped: list = []
    prev_mtime = None
    for seg, extinf in segments:
        try:
            mtime = seg.stat().st_mtime
        except OSError:
            kept.append(seg)
            prev_mtime = None
            continue
        wall = mtime - prev_mtime if prev_mtime is not None else None
        prev_mtime = mtime
        if wall is not None and is_pts_discontinuity(extinf, wall):
            dropped.append((seg.name, extinf, wall))
            continue
        kept.append(seg)
    return kept, dropped


def _probe_duration(path: Path) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True,
        ).stdout.strip()
        return float(out) if out else None
    except (OSError, ValueError):
        return None


def _max_pts_gap(path: Path) -> float:
    """Largest forward jump between consecutive video packet PTS (seconds)."""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(path)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return 0.0
    prev = None
    mx = 0.0
    for line in proc.stdout.splitlines():
        line = line.strip().rstrip(",")
        if not line:
            continue
        try:
            t = float(line)
        except ValueError:
            continue
        if prev is not None and t - prev > mx:
            mx = t - prev
        prev = t
    return mx


def _remux(kept: list, dst: Path) -> bool:
    """Concat the surviving segments into dst (stream copy). Mirrors the recorder's
    finalize concat so the repaired mp4 matches what a fresh recording would now
    produce."""
    list_path = dst.parent / (dst.stem + ".concat.txt")
    try:
        list_path.write_text("".join(f"file '{seg.resolve().as_posix()}'\n" for seg in kept), encoding="utf-8")
        proc = subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
             "-fflags", "+genpts", "-f", "concat", "-safe", "0", "-i", str(list_path),
             "-c", "copy", "-movflags", "+faststart", "-avoid_negative_ts", "make_zero", str(dst)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return proc.returncode == 0 and dst.is_file() and dst.stat().st_size > 0
    except OSError:
        logger.warning("re-mux failed for %s", dst, exc_info=True)
        return False
    finally:
        list_path.unlink(missing_ok=True)


def _overlay_artifacts(mp4_path: Path) -> list:
    # The burned-in overlay mp4 sits in the recordings root next to its source; the
    # ass/meta render artifacts stay under .sidecars (see video_overlay.overlay_paths).
    return [
        mp4_path.with_name(mp4_path.stem + ".overlay.mp4"),
        sidecar_path(mp4_path, ".overlay.ass"),
        sidecar_path(mp4_path, ".overlay.meta"),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    parser.add_argument("--record-dir", default=None, help="recordings directory (default: project setting)")
    args = parser.parse_args()

    if not ffprobe_available():
        logger.error("ffprobe/ffmpeg not found on PATH; cannot validate or re-mux.")
        return 2

    record_dir = Path(args.record_dir) if args.record_dir else Path(record_dir_from_db(get_db_path()))
    if not record_dir.is_dir():
        logger.error("recordings directory not found: %s", record_dir)
        return 2

    repaired = 0
    scanned = 0
    for hls_dir in layout.iter_sessions(record_dir):
        segments = _read_playlist(hls_dir)
        if not segments:
            continue
        mp4_path = layout.mp4_path(record_dir, hls_dir.name)
        if not mp4_path.is_file():
            continue
        scanned += 1
        kept, dropped = _classify(segments)
        if not dropped:
            continue
        phantom = sum(e for _, e, _ in dropped)
        logger.info(
            "%s: %d discontinuity segment(s), ~%.0fs phantom -> %s",
            hls_dir.name, len(dropped), phantom,
            ", ".join("%s(EXTINF=%.0fs wall=%.1fs)" % (n, e, w) for n, e, w in dropped),
        )
        if not args.apply:
            continue

        tmp = mp4_path.with_name(mp4_path.stem + ".repair.tmp.mp4")
        if not _remux(kept, tmp):
            logger.error("  re-mux failed; left untouched")
            tmp.unlink(missing_ok=True)
            continue
        old_dur = _probe_duration(mp4_path) or 0.0
        new_dur = _probe_duration(tmp) or 0.0
        gap = _max_pts_gap(tmp)
        if new_dur <= 0 or gap >= PTS_DISCONTINUITY_MIN_SECONDS or new_dur >= old_dur:
            logger.error(
                "  validation failed (old=%.0fs new=%.0fs max_gap=%.0fs); left untouched",
                old_dur, new_dur, gap,
            )
            tmp.unlink(missing_ok=True)
            continue
        os.replace(tmp, mp4_path)
        # Rebuild the phantom-free timing map and drop the stale burn-in cache so it
        # re-renders against the clean mp4.
        _rewrite_timing(segments, dropped, mp4_path)
        for art in _overlay_artifacts(mp4_path):
            art.unlink(missing_ok=True)
        logger.info("  repaired: %.0fs -> %.0fs (max gap now %.1fs)", old_dur, new_dur, gap)
        repaired += 1

    logger.info(
        "%s: scanned %d recording(s) with retained HLS, %s %d.",
        "applied" if args.apply else "dry-run", scanned,
        "repaired" if args.apply else "would repair", repaired,
    )
    return 0


def _rewrite_timing(segments: list, dropped: list, mp4_path: Path) -> None:
    """Rewrite <stem>.timing.json from the playlist, skipping the dropped
    discontinuity segments so the media axis stays gap-free and aligned with the
    re-muxed mp4 (same shape as Recorder._write_timing_map)."""
    dropped_names = {n for n, _, _ in dropped}
    media = 0.0
    anchors: list = []
    for seg, extinf in segments:
        try:
            wall = seg.stat().st_mtime
        except OSError:
            continue
        if seg.name in dropped_names:
            continue
        media += extinf
        anchors.append((wall, round(media, 6)))
    if len(anchors) < 2:
        return
    anchors.sort(key=lambda a: a[0])
    anchors.insert(0, (anchors[0][0] - anchors[0][1], 0.0))
    payload = {
        "version": 1,
        "media_duration": anchors[-1][1],
        "anchors": [[w, m] for w, m in anchors],
    }
    out = timing_path(mp4_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
