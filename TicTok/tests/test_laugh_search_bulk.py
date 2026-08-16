"""笑い声の一覧と一括生成の配線。

engineそのもの(確率列の作り方・窓の畳み方)は test_laugh_audio.py が見る。ここで見るのは
「検出した笑いが一覧から引けるか」と「一括生成の種別として振る舞うか」だけ:

  1. 笑い声は**語での検索には混ざらない**こと — 音が根拠で当たる語を持たないため、
     source=laugh を受け付けていた頃は「笑い声」と打った時だけ出る隠しmodeだった
  2. 専用の一覧(/api/search/laughs)が語を受け取らず、強さ・長さで並べ替えられること
  3. 済み判定が**indexを張った条件**であること — 解析だけ済んで一覧に出ない録画も、
     共演中を外す前に張った録画も拾い直せる
  4. engine未設定のまま一括投入すると、queueを1件も積まずに理由を返すこと
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def server(env_guard):
    # env_guard を先に効かせてから import する。tictok.api.runtime は import 時に
    # Storage / instance lock / record dir を掴むため、順序が逆だと本番を掴む
    # (test_clip_candidates.py と同じ理由・同じ順序)。
    from types import SimpleNamespace

    import tictok.server as srv
    from fastapi import HTTPException
    from tictok.api import runtime
    from tictok.api.routes import bulk
    from tictok.media import laugh_audio
    from tictok.search import indexer

    assert not str(runtime.RECORD_DIR).lower().endswith("tictok\\recordings")
    return SimpleNamespace(app=srv.app, runtime=runtime, storage=runtime.storage,
                           bulk=bulk, indexer=indexer, laugh_audio=laugh_audio,
                           HTTPException=HTTPException)


@pytest.fixture
def client(server):
    # context manager として使わないこと(test_server.py と同じ理由: lifespanが走ると
    # shutdownでstorageが閉じ、後続testが使えなくなる)。
    return TestClient(server.app)


def _capture_sources(server, monkeypatch) -> dict:
    captured: dict = {}

    def fake_search(query, sources, ids, since, until, order, limit, offset):
        captured["sources"] = sources
        return {"total": 0, "items": [], "mode": "fts", "hint": "", "terms": []}

    monkeypatch.setattr(server.storage, "search_scenes", fake_search)
    return captured


# --------------------------------------------------------------------------- 検索


def _capture_laughs(server, monkeypatch) -> dict:
    captured: dict = {}

    def fake_laughs(unique_ids, order, limit, offset):
        captured.update(unique_ids=unique_ids, order=order, limit=limit, offset=offset)
        return {"total": 0, "items": [], "mode": "laugh", "hint": "", "terms": []}

    monkeypatch.setattr(server.storage, "laugh_scenes", fake_laughs)
    return captured


def test_the_word_search_does_not_accept_laughter_as_a_source(client, server, monkeypatch):
    """語で当たる本文を持たない行を語の検索へ混ぜない。混ぜていた頃は、`ガンダム` で
    探しても笑いは1件も出ず、「笑い声」と打った時だけ一覧に化けていた。"""
    captured = _capture_sources(server, monkeypatch)
    res = client.get("/api/search", params={"q": "x", "sources": "stt,comment,laugh"})
    assert res.status_code == 200
    assert captured["sources"] == [server.indexer.SOURCE_STT, server.indexer.SOURCE_COMMENT]


def test_an_unknown_source_is_dropped_rather_than_queried(client, server, monkeypatch):
    captured = _capture_sources(server, monkeypatch)
    client.get("/api/search", params={"q": "x", "sources": "stt,nope"})
    assert captured["sources"] == [server.indexer.SOURCE_STT]


def test_the_laughter_list_takes_no_search_word(client, server, monkeypatch):
    """語を受け取らないことがこのendpointの存在理由。qを足したくなったらそれは検索である。"""
    captured = _capture_laughs(server, monkeypatch)
    res = client.get("/api/search/laughs")
    assert res.status_code == 200
    assert captured == {"unique_ids": [], "order": "time", "limit": 200, "offset": 0}


def test_the_laughter_list_can_be_ordered_by_strength_and_length(client, server,
                                                                 monkeypatch):
    """語の一致度が無い代わりに、強さと長さが「どれを開くか」の手掛かりになる。"""
    captured = _capture_laughs(server, monkeypatch)
    for order in ("strength", "length", "time"):
        client.get("/api/search/laughs", params={"order": order})
        assert captured["order"] == order


def test_an_unknown_order_falls_back_to_time_instead_of_reaching_sql(client, server,
                                                                    monkeypatch):
    captured = _capture_laughs(server, monkeypatch)
    client.get("/api/search/laughs", params={"order": "h.body; DROP TABLE"})
    assert captured["order"] == "time"


def test_the_laughter_list_narrows_to_the_selected_streamer(client, server, monkeypatch):
    captured = _capture_laughs(server, monkeypatch)
    client.get("/api/search/laughs", params={"unique_ids": "@who,", "offset": "200"})
    assert captured["unique_ids"] == ["@who"]
    assert captured["offset"] == 200


# --------------------------------------------------------------------------- 一括生成


def test_laughter_is_a_bulk_kind_that_reads_from_segments(server):
    assert "laugh" in server.bulk.BULK_KINDS
    # mp4が無くても.tsから解析できる。素材の有無を見ずに判定すると、単体では処理できる
    # 録画が一括だけ弾かれる。
    assert "laugh" in server.bulk.BULK_HLS_KINDS
    assert server.bulk.BULK_KIND_TITLES["laugh"] == "笑い声分析"


def _current_meta(server) -> dict:
    from tictok.core.config import get_laugh_index_exclude_coop
    return {"version": server.indexer.LAUGH_INDEX_VERSION,
            "mode": get_laugh_index_exclude_coop()}


def test_done_is_decided_by_the_index_conditions_not_the_sidecar(server):
    """確率列だけ在ってindexが無い録画は「解析済みだが検索に出ない」。sidecarで済みに
    すると誰も拾い直せなくなる。行の有無でも足りない: 共演中を外す条件が違うindexは、
    同じ行が別の意味を持つ。"""
    recording = {"id": 5, "status": "completed"}
    facts = {"has_file": True, "has_hls": True}

    assert server.bulk._bulk_classify("laugh", recording, facts, None,
                                      laugh_meta={}) == (True, "")
    assert server.bulk._bulk_classify(
        "laugh", recording, facts, None,
        laugh_meta={5: _current_meta(server)}) == (False, "done")


def test_an_index_built_before_the_coop_exclusion_is_a_target_again(server):
    """条件を記録していないindex(この仕組みより前に張ったもの)には共演中の笑いが
    そのまま入っている。済みのままにすると、誰も張り直せない。"""
    recording = {"id": 5, "status": "completed"}
    facts = {"has_file": True, "has_hls": True}
    stale_version = {**_current_meta(server),
                     "version": server.indexer.LAUGH_INDEX_VERSION - 1}
    other_mode = {**_current_meta(server), "mode": "none"}

    assert server.bulk._bulk_classify("laugh", recording, facts, None,
                                      laugh_meta={5: {}}) == (True, "")
    assert server.bulk._bulk_classify("laugh", recording, facts, None,
                                      laugh_meta={5: stale_version}) == (True, "")
    assert server.bulk._bulk_classify("laugh", recording, facts, None,
                                      laugh_meta={5: other_mode}) == (True, "")


def test_a_recording_with_no_material_is_not_a_laughter_target(server):
    ok, reason = server.bulk._bulk_classify(
        "laugh", {"id": 5, "status": "completed"},
        {"has_file": False, "has_hls": False}, None, laugh_meta={})
    assert (ok, reason) == (False, "no_source")


def test_a_recording_still_being_captured_is_not_a_target(server):
    ok, reason = server.bulk._bulk_classify(
        "laugh", {"id": 5, "status": "recording"},
        {"has_file": True, "has_hls": True}, None, laugh_meta={})
    assert (ok, reason) == (False, "recording")


async def test_bulk_refuses_to_queue_while_the_engine_is_unconfigured(server,
                                                                      monkeypatch):
    """model未配置のまま積むと、台帳が同じerrorで録画数ぶん埋まるだけになる。"""
    monkeypatch.setattr(server.laugh_audio, "laugh_status",
                        lambda: {"configured": False, "enabled": False})
    payload = server.bulk.BulkQueueRequest(kind="laugh")
    with pytest.raises(server.HTTPException) as caught:
        await server.bulk._bulk_queue_laugh(payload)
    assert caught.value.status_code == 503
    assert "笑い声検出" in str(caught.value.detail)
