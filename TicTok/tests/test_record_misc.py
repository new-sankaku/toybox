import hashlib
import json
import pathlib
import subprocess
import sys

import pytest

from tictok.core import layout
from tictok.record import audio_norm, fonts, subtitles, transcription


# --------------------------------------------------------------------------
# subtitles: usable_segments
# --------------------------------------------------------------------------


def test_usable_segments_drops_incomplete_and_empty():
    segs = [
        {"start": 0.0, "end": 1.0, "text": "keep"},
        {"start": None, "end": 2.0, "text": "no start"},
        {"start": 3.0, "end": None, "text": "no end"},
        {"start": 4.0, "end": 5.0, "text": "   "},
        {"start": 6.0, "end": 6.0, "text": "zero length"},
        {"start": 8.0, "end": 7.0, "text": "reversed"},
    ]
    assert subtitles.usable_segments(segs) == [{"start": 0.0, "end": 1.0, "text": "keep"}]


def test_usable_segments_sorts_by_start_and_strips_text():
    segs = [
        {"start": 5.0, "end": 6.0, "text": "  second  "},
        {"start": 1.0, "end": 2.0, "text": "\nfirst\n"},
    ]
    assert [s["text"] for s in subtitles.usable_segments(segs)] == ["first", "second"]


def test_usable_segments_accepts_string_numbers():
    segs = [{"start": "1.5", "end": "2.5", "text": "x"}]
    assert subtitles.usable_segments(segs) == [{"start": 1.5, "end": 2.5, "text": "x"}]


def test_usable_segments_none_and_empty_inputs():
    assert subtitles.usable_segments(None) == []
    assert subtitles.usable_segments([]) == []


def test_usable_segments_clamps_tail_to_media_duration():
    # whisperのVAD窓境界は実尺をわずかに超えることがある。
    segs = [{"start": 10.0, "end": 61.77, "text": "tail"}]
    assert subtitles.usable_segments(segs, media_duration=60.0) == [
        {"start": 10.0, "end": 60.0, "text": "tail"}
    ]


def test_usable_segments_drops_cue_starting_past_media_duration():
    segs = [
        {"start": 5.0, "end": 6.0, "text": "in"},
        {"start": 60.0, "end": 61.0, "text": "at end"},
        {"start": 70.0, "end": 71.0, "text": "beyond"},
    ]
    got = subtitles.usable_segments(segs, media_duration=60.0)
    assert [s["text"] for s in got] == ["in"]


def test_usable_segments_drops_fully_negative_window():
    # 全区間が負のsegmentはmedia軸に実在しない。0クランプ後に end<=start を判定するので
    # 0.0-->0.0 の長さ0 cueにならず落ちる。media_durationの有無で結果が変わらないこと。
    segs = [{"start": -5.0, "end": -1.0, "text": "x"}]
    assert subtitles.usable_segments(segs) == []
    assert subtitles.usable_segments(segs, media_duration=60.0) == []


def test_usable_segments_clamps_head_of_partially_negative_window():
    segs = [{"start": -1.5, "end": 2.0, "text": "x"}]
    assert subtitles.usable_segments(segs) == [{"start": 0.0, "end": 2.0, "text": "x"}]


def test_to_srt_omits_fully_negative_window():
    segs = [
        {"start": -5.0, "end": -1.0, "text": "ghost"},
        {"start": 1.0, "end": 2.0, "text": "real"},
    ]
    out = subtitles.to_srt(segs)
    assert "ghost" not in out
    assert out.startswith("1\n00:00:01,000 --> 00:00:02,000\nreal\n")


def test_usable_segments_without_media_duration_keeps_overhang():
    segs = [{"start": 10.0, "end": 61.77, "text": "tail"}]
    assert subtitles.usable_segments(segs)[0]["end"] == 61.77


# --------------------------------------------------------------------------
# subtitles: _clock / to_srt / to_vtt
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0.0, "00:00:00,000"),
        (0.0004, "00:00:00,000"),
        (0.9999, "00:00:01,000"),
        (59.999, "00:00:59,999"),
        (59.9996, "00:01:00,000"),
        (3599.0, "00:59:59,000"),
        (3600.0, "01:00:00,000"),
        (3661.5, "01:01:01,500"),
        (-5.0, "00:00:00,000"),
        (359999.999, "99:59:59,999"),
    ],
)
def test_clock_srt_format(seconds, expected):
    assert subtitles._clock(seconds, ",") == expected


def test_clock_vtt_uses_dot_separator():
    assert subtitles._clock(1.25, ".") == "00:00:01.250"


def test_to_srt_numbering_is_contiguous_after_drops():
    segs = [
        {"start": 0.0, "end": 1.0, "text": "a"},
        {"start": None, "end": 2.0, "text": "dropped"},
        {"start": 2.0, "end": 3.0, "text": "b"},
    ]
    out = subtitles.to_srt(segs)
    assert out == (
        "1\n00:00:00,000 --> 00:00:01,000\na\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\nb\n"
    )


def test_to_srt_empty_when_nothing_usable():
    assert subtitles.to_srt([{"start": None, "end": None, "text": ""}]) == ""


def test_to_vtt_has_header_and_no_indices():
    out = subtitles.to_vtt([{"start": 1.0, "end": 2.0, "text": "hi"}])
    assert out == "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhi\n"
    assert "-->" in out and not out.startswith("1\n")


def test_to_vtt_header_survives_zero_segments():
    assert subtitles.to_vtt([]) == "WEBVTT\n"


# --------------------------------------------------------------------------
# subtitles: to_text / render
# --------------------------------------------------------------------------


def test_to_text_uses_segments_when_available():
    segs = [{"start": 1.0, "end": 2.0, "text": "b"}, {"start": 0.0, "end": 1.0, "text": "a"}]
    assert subtitles.to_text(segs, "whole") == "a\nb\n"


def test_to_text_falls_back_to_full_text_only_without_segments():
    assert subtitles.to_text([], "whole transcript") == "whole transcript"
    assert subtitles.to_text(None, "") == ""


def test_render_dispatch_matches_export_formats():
    transcript = {"segments": [{"start": 0.0, "end": 1.0, "text": "hi"}], "text": "hi"}
    for fmt in subtitles.EXPORT_FORMATS:
        assert isinstance(subtitles.render(fmt, transcript), str)
    assert subtitles.render("srt", transcript).startswith("1\n")
    assert subtitles.render("vtt", transcript).startswith("WEBVTT")
    assert subtitles.render("txt", transcript) == "hi\n"


def test_render_rejects_unknown_format():
    with pytest.raises(ValueError):
        subtitles.render("ass", {"segments": []})


def test_render_tolerates_transcript_without_segments():
    assert subtitles.render("srt", {}) == ""
    assert subtitles.render("txt", {"text": "raw"}) == "raw"


def test_export_formats_table_is_consistent():
    for fmt, (ext, mime, enc) in subtitles.EXPORT_FORMATS.items():
        assert ext == f".{fmt}"
        assert enc == "utf-8"
        assert "charset=utf-8" in mime


# --------------------------------------------------------------------------
# subtitles: timemap_current / fingerprint
# --------------------------------------------------------------------------


def test_timemap_current_only_for_exact_current_version():
    assert subtitles.timemap_current(transcription.TIMEMAP_VERSION) is True
    assert subtitles.timemap_current(None) is False
    assert subtitles.timemap_current(str(transcription.TIMEMAP_VERSION)) is False
    assert subtitles.timemap_current(transcription.TIMEMAP_VERSION + 1) is False


def test_axis_matches_media_rejects_a_transcript_from_a_different_timeline():
    """版が同じでも、作られたときの入力が別物なら時刻は尺に比例してずれる。実測(版1のまま)
    で実尺+191秒・+28287秒の文字起こしが存在した。焼き込みは戻せないので拒否する。"""
    assert subtitles.axis_matches_media({"duration": 5265.93}, 5074.8) is False
    assert subtitles.axis_matches_media({"duration": 38584.7}, 10297.4) is False


