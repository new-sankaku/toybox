"""週ぜんたいの俯瞰(``highlight_coverage``)—— 突き合わせを人が検証するための面。

1本ずつの照合結果は「このhighlightは何から出来ているか」しか言えない。照合が正しいかを
確かめるには逆向きの面が要る。見るのは5点。

(1) **主語がgiftである**こと。その週のgiftが1件ずつ並び、highlightのどこに出たかが付く。
(2) **1本も出てこないgiftを隠さない**こと。高額なのに ``hits`` が空の行こそが読みどころで、
    0件を落とすと「取りこぼしが無いように見える一覧」が出来上がる。ただし母集団は
    **対象gifter(週合計1,000💎)のgiftだけ**である —— 確かめるのはfileになる週の中身で、
    fileが作られない人のgiftは相手ではない。落とした件数は ``totals.offtarget`` が名乗る。
(3) 同じgiftが複数のhighlightに入れば ``hits`` が複数になること(重複排除の確認になる)。
(4) 突き合わせが **``gift_event_id`` の一致だけ**で、時刻の近さを使わないこと。照合を
    検証する面が、照合とは別の緩い規則で答えを作ってはいけない。
(5) 週の窓と対象gifterがメンション一覧と同じ経路から出ること(数が食い違えば道具にならない)。
"""
from datetime import datetime

import pytest

from tictok.store.streamers import MENTION_POST_MIN

# 2026-08-29(土)07:00 〜 2026-09-05(土)07:00 の週。**ローカル時刻で組む** —— 週の境界は
# ローカル時刻で切るので、UTC固定で書くと実行環境のtzでtestが意味を失う。
IN_WEEK = datetime(2026, 8, 30, 21, 0).timestamp()
BEFORE_WEEK = datetime(2026, 8, 29, 6, 0).timestamp()      # 土曜の朝7時より手前 = 前の週


def _gift(tmp_db, session_id, gift_builder, *, handle, at, diamonds, name="Rose",
          repeat_count=1):
    tmp_db.add_event(session_id, gift_builder(
        gift_name=name, diamonds=diamonds, at=at, repeat_count=repeat_count,
        user={"user_id": f"7300000000000{handle}", "unique_id": handle,
              "nickname": handle.upper(), "avatar": "", "fans_level": 0,
              "gifter_level": 0, "gifter_badge": "", "member_badge": ""}))


def _event_ids(tmp_db):
    """``{gift名: event id}``。gift演出はこのidで結ぶので、testも同じ鍵を使う。"""
    tmp_db.flush()
    with tmp_db._lock:
        rows = tmp_db._conn.execute(
            "SELECT id, gift_name FROM events WHERE kind = 'gift'").fetchall()
    return {row["gift_name"]: row["id"] for row in rows}


def _highlight(tmp_db, unique_id, filename):
    with tmp_db._lock:
        cursor = tmp_db._conn.execute(
            "INSERT INTO highlight_videos (unique_id, filename, path, status, created_at)"
            " VALUES (?, ?, ?, 'matched', 0)",
            (unique_id, filename, f"C:/{filename}"))
        tmp_db._conn.commit()
    return cursor.lastrowid


