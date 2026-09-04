"""TikTok本体のhighlightの台帳・走査・手直しのtest。

置き場が複数ある(2通り × work/final の両root ―― ``layout.highlight_dirs``)ことと、**再照合で人の手直しが消えない**こと
が、この画面の成立条件そのものである。前者が崩れると利用者が置いたfileが1本も見つからず、
後者が崩れると照合をやり直すたびに人の作業が消える(そういう台帳は二度と使われない)。

rootは ``runtime.RECORD_DIR`` ではなくこのtestのtmpへ張る。runtimeはimport時に1度だけ
rootを掴むmodule singletonで、全testが**最初のtestのsandbox**を共有するため、そこへ置くと
前のtestが作ったfileを次のtestが自分のものとして数える(tests/test_clips_api.py と同じ理由)。
"""

from pathlib import Path

import pytest

from tests.test_server import (  # noqa: F401  (fixtureとして使う)
    client, make_srv_recording, server,
)


@pytest.fixture(autouse=True)
def clean_highlights(server):
    """testごとに台帳を空にする。

    ``runtime.storage`` はimport時に1度だけ作られるmodule singletonで、DBはtest間で
    共有される(置き場のtmpだけが毎回変わる)。台帳を消さないと、前のtestが走査した行が
    次のtestの一覧に並び、件数を数えるassertが実行順で通ったり落ちたりする。"""
    storage = server.runtime.storage

    def _wipe() -> None:
        with storage._lock:
            storage._conn.execute("DELETE FROM highlight_segments")
            storage._conn.execute("DELETE FROM highlight_videos")
            storage._conn.commit()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def highlight_roots(server, tmp_path):
    """work / final の2つのrootを張り、どの置き場へもfileを置ける状態にする。

    2 rootにするのが要点である。highlightは録画に随伴して最終保存先へ移り得るので、
    work rootだけを見る実装はその場では動いて見える。"""
    from tictok.core import layout

    work = tmp_path / "work"
    final = tmp_path / "final"
    work.mkdir(parents=True, exist_ok=True)
    final.mkdir(parents=True, exist_ok=True)
    layout.set_record_roots([work, final])
    layout.set_pool_root(work)

    def _write(target: Path, name: str, size: int) -> Path:
        target.mkdir(parents=True, exist_ok=True)
        path = target / name
        path.write_bytes(b"\x00" * size)
        return path

    def _place(root: Path, streamer: str, dirname: str, name: str,
               size: int = 32) -> Path:
        """配信者folderの下の置き場(``<root>/<配信者>/<dirname>``)へ1本置く。"""
        return _write(root / streamer / dirname, name, size)

    def _place_pool(streamer: str, name: str, size: int = 32) -> Path:
        """root直下の旧pool(``<work root>/highlights/<配信者>``)へ1本置く。

        こちらだけ配信者folderの位置が逆である。**走査対象ではない**ので、置き場の形を
        testが自分で組む —— 解決側に問い合わせて作ると、辿らないことを確かめられない。
        実体はPOCが作った合成素材で、実物のhighlightはここに1本も無い。"""
        return _write(work / layout.HIGHLIGHT_DIRNAME / streamer, name, size)

    return {"work": work, "final": final, "place": _place, "pool": _place_pool,
            "layout": layout}


# ===== 置き場の解決 =====


def test_highlight_dirs_covers_both_placements_across_roots(highlight_roots):
    """正規の置き場と利用者の現行の置き場を、work / final の両rootで拾う。

    綴り(``LiveHightlite``)は実在するfolder名なので直さない。直した瞬間、利用者が置いた
    fileは1本も見つからなくなる。"""
    layout = highlight_roots["layout"]
    highlight_roots["place"](highlight_roots["work"], "streamer_a", "highlights", "a.mp4")
    highlight_roots["place"](highlight_roots["work"], "streamer_a", "LiveHightlite", "b.mp4")
    highlight_roots["place"](highlight_roots["final"], "streamer_a", "highlights", "c.mp4")

    found = layout.highlight_dirs("streamer_a")
    assert found == [
        highlight_roots["work"] / "streamer_a" / "highlights",
        highlight_roots["final"] / "streamer_a" / "highlights",
        highlight_roots["work"] / "streamer_a" / "LiveHightlite",
    ]
    # 実在しない置き場は返さない(在るものだけを名乗る)。
    assert layout.highlight_dirs("unknown") == []
    # 正規の置き場は配信者folderの下。root直下の ``highlights`` とは別物である。
    assert layout.highlight_dir("streamer_a") == highlight_roots["work"] / "streamer_a" / "highlights"


def test_highlight_dirs_ignores_the_root_level_pool(highlight_roots):
    """root直下の ``<work>/highlights/<配信者>`` は**辿らない**。

    そこに在る実体はPOCが作った合成素材だけで、実物のhighlightは1本も無い。走査に残すと、
    合成素材が台帳に並んで「TikTokから来た物」のふりをする。"""
    layout = highlight_roots["layout"]
    highlight_roots["pool"]("streamer_a", "synth.mp4")
    assert layout.highlight_dirs("streamer_a") == []
    assert layout.highlight_streamers() == []
    # 走査が辿らない場所を、**置く側も名乗れない**。配信者を失った呼び出しがroot直下へ
    # 落ちると、誰も読まない場所へ置いた/そこから読もうとした事実がpathにしか残らない。
    for empty in (None, ""):
        with pytest.raises(ValueError):
            layout.highlight_dir(empty)


def test_highlight_streamers_lists_only_streamers_with_a_placement(highlight_roots):
    layout = highlight_roots["layout"]
    highlight_roots["place"](highlight_roots["work"], "streamer_a", "highlights", "a.mp4")
    highlight_roots["place"](highlight_roots["final"], "wicha", "LiveHightlite", "b.mp4")
    # 置き場を持たない配信者folder(録画だけが在る)は入らない。
    (highlight_roots["work"] / "solo" / "mp4").mkdir(parents=True, exist_ok=True)
    assert layout.highlight_streamers() == ["streamer_a", "wicha"]


def test_merged_output_is_reachable_from_the_artifact_paths(highlight_roots):
    """繋いだ1本は ``_clips`` / ``_screenshots`` と同じ成果物として扱う。

    一覧(``/api/clips``)・移動・容量のどれもが ``ARTIFACT_DIRNAMES`` を根拠に辿るので、
    ここに入っていないと**数十本のmp4がどの画面からも辿れないまま溜まる**。"""
    layout = highlight_roots["layout"]
    assert layout.MERGED_HIGHLIGHT_DIRNAME in layout.ARTIFACT_DIRNAMES
    merged = layout.merged_highlight_dir("streamer_a")
    assert merged == highlight_roots["work"] / "streamer_a" / layout.MERGED_HIGHLIGHT_DIRNAME
    merged.mkdir(parents=True, exist_ok=True)
    (merged / "260830-260901_coin2088_someone_story.mp4").write_bytes(b"\x00" * 8)

    work = highlight_roots["work"]
    assert merged in list(layout.iter_clip_dirs(work))
    found = [p for p in layout.iter_clip_files(work) if p.parent == merged]
    assert len(found) == 1
    # 置き場が名乗る配信者へ戻せること(file名の規約は読めなくてよい)。
    assert layout.clip_streamer_of(work, found[0]) == "streamer_a"
    assert layout.is_clip_path(work, found[0])

    # 素材の置き場は成果物ではない。繋ぐ前のhighlightが一覧へ混ざってはいけない。
    highlight_roots["place"](work, "streamer_a", "LiveHightlite", "src.mp4")
    assert (work / "streamer_a" / "LiveHightlite") not in list(layout.iter_clip_dirs(work))


# ===== 走査 =====


