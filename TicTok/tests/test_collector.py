import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import collector as collector_mod
from collector import (
    STATE_CONNECTED,
    STATE_DISCONNECTED,
    STATE_ERROR,
    STATE_WAITING,
    TikTokCollector,
)
from settings import Settings
from storage import Storage
from TikTokLive.client.errors import UserNotFoundError, UserOfflineError
from TikTokLive.events import LinkMicArmiesEvent, LinkMicBattleEvent
from TikTokLive.proto.tiktok_proto import BattleUserArmies

ORIG_SLEEP = asyncio.sleep


async def fast_sleep(seconds):
    await ORIG_SLEEP(min(seconds, 0.05))


async def noop_broadcast(message):
    pass


def make_env():
    storage = Storage(tempfile.mktemp(suffix=".db"))
    settings = Settings(storage)
    settings._values.update({"live_check_interval": 0.05, "reconnect_base_delay": 0.05})
    return storage, settings


class FakeProbeFactory:
    results = []

    def __init__(self, unique_id):
        self.web = self

    async def fetch_is_live(self, unique_id=None):
        if FakeProbeFactory.results:
            result = FakeProbeFactory.results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return True


class FakeClient:
    def __init__(self, c, plan):
        self.c = c
        self.plan = plan
        self.room_id = 1
        self.room_info = {"owner": {"id": 999}}
        self._stop = asyncio.Event()

    async def connect(self, **kwargs):
        action = self.plan.pop(0) if self.plan else "stay"
        if action == "offline":
            raise UserOfflineError("x", "offline")
        if action == "fail":
            raise RuntimeError("transient boom")
        await self.c._on_connect(None)
        if action == "live_end":
            await ORIG_SLEEP(0.1)
            await self.c._on_live_end(None)
            return
        await self._stop.wait()

    async def disconnect(self, **kwargs):
        self._stop.set()
        await self.c._on_disconnect(None)


async def wait_for(predicate, timeout=8.0):
    for _ in range(int(timeout / 0.02)):
        await ORIG_SLEEP(0.02)
        if predicate():
            return True
    return False


async def test_battle_score_with_real_proto():
    storage, settings = make_env()
    c = TikTokCollector("battle", noop_broadcast, storage, settings)
    c._owner_id = "999"
    await c._on_armies(
        LinkMicArmiesEvent(battle_id=42, armies={999: BattleUserArmies(host_score=300, anchor_id_str="999")})
    )
    await c._on_armies(
        LinkMicArmiesEvent(
            battle_id=42,
            armies={
                999: BattleUserArmies(host_score=750, anchor_id_str="999"),
                111: BattleUserArmies(host_score=9999, anchor_id_str="111"),
            },
        )
    )
    await c._on_armies(
        LinkMicArmiesEvent(battle_id=43, armies={999: BattleUserArmies(host_score=200, anchor_id_str="999")})
    )
    assert c.stats["battle_points"] == 950, c.stats["battle_points"]
    c2 = TikTokCollector("battle2", noop_broadcast, storage, settings)
    c2._owner_id = "888"
    await c2._on_armies(
        LinkMicArmiesEvent(battle_id=1, armies={777: BattleUserArmies(host_score=500, anchor_id_str="888")})
    )
    assert c2.stats["battle_points"] == 500, c2.stats["battle_points"]
    c2.stats["battles"] = 0
    await c2._on_battle(LinkMicBattleEvent(battle_id=1, action=1))
    assert c2.stats["battles"] == 1
    print("OK battle score (real proto, owner照合はID/anchor_id_str両対応)")


async def test_false_offline_keeps_session():
    storage, settings = make_env()
    c = TikTokCollector("doublecheck", noop_broadcast, storage, settings)
    plan = ["offline", "stay"]
    c._build_client = lambda uid: FakeClient(c, plan)
    FakeProbeFactory.results = [True, True]
    await c.start()
    assert await wait_for(lambda: c.state == STATE_CONNECTED), c.state
    assert len(storage.list_sessions(10)) == 1
    await c.stop()
    print("OK 誤った未配信応答 -> 同一Session継続")


