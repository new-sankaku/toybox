"""録画行の path を、mp4 の実体が在る root へ合わせる。

## 直そうとしている壊れ方

録画1本の在処は ``recordings.path`` の1列だけが持っている。完了した録画は working dir から
final dir へ移送されるが、移送の途中で止まった・あとから手で戻した等の理由で、**DBが名乗る
root と mp4 の実体の root がずれた行**が残る。

ずれた行は「動かないわけではない」ので気付きにくい。実体を探す経路
(``files._resolved_recording_path``)は両rootを見るため再生も切り出しも通り、DBのpathを
そのまま信じる経路だけが静かに外れる。実際に、sidecar(音声波形・サムネ・声profile・gain)の
**済み判定**がDBのpath側の ``.sidecars`` を見ていたため、jobは実体側のcacheに命中して
毎回completedになるのに判定は「未生成」のままで、30分ごとのsweepが同じ4種別を積み直して
いた(台帳2,279行のうち627行=27.5%がその1本)。判定側は ``fsfacts._recording_src`` で
実体側へ揃えたが、**ずれ自体はDBに残っている**。それを消すのがこのscript。

## このscriptがすること

``recordings.path`` が実在せず、同じ stem の mp4 が**別のrecord rootに実在する**行について、
path をその実体へ書き換える。fileは1byteも動かさない ―― 直すのは「どこに在るか」という
DBの申告だけである。

移送そのもの(work → final)をやり直したい場合は、このscriptではなく画面の移送を使うこと。
4GB級のfileをこのscriptが勝手に動かすことはしない。

派生file(焼き込み・Up出力・sidecar)は mp4 の現在地から解決される。pathを実体へ合わせると
解決先も実体側へ揃うので、実体側に既に在る派生fileがそのまま見えるようになる。実体側に無い
派生fileは未生成として扱われる ―― それが事実なので、旧root側に残っている物を拾いに行く
ことはしない(その後始末は ``repair_relocated_artifacts.py`` の仕事)。

Usage (run from the TicTok directory, venv active):
    venv\\Scripts\\python scripts/repair_recording_paths.py           # dry-run, report only
    venv\\Scripts\\python scripts/repair_recording_paths.py --apply   # DBを書き換える
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tictok.core import layout
from tictok.core.config import get_db_path, record_dir_from_db


def _setting(db_path: str, key: str) -> str:
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return str(row[0]).strip() if row and row[0] else ""


def _rows(db_path: str) -> list:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, path, filename, status FROM recordings "
            "WHERE path IS NOT NULL AND path <> ''"
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def _drifted(rows: list, roots: list) -> list:
    """DBのpathが実在せず、同じstemのmp4が別rootに実在する行 → (row, 実体のpath)。

    実体が見つからない行は対象にしない。mp4を消した録画・素材(.ts)だけが残る録画は
    「pathがずれている」のではなく「mp4が無い」のであって、直す対象が別である。"""
    out = []
    for row in rows:
        current = Path(row["path"])
        if current.is_file():
            continue
        stem = Path(row["filename"] or "").stem
        if not stem:
            continue
        found = next((p for p in (layout.mp4_path(root, stem) for root in roots)
                      if p.is_file()), None)
        if found is None or found == current:
            continue
        out.append((row, found))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="実際にDBを書き換える(既定はdry-run)")
    parser.add_argument("--db", default=get_db_path(), help="DBのpath")
    args = parser.parse_args()

    db_path = args.db
    work_root = Path(record_dir_from_db(db_path)).resolve()
    roots = [work_root]
    final_setting = _setting(db_path, "record_dir_final")
    if final_setting:
        final_root = Path(final_setting).resolve()
        if final_root != work_root:
            roots.append(final_root)
    layout.set_pool_root(work_root)
    layout.set_record_roots(roots)

    for root in roots:
        print(f"root : {root}")
    print()

    targets = _drifted(_rows(db_path), roots)
    if not targets:
        print("pathがずれている録画はありません。")
        return 0

    for row, found in targets:
        print(f"rid={row['id']} ({row['status']}) {row['filename']}")
        print(f"  DBの申告: {row['path']}  ← 実在しません")
        print(f"  実体    : {found}  ({found.stat().st_size / 1_000_000_000:.2f} GB)")

    print()
    if not args.apply:
        print(f"{len(targets)}件が対象です。--apply を付けると書き換えます。")
        return 0

    conn = sqlite3.connect(db_path, timeout=10)
    try:
        with conn:
            for row, found in targets:
                conn.execute("UPDATE recordings SET path = ? WHERE id = ?",
                             (str(found), row["id"]))
    finally:
        conn.close()
    print(f"{len(targets)}件のpathを実体へ合わせました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
