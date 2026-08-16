"""Local speech-to-text over recordings via faster-whisper (CTranslate2, GPU).

faster-whisper is an optional dependency imported lazily, so the base app runs without
it. Model/device/precision are config-driven (config.py) — no model is baked into logic.
No fallback: when STT is disabled, the package is missing, or the model fails to load,
this raises STTError and the caller surfaces it as unavailable."""

import logging
import os
import sys
import threading
import time

from tictok.core.config import (
    get_stt_beam_size,
    get_stt_compute_type,
    get_stt_condition_on_previous_text,
    get_stt_device,
    get_stt_enabled,
    get_stt_feature_block_frames,
    get_stt_language,
    get_stt_model,
    get_stt_no_repeat_ngram_size,
)
from tictok.record.recorder import ProgressGate

logger = logging.getLogger("tictok.stt")

# Schema version of the gapless->media time map applied to segment times. Stored on
# every transcript so the population produced by a given mapping is identifiable:
# transcripts written before the mapping existed carry no version, and a future
# change to the anchor rules bumps this, which is what makes "which transcripts need
# re-running" an answerable query instead of a guess.
#
# 2: 幻のtimestamp jumpをplaylistの尺で畳む(_rebase_phantom_jumps)。これを入れた時に版を
#    据え置いたため、壊れた地図で作られた文字起こし(実測: 2時間51分の録画に対し終端10時間43分)が
#    現行版を名乗ったまま残り、画面もDBもそれを見分けられなかった。既存の版1の文字起こしは起動時の
#    timemap_migrationが選別する — 畳む対象が無かったものは版2の出力と一致するので昇格させ、
#    素材と尺が食い違うものだけ版1のまま残して「要再文字起こし」として名乗らせる。
TIMEMAP_VERSION = 2


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
                    logger.warning(
                        "CUDAのDLL dir %s を登録できません（GPUでの文字起こしがCPUへ"
                        "落ちる可能性があります）", bin_dir,
                        extra={"event": "stt.cuda_dll_dir_rejected",
                               "ctx": {"path": bin_dir}},
                        exc_info=True,
                    )
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
        # 画面がtranscriptの時刻mapの版を「現行かどうか」で判定できるようにする。
        # 版が古いtranscriptは字幕のtimecodeがズレるため、書き出し前に警告が要る。
        "timemap_version": TIMEMAP_VERSION,
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


# faster-whisper's numpy FeatureExtractor computes the STFT of the entire waveform in one
# array: np.fft.rfft returns complex128, so a 3-hour capture needs a single (1, ~1.1M, 201)
# complex128 buffer (~3.3 GiB) and raises MemoryError before decoding even starts — the
# feature step runs on the CPU/numpy path regardless of device, so a GPU model does not help.
# The log-mel that model.transcribe actually consumes is small (feature_size x n_frames
# float32); only the transient STFT is huge. We compute that log-mel in frame blocks so the
# transient buffer is bounded, mirroring FeatureExtractor.__call__ exactly (same reflect
# padding, hanning window, complex64 magnitudes, mel matmul, global normalization). STFT
# frames are independent, so the produced features are bit-identical and the transcript is
# unchanged. No fallback: if the vendored extractor's shape differs from what we mirror, we
# raise STTError rather than silently degrade.
_blocked_fe_installed = False


