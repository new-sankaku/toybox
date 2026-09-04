"""User単位のavatar画像をdiskへ永続cacheする単一pool。

owner(配信者)もcomment/gift userも、すべて同じuser key(unique_id、無ければ
nickname)で同じpoolへ保存し、同じpoolから読む。これにより:
  - browser proxy(AvatarProxy)は署名URL期限切れ時にid単位でこのpoolへfallbackする。
  - 履歴のowner avatarも同様にid単位でこのpoolから復元する。
  - 動画burn-in(video_overlay)はcommentのuser keyでこのpoolの画像を合成する。

同一人物のavatarがowner経由・comment経由のどちらで取得されても1fileに集約され、
ある場面で取得できなかったuserも、別場面で取得済みなら代替される。

avatarのCDN URLは署名付きで後から403になり得るため、URLが新鮮なうち(収集時)に
diskへ保存しておく。GiftIconCacheと同じ持続化方針。Windows/Linux双方で動作する。
"""

import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger("tictok.avatar_pool")

# TikTok / ByteDance CDN host suffixes that serve avatar images. Restrict fetches
# to these so a malicious URL cannot turn this into an SSRF vector.
_ALLOWED_HOST_SUFFIXES = (
    ".tiktokcdn.com",
    ".tiktokcdn-us.com",
    ".tiktokcdn-eu.com",
    ".ibyteimg.com",
    ".ibytedtos.com",
    ".byteimg.com",
    ".muscdn.com",
    ".tiktokv.com",
)

_FETCH_TIMEOUT_SECONDS = 8.0
_MAX_BYTES = 4 * 1024 * 1024
_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.tiktok.com/",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}

# HTTP statuses worth retrying: the request was throttled or the edge had a
# transient fault. A 403/404 on a fresh capture-time URL will not become valid by
# retrying, and re-hitting it only brings rate-limit blocking closer, so those are
# treated as permanent and not retried.
_RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})

# TikTok CDN avatar URLs look like
#   /tos-.../<object-id>~tplv-tiktok-shrink:72:72.webp?x-signature=...
# The <object-id> before ``~tplv`` is stable across renditions (thumb/medium/larger)
# of the SAME uploaded avatar and only changes when the user uploads a new avatar;
# the ``:W:H`` template gives the rendition's pixel size; the query is a per-fetch
# signature. Splitting these lets the pool tell a genuine avatar change (new object
# id) and a higher-resolution rendition (larger W:H) apart from a mere re-sign of the
# identical image (same object id + template, different signature) — so a fetch is
# only spent when it would actually change what is stored.
_TPLV_SIZE_RE = re.compile(r"tplv[^/?#]*?:(\d+):(\d+)")


def _avatar_identity(url: str) -> str:
    """Per-avatar identity: the CDN object-id path with the size template and signing
    query stripped, so every rendition/signature of one uploaded avatar shares it and
    a changed avatar gets a new one. Falls back to the full path when no ``~tplv``
    template is present."""
    path = urlsplit(url).path
    marker = path.find("~tplv")
    return path[:marker] if marker >= 0 else path


def _url_res_hint(url: str) -> int:
    """Largest output dimension the URL's ``~tplv`` size template encodes (e.g.
    ``shrink:72:72`` -> 72, ``cropcenter:1080:1080`` -> 1080), or 0 when absent."""
    m = _TPLV_SIZE_RE.search(url)
    return max(int(m.group(1)), int(m.group(2))) if m else 0


_pillow_missing_reported = False


def _image_size(source) -> Optional[tuple[int, int]]:
    """(width, height) of an image given a path or raw bytes, or None when Pillow is
    unavailable or the image cannot be read. Best-effort — callers fall back to the
    URL size hint so the pool never hard-depends on Pillow.

    Both failure modes used to return None in silence, which mattered: with no real
    pixel size the pool compares an incoming rendition against a guess, so it can stop
    following a genuine avatar upgrade and no line anywhere says why. Pillow being
    absent is a once-per-process condition and is reported once; a single unreadable
    image is per-avatar and stays at debug so a burn-in with tens of thousands of
    avatars cannot turn the log into an image-decode trace."""
    global _pillow_missing_reported
    try:
        import io

        from PIL import Image
    except ImportError:
        if not _pillow_missing_reported:
            _pillow_missing_reported = True
            logger.warning(
                "Pillowが利用できないためavatarのsizeはURLのsize hintに依存し、"
                "解像度の向上を検出できない場合があります",
                extra={"event": "collector.avatar_sizing_degraded",
                       "ctx": {"reason": "pillow_missing"}},
                exc_info=True,
            )
        return None
    try:
        opener = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
        with Image.open(opener) as im:
            return int(im.width), int(im.height)
    except Exception:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "avatar imageのpixel sizeを読み取れませんでした",
                extra={"event": "collector.avatar_size_read_failed",
                       "ctx": {"path": str(source) if not isinstance(source, (bytes, bytearray)) else "",
                               "size_bytes": len(source) if isinstance(source, (bytes, bytearray)) else None}},
                exc_info=True,
            )
        return None


