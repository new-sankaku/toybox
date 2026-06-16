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
    LinkMicArmiesEvent,
    LinkMicBattleEvent,
    LiveEndEvent,
    RoomUserSeqEvent,
    ShareEvent,
    SubscribeEvent,
)

from config import get_record_dir, get_simulation, get_timeline_limit
from recorder import Recorder, extract_stream_url, ffmpeg_available

logger = logging.getLogger("tictok.collector")

Broadcast = Callable[[dict], Awaitable[None]]

STATE_IDLE = "idle"
STATE_WAITING = "waiting"
STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"
STATE_RECONNECTING = "reconnecting"
STATE_DISCONNECTED = "disconnected"
STATE_ENDED = "ended"
STATE_ERROR = "error"

ACTIVE_STATES = (STATE_WAITING, STATE_CONNECTING, STATE_CONNECTED, STATE_RECONNECTING)

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


def _user_payload(user: Any) -> dict:
    if user is None:
        return {"unique_id": "", "nickname": "(unknown)"}
    unique_id = getattr(user, "unique_id", "") or ""
    nickname = getattr(user, "nick_name", "") or unique_id or "(unknown)"
    return {"unique_id": unique_id, "nickname": nickname}


class TikTokCollector:
    def __init__(self, unique_id: str, broadcast: Broadcast, storage, settings) -> None:
        self._broadcast = broadcast
        self._storage = storage
        self._settings = settings
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
        self._bucket_seconds = settings.get("bucket_seconds")
        self.recent_events: deque = deque(maxlen=settings.get("event_history"))
        self.timeline: deque = deque(maxlen=get_timeline_limit())
        self.markers: deque = deque(maxlen=500)
        self.gifters: dict = {}
        self.gift_types: dict = {}
        self._battles: dict = {}
        self._owner_id: str = ""
        self._owner_warned = False
        self._stop_requested = False
        self._reconnect_attempt = 0
        self._last_stats_sent = 0.0
        self._record_dir = get_record_dir()
        self._room_info: dict = {}
        self.recorder: Optional[Recorder] = None

    def snapshot(self) -> dict:
        return {
            "status": self.state,
            "simulation": self._simulation,
            "error_message": self.error_message,
            "ffmpeg_available": ffmpeg_available(),
            "recording": self.recorder.snapshot() if self.recorder else None,
            "unique_id": self.unique_id,
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

    def _reset_session_data(self) -> None:
        self._reconnect_attempt = 0
        self.room_id = None
        self.error_message = None
        self.stats = _empty_stats()
        self._bucket_seconds = self._settings.get("bucket_seconds")
        self.recent_events = deque(maxlen=self._settings.get("event_history"))
        self.timeline.clear()
        self.markers.clear()
        self.gifters = {}
        self.gift_types = {}
        self._battles = {}
        self._owner_id = ""
        self._owner_warned = False

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
                if not await self._wait_for_live_start(skip_first_check=not first_cycle):
                    break
                first_cycle = False
                self._prepare_session()
                await self._notify_state()
                outcome = await self._session_loop()
                await self._stop_recording()
                self._persist_final()
                await self._notify_state()
                if outcome in ("stopped", "fatal"):
                    break
                logger.info("session closed (%s), resuming watch: unique_id=%s", outcome, self.unique_id)
        except asyncio.CancelledError:
            self.state = STATE_DISCONNECTED
            await self._stop_recording()
            self._persist_final()
        finally:
            if self.state in (STATE_DISCONNECTED, STATE_ENDED):
                self.steps["receiving"] = "done"
            await self._notify_state()
            logger.info("collector finished: state=%s", self.state)

    async def start_recording(self) -> None:
        if self.state != STATE_CONNECTED:
            raise RuntimeError("録画は配信に接続中のみ開始できます。")
        if self.recorder is not None and self.recorder.is_active:
            raise RuntimeError("既に録画中です。")
        url, quality = extract_stream_url(self._room_info)
        if not url:
            raise RuntimeError("この配信のstream URLを取得できませんでした（録画不可）。")
        recorder = Recorder(self.unique_id, self._record_dir)
        await recorder.start(self._room_info, on_finalize=self._on_recording_finalized)
        recorder.recording_id = self._storage.create_recording(
            self.session_id,
            self.unique_id,
            str(recorder.output_path),
            recorder.output_path.name,
            recorder.quality,
            recorder.started_at,
        )
        self.recorder = recorder
        self._add_marker("record", "録画開始")
        await self._record("system", {"text": f"録画を開始しました（quality: {recorder.quality}）。"})
        await self._notify_state()

    async def stop_recording(self) -> None:
        if self.recorder is None or not self.recorder.is_active:
            raise RuntimeError("録画は実行されていません。")
        await self.recorder.stop()
        await self._notify_state()

    async def _stop_recording(self) -> None:
        if self.recorder is not None and self.recorder.is_active:
            try:
                await self.recorder.stop()
            except Exception:
                logger.exception("failed to stop recording for %s", self.unique_id)

    async def _on_recording_finalized(self, recorder: Recorder) -> None:
        if recorder.recording_id is not None:
            snap = recorder.snapshot()
            self._storage.update_recording(
                recorder.recording_id,
                recorder.state,
                str(recorder.output_path) if recorder.output_path else "",
                recorder.output_path.name if recorder.output_path else "",
                recorder.ended_at,
                snap["bytes"],
                recorder.error,
            )
        await self._record(
            "system",
            {"text": f"録画が終了しました（{recorder.state}）。"},
        )
        await self._notify_state()

    async def _announce_waiting(self) -> None:
        self.state = STATE_WAITING
        self.steps = {step: "pending" for step in STEP_IDS}
        self.steps["request"] = "done"
        self.steps["live_check"] = "active"
        await self._notify_state()
        logger.info(
            "waiting for live start: unique_id=%s interval=%ss",
            self.unique_id,
            self._settings.get("live_check_interval"),
        )

    async def _wait_for_live_start(self, skip_first_check: bool = False) -> bool:
        probe = TikTokLiveClient(unique_id=self.unique_id)
        try:
            waiting_announced = False
            if skip_first_check:
                waiting_announced = True
                await self._announce_waiting()
                await asyncio.sleep(self._settings.get("live_check_interval"))
            while True:
                if self._stop_requested:
                    self.state = STATE_DISCONNECTED
                    return False
                try:
                    if await probe.web.fetch_is_live(unique_id=self.unique_id):
                        return True
                except UserNotFoundError:
                    self._fail("live_check", f"@{self.unique_id} というUserが見つかりません。")
                    return False
                except Exception as exc:
                    logger.warning("live check failed for %s: %s", self.unique_id, exc, exc_info=True)
                if not waiting_announced:
                    waiting_announced = True
                    await self._announce_waiting()
                await asyncio.sleep(self._settings.get("live_check_interval"))
        finally:
            await self._close_probe(probe)

    @staticmethod
    async def _close_probe(probe: TikTokLiveClient) -> None:
        try:
            await probe.web.close()
        except Exception:
            logger.debug("probe close skipped", exc_info=True)

    async def _session_loop(self) -> str:
        while True:
            outcome, reason = await self._connect_once()
            if outcome != "transient":
                return outcome
            result = await self._wait_for_reconnect(reason)
            if result != "retry":
                return result

    def _persist_final(self) -> None:
        if self.session_id is None:
            return
        try:
            self._storage.finalize_session(
                self.session_id, self.state, self.stats, list(self.timeline), list(self.markers)
            )
        except Exception:
            logger.exception("failed to persist session %s", self.session_id)
        self.session_id = None

    async def _connect_once(self) -> tuple:
        try:
            await self._client.connect(fetch_room_info=True)
            if self._stop_requested:
                if self.state == STATE_CONNECTED:
                    self.state = STATE_DISCONNECTED
                return ("stopped", None)
            if self.state == STATE_ENDED:
                return ("ended", None)
            return ("transient", "LIVEとの接続が切断されました")
        except UserOfflineError:
            try:
                offline_confirmed = await self._confirm_offline()
            except UserNotFoundError:
                self._fail("live_check", f"@{self.unique_id} というUserが見つかりません。")
                return ("fatal", None)
            if offline_confirmed:
                self.state = STATE_ENDED
                return ("ended", None)
            logger.info("offline report not confirmed, treating as transient: %s", self.unique_id)
            return ("transient", "TikTokが一時的に未配信と応答しました（再確認では配信中）")
        except UserNotFoundError:
            self._fail("live_check", f"@{self.unique_id} というUserが見つかりません。")
            return ("fatal", None)
        except AgeRestrictedError:
            self._fail("live_check", "年齢制限付きのLIVEのため接続できません。")
            return ("fatal", None)
        except TikTokLiveError as exc:
            logger.warning("transient TikTokLive error: %s", exc, exc_info=True)
            return ("transient", f"TikTok接続Error: {exc}")
        except Exception as exc:
            logger.warning("transient collector error: %s", exc, exc_info=True)
            return ("transient", f"接続Error: {exc}")

    async def _confirm_offline(self) -> bool:
        await asyncio.sleep(5)
        if self._stop_requested:
            return True
        probe = TikTokLiveClient(unique_id=self.unique_id)
        try:
            is_live = await probe.web.fetch_is_live(unique_id=self.unique_id)
        except UserNotFoundError:
            raise
        except Exception as exc:
            logger.warning(
                "offline confirmation check failed for %s: %s", self.unique_id, exc, exc_info=True
            )
            return False
        finally:
            await self._close_probe(probe)
        return not is_live

    async def _wait_for_reconnect(self, reason: str) -> str:
        if self._stop_requested:
            self.state = STATE_DISCONNECTED
            return "stopped"
        max_attempts = self._settings.get("reconnect_max_attempts")
        self._reconnect_attempt += 1
        if self._reconnect_attempt > max_attempts:
            self._fail(
                "websocket",
                f"再接続が{max_attempts}回失敗したため停止しました。最後の原因: {reason}",
            )
            return "fatal"
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
        return client

    async def _on_connect(self, event: ConnectEvent) -> None:
        reconnected = self._reconnect_attempt > 0
        self._reconnect_attempt = 0
        self.state = STATE_CONNECTED
        self.steps["live_check"] = "done"
        self.steps["websocket"] = "done"
        self.steps["receiving"] = "active"
        self.room_id = self._client.room_id if self._client else None
        try:
            self._room_info = (self._client.room_info if self._client else None) or {}
            owner = self._room_info.get("owner") or {}
            self._owner_id = str(owner.get("id") or "")
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
        if not reconnected and self._settings.get("auto_record") and ffmpeg_available():
            try:
                await self.start_recording()
            except Exception as exc:
                logger.warning("auto-record failed to start for %s: %s", self.unique_id, exc)

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

    async def _on_battle(self, event: LinkMicBattleEvent) -> None:
        self.stats["battles"] += 1
        label = f"Battle #{event.battle_id}"
        self._add_marker("battle", label)
        await self._record(
            "battle",
            {"text": f"{label} のEventを受信しました (action={event.action})"},
        )

    async def _on_armies(self, event: LinkMicArmiesEvent) -> None:
        if not self._owner_id:
            if not self._owner_warned:
                self._owner_warned = True
                logger.warning(
                    "room owner id unknown; battle score tracking disabled for %s", self.unique_id
                )
            return
        own_score = None
        for host_id, army in (event.armies or {}).items():
            if str(host_id) == self._owner_id or getattr(army, "anchor_id_str", "") == self._owner_id:
                own_score = army.host_score
                break
        if own_score is None or self._battles.get(event.battle_id) == own_score:
            return
        self._battles[event.battle_id] = own_score
        self.stats["battle_points"] = sum(self._battles.values())
        await self._broadcast_stats()

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
        self._update_rates()
        await self._broadcast_stats()

    async def _broadcast_stats(self) -> None:
        now = time.time()
        if now - self._last_stats_sent < 0.25:
            return
        self._last_stats_sent = now
        await self._broadcast({"type": "stats", "data": self.stats})

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
                if tick % 60 == 0:
                    battle_id = rng.randrange(10**6)
                    await self._on_battle(SimpleNamespace(battle_id=battle_id, action=1))
                    own_score = 0
                    for _ in range(rng.randint(2, 4)):
                        own_score += rng.randint(50, 400)
                        await self._on_armies(
                            SimpleNamespace(
                                battle_id=battle_id,
                                armies={
                                    1111: SimpleNamespace(host_score=own_score, anchor_id_str="sim_owner"),
                                    2222: SimpleNamespace(host_score=rng.randint(0, 800), anchor_id_str="rival"),
                                },
                            )
                        )
        except asyncio.CancelledError:
            self.state = STATE_DISCONNECTED
            self.steps["receiving"] = "done"
            self._add_marker("disconnect", "切断")
            self._persist_final()
            await self._notify_state()
            logger.info("simulation stopped: unique_id=%s", self.unique_id)

    async def _record(self, kind: str, payload: dict) -> None:
        self.stats["events_total"] += 1
        entry = {"kind": kind, "time": time.time(), **payload}
        self.recent_events.append(entry)
        if self.session_id is not None:
            try:
                self._storage.add_event(self.session_id, entry)
            except Exception:
                logger.exception("failed to persist event for session %s", self.session_id)
        self._update_rates()
        await self._broadcast({"type": "event", "data": entry})
        await self._broadcast_stats()

    async def _emit_only(self, kind: str, payload: dict) -> None:
        entry = {"kind": kind, "time": time.time(), **payload}
        await self._broadcast({"type": "event", "data": entry})

    async def _notify_state(self) -> None:
        await self._broadcast({"type": "state", "data": self.snapshot()})
