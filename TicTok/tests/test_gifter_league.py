"""ギフターの配信者リーグ帯: 取得待ち行列・D帯の扱い・画面へ渡る値。"""
import asyncio
import time

import pytest

from tictok.collect.gifter_league import MAX_ATTEMPTS, GifterLeagueWorker
from tictok.core.league import display_league, display_league_sql, is_broadcaster_league

DAY = 86400.0


# ===== D帯の解釈 =====

@pytest.mark.parametrize(
    "league, expected",
    [
        ("A1", True), ("a1", True), ("B4", True), ("C5", True),
        # D帯は1度配信しただけでも付き、無効なroom_idに対する応答(D5)とも区別できない。
        ("D1", False), ("D5", False), ("d2", False),
        ("", False), (None, False), ("   ", False),
    ],
)
def test_d_league_is_not_treated_as_broadcaster(league, expected):
    assert is_broadcaster_league(league) is expected


@pytest.mark.parametrize(
    "league, expected",
    [("A1", "A1"), ("b3", "B3"), ("D2", ""), ("", ""), (None, "")],
)
def test_display_league_normalizes_and_drops_d(league, expected):
    assert display_league(league) == expected


def test_display_league_sql_matches_python(tmp_db):
    """SQL側とPython側の判定が食い違うと、一覧と詳細で同じ人のリーグが変わる。"""
    conn = tmp_db._conn
    for raw in ("A1", "b3", "D5", "d1", "", "C4"):
        conn.execute(
            "INSERT OR REPLACE INTO users (identity_key, league) VALUES (?, ?)", ("k", raw)
        )
        row = conn.execute(
            f"SELECT {display_league_sql('u')} AS v FROM users u WHERE identity_key = 'k'"
        ).fetchone()
        assert row["v"] == display_league(raw), raw


# ===== 待ち行列 =====

def _gift(tmp_db, session_id, key, unique_id, coin, at):
    tmp_db.add_event(session_id, {
        "kind": "gift", "time": at, "diamonds": coin, "gift_count": 1,
        "user": {"user_id": key, "unique_id": unique_id, "nickname": unique_id,
                 "avatar": "", "identity_key": key},
    })


@pytest.fixture
def gifters(tmp_db, make_session, frozen_now):
    session_id = make_session("streamer_a")
    _gift(tmp_db, session_id, "111", "whale", 500, frozen_now)
    _gift(tmp_db, session_id, "222", "minnow", 50, frozen_now)
    _gift(tmp_db, session_id, "333", "mid", 100, frozen_now)
    tmp_db.flush()
    return frozen_now


def test_enqueue_only_takes_gifters_over_the_coin_threshold(tmp_db, gifters):
    now = gifters
    assert tmp_db.enqueue_gifter_leagues(now - 3600, 100, 5 * DAY, now) == 2
    keys = set()
    while (target := tmp_db.next_gifter_league_target()) is not None:
        keys.add(target["identity_key"])
        tmp_db.save_gifter_league(target["identity_key"], True, "1", "A1")
    assert keys == {"111", "333"}


def test_enqueue_skips_recently_checked_and_returns_after_the_recheck_window(tmp_db, gifters):
    now = gifters
    assert tmp_db.enqueue_gifter_leagues(now - 3600, 100, 5 * DAY, now) == 2
    target = tmp_db.next_gifter_league_target()
    tmp_db.save_gifter_league(target["identity_key"], True, "999", "A1", now=now)
    tmp_db.save_gifter_league("333", True, "888", "B2", now=now)
    # 確認直後は積み直さない。リーグは日次変動だが毎日全員を引き直す必要は無い。
    assert tmp_db.enqueue_gifter_leagues(now - 3600, 100, 5 * DAY, now) == 0
    assert tmp_db.enqueue_gifter_leagues(now - 3600, 100, 5 * DAY, now + 4 * DAY) == 0
    assert tmp_db.enqueue_gifter_leagues(now - 3600, 100, 5 * DAY, now + 6 * DAY) == 2


def test_enqueue_is_idempotent_within_one_window(tmp_db, gifters):
    now = gifters
    assert tmp_db.enqueue_gifter_leagues(now - 3600, 100, 5 * DAY, now) == 2
    assert tmp_db.enqueue_gifter_leagues(now - 3600, 100, 5 * DAY, now) == 0


