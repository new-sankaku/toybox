"""giftごとの切り出し範囲(``highlight_segment_gifts.cut_start`` / ``cut_end``)のtest。

**1つのgift演出に別人のgiftが複数入る。** 本番DBの実測では gift 49件のうち27件が「gift 2件
以上のgift演出」に載っており、うち **19件はgifterが2人以上**のgift演出だった。6.0秒のgift演出に
あきと6000💎(1.17s) / おニャンコ999💎(4.55s) / るきしろ99💎(0.32s) の3人、という形が3本
ある。

出力は **gifterごとに1本**なので、切り出す範囲がgift演出単位だと:

- 同じ6秒が3人ぶんのfileへ**同じ形で**入る
- 1人の行で範囲を詰めると、他の2人のfileまで一緒に動く
- 1人の行でNGを押すと、**他の2人の見せ場まで消える**

``cut_start`` / ``cut_end`` が **NULL** であることは「まだ触っていない」という意味であって、
既定値ではない。gift演出の値をDBへcopyして埋めると、再照合でgift演出が動いたときに、人が一度も
触っていないgiftの窓だけが古い場所へ取り残される。

fixtureとhelperは :mod:`tests.test_highlight_api` と共有する —— 同じ台帳を相手にする以上、
gift演出とgiftの組み立て方を2箇所に書くと、片方だけが表の変更に追従して黙って食い違う。
"""

import pytest  # noqa: F401  (fixtureの解決に要る)

from tests.test_server import (  # noqa: F401  (fixtureとして使う)
    client, make_srv_recording, server,
)
from tests.test_highlight_api import (  # noqa: F401  (fixtureとして使う)
    clean_highlights, highlight_roots, matched_highlight,
    _fake_result, _gift, _segment,
)


def _segment_of(client, highlight_id):
    return client.get(f"/api/highlights/{highlight_id}").json()["segments"][0]


def _gift_url(highlight_id, segment, gift):
    return (f"/api/highlights/{highlight_id}/segments/{segment['id']}"
            f"/gifts/{gift['id']}")


def test_the_cut_is_per_gift_not_per_segment(client, matched_highlight,
                                             make_srv_recording):
    """同じgift演出の2件が、**別々の範囲**を持てること。

    片方を詰めても、もう片方はgift演出の窓のまま動かない —— これが持てないと、6秒に3人載って
    いるgift演出で誰か1人に合わせた範囲が3人ぶんのfileへ同じ形で入る。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 10.0, 16.0, recording_id=recording_id, media_start=100.0,
                 gifts=[_gift(event_id=111, media_time=101.2, name="Guardian"),
                        _gift(event_id=222, media_time=104.5, name="Rose",
                              primary=False)]),
    ]))
    segment = _segment_of(client, highlight_id)
    guardian = next(g for g in segment["gifts"] if g["gift_name"] == "Guardian")
    rose = next(g for g in segment["gifts"] if g["gift_name"] == "Rose")
    # 触っていないgiftもgift演出の窓を**必ず名乗る**。画面に「無ければgift演出の窓」を組み立て
    # させると、いつか片方だけがgift演出の窓のままになり、詰めた区間が元の長さで出力へ入る。
    assert (guardian["cut_start"], guardian["cut_end"]) == (10.0, 16.0)
    assert guardian["cut_own"] is False and rose["cut_own"] is False

    reply = client.patch(_gift_url(highlight_id, segment, guardian),
                         json={"cut_start": 10.5, "cut_end": 13.0})
    assert reply.status_code == 200
    gifts = {g["gift_name"]: g for g in reply.json()["segment"]["gifts"]}
    assert (gifts["Guardian"]["cut_start"], gifts["Guardian"]["cut_end"]) == (10.5, 13.0)
    assert gifts["Guardian"]["cut_own"] is True
    # **もう片方は動かない。**
    assert (gifts["Rose"]["cut_start"], gifts["Rose"]["cut_end"]) == (10.0, 16.0)
    assert gifts["Rose"]["cut_own"] is False
    # gift演出そのものの窓も動かない(区間はgiftの持ち物である)。
    assert reply.json()["segment"]["start"] == 10.0
    assert reply.json()["segment"]["end"] == 16.0


def test_a_gift_cut_must_stay_inside_the_segment(client, matched_highlight,
                                                 make_srv_recording):
    """gift演出の外は**まったく無関係な場面**である(montageなので、隣は別の時刻のgift演出)。

    黙って丸めずに400で断る —— 丸めて受けると、画面には打った値が残って出力だけが別の
    場所を切る。しかも数字は出るので誰も気付かない。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 10.0, 16.0, recording_id=recording_id, media_start=100.0,
                 gifts=[_gift(event_id=111, media_time=101.2)]),
    ]))
    segment = _segment_of(client, highlight_id)
    url = _gift_url(highlight_id, segment, segment["gifts"][0])

    out = client.patch(url, json={"cut_start": 8.0, "cut_end": 13.0})
    assert out.status_code == 400 and "gift演出の中" in out.json()["detail"]
    over = client.patch(url, json={"cut_start": 12.0, "cut_end": 20.0})
    assert over.status_code == 400 and "gift演出の中" in over.json()["detail"]
    # 短すぎる窓は切っても中身が無い(空のpartでffmpegが落ちる)。
    thin = client.patch(url, json={"cut_start": 12.0, "cut_end": 12.1})
    assert thin.status_code == 400 and "短すぎ" in thin.json()["detail"]
    # gift演出の端ちょうどは通る。画面は0.001秒に丸めた値を送るので、厳密に比べると自分が
    # 出した値で400になる。
    assert client.patch(url, json={"cut_start": 10.0, "cut_end": 16.0}).status_code == 200
    after = _segment_of(client, highlight_id)["gifts"][0]
    assert (after["cut_start"], after["cut_end"]) == (10.0, 16.0)


