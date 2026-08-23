"""録画の音声から「人が声を出している区間」を作る(Silero VAD)。

== なぜ文字起こしの語の時刻ではないのか ==

「誰か喋っているか」を語の時刻で代用していた版は、実録画4本で**速い区間の4.4〜43.8%が
実際には声**だった。語の時刻はVADより +0.22〜+0.30秒 遅れており(1本は -0.78秒ずれ、重なりが
53%しかない)、発声の入りが中央値0.29〜0.62秒・最大7.2秒ぶん速いまま流れていた。

語の時刻は文字起こしの副産物である。whisperは「何と言ったか」を解くmodelで、語の境界はその
途中で出てくる推定にすぎない。「声が在るか」は別の問いで、専用の計器がある。同じ4本をVADで
測り直すと**食い込みは0%**になり、しかも倍率は落ちない(語ベース2.16〜2.64x に対し
VAD 2.05〜2.55x)。

副産物としてもう1つ効く: **文字起こしが要らなくなる**。語の時刻を持つ文字起こしは387件中
209件しか無く、語ベースの版はそれ以外の録画で何もできなかった。

== 確率を保存する ==

sidecarへ書くのは0.0〜1.0の**生確率**で、区間ではない。閾値は素材で最適値が変わる
(実測: VADの既定0.5は0.2に比べ声を299〜672秒落とす)。生確率を残せば後から掃引でき、閾値を
変えても再解析が要らない。区間化は問い合わせ側(``speech_spans``)にだけ置く。

刻みは0.1秒で、VADの生frame(32ms)を**max**で畳む。maxなのは畳みが声を広げる側へ倒れて
ほしいため — 平均で畳むと語頭の1 frameが薄まって閾値を下回る。

== Fallbackを持たない ==

decodeの失敗・modelの読み込み失敗はいずれも ``VoiceError``。黙って「声が無かった」を返すのが
最悪で、その録画は全編が速く流れる。
"""
import asyncio
import json
import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from tictok.core import cancel
from tictok.core.config import (get_voice_frame_seconds, get_voice_min_silence_seconds,
                                get_voice_min_speech_seconds, get_voice_threshold)
from tictok.media import hls_source
from tictok.media.waveform import _RESAMPLE_FILTER, _StderrDrain
from tictok.record.recorder import ffmpeg_available, ffmpeg_ctx, sidecar_path

logger = logging.getLogger("tictok.voice")

VOICE_SUFFIX = ".voice.json"
# sidecarのschema version。刻み・畳み方・保存する項を変えたら上げる。
_PROFILE_VERSION = 1
# Silero VADの契約。16kHzで512 sampleが1 frame(=32ms)で、これ以外の刻みは受け付けない。
SAMPLE_RATE = 16000
VAD_FRAME_SAMPLES = 512
# 1回のmodel呼び出しへ渡す長さ。modelはLSTMで呼び出しごとに状態が初期化されるため、短く切ると
# 境目の数frameだけ文脈を失う。5分なら3時間の録画で境目は36回に留まり、memoryも19MBで済む
# (全部載せると690MB)。
CHUNK_SECONDS = 300
READ_CHUNK_BYTES = 1 << 20
_BYTES_PER_SAMPLE = 2
_FULL_SCALE = 32768.0
_PROB_DECIMALS = 3
# 刻み(秒)をsidecarへ書くときの丸め。fileへ書く値とcacheの照合値が同じ関数から出るように、
# 桁数も1箇所に置く。
_INTERVAL_DECIMALS = 3

_model = None
_model_lock = threading.Lock()
_build_locks: dict = {}
_build_locks_guard = threading.Lock()


class VoiceError(RuntimeError):
    """声区間の解析に失敗した。無音として返さず、必ず送出する。"""


def voice_profile_path(src) -> Path:
    return sidecar_path(Path(src), VOICE_SUFFIX)


