import asyncio
import logging
import time
from collections import deque
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
    LiveEndEvent,
    RoomUserSeqEvent,
    ShareEvent,
    SubscribeEvent,
)

from config import get_event_history_size

logger = logging.getLogger("tictok.collector")

Broadcast = Callable[[dict], Awaitable[None]]

STATE_IDLE = "idle"
STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"
STATE_DISCONNECTED = "disconnected"
STATE_ENDED = "ended"
STATE_ERROR = "error"

STEP_IDS = ["request", "live_check", "websocket", "receiving"]

STEP_LABELS = {
    "request": "Request受付",
    "live_check": "LIVE状態確認",
    "websocket": "WebSocket接続",
    "receiving": "Data受信中",
}


def _empty_stats() -> dict:
    return {
        "viewers": 0,
        "total_viewers": 0,
        "likes_total": 0,
        "comments": 0,
        "gifts": 0,
        "diamonds": 0,
        "follows": 0,
        "shares": 0,
        "joins": 0,
        "subscribes": 0,
        "events_total": 0,
        "connected_at": None,
    }


def _user_payload(user: Any) -> dict:
    if user is None:
        return {"unique_id": "", "nickname": "(unknown)"}
    unique_id = getattr(user, "unique_id", "") or ""
    nickname = getattr(user, "nick_name", "") or unique_id or "(unknown)"
    return {"unique_id": unique_id, "nickname": nickname}


