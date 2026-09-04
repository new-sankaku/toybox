"""core.ffprobe: 全probeが満たすべき2つの約束(timeoutと取り消し)を固定する。

probeはどの経路でもframe loopの**前**に置かれているので、ここで固まったjobは
``cancel.check_cancelled()`` に一度も触れられない。userが取り消しを押してもjobは running の
まま永久に残る。この2つは「あれば良い」ではなく、取り消しがprobeへ届く唯一の道である。
"""

import asyncio
import subprocess
import sys
import types

import pytest

from tictok.core import cancel, ffprobe
from tictok.media import hls_source
from tictok.record import recorder


# --------------------------------------------------------------------------
# timeout
# --------------------------------------------------------------------------


async def test_run_gives_up_instead_of_waiting_forever():
    """終端されていないplaylistを渡したffprobeはlive streamと見なして永久に待つ。
    打ち切らないと、そのjobは取り消しも効かないまま running で残り続ける。"""
    result = await ffprobe.run(
        [sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.3)

    assert result.timed_out
    assert result.returncode is None
    assert not result.ok


def test_run_sync_gives_up_instead_of_waiting_forever():
    result = ffprobe.run_sync(
        [sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.3)

    assert result.timed_out
    assert not result.ok


async def test_a_timeout_is_not_an_exception():
    """呼び出し側は既に「exit codeが0でなければ測れなかった」分岐を持っている。timeoutを
    そこへ合流させないと、経路ごとに例外の握り方が増えて必ずどこかが漏れる。"""
    result = await ffprobe.run(
        [sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.3)

    assert ffprobe.parse_duration(result.stdout) is None


# --------------------------------------------------------------------------
# 取り消し
# --------------------------------------------------------------------------


class _FakeProc:
    """communicateの最中に外から取り消しを掛けられる偽process。"""

    def __init__(self, stdout=b"", on_communicate=None):
        # 走行中は None。``cancel._kill`` はここを見て、もう終わったprocessへkillを
        # 撃たないようにしている。
        self.returncode = None
        self.killed = False
        self._stdout = stdout
        self._on_communicate = on_communicate

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        return self.returncode

    async def communicate(self):
        if self._on_communicate is not None:
            self._on_communicate()
        if self.returncode is None:
            self.returncode = 0
        return self._stdout, b""

    def communicate_sync(self, timeout=None):
        if self._on_communicate is not None:
            self._on_communicate()
        if self.returncode is None:
            self.returncode = 0
        return self._stdout, b""


def _patch_popen(monkeypatch, proc):
    proc.communicate = proc.communicate_sync
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: proc)


# async版 ``run`` は ``run_sync`` をthreadで走らせるだけなので、差し替える先は同じPopen。
_patch_async_exec = _patch_popen


async def test_a_cancel_reaches_a_probe_that_is_already_running(monkeypatch):
    token = cancel.CancelToken("job-1")
    proc = _FakeProc(on_communicate=token.cancel)
    _patch_async_exec(monkeypatch, proc)

    with cancel.token_scope(token):
        await ffprobe.run(["ffprobe", "-v", "error", "x.mp4"])

    assert proc.killed


def test_a_cancel_reaches_a_running_sync_probe(monkeypatch):
    token = cancel.CancelToken("job-1")
    proc = _FakeProc(on_communicate=token.cancel)
    _patch_popen(monkeypatch, proc)

    with cancel.token_scope(token):
        ffprobe.run_sync(["ffprobe", "-v", "error", "x.mp4"])

    assert proc.killed


async def test_a_finished_probe_is_no_longer_a_cancel_target(monkeypatch):
    """登録したまま外さないと、jobの持つlistが1 segmentにつき1つずつ伸びる(3時間の録画で
    5,000本)。取り消し時にはもう終わっているprocessを全部killしに行くことになる。"""
    token = cancel.CancelToken("job-1")
    _patch_async_exec(monkeypatch, _FakeProc(stdout=b"1.5\n"))

    with cancel.token_scope(token):
        for _ in range(3):
            await ffprobe.run(["ffprobe", "-v", "error", "x.mp4"])

    assert token._processes == []


async def test_a_probe_does_not_start_after_the_cancel_fired(monkeypatch):
    launched = []

    def fake_popen(*args, **kwargs):
        launched.append(args)
        return _FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    token = cancel.CancelToken("job-1")
    token.cancel()

    with cancel.token_scope(token):
        with pytest.raises(cancel.JobCancelled):
            await ffprobe.run(["ffprobe", "-v", "error", "x.mp4"])

    assert launched == []


def test_a_sync_probe_does_not_start_after_the_cancel_fired(monkeypatch):
    launched = []

    def fake_popen(*args, **kwargs):
        launched.append(args)
        return _FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    token = cancel.CancelToken("job-1")
    token.cancel()

    with cancel.token_scope(token):
        with pytest.raises(cancel.JobCancelled):
            ffprobe.run_sync(["ffprobe", "-v", "error", "x.mp4"])

    assert launched == []


# --------------------------------------------------------------------------
# 尺
# --------------------------------------------------------------------------


def test_parse_duration_keeps_zero_distinct_from_unreadable():
    """「読めなかった」(probeの失敗)と「0だった」(素材の異常)は呼び出し側で意味が違う。"""
    assert ffprobe.parse_duration("12.5\n") == pytest.approx(12.5)
    assert ffprobe.parse_duration("0\n") == 0.0
    assert ffprobe.parse_duration("N/A\n") is None
    assert ffprobe.parse_duration("") is None


def test_duration_args_asks_for_a_bare_line_on_every_path():
    """形式が経路ごとに割れていると、同じ「尺を取る」処理のparseが人数ぶん増える。"""
    args = ffprobe.duration_args("a.mp4", ("-allowed_extensions", "ALL"))

    assert args[0] == "ffprobe"
    assert args[-1] == "a.mp4"
    assert "-allowed_extensions" in args
    assert args[args.index("-show_entries") + 1] == "format=duration"
    assert args[args.index("-of") + 1] == "default=nokey=1:noprint_wrappers=1"


async def test_duration_seconds_reads_the_bare_line(monkeypatch):
    _patch_async_exec(monkeypatch, _FakeProc(stdout=b"3600.5\n"))

    assert await ffprobe.duration_seconds("a.mp4") == pytest.approx(3600.5)


# --------------------------------------------------------------------------
# 解像度
# --------------------------------------------------------------------------


def test_parse_resolution_csv_reads_the_trailing_separator_ffprobe_emits():
    assert ffprobe.parse_resolution_csv("160,120,\n320,240\n") == [(160, 120), (320, 240)]


def test_parse_resolution_csv_collapses_a_repeated_resolution():
    assert ffprobe.parse_resolution_csv("160,120\n160,120\n320,240\n") == [
        (160, 120), (320, 240)]


def test_parse_resolution_csv_skips_lines_it_cannot_read():
    assert ffprobe.parse_resolution_csv("160\nN/A,N/A\n\n160,120\n") == [(160, 120)]


def test_keyframe_resolution_args_scan_keyframes_not_the_stream_header():
    """``stream=width,height`` は開いた所の1組しか返さず、混在解像度の録画を代表しない。"""
    args = ffprobe.keyframe_resolution_args("a.mp4")

    assert args[args.index("-skip_frame") + 1] == "nokey"
    assert args[args.index("-show_entries") + 1] == "frame=width,height"


async def test_a_resolution_scan_does_not_retry_a_timeout(monkeypatch):
    """走査は途中終了に備えて3回まで再試行する。timeoutをそこへ乗せると、返らない入力に
    対して待ち時間だけが3倍(既定で30分)になる。"""
    calls = []

    async def fake_run(args, **kwargs):
        calls.append(args)
        return ffprobe.ProbeResult(tuple(args), None, "", "")

    monkeypatch.setattr(recorder.ffprobe, "run", fake_run)

    assert await recorder.probe_mp4_resolutions(recorder.Path("a.mp4")) == set()
    assert len(calls) == 1


def test_a_sync_resolution_scan_does_not_retry_a_timeout(monkeypatch):
    calls = []

    def fake_run_sync(args, **kwargs):
        calls.append(args)
        return ffprobe.ProbeResult(tuple(args), None, "", "")

    monkeypatch.setattr(hls_source.ffprobe, "run_sync", fake_run_sync)
    source = types.SimpleNamespace(path=hls_source.Path("a.mp4"), input_args=())

    assert hls_source.resolutions_sync(source) == set()
    assert len(calls) == 1
