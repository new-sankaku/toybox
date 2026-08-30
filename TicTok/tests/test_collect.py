import asyncio
import json
import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import mock

import pytest

from TikTokLive.client.errors import UserNotFoundError
from TikTokLive.proto import (
    BadgeStruct,
    BadgeStructBadgeSceneType,
    CombineBadgeStruct,
    CommonMessageData,
    ExtendedUser,
    FollowInfo,
    ImageBadge,
    ImageModel,
    PrivilegeLogExtra,
    Text,
    TextPiece,
    TextPieceUser,
    User,
    UserFansClubInfo,
    UserIdentity,
    WebcastBarrageMessage,
    WebcastLikeMessage,
    WebcastSocialMessage,
)
from TikTokLive.events import CommentEvent, LikeEvent, SocialEvent

from tictok.collect import collector as C
from tictok.collect import dedup
from tictok.collect import live_resolver as LR
from tictok.collect.live_resolver import LiveResolveBlocked, interpret_live_state
from tictok.collect.proto_dict import safe_event_to_dict, to_plain


def _on_wire(msg):
    """default値だけのmessageでも『wireに載っていた』状態にする(parse経由)。"""
    return type(msg)().FromString(bytes(msg))


def _img(*urls):
    return ImageModel(m_urls=list(urls))


@pytest.fixture
def collector(tmp_db):
    from tictok.core.settings import Settings

    async def _broadcast(_message):
        return None

    return C.TikTokCollector(
        unique_id="tester", broadcast=_broadcast, storage=tmp_db, settings=Settings(tmp_db)
    )


class FakeSettings:
    def __init__(self, **values):
        self._values = values

    def get(self, key):
        return self._values[key]


# ---------------- proto_dict ----------------


def test_to_plain_keeps_unknown_enum_as_raw_int():
    # TikTokが未定義のenum値(999)を送ってきてもValueErrorにせず生intで残す。
    parsed = BadgeStruct().FromString(bytes([3 << 3 | 0, 0xE7, 0x07]))
    assert to_plain(parsed) == {"badge_scene": 999}


def test_to_plain_known_enum_becomes_name_and_defaults_are_dropped():
    badge = BadgeStruct(badge_scene=BadgeStructBadgeSceneType(10), schema_url="https://x/y")
    plain = to_plain(badge)
    assert plain["badge_scene"] == "BADGE_SCENE_TYPE_FANS"
    assert plain["schema_url"] == "https://x/y"
    # default値のfieldは出力しない(1 eventあたりの体積を抑えるのが目的)。
    assert "greyed_by_client" not in plain
    assert "display" not in plain


def test_to_plain_scalar_conversions():
    value = to_plain(
        {"b": b"\x01\xff", "t": datetime(2026, 1, 2, 3, 4, 5), "d": timedelta(seconds=90), 7: [1, 2]}
    )
    assert value == {"b": "01ff", "t": "2026-01-02T03:04:05", "d": 90.0, "7": [1, 2]}


def test_to_plain_depth_cap_truncates_instead_of_recursing_forever():
    deep = current = []
    for _ in range(30):
        nxt = []
        current.append(nxt)
        current = nxt
    out = to_plain(deep)
    for _ in range(21):
        assert isinstance(out, list)
        out = out[0]
    assert out == "…"


def test_safe_event_to_dict_wraps_non_dict_values():
    assert safe_event_to_dict(42) == {"_value": 42}


def test_safe_event_to_dict_falls_back_to_repr_instead_of_raising(monkeypatch):
    import tictok.collect.proto_dict as pd

    def boom(_value, depth=0):
        raise RuntimeError("conversion exploded")

    monkeypatch.setattr(pd, "to_plain", boom)
    assert safe_event_to_dict(["payload"]) == {"_repr": "['payload']"}


# ---------------- live_resolver.interpret_live_state ----------------


def test_interpret_live_state_waf_and_missing_sigi_are_distinguished():
    with pytest.raises(LiveResolveBlocked) as waf:
        interpret_live_state({"sigi": False, "waf": True}, "someone")
    assert "WAF" in str(waf.value)
    with pytest.raises(LiveResolveBlocked) as plain:
        interpret_live_state({"sigi": False, "waf": False}, "someone")
    assert "SIGI_STATE" in str(plain.value)


def test_interpret_live_state_missing_live_room_is_user_not_found():
    with pytest.raises(UserNotFoundError):
        interpret_live_state({"sigi": True, "liveRoom": False}, "someone")


@pytest.mark.parametrize(
    "data,expected",
    [
        ({"sigi": True, "liveRoom": True, "status": 4, "roomId": "123"}, None),
        ({"sigi": True, "liveRoom": True, "status": 2, "roomId": "7300000000000000000"},
         7300000000000000000),
        ({"sigi": True, "liveRoom": True, "status": 2, "roomId": None}, None),
        ({"sigi": True, "liveRoom": True, "status": 2, "roomId": 0}, None),
    ],
)
def test_interpret_live_state_room_id(data, expected):
    # status==4はofflineなのでroomIdが残っていてもliveと誤認しない。
    assert interpret_live_state(data, "someone") == expected


# ---------------- 監視loopの異常終了 ----------------


@pytest.mark.asyncio
async def test_watch_loop_crash_is_reported_not_silent(collector, monkeypatch):
    # watch loopが落ちても誰も拾い直さない。「待機中」を名乗ったまま黙って止まると
    # 気づけないので、状態をerrorへ落として理由を画面とlogに出す。
    async def boom(*args, **kwargs):
        raise RuntimeError("watch loop exploded")

    monkeypatch.setattr(collector, "_wait_for_live_start", boom)
    await collector._run()
    assert collector.state == C.STATE_ERROR
    assert "RuntimeError" in (collector.error_message or "")


# ---------------- live_resolver の browser 監視 ----------------

_LIVE_SIGI = {"sigi": True, "liveRoom": True, "status": 2, "roomId": "7300000000000000000"}


class _FakePage:
    def __init__(self, data):
        self._data = data
        self.closed = False

    async def goto(self, *args, **kwargs):
        return None

    async def wait_for_selector(self, *args, **kwargs):
        return None

    async def evaluate(self, *args, **kwargs):
        return self._data

    async def close(self):
        self.closed = True


class _FakeContext:
    """``fails`` 回だけ new_page が driver 切断と同じ形で落ちる context。"""

    def __init__(self, fails=0, data=None):
        self.fails = fails
        self.data = data if data is not None else _LIVE_SIGI
        self.opened = 0

    async def new_page(self):
        self.opened += 1
        if self.fails > 0:
            self.fails -= 1
            raise Exception("Connection closed while reading from the driver")
        return _FakePage(self.data)

    async def close(self):
        return None


class _FakeBrowser:
    def is_connected(self):
        return True

    async def close(self):
        return None


class _SupervisedResolver(LR.BrowserLiveResolver):
    """実 playwright を起こさずに監視の振る舞いだけを見る。"""

    def __init__(self, contexts):
        super().__init__(None)
        self._pending = list(contexts)
        self.launches = 0

    async def _launch(self):
        self._last_launch_at = time.monotonic()
        self.launches += 1
        self._browser = _FakeBrowser()
        self._context = self._pending.pop(0)
        self._failures = 0

    async def _teardown(self):
        self._context = self._browser = self._playwright = None


@pytest.mark.asyncio
async def test_resolver_rebuilds_browser_after_consecutive_failures(monkeypatch):
    # driver process が死ぬと以後の呼び出しは永久に同じ例外を返す。
    # 連続失敗で browser を作り直し、live 検出が自力で戻ること。
    monkeypatch.setenv("TICTOK_RESOLVER_RESTART_AFTER_FAILURES", "2")
    monkeypatch.setenv("TICTOK_RESOLVER_RESTART_COOLDOWN_SECONDS", "0")
    dead = _FakeContext(fails=99)
    healthy = _FakeContext(fails=0)
    resolver = _SupervisedResolver([dead, healthy])
    await resolver.start()
    assert resolver.launches == 1

    for _ in range(2):
        with pytest.raises(LiveResolveBlocked):
            await resolver.resolve("someone")
    assert resolver.launches == 1

    resolution = await resolver.resolve("someone")
    assert resolution.room_id == 7300000000000000000
    assert resolver.launches == 2
    assert healthy.opened == 1


class _HangingContext:
    """new_page が返ってこない context。driverが死なずに固まる型。"""

    async def new_page(self):
        await asyncio.Event().wait()

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_resolver_gives_up_when_browser_never_answers(monkeypatch):
    # playwrightのnew_page/evaluate/closeにはtimeoutが無い。ここで切らないとlockを
    # 握ったまま止まり、全監視のlive検出がlog1行も残さずに停止する。
    monkeypatch.setenv("TICTOK_RESOLVER_TIMEOUT_MS", "30")
    monkeypatch.setenv("TICTOK_RESOLVER_RESTART_AFTER_FAILURES", "1")
    monkeypatch.setenv("TICTOK_RESOLVER_RESTART_COOLDOWN_SECONDS", "0")
    resolver = _SupervisedResolver([_HangingContext(), _FakeContext(fails=0)])
    await resolver.start()
    with pytest.raises(LiveResolveBlocked) as blocked:
        await asyncio.wait_for(resolver.resolve("someone"), timeout=5)
    assert "unresponsive" in str(blocked.value)
    # 固まったbrowserは次のprobeで作り直され、検出が戻る。
    assert (await resolver.resolve("someone")).room_id == 7300000000000000000
    assert resolver.launches == 2


@pytest.mark.asyncio
async def test_resolver_restart_waits_for_cooldown(monkeypatch):
    # 起動そのものが壊れている間、probe ごとに chromium を起こさない。
    monkeypatch.setenv("TICTOK_RESOLVER_RESTART_AFTER_FAILURES", "1")
    monkeypatch.setenv("TICTOK_RESOLVER_RESTART_COOLDOWN_SECONDS", "300")
    resolver = _SupervisedResolver([_FakeContext(fails=99), _FakeContext(fails=0)])
    await resolver.start()
    with pytest.raises(LiveResolveBlocked):
        await resolver.resolve("someone")
    with pytest.raises(LiveResolveBlocked) as pending:
        await resolver.resolve("someone")
    assert "cooldown" in str(pending.value)
    assert resolver.launches == 1


@pytest.mark.asyncio
async def test_resolver_success_clears_failure_streak(monkeypatch):
    # 単発の navigation 失敗で browser を捨てない（WAF通過済の context を失う）。
    monkeypatch.setenv("TICTOK_RESOLVER_RESTART_AFTER_FAILURES", "2")
    monkeypatch.setenv("TICTOK_RESOLVER_RESTART_COOLDOWN_SECONDS", "0")
    flaky = _FakeContext(fails=1)
    resolver = _SupervisedResolver([flaky, _FakeContext(fails=0)])
    await resolver.start()
    with pytest.raises(LiveResolveBlocked):
        await resolver.resolve("someone")
    assert (await resolver.resolve("someone")).room_id == 7300000000000000000
    # 成功で連続が切れているので、次の1回の失敗では閾値(2)に届かない。
    flaky.fails = 1
    with pytest.raises(LiveResolveBlocked):
        await resolver.resolve("someone")
    assert resolver.launches == 1


# ---------------- 小さな正規化 helper ----------------


@pytest.mark.parametrize(
    "raw,expected",
    [(None, None), (5, 5), ("7", 7), (True, 1), (3.9, 3), ("x", None), ([], None)],
)
def test_as_int_and_enum_value(raw, expected):
    assert C._as_int(raw) == expected
    assert C._enum_value(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0, None),
        (None, None),
        (-5, None),
        (999_999_999, None),               # 1970年代=epoch秒として小さすぎる
        (1_700_000_000, 1_700_000_000.0),  # 秒
        (1_700_000_000_123, 1_700_000_000.123),  # ミリ秒
        ("1700000000", 1_700_000_000.0),
        ("abc", None),
    ],
)
def test_epoch_seconds_unit_detection(raw, expected):
    assert C._epoch_seconds(raw) == expected


# ---------------- stream URL 診断 ----------------


def test_mask_url_hides_credentials_but_keeps_expiry_readable():
    url = "https://cdn/live.flv?expire=1700000000&signature=abcdef&session_id=zz&plain=1&novalue="
    masked = C._mask_url(url)
    assert "abcdef" not in masked and "zz" not in masked
    assert "expire=1700000000" in masked
    assert "plain=1" in masked
    # 値が空のkeyは masked にせずそのまま(秘密が載っていない)。
    assert "novalue=" in masked


def test_mask_url_edge_cases():
    assert C._mask_url("") == ""
    assert C._mask_url("https://cdn/live.flv") == "https://cdn/live.flv"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://cdn/a?expire=1700000000", 1_700_000_000.0),
        ("https://cdn/a?oe=1700000000000", 1_700_000_000.0),
        ("https://cdn/a?EXPIRES=1700000000", 1_700_000_000.0),
        ("https://cdn/a?expire=abc", None),
        ("https://cdn/a?expire=5", None),
        ("https://cdn/a?other=1700000000", None),
        ("https://cdn/a", None),
        ("", None),
    ],
)
def test_url_expiry(url, expected):
    assert C._url_expiry(url) == expected


def test_stream_url_ctx_only_reports_expiry_when_the_url_states_one(monkeypatch):
    monkeypatch.setattr(C.time, "time", lambda: 1_700_000_000.0)
    ctx = C._stream_url_ctx("https://cdn/a?expire=1700000060&token=secret")
    assert ctx["url_expires_at"] == 1_700_000_060.0
    assert ctx["seconds_to_expiry"] == 60.0
    assert "secret" not in ctx["stream_url"]

    bare = C._stream_url_ctx("https://cdn/a")
    assert bare == {"stream_url": "https://cdn/a"}


# ---------------- 画像 / バッジ ----------------


def test_image_url_prefers_url_list_and_falls_back_to_m_urls():
    assert C._image_url(None) == ""
    assert C._image_url({}) == ""
    assert C._image_url({"m_urls": ["m"], "url_list": ["u"]}) == "u"
    assert C._image_url({"urls": ["z"]}) == "z"
    assert C._image_url(_img("proto1", "proto2")) == "proto1"
    assert C._image_url(ImageModel()) == ""


def test_best_owner_image_prefers_the_largest_rendition():
    owner = {
        "avatar_thumb": {"url_list": ["thumb"]},
        "avatar_medium": {"url_list": ["medium"]},
        "avatar_larger": {"url_list": ["large"]},
    }
    assert C._best_owner_image(owner) == "large"
    del owner["avatar_larger"]
    assert C._best_owner_image(owner) == "medium"
    assert C._best_owner_image({"avatar_thumb": {"url_list": []}}) == ""
    assert C._best_owner_image(None) == ""


def test_badge_image_prefers_image_badge_then_combine_icon_then_background():
    from TikTokLive.proto import CombineBadgeBackground

    assert C._badge_image(None) == ""
    icon_only = BadgeStruct(combine_badge_struct=CombineBadgeStruct(icon=_img("icon")))
    assert C._badge_image(icon_only) == "icon"
    both = BadgeStruct(
        image_badge=ImageBadge(image_model=_img("image_badge")),
        combine_badge_struct=CombineBadgeStruct(icon=_img("icon")),
    )
    assert C._badge_image(both) == "image_badge"
    bg_only = BadgeStruct(
        combine_badge_struct=CombineBadgeStruct(
            background=CombineBadgeBackground(image=_img("bg"))
        )
    )
    assert C._badge_image(bg_only) == "bg"


def test_badge_level_prefers_log_extra_over_fanclub_name():
    # FANSバッジの str はファンクラブ名(数字を含み得る)なので log_extra を先に読む。
    badge = BadgeStruct(
        log_extra=PrivilegeLogExtra(level="12"),
        combine_badge_struct=CombineBadgeStruct(str="Team 99"),
    )
    assert C._badge_level(badge) == 12
    assert C._badge_level(BadgeStruct(combine_badge_struct=CombineBadgeStruct(str="Lv 7"))) == 7
    # 数字が1つも無ければ捏造せず0(非表示)。
    assert C._badge_level(BadgeStruct(combine_badge_struct=CombineBadgeStruct(str="VIP"))) == 0
    assert C._badge_level(None) == 0