def test_scan_records_where_each_file_was_found(client, highlight_roots):
    """行は必ず「どこで見つけたか」を持つ。置き場が複数ある以上、それが無ければ
    利用者は自分が置いたfileへ戻れない。"""
    highlight_roots["place"](highlight_roots["work"], "streamer_a", "LiveHightlite", "a.mp4", 11)
    highlight_roots["place"](highlight_roots["final"], "streamer_a", "highlights", "b.mp4", 22)
    # root直下の旧poolは走査しない。ここへ置いた物は台帳に載らない。
    highlight_roots["pool"]("streamer_a", "synth.mp4", 33)

    scanned = client.post("/api/highlights/scan", json={"streamer": "streamer_a"}).json()
    assert scanned["added"] == 2 and scanned["missing"] == 0
    # 見た置き場を返す。0件だったとき「どこも見ていない」と「見たが空」を区別させる。
    assert len(scanned["dirs"]) == 2

    items = {item["filename"]: item
             for item in client.get("/api/highlights?streamer=streamer_a").json()["items"]}
    assert set(items) == {"a.mp4", "b.mp4"}
    assert items["a.mp4"]["root_key"] == "work"
    assert items["a.mp4"]["source_dir"] == "streamer_a/LiveHightlite"
    assert items["b.mp4"]["root_key"] == "final"
    assert items["b.mp4"]["source_dir"] == "streamer_a/highlights"
    assert items["a.mp4"]["bytes"] == 11 and items["b.mp4"]["bytes"] == 22
    assert all(item["status"] == "new" for item in items.values())
    # 同じ走査を2度かけても行は増えない。
    assert client.post("/api/highlights/scan",
                       json={"streamer": "streamer_a"}).json()["added"] == 0


def test_scan_walks_the_subfolders_a_person_made(client, highlight_roots):
    """置き場の下のsubfolderまで辿り、行は**fileを抱えているfolder**を名乗る。

    利用者は置き場の下へ週ごとのfolder(``20260829-20260905``)を作って素材を仕分ける。
    直下しか見ない走査では、仕分けた瞬間に行が「fileが無い」へ倒れ、照合結果と人の
    手直しがそこへ道連れになる。"""
    highlight_roots["place"](highlight_roots["work"], "streamer_a", "LiveHightlite", "top.mp4")
    highlight_roots["place"](highlight_roots["work"], "streamer_a",
                             "LiveHightlite/20260829-20260905", "week.mp4")
    highlight_roots["place"](highlight_roots["work"], "streamer_a",
                             "LiveHightlite/20260829-20260905/naka", "deep.mp4")

    scanned = client.post("/api/highlights/scan", json={"streamer": "streamer_a"}).json()
    assert scanned["added"] == 3
    # 名乗るのは**置き場**の数のままにする(subfolderを足すと、0件のときに
    # 「どこも見ていない」を言い分けるための数が別の意味になる)。
    assert len(scanned["dirs"]) == 1

    items = {item["filename"]: item
             for item in client.get("/api/highlights?streamer=streamer_a").json()["items"]}
    assert items["top.mp4"]["source_dir"] == "streamer_a/LiveHightlite"
    assert items["week.mp4"]["source_dir"] == "streamer_a/LiveHightlite/20260829-20260905"
    assert items["deep.mp4"]["source_dir"] == "streamer_a/LiveHightlite/20260829-20260905/naka"
    assert all(item["root_key"] == "work" for item in items.values())


def test_scan_prefers_the_shallower_copy_when_a_name_repeats(client, highlight_roots):
    """同じfile名が置き場の直下とsubfolderの両方に在れば、直下を採る(行は1本)。

    仕分けの途中では必ずその状態になる。2本にすると、同じhighlightに2つの照合結果が並ぶ。"""
    highlight_roots["place"](highlight_roots["work"], "streamer_a", "LiveHightlite", "dup.mp4")
    highlight_roots["place"](highlight_roots["work"], "streamer_a",
                             "LiveHightlite/20260829-20260905", "dup.mp4")

    client.post("/api/highlights/scan", json={"streamer": "streamer_a"})
    items = client.get("/api/highlights?streamer=streamer_a").json()["items"]
    assert len(items) == 1
    assert items[0]["source_dir"] == "streamer_a/LiveHightlite"


def test_list_names_every_folder_including_the_empty_ones(client, highlight_roots):
    """一覧はfolderを名乗る。**1本も入っていないfolderも返す。**

    ここは「置き場に何が在るか」の答えで、どれを棚として出すかは画面の見せ方の判断で
    ある(今の一覧は中身も子孫も無い棚を出さない)。Serverが先に間引くと、画面はもう
    「在るのに空だ」と言えなくなる。綴りは行の ``source_dir`` と同じでなければ、
    画面はfolderと行を突き合わせられない。"""
    highlight_roots["place"](highlight_roots["work"], "streamer_a", "LiveHightlite", "a.mp4")
    (highlight_roots["work"] / "streamer_a" / "LiveHightlite" / "20260829-20260905").mkdir()
    client.post("/api/highlights/scan", json={"streamer": "streamer_a"})

    data = client.get("/api/highlights?streamer=streamer_a").json()
    folders = {folder["source_dir"]: folder for folder in data["folders"]}
    assert set(folders) == {"streamer_a/LiveHightlite",
                            "streamer_a/LiveHightlite/20260829-20260905"}
    # 置き場そのものは name が空。棚の見出しを画面が組めるよう、置き場の名乗りも添える。
    assert folders["streamer_a/LiveHightlite"]["name"] == ""
    assert folders["streamer_a/LiveHightlite"]["place"] == "streamer_a/LiveHightlite"
    week = folders["streamer_a/LiveHightlite/20260829-20260905"]
    assert week["name"] == "20260829-20260905"
    assert week["place"] == "streamer_a/LiveHightlite"
    assert week["root_key"] == "work"
    # 行の名乗りと同じ綴りである(片方だけ絶対path・片方だけ相対、が起きない)。
    assert data["items"][0]["source_dir"] in folders


def test_scan_prefers_the_canonical_placement_for_the_same_name(client, highlight_roots):
    """同じfile名が正規の置き場と現行の置き場の両方に在っても行は1本。

    移行の途中では必ずその状態になる。2本にすると、同じhighlightに2つの照合結果が並ぶ。"""
    highlight_roots["place"](highlight_roots["work"], "streamer_a", "LiveHightlite", "dup.mp4")
    highlight_roots["place"](highlight_roots["work"], "streamer_a", "highlights", "dup.mp4")

    client.post("/api/highlights/scan", json={"streamer": "streamer_a"})
    items = client.get("/api/highlights?streamer=streamer_a").json()["items"]
    assert len(items) == 1
    assert items[0]["source_dir"] == "streamer_a/highlights"


def test_scan_marks_missing_without_dropping_the_row(client, highlight_roots):
    """fileが消えても行は残す。gift演出には人が確認・修正した内容が貼り付いている。"""
    path = highlight_roots["place"](highlight_roots["work"], "streamer_a", "highlights", "a.mp4")
    client.post("/api/highlights/scan", json={"streamer": "streamer_a"})

    path.unlink()
    scanned = client.post("/api/highlights/scan", json={"streamer": "streamer_a"}).json()
    assert scanned["missing"] == 1
    items = client.get("/api/highlights?streamer=streamer_a").json()["items"]
    assert len(items) == 1 and items[0]["status"] == "missing"

    # 挿し直せば元へ戻る。照合していない行はnewへ(matched_atが無いので断定しない)。
    path.write_bytes(b"\x00" * 32)
    client.post("/api/highlights/scan", json={"streamer": "streamer_a"})
    items = client.get("/api/highlights?streamer=streamer_a").json()["items"]
    assert items[0]["status"] == "new"


# ===== 照合結果の保存 =====


def _fake_result(segments, seconds=60.0):
    return {"seconds": seconds, "segments": segments, "pool": 3, "pool_hours": 5.0,
            "elapsed": 9.9, "scope": {"scope": "gift", "days": 14.0}}


def _segment(index, start, end, *, recording_id=None, media_start=None, gifts=()):
    """``Segment`` 1つ。giftは**複数**持てる —— segmentは最長8.3秒あり、その中に演出を
    持つgiftが複数入る。1件しか持てない形に戻すと、画面に映っている演出の主が落ちて
    別人の名前が付く(doc/HIGHLIGHT_MATCH.md)。"""
    return {"index": index, "start": start, "end": end, "recording_id": recording_id,
            "media_start": media_start, "votes": 900 if recording_id else 0,
            "ratio": 220.0 if recording_id else 0.0,
            "corr": 0.98 if recording_id else 0.0,
            "confidence": "high" if recording_id else "none",
            "gifts": list(gifts), "effect": []}


