"""配信の終わりを合図にした退避(``api.startup._backup_tick``)。

ここで確かめるのは**発火の条件**だけで、退避そのものの中身(snapshotの取り方・差分copy・
設定値のJSON)は各moduleのtestが持つ。この層の失敗は「走るべきときに走らない」か「走るべき
でないときに走る」のどちらかで、どちらも実害が出るまで気付けない ―― 前者は控えが増えない
ことでしか、後者は録画中にdiskが取られることでしか現れない。

3つの退避を独立に失敗させることも、ここでしか確かめられない。まとめてtryで包んでしまうと
最初の失敗が残り2つを黙って飛ばすが、その症状は「DBの退避が失敗した日だけ設定値も写らない」
という、原因と離れた形で出る。

印は退避ごとに別で、失敗した退避だけがbackoffで再試行される。印が1つだった頃は、file backupの
先が外れている間、周期ごとにDBのsnapshot(1.65GB・K:で約40秒)を取り直していた。
"""
import asyncio
import time

import pytest


def rec(ended_at, *, stem="00001_alice_20260101_120000", status="completed", rid=1):
    """録画1本ぶんの行。``ended_at`` が None なら「まだ録画中」。"""
    return {"id": rid, "unique_id": "alice", "status": status,
            "filename": f"{stem}.mp4", "path": f"/rec/alice/mp4/{stem}.mp4",
            "ended_at": ended_at}


class _Storage:
    """発火の判定に要る分だけを持つ最小のstorage。"""

    def __init__(self, rows):
        self.rows = list(rows)
        self.values: dict = {}
        self.flushed = 0
        self.busy_ids: set = set()
        self.ops: list = []

    def recordings_for_backup(self, since: float) -> list:
        return [r for r in self.rows
                if r["ended_at"] is None or float(r["ended_at"]) > since]

    def pending_media_job_keys(self):
        return {("pack", rid) for rid in self.busy_ids}

    def get_maintenance_value(self, key: str):
        return self.values.get(key)

    def set_maintenance_value(self, key: str, value: str) -> None:
        self.values[key] = value

    def flush(self) -> None:
        self.flushed += 1

    def record_ops_event(self, log, kind, message, **kw) -> str:
        self.ops.append({"kind": kind, "message": message, **kw})
        return "ops"


@pytest.fixture
def startup(env_guard):
    """``env_guard`` を先に効かせてから import する。

    ``tictok.api.runtime`` は **import時に** Storage・instance lock・record dir を掴むので、
    module冒頭でimportすると本番のDBを掴み、serverが動いていればlockで落ちる
    (``tests/test_server.py`` の ``server`` fixtureと同じ理由)。"""
    from tictok.api import startup as module

    return module


@pytest.fixture
def env(startup, monkeypatch):
    """3つの退避を全て偽物へ差し替え、呼ばれた順に記録する。"""
    calls: list = []

    async def _db(ended_at):
        calls.append("db")

    async def _settings():
        calls.append("settings")

    async def _files(exclude):
        calls.append("files")
        calls.append(("exclude", frozenset(exclude)))

    monkeypatch.setattr(startup, "_backup_db_snapshot", _db)
    monkeypatch.setattr(startup, "_backup_settings_export", _settings)
    monkeypatch.setattr(startup, "_backup_primary_files", _files)
    monkeypatch.setattr(startup, "get_db_backup_on_recording_finished", lambda: True)
    monkeypatch.setattr(startup, "get_record_backup_quiet_minutes", lambda: 15.0)
    monkeypatch.setattr(startup, "get_record_backup_min_interval_minutes", lambda: 60.0)
    monkeypatch.setattr(startup.primary_backup, "is_configured", lambda: True)
    monkeypatch.setattr(startup.primary_backup, "last_run", lambda: None)
    startup._reset_backup_state()
    return calls