def test_enqueue_ignores_gifts_outside_the_window(tmp_db, gifters):
    now = gifters
    assert tmp_db.enqueue_gifter_leagues(now + 3600, 100, 5 * DAY, now + 7200) == 0


def test_enqueue_skips_unidentified_gifters(tmp_db, make_session, frozen_now):
    """身元不明(identity_keyが空/(unknown))は1人を指さないので取得対象にしない。"""
    session_id = make_session("streamer_a")
    tmp_db.add_event(session_id, {
        "kind": "gift", "time": frozen_now, "diamonds": 5000, "gift_count": 1,
        "user": {"user_id": "", "unique_id": "", "nickname": "", "avatar": "",
                 "identity_key": ""},
    })
    tmp_db.flush()
    assert tmp_db.enqueue_gifter_leagues(frozen_now - 3600, 100, 5 * DAY, frozen_now) == 0


def test_queue_survives_a_restart(tmp_db_path, tmp_db, gifters):
    """再起動でqueueが消えると、1件15秒で流している当日ぶんが丸ごと落ちる。"""
    from tictok.storage import Storage

    now = gifters
    tmp_db.enqueue_gifter_leagues(now - 3600, 100, 5 * DAY, now)
    tmp_db.close()
    reopened = Storage(str(tmp_db_path))
    try:
        assert reopened.gifter_league_stats()["pending"] == 2
        assert reopened.next_gifter_league_target()["identity_key"] == "111"
    finally:
        reopened.close()


def test_defer_backs_off_then_drops_without_marking_the_user(tmp_db, gifters):
    now = gifters
    tmp_db.enqueue_gifter_leagues(now - 3600, 100, 5 * DAY, now)
    for attempt in range(1, MAX_ATTEMPTS):
        assert tmp_db.defer_gifter_league("111", "boom", 0.0, MAX_ATTEMPTS) is True
    assert tmp_db.defer_gifter_league("111", "boom", 0.0, MAX_ATTEMPTS) is False
    # 降ろしても「確認済み」にはしない。取れなかったことと、確認して配信者でなかったこと
    # は別物で、前者は次にgiftすれば積み直される。
    row = tmp_db._conn.execute(
        "SELECT broadcaster, league_checked_at FROM users WHERE identity_key = '111'"
    ).fetchone()
    assert row["broadcaster"] is None and row["league_checked_at"] is None
    assert tmp_db.enqueue_gifter_leagues(now - 3600, 100, 5 * DAY, now) == 1


def test_deferred_target_is_not_served_before_its_retry_time(tmp_db, gifters):
    now = gifters
    tmp_db.enqueue_gifter_leagues(now - 3600, 100, 5 * DAY, now)
    tmp_db.defer_gifter_league("111", "boom", 3600.0, MAX_ATTEMPTS)
    assert tmp_db.next_gifter_league_target()["identity_key"] == "333"


def test_stats_count_broadcasters_and_leagues(tmp_db, gifters):
    now = gifters
    tmp_db.enqueue_gifter_leagues(now - 3600, 100, 5 * DAY, now)
    tmp_db.save_gifter_league("111", True, "999", "A1")
    tmp_db.save_gifter_league("333", False, "", "")
    stats = tmp_db.gifter_league_stats()
    assert stats == {"pending": 0, "oldest_enqueued_at": None, "checked": 2,
                     "broadcasters": 1, "with_league": 1}


# ===== 画面へ渡る値 =====