def _gift(event_id=111, diamonds=6000, media_time=108.0, *, name="Goal Highlight",
          key="k1", inside=True, primary=True):
    return {"event_id": event_id, "gift_id": 5655, "gift_name": name,
            "diamonds": diamonds, "gift_image": "https://cdn/x.png",
            "user_unique_id": "u1", "user_nickname": "N1", "user_id": "9",
            "identity_key": key, "media_time": media_time, "at": 8.0,
            "inside": inside, "primary": primary}


@pytest.fixture
def matched_highlight(client, highlight_roots, server):
    """1本走査して照合結果を入れた状態。(highlight_id, storage) を返す。"""
    highlight_roots["place"](highlight_roots["work"], "streamer_a", "highlights", "a.mp4")
    client.post("/api/highlights/scan", json={"streamer": "streamer_a"})
    highlight_id = client.get("/api/highlights?streamer=streamer_a").json()["items"][0]["id"]
    storage = server.runtime.storage
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 6.0),
        _segment(1, 6.0, 14.0),
        _segment(2, 14.0, 21.0),
    ]))
    return highlight_id, storage


def test_rematch_keeps_human_edits_across_a_reordered_result(client, matched_highlight):
    """再照合で並びが変わっても、人が確認・修正した内容は同じgift演出に付いたまま残る。

    ``idx`` で対応付けてはいけない(gift演出の数も並びも設定で変わる)。鍵はhighlight自身の
    時間軸の区間である —— highlightのfileは変わらないので、同じ区間を覆うgift演出は同じgift演出。"""
    highlight_id, storage = matched_highlight
    segments = client.get(f"/api/highlights/{highlight_id}").json()["segments"]
    approved_id = segments[1]["id"]
    edited_id = segments[2]["id"]
    client.patch(f"/api/highlights/{highlight_id}/segments/{approved_id}",
                 json={"approved": True, "memo": "これは採用"})
    client.patch(f"/api/highlights/{highlight_id}/segments/{edited_id}",
                 json={"start": 14.5, "end": 20.5})

    # 前にgift演出が2つ増え、最後の1つは今回の照合では出なかった。
    stats = storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 3.0),
        _segment(1, 3.0, 6.0),
        _segment(2, 6.2, 13.8, recording_id=None, media_start=None),
    ]))
    assert stats == {"kept": 2, "added": 1, "removed": 0, "dropped": 1, "gifts": 0}

    after = {row["id"]: row
             for row in client.get(f"/api/highlights/{highlight_id}").json()["segments"]}
    # 承認済みのgift演出は同じ行のまま、位置だけが新しい照合の値になる。
    assert after[approved_id]["approved"] == 1
    assert after[approved_id]["memo"] == "これは採用"
    assert after[approved_id]["idx"] == 2 and after[approved_id]["start"] == 6.2
    # 手で端を直したgift演出は今回出なかった。人の値のまま残り、出力からは外れる。
    assert after[edited_id]["dropped"] == 1 and after[edited_id]["excluded"] == 1
    assert after[edited_id]["start"] == 14.5 and after[edited_id]["end"] == 20.5


def test_rematch_drops_untouched_segments_but_keeps_edited_start(client,
                                                                 matched_highlight):
    """人が触っていないgift演出は消してよい。触ったgift演出だけが残る。"""
    highlight_id, storage = matched_highlight
    stats = storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 6.0),
    ]))
    assert stats == {"kept": 1, "added": 0, "removed": 2, "dropped": 0, "gifts": 0}
    assert len(client.get(f"/api/highlights/{highlight_id}").json()["segments"]) == 1


def test_rematch_shifts_media_start_for_a_hand_moved_segment(client, matched_highlight,
                                                             make_srv_recording):
    """端を手で動かしたgift演出は、その端を保ったまま録画側の位置が付け直される。

    録画の中の位置を決めるのは照合で、人が触ったのはhighlight側の端である。人のstartを
    残して機械のmedia_startをそのまま入れると、2つが別の場所を指す。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    segments = client.get(f"/api/highlights/{highlight_id}").json()["segments"]
    target = segments[2]["id"]
    client.patch(f"/api/highlights/{highlight_id}/segments/{target}",
                 json={"start": 15.0})

    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 6.0),
        _segment(1, 6.0, 14.0),
        _segment(2, 14.0, 21.0, recording_id=recording_id, media_start=300.0),
    ]))
    after = {row["id"]: row
             for row in client.get(f"/api/highlights/{highlight_id}").json()["segments"]}
    assert after[target]["start"] == 15.0
    # startを+1.0動かしたぶんだけ、録画側の位置も後ろへ寄る。
    assert after[target]["media_start"] == pytest.approx(301.0)


# ===== gift の差し替え =====


def test_candidates_refuses_when_the_segment_has_no_recording(client, matched_highlight):
    """録画が当たっていないgift演出には候補の母集団が無い。0件ではなく断る。"""
    highlight_id, _storage = matched_highlight
    segment_id = client.get(f"/api/highlights/{highlight_id}").json()["segments"][0]["id"]
    response = client.get(
        f"/api/highlights/{highlight_id}/segments/{segment_id}/candidates")
    assert response.status_code == 409


def test_candidates_lists_gifts_around_the_segment_window(
        client, server, matched_highlight, make_srv_recording, gift_builder):
    """gift演出のmedia窓の前後にあるgiftだけを候補にする。窓の外は演出と無関係になる。"""
    highlight_id, storage = matched_highlight
    session_id, recording_id, _path = make_srv_recording(unique_id="hlrec", ts_segments=4)
    recording = storage.get_recording(recording_id)
    started = recording["started_at"]
    storage.add_event(session_id, gift_builder("Rose", diamonds=10, at=started + 20.0))
    storage.add_event(session_id, gift_builder("Galaxy", diamonds=1000,
                                               at=started + 200.0))
    storage.flush()
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 8.0, recording_id=recording_id, media_start=20.0),
    ]))
    segment_id = client.get(f"/api/highlights/{highlight_id}").json()["segments"][0]["id"]

    body = client.get(
        f"/api/highlights/{highlight_id}/segments/{segment_id}/candidates?span=25"
    ).json()
    names = [item["gift_name"] for item in body["candidates"]]
    assert names == ["Rose"]
    assert body["candidates"][0]["media_time"] == pytest.approx(20.0, abs=2.0)
    # CDN URLはそのまま渡さない(署名付きで失効する)。解決できなければ空文字。
    assert not body["candidates"][0]["gift_image"].startswith("http")

    # 窓を広げれば遠いgiftも入る。
    wide = client.get(
        f"/api/highlights/{highlight_id}/segments/{segment_id}/candidates?span=300"
    ).json()
    assert {item["gift_name"] for item in wide["candidates"]} == {"Rose", "Galaxy"}


def test_adding_a_gift_fills_columns_from_the_event_and_marks_it_manual(
        client, server, matched_highlight, make_srv_recording, gift_builder):
    """付け替えで画面から受け取るのはeventのidだけ。名前も💎もDBから引き直す。

    印は gift行の ``manual`` で、gift演出の ``edited``(端を動かした)とは別である。1つにすると
    端を微調整しただけで人のgift差し替えが守られる(逆も起きる)。"""
    highlight_id, storage = matched_highlight
    session_id, recording_id, _path = make_srv_recording(unique_id="hlrec", ts_segments=4)
    recording = storage.get_recording(recording_id)
    storage.add_event(session_id, gift_builder(
        "Galaxy", diamonds=1000, at=recording["started_at"] + 25.0))
    storage.flush()
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 8.0, recording_id=recording_id, media_start=20.0),
    ]))
    segment_id = client.get(f"/api/highlights/{highlight_id}").json()["segments"][0]["id"]
    candidates = client.get(
        f"/api/highlights/{highlight_id}/segments/{segment_id}/candidates"
    ).json()["candidates"]
    event_id = candidates[0]["event_id"]

    body = client.post(f"/api/highlights/{highlight_id}/segments/{segment_id}/gifts",
                       json={"gift_event_id": event_id})
    assert body.status_code == 200
    segment = body.json()["segment"]
    assert len(segment["gifts"]) == 1
    gift = segment["gifts"][0]
    assert gift["gift_name"] == "Galaxy" and gift["diamonds"] == 1000
    assert gift["gift_event_id"] == event_id
    assert gift["gift_media_time"] is not None
    assert gift["manual"] is True
    # gift演出の端は触っていないので ``edited`` は立たない。
    assert segment["edited"] == 0
    # CDN URLはそのまま渡さない(署名付きで失効する)。
    assert not gift["gift_image"].startswith("http")


def test_a_hand_added_gift_survives_a_rematch(client, server, matched_highlight,
                                              make_srv_recording, gift_builder):
    """再照合はgiftを ``gift_event_id`` で結び、``manual`` の行のeventは置き換えない。

    時刻の近さで結んではいけない —— 「演出の直前の10💎が6000💎に勝つ」罠を、対応付けの
    側で踏み直すことになる。"""
    highlight_id, storage = matched_highlight
    session_id, recording_id, _path = make_srv_recording(unique_id="hlrec", ts_segments=4)
    recording = storage.get_recording(recording_id)
    storage.add_event(session_id, gift_builder(
        "Galaxy", diamonds=1000, at=recording["started_at"] + 25.0))
    storage.flush()
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 8.0, recording_id=recording_id, media_start=20.0),
    ]))
    segment_id = client.get(f"/api/highlights/{highlight_id}").json()["segments"][0]["id"]
    event_id = client.get(
        f"/api/highlights/{highlight_id}/segments/{segment_id}/candidates"
    ).json()["candidates"][0]["event_id"]
    client.post(f"/api/highlights/{highlight_id}/segments/{segment_id}/gifts",
                json={"gift_event_id": event_id})

    # 機械が別のgiftを出してくる再照合。人の1件は残り、機械の1件が足される。
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 8.0, recording_id=recording_id, media_start=20.0,
                 gifts=[_gift(event_id=999, diamonds=6000)]),
    ]))
    segment = client.get(f"/api/highlights/{highlight_id}").json()["segments"][0]
    by_event = {gift["gift_event_id"]: gift for gift in segment["gifts"]}
    assert set(by_event) == {event_id, 999}
    assert by_event[event_id]["manual"] is True
    assert by_event[event_id]["gift_name"] == "Galaxy"


def test_excluding_one_gift_leaves_the_others_in_the_segment(client, matched_highlight,
                                                             make_srv_recording):
    """gift 1件だけを外せること。gift演出単位でしか外せないと、gift 1件が消えただけで同じ
    gift演出の他のgiftまで巻き添えになる。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 8.0, recording_id=recording_id, media_start=20.0,
                 gifts=[_gift(event_id=111, diamonds=1000, name="Galaxy"),
                        _gift(event_id=222, diamonds=399, name="Spartan Helmet",
                              primary=False)]),
    ]))
    segment = client.get(f"/api/highlights/{highlight_id}").json()["segments"][0]
    target = next(g for g in segment["gifts"] if g["gift_name"] == "Galaxy")

    body = client.patch(
        f"/api/highlights/{highlight_id}/segments/{segment['id']}"
        f"/gifts/{target['id']}", json={"excluded": True})
    assert body.status_code == 200
    gifts = {g["gift_name"]: g for g in body.json()["segment"]["gifts"]}
    assert gifts["Galaxy"]["excluded"] is True
    assert gifts["Spartan Helmet"]["excluded"] is False


