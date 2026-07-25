import itertools
import json
import re
import secrets
import time
import types
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

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


def _nav_hrefs() -> list[str]:
    """common.js の NAV_ITEMS から href を読む。"""
    source = (STATIC_DIR / "common.js").read_text(encoding="utf-8")
    block = re.search(r"const NAV_ITEMS = \[(.*?)\];", source, re.S)
    assert block, "common.js に NAV_ITEMS が見つかりません。"
    return re.findall(r'\["([^"]+)",', block.group(1))


# FastAPIが自前で生やす調査用route。画面ではないのでnavの対象外。
FRAMEWORK_ROUTES = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}


def _page_routes(server) -> set[str]:
    """/api を除いた GET の page route。"""
    return {
        route.path
        for route in server.app.routes
        if getattr(route, "methods", None)
        and "GET" in route.methods
        and not route.path.startswith("/api")
        and not route.path.startswith("/static")
        and "{" not in route.path
        and route.path not in FRAMEWORK_ROUTES
    }


# navとrouteは別fileにあるため、片方だけ足すと黙って壊れる。実際 /compare は
# route未登録かつnav未掲載で到達不能なまま、/battle はrouteだけ残って放置されていた。
# 「navから開ける」「routeは全部navに載っている」の両方向をここで固定する。
def test_every_nav_link_is_served(client):
    for href in _nav_hrefs():
        assert client.get(href).status_code == 200, f"nav の {href} が開けません。"


def test_every_page_route_is_reachable_from_nav(server):
    orphans = _page_routes(server) - set(_nav_hrefs())
    assert not orphans, f"navから到達できないpage routeがあります: {sorted(orphans)}"


# 画面のHTMLとJSは別fileで、片方だけ直しても誰も気付かない(要素が見つからず、その先の
# 描画が例外で止まるだけ)。JSが名指しするidがHTMLに在ることをここで固定する。
def test_every_page_script_only_touches_ids_that_exist():
    for js in sorted(STATIC_DIR.glob("*.js")):
        html = STATIC_DIR / f"{js.stem}.html"
        if not html.exists():
            continue
        present = set(re.findall(r'id="([^"]+)"', html.read_text(encoding="utf-8")))
        source = js.read_text(encoding="utf-8")
        wanted = set(re.findall(r'getElementById\("([^"]+)"\)', source))
        wanted |= set(re.findall(r'renderTableRows\(\s*"([^"]+)"', source))
        assert not wanted - present, f"{js.name} が触るidが {html.name} にありません: {sorted(wanted - present)}"


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


# シーン検索は語が無いと0件を返す。語なしで「録画をそのまま開く」導線がこの一覧なので、
# 語を1文字も打たない状態で中身が返ることそのものが仕様。
def test_browse_recordings_lists_completed_recordings_without_a_query(client, make_srv_recording):
    _, recording_id, _ = make_srv_recording(unique_id="browsable")
    body = client.get("/api/recordings/browse").json()
    rec = next(r for r in body["recordings"] if r["recording_id"] == recording_id)
    assert rec["unique_id"] == "browsable"
    assert rec["has_transcript"] is False
    assert rec["file_exists"] is True


def test_browse_recordings_filters_by_streamer(client, make_srv_recording):
    _, wanted, _ = make_srv_recording(unique_id="wanted")
    _, other, _ = make_srv_recording(unique_id="other")
    ids = {r["recording_id"] for r in client.get(
        "/api/recordings/browse?unique_id=wanted").json()["recordings"]}
    assert wanted in ids and other not in ids


def test_browse_recordings_omits_still_recording_rows(client, make_srv_recording):
    _, running, _ = make_srv_recording(status="recording")
    ids = {r["recording_id"] for r in client.get("/api/recordings/browse").json()["recordings"]}
    assert running not in ids


def test_browse_recordings_reports_a_deleted_file_as_missing(client, make_srv_recording):
    _, recording_id, path = make_srv_recording()
    path.unlink()
    body = client.get("/api/recordings/browse").json()
    rec = next(r for r in body["recordings"] if r["recording_id"] == recording_id)
    assert rec["file_exists"] is False


def test_browse_recordings_reports_the_measured_duration_not_the_wall_clock(
        client, server, make_srv_recording):
    """一覧の尺は実測値だけを出す。壁時計(ended_at - started_at)は捕捉の停滞ぶんが載る上、
    再処理でended_atが「今」に潰れた録画では数百時間に化ける(実測: 3時間13分が177時間)。"""
    _, recording_id, _ = make_srv_recording()
    server.storage.set_recording_duration(recording_id, 123.0)

    body = client.get("/api/recordings/browse").json()
    rec = next(r for r in body["recordings"] if r["recording_id"] == recording_id)
    # fixtureの壁時計は300秒。尺はそちらではなく実測の123秒。
    assert rec["ended_at"] - rec["started_at"] == pytest.approx(300.0)
    assert rec["duration_seconds"] == 123.0


def test_browse_recordings_leaves_an_unmeasured_duration_null(client, make_srv_recording):
    """測っていない録画に壁時計を代入しない。画面は「—」と出す。"""
    _, recording_id, _ = make_srv_recording()
    body = client.get("/api/recordings/browse").json()
    rec = next(r for r in body["recordings"] if r["recording_id"] == recording_id)
    assert rec["duration_seconds"] is None


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


def test_ops_events_rejects_unknown_min_severity(client):
    response = client.get("/api/ops/events", params={"min_severity": "critical"})
    assert response.status_code == 422
    assert "critical" in response.json()["detail"]


def test_ops_events_min_severity_keeps_everything_above_the_threshold(client, server):
    """「warning以上」はwarningとerrorを両方返す。片方だけになると、障害を追うために
    絞った画面からerrorが消える。"""
    import logging

    storage = server.storage
    log = logging.getLogger("tictok.test")
    for severity in server.OPS_SEVERITIES:
        storage.record_ops_event(log, f"test.{severity}", f"{severity}の記録",
                                 severity=severity)
    events = client.get("/api/ops/events",
                        params={"min_severity": "warning", "limit": 200}).json()["events"]
    kinds = {e["kind"] for e in events if e["kind"].startswith("test.")}
    assert kinds == {"test.warning", "test.error"}

    only_error = client.get("/api/ops/events",
                            params={"min_severity": "error", "limit": 200}).json()["events"]
    assert {e["kind"] for e in only_error if e["kind"].startswith("test.")} == {"test.error"}