def _segment(tmp_db, highlight_id, idx, *, gift_event_id=None, start=0.0, end=6.0,
             media_start=100.0, gift_media_time=None, effect="[]", dropped=0,
             excluded=0, confidence="high", gifts=None, video_start=None):
    """gift演出を1件置く。``gift_event_id`` を渡すとgiftも1件付ける(``gifts`` で複数可)。

    giftは別表(``highlight_segment_gifts``)である —— gift演出1つが複数のgiftを持つので、
    1行に畳んだ形には戻せない。"""
    with tmp_db._lock:
        cursor = tmp_db._conn.execute(
            "INSERT INTO highlight_segments"
            " (highlight_id, idx, start, end, recording_id, media_start, votes, ratio,"
            "  corr, confidence, effect_json, dropped, excluded, video_start,"
            "  video_probed)"
            " VALUES (?, ?, ?, ?, 7, ?, 900, 250.0, 0.99, ?, ?, ?, ?, ?, ?)",
            (highlight_id, idx, start, end, media_start, confidence, effect,
             dropped, excluded, video_start, 1 if video_start is not None else 0))
        segment_id = cursor.lastrowid
        rows = list(gifts or [])
        if gift_event_id is not None:
            rows.append({"gift_event_id": gift_event_id,
                         "gift_media_time": gift_media_time})
        for order, gift in enumerate(rows):
            tmp_db._conn.execute(
                "INSERT INTO highlight_segment_gifts"
                " (segment_id, highlight_id, idx, gift_event_id, gift_media_time,"
                "  inside, is_primary, manual, excluded, dropped)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (segment_id, highlight_id, order, gift["gift_event_id"],
                 gift.get("gift_media_time"), gift.get("inside", 1),
                 1 if order == 0 else 0,
                 gift.get("manual", 0), gift.get("excluded", 0),
                 gift.get("dropped", dropped)))
        tmp_db._conn.commit()
    return segment_id


def _names(week) -> tuple:
    """(6000💎, 99💎, 別の人の99💎) のevent id。"""
    ids = week["ids"]
    return ids["Goal Highlight"], ids["LIVE On Air"], ids["Singing Mushroom"]


@pytest.fixture
def week(tmp_db, make_session, gift_builder):
    """1週ぶんのgiftと、そのうち1件だけがhighlightに入っている状態。

    fanA は週合計6,000💎(対象)、fanB は99💎(対象外)。前の週のgiftも1件置いて、窓の外が
    混ざらないことを確かめられるようにする。"""
    session_id = make_session("pomi")
    _gift(tmp_db, session_id, gift_builder, handle="01", at=IN_WEEK,
          diamonds=6000, name="Goal Highlight")
    _gift(tmp_db, session_id, gift_builder, handle="01", at=IN_WEEK + 600,
          diamonds=99, name="LIVE On Air")
    _gift(tmp_db, session_id, gift_builder, handle="02", at=IN_WEEK + 900,
          diamonds=99, name="Singing Mushroom")
    _gift(tmp_db, session_id, gift_builder, handle="01", at=BEFORE_WEEK,
          diamonds=5000, name="Flying Jets")
    return {"session_id": session_id, "ids": _event_ids(tmp_db)}


# ===== giftが主語であること =====

def test_出てこないgiftも必ず並ぶ(tmp_db, week):
    """**0件を隠さない。** 高額なのに1本も無いgiftが並ぶことがこの面の価値である ——
    TikTokが選ばなかったのか照合が取りこぼしたのかを、人はそこから確かめる。"""
    goal, on_air, mushroom = _names(week)
    highlight_id = _highlight(tmp_db, "pomi", "hl1.mp4")
    _segment(tmp_db, highlight_id, 0, gift_event_id=goal)

    result = tmp_db.highlight_coverage("pomi", "", 0)
    by_event = {item["event_id"]: item for item in result["items"]}
    # 窓の中の**対象gifterの**2件が並ぶ。当たったのは1件だけで、残る1件は空listのまま
    # 残る(mushroom は週合計99💎の人のgiftなので、そもそもこの面に出ない)。
    assert sorted(by_event) == sorted([goal, on_air])
    assert len(by_event[goal]["hits"]) == 1
    assert by_event[on_air]["hits"] == []
    assert mushroom not in by_event
    assert result["totals"]["gifts"] == 2
    assert result["totals"]["matched"] == 1
    assert result["totals"]["diamonds"] == 6000 + 99
    assert result["totals"]["matched_diamonds"] == 6000


