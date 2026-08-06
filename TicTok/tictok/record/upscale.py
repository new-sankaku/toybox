"""Local AI video upscaling (super-resolution) over finished recordings.

torch + spandrel are optional dependencies imported lazily, so the base app runs
without them. The model is a deployment-provided weights file (any super-resolution
architecture spandrel can load — e.g. Real-ESRGAN — loaded generically, nothing baked
into logic); device/precision/tiling are config-driven (config.py). No fallback: when
upscaling is disabled, the packages are missing, or the model fails to load, this
raises UpscaleError and the caller surfaces the feature as unavailable rather than
returning a non-upscaled file as if it were upscaled.

Pipeline: ffmpeg decodes the source to raw RGB frames on a pipe, each frame runs
through the model on the GPU (tiled to bound VRAM), and a second ffmpeg muxes the
upscaled frames with the source audio into the output mp4 using the same encoder
selection (NVENC first) and quality mapping as the burn-in output.
"""

import hashlib
import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from tictok.core.config import (
    get_db_path,
    get_log_dir,
    get_upscale_compute_type,
    get_upscale_device,
    get_upscale_enabled,
    get_upscale_max_height,
    get_upscale_model_path,
    get_upscale_tile,
    get_upscale_tile_overlap,
)
from tictok.core import cancel
from tictok.core import ffprobe
from tictok.core.config import get_normalize_scale_mode
from tictok.media import hls_source
from tictok.record import audio_norm
from tictok.core.gpu import gpu_slot
from tictok.paths import PROJECT_ROOT
from tictok.record.recorder import (
    ProgressGate,
    _normalize_filter,
    ffmpeg_available,
    ffmpeg_ctx,
    ffprobe_available,
    log_disk_preflight,
    sidecar_dir,
    sidecar_path,
)
from tictok.record.video_overlay import (
    _encoder_args,
    _mapped_quality,
    _parse_fps,
    overlay_paths,
    overlay_paths_b,
)

logger = logging.getLogger("tictok.upscale")

UPSCALE_SUFFIX = ".up.mp4"
UPSCALE_META_SUFFIX = ".up.meta"
UPSCALE_LOG_SUFFIX = ".up.ffmpeg.log"
# Cache-signature schema version; bump when the render pipeline changes output.
_SIGNATURE_VERSION = 2
# Progress callback granularity (frames). Fine enough for a smooth %, coarse
# enough not to flood the websocket.
_PROGRESS_EVERY_FRAMES = 15


class UpscaleError(RuntimeError):
    """Upscaleが無効・未導入・model読み込み失敗・処理失敗のときに送出する。"""


_model = None
_model_key = None
_model_lock = threading.Lock()
# One video at a time: concurrent inference on the same GPU contends for VRAM
# (risking OOM) and only slows both runs down.
_upscale_lock = threading.Lock()


def upscale_available() -> bool:
    """torch と spandrel が利用可能か（実importせず存在のみ確認）。実importはCUDA関連の
    ネイティブlib読み込みで数秒かかるため、status確認では find_spec で存在だけ調べる。"""
    import importlib.util

    return (
        importlib.util.find_spec("torch") is not None
        and importlib.util.find_spec("spandrel") is not None
    )

def _model_file() -> Optional[Path]:
    """Configured weights file, relative paths resolved against the project root
    (the server may be launched from another working directory)."""
    raw = get_upscale_model_path()
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def upscale_status() -> dict:
    available = upscale_available()
    model = _model_file()
    return {
        "enabled": get_upscale_enabled(),
        "available": available,
        "configured": bool(
            get_upscale_enabled() and available and model is not None and model.is_file()
        ),
        "model": model.name if model is not None else "",
        "device": get_upscale_device(),
    }


def upscale_input_path(src: Path) -> Path:
    """The file the Up出力 would upscale right now: the burned-in overlay output when
    one exists (so comments/gifts are upscaled along with the footage), else the raw
    recording."""
    overlay = overlay_paths(Path(src))[0]
    return overlay if overlay.is_file() else Path(src)


def upscale_output_path(input_path: Path) -> Path:
    """User-facing upscaled mp4, next to its input in the recordings root."""
    input_path = Path(input_path)
    return input_path.parent / (input_path.stem + UPSCALE_SUFFIX)