def test_ops_events_exposes_kind_labels_for_every_recorded_kind(client, server):
    """種別は画面で日本語ラベルに置き換える。記録されているkindが表に無いと、その行だけ
    code値のまま出る。"""
    body = client.get("/api/ops/events", params={"limit": 200}).json()
    labels = body["kind_labels"]
    assert labels["collector.disconnected"]
    assert labels["overlay.job_failed"]


def test_ops_kinds_lists_streamer_candidates_from_the_log_itself(client, server):
    import logging

    server.storage.record_ops_event(logging.getLogger("tictok.test"),
                                    "test.info", "候補用の記録", unique_id="cand_streamer")
    body = client.get("/api/ops/kinds").json()
    assert "cand_streamer" in {e["unique_id"] for e in body["unique_ids"]}
    assert all(e["count"] >= 1 for e in body["unique_ids"])


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


def test_play_serves_the_overlay_file_when_that_variant_is_asked_for(
        client, make_srv_recording):
    """素材版を選んで再生できないと、焼き込みの出来は外部playerでしか確かめられない。"""
    from tictok.record.video_overlay import overlay_paths

    _, recording_id, path = make_srv_recording()
    overlay = overlay_paths(path)[0]
    overlay.parent.mkdir(parents=True, exist_ok=True)
    overlay.write_bytes(b"overlay-body")
    response = client.get(f"/api/recordings/{recording_id}/play", params={"variant": "overlay"})
    assert response.status_code == 200
    assert response.content == b"overlay-body"


def test_play_refuses_a_variant_that_was_never_produced(client, make_srv_recording):
    """無い版を黙って元録画へ落とすと、焼き込んだつもりの素の動画を出来として見てしまう。"""
    _, recording_id, _ = make_srv_recording()
    response = client.get(f"/api/recordings/{recording_id}/play", params={"variant": "overlay"})
    assert response.status_code == 404
    assert "焼き込み出力" in response.json()["detail"]


def test_play_rejects_an_unknown_variant(client, make_srv_recording):
    _, recording_id, _ = make_srv_recording()
    response = client.get(f"/api/recordings/{recording_id}/play", params={"variant": "hdr"})
    assert response.status_code == 400


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


def _stub_reprocess_recorder(server, monkeypatch):
    """再mp4化のffmpegを外し、渡された mp4_root へmp4を1本置くだけのRecorderに差し替える。
    構築時のkwargsを返し、読む先(record_dir)と書く先(final_dir)の指定を検証できるようにする。"""
    from tictok.core import layout

    seen = {}

    class _StubRecorder:
        def __init__(self, *args, **kwargs):
            seen["args"] = args
            seen["kwargs"] = kwargs
            self.state = "pending"
            self.error = None
            self.ended_at = time.time()
            self.output_path = None

        async def finalize_recovered_hls(self, base, progress=None, mp4_root=None):
            out = layout.mp4_path(mp4_root or Path(seen["args"][1]), base)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"\x00" * 128)
            self.output_path = out
            self.state = "completed"

        def snapshot(self):
            return {"bytes": 128}

    monkeypatch.setattr(server, "Recorder", _StubRecorder)
    monkeypatch.setattr(server, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(server, "ffprobe_available", lambda: True)
    return seen


def _split_record_roots(server, monkeypatch, final_dir: Path):
    """1次(work)と2次(final)が別dirの構成へ差し替える。既定のtest環境は両者が同一で、
    root跨ぎの判定が一切効かない。"""
    final_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server, "FINAL_DIR", final_dir)
    monkeypatch.setattr(server, "_RECORD_ROOTS", [server.RECORD_DIR, final_dir])


async def test_reprocess_reports_completion_after_updating_the_recording(
        server, make_srv_recording, monkeypatch):
    """成功の末尾(100%通知)まで通す。ここが例外になると、実処理が全部終わった後に
    jobがfailedへ倒れ、queueが同じ録画をもう一度まるごと再実行する。"""
    from tictok.core import layout

    _, recording_id, path = make_srv_recording(status="completed")
    stem = path.stem
    monkeypatch.setattr(server, "_find_hls_root", lambda _stem: server.RECORD_DIR)
    _stub_reprocess_recorder(server, monkeypatch)

    stages = []

    async def report(stage, pct):
        stages.append((stage, pct))

    recording = server.storage.get_recording(recording_id)
    result = await server._reprocess_recording(recording_id, recording, "test0003", report)

    assert result["recording_id"] == recording_id
    assert stages[-1][1] == 100
    assert server.storage.get_recording(recording_id)["path"] == str(
        layout.mp4_path(server.RECORD_DIR, stem))


async def test_reprocess_writes_back_to_the_root_holding_the_mp4(
        server, make_srv_recording, monkeypatch, tmp_path):
    """2次(final)へ移送済みの録画は2次へ作り直す。.tsは1次に残るので、segment側を基準に
    すると再mp4化のたびに録画が1次へ引っ越し、録画中の書き込み先を食い潰す。"""
    from tictok.core import layout

    final_dir = tmp_path / "final"
    _split_record_roots(server, monkeypatch, final_dir)
    _, recording_id, path = make_srv_recording(status="completed")
    stem = path.stem
    # 実際の移送と同じ形にする: mp4は2次へ、.tsは1次に残す。
    moved = layout.mp4_path(final_dir, stem)
    moved.parent.mkdir(parents=True, exist_ok=True)
    path.replace(moved)
    server.storage.update_recording(recording_id, "completed", str(moved), moved.name,
                                    time.time(), moved.stat().st_size, None)
    monkeypatch.setattr(server, "_find_hls_root", lambda _stem: server.RECORD_DIR)
    seen = _stub_reprocess_recorder(server, monkeypatch)

    async def report(stage, pct):
        return None

    recording = server.storage.get_recording(recording_id)
    result = await server._reprocess_recording(recording_id, recording, "test0004", report)

    assert result["output_path"] == str(layout.mp4_path(final_dir, stem))
    assert result["backup"] == str(final_dir / "_backup" / f"{stem}.mp4")
    assert server.storage.get_recording(recording_id)["path"] == str(
        layout.mp4_path(final_dir, stem))
    # 1次にはこの録画の新しいmp4も退避も残さない。
    assert not layout.mp4_path(server.RECORD_DIR, stem).exists()
    assert not (server.RECORD_DIR / "_backup" / f"{stem}.mp4").exists()
    # 読む先は.tsのroot、書く先はmp4のroot。
    assert seen["args"][1] == str(server.RECORD_DIR)
    assert seen["kwargs"]["final_dir"] == str(final_dir)


