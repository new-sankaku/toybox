"""収集時にGift Icon画像をdiskへ永続cacheする(burn-in用)。

Gift IconのCDN URLは後から取得できなくなり得る(署名/地域host)。録画Download時に
焼き込むには、収集時(URLが新鮮なうち)にgift_id別でdiskへ保存しておく必要がある。
AvatarProxyと同じ持続化方針。Windows/Linux双方で動作する。
"""

import asyncio
import json
import logging
from pathlib import Path
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger("tictok.gift_icons")

# TikTok / ByteDance CDN host suffixes that serve gift icons. Restrict fetches to
# these so a malicious URL cannot turn this into an SSRF vector.
_ALLOWED_HOST_SUFFIXES = (
    ".tiktokcdn.com",
    ".tiktokcdn-us.com",
    ".tiktokcdn-eu.com",
    ".ibyteimg.com",
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


class GiftIconCache:
    """Durable on-disk gift-icon store keyed by gift_id, populated at capture time
    so the burn-in pipeline can composite icons even after the original CDN URL
    would 403. The burn-in side reads the same ``<gift_id>.img`` files directly.

    Best-effort throughout: a failed download never blocks collection."""

    def __init__(self, cache_dir: Path) -> None:
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SECONDS, follow_redirects=True)
        self._locks: dict[int, asyncio.Lock] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def is_allowed(url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            return False
        host = (parts.hostname or "").lower()
        return any(host == suffix.lstrip(".") or host.endswith(suffix) for suffix in _ALLOWED_HOST_SUFFIXES)

    def path_for(self, gift_id: int) -> Path:
        return self._dir / f"{int(gift_id)}.img"

    def has(self, gift_id: int) -> bool:
        if not gift_id:
            return False
        path = self.path_for(gift_id)
        try:
            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    async def persist(self, gift_id: int, url: str) -> bool:
        """Download the icon once and store it as ``<gift_id>.img``. Returns True
        if the icon is on disk afterwards (already cached counts as success)."""
        if not gift_id or not url or not self.is_allowed(url):
            return False
        if self.has(gift_id):
            return True
        lock = self._locks.setdefault(int(gift_id), asyncio.Lock())
        async with lock:
            if self.has(gift_id):
                return True
            try:
                resp = await self._client.get(url, headers=_FETCH_HEADERS)
                resp.raise_for_status()
                content = resp.content
                if not content or len(content) > _MAX_BYTES:
                    logger.warning("gift icon size invalid (id=%s, %d bytes)", gift_id, len(content))
                    return False
                self.path_for(gift_id).write_bytes(content)
                return True
            except Exception:
                logger.warning("gift icon persist failed (id=%s): %s", gift_id, url, exc_info=True)
                return False

    async def persist_gift_list(self, gift_list: dict) -> int:
        """Pre-cache every icon in a fetched gift-list response (best-effort).
        Also records a gift-name -> gift-id index so the burn-in pipeline can
        recover an icon for legacy events that stored the gift name but no id,
        without a network round-trip. Returns the number newly persisted."""
        count = 0
        names: dict[str, int] = {}
        for gift in (gift_list.get("gifts") or []):
            gift_id = gift.get("id")
            name = gift.get("name") or ""
            url = ((gift.get("image") or {}).get("url_list") or [None])[0]
            if gift_id and name:
                names[name] = int(gift_id)
            if gift_id and url and not self.has(gift_id):
                if await self.persist(int(gift_id), url):
                    count += 1
        if names:
            self._merge_name_index(names)
        return count

    def _merge_name_index(self, mapping: dict) -> None:
        """Merge {gift_name: gift_id} into the on-disk names.json index."""
        path = self._dir / "names.json"
        try:
            existing = {}
            if path.is_file():
                existing = json.loads(path.read_text(encoding="utf-8"))
            existing.update(mapping)
            path.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")
        except (OSError, ValueError):
            logger.warning("gift name index write failed: %s", path, exc_info=True)
