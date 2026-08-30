"""切り出し候補(api/candidates)の、素材由来の指標(_MATERIAL_METRICS)の配線。

engineそのもの(笑い声の検出精度)は tests/test_laugh_audio.py の担当なので、ここで見るのは
候補APIとengineの間だけである。壊れ方が最も分かりにくいのは「笑いを見ているつもりで見て
いない候補一覧」なので、次の4点を軸にする:

  1. 既定では解析を1度も起動しない(重い解析を勝手に走らせない)
  2. 有効なのにmodelが無ければ**失敗する** — 笑い0秒の候補を黙って返さない
  3. 確率列は動画時間軸なので、bucketの窓を動画時間へ写してから秒数を引く
  4. 判定できない録画では指標を外す。0で埋めない(=keyを付けない)
"""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BUCKET_SECONDS = 10
BUCKET_COUNT = 20


@pytest.fixture
def server(env_guard):
    # env_guard を先に効かせてから import する。tictok.api.runtime は import 時に
    # Storage / instance lock / record dir を掴むため、順序が逆だと本番を掴む。
    import asyncio as _asyncio
    from types import SimpleNamespace

    import tictok.server as srv
    from tictok.api import (access_log, candidates, disk, files, fsfacts, media_jobs,
                            runtime, startup)
    from tictok.api.routes import (ai, analytics, bulk, media, monitors, pages,
                                   recordings, search, sessions, storage, streamers,
                                   system, ws)
    from tictok.core import layout
    from tictok.media import laugh_audio, smile
    from tictok.record import audio_norm, hls_pack
    from tictok.record.media_queue import JobDeferred
    from tictok.record.recorder import Recorder
    from tictok.search import indexer
    from fastapi import HTTPException

    assert not str(runtime.RECORD_DIR).lower().endswith("tictok\\recordings")
    return SimpleNamespace(
        app=srv.app, main=srv.main,
        # 分割後のmodule。module levelの名前を差し替えるときはここを通す
        # (``from ... import`` で束ねると差し替えが届かない)。
        runtime=runtime, files=files, fsfacts=fsfacts, disk=disk,
        media_jobs=media_jobs, startup=startup, access_log=access_log,
        candidates=candidates,
        routes=SimpleNamespace(ai=ai, analytics=analytics, bulk=bulk, media=media,
                               monitors=monitors, pages=pages, recordings=recordings,
                               search=search, sessions=sessions, storage=storage,
                               streamers=streamers, system=system, ws=ws),
        # objectそのものを差し替える先。実体は1つなので、どのmoduleから見ても同じ。
        layout=layout, smile=smile, indexer=indexer, hls_pack=hls_pack,
        audio_norm=audio_norm, laugh_audio=laugh_audio, asyncio=_asyncio,
        Recorder=Recorder, HTTPException=HTTPException, JobDeferred=JobDeferred,
    )


@pytest.fixture
def client(server):
    return TestClient(server.app)


@pytest.fixture
def clip_settings(server):
    """設定を触るtestのために、触ったkeyを必ず元へ戻す。

    tictok.server はprocessで1度しかimportされず storage も1つなので、設定を変えたまま
    終わると後続のtestがその値を引き継ぐ。
    """
    saved: dict = {}

    def _set(**values):
        for key in values:
            saved.setdefault(key, server.runtime.settings.get(key))
        server.runtime.settings.update(values)

    yield _set
    if saved:
        server.runtime.settings.update(saved)