def upscale_done(src: Path) -> bool:
    """True when an upscaled output already exists for the recording's current input
    (like the burn-in badge, the file on disk is the source of truth)."""
    try:
        return upscale_output_path(upscale_input_path(src)).is_file()
    except OSError:
        return False


def upscale_artifact_paths(src: Path) -> list:
    """Every upscale artifact of a recording, over both possible inputs (raw source and
    the overlay variants). Regenerable from the input, so the retention sweep may drop
    them; enumerated here so the reported reclaimable bytes and what cleanup removes
    stay the same set."""
    src = Path(src)
    paths = []
    for input_path in (src, overlay_paths(src)[0], overlay_paths_b(src)[0]):
        paths.extend((
            upscale_output_path(input_path),
            sidecar_path(input_path, UPSCALE_META_SUFFIX),
            sidecar_path(input_path, UPSCALE_LOG_SUFFIX),
        ))
    return paths


def cleanup_upscale_files(src: Path) -> None:
    """Remove upscaled outputs and their cache metas for a recording (called on
    delete). Covers both possible inputs (raw source and overlay variants)."""
    src = Path(src)
    for path in upscale_artifact_paths(src):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "AI高画質化の生成物 %s を削除できませんでした", path.name,
                extra={"event": "upscale.artifact_removal_failed",
                       "ctx": {"stem": src.stem, "path": str(path)}},
                exc_info=True,
            )


def _resolve_device() -> str:
    device = get_upscale_device()
    if device != "auto":
        return device
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _get_model():
    """Load (and cache) the configured super-resolution model for the video Up出力
    feature. Gated on TICTOK_UPSCALE_ENABLED. Returns (descriptor, device, half).
    Raises UpscaleError with an actionable message."""
    if not get_upscale_enabled():
        raise UpscaleError("Upscaleが無効です（TICTOK_UPSCALE_ENABLED=1 を設定してください）。")
    return load_image_model()


def load_image_model():
    """Load (and cache) the configured super-resolution model regardless of the
    video Up出力 enable flag. Returns (descriptor, device, half). Shared by the
    video Up出力 (gated on get_upscale_enabled via _get_model) and avatar upscaling
    (gated on its own overlay setting); both need only TICTOK_UPSCALE_MODEL_PATH and
    torch/spandrel. Raises UpscaleError with an actionable message."""
    try:
        import torch
        from spandrel import ImageModelDescriptor, ModelLoader
    except ImportError as exc:
        raise UpscaleError(
            "torch / spandrel が未インストールです（pip install torch spandrel）。"
        ) from exc
    model_file = _model_file()
    if model_file is None:
        raise UpscaleError("Upscale modelが未設定です（TICTOK_UPSCALE_MODEL_PATH を設定してください）。")
    if not model_file.is_file():
        raise UpscaleError(f"Upscale model fileが見つかりません: {model_file}")
    model_path = str(model_file)
    device = _resolve_device()
    compute = get_upscale_compute_type()
    key = (model_path, device, compute)
    global _model, _model_key
    with _model_lock:
        if _model is None or _model_key != key:
            started = time.monotonic()
            logger.info(
                "AI高画質化のmodelを読み込みます: %s device=%s compute=%s",
                model_path, device, compute,
                extra={"event": "upscale.model_load_started",
                       "ctx": {"path": model_path, "device": device, "compute": compute,
                               "size_bytes": model_file.stat().st_size}},
            )
            try:
                descriptor = ModelLoader().load_from_file(model_path)
            except Exception as exc:
                logger.error(
                    "AI高画質化のmodel %s を読み込めません", model_file.name,
                    extra={"event": "upscale.model_load_failed",
                           "ctx": {"path": model_path, "device": device, "compute": compute,
                                   "reason": "unreadable",
                                   "duration_ms": int((time.monotonic() - started) * 1000)}},
                    exc_info=True,
                )
                raise UpscaleError(f"Upscale modelの読み込みに失敗しました: {exc}") from exc
            if not isinstance(descriptor, ImageModelDescriptor):
                logger.error(
                    "設定されたAI高画質化のmodel %s は画像から画像へのmodelではありません",
                    model_file.name,
                    extra={"event": "upscale.model_load_failed",
                           "ctx": {"path": model_path, "reason": "wrong_model_kind",
                                   "descriptor": type(descriptor).__name__}},
                )
                raise UpscaleError("このmodelは画像→画像の超解像modelではありません。")
            if compute == "auto":
                half = device == "cuda" and descriptor.supports_half
            elif compute == "float16":
                if not descriptor.supports_half:
                    logger.error(
                        "設定されたAI高画質化のmodel %s はfloat16に対応していません",
                        model_file.name,
                        extra={"event": "upscale.model_load_failed",
                               "ctx": {"path": model_path, "reason": "half_unsupported",
                                       "compute": compute}},
                    )
                    raise UpscaleError("このmodelはfloat16に対応していません（TICTOK_UPSCALE_COMPUTE_TYPE=float32 にしてください）。")
                half = True
            else:
                half = False
            try:
                descriptor = descriptor.to(torch.device(device))
                if half:
                    descriptor.model.half()
                descriptor.model.eval()
            except Exception as exc:
                logger.error(
                    "AI高画質化のmodel %s を %s で初期化できません",
                    model_file.name, device,
                    extra={"event": "upscale.model_load_failed",
                           "ctx": {"path": model_path, "device": device, "half": half,
                                   "reason": "device_init",
                                   "duration_ms": int((time.monotonic() - started) * 1000)}},
                    exc_info=True,
                )
                raise UpscaleError(f"Upscale modelの初期化に失敗しました（device={device}）: {exc}") from exc
            _model = (descriptor, device, half)
            _model_key = key
            logger.info(
                "AI高画質化のmodelの準備ができました: %s x%s / %s（half=%s）",
                model_file.name, descriptor.scale, device, half,
                extra={"event": "upscale.model_loaded",
                       "ctx": {"path": model_path, "device": device, "half": half,
                               "compute": compute, "scale": int(descriptor.scale),
                               "duration_ms": int((time.monotonic() - started) * 1000)}},
            )
    return _model


