"""期間別ランキング(月・週・日)の集計。

見るのは4点。(1)期間の境界が暦どおりで、SQL側の一覧とPython側の切り出しが同じ境界を
出すこと。(2)順位の動き(前期比)が前の期間の全順位から出ること。(3)配信したがGiftの
無かった期間が一覧から消えないこと。(4)Battleがstart_timeの属する期間へ数えられること。
"""
import time
from datetime import datetime

import pytest

from tictok.store.streamers import _period_bounds, _period_key


def _ts(text: str) -> float:
    """ローカル時刻の 'YYYY-MM-DD HH:MM' をPOSIX秒へ。集計はローカル時刻で切るので、
    testも同じ軸で置く(UTC固定で書くと、実行環境のtzで境界testが意味を失う)。"""
    return datetime.strptime(text, "%Y-%m-%d %H:%M").timestamp()


def _set_session_span(tmp_db, tmp_db_path, session_id, started_at, ended_at):
    """配信の時刻を直接置く。create_sessionは「今」で刻むので、暦の期間を狙って
    並べるにはこうするしかない(他のstorage testと同じ手)。"""
    import sqlite3

    tmp_db.flush()
    side = sqlite3.connect(str(tmp_db_path))
    try:
        side.execute("UPDATE sessions SET started_at = ?, ended_at = ? WHERE id = ?",
                     (started_at, ended_at, session_id))
        side.commit()
    finally:
        side.close()


def _gifter(tmp_db, session_id, gift_builder, handle, at, diamonds, user_id=None):
    tmp_db.add_event(session_id, gift_builder(
        diamonds=diamonds, at=at,
        user={"user_id": user_id or f"73000000000000{handle[-2:]}", "unique_id": handle,
              "nickname": handle.upper(), "avatar": "", "fans_level": 0,
              "gifter_level": 0, "gifter_badge": "", "member_badge": ""}))


# ===== 期間の境界 =====


def test_period_key_cuts_on_calendar_boundaries():
    """月=1日〜末日 / 週=月曜〜日曜 / 日=0時〜24時。深夜1時の配信は翌日ぶんに入る。"""
    assert _period_key(_ts("2026-07-15 13:00"), "month") == "2026-07"
    assert _period_key(_ts("2026-07-31 23:59"), "month") == "2026-07"
    assert _period_key(_ts("2026-08-01 00:01"), "month") == "2026-08"
    # 2026-07-15は水曜。その週の月曜は07-13。
    assert _period_key(_ts("2026-07-15 13:00"), "week") == "2026-07-13"
    # 日曜(07-19)は前の月曜の週に属する(週の切れ目は月曜)。
    assert _period_key(_ts("2026-07-19 23:00"), "week") == "2026-07-13"
    assert _period_key(_ts("2026-07-20 00:30"), "week") == "2026-07-20"
    # 深夜1時は「前日の配信の続き」ではなく、暦どおり当日ぶん。
    assert _period_key(_ts("2026-07-16 01:00"), "day") == "2026-07-16"


def test_period_bounds_end_is_the_next_period_start():
    """[start, end) の end は次の期間の開始そのもの。1秒の隙間を空けると、その瞬間の
    Giftがどの期間にも入らない。"""
    for granularity, key, nxt in (
        ("month", "2026-12", "2027-01"),
        ("week", "2026-07-13", "2026-07-20"),
        ("day", "2026-07-31", "2026-08-01"),
    ):
        _, end = _period_bounds(key, granularity)
        assert _period_key(end, granularity) == nxt
        assert _period_bounds(nxt, granularity)[0] == end


@pytest.mark.parametrize("granularity", ["month", "week", "day"])
def test_sql_and_python_agree_on_the_period_of_an_event(
    tmp_db, make_session, gift_builder, granularity
):
    """期間の一覧はSQL側の式で、一覧の中身はPython側の境界で切る。両者がずれると、
    一覧に出ているコイン合計と、その期間を開いたときの合計が合わなくなる。"""
    session_id = make_session("streamer")
    # 月末・週またぎ・深夜と、境界に当たる時刻を並べる。
    stamps = ["2026-06-28 22:00", "2026-06-30 23:30", "2026-07-01 00:30",
              "2026-07-13 09:00", "2026-07-19 23:59", "2026-07-20 00:00"]
    for i, stamp in enumerate(stamps):
        _gifter(tmp_db, session_id, gift_builder, f"fan{i:02d}", _ts(stamp), 10)
    tmp_db.flush()

    result = tmp_db.streamer_gifter_ranking("streamer", granularity)
    by_key = {p["key"]: p["diamonds"] for p in result["periods"]}
    expected: dict = {}
    for stamp in stamps:
        expected[_period_key(_ts(stamp), granularity)] = \
            expected.get(_period_key(_ts(stamp), granularity), 0) + 10
    for key, diamonds in expected.items():
        assert by_key.get(key) == diamonds


# ===== ランキングの中身 =====