def test_pointing_at_a_new_primary_clears_the_old_one(client, matched_highlight,
                                                      make_srv_recording):
    """主はgift演出に1件だけ。2件が主を名乗るgift演出は、読む側のどちらが勝つかで表示が変わる。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 8.0, recording_id=recording_id, media_start=20.0,
                 gifts=[_gift(event_id=111, diamonds=1000, name="Galaxy"),
                        _gift(event_id=222, diamonds=399, name="Spartan Helmet",
                              primary=False)]),
    ]))
    segment = client.get(f"/api/highlights/{highlight_id}").json()["segments"][0]
    assert segment["primary"]["gift_name"] == "Galaxy"
    helmet = next(g for g in segment["gifts"] if g["gift_name"] == "Spartan Helmet")

    body = client.patch(
        f"/api/highlights/{highlight_id}/segments/{segment['id']}"
        f"/gifts/{helmet['id']}", json={"is_primary": True})
    after = body.json()["segment"]
    assert after["primary"]["gift_name"] == "Spartan Helmet"
    assert sum(1 for g in after["gifts"] if g["is_primary"]) == 1


def test_choosing_one_hit_marks_it_through_the_api(client, matched_highlight,
                                                   make_srv_recording):
    """「このgiftはこの1本を使う」を画面から立てられること。

    同じgiftが複数のhighlightに入るので、どれを使うかは機械の順位で決まっていた。順位は
    「そのgiftのアニメが映っているのはどれか」の代用で、実測(Whale diving 2,150💎)では
    3本すべてで代用が外れていた。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 8.0, recording_id=recording_id, media_start=20.0,
                 gifts=[_gift(event_id=111, diamonds=1000, name="Galaxy"),
                        _gift(event_id=222, diamonds=399, name="Spartan Helmet",
                              primary=False)]),
    ]))
    segment = client.get(f"/api/highlights/{highlight_id}").json()["segments"][0]
    helmet = next(g for g in segment["gifts"] if g["gift_name"] == "Spartan Helmet")

    body = client.patch(
        f"/api/highlights/{highlight_id}/segments/{segment['id']}"
        f"/gifts/{helmet['id']}", json={"chosen": True})
    assert body.status_code == 200
    gifts = {g["gift_name"]: g for g in body.json()["segment"]["gifts"]}
    assert gifts["Spartan Helmet"]["chosen"] is True
    # 主(``is_primary``)には触らない。gift演出の中の順位と、highlightどうしの選択は別物である。
    assert gifts["Galaxy"]["is_primary"] is True and gifts["Galaxy"]["chosen"] is False


def test_adding_a_gift_rejects_an_event_that_does_not_exist(client, matched_highlight,
                                                            make_srv_recording):
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec", ts_segments=4)
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 8.0, recording_id=recording_id, media_start=20.0),
    ]))
    segment_id = client.get(f"/api/highlights/{highlight_id}").json()["segments"][0]["id"]
    response = client.post(
        f"/api/highlights/{highlight_id}/segments/{segment_id}/gifts",
        json={"gift_event_id": 999999})
    assert response.status_code == 404


def test_segment_patch_no_longer_takes_a_single_gift(client, matched_highlight):
    """単数の ``gift_event_id`` をここへ残すと「gift演出のgift」という概念が戻り、実測で
    別人の名前が付いた形(高額な1件が範囲内の1件を押しのける)へ逆戻りする。"""
    highlight_id, _storage = matched_highlight
    segment_id = client.get(f"/api/highlights/{highlight_id}").json()["segments"][0]["id"]
    response = client.patch(f"/api/highlights/{highlight_id}/segments/{segment_id}",
                            json={"gift_event_id": 111})
    assert response.status_code == 422


# ===== 照合の投入 =====


def test_match_enqueues_a_job_and_refuses_a_second_one(client, highlight_roots, server):
    """照合はqueueへ投入して返す(同期実行しない)。二重投入は行のstatusで弾く。"""
    highlight_roots["place"](highlight_roots["work"], "streamer_a", "highlights", "a.mp4")
    client.post("/api/highlights/scan", json={"streamer": "streamer_a"})
    highlight_id = client.get("/api/highlights?streamer=streamer_a").json()["items"][0]["id"]

    body = client.post(f"/api/highlights/{highlight_id}/match",
                       json={"days": 7.0, "scope": "gift"})
    assert body.status_code == 200
    job_id = body.json()["job_id"]
    row = server.runtime.storage.get_media_job(job_id)
    assert row["kind"] == "highlight_match" and row["state"] == "pending"
    # 録画1本に属さないjobなので録画idを持たない。
    assert row["recording_id"] is None
    assert row["params"]["highlight_id"] == highlight_id
    # 既定値は match_highlight の署名が唯一の出所。渡さなかった項目は運ばない。
    assert set(row["params"]) == {"highlight_id", "days", "scope"}

    highlight = client.get(f"/api/highlights/{highlight_id}").json()["highlight"]
    assert highlight["status"] == "matching"
    # 指定した値はそのまま、指定しなかった項目はServerの既定で埋まる。指定分だけを
    # 残すと、待機中の行が「下限の指定なし」に見え、実際には設定の98💎が効いているのに
    # 「下限なしで照合される」と読めてしまう。
    from tictok.media import highlight_match

    assert highlight["scope"] == {**highlight_match.defaults(),
                                  "days": 7.0, "scope": "gift"}
    assert highlight["scope"]["min_diamonds"] == 98

    assert client.post(f"/api/highlights/{highlight_id}/match", json={}).status_code == 409


