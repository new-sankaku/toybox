"""Local speech-to-text over recordings via faster-whisper (CTranslate2, GPU).

faster-whisper is an optional dependency imported lazily, so the base app runs without
it. Model/device/precision are config-driven (config.py) — no model is baked into logic.
No fallback: when STT is disabled, the package is missing, or the model fails to load,
this raises STTError and the caller surfaces it as unavailable."""

import logging
import os
import sys
import threading

from tictok.core.config import (
    get_stt_beam_size,
    get_stt_compute_type,
    get_stt_condition_on_previous_text,
    get_stt_device,
    get_stt_enabled,
    get_stt_language,
    get_stt_model,
    get_stt_no_repeat_ngram_size,
)

logger = logging.getLogger("tictok.stt")


class STTError(RuntimeError):
    """STTが無効・未導入・model読み込み失敗・処理失敗のときに送出する。"""


_model = None
_model_key = None
_model_lock = threading.Lock()
# The shared CTranslate2 model is decoded one request at a time: concurrent
# transcribe() calls on the same instance contend for VRAM (risking OOM) and only
# slow each other down on a single GPU. Serialize the whole decode, not just the
# model.transcribe() call — that call returns a lazy generator and the actual GPU
# work happens while iterating it, so the lock must span the iteration too.
_transcribe_lock = threading.Lock()


def _register_cuda_dll_dirs() -> None:
    """On Windows the CUDA runtime DLLs (cuBLAS/cuDNN) ship inside the venv's
    nvidia/* wheels but their bin directories are not on the loader search path,
    so CTranslate2 fails to find cudnn/cublas at GPU init. Register them with the
    DLL loader before faster-whisper imports CTranslate2. No-op off Windows (the
    wheels expose libs via RPATH there) and when the wheels are absent (CPU-only
    or system-CUDA installs). Paths are resolved from the installed package, not
    hard-coded."""
    if not sys.platform.startswith("win"):
        return
    try:
        import nvidia
    except ImportError:
        return
    # Each nvidia-*-cu12 wheel exposes its DLLs under nvidia/<pkg>/bin (e.g. cublas,
    # cudnn, cuda_runtime, cuda_nvrtc). CTranslate2 resolves cuBLAS/cuDNN at runtime
    # through the loader's PATH search, so add_dll_directory alone is insufficient —
    # the dirs must also be on PATH before the libraries load. Register both so
    # inter-library dependencies (cuBLAS -> cudart, cuDNN -> its sub-DLLs) resolve.
    bin_dirs = []
    for base in getattr(nvidia, "__path__", []):
        try:
            subs = os.listdir(base)
        except OSError:
            continue
        for sub in subs:
            bin_dir = os.path.join(base, sub, "bin")
            if os.path.isdir(bin_dir):
                bin_dirs.append(bin_dir)
                try:
                    os.add_dll_directory(bin_dir)
                except OSError:
                    logger.warning("could not register CUDA DLL dir: %s", bin_dir, exc_info=True)
    if bin_dirs:
        existing = os.environ.get("PATH", "")
        new = [d for d in bin_dirs if d not in existing]
        if new:
            os.environ["PATH"] = os.pathsep.join(new) + os.pathsep + existing


def stt_available() -> bool:
    """faster-whisper が利用可能か（実importせず存在のみ確認、重い初期化はしない）。
    実importは faster_whisper/__init__ 経由でCTranslate2等のネイティブlibをロードし
    初回数秒かかるため、status確認では find_spec でmoduleの存在だけを調べる。実際の
    重いloadは文字起こし実行時(_get_model)にのみ走る。"""
    import importlib.util

    return importlib.util.find_spec("faster_whisper") is not None


def stt_status() -> dict:
    available = stt_available()
    return {
        "enabled": get_stt_enabled(),
        "available": available,
        "configured": bool(get_stt_enabled() and available and get_stt_model()),
        "model": get_stt_model(),
        "device": get_stt_device(),
        "compute_type": get_stt_compute_type(),
    }


def _resolve_device_compute() -> tuple:
    device = get_stt_device()
    compute = get_stt_compute_type()
    if device == "auto":
        try:
            import ctranslate2

            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    if compute == "auto":
        compute = "float16" if device == "cuda" else "int8"
    return device, compute


def _get_model():
    if not get_stt_enabled():
        raise STTError("STTが無効です（TICTOK_STT_ENABLED=1 を設定してください）。")
    _register_cuda_dll_dirs()
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise STTError("faster-whisper が未インストールです（pip install faster-whisper）。") from exc
    model_name = get_stt_model()
    if not model_name:
        raise STTError("STT modelが未設定です（TICTOK_STT_MODEL を設定してください）。")
    device, compute = _resolve_device_compute()
    key = (model_name, device, compute)
    global _model, _model_key
    with _model_lock:
        if _model is None or _model_key != key:
            logger.info("loading whisper model: %s device=%s compute=%s", model_name, device, compute)
            try:
                _model = WhisperModel(model_name, device=device, compute_type=compute)
            except Exception as exc:
                raise STTError(f"STT modelの読み込みに失敗しました: {exc}") from exc
            _model_key = key
    return _model


# faster-whisper's audio decoder (faster_whisper/audio.py) discards every frame's
# presentation timestamp and concatenates only the samples that decode, so a live
# capture whose source dropped audio packets (reconnects, packet loss) yields a
# *gapless* waveform whose timeline is shorter than the media/container timeline the
# <video> element seeks by. The deficit accumulates over the recording, so raw whisper
# segment times drift progressively behind the video (a 3-hour capture can end minutes
# short). We decode once ourselves — mirroring faster-whisper's resample so the waveform
# is bit-identical, hence the transcript text is unchanged — while recording anchors that
# map the gapless decoded-audio axis back onto the container PTS axis. Segment times are
# then restored onto the media timeline so a transcript click seeks accurately throughout.
_TIMEMAP_ANCHOR_STEP_SECONDS = 0.02


