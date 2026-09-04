"""highlightが「いつの週の素材か」(``list_highlights`` の ``week`` / ``weeks``)。

出力の面は週で対象gifterを決めるのに、素材のhighlightは毎回手で選ばせていた。**期間を
指定してある以上、その期間の素材は選ばれていなければならない。** そのために台帳の行が週を
名乗る。見るのは4点。

(1) 週は**当たったgiftのeventの時刻**から決まること。highlightは自分の時刻を持たない ——
    fileの日付は落とした日で、配信の日ではない。
(2) 区切りがメンション一覧と同じ**土曜7時**であること。ここがずれると、境目の配信だけが
    出力の週選択から黙って外れる。
(3) 土曜7時を跨いだ配信は**両方の週**を名乗ること(多い方へ丸めない)。丸めると跨がれた側で
    「この週の素材が無い」と見える。
(4) giftが1件も当たっていない本は**どの週にも属さない**こと。置き場に在るだけの素材を
    「この週の物」と名乗る根拠が無い。
"""
from datetime import datetime

import pytest

# 2026-08-29(土)07:00 〜 2026-09-05(土)07:00 の週。**ローカル時刻で組む** —— 週の境界は
# ローカル時刻で切るので、UTC固定で書くと実行環境のtzでtestが意味を失う。
THIS_WEEK = datetime(2026, 8, 30, 21, 0).timestamp()
PREV_WEEK = datetime(2026, 8, 29, 6, 0).timestamp()        # 土曜の朝7時より手前 = 前の週
THIS_WEEK_KEY = "2026-08-29"
PREV_WEEK_KEY = "2026-08-22"


def _gift(tmp_db, session_id, gift_builder, *, handle, at, diamonds, name):
    tmp_db.add_event(session_id, gift_builder(
        gift_name=name, diamonds=diamonds, at=at, repeat_count=1,
        user={"user_id": f"7300000000000{handle}", "unique_id": handle,
              "nickname": handle.upper(), "avatar": "", "fans_level": 0,
              "gifter_level": 0, "gifter_badge": "", "member_badge": ""}))


def _event_ids(tmp_db) -> dict:
    tmp_db.flush()
    with tmp_db._lock:
        rows = tmp_db._conn.execute(
            "SELECT id, gift_name FROM events WHERE kind = 'gift'").fetchall()
    return {row["gift_name"]: row["id"] for row in rows}


def _highlight(tmp_db, unique_id, filename) -> int:
    with tmp_db._lock:
        cursor = tmp_db._conn.execute(
            "INSERT INTO highlight_videos (unique_id, filename, path, status, created_at)"
            " VALUES (?, ?, ?, 'matched', 0)",
            (unique_id, filename, f"C:/{filename}"))
        tmp_db._conn.commit()
    return cursor.lastrowid


def _segment(tmp_db, highlight_id, idx, *, gift_event_id=None, dropped=0,
             gift_dropped=0) -> int:
    with tmp_db._lock:
        cursor = tmp_db._conn.execute(
            "INSERT INTO highlight_segments"
            " (highlight_id, idx, start, end, recording_id, media_start, votes, ratio,"
            "  corr, confidence, effect_json, dropped)"
            " VALUES (?, ?, ?, ?, 7, 100.0, 900, 250.0, 0.99, 'high', '[]', ?)",
            (highlight_id, idx, idx * 6.0, idx * 6.0 + 6.0, dropped))
        segment_id = cursor.lastrowid
        if gift_event_id is not None:
            tmp_db._conn.execute(
                "INSERT INTO highlight_segment_gifts"
                " (segment_id, highlight_id, idx, gift_event_id, inside, is_primary,"
                "  manual, excluded, dropped)"
                " VALUES (?, ?, 0, ?, 1, 1, 0, 0, ?)",
                (segment_id, highlight_id, gift_event_id, gift_dropped))
        tmp_db._conn.commit()
    return segment_id


