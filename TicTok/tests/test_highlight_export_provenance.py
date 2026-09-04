"""**実照合結果に基づかない書き出しを止める**仕掛けのtest。

事故があったので在るtestである。``highlight_videos`` が1行も無い状態で、手で組んだgift演出の
定義から7本のmp4が書き出された。素材の範囲はあるhighlightから、gifterの名前は**別の
highlight**の真値から採られており、``視聴者A`` の名前を持つfileの中身は ``視聴者C`` が投げた
Guardian's Pledge だった。file名は誰の物かを名乗るが、名前の側に中身の保証は何も無い。

ここが確かめるのは6つ。

(1) 照合が終わっていないhighlightからは書き出せないこと(``status`` が ``matched`` 以外)。
(2) 切る直前にDBを引き直し、**素材・範囲・gift・持ち主が1つでも食い違えば失敗**すること。
    事故そのもの(別の素材 / 別人のgift)を2件そのまま再現して置いてある。
(3) 素性の無いmp4が作れないこと。名前の印(``.検証用``)と素性の ``verified`` は必ず一致する。
(4) 検証用の口が**HTTPからは届かない**こと。
(5) 下見(``/export/plan``)の各行に**代表frameのURL**が付くこと。文字列だけでは「別人のfileへ
    別人のgiftが入る」誤りに人が気付けない —— 押す前に絵で判るようにするためである。
(6) 下見が**記録(gift)と切り出し(窓)を別々に**名乗り、演出の印を落とさずに出すこと。
    1つのgift演出が複数のgiftを持つので、この2つは1対1にならない。

**素の値ではなく本物のDBで確かめる。** 突き合わせる相手はstoreの実装そのもの(列の綴りと
型)なので、stubを相手にすると「stubとは一致する」ことしか言えない。
"""
from pathlib import Path

import pytest

from tictok.media import highlight_export as hx

from tests.test_server import (  # noqa: F401  (fixtureとして使う)
    client, make_srv_recording, server,
)
from tests.test_clips_api import clip_roots  # noqa: F401  (fixtureとして使う)
from tests.test_highlight_api import (  # noqa: F401  (fixtureとして使う)
    clean_highlights, highlight_roots,
)

STREAMER = "streamer_a"


def _user(nickname, *, user_id, unique_id):
    """gift eventのuser。**別人を別人として作れる形**にしておく。

    名寄せの鍵(``identity_key``)はstorageが ``user_id`` から決めるので、testが自分で
    鍵を組み立てない —— 組み立てると、名寄せの規則が変わった日にtestだけが古い鍵で通る。"""
    return {"user_id": user_id, "unique_id": unique_id, "nickname": nickname,
            "avatar": "", "fans_level": 0, "gifter_level": 0,
            "gifter_badge": "", "member_badge": ""}


