"""週のメンション一覧(土曜の朝7時〜次の土曜の朝7時)。

ショート動画の説明文へ貼る@IDを作る口なので、見るのは4点。
(1) 週の境目が土曜の7時であること — 既存のランキングの「週」は月曜0時始まりで、こちら
    だけが投稿の周期に合わせて土曜の朝で切る。日の境目も0時ではないので、土曜の未明の
    配信は前の週に入る。
(2) SQL側の一覧とPython側の切り出しが同じ境界を出すこと。
(3) コイン額の区分(10K以上 / 5K以上 / 1K以上 / 100コイン以上)が排他で、1人が1つの区分に
    しか入らないこと。区分の人数の合計が一覧の人数と一致すること。
(4) 一番下の区分に届かない人は一覧から外すが、人数とコインは必ず名乗ること。
    @IDの取れていない人は落とさないこと(貼れるかどうかは別のfieldが名乗る)。
(5) 行を開いたときのgift一覧が、一覧のコイン合計と必ず一致すること。
(6) 投稿へまとめて貼るための名乗り(月日だけの範囲)と、載せる区分の下限をServerが返すこと。
(7) 同じ週を日(7時〜翌7時)へ割った貢献(days)。境目が週と同じ時刻なので、7日ぶんのコインは
    週の合計と必ず一致すること。貼る文面はServerが組み、@IDの取れていない人も順位から
    外さないこと ―― 週の一覧は@で呼ぶ相手、こちらは順位の名乗りで目的が違う。
(8) 同じ人の別アカウント(user_merges)を日ぶんだけ1人へ畳むこと。畳むのは行の束ね方だけで、
    数えるGift eventは変わらないので、日の合計は週の合計と一致したままであること。
"""
from datetime import datetime

import pytest

from tictok.store._common import NON_IDENTITY_KEYS, USER_ALIAS_MAX
from tictok.store.streamers import (
    DAY_SHIFTED, MENTION_MEDALS, MENTION_POST_MIN, MENTION_TIERS, WEEK_SATURDAY,
    WEEK_START_HOUR, _MENTION_DAY_ROSTER, _mention_tier_defs, _mention_tier_of,
    _period_bounds, _period_key,
)


def _ts(text: str) -> float:
    """ローカル時刻の 'YYYY-MM-DD HH:MM' をPOSIX秒へ。集計はローカル時刻で切るので、
    testも同じ軸で置く(UTC固定で書くと、実行環境のtzで境界testが意味を失う)。"""
    return datetime.strptime(text, "%Y-%m-%d %H:%M").timestamp()


def _gifter(tmp_db, session_id, gift_builder, handle, at, diamonds, unique_id=None):
    tmp_db.add_event(session_id, gift_builder(
        diamonds=diamonds, at=at,
        user={"user_id": f"73000000000000{handle[-2:]}",
              "unique_id": handle if unique_id is None else unique_id,
              "nickname": handle.upper(), "avatar": "", "fans_level": 0,
              "gifter_level": 0, "gifter_badge": "", "member_badge": ""}))


# ===== 週の境界 =====


def test_week_starts_saturday_morning_not_midnight():
    """土曜の7時が週の始まり。同じ土曜でも6時台はまだ前の週で、日の境目(0時)では切らない。"""
    # 2026-08-29は土曜。
    assert _period_key(_ts("2026-08-29 07:00"), WEEK_SATURDAY) == "2026-08-29"
    assert _period_key(_ts("2026-08-29 06:59"), WEEK_SATURDAY) == "2026-08-22"
    # 土曜の未明(前日から続く配信)は前の週。ここを0時で切ると1本の配信が2週に割れる。
    assert _period_key(_ts("2026-09-05 02:00"), WEEK_SATURDAY) == "2026-08-29"
    assert _period_key(_ts("2026-09-05 06:59"), WEEK_SATURDAY) == "2026-08-29"
    assert _period_key(_ts("2026-09-05 07:00"), WEEK_SATURDAY) == "2026-09-05"
    # 同じ時刻が、月曜0時始まりの週では別の箱。ここが取り違えの元なので縛る。
    assert _period_key(_ts("2026-08-29 12:00"), "week") == "2026-08-24"
    assert _period_key(_ts("2026-08-29 12:00"), WEEK_SATURDAY) == "2026-08-29"


def test_week_bounds_run_from_seven_to_seven():
    """[start, end) は土曜7時から次の土曜7時。endは次の週の開始そのもので、1秒の隙間を
    空けるとその瞬間のGiftがどの週にも入らない。"""
    start, end = _period_bounds("2026-08-29", WEEK_SATURDAY)
    assert start == _ts("2026-08-29 07:00")
    assert end == _ts("2026-09-05 07:00")
    assert datetime.fromtimestamp(start).hour == WEEK_START_HOUR
    assert _period_bounds("2026-09-05", WEEK_SATURDAY)[0] == end


def test_sql_and_python_agree_on_the_week_of_an_event(
    tmp_db, make_session, gift_builder
):
    """週の一覧はSQL側の式で、一覧の中身はPython側の境界で切る。両者がずれると、
    selectに出ているコイン合計と、その週を開いたときの合計が合わなくなる。"""
    session_id = make_session("streamer")
    # 土曜の7時ちょうど・その1分前・未明と、境界に当たる時刻を並べる。
    stamps = ["2026-08-22 07:00", "2026-08-29 06:59", "2026-08-29 07:00",
              "2026-09-01 21:00", "2026-09-05 03:30", "2026-09-05 07:00"]
    for i, stamp in enumerate(stamps):
        _gifter(tmp_db, session_id, gift_builder, f"fan{i:02d}", _ts(stamp), 10)
    tmp_db.flush()

    weeks = {w["key"]: w["diamonds"]
             for w in tmp_db.streamer_mention_week("streamer")["weeks"]}
    expected: dict = {}
    for stamp in stamps:
        key = _period_key(_ts(stamp), WEEK_SATURDAY)
        expected[key] = expected.get(key, 0) + 10
    assert expected == {"2026-08-22": 20, "2026-08-29": 30, "2026-09-05": 10}
    for key, diamonds in expected.items():
        assert weeks.get(key) == diamonds


