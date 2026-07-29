"""websocket。接続時に監視のsnapshotとjob一覧をこの順で渡してから購読させる。"""

import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from tictok.core.jsonio import js_safe
from fastapi import APIRouter
from tictok.api import media_jobs
from tictok.api import runtime

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Live update channel for every page.

    The request id is bound by AccessLogMiddleware, which wraps websocket scopes too,
    so every line this connection produces (including the hub's) carries it and one
    client's whole session can be followed through the log.
    """
    await runtime.hub.register(websocket)
    try:
        await websocket.send_json(
            js_safe({"type": "monitors", "data": runtime.manager.snapshots()}))
        # A page that reloads mid-render has no idea a job is running; hand it the
        # registry so it re-attaches to the progress instead of showing an idle button.
        # 台帳の読みはDBなので、接続のたびにevent loop上で書き込みlockを待つことになる。
        # WSは画面を開くたびに張られる(=収集中ほど頻繁)ので、ここもthreadへ逃がす。
        jobs = await asyncio.to_thread(media_jobs._job_snapshot)
        await websocket.send_json(js_safe({"type": "jobs", "data": jobs}))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        # Not a clean disconnect: the page keeps whatever it last rendered until it
        # reconnects, so the reason must not be swallowed by the finally below.
        runtime.logger.warning(
            "websocketの接続が異常終了しました", exc_info=True,
            extra={"event": "http.websocket_failed", "ctx": {}},
        )
        raise
    finally:
        await runtime.hub.unregister(websocket)
