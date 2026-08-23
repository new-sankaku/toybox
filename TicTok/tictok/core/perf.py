"""API単位の所要時間計測。

「画面が重い」を調べるとき、遅かった1本のrequestを見ても答えは出ない。1秒待たされる画面は
「1回800msの重いAPIが1本」でも「8msのAPIが100本」でも同じ体感になり、前者と後者では直す
場所が違う。ここは route ごとに件数・合計・分位数を積み、さらに1本のrequestの中で時間が
どこ(DB read / filesystem走査 / 子process / 集計計算)へ消えたかを内訳として持つ。

計測の入り口は2つだけ:

- ``request(path)``  — HTTP middlewareが1 requestを囲む。routeは routing 後に決まるので
  終了時に ``RequestPerf.finish`` へ渡す。
- ``phase(name)``    — 内訳を積む区間。request contextの外(collector・録画・起動sweep)では
  ContextVarがNoneなので、``phase`` は時計すら読まずに素通りする。

内訳はContextVarの中の可変dictへ積む。``asyncio.to_thread`` はcontextをcopyするが、copyが
指すdictは同一objectなので、worker threadで測った区間もそのままrequestへ戻る(dictの更新は
lockで保護する — 1 requestが複数threadへ同時に出ることがある)。

event loopの遅れ(``loop_lag_monitor``)だけはrequest単位ではなくprocess単位で測る。loopを
握ったまま返さないcoroutineが1本あると全画面が同時に遅くなるが、その被害はrequestごとの
所要時間には「全員が少しずつ遅い」としか現れず、原因のrequestは名指しできない。probeは
自分のsleepがどれだけ延びたかを測り、延びた瞬間に在庫していたrequestを一緒に記録する。
"""

import asyncio
import logging
import math
import os
import sqlite3
import sys
import threading
import time
import traceback
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar

from tictok.core.config import (
    get_perf_enabled,
    get_perf_loop_lag_interval_seconds,
    get_perf_loop_lag_warn_ms,
    get_perf_stall_sample_enabled,
    get_perf_stall_sample_ms,
    get_perf_max_routes,
    get_perf_rollup_seconds,
    get_perf_rollup_top,
    get_perf_sample_window,
)

logger = logging.getLogger("tictok.perf")

# routeが決まらなかったrequest(未routingの404・静的file以外の素通り)を1つのkeyへ畳む。
# pathをkeyにするとURL scanが数千keyを作る。
UNMATCHED_ROUTE = "<unmatched>"
# 追跡上限を超えた分の受け皿。件数と合計は失わないが、内訳は混ざるので名前で明示する。
OVERFLOW_ROUTE = "<overflow>"


class RequestPerf:
    """1 requestぶんの内訳の入れ物。ContextVarに載って、worker threadへも同じobjectが渡る。"""

    __slots__ = ("path", "method", "started", "_phases", "_lock")

    def __init__(self, path: str, method: str) -> None:
        self.path = path
        self.method = method
        self.started = time.perf_counter()
        self._phases: dict = {}
        self._lock = threading.Lock()

    def add(self, name: str, duration_ms: float) -> None:
        with self._lock:
            slot = self._phases.get(name)
            if slot is None:
                self._phases[name] = [1, duration_ms]
            else:
                slot[0] += 1
                slot[1] += duration_ms

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000.0

    def phases(self) -> dict:
        """``{name: [count, ms]}`` のsnapshot。値のlistもcopyして返す(呼び出し側が読んで
        いる最中にworker threadが加算しても壊れないため)。"""
        with self._lock:
            return {name: [slot[0], slot[1]] for name, slot in self._phases.items()}

    def breakdown(self) -> dict:
        """log行に載せる形の内訳。``{name: ms(小数1桁)}`` に ``other`` を足す。

        ``other`` は「計測した区間のどれにも入らなかった時間」で、payloadの組み立てや
        JSON化、awaitの待ちがここへ落ちる。計測点が足りていない区間もここに見えるので、
        otherが支配的なrouteは次に計装を足す場所そのものになる。"""
        phases = self.phases()
        measured = sum(slot[1] for slot in phases.values())
        out = {name: round(slot[1], 1) for name, slot in phases.items()}
        # 積んであるのは各区間の自分の時間なので、合計は全体を超えない。並行に走った
        # thread(1 requestが複数のto_threadを同時に出す場合)だけは超え得るため、負の
        # otherを出す代わりに0で止める。
        out["other"] = round(max(0.0, self.elapsed_ms() - measured), 1)
        return out