def test_ranking_splits_gifters_by_period(tmp_db, make_session, gift_builder):
    """同じ人でも期間が違えば別の行に数える。通算のGifter一覧とは別の軸である。"""
    session_id = make_session("streamer")
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-06-10 20:00"), 500)
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-07-10 20:00"), 100)
    _gifter(tmp_db, session_id, gift_builder, "fan02", _ts("2026-07-11 20:00"), 300)
    tmp_db.flush()

    june = tmp_db.streamer_gifter_ranking("streamer", "month", "2026-06")
    assert [(g["unique_id"], g["diamonds"]) for g in june["gifters"]] == [("fan01", 500)]
    july = tmp_db.streamer_gifter_ranking("streamer", "month", "2026-07")
    assert [(g["unique_id"], g["diamonds"]) for g in july["gifters"]] == \
        [("fan02", 300), ("fan01", 100)]


def test_rank_delta_reads_the_previous_period(tmp_db, make_session, gift_builder):
    """前期比は前の期間の順位との差。前の期間に居なかった人はNone(=初登場)で、
    0や大きな数で埋めない(埋めると「急上昇」として描かれる)。"""
    session_id = make_session("streamer")
    # 6月: fan01が1位、fan02が2位。
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-06-10 20:00"), 500)
    _gifter(tmp_db, session_id, gift_builder, "fan02", _ts("2026-06-10 21:00"), 100)
    # 7月: 逆転し、fan03が初登場。
    _gifter(tmp_db, session_id, gift_builder, "fan02", _ts("2026-07-10 20:00"), 900)
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-07-10 21:00"), 400)
    _gifter(tmp_db, session_id, gift_builder, "fan03", _ts("2026-07-11 21:00"), 50)
    tmp_db.flush()

    july = tmp_db.streamer_gifter_ranking("streamer", "month", "2026-07")
    assert july["prev_period"] == "2026-06"
    delta = {g["unique_id"]: (g["rank"], g["prev_rank"], g["rank_delta"])
             for g in july["gifters"]}
    assert delta["fan02"] == (1, 2, 1)
    assert delta["fan01"] == (2, 1, -1)
    assert delta["fan03"] == (3, None, None)

    # 比べる前の期間が無い最初の期間は、差そのものが存在しない。
    june = tmp_db.streamer_gifter_ranking("streamer", "month", "2026-06")
    assert june["prev_period"] == ""
    assert all(g["rank_delta"] is None for g in june["gifters"])


def test_counts_are_not_cut_by_the_display_limit(tmp_db, make_session, gift_builder):
    """人数は一覧を切る前の全員。切った後の数を出すと、上限に当たった期間がどれも同じ
    人数に見える(画面上部の通算Gifter数と並ぶので、比べられる値でなければならない)。"""
    session_id = make_session("streamer")
    for i in range(120):
        _gifter(tmp_db, session_id, gift_builder, f"f{i:03d}"[-5:],
                _ts("2026-07-10 20:00"), 1000 - i, user_id=f"7300000000000{i:04d}")
    tmp_db.flush()

    result = tmp_db.streamer_gifter_ranking("streamer", "month", "2026-07")
    assert result["gifter_count"] == 120
    assert len(result["gifters"]) == 100


def test_rank_delta_sees_past_the_displayed_top(tmp_db, make_session, gift_builder):
    """前の期間の順位は表示件数で切る前の全順位から引く。上位N件だけを覚えていると、
    圏外から上がってきた人が全員「初登場」に化ける。"""
    session_id = make_session("streamer")
    # 6月: 120人。fan119は最下位(120位)。
    for i in range(120):
        _gifter(tmp_db, session_id, gift_builder, f"f{i:03d}"[-5:],
                _ts("2026-06-10 20:00"), 1000 - i, user_id=f"7300000000000{i:04d}")
    # 7月: その最下位が1位になる。
    _gifter(tmp_db, session_id, gift_builder, "f119"[-5:], _ts("2026-07-10 20:00"), 9000,
            user_id="73000000000000119")
    tmp_db.flush()

    july = tmp_db.streamer_gifter_ranking("streamer", "month", "2026-07")
    top = july["gifters"][0]
    assert top["prev_rank"] == 120
    assert top["rank_delta"] == 119


def test_periods_keep_a_month_that_had_a_stream_but_no_gift(
    tmp_db, tmp_db_path, gift_builder
):
    """配信はしたがGiftが0だった期間を一覧から抜かない。抜くと「その月は誰も投げて
    いない」が「その月は配信していない」に化ける。"""
    quiet = tmp_db.create_session("streamer", 60)
    tmp_db.update_session(quiet, "ended")
    _set_session_span(tmp_db, tmp_db_path, quiet,
                      _ts("2026-06-05 20:00"), _ts("2026-06-05 23:00"))
    loud = tmp_db.create_session("streamer", 60)
    _gifter(tmp_db, loud, gift_builder, "fan01", _ts("2026-08-10 20:00"), 500)
    tmp_db.update_session(loud, "ended")
    # 実行日に引きずられないよう、こちらの配信も時刻を置く(置かないと「今」が端になり、
    # 月が変わった日にこのtestだけ落ちる)。
    _set_session_span(tmp_db, tmp_db_path, loud,
                      _ts("2026-08-10 20:00"), _ts("2026-08-10 23:00"))

    result = tmp_db.streamer_gifter_ranking("streamer", "month")
    keys = [p["key"] for p in result["periods"]]
    # 間の7月(配信も無い)も飛ばさない。飛ばすと期間の並びが詰まって間隔を読み違える。
    assert keys == ["2026-06", "2026-07", "2026-08"]
    assert next(p for p in result["periods"] if p["key"] == "2026-06")["diamonds"] == 0
    # periodを省いたら最新の期間。
    assert result["period"] == "2026-08"


