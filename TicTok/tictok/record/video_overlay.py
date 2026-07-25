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
import shutil
import subprocess
import tempfile
import time
import unicodedata
import urllib.request
from pathlib import Path
from typing import Awaitable, Callable, Optional


from tictok.paths import PROJECT_ROOT
from tictok.core import cancel
from tictok.core import config
from tictok.core import layout
from tictok.core.cancel import JobCancelled
from tictok.core.gpu import gpu_slot_async
from tictok.core.logging_setup import progress_interval_seconds
from tictok.core.progress import (  # 進捗reporterは全長時間jobで共通
    OVERLAY_PHASES, PREVIEW_PHASES, IntervalGate, JobProgress, ProgressCb, StageCb,
    fmt_hms, pump_ffmpeg_progress, pump_progress_sync,
)
from tictok.core.battle import battle_sides, battle_type
from tictok.media.avatar_pool import avatar_key
from tictok.record import audio_norm, subtitles
from tictok.record.recorder import (
    PTS_DISCONTINUITY_MIN_SECONDS,
    SIDECAR_DIRNAME,
    ffmpeg_available,
    ffprobe_available,
    is_pts_discontinuity,
    sidecar_dir,
    sidecar_path,
    timing_path,
)

logger = logging.getLogger("tictok.video_overlay")


# ===== 診断用ctx builder =====
# 焼き込みは別process(ffmpeg)と別thread(PIL layer)に跨がって失敗するため、失敗地点の
# logがその場で原因を確定できるだけのfieldを持っていないと、後から再現できない。以下は
# その「失敗地点に必ず載せるfield」を組み立てる小道具で、描画結果には一切影響しない。


def _oserror_ctx(exc: BaseException) -> dict:
    """OSErrorの識別子をctxへ。errnoが無いとdisk満杯(ENOSPC)と権限とpath不正が
    区別できず、過去の障害では全て「render failed」の一行に潰れていた。"""
    ctx: dict = {"exc_type": type(exc).__name__, "error": str(exc)}
    for attr in ("errno", "strerror", "winerror"):
        value = getattr(exc, attr, None)
        if value is not None:
            ctx[attr] = value
    return ctx


def _disk_ctx(path: Path) -> dict:
    """``path``が載るvolumeの空き容量。書き込み失敗のlogに必ず添える。空き容量の取得自体が
    失敗しても診断を止めないよう、取れなかったことをfieldとして残す。"""
    try:
        usage = shutil.disk_usage(str(path if path.is_dir() else path.parent))
    except OSError as exc:
        return {"disk_free_bytes": None, "disk_probe_error": str(exc)}
    return {
        "disk_free_bytes": usage.free,
        "disk_total_bytes": usage.total,
        "disk_low": usage.free < config.get_log_disk_low_bytes(),
    }


def _dir_bytes(path: Path) -> Optional[int]:
    """展開済みframeが実際に何byte書けたか。ENOSPCの直前まで書けていたのか、最初の1枚で
    落ちたのかを分ける。走査に失敗したらNone(不明)を返し、推測値は作らない。"""
    try:
        return sum(p.stat().st_size for p in path.iterdir() if p.is_file())
    except OSError:
        return None


class NothingToDrawError(RuntimeError):
    """描く対象が1件も無いという入力側の前提不成立。

    ffmpegの失敗と同じRuntimeErrorで運ぶと、HTTP側が5xxへ落とすしか無くなり、監視とlogでは
    server errorとして数えられる(userへ出す文言は正常なのに、状態だけが異常になる)。
    呼び出し側が4xxへ落とせるよう型で分ける。"""


def _timing_map_ctx(src: Path) -> dict:
    """録画のtiming map(wall->media anchors / media_pts)の在否。recorderはCFR転落時に
    このfileをunlinkするが、焼き込みは別時刻・別操作で走るため、焼き込み側のlogだけを見る
    調査者にはmapが無い理由が見えない。開始logに在否とversionとmtimeを必ず残す。"""
    path = timing_path(src)
    ctx: dict = {"timing_map_present": False, "timing_map_version": None,
                 "timing_map_mtime": None}
    try:
        stat = path.stat()
    except OSError:
        return ctx
    ctx["timing_map_present"] = True
    ctx["timing_map_mtime"] = round(stat.st_mtime, 3)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ctx
    if isinstance(data, dict):
        ctx["timing_map_version"] = data.get("version")
        ctx["timing_map_anchors"] = len(data.get("anchors") or [])
        ctx["timing_map_media_pts"] = len(data.get("media_pts") or [])
    return ctx


def _bridge_ctx(source: Optional[dict]) -> dict:
    """Mode A/B共通のtime bridge診断。原点Cが破綻すると全eventが動画長の外へ落ちるので、
    Cとその根拠件数はどちらのModeでも構造化して残す(Bだけに出すと、Aで起きた同種の
    ズレを後から突き合わせられない)。"""
    if source is None:
        return {"bridge_available": False, "c_value": None, "n_anchor": None,
                "n_samples": None, "n_backlog": None}
    return {
        "bridge_available": True,
        "c_value": round(source["c_value"], 3),
        "n_anchor": source["n_anchor"],
        "n_samples": source["n_samples"],
        "n_backlog": source["n_backlog"],
    }


def _placement_ctx(stats: dict) -> dict:
    """"何も描かない"判断と描画完了の双方に載せる、event配置の全体像。件数だけでは
    multi-recordingの2本目で窓がズレた場合を検出できないため、渡されたevent窓・
    event時刻の範囲・映像timeへ写像したoffsetの範囲を必ず併記する。"""
    keys = (
        "events_total", "placed", "dropped_no_create_time", "dropped_before_start",
        "dropped_after_end", "dropped_ratio", "offset_min", "offset_max",
        "events_time_min", "events_time_max", "video_duration_seconds",
        "window_started_at", "window_ended_at", "time_source",
    )
    ctx = {k: stats.get(k) for k in keys}
    ctx.update(stats.get("bridge") or {})
    return ctx


# Font size in settings is authored against this reference height (a typical
# vertical video); the actual script size is scaled to the real video so burned
# text looks consistent regardless of the source resolution.
BASE_HEIGHT = 1280
DEFAULT_WIDTH = 720
DEFAULT_HEIGHT = 1280

# Comment avatar radius as a fraction of the line height. The drawn diameter is the
# dominant factor in how much of the avatar survives encoding: at 4:2:0 the chroma
# plane is half this again, so a disc small enough to matter loses fine detail no
# matter how good the source or the bitrate (a larger source or a higher bitrate
# does not recover it — both were measured and neither helps).
#
# 1.0 is the free point: it makes the disc exactly one comment block tall (a block is
# at least the nickname line plus one body line, i.e. 2 * line_h), so the avatar fills
# the space the layout already reserves and the feed keeps the same number of comments
# on screen. Above 1.0 the avatar drives the block height instead of the text, and
# every extra pixel costs feed density.
AVATAR_RADIUS_FRAC = 1.00

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
# Legacy transient CFR-normalised copy of a VFR source (older builds). Kept so
# cleanup removes any such file orphaned by an older build's crashed render.
CFR_SUFFIX = ".cfr.mp4"
# Transient CFR-normalised base written by the pre-pass when a comment layer is
# composited on a VFR source (see _run_ffmpeg); removed when the render finishes.
CFR_BASE_SUFFIX = ".cfrbase.mp4"
# Upper bound for the CFR normalisation target. TikTok recordings are stream-copied
# HLS: the container's nominal rate (r_frame_rate, often 50/60) is padding — the real
# average rate is far lower (mobile live content is ~30fps). Normalising to the nominal
# would encode phantom duplicate frames, doubling the pre-pass, comment-layer and
# burn-in frame counts for no visible gain, so the target is capped here. 30 preserves
# all real motion and matches the comment layer's fps cap so base and layer share a grid.
CFR_FPS_CAP = 30.0
# Mode B (source-clock timing) burn-in, produced alongside Mode A for comparison
# when video_overlay_timing_compare is on. Same source mp4, comments/battle timed
# by TikTok create_time instead of consumer arrival.
OVERLAY_SUFFIX_B = ".overlay.b.mp4"
ASS_SUFFIX_B = ".overlay.b.ass"
META_SUFFIX_B = ".overlay.b.meta"
# Per-comment timing detail for offline investigation (arrival vs source offset).
TIMING_DEBUG_SUFFIX = ".timing.debug.json"
# 焼き込み設定の確認用プレビュー。本出力とはfile名・meta・lock keyを完全に分けており、
# ここのfileが在っても本出力のcache判定には一切影響しない(逆も同じ)。成果物はuserへ
# 見せる中間確認物なので、本出力のmp4と同じ場所(recordings root)には置かず、sidecar
# dirへ隔離する。
PREVIEW_STILL_SUFFIX = ".preview.png"
PREVIEW_CLIP_SUFFIX = ".preview.mp4"
PREVIEW_CLIP_META_SUFFIX = ".preview.meta"
PREVIEW_CLIP_BASE_SUFFIX = ".preview.cfrbase.mp4"
PREVIEW_LAYER_SUFFIX = ".preview.comments.mov"
ICON_CACHE_DIR = layout.GIFT_ICON_POOL_DIRNAME
# Downloaded custom-emote images, cached by stable emote_id so a repeated emote
# ([laugh] etc.) is fetched once and reused across comments and recordings.
EMOTE_CACHE_DIR = layout.EMOTE_POOL_DIRNAME
# Private-Use base for per-render emote sentinel codepoints (see _CommentShaper).
_EMOTE_SENTINEL_BASE = 0xE000

# Settings that change the rendered output; the cache is invalidated when any
# of these (or the source file) change.
OVERLAY_KEYS = (
    "video_overlay_comments",
    "video_overlay_gifts",
    "video_overlay_score_bar",
    "video_overlay_score_bar_hold_seconds",
    "video_overlay_real_avatars",
    "video_overlay_avatar_upscale",
    "video_overlay_font_size",
    # 出力解像度そのものを決めるので、変更したら焼き直しになる(cacheを跨がせない)。
    "video_overlay_min_height",
    "video_overlay_comment_delay_seconds",
    "video_overlay_gift_seconds",
    "video_overlay_gift_min_diamonds",
    "video_overlay_icon_percent",
    "video_overlay_quality",
    "video_overlay_codec",
    "video_overlay_subtitles",
    "video_overlay_subtitle_font_size",
    "video_overlay_subtitle_position_percent",
    # 音量正規化は出力の中身を変えるので、cache signatureへ入る必要がある(値を変えたのに
    # 前回の音声のままcache hitする、を避ける)。
    "video_output_normalize_audio",
    *audio_norm.NORMALIZE_SETTING_KEYS,
)

_locks_guard = asyncio.Lock()
_locks: dict[str, asyncio.Lock] = {}


# Avatar AI super-resolution lives in tictok.media.avatar_upscale, which imports the
# upscale stack that in turn imports this module — so it is imported lazily (inside the
# call) to avoid an import cycle at module load. Both entry points are only reached at
# render time.
def _avatars_upscalable() -> bool:
    from tictok.media.avatar_upscale import avatars_upscalable

    return avatars_upscalable()


def _upscale_avatar(src_img: Path) -> Optional[Path]:
    from tictok.media.avatar_upscale import ensure_avatar_upscaled

    return ensure_avatar_upscaled(src_img)


def overlay_settings(settings) -> dict:
    return {key: settings.get(key) for key in OVERLAY_KEYS}


def overlay_enabled(settings) -> bool:
    cfg = overlay_settings(settings)
    return (
        bool(cfg["video_overlay_comments"])
        or bool(cfg["video_overlay_gifts"])
        or bool(cfg["video_overlay_score_bar"])
        or bool(cfg["video_overlay_subtitles"])
    )


def subtitles_enabled(settings) -> bool:
    """字幕焼き込みが要求されているか。呼び出し側はこれが真のとき、転写の有無と時刻mapの
    版を確かめてから焼き込みへ入る(無いまま字幕なしで焼くのは禁止)。"""
    return bool(settings.get("video_overlay_subtitles"))


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


def preview_paths(src: Path) -> tuple[Path, Path, Path]:
    """(静止画png, 動画mp4, 動画のmeta)。いずれもsidecar dirに置き、本出力のpath空間とは
    重ならない。"""
    src = Path(src)
    return (
        sidecar_path(src, PREVIEW_STILL_SUFFIX),
        sidecar_path(src, PREVIEW_CLIP_SUFFIX),
        sidecar_path(src, PREVIEW_CLIP_META_SUFFIX),
    )


def overlay_artifact_paths(src: Path) -> list:
    """Every burn-in artifact that survives a finished render (the output mp4s and
    their ass/meta/debug sidecars). Regenerable from the source plus the stored events,
    so the retention sweep may drop them; enumerated here rather than at the call site
    so what is reported as reclaimable and what cleanup actually removes cannot drift."""
    src = Path(src)
    return list(overlay_paths(src)) + list(overlay_paths_b(src)) + [
        sidecar_path(src, TIMING_DEBUG_SUFFIX),
    ] + list(preview_paths(src))


def overlay_transient_paths(src: Path) -> list:
    """Intermediates a render writes and deletes again (CFR base, comment layer). A
    crashed render orphans them, and an orphan is pure waste — no output depends on it."""
    src = Path(src)
    paths = [sidecar_path(src, CFR_SUFFIX)]
    for out_mp4 in (overlay_paths(src)[0], overlay_paths_b(src)[0]):
        paths.append(sidecar_dir(src) / (out_mp4.stem + CFR_BASE_SUFFIX))
        paths.append(sidecar_dir(src) / (out_mp4.stem + COMMENT_LAYER_SUFFIX))
    paths.append(sidecar_path(src, PREVIEW_CLIP_BASE_SUFFIX))
    paths.append(sidecar_path(src, PREVIEW_LAYER_SUFFIX))
    return paths


_TRANSIENT_SWEEP_DIR_SUFFIX = ".frames"


def _transient_sweep_suffixes() -> tuple:
    """起動sweepが孤児と見なすsuffix。renderが自分で消す物とちょうど同じ集合。

    module levelのtupleにしないのは、COMMENT_LAYER_SUFFIX等がこの関数より後ろで定義されて
    おり、import時評価ではNameErrorになるため(定義順に依存しない形にしておく)。"""
    return (
        CFR_BASE_SUFFIX, CFR_SUFFIX, COMMENT_LAYER_SUFFIX,
        PREVIEW_CLIP_BASE_SUFFIX, PREVIEW_LAYER_SUFFIX,
        PREVIEW_RAW_SUFFIX, PREVIEW_ASS_SUFFIX,
        CFR_BASE_SUFFIX.replace(".mp4", "") + ".prepass.log",
    )


def sweep_orphaned_transients(roots) -> tuple:
    """起動時に、落ちたrenderが残した焼き込み中間物をすべて消す。(件数, bytes)を返す。

    renderは成功でも例外でも ``finally`` で中間物を消すが、**processが即死すると finally は
    走らない**。実際にserver再起動で53%だったjobが31GB(cfrbase 17.3GB + comments.mov 13.7GB)
    を残し、空き容量を直接圧迫した。起動時点では実行中jobは存在しない(_recover_media_jobsが
    interruptedへ倒した後に呼ぶこと)ので、ここに在る中間物は定義上すべて孤児で、
    どの成果物もこれらに依存しない。次のrenderは必ず作り直すため、消して失うものは無い。

    保持policy(retention)にも同じfileを拾う経路はあるが、あちらは人が画面から起こす掃除で、
    誰も見ていない夜間に貯まる孤児には届かない。"""
    removed, freed = 0, 0
    suffixes = _transient_sweep_suffixes()
    for root in roots:
        sidecars = Path(root) / SIDECAR_DIRNAME
        if not sidecars.is_dir():
            continue
        for path in sidecars.iterdir():
            if path.is_dir():
                # PIL側の展開先(<layer>.frames/)。中身はdistinct frameのpngで、layerを
                # 作り直せば再生成される。
                if not path.name.endswith(_TRANSIENT_SWEEP_DIR_SUFFIX):
                    continue
                size = _dir_bytes(path)
                _rm_frames_dir(path)
                if path.exists():
                    continue
                removed += 1
                freed += size
                continue
            if not any(path.name.endswith(suffix) for suffix in suffixes):
                continue
            try:
                size = path.stat().st_size
                path.unlink()
            except OSError:
                logger.warning(
                    "could not remove the orphaned burn-in intermediate %s", path.name,
                    extra={"event": "overlay.transient_sweep_failed",
                           "ctx": {"path": str(path)}},
                    exc_info=True,
                )
                continue
            removed += 1
            freed += size
    if removed:
        logger.info(
            "removed %d orphaned burn-in intermediate(s), freeing %.1f GB",
            removed, freed / 1e9,
            extra={"event": "overlay.transient_swept",
                   "ctx": {"removed": removed, "freed_bytes": freed}},
        )
    return removed, freed


def cleanup_overlay_files(src: Path) -> None:
    """Remove cached burn-in artifacts for a recording (called on delete)."""
    paths = overlay_artifact_paths(src) + overlay_transient_paths(src)
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


