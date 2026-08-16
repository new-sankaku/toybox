"""作品(グループ1件 -> 完成品1本)の配線。

シーンごとの仕上げ・連結・検品はそれぞれの単体testが持つ(test_short / test_reel /
test_clip_gate)。ここで見るのはそれらを繋ぐ側で、壊れても「動いているように見える」部分:

  1. シーンの並びは ``bookmarks.position``(=人が決めた書き出し順)であって時刻順ではない
  2. 型の尺の下限・上限は**1シーンぶん**の値なので、作品には当てない
  3. 期待尺は「範囲の合計 − 間の詰めで落とした合計」。両trackが揃って短い回はここでしか出ない
  4. 繋げないcodec(AV1)を、繋いでから気付く形にしない
  5. 出来たfileの名前から素性を読み戻せる(成果物はDBに行を持たない)
  6. 同じ録画から採った複数シーンで、eventの読み出しを繰り返さない
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def server(env_guard):
    # env_guard を先に効かせてから import する(test_short と同じ理由)。
    import tictok.server as srv
    from tictok.api import media_jobs, runtime
    from tictok.api.routes import media
    from tictok.media import work as work_media

    assert not str(runtime.RECORD_DIR).lower().endswith("tictok\\recordings")
    return SimpleNamespace(app=srv.app, runtime=runtime, media_jobs=media_jobs,
                           work=work_media, routes=SimpleNamespace(media=media))


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
def group_with_cuts(server):
    """録画1本と、そこから採った3シーンを持つグループ。position は時刻順とは**別**にする。

    pathは ``make_recording``(tmp_root基準)ではなく ``runtime.RECORD_DIR`` から組む。
    runtimeはimport時にrecord rootを固定するので、moduleが既にloadされた後のtestでは
    fixtureのsandboxとrootが食い違い、APIが「不正な録画path」で断る(test_shortが
    同じ理由で同じ作りにしている)。
    """
    import time

    storage = server.runtime.storage
    unique_id = "worktester"
    session_id = storage.create_session(unique_id, 10)
    stem = f"90601_{unique_id}_20260101_{int(time.time() % 1000000):06d}"
    directory = server.runtime.RECORD_DIR / unique_id / "mp4"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stem}.mp4"
    path.write_bytes(b"\x00" * 64)
    recording_id = storage.create_recording(
        session_id, unique_id, str(path), path.name, "hd", 1000.0)
    group = storage.add_group("作品test")
    # 追加順 = position。開始時刻の昇順とはわざと違えて入れる。
    for start, end, label in ((300.0, 320.0, "三番目の時刻"),
                              (100.0, 130.0, "二番目の時刻"),
                              (500.0, 515.0, "一番後ろの時刻")):
        storage.add_bookmark(recording_id, unique_id, start, end, label,
                             group_id=group["id"])
    yield SimpleNamespace(group_id=group["id"], recording_id=recording_id,
                          path=path, unique_id=unique_id)
    storage.delete_group(group["id"])


def test_scenes_come_out_in_export_order_not_in_time_order(server, group_with_cuts):
    """並びは人が決めた ``position``。時刻順へ整えると、並べた操作が無かったことになる。"""
    cuts = server.runtime.storage.bookmarks_in_group(group_with_cuts.group_id)
    assert [c["start"] for c in cuts] == [300.0, 100.0, 500.0]
    assert [c["position"] for c in cuts] == [0, 1, 2]


def test_ungrouped_cuts_do_not_leak_into_a_group(server, group_with_cuts):
    storage = server.runtime.storage
    storage.add_bookmark(group_with_cuts.recording_id, group_with_cuts.unique_id,
                         900.0, 910.0, "未分類")
    cuts = storage.bookmarks_in_group(group_with_cuts.group_id)
    assert 900.0 not in [c["start"] for c in cuts]


def test_preset_length_limits_are_not_applied_to_a_work():
    """型の尺は1シーンぶんの値。5シーン繋げば定義上その上限を超える。

    当ててしまうと全ての作品が「上限超過」で落ち、その不合格は成果物について何も語らない。
    """
    from tictok.media import clip_gate

    preset = {"min_seconds": 15.0, "max_seconds": 60.0, "subtitles": 0}
    report = {"video_seconds": 175.0, "audio_seconds": 175.0, "seconds": 175.0,
              "silent_seconds": 0.0, "black_seconds": 0.0}

    as_short = clip_gate.evaluate(report, preset=preset)
    assert clip_gate.FAIL_TOO_LONG in [f["code"] for f in as_short["failures"]]

    as_work = clip_gate.evaluate(report, preset=preset, scenes=5)
    assert as_work["ok"], as_work["failures"]


def test_a_work_that_lost_both_tracks_equally_is_still_caught():
    """片側だけ短ければ truncated が拾う。**両方揃って**短い回を拾えるのは期待尺だけ。"""
    from tictok.media import clip_gate

    preset = {"min_seconds": 15.0, "max_seconds": 60.0, "subtitles": 0}
    report = {"video_seconds": 40.0, "audio_seconds": 40.0, "seconds": 40.0,
              "silent_seconds": 0.0, "black_seconds": 0.0}
    verdict = clip_gate.evaluate(report, preset=preset, scenes=3, expected_seconds=65.0)
    assert not verdict["ok"]
    assert clip_gate.FAIL_SHORTFALL in [f["code"] for f in verdict["failures"]]
    # 片側だけの欠けと取り違えないこと。
    assert clip_gate.FAIL_TRUNCATED not in [f["code"] for f in verdict["failures"]]


@pytest.mark.asyncio
async def test_a_codec_that_cannot_be_concatenated_is_refused_before_encoding(
        server, monkeypatch, tmp_path):
    """AV1は繋げない。シーンを全部焼いてから気付くと、その時間が丸ごと無駄になる。"""
    from tictok.core import config
    from tictok.media import work as work_media

    monkeypatch.setattr(config, "get_short_codec", lambda: "av1")
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="対応していない映像codec"):
        await work_media.make_work(
            [{"src": src, "start": 0.0, "end": 10.0}],
            preset={"min_seconds": 1.0, "max_seconds": 600.0})


@pytest.mark.asyncio
async def test_an_empty_group_does_not_produce_an_empty_file(tmp_path):
    from tictok.media import work as work_media

    with pytest.raises(RuntimeError, match="シーンがありません"):
        await work_media.make_work([], preset={})


@pytest.mark.asyncio
async def test_a_reversed_range_names_which_scene_is_wrong(tmp_path):
    """どのシーンが悪いかを言う。件数だけ言われても、10シーンの棚では探せない。"""
    from tictok.media import work as work_media

    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="シーン2"):
        await work_media.make_work(
            [{"src": src, "start": 0.0, "end": 10.0},
             {"src": src, "start": 30.0, "end": 20.0}],
            preset={})


def test_a_cache_entry_is_ignored_when_its_artifact_is_gone(tmp_path):
    """署名だけを見ると、fileを消した後も「在る」と答えて存在しない物を繋ごうとする。"""
    from tictok.media import work as work_media

    meta = tmp_path / "x.json"
    artifact = tmp_path / "x.ts"
    work_media._write_meta(meta, "sig", removed_seconds=1.5)
    assert work_media._read_meta(meta, artifact, "sig") is None
    artifact.write_bytes(b"x")
    assert work_media._read_meta(meta, artifact, "sig")["removed_seconds"] == 1.5
    # 指定が変われば同じfileでもcacheは効かない。
    assert work_media._read_meta(meta, artifact, "other") is None


def test_a_broken_cache_record_is_treated_as_a_miss(tmp_path):
    """壊れたjsonで例外にしない。cacheは無くても正しさが変わらない物なので、読めなければ
    作り直せばよい — ここで落とすと、cacheの破損が作品を作れない障害になる。"""
    from tictok.media import work as work_media

    meta = tmp_path / "x.json"
    artifact = tmp_path / "x.ts"
    artifact.write_bytes(b"x")
    meta.write_text("{壊れ", encoding="utf-8")
    assert work_media._read_meta(meta, artifact, "sig") is None


def test_the_tighten_settings_change_the_part_signature(tmp_path):
    """間の詰めはpartの段で掛ける。設定が変われば同じ切り出しから別のpartが出る。"""
    from tictok.media import work as work_media

    cut = tmp_path / "cut.mp4"
    cut.write_bytes(b"x")
    base = {"tighten": 1, "tighten_min_silence_seconds": 1.2, "tighten_keep_seconds": 0.25}
    same = work_media._part_signature(cut, dict(base), "h264")
    assert work_media._part_signature(cut, dict(base), "h264") == same
    assert work_media._part_signature(
        cut, {**base, "tighten_keep_seconds": 0.4}, "h264") != same
    assert work_media._part_signature(cut, dict(base), "hevc") != same


def test_scene_cache_lives_under_the_clips_dir(tmp_path, monkeypatch):
    """成果物と同じvolume・同じ配信者dirの下。片方だけ別driveへ移せない置き方にする。

    録画が最終保存先に在っても一時保存先へ出る(出力先と同じ決め方)。焼き直しは常に
    一時保存先で走るので、録画の所在でcacheを分けると次回のcacheが必ず外れる。"""
    from tictok.core import layout
    from tictok.media import work as work_media

    layout.set_record_roots([tmp_path])
    layout.set_pool_root(tmp_path)
    src = layout.mp4_path(tmp_path / "final", "00042_someone_20260101_120000", "someone")
    cache = work_media.scene_cache_dir(src)
    assert cache.parent == layout.clips_dir(tmp_path, "someone")
    assert cache.name == work_media.SCENE_CACHE_DIR
    # 名前から範囲が読めること(実体がどのシーンか、cache dirを開いて分かる必要がある)。
    assert work_media._scene_stem(src, 100.0, 130.0).endswith("_000140-000210")


def test_the_work_output_stays_in_the_work_root(tmp_path, tmp_root):
    """作品も切り出しと同じ置き方。先頭シーンの録画が最終保存先に在っても一時保存先へ出る。"""
    from tictok.core import layout
    from tictok.media.work import work_path

    src = layout.mp4_path(tmp_path / "final", "00042_someone_20260101_120000", "someone")
    assert work_path(src, 100.0, 515.0, 3).parent == layout.clips_dir(tmp_root, "someone")


def test_the_output_name_can_be_read_back(tmp_path):
    """成果物はDBに行を持たない。一覧が範囲もシーン数も名乗るには名前が唯一の手掛かり。"""
    from tictok.media.clipper import parse_clip_name
    from tictok.media.work import work_path

    src = tmp_path / "00042_someone_20260101_120000.mp4"
    out = work_path(src, 100.0, 515.0, 3, "作品の題")
    parsed = parse_clip_name(out.name)
    assert parsed is not None, out.name
    assert parsed["kind"] == "work"
    assert parsed["parts"] == 3
    assert parsed["start"] == 100.0
    assert parsed["end"] == 515.0
    assert parsed["label"] == "作品の題"


def test_a_reel_name_is_still_read_as_a_reel(tmp_path):
    """作品の印を足したせいで、素材の連結が別物として読まれないこと。"""
    from tictok.media.clipper import parse_clip_name
    from tictok.media.reel import reel_path

    src = tmp_path / "00042_someone_20260101_120000.mp4"
    parsed = parse_clip_name(reel_path(src, 10.0, 90.0, 4).name)
    assert parsed["kind"] == "reel"
    assert parsed["parts"] == 4


def test_the_work_api_refuses_a_group_that_has_no_scenes(client, server):
    storage = server.runtime.storage
    group = storage.add_group("空の棚")
    try:
        response = client.post(f"/api/groups/{group['id']}/work", json={})
        assert response.status_code == 422, response.text
        assert "尺のある見どころがありません" in response.json()["detail"]
    finally:
        storage.delete_group(group["id"])


def test_the_plan_shows_the_order_and_what_gets_burned_without_making_anything(
        client, server, group_with_cuts, presets):
    """生成は分単位。中身の確認を成果物で行うと、確認のcostが実行のcostと同じになる。"""
    preset = presets("下見用", subtitles=1, tighten=1)
    response = client.get(f"/api/groups/{group_with_cuts.group_id}/work-plan",
                          params={"preset_id": preset["id"]})
    assert response.status_code == 200, response.text
    plan = response.json()
    # 並びは position(=書き出し順)。時刻順に整えて見せると、実物と違う順を確認することになる。
    assert [s["start"] for s in plan["scenes"]] == [300.0, 100.0, 500.0]
    assert [s["position"] for s in plan["scenes"]] == [1, 2, 3]
    assert plan["requested_seconds"] == 65.0
    assert plan["burns"] == ["字幕"]
    assert plan["tighten"] is True
    # 素材もSessionも揃っているので止まる行は無い。
    assert plan["blocking"] == []
    # 何も作らないこと。下見のcostが実行と同じでは下見の意味が無い。
    assert not any(s["part_ready"] for s in plan["scenes"])


def test_the_plan_keeps_a_scene_whose_source_is_gone_as_a_row(client, server,
                                                              group_with_cuts, presets):
    """見つからない行を黙って除くと、件数だけが減って理由が誰にも分からない。

    見どころは録画へのFKを持つので、行が孤児になることはない。素材が消えるのは
    **fileだけが無くなる**形で起きる(録画の削除は行ごと消え、fileの掃除はDBを通らない)。
    """
    preset = presets("下見用2")
    group_with_cuts.path.unlink()
    plan = client.get(f"/api/groups/{group_with_cuts.group_id}/work-plan",
                      params={"preset_id": preset["id"]}).json()
    assert plan["scene_count"] == 3
    assert all(s["source_missing"] for s in plan["scenes"])
    # 押す前に止める行として名乗る。押した後にqueueで落ちるより先に出す。
    assert plan["blocking"] == [1, 2, 3]


def test_the_work_api_refuses_an_unknown_group(client):
    assert client.post("/api/groups/999999/work", json={}).status_code == 404


def test_the_work_api_enqueues_one_job_for_the_whole_group(client, server,
                                                           group_with_cuts, monkeypatch):
    """作品は1本の成果物なので、jobも1件。シーンごとに分けると途中まで出来た物が残る。"""
    enqueued: list = []

    async def fake_enqueue(kind, recording_id, **kwargs):
        enqueued.append({"kind": kind, "recording_id": recording_id, **kwargs})
        return {"job_id": "test", "kind": kind}

    monkeypatch.setattr(server.media_jobs, "_enqueue_media_job", fake_enqueue)
    response = client.post(f"/api/groups/{group_with_cuts.group_id}/work", json={})
    assert response.status_code == 200, response.text
    assert response.json()["scenes"] == 3
    assert len(enqueued) == 1
    assert enqueued[0]["kind"] == "work"
    # 代表recording_idは必ず入れる。NULLだとclaimのSQLが `NULL NOT IN (...)` になり、
    # 実行中のjobが在る間この行が拾われない。
    assert enqueued[0]["recording_id"] == group_with_cuts.recording_id
    assert enqueued[0]["params"]["group_id"] == group_with_cuts.group_id


@pytest.mark.asyncio
async def test_event_material_is_collected_once_per_recording(server, group_with_cuts,
                                                              monkeypatch):
    """同じ録画から3シーン採っても、3時間ぶんのevent読み出しは1回で済ませる。"""
    calls = {"material": 0}

    async def fake_material(recording, preset):
        calls["material"] += 1
        return {"settings": None, "started_at": 0.0, "ended_at": None,
                "events": [], "battles": [], "transcript": None}

    async def fake_make_work(scenes, *, preset, label=None, on_progress=None):
        assert len(scenes) == 3
        # 同じ録画のシーンは同じ材料を指していること(作り直した別objectではない)。
        assert scenes[0]["overlay"] is scenes[1]["overlay"] is scenes[2]["overlay"]
        return {"path": "out.mp4", "filename": "out.mp4", "bytes": 1, "scenes": 3,
                "requested_seconds": 65.0, "tightened_seconds": 0.0,
                "output_duration_seconds": 65.0, "preset_name": "型",
                "gate": {"ok": True, "failures": []}}

    monkeypatch.setattr(server.media_jobs, "_overlay_material", fake_material)
    monkeypatch.setattr(server.media_jobs.work_media, "make_work", fake_make_work)
    monkeypatch.setattr(server.media_jobs.short_media, "draws_anything", lambda p: True)
    monkeypatch.setattr(
        server.media_jobs, "_recording_for_output",
        lambda rid: ({"id": rid, "session_id": 1, "started_at": 0.0},
                     Path(group_with_cuts.path)))
    monkeypatch.setattr(
        server.media_jobs, "_short_preset", lambda params: {"id": 1, "name": "型"})

    async def report(stage, pct):
        return None

    result = await server.media_jobs._run_work_job(
        {"job_id": "j", "params": {"group_id": group_with_cuts.group_id}}, report)
    assert calls["material"] == 1
    assert result["scenes"] == 3
    # 使ったシーンには「書き出した」印が付く。作品のfileはDBに行を持たないため、次に同じ
    # グループを見たときに何が出済みかを言えるのはこの列だけである。
    cuts = server.runtime.storage.bookmarks_in_group(group_with_cuts.group_id)
    assert all(c["exported_path"] == "out.mp4" for c in cuts)