def test_labels_carry_the_time_of_day(tmp_db, make_session, gift_builder):
    """名乗りには時刻を入れる。keyは土曜の日付なので、日付だけだと土曜の朝(0〜7時)が
    どちらの週とも読める。endは次の週の開始と同じ時刻(半開区間)をそのまま出す。"""
    session_id = make_session("streamer")
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-09-01 20:00"), 100)
    tmp_db.flush()

    result = tmp_db.streamer_mention_week("streamer")
    assert result["week"] == "2026-08-29"
    assert result["start_label"] == "2026-08-29 07:00"
    assert result["end_label"] == "2026-09-05 07:00"
    # 選択肢の文言もServerが持つ(画面側で組ませると時刻が落ちる)。
    assert [w["label"] for w in result["weeks"]] == ["2026-08-29 07:00"]


def test_post_label_names_the_week_for_the_caption(tmp_db, make_session, gift_builder):
    """投稿へまとめて貼るときの名乗りは月日だけ。窓の端(時刻付き)とは別に持つのは、
    投稿の文言に時刻や年を出さないためで、画面側で日付から組み直させない。"""
    session_id = make_session("streamer")
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-09-01 20:00"), 100)
    tmp_db.flush()

    result = tmp_db.streamer_mention_week("streamer")
    assert result["post_label"] == "8月29日〜9月5日"
    # まとめcopyへ載せる区分の下限もServerが名乗る。画面側で額を書くと、区分の切り方を
    # 変えたときに画面だけ古い境目のまま残る。
    assert result["post_min"] == MENTION_POST_MIN
    assert MENTION_POST_MIN in MENTION_TIERS
    # 100コインの区分は下限より下。まとめcopyには入らない。
    assert MENTION_TIERS[-1] < MENTION_POST_MIN


# ===== コイン額の区分 =====


def test_tiers_are_exclusive_and_ordered_high_to_low():
    """区分は高い順で排他。「5K以上」に10K以上の人は入らない(累積にすると同じ人が
    どの区分にも出て、区分ごとにメンションを作れない)。"""
    labels = [t["label"] for t in _mention_tier_defs()]
    assert labels == ["10K以上", "5K以上", "1K以上", "100コイン以上"]
    # 境目そのものは上の区分に入る(「10K以上」は10000ちょうどを含む)。
    assert _mention_tier_of(30000) == 0
    assert _mention_tier_of(10000) == 0
    assert _mention_tier_of(9999) == 1
    assert _mention_tier_of(5000) == 1
    assert _mention_tier_of(4999) == 2
    assert _mention_tier_of(1000) == 2
    assert _mention_tier_of(999) == 3
    assert _mention_tier_of(100) == 3
    # 区分の一番下に届かない人は区分そのものが無い。一覧には載せず、人数だけ名乗る。
    assert _mention_tier_of(99) is None
    assert _mention_tier_of(0) is None


def test_gifters_carry_their_tier_and_the_bands_add_up(
    tmp_db, make_session, gift_builder
):
    """行のtierと区分の人数は同じ集計から出す。区分の人数の合計が一覧の人数と合わないと、
    画面の枠の見出しが嘘になる。"""
    session_id = make_session("streamer")
    coins = [30000, 10000, 9999, 5000, 4999, 1000, 999, 100, 99, 1]
    for i, coin in enumerate(coins):
        _gifter(tmp_db, session_id, gift_builder, f"fan{i:02d}",
                _ts("2026-09-01 20:00"), coin)
    tmp_db.flush()

    result = tmp_db.streamer_mention_week("streamer", "2026-08-29")
    assert [g["tier"] for g in result["gifters"]] == [0, 0, 1, 1, 2, 2, 3, 3]
    assert [(t["label"], t["count"]) for t in result["tiers"]] == [
        ("10K以上", 2), ("5K以上", 2), ("1K以上", 2), ("100コイン以上", 2),
    ]
    # 区分の人数の合計は一覧の長さ。gifter_countはその週に投げた全員なので別の数。
    assert sum(t["count"] for t in result["tiers"]) == len(result["gifters"]) == 8
    assert result["gifter_count"] == 10
    # 一覧から外した2人(99/1コイン)は人数とコインで必ず名乗る。
    assert result["below_count"] == 2
    assert result["below_diamonds"] == 100
    assert sum(t["diamonds"] for t in result["tiers"]) + result["below_diamonds"] \
        == sum(coins)
    # 順位は一覧に載る人の中で振り直す(番号が飛ぶと画面の行数と最後の番号が合わない)。
    assert [g["rank"] for g in result["gifters"]] == [1, 2, 3, 4, 5, 6, 7, 8]
    # 区分の上限は1つ上の区分の下限。画面はこれで「5K以上」が5K〜10Kだと名乗る。
    assert [t["max"] for t in result["tiers"]] == [None, 10000, 5000, 1000]
    assert [t["min"] for t in result["tiers"]] == list(MENTION_TIERS)