@pytest.fixture
def matched(client, server, highlight_roots, make_srv_recording, gift_builder):
    """**製品と同じ経路で**照合済みのhighlightを1本作る。

    走査(``scan_highlights``)→照合結果の保存(``save_highlight_match``)まで実物の経路を
    通す。gift演出のgift列はDBのeventから解決した値をそのまま渡す —— 実装(照合と手直しの
    どちらも)がそうしているので、testだけが別の作り方をすると照合の網が意味を失う。

    ``(highlight_id, storage, gifts, path)`` を返す。``gifts`` は2件で、**投げた人が別人**
    である(事故の再現に要る)。"""
    storage = server.runtime.storage
    session_id, recording_id, _mp4 = make_srv_recording(unique_id=STREAMER, ts_segments=4)
    recording = storage.get_recording(recording_id)
    started = recording["started_at"]
    storage.add_event(session_id, gift_builder(
        "Goal Highlight", diamonds=6000, at=started + 100.0,
        user=_user("視聴者A", user_id="7001", unique_id="viewer_a")))
    storage.add_event(session_id, gift_builder(
        "Guardian's Pledge", diamonds=4999, at=started + 200.0,
        user=_user("視聴者C", user_id="7002", unique_id="viewer_c")))
    storage.flush()
    gifts = storage.highlight_gift_events(session_id, started, started + 1000.0)
    assert len(gifts) == 2

    path = highlight_roots["place"](highlight_roots["work"], STREAMER, "highlights",
                                    "a.mp4")
    client.post("/api/highlights/scan", json={"streamer": STREAMER})
    highlight_id = client.get(
        f"/api/highlights?streamer={STREAMER}").json()["items"][0]["id"]
    storage.save_highlight_match(highlight_id, {
        "seconds": 60.0, "pool": 1, "pool_hours": 1.0, "elapsed": 1.0,
        "scope": {"scope": "gift", "days": 14.0},
        "segments": [
            {"index": index, "start": 3.0 * index, "end": 3.0 * index + 3.0,
             "recording_id": recording_id, "media_start": 100.0 + 100.0 * index,
             "votes": 900, "ratio": 220.0, "corr": 0.98, "confidence": "high",
             "effect": [],
             # 照合側は **gifts(複数)** を返す。1つのgift演出に複数のgiftが乗るためで、
             # 高額な1件だけを持つ形へ戻すと画面に映っている演出の主が落ちる。
             "gifts": [{**gift, "event_id": gift["gift_event_id"],
                        "media_time": 100.0 + 100.0 * index,
                        "inside": True, "primary": True}]}
            for index, gift in enumerate(gifts)],
    })
    return highlight_id, storage, gifts, path


@pytest.fixture
def items(matched):
    """切り出しへ渡す1件ずつ。``(items, storage, gifts)``。

    ``_fetch_segments`` → ``_item`` という製品と同じ順で組む。ここを手で組むと、まさに
    事故と同じ「実照合結果ではない行」でtestを書くことになる。"""
    highlight_id, storage, gifts, _path = matched
    rows = hx._fetch_segments(storage, [highlight_id])
    return [hx._item(row, 0.0, 0.0) for row in rows], storage, gifts


# ===== (1) 照合が終わっていないものからは書き出せない =====

def test_未照合のhighlightからは読み出せない(client, server, highlight_roots):
    """走査しただけ(``new``)の行からgift演出を読もうとしたら失敗させる。

    下見(``/export/plan``)もこの関数を通るので、**画面が予告を出す前に**判る。"""
    highlight_roots["place"](highlight_roots["work"], STREAMER, "highlights", "b.mp4")
    client.post("/api/highlights/scan", json={"streamer": STREAMER})
    highlight_id = client.get(
        f"/api/highlights?streamer={STREAMER}").json()["items"][0]["id"]
    with pytest.raises(hx.NotMatched):
        hx._fetch_segments(server.runtime.storage, [highlight_id])


def test_未照合のhighlightは書き出しの口が409で断る(client, highlight_roots):
    """jobを積む前に断る。待機列の順番を待った末に同じ理由で落ちても、押した人には届かない。"""
    highlight_roots["place"](highlight_roots["work"], STREAMER, "highlights", "b.mp4")
    client.post("/api/highlights/scan", json={"streamer": STREAMER})
    highlight_id = client.get(
        f"/api/highlights?streamer={STREAMER}").json()["items"][0]["id"]
    for endpoint in ("/api/highlights/export", "/api/highlights/export/plan"):
        response = client.post(endpoint, json={"highlight_ids": [highlight_id]})
        assert response.status_code == 409, endpoint
        assert "照合が終わっていない" in response.json()["detail"]


# ===== (2) 切る直前にDBと突き合わせる =====

def test_実照合結果はそのまま通り素性を返す(items):
    """通る道が在ることを先に確かめる。**網が細かすぎて何も通らない**のは直せない不具合になる。"""
    (item, _other), storage, gifts = items
    record = hx.verify_item(storage, item, gifts[0]["identity_key"])
    assert record["gift_event_id"] == gifts[0]["gift_event_id"]
    assert record["gift_name"] == "Goal Highlight" and record["diamonds"] == 6000
    assert record["gifter"]["nickname"] == "視聴者A"
    assert record["segment_start"] == 0.0 and record["cut_end"] == 3.0
    assert record["highlight_filename"] == "a.mp4"


