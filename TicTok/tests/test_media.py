import io
import json
import subprocess
import types

import numpy as np
import pytest

from tictok.core import layout
from tictok.media import avatar_pool as ap
from tictok.media import clipper
from tictok.media import gift_icons as gi
from tictok.media import thumbnails as th
from tictok.media import waveform as wf


def _pcm(values):
    return np.asarray(values, dtype="<i2").tobytes()


def _fake_proc(payload: bytes):
    return types.SimpleNamespace(stdout=io.BytesIO(payload))


# --------------------------------------------------------------------------- waveform


def test_fine_peaks_takes_absolute_max_per_frame():
    frame_a = [0] * wf.FINE_FRAME_SAMPLES
    frame_a[3] = 1000
    frame_b = [0] * wf.FINE_FRAME_SAMPLES
    frame_b[7] = -2500
    peaks = wf._fine_peaks(_fake_proc(_pcm(frame_a + frame_b)))
    assert peaks.tolist() == [1000.0, 2500.0]


def test_fine_peaks_handles_int16_min_without_overflow():
    frame = [-32768] * wf.FINE_FRAME_SAMPLES
    peaks = wf._fine_peaks(_fake_proc(_pcm(frame)))
    assert peaks.tolist() == [32768.0]


def test_fine_peaks_keeps_trailing_partial_frame():
    full = [0] * wf.FINE_FRAME_SAMPLES
    full[0] = 100
    tail = [0] * 40
    tail[5] = 900
    peaks = wf._fine_peaks(_fake_proc(_pcm(full + tail)))
    assert peaks.tolist() == [100.0, 900.0]


def test_fine_peaks_empty_stream_returns_empty():
    assert wf._fine_peaks(_fake_proc(b"")).size == 0


def test_reduce_folds_to_exactly_the_requested_buckets():
    fine = np.arange(10, dtype=np.float32)
    out = wf._reduce(fine, 5)
    assert out.tolist() == [1.0, 3.0, 5.0, 7.0, 9.0]


def test_reduce_single_bucket_is_the_global_max():
    fine = np.array([3.0, 41.0, 7.0], dtype=np.float32)
    assert wf._reduce(fine, 1).tolist() == [41.0]


def test_reduce_stretches_when_shorter_than_buckets():
    fine = np.array([5.0, 7.0], dtype=np.float32)
    out = wf._reduce(fine, 4)
    assert out.tolist() == [5.0, 5.0, 7.0, 7.0]


def test_levels_are_time_binned_and_full_scale_normalised():
    frames_per_second = 1000 // wf.FINE_FRAME_MS
    fine = np.zeros(frames_per_second * 3, dtype=np.float32)
    fine[0] = 32768.0
    fine[frames_per_second] = 16384.0
    profile = wf._levels(fine, 1.0)
    assert profile["interval_seconds"] == 1.0
    assert profile["duration_seconds"] == 3.0
    assert profile["levels"] == [1.0, 0.5, 0.0]


def test_levels_interval_snaps_to_fine_frame_grid():
    fine = np.zeros(200, dtype=np.float32)
    profile = wf._levels(fine, 0.001)
    assert profile["interval_seconds"] == wf.FINE_FRAME_MS / 1000.0
    assert len(profile["levels"]) == 200


def test_waveform_cache_roundtrip_and_invalidation(make_recording):
    _, mp4 = make_recording()
    result = {"buckets": 4, "duration_seconds": 12.5, "peaks": [0.1, 0.2, 0.3, 1.0]}
    wf._store_cache(mp4, result)

    assert wf._load_cache(mp4, 4) == result
    assert wf._load_cache(mp4, 8) == {}

    mp4.write_bytes(b"\x00" * 999)
    assert wf._load_cache(mp4, 4) == {}


def test_waveform_cache_rejects_a_stale_schema_version(make_recording):
    _, mp4 = make_recording()
    wf._store_cache(mp4, {"buckets": 2, "duration_seconds": 1.0, "peaks": [0.0, 1.0]})
    path = wf.waveform_path(mp4)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["version"] = wf._CACHE_VERSION + 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert wf._load_cache(mp4, 2) == {}


def test_audio_profile_cache_ignores_a_different_interval(make_recording):
    _, mp4 = make_recording()
    profile = {"interval_seconds": 1.0, "duration_seconds": 4.0,
               "levels": [0.0, 0.5, 0.0, 0.9]}
    wf._store_profile_cache(mp4, profile)
    assert wf._load_profile_cache(mp4, 1.0) == profile
    assert wf._load_profile_cache(mp4, 0.5) == {}


