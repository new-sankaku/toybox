import os
from pathlib import Path

import pytest

from tictok.core import layout
from tictok.core.cancel import JobCancelled
from tictok.record import disk_scan, retention
from tictok.record.media_queue import JobSkipped, MediaJobQueue, group_payload, job_payload
from tictok.record.transcribe_queue import TranscribeQueue

HOUR = 3600.0
DAY = 86400.0


# ===== helpers =====


def _row(job_id="j1", kind="overlay", state="pending", **extra):
    row = {
        "job_id": job_id,
        "kind": kind,
        "recording_id": 1,
        "session_id": 7,
        "group_id": "g1",
        "title": "配信タイトル",
        "state": state,
        "priority": 0,
        "queued_at": 100.0,
        "started_at": None,
        "finished_at": None,
        "pct": 0,
        "stage": "",
        "error": None,
        "result": {},
        "params": {},
    }
    row.update(extra)
    return row


@pytest.fixture
def recording_factory(tmp_db, tmp_root, make_session):
    """DBにrecording行を作り、実mp4もlayout規約の位置へ置く。"""
    counter = {"n": 0}

    def _make(unique_id="streamerA", status="completed", started_at=1000.0,
              ended_at=2000.0, size=1024, when="20260101_120000", write_file=True):
        counter["n"] += 1
        session_id = make_session(unique_id, status="connected")
        stem = f"{counter['n']:05d}_{unique_id}_{when}"
        mp4 = layout.mp4_path(tmp_root, stem, unique_id)
        mp4.parent.mkdir(parents=True, exist_ok=True)
        if write_file:
            mp4.write_bytes(b"\x00" * size)
        recording_id = tmp_db.create_recording(
            session_id, unique_id, str(mp4), mp4.name, "hd", started_at)
        tmp_db.update_recording(recording_id, status, str(mp4), mp4.name, ended_at, size)
        return tmp_db.get_recording(recording_id)

    return _make


def _resolve(recording):
    path = recording.get("path")
    return Path(path) if path else None


def _touch(path: Path, mtime: float, size: int = 8) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)
    os.utime(path, (mtime, mtime))
    return path


# ===== media_queue: payload合成 =====


def test_job_payload_maps_error_to_message_and_defaults_totals():
    payload = job_payload(_row(state="failed", error="ffmpeg failed", pct=None))
    assert payload["message"] == "ffmpeg failed"
    assert payload["pct"] == 0
    assert (payload["index"], payload["total"]) == (0, 1)
    assert payload["domain"] == "overlay"


def test_job_payload_started_at_falls_back_to_queued_at():
    payload = job_payload(_row(started_at=None, queued_at=42.0))
    assert payload["started_at"] == 42.0


def test_group_payload_none_for_empty_or_ungroupable_kind():
    assert group_payload([]) is None
    assert group_payload([_row(kind="reprocess")]) is None
    assert group_payload([_row(kind="upscale")])["domain"] == "session_upscale"


def test_group_payload_all_completed_reports_count_and_full_pct():
    rows = [_row(job_id=f"j{i}", state="completed", finished_at=200.0 + i) for i in range(3)]
    group = group_payload(rows)
    assert group["state"] == "completed"
    assert group["message"] == "3件の録画を出力しました"
    assert group["pct"] == 100
    assert (group["index"], group["total"]) == (3, 3)
    assert group["finished_at"] == 202.0


def test_group_payload_excludes_skipped_from_the_output_count():
    rows = [
        _row(job_id="a", state="completed"),
        _row(job_id="b", state="skipped", error="描く対象がありません"),
        _row(job_id="c", state="cancelled"),
    ]
    group = group_payload(rows)
    assert group["state"] == "completed"
    assert group["message"] == "1件の録画を出力しました"


def test_group_payload_failure_wins_over_cancelled_and_skipped():
    rows = [
        _row(job_id="a", state="cancelled"),
        _row(job_id="b", state="failed", error="disk full"),
        _row(job_id="c", state="skipped"),
    ]
    group = group_payload(rows)
    assert group["state"] == "failed"
    assert "1件" in group["message"] and "disk full" in group["message"]