def test_別人のgiftを持つgift演出はそのfileへ入れない(items):
    """**事故そのもの。** ``視聴者A`` のfileに ``視聴者C`` のgiftのgift演出を入れようとする。

    file名は持ち主を名乗るので、ここが通ると名前が嘘をつく。"""
    (viewer_a, viewer_c), storage, gifts = items
    assert viewer_c["gift_name"] == "Guardian's Pledge"
    with pytest.raises(hx.NotVerified) as exc:
        hx.verify_item(storage, viewer_c, gifts[0]["identity_key"])
    assert "持ち主" in str(exc.value)


def test_束ねたサブアカウントのgiftはその人のfileへ入る(items):
    """**束ね(user_merges)を畳んでから比べる。** 人が「この2つは同じ人だ」と決めた相手の
    giftは、その人のfileの中身である —— 畳まずに比べると、束ねた人ほど自分のgiftが
    「別人のgift」として弾かれる。

    畳み先は**その場でDBを引き直す**(計画の段で作った辞書は受け取らない)ので、束ねを
    外せば同じ組み合わせがまた止まる。"""
    (viewer_a, viewer_c), storage, gifts = items
    owner = gifts[0]["identity_key"]
    other = gifts[1]["identity_key"]
    assert owner != other
    storage.merge_users(other, owner)
    record = hx.verify_item(storage, viewer_c, owner)
    # 素性に残るgifterは**投げたアカウント**のまま(観測した事実は書き換えない)。
    assert record["gifter"]["identity_key"] == other

    storage.unmerge_user(other)
    with pytest.raises(hx.NotVerified):
        hx.verify_item(storage, viewer_c, owner)


def test_別のhighlightのfileを切ろうとしたら止める(items, highlight_roots):
    """**事故のもう半分。** 範囲はgift演出の物、素材は別のhighlight —— という組み合わせを止める。"""
    (item, _other), storage, gifts = items
    other = highlight_roots["place"](highlight_roots["work"], STREAMER, "highlights",
                                     "other.mp4")
    with pytest.raises(hx.NotVerified) as exc:
        hx.verify_item(storage, {**item, "src": other}, gifts[0]["identity_key"])
    assert "素材" in str(exc.value)


def test_DBの行を指していないgift演出は通さない(items):
    """手で組んだ行には ``segment_id`` が無い。DBに引き当てる鍵が無ければ確かめようがない。"""
    (item, _other), storage, gifts = items
    with pytest.raises(hx.NotVerified):
        hx.verify_item(storage, {**item, "segment_id": None},
                       gifts[0]["identity_key"])


@pytest.mark.parametrize("field, value", [
    ("segment_start", 1.5),      # 範囲を勝手に動かした
    ("segment_end", 30.0),
    ("diamonds", 99),            # 額を書き換えた
    ("gift_name", "Rose"),       # 別のgiftを名乗った
    ("recording_id", 999),       # 別の録画から来たことにした
    ("media_start", 1.0),
    ("gift_event_id", 424242),   # 別のeventを指した
])
def test_DBと1つでも違えば通さない(items, field, value):
    """**どの値も出来上がるmp4の中身か持ち主を決めている。** 1つでも違えば別物である。"""
    (item, _other), storage, gifts = items
    with pytest.raises(hx.NotVerified):
        hx.verify_item(storage, {**item, field: value}, gifts[0]["identity_key"])


def test_人が外したgift演出は通さない(client, items, matched):
    """計画を組んでから切るまでの間に人が外すことがある。**下見の時点の判断を使い回さない。**"""
    highlight_id, storage, gifts, _path = matched
    (item, _other), _storage, _gifts = items
    response = client.patch(
        f"/api/highlights/{highlight_id}/segments/{item['segment_id']}",
        json={"excluded": True})
    assert response.status_code == 200
    with pytest.raises(hx.NotVerified) as exc:
        hx.verify_item(storage, item, gifts[0]["identity_key"])
    assert "外した" in str(exc.value)