def test_streamer_profile_gifters_carry_league_and_levels(tmp_db, make_session, frozen_now):
    session_id = make_session("streamer_a")
    tmp_db.add_event(session_id, {
        "kind": "gift", "time": frozen_now, "diamonds": 500, "gift_count": 1,
        "user": {"user_id": "111", "unique_id": "whale", "nickname": "Whale", "avatar": "",
                 "identity_key": "111", "fans_level": 7, "gifter_level": 12,
                 "gifter_badge": "g.png", "member_badge": "m.png"},
    })
    tmp_db.add_event(session_id, {
        "kind": "gift", "time": frozen_now, "diamonds": 400, "gift_count": 1,
        "user": {"user_id": "222", "unique_id": "casual", "nickname": "Casual", "avatar": "",
                 "identity_key": "222"},
    })
    tmp_db.flush()
    tmp_db.save_gifter_league("111", True, "999", "B4")
    tmp_db.save_gifter_league("222", True, "888", "D2")
    gifters = {g["unique_id"]: g for g in tmp_db.streamer_profile("streamer_a")["gifters"]}
    assert gifters["whale"]["league"] == "B4"
    assert gifters["whale"]["gifter_level"] == 12
    assert gifters["whale"]["fans_level"] == 7
    assert gifters["whale"]["gifter_badge"] == "g.png"
    # D帯は配信者として見せない(表示だけ落とし、生値はusersに残す)。
    assert gifters["casual"]["league"] == ""
    assert tmp_db._conn.execute(
        "SELECT league FROM users WHERE identity_key = '222'"
    ).fetchone()["league"] == "D2"


def test_fan_ledger_and_profile_expose_league(tmp_db, make_session, frozen_now):
    session_id = make_session("streamer_a")
    tmp_db.add_event(session_id, {
        "kind": "gift", "time": frozen_now, "diamonds": 500, "gift_count": 1,
        "user": {"user_id": "111", "unique_id": "whale", "nickname": "Whale", "avatar": "",
                 "identity_key": "111"},
    })
    tmp_db.flush()
    tmp_db.save_gifter_league("111", True, "999", "A2")
    fan = next(f for f in tmp_db.fan_ledger(0, 50)["fans"] if f["identity_key"] == "111")
    assert fan["league"] == "A2"
    profile = tmp_db.fan_profile("111")
    assert profile["league"] == "A2" and profile["broadcaster"] is True


def test_fan_profile_separates_unchecked_from_not_a_broadcaster(tmp_db, make_session, frozen_now):
    session_id = make_session("streamer_a")
    for key, uid in (("111", "checked"), ("222", "unchecked")):
        tmp_db.add_event(session_id, {
            "kind": "gift", "time": frozen_now, "diamonds": 500, "gift_count": 1,
            "user": {"user_id": key, "unique_id": uid, "nickname": uid, "avatar": "",
                     "identity_key": key},
        })
    tmp_db.flush()
    tmp_db.save_gifter_league("111", False, "", "")
    assert tmp_db.fan_profile("111")["broadcaster"] is False
    assert tmp_db.fan_profile("222")["broadcaster"] is None


# ===== 取得worker(通信は差し替える) =====

class _StubWeb:
    def __init__(self, gift_list):
        self.params = {}
        self._gift_list = gift_list

    async def fetch_gift_list(self):
        return self._gift_list


def _worker_with(monkeypatch, room_data, gift_list, storage=None, settings=None):
    worker = GifterLeagueWorker(storage=storage, settings=settings)
    web = _StubWeb(gift_list)
    monkeypatch.setattr(worker, "_web", lambda: web)

    async def _fetch_user_room_data(web, unique_id):
        if isinstance(room_data, Exception):
            raise room_data
        return room_data

    monkeypatch.setattr(
        "tictok.collect.gifter_league.FetchRoomIdAPIRoute.fetch_user_room_data",
        staticmethod(_fetch_user_room_data),
    )
    return worker, web


def _gift_list(league):
    return {"gifts_info": {"gift_gallery_info": {"anchor_ranking_league": league}}}


def test_worker_reads_league_for_an_offline_broadcaster(monkeypatch):
    """live中である必要は無い(status=4でもroomIdは返り、終了済みの室でもleagueは引ける)。"""
    worker, web = _worker_with(
        monkeypatch, {"data": {"user": {"roomId": "7669064047828601616", "status": 4}}},
        _gift_list("B4"),
    )
    assert asyncio.run(worker._fetch("someone")) == (True, "7669064047828601616", "B4")
    assert web.params["room_id"] == "7669064047828601616"


def test_worker_treats_user_not_found_as_a_confirmed_non_broadcaster(monkeypatch):
    from TikTokLive.client.errors import UserNotFoundError

    worker, _ = _worker_with(
        monkeypatch, UserNotFoundError("nobody", "never went live"), _gift_list("A1"))
    assert asyncio.run(worker._fetch("nobody")) == (False, "", "")


