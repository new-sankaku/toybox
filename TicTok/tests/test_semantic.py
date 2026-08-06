"""意味検索indexと再生位置の整合。

守りたい不変条件は1つ: **意味検索が返す秒は、今のsearch_hitsの秒と一致する**。
indexは構築時のsnapshotを持つので、文字起こしのやり直しや時間軸の張り直しで
search_hits側だけが動くと、意味検索だけが古い軸を名乗る(実測で最大約20分)。
"""
import asyncio

import numpy as np
import pytest

from tictok.search import semantic


DIM = 16


class _CharEmbedder(semantic.Embedder):
    """文字のbagをvectorにする決定論的な埋め込み。外部serverを要さず、似た文が近くなる。"""

    @property
    def name(self) -> str:
        return "test-embedder"

    async def embed(self, texts: list) -> np.ndarray:
        out = np.zeros((len(texts), DIM), dtype=np.float32)
        for row, text in enumerate(texts):
            for char in text:
                out[row][ord(char) % DIM] += 1.0
        # 全成分0だと正規化後も0のままで、どのqueryとも無相関になる。
        out += 0.01
        return out


@pytest.fixture
def semantic_env(env_guard, monkeypatch):
    monkeypatch.setenv("TICTOK_SEMANTIC_DIR", str(env_guard / "semantic"))
    monkeypatch.setenv("TICTOK_SEMANTIC_ENABLED", "1")
    monkeypatch.setenv("TICTOK_SEMANTIC_MODEL", "test-embedder")
    semantic.set_embedder(_CharEmbedder())
    try:
        yield
    finally:
        semantic.set_embedder(None)


@pytest.fixture
def recordings(tmp_db, make_session):
    """search_hitsはrecordingsへのFKを持つので、2本ぶんの実在する録画を先に作る。"""
    session_id = make_session("tester", status="connected")
    return [tmp_db.create_recording(session_id, "tester", f"/x/{n}.mp4", f"{n}.mp4",
                                    "hd", 1700000000.0) for n in ("a", "b")]


def _hits(session_id: int, times: list, bodies: list) -> list:
    return [
        {"unique_id": "tester", "session_id": session_id, "started_at": 1700000000.0,
         "video_time": t, "end_time": t + 2.0, "nickname": None, "body": body}
        for t, body in zip(times, bodies)
    ]


BODIES = ["ラーメンが美味しい", "今日は寒い", "また明日"]


def _seed(storage, recordings, times=(10.0, 40.0, 70.0)) -> None:
    storage.replace_search_hits(recordings[0], "stt",
                                _hits(recordings[0], list(times), BODIES))


def _search(storage, query="ラーメン", **kwargs) -> dict:
    return asyncio.run(semantic.search(storage, query, 10, **kwargs))


def test_search_returns_the_time_stored_in_search_hits(semantic_env, tmp_db, recordings):
    _seed(tmp_db, recordings)
    asyncio.run(semantic.build_index(tmp_db))
    found = _search(tmp_db)
    assert found["stale"] == 0
    assert found["items"]
    assert found["items"][0]["video_time"] == 10.0


def test_in_place_time_shift_is_reflected_without_rebuilding(semantic_env, tmp_db,
                                                             recordings):
    """秒だけをUPDATEする移行(migrate_time_axis_to_media.py)の後もズレないこと。

    件数も最大idも動かないので差分buildは走らない。indexのsnapshotを返していた頃は、
    ここで古い秒がそのまま出ていた。"""
    _seed(tmp_db, recordings)
    asyncio.run(semantic.build_index(tmp_db))
    with tmp_db._lock:
        tmp_db._conn.execute(
            "UPDATE search_hits SET video_time = video_time + 600,"
            " end_time = end_time + 600")
        tmp_db._conn.commit()

    found = _search(tmp_db)
    assert found["stale"] == 0
    assert found["items"][0]["video_time"] == 610.0
    assert found["items"][0]["end_time"] == 612.0


def test_rebuilt_hits_are_dropped_until_the_index_is_updated(semantic_env, tmp_db,
                                                            recordings):
    """張り直し(DELETE -> 再INSERT)でindexが指す行が消えたpassageは出さない。"""
    _seed(tmp_db, recordings)
    asyncio.run(semantic.build_index(tmp_db))
    _seed(tmp_db, recordings, times=(100.0, 130.0, 160.0))

    found = _search(tmp_db)
    assert found["items"] == []
    assert found["stale"] > 0


def test_rebuild_restores_them_with_the_new_time(semantic_env, tmp_db, recordings):
    _seed(tmp_db, recordings)
    asyncio.run(semantic.build_index(tmp_db))
    _seed(tmp_db, recordings, times=(100.0, 130.0, 160.0))
    asyncio.run(semantic.build_index(tmp_db))

    found = _search(tmp_db)
    assert found["stale"] == 0
    assert found["items"][0]["video_time"] == 100.0


def test_index_status_counts_stale_and_unindexed_groups(semantic_env, tmp_db,
                                                       recordings):
    _seed(tmp_db, recordings)
    asyncio.run(semantic.build_index(tmp_db))
    assert semantic.index_status(tmp_db)["stale_groups"] == 0

    _seed(tmp_db, recordings, times=(100.0, 130.0, 160.0))
    tmp_db.replace_search_hits(recordings[1], "comment",
                               _hits(recordings[1], [5.0], ["草"]))
    status = semantic.index_status(tmp_db)
    assert status["stale_groups"] == 1
    assert status["stale_passages"] > 0
    assert status["unindexed_groups"] == 1


def test_index_status_without_storage_reports_zero_not_an_error(semantic_env, tmp_db,
                                                               recordings):
    _seed(tmp_db, recordings)
    asyncio.run(semantic.build_index(tmp_db))
    status = semantic.index_status()
    assert status["built"] is True
    assert status["stale_groups"] == 0
    assert status["unindexed_groups"] == 0
