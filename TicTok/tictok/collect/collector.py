import asyncio
import json
import logging
import random
import re
import time

import betterproto
import httpx
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Optional

from websockets.exceptions import ConnectionClosed

from TikTokLive import TikTokLiveClient
from TikTokLive.client.errors import (
    AgeRestrictedError,
    TikTokLiveError,
    UserNotFoundError,
    UserOfflineError,
)
from TikTokLive.events import (
    BoostCardEvent,
    CommentEvent,
    ConnectEvent,
    DisconnectEvent,
    EnvelopeEvent,
    EnvelopePortalEvent,
    FollowEvent,
    GiftEvent,
    GoodyBagEvent,
    HotRoomEvent,
    JoinEvent,
    LikeEvent,
    LinkLayerEvent,
    LinkLayoutEvent,
    LinkMicArmiesEvent,
    LinkMicBattleEvent,
    LinkMicBattleItemCardEvent,
    LinkMicBattlePunishFinishEvent,
    LinkMicBattleVictoryLapEvent,
    LinkMicMethodEvent,
    LinkmicBattleNoticeEvent,
    LinkmicBattleTaskEvent,
    LinkStateEvent,
    HourlyRankRewardEvent,
    LiveEndEvent,
    PortalEvent,
    RankUpdateEvent,
    RankTextEvent,
    RankToastEvent,
    RoomUserSeqEvent,
    ShareEvent,
    SpecialPushEvent,
    SubscribeEvent,
    UnknownEvent,
    WeeklyRankRewardEvent,
)

from TikTokLive.client.web.web_settings import WebDefaults

from tictok.core.config import (
    get_locale_country,
    get_locale_lang,
    get_locale_lang_country,
    get_locale_tz,
    get_log_battle_raw_gzip,
    get_log_dir,
    get_log_live_wait_interval_seconds,
    get_log_restriction_text_chars,
    get_log_stream_url_expiry_warn_seconds,
    get_sample_dir,
    get_sign_api_key,
    get_simulation,
    get_timeline_limit,
)
from tictok.core.battle import (
    BATTLE_TOPOLOGY_VERSION,
    GLOVE_EVENT_VERSION,
    annotate_result,
    battle_type,
)
from tictok.core.logctx import (
    ctx_recording_id,
    ctx_session_id,
    ctx_unique_id,
    log_context,
)
from tictok.core.logging_setup import compress_async, progress_interval_seconds
from tictok.collect.live_resolver import LiveResolveBlocked
from tictok.collect.proto_dict import safe_event_to_dict
from tictok.collect.sampler import EventSampler
from tictok.record.recorder import Recorder, extract_stream_url, ffmpeg_available
from tictok.storage import OPS_ERROR, OPS_INFO, OPS_WARNING, _identity_key

logger = logging.getLogger("tictok.collector")

# WebcastLinkMicBattleBattleAction (tiktok_proto). A PK that ends via CANCEL /
# REJECT / CUT_SHORT never produced a real contest (matchmaking aborted or the
# host bailed within seconds), so it is excluded from the battle count and list.
BATTLE_ACTION_REJECT = 2
BATTLE_ACTION_CANCEL = 3
BATTLE_ACTION_OPEN = 4
BATTLE_ACTION_FINISH = 5
BATTLE_ACTION_CUT_SHORT = 6
_ABORTED_BATTLE_ACTIONS = {BATTLE_ACTION_REJECT, BATTLE_ACTION_CANCEL, BATTLE_ACTION_CUT_SHORT}

# グローブ(Critical Strike card)のcrit判定は、armies eventごとの自hostスコアの増分(delta)と
# ギフト額の厳密一致で行う。実dump実測(17 battle)で score寄与は 通常=倍率タイムm×単価 /
# crit=窓倍率M×単価(倍率タイムと重畳しない) が全件厳密一致。user_armiesは上位3名しか載らず
# 送信者突合は原理的に不可能なため使わない。一意に一致しないgiftは判定不能(crit=None)とし推測しない。
GLOVE_MULTIPLE = 5
# gift送信時刻(server epoch秒)に対し、そのscore deltaの観測を許容する時間窓。armiesは
# gift後1〜3秒で届くのが実測typical。窓外のdeltaは別giftのものとして突合しない。
GLOVE_MATCH_BEFORE_SEC = 2.0
GLOVE_MATCH_AFTER_SEC = 8.0
# armies payload直下の gift_id / gift_sent_time / from_user_id は「そのscore更新がどのgiftに
# よるものか」を名指しするため、額の一致に頼らずdeltaをgiftへ同定できる(user_armiesが上位3名
# しか載らないのはuser_armiesの制約であって、これらのfieldには当てはまらない)。実測では
# 窓中giftの45%にこの同定が効き、額一致では解けない合算・両成立を確定できる。
GLOVE_ATTR_MATCH_SEC = 3.0
# 判定根拠。強い順に flag(TikTokがcritを明示) > attr(gift同定) > delta(額の厳密一致)。
GLOVE_METHOD_FLAG = "flag"
GLOVE_METHOD_ATTR = "attr"
GLOVE_METHOD_DELTA = "delta"


def _enum_value(value: Any) -> Optional[int]:
    """betterproto enum fields are IntEnum members; return the underlying int so
    actions can be compared against the protocol constants regardless of whether
    the field arrived as an enum member, a plain int, or None."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    """protoのint fieldを素直にintへ。Noneや数値化できない値はNoneを返し、0で埋めない
    (proto3のscalarはpresenceを持たないため、0で届いたものはそのまま0として残す)。"""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> Optional[str]:
    """protoのid系fieldを文字列へ。空文字とNoneはNoneに寄せる。

    idはint64で届くこともstrで届くこともあり(実測: envelope_idはstr、portal_info.idもstr、
    一方でuser idはint)、桁の大きいintをそのままJSONへ載せるとJS側で精度が落ちる。
    文字列に寄せておけば比較も保存も一意に決まる。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _apply_locale() -> None:
    lang = get_locale_lang()
    country = get_locale_country()
    lang_country = get_locale_lang_country()
    tz = get_locale_tz()
    WebDefaults.web_client_params.update(
        {
            "app_language": lang,
            "webcast_language": lang,
            "browser_language": lang_country,
            "priority_region": country,
            "region": country,
            "tz_name": tz,
        }
    )
    WebDefaults.ws_client_params.update(
        {
            "app_language": lang,
            "webcast_language": lang,
            "browser_language": lang_country,
            "tz_name": tz,
        }
    )
    WebDefaults.web_client_headers["Accept-Language"] = f"{lang_country},{lang};q=0.9"
    logger.info(
        "TikTok client locale applied: lang=%s region=%s", lang, country,
        extra={"event": "collector.locale_applied",
               "ctx": {"lang": lang, "country": country,
                       "lang_country": lang_country, "tz": tz}},
    )


def _apply_sign_api_key() -> None:
    """Send the EulerStream API key as X-Api-Key on sign requests, lifting the
    anonymous-tier rate limit. The key is a secret, so only its presence is
    logged, never its value."""
    api_key = get_sign_api_key()
    if api_key:
        WebDefaults.tiktok_sign_api_key = api_key
    logger.info(
        "sign api key %s; sign requests run on the %s tier",
        "configured" if api_key else "absent",
        "keyed" if api_key else "anonymous",
        extra={"event": "collector.sign_key_configured",
               "ctx": {"configured": bool(api_key)}},
    )


_apply_locale()
_apply_sign_api_key()

# league_probe診断: field名がこれらを含めばリーグ/ランク関連の可能性が高い(snake/camel両対応)。
_LEAGUE_KEY_RE = re.compile(r"league|ranking|grade", re.IGNORECASE)
# 'A1' 'B1' 'S1' 'C10' のようなリーグ帯ラベルの形。key名に依らず値側からも拾うための後段signal。
_LEAGUE_VALUE_RE = re.compile(r"^[A-Za-z]\d{1,2}$")


def _extract_league(gift_list: Any) -> str:
    """gift list(/gift/list/の生JSON=dict)から配信者リーグ帯を取り出す。実データ確認により
    gifts_info.gift_gallery_info.anchor_ranking_league がリーグ帯(A1/B3等)を持つと判明。
    取れなければ ''(捏造しない)。"""
    if not isinstance(gift_list, dict):
        return ""
    gallery = (
        (gift_list.get("gifts_info") or {}).get("gift_gallery_info") or {}
    )
    return str(gallery.get("anchor_ranking_league") or "").strip()


# ---- stream URL diagnostics (empty-recording root cause) ----
# An empty recording is almost always a TikTok pull URL that had already expired when
# ffmpeg first read it. The expiry is carried in the URL's own query string, so the URL
# has to reach the log to make that determination possible — but it also carries the
# credentials that authorise the pull. Query keys matching _URL_SECRET_KEY_RE are
# therefore masked while the expiry keys are kept verbatim: dropping the whole query
# (the obvious "safe" choice) is what makes an expired-URL incident indistinguishable
# from a dead-CDN one in the log.
_URL_SECRET_KEY_RE = re.compile(
    r"sign|signature|token|secret|auth|cred|policy|session|key|uid|passwd|password",
    re.IGNORECASE,
)
# Query keys carrying the absolute moment the URL stops working. TikTok is not
# consistent about which one it uses across pull-flv / pull-hls / CDN vendors.
_URL_EXPIRY_KEYS = ("expire", "expires", "expiry", "expired_time", "valid_until", "oe")
# Below this the value cannot be an epoch stamp (it would be 1970) and above it the
# value cannot be seconds (it is a millisecond stamp). Used to pick the unit without
# guessing, the same magnitude test _create_time_sec uses for event timestamps.
_EPOCH_SECONDS_MIN = 1_000_000_000
_EPOCH_SECONDS_MAX = 100_000_000_000


def _mask_url(url: str) -> str:
    """URL with credential-bearing query values replaced by '***', keeping the path
    and every non-secret parameter (notably the expiry) readable. Returns '' for an
    empty URL so callers never log the string 'None'."""
    if not url:
        return ""
    base, sep, query = url.partition("?")
    if not sep:
        return base
    parts = []
    for item in query.split("&"):
        key, eq, value = item.partition("=")
        if eq and value and _URL_SECRET_KEY_RE.search(key):
            parts.append(f"{key}=***")
        else:
            parts.append(item)
    return base + "?" + "&".join(parts)


def _url_expiry(url: str) -> Optional[float]:
    """Absolute expiry of a signed URL as an epoch second, or None when the URL
    carries no recognisable expiry. None means "unknown", never "does not expire":
    callers must not treat it as a healthy URL."""
    if not url or "?" not in url:
        return None
    query = url.partition("?")[2]
    for item in query.split("&"):
        key, eq, value = item.partition("=")
        if not eq or key.strip().lower() not in _URL_EXPIRY_KEYS:
            continue
        try:
            raw = int(value)
        except (TypeError, ValueError):
            continue
        if _EPOCH_SECONDS_MIN <= raw < _EPOCH_SECONDS_MAX:
            return float(raw)
        if _EPOCH_SECONDS_MAX <= raw < _EPOCH_SECONDS_MAX * 1000:
            return raw / 1000.0
    return None


def _stream_url_ctx(url: str) -> dict:
    """Log ctx describing a pull URL: masked URL plus, when the URL states one, the
    expiry moment and how long it has left. This is the pair that lets an empty
    recording be attributed to (or cleared of) an expired URL from the log alone."""
    ctx: dict = {"stream_url": _mask_url(url)}
    expires_at = _url_expiry(url)
    if expires_at is not None:
        ctx["url_expires_at"] = round(expires_at, 3)
        ctx["seconds_to_expiry"] = round(expires_at - time.time(), 1)
    return ctx


Broadcast = Callable[[dict], Awaitable[None]]

STATE_IDLE = "idle"
STATE_WAITING = "waiting"
STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"
STATE_RECONNECTING = "reconnecting"
STATE_DISCONNECTED = "disconnected"
STATE_ENDED = "ended"
STATE_ERROR = "error"
# Non-terminal "recording impossible" status (members-only / age-restricted). The
# monitor keeps polling for a normal broadcast instead of failing, so a later
# unrestricted live on a new room id is still detected and recorded.
STATE_RESTRICTED = "restricted"

ACTIVE_STATES = (STATE_WAITING, STATE_CONNECTING, STATE_CONNECTED, STATE_RECONNECTING, STATE_RESTRICTED)

# live checkを撃ち続けている状態。ProbeGateの間隔はこの母数で割る: 接続中のcollectorは
# probeを消費しないので、全collector数で割ると「まだ配信していない人の検出」だけが監視数に
# 比例して遅くなる(20監視中15人が接続中でも残り5人が20人分に薄めた間隔で待たされる)。
PROBING_STATES = (STATE_WAITING, STATE_RESTRICTED)

# 制限holdの再確認を基準間隔のまま繰り返す回数。一時的な制限応答は数分で解けることが
# 多く序盤は密に見たいが、本当のメンバー限定/年齢制限はその放送が終わるまで解けないので、
# この回数を過ぎたら上限まで倍々に広げて無駄アクセスを抑える。
_RESTRICTED_FAST_RECHECKS = 3
# backoffの指数の打ち止め。基準間隔60秒でも2^12=4096倍あれば設定可能な上限(7200秒)を
# 必ず超えるため、これ以上は段数を伸ばしても結果が変わらない。
_RESTRICTED_MAX_BACKOFF_STEPS = 12

# Grace period before resuming a recording that ended on its own while the live
# is still connected. Lets a concurrent websocket drop surface first, so a full
# host drop is handled once by the reconnect path rather than by a doomed resume.
RESUME_SETTLE_DELAY = 3

# Recording recovery backoff (seconds). When a recording finalizes having captured
# nothing (its video pull URL was dead at start or a host re-broadcast reissued the
# URL) while the event websocket keeps flowing, the collector re-resolves a fresh
# stream URL and relaunches — see _maybe_resume_after_finalize. Re-resolution uses
# web.fetch_room_info (sign_url=False), so no sign request is spent and recovery can
# follow the host for as long as they stay live. The backoff throttles only the
# fast-fail cases (room_info fetch failed / no stream URL yet); a relaunch that
# actually runs ffmpeg is self-throttled by the recorder's own launch attempts.
RECORDING_RECOVERY_BACKOFF_MIN = 3
RECORDING_RECOVERY_BACKOFF_MAX = 30

# Battle/Collab窓を進行中sessionのうちに中間永続化する最短間隔(秒)。Battle終了・Collab終了の
# 契機でも都度保存するが、それらの契機が来ない進行中窓(クラッシュ直前の未終了PK等)を守るため
# 接続監視ループから定期的にもcheckpointする。save_*はDELETE→INSERT全置換で冪等。
_PROGRESS_CHECKPOINT_INTERVAL_SECONDS = 30.0
# 入室ドライバ(portal/宝箱)mask markerの集約不応期。1演出中の複数message(invite/ping/
# finish/grab)を1 onsetへ寄せ、mask marker dequeの消費と過剰mask抑制を両立する。
_DRIVER_MARKER_REFRACTORY_SECONDS = 60.0
# markerを保持するdequeの上限。kind別に分けているのは、溢れ得るのを捨ててよいmask marker
# (portal/宝箱)だけに限定するため。接続系とBattle/Collabは欠けると欠測秒数・Battle回数を
# 復元できなくなるので、実運用の発生量から充分に離れた上限を置く(実測の最大は1sessionあたり
# 全kind合計132件)。運用で調整する値ではなく保持ruleそのものなのでSETTING_DEFSには出さない。
_MASK_MARKER_CAP = 500
_CONN_MARKER_CAP = 2000
_LINKMIC_MARKER_CAP = 2000

# Live-check polling. TikTok rate-limits unauthenticated requests per IP via its
# WAF; many monitors at a short interval (rate = accounts x 60/interval) trip it
# and block the whole IP. Jitter de-synchronizes concurrent monitors so they
# don't burst together, and backoff lengthens the interval while blocked instead
# of hammering at the fixed rate (which only prolongs the block).
LIVE_CHECK_JITTER_RATIO = 0.2
LIVE_CHECK_BACKOFF_MAX_MULTIPLIER = 8
# Safety floor for the spacing between consecutive live-check probes. interval /
# monitor_count can fall below a second when many monitors share a short
# interval; sub-second spacing re-introduces the micro-bursts the gate exists to
# prevent, so probe starts are never spaced closer than this.
LIVE_CHECK_MIN_PROBE_SPACING = 1.0

# Reconnect burns one EulerStream sign request per attempt, and a broadcast that
# ended mid-reconnect can never be signed again (the sign server returns 502/500
# for a dead room), so every remaining attempt is a guaranteed miss. Re-resolving
# live state costs no sign request, so the reconnect loop spends one free probe
# periodically to detect that case and return to the watch loop early. The first
# attempts skip the probe because a genuinely transient sign 500 clears within
# seconds and must not pay for a browser navigation.
RECONNECT_LIVE_RECHECK_AFTER = 3
RECONNECT_LIVE_RECHECK_EVERY = 5

STEP_IDS = ["request", "live_check", "websocket", "receiving"]


class ProbeGate:
    """Serializes every TikTok live-check HTTP probe across all collectors so
    concurrent monitors never fire simultaneously. A startup burst (all monitors
    probing at once) trips TikTok's per-IP WAF, which then returns a stub page
    with no SIGI_STATE for several minutes; jitter/backoff on individual monitors
    cannot prevent that because the very first probe of each monitor has nothing
    to back off from. The gate spaces probe starts at least
    ``live_check_interval / monitor_count`` apart (with jitter), so the aggregate
    probe rate matches the configured per-monitor cadence but is spread evenly
    instead of bursting.

    Even spacing stops bursts but not sustained-rate blocking: an unauthenticated
    IP that polls the live page continuously gets blocked once its aggregate
    request volume crosses TikTok's threshold, no matter how evenly the requests
    are spread. ``interval / monitor_count`` keeps the per-monitor cadence but
    makes the aggregate rate grow linearly with the monitor count, so the gate
    also caps the aggregate at ``live_check_max_per_min`` requests per minute
    (slowing individual detection when many monitors share the cap, in exchange
    for keeping the IP alive)."""

    def __init__(self, settings, count_provider: Callable[[], int]) -> None:
        self._settings = settings
        self._count_provider = count_provider
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0
        self._last_probe = 0.0

    def _spacing(self) -> float:
        interval = self._settings.get("live_check_interval")
        count = max(1, self._count_provider())
        max_per_min = self._settings.get("live_check_max_per_min")
        cap_spacing = 60.0 / max_per_min
        return max(LIVE_CHECK_MIN_PROBE_SPACING, cap_spacing, interval / count)

    async def acquire(self, priority: bool = False) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if priority:
                # 起動時の初回probe / 監視追加時の初回probe。WAF対策の間隔(interval や
                # 回数上限)は適用せず、同時発火だけを防ぐ最小間隔で順次に即時実行する。
                # 一度に多数を復元しても1秒刻みで素早く全監視のLIVE状態を検出できる。
                wait = (self._last_probe + LIVE_CHECK_MIN_PROBE_SPACING) - now
                if wait > 0:
                    await asyncio.sleep(wait)
                    now = loop.time()
                self._last_probe = now
                # 直後の定期probeが重ならないよう、次回許可時刻は最小間隔ぶんだけ進める。
                self._next_allowed = max(self._next_allowed, now + LIVE_CHECK_MIN_PROBE_SPACING)
                return
            wait = self._next_allowed - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = loop.time()
            jitter = 1.0 + random.uniform(-LIVE_CHECK_JITTER_RATIO, LIVE_CHECK_JITTER_RATIO)
            self._next_allowed = now + self._spacing() * jitter
            self._last_probe = now

class OpponentRoomListener:
    """PK中に相手host1人のRoomへ接続し、そのRoomのGift(相手陣の実弾/コイン)を拾う。
    相手RoomのGiftは監視配信者自身のwebsocketには流れてこないため、これが唯一の取得源。
    GiftEventのみを購読し、録画・Session・stats更新は行わない軽量listener。

    取得したコインは on_gift コールバックで主Collectorへ渡し、Battle記録の相手陣貢献
    (host_idで配信者別)へ数値IDで突合・加算される。Battle終了/Session終了でstopする。"""

    def __init__(self, handle, host_id, battle_id, resolver, probe_gate, on_gift):
        self._handle = handle
        self.host_id = str(host_id)
        self._battle_id = battle_id
        self._resolver = resolver
        self._probe_gate = probe_gate
        self._on_gift = on_gift
        self._client: Optional[TikTokLiveClient] = None
        self._task: Optional[asyncio.Task] = None
        self._stopped = False

    async def start(self) -> None:
        self._task = asyncio.create_task(
            self._run(), name=f"tictok-opp-{self._handle}-{self._battle_id}"
        )

    async def _run(self) -> None:
        try:
            # 相手Roomの解決もProbeGate経由(優先=即時)。PKは数分なので即時性を優先する。
            await self._probe_gate.acquire(priority=True)
            if self._stopped:
                return
            room_id = (await self._resolver.resolve(self._handle)).room_id
            if not room_id or self._stopped:
                return
            client = TikTokLiveClient(unique_id=self._handle)
            client.add_listener(GiftEvent, self._handle_gift)
            self._client = client
            await client.connect(room_id=int(room_id), fetch_live_check=False, fetch_room_info=False)
        except asyncio.CancelledError:
            raise
        except Exception:
            # 相手陣の実弾が欠けるだけで主Collectorの収集は継続する(劣化)。Battle終了まで
            # 再試行はしないので、どのPKで欠けたかを battle_id 付きで残す。
            logger.warning(
                "opponent room listener failed for @%s; opponent gift totals will be "
                "incomplete for this battle", self._handle, exc_info=True,
                extra={"event": "collector.opponent_listener_failed",
                       "ctx": {"opp_unique_id": self._handle,
                               "opp_host_id": self.host_id,
                               "battle_id": self._battle_id}},
            )

    async def _handle_gift(self, event: "GiftEvent") -> None:
        if self._stopped or getattr(event, "streaking", False):
            return
        count = max(getattr(event, "repeat_count", 1) or 1, 1)
        coins = (getattr(event.gift, "diamond_count", 0) or 0) * count
        if coins <= 0:
            return
        await self._on_gift(self._battle_id, self.host_id, _user_payload(event.user), coins)

    async def stop(self) -> None:
        self._stopped = True
        client = self._client
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                # 切断は後続のtask cancelでも成立するため実害は無い。ただし無音にすると
                # 「相手Roomのsocketが残っていないか」を後から確認できないのでDEBUGで残す。
                logger.debug(
                    "opponent room disconnect failed for @%s; falling through to cancel",
                    self._handle, exc_info=True,
                    extra={"event": "collector.opponent_listener_disconnect_failed",
                           "ctx": {"opp_unique_id": self._handle,
                                   "battle_id": self._battle_id}},
                )
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug(
                    "opponent room listener task raised while stopping for @%s",
                    self._handle, exc_info=True,
                    extra={"event": "collector.opponent_listener_stop_failed",
                           "ctx": {"opp_unique_id": self._handle,
                                   "battle_id": self._battle_id}},
                )


STEP_LABELS = {
    "request": "Request受付",
    "live_check": "LIVE状態確認",
    "websocket": "WebSocket接続",
    "receiving": "Data受信中",
}


def _empty_stats() -> dict:
    return {
        "viewers": 0,
        # viewersは毎update上書き(=最終値)なので、最大同接は別に保持する。
        "viewers_peak": 0,
        "total_viewers": 0,
        "anonymous": 0,
        "likes_total": 0,
        "comments": 0,
        "gifts": 0,
        "diamonds": 0,
        "follows": 0,
        "shares": 0,
        "joins": 0,
        "subscribes": 0,
        "battles": 0,
        "battle_points": 0,
        "events_total": 0,
        "connected_at": None,
        "rate_gifts": 0,
        "rate_diamonds": 0,
        "rate_comments": 0,
        "rate_likes": 0,
    }


def _empty_bucket(start: int, viewers: int) -> dict:
    return {
        "start": start,
        "gifts": 0,
        "diamonds": 0,
        "comments": 0,
        "likes": 0,
        "joins": 0,
        "follows": 0,
        "shares": 0,
        "viewers": viewers,
    }


def _image_url(image: Any) -> str:
    """Extract a CDN URL from a TikTokLive ImageModel (protobuf with ``m_urls``)
    or a REST room_info image dict (``url_list``). Returns '' when absent; the UI
    falls back to an initial avatar rather than a placeholder image."""
    if image is None:
        return ""
    if isinstance(image, dict):
        for key in ("url_list", "m_urls", "urls"):
            urls = image.get(key)
            if urls:
                return urls[0]
        return ""
    urls = getattr(image, "m_urls", None) or getattr(image, "url_list", None)
    if urls:
        return urls[0]
    return ""


def _emote_payload(event: Any) -> Optional[str]:
    """JSON list of the TikTok custom emotes carried by a comment, or None. Each entry
    is ``{index, id, url}``: the insertion position in the comment, the stable emote_id
    (used as the burn-in image cache key), and a CDN image URL. TikTok delivers chat
    sub/fansclub emotes out-of-band in ``f315_emotes`` — the comment text only holds a
    ``[shortcode]`` (or nothing) — so without this the burn-in can only show that raw
    text. The first entry's ``index`` is unset in the protobuf (defaults to 0)."""
    raw = getattr(event, "f315_emotes", None)
    if not raw:
        return None
    out = []
    for e in raw:
        model = getattr(e, "emote_model", None)
        if model is None:
            continue
        url = _image_url(getattr(model, "image", None))
        if not url:
            continue
        out.append({
            "index": getattr(e, "index", 0) or 0,
            "id": str(getattr(model, "emote_id", "") or ""),
            "url": url,
        })
    return json.dumps(out, ensure_ascii=False) if out else None


def _best_owner_image(owner: Any) -> str:
    """Highest-resolution avatar URL from a REST room_info owner dict, preferring
    ``avatar_larger`` then ``avatar_medium`` then ``avatar_thumb``. Unlike comment/gift
    event users (72x72 thumb only), the streamer's room_info carries larger renditions,
    so picking the thumb would needlessly burn in a low-resolution owner avatar. Mirrors
    the resolver's avatarLarger→Medium→Thumb order (live_resolver.py)."""
    if not isinstance(owner, dict):
        return ""
    for key in ("avatar_larger", "avatar_medium", "avatar_thumb"):
        url = _image_url(owner.get(key))
        if url:
            return url
    return ""


# BadgeStruct.badge_scene (tiktok_proto BadgeSceneType): 名前横のバッジ種別。
# USER_GRADE=ギフターレベル(課金グレード)、FANS=ファンクラブ(メンバー)バッジ。
BADGE_SCENE_USER_GRADE = 8
BADGE_SCENE_FANS = 10


def _badge_image(badge: Any) -> str:
    """BadgeStruct から表示用の画像URLを取り出す。grade/fans badgeは image_badge か
    combine_badge_struct(icon/背景画像)のいずれかに画像を持つ。無ければ ''。"""
    if badge is None:
        return ""
    ib = getattr(badge, "image_badge", None)
    if ib is not None:
        url = _image_url(getattr(ib, "image_model", None))
        if url:
            return url
    cb = getattr(badge, "combine_badge_struct", None)
    if cb is not None:
        url = _image_url(getattr(cb, "icon", None))
        if url:
            return url
        bg = getattr(cb, "background", None)
        if bg is not None:
            url = _image_url(getattr(bg, "image", None))
            if url:
                return url
    return ""


def _badge_image_by_scene(user: Any, scene: int) -> str:
    for badge in getattr(user, "badge_list", None) or []:
        if _enum_value(getattr(badge, "badge_scene", None)) == scene:
            url = _badge_image(badge)
            if url:
                return url
    return ""


def _badge_by_scene(user: Any, scene: int) -> Any:
    for badge in getattr(user, "badge_list", None) or []:
        if _enum_value(getattr(badge, "badge_scene", None)) == scene:
            return badge
    return None


def _badge_text_candidates(bt: Any) -> list:
    """BadgeText(pieces + default_pattern)から文字列候補を集める。piecesが実値のため優先。"""
    if bt is None:
        return []
    out = []
    pieces = getattr(bt, "pieces", None)
    if pieces:
        out.extend(str(p) for p in pieces if p)
    dp = getattr(bt, "default_pattern", None)
    if dp:
        out.append(dp)
    return out


def _badge_level(badge: Any) -> int:
    """バッジのレベル数値を取り出す。実配信で確認した最も確実な源は `log_extra.level`
    (USER_GRADE=ギフターLv, FANS=メンバーLv どちらもここに入る)。次点で overlay text
    (combine_badge_struct.str 等)。FANSバッジのstrはファンクラブ名(非数値)なので log_extra
    を先に見る。最初に見つかった整数を返し、無ければ0(非表示)。"""
    if badge is None:
        return 0
    texts = []
    le = getattr(badge, "log_extra", None)
    if le is not None:
        texts.append(getattr(le, "level", None))
    cb = getattr(badge, "combine_badge_struct", None)
    if cb is not None:
        texts.append(getattr(cb, "str", None))
        texts.extend(_badge_text_candidates(getattr(cb, "text", None)))
    sb = getattr(badge, "string_badge", None)
    if sb is not None:
        texts.append(getattr(sb, "content_str", None))
    texts.extend(_badge_text_candidates(getattr(badge, "text_badge", None)))
    for t in texts:
        if not t:
            continue
        m = re.search(r"\d+", str(t))
        if m:
            return int(m.group())
    return 0