def test_a_gift_cut_needs_both_ends(client, matched_highlight, make_srv_recording):
    """頭と尻は**必ず揃えて**送る。片方だけ受ける口にすると、「窓を持っている」と判定
    されたまま尻がNULL、という読み手のいない状態が作れる。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 10.0, 16.0, recording_id=recording_id, media_start=100.0,
                 gifts=[_gift(event_id=111, media_time=101.2)]),
    ]))
    segment = _segment_of(client, highlight_id)
    half = client.patch(_gift_url(highlight_id, segment, segment["gifts"][0]),
                        json={"cut_start": 11.0})
    assert half.status_code == 400 and "揃えて" in half.json()["detail"]


def test_clearing_a_gift_cut_goes_back_to_the_segment_window(client, matched_highlight,
                                                             make_srv_recording):
    """区間を捨てるとgift演出の窓へ戻る。**消す操作であって、既定値へ戻す操作ではない**ので、
    DBもNULLへ戻す(gift演出の値をcopyして埋めると、次の再照合でgift演出が動いても付いていかない)。

    ``cut_start`` に null を送る形にしないのは、「送っていない」と「nullを送った」を
    区別する作りだと、JSONを組む側の取り違えが**黙って範囲を消す**操作になるためである。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 10.0, 16.0, recording_id=recording_id, media_start=100.0,
                 gifts=[_gift(event_id=111, media_time=101.2)]),
    ]))
    segment = _segment_of(client, highlight_id)
    url = _gift_url(highlight_id, segment, segment["gifts"][0])
    client.patch(url, json={"cut_start": 11.0, "cut_end": 14.0})

    reply = client.patch(url, json={"cut_clear": True})
    assert reply.status_code == 200
    gift = reply.json()["segment"]["gifts"][0]
    assert (gift["cut_start"], gift["cut_end"]) == (10.0, 16.0)
    assert gift["cut_own"] is False
    # 値と「消す」を同時に送るのは取り違えなので断る。
    both = client.patch(url, json={"cut_clear": True, "cut_start": 11.0, "cut_end": 14.0})
    assert both.status_code == 400


def test_a_rematch_carries_the_gift_cut_with_the_segment(client, matched_highlight,
                                                         make_srv_recording):
    """再照合でgift演出が動いたら、人が詰めた区間も**同じだけ動く**。

    人が詰めたのは「gift演出のこの辺り」であって、highlightの絶対秒そのものではない ——
    動いていないのは録画の中の映像の方である(``media_start`` を載せ直すのと同じ写像)。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 10.0, 16.0, recording_id=recording_id, media_start=100.0,
                 gifts=[_gift(event_id=111, media_time=101.2)]),
    ]))
    segment = _segment_of(client, highlight_id)
    client.patch(_gift_url(highlight_id, segment, segment["gifts"][0]),
                 json={"cut_start": 11.0, "cut_end": 14.0})

    # 次の照合が同じgift演出を0.5秒後ろで見つけた(重なりで結ばれる)。
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 10.5, 16.5, recording_id=recording_id, media_start=100.5,
                 gifts=[_gift(event_id=111, media_time=101.2)]),
    ]))
    gift = _segment_of(client, highlight_id)["gifts"][0]
    assert (gift["cut_start"], gift["cut_end"]) == (11.5, 14.5)
    assert gift["cut_own"] is True


def test_a_rematch_that_leaves_no_room_drops_the_gift_cut(client, matched_highlight,
                                                          make_srv_recording):
    """gift演出が大きく動いて区間が残らないときは、**捨ててgift演出の窓へ戻す**。

    はみ出したまま持たせると、出力だけが無関係な場面を切る(端が逆転すれば書き出しが
    そこで落ちる)。人の手直しが失われる操作なので、黙って行わずlogに残す
    (``highlight.gift_cut_reset``)。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 10.0, 20.0, recording_id=recording_id, media_start=100.0,
                 gifts=[_gift(event_id=111, media_time=101.2)]),
    ]))
    segment = _segment_of(client, highlight_id)
    client.patch(_gift_url(highlight_id, segment, segment["gifts"][0]),
                 json={"cut_start": 18.0, "cut_end": 20.0})
    # gift演出の尻が4秒前へ詰まり、人の窓(18.0〜20.0)が入る余地を失った。
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 10.0, 16.0, recording_id=recording_id, media_start=100.0,
                 gifts=[_gift(event_id=111, media_time=101.2)]),
    ]))
    gift = _segment_of(client, highlight_id)["gifts"][0]
    assert gift["cut_own"] is False
    assert (gift["cut_start"], gift["cut_end"]) == (10.0, 16.0)