def test_worker_treats_a_missing_room_id_as_a_non_broadcaster(monkeypatch):
    worker, _ = _worker_with(monkeypatch, {"data": {"user": {"status": 4}}}, _gift_list("A1"))
    assert asyncio.run(worker._fetch("roomless")) == (False, "", "")


def test_worker_defers_instead_of_confirming_when_the_response_is_unreadable(
    monkeypatch, tmp_db, gifters
):
    """レート制限はHTMLが返りJSONとして読めない。これを「配信者ではない」と確定させると、
    その人のリーグは再取得の機会ごと失われる。"""
    now = gifters
    tmp_db.enqueue_gifter_leagues(now - 3600, 100, 5 * DAY, now)
    settings = {"gifter_league_interval_seconds": 15}
    worker, _ = _worker_with(
        monkeypatch, ValueError("Expecting value: line 1"), _gift_list("A1"),
        storage=tmp_db, settings=settings,
    )
    assert asyncio.run(worker._process_one()) is True
    row = tmp_db._conn.execute(
        "SELECT attempts, last_error FROM league_queue WHERE identity_key = '111'"
    ).fetchone()
    assert row["attempts"] == 1 and "Expecting value" in row["last_error"]
    assert tmp_db._conn.execute(
        "SELECT league_checked_at FROM users WHERE identity_key = '111'"
    ).fetchone()["league_checked_at"] is None


def test_worker_saves_and_dequeues_on_success(monkeypatch, tmp_db, gifters):
    now = gifters
    tmp_db.enqueue_gifter_leagues(now - 3600, 100, 5 * DAY, now)
    worker, _ = _worker_with(
        monkeypatch, {"data": {"user": {"roomId": "999", "status": 4}}}, _gift_list("A1"),
        storage=tmp_db, settings={"gifter_league_interval_seconds": 15},
    )
    assert asyncio.run(worker._process_one()) is True
    assert tmp_db.next_gifter_league_target()["identity_key"] == "333"
    row = tmp_db._conn.execute(
        "SELECT broadcaster, broadcaster_room_id, league FROM users WHERE identity_key = '111'"
    ).fetchone()
    assert (row["broadcaster"], row["broadcaster_room_id"], row["league"]) == (1, "999", "A1")


def test_worker_reports_an_empty_queue(monkeypatch, tmp_db):
    worker, _ = _worker_with(
        monkeypatch, {"data": {"user": {"roomId": "1"}}}, _gift_list("A1"),
        storage=tmp_db, settings={"gifter_league_interval_seconds": 15},
    )
    assert asyncio.run(worker._process_one()) is False


# ===== ギフトに占めるライバーの割合 =====

def _gift_from(tmp_db, session_id, key, uid, coin, at):
    tmp_db.add_event(session_id, {
        "kind": "gift", "time": at, "diamonds": coin, "gift_count": 1,
        "user": {"user_id": key, "unique_id": uid, "nickname": uid, "avatar": "",
                 "identity_key": key},
    })


@pytest.fixture
def liver_mix(tmp_db, make_session, frozen_now):
    """コイン1000のうち、ライバー300 / 非ライバー200 / 未判定500。"""
    session_id = make_session("streamer_a")
    _gift_from(tmp_db, session_id, "liver1", "liver1", 300, frozen_now)
    _gift_from(tmp_db, session_id, "plain1", "plain1", 200, frozen_now)
    _gift_from(tmp_db, session_id, "unknown1", "unknown1", 500, frozen_now)
    tmp_db.flush()
    tmp_db.save_gifter_league("liver1", True, "999", "A2")
    tmp_db.save_gifter_league("plain1", False, "", "")
    return frozen_now


def test_liver_share_is_reported_on_both_coins_and_headcount(tmp_db, liver_mix):
    """コイン基準と人数基準は別物。1人の大口ライバーが居ればコイン比率だけが跳ねるので、
    どちらの分母かが分かる形で独立して出す。"""
    c = tmp_db.streamer_profile("streamer_a")["concentration"]
    # コイン: ライバー300 / 全体1000。分母は判定済み(500)ではなく全体。
    assert c["liver_diamonds"] == 300
    assert c["liver_gift_diamonds"] == 1000
    assert c["liver_coin_share"] == pytest.approx(30.0)
    assert c["liver_checked_diamonds"] == 500
    assert c["liver_coin_coverage"] == pytest.approx(50.0)
    # 人数: ライバー1人 / 全体3人。同じ素材でもコイン基準と値が違う。
    assert c["liver_gifters"] == 1
    assert c["liver_total_gifters"] == 3
    assert c["liver_gifter_share"] == pytest.approx(100 / 3)
    assert c["liver_checked_gifters"] == 2
    assert c["liver_gifter_coverage"] == pytest.approx(200 / 3)


