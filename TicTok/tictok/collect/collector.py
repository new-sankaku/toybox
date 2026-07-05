import asyncio
import json
import logging
import random
import re
import time

import httpx
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Optional

from TikTokLive import TikTokLiveClient
from TikTokLive.client.errors import (
    AgeRestrictedError,
    TikTokLiveError,
    UserNotFoundError,
    UserOfflineError,
)
from TikTokLive.events import (
    CommentEvent,
    ConnectEvent,
    DisconnectEvent,
    FollowEvent,
    GiftEvent,
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
    RankUpdateEvent,
    RankTextEvent,
    RankToastEvent,
    RoomUserSeqEvent,
    ShareEvent,
    SubscribeEvent,
    WeeklyRankRewardEvent,
)

from TikTokLive.client.web.web_settings import WebDefaults

from tictok.core.config import (
    get_locale_country,
    get_locale_lang,
    get_locale_lang_country,
    get_locale_tz,
    get_log_dir,
    get_record_dir,
    get_sample_dir,
    get_sign_api_key,
    get_simulation,
    get_timeline_limit,
)
from tictok.collect.live_resolver import LiveResolveBlocked
from tictok.collect.sampler import EventSampler
from tictok.record.recorder import Recorder, extract_stream_url, ffmpeg_available
from tictok.storage import _identity_key

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

# グローブ(Critical Strike card)の倍率。自陣ギフトの5×は、貢献者のバトルスコア(PKポイント)が
# そのギフトの単価の何倍跳ねたかで判定する。armiesのgift fieldは相手側しか載らず、自陣貢献者の
# user_armiesは単価を欠くため、単価はGift event・5×はarmiesスコア跳ね、をuser_idで突合する。
GLOVE_MULTIPLE = 5
# 実測倍率の許容幅。5×critはスコア跳ね/単価がほぼ5.0に乗る一方、通常ギフトは1×付近に集まる
# ため、倍率-この値(=4.5)以上をcritとする。実ダンプ実測で窓中発動率≈24-27%(20-30%仕様)に一致。
GLOVE_CRIT_TOLERANCE = 0.5


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
    logger.info("locale applied: lang=%s region=%s", lang, country)


def _apply_sign_api_key() -> None:
    """Send the EulerStream API key as X-Api-Key on sign requests, lifting the
    anonymous-tier rate limit. The key is a secret, so only its presence is
    logged, never its value."""
    api_key = get_sign_api_key()
    if api_key:
        WebDefaults.tiktok_sign_api_key = api_key
    logger.info("sign api key configured: %s", bool(api_key))


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

# Grace period before resuming a recording that ended on its own while the live
# is still connected. Lets a concurrent websocket drop surface first, so a full
# host drop is handled once by the reconnect path rather than by a doomed resume.
RESUME_SETTLE_DELAY = 3

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
            logger.warning("opponent room listener failed for @%s", self._handle, exc_info=True)

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
                pass
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass


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
    nickname = getattr(user, "nick_name", "") or unique_id or "(unknown)"
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
        "identity_key": _identity_key(user_id, unique_id, nickname),
    }