def test_まとめ投げは合計ではなく単価で切る(tmp_db, week, make_session, gift_builder):
    """**30💎を9個(合計270💎)はこの面に並べない。** 演出が出るのは1発ごとの単価で決まる。

    合計で判定していた頃は、この行が「270💎なのに1本も出ていない」として並び、人が
    照合の取りこぼしとして追いかける先になっていた —— 実際には演出そのものが無い。"""
    _gift(tmp_db, week["session_id"], gift_builder, handle="01", at=IN_WEEK + 1200,
          diamonds=270, name="Rose Combo", repeat_count=9)
    tmp_db.flush()
    result = tmp_db.highlight_coverage("pomi", "", 98)
    assert "Rose Combo" not in {item["gift_name"] for item in result["items"]}
    # **黙って消さない。** 落ちた件数は名乗る(数が合わないと、人はまず数を疑う)。
    assert result["totals"]["combo_below_min"] == 1
    # 単価が下限を越えるまとめ投げは残り、単価も添える。
    _gift(tmp_db, week["session_id"], gift_builder, handle="01", at=IN_WEEK + 1500,
          diamonds=1194, name="Hearts", repeat_count=6)
    tmp_db.flush()
    again = tmp_db.highlight_coverage("pomi", "", 98)
    hearts = next(i for i in again["items"] if i["gift_name"] == "Hearts")
    assert (hearts["diamonds"], hearts["unit_diamonds"], hearts["gift_count"])         == (1194, 199, 6)


def test_前の週のgiftは混ざらない(tmp_db, week):
    """窓はメンション一覧と同じ土曜7時〜土曜7時。ここがずれると配信者画面と数が合わず、
    どちらが正しいのかで人が止まる。"""
    result = tmp_db.highlight_coverage("pomi", "2026-08-29", 0)
    assert result["week"] == "2026-08-29"
    assert week["ids"]["Flying Jets"] not in {item["event_id"] for item in result["items"]}
    assert result["start_label"].endswith("07:00")
    assert result["post_min"] == MENTION_POST_MIN


def test_下限はgift1件あたり_0は全件(tmp_db, week):
    """``min_diamonds`` はgift 1件あたりの下限。0は「下限なし」で、未指定とは別の意味。"""
    # 0でも対象gifterの2件だけ(対象外の1件は下限とは別の規則で外れている)。
    assert len(tmp_db.highlight_coverage("pomi", "", 0)["items"]) == 2
    assert len(tmp_db.highlight_coverage("pomi", "", 98)["items"]) == 2
    high = tmp_db.highlight_coverage("pomi", "", 199)
    assert [item["diamonds"] for item in high["items"]] == [6000]
    assert high["min_diamonds"] == 199


def test_対象外のgifterのgiftは並ばない(tmp_db, week):
    """週合計が1,000💎に届かない人のgiftは表に出さない(利用者の指定)。

    確かめる相手は「fileになる週」の中身である。fileが作られない人のgiftまで並べると、
    人が1件ずつ読み下す行が週の全gifterぶんへ膨らむ。**黙って消さない** —— 単価の下限は
    越えていたのに外れた件数は ``totals.offtarget`` が名乗る。
    """
    result = tmp_db.highlight_coverage("pomi", "", 0)
    by_event = {item["event_id"]: item for item in result["items"]}
    goal, _on_air, mushroom = _names(week)
    assert by_event[goal]["target"] is True and by_event[goal]["week_diamonds"] == 6099
    assert mushroom not in by_event
    assert result["totals"]["offtarget"] == 1
    # 並んだ行はすべて対象gifterのもの。
    assert all(item["target"] is True for item in result["items"])
    assert result["totals"]["target_gifters"] == 1
    # 人数は**その週にgiftを投げた人**の数で、表に並んだ人の数ではない。ここが items から
    # の数え直しに戻ると、target_gifters と必ず同じ数になって「何人のうち何人がfileに
    # なるのか」が読めなくなる。
    assert result["totals"]["gifters"] == 2


def test_高額な順に並ぶ(tmp_db, week, gift_builder):
    """読みどころは「高額なのに1本も無い行」なので、額の順に並べる。"""
    # 同額の並びを見るための3件目。対象gifter(fanA)のgiftでなければ表に出ない。
    _gift(tmp_db, week["session_id"], gift_builder, handle="01", at=IN_WEEK + 1800,
          diamonds=99, name="Hand Heart")
    tmp_db.flush()
    items = tmp_db.highlight_coverage("pomi", "", 0)["items"]
    assert [item["diamonds"] for item in items] == [6000, 99, 99]
    assert items[1]["time"] < items[2]["time"]   # 同額は時刻順