def test_group_payload_interrupted_counts_as_failure_not_success():
    rows = [_row(job_id="a", state="completed"),
            _row(job_id="b", state="interrupted", error="server再起動")]
    assert group_payload(rows)["state"] == "failed"


def test_group_payload_all_cancelled_is_cancelled():
    rows = [_row(job_id="a", state="cancelled"), _row(job_id="b", state="cancelled")]
    group = group_payload(rows)
    assert group["state"] == "cancelled"
    assert group["message"] == "取り消しました。"


def test_group_payload_running_blends_finished_count_with_partial_pct():
    rows = [
        _row(job_id="a", state="completed"),
        _row(job_id="b", state="running", pct=50, stage="焼き込み"),
        _row(job_id="c", state="pending"),
        _row(job_id="d", state="pending"),
    ]
    group = group_payload(rows)
    assert group["state"] == "running"
    assert group["pct"] == (100 + 50) // 4
    assert group["index"] == 2
    assert group["stage"] == "(2/4) 焼き込み"


def test_group_payload_finished_at_is_none_while_nothing_finished():
    group = group_payload([_row(state="pending"), _row(job_id="b", state="pending")])
    assert group["finished_at"] is None
    assert group["started_at"] == 100.0


# ===== media_queue: worker =====


@pytest.fixture
def queue_factory(tmp_db, monkeypatch):
    monkeypatch.setenv("TICTOK_MEDIA_JOB_ATTEMPTS", "1")
    monkeypatch.setenv("TICTOK_MEDIA_JOB_RETRY_BACKOFF_SECONDS", "0")
    sent = []

    def _make(runner):
        async def broadcast(message):
            sent.append(message)

        return MediaJobQueue(tmp_db, broadcast, runner), sent

    return _make


async def test_enqueue_persists_pending_and_blocks_duplicate_via_pending_for(
        queue_factory, recording_factory):
    recording = recording_factory()

    async def runner(job, report):
        return {}

    queue, sent = queue_factory(runner)
    row = await queue.enqueue("job-1", "overlay", recording["id"], group_id="g")
    assert row["state"] == "pending"
    assert queue.pending_for("overlay", recording["id"])["job_id"] == "job-1"
    assert queue.pending_for("upscale", recording["id"]) is None
    assert [m["job"]["job_id"] for m in sent if m["job"]["domain"] == "overlay"] == ["job-1"]


async def test_cancel_pending_marks_cancelled_and_second_cancel_reports_finished(
        queue_factory, recording_factory, tmp_db):
    recording = recording_factory()

    async def runner(job, report):
        return {}

    queue, _ = queue_factory(runner)
    await queue.enqueue("job-1", "overlay", recording["id"])
    assert await queue.cancel("job-1") == "cancelled"
    assert tmp_db.get_media_job("job-1")["state"] == "cancelled"
    assert await queue.cancel("job-1") == "finished"
    assert await queue.cancel("nope") == "missing"


async def test_cancel_running_reprocess_is_refused_not_silently_accepted(
        queue_factory, recording_factory, tmp_db):
    recording = recording_factory()

    async def runner(job, report):
        return {}

    queue, _ = queue_factory(runner)
    await queue.enqueue("job-1", "reprocess", recording["id"])
    tmp_db.start_media_job("job-1")
    assert await queue.cancel("job-1") == "unsupported"
    assert tmp_db.get_media_job("job-1")["state"] == "running"


async def test_cancel_running_row_without_token_does_not_rewrite_state(
        queue_factory, recording_factory, tmp_db):
    """前回processの残骸(running行)をcancelしても、stateを勝手に触らない。"""
    recording = recording_factory()

    async def runner(job, report):
        return {}

    queue, _ = queue_factory(runner)
    await queue.enqueue("job-1", "overlay", recording["id"])
    tmp_db.start_media_job("job-1")
    assert await queue.cancel("job-1") == "missing"
    assert tmp_db.get_media_job("job-1")["state"] == "running"