def test_axis_matches_media_accepts_a_transcript_of_the_same_material():
    assert subtitles.axis_matches_media({"duration": 5074.78}, 5074.8) is True
    assert subtitles.axis_matches_media({"duration": 5076.0}, 5074.8) is True


def test_axis_matches_media_allows_when_there_is_no_evidence():
    """実尺が測れない/尺を持たない文字起こしは、ズレている証拠が無い。根拠なく拒否すると
    正しい文字起こしまで焼けなくなる。"""
    assert subtitles.axis_matches_media({"duration": 5265.93}, None) is True
    assert subtitles.axis_matches_media({"duration": 5265.93}, 0) is True
    assert subtitles.axis_matches_media({}, 5074.8) is True
    assert subtitles.axis_matches_media(None, 5074.8) is True


def test_fingerprint_empty_for_missing_transcript():
    assert subtitles.fingerprint(None) == ""
    assert subtitles.fingerprint({}) == ""


def test_fingerprint_changes_with_segment_text():
    a = {"timemap_version": 1, "segments": [{"start": 0.0, "end": 1.0, "text": "a"}]}
    b = {"timemap_version": 1, "segments": [{"start": 0.0, "end": 1.0, "text": "b"}]}
    assert subtitles.fingerprint(a) != subtitles.fingerprint(b)
    assert len(subtitles.fingerprint(a)) == 64


def test_fingerprint_changes_with_timemap_version():
    segs = [{"start": 0.0, "end": 1.0, "text": "a"}]
    assert subtitles.fingerprint({"timemap_version": 1, "segments": segs}) != subtitles.fingerprint(
        {"timemap_version": 2, "segments": segs}
    )


def test_fingerprint_ignores_segment_order_and_unusable_noise():
    a = {
        "timemap_version": 1,
        "segments": [
            {"start": 2.0, "end": 3.0, "text": "b"},
            {"start": 0.0, "end": 1.0, "text": "a"},
        ],
    }
    b = {
        "timemap_version": 1,
        "segments": [
            {"start": 0.0, "end": 1.0, "text": "a"},
            {"start": None, "end": 9.0, "text": "junk"},
            {"start": 2.0, "end": 3.0, "text": "b"},
        ],
    }
    assert subtitles.fingerprint(a) == subtitles.fingerprint(b)


def test_fingerprint_ignores_unrelated_transcript_fields():
    base = {"timemap_version": 1, "segments": [{"start": 0.0, "end": 1.0, "text": "a"}]}
    other = dict(base, model="large-v3", language="ja", duration=12.5)
    assert subtitles.fingerprint(base) == subtitles.fingerprint(other)


# --------------------------------------------------------------------------
# audio_norm: targets / filter / encode args
# --------------------------------------------------------------------------


def test_targets_coerces_types():
    got = audio_norm.targets(
        {"audio_normalize_lufs": "-14", "audio_normalize_true_peak": "-1.5",
         "audio_normalize_bitrate_kbps": "192"}
    )
    assert got == {"target_lufs": -14.0, "true_peak": -1.5, "bitrate_kbps": 192}


def test_targets_raises_on_missing_setting():
    with pytest.raises(TypeError):
        audio_norm.targets({})


def test_targets_from_cfg_disabled_returns_none():
    assert audio_norm.targets_from_cfg({}) is None
    assert audio_norm.targets_from_cfg({"video_output_normalize_audio": 0}) is None
    assert audio_norm.targets_from_cfg({"video_output_normalize_audio": "0"}) is None
    assert audio_norm.targets_from_cfg({"video_output_normalize_audio": None}) is None


def test_targets_from_cfg_enabled():
    cfg = {
        "video_output_normalize_audio": "1",
        "audio_normalize_lufs": -14,
        "audio_normalize_true_peak": -1.5,
        "audio_normalize_bitrate_kbps": 192,
    }
    assert audio_norm.targets_from_cfg(cfg) == {
        "target_lufs": -14.0, "true_peak": -1.5, "bitrate_kbps": 192,
    }


def test_targets_from_cfg_enabled_without_values_raises():
    with pytest.raises(KeyError):
        audio_norm.targets_from_cfg({"video_output_normalize_audio": 1})


def test_normalize_setting_keys_cover_targets_inputs():
    assert set(audio_norm.NORMALIZE_SETTING_KEYS) == {
        "audio_normalize_lufs", "audio_normalize_true_peak", "audio_normalize_bitrate_kbps",
    }


def test_audio_filter_keeps_aresample_first():
    got = audio_norm.audio_filter(-14.0, -1.5)
    assert got == "aresample=async=1,loudnorm=I=-14:TP=-1.5"
    assert got.split(",")[0] == "aresample=async=1"


def test_audio_filter_trims_float_noise():
    assert audio_norm.audio_filter(-23.0, -2.0) == "aresample=async=1,loudnorm=I=-23:TP=-2"


def test_encode_args_pins_source_sample_rate():
    args = audio_norm.encode_args(-14.0, -1.5, 192, 44100)
    assert args[:4] == ["-c:a", "aac", "-b:a", "192k"]
    assert args[-2:] == ["-ar", "44100"]
    assert args[args.index("-af") + 1] == audio_norm.audio_filter(-14.0, -1.5)


def test_encode_args_omits_rate_when_no_audio_stream():
    args = audio_norm.encode_args(-14.0, -1.5, 192, None)
    assert "-ar" not in args


def test_encode_args_coerces_numeric_strings():
    args = audio_norm.encode_args(-14.0, -1.5, "128", "48000")
    assert "128k" in args
    assert args[-1] == "48000"


def test_describe_marks_absence_explicitly():
    assert audio_norm.describe(None) == {"audio_normalize": False}
    assert audio_norm.describe({}) == {"audio_normalize": False}


def test_describe_reports_targets():
    got = audio_norm.describe({"target_lufs": -14.0, "true_peak": -1.5, "bitrate_kbps": 192})
    assert got == {
        "audio_normalize": True,
        "audio_target_lufs": -14.0,
        "audio_true_peak": -1.5,
        "audio_bitrate_kbps": 192,
    }


# --------------------------------------------------------------------------
# audio_norm: probe_sample_rate (subprocess monkeypatched)
# --------------------------------------------------------------------------


def _stub_probe(monkeypatch, *, streams=None, exc=None):
    monkeypatch.setattr(audio_norm, "ffprobe_available", lambda: True)

    def fake_run(args, **kwargs):
        assert args[0] == "ffprobe"
        assert kwargs.get("check") is True
        if exc is not None:
            raise exc
        payload = json.dumps({"streams": streams if streams is not None else []})
        return subprocess.CompletedProcess(args, 0, payload.encode("utf-8"), b"")

    monkeypatch.setattr(audio_norm.subprocess, "run", fake_run)


def test_probe_sample_rate_requires_ffprobe(monkeypatch):
    monkeypatch.setattr(audio_norm, "ffprobe_available", lambda: False)
    with pytest.raises(RuntimeError, match="ffprobe"):
        audio_norm.probe_sample_rate("in.mp4")


def test_probe_sample_rate_reads_first_audio_stream(monkeypatch):
    _stub_probe(monkeypatch, streams=[{"sample_rate": "44100"}, {"sample_rate": "48000"}])
    assert audio_norm.probe_sample_rate("in.mp4") == 44100


def test_probe_sample_rate_none_without_audio_stream(monkeypatch):
    _stub_probe(monkeypatch, streams=[])
    assert audio_norm.probe_sample_rate("in.mp4") is None


def test_probe_sample_rate_rejects_nonpositive_rate(monkeypatch):
    _stub_probe(monkeypatch, streams=[{"sample_rate": "0"}])
    with pytest.raises(RuntimeError):
        audio_norm.probe_sample_rate("in.mp4")


def test_probe_sample_rate_raises_on_ffprobe_failure(monkeypatch):
    _stub_probe(
        monkeypatch,
        exc=subprocess.CalledProcessError(1, ["ffprobe"], output=b"", stderr=b"boom"),
    )
    with pytest.raises(RuntimeError, match="音声情報の取得に失敗"):
        audio_norm.probe_sample_rate("in.mp4")


