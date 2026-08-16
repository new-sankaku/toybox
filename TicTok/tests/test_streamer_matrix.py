"""人×期間の一覧(Gifter × 配信日/週/月)。

期間を1つ選ぶ streamer_gifter_ranking と違い、同じ人を期間を跨いで横へ並べる表である。
見るのは6点。(1)列が「Giftの在った期間」と「配信の在った期間」の合併で、日を跨いだ配信の
深夜ぶんも投げた記録がどこかの列に載ること。(2)同じ人が1行に畳まれ、期間ごとのcellに
分かれること。(3)列の上限を超えた古い期間を黙って捨てず、件数で名乗ること。
(4)Battle側が戦の在る期間にだけ入ること。(5)粒度(日/週/月)で列が畳まれること。
(6)カレンダーで選んだ範囲が、その日の属する期間まで含めて効くこと。
"""
import pytest
import sqlite3
from datetime import datetime


def _ts(text: str) -> float:
    """ローカル時刻の 'YYYY-MM-DD HH:MM' をPOSIX秒へ。集計はローカル時刻で切る。"""
    return datetime.strptime(text, "%Y-%m-%d %H:%M").timestamp()


def _set_session_span(tmp_db, tmp_db_path, session_id, started_at, ended_at):
    """配信の時刻を直接置く。create_sessionは「今」で刻むので、暦の日を狙うにはこうする。"""
    tmp_db.flush()
    side = sqlite3.connect(str(tmp_db_path))
    try:
        side.execute("UPDATE sessions SET started_at = ?, ended_at = ? WHERE id = ?",
                     (started_at, ended_at, session_id))
        side.commit()
    finally:
        side.close()


def _gifter(tmp_db, session_id, gift_builder, handle, at, diamonds):
    tmp_db.add_event(session_id, gift_builder(
        diamonds=diamonds, at=at,
        user={"user_id": f"73000000000000{handle[-2:]}", "unique_id": handle,
              "nickname": handle.upper(), "avatar": "", "fans_level": 0,
              "gifter_level": 0, "gifter_badge": "", "member_badge": ""}))


def _cells(row):
    return {key: cell["diamonds"] for key, cell in row["cells"].items()}


def test_same_person_is_one_row_split_into_days(
    tmp_db, tmp_db_path, make_session, gift_builder
):
    """同じ人は1行で、日ごとのcellに分かれる。行の並びは窓の中の合計順。"""
    session_id = make_session("streamer")
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-07-10 20:00"), 500)
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-07-11 20:00"), 300)
    _gifter(tmp_db, session_id, gift_builder, "fan02", _ts("2026-07-11 21:00"), 600)
    _set_session_span(tmp_db, tmp_db_path, session_id,
                      _ts("2026-07-10 19:00"), _ts("2026-07-11 23:00"))

    result = tmp_db.streamer_gifter_matrix("streamer")
    assert [d["key"] for d in result["periods"]] == ["2026-07-10", "2026-07-11"]
    assert [g["unique_id"] for g in result["gifters"]] == ["fan01", "fan02"]
    top = result["gifters"][0]
    assert _cells(top) == {"2026-07-10": 500, "2026-07-11": 300}
    assert top["diamonds"] == 800
    assert top["periods"] == 2
    # 投げていない日はcellを持たない(0で埋めない)。画面はこれを空欄として描く。
    assert _cells(result["gifters"][1]) == {"2026-07-11": 600}


def test_day_totals_match_the_sum_of_the_cells(
    tmp_db, tmp_db_path, make_session, gift_builder
):
    """列の合計は、その列のcellの合計と一致する。ずれると表の縦の読みが崩れる。"""
    session_id = make_session("streamer")
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-07-10 20:00"), 500)
    _gifter(tmp_db, session_id, gift_builder, "fan02", _ts("2026-07-10 21:00"), 250)
    _set_session_span(tmp_db, tmp_db_path, session_id,
                      _ts("2026-07-10 19:00"), _ts("2026-07-10 23:00"))

    result = tmp_db.streamer_gifter_matrix("streamer")
    day = next(d for d in result["periods"] if d["key"] == "2026-07-10")
    assert day["diamonds"] == 750
    assert sum(_cells(g).get("2026-07-10", 0) for g in result["gifters"]) == 750


def test_a_stream_past_midnight_gets_its_own_column(
    tmp_db, tmp_db_path, make_session, gift_builder
):
    """日を跨いだ配信の深夜ぶんも列になる。列をsessionの開始日だけで組むと、この
    Giftがどの列にも載らずに消える。"""
    session_id = make_session("streamer")
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-07-10 23:30"), 100)
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-07-11 00:30"), 400)
    _set_session_span(tmp_db, tmp_db_path, session_id,
                      _ts("2026-07-10 22:00"), _ts("2026-07-11 01:00"))

    result = tmp_db.streamer_gifter_matrix("streamer")
    assert [d["key"] for d in result["periods"]] == ["2026-07-10", "2026-07-11"]
    assert _cells(result["gifters"][0]) == {"2026-07-10": 100, "2026-07-11": 400}


