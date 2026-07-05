import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger("tictok.avatar")

# TikTok / ByteDance CDN host suffixes that serve avatar images. The proxy only
# fetches from these so that ?u= cannot be abused to make the server request
# arbitrary internal or third-party URLs (SSRF).
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

# CDN avatar bytes are stable for a given signed URL; cache so repeated tiles /
# screens do not re-hit the CDN, and so a later URL expiry does not flicker the
# image during a session.
_CACHE_TTL_SECONDS = 6 * 60 * 60
_CACHE_MAX_ENTRIES = 512
_FETCH_TIMEOUT_SECONDS = 8.0
_MAX_BYTES = 4 * 1024 * 1024

# TikTok's CDN hotlink-blocks requests without a browser User-Agent / Referer,
# which is the exact failure that makes <img src=cdnUrl> break in the browser.
_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.tiktok.com/",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


class _Entry:
    __slots__ = ("content", "content_type", "expires_at")

    def __init__(self, content: bytes, content_type: str, expires_at: float) -> None:
        self.content = content
        self.content_type = content_type
        self.expires_at = expires_at


class AvatarProxy:
    """Server-side fetch + cache for TikTok CDN avatar images so the browser
    loads them same-origin, bypassing CDN hotlink/Referer restrictions and URL
    expiry.

    Resolution tiers:
    - In-memory (all avatars): fast path for repeated views within a session.
    - By-id pool (:class:`AvatarPool`): a user's latest avatar, persisted at
      capture time. Lets an expired URL still render the user's current avatar as
      long as it was cached in any session — the same pool the video burn-in uses.
    - Legacy on-disk copies (by URL path / by owner id) written by older builds
      before the unified pool; read-only fallback so existing data keeps working.

    On total miss the caller returns an error and the UI keeps its initial-letter
    fallback (no fabricated avatar)."""

    def __init__(self, cache_dir: Path, pool=None) -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._pool = pool
        self._client = httpx.AsyncClient(
            timeout=_FETCH_TIMEOUT_SECONDS, follow_redirects=True
        )
        self._cache: "OrderedDict[str, _Entry]" = OrderedDict()
        self._url_locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def is_allowed(url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            return False
        host = (parts.hostname or "").lower()
        return any(host == suffix.lstrip(".") or host.endswith(suffix) for suffix in _ALLOWED_HOST_SUFFIXES)

    async def fetch(self, url: str, user_key: Optional[str] = None) -> Optional[tuple[bytes, str]]:
        """Resolve an avatar: memory cache -> any local copy we already hold (the
        user's pooled avatar by ``user_key``, or an on-disk copy by URL path) ->
        live CDN fetch. Local copies are served first so an avatar captured while
        its URL was fresh never triggers a doomed CDN round-trip: signed URLs expire
        within hours, so re-fetching an already-cached one only 403s before falling
        back to the very copy we could have served immediately. The CDN is hit only
        for an avatar we have never seen (no pool/disk copy yet)."""
        now = time.time()
        cached = self._cache.get(url)
        if cached is not None and cached.expires_at > now:
            self._cache.move_to_end(url)
            return cached.content, cached.content_type

        async with self._lock_for(url):
            cached = self._cache.get(url)
            if cached is not None and cached.expires_at > time.time():
                self._cache.move_to_end(url)
                return cached.content, cached.content_type
            # Local-first: if we already hold this avatar, serve it without touching
            # the CDN. Only a genuinely new avatar reaches the network fetch below.
            local = self._load_local(url, user_key)
            if local is not None:
                self._remember(url, *local)
                return local
            downloaded = await self._download(url)
            if downloaded is not None:
                self._remember(url, *downloaded)
                return downloaded
            return None

    def _load_local(self, url: str, user_key: Optional[str]) -> Optional[tuple[bytes, str]]:
        """Best already-held copy of this avatar, or None. Order: the by-id pool
        (canonical per user, shared with history and the video burn-in), then legacy
        on-disk copies written before the unified pool (by URL path, then by owner
        id). No network access."""
        if user_key and self._pool is not None:
            pooled = self._pool.get(user_key)
            if pooled is not None:
                return pooled
        disk = self._load_disk(url)
        if disk is not None:
            return disk
        if user_key:
            owner = self._load_owner(user_key)
            if owner is not None:
                return owner
        return None

    def _lock_for(self, url: str) -> asyncio.Lock:
        # One in-flight fetch per URL; concurrent tiles requesting the same
        # avatar wait on the cache rather than stampeding the CDN.
        lock = self._url_locks.get(url)
        if lock is None:
            if len(self._url_locks) >= 512:
                # 署名URLはローテーションして二度と戻らないため、使用中でない
                # lockを間引いて無制限に増えないようにする。
                self._url_locks = {
                    u: l for u, l in self._url_locks.items() if l.locked()
                }
            lock = self._url_locks.setdefault(url, asyncio.Lock())
        return lock

    async def _download(self, url: str) -> Optional[tuple[bytes, str]]:
        try:
            resp = await self._client.get(url, headers=_FETCH_HEADERS)
            resp.raise_for_status()
            content = resp.content
            if len(content) > _MAX_BYTES:
                logger.warning("avatar too large (%d bytes): %s", len(content), url)
                return None
            content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            if not content_type.startswith("image/"):
                logger.warning("avatar non-image content-type %r: %s", content_type, url)
                return None
            return content, content_type
        except httpx.HTTPStatusError as exc:
            # Reached only for an avatar with no local copy (fetch() serves pool/disk
            # first). A signed URL can still 403 if it expired before we ever cached
            # it; log concisely without a stack trace — it is an expected CDN state,
            # not a server fault. The UI keeps its initial-letter avatar.
            logger.info("avatar fetch HTTP %d (no local copy): %s", exc.response.status_code, url)
            return None
        except Exception:
            logger.warning("avatar fetch failed: %s", url, exc_info=True)
            return None

    def _remember(self, url: str, content: bytes, content_type: str) -> None:
        self._cache[url] = _Entry(content, content_type, time.time() + _CACHE_TTL_SECONDS)
        self._cache.move_to_end(url)
        while len(self._cache) > _CACHE_MAX_ENTRIES:
            self._cache.popitem(last=False)

    def _disk_paths(self, url: str) -> tuple[Path, Path]:
        # Key by path only: the same avatar image keeps a stable path across
        # sessions even as the query signature / CDN region host changes.
        key = hashlib.sha256(urlsplit(url).path.encode("utf-8")).hexdigest()
        return self._cache_dir / key, self._cache_dir / f"{key}.type"

    def _load_disk(self, url: str) -> Optional[tuple[bytes, str]]:
        bin_path, type_path = self._disk_paths(url)
        try:
            if not bin_path.is_file():
                return None
            content = bin_path.read_bytes()
            content_type = (
                type_path.read_text(encoding="utf-8").strip()
                if type_path.is_file()
                else "image/jpeg"
            )
            return content, content_type
        except OSError:
            logger.warning("failed to read persisted avatar: %s", url, exc_info=True)
            return None

    def _owner_disk_paths(self, owner_key: str) -> tuple[Path, Path]:
        # Key by the broadcaster id (overwritten with their latest avatar), so it
        # is independent of the per-session URL and survives URL/path changes.
        key = hashlib.sha256(f"owner:{owner_key}".encode("utf-8")).hexdigest()
        owner_dir = self._cache_dir / "owner"
        return owner_dir / key, owner_dir / f"{key}.type"

    def _load_owner(self, owner_key: str) -> Optional[tuple[bytes, str]]:
        bin_path, type_path = self._owner_disk_paths(owner_key)
        try:
            if not bin_path.is_file():
                return None
            content = bin_path.read_bytes()
            content_type = (
                type_path.read_text(encoding="utf-8").strip()
                if type_path.is_file()
                else "image/jpeg"
            )
            return content, content_type
        except OSError:
            logger.warning("failed to read owner avatar by id: %s", owner_key, exc_info=True)
            return None
