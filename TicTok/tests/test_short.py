"""short(縦の短尺動画)の自動生成の配線。

範囲確定・間の詰め・検品・題名生成は、それぞれの単体testが持つ(test_clip_range /
test_tighten / test_clip_gate / test_ai_clip_meta)。ここで見るのはそれらを繋ぐ側で、
壊れても「動いているように見える」部分である:

  1. 型(clip_presets)が無い状態で既定値を捏造しない
  2. 型の値域はDBの1箇所で判定する(画面は通すがDBが弾く、を作らない)
  3. 下見(short-plan)は捨てた候補も理由つきで返す
  4. 型が焼き込みを要求するなら、字幕の材料は**投入時**に確かめる
  5. 題名の自動生成が指定されていてAIが未設定なら、1本も作る前に断る
"""

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

BUCKET_SECONDS = 10
BUCKET_COUNT = 40


@pytest.fixture
def server(env_guard):
    # env_guard を先に効かせてから import する(test_clip_candidates と同じ理由)。
    import asyncio as _asyncio

    import tictok.server as srv
    from tictok.api import (access_log, candidates, disk, files, fsfacts, media_jobs,
                            runtime, startup)
    from tictok.api.routes import (ai, analytics, bulk, media, monitors, pages,
                                   recordings, search, sessions, storage, streamers,
                                   system, ws)
    from tictok.media import short as short_media
    from tictok.search import indexer

    assert not str(runtime.RECORD_DIR).lower().endswith("tictok\\recordings")
    return SimpleNamespace(
        app=srv.app, runtime=runtime, files=files, media_jobs=media_jobs,
        candidates=candidates, indexer=indexer, short=short_media,
        routes=SimpleNamespace(media=media, recordings=recordings),
        asyncio=_asyncio,
    )


@pytest.fixture
def client(server):
    return TestClient(server.app)


@pytest.fixture
def presets(server):
    """このtestが作った型だけを残し、終わったら消す。

    storage は process で1つなので、消さないと後続のtestが「既定の型」として拾う。
    """
    created: list = []

    def _make(name: str, **values) -> dict:
        base = {"min_seconds": 15.0, "target_seconds": 30.0, "max_seconds": 60.0,
                "subtitles": 0, "comments": 0, "gifts": 0, "score_bar": 0}
        base.update(values)
        preset_id = server.runtime.storage.create_clip_preset(name, base)
        created.append(preset_id)
        return server.runtime.storage.get_clip_preset(preset_id)

    yield _make
    for preset_id in created:
        server.runtime.storage.delete_clip_preset(preset_id)


@pytest.fixture
def recording(server, monkeypatch):
    """盛り上がりを1箇所持つ録画1本。範囲確定まで通せる最小の前提を揃える。"""
    storage = server.runtime.storage
    unique_id = "shorttester"
    session_id = storage.create_session(unique_id, BUCKET_SECONDS)
    storage.update_session(session_id, "connected")
    stem = f"90501_{unique_id}_20260101_{int(time.time() % 1000000):06d}"
    directory = server.runtime.RECORD_DIR / unique_id / "mp4"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stem}.mp4"
    path.write_bytes(b"\x00" * 64)
    started = float(int(time.time()) - 7200)
    recording_id = storage.create_recording(
        session_id, unique_id, str(path), path.name, "hd", started)
    storage.update_recording(
        recording_id, "completed", str(path), path.name,
        started + BUCKET_SECONDS * BUCKET_COUNT, 64)

    rows = []
    for i in range(BUCKET_COUNT):
        rows.append({"start": started + i * BUCKET_SECONDS, "gifts": 0,
                     # 1箇所だけ突出させる。平坦だと標準偏差が0で候補が出ない。
                     "diamonds": 500 if i == 20 else 1,
                     "comments": 1, "likes": 0, "joins": 0, "follows": 0,
                     "shares": 0, "viewers": 10})
    monkeypatch.setattr(storage, "session_buckets",
                        lambda sid, start=None, end=None: rows)
    monkeypatch.setattr(server.indexer, "build_time_mapper_sync",
                        lambda src, started_at, ended_at, video_duration=None: (lambda t: t - started_at))

    async def _duration(src, input_args=()):
        return float(BUCKET_SECONDS * BUCKET_COUNT)

    monkeypatch.setattr(server.candidates, "_duration_seconds", _duration)
    monkeypatch.setattr(server.media_jobs, "_duration_seconds", _duration)
    return SimpleNamespace(id=recording_id, session_id=session_id,
                           started_at=started, path=path, unique_id=unique_id)


def test_preset_list_carries_the_value_ranges_for_the_screen(client):
    response = client.get("/api/clip-presets")
    assert response.status_code == 200, response.text
    fields = response.json()["fields"]
    assert fields["peak_position"]["min"] == 0.1
    assert fields["peak_position"]["max"] == 0.9
    assert fields["subtitles"]["type"] == "bool"