async def test_reprocess_keeps_a_working_dir_recording_in_the_working_dir(
        server, make_srv_recording, monkeypatch, tmp_path):
    """1次に在る録画は1次のまま。2次が設定済みでも勝手に移送しない(移送は録画本番の
    finalizeの仕事で、再mp4化は置き場を変えない)。"""
    from tictok.core import layout

    final_dir = tmp_path / "final"
    _split_record_roots(server, monkeypatch, final_dir)
    _, recording_id, path = make_srv_recording(status="completed")
    stem = path.stem
    monkeypatch.setattr(server, "_find_hls_root", lambda _stem: server.RECORD_DIR)
    _stub_reprocess_recorder(server, monkeypatch)

    async def report(stage, pct):
        return None

    recording = server.storage.get_recording(recording_id)
    result = await server._reprocess_recording(recording_id, recording, "test0005", report)

    assert result["output_path"] == str(layout.mp4_path(server.RECORD_DIR, stem))
    assert result["backup"] == str(server.RECORD_DIR / "_backup" / f"{stem}.mp4")
    assert not layout.mp4_path(final_dir, stem).exists()
    assert not (final_dir / "_backup").exists()


def test_recording_home_root_falls_back_to_the_final_dir_when_the_mp4_is_gone(
        server, make_srv_recording, monkeypatch, tmp_path):
    """mp4が消えた録画は手掛かりが行のpathしかない。それも辿れなければ完成mp4の
    既定の置き場(2次)へ作り直す。"""
    final_dir = tmp_path / "final"
    _split_record_roots(server, monkeypatch, final_dir)
    _, recording_id, path = make_srv_recording(status="completed")
    stem = path.stem
    path.unlink()

    recording = server.storage.get_recording(recording_id)
    # 行は1次のpathを指したまま = そこが住所。
    assert server._recording_home_root(recording, stem) == server.RECORD_DIR

    server.storage.update_recording(recording_id, "completed", "", "", None, 0, None)
    assert server._recording_home_root(
        server.storage.get_recording(recording_id), stem) == final_dir


async def test_retry_of_a_group_requeues_only_its_failed_members(
        server, make_srv_recording, client):
    """一括の失敗ぶんを1clickで続きから流す。完了済みを巻き込むとGPU時間を捨てる。"""
    _s, ok_id, _p = make_srv_recording()
    _s2, ng_id, _p2 = make_srv_recording()
    await server.media_job_queue.enqueue("grp-ok", "reprocess", ok_id, group_id="grp")
    await server.media_job_queue.enqueue("grp-ng", "reprocess", ng_id, group_id="grp")
    server.storage.finish_media_job("grp-ok", "completed")
    server.storage.finish_media_job("grp-ng", "failed", error="保存先が見つかりません")

    body = client.post("/api/jobs/grp/retry").json()

    assert body["requeued"] == 1
    assert server.storage.get_media_job("grp-ng")["state"] == "pending"
    assert server.storage.get_media_job("grp-ng")["error"] is None
    assert server.storage.get_media_job("grp-ok")["state"] == "completed"
    # 母数を増やさない: 増やすとgroupは何度やり直しても完了に到達しない。
    assert len(server.storage.media_jobs_in_group("grp")) == 2


async def test_retry_of_a_group_without_failures_is_refused(
        server, make_srv_recording, client):
    _s, ok_id, _p = make_srv_recording()
    await server.media_job_queue.enqueue("g2-a", "reprocess", ok_id, group_id="grp2")
    server.storage.finish_media_job("g2-a", "completed")

    response = client.post("/api/jobs/grp2/retry")
    assert response.status_code == 409


async def test_media_job_runner_defers_instead_of_failing_when_a_root_is_gone(
        server, make_srv_recording, monkeypatch, tmp_path):
    """保存先が消えている間の失敗はどれも二次症状。失敗として残すと一括の中に原因不明の
    欠落が散らばり、復帰しても誰も拾い直さない。"""
    from tictok.record.media_queue import JobDeferred

    _s, recording_id, _p = make_srv_recording()
    monkeypatch.setattr(server, "_RECORD_ROOTS", [server.RECORD_DIR, tmp_path / "gone"])

    async def report(stage, pct):
        return None

    job = {"kind": "reprocess", "recording_id": recording_id, "job_id": "test0006"}
    with pytest.raises(JobDeferred) as excinfo:
        await server._media_job_runner(job, report)
    assert "保存先が見つかりません" in str(excinfo.value)


async def test_media_job_runner_defers_when_a_root_disappears_mid_run(
        server, make_srv_recording, monkeypatch, tmp_path):
    from tictok.record.media_queue import JobDeferred

    _s, recording_id, _p = make_srv_recording()
    gone = tmp_path / "gone"

    async def boom(_job, _report):
        # 実行中にvolumeが落ちた状況: ffmpegは意味の分からない終了コードで死ぬ。
        monkeypatch.setattr(server, "_RECORD_ROOTS", [server.RECORD_DIR, gone])
        raise OSError("ffmpeg exited -22")

    monkeypatch.setattr(server, "_run_media_job", boom)

    async def report(stage, pct):
        return None

    with pytest.raises(JobDeferred):
        await server._media_job_runner(
            {"kind": "reprocess", "recording_id": recording_id, "job_id": "test0007"}, report)


async def test_media_job_skips_when_the_recording_row_is_gone(server):
    from tictok.record.media_queue import JobSkipped

    async def report(stage, pct):
        return None

    job = {"kind": "reprocess", "recording_id": 999999, "job_id": "test0002"}
    with pytest.raises(JobSkipped):
        await server._run_media_job(job, report)


# ---- live見どころ ------------------------------------------------------------------

def test_live_bookmark_on_unknown_monitor_is_404(client):
    response = client.post("/api/monitors/ghost/bookmark", json={"memo": ""})
    assert response.status_code == 404
    assert "@ghost" in response.json()["detail"]


def test_live_bookmark_requires_an_active_recording(client, server):
    """録画していない配信には打てない。見どころは動画の中の位置を指すので、
    録画が無ければ後から戻る先が無く、再生できない印が残るだけになる。"""
    class _Collector:
        def snapshot(self):
            return {"status": "connected", "recording": None}

    server.manager._collectors["idle_user"] = _Collector()
    try:
        response = client.post("/api/monitors/idle_user/bookmark", json={"memo": ""})
    finally:
        server.manager._collectors.pop("idle_user", None)
    assert response.status_code == 409
    assert "録画中ではありません" in response.json()["detail"]


