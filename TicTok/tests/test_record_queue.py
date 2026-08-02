import json
import os
import time
from pathlib import Path

import pytest

from tictok.core import layout
from tictok.core.cancel import CancelToken, JobCancelled
from tictok.record import disk_scan, retention
from tictok.record.media_queue import (
    JobDeferred,
    JobSkipped,
    MediaJobQueue,
    group_payload,
    job_payload,
)
from tictok.record.recorder import timing_path as recorder_timing_path

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


async def test_cancel_running_job_requests_interruption(
        queue_factory, recording_factory, tmp_db):
    """workerが掴んでいる実行中jobのcancelはtokenを倒す中断要求として通る。
    stateはrunningのまま — 実際に止まったのはrunner側が畳んでから書く。"""
    recording = recording_factory()

    async def runner(job, report):
        return {}

    queue, _ = queue_factory(runner)
    await queue.enqueue("job-1", "reprocess", recording["id"])
    tmp_db.start_media_job("job-1")
    token = CancelToken("job-1")
    queue._tokens["job-1"] = token
    assert await queue.cancel("job-1") == "cancelling"
    assert token.cancelled
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


async def test_deferred_job_returns_to_the_queue_without_failing(
        queue_factory, recording_factory, tmp_db, monkeypatch):
    """保存先volumeの不在は失敗ではない。attemptを食わず、待機へ戻して自分で再開する。"""
    monkeypatch.setenv("TICTOK_MEDIA_JOB_ATTEMPTS", "5")
    recording = recording_factory()
    calls = []

    async def runner(job, report):
        calls.append(1)
        raise JobDeferred("保存先が見つかりません（K:）。")

    queue, _ = queue_factory(runner)
    await queue.enqueue("job-1", "reprocess", recording["id"])
    await queue._process(tmp_db.get_media_job("job-1"))

    stored = tmp_db.get_media_job("job-1")
    assert len(calls) == 1                      # retryで潰さない
    assert stored["state"] == "pending"
    assert stored["finished_at"] is None
    assert stored["not_before"] > time.time()
    assert "保存先が見つかりません" in stored["stage"]


async def test_deferred_job_is_not_claimed_until_its_wait_elapses(
        queue_factory, recording_factory, tmp_db):
    """待機へ戻した直後に同じworkerが拾い直すと、待つ意味が無くなる。"""
    recording = recording_factory()

    async def runner(job, report):
        raise JobDeferred("保存先が見つかりません（K:）。")

    queue, _ = queue_factory(runner)
    await queue.enqueue("job-1", "reprocess", recording["id"])
    await queue._process(tmp_db.get_media_job("job-1"))

    assert tmp_db.claim_next_pending_media_job() is None
    tmp_db.defer_media_job("job-1", time.time() - 1, "復帰待ち")
    assert tmp_db.claim_next_pending_media_job()["job_id"] == "job-1"


async def test_deferred_job_fails_once_it_has_waited_too_long(
        queue_factory, recording_factory, tmp_db, monkeypatch):
    """待ち続けるqueueは、動いているように見えて何も進まない。上限で失敗へ倒す。"""
    monkeypatch.setenv("TICTOK_MEDIA_JOB_DEFER_TIMEOUT_SECONDS", "60")
    recording = recording_factory()

    async def runner(job, report):
        raise JobDeferred("保存先が見つかりません（K:）。")

    queue, _ = queue_factory(runner)
    await queue.enqueue("job-1", "reprocess", recording["id"])
    await queue._process(tmp_db.get_media_job("job-1"))
    # 61分前から待っていたことにする
    tmp_db.defer_media_job("job-1", time.time(), "復帰待ち")
    with tmp_db._lock:
        tmp_db._conn.execute(
            "UPDATE media_job_queue SET deferred_since = ? WHERE job_id = ?",
            (time.time() - 3600, "job-1"))
        tmp_db._conn.commit()
    await queue._process(tmp_db.get_media_job("job-1"))

    stored = tmp_db.get_media_job("job-1")
    assert stored["state"] == "failed"
    assert "解消しませんでした" in stored["error"]


