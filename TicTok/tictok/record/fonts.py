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
import time
import urllib.request
from pathlib import Path
from typing import NamedTuple, Optional

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
    "NotoSansSymbols2-Regular.ttf": _Font(
        "https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssymbols2/NotoSansSymbols2-Regular.ttf",
        "7d5fb73b7ca67a6798101741f5d280a3d016a56a197afcd4199dbb57b4b82a21",
    ),
    # Universal last-resort fallback: GNU Unifont covers essentially every assigned
    # Basic Multilingual Plane codepoint (~59k glyphs), so a comment character no
    # nicer font has — the exotic scripts kaomoji borrow (Canadian syllabics, Thai,
    # Yi, Armenian, Ethiopic, …) — renders as a plain glyph instead of being dropped.
    # Placed last in the chain, so it only catches what the quality fonts miss. Dual
    # GPLv2+FE / SIL OFL 1.1.
    "unifont.otf": _Font(
        "https://unifoundry.com/pub/unifont/unifont-16.0.01/font-builds/unifont-16.0.01.otf",
        "ea39a0e614e7486490239c5759e1a0cd86fd49e335c4b08d2fd13e313147f022",
    ),
}

# テロップのfontは**書体ごとに1部屋**へ置く。libassの ``fontsdir`` は渡したdirectoryの
# 全fileをfontとして読もうとするので、まとめて置くと使わない書体まで毎processで読み込まれ
# (通常presetのNoto Sans CJK JP Boldだけで17MB)、README/OFL.txtは「font として開けない」
# errorとしてlogへ並ぶ(実測)。1書体1部屋なら、その回に要る1本だけが読まれる。
# ``FONT_DIR`` を差し替えたら追随するよう、定数ではなく関数で持つ(定数にすると
# import時の値がdefault引数へ焼き付いて、差し替えが効かない)。
def telop_font_dir(font_file: str) -> Path:
    return FONT_DIR / "telop" / Path(font_file).stem


