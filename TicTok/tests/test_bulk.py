"""配信者まるごとの一括生成(焼き込み/Up出力/再mp4化)。

見積りと投入で対象の絞り方が食い違うと「確認した本数と積まれた本数が違う」という最悪の
壊れ方をするため、両者が同じ_bulk_planを通ることを軸に確かめる。
"""

import secrets
import time

import pytest
from fastapi.testclient import TestClient

from tictok.record.transcription import TIMEMAP_VERSION


@pytest.fixture
def server(env_guard):
    # env_guard を先に効かせてから import する。tictok.api.runtime は import 時に
    # Storage / instance lock / record dir を掴むため、順序が逆だと本番を掴む。
    import asyncio as _asyncio
    from types import SimpleNamespace

    import tictok.server as srv
    from tictok.api import access_log, disk, files, fsfacts, media_jobs, runtime, startup
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
def make_recording(server):
    """一括の対象になり得る録画を1本作る。overlay済みにしたい場合は with_output=True。"""
    def _make(unique_id="tester", status="completed", file_exists=True,
              with_output=False, seconds=300):
        storage = server.runtime.storage
        session_id = storage.create_session(unique_id, 60)
        storage.update_session(session_id, "connected")
        stem = f"00001_{unique_id}_{secrets.token_hex(4)}"
        directory = server.runtime.RECORD_DIR / unique_id / "mp4"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{stem}.mp4"
        if file_exists:
            path.write_bytes(b"\x00" * 64)
        started = time.time() - seconds * 2
        recording_id = storage.create_recording(
            session_id, unique_id, str(path), path.name, "hd", started)
        if status != "recording":
            # 尺は実測値(duration_seconds)で持つ。見積りも一括の並びも壁時計ではなく
            # こちらを見るので、fixtureが埋めないと本数以外の数字が全て0になる。
            storage.update_recording(
                recording_id, status, str(path), path.name, started + seconds, 64,
                duration_seconds=seconds)
        if with_output:
            from tictok.record.video_overlay import overlay_paths
            overlay = overlay_paths(path)[0]
            overlay.parent.mkdir(parents=True, exist_ok=True)
            overlay.write_bytes(b"\x00" * 32)
        # 出力状態はfilesystem由来でcacheされる。前のtestの残りを持ち越さない。
        server.fsfacts._fs_state_cache.clear()
        server.fsfacts._fs_bulk_cache.clear()
        server.fsfacts._bulk_status_cache.clear()
        return session_id, recording_id, path

    return _make


def test_unknown_kind_is_refused(client):
    assert client.get("/api/bulk/estimate", params={"kind": "clip_batch"}).status_code == 400
    assert client.post("/api/bulk/queue", json={"kind": "clip_batch"}).status_code == 400


def test_estimate_counts_only_recordings_that_can_be_output(client, make_recording):
    make_recording(unique_id="alice")
    make_recording(unique_id="alice", with_output=True)
    # fileが消えた録画は対象にならない(workerが1件ずつ404で落ちるだけ)。
    make_recording(unique_id="alice", file_exists=False)

    body = client.get("/api/bulk/estimate",
                      params={"kind": "overlay", "unique_id": "alice"}).json()
    assert body["recordings"] == 1
    assert body["skipped"]["done"] == 1
    # 焼き込みの入力はmp4ではなく素材(.ts)になった。mp4だけが無い録画は焼けるので、
    # ここで落ちるのは「mp4も.tsも無い」場合だけ = no_source。
    assert body["skipped"]["no_source"] == 1


def test_estimate_redo_brings_back_already_output_recordings(client, make_recording):
    make_recording(unique_id="bob", with_output=True)

    plain = client.get("/api/bulk/estimate",
                       params={"kind": "overlay", "unique_id": "bob"}).json()
    redone = client.get("/api/bulk/estimate",
                        params={"kind": "overlay", "unique_id": "bob", "redo": 1}).json()
    assert (plain["recordings"], redone["recordings"]) == (0, 1)
    assert "done" not in redone["skipped"]


def test_estimate_reports_unknown_eta_without_history(client, make_recording):
    make_recording(unique_id="carol")
    body = client.get("/api/bulk/estimate",
                      params={"kind": "overlay", "unique_id": "carol"}).json()
    # 実績が無いときに倍率をでっち上げないこと。根拠のある数字と区別できなくなる。
    assert body["eta_seconds"] is None
    assert body["eta_samples"] == 0


