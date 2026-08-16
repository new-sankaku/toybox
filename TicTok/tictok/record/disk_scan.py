"""録画root配下の容量内訳をfilesystem走査で集計する。

``recordings.bytes`` はmp4本体のbytesしか持たない。焼き込み(.overlay.mp4)・高画質化
(.up.mp4)・renderの中間物(.cfrbase.mp4/.comments.mov)・HLS(.ts)・avatar/gift iconの
cacheはDBに一切載らないため、「何が容量を食っているか」に答えるにはfilesystemを実際に
歩くしかない。このmoduleが layout の規約に沿って歩き、配信者別・種別別のbytesへ畳む。

数TB規模のHDDでは1回の走査が数十秒〜分かかるblocking処理なので、呼び出し側は必ず
別thread(``asyncio.to_thread``)で回し、結果をcacheすること。読めなかったdirectoryは
黙って0として畳まず ``errors`` に残す(空き容量と同じで、測れなかったものを測れたことに
してはならない)。
"""
import logging
import os
from pathlib import Path

from tictok.core import layout
from tictok.record.recorder import (
    NORMALIZE_DONE_SUFFIX,
    NORMALIZE_TMP_SUFFIX,
    SIDECAR_DIRNAME,
    TIMING_SUFFIX,
)
from tictok.record.upscale import (
    UPSCALE_LOG_SUFFIX,
    UPSCALE_META_SUFFIX,
    UPSCALE_SUFFIX,
)
from tictok.record.video_overlay import (
    ASS_SUFFIX,
    ASS_SUFFIX_B,
    CFR_BASE_SUFFIX,
    CFR_SUFFIX,
    COMMENT_LAYER_SUFFIX,
    EMOTE_CACHE_DIR,
    ICON_CACHE_DIR,
    META_SUFFIX,
    META_SUFFIX_B,
    OVERLAY_SUFFIX,
    OVERLAY_SUFFIX_B,
    PREVIEW_ASS_SUFFIX,
    PREVIEW_CLIP_BASE_SUFFIX,
    PREVIEW_CLIP_META_SUFFIX,
    PREVIEW_CLIP_SUFFIX,
    PREVIEW_LAYER_SUFFIX,
    PREVIEW_RAW_SUFFIX,
    PREVIEW_STILL_SUFFIX,
    TIMING_DEBUG_SUFFIX,
)

logger = logging.getLogger("tictok.disk_scan")

AVATAR_CACHE_DIR = "avatars"
BACKUP_DIRNAME = "_backup"

CATEGORY_SOURCE = "source"
CATEGORY_OVERLAY = "overlay"
CATEGORY_UPSCALE = "up"
CATEGORY_TRANSIENT = "transient"
CATEGORY_HLS = "ts"
CATEGORY_SIDECAR = "sidecar"
CATEGORY_AVATAR = "avatar"
CATEGORY_ICON = "icon"
CATEGORY_CLIP = "clip"
CATEGORY_BACKUP = "backup"
CATEGORY_OTHER = "other"

# 表示順と文言。画面側は判定も文言も持たず、この定義をそのまま描画する。
CATEGORY_LABELS = [
    (CATEGORY_SOURCE, "生録画(mp4)"),
    (CATEGORY_OVERLAY, "焼き込み(overlay)"),
    # 呼称はJob画面・運用logと同じ「Up出力」に揃える。同じ物を画面ごとに別名で呼ぶと、
    # 「Up出力が800GB」という会話が画面をまたいで通じなくなる。
    (CATEGORY_UPSCALE, "Up出力(up)"),
    (CATEGORY_TRANSIENT, "renderの中間file"),
    (CATEGORY_HLS, "HLS中間data(.ts)"),
    (CATEGORY_SIDECAR, "sidecar(timing/meta/log)"),
    (CATEGORY_AVATAR, "アイコンcache"),
    (CATEGORY_ICON, "Gift Icon/絵文字cache"),
    (CATEGORY_CLIP, "切り出しclip"),
    (CATEGORY_BACKUP, "再mp4化の退避(_backup)"),
    (CATEGORY_OTHER, "その他"),
]
CATEGORIES = [key for key, _ in CATEGORY_LABELS]

