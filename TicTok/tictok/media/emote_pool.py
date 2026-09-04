"""収集時にTikTok custom emote(sub/fansclub絵文字)画像をdiskへ永続cacheする。

commentのemoteはCDN URLで届き、そのURLは署名/地域hostのため後から403になり得る。
焼き込み(video_overlay._resolve_emotes)はemote_id単位で ``<emote_id>.img`` を読むので、
URLが新鮮なうち(収集時)に同じ名前で保存しておけばcache hitし、downloadは走らない。

GiftIconCache / AvatarPool と同じ持続化方針。Windows/Linux双方で動作する。

**命名の一致**: 保存名は ``<emote_id>.img`` で、焼き込み側 ``_resolve_emotes`` の
``cache_dir / f"{eid}.img"`` と一字一句同じでなければcacheは無視される(``emote_id`` は
どちらも同じ ``events.emotes`` JSONの ``id`` 文字列)。置き場も同じ
``layout.emote_pool_dir()``。emote_idは外部由来の文字列なので、path区切りや ``..`` を
含むものは保存せずに弾く(pool外への書き出しを防ぐ)。弾く条件を「安全な文字だけ」に
限っているので、保存される限り名前は焼き込み側の式と常に一致する。
"""

import asyncio
import logging
import re
from pathlib import Path
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger("tictok.emote_pool")

# TikTok / ByteDance CDN host suffixes that serve emote images. Restrict fetches to
# these so a malicious URL cannot turn this into an SSRF vector.
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

# emote_id は実測で数字列だが、外部由来なので保存前に検証する。ここを通った文字列だけを
# file名にするので、path traversalも、焼き込み側の式との食い違いも起こらない。
_EMOTE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# 焼き込み側(video_overlay._resolve_emotes)が読むfile名の拡張子。
EMOTE_FILE_SUFFIX = ".img"


def is_valid_emote_id(emote_id: str) -> bool:
    """その emote_id を file名として使ってよいか。"""
    return bool(emote_id) and _EMOTE_ID_RE.match(emote_id) is not None


class EmotePool:
    """Durable on-disk custom-emote store keyed by emote_id, populated at capture time
    so the burn-in pipeline can draw the emote inline even after the original CDN URL
    would 403. The burn-in side reads the same ``<emote_id>.img`` files directly.

    Best-effort throughout: a failed download never blocks collection."""

    def __init__(self, cache_dir: Path) -> None:
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SECONDS, follow_redirects=True)
        self._locks: dict[str, asyncio.Lock] = {}
        # 報告済みの永久失敗(id書式 / 許可外host)。同じ原因の再報告を止めるためだけに持つ。
        self._reported: set = set()

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def is_allowed(url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            return False
        host = (parts.hostname or "").lower()
        return any(host == suffix.lstrip(".") or host.endswith(suffix) for suffix in _ALLOWED_HOST_SUFFIXES)

    def path_for(self, emote_id: str) -> Path:
        """焼き込みが読むのと同じpath。``is_valid_emote_id`` を満たすidにのみ使う。"""
        return self._dir / f"{emote_id}{EMOTE_FILE_SUFFIX}"

    def has(self, emote_id: str) -> bool:
        if not is_valid_emote_id(emote_id):
            return False
        path = self.path_for(emote_id)
        try:
            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    def should_fetch(self, emote_id: str, url: str) -> bool:
        """その (emote_id, url) を取りに行く価値があるか。

        既に在るもの、file名に使えないid、許可外hostのURLをここで落とす。後ろの2つは
        再試行しても永久に変わらない上、その絵文字が焼き込みから失われることを意味する
        ので、無言で捨てずに1度だけ報告する(``is_fetchable``)。在るかの判定はstat 1回。"""
        return self.is_fetchable(emote_id, url) and not self.has(emote_id)

    def is_fetchable(self, emote_id: str, url: str) -> bool:
        """idとURLが取得に使える形か。diskは見ない — 投入側(event loop上)がここまでを
        見て、cacheの有無はworkerがthreadで確かめる。"""
        if not emote_id or not url:
            return False
        if not is_valid_emote_id(emote_id):
            self._report_permanent(
                "emote_id", emote_id,
                "emote idがfile名に使えないため取得しません（id=%r）。"
                "焼き込みではこの絵文字が透明な余白になります",
                emote_id, reason="invalid_id",
                ctx={"emote_id": str(emote_id)[:64]},
            )
            return False
        if not self.is_allowed(url):
            host = urlsplit(url).hostname or ""
            self._report_permanent(
                "host", host,
                "emoteのCDN host %s は許可listに無いため取得しません。"
                "焼き込みではこの絵文字が透明な余白になります",
                host, reason="host_not_allowed",
                ctx={"emote_id": emote_id, "host": host},
            )
            return False
        return True

    def _report_permanent(self, scope: str, key: str, message: str, *args,
                          reason: str, ctx: dict) -> None:
        """永久に取れないemoteを、同じ原因につき1度だけ報告する。原因はid書式かhostなので
        件数ぶん出すと、1配信ぶんのlogがそれで埋まる(同じ絵文字が何度も流れる)。"""
        if (scope, key) in self._reported:
            return
        self._reported.add((scope, key))
        logger.warning(
            message, *args,
            extra={"event": "collector.emote_persist_failed",
                   "ctx": {**ctx, "reason": reason}},
        )

    async def persist(self, emote_id: str, url: str) -> bool:
        """Download the emote image once and store it as ``<emote_id>.img``. Returns
        True if the image is on disk afterwards (already cached counts as success)."""
        if not self.should_fetch(emote_id, url):
            return self.has(emote_id)
        lock = self._locks.setdefault(emote_id, asyncio.Lock())
        async with lock:
            if self.has(emote_id):
                return True
            try:
                resp = await self._client.get(url, headers=_FETCH_HEADERS)
                resp.raise_for_status()
                content = resp.content
                if not content or len(content) > _MAX_BYTES:
                    logger.error(
                        "%s のemote responseが使用できないため（%d bytes）"
                        "焼き込みでこの絵文字が失われます", emote_id, len(content),
                        extra={"event": "collector.emote_persist_failed",
                               "ctx": {"emote_id": emote_id, "reason": "invalid_size",
                                       "size_bytes": len(content), "max_bytes": _MAX_BYTES}},
                    )
                    return False
                self.path_for(emote_id).write_bytes(content)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "emote %s を保存しました（%d bytes）", emote_id, len(content),
                        extra={"event": "collector.emote_persisted",
                               "ctx": {"emote_id": emote_id, "size_bytes": len(content)}},
                    )
                return True
            except Exception:
                # 署名付きURLは配信中しか有効ではないので、ここで取れなければ焼き込みは
                # この絵文字を永久に描けない(sentinelが透明な余白になる)。
                logger.warning(
                    "emoteの保存に失敗しました（id=%s）: %s", emote_id, url,
                    extra={"event": "collector.emote_persist_failed",
                           "ctx": {"emote_id": emote_id, "reason": "unexpected"}},
                    exc_info=True,
                )
                return False