def test_live_bookmark_is_stamped_by_the_server_and_left_unmapped(
    client, server, make_srv_recording
):
    """Serverが今の時刻で打ち、PTS未確定(pts_mapped=0)で入ること。
    clientから時刻を受け取るとbrowserの時計ずれがそのまま印のずれになる。"""
    _session_id, recording_id, _path = make_srv_recording(
        unique_id="live_user", status="recording")
    started = time.time() - 120

    class _Collector:
        def snapshot(self):
            return {"status": "connected",
                    "recording": {"state": "recording", "live": True,
                                  "recording_id": recording_id, "started_at": started}}

    server.manager._collectors["live_user"] = _Collector()
    try:
        created = client.post("/api/monitors/live_user/bookmark",
                              json={"memo": "ここ"}).json()
    finally:
        server.manager._collectors.pop("live_user", None)

    assert created["pts_mapped"] == 0
    assert created["memo"] == "ここ"
    assert created["live_wall"] == pytest.approx(time.time(), abs=10)
    # 暫定startは録画開始からの経過秒。確定値ではない。
    assert created["start"] == pytest.approx(120, abs=10)
    assert server.storage.list_unmapped_bookmarks(recording_id)[0]["id"] == created["id"]


# ---- 容量予測 ----------------------------------------------------------------------

@pytest.fixture
def capacity_settings(server, monkeypatch):
    """容量予測の設定値。SETTING_DEFSはこのAgentの担当外(team-lead管理)なので、
    endpointの検証ではsettings.getを差し替えて既定相当を与える。"""
    defaults = {
        "capacity_sample_interval_hours": 24,
        "capacity_forecast_min_samples": 3,
        "capacity_forecast_max_extrapolation": 3.0,
        "capacity_alert_days": 14,
    }
    original = server.settings.get

    def _get(key):
        if key in defaults:
            return defaults[key]
        return original(key)

    monkeypatch.setattr(server.settings, "get", _get)
    return defaults


def test_capacity_report_without_samples_says_so_instead_of_predicting(
    client, capacity_settings
):
    """記録が無い段階で「あとX日」を出さないこと。volumeの行自体は出す
    (行が消えていると、予測不能なのか対象外なのかが区別できない)。"""
    body = client.get("/api/capacity").json()
    assert body["sampled_at"] is None
    assert body["samples"] == []
    assert body["forecasts"], "volumeの行は必ず出す"
    for name, forecast in body["forecasts"].items():
        assert forecast["status"] == "insufficient_data"
        assert "days_to_full" not in forecast


def test_capacity_sample_is_appended_and_kept_separate_from_storage_scan(
    client, server, capacity_settings
):
    """sampleは追記され、1行cacheのstorage_scanは触られないこと。"""
    server.storage.save_storage_scan({"total_bytes": 42, "total_files": 1}, 1.0)
    first = client.post("/api/capacity/sample").json()
    second = client.post("/api/capacity/sample").json()
    assert first["sampled_at"] <= second["sampled_at"]
    assert len(server.storage.list_capacity_samples()) == 2
    # 既存の1行cacheは無傷。
    assert server.storage.get_storage_scan()["usage"]["total_bytes"] == 42


def test_capacity_sample_records_sizes_without_scanning_the_record_tree(
    client, server, capacity_settings
):
    """snapshotはfilesystem走査を伴わない。drive空き・DB size・行数だけで構成される。"""
    body = client.post("/api/capacity/sample").json()
    now = body["report"]["now"]
    assert now["disk"]["volumes"]
    assert now["db_files"]["db"] > 0
    assert "bytes" in now["backups"]
    assert now["rows"]["sessions"] >= 0
    # 走査結果(storage_scan)は含めない。あれは分単位かかるもので日次には乗せない。
    assert "streamers" not in now


def test_capacity_forecast_appears_once_enough_samples_exist(
    client, server, capacity_settings
):
    """空きが減る記録を入れれば予測が幅で出ること。点推定だけを返さない。"""
    volumes = server._disk_report()["volumes"]
    name = sorted(volumes)[0]
    free_now = volumes[name]["free_bytes"]
    now = time.time()
    # 8日で尽きるペースを5日ぶん(観測4日)。外挿は2倍で既定の上限3倍に収まる。
    for i in range(5):
        server.storage.add_capacity_sample(
            {"disk": {"volumes": {name: {"free_bytes": free_now + (4 - i) * (free_now / 8),
                                         "total_bytes": volumes[name]["total_bytes"]}}}},
            sampled_at=now - (4 - i) * 86400,
        )
    forecast = client.get("/api/capacity").json()["forecasts"][name]
    assert forecast["status"] == "ok"
    assert forecast["days_low"] <= forecast["days_to_full"] <= forecast["days_high"]
    assert forecast["observed_days"] == pytest.approx(4.0, abs=0.1)


def test_capacity_alert_goes_through_ops_events_not_a_new_channel(
    client, server, capacity_settings, monkeypatch
):
    """閾値割れは ops_event として残る。通知経路を新設せず、既存のops observerに乗せる。"""
    volumes = server._disk_report()["volumes"]
    name = sorted(volumes)[0]
    free_now = volumes[name]["free_bytes"]
    now = time.time()
    # 5日で尽きるペース = 既定閾値(14日)を割る。
    for i in range(5):
        server.storage.add_capacity_sample(
            {"disk": {"volumes": {name: {"free_bytes": free_now + (4 - i) * (free_now / 5),
                                         "total_bytes": volumes[name]["total_bytes"]}}}},
            sampled_at=now - (4 - i) * 86400,
        )
    report = server._capacity_report()
    server._capacity_alert_check(report)

    events = server.storage.list_ops_events(limit=50)
    low = [e for e in events if e["kind"] == "capacity.forecast_low"]
    assert low, "閾値割れがops_eventとして残ること"
    assert low[0]["severity"] == "warning"
    assert low[0]["detail"]["volume"] == name


# ---- 最終保存先への退避 --------------------------------------------------------------

@pytest.fixture
def relocation_dirs(server, tmp_path, monkeypatch):
    """作業先と退避先を tmp へ振り替える。本番のrecordings配下には一切触れない。"""
    work = tmp_path / "work"
    final = tmp_path / "final"
    work.mkdir()
    final.mkdir()
    monkeypatch.setattr(server, "RECORD_DIR", work.resolve())
    monkeypatch.setattr(server, "FINAL_DIR", final.resolve())
    return work.resolve(), final.resolve()