# テロップpresetが使うfont。commentのfont(上のFONT_MANIFEST)とは用途も失敗時の扱いも
# 違うので別のmanifestにしている: commentのfontは1つでも欠けるとカラー絵文字を諦めて
# 白黒描画へ落ちるが、テロップのfontは「利用者が選んだpresetそのもの」なので、欠けたら
# 焼き込みを止める(別のfontで代替すると、選んだのと違う書体で恒久的に焼き込まれる)。
# 家族名は tictok/record/telop_styles.py 側に実測値で持つ。全てSIL OFL 1.1。
TELOP_FONT_MANIFEST: dict[str, _Font] = {
    # 通常/ネオンpreset。既にあるRegularと同じ家族名なので、Style側のBold指定で選び分ける。
    "NotoSansCJKjp-Bold.otf": _Font(
        "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/Japanese/NotoSansCJKjp-Bold.otf",
        "e53dcb0dcb2922e45d01aae1ebd2f382bb81d4229b18b6b883bd170678af1f76",
    ),
    # バラエティpreset: 極太の日本語display体。
    "ReggaeOne-Regular.ttf": _Font(
        "https://raw.githubusercontent.com/google/fonts/main/ofl/reggaeone/ReggaeOne-Regular.ttf",
        "aebe62598732d76036f30ec11bb0ec5f68938e373a06d1b4ceb6b9cf1abf3db2",
    ),
    # カワイイpreset: 丸みのあるpop体。
    "MochiyPopOne-Regular.ttf": _Font(
        "https://raw.githubusercontent.com/google/fonts/main/ofl/mochiypopone/MochiyPopOne-Regular.ttf",
        "9e009430e1316c271a5f34759c6b65fc343c4e806f193042528887e7235a92c6",
    ),
    # ホラーpreset: 極太明朝。
    "ShipporiMinchoB1-ExtraBold.ttf": _Font(
        "https://raw.githubusercontent.com/google/fonts/main/ofl/shipporiminchob1/ShipporiMinchoB1-ExtraBold.ttf",
        "bee99a242f32128e8d6a4acff2b3f1742cd42ea90748758e6e10456871887e76",
    ),
    # レトロpreset: bitmap風のドット体。
    "DotGothic16-Regular.ttf": _Font(
        "https://raw.githubusercontent.com/google/fonts/main/ofl/dotgothic16/DotGothic16-Regular.ttf",
        "3ad9af88726d42b40f7f365f0dcac785af73cf20ea6f1d5b44e57cc21150b8f1",
    ),
    # 映画字幕preset: 細めの明朝。ホラーのB1 ExtraBoldとは別family。
    "ShipporiMincho-Regular.ttf": _Font(
        "https://raw.githubusercontent.com/google/fonts/main/ofl/shipporimincho/ShipporiMincho-Regular.ttf",
        "769b5269f0f9bc6534b352c0e6bd856a566e03ff788f107191c2d835863570b2",
    ),
    # 手書きpreset: marker風。
    "YuseiMagic-Regular.ttf": _Font(
        "https://raw.githubusercontent.com/google/fonts/main/ofl/yuseimagic/YuseiMagic-Regular.ttf",
        "82098615f39ed9da6a8ccc674b9006e49c70dd5b775a7a1697f6bedd22ce25a2",
    ),
    # ゆるふわpreset: 丸い手書き。
    "HachiMaruPop-Regular.ttf": _Font(
        "https://raw.githubusercontent.com/google/fonts/main/ofl/hachimarupop/HachiMaruPop-Regular.ttf",
        "78408910c8f1a2f174a279cbc1484b48b71780039eba3fe1be2bfcc5d4df3f98",
    ),
    # 和風preset: 筆書体。
    "YujiSyuku-Regular.ttf": _Font(
        "https://raw.githubusercontent.com/google/fonts/main/ofl/yujisyuku/YujiSyuku-Regular.ttf",
        "82728ebafc8c97391e2dab633414a806f344b8e4e2227d307179f07b548fca61",
    ),
    # インパクトpreset: 極太の丸ゴシックdisplay。
    "RocknRollOne-Regular.ttf": _Font(
        "https://raw.githubusercontent.com/google/fonts/main/ofl/rocknrollone/RocknRollOne-Regular.ttf",
        "dc0f5ff975851827f63f2c6bfed128ffbca14b6399a10fb5e1711215c0108526",
    ),
    # サイバーpreset: 字画が二重線で抜けたdisplay体。
    "TrainOne-Regular.ttf": _Font(
        "https://raw.githubusercontent.com/google/fonts/main/ofl/trainone/TrainOne-Regular.ttf",
        "07d67ad14231a4a41f0ee501b14bd6f9c7a9beada5ee6af2924114863a034623",
    ),
    # ミニマルpreset: 細字。commentのfontと同じfileだが、libassへ渡すdirectoryが別なので
    # (書体ごとに1部屋)ここにも要る。
    "NotoSansCJKjp-Regular.otf": _Font(
        "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/Japanese/NotoSansCJKjp-Regular.otf",
        "68a3fc98800b2a27b371f2fb79991daf3633bd89309d4ffaa6946fd587f375b5",
    ),
    # ポップpreset: 角の丸いgothic。
    "ZenMaruGothic-Bold.ttf": _Font(
        "https://raw.githubusercontent.com/google/fonts/main/ofl/zenmarugothic/ZenMaruGothic-Bold.ttf",
        "fe24426b9c8b5523a0146a8235c8674eccf0493af354a53ec895c3596d9eb745",
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


def _present(name: str, spec: _Font, dest_dir: Optional[Path] = None) -> bool:
    path = (dest_dir or FONT_DIR) / name
    return path.is_file() and _sha256(path) == spec.sha256


def _fetch(name: str, spec: _Font, dest_dir: Optional[Path] = None) -> None:
    """Download one font, verifying its SHA-256 before it is put in place. The
    bytes are written to a temporary sibling and renamed, so an interrupted or
    corrupted download never leaves a half-written file that later reads as
    present."""
    dest_dir = dest_dir or FONT_DIR
    started = time.monotonic()
    req = urllib.request.Request(spec.url, headers={"User-Agent": "TicTok-font-fetch"})
    with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp:
        data = resp.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != spec.sha256:
        # Upstream now serves a different build. Not a transient failure and not
        # self-correcting: the pin has to be reviewed and updated by hand, and until
        # then every burn-in loses colour emoji.
        logger.error(
            "font %s の検証に失敗しました（配布元の内容が変わっています）", name,
            extra={"event": "overlay.font_digest_mismatch",
                   "ctx": {"stem": name, "url": spec.url, "digest": digest,
                           "expected_digest": spec.sha256, "size_bytes": len(data)}},
        )
        raise RuntimeError(
            f"font {name} sha256 mismatch: got {digest}, expected {spec.sha256}"
        )
    tmp = dest_dir / f"{name}.part"
    tmp.write_bytes(data)
    tmp.replace(dest_dir / name)
    logger.info(
        "font %s を取得しました（%d bytes）", name, len(data),
        extra={"event": "overlay.font_fetched",
               "ctx": {"stem": name, "url": spec.url, "size_bytes": len(data),
                       "path": str(dest_dir / name),
                       "duration_ms": int((time.monotonic() - started) * 1000)}},
    )


def ensure_telop_font(name: str) -> Path:
    """テロップpresetのfontを1つ揃えてpathを返す。

    ``ensure_fonts`` と違い失敗を握り潰さない。ここで代替fontへ落とすと、利用者が選んだ
    presetと違う書体で焼き込まれ、しかも成果物を見るまで誰も気づけない。取得できない
    ことは呼び出し側から利用者へそのまま伝える。"""
    spec = TELOP_FONT_MANIFEST.get(name)
    if spec is None:
        raise KeyError(f"unknown telop font: {name}")
    dest_dir = telop_font_dir(name)
    path = dest_dir / name
    with _lock:
        if _present(name, spec, dest_dir):
            return path
        dest_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "テロップ用のfont %s を %s へ取得します", name, dest_dir,
            extra={"event": "overlay.telop_font_fetch_started",
                   "ctx": {"stem": name, "url": spec.url, "path": str(dest_dir)}},
        )
        _fetch(name, spec, dest_dir)
    return path


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
            started = time.monotonic()
            logger.info(
                "コメント焼き込み用のfont %d 件を %s へ取得します", len(missing), FONT_DIR,
                extra={"event": "overlay.font_fetch_started",
                       "ctx": {"fonts": sorted(missing), "missing": len(missing),
                               "total": len(FONT_MANIFEST), "forced": force,
                               "path": str(FONT_DIR)}},
            )
            for name, spec in missing.items():
                try:
                    _fetch(name, spec)
                except Exception:
                    # The caller renders comments through the monochrome ASS path
                    # instead, so this degrades output rather than losing it — but the
                    # degradation is silent in the finished video, so it is named here.
                    logger.warning(
                        "font %s を取得できないため、焼き込みのcommentは"
                        "白黒の描画へ転落します", name,
                        extra={"event": "overlay.font_fetch_failed",
                               "ctx": {"stem": name, "url": spec.url,
                                       "timeout_seconds": _DOWNLOAD_TIMEOUT}},
                        exc_info=True,
                    )
                    raise
            logger.info(
                "コメント焼き込み用のfontが揃いました（%d 件取得）", len(missing),
                extra={"event": "overlay.fonts_ready",
                       "ctx": {"fetched": len(missing), "total": len(FONT_MANIFEST),
                               "path": str(FONT_DIR),
                               "duration_ms": int((time.monotonic() - started) * 1000)}},
            )
        _ensured = True