async def test_requeue_returns_failed_members_to_the_same_group(
        queue_factory, recording_factory, tmp_db):
    """一括の失敗ぶんは同じ行を戻す。新規行を足すとgroupの母数が増え、完了に到達しない。"""
    a, b = recording_factory(), recording_factory()

    async def runner(job, report):
        if job["recording_id"] == b["id"]:
            raise OSError("boom")
        return {}

    queue, _ = queue_factory(runner)
    await queue.enqueue("job-a", "reprocess", a["id"], group_id="grp")
    await queue.enqueue("job-b", "reprocess", b["id"], group_id="grp")
    await queue._process(tmp_db.get_media_job("job-a"))
    await queue._process(tmp_db.get_media_job("job-b"))
    assert tmp_db.get_media_job("job-b")["state"] == "failed"

    assert await queue.requeue(["job-a", "job-b"]) == 1      # 完了ぶんは戻さない
    assert tmp_db.get_media_job("job-b")["state"] == "pending"
    assert tmp_db.get_media_job("job-b")["error"] is None
    assert tmp_db.get_media_job("job-a")["state"] == "completed"
    assert len(tmp_db.media_jobs_in_group("grp")) == 2


async def test_finished_group_with_failures_leaves_one_ops_event(
        queue_factory, recording_factory, tmp_db):
    """一括は投げて寝る使い方なので、Job画面を開いていなくても欠落が残る場所が要る。"""
    a, b = recording_factory(), recording_factory()

    async def runner(job, report):
        if job["recording_id"] == b["id"]:
            raise OSError("boom")
        return {}

    queue, _ = queue_factory(runner)
    await queue.enqueue("job-a", "reprocess", a["id"], group_id="grp")
    await queue.enqueue("job-b", "reprocess", b["id"], group_id="grp")
    await queue._process(tmp_db.get_media_job("job-a"))
    await queue._process(tmp_db.get_media_job("job-b"))

    events = [e for e in tmp_db.list_ops_events(limit=50)
              if e["kind"] == "media_queue.group_finished"]
    assert len(events) == 1
    assert events[0]["severity"] == "warning"
    assert events[0]["detail"]["failed"] == 1
    assert events[0]["detail"]["failed_job_ids"] == ["job-b"]


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


def test_transient_phase_spares_a_normalize_tmp_that_completed(recording_factory, tmp_root):
    """完了印付きの .norm.tmp は『中断した残骸』ではなく『直ったが当てられなかった成果物』。

    これを消すと、混在解像度の壊れたmp4が残って直った方が消える。実際に一度その形で
    再生カクつきが再発している(差し替えがlockで失敗し、掃除が完成品を消す側に回った)。"""
    from tictok.record.recorder import normalize_marker_path, normalize_tmp_path

    now = 100 * DAY
    recording = recording_factory(ended_at=DAY)
    src = Path(recording["path"])
    tmp = _touch(normalize_tmp_path(src), now - 10 * HOUR)
    normalize_marker_path(tmp).write_text('{"timing_mode": "passthrough"}', encoding="utf-8")
    assert retention.transient_candidates([tmp_root], [recording], _resolve, HOUR, now) == []
    assert tmp.is_file()


def test_transient_phase_ignores_recordings_still_running(recording_factory, tmp_root):
    from tictok.record.recorder import NORMALIZE_TMP_SUFFIX

    now = 100 * DAY
    recording = recording_factory(status="recording", ended_at=None)
    src = Path(recording["path"])
    _touch(src.with_suffix(src.suffix + NORMALIZE_TMP_SUFFIX), now - 10 * HOUR)
    assert retention.transient_candidates([tmp_root], [recording], _resolve, HOUR, now) == []


# --------------------------------------------------------------------------
# 混在解像度normalizeの再回収(差し替えがlockで失敗した成果物の救済)
# --------------------------------------------------------------------------


async def test_reclaim_swaps_a_completed_normalization_into_place(recording_factory, monkeypatch):
    """再encodeは終わったのにos.replaceだけがlockで落ちた録画を、後から当て直せること。"""
    from tictok.record import recorder

    recording = recording_factory(ended_at=DAY)
    mp4 = Path(recording["path"])
    mp4.write_bytes(b"mixed")
    tmp = recorder.normalize_tmp_path(mp4)
    tmp.write_bytes(b"normalized")
    recorder.normalize_marker_path(tmp).write_text(
        '{"timing_mode": "passthrough", "width": 720, "height": 1280}', encoding="utf-8")
    monkeypatch.setattr(recorder, "probe_mp4_resolutions", _fake_probe({(720, 1280)}))

    assert await recorder.reclaim_normalized_mp4(mp4) == "reclaimed"
    assert mp4.read_bytes() == b"normalized"
    assert not tmp.exists()
    assert not recorder.normalize_marker_path(tmp).exists()