def test_gift_eventが消えていれば通さない(items, server):
    """``events`` 側が消えた(録画を消した等)ときに、gift演出の列だけで書き出さない。"""
    (item, _other), storage, gifts = items
    with storage._lock:
        storage._conn.execute("DELETE FROM events WHERE id = ?",
                              (gifts[0]["gift_event_id"],))
        storage._conn.commit()
    with pytest.raises(hx.NotVerified) as exc:
        hx.verify_item(storage, item, gifts[0]["identity_key"])
    assert "gift event" in str(exc.value)


def test_gift演出のgiftとeventが食い違えば再照合を促す(items):
    """gift演出のgift列は ``events`` の1行から丸ごと写される。食い違う行は作られ得ない。"""
    (item, _other), storage, gifts = items
    with storage._lock:
        storage._conn.execute("UPDATE events SET diamonds = ? WHERE id = ?",
                              (10, gifts[0]["gift_event_id"]))
        storage._conn.commit()
    with pytest.raises(hx.NotVerified) as exc:
        hx.verify_item(storage, item, gifts[0]["identity_key"])
    assert "再照合" in str(exc.value)


# ===== (3) 素性の無いmp4を作らせない =====

def test_素性は省略できない():
    """``render_segments`` は素性を必ず要る引数にしてある(既定値を持たせない)。"""
    with pytest.raises(TypeError):
        hx.render_segments([], Path("x_story.mp4"))


def test_名前の印と素性のverifiedは必ず一致する(tmp_path):
    """**両方向に縛る。** 検証していない中身が製品の名前で出るのも、その逆も止める。"""
    product = tmp_path / "260829-260905_coin1000_名前_story.mp4"
    marked = tmp_path / f"260829-260905_coin1000_名前_story{hx.UNVERIFIED_MARK}.mp4"
    hx._require_marked_name(product, {"verified": True})
    hx._require_marked_name(marked, {"verified": False})
    with pytest.raises(hx.NotVerified):
        hx._require_marked_name(product, {"verified": False})
    with pytest.raises(hx.NotVerified):
        hx._require_marked_name(marked, {"verified": True})
    with pytest.raises(hx.NotVerified):
        hx._require_marked_name(product, {})


def test_検証用の出力はfile名で判る():
    """名前の印は中身と一緒に動く。素性のJSONは隣に在るだけで、1本運べば付いて行かない。"""
    name = hx.export_filename(0.0, 0.0, 5906, "視聴者J", verified=False)
    assert name.endswith(f"{hx.STORY_SUFFIX}{hx.UNVERIFIED_MARK}{hx.STORY_EXT}")
    assert hx.UNVERIFIED_MARK not in hx.export_filename(0.0, 0.0, 5906, "視聴者J")


def test_素性は中身の出所を1件ずつ名乗る(items, matched, tmp_path):
    """後から人が「このfileは本当に合っているか」を辿れる形になっていること。

    要るのは**DBを引き直せる鍵**である。highlightのidとfile名・gift演出のid・gift eventのid・
    録画のidとmedia秒が揃っていれば、mp4を開かずに1件ずつ確かめられる。"""
    highlight_id, storage, gifts, _path = matched
    (item, _other), _storage, _gifts = items
    checked = hx.verify_items(storage, [item], gifts[0]["identity_key"])
    record = hx.provenance_record(
        {"filename": "x_story.mp4", "identity_key": gifts[0]["identity_key"],
         "nickname": "視聴者A", "unique_id": "viewer_a", "coin": 6000, "rank": 1},
        checked, streamer=STREAMER,
        plan={"week": "2026-08-29", "week_label": "…", "order": "diamonds",
              "post_min": 1000, "min_diamonds": 98},
        verified=True)
    assert record["verified"] is True and record["schema"] == hx.PROVENANCE_SCHEMA
    assert record["gifter"]["nickname"] == "視聴者A"
    entry = record["segments"][0]
    assert entry["position"] == 1 and entry["highlight_id"] == highlight_id
    assert entry["segment_id"] == item["segment_id"]
    assert entry["gift_event_id"] == gifts[0]["gift_event_id"]
    assert entry["recording_id"] and entry["media_start"] == 100.0


