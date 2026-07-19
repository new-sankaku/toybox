"""Add the exact media->pts axis to already-finalized recordings' timing maps.

The concatenated mp4's PTS runs longer than the media (EXTINF) axis by a roughly
fixed per-segment mux overhead. The burn-in used to model that as one proportional
scale, which drifts comments by tens of seconds mid-stream because segment lengths
vary. The recorder now records each kept segment's real PTS contribution as an exact
media->pts correspondence (timing.json ``media_pts``, version 2); this script
back-fills it for recordings whose HLS segments were retained (録画: HLS中間data(.ts)を
保持する was on).

For each recording dir that still has its segments, it rebuilds timing.json from the
playlist — the same kept-segment sequence and PTS-discontinuity filter the recorder
uses — probing each segment's duration to build the media->pts axis, then drops the
stale burn-in cache so it re-renders against the corrected map. Idempotent and
best-effort: a recording whose segments cannot be fully probed, or whose mp4 is
missing, is skipped and left untouched.

Usage (run from the TicTok directory):
    python scripts/repair_timing_pts.py            # dry-run, report only
    python scripts/repair_timing_pts.py --apply    # write changes
    python scripts/repair_timing_pts.py --record-dir other/recordings --apply
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
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
    ffprobe_available,
    is_pts_discontinuity,
    media_pts_from_segments,
    sidecar_path,
    timing_path,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("tictok.repair_timing_pts")


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


def _kept_segments(segments: list) -> list:
    """[(seg, extinf, wall)] with PTS-discontinuity segments removed, matching the
    recorder's finalize filter (EXTINF dwarfs the file-mtime delta => glitched)."""
    kept: list = []
    prev_wall = None
    for seg, extinf in segments:
        try:
            wall = seg.stat().st_mtime
        except OSError:
            prev_wall = None
            continue
        wall_delta = wall - prev_wall if prev_wall is not None else None
        prev_wall = wall
        if wall_delta is not None and is_pts_discontinuity(extinf, wall_delta):
            continue
        kept.append((seg, extinf, wall))
    return kept


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


def _probe_durations(paths: list) -> list:
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        return list(ex.map(_probe_duration, paths))


def _overlay_artifacts(mp4_path: Path) -> list:
    return [
        mp4_path.with_name(mp4_path.stem + ".overlay.mp4"),
        mp4_path.with_name(mp4_path.stem + ".overlay.b.mp4"),
        sidecar_path(mp4_path, ".overlay.ass"),
        sidecar_path(mp4_path, ".overlay.meta"),
        sidecar_path(mp4_path, ".overlay.b.ass"),
        sidecar_path(mp4_path, ".overlay.b.meta"),
        sidecar_path(mp4_path, ".timing.debug.json"),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    parser.add_argument("--record-dir", default=None, help="recordings directory (default: project setting)")
    args = parser.parse_args()

    if not ffprobe_available():
        logger.error("ffprobe/ffmpeg not found on PATH; cannot probe segment durations.")
        return 2

    record_dir = Path(args.record_dir) if args.record_dir else Path(record_dir_from_db(get_db_path()))
    if not record_dir.is_dir():
        logger.error("recordings directory not found: %s", record_dir)
        return 2

    repaired = scanned = 0
    for hls_dir in layout.iter_sessions(record_dir):
        segments = _read_playlist(hls_dir)
        if not segments:
            continue
        mp4_path = layout.mp4_path(record_dir, hls_dir.name)
        if not mp4_path.is_file():
            continue
        scanned += 1

        # Already has the exact axis? skip (idempotent).
        tpath = timing_path(mp4_path)
        try:
            if tpath.is_file():
                existing = json.loads(tpath.read_text(encoding="utf-8"))
                if isinstance(existing, dict) and existing.get("media_pts"):
                    continue
        except (OSError, ValueError):
            pass

        kept = _kept_segments(segments)
        if len(kept) < 2:
            continue

        media = 0.0
        anchors: list = []
        for _, extinf, wall in kept:
            media += extinf
            anchors.append((wall, round(media, 6)))
        anchors.insert(0, (anchors[0][0] - anchors[0][1], 0.0))

        mp4_dur = _probe_duration(mp4_path)
        durations = _probe_durations([seg for seg, _, _ in kept])
        media_pts = media_pts_from_segments([e for _, e, _ in kept], durations, mp4_dur)
        if media_pts is None:
            logger.info("%s: segment durations incomplete or mp4 unprobed; skipped", hls_dir.name)
            continue

        drift = mp4_dur - anchors[-1][1] if mp4_dur else 0.0
        logger.info(
            "%s: %d kept segments, media=%.0fs mp4=%.0fs (mux inflation %.0fs) -> media_pts[%d]",
            hls_dir.name, len(kept), anchors[-1][1], mp4_dur or 0.0, drift, len(media_pts),
        )
        if not args.apply:
            continue

        payload = {
            "version": 2,
            "media_duration": anchors[-1][1],
            "anchors": [[w, m] for w, m in anchors],
            "media_pts": media_pts,
        }
        try:
            tpath.parent.mkdir(parents=True, exist_ok=True)
            tpath.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            logger.warning("  failed to write timing map; left untouched", exc_info=True)
            continue
        for art in _overlay_artifacts(mp4_path):
            art.unlink(missing_ok=True)
        logger.info("  timing map rebuilt with media_pts; stale burn-in cache dropped")
        repaired += 1

    logger.info(
        "%s: scanned %d recording(s) with retained HLS, %s %d.",
        "applied" if args.apply else "dry-run", scanned,
        "repaired" if args.apply else "would repair", repaired,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
