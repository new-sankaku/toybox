import asyncio
import logging
import random
import time
from collections import deque
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
    LinkMicBattleEvent,
    LiveEndEvent,
    RoomUserSeqEvent,
    ShareEvent,
    SubscribeEvent,
)

from config import (
    get_bucket_seconds,
    get_event_history_size,
    get_simulation,
    get_timeline_limit,
)

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
        "battles": 0,
        "events_total": 0,
        "connected_at": None,
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
        self._bucket_seconds = get_bucket_seconds()
        self._simulation = get_simulation()
        self.timeline: deque = deque(maxlen=get_timeline_limit())
        self.markers: deque = deque(maxlen=500)
        self.gifters: dict = {}
        self.gift_types: dict = {}

    def snapshot(self) -> dict:
        return {
            "status": self.state,
            "simulation": self._simulation,
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

    def timeline_snapshot(self) -> dict:
        return {
            "bucket_seconds": self._bucket_seconds,
            "buckets": list(self.timeline),
            "markers": list(self.markers),
        }

    def summary_snapshot(self) -> dict:
        users = sorted(
            self.gifters.values(),
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

    def _bucket(self) -> dict:
        now = time.time()
        start = int(now // self._bucket_seconds * self._bucket_seconds)
        if not self.timeline or self.timeline[-1]["start"] != start:
            self.timeline.append(_empty_bucket(start, self.stats["viewers"]))
        return self.timeline[-1]

    def _add_marker(self, kind: str, label: str) -> None:
        self.markers.append({"time": time.time(), "kind": kind, "label": label})

    async def start(self, unique_id: str) -> None:
        async with self._lock:
            if self.state in (STATE_CONNECTING, STATE_CONNECTED):
                raise RuntimeError("収集は既に実行中です。先に停止してください。")
            self.unique_id = unique_id
            self.room_id = None
            self.error_message = None
            self.stats = _empty_stats()
            self.recent_events.clear()
            self.timeline.clear()
            self.markers.clear()
            self.gifters = {}
            self.gift_types = {}
            self.steps = {step: "pending" for step in STEP_IDS}
            self.steps["request"] = "done"
            self.steps["live_check"] = "active"
            self.state = STATE_CONNECTING
            if self._simulation:
                self._client = None
                self._task = asyncio.create_task(self._run_simulation(), name="tictok-simulator")
            else:
                self._client = self._build_client(unique_id)
                self._task = asyncio.create_task(self._run(), name="tictok-collector")
        logger.info("collection start requested: unique_id=%s", unique_id)
        await self._notify_state()

    async def stop(self) -> None:
        async with self._lock:
            client = self._client
            task = self._task
        if self.state not in (STATE_CONNECTING, STATE_CONNECTED):
            raise RuntimeError("収集は実行されていません。")
        logger.info("collection stop requested: unique_id=%s", self.unique_id)
        if client is not None:
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
        client.add_listener(LinkMicBattleEvent, self._on_battle)
        return client

    async def _on_connect(self, event: ConnectEvent) -> None:
        self.state = STATE_CONNECTED
        self.steps["live_check"] = "done"
        self.steps["websocket"] = "done"
        self.steps["receiving"] = "active"
        self.room_id = self._client.room_id if self._client else None
        self.stats["connected_at"] = time.time()
        self._add_marker("connect", "LIVE接続")
        logger.info("connected: unique_id=%s room_id=%s", self.unique_id, self.room_id)
        await self._notify_state()
        await self._record(
            "system",
            {"text": f"@{self.unique_id} のLIVE (Room {self.room_id}) に接続しました。"},
        )

    async def _on_disconnect(self, event: DisconnectEvent) -> None:
        if self.state == STATE_CONNECTED:
            self.state = STATE_DISCONNECTED
            self._add_marker("disconnect", "切断")
            await self._record("system", {"text": "LIVEから切断されました。"})
            await self._notify_state()

    async def _on_live_end(self, event: LiveEndEvent) -> None:
        self.state = STATE_ENDED
        self._add_marker("live_end", "LIVE終了")
        await self._record("system", {"text": "LIVE配信が終了しました。"})
        await self._notify_state()

    async def _on_battle(self, event: LinkMicBattleEvent) -> None:
        self.stats["battles"] += 1
        label = f"Battle #{event.battle_id}"
        self._add_marker("battle", label)
        await self._record(
            "battle",
            {"text": f"{label} のEventを受信しました (action={event.action})"},
        )

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
        bucket = self._bucket()
        bucket["gifts"] += count
        bucket["diamonds"] += diamonds
        gifter_key = user["unique_id"] or user["nickname"]
        gifter = self.gifters.setdefault(
            gifter_key,
            {"unique_id": user["unique_id"], "nickname": user["nickname"], "gifts": 0, "diamonds": 0, "items": {}},
        )
        gifter["nickname"] = user["nickname"]
        gifter["gifts"] += count
        gifter["diamonds"] += diamonds
        gifter["items"][gift_name] = gifter["items"].get(gift_name, 0) + count
        gift_type = self.gift_types.setdefault(
            gift_name,
            {"name": gift_name, "count": 0, "diamonds": 0, "diamonds_each": diamonds_each},
        )
        gift_type["count"] += count
        gift_type["diamonds"] += diamonds
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
        self._bucket()["comments"] += 1
        await self._record(
            "comment",
            {"user": user, "comment": event.comment, "text": f"{user['nickname']}: {event.comment}"},
        )

    async def _on_like(self, event: LikeEvent) -> None:
        user = _user_payload(event.user)
        if event.total:
            self.stats["likes_total"] = event.total
        self._bucket()["likes"] += event.count
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
        self._bucket()["follows"] += 1
        await self._record(
            "follow", {"user": user, "text": f"{user['nickname']} がFollowしました"}
        )

    async def _on_share(self, event: ShareEvent) -> None:
        user = _user_payload(event.user)
        self.stats["shares"] += 1
        self._bucket()["shares"] += 1
        await self._record(
            "share", {"user": user, "text": f"{user['nickname']} がLIVEをShareしました"}
        )

    async def _on_join(self, event: JoinEvent) -> None:
        user = _user_payload(event.user)
        self.stats["joins"] += 1
        self._bucket()["joins"] += 1
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
        self._bucket()["viewers"] = event.m_total
        await self._broadcast({"type": "stats", "data": self.stats})

    async def _run_simulation(self) -> None:
        rng = random.Random()
        users = [
            SimpleNamespace(unique_id="yorha2b", nick_name="YoRHa二号B型"),
            SimpleNamespace(unique_id="pod042", nick_name="Pod 042"),
            SimpleNamespace(unique_id="operator6o", nick_name="Operator 6O"),
            SimpleNamespace(unique_id="desert_fox", nick_name="Desert Fox"),
            SimpleNamespace(unique_id="sand_walker", nick_name="Sand Walker"),
            SimpleNamespace(unique_id="machine_lf", nick_name="Machine Lifeform"),
        ]
        gifts = [
            ("Rose", 1),
            ("TikTok", 1),
            ("Finger Heart", 5),
            ("Doughnut", 30),
            ("Hand Hearts", 100),
            ("Money Gun", 500),
            ("Galaxy", 1000),
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
            self.state = STATE_CONNECTED
            self.steps["live_check"] = "done"
            self.steps["websocket"] = "done"
            self.steps["receiving"] = "active"
            self.room_id = rng.randrange(10**18, 10**19)
            self.stats["connected_at"] = time.time()
            self._add_marker("connect", "LIVE接続")
            logger.info("simulation connected: unique_id=%s", self.unique_id)
            await self._notify_state()
            await self._record(
                "system",
                {"text": f"Simulation mode: @{self.unique_id} の擬似LIVEに接続しました。"},
            )
            viewers = rng.randint(80, 150)
            likes_total = 0
            tick = 0
            while True:
                await asyncio.sleep(rng.uniform(0.4, 1.4))
                tick += 1
                user = rng.choice(users)
                if tick % 3 == 0:
                    viewers = max(1, viewers + rng.randint(-6, 8))
                    await self._on_room_user(
                        SimpleNamespace(m_total=viewers, total_user=viewers + tick * 2)
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
                    name, diamonds = rng.choice(gifts)
                    await self._on_gift(
                        SimpleNamespace(
                            user=user,
                            gift=SimpleNamespace(name=name, diamond_count=diamonds),
                            streaking=False,
                            repeat_count=rng.randint(1, 5),
                        )
                    )
                elif roll < 0.98:
                    await self._on_follow(SimpleNamespace(user=user))
                else:
                    await self._on_share(SimpleNamespace(user=user))
                if tick % 90 == 0:
                    await self._on_battle(
                        SimpleNamespace(battle_id=rng.randrange(10**6), action=1)
                    )
        except asyncio.CancelledError:
            self.state = STATE_DISCONNECTED
            self.steps["receiving"] = "done"
            self._add_marker("disconnect", "切断")
            await self._notify_state()
            logger.info("simulation stopped: unique_id=%s", self.unique_id)

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