def test_estimate_derives_eta_from_completed_jobs(client, server, make_recording,
                                                  monkeypatch):
    monkeypatch.setattr(server.routes.bulk, "get_media_queue_workers", lambda: 1)
    _, recording_id, _ = make_recording(unique_id="dave", seconds=100)
    storage = server.runtime.storage
    # 100秒の録画を200秒かけて焼いた実績 → 次の100秒も200秒と見積もる。
    storage.enqueue_media_job("past-1", "overlay", recording_id)
    storage.start_media_job("past-1")
    storage.finish_media_job("past-1", "completed")
    with storage._lock:
        storage._conn.execute(
            "UPDATE media_job_queue SET started_at = ?, finished_at = ? WHERE job_id = ?",
            (1000.0, 1200.0, "past-1"))
        storage._conn.commit()

    _, _, _ = make_recording(unique_id="dave", seconds=100)
    body = client.get("/api/bulk/estimate",
                      params={"kind": "overlay", "unique_id": "dave"}).json()
    assert body["eta_samples"] == 1
    # 尺が0だと以下の比較が 0 == 0 で素通りする。実測が載っていることを先に確かめる。
    assert body["seconds"] == pytest.approx(200.0)
    assert body["eta_seconds"] == pytest.approx(body["seconds"] * 2, rel=0.01)


def test_estimate_accounts_for_concurrent_workers(client, server, make_recording,
                                                  monkeypatch):
    """同時実行数は所要時間と容量の山の両方に効く。1本ぶんで見せると、workerを増やした
    環境で「入るはず」と示した直後に空き容量を割る。"""
    _, recording_id, _ = make_recording(unique_id="frank", seconds=100)
    make_recording(unique_id="frank", seconds=100)
    storage = server.runtime.storage
    storage.enqueue_media_job("past-2", "overlay", recording_id)
    storage.start_media_job("past-2")
    storage.finish_media_job("past-2", "completed")
    with storage._lock:
        storage._conn.execute(
            "UPDATE media_job_queue SET started_at = ?, finished_at = ? WHERE job_id = ?",
            (1000.0, 1200.0, "past-2"))
        storage._conn.commit()

    def _estimate():
        return client.get("/api/bulk/estimate",
                          params={"kind": "overlay", "unique_id": "frank"}).json()

    monkeypatch.setattr(server.routes.bulk, "get_media_queue_workers", lambda: 1)
    one = _estimate()
    monkeypatch.setattr(server.routes.bulk, "get_media_queue_workers", lambda: 2)
    two = _estimate()

    assert two["eta_seconds"] == pytest.approx(one["eta_seconds"] / 2, rel=0.01)
    assert two["largest_source_bytes"] == one["largest_source_bytes"] * 2


def test_queue_enqueues_one_job_per_recording_under_one_group(client, server,
                                                              make_recording):
    make_recording(unique_id="erin")
    make_recording(unique_id="erin")
    make_recording(unique_id="frank")

    body = client.post("/api/bulk/queue",
                       json={"kind": "overlay", "unique_id": "erin"}).json()
    assert body["total"] == 2
    rows = server.runtime.storage.media_jobs_in_group(body["group_id"])
    assert len(rows) == 2
    # 他の配信者を巻き込まないこと。
    assert {row["recording_id"] for row in rows} == set(body["recording_ids"])


def test_queued_group_is_not_reported_as_a_session_job(client, server, make_recording):
    """一括groupをsession_*として出すと、履歴画面が先頭録画のsession行へ、そのsessionに
    属さない録画まで含む進捗を貼り付けてしまう。"""
    from tictok.record.media_queue import group_payload

    make_recording(unique_id="grace")
    make_recording(unique_id="grace")
    body = client.post("/api/bulk/queue",
                       json={"kind": "overlay", "unique_id": "grace"}).json()

    group = group_payload(server.runtime.storage.media_jobs_in_group(body["group_id"]))
    assert group["domain"] == "bulk_overlay"
    assert group["session_id"] is None


def test_session_group_still_folds_into_a_session_job(server, make_recording):
    """一括の分岐を足したことでsession一括の畳み方が変わっていないこと。"""
    from tictok.record.media_queue import group_payload

    session_id, recording_id, _ = make_recording(unique_id="heidi")
    server.runtime.storage.enqueue_media_job("s-1", "overlay", recording_id,
                                     session_id=session_id, group_id="grp-s")

    group = group_payload(server.runtime.storage.media_jobs_in_group("grp-s"))
    assert group["domain"] == "session_overlay"
    assert group["session_id"] == session_id


