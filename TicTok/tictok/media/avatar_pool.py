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
import logging
from pathlib import Path
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
                logger.warning("failed to migrate legacy avatar: %s", src, exc_info=True)
        if moved:
            logger.info("migrated %d legacy avatar(s) into %s", moved, self._dir)

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
            logger.warning("failed to read pooled avatar (user=%s)", user_id, exc_info=True)
            return None

    async def persist(self, user_id: str, url: str) -> bool:
        """Download the avatar and store it as ``<key>.img`` / ``<key>.type``.
        Returns True if the avatar is on disk afterwards (already cached counts as
        success).

        A signed CDN URL is only fresh at capture time, so a transient failure here
        is unrecoverable later (the video burn-in cannot re-fetch a 403'd URL).
        Transient failures are therefore retried with a back-off; permanent ones
        (4xx other than throttling) are not, to avoid hastening a rate-limit block."""
        if not user_id or not url or not self.is_allowed(url):
            return False
        if self.has(user_id):
            return True
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            if self.has(user_id):
                return True
            for attempt in range(1, self._attempts + 1):
                retryable, done = await self._try_fetch(user_id, url, attempt)
                if done:
                    return True
                if not retryable or attempt == self._attempts:
                    return False
                # Back off between retries (Nth retry waits base * N) and release
                # the concurrency slot during the wait so other avatars proceed.
                await asyncio.sleep(self._backoff * attempt)
            return False

    async def _try_fetch(self, user_id: str, url: str, attempt: int) -> tuple[bool, bool]:
        """One download attempt. Returns ``(retryable, succeeded)``: ``succeeded``
        True means the avatar is on disk; otherwise ``retryable`` says whether
        another attempt could help."""
        try:
            async with self._sem:
                resp = await self._client.get(url, headers=_FETCH_HEADERS)
            resp.raise_for_status()
            content = resp.content
            if not content or len(content) > _MAX_BYTES:
                logger.warning("avatar size invalid (user=%s, %d bytes)", user_id, len(content))
                return False, False
            content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            if not content_type.startswith("image/"):
                content_type = "image/jpeg"
            self.path_for(user_id).write_bytes(content)
            self._type_path(user_id).write_text(content_type, encoding="utf-8")
            return False, True
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            retryable = status in _RETRYABLE_STATUSES
            logger.warning(
                "avatar persist HTTP %d (user=%s, attempt=%d/%d, retry=%s): %s",
                status, user_id, attempt, self._attempts, retryable, url,
            )
            return retryable, False
        except (httpx.TimeoutException, httpx.TransportError):
            logger.warning(
                "avatar persist transport error (user=%s, attempt=%d/%d): %s",
                user_id, attempt, self._attempts, url, exc_info=True,
            )
            return True, False
        except Exception:
            logger.warning(
                "avatar persist failed (user=%s, attempt=%d/%d): %s",
                user_id, attempt, self._attempts, url, exc_info=True,
            )
            return False, False
