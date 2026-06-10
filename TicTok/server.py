import asyncio
import logging
import re
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from collector import TikTokCollector
from config import get_host, get_log_level, get_port

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
                dead.append(connection)
        if dead:
            async with self._lock:
                for connection in dead:
                    self._connections.discard(connection)


hub = EventHub()
collector = TikTokCollector(broadcast=hub.broadcast)
app = FastAPI(title="TicTok LIVE Monitor")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class StartRequest(BaseModel):
    unique_id: str = Field(min_length=1, max_length=80)


def _normalize_unique_id(raw: str) -> str:
    unique_id = raw.strip().lstrip("@").strip()
    if not UNIQUE_ID_PATTERN.match(unique_id):
        raise HTTPException(
            status_code=422,
            detail="TikTok IDの形式が不正です。英数字・'_'・'.' のみ使用できます。",
        )
    return unique_id


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
async def status() -> dict:
    return collector.snapshot()


@app.get("/api/timeline")
async def timeline() -> dict:
    return collector.timeline_snapshot()


@app.get("/api/summary")
async def summary() -> dict:
    return collector.summary_snapshot()


@app.post("/api/start")
async def start(request: StartRequest) -> dict:
    unique_id = _normalize_unique_id(request.unique_id)
    try:
        await collector.start(unique_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return collector.snapshot()


@app.post("/api/stop")
async def stop() -> dict:
    try:
        await collector.stop()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return collector.snapshot()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await hub.register(websocket)
    try:
        await websocket.send_json({"type": "state", "data": collector.snapshot()})
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