def kinds(calls):
    """呼ばれた退避の種別だけ(除外集合の記録を除く)。"""
    return [c for c in calls if isinstance(c, str)]


def excluded(calls):
    """file backupへ渡された除外の接頭辞。"""
    for c in calls:
        if isinstance(c, tuple) and c[0] == "exclude":
            return set(c[1])
    return None


def _use_storage(startup, monkeypatch, storage):
    monkeypatch.setattr(startup.runtime, "storage", storage)
    return storage


def mark(startup, store, step):
    """退避 ``step`` の印(どの録画まで済んだか)。無ければ None。"""
    raw = store.values.get(startup._BACKUP_MARK_KEYS[step])
    return float(raw) if raw else None


def marks(startup, store):
    return {step: mark(startup, store, step) for step in startup._BACKUP_MARK_KEYS}


def test_fires_after_the_quiet_window(startup, monkeypatch, env):
    """静穏時間が明けた録画で3つとも走り、印が進むこと。"""
    ended = time.time() - 20 * 60
    store = _use_storage(startup, monkeypatch, _Storage([rec(ended)]))

    asyncio.run(startup._backup_tick())

    assert kinds(env) == ["db", "settings", "files"]
    assert all(v == pytest.approx(ended) for v in marks(startup, store).values())


def test_waits_while_the_recording_is_still_settling(startup, monkeypatch, env):
    """確定の直後は走らない。ts結合・波形・文字起こしが同じfileを触っている最中である。"""
    store = _use_storage(startup, monkeypatch, _Storage([rec(time.time() - 60)]))

    asyncio.run(startup._backup_tick())

    assert kinds(env) == []
    assert not any(marks(startup, store).values())


def test_does_not_repeat_for_the_same_recording(startup, monkeypatch, env):
    """同じ録画で二度走らない。周期は60秒なので、走れば1晩で何十回にもなる。"""
    ended = time.time() - 20 * 60
    _use_storage(startup, monkeypatch, _Storage([rec(ended)]))
    asyncio.run(startup._backup_tick())
    env.clear()

    asyncio.run(startup._backup_tick())

    assert kinds(env) == []


def test_fires_again_for_a_newer_recording(startup, monkeypatch, env):
    """次の録画が終われば また走ること(印は「ここまで済んだ」であって「もう走らない」ではない)。"""
    store = _use_storage(startup, monkeypatch, _Storage([rec(time.time() - 40 * 60)]))
    asyncio.run(startup._backup_tick())
    env.clear()
    store.rows.append(rec(time.time() - 20 * 60, stem="00002_alice_20260101_140000", rid=2))

    asyncio.run(startup._backup_tick())

    assert kinds(env) == ["db", "settings", "files"]


def test_no_recordings_does_nothing(startup, monkeypatch, env):
    """1本も確定していないDB(新規install)で走らない。"""
    _use_storage(startup, monkeypatch, _Storage([]))

    asyncio.run(startup._backup_tick())

    assert kinds(env) == []


def test_db_backup_failure_does_not_block_the_others(startup, monkeypatch, env):
    """DBの退避が落ちても設定値とfileは走る。まとめてtryで包むとここが落ちる。"""
    async def _boom(ended_at):
        raise OSError("退避先が見えません")

    monkeypatch.setattr(startup, "_backup_db_snapshot", _boom)
    _use_storage(startup, monkeypatch, _Storage([rec(time.time() - 20 * 60)]))

    asyncio.run(startup._backup_tick())

    assert kinds(env) == ["settings", "files"]


