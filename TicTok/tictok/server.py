import asyncio
import atexit
import csv
import io
import itertools
import json
import logging
import mimetypes
import os
import re
import secrets
import shutil
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tictok.paths import PROJECT_ROOT
from tictok.core.logging_setup import (
    progress_interval_seconds,
    setup_logging,
    shutdown_logging,
)
from tictok.core.logctx import ctx_request_id, log_context
from tictok.core.jsonio import JsSafeJSONResponse, js_safe
from tictok.core.http_cache import REVALIDATE_CACHE_CONTROL, static_cache_control
from tictok.media.avatar_pool import AvatarPool
from tictok.media.avatar_proxy import AvatarProxy
from tictok.media.gift_icons import GiftIconCache
from tictok.ai import ai_analysis, review_digest
from tictok.ai.ai_analysis import AIError, ai_status, analyze_comments, analyze_streamer
from tictok.core.config import (
    get_ai_enabled,
    get_avatar_fetch_attempts,
    get_avatar_fetch_backoff_seconds,
    get_avatar_fetch_concurrency,
    dotenv_summary,
    get_db_path,
    get_host,
    get_job_retention_seconds,
    get_log_access_gate_max_keys,
    get_log_access_rollup_seconds,
    get_log_dir,
    get_log_level,
    get_log_slow_http_ms,
    get_media_job_history_days,
    get_no_restore,
    get_ops_badge_window_hours,
    get_ops_events_detail_max_chars,
    get_ops_events_query_limit,
    get_ops_events_retention_days,
    get_port,
)
from tictok.collect.manager import CollectorManager
from tictok.core.gpu import gpu_status
from tictok.core.process_lock import ProcessLock, ProcessLockError
from tictok.core import layout
from tictok.record.recorder import (
    disk_free_by_volume,
    ffmpeg_available,
    ffprobe_available,
    migrate_sidecars,
    recover_interrupted_recordings,
    Recorder,
)
from tictok.record.transcription import STTError, stt_available, stt_status
from tictok.record.transcription import transcribe as stt_transcribe
from tictok.record.transcribe_queue import TranscribeQueue, backfill_search_index
from tictok.media.clipper import make_clip
from tictok.media.thumbnails import ensure_sprite, sprite_path
from tictok.media.waveform import (
    ensure_audio_profile,
    ensure_waveform,
    level_peak,
    silent_ratio,
)
from tictok.search import cutlist_export, indexer, semantic
from tictok.record import audio_norm, disk_scan, retention, subtitles
from tictok.record.media_queue import JobSkipped, MediaJobQueue
from tictok.record.upscale import (
    UpscaleError,
    cleanup_upscale_files,
    ensure_upscaled,
    upscale_artifact_paths,
    upscale_done,
    upscale_input_path,
    upscale_output_path,
    upscale_status,
)
from tictok import analytics
from tictok.core import cancel, spike
from tictok.core.settings import Settings
from tictok.storage import OPS_ERROR, OPS_INFO, OPS_WARNING, Storage
from tictok.record.video_overlay import (
    _duration_seconds,
    cleanup_overlay_files,
    codec_family,
    ensure_overlay,
    NothingToDrawError,
    overlay_artifact_paths,
    overlay_enabled,
    overlay_paths,
    overlay_transient_paths,
    preview_clip,
    preview_paths,
    preview_seconds,
    preview_still,
    subtitles_enabled,
    timing_path,
    video_encoder_name,
)

# Configure logging before anything below it runs. The module-level Storage,
# the single-instance lock, journal recovery and the schema migration all execute
# at import time; configured any later, their output never reaches the log files.
setup_logging(profile="server")

logger = logging.getLogger("tictok.server")

BASE_DIR = PROJECT_ROOT
STATIC_DIR = BASE_DIR / "static"
# Windowsのmimetypesはregistry(HKCR)を読むため .js が text/plain に化ける環境がある。
# 現状のclassic scriptは動くが、module scriptはMIME厳格checkで実行拒否されるので、
# registryに依らずRFC 9239の値へ固定する。
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
# Resolved at startup from settings (see init below). A UI change to either dir
# therefore takes effect on the next server start, not mid-run.
# RECORD_DIR = working dir (SSD): live recording, HLS, avatar/gift caches.
# FINAL_DIR  = final dir (HDD): completed mp4s relocate here (== RECORD_DIR when unset).
RECORD_DIR: Path
FINAL_DIR: Path
# Roots a stored recording path is allowed to resolve under (both dirs, deduped).
_RECORD_ROOTS: list[Path] = []
UNIQUE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.]{1,64}$")
# Number of recent finished sessions averaged for the monitor page's
# "past streams" comparison (今回 / 前回 / 平均 / 自己Best).
HISTORY_COMPARE_LIMIT = 5
# A finished recording's bytes are immutable, so playback can cache them privately;
# a still-recording file keeps changing and must not be cached.
RECORDING_CACHE_MAX_AGE_SECONDS = 86400


@asynccontextmanager
async def _job_ops(domain: str, recording_id: Optional[int], **detail):
    """Bracket a long-running post-processing job (burn-in, upscale, transcription)
    with ops_events transitions and a job id.

    These jobs run across worker threads and ffmpeg sub-processes, so a single bound
    ``job_id`` is what joins their log lines to the Layer2 row. Recording the pair
    here rather than inside the job modules keeps those modules free of a Storage
    handle, which they cannot import without a cycle through this module.
    """
    job_id = secrets.token_hex(4)
    started = time.monotonic()
    with log_context(job_id=job_id, recording_id=recording_id):
        storage.record_ops_event(
            logger, f"{domain}.job_started", f"{domain} job started",
            recording_id=recording_id, job_id=job_id, detail=detail,
        )
        try:
            yield job_id
        except cancel.JobCancelled:
            # JobCancelledはBaseExceptionなので下のexcept Exceptionには入らない。ここで拾わ
            # ないと、job_startedだけが残り終端の遷移が無いops_events行になる。取り消しは
            # 正常な終わり方なのでseverityは既定(info)のまま — errorにするとnavのbadgeが
            # 点き、userが自分で取り消したのに障害として提示される。
            storage.record_ops_event(
                logger, f"{domain}.job_cancelled", f"{domain} job cancelled",
                recording_id=recording_id, job_id=job_id,
                duration_ms=(time.monotonic() - started) * 1000, detail=detail,
            )
            raise
        except JobSkipped as exc:
            # 作る物が無くて何も出力しなかった、という正常な終わり方。job_failedにすると
            # severity=errorでnavのbadgeが点き、入力の性質が障害として提示される。
            storage.record_ops_event(
                logger, f"{domain}.job_skipped", f"{domain} job skipped: {exc}",
                recording_id=recording_id, job_id=job_id,
                duration_ms=(time.monotonic() - started) * 1000,
                detail={**detail, "reason": str(exc)},
            )
            raise
        except Exception as exc:
            storage.record_ops_event(
                logger, f"{domain}.job_failed", f"{domain} job failed: {exc}",
                severity="error", recording_id=recording_id, job_id=job_id,
                duration_ms=(time.monotonic() - started) * 1000,
                detail={**detail, "error": type(exc).__name__}, exc_info=True,
            )
            raise
        storage.record_ops_event(
            logger, f"{domain}.job_completed", f"{domain} job completed",
            recording_id=recording_id, job_id=job_id,
            duration_ms=(time.monotonic() - started) * 1000, detail=detail,
        )


def _safe_recording_path(raw_path: str) -> Path:
    """Resolve a stored recording path and ensure it stays under an allowed record root
    (the working dir or the final dir). Recordings live in the working dir while in
    progress / interrupted and in the final dir once completed and relocated."""
    path = Path(raw_path).resolve()
    for root in _RECORD_ROOTS:
        if path == root or root in path.parents:
            return path
    raise HTTPException(status_code=400, detail="不正な録画pathです。")


def _remove_recording_files(recording: dict) -> None:
    """Best-effort removal of a recording's video file and its sidecars (overlay,
    timing) from disk. Used by session/bulk deletes where one file error must not
    abort the whole operation and where leaving the .mp4 behind would orphan it."""
    try:
        path = _safe_recording_path(recording["path"])
    except HTTPException:
        return
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        logger.warning("failed to delete recording file: %s", path, exc_info=True)
    cleanup_overlay_files(path)
    cleanup_upscale_files(path)
    try:
        timing_path(path).unlink(missing_ok=True)
    except OSError:
        pass