def test_match_refuses_when_the_file_is_gone(client, highlight_roots):
    path = highlight_roots["place"](highlight_roots["work"], "streamer_a", "highlights", "a.mp4")
    client.post("/api/highlights/scan", json={"streamer": "streamer_a"})
    highlight_id = client.get("/api/highlights?streamer=streamer_a").json()["items"][0]["id"]
    path.unlink()
    assert client.post(f"/api/highlights/{highlight_id}/match",
                       json={}).status_code == 404


def test_highlight_match_runs_in_the_instant_lane():
    """人が画面の前で待つjobなので即時lane。通常のlaneに入れると、長い焼き込みの後ろで
    数時間動かない。"""
    from tictok.record.media_queue import INSTANT_KINDS

    assert "highlight_match" in INSTANT_KINDS


# ===== 一覧の集計と削除 =====


def test_list_counts_exclude_the_segments_a_person_removed(client, matched_highlight,
                                                           make_srv_recording):
    """一覧の読みどころは「出力に入るのは何件で幾らぶんか」。消し込んだ物は数えない。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 8.0, recording_id=recording_id, media_start=20.0,
                 gifts=[_gift(diamonds=6000),
                        _gift(event_id=333, diamonds=199, name="Hearts",
                              primary=False)]),
        _segment(1, 8.0, 16.0, recording_id=recording_id, media_start=50.0,
                 gifts=[_gift(event_id=222, diamonds=100)]),
        _segment(2, 16.0, 22.0),
    ]))
    # giftがgift演出から別表へ出たので、意味の変わる数は名前も変えた。gift演出1つが複数のgiftを
    # 持つため「gift付きgift演出の数」と「giftの件数」は別の数になる。
    item = client.get("/api/highlights?streamer=streamer_a").json()["items"][0]
    assert item["segment_count"] == 3
    assert item["gift_segment_count"] == 2 and item["gift_total_count"] == 3
    assert item["top_diamonds"] == 6000 and item["gift_diamonds"] == 6299

    segments = client.get(f"/api/highlights/{highlight_id}").json()["segments"]
    client.patch(f"/api/highlights/{highlight_id}/segments/{segments[0]['id']}",
                 json={"excluded": True})
    item = client.get("/api/highlights?streamer=streamer_a").json()["items"][0]
    assert item["segment_count"] == 2
    assert item["gift_segment_count"] == 1 and item["gift_total_count"] == 1
    assert item["top_diamonds"] == 100 and item["gift_diamonds"] == 100


def test_delete_removes_the_row_but_not_the_file(client, highlight_roots):
    """highlightは外から来た素材で、こちらが作った成果物ではない。mp4には触らない。"""
    path = highlight_roots["place"](highlight_roots["work"], "streamer_a", "highlights", "a.mp4")
    client.post("/api/highlights/scan", json={"streamer": "streamer_a"})
    highlight_id = client.get("/api/highlights?streamer=streamer_a").json()["items"][0]["id"]

    body = client.delete(f"/api/highlights/{highlight_id}").json()
    assert body["deleted"] is True
    assert client.get("/api/highlights?streamer=streamer_a").json()["items"] == []
    assert path.is_file()
    # 走査すれば新しい行として戻る(手直しは戻らない)。
    assert client.post("/api/highlights/scan",
                       json={"streamer": "streamer_a"}).json()["added"] == 1


# ===== 再生URLと既定値 =====


def test_list_and_detail_carry_a_playable_url(client, highlight_roots):
    """再生URLはServerが名乗る。画面がpathから組み立てる形にはしない。

    名前を実pathへ解く口を作ると、そこから任意のdirを名乗れてしまう
    (``tictok.api.routes.clips`` が既に持っている方針)。"""
    path = highlight_roots["place"](highlight_roots["work"], "streamer_a", "highlights",
                                    "a.mp4", 64)
    client.post("/api/highlights/scan", json={"streamer": "streamer_a"})
    item = client.get("/api/highlights?streamer=streamer_a").json()["items"][0]
    highlight_id = item["id"]
    assert item["url"] == f"/api/highlights/{highlight_id}/media"
    detail = client.get(f"/api/highlights/{highlight_id}").json()["highlight"]
    assert detail["url"] == item["url"]

    played = client.get(item["url"])
    assert played.status_code == 200
    assert played.headers["content-type"] == "video/mp4"
    assert played.content == path.read_bytes()
    # Rangeを解すること(gift演出の頭出しはplayerのseekでやる)。
    part = client.get(item["url"], headers={"Range": "bytes=0-9"})
    assert part.status_code == 206 and len(part.content) == 10


def test_missing_file_has_no_url_and_media_is_a_404(client, highlight_roots):
    """実体が無い行はURLを名乗らない。押しても404になるbuttonを画面に出させない。"""
    path = highlight_roots["place"](highlight_roots["work"], "streamer_a", "highlights", "a.mp4")
    client.post("/api/highlights/scan", json={"streamer": "streamer_a"})
    highlight_id = client.get("/api/highlights?streamer=streamer_a").json()["items"][0]["id"]
    path.unlink()
    client.post("/api/highlights/scan", json={"streamer": "streamer_a"})

    item = client.get("/api/highlights?streamer=streamer_a").json()["items"][0]
    assert item["status"] == "missing" and item["url"] is None
    assert client.get(f"/api/highlights/{highlight_id}/media").status_code == 404


def test_list_reports_server_defaults_for_both_sides(client):
    """画面が既定値を書き写さずに済むよう、Serverが実際に効く値を名乗る。

    照合側と出力側で ``min_diamonds`` の意味が違うので、口を分けて返す(平らに混ぜると
    画面はどちらの下限を出しているのか言えない)。"""
    from tictok.media import highlight_export, highlight_match

    defaults = client.get("/api/highlights").json()["defaults"]
    assert defaults["match"] == highlight_match.defaults()
    assert defaults["export"] == highlight_export.defaults()
    # 設定値(演出gift下限)がそのまま出ること。routeが数字を書き写していない証拠。
    assert defaults["match"]["min_diamonds"] == 98


def test_match_request_rejects_an_unknown_field(client, highlight_roots):
    """知らないfieldは黙って捨てず弾く。捨てると、画面が送った値が何事も無く消えたまま
    「指定したはずの条件と違う結果」が出る。"""
    highlight_roots["place"](highlight_roots["work"], "streamer_a", "highlights", "a.mp4")
    client.post("/api/highlights/scan", json={"streamer": "streamer_a"})
    highlight_id = client.get("/api/highlights?streamer=streamer_a").json()["items"][0]["id"]
    response = client.post(f"/api/highlights/{highlight_id}/match",
                           json={"days": 7.0, "no_such_option": 1})
    assert response.status_code == 422


def test_unknown_highlight_is_a_404(client):
    assert client.get("/api/highlights/999999").status_code == 404
    assert client.get("/api/highlights/999999/media").status_code == 404
    assert client.delete("/api/highlights/999999").status_code == 404
    assert client.post("/api/highlights/999999/match", json={}).status_code == 404


# ===== 週ぜんたいの俯瞰(検証の面) =====


def test_coverage_lists_the_week_and_never_hides_the_misses(client, server):
    """その週のgiftが1件ずつ並び、highlightに1本も無い行も残ること。

    照合が正しいかを人が確かめられるのはこの面だけで、0件を落とすと「取りこぼしが無い
    ように見える一覧」が出来上がる。判定の中身は tests/test_highlight_coverage.py に在り、
    ここは**routeが素通しできているか**だけを見る(path の並び・下限の既定・iconの解決)。
    """
    from datetime import datetime

    storage = server.runtime.storage
    session_id = storage.create_session("covtest", 60)
    at = datetime(2026, 8, 30, 21, 0).timestamp()
    for name, diamonds in (("Goal Highlight", 6000), ("Rose", 1)):
        storage.add_event(session_id, {
            "kind": "gift", "time": at, "gift_name": name, "diamonds": diamonds,
            "gift_id": 5655, "gift_count": 1, "repeat_count": 1,
            "gift_image": "https://example.invalid/icon.png",
            "user": {"user_id": "7300000000001", "unique_id": "fan01",
                     "nickname": "FAN01", "avatar": "", "fans_level": 0,
                     "gifter_level": 0, "gifter_badge": "", "member_badge": ""},
        })
    storage.flush()

    body = client.get("/api/highlights/coverage?streamer=covtest&min_diamonds=0").json()
    names = [item["gift_name"] for item in body["items"]]
    assert names == ["Goal Highlight", "Rose"]      # 高額な順
    assert all(item["hits"] == [] for item in body["items"])
    assert body["totals"]["gifts"] == 2 and body["totals"]["matched"] == 0
    assert body["min_diamonds"] == 0

    # 既定は照合側と同じ設定値(98💎)。routeが数字を書き写していれば、ここで1💎が残る。
    from tictok.media import highlight_match

    default = client.get("/api/highlights/coverage?streamer=covtest").json()
    assert default["min_diamonds"] == highlight_match.defaults()["min_diamonds"]
    assert [item["gift_name"] for item in default["items"]] == ["Goal Highlight"]

    # eventが運んできたCDN URLはそのまま渡さない(署名付きで失効する)。
    assert not default["items"][0]["gift_image"].startswith("http")


def test_coverage_check_marks_a_gift_even_when_it_is_in_no_highlight(client, server):
    """「確認済み」の印がgift 1件ごとに残り、**当たりの無い行にも押せる**こと。

    印をgift演出(``approved``)に持たせると、highlightに1本も出ていないgift —— この面で人が
    一番確かめる相手 —— には残す場所が無くなる。ここはその行に押せることを見る。
    """
    from datetime import datetime

    storage = server.runtime.storage
    session_id = storage.create_session("chktest", 60)
    at = datetime(2026, 8, 30, 21, 0).timestamp()
    storage.add_event(session_id, {
        "kind": "gift", "time": at, "gift_name": "Fantastic Fly Love", "diamonds": 19999,
        "gift_id": 5655, "gift_count": 1, "repeat_count": 1, "gift_image": "",
        "user": {"user_id": "7300000000002", "unique_id": "fan02", "nickname": "FAN02",
                 "avatar": "", "fans_level": 0, "gifter_level": 0,
                 "gifter_badge": "", "member_badge": ""},
    })
    storage.flush()

    url = "/api/highlights/coverage?streamer=chktest"
    item = client.get(url).json()["items"][0]
    assert item["hits"] == [] and item["checked"] is False

    event_id = item["event_id"]
    response = client.post("/api/highlights/coverage/checks",
                           json={"gift_event_ids": [event_id], "checked": True})
    assert response.status_code == 200
    assert response.json() == {"gift_event_ids": [event_id], "checked": True}

    # 印は読み直しても残る(画面のstateではなくDBに在る)。
    body = client.get(url).json()
    assert body["items"][0]["checked"] is True
    assert body["totals"]["checked"] == 1

    # 付け直しは行を二重に積まない。
    client.post("/api/highlights/coverage/checks",
                json={"gift_event_ids": [event_id, event_id], "checked": True})
    assert client.get(url).json()["totals"]["checked"] == 1

    # 外すと消える。
    client.post("/api/highlights/coverage/checks",
                json={"gift_event_ids": [event_id], "checked": False})
    body = client.get(url).json()
    assert body["items"][0]["checked"] is False and body["totals"]["checked"] == 0

    # 知らないfieldは黙って捨てずに弾く(他の口と同じ約束)。
    assert client.post("/api/highlights/coverage/checks",
                       json={"gift_event_ids": [event_id], "checked": True,
                             "note": "x"}).status_code == 422
    # 空のlistは受けない。**何も起きない書き込み**を成功として返すと、押した印が
    # 付かなかったことに画面が気付けない。
    assert client.post("/api/highlights/coverage/checks",
                       json={"gift_event_ids": [], "checked": True}).status_code == 422


def test_coverage_needs_a_streamer_and_is_not_read_as_an_id(client):
    """``coverage`` が ``{highlight_id}`` として解釈されていたら422になる。

    path の並びに意味がある(先に宣言したrouteから照合される)ので、順序が入れ替わった
    ことをこのtestが気付く。"""
    assert client.get("/api/highlights/coverage").status_code == 400
    assert client.get("/api/highlights/coverage?streamer=  ").status_code == 400
    assert client.get(
        "/api/highlights/coverage?streamer=covtest&min_diamonds=-1").status_code == 400


# ===== 代表frame(突き合わせを目で確かめる) =====

_FFMPEG = pytest.mark.skipif(
    not (__import__("shutil").which("ffmpeg") and __import__("shutil").which("ffprobe")),
    reason="ffmpeg/ffprobe が要る",
)

FRAME_SECONDS = 3


def _make_highlight_mp4(path: Path) -> Path:
    """3秒の実mp4。0 byteのdummyでは「frameが出る」ことを確かめられない。"""
    import subprocess

    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc2=size=160x288:rate=30:duration={FRAME_SECONDS}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True)
    return path


def test_frame_url_is_built_in_one_place(server):
    """URLを組む場所はServerの1関数だけにする。同じ組み立てが2箇所に在ると、片方だけが
    引数を足した日に一方の面だけ絵が出なくなる(404は画面には壊れた画像箱にしか見えない)。

    位置が判らないgift演出では **None** を返す —— それらしい秒(gift演出の頭)で埋めると、位置が
    判っているように見える絵が並ぶ。"""
    from tictok.api.routes import highlights as route

    assert route.highlight_frame_url(7, 23.5) == "/api/highlights/7/frame?at=23.500"
    assert route.highlight_frame_url(7, 1.0, 320) == "/api/highlights/7/frame?at=1.000&w=320"
    assert route.highlight_frame_url(7, None) is None


@_FFMPEG
def test_frame_returns_a_jpeg_and_caches_it(client, highlight_roots):
    """一覧に20〜60枚並ぶので、cacheが要る。素材は不変なので使い回してよい。"""
    from tictok.media import highlight_frames

    _make_highlight_mp4(
        highlight_roots["work"] / "streamer_a" / "highlights" / "a.mp4")
    client.post("/api/highlights/scan", json={"streamer": "streamer_a"})
    highlight_id = client.get("/api/highlights?streamer=streamer_a").json()["items"][0]["id"]

    response = client.get(f"/api/highlights/{highlight_id}/frame?at=1.0")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content[:2] == b"\xff\xd8"          # JPEGのSOI
    assert "max-age=" in response.headers["cache-control"]

    # 2度目は切り直さない。cacheのfile名は素材のbytes/mtimeを含むので、同じ素材なら同じ1枚。
    cached = list(highlight_frames.cache_dir().glob("hl_*_1000ms_w*.jpg"))
    assert len(cached) == 1
    before = cached[0].stat().st_mtime_ns
    assert client.get(f"/api/highlights/{highlight_id}/frame?at=1.0").status_code == 200
    assert cached[0].stat().st_mtime_ns == before

    # 幅を変えれば別の1枚(丸めて使い回さない)。
    assert client.get(
        f"/api/highlights/{highlight_id}/frame?at=1.0&w=64").status_code == 200
    assert len(list(highlight_frames.cache_dir().glob("hl_*_1000ms_w*.jpg"))) == 2


@_FFMPEG
def test_frame_beyond_the_length_is_a_404_not_a_rounded_picture(client, highlight_roots):
    """尺を超えた ``at`` で最後のframeを返してはいけない。丸めた絵は「その位置の絵」として
    並ぶので、範囲外を指したことが画面から見えなくなる。"""
    _make_highlight_mp4(highlight_roots["work"] / "streamer_a" / "highlights" / "a.mp4")
    client.post("/api/highlights/scan", json={"streamer": "streamer_a"})
    highlight_id = client.get("/api/highlights?streamer=streamer_a").json()["items"][0]["id"]
    assert client.get(
        f"/api/highlights/{highlight_id}/frame?at={FRAME_SECONDS + 10}"
    ).status_code == 404


def test_frame_rejects_a_bad_position_or_width(client, highlight_roots):
    """黙って丸めない。丸めると画面は指定が効いていると思ったまま別の物を受け取る。"""
    highlight_roots["place"](highlight_roots["work"], "streamer_a", "highlights", "a.mp4")
    client.post("/api/highlights/scan", json={"streamer": "streamer_a"})
    highlight_id = client.get("/api/highlights?streamer=streamer_a").json()["items"][0]["id"]
    assert client.get(f"/api/highlights/{highlight_id}/frame?at=-1").status_code == 400
    assert client.get(f"/api/highlights/{highlight_id}/frame?at=1&w=0").status_code == 400
    assert client.get(
        f"/api/highlights/{highlight_id}/frame?at=1&w=99999").status_code == 400
    assert client.get("/api/highlights/999999/frame?at=1").status_code == 404


# ===== 時間軸へ敷くコマ(filmstrip) =====


@_FFMPEG
def test_filmstrip_sheet_is_built_once_and_served(client, highlight_roots):
    """軸1本を絵で埋めるのに1枚のsheetで済ませる。1枚ずつのfileで敷くと、軸を描くたびに
    数十のHTTP往復が要る(録画側のseek barが既にspriteにしているのと同じ理由)。"""
    from tictok.media import highlight_frames

    _make_highlight_mp4(highlight_roots["work"] / "streamer_a" / "highlights" / "a.mp4")
    client.post("/api/highlights/scan", json={"streamer": "streamer_a"})
    highlight_id = client.get("/api/highlights?streamer=streamer_a").json()["items"][0]["id"]

    spec = client.get(f"/api/highlights/{highlight_id}/thumbnails")
    assert spec.status_code == 200
    body = spec.json()
    # 画面はtileの番号からしか秒を知らない。仕様が欠けると絵と秒が黙ってずれる。
    assert body["count"] > 0
    assert body["interval_seconds"] > 0
    assert body["tile_width"] > 0 and body["tile_height"] > 0
    assert body["columns"] > 0 and body["rows"] > 0
    assert body["count"] <= body["columns"] * body["rows"]

    sheet = client.get(body["url"])
    assert sheet.status_code == 200
    assert sheet.headers["content-type"] == "image/jpeg"
    assert sheet.content[:2] == bytes.fromhex("ffd8")     # JPEGのSOI
    assert "max-age=" in sheet.headers["cache-control"]

    # 2度目は焼き直さない。素材は不変なので、同じ素材なら同じ1枚である。
    files = list(highlight_frames.cache_dir().glob("strip_*.jpg"))
    assert len(files) == 1
    before = files[0].stat().st_mtime_ns
    assert client.get(f"/api/highlights/{highlight_id}/thumbnails").status_code == 200
    assert files[0].stat().st_mtime_ns == before


@_FFMPEG
def test_filmstrip_url_changes_when_the_material_is_replaced(client, highlight_roots):
    """URLへsheetの鍵(素材のbytesとmtime)を混ぜる。idだけのURLにすると、同じ名前で
    highlightを置き直したときにbrowserのcacheが**古い絵を新しい仕様で**読み、絵と秒が
    黙ってずれる(画面はtileの番号からしか秒を知らない)。"""
    path = _make_highlight_mp4(
        highlight_roots["work"] / "streamer_a" / "highlights" / "a.mp4")
    client.post("/api/highlights/scan", json={"streamer": "streamer_a"})
    highlight_id = client.get("/api/highlights?streamer=streamer_a").json()["items"][0]["id"]
    first = client.get(f"/api/highlights/{highlight_id}/thumbnails").json()["url"]

    import subprocess

    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=160x288:rate=30:duration=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True)
    second = client.get(f"/api/highlights/{highlight_id}/thumbnails").json()["url"]
    assert first != second


def test_filmstrip_is_a_404_when_the_highlight_or_sheet_is_missing(client,
                                                                  highlight_roots):
    """焼く口が先である。sheetだけを先に頼まれても、その場で焼いて返さない ――
    仕様(刻み・grid)を伴わない絵は、画面には秒へ写せない1枚でしかない。"""
    highlight_roots["place"](highlight_roots["work"], "streamer_a", "highlights", "a.mp4")
    client.post("/api/highlights/scan", json={"streamer": "streamer_a"})
    highlight_id = client.get("/api/highlights?streamer=streamer_a").json()["items"][0]["id"]
    assert client.get(
        f"/api/highlights/{highlight_id}/thumbnails.jpg").status_code == 404
    assert client.get("/api/highlights/999999/thumbnails").status_code == 404


def test_recording_frame_refuses_when_the_segment_has_no_recording(client, highlight_roots,
                                                                   server):
    """録画が当たっていないgift演出は409。「候補が無い」ではなく「そもそも探せない」であり、
    ``/candidates`` が同じ理由で409を返すのと揃える。"""
    highlight_roots["place"](highlight_roots["work"], "streamer_a", "highlights", "a.mp4")
    client.post("/api/highlights/scan", json={"streamer": "streamer_a"})
    highlight_id = client.get("/api/highlights?streamer=streamer_a").json()["items"][0]["id"]
    storage = server.runtime.storage
    with storage._lock:
        cursor = storage._conn.execute(
            "INSERT INTO highlight_segments (highlight_id, idx, start, end)"
            " VALUES (?, 0, 0.0, 6.0)", (highlight_id,))
        storage._conn.commit()
    segment_id = cursor.lastrowid
    assert client.get(
        f"/api/highlights/{highlight_id}/segments/{segment_id}/frame?at=1.0"
    ).status_code == 409
    assert client.get(
        f"/api/highlights/{highlight_id}/segments/999999/frame?at=1.0"
    ).status_code == 404


# ===== 録画1本に属さないjob(突き合わせ・書き出し)の再実行 =====


def _recordingless_job(server, state: str) -> str:
    """録画idを持たないjobを1件、指定のstateで置く。

    突き合わせも書き出しも「どの録画のどこか」を求めるのがjob本体なので、投入時点では
    録画idが無い(``media_job_queue.recording_id`` はNULL可)。"""
    import secrets

    storage = server.runtime.storage
    # 台帳はtest間で共有される(module singletonのstorage)ので、idは毎回変える。
    job_id = f"nullrec-{state}-{secrets.token_hex(3)}"
    storage.enqueue_media_job(job_id, "highlight_match", None,
                              title="突き合わせ streamer_a / a.mp4",
                              params={"highlight_id": 1})
    storage.start_media_job(job_id)
    storage.finish_media_job(job_id, state, error="test" if state == "failed" else None)
    return job_id


def test_retry_does_not_claim_a_deleted_recording_for_a_recordingless_job(client, server):
    """``get_recording(None)`` は必ずNoneを返す。そこを素通しにしていると、**一度も録画を
    持たなかったjob**が「録画が見つかりません（削除済み）」という嘘の理由で弾かれ、失敗した
    突き合わせを人が二度と再開できない。"""
    job_id = _recordingless_job(server, "failed")
    response = client.post(f"/api/jobs/{job_id}/retry")
    assert response.status_code == 200, response.text
    assert response.json()["requeued"] == 1
    assert server.runtime.storage.get_media_job(job_id)["state"] == "pending"


def test_retry_of_a_finished_recordingless_job_points_at_the_right_screen(client, server):
    """完了済みからのやり直しは「同じ行の再開」ではなく新しい投入である。録画を持たない
    jobの二重投入は**その種別の台帳**(highlightの行のstatus)が抑えているので、ここで作ると
    抑止を素通りした2本目が走る。作らずに出所の画面へ案内する。"""
    job_id = _recordingless_job(server, "completed")
    response = client.post(f"/api/jobs/{job_id}/retry")
    assert response.status_code == 409
    assert "元の画面" in response.json()["detail"]


def test_recordingless_jobs_do_not_poison_the_recording_id_lookups(server):
    """NULLの録画idが録画単位の集合へ紛れ込まないこと。紛れると容量整理が「使用中の録画」を
    数え損ね、sweepの抑止listが壊れる。"""
    import secrets

    storage = server.runtime.storage
    _recordingless_job(server, "failed")
    storage.enqueue_media_job(f"nullrec-pending-{secrets.token_hex(3)}",
                              "highlight_match", None,
                              title="突き合わせ streamer_a / b.mp4")
    assert None not in storage.busy_recording_ids()
    assert storage.media_job_recording_ids_in_states(
        ["highlight_match"], ["failed"]) == {"highlight_match": set()}
    # (kind, None) は残るが、実在の録画idと照合されることはない(二重投入judgeは
    # recording_idで引くので、Noneの行はそもそも鍵を持たない)。
    keys = storage.pending_media_job_keys()
    assert ("highlight_match", None) in keys
    assert storage.pending_media_job_for("highlight_match", None) is None


# ===== gift演出とgiftの2段の対応付け =====


def test_moving_a_segment_edge_does_not_protect_the_gift(client, matched_highlight,
                                                         make_srv_recording):
    """``edited``(端を動かした)と ``manual``(giftを差し替えた)を分ける理由そのもの。

    1つの印にすると、**端を微調整しただけで人のgift差し替えが「守られた」ことになり**、
    再照合が機械の答えで上書きすべき行を守ってしまう(逆も起きる)。端を動かしたgift演出でも、
    人が触っていないgiftは次の照合の値で更新されること。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 8.0, recording_id=recording_id, media_start=20.0,
                 gifts=[_gift(event_id=111, diamonds=1000, name="Galaxy")]),
    ]))
    segment_id = client.get(f"/api/highlights/{highlight_id}").json()["segments"][0]["id"]
    client.patch(f"/api/highlights/{highlight_id}/segments/{segment_id}",
                 json={"start": 1.0})

    # 同じeventだが機械が名前と💎を出し直した(gift iconの取り込み等で普通に起きる)。
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 8.0, recording_id=recording_id, media_start=20.0,
                 gifts=[_gift(event_id=111, diamonds=1088, name="Fireworks")]),
    ]))
    segment = client.get(f"/api/highlights/{highlight_id}").json()["segments"][0]
    # 端は人のものが残る。giftは人が触っていないので機械の値で更新される。
    assert segment["start"] == 1.0 and segment["edited"] == 1
    assert segment["gifts"][0]["gift_name"] == "Fireworks"
    assert segment["gifts"][0]["diamonds"] == 1088
    assert segment["gifts"][0]["manual"] is False


