import itertools
import json
import os
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
    # context manager として使わないこと。lifespan が走ると監視復元と queue worker が
    # 立ち上がり、shutdown で storage が閉じられて後続 test が使えなくなる。
    return TestClient(server.app)


# stemの通し番号はmodule levelで持つ。fixtureの中に置くと関数scopeで毎testリセットされ、
# record rootを跨いで同じstemが再利用される(前testの素材を次testが自分のものとして拾う)。
_srv_stem_counter = itertools.count(1)


@pytest.fixture
def make_srv_recording(server):
    def _make(unique_id="tester", status="completed", file_exists=True, ts_segments=0):
        storage = server.runtime.storage
        session_id = storage.create_session(unique_id, 60)
        storage.update_session(session_id, "connected")
        counter = {"n": next(_srv_stem_counter)}
        # stemはlayoutの規約(<session>_<配信者>_<日付>_<時刻>)に合わせる。合わない名前だと
        # layout.streamer_of が None を返し、素材(.ts)を解決する経路が丸ごと素通りするため、
        # mp4しか無い状況しかtestできなくなる。
        stem = f"{counter['n']:05d}_{unique_id}_20260101_{counter['n']:06d}"
        directory = server.runtime.RECORD_DIR / unique_id / "mp4"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{stem}.mp4"
        if file_exists:
            path.write_bytes(b"\x00" * 64)
        # 素材だけが在る録画(=現行のfinalizeが残す形)。再生listまで置くのは、
        # _has_usable_media が素材と index.m3u8 の両方を要求するため。
        if ts_segments:
            session = server.layout.session_dir(server.runtime.RECORD_DIR, stem, unique_id)
            session.mkdir(parents=True, exist_ok=True)
            lines = ["#EXTM3U", "#EXT-X-TARGETDURATION:2"]
            for i in range(ts_segments):
                (session / f"seg{i:05d}.ts").write_bytes(b"\x47" * 188)
                lines += ["#EXTINF:2.000000,", f"seg{i:05d}.ts"]
            lines.append("#EXT-X-ENDLIST")
            (session / "index.m3u8").write_text("\n".join(lines), encoding="utf-8")
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
    inside = server.runtime.RECORD_DIR / "tester" / "mp4" / "a.mp4"
    assert server.files._safe_recording_path(str(inside)) == inside.resolve()


def test_safe_recording_path_rejects_sibling_of_record_root(server):
    outside = server.runtime.RECORD_DIR.parent / "escaped.mp4"
    with pytest.raises(HTTPException) as excinfo:
        server.files._safe_recording_path(str(outside))
    assert excinfo.value.status_code == 400


def test_safe_recording_path_rejects_traversal_that_climbs_out(server):
    traversal = server.runtime.RECORD_DIR / ".." / ".." / "windows" / "system32" / "x.mp4"
    with pytest.raises(HTTPException) as excinfo:
        server.files._safe_recording_path(str(traversal))
    assert excinfo.value.status_code == 400


def test_safe_recording_path_allows_traversal_that_stays_inside(server):
    # 正規化後に root 配下へ戻るなら通す。文字列一致ではなく resolve 後で判定していること。
    weird = server.runtime.RECORD_DIR / "tester" / ".." / "tester" / "mp4" / "a.mp4"
    resolved = server.files._safe_recording_path(str(weird))
    assert resolved == (server.runtime.RECORD_DIR / "tester" / "mp4" / "a.mp4").resolve()


# ---- unique_id の正規化 -----------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("@tester", "tester"),
    ("  @tester  ", "tester"),
    ("@@tester", "tester"),
    ("a.b_c", "a.b_c"),
    ("A" * 64, "A" * 64),
])
def test_normalize_unique_id_accepts(server, raw, expected):
    assert server.runtime._normalize_unique_id(raw) == expected


@pytest.mark.parametrize("raw", ["", "@", "has space", "日本語", "a/b", "A" * 65, "a-b"])
def test_normalize_unique_id_rejects(server, raw):
    with pytest.raises(HTTPException) as excinfo:
        server.runtime._normalize_unique_id(raw)
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
    server.runtime.storage.set_recording_duration(recording_id, 123.0)

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


# 「この録画を観たか」は一覧からしか分からない。印が既定値を名乗らないと、画面はどの
# 状態にも寄せられない。
def test_browse_recordings_reports_the_review_state(client, make_srv_recording):
    _, recording_id, _ = make_srv_recording()
    body = client.get("/api/recordings/browse").json()
    rec = next(r for r in body["recordings"] if r["recording_id"] == recording_id)
    assert rec["review_state"] == "unchecked"
    assert rec["review_updated_at"] is None


def test_patch_recording_review_round_trips_to_the_browse_list(client, make_srv_recording):
    _, recording_id, _ = make_srv_recording()
    response = client.patch(f"/api/recordings/{recording_id}/review", json={"state": "checking"})
    assert response.status_code == 200
    assert response.json()["review_state"] == "checking"

    body = client.get("/api/recordings/browse").json()
    rec = next(r for r in body["recordings"] if r["recording_id"] == recording_id)
    assert rec["review_state"] == "checking"
    assert rec["review_updated_at"] > 0


def test_recording_path_reports_the_review_state(client, make_srv_recording):
    """検索hit経由で開いた録画は一覧の値を持たない。再生画面の印はここから出る。"""
    _, recording_id, _ = make_srv_recording()
    client.patch(f"/api/recordings/{recording_id}/review", json={"state": "checked"})
    body = client.get(f"/api/recordings/{recording_id}/path").json()
    assert body["review_state"] == "checked"


def test_patch_recording_review_rejects_an_unknown_state(client, make_srv_recording):
    _, recording_id, _ = make_srv_recording()
    response = client.patch(f"/api/recordings/{recording_id}/review", json={"state": "done"})
    assert response.status_code == 400
    assert client.get(f"/api/recordings/{recording_id}/path").json()["review_state"] == "unchecked"


def test_patch_recording_review_404_for_unknown_recording(client):
    response = client.patch("/api/recordings/99999999/review", json={"state": "checked"})
    assert response.status_code == 404


def test_patch_session_note_round_trips(client, make_srv_recording):
    session_id, _, _ = make_srv_recording()
    assert client.patch(f"/api/sessions/{session_id}", json={"note": "メモ"}).status_code == 200
    assert client.get(f"/api/sessions/{session_id}").json()["session"]["note"] == "メモ"


def test_patch_session_note_rejects_over_10000_chars(client, make_srv_recording):
    session_id, _, _ = make_srv_recording()
    response = client.patch(f"/api/sessions/{session_id}", json={"note": "x" * 10001})
    assert response.status_code == 422


def test_delete_session_keeps_the_mp4_when_there_is_no_ts(client, server, make_srv_recording):
    """素材を持たない録画のmp4は原本なので、session削除では消さない。

    旧実装は無条件に消しており、旧録画flow由来の(=.tsが無い)録画をsessionごと消すと
    復元不能になっていた。実DBに該当する録画が16本残っている。"""
    session_id, recording_id, path = make_srv_recording(ts_segments=0)
    assert path.is_file()
    body = client.delete(f"/api/sessions/{session_id}").json()
    assert body["deleted"] == session_id
    assert body["recordings"] == {"kept_source_mp4": 1}
    assert path.is_file()
    assert server.runtime.storage.get_recording(recording_id) is not None
    assert client.get(f"/api/sessions/{session_id}").status_code == 404


def test_delete_session_removes_the_mp4_when_the_ts_survives(client, server, make_srv_recording):
    """素材が在る録画のmp4は素材から作り直せるので消してよい。行は残す(録画は使える)。"""
    session_id, recording_id, path = make_srv_recording(ts_segments=2)
    session_dir = server.layout.session_dir(server.runtime.RECORD_DIR, path.stem, "tester")
    assert path.is_file() and session_dir.is_dir()
    body = client.delete(f"/api/sessions/{session_id}").json()
    assert body["recordings"] == {"kept_ts": 1}
    assert not path.exists()
    assert session_dir.is_dir(), "素材はuserが明示的に捨てると決めたときだけ消す"
    assert server.runtime.storage.get_recording(recording_id) is not None


def test_delete_session_drops_the_row_when_nothing_remains(client, server, make_srv_recording):
    """実体を持たない録画行は指す先が無いので落とす。"""
    session_id, recording_id, path = make_srv_recording(file_exists=False, ts_segments=0)
    assert not path.exists()
    body = client.delete(f"/api/sessions/{session_id}").json()
    assert body["recordings"] == {"removed_row": 1}
    assert server.runtime.storage.get_recording(recording_id) is None


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
    assert body["severities"] == list(server.routes.system.OPS_SEVERITIES)


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

    storage = server.runtime.storage
    log = logging.getLogger("tictok.test")
    for severity in server.routes.system.OPS_SEVERITIES:
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

    server.runtime.storage.record_ops_event(logging.getLogger("tictok.test"),
                                    "test.info", "候補用の記録", unique_id="cand_streamer")
    body = client.get("/api/ops/kinds").json()
    assert "cand_streamer" in {e["unique_id"] for e in body["unique_ids"]}
    assert all(e["count"] >= 1 for e in body["unique_ids"])


def test_ops_summary_reports_every_severity_bucket(client, server):
    body = client.get("/api/ops/summary", params={"hours": 1}).json()
    assert body["window_hours"] == 1.0
    assert set(body["counts"]) == set(server.routes.system.OPS_SEVERITIES)
    assert all(isinstance(v, int) for v in body["counts"].values())


# ---- settings ---------------------------------------------------------------------

def test_settings_update_rejects_unknown_key(client):
    response = client.put("/api/settings", json={"no_such_setting": 1})
    assert response.status_code == 422
    assert "不明な設定key" in response.json()["detail"]


def test_settings_update_rejects_non_integer_for_int_setting(client, server):
    # int(10.9)=10 の黙った切り捨てを拒否する、という設計の回帰 test。
    before = server.runtime.settings.get("session_list_limit")
    response = client.put("/api/settings", json={"session_list_limit": 10.9})
    assert response.status_code == 422
    assert server.runtime.settings.get("session_list_limit") == before