def test_probe_sample_rate_raises_on_unparsable_output(monkeypatch):
    monkeypatch.setattr(audio_norm, "ffprobe_available", lambda: True)
    monkeypatch.setattr(
        audio_norm.subprocess, "run",
        lambda args, **kw: subprocess.CompletedProcess(args, 0, b"not json", b""),
    )
    with pytest.raises(RuntimeError):
        audio_norm.probe_sample_rate("in.mp4")


# --------------------------------------------------------------------------
# fonts
# --------------------------------------------------------------------------


@pytest.fixture
def font_dir(tmp_path, monkeypatch):
    """FONT_DIRを必ずtmpへ逃がす(本番 assets/fonts を触らない)。"""
    d = tmp_path / "fonts"
    d.mkdir()
    monkeypatch.setattr(fonts, "FONT_DIR", d)
    monkeypatch.setattr(fonts, "_ensured", False)
    return d


def test_font_manifest_pins_are_well_formed():
    assert fonts.FONT_MANIFEST
    for name, spec in fonts.FONT_MANIFEST.items():
        assert spec.url.startswith("https://"), name
        assert len(spec.sha256) == 64, name
        assert set(spec.sha256) <= set("0123456789abcdef"), name
    digests = [s.sha256 for s in fonts.FONT_MANIFEST.values()]
    assert len(set(digests)) == len(digests)


def test_sha256_matches_hashlib(font_dir):
    path = font_dir / "blob.bin"
    data = b"\x00\x01\x02" * 1000
    path.write_bytes(data)
    assert fonts._sha256(path) == hashlib.sha256(data).hexdigest()


def test_present_requires_matching_digest(font_dir):
    data = b"font-bytes"
    spec = fonts._Font("https://example/f.ttf", hashlib.sha256(data).hexdigest())
    assert fonts._present("f.ttf", spec) is False
    (font_dir / "f.ttf").write_bytes(b"other")
    assert fonts._present("f.ttf", spec) is False
    (font_dir / "f.ttf").write_bytes(data)
    assert fonts._present("f.ttf", spec) is True


def _stub_urlopen(monkeypatch, data):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return data

    monkeypatch.setattr(fonts.urllib.request, "urlopen", lambda req, timeout=None: _Resp())


def test_fetch_writes_verified_bytes_atomically(font_dir, monkeypatch):
    data = b"good-font"
    _stub_urlopen(monkeypatch, data)
    spec = fonts._Font("https://example/f.ttf", hashlib.sha256(data).hexdigest())
    fonts._fetch("f.ttf", spec)
    assert (font_dir / "f.ttf").read_bytes() == data
    assert not (font_dir / "f.ttf.part").exists()


def test_fetch_rejects_digest_mismatch_without_writing(font_dir, monkeypatch):
    _stub_urlopen(monkeypatch, b"tampered")
    spec = fonts._Font("https://example/f.ttf", "0" * 64)
    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        fonts._fetch("f.ttf", spec)
    assert list(font_dir.iterdir()) == []


def test_fetch_leaves_existing_file_untouched_on_mismatch(font_dir, monkeypatch):
    (font_dir / "f.ttf").write_bytes(b"previous-good")
    _stub_urlopen(monkeypatch, b"tampered")
    with pytest.raises(RuntimeError):
        fonts._fetch("f.ttf", fonts._Font("https://example/f.ttf", "1" * 64))
    assert (font_dir / "f.ttf").read_bytes() == b"previous-good"


def test_ensure_fonts_fetches_only_missing(font_dir, monkeypatch):
    manifest = {
        "a.ttf": fonts._Font("https://example/a", hashlib.sha256(b"A").hexdigest()),
        "b.ttf": fonts._Font("https://example/b", hashlib.sha256(b"B").hexdigest()),
    }
    monkeypatch.setattr(fonts, "FONT_MANIFEST", manifest)
    (font_dir / "a.ttf").write_bytes(b"A")
    fetched = []
    monkeypatch.setattr(fonts, "_fetch", lambda n, s: fetched.append(n))
    fonts.ensure_fonts()
    assert fetched == ["b.ttf"]


def test_ensure_fonts_is_idempotent_after_success(font_dir, monkeypatch):
    manifest = {"a.ttf": fonts._Font("https://example/a", hashlib.sha256(b"A").hexdigest())}
    monkeypatch.setattr(fonts, "FONT_MANIFEST", manifest)
    calls = []
    monkeypatch.setattr(fonts, "_fetch", lambda n, s: calls.append(n) or (font_dir / n).write_bytes(b"A"))
    fonts.ensure_fonts()
    fonts.ensure_fonts()
    assert calls == ["a.ttf"]


def test_ensure_fonts_force_refetches(font_dir, monkeypatch):
    manifest = {"a.ttf": fonts._Font("https://example/a", hashlib.sha256(b"A").hexdigest())}
    monkeypatch.setattr(fonts, "FONT_MANIFEST", manifest)
    (font_dir / "a.ttf").write_bytes(b"A")
    calls = []
    monkeypatch.setattr(fonts, "_fetch", lambda n, s: calls.append(n))
    fonts.ensure_fonts()
    assert calls == []
    fonts.ensure_fonts(force=True)
    assert calls == ["a.ttf"]


def test_ensure_fonts_propagates_failure_and_stays_unensured(font_dir, monkeypatch):
    manifest = {"a.ttf": fonts._Font("https://example/a", hashlib.sha256(b"A").hexdigest())}
    monkeypatch.setattr(fonts, "FONT_MANIFEST", manifest)

    def boom(name, spec):
        raise OSError("network down")

    monkeypatch.setattr(fonts, "_fetch", boom)
    with pytest.raises(OSError):
        fonts.ensure_fonts()
    assert fonts._ensured is False
    with pytest.raises(OSError):
        fonts.ensure_fonts()