async def test_reclaim_refuses_a_leftover_that_is_still_mixed_resolution(
        recording_factory, monkeypatch):
    """印が付いていても実fileが単一解像度でなければ当てない。壊れた物を壊れた物で
    置き換えるくらいなら、両方残して人間に判断させる。"""
    from tictok.record import recorder

    recording = recording_factory(ended_at=DAY)
    mp4 = Path(recording["path"])
    mp4.write_bytes(b"mixed")
    tmp = recorder.normalize_tmp_path(mp4)
    tmp.write_bytes(b"truncated")
    recorder.normalize_marker_path(tmp).write_text('{"timing_mode": "passthrough"}', encoding="utf-8")
    monkeypatch.setattr(recorder, "probe_mp4_resolutions",
                        _fake_probe({(640, 1280), (720, 1280)}))

    assert await recorder.reclaim_normalized_mp4(mp4) == "invalid"
    assert mp4.read_bytes() == b"mixed"
    assert tmp.is_file()


async def test_reclaim_drops_the_timing_map_only_for_a_cfr_reencode(
        recording_factory, monkeypatch):
    """CFRへ落ちた再encodeはframe timelineを作り直すので、media->pts mapは捨てる。
    passthroughでは残す(消すと焼き込みのコメント同期が近似へ劣化する)。"""
    from tictok.record import recorder

    monkeypatch.setattr(recorder, "probe_mp4_resolutions", _fake_probe({(720, 1280)}))
    for timing_mode, map_survives in (("passthrough", True), ("cfr", False)):
        recording = recording_factory(ended_at=DAY)
        mp4 = Path(recording["path"])
        mp4.write_bytes(b"mixed")
        tmp = recorder.normalize_tmp_path(mp4)
        tmp.write_bytes(b"normalized")
        recorder.normalize_marker_path(tmp).write_text(
            json.dumps({"timing_mode": timing_mode}), encoding="utf-8")
        timing = recorder.timing_path(mp4)
        timing.parent.mkdir(parents=True, exist_ok=True)
        timing.write_text("{}", encoding="utf-8")

        assert await recorder.reclaim_normalized_mp4(mp4) == "reclaimed"
        assert timing.is_file() is map_survives


async def test_reclaim_is_a_noop_without_a_completion_marker(recording_factory):
    """印の無い .norm.tmp は中断した中間file。当ててはいけない(掃除側の担当)。"""
    from tictok.record import recorder

    recording = recording_factory(ended_at=DAY)
    mp4 = Path(recording["path"])
    mp4.write_bytes(b"mixed")
    tmp = recorder.normalize_tmp_path(mp4)
    tmp.write_bytes(b"half-written")

    assert await recorder.reclaim_normalized_mp4(mp4) == "none"
    assert mp4.read_bytes() == b"mixed"
    assert tmp.is_file()


async def test_reclaim_clears_a_marker_whose_tmp_is_gone(recording_factory):
    """手動で当て済み(tmpだけ消えた)なら印も片付ける。残すと毎回probeし直すことになる。"""
    from tictok.record import recorder

    recording = recording_factory(ended_at=DAY)
    mp4 = Path(recording["path"])
    mp4.write_bytes(b"normalized")
    tmp = recorder.normalize_tmp_path(mp4)
    recorder.normalize_marker_path(tmp).write_text('{"timing_mode": "passthrough"}', encoding="utf-8")

    assert await recorder.reclaim_normalized_mp4(mp4) == "none"
    assert not recorder.normalize_marker_path(tmp).exists()


