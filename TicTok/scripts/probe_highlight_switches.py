"""照合済みhighlightの**映像の切り替わり(頭と尻)を測り直す**。照合はやり直さない。

なぜ要るのか
------------
切り出す窓の既定は「gift演出の窓」ではなく「映像が綺麗な区間」である
(:func:`tictok.store.highlights.default_cut`)。gift演出の境目は**音**で決めていて、TikTokの
montageは音を一瞬で切り替えながら映像には切り替わりの演出を掛け、その演出は境目を跨ぐ。

尻(``video_end``)を測るようになったのは頭(``video_start``)より後である。既に照合済みの
highlightは頭しか持っておらず、そのままでは**窓の終わりに次のgiftが映る**。実測(あきと🐢💤
の Strong Finish の窓)で音の境目の0.93秒手前から次の場面が現れており、通しで観ると
「2人目のgiftの終わりに3人目のgiftが少し映る」形になっていた。

照合(``highlight_match``)を走らせ直せば同じ値は入るが、あちらは録画を1週間ぶん読み直す
重い段で、**切り替わりの測り方が変わっただけで走らせる理由が無い**。このscriptは素材の
mp4だけを読み、gift演出の境目にも人の入力にも触らない。

既定はdry-run。``--apply`` のときだけ台帳へ書く。読むだけなのでserver稼働中でも走るが、
``--apply`` は書き込みなので停めてから実行する。

Usage (TicTok directory から venv で実行):
    python scripts/probe_highlight_switches.py
    python scripts/probe_highlight_switches.py --streamer pomiiiip
    python scripts/probe_highlight_switches.py --apply
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tictok.core.config import get_db_path
from tictok.media import highlight_switch
from tictok.storage import Storage

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("probe_highlight_switches")


def _describe(index: int, segment: dict, span: tuple) -> str:
    """gift演出1つぶんの結末。**何秒詰まるのかを出す** —— 値そのものより、切り出しがどれだけ
    変わるのかが、走らせた人が見たい数字である。"""
    start, end = float(segment["start"]), float(segment["end"])
    began, ended = span
    head = "測れず" if began is None else f"{began:.3f}"
    tail = "測れず" if ended is None else f"{ended:.3f}"
    trim = "" if ended is None else f"　尻を {end - ended:+.3f}秒"
    return (f"  gift演出{index:>3}  {start:8.3f}〜{end:8.3f}　"
            f"映像 {head}〜{tail}{trim}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--streamer", default="",
                        help="この配信者のhighlightだけを測る(既定: 全部)")
    parser.add_argument("--highlight-id", type=int, default=0,
                        help="このhighlight 1本だけを測る")
    parser.add_argument("--apply", action="store_true",
                        help="台帳へ書く(既定は測って出すだけ)")
    args = parser.parse_args()

    storage = Storage(get_db_path())
    try:
        rows = storage.list_highlights(unique_id=args.streamer, status="matched")
        if args.highlight_id:
            rows = [row for row in rows if row["id"] == args.highlight_id]
        if not rows:
            logger.info("対象のhighlightがありません。")
            return 1
        written = 0
        for row in rows:
            path = Path(row["path"])
            segments = storage.highlight_segments(row["id"])
            logger.info("== #%s %s（gift演出 %d件）", row["id"], row["filename"],
                        len(segments))
            if not path.is_file():
                logger.info("  fileがありません: %s", path)
                continue
            if len(segments) < 2:
                # 境目が無い。fileの両端は演出ではないので、測る物が無い。
                logger.info("  境目がありません（gift演出が1つ以下）。")
                continue
            spans = highlight_switch.video_spans(
                path, [(seg["start"], seg["end"]) for seg in segments])
            for index, (segment, span) in enumerate(zip(segments, spans)):
                logger.info("%s", _describe(index, segment, span))
            if args.apply:
                written += storage.update_highlight_switches(row["id"], spans)
        logger.info("%s: highlight %d本 / gift演出 %d件",
                    "書きました" if args.apply else "測っただけです（--apply で書きます）",
                    len(rows), written)
    finally:
        storage.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
