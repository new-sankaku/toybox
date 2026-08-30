import asyncio
import logging
import time
from typing import NamedTuple, Optional

from TikTokLive.client.errors import UserNotFoundError

from tictok.core.config import (
    get_locale_lang_country,
    get_locale_tz,
    get_resolver_close_timeout_seconds,
    get_resolver_headless,
    get_resolver_restart_after_failures,
    get_resolver_restart_cooldown_seconds,
    get_resolver_timeout_ms,
)

logger = logging.getLogger("tictok.resolver")

LIVE_URL = "https://www.tiktok.com/@{unique_id}/live"

# 1回の解決に許す実時間の上限を、page操作のtimeoutの何倍に置くか。goto と SIGI_STATE
# 待ちがそれぞれ timeout を使い切りうるので2倍では足りず、new_page/evaluate/close の
# ぶんを足して3倍を上限にする。
RESOLVE_BUDGET_RATIO = 3

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
    the context's WAF token and cookies are reused across all monitors.

    The browser is supervised, not merely launched once. Chromium can crash and
    the playwright driver process can die (killed, out of memory, host sleep);
    after that every call raises the same error forever — "Connection closed
    while reading from the driver" — and live detection stops for every monitor
    until the server is restarted (実測 2026-08-26 12:55〜18:06、229件連続)。
    ``resolve`` therefore rebuilds the browser when it is disconnected or when
    browser-side calls keep failing."""

    def __init__(self, settings=None) -> None:
        self._settings = settings
        self._lock = asyncio.Lock()
        self._playwright = None
        self._browser = None
        self._context = None
        self._failures = 0
        self._last_launch_at = 0.0
        self._restarts = 0

    async def start(self) -> None:
        async with self._lock:
            await self._ensure_browser()

    async def _launch(self) -> None:
        """playwright・chromium・contextを起こす。lock保持が前提で、直前の一式は
        呼び元が落としてあること。"""
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "playwright が install されていません。`pip install playwright` 後に "
                "`playwright install chromium` を実行してください。"
            ) from exc
        # 起動を試みた時点を再起動のcooldownの起点にする。起動自体が失敗する状態
        # (chromium未install等)でも、probeごとに起動を繰り返さないため。
        self._last_launch_at = time.monotonic()
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
        self._failures = 0
        logger.info(
            "browserのlive resolverを開始しました（headless=%s）", get_resolver_headless(),
            extra={"event": "collector.resolver_started",
                   "ctx": {"headless": get_resolver_headless(),
                           "locale": get_locale_lang_country(),
                           "timezone": get_locale_tz(),
                           "timeout_ms": get_resolver_timeout_ms(),
                           "restarts": self._restarts}},
        )

    def _is_alive(self) -> bool:
        """contextが在り、browserとの接続が生きているか。driver processが死んだ場合は
        browser側へcloseが届かないので ``is_connected()`` はTrueのまま残る。その型は
        連続失敗のほうで捕まえる。"""
        if self._context is None or self._browser is None:
            return False
        try:
            return bool(self._browser.is_connected())
        except Exception:
            return False

    async def _ensure_browser(self) -> None:
        """健全なcontextを用意する。lock保持が前提。落ちている/失敗が続いている場合は
        cooldownを守って作り直す。"""
        threshold = get_resolver_restart_after_failures()
        if self._is_alive() and self._failures < threshold:
            return
        if self._context is None and self._last_launch_at == 0.0:
            await self._launch()
            return
        reason = "browser_disconnected" if not self._is_alive() else "consecutive_failures"
        cooldown = get_resolver_restart_cooldown_seconds()
        waited = time.monotonic() - self._last_launch_at
        if waited < cooldown:
            raise LiveResolveBlocked(
                f"resolver restart pending ({reason}, {cooldown - waited:.0f}s cooldown)"
            )
        logger.warning(
            "live resolverのbrowserを作り直します（理由=%s、連続失敗%d回）",
            reason, self._failures,
            extra={"event": "collector.resolver_restarting",
                   "ctx": {"reason": reason, "consecutive_failures": self._failures,
                           "restarts": self._restarts,
                           "seconds_since_launch": round(waited, 1)}},
        )
        await self._teardown()
        await self._launch()
        self._restarts += 1

    async def _teardown(self) -> None:
        """一式を閉じて参照を落とす。driverが応答しないときに停止処理そのものが止まらない
        よう、各段に待ち上限を掛ける。"""
        timeout = get_resolver_close_timeout_seconds()
        for closer, label in (
            (lambda: self._context and self._context.close(), "context"),
            (lambda: self._browser and self._browser.close(), "browser"),
            (lambda: self._playwright and self._playwright.stop(), "playwright"),
        ):
            try:
                result = closer()
                if result is not None:
                    await asyncio.wait_for(result, timeout=timeout)
            except Exception:
                # 閉じ残しはprocess終了で回収されるが、shutdownが遅い/chromiumが残る
                # 原因になるので無音にはしない。
                logger.warning(
                    "resolverの%sを閉じられませんでした。chromiumのprocessが残る可能性が"
                    "あります", label, exc_info=True,
                    extra={"event": "collector.resolver_close_failed",
                           "ctx": {"component": label}},
                )
        self._context = self._browser = self._playwright = None

    async def close(self) -> None:
        # 実行中のresolveと重ならないよう待つ。閉じた一式へ触るとresolve側が
        # driver切断と同じ例外を上げるため。待ち上限を置いて停止は必ず進める。
        acquired = False
        try:
            await asyncio.wait_for(
                self._lock.acquire(), timeout=get_resolver_close_timeout_seconds()
            )
            acquired = True
        except Exception:
            logger.warning(
                "resolverの実行中の解決を待てませんでした。閉じる処理を続けます",
                exc_info=True,
                extra={"event": "collector.resolver_close_not_idle", "ctx": {}},
            )
        try:
            await self._teardown()
            self._failures = 0
            self._last_launch_at = 0.0
        finally:
            if acquired:
                self._lock.release()
        logger.info(
            "browserのlive resolverを停止しました",
            extra={"event": "collector.resolver_stopped",
                   "ctx": {"restarts": self._restarts}},
        )

    async def _read_live_state(self, unique_id: str, timeout: int) -> dict:
        """live pageを1枚開いてSIGI_STATEの生payloadを読む。lock保持が前提。
        呼び元が全体に待ち上限を掛けるので、ここでcancelされうる。"""
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
                    "SIGI_STATEが%dms以内に付きませんでした（@%s）。pageが出している"
                    "内容だけを読みます", timeout, unique_id, exc_info=True,
                    extra={"event": "collector.resolver_sigi_timed_out",
                           "ctx": {"target_unique_id": unique_id, "timeout_ms": timeout}},
                )
            return await page.evaluate(_EXTRACT_JS)
        finally:
            try:
                await page.close()
            except Exception:
                # cancel中はここも即座に落ちる。閉じ残したpageは、応答しないbrowserごと
                # 次のprobeの作り直しで回収される。
                logger.debug(
                    "@%s のresolver pageを閉じられませんでした", unique_id, exc_info=True,
                    extra={"event": "collector.resolver_page_close_failed",
                           "ctx": {"target_unique_id": unique_id}},
                )

    async def resolve(self, unique_id: str) -> LiveResolution:
        """Resolve live state for a user. See :func:`interpret_live_state`.

        Returns a :class:`LiveResolution`: ``room_id`` classifies live/offline as
        before, and ``avatar``/``nickname``/``user_id`` carry the host profile
        lifted from the same page (available even while offline)."""
        timeout = get_resolver_timeout_ms()
        budget = timeout * RESOLVE_BUDGET_RATIO / 1000.0
        async with self._lock:
            await self._ensure_browser()
            if self._context is None:
                raise LiveResolveBlocked("resolver not started")
            try:
                data = await asyncio.wait_for(
                    self._read_live_state(unique_id, timeout), timeout=budget
                )
            except asyncio.TimeoutError as exc:
                # driverが応答しない型。playwrightのnew_page/evaluate/closeにはtimeoutが
                # 無く、ここで切らないとlockを握ったまま止まり、全監視のlive検出が1行の
                # logも残さずに停止する。
                self._failures += 1
                raise LiveResolveBlocked(
                    f"resolver unresponsive (no answer in {budget:.0f}s)"
                ) from exc
            except Exception as exc:
                self._failures += 1
                raise LiveResolveBlocked(f"navigation error: {exc}") from exc
            # pageを開いて読めた＝browserは健全。WAF未通過(dataの中身)はbrowserの
            # 健康状態ではないので、ここで数え直す。
            self._failures = 0
        room_id = interpret_live_state(data, unique_id)
        # probeごとの結果。全監視×poll間隔の最高頻度pathなので level guard で抑える。
        # DEBUG時は「いつ・どのroomが・どう見えたか」を1件ずつ辿れる。
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "@%s の配信状態を解決しました: room_id=%s", unique_id, room_id,
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