def test_preset_values_are_judged_in_one_place(client, presets):
    preset = presets("判定用")
    # 尺の順序が逆。列単独では判定できないので、行全体で見る側が弾く。
    response = client.patch(f"/api/clip-presets/{preset['id']}",
                            json={"values": {"min_seconds": 90.0}})
    assert response.status_code == 422
    assert "下限" in response.json()["detail"]
    # 値域の外。丸めずに弾く(丸めると画面とDBで違う値が残る)。
    response = client.patch(f"/api/clip-presets/{preset['id']}",
                            json={"values": {"peak_position": 5.0}})
    assert response.status_code == 422


def test_unknown_keys_are_dropped_not_stored(client, presets):
    preset = presets("未知key")
    response = client.patch(f"/api/clip-presets/{preset['id']}",
                            json={"values": {"nonsense": 1, "target_seconds": 40.0}})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["target_seconds"] == 40.0
    assert "nonsense" not in body


def test_deleting_a_preset_twice_reports_it_is_gone(client, presets):
    preset = presets("消す用")
    assert client.delete(f"/api/clip-presets/{preset['id']}").status_code == 200
    assert client.delete(f"/api/clip-presets/{preset['id']}").status_code == 404


def test_plan_returns_ranges_and_the_reasons_for_what_it_dropped(
        client, presets, recording):
    preset = presets("下見", min_seconds=15.0, target_seconds=30.0, max_seconds=60.0)
    response = client.get(f"/api/recordings/{recording.id}/short-plan",
                          params={"preset_id": preset["id"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["candidate_count"] >= 1
    assert len(body["ranges"]) >= 1
    got = body["ranges"][0]
    # 山は範囲の中央ではなく peak_position の位置。
    assert got["start"] < got["peak"] < got["end"]
    assert got["seconds"] == pytest.approx(preset["target_seconds"], abs=0.01)
    # 落とした候補には必ず読める理由が付く。
    for item in body["rejected"]:
        assert item["reason_label"]


def test_plan_without_any_preset_refuses_instead_of_guessing(
        client, monkeypatch, server, recording):
    monkeypatch.setattr(server.runtime.storage, "default_clip_preset", lambda: None)
    response = client.get(f"/api/recordings/{recording.id}/short-plan")
    assert response.status_code == 409
    assert "型" in response.json()["detail"]


def test_ai_titles_are_refused_up_front_when_ai_is_unset(
        client, presets, recording, monkeypatch):
    """途中で気付くと、題名の無いshortが何本か出来た後で止まることになる。"""
    monkeypatch.setenv("TICTOK_AI_ENABLED", "0")
    preset = presets("AIなし")
    response = client.post(f"/api/recordings/{recording.id}/short",
                           json={"preset_id": preset["id"], "ai": True})
    # 投入は通る(材料の確認はworkerが行う)ので、断るのはjobの実行時。
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["kind"] == "short"


def test_burning_subtitles_without_a_transcript_is_refused_at_enqueue(
        client, presets, recording):
    """待った末に落とさない。字幕の材料はqueueへ載せる前に確かめる。"""
    preset = presets("字幕あり", subtitles=1)
    response = client.post(f"/api/recordings/{recording.id}/short",
                           json={"preset_id": preset["id"]})
    assert response.status_code == 409
    assert "文字起こし" in response.json()["detail"]


def test_manual_ranges_are_not_snapped(client, presets, recording, server):
    """人が選んだ位置は動かさない。それが手で指定するということの意味である。"""
    preset = presets("手動")
    path = Path(recording.path)
    plan = server.asyncio.run(server.media_jobs._plan_short_ranges(
        recording.id, path, preset,
        {"ranges": [{"start": 100.0, "end": 140.0, "label": "手で選んだ"}]}))
    assert [(item["start"], item["end"]) for item in plan["ranges"]] == [(100.0, 140.0)]
    assert plan["ranges"][0]["manual"] is True


def test_short_job_kind_is_registered_everywhere(server):
    """種別を足してlabelを足し忘れると、job画面が種別名を名乗れない。"""
    from tictok.core import ops_labels

    assert "short" in server.media_jobs.MEDIA_JOB_KINDS
    assert ops_labels.JOB_DOMAIN_LABELS["short"]
    assert server.media_jobs.MEDIA_JOB_TITLES["short"]
    assert "short" in server.media_jobs.QUEUED_JOB_DOMAINS


def test_preset_drives_what_the_burn_in_draws(server, presets):
    """型は焼き込みの**設定を差し替える**だけで、描画そのものは全尺の焼き込みと同じ経路を
    通る。ここが別経路になると、同じ設定から2つの見た目が生まれる。"""
    preset = presets("焼き分け", subtitles=1, comments=0, gifts=1, score_bar=0)
    view = server.short.ShortSettings(server.runtime.settings, preset)
    assert view.get("video_overlay_subtitles") == 1
    assert view.get("video_overlay_comments") == 0
    assert view.get("video_overlay_gifts") == 1
    assert view.get("video_overlay_score_bar") == 0
    # 型が触らないkeyは元の設定のまま通る。
    assert view.get("video_overlay_font_size") == server.runtime.settings.get(
        "video_overlay_font_size")


def test_subtitle_position_is_pulled_inside_the_safe_area(server, presets):
    preset = presets("安全域", subtitles=1, safe_top_percent=10.0,
                     safe_bottom_percent=30.0)
    view = server.short.ShortSettings(server.runtime.settings, preset)
    assert view.get("video_overlay_subtitle_position_percent") <= 70


def test_level_is_excluded_from_the_smart_cut_join_check():
    """headはこちらが焼いた側で、encoderが実際の解像度・fpsを満たす最小のlevelを選ぶ。
    原本の宣言と食い違うが、level_idcは復号に要る能力の宣言でbitstreamの形式ではない。"""
    from tictok.media import concat

    first = {"video": {"codec_name": "h264", "width": 432, "height": 864,
                       "resolutions": 1, "pix_fmt": "yuv420p", "profile": "High",
                       "level": 31},
             "audio": {"codec_name": "aac", "sample_rate": "48000", "channels": 2}}
    other = {"video": {**first["video"], "level": 30}, "audio": first["audio"]}
    assert concat.mismatch_reasons(first, other) != []
    assert concat.mismatch_reasons(first, other, ("level",)) == []
    # 形式そのものの食い違いは ignore を渡しても残る。
    wrong = {"video": {**other["video"], "width": 720}, "audio": first["audio"]}
    assert concat.mismatch_reasons(first, wrong, ("level",)) != []


@pytest.mark.asyncio
async def test_short_cut_reencodes_the_whole_range_in_the_short_codec(monkeypatch):
    """smart cutは使わない。この録画の音声はHE-AAC(SBR)で、先頭だけAAC-LCへ焼いて残りを
    原本のpacketのまま繋ぐと、1つのtrackにLCの構成情報とHEのframeが同居する(実測で復号
    error率77%)。映像は正常なぶん再生するまで気付けない。"""
    from tictok.media import short as short_media

    calls = {}

    async def fake_make_clip(src, start, end, label=None, **kwargs):
        calls.update(kwargs)
        out = Path(src).parent / "made.mp4"
        out.write_bytes(b"x")
        return {"path": str(out), "keyframe_lead_seconds": None}

    monkeypatch.setattr(short_media, "make_clip", fake_make_clip)
    preset = {"subtitles": 0, "comments": 0, "gifts": 0, "score_bar": 0}
    tmp = Path(__import__("tempfile").mkdtemp())
    (tmp / "src.mp4").write_bytes(b"x")
    result = await short_media.cut_scene(tmp / "src.mp4", tmp / "out.mp4", 0.0, 30.0,
                                         preset, "題", None, None)
    assert result["mode"] == "precise"
    assert calls["precise"] is True
    assert not calls.get("smart")
    # 投稿へ回る出力なので、保存用の正規化codec(既定AV1)ではなくshortのcodecで焼く。
    assert calls["codec"] == "h264"


def test_short_ledger_reuses_the_row_for_a_range_it_already_holds(server, recording):
    """同じ場面のshortを二度作っても、見どころの行は増えない。

    同じ場面を二度出さないための ``taken`` は範囲を決める時に一度読むだけなので、同じ録画へ
    jobが重なると双方が空の台帳を見て同じ範囲を作る。台帳へ書く1箇所が最後の関門で、ここが
    素通しだと範囲しか持たない(メモの空の)行が並び、行だけを読んでも区別が付かなくなる。
    """
    storage = server.runtime.storage
    rec = storage.get_recording(recording.id)
    before = len(storage.list_bookmarks())
    item = {"start": 100.0, "end": 130.0}
    server.media_jobs._record_short_cut(
        rec, item, {"start": 100.0, "end": 130.0, "path": "/out/first.mp4"}, "笑い")
    # 端が1 frame動いた範囲も同じ場面として扱う(無音への吸着でこの程度は動く)。
    server.media_jobs._record_short_cut(
        rec, item, {"start": 100.02, "end": 130.01, "path": "/out/second.mp4"}, "笑い")

    mine = [row for row in storage.list_bookmarks()
            if row["recording_id"] == recording.id]
    assert len(storage.list_bookmarks()) == before + 1
    assert len(mine) == 1
    # 機械が作った範囲は人が付けた印と区別できる形で入る(画面は既定で出さない)。
    assert mine[0]["origin"] == "auto"
    # 書き出し先は最後に出したmp4を指す(古いpathのまま残さない)。
    assert mine[0]["exported_path"] == "/out/second.mp4"

    # 離れた範囲は別の場面なので、これは行を増やす。
    server.media_jobs._record_short_cut(
        rec, item, {"start": 400.0, "end": 430.0, "path": "/out/third.mp4"}, "笑い")
    assert len([row for row in storage.list_bookmarks()
                if row["recording_id"] == recording.id]) == 2
