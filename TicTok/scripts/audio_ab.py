"""音声加工の前後を同じ物差しで比べる。採否は必ず試聴で決めるが、その前に
「何がどれだけ変わったか」を数値で押さえるためのscript。

前提: 源はHE-AAC 約67kbps / 48kHz stereo で、配信者・コラボ相手・BGM・gift SEが
mix済みの1 trackである。11kHz以上はSBRが合成した帯域なので、その上の変化は
「元の情報が復元された」ことを意味しない。

物差しは5つ。いずれもreference(加工前)と比較対象(加工後)で**同じ時間区間**を見る。
区間の切り分けはreference側のframe energyだけで決め、加工後の音で決め直さない。
加工後で決め直すと、BGMを消したことで「静かなframe」の集合そのものが動いてしまい、
BGMが減ったのか区間がずれたのかを区別できなくなる。

  1. nonspeech_rms  静かな側のframeのRMS。**BGMの残量の代理指標**。BGM分離の効果は
                    ここに出る。noise floorが-19〜-23dBFSの録画は静かなのではなく
                    BGMが鳴り続けている状態なので、この値が下がることが分離の成否。
  2. speech_rms     喋っている側のframeのRMS。1だけが下がり2が保たれるのが理想で、
                    2まで一緒に下がるものは「音量を絞っただけ」である。
  3. click_per_min  高域(4〜11kHz)に立つ孤立transientの毎分回数。lip音・口内click・
                    分離modelのartifactがここに出る。**増えていないかの見張りも兼ねる**
                    (spectrum減算型のnoise除去はmusical noiseでこの値を増やす)。
  4. fullscale_pct  full scaleに貼り付いたsampleの割合。源が既に0dBFS到達38%の窓を
                    持つため、加工でここが増えるものは歪みを足している。
  5. corr           referenceとの相関。「変わった」ことの確認用で、良し悪しではない。
                    1.0000のままなら、その加工は何もしていない。

比較対象はreferenceとsample数が完全に一致していること。分離modelはchunk paddingで
末尾が伸びるため、長さが違う出力をそのまま採ると[[comment overlay drift]]と同型の
ズレを全出力経路へ配る。ここで弾く。
"""

import argparse
import logging
import sys
import wave
from pathlib import Path

import numpy as np

logger = logging.getLogger("audio_ab")

FRAME_MS = 20.0
CLICK_FRAME_MS = 5.0
# 静かな側とみなすframeの割合。BGMはここに露出する。
QUIET_PERCENTILE = 35.0
# clickとみなす高域の突出量(dB)と、孤立とみなす最大の幅(frame数)。
CLICK_RISE_DB = 9.0
CLICK_MAX_WIDTH = 3
CLICK_BAND_HZ = (4000.0, 11000.0)
# SBRの合成帯域に入らない上限。CLICK_BAND_HZの上端はこれに合わせてある。
EPS = 1e-12


def read_wav(path: Path) -> tuple:
    """(mono float32 [-1,1], sample_rate, channels, 全channelの生sample) を返す。"""
    with wave.open(str(path), "rb") as wav:
        if wav.getsampwidth() != 2:
            raise ValueError(f"{path.name}: 16bit PCMのみ対応しています "
                             f"(sampwidth={wav.getsampwidth()})")
        channels = wav.getnchannels()
        rate = wav.getframerate()
        raw = wav.readframes(wav.getnframes())
    data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels)
        mono = data.mean(axis=1)
    else:
        data = data.reshape(-1, 1)
        mono = data[:, 0]
    return mono, rate, channels, data


def db(value: float) -> float:
    return 20.0 * float(np.log10(max(float(value), EPS)))


def frame_rms(mono: np.ndarray, rate: int, frame_ms: float) -> np.ndarray:
    size = max(1, int(rate * frame_ms / 1000.0))
    count = len(mono) // size
    if count == 0:
        return np.zeros(0, dtype=np.float32)
    frames = mono[:count * size].reshape(count, size)
    return np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1))


def band_energy(mono: np.ndarray, rate: int, frame_ms: float,
                low_hz: float, high_hz: float) -> np.ndarray:
    size = max(1, int(rate * frame_ms / 1000.0))
    count = len(mono) // size
    if count == 0:
        return np.zeros(0, dtype=np.float64)
    frames = mono[:count * size].reshape(count, size).astype(np.float64)
    frames = frames * np.hanning(size)[None, :]
    spectrum = np.abs(np.fft.rfft(frames, axis=1))
    freqs = np.fft.rfftfreq(size, d=1.0 / rate)
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    return (spectrum[:, mask] ** 2).sum(axis=1)