_current: ContextVar = ContextVar("tictok_request_perf", default=None)


def current() -> "RequestPerf | None":
    return _current.get()


@contextmanager
def request(path: str, method: str = ""):
    """1 requestを囲み、内訳の入れ物をContextVarへ束ねる。計測が無効なら何もしない。"""
    if not get_perf_enabled():
        yield None
        return
    perf = RequestPerf(path, method)
    token = _current.set(perf)
    _inflight_add(perf)
    try:
        yield perf
    finally:
        _inflight_remove(perf)
        _current.reset(token)


# 入れ子の区間を「自分の時間」に分けるためのthread別stack。集計stageの中でDB readが
# 走るような入れ子は普通に起きるので、素の経過時間をそのまま積むと合計が全体を超え、
# 内訳が割合として読めなくなる。
_stack = threading.local()


@contextmanager
def phase(name: str):
    """内訳を1区間ぶん積む。request contextの外では時計も読まずに素通りする。

    素通りが効くのはこのモジュールの前提そのもの: DB接続やfilesystem helperはcollectorや
    録画pipelineからも同じ道を通るので、request以外の呼び出しに計測費用を負わせない。

    積むのは**自分の時間**(経過 − 内側の区間の合計)。集計stageの中のDB readのように区間は
    入れ子になるので、経過をそのまま積むと同じ時間を二重に数えて内訳の合計が全体を超える。

    囲めるのは同期の区間だけ。``await`` を跨ぐと、中断中に同じthreadで別のcoroutineが開いた
    区間と入れ子関係が混ざる。非同期の処理(子processの待ち等)は ``record`` で測った値を渡す。
    """
    perf = _current.get()
    if perf is None:
        yield
        return
    stack = getattr(_stack, "frames", None)
    if stack is None:
        stack = []
        _stack.frames = stack
    frame = [0.0]
    stack.append(frame)
    started = time.perf_counter()
    try:
        yield
    finally:
        total = (time.perf_counter() - started) * 1000.0
        stack.pop()
        if stack:
            stack[-1][0] += total
        perf.add(name, total - frame[0])


def record(name: str, duration_ms: float) -> None:
    """既に測ってある時間を内訳へ積む(子processの実行時間など、区間で囲めない場合用)。"""
    perf = _current.get()
    if perf is not None:
        perf.add(name, duration_ms)


@contextmanager
def timer(name: str):
    """``await`` を含む区間用。``phase`` と違って入れ子の管理をしないので、内側に別の
    計測区間を含めないこと(子processの起動〜終了待ちのような葉の区間に使う)。

    ``phase`` を使えないのは、awaitで中断している間に同じthreadの別requestが区間を開き、
    thread別stackの入れ子が混ざるため。"""
    started = time.perf_counter()
    try:
        yield
    finally:
        record(name, (time.perf_counter() - started) * 1000.0)


# ---- route別の集計 --------------------------------------------------------------------


class _RouteStat:
    __slots__ = ("count", "failed", "total_ms", "max_ms", "last_ms", "last_ts",
                 "samples", "phases", "win_count", "win_total_ms", "win_max_ms")

    def __init__(self, window: int) -> None:
        self.count = 0
        self.failed = 0
        self.total_ms = 0.0
        self.max_ms = 0.0
        self.last_ms = 0.0
        self.last_ts = 0.0
        # 分位数は個々の値からしか出ない。合計だけでは「たまに3秒」を平均が飲み込む。
        self.samples: deque = deque(maxlen=max(1, window))
        self.phases: dict = {}
        self.win_count = 0
        self.win_total_ms = 0.0
        self.win_max_ms = 0.0