def test_badge_by_scene_picks_the_matching_scene_only():
    fans = BadgeStruct(badge_scene=BadgeStructBadgeSceneType(C.BADGE_SCENE_FANS), image_badge=ImageBadge(image_model=_img("f")))
    grade = BadgeStruct(
        badge_scene=BadgeStructBadgeSceneType(C.BADGE_SCENE_USER_GRADE), image_badge=ImageBadge(image_model=_img("g"))
    )
    user = ExtendedUser(badge_list=[fans, grade])
    assert C._badge_image_by_scene(user, C.BADGE_SCENE_USER_GRADE) == "g"
    assert C._badge_image_by_scene(user, C.BADGE_SCENE_FANS) == "f"
    assert C._badge_by_scene(user, 999) is None
    assert C._badge_image_by_scene(ExtendedUser(), C.BADGE_SCENE_FANS) == ""


# ---------------- user payload / identity ----------------


def test_user_payload_of_none_is_explicitly_unknown():
    payload = C._user_payload(None)
    assert payload["nickname"] == "(unknown)"
    assert payload["identity_key"] == ""
    assert payload["fans_level"] == 0 and payload["gifter_level"] == 0


def test_user_payload_identity_key_prefers_the_immutable_numeric_id():
    user = ExtendedUser(id=7_012_345_678, nick_name="Nick", username="handle")
    payload = C._user_payload(user)
    assert payload["user_id"] == "7012345678"
    assert payload["unique_id"] == "handle"
    assert payload["nickname"] == "Nick"
    assert payload["identity_key"] == "7012345678"


def test_event_user_survives_multi_word_proto_fields():
    """event.userはExtendedUser.from_user経由。TikTokLive 6.6.5はここでto_pydictを
    casing無しで呼ぶためnick_nameがnickNameになりTypeErrorで落ちる(ttlive_compatで補正)。
    既存testはExtendedUserを直に組むのでisinstanceで素通りし、この経路を通らない。"""
    event = CommentEvent(
        user_info=User(id=7_012_345_678, nick_name="Nick", username="handle", sec_uid="sec"),
        content="やあ",
    )
    payload = C._user_payload(event.user)
    assert payload["nickname"] == "Nick"
    assert payload["unique_id"] == "handle"
    assert payload["identity_key"] == "7012345678"


def test_user_payload_falls_back_unique_id_then_unknown_for_the_display_name():
    assert C._user_payload(ExtendedUser(username="handle"))["nickname"] == "handle"
    anonymous = C._user_payload(ExtendedUser())
    assert anonymous["nickname"] == "(unknown)"
    # 表示用の "(unknown)" は名寄せkeyに漏らさない。身元不明はkey無し("")で、user=None
    # 経路と同じ扱いにする(経路差でidentityが変わらない)。
    assert anonymous["identity_key"] == ""
    assert C._user_payload(None)["identity_key"] == ""


def test_user_payload_does_not_fold_unidentified_viewers_into_one_identity(collector):
    # 身元不明の視聴者は互いに別人。表示名が同じ "(unknown)" でも1 identityへ畳まない。
    a = C._user_payload(ExtendedUser())
    b = C._user_payload(ExtendedUser())
    assert a["identity_key"] == "" and b["identity_key"] == ""
    assert collector._touch_user(a) == ""
    assert collector._touch_user(b) == ""
    # keyの無いUserはSession registryに入らない(入れば全員が同じ1行へ潰れる)。
    assert collector.users == {}
    # @handleしか無いUserは畳まれずhandleで名寄せされる(こちらは身元がある)。
    named = C._user_payload(ExtendedUser(username="handle"))
    assert collector._touch_user(named) == "handle"
    assert set(collector.users) == {"handle"}


@pytest.mark.asyncio
async def test_gift_ranking_does_not_fold_unidentified_gifters_into_one_entry(collector, monkeypatch):
    """身元不明のgifterはranking(self.gifters)に載せない。表示名 "(unknown)" をkeyに
    落とすと、別人のgiftが1人分として合算され、その1行が上位を占める。"""
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(collector, "_record", _noop)
    monkeypatch.setattr(collector, "_emit_only", _noop)

    def _gift(user):
        return SimpleNamespace(
            user=user,
            gift=SimpleNamespace(name="rose", diamond_count=10, image=None, id=0),
            repeat_count=1,
            streaking=False,
            base_message=SimpleNamespace(create_time=0),
        )

    await collector._on_gift(_gift(ExtendedUser()))
    await collector._on_gift(_gift(ExtendedUser()))
    assert collector.gifters == {}
    assert collector.users == {}
    # 身元のあるgifterは従来どおり積まれる。
    await collector._on_gift(_gift(ExtendedUser(username="handle")))
    assert set(collector.gifters) == {"handle"}
    assert collector.gifters["handle"]["diamonds"] == 10
    # gift総数は身元の有無に関わらず数える(落とすのはranking行だけ)。
    assert collector.stats["gifts"] == 3


@pytest.mark.asyncio
async def test_opponent_gift_uses_the_payload_identity_key(collector, monkeypatch):
    """相手陣の貢献者も _user_payload のidentity_keyで名寄せする。ここで
    user_id/unique_id/nickname から再計算すると "(unknown)" で別人が畳まれる。"""
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(collector, "_broadcast_battles", _noop)
    rec = {"contributions": {}, "participants": {"h2": {"user_id": "h2", "side": "opp"}}}
    collector._battles[1] = rec
    await collector._on_opponent_gift("h2", C._user_payload(ExtendedUser()), 10)
    await collector._on_opponent_gift("h2", C._user_payload(ExtendedUser()), 20)
    assert rec["contributions"] == {}
    await collector._on_opponent_gift("h2", C._user_payload(ExtendedUser(username="rival")), 30)
    assert set(rec["contributions"]) == {"rival"}


@pytest.mark.asyncio
async def test_peer_gift_lands_on_the_battle_that_peer_is_fighting(collector, monkeypatch):
    """listenerはPKの外(コラボ中)でも生きているので、Gift の宛先は「そのhostが今戦って
    いる進行中のBattle」に限る。終わったPKや、その相手が居ないPKへ入れない。"""
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(collector, "_broadcast_battles", _noop)
    done = {"contributions": {}, "action": C.BATTLE_ACTION_FINISH,
            "participants": {"h2": {"user_id": "h2", "side": "opp"}}}
    live = {"contributions": {}, "action": None,
            "participants": {"h2": {"user_id": "h2", "side": "opp"}}}
    collector._battles[1] = done
    collector._battles[2] = live
    await collector._on_opponent_gift("h2", C._user_payload(ExtendedUser(username="rival")), 30)
    assert done["contributions"] == {}
    assert live["contributions"]["rival"]["diamonds"] == 30

    # 進行中のPKにそのhostが居なければ、どこにも入れない(コラボ中の通常Gift)。
    other = {"contributions": {}, "action": None,
             "participants": {"h9": {"user_id": "h9", "side": "opp"}}}
    collector._battles.clear()
    collector._battles[3] = other
    await collector._on_opponent_gift("h2", C._user_payload(ExtendedUser(username="rival")), 30)
    assert other["contributions"] == {}


@pytest.mark.asyncio
async def test_peer_gift_takes_the_side_from_participants(collector, monkeypatch):
    """味方hostのRoomも張る。拾った実弾を"opp"に決め打つと、味方の貢献が敵陣として
    記録され、配信者profileの敵陣集計が味方を数える。"""
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(collector, "_broadcast_battles", _noop)
    rec = {"contributions": {}, "action": None,
           "participants": {"mate": {"user_id": "mate", "side": "own", "is_own": False}}}
    collector._battles[1] = rec
    await collector._on_opponent_gift("mate", C._user_payload(ExtendedUser(username="fan")), 40)
    assert rec["contributions"]["fan"]["side"] == "own"
    assert rec["contributions"]["fan"]["host_id"] == "mate"


def test_user_payload_takes_member_level_from_the_fans_badge_when_fans_club_is_empty():
    fans_badge = BadgeStruct(
        badge_scene=BadgeStructBadgeSceneType(C.BADGE_SCENE_FANS),
        log_extra=PrivilegeLogExtra(level="21"),
        image_badge=ImageBadge(image_model=_img("member.png")),
    )
    grade_badge = BadgeStruct(
        badge_scene=BadgeStructBadgeSceneType(C.BADGE_SCENE_USER_GRADE),
        log_extra=PrivilegeLogExtra(level="35"),
        image_badge=ImageBadge(image_model=_img("grade.png")),
    )
    user = ExtendedUser(id=1, badge_list=[fans_badge, grade_badge])
    payload = C._user_payload(user)
    assert payload["fans_level"] == 21
    assert payload["member_badge"] == "member.png"
    assert payload["gifter_level"] == 35
    assert payload["gifter_badge"] == "grade.png"


def test_user_payload_prefers_fans_club_info_level_over_the_badge():
    fans_badge = BadgeStruct(
        badge_scene=BadgeStructBadgeSceneType(C.BADGE_SCENE_FANS), log_extra=PrivilegeLogExtra(level="21")
    )
    user = ExtendedUser(
        id=1, badge_list=[fans_badge], fans_club_info=UserFansClubInfo(fans_level=4)
    )
    assert C._user_payload(user)["fans_level"] == 4


# ---------------- 流入元 / follow / comment signals ----------------


def test_enter_signals_marks_missing_fields_unknown_not_empty():
    event = SimpleNamespace(client_enter_source="  homepage_hot  ", client_enter_type="")
    assert C._enter_signals(event) == {
        "enter_source": "homepage_hot",
        "enter_type": C.ENTRY_UNKNOWN,
        "enter_reason": C.ENTRY_UNKNOWN,
    }


def test_follow_signals_never_rounds_a_missing_message_down_to_not_following():
    absent = C._follow_signals(SimpleNamespace(follow_info=None))
    assert absent == {"follow_status": C.FOLLOW_UNKNOWN, "follower_count": None}
    # message自体が空 instance(未送出)でも unknown のまま。
    assert C._follow_signals(SimpleNamespace(follow_info=FollowInfo()))["follow_status"] == (
        C.FOLLOW_UNKNOWN
    )
    # wireに載っていれば 0 は「非follower」として読む。
    on_wire = C._follow_signals(SimpleNamespace(follow_info=_on_wire(FollowInfo(follower_count=3))))
    assert on_wire == {"follow_status": "not_following", "follower_count": 3}
    mutual = C._follow_signals(SimpleNamespace(follow_info=FollowInfo(follow_status=2)))
    assert mutual["follow_status"] == "mutual"


def test_identity_signals_absent_message_leaves_flags_unobserved():
    out = C._identity_signals(SimpleNamespace(user_identity=UserIdentity()))
    assert out == {
        "follow_status": C.FOLLOW_UNKNOWN,
        "is_subscriber": None,
        "is_moderator": None,
        "is_gift_giver": None,
    }


def test_identity_signals_mutual_wins_over_follower():
    ident = UserIdentity(
        is_mutual_following_with_anchor=True,
        is_follower_of_anchor=True,
        is_subscriber_of_anchor=True,
    )
    out = C._identity_signals(SimpleNamespace(user_identity=ident))
    assert out["follow_status"] == "mutual"
    assert out["is_subscriber"] == 1
    assert out["is_moderator"] == 0

    only_follower = C._identity_signals(
        SimpleNamespace(user_identity=UserIdentity(is_follower_of_anchor=True))
    )
    assert only_follower["follow_status"] == "following"


def test_share_signals_report_unknown_for_absent_scalars():
    assert C._share_signals(SimpleNamespace()) == {
        "share_type": C.SHARE_UNKNOWN,
        "share_target": C.SHARE_UNKNOWN,
    }
    filled = C._share_signals(SimpleNamespace(share_type=112, share_target=" -1 "))
    assert filled == {"share_type": "112", "share_target": "-1"}


def test_comment_signals_serialize_tags_as_enum_names():
    event = SimpleNamespace(
        content_language=" ja ",
        comment_tag=[SimpleNamespace(name="SUBSCRIBER"), 3],
    )
    out = C._comment_signals(event)
    assert out["content_language"] == "ja"
    assert json.loads(out["comment_tag"]) == ["SUBSCRIBER", "3"]

    empty = C._comment_signals(SimpleNamespace())
    assert empty == {
        "content_language": C.COMMENT_UNKNOWN,
        "comment_tag": C.COMMENT_UNKNOWN,
    }


def test_emote_payload_drops_entries_without_an_image_and_returns_none_when_empty():
    good = SimpleNamespace(
        index=3, emote_model=SimpleNamespace(emote_id=99, image=_img("https://cdn/e.png"))
    )
    no_url = SimpleNamespace(index=1, emote_model=SimpleNamespace(emote_id=1, image=None))
    no_model = SimpleNamespace(index=2, emote_model=None)
    payload = C._emote_payload(SimpleNamespace(f315_emotes=[good, no_url, no_model]))
    assert json.loads(payload) == [{"index": 3, "id": "99", "url": "https://cdn/e.png"}]

    assert C._emote_payload(SimpleNamespace(f315_emotes=[no_url])) is None
    assert C._emote_payload(SimpleNamespace(f315_emotes=[])) is None
    assert C._emote_payload(SimpleNamespace()) is None


# ---------------- スーパーファン加入 ----------------


def _super_fan_event(*users, key="ttlive_superFan_join"):
    """実配信と同形のSuperFanEvent。Barrage系はuser fieldを持たず、表示文のTextPiece
    にしか本人が載らないので、必ずwire経由(parse)で組んでその読み出しを検証する。"""
    message = WebcastBarrageMessage(
        base_message=CommonMessageData(create_time=1700000000),
        content=Text(
            key=key,
            pieces=[TextPiece(user_value=TextPieceUser(user=user)) for user in users],
        ),
    )
    return C.SuperFanEvent().parse(bytes(message))


def test_super_fan_user_comes_from_the_text_piece_not_a_user_field():
    event = _super_fan_event(User(id=9001, nick_name="2B"))
    assert not hasattr(event, "user")
    payload = C._user_payload(C._barrage_user(event))
    assert payload["nickname"] == "2B"
    assert payload["identity_key"] == "9001"


def test_super_fan_skips_empty_pieces_and_never_invents_a_user():
    # 空のuser pieceは「載っていない」。ここを拾うと身元不明が1 identityへ畳まれる。
    event = _super_fan_event(User(), User(id=9002, nick_name="Pod 042"))
    assert C._user_payload(C._barrage_user(event))["nickname"] == "Pod 042"

    empty = _super_fan_event(User())
    assert C._barrage_user(empty) is None
    assert C._user_payload(C._barrage_user(empty))["nickname"] == "(unknown)"
    assert C._barrage_user(C.SuperFanEvent().parse(b"")) is None


def test_super_fan_reads_the_simulation_shape_too():
    """simulationが流す擬似eventも同じ経路で読めること。presence判定をbetterproto専用に
    すると本番だけ通ってsimulationが身元不明に落ち、画面の表示経路を検証できなくなる。"""
    user = SimpleNamespace(unique_id="pod042", nick_name="Pod 042", id=2002)
    event = SimpleNamespace(
        content=SimpleNamespace(pieces=[SimpleNamespace(user_value=SimpleNamespace(user=user))])
    )
    assert C._user_payload(C._barrage_user(event))["nickname"] == "Pod 042"


@pytest.mark.asyncio
async def test_super_fan_is_stored_as_its_own_kind(collector, tmp_db, db_read, make_session):
    """スーパーファン加入がevents表へ残ること。SubscribeEvent(サブスク)とは別messageで
    届くため、subscribeを待つ経路では永久に入らない。"""
    collector.session_id = make_session("streamer", status="connected")

    await collector._on_super_fan(_super_fan_event(User(id=9001, nick_name="2B")))

    tmp_db.flush()
    row = db_read.execute(
        "SELECT kind, text, user_nickname, identity_key, create_time"
        " FROM events WHERE session_id = ?", (collector.session_id,)
    ).fetchone()
    assert row["kind"] == "super_fan"
    assert row["text"] == "2B がスーパーファンになりました"
    assert row["user_nickname"] == "2B"
    assert row["identity_key"] == "9001"
    # 表示順の基準になるTikTok側時刻を落とさない(焼き込みのMode Bが使う)。
    assert row["create_time"] == 1700000000
    assert collector.stats["super_fans"] == 1


# ---------------- 列を持たないfieldの保存(events.extra / battles) ----------------


def test_extra_keeps_fields_that_have_no_column_of_their_own():
    """専用の列が無いだけで捨てていたfieldを残すこと。base_message側(room単位)と
    event本体側の両方を拾う。"""
    msg = WebcastLikeMessage(
        base_message=CommonMessageData(room_message_heat_level=3, fold_type=1),
        count=2, total=10, effect_cnt=4,
    )
    extra = json.loads(C._extra_payload(LikeEvent().parse(bytes(msg)), "like"))
    assert extra["room_message_heat_level"] == 3
    assert extra["fold_type"] == 1
    assert extra["effect_cnt"] == 4