def avatar_key(user_id: str) -> str:
    """Stable on-disk filename stem for a user, derived from the user key
    (unique_id, or nickname when the id is absent). The burn-in side computes the
    same key from the stored event fields to locate the cached image."""
    return hashlib.sha1((user_id or "").encode("utf-8")).hexdigest()


class AvatarPool:
    """Durable on-disk avatar store keyed by user, shared by owner and commenter
    avatars. Populated at capture time so the burn-in pipeline can composite real
    avatars even after the signed CDN URL would 403, and so the browser proxy and
    history can fall back to a user's latest avatar by id.

    Stores ``<key>.img`` (image bytes) and ``<key>.type`` (content-type). Legacy
    ``.img`` files without a sibling ``.type`` read back as ``image/jpeg``.

    Best-effort throughout: a failed download never blocks collection."""

    def __init__(
        self,
        cache_dir: Path,
        legacy_dir: Path | None = None,
        concurrency: int = 6,
        attempts: int = 3,
        backoff_seconds: float = 1.5,
    ) -> None:
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SECONDS, follow_redirects=True)
        self._locks: dict[str, asyncio.Lock] = {}
        # Cap concurrent downloads so a burst of comments cannot exhaust the
        # connection pool (the failure mode that makes fresh-URL fetches time out
        # and never reach disk).
        self._sem = asyncio.Semaphore(max(1, concurrency))
        self._attempts = max(1, attempts)
        self._backoff = max(0.0, backoff_seconds)
        if legacy_dir is not None:
            self._migrate_legacy(Path(legacy_dir))

    def _migrate_legacy(self, legacy_dir: Path) -> None:
        """Adopt avatars from a previous pool directory that used the same per-user
        key. Files already present in the new pool are left untouched."""
        if not legacy_dir.is_dir() or legacy_dir == self._dir:
            return
        moved = 0
        for src in legacy_dir.glob("*.img"):
            dst = self._dir / src.name
            if dst.exists():
                continue
            try:
                src.replace(dst)
                moved += 1
            except OSError:
                logger.warning(
                    "旧形式のavatar %s の移行に失敗しました", src.name,
                    extra={"event": "collector.avatar_migration_failed",
                           "ctx": {"path": str(src)}},
                    exc_info=True,
                )
        if moved:
            logger.info(
                "旧形式のavatar %d 件を %s へ移行しました", moved, self._dir,
                extra={"event": "collector.avatars_migrated",
                       "ctx": {"moved": moved, "path": str(self._dir)}},
            )

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def is_allowed(url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            return False
        host = (parts.hostname or "").lower()
        return any(host == suffix.lstrip(".") or host.endswith(suffix) for suffix in _ALLOWED_HOST_SUFFIXES)

    def path_for(self, user_id: str) -> Path:
        return self._dir / f"{avatar_key(user_id)}.img"

    def _type_path(self, user_id: str) -> Path:
        return self._dir / f"{avatar_key(user_id)}.type"

    def _meta_path(self, user_id: str) -> Path:
        return self._dir / f"{avatar_key(user_id)}.meta"

    def _read_meta(self, user_id: str) -> Optional[dict]:
        """Stored ``{aid, w, h}`` describing the on-disk avatar's identity and pixel
        size, or None for a legacy avatar saved before metadata was tracked."""
        path = self._meta_path(user_id)
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except (OSError, ValueError):
            logger.warning(
                "avatarのmetaを読み取れないため次回の取得判定はmeta無しで行います"
                "（user=%s）", user_id,
                extra={"event": "collector.avatar_meta_read_failed",
                       "ctx": {"user_id": user_id, "path": str(path)}},
                exc_info=True,
            )
        return None

    def _write_meta(self, user_id: str, aid: str, width: int, height: int) -> None:
        try:
            self._meta_path(user_id).write_text(
                json.dumps({"aid": aid, "w": int(width), "h": int(height)}),
                encoding="utf-8",
            )
        except OSError:
            logger.warning(
                "avatarのmetaを書き込めないためこのuserのavatarの向上を検出できません"
                "（user=%s）", user_id,
                extra={"event": "collector.avatar_meta_write_failed",
                       "ctx": {"user_id": user_id, "path": str(self._meta_path(user_id))}},
                exc_info=True,
            )

    def needs_update(self, user_id: str, url: str) -> bool:
        """Whether persisting ``url`` would change what is stored for ``user_id``.

        True when the user has no cached avatar, when ``url`` is a higher-resolution
        rendition of the same avatar, or when it is a different avatar (the user
        changed it). A same-rendition re-sign (identical object id + size, new
        signature) returns False so a fetch — and a step toward a rate-limit block —
        is not spent on it. Cheap (a stat + a small metadata read); safe to call on
        the event loop before scheduling a download."""
        if not user_id or not url or not self.is_allowed(url):
            return False
        img = self.path_for(user_id)
        try:
            if not (img.is_file() and img.stat().st_size > 0):
                return True
        except OSError:
            return True
        aid = _avatar_identity(url)
        res = _url_res_hint(url)
        meta = self._read_meta(user_id)
        if meta is None:
            # Legacy avatar (no metadata): adopt the incoming identity and the image's
            # on-disk size so change/upgrade detection works from here on, without a
            # mass re-fetch of the whole legacy pool. Only a clearly higher-resolution
            # rendition triggers an upgrade fetch now; a genuine later change is caught
            # once this backfilled identity no longer matches.
            size = _image_size(img)
            width, height = size if size else (res or 72, res or 72)
            if res > height:
                return True
            self._write_meta(user_id, aid, width, height)
            return False
        if meta.get("aid") != aid:
            return True  # the user uploaded a different avatar — follow the change
        if res > int(meta.get("h") or 0):
            return True  # a higher-resolution rendition of the same avatar
        return False

    def has(self, user_id: str) -> bool:
        if not user_id:
            return False
        path = self.path_for(user_id)
        try:
            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    def get(self, user_id: str) -> tuple[bytes, str] | None:
        """Read a user's cached avatar bytes and content-type, for the browser
        proxy / history by-id fallback. Returns None when not cached."""
        if not user_id:
            return None
        path = self.path_for(user_id)
        try:
            if not path.is_file():
                return None
            content = path.read_bytes()
            if not content:
                return None
            type_path = self._type_path(user_id)
            content_type = (
                type_path.read_text(encoding="utf-8").strip()
                if type_path.is_file()
                else "image/jpeg"
            )
            return content, content_type
        except OSError:
            logger.warning(
                "pool内のavatarを読み取れませんでした（user=%s）", user_id,
                extra={"event": "collector.avatar_read_failed",
                       "ctx": {"user_id": user_id, "path": str(path)}},
                exc_info=True,
            )
            return None

    async def persist(self, user_id: str, url: str) -> bool:
        """Download the avatar and store it as ``<key>.img`` / ``<key>.type`` /
        ``<key>.meta``. Returns True if an avatar for the user is on disk afterwards.

        A fetch runs only when :meth:`needs_update` says it would change what is
        stored — the user has no avatar yet, ``url`` is a higher-resolution rendition
        of the same avatar, or the user changed their avatar (new object id). This
        both prefers the highest resolution ever seen for a user and follows avatar
        changes, while never re-fetching a mere re-signed copy of the same rendition.

        A signed CDN URL is only fresh at capture time, so a transient failure here
        is unrecoverable later (the video burn-in cannot re-fetch a 403'd URL).
        Transient failures are therefore retried with a back-off; permanent ones
        (4xx other than throttling) are not, to avoid hastening a rate-limit block.
        On failure any previously stored avatar is kept rather than dropped."""
        if not user_id or not url or not self.is_allowed(url):
            return False
        # diskを見る判定(stat + meta読み)と書き込みはthreadで行う。この協程はevent loop上の
        # worker(asset_prefetch)から呼ばれ、diskが応答しない間にloopを止めない。
        if not await asyncio.to_thread(self.needs_update, user_id, url):
            return await asyncio.to_thread(self.has, user_id)
        aid = _avatar_identity(url)
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            if not await asyncio.to_thread(self.needs_update, user_id, url):
                return await asyncio.to_thread(self.has, user_id)
            for attempt in range(1, self._attempts + 1):
                retryable, done = await self._try_fetch(user_id, url, aid, attempt)
                if done:
                    return True
                if not retryable or attempt == self._attempts:
                    if retryable and not self.has(user_id):
                        # Every retry is spent and nothing is on disk. The individual
                        # attempts logged as recoverable warnings; this is the line that
                        # says the recovery never happened.
                        logger.error(
                            "%s のavatarを %d 回試行しても保存できませんでした"
                            "（署名付きURLのため後から再試行できません）",
                            user_id, self._attempts,
                            extra={"event": "collector.avatar_persist_exhausted",
                                   "ctx": {"user_id": user_id,
                                           "attempts": self._attempts}},
                        )
                    return self.has(user_id)
                # Back off between retries (Nth retry waits base * N) and release
                # the concurrency slot during the wait so other avatars proceed.
                await asyncio.sleep(self._backoff * attempt)
            return self.has(user_id)

    def _store(self, user_id: str, content: bytes, content_type: str, url: str,
               aid: str) -> tuple[int, int]:
        """取得した画像と種別・metaをdiskへ置く(threadで呼ぶ)。(width, height)を返す。"""
        self.path_for(user_id).write_bytes(content)
        self._type_path(user_id).write_text(content_type, encoding="utf-8")
        size = _image_size(content)
        hint = _url_res_hint(url)
        width, height = size if size else (hint or 72, hint or 72)
        self._write_meta(user_id, aid, width, height)
        return width, height

    async def _try_fetch(self, user_id: str, url: str, aid: str, attempt: int) -> tuple[bool, bool]:
        """One download attempt. Returns ``(retryable, succeeded)``: ``succeeded``
        True means the avatar is on disk; otherwise ``retryable`` says whether
        another attempt could help. On success the identity ``aid`` and the decoded
        pixel size are recorded in ``<key>.meta`` for later change/upgrade decisions."""
        try:
            async with self._sem:
                resp = await self._client.get(url, headers=_FETCH_HEADERS)
            resp.raise_for_status()
            content = resp.content
            if not content or len(content) > _MAX_BYTES:
                # Not retried, and the signed URL will not be valid later: this user's
                # avatar is permanently unavailable to the burn-in.
                logger.error(
                    "%s のavatar responseが使用できないため（%d bytes）"
                    "このuserのavatarは失われます", user_id, len(content),
                    extra={"event": "collector.avatar_persist_failed",
                           "ctx": {"user_id": user_id, "reason": "invalid_size",
                                   "size_bytes": len(content), "max_bytes": _MAX_BYTES,
                                   "attempt": attempt, "attempts": self._attempts}},
                )
                return False, False
            content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            if not content_type.startswith("image/"):
                content_type = "image/jpeg"
            width, height = await asyncio.to_thread(
                self._store, user_id, content, content_type, url, aid)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "%s のavatarを保存しました（%dx%d, %d bytes）",
                    user_id, width, height, len(content),
                    extra={"event": "collector.avatar_persisted",
                           "ctx": {"user_id": user_id, "width": width, "height": height,
                                   "size_bytes": len(content), "attempt": attempt}},
                )
            return False, True
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            retryable = status in _RETRYABLE_STATUSES
            # A non-retryable status on a capture-time URL is terminal: the URL is signed
            # and cannot be re-fetched later, so the burn-in will never have this avatar.
            log = logger.warning if retryable else logger.error
            log(
                "avatarの保存がHTTP %d で失敗しました（user=%s, attempt=%d/%d, 再試行=%s）: %s",
                status, user_id, attempt, self._attempts, retryable, url,
                extra={"event": "collector.avatar_persist_failed",
                       "ctx": {"user_id": user_id, "reason": "http_status",
                               "status": status, "retryable": retryable,
                               "attempt": attempt, "attempts": self._attempts}},
            )
            return retryable, False
        except (httpx.TimeoutException, httpx.TransportError):
            logger.warning(
                "avatarの保存でtransport errorが発生しました（user=%s, attempt=%d/%d）: %s",
                user_id, attempt, self._attempts, url,
                extra={"event": "collector.avatar_persist_retried",
                       "ctx": {"user_id": user_id, "reason": "transport",
                               "attempt": attempt, "attempts": self._attempts}},
                exc_info=True,
            )
            return True, False
        except Exception:
            # No retry follows and the URL expires, so this avatar is gone for good --
            # it will be missing from every burn-in of every recording this user appears
            # in. Previously a warning, which understated a permanent data loss.
            logger.error(
                "avatarの保存に失敗しました（user=%s, attempt=%d/%d）: %s",
                user_id, attempt, self._attempts, url,
                extra={"event": "collector.avatar_persist_failed",
                       "ctx": {"user_id": user_id, "reason": "unexpected",
                               "attempt": attempt, "attempts": self._attempts}},
                exc_info=True,
            )
            return False, False