# 元mp4と収集eventから作り直せる種別。retentionが触ってよいのはここだけで、
# source は唯一の再取得不能資産なので別扱いにする(削除順序の根拠)。
REGENERABLE_CATEGORIES = (CATEGORY_OVERLAY, CATEGORY_UPSCALE, CATEGORY_TRANSIENT)

# 判定は上から順に最初に一致したもの。多段suffix(.overlay.b.mp4 は .overlay.mp4 で
# 終わらない)を取り違えないよう、長い/特殊なものを先に並べる。
_SUFFIX_CATEGORIES = (
    (UPSCALE_SUFFIX, CATEGORY_UPSCALE),
    (UPSCALE_META_SUFFIX, CATEGORY_UPSCALE),
    (UPSCALE_LOG_SUFFIX, CATEGORY_UPSCALE),
    (OVERLAY_SUFFIX_B, CATEGORY_OVERLAY),
    (OVERLAY_SUFFIX, CATEGORY_OVERLAY),
    (ASS_SUFFIX_B, CATEGORY_OVERLAY),
    (ASS_SUFFIX, CATEGORY_OVERLAY),
    (META_SUFFIX_B, CATEGORY_OVERLAY),
    (META_SUFFIX, CATEGORY_OVERLAY),
    (NORMALIZE_TMP_SUFFIX + NORMALIZE_DONE_SUFFIX, CATEGORY_TRANSIENT),
    (NORMALIZE_TMP_SUFFIX + ".ffmpeg.log", CATEGORY_TRANSIENT),
    (NORMALIZE_TMP_SUFFIX, CATEGORY_TRANSIENT),
    # プレビューは焼き込みの派生物。中間物(base/layer/raw/ass)はrenderが消すが、
    # 落ちた場合に備えて中間fileとして数える。判定は上から順なので、より長い
    # PREVIEW_CLIP_BASE_SUFFIX を CFR_BASE_SUFFIX より先に置く。
    (PREVIEW_CLIP_BASE_SUFFIX, CATEGORY_TRANSIENT),
    (PREVIEW_LAYER_SUFFIX, CATEGORY_TRANSIENT),
    (PREVIEW_RAW_SUFFIX, CATEGORY_TRANSIENT),
    (PREVIEW_ASS_SUFFIX, CATEGORY_TRANSIENT),
    (PREVIEW_CLIP_META_SUFFIX, CATEGORY_OVERLAY),
    (PREVIEW_CLIP_SUFFIX, CATEGORY_OVERLAY),
    (PREVIEW_STILL_SUFFIX, CATEGORY_OVERLAY),
    (CFR_BASE_SUFFIX, CATEGORY_TRANSIENT),
    (CFR_SUFFIX, CATEGORY_TRANSIENT),
    (COMMENT_LAYER_SUFFIX, CATEGORY_TRANSIENT),
    (TIMING_DEBUG_SUFFIX, CATEGORY_SIDECAR),
    (TIMING_SUFFIX, CATEGORY_SIDECAR),
)

_DIR_CATEGORIES = {
    SIDECAR_DIRNAME: CATEGORY_SIDECAR,
    AVATAR_CACHE_DIR: CATEGORY_AVATAR,
    ICON_CACHE_DIR: CATEGORY_ICON,
    EMOTE_CACHE_DIR: CATEGORY_ICON,
    BACKUP_DIRNAME: CATEGORY_BACKUP,
}
# 成果物の置き場(``_clips``/``_screenshots``)はここに置かない。置き場が配信者folderの下
# (``<配信者>/_clips/``)へ移り、root直下の名前では当たらなくなったため、path要素のどこに
# 在っても効く判定で拾う。

# 配信者に紐付かない共有領域のbytesをまとめる行のkey。実在する配信者名と衝突しない
# ように空文字を使い、文言は画面側ではなくこのmoduleが決める。
SHARED_STREAMER_KEY = ""
SHARED_STREAMER_LABEL = "共有(cache/clip/退避)"