def _install_blocked_feature_extractor(model) -> None:
    global _blocked_fe_installed
    import numpy as np

    fe = model.feature_extractor
    required = ("n_fft", "hop_length", "mel_filters", "sampling_rate", "chunk_length")
    missing = [a for a in required if not hasattr(fe, a)]
    if missing:
        raise STTError(
            "faster-whisper の FeatureExtractor 実装が想定と異なります"
            f"（不足属性: {missing}）。block化した特徴抽出を安全に適用できません。"
        )

    base_cls = type(fe)
    block_frames = get_stt_feature_block_frames()
    if block_frames < 1:
        raise STTError(f"TICTOK_STT_FEATURE_BLOCK_FRAMES は1以上にしてください（現在 {block_frames}）。")

    class _BlockedFeatureExtractor(base_cls):
        # Overrides only __call__; every other attribute/method is inherited unchanged so
        # transcribe()'s use of sampling_rate/hop_length/nb_max_frames/time_per_frame holds.
        def __call__(self, waveform, padding=160, chunk_length=None):
            if chunk_length is not None:
                # Preserve the side effect the original relies on for the batched path.
                self.n_samples = chunk_length * self.sampling_rate
                self.nb_max_frames = self.n_samples // self.hop_length
            if waveform.dtype is not np.float32:
                waveform = waveform.astype(np.float32)
            if padding:
                waveform = np.pad(waveform, (0, padding))
            n_fft = self.n_fft
            hop = self.hop_length
            window = np.hanning(n_fft + 1)[:-1].astype("float32")
            # Mirror FeatureExtractor.stft framing: center=True reflect-pad then strided frames.
            x = np.expand_dims(waveform, 0)
            pad_amount = n_fft // 2
            x = np.pad(x, ((0, 0), (pad_amount, pad_amount)), mode="reflect")
            length = x.shape[1]
            n_frames = 1 + (length - n_fft) // hop
            # The original drops the final STFT frame (magnitudes = abs(stft[..., :-1]) ** 2).
            use_frames = n_frames - 1
            if use_frames < 1:
                raise STTError("音声が短すぎて文字起こしできません。")
            frames = np.lib.stride_tricks.as_strided(
                x, (1, n_frames, n_fft), (x.strides[0], hop * x.strides[1], x.strides[1])
            )
            # Fill the full magnitudes array (small float32, unlike the complex128 STFT) in
            # blocks, then run the mel matmul once over the whole array exactly as the
            # original does. Blocking only the transient rfft — not the matmul — keeps the
            # BLAS reduction order identical, so the log-mel is bit-identical to the original.
            magnitudes = np.empty((n_fft // 2 + 1, use_frames), dtype=np.float32)
            for i in range(0, use_frames, block_frames):
                j = min(i + block_frames, use_frames)
                spec = np.fft.rfft(frames[0, i:j, :] * window, n=n_fft, axis=-1).astype("complex64")
                magnitudes[:, i:j] = (np.abs(spec) ** 2).T
            mel_spec = self.mel_filters @ magnitudes
            log_spec = np.log10(np.clip(mel_spec, a_min=1e-10, a_max=None))
            log_spec = np.maximum(log_spec, log_spec.max() - 8.0)
            log_spec = (log_spec + 4.0) / 4.0
            return log_spec

    # Retype the existing instance so all loaded state (mel_filters, etc.) is preserved.
    fe.__class__ = _BlockedFeatureExtractor
    if not _blocked_fe_installed:
        logger.info(
            "分割版のfeature extractorを組み込みました（block_frames=%d）", block_frames,
            extra={"event": "stt.feature_extractor_installed",
                   "ctx": {"block_frames": block_frames,
                           "extractor": base_cls.__name__}},
        )
        _blocked_fe_installed = True


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
            started = time.monotonic()
            logger.info(
                "whisper modelを読み込みます: %s device=%s compute=%s", model_name, device, compute,
                extra={"event": "stt.model_load_started",
                       "ctx": {"model": model_name, "device": device, "compute": compute}},
            )
            try:
                _model = WhisperModel(model_name, device=device, compute_type=compute)
            except Exception as exc:
                logger.error(
                    "whisper model %s を %s で読み込めません", model_name, device,
                    extra={"event": "stt.model_load_failed",
                           "ctx": {"model": model_name, "device": device,
                                   "compute": compute,
                                   "duration_ms": int((time.monotonic() - started) * 1000)}},
                    exc_info=True,
                )
                raise STTError(f"STT modelの読み込みに失敗しました: {exc}") from exc
            _install_blocked_feature_extractor(_model)
            _model_key = key
            logger.info(
                "whisper modelの準備ができました: %s / %s（%s）", model_name, device, compute,
                extra={"event": "stt.model_loaded",
                       "ctx": {"model": model_name, "device": device, "compute": compute,
                               "duration_ms": int((time.monotonic() - started) * 1000)}},
            )
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
# A jump smaller than this is never treated as a source-timestamp glitch: real gaps of a
# few seconds (a reconnect, a run of dropped audio packets) are elapsed media time and
# must stay on the map.
_PHANTOM_JUMP_MIN_SECONDS = 5.0
# Slack between the playlist's span and the decoded end before a rebase is considered.
# Covers the tail after the last keyframe and EXTINF rounding across thousands of entries.
_PLAYLIST_SPAN_TOLERANCE_SECONDS = 5.0


def _playlist_media_total(path: str):
    """HLS playlistの ``#EXTINF`` 合計(=playerが進む秒)。playlist以外・読めなければNone。

    採用集合のplaylistは録画の media span の唯一の権威である(recorder._playlist_segments)。
    復号側の時刻がこれを超えたなら、超えたぶんは経過時間ではない。"""
    if not str(path).lower().endswith(".m3u8"):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return None
    total = 0.0
    for line in text.splitlines():
        if line.startswith("#EXTINF:"):
            try:
                total += float(line[8:].split(",", 1)[0])
            except ValueError:
                continue
    return total if total > 0 else None


def _rebase_phantom_jumps(anchor_gapless: list, anchor_media: list, playlist_total):
    """源のtimestampが壊れたsegmentが残した「幻のjump」をmedia軸から取り除く。

    採用集合のplaylistは壊れたsegment自体を落とすが、**その隣のsegmentが持つPTSは壊れた
    ままである**。ffmpegは ``#EXT-X-DISCONTINUITY`` で時刻を貼り直すのに対し、PyAVは貼り
    直さないため、復号側の時刻だけが飛ぶ。実測(00126): playlistは10297.4sなのにPyAVの終端
    は38586.1sで、630.7s地点に+28288.4sのjumpが1つあった。そのまま地図にすると、字幕は
    録画の外側を指す。

    判定はplaylistの尺で行う — 「大きいjumpは疑わしい」ではなく「**playlistの尺を超えた
    ぶんだけが幻**」である。音声が実在しない本物の穴(録画00268-682で実測34.2s)は尺の内側に
    収まるので、こちらは触らない。大きいjumpから順に、終端が尺へ収まるまで畳む。

    ``(畳んだ後のmedia, 畳んだ秒数, 畳んだ箇所数)`` を返す。"""
    if playlist_total is None or len(anchor_media) < 2:
        return anchor_media, 0.0, 0
    if anchor_media[-1] <= playlist_total + _PLAYLIST_SPAN_TOLERANCE_SECONDS:
        return anchor_media, 0.0, 0
    # 各anchorが持ち込んだ「音声の進みに対する超過」= そこで開いた穴。
    gaps = [
        (anchor_media[i] - anchor_media[i - 1]) - (anchor_gapless[i] - anchor_gapless[i - 1])
        for i in range(1, len(anchor_media))
    ]
    order = sorted(range(len(gaps)), key=lambda i: gaps[i], reverse=True)
    media = list(anchor_media)
    absorbed = 0.0
    count = 0
    for index in order:
        if media[-1] <= playlist_total + _PLAYLIST_SPAN_TOLERANCE_SECONDS:
            break
        jump = gaps[index]
        if jump < _PHANTOM_JUMP_MIN_SECONDS:
            break
        for k in range(index + 1, len(media)):
            media[k] -= jump
        absorbed += jump
        count += 1
    return media, absorbed, count


def _decode_audio_with_media_map(path: str, sampling_rate: int = 16000):
    """Decode `path` to the 16 kHz mono float32 waveform faster-whisper expects and,
    in the same pass, build anchors mapping that gapless decoded-audio time to the
    media/container PTS time. Returns (audio, anchor_gapless, anchor_media)."""
    import gc
    import io

    import av
    import numpy as np

    started = time.monotonic()
    resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=sampling_rate)
    raw_buffer = io.BytesIO()
    dtype = None
    gapless = 0.0
    anchor_gapless: list = []
    anchor_media: list = []
    last_delta = None
    # Corrupt frames are skipped (as faster-whisper's own decoder does) but counted:
    # each one is audio that exists in the container and not in the waveform, i.e. a
    # direct contributor to the gapless/media divergence this map corrects. Without a
    # count, a transcript that drifted badly is indistinguishable from one that did not.
    invalid_frames_skipped = 0
    try:
        container = av.open(path, mode="r", metadata_errors="ignore")
    except Exception as exc:
        logger.error(
            "文字起こしのために %s を開けません", os.path.basename(path),
            extra={"event": "stt.audio_open_failed", "ctx": {"path": path}},
            exc_info=True,
        )
        raise STTError(f"音声の読み込みに失敗しました: {exc}") from exc
    with container:
        stream = container.streams.audio[0]
        time_base = float(stream.time_base)
        rate = stream.rate
        # 出す時刻は**playerがseekする軸**でなければならない。その軸は0始まりだが、
        # containerの内部timestampは0始まりとは限らない。HLSのsegmentは実測1.438s から
        # 始まり、**PyAVはffmpegと違って先頭を0へ寄せない**(ffmpegは-copytsを付けない
        # 限り寄せる)。引かないまま出すと、文字起こしの全segmentがそのぶん後ろへずれ、
        # 字幕clickのseekが丸ごと1.4秒ずれる。mp4では0.016s(=最初の音声frame)で、
        # 引いても1 frame未満の補正にしかならない。
        origin = (container.start_time / av.time_base) if container.start_time is not None else 0.0
        frames = container.decode(stream)
        while True:
            try:
                frame = next(frames)
            except StopIteration:
                break
            except av.error.InvalidDataError:
                # Skip a corrupt frame exactly as faster-whisper's decoder does, so the
                # sample total (and thus the gapless axis) stays identical to its output.
                invalid_frames_skipped += 1
                continue
            if frame.pts is not None:
                media = frame.pts * time_base - origin
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
    # 壊れた源timestampが残した幻のjumpを、playlistの尺を権威にして畳む(_rebase_phantom_jumps)。
    playlist_total = _playlist_media_total(path)
    anchor_media, absorbed, absorbed_count = _rebase_phantom_jumps(
        anchor_gapless, anchor_media, playlist_total)
    if absorbed_count:
        logger.warning(
            "幻のtimestamp jump %d 件（%.1fs）を %s で畳みました（playlistの尺は %.1fs）",
            absorbed_count, absorbed, os.path.basename(path), playlist_total or 0.0,
            extra={"event": "stt.phantom_jump_rebased",
                   "ctx": {"path": path, "jumps": absorbed_count,
                           "absorbed_seconds": round(absorbed, 3),
                           "playlist_seconds": round(playlist_total or 0.0, 3)}},
        )
    # drift_seconds is the whole point of this pass: how far the end of the gapless
    # waveform sits behind the container timeline the player seeks by. It is also the
    # field that identifies which stored transcripts were produced from a drifting
    # source and therefore need re-running when the mapping changes.
    drift_seconds = round(anchor_media[-1] - anchor_gapless[-1], 3) if anchor_gapless else 0.0
    logger.info(
        "%.1fs 分の音声を %s から復号しました（timemapのanchor %d 件, ズレ %.3fs）",
        gapless, os.path.basename(path), len(anchor_gapless), drift_seconds,
        extra={"event": "stt.audio_decoded",
               "ctx": {"path": path, "anchors": len(anchor_gapless),
                       "drift_seconds": drift_seconds,
                       "timemap_version": TIMEMAP_VERSION,
                       "invalid_frames_skipped": invalid_frames_skipped,
                       "gapless_seconds": round(gapless, 3),
                       "duration_ms": int((time.monotonic() - started) * 1000)}},
    )
    if invalid_frames_skipped:
        logger.warning(
            "壊れた音声frame %d 件を %s の復号中にskipしました（文字起こしはcontainerより"
            "短い音声しか覆いません）",
            invalid_frames_skipped, os.path.basename(path),
            extra={"event": "stt.invalid_frames_skipped",
                   "ctx": {"path": path,
                           "invalid_frames_skipped": invalid_frames_skipped,
                           "drift_seconds": drift_seconds}},
        )
    return audio, anchor_gapless, anchor_media, drift_seconds


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
    """Transcribe an audio/video file. Blocking (CPU/GPU bound).

    **Runs in the STT worker process, never in the server** — importing CTranslate2 into
    a process that also loads torch puts two cuDNN versions behind one DLL name and kills
    it outright (see tictok.record.stt_worker). Callers go through
    ``stt_worker.run_transcribe``, which owns the GPU slot for the child's lifetime; that
    is why no slot is taken here (``gpu_slot`` is per-process and would not line up with
    the burn-in's).

    on_progress(done_seconds, total_seconds) is invoked per decoded segment."""
    model = _get_model()
    language = get_stt_language() or None
    out_segments = []
    texts = []
    started = time.monotonic()
    gate = ProgressGate()
    # The private lock keeps concurrent decodes off the shared CTranslate2 model. The GPU
    # slot is held by the parent (stt_worker.run_transcribe) around this whole process —
    # taking it here would acquire the *worker's* semaphore, which no other job shares.
    with _transcribe_lock:
        # Decode ourselves so segment times can be restored onto the media/container
        # timeline; the waveform is bit-identical to faster-whisper's own decode, so the
        # transcript text is unaffected. See _decode_audio_with_media_map.
        try:
            audio, anchor_gapless, anchor_media, drift_seconds = _decode_audio_with_media_map(path)
        except STTError:
            raise
        except Exception as exc:
            logger.error(
                "%s の音声の復号に失敗しました", os.path.basename(path),
                extra={"event": "stt.audio_decode_failed", "ctx": {"path": path}},
                exc_info=True,
            )
            raise STTError(f"文字起こしに失敗しました: {exc}") from exc
        try:
            segments, info = model.transcribe(
                audio,
                language=language,
                beam_size=get_stt_beam_size(),
                vad_filter=True,
                condition_on_previous_text=get_stt_condition_on_previous_text(),
                no_repeat_ngram_size=get_stt_no_repeat_ngram_size(),
                # 語ごとの時刻。**字幕として使うための必須条件**であって、装飾のためではない。
                # segmentは1件が数十秒になることがあり(実測: 全297文字起こし459,738件のうち5秒超が
                # 16.5%・20秒超が1.0%・最大5,354秒)、それを1枚のテロップとして出すと、画面には
                # 40秒ぶんの文が居座り、その間ずっと別の言葉が喋られる。「テロップが合わない」の
                # 実体はこれで、時刻軸をどう直しても解けない — 分割できる位置がdataに無いため。
                # 文字数で按分して割るのは時刻の捏造なので採らない(tictok.record.subtitles)。
                word_timestamps=True,
            )
        except Exception as exc:
            logger.error(
                "%s のwhisperの復号に失敗しました", os.path.basename(path),
                extra={"event": "stt.transcribe_failed",
                       "ctx": {"path": path, "model": get_stt_model(),
                               "language": language,
                               "duration_ms": int((time.monotonic() - started) * 1000)}},
                exc_info=True,
            )
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
                row = {"start": start, "end": end, "text": text}
                # 語の時刻も同じmedia軸へ写して持つ。持たない文字起こし(既存分)と区別できるよう、
                # 空listではなくkey自体を置かない。
                words = [
                    {"start": round(_media_time(anchor_gapless, anchor_media, w.start), 2),
                     "end": round(_media_time(anchor_gapless, anchor_media, w.end), 2),
                     "text": (w.word or "")}
                    for w in (getattr(segment, "words", None) or [])
                    if w.start is not None and w.end is not None and (w.word or "").strip()
                ]
                if words:
                    row["words"] = words
                out_segments.append(row)
                texts.append(raw)
            if on_progress and gapless_total > 0:
                on_progress(segment.end, gapless_total)
            if gapless_total > 0:
                percent = 100.0 * min(segment.end, gapless_total) / gapless_total
                if gate.due(percent):
                    elapsed = time.monotonic() - started
                    logger.info(
                        "%s を文字起こし中: 音声 %.0f/%.0fs（%.1f%%）, segment %d 件",
                        os.path.basename(path), segment.end, gapless_total,
                        percent, len(out_segments),
                        extra={"event": "stt.progress_reported",
                               "ctx": {"path": path, "percent": round(percent, 2),
                                       "audio_seconds": round(segment.end, 1),
                                       "gapless_seconds": round(gapless_total, 1),
                                       "segments": len(out_segments),
                                       "realtime_factor": round(segment.end / elapsed, 3) if elapsed > 0 else None,
                                       "duration_ms": int(elapsed * 1000)}},
                    )
    elapsed = time.monotonic() - started
    logger.info(
        "%s の文字起こしが完了しました: segment %d 件 / 音声 %.0fs 分",
        os.path.basename(path), len(out_segments), media_total or gapless_total,
        extra={"event": "stt.transcribed",
               "ctx": {"path": path, "model": get_stt_model(),
                       "language": getattr(info, "language", language) or "",
                       "segments": len(out_segments),
                       "characters": len("".join(texts)),
                       "anchors": len(anchor_gapless),
                       "drift_seconds": drift_seconds,
                       "timemap_version": TIMEMAP_VERSION,
                       "gapless_seconds": round(gapless_total, 3),
                       "media_seconds": round(media_total, 3) if media_total else None,
                       "realtime_factor": round(gapless_total / elapsed, 3) if elapsed > 0 else None,
                       "duration_ms": int(elapsed * 1000)}},
    )
    return {
        "text": "".join(texts).strip(),
        "segments": out_segments,
        "language": getattr(info, "language", language) or "",
        "duration": round(media_total, 2) if media_total else gapless_total,
        "model": get_stt_model(),
        # Carried into the transcripts row (see Storage.save_transcript): these three
        # identify the time mapping a stored transcript was produced under, which is
        # what makes "select the transcripts that must be re-run" a query rather than a
        # re-transcription of everything.
        "timemap_version": TIMEMAP_VERSION,
        "timemap_anchors": len(anchor_gapless),
        "timemap_drift_seconds": drift_seconds,
    }