def test_battle_gifters_are_counted_into_the_period_of_the_battle_start(
    tmp_db, make_session, gift_builder
):
    """Battleはstart_timeの属する期間へ数える。窓が翌日へ伸びても戦を割らない。"""
    session_id = make_session("streamer")
    start = _ts("2026-07-31 23:30")
    _gifter(tmp_db, session_id, gift_builder, "fan01", start + 60, 700)
    # 窓の中だが暦では翌月。戦ごと7月に入ること。
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-08-01 00:10"), 300)
    tmp_db.flush()
    tmp_db.save_battles(session_id, [{
        "battle_id": 1, "start_time": start, "end_time": _ts("2026-08-01 00:20"),
        "own_score": 1200, "opp_score": 1000,
        "opponents": [{"unique_id": "rival", "nickname": "RIVAL", "avatar": "", "user_id": ""}],
    }])

    july = tmp_db.streamer_gifter_ranking("streamer", "month", "2026-07")
    assert july["battles"] == 1
    assert [(g["unique_id"], g["diamonds"], g["battles"]) for g in july["battle_gifters"]] == \
        [("fan01", 1000, 1)]
    # 8月のBattleは0件。窓が食い込んでいてもそちらへは数えない。
    august = tmp_db.streamer_gifter_ranking("streamer", "month", "2026-08")
    assert august["battles"] == 0
    assert august["battle_gifters"] == []
    # Gifter側は暦どおりなので、8月ぶんは8月に出る(Battleとは軸が違う)。
    assert [(g["unique_id"], g["diamonds"]) for g in august["gifters"]] == [("fan01", 300)]


def test_battle_gifters_show_the_latest_identity(tmp_db, make_session, gift_builder):
    """期間別も通算表と同じく最新の身元で出す。Gifter側と同じ行に見えること。"""
    session_id = make_session("streamer")
    start = _ts("2026-07-10 20:00")
    for handle, nickname, at in (("zzz_old", "Old Name", start + 60),
                                 ("aaa_new", "New Name", start + 120)):
        tmp_db.add_event(session_id, gift_builder(
            diamonds=50, at=at,
            user={"user_id": "7300000000000000009", "unique_id": handle,
                  "nickname": nickname, "avatar": "", "fans_level": 0,
                  "gifter_level": 0, "gifter_badge": "", "member_badge": ""}))
    tmp_db.flush()
    tmp_db.save_battles(session_id, [{
        "battle_id": 1, "start_time": start, "end_time": start + 300,
        "own_score": 1200, "opp_score": 1000,
        "opponents": [{"unique_id": "rival", "nickname": "RIVAL", "avatar": "", "user_id": ""}],
    }])

    result = tmp_db.streamer_gifter_ranking("streamer", "month", "2026-07")
    battle_row = result["battle_gifters"][0]
    gift_row = result["gifters"][0]
    assert battle_row["unique_id"] == gift_row["unique_id"] == "aaa_new"
    assert battle_row["identity_key"] == gift_row["identity_key"] == "7300000000000000009"


def test_unknown_granularity_is_refused(tmp_db, make_session):
    """粒度は3つだけ。黙って月へ倒すと、画面が別の切り方を出しているのに気づけない。"""
    make_session("streamer")
    with pytest.raises(ValueError):
        tmp_db.streamer_gifter_ranking("streamer", "year")


def test_ranking_of_a_streamer_without_sessions_is_empty(tmp_db):
    """1件も無い配信者でも落ちない(画面が先に開くことがある)。"""
    result = tmp_db.streamer_gifter_ranking("nobody", "month")
    assert result["periods"] == [] and result["gifters"] == []
    assert result["period"] == "" and result["battles"] == 0


def test_ranking_does_not_double_count_a_battle_collected_twice(
    tmp_db, make_session, gift_builder
):
    """同じBattleを2つのsessionが収集していたら、battle_idで1件に畳む。"""
    start = time.time() - 3600
    battle = {"battle_id": 42, "start_time": start, "end_time": start + 300,
              "own_score": 1200, "opp_score": 1000,
              "opponents": [{"unique_id": "rival", "nickname": "RIVAL", "avatar": "",
                             "user_id": ""}]}
    first = make_session("streamer")
    second = make_session("streamer")
    for session_id in (first, second):
        _gifter(tmp_db, session_id, gift_builder, "fan01", start + 60, 100)
        tmp_db.save_battles(session_id, [dict(battle)])
    tmp_db.flush()

    key = _period_key(start, "month")
    result = tmp_db.streamer_gifter_ranking("streamer", "month", key)
    assert result["battles"] == 1
    assert [g["battles"] for g in result["battle_gifters"]] == [1]