def test_a_gift_cut_survives_a_rematch_that_drops_the_gift(client, matched_highlight,
                                                           make_srv_recording):
    """区間を詰めただけの行も「人の入力」である。

    ``cut_start`` は **0.0 を取り得る**ので、人の入力の有無を真偽で見てはいけない ——
    真偽で見ると、highlightの頭から始まる区間を持たせた行だけが「人の入力なし」と判定
    されて、次の再照合で黙って消える。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 16.0, recording_id=recording_id, media_start=100.0,
                 gifts=[_gift(event_id=111, media_time=101.2, name="Galaxy"),
                        _gift(event_id=222, media_time=104.5, name="Rose",
                              primary=False)]),
    ]))
    segment = _segment_of(client, highlight_id)
    rose = next(g for g in segment["gifts"] if g["gift_name"] == "Rose")
    # 頭がちょうど 0.0 の区間。真偽で見ると「入力なし」に見える形である。
    client.patch(_gift_url(highlight_id, segment, rose), json={"cut_start": 0.0,
                                                               "cut_end": 3.0})
    # 次の照合にこのgiftは出なかった。人の入力を持つので、消さずにdroppedで残す。
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 16.0, recording_id=recording_id, media_start=100.0,
                 gifts=[_gift(event_id=111, media_time=101.2, name="Galaxy")]),
    ]))
    gifts = {g["gift_name"]: g for g in _segment_of(client, highlight_id)["gifts"]}
    assert "Rose" in gifts
    assert gifts["Rose"]["dropped"] is True and gifts["Rose"]["excluded"] is True


def test_coverage_names_the_cut_and_how_many_people_share_the_segment(
        client, matched_highlight, make_srv_recording, gift_builder):
    """俯瞰の行が、**そのgiftの区間**と**相席の人数**を名乗ること。

    区間をgift演出の窓で出していた頃は、6秒に3人載ったgift演出の3行が同じ数字で並び、gift単位で
    詰めた意味が表から消えていた。人数は**件数ではない** —— 連投は同じ人が何件も出すので、
    件数で見ると1人しか居ないgift演出が「相席」に見える。"""
    highlight_id, storage = matched_highlight
    highlight = storage.get_highlight(highlight_id)
    session_id, recording_id, _path = make_srv_recording(
        unique_id=highlight["unique_id"])
    started = storage.get_recording(recording_id)["started_at"]
    # **2人とも対象gifter(週合計1,000🪙以上)にする。** 検証の面に並ぶのは対象gifterのgift
    # だけなので、届かない額を置くと相席の相手が表から消えて、人数を数える相手が居なくなる。
    # この test の主眼は区間と相席の人数なので、額そのものは本質ではない。
    for offset, (nickname, user_id, coin) in enumerate((
            ("あきと", "7001", 6000), ("るきしろ", "7002", 1000))):
        storage.add_event(session_id, gift_builder(
            "G", diamonds=coin, at=started + 100.0 + offset,
            user={"userId": user_id, "uniqueId": f"u{user_id}",
                  "nickname": nickname}))
    storage.flush()
    events = storage.highlight_gift_events(session_id, started, started + 1000.0)
    assert len(events) == 2
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 10.0, 16.0, recording_id=recording_id, media_start=100.0,
                 # **別人**である(identity_keyが違う)。同じ人の連投と区別するために、
                 # 人数はDISTINCTなidentity_keyで数える。
                 gifts=[_gift(event_id=events[0]["gift_event_id"], media_time=100.5,
                              name=events[0]["gift_name"], key="k-akito",
                              diamonds=events[0]["diamonds"]),
                        _gift(event_id=events[1]["gift_event_id"], media_time=101.5,
                              name=events[1]["gift_name"], key="k-rukishiro",
                              diamonds=events[1]["diamonds"], primary=False)]),
    ]))
    segment = _segment_of(client, highlight_id)
    first = segment["gifts"][0]
    client.patch(_gift_url(highlight_id, segment, first),
                 json={"cut_start": 10.0, "cut_end": 12.0})

    hits = []
    for item in client.get(
            f"/api/highlights/coverage?streamer={highlight['unique_id']}"
            "&min_diamonds=0").json()["items"]:
        hits.extend(item["hits"])
    by_row = {hit["gift_row_id"]: hit for hit in hits}
    assert len(by_row) == 2
    mine = by_row[first["id"]]
    other = next(hit for row_id, hit in by_row.items() if row_id != first["id"])
    assert (mine["cut_start"], mine["cut_end"]) == (10.0, 12.0)
    assert mine["cut_own"] is True
    assert (other["cut_start"], other["cut_end"]) == (10.0, 16.0)
    assert other["cut_own"] is False
    # **人数**。この2件は別人なので2。
    assert mine["segment_gifters"] == 2 and other["segment_gifters"] == 2
