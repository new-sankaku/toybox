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
from pathlib import Path
from typing import Optional

from tictok.core.config import (
    get_upscale_compute_type,
    get_upscale_device,
    get_upscale_enabled,
    get_upscale_max_height,
    get_upscale_model_path,
    get_upscale_tile,
    get_upscale_tile_overlap,
)
from tictok.paths import PROJECT_ROOT
from tictok.record.recorder import ffmpeg_available, ffprobe_available, sidecar_dir, sidecar_path
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


def cleanup_upscale_files(src: Path) -> None:
    """Remove upscaled outputs and their cache metas for a recording (called on
    delete). Covers both possible inputs (raw source and overlay variants)."""
    src = Path(src)
    inputs = [src, overlay_paths(src)[0], overlay_paths_b(src)[0]]
    for input_path in inputs:
        for path in (
            upscale_output_path(input_path),
            sidecar_path(input_path, UPSCALE_META_SUFFIX),
            sidecar_path(input_path, UPSCALE_LOG_SUFFIX),
        ):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning("failed to remove upscale artifact %s", path, exc_info=True)


def _resolve_device() -> str:
    device = get_upscale_device()
    if device != "auto":
        return device
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _get_model():
    """Load (and cache) the configured super-resolution model. Returns
    (descriptor, device, half). Raises UpscaleError with an actionable message."""
    if not get_upscale_enabled():
        raise UpscaleError("Upscaleが無効です（TICTOK_UPSCALE_ENABLED=1 を設定してください）。")
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
            logger.info("loading upscale model: %s device=%s compute=%s", model_path, device, compute)
            try:
                descriptor = ModelLoader().load_from_file(model_path)
            except Exception as exc:
                raise UpscaleError(f"Upscale modelの読み込みに失敗しました: {exc}") from exc
            if not isinstance(descriptor, ImageModelDescriptor):
                raise UpscaleError("このmodelは画像→画像の超解像modelではありません。")
            if compute == "auto":
                half = device == "cuda" and descriptor.supports_half
            elif compute == "float16":
                if not descriptor.supports_half:
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
                raise UpscaleError(f"Upscale modelの初期化に失敗しました（device={device}）: {exc}") from exc
            _model = (descriptor, device, half)
            _model_key = key
    return _model


