"""On-demand fetch of the comment-overlay fonts.

The recording burn-in draws comments through Pillow so colour emoji render like a
phone (libass only produces monochrome glyphs). Pillow has no automatic font
fallback, so a CJK+Latin text font, a colour-emoji font and a few decorative
fallbacks must be present on disk under ``assets/fonts`` -- see ``video_overlay``.
Together they are ~30 MB of binary, too large to keep in the repository, so they
are fetched on first use from their upstream Open Font License sources and pinned
by SHA-256 (upstream content drift fails verification rather than silently
shipping a different build). A fetch failure is not fatal: the caller falls back
to the monochrome ASS comment path, so only emoji colour is lost.

Windows/Linux: standard library only (urllib, hashlib)."""

from __future__ import annotations

import hashlib
import logging
import threading
import urllib.request
from pathlib import Path
from typing import NamedTuple

from tictok.paths import PROJECT_ROOT

logger = logging.getLogger("tictok.fonts")

FONT_DIR = PROJECT_ROOT / "assets" / "fonts"


class _Font(NamedTuple):
    url: str
    sha256: str


# filename -> upstream source, pinned by SHA-256. All SIL OFL 1.1; see
# assets/fonts/README.md for the per-font rationale and assets/fonts/OFL.txt for
# the licence. Each URL is the font's canonical upstream repository; the digest
# guards against that upstream serving a different build later.
FONT_MANIFEST: dict[str, _Font] = {
    "NotoSansCJKjp-Regular.otf": _Font(
        "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/Japanese/NotoSansCJKjp-Regular.otf",
        "68a3fc98800b2a27b371f2fb79991daf3633bd89309d4ffaa6946fd587f375b5",
    ),
    "NotoColorEmoji.ttf": _Font(
        "https://raw.githubusercontent.com/googlefonts/noto-emoji/main/fonts/NotoColorEmoji.ttf",
        "72a635cb3d2f3524c51620cdde406b217204e8a6a06c6a096ff8ed4b5fd6e27b",
    ),
    "NotoSans-VF.ttf": _Font(
        "https://raw.githubusercontent.com/google/fonts/main/ofl/notosans/NotoSans%5Bwdth,wght%5D.ttf",
        "bfb7bb691513f12e734dc346c03a03f784912432d7e3fa8e56efcf906fe86b3d",
    ),
    "NotoSansGeorgian-VF.ttf": _Font(
        "https://raw.githubusercontent.com/google/fonts/main/ofl/notosansgeorgian/NotoSansGeorgian%5Bwdth,wght%5D.ttf",
        "dc591156f36842d38996c4a7a17fee9bb58e45da3e2cac7a31b7d33de700adb9",
    ),
    "NotoSansMath-Regular.ttf": _Font(
        "https://raw.githubusercontent.com/google/fonts/main/ofl/notosansmath/NotoSansMath-Regular.ttf",
        "3f495fe933c06786e4d5f6d86b8ee70b6753a68ee3b9d87528726de0f6e2c47d",
    ),
}

_DOWNLOAD_TIMEOUT = 60
_lock = threading.Lock()
_ensured = False


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _present(name: str, spec: _Font) -> bool:
    path = FONT_DIR / name
    return path.is_file() and _sha256(path) == spec.sha256


def _fetch(name: str, spec: _Font) -> None:
    """Download one font, verifying its SHA-256 before it is put in place. The
    bytes are written to a temporary sibling and renamed, so an interrupted or
    corrupted download never leaves a half-written file that later reads as
    present."""
    req = urllib.request.Request(spec.url, headers={"User-Agent": "TicTok-font-fetch"})
    with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp:
        data = resp.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != spec.sha256:
        raise RuntimeError(
            f"font {name} sha256 mismatch: got {digest}, expected {spec.sha256}"
        )
    tmp = FONT_DIR / f"{name}.part"
    tmp.write_bytes(data)
    tmp.replace(FONT_DIR / name)


def ensure_fonts(force: bool = False) -> None:
    """Make sure every comment-overlay font is present and matches its pinned
    digest, downloading any that are missing or stale. Raises on a network or
    verification failure; ``_make_comment_shaper`` treats that as "no colour-emoji
    layer" and renders comments through the monochrome ASS path instead.

    Thread-safe and idempotent: after one success the per-file check is skipped,
    so it is cheap to call before every render."""
    global _ensured
    if _ensured and not force:
        return
    with _lock:
        if _ensured and not force:
            return
        FONT_DIR.mkdir(parents=True, exist_ok=True)
        missing = {n: s for n, s in FONT_MANIFEST.items() if force or not _present(n, s)}
        if missing:
            logger.info("fetching %d comment-overlay font(s) to %s", len(missing), FONT_DIR)
            for name, spec in missing.items():
                _fetch(name, spec)
                logger.info("fetched font %s", name)
        _ensured = True