def test_silence_spans_respects_the_minimum_run_length():
    profile = {"interval_seconds": 1.0, "levels": [0.5, 0.0, 0.0, 0.0, 0.5]}
    assert wf.silence_spans(profile) == [{"start": 1.0, "end": 4.0}]

    short = {"interval_seconds": 1.0, "levels": [0.5, 0.0, 0.5]}
    assert wf.silence_spans(short) == []


def test_silence_spans_closes_a_run_that_reaches_the_end():
    profile = {"interval_seconds": 1.0, "levels": [0.5, 0.0, 0.0, 0.0]}
    assert wf.silence_spans(profile) == [{"start": 1.0, "end": 4.0}]


def test_silence_spans_threshold_is_absolute_full_scale():
    profile = {"interval_seconds": 1.0, "levels": [0.4, 0.4, 0.4]}
    assert wf.silence_spans(profile) == []
    assert wf.silence_spans(profile, threshold_dbfs=-6.0, min_seconds=1.0) == [
        {"start": 0.0, "end": 3.0}
    ]


def test_silent_ratio_clamps_the_window_to_the_profile():
    profile = {"interval_seconds": 1.0, "levels": [0.5, 0.0, 0.0, 0.5]}
    assert wf.silent_ratio(profile, 0.0, 4.0) == 0.5
    assert wf.silent_ratio(profile, 0.0, 900.0) == 0.5


def test_silent_ratio_returns_none_outside_the_profile():
    profile = {"interval_seconds": 1.0, "levels": [0.5, 0.0]}
    assert wf.silent_ratio(profile, 10.0, 12.0) is None
    assert wf.silent_ratio(profile, 1.0, 1.0) is None
    assert wf.silent_ratio(profile, -1.0, 1.0) is None


def test_level_peak_covers_at_least_one_bin():
    profile = {"interval_seconds": 1.0, "levels": [0.1, 0.9, 0.2]}
    assert wf.level_peak(profile, 0.0, 2.0) == 0.9
    # end-start が interval 未満でも空区間にせず1binは見る
    assert wf.level_peak(profile, 1.0, 1.2) == 0.9


def test_level_peak_returns_none_for_unusable_windows():
    profile = {"interval_seconds": 1.0, "levels": [0.1, 0.9]}
    assert wf.level_peak(profile, 5.0, 6.0) is None
    assert wf.level_peak(profile, -1.0, 1.0) is None
    assert wf.level_peak(profile, 1.0, 0.5) is None


async def test_ensure_waveform_rejects_non_positive_buckets(make_recording):
    _, mp4 = make_recording()
    with pytest.raises(RuntimeError):
        await wf.ensure_waveform(mp4, buckets=0)


async def test_ensure_waveform_requires_an_existing_file(tmp_root):
    with pytest.raises(RuntimeError):
        await wf.ensure_waveform(tmp_root / "missing.mp4")


def test_decode_command_maps_only_audio_and_resamples(monkeypatch, make_recording):
    _, mp4 = make_recording()
    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        raise OSError("blocked")

    monkeypatch.setattr(wf.subprocess, "Popen", fake_popen)
    with pytest.raises(RuntimeError):
        wf._decode_fine_peaks(mp4)

    args = captured["args"]
    assert args[0] == "ffmpeg"
    assert "-vn" in args and args[args.index("-map") + 1] == "0:a:0"
    assert args[args.index("-af") + 1] == wf._RESAMPLE_FILTER
    assert args[args.index("-ar") + 1] == str(wf.SAMPLE_RATE)
    assert args[args.index("-ac") + 1] == "1"
    assert args[args.index("-f") + 1] == "s16le"
    assert args[-1] == "-"


# --------------------------------------------------------------------------- clipper


@pytest.mark.parametrize("seconds,expected", [
    (0, "000000"),
    (-5, "000000"),
    (61, "000101"),
    (3661.9, "010101"),
    (360000, "1000000"),
])
def test_hhmmss(seconds, expected):
    assert clipper._hhmmss(seconds) == expected


def test_clip_path_lands_in_the_shared_clips_dir(make_recording, tmp_root):
    stem, mp4 = make_recording(streamer="some.user_x")
    out = clipper.clip_path(mp4, 10.0, 70.0)
    assert out.parent == layout.clips_dir(tmp_root, "some.user_x")
    assert out.name == f"{stem}_000010-000110.mp4"


