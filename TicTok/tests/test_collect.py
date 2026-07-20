import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from TikTokLive.client.errors import UserNotFoundError
from TikTokLive.proto import (
    BadgeStruct,
    BadgeStructBadgeSceneType,
    CombineBadgeStruct,
    ExtendedUser,
    FollowInfo,
    ImageBadge,
    ImageModel,
    PrivilegeLogExtra,
    UserFansClubInfo,
    UserIdentity,
)

from tictok.collect import collector as C
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
    rec = {"contributions": {}}
    collector._battles[1] = rec
    await collector._on_opponent_gift(1, "h2", C._user_payload(ExtendedUser()), 10)
    await collector._on_opponent_gift(1, "h2", C._user_payload(ExtendedUser()), 20)
    assert rec["contributions"] == {}
    await collector._on_opponent_gift(1, "h2", C._user_payload(ExtendedUser(username="rival")), 30)
    assert set(rec["contributions"]) == {"rival"}


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


# ---------------- league ----------------


def test_extract_league_reads_the_only_known_source_and_never_invents():
    payload = {"gifts_info": {"gift_gallery_info": {"anchor_ranking_league": " B3 "}}}
    assert C._extract_league(payload) == "B3"
    assert C._extract_league({"gifts_info": {}}) == ""
    assert C._extract_league({"gifts_info": {"gift_gallery_info": {}}}) == ""
    assert C._extract_league(None) == ""
    assert C._extract_league("not a dict") == ""


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


def test_linkmic_roster_uids_collects_uids_and_survives_a_broken_payload(collector):
    roster = SimpleNamespace(linked_list=[
        SimpleNamespace(link_user=SimpleNamespace(uid=1)),
        SimpleNamespace(link_user=SimpleNamespace(uid=0)),
        SimpleNamespace(link_user=None),
        SimpleNamespace(link_user=SimpleNamespace(uid=1)),
        SimpleNamespace(link_user=SimpleNamespace(uid=2)),
    ])
    assert collector._linkmic_roster_uids(roster) == {"1", "2"}
    assert collector._linkmic_roster_uids(None) == set()

    class Broken:
        @property
        def linked_list(self):
            raise RuntimeError("bad payload")

    # 読めなくても窓自体は残す(例外を上へ投げない)。
    assert collector._linkmic_roster_uids(Broken()) == set()


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