def test_a_failure_leaves_only_that_mark_unset(startup, monkeypatch, env):
    """落ちた退避の印だけが進まない。他の2つは済んでいるので、次の周期で取り直さない。

    印が1つだった頃は、設定値の書き出しが落ちた周期にDBのsnapshot(1.65GB)まで取り直して
    いた。"""
    async def _boom():
        raise OSError("書けません")

    monkeypatch.setattr(startup, "_backup_settings_export", _boom)
    ended = time.time() - 20 * 60
    store = _use_storage(startup, monkeypatch, _Storage([rec(ended)]))

    asyncio.run(startup._backup_tick())

    got = marks(startup, store)
    assert got["db"] == pytest.approx(ended)
    assert got["files"] == pytest.approx(ended)
    assert got["settings"] is None

    # 直って次の周期(backoffの1回目は次の周期)。落ちた退避だけをもう一度試し、印が進む。
    async def _settings():
        env.append("settings")

    monkeypatch.setattr(startup, "_backup_settings_export", _settings)
    env.clear()
    startup._backup_retry["settings"]["until"] = time.monotonic() - 1
    asyncio.run(startup._backup_tick())

    assert kinds(env) == ["settings"]
    assert mark(startup, store, "settings") == pytest.approx(ended)


def test_a_failure_is_recorded_as_an_ops_event(startup, monkeypatch, env):
    """自動の退避の失敗はops_eventsへ残る(=通知の対象になる)。textのlogだけでは、
    退避先が外れたまま何週間も失敗し続けていることに誰も気付かない。"""
    async def _boom(ended_at):
        raise OSError("退避先が見えません")

    monkeypatch.setattr(startup, "_backup_db_snapshot", _boom)
    store = _use_storage(startup, monkeypatch, _Storage([rec(time.time() - 20 * 60)]))

    asyncio.run(startup._backup_tick())

    failed = [o for o in store.ops if o["kind"] == "maintenance.backup_failed"]
    assert len(failed) == 1
    assert failed[0]["severity"] == "error"
    assert "退避先が見えません" in failed[0]["message"]
    assert failed[0]["detail"]["failures"] == 1


def test_repeated_failures_back_off(startup, monkeypatch, env):
    """失敗が続く退避は間隔を倍にして再試行し、上限で頭打ちになる。

    退避先のdriveが外れたまま60秒ごとにsnapshot(1.65GB・K:で約40秒)を取り直すと、1日で
    1.4TBをSMR driveへ書いて消すことになる。"""
    attempts = 0

    async def _boom(ended_at):
        nonlocal attempts
        attempts += 1
        raise OSError("退避先が見えません")

    monkeypatch.setattr(startup, "_backup_db_snapshot", _boom)
    _use_storage(startup, monkeypatch, _Storage([rec(time.time() - 20 * 60)]))

    asyncio.run(startup._backup_tick())
    assert attempts == 1
    # 次の周期(60秒後)はまだ待つ。
    asyncio.run(startup._backup_tick())
    assert attempts == 1
    assert startup._backup_retry["db"]["failures"] == 1
    assert startup._backup_retry_delay(1) == startup.BACKUP_TICK_SECONDS

    for n in range(2, 12):
        startup._backup_retry["db"]["until"] = time.monotonic() - 1
        asyncio.run(startup._backup_tick())
        assert attempts == n
    assert startup._backup_retry_delay(11) == startup.BACKUP_RETRY_MAX_SECONDS
    assert startup._backup_retry["db"]["failures"] == 11


def test_success_clears_the_backoff(startup, monkeypatch, env):
    calls = {"n": 0}

    async def _flaky(ended_at):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("一度だけ落ちる")

    monkeypatch.setattr(startup, "_backup_db_snapshot", _flaky)
    _use_storage(startup, monkeypatch, _Storage([rec(time.time() - 20 * 60)]))

    asyncio.run(startup._backup_tick())
    startup._backup_retry["db"]["until"] = time.monotonic() - 1
    asyncio.run(startup._backup_tick())

    assert "db" not in startup._backup_retry


def test_db_snapshot_can_be_turned_off_alone(startup, monkeypatch, env):
    """DBの退避だけを止めても、設定値とfileのbackupは続くこと。"""
    monkeypatch.setattr(startup, "get_db_backup_on_recording_finished", lambda: False)
    _use_storage(startup, monkeypatch, _Storage([rec(time.time() - 20 * 60)]))

    asyncio.run(startup._backup_tick())

    assert kinds(env) == ["settings", "files"]