# ===== 当たりの数え方 =====

def test_同じgiftが複数のhighlightに入れば当たりも複数(tmp_db, week):
    """TikTokは同じ瞬間を別のhighlightにも入れる。1へ丸めると重複排除を確かめられない。"""
    goal = week["ids"]["Goal Highlight"]
    first = _highlight(tmp_db, "pomi", "hl1.mp4")
    second = _highlight(tmp_db, "pomi", "hl2.mp4")
    _segment(tmp_db, first, 0, gift_event_id=goal)
    _segment(tmp_db, second, 0, gift_event_id=goal, start=12.0, end=18.0)

    result = tmp_db.highlight_coverage("pomi", "", 0)
    hits = next(i for i in result["items"] if i["event_id"] == goal)["hits"]
    assert [(h["filename"], h["segment_start"]) for h in hits] == [
        ("hl1.mp4", 0.0), ("hl2.mp4", 12.0)]
    # 行は1つ、当たりは2つ。totalsはその両方を名乗る。
    assert result["totals"]["matched"] == 1 and result["totals"]["hits"] == 2


def test_自分の見せ場の当たりが代表になる(tmp_db, week):
    """同席しただけの当たりが先頭に来てはいけない。

    画面は先頭の当たりを行の代表として使い、区間・確信度・NGの対象をそこから採る。
    SQLの並び(highlight_id順)のままでは代表が偶然で決まり、実測では1件のgiftが3本へ
    入って先頭だけが同席、残る2本が自分の見せ場という行が丸ごと「同席しただけ」として
    沈んだ。
    """
    goal = week["ids"]["Goal Highlight"]
    other = week["ids"]["LIVE On Air"]
    # id の小さい方(= SQLの並びで先頭)を同席の当たりにする。
    passenger = _highlight(tmp_db, "pomi", "hl1.mp4")
    own = _highlight(tmp_db, "pomi", "hl2.mp4")
    _segment(tmp_db, passenger, 0,
             gifts=[{"gift_event_id": other}, {"gift_event_id": goal}])
    _segment(tmp_db, own, 0, gift_event_id=goal, start=12.0, end=18.0)

    hits = next(i for i in tmp_db.highlight_coverage("pomi", "", 0)["items"]
                if i["event_id"] == goal)["hits"]
    assert [(h["filename"], h["is_primary"]) for h in hits] == [
        ("hl2.mp4", True), ("hl1.mp4", False)]


def _goal_hits(tmp_db, goal):
    return next(i for i in tmp_db.highlight_coverage("pomi", "", 0)["items"]
                if i["event_id"] == goal)["hits"]


def _choose(tmp_db, hit):
    tmp_db.update_highlight_segment_gift(
        hit["highlight_id"], hit["segment_id"], hit["gift_row_id"], {"chosen": True})


def test_人が選んだ当たりが代表になる(tmp_db, week):
    """**機械の順位より人の選択が先。**

    見せ場も主も「そのgiftのアニメが映っているのはどれか」を機械が当てる代用でしかない。
    実測(Whale diving 2,150💎 / おニャンコ🐢💤)では3本すべてで同席と判定され、本人のアニメが
    映っている11.1秒の1本も後ろへ回っていた。画面は先頭の当たりを代表として使うので、人が
    選べない限りその行から本人のアニメへは辿り着けない。
    """
    goal = week["ids"]["Goal Highlight"]
    other = week["ids"]["LIVE On Air"]
    own = _highlight(tmp_db, "pomi", "hl1.mp4")
    passenger = _highlight(tmp_db, "pomi", "hl2.mp4")
    _segment(tmp_db, own, 0, gift_event_id=goal)
    # 同席(主は別人)だが、後続のアニメまで入っている長い方。
    _segment(tmp_db, passenger, 0, start=12.0, end=23.1,
             gifts=[{"gift_event_id": other}, {"gift_event_id": goal}])

    assert [h["filename"] for h in _goal_hits(tmp_db, goal)] == ["hl1.mp4", "hl2.mp4"]
    _choose(tmp_db, next(h for h in _goal_hits(tmp_db, goal)
                         if h["filename"] == "hl2.mp4"))
    assert [(h["filename"], h["chosen"]) for h in _goal_hits(tmp_db, goal)] == [
        ("hl2.mp4", True), ("hl1.mp4", False)]