def test_clip_path_sanitises_the_label_but_keeps_japanese(make_recording):
    _, mp4 = make_recording()
    out = clipper.clip_path(mp4, 0, 1, label='神回/ばと:る')
    assert out.name.endswith("_神回_ばと_る.mp4")


def test_clip_path_drops_a_label_that_sanitises_to_nothing(make_recording):
    _, mp4 = make_recording()
    plain = clipper.clip_path(mp4, 0, 1)
    assert clipper.clip_path(mp4, 0, 1, label="  ...  ") == plain


def test_clip_path_truncates_a_long_label(make_recording):
    _, mp4 = make_recording()
    out = clipper.clip_path(mp4, 0, 1, label="x" * 100)
    assert out.name.endswith("_" + "x" * 40 + ".mp4")


def _patch_clip_ffmpeg(monkeypatch, captured, duration=None):
    monkeypatch.setattr(clipper, "ffmpeg_available", lambda: True)

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = list(cmd)
        out = clipper.Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00" * 8)

        async def communicate():
            return b"", b""

        return types.SimpleNamespace(returncode=0, communicate=communicate, kill=lambda: None)

    monkeypatch.setattr(clipper.asyncio, "create_subprocess_exec", fake_exec)

    async def fake_duration(path):
        return duration

    monkeypatch.setattr(clipper, "_duration_seconds", fake_duration)


async def test_make_clip_puts_the_copy_seek_before_the_input(monkeypatch, make_recording):
    """出力側-ssはkeyframeが来るまでvideo packetを捨て、GOPより短い範囲では映像が1 frameも
    残らない(keyframe間隔17.67秒の実録画で音声のみのmp4になることを確認済み)。"""
    _, mp4 = make_recording()
    captured = {}
    _patch_clip_ffmpeg(monkeypatch, captured)

    info = await clipper.make_clip(mp4, 12.0, 23.6)
    cmd = captured["cmd"]
    assert cmd.index("-ss") < cmd.index("-i")
    assert cmd[cmd.index("-ss") + 1] == "12.000"
    assert cmd[cmd.index("-to") + 1] == "23.600"
    assert "-copyts" in cmd
    assert "-t" not in cmd
    assert "-c" in cmd and cmd[cmd.index("-c") + 1] == "copy"
    assert cmd[cmd.index("-avoid_negative_ts") + 1] == "make_zero"
    assert info["encoder"] == "copy"
    assert info["precise"] is False
    assert info["normalized"] is False
    assert info["bytes"] == 8


async def test_make_clip_copy_disables_accurate_seek(monkeypatch, make_recording):
    """accurate seekは復号するstreamだけを-ssまで捨てる。音声を再encodeする経路で有効だと、
    映像はkeyframeから・音声は要求位置から始まりGOPぶんずれる(実測3.5秒)。"""
    _, mp4 = make_recording()
    captured = {}
    _patch_clip_ffmpeg(monkeypatch, captured)

    await clipper.make_clip(mp4, 12.0, 23.6)
    cmd = captured["cmd"]
    assert "-noaccurate_seek" in cmd
    assert cmd.index("-noaccurate_seek") < cmd.index("-i")


async def test_make_clip_normalize_also_disables_accurate_seek(monkeypatch, make_recording):
    _, mp4 = make_recording()
    captured = {}
    _patch_clip_ffmpeg(monkeypatch, captured)
    monkeypatch.setattr(clipper.audio_norm, "probe_sample_rate", lambda src: 48000)

    await clipper.make_clip(
        mp4, 0.0, 4.0,
        normalize={"target_lufs": -14.0, "true_peak": -1.5, "bitrate_kbps": 192},
    )
    cmd = captured["cmd"]
    assert "-noaccurate_seek" in cmd
    assert cmd.index("-noaccurate_seek") < cmd.index("-i")


async def test_make_clip_reports_the_keyframe_lead(monkeypatch, make_recording):
    """stream copyは直前のkeyframeから始まるので、実尺は要求より長く実開始は手前になる。"""
    _, mp4 = make_recording()
    _patch_clip_ffmpeg(monkeypatch, {}, duration=16.4)

    info = await clipper.make_clip(mp4, 200.0, 210.0)
    assert info["keyframe_lead_seconds"] == 6.4
    assert info["actual_start_seconds"] == 193.6
    assert info["start"] == 200.0


