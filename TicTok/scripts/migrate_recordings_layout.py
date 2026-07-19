"""Reorganize a flat recordings root into the per-streamer layout.

Before (flat), each record root holds side by side:
    <root>/<stem>/seg*.ts            ... HLS session dir
    <root>/<stem>.mp4                ... finished recording
    <root>/<stem>.overlay*.mp4       ... burned-in output(s)
    <root>/<stem>.up.mp4             ... upscaled output

After (per-streamer), the same files are grouped by streamer (unique_id):
    <root>/<streamer>/ts/<stem>/seg*.ts
    <root>/<streamer>/mp4/<stem>.mp4
    <root>/<streamer>/mp4/<stem>.overlay*.mp4
    <root>/<streamer>/mp4/<stem>.up.mp4

stem = ``NNNNN_<streamer>_YYYYMMDD_HHMMSS``. Shared caches kept at the root
(.sidecars, avatars, emotes, gift_icons, _backup) are never touched. The DB
``recordings.path`` values are rewritten to the new mp4 locations so playback and
delete keep resolving. Runs on the working record dir and the final(archive) dir.

Moves are same-root renames (instant even for multi-GB files). Idempotent: entries
already under a streamer folder are skipped, so a re-run is a no-op.

Usage (run from the TicTok directory, venv active):
    python scripts/migrate_recordings_layout.py            # dry-run, report only
    python scripts/migrate_recordings_layout.py --apply    # perform the move
    python scripts/migrate_recordings_layout.py --record-dir K:\\80_Tiktok --apply
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tictok.core import layout
from tictok.core.config import get_db_path, get_record_dir, record_dir_from_db

# Root-level shared dirs that are never per-streamer and must stay put.
_KEEP_DIRS = {".sidecars", "avatars", "emotes", "gift_icons", "_backup"}
# The recording stem prefixing any related file name (mp4/overlay/up). The trailing
# _<8digits>_<6digits> stamp anchors the end even when the streamer contains '.'/'_'.
# Matches both the current (NNNNN_ prefixed) and legacy (no prefix) naming; which one
# it is, and the streamer, is decided by layout.streamer_of on the captured stem.
_STEM_PREFIX_RE = re.compile(r"^(.+_\d{8}_\d{6})")


def _final_dir_from_db(db_path: str) -> str:
    """The UI-set 'record_dir_final' (archive) setting, or '' when unset."""
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'record_dir_final'"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return ""
    if row and row[0] and str(row[0]).strip():
        return str(row[0]).strip()
    return os.environ.get("TICTOK_RECORD_DIR_FINAL", "")


def _stem_of_name(name: str):
    """The recording stem that a root-level file/dir name belongs to, or None."""
    m = _STEM_PREFIX_RE.match(name)
    return m.group(1) if m else None


def _plan_root(root: Path):
    """(moves, skipped) for one root. moves: list of (src, dst, kind)."""
    moves = []
    skipped = 0
    if not root.is_dir():
        return moves, skipped
    for entry in sorted(root.iterdir()):
        name = entry.name
        if name in _KEEP_DIRS:
            continue
        if entry.is_dir():
            # A flat HLS session dir is named exactly as the stem.
            streamer = layout.streamer_of(name)
            if not streamer:
                continue  # already-nested streamer folder or unrelated dir
            dst = layout.session_dir(root, name, streamer)
            if dst == entry:
                continue
            moves.append((entry, dst, "ts"))
        elif entry.is_file() and name.lower().endswith(".mp4"):
            stem = _stem_of_name(name)
            if not stem:
                continue
            streamer = layout.streamer_of(stem)
            if not streamer:
                continue
            dst = layout.mp4_dir(root, stem, streamer) / name
            if dst == entry:
                continue
            moves.append((entry, dst, "mp4"))
        else:
            skipped += 1
    return moves, skipped


def _move(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        raise FileExistsError(f"destination already exists: {dst}")
    try:
        os.rename(src, dst)  # instant within the same volume
    except OSError:
        shutil.move(str(src), str(dst))  # cross-volume fallback (copy+unlink)


def _resolve_real_mp4(roots, stem: str, streamer: str, name: str):
    """The mp4's true nested location, searched across both roots (a recording may have
    been archived to the final dir). None when the file is not found in either."""
    for root in roots:
        cand = layout.mp4_dir(root, stem, streamer) / name
        if cand.is_file():
            return cand
    return None


def _update_db_paths(db_path: str, roots, apply: bool) -> int:
    """Repair recordings.path to the file's real nested location. This also fixes rows
    that were already stale before the migration (path in the working dir while the mp4
    had been archived to the final dir). Rows whose file is not found in either root are
    left untouched. Returns the number of rows changed (or that would change)."""
    root_list = list(roots)
    changed = 0
    try:
        conn = sqlite3.connect(db_path, timeout=10)
    except sqlite3.Error:
        return 0
    try:
        rows = conn.execute("SELECT id, path FROM recordings").fetchall()
        for rec_id, path in rows:
            if not path:
                continue
            p = Path(path)
            name = p.name
            stem = _stem_of_name(name) or p.stem
            streamer = layout.streamer_of(stem)
            if not streamer:
                continue
            real = _resolve_real_mp4(root_list, stem, streamer, name)
            if real is None or real == p:
                continue  # not found on disk, or already correct
            changed += 1
            print(f"  DB rec#{rec_id}: {p}  ->  {real}")
            if apply:
                conn.execute(
                    "UPDATE recordings SET path = ? WHERE id = ?",
                    (str(real), rec_id),
                )
        if apply:
            conn.commit()
    finally:
        conn.close()
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform the move (default: dry-run)")
    parser.add_argument("--record-dir", help="override the working record dir")
    parser.add_argument("--final-dir", help="override the final(archive) dir")
    args = parser.parse_args()

    db_path = get_db_path()
    record_dir = args.record_dir or record_dir_from_db(db_path)
    final_dir = args.final_dir if args.final_dir is not None else _final_dir_from_db(db_path)

    roots: list[Path] = []
    resolved = set()
    for raw in (record_dir, final_dir):
        if not raw:
            continue
        r = Path(raw).resolve()
        if r in resolved:
            continue
        resolved.add(r)
        roots.append(r)

    if not roots:
        print("録画rootが解決できませんでした。--record-dir で指定してください。")
        return 1

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] recordings layout migration")
    total_moves = 0
    total_errors = 0
    for root in roots:
        moves, skipped = _plan_root(root)
        print(f"\n== root: {root}  (move {len(moves)}, keep/skip {skipped}) ==")
        for src, dst, kind in moves:
            print(f"  [{kind}] {src.name}  ->  {dst.relative_to(root)}")
            total_moves += 1
            if args.apply:
                try:
                    _move(src, dst)
                except OSError as exc:
                    total_errors += 1
                    print(f"    ! failed: {exc}")

    print("\n== DB recordings.path ==")
    db_changed = _update_db_paths(db_path, roots, args.apply)

    print(
        f"\n{mode} done: {total_moves} file/dir move(s), {db_changed} DB path update(s)"
        + (f", {total_errors} error(s)" if total_errors else "")
    )
    if not args.apply:
        print("これはdry-runです。実行するには --apply を付けてください。")
    return 1 if total_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
