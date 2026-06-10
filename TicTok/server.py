import asyncio
import csv
import io
import json
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import get_db_path, get_host, get_log_level, get_port
from manager import CollectorManager
from settings import Settings
from storage import Storage

logger = logging.getLogger("tictok.server")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
UNIQUE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.]{1,64}$")


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
storage.cleanup_stale_sessions()
settings = Settings(storage)
manager = CollectorManager(broadcast=hub.broadcast, storage=storage, settings=settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await manager.stop_all()
    storage.close()


app = FastAPI(title="TicTok LIVE Monitor", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class MonitorRequest(BaseModel):
    unique_id: str = Field(min_length=1, max_length=80)


class NoteRequest(BaseModel):
    note: str = Field(max_length=10000)


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
        collector = await manager.start(unique_id)
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


@app.get("/api/monitors/{unique_id}/timeline")
async def monitor_timeline(unique_id: str) -> dict:
    return _get_collector(unique_id).timeline_snapshot()


@app.get("/api/monitors/{unique_id}/summary")
async def monitor_summary(unique_id: str) -> dict:
    return _get_collector(unique_id).summary_snapshot()


@app.get("/api/sessions")
async def list_sessions() -> dict:
    return {
        "sessions": storage.list_sessions(settings.get("session_list_limit")),
        "active_session_ids": sorted(manager.active_session_ids()),
    }


@app.get("/api/sessions/{session_id}")
async def session_detail(session_id: int) -> dict:
    session = _get_session_or_404(session_id)
    timeline = storage.session_timeline(session_id)
    timeline["bucket_seconds"] = session["bucket_seconds"]
    return {
        "session": session,
        "timeline": timeline,
        "summary": storage.session_summary(session_id),
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
    storage.delete_session(session_id)
    return {"deleted": session_id}


@app.get("/api/sessions/{session_id}/export.csv")
async def export_session_csv(session_id: int) -> Response:
    session = _get_session_or_404(session_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["time", "kind", "user_unique_id", "user_nickname", "comment", "text", "gift_name", "gift_count", "diamonds", "like_count"]
    )
    for event in storage.iter_events(session_id):
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
    filename = f"tictok_session_{session_id}_{session['unique_id']}.csv"
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/sessions/{session_id}/export.json")
async def export_session_json(session_id: int) -> Response:
    session = _get_session_or_404(session_id)
    payload = {
        "session": session,
        "summary": storage.session_summary(session_id),
        "timeline": storage.session_timeline(session_id),
        "events": storage.iter_events(session_id),
    }
    filename = f"tictok_session_{session_id}_{session['unique_id']}.json"
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/dashboard")
async def aggregate_dashboard() -> dict:
    return storage.aggregate_dashboard()


RANKING_STAT_KEYS = {
    "likes": "likes_total",
    "comments": "comments",
    "gifts": "diamonds",
    "battles": "battle_points",
}


@app.get("/api/rankings")
async def session_rankings() -> dict:
    rankings = storage.session_rankings(settings.get("session_list_limit"))
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
    logging.basicConfig(
        level=get_log_level(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    host = get_host()
    port = get_port()
    logger.info("starting TicTok LIVE Monitor on http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level=get_log_level().lower())


if __name__ == "__main__":
    main()
