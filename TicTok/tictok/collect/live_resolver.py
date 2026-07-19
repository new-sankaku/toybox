import asyncio
import logging
from typing import NamedTuple, Optional

from TikTokLive.client.errors import UserNotFoundError

from tictok.core.config import (
    get_locale_lang_country,
    get_locale_tz,
    get_resolver_headless,
    get_resolver_timeout_ms,
)

logger = logging.getLogger("tictok.resolver")

LIVE_URL = "https://www.tiktok.com/@{unique_id}/live"

# Read SIGI_STATE the same way TikTokLiveClient does, but from inside a real
# browser context that has already passed TikTok's SlardarWAF JS challenge.
# Plain HTTP clients (httpx / curl_cffi) receive a WAF stub page with no
# SIGI_STATE; a browser solves the challenge and renders the real page.
# We also lift the host's profile avatar/nickname from the same payload: it is
# present even while offline (status 4), so a monitored streamer's icon can be
# shown without waiting for their next broadcast.
_EXTRACT_JS = """() => {
  const html = document.documentElement.outerHTML;
  const waf = !!document.getElementById('wci') || html.includes('_wafchallengeid');
  const el = document.getElementById('SIGI_STATE');
  if (!el) return { sigi: false, waf };
  let state;
  try { state = JSON.parse(el.textContent); } catch (e) { return { sigi: false, waf }; }
  const liveRoom = state.LiveRoom;
  if (!liveRoom) return { sigi: true, waf, liveRoom: false };
  const user = (liveRoom.liveRoomUserInfo && liveRoom.liveRoomUserInfo.user) || {};
  const pick = (a) => {
    if (!a) return '';
    if (typeof a === 'string') return a;
    if (Array.isArray(a.urlList) && a.urlList.length) return a.urlList[a.urlList.length - 1];
    if (Array.isArray(a) && a.length) return a[a.length - 1];
    return '';
  };
  const avatar = pick(user.avatarLarger) || pick(user.avatarMedium) || pick(user.avatarThumb) || '';
  return {
    sigi: true, waf, liveRoom: true,
    roomId: user.roomId || null, status: user.status,
    avatar: avatar, nickname: user.nickname || '',
    userId: (user.id != null ? String(user.id) : '')
  };
}"""


class LiveResolution(NamedTuple):
    """resolve() の結果。``room_id`` は live 中のみ非 None(offline は None)。
    ``avatar``/``nickname``/``user_id`` は offline でも SIGI_STATE に含まれる
    host プロフィールで、配信を待たずにアイコン/表示名を表示するために使う。"""

    room_id: Optional[int]
    avatar: str = ""
    nickname: str = ""
    user_id: str = ""


class LiveResolveBlocked(Exception):
    """TikTok did not return parseable live state (WAF challenge unsolved, page
    timeout, or transient navigation error). Callers back off and retry."""


def interpret_live_state(data: dict, unique_id: str) -> Optional[int]:
    """Map the SIGI_STATE LiveRoom payload to a room id.

    :return: the room id when the user is live, ``None`` when offline.
    :raises UserNotFoundError: the user cannot go LIVE / never has / does not exist.
    :raises LiveResolveBlocked: SIGI_STATE was absent (WAF or transient).
    """
    if not data.get("sigi"):
        reason = "WAF challenge not solved" if data.get("waf") else "no SIGI_STATE in page"
        raise LiveResolveBlocked(reason)
    if not data.get("liveRoom"):
        raise UserNotFoundError(
            unique_id,
            "The requested user is not capable of going LIVE on TikTok, "
            "has never gone live on TikTok, or does not exist.",
        )
    if data.get("status") == 4:
        return None
    room_id = data.get("roomId")
    if not room_id:
        return None
    return int(room_id)


