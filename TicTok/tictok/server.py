import asyncio
import atexit
import csv
import io
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tictok.paths import PROJECT_ROOT
from tictok.media.avatar_pool import AvatarPool
from tictok.media.avatar_proxy import AvatarProxy
from tictok.media.gift_icons import GiftIconCache
from tictok.ai.ai_analysis import AIError, ai_status, analyze_comments, analyze_streamer
from tictok.core.config import (
    get_ai_comment_sample,
    get_avatar_fetch_attempts,
    get_avatar_fetch_backoff_seconds,
    get_avatar_fetch_concurrency,
    get_db_path,
    get_host,
    get_log_dir,
    get_log_level,
    get_port,
    get_record_dir,
)
from tictok.collect.manager import CollectorManager
from tictok.core.process_lock import ProcessLock, ProcessLockError
from tictok.record.recorder import ffmpeg_available, migrate_sidecars
from tictok.record.transcription import STTError, stt_status
from tictok.record.transcription import transcribe as stt_transcribe
from tictok.record.upscale import (
    UpscaleError,
    cleanup_upscale_files,
    ensure_upscaled,
    upscale_done,
    upscale_input_path,
    upscale_status,
)
from tictok.core.settings import Settings
from tictok.storage import Storage
from tictok.record.video_overlay import (
    cleanup_overlay_files,
    codec_family,
    ensure_overlay,
    overlay_enabled,
    overlay_paths,
    timing_path,
    video_encoder_name,
)

logger = logging.getLogger("tictok.server")

BASE_DIR = PROJECT_ROOT
STATIC_DIR = BASE_DIR / "static"
RECORD_DIR = Path(get_record_dir()).resolve()
UNIQUE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.]{1,64}$")
# Number of recent finished sessions averaged for the monitor page's
# "past streams" comparison (今回 / 前回 / 平均 / 自己Best).
HISTORY_COMPARE_LIMIT = 5
# A finished recording's bytes are immutable, so playback can cache them privately;
# a still-recording file keeps changing and must not be cached.
RECORDING_CACHE_MAX_AGE_SECONDS = 86400


def _safe_recording_path(raw_path: str) -> Path:
    """Resolve a stored recording path and ensure it stays under the record dir."""
    path = Path(raw_path).resolve()
    if RECORD_DIR not in path.parents and path != RECORD_DIR:
        raise HTTPException(status_code=400, detail="不正な録画pathです。")
    return path


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
        logger.info("websocket client connected (total=%d)", len(self._connections))

    async def unregister(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
        logger.info("websocket client disconnected (total=%d)", len(self._connections))

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            connections = list(self._connections)
        dead: list[WebSocket] = []
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception:
                logger.debug("dropping dead websocket connection", exc_info=True)
                dead.append(connection)
        if dead:
            async with self._lock:
                for connection in dead:
                    self._connections.discard(connection)


hub = EventHub()
storage = Storage(get_db_path())
# Acquire the single-instance lock before cleanup_stale_sessions() — that call
# finalizes every connecting/connected session unconditionally, so a second
# process starting here would otherwise terminate the first process's live
# session and both would then collect the same rooms in parallel.
instance_lock = ProcessLock(get_db_path() + ".lock")
try:
    instance_lock.acquire()
except ProcessLockError as exc:
    logger.error("cannot start: %s", exc)
    raise SystemExit(1)
atexit.register(instance_lock.release)
storage.cleanup_stale_sessions()
storage.mark_stale_recordings()
# Relocate sidecars older recordings wrote next to the .mp4 into per-folder
# .sidecars/, so the recordings root holds only the .mp4 files.
migrate_sidecars(RECORD_DIR)
settings = Settings(storage)
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await manager.startup()
    await manager.restore()
    yield
    await manager.stop_all()
    await manager.shutdown()
    await avatar_proxy.aclose()
    await gift_icons.aclose()
    await avatar_pool.aclose()
    storage.close()
    instance_lock.release()


app = FastAPI(title="TicTok LIVE Monitor", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/overview")
async def overview_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "overview.html")


@app.get("/history")
async def history_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "history.html")


@app.get("/settings")
async def settings_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "settings.html")


@app.get("/battle")
async def battle_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "battle.html")


@app.get("/streamers")
async def streamers_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "streamers.html")


