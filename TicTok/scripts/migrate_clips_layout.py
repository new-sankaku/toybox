"""切り出し成果物を root直下の ``_clips`` から、配信者folderの下へ移す。

    移動前  <root>/_clips/<配信者>/<file>
    移動後  <root>/<配信者>/_clips/<file>

置き場を配信者folderの中(録画の ``ts``/``mp4`` と同じ階層)へ揃える移行である。以後は
配信者ごとの片付け — folderごと消す・別driveへ移す・容量を見る — が、録画と成果物で別の
場所を指さない。新しく作る先は ``layout.clip_output_dir`` が既にこの規約で決めるので、
このscriptは**それ以前に出た分**を現状へ揃える1度きりの移行である。

両rootを対象にする。切り出しは常に一時保存先へ出るが、最終保存先へは「最終保存先へ移動」で
録画に随伴して移っており(``tictok.api.disk._clip_relocation_items``)、向こう側にも旧い
置き場の実体が在る。

移すもの: ``<root>/_clips/<配信者>/`` 配下の全file。成果物(mp4/png)も、作品のシーンcache
(``.scenes``)も、落ちた回の中間dirも含む — 置き場ごと動かさないと、cacheは次の焼き直しで
必ず外れ、中間dirは誰も見ない場所に残り続ける。

``<root>/_clips/`` 直下のfile(配信者dirに入っていないもの)は**動かさない**。そこは配信者を
読み取れないstemから出た成果物の受け皿として今も使う置き場である。

移動先に同名のfileが在る場合は触らない。上書きすると、どちらが本物か確かめる術が無いまま
片方が消える。

Usage (TicTok directory から venv で実行):
    python scripts/migrate_clips_layout.py
    python scripts/migrate_clips_layout.py --apply
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
logger = logging.getLogger("migrate_clips_layout")


def _fmt_bytes(size: int) -> str:
    return f"{size / 1024 ** 3:8.3f} GB"


def _plan(root: Path) -> tuple[list, list]:
    """(移すもの, 移せないもの) を (src, dst, bytes[, 理由]) で返す。"""
    moves: list = []
    blocked: list = []
    old_base = root / layout.CLIPS_DIRNAME
    if not old_base.is_dir():
        return moves, blocked
    for entry in sorted(old_base.iterdir()):
        if not entry.is_dir():
            # 配信者dirに入っていないfileは受け皿の中身。動かさない。
            continue
        streamer = entry.name
        new_base = layout.clips_dir(root, streamer)
        for dirpath, _dirnames, filenames in os.walk(entry):
            here = Path(dirpath)
            for name in sorted(filenames):
                src = here / name
                dst = new_base / src.relative_to(entry)
                try:
                    size = src.stat().st_size
                except OSError as exc:
                    blocked.append((src, dst, 0, str(exc)))
                    continue
                if dst.exists():
                    blocked.append((src, dst, size, "移動先に同名のfileがあります"))
                    continue
                moves.append((src, dst, size))
    return moves, blocked


def _prune_empty(base: Path) -> None:
    """空になったdirを畳む。残すと、次に走らせた人が「まだ在る」と読む。"""
    if not base.is_dir():
        return
    for dirpath, _dirnames, _filenames in sorted(os.walk(base), reverse=True):
        here = Path(dirpath)
        if here == base:
            continue
        try:
            if not any(here.iterdir()):
                here.rmdir()
        except OSError:
            pass
    try:
        if not any(base.iterdir()):
            base.rmdir()
    except OSError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="実際に移動する。既定はdry-run(何も動かさない)。")
    args = parser.parse_args()

    db_path = get_db_path()
    work = Path(record_dir_from_db(db_path)).resolve()
    final = Path(final_record_dir_from_db(db_path)).resolve()
    roots = [work] if work == final else [work, final]

    failures = 0
    moved = 0
    moved_bytes = 0
    for root in roots:
        logger.info("")
        logger.info("root %s", root)
        if not root.is_dir():
            logger.info("  ありません。")
            continue
        moves, blocked = _plan(root)
        total = sum(size for _src, _dst, size in moves)
        logger.info("  移す file %d本 / %s", len(moves), _fmt_bytes(total))
        for src, dst, size in moves:
            logger.info("    %s  %s -> %s", _fmt_bytes(size),
                        src.relative_to(root), dst.relative_to(root))
        if blocked:
            logger.info("  移せない file %d本", len(blocked))
            for src, _dst, size, reason in blocked:
                logger.info("    %s  %s  (%s)", _fmt_bytes(size),
                            src.relative_to(root), reason)
        if not args.apply:
            continue
        for src, dst, size in moves:
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
            except OSError:
                logger.exception("移動に失敗しました: %s", src)
                failures += 1
                continue
            moved += 1
            moved_bytes += size
        _prune_empty(root / layout.CLIPS_DIRNAME)

    logger.info("")
    if not args.apply:
        logger.info("dry-runです。実行するには --apply を付けてください。")
        return 0
    logger.info("%d本 / %s を配信者folderの下へ移しました%s",
                moved, _fmt_bytes(moved_bytes),
                f"（{failures}本は失敗）" if failures else "")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