def _make_relocatable(server, work, unique_id="alice", status="completed", size=2048,
                      with_timing=True):
    from tictok.core import layout
    from tictok.record.recorder import timing_path

    storage = server.storage
    session_id = storage.create_session(unique_id, 60)
    stem = f"00001_{unique_id}_{secrets.token_hex(4)}"
    path = layout.mp4_path(work, stem)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)
    if with_timing:
        tp = timing_path(path)
        tp.parent.mkdir(parents=True, exist_ok=True)
        tp.write_text('{"version": 2}', encoding="utf-8")
    started = time.time() - 600
    recording_id = storage.create_recording(
        session_id, unique_id, str(path), path.name, "hd", started)
    if status != "recording":
        storage.update_recording(recording_id, status, str(path), path.name,
                                 started + 300, size)
    return recording_id, path


def test_relocation_is_disabled_when_there_is_no_separate_final_dir(server, monkeypatch):
    """作業先と退避先が同じなら機能ごと出さない。移す先が無い。"""
    monkeypatch.setattr(server, "FINAL_DIR", server.RECORD_DIR)
    plan = server._relocation_plan()
    assert plan["enabled"] is False
    assert plan["items"] == []


def test_relocation_plan_lists_only_completed_files_that_exist(server, relocation_dirs):
    """対象は「完了 かつ 作業先 かつ 実体がある」もの。DBにpathがあるだけの行を件数に
    混ぜると「移せる」という嘘になる(実測で132本中82本が実体なし)。"""
    work, _final = relocation_dirs
    ok_id, _ = _make_relocatable(server, work)
    _make_relocatable(server, work, status="recording")
    ghost_id, ghost_path = _make_relocatable(server, work)
    ghost_path.unlink()

    plan = server._relocation_plan()
    assert [i["recording_id"] for i in plan["items"]] == [ok_id]
    assert plan["skipped_missing"] == 1
    assert plan["total_bytes"] == 2048
    assert plan["by_streamer"][0]["items"] == 1
    assert ghost_id not in [i["recording_id"] for i in plan["items"]]


def test_relocation_plan_uses_real_file_size_not_db_bytes(server, relocation_dirs):
    """容量は実fileのsizeで出す。実測で16本がDB値とずれていた。"""
    work, _final = relocation_dirs
    recording_id, path = _make_relocatable(server, work, size=4096)
    server.storage.update_recording(
        recording_id, "completed", str(path), path.name, time.time(), 999999)

    plan = server._relocation_plan()
    assert plan["items"][0]["bytes"] == 4096


def test_relocation_moves_the_pair_and_updates_the_db_path(server, relocation_dirs):
    """mp4とtiming sidecarが移り、DBのpathが退避先を指すこと。
    pathを更新しないと再生と出力が壊れる(serverはrecordings.pathをそのまま使う)。"""
    from pathlib import Path

    from tictok.record.recorder import timing_path

    work, final = relocation_dirs
    recording_id, src = _make_relocatable(server, work)
    src_timing = timing_path(src)
    assert src_timing.is_file()

    result = server._run_relocation(server._relocation_plan())

    assert (result["moved"], result["failures"]) == (1, [])
    assert not src.exists()
    assert not src_timing.exists()
    dst = Path(server.storage.get_recording(recording_id)["path"])
    assert dst.is_file()
    assert server._is_under(dst, final)
    assert timing_path(dst).is_file()


def test_relocation_without_a_timing_sidecar_still_moves_the_mp4(server, relocation_dirs):
    """sidecarが無い録画でも移せること(既存の_move_recording_filesの判断をそのまま使う)。"""
    from pathlib import Path

    work, final = relocation_dirs
    recording_id, _src = _make_relocatable(server, work, with_timing=False)
    result = server._run_relocation(server._relocation_plan())
    assert result["moved"] == 1
    assert server._is_under(Path(server.storage.get_recording(recording_id)["path"]), final)


def test_relocation_failure_keeps_the_file_and_the_db_path(server, relocation_dirs,
                                                           monkeypatch):
    """失敗したら作業先に残し、DBも更新しない。偽の最終位置を作らない既存の設計に揃える。"""
    work, _final = relocation_dirs
    recording_id, src = _make_relocatable(server, work)
    original_path = server.storage.get_recording(recording_id)["path"]

    def _boom(source, destination):
        raise OSError(32, "file is in use")

    monkeypatch.setattr(server.Recorder, "_move_recording_files", staticmethod(_boom))
    result = server._run_relocation(server._relocation_plan())

    assert result["moved"] == 0
    assert len(result["failures"]) == 1
    assert src.is_file(), "失敗時はfileを作業先に残す"
    assert server.storage.get_recording(recording_id)["path"] == original_path


def test_relocation_continues_past_a_single_failure(server, relocation_dirs, monkeypatch):
    """1本の失敗で残り全部を諦めない。取り残しを減らすという目的に反する。"""
    from pathlib import Path

    work, _final = relocation_dirs
    ids = [_make_relocatable(server, work)[0] for _ in range(3)]
    real_move = server.Recorder._move_recording_files
    calls = {"n": 0}

    def _flaky(source, destination):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(32, "file is in use")
        return real_move(source, destination)

    monkeypatch.setattr(server.Recorder, "_move_recording_files", staticmethod(_flaky))
    result = server._run_relocation(server._relocation_plan())

    assert result["moved"] == 2
    assert len(result["failures"]) == 1
    assert sum(1 for i in ids
               if server._is_under(Path(server.storage.get_recording(i)["path"]),
                                   server.FINAL_DIR)) == 2


def test_relocation_carries_every_derived_file_not_just_the_timing_map(
    server, relocation_dirs
):
    """mp4から派生する持続fileは全部一緒に移すこと。

    派生fileはmp4の現在地から解決されるため、mp4だけ移すと旧rootに取り残されて誰も
    見に行かなくなる:焼き込み済みの.overlay.mp4は画面から消え、.timing.jsonが欠けた
    録画は焼き込みが概算timingに落ちてコメントがズレ、.overlay.metaが欠ければcacheが
    当たらず全編を再encodeする。掃除もmp4基準なので残骸は永久に残る。"""
    from pathlib import Path

    from tictok.record.recorder import relocatable_artifact_paths

    work, final = relocation_dirs
    recording_id, src = _make_relocatable(server, work)
    derived = relocatable_artifact_paths(src)
    for path in derived:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    result = server._run_relocation(server._relocation_plan())

    assert (result["moved"], result["failures"]) == (1, [])
    dst = Path(server.storage.get_recording(recording_id)["path"])
    assert server._is_under(dst, final)
    assert not any(path.exists() for path in derived), "旧rootに派生fileが残っている"
    assert all(path.is_file() for path in relocatable_artifact_paths(dst))