@app.get("/analytics")
async def analytics_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "analytics.html")


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
        raise HTTPException(status_code=422, detail=str(exc))
    return {"settings": settings.describe(), "values": updated}


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
async def live_recording(unique_id: str, filename: str) -> FileResponse:
    path = manager.live_recording_file(unique_id, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="ライブ録画が見つかりません。")
    media_type = "application/vnd.apple.mpegurl" if path.suffix == ".m3u8" else "video/mp2t"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-cache"})


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
async def list_sessions() -> dict:
    sessions = await asyncio.to_thread(storage.list_sessions, settings.get("session_list_limit"))
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
    battle list, so serve that; once ended, read the saved rows."""
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


@app.post("/api/recordings/{recording_id}/output")
async def output_recording(recording_id: int) -> dict:
    """設定でComment/Gift演出が有効なら、収集eventを焼き込んだ動画をrecordings
    folderへ出力する。ブラウザへはダウンロードせず、出力先のfile名を返す。"""
    recording = storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    path = _safe_recording_path(recording["path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="録画fileが存在しません（削除済みか録画失敗）。")
    rendered = path
    payload: dict = {}
    if overlay_enabled(settings) and recording.get("session_id") is not None:
        events = storage.iter_events(recording["session_id"])
        battles = storage.battles_for_session(recording["session_id"])

        async def _emit_progress(pct: int) -> None:
            await hub.broadcast(
                {"type": "output_progress", "recording_id": recording_id, "pct": pct}
            )

        try:
            result = await ensure_overlay(
                str(path), recording["started_at"], recording.get("ended_at"),
                events, settings, battles=battles, on_progress=_emit_progress,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        rendered = _safe_recording_path(str(result["a"]))
        # Mode B (source-clock timing) comparison output, present only when the
        # compare setting is on and the recording carried create_time to anchor on.
        out_b = result.get("b")
        if out_b is not None:
            rendered_b = _safe_recording_path(str(out_b))
            payload["filename_b"] = rendered_b.name
            payload["output_path_b"] = str(rendered_b)
    payload.update({
        "recording_id": recording_id,
        "filename": rendered.name,
        "output_path": str(rendered),
        "rendered": rendered != path,
    })
    return payload


@app.get("/api/upscale/status")
async def upscale_status_api() -> dict:
    return upscale_status()


@app.post("/api/recordings/{recording_id}/upscale-output")
async def upscale_output_recording(recording_id: int) -> dict:
    """AI高画質化(超解像)出力。焼き込みが有効な場合はまず通常の出力(焼き込み)を確保し
    (進捗はoutput_progress)、その動画をローカルAI modelで高画質化して .up.mp4 として
    recordings folderへ出力する(進捗はupscale_progress)。"""
    recording = storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    path = _safe_recording_path(recording["path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="録画fileが存在しません（削除済みか録画失敗）。")
    rendered = path
    if overlay_enabled(settings) and recording.get("session_id") is not None:
        events = storage.iter_events(recording["session_id"])
        battles = storage.battles_for_session(recording["session_id"])

        async def _emit_progress(pct: int) -> None:
            await hub.broadcast(
                {"type": "output_progress", "recording_id": recording_id, "pct": pct}
            )

        try:
            result = await ensure_overlay(
                str(path), recording["started_at"], recording.get("ended_at"),
                events, settings, battles=battles, on_progress=_emit_progress,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        rendered = _safe_recording_path(str(result["a"]))

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
            hub.broadcast({"type": "upscale_progress", "recording_id": recording_id, "pct": pct}),
            loop,
        )

    try:
        out = await asyncio.to_thread(
            ensure_upscaled, str(rendered), encoder,
            int(settings.get("video_overlay_quality")), on_progress,
        )
    except UpscaleError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    await hub.broadcast({"type": "upscale_progress", "recording_id": recording_id, "pct": 100})
    return {
        "recording_id": recording_id,
        "filename": out.name,
        "output_path": str(out),
        "source": rendered.name,
    }


@app.get("/api/recordings/{recording_id}/play")
async def play_recording(recording_id: int) -> FileResponse:
    """Stream a finished recording for in-browser playback (highlight deep-link).
    FileResponse honours the Range header, so the <video> element can seek to the
    highlight offset without downloading the whole file."""
    recording = storage.get_recording(recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    path = _safe_recording_path(recording["path"])
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

    def on_progress(done: float, total: float) -> None:
        pct = min(100, int(done / total * 100)) if total > 0 else 0
        asyncio.run_coroutine_threadsafe(
            hub.broadcast({"type": "transcribe_progress", "recording_id": recording_id, "pct": pct}),
            loop,
        )

    try:
        result = await asyncio.to_thread(stt_transcribe, str(path), on_progress)
    except STTError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    storage.save_transcript(recording_id, result)
    await hub.broadcast({"type": "transcribe_progress", "recording_id": recording_id, "pct": 100})
    return {
        "recording_id": recording_id,
        "language": result["language"],
        "model": result["model"],
        "duration": result["duration"],
        "text": result["text"],
        "segments": result["segments"],
        "segments_count": len(result["segments"]),
    }


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


@app.get("/api/sessions/{session_id}/comment-analysis")
async def session_comment_analysis(session_id: int) -> dict:
    _get_session_or_404(session_id)
    comments = await asyncio.to_thread(storage.session_comments, session_id, get_ai_comment_sample())
    if not comments:
        raise HTTPException(status_code=404, detail="このSessionに分析できるCommentがありません。")
    try:
        analysis = await analyze_comments(comments)
    except AIError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"session_id": session_id, "comment_count": len(comments), "analysis": analysis}


@app.get("/api/streamers/{unique_id}/ai-review")
async def streamer_ai_review(unique_id: str) -> dict:
    """Natural-language growth review of a streamer from their aggregated profile.
    A compact summary (no raw events) is sent to the local model."""
    profile = await asyncio.to_thread(storage.streamer_profile, unique_id)
    if profile["count"] == 0:
        raise HTTPException(status_code=404, detail="この配信者の集計データがありません。")
    battles = profile["battles"]
    heatmap_top = sorted(profile["heatmap"], key=lambda c: c["diamonds"], reverse=True)[:5]
    review_input = {
        "配信者": profile["identity"]["nickname"],
        "配信回数": profile["count"],
        "通算": profile["totals"],
        "平均": {k: round(v) for k, v in profile["average"].items()},
        "自己ベスト": profile["best"],
        "収益集中度": profile["concentration"],
        "Battle": {
            k: battles[k]
            for k in ("count", "wins", "losses", "win_rate", "avg_own_score", "avg_opp_score", "battle_diamond_share")
        },
        "上位gifter": [
            {"name": g["nickname"], "diamonds": g["diamonds"], "出現session": g["sessions"]}
            for g in profile["gifters"][:10]
        ],
        "Battle上位gifter": [
            {"name": g["nickname"], "diamonds": g["diamonds"], "出現battle": g["battles"]}
            for g in battles.get("gifters", [])[:8]
        ],
        "稼ぐ時間帯top": [
            {
                "曜日": ["日", "月", "火", "水", "木", "金", "土"][c["dow"]],
                "時刻": f"{c['hour']:02d}:{c['quarter'] * 15:02d}",
                "コイン": c["diamonds"],
            }
            for c in heatmap_top
        ],
    }
    try:
        review = await analyze_streamer(review_input)
    except AIError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"unique_id": unique_id, "review": review}


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
    await hub.register(websocket)
    try:
        await websocket.send_json({"type": "monitors", "data": manager.snapshots()})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unregister(websocket)


def main() -> None:
    log_format = "%(asctime)s %(levelname)s %(name)s %(message)s"
    # Persist logs to a rotating file (in addition to the console) so best-effort
    # failures such as avatar persist errors survive the session and can be
    # diagnosed after the fact. RotatingFileHandler works on Windows and Linux.
    log_dir = Path(get_log_dir())
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / "tictok.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(log_format))
    logging.basicConfig(
        level=get_log_level(),
        format=log_format,
        handlers=[logging.StreamHandler(), file_handler],
    )
    # httpx logs one INFO line per request ("HTTP Request: GET ... 200 OK"); each
    # live-check probe already logs its own outcome, so the httpx line is pure
    # noise. Silence it unless explicitly debugging.
    if get_log_level().upper() != "DEBUG":
        logging.getLogger("httpx").setLevel(logging.WARNING)
    host = get_host()
    port = get_port()
    logger.info("starting TicTok LIVE Monitor on http://%s:%d", host, port)
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=get_log_level().lower(),
        timeout_graceful_shutdown=3,
    )


if __name__ == "__main__":
    main()