def test_unconfigured_primary_backup_is_skipped_without_failing(startup, monkeypatch, env):
    """backup先が未設定なら file の写しだけ飛ばす。設定値の退避は保存先が別なので走る。"""
    monkeypatch.setattr(startup.primary_backup, "is_configured", lambda: False)
    store = _use_storage(startup, monkeypatch, _Storage([rec(time.time() - 20 * 60)]))

    asyncio.run(startup._backup_tick())

    assert kinds(env) == ["db", "settings"]
    # 未設定の退避は数えない。数えるとその印が永久に進まず、毎周期「未退避の録画」が在る
    # ことになる。
    got = marks(startup, store)
    assert got["db"] and got["settings"] and got["files"] is None
    env.clear()
    asyncio.run(startup._backup_tick())
    assert kinds(env) == []


def test_min_interval_skips_only_the_file_backup(startup, monkeypatch, env):
    """下限間隔の中なら file の写しだけ見送る。DBの退避と設定値は別の頻度で回す。"""
    monkeypatch.setattr(startup.primary_backup, "last_run",
                        lambda: {"started_at": time.time() - 5 * 60})
    store = _use_storage(startup, monkeypatch, _Storage([rec(time.time() - 20 * 60)]))

    asyncio.run(startup._backup_tick())

    assert kinds(env) == ["db", "settings"]
    # 見送りは失敗ではないが済んでもいない。fileの印だけ進めず、間隔が明けた最初の周期で
    # 写す。DBと設定値の印は進んでいるので、そのあいだ取り直されることはない。
    got = marks(startup, store)
    assert got["db"] and got["settings"] and got["files"] is None
    env.clear()
    asyncio.run(startup._backup_tick())
    assert kinds(env) == []
    monkeypatch.setattr(startup.primary_backup, "last_run",
                        lambda: {"started_at": time.time() - 120 * 60})
    asyncio.run(startup._backup_tick())
    assert kinds(env) == ["files"]
    assert got["db"] == mark(startup, store, "files")


def test_min_interval_elapsed_runs_the_file_backup(startup, monkeypatch, env):
    monkeypatch.setattr(startup.primary_backup, "last_run",
                        lambda: {"started_at": time.time() - 120 * 60})
    _use_storage(startup, monkeypatch, _Storage([rec(time.time() - 20 * 60)]))

    asyncio.run(startup._backup_tick())

    assert kinds(env) == ["db", "settings", "files"]


# ---- 複数配信者の同時監視 ----
# 「配信が終わった」を全体の状態として扱うと、監視数が増えるほど壊れる。実測(2026-09-02、
# 確定録画529本)では終了の29.5%が他の録画の進行中で、全体gateの形では走った回の65.4%が
# 書き込み中の.tsを写しに行っていた。ここはその形へ戻らないための留め金である。


def test_runs_while_another_stream_is_still_recording(startup, monkeypatch, env):
    """他の録画が進行中でも、落ち着いた録画は退避する（待たない）。

    待つ形にすると、監視数が増えて静穏窓が消えたときに退避が永久に止まる。"""
    done = rec(time.time() - 20 * 60, stem="00001_alice_20260101_120000", rid=1)
    live = rec(None, stem="00002_bob_20260101_130000", status="recording", rid=2)
    _use_storage(startup, monkeypatch, _Storage([done, live]))

    asyncio.run(startup._backup_tick())

    assert kinds(env) == ["db", "settings", "files"]


