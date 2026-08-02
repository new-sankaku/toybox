"""笑い声のシーン検索と一括生成の配線。

engineそのもの(確率列の作り方・窓の畳み方)は test_laugh_audio.py が見る。ここで見るのは
「検出した笑いが検索から引けるか」と「一括生成の種別として振る舞うか」だけ:

  1. /api/search が source=laugh を受け、語で一致する側(音声/Comment)と混ぜて引けること
  2. 済み判定が**検索indexの有無**であること — 解析だけ済んで検索に出ない録画を拾い直せる
  3. engine未設定のまま一括投入すると、queueを1件も積まずに理由を返すこと
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


def test_the_search_api_accepts_laughter_as_a_source(client, server, monkeypatch):
    captured = _capture_sources(server, monkeypatch)
    res = client.get("/api/search", params={"q": "笑い声", "sources": "laugh"})
    assert res.status_code == 200
    assert captured["sources"] == [server.indexer.SOURCE_LAUGH]


def test_laughter_can_be_searched_together_with_speech_and_comments(client, server,
                                                                    monkeypatch):
    """語で探しながら笑いも混ぜられること。片方しか選べないと同じ場面を2回探すことになる。"""
    captured = _capture_sources(server, monkeypatch)
    client.get("/api/search", params={"q": "x", "sources": "stt,comment,laugh"})
    assert captured["sources"] == [server.indexer.SOURCE_STT,
                                   server.indexer.SOURCE_COMMENT,
                                   server.indexer.SOURCE_LAUGH]


def test_an_unknown_source_is_dropped_rather_than_queried(client, server, monkeypatch):
    captured = _capture_sources(server, monkeypatch)
    client.get("/api/search", params={"q": "x", "sources": "laugh,nope"})
    assert captured["sources"] == [server.indexer.SOURCE_LAUGH]


# --------------------------------------------------------------------------- 一括生成


def test_laughter_is_a_bulk_kind_that_reads_from_segments(server):
    assert "laugh" in server.bulk.BULK_KINDS
    # mp4が無くても.tsから解析できる。素材の有無を見ずに判定すると、単体では処理できる
    # 録画が一括だけ弾かれる。
    assert "laugh" in server.bulk.BULK_HLS_KINDS
    assert server.bulk.BULK_KIND_TITLES["laugh"] == "笑い声分析"


def test_done_is_decided_by_the_search_index_not_the_sidecar(server):
    """確率列だけ在ってindexが無い録画は「解析済みだが検索に出ない」。sidecarで済みに
    すると誰も拾い直せなくなる。"""
    recording = {"id": 5, "status": "completed"}
    facts = {"has_file": True, "has_hls": True}
    laugh = server.indexer.SOURCE_LAUGH

    assert server.bulk._bulk_classify("laugh", recording, facts, None,
                                      indexed={}) == (True, "")
    assert server.bulk._bulk_classify("laugh", recording, facts, None,
                                      indexed={5: {laugh: 12}}) == (False, "done")
    # 別sourceだけ在る録画は済みではない(転写済みでも笑いは未解析)。
    assert server.bulk._bulk_classify(
        "laugh", recording, facts, None,
        indexed={5: {server.indexer.SOURCE_STT: 900}}) == (True, "")


def test_a_recording_with_no_material_is_not_a_laughter_target(server):
    ok, reason = server.bulk._bulk_classify(
        "laugh", {"id": 5, "status": "completed"},
        {"has_file": False, "has_hls": False}, None, indexed={})
    assert (ok, reason) == (False, "no_source")


def test_a_recording_still_being_captured_is_not_a_target(server):
    ok, reason = server.bulk._bulk_classify(
        "laugh", {"id": 5, "status": "recording"},
        {"has_file": True, "has_hls": True}, None, indexed={})
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