def test_group_row_counts_all_members_even_past_the_ledger_limit(server, make_recording):
    """Job画面の一覧はlist_media_jobs(limit)で切られる。group行をその切られた行から
    畳むと、limitを超える一括投入が実際より小さい母数で進捗を出す。"""
    _, recording_id, _ = make_recording(unique_id="mallory")
    for index in range(5):
        server.runtime.storage.enqueue_media_job(f"m-{index}", "overlay", recording_id,
                                         group_id="grp-big", params={"bulk": True})

    payloads = server.media_jobs.media_job_queue.list_jobs(limit=2)
    group = next(p for p in payloads if p["job_id"] == "grp-big")
    assert group["total"] == 5


def test_queue_refuses_when_nothing_is_eligible(client, make_recording):
    make_recording(unique_id="ivan", with_output=True)
    response = client.post("/api/bulk/queue",
                           json={"kind": "overlay", "unique_id": "ivan"})
    assert response.status_code == 409
    # 0本という結果だけでなく、なぜ0本なのかを本文に含めること。
    assert "処理済み" in response.json()["detail"]


def test_queue_skips_recordings_already_in_the_queue(client, server, make_recording):
    _, recording_id, _ = make_recording(unique_id="judy")
    make_recording(unique_id="judy")
    server.runtime.storage.enqueue_media_job("dup-1", "overlay", recording_id)

    body = client.post("/api/bulk/queue",
                       json={"kind": "overlay", "unique_id": "judy"}).json()
    assert body["total"] == 1
    assert body["skipped"]["queued"] == 1


def test_status_lists_targets_and_done_per_streamer(client, make_recording):
    make_recording(unique_id="ken")
    make_recording(unique_id="ken", with_output=True)

    entry = next(s for s in client.get("/api/bulk/status").json()["streamers"]
                 if s["unique_id"] == "ken")
    assert entry["recordings"] == 2
    assert entry["targets"]["overlay"] == 1
    assert entry["done"]["overlay"] == 1


def test_reprocess_targets_only_recordings_that_still_have_segments(client,
                                                                    make_recording):
    make_recording(unique_id="lena")
    body = client.get("/api/bulk/estimate",
                      params={"kind": "reprocess", "unique_id": "lena"}).json()
    # .tsを残していない録画は再mp4化できない。理由まで返すこと。
    assert body["recordings"] == 0
    assert body["skipped"]["no_hls"] == 1


def test_reprocess_skips_recordings_that_were_already_rebuilt(client, server,
                                                              make_recording, monkeypatch):
    """作り直しは元動画を差し替える不可逆な操作。印が無かった頃は一括のたびに全部作り直し、
    同じ内容の元mp4が_backupへ積まれていた(同一録画に3世代・退避307GB)。"""
    _, done_id, _ = make_recording(unique_id="mika")
    make_recording(unique_id="mika")
    monkeypatch.setattr(server.fsfacts, "_recording_has_hls", lambda _r: True)
    monkeypatch.setattr(server.fsfacts, "_bulk_hls_batch",
                        lambda recordings, facts: [f.update({"has_hls": True})
                                                   for f in facts.values()])
    server.runtime.storage.set_recording_reprocessed(done_id, 1000.0)
    server.fsfacts._bulk_status_cache.clear()
    server.fsfacts._fs_bulk_cache.clear()

    body = client.get("/api/bulk/estimate",
                      params={"kind": "reprocess", "unique_id": "mika"}).json()
    assert body["recordings"] == 1
    assert body["skipped"]["done"] == 1

    # 「処理済みも作り直す」を選べば戻せる(作り直しそのものを禁じるわけではない)。
    redo = client.get("/api/bulk/estimate",
                      params={"kind": "reprocess", "unique_id": "mika", "redo": "1"}).json()
    assert redo["recordings"] == 2


# ---- 音量正規化 ----

def test_audionorm_targets_recordings_that_are_not_normalized_yet(client, server,
                                                                  make_recording):
    """済み判定はDBの列だけを見る。mp4からは正規化の有無を判別できない。"""
    _, done_id, _ = make_recording(unique_id="nina")
    make_recording(unique_id="nina")
    server.runtime.storage.set_recording_audio_normalized(done_id, 1000.0, -14.0)
    server.fsfacts._bulk_status_cache.clear()

    body = client.get("/api/bulk/estimate",
                      params={"kind": "audionorm", "unique_id": "nina"}).json()
    assert body["recordings"] == 1
    assert body["skipped"]["done"] == 1
    # .tsが無くても対象になる(再mp4化と違い元mp4だけで完結する)。
    assert "no_hls" not in body["skipped"]


