import logging
from typing import Awaitable, Callable, Optional

from collector import ACTIVE_STATES, TikTokCollector
from storage import Storage

logger = logging.getLogger("tictok.manager")

Broadcast = Callable[[dict], Awaitable[None]]


class CollectorManager:
    def __init__(self, broadcast: Broadcast, storage: Storage, settings) -> None:
        self._broadcast = broadcast
        self._storage = storage
        self._settings = settings
        self._collectors: dict[str, TikTokCollector] = {}

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

    async def start(self, unique_id: str) -> TikTokCollector:
        collector = self._collectors.get(unique_id)
        if collector is None:
            collector = TikTokCollector(
                unique_id=unique_id,
                broadcast=self._make_broadcast(unique_id),
                storage=self._storage,
                settings=self._settings,
            )
            self._collectors[unique_id] = collector
        await collector.start()
        logger.info("monitor started: %s (total=%d)", unique_id, len(self._collectors))
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
        logger.info("monitor removed: %s (total=%d)", unique_id, len(self._collectors))
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

    async def stop_all(self) -> None:
        for collector in self._collectors.values():
            if collector.state in ACTIVE_STATES:
                try:
                    await collector.stop()
                except Exception:
                    logger.exception("failed to stop monitor %s", collector.unique_id)

    async def notify_monitors(self) -> None:
        await self._broadcast({"type": "monitors", "data": self.snapshots()})

    def _make_broadcast(self, unique_id: str) -> Broadcast:
        async def broadcast(message: dict) -> None:
            await self._broadcast({**message, "monitor": unique_id})

        return broadcast