async def test_process_completed_stores_runner_result_and_full_pct(
        queue_factory, recording_factory, tmp_db):
    recording = recording_factory()

    async def runner(job, report):
        await report("焼き込み", 40)
        return {"output": "x.overlay.mp4"}

    queue, _ = queue_factory(runner)
    job = await queue.enqueue("job-1", "overlay", recording["id"])
    await queue._process(tmp_db.get_media_job(job["job_id"]))
    stored = tmp_db.get_media_job("job-1")
    assert stored["state"] == "completed"
    assert stored["pct"] == 100
    assert stored["result"] == {"output": "x.overlay.mp4"}
    assert stored["stage"] == ""


async def test_process_skipped_is_not_a_failure(queue_factory, recording_factory, tmp_db):
    recording = recording_factory()

    async def runner(job, report):
        raise JobSkipped("描く対象のコメントがありません。")

    queue, _ = queue_factory(runner)
    await queue.enqueue("job-1", "overlay", recording["id"])
    await queue._process(tmp_db.get_media_job("job-1"))
    stored = tmp_db.get_media_job("job-1")
    assert stored["state"] == "skipped"
    assert stored["error"] == "描く対象のコメントがありません。"


async def test_process_prefers_http_detail_over_str_for_the_user_message(
        queue_factory, recording_factory, tmp_db):
    recording = recording_factory()

    class Detailed(Exception):
        detail = "録画fileが見つかりません。"

    async def runner(job, report):
        raise Detailed("internal repr")

    queue, _ = queue_factory(runner)
    await queue.enqueue("job-1", "overlay", recording["id"])
    await queue._process(tmp_db.get_media_job("job-1"))
    assert tmp_db.get_media_job("job-1")["error"] == "録画fileが見つかりません。"


async def test_process_cancelled_token_lands_as_cancelled_state(
        queue_factory, recording_factory, tmp_db):
    recording = recording_factory()

    async def runner(job, report):
        raise JobCancelled(job["job_id"])

    queue, _ = queue_factory(runner)
    await queue.enqueue("job-1", "overlay", recording["id"])
    await queue._process(tmp_db.get_media_job("job-1"))
    stored = tmp_db.get_media_job("job-1")
    assert stored["state"] == "cancelled"
    assert stored["error"] == "取り消しました。"


async def test_transient_failure_is_retried_then_succeeds(
        queue_factory, recording_factory, tmp_db, monkeypatch):
    monkeypatch.setenv("TICTOK_MEDIA_JOB_ATTEMPTS", "3")
    recording = recording_factory()
    calls = []

    async def runner(job, report):
        calls.append(1)
        if len(calls) < 3:
            raise OSError("file locked")
        return {"ok": True}

    queue, _ = queue_factory(runner)
    await queue.enqueue("job-1", "overlay", recording["id"])
    await queue._process(tmp_db.get_media_job("job-1"))
    assert len(calls) == 3
    assert tmp_db.get_media_job("job-1")["state"] == "completed"


async def test_skipped_and_cancelled_are_never_retried(
        queue_factory, recording_factory, tmp_db, monkeypatch):
    monkeypatch.setenv("TICTOK_MEDIA_JOB_ATTEMPTS", "5")
    recording = recording_factory()
    calls = []

    async def runner(job, report):
        calls.append(1)
        raise JobSkipped("対象なし")

    queue, _ = queue_factory(runner)
    await queue.enqueue("job-1", "overlay", recording["id"])
    await queue._process(tmp_db.get_media_job("job-1"))
    assert len(calls) == 1


async def test_repeated_identical_progress_is_collapsed(
        queue_factory, recording_factory, tmp_db):
    recording = recording_factory()

    async def runner(job, report):
        for _ in range(5):
            await report("焼き込み", 30)
        await report("焼き込み", 31)
        return {}

    queue, sent = queue_factory(runner)
    await queue.enqueue("job-1", "overlay", recording["id"])
    sent.clear()
    await queue._process(tmp_db.get_media_job("job-1"))
    stages = [m["job"]["stage"] for m in sent if m["job"]["domain"] == "overlay"]
    assert stages.count("焼き込み") == 2


