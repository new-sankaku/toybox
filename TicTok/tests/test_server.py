import json
import secrets
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


@pytest.fixture
def server(env_guard):
    # env_guard を先に効かせてから import する。tictok.server は import 時に
    # Storage / instance lock / record dir を掴むため、順序が逆だと本番を掴む。
    import tictok.server as srv

    assert not str(srv.RECORD_DIR).lower().endswith("tictok\\recordings")
    return srv


@pytest.fixture
def client(server):
    # context manager として使わないこと。lifespan が走ると監視復元と queue worker が
    # 立ち上がり、shutdown で storage が閉じられて後続 test が使えなくなる。
    return TestClient(server.app)


@pytest.fixture
def make_srv_recording(server):
    def _make(unique_id="tester", status="completed", file_exists=True):
        storage = server.storage
        session_id = storage.create_session(unique_id, 60)
        storage.update_session(session_id, "connected")
        stem = f"00001_{unique_id}_{secrets.token_hex(4)}"
        directory = server.RECORD_DIR / unique_id / "mp4"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{stem}.mp4"
        if file_exists:
            path.write_bytes(b"\x00" * 64)
        started = time.time() - 600
        recording_id = storage.create_recording(
            session_id, unique_id, str(path), path.name, "hd", started)
        if status != "recording":
            storage.update_recording(
                recording_id, status, str(path), path.name, started + 300, 64)
        return session_id, recording_id, path

    return _make


# ---- path 安全性 ------------------------------------------------------------------

def test_safe_recording_path_accepts_path_under_record_root(server):
    inside = server.RECORD_DIR / "tester" / "mp4" / "a.mp4"
    assert server._safe_recording_path(str(inside)) == inside.resolve()


def test_safe_recording_path_rejects_sibling_of_record_root(server):
    outside = server.RECORD_DIR.parent / "escaped.mp4"
    with pytest.raises(HTTPException) as excinfo:
        server._safe_recording_path(str(outside))
    assert excinfo.value.status_code == 400


def test_safe_recording_path_rejects_traversal_that_climbs_out(server):
    traversal = server.RECORD_DIR / ".." / ".." / "windows" / "system32" / "x.mp4"
    with pytest.raises(HTTPException) as excinfo:
        server._safe_recording_path(str(traversal))
    assert excinfo.value.status_code == 400


def test_safe_recording_path_allows_traversal_that_stays_inside(server):
    # 正規化後に root 配下へ戻るなら通す。文字列一致ではなく resolve 後で判定していること。
    weird = server.RECORD_DIR / "tester" / ".." / "tester" / "mp4" / "a.mp4"
    resolved = server._safe_recording_path(str(weird))
    assert resolved == (server.RECORD_DIR / "tester" / "mp4" / "a.mp4").resolve()


# ---- unique_id の正規化 -----------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("@tester", "tester"),
    ("  @tester  ", "tester"),
    ("@@tester", "tester"),
    ("a.b_c", "a.b_c"),
    ("A" * 64, "A" * 64),
])
def test_normalize_unique_id_accepts(server, raw, expected):
    assert server._normalize_unique_id(raw) == expected


@pytest.mark.parametrize("raw", ["", "@", "has space", "日本語", "a/b", "A" * 65, "a-b"])
def test_normalize_unique_id_rejects(server, raw):
    with pytest.raises(HTTPException) as excinfo:
        server._normalize_unique_id(raw)
    assert excinfo.value.status_code == 422


# ---- page shell / 未定義 route ----------------------------------------------------