def test_settings_update_rejects_out_of_range_value(client, server):
    before = server.runtime.settings.get("session_list_limit")
    response = client.put("/api/settings", json={"session_list_limit": -1})
    assert response.status_code == 422
    assert server.runtime.settings.get("session_list_limit") == before


def test_settings_update_round_trips_valid_value(client, server):
    before = server.runtime.settings.get("session_list_limit")
    try:
        response = client.put("/api/settings", json={"session_list_limit": 123})
        assert response.status_code == 200
        # values は差分ではなく更新後の全設定 snapshot。
        assert response.json()["values"]["session_list_limit"] == 123
        described = {row["key"]: row["value"] for row in client.get("/api/settings").json()["settings"]}
        assert described["session_list_limit"] == 123
    finally:
        server.runtime.settings.update({"session_list_limit": before})


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


def test_locate_404s_for_an_unknown_recording(client):
    response = client.get("/api/recordings/99999999/locate", params={"at": 1.0})
    assert response.status_code == 404


def test_locate_maps_wall_clock_onto_the_recording_time_axis(client, make_srv_recording,
                                                             server):
    """Battle履歴からその対戦の場面へ飛ぶための変換。壁時計との差(起動latency・再接続の
    穴)は録画の時刻anchorでしか解けないので、生の引き算になっていないことを見る。"""
    from tictok.record.recorder import timing_path

    _, recording_id, path = make_srv_recording()
    started = server.runtime.storage.get_recording(recording_id)["started_at"]
    timing = timing_path(path)
    timing.parent.mkdir(parents=True, exist_ok=True)
    # 録画開始から30秒遅れて映像が始まった録画。壁時計+120秒は動画の90秒地点。
    timing.write_text(
        json.dumps({"anchors": [[started + 30, 0.0], [started + 630, 600.0]]}),
        encoding="utf-8",
    )
    body = client.get(f"/api/recordings/{recording_id}/locate",
                      params={"at": started + 120}).json()
    assert body["video_time"] == pytest.approx(90.0, abs=0.1)


def test_locate_clamps_a_time_before_the_video_starts_to_the_head(
        client, make_srv_recording, server):
    """録画の頭より前の時刻は0へ。負の秒でseekすると再生が始まらない。"""
    _, recording_id, _ = make_srv_recording()
    started = server.runtime.storage.get_recording(recording_id)["started_at"]
    body = client.get(f"/api/recordings/{recording_id}/locate",
                      params={"at": started - 60}).json()
    assert body["video_time"] == 0.0


# ---- 確定録画のHLS再生 --------------------------------------------------------------


# 録画は ``hlsplay`` 名義で作る。make_recording_with_ts の連番は test ごとに振り直され、
# storage と record dir は test 間で共有されるため、``tester`` のまま使うと同じ session dir へ
# playlist を足すことになり、容量を数える側の test が別の test の書き足しを数えてしまう。
def _write_playlist(seg_dir, *, terminated: bool) -> None:
    lines = ["#EXTM3U", "#EXT-X-VERSION:6", "#EXT-X-TARGETDURATION:4",
             "#EXTINF:2.000000,", "seg00000.ts", "#EXTINF:2.000000,", "seg00001.ts"]
    if terminated:
        lines.append("#EXT-X-ENDLIST")
    (seg_dir / "index.m3u8").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_playback_picks_hls_when_the_ts_are_still_there(client, make_recording_with_ts):
    _s, recording_id, _path, seg_dir = make_recording_with_ts(unique_id="hlsplay")
    _write_playlist(seg_dir, terminated=True)
    body = client.get(f"/api/recordings/{recording_id}/playback").json()
    assert body["mode"] == "hls"
    assert body["url"] == f"/api/recordings/{recording_id}/hls/index.m3u8"


def test_playback_picks_mp4_when_the_ts_are_gone(client, make_srv_recording):
    """mp4しか残っていない録画はmp4で再生する。経路は録画ごとの素材の在り方で決まる。"""
    _s, recording_id, _path = make_srv_recording()
    body = client.get(f"/api/recordings/{recording_id}/playback").json()
    assert body["mode"] == "mp4"
    assert body["url"] == f"/api/recordings/{recording_id}/play"


def test_playback_picks_mp4_for_output_variants(client, make_recording_with_ts):
    """焼き込み・Up出力はmp4としてしか存在しない。素材が残っていてもHLSへは寄せない。"""
    _s, recording_id, _path, seg_dir = make_recording_with_ts(unique_id="hlsplay")
    _write_playlist(seg_dir, terminated=True)
    body = client.get(f"/api/recordings/{recording_id}/playback",
                      params={"variant": "overlay"}).json()
    assert body["mode"] == "mp4"
    assert body["url"] == f"/api/recordings/{recording_id}/play?variant=overlay"


def test_playback_rejects_an_unknown_variant(client, make_srv_recording):
    _s, recording_id, _path = make_srv_recording()
    response = client.get(f"/api/recordings/{recording_id}/playback",
                          params={"variant": "hdr"})
    assert response.status_code == 400


def test_playback_404s_for_an_unknown_recording(client):
    assert client.get("/api/recordings/99999999/playback").status_code == 404


def test_hls_playlist_is_terminated_for_a_finished_recording(client, make_recording_with_ts):
    """停止時のffmpegは強制終了でcapture indexに#EXT-X-ENDLISTが付かない。そのまま返すと
    hls.jsがlive streamと見なし、末尾から再生を始めて頭へseekできない。"""
    _s, recording_id, _path, seg_dir = make_recording_with_ts(unique_id="hlsplay")
    _write_playlist(seg_dir, terminated=False)
    response = client.get(f"/api/recordings/{recording_id}/hls/index.m3u8")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.apple.mpegurl")
    assert response.text.rstrip().endswith("#EXT-X-ENDLIST")
    assert response.text.count("#EXT-X-ENDLIST") == 1


def test_hls_playlist_leaves_an_already_terminated_playlist_alone(
        client, make_recording_with_ts):
    """束ね済み(hls_pack)のplaylistは既にVODとして終端している。二重に足さない。"""
    _s, recording_id, _path, seg_dir = make_recording_with_ts(unique_id="hlsplay")
    _write_playlist(seg_dir, terminated=True)
    response = client.get(f"/api/recordings/{recording_id}/hls/index.m3u8")
    assert response.text.count("#EXT-X-ENDLIST") == 1


def test_hls_serves_a_segment_as_mp2t(client, make_recording_with_ts):
    _s, recording_id, _path, seg_dir = make_recording_with_ts(unique_id="hlsplay")
    _write_playlist(seg_dir, terminated=True)
    response = client.get(f"/api/recordings/{recording_id}/hls/seg00000.ts")
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp2t"
    assert response.content == b"\x01" * 128


def test_hls_serves_a_byte_range_of_a_packed_segment(client, make_recording_with_ts):
    """束ね済み録画のplaylistは#EXT-X-BYTERANGEで1本のfileの中を指す。範囲取得が効かないと
    再生できない。"""
    _s, recording_id, _path, seg_dir = make_recording_with_ts(unique_id="hlsplay")
    _write_playlist(seg_dir, terminated=True)
    (seg_dir / "pack00000.ts").write_bytes(bytes(range(64)))
    response = client.get(f"/api/recordings/{recording_id}/hls/pack00000.ts",
                          headers={"Range": "bytes=8-15"})
    assert response.status_code == 206
    assert response.content == bytes(range(8, 16))


def test_hls_404s_when_the_recording_has_no_ts(client, make_srv_recording):
    _s, recording_id, _path = make_srv_recording()
    response = client.get(f"/api/recordings/{recording_id}/hls/index.m3u8")
    assert response.status_code == 404
    assert ".ts" in response.json()["detail"]


def test_hls_refuses_files_that_are_not_playlist_or_segment(client, make_recording_with_ts):
    """session dirにはffmpegのlogやpack snapshotも同居する。再生に要るものだけを出す。"""
    _s, recording_id, _path, seg_dir = make_recording_with_ts(unique_id="hlsplay")
    _write_playlist(seg_dir, terminated=True)
    (seg_dir / "pack.json").write_text("{}", encoding="utf-8")
    assert client.get(f"/api/recordings/{recording_id}/hls/pack.json").status_code == 404


def test_hls_member_refuses_names_that_climb_out_of_the_session_dir(server, tmp_path):
    outside = tmp_path / "secret.ts"
    outside.write_bytes(b"x")
    seg_dir = tmp_path / "ts" / "00001_tester_20250101_000001"
    seg_dir.mkdir(parents=True)
    (seg_dir / "seg00000.ts").write_bytes(b"x")
    assert server.files._hls_member(seg_dir, "seg00000.ts") is not None
    for name in ("../secret.ts", "..\\secret.ts", "sub/seg00000.ts", "index.m3u8.bak"):
        assert server.files._hls_member(seg_dir, name) is None


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
    storage = server.runtime.storage
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
    assert body["min_free_bytes"] == int(server.runtime.settings.get("disk_min_free_gb")) * 1024 ** 3


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
        server.media_jobs._session_output_targets(session_id)
    assert excinfo.value.status_code == 409
    # 断る条件は「素材もmp4も無い」であって、mp4の有無ではない(素材から出力できる録画を
    # 断ると、単体では焼けるのにsession一括だけが通らなくなる)。
    assert "素材もmp4も" in excinfo.value.detail

    assert [r["id"] for r in server.media_jobs._session_output_targets(ok_session)] == [ok_recording]


def test_session_output_targets_accept_a_recording_that_only_has_ts(
        server, make_srv_recording):
    """finalizeはmp4を作らない。素材だけの録画をsession一括が断ると、単体の焼き込みは
    通るのに配信者のsession全部が「録画fileが残っていません」になる。"""
    session_id, recording_id, path = make_srv_recording(
        status="completed", file_exists=False, ts_segments=3)

    assert not path.is_file()
    assert [r["id"] for r in server.media_jobs._session_output_targets(session_id)] == [recording_id]


