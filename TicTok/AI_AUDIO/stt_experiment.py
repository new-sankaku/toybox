"""BGM除去が文字起こしに効くのかを、対照群つきで測る。

90秒1窓の比較では何も言えない。差が出ても、それがBGM除去のせいなのか、whisperの
揺らぎなのか、加工の副作用(mono複製・peak正規化)なのか分けられないためである。
ここでは3つを分ける。

  A 原音        録画から切り出したまま(stereo)
  B 対照        原音をBGM除去と**同じ経路**でmono48kへ落とし、同じpeak正規化をして
                stereoへ複製し直したもの。**modelだけ通していない**。
                AとBの差 = ch数と音量の変化による差
  C BGM除去     Bと同じ経路でmodelを通したもの。
                BとCの差 = **BGM除去そのものの効果**

さらにAをもう一度だけ流して(A')、whisper自体がどれだけ揺れるかを測る。A-A'の差より
B-Cの差が小さければ、その差はBGM除去の効果とは呼べない。

窓は複数の配信者・複数の録画から取る。1本の録画の中だけで測ると、その配信のBGMの
掛かり方に固有の結果しか出ない。窓ごとにBGMの量(nonspeech RMS)も記録し、
「BGMが鳴っている窓だけ」で切り直せるようにする。

途中結果はJSONLへ1件ずつ書く。server起動が同じvenvのpythonを巻き添えで殺すため、
最後にまとめて書くと数十分の計測が消える。
"""

import argparse
import json
import logging
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("stt_experiment")

WINDOW_SECONDS = 60
OFFSET_FRACTIONS = (0.2, 0.4, 0.6, 0.8)
# whisperが読めない字を吐いた印。加工の副作用かどうかを数えるために別枠で持つ。
REPLACEMENT_CHAR = "�"


def playlist_duration(index: Path) -> float:
    total = 0.0
    for line in index.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("#EXTINF:"):
            total += float(line[len("#EXTINF:"):].strip().rstrip(","))
    return total


