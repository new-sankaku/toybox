"""切り抜きの隣へ出す字幕・comment sidecarの検証。

ここで守りたいのは1点に尽きる。**sidecarの0点は要求のstartではなくactual_start_seconds**
であること。stream copyは直前のkeyframeから始まるので(実測2.1秒〜37.6秒手前)、要求の
startを0点にすると全cueがlead秒ぶん後ろへずれる。ズレた字幕は「それらしく」見えるので、
外部NLEへ渡してから気付くことになる。
"""

import pytest

from tictok.media import clip_sidecar, comment_track
from tictok.record import subtitles
from tictok.record.transcription import TIMEMAP_VERSION


def _comment(at, body, nickname="視聴者"):
    return {"video_time": at, "nickname": nickname, "body": body}


def _transcript(segments, timemap_version=TIMEMAP_VERSION):
    return {"segments": segments, "timemap_version": timemap_version}


def _clip(tmp_path, start, end, actual_start=None, duration=None):
    out = tmp_path / "00001_tester_20260101_120000_001200-001300.mp4"
    out.write_bytes(b"\x00" * 8)
    return {"path": str(out), "filename": out.name, "start": start, "end": end,
            "actual_start_seconds": start if actual_start is None else actual_start,
            "output_duration_seconds": duration}


# ----------------------------------------------------------------- window_segments


def test_window_segments_rebases_to_the_origin():
    segments = [{"start": 100.0, "end": 102.0, "text": "中"}]
    got = subtitles.window_segments(segments, 90.0, 110.0, origin=90.0)
    assert got == [{"start": 10.0, "end": 12.0, "text": "中"}]


def test_window_segments_uses_the_keyframe_origin_not_the_request():
    """要求は100秒からでも、実物は96.5秒から始まっている。0点は96.5でなければならない。"""
    segments = [{"start": 100.0, "end": 102.0, "text": "発話"}]
    got = subtitles.window_segments(segments, 96.5, 106.5, origin=96.5)
    assert got == [{"start": 3.5, "end": 5.5, "text": "発話"}]


def test_window_segments_drops_segments_outside_the_window():
    segments = [{"start": 10.0, "end": 12.0, "text": "前"},
                {"start": 100.0, "end": 102.0, "text": "中"},
                {"start": 500.0, "end": 502.0, "text": "後"}]
    got = subtitles.window_segments(segments, 90.0, 110.0, origin=90.0)
    assert [s["text"] for s in got] == ["中"]


def test_window_segments_truncates_a_segment_that_straddles_the_edge():
    """端に掛かる発話を落とすと、切り抜きの冒頭が無言だったように読める。"""
    segments = [{"start": 85.0, "end": 95.0, "text": "またぐ"},
                {"start": 105.0, "end": 115.0, "text": "またぐ2"}]
    got = subtitles.window_segments(segments, 90.0, 110.0, origin=90.0)
    assert got == [{"start": 0.0, "end": 5.0, "text": "またぐ"},
                   {"start": 15.0, "end": 20.0, "text": "またぐ2"}]


def test_window_segments_keeps_dropping_unusable_segments():
    segments = [{"start": 100.0, "end": None, "text": "端が無い"},
                {"start": 100.0, "end": 102.0, "text": "  "}]
    assert subtitles.window_segments(segments, 90.0, 110.0, origin=90.0) == []


# ------------------------------------------------------------------ comment_track


def test_usable_comments_windows_and_rebases():
    rows = [_comment(10.0, "前"), _comment(100.0, "中"), _comment(500.0, "後")]
    got = comment_track.usable_comments(rows, 96.5, 106.5, origin=96.5)
    assert [(c["t"], c["body"]) for c in got] == [(3.5, "中")]


def test_usable_comments_drops_rows_without_a_time_or_body():
    rows = [_comment(None, "時刻なし"), _comment(5.0, "   "), _comment(5.0, "残る")]
    assert [c["body"] for c in comment_track.usable_comments(rows)] == ["残る"]


def test_usable_comments_sorts_by_time():
    rows = [_comment(9.0, "後"), _comment(1.0, "前")]
    assert [c["body"] for c in comment_track.usable_comments(rows)] == ["前", "後"]