class BrowserLiveResolver:
    """Resolves TikTok LIVE status through a shared headless browser context so
    requests pass the SlardarWAF JS challenge that blocks plain HTTP clients.
    One browser is launched for the whole process; navigations are serialized so
    the context's WAF token and cookies are reused across all monitors."""

    def __init__(self, settings=None) -> None:
        self._settings = settings
        self._lock = asyncio.Lock()
        self._playwright = None
        self._browser = None
        self._context = None

    async def start(self) -> None:
        if self._context is not None:
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "playwright が install されていません。`pip install playwright` 後に "
                "`playwright install chromium` を実行してください。"
            ) from exc
        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch(
                headless=get_resolver_headless()
            )
        except Exception as exc:
            raise RuntimeError(
                "Chromium を起動できませんでした。`playwright install chromium` を実行してください。"
            ) from exc
        self._context = await self._browser.new_context(
            locale=get_locale_lang_country(),
            timezone_id=get_locale_tz(),
        )
        logger.info(
            "browser live resolver started (headless=%s)", get_resolver_headless(),
            extra={"event": "collector.resolver_started",
                   "ctx": {"headless": get_resolver_headless(),
                           "locale": get_locale_lang_country(),
                           "timezone": get_locale_tz(),
                           "timeout_ms": get_resolver_timeout_ms()}},
        )

    async def close(self) -> None:
        for closer, label in (
            (lambda: self._context and self._context.close(), "context"),
            (lambda: self._browser and self._browser.close(), "browser"),
            (lambda: self._playwright and self._playwright.stop(), "playwright"),
        ):
            try:
                result = closer()
                if result is not None:
                    await result
            except Exception:
                # 閉じ残しはprocess終了で回収されるが、shutdownが遅い/chromiumが残る
                # 原因になるので無音にはしない。
                logger.warning(
                    "failed to close the resolver's %s; a chromium process may be left "
                    "behind", label, exc_info=True,
                    extra={"event": "collector.resolver_close_failed",
                           "ctx": {"component": label}},
                )
        self._context = self._browser = self._playwright = None
        logger.info(
            "browser live resolver stopped",
            extra={"event": "collector.resolver_stopped", "ctx": {}},
        )

    async def resolve(self, unique_id: str) -> LiveResolution:
        """Resolve live state for a user. See :func:`interpret_live_state`.

        Returns a :class:`LiveResolution`: ``room_id`` classifies live/offline as
        before, and ``avatar``/``nickname``/``user_id`` carry the host profile
        lifted from the same page (available even while offline)."""
        if self._context is None:
            raise LiveResolveBlocked("resolver not started")
        timeout = get_resolver_timeout_ms()
        async with self._lock:
            page = await self._context.new_page()
            try:
                await page.goto(
                    LIVE_URL.format(unique_id=unique_id),
                    wait_until="domcontentloaded",
                    timeout=timeout,
                )
                try:
                    await page.wait_for_selector("#SIGI_STATE", state="attached", timeout=timeout)
                except Exception:
                    # No SIGI_STATE within the window: most often the WAF
                    # challenge has not resolved. Fall through to read whatever
                    # state the page exposes so interpret_live_state can classify.
                    logger.debug(
                        "SIGI_STATE did not attach within %dms for @%s; reading whatever "
                        "the page exposes", timeout, unique_id, exc_info=True,
                        extra={"event": "collector.resolver_sigi_timed_out",
                               "ctx": {"target_unique_id": unique_id, "timeout_ms": timeout}},
                    )
                data = await page.evaluate(_EXTRACT_JS)
            except UserNotFoundError:
                raise
            except LiveResolveBlocked:
                raise
            except Exception as exc:
                raise LiveResolveBlocked(f"navigation error: {exc}") from exc
            finally:
                try:
                    await page.close()
                except Exception:
                    logger.debug(
                        "resolver page close failed for @%s", unique_id, exc_info=True,
                        extra={"event": "collector.resolver_page_close_failed",
                               "ctx": {"target_unique_id": unique_id}},
                    )
        room_id = interpret_live_state(data, unique_id)
        # probeごとの結果。全監視×poll間隔の最高頻度pathなので level guard で抑える。
        # DEBUG時は「いつ・どのroomが・どう見えたか」を1件ずつ辿れる。
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "live state resolved for @%s: room_id=%s", unique_id, room_id,
                extra={"event": "collector.live_state_resolved",
                       "ctx": {"target_unique_id": unique_id, "room_id": room_id,
                               "status": data.get("status"),
                               "waf": bool(data.get("waf")),
                               "has_avatar": bool(data.get("avatar"))}},
            )
        return LiveResolution(
            room_id=room_id,
            avatar=str(data.get("avatar") or ""),
            nickname=str(data.get("nickname") or ""),
            user_id=str(data.get("userId") or ""),
        )