_stats: dict = {}
_stats_lock = threading.Lock()
_since = time.time()
_last_rollup = time.monotonic()


def observe(route: str, duration_ms: float, *, failed: bool = False,
            phases: dict | None = None) -> None:
    """1 requestの結果を route の集計へ積む。"""
    with _stats_lock:
        stat = _stats.get(route)
        if stat is None:
            if len(_stats) >= get_perf_max_routes():
                route = OVERFLOW_ROUTE
                stat = _stats.get(route)
            if stat is None:
                stat = _RouteStat(get_perf_sample_window())
                _stats[route] = stat
        stat.count += 1
        if failed:
            stat.failed += 1
        stat.total_ms += duration_ms
        stat.max_ms = max(stat.max_ms, duration_ms)
        stat.last_ms = duration_ms
        stat.last_ts = time.time()
        stat.samples.append(duration_ms)
        stat.win_count += 1
        stat.win_total_ms += duration_ms
        stat.win_max_ms = max(stat.win_max_ms, duration_ms)
        for name, slot in (phases or {}).items():
            acc = stat.phases.get(name)
            if acc is None:
                stat.phases[name] = [slot[0], slot[1]]
            else:
                acc[0] += slot[0]
                acc[1] += slot[1]


def _percentile(values: list, q: float) -> float:
    """nearest-rank。標本数が数百のwindowでは補間しても意味の差が出ず、実在した1本の
    所要時間をそのまま返す方が「その値のrequestが本当にあった」と言える。"""
    if not values:
        return 0.0
    rank = max(1, min(len(values), math.ceil(q * len(values))))
    return values[rank - 1]


def _route_row(route: str, stat: _RouteStat) -> dict:
    values = sorted(stat.samples)
    return {
        "route": route,
        "count": stat.count,
        "failed": stat.failed,
        "total_ms": round(stat.total_ms, 1),
        "avg_ms": round(stat.total_ms / stat.count, 1) if stat.count else 0.0,
        "p50_ms": round(_percentile(values, 0.50), 1),
        "p95_ms": round(_percentile(values, 0.95), 1),
        "p99_ms": round(_percentile(values, 0.99), 1),
        "max_ms": round(stat.max_ms, 1),
        "last_ms": round(stat.last_ms, 1),
        "last_ts": stat.last_ts,
        "samples": len(stat.samples),
        "phases": {name: {"count": slot[0], "ms": round(slot[1], 1),
                          "avg_ms": round(slot[1] / slot[0], 2) if slot[0] else 0.0}
                   for name, slot in sorted(stat.phases.items())},
    }


def snapshot(limit: int = 0) -> dict:
    """集計の読み出し。合計時間の降順 = 「直すと一番効く順」で返す。

    平均や最大の降順ではない: 1回3秒でも1日1回しか呼ばれないrouteより、40msでも毎秒
    叩かれるrouteの方がserverを占有している。"""
    with _stats_lock:
        rows = [_route_row(route, stat) for route, stat in _stats.items()]
        since = _since
    rows.sort(key=lambda row: row["total_ms"], reverse=True)
    total_ms = sum(row["total_ms"] for row in rows)
    total_count = sum(row["count"] for row in rows)
    for row in rows:
        row["share"] = round(row["total_ms"] / total_ms, 4) if total_ms else 0.0
    if limit > 0:
        rows = rows[:limit]
    return {
        "enabled": get_perf_enabled(),
        "since": since,
        "window_seconds": round(max(0.0, time.time() - since), 1),
        "routes": rows,
        "route_count": len(_stats),
        "request_count": total_count,
        "total_ms": round(total_ms, 1),
        "loop_lag": loop_lag_snapshot(),
        "inflight": inflight_snapshot(),
    }