async def test_startup_sweep_reclaims_and_refreshes_the_recorded_size(
        recording_factory, tmp_db, tmp_root, monkeypatch):
    """起動sweepが差し替え待ちを拾い、DBのbytesも取り直すこと。

    bytesを直さないと容量画面と保持policyが元mp4のサイズで計算し続ける(再encodeで
    数倍変わる)。印の無い録画はsweepの対象外で、ffprobeも走らない。"""
    from tictok.record import recorder

    pending = recording_factory(ended_at=DAY)
    untouched = recording_factory(ended_at=DAY)
    mp4 = Path(pending["path"])
    mp4.write_bytes(b"mixed")
    tmp = recorder.normalize_tmp_path(mp4)
    tmp.write_bytes(b"normalized-and-larger")
    recorder.normalize_marker_path(tmp).write_text(
        '{"timing_mode": "passthrough", "width": 720, "height": 1280}', encoding="utf-8")
    probed = []

    async def probe(path):
        probed.append(path)
        return {(720, 1280)}

    monkeypatch.setattr(recorder, "probe_mp4_resolutions", probe)

    assert await recorder.reclaim_pending_normalizations(tmp_db, [tmp_root]) == 1
    assert mp4.read_bytes() == b"normalized-and-larger"
    assert tmp_db.get_recording(pending["id"])["bytes"] == len(b"normalized-and-larger")
    assert tmp_db.get_recording(untouched["id"])["bytes"] == untouched["bytes"]
    assert probed == [tmp]


async def test_replace_with_retry_survives_a_lock_that_outlasts_the_first_attempts(tmp_path):
    """差し替えは一度の失敗で諦めない。30秒固定だった頃に、再生中のfileを掴んだまま
    抜けられて正規化が丸ごと失われている。"""
    from tictok.record import recorder

    tmp = tmp_path / "a.mp4.norm.tmp"
    dst = tmp_path / "a.mp4"
    tmp.write_bytes(b"normalized")
    dst.write_bytes(b"mixed")
    real_replace, attempts = os.replace, []

    def locked_for_the_first_few(src, target):
        attempts.append(target)
        if len(attempts) < 4:
            raise PermissionError("locked by another process")
        real_replace(src, target)

    monkeypatch_sleep = getattr(recorder.asyncio, "sleep")
    try:
        recorder.os.replace = locked_for_the_first_few
        recorder.asyncio.sleep = _no_wait
        assert await recorder.replace_with_retry(tmp, dst) is True
    finally:
        recorder.os.replace = real_replace
        recorder.asyncio.sleep = monkeypatch_sleep
    assert len(attempts) == 4
    assert dst.read_bytes() == b"normalized"


async def _no_wait(_seconds):
    return None


def _fake_probe(resolutions):
    async def probe(_path, *_args):
        return set(resolutions)
    return probe


# --------------------------------------------------------------------------
# 再mp4化の無駄削り(concatと並行したkeyframe走査 / 音声の二重encode回避)
# --------------------------------------------------------------------------


async def test_normalize_uses_the_resolutions_probed_during_concat(recording_factory,
                                                                   monkeypatch):
    """concatと並行して取った解像度が在れば、連結後mp4を頭から読み直さないこと。

    この再走査は実測で349MBあたり14秒・1.2GBで50秒かかる。同じ内容を2度読むのを
    やめるのがこの経路の狙いなので、握り潰されていないことを固定する。"""
    from tictok.record import recorder

    recording = recording_factory(ended_at=DAY)
    mp4 = Path(recording["path"])
    calls = []

    async def probe(path, *args):
        calls.append(path)
        return {(640, 1280), (720, 1280)}

    monkeypatch.setattr(recorder, "probe_mp4_resolutions", probe)
    rec = recorder.Recorder("streamerA", str(mp4.parent), 1)
    rec.base = mp4.stem
    rec._concat_resolutions = {(720, 1280)}
    monkeypatch.setattr(recorder.config, "get_normalize_mixed_resolution", lambda: True)

    await rec._normalize_mixed_resolution(mp4)

    # 単一解像度として畳まれ、再走査もre-encodeも走らない。
    assert calls == []