def test_relocation_survives_a_derived_file_that_cannot_be_moved(
    server, relocation_dirs, monkeypatch
):
    """派生file1つが動かせなくてもmp4の移送は成立させる。mp4が動いた事実は取り消せず、
    ここで例外を上げると呼び出し側がDBを更新せず、pathが存在しないfileを指す。"""
    from pathlib import Path

    from tictok.record import recorder as recorder_module
    from tictok.record.recorder import relocatable_artifact_paths, timing_path

    work, final = relocation_dirs
    recording_id, src = _make_relocatable(server, work)
    stuck = timing_path(src)
    real_move = recorder_module.shutil.move

    def _move(source, destination):
        if Path(source) == stuck:
            raise OSError(32, "file is in use")
        return real_move(source, destination)

    monkeypatch.setattr(recorder_module.shutil, "move", _move)
    result = server._run_relocation(server._relocation_plan())

    assert (result["moved"], result["failures"]) == (1, [])
    dst = Path(server.storage.get_recording(recording_id)["path"])
    assert dst.is_file()
    assert server._is_under(dst, final)
    assert stuck.is_file(), "動かせなかったfileは旧rootに残る(消さない)"
    assert relocatable_artifact_paths(dst)


def test_relocation_skips_a_recording_that_started_again_before_execution(
    server, relocation_dirs
):
    """dry-runから実行までの間に状態が変わった録画は動かさない。
    書き込み中のfileを動かすことになる。"""
    work, _final = relocation_dirs
    recording_id, src = _make_relocatable(server, work)
    plan = server._relocation_plan()
    server.storage.update_recording(
        recording_id, "recording", str(src), src.name, None, 0)

    result = server._run_relocation(plan)
    assert result["moved"] == 0
    assert result["failures"][0]["reason"] == "状態が変わりました"
    assert src.is_file()


def test_relocation_does_not_overwrite_an_existing_destination(server, relocation_dirs):
    """退避先に同名があれば触らない。上書きすると既に退避済みの実体を壊す。"""
    from tictok.core import layout

    work, final = relocation_dirs
    _recording_id, src = _make_relocatable(server, work)
    dst = layout.mp4_path(final, src.stem)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(b"already here")

    plan = server._relocation_plan()
    assert plan["total_items"] == 0
    assert plan["skipped_existing_at_destination"] == 1
    assert src.is_file()
    assert dst.read_bytes() == b"already here"


def test_relocation_post_without_confirm_is_a_dry_run(client, server, relocation_dirs):
    """confirm無しではfileを動かさない。"""
    work, _final = relocation_dirs
    _recording_id, src = _make_relocatable(server, work)
    body = client.post("/api/storage/relocate", json={"confirm": False}).json()
    assert body["applied"] is False
    assert body["plan"]["total_items"] == 1
    assert src.is_file()


def test_capacity_report_carries_the_placement(server, relocation_dirs, capacity_settings):
    """動画容量画面に常時出す指標。これが出ていれば移動が呼ばれていない状態に気付ける。"""
    work, _final = relocation_dirs
    _make_relocatable(server, work, size=8192)
    placement = server._capacity_report()["placement"]
    assert placement["enabled"] is True
    assert placement["items"] == 1
    assert placement["bytes"] == 8192


def test_placement_counts_completed_recordings_on_both_sides(server, relocation_dirs):
    """所在の内訳は両方の保存先ぶん出す。一時保存先の取り残しだけでは「移し終えたのか、
    そもそも録画が無いのか」が読めない。"""
    work, final = relocation_dirs
    _make_relocatable(server, work, size=2048)
    _make_relocatable(server, final, unique_id="bob", size=4096)
    ghost_id, _ = _make_relocatable(server, final, unique_id="carol", size=8192)
    # bytes未記録の行(実測でも存在する)。0として足すと内訳が実態より小さく見える。
    server.storage.update_recording_bytes(ghost_id, 0)

    locations = server._relocation_summary()["locations"]
    assert locations["work"] == {"items": 1, "bytes": 2048, "unknown_bytes": 0}
    assert locations["final"]["items"] == 2
    assert locations["final"]["bytes"] == 4096
    assert locations["final"]["unknown_bytes"] == 1


def test_placement_is_reported_even_without_a_final_dir(server, monkeypatch, tmp_path):
    """最終保存先が未設定でも所在は出す。出さないと画面から機能ごと消え、「移動できない」
    ではなく「移動機能が無い」に見える。"""
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(server, "RECORD_DIR", work.resolve())
    monkeypatch.setattr(server, "FINAL_DIR", work.resolve())
    _make_relocatable(server, work.resolve(), size=1024)

    summary = server._relocation_summary()
    assert summary["enabled"] is False
    assert summary["items"] == 0
    assert summary["locations"]["work"]["items"] == 1


# ---- 配信者単位のfile削除 ---------------------------------------------------------


@pytest.fixture
def make_recording_with_ts(server):
    """mp4とHLS(.ts)の両方を持つ録画。容量整理はこの2つを別々に消せることが要件。

    stemは実際の命名(``NNNNN_<配信者>_YYYYMMDD_HHMMSS``)に揃える。HLSの解決はlayout規約に
    沿ったpathしか受け付けない(規約外のpathへrmtreeを効かせないため)ので、規約を外した
    stemで組むとTSが有るのに見えない状態をtestが再現できない。"""
    counter = itertools.count(1)

    def _make(unique_id="tester", status="completed", segments=2):
        from tictok.core import layout

        storage = server.storage
        session_id = storage.create_session(unique_id, 60)
        storage.update_session(session_id, "connected")
        n = next(counter)
        stem = f"{n:05d}_{unique_id}_20250101_{n:06d}"
        mp4_dir = layout.mp4_dir(server.RECORD_DIR, stem, unique_id)
        mp4_dir.mkdir(parents=True, exist_ok=True)
        path = mp4_dir / f"{stem}.mp4"
        path.write_bytes(b"\x00" * 64)
        seg_dir = layout.session_dir(server.RECORD_DIR, stem, unique_id)
        seg_dir.mkdir(parents=True, exist_ok=True)
        for i in range(segments):
            (seg_dir / f"seg{i:05d}.ts").write_bytes(b"\x01" * 128)
        started = time.time() - 600
        recording_id = storage.create_recording(
            session_id, unique_id, str(path), path.name, "hd", started)
        if status != "recording":
            storage.update_recording(
                recording_id, status, str(path), path.name, started + 300, 64)
        return session_id, recording_id, path, seg_dir

    return _make