async def test_list_jobs_adds_one_folded_row_per_group(
        queue_factory, recording_factory, tmp_db):
    a = recording_factory()
    b = recording_factory()

    async def runner(job, report):
        return {}

    queue, _ = queue_factory(runner)
    await queue.enqueue("job-a", "overlay", a["id"], group_id="grp", session_id=a["session_id"])
    await queue.enqueue("job-b", "overlay", b["id"], group_id="grp", session_id=b["session_id"])
    await queue.enqueue("job-c", "upscale", a["id"])
    payloads = queue.list_jobs()
    domains = sorted(p["domain"] for p in payloads)
    assert domains == ["overlay", "overlay", "session_overlay", "upscale"]
    folded = next(p for p in payloads if p["domain"] == "session_overlay")
    assert folded["total"] == 2 and folded["job_id"] == "grp"


# ===== retention =====


def test_source_phase_never_lists_protected_or_in_progress_recordings(recording_factory):
    now = 10 * DAY
    keep_protected = recording_factory(ended_at=1.0)
    keep_protected["protected"] = 1
    keep_recording = recording_factory(status="recording", ended_at=1.0)
    droppable = recording_factory(ended_at=1.0)
    items = retention.source_candidates(
        [keep_protected, keep_recording, droppable], _resolve, DAY, now)
    assert [i["recording_id"] for i in items] == [droppable["id"]]


def test_source_phase_skips_rows_whose_path_is_not_a_file(recording_factory, tmp_root):
    now = 10 * DAY
    ghost = recording_factory(write_file=False, ended_at=1.0)
    directory = recording_factory(ended_at=1.0)
    Path(directory["path"]).unlink()
    Path(directory["path"]).mkdir()
    assert retention.source_candidates([ghost, directory], _resolve, DAY, now) == []


def test_source_phase_uses_mtime_when_ended_at_is_missing(recording_factory):
    """完了time刻が無い録画を0扱いすると『無限に古い』となり最優先で消える。"""
    now = 10 * DAY
    interrupted = recording_factory(status="interrupted", ended_at=None)
    _touch(Path(interrupted["path"]), now - 60.0)
    assert retention.source_candidates([interrupted], _resolve, DAY, now) == []
    old = retention.source_candidates([interrupted], _resolve, 30.0, now)
    assert [i["recording_id"] for i in old] == [interrupted["id"]]


def test_source_phase_bytes_include_the_derived_files_that_go_with_it(recording_factory):
    from tictok.record.upscale import upscale_artifact_paths
    from tictok.record.video_overlay import overlay_artifact_paths

    now = 10 * DAY
    recording = recording_factory(ended_at=1.0, size=100)
    src = Path(recording["path"])
    _touch(overlay_artifact_paths(src)[0], now, size=30)
    _touch(upscale_artifact_paths(src)[0], now, size=20)
    item = retention.source_candidates([recording], _resolve, DAY, now)[0]
    assert item["bytes"] == 150
    assert item["files"] == 3


def test_source_phase_orders_oldest_first(recording_factory):
    now = 100 * DAY
    older = recording_factory(ended_at=DAY)
    newer = recording_factory(ended_at=50 * DAY)
    items = retention.source_candidates([newer, older], _resolve, DAY, now)
    assert [i["recording_id"] for i in items] == [older["id"], newer["id"]]


def test_derived_phase_ages_on_the_derived_file_not_the_recording(recording_factory):
    from tictok.record.video_overlay import overlay_artifact_paths

    now = 100 * DAY
    recording = recording_factory(ended_at=DAY)
    fresh = _touch(overlay_artifact_paths(Path(recording["path"]))[0], now - HOUR, size=7)
    assert fresh.is_file()
    assert retention.derived_candidates([recording], _resolve, 7 * DAY, now) == []
    os.utime(fresh, (now - 30 * DAY, now - 30 * DAY))
    items = retention.derived_candidates([recording], _resolve, 7 * DAY, now)
    assert [i["recording_id"] for i in items] == [recording["id"]]
    assert items[0]["bytes"] == 7