@pytest.fixture
def gifts(tmp_db, make_session, gift_builder):
    """今週2件・前の週1件のgift。どれも同じ配信者(pomi)へ投げられている。"""
    session_id = make_session("pomi")
    _gift(tmp_db, session_id, gift_builder, handle="01", at=THIS_WEEK,
          diamonds=6000, name="Goal Highlight")
    _gift(tmp_db, session_id, gift_builder, handle="01", at=THIS_WEEK + 600,
          diamonds=999, name="LIVE On Air")
    _gift(tmp_db, session_id, gift_builder, handle="01", at=PREV_WEEK,
          diamonds=5000, name="Flying Jets")
    return _event_ids(tmp_db)


def _by_name(tmp_db) -> dict:
    return {item["filename"]: item for item in tmp_db.list_highlights("pomi")}


def test_週は当たったgiftの時刻から決まる(tmp_db, gifts):
    """**fileの日付ではない。** highlightは自分の時刻を持たないので、当たったgiftの
    eventの時刻だけが「いつの素材か」を言える。"""
    this_week = _highlight(tmp_db, "pomi", "hl_this.mp4")
    _segment(tmp_db, this_week, 0, gift_event_id=gifts["Goal Highlight"])
    prev_week = _highlight(tmp_db, "pomi", "hl_prev.mp4")
    _segment(tmp_db, prev_week, 0, gift_event_id=gifts["Flying Jets"])

    rows = _by_name(tmp_db)
    assert rows["hl_this.mp4"]["week"] == THIS_WEEK_KEY
    assert rows["hl_prev.mp4"]["week"] == PREV_WEEK_KEY
    # 区切りはメンション一覧と同じ土曜7時。名乗りもあちらと同じ書式で、画面はこれを出す。
    assert rows["hl_this.mp4"]["week_label"].endswith("07:00")


def test_土曜7時を跨いだ本は両方の週を名乗る(tmp_db, gifts):
    """**多い方へ丸めない。** 丸めると、跨がれた側の週で「この週の素材が無い」と見える。
    代表(``week``)はgiftの多い方だが、``weeks`` には両方が残る。"""
    highlight_id = _highlight(tmp_db, "pomi", "hl_cross.mp4")
    _segment(tmp_db, highlight_id, 0, gift_event_id=gifts["Flying Jets"])
    _segment(tmp_db, highlight_id, 1, gift_event_id=gifts["Goal Highlight"])
    _segment(tmp_db, highlight_id, 2, gift_event_id=gifts["LIVE On Air"])

    row = _by_name(tmp_db)["hl_cross.mp4"]
    assert row["weeks"] == [PREV_WEEK_KEY, THIS_WEEK_KEY]
    assert row["week"] == THIS_WEEK_KEY


def test_giftの当たっていない本は週を名乗らない(tmp_db, gifts):
    """置き場に在るだけの素材を「この週の物」と名乗る根拠が無い。推測で埋めない。"""
    highlight_id = _highlight(tmp_db, "pomi", "hl_bare.mp4")
    _segment(tmp_db, highlight_id, 0)

    row = _by_name(tmp_db)["hl_bare.mp4"]
    assert (row["week"], row["week_label"], row["weeks"]) == ("", "", [])


def test_前回の照合の残りは数えない(tmp_db, gifts):
    """``dropped`` は前回の照合に在って今回は出なくなった行で、**今の照合が指す場所を
    持たない**。これを数えると、既に否定された対応が週の割り当てを動かす。"""
    highlight_id = _highlight(tmp_db, "pomi", "hl_dropped.mp4")
    _segment(tmp_db, highlight_id, 0, gift_event_id=gifts["Goal Highlight"])
    _segment(tmp_db, highlight_id, 1, gift_event_id=gifts["Flying Jets"],
             dropped=1, gift_dropped=1)

    row = _by_name(tmp_db)["hl_dropped.mp4"]
    assert row["weeks"] == [THIS_WEEK_KEY]