def test_a_hand_moved_edge_does_not_move_the_gift(client, matched_highlight,
                                                  make_srv_recording):
    """``gift_media_time`` は録画のmedia軸の**絶対秒**である。人がgift演出の端を動かしても、
    giftは録画の中で動いていない。差で持つと端を1秒ずらした瞬間にgiftまで1秒動く。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 10.0, 18.0, recording_id=recording_id, media_start=100.0,
                 gifts=[_gift(event_id=111, media_time=103.0)]),
    ]))
    segment = client.get(f"/api/highlights/{highlight_id}").json()["segments"][0]
    assert segment["gifts"][0]["gift_media_time"] == 103.0
    assert segment["gifts"][0]["at"] == 13.0        # 10.0 + (103.0 - 100.0)

    client.patch(f"/api/highlights/{highlight_id}/segments/{segment['id']}",
                 json={"start": 11.0})
    after = client.get(f"/api/highlights/{highlight_id}").json()["segments"][0]
    # 録画の中のgiftの位置は動かない。highlight内の秒だけが端の移動ぶん動く。
    assert after["gifts"][0]["gift_media_time"] == 103.0
    assert after["gifts"][0]["at"] == 14.0


def test_rematch_drops_one_gift_without_taking_the_segment(client, matched_highlight,
                                                           make_srv_recording):
    """gift 1件が消えてもgift演出は残ること。gift演出ごと落とすと、同じgift演出の他のgiftまで
    巻き添えになる。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 8.0, recording_id=recording_id, media_start=20.0,
                 gifts=[_gift(event_id=111, name="Galaxy"),
                        _gift(event_id=222, name="Spartan Helmet", primary=False)]),
    ]))
    # 2件目が今回の照合では出なかった。人の入力を持たないので消える。
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 8.0, recording_id=recording_id, media_start=20.0,
                 gifts=[_gift(event_id=111, name="Galaxy")]),
    ]))
    segments = client.get(f"/api/highlights/{highlight_id}").json()["segments"]
    assert len(segments) == 1
    assert [g["gift_name"] for g in segments[0]["gifts"]] == ["Galaxy"]