def test_ensure_fonts_creates_missing_font_dir(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "fonts"
    monkeypatch.setattr(fonts, "FONT_DIR", target)
    monkeypatch.setattr(fonts, "_ensured", False)
    monkeypatch.setattr(fonts, "FONT_MANIFEST", {})
    fonts.ensure_fonts()
    assert target.is_dir()


# --------------------------------------------------------------------------
# transcription: _media_time
# --------------------------------------------------------------------------


def test_media_time_identity_without_anchors():
    assert transcription._media_time([], [], 12.5) == 12.5
    assert transcription._media_time([], [], 0.0) == 0.0


def test_media_time_interpolates_between_anchors():
    g = [0.0, 10.0, 20.0]
    m = [0.0, 11.0, 23.0]
    assert transcription._media_time(g, m, 0.0) == pytest.approx(0.0)
    assert transcription._media_time(g, m, 5.0) == pytest.approx(5.5)
    assert transcription._media_time(g, m, 10.0) == pytest.approx(11.0)
    assert transcription._media_time(g, m, 15.0) == pytest.approx(17.0)


def test_media_time_extrapolates_with_edge_offsets():
    g = [5.0, 10.0]
    m = [7.0, 13.0]
    # 先頭より前は最初のoffset、最後より後ろは最後のoffsetで平行移動する。
    assert transcription._media_time(g, m, 0.0) == pytest.approx(2.0)
    assert transcription._media_time(g, m, 25.0) == pytest.approx(28.0)


def test_media_time_is_monotonic_over_a_drifting_map():
    g = [0.0, 30.0, 60.0, 90.0]
    m = [0.0, 31.0, 65.0, 101.0]
    values = [transcription._media_time(g, m, t) for t in range(0, 120, 3)]
    assert all(b >= a for a, b in zip(values, values[1:]))


def test_media_time_never_goes_backwards_at_a_zero_width_anchor():
    g = [0.0, 10.0, 10.0, 20.0]
    m = [0.0, 12.0, 18.0, 28.0]
    assert transcription._media_time(g, m, 10.0) == pytest.approx(18.0)
    assert transcription._media_time(g, m, 15.0) == pytest.approx(23.0)


def test_media_time_single_anchor_is_a_constant_offset():
    assert transcription._media_time([5.0], [7.0], 1.0) == pytest.approx(3.0)
    assert transcription._media_time([5.0], [7.0], 9.0) == pytest.approx(11.0)


# --------------------------------------------------------------------------
# transcription: status / device resolution
# --------------------------------------------------------------------------


def test_stt_status_not_configured_when_disabled(monkeypatch):
    monkeypatch.setenv("TICTOK_STT_ENABLED", "0")
    monkeypatch.setattr(transcription, "stt_available", lambda: True)
    status = transcription.stt_status()
    assert status["enabled"] is False
    assert status["configured"] is False
    assert status["timemap_version"] == transcription.TIMEMAP_VERSION


def test_stt_status_not_configured_when_package_missing(monkeypatch):
    monkeypatch.setenv("TICTOK_STT_ENABLED", "1")
    monkeypatch.setattr(transcription, "stt_available", lambda: False)
    status = transcription.stt_status()
    assert status["enabled"] is True
    assert status["available"] is False
    assert status["configured"] is False


def test_stt_status_not_configured_without_model(monkeypatch):
    monkeypatch.setenv("TICTOK_STT_ENABLED", "1")
    monkeypatch.setenv("TICTOK_STT_MODEL", "")
    monkeypatch.setattr(transcription, "stt_available", lambda: True)
    status = transcription.stt_status()
    assert status["model"] == ""
    assert status["configured"] is False


def test_stt_status_configured(monkeypatch):
    monkeypatch.setenv("TICTOK_STT_ENABLED", "1")
    monkeypatch.setenv("TICTOK_STT_MODEL", "large-v3-turbo")
    monkeypatch.setenv("TICTOK_STT_DEVICE", "cuda")
    monkeypatch.setenv("TICTOK_STT_COMPUTE_TYPE", "float16")
    monkeypatch.setattr(transcription, "stt_available", lambda: True)
    status = transcription.stt_status()
    assert status["configured"] is True
    assert status["device"] == "cuda"
    assert status["compute_type"] == "float16"


def test_resolve_device_compute_honours_explicit_values(monkeypatch):
    monkeypatch.setenv("TICTOK_STT_DEVICE", "cpu")
    monkeypatch.setenv("TICTOK_STT_COMPUTE_TYPE", "int8_float16")
    assert transcription._resolve_device_compute() == ("cpu", "int8_float16")


@pytest.mark.parametrize("device,expected", [("cpu", "int8"), ("cuda", "float16")])
def test_resolve_device_compute_auto_precision(monkeypatch, device, expected):
    monkeypatch.setenv("TICTOK_STT_DEVICE", device)
    monkeypatch.setenv("TICTOK_STT_COMPUTE_TYPE", "auto")
    assert transcription._resolve_device_compute() == (device, expected)


@pytest.mark.parametrize("count,expected", [(0, ("cpu", "int8")), (2, ("cuda", "float16"))])
def test_resolve_device_compute_auto_device(monkeypatch, count, expected):
    import types

    fake = types.SimpleNamespace(get_cuda_device_count=lambda: count)
    monkeypatch.setitem(sys.modules, "ctranslate2", fake)
    monkeypatch.setenv("TICTOK_STT_DEVICE", "auto")
    monkeypatch.setenv("TICTOK_STT_COMPUTE_TYPE", "auto")
    assert transcription._resolve_device_compute() == expected


def test_resolve_device_compute_auto_falls_back_to_cpu_when_ctranslate2_broken(monkeypatch):
    import types

    def boom():
        raise RuntimeError("no cuda driver")

    monkeypatch.setitem(sys.modules, "ctranslate2",
                        types.SimpleNamespace(get_cuda_device_count=boom))
    monkeypatch.setenv("TICTOK_STT_DEVICE", "auto")
    monkeypatch.setenv("TICTOK_STT_COMPUTE_TYPE", "auto")
    assert transcription._resolve_device_compute() == ("cpu", "int8")


def test_get_model_raises_when_stt_disabled(monkeypatch):
    monkeypatch.setenv("TICTOK_STT_ENABLED", "0")
    with pytest.raises(transcription.STTError):
        transcription._get_model()


# --------------------------------------------------------------------------
# recorder: 中断録画の復旧
# --------------------------------------------------------------------------


@pytest.fixture
def recovery_env(monkeypatch, tmp_db, tmp_root, make_session):
    """録画中断行を作り、ffmpeg/ffprobeの有無を固定したrecovery環境。

    ffprobeを不在にするのは、testの16 byte mp4を実際にdecodeさせないため。復旧の分岐
    (行を張り直すか作り直すか)はffprobeの有無とは独立に判定される。
    """
    from tictok.record import recorder

    monkeypatch.setattr(recorder, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(recorder, "ffprobe_available", lambda: False)

    counter = {"n": 0}

    def _make(streamer="tester", segments=0, mp4_bytes=None, row_path=None):
        counter["n"] += 1
        stem = f"{counter['n']:05d}_{streamer}_20260101_120000"
        session_id = make_session(streamer, status="connected")
        if segments:
            session_dir = layout.session_dir(tmp_root, stem, streamer)
            session_dir.mkdir(parents=True, exist_ok=True)
            for i in range(segments):
                (session_dir / f"seg{i:05d}.ts").write_bytes(b"\x47" * 188)
        mp4 = layout.mp4_path(tmp_root, stem, streamer)
        if mp4_bytes is not None:
            mp4.parent.mkdir(parents=True, exist_ok=True)
            mp4.write_bytes(mp4_bytes)
        # 録画開始時の行はmp4ではなく録画rootを指す(finalizeが完走して初めて実fileになる)。
        recording_id = tmp_db.create_recording(
            session_id, streamer, row_path or str(tmp_root), f"{stem}.mp4", "hd", 1000.0)
        tmp_db.update_recording(recording_id, "interrupted", row_path or str(tmp_root),
                                f"{stem}.mp4", None, 0)
        return recording_id, stem, mp4

    return _make


async def test_recovery_reattaches_an_mp4_the_row_never_got_pointed_at(
        recovery_env, tmp_db, tmp_root):
    """finalizeがmp4を作った後・DB更新前に落ちた行を、実fileへ張り直す。

    segmentが残っていないので作り直す手段は無く、放置すると完成済みの録画が
    「録画fileが存在しません」のまま出力も再生もできない。"""
    from tictok.record.recorder import recover_interrupted_recordings

    recording_id, _, mp4 = recovery_env(segments=0, mp4_bytes=b"\x00" * 4096)

    assert await recover_interrupted_recordings(tmp_db, tmp_root) == 1

    row = tmp_db.get_recording(recording_id)
    assert row["path"] == str(mp4)
    assert row["status"] == "completed"
    assert row["bytes"] == 4096
    assert row["ended_at"] == pytest.approx(mp4.stat().st_mtime)


async def test_recovery_leaves_a_row_that_already_points_at_its_mp4(
        recovery_env, tmp_db, tmp_root):
    """pathが実fileなら復旧するものは無い。statusも書き換えない。"""
    from tictok.record.recorder import recover_interrupted_recordings

    stem_mp4 = layout.mp4_path(tmp_root, "00001_tester_20260101_120000", "tester")
    stem_mp4.parent.mkdir(parents=True, exist_ok=True)
    stem_mp4.write_bytes(b"\x00" * 16)
    recording_id, _, _ = recovery_env(mp4_bytes=b"\x00" * 16, row_path=str(stem_mp4))

    assert await recover_interrupted_recordings(tmp_db, tmp_root) == 0
    assert tmp_db.get_recording(recording_id)["status"] == "interrupted"


async def test_recovery_rebuilds_from_segments_even_when_an_mp4_already_exists(
        recovery_env, tmp_db, tmp_root, monkeypatch):
    """mp4があってもsegmentが残っていれば作り直す。

    normalize等のfinalize後段で落ちた場合、ディスク上のmp4は途中生成物であり完成品とは
    限らない。素材(seg*.ts)が残っている限り、それを唯一の正とする。"""
    from tictok.record import recorder

    calls = []

    async def fake_finalize(self, base, on_progress=None):
        calls.append(base)
        self.output_path = layout.mp4_path(tmp_root, base, "tester")
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_bytes(b"\x00" * 999)
        self.state = recorder.STATE_COMPLETED
        self.ended_at = 4242.0

    monkeypatch.setattr(recorder.Recorder, "finalize_recovered_hls", fake_finalize)
    recording_id, stem, _ = recovery_env(segments=3, mp4_bytes=b"\x00" * 8)

    assert await recorder.recover_interrupted_recordings(tmp_db, tmp_root) == 1

    assert calls == [stem]
    row = tmp_db.get_recording(recording_id)
    assert row["bytes"] == 999
    assert row["status"] == "completed"


async def test_recovery_skips_rows_with_neither_segments_nor_mp4(
        recovery_env, tmp_db, tmp_root):
    from tictok.record.recorder import recover_interrupted_recordings

    recording_id, _, _ = recovery_env(segments=0, mp4_bytes=None)

    assert await recover_interrupted_recordings(tmp_db, tmp_root) == 0
    assert tmp_db.get_recording(recording_id)["status"] == "interrupted"


async def test_recovery_leaves_recordings_a_media_job_is_holding(
        recovery_env, tmp_db, tmp_root, monkeypatch):
    """待機/実行中のjobが掴んでいる録画は、この起動では復旧しない。

    復旧は確定をやり直す処理で、最後にsession dirごと最終保存先へ移す。同じ素材を読み書き
    しているjobの足元を抜くことになるため、jobが先に走り出していたらこちらが譲る(実測
    2026-07-26 13:10、起動時のts結合が復旧中の録画のsegmentを消し、移送のcopyがそれを
    掴んでFileNotFoundで落ちた)。"""
    from tictok.record import recorder

    calls = []

    async def fake_finalize(self, base, on_progress=None):
        calls.append(base)

    monkeypatch.setattr(recorder.Recorder, "finalize_recovered_hls", fake_finalize)
    recording_id, _, _ = recovery_env(segments=3)
    tmp_db.enqueue_media_job("packjob1", "pack", recording_id)

    assert await recorder.recover_interrupted_recordings(tmp_db, tmp_root) == 0
    assert calls == []
    assert tmp_db.get_recording(recording_id)["status"] == "interrupted"


async def test_finalize_holds_the_recording_against_media_jobs(tmp_root, monkeypatch):
    """確定処理の間、その録画は ``is_finalizing`` で「触るな」と名乗る。抜けたら解ける。"""
    from tictok.record import recorder

    seen = []

    async def fake_body(self, progress=None, build_mp4=False):
        seen.append(recorder.is_finalizing(self.recording_id))

    monkeypatch.setattr(recorder.Recorder, "_finalize_body", fake_body)
    rec = recorder.Recorder("tester", str(tmp_root), 1)
    rec.recording_id = 4242

    await rec._finalize()

    assert seen == [True]
    assert not recorder.is_finalizing(4242)


async def test_recovery_does_not_stamp_ended_at_with_the_recovery_time(
        recovery_env, tmp_db, tmp_root, monkeypatch):
    """復旧は捕捉が終わった時刻を動かさない。既にended_atがある行は据え置く。

    Recorder._finalizeは``ended_at = time.time()``を打つ。それをDBへ書き戻していたため、
    起動時の復旧と再mp4化がDBの尺を「録画開始〜再処理時刻」に化けさせていた(実測: 3時間
    13分の録画が34時間)。同じbatchの行は同じended_atになるので、一覧では古い行ほど尺が
    伸びて積算に見える。ended_atはevent窓としても使われるため被害は表示に留まらない。"""
    from tictok.record import recorder

    async def fake_finalize(self, base, on_progress=None):
        self.output_path = layout.mp4_path(tmp_root, base, "tester")
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_bytes(b"\x00" * 512)
        self.state = recorder.STATE_COMPLETED
        # 復旧を走らせた「今」。DBへ持ち込んではいけない値。
        self.ended_at = 9_999_999.0
        self.duration_seconds = 120.0

    monkeypatch.setattr(recorder.Recorder, "finalize_recovered_hls", fake_finalize)
    recording_id, stem, _ = recovery_env(segments=3)
    tmp_db.update_recording(
        recording_id, "interrupted", str(tmp_root), f"{stem}.mp4", 1300.0, 0)

    assert await recorder.recover_interrupted_recordings(tmp_db, tmp_root) == 1

    row = tmp_db.get_recording(recording_id)
    assert row["ended_at"] == 1300.0
    assert row["duration_seconds"] == pytest.approx(120.0)


async def test_recovery_fills_a_missing_ended_at_from_the_measured_duration(
        recovery_env, tmp_db, tmp_root, monkeypatch):
    """ended_atを持たない行(中断のまま終わった録画)だけは埋める。

    捕捉は実時間で進むので、録画開始+実尺が捕捉の終わりに当たる。復旧を走らせた時刻では
    ない — そちらは何日も後になりうる。"""
    from tictok.record import recorder

    async def fake_finalize(self, base, on_progress=None):
        self.output_path = layout.mp4_path(tmp_root, base, "tester")
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_bytes(b"\x00" * 512)
        self.state = recorder.STATE_COMPLETED
        self.ended_at = 9_999_999.0
        self.duration_seconds = 300.0

    monkeypatch.setattr(recorder.Recorder, "finalize_recovered_hls", fake_finalize)
    recording_id, _, _ = recovery_env(segments=3)

    assert await recorder.recover_interrupted_recordings(tmp_db, tmp_root) == 1

    row = tmp_db.get_recording(recording_id)
    # recovery_envのstarted_atは1000.0。
    assert row["ended_at"] == pytest.approx(1300.0)
    assert row["duration_seconds"] == pytest.approx(300.0)


# --------------------------------------------------------------------------
# recorder: live見どころのPTS再map
# --------------------------------------------------------------------------


def _timing_recorder(tmp_path, tmp_db, session_id, *, media_pts, anchors,
                     started_at=1000.0, ended_at=1300.0):
    """timing map sidecarを持つ録画1本ぶんのRecorderを組む。mp4の中身は使わない
    (長さはprobeを差し替えて与える)。"""
    from tictok.record import recorder as rec_mod

    mp4 = tmp_path / "rec" / "alice" / "mp4" / "00001_alice_20260101_000000.mp4"
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"")
    tp = rec_mod.timing_path(mp4)
    tp.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 2, "media_duration": anchors[-1][1],
               "anchors": [[w, m] for w, m in anchors]}
    if media_pts:
        payload["media_pts"] = [[m, p] for m, p in media_pts]
    tp.write_text(json.dumps(payload), encoding="utf-8")

    r = rec_mod.Recorder("alice", str(tmp_path / "rec"), session_id, storage=tmp_db)
    r.base = mp4.stem
    r.started_at = started_at
    r.ended_at = ended_at
    r.recording_id = tmp_db.create_recording(
        session_id, "alice", str(mp4), mp4.name, "hd", started_at)
    return r, mp4