def test_選べる当たりは1本だけ_highlightを跨いで落とす(tmp_db, week):
    """主(``is_primary``)はgift演出の中で1つだが、**選んだ1本はhighlightを跨いで1つ**である。

    落とす相手をgift演出の中に限ると、2本が「この1本を使う」と名乗ったまま残り、書き出しが
    どちらを採るかは行の並び順で決まる。"""
    goal = week["ids"]["Goal Highlight"]
    first = _highlight(tmp_db, "pomi", "hl1.mp4")
    second = _highlight(tmp_db, "pomi", "hl2.mp4")
    _segment(tmp_db, first, 0, gift_event_id=goal)
    _segment(tmp_db, second, 0, gift_event_id=goal, start=12.0, end=18.0)

    _choose(tmp_db, next(h for h in _goal_hits(tmp_db, goal)
                         if h["filename"] == "hl2.mp4"))
    _choose(tmp_db, next(h for h in _goal_hits(tmp_db, goal)
                         if h["filename"] == "hl1.mp4"))
    assert [(h["filename"], h["chosen"]) for h in _goal_hits(tmp_db, goal)] == [
        ("hl1.mp4", True), ("hl2.mp4", False)]


def test_時刻の近さでは結ばない(tmp_db, week):
    """突き合わせは ``gift_event_id`` の一致だけ。照合を検証する面が別の(緩い)規則で
    答えを作ると、両方が間違っているときに一致して見える。"""
    goal, on_air, _mushroom = _names(week)
    highlight_id = _highlight(tmp_db, "pomi", "hl1.mp4")
    # media軸ではこのgift演出の窓が両方のgiftを覆っていても、指すのは1件だけである。
    _segment(tmp_db, highlight_id, 0, gift_event_id=on_air, media_start=0.0,
             gift_media_time=1.0, start=0.0, end=3600.0)

    result = tmp_db.highlight_coverage("pomi", "", 0)
    by_event = {item["event_id"]: item for item in result["items"]}
    assert by_event[on_air]["hits"] and by_event[goal]["hits"] == []


def test_再照合で消えたgift演出は当たりにしない(tmp_db, week):
    """``dropped`` は「前回は在ったが今回の照合では出なくなった」印である。並べると、
    既に否定された対応が検証の面で生き続ける。"""
    goal = week["ids"]["Goal Highlight"]
    highlight_id = _highlight(tmp_db, "pomi", "hl1.mp4")
    _segment(tmp_db, highlight_id, 0, gift_event_id=goal, dropped=1, excluded=1)
    result = tmp_db.highlight_coverage("pomi", "", 0)
    assert result["totals"]["matched"] == 0
    # 人が外しただけ(excluded)のgift演出は残す —— 外した判断そのものを人が見直せるように。
    _segment(tmp_db, highlight_id, 1, gift_event_id=goal, excluded=1)
    again = tmp_db.highlight_coverage("pomi", "", 0)
    hits = next(i for i in again["items"] if i["event_id"] == goal)["hits"]
    assert len(hits) == 1 and hits[0]["excluded"] is True


