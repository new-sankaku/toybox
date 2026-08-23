"""websocket。接続時に監視のsnapshotとjob一覧をこの順で渡してから購読させる。"""

import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from tictok.core.jsonio import js_safe
from fastapi import APIRouter
from tictok.api import media_jobs
from tictok.api import runtime

router = APIRouter()


def _monitor_payload() -> dict:
    """画面へ渡す監視snapshot。recent_eventsは末尾ぶんだけに切る。

    snapshot()が積むrecent_eventsはevent_history件(既定200・上限5000)で、収集中の
    監視1件だけで5.4MBに達する。受け手が使うのは末尾だけで――app.jsは
    slice(-FEED_LIMIT*2)で末尾200件、overview.jsは最後のgift/commentだけ――残りは
    受け取った直後に捨てられている。event_historyはcollectorが抱える履歴の深さで、
    1通のmessageへ載せる量とは別の関心事なので、送信件数は独立の設定で決める。

    js_safeも含めて呼び出し側でthreadへ逃がす。ここはevent loop上で回してはいけない。
    """
    limit = int(runtime.settings.get("ws_recent_events"))
    snapshots = runtime.manager.snapshots()
    for snap in snapshots:
        events = snap.get("recent_events")
        if not isinstance(events, list):
            continue
        snap["recent_events"] = events[-limit:] if limit > 0 else []
    return js_safe({"type": "monitors", "data": snapshots})


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Live update channel for every page.

    The request id is bound by AccessLogMiddleware, which wraps websocket scopes too,
    so every line this connection produces (including the hub's) carries it and one
    client's whole session can be followed through the log.
    """
    await runtime.hub.register(websocket)
    try:
        # snapshotの組み立ては監視の数ぶんのdict生成とevent listのcopy、そこへjs_safeの
        # 全走査が乗る。11画面すべてがWSを張るので、event loop上でやるとその画面が続けて
        # 投げるAPIが丸ごとその後ろに並ぶ(実測: WS接続中の/api/diskが4ms→976〜1177ms)。
        # 下のjobsと同じくthreadへ逃がす。
        payload = await asyncio.to_thread(_monitor_payload)
        await websocket.send_json(payload)
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
