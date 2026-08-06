import asyncio
import sqlite3
import threading
import time

import pytest

from tictok.core import perf


@pytest.fixture(autouse=True)
def clean_registry():
    perf.reset()
    yield
    perf.reset()


# ---------------- 内訳の積み方 ----------------


def test_phase_outside_request_is_a_no_op():
    # collectorや録画pipelineも同じhelperを通る。request contextの外では何も積まない。
    with perf.phase("db.read"):
        pass
    assert perf.current() is None


def test_phase_accumulates_count_and_duration():
    with perf.request("/api/x", "GET") as measured:
        with perf.phase("db.read"):
            time.sleep(0.01)
        with perf.phase("db.read"):
            time.sleep(0.01)
        phases = measured.phases()
    assert phases["db.read"][0] == 2
    assert phases["db.read"][1] >= 15.0


def test_nested_phase_records_self_time_only():
    # 集計stageの中でDB readが走る形。素の経過を積むと同じ時間を二重に数える。
    with perf.request("/api/x", "GET") as measured:
        with perf.phase("analytics.reduce"):
            time.sleep(0.02)
            with perf.phase("db.read"):
                time.sleep(0.03)
        phases = measured.phases()
    assert 15.0 <= phases["analytics.reduce"][1] <= 45.0
    assert phases["db.read"][1] >= 25.0


def test_breakdown_has_other_and_never_exceeds_elapsed():
    with perf.request("/api/x", "GET") as measured:
        with perf.phase("fs.scan"):
            time.sleep(0.01)
        time.sleep(0.01)
        breakdown = measured.breakdown()
        elapsed = measured.elapsed_ms()
    assert breakdown["other"] > 0
    assert sum(breakdown.values()) <= elapsed + 1.0