def reset() -> dict:
    """集計を捨てて測り直す。変更の前後を比べるときは、これで区間を切ってから操作する。"""
    global _since, _last_rollup
    with _stats_lock:
        dropped = len(_stats)
        _stats.clear()
        _since = time.time()
    _last_rollup = time.monotonic()
    _loop_lag_reset()
    return {"cleared_routes": dropped, "since": _since}


def _rollup_rows() -> list:
    """直近interval分の集計を取り出し、窓のcounterを畳む。"""
    with _stats_lock:
        rows = []
        for route, stat in _stats.items():
            if not stat.win_count:
                continue
            rows.append({
                "route": route,
                "count": stat.win_count,
                "total_ms": round(stat.win_total_ms, 1),
                "avg_ms": round(stat.win_total_ms / stat.win_count, 1),
                "max_ms": round(stat.win_max_ms, 1),
            })
            stat.win_count = 0
            stat.win_total_ms = 0.0
            stat.win_max_ms = 0.0
    rows.sort(key=lambda row: row["total_ms"], reverse=True)
    return rows


def maybe_log_rollup() -> None:
    """intervalを跨いだら、その区間の重いroute上位を1行で書き出す。

    per-requestのslow行とは役割が違う: あちらは「この1本が遅かった」、こちらは
    「この区間でserverの時間を食ったのは誰か」。速いが多いrouteは前者には一生出ない。"""
    global _last_rollup
    interval = get_perf_rollup_seconds()
    if interval <= 0:
        return
    now = time.monotonic()
    if now - _last_rollup < interval:
        return
    elapsed = now - _last_rollup
    _last_rollup = now
    rows = _rollup_rows()
    if not rows:
        return
    top = rows[: max(1, get_perf_rollup_top())]
    total_ms = sum(row["total_ms"] for row in rows)
    total_count = sum(row["count"] for row in rows)
    summary = " / ".join(
        f"{row['route']} {row['count']}回 {row['total_ms']:.0f}ms(平均{row['avg_ms']:.0f}"
        f"・最大{row['max_ms']:.0f})" for row in top
    )
    logger.info(
        "API所要時間の集計（直近%.0f秒 / %d件 / 合計%.0fms）: %s",
        elapsed, total_count, total_ms, summary,
        extra={"event": "http.perf_rollup",
               "ctx": {"window_seconds": round(elapsed, 1), "requests": total_count,
                       "total_ms": round(total_ms, 1), "routes": top,
                       "route_count": len(rows)}},
    )


# ---- 進行中requestとevent loopの遅れ ----------------------------------------------------

_inflight: dict = {}
_inflight_lock = threading.Lock()
_loop_lag = {"max_ms": 0.0, "warned": 0, "last_ms": 0.0, "last_ts": 0.0}


def _inflight_add(perf: RequestPerf) -> None:
    with _inflight_lock:
        _inflight[id(perf)] = perf


def _inflight_remove(perf: RequestPerf) -> None:
    with _inflight_lock:
        _inflight.pop(id(perf), None)


def inflight_snapshot() -> list:
    """今まさに処理中のrequest。古い順(＝待たせている順)に返す。"""
    with _inflight_lock:
        items = list(_inflight.values())
    rows = [{"path": perf.path, "method": perf.method,
             "elapsed_ms": round(perf.elapsed_ms(), 1)} for perf in items]
    rows.sort(key=lambda row: row["elapsed_ms"], reverse=True)
    return rows


def loop_lag_snapshot() -> dict:
    return dict(_loop_lag)


def _loop_lag_reset() -> None:
    _loop_lag.update({"max_ms": 0.0, "warned": 0, "last_ms": 0.0, "last_ts": 0.0})