def test_a_recording_in_progress_is_excluded_from_the_copy(startup, monkeypatch, env):
    """進行中の録画は写す対象から外れること。書き込み中の.tsを写すと途中の姿が残る。"""
    done = rec(time.time() - 20 * 60, stem="00001_alice_20260101_120000", rid=1)
    live = rec(None, stem="00002_bob_20260101_130000", status="recording", rid=2)
    _use_storage(startup, monkeypatch, _Storage([done, live]))

    asyncio.run(startup._backup_tick())

    ex = excluded(env)
    assert "bob/ts/00002_bob_20260101_130000" in ex
    assert "bob/mp4/00002_bob_20260101_130000" in ex
    assert ".sidecars/00002_bob_20260101_130000" in ex
    # 落ち着いた録画は外れない。外れると控えが永久に増えない。
    assert not any("00001_alice" in rel for rel in ex)


def test_a_recording_still_settling_is_excluded_but_does_not_block(startup, monkeypatch, env):
    """静穏時間の明けていない録画は除外されるだけで、他の録画の退避は止めない。

    静穏時間を**全体のgate**にしていた頃は、終わったばかりの録画が1本あるだけで
    すべての退避が止まっていた。監視数が増えるほどその状態が続く。"""
    old = rec(time.time() - 60 * 60, stem="00001_alice_20260101_120000", rid=1)
    fresh = rec(time.time() - 60, stem="00002_bob_20260101_130000", rid=2)
    _use_storage(startup, monkeypatch, _Storage([old, fresh]))

    asyncio.run(startup._backup_tick())

    assert kinds(env) == ["db", "settings", "files"]
    assert "bob/ts/00002_bob_20260101_130000" in excluded(env)


def test_a_recording_with_pending_media_jobs_is_excluded(startup, monkeypatch, env):
    """ts結合・波形・サムネが控えている録画は写さない。移送(relocate)と同じ条件である。"""
    a = rec(time.time() - 60 * 60, stem="00001_alice_20260101_120000", rid=1)
    b = rec(time.time() - 50 * 60, stem="00002_bob_20260101_130000", rid=2)
    store = _use_storage(startup, monkeypatch, _Storage([a, b]))
    store.busy_ids = {2}

    asyncio.run(startup._backup_tick())

    assert "bob/ts/00002_bob_20260101_130000" in excluded(env)
    assert not any("00001_alice" in rel for rel in excluded(env))


def test_only_unsettled_recordings_do_not_trigger_a_run(startup, monkeypatch, env):
    """動いている録画しか無ければ走らない。数えると録画中は毎周期走り続ける。"""
    live = rec(None, stem="00002_bob_20260101_130000", status="recording", rid=2)
    fresh = rec(time.time() - 60, stem="00003_carol_20260101_140000", rid=3)
    _use_storage(startup, monkeypatch, _Storage([live, fresh]))

    asyncio.run(startup._backup_tick())

    assert kinds(env) == []


def test_the_mark_only_advances_past_settled_recordings(startup, monkeypatch, env):
    """印は落ち着いた録画までしか進まない。進めると、まだ写していない録画が飛ばされる。"""
    settled = rec(time.time() - 60 * 60, stem="00001_alice_20260101_120000", rid=1)
    fresh = rec(time.time() - 60, stem="00002_bob_20260101_130000", rid=2)
    store = _use_storage(startup, monkeypatch, _Storage([settled, fresh]))

    asyncio.run(startup._backup_tick())

    assert all(v == pytest.approx(float(settled["ended_at"]))
               for v in marks(startup, store).values())
    # 静穏時間が明ければ、飛ばさずに拾う。
    env.clear()
    store.rows[1] = rec(time.time() - 20 * 60, stem="00002_bob_20260101_130000", rid=2)
    asyncio.run(startup._backup_tick())
    assert kinds(env) == ["db", "settings", "files"]
# ---- 画面へ返す状態(``backup_schedule_status``) ----
# 状況画面は退避の判定を1つも持たない。持たせると、周期や猶予を直したときに画面だけが古い
# 答えを出し続ける。したがって確かめるのは「``_backup_tick`` と同じ材料が同じ形で出るか」で、
# とりわけ **走らないのが正しい状態を異常として出さないこと** である。