class TikTokCollector:
    def __init__(
        self, unique_id: str, broadcast: Broadcast, storage, settings, probe_gate=None, resolver=None, gift_icons=None, avatar_pool=None, avatar_proxy=None, record_video: bool = True
    ) -> None:
        self._broadcast = broadcast
        self._storage = storage
        self._settings = settings
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
        self.markers: deque = deque(maxlen=500)
        self.gifters: dict = {}
        # User正規化プロフィール(identity_key -> profile)。変更されうる属性(名前/@handle/
        # avatar/Lv/badge)をSession中1か所に集約し、gifters等はidentity_keyのみ持つ。
        self.users: dict = {}
        self.gift_types: dict = {}
        # gift_id -> 単価(diamonds_each)。Battleのグローブ(Critical Strike)刺さり率を
        # coin帯別に集計する際、armies eventのgift_idを価格帯へ写像するために使う。
        self._gift_coins: dict = {}
        self._battles: dict = {}
        # グローブcrit判定(自陣・二系統突合)の作業state。詳細は _reset_session_data 参照。
        self._glove_own_score: dict = {}
        self._glove_resolved_score: dict = {}
        self._glove_pending: dict = {}
        # コラボ(非BattleのLinkMic)接続窓。channel_id -> {start, guests_max}(接続中)、
        # finish/session終了で _collab_windows へ確定。入室コンテキスト3分類(doc §14)に使う。
        self._collab_open: dict = {}
        self._collab_windows: list = []
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
        self._last_stats_sent = 0.0
        # Timestamp of the last datum received from TikTok over the live websocket.
        # The idle watchdog uses it to detect a silent half-open connection (host
        # network drop) where connect() never returns and no disconnect fires.
        self._last_data_at: Optional[float] = None
        self._idle_disconnect = False
        # Whether recording should be running for the current live. Set when a
        # recording starts (auto or manual), cleared on manual stop, so a
        # websocket reconnect resumes only a recording the user did not stop.
        self._recording_desired = False
        # Room id of a broadcast classified as restricted (members-only / age). While
        # the same room keeps resolving live, the watch loop holds the "restricted"
        # status without reconnecting, so no sign request is spent and no empty
        # session is created. Cleared on a successful connect or when the room ends.
        self._restricted_room_id: Optional[int] = None
        # Per-target preference: when False this monitor only collects data and never
        # records video (auto-record is skipped and manual recording is rejected).
        self.record_video = record_video
        self._record_dir = get_record_dir()
        self._room_info: dict = {}
        self.recorder: Optional[Recorder] = None
        # battle_id -> [OpponentRoomListener]. PK中だけ相手RoomのGiftを拾うlistener群。
        self._opp_listeners: dict = {}

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
            "markers": list(self.markers),
        }

    def _touch_user(self, user: dict) -> str:
        """User正規化プロフィールをSession registryに反映し、identity_keyを返す。変更され
        うる属性は最新の非空値で上書きする(storage.users表と同じ最新値上書きロジック)。"""
        key = user.get("identity_key") or _identity_key(
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
        public = [self._battle_public(b) for b in battles]
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
        return {
            **rec,
            "contributions": contributions,
            "bonus_missions": self._public_bonus_missions(rec),
            "participants": self._public_participants(rec),
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

    def _reset_session_data(self) -> None:
        self._reconnect_attempt = 0
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
        self.gifters = {}
        self.users = {}
        self.gift_types = {}
        self._battles = {}
        # グローブcrit判定(自陣・二系統突合)。armiesのuser_armiesは自陣貢献者のバトルスコア
        # (PKポイント)しか持たず単価を欠くため、単価はGift event、5×判定は貢献者スコアの跳ね、
        # という二系統をuser_idで突合する。いずれもrec外(非永続)に持つ。
        # battle_id -> {contributor user_id: 直近cumulative score}
        self._glove_own_score = {}
        # battle_id -> {contributor user_id: 窓中giftへ既に割当済のcumulative score}
        self._glove_resolved_score = {}
        # battle_id -> [{sender, resolved, multiple, ev(=glove_events内の同一dict)}]
        self._glove_pending = {}
        self._collab_open = {}
        self._collab_windows = []
        self._team_shape_logged = set()
        # 前Sessionのlistenerは_runの終了処理でstop済み。dictだけ空に戻す。
        self._opp_listeners = {}
        self._owner_id = ""
        self.owner = {"unique_id": self.unique_id, "nickname": self.unique_id, "avatar": "", "league": ""}
        self._apply_cached_owner()
        self._league = ""
        self._owner_warned = False
        self._create_time_logged = False
        self._recording_desired = False
        # We only reset a session for a recordable live; a restriction hold no longer applies.
        self._restricted_room_id = None

    def _prepare_session(self) -> None:
        self._reset_session_data()
        self.steps = {step: "pending" for step in STEP_IDS}
        self.steps["request"] = "done"
        self.steps["live_check"] = "done"
        self.steps["websocket"] = "active"
        self.state = STATE_CONNECTING
        self.session_id = self._storage.create_session(self.unique_id, self._bucket_seconds)
        self._client = self._build_client(self.unique_id)
        logger.info("session prepared: unique_id=%s session_id=%s", self.unique_id, self.session_id)

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
        logger.info("monitoring start requested: unique_id=%s", self.unique_id)
        await self._notify_state()

    async def stop(self) -> None:
        async with self._lock:
            client = self._client
            task = self._task
        if self.state not in ACTIVE_STATES:
            raise RuntimeError("収集は実行されていません。")
        logger.info("collection stop requested: unique_id=%s", self.unique_id)
        self._stop_requested = True
        if client is not None and self.state == STATE_CONNECTED:
            try:
                await client.disconnect()
            except Exception:
                logger.exception("disconnect failed")
        elif task is not None:
            task.cancel()
        if task is not None:
            done, pending = await asyncio.wait({task}, timeout=10)
            if pending:
                task.cancel()
                logger.warning("collector task cancelled after timeout")

    async def _run(self) -> None:
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
                ):
                    continue
                self._prepare_session()
                await self._notify_state()
                outcome = await self._session_loop()
                await self._stop_all_opponent_listeners()
                await self._stop_recording()
                if outcome == "restricted":
                    # Recording is impossible for this broadcast. Stay a non-terminal
                    # "restricted" watcher (status held by _announce_waiting) so a later
                    # normal broadcast on a new room id is still detected and recorded.
                    # Drop the empty session row this attempt created.
                    self._restricted_room_id = self._resolved_room_id
                    self._discard_session()
                    self.state = STATE_RESTRICTED
                    await self._notify_state()
                    logger.info(
                        "restricted live, holding watch: unique_id=%s room=%s",
                        self.unique_id, self._resolved_room_id,
                    )
                    continue
                self._persist_final()
                await self._notify_state()
                if outcome in ("stopped", "fatal"):
                    break
                logger.info("session closed (%s), resuming watch: unique_id=%s", outcome, self.unique_id)
        except asyncio.CancelledError:
            self.state = STATE_DISCONNECTED
            await self._stop_all_opponent_listeners()
            await self._stop_recording()
            self._persist_final()
        finally:
            if self.state in (STATE_DISCONNECTED, STATE_ENDED):
                self.steps["receiving"] = "done"
            await self._notify_state()
            logger.info("collector finished: state=%s", self.state)

    async def start_recording(self) -> None:
        if not self.record_video:
            raise RuntimeError("この監視対象は動画保存OFF（データのみ）です。先に動画保存をONにしてください。")
        if self.state != STATE_CONNECTED:
            raise RuntimeError("録画は配信に接続中のみ開始できます。")
        if self.recorder is not None and self.recorder.is_active:
            raise RuntimeError("既に録画中です。")
        url, quality = extract_stream_url(self._room_info)
        if not url:
            raise RuntimeError("この配信のstream URLを取得できませんでした（録画不可）。")
        recorder = Recorder(
            self.unique_id, self._record_dir, self.session_id,
            keep_hls=bool(self._settings.get("recording_keep_hls")),
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
        self.recorder = recorder
        self._recording_desired = True
        self._add_marker("record", "録画開始")
        await self._record("system", {"text": f"録画を開始しました（quality: {recorder.quality}）。"})
        await self._notify_state()

    async def stop_recording(self) -> None:
        if self.recorder is None or not self.recorder.is_active:
            raise RuntimeError("録画は実行されていません。")
        # User-initiated stop: clear intent so a later reconnect does not resume it.
        self._recording_desired = False
        await self.recorder.stop()
        await self._notify_state()

    async def set_record_video(self, record_video: bool) -> None:
        """Toggle this target's video-saving preference. Turning it off stops any
        recording in progress (and clears the resume intent) so the monitor keeps
        collecting data without keeping video; turning it on lets the next live
        auto-record per the global setting."""
        if self.record_video == record_video:
            return
        self.record_video = record_video
        if not record_video and self.recorder is not None and self.recorder.is_active:
            self._recording_desired = False
            try:
                await self.recorder.stop()
            except Exception:
                logger.exception("failed to stop recording on record_video off for %s", self.unique_id)
        await self._notify_state()

    async def _stop_recording(self) -> None:
        # Monitor/server shutdown: wait for finalize so the mp4 is fully written.
        if self.recorder is not None:
            try:
                await self.recorder.stop(wait=True)
            except Exception:
                logger.exception("failed to stop recording for %s", self.unique_id)

    async def _on_recording_finalized(self, recorder: Recorder) -> None:
        snap = recorder.snapshot()
        # An empty recording captured no data and left no playable artifact (a dead
        # stream URL, e.g. a full host drop that reissues the URL). Drop the row so
        # failed empty attempts don't clutter the recording history.
        empty = snap.get("bytes", 0) <= 0 and recorder.output_path is None
        if recorder.recording_id is not None:
            if empty:
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
        logger.info(
            "%s for live start: unique_id=%s interval=%ss",
            "restricted, watching" if self.state == STATE_RESTRICTED else "waiting",
            self.unique_id,
            self._settings.get("live_check_interval"),
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
                    return True
                failures = 0
                # Resolved offline: a broadcast we were holding as restricted has
                # ended, so drop the hold and let the status revert to plain waiting.
                if self._restricted_room_id is not None:
                    self._restricted_room_id = None
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
                    "live page exposes no LiveRoom for %s (consecutive=%d): user may "
                    "not exist or the page rendered partially; continuing to watch",
                    self.unique_id,
                    failures,
                )
            except LiveResolveBlocked as exc:
                # TikTok did not return parseable live state (WAF challenge
                # unsolved or transient). One concise line, then back off; the
                # browser resolver normally clears this on retry.
                failures += 1
                logger.warning(
                    "live check blocked for %s (consecutive=%d): %s; backing off",
                    self.unique_id,
                    failures,
                    exc,
                )
            except Exception as exc:
                failures += 1
                logger.warning(
                    "live check failed for %s (consecutive=%d): %s",
                    self.unique_id,
                    failures,
                    exc,
                    exc_info=True,
                )
            # 即時probeは初回のみ。以降の再試行はWAF対策の通常間隔に従う。
            use_priority = False
            if not waiting_announced:
                waiting_announced = True
                await self._announce_waiting()
            await self._live_check_sleep(failures)

    async def _live_check_sleep(self, failures: int) -> None:
        base = self._settings.get("live_check_interval")
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

    async def _session_loop(self) -> str:
        while True:
            outcome, reason = await self._connect_once()
            if outcome != "transient":
                return outcome
            result = await self._wait_for_reconnect(reason)
            if result != "retry":
                return result

    def _discard_session(self) -> None:
        """Delete the empty session row created for a broadcast that turned out to be
        unrecordable (restricted), so failed restricted attempts leave no clutter in
        history. The connect aborted before any owner/event/recording was stored."""
        if self.session_id is None:
            return
        try:
            self._storage.delete_session(self.session_id)
        except Exception:
            logger.exception("failed to discard restricted session %s", self.session_id)
        self.session_id = None

    def _persist_final(self) -> None:
        if self.session_id is None:
            return
        try:
            self._storage.finalize_session(
                self.session_id, self.state, self.stats, list(self.timeline), list(self.markers)
            )
            self._storage.save_battles(
                self.session_id,
                [self._battle_public(b) for b in self._battles.values() if not b.get("aborted")],
            )
            self._storage.save_collab_windows(self.session_id, self._collab_windows_public())
        except Exception:
            logger.exception("failed to persist session %s", self.session_id)
        self._close_battle_raw()
        self.session_id = None

    async def _connect_once(self) -> tuple:
        self._idle_disconnect = False
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
                    "TikTokからのData受信が途絶えたため再接続します（配信側の電波切れの可能性）。",
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
                    "live page no longer exposes LiveRoom for %s; treating as ended",
                    self.unique_id,
                )
                self.state = STATE_ENDED
                return ("ended", None)
            if offline_confirmed:
                self.state = STATE_ENDED
                return ("ended", None)
            logger.info("offline report not confirmed, treating as transient: %s", self.unique_id)
            return ("transient", "TikTokが一時的に未配信と応答しました（再確認では配信中）")
        except UserNotFoundError:
            # room_info reports no LiveRoom for a room we just resolved as live:
            # the broadcast ended or the page rendered partially. End this session
            # (non-terminal) and resume watching instead of killing the monitor.
            logger.info(
                "room_info reports no LiveRoom for %s; treating as ended, resuming watch",
                self.unique_id,
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
            logger.warning("transient TikTokLive error: %s", exc, exc_info=True)
            return ("transient", f"TikTok接続Error: {exc}")
        except httpx.TransportError as exc:
            # Timeout / network drop while fetching the signed websocket: an expected
            # transient hiccup, not a defect. Log one line (no traceback) and reconnect.
            logger.warning("transient network error: %s: %s", type(exc).__name__, exc)
            return ("transient", "TikTokとの通信が一時的にTimeoutしました（再接続します）")
        except Exception as exc:
            logger.warning("transient collector error: %s", exc, exc_info=True)
            return ("transient", f"接続Error: {exc}")
        finally:
            watchdog.cancel()
            try:
                await watchdog
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("idle watchdog error for %s", self.unique_id)
            # Awaiting connect_task does not cancel it when our own coroutine is
            # cancelled (outer stop), so drop any still-running connect here.
            if not connect_task.done():
                connect_task.cancel()
                try:
                    await connect_task
                except (asyncio.CancelledError, Exception):
                    pass

    async def _idle_watchdog(self, connect_task: "asyncio.Future") -> None:
        """Force a reconnect when TikTok stops sending data on a live we believe
        is still connected. This is the only path that recovers a half-open
        websocket (typically a host-side network drop), where connect() never
        returns and no disconnect/live-end event ever fires."""
        timeout = self._settings.get("connection_idle_timeout")
        interval = max(1.0, min(5.0, timeout / 3))
        while not connect_task.done():
            await asyncio.sleep(interval)
            if connect_task.done() or self._stop_requested or self.state == STATE_ENDED:
                continue
            if self._last_data_at is None:
                continue
            idle = time.time() - self._last_data_at
            if idle < timeout:
                continue
            self._idle_disconnect = True
            logger.warning(
                "no data from TikTok for %.0fs (timeout=%ds) while %s on %s; "
                "forcing reconnect (likely host network drop)",
                idle, timeout, self.state, self.unique_id,
            )
            # Prefer a graceful close so the library frees the websocket; fall back
            # to cancelling the blocked connect() if disconnect() is itself stuck.
            try:
                await asyncio.wait_for(self._client.disconnect(), timeout=5)
            except Exception:
                logger.warning(
                    "watchdog graceful disconnect failed for %s; cancelling connect",
                    self.unique_id, exc_info=True,
                )
            if not connect_task.done():
                connect_task.cancel()
            return

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
                "offline confirmation check failed for %s: %s", self.unique_id, exc, exc_info=True
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
            "restricted live detected (%s): unique_id=%s room=%s", source, self.unique_id, room_id
        )
        if self._client is None or room_id is None:
            return
        try:
            url = WebDefaults.tiktok_webcast_url + "/room/info/"
            resp = await self._client.web.get(url=url, extra_params={"room_id": str(room_id)})
            data = (resp.json() or {}).get("data", {}) or {}
        except Exception:
            logger.warning(
                "restriction diagnostics: raw room_info fetch failed for %s",
                self.unique_id, exc_info=True,
            )
            return
        diag = {k: data.get(k) for k in self._RESTRICTION_FIELDS}
        diag["has_prompts"] = "prompts" in data
        diag["data_keys"] = sorted(data.keys())
        logger.warning(
            "restriction diagnostics for %s room=%s: %s", self.unique_id, room_id, diag
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
                "connected room carries sub-only flags: unique_id=%s room=%s %s",
                self.unique_id, self.room_id, flags,
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
            logger.warning(
                "reconnect exhausted after %d attempts for %s (last reason: %s); "
                "returning to watch loop instead of terminating",
                max_attempts, self.unique_id, reason,
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
            "reconnecting (attempt %d/%d, delay %.1fs): %s",
            self._reconnect_attempt,
            max_attempts,
            delay,
            reason,
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
        self._client = self._build_client(self.unique_id)
        return "retry"

    def _fail(self, step: str, message: str) -> None:
        self.steps[step] = "failed"
        self.state = STATE_ERROR
        self.error_message = message
        logger.error("collector failed at %s: %s", step, message)

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
            logger.warning("failed to persist league for %s", self.unique_id, exc_info=True)
        logger.info("league captured: unique_id=%s league=%s", self.unique_id, league)
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
                    "[league-probe] %s @%s: %s = %r", source, self.unique_id, path, value
                )
        except Exception:
            logger.warning("[league-probe] scan failed for %s", source, exc_info=True)

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
        """rank関連eventを辞書化して league scanner にかける。生protoはto_dict()で
        JSON化してから走査する(field名はcamelだが _LEAGUE_KEY_RE がsnake/camel両対応)。"""
        if not self._league_enabled():
            return
        try:
            payload = event.to_dict() if hasattr(event, "to_dict") else event
        except Exception:
            logger.warning("[league-probe] to_dict failed for %s", name, exc_info=True)
            return
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
        reconnected = self._reconnect_attempt > 0
        self._reconnect_attempt = 0
        # We reached a recordable broadcast; any prior restriction hold no longer applies.
        self._restricted_room_id = None
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
                "avatar": _image_url(owner.get("avatar_thumb")),
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
            logger.exception("failed to read room owner for %s", self.unique_id)
        if self.stats["connected_at"] is None:
            self.stats["connected_at"] = time.time()
        self._add_marker("reconnect" if reconnected else "connect", "再接続" if reconnected else "LIVE接続")
        if self.session_id is not None:
            self._storage.update_session(self.session_id, STATE_CONNECTED, self.room_id)
        logger.info("connected: unique_id=%s room_id=%s", self.unique_id, self.room_id)
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
                await self._resume_recording()
        elif self.record_video and self._settings.get("auto_record") and ffmpeg_available():
            try:
                await self.start_recording()
            except Exception as exc:
                logger.warning("auto-record failed to start for %s: %s", self.unique_id, exc)

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

        async def _run() -> None:
            try:
                await self._avatar_pool.persist(owner_id, url)
            except Exception:
                logger.warning("owner avatar persist failed for %s", owner_id, exc_info=True)

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
                logger.warning("gift icon persist failed (id=%s)", gift_id, exc_info=True)

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
                logger.warning("badge prefetch failed: %s", url, exc_info=True)

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
        if self._avatar_pool.has(user_key):
            return

        async def _run() -> None:
            try:
                await self._avatar_pool.persist(user_key, url)
            except Exception:
                logger.warning("user avatar persist failed (user=%s)", user_key, exc_info=True)

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
                    logger.info("pre-cached %d gift icons for %s", n, self.unique_id)
            except Exception:
                logger.warning("gift list pre-cache failed for %s", self.unique_id, exc_info=True)

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
                logger.exception("failed to stop stale recorder before resume for %s", self.unique_id)
        await self._start_replacement_recording()

    async def _start_replacement_recording(self) -> None:
        # Detach the prior recorder (its finalize task runs on independently and
        # persists via its own recording_id) so start_recording's active-guard
        # sees a clean slate even while the old one is still finalizing.
        self.recorder = None
        try:
            await self.start_recording()
        except Exception as exc:
            logger.warning("failed to start replacement recording for %s: %s", self.unique_id, exc)

    async def _maybe_resume_after_finalize(self, recorder: Recorder) -> None:
        """Resume after a recording ends on its own while the live is still
        connected — e.g. the video stream dropped but events keep flowing, so no
        websocket reconnect fires to trigger the reconnect-path resume.

        Resumes only if the finished recording actually captured data. A recording
        that captured nothing indicates a dead stream URL (a full host drop, where
        TikTok reissues the URL); that case is left to the reconnect path, so this
        never spins relaunching ffmpeg against an unrecoverable URL."""
        if recorder is not self.recorder or not self._recording_desired:
            return
        if self.state != STATE_CONNECTED or self._stop_requested:
            return
        if recorder.snapshot().get("bytes", 0) <= 0:
            return
        await asyncio.sleep(RESUME_SETTLE_DELAY)
        if recorder is not self.recorder or not self._recording_desired:
            return
        if self.state != STATE_CONNECTED or self._stop_requested:
            return
        logger.info("recording for %s ended while still live; resuming", self.unique_id)
        await self._start_replacement_recording()

    async def _on_disconnect(self, event: DisconnectEvent) -> None:
        if self.state == STATE_CONNECTED and self._stop_requested:
            self.state = STATE_DISCONNECTED
            self._add_marker("disconnect", "切断")
            await self._record("system", {"text": "収集を停止しました。"})
            await self._notify_state()

    async def _on_live_end(self, event: LiveEndEvent) -> None:
        self.state = STATE_ENDED
        self._add_marker("live_end", "LIVE終了")
        await self._record("system", {"text": "LIVE配信が終了しました。"})
        await self._notify_state()

    def _battle_record(self, battle_id: int) -> dict:
        rec = self._battles.get(battle_id)
        if rec is None:
            now = time.time()
            rec = {
                "battle_id": battle_id,
                "type": None,
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
        appended only once the window elapses or the score changes.

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
        if series:
            last = series[-1]
            within_window = now - last["t"] < self._settings.get("battle_score_sample_seconds")
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

    def _is_own_host(self, host_id: Any, army: Any) -> bool:
        return str(host_id) == self._owner_id or getattr(army, "anchor_id_str", "") == self._owner_id

    def _dump_battle_raw(self, kind: str, event: Any) -> None:
        """検証用: Battle系eventをTikTokから届いた生のまま logs/battle_raw_*.jsonl へ
        追記する。設定 battle_debug_capture がON、かつ実API mode (非simulation) のときだけ
        記録する。失敗してもStackTraceを残すのみで本流の収集は止めない。"""
        if self._simulation or not self._settings.get("battle_debug_capture"):
            return
        to_dict = getattr(event, "to_dict", None)
        if callable(to_dict):
            try:
                payload = to_dict(include_default_values=False)
            except TypeError:
                payload = to_dict()
            except Exception:
                logger.exception("battle raw to_dict failed: kind=%s", kind)
                payload = {"_repr": repr(event)}
        else:
            payload = {"_repr": repr(event)}
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
            logger.exception("failed to write battle raw capture: kind=%s", kind)

    def _close_battle_raw(self) -> None:
        if self._battle_raw_fh is not None:
            try:
                self._battle_raw_fh.close()
            except OSError:
                logger.exception("failed to close battle raw capture handle")
            self._battle_raw_fh = None
            self._battle_raw_path = None

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
            logger.exception("linkmic roster parse failed for %s", self.unique_id)
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
                self._add_marker("collab", "コラボ")
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
        except Exception:
            logger.exception("link layer handling failed for %s", self.unique_id)

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
        # Team vs personal is derived from the presence of team structures in the
        # event itself (not a guessed enum mapping), so an unrecognised battle_type
        # never mislabels the mode.
        if getattr(event, "team_users", None) or getattr(event, "team_armies", None):
            rec["type"] = "team"
        elif rec["type"] is None:
            rec["type"] = "personal"
        self._capture_opponents(rec, getattr(event, "anchor_info", None))
        self._recount_battles()
        label = f"Battle #{battle_id}"
        self._add_marker("battle", label)
        await self._record(
            "battle",
            {"text": f"{label} のEventを受信しました (action={getattr(event, 'action', None)})"},
        )
        if rec.get("aborted") or action == BATTLE_ACTION_FINISH:
            await self._stop_opponent_listeners(battle_id)
        else:
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
        # はSTART messageにしか載らないため、START欠落時は×Nを復元できない(overlayは"BONUS"表示)。
        if not missions:
            logger.warning(
                "battle %s: bonus mission START not seen (mtype=%s); multiplier "
                "unavailable — overlay will show 'BONUS' without xN for this mission",
                battle_id, mtype,
            )
            missions.append({
                "multiplier": 0, "preview_start_ts": None, "task_start_ts": None,
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
                    logger.warning("bonus sum not an int: %r", total)
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
        key = user.get("user_id") or user.get("unique_id") or user.get("nickname")
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
            logger.exception("glove window capture failed for %s", self.unique_id)

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

    def _record_glove_candidate(self, user: dict, gift_id: int, diamonds_each: int, count: int,
                                t: Optional[float]) -> None:
        """自陣グローブ窓中に自陣へ届いた1ギフトを、5×判定待ち(pending)として記録する。単価は
        Gift event(自室)からのみ確実に取れるためここで確定し、crit(5×)は後続armiesの貢献者スコア
        跳ねで解決する。gift時刻は窓・armiesと同じserver epoch秒(create_time)で突合する。"""
        if not diamonds_each or count <= 0:
            return
        sender = str(user.get("user_id") or "")
        if not sender:
            return
        ts = int(t if t is not None else time.time())
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
                "crit": False,
            }
            rec["glove_events"].append(ev)
            self._glove_pending.setdefault(rec["battle_id"], []).append({
                "sender": sender,
                "resolved": False,
                "multiple": window.get("multiple") or GLOVE_MULTIPLE,
                "ev": ev,
            })
            # この送信者の最初のpendingを作る時点のcumulative scoreを割当基点に固定し、以降の
            # スコア増分だけを窓中giftへ帰属させる(窓前の実績スコアを混入させない)。
            resolved = self._glove_resolved_score.setdefault(rec["battle_id"], {})
            resolved.setdefault(sender, self._glove_own_score.setdefault(rec["battle_id"], {}).get(sender, 0))
            return

    def _resolve_glove_crits(self, rec: dict, event: Any) -> None:
        """自陣貢献者(user_armies)のバトルスコアを追い、pending中のグローブ・ギフトの5×を解決する。
        送信者ごとに『まだ帰属していないスコア(avail=現cumulative-割当済)』を古いpendingから順に、
        avail/単価が窓倍率(≈5)付近なら5×、1付近なら通常として食い潰す。armiesはgiftの後に届く前提で、
        まだavailが足りないpendingは次のarmiesまで保留する。pending送信者は自室Gift event由来=自陣
        貢献者のみ照合されるため相手側とは衝突しない。"""
        battle_id = int(getattr(event, "battle_id", 0) or 0)
        own = self._glove_own_score.setdefault(battle_id, {})
        armies = list((getattr(event, "armies", None) or {}).values())
        for ta in (getattr(event, "team_armies", None) or []):
            inner = getattr(ta, "user_armies", None)
            if inner is not None:
                armies.append(inner)
        for army in armies:
            for contrib in (getattr(army, "user_armies", None) or []):
                cid = getattr(contrib, "user_id_str", "") or str(getattr(contrib, "user_id", 0) or "")
                if not cid:
                    continue
                score = int(getattr(contrib, "score", 0) or 0)
                if score > own.get(cid, 0):
                    own[cid] = score
        pending = self._glove_pending.get(battle_id)
        if not pending:
            return
        resolved = self._glove_resolved_score.setdefault(battle_id, {})
        by_sender = {}
        for p in pending:
            if not p["resolved"]:
                by_sender.setdefault(p["sender"], []).append(p)
        for cid, cands in by_sender.items():
            avail = own.get(cid, 0) - resolved.get(cid, 0)
            for cand in cands:  # pendingは生成順=古い順
                total = cand["ev"].get("total") or 0
                if total <= 0:
                    cand["resolved"] = True
                    continue
                mult_win = cand["multiple"]
                ratio = avail / total
                if ratio >= mult_win - GLOVE_CRIT_TOLERANCE:
                    consume = mult_win * total
                    cand["ev"]["crit"] = True
                    cand["ev"]["mult"] = mult_win
                elif ratio >= 1 - GLOVE_CRIT_TOLERANCE:
                    consume = total
                    cand["ev"]["crit"] = False
                    cand["ev"]["mult"] = 1
                else:
                    break  # このgiftのスコアはまだ届いていない。次のarmiesで解決する。
                cand["ev"]["score_delta"] = consume
                cand["resolved"] = True
                avail -= consume
                resolved[cid] = resolved.get(cid, 0) + consume

    async def _on_armies(self, event: LinkMicArmiesEvent) -> None:
        self._dump_battle_raw("LinkMicArmies", event)
        self._mark_data()
        if not self._owner_id:
            if not self._owner_warned:
                self._owner_warned = True
                logger.warning(
                    "room owner id unknown; battle score tracking disabled for %s", self.unique_id
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
            # own/opp score stay 0 for every team battle.
            rec["type"] = "team"
            own_score, opp_scores = self._consume_team_armies(rec, team_armies)
        else:
            own_score, opp_scores = self._consume_host_armies(rec, getattr(event, "armies", None))
        if own_score is not None:
            rec["own_score"] = own_score
        # 自陣貢献者のバトルスコアの跳ねを追い、グローブ窓中に届いたギフト(Gift event側で
        # pending化済)の5×を解決する。armiesのgift fieldは相手側しか載らないため、自陣は
        # この貢献者スコア突合でしか判定できない。
        try:
            self._resolve_glove_crits(rec, event)
        except Exception:
            logger.exception("glove crit resolve failed for %s", self.unique_id)
        if opp_scores:
            rec["opp_score"] = sum(opp_scores) if rec["type"] == "team" else max(opp_scores)
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
            "team_armies shape battle=%s owner=%s | %s",
            battle_id, self._owner_id, " || ".join(parts),
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
        gifter_key = self._touch_user(user) or user["nickname"] or "(unknown)"
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
            },
            create_time=create_time_sec,
        )
        # 自陣の貢献者はGift eventから再構成される(armiesはUser内訳を欠く)。PK中はここで
        # battlesを再配信しないと、新しい貢献者がarmies/battle eventが来るまで反映されない。
        # throttle(force無し)で過負荷を防ぐため、PK中以外は再配信しない。
        if self._has_ongoing_battle():
            # グローブ窓中のギフトは単価を確定してpending化し、5×は後続armiesで解決する。
            self._record_glove_candidate(user, gift_id, diamonds_each, count, create_time_sec)
            await self._broadcast_battles()

    async def _on_comment(self, event: CommentEvent) -> None:
        user = _user_payload(event.user)
        self.stats["comments"] += 1
        self._bucket()["comments"] += 1
        await self._record(
            "comment",
            {"user": user, "comment": event.comment, "text": f"{user['nickname']}: {event.comment}"},
            create_time=self._create_time_sec(event),
        )

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
            },
            create_time=self._create_time_sec(event),
        )

    async def _on_follow(self, event: FollowEvent) -> None:
        user = _user_payload(event.user)
        self.stats["follows"] += 1
        self._bucket()["follows"] += 1
        await self._record(
            "follow", {"user": user, "text": f"{user['nickname']} がFollowしました"},
            create_time=self._create_time_sec(event),
        )

    async def _on_share(self, event: ShareEvent) -> None:
        user = _user_payload(event.user)
        self.stats["shares"] += 1
        self._bucket()["shares"] += 1
        await self._record(
            "share", {"user": user, "text": f"{user['nickname']} がLIVEをShareしました"},
            create_time=self._create_time_sec(event),
        )

    async def _on_join(self, event: JoinEvent) -> None:
        user = _user_payload(event.user)
        self.stats["joins"] += 1
        self._bucket()["joins"] += 1
        await self._record(
            "join", {"user": user, "text": f"{user['nickname']} が入室しました"},
            create_time=self._create_time_sec(event),
        )

    async def _on_subscribe(self, event: SubscribeEvent) -> None:
        user = _user_payload(getattr(event, "user", None))
        self.stats["subscribes"] += 1
        await self._record(
            "subscribe", {"user": user, "text": f"{user['nickname']} がSubscribeしました"},
            create_time=self._create_time_sec(event),
        )

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
                logger.exception(
                    "failed to persist viewer sample for session %s", self.session_id
                )
        self._update_rates()
        await self._broadcast_stats()

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

    async def _run_simulation(self) -> None:
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
            self.state = STATE_CONNECTED
            self.steps["live_check"] = "done"
            self.steps["websocket"] = "done"
            self.steps["receiving"] = "active"
            self.room_id = rng.randrange(10**18, 10**19)
            self._owner_id = "sim_owner"
            self.stats["connected_at"] = time.time()
            self._add_marker("connect", "LIVE接続")
            if self.session_id is not None:
                self._storage.update_session(self.session_id, STATE_CONNECTED, self.room_id)
            logger.info("simulation connected: unique_id=%s", self.unique_id)
            await self._notify_state()
            await self._record(
                "system",
                {"text": f"Simulation mode: @{self.unique_id} の擬似LIVEに接続しました。"},
            )
            viewers = rng.randint(80, 150)
            likes_total = 0
            tick = 0
            sim_collab_channel = None
            while True:
                await asyncio.sleep(rng.uniform(0.4, 1.4))
                tick += 1
                user = rng.choice(users)
                if tick % 3 == 0:
                    viewers = max(1, viewers + rng.randint(-6, 8))
                    anonymous = max(0, int(viewers * rng.uniform(0.2, 0.4)))
                    await self._on_room_user(
                        SimpleNamespace(
                            m_total=viewers, total_user=viewers + tick * 2, anonymous=anonymous
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
                    await self._on_gift(
                        SimpleNamespace(
                            user=user,
                            gift=SimpleNamespace(id=gid, name=name, diamond_count=diamonds, image=sim_icon),
                            streaking=False,
                            repeat_count=rng.randint(1, 5),
                        )
                    )
                elif roll < 0.98:
                    await self._on_follow(SimpleNamespace(user=user))
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
            self._add_marker("disconnect", "切断")
            self._persist_final()
            await self._notify_state()
            logger.info("simulation stopped: unique_id=%s", self.unique_id)

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
        aborted = rng.random() < 0.12
        now_ms = int(time.time() * 1000)

        pool = [u for u in users if u.unique_id != self.unique_id] or users

        # Build the host roster. The monitored streamer is always "sim_owner"
        # (matching _owner_id); every other host gets a distinct, stable id so the
        # armies map key, team anchor_id_str and anchor_info user_id all agree.
        if is_team:
            per_team = 2 if topology == "team2v2" else 3
            own_team = ["sim_owner"] + [f"ally_{i}" for i in range(1, per_team)]
            opp_team = [f"rival_{i}" for i in range(per_team)]
            extra_hosts = own_team[1:] + opp_team
        else:
            n_opp = {"1v1": 1, "3way": 2, "4way": 3}[topology]
            own_team, opp_team = ["sim_owner"], []
            extra_hosts = [f"rival_{i}" for i in range(n_opp)]

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
            team_users=[1, 2] if is_team else None,
            team_armies=[1, 2] if is_team else None,
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
        # 自室Gift event(単価確定→pending化)を出し、同gifterの貢献スコアを一定確率で5×跳ねさせて
        # armies経路でcritを解決させる。実modeもItemCard/Gift/armiesの実eventから同じ経路で埋まる。
        sim_glove = (not is_team) and rng.random() < 0.85
        sim_glove_score = 0
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
            for hid in scores:
                scores[hid] += rng.randint(50, 400)
            if is_team:
                # 実proto(BattleTeamUserArmies)に合わせる: 1チーム=1 entry。team_usersが
                # 全hostの名簿(実user_id+score)、user_armiesはチーム集約1個で、anchor_id_str
                # は実データ同様に空。host名簿はanchor_info(名前)とuser_idで結合する。
                team_armies = []
                for team_id, members in ((1, own_team), (2, opp_team)):
                    total = sum(scores[h] for h in members)
                    agg = []
                    for hid in members:
                        agg += contribs(team_id == 1, hid)
                    inner = SimpleNamespace(
                        host_score=total, anchor_id_str="", user_armies=agg)
                    team_armies.append(SimpleNamespace(
                        team_id=team_id, team_total_score=total, user_armies=inner,
                        team_users=[
                            SimpleNamespace(user_id=0, user_id_str=hid, score=scores[hid])
                            for hid in members
                        ]))
                await self._on_armies(SimpleNamespace(
                    battle_id=battle_id, armies=None, team_armies=team_armies))
            else:
                own_ua = contribs(True, "own")
                if sim_glove:
                    # 窓中の自室Gift eventを1件出してpending化(単価確定)、同gifterの貢献スコアを
                    # 5×or1×跳ねさせ、直後のarmiesでcritを解決させる(gift→armiesの順序を再現)。
                    unit = rng.choice(sim_tiers)
                    gid = 900000 + sim_tiers.index(unit)
                    self._gift_coins[gid] = unit
                    self._record_glove_candidate({"user_id": "sim_glove_gifter"}, gid, unit, 1, time.time())
                    sim_glove_score += unit * (5 if rng.random() < 0.25 else 1)
                    own_ua.append(SimpleNamespace(
                        user_id_str="sim_glove_gifter", user_id=0, nickname="Sim Glove Gifter",
                        score=sim_glove_score, diamond_score=0, avatar_thumb=None))
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
            team_users=[1, 2] if is_team else None,
            team_armies=[1, 2] if is_team else None, anchor_info=anchor_info))

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
                "event create_time observed: raw=%s -> %.3fs (unit=%s) for %s",
                raw, sec, "ms" if is_ms else "s", self.unique_id,
            )
        return sec

    async def _record(self, kind: str, payload: dict, create_time: Optional[float] = None) -> None:
        self._mark_data()
        self.stats["events_total"] += 1
        entry = {"kind": kind, "time": time.time(), "create_time": create_time, **payload}
        self.recent_events.append(entry)
        # Single capture point: any user that lands in history (comment / gift /
        # follow / share / join / subscribe) gets their avatar pooled by id, so it
        # is reusable across sessions for the browser, 履歴 and the video burn-in.
        self._persist_user_avatar(entry.get("user"))
        if self.session_id is not None:
            try:
                self._storage.add_event(self.session_id, entry)
            except Exception:
                logger.exception("failed to persist event for session %s", self.session_id)
        self._update_rates()
        await self._broadcast({"type": "event", "data": entry})
        await self._broadcast_stats()

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