def note_loop_lag(lag_ms: float) -> None:
    """probeが測った遅れを記録し、閾値を超えていれば在庫requestごと書き出す。"""
    _loop_lag["last_ms"] = round(lag_ms, 1)
    _loop_lag["last_ts"] = time.time()
    if lag_ms > _loop_lag["max_ms"]:
        _loop_lag["max_ms"] = round(lag_ms, 1)
    warn_ms = get_perf_loop_lag_warn_ms()
    if lag_ms < warn_ms:
        return
    _loop_lag["warned"] += 1
    inflight = inflight_snapshot()
    # 犯人がrequestとは限らない(collectorのeventループや録画のfinalizeも同じloopに居る)。
    # 「この時刻に居たrequest」までしか言えないので、log文もそう名乗る。
    where = " / ".join(f"{row['method']} {row['path']}（{row['elapsed_ms']:.0f}ms経過）"
                       for row in inflight[:5]) or "処理中のrequestなし"
    logger.warning(
        "event loopが%.0fms止まりました（同時刻に処理中: %s）", lag_ms, where,
        extra={"event": "http.loop_lag",
               "ctx": {"lag_ms": round(lag_ms, 1), "warn_ms": warn_ms,
                       "inflight": inflight[:5], "inflight_count": len(inflight)}},
    )


# ---- 停止しているloopを外から覗く番人 -----------------------------------------------------

# stackは深い側が犯人に近い。全部出すとlogが読めなくなるので、末尾だけを残す。
_STALL_STACK_FRAMES = 14

_loop_thread_id = None
_loop_heartbeat = [0.0]
_stall_watchdog_started = False


def _stall_watchdog() -> None:
    """event loopが止まっている**最中**に、loop threadのstackを写す番人thread。

    ``note_loop_lag`` はloopが動き出してから呼ばれるので、そこで写しても犯人は既に戻って
    いる。実測でも停止836件のうち **593件(71%)が「同時刻に処理中のrequestなし」** で、
    requestの一覧だけでは辿り着けなかった。止まっている間に覗けるのは、そのloopに乗って
    いない別threadだけである。

    平常時の費用はtickごとの引き算1回。stackを歩くのは停止1回につき1度だけで、同じ停止の
    間は二度写さない(写した瞬間のframeが全てで、同じ停止を何枚撮っても中身は変わらない)。"""
    armed = False
    while True:
        threshold_ms = get_perf_stall_sample_ms()
        # 閾値の1/8で見張る。停止の始まりからそのぶん遅れて写ることになるので、粒度は
        # 閾値に従わせる(独立のつまみを増やしても調整する材料が無い)。
        time.sleep(max(0.05, threshold_ms / 8000.0))
        if not (get_perf_enabled() and get_perf_stall_sample_enabled()):
            continue
        tid, beat = _loop_thread_id, _loop_heartbeat[0]
        if tid is None or beat <= 0.0:
            continue
        stalled_ms = (time.perf_counter() - beat) * 1000.0
        if stalled_ms < threshold_ms:
            armed = True
            continue
        if not armed:
            continue
        armed = False
        frames = sys._current_frames().get(tid)
        if frames is None:
            stack = ["(loop threadのstackを取得できませんでした)"]
        else:
            stack = [line.rstrip() for line
                     in traceback.format_stack(frames)[-_STALL_STACK_FRAMES:]]
        inflight = inflight_snapshot()
        logger.warning(
            "event loopが%.0fms止まっている最中のstackです（同時刻に処理中: %s）",
            stalled_ms,
            " / ".join(f"{row['method']} {row['path']}" for row in inflight[:3])
            or "処理中のrequestなし",
            extra={"event": "http.loop_stall_stack",
                   "ctx": {"stalled_ms": round(stalled_ms, 1),
                           "threshold_ms": threshold_ms,
                           "inflight_count": len(inflight),
                           "stack": stack}},
        )