async def test_normalize_reprobes_when_concat_left_no_resolutions(recording_factory,
                                                                  monkeypatch):
    """並行走査が何も返せなかった時は、必ず連結後mp4を読み直すこと。空のまま進めると
    混在録画を「単一解像度」と誤判定して黙ってnormalizeを飛ばす(過去の実バグ)。"""
    from tictok.record import recorder

    recording = recording_factory(ended_at=DAY)
    mp4 = Path(recording["path"])
    calls = []

    async def probe(path, *args):
        calls.append(path)
        return {(720, 1280)}

    monkeypatch.setattr(recorder, "probe_mp4_resolutions", probe)
    rec = recorder.Recorder("streamerA", str(mp4.parent), 1)
    rec.base = mp4.stem
    rec._concat_resolutions = None

    await rec._normalize_mixed_resolution(mp4)

    assert calls == [mp4]


async def test_reencode_copies_audio_only_when_asked(tmp_path, monkeypatch):
    """finalize経路は直前のconcatが書いたAACをそのまま運ぶ(copy)。素性を保証できない
    維持scriptは既定のままre-encodeする。"""
    from tictok.record import recorder

    captured = []

    class _Proc:
        returncode = 0

        def __init__(self):
            self.stdout = _EmptyStream()

        async def wait(self):
            return 0

    class _EmptyStream:
        async def readline(self):
            return b""

    async def fake_exec(*args, **kwargs):
        captured.append(args)
        (tmp_path / "out.tmp").write_bytes(b"x")
        return _Proc()

    async def same_length(_path):
        return 3600.0

    monkeypatch.setattr(recorder.asyncio, "create_subprocess_exec", fake_exec)
    # 尺の突き合わせ(完走の検証)は別testの主題。ここはffmpegの引数だけを見る。
    monkeypatch.setattr(recorder, "_probe_duration_seconds", same_length)
    monkeypatch.setattr(recorder, "_write_normalize_marker", lambda *a, **k: None)

    src, dst = tmp_path / "in.mp4", tmp_path / "out.tmp"
    src.write_bytes(b"x")
    assert await recorder.reencode_single_resolution(
        src, dst, 720, 1280, "pad", "h264", 17, audio_copy=True) == "passthrough"
    assert "copy" in captured[-1] and "aac" not in captured[-1]

    assert await recorder.reencode_single_resolution(
        src, dst, 720, 1280, "pad", "h264", 17) == "passthrough"
    assert "aac" in captured[-1]