def test_streamer_recordings_reports_mp4_and_ts_separately(client, make_recording_with_ts):
    _s, recording_id, _path, _seg = make_recording_with_ts()
    body = client.get("/api/streamers/tester/recordings").json()
    item = next(i for i in body["recordings"] if i["id"] == recording_id)
    assert item["mp4_exists"] is True
    assert item["mp4_bytes"] == 64
    assert item["ts_exists"] is True
    assert item["ts_bytes"] == 256
    # 合計はこの録画ぶんを必ず含む。storageはtest間で共有なので固定値では比べない。
    assert body["total_ts_bytes"] >= 256


def test_streamer_recordings_sizes_come_from_disk_not_the_db(client, make_srv_recording):
    """DBのbytesは録画完了時の値のまま残る。消えたfileを容量ありと報告してはならない。"""
    _s, recording_id, path = make_srv_recording()
    path.unlink()
    body = client.get("/api/streamers/tester/recordings").json()
    item = next(i for i in body["recordings"] if i["id"] == recording_id)
    assert item["mp4_exists"] is False
    assert item["mp4_bytes"] == 0


def test_deleting_ts_only_keeps_the_mp4(client, make_recording_with_ts):
    _s, recording_id, path, seg_dir = make_recording_with_ts()
    body = client.post("/api/streamers/tester/recordings/delete-files",
                       json={"mp4_ids": [], "ts_ids": [recording_id]}).json()
    assert body["freed_bytes"] == 256
    assert not seg_dir.exists()
    assert path.is_file()


def test_deleting_mp4_keeps_the_row_and_its_transcript(client, server, make_recording_with_ts):
    """行を消さないことがこの機能の要点。転写・検索indexはCASCADEで道連れになる。"""
    _s, recording_id, path, seg_dir = make_recording_with_ts()
    server.storage.save_transcript(
        recording_id, {"language": "ja", "text": "あ",
                       "segments": [{"start": 0.0, "end": 1.0, "text": "あ"}]})
    client.post("/api/streamers/tester/recordings/delete-files",
                json={"mp4_ids": [recording_id], "ts_ids": []})
    assert not path.exists()
    # mp4だけの指定なのでHLSは残る。
    assert seg_dir.is_dir()
    assert server.storage.get_recording(recording_id) is not None
    assert recording_id in server.storage.transcribed_recording_ids()


def test_deleting_mp4_also_removes_its_sprite_and_waveform_caches(client, server,
                                                                  make_srv_recording):
    """cacheはsrcのmtime+sizeで有効判定するため、srcを消しただけでは無効化されない。"""
    from tictok.media.thumbnails import thumbnail_artifact_paths
    from tictok.media.waveform import waveform_artifact_paths

    _s, recording_id, path = make_srv_recording()
    caches = [*thumbnail_artifact_paths(path), *waveform_artifact_paths(path)]
    caches[0].parent.mkdir(parents=True, exist_ok=True)
    for cache in caches:
        cache.write_bytes(b"\x02" * 32)
    client.post("/api/streamers/tester/recordings/delete-files",
                json={"mp4_ids": [recording_id], "ts_ids": []})
    assert [c for c in caches if c.exists()] == []


def test_deleting_mp4_also_removes_render_intermediates(client, server, make_srv_recording):
    """焼き込みの中間(.cfrbase.mp4等)は元動画級に大きい。srcを消して残すと容量が空かない。"""
    from tictok.record.video_overlay import overlay_transient_paths

    _s, recording_id, path = make_srv_recording()
    transients = list(overlay_transient_paths(path))
    assert transients
    transients[0].parent.mkdir(parents=True, exist_ok=True)
    for tmp in transients:
        tmp.write_bytes(b"\x03" * 1024)
    client.post("/api/streamers/tester/recordings/delete-files",
                json={"mp4_ids": [recording_id], "ts_ids": []})
    assert [t for t in transients if t.exists()] == []


def test_delete_files_refuses_a_recording_still_being_written(client, make_recording_with_ts):
    _s, recording_id, path, seg_dir = make_recording_with_ts(status="recording")
    response = client.post("/api/streamers/tester/recordings/delete-files",
                           json={"mp4_ids": [recording_id], "ts_ids": [recording_id]})
    assert response.status_code == 409
    assert path.is_file()
    assert seg_dir.is_dir()


def test_delete_files_refuses_a_recording_with_a_queued_job(client, server,
                                                            make_srv_recording):
    """焼き込み/転写はsrcを実行中に読む。消すと壊れたjobだけが残る。"""
    _s, recording_id, path = make_srv_recording()
    server.storage.enqueue_media_job("job-1", "overlay", recording_id)
    response = client.post("/api/streamers/tester/recordings/delete-files",
                           json={"mp4_ids": [recording_id], "ts_ids": []})
    assert response.status_code == 409
    assert path.is_file()


def test_delete_files_refuses_ids_belonging_to_another_streamer(client, make_srv_recording):
    """他人の録画idを混ぜて投げても、pathのstreamer側だけを見て触らない。"""
    _s, other_id, other_path = make_srv_recording(unique_id="someone")
    response = client.post("/api/streamers/tester/recordings/delete-files",
                           json={"mp4_ids": [other_id], "ts_ids": []})
    assert response.status_code == 404
    assert other_path.is_file()


def test_delete_files_rejects_an_empty_selection(client):
    response = client.post("/api/streamers/tester/recordings/delete-files",
                           json={"mp4_ids": [], "ts_ids": []})
    assert response.status_code == 400


def test_session_detail_marks_a_recording_whose_file_was_deleted(client, make_srv_recording):
    session_id, recording_id, path = make_srv_recording()
    assert client.get(f"/api/sessions/{session_id}").json()["recordings"][0]["file_exists"] is True
    path.unlink()
    body = client.get(f"/api/sessions/{session_id}").json()
    rec = next(r for r in body["recordings"] if r["id"] == recording_id)
    assert rec["file_exists"] is False


# ---- 音量正規化 (audionorm) -------------------------------------------------------