def _events_fingerprint(events: list) -> str:
    """Digest of the burned-in event set. The mp4's size/mtime does not change when
    the DB's events for the session change (journal recovery re-inserts, or the session
    keeps collecting after this recording finalised), so without this a re-output would
    return a stale burn-in on a cache hit."""
    h = hashlib.sha256()
    for e in events:
        h.update(json.dumps(e, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


# 描く物が1つも無く、音量正規化だけを掛けて出した成果物の印。meta の2行目に置く。
# cache hitで再renderを飛ばした場合でも「A側は何も描かなかった」ことが要る(Mode Bの
# 起動判定)ため、signatureとは別にこの事実を残す。
AUDIO_ONLY_MARK = "audio-only"


def _read_meta(meta_path: Path, signature: str) -> Optional[bool]:
    """cacheが有効なら「音声のみ正規化した出力か」を返す。無効・読めない場合はNone。"""
    try:
        lines = meta_path.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return None
    if not lines or lines[0].strip() != signature:
        return None
    return len(lines) > 1 and lines[1].strip() == AUDIO_ONLY_MARK


def _signature(
    src: Path,
    cfg: dict,
    timing: Optional[Path] = None,
    variant: str = "a",
    events_sig: Optional[str] = None,
    subtitles_sig: Optional[str] = None,
) -> str:
    stat = src.stat()
    payload = {
        # 28: avatar/emote/gift iconのpoolをmp4の現在地ではなくwork rootで解決するよう修正。
        # final dirへ移送済みの録画は今までpoolを1件も引けず、全コメントがイニシャル円盤へ
        # 縮退した出力になっていた。描画が変わるのでcacheを無効化する — これが無いと、
        # 直った後に焼き直しても既存のmeta+出力にcache hitして壊れた出力が返り続ける。
        # 27: TikTok custom emoteを文字高の2倍で描画し、該当行の行高も拡張。
        # commentの行送り・block高が変わるためcacheを無効化する。
        "version": 28,
        "variant": variant,
        "cfg": cfg,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "events": events_sig,
        # 転写のやり直しでsegmentが変われば描く字幕も変わるが、mp4も設定値も変わらない。
        # これが無いと転写後の焼き直しがcache hitで無視される。
        "subtitles": subtitles_sig,
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

# STT字幕は画面中央に横いっぱいで置く帯。縦位置は設定
# (video_overlay_subtitle_position_percent)で動かすので、ここは幅と行間だけを持つ。
# 幅はComment帯(左80%)と違い中央揃えなので、左右に均等な余白を残す。
SUBTITLE_WIDTH_FRAC = 0.90
# 1つのsegmentが極端に長い場合の行数上限。これを超える行は描かず、字幕が画面全体を
# 覆って映像が見えなくなるのを防ぐ(捨てた行数はstatsとlogに残す)。
SUBTITLE_MAX_LINES = 4

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
    "NotoSansSymbols2-Regular.ttf",  # dingbats/ornaments (e.g. U+275B) and misc symbols
    "unifont.otf",                   # universal last resort: any assigned BMP codepoint
)
# Noto Color Emoji is a bitmap-strike font: its glyphs live at this single pixel
# size, so emoji are rendered at the native strike and scaled down (crisp result).
EMOJI_STRIKE_PX = 109
# A colour-emoji cell is laid out roughly square at this multiple of the comment
# font size; used by both wrap measurement and rendering so they stay consistent.
# Kept at 1.0 so emoji match the text height instead of overpowering it.
EMOJI_TILE_EM = 1.0
# TikTok custom emotes (sub/fansclub) are detailed illustrations, not glyphs: at the
# text height they read as unrecognisable specks, so they are drawn at this multiple
# of the comment font size. Lines carrying one grow taller to fit (see line_height).
EMOTE_TILE_EM = 2.0

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


def _tokenize_emoji(text: str, is_base=_is_emoji_base) -> list:
    """Split ``text`` into ordered ('text', run) / ('emoji', cluster) tokens. An
    emoji cluster absorbs trailing modifiers (variation selector, skin tone) and
    ZWJ-joined emoji so a joined sequence draws as a single token; adjacent emoji
    without a ZWJ stay separate tokens.

    ``is_base`` decides which codepoints start an emoji cluster. It defaults to the
    codepoint-range test, but the colour-emoji shaper passes a coverage-aware
    predicate (range AND present in the colour-emoji font) so range codepoints the
    font has no colour glyph for — decorative music notes/ornaments/enclosed letters
    that live inside the emoji blocks — stay in text runs and render through the text
    fallback chain instead of vanishing as a blank tile."""
    tokens: list = []
    buf: list = []
    i, n = 0, len(text)
    while i < n:
        cp = ord(text[i])
        if is_base(cp):
            if buf:
                tokens.append(("text", "".join(buf)))
                buf = []
            cluster = [text[i]]
            i += 1
            while i < n:
                c2 = ord(text[i])
                if c2 == 0x200D and i + 1 < n and is_base(ord(text[i + 1])):
                    cluster.append(text[i])
                    cluster.append(text[i + 1])
                    i += 2
                elif _is_emoji_mod(c2):
                    cluster.append(text[i])
                    i += 1
                else:
                    break
            tokens.append(("emoji", "".join(cluster)))
        else:
            buf.append(text[i])
            i += 1
    if buf:
        tokens.append(("text", "".join(buf)))
    return tokens


def _emoji_units(text: str, is_base=_is_emoji_base) -> list:
    """Wrap units: one entry per character for text, one per cluster for emoji."""
    out: list = []
    for kind, s in _tokenize_emoji(text, is_base):
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
        # Codepoints the colour-emoji font actually has a glyph for. A codepoint can
        # be an emoji by Unicode range yet have no colour glyph here (music notes,
        # ornaments, enclosed letters that share the emoji blocks); routing those to
        # the emoji font produces a blank tile, so ``is_color_emoji`` gates on this.
        self._emoji_cov = frozenset(TTFont(str(emoji_path)).getBestCmap())
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
        # TikTok custom emotes (sub/fansclub) are inline images, not glyphs. Each is
        # assigned a Private-Use sentinel codepoint inserted into the comment text at
        # its position; the sentinel then flows through wrap/measure/draw as an
        # emoji-like unit, and ``emote_tile`` supplies the resolved image. Registered
        # before layout (with a square placeholder size) and the image is attached
        # once downloaded — see _apply_comment_emotes / _resolve_emotes.
        self._emotes: dict = {}       # sentinel char -> {"id", "url", "image"}
        self._emote_cps: set = set()  # sentinel codepoints (fast membership test)
        self._emote_tile_cache: dict = {}  # (sentinel, px) -> resized RGBA tile

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

    def is_color_emoji(self, cp: int) -> bool:
        """True when ``cp`` renders as a colour emoji here: an emoji by Unicode range
        AND present in the colour-emoji font, or a registered custom-emote sentinel.
        Range codepoints the font lacks a colour glyph for (music notes/ornaments/
        enclosed letters sharing the emoji blocks) return False so they fall back to
        the monochrome text chain instead of drawing a blank tile."""
        return cp in self._emote_cps or (_is_emoji_base(cp) and cp in self._emoji_cov)

    def register_emote(self, sentinel: str, emote_id: str, url: str) -> None:
        """Bind a Private-Use sentinel char to a custom emote (image resolved later)."""
        self._emotes[sentinel] = {"id": emote_id, "url": url, "image": None}
        self._emote_cps.add(ord(sentinel))

    def set_emote_image(self, sentinel: str, image) -> None:
        """Attach the downloaded RGBA image for a sentinel; clears any placeholder tile."""
        rec = self._emotes.get(sentinel)
        if rec is not None:
            rec["image"] = image
            for key in [k for k in self._emote_tile_cache if k[0] == sentinel]:
                self._emote_tile_cache.pop(key, None)

    def _emote_tile(self, sentinel: str, px: int):
        """Square emote image scaled to height ``px`` (cached). A transparent square is
        returned until the image is downloaded, so wrap/measure stay stable."""
        key = (sentinel, px)
        tile = self._emote_tile_cache.get(key)
        if tile is not None:
            return tile
        from PIL import Image
        img = self._emotes[sentinel].get("image")
        if img is None:
            return Image.new("RGBA", (px, px), (0, 0, 0, 0))  # placeholder; not cached
        scale = px / img.height
        w = max(1, int(round(img.width * scale)))
        tile = img.resize((w, px), Image.LANCZOS)
        self._emote_tile_cache[key] = tile
        return tile

    def tokenize(self, text: str) -> list:
        """Coverage-aware emoji tokenisation (see ``_tokenize_emoji``)."""
        return _tokenize_emoji(text, self.is_color_emoji)

    def sanitize(self, text: Optional[str]) -> str:
        """Clean a comment string for the colour-emoji path: drop invisible bidi/
        control characters (tofu, kept-emoji-mods excepted) and any glyph no bundled
        font covers, so the burn-in never shows replacement boxes. Colour emoji are
        kept for the emoji font; range codepoints without a colour glyph are kept only
        when the text chain covers them (else dropped like any other tofu)."""
        if not text:
            return ""
        out = []
        for ch in text:
            cp = ord(ch)
            if self.is_color_emoji(cp) or _is_emoji_mod(cp):
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

    def emote_px(self, fs: int) -> int:
        return max(8, int(round(fs * EMOTE_TILE_EM)))

    def has_emote(self, text: str) -> bool:
        return bool(self._emote_cps) and any(ord(ch) in self._emote_cps for ch in text)

    def line_height(self, text: str, fs: int, base_line_h: int) -> int:
        """Height of the line box holding ``text``. A line carrying a custom emote is
        taller than the text line so the enlarged emote tile fits inside its own box
        instead of bleeding over the neighbouring lines."""
        if not self.has_emote(text):
            return base_line_h
        return max(base_line_h, int(round(self.emote_px(fs) * 1.15)))

    def emoji_tile(self, cluster: str, px: int):
        """RGBA image of ``cluster`` scaled to height ``px`` (cached). Multi-emoji
        (ZWJ) clusters keep their natural width so components never overlap. A
        single-char custom-emote sentinel returns its inline emote image instead."""
        if len(cluster) == 1 and cluster in self._emotes:
            # Emotes are drawn larger than the surrounding emoji/text (EMOTE_TILE_EM);
            # ``px`` arrives as the emoji cell height, so rescale it to the emote cell.
            return self._emote_tile(cluster, max(8, int(round(px * EMOTE_TILE_EM / EMOJI_TILE_EM))))
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
        return sum(self._unit_width(k, s, fs) for k, s in _emoji_units(text, self.is_color_emoji))

    def wrap(self, text: str, fs: int, max_w: float) -> list:
        """Break ``text`` into lines fitting ``max_w`` px. ASCII breaks at spaces,
        CJK/emoji per unit; emoji widths are the rendered tile widths."""
        if max_w <= 0 or not text:
            return [text] if text else [""]
        lines: list = []
        cur = ""
        cur_w = 0.0
        last_space = -1
        for kind, s in _emoji_units(text, self.is_color_emoji):
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
        for kind, s in _emoji_units(text, self.is_color_emoji):
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
    avatar_r = max(4, int(round(line_h * AVATAR_RADIUS_FRAC)))
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

    Placement: {nick_disp, body_lines, line_hs, color, initial, has_avatar, uid, empty,
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
            # Lines carrying a custom emote get a taller box (the emote tile is drawn
            # above text size), so the block height is the sum of the per-line boxes.
            line_hs = [shaper.line_height(ln, font_size, line_h)
                       for ln in [nick_disp] + body_lines]
        else:
            nick = _ass_escape(_strip_bidi_controls(c.get("nick")))
            body = _ass_escape(_strip_bidi_controls(c.get("text")))
            body_lines = _wrap_text(body, font_size, text_max_w, wide_em, narrow_em)[:max_body_lines]
            nick_disp = _truncate(nick, font_size, text_max_w, wide_em, narrow_em)
            line_hs = [line_h] * (1 + len(body_lines))
        block_h = max(avatar_d + 2 * avatar_off, sum(line_hs))
        items.append({
            "nick_disp": nick_disp,
            "body_lines": body_lines,
            "line_hs": line_hs,
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
    # slot割り当てを先に確定させる。空きが無いときは最も早く空くslotを再利用するが、その際は
    # 先客の表示終了を新しいgiftの開始時刻まで詰める。詰めないと同じslotに2枚が同時に描かれ、
    # labelが重なって双方読めなくなる(Battle中はgiftが集中するので常態化する)。
    placed: list[dict] = []
    slot_owner: list[Optional[int]] = [None] * slot_count
    for item in gifts:
        t = item["offset"]
        slot = min(range(slot_count), key=lambda i: slot_free[i])
        for idx in range(slot_count):
            if slot_free[idx] <= t:
                slot = idx
                break
        prev = slot_owner[slot]
        if prev is not None and placed[prev]["end"] > t:
            placed[prev]["end"] = t
        slot_free[slot] = t + hold
        slot_owner[slot] = len(placed)
        placed.append({"item": item, "slot": slot, "start": t, "end": t + hold})

    for entry in placed:
        item, slot = entry["item"], entry["slot"]
        start, end = entry["start"], entry["end"]
        if end <= start:
            continue
        icon_y = gift_top + slot * slot_h
        coins = item.get("diamonds") or 0
        # Gift labels render through libass; strip invisible bidi/control chars so a
        # sender name carrying them does not burn in as tofu boxes (same root cause
        # as comments, which the colour-emoji shaper sanitizes).
        nick = _ass_escape(_strip_bidi_controls(item.get("nick")))
        # "<coins> (<user>)", e.g. "1 (user a)"; truncated to stay within frame.
        label = f"{coins:,} ({nick})" if nick else f"{coins:,}"
        label = _truncate(label, coin_fs, width - x_left * 2, wide_em, narrow_em)
        # coin+user line sits left-aligned just under the icon
        cy = icon_y + icon_px + 2
        identifiable = bool(item.get("gift_id") or item.get("gift_name") or item.get("image"))
        if identifiable:
            # slide horizontally in sync with the icon。開始xは0でclampする: 素の
            # x_left-(icon_px+20) は負になり、slide中のlabelが画面外へはみ出したまま
            # 描かれる(Battle中はbandが押し下がって同時表示が増えるため特に目立つ)。
            # 出現の演出は\fadが担うので、水平移動は枠内だけで完結させる。
            x_off = max(0, x_left - (icon_px + 20))
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
# TikTok本家のPK bar寄りの質感付け。陣営色(上の2色)は変えず、奥行きと締まりだけを足す:
# barの落ち影 / fill上端のgloss帯 / splitのVSノッチ(白・glow付き) / mode・clockを収める丸pill。
_SCORE_NOTCH_RGB = "FFFFFF"
_SCORE_PILL_RGB = "0A0E14"
# avatarを囲む陣営色のring厚(av_rに対する比)。実写真はringの内側に合成するので、
# 写真が取れた端でもringだけは残り、両端の陣営色が途切れない。
_SCORE_RING_FRAC = 0.18
_SCORE_GLOSS_FRAC = 0.34
_SCORE_GLOSS_ALPHA = "\\1a&HC8&"
_SCORE_SHADOW_ALPHA = "\\1a&H96&"
_SCORE_GLOW_ALPHA = "\\1a&HB4&"
_SCORE_PILL_ALPHA = "\\1a&H55&"
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
# Match Bonus Mission の種別文言。TikTokはStarling key(pm_mt_*)しか配信せず、文言そのものは
# event に載らないため、key -> 表示文言をここで持つ。差し込み値(progress_target)は event 実値。
# 対応するkeyは、その差し込み値が実配信468件で progress_target と完全一致することを確認済み
# (倍率キー instructions_1/3・gifter_2・*_target_host は reward_multiple と一致)。
# ミッション種別は target_type だけでは文言を復元できず、この key でしか判別できない。
_BONUS_TASK_TEXT = {
    "pm_mt_live_match_instructions_2": "ギフト{n}個",
    "pm_mt_live_match_instructions_gifter_1": "指定ギフト{n}個",
    "pm_mt_match_sp_team_gifter": "チーム 指定ギフト{n}個",
    "pm_mt_match_sp_team_point": "チーム {n}ポイント",
}
_bonus_unknown_task_keys: set = set()


def _bonus_task_label(mission: dict) -> str:
    """ミッションの達成条件文言。種別(指定ギフト/チーム/ポイント)を運ぶのは prompt key
    だけなので、それを持たない mission(key未収集の旧record、または未知key)では種別を
    名乗らず空を返す。呼び出し側は条件を伏せた汎用文言へ落とす。"""
    prompts = mission.get("prompts") or []
    for p in prompts:
        key = p.get("key") or ""
        text = _BONUS_TASK_TEXT.get(key)
        if text is None:
            continue
        n = (p.get("fields") or {}).get("multi") or ""
        return text.format(n=n) if n else ""
    known = {p.get("key") for p in prompts} - set(_BONUS_TASK_TEXT)
    for key in sorted(k for k in known if k):
        if key.startswith("pm_mt_") and key not in _bonus_unknown_task_keys:
            _bonus_unknown_task_keys.add(key)
            logger.info(
                "bonus mission prompt key %s has no display text; the burn-in band "
                "shows the mission without naming its condition", key,
                extra={"event": "overlay.bonus_prompt_key_unknown",
                       "ctx": {"prompt_key": key,
                               "target_type": mission.get("target_type") or 0}},
            )
    return ""
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
    """形式ラベル(Web common.jsのbattleModeLabelと一致): チーム戦 NvM / 個人戦 Nコラ /
    個人戦 1v1。形式はbattle["type"]ではなくcore.battleのruleで参加者から判定するため、
    typeが未migrationの古いdataでも正しく出る。"""
    parts = battle.get("participants") or []
    if battle_type(parts) == "team":
        sides = battle_sides(parts)
        return ("チーム戦 " + "v".join(str(len(ids)) for ids, _ in sides)) if sides else "チーム戦"
    n = len(parts)
    return "個人戦 1v1" if n <= 2 else f"個人戦 {n}コラ"


def _fmt_clock(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return f"{s // 60:d}:{s % 60:02d}"


# Hard cap on per-second clock lines per battle, so a pathological window (e.g. an
# ongoing battle with a sparse/odd time map) cannot explode the ASS line count.
_SCORE_CLOCK_MAX_STEPS = 3600


def _sample_lanes(sample: dict, lane_order: list) -> list:
    """1サンプルのpartsをlane_order(固定順)へ写像した[(score, is_own)]を返す。segmentの
    scoreは属する参加者scoreの合計(1人segmentなら本人のscore)。そのサンプルに居ない
    参加者はscore=0(セグメント幅0)で詰める。"""
    by_id = {str(pt.get("id")): (pt.get("score") or 0) for pt in (sample.get("parts") or [])}
    return [(sum(by_id.get(pid, 0) for pid in ids), is_own) for ids, is_own in lane_order]


def _step_xexpr(entries: list) -> str:
    """[(end_time, x), ...](時刻昇順)を ffmpeg overlay の ``x`` 用step式へ畳む。個人マルチの
    lane avatarはsegment幅と一緒に毎sample動くが、sampleごとにoverlay instanceを積むと1本の
    動画で数百inputになりfilter graphが破綻する。1 laneにつきoverlayを1つだけ置き、xを時間の
    階段関数で動かすことで instance数を lane数 に固定する(gift iconの``xexpr``と同じ仕組み)。
    連続する同一xは1段に潰す。filtergraph parserはcommaで分割するので ``\\,`` で退避する。"""
    merged: list = []
    for end_t, x in entries:
        if merged and merged[-1][1] == x:
            merged[-1][0] = end_t
        else:
            merged.append([end_t, x])
    expr = str(merged[-1][1])
    for end_t, x in reversed(merged[:-1]):
        expr = f"if(lt(t\\,{end_t:.3f})\\,{x}\\,{expr})"
    return expr


def _build_score_bar_dialogues(battles: list, to_media, video_duration: Optional[float],
                               width: int, height: int, hold_seconds: float = 0.0,
                               avatar_dir: Optional[Path] = None,
                               use_real_avatars: bool = False,
                               wide_em: float = NOMINAL_WIDE_EM,
                               narrow_em: float = NOMINAL_NARROW_EM) -> tuple[list, list]:
    """TikTok風のBattleスコアバーをASS dialogueで描く。Battle中だけ画面上部にバーを表示し、
    score_seriesの各点を映像timeへ写像して時系列で更新する(数値・境界が動く)。形式に応じて
    Web(common.jsのbattleBarUnits)と同じ分割で描く:
      1v1        : 自陣(左)/敵陣(右)の2分割。
      チーム戦NvM: 自陣/敵陣のチーム合計(own/opp)で2分割。Web同様memberには割らず、境界(VS)は
                   陣営合計で時系列移動する。
      個人Nコラ  : 参加者ごとにN分割(全員別色)。
    全形式で陣営ごとに配信者アバターを合成する: 2極は両端、個人マルチは各segmentの先頭。
    ``_build_ass``がavatar_specを解決してoverlay合成し、解決できなかった陣営はここで描く
    イニシャル円盤がそのまま残る(アバターはASSより上に合成されるので、円盤は常に下敷きとして
    描いておけばよい)。陣営色のringは写真の外側に残すので、両端の陣営色は途切れない。

    残り時間のcountdownはscore sampleと切り離し1秒刻みで描く(sample間隔に依らない)。
    Battle終了後も``hold_seconds``だけ最終スコアと勝敗を残す(勝利タイム表示)。保持は
    次Battleの開始・動画終端で打ち切る。戻り値 (dialogue_lines, avatar_specs)。"""
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
    shad = max(1, int(round(bar_h * 0.05)))
    meta_y = int(round(top - bar_h * 0.5))

    own_c, opp_c, track_c = _ass_bgr(_SCORE_OWN_RGB), _ass_bgr(_SCORE_OPP_RGB), _ass_bgr(_SCORE_TRACK_RGB)
    opp_palette_c = [_ass_bgr(c) for c in _SCORE_OPP_PALETTE]
    notch_c, pill_c, shadow_c = _ass_bgr(_SCORE_NOTCH_RGB), _ass_bgr(_SCORE_PILL_RGB), _ass_bgr("000000")
    own_cx = left + pad + av_r
    opp_cx = right - pad - av_r
    own_num_x = own_cx + av_r + gap
    opp_num_x = opp_cx - av_r - gap
    # 実写真はringの内側に収める。ring厚ぶん小さい画像を円盤の中心へ重ねると、下敷きの
    # 陣営色円盤が縁として残り、写真の有無に関わらず端の見た目が揃う。
    ring = max(1, int(round(av_r * _SCORE_RING_FRAC)))
    av_size = max(4, 2 * (av_r - ring))
    gloss_h = max(2, int(round(bar_h * _SCORE_GLOSS_FRAC)))
    shadow_off = max(2, int(round(bar_h * 0.12)))

    def shape(layer, start, end, color, path, alpha=""):
        return (f"Dialogue: {layer},{_ass_timestamp(start)},{_ass_timestamp(end)},Score,,0,0,0,,"
                f"{{\\an7\\pos(0,0)\\bord0\\shad0\\1c{color}{alpha}\\p1}}{path}")

    def text(layer, start, end, x, y, an, fs, body):
        return (f"Dialogue: {layer},{_ass_timestamp(start)},{_ass_timestamp(end)},Score,,0,0,0,,"
                f"{{\\an{an}\\pos({x},{y})\\fs{fs}\\b1\\1c&H00FFFFFF&\\3c&H00000000&"
                f"\\bord{bord}\\shad{shad}\\4c&H00000000&}}{body}")

    def disc(layer, start, end, cx, color):
        """陣営色の塗り円盤。実写真が解決すればring厚ぶん内側を覆われ、縁だけが残る。"""
        return (f"Dialogue: {layer},{_ass_timestamp(start)},{_ass_timestamp(end)},Score,,0,0,0,,"
                f"{{\\an7\\pos({int(round(cx - av_r))},{int(round(cy - av_r))})\\1c{color}"
                f"\\bord0\\shad0\\p1}}{_circle_path(av_r)}")

    def gloss(layer, start, end, x, w, rl, rr):
        """fill上端に薄い白帯を重ねて、平坦な塗りに軽い立体感(艶)を出す。"""
        if w < 2:
            return
        out.append(shape(layer, start, end, notch_c,
                         _round_rect_path(x, top, w, gloss_h, gloss_h / 2, rl, rr),
                         alpha=_SCORE_GLOSS_ALPHA))

    notch_w = max(2, int(round(bar_h * 0.09)))
    # ノッチを立てられる範囲。端のavatar zoneまで寄せるとdiamondがbarの丸端からはみ出し、
    # avatarにも重なるので、両端のavatar+余白ぶんを除いた内側にclampする。片側が0点の
    # 試合ではsplitが端に張り付くが、その場合も境界はここで止めて枠内に収める。
    notch_min = left + pad + av_r * 2
    notch_max = right - pad - av_r * 2

    def notch(layer, start, end, x):
        """splitに立てるVSノッチ。太い半透明の白帯でglowを近似し、その上に芯の細帯と
        中央のdiamondを重ねる。境界がどこかを一目で分かるようにする。"""
        if notch_max <= notch_min:
            return
        nw = notch_w
        xi = int(round(min(max(x, notch_min), notch_max)))
        out.append(shape(layer, start, end, notch_c,
                         _round_rect_path(xi - nw * 1.5, top, nw * 3, bar_h, 0),
                         alpha=_SCORE_GLOW_ALPHA))
        out.append(shape(layer + 1, start, end, notch_c,
                         _round_rect_path(xi - nw / 2, top, nw, bar_h, 0)))
        d = max(3, int(round(bar_h * 0.26)))
        out.append(shape(layer + 1, start, end, notch_c,
                         f"m {xi} {cyi - d} l {xi + d} {cyi} l {xi} {cyi + d} l {xi - d} {cyi}"))

    def pill(layer, start, end, x, w):
        """mode/clockを収める丸pill。裸の文字が映像に直接乗ると読みにくく安っぽいので、
        暗い半透明の下地を敷いて情報の塊として見せる。"""
        ph = meta_fs + max(4, int(round(meta_fs * 0.55)))
        out.append(shape(layer, start, end, pill_c,
                         _round_rect_path(x, meta_y - ph / 2, w, ph, ph / 2),
                         alpha=_SCORE_PILL_ALPHA))

    def pill_w(body: str) -> int:
        pad_x = max(4, int(round(meta_fs * 0.55)))
        return int(round(_estimate_width(body, meta_fs, wide_em, narrow_em))) + pad_x * 2

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
            gloss(8, start, end, left, split - left, True, False)
        if right - split >= 2:
            out.append(shape(8, start, end, opp_c,
                             _round_rect_path(split, top, right - split, bar_h, radius, False, True)))
            gloss(8, start, end, split, right - split, False, True)
        notch(8, start, end, split)
        out.append(text(9, start, end, own_num_x, cyi, 4, num_fs, f"{own:,}"))
        out.append(text(9, start, end, opp_num_x, cyi, 6, num_fs, f"{opp:,}"))

    seg_sep = max(2, int(round(bar_h * 0.05)))

    # 個人マルチのlane avatarは、laneごとに1つのoverlayを置いてxを時間で動かす(_step_xexpr)。
    # ここではlaneごとに [(segment終了time, そのsampleでのx), ...] を貯める。segmentがavatarを
    # 置けない幅のsampleでは画面外のxを積み、そのlaneだけ一時的に隠す。
    lane_tracks: dict = {}
    lane_reps: dict = {}

    def emit_lanes(start, end, lanes, reps=None):
        """個人マルチ(3コラ+): 1本のバーを各参加者のscore比でN分割し、各segment内に
        scoreを描く。色は陣営(segment)ごとに変える: 自分=own色、相手は出現順(score降順)に
        opp_palette_cの別色で塗り分け、自分を強調する。``lanes`` は左→右の固定順
        [(score, is_own), ...]。全score=0なら均等割り。
        各segmentの先頭には陣営色ringのアバターを置き、誰のlaneかを色だけに頼らず示す。
        segmentが狭いときはavatarを優先して数値を省き、avatarも入らない幅なら両方省く。"""
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
                gloss(8, start, end, x, seg_w, i == 0, i == n - 1)
            if i > 0 and seg_w >= 2:
                notch(8, start, end, x)
            # segment先頭のavatar。ringぶんの余白を見て、置ける幅があるsampleだけ表示する。
            # 2本目以降のsegmentは直前にノッチが立つので、その芯幅ぶん右へ逃がして重なりを避ける。
            lead = pad + (notch_w * 2 if i > 0 else 0)
            av_cx = x + lead + av_r
            fits_avatar = seg_w >= av_r * 2 + lead + pad
            if fits_avatar:
                out.append(disc(9, start, end, av_cx, seg_c))
                rep = (reps or {}).get(i)
                if rep:
                    ini = _ass_escape((_strip_bidi_controls(rep.get("nickname")).strip()[:1] or "＊")).upper()
                    out.append(text(9, start, end, int(round(av_cx)), cyi, 5, ini_fs, ini))
                    lane_reps.setdefault(i, rep)
            lane_tracks.setdefault(i, []).append(
                (end, int(round(av_cx - av_size / 2)) if fits_avatar else -av_size - 8)
            )
            # 数値はavatarを置いた残り幅に収まるときだけ描く(avatarを潰してまで出さない)。
            used = av_cx + av_r - x if fits_avatar else 0
            text_w = seg_w - used - pad
            if text_w >= 8:
                label = f"{max(0, score):,}"
                fs = min(num_fs, max(8, int(text_w / (len(label) * 0.62))))
                out.append(text(9, start, end, int(round(x + used + text_w / 2)), cyi, 5, fs, label))
            x += seg_w + seg_sep

    # 陣営ごとに合成する配信者アバター(overlay)。呼び出し側(_build_ass)が解決して焼き込む。
    # 解決できなかった陣営は、下に常に描いてあるイニシャル円盤がそのまま残る。
    avatar_specs: list = []

    def add_avatar_spec(rep, cx, start, end, xexpr=None):
        """陣営 representative host のアバターoverlay specを積む。user_id候補と保存URLを持たせ、
        解決側でcache/URLからcircle画像を作る。sizeは陣営色ringの内側に収まる直径。
        cacheの有無で積むかどうかを決めない: 解決側がcache→URL downloadの順で解決し、
        どちらも駄目なspecだけを落とすので、ここで先回りに諦めるとURL経路が死ぬ。"""
        if not rep:
            return
        uids = [rep.get("user_id"), rep.get("unique_id"), rep.get("nickname")]
        uids = [u for u in uids if u]
        url = rep.get("avatar") or ""
        if not uids and not url:
            return
        key = (avatar_key(str(uids[0])) if uids else hashlib.sha1(url.encode("utf-8")).hexdigest()[:16])
        spec = {
            "kind": "avatar",
            "key": key,
            "uids": [str(u) for u in uids],
            "url": url,
            "size": av_size,
            "x": int(round(cx - av_size / 2)),
            "y": int(round(cy - av_size / 2)),
            "start": start,
            "end": end,
            "static": True,
        }
        if xexpr is not None:
            spec["xexpr"] = xexpr
        avatar_specs.append(spec)

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
        # 形式ごとの分割はWeb(common.jsのbattleBarUnits)と一致させる。segment単位(陣営)は
        # core.battleのbattle_sidesが決めるので、2陣営なら2極、3陣営以上ならN分割:
        #   1v1 / チーム戦2v2 : 自陣/敵陣の合計(own/opp)で2分割。memberには割らない。
        #   個人マルチ(1:1:1等) : 陣営(=1人)ごとのN分割(lane)。
        # 2極は1v1もチーム戦も同じ emit_bar で描く(sm["own"]/["opp"]が陣営合計)。
        lane_order = battle_sides(parts)
        # score_seriesがparts(host別score)を持たない古いrecordでは陣営別の内訳を時系列で
        # 復元できず、N分割は描けない(全lane=0は emit_lanes の均等割りに落ちて捏造になる)。
        # その場合はrecordが実際に持つown/oppの2極だけを描く。
        has_lane_scores = any(sm.get("parts") for sm in series)
        multi = len(lane_order) > 2 and has_lane_scores
        # 陣営別内訳を欠く個人マルチ。旧collectorのown/oppは首位の敵という現行semanticsと
        # 別物なので、勝利タイムでheadline(opp_score)と混ぜない目印にする。
        lanes_unavailable = len(lane_order) > 2 and not has_lane_scores

        # Static elements over the whole visible span (battle + hold).
        # 落ち影 → track の順に敷く。影はbarと同じ形を下へずらした黒で、映像の明暗に関わらず
        # barが板として浮いて見えるようにする(平坦な塗りだけだと映像に沈んで安っぽく見える)。
        out.append(shape(6, win_start, disp_end, shadow_c,
                         _round_rect_path(left, top + shadow_off, track_w, bar_h, radius),
                         alpha=_SCORE_SHADOW_ALPHA))
        out.append(shape(7, win_start, disp_end, track_c,
                         _round_rect_path(left, top, track_w, bar_h, radius), alpha="\\1a&H45&"))
        if not multi:
            # 2極表示(1v1/チーム戦)は両端に representative host を出す。イニシャル円盤は常に
            # 下敷きとして描き、その上にavatar specを必ず積む。avatarはASSより後に合成される
            # ので、解決できれば写真がイニシャルを覆い、駄目なら円盤がそのまま残る。
            own_p = next((p for p in parts if p.get("is_own")), None)
            opp_p = max((p for p in parts if p.get("side") == "opp" and not p.get("is_own")),
                        key=lambda p: p.get("score", 0) or 0, default=None)
            # Strip invisible bidi/control chars before taking the initial so a
            # nickname leading with one does not yield a tofu box as the disc letter.
            own_ini = _ass_escape((_strip_bidi_controls((own_p or {}).get("nickname")).strip()[:1] or "自")).upper()
            opp_ini = _ass_escape((_strip_bidi_controls((opp_p or {}).get("nickname")).strip()[:1] or "敵")).upper()
            out.append(disc(9, win_start, disp_end, own_cx, own_c))
            out.append(text(9, win_start, disp_end, own_cx, cyi, 5, ini_fs, own_ini))
            out.append(disc(9, win_start, disp_end, opp_cx, opp_c))
            out.append(text(9, win_start, disp_end, opp_cx, cyi, 5, ini_fs, opp_ini))
            if use_real_avatars:
                add_avatar_spec(own_p, own_cx, win_start, disp_end)
                add_avatar_spec(opp_p, opp_cx, win_start, disp_end)
        # mode / clock は丸pillの中に収める。clockは毎秒張り替えるが、pillは最大幅("59:59")
        # で1枚だけ敷いて使い回す(毎秒pillを積むとdialogueが倍になるだけで見た目は同じ)。
        mode_plain = _battle_mode_label(battle)
        mode_pw = pill_w(mode_plain)
        clock_pw = pill_w("59:59")
        pill(8, win_start, disp_end, left - max(4, int(round(meta_fs * 0.55))), mode_pw)
        pill(8, win_start, disp_end, right + max(4, int(round(meta_fs * 0.55))) - clock_pw, clock_pw)
        out.append(text(9, win_start, disp_end, left, meta_y, 4, meta_fs, mode))

        # Fills + numbers per score sample (battle phase: scores change discretely).
        lane_tracks.clear()
        lane_reps.clear()
        parts_by_id = {str(p.get("user_id")): p for p in parts if p.get("user_id")}
        # laneの representative host = その陣営で最高scoreのmember(2極の敵陣選出と同じ基準)。
        lane_rep_by_index = {
            i: max((parts_by_id[pid] for pid in ids if pid in parts_by_id),
                   key=lambda p: p.get("score", 0) or 0, default=None)
            for i, (ids, _own) in enumerate(lane_order)
        }
        n = len(series)
        for i, sm in enumerate(series):
            s_pts = max(win_start, to_media(sm.get("t") or 0))
            e_pts = min(win_end, to_media(series[i + 1].get("t") or 0) if i + 1 < n else win_end)
            if e_pts <= s_pts:
                continue
            if multi:
                emit_lanes(s_pts, e_pts, _sample_lanes(sm, lane_order), lane_rep_by_index)
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
            last = series[-1]
            if multi:
                emit_lanes(win_end, disp_end, _sample_lanes(last, lane_order), lane_rep_by_index)
            elif lanes_unavailable:
                # headline(opp_score=首位の敵)はこのrecordのseries oppと別semanticsのため、
                # 混ぜると勝利タイムでバーが飛ぶ。seriesの最終値をそのまま保持する。
                emit_bar(win_end, disp_end, last.get("own") or 0, last.get("opp") or 0)
            else:
                fown = max(0, battle.get("own_score") or (last.get("own") or 0))
                fopp = max(0, battle.get("opp_score") or (last.get("opp") or 0))
                emit_bar(win_end, disp_end, fown, fopp)
            result = {"win": "WIN", "lose": "LOSE", "draw": "DRAW"}.get(battle.get("result"), "0:00")
            out.append(text(9, win_end, disp_end, right, meta_y, 6, meta_fs, result))

        # 個人マルチのlane avatar: このBattleぶんの位置履歴を1 laneあたり1つのoverlayへ畳む
        # (勝利タイムぶんも溜め終わってからなので、hold中も正しい位置に残る)。
        if use_real_avatars:
            for i, entries in lane_tracks.items():
                rep = lane_reps.get(i)
                if rep and entries:
                    add_avatar_spec(rep, 0, win_start, disp_end, xexpr=_step_xexpr(entries))
    return out, avatar_specs


def _build_bonus_dialogues(battles: list, to_media, video_duration: Optional[float],
                           width: int, height: int) -> list:
    """Match Bonus Mission（倍率タイム）をスコアバー直下に焼き込む。該当時間帯のみ表示:
    予告(まもなく条件で×N) → ミッション期間(条件で×N) → 達成(×N解放) → 倍率期間(×Nのcountdown帯)
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
            # 倍率タイム中のギフト倍率(reward_multiple)。達成条件("チーム 200ポイント"等)の
            # 直後に置くため、単なる"x2"だと条件値との掛け算に読める。何が2倍になるかを
            # 文言で明示する。倍率不明(START取り逃し)のときは値を騙らない。
            tag = f"ギフト{mult}倍" if mult else "ギフト倍率"
            preview_s = m.get("preview_start_ts")
            task_s = m.get("task_start_ts")
            task_dur = m.get("task_duration") or 0
            reward_s = m.get("reward_start_ts")
            reward_dur = m.get("reward_duration") or 0
            achieved = bool(m.get("achieved"))
            # 達成条件はミッション種別ごとに違う(指定ギフト/チーム/ポイント)。判別できる
            # prompt keyが無いmissionでは条件を伏せ、種別を誤って名乗らない。
            task_label = _bonus_task_label(m)

            # ミッションの実終了時刻: task_durationで確定。無ければ倍率開始へfallbackする。
            # reward_sがあれば必ずそれ以前へ丸める(倍率帯と重ねない)。
            mission_end = (task_s + task_dur) if (task_s and task_dur) else reward_s
            if mission_end and reward_s:
                mission_end = min(mission_end, reward_s)

            # ① 予告: ミッション開始前。これから来る倍率と達成条件を告知する(該当区間のみ)。
            if preview_s and task_s and task_s > preview_s:
                head = f"まもなく {task_label}で{tag}" if task_label else f"まもなく {tag}"
                band(preview_s, task_s, f"BONUS MISSION  {head}", gold, "\\1a&H50&")

            # ② ミッション期間: 進捗の逐次値は持たないため目標(達成で×N)を提示する。終端は
            #    倍率開始ではなくミッション実終了(mission_end)。以前はreward開始まで延ばしており
            #    達成〜倍率開始のsettle gap分だけ「達成で」表示が後ろへズレていた。
            if task_s and mission_end and mission_end > task_s:
                goal = f"{task_label}で{tag}" if task_label else f"達成で{tag}"
                band(task_s, mission_end, f"BONUS MISSION  {goal}", gold, "\\1a&H40&")

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
                                        f"{tag}  {_fmt_clock(re_ - t)}"))
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


def _subtitle_font(cfg: dict, height: int) -> int:
    """字幕のfont size(px)。Commentと同じく基準高さから実解像度へ比例させる。"""
    return max(8, int(round(cfg["video_overlay_subtitle_font_size"] * height / BASE_HEIGHT)))


def _build_subtitle_dialogues(segments: list, video_duration: Optional[float],
                              width: int, height: int, cfg: dict,
                              wide_em: float, narrow_em: float) -> tuple[list, dict]:
    """転写segmentをASSのDialogue行へ。時刻変換は一切しない。

    segments_jsonのstart/endは転写時にmedia軸(このmp4のPTS秒)へ再map済みで、焼き込みが
    使う軸と同一なので、壁時計mapper(to_media)へ通してはならない。通すと二重変換になる。
    """
    fs = _subtitle_font(cfg, height)
    pct = cfg.get("video_overlay_subtitle_position_percent") or 0
    cx = width // 2
    cy = int(round(height * pct / 100.0))
    max_w = int(width * SUBTITLE_WIDTH_FRAC)
    upper = video_duration if video_duration is not None else float("inf")
    lines: list = []
    dropped_after = 0
    truncated = 0
    for seg in segments:
        start = float(seg["start"])
        end = float(seg["end"])
        if start >= upper:
            dropped_after += 1
            continue
        end = min(end, upper)
        if end <= start:
            dropped_after += 1
            continue
        text = _ass_escape(_strip_bidi_controls(seg["text"]))
        if not text:
            continue
        wrapped = _wrap_text(text, fs, max_w, wide_em, narrow_em)
        if len(wrapped) > SUBTITLE_MAX_LINES:
            truncated += 1
            wrapped = wrapped[:SUBTITLE_MAX_LINES]
        body = "\\N".join(wrapped)
        lines.append(
            f"Dialogue: 7,{_ass_timestamp(start)},{_ass_timestamp(end)},Subtitle,,0,0,0,,"
            f"{{\\an5\\pos({cx},{cy})}}{body}"
        )
    if dropped_after or truncated:
        logger.info(
            "subtitle layout: %d line(s) placed, %d outside the video, %d truncated to %d lines",
            len(lines), dropped_after, truncated, SUBTITLE_MAX_LINES,
            extra={"event": "overlay.subtitles_laid_out",
                   "ctx": {"placed": len(lines), "dropped_after_end": dropped_after,
                           "truncated": truncated, "max_lines": SUBTITLE_MAX_LINES,
                           "font_size": fs, "position_percent": pct}},
        )
    return lines, {"placed": len(lines), "dropped_after_end": dropped_after,
                   "truncated": truncated, "font_size": fs}


def _build_ass(events: list, started_at: float, ended_at: Optional[float], video_duration: Optional[float],
               width: int, height: int, cfg: dict, anchors: Optional[list] = None,
               avatar_dir: Optional[Path] = None,
               wide_em: float = NOMINAL_WIDE_EM, narrow_em: float = NOMINAL_NARROW_EM,
               pts_gaps: Optional[list] = None,
               battles: Optional[list] = None,
               use_comment_layer: bool = True,
               time_source: str = "arrival",
               debug_sink: Optional[list] = None,
               media_pts: Optional[list] = None,
               subtitle_segments: Optional[list] = None) -> tuple[str, list, dict, Optional[dict]]:
    comment_fs = _comment_font(cfg, height)
    icon_px = _icon_px(cfg, height)
    coin_fs = max(10, int(round(height * COIN_REF_PX / BASE_HEIGHT)))
    outline = max(1, int(round(comment_fs * 0.08)))
    subtitle_fs = _subtitle_font(cfg, height)
    subtitle_outline = max(2, int(round(subtitle_fs * 0.10)))
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
                "Mode B output is unavailable for this recording",
                extra={"event": "overlay.time_bridge_unavailable",
                       "ctx": {"time_source": time_source, "mode": "B",
                               **_bridge_ctx(None)}},
            )
        else:
            logger.info(
                "overlay Mode B anchored: C=%.3f on %d/%d live events (%d backlog excluded)",
                source["c_value"], source["n_anchor"], source["n_samples"], source["n_backlog"],
                extra={"event": "overlay.time_bridge_resolved",
                       "ctx": {"time_source": time_source, "mode": "B",
                               **_bridge_ctx(source)}},
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
                "no live create_time to anchor bonus windows; placing them on the arrival axis",
                extra={"event": "overlay.time_bridge_unavailable",
                       "ctx": {"time_source": time_source, "mode": "A",
                               **_bridge_ctx(None)}},
            )
        else:
            # Mode Aでも同じ橋を建てているので、その原点Cと根拠件数をAでも構造化して残す。
            # 原点破綻はModeに依らず「全eventが動画長の外」という同じ症状で出る。
            logger.info(
                "overlay Mode A source bridge: C=%.3f on %d/%d live events (%d backlog excluded)",
                bonus_source["c_value"], bonus_source["n_anchor"],
                bonus_source["n_samples"], bonus_source["n_backlog"],
                extra={"event": "overlay.time_bridge_resolved",
                       "ctx": {"time_source": time_source, "mode": "A",
                               **_bridge_ctx(bonus_source)}},
            )
    to_bonus = to_media if bonus_source is None else bonus_source["source_to_pts"]
    dropped_no_ct = 0
    # 範囲外dropの内訳。過去のMode B原点破綻では全eventが範囲外へ落ちたにもかかわらず
    # 「描くものが無い」としか残らず、調査を正反対へ誘導した。境界のどちら側へ落ちたかと
    # offsetの実際の範囲を必ず数える。
    dropped_before = 0
    dropped_after = 0
    offset_min: Optional[float] = None
    offset_max: Optional[float] = None
    time_min: Optional[float] = None
    time_max: Optional[float] = None
    placed = 0

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
        raw_time = event.get("time")
        if raw_time is not None:
            time_min = raw_time if time_min is None else min(time_min, raw_time)
            time_max = raw_time if time_max is None else max(time_max, raw_time)
        offset = event_offset(event)
        if offset is None:
            dropped_no_ct += 1
            continue
        offset_min = offset if offset_min is None else min(offset_min, offset)
        offset_max = offset if offset_max is None else max(offset_max, offset)
        if debug_sink is not None and event.get("kind") in ("comment", "gift"):
            debug_sink.append({
                "kind": event.get("kind"),
                "time": event.get("time"),
                "create_time": event.get("create_time"),
                "offset_arrival": round(to_media(event["time"] or 0) + delay, 3),
                "offset": round(offset, 3),
                # プレビュー窓の自動選定がgiftの重みとmin diamondsを効かせるために読む。
                "diamonds": event.get("diamonds"),
                "nick": event.get("user_nickname") or "",
                "text": (event.get("comment") or event.get("text") or "")[:80],
            })
        if offset < 0:
            dropped_before += 1
            continue
        if offset > upper:
            dropped_after += 1
            continue
        placed += 1
        kind = event["kind"]
        if kind == "comment" and cfg["video_overlay_comments"]:
            body = event.get("comment") or event.get("text") or ""
            if body:
                comments.append({
                    "offset": offset,
                    "nick": event.get("user_nickname") or "",
                    "user_id": event.get("user_unique_id") or event.get("user_nickname") or "",
                    "text": body,
                    "emotes": event.get("emotes"),
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

    metrics = _comment_metrics(width, height, comment_fs, wide_em, narrow_em)
    # Comments are drawn by the PIL colour-emoji layer when its shaper is available;
    # only then are the ASS comment dialogues suppressed. Without it (Pillow/fonts
    # missing, or an explicit fallback after a layer-render failure) comments fall
    # back to the monochrome ASS feed so they still show.
    shaper = _make_comment_shaper() if (use_comment_layer and cfg["video_overlay_comments"] and comments) else None
    # Real-avatar resolution: a comment whose commenter avatar was cached at
    # capture time gets a composited circular photo (ASS disc omitted for it); the
    # rest keep the initial-letter disc. The circular photo can only be composited by
    # the PIL comment layer, so it is resolved only when the shaper exists. On the ASS
    # fallback path (shaper is None — Pillow/fonts missing or a colour-layer failure)
    # nothing can draw the photo; leaving avatars unresolved keeps has_avatar False so
    # every comment gets its initial-letter disc instead of a blank avatar hole.
    avatar_files: dict = {}
    if shaper is not None and avatar_dir is not None and cfg.get("video_overlay_real_avatars"):
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
    # Splice TikTok custom emotes into the comment text as inline-image sentinels
    # before layout so wrapping accounts for them (images downloaded by _resolve_emotes
    # before the layer render). Only on the colour-layer path; the ASS fallback has no
    # shaper and keeps the raw [shortcode]/placeholder text.
    if shaper is not None:
        _apply_comment_emotes(comments, shaper)
    placements = _layout_comment_feed(comments, metrics, comment_fs, comment_end, avatar_ids, shaper)
    comment_lines = [] if shaper is not None else _build_comment_dialogues(placements, metrics)
    drawable_comments = sum(1 for p in placements if not p["empty"])

    # Battle score bar (own/opp, time-mapped). Built before gifts so the gift band
    # can drop below the bar when it is present (avoids overlapping the top strip).
    score_lines: list = []
    bonus_lines: list = []
    score_avatars: list = []
    if cfg.get("video_overlay_score_bar") and battles:
        score_lines, score_avatars = _build_score_bar_dialogues(
            battles, to_score, video_duration, width, height,
            cfg.get("video_overlay_score_bar_hold_seconds") or 0,
            avatar_dir=avatar_dir,
            use_real_avatars=bool(cfg.get("video_overlay_real_avatars")),
            wide_em=wide_em, narrow_em=narrow_em,
        )
        bonus_lines = _build_bonus_dialogues(battles, to_bonus, video_duration, width, height)
    gift_band_top = SCORE_BAR_GIFT_BAND_TOP if score_lines else GIFT_BAND_TOP

    # STT字幕。時刻は既にmedia軸なのでmapperを通さない(_build_subtitle_dialogues参照)。
    subtitle_lines: list = []
    subtitle_stats = {"placed": 0, "dropped_after_end": 0, "truncated": 0, "font_size": 0}
    if cfg.get("video_overlay_subtitles") and subtitle_segments:
        subtitle_lines, subtitle_stats = _build_subtitle_dialogues(
            subtitle_segments, video_duration, width, height, cfg, wide_em, narrow_em)

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
    # Score-bar avatars are composited by the same overlay graph but are not gift
    # icons (no diamond count), so they are appended after the gift-count cap rather
    # than competing with gifts for the MAX_GIFT_OVERLAYS budget.
    overlays.extend(score_avatars)

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
        f"100,100,0,0,1,2,0,7,0,0,0,1\n"
        # STT字幕: 中央揃え・太めの縁取り。映像の明暗に関わらず読めるよう、Commentより
        # 強い輪郭と影を付ける(位置は行ごとの\posで与える)。
        f"Style: Subtitle,{COMMENT_FONT},{subtitle_fs},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,"
        f"100,100,0,0,1,{subtitle_outline},1,5,0,0,0,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    body = "\n".join(comment_lines + gift_lines + score_lines + bonus_lines + subtitle_lines)
    stats = {
        # Count drawable comments (not ASS lines) so the "nothing to draw" check holds
        # whether comments render via the PIL layer or the ASS fallback.
        "comments": drawable_comments,
        "gifts": len(gift_lines),
        "score": len(score_lines),
        "bonus": len(bonus_lines),
        "subtitles": len(subtitle_lines),
        "subtitle_diag": subtitle_stats,
        "icons": len(overlays),
        "dropped_icons": dropped_icons,
        "avatars": len(avatar_ids),
        "time_source": time_source,
        "source_unavailable": time_source == "server" and source is None,
        "source_diag": {k: source[k] for k in ("c_value", "n_anchor", "n_backlog", "n_samples")} if source else None,
        "dropped_no_create_time": dropped_no_ct,
        # 以下は「描くものが無い」判断を後から検証するための配置診断。件数だけでは
        # multi-recordingの2本目で窓がズレた場合と、そもそもeventが無い場合を区別できない。
        "events_total": len(events),
        "placed": placed,
        "dropped_before_start": dropped_before,
        "dropped_after_end": dropped_after,
        "dropped_ratio": (
            round((dropped_before + dropped_after + dropped_no_ct) / len(events), 4)
            if events else 0.0
        ),
        "offset_min": round(offset_min, 3) if offset_min is not None else None,
        "offset_max": round(offset_max, 3) if offset_max is not None else None,
        "events_time_min": round(time_min, 3) if time_min is not None else None,
        "events_time_max": round(time_max, 3) if time_max is not None else None,
        "video_duration_seconds": video_duration,
        # 呼び出し元が渡したevent窓そのもの。窓が録画と一致しているかは、この値なしには
        # 焼き込みのlogだけからは判定できない。
        "window_started_at": started_at,
        "window_ended_at": ended_at,
        "bridge": {"mode": "B" if time_source == "server" else "A",
                   **_bridge_ctx(source if time_source == "server" else bonus_source)},
    }
    comment_plan = None
    if shaper is not None and drawable_comments:
        comment_plan = {
            "placements": placements,
            "metrics": metrics,
            "avatar_files": avatar_files,
            "comment_fs": comment_fs,
            "shaper": shaper,
            # AI super-resolution of the composited avatars: only when the setting is on,
            # real avatars are in use, and a model is actually available. Resolved inside
            # the comment-layer render thread (never the event loop) — see
            # _render_comment_layer_sync. Imported lazily: the upscale stack imports this
            # module, so a top-level import here would be circular.
            "avatar_upscale": bool(
                avatar_files and cfg.get("video_overlay_avatar_upscale") and _avatars_upscalable()
            ),
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


def _apply_comment_emotes(comments: list, shaper: "_CommentShaper") -> None:
    """Splice TikTok custom emotes into each comment's text as inline-image sentinels.

    TikTok delivers chat sub/fansclub emotes out of band (the comment text holds only
    a ``[shortcode]`` or a space); the ``emotes`` field carries, per emote, the stable
    ``id``, an image ``url`` and the ``index`` where it belongs. Each distinct emote_id
    gets one Private-Use sentinel char (registered with the shaper so it tokenises and
    measures as an emoji-sized unit); the sentinels are placed at their indices and the
    original content characters fill the remaining slots. Images are downloaded later by
    _resolve_emotes. Comments without emote data are left untouched."""
    nxt = _EMOTE_SENTINEL_BASE
    sentinel_of: dict = {}
    for c in comments:
        raw = c.get("emotes")
        if not raw:
            continue
        try:
            emotes = raw if isinstance(raw, list) else json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not emotes:
            continue
        text = c.get("text") or ""
        max_idx = max((int(e.get("index", 0) or 0) for e in emotes), default=-1)
        n = max(len(text), max_idx + 1)
        slots: list = [None] * n
        for e in emotes:
            eid = str(e.get("id") or "")
            url = e.get("url") or ""
            if not eid or not url:
                continue
            sent = sentinel_of.get(eid)
            if sent is None:
                if nxt > 0xF8FF:  # exhausted the PUA block (thousands of distinct emotes)
                    continue
                sent = chr(nxt)
                nxt += 1
                sentinel_of[eid] = sent
                shaper.register_emote(sent, eid, url)
            idx = int(e.get("index", 0) or 0)
            if 0 <= idx < n and slots[idx] is None:
                slots[idx] = sent
        it = iter(text)
        out = [s if s is not None else next(it, "") for s in slots]
        out.append("".join(it))  # any content chars past the last slot
        c["text"] = "".join(out)


def _load_emote_image(path: Path):
    """Decode a downloaded emote image (webp/png) to RGBA, or None if undecodable."""
    from PIL import Image
    with Image.open(path) as im:
        return im.convert("RGBA")


async def _resolve_emotes(shaper: Optional["_CommentShaper"], cache_dir: Path,
                          on_step: Optional[Callable] = None) -> int:
    """Download every registered custom-emote image (cached by emote_id) and attach it
    to the shaper so the comment layer draws it inline. Returns the count resolved; a
    failed emote is skipped (its sentinel then draws as a transparent gap)."""
    if shaper is None or not shaper._emotes:
        return 0
    cache_dir.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_running_loop()
    by_id: dict = {}
    for sent, rec in shaper._emotes.items():
        by_id.setdefault(rec["id"], []).append(sent)
    resolved = 0
    for index, (eid, sents) in enumerate(by_id.items()):
        if on_step is not None:
            await on_step("絵文字", index, len(by_id))
        url = shaper._emotes[sents[0]]["url"]
        dest = cache_dir / f"{eid}.img"
        img = None
        try:
            if not (dest.is_file() and dest.stat().st_size > 0):
                await loop.run_in_executor(None, _download, url, dest)
            img = await loop.run_in_executor(None, _load_emote_image, dest)
        except (OSError, ValueError):
            logger.warning("emote download/decode failed (id=%s): %s", eid, url, exc_info=True)
            dest.unlink(missing_ok=True)
        if img is not None:
            for s in sents:
                shaper.set_emote_image(s, img)
            resolved += 1
    return resolved


async def _resolve_icons(overlays: list, cache_dir: Path,
                         on_step: Optional[Callable] = None) -> list:
    """Resolve each gift overlay to a local icon file. Cache first — icons are
    persisted at capture time (while URLs are fresh), so an expired URL still
    renders. On a cache miss, auto-resolve the URL from the current gift list by
    id/name (or the stored URL) and persist it. Specs that cannot be resolved are
    dropped; the coin count still shows."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_running_loop()
    name_index = _load_name_index(cache_dir)
    gift_map: Optional[dict] = None
    for index, spec in enumerate(overlays):
        if on_step is not None:
            await on_step("ギフトアイコン", index, len(overlays))
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


def _save_png(im, dest: Path) -> None:
    im.save(str(dest), format="PNG")


async def _resolve_score_avatars(specs: list, avatar_dir: Optional[Path], cache_dir: Path,
                                 on_step: Optional[Callable] = None) -> list:
    """Score-bar端の配信者アバターを、円形PNG(alpha付き)へ解決する。取得順は
    (1)avatar_dirのcache(capture時に保存された鮮度の高い画像。user_id/@id/nicknameのkey候補で探す)
    (2)無ければDBに保存された avatar URL をon-demand download。どちらも不可ならそのspecは落とし、
    バーの端は下に常に描かれるイニシャル円盤が残る(空にならない)。解決したspecには``file``を付ける。"""
    if not specs:
        return []
    cache_dir.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_running_loop()
    resolved: list = []
    # 同じ配信者のspecは1試合ぶん・全試合ぶん何本も出る(2極の両端、個人マルチのlane、Battle毎)。
    # 解決結果は(key,size)単位でmemo化し、失敗も覚える: 失効したCDN URLはdownloadが15s timeout
    # まで待つので、memoが無いとspec本数ぶん直列に再試行して出力が数分stallする。
    done: dict = {}
    for index, spec in enumerate(specs):
        if on_step is not None:
            await on_step("配信者アイコン", index, len(specs))
        size = int(spec.get("size") or 0)
        if size <= 0:
            continue
        memo_key = (spec["key"], size)
        if memo_key in done:
            png = done[memo_key]
            if png is not None:
                spec["file"] = png
                resolved.append(spec)
            continue
        src_img: Optional[Path] = None
        if avatar_dir is not None:
            for uid in spec.get("uids") or []:
                cand = avatar_dir / f"{avatar_key(str(uid))}.img"
                try:
                    if cand.is_file() and cand.stat().st_size > 0:
                        src_img = cand
                        break
                except OSError:
                    continue
        if src_img is None and spec.get("url"):
            dl = cache_dir / f"savatar_src_{spec['key']}.img"
            if dl.is_file() and dl.stat().st_size > 0:
                src_img = dl
            else:
                try:
                    await loop.run_in_executor(None, _download, spec["url"], dl)
                    if dl.stat().st_size > 0:
                        src_img = dl
                except (OSError, ValueError):
                    logger.warning("score avatar download failed: %s", spec.get("url"), exc_info=True)
                    dl.unlink(missing_ok=True)
        if src_img is None:
            done[memo_key] = None
            continue
        png = cache_dir / f"savatar_{spec['key']}_{size}.png"
        if not (png.is_file() and png.stat().st_size > 0):
            im = await loop.run_in_executor(None, _circle_avatar, src_img, size)
            if im is None:
                done[memo_key] = None
                continue
            try:
                await loop.run_in_executor(None, _save_png, im, png)
            except OSError:
                logger.warning("score avatar render failed: %s", png, exc_info=True)
                done[memo_key] = None
                continue
        done[memo_key] = png
        spec["file"] = png
        resolved.append(spec)
    return resolved


# Frames-per-second of the rendered comment overlay layer. The feed is a slow
# scroll, so the layer is sampled at the source fps (capped here to bound the
# per-frame render cost on long recordings); ffmpeg composites it by PTS so a lower
# layer fps than the video still aligns at each sampled instant. 中間fileの容量は
# frame数にほぼ比例するので、ここは容量の主要な調整点でもある(config側の説明を参照)。


def comment_layer_fps_cap() -> float:
    return config.get_overlay_layer_fps_cap()
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
    for kind, s in shaper.tokenize(line):
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
    # Line boxes are per-line (a line holding a custom emote is taller than the text
    # line height), so each row advances by its own box height, not by a fixed line_h.
    line_hs = p.get("line_hs") or [line_h] * (1 + len(p["body_lines"]))
    _draw_comment_line(draw, tile, shaper, p["nick_disp"], x_text, 0, line_hs[0], fs, (255, 224, 124, 255))
    y = line_hs[0]
    for ln, lh in zip(p["body_lines"], line_hs[1:]):
        _draw_comment_line(draw, tile, shaper, ln, x_text, y, lh, fs, (255, 255, 255, 255))
        y += lh
    return tile


# Per-alpha-step attenuation LUTs for the positional/fade-in dimming of comment
# tiles. Building the 256-entry table once per distinct quantised alpha (there are
# at most 256) and reusing it across frames/tiles removes the per-frame Python
# lambda LUT build the fade previously did for every dimmed tile every composited
# frame. Bounded to <=256 entries (<=64 KiB total), so it is a module-level cache.
_ALPHA_LUTS: dict[int, bytes] = {}


def _rm_frames_dir(d: Path) -> None:
    """Best-effort removal of the transient sparse-layer frame directory."""
    try:
        if d.exists():
            for p in d.iterdir():
                p.unlink(missing_ok=True)
            d.rmdir()
    except OSError:
        logger.warning("could not remove transient frames dir %s", d, exc_info=True)


def _alpha_lut(aq: int) -> bytes:
    """256-entry byte LUT scaling an alpha channel by ``aq``/255 (aq in 0..255)."""
    lut = _ALPHA_LUTS.get(aq)
    if lut is None:
        lut = bytes((v * aq) // 255 for v in range(256))
        _ALPHA_LUTS[aq] = lut
    return lut


def _comment_layer_tiles(placements: list, avatar_files: dict, m: dict, fs: int,
                         shaper: "_CommentShaper", width: int, height: int,
                         avatar_upscale: bool = False,
                         time_window: Optional[tuple] = None) -> Optional[dict]:
    """Rasterise the comment feed into per-comment tiles plus the scroll segments that
    reference them, and resolve the band geometry. Built from the whole-recording
    placements, so the burn-in and the preview share one and the same tile set and
    timing — a preview may only narrow which frames get composited, never how a frame
    is composed. Returns None when there is nothing to draw.

    ``time_window`` (preview only) skips rasterising comments that are never on screen
    inside it. This is a cost cut, not a layout change: the band geometry is still
    derived from every drawable comment in the recording, so a comment outside the
    window cannot move the ones inside it."""
    try:
        from PIL import Image  # noqa: F401  (availability check; used by the compositor)
    except ImportError:
        logger.warning("Pillow not installed; cannot render comment layer")
        return None

    avatar_d, line_h = m["avatar_d"], m["line_h"]
    x_text, text_max_w, gap = m["x_text"], m["text_max_w"], m["gap"]

    # This runs in a worker thread (see _render_comment_layer), so the AI super-
    # resolution GPU inference here never blocks the event loop. Each avatar is
    # upscaled once and cached on disk; a failed/unavailable upscale returns None and
    # the raw 72px avatar is used (quality degraded, never a render failure).
    circ: dict = {}
    for uid, path in avatar_files.items():
        src = Path(path)
        if avatar_upscale:
            up = _upscale_avatar(src)
            if up is not None:
                src = up
        im = _circle_avatar(src, avatar_d)
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
    if time_window is not None:
        win_start, win_end = time_window
        drawable = [
            p for p in drawable
            if any(seg["start"] <= win_end and seg["end"] > win_start for seg in p["segments"])
        ]
        if not drawable:
            return None
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
    return {"region_x": region_x, "region_y0": region_y0, "region_w": region_w,
            "region_h": region_h, "segments": segments, "layer_end": layer_end}


def _comment_frame_state(t: float, live: list, region_y0: int):
    """Draw ops + a content signature for time ``t``. The signature captures every
    visible tile's quantised position and alpha, so an unchanged signature means a
    pixel-identical frame — letting the layer loop skip recompositing through the long
    static stretches between comments (only slides/fade-ins actually change)."""
    slide = SLIDE_SECONDS / 2.0  # seconds; matches slide_cs (ms) in the ASS \move
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


def _composite_comment_frame(ops: list, region_x: int, region_w: int, region_h: int):
    """Compose one RGBA band image from the draw ops of a single instant."""
    from PIL import Image

    layer = Image.new("RGBA", (region_w, region_h), (0, 0, 0, 0))
    for tile, y, alpha in ops:
        draw_tile = tile
        if alpha < 0.999:
            draw_tile = tile.copy()
            draw_tile.putalpha(tile.getchannel("A").point(_alpha_lut(int(alpha * 255))))
        layer.alpha_composite(draw_tile, (region_x, y))
    return layer


def _comment_still_frame(tiles: dict, t: float):
    """The comment band exactly as it looks at media time ``t``, as an RGBA image.
    Uses the same tiles and the same slide/fade maths as the video layer, so the still
    preview cannot show a different feed from the one the burn-in would produce."""
    segments = tiles["segments"]
    live = [seg for seg in segments if seg[1] <= t < seg[2]]
    _sig, ops = _comment_frame_state(t, live, tiles["region_y0"])
    if not ops:
        return None
    return _composite_comment_frame(ops, tiles["region_x"], tiles["region_w"], tiles["region_h"])


def _render_comment_layer_sync(placements: list, avatar_files: dict, m: dict, fs: int,
                               shaper: "_CommentShaper", width: int, height: int, fps: float,
                               out_path: Path, avatar_upscale: bool = False,
                               window: Optional[tuple] = None,
                               progress: Optional[Callable] = None) -> Optional[tuple]:
    """Render the comment feed as an alpha overlay video (qtrle .mov) using Pillow so
    emoji show in colour. Each comment is rasterised once to a tile and scrolled/faded
    using the same placements/timing the ASS layer would have used, so comments stay
    locked to the footage. Only the bottom-left comment band is rendered and composited
    as a single ffmpeg overlay regardless of comment count. Returns
    (out_path, overlay_x, overlay_y, stats) or None when there is nothing to draw.
    ``stats`` carries the frame count / fps / rendered length so the caller can verify
    the layer covers the whole base (a layer shorter than the base makes comments
    vanish mid-video without any error — see _log_duration_check).

    ``window`` is a (start, end) media-PTS window for the burn-in preview: only frames
    inside it are composited, and the produced file starts at its first frame (time 0),
    so the caller must offset the layer input by ``window[0]`` when compositing. The
    tiles and their timings are unchanged — the window narrows what is rendered, never
    how it is placed."""
    tiles = _comment_layer_tiles(placements, avatar_files, m, fs, shaper, width, height,
                                 avatar_upscale, time_window=window)
    if tiles is None:
        return None
    region_x, region_y0 = tiles["region_x"], tiles["region_y0"]
    region_w, region_h = tiles["region_w"], tiles["region_h"]
    segments, layer_end = tiles["segments"], tiles["layer_end"]

    if window is None:
        first_frame = 0
        n_frames = int(math.ceil(layer_end * fps)) + 1
    else:
        win_start, win_end = window
        first_frame = max(0, int(math.floor(win_start * fps)))
        # 窓の終端までは必ず覆う(layer_endで打ち切らない)。commentが尽きた後は同一signature
        # のframeがsparse圧縮で1枚に畳まれるだけなので、costは増えない。
        last_frame = int(math.ceil(win_end * fps)) + 1
        n_frames = max(1, last_frame - first_frame)

    # The feed is static except during each comment's brief slide/fade-in, so instead
    # of streaming every CFR frame to the encoder (hundreds of thousands of full RGBA
    # writes on a multi-hour recording), only frames whose content signature changes
    # are materialised; each is then held for its run length via the concat demuxer's
    # per-frame duration. The output is still CFR at ``fps`` (``-r``/``-vsync cfr``
    # resample the held frames onto the exact 1/fps grid, and every duration is an
    # integer number of frames, so no boundary drifts), which keeps the overlay
    # frame-locked exactly as the dense stream was — only the redundant static frames
    # are elided. Distinct frames live transiently on disk (bounded by comment
    # activity, not by duration) under a per-render frames dir, removed when done.
    frames_dir = out_path.with_name(out_path.stem + ".frames")
    _rm_frames_dir(frames_dir)
    try:
        frames_dir.mkdir(parents=True)
    except OSError as exc:
        # ここはdisk満杯が最初に当たる2箇所のうちの1つ。pathとerrnoと空き容量が無いと、
        # 権限・path不正・ENOSPCが「layer render failed」の一行に潰れて区別できない。
        logger.error(
            "comment layer: cannot create frames dir %s", frames_dir, exc_info=True,
            extra={"event": "overlay.frames_dir_create_failed",
                   "ctx": {"path": str(frames_dir), "frames_written": 0,
                           **_oserror_ctx(exc), **_disk_ctx(frames_dir.parent)}},
        )
        return None

    entries: list[tuple[str, int]] = []  # (png filename, start frame index)
    ptr = 0
    live: list = []
    prev_sig = None
    # 進捗はdistinct frameの生成に律速される(大半のframeは直後のcontinueで即skipされる)ので、
    # gateはcontinueの後、実際に1枚描く分岐の中に置く。
    gate = IntervalGate(progress_interval_seconds(config.get_log_progress_interval_seconds()))
    # UIへ返す進捗はlog gateとは別。logは間引いて良いが、画面の%は数十分無言にできない。
    ui_gate = IntervalGate(config.get_job_progress_min_interval_seconds())
    render_started = time.monotonic()
    try:
        for f in range(first_frame, first_frame + n_frames):
            if progress is not None and ui_gate.ready():
                done = f - first_frame
                progress("layer", done / n_frames if n_frames else 1.0,
                         f"{done:,}/{n_frames:,}フレーム")
            # JobCancelledはBaseException(下のexcept Exceptionでは捕まらない)。ここで捕まると
            # cancelがASS転落という「品質を落とした成功」に化けるため、意図的に素通りさせる。
            cancel.check_cancelled()
            t = f / fps
            while ptr < len(segments) and segments[ptr][1] <= t:
                live.append(segments[ptr])
                ptr += 1
            if live:
                live = [seg for seg in live if seg[2] > t]
            sig, ops = _comment_frame_state(t, live, region_y0)
            if sig == prev_sig and entries:
                continue  # unchanged: extends the current distinct frame's run
            layer = _composite_comment_frame(ops, region_x, region_w, region_h)
            name = f"f{len(entries):07d}.png"
            layer.save(frames_dir / name)
            # frame indexはfileの先頭を0とする相対値。窓ありでもconcatのdurationが
            # そのまま使えるようにするため、絶対frame番号は持ち込まない。
            entries.append((name, f - first_frame))
            prev_sig = sig
            if gate.ready():
                logger.debug(
                    "comment layer progress: %d distinct frames at %.1fs of %.1fs",
                    len(entries), t, layer_end,
                    extra={"event": "overlay.comment_layer_progress_reported",
                           "ctx": {"frames_written": len(entries), "frame_index": f,
                                   "n_frames": n_frames, "position_seconds": round(t, 3),
                                   "layer_duration_seconds": round(layer_end, 3),
                                   "fps": round(fps, 3),
                                   "duration_ms": int((time.monotonic() - render_started) * 1000)}},
                )
    except JobCancelled:
        # 展開済みpngは1配信ぶんで数GBになる。cancelでもここを掃除しないと、誰も参照しない
        # frames dirがdiskに残り続ける。
        _rm_frames_dir(frames_dir)
        raise
    except Exception as exc:
        # disk満杯(ENOSPC)が実際に最初に当たる地点。ここでreturn Noneすると下のqtrle encode
        # には到達しないため、encode側にsignatureを置いても実経路では一度も発火しない。
        # 書けたframe数・展開済みbyte・空き容量をこの行に必ず載せる。
        logger.error(
            "comment layer frame render failed at frame %d of %d", f, n_frames, exc_info=True,
            extra={"event": "overlay.comment_layer_frame_failed",
                   "ctx": {"path": str(frames_dir), "frames_written": len(entries),
                           "frame_index": f, "n_frames": n_frames,
                           "frames_dir_bytes": _dir_bytes(frames_dir),
                           "fps": round(fps, 3),
                           **_oserror_ctx(exc), **_disk_ctx(frames_dir)}},
        )
        _rm_frames_dir(frames_dir)
        return None

    if not entries:
        _rm_frames_dir(frames_dir)
        return None

    # concat playlist: hold each distinct frame until the next begins (the last until
    # the stream ends). The final entry is repeated because the concat demuxer ignores
    # the last listed duration. Durations are integer-frame multiples of 1/fps.
    lines = ["ffconcat version 1.0"]
    for i, (name, start) in enumerate(entries):
        end = entries[i + 1][1] if i + 1 < len(entries) else n_frames
        lines.append(f"file '{name}'")
        lines.append(f"duration {(end - start) / fps:.9f}")
    lines.append(f"file '{entries[-1][0]}'")
    (frames_dir / "list.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    cancel.check_cancelled()
    if progress is not None:
        progress("layer", 1.0, f"{n_frames:,}/{n_frames:,}フレーム")
    # Popen + register: qtrle encoding a full recording's layer runs for minutes, and an
    # unregistered process is one the cancel cannot reach — the operator would keep
    # waiting on "取り消し中…" until this finished on its own.
    layer_seconds = n_frames / fps if fps > 0 else 0.0
    proc = subprocess.Popen(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
         *(["-progress", "pipe:1", "-nostats"] if progress is not None else []),
         "-f", "concat", "-safe", "0", "-i", "list.txt",
         "-vsync", "cfr", "-r", f"{fps:.6f}",
         "-c:v", "qtrle", "-pix_fmt", "argb", str(out_path.resolve())],
        cwd=str(frames_dir), stdin=subprocess.DEVNULL,
        stdout=(subprocess.PIPE if progress is not None else None),
    )
    cancel.register_process(proc)
    try:
        # 数十GBのqtrleを吐くこの pass も数分〜数十分かかる。worker thread内なので
        # -progress を同thread内でそのまま読み進める(loopは塞がない)。
        if progress is not None and proc.stdout is not None:
            pump_progress_sync(proc.stdout, layer_seconds, progress, "layer_encode")
        proc.wait()
    finally:
        cancel.forget_process(proc)
    frames_bytes = _dir_bytes(frames_dir)
    _rm_frames_dir(frames_dir)
    if cancel.is_cancelled():
        out_path.unlink(missing_ok=True)
        cancel.check_cancelled()
    if proc.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        logger.error(
            "comment layer encoder failed (rc=%s, output_exists=%s)",
            proc.returncode, out_path.exists(),
            extra={"event": "overlay.comment_layer_encode_failed",
                   "ctx": {"path": str(out_path.resolve()), "returncode": proc.returncode,
                           "frames_written": len(entries), "n_frames": n_frames,
                           "frames_dir_bytes": frames_bytes, "fps": round(fps, 3),
                           **_disk_ctx(out_path.parent)}},
        )
        out_path.unlink(missing_ok=True)
        return None
    layer_stats = {
        "frames_written": len(entries),
        "n_frames": n_frames,
        "fps": round(fps, 3),
        # 全尺のfeedが何秒まで続くか(窓の有無に依らない)と、この file が実際に覆う長さ。
        # 窓ありのときに両者が一致すると思い込むと、尾切れの検知が効かなくなる。
        "layer_duration_seconds": round(layer_end, 3),
        "rendered_seconds": round(n_frames / fps, 3),
        "window_start_seconds": round(first_frame / fps, 3) if window is not None else None,
        "size_bytes": out_path.stat().st_size,
        "duration_ms": int((time.monotonic() - render_started) * 1000),
    }
    logger.info(
        "comment layer: %d distinct frames held over %d total (sparse)", len(entries), n_frames,
        extra={"event": "overlay.comment_layer_rendered",
               "ctx": {"path": str(out_path.resolve()), **layer_stats}},
    )
    return out_path, region_x, region_y0, layer_stats


async def _render_comment_layer(placements: list, avatar_files: dict, m: dict, fs: int,
                                shaper: "_CommentShaper", width: int, height: int, fps: float,
                                out_path: Path, avatar_upscale: bool = False,
                                window: Optional[tuple] = None,
                                progress: Optional[Callable] = None) -> Optional[tuple]:
    """Async wrapper: the PIL/ffmpeg render is blocking, so run it off the loop.

    ``to_thread`` rather than ``run_in_executor``: it copies the caller's context into the
    worker, which is what lets the avatar super-resolution inside recognise that this job
    already holds the GPU slot instead of deadlocking behind itself.

    ``progress`` は ``progress(段階key, 達成率, 詳細)`` の**同期**callback。worker thread
    から呼ばれるので、loopへ戻す橋渡し(JobProgress.thread_cb)を通す必要がある。"""
    return await asyncio.to_thread(
        _render_comment_layer_sync,
        placements, avatar_files, m, fs, shaper, width, height, fps, out_path, avatar_upscale,
        window, progress,
    )


def _build_filter_complex(overlays: list, icon_px: int, ass_name: str, layer_input: Optional[int] = None,
                          layer_y: int = 0, scale_to: Optional[tuple] = None,
                          cfr_fps: Optional[float] = None) -> str:
    """Build the ffmpeg filter graph: scale each unique icon once, split it into
    one stream per instance, then slide each instance in/out over its window. When
    ``scale_to`` is given, the source frame is first upscaled to that (w, h) so the
    overlays — authored at the same render resolution — composite crisply onto it.
    When ``cfr_fps`` is given (VFR source with no comment layer), the base is
    normalised to that constant frame rate in this same graph. The ``fps`` filter
    preserves each frame's time position (it only regularises spacing), so the
    overlay/ASS timeline — computed in the source mp4's PTS seconds — still aligns
    with the normalised base.

    Note: when a comment layer is composited on a VFR source, ``fps`` folded into this
    graph is NOT enough — overlay's framesync couples to the fps filter's bursty
    in-graph frame delivery and the separately-rendered layer drifts tens of seconds
    out mid-stream (comments vanish where the source's real rate dips). That case runs
    the CFR normalisation as a separate first pass (see ``_run_ffmpeg``) so this graph
    receives an already-CFR base and ``cfr_fps`` is None here — the layer then stays
    locked. Gifts and the ass score bar are timestamp-driven (``enable=between(t,...)``
    / ``ass``), not framesync, so they never needed the separate pass."""
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
        # Each file is scaled once to its own size: gift icons to icon_px, score-bar
        # avatars to the disc diameter they carry. Specs sharing a file share a size.
        sz = int(specs[0].get("size") or icon_px)
        chain = f"[{input_index}:v]scale={sz}:{sz},format=rgba"
        if count == 1:
            parts.append(f"{chain}[{base}_0]")
        else:
            outs = "".join(f"[{base}_{k}]" for k in range(count))
            parts.append(f"{chain},split={count}{outs}")
        label_queue[file] = [f"{base}_{k}" for k in range(count)]
        input_index += 1

    # Gift icons (and the comment layer) composite BELOW the ASS text, so gift coin
    # numbers/labels draw over their icon. Score-bar avatars must sit ABOVE ASS: the
    # ASS score bar draws a translucent track over the whole bar, so an avatar left
    # beneath it would be dimmed by that track. Static specs are therefore held back
    # and composited after the ass filter.
    slide_specs = [s for s in overlays if not s.get("static")]
    static_specs = [s for s in overlays if s.get("static")]

    cur = base_label
    step = 0
    for spec in slide_specs:
        label = label_queue[str(spec["file"])].pop(0)
        s, e = spec["start"], spec["end"]
        out = f"[v{step}]"
        # Gift icon: slide in/out horizontally to its rest x.
        sz = int(spec.get("size") or icon_px)
        x = spec["x_rest"]
        fi = f"clip((t-{s})/{SLIDE_SECONDS}\\,0\\,1)"
        fo = f"clip(({e}-t)/{SLIDE_SECONDS}\\,0\\,1)"
        # slideは枠内(x=0)から開始する。画面外(-sz-20)から入れるとslide中のiconが左端で
        # 切れたまま表示され、labelの開始x clampと合わせて枠外描画を無くす。
        xexpr = f"0+({x})*min({fi}\\,{fo})"
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
    # ass output is the final [vout] unless score-bar avatars still composite on top.
    ass_out = "[assed]" if static_specs else "[vout]"
    parts.append(f"{cur}ass={ass_name}{ass_out}")
    cur = ass_out
    for i, spec in enumerate(static_specs):
        label = label_queue[str(spec["file"])].pop(0)
        s, e = spec["start"], spec["end"]
        out = "[vout]" if i == len(static_specs) - 1 else f"[a{i}]"
        # Score-bar avatar: fixed position over the disc, on top of the ass bar. 個人マルチの
        # lane avatarはsegmentと一緒に動くので、instanceを増やさずxを時間の階段式で与える
        # (``xexpr``。segmentが狭くavatarを置けない区間は画面外のxへ退避している)。
        xexpr = spec.get("xexpr")
        xarg = f"'{xexpr}'" if xexpr else str(int(spec.get("x", spec.get("x_rest", 0))))
        parts.append(
            f"{cur}[{label}]overlay=x={xarg}:y={spec['y']}:"
            f"eof_action=repeat:enable='between(t,{s},{e})'{out}"
        )
        cur = out
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
                logger.info("video overlay encoder: %s (codec=%s)", name, codec,
                            extra={"event": "overlay.encoder_resolved",
                                   "ctx": {"encoder": name, "codec": codec,
                                           "probed": list(order)[:list(order).index(name) + 1]}})
                _resolved_encoders[codec] = name
                return name
        # Requested codec unavailable: never fail the render — fall back to H.264.
        # 利用者が選んだcodecでは出力されず、file sizeと画質が確定的に変わる(自動回復ではない)。
        # TODO: 規約上のfallback禁止に該当する。廃止は別taskで判断する。
        logger.warning(
            "no working encoder for codec=%s; falling back to libx264", codec,
            extra={"event": "overlay.encoder_fallback_used",
                   "ctx": {"codec": codec, "encoder": "libx264",
                           "probed": list(order),
                           "degraded": "requested codec unavailable; CPU H.264 used"}},
        )
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


async def _duration_seconds(src: Path) -> Optional[float]:
    """Duration in seconds, or None when it could not be probed."""
    us = await _probe_duration_us(src)
    return us / 1_000_000 if us else None


def _log_duration_check(event: str, message: str, *, fps: float,
                        layer_seconds: Optional[float], base_seconds: Optional[float],
                        src_seconds: Optional[float], compare: tuple,
                        n_frames: Optional[int] = None, ctx: Optional[dict] = None) -> None:
    """生成物のdurationが基準stream(base)と一致しているかを1行で残す。

    過去障害「焼き込みcommentが中盤で数分消える」の本質は、CFRのcomment layerがVFRの
    baseより早く終わることだった。合成filterのeof_action=passはlayerが尽きた瞬間に
    無警告で消える設計なので、生成物のdurationを測っていない限り症状しか残らない。
    1 jobあたりprobe 2回。

    警告は**不足側のみ**。この障害は片側にしか起きない: layerがbaseより短ければcommentが
    その時点で消えるが、長ければ余剰は合成時に捨てられるだけで無害である。実測でもconcat
    demuxerが最終frameを1つ余分に並べる仕様上、layerは常時2 frameほどbaseより長い。両側を
    等しく警告すると毎回warningが出て、本物の不足がその中に埋もれる。超過側もdeltaとして
    必ず記録されるので、JSONL側からは同じ精度で追える。

    ``compare`` は差を取る2つのfield名(例 ("layer", "base"))。どちらか一方でも測れなければ
    差はNoneのまま残し、既定値で埋めた「一致した」という誤った記録は作らない。
    """
    measured = {
        "layer_duration_seconds": round(layer_seconds, 3) if layer_seconds is not None else None,
        "base_duration_seconds": round(base_seconds, 3) if base_seconds is not None else None,
        "src_duration_seconds": round(src_seconds, 3) if src_seconds is not None else None,
    }
    left = measured[f"{compare[0]}_duration_seconds"]
    right = measured[f"{compare[1]}_duration_seconds"]
    delta = None if (left is None or right is None) else round(left - right, 3)
    tolerance = (
        config.get_log_overlay_duration_tolerance_frames() / fps if fps > 0 else None
    )
    short = delta is not None and tolerance is not None and delta < -tolerance
    payload = dict(measured)
    payload.update({
        "duration_delta_seconds": delta,
        "duration_compared": list(compare),
        "duration_shortfall": short,
        "duration_tolerance_seconds": round(tolerance, 4) if tolerance is not None else None,
        "n_frames": n_frames,
        "fps": round(fps, 3),
        "duration_measured": delta is not None,
    })
    payload.update(ctx or {})
    logger.log(
        logging.WARNING if short else logging.INFO,
        message, left, right, delta,
        extra={"event": event, "ctx": payload},
    )


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


def _prepass_encoder_args(name: str) -> list:
    """Visually-transparent, fast encode args for the transient CFR base. It is re-encoded
    by the main pass, so it only needs to be good enough to feed that pass (a low CQ/CRF),
    and fast (a light preset) — the GPU encoders keep this pass off the CPU and quick.

    品質は設定(get_overlay_prepass_quality)。以前はCQ16固定で、2h43mの録画で17GBに達し
    comment layerと合わせて同時38GBを占めていた。捨て物に無劣化を求めるのは割に合わない。
    CPU側libx264はCQと同じ数字ではCRFの方が重くなるので、2段ぶん緩めて釣り合わせる。"""
    quality = config.get_overlay_prepass_quality()
    if name in ("h264_nvenc", "hevc_nvenc", "av1_nvenc"):
        return ["-c:v", name, "-preset", "p4", "-rc", "vbr", "-cq", str(quality), "-b:v", "0"]
    if name in ("h264_qsv", "hevc_qsv", "av1_qsv"):
        return ["-c:v", name, "-global_quality", str(quality), "-preset", "veryfast"]
    if name in ("h264_amf", "hevc_amf", "av1_amf"):
        return ["-c:v", name, "-rc", "cqp", "-qp_i", str(quality), "-qp_p", str(quality),
                "-quality", "speed"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(max(0, quality - 2))]


async def _prepass_cfr(src: Path, out: Path, scale_to: Optional[tuple], cfr_fps: float, cwd: Path,
                       window: Optional[tuple] = None,
                       on_progress: Optional[ProgressCb] = None) -> None:
    """Render the scaled/CFR-normalised base to a transient near-lossless file so the
    comment-layer overlay composites onto a real CFR stream (clean container PTS),
    not the fps filter's in-graph output. Overlay's framesync locks to a real file but
    drifts against the folded fps output on VFR sources — see _build_filter_complex.
    Uses the GPU encoder when available (this base can be several GB for a long
    recording; a CPU pass would be slow). Audio is copied through so the main pass can
    still map it from this base.

    ``window`` limits the base to a (start, end) media-PTS window for the burn-in
    preview — this is where the preview's cost actually drops, since a whole-recording
    base is the single largest intermediate. ``-ss``/``-t`` are input options (a plain
    duration measured from the seek point, unambiguous under ``-copyts``) and
    ``-copyts`` keeps the source's own timestamps, so the ASS/gift timeline — built for
    the whole recording and never re-derived — still lines up with the windowed base.
    The windowed base carries no audio: the preview is a visual check, and stream-copied
    audio cannot be cut at an arbitrary point without shifting its start."""
    seek: list[str] = []
    tail: list[str] = ["-c:a", "copy"]
    if window is not None:
        win_start, win_end = window
        seek = ["-ss", f"{win_start:.6f}", "-t", f"{max(0.0, win_end - win_start):.6f}"]
        tail = ["-an", "-copyts"]
    vf: list[str] = []
    if scale_to is not None:
        sw, sh = scale_to
        vf.append(f"scale={sw}:{sh}:flags=lanczos")
    vf.append(f"fps={cfr_fps:.6f}")
    # Prefer the H.264 GPU encoder for the transient (fastest, universally decodable);
    # falls back to CPU libx264 only when no hardware encoder works here.
    encoder = await video_encoder_name("h264")
    log_path = out.with_name(out.stem + ".prepass.log")
    log_file = open(log_path, "wb")
    proc = None
    # この pre-pass は4.65時間の録画で20分以上かかる。進捗を出さないと、jobは動いている
    # のに%が据え置きになり「止まった」ようにしか見えない(実際にそう報告された)。
    total_us = None
    if on_progress is not None:
        if window is not None:
            total_us = int(max(0.0, window[1] - window[0]) * 1_000_000) or None
        else:
            total_us = await _probe_duration_us(src)
    report = on_progress if total_us else None
    try:
        cancel.check_cancelled()
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
            *(["-progress", "pipe:1", "-nostats"] if report else []),
            *seek, "-i", str(src), "-vf", ",".join(vf),
            *_prepass_encoder_args(encoder),
            # faststartは付けない。moovを先頭へ移す処理はfile全体を書き直すpassで、
            # 数十GBになるこの中間fileでは無視できない時間を食う。読むのは次のffmpegが
            # localのfileを順に流すだけなので、先頭にmoovが在る必要が無い。
            *tail, str(out),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=(asyncio.subprocess.PIPE if report else asyncio.subprocess.DEVNULL),
            stderr=log_file, cwd=str(cwd),
        )
        cancel.register_process(proc)
        if report:
            # 窓ありは-copytsでsourceの絶対PTSが出るので、窓開始を引いて0起点へ戻す。
            base_us = int(window[0] * 1_000_000) if window is not None else 0
            await pump_ffmpeg_progress(proc.stdout, total_us, report, base_us)
        await proc.wait()
    finally:
        if proc is not None:
            cancel.forget_process(proc)
        log_file.close()
    if cancel.is_cancelled():
        out.unlink(missing_ok=True)
        log_path.unlink(missing_ok=True)
        cancel.check_cancelled()
    if proc.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        tail = ""
        try:
            tail = log_path.read_text(
                encoding="utf-8", errors="replace")[-config.get_log_ffmpeg_stderr_chars():]
        except OSError:
            logger.warning(
                "pre-pass ffmpeg log unreadable: %s", log_path, exc_info=True,
                extra={"event": "overlay.ffmpeg_log_unreadable", "ctx": {"path": str(log_path)}},
            )
        out.unlink(missing_ok=True)
        logger.error(
            "CFR base pre-pass failed for %s via %s", src.name, encoder,
            extra={"event": "overlay.prepass_failed",
                   "ctx": {"path": str(out.resolve()), "stem": src.stem,
                           "encoder": encoder, "fps": round(cfr_fps, 3),
                           "returncode": proc.returncode,
                           "stderr_tail": tail, **_disk_ctx(out.parent)}},
        )
        raise RuntimeError(f"CFR正規化(pre-pass)に失敗しました（ffmpeg）。{tail}".strip())
    log_path.unlink(missing_ok=True)
    # baseがsourceより短ければ、この時点で映像そのものが尾切れしている。合成後に気付いても
    # 原因がbaseかlayerか切り分けられないので、pre-pass直後に測る。
    # 窓ありのbaseはsourceより短くて当然なので、比較対象は窓の長さにする(全尺と比べると
    # 毎回shortfall warningになり、本物の尾切れがその中に埋もれる)。
    expected = await _duration_seconds(src)
    if window is not None:
        expected = max(0.0, window[1] - window[0])
    _log_duration_check(
        "overlay.prepass_completed",
        "CFR base pre-pass done: base=%ss src=%ss (delta=%ss)",
        fps=cfr_fps,
        layer_seconds=None,
        base_seconds=await _duration_seconds(out),
        src_seconds=expected,
        compare=("base", "src"),
        ctx={"path": str(out.resolve()), "stem": src.stem, "encoder": encoder,
             "window_start_seconds": round(window[0], 3) if window is not None else None,
             "window_end_seconds": round(window[1], 3) if window is not None else None,
             "size_bytes": out.stat().st_size},
    )


async def _run_ffmpeg(src: Path, overlays: list, icon_px: int, ass_name: str, out: Path, cwd: Path, quality: int,
                      codec: str = "auto", comment_layer: Optional[tuple] = None,
                      on_progress: Optional[ProgressCb] = None,
                      scale_to: Optional[tuple] = None,
                      cfr_fps: Optional[float] = None,
                      window: Optional[tuple] = None,
                      seek_source: bool = False,
                      layer_offset: float = 0.0,
                      audio_normalize: Optional[dict] = None) -> None:
    """``window`` (burn-in preview only) keeps the source's absolute timestamps via
    ``-copyts`` and trims the output to that media-PTS window, so the filter graph — the
    very same graph the whole-recording burn-in builds, with the same ASS and the same
    gift ``enable=between(t,...)`` expressions — needs no rewriting. ``seek_source``
    applies the seek to input 0; it is False when input 0 is a CFR base the pre-pass has
    already windowed. ``layer_offset`` shifts the comment layer input (that file always
    starts at 0) onto the window's absolute position."""
    log_path = out.with_name(out.stem + ".ffmpeg.log")
    log_file = open(log_path, "wb")
    # Compositing a comment layer on a VFR source needs a real CFR base (framesync
    # desyncs against fps folded into the overlay graph). That base is produced by a
    # separate pre-pass the caller runs concurrently with the comment-layer render
    # (see _render_variant); by the time it reaches here ``src`` is already the CFR
    # base and ``scale_to``/``cfr_fps`` are None. Gifts/ass are timestamp-driven, so
    # without a layer the CFR normalisation stays folded into this graph via cfr_fps.
    win_start, win_end = window if window is not None else (0.0, 0.0)
    win_seconds = max(0.0, win_end - win_start)
    inputs: list[str] = []
    if window is not None:
        # -copyts はinputのtimestampを触らせないためのoptionなので、必ず入力より前に置く。
        # これが無いとffmpegは各入力のstart_timeを引いて0基準へ寄せてしまい、窓の内側で
        # ASS/giftのenable式が全て外れる。
        inputs += ["-copyts"]
        if seek_source:
            inputs += ["-ss", f"{win_start:.6f}", "-t", f"{win_seconds:.6f}"]
    inputs += ["-i", str(src)]
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
        layer_path, _layer_x, layer_y, _layer_stats = comment_layer
        layer_input = 1 + len(seen)  # source is [0], gift icons follow
        if layer_offset:
            inputs += ["-itsoffset", f"{layer_offset:.6f}"]
        inputs += ["-i", str(layer_path)]
    filter_complex = _build_filter_complex(overlays, icon_px, ass_name, layer_input, layer_y, scale_to, cfr_fps)
    # graphはfileで渡す。gift icon 100枚超・lane avatar付きのBattle録画では graph が数十KBに
    # なり、Windowsのcommand line上限(32767字)を実測27KBまで使い切って超える。-filter_complex
    # だと超えた時点でprocess生成そのものが失敗するので、常にscript渡しにして上限から外す。
    filter_path = out.with_name(out.stem + ".filter.txt")
    filter_path.write_text(filter_complex, encoding="utf-8")
    vmap = "[vout]"
    encoder = await video_encoder_name(codec)
    encoder_args = _encoder_args(encoder, _mapped_quality(encoder, quality))
    # 進捗を出すにはsource長(分母)が要る。取得できた時だけ-progressを有効化する。
    if window is not None:
        total_us = int(win_seconds * 1_000_000) if win_seconds > 0 else None
        base_us = int(win_start * 1_000_000)
        # 窓ありは音声を持たない(prepassの説明を参照)。尺の切り出しはinput側の-ss/-t
        # (seek_source)かpre-passが済ませているので、output側では切らない: -copyts下の
        # -tは出力timestampを基準に測るため、窓の開始offsetぶん早く打ち切ってしまう。
        audio_args = ["-an"]
    else:
        total_us = await _probe_duration_us(src) if on_progress else None
        base_us = 0
        # 正規化するときだけ音声を再encodeする。録画はVFRなのでfilterの前段に
        # aresample=async=1が要る(audio_norm側で必ず付けている)。出力rateはinput 0の
        # 実値へ戻す(loudnormは192kHzを出すため)。
        if audio_normalize:
            rate = await asyncio.to_thread(audio_norm.probe_sample_rate, src)
            audio_args = ["-map", "0:a?"] + audio_norm.encode_args(
                **audio_normalize, sample_rate=rate)
        else:
            audio_args = ["-map", "0:a?", "-c:a", "copy"]
    report = on_progress if (on_progress and total_us) else None
    proc = None
    try:
        cancel.check_cancelled()
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
            *inputs,
            "-filter_complex_script", str(filter_path),
            "-map", vmap,
            *audio_args,
            *encoder_args,
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            *(["-progress", "pipe:1", "-nostats"] if report else []),
            str(out),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE if report else asyncio.subprocess.DEVNULL,
            stderr=log_file,
            cwd=str(cwd),
        )
        cancel.register_process(proc)
        if report and proc.stdout is not None:
            await pump_ffmpeg_progress(proc.stdout, total_us, report, base_us)
        await proc.wait()
    finally:
        if proc is not None:
            cancel.forget_process(proc)
        log_file.close()
    if cancel.is_cancelled():
        out.unlink(missing_ok=True)
        log_path.unlink(missing_ok=True)
        filter_path.unlink(missing_ok=True)
        cancel.check_cancelled()
    if proc.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        tail = ""
        try:
            tail = log_path.read_text(
                encoding="utf-8", errors="replace")[-config.get_log_ffmpeg_stderr_chars():]
        except OSError:
            logger.warning(
                "burn-in ffmpeg log unreadable: %s", log_path, exc_info=True,
                extra={"event": "overlay.ffmpeg_log_unreadable", "ctx": {"path": str(log_path)}},
            )
        out.unlink(missing_ok=True)
        # 成果物は残らず、この呼び出しに自動回復経路も無いのでerror。ENOSPCはffmpegの
        # stderrにしか出ないため、空き容量を同じ行に併記して切り分け可能にする。
        logger.error(
            "burn-in ffmpeg failed for %s (rc=%s)", out.name, proc.returncode,
            extra={"event": "overlay.burn_in_failed",
                   "ctx": {"path": str(out.resolve()), "stem": src.stem,
                           "returncode": proc.returncode, "encoder": encoder,
                           "quality": quality, "codec": codec,
                           "overlays": len(overlays),
                           "comment_layer_used": comment_layer is not None,
                           "filter_chars": len(filter_complex),
                           "stderr_tail": tail, **_disk_ctx(out.parent)}},
        )
        raise RuntimeError(f"動画へのComment/Gift焼き込みに失敗しました（ffmpeg）。{tail}".strip())
    log_path.unlink(missing_ok=True)
    filter_path.unlink(missing_ok=True)


async def _run_audio_only(src: Path, out: Path, cwd: Path, audio_normalize: dict,
                          on_progress: Optional[ProgressCb] = None) -> None:
    """描く物が1つも無い録画へ音量正規化だけを掛ける。映像はstream copyなので再encodeは
    音声だけで、GPUも尺なりのencode時間も要らない。

    録画はHLS由来のVFRで、-c:v copy のまま音声filterを足すと同期が崩れる。前段の
    aresample=async=1 はaudio_norm.encode_args()が必ず付けているので、ここでは音声引数を
    組み替えないこと。"""
    log_path = out.with_name(out.stem + ".ffmpeg.log")
    log_file = open(log_path, "wb")
    total_us = await _probe_duration_us(src) if on_progress else None
    report = on_progress if (on_progress and total_us) else None
    rate = await asyncio.to_thread(audio_norm.probe_sample_rate, src)
    proc = None
    try:
        cancel.check_cancelled()
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
            "-i", str(src),
            "-map", "0:v:0", "-map", "0:a?",
            "-c:v", "copy",
            *audio_norm.encode_args(**audio_normalize, sample_rate=rate),
            "-movflags", "+faststart",
            *(["-progress", "pipe:1", "-nostats"] if report else []),
            str(out),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE if report else asyncio.subprocess.DEVNULL,
            stderr=log_file,
            cwd=str(cwd),
        )
        cancel.register_process(proc)
        if report and proc.stdout is not None:
            await pump_ffmpeg_progress(proc.stdout, total_us, report)
        await proc.wait()
    finally:
        if proc is not None:
            cancel.forget_process(proc)
        log_file.close()
    if cancel.is_cancelled():
        out.unlink(missing_ok=True)
        log_path.unlink(missing_ok=True)
        cancel.check_cancelled()
    if proc.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        tail = ""
        try:
            tail = log_path.read_text(
                encoding="utf-8", errors="replace")[-config.get_log_ffmpeg_stderr_chars():]
        except OSError:
            logger.warning(
                "audio-normalise ffmpeg log unreadable: %s", log_path, exc_info=True,
                extra={"event": "overlay.ffmpeg_log_unreadable", "ctx": {"path": str(log_path)}},
            )
        out.unlink(missing_ok=True)
        logger.error(
            "audio-normalise ffmpeg failed for %s (rc=%s)", out.name, proc.returncode,
            extra={"event": "overlay.audio_normalise_failed",
                   "ctx": {"path": str(out.resolve()), "stem": src.stem,
                           "returncode": proc.returncode,
                           "stderr_tail": tail,
                           **audio_norm.describe(audio_normalize),
                           **_disk_ctx(out.parent)}},
        )
        raise RuntimeError(f"音量正規化に失敗しました（ffmpeg）。{tail}".strip())
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


def _render_dimensions(src_w: int, src_h: int, min_height: int) -> tuple[int, int]:
    """Output (width, height) for the burn-in. A source shorter than ``min_height``
    is upscaled to it (aspect preserved) so burned text/emoji/avatars rasterise
    crisply instead of inheriting a low source resolution; taller sources are
    returned unchanged. Both dimensions are forced even (yuv420p requires it).

    ``min_height`` is the user's ``video_overlay_min_height`` and normally exceeds the
    720x1280 source, because the avatar disc — diameter 2 * line_h, which scales with
    the output height — is only 46px at 1280 and collapses into mush. The AI super-
    resolution pass (media/avatar_upscale.py) lifts the 72px avatar to 288-400px, so a
    taller canvas draws real detail rather than an interpolated enlargement. Measured
    on a 3h50m recording: 1280 -> 11.7min/1.24GB, 1920 -> ~12.6min/1.99GB, 2560 ->
    ~19.4min/2.75GB (NVENC; the comment layer is rasterised once per comment and
    scrolled, not redrawn per frame, so 4x the pixels costs well under 2x the time)."""
    if src_w <= 0 or src_h <= 0 or src_h >= min_height:
        return src_w, src_h
    out_h = min_height
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


async def _render_context(src: Path, cfg: dict, transcript: Optional[dict],
                          progress: Optional["JobProgress"] = None) -> dict:
    """Probe everything a render needs from the source: duration, the wall->media timing
    map inputs, geometry, CFR target, font metrics and the usable subtitle segments.

    The burn-in and the burn-in preview both go through here, unconditionally and with
    the same arguments, so the preview cannot end up on a different timeline from the
    output it is previewing. Nothing in here is allowed to branch on "this is a preview"
    — a preview that builds its own time map would be worse than no preview at all."""
    async def _step(frac: float, detail: str) -> None:
        if progress is not None:
            await progress.set("probe", frac, detail)

    await _step(0.05, "長さを取得中")
    dur_us = await _probe_duration_us(src)
    video_dur = dur_us / 1_000_000 if dur_us else None
    await _step(0.25, "時刻mapを読み込み中")
    anchors = _load_timing_anchors(src)
    media_pts = _load_media_pts(src)
    # media_pts(version-2 mapで2点以上)があればmapperはpts_gapsを参照しない。全packetの
    # pts_timeをdumpするprobeは長時間録画で数十万行になるため、必要な時だけ走らせる。
    if media_pts and len(media_pts) >= 2:
        pts_gaps = None
    else:
        # 全packet走査。長時間録画では数分かかるので、入る前に必ず知らせる。
        await _step(0.35, "PTSの欠落を走査中")
        pts_gaps = await _probe_pts_gaps(src)
    await _step(0.75, "解像度・フレームレートを取得中")
    src_w, src_h, fps = await _probe_dimensions(src)
    # Render (and burn) at the upscaled resolution when the source is low-res, so the
    # overlay text/emoji are crisp; scale_to tells ffmpeg to bring the source frame up
    # to the same canvas before compositing. None when no upscale is needed.
    width, height = _render_dimensions(src_w, src_h, int(cfg["video_overlay_min_height"]))
    await _step(0.9, "フォントを測定中")
    wide_em, narrow_em = await _font_metrics()
    return {
        "video_dur": video_dur,
        "anchors": anchors,
        "media_pts": media_pts,
        "pts_gaps": pts_gaps,
        "src_w": src_w,
        "src_h": src_h,
        "fps": fps,
        "width": width,
        "height": height,
        "scale_to": (width, height) if (width, height) != (src_w, src_h) else None,
        "icon_px": _icon_px(cfg, height),
        "avatar_dir": layout.avatar_pool_dir(),
        "wide_em": wide_em,
        "narrow_em": narrow_em,
        "quality": int(cfg.get("video_overlay_quality") or 21),
        "codec": codec_family(cfg.get("video_overlay_codec")),
        "subtitle_segments": (
            subtitles.usable_segments(transcript.get("segments"))
            if (cfg.get("video_overlay_subtitles") and transcript) else []
        ),
    }


async def ensure_overlay(
    src_path: str,
    started_at: float,
    ended_at: Optional[float],
    events: list,
    settings,
    battles: Optional[list] = None,
    on_progress: Optional[StageCb] = None,
    transcript: Optional[dict] = None,
) -> dict:
    """Burn comments/gifts/battle into the recording per settings and return
    ``{"a": Path, "b": Optional[Path]}``: ``a`` is the user-facing Mode A
    (consumer-arrival timing) output, and ``b`` is the Mode B (source-clock /
    create_time timing) comparison output, produced only when
    ``video_overlay_timing_compare`` is on and the recording has live create_time to
    anchor on, else ``None``. Built and cached on first use; raises RuntimeError on
    failure.

    描く物が1つも無い録画では、``a`` は音量正規化がOFFならsource pathそのもの、ONなら
    映像をstream copyしたまま音声だけを正規化した出力になる(userが求めた「履歴の出力にも
    音量正規化」は、描く物の有無に依らず掛かる必要がある)。

    ``transcript`` is this recording's stored transcript (storage.get_transcript). It is
    only read when ``video_overlay_subtitles`` is on, and the caller is responsible for
    refusing the job when the setting is on but no usable transcript exists — burning a
    recording without the subtitles that were asked for would be a silent downgrade.

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
    progress = JobProgress(on_progress)
    # 比較出力(Mode B)は同じ段階列をもう一度最初から流す。持ち分を先に切っておかないと
    # %が 0→99→0→99 と往復する。実際にBを作るかはA終了後にしか決まらないが、作らなかった
    # 場合は前進方向へ飛ぶだけなので、可能性がある時点で2分割しておく方が安全である。
    b_possible = (bool(settings.get("video_overlay_timing_compare"))
                  and len(_live_create_samples(events)) >= SOURCE_MIN_ANCHOR_SAMPLES)
    progress.span(0, 2 if b_possible else 1)
    ctx = await _render_context(src, cfg, transcript, progress)
    await progress.done("probe")
    video_dur = ctx["video_dur"]
    anchors, media_pts, pts_gaps = ctx["anchors"], ctx["media_pts"], ctx["pts_gaps"]
    src_w, src_h, fps = ctx["src_w"], ctx["src_h"], ctx["fps"]
    # 焼き込みはrecorderとは別時刻・別操作で走るので、焼き込みのlogだけを見る調査者に
    # 前提条件が見えている必要がある。特にtiming mapはrecorderがCFR転落時にunlinkする
    # ため、「無い」ことと「その理由の時刻」が開始行に残っていないと辿れない。
    logger.info(
        "overlay job started for %s (events=%d window=%s..%s duration=%ss %dx%d @%.3ffps)",
        src.name, len(events), started_at, ended_at, video_dur, src_w, src_h, fps,
        extra={"event": "overlay.job_started",
               "ctx": {"path": str(src.resolve()), "stem": src.stem,
                       "events_total": len(events),
                       "window_started_at": started_at, "window_ended_at": ended_at,
                       "video_duration_seconds": video_dur,
                       "src_width": src_w, "src_height": src_h, "src_fps": fps,
                       "anchors": len(anchors) if anchors else 0,
                       "media_pts": len(media_pts) if media_pts else 0,
                       "pts_gaps": len(pts_gaps) if pts_gaps else 0,
                       **_timing_map_ctx(src), **_disk_ctx(src)}},
    )
    width, height, scale_to = ctx["width"], ctx["height"], ctx["scale_to"]
    icon_px = ctx["icon_px"]
    # TikTok recordings are stream-copied HLS and thus variable-frame-rate. ffmpeg's
    # overlay filter cannot keep the constant-rate comment layer time-locked to a VFR
    # base — comments end up many seconds behind the footage — so the base is normalised
    # to CFR. This is folded into the burn-in filter graph (see _build_filter_complex)
    # rather than run as a separate full re-encode pass, so the video body is encoded
    # once instead of twice. cfr_fps is None for an already-CFR source (no resample).
    # Cap the CFR target: the nominal rate is HLS padding (see CFR_FPS_CAP), so a
    # 50/60fps VFR source normalises to 30 — halving the frames every downstream pass
    # touches — while a source already at or below the cap keeps its own rate.
    cfr_fps = min(fps, CFR_FPS_CAP) if await _probe_is_vfr(src, fps) else None
    if cfr_fps is None:
        # 既にCFRならbase pre-passは走らない。重みに残すと全体%がその分だけ頭打ちになる。
        progress.disable("base")
    if cfr_fps is not None:
        logger.info("overlay: normalising VFR source (nominal %.3ffps) to CFR %.3ffps for %s",
                    fps, cfr_fps, src.name,
                    extra={"event": "overlay.cfr_normalisation_planned",
                           "ctx": {"stem": src.stem, "src_fps": fps, "fps": cfr_fps}})
    avatar_dir = ctx["avatar_dir"]
    wide_em, narrow_em = ctx["wide_em"], ctx["narrow_em"]
    quality, codec = ctx["quality"], ctx["codec"]
    subtitle_segments = ctx["subtitle_segments"]

    # 「A側が何も描かなかった」ことをMode Bの起動判定へ渡す。素通しでも音量正規化だけを
    # 掛けた出力を返すため、A の戻り値がsrcかどうかでは区別できない。
    a_drew_nothing = False

    # assets段階は3つのresolver(絵文字→ギフトicon→配信者icon)を順に通る。段階内の
    # 達成率が巻き戻らないよう、resolverごとに持ち分を割り当てる。
    _ASSET_SPANS = {"絵文字": (0.0, 1 / 3), "ギフトアイコン": (1 / 3, 2 / 3),
                    "配信者アイコン": (2 / 3, 1.0)}

    async def _asset_step(label: str, index: int, total: int) -> None:
        lo, hi = _ASSET_SPANS[label]
        inner = (index / total) if total else 1.0
        await progress.set("assets", lo + (hi - lo) * inner, f"{label} {index:,}/{total:,}")

    async def _render_variant_locked(time_source, out, ass_path, meta_path, signature, debug_path=None):
        nonlocal a_drew_nothing
        render_started = time.monotonic()
        if out.is_file() and meta_path.is_file():
            cached_audio_only = _read_meta(meta_path, signature)
            if cached_audio_only is not None:
                if cached_audio_only and time_source == "arrival":
                    a_drew_nothing = True
                return out
        debug_sink = [] if debug_path is not None else None
        await progress.set("plan", 0.1, f"{len(events):,}件のeventを配置中")
        ass_text, overlays, stats, comment_plan = _build_ass(
            events, started_at, ended_at, video_dur, width, height, cfg, anchors, avatar_dir,
            wide_em, narrow_em, pts_gaps, battles, time_source=time_source, debug_sink=debug_sink,
            media_pts=media_pts, subtitle_segments=subtitle_segments,
        )
        await progress.done(
            "plan",
            f"コメント{stats['comments']:,} ギフト{stats['gifts']:,} 字幕{stats['subtitles']:,}",
        )
        if stats.get("source_unavailable"):
            # Mode B could not be anchored (no live create_time); leave no B output.
            out.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            return None
        if (stats["comments"] == 0 and stats["gifts"] == 0 and stats["score"] == 0
                and stats["subtitles"] == 0):
            # 「eventが無かった」と「原点破綻で全eventが動画長の外へ落ちた」は、この行だけ
            # 見ると区別がつかない。drop内訳とoffsetの範囲を必ず併記し、drop率が高い場合は
            # 正常なtrimではなく欠陥として扱う。
            placement = _placement_ctx(stats)
            broken = stats["dropped_ratio"] >= config.get_log_overlay_drop_warn_ratio()
            normalize = audio_norm.targets_from_cfg(cfg) if time_source == "arrival" else None
            logger.log(
                logging.WARNING if broken else logging.INFO,
                "overlay[%s]: nothing to draw for %s; %s "
                "(events=%d placed=%d dropped_before=%d dropped_after=%d offsets=%s..%s of %ss)",
                time_source, src.name,
                "normalising audio only" if normalize else "serving source",
                stats["events_total"], stats["placed"],
                stats["dropped_before_start"], stats["dropped_after_end"],
                stats["offset_min"], stats["offset_max"], stats["video_duration_seconds"],
                extra={"event": "overlay.nothing_to_draw",
                       "ctx": {"stem": src.stem, **placement,
                               **audio_norm.describe(normalize)}},
            )
            if time_source == "arrival":
                a_drew_nothing = True
            if normalize is None:
                out.unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
                return src if time_source == "arrival" else None
            # 描く物は無いが音量正規化は要求されている。映像はstream copyのままで音声だけを
            # 再encodeし、履歴の出力にも正規化が掛かった状態で残す。
            # 描く物が無い経路: 残るのは音声の再encodeだけなので、層生成の段階を重みから
            # 外して、この1本で100%へ届くようにする。
            progress.disable("assets", "layer", "layer_encode", "base")
            await _run_audio_only(src, out, sidecar_dir(src), normalize,
                                  progress.cb("encode", video_dur))
            meta_path.write_text(f"{signature}\n{AUDIO_ONLY_MARK}", encoding="utf-8")
            logger.info(
                "overlay[%s]: audio-only normalise done for %s (%d bytes)",
                time_source, out.name, out.stat().st_size,
                extra={"event": "overlay.audio_normalised",
                       "ctx": {"path": str(out.resolve()), "stem": src.stem,
                               "duration_ms": int((time.monotonic() - render_started) * 1000),
                               "size_bytes": out.stat().st_size,
                               **audio_norm.describe(normalize)}},
            )
            return out

        # comment layer(数GB)とCFR base(数十GB)は、合成まで到達しなかった経路でも必ず
        # 消す。pre-passのre-raiseやcancelはlayer renderの後・_run_ffmpegの前で抜けるため、
        # _run_ffmpegのfinallyに置いたままでは回収する所有者が誰も居なくなる。
        comment_layer_path: Optional[Path] = None
        prepass_file: Optional[Path] = None
        try:
            comment_layer = None
            comment_fallback = False
            comment_layer_path = sidecar_dir(src) / (out.stem + COMMENT_LAYER_SUFFIX)
            # ``render_src``/``main_cfr``/``main_scale`` are what the burn-in graph sees.
            # They stay as the source unless a CFR base pre-pass runs, which swaps in the
            # normalised base and drops the in-graph resample.
            render_src, main_cfr, main_scale = src, cfr_fps, scale_to
            if comment_plan is None:
                # commentが1件も無い(ギフトだけ等)。層は作られず、CFR正規化も本graphに
                # 畳まれてbase pre-passは走らない。3段階まとめて重みから外す。
                progress.disable("layer", "layer_encode", "base")
            if comment_plan is not None:
                # Download the custom-emote images and attach them to the shaper before the
                # layer render draws them inline (cached by emote_id under the recording's
                # sidecar dir, reused across comments and re-outputs).
                await _resolve_emotes(comment_plan["shaper"],
                                      layout.emote_pool_dir(),
                                      _asset_step)
                layer_fps = min(fps, comment_layer_fps_cap())
                # Run the CFR base pre-pass (GPU) concurrently with the comment-layer
                # render (CPU/qtrle): they are independent (both only read the source) and
                # bound different hardware, so overlapping them roughly halves the pre-burn
                # "preparing" wait. Started optimistically since the layer almost always
                # renders; if it ends up unavailable the base is discarded below and the
                # in-graph CFR path is used for the ASS fallback instead.
                prepass_task = None
                if cfr_fps is not None:
                    prepass_file = sidecar_dir(src) / (out.stem + CFR_BASE_SUFFIX)
                    # baseは**元の解像度のまま**作る。この pre-pass が担うのはCFR化だけで、
                    # 拡大は本passのgraphでやれば足りる(framesyncが噛むのはfpsだけ)。以前は
                    # ここで min_height(既定2560)へ引き伸ばしてから中間fileに焼いていたため、
                    # 捨てる中間物にNVENCの時間と容量を最終尺ぶん払っていた。実測(31分の
                    # 512x1024): 178秒/2844MB -> 33秒/666MB。
                    prepass_task = asyncio.create_task(
                        _prepass_cfr(src, prepass_file, None, cfr_fps, sidecar_dir(src),
                                     on_progress=progress.cb("base", video_dur)))
                # The comment layer streams every frame through a long-lived pipe to a
                # qtrle encoder; under load that pipe can break transiently and yield
                # None. Retry once before giving up, since a mono fallback must never be
                # cached as the final result (see the meta write below).
                layer_progress = progress.thread_cb_multi(asyncio.get_running_loop())
                for attempt in range(1, 3):
                    comment_layer = await _render_comment_layer(
                        comment_plan["placements"], comment_plan["avatar_files"], comment_plan["metrics"],
                        comment_plan["comment_fs"], comment_plan["shaper"],
                        width, height, layer_fps, comment_layer_path,
                        comment_plan.get("avatar_upscale", False),
                        progress=layer_progress,
                    )
                    if comment_layer is not None:
                        await progress.done("layer_encode")
                        break
                    logger.warning(
                        "comment layer render produced nothing for %s (attempt %d/2)", src.name, attempt,
                        extra={"event": "overlay.comment_layer_retried",
                               "ctx": {"stem": src.stem, "attempt": attempt,
                                       "time_source": time_source, "fps": layer_fps}},
                    )
                if prepass_task is not None:
                    try:
                        await prepass_task
                        # pumpは99%上限(100はjob完了専用)なので、そのままではこの段階が
                        # 永久に「進行中」で残り、重みぶんの%も届かない。完了を明示する。
                        await progress.done("base")
                    except Exception:
                        # The base pre-pass failed. If the layer rendered, it cannot be
                        # composited on a VFR base without drift, so re-raise (fatal); if
                        # the layer also failed the base is not needed anyway.
                        prepass_file.unlink(missing_ok=True)
                        prepass_file = None
                        progress.disable("base")
                        if comment_layer is not None:
                            raise
                if comment_layer is not None and prepass_file is not None:
                    # Composite onto the real CFR base; the main graph no longer resamples
                    # the frame rate. 拡大(scale_to)は本graphに残す — baseは元解像度で作って
                    # あり、overlay/ASSは出力canvasの座標で組まれているため、合成の前に
                    # 引き伸ばす必要がある。
                    render_src, main_cfr, main_scale = prepass_file, None, scale_to
                if comment_layer is not None:
                    # layerがbaseより短ければ、合成後にcommentが途中で無警告に消える
                    # (eof_action=passの設計上、ffmpegは何も言わない)。合成前に測る。
                    layer_stats = comment_layer[3]
                    _log_duration_check(
                        "overlay.comment_layer_checked",
                        "comment layer duration check: layer=%ss base=%ss (delta=%ss)",
                        fps=layer_fps,
                        layer_seconds=await _duration_seconds(comment_layer[0]),
                        base_seconds=await _duration_seconds(render_src),
                        src_seconds=video_dur,
                        compare=("layer", "base"),
                        n_frames=layer_stats["n_frames"],
                        ctx={"path": str(comment_layer[0].resolve()), "stem": src.stem,
                             "time_source": time_source,
                             "frames_written": layer_stats["frames_written"],
                             "size_bytes": layer_stats["size_bytes"],
                             "base_is_prepass": prepass_file is not None},
                    )
                elif prepass_file is not None:
                    # Layer unavailable → base unused; drop it and let the ASS path
                    # normalise CFR in-graph via cfr_fps.
                    prepass_file.unlink(missing_ok=True)
                    prepass_file = None
                    progress.disable("base")
                if comment_layer is None:
                    # The colour-emoji layer could not be produced; rebuild the ASS with
                    # the monochrome comment feed so comments still show. This output is
                    # degraded (colour emoji were requested but failed to render), so it is
                    # NOT cached as complete — the next output retries the colour layer.
                    comment_fallback = True
                    # 層は結局作られていない。重みに残すと、その分だけ%が届かなくなる。
                    progress.disable("layer", "layer_encode")
                    # 転落先のASS feedはカラー絵文字も実写アイコンも描けないため、成果物の品質は
                    # 確定的に劣化する(自動回復ではない)。転落した事実と理由を必ずerrorで残す。
                    # TODO: 規約上のfallback禁止に該当する。廃止は別taskで判断する。
                    logger.warning(
                        "comment layer unavailable for %s after retry; falling back to monochrome ASS comments",
                        src.name,
                        extra={"event": "overlay.comment_layer_fallback_used",
                               "ctx": {"stem": src.stem, "time_source": time_source,
                                       "reason": "comment layer render returned nothing twice",
                                       "degraded": "no colour emoji, no real avatars",
                                       "fps": layer_fps,
                                       **_disk_ctx(sidecar_dir(src))}},
                    )
                    ass_text, overlays, stats, _ = _build_ass(
                        events, started_at, ended_at, video_dur, width, height, cfg, anchors, avatar_dir,
                        wide_em, narrow_em, pts_gaps, battles, use_comment_layer=False, time_source=time_source,
                        media_pts=media_pts, subtitle_segments=subtitle_segments,
                    )

            icon_cache = layout.gift_icon_pool_dir()
            gift_specs = [o for o in overlays if o.get("kind") != "avatar"]
            avatar_specs = [o for o in overlays if o.get("kind") == "avatar"]
            renderable = await _resolve_icons(gift_specs, icon_cache, _asset_step)
            renderable += await _resolve_score_avatars(avatar_specs, avatar_dir, icon_cache,
                                                       _asset_step)
            await progress.done("assets", f"アイコン{len(renderable):,}件")
            ass_path.write_text(ass_text, encoding="utf-8")
            await _run_ffmpeg(render_src, renderable, icon_px, ass_path.name, out, sidecar_dir(src), quality,
                              codec=codec, comment_layer=comment_layer,
                              on_progress=progress.cb("encode", video_dur),
                              scale_to=main_scale, cfr_fps=main_cfr,
                              audio_normalize=audio_norm.targets_from_cfg(cfg))
            await progress.done("encode")
        finally:
            ass_path.unlink(missing_ok=True)
            if comment_layer_path is not None:
                comment_layer_path.unlink(missing_ok=True)
            if prepass_file is not None:
                prepass_file.unlink(missing_ok=True)
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
        placement = _placement_ctx(stats)
        drop_ratio = stats["dropped_ratio"]
        broken = drop_ratio >= config.get_log_overlay_drop_warn_ratio()
        logger.log(
            logging.WARNING if broken else logging.INFO,
            "overlay rendered[%s]: %s (comments=%d gifts=%d score=%d icons=%d dropped_icons=%d "
            "avatars=%d placed=%d/%d dropped_before=%d dropped_after=%d)",
            time_source, out.name, stats["comments"], stats["gifts"], stats["score"], len(renderable),
            stats["dropped_icons"], stats["avatars"], stats["placed"], stats["events_total"],
            stats["dropped_before_start"], stats["dropped_after_end"],
            extra={"event": "overlay.rendered",
                   "ctx": {"stem": out.stem,
                           "comments": stats["comments"], "gifts": stats["gifts"],
                           "score": stats["score"], "bonus": stats["bonus"],
                           "subtitles": stats["subtitles"],
                           "subtitle_diag": stats["subtitle_diag"],
                           "icons": len(renderable), "dropped_icons": stats["dropped_icons"],
                           "avatars": stats["avatars"],
                           "comment_layer_used": comment_layer is not None,
                           "comment_fallback": comment_fallback,
                           "duration_ms": int((time.monotonic() - render_started) * 1000),
                           "size_bytes": out.stat().st_size if out.is_file() else None,
                           **placement}},
        )
        return out

    async def _render_variant(time_source, out, ass_path, meta_path, signature, debug_path=None):
        """Render one variant while holding a process-wide GPU slot. The cache hit is
        answered before queueing: a re-output that is already up to date must not wait
        behind another recording's encode just to return the file it already has."""
        nonlocal a_drew_nothing
        if out.is_file() and meta_path.is_file():
            cached_audio_only = _read_meta(meta_path, signature)
            if cached_audio_only is not None:
                if cached_audio_only and time_source == "arrival":
                    a_drew_nothing = True
                return out
        async with gpu_slot_async(f"overlay:{out.stem}"):
            return await _render_variant_locked(
                time_source, out, ass_path, meta_path, signature, debug_path
            )

    events_sig = _events_fingerprint(events)
    subtitles_sig = subtitles.fingerprint(transcript) if cfg.get("video_overlay_subtitles") else ""
    out_a, ass_a, meta_a = overlay_paths(src)
    sig_a = _signature(src, cfg, timing_path(src), variant="a", events_sig=events_sig,
                       subtitles_sig=subtitles_sig)
    lock = await _get_lock(str(out_a))
    async with lock:
        result_a = await _render_variant("arrival", out_a, ass_a, meta_a, sig_a)
        result_b = None
        # Mode B comparison output: opt-in and only when the recording carries live
        # create_time to anchor on. Skipped entirely when A drew nothing (same events
        # => B would draw nothing too).
        b_enabled = (
            not a_drew_nothing
            and bool(settings.get("video_overlay_timing_compare"))
            and len(_live_create_samples(events)) >= SOURCE_MIN_ANCHOR_SAMPLES
        )
        if b_enabled:
            progress.span(1, 2)
            out_b, ass_b, meta_b = overlay_paths_b(src)
            sig_b = _signature(src, cfg, timing_path(src), variant="b", events_sig=events_sig,
                               subtitles_sig=subtitles_sig)
            result_b = await _render_variant(
                "server", out_b, ass_b, meta_b, sig_b, sidecar_path(src, TIMING_DEBUG_SUFFIX)
            )
        if result_b is None:
            # Compare off / not anchorable / B drew nothing: drop any stale B output.
            for p in overlay_paths_b(src):
                p.unlink(missing_ok=True)
    await progress.finish("出力を確認中")
    return {"a": result_a, "b": result_b}


# ===== 焼き込み設定のプレビュー =====
# 13項目ある焼き込み設定の効き目を、1配信ぶんの本出力(数十分〜数時間)を待たずに確かめる
# ための経路。静止画は1 frameだけをPIL層と合成して秒で返し、動画は実解像度・実codecのまま
# 尺だけをmedia PTS窓で切る。
#
# 守るべき不変条件が1つある: **時刻mapを分岐させないこと**。プレビューは全尺のまま組んだ
# 描画plan(_render_context / _build_ass)をそのまま使い、窓はffmpegのseekと-copytsでしか
# 効かせない。プレビュー専用にoffsetを組み直すと「プレビューでは合っているのに本出力は
# ズレる」という、無いより有害な確認手段になる。成果物(png/mp4/meta/中間物)はsidecar dirへ
# 隔離し、本出力のcache判定とは無関係にしてある。

PREVIEW_ASS_SUFFIX = ".preview.ass"
PREVIEW_RAW_SUFFIX = ".preview.raw.png"
# 窓の自動選定で使う重み。giftとBattleはcommentより低頻度なので、同じ件数ならそれらを
# 含む窓を優先する(gift秒数・min diamonds・score bar holdが空振りする窓を選ばないため)。
# 選定にしか効かず、描画結果には一切影響しない。
PREVIEW_GIFT_WEIGHT = 6.0
PREVIEW_BATTLE_WEIGHT = 2.0
# Battle区間へ置く評価点の間隔(秒)。Battleは数分続くので、開始点だけに重みを置くと窓が
# 常にBattle冒頭へ吸い寄せられる。
PREVIEW_BATTLE_SAMPLE_SECONDS = 15.0


def preview_seconds(settings) -> float:
    """動画プレビューの尺(秒)。costは解像度ではなく尺で決まるので、ここが唯一の削減軸。"""
    return float(settings.get("video_overlay_preview_seconds"))


def _battle_media_windows(battles, to_media, video_duration) -> list:
    """Battleが映像上のどの区間かを (start, end) で返す。窓の自動選定にしか使わない
    (描画は_build_score_bar_dialoguesが自前で解決する)ので、ここでの誤差はプレビュー窓の
    選び方が少し悪くなるだけで、描かれる内容は動かない。"""
    upper = video_duration if video_duration is not None else float("inf")
    wins: list = []
    for battle in battles or []:
        if battle.get("aborted"):
            continue
        series = battle.get("score_series") or []
        if not series:
            continue
        end_wall = battle.get("end_time") or series[-1].get("t")
        start = max(0.0, to_media(series[0].get("t") or 0))
        end = to_media(end_wall) if end_wall else start
        if end <= start or start >= upper:
            continue
        wins.append((start, min(end, upper)))
    return wins


def _preview_points(debug_rows: list, cfg: dict, battle_windows: list,
                    video_duration) -> list:
    """窓の評価に使う (映像time, 重み) の列。commentとgiftの位置は本番の描画planが出した
    offsetそのもの(_build_assのdebug_sink)なので、選定と描画で時刻がズレようがない。"""
    upper = video_duration if video_duration is not None else float("inf")
    min_diamonds = cfg.get("video_overlay_gift_min_diamonds") or 0
    points: list = []
    for row in debug_rows:
        offset = row.get("offset")
        if offset is None or offset < 0 or offset > upper:
            continue
        if row.get("kind") == "comment":
            if cfg.get("video_overlay_comments"):
                points.append((offset, 1.0))
        elif row.get("kind") == "gift":
            if cfg.get("video_overlay_gifts") and (row.get("diamonds") or 0) >= min_diamonds:
                points.append((offset, PREVIEW_GIFT_WEIGHT))
    if cfg.get("video_overlay_score_bar"):
        for start, end in battle_windows:
            t = start
            while t < end:
                points.append((t, PREVIEW_BATTLE_WEIGHT))
                t += PREVIEW_BATTLE_SAMPLE_SECONDS
    points.sort(key=lambda p: p[0])
    return points


def _pick_preview_window(points: list, video_duration, seconds: float) -> tuple:
    """描くものが最も濃い ``seconds`` 秒の窓を返す。userに開始時刻を入れさせると、大半の
    録画では何も起きていない区間を引いてしまい、gift秒数もmin diamondsもscore barも
    確認できない空振りのプレビューになる。"""
    total = video_duration if video_duration is not None else 0.0
    if total and total <= seconds:
        return 0.0, total
    max_start = max(0.0, total - seconds) if total else 0.0
    if not points:
        return 0.0, (min(seconds, total) if total else seconds)
    times = [p[0] for p in points]
    cumulative = [0.0]
    for _t, weight in points:
        cumulative.append(cumulative[-1] + weight)

    def score(start: float) -> float:
        lo = bisect.bisect_left(times, start)
        hi = bisect.bisect_right(times, start + seconds)
        return cumulative[hi] - cumulative[lo]

    # 候補は「ある点で窓が始まる」「ある点が窓の中央に来る」の2種類で足りる。窓の重みは
    # 開始位置に対して区分定数なので、最大値は必ずいずれかの点の近傍で取れる。
    candidates = {0.0, max_start}
    for t in times:
        candidates.add(min(max(0.0, t), max_start))
        candidates.add(min(max(0.0, t - seconds / 2.0), max_start))
    ordered = sorted(candidates)
    best = ordered[0]
    best_score = score(best)
    for start in ordered:
        value = score(start)
        if value > best_score:
            best, best_score = start, value
    end = best + seconds
    if total:
        end = min(end, total)
    return best, end


async def _preview_plan(src: Path, settings, started_at: float, ended_at,
                        events: list, battles, transcript,
                        seconds: float, at_seconds) -> dict:
    """プレビュー1回ぶんの描画plan。本出力と同じ_render_context・同じ_build_assを、同じ
    引数で通す(ここが分岐したらプレビューは嘘になる)。窓だけをこの後で決める。"""
    if not ffmpeg_available():
        raise RuntimeError("ffmpegが見つかりません。プレビューにはffmpegのinstallが必要です。")
    if not src.is_file():
        raise RuntimeError("録画fileが存在しません。")
    sidecar_dir(src).mkdir(parents=True, exist_ok=True)
    cfg = overlay_settings(settings)
    ctx = await _render_context(src, cfg, transcript)
    debug_sink: list = []
    ass_text, overlays, stats, comment_plan = _build_ass(
        events, started_at, ended_at, ctx["video_dur"], ctx["width"], ctx["height"], cfg,
        ctx["anchors"], ctx["avatar_dir"], ctx["wide_em"], ctx["narrow_em"], ctx["pts_gaps"],
        battles, time_source="arrival", debug_sink=debug_sink,
        media_pts=ctx["media_pts"], subtitle_segments=ctx["subtitle_segments"],
    )
    if (stats["comments"] == 0 and stats["gifts"] == 0 and stats["score"] == 0
            and stats["subtitles"] == 0):
        raise NothingToDrawError(
            "この録画には焼き込むComment/Gift/Battle/字幕がありません。"
            "設定を変えるか、別の録画でプレビューしてください。"
        )
    to_media = _make_time_mapper(ctx["anchors"], started_at, ended_at, ctx["video_dur"],
                                ctx["pts_gaps"], ctx["media_pts"])
    battle_windows = _battle_media_windows(battles, to_media, ctx["video_dur"])
    points = _preview_points(debug_sink, cfg, battle_windows, ctx["video_dur"])
    if at_seconds is None:
        win_start, win_end = _pick_preview_window(points, ctx["video_dur"], seconds)
        auto = True
    else:
        total = ctx["video_dur"] or (at_seconds + seconds)
        win_start = min(max(0.0, at_seconds), max(0.0, total - seconds))
        win_end = min(win_start + seconds, total)
        auto = False
    return {"cfg": cfg, "ctx": ctx, "ass_text": ass_text, "overlays": overlays,
            "stats": stats, "comment_plan": comment_plan, "points": points,
            "window": (win_start, win_end), "window_auto": auto,
            "battle_windows": battle_windows}


def _comments_in_window(comment_plan, window: tuple) -> bool:
    """窓の中でcommentが1件でも画面に出るか。出ないなら層を描かない。本出力の「層を作れ
    なかったのでASSの白黒feedへ転落」とは別事象で、混同するとプレビューだけ見た目が
    変わってしまう。"""
    if comment_plan is None:
        return False
    win_start, win_end = window
    for p in comment_plan["placements"]:
        if p["empty"] or not p.get("segments"):
            continue
        for seg in p["segments"]:
            if seg["start"] <= win_end and seg["end"] > win_start:
                return True
    return False


async def _preview_render_inputs(src: Path, plan: dict) -> list:
    """gift icon / score barのavatarを解決して、overlay filterへ渡せるspecにする。"""
    icon_cache = layout.gift_icon_pool_dir()
    overlays = plan["overlays"]
    gift_specs = [o for o in overlays if o.get("kind") != "avatar"]
    avatar_specs = [o for o in overlays if o.get("kind") == "avatar"]
    renderable = await _resolve_icons(gift_specs, icon_cache)
    renderable += await _resolve_score_avatars(avatar_specs, plan["ctx"]["avatar_dir"], icon_cache)
    return renderable


async def _run_preview_frame(src: Path, overlays: list, ctx: dict, ass_path: Path,
                             out_png: Path, at: float) -> None:
    """``at`` の1 frameを、本出力と同一のfilter graphを通してpngへ書く。``-copyts``で
    sourceのtimestampを保つので、ASSのDialogueもgiftの``enable=between(t,...)``も全尺の
    ままの時刻で正しく効く(時刻を組み直さないための要)。"""
    cwd = sidecar_dir(src)
    filter_complex = _build_filter_complex(
        overlays, ctx["icon_px"], ass_path.name, None, 0, ctx["scale_to"], None)
    # graphは常にscript渡し(command line長の上限に触れないため。_run_ffmpegと同じ理由)。
    filter_path = out_png.with_name(out_png.stem + ".filter.txt")
    filter_path.write_text(filter_complex, encoding="utf-8")
    log_path = out_png.with_name(out_png.stem + ".ffmpeg.log")
    log_file = open(log_path, "wb")
    inputs: list = ["-copyts", "-ss", f"{at:.6f}", "-i", str(src)]
    seen: list = []
    for spec in overlays:
        f = str(spec["file"])
        if f not in seen:
            seen.append(f)
    for f in seen:
        inputs += ["-i", f]
    proc = None
    try:
        cancel.check_cancelled()
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
            *inputs,
            "-filter_complex_script", str(filter_path),
            "-map", "[vout]", "-an", "-frames:v", "1", "-update", "1",
            str(out_png),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL, stderr=log_file, cwd=str(cwd),
        )
        cancel.register_process(proc)
        await proc.wait()
    finally:
        if proc is not None:
            cancel.forget_process(proc)
        log_file.close()
    if cancel.is_cancelled():
        out_png.unlink(missing_ok=True)
        log_path.unlink(missing_ok=True)
        filter_path.unlink(missing_ok=True)
        cancel.check_cancelled()
    if proc.returncode != 0 or not out_png.exists() or out_png.stat().st_size == 0:
        tail = ""
        try:
            tail = log_path.read_text(
                encoding="utf-8", errors="replace")[-config.get_log_ffmpeg_stderr_chars():]
        except OSError:
            logger.warning(
                "preview ffmpeg log unreadable: %s", log_path, exc_info=True,
                extra={"event": "overlay.ffmpeg_log_unreadable", "ctx": {"path": str(log_path)}},
            )
        out_png.unlink(missing_ok=True)
        filter_path.unlink(missing_ok=True)
        logger.error(
            "preview frame extraction failed for %s at %.3fs (rc=%s)", src.name, at,
            proc.returncode,
            extra={"event": "overlay.preview_frame_failed",
                   "ctx": {"path": str(out_png.resolve()), "stem": src.stem,
                           "at_seconds": round(at, 3), "returncode": proc.returncode,
                           "overlays": len(overlays), "filter_chars": len(filter_complex),
                           "stderr_tail": tail, **_disk_ctx(out_png.parent)}},
        )
        raise RuntimeError(f"プレビュー用frameの抽出に失敗しました（ffmpeg）。{tail}".strip())
    log_path.unlink(missing_ok=True)
    filter_path.unlink(missing_ok=True)


def _preview_still_sync(comment_plan: dict, ctx: dict, raw_png: Path, out_png: Path,
                        at: float) -> bool:
    """抜いた1 frameへcomment層を重ねてpngにする。tile化も配置式も本出力と同じ関数を通す。"""
    from PIL import Image

    tiles = _comment_layer_tiles(
        comment_plan["placements"], comment_plan["avatar_files"], comment_plan["metrics"],
        comment_plan["comment_fs"], comment_plan["shaper"], ctx["width"], ctx["height"],
        comment_plan.get("avatar_upscale", False), time_window=(at, at),
    )
    if tiles is None:
        return False
    band = _comment_still_frame(tiles, at)
    if band is None:
        return False
    with Image.open(raw_png) as frame:
        base = frame.convert("RGBA")
    base.alpha_composite(band, (tiles["region_x"], tiles["region_y0"]))
    base.convert("RGB").save(out_png)
    return True


async def _preview_still_compose(comment_plan: dict, ctx: dict, raw_png: Path,
                                 out_png: Path, at: float) -> bool:
    """comment層の合成。avatarのAI超解像を伴うときだけGPU slotを取る(取らない場合は本出力の
    encode中でも待たずに返せる。設定確認を待たせないことが静止画プレビューの存在理由)。"""
    if comment_plan.get("avatar_upscale"):
        async with gpu_slot_async(f"overlay-preview:{out_png.stem}"):
            return await asyncio.to_thread(_preview_still_sync, comment_plan, ctx,
                                           raw_png, out_png, at)
    return await asyncio.to_thread(_preview_still_sync, comment_plan, ctx,
                                   raw_png, out_png, at)


async def preview_still(src_path: str, started_at: float, ended_at,
                        events: list, settings, battles=None, transcript=None,
                        at_seconds=None) -> dict:
    """焼き込み設定の静止画プレビュー。指定(既定はevent密度で自動選定した)media PTSの
    1 frameだけを抜き、本出力と同じASS・同じgift overlay・同じPIL comment層を重ねてpngへ
    書く。動画encodeもcomment layerのpipeもCFR pre-passも通らないので秒で返る。"""
    src = Path(src_path)
    # 窓の長さはGift演出の表示秒数に合わせる。giftは自分のoffsetから表示秒数のあいだ画面に
    # 残るので、その幅で最も濃い窓の「終わり」が、Gift/Commentが最も多く同時に出ている瞬間
    # になる。
    span = float(settings.get("video_overlay_gift_seconds") or 0) or SLIDE_SECONDS
    plan = await _preview_plan(src, settings, started_at, ended_at, events, battles,
                               transcript, span, at_seconds)
    ctx = plan["ctx"]
    at = plan["window"][1] if at_seconds is None else plan["window"][0]
    if ctx["video_dur"]:
        at = min(at, max(0.0, ctx["video_dur"] - 1.0 / max(ctx["fps"], 1.0)))
    still_path, _clip_path, _meta_path = preview_paths(src)
    ass_path = sidecar_path(src, PREVIEW_ASS_SUFFIX)
    raw_path = sidecar_path(src, PREVIEW_RAW_SUFFIX)
    comment_plan = plan["comment_plan"]
    draw_comments = _comments_in_window(comment_plan, (at, at))
    started = time.monotonic()
    lock = await _get_lock(f"preview-still:{still_path}")
    async with lock:
        if draw_comments:
            await _resolve_emotes(comment_plan["shaper"],
                                  layout.emote_pool_dir())
        renderable = await _preview_render_inputs(src, plan)
        ass_path.write_text(plan["ass_text"], encoding="utf-8")
        try:
            await _run_preview_frame(src, renderable, ctx, ass_path, raw_path, at)
            if draw_comments:
                drawn = await _preview_still_compose(comment_plan, ctx, raw_path,
                                                     still_path, at)
            else:
                drawn = False
                shutil.copyfile(raw_path, still_path)
        finally:
            ass_path.unlink(missing_ok=True)
            raw_path.unlink(missing_ok=True)
    logger.info(
        "overlay preview still rendered at %.3fs for %s (comments=%s icons=%d)",
        at, src.name, drawn, len(renderable),
        extra={"event": "overlay.preview_still_rendered",
               "ctx": {"path": str(still_path.resolve()), "stem": src.stem,
                       "at_seconds": round(at, 3), "window_auto": plan["window_auto"],
                       "comments_drawn": drawn, "icons": len(renderable),
                       "video_duration_seconds": ctx["video_dur"],
                       "duration_ms": int((time.monotonic() - started) * 1000)}},
    )
    return {"path": still_path, "at_seconds": at, "window_auto": plan["window_auto"],
            "comments_drawn": drawn, "stats": plan["stats"],
            "video_duration_seconds": ctx["video_dur"]}


async def _render_preview_clip(src: Path, plan: dict, out: Path, meta_path: Path,
                               signature: str, on_progress) -> None:
    ctx = plan["ctx"]
    window = plan["window"]
    win_start, win_end = window
    # プレビューも本出力と同じ3 pass構成(層描画→CFRベース→合成)を通る。窓ぶんとはいえ
    # 数十秒かかるので、本出力と同じ段階表示にする。
    progress = JobProgress(on_progress, PREVIEW_PHASES)
    win_seconds = max(0.0, win_end - win_start)
    comment_plan = plan["comment_plan"]
    render_started = time.monotonic()
    cfr_fps = min(ctx["fps"], CFR_FPS_CAP) if await _probe_is_vfr(src, ctx["fps"]) else None
    ass_path = sidecar_path(src, PREVIEW_ASS_SUFFIX)
    layer_path = sidecar_path(src, PREVIEW_LAYER_SUFFIX)
    prepass_file = None
    comment_layer = None
    render_src, main_cfr, main_scale = src, cfr_fps, ctx["scale_to"]
    seek_source = True
    draw_comments = _comments_in_window(comment_plan, window)
    try:
        await progress.done("plan", f"{fmt_hms(win_seconds)}ぶん")
        # base pre-passはcomment層を合成する時にしか作らない(下のbranchの中)。commentが
        # 窓に無ければ層もbaseも走らないので、両方まとめて重みから外す。
        if not draw_comments or cfr_fps is None:
            progress.disable("base")
        if not draw_comments:
            progress.disable("layer", "layer_encode")
        if draw_comments:
            await _resolve_emotes(comment_plan["shaper"],
                                  layout.emote_pool_dir())
            layer_fps = min(ctx["fps"], comment_layer_fps_cap())
            prepass_task = None
            if cfr_fps is not None:
                prepass_file = sidecar_path(src, PREVIEW_CLIP_BASE_SUFFIX)
                # 本出力と同じ組み方: baseは元解像度でCFR化だけ、拡大は本graphに残す。
                # ここが本出力と違うと、プレビューが本出力と別の絵を見せることになる。
                prepass_task = asyncio.create_task(
                    _prepass_cfr(src, prepass_file, None, cfr_fps,
                                 sidecar_dir(src), window=window,
                                 on_progress=progress.cb("base", win_seconds)))
            comment_layer = await _render_comment_layer(
                comment_plan["placements"], comment_plan["avatar_files"],
                comment_plan["metrics"], comment_plan["comment_fs"], comment_plan["shaper"],
                ctx["width"], ctx["height"], layer_fps, layer_path,
                comment_plan.get("avatar_upscale", False), window=window,
                progress=progress.thread_cb_multi(asyncio.get_running_loop()),
            )
            await progress.done("layer_encode")
            if prepass_task is not None:
                try:
                    await prepass_task
                    await progress.done("base")
                except Exception:
                    prepass_file.unlink(missing_ok=True)
                    prepass_file = None
                    raise
            if comment_layer is None:
                # 本出力はここでASSの白黒feedへ転落するが、プレビューでは転落させない。
                # 本出力と違う見た目を「プレビュー」として見せる方が有害なので、失敗を
                # そのまま失敗として返す。
                raise RuntimeError(
                    "プレビューのComment層を描画できませんでした。"
                    "空き容量とPillow/fontのinstallを確認してください。"
                )
            if prepass_file is not None:
                render_src, main_cfr, main_scale = prepass_file, None, ctx["scale_to"]
                seek_source = False  # pre-passが既に窓で切っている
        renderable = await _preview_render_inputs(src, plan)
        ass_path.write_text(plan["ass_text"], encoding="utf-8")
        await _run_ffmpeg(
            render_src, renderable, ctx["icon_px"], ass_path.name, out, sidecar_dir(src),
            ctx["quality"], codec=ctx["codec"], comment_layer=comment_layer,
            on_progress=progress.cb("encode", win_seconds), scale_to=main_scale, cfr_fps=main_cfr,
            window=window, seek_source=seek_source,
            # layer fileは常に0始まり。窓の絶対位置へずらして初めてbaseと噛み合う。
            layer_offset=(win_start if comment_layer is not None else 0.0),
        )
        await progress.done("encode")
    finally:
        ass_path.unlink(missing_ok=True)
        layer_path.unlink(missing_ok=True)
        if prepass_file is not None:
            prepass_file.unlink(missing_ok=True)
    meta_path.write_text(signature, encoding="utf-8")
    logger.info(
        "overlay preview clip rendered: %s (%.3f..%.3fs, comments=%s)",
        out.name, win_start, win_end, comment_layer is not None,
        extra={"event": "overlay.preview_clip_rendered",
               "ctx": {"path": str(out.resolve()), "stem": src.stem,
                       "window_start_seconds": round(win_start, 3),
                       "window_end_seconds": round(win_end, 3),
                       "window_auto": plan["window_auto"],
                       "comment_layer_used": comment_layer is not None,
                       "prepass_used": prepass_file is not None,
                       "codec": ctx["codec"], "quality": ctx["quality"],
                       "size_bytes": out.stat().st_size if out.is_file() else None,
                       "duration_ms": int((time.monotonic() - render_started) * 1000)}},
    )


async def preview_clip(src_path: str, started_at: float, ended_at,
                       events: list, settings, battles=None, transcript=None,
                       on_progress=None, at_seconds=None) -> dict:
    """焼き込み設定の動画プレビュー。実解像度・実codec・実qualityのまま、media PTS窓の
    ぶんだけを焼き込む。窓は comment layerのrender・CFR pre-pass・本encode の3箇所すべてに
    効かせる(1つでも全尺のままなら本出力とcostが変わらず、プレビューの意味が消える)。

    描画planは全尺のまま組み、窓はffmpegのseekと``-copyts``でしか効かせない。時刻mapを
    組み直さないので、ここで見えたズレは本出力でも同じだけ起きる。"""
    src = Path(src_path)
    seconds = preview_seconds(settings)
    plan = await _preview_plan(src, settings, started_at, ended_at, events, battles,
                               transcript, seconds, at_seconds)
    ctx, cfg = plan["ctx"], plan["cfg"]
    window = plan["window"]
    win_start, win_end = window
    _still, clip_path, meta_path = preview_paths(src)
    signature = _signature(
        src, cfg, timing_path(src),
        # 本出力のsignature空間と絶対に交差させないため、variantに窓まで畳み込む。
        variant=f"preview:{win_start:.3f}:{win_end:.3f}",
        events_sig=_events_fingerprint(events),
        subtitles_sig=(subtitles.fingerprint(transcript)
                       if cfg.get("video_overlay_subtitles") else ""),
    )
    lock = await _get_lock(f"preview-clip:{clip_path}")
    async with lock:
        if clip_path.is_file() and meta_path.is_file():
            try:
                if meta_path.read_text(encoding="utf-8").strip() == signature:
                    return {"path": clip_path, "window": window,
                            "window_auto": plan["window_auto"], "cached": True,
                            "video_duration_seconds": ctx["video_dur"]}
            except OSError:
                pass
        async with gpu_slot_async(f"overlay-preview:{clip_path.stem}"):
            await _render_preview_clip(src, plan, clip_path, meta_path, signature,
                                       on_progress)
    return {"path": clip_path, "window": window, "window_auto": plan["window_auto"],
            "cached": False, "video_duration_seconds": ctx["video_dur"]}