def count_clicks(mono: np.ndarray, rate: int) -> int:
    """高域帯の孤立した突出をclickとして数える。

    周囲のmedianからの突出で見るので、高域が常に鳴っている区間(BGMのhi-hat等)は
    拾わない。幅がCLICK_MAX_WIDTHを超えるものは持続音として除く。
    """
    energy = band_energy(mono, rate, CLICK_FRAME_MS, *CLICK_BAND_HZ)
    if len(energy) < 21:
        return 0
    level = 10.0 * np.log10(energy + EPS)
    # 前後10 frame(=±50ms)のmedianを地の高さとする。
    pad = np.pad(level, 10, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(pad, 21)
    floor = np.median(windows, axis=1)
    hot = level - floor >= CLICK_RISE_DB
    clicks = 0
    run = 0
    for flag in hot:
        if flag:
            run += 1
            continue
        if 0 < run <= CLICK_MAX_WIDTH:
            clicks += 1
        run = 0
    if 0 < run <= CLICK_MAX_WIDTH:
        clicks += 1
    return clicks


def measure(path: Path, quiet_mask=None) -> dict:
    mono, rate, channels, allch = read_wav(path)
    duration = len(mono) / float(rate)
    rms = frame_rms(mono, rate, FRAME_MS)
    if quiet_mask is None:
        threshold = np.percentile(rms, QUIET_PERCENTILE)
        quiet_mask = rms <= threshold
    usable = min(len(rms), len(quiet_mask))
    mask = quiet_mask[:usable]
    quiet = rms[:usable][mask]
    loud = rms[:usable][~mask]
    peak = float(np.abs(allch).max()) if allch.size else 0.0
    stuck = float((np.abs(allch) >= 0.999).mean() * 100.0) if allch.size else 0.0
    minutes = duration / 60.0
    return {
        "path": path,
        "samples": len(mono),
        "rate": rate,
        "channels": channels,
        "duration": duration,
        "mono": mono,
        "quiet_mask": quiet_mask,
        "nonspeech_rms_db": db(quiet.mean()) if quiet.size else float("nan"),
        "speech_rms_db": db(loud.mean()) if loud.size else float("nan"),
        "peak_db": db(peak),
        "fullscale_pct": stuck,
        "click_per_min": count_clicks(mono, rate) / minutes if minutes > 0 else 0.0,
    }


def correlation(a: np.ndarray, b: np.ndarray) -> float:
    length = min(len(a), len(b))
    if length == 0:
        return float("nan")
    x = a[:length].astype(np.float64)
    y = b[:length].astype(np.float64)
    x -= x.mean()
    y -= y.mean()
    denom = np.sqrt((x ** 2).sum() * (y ** 2).sum())
    if denom < EPS:
        return float("nan")
    return float((x * y).sum() / denom)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reference", type=Path, help="加工前のwav (16bit PCM)")
    parser.add_argument("compare", type=Path, nargs="+", help="加工後のwav (16bit PCM)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

    if not args.reference.is_file():
        logger.error("referenceがありません: %s", args.reference)
        return 1
    ref = measure(args.reference)
    logger.info("reference: %s  %.1f秒 %dch %dHz",
                args.reference.name, ref["duration"], ref["channels"], ref["rate"])
    logger.info("")
    header = (f"{'file':<34}{'nonspeech':>11}{'speech':>10}{'click/min':>11}"
              f"{'peak':>9}{'貼付%':>9}{'corr':>9}{'長さ差':>9}")
    logger.info(header)
    logger.info("-" * len(header))
    logger.info("%-34s%10.2fdB%9.2fdB%11.1f%8.2fdB%9.2f%9s%9s",
                "(reference)", ref["nonspeech_rms_db"], ref["speech_rms_db"],
                ref["click_per_min"], ref["peak_db"], ref["fullscale_pct"], "-", "-")

    failed = False
    for path in args.compare:
        if not path.is_file():
            logger.error("%-34s読めません", path.name)
            failed = True
            continue
        try:
            cur = measure(path, quiet_mask=ref["quiet_mask"])
        except ValueError as exc:
            logger.error("%-34s%s", path.name, exc)
            failed = True
            continue
        delta = cur["samples"] - ref["samples"]
        logger.info("%-34s%10.2fdB%9.2fdB%11.1f%8.2fdB%9.2f%9.4f%+9d",
                    path.name[:33], cur["nonspeech_rms_db"], cur["speech_rms_db"],
                    cur["click_per_min"], cur["peak_db"], cur["fullscale_pct"],
                    correlation(ref["mono"], cur["mono"]), delta)
        if delta != 0:
            logger.error("  ^ sample数がreferenceと違います(%+d)。"
                         "この出力を採ると全出力経路へ時刻ズレを配ります。", delta)
            failed = True
        if cur["rate"] != ref["rate"]:
            logger.error("  ^ sample rateが違います(%d -> %d)", ref["rate"], cur["rate"])
            failed = True

    logger.info("")
    logger.info("nonspeech: BGM残量の代理。分離が効けば下がる。")
    logger.info("speech   : ここまで下がるものは音量を絞っただけ。")
    logger.info("click/min: lip音とartifact。減るのが目的だが、増やす加工の見張りでもある。")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
