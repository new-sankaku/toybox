"""Comment/gift userのavatarをAI超解像で高精細化する（焼き込み用）。

TikTok webcast eventのuser avatarは72x72の強圧縮thumbしか来ず（medium/largerは常に
空、署名URLはサイズ書き換えで403になり取得不可＝検証済）、焼き込み時にdiscへ拡大すると
ぼやける。この上限を後処理で補うため、有効時は各User固有のavatarをsuper-resolution model
へ一度だけ通し、結果をUser単位でcacheする。焼き込みはその高精細版をcircle discへ合成する。

modelとtiled inferenceはrecord.upscale（Up出力）と共有する。torch/spandrelはoptionalで、
未導入・model未設定・読み込み失敗のときはNoneを返し（logに記録）、呼び出し側は元の72px
avatarで焼き込む。あくまで任意の高精細化なので、modelが無い場合は画質が下がるだけで
renderは失敗させない。Windows/Linux双方で動作する。
"""

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

from tictok.core.config import get_upscale_compute_type, get_upscale_model_path
from tictok.core.gpu import gpu_slot
from tictok.record.upscale import (
    UpscaleError,
    _model_file,
    _upscale_frame,
    load_image_model,
    upscale_available,
)

logger = logging.getLogger("tictok.avatar_upscale")

# Cache-signature schema version; bump when the produced image changes meaning.
_SIGNATURE_VERSION = 1

# One inference at a time: the super-resolution model runs on a single CUDA context
# (shared with the video Up出力), and avatars are resolved sequentially inside the
# comment-layer render thread anyway. The persistent per-user cache means each unique
# avatar is upscaled once ever, so this lock is virtually always uncontended.
_lock = threading.Lock()
# Once the model cannot be loaded (packages/model absent), stop retrying for the rest
# of the process so a burn-in with thousands of avatars does not attempt (and log) a
# failed load per avatar. Cleared only by a restart (after the model is configured).
_model_unavailable = False


def avatars_upscalable() -> bool:
    """True when avatar upscaling could run: torch/spandrel are importable and a
    super-resolution model path is configured. A cheap pre-check for the burn-in;
    deep failures (bad model file, device error) surface in ``ensure_avatar_upscaled``."""
    return upscale_available() and bool(get_upscale_model_path())


def _signature(src_img: Path, model_file: Path) -> str:
    """Cache key for an upscaled avatar: identifies the source image *and* the model
    and precision, so a changed model/compute OR a replaced source avatar reprocesses
    instead of serving a stale image. The source stat matters because the pool now
    replaces a user's ``.img`` in place when a higher-resolution rendition or a changed
    avatar arrives; without it, the upscaled cache (keyed only by model) would keep
    serving the super-resolved *old* avatar."""
    mstat = model_file.stat()
    sstat = src_img.stat()
    payload = {
        "version": _SIGNATURE_VERSION,
        "model": [str(model_file), mstat.st_size, mstat.st_mtime_ns],
        "src": [sstat.st_size, sstat.st_mtime_ns],
        "compute": get_upscale_compute_type(),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _upscaled_path(src_img: Path, sig: str) -> Path:
    # The signature is embedded in the filename so existence is a cache hit and a
    # model change simply orphans the old file (removed opportunistically below),
    # avoiding a second sidecar file per avatar in a directory of tens of thousands.
    return src_img.with_name(f"{src_img.stem}.up-{sig}.png")


def ensure_avatar_upscaled(src_img: Path) -> Optional[Path]:
    """Return a path to an AI-upscaled RGB PNG of ``src_img`` (the cached 72px avatar),
    generating and caching it next to the source on first use. Returns None (logged)
    when upscaling is unavailable or fails, so the caller composites the raw avatar.

    Blocking (GPU/CPU inference) — call from a worker thread, never the event loop.
    The result is cached by model signature, so a repeated avatar is a disk hit."""
    global _model_unavailable
    if _model_unavailable:
        return None
    src_img = Path(src_img)
    model_file = _model_file()
    if model_file is None or not model_file.is_file():
        return None
    try:
        sig = _signature(src_img, model_file)
    except OSError:
        # Source avatar vanished between resolution and here — nothing to upscale.
        return None
    dst = _upscaled_path(src_img, sig)
    try:
        if dst.is_file() and dst.stat().st_size > 0:
            return dst
    except OSError:
        pass

    # Nested inside the burn-in's slot when called from the comment-layer render (a no-op
    # re-entry there); a genuine wait only happens when avatars are resolved outside one.
    with gpu_slot("avatar_upscale"), _lock:
        # Another thread may have produced it while we waited for the lock.
        try:
            if dst.is_file() and dst.stat().st_size > 0:
                return dst
        except OSError:
            pass
        try:
            descriptor, device, half = load_image_model()
        except UpscaleError:
            _model_unavailable = True
            logger.warning(
                "avatar upscale requested but the super-resolution model is unavailable; "
                "burning in raw 72px avatars instead",
                extra={"event": "upscale.avatar_model_load_failed",
                       "ctx": {"path": str(model_file), "suppressed_for_process": True}},
                exc_info=True,
            )
            return None
        started = time.monotonic()
        try:
            _render_avatar(descriptor, device, half, src_img, dst)
        except Exception:
            logger.warning(
                "avatar upscale failed for %s; using the raw avatar", src_img.name,
                extra={"event": "upscale.avatar_failed",
                       "ctx": {"path": str(src_img), "device": device, "half": half}},
                exc_info=True,
            )
            dst.unlink(missing_ok=True)
            return None
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "upscaled avatar %s", src_img.name,
                extra={"event": "upscale.avatar_rendered",
                       "ctx": {"path": str(dst),
                               "size_bytes": dst.stat().st_size if dst.is_file() else 0,
                               "duration_ms": int((time.monotonic() - started) * 1000)}},
            )
    _prune_stale(src_img, keep=dst)
    return dst


def _render_avatar(descriptor, device: str, half: bool, src_img: Path, dst: Path) -> None:
    """Upscale one avatar image through the model and write it as an RGB PNG. The
    avatar is tiny (72px) so inference is untiled; the circular alpha mask is applied
    later by the burn-in, so only RGB is produced here."""
    import numpy as np
    import torch
    from PIL import Image

    with Image.open(src_img) as im:
        arr = np.asarray(im.convert("RGB"), dtype=np.uint8)
    dtype = torch.float16 if half else torch.float32
    scale = int(descriptor.scale)
    with torch.inference_mode():
        frame = (
            torch.from_numpy(arr).to(device)
            .permute(2, 0, 1).unsqueeze(0).to(dtype).div_(255.0)
        )
        out = _upscale_frame(descriptor, frame, tile=0, overlap=0, scale=scale)
        out_arr = (
            out.squeeze(0).permute(1, 2, 0)
            .clamp_(0.0, 1.0).mul_(255.0).round_()
            .to(torch.uint8).cpu().numpy()
        )
    tmp = dst.with_suffix(".tmp.png")
    Image.fromarray(out_arr, "RGB").save(tmp)
    tmp.replace(dst)


def _prune_stale(src_img: Path, keep: Path) -> None:
    """Remove upscaled avatars for this user left by a previous model/precision (the
    signature in their filename no longer matches), keeping only the current one."""
    try:
        for old in src_img.parent.glob(f"{src_img.stem}.up-*.png"):
            if old != keep:
                old.unlink(missing_ok=True)
    except OSError:
        logger.warning(
            "failed to prune stale upscaled avatars for %s", src_img.name,
            extra={"event": "upscale.avatar_prune_failed", "ctx": {"path": str(src_img)}},
            exc_info=True,
        )