def test_liver_share_is_none_until_anything_has_been_checked(tmp_db, make_session, frozen_now):
    """判定が1件も無い状態の0%は「ライバーが居ない」ではないので、比率を出さない。"""
    session_id = make_session("streamer_b")
    _gift_from(tmp_db, session_id, "someone", "someone", 400, frozen_now)
    tmp_db.flush()
    c = tmp_db.streamer_profile("streamer_b")["concentration"]
    assert c["liver_coin_share"] is None and c["liver_gifter_share"] is None
    assert c["liver_coin_coverage"] == pytest.approx(0.0)
    assert c["liver_gifter_coverage"] == pytest.approx(0.0)


def test_liver_share_counts_d_league_as_not_a_liver(tmp_db, make_session, frozen_now):
    session_id = make_session("streamer_c")
    _gift_from(tmp_db, session_id, "dtier", "dtier", 100, frozen_now)
    tmp_db.flush()
    tmp_db.save_gifter_league("dtier", True, "1", "D2")
    c = tmp_db.streamer_profile("streamer_c")["concentration"]
    assert c["liver_coin_share"] == pytest.approx(0.0)
    assert c["liver_gifter_share"] == pytest.approx(0.0)
    assert c["liver_coin_coverage"] == pytest.approx(100.0)


def test_streamer_index_carries_the_same_liver_numbers(tmp_db, liver_mix):
    """一覧と詳細で同じ配信者の比率が食い違うと、どちらが正か判断できなくなる。"""
    row = next(s for s in tmp_db.streamer_index() if s["unique_id"] == "streamer_a")
    profile = tmp_db.streamer_profile("streamer_a")["concentration"]
    for field in ("liver_coin_share", "liver_gifter_share", "liver_coin_coverage",
                  "liver_gifter_coverage"):
        assert row[field] == pytest.approx(profile[field]), field
    assert row["liver_diamonds"] == profile["liver_diamonds"]
    assert row["liver_gifters"] == profile["liver_gifters"]
    assert row["liver_total_gifters"] == profile["liver_total_gifters"]


def test_streamer_index_liver_share_is_per_streamer(tmp_db, make_session, frozen_now):
    a = make_session("streamer_a")
    b = make_session("streamer_b")
    _gift_from(tmp_db, a, "liver1", "liver1", 100, frozen_now)
    _gift_from(tmp_db, b, "plain1", "plain1", 100, frozen_now)
    tmp_db.flush()
    tmp_db.save_gifter_league("liver1", True, "9", "B3")
    tmp_db.save_gifter_league("plain1", False, "", "")
    rows = {s["unique_id"]: s for s in tmp_db.streamer_index()}
    assert rows["streamer_a"]["liver_coin_share"] == pytest.approx(100.0)
    assert rows["streamer_b"]["liver_coin_share"] == pytest.approx(0.0)


def test_enqueue_skips_handles_that_cannot_be_looked_up(tmp_db, make_session, frozen_now):
    """identity_keyのfallbackはnicknameまで下りるため、handle欄に表示名が入った行が実在する
    (実DBで3人、うち1人は通算86万コイン)。照会すればTikTokは「居ない」を返すが、それを
    「確認して配信者ではなかった」と確定させると、見ていないものを見たことにしてしまう。"""
    session_id = make_session("streamer_a")
    for key, uid in (("a", "Enigma 40944"), ("b", "だれか"), ("c", "valid.handle_1")):
        _gift(tmp_db, session_id, key, uid, 500, frozen_now)
    tmp_db.flush()
    assert tmp_db.enqueue_gifter_leagues(frozen_now - 3600, 100, 5 * DAY, frozen_now) == 1
    assert tmp_db.next_gifter_league_target()["unique_id"] == "valid.handle_1"