def test_tier_counts_separate_the_mentionable(tmp_db, make_session, gift_builder):
    """区分ごとに、貼れる人数(@IDの取れている人)も別に数える。画面は枠の印の状態を
    これで決めるので、@ID無しを人数に混ぜると「全員載せたのに満杯にならない」印になる。"""
    session_id = make_session("streamer")
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-09-01 20:00"), 20000)
    _gifter(tmp_db, session_id, gift_builder, "fan02", _ts("2026-09-01 21:00"), 15000,
            unique_id="")
    tmp_db.flush()

    top = tmp_db.streamer_mention_week("streamer", "2026-08-29")["tiers"][0]
    assert (top["count"], top["mentionable"]) == (2, 1)


# ===== 一覧の中身 =====


def test_latest_week_is_returned_when_none_is_asked(
    tmp_db, make_session, gift_builder
):
    """週を省いたら一番新しい週。"""
    session_id = make_session("streamer")
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-08-25 20:00"), 100)
    _gifter(tmp_db, session_id, gift_builder, "fan02", _ts("2026-09-01 20:00"), 300)
    tmp_db.flush()

    result = tmp_db.streamer_mention_week("streamer")
    assert result["week"] == "2026-08-29"
    assert result["prev_week"] == "2026-08-22"
    assert result["next_week"] == ""
    assert [g["unique_id"] for g in result["gifters"]] == ["fan02"]


def test_gifters_are_ordered_by_coins_within_the_week(
    tmp_db, make_session, gift_builder
):
    """同じ週の中はコインの多い順。画面は枠ごとにこの順で並べるので、崩れると
    「この区分の1位」が別人になる。"""
    session_id = make_session("streamer")
    for handle, coins in (("fan01", 100), ("fan02", 900), ("fan03", 400)):
        _gifter(tmp_db, session_id, gift_builder, handle, _ts("2026-09-01 20:00"), coins)
    # 隣の週のGiftは混ざらない。
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-08-26 20:00"), 5000)
    tmp_db.flush()

    result = tmp_db.streamer_mention_week("streamer", "2026-08-29")
    assert [(g["unique_id"], g["diamonds"], g["rank"]) for g in result["gifters"]] == [
        ("fan02", 900, 1), ("fan03", 400, 2), ("fan01", 100, 3),
    ]
    assert result["gifter_count"] == 3
    assert result["diamonds"] == 1400


def test_gifters_without_a_handle_stay_in_the_list(
    tmp_db, make_session, gift_builder
):
    """@IDの取れていない人も一覧に残す。落とすと「その週に投げたのはこの人数」が
    実際より小さくなる。貼れる人数は mentionable_count が別に名乗る。"""
    session_id = make_session("streamer")
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-09-01 20:00"), 900)
    _gifter(tmp_db, session_id, gift_builder, "fan02", _ts("2026-09-01 21:00"), 100,
            unique_id="")
    tmp_db.flush()

    result = tmp_db.streamer_mention_week("streamer", "2026-08-29")
    assert result["gifter_count"] == 2
    assert result["mentionable_count"] == 1
    assert [g["unique_id"] for g in result["gifters"]] == ["fan01", ""]


def test_weeks_without_gifts_stay_in_the_list(tmp_db, make_session, gift_builder):
    """配信したがGiftの無かった週を抜くと、「その週は誰も投げていない」が
    「その週は配信していない」に化ける。"""
    session_id = make_session("streamer")
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-08-24 20:00"), 100)
    _gifter(tmp_db, session_id, gift_builder, "fan02", _ts("2026-09-07 20:00"), 100)
    tmp_db.flush()

    result = tmp_db.streamer_mention_week("streamer")
    keys = [w["key"] for w in result["weeks"]]
    assert keys == ["2026-08-22", "2026-08-29", "2026-09-05"]
    # 間の週は残るが中身は0。
    assert dict(zip(keys, (w["diamonds"] for w in result["weeks"])))["2026-08-29"] == 0
    quiet = tmp_db.streamer_mention_week("streamer", "2026-08-29")
    assert quiet["gifters"] == []
    assert quiet["gifter_count"] == 0
    # 0件の週でも区分の形は返す(画面が枠の見出しを描き分けられなくなる)。
    assert [t["count"] for t in quiet["tiers"]] == [0, 0, 0, 0]


def test_unknown_week_falls_back_to_the_latest(tmp_db, make_session, gift_builder):
    """一覧に無い週を渡されたら最新の週。存在しない週の空の一覧を「その週は0人」
    として返すと、画面がその名前で0人を描いてしまう。"""
    session_id = make_session("streamer")
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-09-01 20:00"), 100)
    tmp_db.flush()

    result = tmp_db.streamer_mention_week("streamer", "1999-01-02")
    assert result["week"] == "2026-08-29"
    assert [g["unique_id"] for g in result["gifters"]] == ["fan01"]


def test_no_sessions_returns_an_empty_shape(tmp_db):
    """記録の無い配信者でも同じ形を返す。keyが欠けると画面が「取得失敗」と読む。"""
    result = tmp_db.streamer_mention_week("nobody")
    assert result["week"] == ""
    assert result["start_label"] == ""
    assert result["end_label"] == ""
    assert result["weeks"] == []
    assert result["gifters"] == []
    assert result["gifter_count"] == 0
    assert result["mentionable_count"] == 0
    assert [t["label"] for t in result["tiers"]] == [
        t["label"] for t in _mention_tier_defs()]


# ===== 行を開いたときのgift一覧 =====