class EventHub:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def register(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
            total = len(self._connections)
        logger.info(
            "websocket client connected (total=%d)", total,
            extra={"event": "http.websocket_connected", "ctx": {"connections": total}},
        )

    async def unregister(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
            total = len(self._connections)
        logger.info(
            "websocket client disconnected (total=%d)", total,
            extra={"event": "http.websocket_disconnected", "ctx": {"connections": total}},
        )

    async def broadcast(self, message: dict) -> None:
        """Push one update to every connected page.

        A send that raises means that client missed this update; it is dropped here and
        the browser reconnects on its own, so the individual failure is degradation
        rather than loss. The per-connection reason stays at debug (a closing tab
        produces one routinely) while the fact that a live update was lost is reported
        once per broadcast at warning.
        """
        async with self._lock:
            connections = list(self._connections)
        # WSはHTTPのresponse classを通らないので、int64の桁落ち対策はここで掛ける。
        # 送信前に1回だけ変換し、接続ごとに繰り返さない。
        payload = js_safe(message)
        dead: list[WebSocket] = []
        for connection in connections:
            try:
                await connection.send_json(payload)
            except Exception:
                logger.debug(
                    "dropping dead websocket connection", exc_info=True,
                    extra={"event": "http.websocket_send_failed",
                           "ctx": {"message_type": message.get("type")}},
                )
                dead.append(connection)
        if dead:
            async with self._lock:
                for connection in dead:
                    self._connections.discard(connection)
                total = len(self._connections)
            logger.warning(
                "dropped %d unreachable websocket client(s) during broadcast (total=%d)",
                len(dead), total,
                extra={"event": "http.websocket_clients_dropped",
                       "ctx": {"dropped": len(dead), "connections": total,
                               "message_type": message.get("type")}},
            )


class JobRegistry:
    """実行中/直近終了した長時間jobの台帳。

    Progress used to live only in the browser: the page registered a callback when the
    button was clicked, so a reload threw the registration away and neither completion nor
    failure ever arrived — the job kept running invisibly. The authoritative state is here
    instead, and a connecting websocket is handed the whole snapshot, so a reloaded (or
    second) page picks the running job back up.

    Finished jobs linger for a retention window so a reload immediately after completion
    still shows the outcome rather than an empty list, which reads as "nothing happened".
    """

    def __init__(self, broadcast) -> None:
        self._broadcast = broadcast
        self._jobs: dict[str, dict] = {}

    def _prune(self) -> None:
        cutoff = time.time() - get_job_retention_seconds()
        for job_id, job in list(self._jobs.items()):
            if job["state"] != "running" and (job.get("finished_at") or 0) < cutoff:
                del self._jobs[job_id]

    async def start(self, job_id: str, domain: str, title: str, *,
                    recording_id: Optional[int] = None,
                    session_id: Optional[int] = None, total: int = 1) -> dict:
        self._prune()
        job = {
            "job_id": job_id, "domain": domain, "title": title,
            "recording_id": recording_id, "session_id": session_id,
            "state": "running", "stage": "", "pct": 0,
            "index": 0, "total": total,
            "started_at": time.time(), "finished_at": None, "message": "",
        }
        self._jobs[job_id] = job
        await self._broadcast({"type": "job_update", "job": dict(job)})
        return job

    async def progress(self, job_id: str, pct: int, *, stage: Optional[str] = None,
                       index: Optional[int] = None) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        pct = max(0, min(100, int(pct)))
        if stage is not None:
            job["stage"] = stage
        if index is not None:
            job["index"] = index
        # The per-frame callbacks fire far more often than the percentage changes; only
        # a real change is worth a broadcast to every connected page.
        if job["pct"] == pct and stage is None and index is None:
            return
        job["pct"] = pct
        await self._broadcast({"type": "job_update", "job": dict(job)})

    async def finish(self, job_id: str, state: str, *, message: str = "") -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job["state"] = state
        job["message"] = message
        job["finished_at"] = time.time()
        if state == "completed":
            job["pct"] = 100
        await self._broadcast({"type": "job_update", "job": dict(job)})

    def snapshot(self) -> list:
        self._prune()
        return [dict(job) for job in
                sorted(self._jobs.values(), key=lambda j: j["started_at"])]


hub = EventHub()
jobs = JobRegistry(hub.broadcast)


@asynccontextmanager
async def _tracked_job(domain: str, title: str, *, recording_id: Optional[int] = None,
                       session_id: Optional[int] = None, total: int = 1):
    """Register a job so its progress survives a browser reload, and always mark it
    finished — a failure that left the entry ``running`` would be a spinner nothing ever
    clears, which is the very symptom this replaces."""
    job_id = secrets.token_hex(4)
    await jobs.start(job_id, domain, title, recording_id=recording_id,
                     session_id=session_id, total=total)
    try:
        yield job_id
    except HTTPException as exc:
        await jobs.finish(job_id, "failed", message=str(exc.detail))
        raise
    except Exception as exc:
        await jobs.finish(job_id, "failed", message=str(exc))
        raise
    await jobs.finish(job_id, "completed")


# The .env load happens while config is first imported, which is before any log
# handler exists (logging_setup imports config), so it reports itself here instead.
logger.info(
    "environment file loaded (present=%s applied=%d)",
    dotenv_summary()["present"], dotenv_summary()["applied"],
    extra={"event": "process.dotenv_loaded", "ctx": dotenv_summary()},
)
_startup_started = time.perf_counter()
storage = Storage(get_db_path())
# Acquire the single-instance lock before cleanup_stale_sessions() — that call
# finalizes every connecting/connected session unconditionally, so a second
# process starting here would otherwise terminate the first process's live
# session and both would then collect the same rooms in parallel.
instance_lock = ProcessLock(get_db_path() + ".lock")
try:
    instance_lock.acquire()
except ProcessLockError as exc:
    logger.error(
        "cannot start: %s", exc, exc_info=True,
        extra={"event": "process.instance_lock_conflicted",
               "ctx": {"path": get_db_path() + ".lock"}},
    )
    raise SystemExit(1)
atexit.register(instance_lock.release)
logger.info(
    "single-instance lock acquired",
    extra={"event": "process.instance_lock_acquired",
           "ctx": {"path": get_db_path() + ".lock"}},
)
# batched writerの停滞/クラッシュ/再起動でbuffer滞留分が失われても、取り込み時にdiskへ
# 追記した耐久journalから欠損eventを復元する。stale finalizeより前に走らせ、復元済みeventで
# stats/bucketが再構成された状態にする。
_journal_summary = storage.recover_from_journal()
_stale_sessions = storage.cleanup_stale_sessions()
_stale_recordings = storage.mark_stale_recordings()
# One line for the whole crash-recovery step. Each call already reports its own
# anomalies; this states the outcome and its cost, which is what tells a "why did the
# server take a minute to come up" question apart from a "what did it repair" one.
storage.record_ops_event(
    logger,
    "process.startup_recovery_completed",
    "startup recovery: journal restored {sessions} session(s) (+{events} events,"
    " +{viewers} viewers), finalized {stale_sessions} stale session(s),"
    " flagged {stale_recordings} interrupted recording(s)".format(
        stale_sessions=_stale_sessions, stale_recordings=_stale_recordings,
        **_journal_summary
    ),
    duration_ms=round((time.perf_counter() - _startup_started) * 1000.0, 1),
    detail={
        "journal_sessions": _journal_summary["sessions"],
        "journal_events": _journal_summary["events"],
        "journal_viewers": _journal_summary["viewers"],
        "stale_sessions": _stale_sessions,
        "stale_recordings": _stale_recordings,
    },
)
settings = Settings(storage)
# The record dirs are UI-configurable settings; resolve them before anything roots off
# them (sidecar migration, avatar/gift caches, the recorder). settings.get returns the
# DB value if set, else the env var, else the default. FINAL_DIR falls back to the
# working dir when unset (no split; completed recordings are not relocated).
RECORD_DIR = Path(settings.get("record_dir")).resolve()
_final_setting = settings.get("record_dir_final")
FINAL_DIR = Path(_final_setting).resolve() if _final_setting else RECORD_DIR
_RECORD_ROOTS = [RECORD_DIR] if FINAL_DIR == RECORD_DIR else [RECORD_DIR, FINAL_DIR]
# Relocate sidecars older recordings wrote next to the .mp4 into per-folder .sidecars/,
# so each recordings root holds only the .mp4 files. Run on both roots (idempotent).
_migrated_sidecars = sum(migrate_sidecars(_root) for _root in _RECORD_ROOTS)
logger.info(
    "record dirs resolved (work=%s final=%s, %d sidecar file(s) migrated)",
    RECORD_DIR, FINAL_DIR, _migrated_sidecars,
    extra={"event": "process.record_dirs_resolved",
           "ctx": {"path": str(RECORD_DIR), "final_path": str(FINAL_DIR),
                   "split": FINAL_DIR != RECORD_DIR,
                   "sidecars_migrated": _migrated_sidecars}},
)
avatar_pool = AvatarPool(
    cache_dir=RECORD_DIR / "avatars" / "by-id",
    legacy_dir=RECORD_DIR / "avatars" / "commenter",
    concurrency=get_avatar_fetch_concurrency(),
    attempts=get_avatar_fetch_attempts(),
    backoff_seconds=get_avatar_fetch_backoff_seconds(),
)
avatar_proxy = AvatarProxy(cache_dir=RECORD_DIR / "avatars", pool=avatar_pool)
gift_icons = GiftIconCache(cache_dir=RECORD_DIR / "gift_icons")
manager = CollectorManager(
    broadcast=hub.broadcast, storage=storage, settings=settings,
    gift_icons=gift_icons, avatar_pool=avatar_pool, avatar_proxy=avatar_proxy,
)


# 一括転写のworkerは1本(STT自体がprocess内で直列化されている)。queueの実体はDB側にあり、
# processが落ちても投入内容は残る。
transcribe_queue = TranscribeQueue(storage, hub.broadcast, _safe_recording_path)


async def _media_job_runner(job: dict, report) -> dict:
    """queueからjobを受け取る入口。実処理はこのmoduleの既存helperなので、queue側は焼き込みも
    超解像も知らないままでいられる。名前解決は呼び出し時なので、実体が下で定義されていてよい。"""
    return await _run_media_job(job, report)


# 焼き込み/Up出力/再mp4化の永続queue。workerは1本で、投入内容はDBに残るためserverを再起動
# しても消えない(実行中だった行は起動時にinterruptedへ倒し、個別recoveryへ回す)。
media_job_queue = MediaJobQueue(storage, hub.broadcast, _media_job_runner)


def _job_snapshot() -> list:
    """画面が見るjobの全体像: process内registry(容量scan・保持policy・文字起こし)と、DBの
    映像job queue(単体job + session一括のgroup)を1つのlistに畳む。"""
    return jobs.snapshot() + media_job_queue.list_jobs()


def _media_job_running() -> bool:
    """焼き込み/Up出力が今この瞬間走っているか。renderの中間fileを消す操作の可否判定に使う。"""
    return any(job["state"] == "running" and job["domain"] in ("overlay", "upscale")
               for job in _job_snapshot())


def _restore_reprocess_backup(job: dict) -> Optional[str]:
    """中断した再mp4化の後始末。

    再mp4化は元mp4を _backup/ へ退避してからfinalizeをやり直すので、その最中にprocessが死ぬと
    録画にmp4が無い状態のまま誰も復元しない。退避先はmove直後にjob行へ書いてあるため、ここで
    元へ戻せる。戻したpathを返す(戻す必要が無ければNone)。
    """
    result = job.get("result") or {}
    backup = result.get("backup_path")
    final = result.get("final_path")
    if not backup or not final:
        return None
    backup_path, final_path = Path(backup), Path(final)
    # finalize が完走していれば mp4 は既に在る。その場合の退避fileは正常な世代管理なので残す。
    if final_path.is_file() or not backup_path.is_file():
        return None
    shutil.move(str(backup_path), str(final_path))
    return str(final_path)


async def _recover_media_jobs() -> None:
    """起動時: 前回processで実行中だった映像jobを中断扱いにし、必要な後始末を行う。"""
    interrupted = storage.interrupt_running_media_jobs()
    for job in interrupted:
        restored = None
        if job["kind"] == "reprocess":
            try:
                restored = await asyncio.to_thread(_restore_reprocess_backup, job)
            except OSError:
                # 復元できなければ録画は退避先(_backup/)にしか無い。pathをlogへ必ず残す。
                logger.exception(
                    "could not restore the backup of interrupted reprocess job %s",
                    job["job_id"],
                    extra={"event": "media_queue.backup_restore_failed",
                           "ctx": {"job_id": job["job_id"],
                                   "recording_id": job.get("recording_id"),
                                   "result": job.get("result")}},
                )
        storage.record_ops_event(
            logger, "media_queue.job_interrupted",
            f"{job['kind']} job interrupted by a server restart",
            recording_id=job.get("recording_id"), session_id=job.get("session_id"),
            job_id=job["job_id"],
            detail={"kind": job["kind"], "pct": job.get("pct"),
                    "restored_path": restored},
        )
    pruned = storage.prune_media_jobs(get_media_job_history_days() * 86400.0)
    if interrupted or pruned:
        logger.info(
            "media job queue: %d interrupted, %d old row(s) pruned",
            len(interrupted), pruned,
            extra={"event": "media_queue.recovered",
                   "ctx": {"interrupted": len(interrupted), "pruned": pruned}},
        )


async def _recover_interrupted_recordings_bg():
    # クラッシュで中断した録画のHLS segmentをmp4へ復元する(mark_stale_recordingsで
    # interrupted化された行を、捕捉済み映像が残っていれば再finalizeしてcompletedに戻す)。
    # 大容量録画のffmpeg remuxはstartup lifespanを塞ぐため、listen開始後にbackgroundで実行する。
    try:
        await recover_interrupted_recordings(
            storage, RECORD_DIR, keep_hls=bool(settings.get("recording_keep_hls")),
            final_dir=FINAL_DIR,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        # The recording exists as HLS segments on disk but has no playable mp4, and
        # nothing retries after this point in the process's life.
        logger.exception(
            "interrupted-recording recovery failed",
            extra={"event": "recording.recovery_failed",
                   "ctx": {"path": str(RECORD_DIR)}},
        )


async def _backfill_search_index_bg():
    """検索indexの未構築分(comment・既存transcript)を起動後に均す。GPUを使わずSTT queueとは独立。"""
    try:
        await backfill_search_index(storage, _safe_recording_path)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "search index backfill failed",
            extra={"event": "search.backfill_failed", "ctx": {}},
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await manager.startup()
    no_restore = get_no_restore()
    if no_restore:
        # 監視の復元だけを止める。復元は起動数秒後に実配信へ接続して録画を開始するので、
        # 検証目的の起動が二重録画とdisk書き込みを伴わないようにするための唯一の入口。
        logger.warning(
            "monitor restore skipped (TICTOK_NO_RESTORE)",
            extra={"event": "process.monitor_restore_skipped",
                   "ctx": {"monitored": len(storage.list_monitored_targets())}},
        )
    else:
        await manager.restore()
    recovery_task = asyncio.create_task(_recover_interrupted_recordings_bg())
    transcribe_queue.start()
    # 中断jobの後始末はworkerを起こす前に済ませる。順序を逆にすると、退避したmp4を戻す前に
    # 同じ録画のjobが走り出す。
    await _recover_media_jobs()
    media_job_queue.start()
    backfill_task = asyncio.create_task(_backfill_search_index_bg())
    # ffmpeg/ffprobe are resolved from PATH at call time, so a missing binary surfaces
    # only when a recording fails to start. Stating it once at startup turns "no
    # recordings were produced last night" into a one-line answer.
    logger.info(
        "startup complete: %d monitor(s) restored in %.1fs (ffmpeg=%s ffprobe=%s no_restore=%s)",
        len(manager.snapshots()), time.perf_counter() - _startup_started,
        ffmpeg_available(), ffprobe_available(), no_restore,
        extra={"event": "process.startup_completed",
               "ctx": {"monitors": len(manager.snapshots()), "no_restore": no_restore,
                       "duration_ms": round((time.perf_counter() - _startup_started) * 1000.0, 1),
                       "ffmpeg": ffmpeg_available(), "ffprobe": ffprobe_available()}},
    )
    yield
    logger.info(
        "shutdown started", extra={"event": "process.shutdown_started", "ctx": {}}
    )
    recovery_task.cancel()
    try:
        await recovery_task
    except asyncio.CancelledError:
        pass
    backfill_task.cancel()
    try:
        await backfill_task
    except asyncio.CancelledError:
        pass
    await transcribe_queue.stop()
    await media_job_queue.stop()
    await manager.stop_all()
    await manager.shutdown()
    await avatar_proxy.aclose()
    await gift_icons.aclose()
    await avatar_pool.aclose()
    storage.close()
    instance_lock.release()


# ---- HTTP access log -------------------------------------------------------------
# Only failures and slow requests are recorded. A successful poll carries no diagnostic
# information and this deployment issues tens of thousands of them a day (/timeline
# alone), so logging 2xx/3xx would bury every line that matters.
access_logger = logging.getLogger("tictok.access")
# Random per-process prefix so request ids from two runs (or a restart mid-incident)
# never collide when their logs are read together; the counter keeps them ordered.
_REQUEST_ID_PREFIX = secrets.token_hex(3)
_request_ids = itertools.count(1)


class _AccessGate:
    """Interval gate keyed by (route, status).

    The generic DuplicateSuppressFilter cannot be used here: every access line is the
    same template from the same logger, so collapsing an HLS 404 storm by that
    fingerprint would collapse an unrelated route's 500 with it. Keying on
    (route, status) folds the storm and leaves every other failure visible.

    The suppressed count rides on the next emitted line for that key, so a storm is
    reported as a count rather than hidden. Counts held by an evicted key are lost;
    eviction only happens past get_log_access_gate_max_keys() distinct keys, which the
    routed endpoints cannot reach on their own.
    """

    def __init__(self) -> None:
        self._state: dict = {}
        self._lock = threading.Lock()

    def check(self, key, interval: float, now: float) -> tuple[bool, int]:
        if interval <= 0:
            return True, 0
        with self._lock:
            entry = self._state.get(key)
            if entry is None:
                if len(self._state) >= get_log_access_gate_max_keys():
                    self._evict_locked(now, interval)
                self._state[key] = [now, 0]
                return True, 0
            started, suppressed = entry
            if now - started < interval:
                entry[1] = suppressed + 1
                return False, 0
            self._state[key] = [now, 0]
            return True, suppressed

    def _evict_locked(self, now: float, interval: float) -> None:
        for key in [k for k, v in self._state.items() if now - v[0] >= interval]:
            del self._state[key]
        if len(self._state) >= get_log_access_gate_max_keys():
            oldest = sorted(self._state.items(), key=lambda kv: kv[1][0])
            for key, _ in oldest[: len(oldest) // 2]:
                del self._state[key]


_access_gate = _AccessGate()


def _route_key(scope: dict) -> str:
    """Stable label for the gate and the log line. Starlette writes the matched
    endpoint into the scope during routing, so this is read after the call: the
    endpoint name is per-route where the raw path is per-request (a path holding a
    recording id or a streamer id would defeat the gate). Unmatched paths share one
    key on purpose, so a scan of random URLs stays one countable line."""
    endpoint = scope.get("endpoint")
    return getattr(endpoint, "__name__", None) or "<unmatched>"


def _log_access(scope: dict, status: int, duration_ms: float, *, failed: bool = False) -> None:
    slow_ms = get_log_slow_http_ms()
    slow = duration_ms >= slow_ms
    if not failed and status < 400 and not slow:
        return
    route = _route_key(scope)
    allowed, suppressed = _access_gate.check(
        (route, status),
        progress_interval_seconds(get_log_access_rollup_seconds()),
        time.monotonic(),
    )
    if not allowed:
        return
    ctx = {
        "route": route,
        "method": scope.get("method", ""),
        "path": scope.get("path", ""),
        "status": status,
        "duration_ms": round(duration_ms, 1),
        "slow": slow,
    }
    if suppressed:
        ctx["suppressed"] = suppressed
    # A 5xx (or an unhandled exception) is a request whose result is gone with no
    # retry behind it; a 4xx is the client being told to change what it asked for, and
    # a slow success is degradation only.
    level = logging.ERROR if status >= 500 else logging.WARNING
    message = "%s %s -> %d in %.0fms" % (
        ctx["method"], ctx["path"], status, duration_ms
    )
    if suppressed:
        message += f" (+{suppressed} more since the previous line)"
    access_logger.log(
        level, message, exc_info=failed,
        extra={"event": "http.request_failed" if (failed or status >= 400)
               else "http.request_slow", "ctx": ctx},
    )


class AccessLogMiddleware:
    """Pure ASGI middleware: assigns the request id and reports failures/slow requests.

    Pure ASGI rather than BaseHTTPMiddleware because BaseHTTPMiddleware runs the
    downstream app in a separate task, so a ContextVar set around ``call_next`` does not
    reach the endpoint and the reset lands in a different context than the set. Here the
    endpoint is awaited inside this call, so the request id set below is visible to
    every log line the request produces — including the websocket endpoint's.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        token = ctx_request_id.set(f"{_REQUEST_ID_PREFIX}-{next(_request_ids)}")
        started = time.perf_counter()
        # 0 means the response never started (the client aborted); it is not a status
        # the server chose, so it is only ever reported by the slow rule.
        seen = {"status": 0}

        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                seen["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            if scope["type"] == "http":
                _log_access(
                    scope, 500, (time.perf_counter() - started) * 1000.0, failed=True
                )
            raise
        else:
            if scope["type"] == "http":
                _log_access(
                    scope, seen["status"], (time.perf_counter() - started) * 1000.0
                )
        finally:
            ctx_request_id.reset(token)


class CachePolicyStaticFiles(StaticFiles):
    """静的fileに種類ごとのCache-Controlを付けて返す。

    素のStaticFilesはETag/Last-Modifiedしか返さないため、browserがheuristicに
    cache期間を推測して古いJSを掴み、HTMLとの版ズレを起こす。方針は
    ``tictok.core.http_cache`` に集約する。"""

    def file_response(self, full_path, stat_result, scope, status_code=200) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        # full_path は realpath 化済みで static root と綴りが一致する保証が無いため、
        # routing時の相対path(get_path)で判定する。304応答にも同じ方針を載せる。
        response.headers["Cache-Control"] = static_cache_control(self.get_path(scope))
        return response


app = FastAPI(title="TicTok LIVE Monitor", lifespan=lifespan,
              default_response_class=JsSafeJSONResponse)
app.add_middleware(AccessLogMiddleware)
app.mount("/static", CachePolicyStaticFiles(directory=STATIC_DIR), name="static")


class MonitorRequest(BaseModel):
    unique_id: str = Field(min_length=1, max_length=80)
    # None: keep the target's existing preference (used by restart); a new target
    # then defaults to saving video. Explicit true/false sets it on add.
    record_video: Optional[bool] = None


class RecordVideoRequest(BaseModel):
    record_video: bool


class NoteRequest(BaseModel):
    note: str = Field(max_length=10000)


class DeleteUsersRequest(BaseModel):
    unique_ids: list[str] = Field(min_length=1, max_length=500)


def _normalize_unique_id(raw: str) -> str:
    unique_id = raw.strip().lstrip("@").strip()
    if not UNIQUE_ID_PATTERN.match(unique_id):
        raise HTTPException(
            status_code=422,
            detail="TikTok IDの形式が不正です。英数字・'_'・'.' のみ使用できます。",
        )
    return unique_id


def _get_collector(unique_id: str):
    collector = manager.get(unique_id)
    if collector is None:
        raise HTTPException(status_code=404, detail=f"@{unique_id} は監視対象に存在しません。")
    return collector


def _get_session_or_404(session_id: int) -> dict:
    session = storage.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} が見つかりません。")
    return session


def _page_response(filename: str) -> FileResponse:
    """HTML shellの応答。必ずrevalidateさせ、JS/CSSとの版ズレを防ぐ。"""
    return FileResponse(STATIC_DIR / filename,
                        headers={"Cache-Control": REVALIDATE_CACHE_CONTROL})


@app.get("/")
async def index() -> FileResponse:
    return _page_response("index.html")


@app.get("/overview")
async def overview_page() -> FileResponse:
    return _page_response("overview.html")


@app.get("/history")
async def history_page() -> FileResponse:
    return _page_response("history.html")


@app.get("/videos")
async def videos_page() -> FileResponse:
    return _page_response("videos.html")


@app.get("/jobs")
async def jobs_page() -> FileResponse:
    return _page_response("jobs.html")


@app.get("/ops")
async def ops_page() -> FileResponse:
    return _page_response("ops.html")


@app.get("/settings")
async def settings_page() -> FileResponse:
    return _page_response("settings.html")


@app.get("/battle")
async def battle_page() -> FileResponse:
    return _page_response("battle.html")


@app.get("/streamers")
async def streamers_page() -> FileResponse:
    return _page_response("streamers.html")


@app.get("/analytics")
async def analytics_page() -> FileResponse:
    return _page_response("analytics.html")


@app.get("/api/avatar")
async def avatar_image(u: str, id: str = "") -> Response:
    """Same-origin proxy for TikTok CDN avatars. The CDN hotlink/Referer-blocks
    direct <img src> loads and its signed URLs expire, so the browser fetches via
    here instead. ``id`` (the user's unique_id, optional) lets an expired URL fall
    back to that user's latest pooled avatar (owner or commenter). On total failure
    the UI falls back to its initial-letter avatar."""
    if not AvatarProxy.is_allowed(u):
        raise HTTPException(status_code=400, detail="許可されていない画像URLです。")
    result = await avatar_proxy.fetch(u, user_key=id or None)
    if result is None:
        raise HTTPException(status_code=502, detail="アイコン画像の取得に失敗しました。")
    content, content_type = result
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=21600"},
    )


@app.get("/api/settings")
async def get_settings_api() -> dict:
    return {"settings": settings.describe()}


@app.put("/api/settings")
async def update_settings_api(values: dict) -> dict:
    try:
        updated = settings.update(values)
    except ValueError as exc:
        # The operator's intended change did not take effect. Info, not warning: the
        # request is rejected with the reason and nothing in the system is degraded.
        # Keys only — the rejected value is already in the message.
        logger.info(
            "settings update rejected: %s", exc,
            extra={"event": "process.settings_update_rejected",
                   "ctx": {"keys": sorted(values), "reason": str(exc)}},
        )
        raise HTTPException(status_code=422, detail=str(exc))
    return {"settings": settings.describe(), "values": updated}


# ---- 運用log(ops_events viewer) ----
# 録画失敗・接続断・設定変更・jobの開始完了は全てops_eventsへ貯まっているが、これまで
# 読み出す導線が無かった。表はFKを張らずsession削除後も行が残るため、session_unique_idが
# NULLの行(=対象が削除済み)が正常に存在する。
OPS_SEVERITIES = (OPS_ERROR, OPS_WARNING, OPS_INFO)
# 設定変更履歴。同じendpointをkind前方一致で絞って使う。
OPS_SETTINGS_KIND = "process.settings_updated"


@app.get("/api/ops/events")
async def list_ops_events_api(
    severity: str = "",
    kind_prefix: str = "",
    unique_id: str = "",
    session_id: Optional[int] = None,
    job_id: str = "",
    since: Optional[float] = None,
    until: Optional[float] = None,
    limit: Optional[int] = None,
    before_ts: Optional[float] = None,
    before_id: Optional[int] = None,
) -> dict:
    if severity and severity not in OPS_SEVERITIES:
        raise HTTPException(status_code=422,
                            detail=f"不明なseverity: {severity}")
    max_page_size = max(1, get_ops_events_query_limit())
    page_size = max(1, min(int(limit), max_page_size)) if limit else max_page_size
    events = await asyncio.to_thread(
        storage.list_ops_events,
        limit=page_size,
        severity=severity or None,
        kind_prefix=kind_prefix or None,
        unique_id=unique_id or None,
        session_id=session_id,
        job_id=job_id or None,
        since=since,
        until=until,
        before_ts=before_ts,
        before_id=before_id,
    )
    # 次ページのkeyset。最後の行の(ts,id)を渡してもらう方式にし、offsetは使わない
    # (この表は末尾に行が増え続けるのでoffsetでは境界が重複・欠落する)。
    last = events[-1] if events else None
    return {
        "events": events,
        "limit": page_size,
        "next": ({"before_ts": last["ts"], "before_id": last["id"]}
                 if last is not None and len(events) >= page_size else None),
        "severities": list(OPS_SEVERITIES),
        "detail_max_chars": get_ops_events_detail_max_chars(),
        "retention_days": get_ops_events_retention_days(),
        "settings_kind": OPS_SETTINGS_KIND,
    }


@app.get("/api/ops/kinds")
async def list_ops_kinds_api(hours: Optional[float] = None) -> dict:
    since = time.time() - float(hours) * 3600 if hours else None
    kinds = await asyncio.to_thread(storage.ops_event_kinds, since=since)
    return {"kinds": kinds, "since": since}


@app.get("/api/ops/summary")
async def ops_summary_api(hours: Optional[float] = None) -> dict:
    """header badge用の軽量COUNT。DB照会に失敗したらここで500を返す。0件として握り潰すと
    「何も壊れていない」という嘘の表示になる。"""
    window = float(hours) if hours else float(get_ops_badge_window_hours())
    since = time.time() - window * 3600
    counts = await asyncio.to_thread(
        storage.count_ops_events_by_severity, since=since)
    return {
        "since": since,
        "window_hours": window,
        "counts": {level: int(counts.get(level, 0)) for level in OPS_SEVERITIES},
    }


@app.get("/api/monitors")
async def list_monitors() -> dict:
    return {"monitors": manager.snapshots()}


@app.post("/api/monitors")
async def add_monitor(request: MonitorRequest) -> dict:
    unique_id = _normalize_unique_id(request.unique_id)
    try:
        collector = await manager.start(unique_id, record_video=request.record_video)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return collector.snapshot()


@app.post("/api/monitors/{unique_id}/stop")
async def stop_monitor(unique_id: str) -> dict:
    collector = _get_collector(unique_id)
    try:
        await manager.stop(unique_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return collector.snapshot()


@app.delete("/api/monitors/{unique_id}")
async def remove_monitor(unique_id: str) -> dict:
    _get_collector(unique_id)
    await manager.remove(unique_id)
    return {"removed": unique_id}


@app.post("/api/monitors/{unique_id}/record/start")
async def start_recording(unique_id: str) -> dict:
    collector = _get_collector(unique_id)
    try:
        await manager.start_recording(unique_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return collector.snapshot()


@app.post("/api/monitors/{unique_id}/record/stop")
async def stop_recording(unique_id: str) -> dict:
    collector = _get_collector(unique_id)
    try:
        await manager.stop_recording(unique_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return collector.snapshot()


@app.post("/api/monitors/{unique_id}/record-video")
async def set_record_video(unique_id: str, request: RecordVideoRequest) -> dict:
    collector = _get_collector(unique_id)
    await manager.set_record_video(unique_id, request.record_video)
    return collector.snapshot()


@app.get("/api/monitors/{unique_id}/record/live/{filename}")
async def live_recording(unique_id: str, filename: str) -> Response:
    path = manager.live_recording_file(unique_id, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="ライブ録画が見つかりません。")
    if path.suffix == ".m3u8":
        # ライブ録画中のplaylistはrecorderが追記し続けるため、stat時のsizeでContent-Length
        # を決めるFileResponseだと送信body長が超過し"Response content longer than
        # Content-Length"で落ちる。読み込んだbytesを返せばContent-Lengthが実体長と一致する。
        data = await asyncio.to_thread(path.read_bytes)
        return Response(
            content=data,
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "no-cache"},
        )
    return FileResponse(path, media_type="video/mp2t", headers={"Cache-Control": "no-cache"})


@app.get("/api/monitors/{unique_id}/timeline")
async def monitor_timeline(unique_id: str) -> dict:
    return _get_collector(unique_id).timeline_snapshot()


@app.get("/api/monitors/{unique_id}/summary")
async def monitor_summary(unique_id: str) -> dict:
    return _get_collector(unique_id).summary_snapshot()


@app.get("/api/monitors/{unique_id}/battles")
async def monitor_battles(unique_id: str) -> dict:
    return _get_collector(unique_id).battles_snapshot()


@app.get("/api/monitors/{unique_id}/history-stats")
async def monitor_history_stats(unique_id: str, limit: int = HISTORY_COMPARE_LIMIT) -> dict:
    limit = max(1, min(limit, 50))
    return storage.streamer_history_stats(unique_id, limit)


def _output_done(path: Optional[str]) -> bool:
    """True when a burned-in output (overlay mp4) already exists for this recording.
    The rendered file on disk is the source of truth (it is settings-invalidated and
    can be cleaned up), so output state is derived from the filesystem, not the DB."""
    if not path:
        return False
    try:
        return overlay_paths(Path(path))[0].is_file()
    except OSError:
        return False


# Disk remains the source of truth for output/upscale existence, but the session
# list re-stats every recording on each poll; a short TTL cache collapses those
# filesystem stat calls without duplicating the state into the DB.
_FS_STATE_TTL_SECONDS = 3.0
_fs_state_cache: dict = {}


def _recording_output_state(path: Optional[str]) -> tuple[bool, bool]:
    """(output_done, up_output_done) for a recording path, cached briefly to avoid
    re-stat'ing the same files on every session-list poll."""
    now = time.time()
    cached = _fs_state_cache.get(path)
    if cached is not None and cached[0] > now:
        return cached[1], cached[2]
    output_done = _output_done(path)
    up_output_done = bool(path) and upscale_done(Path(path))
    _fs_state_cache[path] = (now + _FS_STATE_TTL_SECONDS, output_done, up_output_done)
    return output_done, up_output_done


@app.get("/api/sessions")
async def list_sessions(limit: Optional[int] = None) -> dict:
    # limit省略時は設定の既定上限、limit<=0は全件(履歴のfilter/検索が最新N件で頭打ちにならないよう)。
    effective_limit = settings.get("session_list_limit") if limit is None else limit
    sessions = await asyncio.to_thread(storage.list_sessions, effective_limit)
    briefs = await asyncio.to_thread(storage.recordings_brief)
    active = manager.active_session_ids()
    # Per-session done badges: a Session is "済" only when every finished recording is
    # transcribed / output (all-done), so a partial Session still reads as not done.
    by_session: dict = {}
    for brief in briefs:
        by_session.setdefault(brief["session_id"], []).append(brief)
    # stats_json is persisted only at finalize, so a still-collecting session would
    # otherwise show stale/empty counts (battles included). Overlay the live stats.
    for session in sessions:
        recs = by_session.get(session["id"], [])
        states = [_recording_output_state(b["path"]) for b in recs]
        session["transcript_done"] = bool(recs) and all(b["has_transcript"] for b in recs)
        session["output_done"] = bool(recs) and all(s[0] for s in states)
        session["up_output_done"] = bool(recs) and all(s[1] for s in states)
        if session["id"] in active:
            collector = manager.get(session["unique_id"])
            if collector is not None and collector.session_id == session["id"]:
                session["stats"] = collector.stats
    return {
        "sessions": sessions,
        "active_session_ids": sorted(active),
    }


@app.get("/api/sessions/{session_id}")
async def session_detail(session_id: int) -> dict:
    session = _get_session_or_404(session_id)
    timeline = storage.session_timeline(session_id)
    timeline["bucket_seconds"] = session["bucket_seconds"]
    recordings = storage.recordings_for_session(session_id)
    transcribed = storage.transcribed_recording_ids()
    for rec in recordings:
        rec["has_transcript"] = rec["id"] in transcribed
        rec["has_output"] = _output_done(rec.get("path"))
        rec["has_up_output"] = bool(rec.get("path")) and upscale_done(Path(rec["path"]))
    return {
        "session": session,
        "timeline": timeline,
        "summary": storage.session_summary(session_id),
        "recordings": recordings,
        "owner": _session_owner(session),
        "battles": _battles_for_session(session),
    }


def _battles_for_session(session: dict) -> list:
    """Battles are persisted only when the session ends (_persist_final). While the
    session is still collecting, the live collector holds the authoritative, updating
    battle list, so serve that; once ended, read the saved rows.

    どちらの経路も勝敗はcore.battleの確定判定へ揃えて返す(live側はbattles_snapshot、
    保存側はbattles_for_sessionがannotate_result済み)。"""
    collector = manager.get(session["unique_id"])
    if collector is not None and collector.session_id == session["id"]:
        return collector.battles_snapshot()["battles"]
    return storage.battles_for_session(session["id"])


def _session_owner(session: dict) -> dict:
    """Owner identity for a stored session, so battle cards can render the monitored
    streamer's name/avatar (the own host) the same way the live snapshot does."""
    return {
        "unique_id": session["unique_id"],
        "nickname": session.get("owner_nickname") or session["unique_id"],
        "avatar": session.get("owner_avatar") or "",
    }


@app.get("/api/sessions/{session_id}/battles")
async def session_battles(session_id: int) -> dict:
    session = _get_session_or_404(session_id)
    return {
        "unique_id": session["unique_id"],
        "owner": _session_owner(session),
        "battles": _battles_for_session(session),
    }


@app.patch("/api/sessions/{session_id}")
async def update_session_note(session_id: int, request: NoteRequest) -> dict:
    _get_session_or_404(session_id)
    storage.set_note(session_id, request.note)
    return {"id": session_id, "note": request.note}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: int) -> dict:
    _get_session_or_404(session_id)
    if session_id in manager.active_session_ids():
        raise HTTPException(status_code=409, detail="収集中のSessionは削除できません。先に停止してください。")
    for recording in storage.recordings_for_session(session_id):
        _remove_recording_files(recording)
    storage.delete_session(session_id)
    return {"deleted": session_id}


@app.post("/api/sessions/delete-by-users")
async def delete_sessions_by_users(request: DeleteUsersRequest) -> dict:
    """Delete every session (and its recording files) belonging to the given
    streamers. Handle renames are followed via owner identity so a streamer's whole
    history is removed. Blocks if any target streamer is still collecting."""
    session_ids = storage.session_ids_for_users(request.unique_ids)
    if not session_ids:
        return {"deleted_sessions": 0}
    active = manager.active_session_ids()
    if any(session_id in active for session_id in session_ids):
        raise HTTPException(
            status_code=409,
            detail="収集中のSessionを含む配信者は削除できません。先に停止してください。",
        )
    for session_id in session_ids:
        for recording in storage.recordings_for_session(session_id):
            _remove_recording_files(recording)
    deleted = sum(1 for session_id in session_ids if storage.delete_session(session_id))
    return {"deleted_sessions": deleted}


@app.get("/api/sessions/{session_id}/export.csv")
async def export_session_csv(session_id: int) -> Response:
    session = _get_session_or_404(session_id)
    events = await asyncio.to_thread(storage.iter_events, session_id)

    def _rows():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["time", "kind", "user_unique_id", "user_nickname", "comment", "text", "gift_name", "gift_count", "diamonds", "like_count"]
        )
        yield "\ufeff" + buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        for event in events:
            writer.writerow(
                [
                    event["time"],
                    event["kind"],
                    event["user_unique_id"] or "",
                    event["user_nickname"] or "",
                    event["comment"] or "",
                    event["text"] or "",
                    event["gift_name"] or "",
                    event["gift_count"] if event["gift_count"] is not None else "",
                    event["diamonds"] if event["diamonds"] is not None else "",
                    event["count"] if event["count"] is not None else "",
                ]
            )
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    filename = f"tictok_session_{session_id}_{session['unique_id']}.csv"
    return StreamingResponse(
        _rows(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/sessions/{session_id}/export.json")
async def export_session_json(session_id: int) -> Response:
    session = _get_session_or_404(session_id)

    def _build() -> str:
        payload = {
            "session": session,
            "summary": storage.session_summary(session_id),
            "timeline": storage.session_timeline(session_id),
            "events": storage.iter_events(session_id),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    content = await asyncio.to_thread(_build)
    filename = f"tictok_session_{session_id}_{session['unique_id']}.json"
    return Response(
        content=content,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/recordings")
async def list_recordings() -> dict:
    return {
        "ffmpeg_available": ffmpeg_available(),
        "recordings": storage.list_recordings(settings.get("session_list_limit")),
    }


def _disk_volume_paths() -> list:
    """Every volume the running install writes to: the working dir (HLS + capture),
    the final dir (relocation target and where outputs are generated), the DB and the
    logs. These routinely sit on different drives, so only a per-volume reading says
    which one is about to fill up."""
    return [RECORD_DIR, FINAL_DIR, get_db_path(), get_log_dir()]


def _disk_min_free_bytes() -> int:
    """Free-space floor below which heavy outputs are refused. Deliberately separate
    from the log-only preflight threshold (get_log_disk_low_bytes): that one warns,
    this one blocks, and an operator who wants a louder warning must not thereby
    change what is allowed to run."""
    return int(settings.get("disk_min_free_gb")) * 1024 * 1024 * 1024


def _disk_report(paths=None) -> dict:
    """Per-volume free space with the volumes that are already below the floor named.
    ``low_volumes`` is empty when the gate is disabled (floor 0), which keeps the
    "blocked" state and the "measured" state distinguishable in the UI."""
    report = disk_free_by_volume(_disk_volume_paths() if paths is None else paths)
    floor = _disk_min_free_bytes()
    low = sorted(v for v, info in report.items() if info["free_bytes"] < floor) if floor else []
    return {"volumes": report, "min_free_bytes": floor, "low_volumes": low}


def _require_disk_space(paths, stage: str, **ctx) -> None:
    """Refuse to start a job that writes a large intermediate when a volume it needs is
    below the configured floor. Disk exhaustion has surfaced here as symptoms with no
    visible relation to disk (avatars vanishing from a burn-in, emoji turning
    monochrome), so the check runs before the work rather than after the damage."""
    floor = _disk_min_free_bytes()
    if floor <= 0:
        return
    report = disk_free_by_volume(paths)
    low = sorted(v for v, info in report.items() if info["free_bytes"] < floor)
    if not low:
        return
    logger.warning(
        "refused %s: free disk space below the configured floor on %s", stage, ", ".join(low),
        extra={"event": "disk.gate_blocked",
               "ctx": {"volumes": report, "low_volumes": low, "min_free_bytes": floor,
                       "stage": stage, **ctx}},
    )
    shortest = min(report[v]["free_bytes"] for v in low)
    raise HTTPException(
        status_code=507,
        detail=(f"空き容量が不足しています（{', '.join(low)}: 残り{shortest / (1024 ** 3):.1f}GB / "
                f"下限{floor / (1024 ** 3):.0f}GB）。不要なfileを削除するか、設定の"
                f"「出力を拒否する空き容量の下限（GB）」を見直してください。"),
    )


@app.get("/api/disk")
async def disk_status_api() -> dict:
    """録画・出力が使うdrive別の空き容量と、出力を拒否する下限。画面に常時表示する。"""
    return _disk_report()


# ---- 容量内訳と保持policy(retention) ----------------------------------------------
# 走査は数TB規模のHDDで分単位かかるblocking I/O。GETは常にDBのcacheを返し、再走査は
# operatorの明示操作だけが起こす。削除も同様で、設定値だけでは何も消えない: 必ずdry-run
# (POST /api/storage/retention) の結果を見せ、確認付きのapplyでのみ実行する。
_storage_scan_lock = asyncio.Lock()
_retention_lock = asyncio.Lock()


class RetentionRequest(BaseModel):
    # 既定がdry-runなのは意図的。bodyを付け忘れたrequestが削除を走らせてはならない。
    apply: bool = False
    confirm: bool = False


class ProtectRequest(BaseModel):
    protected: bool


def _retention_rules() -> dict:
    """保持policyの設定値。閾値はすべてSETTING_DEFS側にあり、ここは読み替えのみ。"""
    return {
        "transient_hours": int(settings.get("retention_transient_hours")),
        "derived_days": int(settings.get("retention_derived_days")),
        "source_days": int(settings.get("retention_source_days")),
        "source_enabled": bool(settings.get("retention_source_enabled")),
    }


def _retention_path(recording: dict) -> Optional[Path]:
    """録画pathをrecord root配下へ解決する。範囲外・不正pathは削除候補にしない。"""
    raw = recording.get("path")
    if not raw:
        return None
    try:
        return _safe_recording_path(raw)
    except HTTPException:
        return None


def _retention_free_target_bytes() -> int:
    return int(settings.get("retention_free_target_gb")) * 1024 * 1024 * 1024


def _retention_free_reached() -> bool:
    """全volumeが打ち切り目標の空き容量に達したか。目標0(=打ち切らない)は常にFalse。

    読めなかったvolumeは判定へ入れない。空き容量が不明なものを「足りている」とみなすと、
    削除を止めるべき場面で止まらなくなる。"""
    target = _retention_free_target_bytes()
    if target <= 0:
        return False
    report = disk_free_by_volume(_disk_volume_paths())
    if not report:
        return False
    return all(info["free_bytes"] >= target for info in report.values())


def _build_retention_plan() -> dict:
    recordings = storage.recordings_for_retention()
    plan = retention.build_plan(
        recordings, _RECORD_ROOTS, _retention_path, _retention_rules(), time.time()
    )
    plan["rules"] = _retention_rules()
    plan["free_target_bytes"] = _retention_free_target_bytes()
    plan["protected_count"] = sum(1 for rec in recordings if rec.get("protected"))
    return plan


def _delete_transient_item(item: dict) -> int:
    """中断したrenderの残骸を1件削除し、解放bytesを返す。個々の失敗は握り潰さずlogへ残す。"""
    path = Path(item["path"])
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning(
            "failed to remove orphaned render intermediate %s", path.name,
            extra={"event": "retention.remove_failed",
                   "ctx": {"path": str(path), "phase": retention.PHASE_TRANSIENT}},
            exc_info=True,
        )
        return 0
    return int(item["bytes"])


def _delete_derived_item(item: dict) -> int:
    """1録画分の派生物(焼き込み・Up出力)を、削除endpointと同じcleanup関数で消す。"""
    src = Path(item["path"])
    cleanup_overlay_files(src)
    cleanup_upscale_files(src)
    return int(item["bytes"])


def _delete_source_item(item: dict) -> int:
    """生録画をfileごと消し、録画行も落とす(単体削除endpointと同じ後始末)。"""
    recording = storage.get_recording(item["recording_id"])
    if recording is None:
        return 0
    _remove_recording_files(recording)
    storage.delete_recording(item["recording_id"])
    return int(item["bytes"])


_RETENTION_DELETERS = {
    retention.PHASE_TRANSIENT: _delete_transient_item,
    retention.PHASE_DERIVED: _delete_derived_item,
    retention.PHASE_SOURCE: _delete_source_item,
}


def _apply_retention(plan: dict) -> dict:
    """planを実行順(transient -> derived -> source)に消す。打ち切り目標に達したら停止する。

    実行のたびにfileが消えて空きが増えるので、目標判定はphaseの区切りで測り直す。"""
    removed = {phase: {"items": 0, "bytes": 0} for phase in retention.PHASE_ORDER}
    stopped = ""
    for phase in plan["phases"]:
        key = phase["phase"]
        if not phase["enabled"]:
            continue
        deleter = _RETENTION_DELETERS[key]
        for item in phase["items"]:
            if _retention_free_reached():
                stopped = key
                break
            freed = deleter(item)
            if freed:
                removed[key]["items"] += 1
                removed[key]["bytes"] += freed
        if stopped:
            break
    return {"removed": removed, "stopped_at": stopped,
            "freed_bytes": sum(entry["bytes"] for entry in removed.values()),
            "removed_items": sum(entry["items"] for entry in removed.values())}


@app.get("/api/storage/usage")
async def storage_usage_api() -> dict:
    """保存済みの容量内訳(配信者別・種別別)。まだ走査していなければ scan は null で返す。"""
    cached = await asyncio.to_thread(storage.get_storage_scan)
    return {
        "scan": cached,
        "roots": [str(root) for root in _RECORD_ROOTS],
        "disk": _disk_report(),
        "scanning": _storage_scan_lock.locked(),
    }


@app.post("/api/storage/scan")
async def storage_scan_api() -> dict:
    """録画root配下を走査し直して容量内訳のcacheを更新する。数TB規模では分単位かかる。"""
    if _storage_scan_lock.locked():
        raise HTTPException(status_code=409, detail="容量の再scanが既に実行中です。")
    async with _storage_scan_lock:
        async with _tracked_job("storage", "容量scan") as job_id:
            started = time.monotonic()
            usage = await asyncio.to_thread(disk_scan.scan_roots, _RECORD_ROOTS)
            duration_ms = (time.monotonic() - started) * 1000
            await asyncio.to_thread(storage.save_storage_scan, usage, duration_ms)
            storage.record_ops_event(
                logger, "storage.scan_completed",
                "storage usage scan completed: {files} file(s), {gb:.1f}GB".format(
                    files=usage["total_files"], gb=usage["total_bytes"] / (1024 ** 3)),
                job_id=job_id, duration_ms=duration_ms,
                detail={"total_bytes": usage["total_bytes"],
                        "total_files": usage["total_files"],
                        "streamers": len(usage["streamers"]),
                        "errors": len(usage["errors"])},
            )
    return await storage_usage_api()


@app.post("/api/storage/retention")
async def storage_retention_api(request: RetentionRequest) -> dict:
    """保持policyのdry-run(既定)と実行。実行には apply と confirm の両方が要る。

    削除順序は (1)中断renderの残骸 (2)作り直せる派生物 (3)生録画 で固定する。生録画は唯一の
    再取得不能資産で、先に消すと再出力も文字起こしも復旧できなくなるため、順序は入れ替えない。"""
    if _retention_lock.locked():
        raise HTTPException(status_code=409, detail="保持policyの処理が既に実行中です。")
    async with _retention_lock:
        plan = await asyncio.to_thread(_build_retention_plan)
        if not request.apply:
            storage.record_ops_event(
                logger, "retention.previewed",
                "retention dry-run: {items} item(s), {gb:.1f}GB reclaimable".format(
                    items=plan["total_items"], gb=plan["total_bytes"] / (1024 ** 3)),
                detail={"rules": plan["rules"], "total_bytes": plan["total_bytes"],
                        "by_phase": {p["phase"]: {"items": len(p["items"]),
                                                  "bytes": p["bytes"],
                                                  "enabled": p["enabled"]}
                                     for p in plan["phases"]}},
            )
            return {"applied": False, "plan": plan}
        if not request.confirm:
            raise HTTPException(status_code=400,
                                detail="削除内容の確認が取れていません。dry-runの結果を確認してから実行してください。")
        # 焼き込みが動いている間のsidecarは「残骸」ではなく実行中のfileなので、GPU jobの
        # 有無を見て中断renderの掃除を丸ごと見送る(経過時間の猶予だけでは足りない)。
        if _media_job_running():
            raise HTTPException(status_code=409,
                                detail="焼き込み/Up出力の実行中は保持policyを実行できません。完了後に再実行してください。")
        async with _tracked_job("retention", "保持policyの実行") as job_id:
            result = await asyncio.to_thread(_apply_retention, plan)
            storage.record_ops_event(
                logger, "retention.applied",
                "retention applied: removed {items} item(s), freed {gb:.1f}GB{stop}".format(
                    items=result["removed_items"], gb=result["freed_bytes"] / (1024 ** 3),
                    stop=f" (stopped at {result['stopped_at']})" if result["stopped_at"] else ""),
                job_id=job_id,
                detail={"rules": plan["rules"], "removed": result["removed"],
                        "stopped_at": result["stopped_at"],
                        "free_target_bytes": plan["free_target_bytes"]},
            )
    return {"applied": True, "plan": plan, "result": result, "disk": _disk_report()}


@app.post("/api/recordings/{recording_id}/protect")
async def protect_recording(recording_id: int, request: ProtectRequest) -> dict:
    """保持policyの自動削除からこの録画を除外する(または除外を解除する)。"""
    if not storage.set_recording_protected(recording_id, request.protected):
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    storage.record_ops_event(
        logger, "retention.protection_changed",
        f"recording protection {'enabled' if request.protected else 'disabled'}",
        recording_id=recording_id, detail={"protected": request.protected},
    )
    return {"recording_id": recording_id, "protected": request.protected}


@app.delete("/api/recordings/{recording_id}/derived")
async def delete_recording_derived(recording_id: int) -> dict:
    """この録画の派生物(焼き込み・Up出力・renderの中間file)だけを消し、元録画は残す。

    既存のDELETEは元録画ごと消すため、容量を空けたいだけの操作にはこちらを使う。"""
    recording = storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    path = _safe_recording_path(recording["path"])
    freed = await asyncio.to_thread(
        retention.artifact_bytes,
        overlay_artifact_paths(path) + overlay_transient_paths(path)
        + upscale_artifact_paths(path),
    )
    await asyncio.to_thread(cleanup_overlay_files, path)
    await asyncio.to_thread(cleanup_upscale_files, path)
    storage.record_ops_event(
        logger, "retention.derived_removed",
        f"derived artifacts removed for recording #{recording_id}",
        recording_id=recording_id, detail={"freed_bytes": freed, "stem": path.stem},
    )
    return {"recording_id": recording_id, "freed_bytes": freed}


def _recording_for_output(recording_id: int) -> tuple[dict, Path]:
    recording = storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    path = _safe_recording_path(recording["path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="録画fileが存在しません（削除済みか録画失敗）。")
    # Outputs (comment layer, CFR base, the rendered mp4, the upscaled mp4) are all
    # written beside the source, so that volume is the one that has to hold them.
    _require_disk_space([path.parent], "output", recording_id=recording_id)
    return recording, path


def _subtitle_transcript(recording_id: int) -> Optional[dict]:
    """字幕焼き込みに使うtranscript。設定がOFFならNone。

    設定がONなのに転写が無い / 時刻mapが現行版でない / 出せるsegmentが無い場合は、字幕なしで
    焼かずに拒否する。焼き込みは元に戻せない成果物なので、ズレた字幕や無言の欠落を作るより
    先に転写をやり直させる方が安い(提案書②-4の必須条件(c))。"""
    if not subtitles_enabled(settings):
        return None
    transcript = storage.get_transcript(recording_id)
    if transcript is None:
        raise HTTPException(
            status_code=409,
            detail="字幕の焼き込みが有効ですが、この録画は文字起こしがありません。先に文字起こしを実行してください。",
        )
    if not subtitles.timemap_current(transcript.get("timemap_version")):
        raise HTTPException(
            status_code=409,
            detail="この録画の文字起こしは古い時刻mapで作られており、字幕が動画とズレます。文字起こしをやり直してから焼き込んでください。",
        )
    if not subtitles.usable_segments(transcript.get("segments")):
        raise HTTPException(
            status_code=409,
            detail="この録画の文字起こしに、字幕として焼き込めるsegmentがありません。",
        )
    return transcript


async def _burn_in_recording(recording: dict, path: Path, job_id: str,
                             on_stage_pct) -> dict:
    """Render one recording's burn-in, reporting stage progress to both the legacy
    per-recording websocket message (which the open page's row spinner reads) and the job
    registry (which survives a reload). Returns the ensure_overlay result, or an empty
    dict when the burn-in is off / the recording has no session to draw from."""
    recording_id = recording["id"]
    if not (overlay_enabled(settings) and recording.get("session_id") is not None):
        return {}
    transcript = _subtitle_transcript(recording_id)
    events = storage.iter_events(
        recording["session_id"], recording["started_at"], recording.get("ended_at")
    )
    battles = storage.battles_for_session(recording["session_id"])

    async def _emit_progress(pct: int) -> None:
        await hub.broadcast(
            {"type": "output_progress", "recording_id": recording_id, "pct": pct}
        )
        await on_stage_pct("焼き込み", pct)

    try:
        async with _job_ops("overlay", recording_id, stem=path.stem, events=len(events),
                            job_registry_id=job_id):
            return await ensure_overlay(
                str(path), recording["started_at"], recording.get("ended_at"),
                events, settings, battles=battles, on_progress=_emit_progress,
                transcript=transcript,
            )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def _overlay_payload(result: dict, path: Path) -> tuple[Path, dict]:
    """(rendered path, extra payload) for an ensure_overlay result."""
    rendered = path
    payload: dict = {}
    if result:
        rendered = _safe_recording_path(str(result["a"]))
        # Mode B (source-clock timing) comparison output, present only when the
        # compare setting is on and the recording carried create_time to anchor on.
        out_b = result.get("b")
        if out_b is not None:
            rendered_b = _safe_recording_path(str(out_b))
            payload["filename_b"] = rendered_b.name
            payload["output_path_b"] = str(rendered_b)
    return rendered, payload


def _preview_sources(recording_id: int) -> tuple:
    """プレビュー1回ぶんの入力 (recording, path, events, battles, transcript)。
    焼き込み本体(_burn_in_recording)と同じ源から、同じ窓で取る。ここが違うと
    プレビューと本出力で描くeventが変わり、確認の意味が消える。"""
    recording, path = _recording_for_output(recording_id)
    if not overlay_enabled(settings):
        raise HTTPException(
            status_code=409,
            detail="焼き込みの設定が全てOFFです。Comment/Gift/Battle/字幕のいずれかを有効にしてください。",
        )
    if recording.get("session_id") is None:
        raise HTTPException(
            status_code=409, detail="この録画にはSessionが紐づいておらず、焼き込むeventがありません。",
        )
    transcript = _subtitle_transcript(recording_id)
    events = storage.iter_events(
        recording["session_id"], recording["started_at"], recording.get("ended_at")
    )
    battles = storage.battles_for_session(recording["session_id"])
    return recording, path, events, battles, transcript


@app.post("/api/recordings/{recording_id}/preview/still")
async def preview_still_api(recording_id: int, at: Optional[float] = None) -> dict:
    """焼き込み設定の静止画プレビュー。動画encode・comment layerのpipe・CFR pre-passを
    通らないので数秒で返る。``at`` 未指定ならComment/Gift/Battleが最も濃い時刻を自動で選ぶ。"""
    recording, path, events, battles, transcript = _preview_sources(recording_id)
    try:
        result = await preview_still(
            str(path), recording["started_at"], recording.get("ended_at"),
            events, settings, battles=battles, transcript=transcript, at_seconds=at,
        )
    except NothingToDrawError as exc:
        # 入力に描く対象が無いだけで、serverは正常。_preview_sourcesの他の前提不成立と
        # 同じ409に揃える(5xxにすると監視とlogがserver errorとして数える)。
        raise HTTPException(status_code=409, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "recording_id": recording_id,
        "at_seconds": result["at_seconds"],
        "window_auto": result["window_auto"],
        "comments_drawn": result["comments_drawn"],
        "video_duration_seconds": result["video_duration_seconds"],
        "url": f"/api/recordings/{recording_id}/preview/still.png?v={int(time.time())}",
    }


@app.get("/api/recordings/{recording_id}/preview/still.png")
async def preview_still_image(recording_id: int) -> FileResponse:
    recording = storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    still = preview_paths(_safe_recording_path(recording["path"]))[0]
    if not still.is_file():
        raise HTTPException(status_code=404, detail="プレビュー画像がまだ生成されていません。")
    # 設定を変えるたびに作り直す一時的な確認物なので、browserにcacheさせない。
    return FileResponse(still, media_type="image/png",
                        headers={"Cache-Control": "no-store"})


@app.post("/api/recordings/{recording_id}/preview/clip")
async def preview_clip_api(recording_id: int) -> dict:
    """焼き込み設定の動画プレビューをqueueへ載せる。本出力と同じ解像度・codec・qualityで、
    尺だけをmedia PTS窓で切る。応答はjob_idのみ(完了はWSのjob_updateで届く)。"""
    recording, path, _events, _battles, _transcript = _preview_sources(recording_id)
    return await _enqueue_media_job("overlay_preview", recording_id, recording=recording,
                                    stem=path.stem)


@app.get("/api/recordings/{recording_id}/preview/clip.mp4")
async def preview_clip_video(recording_id: int) -> FileResponse:
    recording = storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    clip = preview_paths(_safe_recording_path(recording["path"]))[1]
    if not clip.is_file():
        raise HTTPException(status_code=404, detail="プレビュー動画がまだ生成されていません。")
    return FileResponse(clip, media_type="video/mp4",
                        headers={"Cache-Control": "no-store"})


MEDIA_JOB_TITLES = {"overlay": "焼き込み", "upscale": "Up出力", "reprocess": "再mp4化",
                    "overlay_preview": "焼き込みプレビュー", "clip_batch": "clip一括書き出し"}


async def _enqueue_media_job(kind: str, recording_id: int, *, group_id: str = "",
                             recording: Optional[dict] = None,
                             stem: str = "", params: Optional[dict] = None) -> dict:
    """映像jobを1件queueへ載せ、job_idを返す。

    実行はworkerが行うため、この応答に出力file名は含まれない(完了時のfile名はjobのresultと
    WSのjob_updateで届く)。同じ録画・同じ種別が既にqueueに居るときは二重投入を拒む: 同一
    出力pathへ2本走らせても片方の成果は必ず捨てられ、GPUを二重に占有するだけになる。
    """
    if media_job_queue.pending_for(kind, recording_id) is not None:
        raise HTTPException(
            status_code=409,
            detail=f"この録画の{MEDIA_JOB_TITLES[kind]}は既にqueueにあります（jobで確認できます）。",
        )
    if kind in ("overlay", "upscale", "overlay_preview"):
        # 字幕焼き込みが有効なら、転写が揃っているかを投入時に確かめる。workerで初めて
        # 落とすと、GPUの順番を待った末に失敗することになる。
        _subtitle_transcript(recording_id)
    job_id = secrets.token_hex(4)
    row = await media_job_queue.enqueue(
        job_id, kind, recording_id,
        session_id=(recording or {}).get("session_id"), group_id=group_id,
        title=f"{MEDIA_JOB_TITLES[kind]} {stem}".strip(), params=params,
    )
    return {"job_id": job_id, "kind": kind, "recording_id": recording_id,
            "state": row["state"], "queued_at": row["queued_at"]}


async def _run_preview_clip_job(recording_id: int, report) -> dict:
    """動画プレビューをqueueのworkerとして実行する。焼き込み本体と違い成果物はsidecarの
    <name>.preview.mp4 だけで、本出力のmp4にもそのcache判定にも触れない。"""
    recording, path, events, battles, transcript = _preview_sources(recording_id)

    async def _emit_progress(pct: int) -> None:
        await report("プレビュー焼き込み", pct)

    try:
        async with _job_ops("overlay_preview", recording_id, stem=path.stem,
                            events=len(events)):
            try:
                result = await preview_clip(
                    str(path), recording["started_at"], recording.get("ended_at"),
                    events, settings, battles=battles, transcript=transcript,
                    on_progress=_emit_progress,
                )
            except NothingToDrawError as exc:
                # 静止画側は409で返している同じ前提不成立。job経路はHTTP statusを持たない
                # ため、失敗ではなくskippedとして着地させる(RuntimeErrorの下で拾うと
                # 500→job failedになり、静止画と動画で結論が食い違う)。
                raise JobSkipped(str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    win_start, win_end = result["window"]
    return {
        "recording_id": recording_id,
        "filename": Path(result["path"]).name,
        "output_path": str(result["path"]),
        "window_start_seconds": round(win_start, 3),
        "window_end_seconds": round(win_end, 3),
        "window_auto": result["window_auto"],
        "cached": result["cached"],
        "url": f"/api/recordings/{recording_id}/preview/clip.mp4",
    }


async def _run_clip_batch_job(job: dict, report) -> dict:
    """1録画ぶんの範囲listを順に切り出す。GPUは使わないがdiskは食うので、queueに載せて
    直列に流す(browserを閉じても続き、job画面から取り消せる)。"""
    recording_id = job["recording_id"]
    params = job.get("params") or {}
    ranges = params.get("ranges") or []
    recording = storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    src = _clip_source(recording, params.get("variant") or "source")
    normalize = _clip_normalize(params.get("normalize_audio"))
    precise = bool(params.get("precise"))
    total = len(ranges)
    files = []
    total_bytes = 0
    for index, item in enumerate(ranges):
        cancel.check_cancelled()
        await report(f"({index + 1}/{total}) 切り出し中",
                     int(index * 100 / total) if total else 0)
        try:
            async with _job_ops("clip", recording_id, stem=src.stem,
                                variant=params.get("variant") or "source",
                                job_registry_id=job["job_id"],
                                **audio_norm.describe(normalize)):
                result = await make_clip(
                    src, float(item["start"]), float(item["end"]), item.get("label"),
                    precise, normalize=normalize)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        files.append(result["filename"])
        total_bytes += result["bytes"]
    return {"recording_id": recording_id, "count": len(files), "files": files,
            "filename": files[0] if len(files) == 1 else "",
            "bytes": total_bytes, "variant": params.get("variant") or "source",
            "normalized": bool(normalize), "precise": precise}


@contextmanager
def _input_precondition():
    """job runner内で、入力側の前提不成立(404)を失敗ではなくskipへ落とす。

    録画行やfileが無いのは待っても変わらないので、media_queueのretryでbackoffを消費してから
    赤いfailedとして残すのは誤り。取り消しと同じ「正常な終わり方」へ畳む。"""
    try:
        yield
    except HTTPException as exc:
        if exc.status_code == 404:
            raise JobSkipped(str(exc.detail)) from exc
        raise


async def _run_media_job(job: dict, report) -> dict:
    """queueが1件を実行する本体。stage進捗は report(stage, pct) でqueueへ返す。"""
    kind = job["kind"]
    recording_id = job["recording_id"]
    job_id = job["job_id"]
    if kind == "reprocess":
        recording = storage.get_recording(recording_id)
        if recording is None:
            raise JobSkipped("録画が見つかりません（削除済み）。")
        return await _reprocess_recording(recording_id, recording, job_id, report)
    if kind == "overlay_preview":
        return await _run_preview_clip_job(recording_id, report)
    if kind == "clip_batch":
        return await _run_clip_batch_job(job, report)
    if kind not in ("overlay", "upscale"):
        raise HTTPException(status_code=400, detail=f"未知のjob種別です: {kind}")
    with _input_precondition():
        recording, path = _recording_for_output(recording_id)
    result = await _burn_in_recording(recording, path, job_id, report)
    rendered, payload = _overlay_payload(result, path)
    payload.update({
        "recording_id": recording_id,
        "filename": rendered.name,
        "output_path": str(rendered),
        "rendered": rendered != path,
    })
    if kind == "upscale":
        out = await _upscale_rendered(rendered, recording_id, job_id, report)
        payload.update({"filename": out.name, "output_path": str(out),
                        "source": rendered.name})
    return payload


@app.post("/api/recordings/{recording_id}/output")
async def output_recording(recording_id: int) -> dict:
    """設定でComment/Gift演出が有効なら、収集eventを焼き込んだ動画をrecordings folderへ
    出力する。実処理は永続queueのworkerが行い、この応答はjob_idを即時返す(出力file名は
    完了時のjob resultで届く)。録画・空き容量のcheckは投入時に済ませ、実行を待たずに
    弾けるようにしている。"""
    recording, path = _recording_for_output(recording_id)
    return await _enqueue_media_job("overlay", recording_id, recording=recording,
                                    stem=path.stem)


def _find_hls_root(stem: str) -> Path | None:
    """The record root actually holding this recording's HLS segments
    (<root>/<streamer>/ts/<stem>/seg*.ts), or None. Both roots are searched because a
    manual move can leave the DB path stale."""
    for root in _RECORD_ROOTS:
        seg_dir = layout.session_dir(root, stem)
        if seg_dir.is_dir() and any(seg_dir.glob("seg*.ts")):
            return root
    return None


def _existing_recording_mp4(stem: str) -> Path | None:
    """The recording's current mp4 across either record root, or None."""
    for root in _RECORD_ROOTS:
        cand = layout.mp4_path(root, stem)
        if cand.is_file():
            return cand
    return None


@app.post("/api/recordings/{recording_id}/reprocess")
async def reprocess_recording(recording_id: int) -> dict:
    """録画をその保持HLS(.ts)から、実録画と同一のfinalizeパイプライン(concat→timing map再生成→
    単一解像度normalize)で作り直す。混在解像度でPlayerがカクつく録画を、元の.tsから正しく1解像度へ
    直すための経路。mp4は上書きせず既存を _backup/ へ退避し、成功時のみ差し替える(失敗時は復元)。.ts
    が残っていない録画は再mp4化できない。進捗は reprocess_progress でWS通知。"""
    recording = storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    if recording.get("status") == "recording":
        raise HTTPException(status_code=409, detail="録画中のため再mp4化できません。")
    return await _enqueue_media_job("reprocess", recording_id, recording=recording,
                                    stem=f"#{recording_id}")


async def _reprocess_recording(recording_id: int, recording: dict, job_id: str,
                               on_stage_pct) -> dict:
    if recording.get("status") == "recording":
        raise HTTPException(status_code=409, detail="録画中のため再mp4化できません。")
    if not (ffmpeg_available() and ffprobe_available()):
        raise HTTPException(status_code=503, detail="ffmpeg/ffprobeが利用できません。")
    stem = Path(recording.get("filename") or recording.get("path") or "").stem
    if not stem:
        raise HTTPException(status_code=400, detail="録画の識別子が不正です。")
    record_root = _find_hls_root(stem)
    if record_root is None:
        raise HTTPException(
            status_code=409,
            detail="元の.tsセグメントが見つかりません（このファイルは再mp4化できません）。",
        )
    final_mp4 = layout.mp4_path(record_root, stem)

    # Back up the current mp4 before finalize overwrites <stem>.mp4; keep it on success,
    # restore it if the re-finalize fails so the recording is never left without a file.
    backup_path: Path | None = None
    existing = _existing_recording_mp4(stem)
    if existing is not None:
        backup_dir = record_root / "_backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{stem}.mp4"
        n = 1
        while backup_path.exists():
            backup_path = backup_dir / f"{stem}.{n}.mp4"
            n += 1
        # 退避先はmoveの「前」に記録する。moveの直後に落ちた場合、job行に退避先が無ければ
        # 起動時のrecoveryはmp4の在り処を知る手段が無く、録画がfileの無い状態で残る。
        storage.set_media_job_result(
            job_id, {"backup_path": str(backup_path), "final_path": str(final_mp4)})
        await asyncio.to_thread(shutil.move, str(existing), str(backup_path))

    async def _restore_backup() -> None:
        if backup_path is not None and not final_mp4.is_file():
            await asyncio.to_thread(shutil.move, str(backup_path), str(final_mp4))

    async def _emit_progress(pct: int) -> None:
        await hub.broadcast(
            {"type": "reprocess_progress", "recording_id": recording_id, "pct": pct}
        )
        await on_stage_pct("再mp4化", pct)

    await _emit_progress(0)
    recorder = Recorder(
        recording.get("unique_id") or stem, str(record_root),
        recording.get("session_id"), keep_hls=True, final_dir=str(record_root),
        storage=storage,
    )
    try:
        await recorder.finalize_recovered_hls(stem, on_progress=_emit_progress)
    except Exception as exc:
        logger.exception("reprocess failed for recording %s", recording_id)
        await _restore_backup()
        raise HTTPException(status_code=500, detail=f"再mp4化に失敗しました: {exc}")

    snap = recorder.snapshot()
    out = recorder.output_path
    if out is None or not Path(out).is_file() or snap.get("bytes", 0) <= 0 \
            or recorder.state != "completed":
        await _restore_backup()
        raise HTTPException(
            status_code=500,
            detail="再mp4化が有効なmp4を生成できませんでした（元ファイルは復元しました）。",
        )
    # The regenerated mp4's path can differ from the (possibly stale) DB value, so update it.
    storage.update_recording(
        recording_id, recorder.state, str(out), Path(out).name,
        recorder.ended_at, snap["bytes"], recorder.error,
    )
    await _emit_progress(100)
    return {
        "recording_id": recording_id,
        "filename": Path(out).name,
        "output_path": str(out),
        "bytes": snap["bytes"],
        "backup": str(backup_path) if backup_path is not None else None,
    }


@app.get("/api/upscale/status")
async def upscale_status_api() -> dict:
    return upscale_status()


async def _upscale_rendered(rendered: Path, recording_id: int, job_id: str,
                            on_stage_pct) -> Path:
    """Super-resolve an already-rendered video. The stage progress goes to the legacy
    per-recording message and to the job registry, same as the burn-in stage."""
    encoder = await video_encoder_name(codec_family(settings.get("video_overlay_codec")))
    loop = asyncio.get_running_loop()
    last_pct = -1

    def on_progress(done: float, total: float) -> None:
        nonlocal last_pct
        pct = min(100, int(done / total * 100)) if total > 0 else 0
        if pct == last_pct:
            return
        last_pct = pct
        asyncio.run_coroutine_threadsafe(
            _report_upscale_pct(recording_id, pct, on_stage_pct), loop,
        )

    try:
        async with _job_ops("upscale", recording_id, stem=rendered.stem, encoder=encoder,
                            job_registry_id=job_id):
            out = await asyncio.to_thread(
                ensure_upscaled, str(rendered), encoder,
                int(settings.get("video_overlay_quality")), on_progress,
                _output_normalize(),
            )
    except UpscaleError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    await _report_upscale_pct(recording_id, 100, on_stage_pct)
    return out


async def _report_upscale_pct(recording_id: int, pct: int, on_stage_pct) -> None:
    await hub.broadcast(
        {"type": "upscale_progress", "recording_id": recording_id, "pct": pct}
    )
    await on_stage_pct("高画質化", pct)


@app.post("/api/recordings/{recording_id}/upscale-output")
async def upscale_output_recording(recording_id: int) -> dict:
    """AI高画質化(超解像)出力。焼き込みが有効な場合はまず通常の出力(焼き込み)を確保し
    (進捗はoutput_progress)、その動画をローカルAI modelで高画質化して .up.mp4 として
    recordings folderへ出力する(進捗はupscale_progress)。実処理は永続queueのworkerで、
    この応答はjob_idを即時返す。"""
    recording, path = _recording_for_output(recording_id)
    return await _enqueue_media_job("upscale", recording_id, recording=recording,
                                    stem=path.stem)


def _existing_recording_file(recording: dict) -> Optional[Path]:
    """録画行が指す実在のmp4。path不正・削除済み・finalize未完(録画dirのまま)ならNone。"""
    try:
        path = _safe_recording_path(recording.get("path") or "")
    except HTTPException:
        return None
    return path if path.is_file() else None


def _session_output_targets(session_id: int) -> list:
    """Recordings of a session that can be output, in the order they were made.

    statusだけで選ぶと、fileが消えた/finalizeが完走しなかった行までqueueへ載り、workerが
    1件ずつ404で落ちる。単体の出力APIは投入時にfileの実在を見て弾いているので、session
    一括でも同じ条件で絞る。"""
    if storage.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Sessionが見つかりません。")
    finished = [r for r in storage.recordings_for_session(session_id)
                if r.get("status") in ("completed", "interrupted")]
    targets = [r for r in finished if _existing_recording_file(r) is not None]
    if not targets:
        raise HTTPException(
            status_code=409,
            detail=("この Session の録画は録画fileが残っていません（削除済みか録画失敗）。"
                    if finished else "出力できる録画がありません。"),
        )
    return targets


async def _start_session_output(session_id: int, upscale: bool) -> dict:
    """Session内の録画を1本ずつqueueへ載せる。

    投入は録画ごとの行だが、履歴画面のSession行が見るのは1つの進捗なので、同じ group_id を
    振ってqueue側でsession単位のjobへ畳み直す(media_queue.group_payload)。行を分けるのは、
    再起動しても残りの録画が実行されること・1本だけ取り消せることの2点のためで、どちらも
    session全体を1 jobにすると実現できない。
    """
    targets = _session_output_targets(session_id)
    # 実行はworkerなので、投入時点で下限割れなら即答する(全件がworkerで失敗するより早い)。
    _require_disk_space(_disk_volume_paths(), "session_output", session_id=session_id)
    # 字幕焼き込みが有効な場合、1本でも転写が欠けていれば Session 全体を止める。半分だけ
    # 字幕付きの出力が並ぶ状態は、どれが字幕付きか後から判別できず運用を壊す。
    if subtitles_enabled(settings):
        missing = [t["id"] for t in targets if storage.get_transcript(t["id"]) is None]
        if missing:
            raise HTTPException(
                status_code=409,
                detail=(f"字幕の焼き込みが有効ですが、文字起こしが無い録画が{len(missing)}件あります"
                        "（録画 #" + ", #".join(str(i) for i in missing[:5])
                        + ("…" if len(missing) > 5 else "")
                        + "）。先にSessionの文字起こしを実行してください。"),
            )
        for target in targets:
            _subtitle_transcript(target["id"])
    kind = "upscale" if upscale else "overlay"
    group_id = secrets.token_hex(4)
    title = ("Session Up出力" if upscale else "Session出力") + f" #{session_id}"
    queued: list[str] = []
    skipped: list[int] = []
    for target in targets:
        if media_job_queue.pending_for(kind, target["id"]) is not None:
            skipped.append(target["id"])
            continue
        job_id = secrets.token_hex(4)
        await media_job_queue.enqueue(
            job_id, kind, target["id"], session_id=session_id, group_id=group_id,
            title=title,
        )
        queued.append(job_id)
    if not queued:
        raise HTTPException(
            status_code=409,
            detail="この Session の録画はすべて既にqueueにあります（jobで確認できます）。",
        )
    return {"job_id": group_id, "group_id": group_id, "session_id": session_id,
            "total": len(queued), "skipped_recording_ids": skipped,
            "recording_ids": [t["id"] for t in targets]}


@app.post("/api/sessions/{session_id}/output")
async def output_session(session_id: int) -> dict:
    """Session内の全録画を焼き込み出力する。実処理はserver側のbackground jobで、応答は
    job_idを即時返す(進捗はWSのjob_update、reload後は /api/jobs で復元できる)。"""
    return await _start_session_output(session_id, upscale=False)


@app.post("/api/sessions/{session_id}/upscale-output")
async def upscale_output_session(session_id: int) -> dict:
    """Session内の全録画をUp出力(AI高画質化)する。焼き込みが有効なら録画ごとに焼き込み→
    高画質化の順で走る。実処理はserver側のbackground job。"""
    return await _start_session_output(session_id, upscale=True)


@app.get("/api/jobs")
async def list_jobs() -> dict:
    """待機中/実行中/過去のjobと、GPU排他の現況。画面のreload後もこれで進捗へ復帰する。

    文字起こしはmedia_job_queueではなくtranscribe_queueで動くため、この台帳には行が出ない。
    一方でGPUの枠は同じgpu_slotを奪い合うので、gpu.activeにはsttが出る。台帳0行のまま
    「実行中 stt」とだけ出すと『GPUは動いているのにjobは無い』と読めてしまうので、
    台帳外queueの実状をそのまま併記する(台帳に偽の行を足すことはしない)。"""
    return {
        "jobs": _job_snapshot(),
        "gpu": gpu_status(),
        "stt": {"counts": await asyncio.to_thread(storage.count_transcribe_queue_by_state)},
    }


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict:
    """jobを取り消す。待機中はqueueから外すだけ、実行中はffmpegをkillして部分fileを片付ける
    (frame単位でしか止まらないため、応答は『取り消し中』で実際の終了は少し後になる)。
    session一括のgroup idを渡すと、そのgroupの未終了jobをまとめて取り消す。"""
    group = storage.media_jobs_in_group(job_id)
    if group:
        outcomes = [await media_job_queue.cancel(row["job_id"]) for row in group]
        cancelled = sum(1 for o in outcomes if o in ("cancelled", "cancelling"))
        if cancelled == 0:
            raise HTTPException(status_code=409, detail="取り消せるjobがありません（既に終了しています）。")
        return {"job_id": job_id, "cancelled": cancelled, "total": len(group)}
    outcome = await media_job_queue.cancel(job_id)
    if outcome == "missing":
        raise HTTPException(status_code=404, detail="jobが見つかりません。")
    if outcome == "finished":
        raise HTTPException(status_code=409, detail="このjobは既に終了しています。")
    if outcome == "unsupported":
        raise HTTPException(
            status_code=409,
            detail="実行中の再mp4化は取り消せません（中断すると元mp4が退避されたままになります）。完了までお待ちください。",
        )
    return {"job_id": job_id, "state": outcome}


@app.post("/api/jobs/{job_id}/retry")
async def retry_job(job_id: str) -> dict:
    """終了したjobと同じ内容を新しいjobとして投入し直す。元の行は履歴として残す。"""
    job = storage.get_media_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="jobが見つかりません。")
    if job["state"] in ("pending", "running"):
        raise HTTPException(status_code=409, detail="このjobはまだ実行中です。")
    recording = storage.get_recording(job["recording_id"])
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません（削除済み）。")
    if job["kind"] in ("overlay", "upscale"):
        # 空き容量と録画fileの有無は投入時に確認する(再実行でも新規と同じ関門を通す)。
        _recording_for_output(job["recording_id"])
    return await _enqueue_media_job(
        job["kind"], job["recording_id"], group_id=job.get("group_id") or "",
        recording=recording,
        stem=Path(recording.get("filename") or "").stem or f"#{job['recording_id']}",
        params=job.get("params") or None,
    )


@app.get("/api/recordings/{recording_id}/play")
async def play_recording(recording_id: int) -> FileResponse:
    """Stream a finished recording for in-browser playback (highlight deep-link).
    FileResponse honours the Range header, so the <video> element can seek to the
    highlight offset without downloading the whole file."""
    recording = storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    path = _resolved_recording_path(recording)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="録画fileが存在しません。")
    media_type = {".ts": "video/mp2t", ".webm": "video/webm", ".mkv": "video/x-matroska"}.get(
        path.suffix, "video/mp4"
    )
    if recording["status"] == "recording":
        headers = {"Cache-Control": "no-cache"}
    else:
        headers = {"Cache-Control": f"private, max-age={RECORDING_CACHE_MAX_AGE_SECONDS}"}
    return FileResponse(path, media_type=media_type, headers=headers)


@app.get("/api/stt/status")
async def stt_status_api() -> dict:
    return stt_status()


@app.get("/api/recordings/{recording_id}/transcript")
async def get_transcript_api(recording_id: int) -> dict:
    if storage.get_recording(recording_id) is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    transcript = storage.get_transcript(recording_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="この録画の文字起こしはまだありません。")
    return transcript


def _transcript_basename(recording: dict) -> str:
    """字幕fileのbase名。録画file名と揃えるとNLEで動画と自動で紐づく。

    中断録画のpathはmp4ではなくrecord dir自体を指すことがあるため、stemはfilename優先で
    取り、それも無ければrecording idで代用する(pathからstemを引くと'recordings'になる)。"""
    name = (recording.get("filename") or "").strip()
    if name:
        return Path(name).stem
    return f"recording_{recording['id']}"


@app.get("/api/recordings/{recording_id}/transcript/export")
async def export_transcript_api(recording_id: int, format: str = "srt") -> Response:
    """転写を字幕file(SRT/VTT)または素のtextで書き出す。

    timecodeは元録画mp4のmedia軸(PTS)基準。焼き込み出力・Up出力は再encodeを挟むので、
    それらに対するPTS一致は保証しない。時刻mapが現行版でないtranscriptも書き出しは通すが、
    ズレている可能性を応答headerで明示する(外部で直せるsidecarなので拒否はしない)。"""
    if format not in subtitles.EXPORT_FORMATS:
        raise HTTPException(
            status_code=400,
            detail="formatはsrt・vtt・txtのいずれかを指定してください。",
        )
    recording = storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    transcript = storage.get_transcript(recording_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="この録画の文字起こしはまだありません。")
    # timecodeは元録画mp4のmedia軸なので、打ち切りもその実尺で測る(transcriptのdurationは
    # gapless長からの換算値で、実尺そのものではない)。ffprobeが無ければNone=打ち切らない。
    media_duration = await _duration_seconds(_safe_recording_path(recording["path"]))
    body = subtitles.render(format, transcript, media_duration)
    if not body.strip():
        raise HTTPException(status_code=404, detail="書き出せるsegmentがありません。")
    suffix, media_type, encoding = subtitles.EXPORT_FORMATS[format]
    filename = _transcript_basename(recording) + suffix
    # 配信者IDに非ASCIIが混じるとheaderへ素で載せられないので、RFC 5987のfilename*を併記する。
    filename_star = quote(filename, safe="")
    stale = not subtitles.timemap_current(transcript.get("timemap_version"))
    logger.info(
        "transcript exported: recording_id=%d format=%s segments=%d",
        recording_id, format, len(transcript.get("segments") or []),
        extra={"event": "subtitle.exported",
               "ctx": {"recording_id": recording_id, "format": format,
                       "timemap_version": transcript.get("timemap_version"),
                       "timemap_stale": stale,
                       "segments": len(transcript.get("segments") or [])}},
    )
    return Response(
        content=body.encode(encoding),
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename_star}",
            "X-Tictok-Timemap-Stale": "1" if stale else "0",
        },
    )


@app.get("/api/recordings/{recording_id}/comments")
async def get_recording_comments_api(recording_id: int) -> dict:
    """録画窓のcommentを動画時間軸で返す(player下段のcomment panel用)。

    search_hits(source=comment)をそのまま使う。video_timeはindex時にmp4 PTSへ変換済みで
    焼き込み・検索hitと同じ軸なので、ここで時刻変換を挟まずに再生位置と突き合わせられる。
    index未構築の録画は起動時のbackfillが埋めるため、ここでは空で返る。"""
    if storage.get_recording(recording_id) is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    rows = await asyncio.to_thread(
        storage.search_hits_for, recording_id, indexer.SOURCE_COMMENT)
    return {
        "recording_id": recording_id,
        "items": [
            {"id": row["id"], "t": row["video_time"],
             "nickname": row["nickname"], "body": row["body"]}
            for row in rows
        ],
    }


@app.post("/api/recordings/{recording_id}/transcribe")
async def transcribe_recording(recording_id: int) -> dict:
    """Run local STT over a finished recording and cache the transcript. Progress is
    broadcast over the websocket as transcribe_progress while segments decode."""
    recording = storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    path = _safe_recording_path(recording["path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="録画fileが存在しません。")
    loop = asyncio.get_running_loop()
    async with _tracked_job("stt", f"文字起こし {path.stem}", recording_id=recording_id,
                            session_id=recording.get("session_id")) as job_id:
        async def _report(pct: int) -> None:
            await hub.broadcast(
                {"type": "transcribe_progress", "recording_id": recording_id, "pct": pct}
            )
            await jobs.progress(job_id, pct, stage="文字起こし")

        def on_progress(done: float, total: float) -> None:
            pct = min(100, int(done / total * 100)) if total > 0 else 0
            asyncio.run_coroutine_threadsafe(_report(pct), loop)

        try:
            async with _job_ops("stt", recording_id, stem=path.stem,
                                job_registry_id=job_id):
                result = await asyncio.to_thread(stt_transcribe, str(path), on_progress)
        except STTError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        storage.save_transcript(recording_id, result)
        # 保存と同時に検索indexへ反映する。ここを省くと単発転写した録画だけが検索に出ない。
        await asyncio.to_thread(indexer.index_transcript, storage, recording)
        await _report(100)
    return {
        "recording_id": recording_id,
        "language": result["language"],
        "model": result["model"],
        "duration": result["duration"],
        "text": result["text"],
        "segments": result["segments"],
        "segments_count": len(result["segments"]),
    }


class ClipRequest(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    label: Optional[str] = None
    precise: bool = False
    variant: str = "source"
    # 未指定は設定の既定(clip_normalize_audio)に従う。
    normalize_audio: Optional[bool] = None


class ClipRangeRequest(BaseModel):
    recording_id: int
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    label: Optional[str] = None


class ClipBatchRequest(BaseModel):
    items: list[ClipRangeRequest]
    variant: str = "source"
    normalize_audio: Optional[bool] = None
    precise: bool = False


class EnqueueRequest(BaseModel):
    unique_id: Optional[str] = None
    recording_ids: Optional[list[int]] = None
    priority: int = 0


class CancelRequest(BaseModel):
    recording_ids: Optional[list[int]] = None


def _resolved_recording_path(recording: dict) -> Path:
    """録画の現在のmp4 path。完了録画はfinal dirへ移動するので、DBのpathが実体を指さない
    ことがある。両rootを探して実在する方を返す(見つからなければDBのpathをそのまま返す)。"""
    path = _safe_recording_path(recording["path"])
    if path.is_file():
        return path
    found = _existing_recording_mp4(Path(recording["filename"]).stem)
    return found if found is not None else path


CLIP_VARIANTS = ("source", "overlay", "upscaled")
CLIP_VARIANT_LABELS = {"source": "元録画", "overlay": "焼き込み出力", "upscaled": "Up出力"}


def _variant_paths(path: Path) -> dict:
    """録画1本ぶんの素材版 → path。存在するものだけを返す(存在しない版は作らない)。"""
    found = {"source": path} if path.is_file() else {}
    overlay_mp4 = overlay_paths(path)[0]
    if overlay_mp4.is_file():
        found["overlay"] = overlay_mp4
    upscaled = upscale_output_path(upscale_input_path(path))
    if upscaled.is_file():
        found["upscaled"] = upscaled
    return found


def _clip_source(recording: dict, variant: str) -> Path:
    """切り出しの入力。無い版を黙ってsourceへ落とすと、利用者は焼き込み済みを頼んだのに
    素のclipを受け取ることになるので、無ければ拒否する。"""
    if variant not in CLIP_VARIANTS:
        raise HTTPException(status_code=400, detail=f"未知の素材版です: {variant}")
    found = _variant_paths(_resolved_recording_path(recording))
    if variant not in found:
        raise HTTPException(
            status_code=404,
            detail=f"この録画の{CLIP_VARIANT_LABELS[variant]}がありません。先に出力してください。",
        )
    return found[variant]


def _clip_normalize(requested: Optional[bool]) -> Optional[dict]:
    """切り出しの音量正規化の目標値。Noneなら設定の既定に従う。"""
    enabled = (bool(int(settings.get("clip_normalize_audio")))
               if requested is None else bool(requested))
    return audio_norm.targets(settings) if enabled else None


def _output_normalize() -> Optional[dict]:
    """焼き込み出力・Up出力の音量正規化の目標値(無効ならNone)。"""
    if not int(settings.get("video_output_normalize_audio")):
        return None
    return audio_norm.targets(settings)


@app.get("/api/recordings/{recording_id}/path")
async def recording_path_api(recording_id: int) -> dict:
    """編集ソフトへ渡すための実file path。録画本体に加え、焼き込み・高画質化の出力が
    あればそれらのpathも返す(素材としてどれを使うかは利用者が選ぶ)。"""
    recording = storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    path = _resolved_recording_path(recording)
    found = _variant_paths(path)
    variants = [{"kind": "source", "path": str(path), "exists": path.is_file()}]
    variants += [{"kind": kind, "path": str(found[kind]), "exists": True}
                 for kind in CLIP_VARIANTS if kind != "source" and kind in found]
    return {"recording_id": recording_id, "path": str(path),
            "exists": path.is_file(), "variants": variants}


@app.get("/api/recordings/{recording_id}/heat")
async def recording_heat_api(recording_id: int) -> dict:
    """録画窓のcomment/gift密度を動画時間軸へ載せて返す(seek bar下のheat bar用)。

    bucketの時刻はwall-clockなので、commentのindexと同じmapperで動画時間へ変換する。
    ここで生の差分を使うと焼き込み動画とheatの位置がずれる。"""
    recording = storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    session_id = recording.get("session_id")
    if session_id is None:
        return {"recording_id": recording_id, "points": []}
    path = _resolved_recording_path(recording)
    started_at = recording["started_at"]
    ended_at = recording.get("ended_at")
    to_pts = await asyncio.to_thread(
        indexer.build_time_mapper_sync, path, started_at, ended_at)
    buckets = storage.session_buckets(session_id, started_at, ended_at)
    points = [
        {
            "t": round(to_pts(bucket["start"]), 2),
            "comments": bucket["comments"],
            "gifts": bucket["gifts"],
            "diamonds": bucket["diamonds"],
            "likes": bucket["likes"],
            "viewers": bucket["viewers"],
        }
        for bucket in buckets
    ]
    return {"recording_id": recording_id, "points": points}


# 候補badgeの文言。指標を足したらここも足すこと(素通りするとKeyErrorで気付ける)。
_CANDIDATE_LABELS = {
    "diamonds": lambda item: f"ダイヤ{item['diamonds']}",
    "comments": lambda item: f"コメント{item['comments']}",
    "audio_peak": lambda item: "音量",
}
# 窓が重なった候補を畳むときに、代表となった窓から引き継ぐkey。
_CANDIDATE_REPRESENTATIVE_KEYS = ("zscore", "metric", "diamonds", "comments", "ratio",
                                  "silent_ratio")


def _merge_candidates(items: list) -> list:
    """時刻順に並んだ候補のうち、範囲が重なるものを1つへ畳む。移動窓は1 bucketずつずれた
    窓を連続で拾うため、畳まないと同じ盛り上がりが何本ものclipになる。"""
    merged: list = []
    for item in sorted(items, key=lambda c: c["start"]):
        if merged and item["start"] <= merged[-1]["end"]:
            prev = merged[-1]
            prev["end"] = max(prev["end"], item["end"])
            if item["zscore"] > prev["zscore"]:
                # 代表値は最も外れている窓のものを残す(合算すると窓の重なりを二重に数える)。
                prev.update({k: item[k] for k in _CANDIDATE_REPRESENTATIVE_KEYS
                             if k in item})
            continue
        merged.append(dict(item))
    return merged


@app.get("/api/recordings/{recording_id}/clip-candidates")
async def recording_clip_candidates_api(recording_id: int) -> dict:
    """録画窓の盛り上がりから切り出し候補を出す。時刻は動画時間軸(秒)。

    判定は配信者pageのハイライト(storage.streamer_highlights)と同じ core.spike で、窓だけを
    設定の秒数へ広げる。窓に入るbucket数はsessionのbucket幅から導くので、bucket幅の違う
    session間でも窓の実長は揃う。"""
    recording = storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    window_seconds = int(settings.get("clip_candidate_window_seconds"))
    pad_before = int(settings.get("clip_pad_before_seconds"))
    pad_after = int(settings.get("clip_pad_after_seconds"))
    lead = int(settings.get("clip_candidate_lead_seconds"))
    empty = {"recording_id": recording_id, "window_seconds": window_seconds,
             "pad_before_seconds": pad_before, "pad_after_seconds": pad_after,
             "lead_seconds": lead, "candidates": []}
    session_id = recording.get("session_id")
    if session_id is None:
        return empty
    session = storage.get_session(session_id)
    if session is None:
        return empty
    bucket_seconds = session.get("bucket_seconds")
    if not bucket_seconds:
        # bucket幅が無いsessionは窓のbucket数を出せない。推測で埋めると窓の実長が嘘になる。
        return empty
    started_at = recording["started_at"]
    ended_at = recording.get("ended_at")
    buckets = storage.session_buckets(session_id, started_at, ended_at)
    window_buckets = spike.window_bucket_count(bucket_seconds, window_seconds)
    path = _resolved_recording_path(recording)
    to_pts = await asyncio.to_thread(
        indexer.build_time_mapper_sync, path, started_at, ended_at)
    metrics = spike.METRICS
    profile = None
    if int(settings.get("clip_candidate_audio")):
        try:
            profile = await ensure_audio_profile(path)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        # 音声は動画時間軸なので、各bucketの窓を動画時間へ写してからpeakを引く。
        # 録画の外へ落ちるbucketがあるとlevelの取れない窓ができるため、その録画では
        # 音声を判定から外す(0で埋めると「無音だった」という観測を作ってしまう)。
        outside = next((b for b in buckets
                        if level_peak(profile, to_pts(b["start"]),
                                      to_pts(b["start"] + bucket_seconds)) is None), None)
        if outside is None:
            for bucket in buckets:
                bucket["audio_peak"] = level_peak(
                    profile, to_pts(bucket["start"]),
                    to_pts(bucket["start"] + bucket_seconds))
            metrics = metrics + ("audio_peak",)
        else:
            logger.info(
                "clip candidates: audio metric skipped for recording %s"
                " (bucket outside the recorded audio)", recording_id,
                extra={"event": "clip.audio_metric_skipped",
                       "ctx": {"recording_id": recording_id,
                               "bucket_start": outside["start"],
                               "audio_duration_seconds": profile["duration_seconds"]}},
            )
    found = spike.detect_spikes(
        buckets, window_buckets=window_buckets, metrics=metrics,
        zscore_min=float(settings.get("clip_candidate_zscore")))
    if not found:
        return empty
    video_seconds = await _duration_seconds(path)
    span = bucket_seconds * window_buckets
    items = []
    for candidate in found:
        start = to_pts(candidate["start"]) - lead - pad_before
        end = to_pts(candidate["start"] + span) + pad_after
        start = max(0.0, start)
        if video_seconds is not None:
            end = min(end, video_seconds)
        if end <= start:
            continue
        item = {
            "start": round(start, 2),
            "end": round(end, 2),
            "zscore": round(candidate["zscore"], 2),
            "metric": candidate["metric"],
            "ratio": round(candidate["ratio"], 2),
            "diamonds": int(candidate["values"]["diamonds"]),
            "comments": int(candidate["values"]["comments"]),
        }
        items.append(item)
    merged = _merge_candidates(items)
    merged.sort(key=lambda c: c["zscore"], reverse=True)
    limit = int(settings.get("clip_candidate_limit"))
    for item in merged:
        item["label"] = _CANDIDATE_LABELS[item["metric"]](item)
        if profile is not None:
            # 無音割合は畳んだ後の区間で測る。代表窓の値を引き継ぐと、窓が伸びた分の
            # 無音が数に入らず実態とずれる。判定できなければNoneのまま。
            item["silent_ratio"] = silent_ratio(profile, item["start"], item["end"])
    return {**empty, "candidates": merged[:limit]}


@app.get("/api/recordings/{recording_id}/waveform")
async def recording_waveform_api(recording_id: int, buckets: int = 2000) -> dict:
    """seek bar用の音声波形。無音・BGM・発話の区別が付くので切り所の判断に使う。

    初回はcontainerを丸ごと読むため長尺(3.9時間)で90秒級かかる。画面側は利用者が明示的に
    要求したときだけ呼ぶこと(録画を開く度に走らせるとdiskを占有する)。"""
    recording = storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    path = _resolved_recording_path(recording)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="録画fileが存在しません。")
    try:
        result = await ensure_waveform(path, max(200, min(buckets, 8000)))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    result["recording_id"] = recording_id
    return result


@app.get("/api/recordings/{recording_id}/thumbnails")
async def recording_thumbnails_api(recording_id: int) -> dict:
    """seek bar hover用のsprite sheetを用意して仕様を返す。

    3時間級の録画では初回生成に十数秒かかる(keyframeのみのdecodeでも尺なりの読み込みが
    要る)ため、hoverの瞬間ではなく録画を開いた時点で呼ぶこと。2回目以降はcache hitで即返る。"""
    recording = storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    path = _resolved_recording_path(recording)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="録画fileが存在しません。")
    try:
        spec = await ensure_sprite(path)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    spec["recording_id"] = recording_id
    spec["url"] = f"/api/recordings/{recording_id}/thumbnails.jpg"
    spec.pop("path", None)
    return spec


@app.get("/api/recordings/{recording_id}/thumbnails.jpg")
async def recording_thumbnails_image(recording_id: int) -> FileResponse:
    recording = storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    sprite = sprite_path(_resolved_recording_path(recording))
    if not sprite.is_file():
        raise HTTPException(status_code=404, detail="sprite未生成です。")
    return FileResponse(
        sprite, media_type="image/jpeg",
        headers={"Cache-Control": f"private, max-age={RECORDING_CACHE_MAX_AGE_SECONDS}"},
    )


@app.post("/api/recordings/{recording_id}/clip")
async def clip_recording(recording_id: int, payload: ClipRequest) -> dict:
    recording = storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    src = _clip_source(recording, payload.variant)
    normalize = _clip_normalize(payload.normalize_audio)
    try:
        async with _job_ops("clip", recording_id, stem=src.stem, variant=payload.variant,
                            **audio_norm.describe(normalize)):
            result = await make_clip(
                src, payload.start, payload.end, payload.label, payload.precise,
                normalize=normalize)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    result["recording_id"] = recording_id
    result["variant"] = payload.variant
    return result


@app.post("/api/clips/batch")
async def clip_batch_api(payload: ClipBatchRequest) -> dict:
    """複数の範囲をまとめて切り出す。録画ごとに1 jobへ束ねてqueueへ載せ、job_idを返す。

    切り出し1本は秒で終わるが、精密(再encode)を選ぶと1本が分単位になる。browserのloopで
    回すとtabを閉じた時点で残りが起動すらしないため、実行はserver側のqueueへ寄せている。"""
    if not payload.items:
        raise HTTPException(status_code=400, detail="切り出す範囲がありません。")
    if payload.variant not in CLIP_VARIANTS:
        raise HTTPException(status_code=400, detail=f"未知の素材版です: {payload.variant}")
    _require_disk_space(_disk_volume_paths(), "clip_batch", items=len(payload.items))
    by_recording: dict = {}
    for item in payload.items:
        if item.end <= item.start:
            raise HTTPException(status_code=400, detail="終了位置は開始位置より後にしてください。")
        by_recording.setdefault(item.recording_id, []).append(item)
    group_id = secrets.token_hex(4) if len(by_recording) > 1 else ""
    jobs_started = []
    for recording_id, items in by_recording.items():
        recording = storage.get_recording(recording_id)
        if recording is None:
            raise HTTPException(status_code=404, detail="録画が見つかりません。")
        # 素材が無い版を指定していれば、queueへ載せる前にここで弾く。
        src = _clip_source(recording, payload.variant)
        params = {
            "variant": payload.variant,
            "normalize_audio": payload.normalize_audio,
            "precise": payload.precise,
            "ranges": [{"start": i.start, "end": i.end, "label": i.label} for i in items],
        }
        jobs_started.append(await _enqueue_media_job(
            "clip_batch", recording_id, group_id=group_id, recording=recording,
            stem=f"{src.stem} ({len(items)}件)", params=params))
    return {"jobs": jobs_started, "group_id": group_id,
            "total": sum(len(v) for v in by_recording.values())}


@app.get("/api/search")
async def search_api(q: str, sources: str = "stt,comment", unique_ids: str = "",
                     since: Optional[float] = None, until: Optional[float] = None,
                     order: str = "time", limit: int = 200, offset: int = 0) -> dict:
    """転写とcommentを横断して検索する。1件=1シーンで、video_timeへそのままseekできる。"""
    wanted = [s for s in sources.split(",") if s in (indexer.SOURCE_STT, indexer.SOURCE_COMMENT)]
    ids = [u for u in unique_ids.split(",") if u]
    result = await asyncio.to_thread(
        storage.search_scenes, q, wanted, ids, since, until, order,
        max(1, min(limit, 500)), max(0, offset))
    return result


class CutRequest(BaseModel):
    recording_id: int
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    label: str = ""


@app.get("/api/cutlist")
async def list_cutlist_api() -> dict:
    """cut listを返す。pathは移動後の実体を指すよう解決し直す。"""
    cuts = storage.list_cuts()
    for cut in cuts:
        if not cut.get("path"):
            continue
        recording = storage.get_recording(cut["recording_id"])
        if recording is not None:
            cut["path"] = str(_resolved_recording_path(recording))
    return {"items": cuts}


@app.post("/api/cutlist")
async def add_cut_api(payload: CutRequest) -> dict:
    recording = storage.get_recording(payload.recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    if payload.end <= payload.start:
        raise HTTPException(status_code=400, detail="終了位置は開始位置より後にしてください。")
    return storage.add_cut(payload.recording_id, recording["unique_id"],
                           payload.start, payload.end, payload.label)


@app.delete("/api/cutlist/{cut_id}")
async def delete_cut_api(cut_id: int) -> dict:
    if not storage.delete_cut(cut_id):
        raise HTTPException(status_code=404, detail="対象が見つかりません。")
    return {"deleted": cut_id}


@app.delete("/api/cutlist")
async def clear_cutlist_api() -> dict:
    return {"deleted": storage.clear_cuts()}


@app.get("/api/cutlist/export")
async def export_cutlist_api(format: str = "csv", unique_ids: str = "") -> Response:
    """cut listをCSV/EDL/FCPXMLで書き出す。mp4を出さずに範囲だけ渡せば再encodeが要らない。

    EDL/FCPXMLはframeが最小単位なので、素材のfpsをffprobeで実測してから組み立てる
    (既定値で埋めるとNLE上の位置が素材ごとにずれる)。実測できない素材が混ざる場合は
    frame基準の形式を出さずにerrorへ倒す。

    実測では配信者ごとにfpsが違う(25/60fpsの実例)。EDLはlist全体で1 frame rateしか
    持てないため、配信者を跨いで出すとほぼ確実に混在で止まる。unique_idsで配信者を
    絞って出すか、素材ごとにframe rateを持てるFCPXMLを使うこと。"""
    if format not in ("csv", "edl", "fcpxml"):
        raise HTTPException(status_code=400,
                            detail="formatはcsv/edl/fcpxmlのいずれかを指定してください。")
    wanted = {u for u in unique_ids.split(",") if u}
    cuts = (await list_cutlist_api())["items"]
    if wanted:
        cuts = [c for c in cuts if c["unique_id"] in wanted]
    cuts = await cutlist_export.resolve_timebases(cuts)
    try:
        if format == "csv":
            body = cutlist_export.to_csv(cuts)
            media_type, filename = "text/csv; charset=utf-8", "tictok_cutlist.csv"
        elif format == "edl":
            body = cutlist_export.to_edl(cuts)
            media_type, filename = "text/plain; charset=utf-8", "tictok_cutlist.edl"
        else:
            body = cutlist_export.to_fcpxml(cuts)
            media_type, filename = "application/xml; charset=utf-8", "tictok_cutlist.fcpxml"
    except cutlist_export.CutlistExportError as exc:
        logger.warning(
            "cutlist export refused (%s): %s", format, exc, exc_info=True,
            extra={"event": "cutlist.export_refused",
                   "ctx": {"format": format, "cuts": len(cuts)}},
        )
        raise HTTPException(status_code=400, detail=str(exc))
    return Response(
        content=body.encode("utf-8-sig" if format == "csv" else "utf-8"),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class BookmarkRequest(BaseModel):
    recording_id: int
    start: float = Field(ge=0)
    end: Optional[float] = None
    memo: str = ""
    source_hit_id: Optional[int] = None


class BookmarkMemoRequest(BaseModel):
    memo: str


@app.get("/api/bookmarks")
async def list_bookmarks_api(recording_id: Optional[int] = None) -> dict:
    """見どころ一覧。recording_id指定で1録画分(seek barのmarker用)、無指定で全録画分。"""
    return {"items": storage.list_bookmarks(recording_id)}


@app.post("/api/bookmarks")
async def add_bookmark_api(payload: BookmarkRequest) -> dict:
    """見どころを1件記録する。endを省くと点(コメント1件や現在位置)として残る。"""
    recording = storage.get_recording(payload.recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    if payload.end is not None and payload.end <= payload.start:
        raise HTTPException(status_code=400, detail="終了位置は開始位置より後にしてください。")
    return storage.add_bookmark(payload.recording_id, recording["unique_id"],
                                payload.start, payload.end, payload.memo,
                                payload.source_hit_id)


@app.patch("/api/bookmarks/{bookmark_id}")
async def update_bookmark_api(bookmark_id: int, payload: BookmarkMemoRequest) -> dict:
    updated = storage.update_bookmark_memo(bookmark_id, payload.memo)
    if updated is None:
        raise HTTPException(status_code=404, detail="対象が見つかりません。")
    return updated


@app.delete("/api/bookmarks/{bookmark_id}")
async def delete_bookmark_api(bookmark_id: int) -> dict:
    if not storage.delete_bookmark(bookmark_id):
        raise HTTPException(status_code=404, detail="対象が見つかりません。")
    return {"deleted": bookmark_id}


def _semantic_min_score() -> float:
    """意味検索の類似度の下限。これ未満は「該当なし」として捨てる。

    scoreの尺度は埋め込みmodel依存(embeddinggemma:300mでの実測に基づく既定値)なので、
    modelを替えたら測り直して設定すること。
    TODO: 他のTICTOK_SEMANTIC_*と併せてcore/config.pyへ移す。"""
    return float(os.environ.get("TICTOK_SEMANTIC_MIN_SCORE", "0.30"))


@app.get("/api/search/semantic")
async def semantic_search_api(q: str, sources: str = "stt,comment", unique_ids: str = "",
                              since: Optional[float] = None, until: Optional[float] = None,
                              limit: int = 50) -> dict:
    """意味検索。語の一致ではなく意味の近さで探すので、言い回しを覚えていなくても引ける。

    結果はkeyword検索と同じ行形式へ揃えて返す(画面が両者を同じ表で描けるようにする)。
    passageは複数のsearch_hits行を束ねたものなので、代表行の位置へseekする。
    sources/since/untilの意味は /api/search と同じで、絞り込むほど走査行が減って速くなる。"""
    wanted = [s for s in sources.split(",") if s in (indexer.SOURCE_STT, indexer.SOURCE_COMMENT)]
    ids = [u for u in unique_ids.split(",") if u]
    if not wanted:
        # 0件は0件として返す。ここで全件を検索すると、種類を全部外したのに結果が出る。
        return {"total": 0, "mode": "semantic", "items": [],
                "hint": "検索する種類（発話／コメント）を選んでください。"}
    try:
        matches = await semantic.search(q, max(1, min(limit, 200)), ids or None,
                                        wanted, since, until)
    except semantic.SemanticError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    # 意味検索は常に上位k件を返すので、そもそも該当が無い話題でも「それらしいゴミ」が並ぶ。
    # 実測ではdata内に在る話題のtop1が0.40〜0.49、無い話題が0.12〜0.27と分離するため、
    # 下限を設けて後者を落とす。閾値はscoreの尺度がmodel依存なので設定で変えられる。
    floor = _semantic_min_score()
    kept = [m for m in matches if m["score"] >= floor]
    if not kept:
        best = max((m["score"] for m in matches), default=0.0)
        return {"total": 0, "mode": "semantic", "items": [],
                "hint": f"意味の近いシーンが見つかりませんでした（最も近いもので類似度{best:.2f}"
                        f"／下限{floor:.2f}）。別の言い方を試すか、語で一致に切り替えてください。"}
    matches = kept
    # semantic.searchはpassage全文(既定25秒ぶん)をbodyに持つ。先頭行のsearch_hitsを
    # 引き直して表示すると、当たった本文ではなく「でその」のような断片が並び、
    # 精度が実際より遥かに悪く見える。返ってきたpassageをそのまま見せる。
    items = []
    for match in matches:
        items.append({
            "id": match["id"],
            "source": match["source"],
            "recording_id": match["recording_id"],
            "session_id": match["session_id"],
            "unique_id": match["unique_id"],
            "started_at": match["started_at"],
            "video_time": match["video_time"],
            "end_time": match["end_time"],
            "nickname": None,
            "body": match["body"],
            "snippet": match["body"],
            "score": round(match["score"], 4),
        })
    return {"total": len(items), "mode": "semantic", "hint": "", "items": items}


@app.get("/api/search/semantic/status")
async def semantic_status_api() -> dict:
    return await asyncio.to_thread(semantic.index_status)


async def _broadcast_semantic_status() -> None:
    """意味検索indexの現況を配る。開始時はcreate_taskで投げっぱなしにするので、
    ここで例外を出すと「Task exception was never retrieved」だけが残る。通知の失敗で
    buildを巻き添えにする理由も無いので、logへ落として飲む。"""
    try:
        status = await asyncio.to_thread(semantic.index_status)
        await hub.broadcast({"type": "semantic_index", "status": status})
    except Exception:
        logger.exception(
            "failed to broadcast the semantic index status",
            extra={"event": "search.semantic_status_broadcast_failed", "ctx": {}},
        )


@app.post("/api/search/semantic/build")
async def semantic_build_api() -> dict:
    """意味検索indexを構築する(差分)。keyword indexが増えた後に呼ぶ。"""
    loop = asyncio.get_running_loop()

    def on_progress(info: dict) -> None:
        # 開始をここで知らせる。lockを実際に握った後なので、配る status の building は真。
        # これが無いと、別tabやこのbuildを始めていない画面はbuttonを塞げない。
        if info.get("stage") == "start":
            loop.create_task(_broadcast_semantic_status())

    try:
        async with _job_ops("semantic", None):
            result = await semantic.build_index(storage, on_progress=on_progress)
    except semantic.SemanticBusy as exc:
        # 待たせずに「実行中」と返す。SemanticErrorより先に捕まえること(subclassのため)。
        raise HTTPException(status_code=409, detail=str(exc))
    except semantic.SemanticError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    finally:
        # 失敗して抜けた場合もbuildingを下ろす。ここを通さないと画面が塞がったまま残る。
        await _broadcast_semantic_status()
    return result


@app.get("/api/search/status")
async def search_status_api() -> dict:
    """検索対象がどこまで揃っているか。転写は配信者単位で進むため、配信者ごとに集計する。"""
    counts = storage.search_indexed_counts()
    transcribed = storage.transcribed_recording_ids()
    per_streamer: dict = {}
    for recording in storage.list_recordings(100000):
        if recording["status"] != "completed":
            continue
        entry = per_streamer.setdefault(
            recording["unique_id"],
            {"unique_id": recording["unique_id"], "recordings": 0, "transcribed": 0,
             "comment_indexed": 0, "seconds": 0.0},
        )
        entry["recordings"] += 1
        if recording["id"] in transcribed:
            entry["transcribed"] += 1
        if indexer.SOURCE_COMMENT in counts.get(recording["id"], {}):
            entry["comment_indexed"] += 1
        if recording.get("ended_at"):
            entry["seconds"] += recording["ended_at"] - recording["started_at"]
    streamers = sorted(per_streamer.values(),
                       key=lambda e: e["seconds"], reverse=True)
    return {"streamers": streamers, "queue": transcribe_queue.status()}


@app.post("/api/transcribe/queue")
async def enqueue_transcriptions_api(payload: EnqueueRequest) -> dict:
    """転写queueへ投入する。recording_ids指定なら1本単位、無ければ配信者単位
    (unique_id未指定なら全配信者)。"""
    if not stt_available():
        raise HTTPException(
            status_code=503,
            detail="STTが利用できません。faster-whisperのinstallとTICTOK_STT_ENABLEDを確認してください。")
    if payload.recording_ids:
        try:
            result = transcribe_queue.enqueue_recordings(
                payload.recording_ids, payload.priority)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    else:
        result = transcribe_queue.enqueue_streamer(payload.unique_id, payload.priority)
    result["queue"] = transcribe_queue.status()
    await hub.broadcast({"type": "transcribe_queue", "status": result["queue"]})
    return result


@app.get("/api/transcribe/queue")
async def transcribe_queue_api() -> dict:
    return transcribe_queue.status()


@app.delete("/api/transcribe/queue")
async def cancel_transcriptions_api(payload: CancelRequest) -> dict:
    cancelled = transcribe_queue.cancel(payload.recording_ids)
    status = transcribe_queue.status()
    await hub.broadcast({"type": "transcribe_queue", "status": status})
    return {"cancelled": cancelled, "queue": status}


@app.delete("/api/recordings/{recording_id}")
async def delete_recording(recording_id: int) -> dict:
    recording = storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    if recording["status"] == "recording":
        raise HTTPException(status_code=409, detail="録画中のfileは削除できません。先に停止してください。")
    path = _safe_recording_path(recording["path"])
    try:
        if path.is_file():
            path.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"file削除に失敗しました: {exc}")
    cleanup_overlay_files(path)
    cleanup_upscale_files(path)
    try:
        timing_path(path).unlink(missing_ok=True)
    except OSError:
        pass
    storage.delete_recording(recording_id)
    return {"deleted": recording_id}


@app.get("/api/ai/status")
async def ai_status_api() -> dict:
    return ai_status()


# AI分析の永続化。GETは保存済みの結果だけを返し、LLMは一切走らせない(画面を開くたびに
# 数十秒の推論が始まるのを構造的に防ぐ)。実行はPOSTのみで、operatorがbuttonを押したとき
# だけ走る。未計算の対象をまとめて計算する経路は作らない。
def _ai_payload(base: dict, record: Optional[dict], *, cached: bool) -> dict:
    """API応答の共通部分。分析日時・model・prompt版・cacheかどうかを必ず載せる
    (いつ・どのmodelで出した結果なのかが分からない表示にはしない)。"""
    payload = dict(base)
    payload["cached"] = cached
    if record is None:
        payload.update({"analysis": None, "computed_at": None, "model": None,
                        "prompt_version": None})
        return payload
    payload.update({
        "analysis": record.get("payload"),
        "computed_at": record.get("computed_at"),
        "model": record.get("model"),
        "prompt_version": record.get("prompt_version"),
    })
    if record.get("payload_unreadable"):
        # 読めない行を「未分析」に化けさせない。再分析すれば直ることを画面へ伝える。
        payload["error"] = "保存された分析結果を読み取れませんでした。再分析してください。"
    return payload


def _ai_cache_hit(record: Optional[dict], model: str, prompt_version: int,
                  signature: str) -> bool:
    return bool(
        record
        and not record.get("payload_unreadable")
        and record.get("model") == model
        and record.get("prompt_version") == prompt_version
        and record.get("input_signature") == signature
    )


def _ai_model_or_503() -> str:
    model = ai_status()["model"]
    if not get_ai_enabled():
        raise HTTPException(status_code=503,
                            detail="AI機能が無効です（TICTOK_AI_ENABLED=1 を設定してください）。")
    if not model:
        raise HTTPException(status_code=503,
                            detail="AI modelが未設定です（TICTOK_AI_MODEL を設定してください）。")
    return model


def _session_comment_entries(session_id: int) -> list:
    """sessionのcommentを(時刻, 本文)で返す。時刻が要るのは時間層化抽出のため。

    storage.session_commentsは新しい順にN件を切って本文だけを返すので、そこから採ると
    標本が配信終盤に偏る(=出力されるsentiment比率が配信全体の推定量にならない)。件数を
    絞るのは抽出側の仕事なので、ここでは全commentを時刻付きで渡す。"""
    return [
        (row["time"], row["comment"] or row["text"] or "")
        for row in storage.iter_events(session_id)
        if row["kind"] == "comment" and (row["comment"] or row["text"])
    ]


async def _session_comment_input(session_id: int) -> list:
    entries = await asyncio.to_thread(_session_comment_entries, session_id)
    sample = ai_analysis.comment_sample(entries)
    if not sample:
        raise HTTPException(status_code=404, detail="このSessionに分析できるCommentがありません。")
    return sample


def _comment_analysis_payload(session_id: int, record: Optional[dict],
                              *, cached: bool) -> dict:
    """comment分析の保存形式は {analysis, comment_count} の包み。何件を分析した結果なのかは
    分析日時と同じくらい読み手に必要で、payload以外に置き場が無いため一緒に保存している。"""
    stored = (record or {}).get("payload")
    wrapped = stored if isinstance(stored, dict) else {}
    view = dict(record) if record else None
    if view is not None:
        view["payload"] = wrapped.get("analysis")
    payload = _ai_payload({"session_id": session_id}, view, cached=cached)
    payload["comment_count"] = wrapped.get("comment_count")
    return payload


@app.get("/api/sessions/{session_id}/comment-analysis")
async def session_comment_analysis(session_id: int) -> dict:
    """保存済みの分析結果のみを返す。無ければanalysis=nullで、LLMは起動しない。"""
    _get_session_or_404(session_id)
    record = await asyncio.to_thread(
        storage.get_ai_analysis, ai_analysis.KIND_COMMENT,
        ai_analysis.TARGET_SESSION, str(session_id))
    return _comment_analysis_payload(session_id, record, cached=record is not None)


@app.post("/api/sessions/{session_id}/comment-analysis")
async def run_session_comment_analysis(session_id: int, refresh: int = 0) -> dict:
    """明示要求でのみ実行する。入力・model・prompt版が前回と同じなら保存済みを返し、
    refresh=1 のときだけ同一条件でも作り直す。"""
    _get_session_or_404(session_id)
    model = _ai_model_or_503()
    sample = await _session_comment_input(session_id)
    signature = ai_analysis.input_signature({"comments": sample})
    record = await asyncio.to_thread(
        storage.get_ai_analysis, ai_analysis.KIND_COMMENT,
        ai_analysis.TARGET_SESSION, str(session_id))
    if not refresh and _ai_cache_hit(record, model, ai_analysis.COMMENT_PROMPT_VERSION,
                                     signature):
        return _comment_analysis_payload(session_id, record, cached=True)
    try:
        analysis = await analyze_comments(sample)
    except AIError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    saved = await asyncio.to_thread(
        storage.save_ai_analysis, ai_analysis.KIND_COMMENT, ai_analysis.TARGET_SESSION,
        str(session_id), session_id=session_id, model=model,
        prompt_version=ai_analysis.COMMENT_PROMPT_VERSION, input_signature=signature,
        payload={"analysis": analysis, "comment_count": len(sample)})
    return _comment_analysis_payload(session_id, saved, cached=False)


def _streamer_review_input(profile: dict) -> dict:
    """配信者profileと全体解析からLLMへ渡す集約dictを組む。指紋もこの戻り値から取るので、
    実行経路と指紋計算で別のdictを作らないこと(作ると毎回cacheが外れる)。

    全体解析(信頼区間・標本数・被覆率つき)を併せて渡すのは、profileだけでは時間帯の話が
    「最も稼いだ15分枠top5」という粗い入力からしか語れないため。解析側の母集団は監視対象
    全体なので、review_digestが入れ物を分けて区別できる形にする。DB読みなので同期で組み、
    呼び出し側がto_threadへ逃がす。"""
    return review_digest.review_input(
        profile,
        time_index=storage.analytics_time_index(),
        retention=storage.analytics_retention(),
        entry_source=storage.analytics_entry_source(),
        battle_flow=storage.analytics_battle_flow(),
        coverage=storage.analytics_coverage(),
    )


@app.get("/api/streamers/{unique_id}/ai-review")
async def streamer_ai_review(unique_id: str) -> dict:
    """保存済みの講評のみを返す。無ければreview=nullで、LLMは起動しない。"""
    record = await asyncio.to_thread(
        storage.get_ai_analysis, ai_analysis.KIND_STREAMER_REVIEW,
        ai_analysis.TARGET_STREAMER, unique_id)
    payload = _ai_payload({"unique_id": unique_id}, record, cached=record is not None)
    payload["review"] = payload.pop("analysis")
    return payload


@app.post("/api/streamers/{unique_id}/ai-review")
async def run_streamer_ai_review(unique_id: str, refresh: int = 0) -> dict:
    """Natural-language growth review of a streamer from their aggregated profile.
    A compact summary (no raw events) is sent to the local model."""
    model = _ai_model_or_503()
    profile = await asyncio.to_thread(storage.streamer_profile, unique_id)
    if profile["count"] == 0:
        raise HTTPException(status_code=404, detail="この配信者の集計データがありません。")
    review_input = await asyncio.to_thread(_streamer_review_input, profile)
    signature = ai_analysis.input_signature(review_input)
    record = await asyncio.to_thread(
        storage.get_ai_analysis, ai_analysis.KIND_STREAMER_REVIEW,
        ai_analysis.TARGET_STREAMER, unique_id)
    base = {"unique_id": unique_id}
    if not refresh and _ai_cache_hit(record, model, ai_analysis.REVIEW_PROMPT_VERSION,
                                     signature):
        payload = _ai_payload(base, record, cached=True)
        payload["review"] = payload.pop("analysis")
        return payload
    try:
        review = await analyze_streamer(review_input)
    except AIError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    saved = await asyncio.to_thread(
        storage.save_ai_analysis, ai_analysis.KIND_STREAMER_REVIEW,
        ai_analysis.TARGET_STREAMER, unique_id, session_id=None, model=model,
        prompt_version=ai_analysis.REVIEW_PROMPT_VERSION, input_signature=signature,
        payload=review)
    payload = _ai_payload(base, saved, cached=False)
    payload["review"] = payload.pop("analysis")
    return payload


@app.get("/api/dashboard")
async def aggregate_dashboard() -> dict:
    return await asyncio.to_thread(storage.aggregate_dashboard)


@app.get("/api/streamers")
async def list_streamers() -> dict:
    streamers = await asyncio.to_thread(storage.streamer_index)
    return {"streamers": streamers}


@app.get("/api/streamers/{unique_id}/profile")
async def streamer_profile(unique_id: str) -> dict:
    profile = await asyncio.to_thread(storage.streamer_profile, unique_id)
    # A still-collecting session persists stats only at finalize, so overlay the
    # live collector's running stats so today's numbers are reflected in the totals.
    collector = manager.get(unique_id)
    if collector is not None and collector.session_id is not None:
        for session in profile["sessions"]:
            if session["session_id"] == collector.session_id:
                stats = collector.stats
                session["gifts"] = stats.get("gifts", session["gifts"]) or 0
                session["diamonds"] = stats.get("diamonds", session["diamonds"]) or 0
                session["comments"] = stats.get("comments", session["comments"]) or 0
                session["likes"] = stats.get("likes_total", session["likes"]) or 0
                session["viewers"] = stats.get("viewers", session["viewers"]) or 0
                session["battles"] = stats.get("battles", session["battles"]) or 0
                session["battle_points"] = stats.get("battle_points", session["battle_points"]) or 0
                session["live"] = True
                # Re-derive the lifetime aggregates so the live session's running
                # numbers are reflected (stats_json is stale until finalize).
                sessions = profile["sessions"]
                metrics = ["gifts", "diamonds", "comments", "likes", "viewers", "duration", "battle_points"]
                count = len(sessions)
                profile["totals"] = {m: sum(s[m] for s in sessions) for m in metrics}
                profile["average"] = {m: (profile["totals"][m] / count if count else 0) for m in metrics}
                profile["best"] = {m: max((s[m] for s in sessions), default=0) for m in metrics}
                break
    return profile


@app.get("/api/streamers/{unique_id}/cohort")
async def streamer_cohort(unique_id: str) -> dict:
    return await asyncio.to_thread(storage.streamer_cohort, unique_id)


@app.get("/api/streamers/{unique_id}/highlights")
async def streamer_highlights(unique_id: str) -> dict:
    highlights = await asyncio.to_thread(storage.streamer_highlights, unique_id)
    return {"highlights": highlights}


def _analytics_since(days: int) -> float:
    """期間フィルタ(直近days日)をstarted_atの下限epochへ。0以下は全期間。"""
    return (time.time() - days * 86400) if days and days > 0 else 0.0


ANALYTICS_INDEX_METRICS = {"joins", "comments", "diamonds", "likes", "follows"}


@app.get("/api/analytics/summary")
async def analytics_summary(days: int = 0) -> dict:
    return await asyncio.to_thread(storage.analytics_summary, _analytics_since(days))


@app.get("/api/analytics/time-index")
async def analytics_time_index(metric: str = "joins", days: int = 0) -> dict:
    if metric not in ANALYTICS_INDEX_METRICS:
        raise HTTPException(status_code=422, detail=f"未対応の指標です: {metric}")
    return await asyncio.to_thread(storage.analytics_time_index, metric, _analytics_since(days))


@app.get("/api/analytics/relations")
async def analytics_relations(days: int = 0) -> dict:
    return await asyncio.to_thread(storage.analytics_relations, _analytics_since(days))


@app.get("/api/analytics/battle-uplift")
async def analytics_battle_uplift(days: int = 0) -> dict:
    return await asyncio.to_thread(storage.analytics_battle_uplift, _analytics_since(days))


@app.get("/api/analytics/share-uplift")
async def analytics_share_uplift(days: int = 0) -> dict:
    return await asyncio.to_thread(storage.analytics_share_uplift, _analytics_since(days))


@app.get("/api/analytics/glove-crit-rate")
async def analytics_glove_crit_rate(days: int = 0) -> dict:
    return await asyncio.to_thread(storage.analytics_glove_crit_rate, _analytics_since(days))


@app.get("/api/analytics/join-quality")
async def analytics_join_quality(days: int = 0) -> dict:
    return await asyncio.to_thread(storage.analytics_join_quality, _analytics_since(days))


@app.get("/api/analytics/scale-efficiency")
async def analytics_scale_efficiency(days: int = 0) -> dict:
    return await asyncio.to_thread(storage.analytics_scale_efficiency, _analytics_since(days))


@app.get("/api/analytics/retention")
async def analytics_retention(days: int = 0) -> dict:
    return await asyncio.to_thread(storage.analytics_retention, _analytics_since(days))


@app.get("/api/analytics/concentration")
async def analytics_concentration(days: int = 0) -> dict:
    return await asyncio.to_thread(storage.analytics_concentration, _analytics_since(days))


@app.get("/api/analytics/join-context")
async def analytics_join_context(days: int = 0) -> dict:
    return await asyncio.to_thread(storage.analytics_join_context, _analytics_since(days))


@app.get("/api/analytics/battle-flow")
async def analytics_battle_flow(days: int = 0) -> dict:
    return await asyncio.to_thread(storage.analytics_battle_flow, _analytics_since(days))


@app.get("/api/analytics/coverage")
async def analytics_coverage(days: int = 0) -> dict:
    return await asyncio.to_thread(storage.analytics_coverage, _analytics_since(days))


@app.get("/api/analytics/entry-source")
async def analytics_entry_source(days: int = 0) -> dict:
    return await asyncio.to_thread(storage.analytics_entry_source, _analytics_since(days))


def _analytics_gift_sku(since: float) -> dict:
    """ギフトSKU構成。reduceに要るのはsession単位payloadだけで、storage側から追加で
    引くものが無いため(gloveの単価表のような横断queryが不要)、ここで組み立てる。"""
    return analytics.reduce_gift_sku(storage._analytics_rows("gift_sku", since))


@app.get("/api/analytics/gift-sku")
async def analytics_gift_sku(days: int = 0) -> dict:
    """コインがどの価格帯のギフトから来ているか、帯ごとの反復購入率、battle内外の構成差。"""
    return await asyncio.to_thread(_analytics_gift_sku, _analytics_since(days))


@app.get("/api/analytics/organic-entries")
async def analytics_organic_entries(days: int = 0) -> dict:
    return await asyncio.to_thread(storage.analytics_organic_entries, _analytics_since(days))


RANKING_STAT_KEYS = {
    "likes": "likes_total",
    "comments": "comments",
    "gifts": "diamonds",
    "battles": "battle_points",
}


@app.get("/api/rankings")
async def session_rankings() -> dict:
    rankings = await asyncio.to_thread(storage.session_rankings, settings.get("session_list_limit"))
    live_stats = {
        snap["session_id"]: snap["stats"]
        for snap in manager.snapshots()
        if snap.get("session_id") is not None
    }
    if live_stats:
        for metric, stat_key in RANKING_STAT_KEYS.items():
            entries = rankings[metric]
            for entry in entries:
                stats = live_stats.get(entry["session_id"])
                if stats is not None:
                    entry["value"] = stats.get(stat_key, entry["value"])
            entries.sort(key=lambda e: e["value"], reverse=True)
    return rankings


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Live update channel for every page.

    The request id is bound by AccessLogMiddleware, which wraps websocket scopes too,
    so every line this connection produces (including the hub's) carries it and one
    client's whole session can be followed through the log.
    """
    await hub.register(websocket)
    try:
        await websocket.send_json(
            js_safe({"type": "monitors", "data": manager.snapshots()}))
        # A page that reloads mid-render has no idea a job is running; hand it the
        # registry so it re-attaches to the progress instead of showing an idle button.
        await websocket.send_json(js_safe({"type": "jobs", "data": _job_snapshot()}))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        # Not a clean disconnect: the page keeps whatever it last rendered until it
        # reconnects, so the reason must not be swallowed by the finally below.
        logger.warning(
            "websocket connection failed", exc_info=True,
            extra={"event": "http.websocket_failed", "ctx": {}},
        )
        raise
    finally:
        await hub.unregister(websocket)


def main() -> None:
    # Logging was configured at import time (see setup_logging above), because the
    # module-level Storage and lock acquisition run before this function is reached.
    host = get_host()
    port = get_port()
    logger.info(
        "starting TicTok LIVE Monitor on http://%s:%d", host, port,
        extra={"event": "process.started", "ctx": {"host": host, "port": port}},
    )
    # log_config=None stops uvicorn from installing its own handlers with
    # propagate=False, which is why its access and error lines have never appeared
    # in the log file. With it unset they propagate to the root handlers.
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=get_log_level().lower(),
        log_config=None,
        timeout_graceful_shutdown=3,
    )


if __name__ == "__main__":
    main()