@pytest.fixture
def recording(server, monkeypatch):
    """buckets付きの録画1本と、その録画に対する候補APIの前提を揃える。

    bucketsはDBを介さず差し替える。ここで確かめたいのは指標の載せ方であって、eventから
    bucketを組む経路(storage側)ではない。
    """
    storage = server.runtime.storage
    unique_id = "tester"
    session_id = storage.create_session(unique_id, BUCKET_SECONDS)
    storage.update_session(session_id, "connected")
    stem = f"90001_{unique_id}_20260101_{int(time.time() % 1000000):06d}"
    directory = server.runtime.RECORD_DIR / unique_id / "mp4"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stem}.mp4"
    path.write_bytes(b"\x00" * 64)
    # 起点は整数秒。bucketのstartは丸めた整数なので、端数を持つと窓の写しがずれる。
    started = float(int(time.time()) - 3600)
    recording_id = storage.create_recording(
        session_id, unique_id, str(path), path.name, "hd", started)
    storage.update_recording(
        recording_id, "completed", str(path), path.name,
        started + BUCKET_SECONDS * BUCKET_COUNT, 64)

    def _buckets(diamonds=None) -> list:
        rows = []
        for i in range(BUCKET_COUNT):
            rows.append({
                "start": started + i * BUCKET_SECONDS,
                "gifts": 0,
                # 既定はdiamonds/commentsを平坦にする。分散0の指標はz-scoreを出せず
                # 判定から落ちるので、候補は素材由来の指標だけが根拠になる。
                "diamonds": 0 if diamonds is None else diamonds[i],
                "comments": 1,
                "likes": 0,
                "joins": 0,
                "follows": 0,
                "shares": 0,
                "viewers": 10,
            })
        return rows

    def _install(diamonds=None) -> list:
        rows = _buckets(diamonds)
        monkeypatch.setattr(server.runtime.storage, "session_buckets",
                            lambda sid, start=None, end=None: rows)
        return rows

    # wall-clock -> 動画時間。実mapperはtiming anchorを読むので、ここでは録画開始からの
    # 経過秒という素の対応にしておく(窓の写し先が読める形であることが要点)。
    monkeypatch.setattr(server.indexer, "build_time_mapper_sync",
                        lambda src, started_at, ended_at, video_duration=None: (lambda t: t - started_at))

    async def _duration(src, input_args=()):
        return float(BUCKET_SECONDS * BUCKET_COUNT)

    monkeypatch.setattr(server.candidates, "_duration_seconds", _duration)
    _install()
    return type("Rec", (), {"id": recording_id, "session_id": session_id,
                            "started_at": started, "path": path,
                            "buckets": staticmethod(_install)})


def _profile(probs: list, interval: float = 1.0) -> dict:
    return {"interval_seconds": interval, "duration_seconds": len(probs) * interval,
            "probs": probs}


def _laughing_at(bucket_index: int, hits: int, total_buckets: int = BUCKET_COUNT) -> dict:
    """bucket ``bucket_index`` の中だけで ``hits`` 刻みぶん笑っている確率列。"""
    probs = [0.0] * (total_buckets * BUCKET_SECONDS)
    for i in range(hits):
        probs[bucket_index * BUCKET_SECONDS + i] = 0.9
    return _profile(probs)


def _fake_engine(monkeypatch, server, profile):
    calls: list = []

    async def _ensure(src):
        calls.append(Path(src))
        return profile

    monkeypatch.setattr(server.laugh_audio, "ensure_laugh_profile", _ensure)
    return calls


def _candidates(client, recording) -> list:
    response = client.get(f"/api/recordings/{recording.id}/clip-candidates")
    assert response.status_code == 200, response.text
    return response.json()["candidates"]


# ---- 既定は無効 --------------------------------------------------------------------

def test_laugh_audio_is_not_analyzed_unless_the_setting_is_on(
        client, server, recording, monkeypatch):
    """既定では解析を起動しない。3.9時間の録画で音声を最後まで読む処理を、候補を開いた
    だけで走らせてはいけない。"""
    calls = _fake_engine(monkeypatch, server, _laughing_at(10, 8))
    recording.buckets(diamonds=[0] * 19 + [500])

    candidates = _candidates(client, recording)

    assert calls == [], "設定OFFでも笑い声の解析が走っている"
    assert candidates, "diamonds由来の候補が出ていない"
    assert all("laugh_audio" not in c for c in candidates)


# ---- modelが無いときは失敗する -----------------------------------------------------

def test_enabled_without_a_model_fails_instead_of_returning_laughless_candidates(
        client, server, recording, clip_settings):
    """有効なのにmodelが無ければ503。ここで候補を返すと「笑いの無い配信」と読めてしまう。"""
    clip_settings(clip_candidate_laugh_audio=1)
    recording.buckets(diamonds=[0] * 19 + [500])

    response = client.get(f"/api/recordings/{recording.id}/clip-candidates")

    assert response.status_code == 503, response.text
    detail = response.json()["detail"]
    assert "笑い声検出" in detail and "TICTOK_LAUGH_AUDIO_ENABLED" in detail
    assert "candidates" not in response.json()