async def test_make_clip_precise_has_no_keyframe_lead(monkeypatch, make_recording):
    _, mp4 = make_recording()
    _patch_clip_ffmpeg(monkeypatch, {}, duration=10.0)

    async def fake_encoder(codec):
        return "libx264"

    monkeypatch.setattr(clipper, "video_encoder_name", fake_encoder)
    info = await clipper.make_clip(mp4, 200.0, 210.0, precise=True)
    assert info["keyframe_lead_seconds"] is None
    assert info["actual_start_seconds"] == 200.0


async def test_make_clip_does_not_warn_about_the_keyframe_lead(monkeypatch, make_recording,
                                                               caplog):
    """前へ伸びるのはstream copyの正常な結果。これを警告にすると、本来拾いたい
    「音声filterが尺を変えた」異常が毎回の警告に埋もれる。"""
    _, mp4 = make_recording()
    _patch_clip_ffmpeg(monkeypatch, {}, duration=40.0)

    with caplog.at_level("WARNING", logger="tictok.media.clipper"):
        await clipper.make_clip(mp4, 200.0, 210.0)
    assert "duration_mismatch" not in caplog.text


async def test_make_clip_still_warns_when_the_output_is_short(monkeypatch, make_recording,
                                                              caplog):
    _, mp4 = make_recording()
    _patch_clip_ffmpeg(monkeypatch, {}, duration=3.0)

    with caplog.at_level("WARNING", logger="tictok.media.clipper"):
        await clipper.make_clip(mp4, 200.0, 210.0)
    assert "duration differs from the request" in caplog.text


async def test_make_clip_precise_reencodes_video(monkeypatch, make_recording):
    _, mp4 = make_recording()
    captured = {}
    _patch_clip_ffmpeg(monkeypatch, captured)

    async def fake_encoder(codec):
        return "libx264"

    monkeypatch.setattr(clipper, "video_encoder_name", fake_encoder)

    info = await clipper.make_clip(mp4, 5.0, 6.5, precise=True)
    cmd = captured["cmd"]
    assert info["encoder"] == "libx264"
    assert "copy" not in cmd
    assert cmd[cmd.index("-t") + 1] == "1.500"
    assert cmd.index("-i") < cmd.index("-ss")


async def test_make_clip_normalize_copies_video_and_reencodes_audio(monkeypatch, make_recording):
    _, mp4 = make_recording()
    captured = {}
    _patch_clip_ffmpeg(monkeypatch, captured)
    monkeypatch.setattr(clipper.audio_norm, "probe_sample_rate", lambda src: 48000)

    info = await clipper.make_clip(
        mp4, 0.0, 4.0,
        normalize={"target_lufs": -14.0, "true_peak": -1.5, "bitrate_kbps": 192},
    )
    cmd = captured["cmd"]
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert cmd[cmd.index("-ar") + 1] == "48000"
    assert info["normalized"] is True


@pytest.mark.requires_ffmpeg
async def test_make_clip_keeps_video_when_the_range_is_shorter_than_a_gop(make_recording):
    """このbugの本体。GOPより短い範囲を出力側-ssで切ると映像が1 frameも残らないため、
    実frameを数える形でしか守れない(commandの形からは見えない)。"""
    # GOP 300 frame = 10秒。要求4秒はGOPより短いので、旧実装では映像が0 frameになる。
    _, mp4 = make_recording()
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=40",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=40",
         "-c:v", "libx264", "-g", "300", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(mp4)],
        check=True, stdin=subprocess.DEVNULL)

    info = await clipper.make_clip(mp4, 12.0, 16.0)
    counted = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", info["path"]],
        capture_output=True, text=True, check=True).stdout.strip().splitlines()[0]
    assert int(counted) > 0
    # 直前のkeyframeは10秒地点なので、要求4秒に対し2秒ぶん手前から始まる。
    assert info["keyframe_lead_seconds"] == pytest.approx(2.0, abs=0.3)
    assert info["actual_start_seconds"] == pytest.approx(10.0, abs=0.3)


async def test_make_clip_rejects_a_non_positive_range(monkeypatch, make_recording):
    _, mp4 = make_recording()
    _patch_clip_ffmpeg(monkeypatch, {})
    with pytest.raises(RuntimeError):
        await clipper.make_clip(mp4, 10.0, 10.0)


# ------------------------------------------------------------------------ thumbnails