def test_giftの位置と生の演出区間を添える(tmp_db, week):
    """``at`` は **giftそのもの**の位置(画面が飛ぶ先・代表frameを採る秒)であって、
    gift演出の頭ではない。giftはgift演出の頭に在るとは限らず(実測1.2秒後ろ)、gift演出の頭を返すと
    飛び先が毎回gift演出の頭になり、しかも「だいたい合っている」ので誰も気付かない。
    録画が当たっていないgift演出では ``at`` は None —— gift演出の頭で代用すると、位置が判って
    いるように見える数字が出る。"""
    goal, on_air, _mushroom = _names(week)
    highlight_id = _highlight(tmp_db, "pomi", "hl1.mp4")
    _segment(tmp_db, highlight_id, 0, gift_event_id=goal, start=21.0, end=27.0,
             media_start=378.1, gift_media_time=380.6, effect="[[24.0, 26.0]]")
    _segment(tmp_db, highlight_id, 1, gift_event_id=on_air, start=27.0, end=30.0,
             media_start=None, gift_media_time=None)

    by_event = {item["event_id"]: item
                for item in tmp_db.highlight_coverage("pomi", "", 0)["items"]}
    hit = by_event[goal]["hits"][0]
    # gift演出の頭は21.0、giftは録画のmedia軸で2.5秒後ろなので 23.5。
    assert hit["at"] == 23.5
    assert hit["segment_start"] == 21.0 and hit["segment_end"] == 27.0
    # 生の演出区間は診断用に残す。**「演出があるか」の真偽値は返さない** —— 差分による
    # 検出は実測で両方向に無力で(7本のgift 47件で当たり0件)、真偽値を返せばいずれ誰かが
    # 信じる。演出が映っているかは代表frameの2枚並べで人が見る。
    assert hit["effect"] == [[24.0, 26.0]]
    assert "has_effect" not in hit and "segment_has_effect" not in hit
    assert by_event[on_air]["hits"][0]["at"] is None
    assert by_event[on_air]["hits"][0]["segment_start"] == 27.0
    assert by_event[on_air]["hits"][0]["effect"] == []


# ===== 週のhighlightの内訳 =====

def test_週のhighlightはgiftで割り当てる(tmp_db, week):
    """1本のhighlightはLIVE replay 1本 = 配信1回から作られるので、週は1つに定まる。
    giftの付いていないgift演出も、そのhighlightの内訳としては数える(演出の音が配信の音を
    覆う区間は票が立たないので、0にはならないのが普通である)。"""
    goal = week["ids"]["Goal Highlight"]
    mine = _highlight(tmp_db, "pomi", "hl1.mp4")
    _segment(tmp_db, mine, 0, gift_event_id=goal)
    _segment(tmp_db, mine, 1, gift_event_id=None, start=6.0, end=12.0)
    # まだ照合していないhighlight。どの週へも割り当てない(名乗る根拠が無い)。
    other = _highlight(tmp_db, "pomi", "hl2.mp4")
    _segment(tmp_db, other, 0, gift_event_id=None)

    totals = tmp_db.highlight_coverage("pomi", "", 0)["totals"]
    assert totals["highlights"] == 1
    assert totals["segments"] == 2
    assert totals["unidentified"] == 1


def test_別の配信者のhighlightは入らない(tmp_db, week):
    goal = week["ids"]["Goal Highlight"]
    theirs = _highlight(tmp_db, "wicha", "hl9.mp4")
    _segment(tmp_db, theirs, 0, gift_event_id=goal)
    result = tmp_db.highlight_coverage("pomi", "", 0)
    assert result["totals"]["matched"] == 0 and result["totals"]["highlights"] == 0


def test_配信の記録が無ければ空の形で返す(tmp_db, week):
    """週そのものが1つも決まらない配信者。空listではなく「週が無い」形で返す。"""
    result = tmp_db.highlight_coverage("nobody", "", 0)
    assert result["items"] == [] and result["week"] == "" and result["weeks"] == []
    assert result["totals"]["gifts"] == 0
    # 空でも下限と対象の下限は名乗る —— 画面が「何を条件に0件なのか」を出せるように。
    assert result["post_min"] == MENTION_POST_MIN and result["min_diamonds"] == 0
    assert result["totals"]["offtarget"] == 0


def test_演出を持つ階層かを行ごとに名乗る(tmp_db, week):
    """出てこないgiftを「演出が無いので当然」と「演出があるのに採られていない = 要調査」に
    切り分ける線。**coinを代理指標にした推定で実測ではない**(doc/HIGHLIGHT_MATCH.md)。

    ``min_diamonds`` を0にして全giftを並べても、行ごとの判断がこの線を失わないこと。"""
    result = tmp_db.highlight_coverage("pomi", "", 0)
    assert result["effect_floor"] == 98
    by_event = {item["event_id"]: item for item in result["items"]}
    goal, on_air, _mushroom = _names(week)
    assert by_event[goal]["effect_expected"] is True      # 6000💎
    assert by_event[on_air]["effect_expected"] is True    # 99💎 は演出を持つ階層である
    # 対象gifterの2件だけを数える(mushroom はこの面の母集団に入らない)。
    assert result["totals"]["effect_expected"] == 2
    assert result["totals"]["effect_expected_matched"] == 0