def test_a_gift_a_person_excluded_survives_as_dropped(client, matched_highlight,
                                                      make_srv_recording):
    """人が外したgiftは、次の照合に出なくても消さない。判断そのものが記録である。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 8.0, recording_id=recording_id, media_start=20.0,
                 gifts=[_gift(event_id=111, name="Galaxy"),
                        _gift(event_id=222, name="Spartan Helmet", primary=False)]),
    ]))
    segment = client.get(f"/api/highlights/{highlight_id}").json()["segments"][0]
    helmet = next(g for g in segment["gifts"] if g["gift_name"] == "Spartan Helmet")
    client.patch(f"/api/highlights/{highlight_id}/segments/{segment['id']}"
                 f"/gifts/{helmet['id']}", json={"excluded": True})

    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 8.0, recording_id=recording_id, media_start=20.0,
                 gifts=[_gift(event_id=111, name="Galaxy")]),
    ]))
    gifts = {g["gift_name"]: g
             for g in client.get(f"/api/highlights/{highlight_id}"
                                 ).json()["segments"][0]["gifts"]}
    assert gifts["Spartan Helmet"]["dropped"] is True
    assert gifts["Spartan Helmet"]["excluded"] is True
    assert gifts["Galaxy"]["dropped"] is False


def test_gifts_are_paired_by_event_id_not_by_time(client, matched_highlight,
                                                  make_srv_recording):
    """対応付けの鍵は ``gift_event_id`` だけ。時刻の近さで結ぶと「演出の直前の10💎が
    6000💎に勝つ」罠を、対応付けの側で踏み直すことになる。

    ほぼ同じ秒に別のeventが来ても、別のgiftとして扱われること。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 8.0, recording_id=recording_id, media_start=20.0,
                 gifts=[_gift(event_id=111, media_time=25.0, name="Galaxy")]),
    ]))
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 0.0, 8.0, recording_id=recording_id, media_start=20.0,
                 gifts=[_gift(event_id=222, media_time=25.01, name="Rose")]),
    ]))
    gifts = client.get(f"/api/highlights/{highlight_id}").json()["segments"][0]["gifts"]
    # 0.01秒しか違わないが別のevent。前のgiftは消え、新しいgiftが入る(結ばれない)。
    assert [g["gift_event_id"] for g in gifts] == [222]
    assert gifts[0]["gift_name"] == "Rose"


def test_a_gift_outside_the_segment_is_marked_not_dropped(client, matched_highlight,
                                                          make_srv_recording):
    """``inside=False`` は「``gift_lead`` で手前へ伸ばした窓に入っただけ」の印である。
    **highlightにはその手前の映像が無い**(別の時刻のgift演出が繋がっているだけ)ので、画面が
    その旨を言えるように行として残し、印で名乗る。"""
    highlight_id, storage = matched_highlight
    _session_id, recording_id, _path = make_srv_recording(unique_id="hlrec")
    storage.save_highlight_match(highlight_id, _fake_result([
        _segment(0, 10.0, 18.0, recording_id=recording_id, media_start=100.0,
                 gifts=[_gift(event_id=111, media_time=97.0, inside=False),
                        _gift(event_id=222, media_time=103.0, primary=False)]),
    ]))
    gifts = {g["gift_event_id"]: g
             for g in client.get(f"/api/highlights/{highlight_id}"
                                 ).json()["segments"][0]["gifts"]}
    assert gifts[111]["inside"] is False and gifts[222]["inside"] is True
    # 手前の窓のgiftはgift演出の頭より手前を指す(highlightにその映像は無い)。
    assert gifts[111]["at"] == 7.0 and gifts[222]["at"] == 13.0
