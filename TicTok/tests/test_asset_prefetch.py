import asyncio
import json

import pytest

from tictok.media.asset_prefetch import AssetPrefetcher
from tictok.media.avatar_pool import avatar_key
from tictok.media.emote_pool import EmotePool, is_valid_emote_id

# 許可listに載っているhostの、実物と同じ形のURL(networkへは出ない。取得はstubが担う)
CDN_URL = "https://p16-webcast.tiktokcdn.com/img/maliva/abc~tplv-obj:72:72.image"


class FakeGiftIcons:
    """GiftIconCacheのうち、先行取得が触る面だけを持つstub。"""

    def __init__(self, cache_dir):
        self.dir = cache_dir
        self.calls = []
        self.gate = None

    def has(self, gift_id):
        path = self.dir / f"{int(gift_id)}.img"
        return path.is_file() and path.stat().st_size > 0

    async def persist(self, gift_id, url):
        self.calls.append(int(gift_id))
        if self.gate is not None:
            await self.gate.wait()
        (self.dir / f"{int(gift_id)}.img").write_bytes(b"icon")
        return True


class FakeAvatarPool:
    """AvatarPoolのうち、先行取得が触る面だけを持つstub。"""

    def __init__(self, cache_dir):
        self.dir = cache_dir
        self.calls = []

    def needs_update(self, user_key, url):
        path = self.dir / f"{avatar_key(user_key)}.img"
        return not (path.is_file() and path.stat().st_size > 0)

    async def persist(self, user_key, url):
        self.calls.append(user_key)
        (self.dir / f"{avatar_key(user_key)}.img").write_bytes(b"avatar")
        return True


@pytest.fixture
def prefetch(tmp_path):
    """rate limit無しの先行取得。queueは小さくして溢れを観測できるようにする。"""
    gift_dir = tmp_path / "gift_icons"
    avatar_dir = tmp_path / "avatars"
    gift_dir.mkdir()
    avatar_dir.mkdir()
    gifts = FakeGiftIcons(gift_dir)
    avatars = FakeAvatarPool(avatar_dir)
    emotes = EmotePool(cache_dir=tmp_path / "emotes")
    pf = AssetPrefetcher(gift_icons=gifts, avatar_pool=avatars, emote_pool=emotes,
                         concurrency=2, queue_size=4, rate_per_second=0)
    pf.gifts = gifts
    pf.avatars = avatars
    pf.emotes = emotes
    return pf


# ---------------- 投入と重複排除 ----------------


async def test_same_gift_icon_is_fetched_once_however_many_events_carry_it(prefetch):
    """同じgiftが連投されても取得は1回。dedupが無いとgift 1件ごとにCDNを叩く。"""
    prefetch.start()
    for _ in range(5):
        prefetch.submit_gift_icon(1234, CDN_URL)
    await prefetch._queue.join()
    await prefetch.aclose()

    assert prefetch.gifts.calls == [1234]
    assert prefetch.stats()["deduped"] == 4


async def test_avatar_dedup_follows_the_on_disk_key_not_the_supplied_id(prefetch):
    """dedup keyは保存先file名(avatar_key)。unique_idとnicknameが混ざって届いても
    同じ人物のavatarを二重に取りに行かない。"""
    prefetch.start()
    prefetch.submit_avatar("tester", CDN_URL)
    prefetch.submit_avatar("tester", CDN_URL + "&x-signature=other")
    await prefetch._queue.join()
    await prefetch.aclose()

    assert prefetch.avatars.calls == ["tester"]


async def test_already_pooled_assets_enter_the_queue_once_then_never_again(prefetch):
    """diskに在るものはworkerが1度確かめた後は投入前に落ちる。ここが効かないと、既知user
    だらけの配信でqueueが取得不要の要求で埋まる。

    投入側はdiskを見ない(見るとevent loopがdiskの応答を待つ — Windows Updateの復元
    ポイント作成で十数秒止まった実績がある)。初見の1回だけqueueを通り、workerがthreadで
    diskを確かめて「在る」と覚える。2回目以降はその記憶だけで落ちる。"""
    (prefetch.gifts.dir / "77.img").write_bytes(b"icon")
    (prefetch.avatars.dir / f"{avatar_key('known')}.img").write_bytes(b"avatar")
    prefetch.emotes.path_for("70012345").write_bytes(b"emote")
    payload = json.dumps([{"index": 0, "id": "70012345", "url": CDN_URL}])

    prefetch.start()
    prefetch.submit_gift_icon(77, CDN_URL)
    prefetch.submit_avatar("known", CDN_URL)
    prefetch.submit_emotes(payload)
    await prefetch._queue.join()
    first = prefetch.stats()["submitted"]
    assert first <= 3

    for _ in range(3):
        prefetch.submit_gift_icon(77, CDN_URL)
        prefetch.submit_avatar("known", CDN_URL)
        prefetch.submit_emotes(payload)
    await prefetch.aclose()

    assert prefetch.stats()["submitted"] == first, "覚えた後もqueueへ入っている"
    assert prefetch._queue.qsize() == 0


