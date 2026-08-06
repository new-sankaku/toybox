"""Re-mux already-finalized recordings onto the media axis, carrying their derived
timestamps across with them.

Recordings muxed by the old concat demuxer carry two defects at once: a ~0.1s audio
hole at every segment boundary (heard as clicking once the holes are stuffed, or as
Chrome running ahead of the video when they are packed away), and a container that
runs 2-6% longer than the media (#EXTINF) axis. Re-muxing through the HLS demuxer
removes both, which also means the container timeline SHRINKS by that 2-6%.

Everything derived from the old container axis therefore has to move with it:

    old container seconds -> media seconds -> new container seconds

Both halves are exact. The old timing sidecar's ``media_pts`` is the first map and is
monotonic, so it inverts; the freshly written sidecar is the second. This is why the
script must read the old sidecar BEFORE the re-mux overwrites it -- without it a
recording cannot be converted and is skipped rather than guessed at.

What moves, and how:
  transcripts.segments_json  converted in place (start/end)
  bookmarks.start/end        converted in place
  cut_list.start/end         converted in place
  search_hits                deleted for the recording; rebuilt from the converted
                             transcript and from comments (comments re-derive from the
                             new sidecar, so converting them would be a worse answer)
  semantic passages          deleted for the recording; rebuilt on next index run
  overlay mp4 + caches       deleted so the burn-in re-renders against the new axis

Safe-by-construction: the new mp4 is built to a temp file and only swapped in once it
validates (decodable video, no audio holes, duration within tolerance of the media
axis). The original is kept under the backup dir. The .ts segments are never touched,
so a recording can always be re-done. Idempotent: a recording already on the media
axis is skipped.

Usage (run from the TicTok directory, in the venv, with the server stopped):
    python scripts/remux_to_media_axis.py                    # dry-run, report only
    python scripts/remux_to_media_axis.py --apply --limit 1  # do one, verify, then more
    python scripts/remux_to_media_axis.py --apply
    python scripts/remux_to_media_axis.py --apply --base 00328_pomiiiip_20260720_112526
"""

from __future__ import annotations