def test_to_segments_closes_a_cue_when_the_next_one_opens():
    """重なるcueを出すと、SRTを読む側によって片方が消えたり順が入れ替わったりする。"""
    rows = comment_track.usable_comments([_comment(0.0, "a"), _comment(1.5, "b")])
    got = comment_track.to_segments(rows, cue_seconds=4.0, max_lines=1)
    assert [(s["start"], s["end"]) for s in got] == [(0.0, 1.5), (1.5, 4.0 + 1.5)]


def test_to_segments_merges_comments_that_share_an_open_cue():
    rows = comment_track.usable_comments([_comment(0.0, "a"), _comment(1.0, "b")])
    got = comment_track.to_segments(rows, cue_seconds=4.0, max_lines=4)
    assert len(got) == 1
    assert got[0]["text"] == "[視聴者] a\n[視聴者] b"


def test_to_segments_caps_the_lines_in_one_cue():
    rows = comment_track.usable_comments(
        [_comment(index * 0.1, str(index)) for index in range(6)])
    got = comment_track.to_segments(rows, cue_seconds=4.0, max_lines=2)
    assert [len(s["text"].splitlines()) for s in got] == [2, 2, 2]


def test_to_segments_keeps_same_instant_comments_together_past_the_cap():
    """同時刻は時間軸で分けようがない。cueを閉じると長さ0になり内容ごと落ちる。"""
    rows = comment_track.usable_comments(
        [_comment(0.0, "a"), _comment(0.0, "b"), _comment(0.0, "c")])
    got = comment_track.to_segments(rows, cue_seconds=4.0, max_lines=2)
    assert len(got) == 1
    assert got[0]["text"].splitlines() == ["[視聴者] a", "[視聴者] b", "[視聴者] c"]


def test_to_segments_clamps_the_last_cue_to_the_media_duration():
    rows = comment_track.usable_comments([_comment(8.0, "終わり際")])
    got = comment_track.to_segments(rows, media_duration=10.0, cue_seconds=4.0)
    assert got[0]["end"] == 10.0


def test_to_segments_drops_a_cue_that_starts_past_the_media_duration():
    rows = comment_track.usable_comments([_comment(12.0, "尺の外")])
    assert comment_track.to_segments(rows, media_duration=10.0, cue_seconds=4.0) == []


def test_line_omits_the_bracket_when_there_is_no_nickname():
    rows = comment_track.usable_comments([_comment(0.0, "本文だけ", nickname="")])
    got = comment_track.to_segments(rows, cue_seconds=4.0)
    assert got[0]["text"] == "本文だけ"


def test_to_srt_renders_a_sequential_cue():
    rows = comment_track.usable_comments([_comment(3.5, "やば")])
    assert comment_track.to_srt(rows, cue_seconds=4.0) == (
        "1\n00:00:03,500 --> 00:00:07,500\n[視聴者] やば\n"
    )


def test_to_csv_writes_seconds_and_a_timecode_with_crlf():
    rows = comment_track.usable_comments([_comment(3.5, "やば")])
    body = comment_track.to_csv(rows)
    # timecodeのmillis区切りはSRTのカンマではなくpoint。毎行が引用符付きになるのを避ける。
    assert body.splitlines() == ["time_seconds,timecode,nickname,body",
                                 "3.500,00:00:03.500,視聴者,やば"]
    assert body.endswith("\r\n")


def test_to_json_rounds_the_time():
    rows = comment_track.usable_comments([_comment(3.5006, "やば")])
    assert '"t": 3.501' in comment_track.to_json(rows)


def test_render_rejects_an_unknown_format():
    with pytest.raises(ValueError):
        comment_track.render("edl", [])


# ------------------------------------------------------------------- clip_sidecar


def test_write_puts_the_sidecars_next_to_the_clip(tmp_path):
    clip = _clip(tmp_path, 100.0, 110.0, actual_start=96.5, duration=13.5)
    got = clip_sidecar.write(
        clip, "source",
        _transcript([{"start": 100.0, "end": 102.0, "text": "発話"}]),
        [_comment(101.0, "やば")])
    stem = tmp_path / "00001_tester_20260101_120000_001200-001300"
    assert sorted(got["files"]) == sorted([
        stem.name + ".srt", stem.name + ".comments.srt", stem.name + ".comments.csv"])
    assert got["skipped"] == ""
    assert (stem.parent / (stem.name + ".srt")).is_file()