def test_grid_caps_the_tile_count_for_long_recordings():
    grid = th._grid(3.9 * 3600, 1080, 1920)
    assert grid["count"] <= th.MAX_TILES
    assert grid["interval_seconds"] >= th.MIN_INTERVAL_SECONDS
    assert grid["columns"] == th.SPRITE_COLUMNS
    assert grid["rows"] * grid["columns"] >= grid["count"]


def test_grid_never_goes_below_the_minimum_interval():
    grid = th._grid(60.0, 1080, 1920)
    assert grid["interval_seconds"] == th.MIN_INTERVAL_SECONDS
    assert grid["count"] == 30


def test_grid_short_recording_yields_a_single_tile():
    grid = th._grid(1.0, 1080, 1920)
    assert grid["count"] == 1
    assert grid["columns"] == 1
    assert grid["rows"] == 1


def test_grid_tile_dimensions_are_even_and_follow_the_aspect():
    portrait = th._grid(600.0, 1080, 1920)
    assert portrait["tile_width"] == th.TILE_WIDTH
    assert portrait["tile_height"] % 2 == 0
    assert portrait["tile_height"] == 212

    landscape = th._grid(600.0, 1920, 1080)
    assert landscape["tile_height"] == 68


def test_grid_falls_back_to_the_default_aspect_without_a_height():
    grid = th._grid(600.0, 1080, 0)
    assert grid["tile_height"] == th._grid(600.0, 9, 16)["tile_height"]


def test_sprite_cache_requires_both_files_and_a_matching_signature(make_recording):
    _, mp4 = make_recording()
    signature = th._signature(mp4)
    assert th._cached(mp4, signature) is None

    th.sprite_path(mp4).parent.mkdir(parents=True, exist_ok=True)
    th.sprite_path(mp4).write_bytes(b"\xff\xd8")
    th._meta_path(mp4).write_text(
        json.dumps({"signature": signature, "sprite": {"count": 7}}), encoding="utf-8")
    assert th._cached(mp4, signature) == {"count": 7}

    stale = dict(signature, size=signature["size"] + 1)
    assert th._cached(mp4, stale) is None


def test_sprite_cache_survives_a_corrupt_meta_file(make_recording):
    _, mp4 = make_recording()
    th.sprite_path(mp4).parent.mkdir(parents=True, exist_ok=True)
    th.sprite_path(mp4).write_bytes(b"\xff\xd8")
    th._meta_path(mp4).write_text("{not json", encoding="utf-8")
    assert th._cached(mp4, th._signature(mp4)) is None


async def test_ensure_sprite_requires_an_existing_file(tmp_root):
    with pytest.raises(RuntimeError):
        await th.ensure_sprite(tmp_root / "nope.mp4")


def test_sprite_signature_covers_the_keyframe_decision(make_recording):
    """判定条件がsignatureに入っていないと、条件を直しても壊れたspriteが残り続ける。"""
    _, mp4 = make_recording()
    signature = th._signature(mp4)
    assert signature["keyframe_safety"] == th.KEYFRAME_SAFETY
    assert signature["keyframe_min_interval"] == th.KEYFRAME_ONLY_MIN_INTERVAL

    th.sprite_path(mp4).parent.mkdir(parents=True, exist_ok=True)
    th.sprite_path(mp4).write_bytes(b"\xff\xd8")
    th._meta_path(mp4).write_text(
        json.dumps({"signature": signature, "sprite": {"count": 7}}), encoding="utf-8")
    assert th._cached(mp4, signature) == {"count": 7}
    # 判定条件を変えたら作り直させる。
    assert th._cached(mp4, dict(signature, keyframe_safety=99.0)) is None


def _patch_keyframe_probe(monkeypatch, stdout=b"", returncode=0, captured=None):
    async def fake_exec(*cmd, **kwargs):
        if captured is not None:
            captured["cmd"] = list(cmd)

        async def communicate():
            return stdout, b""

        return types.SimpleNamespace(returncode=returncode, communicate=communicate,
                                     kill=lambda: None)

    monkeypatch.setattr(th.asyncio, "create_subprocess_exec", fake_exec)


async def test_max_keyframe_gap_ignores_the_window_boundaries(monkeypatch,
                                                              make_recording):
    """窓と窓の間の隙間を数えると、どの録画も「間隔が数百秒」になり常に通常decodeへ倒れる。"""
    _, mp4 = make_recording()
    # 窓1: 100,104,110 (最大6秒) / 窓2: 900,903 (最大3秒)。100→900の800秒は窓の切れ目。
    _patch_keyframe_probe(monkeypatch, b"100\n104\n110\n900\n903\n")
    assert await th._max_keyframe_gap(mp4, 1000.0) == pytest.approx(6.0)