def _fake_audionorm_ffmpeg(monkeypatch, server, captured, *, returncode=0,
                           output=b"\x00" * 128):
    """ffmpegを差し替え、引数を捕まえつつ出力fileだけ作る。"""
    monkeypatch.setattr(server, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(server, "ffprobe_available", lambda: True)
    monkeypatch.setattr(server.audio_norm, "probe_sample_rate", lambda src: 48000)

    async def fake_duration(path):
        return 300.0

    monkeypatch.setattr(server, "_duration_seconds", fake_duration)

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = list(cmd)
        if returncode == 0:
            Path(cmd[-1]).write_bytes(output)

        async def read():
            return b""

        async def readline():
            # 進捗streamはすぐEOF。実際のffmpegは out_time_us= を吐くが、ここで見たいのは
            # 引数と差し替えの成否で、%の刻みは progress 側のtestが持つ。
            return b""

        async def wait():
            return returncode

        return types.SimpleNamespace(
            returncode=returncode,
            stdout=types.SimpleNamespace(readline=readline),
            stderr=types.SimpleNamespace(read=read), wait=wait, kill=lambda: None)

    monkeypatch.setattr(server.asyncio, "create_subprocess_exec", fake_exec)


async def _run_audionorm(server, recording_id, job_id="an-1"):
    async def report(stage, pct):
        return None

    recording = server.storage.get_recording(recording_id)
    return await server._audionorm_recording(recording_id, recording, job_id, report)


async def test_audionorm_copies_video_and_loudnorms_audio(server, monkeypatch,
                                                          make_srv_recording):
    """映像はstream copy。再encodeすると画質も、焼き込みが突き合わせるtimestampも動く。"""
    _s, recording_id, _path = make_srv_recording()
    captured = {}
    _fake_audionorm_ffmpeg(monkeypatch, server, captured)

    await _run_audionorm(server, recording_id)
    cmd = captured["cmd"]
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    filters = cmd[cmd.index("-af") + 1]
    assert filters.startswith("aresample=async=1,")
    assert "loudnorm=I=-14:TP=-1.5" in filters
    # loudnormは192kHzを出す。sourceの実rateへ戻さないと音声dataだけが倍に膨らむ。
    assert cmd[cmd.index("-ar") + 1] == "48000"
    # 2 passにしない(統合値は正確になるが、1本の中の落差はそのまま残る)。
    assert "measured_I" not in filters


async def test_audionorm_replaces_the_mp4_and_keeps_the_original(server, monkeypatch,
                                                                 make_srv_recording):
    _s, recording_id, path = make_srv_recording()
    _fake_audionorm_ffmpeg(monkeypatch, server, {}, output=b"\x01" * 128)

    result = await _run_audionorm(server, recording_id)
    assert path.read_bytes() == b"\x01" * 128
    assert result["bytes"] == 128
    # 元mp4は退避され、失われないこと。
    backup = Path(result["backup"])
    assert backup.is_file() and backup.read_bytes() == b"\x00" * 64
    # 差し替え後のsizeと「正規化済み」がDBへ載ること(一括画面の処理済判定はこれだけを見る)。
    row = server.storage.get_recording(recording_id)
    assert row["bytes"] == 128
    assert row["audio_normalized_at"] is not None
    assert row["audio_normalized_lufs"] == -14.0


async def test_audionorm_failure_leaves_the_recording_untouched(server, monkeypatch,
                                                                make_srv_recording):
    """失敗したときに元mp4を消していると、録画がfileの無い状態で残る。"""
    _s, recording_id, path = make_srv_recording()
    _fake_audionorm_ffmpeg(monkeypatch, server, {}, returncode=1)

    with pytest.raises(HTTPException) as excinfo:
        await _run_audionorm(server, recording_id)
    assert excinfo.value.status_code == 500
    assert path.read_bytes() == b"\x00" * 64
    assert server.storage.get_recording(recording_id)["audio_normalized_at"] is None
    # 書きかけのtempを残さないこと。
    assert not list(path.parent.glob("*.audionorm.tmp"))


def test_audionorm_endpoint_refuses_a_recording_without_a_file(client, server,
                                                               make_srv_recording):
    _s, recording_id, path = make_srv_recording()
    path.unlink()
    assert client.post(f"/api/recordings/{recording_id}/audionorm").status_code == 404


def test_audionorm_endpoint_refuses_a_recording_still_running(client, make_srv_recording):
    _s, recording_id, _path = make_srv_recording(status="recording")
    assert client.post(f"/api/recordings/{recording_id}/audionorm").status_code == 409


async def test_interrupted_audionorm_restores_the_backup(server, make_srv_recording):
    """差し替えの最中にprocessが死ぬと、録画はmp4の無い状態で残る。起動時に戻すこと。"""
    _s, recording_id, path = make_srv_recording()
    backup = path.parent / "backup.mp4"
    path.rename(backup)
    restored = await server._restore_reprocess_backup(
        {"result": {"backup_path": str(backup), "final_path": str(path)}})
    assert restored == str(path)
    assert path.is_file() and not backup.exists()


async def test_interrupted_reprocess_replaces_the_partial_mp4_with_the_backup(
        server, make_srv_recording, monkeypatch):
    """中断はほぼ必ず書きかけのmp4を残す。「最終mp4が在る」だけで復元を打ち切ると、録画は
    断片を指したまま・原本は_backupに置き去りになる(実測62分が12分の断片に置き換わった)。"""
    _s, _recording_id, path = make_srv_recording()
    backup = path.parent / "backup.mp4"
    path.rename(backup)
    path.write_bytes(b"\x00" * 32)          # 中断が残した断片

    async def unreadable(_path):
        return None                          # ffprobeが尺を読めない = 完成品ではない

    monkeypatch.setattr(server, "_duration_seconds", unreadable)
    restored = await server._restore_reprocess_backup(
        {"result": {"backup_path": str(backup), "final_path": str(path)}})

    assert restored == str(path)
    assert path.read_bytes() == b"\x00" * 64  # 断片ではなく原本(64byte)が戻っている
    assert not backup.exists()


async def test_completed_reprocess_keeps_its_backup(server, make_srv_recording, monkeypatch):
    """完走していれば最終mp4は完成品。その退避は正常な世代管理なので戻さない。"""
    _s, _recording_id, path = make_srv_recording()
    backup = path.parent / "backup.mp4"
    backup.write_bytes(b"\x00" * 16)

    async def readable(_path):
        return 1234.5

    monkeypatch.setattr(server, "_duration_seconds", readable)
    restored = await server._restore_reprocess_backup(
        {"result": {"backup_path": str(backup), "final_path": str(path)}})

    assert restored is None
    assert backup.is_file() and path.is_file()


async def test_audionorm_drains_the_progress_stream_without_a_duration(server, monkeypatch,
                                                                       make_srv_recording):
    """尺が測れなくてもstdoutは読み切ること。放置するとpipeが埋まった時点でffmpegが
    書き込みで止まり、jobが0%のまま永久に終わらない。"""
    _s, recording_id, _path = make_srv_recording()
    captured = {}
    _fake_audionorm_ffmpeg(monkeypatch, server, captured)

    async def no_duration(path):
        return None

    monkeypatch.setattr(server, "_duration_seconds", no_duration)
    result = await _run_audionorm(server, recording_id)
    assert result["normalized"] is True