def test_gift_list_matches_the_row_total(tmp_db, make_session, gift_builder):
    """1人ぶんのgiftの合計は、一覧のその人のコインと必ず一致する。窓の作り方を
    一覧と共有しているので、ここがずれたら片方の窓が壊れている。"""
    session_id = make_session("streamer")
    for stamp, coins in (("2026-08-30 20:00", 500), ("2026-09-01 21:00", 300),
                         ("2026-09-03 22:00", 200)):
        _gifter(tmp_db, session_id, gift_builder, "fan01", _ts(stamp), coins)
    # 隣の週のGiftは混ざらない(窓の外)。
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-08-27 20:00"), 9000)
    tmp_db.flush()

    week = tmp_db.streamer_mention_week("streamer", "2026-08-29")
    row = week["gifters"][0]
    assert row["diamonds"] == 1000

    gifts = tmp_db.streamer_mention_gifts("streamer", "2026-08-29", row["identity_key"])
    assert gifts["diamonds"] == row["diamonds"]
    assert len(gifts["items"]) == 3
    # 新しい順。開いてすぐ「直近に何が飛んだか」が読めるようにする。
    assert [i["diamonds"] for i in gifts["items"]] == [200, 300, 500]
    assert gifts["truncated"] == 0
    # 日時は分まで。秒まで出しても投稿の役に立たず、行が横に伸びるだけである。
    assert [i["label"] for i in gifts["items"]] == [
        "09/03 22:00", "09/01 21:00", "08/30 20:00"]


def test_gift_list_names_the_gift(tmp_db, make_session, gift_builder):
    """何が飛んだかを出す口なので、gift名と個数と額をそのまま返す。"""
    session_id = make_session("streamer")
    tmp_db.add_event(session_id, gift_builder(
        diamonds=1000, at=_ts("2026-09-01 20:00"),
        user={"user_id": "7300000000000001", "unique_id": "fan01",
              "nickname": "FAN01", "avatar": "", "fans_level": 0,
              "gifter_level": 0, "gifter_badge": "", "member_badge": ""}))
    tmp_db.flush()

    week = tmp_db.streamer_mention_week("streamer", "2026-08-29")
    gifts = tmp_db.streamer_mention_gifts(
        "streamer", "2026-08-29", week["gifters"][0]["identity_key"])
    item = gifts["items"][0]
    assert item["diamonds"] == 1000
    assert item["count"] >= 1
    # 名前とidは画面がiconを出す根拠。空でも落とさない(iconが出ないだけ)。
    assert "name" in item and "gift_id" in item


def test_gift_list_of_an_unknown_person_is_empty(tmp_db, make_session, gift_builder):
    """居ない人を指されても同じ形を返す。keyが欠けると画面が「取得失敗」と読む。"""
    make_session("streamer")
    result = tmp_db.streamer_mention_gifts("streamer", "2026-08-29", "nobody")
    assert result["items"] == []
    assert result["diamonds"] == 0
    assert result["truncated"] == 0
    # identity_keyが空のときも同じ(画面が組み立てに失敗しても壊れない)。
    assert tmp_db.streamer_mention_gifts("streamer", "2026-08-29", "")["items"] == []


# ===== 日ぶんの貢献 =====


def test_day_starts_at_the_same_hour_as_the_week():
    """日の境目も週と同じ朝7時。0時で切ると深夜の配信が2日へ割れ、土曜の未明の分が
    「週は前の週・日は当日」という別々の箱に入って、日の合計と週の合計が合わなくなる。"""
    assert _period_key(_ts("2026-08-30 07:00"), DAY_SHIFTED) == "2026-08-30"
    assert _period_key(_ts("2026-08-30 06:59"), DAY_SHIFTED) == "2026-08-29"
    # 未明(0〜7時)は前日の枠。暦どおりの"day"とは別の箱になる。
    assert _period_key(_ts("2026-08-30 02:00"), DAY_SHIFTED) == "2026-08-29"
    assert _period_key(_ts("2026-08-30 02:00"), "day") == "2026-08-30"
    start, end = _period_bounds("2026-08-30", DAY_SHIFTED)
    assert start == _ts("2026-08-30 07:00")
    assert end == _ts("2026-08-31 07:00")
    assert datetime.fromtimestamp(start).hour == WEEK_START_HOUR


def test_seven_days_tile_the_week_exactly():
    """週を日で割ると過不足なく7つ。1つでもずれると、日ぶんのコインの和が週の合計と
    合わなくなる(画面はその一致を根拠に並べている)。"""
    week_start, week_end = _period_bounds("2026-08-29", WEEK_SATURDAY)
    keys = []
    key = _period_key(week_start, DAY_SHIFTED)
    while True:
        low, high = _period_bounds(key, DAY_SHIFTED)
        if low >= week_end:
            break
        keys.append((key, low, high))
        key = _period_key(high, DAY_SHIFTED)
    assert len(keys) == 7
    assert keys[0][1] == week_start
    assert keys[-1][2] == week_end
    # 隙間も重なりも無い(前の日の終わりが次の日の始まり)。
    assert all(keys[i][2] == keys[i + 1][1] for i in range(len(keys) - 1))


def test_sql_and_python_agree_on_the_day_of_an_event(
    tmp_db, make_session, gift_builder
):
    """日ぶんの集計はSQL側の式で切り、窓の並べ方はPython側の境界で作る。両者がずれると、
    どの札にも入らないGiftが出る(週の合計と札の合計が合わなくなる)。"""
    session_id = make_session("streamer")
    stamps = ["2026-08-29 07:00", "2026-08-30 06:59", "2026-08-30 07:00",
              "2026-08-31 02:00", "2026-09-01 23:30"]
    for i, stamp in enumerate(stamps):
        _gifter(tmp_db, session_id, gift_builder, f"fan{i:02d}", _ts(stamp), 10)
    tmp_db.flush()

    days = {d["key"]: d["diamonds"]
            for d in tmp_db.streamer_mention_week("streamer", "2026-08-29")["days"]}
    expected: dict = {}
    for stamp in stamps:
        key = _period_key(_ts(stamp), DAY_SHIFTED)
        expected[key] = expected.get(key, 0) + 10
    for key, coins in expected.items():
        assert days[key] == coins, key