def test_live_bookmark_is_remapped_onto_the_mp4_timeline(tmp_path, tmp_db, make_session):
    """押下位置(wall-clock)がmp4のPTS軸へ載ること。

    素朴な wall - started_at のままだと、mux inflationのぶんだけ手前を指す。実測では
    112分の録画で340秒ずれた。ここでは 300s の押下が 330s(1.1倍のinflation)へ動く。
    """
    import asyncio

    session_id = make_session("alice")
    r, mp4 = _timing_recorder(
        tmp_path, tmp_db, session_id,
        anchors=[(1000.0, 0.0), (1300.0, 300.0)],
        media_pts=[(0.0, 0.0), (300.0, 330.0)],
    )
    bm = tmp_db.add_live_bookmark(r.recording_id, "alice", wall_time=1300.0,
                                  provisional_start=300.0)
    assert bm["start"] == 300.0 and bm["pts_mapped"] == 0

    async def fake_probe(path):
        return 330.0

    r._probe_duration = fake_probe
    asyncio.run(r._remap_live_bookmarks(mp4))

    row = {b["id"]: b for b in tmp_db.list_bookmarks(r.recording_id)}[bm["id"]]
    assert row["pts_mapped"] == 1
    # 素朴実装なら300.0のまま。再mapされていれば330.0。
    assert row["start"] == pytest.approx(330.0)
    assert row["start"] != pytest.approx(300.0)
    assert tmp_db.list_unmapped_bookmarks(r.recording_id) == []