def _probe_video(src: Path) -> tuple[int, int, float, float]:
    """(width, height, fps, duration_seconds) via ffprobe. Raises UpscaleError when
    the probe fails — frame geometry must be exact for raw-pipe decode."""
    if not ffprobe_available():
        raise UpscaleError("ffprobeが見つかりません。高画質化にはffmpeg一式のinstallが必要です。")
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate",
             "-show_entries", "format=duration", "-of", "json", str(src)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60, check=True,
        ).stdout
        info = json.loads(out.decode("utf-8", "replace"))
        stream = info["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
        fps = _parse_fps(stream.get("r_frame_rate", ""))
        duration = float(info.get("format", {}).get("duration") or 0)
    except (OSError, subprocess.SubprocessError, KeyError, IndexError, ValueError) as exc:
        raise UpscaleError(f"動画情報の取得に失敗しました: {exc}") from exc
    if width <= 0 or height <= 0 or not (0 < fps <= 240):
        raise UpscaleError(f"動画の解像度/フレームレートが不正です: {width}x{height} @ {fps}")
    return width, height, fps, duration


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


def _signature(input_path: Path, model_path: str, encoder: str, quality: int) -> str:
    stat = input_path.stat()
    mstat = Path(model_path).stat()
    payload = {
        "version": _SIGNATURE_VERSION,
        "input": [stat.st_size, stat.st_mtime_ns],
        "model": [model_path, mstat.st_size, mstat.st_mtime_ns],
        "encoder": encoder,
        "quality": quality,
        "max_height": get_upscale_max_height(),
        "tile": [get_upscale_tile(), get_upscale_tile_overlap()],
        "compute": get_upscale_compute_type(),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def ensure_upscaled(input_path: str, encoder: str, base_quality: int, on_progress=None) -> Path:
    """Upscale ``input_path`` to its ``.up.mp4`` sibling and return that path.
    Blocking (GPU bound) — call via a thread. Cached: an existing output whose meta
    signature matches the input/model/settings is returned as-is.

    ``encoder`` is a concrete ffmpeg encoder name (resolve via video_encoder_name
    beforehand); ``base_quality`` is the user's H.264-scale quality setting.
    ``on_progress(done_frames, total_frames)`` is invoked as frames complete."""
    if not ffmpeg_available():
        raise UpscaleError("ffmpegが見つかりません。高画質化にはffmpegのinstallが必要です。")
    src = Path(input_path)
    if not src.is_file():
        raise UpscaleError("入力の動画fileが存在しません。")
    descriptor, device, half = _get_model()
    dst = upscale_output_path(src)
    meta = sidecar_path(src, UPSCALE_META_SUFFIX)
    quality = _mapped_quality(encoder, int(base_quality))
    signature = _signature(src, str(_model_file()), encoder, quality)
    if dst.is_file() and meta.is_file():
        try:
            if meta.read_text(encoding="utf-8").strip() == signature:
                return dst
        except OSError:
            pass
    with _upscale_lock:
        _render(src, dst, descriptor, device, half, encoder, quality, on_progress)
    sidecar_dir(src).mkdir(parents=True, exist_ok=True)
    meta.write_text(signature, encoding="utf-8")
    return dst


def _render(src: Path, dst: Path, descriptor, device: str, half: bool,
            encoder: str, quality: int, on_progress) -> None:
    import queue
    import numpy as np
    import torch

    # Every frame shares one geometry, so let cuDNN autotune its convolution
    # algorithms once for that shape instead of re-selecting per call.
    torch.backends.cudnn.benchmark = True

    scale = int(descriptor.scale)
    width, height, fps, duration = _probe_video(src)
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

    sidecar_dir(src).mkdir(parents=True, exist_ok=True)
    log_path = sidecar_path(src, UPSCALE_LOG_SUFFIX)
    tmp_dst = dst.with_suffix(".tmp.mp4")
    logger.info(
        "upscale start: %s %dx%d -> %dx%d (model x%d, device=%s, half=%s, tile=%d, encoder=%s, ~%d frames)",
        src.name, width, height, out_w, out_h, scale, device, half, tile, encoder, total_frames,
    )
    decode = encode = None
    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            # Decode to CFR raw RGB. TikTok recordings are VFR (stream-copied HLS);
            # raw frames on a pipe carry no timestamps, so the fps filter must
            # normalise timing here or the muxed audio would drift on long videos.
            # (Burned-in overlay inputs are already CFR — the filter is a no-op.)
            decode = subprocess.Popen(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(src),
                 "-map", "0:v:0", "-vf", f"fps={fps_str}",
                 "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=log_file,
            )
            # Frames are piped at the final output size: when the model overshoots the
            # height cap the downscale happens on the GPU (below), not in ffmpeg — a
            # 4x model on a 720p source would otherwise push ~44MB per raw frame
            # through the pipe only for ffmpeg to throw most of it away.
            encode = subprocess.Popen(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{out_w}x{out_h}",
                 "-framerate", fps_str, "-i", "pipe:0",
                 "-i", str(src),
                 "-map", "0:v:0", "-map", "1:a?", "-c:a", "copy",
                 *_encoder_args(encoder, quality), "-pix_fmt", "yuv420p",
                 "-movflags", "+faststart", "-f", "mp4", str(tmp_dst)],
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
            done = 0
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
                    if on_progress and (done % _PROGRESS_EVERY_FRAMES == 0 or done >= total_frames):
                        on_progress(done, max(total_frames, done))
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
            raise UpscaleError(f"動画のdecodeに失敗しました（詳細: {log_path.name}）。")
        if encode_rc != 0 or not tmp_dst.is_file():
            raise UpscaleError(f"動画のencodeに失敗しました（詳細: {log_path.name}）。")
        if done == 0:
            raise UpscaleError("動画からframeを取得できませんでした。")
        tmp_dst.replace(dst)
        if on_progress:
            on_progress(total_frames, total_frames)
        logger.info("upscale rendered: %s (%d frames)", dst.name, done)
    except BrokenPipeError as exc:
        raise UpscaleError(f"encodeが中断されました（詳細: {log_path.name}）。") from exc
    finally:
        for proc in (decode, encode):
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait()
        tmp_dst.unlink(missing_ok=True)
