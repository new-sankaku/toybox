"""録画mp4へCommentとGift演出を焼き込む(burn-in)処理。

収集済みのComment/Gift eventをTikTok風の表示へ変換し、ffmpegで動画へ合成する。
Commentは画面左下に下から積み上がり、新着が下・古いものが上へscrollして消える
feed形式で描画する。GiftはGift Icon画像を左側へslide-inさせる通知Cardとして描画し、
送り主・Gift名・comboを併記する。Comment/Card文字はASS字幕、Gift Iconはffmpegの
overlay filterで同一passに合成する。生成物は設定値と元fileのhashでcacheし、同条件の
再Downloadでは再Encodeを省く。Windows/Linux双方で動作する。
"""

import asyncio
import bisect
import hashlib
import json
import logging
import math
import subprocess
import tempfile
import unicodedata
import urllib.request
from pathlib import Path
from typing import Awaitable, Callable, Optional

# 焼き込み進捗を0-100%で受け取るcallback。serverはこれをWSへ中継する。
ProgressCb = Callable[[int], Awaitable[None]]

from tictok.paths import PROJECT_ROOT
from tictok.media.avatar_pool import avatar_key
from tictok.record.recorder import (
    PTS_DISCONTINUITY_MIN_SECONDS,
    ffmpeg_available,
    ffprobe_available,
    is_pts_discontinuity,
    sidecar_dir,
    sidecar_path,
    timing_path,
)

logger = logging.getLogger("tictok.video_overlay")

# Font size in settings is authored against this reference height (a typical
# vertical video); the actual script size is scaled to the real video so burned
# text looks consistent regardless of the source resolution.
BASE_HEIGHT = 1280
DEFAULT_WIDTH = 720
DEFAULT_HEIGHT = 1280

# Burned-in overlays (comment text, colour emoji, gift icons, score bar) are
# rasterised at the output resolution, so a low-resolution source would burn
# low-resolution text. To keep text crisp regardless of source quality, the output
# is upscaled (aspect preserved, lanczos) to at least this height when the source is
# shorter; the source video content is upscaled along with it (softer, larger file —
# an accepted trade-off for legible text). Taller sources are left untouched.
OVERLAY_MIN_HEIGHT = 1280

# Coin count size is derived from the video height (not the comment font) so it
# stays legible even though comments use a small font: COIN_REF_PX pixels at the
# reference height, scaled to the real video. The gift icon size is a user
# setting (percent of video height) — see ``video_overlay_icon_percent``.
COIN_REF_PX = 30

# Upper bound on simultaneously-composited gift icons. Each gift instance adds
# one overlay to the ffmpeg filter graph; an unbounded graph on a long, gift-
# heavy recording would make ffmpeg slow and memory-hungry. When exceeded, the
# highest-diamond gifts are kept and the rest are logged as dropped (never
# silently truncated).
MAX_GIFT_OVERLAYS = 120
SLIDE_SECONDS = 0.3
# When a recording's duration is unknown, the final comments (with nothing after
# to push them off the feed) hold this many seconds past the last comment.
COMMENT_END_HOLD_SECONDS = 4

OVERLAY_SUFFIX = ".overlay.mp4"
ASS_SUFFIX = ".overlay.ass"
META_SUFFIX = ".overlay.meta"
# Legacy transient CFR-normalised copy of a VFR source. CFR normalisation is now
# folded into the burn-in filter graph (no intermediate file), but the suffix is kept
# so cleanup removes any such file orphaned by an older build's crashed render.
CFR_SUFFIX = ".cfr.mp4"
# Mode B (source-clock timing) burn-in, produced alongside Mode A for comparison
# when video_overlay_timing_compare is on. Same source mp4, comments/battle timed
# by TikTok create_time instead of consumer arrival.
OVERLAY_SUFFIX_B = ".overlay.b.mp4"
ASS_SUFFIX_B = ".overlay.b.ass"
META_SUFFIX_B = ".overlay.b.meta"
# Per-comment timing detail for offline investigation (arrival vs source offset).
TIMING_DEBUG_SUFFIX = ".timing.debug.json"
ICON_CACHE_DIR = "gift_icons"

# Settings that change the rendered output; the cache is invalidated when any
# of these (or the source file) change.
OVERLAY_KEYS = (
    "video_overlay_comments",
    "video_overlay_gifts",
    "video_overlay_score_bar",
    "video_overlay_score_bar_hold_seconds",
    "video_overlay_real_avatars",
    "video_overlay_font_size",
    "video_overlay_comment_delay_seconds",
    "video_overlay_gift_seconds",
    "video_overlay_gift_min_diamonds",
    "video_overlay_icon_percent",
    "video_overlay_quality",
    "video_overlay_codec",
)

_locks_guard = asyncio.Lock()
_locks: dict[str, asyncio.Lock] = {}


def overlay_settings(settings) -> dict:
    return {key: settings.get(key) for key in OVERLAY_KEYS}


def overlay_enabled(settings) -> bool:
    cfg = overlay_settings(settings)
    return (
        bool(cfg["video_overlay_comments"])
        or bool(cfg["video_overlay_gifts"])
        or bool(cfg["video_overlay_score_bar"])
    )


def overlay_paths(src: Path) -> tuple[Path, Path, Path]:
    """Return (mp4, ass, meta) paths for a source recording. The burned-in mp4 is
    the user-facing output and lives in the recordings root alongside its source;
    the ass/meta render artifacts stay under the per-recording .sidecars dir."""
    src = Path(src)
    return (
        src.parent / (src.stem + OVERLAY_SUFFIX),
        sidecar_path(src, ASS_SUFFIX),
        sidecar_path(src, META_SUFFIX),
    )


def overlay_paths_b(src: Path) -> tuple[Path, Path, Path]:
    """(mp4, ass, meta) paths for the Mode B (source-clock) burn-in variant."""
    src = Path(src)
    return (
        src.parent / (src.stem + OVERLAY_SUFFIX_B),
        sidecar_path(src, ASS_SUFFIX_B),
        sidecar_path(src, META_SUFFIX_B),
    )


def cleanup_overlay_files(src: Path) -> None:
    """Remove cached burn-in artifacts for a recording (called on delete)."""
    paths = list(overlay_paths(Path(src))) + list(overlay_paths_b(Path(src)))
    paths.append(sidecar_path(Path(src), TIMING_DEBUG_SUFFIX))
    # Transient CFR-normalised base (removed at the end of a render, but a crashed
    # render can orphan one).
    paths.append(sidecar_path(Path(src), CFR_SUFFIX))
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("failed to remove overlay artifact %s", path, exc_info=True)


async def _get_lock(key: str) -> asyncio.Lock:
    async with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _locks[key] = lock
        return lock


def _signature(src: Path, cfg: dict, timing: Optional[Path] = None, variant: str = "a") -> str:
    stat = src.stat()
    payload = {
        "version": 18,
        "variant": variant,
        "cfg": cfg,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    # The wall->media timing map changes comment placement, so a new/refreshed
    # sidecar must invalidate a cached burn-in built without (or before) it.
    if timing is not None and timing.is_file():
        tstat = timing.stat()
        payload["timing"] = [tstat.st_size, tstat.st_mtime_ns]
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _ass_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_cs = int(round(seconds * 100))
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: Optional[str]) -> str:
    if not text:
        return ""
    # Braces start ASS override blocks and backslashes start escapes; neutralize
    # them so user text cannot break the dialogue line.
    out = (
        text.replace("\\", "/")
        .replace("{", "(")
        .replace("}", ")")
        .replace("\r", " ")
        .replace("\n", " ")
    )
    return out.strip()


# Layout zones (fractions of the video). Gifts occupy the upper-left band,
# comments the lower-left band; they never overlap. The comment band is the
# bottom ~33% of the height and the left 80% of the width.
GIFT_BAND_TOP = 0.05
COMMENT_BAND_TOP = 0.64
BAND_BOTTOM = 0.97
COMMENT_WIDTH_FRAC = 0.80

# Initial-letter avatar colours (ASS \1c = &HBBGGRR&). Real commenter avatars are
# signed CDN URLs that expire (403 after a while), so a username-initial disc —
# the app's own fallback style — is drawn instead; it needs no download and
# scrolls with the comment.
_AVATAR_COLORS = (
    "&H7C5CFF&", "&H4FA0D6&", "&H6CC87B&", "&HF59B5B&",
    "&HF07DC7&", "&HF2D06F&", "&HE88A8A&", "&H8AD0A0&",
)


def _comment_font(cfg: dict, height: int) -> int:
    """Comment font in pixels: the setting value scaled from the reference height
    to the real video so it looks consistent across resolutions."""
    return max(8, int(round(cfg["video_overlay_font_size"] * height / BASE_HEIGHT)))


def _icon_px(cfg: dict, height: int) -> int:
    """Gift icon size in pixels, computed dynamically from the video height and
    the user's ``video_overlay_icon_percent`` setting (percent of height)."""
    pct = cfg.get("video_overlay_icon_percent") or 0
    return max(8, int(round(height * pct / 100.0)))


# Font used by the burned-in comment/gift text. "Sans" is resolved by libass via
# the host's font config, so it maps to a different actual font (with different
# glyph advances) on Windows vs Linux. The wrap/truncate math below must match
# whatever libass really renders, so the per-glyph advance is measured from this
# same font once per process (``_font_metrics``) instead of being assumed.
COMMENT_FONT = "Sans"

# Em-advance per character class. ``wide`` is a full-width (CJK) glyph, ``narrow``
# an average Latin glyph. These nominal values are the last-resort defaults used
# only when the live calibration cannot run (logged); the real values come from
# measuring the rendered font.
NOMINAL_WIDE_EM = 1.0
NOMINAL_NARROW_EM = 0.55

# Calibration probe: render representative wide/narrow runs through libass and
# read the rendered pixel width to recover the font's true em-advances.
_CALIB_FS = 48
_CALIB_CJK = "あ"
_CALIB_ASCII = "abcdefghijklmnopqrstuvwxyz 0123456789 "

_font_em: Optional[tuple] = None  # (wide_em, narrow_em), measured once
_font_em_lock = asyncio.Lock()


def _measure_font_em_sync() -> Optional[tuple]:
    """Render two lengths each of a wide (CJK) and a narrow (Latin) run through
    libass and recover the per-glyph em-advance from the rendered pixel widths.

    Using two lengths and taking the *difference* of their right ink edges cancels
    the leading offset and the final glyph's side bearing, leaving exactly the
    advance of the added glyphs — so the result is the font's true advance, not an
    ink estimate. Returns (wide_em, narrow_em) or None if the probe cannot run."""
    try:
        from PIL import Image
    except ImportError:
        return None
    fs = _CALIB_FS
    cjk_n1, cjk_n2 = 8, 16
    asc1, asc2 = _CALIB_ASCII, _CALIB_ASCII * 2
    width = 64 + len(asc2) * fs  # 1em upper bound on advance; never clips
    height = 10 + 8 * fs
    ys = [10, 10 + 2 * fs, 10 + 4 * fs, 10 + 6 * fs]
    lines = [_CALIB_CJK * cjk_n1, _CALIB_CJK * cjk_n2, asc1, asc2]
    events = "".join(
        f"Dialogue: 0,0:00:00.00,0:00:01.00,Cal,,0,0,0,,{{\\pos(10,{y})}}{txt}\n"
        for y, txt in zip(ys, lines)
    )
    ass = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Cal,{COMMENT_FONT},{fs},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,"
        "100,100,0,0,1,0,0,7,0,0,0,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        + events
    )
    tmp = Path(tempfile.mkdtemp(prefix="tictok_calib_"))
    ass_path = tmp / "calib.ass"
    png_path = tmp / "calib.png"
    try:
        ass_path.write_text(ass, encoding="utf-8")
        # Reference the .ass by bare name with cwd=tmp so the filter graph needs no
        # Windows path escaping (drive ':' / '\\'), same as the main render path.
        proc = subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
             "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:d=1",
             "-vf", "ass=calib.ass", "-frames:v", "1", "calib.png"],
            cwd=str(tmp), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if proc.returncode != 0 or not png_path.is_file():
            return None
        im = Image.open(png_path).convert("L").point(lambda p: 255 if p > 60 else 0)
        W, H = im.size

        def right_edge(yc: int) -> int:
            box = im.crop((0, max(0, yc - 2), W, min(H, yc + 2 * fs))).getbbox()
            return box[2] if box else -1

        edges = [right_edge(y) for y in ys]
        if any(e < 0 for e in edges):
            return None
        wide_em = (edges[1] - edges[0]) / (cjk_n2 - cjk_n1) / fs
        narrow_em = (edges[3] - edges[2]) / len(_CALIB_ASCII) / fs
    except Exception:
        logger.warning("font metric calibration render failed", exc_info=True)
        return None
    finally:
        for p in (ass_path, png_path):
            p.unlink(missing_ok=True)
        try:
            tmp.rmdir()
        except OSError:
            pass
    # Sanity bounds: advances must be positive and below a full em (full-width is
    # ~1em; anything outside means the probe mis-measured — discard it).
    if not (0.2 <= wide_em <= 1.2 and 0.2 <= narrow_em <= 1.2):
        return None
    return wide_em, narrow_em


async def _font_metrics() -> tuple:
    """(wide_em, narrow_em) for COMMENT_FONT, measured once and cached. Falls back
    to the nominal ratios (logged) only when the calibration render cannot run."""
    global _font_em
    if _font_em is not None:
        return _font_em
    async with _font_em_lock:
        if _font_em is not None:
            return _font_em
        loop = asyncio.get_running_loop()
        measured = await loop.run_in_executor(None, _measure_font_em_sync)
        if measured is None:
            logger.warning(
                "comment font calibration unavailable; using nominal em ratios "
                "(wide=%.2f narrow=%.2f) — wrap width may be approximate",
                NOMINAL_WIDE_EM, NOMINAL_NARROW_EM,
            )
            _font_em = (NOMINAL_WIDE_EM, NOMINAL_NARROW_EM)
        else:
            logger.info("comment font calibrated: wide=%.3f narrow=%.3f em", *measured)
            _font_em = measured
        return _font_em


def _estimate_width(text: str, font_size: float,
                    wide: float = NOMINAL_WIDE_EM, narrow: float = NOMINAL_NARROW_EM) -> float:
    """Rendered pixel width using the measured per-glyph em-advances (CJK ``wide``,
    Latin ``narrow``)."""
    units = 0.0
    for ch in text:
        units += wide if ord(ch) > 0x2E7F else narrow
    return units * font_size


def _truncate(text: str, font_size: float, max_w: float,
              wide: float = NOMINAL_WIDE_EM, narrow: float = NOMINAL_NARROW_EM) -> str:
    """Trim text with an ellipsis so it fits within max_w pixels on one line."""
    if max_w <= 0 or _estimate_width(text, font_size, wide, narrow) <= max_w:
        return text
    ell = "…"
    ell_w = _estimate_width(ell, font_size, wide, narrow)
    out, w = "", 0.0
    for ch in text:
        cw = (wide if ord(ch) > 0x2E7F else narrow) * font_size
        if w + cw + ell_w > max_w:
            break
        out += ch
        w += cw
    return out + ell


# ===== Colour-emoji comment rendering (PIL) =====
# Comments are drawn through Pillow (not libass) so emoji show in full colour like
# a phone, instead of the monochrome glyph outlines libass produces. The fonts are
# fetched on demand into assets/fonts (see fonts.py): a CJK+Latin text font and a
# colour-emoji font. PIL has
# no automatic font fallback, so each comment string is split into text/emoji runs
# and each run is drawn with its own font; the comment layer (this) and the gift/
# score layer (still ASS) are composited together by ffmpeg.
ASSETS_FONT_DIR = PROJECT_ROOT / "assets" / "fonts"
TEXT_FONT_FILE = "NotoSansCJKjp-Regular.otf"
EMOJI_FONT_FILE = "NotoColorEmoji.ttf"
# Text fallback chain for glyphs the primary CJK font lacks (decorative kaomoji use
# Georgian letters, phonetic-extension letters, maths operators and combining marks
# as eyes/brows/mouths). PIL has no automatic fallback, so each character is routed
# to the first font in [primary, *fallbacks] whose cmap covers it; characters no
# bundled font covers are dropped (they would otherwise render as tofu boxes). The
# order is the resolution priority. All SIL OFL 1.1, same Noto family as the primary.
TEXT_FALLBACK_FONT_FILES = (
    "NotoSans-VF.ttf",            # phonetic extensions, combining marks, sub/superset
    "NotoSansGeorgian-VF.ttf",    # Georgian letters used as kaomoji brows
    "NotoSansMath-Regular.ttf",   # supplemental maths operators used as kaomoji mouths
)
# Noto Color Emoji is a bitmap-strike font: its glyphs live at this single pixel
# size, so emoji are rendered at the native strike and scaled down (crisp result).
EMOJI_STRIKE_PX = 109
# A colour-emoji cell is laid out roughly square at this multiple of the comment
# font size; used by both wrap measurement and rendering so they stay consistent.
# Kept at 1.0 so emoji match the text height instead of overpowering it.
EMOJI_TILE_EM = 1.0