async def test_reencode_that_stops_early_is_not_accepted_as_success(tmp_path, monkeypatch):
    """exit 0 は「最後まで読めた」を意味しない。実測では178分の入力に対しdecodeが14.5分で
    止まり、ffmpegは正常終了して91%を捨てた出力を残した。尺で突き合わせないと通ってしまう。"""
    from tictok.record import recorder

    modes = []

    class _Proc:
        returncode = 0

        def __init__(self):
            self.stdout = _EmptyStream()

        async def wait(self):
            return 0

    class _EmptyStream:
        async def readline(self):
            return b""

    async def fake_exec(*args, **kwargs):
        modes.append("cfr" if "cfr" in args else "passthrough")
        (tmp_path / "out.tmp").write_bytes(b"x")
        return _Proc()

    async def short_output(path):
        return 10675.0 if path.name == "in.mp4" else 872.0

    monkeypatch.setattr(recorder.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(recorder, "_probe_duration_seconds", short_output)
    monkeypatch.setattr(recorder, "_write_normalize_marker", lambda *a, **k: None)

    src, dst = tmp_path / "in.mp4", tmp_path / "out.tmp"
    src.write_bytes(b"x")
    result = await recorder.reencode_single_resolution(
        src, dst, 720, 1280, "pad", "h264", 17, audio_copy=True)

    assert result is None                       # 採用しない
    assert modes == ["passthrough", "cfr"]      # CFRまで試してから諦める
    assert not dst.exists()                     # 切れた出力を残さない(sweepが拾ってしまう)


async def test_reencode_keeps_its_output_when_the_duration_matches(tmp_path, monkeypatch):
    from tictok.record import recorder

    class _Proc:
        returncode = 0

        def __init__(self):
            self.stdout = _EmptyStream()

        async def wait(self):
            return 0

    class _EmptyStream:
        async def readline(self):
            return b""

    async def fake_exec(*args, **kwargs):
        (tmp_path / "out.tmp").write_bytes(b"x")
        return _Proc()

    async def same_length(_path):
        return 10675.0

    monkeypatch.setattr(recorder.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(recorder, "_probe_duration_seconds", same_length)
    monkeypatch.setattr(recorder, "_write_normalize_marker", lambda *a, **k: None)

    src, dst = tmp_path / "in.mp4", tmp_path / "out.tmp"
    src.write_bytes(b"x")
    assert await recorder.reencode_single_resolution(
        src, dst, 720, 1280, "pad", "h264", 17, audio_copy=True) == "passthrough"


# ===== 退避(_backup)の後始末 =====


@pytest.fixture
def backup_env(tmp_root, monkeypatch):
    """退避と現行mp4を作り、ffprobeの代わりに (frame数, 尺) を返す仕掛けを置く。"""
    from tictok.record import backups

    measured: dict = {}

    async def fake_probe(path):
        # keyはpathそのもの。現行mp4と1世代目の退避はfile名が同じ(<stem>.mp4)なので、
        # 名前でひくと両者の測定値が混ざる。
        return measured.get(str(path), (None, None))

    monkeypatch.setattr(backups, "probe_frames_seconds", fake_probe)

    def _make(stem="00001_streamerA_20260101_120000", generations=1):
        current = layout.mp4_path(tmp_root, stem, "streamerA")
        current.parent.mkdir(parents=True, exist_ok=True)
        current.write_bytes(b"\x00" * 64)
        backup_dir = backups.backup_dir(tmp_root)
        backup_dir.mkdir(parents=True, exist_ok=True)
        made = []
        for n in range(generations):
            path = backup_dir / (f"{stem}.mp4" if n == 0 else f"{stem}.{n}.mp4")
            path.write_bytes(b"\x00" * 128)
            made.append(path)
        return current, made, measured

    return _make


async def test_backup_is_deleted_once_the_replacement_is_verified(backup_env, tmp_root):
    """退避は失敗を巻き戻すためのもので、成功が確かめられた時点で役目を終える。消す経路が
    無かったため、成功1回につき元mp4が1本ずつ永久に残っていた(実測84本 304GB)。"""
    from tictok.record import backups

    stem = "00001_streamerA_20260101_120000"
    current, made, measured = backup_env(stem=stem, generations=2)
    measured[str(current)] = (81870, 3640.0)
    measured[str(made[0])] = (81870, 3769.0)   # 尺は旧経路のぶん長いがframeは同じ
    measured[str(made[1])] = (81870, 3769.0)

    result = await backups.sweep_recording_backups(
        stem, current, [tmp_root], keep_seconds=0.0, now=time.time())

    assert result["deleted"] == 2
    assert not any(path.exists() for path in made)


async def test_backup_survives_when_the_replacement_lost_content(backup_env, tmp_root):
    """現行が退避より欠けていれば、その退避はその録画の唯一の原本。消してはいけない。"""
    from tictok.record import backups

    stem = "00001_streamerA_20260101_120000"
    current, made, measured = backup_env(stem=stem)
    measured[str(current)] = (18252, 730.0)     # 途中で切れた作り直し
    measured[str(made[0])] = (81870, 3769.0)

    result = await backups.sweep_recording_backups(
        stem, current, [tmp_root], keep_seconds=0.0, now=time.time())

    assert result["deleted"] == 0
    assert made[0].exists()
    assert "欠けている" in "".join(result["kept"])


async def test_backup_survives_when_only_frames_dropped_but_length_held(backup_env, tmp_root):
    """旧mp4がCFR化でframeを水増ししていると、正しい作り直しでもframeが減る。内容欠落とは
    別物だが、尺だけでは中身が薄くなっていないと言い切れないので自動では消さない。"""
    from tictok.record import backups

    stem = "00001_streamerA_20260101_120000"
    current, made, measured = backup_env(stem=stem)
    measured[str(current)] = (160047, 7647.0)
    measured[str(made[0])] = (238531, 7951.0)

    result = await backups.sweep_recording_backups(
        stem, current, [tmp_root], keep_seconds=0.0, now=time.time())

    assert result["deleted"] == 0
    assert made[0].exists()


async def test_backup_is_kept_inside_the_configured_window(backup_env, tmp_root):
    """猶予を設定していれば、判定に関わらずその期間は残す(尺やframeでは見えない不具合に
    人が気付くための窓)。"""
    from tictok.record import backups

    stem = "00001_streamerA_20260101_120000"
    current, made, measured = backup_env(stem=stem)
    measured[str(current)] = (81870, 3640.0)
    measured[str(made[0])] = (81870, 3769.0)

    result = await backups.sweep_recording_backups(
        stem, current, [tmp_root], keep_seconds=DAY, now=time.time())

    assert result["deleted"] == 0
    assert made[0].exists()


def test_startup_sweep_removes_orphaned_burn_in_intermediates(recording_factory, tmp_root):
    """processが即死するとrenderの finally が走らず中間物が残る。実際にserver再起動で
    31GB(cfrbase 17.3GB + comments.mov 13.7GB)が居座り、97%埋まったdiskを直接圧迫した。"""
    from tictok.record.video_overlay import (
        overlay_paths, overlay_transient_paths, sweep_orphaned_transients,
    )

    recording = recording_factory(ended_at=DAY)
    src = Path(recording["path"])
    orphans = [p for p in overlay_transient_paths(src)]
    for path in orphans:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 16)
    frames_dir = orphans[1].with_name(orphans[1].stem + ".frames")
    frames_dir.mkdir(parents=True, exist_ok=True)
    (frames_dir / "f0000000.png").write_bytes(b"x" * 32)
    # 成果物(焼き込み済みmp4)と永続sidecarは巻き込まない。
    output = overlay_paths(src)[0]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"kept")
    timing = recorder_timing_path(src)
    timing.parent.mkdir(parents=True, exist_ok=True)
    timing.write_text("{}", encoding="utf-8")

    removed, freed = sweep_orphaned_transients([tmp_root])

    assert removed == len(orphans) + 1
    assert freed == 16 * len(orphans) + 32
    assert not any(p.exists() for p in orphans)
    assert not frames_dir.exists()
    assert output.read_bytes() == b"kept"
    assert timing.is_file()


