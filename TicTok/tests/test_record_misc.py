import hashlib
import json
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
