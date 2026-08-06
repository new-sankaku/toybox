"""DBに焼き付いた「秒」を、mp4のPTS軸からHLSのmedia軸へ移す。

再生がHLSになった録画では、playerの現在位置は playlist の #EXTINF 累積 = media軸である。
一方 search_hits.video_time などに入っているのは、finalize時のmp4のPTS軸で計算した秒で、
両者は一致しない。実測(v2録画96件)では中央値0.440秒だが、45件が1秒を超え、最大は536秒
(約9分)だった。差が大きいのは主にA/Vズレ修正より前の録画である。放置すると、検索hitや
bookmarkをclickした時に**録画によっては数分ずれた場所へ飛ぶ**。

変換は timing.json の ``media_pts``(media↔pts の対応点列)で行う。pts側を横軸にして
media側へ線形補間するだけで、往復に誤差は入らない。``media_pts`` を持たない版(version-1)の
録画は変換できないが、それらは .ts が1本も残っておらず今後もmp4で再生するため、pts軸のまま
据え置くのが正しい(変換の必要が無い)。

対象は「HLSで再生する録画」= .ts が残っている録画に限る。recordings.time_axis に実際の軸を
記録し、二重適用を防ぐ。

Usage (TicTokディレクトリから、venvで):
    python scripts/migrate_time_axis_to_media.py                 # dry-run(既定)
    python scripts/migrate_time_axis_to_media.py --apply         # 書き換える
    python scripts/migrate_time_axis_to_media.py --recording 42  # 1件だけ
"""
from __future__ import annotations

import argparse
import bisect
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tictok.core import layout
from tictok.core.config import get_db_path
from tictok.record.recorder import timing_path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("migrate_time_axis")


def pts_to_media_mapper(media_pts: list):
    """f(pts秒) -> media秒。``media_pts`` は [[media, pts], ...] の昇順対応点列。

    端は clamp する。対応点の外側にある値は、録画の外を指しているか丸め誤差のどちらかで、
    どちらにしても録画の内側へ寄せるのが正しい。"""
    xs = [p for _, p in media_pts]
    ys = [m for m, _ in media_pts]
    if len(xs) < 2:
        return None

    def to_media(p: float) -> float:
        if p <= xs[0]:
            return ys[0]
        if p >= xs[-1]:
            return ys[-1]
        k = bisect.bisect_right(xs, p)
        x0, x1, y0, y1 = xs[k - 1], xs[k], ys[k - 1], ys[k]
        return y1 if x1 <= x0 else y0 + (y1 - y0) * (p - x0) / (x1 - x0)

    return to_media


def _has_segments(record_roots, stem: str) -> bool:
    return any(layout.has_media(layout.session_dir(root, stem)) for root in record_roots)


def _load_media_pts(mp4_path: Path):
    try:
        data = json.loads(timing_path(mp4_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    points = data.get("media_pts")
    return points if isinstance(points, list) and len(points) >= 2 else None


def _convert_rows(con, table: str, columns: tuple, recording_id: int, to_media) -> tuple:
    """1 tableの該当列を変換する。(書き換えた行数, 最大移動秒) を返す。"""
    cols = ", ".join(columns)
    rows = con.execute(
        f"SELECT rowid AS _rid, {cols} FROM {table} WHERE recording_id = ?", (recording_id,)
    ).fetchall()
    changed = 0
    worst = 0.0
    for row in rows:
        updates = {}
        for name in columns:
            value = row[name]
            if value is None:
                continue
            moved = to_media(float(value))
            worst = max(worst, abs(moved - float(value)))
            updates[name] = moved
        if not updates:
            continue
        assignments = ", ".join(f"{k} = ?" for k in updates)
        con.execute(f"UPDATE {table} SET {assignments} WHERE rowid = ?",
                    (*updates.values(), row["_rid"]))
        changed += 1
    return changed, worst


def _convert_transcript(con, recording_id: int, to_media) -> tuple:
    row = con.execute(
        "SELECT rowid AS _rid, segments_json FROM transcripts WHERE recording_id = ?",
        (recording_id,),
    ).fetchone()
    if row is None or not row["segments_json"]:
        return 0, 0.0
    try:
        segments = json.loads(row["segments_json"])
    except ValueError:
        return 0, 0.0
    if not isinstance(segments, list):
        return 0, 0.0
    worst = 0.0
    for seg in segments:
        for key in ("start", "end"):
            value = seg.get(key)
            if value is None:
                continue
            moved = to_media(float(value))
            worst = max(worst, abs(moved - float(value)))
            seg[key] = moved
    con.execute("UPDATE transcripts SET segments_json = ? WHERE rowid = ?",
                (json.dumps(segments, ensure_ascii=False), row["_rid"]))
    return len(segments), worst


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="書き換える(既定はdry-run)")
    parser.add_argument("--recording", type=int, help="この録画IDだけを対象にする")
    parser.add_argument("--db", help="DB path(既定はserverと同じ解決)")
    args = parser.parse_args()

    db_path = args.db or get_db_path()
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    record_roots = []
    for key in ("record_dir", "record_dir_final"):
        row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row and row["value"]:
            record_roots.append(Path(row["value"]))
    if not record_roots:
        logger.error("record rootが解決できません")
        return 2

    query = "SELECT id, path, filename, time_axis FROM recordings"
    params: tuple = ()
    if args.recording:
        query += " WHERE id = ?"
        params = (args.recording,)
    recordings = con.execute(query, params).fetchall()

    converted = skipped_axis = skipped_no_ts = skipped_no_map = 0
    for rec in recordings:
        stem = Path(rec["filename"] or "").stem
        if rec["time_axis"] == "media":
            skipped_axis += 1
            continue
        if not stem or not _has_segments(record_roots, stem):
            skipped_no_ts += 1
            continue
        mp4_path = Path(rec["path"]) if rec["path"] else None
        media_pts = _load_media_pts(mp4_path) if mp4_path else None
        to_media = pts_to_media_mapper(media_pts) if media_pts else None
        if to_media is None:
            # media_ptsが無い録画は変換できない。.tsがあるのにmapが古い形なので、
            # 作り直す(scripts/repair_timing_pts.py)まではpts軸のまま残す。
            logger.warning("  skip %s: media_ptsが無く変換できません", stem)
            skipped_no_map += 1
            continue

        hits, worst_hits = _convert_rows(
            con, "search_hits", ("video_time", "end_time"), rec["id"], to_media)
        marks, worst_marks = _convert_rows(
            con, "bookmarks", ("start", "end"), rec["id"], to_media)
        cuts, worst_cuts = _convert_rows(
            con, "cut_list", ("start", "end"), rec["id"], to_media)
        segs, worst_segs = _convert_transcript(con, rec["id"], to_media)
        worst = max(worst_hits, worst_marks, worst_cuts, worst_segs)
        con.execute("UPDATE recordings SET time_axis = 'media' WHERE id = ?", (rec["id"],))
        converted += 1
        logger.info(
            "%s%s: hits=%d bookmarks=%d cuts=%d transcript_segments=%d  最大移動=%.3fs",
            "" if args.apply else "[dry-run] ", stem[:44], hits, marks, cuts, segs, worst,
        )

    if args.apply:
        con.commit()
    else:
        con.rollback()
    logger.info(
        "\n%s %d件を変換 / 済み %d / .ts無し %d / map無し %d",
        "適用:" if args.apply else "[dry-run] 変換対象:",
        converted, skipped_axis, skipped_no_ts, skipped_no_map,
    )
    if not args.apply:
        logger.info("書き換えるには --apply を付けてください")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