def test_live_bookmark_stays_provisional_without_a_timing_map(tmp_path, tmp_db, make_session):
    """timing mapが無い(解像度正規化がCFRへ落ちて破棄された等)ときは確定させない。
    暫定値をpts_mapped=1で固めると、ズレたdataが確定値として残る。"""
    import asyncio

    from tictok.record import recorder as rec_mod

    session_id = make_session("alice")
    r, mp4 = _timing_recorder(
        tmp_path, tmp_db, session_id,
        anchors=[(1000.0, 0.0), (1300.0, 300.0)], media_pts=None,
    )
    rec_mod.timing_path(mp4).unlink()
    bm = tmp_db.add_live_bookmark(r.recording_id, "alice", 1300.0, 300.0)

    asyncio.run(r._remap_live_bookmarks(mp4))

    row = {b["id"]: b for b in tmp_db.list_bookmarks(r.recording_id)}[bm["id"]]
    assert row["pts_mapped"] == 0
    assert row["start"] == 300.0
    assert [b["id"] for b in tmp_db.list_unmapped_bookmarks(r.recording_id)] == [bm["id"]]


def test_remap_uses_the_same_mapper_as_the_burn_in(tmp_path, tmp_db, make_session):
    """再mapの結果が焼き込みの時刻mapと一致すること。別実装を持つと、同じ録画で
    コメントの焼き込み位置と見どころの位置が食い違う。"""
    import asyncio

    from tictok.record import video_overlay as vo

    session_id = make_session("alice")
    anchors = [(1000.0, 0.0), (1300.0, 300.0)]
    media_pts = [(0.0, 0.0), (150.0, 160.0), (300.0, 330.0)]
    r, mp4 = _timing_recorder(tmp_path, tmp_db, session_id,
                              anchors=anchors, media_pts=media_pts)
    wall = 1150.0
    bm = tmp_db.add_live_bookmark(r.recording_id, "alice", wall, wall - 1000.0)

    async def fake_probe(path):
        return 330.0

    r._probe_duration = fake_probe
    asyncio.run(r._remap_live_bookmarks(mp4))

    expected = vo._make_time_mapper(anchors, 1000.0, 1300.0, 330.0, None, media_pts)(wall)
    row = {b["id"]: b for b in tmp_db.list_bookmarks(r.recording_id)}[bm["id"]]
    assert row["start"] == pytest.approx(expected)

# --------------------------------------------------------------------------
# recorder: playlist -> VOD playlist (the input the finalize mux reads)
# --------------------------------------------------------------------------


def _recorder_with_hls(tmp_path, playlist_body, segments):
    """A Recorder stub holding just the HLS state the playlist helpers touch.
    ``segments`` maps segment filename -> mtime; a name absent from it is a
    playlist entry with no file on disk."""
    import os

    from tictok.record import recorder as rec

    hls = tmp_path / "hls"
    hls.mkdir()
    for name, mtime in segments.items():
        seg = hls / name
        seg.write_bytes(b"\x00")
        os.utime(seg, (mtime, mtime))
    playlist = hls / "index.m3u8"
    playlist.write_text(playlist_body, encoding="utf-8")

    r = rec.Recorder.__new__(rec.Recorder)
    r.hls_dir = hls
    r.playlist = playlist
    r.base = "stem"
    r.unique_id = "uid"
    r._volume_paths = lambda: []
    return r


def _playlist(entries):
    lines = ["#EXTM3U", "#EXT-X-VERSION:6"]
    for name, extinf in entries:
        lines.append("#EXTINF:%.6f," % extinf)
        lines.append(name)
    return "\n".join(lines) + "\n"


def test_playlist_segments_uses_playlist_order_and_extinf(tmp_path):
    r = _recorder_with_hls(
        tmp_path,
        _playlist([("seg00000.ts", 1.96), ("seg00001.ts", 2.04)]),
        {"seg00000.ts": 1000.0, "seg00001.ts": 1002.0},
    )

    kept = r._playlist_segments()

    assert [(p.name, e, d) for p, e, _, d, _ in kept] == [
        ("seg00000.ts", 1.96, False),
        ("seg00001.ts", 2.04, False),
    ]


def test_playlist_segments_excludes_ts_absent_from_the_playlist(tmp_path):
    # A .ts written after the last playlist flush is an unindexed partial write:
    # it has no #EXTINF, so muxing it would advance pts past the media axis.
    r = _recorder_with_hls(
        tmp_path,
        _playlist([("seg00000.ts", 1.96)]),
        {"seg00000.ts": 1000.0, "seg00001.ts": 1002.0},
    )

    assert [p.name for p, _, _, _, _ in r._playlist_segments()] == ["seg00000.ts"]


def test_playlist_segments_drops_pts_discontinuity_and_marks_the_next(tmp_path):
    # seg1 claims 100s of media for 2s of wall time -> glitched source timestamp.
    r = _recorder_with_hls(
        tmp_path,
        _playlist([("seg00000.ts", 2.0), ("seg00001.ts", 100.0), ("seg00002.ts", 2.0)]),
        {"seg00000.ts": 1000.0, "seg00001.ts": 1002.0, "seg00002.ts": 1004.0},
    )

    kept = r._playlist_segments()

    assert [(p.name, d) for p, _, _, d, _ in kept] == [
        ("seg00000.ts", False),
        ("seg00002.ts", True),
    ]


def test_playlist_segments_carries_a_source_flagged_discontinuity(tmp_path):
    body = _playlist([("seg00000.ts", 2.0)])
    body += "#EXT-X-DISCONTINUITY\n#EXTINF:2.000000,\nseg00001.ts\n"
    r = _recorder_with_hls(
        tmp_path, body, {"seg00000.ts": 1000.0, "seg00001.ts": 1002.0})

    assert [d for _, _, _, d, _ in r._playlist_segments()] == [False, True]


def test_playlist_segments_empty_without_a_playlist(tmp_path):
    r = _recorder_with_hls(tmp_path, _playlist([]), {})
    r.playlist.unlink()

    assert r._playlist_segments() == []


def test_write_vod_playlist_is_terminated_and_typed(tmp_path):
    # Without PLAYLIST-TYPE:VOD + ENDLIST the HLS demuxer treats the list as live
    # and seeks to the live edge, dropping all but the last few segments.
    r = _recorder_with_hls(
        tmp_path,
        _playlist([("seg00000.ts", 1.96), ("seg00001.ts", 2.04)]),
        {"seg00000.ts": 1000.0, "seg00001.ts": 1002.0},
    )
    out = tmp_path / "vod.m3u8"

    assert r._write_vod_playlist(r._playlist_segments(), out) is True

    lines = out.read_text(encoding="utf-8").splitlines()
    assert "#EXT-X-PLAYLIST-TYPE:VOD" in lines
    assert lines[-1] == "#EXT-X-ENDLIST"
    assert "#EXT-X-TARGETDURATION:3" in lines
    # Bare names so the demuxer resolves them beside the playlist.
    assert [l for l in lines if l.endswith(".ts")] == ["seg00000.ts", "seg00001.ts"]
    assert [l for l in lines if l.startswith("#EXTINF")] == [
        "#EXTINF:1.960000,", "#EXTINF:2.040000,"]