# Codepoint ranges drawn with the colour-emoji font (predominantly emoji blocks).
# Text-presentation arrows/letters are intentionally excluded so ordinary text is
# never recoloured; only codepoints that render as emoji by default are included.
_EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),   # Mahjong/Dominoes/Cards + all pictographs/supplemental
    (0x1F1E6, 0x1F1FF),   # Regional indicators (flags)
    (0x2600, 0x27BF),     # Misc symbols + Dingbats
    (0x231A, 0x23FF),     # Watch/hourglass + media controls
    (0x2B00, 0x2BFF),     # Stars and arrows-as-emoji
)
_EMOJI_SINGLES = frozenset({0x2122, 0x2139, 0x203C, 0x2049, 0x2328, 0x24C2,
                            0x3030, 0x303D, 0x3297, 0x3299})
# Codepoints that extend a cluster started by an emoji base (never start one).
_EMOJI_MODS = frozenset({0xFE0F, 0xFE0E, 0x200D, 0x20E3})


def _is_emoji_mod(cp: int) -> bool:
    return (cp in _EMOJI_MODS or 0x1F3FB <= cp <= 0x1F3FF or 0xE0020 <= cp <= 0xE007F)


def _is_emoji_base(cp: int) -> bool:
    if cp in _EMOJI_SINGLES:
        return True
    for lo, hi in _EMOJI_RANGES:
        if lo <= cp <= hi:
            return True
    return False


def _strip_bidi_controls(text: Optional[str]) -> str:
    """Remove invisible format/control characters (bidi embeddings/overrides such as
    U+202A, zero-width controls, etc.) that carry no glyph and render as tofu boxes
    when burned into the video. Emoji joiners and variation selectors (ZWJ, VS) are
    kept so ``_tokenize_emoji`` can still assemble emoji clusters. Used on the ASS
    comment path; the colour-emoji shaper additionally drops uncovered glyphs."""
    if not text:
        return ""
    out = []
    for ch in text:
        cp = ord(ch)
        if unicodedata.category(ch) in ("Cc", "Cf") and not _is_emoji_mod(cp):
            continue
        out.append(ch)
    return "".join(out)


def _tokenize_emoji(text: str) -> list:
    """Split ``text`` into ordered ('text', run) / ('emoji', cluster) tokens. An
    emoji cluster absorbs trailing modifiers (variation selector, skin tone) and
    ZWJ-joined emoji so a joined sequence draws as a single token; adjacent emoji
    without a ZWJ stay separate tokens."""
    tokens: list = []
    buf: list = []
    i, n = 0, len(text)
    while i < n:
        cp = ord(text[i])
        if _is_emoji_base(cp):
            if buf:
                tokens.append(("text", "".join(buf)))
                buf = []
            cluster = [text[i]]
            i += 1
            while i < n:
                c2 = ord(text[i])
                if _is_emoji_mod(c2):
                    cluster.append(text[i])
                    i += 1
                elif c2 == 0x200D and i + 1 < n and _is_emoji_base(ord(text[i + 1])):
                    cluster.append(text[i])
                    cluster.append(text[i + 1])
                    i += 2
                else:
                    break
            tokens.append(("emoji", "".join(cluster)))
        else:
            buf.append(text[i])
            i += 1
    if buf:
        tokens.append(("text", "".join(buf)))
    return tokens


def _emoji_units(text: str) -> list:
    """Wrap units: one entry per character for text, one per cluster for emoji."""
    out: list = []
    for kind, s in _tokenize_emoji(text):
        if kind == "emoji":
            out.append(("emoji", s))
        else:
            out.extend(("text", ch) for ch in s)
    return out


def _emoji_base_count(cluster: str) -> int:
    return max(1, sum(1 for ch in cluster if _is_emoji_base(ord(ch))))


def _ass_color_to_rgb(literal: str) -> tuple:
    """ASS &HBBGGRR& colour literal -> (R, G, B)."""
    h = literal.strip().lstrip("&").lstrip("Hh").rstrip("&")
    h = (h or "0").rjust(6, "0")[-6:]
    return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))