async def test_max_keyframe_gap_samples_instead_of_scanning_the_whole_file(
        monkeypatch, make_recording):
    """全走査は利点とほぼ同額のcostになる(実測4.2秒 対 利点4.6秒)。"""
    _, mp4 = make_recording()
    captured = {}
    _patch_keyframe_probe(monkeypatch, b"10\n12\n", captured=captured)
    await th._max_keyframe_gap(mp4, 1000.0)
    cmd = captured["cmd"]
    assert cmd[cmd.index("-skip_frame") + 1] == "nokey"
    intervals = cmd[cmd.index("-read_intervals") + 1]
    assert len(intervals.split(",")) == th.KEYFRAME_PROBE_WINDOWS


async def test_max_keyframe_gap_returns_none_when_it_cannot_measure(monkeypatch,
                                                                    make_recording):
    _, mp4 = make_recording()
    _patch_keyframe_probe(monkeypatch, b"", returncode=1)
    assert await th._max_keyframe_gap(mp4, 1000.0) is None

    _patch_keyframe_probe(monkeypatch, b"100\n")
    assert await th._max_keyframe_gap(mp4, 1000.0) is None


def _patch_sprite_build(monkeypatch, duration, gap, captured):
    """gridの決定からffmpeg起動までを差し替え、decode modeの選択だけを見る。"""
    async def fake_probe(src):
        return duration, 720, 1280

    async def fake_gap(src, dur):
        captured["probed"] = True
        return gap

    monkeypatch.setattr(th, "_probe", fake_probe)
    monkeypatch.setattr(th, "_max_keyframe_gap", fake_gap)
    monkeypatch.setattr(th, "ffmpeg_available", lambda: True)

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = list(cmd)
        out = th.Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\xff\xd8")

        async def communicate():
            return b"", b""

        return types.SimpleNamespace(returncode=0, communicate=communicate,
                                     kill=lambda: None)

    monkeypatch.setattr(th.asyncio, "create_subprocess_exec", fake_exec)


async def test_sprite_uses_a_full_decode_when_keyframes_are_too_sparse(monkeypatch,
                                                                       make_recording):
    """この不具合の本体。実録画(尺3022秒→interval 11秒、実keyframe間隔 最大18.16秒)では
    keyframeがtile数ぶん無く、280 tile中67枚が誤った時刻の絵になっていた。"""
    _, mp4 = make_recording()
    captured = {}
    _patch_sprite_build(monkeypatch, duration=3022.0, gap=17.7, captured=captured)

    await th.ensure_sprite(mp4)
    assert captured["probed"] is True
    assert "-skip_frame" not in captured["cmd"]


async def test_sprite_keeps_keyframe_only_when_the_interval_is_wide_enough(monkeypatch,
                                                                           make_recording):
    """3時間級(interval 47〜95秒)は従来どおり速い経路のままであること。"""
    _, mp4 = make_recording()
    captured = {}
    _patch_sprite_build(monkeypatch, duration=13841.0, gap=17.7, captured=captured)

    await th.ensure_sprite(mp4)
    cmd = captured["cmd"]
    assert cmd[cmd.index("-skip_frame") + 1] == "nokey"


async def test_sprite_does_not_guess_when_the_keyframe_probe_fails(monkeypatch,
                                                                   make_recording):
    """測れないときに速い方を選ぶと、誤ったspriteが静かにcacheへ残る。"""
    _, mp4 = make_recording()
    captured = {}
    _patch_sprite_build(monkeypatch, duration=13841.0, gap=None, captured=captured)

    await th.ensure_sprite(mp4)
    assert "-skip_frame" not in captured["cmd"]


async def test_sprite_skips_the_probe_for_short_recordings(monkeypatch, make_recording):
    """intervalが小さい録画はどう測ってもkeyframeのみdecodeを選べないので、測定costを払わない。"""
    _, mp4 = make_recording()
    captured = {}
    _patch_sprite_build(monkeypatch, duration=600.0, gap=2.0, captured=captured)

    await th.ensure_sprite(mp4)
    assert "probed" not in captured
    assert "-skip_frame" not in captured["cmd"]


# ------------------------------------------------------------------------ gift_icons