def test_write_vod_playlist_emits_a_discontinuity_marker(tmp_path):
    r = _recorder_with_hls(
        tmp_path,
        _playlist([("seg00000.ts", 2.0), ("seg00001.ts", 100.0), ("seg00002.ts", 2.0)]),
        {"seg00000.ts": 1000.0, "seg00001.ts": 1002.0, "seg00002.ts": 1004.0},
    )
    out = tmp_path / "vod.m3u8"
    r._write_vod_playlist(r._playlist_segments(), out)

    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[lines.index("seg00002.ts") - 2] == "#EXT-X-DISCONTINUITY"


def test_media_pts_is_identity_when_pts_contribution_is_the_extinf():
    # What the HLS demuxer produces: each segment contributes exactly its #EXTINF,
    # so the media axis and the container axis coincide.
    from tictok.record.recorder import media_pts_from_segments

    extinfs = [2.0, 1.5, 2.5]
    points = media_pts_from_segments(extinfs, extinfs, 6.0)

    assert points == [[0.0, 0.0], [2.0, 2.0], [3.5, 3.5], [6.0, 6.0]]


def test_media_pts_pins_the_endpoint_to_the_finalized_duration():
    from tictok.record.recorder import media_pts_from_segments

    extinfs = [2.0, 2.0]
    points = media_pts_from_segments(extinfs, extinfs, 4.4)

    assert points[-1] == [4.0, 4.4]
    assert points[1] == [2.0, 2.2]


# --------------------------------------------------------------------------
# layout: 録画横断poolのroot
# --------------------------------------------------------------------------


def test_pool_dirs_do_not_follow_the_mp4_to_the_final_dir(tmp_path, monkeypatch):
    """avatars/emotes/gift_iconsはmp4の位置ではなくwork rootで解決すること。

    poolを書くのは収集時のcollectorでwork root固定。読む側がmp4の現在地で解くと、
    final dirへ移送された録画だけが存在しないpoolを見に行き、avatarもemoteも1件も
    解決できずイニシャル円盤へ黙って縮退する(署名付きCDN URLは失効しており再取得も
    効かない)。移送の有無で結果が変わってはいけない。"""
    from tictok.core import layout

    work = (tmp_path / "work").resolve()
    final = (tmp_path / "final").resolve()
    monkeypatch.setattr(layout, "_pool_root", None)
    layout.set_pool_root(work)
    try:
        assert layout.avatar_pool_dir() == work / "avatars" / "by-id"
        assert layout.emote_pool_dir() == work / "emotes"
        assert layout.gift_icon_pool_dir() == work / "gift_icons"
        # 移送後のmp4から解いたrootはfinal dirだが、poolはwork rootのまま。
        relocated = layout.mp4_path(final, "00001_tester_20260101_120000")
        assert layout.record_root_of(relocated) == final
        assert layout.pool_root() == work
    finally:
        layout.reset_pool_root()


def test_record_root_of_still_follows_the_mp4_for_per_recording_artifacts(tmp_path):
    """録画ごとのartifact(.sidecars)は逆にmp4へ付いていくこと。poolと混同しない。"""
    from tictok.core import layout
    from tictok.record.recorder import sidecar_dir

    final = (tmp_path / "final").resolve()
    relocated = layout.mp4_path(final, "00001_tester_20260101_120000")
    assert sidecar_dir(relocated) == final / ".sidecars"


# ---- 再mp4化のついでの音量正規化 --------------------------------------------------

async def test_concat_audio_args_default_to_the_recording_time_encode(tmp_path):
    """normalize_audioを渡さない経路(通常録画のfinalize)は、録画したままの音量で残すこと。"""
    from tictok.record import recorder as rec_mod

    r = rec_mod.Recorder("alice", str(tmp_path / "rec"), 1)
    args = await r._concat_audio_args(tmp_path / "seg00000.ts")
    assert args == ["-c:a", "aac", "-b:a", "192k", "-af", "aresample=async=1:first_pts=0"]


async def test_concat_audio_args_add_loudnorm_when_asked(tmp_path, monkeypatch):
    """再mp4化はもともと音声を再encodeするので、正規化は同じpassの中で済む。"""
    from tictok.record import audio_norm
    from tictok.record import recorder as rec_mod

    monkeypatch.setattr(audio_norm, "probe_sample_rate", lambda src: 44100)
    r = rec_mod.Recorder(
        "alice", str(tmp_path / "rec"), 1,
        normalize_audio={"target_lufs": -14.0, "true_peak": -1.5, "bitrate_kbps": 192},
    )
    args = await r._concat_audio_args(tmp_path / "seg00000.ts")
    filters = args[args.index("-af") + 1]
    # first_pts=0を落とすと、live .tsの任意の開始PTSがそのまま残り音声だけ原点がずれる。
    assert filters == "aresample=async=1:first_pts=0,loudnorm=I=-14:TP=-1.5"
    assert args[args.index("-ar") + 1] == "44100"


# --------------------------------------------------------------------------
# relocation: the segments move with the mp4
# --------------------------------------------------------------------------

STEM = "00042_alice_20260101_120000"


def _make_pair(root, segments=3, seg_size=188):
    """work root に「.ts一式 + mp4 + sidecar」の実レイアウトを作り、mp4 pathを返す。"""
    from tictok.record.recorder import timing_path

    ts_dir = layout.session_dir(root, STEM)
    ts_dir.mkdir(parents=True, exist_ok=True)
    for i in range(segments):
        (ts_dir / ("seg%05d.ts" % i)).write_bytes(b"\x47" * seg_size)
    (ts_dir / "index.m3u8").write_text("#EXTM3U\n", encoding="utf-8")
    mp4 = layout.mp4_path(root, STEM)
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"\x00" * 2048)
    tp = timing_path(mp4)
    tp.parent.mkdir(parents=True, exist_ok=True)
    tp.write_text('{"version": 2}', encoding="utf-8")
    return mp4


def test_relocation_moves_the_segments_with_the_mp4(tmp_path):
    """.tsは録画の実体なので、mp4だけを移すと原本が作業volumeに取り残される。"""
    from tictok.record.recorder import Recorder, timing_path

    work, final = tmp_path / "work", tmp_path / "final"
    src = _make_pair(work)
    dst = layout.mp4_path(final, STEM)

    Recorder._move_recording_files(src, dst)

    assert dst.is_file()
    assert timing_path(dst).is_file()
    moved_ts = layout.session_dir(final, STEM)
    assert sorted(p.name for p in moved_ts.iterdir()) == [
        "index.m3u8", "seg00000.ts", "seg00001.ts", "seg00002.ts"]
    assert not layout.session_dir(work, STEM).exists()


def test_relocation_verifies_every_segment_before_dropping_the_source(tmp_path, monkeypatch):
    """copyが途中で欠けたら元を消さない。cross-volume moveはcopy+unlinkなので、
    検証せずに消すと「着いていないsegmentを消す」ことになる。"""
    from tictok.record import recorder as rec_mod

    work, final = tmp_path / "work", tmp_path / "final"
    src = _make_pair(work)
    dst = layout.mp4_path(final, STEM)

    real_copy = rec_mod._copy_durable

    def _short_copy(s, d):
        n = real_copy(s, d)
        if d.name == "seg00001.ts":
            d.write_bytes(b"G")      # 途中までしか着かなかった
        return n

    monkeypatch.setattr(rec_mod, "_copy_durable", _short_copy)

    with pytest.raises(OSError, match="did not arrive intact"):
        rec_mod.Recorder._move_recording_files(src, dst)

    assert layout.session_dir(work, STEM).is_dir()
    assert len(list(layout.session_dir(work, STEM).glob("seg*.ts"))) == 3
    assert not layout.session_dir(final, STEM).exists()
    assert src.is_file()


def test_relocation_is_idempotent_when_the_segments_already_moved(tmp_path):
    """mp4だけ失敗して分かれた状態から、同じmoverを再実行すれば揃うこと。"""
    from tictok.record.recorder import Recorder

    work, final = tmp_path / "work", tmp_path / "final"
    src = _make_pair(work)
    dst = layout.mp4_path(final, STEM)
    Recorder._move_session_dir(src, dst)
    assert not layout.session_dir(work, STEM).exists()

    Recorder._move_recording_files(src, dst)

    assert dst.is_file()
    assert len(list(layout.session_dir(final, STEM).glob("seg*.ts"))) == 3