def test_derived_phase_skips_protected_and_recordings_without_derived_files(recording_factory):
    from tictok.record.video_overlay import overlay_artifact_paths

    now = 100 * DAY
    protected = recording_factory(ended_at=DAY)
    protected["protected"] = 1
    _touch(overlay_artifact_paths(Path(protected["path"]))[0], DAY)
    bare = recording_factory(ended_at=DAY)
    assert retention.derived_candidates([protected, bare], _resolve, DAY, now) == []


def test_derived_phase_never_lists_a_recording_still_running(recording_factory):
    """録画中の録画の派生物は他phaseと同様に対象外(phase間で保護を揃える)。"""
    from tictok.record.video_overlay import overlay_artifact_paths

    now = 100 * DAY
    running = recording_factory(status="recording", ended_at=None)
    _touch(overlay_artifact_paths(Path(running["path"]))[0], now - 30 * DAY, size=7)
    assert retention.derived_candidates([running], _resolve, DAY, now) == []


def test_derived_phase_keeps_artifacts_whose_source_mp4_is_gone(recording_factory):
    """元mp4が消えた派生物は作り直せない最後の1本なので、②では絶対に候補にしない。"""
    from tictok.record.upscale import upscale_artifact_paths
    from tictok.record.video_overlay import overlay_artifact_paths

    now = 100 * DAY
    recording = recording_factory(ended_at=DAY)
    src = Path(recording["path"])
    overlay = _touch(overlay_artifact_paths(src)[0], now - 30 * DAY, size=7)
    up = _touch(upscale_artifact_paths(src)[0], now - 30 * DAY, size=7)
    src.unlink()
    assert retention.derived_candidates([recording], _resolve, DAY, now) == []
    assert overlay.is_file() and up.is_file()


def test_source_phase_treats_zero_ended_at_as_missing_not_as_1970(recording_factory):
    """ended_at=0.0 を実値として扱うと『無限に古い』となり最優先で消える側に回る。"""
    now = 100 * DAY
    recording = recording_factory(ended_at=0.0)
    _touch(Path(recording["path"]), now - 60.0)
    assert retention.source_candidates([recording], _resolve, DAY, now) == []


def test_transient_phase_takes_sidecar_intermediates_but_not_finished_output(
        recording_factory, tmp_root):
    from tictok.record.video_overlay import overlay_artifact_paths, overlay_transient_paths

    now = 100 * DAY
    recording = recording_factory(ended_at=DAY)
    src = Path(recording["path"])
    cfrbase = _touch(overlay_transient_paths(src)[1], now - 10 * HOUR)
    overlay_mp4, overlay_ass = overlay_artifact_paths(src)[0], overlay_artifact_paths(src)[1]
    _touch(overlay_mp4, now - 10 * HOUR)
    _touch(overlay_ass, now - 10 * HOUR)
    items = retention.transient_candidates(
        [tmp_root], [recording], _resolve, HOUR, now)
    assert [i["path"] for i in items] == [str(cfrbase)]
    assert overlay_mp4.is_file() and src.is_file()


def test_transient_phase_leaves_files_younger_than_the_threshold_alone(
        recording_factory, tmp_root):
    from tictok.record.video_overlay import overlay_transient_paths

    now = 100 * DAY
    recording = recording_factory(ended_at=DAY)
    _touch(overlay_transient_paths(Path(recording["path"]))[1], now - 60.0)
    assert retention.transient_candidates([tmp_root], [recording], _resolve, HOUR, now) == []


def test_transient_phase_finds_the_normalize_tmp_next_to_the_mp4(
        recording_factory, tmp_root):
    from tictok.record.recorder import NORMALIZE_TMP_SUFFIX

    now = 100 * DAY
    recording = recording_factory(ended_at=DAY)
    src = Path(recording["path"])
    tmp = _touch(src.with_suffix(src.suffix + NORMALIZE_TMP_SUFFIX), now - 10 * HOUR)
    items = retention.transient_candidates(
        [tmp_root, tmp_root], [recording], _resolve, HOUR, now)
    assert [i["path"] for i in items] == [str(tmp)]
    assert items[0]["recording_id"] == recording["id"]