async def test_confirmed_offline_goes_waiting():
    storage, settings = make_env()
    c = TikTokCollector("ended", noop_broadcast, storage, settings)
    plan = ["offline"]
    c._build_client = lambda uid: FakeClient(c, plan)
    FakeProbeFactory.results = [True, False, False, False, False]
    await c.start()
    assert await wait_for(lambda: c.state == STATE_WAITING), c.state
    await c.stop()
    assert c.state == STATE_DISCONNECTED
    print("OK 確認済みの配信終了 -> WAITINGへ移行")


async def test_resident_new_session_per_live():
    storage, settings = make_env()
    c = TikTokCollector("resident", noop_broadcast, storage, settings)
    plan = ["live_end", "stay"]
    c._build_client = lambda uid: FakeClient(c, plan)
    FakeProbeFactory.results = [False, True, False, True]
    await c.start()
    assert await wait_for(lambda: c.state == STATE_CONNECTED and not plan), c.state
    sessions = storage.list_sessions(10)
    assert len(sessions) == 2, [s["id"] for s in sessions]
    await c.stop()
    assert all(s["ended_at"] is not None for s in storage.list_sessions(10))
    print("OK 常駐監視: 配信ごとに新Session、停止で全finalize")


async def test_reconnect_then_recover():
    storage, settings = make_env()
    c = TikTokCollector("flaky", noop_broadcast, storage, settings)
    plan = ["fail", "fail", "stay"]
    c._build_client = lambda uid: FakeClient(c, plan)
    FakeProbeFactory.results = [True]
    await c.start()
    assert await wait_for(lambda: c.state == STATE_CONNECTED), c.state
    assert c._reconnect_attempt == 0
    await c.stop()
    print("OK transient障害 -> 再接続で復帰")


async def test_reconnect_exhausted():
    storage, settings = make_env()
    settings._values["reconnect_max_attempts"] = 2
    c = TikTokCollector("dead", noop_broadcast, storage, settings)
    c._build_client = lambda uid: FakeClient(c, ["fail"] * 10)
    FakeProbeFactory.results = [True]
    await c.start()
    assert await wait_for(lambda: c.state == STATE_ERROR), c.state
    assert "再接続が2回失敗" in c.error_message
    print("OK 再接続上限超過 -> error停止")


async def test_user_not_found_terminal():
    storage, settings = make_env()
    c = TikTokCollector("ghost", noop_broadcast, storage, settings)
    FakeProbeFactory.results = [UserNotFoundError("ghost", "not found")]
    await c.start()
    assert await wait_for(lambda: c.state == STATE_ERROR), c.state
    print("OK User不存在 -> 即時error")


async def test_event_persistence_columns():
    storage, _ = make_env()
    sid = storage.create_session("persist", 10)
    storage.add_event(sid, {"time": 1.0, "kind": "comment", "user": {"unique_id": "u", "nickname": "U"}, "comment": "本文", "text": "U: 本文"})
    storage.add_event(sid, {"time": 2.0, "kind": "like", "user": {"unique_id": "u", "nickname": "U"}, "count": 12, "text": "x"})
    storage.add_event(sid, {"time": 3.0, "kind": "gift", "user": {"unique_id": "u", "nickname": "U"}, "gift_name": "Rose", "repeat_count": 3, "diamonds": 3, "text": "x"})
    events = storage.iter_events(sid)
    assert events[0]["comment"] == "本文"
    assert events[1]["count"] == 12
    assert events[2]["gift_count"] == 3 and events[2]["diamonds"] == 3
    rankings = storage.session_rankings(10)
    assert rankings["likes"][0]["value"] == 12
    assert rankings["comments"][0]["value"] == 1
    assert rankings["gifts"][0]["value"] == 3
    print("OK 保存column (comment/count/gift) とranking集計")


async def main():
    collector_mod.asyncio.sleep = fast_sleep
    collector_mod.TikTokLiveClient = FakeProbeFactory
    await test_battle_score_with_real_proto()
    await test_false_offline_keeps_session()
    await test_confirmed_offline_goes_waiting()
    await test_resident_new_session_per_live()
    await test_reconnect_then_recover()
    await test_reconnect_exhausted()
    await test_user_not_found_terminal()
    await test_event_persistence_columns()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