def test_index_page_is_served_with_revalidate_cache_control(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "no-cache" in response.headers["cache-control"]


def test_unknown_path_is_404(client):
    assert client.get("/no-such-page").status_code == 404


# ---- monitors ---------------------------------------------------------------------

def test_add_monitor_rejects_invalid_id_before_touching_network(client):
    response = client.post("/api/monitors", json={"unique_id": "bad id!"})
    assert response.status_code == 422
    assert "TikTok ID" in response.json()["detail"]


def test_add_monitor_rejects_empty_id_by_schema(client):
    # min_length=1 は pydantic 側なので detail は list になる(文字列の 422 とは別経路)。
    response = client.post("/api/monitors", json={"unique_id": ""})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


@pytest.mark.parametrize("method,path", [
    ("post", "/api/monitors/ghost/stop"),
    ("delete", "/api/monitors/ghost"),
    ("post", "/api/monitors/ghost/record/start"),
    ("post", "/api/monitors/ghost/record/stop"),
    ("get", "/api/monitors/ghost/timeline"),
    ("get", "/api/monitors/ghost/summary"),
    ("get", "/api/monitors/ghost/battles"),
])
def test_monitor_routes_404_for_unknown_target(client, method, path):
    response = getattr(client, method)(path)
    assert response.status_code == 404
    assert "@ghost" in response.json()["detail"]


def test_history_stats_of_unknown_streamer_is_empty_not_404(client):
    # 監視対象でなくても履歴照会は成立する(collector を要求しない経路)。
    response = client.get("/api/monitors/ghost/history-stats")
    assert response.status_code == 200
    assert isinstance(response.json(), dict)


# ---- sessions ---------------------------------------------------------------------

def test_session_detail_404_for_unknown_id(client):
    response = client.get("/api/sessions/99999999")
    assert response.status_code == 404
    assert "99999999" in response.json()["detail"]


def test_session_detail_shape_for_recording_without_derivatives(client, make_srv_recording):
    session_id, recording_id, _ = make_srv_recording()
    body = client.get(f"/api/sessions/{session_id}").json()
    assert set(body) >= {"session", "timeline", "summary", "recordings", "owner", "battles"}
    rec = next(r for r in body["recordings"] if r["id"] == recording_id)
    assert (rec["has_transcript"], rec["has_output"], rec["has_up_output"]) == (False, False, False)


def test_patch_session_note_round_trips(client, make_srv_recording):
    session_id, _, _ = make_srv_recording()
    assert client.patch(f"/api/sessions/{session_id}", json={"note": "メモ"}).status_code == 200
    assert client.get(f"/api/sessions/{session_id}").json()["session"]["note"] == "メモ"


def test_patch_session_note_rejects_over_10000_chars(client, make_srv_recording):
    session_id, _, _ = make_srv_recording()
    response = client.patch(f"/api/sessions/{session_id}", json={"note": "x" * 10001})
    assert response.status_code == 422


def test_delete_session_removes_recording_file_and_row(client, make_srv_recording):
    session_id, recording_id, path = make_srv_recording()
    assert path.is_file()
    assert client.delete(f"/api/sessions/{session_id}").json() == {"deleted": session_id}
    assert not path.exists()
    assert client.get(f"/api/sessions/{session_id}").status_code == 404


def test_delete_sessions_by_users_requires_non_empty_list(client):
    assert client.post("/api/sessions/delete-by-users", json={"unique_ids": []}).status_code == 422


def test_delete_sessions_by_unknown_user_deletes_nothing(client):
    response = client.post("/api/sessions/delete-by-users",
                           json={"unique_ids": ["nobody_here"]})
    assert response.json() == {"deleted_sessions": 0}


def test_export_csv_starts_with_bom_and_header(client, make_srv_recording):
    session_id, _, _ = make_srv_recording()
    response = client.get(f"/api/sessions/{session_id}/export.csv")
    assert response.status_code == 200
    text = response.content.decode("utf-8")
    assert text.startswith("﻿time,kind,user_unique_id")
    assert f"tictok_session_{session_id}_tester.csv" in response.headers["content-disposition"]


def test_export_json_contains_the_four_sections(client, make_srv_recording):
    session_id, _, _ = make_srv_recording()
    response = client.get(f"/api/sessions/{session_id}/export.json")
    payload = json.loads(response.content.decode("utf-8"))
    assert set(payload) == {"session", "summary", "timeline", "events"}
    assert payload["session"]["id"] == session_id


def test_export_of_unknown_session_is_404(client):
    assert client.get("/api/sessions/99999999/export.csv").status_code == 404
    assert client.get("/api/sessions/99999999/export.json").status_code == 404


# ---- ops log ----------------------------------------------------------------------

def test_ops_events_rejects_unknown_severity(client):
    response = client.get("/api/ops/events", params={"severity": "critical"})
    assert response.status_code == 422
    assert "critical" in response.json()["detail"]


def test_ops_events_honours_limit_and_reports_page_size(client, server):
    body = client.get("/api/ops/events", params={"limit": 1}).json()
    assert body["limit"] == 1
    assert len(body["events"]) <= 1
    assert body["severities"] == list(server.OPS_SEVERITIES)


def test_ops_events_limit_zero_falls_back_to_the_configured_cap(client):
    from tictok.core.config import get_ops_events_query_limit

    body = client.get("/api/ops/events", params={"limit": 0}).json()
    assert body["limit"] == get_ops_events_query_limit()


def test_ops_events_never_asks_storage_for_a_non_positive_page(client, monkeypatch):
    """設定上限が壊れていてもendpointは1以上を渡す。storage側は0以下でValueErrorを投げる
    ので、limit未指定の経路がclampを迂回していると500になる。"""
    monkeypatch.setenv("TICTOK_OPS_EVENTS_QUERY_LIMIT", "0")
    body = client.get("/api/ops/events").json()
    assert body["limit"] == 1


def test_ops_events_negative_limit_does_not_disable_the_cap(client):
    # SQLのLIMIT -1は無制限。負値を素通しすると全行返り、next判定も常に真になる。
    body = client.get("/api/ops/events", params={"limit": -1}).json()
    assert body["limit"] == 1
    assert len(body["events"]) <= 1


def test_ops_events_limit_above_the_cap_is_clamped(client):
    from tictok.core.config import get_ops_events_query_limit

    cap = get_ops_events_query_limit()
    body = client.get("/api/ops/events", params={"limit": cap + 100}).json()
    assert body["limit"] == cap


def test_ops_summary_reports_every_severity_bucket(client, server):
    body = client.get("/api/ops/summary", params={"hours": 1}).json()
    assert body["window_hours"] == 1.0
    assert set(body["counts"]) == set(server.OPS_SEVERITIES)
    assert all(isinstance(v, int) for v in body["counts"].values())


# ---- settings ---------------------------------------------------------------------

def test_settings_update_rejects_unknown_key(client):
    response = client.put("/api/settings", json={"no_such_setting": 1})
    assert response.status_code == 422
    assert "不明な設定key" in response.json()["detail"]


def test_settings_update_rejects_non_integer_for_int_setting(client, server):
    # int(10.9)=10 の黙った切り捨てを拒否する、という設計の回帰 test。
    before = server.settings.get("session_list_limit")
    response = client.put("/api/settings", json={"session_list_limit": 10.9})
    assert response.status_code == 422
    assert server.settings.get("session_list_limit") == before


def test_settings_update_rejects_out_of_range_value(client, server):
    before = server.settings.get("session_list_limit")
    response = client.put("/api/settings", json={"session_list_limit": -1})
    assert response.status_code == 422
    assert server.settings.get("session_list_limit") == before


def test_settings_update_round_trips_valid_value(client, server):
    before = server.settings.get("session_list_limit")
    try:
        response = client.put("/api/settings", json={"session_list_limit": 123})
        assert response.status_code == 200
        # values は差分ではなく更新後の全設定 snapshot。
        assert response.json()["values"]["session_list_limit"] == 123
        described = {row["key"]: row["value"] for row in client.get("/api/settings").json()["settings"]}
        assert described["session_list_limit"] == 123
    finally:
        server.settings.update({"session_list_limit": before})


# ---- recordings / transcript ------------------------------------------------------

def test_transcript_404_distinguishes_missing_recording_from_missing_transcript(
        client, make_srv_recording):
    _, recording_id, _ = make_srv_recording()
    missing = client.get("/api/recordings/99999999/transcript")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "録画が見つかりません。"
    no_transcript = client.get(f"/api/recordings/{recording_id}/transcript")
    assert no_transcript.status_code == 404
    assert no_transcript.json()["detail"] != missing.json()["detail"]


def test_transcript_export_rejects_unknown_format_before_lookup(client):
    # format check が録画の存在確認より前にあること(未知 id でも 400 が返る)。
    response = client.get("/api/recordings/99999999/transcript/export",
                          params={"format": "ass"})
    assert response.status_code == 400


def test_delete_recording_404_for_unknown_id(client):
    assert client.delete("/api/recordings/99999999").status_code == 404


def test_delete_recording_refuses_while_still_recording(client, make_srv_recording):
    _, recording_id, path = make_srv_recording(status="recording")
    response = client.delete(f"/api/recordings/{recording_id}")
    assert response.status_code == 409
    assert path.is_file()


def test_delete_recording_removes_the_file(client, make_srv_recording):
    _, recording_id, path = make_srv_recording()
    assert client.delete(f"/api/recordings/{recording_id}").json() == {"deleted": recording_id}
    assert not path.exists()


def test_play_404s_when_the_row_exists_but_the_file_is_gone(client, make_srv_recording):
    _, recording_id, path = make_srv_recording()
    path.unlink()
    response = client.get(f"/api/recordings/{recording_id}/play")
    assert response.status_code == 404
    assert response.json()["detail"] == "録画fileが存在しません。"


def test_comments_404_for_unknown_recording(client):
    assert client.get("/api/recordings/99999999/comments").status_code == 404


def test_comments_are_empty_when_nothing_is_indexed(client, make_srv_recording):
    _, recording_id, _ = make_srv_recording()
    body = client.get(f"/api/recordings/{recording_id}/comments").json()
    assert body == {"recording_id": recording_id, "items": []}


# ---- cut list / bookmarks ---------------------------------------------------------

def test_add_cut_404_for_unknown_recording(client):
    response = client.post("/api/cutlist",
                           json={"recording_id": 99999999, "start": 0, "end": 5})
    assert response.status_code == 404


def test_add_cut_rejects_non_positive_range(client, make_srv_recording):
    _, recording_id, _ = make_srv_recording()
    response = client.post(
        "/api/cutlist", json={"recording_id": recording_id, "start": 10, "end": 10})
    assert response.status_code == 400
    assert "終了位置" in response.json()["detail"]


def test_cut_lifecycle_add_list_delete(client, make_srv_recording):
    _, recording_id, _ = make_srv_recording()
    created = client.post(
        "/api/cutlist",
        json={"recording_id": recording_id, "start": 1.5, "end": 9.0, "label": "山場"},
    ).json()
    listed = client.get("/api/cutlist").json()["items"]
    assert any(c["id"] == created["id"] and c["label"] == "山場" for c in listed)
    assert client.delete(f"/api/cutlist/{created['id']}").json() == {"deleted": created["id"]}
    assert client.delete(f"/api/cutlist/{created['id']}").status_code == 404


def test_cutlist_export_rejects_unknown_format(client):
    response = client.get("/api/cutlist/export", params={"format": "xml"})
    assert response.status_code == 400


def test_cutlist_csv_export_is_bom_prefixed(client):
    response = client.get("/api/cutlist/export", params={"format": "csv"})
    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")


def test_add_bookmark_rejects_end_at_or_before_start(client, make_srv_recording):
    _, recording_id, _ = make_srv_recording()
    response = client.post(
        "/api/bookmarks", json={"recording_id": recording_id, "start": 5, "end": 5})
    assert response.status_code == 400


def test_bookmark_without_end_is_a_point(client, make_srv_recording):
    _, recording_id, _ = make_srv_recording()
    created = client.post(
        "/api/bookmarks", json={"recording_id": recording_id, "start": 7.25}).json()
    assert created["end"] is None
    listed = client.get("/api/bookmarks", params={"recording_id": recording_id}).json()["items"]
    assert [b["id"] for b in listed] == [created["id"]]


def test_patch_unknown_bookmark_is_404(client):
    assert client.patch("/api/bookmarks/99999999", json={"memo": "x"}).status_code == 404


# ---- jobs -------------------------------------------------------------------------

def test_cancel_unknown_job_is_404(client):
    response = client.post("/api/jobs/deadbeef/cancel")
    assert response.status_code == 404


def test_retry_unknown_job_is_404(client):
    assert client.post("/api/jobs/deadbeef/retry").status_code == 404


def test_retry_clip_batch_carries_over_the_saved_params(client, server, make_srv_recording):
    # paramsを引き継がないと ranges=[] の空jobがcompletedになり、無言で空振りする。
    _, recording_id, _ = make_srv_recording()
    storage = server.storage
    params = {
        "variant": "source",
        "normalize_audio": False,
        "precise": False,
        "ranges": [{"start": 1.0, "end": 3.0, "label": "山場"}],
    }
    job_id = secrets.token_hex(4)
    storage.enqueue_media_job(job_id, "clip_batch", recording_id, params=params)
    storage.finish_media_job(job_id, "failed", error="boom")
    body = client.post(f"/api/jobs/{job_id}/retry").json()
    assert storage.get_media_job(body["job_id"])["params"] == params


def test_clip_batch_rejects_empty_items(client):
    response = client.post("/api/clips/batch", json={"items": []})
    assert response.status_code == 400


def test_clip_batch_rejects_unknown_variant(client, make_srv_recording):
    _, recording_id, _ = make_srv_recording()
    response = client.post("/api/clips/batch", json={
        "items": [{"recording_id": recording_id, "start": 0, "end": 1}],
        "variant": "hdr",
    })
    assert response.status_code == 400
    assert "hdr" in response.json()["detail"]


# ---- search / avatar / disk -------------------------------------------------------

def test_search_requires_a_query(client):
    assert client.get("/api/search").status_code == 422


def test_search_ignores_unknown_sources_and_returns_no_hits(client):
    body = client.get("/api/search", params={"q": "存在しない語句", "sources": "bogus"}).json()
    assert body["items"] == []


def test_avatar_proxy_rejects_non_allowlisted_host(client):
    response = client.get("/api/avatar", params={"u": "http://evil.example/a.jpg"})
    assert response.status_code == 400


def test_disk_report_names_the_configured_floor(client, server):
    body = client.get("/api/disk").json()
    assert set(body) == {"volumes", "min_free_bytes", "low_volumes"}
    assert body["min_free_bytes"] == int(server.settings.get("disk_min_free_gb")) * 1024 ** 3


# ---- AI (env で無効) --------------------------------------------------------------

def test_comment_analysis_get_returns_null_without_running_the_model(client, make_srv_recording):
    session_id, _, _ = make_srv_recording()
    body = client.get(f"/api/sessions/{session_id}/comment-analysis").json()
    assert body["analysis"] is None
    assert body["cached"] is False


def test_comment_analysis_post_is_503_when_ai_is_disabled(client, make_srv_recording):
    session_id, _, _ = make_srv_recording()
    response = client.post(f"/api/sessions/{session_id}/comment-analysis")
    assert response.status_code == 503
    assert "AI機能が無効" in response.json()["detail"]


def test_ai_review_post_is_503_before_looking_up_the_streamer(client):
    response = client.post("/api/streamers/nobody_here/ai-review")
    assert response.status_code == 503


# --------------------------------------------------------------------------
# session出力: 実fileの無い録画をqueueへ載せない
# --------------------------------------------------------------------------


def test_session_output_targets_skip_recordings_whose_file_is_gone(
        server, make_srv_recording):
    """fileが消えた行までqueueへ載ると、workerが1件ずつ404で落ちる。"""
    session_id, recording_id, path = make_srv_recording(status="completed")
    ok_session, ok_recording, _ = make_srv_recording(status="completed")
    path.unlink()

    with pytest.raises(HTTPException) as excinfo:
        server._session_output_targets(session_id)
    assert excinfo.value.status_code == 409
    assert "録画file" in excinfo.value.detail

    assert [r["id"] for r in server._session_output_targets(ok_session)] == [ok_recording]


def test_session_output_targets_reject_a_row_pointing_at_a_directory(
        server, make_srv_recording):
    """finalizeがDB更新前に落ちた行のpathは録画dirのまま。file扱いしてはいけない。"""
    session_id, recording_id, _ = make_srv_recording(status="interrupted")
    server.storage.update_recording(
        recording_id, "interrupted", str(server.RECORD_DIR), "x.mp4", None, 0)

    with pytest.raises(HTTPException) as excinfo:
        server._session_output_targets(session_id)
    assert excinfo.value.status_code == 409


async def test_media_job_skips_instead_of_failing_when_the_file_is_gone(
        server, make_srv_recording):
    """待っても戻らない前提不成立は、retryを消費する失敗ではなくskipで畳む。"""
    from tictok.record.media_queue import JobSkipped

    _, recording_id, path = make_srv_recording(status="completed")
    path.unlink()

    async def report(stage, pct):
        return None

    job = {"kind": "overlay", "recording_id": recording_id, "job_id": "test0001"}
    with pytest.raises(JobSkipped):
        await server._run_media_job(job, report)


async def test_media_job_skips_when_the_recording_row_is_gone(server):
    from tictok.record.media_queue import JobSkipped

    async def report(stage, pct):
        return None

    job = {"kind": "reprocess", "recording_id": 999999, "job_id": "test0002"}
    with pytest.raises(JobSkipped):
        await server._run_media_job(job, report)