async def test_comment_emote_payload_is_expanded_into_one_request_per_emote(prefetch):
    """commentの emotes JSON から emote_id 単位で積む(同一idの複数出現は1件)。"""
    prefetch.submit_emotes(json.dumps([
        {"index": 0, "id": "700111", "url": CDN_URL},
        {"index": 4, "id": "700111", "url": CDN_URL},
        {"index": 7, "id": "700222", "url": CDN_URL},
    ]))

    assert prefetch.stats()["submitted"] == 2


async def test_unusable_emotes_are_reported_and_never_queued(prefetch, caplog):
    """file名に使えないidと許可外hostは、再試行しても結果が変わらない永久失敗。
    queueのslotも試行も使わず、黙って捨てもしないこと。"""
    prefetch.submit_emotes(json.dumps([
        {"index": 0, "id": "../escape", "url": CDN_URL},
        {"index": 1, "id": "700333", "url": "https://evil.example.com/x.png"},
    ]))

    assert prefetch.stats()["submitted"] == 0
    reasons = {r.__dict__["ctx"]["reason"] for r in caplog.records if hasattr(r, "ctx")}
    assert {"invalid_id", "host_not_allowed"} <= reasons


async def test_invalid_emote_payload_is_reported_not_swallowed(prefetch, caplog):
    """壊れたpayloadでeventの取り込みは止めないが、黙って無視もしない。"""
    prefetch.submit_emotes("{ではないもの")

    assert prefetch.stats()["submitted"] == 0
    assert any(r.__dict__.get("event") == "prefetch.emote_payload_invalid"
               for r in caplog.records)


# ---------------- 有界queue ----------------


async def test_queue_overflow_drops_and_says_so(prefetch, caplog):
    """queueは有界。溢れたら捨てる(event処理を待たせない)が、捨てたことはlogに残る。
    溢れを黙って捨てると、そのassetが焼き込みで欠けた理由が後から辿れない。"""
    gate = asyncio.Event()
    prefetch.gifts.gate = gate
    prefetch.start()
    for gift_id in range(20):
        prefetch.submit_gift_icon(1000 + gift_id, CDN_URL)

    stats = prefetch.stats()
    # workerが握る2件 + queueの4件までが上限で、残りは捨てられる
    assert stats["submitted"] <= 6
    assert stats["dropped"] >= 14
    assert any(r.__dict__.get("event") == "prefetch.queue_overflow" for r in caplog.records)

    gate.set()
    await prefetch.aclose()


async def test_submit_never_awaits_so_event_ingest_is_not_blocked(prefetch):
    """投入は同期。event着信のhot pathがCDNの往復を待つことは無い。"""
    gate = asyncio.Event()
    prefetch.gifts.gate = gate
    prefetch.start()
    prefetch.submit_gift_icon(1, CDN_URL)
    # workerが取得の途中(gate待ち)でも、次の投入はその場で戻る
    await asyncio.sleep(0)
    prefetch.submit_gift_icon(2, CDN_URL)

    assert prefetch.stats()["submitted"] == 2
    gate.set()
    await prefetch.aclose()


# ---------------- 焼き込みとのcache命名の一致 ----------------


def test_emote_pool_writes_the_name_the_burn_in_reads(tmp_path):
    """poolの保存名と、焼き込み(_resolve_emotes)が読む名前が一致すること。

    焼き込み側は ``cache_dir / f"{eid}.img"`` を直接組み立てるので、ここがずれると
    先行取得は全て無駄になり、失効後のURLをdownloadしに行って絵文字が消える。"""
    pool = EmotePool(cache_dir=tmp_path / "emotes")
    eid = "70012345"

    assert pool.path_for(eid) == (tmp_path / "emotes" / f"{eid}.img")


async def test_burn_in_resolves_a_pooled_emote_without_downloading(tmp_path, monkeypatch):
    """poolが書いたfileを焼き込みがそのまま使う(downloadが走らない)ことを実物で確認する。"""
    from PIL import Image

    from tictok.record import video_overlay

    cache_dir = tmp_path / "emotes"
    pool = EmotePool(cache_dir=cache_dir)
    eid = "70012345"
    Image.new("RGBA", (48, 48), (10, 20, 30, 255)).save(pool.path_for(eid), format="PNG")

    def _fail(url, dest):
        raise AssertionError(f"cache hitせずdownloadが走った: {url}")

    monkeypatch.setattr(video_overlay, "_download", _fail)

    class Shaper:
        def __init__(self):
            self._emotes = {"": {"id": eid, "url": CDN_URL, "image": None}}
            self.images = {}

        def set_emote_image(self, sentinel, image):
            self.images[sentinel] = image

    shaper = Shaper()
    resolved = await video_overlay._resolve_emotes(shaper, cache_dir)

    assert resolved == 1
    assert shaper.images[""].size == (48, 48)


def test_emote_id_validation_keeps_writes_inside_the_pool():
    """emote_idは外部由来。pathを跨げる文字列をfile名にしないこと。"""
    assert is_valid_emote_id("70012345")
    assert not is_valid_emote_id("../escape")
    assert not is_valid_emote_id("a/b")
    assert not is_valid_emote_id("")