def test_session_output_targets_reject_a_row_pointing_at_a_directory(
        server, make_srv_recording):
    """finalizeがDB更新前に落ちた行のpathは録画dirのまま。file扱いしてはいけない。"""
    session_id, recording_id, _ = make_srv_recording(status="interrupted")
    server.runtime.storage.update_recording(
        recording_id, "interrupted", str(server.runtime.RECORD_DIR), "x.mp4", None, 0)

    with pytest.raises(HTTPException) as excinfo:
        server.media_jobs._session_output_targets(session_id)
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
        await server.media_jobs._run_media_job(job, report)


async def test_media_job_waits_while_the_recording_is_being_finalized(
        server, make_srv_recording):
    """確定処理中の録画を掴むjobは、失敗ではなく保留にして待たせる。

    確定は最後にsession dirごと最終保存先へ移すので、その最中に素材を読み書きすると
    jobも移送も壊れる。確定は分単位で終わるため、待てば必ず解ける。"""
    from tictok.record.media_queue import JobDeferred
    from tictok.record.recorder import finalizing_scope

    _, recording_id, _ = make_srv_recording(status="completed")

    async def report(stage, pct):
        return None

    job = {"kind": "pack", "recording_id": recording_id, "job_id": "test0002"}
    with finalizing_scope(recording_id):
        with pytest.raises(JobDeferred) as excinfo:
            await server.media_jobs._media_job_runner(job, report)
    assert "確定処理中" in excinfo.value.reason


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

        async def finalize_recovered_hls(self, base, progress=None, mp4_root=None,
                                         build_mp4=False):
            # 再mp4化はmp4を作らせる側なので、明示的に要求されていなければ実装の誤り。
            # 既定のfinalizeはmp4を作らなくなったため、この引数が落ちると「操作が成功
            # したのにfileが無い」で終わる。
            assert build_mp4 is True
            seen["build_mp4"] = build_mp4
            out = layout.mp4_path(mp4_root or Path(seen["args"][1]), base)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"\x00" * 128)
            self.output_path = out
            self.state = "completed"

        def snapshot(self):
            return {"bytes": 128}

    monkeypatch.setattr(server.media_jobs, "Recorder", _StubRecorder)
    monkeypatch.setattr(server.media_jobs, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(server.media_jobs, "ffprobe_available", lambda: True)
    return seen


def _split_record_roots(server, monkeypatch, final_dir: Path):
    """1次(work)と2次(final)が別dirの構成へ差し替える。既定のtest環境は両者が同一で、
    root跨ぎの判定が一切効かない。"""
    final_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server.runtime, "FINAL_DIR", final_dir)
    monkeypatch.setattr(server.runtime, "_RECORD_ROOTS", [server.runtime.RECORD_DIR, final_dir])


async def test_reprocess_reports_completion_after_updating_the_recording(
        server, make_srv_recording, monkeypatch):
    """成功の末尾(100%通知)まで通す。ここが例外になると、実処理が全部終わった後に
    jobがfailedへ倒れ、queueが同じ録画をもう一度まるごと再実行する。"""
    from tictok.core import layout

    _, recording_id, path = make_srv_recording(status="completed")
    stem = path.stem
    monkeypatch.setattr(server.files, "_find_hls_root", lambda _stem: server.runtime.RECORD_DIR)
    _stub_reprocess_recorder(server, monkeypatch)

    stages = []

    async def report(stage, pct):
        stages.append((stage, pct))

    recording = server.runtime.storage.get_recording(recording_id)
    result = await server.media_jobs._reprocess_recording(recording_id, recording, "test0003", report)

    assert result["recording_id"] == recording_id
    assert stages[-1][1] == 100
    assert server.runtime.storage.get_recording(recording_id)["path"] == str(
        layout.mp4_path(server.runtime.RECORD_DIR, stem))


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
    server.runtime.storage.update_recording(recording_id, "completed", str(moved), moved.name,
                                    time.time(), moved.stat().st_size, None)
    monkeypatch.setattr(server.files, "_find_hls_root", lambda _stem: server.runtime.RECORD_DIR)
    seen = _stub_reprocess_recorder(server, monkeypatch)

    async def report(stage, pct):
        return None

    recording = server.runtime.storage.get_recording(recording_id)
    result = await server.media_jobs._reprocess_recording(recording_id, recording, "test0004", report)

    assert result["output_path"] == str(layout.mp4_path(final_dir, stem))
    assert result["backup"] == str(final_dir / "_backup" / f"{stem}.mp4")
    assert server.runtime.storage.get_recording(recording_id)["path"] == str(
        layout.mp4_path(final_dir, stem))
    # 1次にはこの録画の新しいmp4も退避も残さない。
    assert not layout.mp4_path(server.runtime.RECORD_DIR, stem).exists()
    assert not (server.runtime.RECORD_DIR / "_backup" / f"{stem}.mp4").exists()
    # 読む先は.tsのroot、書く先はmp4のroot。
    assert seen["args"][1] == str(server.runtime.RECORD_DIR)
    assert seen["kwargs"]["final_dir"] == str(final_dir)


async def test_reprocess_keeps_a_working_dir_recording_in_the_working_dir(
        server, make_srv_recording, monkeypatch, tmp_path):
    """1次に在る録画は1次のまま。2次が設定済みでも勝手に移送しない(移送は動画容量画面の
    手動操作だけの仕事で、再mp4化は置き場を変えない)。"""
    from tictok.core import layout

    final_dir = tmp_path / "final"
    _split_record_roots(server, monkeypatch, final_dir)
    _, recording_id, path = make_srv_recording(status="completed")
    stem = path.stem
    monkeypatch.setattr(server.files, "_find_hls_root", lambda _stem: server.runtime.RECORD_DIR)
    _stub_reprocess_recorder(server, monkeypatch)

    async def report(stage, pct):
        return None

    recording = server.runtime.storage.get_recording(recording_id)
    result = await server.media_jobs._reprocess_recording(recording_id, recording, "test0005", report)

    assert result["output_path"] == str(layout.mp4_path(server.runtime.RECORD_DIR, stem))
    assert result["backup"] == str(server.runtime.RECORD_DIR / "_backup" / f"{stem}.mp4")
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

    recording = server.runtime.storage.get_recording(recording_id)
    # 行は1次のpathを指したまま = そこが住所。
    assert server.media_jobs._recording_home_root(recording, stem) == server.runtime.RECORD_DIR

    server.runtime.storage.update_recording(recording_id, "completed", "", "", None, 0, None)
    assert server.media_jobs._recording_home_root(
        server.runtime.storage.get_recording(recording_id), stem) == final_dir


async def test_retry_of_a_group_requeues_only_its_failed_members(
        server, make_srv_recording, client):
    """一括の失敗ぶんを1clickで続きから流す。完了済みを巻き込むとGPU時間を捨てる。"""
    _s, ok_id, _p = make_srv_recording()
    _s2, ng_id, _p2 = make_srv_recording()
    await server.media_jobs.media_job_queue.enqueue("grp-ok", "reprocess", ok_id, group_id="grp")
    await server.media_jobs.media_job_queue.enqueue("grp-ng", "reprocess", ng_id, group_id="grp")
    server.runtime.storage.finish_media_job("grp-ok", "completed")
    server.runtime.storage.finish_media_job("grp-ng", "failed", error="保存先が見つかりません")

    body = client.post("/api/jobs/grp/retry").json()

    assert body["requeued"] == 1
    assert server.runtime.storage.get_media_job("grp-ng")["state"] == "pending"
    assert server.runtime.storage.get_media_job("grp-ng")["error"] is None
    assert server.runtime.storage.get_media_job("grp-ok")["state"] == "completed"
    # 母数を増やさない: 増やすとgroupは何度やり直しても完了に到達しない。
    assert len(server.runtime.storage.media_jobs_in_group("grp")) == 2


async def test_retry_of_a_group_without_failures_is_refused(
        server, make_srv_recording, client):
    _s, ok_id, _p = make_srv_recording()
    await server.media_jobs.media_job_queue.enqueue("g2-a", "reprocess", ok_id, group_id="grp2")
    server.runtime.storage.finish_media_job("g2-a", "completed")

    response = client.post("/api/jobs/grp2/retry")
    assert response.status_code == 409


async def test_media_job_runner_defers_instead_of_failing_when_a_root_is_gone(
        server, make_srv_recording, monkeypatch, tmp_path):
    """保存先が消えている間の失敗はどれも二次症状。失敗として残すと一括の中に原因不明の
    欠落が散らばり、復帰しても誰も拾い直さない。"""
    from tictok.record.media_queue import JobDeferred

    _s, recording_id, _p = make_srv_recording()
    monkeypatch.setattr(server.runtime, "_RECORD_ROOTS", [server.runtime.RECORD_DIR, tmp_path / "gone"])

    async def report(stage, pct):
        return None

    job = {"kind": "reprocess", "recording_id": recording_id, "job_id": "test0006"}
    with pytest.raises(JobDeferred) as excinfo:
        await server.media_jobs._media_job_runner(job, report)
    assert "保存先が見つかりません" in str(excinfo.value)


async def test_media_job_runner_defers_when_a_root_disappears_mid_run(
        server, make_srv_recording, monkeypatch, tmp_path):
    from tictok.record.media_queue import JobDeferred

    _s, recording_id, _p = make_srv_recording()
    gone = tmp_path / "gone"

    async def boom(_job, _report):
        # 実行中にvolumeが落ちた状況: ffmpegは意味の分からない終了コードで死ぬ。
        monkeypatch.setattr(server.runtime, "_RECORD_ROOTS", [server.runtime.RECORD_DIR, gone])
        raise OSError("ffmpeg exited -22")

    monkeypatch.setattr(server.media_jobs, "_run_media_job", boom)

    async def report(stage, pct):
        return None

    with pytest.raises(JobDeferred):
        await server.media_jobs._media_job_runner(
            {"kind": "reprocess", "recording_id": recording_id, "job_id": "test0007"}, report)


