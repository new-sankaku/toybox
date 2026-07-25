"""Collect the derived files that older relocations left behind in the working dir.

A completed recording is moved from the working dir (SSD) to the final dir (HDD), but
until now only the .mp4 and its .timing.json travelled. Everything else derived from
the recording resolves from the mp4's *current* location, so the leftovers in the
working dir stopped being visible to anything:

    <stem>.overlay*.mp4   焼き込み済みの成果物。画面から消える(実測12.1GB)。
    <stem>.up.mp4         高画質化の成果物。同上。
    <stem>.timing.json    欠けると焼き込みが概算timingへ落ち、コメントがズレる。
    <stem>.overlay.meta   欠けるとcacheが当たらず全編を再encodeする。
    <stem>.thumbs.*       hover用sprite。作り直しにffmpegが1本走る。
    <stem>.waveform.json  波形。同上。

削除も容量表示もmp4の現在地を基準に列挙するため、録画を消しても旧rootの残骸は残り続ける。
このscriptは、DB上のpathがfinal dirを指す録画について、working dir側に残っている派生fileを
final dir側の正しい位置へ移す。移送処理本体(Recorder._move_recording_files)は既に派生file
一式を運ぶよう修正済みなので、これは過去ぶんの後始末で、一度流せば足りる。

移動先に既にfileがある場合は触らない(新しい方を壊さない)。

Usage (run from the TicTok directory, venv active):
    python scripts/repair_relocated_artifacts.py            # dry-run, report only
    python scripts/repair_relocated_artifacts.py --apply    # perform the move
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tictok.core import layout
from tictok.core.config import get_db_path, record_dir_from_db
from tictok.record.recorder import relocatable_artifact_paths


def _setting(db_path: str, key: str) -> str:
    conn = sqlite3.connect(db_path, timeout=5)
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return str(row[0]).strip() if row and row[0] else ""


def _completed_paths(db_path: str) -> list:
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, path, filename FROM recordings "
            "WHERE status = 'completed' AND path IS NOT NULL AND path <> ''"
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def _is_under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _fmt_bytes(n: int) -> str:
    return f"{n / 1_000_000_000:.2f} GB" if n >= 1_000_000_000 else f"{n / 1_000_000:.1f} MB"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="実際に移動する(既定はdry-run)")
    parser.add_argument("--db", default=get_db_path(), help="DBのpath")
    parser.add_argument(
        "--sidecars-only", action="store_true",
        help="成果物(.overlay.mp4/.up.mp4)は動かさず、小さいsidecarだけ移す。"
             "成果物を焼き直す予定なら、旧rootのものは移す価値が無いのでこちら",
    )
    args = parser.parse_args()

    db_path = args.db
    work_root = Path(record_dir_from_db(db_path)).resolve()
    final_setting = _setting(db_path, "record_dir_final")
    if not final_setting:
        print("record_dir_final が未設定です。移送そのものが起きないため、対象はありません。")
        return 0
    final_root = Path(final_setting).resolve()
    if final_root == work_root:
        print("work dir と final dir が同一です。移送が起きないため、対象はありません。")
        return 0
    layout.set_pool_root(work_root)

    print(f"work : {work_root}")
    print(f"final: {final_root}")
    print()

    moves: list = []
    skipped_outputs: list = []
    for row in _completed_paths(db_path):
        dst_src = Path(row["path"]).resolve()
        if not _is_under(dst_src, final_root):
            continue
        stem = Path(row["filename"] or dst_src.name).stem
        if not layout.streamer_of(stem):
            continue
        # 旧位置は「同じ録画が working dir に在ったとしたらどこか」で決まる。列挙は移送本体と
        # 同じ関数を使い、順序が1対1で対応する。
        work_src = layout.mp4_path(work_root, stem)
        for old, new in zip(relocatable_artifact_paths(work_src),
                            relocatable_artifact_paths(dst_src)):
            if old == new or not old.is_file():
                continue
            if new.exists():
                print(f"  skip (移動先に既にあります): {old.name}")
                continue
            if args.sidecars_only and old.suffix == ".mp4":
                skipped_outputs.append((old, old.stat().st_size))
                continue
            moves.append((old, new, old.stat().st_size))

    # 録画横断のpool(emotes/gift_icons)は、これまでmp4の現在地から解決していたため
    # final dir側にも二つ目のpoolが育っている。読み書きはwork rootへ一本化したので、
    # final dir側にしか無いfileだけをwork poolへ引き上げる(重複は触らない)。
    for pool_dir in (layout.emote_pool_dir(), layout.gift_icon_pool_dir()):
        stray_pool = final_root / pool_dir.name
        if not stray_pool.is_dir():
            continue
        for old in sorted(stray_pool.iterdir()):
            if not old.is_file():
                continue
            new = pool_dir / old.name
            if new.exists():
                continue
            moves.append((old, new, old.stat().st_size))

    if skipped_outputs:
        stale = sum(size for _, size in skipped_outputs)
        print(f"動かさない成果物: {len(skipped_outputs)} file / {_fmt_bytes(stale)}"
              f"  (焼き直す前提なら旧rootのこれらは不要です)")
        for old, size in sorted(skipped_outputs, key=lambda o: -o[1]):
            print(f"  {_fmt_bytes(size):>10}  {old}")
        print()

    if not moves:
        print("取り残された派生fileはありません。")
        return 0

    total = sum(size for _, _, size in moves)
    for old, new, size in sorted(moves, key=lambda m: -m[2]):
        print(f"  {_fmt_bytes(size):>10}  {old.name}")
        print(f"              {old.parent}  ->  {new.parent}")
    print()
    print(f"対象 {len(moves)} file / {_fmt_bytes(total)}")

    if not args.apply:
        print("dry-run です。実行するには --apply を付けてください。")
        return 0

    moved = 0
    freed = 0
    for old, new, size in moves:
        try:
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(new))
        except OSError as exc:
            print(f"  失敗: {old.name}: {exc}")
            continue
        moved += 1
        freed += size
    print(f"移動しました: {moved} file / {_fmt_bytes(freed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