def test_audionorm_redo_brings_back_normalized_recordings(client, server,
                                                          make_recording):
    _, recording_id, _ = make_recording(unique_id="olga")
    server.runtime.storage.set_recording_audio_normalized(recording_id, 1000.0, -14.0)
    server.fsfacts._bulk_status_cache.clear()

    body = client.get("/api/bulk/estimate",
                      params={"kind": "audionorm", "unique_id": "olga", "redo": 1}).json()
    assert body["recordings"] == 1


# ---- 録画を選んでの投入 ----

def test_recordings_endpoint_reports_eligibility_per_recording(client, server,
                                                               make_recording):
    _, done_id, _ = make_recording(unique_id="pam")
    _, open_id, _ = make_recording(unique_id="pam")
    server.runtime.storage.set_recording_audio_normalized(done_id, 1000.0, -14.0)

    rows = client.get("/api/bulk/recordings",
                      params={"kind": "audionorm", "unique_id": "pam"}).json()["recordings"]
    by_id = {row["id"]: row for row in rows}
    assert by_id[open_id]["eligible"] is True
    assert by_id[done_id]["eligible"] is False
    # 画面は理由を持たない。server側の判定理由をそのまま出せること。
    assert by_id[done_id]["reason"] == "done"


def test_recordings_endpoint_marks_already_queued_recordings(client, server,
                                                             make_recording):
    """選べるのに投入されない録画を作らないため、queue済みも対象外として返すこと。"""
    _, recording_id, _ = make_recording(unique_id="quinn")
    server.runtime.storage.enqueue_media_job("q-1", "audionorm", recording_id)

    rows = client.get("/api/bulk/recordings",
                      params={"kind": "audionorm", "unique_id": "quinn"}).json()["recordings"]
    assert rows[0]["eligible"] is False
    assert rows[0]["reason"] == "queued"


def test_queue_accepts_a_selection_of_recordings(client, server, make_recording):
    _, first_id, _ = make_recording(unique_id="rita")
    _, second_id, _ = make_recording(unique_id="rita")
    make_recording(unique_id="rita")

    body = client.post("/api/bulk/queue",
                       json={"kind": "audionorm", "unique_id": "rita",
                             "recording_ids": [first_id, second_id]}).json()
    assert body["total"] == 2
    assert set(body["recording_ids"]) == {first_id, second_id}


def test_selection_does_not_count_unselected_recordings_as_skipped(client,
                                                                   make_recording):
    """選ばなかった録画を「対象外」に混ぜると、不具合で弾かれたように読める。"""
    _, first_id, _ = make_recording(unique_id="sara")
    make_recording(unique_id="sara")

    body = client.get("/api/bulk/estimate",
                      params={"kind": "audionorm", "unique_id": "sara",
                              "recording_id": [first_id]}).json()
    assert body["recordings"] == 1
    assert body["skipped"] == {}
    assert body["selected"] == 1


def test_estimate_and_queue_select_the_same_recordings(client, server, make_recording):
    """見せた本数と積んだ本数が食い違わないこと(選択投入でも同じ_bulk_planを通る)。"""
    _, first_id, _ = make_recording(unique_id="tina")
    _, done_id, _ = make_recording(unique_id="tina")
    server.runtime.storage.set_recording_audio_normalized(done_id, 1000.0, -14.0)

    params = {"kind": "audionorm", "unique_id": "tina",
              "recording_id": [first_id, done_id]}
    estimate = client.get("/api/bulk/estimate", params=params).json()
    queued = client.post("/api/bulk/queue",
                         json={"kind": "audionorm", "unique_id": "tina",
                               "recording_ids": [first_id, done_id]}).json()
    assert estimate["recordings"] == queued["total"] == 1
    assert queued["recording_ids"] == [first_id]


# ---- 元mp4の削除 ----

def _with_hls(server, monkeypatch, present=True):
    """.ts走査の結果を差し替える。実segmentを並べなくても対象判定を通せる。"""
    monkeypatch.setattr(server.fsfacts, "_recording_has_hls", lambda _r: present)
    monkeypatch.setattr(
        server.fsfacts, "_bulk_hls_batch",
        lambda recordings, facts: [f.update({"has_hls": present}) for f in facts.values()])