import argparse
import asyncio
import bisect
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tictok.core import layout
from tictok.core.config import get_db_path, record_dir_from_db
from tictok.record import video_overlay
from tictok.record.recorder import (
    SIDECAR_SUFFIXES,
    Recorder,
    ffprobe_available,
    sidecar_dir,
    timing_path,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("tictok.remux_to_media_axis")

# Below this the container already tracks the media axis and there is nothing to fix.
INFLATION_THRESHOLD = 1.005
# The rebuilt container should land on the media axis; allow for the source declaring
# slightly different spans than it delivers.
DURATION_TOLERANCE = 0.01


# ------------------------------------------------------------------ measurement


def probe_duration(path: Path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
            capture_output=True, text=True, timeout=600).stdout
        return float(out.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def audio_holes(path: Path) -> int:
    """Audio pts discontinuities > 20ms -- the defect this whole exercise removes."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-i", str(path), "-select_streams", "a",
         "-show_entries", "packet=pts_time,duration_time", "-of", "csv=p=0"],
        capture_output=True, text=True).stdout
    holes, prev = 0, None
    for line in out.splitlines():
        parts = line.split(",")
        if len(parts) < 2:
            continue
        try:
            pts, dur = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        if prev is not None and pts - prev > 0.02:
            holes += 1
        prev = pts + dur
    return holes


def read_timing(mp4: Path):
    path = timing_path(mp4)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# -------------------------------------------------------------------- the map


def make_converter(old_media_pts: list, new_media_pts: list):
    """old container seconds -> new container seconds.

    Inverts the old media->pts correspondence (it is monotonic, so pts->media is well
    defined) and re-applies the new one. Values outside either table clamp to its ends
    rather than extrapolating, which keeps a stray timestamp inside the file.
    """
    old_media = [m for m, _ in old_media_pts]
    old_pts = [p for _, p in old_media_pts]
    new_media = [m for m, _ in new_media_pts]
    new_pts = [p for _, p in new_media_pts]

    def interp(x: float, xs: list, ys: list) -> float:
        if x <= xs[0]:
            return ys[0]
        if x >= xs[-1]:
            return ys[-1]
        k = bisect.bisect_right(xs, x)
        x0, x1, y0, y1 = xs[k - 1], xs[k], ys[k - 1], ys[k]
        return y1 if x1 <= x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)

    def convert(t: float) -> float:
        return round(interp(interp(t, old_pts, old_media), new_media, new_pts), 6)

    return convert


# --------------------------------------------------------------------- the work


def find_candidates(record_dir: Path, only_base):
    out = []
    for mp4 in sorted(record_dir.glob("*/mp4/*.mp4")):
        if mp4.name.endswith(video_overlay.OVERLAY_SUFFIX):
            continue
        if only_base and mp4.stem != only_base:
            continue
        timing = read_timing(mp4)
        media = (timing or {}).get("media_duration")
        media_pts = (timing or {}).get("media_pts")
        container = probe_duration(mp4)
        hls = layout.session_dir(record_dir, mp4.stem)
        reason = None
        if not timing or not media or not media_pts:
            reason = "media_ptsを持つtiming sidecarが無い(派生の時刻を変換できない)"
        elif not hls.is_dir() or not layout.has_media(hls):
            reason = ".tsのsegmentが残っていない"
        elif not container:
            reason = "mp4をprobeできない"
        elif container / media < INFLATION_THRESHOLD:
            reason = "既にmedia軸になっている(%.4f)" % (container / media)
        out.append({
            "mp4": mp4, "hls": hls, "timing": timing, "container": container,
            "media": media, "inflation": (container / media) if (container and media) else None,
            "skip": reason,
        })
    return out


async def remux(rec_item, record_dir: Path, backup_dir: Path) -> bool:
    """Build the new mp4 + sidecar beside the old one and swap it in. Returns True on
    success; on any failure the original is left exactly as it was."""
    mp4 = rec_item["mp4"]
    tmp = mp4.with_suffix(".remux.tmp.mp4")

    r = Recorder.__new__(Recorder)
    r.hls_dir = rec_item["hls"]
    r.playlist = r.hls_dir / "index.m3u8"
    r.base = mp4.stem
    r.unique_id = mp4.stem
    r._volume_paths = lambda: []

    kept = r._playlist_segments()
    if not kept:
        logger.error("  %s: 使えるsegmentが無いためskipしました", mp4.stem)
        return False
    if not await r._concat_to_mp4(tmp):
        logger.error("  %s: re-muxに失敗しました。元のfileはそのままです", mp4.stem)
        tmp.unlink(missing_ok=True)
        return False

    extinf_sum = sum(e for _, e, _, _, _ in kept)
    new_container = probe_duration(tmp)
    holes = audio_holes(tmp)
    if not new_container or abs(new_container - extinf_sum) / extinf_sum > DURATION_TOLERANCE:
        logger.error("  %s: 作り直したcontainer %.1fs がmedia軸 %.1fs と合わないため破棄しました",
                     mp4.stem, new_container or -1, extinf_sum)
        tmp.unlink(missing_ok=True)
        return False
    if holes:
        logger.error("  %s: 作り直したfileにまだ音声の穴が %d件あるため破棄しました",
                     mp4.stem, holes)
        tmp.unlink(missing_ok=True)
        return False

    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(mp4), str(backup_dir / mp4.name))
    old_sidecar = timing_path(mp4)
    if old_sidecar.is_file():
        shutil.copy2(str(old_sidecar), str(backup_dir / old_sidecar.name))
    os.replace(str(tmp), str(mp4))
    await r._write_timing_map(mp4)
    logger.info("  %s: %.1fs -> %.1fs（media軸 %.1fs）, 音声の穴 0件",
                mp4.stem, rec_item["container"], new_container, extinf_sum)
    return True


def drop_derived(conn: sqlite3.Connection, recording_id: int, convert) -> dict:
    """Convert what only exists on the container axis; delete what can be rebuilt."""
    counts = {"transcript_segments": 0, "bookmarks": 0, "cuts": 0,
              "search_hits": 0}

    row = conn.execute(
        "SELECT segments_json FROM transcripts WHERE recording_id=?",
        (recording_id,)).fetchone()
    if row and row[0]:
        try:
            segments = json.loads(row[0])
        except ValueError:
            segments = None
        if isinstance(segments, list):
            for seg in segments:
                for key in ("start", "end"):
                    if isinstance(seg.get(key), (int, float)):
                        seg[key] = convert(float(seg[key]))
            conn.execute("UPDATE transcripts SET segments_json=? WHERE recording_id=?",
                         (json.dumps(segments, ensure_ascii=False), recording_id))
            counts["transcript_segments"] = len(segments)

    for table in ("bookmarks", "cut_list"):
        try:
            rows = conn.execute(
                "SELECT id, start, end FROM %s WHERE recording_id=?" % table,
                (recording_id,)).fetchall()
        except sqlite3.OperationalError:
            continue
        for rid, start, end in rows:
            conn.execute(
                "UPDATE %s SET start=?, end=? WHERE id=?" % table,
                (convert(float(start)) if start is not None else start,
                 convert(float(end)) if end is not None else end, rid))
        counts["bookmarks" if table == "bookmarks" else "cuts"] += len(rows)

    cur = conn.execute("DELETE FROM search_hits WHERE recording_id=?", (recording_id,))
    counts["search_hits"] = cur.rowcount
    return counts


def drop_passages(semantic_db: Path, unique_id: str) -> int:
    if not semantic_db.is_file():
        return 0
    conn = sqlite3.connect(str(semantic_db))
    try:
        cur = conn.execute("DELETE FROM passages WHERE unique_id=?", (unique_id,))
        conn.execute("DELETE FROM indexed WHERE unique_id=?", (unique_id,))
        conn.commit()
        return cur.rowcount
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def drop_overlay(mp4: Path) -> list:
    """The burn-in output and its caches are keyed to the old axis; remove them so the
    next render rebuilds against the new one."""
    removed = []
    for path in [mp4.with_suffix(video_overlay.OVERLAY_SUFFIX)] + [
            sidecar_dir(mp4) / (mp4.stem + suffix) for suffix in SIDECAR_SUFFIXES
            if suffix != ".timing.json"]:
        if path.is_file():
            path.unlink()
            removed.append(path.name)
    return removed


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="process at most N recordings")
    ap.add_argument("--base", help="a single recording stem")
    ap.add_argument("--record-dir")
    ap.add_argument("--backup-dir")
    args = ap.parse_args()

    if not ffprobe_available():
        logger.error("ffprobeがPATHにありません")
        return 2

    db_path = Path(get_db_path())
    record_dir = (Path(args.record_dir) if args.record_dir
                  else Path(record_dir_from_db(db_path)))
    backup_dir = Path(args.backup_dir) if args.backup_dir else record_dir / "_backup_premux"
    semantic_db = db_path.parent / "semantic_index.db"

    items = find_candidates(record_dir, args.base)
    todo = [i for i in items if not i["skip"]]
    logger.info("録画 %d本を走査し、media軸へ移すべき録画は %d本", len(items), len(todo))
    for i in items:
        if i["skip"]:
            logger.info("  対象外 %-46s %s", i["mp4"].stem, i["skip"])
    for i in todo:
        logger.info("  対象 %-46s 膨張率 %.4f（%.0fs -> %.0fs）",
                    i["mp4"].stem, i["inflation"], i["container"], i["media"])
    if args.limit:
        todo = todo[:args.limit]
    if not args.apply:
        logger.info("dry-runです。書き込むには --apply を付けてください")
        return 0

    conn = sqlite3.connect(str(db_path))
    done = failed = 0
    for item in todo:
        stem = item["mp4"].stem
        logger.info("%s ...", stem)
        old_media_pts = item["timing"]["media_pts"]
        if not await remux(item, record_dir, backup_dir):
            failed += 1
            continue
        new_timing = read_timing(item["mp4"])
        if not new_timing or not new_timing.get("media_pts"):
            logger.error("  %s: 新しいsidecarにmedia_ptsが無いため派生の時刻を変換していません",
                         stem)
            failed += 1
            continue
        convert = make_converter(old_media_pts, new_timing["media_pts"])
        row = conn.execute("SELECT id FROM recordings WHERE path LIKE ?",
                           ("%" + item["mp4"].name,)).fetchone()
        if row:
            counts = drop_derived(conn, row[0], convert)
            conn.commit()
            logger.info("  変換しました: %s", counts)
        else:
            logger.warning("  %s: recordings行が無いためDB側をskipしました", stem)
        passages = drop_passages(semantic_db, stem)
        removed = drop_overlay(item["mp4"])
        logger.info("  削除したpassage=%d件, 削除した焼き込みの成果物=%s",
                    passages, removed or "無し")
        done += 1

    conn.close()
    logger.info("完了=%d 失敗=%d", done, failed)
    logger.info("次の作業: search_hits/passagesを作り直すため転写のindexingと意味検索のindexを"
                "再実行し、必要な焼き込みは出力し直してください")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