def test_extra_is_null_when_nothing_arrived():
    """1つも載っていなければNULL。空dictを入れると「観測したが空」に見えてしまい、
    計装前の未計測と区別できなくなる。"""
    assert C._extra_payload(LikeEvent().parse(b""), "like") is None
    # kindに登録の無いeventでもbase_message側だけは拾う。
    msg = WebcastLikeMessage(base_message=CommonMessageData(room_message_heat_level=2))
    assert json.loads(C._extra_payload(LikeEvent().parse(bytes(msg)), "battle")) == {
        "room_message_heat_level": 2
    }


def test_share_count_is_kept_even_though_the_row_counts_as_one():
    """1回のshareで何人に送ったか。events行は1本なので、ここを捨てると人数が消える。"""
    msg = WebcastSocialMessage(share_count=7)
    extra = json.loads(C._extra_payload(SocialEvent().parse(bytes(msg)), "share"))
    assert extra["share_count"] == 7


@pytest.mark.asyncio
async def test_extra_round_trips_into_the_events_table(collector, tmp_db, db_read, make_session):
    """列順は _EVENTS_COLUMNS と ingest.add_event の位置対応で決まる。ここがずれると
    journal復元まで巻き添えになるので、実際にDBへ入れて読み直す。"""
    collector.session_id = make_session("streamer", status="connected")
    msg = WebcastLikeMessage(
        base_message=CommonMessageData(room_message_heat_level=5),
        user=User(id=9001, nick_name="2B"), count=2, total=10, effect_cnt=3,
    )

    await collector._on_like(LikeEvent().parse(bytes(msg)))

    tmp_db.flush()
    row = db_read.execute(
        "SELECT kind, count, extra FROM events WHERE session_id = ?",
        (collector.session_id,),
    ).fetchone()
    assert row["kind"] == "like" and row["count"] == 2
    assert json.loads(row["extra"]) == {"room_message_heat_level": 5, "effect_cnt": 3}


@pytest.mark.asyncio
async def test_battle_keeps_the_official_result_without_touching_our_own(collector):
    """TikTokが確定させた勝敗を残す。自前で追っている own_score/result とは別の源なので、
    照合も上書きもせず両方持つ(照合は解析側の判断)。"""
    official = {"9001": {"user_id": 9001, "result": "RESULT_LOSE", "score": 4140}}
    await collector._on_battle(SimpleNamespace(
        battle_id=77, action=None, battle_setting=None, anchor_info=None,
        battle_result=official, action_by_user_id="9001",
    ))

    rec = collector._battles[77]
    assert rec["battle_result"] == official
    assert rec["action_by_user_id"] == "9001"
    # 自前の判定は書き換えない。
    assert rec["own_score"] == 0 and rec["result"] is None


@pytest.mark.asyncio
async def test_battle_extras_are_not_erased_by_a_later_event(collector):
    """armiesは同じbattleへ何度も届き、毎回すべてのfieldを載せてくるわけではない。
    値の無い回で既存を消すと、最後の1件だけが残って履歴が壊れる。"""
    await collector._on_battle(SimpleNamespace(
        battle_id=77, action=None, battle_setting=None, anchor_info=None,
        battle_result={"9001": {"score": 1}},
    ))
    await collector._on_battle(SimpleNamespace(
        battle_id=77, action=None, battle_setting=None, anchor_info=None,
    ))
    assert collector._battles[77]["battle_result"] == {"9001": {"score": 1}}


@pytest.mark.asyncio
async def test_punish_finish_records_the_end_of_the_victory_time(collector):
    """PK後の勝利(罰ゲーム)時間の終わりは、この event でしか判らない(battle settingが持つのは
    PK本体のstart/end/durationだけ)。時刻はserver時計(create_time)で採る — end_timeも
    server時計なので、受信時刻で埋めると窓の長さに受信遅延が混ざる。"""
    await collector._on_battle(SimpleNamespace(
        battle_id=77, action=None, anchor_info=None,
        battle_setting=SimpleNamespace(start_time_ms=1_783_156_030_000, duration=300,
                                       end_time_ms=1_783_156_335_000),
    ))
    await collector._on_punish_finish(SimpleNamespace(
        battle_id=77, reason=1,
        base_message=SimpleNamespace(create_time=1_783_156_515_000),
    ))

    rec = collector._battles[77]
    # PK終了(…335)の180秒後。
    assert rec["punish_end_time"] == 1_783_156_515.0
    assert rec["punish_reason"] == 1


@pytest.mark.asyncio
async def test_punish_finish_of_an_unknown_battle_does_not_create_a_record(collector):
    """接続前に始まったPKの分は突合先が無い。空のBattleを作ると、1戦も無い録画にPKが
    生えることになる。"""
    await collector._on_punish_finish(SimpleNamespace(
        battle_id=88, reason=None,
        base_message=SimpleNamespace(create_time=1_783_156_515_000),
    ))
    assert 88 not in collector._battles


@pytest.mark.asyncio
async def test_item_cards_other_than_the_glove_are_kept_and_deduped(collector):
    """グローブ以外の道具cardは1件も残していなかった。同じcardは複数回届くので畳む。"""
    event = SimpleNamespace(
        battle_id=77, msg_type=None,
        use_smoke_card={"card_info": {"card_name_key": "pm_mt_boost_mist_name"}},
    )
    await collector._on_item_card(event)
    await collector._on_item_card(event)

    cards = collector._battles[77]["item_cards"]
    assert [c["kind"] for c in cards] == ["use_smoke_card"]
    assert cards[0]["card"] == {"card_info": {"card_name_key": "pm_mt_boost_mist_name"}}


# ---------------- league ----------------


def test_extract_league_reads_the_only_known_source_and_never_invents():
    payload = {"gifts_info": {"gift_gallery_info": {"anchor_ranking_league": " B3 "}}}
    assert C._extract_league(payload) == "B3"
    assert C._extract_league({"gifts_info": {}}) == ""
    assert C._extract_league({"gifts_info": {"gift_gallery_info": {}}}) == ""
    assert C._extract_league(None) == ""
    assert C._extract_league("not a dict") == ""


# ---------------- sign server outage ----------------


def _sign_error(reason, status=None):
    from TikTokLive.client.errors import SignAPIError

    response = None if status is None else SimpleNamespace(status_code=status, headers={})
    return SignAPIError(reason, "boom", response=response)


@pytest.mark.parametrize("reason", ["RATE_LIMIT", "CONNECT_ERROR", "EMPTY_PAYLOAD", "EMPTY_COOKIES"])
def test_sign_server_outage_classifies_server_side_reasons_as_external(reason):
    from TikTokLive.client.errors import SignAPIError

    outage = C.sign_server_outage(_sign_error(SignAPIError.ErrorReason[reason]))
    assert outage is not None
    assert "sign server" in outage["reason"]
    assert outage["ctx"]["sign_reason"] == reason


def test_sign_server_outage_treats_non_200_by_status_class():
    from TikTokLive.client.errors import SignAPIError

    # 5xxはsign server自身の不調 -> 外部要因として1行に落とす。
    outage = C.sign_server_outage(_sign_error(SignAPIError.ErrorReason.SIGN_NOT_200, 500))
    assert outage is not None and outage["ctx"]["sign_status"] == 500
    assert "500" in outage["reason"]
    # 4xxはこちらのrequest/keyの問題なので隠さない(Stack Trace経路のまま)。
    assert C.sign_server_outage(_sign_error(SignAPIError.ErrorReason.SIGN_NOT_200, 403)) is None
    # statusが読めないSIGN_NOT_200も外部と断定できないので隠さない。
    assert C.sign_server_outage(_sign_error(SignAPIError.ErrorReason.SIGN_NOT_200)) is None


async def _connect_raising(collector, exc, room_id=7000):
    """_connect_onceを1回だけ回し、client.connectが投げるexcの分類結果を返す。"""
    async def _connect(**_kwargs):
        raise exc

    collector._resolved_room_id = room_id
    collector._client = SimpleNamespace(connect=_connect, room_id=room_id, room_info={})
    return await collector._connect_once()


@pytest.mark.asyncio
async def test_repeated_sign_failures_on_one_room_stop_the_reconnect_loop(collector):
    """同じroomだけが署名を拒まれ続けるなら、撃ち直しても結果は変わらない。規定回数で
    transient(=session内の再接続loop)を降り、room単位の保留へ移すこと。

    実測: room 7672781787921353493は1時間48分で97回500を返し続けた一方、同じ時刻に別の
    監視対象は同じsign serverで再接続に成功していた。sign server全体の障害ではない。"""
    from TikTokLive.client.errors import SignAPIError

    exc = _sign_error(SignAPIError.ErrorReason.SIGN_NOT_200, 500)
    threshold = collector._settings.get("sign_block_attempts")

    for attempt in range(1, threshold):
        outcome, _reason = await _connect_raising(collector, exc)
        assert outcome == "transient", f"{attempt}回目はまだ一時障害と見分けが付かない"

    outcome, reason = await _connect_raising(collector, exc)
    assert outcome == "unsigned"
    assert "署名" in reason


@pytest.mark.asyncio
async def test_signer_timeouts_count_as_sign_failures_not_as_tiktok_network_errors(collector, caplog):
    """署名要求のtimeoutは「TikTokとの通信」ではなくsign server側の失敗。署名失敗として
    数えなければ、署名が通らないまま撃ち続けるroomがroom単位の保留へ落ちない。"""
    threshold = collector._settings.get("sign_block_attempts")

    with caplog.at_level("WARNING", logger="tictok.collector"):
        for attempt in range(1, threshold):
            outcome, reason = await _connect_raising(collector, _signer_timeout())
            assert outcome == "transient" and "sign server" in reason, f"{attempt}回目"
        outcome, _reason = await _connect_raising(collector, _signer_timeout())

    assert outcome == "unsigned"
    assert collector._sign_failures == threshold
    events = [r.event for r in caplog.records if r.name == "tictok.collector"]
    assert "collector.network_error_raised" not in events
    assert all(r.exc_info is None for r in caplog.records if r.name == "tictok.collector")


@pytest.mark.asyncio
async def test_tiktok_side_network_errors_stay_network_errors(collector, caplog):
    """signer以外への通信断はsign serverの失敗ではない。署名失敗として数えない。"""
    with caplog.at_level("WARNING", logger="tictok.collector"):
        outcome, _reason = await _connect_raising(
            collector, _signer_timeout("https://www.tiktok.com/x")
        )
    assert outcome == "transient"
    assert collector._sign_failures == 0
    assert [r.event for r in caplog.records
            if r.name == "tictok.collector"] == ["collector.network_error_raised"]


@pytest.mark.asyncio
async def test_sign_failures_after_a_successful_connect_stay_transient(collector):
    """一度でも繋がった配信の再接続は打ち切らない。接続後の署名失敗は本物の一時障害でも
    起こり、ここで諦めると録画中の配信を余計に待たせる。"""
    from TikTokLive.client.errors import SignAPIError

    exc = _sign_error(SignAPIError.ErrorReason.SIGN_NOT_200, 500)
    collector._ever_connected = True

    for _ in range(collector._settings.get("sign_block_attempts") + 3):
        outcome, _reason = await _connect_raising(collector, exc)
        assert outcome == "transient"


@pytest.mark.asyncio
async def test_a_room_already_held_as_unsigned_is_dropped_on_the_first_failure(collector):
    """保留中のroomへ撃ち直して同じ結果なら、閾値を待たず1回で保留へ戻す。待ち時間だけ
    広げればよく、同じ答えを聞き直す意味は無い。"""
    from TikTokLive.client.errors import SignAPIError

    collector._unsigned_room_id = 7000
    outcome, _reason = await _connect_raising(
        collector, _sign_error(SignAPIError.ErrorReason.SIGN_NOT_200, 500), room_id=7000
    )
    assert outcome == "unsigned"


def _stub_outcome(outcome):
    async def _run():
        return outcome

    return _run


def _stub_room_payload(collector, monkeypatch, data):
    async def _fetch(_room_id):
        return data

    monkeypatch.setattr(collector, "_fetch_room_payload", _fetch)


@pytest.mark.asyncio
async def test_an_unsigned_broadcast_leaves_one_folded_row_and_keeps_watching(
    collector, monkeypatch
):
    """署名が通らない配信は録画不可の行を1本だけ残し、監視は続ける。撃ち直すたびに行が
    伸びないよう、同じroomの2本目以降は既存行へ畳むこと。"""
    monkeypatch.setattr(collector, "_session_loop", _stub_outcome("unsigned"))
    _stub_room_payload(collector, monkeypatch, {"id": 7000, "title": "普通の配信"})
    collector._resolved_room_id = 7000

    for _ in range(3):
        collector._prepare_session()
        assert await collector._run_session() == "continue"

    rows = [s for s in collector._storage.list_sessions(0) if s["status"] == "restricted"]
    assert len(rows) == 1, "同じroomの試行は1行に畳む"
    assert rows[0]["room_id"] == "7000", "どのroomで録画できなかったかは行に残す"
    assert collector._unsigned_room_id == 7000
    assert collector._restricted_room_id is None, "限定配信ではないので制限holdへは回さない"


def _stub_connect(outcome, reason=""):
    async def _connect_once():
        return (outcome, reason)

    return _connect_once


# 録画できる普通のroomのpayload(署名を使わないGETで返るもの)。stream URLが取れる形。
_RECORDABLE_PAYLOAD = {
    "id": 7000,
    "stream_url": {"flv_pull_url": {"HD1": "https://pull.example/live.flv"}},
}


@pytest.mark.asyncio
async def test_a_limited_broadcast_behind_a_sign_failure_goes_to_the_restricted_hold(
    collector, monkeypatch
):
    """署名の失敗が限定配信の裏返しだったなら、撃ち直しても録画はできない。制限holdへ
    回して間隔を広げ、署名を無駄打ちしないこと。"""
    monkeypatch.setattr(collector, "_connect_once", _stub_connect("unsigned", "署名が通りません"))
    _stub_room_payload(collector, monkeypatch, {"prompts": "", "message": None})
    collector._resolved_room_id = 7000

    assert await collector._session_loop() == "restricted"