class _CommentShaper:
    """Mixed text/colour-emoji measuring and rendering for the comment layer. Holds
    the bundled CJK text font and colour-emoji font, caches per-size text fonts and
    per-cluster rendered emoji tiles, and exposes wrap/truncate/measure used by both
    the layout (so line breaks match) and the tile renderer. One per render.

    Construction raises if Pillow or the bundled fonts are unavailable; callers treat
    that as "no colour-emoji layer" and fall back to the monochrome ASS comment path."""

    def __init__(self) -> None:
        from PIL import ImageFont  # raises ImportError if Pillow is missing
        from fontTools.ttLib import TTFont  # raises ImportError if fontTools is missing

        from tictok.record.fonts import ensure_fonts

        # The overlay fonts are fetched on demand (not committed); a network or
        # verification failure raises here and the caller falls back to ASS.
        ensure_fonts()

        self._ImageFont = ImageFont
        emoji_path = ASSETS_FONT_DIR / EMOJI_FONT_FILE
        text_path = ASSETS_FONT_DIR / TEXT_FONT_FILE
        if not emoji_path.is_file() or not text_path.is_file():
            raise FileNotFoundError(f"comment fonts missing under {ASSETS_FONT_DIR}")
        self._text_path = str(text_path)
        self._emoji_font = ImageFont.truetype(str(emoji_path), EMOJI_STRIKE_PX)
        self._font_cache: dict = {}   # (path, size) -> PIL font
        self._emoji_cache: dict = {}
        # Glyph-coverage chain: the primary CJK font first, then each fallback in
        # priority order. A character is drawn with the first font whose cmap covers
        # it; this is the manual equivalent of system font fallback (which PIL lacks).
        self._chain: list = [(self._text_path, frozenset(TTFont(self._text_path).getBestCmap()))]
        for name in TEXT_FALLBACK_FONT_FILES:
            fpath = ASSETS_FONT_DIR / name
            if not fpath.is_file():
                raise FileNotFoundError(f"bundled fallback font missing: {fpath}")
            self._chain.append((str(fpath), frozenset(TTFont(str(fpath)).getBestCmap())))
        self._cp_cache: dict = {}     # codepoint -> covering font path (or None)

    def _pil_font(self, path: str, fs: int):
        key = (path, fs)
        font = self._font_cache.get(key)
        if font is None:
            font = self._ImageFont.truetype(path, fs)
            self._font_cache[key] = font
        return font

    def text_font(self, fs: int):
        return self._pil_font(self._text_path, fs)

    def _cp_font(self, cp: int) -> Optional[str]:
        """Path of the first chain font whose cmap covers ``cp``, or None if no
        bundled text font has a glyph for it."""
        if cp in self._cp_cache:
            return self._cp_cache[cp]
        path = next((p for p, cov in self._chain if cp in cov), None)
        self._cp_cache[cp] = path
        return path

    def sanitize(self, text: Optional[str]) -> str:
        """Clean a comment string for the colour-emoji path: drop invisible bidi/
        control characters (tofu, kept-emoji-mods excepted) and any glyph no bundled
        text font covers, so the burn-in never shows replacement boxes. Emoji are
        left untouched (they render through the colour-emoji font)."""
        if not text:
            return ""
        out = []
        for ch in text:
            cp = ord(ch)
            if _is_emoji_base(cp) or _is_emoji_mod(cp):
                out.append(ch)
                continue
            if unicodedata.category(ch) in ("Cc", "Cf"):
                continue
            if self._cp_font(cp) is None:
                continue
            out.append(ch)
        return "".join(out)

    def font_runs(self, s: str, fs: int) -> list:
        """Split a (non-emoji) text string into maximal runs sharing one font, as
        (PIL font, substring) pairs, so each run is drawn with a font that has its
        glyphs. ``sanitize`` has already removed uncovered characters, so every char
        resolves to a font (the primary is the last-resort default)."""
        runs: list = []
        cur: list = []
        cur_path: Optional[str] = None
        for ch in s:
            path = self._cp_font(ord(ch)) or self._text_path
            if cur and path != cur_path:
                runs.append((cur_path, "".join(cur)))
                cur = []
            cur.append(ch)
            cur_path = path
        if cur:
            runs.append((cur_path, "".join(cur)))
        return [(self._pil_font(p, fs), t) for p, t in runs]

    def emoji_px(self, fs: int) -> int:
        return max(8, int(round(fs * EMOJI_TILE_EM)))

    def emoji_tile(self, cluster: str, px: int):
        """RGBA image of ``cluster`` scaled to height ``px`` (cached). Multi-emoji
        (ZWJ) clusters keep their natural width so components never overlap."""
        key = (cluster, px)
        tile = self._emoji_cache.get(key)
        if tile is not None:
            return tile
        from PIL import Image, ImageDraw

        clean = cluster.replace("️", "").replace("︎", "")
        nbase = _emoji_base_count(cluster)
        # Noto Color Emoji's bitmap strike renders a glyph larger than its nominal
        # ppem (a 109-ppem glyph inks to ~136px), so the canvas must be sized well
        # above EMOJI_STRIKE_PX and the glyph drawn with margin — a tight canvas
        # clips the glyph's right/bottom edges, and getbbox then returns the clipped
        # box, which scales up so the emoji looks oversized and cut off.
        pad = EMOJI_STRIKE_PX
        cell = EMOJI_STRIKE_PX * 2
        canvas = Image.new("RGBA", (pad + cell * nbase, pad + cell), (0, 0, 0, 0))
        ImageDraw.Draw(canvas).text((pad // 2, pad // 2), clean, font=self._emoji_font, embedded_color=True)
        bbox = canvas.getbbox()
        if not bbox:
            tile = Image.new("RGBA", (max(1, px), px), (0, 0, 0, 0))
        else:
            crop = canvas.crop(bbox)
            scale = px / crop.height
            w = max(1, int(round(crop.width * scale)))
            tile = crop.resize((w, px), Image.LANCZOS)
        self._emoji_cache[key] = tile
        return tile

    def _unit_width(self, kind: str, s: str, fs: int) -> float:
        if kind == "emoji":
            return self.emoji_tile(s, self.emoji_px(fs)).width
        # ``s`` is a single text character here (see _emoji_units); measure it with
        # the same font it will be drawn with so wrap/draw widths stay consistent.
        path = self._cp_font(ord(s[0])) if s else None
        return self._pil_font(path or self._text_path, fs).getlength(s)

    def measure(self, text: str, fs: int) -> float:
        return sum(self._unit_width(k, s, fs) for k, s in _emoji_units(text))

    def wrap(self, text: str, fs: int, max_w: float) -> list:
        """Break ``text`` into lines fitting ``max_w`` px. ASCII breaks at spaces,
        CJK/emoji per unit; emoji widths are the rendered tile widths."""
        if max_w <= 0 or not text:
            return [text] if text else [""]
        lines: list = []
        cur = ""
        cur_w = 0.0
        last_space = -1
        for kind, s in _emoji_units(text):
            uw = self._unit_width(kind, s, fs)
            if cur and cur_w + uw > max_w:
                if last_space > 0:
                    lines.append(cur[:last_space])
                    cur = cur[last_space + 1:]
                else:
                    lines.append(cur)
                    cur = ""
                cur_w = self.measure(cur, fs)
                last_space = -1
            if kind == "text" and s == " ":
                last_space = len(cur)
            cur += s
            cur_w += uw
        if cur:
            lines.append(cur)
        return lines or [""]

    def truncate(self, text: str, fs: int, max_w: float) -> str:
        if max_w <= 0 or self.measure(text, fs) <= max_w:
            return text
        ell = "…"
        ell_w = self.text_font(fs).getlength(ell)
        out, w = "", 0.0
        for kind, s in _emoji_units(text):
            uw = self._unit_width(kind, s, fs)
            if w + uw + ell_w > max_w:
                break
            out += s
            w += uw
        return out + ell


def _make_comment_shaper() -> Optional["_CommentShaper"]:
    """A shaper for colour-emoji comment rendering, or None (logged) when Pillow or
    the bundled fonts are unavailable — the caller then uses the ASS comment path."""
    try:
        return _CommentShaper()
    except Exception:
        logger.warning(
            "colour-emoji comment shaper unavailable (Pillow or bundled fonts "
            "missing); comments will render with monochrome emoji via ASS",
            exc_info=True,
        )
        return None


def _avatar_color(nick: str) -> str:
    key = sum(ord(c) for c in nick) if nick else 0
    return _AVATAR_COLORS[key % len(_AVATAR_COLORS)]


def _circle_path(r: int) -> str:
    """ASS \\p drawing for a filled circle, bounding box (0,0)-(2r,2r)."""
    k = int(round(r * 0.5523))
    return (
        f"m 0 {r} b 0 {r - k} {r - k} 0 {r} 0 "
        f"b {r + k} 0 {2 * r} {r - k} {2 * r} {r} "
        f"b {2 * r} {r + k} {r + k} {2 * r} {r} {2 * r} "
        f"b {r - k} {2 * r} 0 {r + k} 0 {r}"
    )


def _comment_metrics(width: int, height: int, font_size: int,
                     wide_em: float = NOMINAL_WIDE_EM, narrow_em: float = NOMINAL_NARROW_EM) -> dict:
    """Layout geometry for the comment feed, shared verbatim by the ASS text
    generator and the real-avatar overlay renderer so both place the same comment
    at the same pixel at the same time (otherwise the two layers drift apart).
    Comment blocks have a variable height (a long comment wraps onto as many lines
    as it needs), so the per-comment height is computed by the layout, not here."""
    line_h = max(1, int(round(font_size * 1.3)))
    avatar_r = max(4, int(round(line_h * 0.78)))
    avatar_d = 2 * avatar_r
    gap = max(4, int(round(font_size * 0.4)))
    x_left = max(8, int(round(width * 0.025)))
    x_text = x_left + avatar_d + gap
    # Comments occupy the left COMMENT_WIDTH_FRAC of the frame; text past that
    # wraps onto the next line so the full comment shows (never an ellipsis).
    text_max_w = int(width * COMMENT_WIDTH_FRAC) - x_text
    y_bottom = int(height * BAND_BOTTOM)
    band_top = int(height * COMMENT_BAND_TOP)
    gap_v = max(3, int(round(font_size * 0.3)))  # vertical gap between comments
    # Positional fade zone at the top of the band: a comment fades out smoothly as
    # its top edge rises through this zone, so the oldest comments dissolve like a
    # typical live feed instead of being hard-clipped at the band edge.
    fade_height = max(line_h * 2, int(round((y_bottom - band_top) * 0.16)))
    slide_cs = int(SLIDE_SECONDS * 1000 / 2)
    avatar_off = max(0, (2 * line_h - avatar_d) // 2)
    initial_fs = max(7, int(round(avatar_d * 0.8)))
    return {
        "line_h": line_h, "avatar_r": avatar_r, "avatar_d": avatar_d, "gap": gap,
        "x_left": x_left, "x_text": x_text, "text_max_w": text_max_w,
        "y_bottom": y_bottom, "band_top": band_top, "gap_v": gap_v,
        "fade_height": fade_height, "slide_cs": slide_cs,
        "avatar_off": avatar_off, "initial_fs": initial_fs,
        "wide_em": wide_em, "narrow_em": narrow_em,
    }


def _wrap_text(text: str, font_size: float, max_w: float,
               wide: float = NOMINAL_WIDE_EM, narrow: float = NOMINAL_NARROW_EM) -> list:
    """Break ``text`` into lines that each fit within ``max_w`` pixels, so the
    whole comment shows instead of being cut with an ellipsis. ASCII runs break at
    spaces when possible; CJK (no spaces) breaks per character. Returns at least
    one line (possibly empty)."""
    if max_w <= 0 or not text:
        return [text] if text else [""]
    lines: list[str] = []
    cur = ""
    cur_w = 0.0
    last_space = -1  # index in cur of the most recent space, for a soft break
    for ch in text:
        cw = (wide if ord(ch) > 0x2E7F else narrow) * font_size
        if cur and cur_w + cw > max_w:
            if last_space > 0:
                lines.append(cur[:last_space])
                cur = cur[last_space + 1:]  # carry the remainder, drop the space
            else:
                lines.append(cur)
                cur = ""
            cur_w = _estimate_width(cur, font_size, wide, narrow)
            last_space = -1
        if ch == " ":
            last_space = len(cur)
        cur += ch
        cur_w += cw
    if cur:
        lines.append(cur)
    return lines or [""]


def _pos_alpha(top: float, band_top: float, fade_height: float) -> float:
    """Opacity (1.0 = opaque) for a comment whose top edge is at ``top``. A comment
    is fully opaque below the fade zone and fades linearly to transparent as its
    top edge rises from band_top+fade_height up to band_top — so the oldest
    comments dissolve smoothly off the top like a typical live feed."""
    if fade_height <= 0:
        return 1.0
    if top >= band_top + fade_height:
        return 1.0
    if top <= band_top:
        return 0.0
    return (top - band_top) / fade_height


def _layout_comment_feed(comments: list, m: dict, font_size: int, end_time: float, avatar_ids: set,
                         shaper: Optional["_CommentShaper"] = None) -> list:
    """Place every comment in the bottom-left feed and return a list of placements.

    Each comment is wrapped to as many lines as its full text needs (no ellipsis),
    so blocks have variable heights. The newest comment sits at the bottom; each
    older one is stacked above by its own height. When a new comment arrives the
    whole stack slides up by the new block's height. A comment is emitted for each
    such stack state until its top edge rises above the band (it has fully faded);
    the final comments (nothing after to push them up) hold until ``end_time``.

    Placement: {nick_disp, body_lines, color, initial, has_avatar, uid, empty,
    block_h, segments:[{start, end, top, prev_top, grad, fad_in, tail}]}. Both the
    ASS generator and the real-avatar renderer consume this so they stay aligned."""
    line_h, avatar_d, gap_v = m["line_h"], m["avatar_d"], m["gap_v"]
    y_bottom, band_top = m["y_bottom"], m["band_top"]
    text_max_w, fade_height, avatar_off = m["text_max_w"], m["fade_height"], m["avatar_off"]
    wide_em, narrow_em = m["wide_em"], m["narrow_em"]
    # A single comment can't be taller than the band; cap its wrapped lines to what
    # fits (a pathological essay stops at the band edge — still no ellipsis).
    max_body_lines = max(1, (y_bottom - band_top) // line_h - 1)

    arr = [c["offset"] for c in comments]
    n = len(comments)
    items: list[dict] = []
    for c in comments:
        # With the colour-emoji shaper the breaks/widths are measured with the real
        # render fonts (emoji included); without it, fall back to the libass em model.
        # Either way invisible control chars (and, for the shaper, glyphs no bundled
        # font covers) are stripped first so the burn-in never shows tofu boxes.
        if shaper is not None:
            nick = _ass_escape(shaper.sanitize(c.get("nick")))
            body = _ass_escape(shaper.sanitize(c.get("text")))
            body_lines = shaper.wrap(body, font_size, text_max_w)[:max_body_lines]
            nick_disp = shaper.truncate(nick, font_size, text_max_w)
        else:
            nick = _ass_escape(_strip_bidi_controls(c.get("nick")))
            body = _ass_escape(_strip_bidi_controls(c.get("text")))
            body_lines = _wrap_text(body, font_size, text_max_w, wide_em, narrow_em)[:max_body_lines]
            nick_disp = _truncate(nick, font_size, text_max_w, wide_em, narrow_em)
        block_h = max(avatar_d + 2 * avatar_off, (1 + len(body_lines)) * line_h)
        items.append({
            "nick_disp": nick_disp,
            "body_lines": body_lines,
            "color": _avatar_color(nick),
            "initial": (nick.strip()[:1] or "?").upper(),
            "has_avatar": c.get("user_id") in avatar_ids,
            "uid": c.get("user_id"),
            "empty": (not body and not nick),
            "block_h": block_h,
        })

    for i in range(n):
        h_i = items[i]["block_h"]
        segments: list[dict] = []
        prev_top = y_bottom  # entry: slide up from the bottom edge of the band
        cumulative = 0  # stacked height of the comments newer than i (below it)
        for j in range(i, n):
            if j > i:
                cumulative += items[j]["block_h"] + gap_v
            top = y_bottom - h_i - cumulative
            if j > i and top <= band_top:
                break  # scrolled fully off the top
            grad = _pos_alpha(top, band_top, fade_height)
            segments.append({
                "start": arr[j],
                "end": arr[j + 1] if j + 1 < n else max(end_time, arr[j]),
                "top": top,
                "prev_top": prev_top,
                "grad": grad,
                "fad_in": 150 if j == i else 0,
                "tail": j == n - 1,
            })
            prev_top = top
            if grad <= 0.0:
                break
        items[i]["segments"] = segments
    return items


def _build_comment_dialogues(placements: list, m: dict) -> list:
    """TikTok-style bottom-left comment feed from the layout placements. Each
    comment is an avatar on the left with the username on the first line and the
    full comment text wrapped onto as many lines as it needs to its right.
    Comments with a real avatar (composited by the overlay layer) omit the ASS
    disc/initial; the rest get an initial-letter colour disc drawn here."""
    x_left, x_text = m["x_left"], m["x_text"]
    avatar_r, avatar_off, slide_cs = m["avatar_r"], m["avatar_off"], m["slide_cs"]
    initial_fs = m["initial_fs"]

    dialogues: list[str] = []
    for p in placements:
        if p["empty"]:
            continue
        # username (line 1) + the full wrapped comment (lines 2..N)
        text = (f"{{\\b1\\c&H7CE0FF&}}{p['nick_disp']}{{\\b0\\c&HFFFFFF&}}"
                + "".join(f"\\N{ln}" for ln in p["body_lines"]))
        for seg in p["segments"]:
            top, prev_top, grad = seg["top"], seg["prev_top"], seg["grad"]
            # A faded segment carries a constant \alpha (the gradient); it is never
            # an entry segment, so it needs no \fad — and \fad would override
            # \alpha. Opaque segments keep \fad for enter (and exit on the tail).
            if grad < 1.0:
                anim = f"\\alpha&H{min(255, round((1 - grad) * 255)):02X}&"
            else:
                anim = f"\\fad({seg['fad_in']},{300 if seg['tail'] else 0})"
            start_ts, end_ts = _ass_timestamp(seg["start"]), _ass_timestamp(seg["end"])
            if not p["has_avatar"]:
                # avatar disc (\move on x=0 origin; path supplies the x position)
                mv_av = f"\\move({x_left},{prev_top + avatar_off},{x_left},{top + avatar_off},0,{slide_cs})"
                dialogues.append(
                    f"Dialogue: 4,{start_ts},{end_ts},Comment,,0,0,0,,"
                    f"{{\\an7{mv_av}{anim}\\1c{p['color']}\\bord0\\shad0\\p1}}{_circle_path(avatar_r)}"
                )
                # initial letter centred on the disc
                mv_in = (f"\\move({x_left + avatar_r},{prev_top + avatar_off + avatar_r},"
                         f"{x_left + avatar_r},{top + avatar_off + avatar_r},0,{slide_cs})")
                dialogues.append(
                    f"Dialogue: 5,{start_ts},{end_ts},Comment,,0,0,0,,"
                    f"{{\\an5{mv_in}{anim}\\fs{initial_fs}\\b1\\c&HFFFFFF&\\bord1}}{_ass_escape(p['initial'])}"
                )
            mv_tx = f"\\move({x_text},{prev_top},{x_text},{top},0,{slide_cs})"
            dialogues.append(
                f"Dialogue: 5,{start_ts},{end_ts},Comment,,0,0,0,,"
                f"{{\\an7{mv_tx}{anim}}}{text}"
            )
    return dialogues


def _build_gift_layout(gifts: list, width: int, height: int, coin_fs: int, icon_px: int, hold: int,
                       wide_em: float = NOMINAL_WIDE_EM, narrow_em: float = NOMINAL_NARROW_EM,
                       gift_band_top: float = GIFT_BAND_TOP) -> tuple[list, list]:
    """Gifts shown in the upper-left band as an icon that slides in with the coin
    (diamond) count beneath it — no sender/gift name, no text background. Returns
    (text_dialogues, overlay_specs). The slot count is computed so the gift band
    fits between the top and the comment band (never overlapping comments). Each
    spec carries gift_id/gift_name/url so the icon can be resolved from cache or
    re-resolved later. ``gift_band_top`` is lowered when the Battle score bar
    occupies the very top so gifts never overlap it."""
    x_left = max(8, int(round(width * 0.025)))
    gift_top = int(height * gift_band_top)
    comment_top = int(height * COMMENT_BAND_TOP)
    slot_h = icon_px + coin_fs + max(8, int(round(coin_fs * 0.5)))
    avail = max(slot_h, comment_top - gift_top)
    slot_count = max(1, min(4, avail // slot_h))
    slot_free = [0.0] * slot_count
    slide_ms = int(SLIDE_SECONDS * 1000)
    text_dialogues: list[str] = []
    overlays: list[dict] = []
    for item in gifts:
        t = item["offset"]
        slot = min(range(slot_count), key=lambda i: slot_free[i])
        for idx in range(slot_count):
            if slot_free[idx] <= t:
                slot = idx
                break
        slot_free[slot] = t + hold
        icon_y = gift_top + slot * slot_h
        coins = item.get("diamonds") or 0
        # Gift labels render through libass; strip invisible bidi/control chars so a
        # sender name carrying them does not burn in as tofu boxes (same root cause
        # as comments, which the colour-emoji shaper sanitizes).
        nick = _ass_escape(_strip_bidi_controls(item.get("nick")))
        # "<coins> (<user>)", e.g. "1 (user a)"; truncated to stay within frame.
        label = f"{coins:,} ({nick})" if nick else f"{coins:,}"
        label = _truncate(label, coin_fs, width - x_left * 2, wide_em, narrow_em)
        start, end = t, t + hold
        # coin+user line sits left-aligned just under the icon
        cy = icon_y + icon_px + 2
        identifiable = bool(item.get("gift_id") or item.get("gift_name") or item.get("image"))
        if identifiable:
            # slide horizontally in sync with the icon
            x_off = x_left - (icon_px + 20)
            move = f"\\move({x_off},{cy},{x_left},{cy},0,{slide_ms})"
            tag = f"{{\\an7{move}\\fad(150,300)}}"
            overlays.append({
                "gift_id": int(item.get("gift_id") or 0),
                "gift_name": item.get("gift_name") or "",
                "url": item.get("image") or "",
                "diamonds": coins,
                "start": start,
                "end": end,
                "x_rest": x_left,
                "y": max(0, icon_y),
            })
        else:
            tag = f"{{\\an7\\pos({x_left},{cy})\\fad(150,300)}}"
        text = f"{tag}{{\\b1}}{label}"
        text_dialogues.append(
            f"Dialogue: 6,{_ass_timestamp(start)},{_ass_timestamp(end)},Gift,,0,0,0,,{text}"
        )
    return text_dialogues, overlays


def _load_timing_anchors(src: Path) -> Optional[list]:
    """Load the recorder's wall->media anchors for ``src`` ([[wall, media], ...],
    ascending by wall), or None when absent/unreadable. These let the burn-in put
    each comment on the video's real timeline instead of wall-clock."""
    path = timing_path(src)
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("timing map read failed: %s", path, exc_info=True)
        return None
    anchors = data.get("anchors") if isinstance(data, dict) else None
    if not isinstance(anchors, list) or len(anchors) < 2:
        return None
    try:
        cleaned = [(float(w), float(m)) for w, m in anchors]
    except (TypeError, ValueError):
        return None
    cleaned.sort(key=lambda a: a[0])
    return cleaned


def _load_media_pts(src: Path) -> Optional[list]:
    """Load the recorder's exact media->pts correspondence ([[media, pts], ...],
    ascending by media), or None when absent (old recording, or the finalize probe
    was unavailable). The concatenated mp4's PTS runs longer than the media axis by
    a roughly fixed per-segment mux overhead; this per-segment correspondence lets
    the burn-in map media onto the real PTS exactly, instead of the single
    proportional scale that drifts by tens of seconds mid-stream (see
    _media_to_pts)."""
    path = timing_path(src)
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    media_pts = data.get("media_pts") if isinstance(data, dict) else None
    if not isinstance(media_pts, list) or len(media_pts) < 2:
        return None
    try:
        cleaned = [(float(m), float(p)) for m, p in media_pts]
    except (TypeError, ValueError):
        return None
    cleaned.sort(key=lambda a: a[0])
    return cleaned


def _detect_media_breaks(walls: list, medias: list) -> list:
    """Indices where the anchor media axis (cumulative EXTINF) jumps far more than
    the wall clock did — a glitched source timestamp that inflated one segment's
    media span. Returns [(media_before, media_after)] ascending. A genuine stream
    freeze (media advances with wall) is not a break."""
    breaks: list = []
    for i in range(len(medias) - 1):
        dm = medias[i + 1] - medias[i]
        dw = walls[i + 1] - walls[i]
        if dw >= 0 and is_pts_discontinuity(dm, dw):
            breaks.append((medias[i], medias[i + 1]))
    return breaks


def _media_to_pts(medias: list, walls: list, video_duration: Optional[float],
                  pts_gaps: Optional[list]):
    """Return f(media) -> mp4 PTS seconds.

    The anchor media axis (sum of EXTINF) and the finalized mp4 PTS axis differ by
    (a) a roughly uniform mux inflation (concat/+genpts) and (b) localized PTS
    discontinuities — a glitched source timestamp inflates one segment's EXTINF and
    leaves a matching frozen gap baked into the mp4. A single global
    ``scale = mp4_dur/media_end`` smears (b) across the whole timeline, so every
    comment drifts by tens of seconds, reversing sign at the gap. Instead, anchor
    the map on the real mp4 gap edges and give each clean region its own scale,
    which removes the drift; with no discontinuities this is exactly one scale."""
    media_end = medias[-1]
    if not video_duration or media_end <= 0:
        return lambda m: m

    breaks = _detect_media_breaks(walls, medias)
    gaps = sorted(pts_gaps or [])
    # Correspondence points (media, pts), ascending, pinned at both endpoints.
    points: list = [(0.0, 0.0)]
    for m_pre, m_post in breaks:
        phantom = m_post - m_pre
        # Match this glitch to the mp4 gap of the same size (a genuine freeze, which
        # is not a break, is left untouched and handled by the surrounding region).
        best = min(gaps, key=lambda g: abs((g[1] - g[0]) - phantom), default=None)
        if best is not None and abs((best[1] - best[0]) - phantom) <= max(5.0, 0.05 * phantom):
            points.append((m_pre, best[0]))
            points.append((m_post, best[1]))
            gaps.remove(best)
        else:
            logger.warning(
                "media break (phantom=%.1fs) has no matching mp4 PTS gap; comment "
                "timing near it may be approximate", phantom,
            )
    points.append((media_end, video_duration))
    # Strictly increasing on both axes for the piecewise interpolation.
    points = sorted(set(points))
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    def to_pts(m: float) -> float:
        if m <= xs[0]:
            return ys[0]
        if m >= xs[-1]:
            return ys[-1]
        k = bisect.bisect_right(xs, m)
        x0, x1, y0, y1 = xs[k - 1], xs[k], ys[k - 1], ys[k]
        return y1 if x1 <= x0 else y0 + (y1 - y0) * (m - x0) / (x1 - x0)

    return to_pts


def _media_pts_mapper(media_pts: list):
    """Return f(media) -> mp4 PTS by interpolating the recorder's exact per-segment
    media->pts correspondence (pinned at both ends). Replaces the single-scale
    _media_to_pts when the map carries this axis: the mp4's per-segment mux
    overhead is a near-fixed offset, not a proportional stretch, so a scale drifts
    with segment length while this interpolation stays exact."""
    xs = [m for m, _ in media_pts]
    ys = [p for _, p in media_pts]

    def to_pts(m: float) -> float:
        if m <= xs[0]:
            return ys[0]
        if m >= xs[-1]:
            return ys[-1]
        k = bisect.bisect_right(xs, m)
        x0, x1, y0, y1 = xs[k - 1], xs[k], ys[k - 1], ys[k]
        return y1 if x1 <= x0 else y0 + (y1 - y0) * (m - x0) / (x1 - x0)

    return to_pts


def _anchor_mappers(anchors: Optional[list], started_at: float, ended_at: Optional[float],
                    video_duration: Optional[float], pts_gaps: Optional[list] = None,
                    media_pts: Optional[list] = None):
    """Return (wall_to_media, media_to_pts): the two halves of the wall->pts map,
    exposed separately so Mode B (source-clock comment timing) can swap the
    wall->media half for a create_time axis while reusing the same media->pts
    half. Composing them gives the Mode A wall->pts map verbatim.

    The media->pts half prefers the recorder's exact per-segment correspondence
    (``media_pts``) and falls back to the gap-aware single-scale model when the map
    predates it (old recordings)."""
    if anchors and len(anchors) >= 2:
        walls = [a[0] for a in anchors]
        medias = [a[1] for a in anchors]
        if media_pts and len(media_pts) >= 2:
            media_to_pts = _media_pts_mapper(media_pts)
        else:
            media_to_pts = _media_to_pts(medias, walls, video_duration, pts_gaps)

        def wall_to_media(t: float) -> float:
            if t <= walls[0]:
                return medias[0]
            if t >= walls[-1]:
                return medias[-1]
            k = bisect.bisect_right(walls, t)
            w0, w1, m0, m1 = walls[k - 1], walls[k], medias[k - 1], medias[k]
            return m1 if w1 <= w0 else m0 + (m1 - m0) * (t - w0) / (w1 - w0)

        return wall_to_media, media_to_pts

    if video_duration is not None and ended_at is not None and ended_at > started_at:
        scale = video_duration / (ended_at - started_at)
        return (lambda t: (t - started_at) * scale), (lambda m: m)

    return (lambda t: t - started_at), (lambda m: m)


def _make_time_mapper(anchors: Optional[list], started_at: float, ended_at: Optional[float],
                      video_duration: Optional[float], pts_gaps: Optional[list] = None,
                      media_pts: Optional[list] = None):
    """Return f(event_wall_time) -> seconds on the mp4 PTS timeline (Mode A).

    Comments are stamped with the collector's wall-clock, but the recorded video's
    timeline is the stream's media PTS; the two clocks differ (startup latency,
    reconnect gaps, encoder skew), so a raw ``wall - started_at`` drifts more and
    more out of sync. Mapping order of preference:
      B) interpolate wall->media through the recorder's (wall, media) anchors, then
         media->mp4-PTS gap-aware (see _media_to_pts) — corrects the zero point,
         every reconnect gap, and PTS discontinuities;
      A) when no anchors exist (old recording), linearly fit the wall capture
         window onto the real video duration so the endpoints align and the drift
         can no longer accumulate;
      else) fall back to the raw wall offset.

    Note: this is the consumer-arrival time axis. The arrival path and the video
    path are buffered independently, so their relative latency can drift; Mode B
    (_make_source_mappers) re-anchors comments on the TikTok server create_time to
    remove that drift. Mode A is retained verbatim as the comparison baseline."""
    wall_to_media, media_to_pts = _anchor_mappers(
        anchors, started_at, ended_at, video_duration, pts_gaps, media_pts)
    return lambda t: media_to_pts(wall_to_media(t))


# ===== Mode B: source-clock (create_time) comment/battle timing =====
# Comments/gifts carry the TikTok server create_time (collector._create_time_sec);
# placing events by it instead of consumer arrival removes the arrival-vs-video
# latency drift. On connect the server flushes a backlog of pre-connect messages
# whose create_time is far in the past relative to arrival — excluded so it cannot
# poison the origin (C) estimate or the wall->source bridge.
SOURCE_BACKLOG_THRESHOLD = 5.0   # create_time - arrival below -this (s) => connection backlog
SOURCE_C_ANCHOR_SECONDS = 120.0  # early live window used to pin the origin constant C
SOURCE_MIN_ANCHOR_SAMPLES = 5


def _live_create_samples(events: list) -> list:
    """Ascending (arrival_time, create_time) pairs for live events carrying a
    create_time, with the connection backlog removed. These bridge the collector
    wall axis to the TikTok source axis for Mode B."""
    samples = []
    for e in events:
        ct = e.get("create_time")
        t = e.get("time")
        if ct is None or t is None:
            continue
        if ct - t < -SOURCE_BACKLOG_THRESHOLD:
            continue
        samples.append((t, ct))
    samples.sort()
    return samples


def _make_source_mappers(events: list, anchors: Optional[list], started_at: float,
                         ended_at: Optional[float], video_duration: Optional[float],
                         pts_gaps: Optional[list] = None, media_pts: Optional[list] = None):
    """Build the Mode B mappers, or return None when the recording cannot be
    source-anchored (no live create_time — e.g. an old recording).

    Returns a dict with:
      ``source_to_pts(s)``  -> pts for a TikTok source-epoch timestamp s (used for
            comments via their create_time, and for battle bonus windows whose
            *_timestamp fields are already source epoch);
      ``wall_to_pts(w)``    -> pts for a collector wall timestamp w (used for the
            battle score series, whose samples are stamped with time.time());
      ``c_value`` / ``n_anchor`` / ``n_backlog`` / ``n_samples`` -> diagnostics.

    Origin C (= source epoch at media 0) is the median over an early live window of
    ``create_time - wall_to_media(arrival)``, so Mode B matches the well-aligned
    start of Mode A and only diverges as Mode A drifts. The collector wall axis is
    bridged to source by interpolating the (arrival, create) samples."""
    samples = _live_create_samples(events)
    n_backlog = sum(
        1 for e in events
        if e.get("create_time") is not None and e.get("time") is not None
        and e["create_time"] - e["time"] < -SOURCE_BACKLOG_THRESHOLD
    )
    if len(samples) < SOURCE_MIN_ANCHOR_SAMPLES:
        return None

    wall_to_media, media_to_pts = _anchor_mappers(
        anchors, started_at, ended_at, video_duration, pts_gaps, media_pts)

    t_start = samples[0][0]
    early = [(t, ct) for t, ct in samples if t - t_start <= SOURCE_C_ANCHOR_SECONDS]
    if len(early) < SOURCE_MIN_ANCHOR_SAMPLES:
        early = samples[:SOURCE_MIN_ANCHOR_SAMPLES]
    deltas = sorted(ct - wall_to_media(t) for t, ct in early)
    c_value = deltas[len(deltas) // 2]  # median: source epoch corresponding to media 0

    arr = [t for t, _ in samples]
    crt = [ct for _, ct in samples]

    def arrival_to_create(w: float) -> float:
        if w <= arr[0]:
            return crt[0] + (w - arr[0])
        if w >= arr[-1]:
            return crt[-1] + (w - arr[-1])
        k = bisect.bisect_right(arr, w)
        w0, w1, c0, c1 = arr[k - 1], arr[k], crt[k - 1], crt[k]
        return c1 if w1 <= w0 else c0 + (c1 - c0) * (w - w0) / (w1 - w0)

    def source_to_pts(s: float) -> float:
        return media_to_pts(s - c_value)

    def wall_to_pts(w: float) -> float:
        return media_to_pts(arrival_to_create(w) - c_value)

    return {
        "source_to_pts": source_to_pts,
        "wall_to_pts": wall_to_pts,
        "c_value": c_value,
        "n_anchor": len(early),
        "n_backlog": n_backlog,
        "n_samples": len(samples),
    }


# ===== Battle score bar (burn-in) =====
# Top-of-frame PK score bar layout, as fractions of the video (own=left/opp=right).
SCORE_BAR_TOP = 0.075
SCORE_BAR_H_FRAC = 0.034
SCORE_BAR_MARGIN = 0.03
# Gifts drop below this fraction while the score bar occupies the very top, so the
# two layers never overlap (only applied when the bar is actually drawn).
SCORE_BAR_GIFT_BAND_TOP = 0.135
# Own = cool, opponent = warm; dark translucent track behind them.
_SCORE_OWN_RGB = "22A8E6"
_SCORE_OPP_RGB = "E6486B"
_SCORE_TRACK_RGB = "0A0E14"
# 個人マルチ(3コラ+)で陣営(参加者)ごとに塗り分ける敵陣色。1人目は_SCORE_OPP_RGB(rose)のままで
# 1v1/2分割の見た目を保ち、2人目以降に別色を割り当てる。陣営数が色数を超えたら循環で再利用する。
_SCORE_OPP_PALETTE = (
    _SCORE_OPP_RGB,  # rose (敵陣1)
    "9B6BE6",  # purple
    "E6A60A",  # amber
    "1FB58A",  # teal
    "E6783C",  # orange
    "E64FA6",  # pink
)

# Match Bonus Mission (倍率タイム) band, drawn just below the score bar during the
# task/reward windows only. Gold = mission/reward, red = countdown running out.
BONUS_BAND_TOP = 0.116
BONUS_BAND_H_FRAC = 0.022
BONUS_BAND_MARGIN = 0.20
BONUS_SETTLE_HOLD = 3.0
_BONUS_GOLD_RGB = "F5A60A"
_BONUS_HOT_RGB = "E6486B"
_BONUS_TRACK_RGB = "0A0E14"


def _ass_bgr(rgb_hex: str) -> str:
    """#RRGGBB (or RRGGBB) -> ASS &HBBGGRR& colour literal."""
    h = rgb_hex.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def _round_rect_path(x: float, y: float, w: float, h: float, r: float,
                     left: bool = True, right: bool = True) -> str:
    """ASS \\p drawing of a rounded rectangle in absolute PlayRes coords. ``left`` /
    ``right`` choose which vertical corner pair is rounded, so the own fill rounds only
    on the left and the opp fill only on the right, meeting square at the split."""
    xi, yi = int(round(x)), int(round(y))
    x2, y2 = int(round(x + w)), int(round(y + h))
    r = int(round(min(r, w / 2, h / 2)))
    rl = r if left else 0
    rr = r if right else 0
    p = [f"m {xi + rl} {yi}", f"l {x2 - rr} {yi}"]
    if rr:
        p.append(f"b {x2} {yi} {x2} {yi} {x2} {yi + rr}")
    p.append(f"l {x2} {y2 - rr}")
    if rr:
        p.append(f"b {x2} {y2} {x2} {y2} {x2 - rr} {y2}")
    p.append(f"l {xi + rl} {y2}")
    if rl:
        p.append(f"b {xi} {y2} {xi} {y2} {xi} {y2 - rl}")
    p.append(f"l {xi} {yi + rl}")
    if rl:
        p.append(f"b {xi} {yi} {xi} {yi} {xi + rl} {yi}")
    return " ".join(p)


def _battle_mode_label(battle: dict) -> str:
    """形式ラベル: 個人戦 1v1 / 個人戦 Nコラ / チーム戦 NvM。"""
    parts = battle.get("participants") or []
    own_n = sum(1 for p in parts if p.get("is_own") or p.get("side") == "own")
    opp_n = sum(1 for p in parts if p.get("side") == "opp" and not p.get("is_own"))
    if battle.get("type") == "team":
        return f"チーム戦 {own_n}v{opp_n}" if (own_n and opp_n) else "チーム戦"
    n = len(parts)
    return "個人戦 1v1" if n <= 2 else f"個人戦 {n}コラ"


def _fmt_clock(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return f"{s // 60:d}:{s % 60:02d}"


# Hard cap on per-second clock lines per battle, so a pathological window (e.g. an
# ongoing battle with a sparse/odd time map) cannot explode the ASS line count.
_SCORE_CLOCK_MAX_STEPS = 3600


def _personal_lane_order(series: list) -> list:
    """個人マルチ(3コラ+)用に、score_seriesのpartsから左→右の固定lane順を決める。
    自分(side=="own")を先頭、相手は到達した最高scoreの降順で安定配置する(scoreが
    時系列で前後しても並びは固定)。partsを持たない/2人以下なら空listを返し、呼び出し
    側は従来の自陣/敵陣2分割へfallbackする。戻り値は[(participant_id, is_own), ...]。"""
    side: dict = {}
    best: dict = {}
    for sm in series:
        for pt in (sm.get("parts") or []):
            pid = pt.get("id")
            if pid is None:
                continue
            side[pid] = pt.get("side")
            best[pid] = max(best.get(pid, 0), pt.get("score") or 0)
    if len(side) <= 2:
        return []
    own_ids = [pid for pid, sd in side.items() if sd == "own"]
    opp_ids = sorted((pid for pid, sd in side.items() if sd != "own"),
                     key=lambda pid: -best.get(pid, 0))
    return [(pid, True) for pid in own_ids] + [(pid, False) for pid in opp_ids]


def _sample_lanes(sample: dict, lane_order: list) -> list:
    """1サンプルのpartsをlane_order(固定順)へ写像した[(score, is_own)]を返す。
    そのサンプルに居ないlaneはscore=0(セグメント幅0)で詰める。"""
    by_id = {pt.get("id"): (pt.get("score") or 0) for pt in (sample.get("parts") or [])}
    return [(by_id.get(pid, 0), is_own) for pid, is_own in lane_order]


def _build_score_bar_dialogues(battles: list, to_media, video_duration: Optional[float],
                               width: int, height: int, hold_seconds: float = 0.0) -> list:
    """TikTok風のBattleスコアバーをASS dialogueで描く。Battle中だけ画面上部に
    自陣(左)/敵陣(右)の2分割バーを表示し、score_seriesの各点を映像timeへ写像して
    時系列で更新する(数値・境界が動く)。member別の時系列dataは無いため2分割で描画する。

    残り時間のcountdownはscore sampleと切り離し1秒刻みで描く(sample間隔に依らない)。
    Battle終了後も``hold_seconds``だけ最終スコアと勝敗を残す(勝利タイム表示)。保持は
    次Battleの開始・動画終端で打ち切る。"""
    upper = video_duration if video_duration is not None else float("inf")
    mx = int(round(width * SCORE_BAR_MARGIN))
    left, right = mx, width - mx
    track_w = right - left
    bar_h = max(14, int(round(height * SCORE_BAR_H_FRAC)))
    top = int(round(height * SCORE_BAR_TOP))
    radius = bar_h / 2
    cy = top + bar_h / 2
    av_r = max(5, int(round(bar_h * 0.40)))
    pad = max(3, int(round(bar_h * 0.16)))
    gap = max(3, int(round(bar_h * 0.18)))
    num_fs = max(10, int(round(bar_h * 0.54)))
    meta_fs = max(9, int(round(bar_h * 0.46)))
    ini_fs = max(7, int(round(av_r * 1.05)))
    bord = max(1, int(round(bar_h * 0.06)))
    meta_y = int(round(top - bar_h * 0.5))

    own_c, opp_c, track_c = _ass_bgr(_SCORE_OWN_RGB), _ass_bgr(_SCORE_OPP_RGB), _ass_bgr(_SCORE_TRACK_RGB)
    opp_palette_c = [_ass_bgr(c) for c in _SCORE_OPP_PALETTE]
    own_cx = left + pad + av_r
    opp_cx = right - pad - av_r
    own_num_x = own_cx + av_r + gap
    opp_num_x = opp_cx - av_r - gap

    def shape(layer, start, end, color, path, alpha=""):
        return (f"Dialogue: {layer},{_ass_timestamp(start)},{_ass_timestamp(end)},Score,,0,0,0,,"
                f"{{\\an7\\pos(0,0)\\bord0\\shad0\\1c{color}{alpha}\\p1}}{path}")

    def text(layer, start, end, x, y, an, fs, body):
        return (f"Dialogue: {layer},{_ass_timestamp(start)},{_ass_timestamp(end)},Score,,0,0,0,,"
                f"{{\\an{an}\\pos({x},{y})\\fs{fs}\\b1\\1c&H00FFFFFF&\\3c&H00000000&\\bord{bord}\\shad1}}{body}")

    def disc(layer, start, end, cx, color):
        return (f"Dialogue: {layer},{_ass_timestamp(start)},{_ass_timestamp(end)},Score,,0,0,0,,"
                f"{{\\an7\\pos({cx - av_r},{int(round(cy - av_r))})\\1c{color}\\3c&H00FFFFFF&"
                f"\\bord{bord}\\shad0\\p1}}{_circle_path(av_r)}")

    cyi = int(round(cy))
    out: list = []

    def emit_bar(start, end, own, opp):
        """One fill pair (moving split) + the two numbers for [start, end]."""
        own = max(0, own)
        opp = max(0, opp)
        tot = own + opp
        split = left + (track_w * own / tot if tot else track_w / 2)
        if split - left >= 2:
            out.append(shape(8, start, end, own_c,
                             _round_rect_path(left, top, split - left, bar_h, radius, True, False)))
        if right - split >= 2:
            out.append(shape(8, start, end, opp_c,
                             _round_rect_path(split, top, right - split, bar_h, radius, False, True)))
        out.append(text(8, start, end, own_num_x, cyi, 4, num_fs, f"{own:,}"))
        out.append(text(8, start, end, opp_num_x, cyi, 6, num_fs, f"{opp:,}"))

    seg_sep = max(2, int(round(bar_h * 0.05)))

    def emit_lanes(start, end, lanes):
        """個人マルチ(3コラ+): 1本のバーを各参加者のscore比でN分割し、各segment内に
        scoreを描く。色は陣営(segment)ごとに変える: 自分=own色、相手は出現順(score降順)に
        opp_palette_cの別色で塗り分け、自分を強調する。``lanes`` は左→右の固定順
        [(score, is_own), ...]。全score=0なら均等割り。"""
        n = len(lanes)
        if n == 0:
            return
        weights = [max(0, s) for s, _ in lanes]
        tot = sum(weights)
        if tot <= 0:
            weights, tot = [1] * n, n
        avail = track_w - seg_sep * (n - 1)
        x = float(left)
        opp_i = 0
        for i, (w_score, (score, is_own)) in enumerate(zip(weights, lanes)):
            seg_w = avail * w_score / tot
            if is_own:
                seg_c = own_c
            else:
                seg_c = opp_palette_c[opp_i % len(opp_palette_c)]
                opp_i += 1
            if seg_w >= 2:
                out.append(shape(8, start, end, seg_c,
                                 _round_rect_path(x, top, seg_w, bar_h, radius, i == 0, i == n - 1)))
            if seg_w >= 8:
                label = f"{max(0, score):,}"
                # 狭いsegmentでも収まるよう数字fontをsegment幅に合わせて縮める。
                fs = min(num_fs, max(8, int(seg_w / (len(label) * 0.62))))
                out.append(text(8, start, end, int(round(x + seg_w / 2)), cyi, 5, fs, label))
            x += seg_w + seg_sep

    # Resolve each battle's media window first, so the post-battle hold can be
    # clamped to the next battle's start (two bars never overlap).
    wins: list = []
    for battle in battles:
        if battle.get("aborted"):
            continue
        series = battle.get("score_series") or []
        if not series:
            continue
        end_wall = battle.get("end_time") or series[-1].get("t")
        win_start = max(0.0, to_media(series[0].get("t") or 0))
        win_end = to_media(end_wall) if end_wall else to_media(series[-1].get("t") or 0)
        if win_end <= win_start:
            win_end = win_start + COMMENT_END_HOLD_SECONDS
        wins.append([win_start, win_end, battle, series])
    wins.sort(key=lambda w: w[0])

    for idx, (win_start, win_end, battle, series) in enumerate(wins):
        # Post-battle hold (victory time): keep the final bar up for hold_seconds,
        # but never into the next battle or past the video end.
        disp_end = win_end + max(0.0, hold_seconds)
        if idx + 1 < len(wins):
            disp_end = min(disp_end, wins[idx + 1][0])
        if upper != float("inf"):
            win_start, win_end, disp_end = min(win_start, upper), min(win_end, upper), min(disp_end, upper)
        if disp_end <= win_start:
            continue

        parts = battle.get("participants") or []
        mode = _ass_escape(_battle_mode_label(battle))
        # 個人マルチ(3コラ+)は参加者ごとのlaneにN分割。1v1・チーム戦、及びparts時系列を
        # 持たない旧dataは従来どおり自陣/敵陣の2分割へfallbackする。
        lane_order = _personal_lane_order(series) if battle.get("type") != "team" else []
        multi = bool(lane_order)

        # Static elements over the whole visible span (battle + hold).
        out.append(shape(7, win_start, disp_end, track_c,
                         _round_rect_path(left, top, track_w, bar_h, radius), alpha="\\1a&H45&"))
        if not multi:
            # 端のavatar disc/イニシャルは2分割表示のみ。N分割は各segmentに数値を描く。
            own_p = next((p for p in parts if p.get("is_own")), None)
            opp_p = max((p for p in parts if p.get("side") == "opp" and not p.get("is_own")),
                        key=lambda p: p.get("score", 0) or 0, default=None)
            # Strip invisible bidi/control chars before taking the initial so a
            # nickname leading with one does not yield a tofu box as the disc letter.
            own_ini = _ass_escape((_strip_bidi_controls((own_p or {}).get("nickname")).strip()[:1] or "自")).upper()
            opp_ini = _ass_escape((_strip_bidi_controls((opp_p or {}).get("nickname")).strip()[:1] or "敵")).upper()
            out.append(disc(9, win_start, disp_end, own_cx, own_c))
            out.append(disc(9, win_start, disp_end, opp_cx, opp_c))
            out.append(text(9, win_start, disp_end, own_cx, cyi, 5, ini_fs, own_ini))
            out.append(text(9, win_start, disp_end, opp_cx, cyi, 5, ini_fs, opp_ini))
        out.append(text(9, win_start, disp_end, left, meta_y, 4, meta_fs, mode))

        # Fills + numbers per score sample (battle phase: scores change discretely).
        n = len(series)
        for i, sm in enumerate(series):
            s_pts = max(win_start, to_media(sm.get("t") or 0))
            e_pts = min(win_end, to_media(series[i + 1].get("t") or 0) if i + 1 < n else win_end)
            if e_pts <= s_pts:
                continue
            if multi:
                emit_lanes(s_pts, e_pts, _sample_lanes(sm, lane_order))
            else:
                emit_bar(s_pts, e_pts, sm.get("own") or 0, sm.get("opp") or 0)

        # Countdown clock, 1-second steps (decoupled from the sample cadence).
        steps = 0
        t = win_start
        while t < win_end - 1e-6 and steps < _SCORE_CLOCK_MAX_STEPS:
            seg_end = min(t + 1.0, win_end)
            out.append(text(9, t, seg_end, right, meta_y, 6, meta_fs, _fmt_clock(win_end - t)))
            t += 1.0
            steps += 1

        # Victory-time hold: freeze the final score and show the result.
        if disp_end > win_end + 1e-6:
            if multi:
                emit_lanes(win_end, disp_end, _sample_lanes(series[-1], lane_order))
            else:
                fown = max(0, battle.get("own_score") or (series[-1].get("own") or 0))
                fopp = max(0, battle.get("opp_score") or (series[-1].get("opp") or 0))
                emit_bar(win_end, disp_end, fown, fopp)
            result = {"win": "WIN", "lose": "LOSE", "draw": "DRAW"}.get(battle.get("result"), "0:00")
            out.append(text(9, win_end, disp_end, right, meta_y, 6, meta_fs, result))
    return out


def _build_bonus_dialogues(battles: list, to_media, video_duration: Optional[float],
                           width: int, height: int) -> list:
    """Match Bonus Mission（倍率タイム）をスコアバー直下に焼き込む。該当時間帯のみ表示:
    予告(まもなく×N) → ミッション期間(達成で×N) → 達成(×N解放) → 倍率期間(×Nのcountdown帯)
    → 確定(獲得ボーナス💎を数秒)。時刻はevent実値の絶対timestamp(preview/task/reward_start_ts)を
    映像timeへ写像する。ミッション帯の終端はtask_durationで確定したミッション実終了(mission_end)で、
    倍率開始ではない。達成〜倍率開始のsettle gapは達成beatで埋め、各帯の境界がズレないようにする。
    progressの逐次系列は保持していないため、ミッション帯はlabelのみ(barは倍率期間で描く)。"""
    upper = video_duration if video_duration is not None else float("inf")
    mx = int(round(width * BONUS_BAND_MARGIN))
    left, right = mx, width - mx
    track_w = right - left
    band_h = max(12, int(round(height * BONUS_BAND_H_FRAC)))
    top = int(round(height * BONUS_BAND_TOP))
    radius = band_h / 2
    cyi = int(round(top + band_h / 2))
    fs = max(9, int(round(band_h * 0.60)))
    gold, hot, track_c = _ass_bgr(_BONUS_GOLD_RGB), _ass_bgr(_BONUS_HOT_RGB), _ass_bgr(_BONUS_TRACK_RGB)

    def shape(layer, start, end, color, path, alpha=""):
        return (f"Dialogue: {layer},{_ass_timestamp(start)},{_ass_timestamp(end)},Score,,0,0,0,,"
                f"{{\\an7\\pos(0,0)\\bord0\\shad0\\1c{color}{alpha}\\p1}}{path}")

    def text(layer, start, end, x, an, body, color="&H00FFFFFF&", size=None):
        return (f"Dialogue: {layer},{_ass_timestamp(start)},{_ass_timestamp(end)},Score,,0,0,0,,"
                f"{{\\an{an}\\pos({x},{cyi})\\fs{size or fs}\\b1\\1c{color}\\3c&H00000000&\\bord2\\shad1}}{body}")

    out: list = []

    def band(start_ts, end_ts, body, color, alpha):
        """[start_ts,end_ts]を映像timeへ写像し、トラック帯+中央テキストを1本描く。"""
        ms = max(0.0, to_media(start_ts))
        me = min(upper, to_media(end_ts))
        if me <= ms:
            return
        out.append(shape(6, ms, me, track_c,
                         _round_rect_path(left, top, track_w, band_h, radius), alpha=alpha))
        out.append(text(7, ms, me, (left + right) // 2, 5, _ass_escape(body), color=color))

    for battle in battles:
        if battle.get("aborted"):
            continue
        for m in battle.get("bonus_missions") or []:
            mult = m.get("multiplier") or 0
            tag = f"x{mult}" if mult else "BONUS"
            preview_s = m.get("preview_start_ts")
            task_s = m.get("task_start_ts")
            task_dur = m.get("task_duration") or 0
            reward_s = m.get("reward_start_ts")
            reward_dur = m.get("reward_duration") or 0
            achieved = bool(m.get("achieved"))

            # ミッションの実終了時刻: task_durationで確定。無ければ倍率開始へfallbackする。
            # reward_sがあれば必ずそれ以前へ丸める(倍率帯と重ねない)。
            mission_end = (task_s + task_dur) if (task_s and task_dur) else reward_s
            if mission_end and reward_s:
                mission_end = min(mission_end, reward_s)

            # ① 予告: ミッション開始前。これから来る倍率を告知する(該当区間のみ)。
            if preview_s and task_s and task_s > preview_s:
                band(preview_s, task_s, f"BONUS MISSION  まもなく {tag}", gold, "\\1a&H50&")

            # ② ミッション期間: 進捗の逐次値は持たないため目標(達成で×N)を提示する。終端は
            #    倍率開始ではなくミッション実終了(mission_end)。以前はreward開始まで延ばしており
            #    達成〜倍率開始のsettle gap分だけ「達成で」表示が後ろへズレていた。
            if task_s and mission_end and mission_end > task_s:
                band(task_s, mission_end, f"BONUS MISSION  達成で {tag}", gold, "\\1a&H40&")

            # ③ 達成: ミッション終了〜倍率開始(settle)を、達成済みなら達成beatで埋める。
            #    この区間を②の「達成で(=未達成)」で跨がせないことがズレ解消の要点。
            if achieved and reward_s and mission_end and reward_s > mission_end:
                band(mission_end, reward_s, f"達成  {tag} 解放", gold, "\\1a&H28&")

            # ④ 倍率期間: ×N のcountdown帯(残り時間で減るfill)。最も目立たせる。
            if reward_s and reward_dur:
                rs = max(0.0, to_media(reward_s))
                re_ = min(upper, to_media(reward_s + reward_dur))
                span = re_ - rs
                if span > 0:
                    out.append(shape(6, rs, re_, track_c,
                                     _round_rect_path(left, top, track_w, band_h, radius), alpha="\\1a&H30&"))
                    steps, t = 0, rs
                    while t < re_ - 1e-6 and steps < _SCORE_CLOCK_MAX_STEPS:
                        seg_end = min(t + 1.0, re_)
                        ratio = max(0.0, (re_ - t) / span)
                        fill_w = track_w * ratio
                        if fill_w >= 2:
                            out.append(shape(7, t, seg_end, hot,
                                             _round_rect_path(left, top, fill_w, band_h, radius)))
                        out.append(text(8, t, seg_end, (left + right) // 2, 5,
                                        f"GIFT {tag}  {_fmt_clock(re_ - t)}"))
                        t += 1.0
                        steps += 1

                # 確定: 獲得ボーナスを数秒フラッシュ。
                bonus_sum = m.get("bonus_sum") or 0
                if bonus_sum:
                    fs_end = min(upper, re_ + BONUS_SETTLE_HOLD)
                    if fs_end > re_:
                        out.append(shape(6, re_, fs_end, track_c,
                                         _round_rect_path(left, top, track_w, band_h, radius), alpha="\\1a&H30&"))
                        out.append(text(7, re_, fs_end, (left + right) // 2, 5,
                                        f"BONUS +{bonus_sum:,}", color=gold))
    return out


def _build_ass(events: list, started_at: float, ended_at: Optional[float], video_duration: Optional[float],
               width: int, height: int, cfg: dict, anchors: Optional[list] = None,
               avatar_dir: Optional[Path] = None,
               wide_em: float = NOMINAL_WIDE_EM, narrow_em: float = NOMINAL_NARROW_EM,
               pts_gaps: Optional[list] = None,
               battles: Optional[list] = None,
               use_comment_layer: bool = True,
               time_source: str = "arrival",
               debug_sink: Optional[list] = None,
               media_pts: Optional[list] = None) -> tuple[str, list, dict, Optional[dict]]:
    comment_fs = _comment_font(cfg, height)
    icon_px = _icon_px(cfg, height)
    coin_fs = max(10, int(round(height * COIN_REF_PX / BASE_HEIGHT)))
    outline = max(1, int(round(comment_fs * 0.08)))
    upper = video_duration if video_duration is not None else float("inf")
    # Mode A (arrival): place every timestamp through the consumer-arrival wall->pts
    # map. Mode B (server): place events by their TikTok create_time and the battle
    # score series via the create_time bridge, so comments/battle lock to the source
    # clock instead of drifting with the arrival path. The battle bonus windows are
    # already source-epoch, so they map through source_to_pts in both senses.
    to_media = _make_time_mapper(anchors, started_at, ended_at, video_duration, pts_gaps, media_pts)
    source = None
    if time_source == "server":
        source = _make_source_mappers(events, anchors, started_at, ended_at, video_duration, pts_gaps, media_pts)
        if source is None:
            logger.warning(
                "overlay Mode B requested but no live create_time to anchor on; "
                "Mode B output is unavailable for this recording"
            )
        else:
            logger.info(
                "overlay Mode B anchored: C=%.3f on %d/%d live events (%d backlog excluded)",
                source["c_value"], source["n_anchor"], source["n_samples"], source["n_backlog"],
            )
    # event placement on the mp4 timeline. Mode B uses create_time (source clock);
    # an event without create_time cannot be source-placed and is dropped (counted),
    # never silently re-timed onto the arrival axis.
    to_score = to_media if source is None else source["wall_to_pts"]
    # Bonus窓のtimestampはModeに依らずsource epochなので、Mode Aでもsource橋を
    # 建ててsource_to_ptsで置く(壁時計mapperに入れると到着遅延ぶん早くズレる)。
    # 橋が建たない(live create_time皆無)場合のみ従来の到着軸に置く。
    bonus_source = source
    if bonus_source is None:
        bonus_source = _make_source_mappers(
            events, anchors, started_at, ended_at, video_duration, pts_gaps, media_pts
        )
        if bonus_source is None:
            logger.warning(
                "no live create_time to anchor bonus windows; placing them on the arrival axis"
            )
    to_bonus = to_media if bonus_source is None else bonus_source["source_to_pts"]
    dropped_no_ct = 0

    def event_offset(ev) -> Optional[float]:
        if time_source != "server":
            return to_media(ev["time"] or 0) + delay
        if source is None:
            return None
        ct = ev.get("create_time")
        if ct is None:
            return None
        return source["source_to_pts"](ct) + delay

    comments: list[dict] = []
    gifts: list[dict] = []
    min_diamonds = cfg["video_overlay_gift_min_diamonds"]
    delay = cfg.get("video_overlay_comment_delay_seconds") or 0
    for event in events:
        # Place the event on the video timeline (not wall-clock) so comments/gifts
        # stay locked to the footage; ``delay`` then nudges by a user offset.
        offset = event_offset(event)
        if offset is None:
            dropped_no_ct += 1
            continue
        if debug_sink is not None and event.get("kind") in ("comment", "gift"):
            debug_sink.append({
                "kind": event.get("kind"),
                "time": event.get("time"),
                "create_time": event.get("create_time"),
                "offset_arrival": round(to_media(event["time"] or 0) + delay, 3),
                "offset": round(offset, 3),
                "nick": event.get("user_nickname") or "",
                "text": (event.get("comment") or event.get("text") or "")[:80],
            })
        if offset < 0 or offset > upper:
            continue
        kind = event["kind"]
        if kind == "comment" and cfg["video_overlay_comments"]:
            body = event.get("comment") or event.get("text") or ""
            if body:
                comments.append({
                    "offset": offset,
                    "nick": event.get("user_nickname") or "",
                    "user_id": event.get("user_unique_id") or event.get("user_nickname") or "",
                    "text": body,
                })
        elif kind == "gift" and cfg["video_overlay_gifts"]:
            diamonds = event.get("diamonds") or 0
            if diamonds < min_diamonds:
                continue
            gifts.append({
                "offset": offset,
                "nick": event.get("user_nickname") or "",
                "gift_id": event.get("gift_id") or 0,
                "gift_name": event.get("gift_name") or "",
                "count": event.get("gift_count") or 1,
                "diamonds": diamonds,
                "image": event.get("gift_image") or "",
            })

    # Mode B places events by create_time (server clock) while the list is in
    # arrival order, so offsets can be non-monotonic; the feed layout and the
    # gift rail both assume ascending offsets (segment end = next offset), so an
    # inversion would produce End<Start lines that never display. Sort by offset.
    comments.sort(key=lambda c: c["offset"])
    gifts.sort(key=lambda g: g["offset"])

    # Final comments (nothing after to push them up) stay until the recording
    # ends. When the duration is unknown, hold them briefly past the last comment.
    last_offset = comments[-1]["offset"] if comments else 0.0
    comment_end = video_duration if video_duration is not None else last_offset + COMMENT_END_HOLD_SECONDS

    # Real-avatar resolution: a comment whose commenter avatar was cached at
    # capture time gets a composited circular photo (ASS disc omitted for it); the
    # rest keep the initial-letter disc. avatar_files feeds the overlay renderer.
    metrics = _comment_metrics(width, height, comment_fs, wide_em, narrow_em)
    avatar_files: dict = {}
    if avatar_dir is not None and cfg.get("video_overlay_real_avatars"):
        for c in comments:
            uid = c.get("user_id")
            if not uid or uid in avatar_files:
                continue
            cached = avatar_dir / f"{avatar_key(uid)}.img"
            try:
                if cached.is_file() and cached.stat().st_size > 0:
                    avatar_files[uid] = cached
            except OSError:
                continue
    avatar_ids = set(avatar_files)
    # Comments are drawn by the PIL colour-emoji layer when its shaper is available;
    # only then are the ASS comment dialogues suppressed. Without it (Pillow/fonts
    # missing, or an explicit fallback after a layer-render failure) comments fall
    # back to the monochrome ASS feed so they still show.
    shaper = _make_comment_shaper() if (use_comment_layer and cfg["video_overlay_comments"] and comments) else None
    placements = _layout_comment_feed(comments, metrics, comment_fs, comment_end, avatar_ids, shaper)
    comment_lines = [] if shaper is not None else _build_comment_dialogues(placements, metrics)
    drawable_comments = sum(1 for p in placements if not p["empty"])

    # Battle score bar (own/opp, time-mapped). Built before gifts so the gift band
    # can drop below the bar when it is present (avoids overlapping the top strip).
    score_lines: list = []
    bonus_lines: list = []
    if cfg.get("video_overlay_score_bar") and battles:
        score_lines = _build_score_bar_dialogues(
            battles, to_score, video_duration, width, height,
            cfg.get("video_overlay_score_bar_hold_seconds") or 0,
        )
        bonus_lines = _build_bonus_dialogues(battles, to_bonus, video_duration, width, height)
    gift_band_top = SCORE_BAR_GIFT_BAND_TOP if score_lines else GIFT_BAND_TOP

    gift_lines, overlays = _build_gift_layout(
        gifts, width, height, coin_fs, icon_px, cfg["video_overlay_gift_seconds"], wide_em, narrow_em,
        gift_band_top,
    )

    # Bound the number of icon overlays (each adds a filter to ffmpeg) by keeping
    # the highest-diamond gifts; the coin count still shows for dropped ones.
    dropped_icons = 0
    if len(overlays) > MAX_GIFT_OVERLAYS:
        overlays.sort(key=lambda o: o["diamonds"], reverse=True)
        dropped_icons = len(overlays) - MAX_GIFT_OVERLAYS
        overlays = overlays[:MAX_GIFT_OVERLAYS]

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "ScaledBorderAndShadow: yes\n"
        "WrapStyle: 2\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Comment,{COMMENT_FONT},{comment_fs},&H00FFFFFF,&H000000FF,&H90000000,&H64000000,0,0,0,0,"
        f"100,100,0,0,1,{outline},1,1,0,0,0,1\n"
        # BorderStyle 3 = opaque box: a semi-transparent dark card behind the coin
        # count so a gift reads clearly even when its icon could not be resolved.
        f"Style: Gift,{COMMENT_FONT},{coin_fs},&H00FFFFFF,&H000000FF,&H40202020,&H80000000,1,0,0,0,"
        f"100,100,0,0,3,5,0,5,0,0,0,1\n"
        # Score bar: outline style, top-left aligned; per-line overrides set the real
        # font size, colour and position for each shape/number/avatar.
        f"Style: Score,{COMMENT_FONT},20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,"
        f"100,100,0,0,1,2,0,7,0,0,0,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    body = "\n".join(comment_lines + gift_lines + score_lines + bonus_lines)
    stats = {
        # Count drawable comments (not ASS lines) so the "nothing to draw" check holds
        # whether comments render via the PIL layer or the ASS fallback.
        "comments": drawable_comments,
        "gifts": len(gift_lines),
        "score": len(score_lines),
        "bonus": len(bonus_lines),
        "icons": len(overlays),
        "dropped_icons": dropped_icons,
        "avatars": len(avatar_ids),
        "time_source": time_source,
        "source_unavailable": time_source == "server" and source is None,
        "source_diag": {k: source[k] for k in ("c_value", "n_anchor", "n_backlog", "n_samples")} if source else None,
        "dropped_no_create_time": dropped_no_ct,
    }
    comment_plan = None
    if shaper is not None and drawable_comments:
        comment_plan = {
            "placements": placements,
            "metrics": metrics,
            "avatar_files": avatar_files,
            "comment_fs": comment_fs,
            "shaper": shaper,
        }
    return header + body + ("\n" if body else ""), overlays, stats, comment_plan


# Gift list (name/id -> icon URL), fetched once per process and reused to
# auto-resolve icons for recordings whose events have no stored icon URL.
_gift_map_cache: Optional[dict] = None
_gift_map_lock = asyncio.Lock()


async def _load_gift_map() -> dict:
    global _gift_map_cache
    if _gift_map_cache is not None:
        return _gift_map_cache
    async with _gift_map_lock:
        if _gift_map_cache is not None:
            return _gift_map_cache
        by_id: dict[int, tuple] = {}
        by_name: dict[str, tuple] = {}
        try:
            from TikTokLive import TikTokLiveClient

            client = TikTokLiveClient(unique_id="@_tictok_overlay")
            resp = await client.web.fetch_gift_list()
            for g in resp.get("gifts", []):
                url = ((g.get("image") or {}).get("url_list") or [None])[0]
                if not url:
                    continue
                gid = int(g.get("id") or 0)
                name = g.get("name") or ""
                if gid:
                    by_id[gid] = (gid, url)
                if name:
                    by_name[name] = (gid, url)
        except Exception:
            logger.warning("gift list fetch for icon auto-resolve failed", exc_info=True)
        _gift_map_cache = {"by_id": by_id, "by_name": by_name}
        return _gift_map_cache


_name_index_cache: dict[str, dict] = {}


def _load_name_index(cache_dir: Path) -> dict:
    """Gift-name -> gift-id map persisted at capture time (gift_icons names.json),
    used to recover an icon for legacy events that stored a name but no id —
    offline, before any network gift-list fetch."""
    key = str(cache_dir)
    if key in _name_index_cache:
        return _name_index_cache[key]
    index: dict = {}
    path = cache_dir / "names.json"
    try:
        if path.is_file():
            index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("gift name index read failed: %s", path, exc_info=True)
    _name_index_cache[key] = index
    return index


def _cache_file(cache_dir: Path, gift_id: int, url: str) -> Path:
    if gift_id:
        return cache_dir / f"{gift_id}.img"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.img"


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.tiktok.com/"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = resp.read()
    dest.write_bytes(data)


async def _resolve_icons(overlays: list, cache_dir: Path) -> list:
    """Resolve each gift overlay to a local icon file. Cache first — icons are
    persisted at capture time (while URLs are fresh), so an expired URL still
    renders. On a cache miss, auto-resolve the URL from the current gift list by
    id/name (or the stored URL) and persist it. Specs that cannot be resolved are
    dropped; the coin count still shows."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_running_loop()
    name_index = _load_name_index(cache_dir)
    gift_map: Optional[dict] = None
    for spec in overlays:
        gid = int(spec.get("gift_id") or 0)
        name = spec.get("gift_name") or ""
        # 1. persisted cache by gift_id
        if gid:
            cached = cache_dir / f"{gid}.img"
            if cached.is_file() and cached.stat().st_size > 0:
                spec["file"] = cached
                continue
        # 1b. legacy event without id: recover the id from the local name index and
        #     reuse the icon cached by id — no network needed.
        if not gid and name and name in name_index:
            gid = int(name_index[name] or 0)
            if gid:
                cached = cache_dir / f"{gid}.img"
                if cached.is_file() and cached.stat().st_size > 0:
                    spec["file"] = cached
                    continue
        # 2. need a URL: the stored one, else auto-resolve from the gift list
        url = spec.get("url") or ""
        if not url:
            if gift_map is None:
                gift_map = await _load_gift_map()
            entry = gift_map["by_id"].get(gid) or gift_map["by_name"].get(spec.get("gift_name") or "")
            if entry:
                gid = gid or entry[0]
                url = entry[1]
        if not url:
            continue
        dest = _cache_file(cache_dir, gid, url)
        if dest.is_file() and dest.stat().st_size > 0:
            spec["file"] = dest
            continue
        try:
            await loop.run_in_executor(None, _download, url, dest)
            if dest.stat().st_size > 0:
                spec["file"] = dest
        except (OSError, ValueError):
            logger.warning("gift icon download failed (id=%s): %s", gid, url, exc_info=True)
            dest.unlink(missing_ok=True)
    return [s for s in overlays if s.get("file")]


# Frames-per-second of the rendered comment overlay layer. The feed is a slow
# scroll, so the layer is sampled at the source fps (capped here to bound the
# per-frame render cost on long recordings); ffmpeg composites it by PTS so a lower
# layer fps than the video still aligns at each sampled instant.
COMMENT_LAYER_FPS_CAP = 30
COMMENT_LAYER_SUFFIX = ".comments.mov"
# Supersample factor for the circular avatar mask: the mask is drawn this many
# times larger than the final avatar and downscaled, antialiasing the edge.
AVATAR_MASK_SS = 4

# Unsharp mask applied after the avatar downscale. The only obtainable source is
# TikTok's 72x72 compressed thumb (events never populate avatar_medium/large), so
# the disc drawn at comment size looks soft; a mild sharpen restores edge contrast
# without amplifying the thumb's webp noise (threshold skips near-flat areas).
# Radius scales with the drawn diameter so the effect is resolution-independent.
AVATAR_SHARPEN_RADIUS_FRAC = 1 / 36
AVATAR_SHARPEN_PERCENT = 130
AVATAR_SHARPEN_THRESHOLD = 2


def _circle_avatar(path: Path, diameter: int):
    """Load a cached avatar, center-crop to square, resize, sharpen, and apply a
    circular alpha mask. Returns an RGBA PIL image, or None if it cannot be decoded."""
    from PIL import Image, ImageDraw, ImageFilter

    try:
        img = Image.open(path).convert("RGBA")
    except Exception:
        logger.warning("avatar image decode failed: %s", path, exc_info=True)
        return None
    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    img = img.crop((left, top, left + side, top + side)).resize((diameter, diameter), Image.LANCZOS)
    # Sharpen before the circular mask so the alpha edge (antialiased below) is
    # untouched — sharpening after masking would put halos on the disc rim.
    img = img.filter(ImageFilter.UnsharpMask(
        radius=max(1.0, diameter * AVATAR_SHARPEN_RADIUS_FRAC),
        percent=AVATAR_SHARPEN_PERCENT,
        threshold=AVATAR_SHARPEN_THRESHOLD,
    ))
    # Draw the mask at AVATAR_MASK_SS× the final size and downscale it, so the
    # circular edge is antialiased; a mask drawn straight at this small diameter
    # leaves a visibly jagged (stair-stepped) edge.
    big = diameter * AVATAR_MASK_SS
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    mask = mask.resize((diameter, diameter), Image.LANCZOS)
    out = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _draw_comment_line(draw, layer, shaper: "_CommentShaper", line: str,
                       x: float, y: int, line_h: int, fs: int, color: tuple) -> None:
    """Draw one comment line as mixed text/colour-emoji runs at (x, y). Text runs are
    stroked dark for legibility over video; emoji runs are pasted as colour tiles
    centred vertically within the line."""
    font = shaper.text_font(fs)
    emoji_px = shaper.emoji_px(fs)
    asc, desc = font.getmetrics()
    ty = y + max(0, (line_h - (asc + desc)) // 2)
    # Fallback fonts have their own ascent, so text runs are anchored on a shared
    # baseline (the primary font's) — drawing every run at the same top edge would
    # leave glyphs of differing fonts vertically misaligned.
    baseline = ty + asc
    sw = max(1, int(round(fs * 0.07)))
    cx = float(x)
    for kind, s in _tokenize_emoji(line):
        if kind == "emoji":
            tile = shaper.emoji_tile(s, emoji_px)
            ey = y + max(0, (line_h - tile.height) // 2)
            layer.alpha_composite(tile, (int(round(cx)), ey))
            cx += tile.width
        else:
            for run_font, sub in shaper.font_runs(s, fs):
                draw.text((int(round(cx)), baseline), sub, font=run_font, fill=color,
                          anchor="ls", stroke_width=sw, stroke_fill=(0, 0, 0, 180))
                cx += run_font.getlength(sub)


def _render_comment_tile(p: dict, m: dict, shaper: "_CommentShaper", fs: int, tile_w: int):
    """Render one comment block (avatar/initial disc + username + wrapped body, with
    colour emoji) into an RGBA image of size (tile_w, block_h). Drawn once per comment
    and scrolled by the layer loop, so per-frame cost stays low."""
    from PIL import Image, ImageDraw

    line_h, x_left, x_text = m["line_h"], m["x_left"], m["x_text"]
    avatar_r, avatar_d, avatar_off = m["avatar_r"], m["avatar_d"], m["avatar_off"]
    initial_fs = m["initial_fs"]
    block_h = p["block_h"]
    # The last line is drawn with its box bottom at block_h, but the bundled CJK font's
    # real line height (ascent+descent) exceeds line_h and the stroke extends further
    # below the descender — so a tile exactly block_h tall clips the bottom row's
    # descenders/stroke by a couple of pixels. Pad the tile bottom by the measured
    # overflow (it renders into the inter-comment gap, never over the next comment).
    asc, desc = shaper.text_font(fs).getmetrics()
    stroke = max(1, int(round(fs * 0.07)))
    bottom_pad = max(0, (asc + desc + stroke) - line_h)
    tile = Image.new("RGBA", (tile_w, block_h + bottom_pad), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)

    # Avatar: real circular photo when available, else an initial-letter colour disc
    # (the same fallback the app uses elsewhere).
    avatar_img = p.get("_avatar_img")
    if p["has_avatar"] and avatar_img is not None:
        tile.alpha_composite(avatar_img, (x_left, avatar_off))
    else:
        col = _ass_color_to_rgb(p["color"]) + (255,)
        draw.ellipse((x_left, avatar_off, x_left + avatar_d - 1, avatar_off + avatar_d - 1), fill=col)
        ifont = shaper.text_font(initial_fs)
        draw.text((x_left + avatar_r, avatar_off + avatar_r), p["initial"], font=ifont,
                  fill=(255, 255, 255, 255), anchor="mm",
                  stroke_width=max(1, initial_fs // 12), stroke_fill=(0, 0, 0, 160))

    # Username (line 1, warm accent) then the wrapped body (white) to the avatar's right.
    _draw_comment_line(draw, tile, shaper, p["nick_disp"], x_text, 0, line_h, fs, (255, 224, 124, 255))
    y = line_h
    for ln in p["body_lines"]:
        _draw_comment_line(draw, tile, shaper, ln, x_text, y, line_h, fs, (255, 255, 255, 255))
        y += line_h
    return tile


# Per-alpha-step attenuation LUTs for the positional/fade-in dimming of comment
# tiles. Building the 256-entry table once per distinct quantised alpha (there are
# at most 256) and reusing it across frames/tiles removes the per-frame Python
# lambda LUT build the fade previously did for every dimmed tile every composited
# frame. Bounded to <=256 entries (<=64 KiB total), so it is a module-level cache.
_ALPHA_LUTS: dict[int, bytes] = {}


def _alpha_lut(aq: int) -> bytes:
    """256-entry byte LUT scaling an alpha channel by ``aq``/255 (aq in 0..255)."""
    lut = _ALPHA_LUTS.get(aq)
    if lut is None:
        lut = bytes((v * aq) // 255 for v in range(256))
        _ALPHA_LUTS[aq] = lut
    return lut


def _render_comment_layer_sync(placements: list, avatar_files: dict, m: dict, fs: int,
                               shaper: "_CommentShaper", width: int, height: int, fps: float,
                               out_path: Path) -> Optional[tuple]:
    """Render the whole comment feed as an alpha overlay video (qtrle .mov) using
    Pillow so emoji show in colour. Each comment is rasterised once to a tile and
    scrolled/faded using the same placements/timing the ASS layer would have used, so
    comments stay locked to the footage. Only the bottom-left comment band is rendered
    and composited as a single ffmpeg overlay regardless of comment count. Returns
    (out_path, overlay_x, overlay_y) or None when there is nothing to draw."""
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow not installed; cannot render comment layer")
        return None

    avatar_d, line_h = m["avatar_d"], m["line_h"]
    x_text, text_max_w, gap = m["x_text"], m["text_max_w"], m["gap"]

    circ: dict = {}
    for uid, path in avatar_files.items():
        im = _circle_avatar(Path(path), avatar_d)
        if im is not None:
            circ[uid] = im

    # The band is the left COMMENT_WIDTH_FRAC of the frame; render just that column
    # and overlay it back at (0, region_y0) so the rest of the frame stays untouched.
    region_x = 0
    region_w = min(width, x_text + text_max_w + gap)
    region_y0 = max(0, m["band_top"] - line_h)
    drawable = [p for p in placements if not p["empty"] and p.get("segments")]
    if not drawable:
        return None
    max_block = max(p["block_h"] for p in drawable)
    region_h = min(height - region_y0, (m["y_bottom"] + max_block) - region_y0)
    if region_w <= 0 or region_h <= 0:
        return None

    # One rendered tile per comment, plus the scroll segments referencing it. Each
    # segment: (tile, start, end, prev_top, top, fad_in_ms, grad).
    segments: list = []
    layer_end = 0.0
    for p in drawable:
        if p["has_avatar"]:
            p["_avatar_img"] = circ.get(p["uid"])
            if p["_avatar_img"] is None:
                p["has_avatar"] = False  # photo missing/undecodable → initial disc
        tile = _render_comment_tile(p, m, shaper, fs, region_w)
        for seg in p["segments"]:
            segments.append((tile, seg["start"], seg["end"], seg["prev_top"],
                             seg["top"], seg["fad_in"], seg["grad"]))
            layer_end = max(layer_end, seg["end"])
    if not segments:
        return None
    segments.sort(key=lambda seg: seg[1])

    slide = SLIDE_SECONDS / 2.0  # seconds; matches slide_cs (ms) in the ASS \move
    n_frames = int(math.ceil(layer_end * fps)) + 1

    def frame_state(t: float, live: list):
        """Draw ops + a content signature for time ``t``. The signature captures every
        visible tile's quantised position and alpha, so an unchanged signature means a
        pixel-identical frame — letting the loop skip recompositing through the long
        static stretches between comments (only slides/fade-ins actually change)."""
        ops: list = []
        sig: list = []
        for tile, s, e, prev_top, top, fad_in, grad in live:
            if t < s:
                continue
            cur_top = top if (slide <= 0 or t >= s + slide) else prev_top + (top - prev_top) * ((t - s) / slide)
            alpha = grad
            if fad_in and t < s + fad_in / 1000.0:
                alpha = min(alpha, (t - s) / (fad_in / 1000.0))
            y = int(round(cur_top - region_y0))
            ops.append((tile, y, alpha))
            sig.append((id(tile), y, int(alpha * 255)))
        return tuple(sig), ops

    # Frames are streamed as raw RGBA to a qtrle encoder (constant memory — nothing
    # accumulates on disk, which matters for multi-hour recordings). The feed is
    # static except during each comment's brief slide/fade-in, so a frame whose
    # content signature matches the previous one re-sends the cached bytes instead of
    # recompositing — removing the per-frame pixel work across the static stretches.
    proc = subprocess.Popen(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "rgba", "-video_size", f"{region_w}x{region_h}",
         "-framerate", f"{fps:.6f}", "-i", "-",
         "-c:v", "qtrle", "-pix_fmt", "argb", str(out_path)],
        stdin=subprocess.PIPE,
    )
    ptr = 0
    live: list = []
    prev_sig = None
    prev_bytes: Optional[bytes] = None
    composited = 0
    try:
        for f in range(n_frames):
            t = f / fps
            while ptr < len(segments) and segments[ptr][1] <= t:
                live.append(segments[ptr])
                ptr += 1
            if live:
                live = [seg for seg in live if seg[2] > t]
            sig, ops = frame_state(t, live)
            if sig == prev_sig and prev_bytes is not None:
                proc.stdin.write(prev_bytes)
                continue
            layer = Image.new("RGBA", (region_w, region_h), (0, 0, 0, 0))
            for tile, y, alpha in ops:
                draw_tile = tile
                if alpha < 0.999:
                    draw_tile = tile.copy()
                    draw_tile.putalpha(tile.getchannel("A").point(_alpha_lut(int(alpha * 255))))
                layer.alpha_composite(draw_tile, (region_x, y))
            prev_bytes = layer.tobytes()
            prev_sig = sig
            composited += 1
            proc.stdin.write(prev_bytes)
        proc.stdin.close()
        proc.wait()
    except Exception:
        logger.warning("comment layer render failed", exc_info=True)
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        except OSError:
            pass
        proc.wait()
        out_path.unlink(missing_ok=True)
        return None
    if proc.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        logger.warning(
            "comment layer encoder failed (rc=%s, output_exists=%s)",
            proc.returncode, out_path.exists(),
        )
        out_path.unlink(missing_ok=True)
        return None
    logger.info("comment layer: %d/%d frames composited (rest cached)", composited, n_frames)
    return out_path, region_x, region_y0


async def _render_comment_layer(placements: list, avatar_files: dict, m: dict, fs: int,
                                shaper: "_CommentShaper", width: int, height: int, fps: float,
                                out_path: Path) -> Optional[tuple]:
    """Async wrapper: the PIL/ffmpeg render is blocking, so run it off the loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _render_comment_layer_sync,
        placements, avatar_files, m, fs, shaper, width, height, fps, out_path,
    )


def _build_filter_complex(overlays: list, icon_px: int, ass_name: str, layer_input: Optional[int] = None,
                          layer_y: int = 0, scale_to: Optional[tuple] = None,
                          cfr_fps: Optional[float] = None) -> str:
    """Build the ffmpeg filter graph: scale each unique icon once, split it into
    one stream per instance, then slide each instance in/out over its window. When
    ``scale_to`` is given, the source frame is first upscaled to that (w, h) so the
    overlays — authored at the same render resolution — composite crisply onto it.
    When ``cfr_fps`` is given (VFR source), the base is normalised to that constant
    frame rate in this same graph so the comment layer stays time-locked, avoiding a
    separate full re-encode pass. The ``fps`` filter preserves each frame's time
    position (it only regularises spacing), so the overlay/ASS timeline — computed in
    the source mp4's PTS seconds — still aligns with the normalised base."""
    by_file: dict[str, list] = {}
    for spec in overlays:
        by_file.setdefault(str(spec["file"]), []).append(spec)

    parts: list[str] = []
    base_label = "[0:v]"
    # Scale before fps so only the real (fewer) VFR frames are resampled; the fps
    # filter then duplicates the already-scaled frames (a cheap reference copy) up to
    # the constant rate. Both filters preserve the PTS timeline, so ordering is a
    # cost choice only.
    base_filters: list[str] = []
    if scale_to is not None:
        sw, sh = scale_to
        base_filters.append(f"scale={sw}:{sh}:flags=lanczos")
    if cfr_fps is not None:
        base_filters.append(f"fps={cfr_fps:.6f}")
    if base_filters:
        parts.append(f"[0:v]{','.join(base_filters)}[base]")
        base_label = "[base]"
    label_queue: dict[str, list] = {}
    input_index = 1  # [0] is the source video
    for file in by_file:
        specs = by_file[file]
        count = len(specs)
        base = f"ic{input_index}"
        chain = f"[{input_index}:v]scale={icon_px}:{icon_px},format=rgba"
        if count == 1:
            parts.append(f"{chain}[{base}_0]")
        else:
            outs = "".join(f"[{base}_{k}]" for k in range(count))
            parts.append(f"{chain},split={count}{outs}")
        label_queue[file] = [f"{base}_{k}" for k in range(count)]
        input_index += 1

    cur = base_label
    step = 0
    for spec in overlays:
        label = label_queue[str(spec["file"])].pop(0)
        s, e, x = spec["start"], spec["end"], spec["x_rest"]
        fi = f"clip((t-{s})/{SLIDE_SECONDS}\\,0\\,1)"
        fo = f"clip(({e}-t)/{SLIDE_SECONDS}\\,0\\,1)"
        xexpr = f"{-icon_px - 20}+({x + icon_px + 20})*min({fi}\\,{fo})"
        out = f"[v{step}]"
        parts.append(
            f"{cur}[{label}]overlay=x='{xexpr}':y={spec['y']}:"
            f"eof_action=repeat:enable='between(t,{s},{e})'{out}"
        )
        cur = out
        step += 1
    if layer_input is not None:
        # The comment layer is a full alpha overlay covering its band; eof_action
        # pass lets the main video continue once the (shorter) layer ends.
        parts.append(f"{cur}[{layer_input}:v]overlay=x=0:y={layer_y}:eof_action=pass[cl]")
        cur = "[cl]"
    parts.append(f"{cur}ass={ass_name}[vout]")
    return ";".join(parts)


# Encoders per codec family, hardware (GPU) first and CPU last. Each is chosen by
# actually encoding a couple of real frames on this machine — a listed encoder can
# still fail at runtime (no GPU, driver mismatch), so we probe rather than trust
# the build's encoder list. The CPU encoder is the last resort, not a silent error
# mask: a GPU encoder is used whenever it genuinely works.
_ENCODER_CANDIDATES = {
    "av1": ("av1_nvenc", "av1_qsv", "av1_amf", "libsvtav1"),
    "hevc": ("hevc_nvenc", "hevc_qsv", "hevc_amf", "libx265"),
    "h264": ("h264_nvenc", "h264_qsv", "h264_amf", "libx264"),
}
# "auto": the most space-efficient GPU encoder that works here (AV1 > HEVC > H.264),
# else CPU H.264. CPU AV1/HEVC are excluded from auto — they are far too slow for
# multi-hour recordings; an explicit codec choice may still fall back to them.
_AUTO_ENCODER_ORDER = ("av1_nvenc", "hevc_nvenc", "h264_nvenc", "h264_qsv", "h264_amf", "libx264")
# Setting value -> codec family (0 = auto).
_CODEC_CHOICES = {0: "auto", 1: "h264", 2: "hevc", 3: "av1"}
# Per-family (cq/crf offset, max) applied to the user's base video_overlay_quality.
# The base is calibrated on the H.264 scale; HEVC and especially AV1 reach the same
# perceived quality at a higher number, so without this an AV1 render at the H.264
# value would be near-lossless and huge. Offsets are from measured equal-quality
# points on this content; the max clamps to each codec's valid cq range.
_CODEC_QUALITY = {"h264": (0, 51), "hevc": (4, 51), "av1": (16, 63)}

_resolved_encoders: dict[str, str] = {}
_video_encoder_lock = asyncio.Lock()


def codec_family(setting_value) -> str:
    """Map the ``video_overlay_codec`` setting value to a codec family accepted by
    ``video_encoder_name`` (0/unknown = auto)."""
    return _CODEC_CHOICES.get(int(setting_value or 0), "auto")


def _encoder_family(name: str) -> str:
    if "av1" in name:
        return "av1"
    if "hevc" in name or "x265" in name:
        return "hevc"
    return "h264"


def _probe_encoder_sync(name: str) -> bool:
    # Raw frames, not lavfi ``testsrc``: av1_nvenc rejects the testsrc source on
    # current builds ("no capable devices") yet encodes real frames fine, so
    # testsrc gives a false negative. A zeroed 256x256 yuv420p frame works for all.
    # Use the sync subprocess API: a failing encoder exits before reading stdin, and
    # the stdlib swallows the resulting broken-pipe write (the asyncio proactor would
    # instead leak an unretrieved-future warning on Windows).
    w = h = 256
    frames = (b"\x00" * (w * h * 3 // 2)) * 2
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{w}x{h}", "-framerate", "10",
             "-i", "pipe:0", "-c:v", name, "-f", "null", "-"],
            input=frames,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


async def _probe_encoder(name: str) -> bool:
    """True if ``name`` can actually encode on this machine (probed by piping a
    couple of real raw frames to null). The blocking probe runs off the loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _probe_encoder_sync, name)


async def video_encoder_name(codec: str = "auto") -> str:
    """Resolve the encoder for ``codec`` (auto/h264/hevc/av1) once per process: the
    fastest working encoder for that codec on this machine, else CPU H.264."""
    cached = _resolved_encoders.get(codec)
    if cached is not None:
        return cached
    async with _video_encoder_lock:
        cached = _resolved_encoders.get(codec)
        if cached is not None:
            return cached
        order = _AUTO_ENCODER_ORDER if codec == "auto" else _ENCODER_CANDIDATES.get(codec, ())
        for name in order:
            if await _probe_encoder(name):
                logger.info("video overlay encoder: %s (codec=%s)", name, codec)
                _resolved_encoders[codec] = name
                return name
        # Requested codec unavailable: never fail the render — fall back to H.264.
        logger.warning("no working encoder for codec=%s; falling back to libx264", codec)
        _resolved_encoders[codec] = "libx264"
        return "libx264"


def _mapped_quality(name: str, base_quality: int) -> int:
    """Translate the user's base (H.264-scale) quality to the chosen codec's cq."""
    offset, qmax = _CODEC_QUALITY[_encoder_family(name)]
    return max(0, min(qmax, base_quality + offset))


def _encoder_args(name: str, quality: int) -> list:
    """ffmpeg encode args for the chosen encoder at the given (already codec-mapped)
    quality. Lower quality value = higher quality, larger file."""
    q = str(quality)
    if name in ("h264_nvenc", "hevc_nvenc", "av1_nvenc"):
        return ["-c:v", name, "-preset", "p5", "-rc", "vbr", "-cq", q, "-b:v", "0"]
    if name in ("h264_qsv", "hevc_qsv", "av1_qsv"):
        return ["-c:v", name, "-global_quality", q, "-preset", "slow"]
    if name in ("h264_amf", "hevc_amf", "av1_amf"):
        return ["-c:v", name, "-rc", "cqp", "-qp_i", q, "-qp_p", q, "-quality", "quality"]
    if name == "libsvtav1":
        return ["-c:v", "libsvtav1", "-preset", "8", "-crf", q]
    if name == "libx265":
        return ["-c:v", "libx265", "-preset", "veryfast", "-crf", q]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", q]


async def _probe_duration_us(src: Path) -> Optional[int]:
    """Source duration in microseconds via ffprobe, for encode progress %.
    Returns None when ffprobe is unavailable or the duration can't be read."""
    if not ffprobe_available():
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nokey=1:noprint_wrappers=1", str(src),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        secs = float(out.decode().strip())
    except (ValueError, OSError):
        logger.warning("ffprobe duration probe failed for %s", src, exc_info=True)
        return None
    return int(secs * 1_000_000) if secs > 0 else None


async def _probe_pts_gaps(src: Path) -> list:
    """Forward jumps in the mp4's video PTS, as [(pts_before, pts_after)] ascending.

    A source-timestamp glitch leaves a frozen gap baked into the finalized mp4; the
    comment time map needs the real gap edges to place comments on the correct side
    of it. Only gaps at least PTS_DISCONTINUITY_MIN_SECONDS are reported, so segment
    jitter and the small startup discontinuity are ignored; the time map then matches
    each gap to its media-axis discontinuity by size. Returns [] when ffprobe is
    unavailable or the scan fails."""
    if not ffprobe_available():
        return []
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(src),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
    except OSError:
        logger.warning("ffprobe pts-gap scan failed for %s", src, exc_info=True)
        return []
    if proc.returncode != 0:
        return []
    gaps: list = []
    prev: Optional[float] = None
    for line in out.decode("ascii", "replace").splitlines():
        line = line.strip().rstrip(",")
        if not line:
            continue
        try:
            t = float(line)
        except ValueError:
            continue
        if prev is not None and t - prev >= PTS_DISCONTINUITY_MIN_SECONDS:
            gaps.append((prev, t))
        prev = t
    return gaps


async def _pump_ffmpeg_progress(stream, total_us: int, on_progress: ProgressCb) -> None:
    """Parse ffmpeg ``-progress pipe:1`` output and report 0-99% by elapsed
    ``out_time_us`` over the source duration. 100% is reserved for the download
    phase, so encode tops out at 99%."""
    last = -1
    while True:
        line = await stream.readline()
        if not line:
            break
        text = line.decode("ascii", "replace").strip()
        if not text.startswith("out_time_us="):
            continue
        value = text.split("=", 1)[1]
        if not value.isdigit():
            continue
        pct = min(99, int(int(value) * 100 / total_us))
        if pct != last:
            last = pct
            try:
                await on_progress(pct)
            except Exception:
                logger.exception("overlay progress callback failed")


async def _run_ffmpeg(src: Path, overlays: list, icon_px: int, ass_name: str, out: Path, cwd: Path, quality: int,
                      codec: str = "auto", comment_layer: Optional[tuple] = None,
                      on_progress: Optional[ProgressCb] = None,
                      scale_to: Optional[tuple] = None,
                      cfr_fps: Optional[float] = None) -> None:
    log_path = out.with_name(out.stem + ".ffmpeg.log")
    log_file = open(log_path, "wb")
    inputs: list[str] = ["-i", str(src)]
    seen: list[str] = []
    for spec in overlays:
        f = str(spec["file"])
        if f not in seen:
            seen.append(f)
    for f in seen:
        inputs += ["-i", f]
    layer_input = None
    layer_y = 0
    if comment_layer is not None:
        layer_path, _layer_x, layer_y = comment_layer
        layer_input = 1 + len(seen)  # source is [0], gift icons follow
        inputs += ["-i", str(layer_path)]
    filter_complex = _build_filter_complex(overlays, icon_px, ass_name, layer_input, layer_y, scale_to, cfr_fps)
    vmap = "[vout]"
    encoder = await video_encoder_name(codec)
    encoder_args = _encoder_args(encoder, _mapped_quality(encoder, quality))
    # 進捗を出すにはsource長(分母)が要る。取得できた時だけ-progressを有効化する。
    total_us = await _probe_duration_us(src) if on_progress else None
    report = on_progress if (on_progress and total_us) else None
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", vmap, "-map", "0:a?",
            *encoder_args,
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart",
            *(["-progress", "pipe:1", "-nostats"] if report else []),
            str(out),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE if report else asyncio.subprocess.DEVNULL,
            stderr=log_file,
            cwd=str(cwd),
        )
        if report and proc.stdout is not None:
            await _pump_ffmpeg_progress(proc.stdout, total_us, report)
        await proc.wait()
    finally:
        log_file.close()
    if proc.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        tail = ""
        try:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-800:]
        except OSError:
            pass
        out.unlink(missing_ok=True)
        raise RuntimeError(f"動画へのComment/Gift焼き込みに失敗しました（ffmpeg）。{tail}".strip())
    log_path.unlink(missing_ok=True)


DEFAULT_FPS = 30.0


def _parse_fps(token: str) -> float:
    """Parse ffprobe r_frame_rate ('30000/1001' or '30/1') into fps."""
    token = (token or "").strip()
    if "/" in token:
        num, den = token.split("/", 1)
        den_f = float(den)
        return float(num) / den_f if den_f else DEFAULT_FPS
    return float(token) if token else DEFAULT_FPS


async def _probe_dimensions(src: Path) -> tuple[int, int, float]:
    if not ffprobe_available():
        return DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_FPS
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate", "-of", "csv=s=x:p=0",
            str(src),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        width, height, rate = out.decode().strip().split("x")
        fps = _parse_fps(rate)
        if not (0 < fps <= 120):
            fps = DEFAULT_FPS
        return int(width), int(height), fps
    except (ValueError, OSError):
        logger.warning("ffprobe dimension probe failed for %s; using default", src, exc_info=True)
        return DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_FPS


def _render_dimensions(src_w: int, src_h: int) -> tuple[int, int]:
    """Output (width, height) for the burn-in. A source shorter than
    OVERLAY_MIN_HEIGHT is upscaled to it (aspect preserved) so burned text/emoji
    rasterise crisply instead of inheriting a low source resolution; taller sources
    are returned unchanged. Both dimensions are forced even (yuv420p requires it)."""
    if src_w <= 0 or src_h <= 0 or src_h >= OVERLAY_MIN_HEIGHT:
        return src_w, src_h
    out_h = OVERLAY_MIN_HEIGHT
    out_w = int(round(src_w * out_h / src_h))
    return out_w - (out_w % 2), out_h - (out_h % 2)


async def _probe_is_vfr(src: Path, nominal_fps: float) -> bool:
    """True when the source is variable-frame-rate: its average frame rate is
    meaningfully below the nominal (r_frame_rate). TikTok recordings are stream-
    copied HLS, so the framerate follows the live stream and is genuinely variable.
    ffmpeg's ``overlay`` cannot keep a constant-rate comment layer time-locked to a
    VFR base (the comments drift many seconds behind), so such a source is normalised
    to CFR in the burn-in filter graph (see ``_build_filter_complex`` ``cfr_fps``)."""
    if not ffprobe_available() or nominal_fps <= 0:
        return False
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=avg_frame_rate", "-of", "default=nk=1:nw=1",
            str(src),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        avg = _parse_fps(out.decode().strip())
    except (ValueError, OSError):
        logger.warning("VFR probe failed for %s", src, exc_info=True)
        return False
    # avg_frame_rate is 0/0 (→0) when unknown; treat as CFR to avoid a needless
    # re-encode. A >5% shortfall against nominal is a clear VFR signal.
    return 0 < avg < nominal_fps * 0.95


async def ensure_overlay(
    src_path: str,
    started_at: float,
    ended_at: Optional[float],
    events: list,
    settings,
    battles: Optional[list] = None,
    on_progress: Optional[ProgressCb] = None,
) -> dict:
    """Burn comments/gifts/battle into the recording per settings and return
    ``{"a": Path, "b": Optional[Path]}``: ``a`` is the user-facing Mode A
    (consumer-arrival timing) output — or the source path when nothing is drawn —
    and ``b`` is the Mode B (source-clock / create_time timing) comparison output,
    produced only when ``video_overlay_timing_compare`` is on and the recording has
    live create_time to anchor on, else ``None``. Built and cached on first use;
    raises RuntimeError on failure.

    The caller must only invoke this when overlay_enabled(settings) is True."""
    if not ffmpeg_available():
        raise RuntimeError("ffmpegが見つかりません。焼き込みにはffmpegのinstallが必要です。")
    src = Path(src_path)
    if not src.is_file():
        raise RuntimeError("録画fileが存在しません。")
    # The burned-in mp4 lands in the recordings root; the transient/cache artifacts
    # (ass, meta, comment layer, ffmpeg log) live under the per-recording .sidecars
    # dir, so create it before any write.
    sidecar_dir(src).mkdir(parents=True, exist_ok=True)
    cfg = overlay_settings(settings)

    # Probe the source once; both variants share geometry, duration, anchors and
    # font metrics, differing only in how event timestamps map onto the timeline.
    dur_us = await _probe_duration_us(src)
    video_dur = dur_us / 1_000_000 if dur_us else None
    anchors = _load_timing_anchors(src)
    media_pts = _load_media_pts(src)
    # media_pts(version-2 mapで2点以上)があればmapperはpts_gapsを参照しない。全packetの
    # pts_timeをdumpするprobeは長時間録画で数十万行になるため、必要な時だけ走らせる。
    if media_pts and len(media_pts) >= 2:
        pts_gaps = None
    else:
        pts_gaps = await _probe_pts_gaps(src)
    src_w, src_h, fps = await _probe_dimensions(src)
    # Render (and burn) at the upscaled resolution when the source is low-res, so the
    # overlay text/emoji are crisp; scale_to tells ffmpeg to bring the source frame up
    # to the same canvas before compositing. None when no upscale is needed.
    width, height = _render_dimensions(src_w, src_h)
    scale_to = (width, height) if (width, height) != (src_w, src_h) else None
    icon_px = _icon_px(cfg, height)
    # TikTok recordings are stream-copied HLS and thus variable-frame-rate. ffmpeg's
    # overlay filter cannot keep the constant-rate comment layer time-locked to a VFR
    # base — comments end up many seconds behind the footage — so the base is normalised
    # to CFR. This is folded into the burn-in filter graph (see _build_filter_complex)
    # rather than run as a separate full re-encode pass, so the video body is encoded
    # once instead of twice. cfr_fps is None for an already-CFR source (no resample).
    cfr_fps = fps if await _probe_is_vfr(src, fps) else None
    if cfr_fps is not None:
        logger.info("overlay: normalising VFR source to CFR %.3ffps in-graph for %s", fps, src.name)
    avatar_dir = src.parent / "avatars" / "by-id"
    wide_em, narrow_em = await _font_metrics()
    quality = int(cfg.get("video_overlay_quality") or 21)
    codec = codec_family(cfg.get("video_overlay_codec"))

    async def _render_variant(time_source, out, ass_path, meta_path, signature, debug_path=None):
        if out.is_file() and meta_path.is_file():
            try:
                if meta_path.read_text(encoding="utf-8").strip() == signature:
                    return out
            except OSError:
                pass
        debug_sink = [] if debug_path is not None else None
        ass_text, overlays, stats, comment_plan = _build_ass(
            events, started_at, ended_at, video_dur, width, height, cfg, anchors, avatar_dir,
            wide_em, narrow_em, pts_gaps, battles, time_source=time_source, debug_sink=debug_sink,
            media_pts=media_pts,
        )
        if stats.get("source_unavailable"):
            # Mode B could not be anchored (no live create_time); leave no B output.
            out.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            return None
        if stats["comments"] == 0 and stats["gifts"] == 0 and stats["score"] == 0:
            logger.info("overlay[%s]: nothing to draw for %s; serving source", time_source, src.name)
            out.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            return src if time_source == "arrival" else None

        comment_layer = None
        comment_fallback = False
        comment_layer_path = sidecar_dir(src) / (out.stem + COMMENT_LAYER_SUFFIX)
        if comment_plan is not None:
            layer_fps = min(fps, COMMENT_LAYER_FPS_CAP)
            # The comment layer streams every frame through a long-lived pipe to a
            # qtrle encoder; under load that pipe can break transiently and yield
            # None. Retry once before giving up, since a mono fallback must never be
            # cached as the final result (see the meta write below).
            for attempt in range(1, 3):
                comment_layer = await _render_comment_layer(
                    comment_plan["placements"], comment_plan["avatar_files"], comment_plan["metrics"],
                    comment_plan["comment_fs"], comment_plan["shaper"],
                    width, height, layer_fps, comment_layer_path,
                )
                if comment_layer is not None:
                    break
                logger.warning("comment layer render produced nothing for %s (attempt %d/2)", src.name, attempt)
            if comment_layer is None:
                # The colour-emoji layer could not be produced; rebuild the ASS with
                # the monochrome comment feed so comments still show. This output is
                # degraded (colour emoji were requested but failed to render), so it is
                # NOT cached as complete — the next output retries the colour layer.
                comment_fallback = True
                logger.warning("comment layer unavailable for %s after retry; falling back to ASS comments", src.name)
                ass_text, overlays, stats, _ = _build_ass(
                    events, started_at, ended_at, video_dur, width, height, cfg, anchors, avatar_dir,
                    wide_em, narrow_em, pts_gaps, battles, use_comment_layer=False, time_source=time_source,
                    media_pts=media_pts,
                )

        renderable = await _resolve_icons(overlays, src.parent / ICON_CACHE_DIR)
        ass_path.write_text(ass_text, encoding="utf-8")
        try:
            await _run_ffmpeg(src, renderable, icon_px, ass_path.name, out, sidecar_dir(src), quality,
                              codec=codec, comment_layer=comment_layer, on_progress=on_progress,
                              scale_to=scale_to, cfr_fps=cfr_fps)
        finally:
            ass_path.unlink(missing_ok=True)
            comment_layer_path.unlink(missing_ok=True)
        if comment_fallback:
            meta_path.unlink(missing_ok=True)
        else:
            meta_path.write_text(signature, encoding="utf-8")
        if debug_sink is not None:
            try:
                debug_path.write_text(
                    json.dumps({
                        "source_diag": stats.get("source_diag"),
                        "dropped_no_create_time": stats.get("dropped_no_create_time"),
                        "rows": debug_sink,
                    }, ensure_ascii=False),
                    encoding="utf-8",
                )
            except OSError:
                logger.warning("failed to write timing debug sidecar %s", debug_path, exc_info=True)
        logger.info(
            "overlay rendered[%s]: %s (comments=%d gifts=%d score=%d icons=%d dropped_icons=%d avatars=%d)",
            time_source, out.name, stats["comments"], stats["gifts"], stats["score"], len(renderable),
            stats["dropped_icons"], stats["avatars"],
        )
        return out

    out_a, ass_a, meta_a = overlay_paths(src)
    sig_a = _signature(src, cfg, timing_path(src), variant="a")
    lock = await _get_lock(str(out_a))
    async with lock:
        result_a = await _render_variant("arrival", out_a, ass_a, meta_a, sig_a)
        result_b = None
        # Mode B comparison output: opt-in and only when the recording carries live
        # create_time to anchor on. Skipped entirely when A drew nothing (same events
        # => B would draw nothing too).
        b_enabled = (
            result_a is not src
            and bool(settings.get("video_overlay_timing_compare"))
            and len(_live_create_samples(events)) >= SOURCE_MIN_ANCHOR_SAMPLES
        )
        if b_enabled:
            out_b, ass_b, meta_b = overlay_paths_b(src)
            sig_b = _signature(src, cfg, timing_path(src), variant="b")
            result_b = await _render_variant(
                "server", out_b, ass_b, meta_b, sig_b, sidecar_path(src, TIMING_DEBUG_SUFFIX)
            )
        if result_b is None:
            # Compare off / not anchorable / B drew nothing: drop any stale B output.
            for p in overlay_paths_b(src):
                p.unlink(missing_ok=True)
    return {"a": result_a, "b": result_b}