@pytest.mark.parametrize("url,allowed", [
    ("https://p16.tiktokcdn.com/img/a.png", True),
    ("http://tiktokcdn.com/img/a.png", True),
    ("https://sf16.ibyteimg.com/x.webp", True),
    ("https://evil.com/a.png", False),
    ("https://eviltiktokcdn.com/a.png", False),
    ("https://p16.tiktokcdn.com.evil.net/a.png", False),
    ("ftp://p16.tiktokcdn.com/a.png", False),
    ("file:///etc/passwd", False),
    ("", False),
])
def test_gift_icon_host_allowlist(url, allowed):
    assert gi.GiftIconCache.is_allowed(url) is allowed


def test_gift_icon_has_rejects_zero_byte_files(tmp_path):
    cache = gi.GiftIconCache(tmp_path / "gift_icons")
    assert cache.has(0) is False
    assert cache.has(123) is False
    cache.path_for(123).write_bytes(b"")
    assert cache.has(123) is False
    cache.path_for(123).write_bytes(b"\x89PNG")
    assert cache.has(123) is True


async def test_gift_icon_persist_refuses_a_foreign_host(tmp_path):
    cache = gi.GiftIconCache(tmp_path / "gift_icons")
    assert await cache.persist(9, "https://evil.com/a.png") is False
    assert not cache.path_for(9).exists()


async def test_gift_icon_persist_skips_the_network_when_cached(tmp_path):
    cache = gi.GiftIconCache(tmp_path / "gift_icons")
    cache.path_for(9).write_bytes(b"\x89PNG")

    async def boom(*a, **k):
        raise AssertionError("network must not be touched")

    cache._client.get = boom
    assert await cache.persist(9, "https://p16.tiktokcdn.com/a.png") is True


async def test_persist_gift_list_indexes_names_and_merges(tmp_path, monkeypatch):
    cache = gi.GiftIconCache(tmp_path / "gift_icons")
    (tmp_path / "gift_icons" / "names.json").write_text(
        json.dumps({"Old": 1}), encoding="utf-8")

    persisted = []

    async def fake_persist(gift_id, url):
        persisted.append((gift_id, url))
        return True

    monkeypatch.setattr(cache, "persist", fake_persist)

    count = await cache.persist_gift_list({"gifts": [
        {"id": 5655, "name": "Rose", "image": {"url_list": ["https://p16.tiktokcdn.com/r.png"]}},
        {"id": 7, "name": "NoImage", "image": {}},
        {"name": "NoId", "image": {"url_list": ["https://p16.tiktokcdn.com/x.png"]}},
    ]})

    assert count == 1
    assert persisted == [(5655, "https://p16.tiktokcdn.com/r.png")]
    names = json.loads((tmp_path / "gift_icons" / "names.json").read_text(encoding="utf-8"))
    assert names == {"Old": 1, "Rose": 5655, "NoImage": 7}


# ----------------------------------------------------------------------- avatar_pool


def test_avatar_identity_ignores_rendition_and_signature():
    base = "https://p16.tiktokcdn.com/tos-a/7abc"
    a = f"{base}~tplv-tiktok-shrink:72:72.webp?x-signature=AAA"
    b = f"{base}~tplv-tiktok-shrink:1080:1080.jpeg?x-signature=BBB"
    other = "https://p16.tiktokcdn.com/tos-a/9zzz~tplv-tiktok-shrink:72:72.webp"
    assert ap._avatar_identity(a) == ap._avatar_identity(b)
    assert ap._avatar_identity(a) != ap._avatar_identity(other)


def test_avatar_identity_falls_back_to_the_whole_path():
    url = "https://p16.tiktokcdn.com/plain/avatar.jpeg?sig=1"
    assert ap._avatar_identity(url) == "/plain/avatar.jpeg"


@pytest.mark.parametrize("url,hint", [
    ("https://x.tiktokcdn.com/a~tplv-tiktok-shrink:72:72.webp", 72),
    ("https://x.tiktokcdn.com/a~tplv-tiktok-cropcenter:1080:1080.jpeg", 1080),
    ("https://x.tiktokcdn.com/a~tplv-x:100:200.jpeg", 200),
    ("https://x.tiktokcdn.com/a.jpeg", 0),
])
def test_url_res_hint(url, hint):
    assert ap._url_res_hint(url) == hint


def test_avatar_key_is_stable_and_distinct():
    assert ap.avatar_key("alice") == ap.avatar_key("alice")
    assert ap.avatar_key("alice") != ap.avatar_key("bob")
    assert len(ap.avatar_key("alice")) == 40