@pytest.mark.asyncio
async def test_a_room_that_will_not_sign_is_recorded_video_only_and_keeps_retrying(
    collector, monkeypatch
):
    """録画は署名を必要としない。署名が通らなくても映像URLが取れるなら先に録り始め、
    sessionを畳まずに署名を撃ち直し続けること(通れば同じ録画へeventが合流する)。"""
    started = []

    async def _start_recorder():
        started.append(True)
        collector.recorder = SimpleNamespace(is_active=True, recording_id=1)

    monkeypatch.setattr(C, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(collector, "_start_recorder", _start_recorder)
    monkeypatch.setattr(collector, "_connect_once", _stub_connect("unsigned", "署名が通りません"))
    _stub_room_payload(collector, monkeypatch, _RECORDABLE_PAYLOAD)

    async def _wait(reason):
        assert "映像のみ録画中" in reason, "撃ち直しの理由に映像を録っていることを載せる"
        return "ended"

    monkeypatch.setattr(collector, "_wait_for_reconnect", _wait)
    collector._resolved_room_id = 7000
    collector._prepare_session()

    assert await collector._session_loop() == "ended", "配信が終わるまでsessionは畳まない"
    assert started == [True]
    assert collector._video_only_active()


@pytest.mark.asyncio
async def test_video_only_does_not_re_probe_the_room_on_every_retry(collector, monkeypatch):
    """診断は録り始める前の1回だけ。撃ち直すたびに引き直すと、配信の間ずっと同じ観測を
    繰り返してlogを埋める。"""
    probes = []

    async def _fetch(room_id):
        probes.append(room_id)
        return _RECORDABLE_PAYLOAD

    async def _start_recorder():
        collector.recorder = SimpleNamespace(is_active=True, recording_id=1)

    retries = []

    async def _wait(_reason):
        retries.append(True)
        return "retry" if len(retries) < 3 else "ended"

    monkeypatch.setattr(C, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(collector, "_fetch_room_payload", _fetch)
    monkeypatch.setattr(collector, "_start_recorder", _start_recorder)
    monkeypatch.setattr(collector, "_connect_once", _stub_connect("unsigned", "署名が通りません"))
    monkeypatch.setattr(collector, "_wait_for_reconnect", _wait)
    collector._resolved_room_id = 7000
    collector._prepare_session()

    assert await collector._session_loop() == "ended"
    assert probes == [7000], "診断は1回だけ"


@pytest.mark.asyncio
async def test_a_room_with_no_stream_url_is_not_pretended_to_be_recording(
    collector, monkeypatch
):
    """映像URLが取れないなら録画は始まらない。始まったふりをすると、録れていない配信を
    録れているものとして扱うことになる。"""
    monkeypatch.setattr(C, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(collector, "_connect_once", _stub_connect("unsigned", "署名が通りません"))
    _stub_room_payload(collector, monkeypatch, {"id": 7000, "title": "映像URLの無いpayload"})
    collector._resolved_room_id = 7000
    collector._prepare_session()

    assert await collector._session_loop() == "unsigned"
    assert not collector._video_only


@pytest.mark.asyncio
async def test_a_room_that_cannot_be_observed_is_treated_as_still_recordable(
    collector, monkeypatch
):
    """観測できないことを理由に諦めない。判らない側へ倒すと、録れたはずの配信を落とす。"""
    _stub_room_payload(collector, monkeypatch, None)
    assert await collector._diagnose_unsigned_room(7000) == ("recordable", None)


def test_unsigned_retry_keeps_the_base_interval_and_resets_on_a_new_room(collector):
    """撃ち直しの間隔は広げない。広げた分だけ配信の頭を落とすため、粘る側に倒す。"""
    base = collector._settings.get("restricted_recheck_interval")

    assert [collector._arm_unsigned_retry(7000) for _ in range(10)] == [base] * 10
    assert collector._unsigned_room_id == 7000

    assert collector._arm_unsigned_retry(8000) == base
    assert collector._unsigned_attempts == 1, "別roomは回数を持ち越さない"


@pytest.mark.asyncio
async def test_a_session_that_never_connects_still_carries_the_resolved_owner(collector):
    """connectまで届かなかった配信でも、session行はその時点で観測した身元を持つこと。
    owner_avatarがroom_info経由でしか書かれなかったため、署名が通らない/制限の行は
    履歴で頭文字の円盤になっていた。"""
    await collector._apply_resolved_owner(
        SimpleNamespace(avatar="https://cdn.example/a.webp", nickname="ぽみ", room_id=7000)
    )
    collector._resolved_room_id = 7000
    collector._prepare_session()

    row = collector._storage.get_session(collector.session_id)
    assert row["owner_avatar"] == "https://cdn.example/a.webp"
    assert row["owner_nickname"] == "ぽみ"


def test_a_session_with_nothing_resolved_does_not_borrow_another_sessions_owner(collector):
    """観測できていない身元は書かない。他sessionから借りた値を行へ書くと、過去sessionを
    当時の身元で表示する前提が崩れる(表示だけのfallbackはUI側の役目)。"""
    collector._resolved_room_id = 7000
    collector._prepare_session()

    row = collector._storage.get_session(collector.session_id)
    assert not row["owner_avatar"]


def test_sign_server_outage_does_not_hide_entitlement_or_unrelated_failures():
    from TikTokLive.client.errors import SignAPIError

    # API keyの権限不足は設定で直せる自陣の問題。一時障害へ吸わせない。
    for reason in ("PREMIUM_ENDPOINT", "AUTHENTICATED_WS"):
        assert C.sign_server_outage(_sign_error(SignAPIError.ErrorReason[reason])) is None
    assert C.sign_server_outage(RuntimeError("unrelated")) is None


def _signer_timeout(url="https://tiktok.eulerstream.com/webcast/fetch/?room_id=1"):
    """署名要求(timeout=15秒)が応答を待ち切れずに落ちた形。TikTokLiveがSignAPIErrorへ
    包むのはConnectErrorだけなので、これは生のhttpx例外のまま上がってくる。"""
    import httpx
    return httpx.ReadTimeout("", request=httpx.Request("GET", url))


def test_sign_server_outage_names_a_timeout_against_the_signer():
    """署名要求のReadTimeoutは5xxと同じsign server側の失敗。分類できないままだと、
    httpx/httpcore内部で終わるStack Traceとして積まれる(実測44件)。"""
    outage = C.sign_server_outage(_signer_timeout())
    assert outage is not None
    assert "sign server" in outage["reason"] and "ReadTimeout" in outage["reason"]
    assert outage["ctx"]["sign_request_path"] == "/webcast/fetch/"
    assert outage["retry_after"] is None


def test_sign_server_outage_does_not_claim_unaddressed_or_tiktok_side_timeouts():
    """宛先が signer でない通信断まで吸わせない(TikTok宛の通信断はsign serverの失敗
    ではない)。宛先が判らないものも断定しない。"""
    import httpx
    assert C.sign_server_outage(_signer_timeout("https://www.tiktok.com/x")) is None
    assert C.sign_server_outage(httpx.ReadTimeout("no request attached")) is None


def test_expected_transient_names_route_and_websocket_interruptions_only():
    from websockets.exceptions import ConnectionClosedError

    transient = C.expected_transient(_signer_timeout("https://www.tiktok.com/x"))
    assert transient["ctx"]["request_host"] == "www.tiktok.com"
    closed = C.expected_transient(ConnectionClosedError(None, None))
    assert "websocket" in closed["reason"]
    # 分類できない失敗はNone=Stack Trace経路のまま(未知の失敗を外部要因へ吸わせない)。
    assert C.expected_transient(RuntimeError("unrelated")) is None


@pytest.mark.asyncio
async def test_opponent_listener_logs_sign_outage_without_a_traceback(caplog, monkeypatch):
    from TikTokLive.client.errors import SignAPIError

    class _Resolver:
        async def resolve(self, _handle):
            raise _sign_error(SignAPIError.ErrorReason.SIGN_NOT_200, 500)

    class _Gate:
        async def acquire(self, priority=False):
            return None

    listener = C.OpponentRoomListener(
        "rina__0910", "123", _Resolver(), _Gate(), None
    )
    with caplog.at_level("WARNING", logger="tictok.collector"):
        await listener._run()

    records = [r for r in caplog.records if r.event == "collector.opponent_listener_sign_unavailable"]
    assert len(records) == 1
    assert records[0].exc_info is None
    # 5xxを「一時障害」と名乗らない(実測112分に散る個別失敗で、原因は未確認)。
    assert "一時障害" not in records[0].getMessage()
    assert "接続できませんでした" in records[0].getMessage()
    assert records[0].ctx["opp_host_id"] == "123"
    assert records[0].ctx["sign_status"] == 500
    # retry_seconds=0(既定の引数)は「1回で諦める」。撃ち切ったことを名乗る。
    assert records[0].ctx["retry_in_seconds"] == 0
    assert listener.coverage()["attached_at"] is None


@pytest.mark.asyncio
async def test_opponent_listener_logs_expected_interruptions_without_a_traceback(caplog):
    """相手Roomのwebsocket切断・通信断はこちらのcodeでは直せず、Stack Traceはhttpxと
    websocketsの内部で終わる(実測: Stack Trace 113件のうち86件がこの2種)。1行で残す。"""
    from websockets.exceptions import ConnectionClosedError

    class _Resolver:
        async def resolve(self, _handle):
            raise ConnectionClosedError(None, None)

    class _Gate:
        async def acquire(self, priority=False):
            return None

    listener = C.OpponentRoomListener("rina__0910", "123", _Resolver(), _Gate(), None)
    with caplog.at_level("WARNING", logger="tictok.collector"):
        await listener._run()

    records = [r for r in caplog.records if r.event == "collector.opponent_listener_transient"]
    assert len(records) == 1
    assert records[0].exc_info is None
    assert "websocket" in records[0].getMessage()
    assert records[0].ctx["opp_unique_id"] == "rina__0910"
    assert not [r for r in caplog.records if r.event == "collector.opponent_listener_failed"]


@pytest.mark.asyncio
async def test_peer_listener_retries_after_a_sign_failure(caplog):
    """sign serverの5xxは時刻を変えれば通る(実測: 500を受けた80 hostのうち66 hostは別の
    PKで取得できている)。1回で諦めるとPKの残り時間を丸ごと捨てる。"""
    from TikTokLive.client.errors import SignAPIError

    class _Resolver:
        def __init__(self):
            self.calls = 0

        async def resolve(self, _handle):
            self.calls += 1
            raise _sign_error(SignAPIError.ErrorReason.SIGN_NOT_200, 500)

    class _Gate:
        async def acquire(self, priority=False):
            return None

    sleeps = []

    async def _sleep(delay):
        sleeps.append(delay)
        if len(sleeps) >= 3:
            listener._stopped = True

    resolver = _Resolver()
    listener = C.OpponentRoomListener(
        "rina__0910", "123", resolver, _Gate(), None, retry_seconds=5, retry_max=8
    )
    with caplog.at_level("WARNING", logger="tictok.collector"):
        with mock.patch.object(C.asyncio, "sleep", _sleep):
            await listener._run()

    assert resolver.calls == 3
    # 間隔は失敗のたびに伸ばし、上限で頭打ちにする。
    assert sleeps == [5, 10, 15]
    records = [r for r in caplog.records if r.event == "collector.opponent_listener_sign_unavailable"]
    assert records[0].ctx["retry_in_seconds"] == 5
    assert "繋ぎ直します" in records[0].getMessage()


@pytest.mark.asyncio
async def test_peer_listener_gives_up_after_the_consecutive_failure_cap(caplog):
    """相手が配信を終えた室は何度撃っても通らない。撃ち続けず、諦めたことを名乗る。"""
    class _Resolver:
        def __init__(self):
            self.calls = 0

        async def resolve(self, _handle):
            self.calls += 1
            raise RuntimeError("boom")

    class _Gate:
        async def acquire(self, priority=False):
            return None

    async def _sleep(_delay):
        return None

    resolver = _Resolver()
    listener = C.OpponentRoomListener(
        "rina__0910", "123", resolver, _Gate(), None, retry_seconds=1, retry_max=4
    )
    with caplog.at_level("WARNING", logger="tictok.collector"):
        with mock.patch.object(C.asyncio, "sleep", _sleep):
            await listener._run()
    assert resolver.calls == 4
    gave_up = [r for r in caplog.records if r.event == "collector.opponent_listener_gave_up"]
    assert len(gave_up) == 1
    assert gave_up[0].ctx["attempts"] == 4


@pytest.mark.asyncio
async def test_peer_listener_stops_even_when_reconnects_keep_succeeding():
    """繋がるたびに連続失敗は数え直すので、「繋がっては即切れる」相手はそれだけでは
    止まらない。総試行数の背板で止める。"""
    class _Gate:
        async def acquire(self, priority=False):
            raise AssertionError("room_idが判っているのでgateは通らない")

    class _Client:
        def __init__(self, unique_id, seen=None):
            pass

        def add_listener(self, *_args):
            return None

        async def connect(self, room_id, **_kwargs):
            # 繋がった直後に切れる相手。attached_atが立つので連続失敗は0のまま。
            listener.attached_at = 1.0

    async def _sleep(_delay):
        return None

    listener = C.OpponentRoomListener(
        "rina__0910", "123", None, _Gate(), None, room_id="7777",
        retry_seconds=1, retry_max=4,
    )
    with mock.patch.object(C, "DedupTikTokLiveClient", _Client):
        with mock.patch.object(C.asyncio, "sleep", _sleep):
            await listener._run()
    assert listener.attempts == C._PEER_ROOM_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_peer_listener_skips_the_resolver_when_the_room_id_is_known():
    """コラボ相手のroom_idはLinkLayerが名乗る。resolverはPlaywrightのpageを開き、全監視の
    live検出と同じlockを握るので、判っている相手には通さない。"""
    class _Resolver:
        async def resolve(self, _handle):
            raise AssertionError("resolverを通してはいけない")

    class _Gate:
        async def acquire(self, priority=False):
            raise AssertionError("probe gateを通してはいけない")

    connected = {}

    class _Client:
        def __init__(self, unique_id, seen=None):
            connected["handle"] = unique_id

        def add_listener(self, *_args):
            return None

        async def connect(self, room_id, **_kwargs):
            connected["room_id"] = room_id

    listener = C.OpponentRoomListener(
        "rina__0910", "123", _Resolver(), _Gate(), None, room_id="7777"
    )
    with mock.patch.object(C, "DedupTikTokLiveClient", _Client):
        await listener._run()
    assert connected == {"handle": "rina__0910", "room_id": 7777}
    assert listener.attempts == 1


def _sign_response(status=500, body="", headers=None):
    import httpx
    return httpx.Response(
        status_code=status, headers=headers or {}, text=body,
        request=httpx.Request("GET", "https://tiktok.eulerstream.com/webcast/fetch/"),
    )


def test_sign_outage_keeps_the_server_response_for_diagnosis():
    """500の中身を捨てない。これまでは status だけを残していたので、121件の5xxが
    どれも「500だった」以外に何も判らないまま積み上がっていた。"""
    from TikTokLive.client.errors import SignAPIError

    response = _sign_response(
        500, body='{"message":"Room is not live"}',
        headers={"X-Log-Code": "SIGN_FAIL_9", "X-Agent-Id": "agent-7"},
    )
    exc = SignAPIError(SignAPIError.ErrorReason.SIGN_NOT_200, "boom", response=response)
    ctx = C.sign_server_outage(exc)["ctx"]
    assert ctx["sign_status"] == 500
    assert ctx["sign_body"] == '{"message":"Room is not live"}'
    assert ctx["sign_log_code"] == "SIGN_FAIL_9"
    assert ctx["sign_agent_id"] == "agent-7"
    # keyed/anonymousのどちらで撃った結果かは、5xxを読むときの前提そのもの。
    assert "sign_key" in ctx


def test_sign_outage_truncates_a_long_body():
    from TikTokLive.client.errors import SignAPIError

    exc = SignAPIError(SignAPIError.ErrorReason.SIGN_NOT_200, "boom",
                       response=_sign_response(503, body="x" * 5000))
    ctx = C.sign_server_outage(exc)["ctx"]
    assert len(ctx["sign_body"]) == C._SIGN_BODY_LOG_CHARS
    assert ctx["sign_body_chars"] == 5000


def test_sign_rate_limit_reports_the_wait_the_server_asked_for():
    """利用上限は「こちらが撃ちすぎた」合図。指定された待ち時間を無視して自分の間隔で
    撃ち直すと、上限を押し広げることになる。"""
    from TikTokLive.client.errors import SignatureRateLimitError

    response = _sign_response(
        429, body='{"message":"rate limited"}',
        headers={"RateLimit-Remaining": "42", "RateLimit-Limit": "60",
                 "RateLimit-Reset": "1787753999"},
    )
    exc = SignatureRateLimitError("rate limited", "wait %s", response=response)
    outage = C.sign_server_outage(exc)
    assert outage["retry_after"] == 42
    assert outage["ctx"]["sign_rate_limit"] == "60"
    assert outage["ctx"]["sign_rate_remaining"] == "42"


@pytest.mark.asyncio
async def test_peer_listener_waits_as_long_as_the_sign_server_asked():
    from TikTokLive.client.errors import SignatureRateLimitError

    class _Resolver:
        async def resolve(self, _handle):
            raise SignatureRateLimitError(
                "rate limited", "wait %s",
                response=_sign_response(429, body="{}",
                                        headers={"RateLimit-Remaining": "90"}),
            )

    class _Gate:
        async def acquire(self, priority=False):
            return None

    sleeps = []

    async def _sleep(delay):
        sleeps.append(delay)
        listener._stopped = True

    listener = C.OpponentRoomListener(
        "rina__0910", "123", _Resolver(), _Gate(), None, retry_seconds=5, retry_max=8
    )
    with mock.patch.object(C.asyncio, "sleep", _sleep):
        await listener._run()
    # こちらの既定(5秒)ではなく、sign serverが言った90秒を待つ。
    assert sleeps == [90]


# ---------------- 相手Room listenerの寿命 ----------------


class _FakeListener:
    """OpponentRoomListenerの代役。start/stopの回数だけ数える。"""

    started = []

    def __init__(self, handle, host_id, resolver, probe_gate, on_gift,
                 room_id="", retry_seconds=0, retry_max=1, dedup_window=0):
        self._handle = handle
        self.host_id = str(host_id)
        self.room_id = room_id
        self.retry_seconds = retry_seconds
        self.retry_max = retry_max
        self.stopped = False
        self.attached_at = None
        self.exhausted = False

    @property
    def handle(self):
        return self._handle

    async def start(self):
        _FakeListener.started.append(self)

    async def stop(self):
        self.stopped = True

    def coverage(self):
        return {"handle": self._handle, "attached_at": self.attached_at,
                "attempts": 1, "error": "" if self.attached_at else "boom"}


def _peer_collector(collector, monkeypatch, **settings):
    values = {"monitor_opponent_rooms": 1, "opponent_room_keep_seconds": 180,
              "opponent_room_retry_seconds": 15, "opponent_room_retry_max": 8,
              "message_dedup_window": 7200}
    values.update(settings)
    monkeypatch.setattr(collector, "_settings", FakeSettings(**values))
    monkeypatch.setattr(collector, "_resolver", object())
    monkeypatch.setattr(C, "OpponentRoomListener", _FakeListener)
    _FakeListener.started = []
    return collector


def _battle_rec(battle_id, *, action=None, hosts=()):
    parts = {"own": {"user_id": "own", "unique_id": "me", "is_own": True, "side": "own"}}
    for host_id, handle, side in hosts:
        parts[host_id] = {"user_id": host_id, "unique_id": handle, "is_own": False, "side": side}
    return {"battle_id": battle_id, "action": action, "aborted": False,
            "participants": parts, "contributions": {}, "coin_coverage": {},
            "start_time": 1000.0}


@pytest.mark.asyncio
async def test_peer_listener_survives_between_consecutive_battles(collector, monkeypatch):
    """コラボ中は同じ相手と連戦する。PKごとに切ると、実測で延べ接続の55.1%(1,617本)が
    ただの張り直しになる。前のPKの終了から猶予の内は保つ。"""
    _peer_collector(collector, monkeypatch)
    collector._battles[1] = _battle_rec(1, hosts=[("h2", "rival", "opp")])
    await collector._sync_peer_listeners()
    first = collector._peer_listeners["h2"]

    # PKが終わった: 猶予の内なので切らない。
    collector._battles[1]["action"] = C.BATTLE_ACTION_FINISH
    collector._peer_battle_end["h2"] = time.time()
    await collector._sync_peer_listeners()
    assert collector._peer_listeners["h2"] is first
    assert not first.stopped

    # 次のPKでも同じlistenerのまま(張り直さない)。
    collector._battles[2] = _battle_rec(2, hosts=[("h2", "rival", "opp")])
    await collector._sync_peer_listeners()
    assert collector._peer_listeners["h2"] is first
    assert len(_FakeListener.started) == 1


@pytest.mark.asyncio
async def test_peer_listener_is_dropped_once_the_grace_is_over(collector, monkeypatch):
    _peer_collector(collector, monkeypatch, opponent_room_keep_seconds=60)
    collector._battles[1] = _battle_rec(1, hosts=[("h2", "rival", "opp")])
    await collector._sync_peer_listeners()
    listener = collector._peer_listeners["h2"]

    collector._battles[1]["action"] = C.BATTLE_ACTION_FINISH
    collector._peer_battle_end["h2"] = time.time() - 61
    await collector._sync_peer_listeners()
    assert "h2" not in collector._peer_listeners
    assert listener.stopped


@pytest.mark.asyncio
async def test_peer_listener_covers_teammates_and_uses_the_known_room_id(collector, monkeypatch):
    """味方の実弾も味方のRoomにしか流れないので、取りに行く先は陣営で変わらない。
    room_idが判っていればresolver(Playwright、live検出とlockを共有)を通さない。"""
    _peer_collector(collector, monkeypatch)
    collector._peer_rooms["mate"] = "7777"
    collector._battles[1] = _battle_rec(
        1, hosts=[("mate", "buddy", "own"), ("h2", "rival", "opp")])
    await collector._sync_peer_listeners()
    assert set(collector._peer_listeners) == {"mate", "h2"}
    assert collector._peer_listeners["mate"].room_id == "7777"
    assert collector._peer_listeners["h2"].room_id == ""
    assert collector._peer_listeners["h2"].retry_seconds == 15


@pytest.mark.asyncio
async def test_peer_listeners_are_dropped_when_the_setting_is_off(collector, monkeypatch):
    _peer_collector(collector, monkeypatch)
    collector._battles[1] = _battle_rec(1, hosts=[("h2", "rival", "opp")])
    await collector._sync_peer_listeners()
    listener = collector._peer_listeners["h2"]
    monkeypatch.setattr(collector, "_settings", FakeSettings(
        monitor_opponent_rooms=0, opponent_room_keep_seconds=180,
        opponent_room_retry_seconds=15, opponent_room_retry_max=8))
    await collector._sync_peer_listeners()
    assert collector._peer_listeners == {}
    assert listener.stopped


@pytest.mark.asyncio
async def test_exhausted_peer_is_only_retried_when_a_new_battle_starts(collector, monkeypatch):
    """撃ち切った相手を撃ち直し続けない。ただし次のPKが始まった時だけは作り直す — その
    相手が戦えている以上、室は戻っている。作り直しはPK1戦につき相手1人1本まで。"""
    _peer_collector(collector, monkeypatch)
    collector._battles[1] = _battle_rec(1, hosts=[("h2", "rival", "opp")])
    await collector._sync_peer_listeners()
    dead = collector._peer_listeners["h2"]
    dead.exhausted = True

    # 普段のsync(コラボの顔ぶれ変化など)では撃ち直さない。
    await collector._sync_peer_listeners()
    assert collector._peer_listeners["h2"] is dead
    assert len(_FakeListener.started) == 1

    # 落ちた本を畳んだ後も、PKが始まるまでは張り直さない。
    await collector._stop_peer_listener("h2")
    await collector._sync_peer_listeners()
    assert "h2" not in collector._peer_listeners
    assert len(_FakeListener.started) == 1

    # 次のPKの開始で1本だけ作り直す。
    await collector._sync_peer_listeners(restart_exhausted=True)
    assert collector._peer_listeners["h2"] is not dead
    assert len(_FakeListener.started) == 2


@pytest.mark.asyncio
async def test_coin_coverage_records_who_could_not_be_reached(collector, monkeypatch):
    """繋げなかった相手の実弾は後から取り戻せない(armiesはコインを持たない)。素性を
    残さないと欠測が「実弾0」として読まれる。"""
    _peer_collector(collector, monkeypatch)
    rec = _battle_rec(1, hosts=[("h2", "rival", "opp"), ("h3", "other", "opp")])
    collector._battles[1] = rec
    await collector._sync_peer_listeners()
    collector._peer_listeners["h2"].attached_at = 1000.0
    collector._record_coin_coverage(rec)
    assert rec["coin_coverage"]["h2"]["attached_at"] == 1000.0
    assert rec["coin_coverage"]["h3"]["attached_at"] is None
    assert rec["coin_coverage"]["h3"]["error"] == "boom"
    # 自hostは自室で拾えているので素性を持たない。
    assert "own" not in rec["coin_coverage"]


# ---------------- ProbeGate ----------------


def test_probe_gate_spacing_respects_floor_cap_and_monitor_count():
    counts = {"n": 1}
    settings = FakeSettings(live_check_interval=60, live_check_max_per_min=2.0)
    gate = C.ProbeGate(settings, lambda: counts["n"])
    # cap(60/2=30s)が interval/count(60s)より小さくても、遅い方を採る。
    assert gate._spacing() == 60.0
    counts["n"] = 4
    assert gate._spacing() == 30.0  # interval/count=15 だが cap が効く

    fast = C.ProbeGate(
        FakeSettings(live_check_interval=2, live_check_max_per_min=600.0), lambda: 100
    )
    assert fast._spacing() == C.LIVE_CHECK_MIN_PROBE_SPACING


def test_probe_gate_spacing_never_divides_by_a_zero_monitor_count():
    gate = C.ProbeGate(FakeSettings(live_check_interval=60, live_check_max_per_min=600.0), lambda: 0)
    assert gate._spacing() == 60.0


# ---------------- battle prompts ----------------


def test_prompt_record_and_value_keep_raw_values_without_interpretation():
    prompt = SimpleNamespace(
        prompt_key="pk_multi",
        prompt_elements=[
            SimpleNamespace(prompt_field_key="multi", prompt_field_value="3"),
            SimpleNamespace(prompt_field_key="", prompt_field_value="ignored"),
        ],
    )
    assert C.TikTokCollector._prompt_value(prompt, "multi") == "3"
    assert C.TikTokCollector._prompt_value(prompt, "sum") == ""
    assert C.TikTokCollector._prompt_record(prompt, "task") == {
        "slot": "task", "key": "pk_multi", "fields": {"multi": "3"},
    }
    # prompt_key が無いものは記録しない(文言を復元できない)。
    assert C.TikTokCollector._prompt_record(SimpleNamespace(prompt_key=""), "task") is None


def test_mission_prompts_collect_previews_in_order_then_the_fixed_slots():
    def mk(key):
        return SimpleNamespace(prompt_key=key, prompt_elements=[])

    cfg = SimpleNamespace(
        preview_period_config=[
            SimpleNamespace(promot=mk("p0"), duration=5),
            SimpleNamespace(promot=SimpleNamespace(prompt_key=""), duration=9),
            SimpleNamespace(promot=mk("p2"), duration=7),
        ]
    )
    task = SimpleNamespace(task_static_prompt=mk("t"), click_toast_prompt=None)
    reward = SimpleNamespace(reward_prapare_prompt=None, rewarding_prompt=mk("r"))
    prompts = C.TikTokCollector._mission_prompts(cfg, task, reward)
    assert [p["slot"] for p in prompts] == ["preview0", "preview2", "task", "rewarding"]
    assert prompts[0]["duration"] == 5 and prompts[1]["duration"] == 7


# ---------------- glove (critical strike) ----------------


def test_glove_consume_delta_prefers_an_exact_match_then_subtracts_from_a_compound():
    collector_deltas = {1: [[100.0, 50], [100.0, 30]]}
    gate = C.TikTokCollector.__new__(C.TikTokCollector)
    gate._glove_deltas = collector_deltas
    assert gate._glove_consume_delta(1, 100.0, 30) is True
    assert collector_deltas[1] == [[100.0, 50], [100.0, 0]]
    # 完全一致が無ければ大きいdeltaから差し引く(合算payload)。
    assert gate._glove_consume_delta(1, 100.0, 20) is True
    assert collector_deltas[1][0][1] == 30
    # 窓外のdeltaには手を出さない。
    assert gate._glove_consume_delta(1, 100.0 + C.GLOVE_MATCH_AFTER_SEC + 1, 30) is False
    assert gate._glove_consume_delta(2, 100.0, 30) is False


def test_glove_multiplier_is_one_outside_bonus_time_and_none_when_unresolvable():
    gate = C.TikTokCollector.__new__(C.TikTokCollector)
    rec = {"bonus_missions": [
        {"reward_start_ts": 1000, "reward_duration": 60, "multiplier": 3, "achieved": True},
    ]}
    assert gate._glove_multiplier_at(rec, 1030) == 3
    assert gate._glove_multiplier_at(rec, 999) == 1
    assert gate._glove_multiplier_at(rec, 1061) == 1
    assert gate._glove_multiplier_at({"bonus_missions": []}, 1030) == 1
    # reward期間中なのに未達成/倍率不明は「判定不能」であって1ではない。
    unresolved = {"bonus_missions": [
        {"reward_start_ts": 1000, "reward_duration": 60, "multiplier": 3, "achieved": False},
    ]}
    assert gate._glove_multiplier_at(unresolved, 1030) is None


def test_record_glove_candidate_only_accepts_own_window_gifts_and_dedups_nothing_free(collector):
    rec = collector._battle_record(11)
    rec["glove_windows"] = [
        {"start": 1000, "end": 1030, "target_host_id": "own", "own": True, "multiple": 5},
    ]
    assert collector._record_glove_candidate(1, 10, 3, 1005.4) is True
    ev = rec["glove_events"][-1]
    assert ev["total"] == 30 and ev["crit"] is None and ev["mult"] is None
    assert collector._glove_pending[11][-1]["multiple"] == 5

    # 窓外 / 単価0 / count<=0 は候補にしない。
    assert collector._record_glove_candidate(1, 10, 3, 1031) is False
    assert collector._record_glove_candidate(1, 0, 3, 1005) is False
    assert collector._record_glove_candidate(1, 10, 0, 1005) is False


def test_record_glove_candidate_ignores_aborted_battles_and_opponent_windows(collector):
    aborted = collector._battle_record(21)
    aborted["aborted"] = True
    aborted["glove_windows"] = [
        {"start": 1000, "end": 1030, "target_host_id": "own", "own": True, "multiple": 5}
    ]
    opponent = collector._battle_record(22)
    opponent["glove_windows"] = [
        {"start": 1000, "end": 1030, "target_host_id": "opp", "own": False, "multiple": 5}
    ]
    assert collector._record_glove_candidate(1, 10, 1, 1005) is False
    assert collector._glove_pending == {}


def test_capture_glove_window_dedups_repeated_cards(collector):
    collector._owner_id = "999"
    info = SimpleNamespace(
        to_anchor_id_str="999", effect_time_sec=2000, effect_last_duration=30,
        multiple=0, critical_strike_rate_low=10, critical_strike_rate_high=20,
    )
    event = SimpleNamespace(
        msg_type=SimpleNamespace(name="MSG_TYPE_USE_CRITICAL_STRIKE_CARD"),
        use_critical_strike_card=SimpleNamespace(card_info=info),
        battle_id=31,
    )
    collector._capture_glove_window(event)
    collector._capture_glove_window(event)
    windows = collector._battle_record(31)["glove_windows"]
    assert len(windows) == 1
    assert windows[0]["own"] is True
    assert windows[0]["end"] == 2030
    # multiple が0で届いたら既定倍率へ倒す(0倍にはしない)。
    assert windows[0]["multiple"] == C.GLOVE_MULTIPLE


def test_capture_glove_window_ignores_other_card_types_and_incomplete_info(collector):
    collector._owner_id = "999"
    other = SimpleNamespace(msg_type=SimpleNamespace(name="MSG_TYPE_OTHER"), battle_id=41)
    collector._capture_glove_window(other)
    assert 41 not in collector._battles

    no_duration = SimpleNamespace(
        msg_type=SimpleNamespace(name="CRITICAL_STRIKE"),
        use_critical_strike_card=SimpleNamespace(
            card_info=SimpleNamespace(
                to_anchor_id_str="999", effect_time_sec=2000, effect_last_duration=0
            )
        ),
        battle_id=42,
    )
    collector._capture_glove_window(no_duration)
    assert collector._battle_record(42)["glove_windows"] == []


def test_glove_own_host_score_takes_the_personal_value_from_team_armies(collector):
    collector._owner_id = "999"
    event = SimpleNamespace(
        armies={},
        team_armies=[
            SimpleNamespace(team_users=[
                SimpleNamespace(user_id_str="999", score=120),
                SimpleNamespace(user_id_str="888", score=900),
            ])
        ],
    )
    assert collector._glove_own_host_score(event) == 120

    personal = SimpleNamespace(
        armies={"999": SimpleNamespace(host_score=77, anchor_id_str="999")}, team_armies=[]
    )
    assert collector._glove_own_host_score(personal) == 77
    assert collector._glove_own_host_score(SimpleNamespace(armies={}, team_armies=[])) is None


def _own_armies_event(battle_id, score, create_time=None):
    event = SimpleNamespace(
        battle_id=battle_id,
        armies={"999": SimpleNamespace(host_score=score, anchor_id_str="999")},
        team_armies=[],
    )
    if create_time is not None:
        event.base_message = SimpleNamespace(create_time=create_time)
    return event


def _own_glove_window(collector, battle_id):
    collector._owner_id = "999"
    rec = collector._battle_record(battle_id)
    rec["glove_windows"] = [
        {"start": 1000, "end": 1030, "target_host_id": "999", "own": True, "multiple": 5},
    ]
    return rec


def test_glove_crit_matches_on_the_server_clock_not_the_receiver_clock(collector):
    # gift時刻(create_time)は server epoch秒。armies側を受信側の time.time() で積むと
    # 数秒どころか年単位でずれ、正しいdeltaが突合窓の外へ落ちてcritが全件Noneになる。
    rec = _own_glove_window(collector, 51)
    assert collector._record_glove_candidate(7, 100, 1, 1005) is True
    ev = rec["glove_events"][-1]
    collector._glove_prev_score[51] = 200
    # 窓倍率5 x 単価100 = 500 の跳ね(= crit)。armiesのcreate_timeもserver時計。
    collector._resolve_glove_crits(rec, _own_armies_event(51, 700, create_time=1006))
    assert ev["crit"] is True
    assert ev["mult"] == 5
    assert ev["score_delta"] == 500
    assert ev["method"] == C.GLOVE_METHOD_DELTA
    assert collector._glove_deltas[51] == [[1006, 0]]


def test_glove_delta_without_a_server_create_time_is_dropped_not_backfilled(collector):
    # create_timeが無いarmiesは軸に載せられない。受信側時計へFallbackすると窓が
    # ずれて偽critの母集団になるため、deltaは捨てて判定不能のまま残す。
    rec = _own_glove_window(collector, 52)
    assert collector._record_glove_candidate(7, 100, 1, 1005) is True
    ev = rec["glove_events"][-1]
    collector._glove_prev_score[52] = 200
    collector._resolve_glove_crits(rec, _own_armies_event(52, 700))
    assert collector._glove_deltas.get(52, []) == []
    assert ev["crit"] is None and ev["score_delta"] is None
    # 基準scoreだけは進める(次のdeltaが2回分の合算になるのを避ける)。
    assert collector._glove_prev_score[52] == 700
    # pendingは残し、server時計の読めるarmiesが来たら再試行する。
    assert len(collector._glove_pending[52]) == 1
    assert collector._glove_clock_warned is True


def test_glove_pools_are_pruned_even_when_the_armies_clock_is_missing(collector):
    """server時計の読めないarmiesでも刈り込みは続ける。判定できないからと即returnすると、
    gift側だけcreate_timeを持つ配信でpool(delta/attr/窓外gift)が際限なく伸びる。"""
    rec = _own_glove_window(collector, 54)
    horizon_out = 1000.0
    fresh = horizon_out + 10_000.0
    collector._glove_deltas[54] = [[horizon_out, 100], [fresh, 200]]
    collector._glove_attr[54] = [{"t": horizon_out, "gid": 1, "delta": 1,
                                  "flag": False, "used": False},
                                 {"t": fresh, "gid": 2, "delta": 2,
                                  "flag": False, "used": False}]
    collector._glove_recent_gifts[:] = [[horizon_out, 10], [fresh, 20]]
    # create_timeを持たないarmies。判定は走らないが古いentryは落ちる。
    collector._resolve_glove_crits(rec, _own_armies_event(54, None))
    assert collector._glove_deltas[54] == [[fresh, 200]]
    assert [e["gid"] for e in collector._glove_attr[54]] == [2]
    assert collector._glove_recent_gifts == [[fresh, 20]]


def test_glove_gift_without_a_server_create_time_is_not_timestamped_locally(collector):
    import time as _time

    rec = collector._battle_record(53)
    collector._owner_id = "999"
    # 受信側時計なら必ず窓中に入る窓。create_timeへFallbackしていると候補になってしまう。
    now = _time.time()
    rec["glove_windows"] = [
        {"start": int(now) - 10, "end": int(now) + 600, "target_host_id": "999",
         "own": True, "multiple": 5},
    ]
    assert collector._record_glove_candidate(7, 10, 3, None) is False
    assert rec["glove_events"] == []
    assert collector._glove_pending == {}
    collector._record_glove_offwindow_gift(10, 3, None)
    assert collector._glove_recent_gifts == []


def test_glove_event_version_is_stamped_from_the_shared_constant(collector):
    rec = _own_glove_window(collector, 54)
    assert collector._record_glove_candidate(7, 100, 1, 1005) is True
    assert rec["glove_events"][-1]["v"] == C.GLOVE_EVENT_VERSION


# ---------------- battle score sampling ----------------


def test_score_sample_window_tightens_only_near_the_end(collector):
    collector._settings = FakeSettings(
        battle_score_sample_seconds=10,
        battle_score_endgame_seconds=20,
        battle_score_endgame_sample_seconds=2,
    )
    rec = {"end_time": 1000.0}
    assert collector._score_sample_window(rec, 900.0) == 10
    assert collector._score_sample_window(rec, 985.0) == 2
    # 終了時刻を過ぎても確定scoreが届くので細かいまま。
    assert collector._score_sample_window(rec, 1100.0) == 2
    # end_timeが取れなかったbattleは通常間隔のまま(推定しない)。
    assert collector._score_sample_window({"end_time": None}, 985.0) == 10


# ---------------- LinkMic roster ----------------


@pytest.mark.asyncio
async def test_link_layer_survives_a_broken_payload(collector):
    """rosterが読めないeventで例外を上へ投げないこと(収集本流を止めない)。判定そのものは
    tests/test_collab_rule.py が持つ。"""

    class Broken:
        @property
        def linked_list(self):
            raise RuntimeError("bad payload")

    event = SimpleNamespace(
        channel_id="ch1",
        group_change_content=SimpleNamespace(
            group_user=SimpleNamespace(
                user=[SimpleNamespace(
                    channel_id="ch1", status="GROUP_STATUS_LINKED", all_user=Broken())]
            )
        ),
    )

    await collector._on_link_layer(event)

    assert collector._collab_open == {}
    assert collector._collab_windows == []


# ---------------- CollectorManager ----------------


@pytest.fixture
def manager(tmp_db, monkeypatch):
    from tictok.collect import manager as M
    from tictok.core.settings import Settings

    monkeypatch.setattr(M, "BrowserLiveResolver", lambda settings: SimpleNamespace())
    sent = []

    async def broadcast(message):
        sent.append(message)

    mgr = M.CollectorManager(broadcast, tmp_db, Settings(tmp_db))
    return mgr, sent


@pytest.mark.parametrize("op", ["stop", "remove", "start_recording", "stop_recording"])
async def test_manager_rejects_operations_on_an_unknown_target(manager, op):
    mgr, _sent = manager
    with pytest.raises(KeyError):
        await getattr(mgr, op)("nobody")


async def test_manager_probing_count_excludes_connected_collectors(manager):
    mgr, _sent = manager
    mgr._collectors = {
        "a": SimpleNamespace(state=C.STATE_WAITING, session_id=1),
        "b": SimpleNamespace(state=C.STATE_CONNECTED, session_id=2),
        "c": SimpleNamespace(state=C.STATE_RESTRICTED, session_id=None),
        "d": SimpleNamespace(state=C.STATE_IDLE, session_id=None),
    }
    assert mgr._probing_count() == 2
    assert mgr.active_session_ids() == {1, 2}
    assert mgr.get("zzz") is None


async def test_manager_broadcast_tags_every_message_with_its_monitor(manager):
    mgr, sent = manager
    scoped = mgr._make_broadcast("streamer_a")
    await scoped({"type": "event", "data": {"kind": "comment"}})
    assert sent == [{"type": "event", "data": {"kind": "comment"}, "monitor": "streamer_a"}]


async def test_manager_restore_keeps_going_after_one_target_fails(manager, monkeypatch):
    mgr, _sent = manager
    mgr._storage.add_monitored_target("good", True)
    mgr._storage.add_monitored_target("bad", False)
    started = []

    async def fake_start(unique_id, record_video=None):
        if unique_id == "bad":
            raise RuntimeError("boom")
        started.append((unique_id, record_video))

    monkeypatch.setattr(mgr, "start", fake_start)
    await mgr.restore()
    assert started == [("good", 1)]


# ===== 宝箱(Envelope) / Portal の取り込み =====
# 実sample(samples/EnvelopeEvent.jsonl, PortalEvent.jsonl)で確認した shape を固定する。


class _Obj:
    """protoのようにattribute accessできる薄いobject。実eventはproto messageで、
    dictではなくgetattrで読むため、testも同じ読み方にする。"""

    def __init__(self, **fields):
        for key, value in fields.items():
            setattr(self, key, value)


def _envelope_event(**info):
    return _Obj(envelope_info=_Obj(**info), display="ENVELOPE_DISPLAY_NEW",
                base_message=None)


def _portal_event(**info):
    return _Obj(portal_info=_Obj(**info), portal_display=2, base_message=None)


@pytest.fixture
def envelope_collector(collector):
    collector.session_id = 1
    return collector


def test_treasure_box_payload_is_captured(envelope_collector):
    """実測(business_type=1): diamond_count=20 / people_count=16 / 送信者。
    markerだけでは投下coinが残らないので、payloadを実測値のまま保存する。"""
    import asyncio

    asyncio.run(envelope_collector._on_envelope(_envelope_event(
        envelope_id="7661188576227855124", business_type=1, diamond_count=20,
        people_count=16, create_time="1783764415705", unpack_at=1783764595,
        send_user_id="7310859361970226178", send_user_name="wicha_3111",
    )))

    rows = envelope_collector._envelopes
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "envelope"
    assert (row["diamond_count"], row["people_count"]) == (20, 16)
    assert row["business_type"] == 1
    assert row["sender_unique_id"] == "wicha_3111"
    assert row["envelope_id"] == "7661188576227855124"
    # msの文字列で届くcreate_timeが秒へ正規化されること。
    assert 1783764415 <= row["create_time"] <= 1783764416
    assert row["unpack_at"] == pytest.approx(1783764595)


def test_super_fan_box_has_no_diamond_count_and_is_not_zero_filled(envelope_collector):
    """実測(business_type=19): diamond_countが存在しない。0で埋めると
    「無料で配った」という観測していない事実になる。Noneのまま残すこと。"""
    import asyncio

    asyncio.run(envelope_collector._on_envelope(_envelope_event(
        envelope_id="1195152805380", business_type=19, people_count=1,
        create_time="1784220745989", unpack_at=1784220925,
        send_user_id="7577028547187065877", send_user_name="sinbakwk35k", skin_id=56,
    )))

    row = envelope_collector._envelopes[0]
    assert row["diamond_count"] is None
    assert row["people_count"] == 1
    # 送信者は配信者とは限らない(実測でこれは視聴者)。そのまま残す。
    assert row["sender_unique_id"] == "sinbakwk35k"
    assert row["data"]["skin_id"] == 56


def test_portal_send_arrives_as_an_envelope_with_business_type_4(envelope_collector):
    """実測: Portalの「送信」はEnvelopeEventで届く(business_type=4, 120 coin, 定員80)。
    PortalEventはPortalが閉じたときの別messageである。"""
    import asyncio

    asyncio.run(envelope_collector._on_envelope(_envelope_event(
        envelope_id="7661161260446092052", business_type=4, diamond_count=120,
        people_count=80, create_time="1783764873225", unpack_at=1783765172,
        send_user_id="7310859361970226178", send_user_name="wicha_3111",
    )))

    row = envelope_collector._envelopes[0]
    assert row["kind"] == "envelope"
    assert (row["business_type"], row["diamond_count"], row["people_count"]) == (4, 120, 80)


def test_portal_close_records_the_moved_count_and_no_source_room(envelope_collector):
    """実測: portal_infoはtrans_count(実移動人数)を運ぶ。移動「元」のroomを示すfieldは
    payloadのどこにも無いので、ここでも作らない。"""
    import asyncio

    asyncio.run(envelope_collector._on_portal(_portal_event(
        id="7661135713622936341", sender_id="7310859361970226178", trans_count=24,
    )))

    row = envelope_collector._envelopes[0]
    assert row["kind"] == "portal_closed"
    assert row["trans_count"] == 24
    assert row["sender_user_id"] == "7310859361970226178"
    # 流入元を示すfieldを勝手に作っていないこと。
    assert "source_room_id" not in row
    assert "from_unique_id" not in row
    assert row["diamond_count"] is None


def test_the_same_envelope_id_is_folded_and_hide_does_not_erase_the_measurement(
    envelope_collector
):
    """実測で同じenvelope_idがNEW(実測値あり)とHIDE(idと種別だけ)の2回届く。
    2件に数えず、かつHIDEが後から来ても実測値を消さないこと。"""
    import asyncio

    asyncio.run(envelope_collector._on_envelope(_envelope_event(
        envelope_id="7661188576227855124", business_type=1, diamond_count=20,
        people_count=16, send_user_id="7310859361970226178",
        send_user_name="wicha_3111",
    )))
    asyncio.run(envelope_collector._on_envelope(_envelope_event(
        envelope_id="7661188576227855124", business_type=1,
    )))

    assert len(envelope_collector._envelopes) == 1
    row = envelope_collector._envelopes[0]
    assert (row["diamond_count"], row["people_count"]) == (20, 16)


def test_hide_arriving_first_is_filled_in_by_the_later_measurement(envelope_collector):
    """順序が逆でも同じ結果になること(HIDEが先に届く回がある)。"""
    import asyncio

    asyncio.run(envelope_collector._on_envelope(_envelope_event(
        envelope_id="E1", business_type=1,
    )))
    asyncio.run(envelope_collector._on_envelope(_envelope_event(
        envelope_id="E1", business_type=1, diamond_count=20, people_count=16,
    )))

    assert len(envelope_collector._envelopes) == 1
    assert envelope_collector._envelopes[0]["diamond_count"] == 20


def test_marker_refractory_does_not_drop_the_payload(envelope_collector):
    """markerの不応期は残しつつ、payloadは1件ずつ残すこと。

    不応期は「1演出=1 mask onset」へ畳むためのもので窓としては正しいが、測定では
    1件ずつが別の支出であり、時間で畳むと投下coinの合計が失われる。
    """
    import asyncio

    for i in range(3):
        asyncio.run(envelope_collector._on_envelope(_envelope_event(
            envelope_id=f"E{i}", business_type=1, diamond_count=20, people_count=16,
        )))

    # markerは不応期で1本に畳まれる(既存の挙動を変えない)。
    envelope_markers = [m for m in envelope_collector._all_markers()
                        if m["kind"] == "envelope"]
    assert len(envelope_markers) == 1
    # 実測は3件とも残る。
    assert len(envelope_collector._envelopes) == 3
    assert sum(r["diamond_count"] for r in envelope_collector._envelopes) == 60


def test_envelope_without_info_is_not_recorded(envelope_collector):
    """envelope_infoを持たないeventで空行を作らない。"""
    import asyncio

    asyncio.run(envelope_collector._on_envelope(_Obj(envelope_info=None, display=None,
                                                     base_message=None)))
    assert envelope_collector._envelopes == []


def test_envelopes_round_trip_through_storage(tmp_db, make_session):
    """保存と読み出し。diamond_count=NULLがNULLのまま戻ること。"""
    session_id = make_session("alice")
    tmp_db.save_envelopes(session_id, [
        {"kind": "envelope", "envelope_id": "E1", "time": 100.0, "create_time": 99.0,
         "business_type": 1, "diamond_count": 20, "people_count": 16,
         "trans_count": None, "unpack_at": 200.0, "sender_user_id": "u1",
         "sender_unique_id": "wicha_3111", "data": {"display": "NEW"}},
        {"kind": "envelope", "envelope_id": "E2", "time": 110.0, "create_time": None,
         "business_type": 19, "diamond_count": None, "people_count": 1,
         "trans_count": None, "unpack_at": None, "sender_user_id": "u2",
         "sender_unique_id": "sinbakwk35k", "data": {}},
        {"kind": "portal_closed", "envelope_id": "P1", "time": 120.0,
         "create_time": None, "business_type": None, "diamond_count": None,
         "people_count": None, "trans_count": 24, "unpack_at": None,
         "sender_user_id": "u1", "sender_unique_id": None, "data": {}},
    ])

    rows = tmp_db.session_envelopes(session_id)
    assert [r["kind"] for r in rows] == ["envelope", "envelope", "portal_closed"]
    assert rows[0]["diamond_count"] == 20
    assert rows[0]["data"]["display"] == "NEW"
    assert rows[1]["diamond_count"] is None, "Super Fan Boxの欠落はNULLのまま"
    assert rows[2]["trans_count"] == 24


def test_save_envelopes_replaces_per_session(tmp_db, make_session):
    """battles/collab_windowsと同じ全置換。checkpointを繰り返しても増殖しないこと。"""
    session_id = make_session("alice")
    row = {"kind": "envelope", "envelope_id": "E1", "time": 100.0, "create_time": None,
           "business_type": 1, "diamond_count": 20, "people_count": 16,
           "trans_count": None, "unpack_at": None, "sender_user_id": None,
           "sender_unique_id": None, "data": {}}
    tmp_db.save_envelopes(session_id, [row])
    tmp_db.save_envelopes(session_id, [row])
    assert len(tmp_db.session_envelopes(session_id)) == 1


# ---------------- 録画確定時のcomment index ----------------


def _finalized_recorder(tmp_db, tmp_root, session_id, state="completed", started=1000.0,
                        ended=1600.0):
    """確定直後のRecorderを模したstub。collectorが読むfieldだけを持たせる。

    DB行もupdate_recording済み(=確定を書き戻した後)にしておく。indexはended_atでevent窓を
    切るので、書き戻す前に張ると次の録画のcommentまで巻き込む。"""
    path = tmp_root / "streamer" / "mp4" / "00001_streamer_20260101_120000.mp4"
    recording_id = tmp_db.create_recording(
        session_id, "streamer", str(path), path.name, "hd", started)
    tmp_db.update_recording(recording_id, state, str(path), path.name, ended, 1024,
                            None, ended - started)
    return SimpleNamespace(
        recording_id=recording_id, state=state, output_path=path, ended_at=ended,
        error=None, duration_seconds=ended - started, base=path.stem,
        snapshot=lambda: {"bytes": 1024},
    )


async def test_finalized_recording_indexes_its_comments(
        collector, tmp_db, tmp_root, make_session, event_builder):
    """確定した録画のcommentがその場でindexへ入ること。

    起動時のbackfillしか張る経路が無かった頃は、server稼働中に始まって終わった録画は
    次の再起動までcomment panelにも横断検索にも1件も出なかった。"""
    from tictok.search import indexer

    session_id = make_session("streamer", status="connected")
    recorder = _finalized_recorder(tmp_db, tmp_root, session_id)
    tmp_db.add_event(session_id, event_builder("comment", at=1030.0, comment="こんばんは"))
    tmp_db.add_event(session_id, event_builder("comment", at=1700.0, comment="録画の外"))

    await collector._index_recording_comments(recorder)

    rows = tmp_db.search_hits_for(recorder.recording_id, indexer.SOURCE_COMMENT)
    assert [(r["video_time"], r["body"]) for r in rows] == [(30.0, "こんばんは")]


async def test_finalized_recording_skips_the_index_when_the_material_failed(
        collector, tmp_db, tmp_root, make_session, event_builder):
    """failedの録画は張らない。起動時backfill(recordings_briefがcompleted/interruptedのみ)と
    同じ規則にしないと、commentが出る録画の条件が2つに分かれる。"""
    from tictok.search import indexer

    session_id = make_session("streamer", status="connected")
    recorder = _finalized_recorder(tmp_db, tmp_root, session_id, state="failed")
    tmp_db.add_event(session_id, event_builder("comment", at=1030.0, comment="こんばんは"))

    await collector._index_recording_comments(recorder)

    assert tmp_db.search_hits_for(recorder.recording_id, indexer.SOURCE_COMMENT) == []


async def test_index_failure_does_not_break_the_finalize_callback(
        collector, tmp_db, tmp_root, make_session, monkeypatch):
    """indexが落ちても確定処理は続ける。ここで送出すると通知も次の録画への再開も落ちる。"""
    async def boom(*args, **kwargs):
        raise OSError("timing.jsonが読めません")

    monkeypatch.setattr(C.indexer, "index_comments", boom)
    session_id = make_session("streamer", status="connected")
    collector.session_id = session_id
    recorder = _finalized_recorder(tmp_db, tmp_root, session_id)

    await collector._on_recording_finalized(recorder)

    assert tmp_db.get_recording(recorder.recording_id)["status"] == "completed"


async def test_finalize_callback_wires_the_comment_index(
        collector, tmp_db, tmp_root, make_session, event_builder):
    """確定callbackそのものがindexを張ること(呼び出しの結線が外れていないこと)。"""
    from tictok.search import indexer

    session_id = make_session("streamer", status="connected")
    collector.session_id = session_id
    recorder = _finalized_recorder(tmp_db, tmp_root, session_id)
    tmp_db.add_event(session_id, event_builder("comment", at=1100.0, comment="おつぽみ"))

    await collector._on_recording_finalized(recorder)

    rows = tmp_db.search_hits_for(recorder.recording_id, indexer.SOURCE_COMMENT)
    assert [r["body"] for r in rows] == ["おつぽみ"]


# ---------------- 焼き込みassetの先行取得への結線 ----------------


class _RecordingPrefetch:
    """AssetPrefetcherのうち、collectorが呼ぶ面だけを持つstub。"""

    def __init__(self):
        self.gift_icons = []
        self.avatars = []
        self.emotes = []

    def submit_gift_icon(self, gift_id, url):
        self.gift_icons.append((gift_id, url))

    def submit_avatar(self, user_key, url):
        self.avatars.append((user_key, url))

    def submit_emotes(self, raw):
        self.emotes.append(raw)


@pytest.mark.asyncio
async def test_recorded_event_queues_the_user_avatar_and_comment_emotes(collector):
    """_record は履歴に載る全event種が通る唯一の口で、そこがasset先行取得のhook。
    avatarとemoteのCDN URLは配信終了後403になるため、ここで積み損ねると焼き込みは
    頭文字円盤と透明な余白へ縮退し、後から取り直す手段が無い。"""
    prefetch = _RecordingPrefetch()
    collector._asset_prefetch = prefetch
    emotes = json.dumps([{"index": 0, "id": "700111", "url": "https://cdn.example/e.png"}])

    await collector._record("comment", {
        "user": {"unique_id": "viewer", "avatar": "https://cdn.example/a.png"},
        "comment": "こんばんは",
        "emotes": emotes,
    })

    assert prefetch.avatars == [("viewer", "https://cdn.example/a.png")]
    assert prefetch.emotes == [emotes]


@pytest.mark.asyncio
async def test_event_without_emotes_queues_nothing_for_emotes(collector):
    """emoteを持たないeventで空の要求を積まないこと(queueは有界で、席は有限)。"""
    prefetch = _RecordingPrefetch()
    collector._asset_prefetch = prefetch

    await collector._record("like", {"user": {"unique_id": "viewer", "avatar": ""}, "count": 1})

    assert prefetch.emotes == []
    assert prefetch.avatars == [("viewer", "")]


@pytest.mark.asyncio
async def test_gift_event_queues_the_icon_while_its_url_is_fresh(collector, monkeypatch):
    """gift iconはgift eventの側で積む(gift_idはそこにしか無い)。"""
    prefetch = _RecordingPrefetch()
    collector._asset_prefetch = prefetch

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(collector, "_record", _noop)

    await collector._on_gift(SimpleNamespace(
        user=ExtendedUser(username="handle"),
        gift=SimpleNamespace(name="rose", diamond_count=10,
                             image=ImageModel(m_urls=["https://cdn.example/rose.png"]), id=5827),
        repeat_count=1,
        streaking=False,
        base_message=SimpleNamespace(create_time=0),
    ))

    assert prefetch.gift_icons == [(5827, "https://cdn.example/rose.png")]


@pytest.mark.asyncio
async def test_collector_without_a_prefetcher_still_records_events(collector):
    """先行取得を無効にしたserverでも収集そのものは動く(assetが貯まらないだけ)。"""
    collector._asset_prefetch = None

    await collector._record("comment", {"user": {"unique_id": "viewer", "avatar": "u"},
                                        "comment": "やあ"})

    assert collector.stats["events_total"] == 1


# ---------------- コラボ(非BattleのLinkMic)窓 ----------------


def _link_event(channel_id, rooms, source=None):
    """LinkLayerEventのgroup_change_content形。roomsは (room_id, uid, status)。

    ``source`` はそのsnapshotを出した操作の名乗り(実payloadのfield)。退出系の値が
    入るとv4はrosterを読まない。"""
    return SimpleNamespace(
        channel_id=channel_id,
        source=source,
        group_change_content=C._sim_group_change(rooms),
    )


@pytest.mark.asyncio
async def test_collab_window_opens_on_link_and_closes_when_the_peer_leaves(collector, monkeypatch):
    """rosterが縮んだ時点で窓を閉じること。**v1はfinishが来るまで閉じず**、その間の
    ソロ時間を丸ごとコラボに数えていた(録画照合で窓の中の大半がソロ)。"""
    collector.room_id = 111
    collector._owner_id = "own"
    monkeypatch.setattr(collector, "_persist_progress", lambda: None)
    # 実時計だと2 eventが同じ刻に載って長さ0の窓になり、落ちる回が出る(実際に発生した)。
    clock = {"t": 1000.0}
    monkeypatch.setattr(C.time, "time", lambda: clock["t"])
    linked = [("111", "own", "GROUP_STATUS_LINKED"), ("222", "peer", "GROUP_STATUS_LINKED")]

    await collector._on_link_layer(_link_event("ch1", linked))
    assert len(collector._collab_open) == 1, "接続で窓が開く"
    assert collector._collab_windows == []

    clock["t"] += 300.0
    await collector._on_link_layer(_link_event("ch1", [("111", "own", "GROUP_STATUS_LINKED")]))
    assert collector._collab_open == {}, "相手が抜けたら閉じる"
    assert len(collector._collab_windows) == 1
    window = collector._collab_windows[0]
    assert window["version"] == C.COLLAB_WINDOW_VERSION
    assert window["peers"] == ["peer"]
    assert (window["start"], window["end"]) == (1000.0, 1300.0)


@pytest.mark.asyncio
async def test_collab_window_of_zero_length_is_dropped(collector, monkeypatch):
    """開いた瞬間に閉じた窓は残さない。回数だけが持ち上がる(既存のcollab窓の数え方と同じ)。"""
    collector.room_id = 111
    collector._owner_id = "own"
    monkeypatch.setattr(collector, "_persist_progress", lambda: None)
    monkeypatch.setattr(C.time, "time", lambda: 1000.0)

    await collector._on_link_layer(_link_event("ch1", [
        ("111", "own", "GROUP_STATUS_LINKED"),
        ("222", "peer", "GROUP_STATUS_LINKED"),
    ]))
    await collector._on_link_layer(_link_event("ch1", [("111", "own", "GROUP_STATUS_LINKED")]))

    assert collector._collab_open == {}
    assert collector._collab_windows == []


@pytest.mark.asyncio
async def test_collab_window_does_not_open_while_only_waiting(collector, monkeypatch):
    """自室がWAITINGの間は参加待ちで、まだ一緒に映っていない。ここで開くと、繋がる前の
    時間までコラボに入る。"""
    collector.room_id = 111
    collector._owner_id = "own"
    monkeypatch.setattr(collector, "_persist_progress", lambda: None)

    await collector._on_link_layer(_link_event("ch1", [
        ("111", "own", "GROUP_STATUS_WAITING"),
        ("222", "peer", "GROUP_STATUS_LINKED"),
    ]))

    assert collector._collab_open == {}
    assert collector._collab_windows == []


@pytest.mark.asyncio
async def test_collab_snapshot_names_the_current_peers_and_notifies_on_change(
    collector, monkeypatch
):
    """監視画面が「今この相手と繋がっている」を出すための口。保存形(peers)は窓の生涯の
    和集合なので、入れ替わりのあるコラボでは今の顔ぶれにならない ―― snapshotは現在の
    rosterを出すこと。stateを配るのは顔ぶれが変わった時だけ(LinkLayer eventは接続中ずっと
    届き続けるため、毎回配ると監視画面へsnapshotを撒き散らす)。"""
    collector.room_id = 111
    collector._owner_id = "own"
    monkeypatch.setattr(collector, "_persist_progress", lambda: None)
    notified = []

    async def _notify():
        notified.append(collector.collab_snapshot())

    monkeypatch.setattr(collector, "_notify_state", _notify)
    monkeypatch.setattr(C.time, "time", lambda: 1000.0)

    assert collector.snapshot()["collab"] == []

    await collector._on_link_layer(_link_event("ch1", [
        ("111", "own", "GROUP_STATUS_LINKED"),
        ("222", "peerA", "GROUP_STATUS_LINKED"),
    ]))
    assert collector.snapshot()["collab"] == [
        {"channel_id": "ch1", "start": 1000.0, "guests_max": 1, "peers": ["peerA"],
         # 身元を解決できていない相手はkeyごと出さない。空dictを置くと画面は
         # 「名前が空の相手」と読む。
         "peer_info": {}}
    ]
    assert len(notified) == 1

    # 同じ顔ぶれのsnapshotが繰り返し届いても配り直さない。
    await collector._on_link_layer(_link_event("ch1", [
        ("111", "own", "GROUP_STATUS_LINKED"),
        ("222", "peerA", "GROUP_STATUS_LINKED"),
    ]))
    assert len(notified) == 1

    # 相手が入れ替わったら、今の相手だけを名乗る(抜けたpeerAは残さない)。
    await collector._on_link_layer(_link_event("ch1", [
        ("111", "own", "GROUP_STATUS_LINKED"),
        ("333", "peerB", "GROUP_STATUS_LINKED"),
    ]))
    assert collector.snapshot()["collab"][0]["peers"] == ["peerB"]
    assert len(notified) == 2


class _PeerRoomClient:
    """room_infoだけを持つclientのstub。呼ばれたroom_idを記録する。"""

    def __init__(self, rooms):
        self._rooms = rooms
        self.calls = []
        self.web = SimpleNamespace(fetch_room_info=self._fetch)

    async def _fetch(self, room_id=None):
        self.calls.append(str(room_id))
        return self._rooms[str(room_id)]


def _owner_payload(user_id, nickname, display_id):
    return {"owner": {"id": user_id, "nickname": nickname, "display_id": display_id,
                      "avatar_larger": {"url_list": ["https://cdn/大.jpg"]},
                      "avatar_thumb": {"url_list": ["https://cdn/小.jpg"]}}}


@pytest.mark.asyncio
async def test_collab_peer_identity_comes_from_the_peer_room_info(collector, monkeypatch):
    """コラボ相手の表示名は相手のroom_idからroom_infoを引いて解決すること。LinkLayerは
    user_idとroom_idしか載せないので、これが唯一の経路である。解決はeventの処理を
    待たせず、結果はusers表へ残す(次のprocessが待たずに名前を出せる)。"""
    collector.room_id = 111
    collector._owner_id = "own"
    monkeypatch.setattr(collector, "_persist_progress", lambda: None)
    monkeypatch.setattr(C.time, "time", lambda: 1000.0)
    collector._client = _PeerRoomClient(
        {"222": _owner_payload("peerA", "こつぶ組", "kotsubu")})

    await collector._on_link_layer(_link_event("ch1", [
        ("111", "own", "GROUP_STATUS_LINKED"),
        ("222", "peerA", "GROUP_STATUS_LINKED"),
    ]))
    await asyncio.gather(*collector._peer_tasks)

    assert collector.snapshot()["collab"][0]["peer_info"] == {
        "peerA": {"nickname": "こつぶ組", "unique_id": "kotsubu",
                  "avatar": "https://cdn/大.jpg"},
    }
    assert collector._storage.peer_identities(["peerA"])["peerA"]["nickname"] == "こつぶ組"

    # 同じ相手のeventが続いても撃ち直さない(LinkLayerは接続中ずっと届き続ける)。
    await collector._on_link_layer(_link_event("ch1", [
        ("111", "own", "GROUP_STATUS_LINKED"),
        ("222", "peerA", "GROUP_STATUS_LINKED"),
    ]))
    await asyncio.gather(*collector._peer_tasks)
    assert collector._client.calls == ["222"]


@pytest.mark.asyncio
async def test_collab_peer_identity_is_dropped_when_the_room_owner_is_someone_else(
    collector, monkeypatch
):
    """引いた室の主が相手本人でなければ身元を採らない。採ると別人の名前をコラボ相手として
    出すことになる(IDのままの方がまだ正しい)。"""
    collector.room_id = 111
    collector._owner_id = "own"
    monkeypatch.setattr(collector, "_persist_progress", lambda: None)
    collector._client = _PeerRoomClient(
        {"222": _owner_payload("別人", "別の配信者", "other")})

    await collector._on_link_layer(_link_event("ch1", [
        ("111", "own", "GROUP_STATUS_LINKED"),
        ("222", "peerA", "GROUP_STATUS_LINKED"),
    ]))
    await asyncio.gather(*collector._peer_tasks)

    assert collector.snapshot()["collab"][0]["peer_info"] == {}
    assert collector._storage.peer_identities(["peerA"]) == {}


@pytest.mark.asyncio
async def test_collab_peer_identity_falls_silent_when_the_room_cannot_be_read(
    collector, monkeypatch
):
    """制限中/終了済みの室は引けない。名前が出ないだけで、収集も窓の開閉も止めないこと。"""
    collector.room_id = 111
    collector._owner_id = "own"
    monkeypatch.setattr(collector, "_persist_progress", lambda: None)

    async def _boom(room_id=None):
        raise RuntimeError("age restricted")

    collector._client = SimpleNamespace(web=SimpleNamespace(fetch_room_info=_boom))

    await collector._on_link_layer(_link_event("ch1", [
        ("111", "own", "GROUP_STATUS_LINKED"),
        ("222", "peerA", "GROUP_STATUS_LINKED"),
    ]))
    await asyncio.gather(*collector._peer_tasks)

    assert len(collector._collab_open) == 1, "窓は開いたまま"
    assert collector.snapshot()["collab"][0]["peer_info"] == {}


@pytest.mark.asyncio
async def test_open_collab_window_is_persisted_provisionally(collector, monkeypatch):
    """接続中の窓も暫定の終端つきで書く。session終了時に確定形へ置き換わる。

    以前は確定済みの窓しか書いていなかった。graceful終了なら
    ``_close_open_collab_windows`` が先に走るので漏れは無い前提だったが、serverの
    再起動・強制終了でその前提が崩れ、開いていた窓はメモリごと消えていた(実測で
    38 sessionのうち13 sessionが末尾の窓を失っていた)。"""
    collector.room_id = 111
    collector._owner_id = "own"
    monkeypatch.setattr(collector, "_persist_progress", lambda: None)
    clock = {"t": 1000.0}
    monkeypatch.setattr(C.time, "time", lambda: clock["t"])

    await collector._on_link_layer(_link_event("ch1", [
        ("111", "own", "GROUP_STATUS_LINKED"),
        ("222", "peer", "GROUP_STATUS_LINKED"),
    ]))
    assert collector._collab_open, "接続中の窓は状態としては持つ"

    clock["t"] = 1200.0
    provisional = collector._collab_windows_public()
    assert len(provisional) == 1, "落ちても残るよう、開いている窓も書く"
    assert provisional[0]["closed_by"] == "open", "終端が暫定であることを名乗る"
    assert (provisional[0]["start"], provisional[0]["end"]) == (1000.0, 1200.0)

    collector._close_open_collab_windows(1300.0)
    assert collector._collab_open == {}
    windows = collector._collab_windows_public()
    assert len(windows) == 1, "確定形が暫定形を置き換える(全置換で保存されるため)"
    window = windows[0]
    assert (window["start"], window["end"]) == (1000.0, 1300.0)
    assert window["closed_by"] == "session_end"
    assert window["version"] == C.COLLAB_WINDOW_VERSION


@pytest.mark.asyncio
async def test_leave_snapshot_does_not_open_a_collab_window(collector, monkeypatch):
    """退出操作で出たsnapshotのrosterは読まない(v4)。

    ``click_quick_leave_button`` 等のsnapshotは、抜ける本人をまだLINKEDのまま載せた
    **変化前のroster**である。v3はこれを「まだ繋がっている」と読み、コラボが終わった
    瞬間に窓を開いて次のsnapshotが届くまで(実測で最長1時間40分)ソロ時間をコラボに
    数えていた。録画47本の照合で、この署名の窓は14,230秒中22秒しか映像と一致しない。"""
    collector.room_id = 111
    collector._owner_id = "own"
    monkeypatch.setattr(collector, "_persist_progress", lambda: None)
    clock = {"t": 1000.0}
    monkeypatch.setattr(C.time, "time", lambda: clock["t"])
    linked = [("111", "own", "GROUP_STATUS_LINKED"), ("222", "peer", "GROUP_STATUS_LINKED")]

    await collector._on_link_layer(
        _link_event("ch1", linked, source="click_quick_leave_button"))
    assert collector._collab_open == {}, "退出のsnapshotでは窓を開かない"

    # 通常のsnapshotなら開く。退出系だけを外していることの対照。
    await collector._on_link_layer(
        _link_event("ch1", linked, source="SOURCE_TYPE_FRIEND_LIST[REPLY_STATUS_AGREE]"))
    assert len(collector._collab_open) == 1

    # 開いている窓を、退出のsnapshotで閉じもしない(状態を語っていないため)。
    clock["t"] += 100.0
    await collector._on_link_layer(
        _link_event("ch1", [("111", "own", "GROUP_STATUS_LINKED")],
                    source="click_quick_leave_button"))
    assert len(collector._collab_open) == 1, "退出のsnapshotは開閉のどちらにも使わない"


@pytest.mark.asyncio
async def test_own_disconnect_snapshot_closes_the_window(collector, monkeypatch):
    """``leave_with_user_click_disconnect`` は自分が切ったことの名乗りなので閉じる。

    退出系snapshotを一律に無視すると、コラボが終わっても閉じる合図が無くなり、次の
    snapshotが届くまで窓が開いたままになる(実測47分)。生captureに4件あり、4件とも
    映像のコラボはその1〜4秒後に終わっていた。"""
    collector.room_id = 111
    collector._owner_id = "own"
    monkeypatch.setattr(collector, "_persist_progress", lambda: None)
    clock = {"t": 1000.0}
    monkeypatch.setattr(C.time, "time", lambda: clock["t"])
    linked = [("111", "own", "GROUP_STATUS_LINKED"), ("222", "peer", "GROUP_STATUS_LINKED")]

    await collector._on_link_layer(
        _link_event("ch1", linked, source="SOURCE_TYPE_FRIEND_LIST[REPLY_STATUS_AGREE]"))
    assert len(collector._collab_open) == 1

    # rosterは変化前のまま(全員LINKED)だが、名乗りの方が切断を告げている。
    clock["t"] += 200.0
    await collector._on_link_layer(
        _link_event("ch1", linked, source="leave_with_user_click_disconnect"))
    assert collector._collab_open == {}
    window = collector._collab_windows[0]
    assert (window["start"], window["end"]) == (1000.0, 1200.0)


@pytest.mark.asyncio
async def test_a_guest_in_my_own_room_is_not_a_collab(collector, monkeypatch):
    """相手が自室に居るentryはco-hostではない(自室へゲストを上げるmulti-guest)。

    group_change側は自室entryを is_own として既に除いており、list/join_direct側だけが
    残っていた。実測1件(35分)を録画で確かめたところ、画面は最後まで配信者ひとりで
    共演は映っていない。"""
    collector.room_id = 111
    collector._owner_id = "own"
    monkeypatch.setattr(collector, "_persist_progress", lambda: None)
    monkeypatch.setattr(C.time, "time", lambda: 1000.0)

    guest_in_own_room = SimpleNamespace(
        channel_id="ch1",
        join_direct_content=SimpleNamespace(all_users=SimpleNamespace(linked_list=[
            SimpleNamespace(link_user=SimpleNamespace(uid="own", room_id=111)),
            SimpleNamespace(link_user=SimpleNamespace(uid="guest", room_id=111)),
        ])),
    )
    await collector._on_link_layer(guest_in_own_room)
    assert collector._collab_open == {}, "自室のゲストでは窓を開かない"

    peer_in_another_room = SimpleNamespace(
        channel_id="ch1",
        join_direct_content=SimpleNamespace(all_users=SimpleNamespace(linked_list=[
            SimpleNamespace(link_user=SimpleNamespace(uid="own", room_id=111)),
            SimpleNamespace(link_user=SimpleNamespace(uid="peer", room_id=222)),
        ])),
    )
    await collector._on_link_layer(peer_in_another_room)
    assert len(collector._collab_open) == 1, "別室の相手なら従来どおり開く"


@pytest.mark.asyncio
async def test_open_collab_window_ends_when_the_stream_last_sent_data(collector, monkeypatch):
    """開いたままの窓の終端は「配信が生きていた最後の時刻」で頭打ちにする。

    配信が切れた後もcollectorは再接続を試み続け、sessionはその間開いたままになる
    (実測13.6時間、その間viewer_sampleは0件)。session終了時刻で閉じると、その幻の尾を
    丸ごとコラボに数える。``_last_data_at`` はcollector自身が書くsystem eventでも進むため
    使えない — 配信由来のdataだけが動かす ``_last_stream_at`` で切る。"""
    collector.room_id = 111
    collector._owner_id = "own"
    monkeypatch.setattr(collector, "_persist_progress", lambda: None)
    clock = {"t": 1000.0}
    monkeypatch.setattr(C.time, "time", lambda: clock["t"])

    await collector._on_link_layer(_link_event("ch1", [
        ("111", "own", "GROUP_STATUS_LINKED"),
        ("222", "peer", "GROUP_STATUS_LINKED"),
    ]))
    clock["t"] = 1200.0
    await collector._record("comment", {"user": {"unique_id": "v"}, "comment": "やあ"})
    stream_last = collector._last_stream_at

    # 配信が切れ、再接続の記録(system)だけが積まれていく。
    clock["t"] = 9000.0
    await collector._record("system", {"text": "再接続します (1/100回目)。"})
    assert collector._last_stream_at == stream_last, "systemは配信由来のdataではない"
    assert collector._last_data_at == 9000.0, "idle watchdogは撫でる"

    collector._close_open_collab_windows(9000.0)
    window = collector._collab_windows[0]
    assert window["end"] == 1200.0, "配信が最後にdataを送った時刻で閉じる"


@pytest.mark.asyncio
async def test_a_peers_departure_keeps_the_window_open_for_the_remaining_peers(
    collector, monkeypatch
):
    """groupコラボで他人が抜けても自分の窓は閉じないこと(v2の取りこぼしの最大成分)。

    finish_contentが名乗るのは「終了したroom」で、他の参加者のroomが入る。v2は当事者を
    見ずに閉じていたため、次のgroup_change snapshotが届くまで(実測で数十〜数百秒)
    コラボが記録されなかった。"""
    collector.room_id = 111
    collector._owner_id = "own"
    monkeypatch.setattr(collector, "_persist_progress", lambda: None)
    clock = {"t": 1000.0}
    monkeypatch.setattr(C.time, "time", lambda: clock["t"])

    await collector._on_link_layer(_link_event("ch1", [
        ("111", "own", "GROUP_STATUS_LINKED"),
        ("222", "peerA", "GROUP_STATUS_LINKED"),
        ("333", "peerB", "GROUP_STATUS_LINKED"),
    ]))
    assert len(collector._collab_open) == 1

    clock["t"] += 100.0
    await collector._on_link_layer(SimpleNamespace(
        channel_id="ch1",
        finish_content=SimpleNamespace(owner=SimpleNamespace(uid="peerA", room_id="222")),
    ))
    assert len(collector._collab_open) == 1, "残りの相手が居るので窓は開いたまま"
    assert collector._collab_windows == []

    clock["t"] += 100.0
    await collector._on_link_layer(SimpleNamespace(
        channel_id="ch1",
        finish_content=SimpleNamespace(owner=SimpleNamespace(uid="peerB", room_id="333")),
    ))
    assert collector._collab_open == {}, "最後の相手が抜けたら閉じる"
    window = collector._collab_windows[0]
    assert (window["start"], window["end"]) == (1000.0, 1200.0)


# ---------------- 接続時の遡り(backlog)の重複除去 ----------------


async def _noop_broadcast(_message):
    return None


def _comment_event(text, message_id):
    return CommentEvent(
        base_message=CommonMessageData(message_id=message_id),
        user_info=User(id=7_012_345_678, nick_name="Nick", username="handle"),
        content=text,
    )


def _chat_message(message_id, text="おは"):
    """message_idだけを持つ最小のevent。dedupが見るのはこの1 fieldだけである。"""
    return SimpleNamespace(base_message=SimpleNamespace(message_id=message_id), text=text)


def test_message_id_treats_the_protobuf_default_as_absent():
    """未設定のint64は0で届く。0を鍵にすると、idを持たないevent同士が互いの重複になる。"""
    assert dedup.message_id_of(_chat_message(7658591137032538901)) == 7658591137032538901
    assert dedup.message_id_of(_chat_message(0)) is None
    assert dedup.message_id_of(SimpleNamespace()) is None


def test_message_id_is_read_from_whichever_event_carries_it():
    """1つのmessageは最大3つのeventへ展開され、どれも同じbase_messageを持つ。
    ConnectEventのようにidを持たないものが先頭に来ても拾えること。"""
    events = [SimpleNamespace(), _chat_message(42)]
    assert dedup.first_message_id(events) == 42
    assert dedup.first_message_id([SimpleNamespace()]) is None
    assert dedup.first_message_id([]) is None


def test_seen_messages_accepts_once_and_refuses_the_replay():
    seen = dedup.SeenMessages(window_seconds=3600)
    assert seen.add_if_new(1) is True
    assert seen.add_if_new(2) is True
    assert seen.add_if_new(1) is False
    assert seen.dropped == 1


def test_seen_messages_forgets_after_the_window():
    """窓の外まで離れた再訪は落とせない。窓は「覚えていられる範囲」の宣言である。"""
    seen = dedup.SeenMessages(window_seconds=100)
    seen.add_if_new(1, now=1000.0)
    assert seen.add_if_new(1, now=1099.0) is False
    assert seen.add_if_new(1, now=1101.0) is True


def test_seen_messages_does_not_extend_the_window_on_a_replay():
    """再訪で時刻を更新すると、接続のたびに届き直すmessageが永久に窓へ留まる。
    窓は最初に受け取った時刻から数える。"""
    seen = dedup.SeenMessages(window_seconds=100)
    seen.add_if_new(1, now=1000.0)
    seen.add_if_new(1, now=1090.0)
    assert seen.add_if_new(1, now=1101.0) is True, "初回から101秒。再訪では延びない"


def test_seen_messages_drops_the_oldest_when_the_cap_bites():
    """上限は判定の条件ではなくmemoryの天井。当たったら古い方から捨てる。"""
    seen = dedup.SeenMessages(window_seconds=3600, max_entries=2)
    for i in (1, 2, 3):
        seen.add_if_new(i)
    assert len(seen) == 2
    assert seen.capped == 1
    assert seen.add_if_new(1) is True, "追い出された分は覚えていない"
    assert seen.add_if_new(3) is False


class _Wrapper:
    """ProtoMessageFetchResultBaseProtoMessage の代役(dedupは中身を見ない)。"""


async def _parse_via(client, events):
    with mock.patch.object(
        C.DedupTikTokLiveClient.__bases__[0], "_parse_webcast_response_message",
        mock.AsyncMock(return_value=events),
    ):
        return await client._parse_webcast_response_message(_Wrapper())


@pytest.mark.asyncio
async def test_dedup_client_drops_the_whole_message_on_the_second_delivery():
    """接続のたびに届き直す遡り分を、eventへ配る前にmessageごと落とす。

    落とすのがevent単位ではなくmessage単位であることが要点。1つのmessageから生まれる
    custom event(FollowEvent等)とproto eventは同じmessage_idを共有しているので、
    event単位で落とすと最初の1つを通した時点で残りが道連れになる。"""
    seen = dedup.SeenMessages(window_seconds=3600)
    client = C.DedupTikTokLiveClient(unique_id="tester", seen=seen)
    events = [SimpleNamespace(), _chat_message(999), _chat_message(999)]

    assert await _parse_via(client, events) == events, "初回は3つとも通る"
    assert await _parse_via(client, events) == [], "2回目はmessageごと落ちる"
    assert seen.dropped == 1


@pytest.mark.asyncio
async def test_dedup_client_passes_messages_that_carry_no_id():
    """idの無いmessage(接続の合図など)は判定材料が無いので通す。"""
    client = C.DedupTikTokLiveClient(
        unique_id="tester", seen=dedup.SeenMessages(window_seconds=3600))
    events = [SimpleNamespace()]
    assert await _parse_via(client, events) == events
    assert await _parse_via(client, events) == events


@pytest.mark.asyncio
async def test_the_dedup_memory_survives_a_reconnect_and_the_next_session(collector):
    """記憶はclientではなくcollectorが持つ。clientは再接続のたびに作り直されるので、
    clientに持たせると再接続の遡り(=落としたい相手そのもの)が毎回素通りする。"""
    first = collector._build_client("tester")
    assert await _parse_via(first, [_chat_message(555)]) != []
    second = collector._build_client("tester")
    assert await _parse_via(second, [_chat_message(555)]) == []
    collector._reset_session_data()
    third = collector._build_client("tester")
    assert await _parse_via(third, [_chat_message(555)]) == [], "session跨ぎでも覚えている"


@pytest.mark.asyncio
async def test_a_dropped_message_never_reaches_the_stats(collector, monkeypatch):
    """落とす位置が受信側なので、統計もbucketも重複を数えない。DB側の一意制約だけで
    止めていると行は1つでも stats_json の件数だけが水増しされる。"""
    monkeypatch.setattr(collector, "_broadcast", _noop_broadcast)
    event = _comment_event("hello", message_id=4242)
    client = collector._build_client("tester")
    for _ in range(2):
        for kept in await _parse_via(client, [event]):
            await collector._on_comment(kept)
    assert collector.stats["comments"] == 1