def test_write_rebases_the_sidecar_to_the_keyframe_start(tmp_path):
    """要求100秒・実物96.5秒開始。100秒の発話はsidecar上で3.5秒になる。"""
    clip = _clip(tmp_path, 100.0, 110.0, actual_start=96.5, duration=13.5)
    clip_sidecar.write(
        clip, "source",
        _transcript([{"start": 100.0, "end": 102.0, "text": "発話"}]), [])
    body = (tmp_path / "00001_tester_20260101_120000_001200-001300.srt").read_text("utf-8")
    assert "00:00:03,500 --> 00:00:05,500" in body


def test_write_covers_the_keyframe_lead_region(tmp_path):
    """leadで手前へ伸びた区間も切り抜きの中身なので、そこの発話も字幕に入る。"""
    clip = _clip(tmp_path, 100.0, 110.0, actual_start=96.5, duration=13.5)
    clip_sidecar.write(
        clip, "source",
        _transcript([{"start": 97.0, "end": 98.0, "text": "lead区間"}]), [])
    body = (tmp_path / "00001_tester_20260101_120000_001200-001300.srt").read_text("utf-8")
    assert "lead区間" in body


def test_write_falls_back_to_the_requested_window_when_the_duration_is_unmeasurable(tmp_path):
    """ffprobeが無い場合はleadも測れていないので、窓は要求区間そのものになる。"""
    clip = _clip(tmp_path, 100.0, 110.0, duration=None)
    assert clip_sidecar._window(clip) == (100.0, 110.0)


def test_write_skips_a_variant_it_cannot_time(tmp_path):
    clip = _clip(tmp_path, 100.0, 110.0, duration=10.0)
    got = clip_sidecar.write(
        clip, "overlay",
        _transcript([{"start": 100.0, "end": 102.0, "text": "発話"}]),
        [_comment(101.0, "やば")])
    assert got["files"] == []
    assert "元録画以外" in got["skipped"]
    assert not (tmp_path / "00001_tester_20260101_120000_001200-001300.srt").exists()


def test_write_skips_everything_when_the_sidecar_is_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("TICTOK_CLIP_SIDECAR", "0")
    clip = _clip(tmp_path, 100.0, 110.0, duration=10.0)
    got = clip_sidecar.write(
        clip, "source", _transcript([{"start": 100.0, "end": 102.0, "text": "x"}]), [])
    assert got["files"] == []
    assert got["skipped"]


def test_write_does_not_leave_an_empty_subtitle_file(tmp_path):
    """空のsidecarを置くと、NLEは字幕trackが在るものとして読み「付いているのに何も出ない」
    という切り分けにくい状態になる。"""
    clip = _clip(tmp_path, 100.0, 110.0, duration=10.0)
    got = clip_sidecar.write(
        clip, "source", _transcript([{"start": 500.0, "end": 502.0, "text": "圏外"}]), [])
    assert got["files"] == []
    assert not (tmp_path / "00001_tester_20260101_120000_001200-001300.srt").exists()


def test_write_flags_a_stale_timemap(tmp_path):
    clip = _clip(tmp_path, 100.0, 110.0, duration=10.0)
    got = clip_sidecar.write(
        clip, "source",
        _transcript([{"start": 100.0, "end": 102.0, "text": "発話"}], timemap_version=0),
        [])
    assert got["timemap_stale"] is True
    assert got["files"]


def test_write_without_a_transcript_still_writes_the_comments(tmp_path):
    clip = _clip(tmp_path, 100.0, 110.0, duration=10.0)
    got = clip_sidecar.write(clip, "source", None, [_comment(101.0, "やば")])
    assert sorted(got["files"]) == sorted([
        "00001_tester_20260101_120000_001200-001300.comments.srt",
        "00001_tester_20260101_120000_001200-001300.comments.csv"])


def test_write_safely_reports_a_disk_error_instead_of_failing_the_clip(tmp_path, monkeypatch):
    clip = _clip(tmp_path, 100.0, 110.0, duration=10.0)

    def boom(*args, **kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr(clip_sidecar.Path, "write_text", boom)
    got = clip_sidecar.write_safely(
        clip, "source", _transcript([{"start": 100.0, "end": 102.0, "text": "x"}]), [])
    assert got["files"] == []
    assert "no space" in got["error"]
