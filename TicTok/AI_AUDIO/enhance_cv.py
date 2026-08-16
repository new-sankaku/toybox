"""話し声を残して音楽・効果音・noiseを落とすspeech enhancementを実測する検証用CLI。

音楽用の「歌声 vs 伴奏」分離(AI_AUDIO/separate.py)は、BGMが曲のときにその曲の
ボーカルを配信者の声と同じ側へ置く。曲の伴奏だけが消えて歌が残るのはmodelの設計
どおりの動作であり、パラメータでは直らない。必要なのは「話し声 vs それ以外」で
学習したmodelで、ここではClearerVoice-StudioのMossFormer2_SE_48Kを使う。

**別venv(AI_AUDIO/venv_cv)で動かす。** clearvoiceもtorchをCPU版で上書きするため、
分離用venvとも本体venvとも混ぜない。

入力は48kHz monoへ落としてから渡す。録画の左右chは実質同一(L-R差が本体より27.5dB下)
なので、mono処理して複製し直しても情報は落ちない。出力は必ず入力と同じsample rate・
同じsample数・同じchannel数へ戻す。
"""

import argparse
import logging
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

logger = logging.getLogger("enhance_cv")

DEFAULT_MODEL = "MossFormer2_SE_48K"
MODEL_RATE = 48000


def wav_info(path: Path) -> tuple:
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes(), wav.getframerate(), wav.getnchannels()


def to_mono48k(src: Path, dst: Path) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-c:a", "pcm_s16le",
                    "-ar", str(MODEL_RATE), "-ac", "1", "-y", str(dst)], check=True)


def write_aligned(samples: np.ndarray, dst: Path, rate: int, channels: int, frames: int) -> int:
    """modelが返したmono波形を、referenceのgrid(rate/ch/sample数)へ戻して書く。"""
    mono = np.asarray(samples, dtype=np.float64).reshape(-1)
    peak = float(np.abs(mono).max())
    if peak > 1.0:
        mono = mono / peak
    drift = len(mono) - frames
    if drift > 0:
        mono = mono[:frames]
    elif drift < 0:
        mono = np.concatenate([mono, np.zeros(-drift)])
    pcm = np.clip(np.round(mono * 32767.0), -32768, 32767).astype("<i2")
    data = np.repeat(pcm.reshape(-1, 1), channels, axis=1)
    with wave.open(str(dst), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(data.tobytes())
    return drift


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, nargs="+", help="入力wav (16bit PCM)")
    parser.add_argument("--out", type=Path, help="出力wav (入力1件のとき)")
    parser.add_argument("--out-suffix", default=None,
                        help="入力と同じdirへ <入力stem><suffix> で出す (複数件のとき)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"model名 (既定 {DEFAULT_MODEL})")
    parser.add_argument("--task", default="speech_enhancement", help="ClearVoiceのtask名")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

    if len(args.input) == 1 and args.out:
        targets = [(args.input[0], args.out)]
    elif args.out_suffix:
        targets = [(src, src.with_name(f"{src.stem}{args.out_suffix}{src.suffix}"))
                   for src in args.input]
    else:
        logger.error("入力1件は--out、複数件は--out-suffixを指定してください。")
        return 1
    missing = [src for src, _ in targets if not src.is_file()]
    if missing:
        logger.error("入力がありません: %s", missing[0])
        return 1

    import torch
    from clearvoice import ClearVoice

    if not torch.cuda.is_available():
        logger.error("CUDAが使えません。CPUでの実測は速度の参考にならないため中止します。")
        return 1
    torch.cuda.reset_peak_memory_stats()

    logger.info("model %s  task=%s  device=%s  対象%d件",
                args.model, args.task, torch.cuda.get_device_name(0), len(targets))
    load_started = time.perf_counter()
    engine = ClearVoice(task=args.task, model_names=[args.model])
    logger.info("model load %.1f秒", time.perf_counter() - load_started)

    total_seconds = 0.0
    total_elapsed = 0.0
    for order, (src, dst) in enumerate(targets, 1):
        frames, rate, channels = wav_info(src)
        duration = frames / float(rate)
        dst.parent.mkdir(parents=True, exist_ok=True)
        mono_path = dst.parent / f"{src.stem}.mono48k.wav"
        to_mono48k(src, mono_path)

        started = time.perf_counter()
        result = engine(input_path=str(mono_path), online_write=False)
        elapsed = time.perf_counter() - started
        if isinstance(result, dict):
            result = next(iter(result.values()))
        drift = write_aligned(result, dst, rate, channels, frames)
        mono_path.unlink()
        total_seconds += duration
        total_elapsed += elapsed
        logger.info("[%d/%d] %s  %.1f秒 -> %.1f秒で処理 (drift %+d sample)",
                    order, len(targets), dst.name, duration, elapsed, drift)

    peak_gb = torch.cuda.max_memory_allocated() / (1024 ** 3)
    logger.info("")
    logger.info("合計 %.1f秒の音声を %.1f秒で処理 (%.1f倍速)  VRAM peak %.2fGB",
                total_seconds, total_elapsed, total_seconds / total_elapsed, peak_gb)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
