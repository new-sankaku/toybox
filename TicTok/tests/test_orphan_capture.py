"""前回の実行が残した捕捉ffmpegの回収(tictok.core.orphan_capture)。

固定するのは2点。**孤児は必ず止まること**と、**身元が確かめられない相手には触れないこと**。
後者を落とすと、pidの再利用で無関係なprocessをkillする経路になる。
"""
import json
import os
import subprocess
import sys
import time

import pytest

from tictok.core import layout, orphan_capture


@pytest.fixture
def root(tmp_path):
    (tmp_path / "tester" / layout.TS_DIRNAME / "00001_tester_20260101_120000").mkdir(parents=True)
    return tmp_path


def _session(root):
    return root / "tester" / layout.TS_DIRNAME / "00001_tester_20260101_120000"


def _sleeper():
    """止められる相手として、何もしない子processを1つ起こす。"""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])


def _wait_gone(proc, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(0.05)
    return False


def test_process_identity_distinguishes_a_live_pid_from_a_dead_one():
    assert orphan_capture.process_identity(os.getpid())
    assert orphan_capture.process_identity(0) is None


def test_sweep_kills_the_leftover_capture_and_clears_the_mark(root):
    proc = _sleeper()
    try:
        orphan_capture.mark(_session(root), proc.pid)
        assert (_session(root) / orphan_capture.CAPTURE_MARK_NAME).is_file()
        assert orphan_capture.sweep([root]) == {"found": 1, "killed": 1, "mismatched": 0}
        assert _wait_gone(proc), "孤児が止まっていない"
        assert not (_session(root) / orphan_capture.CAPTURE_MARK_NAME).exists()
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()


def test_sweep_never_kills_a_pid_whose_identity_does_not_match(root):
    """pidは再利用される。記録した作成時刻と食い違う相手は、生きていても触ってはいけない。"""
    proc = _sleeper()
    try:
        path = _session(root) / orphan_capture.CAPTURE_MARK_NAME
        path.write_text(json.dumps({"pid": proc.pid, "identity": "别のprocessの作成時刻"}),
                        encoding="utf-8")
        assert orphan_capture.sweep([root]) == {"found": 1, "killed": 0, "mismatched": 1}
        assert proc.poll() is None, "身元違いのprocessを殺してはいけない"
        # 判断を毎起動で繰り返さないよう、目印は消す。
        assert not path.exists()
    finally:
        proc.kill()
        proc.wait()


def test_sweep_never_kills_a_pid_recorded_without_an_identity(root):
    """作成時刻を取れない環境で書かれた目印。身元が無い相手はkillの対象にしない。"""
    proc = _sleeper()
    try:
        (_session(root) / orphan_capture.CAPTURE_MARK_NAME).write_text(
            json.dumps({"pid": proc.pid, "identity": None}), encoding="utf-8")
        assert orphan_capture.sweep([root]) == {"found": 1, "killed": 0, "mismatched": 1}
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait()


def test_sweep_drops_the_mark_of_a_process_that_already_exited(root):
    proc = _sleeper()
    orphan_capture.mark(_session(root), proc.pid)
    proc.kill()
    proc.wait()
    assert orphan_capture.sweep([root]) == {"found": 1, "killed": 0, "mismatched": 0}
    assert not (_session(root) / orphan_capture.CAPTURE_MARK_NAME).exists()


def test_sweep_ignores_an_unreadable_mark(root):
    (_session(root) / orphan_capture.CAPTURE_MARK_NAME).write_text("oops", encoding="utf-8")
    assert orphan_capture.sweep([root]) == {"found": 1, "killed": 0, "mismatched": 0}


def test_sweep_is_a_noop_without_marks(root):
    assert orphan_capture.sweep([root]) == {"found": 0, "killed": 0, "mismatched": 0}


def test_clear_is_safe_when_the_mark_is_already_gone(root):
    orphan_capture.clear(_session(root))
    orphan_capture.clear(_session(root))


def test_mark_does_not_collide_with_the_material_globs(root):
    """目印は録画実体のglobにもcapture indexにも当たらない名前でなければならない。"""
    orphan_capture.mark(_session(root), os.getpid())
    assert layout.media_files(_session(root)) == []
    assert not layout.has_media(_session(root))
    assert orphan_capture.CAPTURE_MARK_NAME != layout.PLAYLIST_NAME
