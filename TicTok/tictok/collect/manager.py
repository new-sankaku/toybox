import logging
from typing import Awaitable, Callable, Optional

from tictok.collect.collector import ACTIVE_STATES, PROBING_STATES, ProbeGate, TikTokCollector
from tictok.collect.live_resolver import BrowserLiveResolver
from tictok.core.logctx import log_context
from tictok.core.schedule import ScheduleProfiler
from tictok.storage import Storage

logger = logging.getLogger("tictok.manager")

Broadcast = Callable[[dict], Awaitable[None]]


class CollectorManager:
    def __init__(self, broadcast: Broadcast, storage: Storage, settings, gift_icons=None, avatar_proxy=None, asset_prefetch=None, notifier=None) -> None:
        self._broadcast = broadcast
        self._storage = storage
        self._settings = settings
        self._gift_icons = gift_icons
        self._avatar_proxy = avatar_proxy
        self._asset_prefetch = asset_prefetch
        self._notifier = notifier
        self._collectors: dict[str, TikTokCollector] = {}
        self._probe_gate = ProbeGate(settings, self._probing_count)
        self._schedule_profiler = ScheduleProfiler(self._session_start_history, settings)
        self._resolver = BrowserLiveResolver(settings)

    def _session_start_history(self) -> list:
        """全配信者のsession開始時刻。ScheduleProfilerのTTLごとに1回だけ呼ばれ、結果は
        配信者別に切り分けられて全collectorで共有される。"""
        return [
            (session["unique_id"], session.get("started_at"))
            for session in self._storage.list_sessions(0)
        ]

    async def startup(self) -> None:
        await self._resolver.start()

    async def shutdown(self) -> None:
        await self._resolver.close()

    def _probing_count(self) -> int:
        """ProbeGateの間隔計算の母数。probeを実際に消費しているcollector(=live checkを
        撃ち続けている待機中/制限中)だけを数える。接続中のcollectorを含めると、実アクセス
        量は変わらないのに待機中の検出間隔だけが引き伸ばされる。"""
        return sum(1 for c in self._collectors.values() if c.state in PROBING_STATES)

    def get(self, unique_id: str) -> Optional[TikTokCollector]:
        return self._collectors.get(unique_id)

    def snapshots(self) -> list:
        return [collector.snapshot() for collector in self._collectors.values()]

    def active_session_ids(self) -> set:
        return {
            collector.session_id
            for collector in self._collectors.values()
            if collector.session_id is not None
        }

    async def start(self, unique_id: str, record_video: Optional[bool] = None) -> TikTokCollector:
        collector = self._collectors.get(unique_id)
        if collector is None:
            # A new target adopts the supplied preference (default: save video); an
            # existing/restored target keeps the value already persisted in storage.
            if record_video is None:
                record_video = self._storage.get_target_record_video(unique_id)
            collector = TikTokCollector(
                unique_id=unique_id,
                broadcast=self._make_broadcast(unique_id),
                storage=self._storage,
                settings=self._settings,
                probe_gate=self._probe_gate,
                resolver=self._resolver,
                gift_icons=self._gift_icons,
                avatar_proxy=self._avatar_proxy,
                asset_prefetch=self._asset_prefetch,
                record_video=record_video,
                notifier=self._notifier,
                schedule_profiler=self._schedule_profiler,
            )
            self._collectors[unique_id] = collector
        elif record_video is not None and record_video != collector.record_video:
            await collector.set_record_video(record_video)
        self._storage.add_monitored_target(unique_id, collector.record_video)
        # An explicit preference must overwrite the stored value too (add_monitored_target
        # leaves an existing row untouched); None means "keep what is stored" (restart).
        if record_video is not None:
            self._storage.set_target_record_video(unique_id, collector.record_video)
        await collector.start()
        with log_context(unique_id=unique_id):
            logger.info(
                "監視を開始しました（現在 %d 件が稼働中）", len(self._collectors),
                extra={"event": "collector.monitor_started",
                       "ctx": {"total_monitors": len(self._collectors),
                               "record_video": collector.record_video}},
            )
        await self.notify_monitors()
        return collector

    async def stop(self, unique_id: str) -> TikTokCollector:
        collector = self._collectors.get(unique_id)
        if collector is None:
            raise KeyError(unique_id)
        await collector.stop()
        await self.notify_monitors()
        return collector

    async def remove(self, unique_id: str) -> None:
        collector = self._collectors.get(unique_id)
        if collector is None:
            raise KeyError(unique_id)
        if collector.state in ACTIVE_STATES:
            await collector.stop()
        del self._collectors[unique_id]
        self._storage.remove_monitored_target(unique_id)
        with log_context(unique_id=unique_id):
            logger.info(
                "監視を削除しました（残り %d 件）", len(self._collectors),
                extra={"event": "collector.monitor_removed",
                       "ctx": {"total_monitors": len(self._collectors)}},
            )
        await self.notify_monitors()

    async def start_recording(self, unique_id: str) -> TikTokCollector:
        collector = self._collectors.get(unique_id)
        if collector is None:
            raise KeyError(unique_id)
        await collector.start_recording()
        await self.notify_monitors()
        return collector

    async def stop_recording(self, unique_id: str) -> TikTokCollector:
        collector = self._collectors.get(unique_id)
        if collector is None:
            raise KeyError(unique_id)
        await collector.stop_recording()
        await self.notify_monitors()
        return collector

    async def set_record_video(self, unique_id: str, record_video: bool) -> TikTokCollector:
        collector = self._collectors.get(unique_id)
        if collector is None:
            raise KeyError(unique_id)
        await collector.set_record_video(record_video)
        self._storage.set_target_record_video(unique_id, record_video)
        await self.notify_monitors()
        return collector

    def live_recording_file(self, unique_id: str, filename: str):
        collector = self._collectors.get(unique_id)
        if collector is None or collector.recorder is None:
            return None
        return collector.recorder.live_file(filename)

    async def restore(self) -> None:
        """Re-open monitors that were active before the previous shutdown."""
        targets = self._storage.list_monitored_targets()
        if not targets:
            return
        logger.info(
            "前回起動時の監視対象 %d 件を復元します", len(targets),
            extra={"event": "collector.monitors_restore_started",
                   "ctx": {"count": len(targets),
                           "targets": [t["unique_id"] for t in targets]}},
        )
        for target in targets:
            unique_id = target["unique_id"]
            try:
                await self.start(unique_id, record_video=target["record_video"])
            except Exception:
                # 落ちた監視は誰も拾い直さない。userが手で再追加するまで、この配信者の
                # 収集と録画は丸ごと止まったままになる。
                with log_context(unique_id=unique_id):
                    logger.error(
                        "この監視の復元に失敗しました。手動で再開するまで停止したままです",
                        exc_info=True,
                        extra={"event": "collector.monitor_restore_failed", "ctx": {}},
                    )

    async def stop_all(self) -> None:
        for collector in self._collectors.values():
            if collector.state in ACTIVE_STATES:
                try:
                    await collector.stop()
                except Exception:
                    # shutdown中。残りの監視の停止は続行するが、この監視のsessionは
                    # finalizeされないまま終わる可能性がある。
                    with log_context(unique_id=collector.unique_id):
                        logger.error(
                            "shutdown中にこの監視を停止できませんでした。sessionがfinalize"
                            "されないまま残る可能性があります", exc_info=True,
                            extra={"event": "collector.monitor_stop_failed",
                                   "ctx": {"state": collector.state}},
                        )

    async def notify_monitors(self) -> None:
        await self._broadcast({"type": "monitors", "data": self.snapshots()})

    def _make_broadcast(self, unique_id: str) -> Broadcast:
        async def broadcast(message: dict) -> None:
            await self._broadcast({**message, "monitor": unique_id})

        return broadcast