def test_素性には実測値まで入る(tmp_path):
    """後から見た人が、fileを開かずに「この素性はこのfileの物か」を確かめられること。

    容量と尺が入っていれば、隣のmp4と突き合わせるだけで別のfileの素性ではないと判る。"""
    out = tmp_path / "260829-260905_coin1000_名前_story.mp4"
    out.write_bytes(b"\x00" * 16)
    info = {"bytes": 16, "parts": 2, "encoder": "h264_nvenc", "precise": True,
            "normalized": False, "requested_seconds": 6.0,
            "measured": {"video_seconds": 6.02, "audio_seconds": 6.03}}
    written = hx._write_provenance(out, {"verified": True, "segments": []}, info)
    import json

    record = json.loads(Path(written).read_text(encoding="utf-8"))
    assert Path(written) == hx.provenance_path(out)
    assert record["verified"] is True
    assert record["output"]["bytes"] == 16 and record["output"]["parts"] == 2
    assert record["output"]["measured"]["video_seconds"] == 6.02


def test_素性はmp4の隣に置かれる(tmp_path):
    """拡張子を差し替えず後ろへ足す。どのmp4の物かをfile名だけで言い切るため。"""
    out = tmp_path / "260829-260905_coin1000_名前_story.mp4"
    assert hx.provenance_path(out).name == f"{out.name}{hx.PROVENANCE_EXT}"


def test_mp4を消すと素性も消える(client, clip_roots):
    """一覧に出ない拡張子なので、残っても誰も気付けない。中身の無い素性は素性ではない。"""
    target = clip_roots["work"] / STREAMER / "LiveHightlite_マージ済み"
    target.mkdir(parents=True, exist_ok=True)
    mp4 = target / "260829-260905_coin1000_名前_story.mp4"
    mp4.write_bytes(b"\x00" * 8)
    side = hx.provenance_path(mp4)
    side.write_text("{}", encoding="utf-8")
    name = f"{STREAMER}/LiveHightlite_マージ済み/{mp4.name}"
    response = client.request("DELETE", "/api/clips/file",
                              params={"root": "work", "name": name})
    assert response.status_code == 200
    assert response.json()["companion_files"] == [side.name]
    assert not mp4.exists() and not side.exists()


# ===== (4) 検証用の口はHTTPから届かない =====

def test_検証用の引数は製品の口から渡せない(client, highlight_roots):
    """``HighlightExportRequest`` は未知のfieldを弾く。黙って無視すると、指定が効いたと
    思い込んだまま別の結果を受け取ることになる。"""
    for endpoint in ("/api/highlights/export", "/api/highlights/export/plan"):
        response = client.post(endpoint, json={"highlight_ids": [1],
                                               "verification_rows": []})
        assert response.status_code == 422, endpoint


def test_jobが渡す設定に検証用の口は無い():
    """queue経由でも届かないこと。jobは ``EXPORT_OPTION_KEYS`` の分しか渡さない。"""
    from tictok.api import media_jobs

    assert "verification_rows" not in media_jobs.EXPORT_OPTION_KEYS


# ===== (5) 下見の各行に絵が付く =====