def test_transient_phase_ignores_recordings_still_running(recording_factory, tmp_root):
    from tictok.record.recorder import NORMALIZE_TMP_SUFFIX

    now = 100 * DAY
    recording = recording_factory(status="recording", ended_at=None)
    src = Path(recording["path"])
    _touch(src.with_suffix(src.suffix + NORMALIZE_TMP_SUFFIX), now - 10 * HOUR)
    assert retention.transient_candidates([tmp_root], [recording], _resolve, HOUR, now) == []


def test_build_plan_keeps_phase_order_and_explains_disabled_phases(recording_factory, tmp_root):
    now = 100 * DAY
    recording = recording_factory(ended_at=DAY)
    plan = retention.build_plan(
        [recording], [tmp_root], _resolve,
        {"transient_hours": 0, "derived_days": 0, "source_days": 30,
         "source_enabled": False},
        now)
    assert [p["phase"] for p in plan["phases"]] == list(retention.PHASE_ORDER)
    assert [p["enabled"] for p in plan["phases"]] == [False, False, False]
    assert all(p["reason"] and p["items"] == [] for p in plan["phases"])
    assert plan["total_items"] == 0 and plan["total_bytes"] == 0


def test_build_plan_source_needs_both_the_flag_and_a_positive_window(recording_factory,
                                                                    tmp_root):
    now = 100 * DAY
    recording = recording_factory(ended_at=DAY)
    rules = {"transient_hours": 1, "derived_days": 1, "source_days": 0,
             "source_enabled": True}
    source = retention.build_plan([recording], [tmp_root], _resolve, rules, now)["phases"][2]
    assert source["enabled"] is False and "0" in source["reason"]

    rules["source_days"] = 1
    plan = retention.build_plan([recording], [tmp_root], _resolve, rules, now)
    source = plan["phases"][2]
    assert source["enabled"] is True
    assert [i["recording_id"] for i in source["items"]] == [recording["id"]]
    assert plan["total_bytes"] == source["bytes"]


def test_artifact_bytes_counts_only_files_that_exist(tmp_root):
    present = _touch(tmp_root / "a.bin", 0.0, size=12)
    assert retention.artifact_bytes([present, tmp_root / "missing.bin"]) == 12


# ===== disk_scan =====


@pytest.mark.parametrize("name,expected", [
    ("00001_a_20260101_120000.mp4", disk_scan.CATEGORY_SOURCE),
    ("00001_a_20260101_120000.overlay.mp4", disk_scan.CATEGORY_OVERLAY),
    ("00001_a_20260101_120000.overlay.b.mp4", disk_scan.CATEGORY_OVERLAY),
    ("00001_a_20260101_120000.up.mp4", disk_scan.CATEGORY_UPSCALE),
    ("00001_a_20260101_120000.overlay.up.mp4", disk_scan.CATEGORY_UPSCALE),
    ("00001_a_20260101_120000.overlay.cfrbase.mp4", disk_scan.CATEGORY_TRANSIENT),
    ("00001_a_20260101_120000.preview.cfrbase.mp4", disk_scan.CATEGORY_TRANSIENT),
    ("00001_a_20260101_120000.preview.mp4", disk_scan.CATEGORY_OVERLAY),
    ("00001_a_20260101_120000.mp4.norm.tmp", disk_scan.CATEGORY_TRANSIENT),
    ("00001_a_20260101_120000.mp4.norm.tmp.ffmpeg.log", disk_scan.CATEGORY_TRANSIENT),
])
def test_classify_resolves_multi_suffix_names_to_the_right_category(name, expected):
    category, streamer = disk_scan.classify(("a", "mp4"), name)
    assert category == expected
    assert streamer == "a"


