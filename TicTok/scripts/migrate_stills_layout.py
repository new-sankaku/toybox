"""既に出ているスクショ(png)を ``_clips`` から ``_screenshots`` へ移す。

    移動前  <root>/<配信者>/_clips/<元録画>_shot<位置>[_ラベル][.版].png
    移動後  <root>/<配信者>/_screenshots/<元録画>_shot<位置>[_ラベル][.版].png

静止画の置き場を切り出しmp4から分ける移行である。新しく撮る先は
``layout.still_output_dir`` が既にこの規約で決めるので、このscriptは**それ以前に撮った分**を
現状へ揃える1度きりの移行である。

両rootを対象にする。スクショは常に一時保存先へ出るが、最終保存先へは「最終保存先へ移動」で
録画に随伴して移っており(``tictok.api.disk._clip_relocation_items``)、向こう側にも旧い
置き場の実体が在る。配信者folderの下へ移す前の実体(``<root>/_clips/<配信者>/``)も同じ
理屈で ``<root>/_screenshots/<配信者>/`` へ移す — 旧い置き場の中でも動画と静止画は分かれる。

移すもの: 置き場の直下に在る **スクショと読めるpngだけ**である
(:func:`tictok.media.clipper.parse_clip_name` が ``still`` と読む名前)。判定を拡張子だけに
すると、規約外の名前のpngや、他所からそこへ置かれたpngまで巻き込む — 名前で素性を名乗れない
fileは、動かした先で持ち主を辿る手段が無くなる。

作品のシーンcache(``.scenes``)と落ちた回の中間dir(``.clip_``等)には入らない。中にpngが在っても
それは成果物ではなく、置き場を跨いで動かせば cache は次の焼き直しで必ず外れる。

移動先に同名のfileが在る場合は触らない。上書きすると、どちらが本物か確かめる術が無いまま
片方が消える。

Usage (TicTok directory から venv で実行):
    python scripts/migrate_stills_layout.py
    python scripts/migrate_stills_layout.py --apply
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
from tictok.media.clipper import STILL_EXT, parse_clip_name

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("migrate_stills_layout")


def _fmt_bytes(size: int) -> str:
    return f"{size / 1024 ** 3:8.3f} GB"


def _is_still(name: str) -> bool:
    """file名がスクショを名乗っているか。拡張子だけでは決めない。"""
    if not name.lower().endswith(STILL_EXT):
        return False
    parsed = parse_clip_name(name)
    return bool(parsed) and parsed.get("kind") == "still"


def _destination(root: Path, path: Path) -> Path | None:
    """``_clips`` に在るスクショの移動先。置き場の形が読めなければ None(動かさない)。

    現行の置き場(``<root>/<配信者>/_clips/``)と、配信者folderの下へ移す前の実体
    (``<root>/_clips/<配信者>/``)の両方を、それぞれ同じ形のまま静止画側へ写す。"""
    parts = path.relative_to(root).parts
    if len(parts) == 3 and parts[1] == layout.CLIPS_DIRNAME:
        return layout.stills_dir(root, parts[0]) / parts[2]
    if len(parts) == 3 and parts[0] == layout.CLIPS_DIRNAME:
        return root / layout.STILLS_DIRNAME / parts[1] / parts[2]
    # root直下の受け皿(``<root>/_clips/<file>``)は動かさない。そこに落ちるのは配信者を
    # 読み取れないstemから出た物だけで、そのstemはスクショの名前としても読めない
    # (``_STILL_NAME_RE`` も stem の規約に乗っている)ため、``_is_still`` を通る物は在り得ない。
    return None


def _plan(root: Path) -> tuple[list, list]:
    """(移すもの, 移せないもの) を (src, dst, bytes[, 理由]) で返す。"""
    moves: list = []
    blocked: list = []
    for base in layout.iter_clip_dirs(root):
        if base.name != layout.CLIPS_DIRNAME:
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            # 中間dirとcacheには入らない(dot始まりのdirはどちらもそれである)。
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            here = Path(dirpath)
            for name in sorted(filenames):
                if not _is_still(name):
                    continue
                src = here / name
                dst = _destination(root, src)
                if dst is None:
                    continue
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

    logger.info("")
    if not args.apply:
        logger.info("dry-runです。実行するには --apply を付けてください。")
        return 0
    logger.info("%d本 / %s をスクショの置き場へ移しました%s",
                moved, _fmt_bytes(moved_bytes),
                f"（{failures}本は失敗）" if failures else "")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