def test_day_coins_add_up_to_the_week(tmp_db, make_session, gift_builder):
    """日ぶんの和が週の合計と一致すること。これが画面の並べ方の根拠なので、ここが
    崩れたら日と週のどちらが本当か読めなくなる。"""
    session_id = make_session("streamer")
    stamps = ["2026-08-29 08:00", "2026-08-29 23:00", "2026-08-30 03:00",
              "2026-09-01 20:00", "2026-09-01 21:00"]
    for i, stamp in enumerate(stamps):
        _gifter(tmp_db, session_id, gift_builder, f"fan{i:02d}", _ts(stamp), 500)
    tmp_db.flush()

    result = tmp_db.streamer_mention_week("streamer", "2026-08-29")
    assert sum(d["diamonds"] for d in result["days"]) == result["diamonds"] == 2500


def test_days_are_newest_first(tmp_db, make_session, gift_builder):
    """新しい日が先。投稿するのは直近の日なので、探して下まで送らせない。"""
    session_id = make_session("streamer")
    for i, stamp in enumerate(["2026-08-29 20:00", "2026-08-31 20:00"]):
        _gifter(tmp_db, session_id, gift_builder, f"fan{i:02d}", _ts(stamp), 100)
    tmp_db.flush()

    keys = [d["key"]
            for d in tmp_db.streamer_mention_week("streamer", "2026-08-29")["days"]]
    assert keys == sorted(keys, reverse=True)


def _day_of(tmp_db, key="2026-09-01"):
    days = tmp_db.streamer_mention_week("streamer", "2026-08-29")["days"]
    found = [d for d in days if d["key"] == key]
    assert found, key
    return found[0]


def test_day_ranks_by_coins_and_carries_the_medals(
    tmp_db, make_session, gift_builder
):
    """順位はその日のコイン合計。上位にはメダルの印が付き、以降は番号だけになる。
    メダルの数はMENTION_MEDALSが決める(画面側で数えない)。"""
    session_id = make_session("streamer")
    for i, coin in enumerate([5000, 4000, 3000, 2000, 900]):
        _gifter(tmp_db, session_id, gift_builder, f"fan{i:02d}",
                _ts("2026-09-01 20:00"), coin)
    tmp_db.flush()

    day = _day_of(tmp_db)
    assert [g["diamonds"] for g in day["roster"]] == [5000, 4000, 3000, 2000, 900]
    assert [g["rank"] for g in day["roster"]] == [1, 2, 3, 4, 5]
    assert [g["medal"] for g in day["roster"]] == list(MENTION_MEDALS) + ["", ""]


def test_day_post_text_is_the_caption_to_paste(tmp_db, make_session, gift_builder):
    """貼る文面はServerが組む。画面側で組ませると名乗りの形が2つに割れる。
    「1k⬆️◯名」の◯はその日にMENTION_POST_MIN以上を投げた人数で、上位3人も含む。"""
    session_id = make_session("streamer")
    for i, coin in enumerate([5000, 4000, 3000, 2000, 900]):
        _gifter(tmp_db, session_id, gift_builder, f"fan{i:02d}",
                _ts("2026-09-01 20:00"), coin)
    tmp_db.flush()

    day = _day_of(tmp_db)
    assert day["post_text"].split("\n") == [
        "トップ3貢献",
        "🥇 FAN00 🥈 FAN01 🥉 FAN02",
        "1k⬆️4名",
    ]
    # 画面が同じ数を出せるように、人数そのものも返す。
    assert day["post_count"] == 4
    assert day["gifter_count"] == 5
    assert MENTION_POST_MIN == 1000


def test_day_roster_text_numbers_the_faces_with_their_coins(
    tmp_db, make_session, gift_builder
):
    """顔ぶれをそのまま貼る文面。上位3人だけの文面とは別の口で、印の在る3人より下まで
    載るのでメダルではなく番号で並べる。額まで入れるのは、順位の根拠を貼った先でも
    読めるようにするためである。"""
    session_id = make_session("streamer")
    for i, coin in enumerate([5000, 4000, 3000, 2000, 900]):
        _gifter(tmp_db, session_id, gift_builder, f"fan{i:02d}",
                _ts("2026-09-01 20:00"), coin)
    tmp_db.flush()

    day = _day_of(tmp_db)
    assert day["roster_text"].split("\n") == [
        "1. FAN00　5,000",
        "2. FAN01　4,000",
        "3. FAN02　3,000",
        "4. FAN03　2,000",
        "5. FAN04　900",
    ]


def test_day_roster_text_is_capped_with_the_roster(
    tmp_db, make_session, gift_builder
):
    """写る行数は顔ぶれと同じ上限で切る。画面の表と貼る文面が別の件数になると、
    押す前に確かめられない。"""
    session_id = make_session("streamer")
    for i in range(_MENTION_DAY_ROSTER + 3):
        _gifter(tmp_db, session_id, gift_builder, f"fan{i:02d}",
                _ts("2026-09-01 20:00"), 2000 - i)
    tmp_db.flush()

    day = _day_of(tmp_db)
    lines = day["roster_text"].split("\n")
    assert len(lines) == _MENTION_DAY_ROSTER
    assert lines[-1].startswith(f"{_MENTION_DAY_ROSTER}. ")


def test_day_post_text_drops_the_band_line_when_nobody_reaches_it(
    tmp_db, make_session, gift_builder
):
    """1K以上が居ない日は「1k⬆️0名」と書かない。0名の行を貼ると、大口が居なかったのか
    数え忘れたのかが貼った先から読めない。"""
    session_id = make_session("streamer")
    for i, coin in enumerate([900, 500]):
        _gifter(tmp_db, session_id, gift_builder, f"fan{i:02d}",
                _ts("2026-09-01 20:00"), coin)
    tmp_db.flush()

    day = _day_of(tmp_db)
    assert day["post_text"].split("\n") == ["トップ3貢献", "🥇 FAN00 🥈 FAN01"]
    assert day["post_count"] == 0