def test_enabled_with_the_engine_on_but_the_model_file_absent_still_fails(
        client, server, recording, clip_settings, monkeypatch, tmp_path):
    """engineを有効化してもmodel fileが無ければ失敗する(pathの綴り違いを黙って通さない)。"""
    clip_settings(clip_candidate_laugh_audio=1)
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_ENABLED", "1")
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_MODEL_PATH", str(tmp_path / "missing.onnx"))
    monkeypatch.setenv("TICTOK_LAUGH_AUDIO_LABELS_PATH", str(tmp_path / "missing.csv"))

    response = client.get(f"/api/recordings/{recording.id}/clip-candidates")

    assert response.status_code == 503, response.text
    assert "model" in response.json()["detail"]


# ---- 値の載せ方 --------------------------------------------------------------------

def test_laugh_seconds_are_read_on_the_video_time_axis_and_drive_the_candidate(
        client, server, recording, clip_settings, monkeypatch):
    clip_settings(clip_candidate_laugh_audio=1)
    calls = _fake_engine(monkeypatch, server, _laughing_at(10, 8))

    candidates = _candidates(client, recording)

    assert calls == [recording.path], "解析が録画のpathで呼ばれていない"
    assert len(candidates) == 1, "重なった窓が畳まれていない"
    candidate = candidates[0]
    assert candidate["metric"] == "laugh_audio"
    # 窓は既定30秒(bucket 3個)で、笑っていたbucketを含む窓の合計が8秒。
    assert candidate["laugh_audio"] == 8.0
    assert candidate["label"] == "笑い声8秒"
    # 候補の範囲は笑っていた時刻(動画時間100〜110秒)を含む。
    assert candidate["start"] <= 100.0 < candidate["end"]


def test_a_recording_the_engine_cannot_judge_drops_the_metric_without_zeroing_it(
        client, server, recording, clip_settings, monkeypatch):
    """確率列が録画の途中までしか無い場合、その録画では指標を外す。

    0秒として載せると「解析していないbucket」が「笑いの無かったbucket」に化け、平均を
    押し下げて他の窓の判定まで動かす。"""
    clip_settings(clip_candidate_laugh_audio=1)
    recording.buckets(diamonds=[0] * 19 + [500])
    # bucket 5より後を覆えない長さの確率列。
    _fake_engine(monkeypatch, server, _profile([0.0] * (5 * BUCKET_SECONDS)))

    candidates = _candidates(client, recording)

    assert candidates, "他の指標の候補まで消えている"
    assert all("laugh_audio" not in c for c in candidates), "判定できない指標を0で埋めている"
    assert {c["metric"] for c in candidates} == {"diamonds"}


def test_the_minimum_seconds_floor_keeps_a_short_laugh_out_of_the_candidates(
        client, server, recording, clip_settings, monkeypatch):
    """笑い声の系列もほとんどの窓が0秒なので、下限が無いと僅かな検出がzを叩く。"""
    clip_settings(clip_candidate_laugh_audio=1, clip_candidate_laugh_audio_min_seconds=9.0)
    _fake_engine(monkeypatch, server, _laughing_at(10, 8))

    assert _candidates(client, recording) == []

    clip_settings(clip_candidate_laugh_audio_min_seconds=8.0)

    assert len(_candidates(client, recording)) == 1, "下限ちょうどの窓は候補になる"


def test_the_weight_scales_the_zscore_of_the_laugh_audio_metric(
        client, server, recording, clip_settings, monkeypatch):
    clip_settings(clip_candidate_laugh_audio=1)
    _fake_engine(monkeypatch, server, _laughing_at(10, 8))

    plain = _candidates(client, recording)[0]["zscore"]
    clip_settings(clip_candidate_laugh_audio_weight=2.0)
    weighted = _candidates(client, recording)[0]["zscore"]

    assert weighted == pytest.approx(plain * 2, abs=0.02)


# ---- 登録表の契約 ------------------------------------------------------------------