def _user_payload(user: Any) -> dict:
    if user is None:
        return {
            "user_id": "", "unique_id": "", "nickname": "(unknown)", "avatar": "",
            "fans_level": 0, "gifter_level": 0, "gifter_badge": "", "member_badge": "",
            "identity_key": "",
        }
    unique_id = getattr(user, "unique_id", "") or ""
    # 表示名とidentity keyを分ける。"(unknown)" は表示用のリテラルであって身元ではないので、
    # 名寄せ(identity_key)には素のnicknameだけを渡す。混ぜると身元不明の視聴者が全員
    # "(unknown)" という1 identityへ畳まれ、users表・貢献者集計で1人に潰れる。
    raw_nickname = getattr(user, "nick_name", "") or ""
    nickname = raw_nickname or unique_id or "(unknown)"
    avatar = _image_url(getattr(user, "avatar_thumb", None))
    # 数値のアカウントID(不変)。Gift eventとarmiesで同じ体系なので、Battle貢献の
    # 「実弾(コイン)」と「バトルスコア(PKポイント)」を貢献者単位で突合する鍵になる。
    user_id = str(getattr(user, "user_id", "") or getattr(user, "id", "") or "")
    # メンバーLv/ギフターLvはどちらもバッジの log_extra.level に入る(実配信で確認)。
    # メンバーLvは fans_club_info.fans_level に載ることもあるが、多くのeventでは空で
    # FANSバッジ側にしか無い。取れなければバッジ画像で代替、いずれも無ければ0/空(捏造しない)。
    fans = getattr(user, "fans_club_info", None)
    fans_level = int(getattr(fans, "fans_level", 0) or 0) if fans is not None else 0
    member_badge = _image_url(getattr(fans, "badge", None)) if fans is not None else ""
    fans_badge = _badge_by_scene(user, BADGE_SCENE_FANS)
    if not fans_level:
        fans_level = _badge_level(fans_badge)
    if not member_badge:
        member_badge = _badge_image(fans_badge)
    grade_badge = _badge_by_scene(user, BADGE_SCENE_USER_GRADE)
    gifter_level = _badge_level(grade_badge)
    gifter_badge = _badge_image(grade_badge)
    return {
        "user_id": user_id, "unique_id": unique_id, "nickname": nickname, "avatar": avatar,
        "fans_level": fans_level, "gifter_level": gifter_level,
        "gifter_badge": gifter_badge, "member_badge": member_badge,
        "identity_key": _identity_key(user_id, unique_id, raw_nickname),
    }


# ---- 流入元 / 視聴者のfollow関係(既に届いているfieldの追加読み) ----
# 新規subscribeもfetchも増やさない。取れなかった値は捏造せず ENTRY_UNKNOWN /
# FOLLOW_UNKNOWN として「観測したが空だった」ことを明示する。DBのNULLは別の意味
# (この計装より前に収集した行=未計測)なので、両者を混同しないこと。
ENTRY_UNKNOWN = "unknown"
FOLLOW_UNKNOWN = "unknown"
SHARE_UNKNOWN = "unknown"
COMMENT_UNKNOWN = "unknown"
SOURCE_UNKNOWN = "unknown"
# FollowInfo.follow_status の実値。protobufはdefaultを省くため、0(非follower)と未送出は
# 値だけでは区別できない。FollowInfo自体がwireに載っていた場合に限り0を非followerとして
# 読み、message ごと不在なら FOLLOW_UNKNOWN にする(非followerへ丸めない)。
_FOLLOW_STATUS_LABELS = {0: "not_following", 1: "following", 2: "mutual"}


def _on_wire(msg: Any) -> bool:
    """betterprotoのmessage fieldが実際にwireへ載っていたか。未設定でも空のdefault
    instanceが返る仕様のため、属性の有無では『届かなかった』と『空で届いた』を区別
    できない。presenceの唯一の判定手段がこれ。"""
    return isinstance(msg, betterproto.Message) and betterproto.serialized_on_wire(msg)


def _enter_signals(event: Any) -> dict:
    """JoinEventの流入元3種。実配信で到達を確認できたfieldのみを読む
    (client_enter_source / client_enter_type / client_live_reason)。"""
    out = {}
    for key, attr in (
        ("enter_source", "client_enter_source"),
        ("enter_type", "client_enter_type"),
        ("enter_reason", "client_live_reason"),
    ):
        value = str(getattr(event, attr, "") or "").strip()
        out[key] = value or ENTRY_UNKNOWN
    return out


def _follow_signals(user: Any) -> dict:
    """user.follow_info 由来のfollow関係。JoinEvent / LikeEvent にのみ載る。"""
    info = getattr(user, "follow_info", None) if user is not None else None
    if not _on_wire(info):
        return {"follow_status": FOLLOW_UNKNOWN, "follower_count": None}
    status = _FOLLOW_STATUS_LABELS.get(int(getattr(info, "follow_status", 0) or 0), FOLLOW_UNKNOWN)
    count = int(getattr(info, "follower_count", 0) or 0)
    return {"follow_status": status, "follower_count": count}


def _share_signals(event: Any) -> dict:
    """ShareEventの行き先。share_type / share_target を生値のまま残す。実配信では
    share_target が '-1' と '112' に割れ、share_type の有無とも相関するが、112が何を
    指すかは未確定なので解釈したlabelは付けない(分解は解析側の仕事)。protobufはscalarの
    presenceを区別できないため、0/空は SHARE_UNKNOWN として「届いたが空」を明示する。"""
    share_type = int(getattr(event, "share_type", 0) or 0)
    target = str(getattr(event, "share_target", "") or "").strip()
    return {
        "share_type": str(share_type) if share_type else SHARE_UNKNOWN,
        "share_target": target or SHARE_UNKNOWN,
    }


def _comment_signals(event: Any) -> dict:
    """CommentEventの content_language / comment_tag。視聴者層の言語構成をTikTok側の判定で
    取れる唯一の源。どちらもTikTokが後から追加したfieldで、古い収集分には存在しない。
    DBのNULLは「この計装より前=未計測」を意味するので、届かなかった場合は
    COMMENT_UNKNOWN を明示的に入れて両者を混同しないこと。comment_tagはenum名のJSON
    listで残す(数値はproto版で意味が動きうる)。"""
    language = str(getattr(event, "content_language", "") or "").strip()
    tags = [
        str(getattr(tag, "name", None) or tag)
        for tag in (getattr(event, "comment_tag", None) or [])
    ]
    return {
        "content_language": language or COMMENT_UNKNOWN,
        "comment_tag": json.dumps(tags, ensure_ascii=False) if tags else COMMENT_UNKNOWN,
    }


def _identity_signals(event: Any) -> dict:
    """payload.userIdentity 由来の配信者との関係。Comment / Gift に載る。moderator除外と
    subscriber判定の正規の源。message ごと不在なら全項目 未観測(None)にする。"""
    ident = getattr(event, "user_identity", None)
    if not _on_wire(ident):
        return {"follow_status": FOLLOW_UNKNOWN, "is_subscriber": None,
                "is_moderator": None, "is_gift_giver": None}
    if bool(getattr(ident, "is_mutual_following_with_anchor", False)):
        status = "mutual"
    elif bool(getattr(ident, "is_follower_of_anchor", False)):
        status = "following"
    else:
        status = "not_following"
    return {
        "follow_status": status,
        "is_subscriber": int(bool(getattr(ident, "is_subscriber_of_anchor", False))),
        "is_moderator": int(bool(getattr(ident, "is_moderator_of_anchor", False))),
        "is_gift_giver": int(bool(getattr(ident, "is_gift_giver_of_anchor", False))),
    }


def _epoch_seconds(raw: Any) -> Optional[float]:
    """epoch秒/ミリ秒のどちらで来るか一定しないTikTokのtimestampを秒へ正規化する。
    単位は桁で判定する(_create_time_secと同じ基準)。値が無い/範囲外はNone。"""
    try:
        value = int(raw or 0)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    if value > _EPOCH_SECONDS_MAX:
        value = value / 1000.0
    if value < _EPOCH_SECONDS_MIN:
        return None
    return float(value)