def test_下見の各行に代表frameのURLが付く(client, matched):
    """gift名とgifter名の文字列だけでは、中身の取り違えに人が気付けない。

    highlight側と録画側の**同じ秒**の2枚を出す。2枚が同じ場面なら突き合わせが当たっている
    ことがその場で判る —— 片方をmedia秒で組むと、それらしい別の場面が並んで「一致して
    いる」ように見えてしまう。"""
    highlight_id, _storage, gifts, _path = matched
    body = client.post("/api/highlights/export/plan",
                       json={"highlight_ids": [highlight_id]}).json()
    rows = [item for entry in body["files"] for item in entry["items"]]
    assert rows and len(rows) == len(gifts)
    for row in rows:
        assert row["at"] is not None
        assert row["frame_url"] == (
            f"/api/highlights/{highlight_id}/frame?at={row['at']:.3f}")
        assert row["recording_frame_url"] == (
            f"/api/highlights/{highlight_id}/segments/{row['segment_id']}"
            f"/frame?at={row['at']:.3f}")


def test_束ねた2人は下見でも1本になる(client, matched, server):
    """**画面までの通し。** 配信者タブで束ねた2つのアカウントは、下見でもfile 1本になり、
    行は投げたアカウント(``identity_key``)と人(``person_key``)の両方を名乗る。

    畳んだ鍵が応答の列から落ちていると、画面はアカウントで比べるしかなくなり、束ねた人が
    自分のサブで投げたgiftのたびに「別人が混ざっている」と名乗る。"""
    highlight_id, storage, gifts, _path = matched
    viewer_a, viewer_c = gifts[0]["identity_key"], gifts[1]["identity_key"]
    # 束ねる前は2人ぶんで2本。
    before = client.post("/api/highlights/export/plan",
                         json={"highlight_ids": [highlight_id]}).json()
    coins = {f["identity_key"]: f["coin"] for f in before["files"]}
    assert sorted(coins) == sorted([viewer_a, viewer_c])

    storage.merge_users(viewer_c, viewer_a)
    try:
        body = client.post("/api/highlights/export/plan",
                           json={"highlight_ids": [highlight_id]}).json()
    finally:
        # 束ねは人に付く(配信者にも週にも紐付かない)ので、同じstorageを使う後続のtestへ
        # 残さない。
        storage.unmerge_user(viewer_c)
    assert [f["identity_key"] for f in body["files"]] == [viewer_a]
    entry = body["files"][0]
    assert entry["accounts"] == 2
    # 週合計は畳んだ後の額(2つのアカウントの合計)で、file名もその数字を名乗る。
    assert entry["coin"] == coins[viewer_a] + coins[viewer_c]
    assert f"coin{entry['coin']}" in entry["filename"]
    keys = {(item["identity_key"], item["person_key"]) for item in entry["items"]}
    assert keys == {(viewer_a, viewer_a), (viewer_c, viewer_a)}


def test_絵は切り出す窓の中から採る(client, matched, server):
    """giftがgift演出の頭より手前を指すとき、絵はその位置から採らない。

    ``gift_lead`` で手前へ伸ばした窓に入っただけのgiftは、gift演出の頭より前の秒を指す。
    **そこにhighlightの映像は無い**(別の時刻のgift演出が繋がっているだけ)ので、丸めずに絵を
    採ると**出力に入らない場面**が下見に並ぶ。位置そのもの(``at``)は丸めずに返す。"""
    highlight_id, storage, gifts, _path = matched
    # giftのmedia秒をgift演出の頭より10秒手前へ寄せる(= 手前の窓で拾ったgiftと同じ形)。
    with storage._lock:
        storage._conn.execute(
            "UPDATE highlight_segment_gifts SET gift_media_time ="
            " (SELECT s.media_start - 10.0 FROM highlight_segments s"
            "  WHERE s.id = highlight_segment_gifts.segment_id), inside = 0"
            " WHERE highlight_id = ?", (highlight_id,))
        storage._conn.commit()
    body = client.post("/api/highlights/export/plan",
                       json={"highlight_ids": [highlight_id]}).json()
    for entry in body["files"]:
        for row in entry["items"]:
            assert row["at"] == row["start"] - 10.0
            # 絵は窓の頭で止まる。URLの秒は ``at`` ではなく窓の中の秒である。
            assert row["frame_url"].endswith(f"at={row['start']:.3f}")