def test_classify_attributes_shared_dir_artifacts_back_to_their_streamer():
    category, streamer = disk_scan.classify(
        (".sidecars",), "00042_stream.er_1_20250101_120000.overlay.b.ass")
    assert category == disk_scan.CATEGORY_OVERLAY
    assert streamer == "stream.er_1"


def test_classify_keeps_unattributable_cache_in_the_shared_bucket():
    assert disk_scan.classify(("avatars",), "abc123.jpg") == (
        disk_scan.CATEGORY_AVATAR, disk_scan.SHARED_STREAMER_KEY)
    assert disk_scan.classify((), "stray.txt") == (
        disk_scan.CATEGORY_OTHER, disk_scan.SHARED_STREAMER_KEY)


def test_classify_ts_segments_are_hls_not_other():
    category, streamer = disk_scan.classify(
        ("a", "ts", "00001_a_20260101_120000"), "seg00001.ts")
    assert (category, streamer) == (disk_scan.CATEGORY_HLS, "a")


def test_scan_roots_dedupes_repeated_roots_and_reports_missing_ones(tmp_root):
    _touch(tmp_root / "a" / "mp4" / "00001_a_20260101_120000.mp4", 0.0, size=100)
    _touch(tmp_root / "a" / "ts" / "00001_a_20260101_120000" / "seg0.ts", 0.0, size=10)
    _touch(tmp_root / ".sidecars" / "00001_a_20260101_120000.overlay.meta", 0.0, size=5)
    missing = tmp_root / "nope"

    result = disk_scan.scan_roots([tmp_root, tmp_root, missing])
    assert result["roots"] == [str(tmp_root.resolve())]
    assert [e["path"] for e in result["errors"]] == [str(missing.resolve())]
    assert result["total_bytes"] == 115
    assert result["total_files"] == 3
    assert result["categories"][disk_scan.CATEGORY_SOURCE] == {"bytes": 100, "files": 1}
    streamer_a = next(s for s in result["streamers"] if s["streamer"] == "a")
    assert streamer_a["bytes"] == 115
    assert set(streamer_a["categories"]) == {
        disk_scan.CATEGORY_SOURCE, disk_scan.CATEGORY_HLS, disk_scan.CATEGORY_OVERLAY}


def test_scan_roots_labels_the_shared_bucket_and_sorts_streamers_by_size(tmp_root):
    _touch(tmp_root / "a" / "mp4" / "00001_a_20260101_120000.mp4", 0.0, size=10)
    _touch(tmp_root / "bb" / "mp4" / "00002_bb_20260101_120000.mp4", 0.0, size=500)
    _touch(tmp_root / "avatars" / "x.jpg", 0.0, size=50)

    result = disk_scan.scan_roots([tmp_root])
    assert [s["streamer"] for s in result["streamers"]] == [
        "bb", disk_scan.SHARED_STREAMER_KEY, "a"]
    shared = result["streamers"][1]
    assert shared["label"] == disk_scan.SHARED_STREAMER_LABEL
    assert disk_scan.CATEGORY_SOURCE not in disk_scan.REGENERABLE_CATEGORIES


# ===== transcribe_queue =====


@pytest.fixture
def stt_queue(tmp_db, monkeypatch):
    monkeypatch.setattr("tictok.record.transcribe_queue.stt_available", lambda: True)
    sent = []

    async def broadcast(message):
        sent.append(message)

    queue = TranscribeQueue(tmp_db, broadcast, lambda path: Path(path))
    return queue, sent


def test_enqueue_streamer_only_takes_completed_untranscribed_recordings_of_that_streamer(
        stt_queue, recording_factory):
    queue, _ = stt_queue
    mine = recording_factory(unique_id="streamerA")
    recording_factory(unique_id="streamerB")
    recording_factory(unique_id="streamerA", status="recording")

    result = queue.enqueue_streamer("streamerA")
    assert result == {"added": 1, "candidates": 1}
    items = queue.status()["items"]
    assert [i["recording_id"] for i in items] == [mine["id"]]


def test_enqueue_streamer_is_idempotent_while_the_row_is_still_pending(
        stt_queue, recording_factory):
    queue, _ = stt_queue
    recording_factory(unique_id="streamerA")
    assert queue.enqueue_streamer("streamerA")["added"] == 1
    assert queue.enqueue_streamer("streamerA") == {"added": 0, "candidates": 0}