def test_breakdown_other_is_never_negative():
    # 1 requestが複数threadを同時に出すと計測の合計が経過を超え得る。負の"other"は
    # 「余った時間がある」と読めてしまうので0で止める。
    with perf.request("/api/x", "GET") as measured:
        threads = [threading.Thread(target=_sleep_phase, args=(measured, 0.03))
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        breakdown = measured.breakdown()
    assert breakdown["other"] == 0.0


def _sleep_phase(measured, seconds: float) -> None:
    token = perf._current.set(measured)
    try:
        with perf.phase("fs.scan"):
            time.sleep(seconds)
    finally:
        perf._current.reset(token)


def test_phase_survives_an_exception_in_the_block():
    with perf.request("/api/x", "GET") as measured:
        with pytest.raises(ValueError):
            with perf.phase("db.read"):
                raise ValueError("boom")
        # stackが崩れていれば、次の区間の自分の時間が壊れる。
        with perf.phase("fs.scan"):
            time.sleep(0.01)
        phases = measured.phases()
    assert phases["db.read"][0] == 1
    assert phases["fs.scan"][1] >= 8.0


def test_phases_from_a_worker_thread_land_on_the_request():
    # asyncio.to_thread はcontextをcopyするが、copyが指す入れ物は同一object。
    async def main():
        with perf.request("/api/x", "GET") as measured:
            await asyncio.to_thread(_work)
            return measured.phases()

    phases = asyncio.run(main())
    assert phases["fs.scan"][0] == 1


def _work() -> None:
    with perf.phase("fs.scan"):
        time.sleep(0.005)


def test_timer_records_without_touching_the_nesting_stack():
    with perf.request("/api/x", "GET") as measured:
        with perf.timer("proc.ffprobe"):
            time.sleep(0.01)
        phases = measured.phases()
    assert phases["proc.ffprobe"][0] == 1
    assert phases["proc.ffprobe"][1] >= 8.0


def test_request_is_disabled_by_config(monkeypatch):
    monkeypatch.setenv("TICTOK_PERF_ENABLED", "0")
    with perf.request("/api/x", "GET") as measured:
        assert measured is None
        with perf.phase("db.read"):
            pass
        assert perf.current() is None


# ---------------- route別の集計 ----------------


def test_observe_accumulates_per_route():
    perf.observe("list_sessions", 10.0, phases={"db.read": [1, 4.0]})
    perf.observe("list_sessions", 30.0, phases={"db.read": [2, 6.0]})
    row = _route(perf.snapshot(), "list_sessions")
    assert row["count"] == 2
    assert row["total_ms"] == 40.0
    assert row["avg_ms"] == 20.0
    assert row["max_ms"] == 30.0
    assert row["phases"]["db.read"] == {"count": 3, "ms": 10.0, "avg_ms": 3.33}


def test_snapshot_sorts_by_total_time_not_by_average():
    # 1回3秒でも日に1回のrouteより、40msでも毎秒叩かれるrouteの方がserverを占有する。
    perf.observe("rare_but_slow", 3000.0)
    for _ in range(200):
        perf.observe("fast_but_hot", 40.0)
    routes = [row["route"] for row in perf.snapshot()["routes"]]
    assert routes[0] == "fast_but_hot"


def test_percentiles_come_from_real_samples():
    for value in range(1, 101):
        perf.observe("r", float(value))
    row = _route(perf.snapshot(), "r")
    assert row["p50_ms"] == 50.0
    assert row["p95_ms"] == 95.0
    assert row["p99_ms"] == 99.0
    assert row["max_ms"] == 100.0


def test_sample_window_bounds_memory_but_keeps_totals(monkeypatch):
    monkeypatch.setenv("TICTOK_PERF_SAMPLE_WINDOW", "10")
    perf.reset()
    for _ in range(50):
        perf.observe("r", 5.0)
    row = _route(perf.snapshot(), "r")
    assert row["samples"] == 10
    assert row["count"] == 50
    assert row["total_ms"] == 250.0


def test_failed_requests_are_counted_separately():
    perf.observe("r", 5.0)
    perf.observe("r", 5.0, failed=True)
    row = _route(perf.snapshot(), "r")
    assert (row["count"], row["failed"]) == (2, 1)


def test_route_cap_folds_the_overflow_into_one_key(monkeypatch):
    monkeypatch.setenv("TICTOK_PERF_MAX_ROUTES", "3")
    perf.reset()
    for i in range(10):
        perf.observe(f"r{i}", 1.0)
    snapshot = perf.snapshot()
    # 上限まで個別に持ち、それ以降は受け皿1つへ落ちる(受け皿ぶんで上限+1になる)。
    assert snapshot["route_count"] == 4
    # 件数と合計は失わない: 溢れた7件は受け皿のrouteに残る。
    assert snapshot["request_count"] == 10
    assert _route(snapshot, perf.OVERFLOW_ROUTE)["count"] == 7


def test_reset_clears_routes_and_moves_the_window_start():
    perf.observe("r", 5.0)
    before = perf.snapshot()["since"]
    time.sleep(0.01)
    result = perf.reset()
    assert result["cleared_routes"] == 1
    assert perf.snapshot()["routes"] == []
    assert perf.snapshot()["since"] > before


def test_share_is_the_fraction_of_measured_time():
    perf.observe("a", 75.0)
    perf.observe("b", 25.0)
    assert _route(perf.snapshot(), "a")["share"] == 0.75


def test_snapshot_limit_keeps_the_heaviest_routes():
    perf.observe("a", 100.0)
    perf.observe("b", 10.0)
    perf.observe("c", 1.0)
    rows = perf.snapshot(limit=2)["routes"]
    assert [row["route"] for row in rows] == ["a", "b"]


# ---------------- 定期の集計log ----------------


def test_rollup_logs_once_per_interval_and_resets_its_window(monkeypatch, caplog):
    # 待ちをintervalに近づけないこと。Windowsのtime.monotonicは約15.6msごとにしか
    # 進まないので、60ms待っても46.8msとしか読めない回がある。
    monkeypatch.setenv("TICTOK_PERF_ROLLUP_SECONDS", "0.01")
    perf.reset()
    perf.observe("r", 12.0)
    time.sleep(0.1)
    with caplog.at_level("INFO", logger="tictok.perf"):
        perf.maybe_log_rollup()
        # 同じ窓では2度書かない。
        perf.maybe_log_rollup()
    lines = [rec for rec in caplog.records if getattr(rec, "event", "") == "http.perf_rollup"]
    assert len(lines) == 1
    assert lines[0].ctx["routes"][0]["count"] == 1
    # 窓は畳まれるが、累計は残る。
    assert _route(perf.snapshot(), "r")["count"] == 1


def test_rollup_is_silent_without_traffic(monkeypatch, caplog):
    monkeypatch.setenv("TICTOK_PERF_ROLLUP_SECONDS", "0.01")
    perf.reset()
    time.sleep(0.1)
    with caplog.at_level("INFO", logger="tictok.perf"):
        perf.maybe_log_rollup()
    assert [rec for rec in caplog.records if getattr(rec, "event", "") == "http.perf_rollup"] == []


def test_rollup_disabled_by_zero(monkeypatch, caplog):
    monkeypatch.setenv("TICTOK_PERF_ROLLUP_SECONDS", "0")
    perf.observe("r", 12.0)
    with caplog.at_level("INFO", logger="tictok.perf"):
        perf.maybe_log_rollup()
    assert [rec for rec in caplog.records if getattr(rec, "event", "") == "http.perf_rollup"] == []


# ---------------- 進行中requestとloopの遅れ ----------------


def test_inflight_lists_running_requests_slowest_first():
    with perf.request("/api/slow", "GET"):
        time.sleep(0.02)
        inner = perf.RequestPerf("/api/fast", "GET")
        perf._inflight_add(inner)
        try:
            rows = perf.inflight_snapshot()
        finally:
            perf._inflight_remove(inner)
    assert [row["path"] for row in rows] == ["/api/slow", "/api/fast"]
    assert perf.inflight_snapshot() == []


def test_loop_lag_below_threshold_is_recorded_but_not_logged(monkeypatch, caplog):
    monkeypatch.setenv("TICTOK_PERF_LOOP_LAG_WARN_MS", "500")
    with caplog.at_level("WARNING", logger="tictok.perf"):
        perf.note_loop_lag(120.0)
    assert perf.loop_lag_snapshot()["max_ms"] == 120.0
    assert perf.loop_lag_snapshot()["warned"] == 0
    assert caplog.records == []


def test_loop_lag_above_threshold_names_the_requests_in_flight(monkeypatch, caplog):
    monkeypatch.setenv("TICTOK_PERF_LOOP_LAG_WARN_MS", "100")
    with caplog.at_level("WARNING", logger="tictok.perf"):
        with perf.request("/api/heavy", "GET"):
            perf.note_loop_lag(900.0)
    records = [rec for rec in caplog.records if getattr(rec, "event", "") == "http.loop_lag"]
    assert len(records) == 1
    assert records[0].ctx["inflight"][0]["path"] == "/api/heavy"
    assert perf.loop_lag_snapshot()["warned"] == 1


def test_loop_lag_monitor_measures_its_own_oversleep(monkeypatch):
    monkeypatch.setenv("TICTOK_PERF_LOOP_LAG_INTERVAL_SECONDS", "0.05")
    monkeypatch.setenv("TICTOK_PERF_LOOP_LAG_WARN_MS", "1000000")

    async def main():
        task = asyncio.create_task(perf.loop_lag_monitor())
        # probeが自分のsleepへ入るまで一度loopへ返す(create_taskはまだ走らせない)。
        await asyncio.sleep(0.01)
        # loopを握って返さないcoroutineが1本居る状態を作る。
        time.sleep(0.2)
        await asyncio.sleep(0.12)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(main())
    assert perf.loop_lag_snapshot()["max_ms"] >= 100.0


# ---------------- 計測付きのSQLite接続とlock ----------------


def test_timed_connection_attributes_sql_time_to_the_request(tmp_path):
    path = tmp_path / "t.db"
    conn = sqlite3.connect(path, factory=perf.TimedConnection)
    conn.perf_phase = "db.read"
    try:
        conn.execute("CREATE TABLE t (a INTEGER)")
        with perf.request("/api/x", "GET") as measured:
            conn.execute("INSERT INTO t VALUES (1)")
            conn.executemany("INSERT INTO t VALUES (?)", [(2,), (3,)])
            conn.commit()
            phases = measured.phases()
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 3
    finally:
        conn.close()
    assert phases["db.read"][0] == 2
    assert phases["db.read.commit"][0] == 1


def test_timed_lock_records_only_the_waiting(monkeypatch):
    lock = perf.TimedLock("db.write_wait")
    holder_released = threading.Event()

    def hold():
        with lock:
            holder_released.wait(1.0)

    thread = threading.Thread(target=hold)
    thread.start()
    time.sleep(0.02)
    with perf.request("/api/x", "GET") as measured:
        started = threading.Thread(target=holder_released.set)
        started.start()
        with lock:
            time.sleep(0.05)
        phases = measured.phases()
    started.join()
    thread.join()
    # 待ちだけが積まれる。lockを持っている間の作業は自分の区間で測る。
    assert phases["db.write_wait"][0] == 1
    assert phases["db.write_wait"][1] < 40.0


def test_timed_lock_behaves_like_a_plain_lock():
    lock = perf.TimedLock("x")
    assert lock.acquire() is True
    assert lock.locked() is True
    lock.release()
    assert lock.locked() is False


# ---------------- serverへの組み込み ----------------


@pytest.fixture
def perf_server(env_guard):
    import tictok.server as srv

    return srv


@pytest.fixture
def perf_client(perf_server):
    from fastapi.testclient import TestClient

    return TestClient(perf_server.app)


def test_request_is_recorded_under_the_endpoint_name(perf_client):
    perf.reset()
    assert perf_client.get("/api/sessions").status_code == 200
    row = _route(perf.snapshot(), "list_sessions")
    assert row["count"] == 1
    # pathではなくendpoint名がkey。録画idを含むpathをkeyにすると1件1keyになる。
    assert all(not r["route"].startswith("/") for r in perf.snapshot()["routes"])


def test_db_time_is_attributed_to_the_request(perf_client):
    perf.reset()
    perf_client.get("/api/sessions")
    row = _route(perf.snapshot(), "list_sessions")
    # 書き込み接続を使う読み取りは db.write_conn、順番待ちは db.write_wait に分かれる。
    assert row["phases"]["db.write_conn"]["count"] >= 1
    assert row["phases"]["db.write_wait"]["count"] >= 1


def test_read_connection_time_is_reported_separately(perf_client):
    # 重い集計は読み取り専用接続へ逃がしてある(書き込みを止めないため)。内訳もそこで分かれる。
    perf.reset()
    perf_client.get("/api/dashboard")
    row = _route(perf.snapshot(), "aggregate_dashboard")
    assert row["phases"]["db.read"]["count"] >= 1


def test_unmatched_paths_share_one_key(perf_client):
    perf.reset()
    for i in range(5):
        perf_client.get(f"/api/nope-{i}")
    assert _route(perf.snapshot(), perf.UNMATCHED_ROUTE)["count"] == 5


def test_failed_request_is_counted_as_failed(perf_client, monkeypatch, perf_server):
    perf.reset()
    # 4xxはclientへの差し戻しで、serverが結果を失ったわけではない。failedは5xxだけ。
    perf_client.get("/api/sessions/999999")
    assert _route(perf.snapshot(), "session_detail")["failed"] == 0


def test_perf_api_returns_routes_and_config(perf_client):
    perf.reset()
    perf_client.get("/api/sessions")
    payload = perf_client.get("/api/perf").json()
    assert payload["config"]["enabled"] is True
    assert any(row["route"] == "list_sessions" for row in payload["routes"])
    assert "loop_lag" in payload and "inflight" in payload


def test_perf_api_reset_clears_the_registry(perf_client):
    perf_client.get("/api/sessions")
    assert perf_client.request("DELETE", "/api/perf").json()["cleared_routes"] > 0
    # reset自身のrequestだけが残る。
    routes = [row["route"] for row in perf_client.get("/api/perf").json()["routes"]]
    assert "list_sessions" not in routes


def test_websocket_is_not_folded_into_the_route_table(perf_client):
    perf.reset()
    with perf_client.websocket_connect("/ws"):
        pass
    assert perf.snapshot()["routes"] == []


def _route(snapshot: dict, route: str) -> dict:
    for row in snapshot["routes"]:
        if row["route"] == route:
            return row
    raise AssertionError(f"route {route} not in snapshot")
