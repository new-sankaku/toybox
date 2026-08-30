"""推移のコイン段が読む日次コイン(profileの daily_coins)。

配信ごとの合計を開始日へ寄せると、その日いくら出たかを指さなくなる。壊れ方は棒が普通に
立ったまま数字だけが違う形で、画面では気付けない。見るのは4点。

  (1) 日を跨いだ配信のコインが、コインの付いた日へ分かれること
  (2) 同じ日の複数配信(reconnectで割れたsessionを含む)が1日へ畳まれること
  (3) 日の切り方がローカル時刻であること(画面の他の日付と同じ軸)
  (4) 日次の合計がGifter一覧の合計と一致すること(まとめで日が落ちない)
"""
from datetime import datetime

from tictok.store.streamers import _period_key


def _ts(text: str) -> float:
    """ローカル時刻の 'YYYY-MM-DD HH:MM' をPOSIX秒へ。日の切り方はローカル時刻なので、
    testも同じ軸で置く(UTC固定で書くと、実行環境のtzで境界testが意味を失う)。"""
    return datetime.strptime(text, "%Y-%m-%d %H:%M").timestamp()


def _gift(tmp_db, session_id, gift_builder, handle, at, diamonds):
    tmp_db.add_event(session_id, gift_builder(
        diamonds=diamonds, at=at,
        user={"user_id": f"7300000000000{handle[-3:]}", "unique_id": handle,
              "nickname": handle.upper(), "avatar": "", "fans_level": 0,
              "gifter_level": 0, "gifter_badge": "", "member_badge": ""}))


def _daily(tmp_db, unique_id="streamer"):
    tmp_db.flush()
    return {d["date"]: d["diamonds"] for d in tmp_db.streamer_profile(unique_id)["daily_coins"]}


def test_coins_after_midnight_land_on_the_next_day(tmp_db, make_session, gift_builder):
    """日を跨いだ配信のコインは、開始日へ寄らずコインの付いた日へ入る。

    実測でsessionの35.6%が日を跨ぐ。session合計を開始日へ振ると、日付が変わった後に
    出たコインまで前日ぶんとして数えることになる。
    """
    session_id = make_session("streamer")
    _gift(tmp_db, session_id, gift_builder, "fan001", _ts("2026-07-05 23:30"), 300)
    _gift(tmp_db, session_id, gift_builder, "fan002", _ts("2026-07-06 00:30"), 200)

    assert _daily(tmp_db) == {"2026-07-05": 300, "2026-07-06": 200}


def test_same_day_sessions_fold_into_one_day(tmp_db, make_session, gift_builder):
    """同じ日の複数sessionは1日へ畳む。

    reconnectのたびに新しいsessionが立つため、1配信が最大7本に割れる(実測)。配信ごとに
    棒を立てると、その日のコインが割れた本数ぶんの棒に散る。
    """
    first = make_session("streamer")
    second = make_session("streamer")
    _gift(tmp_db, first, gift_builder, "fan001", _ts("2026-07-06 20:00"), 1000)
    _gift(tmp_db, second, gift_builder, "fan002", _ts("2026-07-06 21:00"), 500)

    assert _daily(tmp_db) == {"2026-07-06": 1500}


def test_day_boundary_is_local_midnight(tmp_db, make_session, gift_builder):
    """日の切れ目はローカル時刻の0時。深夜1時のGiftは「前日の配信の続き」ではなく当日ぶん。

    heatmap・cohort・期間別ランキング(PERIOD_RANKING.md)と同じ軸。画面ごとに日の境目が
    違う状態を作らない。
    """
    session_id = make_session("streamer")
    _gift(tmp_db, session_id, gift_builder, "fan001", _ts("2026-07-06 23:59"), 7)
    _gift(tmp_db, session_id, gift_builder, "fan002", _ts("2026-07-07 00:00"), 11)

    daily = _daily(tmp_db)
    assert daily == {"2026-07-06": 7, "2026-07-07": 11}
    # 期間別ランキングの日key(同じローカル時刻の切り方)と一致する。
    assert set(daily) == {_period_key(_ts("2026-07-06 23:59"), "day"),
                          _period_key(_ts("2026-07-07 00:00"), "day")}


def test_daily_total_matches_the_gifter_list(tmp_db, make_session, gift_builder):
    """日次の合計はGifter一覧の合計と一致する(まとめで日が落ちない)。

    突き合わせ先を totals にしないのは、totals が stats_json(finalizeで確定)から来ており、
    収集中のsessionでは0のまま遅れるためである。日次はeventをその場で数えるので、
    同じくeventから作られるGifter一覧と突き合わせるのが同じ土俵になる。
    """
    first = make_session("streamer")
    second = make_session("streamer")
    for i, (session_id, stamp, coins) in enumerate((
        (first, "2026-07-05 20:00", 100),
        (first, "2026-07-05 23:50", 250),
        (first, "2026-07-06 00:10", 400),
        (second, "2026-07-09 21:00", 30),
    )):
        _gift(tmp_db, session_id, gift_builder, f"fan{i:03d}", _ts(stamp), coins)
    tmp_db.flush()

    profile = tmp_db.streamer_profile("streamer")
    daily = {d["date"]: d["diamonds"] for d in profile["daily_coins"]}
    assert daily == {"2026-07-05": 350, "2026-07-06": 400, "2026-07-09": 30}
    assert sum(daily.values()) == sum(g["diamonds"] for g in profile["gifters"])


def test_days_without_gifts_are_absent(tmp_db, make_session, gift_builder):
    """コインの無い日は返さない。0の日を軸の上に置くのは描く側の仕事で、こちらは
    「その日いくら出たか」だけを答える(0を返すと、配信の無い日と区別が付かなくなる)。"""
    session_id = make_session("streamer")
    _gift(tmp_db, session_id, gift_builder, "fan001", _ts("2026-07-05 20:00"), 100)
    _gift(tmp_db, session_id, gift_builder, "fan002", _ts("2026-07-09 20:00"), 100)

    assert list(_daily(tmp_db)) == ["2026-07-05", "2026-07-09"]