def test_delete_mp4_removes_only_the_source_and_keeps_derived_outputs(
        client, server, make_recording, monkeypatch):
    """消すのはDB行が名指ししているfile1本だけ。焼き込み出力や名前を変えたfileは、この
    録画から派生した別の成果物であって作り直しの対象ではない。"""
    from tictok.record.video_overlay import overlay_paths

    _s, recording_id, path = make_recording(unique_id="del", with_output=True)
    renamed = path.parent / f"{path.stem}_お気に入り.mp4"
    renamed.write_bytes(b"\x00" * 8)
    overlay = overlay_paths(path)[0]
    _with_hls(server, monkeypatch)

    body = client.post("/api/bulk/delete-mp4",
                       json={"kind": "delete_mp4", "unique_id": "del"}).json()

    assert body["deleted"] == 1
    assert body["freed_bytes"] == 64
    assert not path.exists()
    assert overlay.is_file() and renamed.is_file()
    row = server.runtime.storage.get_recording(recording_id)
    # 消したmp4についての主張は落とす。残すと再mp4化の対象から外れたままになる。
    assert row["bytes"] == 0
    assert row["reprocessed_at"] is None


def test_delete_mp4_refuses_recordings_without_segments(client, server, make_recording,
                                                        monkeypatch):
    """.tsが残っていない録画のmp4は唯一の再取得不能資産。消せば復元手段が無い。"""
    _s, _recording_id, path = make_recording(unique_id="nots")
    _with_hls(server, monkeypatch, present=False)

    response = client.post("/api/bulk/delete-mp4",
                           json={"kind": "delete_mp4", "unique_id": "nots"})

    assert response.status_code == 409
    assert ".tsが残っていない" in response.json()["detail"]
    assert path.is_file()


def test_delete_mp4_estimate_reports_the_untouchable_ones_as_a_reason(
        client, server, make_recording, monkeypatch):
    """警告の材料は見積りが返す。画面はここから「.tsが無いN本は削除しません」を出す。"""
    make_recording(unique_id="mix")
    _with_hls(server, monkeypatch, present=False)
    server.fsfacts._bulk_status_cache.clear()

    body = client.get("/api/bulk/estimate",
                      params={"kind": "delete_mp4", "unique_id": "mix"}).json()

    assert body["recordings"] == 0
    assert body["skipped"]["no_hls"] == 1


def test_delete_mp4_keeps_protected_recordings(client, server, make_recording, monkeypatch):
    _s, recording_id, path = make_recording(unique_id="prot")
    _with_hls(server, monkeypatch)
    server.runtime.storage.set_recording_protected(recording_id, True)
    server.fsfacts._bulk_status_cache.clear()

    response = client.post("/api/bulk/delete-mp4",
                           json={"kind": "delete_mp4", "unique_id": "prot"})

    assert response.status_code == 409
    assert path.is_file()


def test_delete_mp4_is_not_accepted_by_the_queue_endpoint(client, server, make_recording,
                                                          monkeypatch):
    """fileを1本消すだけの種別をqueueへ載せると、実行時間0のjob行が録画数ぶん並ぶ。"""
    make_recording(unique_id="noqueue")
    _with_hls(server, monkeypatch)

    response = client.post("/api/bulk/queue",
                           json={"kind": "delete_mp4", "unique_id": "noqueue"})
    assert response.status_code == 400


def test_delete_mp4_skips_recordings_a_job_is_holding(client, server, make_recording,
                                                      monkeypatch):
    """焼き込みは実行中ずっと元mp4を読んでいる。その足元で消すと道半ばで壊れたjobが残る。
    見積りの時点で外す(実行時に初めて減ると、確認した本数と消えた本数が食い違う)。"""
    _s, recording_id, path = make_recording(unique_id="busy")
    _with_hls(server, monkeypatch)
    server.runtime.storage.enqueue_media_job("hold-1", "overlay", recording_id)
    server.fsfacts._bulk_status_cache.clear()

    body = client.get("/api/bulk/estimate",
                      params={"kind": "delete_mp4", "unique_id": "busy"}).json()
    assert body["recordings"] == 0
    assert body["skipped"]["busy"] == 1

    assert client.post("/api/bulk/delete-mp4",
                       json={"kind": "delete_mp4", "unique_id": "busy"}).status_code == 409
    assert path.is_file()


# ---- 文字起こし ----
# 対象の選び方(_bulk_plan)は他の種別と共有し、投入の口だけ_enqueue_stt_jobsを通る(台帳は
# 同じmedia_job_queue)。済み判定の出所だけは他と違い、queueの行ではなくtranscriptsの実在。


@pytest.fixture
def stt_ready(server, monkeypatch):
    """STTが使える状態にする。実modelは読まない(投入APIの可否判定だけを通す)。"""
    monkeypatch.setattr(server.routes.bulk, "stt_available", lambda: True)