def test_day_post_text_keeps_people_without_a_handle(
    tmp_db, make_session, gift_builder
):
    """@IDの取れていない人も順位から外さない。ここは@で呼ぶ一覧ではなく順位の名乗りで、
    外すと1位が別人の名前に化ける(週のメンション一覧とは目的が違う)。"""
    session_id = make_session("streamer")
    _gifter(tmp_db, session_id, gift_builder, "fan00", _ts("2026-09-01 20:00"),
            9000, unique_id="")
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-09-01 21:00"), 5000)
    tmp_db.flush()

    day = _day_of(tmp_db)
    assert day["roster"][0]["unique_id"] == ""
    assert day["post_text"].split("\n")[1] == "🥇 FAN00 🥈 FAN01"


def test_day_without_gifts_stays_in_the_list(tmp_db, make_session, gift_builder):
    """Giftの無かった日も残す。抜くと「誰も投げなかった日」が「配信の無かった日」に
    化けるうえ、日の並びが週ごとに変わって位置で読めなくなる。"""
    session_id = make_session("streamer")
    _gifter(tmp_db, session_id, gift_builder, "fan00", _ts("2026-08-29 20:00"), 100)
    tmp_db.flush()

    quiet = _day_of(tmp_db, "2026-08-30")
    assert quiet["gifter_count"] == 0
    assert quiet["post_text"] == ""
    assert quiet["roster_text"] == ""
    assert quiet["roster"] == []


def test_day_labels_carry_the_time_of_day(tmp_db, make_session, gift_builder):
    """札の名乗りは窓の端を時刻付きで出す。日付だけだと未明(0〜7時)がどちらの日とも読める。
    見出しは窓が始まる日で名乗る(終わる日で名乗ると並びと日付が1日ずれて読める)。"""
    session_id = make_session("streamer")
    _gifter(tmp_db, session_id, gift_builder, "fan00", _ts("2026-09-01 20:00"), 100)
    tmp_db.flush()

    day = _day_of(tmp_db)
    assert day["start_label"] == "2026-09-01 07:00"
    assert day["end_label"] == "2026-09-02 07:00"
    assert day["title"] == "9月1日(火)"


def test_day_roster_is_capped_but_the_counts_are_not(
    tmp_db, make_session, gift_builder
):
    """顔ぶれは上限で切るが、人数とコインは全員ぶん。切った件数も名乗るので、画面が
    「これで全部」と読めることはない。"""
    session_id = make_session("streamer")
    for i in range(_MENTION_DAY_ROSTER + 3):
        _gifter(tmp_db, session_id, gift_builder, f"fan{i:02d}",
                _ts("2026-09-01 20:00"), 2000 - i)
    tmp_db.flush()

    day = _day_of(tmp_db)
    assert len(day["roster"]) == _MENTION_DAY_ROSTER
    assert day["roster_truncated"] == 3
    assert day["gifter_count"] == _MENTION_DAY_ROSTER + 3
    assert day["post_count"] == _MENTION_DAY_ROSTER + 3


def test_days_do_not_leak_into_the_neighbouring_week(
    tmp_db, make_session, gift_builder
):
    """選んだ週の日だけが並ぶ。隣の週のGiftが札に入ると、週の合計と札の合計が合わない。"""
    session_id = make_session("streamer")
    # 直前の週の最後(土曜 06:59)と、この週の最初(土曜 07:00)。
    _gifter(tmp_db, session_id, gift_builder, "fan00", _ts("2026-08-29 06:59"), 700)
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-08-29 07:00"), 300)
    tmp_db.flush()

    result = tmp_db.streamer_mention_week("streamer", "2026-08-29")
    days = {d["key"]: d["diamonds"] for d in result["days"]}
    assert "2026-08-28" not in days
    assert days["2026-08-29"] == 300
    assert sum(days.values()) == result["diamonds"] == 300


def test_no_sessions_returns_no_days(tmp_db):
    """配信が1本も無ければ日の一覧も空。画面はこの形をそのまま描く。"""
    assert tmp_db.streamer_mention_week("nobody")["days"] == []



# ===== 名前の省略形 =====


def _key(handle: str) -> str:
    """_gifterが作るuserのidentity_key。名寄せは数値user_id優先なのでそれと同じ物を返す。"""
    return f"73000000000000{handle[-2:]}"


def test_alias_replaces_the_name_in_the_pasted_text(
    tmp_db, make_session, gift_builder
):
    """省略形を付けた人は、貼る文面(トップ3貢献・顔ぶれ)でその名前になる。表示名の側は
    変えない —— 表は順位の根拠なので、省略形だけにすると🥇が誰なのか確かめられない。"""
    session_id = make_session("streamer")
    for i, coin in enumerate([5000, 4000, 3000]):
        _gifter(tmp_db, session_id, gift_builder, f"fan{i:02d}",
                _ts("2026-09-01 20:00"), coin)
    tmp_db.flush()
    tmp_db.set_user_alias(_key("fan00"), "視聴者A")

    day = _day_of(tmp_db)
    assert day["post_text"].split("\n")[1] == "🥇 視聴者A 🥈 FAN01 🥉 FAN02"
    assert day["roster_text"].split("\n")[0] == "1. 視聴者A　5,000"
    # 表は表示名のまま。省略形は別のfieldで添えるだけである。
    assert day["roster"][0]["nickname"] == "FAN00"
    assert day["roster"][0]["alias"] == "視聴者A"
    assert day["roster"][1]["alias"] == ""