def _probe_video(source) -> tuple[int, int, float, float, int]:
    """(width, height, fps, duration_seconds, 解像度の種類数) via ffprobe. Raises
    UpscaleError when the probe fails — frame geometry must be exact for raw-pipe decode.

    「exactでなければならない」の意味がstream headerの1組では足りない。混在解像度の録画で
    その1組(=開いた所の値)を採ると、Up出力は**録画が最初に映っていた解像度から**全編を
    引き伸ばすことになる。実測(ffmpeg 2026-06-10、160x120で開いて240x180へ切り替わる素材):
    raw pipeへ出てくるframeは60枚とも160x120で、切替後の本来大きい絵は一度160x120へ縮めて
    から渡されていた。低い側で開いた録画ほど、実在する画素を捨ててから拡大することになる。

    全編に現れる解像度の最大を枠に採り、種類数を呼び出し側へ返して、複数あるときは復号側で
    その枠へ揃えさせる(``_render``)。"""
    if not ffprobe_available():
        raise UpscaleError("ffprobeが見つかりません。高画質化にはffmpeg一式のinstallが必要です。")
    src = source.path
    args = [
        "ffprobe", "-v", "error", *source.input_args, "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-show_entries", "format=duration", "-of", "json", str(src),
    ]
    try:
        completed = subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=ffprobe.SHORT_TIMEOUT_SECONDS, check=True,
        )
        info = json.loads(completed.stdout.decode("utf-8", "replace"))
        stream = info["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
        fps = _parse_fps(stream.get("r_frame_rate", ""))
        duration = float(info.get("format", {}).get("duration") or 0)
    except (OSError, subprocess.SubprocessError, KeyError, IndexError, ValueError) as exc:
        stderr = getattr(exc, "stderr", None)
        logger.error(
            "AI高画質化のために %s を調べられません", src.name,
            extra={"event": "process.ffprobe_failed",
                   "ctx": {"stage": "upscale_probe", "stem": src.stem, "path": str(src),
                           **ffmpeg_ctx(
                               args,
                               getattr(exc, "returncode", None),
                               stderr_text=stderr.decode("utf-8", "replace") if stderr else None,
                           )}},
            exc_info=True,
        )
        raise UpscaleError(f"動画情報の取得に失敗しました: {exc}") from exc
    if width <= 0 or height <= 0 or not (0 < fps <= 240):
        logger.error(
            "%s の調査結果が使えない値です: %dx%d @ %s fps",
            src.name, width, height, fps,
            extra={"event": "upscale.probe_rejected",
                   "ctx": {"stem": src.stem, "path": str(src), "input_width": width,
                           "input_height": height, "fps": fps}},
        )
        raise UpscaleError(f"動画の解像度/フレームレートが不正です: {width}x{height} @ {fps}")
    found = hls_source.resolutions_sync(source)
    if found:
        width = max(w for w, _ in found)
        height = max(h for _, h in found)
    return width, height, fps, duration, len(found)


def _output_dimensions(src_w: int, src_h: int, scale: int) -> tuple[int, int]:
    """Final output size: model output, downscaled to the configured height cap when
    exceeded, both dimensions forced even (yuv420p requires it)."""
    out_w, out_h = src_w * scale, src_h * scale
    max_h = get_upscale_max_height()
    if out_h > max_h:
        out_w = int(round(out_w * max_h / out_h))
        out_h = max_h
    return out_w - (out_w % 2), out_h - (out_h % 2)


def _upscale_frame(descriptor, frame, tile: int, overlap: int, scale: int):
    """Run one BCHW frame through the model, tiled so VRAM stays bounded on large
    frames. Tiles are inferred with an overlap margin and only the core region is
    pasted, hiding boundary artifacts."""
    import torch

    if tile <= 0:
        return descriptor(frame)
    _, _, h, w = frame.shape
    out = torch.empty(
        (1, 3, h * scale, w * scale), dtype=frame.dtype, device=frame.device
    )
    for y0 in range(0, h, tile):
        y1 = min(y0 + tile, h)
        ys, ye = max(y0 - overlap, 0), min(y1 + overlap, h)
        for x0 in range(0, w, tile):
            x1 = min(x0 + tile, w)
            xs, xe = max(x0 - overlap, 0), min(x1 + overlap, w)
            patch = descriptor(frame[:, :, ys:ye, xs:xe])
            out[:, :, y0 * scale:y1 * scale, x0 * scale:x1 * scale] = patch[
                :, :,
                (y0 - ys) * scale:(y1 - ys) * scale,
                (x0 - xs) * scale:(x1 - xs) * scale,
            ]
    return out


def _signature(input_path: Path, model_path: str, encoder: str, quality: int,
               audio_normalize: Optional[dict] = None) -> str:
    # mp4が在るときの鍵は今までと同じ形のまま残す。Up出力は1本で数時間かかるので、
    # 鍵の形を変えると既にある出力が一斉に作り直しになる。mp4が無い(=.tsから読む)経路には
    # そもそも既存の出力が無いので、素材そのものの指紋を使う。
    if input_path.is_file():
        stat = input_path.stat()
        source_key = [stat.st_size, stat.st_mtime_ns]
    else:
        key = hls_source.fingerprint(input_path)
        source_key = [key["size"], key["mtime"], key["segments"]]
    mstat = Path(model_path).stat()
    payload = {
        "version": _SIGNATURE_VERSION,
        "input": source_key,
        "model": [model_path, mstat.st_size, mstat.st_mtime_ns],
        "encoder": encoder,
        "quality": quality,
        "max_height": get_upscale_max_height(),
        "tile": [get_upscale_tile(), get_upscale_tile_overlap()],
        "compute": get_upscale_compute_type(),
        # 音量正規化は出力の音声を変えるので、設定を変えたら作り直す。
        "audio_normalize": audio_normalize,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def ensure_upscaled(input_path: str, encoder: str, base_quality: int, on_progress=None,
                    audio_normalize: Optional[dict] = None) -> Path:
    """Upscale ``input_path`` to its ``.up.mp4`` sibling and return that path.
    Blocking (GPU bound) — call via a thread. Cached: an existing output whose meta
    signature matches the input/model/settings is returned as-is.

    ``encoder`` is a concrete ffmpeg encoder name (resolve via video_encoder_name
    beforehand); ``base_quality`` is the user's H.264-scale quality setting.
    ``on_progress(done_frames, total_frames)`` is invoked as frames complete."""
    if not ffmpeg_available():
        raise UpscaleError("ffmpegが見つかりません。高画質化にはffmpegのinstallが必要です。")
    src = Path(input_path)
    if not hls_source.available(src):
        raise UpscaleError("入力の動画fileが存在しません。")
    descriptor, device, half = _get_model()
    dst = upscale_output_path(src)
    meta = sidecar_path(src, UPSCALE_META_SUFFIX)
    quality = _mapped_quality(encoder, int(base_quality))
    signature = _signature(src, str(_model_file()), encoder, quality, audio_normalize)
    if dst.is_file() and meta.is_file():
        try:
            if meta.read_text(encoding="utf-8").strip() == signature:
                logger.debug(
                    "%s のAI高画質化はcacheを再利用します", src.name,
                    extra={"event": "upscale.reused",
                           "ctx": {"stem": src.stem, "path": str(dst),
                                   "size_bytes": dst.stat().st_size}},
                )
                return dst
        except OSError:
            logger.warning(
                "%s のAI高画質化のcache signatureを読めないため作り直します",
                src.name,
                extra={"event": "upscale.cache_read_failed",
                       "ctx": {"stem": src.stem, "path": str(meta)}},
                exc_info=True,
            )
    # An upscale writes an output several times the size of its input, on the same
    # volume. Preflight before the GPU work rather than after: a run that dies on a
    # full volume hours in has already thrown away the whole render.
    log_disk_preflight(
        "upscale.disk_checked", [src.parent, get_db_path(), get_log_dir()],
        stage="upscale", stem=src.stem,
    )
    started = time.monotonic()
    with gpu_slot("upscale"), _upscale_lock:
        # mp4が無い録画は.tsのHLSから読む。復号も音声の拾い直しも同じ入力を指す必要が
        # あるので、貸し出しはrender全体を包む(hls_source参照)。
        with hls_source.ffmpeg_source(src) as source:
            _render(src, source, dst, descriptor, device, half, encoder, quality,
                    on_progress, audio_normalize)
    sidecar_dir(src).mkdir(parents=True, exist_ok=True)
    meta.write_text(signature, encoding="utf-8")
    logger.info(
        "AI高画質化が完了しました: %s -> %s", src.name, dst.name,
        extra={"event": "upscale.completed",
               "ctx": {"stem": src.stem, "path": str(dst),
                       "size_bytes": dst.stat().st_size,
                       "input_bytes": src.stat().st_size if src.is_file() else None,
                       "encoder": encoder, "quality": quality, "device": device,
                       "duration_ms": int((time.monotonic() - started) * 1000)}},
    )
    return dst


def _render(src: Path, source, dst: Path, descriptor, device: str, half: bool,
            encoder: str, quality: int, on_progress,
            audio_normalize: Optional[dict] = None) -> None:
    """``src`` はこの録画のpath(log・sidecar・表示名の基準)、``source`` は実際にffmpegへ
    渡す入力。mp4が無い録画では後者だけが使い捨てのplaylistを指し、前者は変わらない —
    sidecarをplaylist側で解くと、jobごとに別の場所へ書かれる。"""
    import queue
    import numpy as np
    import torch

    # Every frame shares one geometry, so let cuDNN autotune its convolution
    # algorithms once for that shape instead of re-selecting per call.
    torch.backends.cudnn.benchmark = True

    scale = int(descriptor.scale)
    width, height, fps, duration, distinct = _probe_video(source)
    # 音声は入力1からそのまま拾う。正規化する場合だけ、loudnormが上げたrateを戻すため
    # sourceの実値を測る。
    audio_rate = audio_norm.probe_sample_rate(source.path) if audio_normalize else None
    out_w, out_h = _output_dimensions(width, height, scale)
    total_frames = max(1, int(round(duration * fps)))
    tile = get_upscale_tile()
    overlap = max(0, get_upscale_tile_overlap())
    # A tile no smaller than the frame is untiled inference; skip the paste loop.
    if tile > 0 and tile >= max(width, height):
        tile = 0
    dtype = torch.float16 if half else torch.float32
    fps_str = f"{fps:.6f}"
    frame_bytes = width * height * 3
    # 解像度が変わる録画は、何も指定しないとffmpegが**開いた所の寸法**でfilter graphを
    # 固定し、切替後のframeをそこへ縮めてから渡してくる(実測: 160x120で開くと240x180の
    # 区間も160x120で出てくる)。低い側で開いた録画は、実在する画素を捨ててから拡大される。
    # 上で採った枠を明示すれば、大きい側の絵はその大きさのまま model へ渡る。
    # 均一な入力(既定)には何も足さない — 従来と同じ1 filterのままにする。
    geometry = (_normalize_filter(width, height, get_normalize_scale_mode()) + ","
                if distinct > 1 else "")

    sidecar_dir(src).mkdir(parents=True, exist_ok=True)
    log_path = sidecar_path(src, UPSCALE_LOG_SUFFIX)
    tmp_dst = dst.with_suffix(".tmp.mp4")
    logger.info(
        "AI高画質化を開始しました: %s %dx%d -> %dx%d"
        "（model x%d, device=%s, half=%s, tile=%d, encoder=%s, 約%d frame）",
        src.name, width, height, out_w, out_h, scale, device, half, tile, encoder, total_frames,
        extra={"event": "upscale.started",
               "ctx": {"stem": src.stem, "path": str(src),
                       "input_width": width, "input_height": height,
                       "width": out_w, "height": out_h, "scale": scale,
                       "device": device, "half": half, "tile": tile,
                       "tile_overlap": overlap, "encoder": encoder, "quality": quality,
                       "fps": round(fps, 3), "frames": total_frames,
                       "source_seconds": round(duration, 3),
                       "stderr_path": str(log_path)}},
    )
    render_started = time.monotonic()
    gate = ProgressGate()
    decode = encode = None
    # Bound before the try so a failure raised between the two Popen calls can still be
    # logged with whatever command line was reached.
    decode_args: list = []
    encode_args: list = []
    done = 0
    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            # Decode to CFR raw RGB. TikTok recordings are VFR (stream-copied HLS);
            # raw frames on a pipe carry no timestamps, so the fps filter must
            # normalise timing here or the muxed audio would drift on long videos.
            # (Burned-in overlay inputs are already CFR — the filter is a no-op.)
            decode_args = [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                *source.input_args, "-i", str(source.path),
                "-map", "0:v:0", "-vf", f"{geometry}fps={fps_str}",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
            ]
            logger.debug(
                "%s のAI高画質化の復号processを起動します", src.name,
                extra={"event": "process.ffmpeg_started",
                       "ctx": {"stage": "upscale_decode", "stem": src.stem,
                               "stderr_path": str(log_path), **ffmpeg_ctx(decode_args)}},
            )
            decode = subprocess.Popen(
                decode_args,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=log_file,
            )
            # Frames are piped at the final output size: when the model overshoots the
            # height cap the downscale happens on the GPU (below), not in ffmpeg — a
            # 4x model on a 720p source would otherwise push ~44MB per raw frame
            # through the pipe only for ffmpeg to throw most of it away.
            encode_args = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{out_w}x{out_h}",
                "-framerate", fps_str, "-i", "pipe:0",
                *source.input_args, "-i", str(source.path),
                "-map", "0:v:0", "-map", "1:a?",
                # 音量正規化のときだけ音声を再encodeする。入力(焼き込み済み or 録画)は
                # VFR由来のtimestampを持つため、audio_norm側でaresample=async=1を前置する。
                *(audio_norm.encode_args(**audio_normalize, sample_rate=audio_rate)
                  if audio_normalize else ["-c:a", "copy"]),
                *_encoder_args(encoder, quality), "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", "-f", "mp4", str(tmp_dst),
            ]
            logger.debug(
                "%s のAI高画質化のencode processを起動します", src.name,
                extra={"event": "process.ffmpeg_started",
                       "ctx": {"stage": "upscale_encode", "stem": src.stem,
                               "stderr_path": str(log_path), **ffmpeg_ctx(encode_args)}},
            )
            encode = subprocess.Popen(
                encode_args,
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log_file,
            )
            # Overlap the three stages: a reader thread pulls raw frames off the
            # decoder pipe and a writer thread flushes upscaled frames to the encoder
            # pipe, bracketing this (single) GPU thread. While the model upscales frame
            # N the reader fetches N+1 and the writer drains N-1, so neither pipe idles
            # the GPU. The model stays on one thread (one CUDA context; _upscale_lock
            # already serialises videos). Queues are bounded so a fast stage cannot
            # outrun a slow one and grow memory without bound.
            frame_q: "queue.Queue" = queue.Queue(maxsize=8)
            out_q: "queue.Queue" = queue.Queue(maxsize=8)
            stop = threading.Event()
            reader_err: list = []
            writer_err: list = []

            def _reader():
                try:
                    while not stop.is_set():
                        buf = decode.stdout.read(frame_bytes)
                        if not buf:
                            break
                        if len(buf) != frame_bytes:
                            raise UpscaleError("decode中に不完全なframeを受信しました（decode失敗）。")
                        # frombuffer gives a read-only view over the pipe buffer; copy so
                        # the tensor owns writable memory (div_ below mutates it in place).
                        arr = np.frombuffer(buf, np.uint8).reshape(height, width, 3).copy()
                        while not stop.is_set():
                            try:
                                frame_q.put(arr, timeout=0.5)
                                break
                            except queue.Full:
                                continue
                except Exception as exc:
                    reader_err.append(exc)
                finally:
                    frame_q.put(None)

            def _writer():
                try:
                    while True:
                        item = out_q.get()
                        if item is None:
                            break
                        encode.stdin.write(item)
                except Exception as exc:
                    writer_err.append(exc)

            reader_t = threading.Thread(target=_reader, name="upscale-reader", daemon=True)
            writer_t = threading.Thread(target=_writer, name="upscale-writer", daemon=True)
            reader_t.start()
            writer_t.start()
            try:
                while True:
                    arr = frame_q.get()
                    if arr is None:
                        break
                    with torch.inference_mode():
                        frame = (
                            torch.from_numpy(arr).to(device)
                            .permute(2, 0, 1).unsqueeze(0).to(dtype).div_(255.0)
                        )
                        try:
                            out = _upscale_frame(descriptor, frame, tile, overlap, scale)
                        except torch.cuda.OutOfMemoryError as exc:
                            logger.error(
                                "%s のAI高画質化でGPUのmemoryが不足しました（frame %d）",
                                src.name, done + 1,
                                extra={"event": "upscale.memory_exhausted",
                                       "ctx": {"stem": src.stem, "frames_done": done,
                                               "frames": total_frames, "tile": tile,
                                               "tile_overlap": overlap, "half": half,
                                               "width": out_w, "height": out_h,
                                               "duration_ms": int((time.monotonic() - render_started) * 1000)}},
                                exc_info=True,
                            )
                            raise UpscaleError(
                                "GPUメモリが不足しました（TICTOK_UPSCALE_TILE をより小さく設定してください）。"
                            ) from exc
                        if out.shape[-2:] != (out_h, out_w):
                            # Height-cap (or odd-dimension) downscale on the GPU. bicubic
                            # +antialias needs float32 — fp16 antialias is unsupported.
                            out = torch.nn.functional.interpolate(
                                out.float(), size=(out_h, out_w), mode="bicubic", antialias=True
                            )
                        out_bytes = (
                            out.squeeze(0).permute(1, 2, 0)
                            .clamp_(0.0, 1.0).mul_(255.0).round_()
                            .to(torch.uint8).cpu().numpy().tobytes()
                        )
                    # Don't block forever if the writer has died (e.g. the encoder pipe
                    # broke): once the bounded queue fills against a dead writer, surface
                    # its error instead of deadlocking the GPU thread.
                    while True:
                        try:
                            out_q.put(out_bytes, timeout=0.5)
                            break
                        except queue.Full:
                            if not writer_t.is_alive():
                                raise (writer_err[0] if writer_err else
                                       UpscaleError("encodeへの書き込みが中断されました。")) from None
                    done += 1
                    # cancelはframe単位でしか効かない(1 frameの推論は中断できない)。ここを
                    # 抜けるとfinallyがdecode/encodeをkillし、tmp_dstも消える。
                    cancel.check_cancelled()
                    if on_progress and (done % _PROGRESS_EVERY_FRAMES == 0 or done >= total_frames):
                        on_progress(done, max(total_frames, done))
                    percent = 100.0 * done / max(total_frames, done)
                    if gate.due(percent):
                        elapsed = time.monotonic() - render_started
                        rate = done / elapsed if elapsed > 0 else 0.0
                        remaining = max(0, max(total_frames, done) - done)
                        logger.info(
                            "%s をAI高画質化中: %d/%d frame（%.1f%%）%.2f fps",
                            src.name, done, max(total_frames, done), percent, rate,
                            extra={"event": "upscale.progress_reported",
                                   "ctx": {"stem": src.stem, "frames_done": done,
                                           "frames": max(total_frames, done),
                                           "percent": round(percent, 2),
                                           "frames_per_second": round(rate, 3),
                                           "eta_seconds": round(remaining / rate, 1) if rate > 0 else None,
                                           "duration_ms": int(elapsed * 1000)}},
                        )
            finally:
                # Stop and unblock the helper threads whatever happens: signal stop,
                # drain the input queue so a blocked reader.put() returns, then send the
                # writer its end sentinel after every produced frame is already enqueued.
                stop.set()
                try:
                    while True:
                        frame_q.get_nowait()
                except queue.Empty:
                    pass
                while writer_t.is_alive():
                    try:
                        out_q.put(None, timeout=0.5)
                        break
                    except queue.Full:
                        continue
                writer_t.join(timeout=30)
                reader_t.join(timeout=30)
            if reader_err:
                raise reader_err[0]
            if writer_err:
                raise writer_err[0]
            encode.stdin.close()
            decode_rc = decode.wait()
            encode_rc = encode.wait()
        if decode_rc != 0:
            logger.error(
                "%s のAI高画質化の復号processが %s で終了しました（frame %d 件の処理後）",
                src.name, decode_rc, done,
                extra={"event": "process.ffmpeg_failed",
                       "ctx": {"stage": "upscale_decode", "stem": src.stem,
                               "frames_done": done, "frames": total_frames,
                               **ffmpeg_ctx(decode_args, decode_rc, log_path)}},
            )
            raise UpscaleError(f"動画のdecodeに失敗しました（詳細: {log_path.name}）。")
        if encode_rc != 0 or not tmp_dst.is_file():
            logger.error(
                "%s のAI高画質化のencode processが %s で終了しました（frame %d 件の処理後）",
                src.name, encode_rc, done,
                extra={"event": "process.ffmpeg_failed",
                       "ctx": {"stage": "upscale_encode", "stem": src.stem,
                               "frames_done": done, "frames": total_frames,
                               "size_bytes": tmp_dst.stat().st_size if tmp_dst.is_file() else 0,
                               **ffmpeg_ctx(encode_args, encode_rc, log_path)}},
            )
            raise UpscaleError(f"動画のencodeに失敗しました（詳細: {log_path.name}）。")
        if done == 0:
            logger.error(
                "%s のAI高画質化の復号processがframeを1枚も出しませんでした", src.name,
                extra={"event": "upscale.no_frames_decoded",
                       "ctx": {"stem": src.stem, "frames": total_frames,
                               **ffmpeg_ctx(decode_args, decode_rc, log_path)}},
            )
            raise UpscaleError("動画からframeを取得できませんでした。")
        tmp_dst.replace(dst)
        if on_progress:
            on_progress(total_frames, total_frames)
        elapsed = time.monotonic() - render_started
        logger.info(
            "AI高画質化の出力を書き出しました: %s（frame %d 件）", dst.name, done,
            extra={"event": "upscale.rendered",
                   "ctx": {"stem": src.stem, "path": str(dst), "frames_done": done,
                           "frames": total_frames, "size_bytes": dst.stat().st_size,
                           "frames_per_second": round(done / elapsed, 3) if elapsed > 0 else None,
                           "duration_ms": int(elapsed * 1000)}},
        )
    except BrokenPipeError as exc:
        logger.error(
            "%s のAI高画質化のencode pipeが切れました（frame %d 件の処理後）", src.name, done,
            extra={"event": "process.ffmpeg_failed",
                   "ctx": {"stage": "upscale_encode", "stem": src.stem,
                           "frames_done": done, "frames": total_frames,
                           **ffmpeg_ctx(encode_args, encode.returncode if encode else None,
                                        log_path)}},
            exc_info=True,
        )
        raise UpscaleError(f"encodeが中断されました（詳細: {log_path.name}）。") from exc
    finally:
        for proc in (decode, encode):
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait()
        tmp_dst.unlink(missing_ok=True)