def test_startup_sweep_is_a_noop_without_a_sidecar_dir(tmp_path):
    """sidecar dirがまだ無いserverでも落ちないこと(初回起動)。"""
    from tictok.record.video_overlay import sweep_orphaned_transients

    assert sweep_orphaned_transients([tmp_path / "nope"]) == (0, 0)


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


# ===== stt_worker: 別processとの境界 =====
#
# 文字起こしはserverと別processで走る(CTranslate2とtorchのcuDNNが同じDLL名で衝突し、
# processごと即死するため)。ここで固定するのは親側の受け口: 進捗と結果を取り出せること、
# そして**子が黙って死んだ時に必ず理由が残ること**である。native crashは例外にならず、
# 終了codeとstderrだけが手掛かりになる。


class _FakeChild:
    """subprocess.Popenの代役。stdoutに流す行と終了codeだけを持つ。

    ``returncode`` も持たせる。取り消しの ``cancel._kill`` はこの属性で「まだ生きているか」
    を見るので、無いと取り消し経路がAttributeErrorで落ちる(Popenは必ず持っている)。"""

    def __init__(self, stdout_lines, stderr_lines=(), code=0):
        self.stdout = iter(stdout_lines)
        self.stderr = iter(stderr_lines)
        self._code = code
        self.returncode = None
        self.killed = False

    def wait(self):
        return self._code

    def poll(self):
        return self._code

    def kill(self):
        self.killed = True


def _run_with_child(monkeypatch, child, on_progress=None):
    from tictok.record import stt_worker

    monkeypatch.setattr(stt_worker.subprocess, "Popen", lambda *a, **k: child)
    return stt_worker.run_transcribe("x.ts", on_progress)


def test_stt_worker_returns_the_childs_result_and_forwards_progress(monkeypatch):
    seen = []
    child = _FakeChild([
        '{"t": "progress", "done": 5.0, "total": 10.0}\n',
        '{"t": "result", "result": {"text": "ok", "segments": []}}\n',
    ])
    result = _run_with_child(monkeypatch, child, lambda d, t: seen.append((d, t)))
    assert result == {"text": "ok", "segments": []}
    assert seen == [(5.0, 10.0)]


