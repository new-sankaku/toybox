"""applicationの組み立てと起動。

中身は ``tictok.api`` 配下にあり、ここはそれを1つのFastAPIへ載せるだけの薄い層である。
``main.py`` が ``from tictok.server import main`` で入ってくる唯一の入口でもある。

順序が挙動に直結するので動かさないこと:

1. ``tictok.api.runtime`` を最初に読む。logの初期化・Storage・単一instance lockが
   import時に走るため、これより前に何かを読むとその出力がlog fileへ入らない。
2. middlewareはrouteより先に登録する(pure ASGIで、requestのidと計測点を張る)。
3. ``/static`` のmountはrouteより前。以降のrouterの取り込み順は元fileのroute定義順。
"""

import uvicorn
from fastapi import FastAPI

from tictok.api import runtime
from tictok.api import access_log
from tictok.api import startup
from tictok.api.routes import (
    ai, analytics, bulk, clips, media, monitors, pages, recordings, search, sessions,
    storage, streamers, system, ws,
)
from tictok.core.config import get_host, get_log_level, get_port
from tictok.core.jsonio import JsSafeJSONResponse

app = FastAPI(title="TicTok LIVE Monitor", lifespan=startup.lifespan,
              default_response_class=JsSafeJSONResponse)
app.add_middleware(access_log.AccessLogMiddleware)
app.mount("/static", access_log.CachePolicyStaticFiles(directory=runtime.STATIC_DIR),
          name="static")

# 取り込み順は元fileでrouteが定義されていた順(=各routerの先頭routeの位置)。pathの重なりは
# 無いので一致判定には効かないが、/docs と openapi.json の並びを動かさないため。
app.include_router(pages.router)
app.include_router(system.router)
app.include_router(monitors.router)
app.include_router(sessions.router)
app.include_router(recordings.router)
app.include_router(storage.router)
app.include_router(media.router)
# 成果物を作る側(media)の直後。/api/clips のGET・DELETEはこちら、POST /api/clips/batch は
# 投入口なのでmedia側に居る(pathは重なるがmethodが違うので一致判定には効かない)。
app.include_router(clips.router)
app.include_router(bulk.router)
app.include_router(search.router)
app.include_router(ai.router)
app.include_router(streamers.router)
app.include_router(analytics.router)
app.include_router(ws.router)


def main() -> None:
    # Logging was configured at import time (see setup_logging above), because the
    # module-level Storage and lock acquisition run before this function is reached.
    host = get_host()
    port = get_port()
    runtime.logger.info(
        "TicTok LIVE Monitorを http://%s:%d で起動します", host, port,
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