def test_relocation_preserves_each_segment_mtime(tmp_path):
    """segmentのmtimeはtiming mapのwall軸そのもの(recorder._playlist_segments)。
    移送で失うと、移送済み録画の焼き込みでコメントの時刻が壊れる。"""
    import os

    from tictok.record.recorder import Recorder

    work, final = tmp_path / "work", tmp_path / "final"
    src = _make_pair(work, segments=3)
    ts_dir = layout.session_dir(work, STEM)
    stamps = {}
    for i, p in enumerate(sorted(ts_dir.glob("seg*.ts"))):
        when = 1_750_000_000 + i * 2
        os.utime(p, (when, when))
        stamps[p.name] = when

    Recorder._move_recording_files(src, layout.mp4_path(final, STEM))

    moved = layout.session_dir(final, STEM)
    assert {p.name: int(p.stat().st_mtime) for p in sorted(moved.glob("seg*.ts"))} == stamps


def test_a_curated_playlist_written_elsewhere_spells_out_full_paths(tmp_path):
    """playlistの参照は素のfile名だとplaylist自身のdirectoryから解決される。session dirの
    外へ書いたときに素のままだと参照が全て外れ、しかもffmpegは「streamが無い」正常終了に
    見えるので、静かに空の結果を返す。"""
    from tictok.record.recorder import write_curated_playlist

    hls = layout.session_dir(tmp_path / "work", STEM)
    hls.mkdir(parents=True)
    for i in range(2):
        (hls / ("seg%05d.ts" % i)).write_bytes(b"\x47" * 188)
    (hls / "index.m3u8").write_text(
        "#EXTM3U\n#EXTINF:2.000000,\nseg00000.ts\n#EXTINF:2.000000,\nseg00001.ts\n",
        encoding="utf-8")

    inside = write_curated_playlist(hls, hls / "vod.m3u8")
    outside = write_curated_playlist(hls, tmp_path / "vod.m3u8")

    assert "\nseg00000.ts\n" in inside.read_text(encoding="utf-8")
    body = outside.read_text(encoding="utf-8")
    assert str((hls / "seg00000.ts").resolve()) in body
    assert "\nseg00000.ts\n" not in body


async def test_recovery_finds_material_that_was_already_moved_to_the_final_root(
        recovery_env, tmp_db, tmp_root, monkeypatch):
    """素材がfinal rootへ移送済みの録画も復旧すること。

    work rootだけを見ていると「作り直す材料が無い」と判断され、行はinterruptedのまま
    永久に残る。実測でそうなった録画が1本あり、素材はfinal rootに589 segment在るのに
    画面から辿れなくなっていた。"""
    from tictok.record import recorder

    final_root = tmp_root.parent / "final"
    recording_id, stem, _ = recovery_env(segments=0)
    # 素材をfinal rootにだけ置く(=移送済みの形)。
    moved = layout.session_dir(final_root, stem, "tester")
    moved.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        (moved / f"seg{i:05d}.ts").write_bytes(b"\x47" * 188)

    seen = {}

    async def fake_finalize(self, base, progress=None, mp4_root=None, build_mp4=False):
        seen["record_dir"] = self._record_dir
        self.output_path = layout.mp4_path(final_root, base, "tester")
        self.state = recorder.STATE_COMPLETED
        self.ended_at = 4242.0
        self.duration_seconds = 12.0

    monkeypatch.setattr(recorder.Recorder, "finalize_recovered_hls", fake_finalize)
    monkeypatch.setattr(recorder.Recorder, "snapshot", lambda self: {"bytes": 564})

    got = await recorder.recover_interrupted_recordings(
        tmp_db, tmp_root, final_dir=final_root)

    assert got == 1, "final rootの素材が見つかっていない"
    assert str(seen["record_dir"]) == str(final_root), "素材の在るrootが渡っていない"
    assert tmp_db.get_recording(recording_id)["status"] == "completed"


async def test_recovery_sees_a_packed_recording_as_having_material(
        recovery_env, tmp_db, tmp_root, monkeypatch):
    """束ね済み(pack*.ts)の録画も「素材あり」と判定すること。

    ``seg*.ts`` だけを数えていると、束ねた録画は全部「素材無し」になり復旧されない。
    束ねは100本超の録画に適用済みなので、ここを外すとその全部が対象外になる。"""
    from tictok.record import recorder

    recording_id, stem, _ = recovery_env(segments=0)
    session = layout.session_dir(tmp_root, stem, "tester")
    session.mkdir(parents=True, exist_ok=True)
    (session / "pack000.ts").write_bytes(b"\x47" * 564)

    async def fake_finalize(self, base, progress=None, mp4_root=None, build_mp4=False):
        self.output_path = layout.mp4_path(tmp_root, base, "tester")
        self.state = recorder.STATE_COMPLETED
        self.ended_at = 4242.0
        self.duration_seconds = 12.0

    monkeypatch.setattr(recorder.Recorder, "finalize_recovered_hls", fake_finalize)
    monkeypatch.setattr(recorder.Recorder, "snapshot", lambda self: {"bytes": 564})

    assert await recorder.recover_interrupted_recordings(tmp_db, tmp_root) == 1
    assert tmp_db.get_recording(recording_id)["status"] == "completed"


# --------------------------------------------------------------------------
# 焼き込み/プレビューの入力取得は event loop 上でやらない
# --------------------------------------------------------------------------


def _loop_side_storage_calls(module_path, function_names):
    """``function_names`` のasync関数から、threadを経由せず storage を触っている箇所。

    ``asyncio.to_thread(storage.x, ...)`` は関数objectを渡しているだけなので数えない。"""
    import ast

    tree = ast.parse(pathlib.Path(module_path).read_text(encoding="utf-8"))
    found = []

    class Walk(ast.NodeVisitor):
        def __init__(self, name):
            self.name = name

        def visit_Call(self, node):
            if getattr(node.func, "attr", None) == "to_thread":
                for arg in node.args[1:]:
                    self.visit(arg)
                return
            target = node.func
            label = None
            if isinstance(target, ast.Attribute):
                owner = target.value
                chain = []
                while isinstance(owner, ast.Attribute):
                    chain.append(owner.attr)
                    owner = owner.value
                if isinstance(owner, ast.Name):
                    chain.append(owner.id)
                if ".".join(reversed(chain)).endswith("storage"):
                    label = "storage.%s" % target.attr
                elif target.attr in _BLOCKING_HELPERS:
                    # ``media_jobs._preview_sources(...)`` のようにmodule越しの呼び方も拾う。
                    label = target.attr
            elif isinstance(target, ast.Name) and target.id in _BLOCKING_HELPERS:
                label = target.id
            if label:
                found.append("%s:%d %s -> %s" % (module_path, node.lineno, self.name, label))
            self.generic_visit(node)

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in function_names:
            Walk(node.name).visit(node)
    return found


# 中でstorageを触る同期helper。async側から素で呼ぶと同じことになる。
_BLOCKING_HELPERS = {"_preview_sources", "_subtitle_transcript"}


@pytest.mark.parametrize("module_path,functions", [
    ("tictok/api/media_jobs.py",
     {"_burn_in_recording", "_run_preview_clip_job", "_run_clip_overlay_job"}),
    ("tictok/api/routes/media.py", {"preview_still_api", "preview_clip_api"}),
])
def test_burn_in_inputs_are_never_loaded_on_the_event_loop(module_path, functions):
    """焼き込みとプレビューの入力取得は必ずthreadへ出す。

    ``iter_events`` はbufferのflushを待ってからsessionの全eventを読む(実測37,214件で372ms)。
    event loop上で呼ぶとその間serverが丸ごと止まり、writer lockも握るのでcollectorの
    書き出しまで巻き添えになる。実測ではloop上の呼び出しがlock保持者を待つと、待った時間が
    そのままevent loopの停止時間になった(4,706ms 対 to_thread経由17ms)。"""
    assert _loop_side_storage_calls(module_path, functions) == []