def test_enqueue_recordings_rejects_an_unknown_id_before_touching_the_queue(
        stt_queue, recording_factory):
    queue, _ = stt_queue
    recording = recording_factory()
    with pytest.raises(ValueError):
        queue.enqueue_recordings([recording["id"], 999999])
    assert queue.status()["items"] == []


def test_cancel_only_removes_pending_work(stt_queue, recording_factory, tmp_db):
    queue, _ = stt_queue
    a = recording_factory()
    b = recording_factory()
    queue.enqueue_recordings([a["id"], b["id"]])
    tmp_db.set_transcription_state(a["id"], "running")

    assert queue.cancel() == 1
    states = {i["recording_id"]: i["state"] for i in queue.status()["items"]}
    assert states == {a["id"]: "running", b["id"]: "cancelled"}


def test_status_counts_by_state_and_reports_the_running_recording(
        stt_queue, recording_factory, tmp_db):
    queue, _ = stt_queue
    a = recording_factory()
    b = recording_factory()
    queue.enqueue_recordings([a["id"], b["id"]])
    tmp_db.set_transcription_state(a["id"], "running")
    queue._current = a["id"]

    status = queue.status()
    assert status["available"] is True
    assert status["running"] == a["id"]
    assert status["counts"] == {"running": 1, "pending": 1}


async def test_process_marks_a_missing_media_file_failed_without_calling_stt(
        stt_queue, recording_factory, tmp_db, monkeypatch):
    queue, sent = stt_queue

    def explode(*args, **kwargs):
        raise AssertionError("STT must not run for a missing file")

    monkeypatch.setattr("tictok.record.transcribe_queue.stt_transcribe", explode)
    recording = recording_factory(write_file=False)
    queue.enqueue_recordings([recording["id"]])

    await queue._process(tmp_db.next_pending_transcription())
    item = queue.status()["items"][0]
    assert item["state"] == "failed"
    assert item["error"] == "録画fileが存在しません。"
    assert sent and sent[-1]["type"] == "transcribe_queue"


async def test_process_marks_a_deleted_recording_row_failed(stt_queue, tmp_db):
    queue, _ = stt_queue
    await queue._process({"recording_id": 424242})
    assert queue.status()["items"] == []


async def test_transcribe_retries_a_transient_failure_then_succeeds(
        stt_queue, recording_factory, tmp_db, monkeypatch):
    queue, _ = stt_queue
    monkeypatch.setenv("TICTOK_TRANSCRIBE_JOB_ATTEMPTS", "3")
    monkeypatch.setenv("TICTOK_TRANSCRIBE_JOB_RETRY_BACKOFF_SECONDS", "0")
    calls = []

    def flaky(path, on_progress):
        calls.append(path)
        if len(calls) < 3:
            raise RuntimeError("CUDA out of memory")
        return {"text": "ok", "segments": []}

    monkeypatch.setattr("tictok.record.transcribe_queue.stt_transcribe", flaky)
    result = await queue._transcribe_with_retry(1, Path("x.mp4"), lambda d, t: None)
    assert len(calls) == 3
    assert result["text"] == "ok"


async def test_transcribe_gives_up_after_the_configured_attempts(
        stt_queue, monkeypatch):
    queue, _ = stt_queue
    monkeypatch.setenv("TICTOK_TRANSCRIBE_JOB_ATTEMPTS", "2")
    monkeypatch.setenv("TICTOK_TRANSCRIBE_JOB_RETRY_BACKOFF_SECONDS", "0")
    calls = []

    def always_fails(path, on_progress):
        calls.append(path)
        raise RuntimeError("no model")

    monkeypatch.setattr("tictok.record.transcribe_queue.stt_transcribe", always_fails)
    with pytest.raises(RuntimeError):
        await queue._transcribe_with_retry(1, Path("x.mp4"), lambda d, t: None)
    assert len(calls) == 2