def test_every_registered_material_metric_is_wired_all_the_way_through(server):
    """登録表へ1 entry足すだけで配線が揃うことを、逆側から固定する。

    指標を足したときに落ちやすいのは判定側ではなく、設定・badge文言・畳み込みの引き継ぎ
    といった周辺で、どれが欠けても候補は普通に返ってしまう。

    画面(videos.js/videos.html)の列までは見ない。候補一覧のUIは再生画面の改装で外され、
    候補の利用者はshortの一括生成(api/media_jobs)だけになった。"""
    from tictok.core import spike
    from tictok.core.settings import SETTING_DEFS

    assert server.candidates._MATERIAL_METRICS
    for metric in server.candidates._MATERIAL_METRICS:
        assert metric.key in spike.OPTIONAL_METRICS, metric.key
        assert metric.key in server.candidates._CANDIDATE_LABELS, metric.key
        assert metric.key in server.candidates._CANDIDATE_REPRESENTATIVE_KEYS, metric.key
        for key in (metric.setting, metric.weight_setting, metric.min_setting):
            assert key in SETTING_DEFS, key


# ---- 笑顔(映像) --------------------------------------------------------------------

def test_smile_is_not_analyzed_unless_the_setting_is_on(client, server, recording,
                                                        monkeypatch):
    """既定では映像の解析を起動しない。3時間の録画をsamplingしながら復号する処理を、
    候補を開いただけで走らせてはいけない。"""
    calls: list = []

    async def _ensure(src):
        calls.append(Path(src))
        raise AssertionError("設定OFFで笑顔の解析が走っている")

    monkeypatch.setattr(server.smile, "ensure_smile_profile", _ensure)
    recording.buckets(diamonds=[0] * 19 + [500])

    candidates = _candidates(client, recording)

    assert calls == []
    assert candidates, "diamonds由来の候補が出ていない"
    assert all("smile" not in c for c in candidates)


def test_smile_enabled_without_a_model_fails_instead_of_returning_smileless_candidates(
        client, server, recording, clip_settings):
    """有効なのにmodelが無ければ503。ここで候補を返すと「笑顔の無い配信」と読めてしまう。"""
    clip_settings(clip_candidate_smile=1)
    recording.buckets(diamonds=[0] * 19 + [500])

    response = client.get(f"/api/recordings/{recording.id}/clip-candidates")

    assert response.status_code == 503, response.text
    assert "笑顔検出" in response.json()["detail"]
    assert "candidates" not in response.json()


def test_smile_seconds_are_read_on_the_video_time_axis_and_drive_the_candidate(
        client, server, recording, clip_settings, monkeypatch):
    """笑顔の秒数がbucketへ載り、その窓が候補になること。"""
    clip_settings(clip_candidate_smile=1, clip_candidate_smile_min_seconds=1.0)
    calls: list = []

    async def _ensure(src):
        calls.append(Path(src))
        return {"duration_seconds": 1000.0}

    def _seconds(profile, start, end, threshold=None):
        # 動画時間100〜110秒だけ笑っていた録画。
        return 8.0 if start <= 100.0 < end else 0.0

    monkeypatch.setattr(server.smile, "ensure_smile_profile", _ensure)
    monkeypatch.setattr(server.smile, "smile_seconds", _seconds)

    candidates = _candidates(client, recording)

    assert calls == [recording.path], "解析が録画のpathで呼ばれていない"
    assert len(candidates) == 1, "重なった窓が畳まれていない"
    candidate = candidates[0]
    assert candidate["metric"] == "smile"
    assert candidate["smile"] == 8.0
    assert candidate["label"] == "笑顔8秒"
    assert candidate["start"] <= 100.0 < candidate["end"]


def test_smile_is_dropped_when_a_window_falls_outside_the_analysis(
        client, server, recording, clip_settings, monkeypatch):
    """判定できない窓が1つでもあれば指標ごと外す。0で埋めると「笑っていなかった」を捏造する。"""
    clip_settings(clip_candidate_smile=1)
    recording.buckets(diamonds=[0] * 19 + [500])

    async def _ensure(src):
        return {"duration_seconds": 20.0}

    monkeypatch.setattr(server.smile, "ensure_smile_profile", _ensure)
    monkeypatch.setattr(server.smile, "smile_seconds",
                        lambda profile, start, end, threshold=None: None)

    candidates = _candidates(client, recording)

    assert candidates, "他の指標の候補まで消えている"
    assert all("smile" not in c for c in candidates)