class TikTokCollector:
    def __init__(self, broadcast: Broadcast) -> None:
        self._broadcast = broadcast
        self._client: Optional[TikTokLiveClient] = None
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self.state = STATE_IDLE
        self.error_message: Optional[str] = None
        self.unique_id: Optional[str] = None
        self.room_id: Optional[int] = None
        self.stats = _empty_stats()
        self.steps = {step: "pending" for step in STEP_IDS}
        self.recent_events: deque = deque(maxlen=get_event_history_size())

    def snapshot(self) -> dict:
        return {
            "status": self.state,
            "error_message": self.error_message,
            "unique_id": self.unique_id,
            "room_id": self.room_id,
            "stats": self.stats,
            "steps": [
                {"id": step, "label": STEP_LABELS[step], "status": self.steps[step]}
                for step in STEP_IDS
            ],
            "recent_events": list(self.recent_events),
        }

    async def start(self, unique_id: str) -> None:
        async with self._lock:
            if self.state in (STATE_CONNECTING, STATE_CONNECTED):
                raise RuntimeError("収集は既に実行中です。先に停止してください。")
            self.unique_id = unique_id
            self.room_id = None
            self.error_message = None
            self.stats = _empty_stats()
            self.recent_events.clear()
            self.steps = {step: "pending" for step in STEP_IDS}
            self.steps["request"] = "done"
            self.steps["live_check"] = "active"
            self.state = STATE_CONNECTING
            self._client = self._build_client(unique_id)
            self._task = asyncio.create_task(self._run(), name="tictok-collector")
        logger.info("collection start requested: unique_id=%s", unique_id)
        await self._notify_state()

    async def stop(self) -> None:
        async with self._lock:
            client = self._client
            task = self._task
        if client is None or self.state not in (STATE_CONNECTING, STATE_CONNECTED):
            raise RuntimeError("収集は実行されていません。")
        logger.info("collection stop requested: unique_id=%s", self.unique_id)
        try:
            await client.disconnect()
        except Exception:
            logger.exception("disconnect failed")
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=10)
            except asyncio.TimeoutError:
                task.cancel()
                logger.warning("collector task cancelled after timeout")

    async def _run(self) -> None:
        client = self._client
        try:
            await client.connect(fetch_room_info=True)
            if self.state == STATE_CONNECTED:
                self.state = STATE_DISCONNECTED
        except UserOfflineError:
            self._fail("live_check", f"@{self.unique_id} は現在LIVE配信していません。")
        except UserNotFoundError:
            self._fail("live_check", f"@{self.unique_id} というUserが見つかりません。")
        except AgeRestrictedError:
            self._fail("live_check", "年齢制限付きのLIVEのため接続できません。")
        except TikTokLiveError as exc:
            logger.exception("TikTokLive error")
            self._fail("websocket", f"TikTok接続Error: {exc}")
        except asyncio.CancelledError:
            self.state = STATE_DISCONNECTED
        except Exception as exc:
            logger.exception("unexpected collector error")
            self._fail("websocket", f"予期しないError: {exc}")
        finally:
            if self.state in (STATE_DISCONNECTED, STATE_ENDED):
                self.steps["receiving"] = "done"
            await self._notify_state()
            logger.info("collector finished: state=%s", self.state)

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
        return client

    async def _on_connect(self, event: ConnectEvent) -> None:
        self.state = STATE_CONNECTED
        self.steps["live_check"] = "done"
        self.steps["websocket"] = "done"
        self.steps["receiving"] = "active"
        self.room_id = self._client.room_id if self._client else None
        self.stats["connected_at"] = time.time()
        logger.info("connected: unique_id=%s room_id=%s", self.unique_id, self.room_id)
        await self._notify_state()
        await self._record(
            "system",
            {"text": f"@{self.unique_id} のLIVE (Room {self.room_id}) に接続しました。"},
        )

    async def _on_disconnect(self, event: DisconnectEvent) -> None:
        if self.state == STATE_CONNECTED:
            self.state = STATE_DISCONNECTED
            await self._record("system", {"text": "LIVEから切断されました。"})
            await self._notify_state()

    async def _on_live_end(self, event: LiveEndEvent) -> None:
        self.state = STATE_ENDED
        await self._record("system", {"text": "LIVE配信が終了しました。"})
        await self._notify_state()

    async def _on_gift(self, event: GiftEvent) -> None:
        user = _user_payload(event.user)
        gift_name = event.gift.name or "(gift)"
        diamonds_each = event.gift.diamond_count or 0
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
        await self._record(
            "gift",
            {
                "user": user,
                "gift_name": gift_name,
                "repeat_count": count,
                "diamonds_each": diamonds_each,
                "diamonds": diamonds,
                "text": f"{user['nickname']} が {gift_name} x{count} を送りました ({diamonds} diamonds)",
            },
        )

    async def _on_comment(self, event: CommentEvent) -> None:
        user = _user_payload(event.user)
        self.stats["comments"] += 1
        await self._record(
            "comment",
            {"user": user, "comment": event.comment, "text": f"{user['nickname']}: {event.comment}"},
        )

    async def _on_like(self, event: LikeEvent) -> None:
        user = _user_payload(event.user)
        if event.total:
            self.stats["likes_total"] = event.total
        await self._record(
            "like",
            {
                "user": user,
                "count": event.count,
                "total": event.total,
                "text": f"{user['nickname']} がLike x{event.count} (累計 {event.total})",
            },
        )

    async def _on_follow(self, event: FollowEvent) -> None:
        user = _user_payload(event.user)
        self.stats["follows"] += 1
        await self._record(
            "follow", {"user": user, "text": f"{user['nickname']} がFollowしました"}
        )

    async def _on_share(self, event: ShareEvent) -> None:
        user = _user_payload(event.user)
        self.stats["shares"] += 1
        await self._record(
            "share", {"user": user, "text": f"{user['nickname']} がLIVEをShareしました"}
        )

    async def _on_join(self, event: JoinEvent) -> None:
        user = _user_payload(event.user)
        self.stats["joins"] += 1
        await self._record(
            "join", {"user": user, "text": f"{user['nickname']} が入室しました"}
        )

    async def _on_subscribe(self, event: SubscribeEvent) -> None:
        user = _user_payload(getattr(event, "user", None))
        self.stats["subscribes"] += 1
        await self._record(
            "subscribe", {"user": user, "text": f"{user['nickname']} がSubscribeしました"}
        )

    async def _on_room_user(self, event: RoomUserSeqEvent) -> None:
        self.stats["viewers"] = event.m_total
        self.stats["total_viewers"] = event.total_user
        await self._broadcast({"type": "stats", "data": self.stats})

    async def _record(self, kind: str, payload: dict) -> None:
        self.stats["events_total"] += 1
        entry = {"kind": kind, "time": time.time(), **payload}
        self.recent_events.append(entry)
        await self._broadcast({"type": "event", "data": entry})
        await self._broadcast({"type": "stats", "data": self.stats})

    async def _emit_only(self, kind: str, payload: dict) -> None:
        entry = {"kind": kind, "time": time.time(), **payload}
        await self._broadcast({"type": "event", "data": entry})

    async def _notify_state(self) -> None:
        await self._broadcast({"type": "state", "data": self.snapshot()})