def test_alias_is_the_same_person_across_days_and_weeks(
    tmp_db, make_session, gift_builder
):
    """省略形は人に付く。配信者にも週にも紐付かないので、別の日の同じ人にも効く。"""
    session_id = make_session("streamer")
    _gifter(tmp_db, session_id, gift_builder, "fan00", _ts("2026-08-31 20:00"), 5000)
    _gifter(tmp_db, session_id, gift_builder, "fan00", _ts("2026-09-01 20:00"), 4000)
    tmp_db.flush()
    tmp_db.set_user_alias(_key("fan00"), "視聴者A")

    for key in ("2026-08-31", "2026-09-01"):
        assert "🥇 視聴者A" in _day_of(tmp_db, key)["post_text"]


def test_empty_alias_removes_the_row_and_the_name_comes_back(
    tmp_db, make_session, gift_builder
):
    """空で確定したら外れる。空文字の行を残さないのは、付けた人を数えられなくなるため。"""
    session_id = make_session("streamer")
    _gifter(tmp_db, session_id, gift_builder, "fan00", _ts("2026-09-01 20:00"), 5000)
    tmp_db.flush()
    tmp_db.set_user_alias(_key("fan00"), "視聴者A")
    assert tmp_db.list_user_aliases() == {_key("fan00"): "視聴者A"}

    tmp_db.set_user_alias(_key("fan00"), "   ")
    assert tmp_db.list_user_aliases() == {}
    assert "🥇 FAN00" in _day_of(tmp_db)["post_text"]


def test_alias_is_trimmed_and_capped(tmp_db):
    """前後の空白と改行は畳む(貼る文面が1行で崩れる)。上限を超えたら受け取らない。"""
    assert tmp_db.set_user_alias("7300000000000000", " あき と\n")["alias"] == "あき と"
    with pytest.raises(ValueError):
        tmp_db.set_user_alias("7300000000000000", "あ" * (USER_ALIAS_MAX + 1))


def test_alias_refuses_keys_that_do_not_name_one_person(tmp_db):
    """'' や '(unknown)' は別人が畳まれた跡なので、省略形を付けさせない ——
    付けると、別人の名前として貼られる。"""
    for key in NON_IDENTITY_KEYS:
        with pytest.raises(ValueError):
            tmp_db.set_user_alias(key, "視聴者A")


def test_alias_max_is_named_by_the_payload(tmp_db, make_session, gift_builder):
    """入力欄の上限は応答から採る。画面へ数字を書くと、上限を動かした日に「入力できたのに
    保存で弾かれる欄」ができる。"""
    session_id = make_session("streamer")
    _gifter(tmp_db, session_id, gift_builder, "fan00", _ts("2026-09-01 20:00"), 5000)
    tmp_db.flush()
    assert tmp_db.streamer_mention_week("streamer")["alias_max"] == USER_ALIAS_MAX
    # 配信が1本も無いときの形にも同じfieldが要る(画面はどちらでも同じ枠を描く)。
    assert tmp_db.streamer_mention_week("nobody")["alias_max"] == USER_ALIAS_MAX


# ===== サブアカウントの統合 =====


def test_merged_accounts_are_one_row_in_the_day(tmp_db, make_session, gift_builder):
    """束ねた2つのアカウントは日の顔ぶれで1行になり、コインは足し合わされる。
    名乗りは主アカウントの物で、畳んだ数(accounts)を行が持つ。"""
    session_id = make_session("streamer")
    _gifter(tmp_db, session_id, gift_builder, "fan00", _ts("2026-09-01 20:00"), 3000)
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-09-01 21:00"), 2500)
    _gifter(tmp_db, session_id, gift_builder, "fan02", _ts("2026-09-01 22:00"), 4000)
    tmp_db.flush()
    # 束ねる前は3人で、1位は単独で4,000を投げたfan02である。
    day = _day_of(tmp_db)
    assert [(r["nickname"], r["diamonds"]) for r in day["roster"]] == [
        ("FAN02", 4000), ("FAN00", 3000), ("FAN01", 2500)]

    tmp_db.merge_users(_key("fan01"), _key("fan00"))

    day = _day_of(tmp_db)
    assert [(r["nickname"], r["diamonds"]) for r in day["roster"]] == [
        ("FAN00", 5500), ("FAN02", 4000)]
    assert day["roster"][0]["accounts"] == 2
    # 束ねていない人は1のまま。画面はこの数で印の有無を決める。
    assert day["roster"][1]["accounts"] == 1
    assert day["gifter_count"] == 2
    # 貼る文面も畳んだ順位で組み直る(1位が入れ替わる)。
    assert day["post_text"].split("\n")[1] == "🥇 FAN00 🥈 FAN02"


def test_merge_does_not_change_the_coins_of_the_week(
    tmp_db, make_session, gift_builder
):
    """畳むのは行の束ね方だけで、数えるGift eventは変わらない。日の合計は週の合計と
    一致したままで、週の一覧(＝@で呼ぶ相手)はアカウントごとに残る。"""
    session_id = make_session("streamer")
    _gifter(tmp_db, session_id, gift_builder, "fan00", _ts("2026-09-01 20:00"), 3000)
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-09-02 21:00"), 2500)
    tmp_db.flush()
    tmp_db.merge_users(_key("fan01"), _key("fan00"))

    result = tmp_db.streamer_mention_week("streamer", "2026-08-29")
    assert sum(d["diamonds"] for d in result["days"]) == result["diamonds"] == 5500
    # 週の一覧は畳まない。@IDはアカウントごとに別物なので、束ねると呼べない相手ができる。
    assert [g["nickname"] for g in result["gifters"]] == ["FAN00", "FAN01"]
    assert result["gifter_count"] == 2