def test_a_stream_without_gifts_stays_as_a_column(tmp_db, tmp_db_path, gift_builder):
    """配信はしたがGiftが0だった日も列に残す。抜くと「誰も投げなかった日」が
    「配信していない日」に化ける。"""
    quiet = tmp_db.create_session("streamer", 60)
    tmp_db.update_session(quiet, "ended")
    _set_session_span(tmp_db, tmp_db_path, quiet,
                      _ts("2026-07-10 20:00"), _ts("2026-07-10 23:00"))
    loud = tmp_db.create_session("streamer", 60)
    _gifter(tmp_db, loud, gift_builder, "fan01", _ts("2026-07-12 20:00"), 500)
    tmp_db.update_session(loud, "ended")
    _set_session_span(tmp_db, tmp_db_path, loud,
                      _ts("2026-07-12 19:00"), _ts("2026-07-12 23:00"))

    result = tmp_db.streamer_gifter_matrix("streamer")
    # 配信の無い7/11は列にしない(列は配信日で、暦の穴は日付ラベルの飛びとして読む)。
    assert [d["key"] for d in result["periods"]] == ["2026-07-10", "2026-07-12"]
    assert next(d for d in result["periods"] if d["key"] == "2026-07-10")["diamonds"] == 0


def test_older_periods_are_named_not_dropped_silently(
    tmp_db, tmp_db_path, make_session, gift_builder
):
    """列の上限で切った古い期間は件数で名乗る。黙って切ると「これしか配信していない」
    と読める。残すのは新しい側。"""
    session_id = make_session("streamer")
    for day in range(1, 8):
        _gifter(tmp_db, session_id, gift_builder, "fan01",
                _ts(f"2026-07-{day:02d} 20:00"), 100)
    _set_session_span(tmp_db, tmp_db_path, session_id,
                      _ts("2026-07-01 19:00"), _ts("2026-07-07 23:00"))

    result = tmp_db.streamer_gifter_matrix("streamer", columns=3)
    assert [d["key"] for d in result["periods"]] == \
        ["2026-07-05", "2026-07-06", "2026-07-07"]
    assert result["older_periods"] == 4
    # 行の合計も窓の中だけ。窓の外の日を混ぜると、列の合計と行の合計が合わなくなる。
    assert result["gifters"][0]["diamonds"] == 300


def test_battle_cells_only_land_on_days_that_had_a_battle(
    tmp_db, tmp_db_path, make_session, gift_builder
):
    """Battle側は戦の在る日にだけ入る。Gifter側は暦どおりなので、同じGiftでも
    2つの表で列が違うことがある(窓が日を跨いだとき)。"""
    session_id = make_session("streamer")
    start = _ts("2026-07-10 23:30")
    _gifter(tmp_db, session_id, gift_builder, "fan01", start + 60, 700)
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-07-11 00:10"), 300)
    tmp_db.flush()
    tmp_db.save_battles(session_id, [{
        "battle_id": 1, "start_time": start, "end_time": _ts("2026-07-11 00:20"),
        "own_score": 1200, "opp_score": 1000,
        "opponents": [{"unique_id": "rival", "nickname": "RIVAL", "avatar": "",
                       "user_id": ""}],
    }])
    _set_session_span(tmp_db, tmp_db_path, session_id,
                      _ts("2026-07-10 22:00"), _ts("2026-07-11 01:00"))

    result = tmp_db.streamer_gifter_matrix("streamer")
    battles = {d["key"]: d["battles"] for d in result["periods"]}
    assert battles == {"2026-07-10": 1, "2026-07-11": 0}
    # 戦は開始日へ数えるので、窓の中の翌日ぶんも7/10のcellに入る。
    assert _cells(result["battle_gifters"][0]) == {"2026-07-10": 1000}
    # Gifter側は暦どおりに2日へ割れる。
    assert _cells(result["gifters"][0]) == {"2026-07-10": 700, "2026-07-11": 300}


def test_matrix_of_a_streamer_without_sessions_is_empty(tmp_db):
    result = tmp_db.streamer_gifter_matrix("nobody")
    assert result["periods"] == []
    assert result["gifters"] == []
    assert result["battle_gifters"] == []


def _week_fixture(tmp_db, tmp_db_path, make_session, gift_builder):
    """7/6(月)〜7/19(日)の2週・2つの月に跨る配信。粒度の畳み方を見るための材料。"""
    session_id = make_session("streamer")
    for day, coins in ((7, 100), (9, 200), (15, 300), (16, 400)):
        _gifter(tmp_db, session_id, gift_builder, "fan01",
                _ts(f"2026-07-{day:02d} 20:00"), coins)
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-08-03 20:00"), 500)
    _set_session_span(tmp_db, tmp_db_path, session_id,
                      _ts("2026-07-07 19:00"), _ts("2026-08-03 23:00"))
    return session_id