async def test_media_job_skips_when_the_recording_row_is_gone(server):
    from tictok.record.media_queue import JobSkipped

    async def report(stage, pct):
        return None

    job = {"kind": "reprocess", "recording_id": 999999, "job_id": "test0002"}
    with pytest.raises(JobSkipped):
        await server.media_jobs._run_media_job(job, report)


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

    server.runtime.manager._collectors["idle_user"] = _Collector()
    try:
        response = client.post("/api/monitors/idle_user/bookmark", json={"memo": ""})
    finally:
        server.runtime.manager._collectors.pop("idle_user", None)
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

    server.runtime.manager._collectors["live_user"] = _Collector()
    try:
        created = client.post("/api/monitors/live_user/bookmark",
                              json={"memo": "ここ"}).json()
    finally:
        server.runtime.manager._collectors.pop("live_user", None)

    assert created["pts_mapped"] == 0
    assert created["memo"] == "ここ"
    assert created["live_wall"] == pytest.approx(time.time(), abs=10)
    # 暫定startは録画開始からの経過秒。確定値ではない。
    assert created["start"] == pytest.approx(120, abs=10)
    assert server.runtime.storage.list_unmapped_bookmarks(recording_id)[0]["id"] == created["id"]


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
    original = server.runtime.settings.get

    def _get(key):
        if key in defaults:
            return defaults[key]
        return original(key)

    monkeypatch.setattr(server.runtime.settings, "get", _get)
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
    server.runtime.storage.save_storage_scan({"total_bytes": 42, "total_files": 1}, 1.0)
    first = client.post("/api/capacity/sample").json()
    second = client.post("/api/capacity/sample").json()
    assert first["sampled_at"] <= second["sampled_at"]
    assert len(server.runtime.storage.list_capacity_samples()) == 2
    # 既存の1行cacheは無傷。
    assert server.runtime.storage.get_storage_scan()["usage"]["total_bytes"] == 42


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
    volumes = server.disk._disk_report()["volumes"]
    name = sorted(volumes)[0]
    free_now = volumes[name]["free_bytes"]
    now = time.time()
    # 8日で尽きるペースを5日ぶん(観測4日)。外挿は2倍で既定の上限3倍に収まる。
    for i in range(5):
        server.runtime.storage.add_capacity_sample(
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
    volumes = server.disk._disk_report()["volumes"]
    name = sorted(volumes)[0]
    free_now = volumes[name]["free_bytes"]
    now = time.time()
    # 5日で尽きるペース = 既定閾値(14日)を割る。
    for i in range(5):
        server.runtime.storage.add_capacity_sample(
            {"disk": {"volumes": {name: {"free_bytes": free_now + (4 - i) * (free_now / 5),
                                         "total_bytes": volumes[name]["total_bytes"]}}}},
            sampled_at=now - (4 - i) * 86400,
        )
    report = server.disk._capacity_report()
    server.disk._capacity_alert_check(report)

    events = server.runtime.storage.list_ops_events(limit=50)
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
    monkeypatch.setattr(server.runtime, "RECORD_DIR", work.resolve())
    monkeypatch.setattr(server.runtime, "FINAL_DIR", final.resolve())
    return work.resolve(), final.resolve()


def _make_relocatable(server, work, unique_id="alice", status="completed", size=2048,
                      with_timing=True, with_mp4=True, segments=0):
    from tictok.core import layout
    from tictok.record.recorder import timing_path

    storage = server.runtime.storage
    session_id = storage.create_session(unique_id, 60)
    stem = f"00001_{unique_id}_{secrets.token_hex(4)}"
    path = layout.mp4_path(work, stem)
    path.parent.mkdir(parents=True, exist_ok=True)
    if with_mp4:
        path.write_bytes(b"\x00" * size)
    if segments:
        # 素材だけの録画(finalizeはmp4を作らない)。再生listまで揃えないと「使える素材」に
        # ならない(_has_usable_media)。
        seg_dir = layout.session_dir(work, stem)
        seg_dir.mkdir(parents=True, exist_ok=True)
        for i in range(segments):
            (seg_dir / f"seg{i:05d}.ts").write_bytes(b"\x47" * 188)
        (seg_dir / "index.m3u8").write_text("#EXTM3U\n#EXT-X-ENDLIST\n", encoding="utf-8")
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
    monkeypatch.setattr(server.runtime, "FINAL_DIR", server.runtime.RECORD_DIR)
    plan = server.disk._relocation_plan()
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

    plan = server.disk._relocation_plan()
    assert [i["recording_id"] for i in plan["items"]] == [ok_id]
    assert plan["skipped_missing"] == 1
    assert plan["total_bytes"] == 2048
    assert plan["by_streamer"][0]["items"] == 1
    assert ghost_id not in [i["recording_id"] for i in plan["items"]]


def test_relocation_plan_uses_real_file_size_not_db_bytes(server, relocation_dirs):
    """容量は実fileのsizeで出す。実測で16本がDB値とずれていた。"""
    work, _final = relocation_dirs
    recording_id, path = _make_relocatable(server, work, size=4096)
    server.runtime.storage.update_recording(
        recording_id, "completed", str(path), path.name, time.time(), 999999)

    plan = server.disk._relocation_plan()
    assert plan["items"][0]["bytes"] == 4096


def test_relocation_plan_includes_recordings_that_only_have_ts(server, relocation_dirs):
    """mp4を作らなくなった今、素材(.ts)だけの録画も移送対象である。

    mp4の実在で対象を選んでいたため、素材しか無い録画は計画に一度も載らず、finalizeの移送に
    失敗した録画が作業先に残ったまま画面にも出なかった。sizeはDBのbytesで出す(session dirは
    束ね前で数千fileあり、容量画面のたびに走査できない)。"""
    work, _final = relocation_dirs
    rid, _path = _make_relocatable(server, work, with_mp4=False, segments=2, size=4096)

    plan = server.disk._relocation_plan()

    assert [i["recording_id"] for i in plan["items"]] == [rid]
    assert plan["items"][0]["bytes"] == 4096
    assert plan["skipped_missing"] == 0


def test_relocation_plan_measures_ts_only_recordings_without_db_bytes(
        server, relocation_dirs):
    """bytesを持たない行だけは実測する。0のまま出すと移送量が桁で狂う。"""
    from tictok.core import layout

    work, _final = relocation_dirs
    rid, path = _make_relocatable(server, work, with_mp4=False, segments=3)
    server.runtime.storage.update_recording(
        rid, "completed", str(path), path.name, time.time(), 0)

    plan = server.disk._relocation_plan()

    measured = server.files._dir_usage(layout.session_dir(work, path.stem))[0]
    assert plan["items"][0]["bytes"] == measured > 0


def test_relocation_moves_a_ts_only_recording(server, relocation_dirs):
    """素材だけの録画は、session dirごと最終保存先へ移りDBのpathも追随する。"""
    from pathlib import Path

    from tictok.core import layout

    work, final = relocation_dirs
    rid, src = _make_relocatable(server, work, with_mp4=False, segments=2)

    result = server.disk._run_relocation(server.disk._relocation_plan())

    assert (result["moved"], result["failures"]) == (1, [])
    assert not layout.session_dir(work, src.stem).exists()
    assert layout.has_media(layout.session_dir(final, src.stem))
    assert server.disk._is_under(Path(server.runtime.storage.get_recording(rid)["path"]), final)


def test_relocation_leaves_a_recording_that_is_being_finalized(server, relocation_dirs):
    """確定処理中の録画は動かさない。移送は元を消す片道の操作で、読み手の足元を抜く。"""
    from tictok.core import layout
    from tictok.record.recorder import finalizing_scope

    work, _final = relocation_dirs
    rid, src = _make_relocatable(server, work, with_mp4=False, segments=2)
    plan = server.disk._relocation_plan()

    with finalizing_scope(rid):
        result = server.disk._run_relocation(plan)

    assert result["moved"] == 0
    assert result["failures"][0]["reason"] == "確定処理中です"
    assert layout.has_media(layout.session_dir(work, src.stem))


def test_relocation_leaves_a_recording_a_media_job_is_holding(server, relocation_dirs):
    """待機/実行中のjobが掴んでいる録画も同じ理由で動かさない。"""
    from tictok.core import layout

    work, _final = relocation_dirs
    rid, src = _make_relocatable(server, work, with_mp4=False, segments=2)
    server.runtime.storage.enqueue_media_job("relojob1", "pack", rid)

    result = server.disk._run_relocation(server.disk._relocation_plan())

    assert result["moved"] == 0
    assert result["failures"][0]["reason"] == "他の処理が使用中です"
    assert layout.has_media(layout.session_dir(work, src.stem))


def test_relocation_moves_the_pair_and_updates_the_db_path(server, relocation_dirs):
    """mp4とtiming sidecarが移り、DBのpathが退避先を指すこと。
    pathを更新しないと再生と出力が壊れる(serverはrecordings.pathをそのまま使う)。"""
    from pathlib import Path

    from tictok.record.recorder import timing_path

    work, final = relocation_dirs
    recording_id, src = _make_relocatable(server, work)
    src_timing = timing_path(src)
    assert src_timing.is_file()

    result = server.disk._run_relocation(server.disk._relocation_plan())

    assert (result["moved"], result["failures"]) == (1, [])
    assert not src.exists()
    assert not src_timing.exists()
    dst = Path(server.runtime.storage.get_recording(recording_id)["path"])
    assert dst.is_file()
    assert server.disk._is_under(dst, final)
    assert timing_path(dst).is_file()


def test_relocation_without_a_timing_sidecar_still_moves_the_mp4(server, relocation_dirs):
    """sidecarが無い録画でも移せること(既存の_move_recording_filesの判断をそのまま使う)。"""
    from pathlib import Path

    work, final = relocation_dirs
    recording_id, _src = _make_relocatable(server, work, with_timing=False)
    result = server.disk._run_relocation(server.disk._relocation_plan())
    assert result["moved"] == 1
    assert server.disk._is_under(Path(server.runtime.storage.get_recording(recording_id)["path"]), final)


def test_relocation_failure_keeps_the_file_and_the_db_path(server, relocation_dirs,
                                                           monkeypatch):
    """失敗したら作業先に残し、DBも更新しない。偽の最終位置を作らない既存の設計に揃える。"""
    work, _final = relocation_dirs
    recording_id, src = _make_relocatable(server, work)
    original_path = server.runtime.storage.get_recording(recording_id)["path"]

    def _boom(source, destination):
        raise OSError(32, "file is in use")

    monkeypatch.setattr(server.Recorder, "_move_recording_files", staticmethod(_boom))
    result = server.disk._run_relocation(server.disk._relocation_plan())

    assert result["moved"] == 0
    assert len(result["failures"]) == 1
    assert src.is_file(), "失敗時はfileを作業先に残す"
    assert server.runtime.storage.get_recording(recording_id)["path"] == original_path


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
    result = server.disk._run_relocation(server.disk._relocation_plan())

    assert result["moved"] == 2
    assert len(result["failures"]) == 1
    assert sum(1 for i in ids
               if server.disk._is_under(Path(server.runtime.storage.get_recording(i)["path"]),
                                   server.runtime.FINAL_DIR)) == 2


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

    result = server.disk._run_relocation(server.disk._relocation_plan())

    assert (result["moved"], result["failures"]) == (1, [])
    dst = Path(server.runtime.storage.get_recording(recording_id)["path"])
    assert server.disk._is_under(dst, final)
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
    result = server.disk._run_relocation(server.disk._relocation_plan())

    assert (result["moved"], result["failures"]) == (1, [])
    dst = Path(server.runtime.storage.get_recording(recording_id)["path"])
    assert dst.is_file()
    assert server.disk._is_under(dst, final)
    assert stuck.is_file(), "動かせなかったfileは旧rootに残る(消さない)"
    assert relocatable_artifact_paths(dst)


def test_relocation_skips_a_recording_that_started_again_before_execution(
    server, relocation_dirs
):
    """dry-runから実行までの間に状態が変わった録画は動かさない。
    書き込み中のfileを動かすことになる。"""
    work, _final = relocation_dirs
    recording_id, src = _make_relocatable(server, work)
    plan = server.disk._relocation_plan()
    server.runtime.storage.update_recording(
        recording_id, "recording", str(src), src.name, None, 0)

    result = server.disk._run_relocation(plan)
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

    plan = server.disk._relocation_plan()
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
    placement = server.disk._capacity_report()["placement"]
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
    server.runtime.storage.update_recording_bytes(ghost_id, 0)

    locations = server.disk._relocation_summary()["locations"]
    assert locations["work"] == {"items": 1, "bytes": 2048, "unknown_bytes": 0}
    assert locations["final"]["items"] == 2
    assert locations["final"]["bytes"] == 4096
    assert locations["final"]["unknown_bytes"] == 1


def test_placement_is_reported_even_without_a_final_dir(server, monkeypatch, tmp_path):
    """最終保存先が未設定でも所在は出す。出さないと画面から機能ごと消え、「移動できない」
    ではなく「移動機能が無い」に見える。"""
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(server.runtime, "RECORD_DIR", work.resolve())
    monkeypatch.setattr(server.runtime, "FINAL_DIR", work.resolve())
    _make_relocatable(server, work.resolve(), size=1024)

    summary = server.disk._relocation_summary()
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

        storage = server.runtime.storage
        session_id = storage.create_session(unique_id, 60)
        storage.update_session(session_id, "connected")
        n = next(counter)
        stem = f"{n:05d}_{unique_id}_20250101_{n:06d}"
        mp4_dir = layout.mp4_dir(server.runtime.RECORD_DIR, stem, unique_id)
        mp4_dir.mkdir(parents=True, exist_ok=True)
        path = mp4_dir / f"{stem}.mp4"
        path.write_bytes(b"\x00" * 64)
        seg_dir = layout.session_dir(server.runtime.RECORD_DIR, stem, unique_id)
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
    server.runtime.storage.save_transcript(
        recording_id, {"language": "ja", "text": "あ",
                       "segments": [{"start": 0.0, "end": 1.0, "text": "あ"}]})
    client.post("/api/streamers/tester/recordings/delete-files",
                json={"mp4_ids": [recording_id], "ts_ids": []})
    assert not path.exists()
    # mp4だけの指定なのでHLSは残る。
    assert seg_dir.is_dir()
    assert server.runtime.storage.get_recording(recording_id) is not None
    assert recording_id in server.runtime.storage.transcribed_recording_ids()


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
    server.runtime.storage.enqueue_media_job("job-1", "overlay", recording_id)
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
    monkeypatch.setattr(server.media_jobs, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(server.media_jobs, "ffprobe_available", lambda: True)
    monkeypatch.setattr(server.audio_norm, "probe_sample_rate", lambda src: 48000)

    async def fake_duration(path):
        return 300.0

    monkeypatch.setattr(server.media_jobs, "_duration_seconds", fake_duration)

    calls = {"n": 0}

    async def fake_exec(*cmd, **kwargs):
        # 見たいのは音量正規化のffmpegで、その後ろで走る退避sweepのffprobeではない。
        # 最後の1本を持つと、sweepが動く録画(素材がありstemが規約に合う=現行の普通の録画)
        # では捕まえる相手が入れ替わる。出力の書き込みも同じ理由で1本目だけにする —
        # sweepのffprobeは退避したmp4を引数の末尾に持つので、毎回書くと退避を上書きする。
        calls["n"] += 1
        first = calls["n"] == 1
        if first:
            captured["cmd"] = list(cmd)
        if returncode == 0 and first:
            Path(cmd[-1]).write_bytes(output)

        async def read():
            return b""

        async def readline():
            # 進捗streamはすぐEOF。実際のffmpegは out_time_us= を吐くが、ここで見たいのは
            # 引数と差し替えの成否で、%の刻みは progress 側のtestが持つ。
            return b""

        async def wait():
            return returncode

        async def communicate():
            # 退避sweepのffprobeもこの偽processを掴む。communicateが無いとsweepが
            # AttributeErrorで落ち、log上は「退避を掃除できなかった」だけが残る。
            return b"", b""

        return types.SimpleNamespace(
            returncode=returncode,
            stdout=types.SimpleNamespace(readline=readline),
            stderr=types.SimpleNamespace(read=read), wait=wait,
            communicate=communicate, kill=lambda: None)

    monkeypatch.setattr(server.asyncio, "create_subprocess_exec", fake_exec)


async def _run_audionorm(server, recording_id, job_id="an-1"):
    async def report(stage, pct):
        return None

    recording = server.runtime.storage.get_recording(recording_id)
    return await server.media_jobs._audionorm_recording(recording_id, recording, job_id, report)


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
    row = server.runtime.storage.get_recording(recording_id)
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
    assert server.runtime.storage.get_recording(recording_id)["audio_normalized_at"] is None
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
    restored = await server.startup._restore_reprocess_backup(
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

    monkeypatch.setattr(server.startup, "_duration_seconds", unreadable)
    restored = await server.startup._restore_reprocess_backup(
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

    monkeypatch.setattr(server.startup, "_duration_seconds", readable)
    restored = await server.startup._restore_reprocess_backup(
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

    monkeypatch.setattr(server.media_jobs, "_duration_seconds", no_duration)
    result = await _run_audionorm(server, recording_id)
    assert result["normalized"] is True


# ---- 保持policyの資産序列(素材が原本・mp4は派生物) -----------------------------------
# 素材を持つ録画は ``retention`` 名義で作る。有無の判定は path をkeyにしたTTL cacheを通るので、
# 同じ stem を別の状態で作り直す test 同士が互いのcacheを踏まないよう、毎回clearしてから使う。


@pytest.fixture
def retention_recording(server, make_recording_with_ts):
    def _make(*, with_media=True, playlist=True, age_days=10.0):
        server.fsfacts._fs_bulk_cache.clear()
        server.fsfacts._fs_state_cache.clear()
        _s, recording_id, path, seg_dir = make_recording_with_ts(unique_id="retention")
        if playlist:
            _write_playlist(seg_dir, terminated=True)
        if not with_media:
            import shutil

            shutil.rmtree(seg_dir)
        # 経過日数で足切りされる段階(②は派生fileのmtime、③はended_at)を通すため、実fileと
        # 行の両方を同じだけ過去へ寄せる。作った直後のままだと候補に載らない。
        old = time.time() - age_days * 86400
        server.runtime.storage.update_recording(recording_id, "completed", str(path), path.name,
                                        old, 64)
        os.utime(path, (old, old))
        return server.runtime.storage.get_recording(recording_id), path, seg_dir

    return _make


def test_material_without_a_playlist_is_not_treated_as_rebuildable(server, retention_recording):
    """再mp4化も再生もplaylist順にsegmentを読む。listの無い.tsからは作り直せないので、
    その録画のmp4は原本のまま(派生物として消させない)。"""
    recording, _path, seg_dir = retention_recording(playlist=False)
    assert server.files._has_usable_media(seg_dir) is False
    assert server.files._recording_media_dirs(recording) == []


def test_the_plan_moves_the_mp4_of_a_recording_that_still_has_material(
        server, monkeypatch, retention_recording):
    recording, _path, seg_dir = retention_recording()
    monkeypatch.setattr(server.disk, "_retention_rules",
                        lambda: {"transient_hours": 0, "derived_days": 1,
                                 "source_days": 1, "source_enabled": 1})
    plan = server.disk._build_retention_plan()
    derived = next(p for p in plan["phases"] if p["phase"] == "derived")
    source = next(p for p in plan["phases"] if p["phase"] == "source")
    mine = next(i for i in derived["items"] if i["recording_id"] == recording["id"])
    assert mine["includes_source"] is True and mine["source_bytes"] == 64
    # ③に載るのは素材の方(segmentと再生listの実体)。mp4のbytesは②が数えている。
    theirs = next(i for i in source["items"] if i["recording_id"] == recording["id"])
    assert theirs["media"] is True
    assert theirs["bytes"] == sum(p.stat().st_size for p in seg_dir.iterdir())
    assert theirs["files"] == len(list(seg_dir.iterdir()))


def test_the_plan_keeps_the_mp4_as_the_source_when_no_material_remains(
        server, monkeypatch, retention_recording):
    recording, _path, _seg = retention_recording(with_media=False)
    monkeypatch.setattr(server.disk, "_retention_rules",
                        lambda: {"transient_hours": 0, "derived_days": 1,
                                 "source_days": 1, "source_enabled": 1})
    plan = server.disk._build_retention_plan()
    derived = next(p for p in plan["phases"] if p["phase"] == "derived")
    source = next(p for p in plan["phases"] if p["phase"] == "source")
    assert [i for i in derived["items"] if i["recording_id"] == recording["id"]] == []
    mine = next(i for i in source["items"] if i["recording_id"] == recording["id"])
    assert mine["media"] is False and mine["bytes"] == 64


def test_the_derived_phase_deletes_the_mp4_but_leaves_the_material(server, retention_recording):
    recording, path, seg_dir = retention_recording()
    freed = server.disk._delete_derived_item(
        {"recording_id": recording["id"], "path": str(path), "bytes": 64,
         "includes_source": True, "source_bytes": 64})
    assert freed == 64
    assert not path.exists()
    assert seg_dir.is_dir()
    # 消したmp4についての主張(作り直し済み/正規化済み)も落ちていること。
    assert server.runtime.storage.get_recording(recording["id"])["bytes"] == 0


def test_the_derived_phase_keeps_the_mp4_when_the_material_vanished_after_planning(
        server, retention_recording):
    """planを組んでから実行までの間に素材が消えることがある。そのmp4はもう最後の1本。"""
    import shutil

    recording, path, seg_dir = retention_recording()
    shutil.rmtree(seg_dir)
    freed = server.disk._delete_derived_item(
        {"recording_id": recording["id"], "path": str(path), "bytes": 64,
         "includes_source": True, "source_bytes": 64})
    assert path.is_file()
    # 解放できなかったmp4ぶんは差し引いて報告する。
    assert freed == 0


def test_the_source_phase_removes_the_material_and_the_row(server, retention_recording):
    recording, path, seg_dir = retention_recording()
    freed = server.disk._delete_source_item(
        {"recording_id": recording["id"], "path": str(path), "bytes": 256, "media": True})
    assert freed == 256
    assert not seg_dir.exists()
    assert not path.exists()
    assert server.runtime.storage.get_recording(recording["id"]) is None


def test_the_source_phase_leaves_the_material_alone_for_an_mp4_only_recording(
        server, retention_recording):
    """素材の無い録画の③はmp4だけを指す。他の録画の素材まで巻き込まないこと。"""
    keep, _keep_path, keep_seg = retention_recording()
    recording, path, _seg = retention_recording(with_media=False)
    server.disk._delete_source_item(
        {"recording_id": recording["id"], "path": str(path), "bytes": 64, "media": False})
    assert not path.exists()
    assert keep_seg.is_dir()
    assert server.runtime.storage.get_recording(keep["id"]) is not None


def test_the_derived_phase_keeps_the_mp4_while_a_job_holds_the_recording(
        server, monkeypatch, retention_recording):
    """焼き込み・転写が走っている録画のmp4を抜くと、実行中のffmpegの入力が消える。"""
    recording, path, _seg = retention_recording()
    monkeypatch.setattr(server.runtime.storage, "busy_recording_ids",
                        lambda: {recording["id"]})
    freed = server.disk._delete_derived_item(
        {"recording_id": recording["id"], "path": str(path), "bytes": 64,
         "includes_source": True, "source_bytes": 64})
    assert path.is_file()
    assert freed == 0


# ---- ts結合(hls_pack)のjob ---------------------------------------------------------
# 束ねる対象は素材そのものなので、mp4の有無とは無関係に走る。判定と実行の両方を、実fileを
# 置いた録画に対して確かめる。


@pytest.fixture
def pack_recording(server, make_recording_with_ts, request):
    """素材(.ts + 再生list)を持つ録画。

    配信者名をtestごとに分けるのは、素材dirのpathがstem(連番+配信者名)で決まり、その連番が
    testごとに振り直されるため。同じ名前で作ると、別のtestが残した束ね済みmarkerや消した
    mp4をそのまま引き継ぐ(storageとrecord dirはtest間で共有)。cacheも同じ理由でclearする。"""
    handle = "pack" + re.sub(r"[^A-Za-z0-9]", "", request.node.name)[-32:]

    def _make(*, packed=False, with_media=True):
        server.fsfacts._fs_bulk_cache.clear()
        server.fsfacts._fs_state_cache.clear()
        _s, recording_id, path, seg_dir = make_recording_with_ts(unique_id=handle)
        _write_playlist(seg_dir, terminated=True)
        if packed:
            (seg_dir / "pack00000.ts").write_bytes(b"\x01" * 256)
        if not with_media:
            import shutil

            shutil.rmtree(seg_dir)
        return server.runtime.storage.get_recording(recording_id), path, seg_dir

    return _make


def _pack_facts(server, recording):
    facts_by_id = server.fsfacts._bulk_fs_facts_batch([recording])
    server.fsfacts._bulk_hls_batch([recording], facts_by_id)
    return facts_by_id[recording["id"]]


def test_pack_targets_material_that_is_not_packed_yet(server, pack_recording):
    recording, _path, _seg = pack_recording()
    assert server.routes.bulk._bulk_classify("pack", recording, _pack_facts(server, recording)) == (True, "")


def test_pack_skips_material_that_is_already_packed(server, pack_recording):
    recording, _path, _seg = pack_recording(packed=True)
    assert server.routes.bulk._bulk_classify("pack", recording, _pack_facts(server, recording)) \
        == (False, "packed")


def test_pack_skips_a_recording_without_material(server, pack_recording):
    recording, _path, _seg = pack_recording(with_media=False)
    assert server.routes.bulk._bulk_classify("pack", recording, _pack_facts(server, recording)) \
        == (False, "no_hls")


def test_pack_does_not_need_the_mp4(server, pack_recording):
    """束ねるのは素材。mp4を消した録画も対象であり続ける。"""
    recording, path, _seg = pack_recording()
    path.unlink()
    server.fsfacts._fs_bulk_cache.clear()
    assert server.routes.bulk._bulk_classify("pack", recording, _pack_facts(server, recording)) == (True, "")


def test_packed_material_is_counted_as_done_in_the_bulk_status(client, pack_recording):
    recording, _path, _seg = pack_recording(packed=True)
    body = client.get("/api/bulk/status", params={"kinds": "pack"}).json()
    entry = next(s for s in body["streamers"] if s["unique_id"] == recording["unique_id"])
    assert entry["done"]["pack"] == 1
    assert entry["targets"]["pack"] == 0


def test_pack_endpoint_enqueues_a_job(client, server, pack_recording):
    recording, _path, _seg = pack_recording()
    body = client.post("/api/recordings/%d/pack" % recording["id"]).json()
    assert body["kind"] == "pack" and body["state"] == "pending"
    assert server.runtime.storage.get_media_job(body["job_id"])["kind"] == "pack"


# ---- 画面に出す録画の番号 ----------------------------------------------------------
# 番号はfile名の先頭に載るSession番号へ一本化する。recordings.idを出すと、同じ録画がdisk上の
# 00339_… と画面の #705 という別々の名前で呼ばれ、file名から画面を引けなくなる。


def test_recording_number_comes_from_the_filename_even_without_a_session(server):
    """session削除後も残る録画はsession_idがNULLになるが、file名の番号は生きている。"""
    rec = {"filename": "00339_user_20260721_144949.mp4", "session_id": None}
    assert server.files._recording_no(rec) == "#00339"
    assert server.files._recording_label(rec) == "00339_user_20260721_144949"


def test_recording_number_falls_back_to_the_session_when_the_name_is_off_convention(server):
    """中断録画はfile名がplaylistを指すことがある。そのときだけsession_idから番号を作る。"""
    rec = {"filename": "index.m3u8", "session_id": 270}
    assert server.files._recording_no(rec) == "#00270"
    assert server.files._recording_label(rec) == "#00270 index"


def test_media_job_titles_name_the_recording_by_its_session_number(client, server,
                                                                   pack_recording):
    """ts結合だけがrecordings.idをtitleに載せていた(他の種別はfile名のstem)。"""
    recording, _path, _seg = pack_recording()
    job_id = client.post("/api/recordings/%d/pack" % recording["id"]).json()["job_id"]
    title = server.runtime.storage.get_media_job(job_id)["title"]
    assert title.endswith(Path(recording["filename"]).stem)
    assert "#%d" % recording["id"] not in title


def test_pack_endpoint_refuses_a_recording_without_material(client, pack_recording):
    recording, _path, _seg = pack_recording(with_media=False)
    response = client.post("/api/recordings/%d/pack" % recording["id"])
    assert response.status_code == 409
    assert ".ts" in response.json()["detail"]


def _fake_pack(server, monkeypatch, result=None, calls=None, steps=(5, 60, 100)):
    async def _pack_session(hls_dir, playlist_name="index.m3u8", on_progress=None):
        if calls is not None:
            calls.append(Path(hls_dir))
        for pct in steps:
            if on_progress is not None:
                await on_progress(pct)
        return result or {"packed": True, "reason": "", "segments": 2, "packs": 1,
                          "bytes": 256}

    monkeypatch.setattr(server.hls_pack, "pack_session", _pack_session)


async def _run_pack(server, recording_id, stages=None):
    async def report(stage, pct):
        if stages is not None:
            stages.append((stage, pct))

    return await server.media_jobs._run_media_job(
        {"kind": "pack", "recording_id": recording_id, "job_id": "packjob"}, report)


async def test_pack_job_runs_on_the_session_dir_and_reports_progress(
        server, monkeypatch, pack_recording):
    recording, _path, seg_dir = pack_recording()
    calls = []
    stages = []
    _fake_pack(server, monkeypatch, calls=calls)
    result = await _run_pack(server, recording["id"], stages)
    assert calls == [seg_dir]
    assert result["packed"] is True and result["packs"] == 1
    assert [pct for _stage, pct in stages] == [0, 5, 60, 100]


async def test_pack_job_is_idempotent_for_material_that_is_already_packed(
        server, monkeypatch, pack_recording):
    recording, _path, _seg = pack_recording(packed=True)
    calls = []
    _fake_pack(server, monkeypatch, calls=calls)
    result = await _run_pack(server, recording["id"])
    assert calls == []
    assert result["reason"] == "already_packed" and result["packed"] is False


async def test_pack_job_surfaces_the_reason_it_could_not_pack(
        server, monkeypatch, pack_recording):
    """pack_sessionは失敗しても元を触らない。理由をそのまま出さないと、容量なのか検証で
    弾かれたのかが読めない。"""
    recording, _path, _seg = pack_recording()
    _fake_pack(server, monkeypatch,
               result={"packed": False, "reason": "packing changed the duration",
                       "segments": 2, "packs": 0, "bytes": 0})
    with pytest.raises(HTTPException) as excinfo:
        await _run_pack(server, recording["id"])
    assert excinfo.value.status_code == 500
    assert "packing changed the duration" in excinfo.value.detail


async def test_pack_job_refuses_when_the_volume_cannot_hold_a_second_copy(
        server, monkeypatch, pack_recording):
    """束ねる間は元segmentを残したまま検証するので、素材と同じだけの空きが要る。"""
    recording, _path, _seg = pack_recording()
    calls = []
    _fake_pack(server, monkeypatch, calls=calls)
    monkeypatch.setattr(server.media_jobs, "_pack_headroom", lambda _dir: (500, 100))
    with pytest.raises(HTTPException) as excinfo:
        await _run_pack(server, recording["id"])
    assert excinfo.value.status_code == 507
    assert calls == []


async def test_pack_job_waits_while_another_job_holds_the_recording(
        server, monkeypatch, pack_recording):
    """再mp4化は素材をplaylist順に読んでいる最中。その足元で束ね直すと読み手が壊れる。"""
    recording, _path, _seg = pack_recording()
    calls = []
    _fake_pack(server, monkeypatch, calls=calls)
    monkeypatch.setattr(server.runtime.storage, "pending_media_job_keys",
                        lambda: {("reprocess", recording["id"])})
    with pytest.raises(server.JobDeferred):
        await _run_pack(server, recording["id"])
    assert calls == []


async def test_pack_job_stops_at_a_cancel_before_anything_is_written(
        server, monkeypatch, pack_recording):
    """取り消しはcallbackでしか効かせられない。60%(束ね書き込みの直前)で抜ければ、まだ何も
    書いていない状態で止まる。"""
    from tictok.core import cancel as cancel_mod

    recording, _path, _seg = pack_recording()
    _fake_pack(server, monkeypatch)
    token = cancel_mod.CancelToken("packjob")
    token.cancel()
    with cancel_mod.token_scope(token):
        with pytest.raises(cancel_mod.JobCancelled):
            await _run_pack(server, recording["id"])


async def test_pack_job_does_not_cancel_after_the_work_is_done(
        server, monkeypatch, pack_recording):
    """100%は元segmentの削除まで終わった後。そこで中断すると、済んだ作業を取り消し扱いに
    してしまう。"""
    from tictok.core import cancel as cancel_mod

    recording, _path, _seg = pack_recording()
    token = cancel_mod.CancelToken("packjob")

    async def _pack_session(hls_dir, playlist_name="index.m3u8", on_progress=None):
        token.cancel()
        await on_progress(100)
        return {"packed": True, "reason": "", "segments": 2, "packs": 1, "bytes": 256}

    monkeypatch.setattr(server.hls_pack, "pack_session", _pack_session)
    with cancel_mod.token_scope(token):
        result = await _run_pack(server, recording["id"])
    assert result["packed"] is True


def test_bulk_queue_accepts_pack(client, server, pack_recording):
    recording, _path, _seg = pack_recording()
    body = client.post("/api/bulk/queue",
                       json={"kind": "pack", "unique_id": recording["unique_id"]}).json()
    assert recording["id"] in body["recording_ids"]
    rows = server.runtime.storage.media_jobs_in_group(body["group_id"])
    assert {row["kind"] for row in rows} == {"pack"}


def test_output_accepts_a_recording_that_has_no_mp4(server, client, monkeypatch):
    """mp4が無いのは異常ではなく既定の状態である。

    finalizeはmp4を作らなくなり、原本は .ts になった。焼き込みも下流も hls_source 経由で
    .ts を読む。ここで ``path.is_file()`` を要求すると、**新しい録画が1本も焼けなくなる**。"""
    from pathlib import Path

    recording = {"id": 1, "path": str(server.runtime.RECORD_DIR / "gone.mp4")}
    monkeypatch.setattr(server.runtime.storage, "get_recording", lambda rid: recording)
    monkeypatch.setattr(server.files, "_safe_recording_path", lambda p: Path(p))
    monkeypatch.setattr(server.files, "_recording_media_dirs",
                        lambda rec: [server.runtime.RECORD_DIR / "ts" / "gone"])
    monkeypatch.setattr(server.disk, "_require_disk_space", lambda *a, **k: None)

    got, path = server.media_jobs._recording_for_output(1)
    assert got is recording
    assert path.name == "gone.mp4"


def test_output_on_a_recording_with_no_material_left_still_says_it_is_gone(server,
                                                                          monkeypatch):
    """素材も無い録画は本当に手が無い。作り直せるかのように案内しないこと。"""
    from pathlib import Path

    recording = {"id": 1, "path": str(server.runtime.RECORD_DIR / "gone.mp4")}
    monkeypatch.setattr(server.runtime.storage, "get_recording", lambda rid: recording)
    monkeypatch.setattr(server.files, "_safe_recording_path", lambda p: Path(p))
    monkeypatch.setattr(server.files, "_recording_media_dirs", lambda rec: [])

    with pytest.raises(server.HTTPException) as excinfo:
        server.media_jobs._recording_for_output(1)
    assert excinfo.value.status_code == 404


# ===== 起動時のts結合sweep =====


def _sweep_recording(server, stem, streamer="tester", status="completed",
                     packed=False, mtime_offset=-3600):
    """sweepの候補になり得る録画を1本作り、(row, session_dir) を返す。"""
    import os

    from tictok.core import layout

    session = layout.session_dir(server.runtime.RECORD_DIR, stem, streamer)
    session.mkdir(parents=True, exist_ok=True)
    name = "pack000.ts" if packed else "seg00000.ts"
    (session / name).write_bytes(b"\x47" * 188)
    (session / "index.m3u8").write_text(
        "#EXTM3U\n#EXTINF:2.000000,\n" + name + "\n", encoding="utf-8")
    if packed:
        (session / "segments.json").write_text("{}", encoding="utf-8")
    stamp = time.time() + mtime_offset
    for f in session.iterdir():
        os.utime(f, (stamp, stamp))
    mp4 = layout.mp4_path(server.runtime.RECORD_DIR, stem, streamer)
    return {"id": 1, "path": str(mp4), "filename": mp4.name, "status": status}, session


def test_the_pack_sweep_skips_live_packed_and_recent_recordings(server, monkeypatch):
    """sweepが触ってはいけない録画を確実に外すこと。

    録画中のdirを束ねると、捕捉中のffmpegがplaylistを上書きし、消したsegmentを指す
    playlistが残る(実際に1本やってしまった)。束ね済みと素材無しは、そもそも仕事が無い。"""
    rows = []
    live, _ = _sweep_recording(server, "00001_tester_20260101_120000", status="recording")
    packed, _ = _sweep_recording(server, "00002_tester_20260101_120000", packed=True)
    recent, _ = _sweep_recording(server, "00003_tester_20260101_120000", mtime_offset=-5)
    todo, _ = _sweep_recording(server, "00004_tester_20260101_120000")
    for i, r in enumerate((live, packed, recent, todo), start=1):
        r["id"] = i
        rows.append(r)
    monkeypatch.setattr(server.runtime.storage, "list_recordings", lambda limit=0: rows)

    got = server.startup._startup_sweep_candidates({"pack": 10})["pack"]

    assert [r["id"] for r in got] == [4], "録画中/束ね済み/直近書き込みのどれかを拾っている"


def test_the_pack_sweep_honours_the_per_start_limit(server, monkeypatch):
    """1度に積む本数を必ず守ること。

    未結合が100件あると、上限が効かなければ起動直後の数時間ずっとdiskが塞がる
    (実測で1本30〜220秒)。"""
    rows = []
    for i in range(1, 6):
        row, _ = _sweep_recording(server, f"0000{i}_tester_20260101_120000")
        row["id"] = i
        rows.append(row)
    monkeypatch.setattr(server.runtime.storage, "list_recordings", lambda limit=0: rows)

    assert len(server.startup._startup_sweep_candidates({"pack": 2})["pack"]) == 2
    assert len(server.startup._startup_sweep_candidates({"pack": 0})["pack"]) == 0


def test_the_startup_sweep_skips_recordings_that_already_failed(server, monkeypatch):
    """前回そうなった録画を自動で積み直さないこと。

    sweepの候補判定は成果物の実在なので、失敗・skip・取り消しで終わった録画は成果物が無い
    まま残り、次の起動でまた候補に戻る。音声の無い録画のように結果が変わらないものを毎回
    積み直すと、台帳が同じ失敗で埋まる。"""
    # RECORD_DIRはtest間で共有される(tictok.serverはmodule cacheで1回しかimportされない)ので、
    # 他のtestが同じstemへ残したpack済みsegmentを掴まないよう、stemを分ける。
    rows = []
    for i in range(1, 4):
        row, _ = _sweep_recording(server, f"0100{i}_tester_20260101_120000")
        row["id"] = i
        rows.append(row)
    monkeypatch.setattr(server.runtime.storage, "list_recordings", lambda limit=0: rows)
    monkeypatch.setattr(
        server.runtime.storage, "media_job_recording_ids_in_states",
        lambda kinds, states: {"pack": {1, 3}},
    )

    got = server.startup._startup_sweep_candidates({"pack": 10})["pack"]

    assert [r["id"] for r in got] == [2], "失敗で終わった録画を積み直している"


async def test_the_startup_sweep_marks_what_it_queues_and_yields_the_queue(server,
                                                                          monkeypatch):
    """sweepが積んだ行は、順番でも本数でも人の投入に道を譲れる形で入ること。

    印(sweep)が付いていないと同時実行を別枠で絞れず、priorityを下げていないと、起動直後に
    人が投げたjobが数十本のsweepの後ろで待たされる。"""
    row, _ = _sweep_recording(server, "03001_tester_20260101_120000")
    row["id"] = 1
    row["ended_at"] = time.time() - 86400
    monkeypatch.setattr(server.runtime.storage, "list_recordings", lambda limit=0: [row])
    monkeypatch.setattr(server.runtime.storage, "get_recording", lambda rid: row)
    async def _no_stt_sweep():
        return {"added": 0, "candidates": 0}

    monkeypatch.setattr(server.startup, "_sweep_transcriptions", _no_stt_sweep)
    # 波形だけを1本積ませる。他の種別まで積むと、印とpriorityがどの種別のものか読めない。
    limits = {"pack_sweep_per_start": 0, "sprite_sweep_per_start": 0,
              "waveform_sweep_per_start": 1}
    real_get = server.runtime.settings.get
    monkeypatch.setattr(server.runtime.settings, "get",
                        lambda key, *a: limits.get(key, real_get(key, *a)))
    enqueued = []

    async def _capture(*args, **kwargs):
        enqueued.append((args, kwargs))
        return {"state": "pending", "queued_at": 0.0}

    monkeypatch.setattr(server.media_jobs.media_job_queue, "enqueue", _capture)
    monkeypatch.setattr(server.media_jobs.media_job_queue, "pending_for", lambda kind, rid: None)

    await server.startup._startup_sweep_bg()

    assert len(enqueued) == 1, "波形を1本も積んでいない"
    kwargs = enqueued[0][1]
    assert kwargs["sweep"] is True
    assert kwargs["priority"] == server.media_jobs.SWEEP_JOB_PRIORITY < 0


def test_the_startup_sweep_picks_recordings_without_a_waveform(server, monkeypatch):
    """波形cacheが無い録画だけを拾い、既に在るものは拾わないこと。

    在るものまで積むと、起動のたびに全録画ぶんのdecodeがqueueへ並ぶ。"""
    from tictok.media.waveform import waveform_artifact_paths

    rows = []
    for i in range(1, 4):
        row, _ = _sweep_recording(server, f"0200{i}_tester_20260101_120000")
        row["id"] = i
        # 波形は素材を読むだけなので、静穏判定は録画の終了時刻で行う。
        row["ended_at"] = time.time() - 86400
        rows.append(row)
    for path in waveform_artifact_paths(Path(rows[1]["path"])):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(server.runtime.storage, "list_recordings", lambda limit=0: rows)

    got = server.startup._startup_sweep_candidates({"waveform": 10})["waveform"]

    # 古い方から片付けるので、新しい順の一覧を逆に辿った順番で返る。
    assert [r["id"] for r in got] == [3, 1], "cacheの有無を見ていない"


# ===== reel(切り出しの連結) =====


def test_create_reel_enqueues_one_job_with_a_representative_recording_id(
    client, server, make_srv_recording
):
    """reelは複数録画にまたがるが、recording_id を空にしてはいけない。

    claim の SQL が ``recording_id NOT IN (SELECT ... WHERE state='running'
    AND recording_id IS NOT NULL)`` なので、SQLの三値論理により NULL の行は
    **実行中のjobが1件でもある間は拾われない**(空くまで待機のまま止まる)。
    """
    session_id, recording_id, _ = make_srv_recording(ts_segments=2)
    body = client.post("/api/reels", json={
        "items": [{"recording_id": recording_id, "start": 0.0, "end": 5.0},
                  {"recording_id": recording_id, "start": 10.0, "end": 15.0}],
    }).json()
    assert body["kind"] == "reel"
    assert body["recording_id"] == recording_id
    assert body["parts"] == 2
    assert body["output_name"].endswith(".mp4")
    jobs = server.runtime.storage.list_media_jobs()
    rows = [j for j in jobs if j["kind"] == "reel"]
    assert len(rows) == 1
    assert rows[0]["recording_id"] == recording_id


def test_create_reel_allows_a_second_reel_from_the_same_lead_recording(
    client, make_srv_recording
):
    """範囲listが違えば別の成果物。(kind, recording_id)で弾くと2本目が投げられない。"""
    _, recording_id, _ = make_srv_recording(ts_segments=2)
    first = client.post("/api/reels", json={
        "items": [{"recording_id": recording_id, "start": 0.0, "end": 5.0}]})
    second = client.post("/api/reels", json={
        "items": [{"recording_id": recording_id, "start": 20.0, "end": 25.0}]})
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["job_id"] != second.json()["job_id"]


def test_create_reel_rejects_an_empty_or_inverted_range(client, make_srv_recording):
    _, recording_id, _ = make_srv_recording(ts_segments=2)
    assert client.post("/api/reels", json={"items": []}).status_code == 422
    assert client.post("/api/reels", json={
        "items": [{"recording_id": recording_id, "start": 5.0, "end": 5.0}],
    }).status_code == 422


def test_create_reel_404s_for_a_variant_the_recording_does_not_have(
    client, make_srv_recording
):
    """無い版を黙ってsourceへ落とすと、焼き込み済みを頼んだのに素のreelを受け取る。"""
    _, recording_id, _ = make_srv_recording(ts_segments=2)
    response = client.post("/api/reels", json={
        "items": [{"recording_id": recording_id, "start": 0.0, "end": 5.0}],
        "variant": "overlay",
    })
    assert response.status_code == 404


# ===== 切り出しの方式(mode) =====


def test_clip_batch_stores_the_resolved_mode(client, server, make_srv_recording):
    _, recording_id, _ = make_srv_recording(ts_segments=2)
    client.post("/api/clips/batch", json={
        "items": [{"recording_id": recording_id, "start": 0.0, "end": 5.0}],
        "mode": "smart",
    })
    job = [j for j in server.runtime.storage.list_media_jobs() if j["kind"] == "clip_batch"][0]
    assert job["params"]["mode"] == "smart"


def test_clip_batch_reads_the_legacy_precise_flag(client, server, make_srv_recording):
    """queueに残っている旧形式(precise: bool)のjobを読み替える。

    fallbackではなく保存済みdataのmigration。読み替えないと、精密を頼んだjobが
    既定の方式で書き出される。"""
    _, recording_id, _ = make_srv_recording(ts_segments=2)
    client.post("/api/clips/batch", json={
        "items": [{"recording_id": recording_id, "start": 0.0, "end": 5.0}],
        "precise": True,
    })
    job = [j for j in server.runtime.storage.list_media_jobs() if j["kind"] == "clip_batch"][0]
    assert job["params"]["mode"] == "precise"


def test_clip_rejects_an_unknown_mode(client, make_srv_recording):
    _, recording_id, _ = make_srv_recording(ts_segments=2)
    response = client.post(f"/api/recordings/{recording_id}/clip", json={
        "start": 0.0, "end": 5.0, "mode": "lossless",
    })
    assert response.status_code == 400


def test_clip_default_mode_setting_is_a_choice_not_a_path(client):
    """optionsを持つstrは列挙。pathとして検証すると「絶対パスで」と拒否される。"""
    assert client.put("/api/settings", json={"clip_default_mode": "smart"}).status_code == 200
    assert client.put("/api/settings", json={"clip_default_mode": "nope"}).status_code == 422


# ===== 範囲焼き込み(全尺出力が無くても焼ける) =====


def test_clip_renders_the_range_when_there_is_no_whole_recording_overlay(
    client, server, make_srv_recording
):
    """全尺の焼き込み出力が無ければ、その範囲だけを焼くjobを立てる。

    従来は404で断っていた。3時間の録画を丸ごと焼くのは可逆中間がC:を192GB/時食うため
    実質不可能で、404は「焼き込み済みの切り抜きは作れない」と同義だった。
    """
    server.runtime.settings.update({"video_overlay_comments": 1})
    _, recording_id, _ = make_srv_recording(ts_segments=2)
    body = client.post(f"/api/recordings/{recording_id}/clip", json={
        "start": 0.0, "end": 5.0, "variant": "overlay",
    }).json()
    assert body["route"] == "render"
    assert body["kind"] == "clip_overlay"
    jobs = [j for j in server.runtime.storage.list_media_jobs() if j["kind"] == "clip_overlay"]
    assert len(jobs) == 1
    assert jobs[0]["params"]["start"] == 0.0


def test_clip_copies_from_the_whole_recording_overlay_when_it_exists(
    client, server, make_srv_recording, monkeypatch
):
    """全尺出力が在ればそこからstream copyする(数秒で終わるので焼き直さない)。"""
    _, recording_id, path = make_srv_recording(ts_segments=2)
    from tictok.record.video_overlay import overlay_paths
    overlay = overlay_paths(path)[0]
    overlay.parent.mkdir(parents=True, exist_ok=True)
    overlay.write_bytes(b"\x00" * 64)

    async def fake_make_clip(*args, **kwargs):
        return {"path": "x.mp4", "filename": "x.mp4", "bytes": 1, "start": 0.0,
                "end": 5.0, "encoder": "copy", "normalized": False,
                "output_duration_seconds": 5.0, "keyframe_lead_seconds": 0.0,
                "actual_start_seconds": 0.0}

    monkeypatch.setattr(server.routes.media, "make_clip", fake_make_clip)
    body = client.post(f"/api/recordings/{recording_id}/clip", json={
        "start": 0.0, "end": 5.0, "variant": "overlay",
    }).json()
    assert body["route"] == "copy"


def test_clip_render_route_409s_when_every_overlay_layer_is_off(
    client, server, make_srv_recording
):
    """何も描かない設定でこの経路を通す意味は無い。素の切り出しへ黙って倒さない。"""
    server.runtime.settings.update({"video_overlay_comments": 0, "video_overlay_gifts": 0,
                            "video_overlay_score_bar": 0, "video_overlay_subtitles": 0})
    _, recording_id, _ = make_srv_recording(ts_segments=2)
    response = client.post(f"/api/recordings/{recording_id}/clip", json={
        "start": 0.0, "end": 5.0, "variant": "overlay",
    })
    assert response.status_code == 409