def voice_artifact_paths(src) -> tuple:
    """この録画の声profileを構成するfile。sweepと一括の「済み」判定が実在を見る先。

    1つしか無いがtupleで返すのは、波形(表示用と絶対level)・サムネ(sheetとindex)と同じ形で
    扱えるようにするため。片方だけ在る状態を済みと数えない判定を種別ごとに書き分けない。
    """
    return (voice_profile_path(src),)


def _get_model():
    """Silero VAD(faster-whisper同梱のONNX)。processで1つを使い回す。"""
    global _model
    with _model_lock:
        if _model is None:
            try:
                from faster_whisper.vad import get_vad_model
                _model = get_vad_model()
            except Exception as exc:
                logger.error("Silero VADを読み込めませんでした",
                             extra={"event": "voice.model_failed",
                                    "ctx": {"error": str(exc)}}, exc_info=True)
                raise VoiceError(f"Silero VADを読み込めませんでした: {exc}") from exc
        return _model


def _lock_for(key: str) -> asyncio.Lock:
    with _build_locks_guard:
        lock = _build_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _build_locks[key] = lock
        return lock


def _source_key(src: Path) -> dict:
    key = hls_source.fingerprint(src)
    return {**key, "mtime": round(key["mtime"], 3)}


def _key_matches(data: dict, key: dict) -> bool:
    return all(data.get(name) == value for name, value in key.items())


def _snap_interval(interval: float) -> tuple:
    """要求の刻みを、VADのframe(512 sample = 32ms)の整数倍へ吸着させる。
    ``(1binのframe数, 実際の刻み秒)`` を返す。

    VADは32msの倍数でしか確率を出さないので、頼まれた刻みちょうどには乗らない(0.1秒を
    頼むとframe 3つ = 0.096秒になる)。sidecarへ書くのも、``speech_spans`` が秒へ戻すのも
    この**吸着後の実値**で、要求値の方はどこにも残らない。

    要求値と実値の両方を扱う場所が2つある(``_fold`` が書き、``_load_cache`` が照合する)ため、
    吸着はここ1箇所に置く。書く側だけが吸着して照合側が要求値のまま比べていた頃は、
    ``0.096 != 0.1`` が必ず成立してcacheが**1件も当たらず**、再生画面を開くたびに全編の
    VADが走り直していた(実測: sidecar 212件中HIT 0件、1本あたり最大52.9秒)。
    """
    per = max(1, int(round(interval * SAMPLE_RATE / VAD_FRAME_SAMPLES)))
    return per, round(per * VAD_FRAME_SAMPLES / SAMPLE_RATE, _INTERVAL_DECIMALS)


def _load_cache(src: Path, interval: float) -> dict:
    """有効なcacheがあれば返す。**閾値は鍵に含めない** — 保存してあるのは閾値を掛ける前の
    生確率なので、閾値を変えても作り直す必要が無い(それがこの形で保存している理由)。"""
    path = voice_profile_path(src)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if data.get("version") != _PROFILE_VERSION:
        return {}
    # 照合するのは要求値ではなく**吸着後の実値**。sidecarに書いてあるのがそちらなので、
    # 要求値のまま比べるとcacheは永久に当たらない(_snap_interval参照)。
    if data.get("interval_seconds") != _snap_interval(interval)[1]:
        return {}
    try:
        key = _source_key(src)
    except (OSError, hls_source.SourceMissing):
        return {}
    if not _key_matches(data, key):
        return {}
    probs = data.get("probs")
    if not isinstance(probs, list):
        return {}
    return {"interval_seconds": data["interval_seconds"],
            "duration_seconds": float(data.get("duration_seconds", 0.0)),
            "probs": probs}


