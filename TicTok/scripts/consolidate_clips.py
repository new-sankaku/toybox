"""最終保存先に在る切り出し成果物を、一時保存先の ``_clips`` へ集約する。

切り出し・reel・作品・スクショの出力先は「録画の実体が在る側のroot」で決まっていたため、
同じ操作の成果物が録画ごとに別のdriveへ出ていた。file systemだけが台帳(切り出しはDBに行を
持たない)である以上、これは「自分が作った物がどこに在るか人には分からない」という状態その
ものだった。出力先は一時保存先へ固定した(``layout.clip_output_dir``)ので、このscriptは
**それ以前に最終保存先へ出てしまった分**を一時保存先へ引き取り、現状を新しい規約へ揃える。

以後、最終保存先へ移るのは容量画面の「最終保存先へ移動」で録画に随伴したときだけである
(``tictok.api.disk._clip_relocation_items``)。つまりこのscriptは1度きりの移行であって、
定期的に走らせる物ではない。

対象は root直下の ``<root>/_clips/`` だけである。置き場はその後さらに配信者folderの下
(``<root>/<配信者>/_clips/``)へ移った(``scripts/migrate_clips_layout.py``)ので、最終保存先の
そちらに在る成果物は「最終保存先へ移動」で録画に随伴した正規の実体であり、引き取らない。

移すもの: 最終保存先の root直下 ``_clips`` 配下の全file。成果物(mp4/png)と、作品のシーンcache
(``.scenes``)の両方を含む。cacheは焼き直しを速くするためだけの物だが、焼き直しは常に
一時保存先で走るようになったので、置いて行くと二度と当たらない。

移動先に同名のfileが在る場合は**触らない**。上書きすると、どちらが本物か確かめる術が
無いまま片方が消える。

Usage (TicTok directory から venv で実行):
    python scripts/consolidate_clips.py
    python scripts/consolidate_clips.py --apply
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tictok.core import layout
from tictok.core.config import (
    final_record_dir_from_db,
    get_db_path,
    record_dir_from_db,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("consolidate_clips")


def _fmt_bytes(size: int) -> str:
    return f"{size / 1024 ** 3:8.3f} GB"


def _plan(src_base: Path, dst_base: Path) -> tuple[list, list]:
    """(移すもの, 移せないもの) を (相対path, bytes, 理由) で返す。"""
    moves: list = []
    blocked: list = []
    if not src_base.is_dir():
        return moves, blocked
    for dirpath, _dirnames, filenames in os.walk(src_base):
        here = Path(dirpath)
        for name in sorted(filenames):
            src = here / name
            rel = src.relative_to(src_base)
            try:
                size = src.stat().st_size
            except OSError as exc:
                blocked.append((rel, 0, str(exc)))
                continue
            if (dst_base / rel).exists():
                blocked.append((rel, size, "移動先に同名のfileがあります"))
                continue
            moves.append((rel, size))
    return moves, blocked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="実際に移動する。既定はdry-run(何も動かさない)。")
    args = parser.parse_args()

    db_path = get_db_path()
    work = Path(record_dir_from_db(db_path)).resolve()
    final = Path(final_record_dir_from_db(db_path)).resolve()
    if work == final:
        logger.info("一時保存先と最終保存先が同じです。集約するものはありません: %s", work)
        return 0

    src_base = layout.clips_dir(final)
    dst_base = layout.clips_dir(work)
    logger.info("移動元 %s", src_base)
    logger.info("移動先 %s", dst_base)

    moves, blocked = _plan(src_base, dst_base)
    total = sum(size for _rel, size in moves)
    logger.info("")
    logger.info("移す file %d本 / %s", len(moves), _fmt_bytes(total))
    for rel, size in moves:
        logger.info("  %s  %s", _fmt_bytes(size), rel)
    if blocked:
        logger.info("")
        logger.info("移せない file %d本", len(blocked))
        for rel, size, reason in blocked:
            logger.info("  %s  %s  (%s)", _fmt_bytes(size), rel, reason)

    if not args.apply:
        logger.info("")
        logger.info("dry-runです。実行するには --apply を付けてください。")
        return 0
    if not moves:
        return 0

    moved = 0
    moved_bytes = 0
    failures = 0
    for rel, size in moves:
        src = src_base / rel
        dst = dst_base / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        except OSError:
            logger.exception("移動に失敗しました: %s", rel)
            failures += 1
            continue
        moved += 1
        moved_bytes += size

    # 空になったdirを畳む。残しておくと、次にこのscriptを走らせた人が「まだ在る」と読む。
    for dirpath, _dirnames, _filenames in sorted(os.walk(src_base), reverse=True):
        here = Path(dirpath)
        if here == src_base:
            continue
        try:
            if not any(here.iterdir()):
                here.rmdir()
        except OSError:
            pass

    logger.info("")
    logger.info("%d本 / %s を一時保存先へ集約しました%s",
                moved, _fmt_bytes(moved_bytes),
                f"（{failures}本は失敗）" if failures else "")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