def extract(index: Path, start: float, seconds: int, dst: Path) -> bool:
    args = ["ffmpeg", "-v", "error", "-allowed_extensions", "ALL", "-f", "hls",
            "-ss", f"{start:.3f}", "-i", str(index), "-t", str(seconds),
            "-vn", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", "-y", str(dst)]
    done = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if done.returncode != 0 or not dst.is_file() or dst.stat().st_size < 1024:
        logger.warning("切り出せません: %s @%.0f秒 (%s)", index.parent.name, start,
                       done.stderr.decode("utf-8", "replace").strip()[:120])
        return False
    return True


def read_wav(path: Path):
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        rate = wav.getframerate()
        raw = wav.readframes(wav.getnframes())
    data = np.frombuffer(raw, dtype="<i2").reshape(-1, channels)
    return data, rate, channels


def write_control(src: Path, dst: Path) -> None:
    """BGM除去と同じ経路を通すが、modelだけ通さない対照群を作る。"""
    data, rate, channels = read_wav(src)
    mono = data.astype(np.float64).mean(axis=1) / 32768.0
    peak = float(np.abs(mono).max())
    if peak > 1.0:
        mono = mono / peak
    pcm = np.clip(np.round(mono * 32767.0), -32768, 32767).astype("<i2")
    out = np.repeat(pcm.reshape(-1, 1), channels, axis=1)
    with wave.open(str(dst), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(out.tobytes())


def nonspeech_db(path: Path) -> float:
    """窓のBGM量の代理指標。scripts/audio_ab.pyと同じ決め方(静かな側35%のRMS)。"""
    data, rate, _ = read_wav(path)
    mono = data.astype(np.float64).mean(axis=1) / 32768.0
    size = int(rate * 0.02)
    count = len(mono) // size
    if count == 0:
        return float("nan")
    rms = np.sqrt((mono[:count * size].reshape(count, size) ** 2).mean(axis=1))
    quiet = rms[rms <= np.percentile(rms, 35.0)]
    return 20.0 * np.log10(max(float(quiet.mean()), 1e-12))


def transcribe(model, path: Path, cfg: dict) -> dict:
    segments, _ = model.transcribe(
        str(path), language=cfg["language"], beam_size=cfg["beam_size"],
        condition_on_previous_text=cfg["condition"],
        no_repeat_ngram_size=cfg["no_repeat"], word_timestamps=False,
    )
    rows = [{"text": seg.text.strip(), "avg_logprob": seg.avg_logprob,
             "start": seg.start, "end": seg.end} for seg in segments]
    text = "".join(row["text"] for row in rows)
    texts = [row["text"] for row in rows]
    return {
        "segments": len(rows),
        "chars": len(text),
        "avg_logprob": sum(r["avg_logprob"] for r in rows) / len(rows) if rows else 0.0,
        "replacement_chars": text.count(REPLACEMENT_CHAR),
        "duplicate_segments": len(texts) - len(set(texts)),
        "text": text,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work", type=Path, required=True, help="作業dir")
    parser.add_argument("--out", type=Path, required=True, help="結果JSONL")
    parser.add_argument("--recordings", type=Path, nargs="+", required=True,
                        help="録画のts dir (index.m3u8を含む)")
    parser.add_argument("--stage", choices=("extract", "transcribe"), required=True,
                        help="extract=窓の切り出しと対照群作成 / transcribe=文字起こし比較")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    args.work.mkdir(parents=True, exist_ok=True)

    if args.stage == "extract":
        made = 0
        for rec in args.recordings:
            index = rec / "index.m3u8"
            if not index.is_file():
                logger.warning("index.m3u8がありません: %s", rec)
                continue
            duration = playlist_duration(index)
            if duration < WINDOW_SECONDS * 3:
                logger.warning("短すぎます(%.0f秒): %s", duration, rec.name)
                continue
            for order, fraction in enumerate(OFFSET_FRACTIONS):
                start = duration * fraction
                dst = args.work / f"{rec.name}__{order}.a.wav"
                if not extract(index, start, WINDOW_SECONDS, dst):
                    continue
                write_control(dst, args.work / f"{rec.name}__{order}.b.wav")
                made += 1
                logger.info("窓 %s @%.0f秒 (%.0f秒中)  nonspeech %.1fdB",
                            dst.stem, start, duration, nonspeech_db(dst))
        logger.info("")
        logger.info("%d窓を作りました。次: venv_cvで .a.wav を強調して .c.wav として置く", made)
        return 0

    from faster_whisper import WhisperModel

    from tictok.core import config

    device = config.get_stt_device()
    compute = config.get_stt_compute_type()
    cfg = {
        "language": config.get_stt_language(),
        "beam_size": config.get_stt_beam_size(),
        "condition": config.get_stt_condition_on_previous_text(),
        "no_repeat": config.get_stt_no_repeat_ngram_size(),
    }
    model = WhisperModel(config.get_stt_model(),
                         device="cuda" if device == "auto" else device,
                         compute_type="float16" if compute == "auto" else compute)
    logger.info("model=%s %s", config.get_stt_model(), cfg)

    windows = sorted(args.work.glob("*.a.wav"))
    with args.out.open("w", encoding="utf-8") as sink:
        for index, src in enumerate(windows, 1):
            key = src.name[:-len(".a.wav")]
            variants = {"A": src, "B": args.work / f"{key}.b.wav",
                        "C": args.work / f"{key}.c.wav"}
            if not all(path.is_file() for path in variants.values()):
                logger.warning("[%d/%d] %s: 3種そろっていません", index, len(windows), key)
                continue
            row = {"key": key, "nonspeech_db": nonspeech_db(src)}
            for label, path in variants.items():
                row[label] = transcribe(model, path, cfg)
            # 同じfileをもう一度。whisper自体の揺らぎの大きさを測る。
            row["A2"] = transcribe(model, src, cfg)
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
            sink.flush()
            logger.info("[%d/%d] %s  nonspeech %.1fdB  lp A=%.3f B=%.3f C=%.3f  "
                        "文字化け A=%d B=%d C=%d",
                        index, len(windows), key, row["nonspeech_db"],
                        row["A"]["avg_logprob"], row["B"]["avg_logprob"],
                        row["C"]["avg_logprob"], row["A"]["replacement_chars"],
                        row["B"]["replacement_chars"], row["C"]["replacement_chars"])
    logger.info("")
    logger.info("結果: %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