def test_当たりの秒はgiftの位置であってgift演出の頭ではない(tmp_db, week):
    """``gift_position`` は計算する場所を1つにするための関数。読む側が各自で書くと、
    いつか片方だけがgift演出の頭へ落ちて、それらしい別の場面が並ぶ(飛び先も代表frameも)。"""
    from tictok.store.highlights import gift_position

    assert gift_position(21.0, 378.1, 380.6) == 23.5
    # 実測の値(7312.50のgift演出に対しgiftは7313.67)。1.2秒後ろで、頭ではない。
    assert gift_position(0.0, 7312.50, 7313.67) == 1.17
    assert gift_position(21.0, None, 380.6) is None
    assert gift_position(21.0, 378.1, None) is None


def test_gift演出の一覧もgiftの位置を名乗る(tmp_db, week):
    """``highlight_segments`` と coverage の ``hits`` が同じ秒を返すこと。片方だけが
    gift演出の頭を返すと、同じgiftが画面によって別の場所を指す。"""
    goal = week["ids"]["Goal Highlight"]
    highlight_id = _highlight(tmp_db, "pomi", "hl1.mp4")
    _segment(tmp_db, highlight_id, 0, gift_event_id=goal, start=21.0, end=27.0,
             media_start=378.1, gift_media_time=380.6)

    listed = tmp_db.highlight_segments(highlight_id)[0]
    hit = next(i for i in tmp_db.highlight_coverage("pomi", "", 0)["items"]
               if i["event_id"] == goal)["hits"][0]
    # ``at`` はgift 1件ずつが名乗る(gift演出は複数のgiftを持つので、gift演出には1つに決まらない)。
    assert listed["gifts"][0]["at"] == hit["at"] == 23.5
    assert listed["primary"]["gift_event_id"] == goal


# ===== 書き出しの下見に渡す母集団 =====

def test_週のgiftを母集団として引ける(tmp_db, week, gift_builder):
    """``highlight_week_gifts`` は「その週に載るはずのgift全部」を、highlightに出ているか
    の印つきで返す。**選んだhighlightで絞らない** —— 「別のhighlightには在るが今回は
    選んでいない」と「どのhighlightにも無い」は人にとって別の話である。

    並べる規則(週の窓・単価の下限)は検証の面と同じにする。2つの面で母集団が食い違うと、
    人はまずどちらが正しいのかで止まる。**対象gifter(週合計)では絞らない**のはここだけの
    約束である —— 誰のfileを作るかを決めるのは ``plan_exports`` 側で、ここは母集団を渡す。"""
    goal, on_air, mushroom = _names(week)
    highlight_id = _highlight(tmp_db, "pomi", "hl1.mp4")
    _segment(tmp_db, highlight_id, 0, gift_event_id=goal)

    ledger = tmp_db.highlight_week_gifts("pomi", "", 0)
    by_event = {g["gift_event_id"]: g for g in ledger["gifts"]}
    assert sorted(by_event) == sorted([goal, on_air, mushroom])
    assert by_event[goal]["highlight_ids"] == [highlight_id]
    assert by_event[on_air]["highlight_ids"] == []
    # 下限は検証の面と同じく**単価**で切る。
    _gift(tmp_db, week["session_id"], gift_builder, handle="01", at=IN_WEEK + 1200,
          diamonds=270, name="Rose Combo", repeat_count=9)
    tmp_db.flush()
    high = tmp_db.highlight_week_gifts("pomi", "", 98)
    assert "Rose Combo" not in {g["gift_name"] for g in high["gifts"]}
    assert [g["gift_name"] for g in high["gifts"]] == ["Goal Highlight",
                                                       "LIVE On Air",
                                                       "Singing Mushroom"]