def _decode_audio_with_media_map(path: str, sampling_rate: int = 16000):
    """Decode `path` to the 16 kHz mono float32 waveform faster-whisper expects and,
    in the same pass, build anchors mapping that gapless decoded-audio time to the
    media/container PTS time. Returns (audio, anchor_gapless, anchor_media)."""
    import gc
    import io

    import av
    import numpy as np

    resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=sampling_rate)
    raw_buffer = io.BytesIO()
    dtype = None
    gapless = 0.0
    anchor_gapless: list = []
    anchor_media: list = []
    last_delta = None
    try:
        container = av.open(path, mode="r", metadata_errors="ignore")
    except Exception as exc:
        raise STTError(f"音声の読み込みに失敗しました: {exc}") from exc
    with container:
        stream = container.streams.audio[0]
        time_base = float(stream.time_base)
        rate = stream.rate
        frames = container.decode(stream)
        while True:
            try:
                frame = next(frames)
            except StopIteration:
                break
            except av.error.InvalidDataError:
                # Skip a corrupt frame exactly as faster-whisper's decoder does, so the
                # sample total (and thus the gapless axis) stays identical to its output.
                continue
            if frame.pts is not None:
                media = frame.pts * time_base
                delta = media - gapless
                if last_delta is None or abs(delta - last_delta) > _TIMEMAP_ANCHOR_STEP_SECONDS:
                    anchor_gapless.append(gapless)
                    anchor_media.append(media)
                    last_delta = delta
            gapless += frame.samples / rate
            frame.pts = None
            for rframe in resampler.resample(frame):
                array = rframe.to_ndarray()
                dtype = array.dtype
                raw_buffer.write(array)
        for rframe in resampler.resample(None):
            array = rframe.to_ndarray()
            dtype = array.dtype
            raw_buffer.write(array)
    del resampler
    gc.collect()
    audio = np.frombuffer(raw_buffer.getbuffer(), dtype=dtype).astype(np.float32) / 32768.0
    if anchor_gapless:
        # Close the map at the true end so interpolation covers the final run.
        anchor_gapless.append(gapless)
        anchor_media.append(gapless + last_delta)
    return audio, anchor_gapless, anchor_media


def _media_time(anchor_gapless: list, anchor_media: list, t: float) -> float:
    """Linear-interpolate a gapless decoded-audio time onto the media/container axis.
    With no anchors (a gapless source) the map is identity."""
    import bisect

    if not anchor_gapless:
        return t
    i = bisect.bisect_right(anchor_gapless, t) - 1
    if i < 0:
        return t + (anchor_media[0] - anchor_gapless[0])
    if i >= len(anchor_gapless) - 1:
        return t + (anchor_media[-1] - anchor_gapless[-1])
    o0, o1 = anchor_gapless[i], anchor_gapless[i + 1]
    m0, m1 = anchor_media[i], anchor_media[i + 1]
    if o1 == o0:
        return m1
    return m0 + (m1 - m0) * (t - o0) / (o1 - o0)


def transcribe(path: str, on_progress=None) -> dict:
    """Transcribe an audio/video file. Blocking (CPU/GPU bound) — call via a thread.
    on_progress(done_seconds, total_seconds) is invoked per decoded segment."""
    model = _get_model()
    language = get_stt_language() or None
    out_segments = []
    texts = []
    with _transcribe_lock:
        # Decode ourselves so segment times can be restored onto the media/container
        # timeline; the waveform is bit-identical to faster-whisper's own decode, so the
        # transcript text is unaffected. See _decode_audio_with_media_map.
        try:
            audio, anchor_gapless, anchor_media = _decode_audio_with_media_map(path)
        except STTError:
            raise
        except Exception as exc:
            raise STTError(f"文字起こしに失敗しました: {exc}") from exc
        try:
            segments, info = model.transcribe(
                audio,
                language=language,
                beam_size=get_stt_beam_size(),
                vad_filter=True,
                condition_on_previous_text=get_stt_condition_on_previous_text(),
                no_repeat_ngram_size=get_stt_no_repeat_ngram_size(),
            )
        except Exception as exc:
            raise STTError(f"文字起こしに失敗しました: {exc}") from exc
        # info.duration is the gapless decoded length; progress ratios stay in that
        # domain (both numerator and denominator gapless), while emitted segment times
        # are mapped onto the media axis the player seeks by.
        gapless_total = getattr(info, "duration", 0) or 0
        media_total = _media_time(anchor_gapless, anchor_media, gapless_total) if gapless_total else 0
        # The generator does the actual GPU decoding lazily, so progress is emitted
        # here and the lock must stay held across the whole iteration.
        for segment in segments:
            # Keep Whisper's native inter-word spacing in the joined full text (it
            # carries leading spaces) for space-delimited languages; strip only the
            # per-segment display text. Drop empty segments VAD can emit.
            raw = segment.text or ""
            text = raw.strip()
            if text:
                start = round(_media_time(anchor_gapless, anchor_media, segment.start), 2)
                end = round(_media_time(anchor_gapless, anchor_media, segment.end), 2)
                out_segments.append({"start": start, "end": end, "text": text})
                texts.append(raw)
            if on_progress and gapless_total > 0:
                on_progress(segment.end, gapless_total)
    return {
        "text": "".join(texts).strip(),
        "segments": out_segments,
        "language": getattr(info, "language", language) or "",
        "duration": round(media_total, 2) if media_total else gapless_total,
        "model": get_stt_model(),
    }
