"""Fill audio gaps in already-finalized recordings so they play in sync everywhere.

The captured HLS stream drops audio across segment boundaries, leaving the finalized
mp4's audio track with fewer samples than its own timestamps span (3-5% is typical;
one 4h recording was short by 9 minutes). Players disagree on what to do with those
holes: VLC honours the timestamps and inserts silence, staying in sync, while Chrome
packs the samples back to back so the audio runs ahead of the video by the full
deficit — which is why the same file looks fine in a desktop player and drifts in the
browser UI. The recorder now fills the holes at concat time, so new recordings are
clean; this script repairs existing ones.

Only the audio is touched: video is stream-copied, so the picture is bit-identical and
the media timeline that transcripts, the heat graph, the comment burn-in and saved
IN/OUT points are all expressed against stays valid. aresample places the surviving
audio at its own timestamps (measured: lag 0.000s, envelope correlation 0.9999 against
a timestamp-honouring decode of the original), so nothing shifts.

Safe-by-construction: a recording is only replaced when the repaired file validates —
video duration and packet count unchanged, and the gap actually gone. The repair is
written to a temp file and swapped in; the original is kept under _backup/ unless
--no-backup is given. Idempotent: a recording without a gap is skipped, so a run can
be repeated or resumed after an interruption.

Usage (run from the TicTok directory):
    python scripts/repair_audio_gaps.py                 # dry-run, report only
    python scripts/repair_audio_gaps.py --apply         # repair
    python scripts/repair_audio_gaps.py --apply --limit 1
    python scripts/repair_audio_gaps.py --record-dir K:/80_Tiktok --apply
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tictok.core.config import get_db_path, record_dir_from_db

logger = logging.getLogger("repair_audio_gaps")

# A real hole shows up as a positive deficit; the encoder's priming and padding samples
# push a clean track slightly negative instead. Measured over 231 existing recordings:
# clean tracks sit between -43ms and -2.5ms, a repaired track lands at about -27ms, and
# the smallest genuine hole is +83ms — the next one up is +411ms. 50ms therefore clears
# the noise floor in both directions: it never touches a clean or already-repaired file
# (so repeated runs are a no-op), and it still catches the smallest real gap. It is also
# below the threshold where a leading audio offset becomes audible (~45ms), so whatever
# stays under it cannot be heard.
AUDIO_GAP_MIN_SECONDS = 0.05
# HE-AAC carries 2048 samples per frame (the SBR-doubled output rate), plain AAC 1024.
SAMPLES_PER_FRAME = {"HE-AAC": 2048}
DEFAULT_SAMPLES_PER_FRAME = 1024
AUDIO_BITRATE = "192k"
# Slack for the remuxed final-frame duration (see video_survived); one frame is ~40ms.
VIDEO_DURATION_TOLERANCE = 1.0
BACKUP_DIRNAME = "_backup"
TEMP_SUFFIX = ".repair.mp4"
# Observed transient read failures under heavy parallel disk load; one retry after a
# pause recovers them without re-running the whole pass.
RETRY_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 30


def _ffprobe_stream(path: Path, selector: str, entries: str) -> dict:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", selector,
         "-show_entries", f"stream={entries}", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {proc.stderr.strip()}")
    streams = json.loads(proc.stdout or "{}").get("streams") or []
    if not streams:
        raise RuntimeError(f"no {selector} stream in {path}")
    return streams[0]


def audio_gap_seconds(path: Path) -> float:
    """Seconds of timeline the audio track claims but has no samples for."""
    stream = _ffprobe_stream(path, "a:0", "profile,nb_frames,duration,sample_rate")
    frames = int(stream["nb_frames"])
    duration = float(stream["duration"])
    rate = int(stream["sample_rate"])
    per_frame = SAMPLES_PER_FRAME.get(stream.get("profile"), DEFAULT_SAMPLES_PER_FRAME)
    return duration - frames * per_frame / rate


def video_signature(path: Path) -> tuple:
    """(duration, frame count) of the video track."""
    stream = _ffprobe_stream(path, "v:0", "duration,nb_frames")
    return float(stream["duration"]), int(stream["nb_frames"])


def video_survived(before: tuple, after: tuple) -> bool:
    """Whether the repair left the picture alone.

    Frame count is the strict invariant: the video is stream-copied, so a single
    frame more or less means something was decoded, dropped or re-timed. The track
    duration is allowed to move a little because the muxer rewrites the final frame's
    duration to the track average when remuxing — verified bit-identical video (equal
    MD5 of the copied stream) with the reported duration differing by ~41ms, one frame
    at 25fps. Real damage is not subtle at this scale: an earlier bad approach shifted
    the track by 74 seconds."""
    return before[1] == after[1] and abs(before[0] - after[0]) <= VIDEO_DURATION_TOLERANCE


def repair(src: Path, dst: Path) -> None:
    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(src),
         "-c:v", "copy",
         "-c:a", "aac", "-b:a", AUDIO_BITRATE,
         "-af", "aresample=async=1:first_pts=0",
         "-movflags", "+faststart", str(dst)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.strip()[:400]}")


def iter_recordings(roots: list) -> list:
    seen = set()
    out = []
    for root in roots:
        for path in sorted(root.glob("*/mp4/*.mp4")):
            # A run killed mid-repair leaves partial temp files behind; they end in
            # .mp4 too, so they would otherwise be picked up as recordings.
            if path.name.endswith(TEMP_SUFFIX):
                continue
            key = str(path.resolve()).lower()
            if key not in seen:
                seen.add(key)
                out.append(path)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="write changes (default: dry-run)")
    parser.add_argument("--record-dir", action="append", default=None,
                        help="recordings root; repeatable (default: project settings)")
    parser.add_argument("--streamer", action="append", default=None,
                        help="only this streamer's recordings; repeatable")
    parser.add_argument("--limit", type=int, default=None,
                        help="stop after this many repairs")
    parser.add_argument("--no-backup", action="store_true",
                        help="replace in place without keeping the original")
    # Video is stream-copied and only the audio is encoded, so a single repair uses
    # about one core and leaves the disk as the limit. Measured on the final root:
    # 5.4 MB/s at one job, 7.8 at four, 9.7 at eight — worth running several at once,
    # but the curve flattens because reads and writes share the same drive.
    parser.add_argument("--jobs", type=int, default=1,
                        help="repairs to run concurrently (default: 1)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.record_dir:
        roots = [Path(d) for d in args.record_dir]
    else:
        # Both the working root and the final root hold mp4s; completed recordings
        # relocate from one to the other, so a repair pass has to cover both.
        import sqlite3
        db_path = get_db_path()
        roots = [Path(record_dir_from_db(db_path))]
        try:
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT value FROM settings WHERE key = 'record_dir_final'"
                ).fetchone()
            if row and row[0] and Path(row[0]).resolve() != roots[0].resolve():
                roots.append(Path(row[0]))
        except sqlite3.Error:
            logger.warning("record_dir_finalを読めないためwork rootのみ走査します")
    roots = [r for r in roots if r.is_dir()]
    if not roots:
        logger.error("録画dirが見つかりません")
        return 1
    for root in roots:
        logger.info("走査します: %s", root)

    recordings = iter_recordings(roots)
    if args.streamer:
        # Layout is <root>/<streamer>/mp4/<file>.mp4, so the streamer is the mp4 dir's
        # parent. Lets one streamer be finished off without waiting on the rest.
        wanted = {s.lower() for s in args.streamer}
        recordings = [p for p in recordings if p.parent.parent.name.lower() in wanted]
        logger.info("配信者で絞り込みます: %s", ", ".join(sorted(wanted)))
    logger.info("mp4 file %d件が見つかりました\n", len(recordings))

    skipped = 0
    worklist = []
    for path in recordings:
        try:
            gap = audio_gap_seconds(path)
        except (RuntimeError, KeyError, ValueError) as exc:
            logger.warning("skip  %s（音声の穴を測れません: %s）", path.name, exc)
            skipped += 1
            continue
        if gap < AUDIO_GAP_MIN_SECONDS:
            skipped += 1
            continue
        worklist.append((path, gap))
        if args.limit and len(worklist) >= args.limit:
            break

    if not args.apply:
        for path, gap in worklist:
            logger.info("修復(dry-run) %-52s 音声の穴=%8.1fs", path.name[:52], gap)
        logger.info("\ndry-run: 修復=%d 失敗=0 skip(穴なし)=%d",
                    len(worklist), skipped)
        return 0

    total_bytes = sum(p.stat().st_size for p, _ in worklist)
    logger.info("%d件 %.1f GB を修復します（job %d並列）\n",
                len(worklist), total_bytes / 1024 ** 3, args.jobs)

    def repair_one(item) -> bool:
        path, gap = item
        started = time.monotonic()
        tmp = path.with_name(path.name + TEMP_SUFFIX)
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            ok, detail = _attempt(path, tmp, gap, started)
            if ok:
                return True
            if attempt < RETRY_ATTEMPTS:
                # Failures here have been observed to be transient: a run at eight jobs
                # had every remaining file fail to read after the drive was hammered,
                # yet each of those files repaired fine on its own afterwards. Back off
                # and let the drive settle rather than burning the whole pass.
                logger.warning("再試行 %-52s %s", path.name[:52], detail)
                time.sleep(RETRY_DELAY_SECONDS * attempt)
        logger.error("失敗  %-52s %s", path.name[:52], detail)
        return False

    def _attempt(path: Path, tmp: Path, gap: float, started: float) -> tuple:
        try:
            before = video_signature(path)
            repair(path, tmp)
            after = video_signature(tmp)
            if not video_survived(before, after):
                raise RuntimeError(f"video changed {before} -> {after}")
            new_gap = audio_gap_seconds(tmp)
            if new_gap >= AUDIO_GAP_MIN_SECONDS:
                raise RuntimeError(f"gap still {new_gap:.1f}s")
            if args.no_backup:
                path.unlink()
            else:
                backup_dir = path.parent / BACKUP_DIRNAME
                backup_dir.mkdir(exist_ok=True)
                path.replace(backup_dir / path.name)
            tmp.replace(path)
        except (RuntimeError, OSError) as exc:
            # Cleanup must not mask the real error: on Windows the temp file can still
            # be held briefly by the ffmpeg process that just died, and an unlink that
            # raises here would replace the useful message with a PermissionError.
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                logger.warning("%s を削除できません。手で削除してください", tmp.name)
            return False, str(exc)
        logger.info("完了  %-52s 音声の穴 %8.1fs -> %.2fs（%.0fs）",
                    path.name[:52], gap, new_gap, time.monotonic() - started)
        return True, ""

    if args.jobs > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(args.jobs) as pool:
            results = list(pool.map(repair_one, worklist))
    else:
        results = [repair_one(item) for item in worklist]
    repaired = sum(results)
    failed = len(results) - repaired

    logger.info("\n実行しました: 修復=%d 失敗=%d skip(穴なし)=%d",
                repaired, failed, skipped)
    if not args.no_backup and repaired:
        logger.info("元のfileは %s/ に残しています。結果を確認したら削除してください",
                    BACKUP_DIRNAME)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