def test_weekly_columns_fold_the_days_of_a_week(
    tmp_db, tmp_db_path, make_session, gift_builder
):
    """週の列はその週の月曜で名乗り、中の日を畳む。合計は日別と一致する。"""
    _week_fixture(tmp_db, tmp_db_path, make_session, gift_builder)

    result = tmp_db.streamer_gifter_matrix("streamer", "week")
    assert result["granularity"] == "week"
    assert [d["key"] for d in result["periods"]] == \
        ["2026-07-06", "2026-07-13", "2026-08-03"]
    assert _cells(result["gifters"][0]) == \
        {"2026-07-06": 300, "2026-07-13": 700, "2026-08-03": 500}
    # 畳んでも通算は変わらない。粒度で合計が動くなら、どこかで取りこぼしている。
    assert result["gifters"][0]["diamonds"] == 1500


def test_monthly_columns_fold_the_days_of_a_month(
    tmp_db, tmp_db_path, make_session, gift_builder
):
    """月の列は 'YYYY-MM' で名乗る。投げた期間の数も月単位になる。"""
    _week_fixture(tmp_db, tmp_db_path, make_session, gift_builder)

    result = tmp_db.streamer_gifter_matrix("streamer", "month")
    assert [d["key"] for d in result["periods"]] == ["2026-07", "2026-08"]
    assert _cells(result["gifters"][0]) == {"2026-07": 1000, "2026-08": 500}
    assert result["gifters"][0]["periods"] == 2


def test_calendar_range_keeps_the_periods_that_contain_the_chosen_dates(
    tmp_db, tmp_db_path, make_session, gift_builder
):
    """since/untilは日付で受け、その日の属する期間まで含める。月の1日・週の月曜だけを
    有効にすると、calendarが選べない日を黙って弾くことになる。"""
    _week_fixture(tmp_db, tmp_db_path, make_session, gift_builder)

    # 日: 選んだ日そのもので切る。
    daily = tmp_db.streamer_gifter_matrix("streamer", "day", "2026-07-09", "2026-07-15")
    assert [d["key"] for d in daily["periods"]] == ["2026-07-09", "2026-07-15"]
    # 週: 7/9は7/6の週、7/15は7/13の週。週の途中の日でも、その週ごと入る。
    weekly = tmp_db.streamer_gifter_matrix("streamer", "week", "2026-07-09", "2026-07-15")
    assert [d["key"] for d in weekly["periods"]] == ["2026-07-06", "2026-07-13"]
    # 行の合計も範囲の中だけ。
    assert weekly["gifters"][0]["diamonds"] == 1000
    # 月: 月半ばの日で7月ごと入り、8月は範囲の外なので出さない。
    monthly = tmp_db.streamer_gifter_matrix("streamer", "month", "2026-07-09", "2026-07-15")
    assert [d["key"] for d in monthly["periods"]] == ["2026-07"]


def test_only_one_end_of_the_range_is_enough(
    tmp_db, tmp_db_path, make_session, gift_builder
):
    """片側だけの指定も効く。もう片方は在る記録の端まで。"""
    _week_fixture(tmp_db, tmp_db_path, make_session, gift_builder)

    since = tmp_db.streamer_gifter_matrix("streamer", "day", since="2026-07-15")
    assert [d["key"] for d in since["periods"]] == \
        ["2026-07-15", "2026-07-16", "2026-08-03"]
    until = tmp_db.streamer_gifter_matrix("streamer", "day", until="2026-07-09")
    assert [d["key"] for d in until["periods"]] == ["2026-07-07", "2026-07-09"]


def test_a_range_with_no_streams_still_names_the_calendar_edges(
    tmp_db, tmp_db_path, make_session, gift_builder
):
    """範囲に1つも入らなくても、在る記録の端は返す。画面が「記録が無い」と
    「選んだ範囲に無い」を描き分けられなくなるため。"""
    _week_fixture(tmp_db, tmp_db_path, make_session, gift_builder)

    result = tmp_db.streamer_gifter_matrix("streamer", "day", "2026-09-01", "2026-09-30")
    assert result["periods"] == []
    assert result["first_date"] == "2026-07-07"
    assert result["last_date"] == "2026-08-03"


def test_bad_input_is_refused_instead_of_guessed(
    tmp_db, tmp_db_path, make_session, gift_builder
):
    """粒度・日付・前後関係の壊れた指定は断る。黙って既定へ倒すと、画面の名乗りと
    中身が食い違う。"""
    _week_fixture(tmp_db, tmp_db_path, make_session, gift_builder)

    with pytest.raises(ValueError):
        tmp_db.streamer_gifter_matrix("streamer", "hour")
    with pytest.raises(ValueError):
        tmp_db.streamer_gifter_matrix("streamer", "day", "2026/07/09")
    with pytest.raises(ValueError):
        tmp_db.streamer_gifter_matrix("streamer", "day", "2026-07-15", "2026-07-09")