def test_下見は記録と切り出しを別々に名乗る(client, matched):
    """``items`` はgift 1件ずつの記録、``cuts`` は実際に切る窓。1対1にならない。

    画面が「gift 6件なのに映像は1つ」を説明できるのは、両方が返るからである。"""
    highlight_id, _storage, gifts, _path = matched
    body = client.post("/api/highlights/export/plan",
                       json={"highlight_ids": [highlight_id]}).json()
    entry = body["files"][0]
    assert entry["count"] == len(entry["items"])
    assert entry["cut_count"] == len(entry["cuts"])
    for cut in entry["cuts"]:
        # 素材の実pathは返さない(画面が指すのはhighlightの行であってfile systemではない)。
        assert "src" not in cut
        assert cut["gift_event_ids"]


def test_下見は演出の印を出さない_gifterは出す(client, matched):
    """**演出の印は運ばない。** 当たりが0件の信号を返すと、画面がそれを警告として出す。

    代わりに要るのは**誰が投げたか**である。行にgifterが無いと、束を開いても持ち主と
    違うgifterのgift演出が紛れていることに人が気付けない —— 今回の事故はそれだった。
    比べるのは表示名ではなく ``identity_key`` である(改名すれば別人に見える)。"""
    highlight_id, _storage, gifts, _path = matched
    body = client.post("/api/highlights/export/plan",
                       json={"highlight_ids": [highlight_id]}).json()
    keys = {g["identity_key"] for g in gifts}
    for entry in body["files"]:
        for row in entry["items"]:
            assert "has_effect" not in row and "segment_has_effect" not in row
            assert row["inside"] is True and row["is_primary"] is True
            # 束の持ち主と、その行のgiftを投げた人。鍵どうしで比べられること。
            assert row["identity_key"] == entry["identity_key"]
            assert row["identity_key"] in keys
            assert row["user_nickname"] and row["user_unique_id"]



# ===== (6) 下見は「無い物」も名乗る =====

def test_下見に載らなかったgiftが理由つきで付く(client, server, matched, gift_builder):
    """**照合結果に在るgiftだけを並べない。** その週に投げたのに1本へ載らなかったgiftを、
    理由つきで返す —— 無い物こそが、書き出す前に人が見なければならない側である。

    ここは**製品と同じ経路**(route → store の母集団 → plan_exports)で確かめる。母集団を
    渡し忘れていれば ``missing`` は空のままなので、繋がっていることまで見える。"""
    highlight_id, storage, _gifts, _path = matched
    session_id = storage.get_highlight(highlight_id)  # 台帳の行(存在確認)
    assert session_id is not None
    recordings = storage.list_recordings(limit=1)
    started = recordings[0]["started_at"]
    # どのhighlightにも出ていないgift。同じ人(視聴者A)が同じ週にもう1件投げている。
    storage.add_event(recordings[0]["session_id"], gift_builder(
        "Fireworks", diamonds=1088, at=started + 300.0,
        user=_user("視聴者A", user_id="7001", unique_id="viewer_a")))
    # まとめ投げ(30💎 x 9)。単価で切るので、**載らなかった一覧にも出さない。**
    storage.add_event(recordings[0]["session_id"], gift_builder(
        "Rose", diamonds=270, repeat_count=9, at=started + 400.0,
        user=_user("視聴者A", user_id="7001", unique_id="viewer_a")))
    storage.flush()

    body = client.post("/api/highlights/export/plan",
                       json={"highlight_ids": [highlight_id]}).json()
    names = {g["gift_name"] for entry in body["files"] for g in entry["missing"]}
    assert "Fireworks" in names
    assert "Rose" not in names
    row = next(g for entry in body["files"] for g in entry["missing"]
               if g["gift_name"] == "Fireworks")
    assert row["reason"] == hx.MISSING_UNMATCHED
    # 出来上がるfileの中身は変わらない(載らなかったgiftは窓を持たない)。
    assert all(entry["count"] == len(entry["items"]) for entry in body["files"])
    assert "uncovered" in body
