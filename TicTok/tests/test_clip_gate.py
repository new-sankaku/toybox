"""short の検品(media/clip_gate)の判定。

測定そのもの(ffprobe / silencedetect / blackdetect)は合成素材で確認済み — 真っ黒・無音の
8秒mp4が silent 100% / black 100% で落ち、正常な6.53秒が合格した。ここで見るのは判定側で、
壊れても「合格」が出てしまう部分である:

  1. 片側trackだけ短い成果物を落とす(container尺は長い側を名乗るので尺だけでは見えない)
  2. 測れなかった項目を合格に化けさせない
  3. 不合格の理由は最初の1件で打ち切らない
  4. 字幕は画素ではなく「焼く材料が在ったか」で見る
"""

import pytest

from tictok.core import config
from tictok.media import clip_gate


def preset(**overrides) -> dict:
    base = {"min_seconds": 15.0, "max_seconds": 60.0, "subtitles": 0}
    base.update(overrides)
    return base


def report(**overrides) -> dict:
    base = {"path": "x.mp4", "bytes": 1000, "video_seconds": 30.0, "audio_seconds": 30.0,
            "video_frames": 900, "seconds": 30.0, "silent_seconds": 2.0,
            "black_seconds": 0.0}
    base.update(overrides)
    return base


def test_a_healthy_clip_passes():
    verdict = clip_gate.evaluate(report(), preset=preset(), expected_seconds=30.0)
    assert verdict == {"ok": True, "failures": []}


def test_one_track_ending_early_is_caught():
    """実測で在る壊れ方: rc=0のまま片側trackだけ3〜4割で終わる。container尺は長い側を
    名乗るので、尺の判定だけでは素通りする。"""
    verdict = clip_gate.evaluate(
        report(video_seconds=12.0, audio_seconds=30.0), preset=preset())
    codes = [f["code"] for f in verdict["failures"]]
    assert clip_gate.FAIL_TRUNCATED in codes
    assert verdict["ok"] is False


def test_missing_audio_track_is_caught():
    verdict = clip_gate.evaluate(
        report(audio_seconds=None, silent_seconds=None), preset=preset())
    assert [f["code"] for f in verdict["failures"]] == [clip_gate.FAIL_NO_AUDIO]


def test_unmeasurable_output_is_not_a_pass():
    verdict = clip_gate.evaluate(
        report(video_seconds=None, audio_seconds=None, seconds=None,
               silent_seconds=None, black_seconds=None), preset=preset())
    codes = [f["code"] for f in verdict["failures"]]
    assert clip_gate.FAIL_UNMEASURED in codes
    assert verdict["ok"] is False


def test_every_failure_is_reported_not_just_the_first():
    verdict = clip_gate.evaluate(
        report(seconds=5.0, video_seconds=5.0, audio_seconds=5.0, silent_seconds=5.0),
        preset=preset(), expected_seconds=30.0)
    codes = {f["code"] for f in verdict["failures"]}
    assert codes == {clip_gate.FAIL_SHORTFALL, clip_gate.FAIL_TOO_SHORT,
                     clip_gate.FAIL_SILENT}


def test_silence_below_the_bound_is_accepted():
    limit = config.get_short_gate_silent_ratio()
    verdict = clip_gate.evaluate(
        report(silent_seconds=30.0 * limit), preset=preset())
    assert verdict["ok"] is True


def test_unmeasured_silence_does_not_fail_the_clip():
    """測れなかった項目を0で埋めないので、無音判定は行われず合格でも不合格でもない。"""
    verdict = clip_gate.evaluate(
        report(silent_seconds=None, black_seconds=None), preset=preset())
    assert verdict["ok"] is True


def test_subtitles_requested_without_any_speech_is_a_failure():
    verdict = clip_gate.evaluate(
        report(), preset=preset(subtitles=1), subtitle_lines=0)
    assert [f["code"] for f in verdict["failures"]] == [clip_gate.FAIL_NO_SUBTITLE]


def test_subtitles_not_requested_ignores_the_speech_count():
    verdict = clip_gate.evaluate(
        report(), preset=preset(subtitles=0), subtitle_lines=0)
    assert verdict["ok"] is True


def test_length_outside_the_preset_is_rejected_on_both_sides():
    short = clip_gate.evaluate(
        report(seconds=10.0, video_seconds=10.0, audio_seconds=10.0), preset=preset())
    long = clip_gate.evaluate(
        report(seconds=90.0, video_seconds=90.0, audio_seconds=90.0), preset=preset())
    assert [f["code"] for f in short["failures"]] == [clip_gate.FAIL_TOO_SHORT]
    assert [f["code"] for f in long["failures"]] == [clip_gate.FAIL_TOO_LONG]


def test_tolerance_absorbs_a_frame_of_rounding():
    tolerance = config.get_short_gate_tolerance_seconds()
    seconds = 15.0 - tolerance / 2.0
    verdict = clip_gate.evaluate(
        report(seconds=seconds, video_seconds=seconds, audio_seconds=seconds),
        preset=preset(), expected_seconds=15.0)
    assert verdict["ok"] is True