class TikTokCollector:
    def __init__(
        self, unique_id: str, broadcast: Broadcast, storage, settings, probe_gate=None, resolver=None, gift_icons=None, avatar_pool=None, avatar_proxy=None, record_video: bool = True, notifier=None, schedule_profiler=None
    ) -> None:
        self._broadcast = broadcast
        self._schedule_profiler = schedule_profiler
        self._storage = storage
        self._settings = settings
        # 通知機構。障害系とsession開始はops_events経由で拾えるが、coin rateとBattle開始は
        # ops_eventsに乗らない(運用logではない)ため、ここから直接渡す。未設定でも収集は動く。
        self._notifier = notifier
        self._probe_gate = probe_gate or ProbeGate(settings, lambda: 1)
        self._resolver = resolver
        self._gift_icons = gift_icons
        self._avatar_pool = avatar_pool
        self._avatar_proxy = avatar_proxy
        self._avatar_tasks: set = set()
        self._gift_icon_tasks: set = set()
        self._avatar_pool_tasks: set = set()
        self._badge_tasks: set = set()
        # 取得済みバッジURLのset(同一URLの再取得spam防止)。proxyのpath単位ディスク
        # キャッシュが最終的な重複排除を担うので、ここはbest-effortの軽い前段で十分。
        self._seen_badges: set = set()
        self._resolved_room_id: Optional[int] = None
        self._client: Optional[TikTokLiveClient] = None
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self.state = STATE_IDLE
        self.error_message: Optional[str] = None
        self.unique_id = unique_id
        self.session_id: Optional[int] = None
        self.room_id: Optional[int] = None
        self.stats = _empty_stats()
        self.steps = {step: "pending" for step in STEP_IDS}
        self._simulation = get_simulation()
        # 実配信の生eventサンプラー(重複shapeを除外して保存)。simulationは生protoが無いので
        # 持たない。captureごとに setting(sample_capture) を見るのでここは常時生成でよい。
        self._sampler: Optional[EventSampler] = (
            None if self._simulation
            else EventSampler(get_sample_dir(), settings.get("sample_capture_max_per_kind"))
        )
        self._bucket_seconds = settings.get("bucket_seconds")
        self.recent_events: deque = deque(maxlen=settings.get("event_history"))
        self.timeline: deque = deque(maxlen=get_timeline_limit())
        # 入室ドライバ(portal/宝箱)のmask marker専用。高頻度側なので溢れるのはここだけに
        # なるよう、構造marker(接続系・Battle/Collab)は下の別dequeへ分けてある。
        self.markers: deque = deque(maxlen=_MASK_MARKER_CAP)
        # 接続系marker(接続/再接続/切断/LIVE終了/録画)は別dequeで持つ。同一dequeだと
        # 長時間sessionでportal/envelope等の高頻度markerがcapを食い潰し、欠測秒数を復元する
        # 唯一の材料である切断/再接続の対が黙って消える。押し出され得ない容量にはできない
        # ので、押し出され得ない場所へ分ける。
        self.conn_markers: deque = deque(maxlen=_CONN_MARKER_CAP)
        # Battle/Collab(LinkMic)markerも同じ理由で別deque。Battle回数・コラボ窓はsessionの
        # 骨格でありmask markerに押し出されてはならない。
        self.linkmic_markers: deque = deque(maxlen=_LINKMIC_MARKER_CAP)
        # 入室ドライバ(portal/宝箱)のmask marker集約用: kind別の最終emit時刻。1演出で複数
        # message(invite/ping/finish/grab)が飛ぶため、refractoryで1 onsetへ寄せ、markers
        # dequeのcapを既存battle markerが押し出されないよう保護する。
        self._last_driver_marker: dict = {}
        self.gifters: dict = {}
        # User正規化プロフィール(identity_key -> profile)。変更されうる属性(名前/@handle/
        # avatar/Lv/badge)をSession中1か所に集約し、gifters等はidentity_keyのみ持つ。
        self.users: dict = {}
        self.gift_types: dict = {}
        # gift_id -> 単価(diamonds_each)。Battleのグローブ(Critical Strike)刺さり率を
        # coin帯別に集計する際、armies eventのgift_idを価格帯へ写像するために使う。
        self._gift_coins: dict = {}
        self._battles: dict = {}
        # グローブcrit判定(delta厳密一致方式)の作業state。詳細は _reset_session_data 参照。
        self._glove_pending: dict = {}
        self._glove_prev_score: dict = {}
        self._glove_deltas: dict = {}
        self._glove_recent_gifts: list = []
        self._glove_attr: dict = {}
        self._glove_clock_warned = False
        # コラボ(非BattleのLinkMic)接続窓。channel_id -> {start, guests_max}(接続中)、
        # finish/session終了で _collab_windows へ確定。入室コンテキスト3分類(doc §14)に使う。
        self._collab_open: dict = {}
        self._collab_windows: list = []
        # 宝箱/Portalの実測。markerの不応期とは別に、1件ずつ残す(支出の合計が要るため)。
        # _envelope_index は envelope_id -> 行 で、同一宝箱のNEW/HIDE通知を1行へ畳む。
        self._envelopes: list = []
        self._envelope_index: dict = {}
        # 進行中sessionのbattles/collab_windowsを最後に中間永続化した時刻(定期checkpoint用)。
        self._last_checkpoint_at: float = 0.0
        self._owner_id: str = ""
        self.owner: dict = {"unique_id": unique_id, "nickname": unique_id, "avatar": "", "league": ""}
        self._apply_cached_owner()
        self._owner_warned = False
        # 配信者リーグ帯(A1/B3等)。接続時にgift listから取得しsessionへ配信単位で保存する。
        self._league: str = ""
        # Logs the first observed event create_time (raw + detected unit) once per session.
        self._create_time_logged = False
        # Battle ids whose team_armies proto shape has been logged once (diagnostic
        # for confirming team_users population against live data, not the sim shape).
        self._team_shape_logged: set = set()
        self._last_battles_sent = 0.0
        # battle_debug_capture有効時の生event追記先。毎eventのopen/closeを避け、pathが
        # 変わる(新session)まで同じhandleを使い回す。
        self._battle_raw_fh = None
        self._battle_raw_path: Optional[str] = None
        self._stop_requested = False
        self._reconnect_attempt = 0
        # Whether the live websocket has ever established in the current session. A
        # first connect that only succeeded after transient retries (e.g. a Sign API
        # 500) still has _reconnect_attempt > 0, so it cannot stand in for "this is a
        # reconnect": _on_connect keys the resume-vs-auto-record decision off this
        # instead. Reset per session in _reset_session_data.
        self._ever_connected = False
        self._last_stats_sent = 0.0
        # RoomUserSeqの貢献者Ranking保存の間引き用。最後に書いた時刻と、その時の内容の
        # 指紋(rank/user/scoreのtuple)。同じRankingが続くあいだは書かない。
        self._contrib_saved_at = 0.0
        self._contrib_saved_sig: Optional[tuple] = None
        self._score_anchor: dict = {}
        # 最後に保存した配信者follower総数。TikTok側の値は結果整合で前後するため、
        # 「変化したら書く」だけを条件にする(単調化はしない)。
        self._follower_saved: Optional[int] = None
        # Timestamp of the last datum received from TikTok over the live websocket.
        # The idle watchdog uses it to detect a silent half-open connection (host
        # network drop) where connect() never returns and no disconnect fires.
        self._last_data_at: Optional[float] = None
        self._idle_disconnect = False
        # Reason text for a watchdog-forced reconnect, surfaced by _connect_once so
        # a video-stall reconnect reports its true cause instead of the idle default.
        self._forced_reason: Optional[str] = None
        # Recording-stall watchdog state: last observed recorder progress token and
        # the wallclock it last advanced. Detects a silently frozen video stream
        # (ffmpeg alive, no new segments) while the event websocket keeps flowing —
        # the one gap the idle watchdog (event-silence) and _maybe_resume_after_
        # finalize (needs ffmpeg to exit) both miss. Re-baselined per recording.
        self._rec_progress: Optional[tuple] = None
        self._rec_progress_at: float = 0.0
        # Whether recording should be running for the current live. Set when a
        # recording starts (auto or manual), cleared on manual stop, so a
        # websocket reconnect resumes only a recording the user did not stop.
        self._recording_desired = False
        # Single-flight guard for the empty-finalize recovery loop (re-resolve stream
        # URL + relaunch). Prevents a stale recorder and its replacement both driving
        # concurrent recovery loops when they finalize near-simultaneously.
        self._recovering = False
        # Room id of a broadcast classified as restricted (members-only / age). While
        # the same room keeps resolving live, the watch loop holds the "restricted"
        # status without reconnecting, so no sign request is spent and no empty
        # session is created. Cleared on a successful connect or when the room ends.
        self._restricted_room_id: Optional[int] = None
        # monotonic期限。これを過ぎたら制限holdを1度だけ再確認する(0=次の機会に即確認)。
        self._restricted_recheck_at: float = 0.0
        # 現holdで再確認を行った回数。間隔を段階的に広げるbackoffの段数。
        self._restricted_recheck_count: int = 0
        # Per-target preference: when False this monitor only collects data and never
        # records video (auto-record is skipped and manual recording is rejected).
        self.record_video = record_video
        # Same source as the server's RECORD_DIR/FINAL_DIR (DB setting > env > default).
        # Recording writes to the working dir; completed mp4s relocate to the final dir
        # (empty final setting => no split, final == working).
        self._record_dir = self._settings.get("record_dir")
        self._final_record_dir = self._settings.get("record_dir_final") or self._record_dir
        self._room_info: dict = {}
        self.recorder: Optional[Recorder] = None
        # battle_id -> [OpponentRoomListener]. PK中だけ相手RoomのGiftを拾うlistener群。
        self._opp_listeners: dict = {}
        # 「まだLIVEが始まらない」進捗logの最終出力時刻(monotonic)。offlineは全監視の
        # 定常状態なので、毎pollではなく間隔gate経由でしか出さない。
        self._last_wait_log_at: float = 0.0

    def snapshot(self) -> dict:
        return {
            "status": self.state,
            "simulation": self._simulation,
            "error_message": self.error_message,
            "ffmpeg_available": ffmpeg_available(),
            "record_video": self.record_video,
            "recording": self.recorder.snapshot() if self.recorder else None,
            "unique_id": self.unique_id,
            "owner": self.owner,
            "session_id": self.session_id,
            "room_id": self.room_id,
            "stats": self.stats,
            "steps": [
                {"id": step, "label": STEP_LABELS[step], "status": self.steps[step]}
                for step in STEP_IDS
            ],
            "recent_events": list(self.recent_events),
        }

    def timeline_snapshot(self) -> dict:
        return {
            "bucket_seconds": self._bucket_seconds,
            "buckets": list(self.timeline),
            "markers": self._all_markers(),
        }

    def _touch_user(self, user: dict) -> str:
        """User正規化プロフィールをSession registryに反映し、identity_keyを返す。変更され
        うる属性は最新の非空値で上書きする(storage.users表と同じ最新値上書きロジック)。
        identity_keyを持つdictはその値をそのまま使う(空文字=身元不明として畳まない)。
        recomputeすると表示用の "(unknown)" が名寄せkeyになり別人が1人へ潰れる。"""
        if "identity_key" in user:
            key = user["identity_key"]
        else:
            key = _identity_key(
                user.get("user_id"), user.get("unique_id"), user.get("nickname")
            )
        if not key:
            return ""
        prof = self.users.get(key)
        if prof is None:
            self.users[key] = {
                "user_id": user.get("user_id", ""),
                "unique_id": user.get("unique_id", ""),
                "nickname": user.get("nickname", "") or "(unknown)",
                "avatar": user.get("avatar", ""),
                "fans_level": user.get("fans_level", 0) or 0,
                "gifter_level": user.get("gifter_level", 0) or 0,
                "gifter_badge": user.get("gifter_badge", ""),
                "member_badge": user.get("member_badge", ""),
            }
            return key
        for field in ("user_id", "unique_id", "avatar", "gifter_badge", "member_badge"):
            if user.get(field):
                prof[field] = user[field]
        nickname = user.get("nickname") or ""
        if nickname and nickname != "(unknown)":
            prof["nickname"] = nickname
        if user.get("fans_level"):
            prof["fans_level"] = user["fans_level"]
        if user.get("gifter_level"):
            prof["gifter_level"] = user["gifter_level"]
        return key

    def summary_snapshot(self) -> dict:
        users = sorted(
            (
                {
                    "user_id": "", "unique_id": "", "nickname": "(unknown)", "avatar": "",
                    "fans_level": 0, "gifter_level": 0, "gifter_badge": "", "member_badge": "",
                    **self.users.get(key, {}),
                    "gifts": g["gifts"],
                    "diamonds": g["diamonds"],
                    "items": g["items"],
                }
                for key, g in self.gifters.items()
            ),
            key=lambda u: (u["diamonds"], u["gifts"]),
            reverse=True,
        )
        gifts = sorted(
            self.gift_types.values(),
            key=lambda g: (g["diamonds"], g["count"]),
            reverse=True,
        )
        return {
            "totals": {
                "gifts": self.stats["gifts"],
                "diamonds": self.stats["diamonds"],
                "unique_gifters": len(self.gifters),
                "comments": self.stats["comments"],
                "likes_total": self.stats["likes_total"],
                "follows": self.stats["follows"],
                "battles": self.stats["battles"],
            },
            "users": users[:100],
            "gifts": gifts[:100],
        }

    def battles_snapshot(self) -> dict:
        battles = sorted(
            (b for b in self._battles.values() if not b.get("aborted")),
            key=lambda b: b["start_time"],
            reverse=True,
        )
        # 勝敗はcore.battleの確定判定へ揃える(履歴画面・解析・焼き込みと同じrule)。
        # _battle_publicは内部recordの浅copyを返し、DBへ書き戻す_persist_progressは
        # _battle_publicを直接呼ぶため、ここでの書き換えは表示用snapshotだけに効く。
        public = [annotate_result(self._battle_public(b)) for b in battles]
        # armies eventはUser単位の実弾内訳を欠くため、自陣貢献はGift eventから再構成する。
        if self.session_id is not None:
            self._storage.apply_battle_gift_contributions(self.session_id, public)
        return {
            "unique_id": self.unique_id,
            "owner": self.owner,
            "battles": public,
        }

    def _battle_public(self, rec: dict) -> dict:
        # snapshot経由でapply_battle_gift_contributionsが貢献recordを書き換えるため、
        # 内側のdictをコピーしてliveの収集状態と切り離す(読み出しがliveを汚染しない)。
        contributions = sorted(
            (dict(c) for c in rec["contributions"].values()),
            key=lambda c: c["diamonds"],
            reverse=True,
        )
        participants = self._public_participants(rec)
        return {
            **rec,
            "contributions": contributions,
            "bonus_missions": self._public_bonus_missions(rec),
            "participants": participants,
            # 形式は参加者のteam_idから導出する(team構造の有無では個人マルチと区別できない)。
            "type": battle_type(participants),
            # 現行ruleで判定済みの目印。起動時のbattle_migrationがこれを見てskipする。
            "topo_v": BATTLE_TOPOLOGY_VERSION,
            # FINISH is the only terminal action that reaches a non-aborted record
            # (aborted ones are filtered out upstream), so anything else is in-progress.
            "ongoing": rec.get("action") != BATTLE_ACTION_FINISH,
        }

    def _public_bonus_missions(self, rec: dict) -> list:
        """bonus_missions を表示用に整える。貢献者の表示名/avatarが未確定なら、その時点の
        contributions(数値ID突合)で再解決する(遅れて判明した名前を反映するため)。"""
        out = []
        for m in rec.get("bonus_missions", []) or []:
            # 倍率/時間帯/進捗/ボーナス/貢献者のいずれも無いmissionは中身が無いので除外する。
            if not any((
                m.get("multiplier"), m.get("task_start_ts"), m.get("reward_start_ts"),
                m.get("bonus_sum"), m.get("progress"), m.get("contributors"),
            )):
                continue
            contributors = []
            for c in m.get("contributors", []):
                nickname, avatar = c.get("nickname", ""), c.get("avatar", "")
                if not nickname:
                    resolved = rec["contributions"].get(c.get("user_id", "")) or {}
                    nickname = resolved.get("nickname", "") or nickname
                    avatar = avatar or resolved.get("avatar", "")
                contributors.append({**c, "nickname": nickname, "avatar": avatar})
            contributors.sort(key=lambda c: c.get("count", 0), reverse=True)
            out.append({**m, "contributors": contributors})
        return out

    def _public_participants(self, rec: dict) -> list:
        """Flatten the participant map into a score-ranked list. The monitored host
        is uniquely known (owner id), so its display fields come from self.owner;
        every other host is enriched from the battle's anchor_info. rank is the
        1-based standing by score — the basis for personal multi (Nコラ) display."""
        parts = []
        for p in rec.get("participants", {}).values():
            entry = dict(p)
            if entry.get("is_own"):
                entry["unique_id"] = self.owner.get("unique_id") or entry.get("unique_id") or self.unique_id
                entry["nickname"] = self.owner.get("nickname") or entry.get("nickname") or self.unique_id
                entry["avatar"] = self.owner.get("avatar") or entry.get("avatar") or ""
            parts.append(entry)
        parts.sort(key=lambda p: p.get("score", 0) or 0, reverse=True)
        for i, p in enumerate(parts):
            p["rank"] = i + 1
        return parts

    def _bucket(self) -> dict:
        now = time.time()
        start = int(now // self._bucket_seconds * self._bucket_seconds)
        if not self.timeline or self.timeline[-1]["start"] != start:
            self.timeline.append(_empty_bucket(start, self.stats["viewers"]))
        return self.timeline[-1]

    def _add_marker(self, kind: str, label: str) -> None:
        self.markers.append({"time": time.time(), "kind": kind, "label": label})

    def _add_conn_marker(self, kind: str, label: str) -> None:
        """接続lifecycleのmarker。driver marker等に押し出されない別dequeへ積み、その場で
        DBへも中間永続化する(非graceful終了でfinalizeへ届かなくても残るように)。"""
        self.conn_markers.append({"time": time.time(), "kind": kind, "label": label})
        self._persist_markers()

    def _add_linkmic_marker(self, kind: str, label: str) -> None:
        """Battle/Collab(LinkMic)のmarker。mask markerに押し出されない別dequeへ積み、その場で
        DBへも中間永続化する(非graceful終了でfinalizeへ届かなくても残るように)。"""
        self.linkmic_markers.append({"time": time.time(), "kind": kind, "label": label})
        self._persist_markers()

    def _all_markers(self) -> list:
        """kind別に分けた全dequeを時刻順に統合する。UI/永続化はどちらもこれを使う。"""
        return sorted(
            list(self.markers) + list(self.conn_markers) + list(self.linkmic_markers),
            key=lambda m: m["time"],
        )

    def _persist_markers(self) -> None:
        """markerをDBへ中間永続化する。best-effortで本流(受信ループ)は止めない。
        追記なので、後続のcheckpointやfinalizeが未保存分を書き足して自動回復する。"""
        if self.session_id is None:
            return
        try:
            self._storage.append_markers(self.session_id, self._all_markers())
        except Exception:
            logger.warning(
                "failed to checkpoint session markers; the next checkpoint will write "
                "the missing ones", exc_info=True,
                extra={"event": "collector.marker_checkpoint_failed",
                       "ctx": {"markers": len(self.markers),
                               "conn_markers": len(self.conn_markers),
                               "linkmic_markers": len(self.linkmic_markers)}},
            )

    def _add_driver_marker(self, kind: str, label: str) -> None:
        """入室ドライバ(portal/宝箱)のmask marker。1演出で複数message(invite/ping/finish/
        grab)が飛ぶため、同種markerを不応期でonsetへ集約する。溢れてよいのはこのdequeだけ
        なので、集約はmask marker自身の欠落を減らすために効かせる。"""
        now = time.time()
        last = self._last_driver_marker.get(kind)
        if last is not None and now - last < _DRIVER_MARKER_REFRACTORY_SECONDS:
            return
        self._last_driver_marker[kind] = now
        self._add_marker(kind, label)

    def _persist_live_create_time(self) -> None:
        """room_infoが持つ配信そのものの開始時刻をsessionへ永続化する。sessions.started_at
        はcollectorが接続した時刻でしかないため、収集開始遅延はこの2値の差でしか測れない。
        取れない場合はNULLのまま(=計測不能)にする。接続時のtotal_userとjoins累計の乖離は
        配信側throttleに支配されるので開始遅延の代用にはならない。"""
        if self.session_id is None:
            return
        create_time = _epoch_seconds((self._room_info or {}).get("create_time"))
        if create_time is None:
            return
        try:
            self._storage.set_session_live_create_time(self.session_id, create_time)
        except Exception:
            logger.warning(
                "failed to persist the broadcast create_time; collection start delay "
                "will not be measurable for this session", exc_info=True,
                extra={"event": "collector.live_create_time_persist_failed",
                       "ctx": {"room_id": self.room_id,
                               "live_create_time": create_time}},
            )

    def _reset_session_data(self) -> None:
        self._reconnect_attempt = 0
        self._ever_connected = False
        # _resolved_room_id is intentionally NOT cleared here: _wait_for_live_start
        # resolves it just before this runs, and _connect_once needs it to connect by
        # room id (skipping the WAF-gated HTML scrape) and to gate restricted rooms.
        # It is always overwritten by the next _resolve_live before use.
        self.room_id = None
        self.error_message = None
        self.stats = _empty_stats()
        self._bucket_seconds = self._settings.get("bucket_seconds")
        self.recent_events = deque(maxlen=self._settings.get("event_history"))
        self.timeline.clear()
        self.markers.clear()
        self.conn_markers.clear()
        self.linkmic_markers.clear()
        self._last_driver_marker.clear()
        self.gifters = {}
        self.users = {}
        self.gift_types = {}
        self._battles = {}
        # battle_id -> スコア推移の記録窓を開いた時刻。_append_score_sampleの間引き起点。
        self._score_anchor = {}
        # グローブcrit判定(delta厳密一致方式)。armies eventごとの自hostスコア増分(delta)を
        # poolに貯め、窓中giftの「倍率タイムm×単価(通常)」「窓倍率M×単価(crit)」との厳密一致で
        # 排他的に突合する。一意に決まらないものはcrit=None(判定不能)のまま確定する。
        # いずれもrec外(非永続)に持つ。
        # battle_id -> [{t, total, multiple, ev(=glove_events内の同一dict)}]
        self._glove_pending = {}
        # battle_id -> 直近観測した自hostのバトルスコア
        self._glove_prev_score = {}
        # battle_id -> [[観測ts, 未消費delta], ...]
        self._glove_deltas = {}
        # 窓外に自室へ届いたgift [t, total]。deltaのpoolから通常寄与(m×total)を先に
        # 消費してpoolを掃除し、窓中giftとの偶然一致(偽crit)を防ぐ。
        self._glove_recent_gifts = []
        # battle_id -> [{gid, t, delta, flag, used}]。armiesが名指ししたgiftへdeltaを同定した
        # 記録。額一致より強い証拠なので先に消費する。
        self._glove_attr = {}
        # server時計(create_time)欠落の警告をSessionごとに1回だけ出すためのflag。
        self._glove_clock_warned = False
        self._collab_open = {}
        self._collab_windows = []
        self._envelopes = []
        self._envelope_index = {}
        self._last_checkpoint_at = 0.0
        self._team_shape_logged = set()
        # 前Sessionのlistenerは_runの終了処理でstop済み。dictだけ空に戻す。
        self._opp_listeners = {}
        self._owner_id = ""
        self.owner = {"unique_id": self.unique_id, "nickname": self.unique_id, "avatar": "", "league": ""}
        self._apply_cached_owner()
        self._league = ""
        self._owner_warned = False
        self._create_time_logged = False
        self._contrib_saved_at = 0.0
        self._contrib_saved_sig = None
        self._follower_saved = None
        self._recording_desired = False
        # We only reset a session for a recordable live; a restriction hold no longer applies.
        self._clear_restricted_hold()

    def _clear_restricted_hold(self) -> None:
        """制限holdの状態を一括で解除する。room id・再確認期限・backoff段数は必ず同時に
        落とすこと(段数が残ると、次の別配信の再確認がいきなり上限間隔から始まる)。"""
        self._restricted_room_id = None
        self._restricted_recheck_at = 0.0
        self._restricted_recheck_count = 0

    def _arm_restricted_recheck(self) -> int:
        """次の再確認までの待ち時間を段数から決めて期限を張り、その秒数を返す。
        基準間隔を_RESTRICTED_FAST_RECHECKS回繰り返した後、上限まで倍々に広げる
        (例: 60,60,60,120,240,480,900,900...)。上限到達後は基準間隔に戻さない —
        そこまで解けない制限は本物である可能性が高く、戻すと無駄な密探索を繰り返す。"""
        base = self._settings.get("restricted_recheck_interval")
        cap = self._settings.get("restricted_recheck_max_interval")
        steps = self._restricted_recheck_count - _RESTRICTED_FAST_RECHECKS + 1
        # 長時間holdで段数が伸び続けるため、cap到達後は指数を打ち止めて巨大数の算出を避ける。
        steps = min(steps, _RESTRICTED_MAX_BACKOFF_STEPS)
        delay = base if steps <= 0 else base * (2 ** steps)
        # capがbaseを下回る設定でも必ずbase以上にする(0秒間隔での連打を防ぐ)。
        delay = max(base, min(delay, cap))
        self._restricted_recheck_at = time.monotonic() + delay
        return delay

    def _prepare_session(self) -> None:
        self._reset_session_data()
        self.steps = {step: "pending" for step in STEP_IDS}
        self.steps["request"] = "done"
        self.steps["live_check"] = "done"
        self.steps["websocket"] = "active"
        self.state = STATE_CONNECTING
        self.session_id = self._storage.create_session(self.unique_id, self._bucket_seconds)
        self._client = self._build_client(self.unique_id)
        # session_id を束ねるのは _run のループ本体で、この行はその外側(直前)に居る。
        # 「どのsessionが起きたか」が最初に確定する行なので、ここだけ明示的に束ねる。
        with log_context(session_id=self.session_id):
            self._storage.record_ops_event(
                logger, "session.started",
                f"配信のsessionを開始しました（room {self._resolved_room_id}）",
                severity=OPS_INFO,
                detail={"room_id": self._resolved_room_id,
                        "bucket_seconds": self._bucket_seconds,
                        "record_video": self.record_video},
            )

    async def start(self) -> None:
        async with self._lock:
            if self.state in ACTIVE_STATES:
                raise RuntimeError("収集は既に実行中です。先に停止してください。")
            if self._task is not None and not self._task.done():
                done, pending = await asyncio.wait({self._task}, timeout=5)
                if pending:
                    raise RuntimeError("前回の収集処理が終了していません。少し待ってから再試行してください。")
            self._stop_requested = False
            self._reset_session_data()
            self.steps = {step: "pending" for step in STEP_IDS}
            self.steps["request"] = "done"
            self.steps["live_check"] = "active"
            self.state = STATE_CONNECTING
            if self._simulation:
                self._client = None
                self._task = asyncio.create_task(self._run_simulation(), name=f"tictok-sim-{self.unique_id}")
            else:
                self._task = asyncio.create_task(self._run(), name=f"tictok-collector-{self.unique_id}")
        # ContextVarはtask生成時点のcontextをcopyするので、ここでunique_idを立てても
        # _run側には効かない(呼び元はmanager/HTTP task)。相関は_run/_run_simulationの
        # 冒頭で張り、この行はrequestを出した側のlogに監視対象を載せるだけ。
        with log_context(unique_id=self.unique_id):
            logger.info(
                "monitoring start requested (mode=%s)",
                "simulation" if self._simulation else "live",
                extra={"event": "collector.monitor_start_requested",
                       "ctx": {"simulation": self._simulation,
                               "record_video": self.record_video}},
            )
        await self._notify_state()

    async def stop(self) -> None:
        async with self._lock:
            client = self._client
            task = self._task
        if self.state not in ACTIVE_STATES:
            raise RuntimeError("収集は実行されていません。")
        with log_context(unique_id=self.unique_id, session_id=self.session_id):
            logger.info(
                "collection stop requested while %s", self.state,
                extra={"event": "collector.monitor_stop_requested",
                       "ctx": {"state": self.state}},
            )
            self._stop_requested = True
            if client is not None and self.state == STATE_CONNECTED:
                try:
                    await client.disconnect()
                except Exception:
                    # 停止要求のdisconnect失敗。この後のtask cancelが必ず落とすので回復する。
                    logger.warning(
                        "graceful disconnect failed on stop; falling back to cancelling "
                        "the collector task", exc_info=True,
                        extra={"event": "collector.disconnect_failed",
                               "ctx": {"phase": "stop"}},
                    )
            elif task is not None:
                task.cancel()
            if task is not None:
                done, pending = await asyncio.wait({task}, timeout=10)
                if pending:
                    task.cancel()
                    logger.warning(
                        "collector task did not stop within the grace period; cancelling",
                        extra={"event": "collector.stop_timed_out", "ctx": {}},
                    )

    async def _run(self) -> None:
        # このtaskが生きている間、全てのlogに監視対象が載る。task寿命=scopeなのでresetは
        # 不要(ContextVarはtask生成時のcopyに書き込むため呼び元へ漏れない)。TikTokLive側の
        # handler task もこのcontextをcopyして生まれるので、event handlerのlogにも載る。
        ctx_unique_id.set(self.unique_id)
        first_cycle = True
        try:
            while True:
                if not await self._wait_for_live_start(
                    skip_first_check=not first_cycle, immediate_first=first_cycle
                ):
                    break
                first_cycle = False
                # A live already classified as restricted (members-only / age) is still
                # up: keep watching for a normal broadcast without reconnecting, so we
                # spend no sign request and create no empty session for it. A new
                # broadcast reissues the room id, which fails this guard and reconnects.
                if (
                    self._resolved_room_id is not None
                    and self._resolved_room_id == self._restricted_room_id
                    and await self._restricted_hold_continues()
                ):
                    continue
                self._prepare_session()
                # session scopeはループ本体で持つ。_persist_final が self.session_id を
                # Noneに落とすので、with の終端はその**後**に置くこと(先に抜けると
                # 「どのsessionが終わったか」が終了logから消える)。
                with log_context(session_id=self.session_id):
                    if await self._run_session() == "break":
                        break
        except asyncio.CancelledError:
            self.state = STATE_DISCONNECTED
            await self._stop_all_opponent_listeners()
            await self._stop_recording()
            # cancel時点ではまだsession_idが残っている。ここを束ねないと、最も知りたい
            # 「強制終了でどのsessionが打ち切られたか」だけが相関の付かないlogになる。
            with log_context(session_id=self.session_id):
                self._persist_final()
        finally:
            if self.state in (STATE_DISCONNECTED, STATE_ENDED):
                self.steps["receiving"] = "done"
            await self._notify_state()
            logger.info(
                "collector task finished in state %s", self.state,
                extra={"event": "collector.finished", "ctx": {"state": self.state}},
            )

    async def _run_session(self) -> str:
        """1 session分の接続〜終了。"break" を返したら _run の watch loop を抜ける。
        _run のループ本体から session scope の log_context 内で呼ばれる。"""
        await self._notify_state()
        outcome = await self._session_loop()
        await self._stop_all_opponent_listeners()
        await self._stop_recording()
        if outcome == "restricted":
            # Recording is impossible for this broadcast. Stay a non-terminal
            # "restricted" watcher (status held by _announce_waiting) so a later
            # normal broadcast on a new room id is still detected and recorded.
            # The empty session row is kept and finalized as "restricted" rather
            # than deleted: deleting it left an unexplained gap in the history id
            # sequence. Aggregations exclude the status, so it costs no statistics.
            self._restricted_room_id = self._resolved_room_id
            self._restricted_recheck_count = 0
            recheck_seconds = self._arm_restricted_recheck()
            self.state = STATE_RESTRICTED
            self._mark_session_restricted()
            await self._notify_state()
            self._storage.record_ops_event(
                logger, "session.restricted",
                f"限定配信のため録画できません（会員限定・年齢制限、"
                f"room {self._resolved_room_id}）。監視は続けます",
                severity=OPS_WARNING,
                detail={"room_id": self._resolved_room_id,
                        "recheck_seconds": recheck_seconds},
            )
            return "continue"
        self._persist_final()
        await self._notify_state()
        if outcome in ("stopped", "fatal"):
            return "break"
        logger.info(
            "session closed (%s); resuming the watch loop", outcome,
            extra={"event": "collector.watch_resumed", "ctx": {"outcome": outcome}},
        )
        return "continue"

    async def start_recording(self) -> None:
        if not self.record_video:
            raise RuntimeError("この監視対象は動画保存OFF（データのみ）です。先に動画保存をONにしてください。")
        if self.state != STATE_CONNECTED:
            raise RuntimeError("録画は配信に接続中のみ開始できます。")
        if self.recorder is not None and self.recorder.is_active:
            raise RuntimeError("既に録画中です。")
        url, quality = extract_stream_url(self._room_info)
        if not url:
            logger.warning(
                "no stream URL in room_info; this broadcast cannot be recorded",
                extra={"event": "collector.stream_url_missing",
                       "ctx": {"room_id": self.room_id,
                               "room_info_keys": sorted(self._room_info.keys())}},
            )
            raise RuntimeError("この配信のstream URLを取得できませんでした（録画不可）。")
        # F9: 空録画の切り分けはこの1行に懸かっている。URLの失効時刻はURL自身のqueryにしか
        # 無いので、秘匿値だけmaskしてexpire系は残す。取れなければ載せない(捏造しない)。
        url_ctx = _stream_url_ctx(url)
        remaining = url_ctx.get("seconds_to_expiry")
        if remaining is not None and remaining <= get_log_stream_url_expiry_warn_seconds():
            logger.warning(
                "stream URL has %.0fs of validity left at launch; the recording is "
                "likely to finalize empty", remaining,
                extra={"event": "collector.stream_url_expiry_detected",
                       "ctx": {"quality": quality, **url_ctx}},
            )
        else:
            logger.info(
                "stream URL resolved for recording (quality=%s)", quality,
                extra={"event": "collector.stream_url_resolved",
                       "ctx": {"quality": quality, **url_ctx}},
            )
        recorder = Recorder(
            self.unique_id, self._record_dir, self.session_id,
            keep_hls=bool(self._settings.get("recording_keep_hls")),
            final_dir=self._final_record_dir,
            storage=self._storage,
        )
        await recorder.start(
            self._room_info,
            on_finalize=self._on_recording_finalized,
            on_notify=self._notify_state,
        )
        planned_name = f"{recorder.base}.mp4"
        recorder.recording_id = self._storage.create_recording(
            self.session_id,
            self.unique_id,
            str(self._record_dir),
            planned_name,
            recorder.quality,
            recorder.started_at,
        )
        # 以降このtask(と、ここから生まれるtask)のlogに recording_id が載る。ContextVarは
        # task境界でcopyされるため、別taskで動くrecorder自身のlogまでは遡及しない — 録画の
        # 開始/停止を判断したcollector側の系列を追えるようにするための束ね。
        ctx_recording_id.set(recorder.recording_id)
        self.recorder = recorder
        self._recording_desired = True
        # Fresh stall baseline: the new recording must earn its own progress history
        # so the watchdog never judges it against a prior (possibly stalled) recorder.
        self._rec_progress = None
        self._rec_progress_at = time.time()
        self._add_conn_marker("record", "録画開始")
        await self._record("system", {"text": f"録画を開始しました（quality: {recorder.quality}）。"})
        await self._notify_state()

    async def stop_recording(self) -> None:
        if self.recorder is None or not self.recorder.is_active:
            raise RuntimeError("録画は実行されていません。")
        # User-initiated stop: clear intent so a later reconnect does not resume it.
        self._recording_desired = False
        logger.info(
            "recording stop requested by the user",
            extra={"event": "collector.recording_stop_requested", "ctx": {}},
        )
        await self.recorder.stop()
        ctx_recording_id.set(None)
        await self._notify_state()

    async def set_record_video(self, record_video: bool) -> None:
        """Toggle this target's video-saving preference. Turning it off stops any
        recording in progress (and clears the resume intent) so the monitor keeps
        collecting data without keeping video; turning it on lets the next live
        auto-record per the global setting."""
        if self.record_video == record_video:
            return
        self.record_video = record_video
        logger.info(
            "video saving turned %s for this monitor", "on" if record_video else "off",
            extra={"event": "collector.record_video_toggled",
                   "ctx": {"record_video": record_video}},
        )
        if not record_video and self.recorder is not None and self.recorder.is_active:
            self._recording_desired = False
            try:
                await self.recorder.stop()
            except Exception:
                # ffmpegが残る可能性があるが、次のstop/finalizeとwatchdogが回収する。
                logger.warning(
                    "failed to stop the recording when video saving was turned off; "
                    "ffmpeg may still be running", exc_info=True,
                    extra={"event": "collector.recording_stop_failed",
                           "ctx": {"phase": "record_video_off"}},
                )
        await self._notify_state()

    async def _stop_recording(self) -> None:
        # Monitor/server shutdown: wait for finalize so the mp4 is fully written.
        if self.recorder is not None:
            try:
                await self.recorder.stop(wait=True)
            except Exception:
                # session終了時のstopなので、失敗するとmp4が未finalizeのまま残りうる。
                # 自動でこれを拾い直す経路は無い。
                logger.error(
                    "failed to stop the recording at session end; the mp4 may be left "
                    "unfinalized", exc_info=True,
                    extra={"event": "collector.recording_stop_failed",
                           "ctx": {"phase": "session_end"}},
                )
            ctx_recording_id.set(None)

    async def _on_recording_finalized(self, recorder: Recorder) -> None:
        snap = recorder.snapshot()
        # An empty recording captured no data and left no playable artifact (a dead
        # stream URL, e.g. a full host drop that reissues the URL). Drop the row so
        # failed empty attempts don't clutter the recording history.
        empty = snap.get("bytes", 0) <= 0 and recorder.output_path is None
        if recorder.recording_id is not None:
            if empty:
                # 成果物ゼロで履歴行も消える=この録画は完全に失われる。回復は
                # _maybe_resume_after_finalize が別URLで撃ち直す形でしか無いので、
                # 「何も残らなかった」事実そのものはここで確定させて残す。
                logger.warning(
                    "recording finalized empty (no bytes, no output file); dropping its "
                    "history row and attempting recovery",
                    extra={"event": "collector.recording_empty_dropped",
                           "ctx": {"recorder_state": recorder.state,
                                   "error": recorder.error}},
                )
                self._storage.delete_recording(recorder.recording_id)
            else:
                self._storage.update_recording(
                    recorder.recording_id,
                    recorder.state,
                    str(recorder.output_path) if recorder.output_path else "",
                    recorder.output_path.name if recorder.output_path else "",
                    recorder.ended_at,
                    snap["bytes"],
                    recorder.error,
                    recorder.duration_seconds,
                )
        text = (
            "録画を終了しました（Data未受信のため履歴から削除）。"
            if empty
            else f"録画が終了しました（{recorder.state}）。"
        )
        await self._record("system", {"text": text})
        await self._notify_state()
        await self._maybe_resume_after_finalize(recorder)

    async def _announce_waiting(self) -> None:
        # Hold the "restricted" status while a known members-only / age-restricted
        # broadcast is still up; otherwise announce ordinary waiting. Both keep
        # polling for a (new) normal broadcast on the same cadence.
        self.state = STATE_RESTRICTED if self._restricted_room_id is not None else STATE_WAITING
        self.steps = {step: "pending" for step in STEP_IDS}
        self.steps["request"] = "done"
        self.steps["live_check"] = "active"
        await self._notify_state()
        # 待機に入った瞬間は必ず1行出す(状態遷移)。以降の「まだ待っている」は
        # _log_still_waiting の間隔gate経由でしか出さない。
        self._last_wait_log_at = time.monotonic()
        logger.info(
            "%s for a live to start (poll interval %ss)",
            "restricted; watching" if self.state == STATE_RESTRICTED else "waiting",
            self._settings.get("live_check_interval"),
            extra={"event": "collector.live_wait_started",
                   "ctx": {"state": self.state,
                           "live_check_interval_seconds": self._settings.get("live_check_interval"),
                           "restricted_room_id": self._restricted_room_id}},
        )

    def _log_still_waiting(self, failures: int) -> None:
        """「まだLIVEが始まらない」進捗log。offlineは全監視の定常状態なので、無条件に出すと
        最頻出行になる。間隔gateを通し、DEBUG時のみ毎pollへ落ちる。録画が始まらない件の
        調査で「監視loopは生きていて、直近のprobeはいつで、連続失敗は何回か」を確定させる。"""
        interval = progress_interval_seconds(get_log_live_wait_interval_seconds())
        now = time.monotonic()
        if now - self._last_wait_log_at < interval:
            return
        self._last_wait_log_at = now
        logger.info(
            "still watching for a live to start (consecutive live-check failures: %d)",
            failures,
            extra={"event": "collector.live_wait_progressed",
                   "ctx": {"state": self.state, "consecutive_failures": failures,
                           "restricted_room_id": self._restricted_room_id}},
        )

    async def _wait_for_live_start(
        self, skip_first_check: bool = False, immediate_first: bool = False
    ) -> bool:
        waiting_announced = False
        failures = 0
        # 起動時・監視追加時の最初のcycleでは初回probeを即時(優先)で撃つ。再接続cycle
        # (skip_first_check)では従来どおり通常間隔に従う。
        use_priority = immediate_first and not skip_first_check
        if skip_first_check:
            waiting_announced = True
            await self._announce_waiting()
            await self._live_check_sleep(failures)
        while True:
            if self._stop_requested:
                self.state = STATE_DISCONNECTED
                return False
            try:
                if await self._resolve_live(priority=use_priority):
                    logger.info(
                        "live detected on room %s after %d failed live-check(s); "
                        "opening a session", self._resolved_room_id, failures,
                        extra={"event": "collector.live_detected",
                               "ctx": {"room_id": self._resolved_room_id,
                                       "consecutive_failures": failures,
                                       "priority_probe": use_priority}},
                    )
                    return True
                failures = 0
                # Resolved offline: a broadcast we were holding as restricted has
                # ended, so drop the hold and let the status revert to plain waiting.
                if self._restricted_room_id is not None:
                    logger.info(
                        "restricted broadcast on room %s has ended; releasing the hold",
                        self._restricted_room_id,
                        extra={"event": "collector.restricted_hold_released",
                               "ctx": {"room_id": self._restricted_room_id,
                                       "reason": "resolved_offline"}},
                    )
                    self._clear_restricted_hold()
                    waiting_announced = False
            except UserNotFoundError:
                # A missing LiveRoom module is NOT a reliable permanent signal: it
                # also appears on partial page renders, WAF partial passes, and
                # regional page variants. Terminating here killed monitors that
                # could never recover from a single false positive. Treat it like
                # offline — keep polling with backoff — so a real streamer is picked
                # up when they next go live; a genuinely invalid id simply keeps
                # returning here and is polled on the (backed-off) live-check cadence.
                failures += 1
                logger.warning(
                    "live page exposes no LiveRoom (consecutive=%d): the user may not "
                    "exist or the page rendered partially; continuing to watch", failures,
                    extra={"event": "collector.live_room_missing",
                           "ctx": {"consecutive_failures": failures}},
                )
            except LiveResolveBlocked as exc:
                # TikTok did not return parseable live state (WAF challenge
                # unsolved or transient). One concise line, then back off; the
                # browser resolver normally clears this on retry.
                failures += 1
                logger.warning(
                    "live check blocked (consecutive=%d): %s; backing off", failures, exc,
                    extra={"event": "collector.live_check_blocked",
                           "ctx": {"consecutive_failures": failures, "reason": str(exc)}},
                )
            except Exception as exc:
                failures += 1
                logger.warning(
                    "live check failed (consecutive=%d): %s", failures, exc, exc_info=True,
                    extra={"event": "collector.live_check_failed",
                           "ctx": {"consecutive_failures": failures,
                                   "exc_type": type(exc).__name__}},
                )
            # 即時probeは初回のみ。以降の再試行はWAF対策の通常間隔に従う。
            use_priority = False
            if not waiting_announced:
                waiting_announced = True
                await self._announce_waiting()
            else:
                self._log_still_waiting(failures)
            await self._live_check_sleep(failures)

    def _schedule_factor(self) -> float:
        """この配信者の、いまの時間帯のlive-check間隔倍率。過去のsession開始時刻から
        推定した配信されやすさで、確認間隔を詰める/広げる。総probe量は一様配分と等しく
        保たれ、上限は従来どおりProbeGate側のlive_check_max_per_minが持つ。"""
        if self._schedule_profiler is None:
            return 1.0
        return self._schedule_profiler.profile_for(self.unique_id).factor_at(time.time())

    async def _live_check_sleep(self, failures: int) -> None:
        base = self._settings.get("live_check_interval") * self._schedule_factor()
        multiplier = min(2 ** failures, LIVE_CHECK_BACKOFF_MAX_MULTIPLIER)
        jitter = 1.0 + random.uniform(-LIVE_CHECK_JITTER_RATIO, LIVE_CHECK_JITTER_RATIO)
        await asyncio.sleep(base * multiplier * jitter)

    async def _resolve_live(self, priority: bool = False) -> bool:
        """Resolve live status through the shared browser resolver, which passes
        the SlardarWAF JS challenge that blocks plain HTTP clients. A resolved
        room id means the user is currently live and is reused for connect() so
        the websocket path never re-scrapes www.tiktok.com; ``None`` means
        offline; UserNotFoundError and LiveResolveBlocked propagate. ``priority``
        requests an immediate probe (first check on startup / monitor add)."""
        await self._probe_gate.acquire(priority)
        resolution = await self._resolver.resolve(self.unique_id)
        await self._apply_resolved_owner(resolution)
        room_id = resolution.room_id
        if room_id:
            self._resolved_room_id = int(room_id)
            return True
        return False

    async def _apply_resolved_owner(self, resolution) -> None:
        """live判定のついでに取得したhostプロフィール(アイコン/表示名)をownerへ反映する。
        SIGI_STATEはoffline(status 4)でもhost profileを含むため、まだ一度もliveして
        いない配信者でも配信を待たずにアイコンを出せる。取得したavatarはunique_id単位の
        poolへ保存し、CDN URL失効後もbrowser proxyが描画できるようにする。変化時のみ
        snapshotをpushする。live接続後はより確実なroom_infoが上書きする。"""
        if resolution is None:
            return
        changed = False
        avatar = resolution.avatar or ""
        if avatar and self.owner.get("avatar") != avatar:
            self.owner["avatar"] = avatar
            self._persist_owner_avatar(avatar)
            changed = True
        if resolution.nickname and self.owner.get("nickname") in ("", self.unique_id):
            self.owner["nickname"] = resolution.nickname
            changed = True
        if changed:
            await self._notify_state()

    def _follow_owner_identity(self, user: Optional[dict]) -> bool:
        """配信中に配信者本人(不変数値ID一致)がコメント/ギフト等を出したら、その最新の
        表示名/アイコンで現在のsession owner identityを追従更新する(配信中の改名/アイコン
        変更の反映)。update_session_ownerは現session_idのみ更新するため過去sessionへは
        遡及しない。変化した時のみTrueを返し、呼び元がlive snapshotを再push する。"""
        if not user or not self._owner_id:
            return False
        if str(user.get("user_id") or "") != self._owner_id:
            return False
        changed = False
        nickname = (user.get("nickname") or "").strip()
        if nickname and nickname != "(unknown)" and self.owner.get("nickname") != nickname:
            self.owner["nickname"] = nickname
            changed = True
        avatar = user.get("avatar") or ""
        if avatar and self.owner.get("avatar") != avatar:
            self.owner["avatar"] = avatar
            self._persist_owner_avatar(avatar)
            changed = True
        if changed and self.session_id is not None:
            self._storage.update_session_owner(
                self.session_id, self.owner["nickname"], self.owner["avatar"],
                self._owner_id,
            )
        return changed

    async def _session_loop(self) -> str:
        while True:
            outcome, reason = await self._connect_once()
            if outcome != "transient":
                return outcome
            result = await self._wait_for_reconnect(reason)
            if result != "retry":
                return result

    async def _restricted_hold_continues(self) -> bool:
        """制限holdを続けるならTrue。期限が来るたびroom_infoを1度だけ撃ち直し、間隔は
        _arm_restricted_recheckのbackoffで段階的に広げる。TikTokは一時的に制限payloadを
        返すことがあり(同一room idが後で普通に接続できた実例あり)、再確認が無いとholdは
        その配信が終わるまで解けず、録画を丸ごと取り逃す。確認は診断と同じ未署名GET 1回
        なので署名serverは消費しない。"""
        if time.monotonic() < self._restricted_recheck_at:
            return True
        if not await self._restriction_lifted():
            self._restricted_recheck_count += 1
            next_delay = self._arm_restricted_recheck()
            logger.info(
                "restriction still in effect for room %s (attempt %s, next recheck in %ss)",
                self._restricted_room_id, self._restricted_recheck_count, next_delay,
                extra={"event": "collector.restriction_recheck_held",
                       "ctx": {"room_id": self._restricted_room_id,
                               "attempt": self._restricted_recheck_count,
                               "next_recheck_seconds": next_delay}},
            )
            return True
        # 制限が解けて再接続できる = 正常な状態遷移。ここをwarningにすると「録画できる状態に
        # 戻った」という良い知らせがwarning検索の結果を汚し、本物の劣化が埋もれる。
        logger.info(
            "restriction lifted for room %s after %s recheck(s); reconnecting",
            self._restricted_room_id, self._restricted_recheck_count,
            extra={"event": "collector.restriction_lifted",
                   "ctx": {"room_id": self._restricted_room_id,
                           "rechecks": self._restricted_recheck_count}},
        )
        self._clear_restricted_hold()
        return False

    async def _restriction_lifted(self) -> bool:
        """holdしているroomのroom_infoを1度だけ引き、実payloadが返るようになったかを返す。
        判定はTikTokLibのfetch_room_info自身の制限判定(promptsを含む/中身が空同然なら
        AgeRestrictedError)と同じ式にして、こちらだけ緩く見て無駄なconnectを撃たない。
        probe gateを通し、失敗時は「まだ制限中」とみなす(確認できない状態でconnectを
        撃つとholdの意味が無くなるため)。"""
        room_id = self._restricted_room_id
        if self._client is None or room_id is None:
            return False
        try:
            await self._probe_gate.acquire()
            url = WebDefaults.tiktok_webcast_url + "/room/info/"
            resp = await self._client.web.get(url=url, extra_params={"room_id": str(room_id)})
            data = (resp.json() or {}).get("data", {}) or {}
        except Exception:
            logger.warning(
                "restriction recheck failed for room %s; treating as still restricted",
                room_id, exc_info=True,
                extra={"event": "collector.restriction_recheck_failed",
                       "ctx": {"room_id": room_id}},
            )
            return False
        return "prompts" not in data and len(data) > 1

    def _mark_session_restricted(self) -> None:
        """Finalize the empty session row created for a broadcast that turned out to be
        unrecordable (members-only / age-restricted) with status "restricted", keeping it
        in history as the record of the failed attempt. The connect aborted before any
        owner/event/recording was stored, so the row carries the resolved room id and the
        zeroed stats; every count/statistic query filters the status out."""
        if self.session_id is None:
            return
        try:
            # 同一roomの制限行が既にあるなら行を増やさない。再確認で撃ち直したconnectが
            # また弾かれるたびに履歴が伸びるのを防ぐ。既存行の終了時刻だけ現在まで延ばし、
            # 「この配信はここまで録画できなかった」を1行で表す。
            existing = self._storage.find_restricted_session(
                self.unique_id, self._resolved_room_id
            )
            if existing is not None and existing != self.session_id:
                self._storage.delete_session(self.session_id)
                self._storage.extend_session_end(existing)
                logger.info(
                    "restricted attempt for room %s folded into session %s",
                    self._resolved_room_id, existing,
                    extra={"event": "collector.restricted_session_folded",
                           "ctx": {"room_id": self._resolved_room_id,
                                   "folded_into_session_id": existing,
                                   "discarded_session_id": self.session_id}},
                )
                self.session_id = None
                self._close_battle_raw()
                return
            # room_idはconnect成功時にしか書かれないので、ここで解決済みidを残す。
            # 制限がどのroomで起きたかを履歴だけで追えるようにするため。
            self._storage.update_session(
                self.session_id, STATE_RESTRICTED, self._resolved_room_id
            )
        except Exception:
            logger.exception(
                "failed to record restricted session %s", self.session_id,
                extra={"event": "collector.restricted_session_record_failed",
                       "ctx": {"room_id": self._resolved_room_id}},
            )
        self._persist_final()

    def _persist_progress(self) -> None:
        """進行中sessionのbattles/collab_windowsをDBへ中間永続化する(finalizeはしない)。
        非graceful終了(クラッシュ/電源断/例外escape)でもBattle窓・Collab窓と、それを窓境界に
        使うGift貢献の再構成が失われないよう、Battle終了・Collab終了・定期tickの契機で呼ぶ。
        save_battles/save_collab_windowsはsession単位のDELETE→INSERT全置換で冪等なため、
        未終了窓も終端補完して含めた現状スナップショットで安全に上書きできる。markerだけは
        追記(append_markers)で、dequeから溢れた分を消さない。best-effortで本流(受信ループ)は
        止めない。"""
        if self.session_id is None:
            return
        try:
            self._storage.save_battles(
                self.session_id,
                [self._battle_public(b) for b in self._battles.values() if not b.get("aborted")],
            )
            self._storage.save_collab_windows(self.session_id, self._collab_windows_public())
            self._storage.save_envelopes(self.session_id, self._envelopes)
            self._storage.append_markers(self.session_id, self._all_markers())
            self._last_checkpoint_at = time.time()
        except Exception:
            # 次のcheckpoint/finalizeが同じ内容を全置換で書き直すので自動回復する。
            logger.warning(
                "failed to checkpoint battle/collab windows; the next checkpoint will "
                "rewrite them", exc_info=True,
                extra={"event": "collector.checkpoint_failed",
                       "ctx": {"battles": len(self._battles),
                               "collab_open": len(self._collab_open),
                               "collab_windows": len(self._collab_windows)}},
            )

    def _persist_final(self) -> None:
        if self.session_id is None:
            return
        connected_at = self.stats.get("connected_at")
        duration_ms = (
            int((time.time() - connected_at) * 1000) if connected_at else None
        )
        try:
            # battles/collab_windowsはfinalize_sessionより先に永続化する。finalize_session末尾の
            # 全体解析cache計算(_refresh_session_analytics_locked)がこの2表を読むため、後だと
            # 空集合でcacheが焼き付き、確定sessionのBattle率/glove crit率/join_context帰属が
            # 恒久的に欠落する(cacheはversion一致・ended_at確定で再計算されない)。
            self._persist_progress()
            self._storage.finalize_session(
                self.session_id, self.state, self.stats, list(self.timeline), self._all_markers()
            )
        except Exception:
            # finalizeが落ちるとこのsessionは ended_at 未確定のまま残り、以後どこからも
            # 書き直されない(集計から恒久的に欠落する)。回復経路が無いのでerror。
            logger.error(
                "failed to persist session %s; it stays unfinalized and will be missing "
                "from aggregations", self.session_id, exc_info=True,
                extra={"event": "session.persist_failed",
                       "ctx": {"state": self.state}},
            )
        else:
            self._storage.record_ops_event(
                logger, "session.ended",
                f"配信のsessionを終了しました（状態 {self.state}）",
                severity=OPS_INFO,
                duration_ms=duration_ms,
                detail={"state": self.state,
                        "room_id": self.room_id,
                        "events_total": self.stats.get("events_total"),
                        "viewers_peak": self.stats.get("viewers_peak"),
                        "diamonds": self.stats.get("diamonds"),
                        "battles": self.stats.get("battles")},
            )
        self._close_battle_raw()
        self.session_id = None

    async def _connect_once(self) -> tuple:
        self._idle_disconnect = False
        self._forced_reason = None
        self._mark_data()
        # room_id was resolved via the browser; passing it (and skipping the
        # live check) keeps connect() off www.tiktok.com, so the WAF that
        # blocks the HTML scrape never touches the websocket path. room_info
        # is fetched from webcast.tiktok.com, which is not WAF-gated.
        connect_task = asyncio.ensure_future(
            self._client.connect(
                room_id=self._resolved_room_id,
                fetch_live_check=False,
                fetch_room_info=True,
            )
        )
        # A host network drop can leave the websocket half-open: connect() blocks
        # forever and no disconnect/live-end event fires, so the collector would
        # sit in CONNECTED showing stale data. The watchdog forces the connection
        # down once data stops arriving, dropping us into the reconnect path.
        watchdog = asyncio.ensure_future(self._idle_watchdog(connect_task))
        try:
            await connect_task
            if self._stop_requested:
                if self.state == STATE_CONNECTED:
                    self.state = STATE_DISCONNECTED
                return ("stopped", None)
            if self.state == STATE_ENDED:
                return ("ended", None)
            return ("transient", "LIVEとの接続が切断されました")
        except asyncio.CancelledError:
            if self._stop_requested:
                raise
            if self._idle_disconnect:
                return (
                    "transient",
                    self._forced_reason
                    or "TikTokからのData受信が途絶えたため再接続します（配信側の電波切れの可能性）。",
                )
            raise
        except UserOfflineError:
            try:
                offline_confirmed = await self._confirm_offline()
            except UserNotFoundError:
                # The live page lost its LiveRoom while we held the room open: the
                # broadcast is gone, not a permanent failure. End this session and
                # resume watching so a later live on this id still records.
                logger.info(
                    "live page no longer exposes LiveRoom; treating the broadcast as ended",
                    extra={"event": "collector.live_ended",
                           "ctx": {"reason": "live_room_gone_on_offline_confirm"}},
                )
                self.state = STATE_ENDED
                return ("ended", None)
            if offline_confirmed:
                logger.info(
                    "offline report confirmed by re-resolution; the broadcast has ended",
                    extra={"event": "collector.live_ended",
                           "ctx": {"reason": "offline_confirmed"}},
                )
                self.state = STATE_ENDED
                return ("ended", None)
            logger.info(
                "TikTok reported offline but re-resolution still shows a live; "
                "treating as transient and reconnecting",
                extra={"event": "collector.offline_unconfirmed", "ctx": {}},
            )
            return ("transient", "TikTokが一時的に未配信と応答しました（再確認では配信中）")
        except UserNotFoundError:
            # room_info reports no LiveRoom for a room we just resolved as live:
            # the broadcast ended or the page rendered partially. End this session
            # (non-terminal) and resume watching instead of killing the monitor.
            logger.info(
                "room_info reports no LiveRoom for a room that just resolved live; "
                "treating as ended and resuming the watch loop",
                extra={"event": "collector.live_ended",
                       "ctx": {"reason": "live_room_missing_in_room_info",
                               "room_id": self._resolved_room_id}},
            )
            self.state = STATE_ENDED
            return ("ended", None)
        except AgeRestrictedError:
            # Members-only and 18+ both surface here: fetch_room_info raises before any
            # sign request is spent (it precedes fetch_signed_websocket), so detection
            # is free. Treat as a non-terminal "restricted" outcome instead of failing,
            # so the watch loop keeps polling for a recordable broadcast.
            await self._log_restriction_diagnostics(self._resolved_room_id, "age_restricted_error")
            self.error_message = "メンバー限定または年齢制限のため録画できません（通常配信の開始を監視継続中）。"
            return ("restricted", "メンバー限定/年齢制限の配信")
        except TikTokLiveError as exc:
            logger.warning(
                "TikTokLive error on the live connection: %s; reconnecting", exc,
                exc_info=True,
                extra={"event": "collector.tiktok_error_raised",
                       "ctx": {"exc_type": type(exc).__name__}},
            )
            return ("transient", f"TikTok接続Error: {exc}")
        except httpx.TransportError as exc:
            # Timeout / network drop while fetching the signed websocket: an expected
            # transient hiccup, not a defect. Log one line (no traceback) and reconnect.
            logger.warning(
                "network error on the live connection: %s: %s; reconnecting",
                type(exc).__name__, exc,
                extra={"event": "collector.network_error_raised",
                       "ctx": {"exc_type": type(exc).__name__, "error": str(exc)}},
            )
            return ("transient", "TikTokとの通信が一時的にTimeoutしました（再接続します）")
        except ConnectionClosed as exc:
            # TikTok closes the live websocket without a close frame (broadcaster signal
            # loss, server-side drop, keepalive ping timeout): an expected transient, not
            # a defect. ConnectionClosed is the base of both ClosedError and ClosedOK, so
            # this covers abnormal and clean closes. Log one line (no traceback) and reconnect.
            logger.warning(
                "live websocket closed by TikTok: %s: %s; reconnecting",
                type(exc).__name__, exc,
                extra={"event": "collector.websocket_closed",
                       "ctx": {"exc_type": type(exc).__name__, "error": str(exc)}},
            )
            return ("transient", "LIVEとの接続が切断されました（再接続します）")
        except Exception as exc:
            # 上の型別分岐で拾えなかった=想定していない失敗。再接続で先へは進むが、原因が
            # 分類できていないこと自体が問題なので、既知transientと同じwarningに埋めない。
            logger.exception(
                "unclassified error on the live connection: %s; reconnecting", exc,
                extra={"event": "collector.unexpected_error_raised",
                       "ctx": {"exc_type": type(exc).__name__}},
            )
            return ("transient", f"接続Error: {exc}")
        finally:
            watchdog.cancel()
            try:
                await watchdog
            except asyncio.CancelledError:
                pass
            except Exception:
                # watchdogが死ぬと以後この接続のhalf-open検知が効かない(自動回復しない)。
                logger.error(
                    "idle watchdog raised; half-open detection is inactive for this "
                    "connection", exc_info=True,
                    extra={"event": "collector.watchdog_failed", "ctx": {}},
                )
            # Awaiting connect_task does not cancel it when our own coroutine is
            # cancelled (outer stop), so drop any still-running connect here.
            if not connect_task.done():
                connect_task.cancel()
                try:
                    await connect_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.debug(
                        "connect task raised while being cancelled", exc_info=True,
                        extra={"event": "collector.connect_cancel_failed", "ctx": {}},
                    )

    async def _idle_watchdog(self, connect_task: "asyncio.Future") -> None:
        """Force a reconnect when a live we believe is still connected stops making
        progress. Covers two silent-failure modes that fire no disconnect/live-end
        event: (1) the event websocket goes half-open (host network drop) so
        connect() never returns and no data arrives; (2) the video stream stalls
        while events keep flowing, so ffmpeg sits alive retrying a now-dead URL and
        never finalizes. Both recover only by tearing the connection down: the
        reconnect re-resolves room_info (a fresh stream URL) and resumes recording."""
        timeout = self._settings.get("connection_idle_timeout")
        stall_timeout = self._settings.get("recording_stall_timeout")
        interval = max(1.0, min(5.0, timeout / 3))
        while not connect_task.done():
            await asyncio.sleep(interval)
            # 進行中Battle/Collab窓を定期的に中間永続化する(未終了のままクラッシュしても
            # 直近checkpointまでは残る)。DELETE→INSERT全置換なのでinterval churnを避けて間引く。
            if (
                self.session_id is not None
                and time.time() - self._last_checkpoint_at >= _PROGRESS_CHECKPOINT_INTERVAL_SECONDS
                and (self._battles or self._collab_open or self._collab_windows)
            ):
                self._persist_progress()
            if connect_task.done() or self._stop_requested or self.state == STATE_ENDED:
                continue
            if self._last_data_at is None:
                continue
            idle = time.time() - self._last_data_at
            if idle >= timeout:
                self._storage.record_ops_event(
                    logger, "collector.stream_lost",
                    f"TikTokから{idle:.0f}秒 dataが届きません（状態 {self.state}）。"
                    f"再接続します（host側の回線断の可能性）",
                    severity=OPS_WARNING,
                    detail={"idle_seconds": round(idle, 1),
                            "timeout_seconds": timeout,
                            "state": self.state,
                            "room_id": self.room_id,
                            "recording_active": bool(
                                self.recorder is not None and self.recorder.is_active
                            )},
                )
                await self._force_reconnect(
                    connect_task,
                    "TikTokからのData受信が途絶えたため再接続します（配信側の電波切れの可能性）。",
                )
                return
            # Events are still arriving (idle < timeout); only the video may have
            # silently stalled. ffmpeg keeps retrying the dead URL and never exits,
            # so _maybe_resume_after_finalize cannot fire — a reconnect to re-resolve
            # the stream URL is the only recovery.
            if self._recording_stalled(stall_timeout):
                self._storage.record_ops_event(
                    logger, "collector.recording_stalled",
                    f"eventは届いているのに{stall_timeout}秒 映像が増えていません。"
                    f"stream URLを取り直すため再接続します",
                    severity=OPS_WARNING,
                    detail={"stall_timeout_seconds": stall_timeout,
                            "idle_seconds": round(idle, 1),
                            "room_id": self.room_id},
                )
                await self._force_reconnect(
                    connect_task,
                    "録画のstreamが停止したため再接続します（動画URLの取り直し）。",
                )
                return

    async def _force_reconnect(self, connect_task: "asyncio.Future", reason: str) -> None:
        """Tear down the current connection so _session_loop reconnects. Flags the
        teardown intentional (a transient outcome, not fatal) and records its cause
        so _connect_once surfaces it. Prefers a graceful close so the library frees
        the websocket; falls back to cancelling a blocked connect()."""
        self._idle_disconnect = True
        self._forced_reason = reason
        try:
            await asyncio.wait_for(self._client.disconnect(), timeout=5)
        except Exception:
            logger.warning(
                "watchdog graceful disconnect failed; cancelling the connect task instead",
                exc_info=True,
                extra={"event": "collector.disconnect_failed",
                       "ctx": {"phase": "watchdog", "reason": reason}},
            )
        if not connect_task.done():
            connect_task.cancel()

    def _recording_stalled(self, stall_timeout: float) -> bool:
        """True when an active, wanted recording has produced no new video for
        stall_timeout seconds. A recording that has not yet produced its first
        segment (progress token (0,0)) is ignored: that startup case is owned by the
        recorder's healthy-wait / empty-finalize path, and ignoring it also stops an
        endless reconnect loop when a re-resolved URL is itself dead — the
        replacement never advances past (0,0), so this never re-fires for it."""
        rec = self.recorder
        if rec is None or not rec.is_active or not self._recording_desired:
            self._rec_progress = None
            return False
        token = rec.progress_token()
        if token == (0, 0):
            return False
        now = time.time()
        if self._rec_progress != token:
            self._rec_progress = token
            self._rec_progress_at = now
            return False
        return (now - self._rec_progress_at) >= stall_timeout

    async def _confirm_offline(self) -> bool:
        await asyncio.sleep(5)
        if self._stop_requested:
            return True
        try:
            is_live = await self._resolve_live()
        except UserNotFoundError:
            raise
        except Exception as exc:
            logger.warning(
                "offline confirmation check failed (%s); treating the offline report as "
                "unconfirmed and reconnecting", exc, exc_info=True,
                extra={"event": "collector.offline_check_failed",
                       "ctx": {"exc_type": type(exc).__name__}},
            )
            return False
        return not is_live

    # Restriction-relevant room_info fields, logged when a restricted live is detected
    # (and when a connected room carries any of them) so members-only (live_sub_only)
    # can later be told apart from age-restricted (18+) from real captures, and the
    # single "restricted" status split accordingly. TODO: split once verified.
    _RESTRICTION_FIELDS = (
        "live_sub_only", "live_room_mode", "disable_preview_sub_only",
        "live_sub_only_tier", "live_sub_only_month", "status", "stream_status",
    )

    async def _log_restriction_diagnostics(self, room_id: Optional[int], source: str) -> None:
        """Best-effort: fetch the raw room_info payload (no sign consumed — web.get
        defaults sign_url=False) for a live we classified as restricted, and log the
        restriction-relevant fields. fetch_room_info() itself raises AgeRestrictedError
        and discards the body, so the raw GET is the only way to capture what TikTok
        returns for each restriction type. Never raises."""
        logger.warning(
            "restricted live detected (%s), recording is not possible for room %s",
            source, room_id,
            extra={"event": "collector.restriction_detected",
                   "ctx": {"source": source, "room_id": room_id}},
        )
        if self._client is None or room_id is None:
            return
        try:
            url = WebDefaults.tiktok_webcast_url + "/room/info/"
            resp = await self._client.web.get(url=url, extra_params={"room_id": str(room_id)})
            data = (resp.json() or {}).get("data", {}) or {}
        except Exception:
            logger.warning(
                "restriction diagnostics unavailable: raw room_info fetch failed for room %s",
                room_id, exc_info=True,
                extra={"event": "collector.restriction_diagnostics_failed",
                       "ctx": {"room_id": room_id}},
            )
            return
        diag = {k: data.get(k) for k in self._RESTRICTION_FIELDS}
        diag["has_prompts"] = "prompts" in data
        diag["data_keys"] = sorted(data.keys())
        logger.warning(
            "restriction diagnostics for room %s: %s", room_id, diag,
            extra={"event": "collector.restriction_diagnosed",
                   "ctx": {"room_id": room_id, **diag}},
        )
        # 18+ / メンバー限定 / レート制限は _RESTRICTION_FIELDS が全てNoneで返るため
        # フラグでは区別できず、TikTokが返す message / prompts の文言だけが手がかりになる。
        # 種別が判明すれば単一の "restricted" statusを分割できる(上のTODO)。
        # 巨大payloadでlogを潰さないよう切り詰めて出す。
        text = json.dumps(
            {"message": data.get("message"), "prompts": data.get("prompts")},
            ensure_ascii=False,
            default=str,
        )
        limit = get_log_restriction_text_chars()
        truncated = len(text) > limit
        if truncated:
            text = text[:limit] + "…(truncated)"
        logger.warning(
            "restriction payload for room %s: %s", room_id, text,
            extra={"event": "collector.restriction_payload_captured",
                   "ctx": {"room_id": room_id, "payload": text, "truncated": truncated}},
        )

    def _log_connected_restriction_fields(self) -> None:
        """Log restriction-relevant room_info fields when a *connected* room carries
        any of them. A members-only stream that still lets us connect (rather than
        raising AgeRestrictedError) would surface its live_sub_only flags here — the
        data needed to decide whether 'restricted' must also cover connectable
        members-only rooms. Best-effort; only logs when a flag is actually set."""
        flags = {k: self._room_info.get(k) for k in self._RESTRICTION_FIELDS}
        if any(flags.get(k) for k in ("live_sub_only", "live_room_mode", "disable_preview_sub_only")):
            logger.warning(
                "connected room %s carries sub-only flags: %s", self.room_id, flags,
                extra={"event": "collector.sub_only_flags_observed",
                       "ctx": {"room_id": self.room_id, **flags}},
            )

    async def _wait_for_reconnect(self, reason: str) -> str:
        if self._stop_requested:
            self.state = STATE_DISCONNECTED
            return "stopped"
        max_attempts = self._settings.get("reconnect_max_attempts")
        self._reconnect_attempt += 1
        if self._reconnect_attempt > max_attempts:
            # Reconnect targets the broadcast's webcast WebSocket, and each attempt
            # also spends one EulerStream sign request. A sign-server rate limit or a
            # prolonged host network drop is transient, so terminating the monitor
            # permanently here made it unrecoverable. Instead fall back to the browser
            # watch loop: it re-resolves live state for FREE (no sign request) and only
            # spends another sign request once the user is confirmed live again. The
            # sign-request budget is therefore never burned while waiting, and the
            # monitor reconnects on its own when the broadcast/connection recovers.
            self._storage.record_ops_event(
                logger, "collector.reconnect_exhausted",
                f"再接続を{max_attempts}回試みましたが繋がりませんでした。終了せず"
                f"監視loopへ戻ります（最後の理由: {reason}）",
                severity=OPS_WARNING,
                detail={"max_attempts": max_attempts, "reason": reason,
                        "room_id": self.room_id},
            )
            await self._record(
                "system",
                {
                    "text": (
                        f"再接続が{max_attempts}回失敗したため監視待機に戻ります"
                        f"（配信再開/接続回復を監視継続。待機中は署名リクエストを消費しません）。"
                        f"最後の原因: {reason}"
                    )
                },
            )
            self.state = STATE_ENDED
            return "ended"
        delay = min(
            self._settings.get("reconnect_base_delay") * (2 ** (self._reconnect_attempt - 1)),
            self._settings.get("reconnect_max_delay"),
        )
        self.state = STATE_RECONNECTING
        self.steps["websocket"] = "active"
        self.steps["receiving"] = "pending"
        logger.info(
            "reconnecting (attempt %d/%d) in %.1fs: %s",
            self._reconnect_attempt, max_attempts, delay, reason,
            extra={"event": "collector.reconnect_scheduled",
                   "ctx": {"attempt": self._reconnect_attempt,
                           "max_attempts": max_attempts,
                           "delay_seconds": round(delay, 1),
                           "reason": reason}},
        )
        await self._notify_state()
        await self._record(
            "system",
            {
                "text": f"再接続します ({self._reconnect_attempt}/{max_attempts}回目、{delay:.0f}秒後)。原因: {reason}"
            },
        )
        await asyncio.sleep(delay)
        if self._stop_requested:
            self.state = STATE_DISCONNECTED
            return "stopped"
        if await self._broadcast_ended_during_reconnect():
            self.state = STATE_ENDED
            return "ended"
        self._client = self._build_client(self.unique_id)
        return "retry"

    async def _broadcast_ended_during_reconnect(self) -> bool:
        """True when the broadcast we are reconnecting to has ended, so the caller
        stops retrying and falls back to the watch loop. Every reconnect attempt
        spends one sign request, and a dead room can never be signed again, so the
        remaining attempts are a guaranteed miss; one free live re-resolve ends the
        session instead of paying that budget out.

        Only a definitive offline resolution ends the session. _resolve_live raises
        (LiveResolveBlocked / UserNotFoundError) for every ambiguous page - WAF
        stubs, partial renders, regional variants - so those never reach the False
        branch, and treating them as 'unknown, keep retrying' keeps a real
        broadcast from being dropped on one unreadable page. Same conservative
        stance as _restricted_hold_continues."""
        attempt = self._reconnect_attempt
        if attempt < RECONNECT_LIVE_RECHECK_AFTER:
            return False
        if (attempt - RECONNECT_LIVE_RECHECK_AFTER) % RECONNECT_LIVE_RECHECK_EVERY:
            return False
        # _resolve_live overwrites _resolved_room_id, which _connect_once connects
        # to. A host who ended and restarted resolves live again on a *new* room,
        # so retrying would pull the next broadcast into this session's records.
        # That restart is an end for this session too: close it and let the watch
        # loop open a fresh session for the new room.
        session_room = self._resolved_room_id
        try:
            if await self._resolve_live() and self._resolved_room_id == session_room:
                return False
        except Exception as exc:
            logger.info(
                "reconnect live re-check inconclusive on attempt %d (%s); "
                "continuing to reconnect", attempt, exc,
                extra={"event": "collector.reconnect_livecheck_inconclusive",
                       "ctx": {"attempt": attempt, "exc_type": type(exc).__name__}},
            )
            return False
        restarted = self._resolved_room_id is not None
        self._storage.record_ops_event(
            logger, "collector.reconnect_broadcast_ended",
            f"再接続中（{attempt}回目）に配信が"
            f"{'新しいroomで再開' if restarted else '終了'}しました。"
            f"sign requestを浪費しないよう監視loopへ戻ります",
            severity=OPS_INFO,
            detail={"attempt": attempt, "room_id": session_room,
                    "restarted": restarted,
                    "new_room_id": self._resolved_room_id if restarted else None},
        )
        await self._record(
            "system",
            {"text": ("配信が再開され別Roomになっていたため再接続を打ち切り、監視待機に戻ります"
                      if restarted else
                      "配信が終了していたため再接続を打ち切り、監視待機に戻ります")
                     + "（署名リクエストの無駄撃ちを回避）。"},
        )
        return True

    def _fail(self, step: str, message: str) -> None:
        self.steps[step] = "failed"
        self.state = STATE_ERROR
        self.error_message = message
        logger.error(
            "collector failed at step %s: %s", step, message,
            extra={"event": "collector.step_failed",
                   "ctx": {"step": step, "message": message}},
        )

    def _build_client(self, unique_id: str) -> TikTokLiveClient:
        client = TikTokLiveClient(unique_id=unique_id)
        client.add_listener(ConnectEvent, self._on_connect)
        client.add_listener(DisconnectEvent, self._on_disconnect)
        client.add_listener(LiveEndEvent, self._on_live_end)
        client.add_listener(GiftEvent, self._on_gift)
        client.add_listener(CommentEvent, self._on_comment)
        client.add_listener(LikeEvent, self._on_like)
        client.add_listener(FollowEvent, self._on_follow)
        client.add_listener(ShareEvent, self._on_share)
        client.add_listener(JoinEvent, self._on_join)
        client.add_listener(SubscribeEvent, self._on_subscribe)
        client.add_listener(RoomUserSeqEvent, self._on_room_user)
        client.add_listener(LinkMicBattleEvent, self._on_battle)
        client.add_listener(LinkMicArmiesEvent, self._on_armies)
        client.add_listener(LinkLayerEvent, self._on_link_layer)
        # 入室ドライバ交絡のmask源。ポータル(他配信からの誘導流入)・宝箱(红包)は
        # 入室が構造的に押し上がる窓なので、marker(battleと同じ扱い)に残して解析の
        # placeboから除外する。scoreへは算入しない。
        client.add_listener(PortalEvent, self._on_portal)
        client.add_listener(EnvelopePortalEvent, self._on_portal)
        client.add_listener(EnvelopeEvent, self._on_envelope)
        # 検証用: 現状未使用のBattle系eventを生のまま記録する診断listener群。
        # 設定OFF / simulation時は _dump_battle_raw が即returnするため無害。
        client.add_listener(LinkmicBattleTaskEvent, self._on_battle_task)
        client.add_listener(LinkMicBattleItemCardEvent, self._on_item_card)
        for kind, evt in (
            ("LinkmicBattleNotice", LinkmicBattleNoticeEvent),
            ("LinkMicBattleVictoryLap", LinkMicBattleVictoryLapEvent),
            ("LinkMicBattlePunishFinish", LinkMicBattlePunishFinishEvent),
        ):
            client.add_listener(evt, lambda event, k=kind: self._dump_battle_raw(k, event))
        # league_probe診断: 配信者リーグ帯(A1/B1等)がどのランキング系eventに載るかを
        # 特定するため、rank関連eventを生のまま走査してログ出力する。設定OFF時は即return。
        for evt in (
            RankUpdateEvent,
            RankTextEvent,
            RankToastEvent,
            WeeklyRankRewardEvent,
            HourlyRankRewardEvent,
        ):
            client.add_listener(
                evt, lambda event, name=evt.__name__: self._probe_league_event(name, event)
            )
        # 全event種別の生サンプラー(既存handlerと並行、shape重複を除外して1件ずつ保存)。
        # 設定OFF / simulation時は _capture_sample が即returnする。
        for kind, evt in (
            ("GiftEvent", GiftEvent),
            ("CommentEvent", CommentEvent),
            ("LikeEvent", LikeEvent),
            ("FollowEvent", FollowEvent),
            ("ShareEvent", ShareEvent),
            ("JoinEvent", JoinEvent),
            ("SubscribeEvent", SubscribeEvent),
            ("RoomUserSeqEvent", RoomUserSeqEvent),
            ("LinkMicBattleEvent", LinkMicBattleEvent),
            ("LinkMicArmiesEvent", LinkMicArmiesEvent),
            ("LinkMicBattleItemCardEvent", LinkMicBattleItemCardEvent),
            ("LinkmicBattleNoticeEvent", LinkmicBattleNoticeEvent),
            ("LinkmicBattleTaskEvent", LinkmicBattleTaskEvent),
            ("LinkMicBattleVictoryLapEvent", LinkMicBattleVictoryLapEvent),
            ("LinkMicBattlePunishFinishEvent", LinkMicBattlePunishFinishEvent),
            # コラボ(非BattleのLinkMic)窓収集の実装確定に向けた診断capture(doc §14)。
            # LinkLayer=channel create/finish/join/leave/roster(user_list)の権威的signal、
            # LinkState=user_states snapshot、LinkMicMethod=m_type/duration。実roomで
            # どのfieldが実際に埋まるか(message_type実値・rosterの型・host識別)を実測する。
            ("LinkLayerEvent", LinkLayerEvent),
            ("LinkStateEvent", LinkStateEvent),
            ("LinkMicMethodEvent", LinkMicMethodEvent),
            ("LinkLayoutEvent", LinkLayoutEvent),
            ("ConnectEvent", ConnectEvent),
            ("LiveEndEvent", LiveEndEvent),
            # 入室ドライバ交絡の診断capture(実roomで発火有無・頻度・payload実値を実測)。
            # portal/envelopeはmarker化済+専用handlerでcapture済のため、ここには含めない。
            # goody_bag/boost/hot_room/special_pushは「入室を押す」仮説段階のため、まずは
            # 実測してからmask源に昇格するか判断する。unknownは未復号messageの型特定用。
            ("GoodyBagEvent", GoodyBagEvent),
            ("BoostCardEvent", BoostCardEvent),
            ("HotRoomEvent", HotRoomEvent),
            ("SpecialPushEvent", SpecialPushEvent),
            ("UnknownEvent", UnknownEvent),
        ):
            client.add_listener(evt, lambda event, k=kind: self._capture_sample(k, event))
        return client

    async def _apply_league(self, league: str) -> None:
        """接続時に取得したリーグ帯をsession(配信単位)へ保存し、live snapshotにも反映する。
        空値・変化なしなら何もしない。best-effortで本流(gift icon取得)は止めない。"""
        if not league or league == self._league:
            return
        self._league = league
        self.owner["league"] = league
        try:
            if self.session_id is not None:
                self._storage.update_session_league(self.session_id, league)
        except Exception:
            # 次のconnectで取り直す。sessionのleague列が空のままになるだけ。
            logger.warning(
                "failed to persist the streamer league band %s for this session", league,
                exc_info=True,
                extra={"event": "collector.league_persist_failed",
                       "ctx": {"league": league}},
            )
        logger.info(
            "streamer league band captured: %s", league,
            extra={"event": "collector.league_captured", "ctx": {"league": league}},
        )
        await self._notify_state()

    def _league_enabled(self) -> bool:
        return bool(self._settings.get("league_probe"))

    def _scan_league(self, source: str, obj: Any) -> None:
        """診断: dict/listを再帰走査し、名前がleague/ranking/grade系のfield、または
        'A1'/'B1'形式の文字列値を [league-probe] としてログ出力する。どのDataに配信者
        リーグが載るかを特定するための計測で、league_probe設定ON時のみ呼ぶ。best-effort。"""
        try:
            hits: list = []
            self._collect_league_hits(obj, "", hits)
            if not hits:
                return
            for path, value in hits:
                logger.info(
                    "[league-probe] %s: %s = %r", source, path, value,
                    extra={"event": "collector.league_probe_hit",
                           "ctx": {"source": source, "path": path, "value": value}},
                )
        except Exception:
            logger.warning(
                "[league-probe] scan failed for %s; this probe yields no hits", source,
                exc_info=True,
                extra={"event": "collector.league_probe_failed",
                       "ctx": {"source": source}},
            )

    def _collect_league_hits(self, obj: Any, path: str, hits: list) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                child = f"{path}.{key}" if path else str(key)
                if (
                    isinstance(value, (str, int))
                    and value not in ("", 0)
                    and _LEAGUE_KEY_RE.search(str(key))
                ):
                    hits.append((child, value))
                elif isinstance(value, str) and _LEAGUE_VALUE_RE.match(value):
                    hits.append((child, value))
                self._collect_league_hits(value, child, hits)
        elif isinstance(obj, (list, tuple)):
            for i, value in enumerate(obj):
                self._collect_league_hits(value, f"{path}[{i}]", hits)

    def _probe_league_event(self, name: str, event: Any) -> None:
        """rank関連eventを辞書化して league scanner にかける。生protoは未定義enum値に
        強い safe_event_to_dict でJSON化してから走査する(field名はsnakeだが
        _LEAGUE_KEY_RE がsnake/camel両対応)。"""
        if not self._league_enabled():
            return
        if hasattr(event, "to_dict"):
            payload = safe_event_to_dict(event)
        else:
            payload = event
        self._scan_league(f"event:{name}", payload)

    def _capture_sample(self, kind: str, event: Any) -> None:
        """実配信サンプラーへ1件渡す。設定OFF / simulation / 未生成時は何もしない。
        識別のためsession/unique_idを付与する。best-effortで本流は止めない。"""
        if self._sampler is None or not self._settings.get("sample_capture"):
            return
        self._sampler.capture(
            kind, event,
            {"session_id": self.session_id, "unique_id": self.unique_id},
        )

    async def _on_connect(self, event: ConnectEvent) -> None:
        # A reconnect is a connection re-established after the live was already up in
        # this session — not merely a first connect that needed retries to succeed.
        # Keying off _reconnect_attempt would misread transient first-connect failures
        # (e.g. Sign API 500) as a reconnect and skip auto-record entirely.
        reconnected = self._ever_connected
        self._ever_connected = True
        self._reconnect_attempt = 0
        # We reached a recordable broadcast; any prior restriction hold no longer applies.
        self._clear_restricted_hold()
        self.state = STATE_CONNECTED
        self.steps["live_check"] = "done"
        self.steps["websocket"] = "done"
        self.steps["receiving"] = "active"
        self.room_id = self._client.room_id if self._client else None
        try:
            self._room_info = (self._client.room_info if self._client else None) or {}
            self._log_connected_restriction_fields()
            if self._league_enabled():
                self._scan_league("room_info", self._room_info)
            owner = self._room_info.get("owner") or {}
            self._owner_id = str(owner.get("id") or "")
            self.owner = {
                "unique_id": owner.get("display_id") or self.unique_id,
                "nickname": owner.get("nickname") or self.unique_id,
                "avatar": _best_owner_image(owner),
                "league": self._league,
            }
            if self.session_id is not None:
                self._storage.update_session_owner(
                    self.session_id, self.owner["nickname"], self.owner["avatar"],
                    self._owner_id,
                )
            self._persist_owner_avatar(self.owner["avatar"])
            self._precache_gift_icons()
        except Exception:
            # _owner_id が立たないとBattleのscore追跡が丸ごと無効化され、このsessionの
            # 間ずっと復旧しない(room_infoは再接続まで取り直さない)。
            logger.error(
                "failed to read the room owner from room_info; battle score tracking "
                "and owner identity will be missing for this session", exc_info=True,
                extra={"event": "collector.owner_read_failed",
                       "ctx": {"room_id": self.room_id,
                               "room_info_keys": sorted(self._room_info.keys())}},
            )
        self._persist_live_create_time()
        if self.stats["connected_at"] is None:
            self.stats["connected_at"] = time.time()
        self._add_conn_marker("reconnect" if reconnected else "connect", "再接続" if reconnected else "LIVE接続")
        if self.session_id is not None:
            self._storage.update_session(self.session_id, STATE_CONNECTED, self.room_id)
        self._storage.record_ops_event(
            logger, "collector.connected",
            f"eventの受信に{'再接続' if reconnected else '接続'}しました"
            f"（live websocket、room {self.room_id}）",
            severity=OPS_INFO,
            detail={"room_id": self.room_id,
                    "reconnected": reconnected,
                    "owner_id": self._owner_id or None,
                    "record_video": self.record_video,
                    "recording_desired": self._recording_desired},
        )
        await self._notify_state()
        await self._record(
            "system",
            {"text": f"@{self.unique_id} のLIVE (Room {self.room_id}) に接続しました。"},
        )
        if reconnected:
            # The host re-broadcasts with a freshly issued stream URL after a drop,
            # so any ffmpeg still retrying the now-dead URL is dropped and recording
            # is re-established against the new room_info. Resume only a recording
            # that was in effect before the drop (auto, or a manual start not stopped).
            if self._recording_desired and ffmpeg_available():
                logger.info(
                    "resuming the recording after a reconnect against the freshly "
                    "issued stream URL",
                    extra={"event": "collector.recording_resume_started",
                           "ctx": {"room_id": self.room_id}},
                )
                await self._resume_recording()
        elif self.record_video and self._settings.get("auto_record") and ffmpeg_available():
            try:
                await self.start_recording()
            except Exception as exc:
                # 自動録画は以後この接続では再試行されない(次のreconnect/liveまで無い)。
                logger.warning(
                    "auto-record failed to start: %s; this broadcast will be collected "
                    "without video unless recording is started manually", exc,
                    exc_info=True,
                    extra={"event": "collector.auto_record_failed",
                           "ctx": {"exc_type": type(exc).__name__, "room_id": self.room_id}},
                )

    def _apply_cached_owner(self) -> None:
        """live未接続(待機/アイドル)でもキャッシュ済みのアイコン/表示名を出すため、最後に
        判明したowner identityをownerへ補完する。identity系(avatar/nickname)は
        point-in-time→永続sessionへfallbackする方針。live接続後はroom_infoが上書きする。
        avatarのURLは期限切れでも、browser proxyがunique_id単位のpoolへfallbackして描画する。"""
        if self._storage is None:
            return
        cached = self._storage.latest_owner(self.unique_id)
        if cached.get("avatar") and not self.owner.get("avatar"):
            self.owner["avatar"] = cached["avatar"]
        if cached.get("nickname") and self.owner.get("nickname") in ("", self.unique_id):
            self.owner["nickname"] = cached["nickname"]

    def _persist_owner_avatar(self, url: str) -> None:
        """Download the streamer avatar into the shared by-id pool in the background
        so 履歴 / browser proxy / video burn-in can all render it after the signed
        CDN URL expires. Keyed by the monitored unique_id — the id the browser /
        history pass to the proxy (sessions.unique_id) and the same per-user pool
        the commenter avatars use. Non-blocking: connect must not wait on a CDN
        round-trip."""
        if not url or self._avatar_pool is None:
            return
        owner_id = self.unique_id
        # Skip scheduling when the pool already holds this (or a better) avatar for the
        # owner; a re-signed same-rendition URL on every reconnect must not re-fetch.
        if not self._avatar_pool.needs_update(owner_id, url):
            return

        async def _run() -> None:
            try:
                await self._avatar_pool.persist(owner_id, url)
            except Exception:
                logger.warning(
                    "owner avatar persist failed; history and burn-in will fall back "
                    "to the initial-letter avatar for this streamer", exc_info=True,
                    extra={"event": "collector.avatar_persist_failed",
                           "ctx": {"user_key": owner_id, "scope": "owner"}},
                )

        # 単一属性だと連続呼び出し(resolver→connect)で先行taskへの強参照が消え、
        # 完了前にGCで破棄され得る。他のpersist系と同じくset+done_callbackで保持する。
        task = asyncio.create_task(_run())
        self._avatar_tasks.add(task)
        task.add_done_callback(self._avatar_tasks.discard)

    def _persist_gift_icon(self, gift_id: int, url: str) -> None:
        """Cache a gift icon to disk in the background while its URL is fresh, so
        the burn-in pipeline can composite it after the CDN URL would expire.
        Non-blocking: event handling must not wait on a CDN round-trip."""
        if not gift_id or not url or self._gift_icons is None:
            return
        if self._gift_icons.has(gift_id):
            return

        async def _run() -> None:
            try:
                await self._gift_icons.persist(gift_id, url)
            except Exception:
                logger.warning(
                    "gift icon persist failed for gift %s; the burn-in will render this "
                    "gift without its icon", gift_id, exc_info=True,
                    extra={"event": "collector.gift_icon_persist_failed",
                           "ctx": {"gift_id": gift_id}},
                )

        task = asyncio.create_task(_run())
        self._gift_icon_tasks.add(task)
        task.add_done_callback(self._gift_icon_tasks.discard)

    def _persist_badge(self, url: str) -> None:
        """Pre-fetch a Lv/grade badge image through the avatar proxy while its signed
        URL is fresh. The proxy caches by URL path on disk, so once fetched the badge
        survives CDN signature expiry and renders in 履歴 even if it was never shown
        live. Avatar/gift-iconと同じcapture時取得。Non-blocking & best-effort."""
        if not url or self._avatar_proxy is None:
            return
        if url in self._seen_badges or not self._avatar_proxy.is_allowed(url):
            return
        self._seen_badges.add(url)

        async def _run() -> None:
            try:
                await self._avatar_proxy.fetch(url)
            except Exception:
                logger.warning(
                    "badge prefetch failed; the badge will be missing in history once "
                    "its CDN signature expires", exc_info=True,
                    extra={"event": "collector.badge_prefetch_failed",
                           "ctx": {"badge_url": url}},
                )

        task = asyncio.create_task(_run())
        self._badge_tasks.add(task)
        task.add_done_callback(self._badge_tasks.discard)

    def _persist_user_avatar(self, user: dict) -> None:
        """Pool any event user's avatar, keyed by user (unique_id, else nickname).
        Used as the single capture point for every history user."""
        if not isinstance(user, dict):
            return
        self._persist_avatar(user.get("unique_id") or user.get("nickname"), user.get("avatar"))

    def _persist_avatar(self, user_key: Optional[str], url: Optional[str]) -> None:
        """Cache a user's avatar into the shared by-id pool in the background while
        its URL is fresh, so the burn-in pipeline can composite the real avatar after
        the CDN URL would 403, and the browser proxy / history can fall back to it by
        id. Keyed by user_key (unique_id, else nickname) — the same key the burn-in
        side and the proxy derive for that user. Non-blocking."""
        if self._avatar_pool is None or not user_key or not url:
            return
        # Consult the pool's identity/resolution check instead of a plain "already have
        # one": this re-fetches only when the avatar is a higher resolution or the user
        # changed it, and skips the common re-signed same-image URL — so a task is not
        # spawned per comment for a known, unchanged user.
        if not self._avatar_pool.needs_update(user_key, url):
            return

        async def _run() -> None:
            try:
                await self._avatar_pool.persist(user_key, url)
            except Exception:
                logger.warning(
                    "user avatar persist failed for %s; history and burn-in will fall "
                    "back to the initial-letter avatar", user_key, exc_info=True,
                    extra={"event": "collector.avatar_persist_failed",
                           "ctx": {"user_key": user_key, "scope": "user"}},
                )

        task = asyncio.create_task(_run())
        self._avatar_pool_tasks.add(task)
        task.add_done_callback(self._avatar_pool_tasks.discard)

    def _precache_gift_icons(self) -> None:
        """At connect, pre-cache the room's full gift catalogue so every icon is
        saved while fresh — even gifts not yet sent in this session. Best-effort,
        non-blocking."""
        if self._gift_icons is None or self._client is None:
            return

        async def _run() -> None:
            try:
                gift_list = await self._client.web.fetch_gift_list()
                if self._league_enabled():
                    self._scan_league("gift_list", gift_list)
                await self._apply_league(_extract_league(gift_list))
                n = await self._gift_icons.persist_gift_list(gift_list)
                if n:
                    logger.info(
                        "pre-cached %d gift icons from the room gift catalogue", n,
                        extra={"event": "collector.gift_icons_precached",
                               "ctx": {"count": n}},
                    )
            except Exception:
                logger.warning(
                    "gift list pre-cache failed; gift icons will only be cached as "
                    "gifts arrive", exc_info=True,
                    extra={"event": "collector.gift_list_precache_failed", "ctx": {}},
                )

        task = asyncio.create_task(_run())
        self._gift_icon_tasks.add(task)
        task.add_done_callback(self._gift_icon_tasks.discard)

    async def _resume_recording(self) -> None:
        old = self.recorder
        if old is not None and old.is_active:
            try:
                # wait=False: ffmpeg is terminated now, but the old segments are
                # concatenated to mp4 in the background so the new recording can
                # start immediately against the fresh stream URL.
                await old.stop()
            except Exception:
                # 旧ffmpegが残ると死んだURLを掴んだまま回り続ける。置き換えは続行するが、
                # 残留processの有無はここでしか分からない。
                logger.warning(
                    "failed to stop the stale recorder before resuming; a previous "
                    "ffmpeg may still be running against the dead URL", exc_info=True,
                    extra={"event": "collector.recording_stop_failed",
                           "ctx": {"phase": "resume"}},
                )
        await self._start_replacement_recording()

    async def _start_replacement_recording(self) -> None:
        # Detach the prior recorder (its finalize task runs on independently and
        # persists via its own recording_id) so start_recording's active-guard
        # sees a clean slate even while the old one is still finalizing.
        self.recorder = None
        try:
            await self.start_recording()
        except Exception as exc:
            # 置き換え起動の失敗。empty finalize経由なら回復loopが再入するが、
            # bytes>0からのresumeではここが最後の試行になる。
            logger.warning(
                "failed to start the replacement recording: %s", exc, exc_info=True,
                extra={"event": "collector.replacement_recording_failed",
                       "ctx": {"exc_type": type(exc).__name__}},
            )

    async def _refresh_room_info(self) -> bool:
        """Re-fetch room_info (and with it a fresh stream pull URL) without a
        websocket reconnect. Uses web.fetch_room_info, which is an unsigned GET
        (sign_url=False), so it spends no sign request — recovery can re-resolve the
        URL as often as needed without draining the sign API. Updates self._room_info
        in place and returns True on success. AgeRestrictedError / fetch failures are
        treated as 'no fresh URL right now' (False); the caller backs off and retries."""
        client = self._client
        if client is None:
            return False
        try:
            info = await client.web.fetch_room_info(room_id=self.room_id or self._resolved_room_id)
        except AgeRestrictedError:
            logger.warning(
                "room_info refresh rejected as restricted; no fresh stream URL is "
                "available right now",
                extra={"event": "collector.room_info_refresh_failed",
                       "ctx": {"reason": "age_restricted",
                               "room_id": self.room_id or self._resolved_room_id}},
            )
            return False
        except Exception as exc:
            logger.warning(
                "room_info refresh failed: %s; no fresh stream URL this round",
                exc, exc_info=True,
                extra={"event": "collector.room_info_refresh_failed",
                       "ctx": {"reason": "fetch_failed",
                               "exc_type": type(exc).__name__,
                               "room_id": self.room_id or self._resolved_room_id}},
            )
            return False
        if not info:
            logger.warning(
                "room_info refresh returned an empty payload; no fresh stream URL "
                "this round",
                extra={"event": "collector.room_info_refresh_failed",
                       "ctx": {"reason": "empty_payload",
                               "room_id": self.room_id or self._resolved_room_id}},
            )
            return False
        self._room_info = info
        return True

    async def _maybe_resume_after_finalize(self, recorder: Recorder) -> None:
        """Re-establish recording after one ends on its own while the live is still
        connected — the video pull URL dropped (or was dead at start) but events keep
        flowing, so no websocket reconnect fires to trigger the reconnect-path resume.

        Two cases, both re-resolve a fresh stream URL first (self._room_info still
        holds the stale/dead URL that the finished recording used):

        - Captured data then stopped: settle briefly (let a concurrent websocket drop
          surface first) and relaunch once.
        - Captured nothing (empty): the URL was dead at start or a host re-broadcast
          reissued it. Relaunch with backoff and keep retrying until recording is
          re-established, the live ends, or the user stops — driven by each empty
          finalize re-entering here. Re-resolution is sign-free (see _refresh_room_info),
          so this follows the host for as long as they stay live without spending sign
          requests. The backoff only throttles fast-fail rounds (no fresh URL yet); a
          round that actually runs ffmpeg is self-throttled by the recorder's attempts."""
        if recorder is not self.recorder or not self._recording_desired:
            return
        if self.state != STATE_CONNECTED or self._stop_requested:
            return

        if recorder.snapshot().get("bytes", 0) > 0:
            await asyncio.sleep(RESUME_SETTLE_DELAY)
            if recorder is not self.recorder or not self._recording_desired:
                return
            if self.state != STATE_CONNECTED or self._stop_requested:
                return
            logger.info(
                "recording ended on its own while the live is still connected; "
                "re-resolving the stream URL and resuming",
                extra={"event": "collector.recording_resume_started",
                       "ctx": {"reason": "finalized_while_live",
                               "size_bytes": recorder.snapshot().get("bytes", 0)}},
            )
            await self._refresh_room_info()
            await self._start_replacement_recording()
            return

        # Empty finalize: dead/stale stream URL while events still flow. Nothing else
        # will retry this (the stall watchdog ignores a recording that never produced a
        # segment, and no websocket reconnect fires), so recover here.
        if self._recovering:
            return
        self._recovering = True
        logger.warning(
            "recording captured nothing while the live is still connected; starting the "
            "stream-URL recovery loop",
            extra={"event": "collector.recording_recovery_started",
                   "ctx": {"room_id": self.room_id,
                           "recorder_state": recorder.state,
                           "error": recorder.error}},
        )
        rounds = 0
        try:
            delay = RECORDING_RECOVERY_BACKOFF_MIN
            while (not self._stop_requested and self._recording_desired
                   and self.state == STATE_CONNECTED):
                if self.recorder is not None and self.recorder.is_active:
                    return
                if await self._refresh_room_info():
                    self.recorder = None
                    try:
                        await self.start_recording()
                        # Launched: if this replacement also captures nothing, its own
                        # empty finalize re-enters here to drive the next round.
                        return
                    except Exception as exc:
                        logger.warning(
                            "recording recovery relaunch failed on round %d: %s",
                            rounds + 1, exc, exc_info=True,
                            extra={"event": "collector.recording_recovery_failed",
                                   "ctx": {"round": rounds + 1,
                                           "exc_type": type(exc).__name__}},
                        )
                rounds += 1
                await asyncio.sleep(delay)
                delay = min(delay * 2, RECORDING_RECOVERY_BACKOFF_MAX)
        finally:
            self._recovering = False
            logger.info(
                "stream-URL recovery loop finished after %d round(s)", rounds,
                extra={"event": "collector.recording_recovery_finished",
                       "ctx": {"rounds": rounds, "state": self.state,
                               "recording_desired": self._recording_desired}},
            )

    async def _on_disconnect(self, event: DisconnectEvent) -> None:
        """全ての切断でmarkerとops_eventを残す。従来は「接続中かつ停止要求あり」の内側
        でしかmarkerを出しておらず、収集の穴を測るために唯一必要な**予期しない切断**だけが
        記録に残らなかった(対になる再接続markerだけが孤立した)。切断中のjoin/giftは丸ごと
        欠落するため、planned/unplannedの区別込みで必ず残す。"""
        planned = self._stop_requested
        was_connected = self.state == STATE_CONNECTED
        # kindを分けるのは、後段のカバレッジ解析がmarkers表だけで欠測窓を組めるように
        # するため。labelはUIに出ないので、labelだけの区別では機械的に読めない。
        self._add_conn_marker(
            *(("disconnect", "切断") if planned
              else ("disconnect_unplanned", "異常切断"))
        )
        self._storage.record_ops_event(
            logger, "collector.disconnected",
            f"eventの受信が切れました"
            f"（{'停止要求による切断' if planned else '予期しない切断'}、room {self.room_id}）",
            severity=OPS_INFO if planned else OPS_WARNING,
            detail={"room_id": self.room_id,
                    "planned": planned,
                    "was_connected": was_connected,
                    "state": self.state,
                    "ever_connected": self._ever_connected,
                    "reconnect_attempt": self._reconnect_attempt,
                    "recording_desired": self._recording_desired},
        )
        if planned and was_connected:
            self.state = STATE_DISCONNECTED
            await self._record("system", {"text": "収集を停止しました。"})
        await self._notify_state()

    async def _on_live_end(self, event: LiveEndEvent) -> None:
        # 終了の申告元。実配信では extra_info.source に 'finish_by_server' が入る例を
        # 観測している。配信者自身の終了とサーバ側都合の終了は運用上まったく別物なので、
        # 生値を残して後から区別できるようにする。ただし各値が何を意味するかは未確定
        # なので、labelもseverityの出し分けも行わない(推測で意味を与えない)。
        extra = getattr(event, "extra_info", None)
        source = (
            str(getattr(extra, "source", "") or "").strip()
            if _on_wire(extra) else ""
        ) or SOURCE_UNKNOWN
        logger.info(
            "TikTok signalled that the broadcast has ended",
            extra={"event": "collector.live_ended",
                   "ctx": {"reason": "live_end_event", "room_id": self.room_id,
                           "end_source": source,
                           "recording_active": bool(
                               self.recorder is not None and self.recorder.is_active
                           )}},
        )
        self._storage.record_ops_event(
            logger, "collector.live_ended",
            f"配信が終了しました（room {self.room_id}、検知元: {source}）",
            severity=OPS_INFO,
            detail={"room_id": self.room_id,
                    "end_source": source,
                    "state": self.state,
                    "recording_desired": self._recording_desired,
                    "recording_active": bool(
                        self.recorder is not None and self.recorder.is_active
                    )},
        )
        self.state = STATE_ENDED
        self._add_conn_marker("live_end", "LIVE終了")
        await self._record("system", {"text": "LIVE配信が終了しました。"})
        await self._notify_state()

    def _battle_record(self, battle_id: int) -> dict:
        rec = self._battles.get(battle_id)
        if rec is None:
            now = time.time()
            rec = {
                "battle_id": battle_id,
                # type(個人戦/チーム戦)はrecordには持たない。参加者のteam_idから
                # _battle_publicで導出する(core.battle.battle_type)。
                "action": None,
                "aborted": False,
                "start_time": now,
                "end_time": None,
                "duration": None,
                "own_score": 0,
                "opp_score": 0,
                "result": None,
                "opponents": [],
                "participants": {},
                "contributions": {},
                "score_series": [],
                "bonus_missions": [],
                # グローブ(Critical Strike card)の効果窓。自陣狙いのみ集計対象。
                # {start, end, target_host_id, own, multiple, rate_low, rate_high}
                "glove_windows": [],
                # グローブ窓中に自陣へ入ったギフト単位のクリ判定records。
                # {t, gift_id, gift_count, coins, total, score_delta, mult, crit}
                "glove_events": [],
                "updated_at": now,
            }
            self._battles[battle_id] = rec
        return rec

    def _append_score_sample(self, rec: dict) -> None:
        """Record a {t, own, opp, parts} point for the battle's score-over-time
        chart. The latest point within the sample window is collapsed in place so the
        series stays bounded yet always reflects the current score; a new point is
        appended only once the window elapses.

        窓の起点(anchor)はseries[-1]["t"]ではなく別に持つ。scoreが動き続けるあいだは
        series[-1]を差し替えるが、そのtも一緒に進むためseries[-1]["t"]を起点にすると窓が
        永久に閉じず、系列が1点のまま伸びない。スコアが動き続ける場面=決着の瞬間が丸ごと
        1点に潰れるので、起点は「その窓を開いた時刻」に固定する。anchorはrec外に持つ
        (recはそのままDBへJSON保存されるため、実行時のみの状態を混ぜない)。

        ``parts`` snapshots each host's live score (id/side/team_id) so a per-member /
        per-team breakdown is available over time, not just the 2-sided own/opp totals
        — personal Nコラ (1:1:1) and team NvM (2:2) score curves can then be rebuilt."""
        now = time.time()
        parts = [
            {
                "id": uid,
                "score": p.get("score", 0) or 0,
                "side": p.get("side"),
                "team_id": p.get("team_id"),
            }
            for uid, p in rec["participants"].items()
        ]
        sample = {"t": now, "own": rec["own_score"], "opp": rec["opp_score"], "parts": parts}
        series = rec["score_series"]
        battle_id = rec.get("battle_id")
        if series:
            last = series[-1]
            anchor = self._score_anchor.get(battle_id, last["t"])
            within_window = now - anchor < self._score_sample_window(rec, now)
            unchanged = (
                last["own"] == sample["own"]
                and last["opp"] == sample["opp"]
                and last.get("parts") == parts
            )
            if within_window:
                if not unchanged:
                    series[-1] = sample
                return
        series.append(sample)
        self._score_anchor[battle_id] = now

    def _score_sample_window(self, rec: dict, now: float) -> float:
        """スコア推移の記録間隔。終盤だけ短い窓を返す。

        PKの決着は終了間際に集中する(core.battleの実測: 最後にscoreが動いたsampleの大半が
        end_timeの±3秒)ため、通常の間隔のままでは逆転の瞬間が1点に潰れる。end_timeは
        Battle開始時のbattle settingで既知なので、残り時間で窓を切り替える。

        end_timeはTikTok server時計、nowは受信側のlocal時計で厳密には同一ではない。境界が
        数秒ずれても「終盤を細かく録る」という目的は達せられるので補正はしない(ずれの補正は
        推定値の捏造になる)。end_timeが届かなかったBattleは通常の間隔のままにする。"""
        normal = self._settings.get("battle_score_sample_seconds")
        endgame = self._settings.get("battle_score_endgame_seconds")
        end_time = rec.get("end_time")
        if not endgame or not end_time:
            return normal
        # 終了時刻を過ぎた後も同じ幅を続ける: 確定scoreはend_timeの後に届くことがある。
        if now < end_time - endgame:
            return normal
        return min(normal, self._settings.get("battle_score_endgame_sample_seconds"))

    def _is_own_host(self, host_id: Any, army: Any) -> bool:
        return str(host_id) == self._owner_id or getattr(army, "anchor_id_str", "") == self._owner_id

    def _dump_battle_raw(self, kind: str, event: Any) -> None:
        """検証用: Battle系eventをTikTokから届いた生のまま logs/battle_raw_*.jsonl へ
        追記する。設定 battle_debug_capture がON、かつ実API mode (非simulation) のときだけ
        記録する。失敗してもStackTraceを残すのみで本流の収集は止めない。"""
        if self._simulation or not self._settings.get("battle_debug_capture"):
            return
        # 未定義enum値(TikTok新種)で例外を出さない安全変換。default値は省かれる。
        payload = safe_event_to_dict(event)
        record = {
            "ts": time.time(),
            "session_id": self.session_id,
            "unique_id": self.unique_id,
            "kind": kind,
            "payload": payload,
        }
        try:
            log_dir = Path(get_log_dir())
            log_dir.mkdir(parents=True, exist_ok=True)
            safe = (self.unique_id or "unknown").lstrip("@").replace("/", "_")
            out_path = log_dir / f"battle_raw_{safe}_{self.session_id}.jsonl"
            if self._battle_raw_path != str(out_path):
                self._close_battle_raw()
                self._battle_raw_fh = out_path.open("a", encoding="utf-8")
                self._battle_raw_path = str(out_path)
            self._battle_raw_fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            self._battle_raw_fh.flush()
        except Exception:
            # このeventの生payloadは二度と手に入らない(TikTokは再送しない)。
            logger.error(
                "failed to write the battle raw capture for %s; this event's raw "
                "payload is lost", kind, exc_info=True,
                extra={"event": "collector.battle_raw_write_failed",
                       "ctx": {"kind": kind, "path": self._battle_raw_path}},
            )

    def _close_battle_raw(self) -> None:
        """生capture fileを閉じ、設定が有効なら gzip へ回す。

        圧縮は**必ず close の後**に行う。Windowsではopen handleのまま圧縮すると、
        圧縮完了後のunlinkが WinError 32 (使用中) で失敗し、非圧縮の元fileが残る。
        また出力名には close 時刻stampを付ける。同一sessionが再開して同じ base 名に
        戻った場合、stampが無いと既存の .gz を上書きして過去のcaptureを消す。"""
        if self._battle_raw_fh is None:
            return
        path = self._battle_raw_path
        try:
            self._battle_raw_fh.close()
        except OSError:
            # 閉じられなかったfileは圧縮に回さない(open handleのまま圧縮するのを避ける)。
            logger.warning(
                "failed to close the battle raw capture handle; leaving the plain file "
                "uncompressed", exc_info=True,
                extra={"event": "collector.battle_raw_close_failed",
                       "ctx": {"path": path}},
            )
            path = None
        self._battle_raw_fh = None
        self._battle_raw_path = None
        if path:
            self._compress_battle_raw(Path(path))

    def _compress_battle_raw(self, path: Path) -> None:
        """閉じ終わった生captureを、close時刻stamp付きの名前へ改名してから非同期gzipへ
        submitする。改名は同期(呼び出し元がbase pathを直ちに解放する必要がある)、gzipは
        共有workerで行うのでevent loopを止めない。"""
        if not get_log_battle_raw_gzip():
            return
        try:
            if not path.exists() or path.stat().st_size <= 0:
                return
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
            target = path.with_name(f"{path.stem}-{stamp}{path.suffix}")
            counter = 1
            while target.exists() or target.with_suffix(target.suffix + ".gz").exists():
                target = path.with_name(f"{path.stem}-{stamp}.{counter}{path.suffix}")
                counter += 1
            # size は submit の前に読む。compress_async は完了後に元fileを消すので、
            # 後から stat すると race で FileNotFoundError になりうる。
            size_bytes = path.stat().st_size
            path.rename(target)
        except OSError:
            logger.warning(
                "failed to stage the battle raw capture for compression; leaving the "
                "plain file", exc_info=True,
                extra={"event": "collector.battle_raw_compress_failed",
                       "ctx": {"path": str(path)}},
            )
            return
        compress_async(target)
        logger.info(
            "battle raw capture closed and queued for compression",
            extra={"event": "collector.battle_raw_closed",
                   "ctx": {"path": str(target), "size_bytes": size_bytes}},
        )

    def _linkmic_roster_uids(self, all_list_user) -> set:
        """AllListUser.linked_list から接続中userのuid集合を取り出す(host含む)。"""
        uids = set()
        try:
            for item in getattr(all_list_user, "linked_list", None) or []:
                link_user = getattr(item, "link_user", None)
                uid = getattr(link_user, "uid", 0) if link_user is not None else 0
                if uid:
                    uids.add(str(uid))
        except Exception:
            # rosterが読めないとその窓のguests_maxが過小になる(窓自体は残る)。
            logger.warning(
                "linkmic roster parse failed; the collab guest count for this window "
                "may be understated", exc_info=True,
                extra={"event": "collector.linkmic_roster_parse_failed", "ctx": {}},
            )
        return uids

    async def _on_link_layer(self, event: LinkLayerEvent) -> None:
        """コラボ(非BattleのLinkMic)の接続窓を収集する。message_typeはTikTokが番号を
        使い回すため当てにできず、content(create/finish/list/join)の有無で判定する。
        create→finishでchannel窓、roster(linked_list)で guest数(host=_owner_id 除外)を
        追跡。Battle窓の差し引きは分析側で行う。best-effortで本流は止めない(doc §14)。"""
        try:
            channel_id = str(getattr(event, "channel_id", 0) or "")
            if not channel_id:
                return
            now = time.time()
            roster = None
            list_content = getattr(event, "list_content", None)
            if list_content is not None:
                roster = self._linkmic_roster_uids(getattr(list_content, "user_list", None))
            join_content = getattr(event, "join_direct_content", None)
            if join_content is not None:
                extra = self._linkmic_roster_uids(getattr(join_content, "all_users", None))
                roster = (roster or set()) | extra if extra else roster
            create_content = getattr(event, "create_channel_content", None)
            is_create = bool(create_content and getattr(getattr(create_content, "owner", None), "uid", 0))
            finish_content = getattr(event, "finish_content", None)
            is_finish = bool(
                finish_content
                and (getattr(getattr(finish_content, "owner", None), "uid", 0)
                     or getattr(finish_content, "finish_reason", 0))
            )
            state = self._collab_open.get(channel_id)
            if state is None and (is_create or roster is not None or is_finish):
                state = {"start": now, "guests_max": 0, "channel_id": channel_id}
                self._collab_open[channel_id] = state
                self._add_linkmic_marker("collab", "コラボ")
                logger.info(
                    "collab (non-battle LinkMic) window opened on channel %s", channel_id,
                    extra={"event": "collector.collab_opened",
                           "ctx": {"channel_id": channel_id,
                                   "trigger": ("create" if is_create
                                               else "finish" if is_finish else "roster"),
                                   "roster_size": len(roster) if roster else 0}},
                )
            if state is None:
                return
            if roster:
                guests = {u for u in roster if u != self._owner_id}
                state["guests_max"] = max(state["guests_max"], len(guests))
            if is_finish:
                self._collab_windows.append(
                    {
                        "channel_id": channel_id,
                        "start": state["start"],
                        "end": now,
                        "guests_max": state["guests_max"],
                    }
                )
                self._collab_open.pop(channel_id, None)
                logger.info(
                    "collab window closed on channel %s (%.0fs, max %d guest(s))",
                    channel_id, now - state["start"], state["guests_max"],
                    extra={"event": "collector.collab_closed",
                           "ctx": {"channel_id": channel_id,
                                   "duration_ms": int((now - state["start"]) * 1000),
                                   "guests_max": state["guests_max"]}},
                )
                # 窓が確定したので即中間永続化(クラッシュ耐性)。
                self._persist_progress()
        except Exception:
            # この窓の入室コンテキスト分類が欠ける。次のLinkLayer eventで再入する。
            logger.warning(
                "link layer handling failed; this collab window may be missing from the "
                "join-context classification", exc_info=True,
                extra={"event": "collector.collab_handling_failed", "ctx": {}},
            )

    def _collab_windows_public(self) -> list:
        """確定済み窓＋未クローズ窓(終端=現在時刻で補完)。session終了時の保存に使う。"""
        now = time.time()
        windows = list(self._collab_windows)
        for channel_id, state in self._collab_open.items():
            windows.append(
                {
                    "channel_id": channel_id,
                    "start": state["start"],
                    "end": now,
                    "guests_max": state["guests_max"],
                }
            )
        return windows

    async def _on_battle(self, event: LinkMicBattleEvent) -> None:
        self._dump_battle_raw("LinkMicBattle", event)
        battle_id = getattr(event, "battle_id", 0)
        rec = self._battle_record(battle_id)
        action = _enum_value(getattr(event, "action", None))
        rec["action"] = action
        if action in _ABORTED_BATTLE_ACTIONS:
            rec["aborted"] = True
        setting = getattr(event, "battle_setting", None)
        if setting is not None:
            start_ms = getattr(setting, "start_time_ms", 0) or 0
            if start_ms:
                rec["start_time"] = start_ms / 1000.0
            end_ms = getattr(setting, "end_time_ms", 0) or 0
            if end_ms:
                rec["end_time"] = end_ms / 1000.0
            duration = getattr(setting, "duration", 0) or 0
            if duration:
                rec["duration"] = duration
        # 個人戦/チーム戦はここでは決めない。team構造の有無で決めるとTikTokが「1人陣営×N」の
        # team構造で送る個人マルチ(1:1:1)が全てチーム戦になるため、参加者のteam_idから
        # core.battleのruleで導出する(_battle_public)。
        self._capture_opponents(rec, getattr(event, "anchor_info", None))
        self._recount_battles()
        label = f"Battle #{battle_id}"
        self._add_linkmic_marker("battle", label)
        await self._record(
            "battle",
            {"text": f"{label} のEventを受信しました (action={getattr(event, 'action', None)})"},
        )
        # Battle窓の判定分岐。窓境界はGift貢献の再構成・グローブcrit判定・入室コンテキスト
        # 分類の全ての基準になるので、どちらへ分岐したかは後から確定できる必要がある。
        if rec.get("aborted") or action == BATTLE_ACTION_FINISH:
            logger.info(
                "battle %s %s (action=%s); closing its window",
                battle_id, "aborted" if rec.get("aborted") else "finished", action,
                extra={"event": "collector.battle_closed",
                       "ctx": {"battle_id": battle_id, "action": action,
                               "aborted": bool(rec.get("aborted")),
                               "own_score": rec.get("own_score"),
                               "opp_score": rec.get("opp_score"),
                               "result": rec.get("result"),
                               "participants": len(rec.get("participants") or {})}},
            )
            await self._stop_opponent_listeners(battle_id)
            # Battleが確定(FINISH/abort)した時点で窓が固定されるので即中間永続化する。
            # クラッシュ前でも確定済みBattleと貢献がDBに残る。
            self._persist_progress()
        else:
            logger.info(
                "battle %s is in progress (action=%s) with %d opponent host(s)",
                battle_id, action, len(rec.get("opponents") or []),
                extra={"event": "collector.battle_opened",
                       "ctx": {"battle_id": battle_id, "action": action,
                               "opponents": len(rec.get("opponents") or []),
                               "duration_seconds": rec.get("duration")}},
            )
            if self._notifier is not None:
                # 「窓が開いた」分岐なので、同一Battleのaction更新でも毎回ここへ来る。1戦1件に
                # 畳むのは通知側(battle_id単位のdedup key)の仕事。
                self._notifier.on_battle_started(
                    self.unique_id, battle_id, len(rec.get("opponents") or []))
            await self._start_opponent_listeners(rec)
        await self._broadcast_battles(force=True)

    @staticmethod
    def _prompt_value(prompt: Any, key: str) -> str:
        """BattlePrompt の prompt_elements から field_key 一致の値を取り出す。
        文言はStarling key 側に持たせる方針なので、ここでは数値等の動的値(multi/sum 等)
        だけを実値として拾う。"""
        for elem in (getattr(prompt, "prompt_elements", None) or []):
            if getattr(elem, "prompt_field_key", "") == key:
                return getattr(elem, "prompt_field_value", "") or ""
        return ""

    @staticmethod
    def _prompt_record(prompt: Any, slot: str) -> Optional[dict]:
        """BattlePrompt を {slot, key, fields} へ落とす。文言はStarling keyにしか無く
        event本体は key と差し込み値しか運ばないので、解釈せず実値のまま保存し、
        表示側(overlay/Web)がkeyから文言を組む。"""
        key = getattr(prompt, "prompt_key", "") or ""
        if not key:
            return None
        fields = {}
        for elem in (getattr(prompt, "prompt_elements", None) or []):
            fk = getattr(elem, "prompt_field_key", "") or ""
            if fk:
                fields[fk] = getattr(elem, "prompt_field_value", "") or ""
        return {"slot": slot, "key": key, "fields": fields}

    @classmethod
    def _mission_prompts(cls, cfg: Any, task: Any, reward: Any) -> list:
        """ミッションの文言keyを配信順に集める。ミッション種別(指定ギフト/チーム/
        ポイント等)はこのkeyでしか判別できず、target_typeだけでは文言を復元できない。"""
        prompts = []
        for i, period in enumerate(getattr(cfg, "preview_period_config", None) or []):
            rec = cls._prompt_record(getattr(period, "promot", None), f"preview{i}")
            if rec is not None:
                rec["duration"] = getattr(period, "duration", 0) or 0
                prompts.append(rec)
        for prompt, slot in (
            (getattr(task, "task_static_prompt", None), "task"),
            (getattr(task, "click_toast_prompt", None), "toast"),
            (getattr(reward, "reward_prapare_prompt", None), "prepare"),
            (getattr(reward, "rewarding_prompt", None), "rewarding"),
        ):
            rec = cls._prompt_record(prompt, slot)
            if rec is not None:
                prompts.append(rec)
        return prompts

    def _mission_add_contributor(self, rec: dict, mission: dict, uid: str) -> None:
        """ミッション進捗を押し上げた送信者を記録する。表示名/avatarは判れば突合し、
        未判明なら id のみ。突合は _battle_public 時にも再試行する。"""
        if not uid:
            return
        for c in mission["contributors"]:
            if c["user_id"] == uid:
                c["count"] = c.get("count", 0) + 1
                return
        contrib = rec["contributions"].get(uid) or {}
        mission["contributors"].append({
            "user_id": uid,
            "count": 1,
            "nickname": contrib.get("nickname", "") or "",
            "avatar": contrib.get("avatar", "") or "",
        })

    async def _on_battle_task(self, event: LinkmicBattleTaskEvent) -> None:
        """Match Bonus Mission（倍率タイム）。preview→task(達成)→reward(倍率)→settle の
        各messageを、Battleレコードの bonus_missions[] に集約する。倍率値・秒数・進捗・
        確定ボーナスはすべてevent実値を使う(hard-codeしない)。"""
        self._dump_battle_raw("LinkmicBattleTask", event)
        battle_id = getattr(event, "battle_id", 0) or 0
        if not battle_id:
            return
        rec = self._battle_record(battle_id)
        missions = rec.setdefault("bonus_missions", [])

        # betterprotoはunsetのmessage fieldに空のdefault instanceを返す(Noneではない)ため、
        # task_start等の有無では判別できない。message_typeで明示的に分岐する。
        # START=0(または未設定でNone), UPDATE=1, TASK_SETTLE=2, REWARD_SETTLE=3。
        mtype = _enum_value(getattr(event, "battle_task_message_type", None))
        if mtype in (None, 0):
            start = getattr(event, "task_start", None)
            cfg = getattr(start, "battle_bonus_config", None)
            task = getattr(cfg, "task_period_config", None)
            reward = getattr(cfg, "reward_period_config", None)
            missions.append({
                "multiplier": getattr(reward, "reward_multiple", 0) or 0,
                "target_type": getattr(task, "target_type", 0) or 0,
                "prompts": self._mission_prompts(cfg, task, reward),
                "preview_start_ts": (getattr(cfg, "preview_start_timestamp", 0) or 0) or None,
                "task_start_ts": (getattr(task, "target_start_timestamp", 0) or 0) or None,
                "task_duration": getattr(task, "duration", 0) or 0,
                "progress_target": getattr(task, "progress_target", 0) or 0,
                "reward_start_ts": (getattr(reward, "reward_start_timestamp", 0) or 0) or None,
                "reward_duration": getattr(reward, "duration", 0) or 0,
                "progress": 0,
                "achieved": False,
                "settled": False,
                "contributors": [],
                "bonus_sum": 0,
                "created_at": time.time(),
            })
            await self._broadcast_battles(force=True)
            return

        # update/settle系は、このBattleの最新missionへ適用する。startを取り逃した
        # (途中接続)場合は最小限のplaceholderを起こしてdataを捨てない。倍率(reward_multiple)
        # はSTART messageにしか載らないため、START欠落時は倍率を復元できない(overlayは倍率値を
        # 騙らず「ギフト倍率」表示)。達成条件の種別を運ぶprompt keyも同様に復元できない。
        if not missions:
            # 倍率はSTART messageにしか載らないため、この mission の ×N は復元不能。
            # 以後のUPDATE/SETTLEでも埋まらない。
            logger.warning(
                "battle %s: bonus mission START was not seen (mtype=%s); its multiplier "
                "cannot be recovered and the overlay will show 'BONUS' without xN",
                battle_id, mtype,
                extra={"event": "collector.bonus_mission_start_missing",
                       "ctx": {"battle_id": battle_id, "message_type": mtype}},
            )
            missions.append({
                "multiplier": 0, "target_type": 0, "prompts": [],
                "preview_start_ts": None, "task_start_ts": None,
                "task_duration": 0, "progress_target": 0, "reward_start_ts": None,
                "reward_duration": 0, "progress": 0, "achieved": False, "settled": False,
                "contributors": [], "bonus_sum": 0, "created_at": time.time(),
            })
        mission = missions[-1]

        if mtype == 1:  # TASK_UPDATE
            upd = getattr(event, "task_update", None)
            mission["progress"] = max(mission["progress"], getattr(upd, "task_progress", 0) or 0)
            self._mission_add_contributor(rec, mission, str(getattr(upd, "from_user_uid", 0) or "") or "")
            target = mission["progress_target"]
            if target and mission["progress"] >= target:
                mission["achieved"] = True
        elif mtype == 2:  # TASK_SETTLE: ミッション期間の確定(達成可否・倍率開始時刻)
            settle = getattr(event, "task_settle", None)
            # 倍率の実開始時刻。STARTの予定値より確実なので確定値で上書きする(無ければ据え置き)。
            rs = getattr(settle, "reward_start_timestamp", 0) or 0
            if rs:
                mission["reward_start_ts"] = rs
            # 進捗UPDATEを取り逃しても、確定resultが成功(SUCCEED/BOTH)なら達成として尊重する。
            result = _enum_value(getattr(settle, "task_result", None))
            target = mission["progress_target"]
            if result in (0, 2) or (target and mission["progress"] >= target):
                mission["achieved"] = True
        elif mtype == 3:  # REWARD_SETTLE: 倍率期間の獲得ボーナス確定
            settle = getattr(event, "reward_settle", None)
            total = self._prompt_value(getattr(settle, "reward_settle_prompt", None), "sum")
            if total:
                try:
                    mission["bonus_sum"] = int(total)
                except ValueError:
                    logger.warning(
                        "bonus mission settle sum is not an integer (%r); the confirmed "
                        "bonus for battle %s stays 0", total, battle_id,
                        extra={"event": "collector.bonus_sum_unparsed",
                               "ctx": {"battle_id": battle_id, "raw": str(total)}},
                    )
            mission["settled"] = True
            mission["achieved"] = mission["achieved"] or mission["bonus_sum"] > 0

        await self._broadcast_battles(force=True)

    async def _start_opponent_listeners(self, rec: dict) -> None:
        """PK中、判明している相手host各人のRoomへGift取得listenerを張る。設定OFF /
        simulation時は何もしない。同一hostへの二重接続は避ける。"""
        if self._simulation or not self._settings.get("monitor_opponent_rooms"):
            return
        if self._resolver is None:
            return
        battle_id = rec["battle_id"]
        listeners = self._opp_listeners.setdefault(battle_id, [])
        started = {listener.host_id for listener in listeners}
        for opp in rec.get("opponents", []):
            handle = opp.get("unique_id")
            host_id = str(opp.get("user_id") or "")
            if not handle or not host_id or host_id in started:
                continue
            listener = OpponentRoomListener(
                handle, host_id, battle_id, self._resolver, self._probe_gate, self._on_opponent_gift
            )
            listeners.append(listener)
            started.add(host_id)
            await listener.start()

    async def _stop_opponent_listeners(self, battle_id: int) -> None:
        for listener in self._opp_listeners.pop(battle_id, []):
            await listener.stop()

    async def _stop_all_opponent_listeners(self) -> None:
        for battle_id in list(self._opp_listeners.keys()):
            await self._stop_opponent_listeners(battle_id)

    async def _on_opponent_gift(self, battle_id: int, host_id: str, user: dict, coins: int) -> None:
        """相手RoomのlistenerからのGift。相手陣貢献(host_id=相手配信者)へ数値IDで突合し
        実弾を加算する。armies由来の同一貢献者(score=BS)があればそこへ足し込む。"""
        rec = self._battles.get(battle_id)
        if rec is None:
            return
        # _user_payloadが決めたidentity_keyをそのまま使う。ここで再計算すると表示用の
        # "(unknown)" がkeyになり、身元不明の相手陣gifterが1人へ畳まれる。
        key = user.get("identity_key")
        if not key:
            return
        entry = rec["contributions"].get(key)
        if entry is None:
            entry = {
                "user_id": user.get("user_id", ""),
                "unique_id": user.get("unique_id", ""),
                "nickname": user.get("nickname", "(unknown)"),
                "avatar": user.get("avatar", ""),
                "side": "opp",
                "host_id": str(host_id),
                "score": 0,
                "diamonds": 0,
                "fans_level": user.get("fans_level", 0),
                "gifter_level": user.get("gifter_level", 0),
                "gifter_badge": user.get("gifter_badge", ""),
                "member_badge": user.get("member_badge", ""),
            }
            rec["contributions"][key] = entry
            self._persist_avatar(entry["unique_id"] or entry["nickname"], entry["avatar"])
        entry["side"] = "opp"
        entry["host_id"] = str(host_id)
        entry["diamonds"] += coins
        if user.get("unique_id"):
            entry["unique_id"] = user["unique_id"]
        entry["nickname"] = user.get("nickname") or entry["nickname"]
        if user.get("avatar"):
            entry["avatar"] = user["avatar"]
        # Lv/バッジは後続のGiftで判明することがあるので、取得できた分で補完(空では上書きしない)。
        if user.get("fans_level"):
            entry["fans_level"] = user["fans_level"]
        if user.get("gifter_level"):
            entry["gifter_level"] = user["gifter_level"]
        if user.get("gifter_badge"):
            entry["gifter_badge"] = user["gifter_badge"]
        if user.get("member_badge"):
            entry["member_badge"] = user["member_badge"]
        self._persist_badge(entry.get("gifter_badge", ""))
        if not entry.get("fans_level"):
            self._persist_badge(entry.get("member_badge", ""))
        await self._broadcast_battles()

    def _capture_opponents(self, rec: dict, anchor_info: Any) -> None:
        """Record opponent host display names/avatars from the battle's anchor_info.
        The host name/avatar is NOT in the armies data (BattleUserArmies carries only
        anchor_id_str), so this is the sole source. The real proto nests it as
        BattleUserInfoWrapper.user_info.user (BattleBaseUserInfo: nick_name /
        display_id / avatar_thumb); getattr fallbacks keep a flatter shape working.
        Own host is skipped via owner id."""
        if not anchor_info:
            return
        for wrapper in anchor_info:
            info = getattr(wrapper, "user_info", None) or wrapper
            base = getattr(info, "user", None) or getattr(wrapper, "user", None) or info
            uid = str(
                getattr(base, "user_id", "")
                or getattr(wrapper, "user_id", "")
                or getattr(base, "id", "")
                or ""
            )
            if not uid or uid == self._owner_id:
                continue
            entry = next((o for o in rec["opponents"] if o.get("user_id") == uid), None)
            if entry is None:
                entry = {"user_id": uid, "unique_id": "", "nickname": "", "avatar": "", "score": 0}
                rec["opponents"].append(entry)
            entry["nickname"] = getattr(base, "nick_name", "") or getattr(base, "nickname", "") or entry["nickname"]
            entry["unique_id"] = getattr(base, "display_id", "") or entry["unique_id"]
            avatar = _image_url(getattr(base, "avatar_thumb", None))
            if avatar:
                entry["avatar"] = avatar
                self._persist_avatar(entry["unique_id"] or entry["nickname"], avatar)
            # Mirror the display fields onto the participant record (keyed by the same
            # host id) so personal multi / team rosters show names, not bare ids.
            # side is intentionally not set here — the armies paths group by team and
            # own-id and are authoritative; anchor_info is display-only enrichment.
            self._upsert_participant(
                rec, uid, unique_id=entry["unique_id"], nickname=entry["nickname"],
                avatar=entry["avatar"],
            )

    async def _on_item_card(self, event: LinkMicBattleItemCardEvent) -> None:
        """Battle item card (グローブ等のブースト)。診断dumpに加え、Critical Strike
        (グローブ=gift 5倍化) の効果窓を自陣狙い分だけBattleレコードへ記録する。窓は後段の
        armies処理で「窓中に自陣へ入ったギフトのクリ率」をcoin帯別に集計する母集団になる。"""
        self._dump_battle_raw("LinkMicBattleItemCard", event)
        try:
            self._capture_glove_window(event)
        except Exception:
            # 窓が取れないとこのcardのcrit判定母集団が丸ごと欠ける(再送は無い)。
            logger.error(
                "glove (critical strike) window capture failed; this card's crit "
                "statistics are lost", exc_info=True,
                extra={"event": "collector.glove_window_failed", "ctx": {}},
            )

    def _capture_glove_window(self, event: LinkMicBattleItemCardEvent) -> None:
        msg_name = getattr(getattr(event, "msg_type", None), "name", "") or str(getattr(event, "msg_type", ""))
        if "CRITICAL_STRIKE" not in msg_name:
            return
        card = getattr(event, "use_critical_strike_card", None)
        info = getattr(card, "card_info", None) if card is not None else None
        if info is None:
            return
        target = str(getattr(info, "to_anchor_id_str", "") or getattr(info, "to_anchor_id", "") or "")
        if not target:
            return
        start = int(getattr(info, "effect_time_sec", 0) or getattr(info, "send_time_sec", 0) or 0)
        duration = int(getattr(info, "effect_last_duration", 0) or 0)
        if start <= 0 or duration <= 0:
            return
        rec = self._battle_record(int(getattr(event, "battle_id", 0) or 0))
        window = {
            "start": start,
            "end": start + duration,
            "target_host_id": target,
            "own": target == self._owner_id,
            "multiple": int(getattr(info, "multiple", 0) or 0) or GLOVE_MULTIPLE,
            "rate_low": int(getattr(info, "critical_strike_rate_low", 0) or 0),
            "rate_high": int(getattr(info, "critical_strike_rate_high", 0) or 0),
        }
        # 同一cardが複数回届くことがある(dispatch_strategy)。同窓の重複は捨てる。
        for w in rec["glove_windows"]:
            if w["start"] == window["start"] and w["target_host_id"] == window["target_host_id"]:
                return
        rec["glove_windows"].append(window)
        logger.info(
            "glove (critical strike) window opened on battle %s for %s host, %ds",
            rec["battle_id"], "own" if window["own"] else "opponent",
            window["end"] - window["start"],
            extra={"event": "collector.glove_window_opened",
                   "ctx": {"battle_id": rec["battle_id"],
                           "own": window["own"],
                           "duration_seconds": window["end"] - window["start"],
                           "multiple": window["multiple"],
                           "rate_low": window["rate_low"],
                           "rate_high": window["rate_high"]}},
        )

    def _record_glove_candidate(self, gift_id: int, diamonds_each: int, count: int,
                                t: Optional[float]) -> bool:
        """自陣グローブ窓中に自陣へ届いた1ギフトを、crit判定待ち(pending)として記録する。
        単価はGift event(自室)からのみ確実に取れるためここで確定し、critは後続armiesの
        自hostスコアdelta厳密一致で解決する。gift時刻は窓・armiesと同じserver epoch秒
        (create_time)で突合する。server時刻が無いgiftは窓の内外すら判定できないので、
        受信側時計へ落とさず判定対象から外す。窓中giftとして記録したらTrue。"""
        if not diamonds_each or count <= 0:
            return False
        if t is None:
            self._warn_glove_clock("gift")
            return False
        ts = int(t)
        for rec in self._battles.values():
            if rec.get("aborted"):
                continue
            window = next(
                (w for w in rec["glove_windows"] if w.get("own") and w["start"] <= ts <= w["end"]),
                None,
            )
            if window is None:
                continue
            ev = {
                "t": ts,
                "gift_id": gift_id,
                "gift_count": count,
                "coins": diamonds_each,
                "total": diamonds_each * count,
                "score_delta": None,
                "mult": None,
                "crit": None,
                # 判定根拠(GLOVE_METHOD_*)。判定不能のまま確定した場合はNoneのまま残す。
                "method": None,
                "v": GLOVE_EVENT_VERSION,
            }
            rec["glove_events"].append(ev)
            self._glove_pending.setdefault(rec["battle_id"], []).append({
                "t": ts,
                "gift_id": gift_id,
                "total": ev["total"],
                "multiple": window.get("multiple") or GLOVE_MULTIPLE,
                "ev": ev,
            })
            return True
        return False

    def _record_glove_offwindow_gift(self, diamonds_each: int, count: int, t: Optional[float]) -> None:
        """窓外に自室へ届いたgiftを記録する。deltaのpool掃除(通常寄与の先取り消費)に使う。
        server時刻が無いgiftはpool上の位置が決まらないため記録しない。"""
        if not diamonds_each or count <= 0:
            return
        if t is None:
            self._warn_glove_clock("gift")
            return
        self._glove_recent_gifts.append([int(t), diamonds_each * count])

    def _glove_pool_latest(self, battle_id: int) -> Optional[float]:
        """glove poolが持つ最新のserver時刻。全entryが同じserver時計の値なので、armies側の
        create_timeが読めないときの刈り込み基準に使える。空ならNone(刈るものが無い)。"""
        stamps = [d[0] for d in self._glove_deltas.get(battle_id) or []]
        stamps += [e["t"] for e in self._glove_attr.get(battle_id) or []]
        stamps += [g[0] for g in self._glove_recent_gifts]
        return max(stamps) if stamps else None

    def _glove_prune(self, battle_id: int, ref: Optional[float]) -> None:
        """突合窓を過ぎたdelta/attr/窓外giftを捨ててpoolを有界に保つ。refはserver時計。"""
        if ref is None:
            return
        horizon = ref - GLOVE_MATCH_AFTER_SEC - 30
        deltas = self._glove_deltas.get(battle_id)
        if deltas:
            deltas[:] = [d for d in deltas if d[0] >= horizon and d[1] > 0]
        entries = self._glove_attr.get(battle_id)
        if entries:
            entries[:] = [e for e in entries if not e["used"] and e["t"] >= horizon]
        self._glove_recent_gifts[:] = [g for g in self._glove_recent_gifts if g[0] >= horizon]

    def _warn_glove_clock(self, source: str) -> None:
        """server時計(create_time)が読めずglove判定から外したことをSessionに1回だけ残す。"""
        if self._glove_clock_warned:
            return
        self._glove_clock_warned = True
        logger.warning(
            "glove crit resolution dropped a %s event without a server create_time; "
            "those gifts stay undecided (crit=None) for this session", source,
            extra={"event": "collector.glove_clock_missing",
                   "ctx": {"source": source, "room_id": self.room_id}},
        )

    def _glove_multiplier_at(self, rec: dict, t: float) -> Optional[int]:
        """時刻tに有効なMatch Bonus倍率。倍率タイム外=1。reward期間中だが倍率不明
        (START取り逃し)や未達成が疑わしい場合はNone(=そのgiftは判定不能)を返す。"""
        for mission in rec.get("bonus_missions") or []:
            start = mission.get("reward_start_ts") or 0
            duration = mission.get("reward_duration") or 0
            if not start or not (start <= t <= start + duration):
                continue
            multiplier = int(mission.get("multiplier") or 0)
            if multiplier <= 0 or not mission.get("achieved"):
                return None
            return multiplier
        return 1

    def _glove_own_host_score(self, event: Any) -> Optional[int]:
        """armies eventから自host個人のバトルスコアを取り出す。personalはarmies mapの
        自host、teamはteam_usersの自host member(チーム合算ではなく個人値)。"""
        score: Optional[int] = None
        for host_id, army in (getattr(event, "armies", None) or {}).items():
            if self._is_own_host(host_id, army):
                s = int(getattr(army, "host_score", 0) or 0)
                score = s if score is None else max(score, s)
        for ta in (getattr(event, "team_armies", None) or []):
            for member in (getattr(ta, "team_users", None) or []):
                mid = getattr(member, "user_id_str", "") or str(getattr(member, "user_id", "") or "")
                if mid and mid == self._owner_id:
                    s = int(getattr(member, "score", 0) or 0)
                    score = s if score is None else max(score, s)
        return score

    def _glove_consume_delta(self, battle_id: int, t: float, amount: int) -> bool:
        """poolから[t-BEFORE, t+AFTER]のdeltaを額で排他消費する。完全一致を優先し、
        無ければ複合delta(同一payload間隔に複数giftが乗った跳ね)から差し引く。"""
        deltas = self._glove_deltas.get(battle_id) or []
        for d in deltas:
            if t - GLOVE_MATCH_BEFORE_SEC <= d[0] <= t + GLOVE_MATCH_AFTER_SEC and d[1] == amount:
                d[1] = 0
                return True
        for d in deltas:
            if t - GLOVE_MATCH_BEFORE_SEC <= d[0] <= t + GLOVE_MATCH_AFTER_SEC and d[1] > amount:
                d[1] -= amount
                return True
        return False

    def _resolve_glove_crits(self, rec: dict, event: Any) -> None:
        """armies eventごとの自hostスコアdeltaを、(1)そのarmiesが名指ししたgiftへの同定、
        (2)額の厳密一致、の順で pending中のグローブ・ギフトへ割り当てて解決する。
        通常=m×total / crit=窓倍率M×total(m=倍率タイム、critは倍率タイムと重畳しない=
        実dump実測: m=3の窓でx15は0件・x5が3件)。どの根拠でも一意に決まらないものは
        crit=None(判定不能)のまま確定し、推測で埋めない。

        時間軸はギフト・グローブ窓と同じserver時計(create_time)に揃える。受信側の
        time.time()を混ぜると数秒のskewだけで正しいdeltaが突合窓(BEFORE/AFTER)から
        外れ、critが全件Noneに落ちる。create_timeが無いarmiesはこの軸に載せられない
        ため、基準scoreだけ進めてdeltaは捨てる(受信側時計へのFallbackはしない)。"""
        battle_id = int(getattr(event, "battle_id", 0) or 0)
        now = self._create_time_sec(event)
        score = self._glove_own_host_score(event)
        if score is not None:
            prev = self._glove_prev_score.get(battle_id)
            if prev is not None and score > prev:
                delta = score - prev
                if now is not None:
                    self._glove_deltas.setdefault(battle_id, []).append([now, delta])
                # 名指し同定(gift_sent_time基準)はarmies自身のcreate_timeに依存しない。
                self._glove_record_attr(battle_id, event, delta)
            if prev is None or score > prev:
                self._glove_prev_score[battle_id] = score
        if now is None:
            self._warn_glove_clock("armies")
            # 判定はできないが刈り込みは続ける。ここでreturnするだけだと、gift側は
            # server時計を持てて armies だけ持てない配信でpoolが際限なく伸びる。
            self._glove_prune(battle_id, self._glove_pool_latest(battle_id))
            return
        self._glove_prune(battle_id, now)
        # 窓外giftの通常寄与(m×total)を先に消費し、窓中giftとの偶然一致(偽crit)を防ぐ。
        remaining_gifts = []
        for g in self._glove_recent_gifts:
            gt, gtotal = g
            m = self._glove_multiplier_at(rec, gt)
            if m is not None and self._glove_consume_delta(battle_id, gt, gtotal * m):
                continue
            remaining_gifts.append(g)
        self._glove_recent_gifts[:] = remaining_gifts
        pending = self._glove_pending.get(battle_id)
        if not pending:
            return
        keep = []
        for cand in pending:  # 生成順=古い順に排他消費する
            t, total = cand["t"], cand["total"]
            ev = cand["ev"]
            expired = now > t + GLOVE_MATCH_AFTER_SEC
            m = self._glove_multiplier_at(rec, t)
            # armiesがこのgiftを名指ししていれば、額の偶然一致に依存せず倍率が読める。
            if self._glove_resolve_by_attr(battle_id, cand, m):
                continue
            if m is None:
                if not expired:
                    keep.append(cand)
                continue
            want_normal = total * m
            want_crit = total * cand["multiple"]
            if want_normal == want_crit:
                continue  # 倍率タイムm=窓倍率Mでは判別不能
            window_deltas = [
                d for d in (self._glove_deltas.get(battle_id) or [])
                if t - GLOVE_MATCH_BEFORE_SEC <= d[0] <= t + GLOVE_MATCH_AFTER_SEC and d[1] > 0
            ]
            hit_normal = any(d[1] == want_normal for d in window_deltas)
            hit_crit = any(d[1] == want_crit for d in window_deltas)
            if hit_normal == hit_crit:
                # 両方一致は曖昧なので即確定(判定不能)。どちらも無ければ次のarmiesを待つ。
                if hit_normal or expired:
                    continue
                keep.append(cand)
                continue
            ev["crit"] = hit_crit
            ev["mult"] = cand["multiple"] if hit_crit else m
            ev["score_delta"] = want_crit if hit_crit else want_normal
            ev["method"] = GLOVE_METHOD_DELTA
            self._glove_consume_delta(battle_id, t, ev["score_delta"])
        self._glove_pending[battle_id] = keep

    def _glove_record_attr(self, battle_id: int, event: Any, delta: int) -> None:
        """armiesが名指ししたgift(gift_id + gift_sent_time)へこのdeltaを同定して控える。
        trigger_critical_strikeはTikTok自身が立てるcritの真値だが、実測では全critの一部
        (窓中x5の74件に対し12件)にしか付かないので、立っていれば確定・無ければ不明として扱う。"""
        gift_id = getattr(event, "gift_id", None)
        sent_ms = getattr(event, "gift_sent_time", None)
        if not gift_id or not sent_ms:
            return
        try:
            sent = float(sent_ms) / 1000.0
        except (TypeError, ValueError):
            return
        self._glove_attr.setdefault(battle_id, []).append({
            "gid": int(gift_id),
            "t": sent,
            "delta": delta,
            "flag": bool(getattr(event, "trigger_critical_strike", False)),
            "used": False,
        })

    def _glove_resolve_by_attr(self, battle_id: int, cand: dict, m: Optional[int]) -> bool:
        """名指し同定されたdeltaでcandを解決する。解決できたらTrue。
        実効倍率が窓倍率なら crit、倍率タイム倍率なら通常。どちらでもない(合算が混じった)
        場合はここでは決めず、額一致側の判断に委ねる。"""
        entries = self._glove_attr.get(battle_id)
        if not entries:
            return False
        total = cand["total"]
        if total <= 0:
            return False
        multiple = cand["multiple"]
        for entry in entries:
            if entry["used"] or entry["gid"] != cand.get("gift_id"):
                continue
            if abs(entry["t"] - cand["t"]) > GLOVE_ATTR_MATCH_SEC:
                continue
            ev = cand["ev"]
            if entry["flag"]:
                entry["used"] = True
                ev["crit"] = True
                ev["mult"] = multiple
                ev["score_delta"] = entry["delta"]
                ev["method"] = GLOVE_METHOD_FLAG
                return True
            # 倍率タイムが不明、または窓倍率と同値のときは実効倍率が通常とcritで同じ値に
            # なり判別材料にならない。額一致側の want_normal == want_crit と同じ除外。
            if m is None or m == multiple:
                continue
            ratio = entry["delta"] / total
            hit = int(round(ratio)) if abs(ratio - round(ratio)) < 0.01 else None
            if hit == multiple:
                crit = True
            elif hit == m:
                crit = False
            else:
                continue
            entry["used"] = True
            ev["crit"] = crit
            ev["mult"] = multiple if crit else m
            ev["score_delta"] = entry["delta"]
            ev["method"] = GLOVE_METHOD_ATTR
            return True
        return False

    async def _on_armies(self, event: LinkMicArmiesEvent) -> None:
        self._dump_battle_raw("LinkMicArmies", event)
        self._mark_data()
        if not self._owner_id:
            if not self._owner_warned:
                self._owner_warned = True
                logger.warning(
                    "room owner id is unknown; battle score tracking is disabled for "
                    "this session",
                    extra={"event": "collector.owner_id_missing",
                           "ctx": {"room_id": self.room_id}},
                )
            return
        battle_id = getattr(event, "battle_id", 0)
        rec = self._battle_record(battle_id)
        prev_own = rec["own_score"]
        team_armies = getattr(event, "team_armies", None)
        if team_armies:
            # Team PK carries scores in team_armies[].team_total_score with the
            # contributors nested under user_armies — the flat `armies` map the
            # personal path reads is empty for team mode, so without this branch
            # own/opp score stay 0 for every team battle. team_armiesは個人マルチ
            # (1人陣営×N)でも届くため、これは形式の判別材料にはしない。
            own_score, opp_scores = self._consume_team_armies(rec, team_armies)
        else:
            own_score, opp_scores = self._consume_host_armies(rec, getattr(event, "armies", None))
        if own_score is not None:
            rec["own_score"] = own_score
        # 自hostスコアのdeltaを追い、グローブ窓中に届いたギフト(Gift event側でpending化済)の
        # critをdelta厳密一致で解決する。armiesのgift fieldは相手側しか載らず、user_armiesは
        # 上位3名のみのため、自陣はこのdelta突合でしか判定できない。
        try:
            self._resolve_glove_crits(rec, event)
        except Exception:
            # 未解決のpendingは次のarmiesで再試行されるが、この回のdeltaは失われる。
            logger.warning(
                "glove crit resolution failed for this armies event; pending gifts stay "
                "unresolved until the next one", exc_info=True,
                extra={"event": "collector.glove_resolve_failed", "ctx": {}},
            )
        if opp_scores:
            # opp_scoresは敵陣営(team PK)/敵host(個人戦)ごとのscore。2極表示・勝敗の相手は
            # 常に**首位の敵**。2陣営(1v1/実team NvM)ではmax==sumで従来と同値だが、3陣営
            # 以上(個人マルチ1:1:1)でsumにすると「自分 vs 敵全員の合計」になり、resultが
            # ほぼ必ずloseになる/score_seriesのoppが敵合算に潰れる。自分が首位ならwin。
            rec["opp_score"] = max(opp_scores)
        rec["result"] = (
            "win" if rec["own_score"] > rec["opp_score"]
            else "lose" if rec["own_score"] < rec["opp_score"]
            else "draw"
        )
        rec["updated_at"] = time.time()
        self._append_score_sample(rec)
        self._recount_battles()
        await self._broadcast_stats()
        await self._broadcast_battles()

    def _consume_host_armies(self, rec: dict, armies: Any) -> tuple[Optional[int], list[int]]:
        """Personal PK: armies is a {host_id: BattleUserArmies} map. The own host's
        host_score is the own score; every other host is an opponent."""
        own_score: Optional[int] = None
        opp_scores: list[int] = []
        for host_id, army in (armies or {}).items():
            host_score = getattr(army, "host_score", 0) or 0
            own_side = self._is_own_host(host_id, army)
            anchor = getattr(army, "anchor_id_str", "") or ""
            if own_side:
                own_score = host_score
            else:
                opp_scores.append(host_score)
                self._upsert_opponent(rec, str(host_id), anchor, host_score)
            # anchor_id_str is the host's numeric user id, NOT a display handle, so it
            # is only the participant key — the @id (unique_id) and name come from
            # anchor_info. Passing it as unique_id would clobber the real display_id.
            self._upsert_participant(
                rec, host_id, score=host_score,
                is_own=own_side, side="own" if own_side else "opp", team_id=None,
            )
            self._merge_contributions(rec, army, "own" if own_side else "opp", host_id)
        return own_score, opp_scores

    def _consume_team_armies(self, rec: dict, team_armies: Any) -> tuple[Optional[int], list[int]]:
        """Team PK: each BattleTeamUserArmies is one TEAM, carrying team_total_score,
        the per-host roster (team_users — each BattleTeamUser has the real numeric
        user_id and that host's score) and a single team-aggregate army (user_armies,
        whose anchor_id_str is frequently empty). The team holding the monitored host
        (owner id, matched in team_users) is 自陣.

        Hosts are registered from team_users, keyed by the real user_id — the SAME id
        space as anchor_info (host display names) and the room owner id — so names and
        team membership merge on one key. The earlier code keyed hosts off the single
        user_armies.anchor_id_str, which is empty in real data: that produced one
        nameless "teamN" host per side (rendered "(unknown)") while the named
        anchor_info hosts, lacking a team_id, split off into a phantom extra team. The
        own host's display name comes from self.owner (anchor_info omits the own host),
        so it is registered explicitly even if team_users does not echo the owner id."""
        teams: dict = {}
        for ta in team_armies or []:
            team_id = getattr(ta, "team_id", 0)
            team = teams.setdefault(team_id, {"score": 0, "own": False, "armies": [], "members": {}})
            team["score"] = max(team["score"], getattr(ta, "team_total_score", 0) or 0)
            inner = getattr(ta, "user_armies", None)
            if inner is not None:
                team["armies"].append(inner)
                if getattr(inner, "anchor_id_str", "") == self._owner_id:
                    team["own"] = True
            for member in (getattr(ta, "team_users", None) or []):
                member_id = getattr(member, "user_id_str", "") or str(getattr(member, "user_id", "") or "")
                if not member_id:
                    continue
                score = getattr(member, "score", 0) or 0
                team["members"][member_id] = max(team["members"].get(member_id, 0), score)
                if member_id == self._owner_id:
                    team["own"] = True
        self._log_team_armies_shape(rec, teams)
        own_score: Optional[int] = None
        opp_scores: list[int] = []
        for team_id, team in teams.items():
            side = "own" if team["own"] else "opp"
            if team["own"]:
                own_score = team["score"]
            else:
                opp_scores.append(team["score"])
            # 自陣には必ず監視hostが居る。team_usersがowner idを含まない実データでも自host
            # 名(self.owner)を出せるよう、owner idを明示的に名簿へ加える。
            if team["own"] and self._owner_id:
                team["members"].setdefault(self._owner_id, 0)
            for member_id, member_score in team["members"].items():
                is_own = member_id == self._owner_id
                self._upsert_participant(
                    rec, member_id, score=member_score, is_own=is_own,
                    side=side, team_id=team_id, team_score=team["score"],
                )
                if side == "opp":
                    self._upsert_opponent(rec, member_id, "", member_score)
            # team集約のuser_armies貢献を取り込む。host_idは必ず実host(team_users由来の
            # member id)に寄せる。team集約のanchor_id_strはチームid("1"/"2"等のplaceholder)
            # のことがあり、それをhost_idにするとカードが参加hostへ紐づけられず貢献者が描画
            # から脱落する(人数もカードと不一致になる)。anchorが実memberの時だけ採用し、
            # それ以外は代表member(自陣はowner)へ寄せる。
            for inner in team["armies"]:
                anchor = getattr(inner, "anchor_id_str", "") or ""
                if team["own"]:
                    host_key = self._owner_id or (anchor if anchor in team["members"] else "")
                else:
                    host_key = anchor if anchor in team["members"] else ""
                host_key = host_key or next(iter(team["members"]), "") or f"team{team_id}"
                self._merge_contributions(rec, inner, side, host_key)
        return own_score, opp_scores

    def _log_team_armies_shape(self, rec: dict, teams: dict) -> None:
        """Diagnostic, one line per battle: record the real team PK proto shape —
        whether team_users carries the host roster and whether each team's single
        user_armies exposes a usable anchor_id_str — so the team parsing can be
        confirmed against live data rather than the simulation's assumed shape."""
        battle_id = rec.get("battle_id")
        if battle_id in self._team_shape_logged:
            return
        self._team_shape_logged.add(battle_id)
        parts = []
        for team_id, team in teams.items():
            anchors = [getattr(a, "anchor_id_str", "") or "" for a in team["armies"]]
            parts.append(
                "team=%s total=%s own=%s members=%d ids=%s armies=%d anchors=%s"
                % (team_id, team["score"], team["own"], len(team["members"]),
                   list(team["members"].keys())[:6], len(team["armies"]), anchors)
            )
        logger.info(
            "team_armies shape for battle %s | %s", battle_id, " || ".join(parts),
            extra={"event": "collector.team_armies_shape_observed",
                   "ctx": {"battle_id": battle_id, "owner_id": self._owner_id,
                           "teams": len(teams), "shape": " || ".join(parts)}},
        )

    def _upsert_opponent(self, rec: dict, host_id: str, anchor_id: str, score: int) -> None:
        entry = next((o for o in rec["opponents"] if o.get("user_id") == host_id), None)
        if entry is None:
            entry = {"user_id": host_id, "unique_id": anchor_id, "nickname": "", "avatar": "", "score": 0}
            rec["opponents"].append(entry)
        if score:
            entry["score"] = score

    def _upsert_participant(
        self,
        rec: dict,
        user_id: Any,
        *,
        unique_id: str = "",
        nickname: str = "",
        avatar: str = "",
        score: Optional[int] = None,
        is_own: bool = False,
        side: Optional[str] = None,
        team_id: Optional[int] = None,
        team_score: Optional[int] = None,
    ) -> Optional[dict]:
        """Record one battle host. Unlike own_score/opp_score (a 2-sided collapse),
        participants preserves every host individually so personal multi (3/4コラ)
        and team NvM render with the real roster. is_own is sticky: once the
        monitored host is identified it is never downgraded to opponent."""
        uid = str(user_id or "")
        if not uid:
            return None
        entry = rec["participants"].get(uid)
        if entry is None:
            entry = {
                "user_id": uid,
                "unique_id": "",
                "nickname": "",
                "avatar": "",
                "score": 0,
                "is_own": False,
                "team_id": None,
                "team_score": 0,
                "side": "opp",
            }
            rec["participants"][uid] = entry
        if unique_id:
            entry["unique_id"] = unique_id
        if nickname:
            entry["nickname"] = nickname
        if avatar:
            entry["avatar"] = avatar
        if score:
            entry["score"] = score
        if is_own:
            entry["is_own"] = True
            entry["side"] = "own"
        elif side and not entry["is_own"]:
            entry["side"] = side
        if team_id is not None:
            entry["team_id"] = team_id
        if team_score:
            entry["team_score"] = team_score
        return entry

    def _recount_battles(self) -> None:
        """Battle count and battle_points reflect only real contests — aborted PKs
        (CANCEL / REJECT / CUT_SHORT) and duplicate per-action events are excluded."""
        active = [r for r in self._battles.values() if not r.get("aborted")]
        self.stats["battles"] = len(active)
        self.stats["battle_points"] = sum(r["own_score"] for r in active)

    def _has_ongoing_battle(self) -> bool:
        """A non-aborted PK that has not reached FINISH is still in progress — same
        rule _battle_public uses for the public ``ongoing`` flag."""
        return any(
            not r.get("aborted") and r.get("action") != BATTLE_ACTION_FINISH
            for r in self._battles.values()
        )

    def _merge_contributions(self, rec: dict, army: Any, side: str, host_id: Any = "") -> None:
        """host_id is the recipient host's id (the participant key), so contributions
        can be grouped per 配信者 — required to show, in multi/team PKs, which host on
        which side each gift backed."""
        host = str(host_id or "")
        for contrib in (getattr(army, "user_armies", None) or []):
            num_id = getattr(contrib, "user_id_str", "") or str(getattr(contrib, "user_id", "") or "")
            key = num_id or getattr(contrib, "nickname", "")
            if not key:
                continue
            entry = rec["contributions"].get(key)
            if entry is None:
                entry = {
                    "user_id": num_id,
                    # armiesは@handleを持たない(user_id_strは数値ID)。@handleはGift event
                    # 側で数値IDを突合して補完する。ここでは表示名のみ確定。
                    "unique_id": "",
                    "nickname": getattr(contrib, "nickname", "") or "(unknown)",
                    "avatar": _image_url(getattr(contrib, "avatar_thumb", None)),
                    "side": side,
                    "host_id": host,
                    "score": 0,
                    "diamonds": 0,
                }
                rec["contributions"][key] = entry
                self._persist_avatar(entry["nickname"], entry["avatar"])
            entry["side"] = side
            if host:
                entry["host_id"] = host
            entry["nickname"] = getattr(contrib, "nickname", "") or entry["nickname"]
            # score = バトルスコア(PKポイント)。diamond_score = 実弾(コイン)で、相手陣は
            # 別Roomのため通常0(=不明)。自陣の実弾はGift eventから数値IDで突合して補完する。
            entry["score"] = max(entry["score"], getattr(contrib, "score", 0) or 0)
            entry["diamonds"] = max(entry["diamonds"], getattr(contrib, "diamond_score", 0) or 0)
            avatar = _image_url(getattr(contrib, "avatar_thumb", None))
            if avatar:
                entry["avatar"] = avatar

    async def _on_gift(self, event: GiftEvent) -> None:
        user = _user_payload(event.user)
        gift_name = event.gift.name or "(gift)"
        diamonds_each = event.gift.diamond_count or 0
        gift_image = _image_url(getattr(event.gift, "image", None))
        gift_id = int(getattr(event.gift, "id", 0) or 0)
        self._persist_gift_icon(gift_id, gift_image)
        # Battleのグローブ刺さり率をcoin帯別に集計するため、gift_id→単価を記録する。
        # armies eventはgift_idのみ持ち単価を欠くので、ここで見た価格で写像できるようにする。
        if gift_id and diamonds_each:
            self._gift_coins[gift_id] = diamonds_each
        # 表示するバッジ(ギフターLv画像は常時、メンバーバッジ画像はLv数値が無い時のみ)を
        # URLが新鮮なうちに事前取得しておき、履歴でも残るようにする。
        self._persist_badge(user["gifter_badge"])
        if not user["fans_level"]:
            self._persist_badge(user["member_badge"])
        if event.streaking:
            await self._emit_only(
                "gift_streak",
                {
                    "user": user,
                    "gift_name": gift_name,
                    "repeat_count": event.repeat_count,
                    "diamonds_each": diamonds_each,
                    "text": f"{user['nickname']} が {gift_name} をStreak中 x{event.repeat_count}",
                },
            )
            return
        count = max(event.repeat_count, 1)
        diamonds = diamonds_each * count
        self.stats["gifts"] += count
        self.stats["diamonds"] += diamonds
        bucket = self._bucket()
        bucket["gifts"] += count
        bucket["diamonds"] += diamonds
        # 不変ID優先(user_id -> unique_id -> nickname)で名寄せ。プロフィールはself.users
        # に集約し、gifterエントリはidentity_keyと集計値のみ持つ(重複保持を避ける)。
        # 身元不明(key='')はrankingに載せない。表示名 "(unknown)" をkeyにすると別人の
        # giftが1人分として合算されるため(self.usersも同じ理由で登録しない)。
        gifter_key = self._touch_user(user)
        if gifter_key:
            gifter = self.gifters.setdefault(
                gifter_key,
                {"gifts": 0, "diamonds": 0, "items": {}},
            )
            gifter["gifts"] += count
            gifter["diamonds"] += diamonds
            gifter["items"][gift_name] = gifter["items"].get(gift_name, 0) + count
        gift_type = self.gift_types.setdefault(
            gift_name,
            {"name": gift_name, "count": 0, "diamonds": 0, "diamonds_each": diamonds_each},
        )
        gift_type["count"] += count
        gift_type["diamonds"] += diamonds
        create_time_sec = self._create_time_sec(event)
        await self._record(
            "gift",
            {
                "user": user,
                "gift_name": gift_name,
                "repeat_count": count,
                "diamonds_each": diamonds_each,
                "diamonds": diamonds,
                "gift_image": gift_image,
                "gift_id": gift_id,
                "text": f"{user['nickname']} が {gift_name} x{count} を送りました ({diamonds} diamonds)",
                **_identity_signals(event),
            },
            create_time=create_time_sec,
        )
        # 自陣の貢献者はGift eventから再構成される(armiesはUser内訳を欠く)。PK中はここで
        # battlesを再配信しないと、新しい貢献者がarmies/battle eventが来るまで反映されない。
        # throttle(force無し)で過負荷を防ぐため、PK中以外は再配信しない。
        if self._has_ongoing_battle():
            # グローブ窓中のギフトは単価を確定してpending化し、critは後続armiesのdelta一致で
            # 解決する。窓外giftもdelta poolの掃除用に控えておく(偽critの防止)。
            if not self._record_glove_candidate(gift_id, diamonds_each, count, create_time_sec):
                self._record_glove_offwindow_gift(diamonds_each, count, create_time_sec)
            await self._broadcast_battles()

    async def _on_comment(self, event: CommentEvent) -> None:
        user = _user_payload(event.user)
        self.stats["comments"] += 1
        self._bucket()["comments"] += 1
        payload = {
            "user": user,
            "comment": event.comment,
            "text": f"{user['nickname']}: {event.comment}",
            **_identity_signals(event),
            **_comment_signals(event),
        }
        emotes = _emote_payload(event)
        if emotes:
            payload["emotes"] = emotes
        await self._record("comment", payload, create_time=self._create_time_sec(event))

    async def _on_like(self, event: LikeEvent) -> None:
        user = _user_payload(event.user)
        self.stats["likes_total"] = max(self.stats["likes_total"], event.total or 0)
        self._bucket()["likes"] += event.count
        await self._record(
            "like",
            {
                "user": user,
                "count": event.count,
                "total": event.total,
                "text": f"{user['nickname']} がLike x{event.count} (累計 {event.total})",
                **_follow_signals(event.user),
            },
            create_time=self._create_time_sec(event),
        )

    async def _on_follow(self, event: FollowEvent) -> None:
        user = _user_payload(event.user)
        self.stats["follows"] += 1
        self._bucket()["follows"] += 1
        self._save_follower_count(event)
        await self._record(
            "follow", {"user": user, "text": f"{user['nickname']} がFollowしました"},
            create_time=self._create_time_sec(event),
        )

    def _save_follower_count(self, event: FollowEvent) -> None:
        """FollowEventが同梱する配信者のfollower総数(絶対値)を残す。

        stats["follows"]はevent本数なので、unfollowも収集が切れていた間の増減も表せない。
        こちらはTikTok側が持つ総数そのものなので、配信中の純増を差で出せる。ただし値は
        結果整合で前後する(実観測: 81507の次に81465)ため、単調化や補間はせず届いた値を
        そのまま残し、解釈は解析側に委ねる。値が動いた時だけ1点書く。"""
        count = _as_int(getattr(event, "follow_count", None))
        if not count or self.session_id is None or count == self._follower_saved:
            return
        try:
            self._storage.add_follower_sample(
                self.session_id, time.time(), self._create_time_sec(event), count
            )
            self._follower_saved = count
        except Exception:
            logger.error(
                "failed to persist the streamer's follower total; this datapoint is "
                "lost from the session's follower curve",
                exc_info=True,
                extra={"event": "collector.follower_sample_persist_failed",
                       "ctx": {"follower_count": count}},
            )

    async def _on_share(self, event: ShareEvent) -> None:
        user = _user_payload(event.user)
        self.stats["shares"] += 1
        self._bucket()["shares"] += 1
        await self._record(
            "share",
            {"user": user, "text": f"{user['nickname']} がLIVEをShareしました",
             **_share_signals(event)},
            create_time=self._create_time_sec(event),
        )

    async def _on_join(self, event: JoinEvent) -> None:
        user = _user_payload(event.user)
        self.stats["joins"] += 1
        self._bucket()["joins"] += 1
        await self._record(
            "join",
            {"user": user, "text": f"{user['nickname']} が入室しました",
             **_enter_signals(event), **_follow_signals(event.user)},
            create_time=self._create_time_sec(event),
        )

    async def _on_subscribe(self, event: SubscribeEvent) -> None:
        user = _user_payload(getattr(event, "user", None))
        self.stats["subscribes"] += 1
        await self._record(
            "subscribe", {"user": user, "text": f"{user['nickname']} がSubscribeしました"},
            create_time=self._create_time_sec(event),
        )

    def _record_envelope(self, row: dict) -> None:
        """宝箱/Portalの実測を1件溜める。

        markerの不応期(_add_driver_marker)とは**別のgate**にする。不応期は「1演出=1 mask onset」
        へ畳むためのもので、mask窓としては正しい。だが測定では1件ずつが別の支出であり、
        時間で畳むと投下coinの合計が失われる。重複除外はenvelope_id(同一性)で行う —
        実測で同じenvelope_idがNEW/HIDEの2回届いており、時間窓より厳密に畳める。

        同じenvelope_idが再訪したときは、後から来た非NULL値で埋める(HIDE通知はbusiness_type
        とidしか持たないので、先にHIDEが来てもNEWの実測値で上書きされる)。
        """
        key = row.get("envelope_id")
        if key:
            existing = self._envelope_index.get(key)
            if existing is not None:
                for field, value in row.items():
                    if value is not None and existing.get(field) is None:
                        existing[field] = value
                return
            self._envelope_index[key] = row
        self._envelopes.append(row)

    async def _on_portal(self, event: Any) -> None:
        """ポータル(他配信からの誘導流入)。入室が構造的に押し上がる交絡窓なので、解析の
        placeboから除外するためのmask源としてmarkerに残す(入室scoreへは算入しない)。
        PortalEvent/EnvelopePortalEventの両系統を同一markerへ寄せる。1ポータルで複数message
        (invite/ping/finish)が飛んでも、後段のmaskは窓のunionを取るため無害。診断capも並行。

        payloadのportal_infoは**Portalが閉じた時点の実移動人数**(trans_count)を運ぶ。
        移動「元」のroomを示すfieldは無い(実payloadを全key走査して確認済み: room_idは受信側
        =自室のみ)。したがって「どの配信者から流入したか」は取得不能で、ここでも推測しない。
        """
        self._mark_data()
        self._add_driver_marker("portal", "ポータル")
        self._capture_sample("PortalEvent", event)
        info = getattr(event, "portal_info", None)
        if info is not None:
            self._record_envelope({
                "kind": "portal_closed",
                "envelope_id": _text(getattr(info, "id", None)),
                "time": time.time(),
                "create_time": self._create_time_sec(event),
                "business_type": None,
                "diamond_count": None,
                "people_count": None,
                "trans_count": _as_int(getattr(info, "trans_count", None)),
                "unpack_at": None,
                "sender_user_id": _text(getattr(info, "sender_id", None)),
                "sender_unique_id": None,
                "data": {"portal_display": _as_int(
                    getattr(event, "portal_display", None))},
            })

    async def _on_envelope(self, event: EnvelopeEvent) -> None:
        """宝箱(红包)。開封待ちで入室が誘引される交絡窓。mask源としてmarkerに残す。

        payloadのenvelope_infoは投下coin(diamond_count)・定員(people_count)・開封時刻
        (unpack_at)・送信者を運ぶ。実測で確認した注意点:
        - business_type=4 は**Portalの送信**である("sent a Portal"表示)。閉鎖側のPortalEvent
          とは別messageで、idも別値なので結合しない
        - business_type=19(Super Fan Box)は**diamond_countを持たない**。0で埋めない
        - 送信者は配信者とは限らない(実測でbt=19は視聴者@sinbakwk35kが送信)。
          「配信者の支出」と決めつけられないので、送信者をそのまま残す
        """
        self._mark_data()
        self._add_driver_marker("envelope", "宝箱")
        self._capture_sample("EnvelopeEvent", event)
        info = getattr(event, "envelope_info", None)
        if info is not None:
            self._record_envelope({
                "kind": "envelope",
                "envelope_id": _text(getattr(info, "envelope_id", None)),
                "time": time.time(),
                "create_time": _epoch_seconds(getattr(info, "create_time", None))
                or self._create_time_sec(event),
                "business_type": _as_int(getattr(info, "business_type", None)),
                "diamond_count": _as_int(getattr(info, "diamond_count", None)),
                "people_count": _as_int(getattr(info, "people_count", None)),
                "trans_count": None,
                "unpack_at": _epoch_seconds(getattr(info, "unpack_at", None)),
                "sender_user_id": _text(getattr(info, "send_user_id", None)),
                "sender_unique_id": _text(getattr(info, "send_user_name", None)),
                "data": {"display": _text(getattr(event, "display", None)),
                         "skin_id": _as_int(getattr(info, "skin_id", None))},
            })

    async def _on_room_user(self, event: RoomUserSeqEvent) -> None:
        self._mark_data()
        self.stats["viewers"] = event.m_total
        self.stats["viewers_peak"] = max(
            self.stats.get("viewers_peak", 0) or 0, event.m_total or 0
        )
        self.stats["total_viewers"] = event.total_user
        self.stats["anonymous"] = event.anonymous
        self._bucket()["viewers"] = event.m_total
        if self.session_id is not None:
            try:
                self._storage.add_viewer_sample(
                    self.session_id,
                    time.time(),
                    self._create_time_sec(event),
                    event.m_total,
                    event.total_user,
                    event.anonymous,
                )
            except Exception:
                # この時点の同接サンプルは失われ、再取得の手段は無い。
                logger.error(
                    "failed to persist a viewer sample; this datapoint is lost from the "
                    "session's viewer curve", exc_info=True,
                    extra={"event": "collector.viewer_sample_persist_failed",
                           "ctx": {"viewers": event.m_total}},
                )
            self._save_contributors(event)
        self._update_rates()
        await self._broadcast_stats()

    def _save_contributors(self, event: RoomUserSeqEvent) -> None:
        """RoomUserSeqが運ぶTikTok公式の上位貢献者Ranking(累積score)を時系列で残す。

        こちらのgift eventの積み上げとは独立な系列なので、突き合わせれば収集の取りこぼし量が
        実測できる。毎message書くと冗長なので、設定間隔を空けた上で内容が変わった時だけ書く。
        scoreは文字列で届くことがあるため数値化するが、数値化できない値は捨てる(捏造しない)。"""
        contributors = getattr(event, "m_contributors", None) or []
        if not contributors:
            return
        now = time.time()
        if now - self._contrib_saved_at < self._settings.get("contributor_sample_seconds"):
            return
        rows = []
        for item in contributors:
            m_user = getattr(item, "m_user", None)
            user = _user_payload(m_user)
            if not user["unique_id"]:
                # @handleはUser protoのusernameに入る(unique_idという名のfieldは実wireに
                # 存在しない)。identity_keyは不変user_idで決まるので順位は変わらないが、
                # 突合結果を人が読むときの手掛かりとして持たせる。
                user["unique_id"] = getattr(m_user, "username", "") or ""
            rows.append(
                {
                    "rank": _as_int(getattr(item, "m_rank", None)),
                    "score": _as_int(getattr(item, "m_score", None)),
                    "user": user,
                }
            )
        sig = tuple(
            (r["rank"], r["score"], r["user"]["user_id"], r["user"]["nickname"]) for r in rows
        )
        if sig == self._contrib_saved_sig:
            return
        # 間隔gateは書き込みの成否によらず進める(失敗が続いても毎message叩きに行かない)。
        # 内容の指紋は書けた時だけ更新し、失敗した内容は次の機会に書き直す。
        self._contrib_saved_at = now
        try:
            self._storage.add_contributor_samples(
                self.session_id, now, self._create_time_sec(event), rows
            )
            self._contrib_saved_sig = sig
        except Exception:
            logger.error(
                "failed to persist a contributor ranking sample; this snapshot of "
                "TikTok's cumulative contribution ranking is lost",
                exc_info=True,
                extra={"event": "collector.contributor_sample_persist_failed",
                       "ctx": {"contributors": len(rows)}},
            )

    async def _broadcast_stats(self) -> None:
        now = time.time()
        if now - self._last_stats_sent < 0.25:
            return
        self._last_stats_sent = now
        await self._broadcast({"type": "stats", "data": self.stats})

    async def _broadcast_battles(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_battles_sent < 0.5:
            return
        self._last_battles_sent = now
        await self._broadcast({"type": "battles", "data": self.battles_snapshot()})

    def _update_rates(self) -> None:
        cutoff = time.time() - 60.0
        gifts = diamonds = comments = likes = 0
        for bucket in reversed(self.timeline):
            if bucket["start"] + self._bucket_seconds <= cutoff:
                break
            gifts += bucket["gifts"]
            diamonds += bucket["diamonds"]
            comments += bucket["comments"]
            likes += bucket["likes"]
        self.stats["rate_gifts"] = gifts
        self.stats["rate_diamonds"] = diamonds
        self.stats["rate_comments"] = comments
        self.stats["rate_likes"] = likes
        if self._notifier is not None:
            # 既に毎回算出している直近1分のcoin量をそのまま閾値判定へ渡す。通知のために
            # 別系列を持たない。submitはnon-blockingで例外を返さない。
            self._notifier.on_coin_rate(self.unique_id, float(diamonds))

    async def _run_simulation(self) -> None:
        # 実modeの _run と同じく、このtaskの全logに監視対象を載せる。simulationのlogが
        # 相関の付かない別物に見えると、simでの再現と実配信のlogを突き合わせられない。
        ctx_unique_id.set(self.unique_id)
        rng = random.Random()
        # simulation用のサンプルGift Icon(TikTok webcastの静的resource URL)。署名なしの
        # 静的resourceなので期限切れせず、avatar proxyの許可host(.tiktokcdn.com)にも合致する。
        # GLvグレードバッジ画像もこの既知resourceを流用し、表示経路を確実に検証できるようにする。
        sim_icon = (
            "https://p16-webcast.tiktokcdn.com/img/alisg/webcast-sg/resource/"
            "aca72c59f99d08b0c0d1cd6cc79dbb16.png~tplv-obj.webp"
        )

        def _sim_grade_badge(url, level=0):
            # 実proto(USER_GRADEバッジ)と同形: _badge_image が image_badge.image_model の
            # url_list[0] を、_badge_level が combine_badge_struct.str の overlay text を読む。
            return SimpleNamespace(
                badge_scene=BADGE_SCENE_USER_GRADE,
                image_badge=SimpleNamespace(image_model=SimpleNamespace(url_list=[url])),
                combine_badge_struct=SimpleNamespace(str=str(level)) if level else None,
                string_badge=None,
                text_badge=None,
            )

        def _sim_fans(level):
            # 実proto(fans_club_info)と同形: _user_payload が fans_level を数値で読む。
            return SimpleNamespace(fans_level=level, badge=None)

        # idは数値アカウントID。Gift event(_user_payload)とBattleのarmies貢献は同じidで
        # 突合するため、両者で一致するよう各userにidを与える。fans_club_info=MLv(数値)、
        # badge_list=GLv(数値+画像)。desert_foxはどちらも持たず、素のuserで非表示を確認する。
        users = [
            SimpleNamespace(unique_id="yorha2b", nick_name="YoRHa二号B型", id=2001,
                            fans_club_info=_sim_fans(30), badge_list=[_sim_grade_badge(sim_icon, 45)]),
            SimpleNamespace(unique_id="pod042", nick_name="Pod 042", id=2002,
                            fans_club_info=_sim_fans(12)),
            SimpleNamespace(unique_id="operator6o", nick_name="Operator 6O", id=2003,
                            badge_list=[_sim_grade_badge(sim_icon, 22)]),
            SimpleNamespace(unique_id="desert_fox", nick_name="Desert Fox", id=2004),
            SimpleNamespace(unique_id="sand_walker", nick_name="Sand Walker", id=2005,
                            fans_club_info=_sim_fans(5)),
            SimpleNamespace(unique_id="machine_lf", nick_name="Machine Lifeform", id=2006,
                            badge_list=[_sim_grade_badge(sim_icon, 8)]),
        ]
        # (gift_id, name, diamonds)。gift_idはsimの安定値(実IDと衝突しない範囲)。
        gifts = [
            (900001, "バラ", 1),
            (900002, "TikTok", 1),
            (900003, "指ハート", 5),
            (900004, "ドーナツ", 30),
            (900005, "ハートの手", 100),
            (900006, "マネーガン", 500),
            (900007, "ギャラクシー", 1000),
        ]
        comments = [
            "こんにちは！",
            "この砂漠、見覚えがある",
            "Glory to Mankind",
            "すごい！",
            "🎉🎉🎉",
            "がんばれ〜",
            "Battle待ってます",
        ]
        try:
            await asyncio.sleep(1.5)
            self.session_id = self._storage.create_session(self.unique_id, self._bucket_seconds)
            # simulationは1 task=1 sessionなので、実modeのようなloop scopeは要らない。
            # cancel後の _persist_final まで束ねたままにしたいので reset もしない。
            ctx_session_id.set(self.session_id)
            self.state = STATE_CONNECTED
            self.steps["live_check"] = "done"
            self.steps["websocket"] = "done"
            self.steps["receiving"] = "active"
            self.room_id = rng.randrange(10**18, 10**19)
            self._owner_id = "sim_owner"
            self.stats["connected_at"] = time.time()
            self._add_conn_marker("connect", "LIVE接続")
            if self.session_id is not None:
                self._storage.update_session(self.session_id, STATE_CONNECTED, self.room_id)
            # 実modeの _prepare_session と同じ start 行を出す。simだけ start が欠けると
            # ops_events が「終わりだけある」不揃いな表になり、突合scriptが書けない。
            self._storage.record_ops_event(
                logger, "session.started",
                f"simulationのsessionを開始しました（room {self.room_id}）",
                severity=OPS_INFO,
                detail={"room_id": self.room_id,
                        "bucket_seconds": self._bucket_seconds,
                        "simulation": True},
            )
            logger.info(
                "simulation connected to a synthetic live (room %s)", self.room_id,
                extra={"event": "collector.simulation_connected",
                       "ctx": {"room_id": self.room_id}},
            )
            await self._notify_state()
            await self._record(
                "system",
                {"text": f"Simulation mode: @{self.unique_id} の擬似LIVEに接続しました。"},
            )
            viewers = rng.randint(80, 150)
            likes_total = 0
            tick = 0
            sim_collab_channel = None
            # TikTok側が算出する累積貢献score(RoomUserSeqのm_contributors)の擬似値。
            # 自前のgift集計より必ず多め(取りこぼしがある前提)に積み、突合で差が出る形にする。
            # keyはuser.id(SimpleNamespaceは__eq__を持つためunhashableでkeyにできない)。
            sim_contrib: dict = {}
            sim_users_by_id = {u.id: u for u in users}
            # 配信者のfollower総数(FollowEventのfollow_count)。実配信では結果整合で
            # 前後するので、その揺れも再現する(単調増加だと後段の前提を誤らせる)。
            sim_followers = rng.randint(3000, 90000)
            while True:
                await asyncio.sleep(rng.uniform(0.4, 1.4))
                tick += 1
                user = rng.choice(users)
                if tick % 3 == 0:
                    viewers = max(1, viewers + rng.randint(-6, 8))
                    anonymous = max(0, int(viewers * rng.uniform(0.2, 0.4)))
                    top = sorted(sim_contrib.items(), key=lambda kv: -kv[1])[:5]
                    await self._on_room_user(
                        SimpleNamespace(
                            m_total=viewers, total_user=viewers + tick * 2, anonymous=anonymous,
                            m_contributors=[
                                SimpleNamespace(
                                    m_rank=i, m_score=score, m_user=sim_users_by_id[uid]
                                )
                                for i, (uid, score) in enumerate(top, start=1)
                            ],
                        )
                    )
                roll = rng.random()
                if roll < 0.45:
                    await self._on_comment(
                        SimpleNamespace(user=user, comment=rng.choice(comments))
                    )
                elif roll < 0.65:
                    count = rng.randint(1, 15)
                    likes_total += count
                    await self._on_like(
                        SimpleNamespace(user=user, count=count, total=likes_total)
                    )
                elif roll < 0.82:
                    await self._on_join(SimpleNamespace(user=user))
                elif roll < 0.95:
                    gid, name, diamonds = rng.choice(gifts)
                    repeat = rng.randint(1, 5)
                    await self._on_gift(
                        SimpleNamespace(
                            user=user,
                            gift=SimpleNamespace(id=gid, name=name, diamond_count=diamonds, image=sim_icon),
                            streaking=False,
                            repeat_count=repeat,
                        )
                    )
                    # 収集の取りこぼしぶんを上乗せしてTikTok側の累積scoreを作る。
                    sim_contrib[user.id] = sim_contrib.get(user.id, 0) + int(
                        diamonds * repeat * rng.uniform(1.0, 1.15)
                    )
                elif roll < 0.98:
                    sim_followers = max(0, sim_followers + rng.choice([1, 1, 1, 2, -1, -3]))
                    await self._on_follow(
                        SimpleNamespace(user=user, follow_count=sim_followers)
                    )
                else:
                    await self._on_share(SimpleNamespace(user=user))
                if tick % 60 == 0:
                    await self._simulate_battle(rng, users)
                # 擬似コラボ窓(非BattleのLinkMic): 開始→roster(guest1名)→終了 を
                # LinkLayerEvent経由で流し、入室コンテキスト3分類の収集/集計を検証する。
                if tick % 80 == 20:
                    sim_collab_channel = rng.randrange(10**18, 10**19)
                    await self._on_link_layer(
                        SimpleNamespace(
                            channel_id=sim_collab_channel,
                            create_channel_content=SimpleNamespace(
                                owner=SimpleNamespace(uid=9001, room_id=self.room_id)),
                            list_content=SimpleNamespace(user_list=SimpleNamespace(
                                linked_list=[SimpleNamespace(link_user=SimpleNamespace(uid=7777))])),
                        )
                    )
                elif tick % 80 == 60 and sim_collab_channel:
                    await self._on_link_layer(
                        SimpleNamespace(
                            channel_id=sim_collab_channel,
                            finish_content=SimpleNamespace(
                                owner=SimpleNamespace(uid=9001), finish_reason=1),
                        )
                    )
                    sim_collab_channel = None
        except asyncio.CancelledError:
            self.state = STATE_DISCONNECTED
            self.steps["receiving"] = "done"
            self._add_conn_marker("disconnect", "切断")
            self._persist_final()
            await self._notify_state()
            logger.info(
                "simulation stopped",
                extra={"event": "collector.simulation_stopped", "ctx": {}},
            )

    async def _simulate_battle(self, rng: "random.Random", users: list) -> None:
        """Drive _on_battle/_on_armies with shaped sample data covering the real
        battle topologies: personal 1v1, personal multi (3コラ/4コラ — a free-for-all
        ranked by score), and team NvM. Scores arrive via the same proto shapes the
        live paths read (the flat armies map for personal, team_armies for team), so
        the Battle tab / battle.html exercise the full participant model. Host ids are
        kept consistent between armies and anchor_info so rosters merge, and ~1 in 8
        PKs is cut short to exercise the aborted-battle exclusion."""
        battle_id = rng.randrange(10**6)
        topology = rng.choice(["1v1", "1v1", "3way", "4way", "team2v2", "team3v3"])
        is_team = topology.startswith("team")
        # 実TikTokは3host以上のPKを常にteam_armiesで送り、**個人マルチ(3コラ/4コラ)も
        # 「1人陣営×N」のteam構造**になる(各陣営のteam_idにそのhost自身のuser_idが入る。
        # 実data 195件で確認)。flat armiesで届くのは1v1だけ。simもこの形状に合わせないと
        # 個人マルチが実modeと違う経路を通り、形式判定(core.battle.battle_type)と
        # スコアバーのN分割を検証できない。
        uses_team_armies = is_team or topology in ("3way", "4way")
        aborted = rng.random() < 0.12
        now_ms = int(time.time() * 1000)

        pool = [u for u in users if u.unique_id != self.unique_id] or users

        # Build the host roster. The monitored streamer is always "sim_owner"
        # (matching _owner_id); every other host gets a distinct, stable id so the
        # armies map key, team anchor_id_str and anchor_info user_id all agree.
        # sidesは陣営(team_id, members): 実team戦は陣営placeholder("1"/"2")、個人マルチは
        # 1人陣営でteam_id=そのhost id。
        if is_team:
            per_team = 2 if topology == "team2v2" else 3
            own_team = ["sim_owner"] + [f"ally_{i}" for i in range(1, per_team)]
            opp_team = [f"rival_{i}" for i in range(per_team)]
            extra_hosts = own_team[1:] + opp_team
            sides = [(1, own_team), (2, opp_team)]
        else:
            n_opp = {"1v1": 1, "3way": 2, "4way": 3}[topology]
            extra_hosts = [f"rival_{i}" for i in range(n_opp)]
            sides = [(hid, [hid]) for hid in (["sim_owner"] + extra_hosts)]

        display = {}
        for idx, hid in enumerate(extra_hosts):
            u = pool[idx % len(pool)]
            display[hid] = (u.unique_id, u.nick_name)
        # Mirror the real proto nesting (BattleUserInfoWrapper.user_info.user) so the
        # simulation exercises the same _capture_opponents path as live data.
        anchor_info = [
            SimpleNamespace(user_id=hid, user_info=SimpleNamespace(user=SimpleNamespace(
                user_id=hid, nick_name=nick, display_id=uid, avatar_thumb=None)))
            for hid, (uid, nick) in display.items()
        ]

        await self._on_battle(SimpleNamespace(
            battle_id=battle_id, action=BATTLE_ACTION_OPEN,
            battle_setting=SimpleNamespace(
                start_time_ms=now_ms, end_time_ms=now_ms + 300000, duration=300,
                battle_type=2 if is_team else 1),
            team_users=[1, 2] if uses_team_armies else None,
            team_armies=[1, 2] if uses_team_armies else None,
            anchor_info=anchor_info,
        ))
        if aborted:
            await self._on_battle(SimpleNamespace(
                battle_id=battle_id, action=BATTLE_ACTION_CUT_SHORT, battle_setting=None,
                team_users=None, team_armies=None, anchor_info=anchor_info))
            return

        def contribs(own: bool, tag: str) -> list:
            if own:
                # user_id_strは数値ID(str(u.id))にして、Gift event由来の自陣実弾と
                # 数値IDで突合できるようにする(実データと同じ突合経路をsimでも再現)。
                return [
                    SimpleNamespace(user_id_str=str(u.id), user_id=u.id, nickname=u.nick_name,
                                    score=rng.randint(100, 6000), diamond_score=0, avatar_thumb=None)
                    for u in rng.sample(users, k=min(3, len(users)))
                ]
            return [
                SimpleNamespace(user_id_str=f"{tag}_fan{i}", user_id=0, nickname=f"{tag} fan{i}",
                                score=rng.randint(100, 6000), diamond_score=0, avatar_thumb=None)
                for i in range(rng.randint(1, 2))
            ]

        scores = {hid: 0 for hid in (["sim_owner"] + extra_hosts)}
        # Spread the score updates over time (just past the sample window) so the
        # simulated battle produces a multi-point score series the chart can plot,
        # mirroring how a real PK's score climbs across its ~5 minutes.
        sample_gap = self._settings.get("battle_score_sample_seconds") + 0.5
        # グローブ(Critical Strike)のtestdata: personal PKで高確率に自陣狙いの窓を張り、窓中に
        # 自室Gift event(単価確定→pending化)を出し、自hostスコアをその寄与分だけ正確に跳ねさせて
        # armiesのdelta厳密一致でcritを解決させる。実modeも同じ経路で埋まる。
        sim_glove = (not is_team) and rng.random() < 0.85
        sim_tiers = [8, 30, 80, 300, 800, 2000, 5000, 9000, 18000, 35000]
        if sim_glove:
            gstart = int(time.time())
            self._capture_glove_window(SimpleNamespace(
                battle_id=battle_id,
                msg_type=SimpleNamespace(name="BATTLE_CARD_MSG_TYPE_USE_CRITICAL_STRIKE_CARD"),
                use_critical_strike_card=SimpleNamespace(card_info=SimpleNamespace(
                    to_anchor_id_str="sim_owner", to_anchor_id="sim_owner",
                    effect_time_sec=gstart, send_time_sec=gstart, effect_last_duration=600,
                    multiple=5, critical_strike_rate_low=20, critical_strike_rate_high=30)),
            ))
        for round_no in range(rng.randint(5, 8)):
            if round_no:
                await asyncio.sleep(sample_gap)
            # 実modeと同じくgift/armiesの時刻はserver時計(create_time)で揃える。
            # simでは実配信のserver時計に相当するものがこのtickになる。
            tick = int(time.time())
            base_message = SimpleNamespace(create_time=tick)
            glove_gift = None
            if sim_glove and round_no:
                # 窓中の自室Gift eventを1件pending化し、自hostスコアをその寄与分
                # (crit=窓倍率×単価 / 通常=単価)だけ跳ねさせ、直後のarmiesのdelta
                # 厳密一致でcritを解決させる(gift→armiesの順序を再現)。round 0は
                # 基準scoreが未観測でdeltaが取れないため出さない。
                unit = rng.choice(sim_tiers)
                gid = 900000 + sim_tiers.index(unit)
                self._gift_coins[gid] = unit
                if self._record_glove_candidate(gid, unit, 1, tick):
                    glove_gift = unit * (GLOVE_MULTIPLE if rng.random() < 0.25 else 1)
            for hid in scores:
                if hid == "sim_owner" and glove_gift is not None:
                    scores[hid] += glove_gift
                else:
                    scores[hid] += rng.randint(50, 400)
            if uses_team_armies:
                # 実proto(BattleTeamUserArmies)に合わせる: 1陣営=1 entry。team_usersが
                # 全hostの名簿(実user_id+score)、user_armiesは陣営集約1個で、anchor_id_str
                # は実データ同様に空。host名簿はanchor_info(名前)とuser_idで結合する。
                team_armies = []
                for team_id, members in sides:
                    own = "sim_owner" in members
                    total = sum(scores[h] for h in members)
                    agg = []
                    for hid in members:
                        agg += contribs(own, hid)
                    inner = SimpleNamespace(
                        host_score=total, anchor_id_str="", user_armies=agg)
                    team_armies.append(SimpleNamespace(
                        team_id=team_id, team_total_score=total, user_armies=inner,
                        team_users=[
                            SimpleNamespace(user_id=0, user_id_str=hid, score=scores[hid])
                            for hid in members
                        ]))
                await self._on_armies(SimpleNamespace(
                    base_message=base_message,
                    battle_id=battle_id, armies=None, team_armies=team_armies))
            else:
                own_ua = contribs(True, "own")
                armies = {
                    "sim_owner": SimpleNamespace(
                        host_score=scores["sim_owner"], anchor_id_str="sim_owner",
                        user_armies=own_ua),
                }
                for hid in extra_hosts:
                    armies[hid] = SimpleNamespace(
                        host_score=scores[hid], anchor_id_str=hid,
                        user_armies=contribs(False, hid))
                await self._on_armies(SimpleNamespace(
                    base_message=base_message,
                    battle_id=battle_id, team_armies=None, armies=armies))
        # Simulate the opponent-room gift capture (Part 2): give 敵陣 contributors a
        # 実弾(コイン) value distinct from their BS(score) so the BS/実弾 併記 is visible
        # in testdata. Real mode fills this from the opponent room listener.
        if self._settings.get("monitor_opponent_rooms"):
            rec = self._battles.get(battle_id)
            if rec:
                for c in rec["contributions"].values():
                    if c["side"] != "own" and not c["diamonds"]:
                        c["diamonds"] = int((c["score"] or 0) * rng.uniform(0.6, 1.4))
        await self._on_battle(SimpleNamespace(
            battle_id=battle_id, action=BATTLE_ACTION_FINISH, battle_setting=None,
            team_users=[1, 2] if uses_team_armies else None,
            team_armies=[1, 2] if uses_team_armies else None, anchor_info=anchor_info))

    def _create_time_sec(self, event) -> Optional[float]:
        """TikTok server timestamp (CommonMessageData.create_time) of an event in
        epoch seconds, or None when absent (never fabricated). The proto carries it
        as int64 in either seconds or milliseconds depending on the message, so the
        unit is normalized by magnitude: epoch seconds stay below 1e11 until well
        past year 5000, while millisecond stamps are ~1e12 today. This source-clock
        time is what lets the burn-in lock comments to the video without the
        consumer-side arrival drift (see Mode B in video_overlay)."""
        base = getattr(event, "base_message", None)
        raw = getattr(base, "create_time", 0) if base is not None else 0
        try:
            raw = int(raw or 0)
        except (TypeError, ValueError):
            return None
        if raw <= 0:
            return None
        is_ms = raw > 100_000_000_000
        sec = raw / 1000.0 if is_ms else float(raw)
        if not self._create_time_logged:
            self._create_time_logged = True
            logger.info(
                "first event create_time observed: raw=%s -> %.3fs (unit=%s)",
                raw, sec, "ms" if is_ms else "s",
                extra={"event": "collector.create_time_observed",
                       "ctx": {"raw": raw, "create_time_seconds": round(sec, 3),
                               "unit": "ms" if is_ms else "s"}},
            )
        return sec

    async def _record(self, kind: str, payload: dict, create_time: Optional[float] = None) -> None:
        self._mark_data()
        self.stats["events_total"] += 1
        entry = {"kind": kind, "time": time.time(), "create_time": create_time, **payload}
        # 受信eventの逐一trace。全event種が通る最高頻度pathなので level guard は必須で、
        # INFO運用では1行も出ない。DEBUG時だけ「何が届いていたか」を時系列で辿れる。
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "event recorded: %s", kind,
                extra={"event": "collector.event_recorded",
                       "ctx": {"kind": kind,
                               "has_create_time": create_time is not None,
                               "events_total": self.stats["events_total"]}},
            )
        self.recent_events.append(entry)
        # Single capture point: any user that lands in history (comment / gift /
        # follow / share / join / subscribe) gets their avatar pooled by id, so it
        # is reusable across sessions for the browser, 履歴 and the video burn-in.
        self._persist_user_avatar(entry.get("user"))
        owner_changed = self._follow_owner_identity(entry.get("user"))
        if self.session_id is not None:
            try:
                self._storage.add_event(self.session_id, entry)
            except Exception:
                # add_eventはbatch writer/journal込みでの受け口なので、ここで例外が出た
                # 場合このeventはどこにも残らない。再送も無い。
                logger.error(
                    "failed to persist a %s event; it is lost from this session's "
                    "history", kind, exc_info=True,
                    extra={"event": "collector.event_persist_failed",
                           "ctx": {"kind": kind}},
                )
        self._update_rates()
        await self._broadcast({"type": "event", "data": entry})
        await self._broadcast_stats()
        if owner_changed:
            await self._notify_state()

    async def _emit_only(self, kind: str, payload: dict) -> None:
        self._mark_data()
        entry = {"kind": kind, "time": time.time(), **payload}
        await self._broadcast({"type": "event", "data": entry})

    def _mark_data(self) -> None:
        """Record that data just arrived over the live websocket. Resets the idle
        watchdog so an active stream (even a quiet one sending only viewer-count
        heartbeats) is never mistaken for a frozen connection."""
        self._last_data_at = time.time()

    async def _notify_state(self) -> None:
        await self._broadcast({"type": "state", "data": self.snapshot()})