def _start_stall_watchdog() -> None:
    global _stall_watchdog_started, _loop_thread_id
    _loop_thread_id = threading.get_ident()
    if _stall_watchdog_started:
        return
    _stall_watchdog_started = True
    threading.Thread(target=_stall_watchdog, name="perf-stall-watchdog",
                     daemon=True).start()


async def loop_lag_monitor() -> None:
    """event loopの遅れを測り続ける常駐task。lifespanが起動し、shutdownでcancelされる。"""
    interval = max(0.05, get_perf_loop_lag_interval_seconds())
    # 番人はこのtaskと同じ生き死にで良いが、loopに乗せると止まった時に一緒に止まるので
    # thread側に置く。loop threadの身元はここでしか分からない。
    _start_stall_watchdog()
    while True:
        started = time.perf_counter()
        await asyncio.sleep(interval)
        _loop_heartbeat[0] = time.perf_counter()
        if not get_perf_enabled():
            continue
        note_loop_lag(max(0.0, (time.perf_counter() - started - interval) * 1000.0))


# ---- 計測付きの土台(SQLite接続・lock) -----------------------------------------------------


class TimedConnection(sqlite3.Connection):
    """SQLの実行時間をrequestの内訳へ積むsqlite3接続。

    ``sqlite3.connect(..., factory=TimedConnection)`` で作り、``perf_phase`` に内訳名を
    入れて使う。呼び出し側を1つも書き換えずにDB時間が取れるのが要点で、storageの
    ``execute`` は6000行に散っている。

    requestの外(collectorのevent書き出し・録画・起動時のmigration)では ``_current`` の
    読み取り1回だけで素の実装へ抜ける。context managerを毎回組むと、``SELECT 1`` 級の
    軽い文で1.3μs増える — 取り込みは1日数十万文を通すので、そこは通さない。"""

    perf_phase = "db"

    def execute(self, sql, parameters=(), /):
        if _current.get() is None:
            return super().execute(sql, parameters)
        with phase(self.perf_phase):
            return super().execute(sql, parameters)

    def executemany(self, sql, parameters, /):
        if _current.get() is None:
            return super().executemany(sql, parameters)
        with phase(self.perf_phase):
            return super().executemany(sql, parameters)

    def executescript(self, sql_script, /):
        if _current.get() is None:
            return super().executescript(sql_script)
        with phase(self.perf_phase):
            return super().executescript(sql_script)

    def commit(self):
        if _current.get() is None:
            return super().commit()
        with phase(f"{self.perf_phase}.commit"):
            return super().commit()


class TimedLock:
    """待ち時間を内訳へ積む ``threading.Lock`` の代役。

    DBが遅いのか、DBを触る順番待ちで止まっているのかは、合計時間を見ても区別できない。
    storageの書き込み接続は単一lockで直列化されているので、待ちを別名で積んで分ける。
    ``with`` 以外の使い方(acquire/release直接呼び)も素のLockと同じに保つ。"""

    __slots__ = ("_lock", "_wait_phase")

    def __init__(self, wait_phase: str) -> None:
        self._lock = threading.Lock()
        self._wait_phase = wait_phase

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        if _current.get() is None:
            return self._lock.acquire(blocking, timeout)
        with phase(self._wait_phase):
            return self._lock.acquire(blocking, timeout)

    def release(self) -> None:
        self._lock.release()

    def locked(self) -> bool:
        return self._lock.locked()

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self._lock.release()


def env_summary() -> dict:
    """設定の実効値。画面が「なぜ数字が出ないのか」を自力で答えられるようにする。"""
    return {
        "enabled": get_perf_enabled(),
        "sample_window": get_perf_sample_window(),
        "rollup_seconds": get_perf_rollup_seconds(),
        "rollup_top": get_perf_rollup_top(),
        "max_routes": get_perf_max_routes(),
        "loop_lag_interval_seconds": get_perf_loop_lag_interval_seconds(),
        "loop_lag_warn_ms": get_perf_loop_lag_warn_ms(),
        "pid": os.getpid(),
    }