def test_stt_worker_raises_the_childs_own_failure_message(monkeypatch):
    from tictok.record.transcription import STTError

    child = _FakeChild(['{"t": "error", "message": "音声の読み込みに失敗しました"}\n'])
    with pytest.raises(STTError, match="音声の読み込みに失敗しました"):
        _run_with_child(monkeypatch, child)


def test_stt_worker_reports_the_exit_code_and_log_tail_when_the_child_dies(monkeypatch):
    """native crash(0xc0000409等)は結果も error 行も残さない。終了codeと直前のlogを
    error本文へ載せないと、「無言で消えた」だけが記録に残る。"""
    from tictok.record.transcription import STTError

    child = _FakeChild([], stderr_lines=["loading whisper model\n", "cuda init\n"],
                       code=3221226505)
    with pytest.raises(STTError) as excinfo:
        _run_with_child(monkeypatch, child)
    assert "3221226505" in str(excinfo.value)
    assert "cuda init" in str(excinfo.value)


def test_stt_worker_registers_the_child_so_cancel_can_kill_it(monkeypatch):
    """取り消しは子processのkillでしか効かない。復号はCTranslate2の中で回っており、python側に
    取り消しを見に行く余地が無いため、登録し忘れると取り消しが黙って無視される。"""
    from tictok.core import cancel
    from tictok.record import stt_worker

    child = _FakeChild([
        '{"t": "progress", "done": 5.0, "total": 10.0}\n',
        '{"t": "result", "result": {"text": "ok"}}\n',
    ], code=3221225786)
    token = cancel.CancelToken("job1")
    monkeypatch.setattr(stt_worker.subprocess, "Popen", lambda *a, **k: child)
    with cancel.token_scope(token):
        with pytest.raises(cancel.JobCancelled):
            stt_worker.run_transcribe("x.ts", lambda d, t: token.cancel())
    assert child.killed


def test_stt_worker_reports_a_cancel_as_cancelled_not_as_a_crash(monkeypatch):
    """killされた子は本物のcrashと同じ非0で返る。取り消しを先に名乗らないと、operator自身の
    取り消しが「processが異常終了しました」というerrorとして記録される。"""
    from tictok.core import cancel
    from tictok.record import stt_worker

    child = _FakeChild([], stderr_lines=["loading whisper model\n"], code=3221225786)
    token = cancel.CancelToken("job1")
    token.cancel()
    monkeypatch.setattr(stt_worker.subprocess, "Popen", lambda *a, **k: child)
    with cancel.token_scope(token):
        with pytest.raises(cancel.JobCancelled):
            stt_worker.run_transcribe("x.ts")


def test_stt_worker_does_not_start_a_child_for_an_already_cancelled_job(monkeypatch):
    """枠待ちは数時間になり得る。待っている間に受けた取り消しが無視されると、止めたはずの
    jobが枠を取った瞬間に改めて走り出す。"""
    from tictok.core import cancel
    from tictok.record import stt_worker

    spawned = []

    def _spawn(*args, **kwargs):
        spawned.append(1)
        return _FakeChild([])

    token = cancel.CancelToken("job1")
    token.cancel()
    monkeypatch.setattr(stt_worker.subprocess, "Popen", _spawn)
    with cancel.token_scope(token):
        with pytest.raises(cancel.JobCancelled):
            stt_worker.run_transcribe("x.ts")
    assert spawned == []


def test_stt_worker_ignores_a_stray_stdout_line_without_losing_the_result(monkeypatch):
    """stdoutは制御channel専用。子が素のtextを混ぜても、結果は取り出せなければならない。"""
    child = _FakeChild([
        "not json at all\n",
        '{"t": "result", "result": {"text": "ok"}}\n',
    ])
    assert _run_with_child(monkeypatch, child) == {"text": "ok"}


async def test_terminate_all_kills_a_running_child(monkeypatch):
    """serverを止めたら復号の子も止める。別processにした以上、親を終えるだけでは
    GPUを掴んだ孤児が残る(Windowsは親の終了で子を落とさない)。"""
    from tictok.record import stt_worker

    child = _FakeChild([])
    child._code = None  # 実行中
    with stt_worker._children_lock:
        stt_worker._children.add(child)
    try:
        assert stt_worker.terminate_all() == 1
        assert child.killed is True
    finally:
        with stt_worker._children_lock:
            stt_worker._children.discard(child)