def test_merged_account_takes_the_alias_of_the_primary(
    tmp_db, make_session, gift_builder
):
    """畳んだ行の省略形は主アカウントの物。サブ側に付いていた省略形では貼らない ——
    束ねたはずの人が別の名前で貼られる。"""
    session_id = make_session("streamer")
    _gifter(tmp_db, session_id, gift_builder, "fan00", _ts("2026-09-01 20:00"), 3000)
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-09-01 21:00"), 2500)
    tmp_db.flush()
    tmp_db.set_user_alias(_key("fan00"), "視聴者A")
    tmp_db.set_user_alias(_key("fan01"), "サブ")
    tmp_db.merge_users(_key("fan01"), _key("fan00"))

    day = _day_of(tmp_db)
    assert day["roster"][0]["alias"] == "視聴者A"
    assert day["post_text"].split("\n")[1] == "🥇 視聴者A"


def test_merge_flattens_instead_of_making_a_chain(tmp_db, make_session, gift_builder):
    """段は作らない。主が誰かへ束ねられていればその主へ寄せ、主だった人を移すときは
    その束ねの全員が付いて行く —— 置き去りにすると主の居ない束ねが残る。"""
    session_id = make_session("streamer")
    for handle in ("fan00", "fan01", "fan02"):
        _gifter(tmp_db, session_id, gift_builder, handle, _ts("2026-09-01 20:00"), 1000)
    tmp_db.flush()
    # fan02 → fan01 → fan00 の順に束ねても、行き先はすべて fan00 の1段になる。
    tmp_db.merge_users(_key("fan02"), _key("fan01"))
    tmp_db.merge_users(_key("fan01"), _key("fan00"))

    groups = tmp_db.list_user_merges()
    assert len(groups) == 1
    assert groups[0]["primary"]["identity_key"] == _key("fan00")
    assert sorted(m["identity_key"] for m in groups[0]["members"]) == [
        _key("fan01"), _key("fan02")]
    day = _day_of(tmp_db)
    assert [(r["nickname"], r["diamonds"], r["accounts"]) for r in day["roster"]] == [
        ("FAN00", 3000, 3)]


def test_unmerge_brings_the_account_back(tmp_db, make_session, gift_builder):
    """外したサブは元のアカウントとして顔ぶれへ戻る。同じ主の他のサブは残る。"""
    session_id = make_session("streamer")
    for handle, coin in (("fan00", 3000), ("fan01", 2500), ("fan02", 1000)):
        _gifter(tmp_db, session_id, gift_builder, handle, _ts("2026-09-01 20:00"), coin)
    tmp_db.flush()
    tmp_db.merge_users(_key("fan01"), _key("fan00"))
    tmp_db.merge_users(_key("fan02"), _key("fan00"))

    tmp_db.unmerge_user(_key("fan01"))

    day = _day_of(tmp_db)
    assert [(r["nickname"], r["diamonds"]) for r in day["roster"]] == [
        ("FAN00", 4000), ("FAN01", 2500)]
    assert [m["identity_key"] for m in tmp_db.list_user_merges()[0]["members"]] == [
        _key("fan02")]


def test_merges_are_named_in_the_payload(tmp_db, make_session, gift_builder):
    """束ねた相手は日の顔ぶれから消えるので、外す相手を選べるように応答が名乗る。
    配信が1本も無いときの形にも同じfieldが要る(画面はどちらでも同じ枠を描く)。"""
    session_id = make_session("streamer")
    _gifter(tmp_db, session_id, gift_builder, "fan00", _ts("2026-09-01 20:00"), 3000)
    _gifter(tmp_db, session_id, gift_builder, "fan01", _ts("2026-09-01 21:00"), 2500)
    tmp_db.flush()
    tmp_db.merge_users(_key("fan01"), _key("fan00"))

    result = tmp_db.streamer_mention_week("streamer", "2026-08-29")
    assert [g["primary"]["nickname"] for g in result["merges"]] == ["FAN00"]
    assert [m["nickname"] for m in result["merges"][0]["members"]] == ["FAN01"]
    assert tmp_db.streamer_mention_week("nobody")["merges"] == result["merges"]


def test_merge_of_an_unseen_account_keeps_the_name_unknown(tmp_db):
    """users表に行の無いkeyでも束ねは残る。名前を作らずに「取れていない」と名乗る ——
    作ると、別人の名前として画面に出る。"""
    tmp_db.merge_users("7300000000000099", "7300000000000098")
    group = tmp_db.list_user_merges()[0]
    assert group["primary"]["nickname"] == "(unknown)"
    assert group["members"][0]["identity_key"] == "7300000000000099"


def test_merge_refuses_keys_that_do_not_name_one_person(tmp_db):
    """'' や '(unknown)' は別人が畳まれた跡。束ねると無関係の人のコインが1人に積まれる。"""
    for key in NON_IDENTITY_KEYS:
        with pytest.raises(ValueError):
            tmp_db.merge_users(key, "7300000000000000")
        with pytest.raises(ValueError):
            tmp_db.merge_users("7300000000000000", key)


def test_merge_refuses_to_swap_a_pair_that_is_already_merged(tmp_db):
    """自分自身へは束ねられない。既に自分のサブになっている相手を主にする指定も断る ——
    主とサブが黙って入れ替わると、人が意図した向きなのか画面から読めない。"""
    with pytest.raises(ValueError):
        tmp_db.merge_users("7300000000000000", "7300000000000000")
    tmp_db.merge_users("7300000000000001", "7300000000000000")
    with pytest.raises(ValueError):
        tmp_db.merge_users("7300000000000000", "7300000000000001")
