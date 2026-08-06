"""HTTP access logと計測のmiddleware、および静的fileのcache方針。

失敗と遅いrequestだけを書く。理由と、route別gateがgenericな重複抑制で代用できない事情は
``_AccessGate`` のdocstringにある。middlewareの登録は ``tictok.server`` が行い、順序が
挙動に直結する(pure ASGIであることの理由は ``AccessLogMiddleware`` 参照)。

この層は tictok.api の他moduleに依存しない。
"""

import itertools
import logging
import secrets
import threading
import time
from typing import Optional
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from tictok.core.logging_setup import progress_interval_seconds
from tictok.core.logctx import ctx_request_id
from tictok.core.http_cache import static_cache_control
from tictok.core.config import (get_log_access_gate_max_keys, get_log_access_rollup_seconds,
    get_log_slow_http_ms)
from tictok.core import perf


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


def _log_access(scope: dict, status: int, duration_ms: float, *, failed: bool = False,
                breakdown: Optional[dict] = None) -> None:
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
    # 遅かったことだけを書いても次の一手は決まらない。1本の中でDB read・lock待ち・
    # filesystem走査・子processのどれに消えたかを同じ行に載せる(otherは計測点の外)。
    if breakdown:
        ctx["breakdown_ms"] = breakdown
    # A 5xx (or an unhandled exception) is a request whose result is gone with no
    # retry behind it; a 4xx is the client being told to change what it asked for, and
    # a slow success is degradation only.
    level = logging.ERROR if status >= 500 else logging.WARNING
    message = "%s %s -> %d（%.0fms）" % (
        ctx["method"], ctx["path"], status, duration_ms
    )
    parts = [f"{name} {value:.0f}ms" for name, value
             in sorted((breakdown or {}).items(), key=lambda kv: kv[1], reverse=True)[:4]
             if value > 0]
    if parts:
        message += "（内訳 " + " / ".join(parts) + "）"
    if suppressed:
        message += f"（前回の行から他に {suppressed}件）"
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

    同じ理由でここが所要時間の計測点でもある。``perf.request`` が張る内訳の入れ物は
    ContextVar越しにendpointとその ``asyncio.to_thread`` まで届くので、DB・filesystem・
    子processの各計装は呼び出し側を書き換えずに自分の時間をこのrequestへ積める。
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        token = ctx_request_id.set(f"{_REQUEST_ID_PREFIX}-{next(_request_ids)}")
        # WSは1本が配信中ずっと開きっぱなしで、所要時間はrouteの重さではなく接続時間に
        # なる。route別の集計に混ぜると1本で全体を塗り潰すので、計測はHTTPだけにする。
        if scope["type"] != "http":
            try:
                await self.app(scope, receive, send)
            finally:
                ctx_request_id.reset(token)
            return
        started = time.perf_counter()
        # 0 means the response never started (the client aborted); it is not a status
        # the server chose, so it is only ever reported by the slow rule.
        seen = {"status": 0}

        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                seen["status"] = message["status"]
            await send(message)

        with perf.request(scope.get("path", ""), scope.get("method", "")) as measured:
            try:
                await self.app(scope, receive, send_wrapper)
            except Exception:
                self._finish(scope, measured, 500, started, failed=True)
                raise
            else:
                self._finish(scope, measured, seen["status"], started)
            finally:
                ctx_request_id.reset(token)

    @staticmethod
    def _finish(scope, measured, status: int, started: float, *,
                failed: bool = False) -> None:
        duration_ms = (time.perf_counter() - started) * 1000.0
        route = _route_key(scope)
        breakdown = measured.breakdown() if measured is not None else None
        if measured is not None:
            perf.observe(route, duration_ms, failed=failed or status >= 500,
                         phases=measured.phases())
            perf.maybe_log_rollup()
        _log_access(scope, status, duration_ms, failed=failed, breakdown=breakdown)


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