def test_needs_update_true_when_nothing_is_cached(tmp_path):
    pool = ap.AvatarPool(tmp_path / "avatars")
    url = "https://p16.tiktokcdn.com/tos/a~tplv-x:72:72.webp"
    assert pool.needs_update("alice", url) is True
    assert pool.needs_update("alice", "https://evil.com/a.png") is False
    assert pool.needs_update("", url) is False


def test_needs_update_backfills_meta_for_a_legacy_avatar(tmp_path, monkeypatch):
    monkeypatch.setattr(ap, "_image_size", lambda source: (72, 72))
    pool = ap.AvatarPool(tmp_path / "avatars")
    pool.path_for("alice").write_bytes(b"\x89PNG")
    url = "https://p16.tiktokcdn.com/tos/a~tplv-x:72:72.webp"

    assert pool.needs_update("alice", url) is False
    meta = json.loads(pool._meta_path("alice").read_text(encoding="utf-8"))
    assert meta == {"aid": ap._avatar_identity(url), "w": 72, "h": 72}


def test_needs_update_follows_a_higher_resolution_rendition(tmp_path, monkeypatch):
    monkeypatch.setattr(ap, "_image_size", lambda source: (72, 72))
    pool = ap.AvatarPool(tmp_path / "avatars")
    pool.path_for("alice").write_bytes(b"\x89PNG")
    big = "https://p16.tiktokcdn.com/tos/a~tplv-x:1080:1080.jpeg"

    assert pool.needs_update("alice", big) is True
    # legacy backfill must not have happened on the upgrade path
    assert not pool._meta_path("alice").exists()


def test_needs_update_ignores_a_mere_resign_but_follows_a_change(tmp_path):
    pool = ap.AvatarPool(tmp_path / "avatars")
    pool.path_for("alice").write_bytes(b"\x89PNG")
    url = "https://p16.tiktokcdn.com/tos/a~tplv-x:72:72.webp"
    pool._write_meta("alice", ap._avatar_identity(url), 72, 72)

    assert pool.needs_update("alice", url + "?x-signature=NEW") is False
    assert pool.needs_update(
        "alice", "https://p16.tiktokcdn.com/tos/a~tplv-x:1080:1080.jpeg") is True
    assert pool.needs_update(
        "alice", "https://p16.tiktokcdn.com/tos/zzz~tplv-x:72:72.webp") is True


def test_pool_get_returns_bytes_and_content_type(tmp_path):
    pool = ap.AvatarPool(tmp_path / "avatars")
    assert pool.get("alice") is None

    pool.path_for("alice").write_bytes(b"\x89PNG")
    assert pool.get("alice") == (b"\x89PNG", "image/jpeg")

    pool._type_path("alice").write_text("image/webp", encoding="utf-8")
    assert pool.get("alice") == (b"\x89PNG", "image/webp")

    pool.path_for("bob").write_bytes(b"")
    assert pool.get("bob") is None


def test_pool_migrates_legacy_avatars_without_clobbering(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    new = tmp_path / "avatars"
    new.mkdir()
    (legacy / "aaa.img").write_bytes(b"legacy-a")
    (legacy / "bbb.img").write_bytes(b"legacy-b")
    (new / "bbb.img").write_bytes(b"new-b")

    ap.AvatarPool(new, legacy_dir=legacy)

    assert (new / "aaa.img").read_bytes() == b"legacy-a"
    assert (new / "bbb.img").read_bytes() == b"new-b"
    assert (legacy / "bbb.img").exists()
    assert not (legacy / "aaa.img").exists()


async def test_pool_persist_skips_the_network_for_a_resigned_url(tmp_path):
    pool = ap.AvatarPool(tmp_path / "avatars")
    url = "https://p16.tiktokcdn.com/tos/a~tplv-x:72:72.webp"
    pool.path_for("alice").write_bytes(b"\x89PNG")
    pool._write_meta("alice", ap._avatar_identity(url), 72, 72)

    async def boom(*a, **k):
        raise AssertionError("network must not be touched")

    pool._client.get = boom
    assert await pool.persist("alice", url + "?x-signature=NEW") is True


async def test_pool_persist_refuses_a_foreign_host(tmp_path):
    pool = ap.AvatarPool(tmp_path / "avatars")
    assert await pool.persist("alice", "https://evil.com/a.png") is False
    assert not pool.path_for("alice").exists()