def _store_cache(src: Path, profile: dict) -> None:
    """cacheを書く。書けなくても値自体は返せるので警告に留める(waveformと同じ)。"""
    path = voice_profile_path(src)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": _PROFILE_VERSION, "sample_rate": SAMPLE_RATE,
                   **_source_key(src), **profile}
        tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}-{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.warning("%s の声profile cacheの書き込みに失敗しました", src.name,
                       extra={"event": "voice.cache_write_failed",
                              "ctx": {"src": str(src), "path": str(path),
                                      "error": str(exc)}})


def _frame_probs(source) -> np.ndarray:
    """音声を16kHz monoでdecodeしながらVADへ通し、32msごとの声確率を返す。

    全部をmemoryへ載せない(3時間で690MB)。``CHUNK_SECONDS`` ごとにmodelへ渡し、frameの
    切れ目に満たない端数だけを持ち越す。時間軸は波形・音量profileと同じ ``aresample`` で、
    確率列のindexがそのまま再生位置に対応する。
    """
    src = source.path
    args = ["ffmpeg", "-v", "error", "-nostdin", *source.input_args, "-i", str(src),
            "-vn", "-map", "0:a:0", "-af", _RESAMPLE_FILTER,
            "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
    try:
        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                bufsize=READ_CHUNK_BYTES)
    except OSError as exc:
        logger.error("声区間の解析で %s のffmpegを起動できませんでした", src.name,
                     extra={"event": "voice.launch_failed",
                            "ctx": {"src": str(src), **ffmpeg_ctx(args),
                                    "error": str(exc)}}, exc_info=True)
        raise VoiceError(f"声区間の解析でffmpegを起動できませんでした: {exc}") from exc
    cancel.register_process(proc)
    drain = _StderrDrain(proc.stderr)

    model = _get_model()
    block = CHUNK_SECONDS * SAMPLE_RATE
    out: list = []
    buf = np.empty(0, dtype=np.float32)
    carry = b""
    try:
        while True:
            chunk = proc.stdout.read(READ_CHUNK_BYTES)
            if not chunk:
                break
            carry += chunk
            usable = len(carry) - (len(carry) % _BYTES_PER_SAMPLE)
            samples = np.frombuffer(carry[:usable], dtype="<i2").astype(np.float32)
            carry = carry[usable:]
            samples = samples / _FULL_SCALE
            buf = np.concatenate([buf, samples]) if buf.size else samples
            while buf.size >= block:
                out.append(np.asarray(model(buf[:block])))
                buf = buf[block:]
        # 端数。VADはframeの整数倍しか受け付けないので0詰めして最後まで見る。
        if buf.size:
            pad = (-buf.size) % VAD_FRAME_SAMPLES
            if pad:
                buf = np.concatenate([buf, np.zeros(pad, dtype=np.float32)])
            out.append(np.asarray(model(buf)))
        proc.stdout.close()
        code = proc.wait()
        stderr = drain.text()
        if code != 0:
            logger.error("声区間の解析で %s のffmpegが失敗しました（rc=%s）", src.name, code,
                         extra={"event": "voice.ffmpeg_failed",
                                "ctx": {"src": str(src), "returncode": code,
                                        "stderr": stderr[-2000:], **ffmpeg_ctx(args)}})
            raise VoiceError(
                f"声区間の解析で音声を読めませんでした（rc={code}）: {stderr[-300:]}")
    finally:
        cancel.forget_process(proc)
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    return np.concatenate(out) if out else np.empty(0, dtype=np.float32)


def _fold(frames: np.ndarray, interval: float) -> dict:
    """32msのframeを ``interval`` 秒へ **max** で畳む。

    maxなのは畳みが声を広げる側へ倒れてほしいため。平均で畳むと、語頭の1 frameだけが高い所が
    薄まって閾値を下回る — それは聞き手が戻らないと取り返せない唯一の失敗である。

    ``interval_seconds`` として書くのは要求値ではなく吸着後の実値で、cacheの照合も
    ``speech_spans`` の秒換算も同じ値を見る(``_snap_interval``)。
    """
    per, step = _snap_interval(interval)
    n = int(frames.size)
    if n == 0:
        return {"interval_seconds": step, "duration_seconds": 0.0, "probs": []}
    starts = np.arange(0, n, per, dtype=np.int64)
    reduced = np.maximum.reduceat(frames, starts)
    return {"interval_seconds": step,
            "duration_seconds": round(n * VAD_FRAME_SAMPLES / SAMPLE_RATE, 3),
            "probs": [round(float(v), _PROB_DECIMALS) for v in reduced]}


def _build(src: Path, interval: float) -> dict:
    with hls_source.ffmpeg_source(src) as source:
        frames = _frame_probs(source)
    profile = _fold(frames, interval)
    logger.info("声profileを作成しました: %s（音声 %.1fs, %d点）",
                src.name, profile["duration_seconds"], len(profile["probs"]),
                extra={"event": "voice.built",
                       "ctx": {"src": str(src), "points": len(profile["probs"]),
                               "duration_seconds": profile["duration_seconds"],
                               "interval_seconds": profile["interval_seconds"]}})
    return profile


async def ensure_voice_profile(src: Path) -> dict:
    """``src``の声確率列を返す(cacheがあればそれを、無ければ解析してcacheする)。

    戻り値: ``{"interval_seconds": float, "duration_seconds": float, "probs": list[float]}``。
    probsは0.0〜1.0の**生確率**で、閾値は掛かっていない。区間化は ``speech_spans`` を使う。
    """
    src = Path(src)
    interval = get_voice_frame_seconds()
    if interval <= 0:
        raise VoiceError("声profileの刻み幅は正の値にしてください。")
    if not hls_source.available(src):
        raise hls_source.SourceMissing()
    cached = await asyncio.to_thread(_load_cache, src, interval)
    if cached:
        return cached
    if not ffmpeg_available():
        raise VoiceError("ffmpegが見つかりません。声区間の解析にはffmpegのinstallが必要です。")
    async with _lock_for(str(src.resolve())):
        cached = await asyncio.to_thread(_load_cache, src, interval)
        if cached:
            return cached
        profile = await asyncio.to_thread(_build, src, interval)
        await asyncio.to_thread(_store_cache, src, profile)
    return profile


def load_voice_profile(src) -> dict:
    """既に在る声profileだけを返す(無ければ空dict)。**解析はしない。**"""
    return _load_cache(Path(src), get_voice_frame_seconds())


def speech_spans(profile: dict, threshold: Optional[float] = None,
                 min_silence: Optional[float] = None,
                 min_speech: Optional[float] = None) -> list:
    """声が出ている区間 ``[{"start": 秒, "end": 秒}]``。

    ``min_silence`` より短い途切れは声の中の息継ぎとして埋める(区切ると、詰めるほどでもない
    隙間で速度が往復する)。``min_speech`` より短い声は落とす。
    """
    probs = profile.get("probs") or []
    interval = profile.get("interval_seconds") or 0
    if not probs or interval <= 0:
        return []
    threshold = get_voice_threshold() if threshold is None else threshold
    min_silence = get_voice_min_silence_seconds() if min_silence is None else min_silence
    min_speech = get_voice_min_speech_seconds() if min_speech is None else min_speech

    spans: list = []
    run = None
    for i, prob in enumerate(list(probs) + [None]):
        hit = prob is not None and prob >= threshold
        if hit and run is None:
            run = i
        elif not hit and run is not None:
            spans.append([run * interval, i * interval])
            run = None
    if not spans:
        return []
    merged = [spans[0]]
    for start, end in spans[1:]:
        if start - merged[-1][1] < min_silence:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    # 最短の声はbin数で測る。刻みは要求値ちょうどには乗らず(0.1秒を頼むと32msのVAD frame 3つ
    # =0.096秒になる)、秒で比べると**1 binだけの声が必ず落ちる** — 落とさないつもりで置いた
    # 下限が、落としたくないものだけを落としていた。実録画では確率0.25の語が丸ごと飛んでいた。
    least = max(1, int(round(min_speech / interval)))
    return [{"start": round(a, 3), "end": round(b, 3)}
            for a, b in merged if round((b - a) / interval) >= least]