def classify(rel_parts, name: str) -> tuple:
    """root からの相対path要素と file名から (種別, 配信者) を決める。

    配信者が決まらない共有cache等は ``SHARED_STREAMER_KEY`` を返す。捏造を避けるため、
    規約に合わない file は種別 ``other`` ・共有扱いにして黙って配信者へ按分しない。"""
    # 切り出しの置き場は**suffixより先に**見る。中身は焼き込み切り抜き(....overlay.mp4)や
    # Up出力から撮ったスクショ(....up.png)で、録画の派生物と同じsuffixを持つ。suffixを先に
    # 引くと、人が作った成果物が「焼き込み」「Up出力」として数えられ、retentionが触ってよい
    # 種別(REGENERABLE_CATEGORIES)の量にも混ざる。
    category = (CATEGORY_CLIP
                if any(part in layout.ARTIFACT_DIRNAMES for part in rel_parts) else None)
    if category is None:
        for suffix, cat in _SUFFIX_CATEGORIES:
            if name.endswith(suffix):
                category = cat
                break
    top = rel_parts[0] if rel_parts else ""
    if category is None:
        category = _DIR_CATEGORIES.get(top)
    if category is None:
        if layout.TS_DIRNAME in rel_parts:
            category = CATEGORY_HLS
        elif layout.MP4_DIRNAME in rel_parts and name.endswith(".mp4"):
            category = CATEGORY_SOURCE
        else:
            category = CATEGORY_OTHER
    if top and top not in layout.NON_STREAMER_DIRS:
        return category, top
    # 共有dir配下でも、録画artifact(sidecar/_backup)はfile名から配信者へ戻せる。
    _, streamer = layout.artifact_owner(name)
    return category, streamer or SHARED_STREAMER_KEY


def _walk(root: Path, totals: dict, errors: list) -> None:
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            errors.append({"path": str(current), "error": str(exc)})
            logger.warning(
                "disk使用量の集計中に %s を読み取れません", current,
                extra={"event": "storage.scan_dir_failed",
                       "ctx": {"path": str(current)}},
                exc_info=True,
            )
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                size = entry.stat(follow_symlinks=False).st_size
            except OSError as exc:
                errors.append({"path": entry.path, "error": str(exc)})
                continue
            rel_parts = Path(entry.path).relative_to(root).parts[:-1]
            category, streamer = classify(rel_parts, entry.name)
            bucket = totals.setdefault(streamer, {})
            slot = bucket.setdefault(category, [0, 0])
            slot[0] += size
            slot[1] += 1


def scan_roots(roots) -> dict:
    """録画rootを歩いて配信者別・種別別のbytesを返す(blocking)。

    同じrootが2度渡っても1度しか歩かない(work dir と final dir が同一設定のとき)。"""
    totals: dict = {}
    errors: list = []
    scanned: list = []
    seen: set = set()
    for raw in roots:
        root = Path(raw).resolve()
        if root in seen:
            continue
        seen.add(root)
        if not root.is_dir():
            errors.append({"path": str(root), "error": "directory not found"})
            continue
        scanned.append(str(root))
        _walk(root, totals, errors)

    categories = {key: {"bytes": 0, "files": 0} for key in CATEGORIES}
    streamers = []
    for streamer in sorted(totals):
        per_category = {}
        total_bytes = 0
        total_files = 0
        for category, (size, count) in totals[streamer].items():
            per_category[category] = {"bytes": size, "files": count}
            categories[category]["bytes"] += size
            categories[category]["files"] += count
            total_bytes += size
            total_files += count
        streamers.append({
            "streamer": streamer,
            "label": SHARED_STREAMER_LABEL if streamer == SHARED_STREAMER_KEY else streamer,
            "bytes": total_bytes,
            "files": total_files,
            "categories": per_category,
        })
    streamers.sort(key=lambda item: item["bytes"], reverse=True)
    return {
        "roots": scanned,
        "categories": categories,
        "category_labels": [{"key": key, "label": label} for key, label in CATEGORY_LABELS],
        "regenerable_categories": list(REGENERABLE_CATEGORIES),
        "streamers": streamers,
        "total_bytes": sum(info["bytes"] for info in categories.values()),
        "total_files": sum(info["files"] for info in categories.values()),
        "errors": errors,
    }