def _save_transcript(server, recording_id, word_times=True,
                     timemap_version=TIMEMAP_VERSION):
    """済みとして数えられる文字起こしを1本保存する。

    既定は**いまの版**の文字起こし(現行の時刻map・語ごとの時刻あり)。済み判定はこの2つを見るので、
    既定を古い形にすると全testが「文字起こしなし」側へ倒れて済み判定を検証できなくなる。"""
    segment = {"start": 0.0, "end": 1.0, "text": "あ"}
    if word_times:
        segment["words"] = [{"start": 0.0, "end": 1.0, "text": "あ"}]
    server.runtime.storage.save_transcript(
        recording_id, {"language": "ja", "model": "test", "text": "あ",
                       "segments": [segment], "duration": 1.0,
                       "timemap_version": timemap_version})


# ---- 無音skipの解析(voice) ----
# 再生画面が使うsidecarを先に作っておく種別。人がその場で待つ生成物なので、一括とsweepの
# 両方から積める必要がある。


def test_voice_targets_recordings_without_the_sidecar(client, server, make_recording):
    """済み判定はsidecarの実在だけ。DBに印を持たない(外で消えたり戻ったりする)。"""
    from tictok.media.voice import voice_profile_path

    make_recording(unique_id="vera")
    _, _, done_path = make_recording(unique_id="vera")
    target = voice_profile_path(done_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    server.fsfacts._fs_state_cache.clear()
    server.fsfacts._fs_bulk_cache.clear()
    server.fsfacts._bulk_status_cache.clear()

    body = client.get("/api/bulk/estimate",
                      params={"kind": "voice", "unique_id": "vera"}).json()
    assert body["recordings"] == 1
    assert body["skipped"]["done"] == 1


def test_voice_is_queued_like_the_other_media_jobs(client, server, make_recording):
    _, recording_id, _ = make_recording(unique_id="wanda")
    body = client.post("/api/bulk/queue",
                       json={"kind": "voice", "unique_id": "wanda"}).json()
    assert body["total"] == 1
    jobs = [j for j in server.runtime.storage.list_media_jobs(50)
            if j["recording_id"] == recording_id]
    assert [j["kind"] for j in jobs] == ["voice"]


def test_voice_is_queued_even_when_the_disk_is_low(client, server, make_recording,
                                                   monkeypatch):
    """残すのは数百kBのsidecarだけ。空き容量で断ると、無関係な行き止まりになる。"""
    def _refuse(*args, **kwargs):
        raise AssertionError("出力を作らない種別で空き容量を判定してはならない")

    monkeypatch.setattr(server.disk, "_require_disk_space", _refuse)
    make_recording(unique_id="xena")
    assert client.post("/api/bulk/queue",
                       json={"kind": "voice", "unique_id": "xena"}).json()["total"] == 1


# ---- 再生gain曲線(gain) ----
# 無音skipの解析と同じ性質の種別。録画のfileを書き換えず、残すのはsidecarだけで、無ければ
# その録画は音量が揃わないまま再生される。


def test_gain_targets_recordings_without_the_curve(client, server, make_recording):
    """済み判定はsidecarの実在だけ。曲線もDBに印を持たない(外で消えたり戻ったりする)。"""
    from tictok.media.loudness import gain_curve_path

    make_recording(unique_id="gina")
    _, _, done_path = make_recording(unique_id="gina")
    target = gain_curve_path(done_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    server.fsfacts._fs_state_cache.clear()
    server.fsfacts._fs_bulk_cache.clear()
    server.fsfacts._bulk_status_cache.clear()

    body = client.get("/api/bulk/estimate",
                      params={"kind": "gain", "unique_id": "gina"}).json()
    assert body["recordings"] == 1
    assert body["skipped"]["done"] == 1


def test_gain_is_queued_like_the_other_media_jobs(client, server, make_recording):
    _, recording_id, _ = make_recording(unique_id="greta")
    body = client.post("/api/bulk/queue",
                       json={"kind": "gain", "unique_id": "greta"}).json()
    assert body["total"] == 1
    jobs = [j for j in server.runtime.storage.list_media_jobs(50)
            if j["recording_id"] == recording_id]
    assert [j["kind"] for j in jobs] == ["gain"]


def test_gain_is_queued_even_when_the_disk_is_low(client, server, make_recording,
                                                  monkeypatch):
    """残すのは1本あたり数百kB〜1MB程度のsidecarだけ。空き容量で断る理由が無い。"""
    def _refuse(*args, **kwargs):
        raise AssertionError("出力を作らない種別で空き容量を判定してはならない")

    monkeypatch.setattr(server.disk, "_require_disk_space", _refuse)
    make_recording(unique_id="gwen")
    assert client.post("/api/bulk/queue",
                       json={"kind": "gain", "unique_id": "gwen"}).json()["total"] == 1


def test_gain_has_a_column_in_the_bulk_matrix(client, server, make_recording):
    """一括画面の表はserverが返す種別で列を作る。BULK_KINDSに無いと、投入APIが弾く前に
    そもそも押す場所が無い(sweepだけが作る状態になり、待っている録画を人が拾えない)。"""
    make_recording(unique_id="gale")
    server.fsfacts._bulk_status_cache.clear()
    body = client.get("/api/bulk/status").json()
    assert "gain" in body["kinds"]
    entry = next(s for s in body["streamers"] if s["unique_id"] == "gale")
    assert entry["targets"]["gain"] == 1
    assert server.routes.bulk.BULK_KIND_TITLES["gain"] == "再生gain曲線"


def test_transcribe_targets_recordings_without_a_transcript(client, server,
                                                            make_recording):
    """済み判定はtranscripts表だけ。文字起こしはfileを作らないので、filesystemからは判別できない。"""
    make_recording(unique_id="stt")
    _s, done_id, _p = make_recording(unique_id="stt")
    _save_transcript(server, done_id)

    body = client.get("/api/bulk/estimate",
                      params={"kind": "transcribe", "unique_id": "stt"}).json()
    assert body["recordings"] == 1
    assert body["skipped"]["done"] == 1


@pytest.mark.parametrize("kwargs,label", [
    ({"word_times": False}, "nowords"),
    ({"timemap_version": TIMEMAP_VERSION - 1}, "oldmap"),
])
def test_transcribe_retargets_transcripts_that_cannot_be_used_as_subtitles(
        client, server, make_recording, kwargs, label):
    """行があるだけでは済みにしない。中身の版が古い文字起こしは再文字起こしでしか直らない。

    語の時刻を持たない文字起こしはcueを語の端で締められず、segmentの終端が次のsegmentの開始まで
    伸びたまま出る（実測: SRTがtimelineを覆う割合が中央値97.7%、実発話は約30%）。行の有無で
    済みにしていた頃は、この母集団が一括投入から永久に外れていた（実測293件・471時間）。
    """
    _s, old_id, _p = make_recording(unique_id=label)
    _save_transcript(server, old_id, **kwargs)

    body = client.get("/api/bulk/estimate",
                      params={"kind": "transcribe", "unique_id": label}).json()
    assert body["recordings"] == 1, label
    assert body["skipped"].get("done", 0) == 0, label


def test_transcribe_accepts_recordings_that_only_have_segments(client, server,
                                                               make_recording, monkeypatch):
    """入力は素材(.ts)でもよい。mp4を要求すると、単体では文字起こしできる録画が一括だけ弾かれる。"""
    make_recording(unique_id="tsonly", file_exists=False)
    _with_hls(server, monkeypatch)
    server.fsfacts._bulk_status_cache.clear()

    body = client.get("/api/bulk/estimate",
                      params={"kind": "transcribe", "unique_id": "tsonly"}).json()
    assert body["recordings"] == 1


def test_transcribe_redo_brings_back_transcribed_recordings(client, server,
                                                            make_recording):
    """modelを替えたときや時刻mapの版が上がったときは文字起こしをやり直すしかない。"""
    _s, recording_id, _p = make_recording(unique_id="again")
    _save_transcript(server, recording_id)

    plain = client.get("/api/bulk/estimate",
                       params={"kind": "transcribe", "unique_id": "again"}).json()
    redone = client.get("/api/bulk/estimate",
                        params={"kind": "transcribe", "unique_id": "again", "redo": 1}).json()
    assert (plain["recordings"], redone["recordings"]) == (0, 1)


def test_transcribe_queues_into_the_media_ledger_as_an_stt_job(
        client, server, make_recording, stt_ready):
    """文字起こしも映像jobと同じ台帳(kind=stt)で走る。台帳を分けていた頃は、同じGPUを
    取り合っているのにJob一覧へ出ず、取り消しも別画面だった。"""
    _s, recording_id, _p = make_recording(unique_id="into")

    body = client.post("/api/bulk/queue",
                       json={"kind": "transcribe", "unique_id": "into"}).json()

    assert body["total"] == 1
    assert body["recording_ids"] == [recording_id]
    assert ("stt", recording_id) in server.runtime.storage.pending_media_job_keys()


def test_transcribe_skips_recordings_already_in_the_stt_queue(client, server,
                                                              make_recording, stt_ready):
    """待機中の録画をもう一度積まない。判定は映像jobと同じ (kind, recording_id) で行う。"""
    _s, recording_id, _p = make_recording(unique_id="dup")
    server.runtime.storage.enqueue_media_job("j-dup", "stt", recording_id)
    server.fsfacts._bulk_status_cache.clear()

    body = client.get("/api/bulk/estimate",
                      params={"kind": "transcribe", "unique_id": "dup"}).json()
    assert body["recordings"] == 0
    assert body["skipped"]["queued"] == 1


def test_transcribe_redo_queues_an_already_transcribed_recording(client, server,
                                                                make_recording, stt_ready):
    """文字起こし済みでもredoなら積む。「済み」の根拠はtranscriptsの存在で、queueの行では
    ないため、やり直しはjobを1件足すだけで済む(doneの行を蘇生させる特殊操作が要らない)。"""
    _s, recording_id, _p = make_recording(unique_id="revive")
    _save_transcript(server, recording_id)
    server.fsfacts._bulk_status_cache.clear()

    body = client.post("/api/bulk/queue",
                       json={"kind": "transcribe", "unique_id": "revive", "redo": True}).json()

    assert body["total"] == 1
    assert ("stt", recording_id) in server.runtime.storage.pending_media_job_keys()


def test_transcribe_without_redo_leaves_transcribed_recordings_alone(
        client, server, make_recording, stt_ready):
    """redoを指定していないのに済みまで積むと、投入のたびに文字起こし済みをGPUで焼き直す。"""
    _s, recording_id, _p = make_recording(unique_id="keep")
    _save_transcript(server, recording_id)
    server.fsfacts._bulk_status_cache.clear()

    body = client.get("/api/bulk/estimate",
                      params={"kind": "transcribe", "unique_id": "keep"}).json()
    assert body["recordings"] == 0
    assert ("stt", recording_id) not in server.runtime.storage.pending_media_job_keys()


def test_transcribe_refuses_when_stt_is_unavailable(client, server, make_recording,
                                                    monkeypatch):
    """STTが無い環境で積むと、workerが1件ずつ失敗にするだけの行が残る。"""
    make_recording(unique_id="nostt")
    monkeypatch.setattr(server.routes.bulk, "stt_available", lambda: False)

    response = client.post("/api/bulk/queue",
                           json={"kind": "transcribe", "unique_id": "nostt"})
    assert response.status_code == 503


def test_transcribe_refuses_when_nothing_is_eligible(client, server, make_recording,
                                                     stt_ready):
    _s, recording_id, _p = make_recording(unique_id="allstt")
    _save_transcript(server, recording_id)

    response = client.post("/api/bulk/queue",
                           json={"kind": "transcribe", "unique_id": "allstt"})
    assert response.status_code == 409
    assert "処理済み" in response.json()["detail"]


def test_transcribe_eta_comes_from_finished_stt_jobs(client, server, make_recording):
    """所要の実測比は実績のあるjobから出す。文字起こしも同じ台帳(kind=stt)にいる。"""
    _s, past_id, _p = make_recording(unique_id="eta", seconds=100)
    server.runtime.storage.enqueue_media_job("j-eta", "stt", past_id)
    server.runtime.storage.finish_media_job("j-eta", "completed")
    # 100秒の録画を50秒で文字起こしした実績にする(状態遷移は実時刻を書くので上書きする)。
    with server.runtime.storage._lock:
        server.runtime.storage._conn.execute(
            "UPDATE media_job_queue SET started_at = 0, finished_at = 50"
            " WHERE job_id = 'j-eta'")
        server.runtime.storage._conn.commit()
    _save_transcript(server, past_id)
    make_recording(unique_id="eta", seconds=200)
    server.fsfacts._bulk_status_cache.clear()

    body = client.get("/api/bulk/estimate",
                      params={"kind": "transcribe", "unique_id": "eta"}).json()
    assert body["eta_samples"] == 1
    # STTは直列(worker1本)なので、同時実行数で詰まらない。
    assert body["eta_seconds"] == pytest.approx(100.0)


def test_transcribe_status_counts_targets_and_done(client, server, make_recording):
    make_recording(unique_id="cnt")
    _s, done_id, _p = make_recording(unique_id="cnt")
    _save_transcript(server, done_id)

    body = client.get("/api/bulk/status", params={"kinds": "transcribe"}).json()
    entry = next(s for s in body["streamers"] if s["unique_id"] == "cnt")
    assert (entry["targets"]["transcribe"], entry["done"]["transcribe"]) == (1, 1)