def status(startup):
    return asyncio.run(startup.backup_schedule_status())


def test_status_reports_nothing_pending_when_caught_up(startup, monkeypatch, env):
    """退避が済んだ直後は、どの経路にも控えが無い。"""
    ended = time.time() - 20 * 60
    _use_storage(startup, monkeypatch, _Storage([rec(ended)]))
    asyncio.run(startup._backup_tick())

    state = status(startup)

    assert [step["pending"] for step in state["steps"].values()] == [0, 0, 0]
    assert all(step["enabled"] for step in state["steps"].values())
    assert not any(step["overdue"] for step in state["steps"].values())


def test_status_counts_settled_recordings_not_yet_copied(startup, monkeypatch, env):
    """まだ写していない録画は経路ごとに数える。"""
    _use_storage(startup, monkeypatch, _Storage([rec(time.time() - 20 * 60)]))

    state = status(startup)

    assert [step["pending"] for step in state["steps"].values()] == [1, 1, 1]
    assert state["holding"] == 0


def test_status_does_not_count_recordings_still_running(startup, monkeypatch, env):
    """録画中は控えではない。数えると、録画が1本走っている間ずっと遅れて見える。"""
    live = rec(None, stem="00002_bob_20260101_130000", status="recording", rid=2)
    _use_storage(startup, monkeypatch, _Storage([live]))

    state = status(startup)

    assert [step["pending"] for step in state["steps"].values()] == [0, 0, 0]
    assert state["holding"] == 1


def test_status_gives_file_backup_the_minimum_interval_as_slack(startup, monkeypatch, env):
    """遅れの物差しは退避ごとに違う。file backupは下限間隔ぶん待つのが正常な姿で、他と
    同じ猶予を当てると、正常な待機が毎周期その1本だけを遅れとして見せる。"""
    _use_storage(startup, monkeypatch, _Storage([rec(time.time() - 45 * 60)]))

    steps = status(startup)["steps"]

    assert steps[startup.BACKUP_STEP_DB]["overdue"] is True
    assert steps[startup.BACKUP_STEP_SETTINGS]["overdue"] is True
    assert steps[startup.BACKUP_STEP_FILES]["overdue"] is False


def test_status_never_calls_a_disabled_backup_late(startup, monkeypatch, env):
    """止めてある退避は印が進まないので控えはいくらでも溜まる。それを遅れと呼ぶと、
    設定どおりの状態が障害として並ぶ。"""
    monkeypatch.setattr(startup, "get_db_backup_on_recording_finished", lambda: False)
    _use_storage(startup, monkeypatch, _Storage([rec(time.time() - 10 * 3600)]))

    step = status(startup)["steps"][startup.BACKUP_STEP_DB]

    assert step["enabled"] is False
    assert step["overdue"] is False


def test_status_reports_the_backoff_of_a_failed_backup(startup, monkeypatch, env):
    """失敗した退避は、失敗の回数と次に試すまでの時間で名乗る。「止まっている」だけでは、
    直りかけているのか諦めているのかが画面から読めない。"""
    async def _boom(ended_at):
        raise OSError("退避先が見つかりません")

    monkeypatch.setattr(startup, "_backup_db_snapshot", _boom)
    _use_storage(startup, monkeypatch, _Storage([rec(time.time() - 20 * 60)]))
    asyncio.run(startup._backup_tick())

    step = status(startup)["steps"][startup.BACKUP_STEP_DB]

    assert step["failures"] == 1
    assert 0 < step["retry_in_seconds"] <= startup.BACKUP_TICK_SECONDS
    # 失敗した退避だけが止まる。残り2つは印が進んでいる。
    assert status(startup)["steps"][startup.BACKUP_STEP_SETTINGS]["pending"] == 0
