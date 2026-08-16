"""同じ音声の加工前後を同じ設定で文字起こしし、結果を並べて比べる検証用CLI。

「BGMを消すと文字起こしが良くなる」を体感でなく確かめるためのもの。正解text
(ground truth)は無いので、良し悪しを1つの数値では出さない。出すのは判断材料である。

  segments        認識された区間の数
  chars           text全体の文字数
  avg_logprob     whisperが自分の出力に付けた対数確率の平均。低いほど自信が無い
  no_speech_prob  「ここは音声ではない」と判断した確率の平均。BGMだけの区間で上がる
  compression_ratio  textをzlibで縮めたときの比。**高いほど同じ語の繰り返し**で、
                  whisperがBGMや歌に引きずられて幻聴を書いた区間で跳ね上がる

最後に両方のtextを全文出す。**採否はこれを読んで決める。** 指標だけで決めない。

設定はtictok.core.configから読み、本番の文字起こしと同じ条件にする。ここだけ別の
model・別のbeam sizeで測ると、比較にならないうえ本番の挙動も予測できない。
"""

import argparse
import logging
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("stt_ab")


def transcribe(model, path: Path, language: str, beam_size: int,
               condition: bool, no_repeat: int) -> dict:
    segments, info = model.transcribe(
        str(path), language=language, beam_size=beam_size,
        condition_on_previous_text=condition,
        no_repeat_ngram_size=no_repeat, word_timestamps=False,
    )
    rows = []
    for seg in segments:
        rows.append({"start": seg.start, "end": seg.end, "text": seg.text.strip(),
                     "avg_logprob": seg.avg_logprob,
                     "no_speech_prob": seg.no_speech_prob,
                     "compression_ratio": seg.compression_ratio})
    text = "".join(row["text"] for row in rows)
    encoded = text.encode("utf-8")
    ratio = len(encoded) / max(len(zlib.compress(encoded)), 1)
    return {
        "rows": rows,
        "text": text,
        "segments": len(rows),
        "chars": len(text),
        "avg_logprob": sum(r["avg_logprob"] for r in rows) / len(rows) if rows else 0.0,
        "no_speech_prob": sum(r["no_speech_prob"] for r in rows) / len(rows) if rows else 0.0,
        "compression_ratio": ratio,
        "duration": info.duration,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("before", type=Path, help="加工前の音声")
    parser.add_argument("after", type=Path, help="加工後の音声")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

    from faster_whisper import WhisperModel

    from tictok.core import config

    name = config.get_stt_model()
    device = config.get_stt_device()
    compute = config.get_stt_compute_type()
    if device == "auto":
        device = "cuda"
    if compute == "auto":
        compute = "float16" if device == "cuda" else "int8"
    language = config.get_stt_language()
    beam_size = config.get_stt_beam_size()
    condition = config.get_stt_condition_on_previous_text()
    no_repeat = config.get_stt_no_repeat_ngram_size()

    logger.info("model=%s device=%s compute=%s lang=%s beam=%d",
                name, device, compute, language, beam_size)
    model = WhisperModel(name, device=device, compute_type=compute)

    results = {}
    for label, path in (("加工前", args.before), ("加工後", args.after)):
        if not path.is_file():
            logger.error("%sがありません: %s", label, path)
            return 1
        results[label] = transcribe(model, path, language, beam_size, condition, no_repeat)

    logger.info("")
    header = f"{'':<8}{'segments':>10}{'chars':>8}{'avg_logprob':>13}{'no_speech':>11}{'圧縮比':>9}"
    logger.info(header)
    logger.info("-" * len(header))
    for label, res in results.items():
        logger.info("%-8s%10d%8d%13.3f%11.3f%9.2f", label, res["segments"], res["chars"],
                    res["avg_logprob"], res["no_speech_prob"], res["compression_ratio"])

    for label, res in results.items():
        logger.info("")
        logger.info("=== %s (%s) ===", label, (args.before if label == "加工前" else args.after).name)
        for row in res["rows"]:
            logger.info("[%6.1f-%6.1f] lp=%.2f ns=%.2f  %s",
                        row["start"], row["end"], row["avg_logprob"],
                        row["no_speech_prob"], row["text"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
