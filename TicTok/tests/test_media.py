import contextlib
import io
import json
import math
import pathlib
import shutil
import subprocess
import types
from fractions import Fraction

import numpy as np
import pytest

from tictok.core import layout
from tictok.media import avatar_pool as ap
from tictok.media import clipper
from tictok.media import concat as concat_mod
from tictok.media import gift_icons as gi
from tictok.media import hls_source
from tictok.media import thumbnails as th
from tictok.media import waveform as wf
from tictok.record import recorder as rec


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


def test_display_peaks_fold_by_fixed_time_buckets():
    frames_per_bucket = int(round(wf.WAVE_BUCKET_SECONDS * 1000.0 / wf.FINE_FRAME_MS))
    fine = np.arange(frames_per_bucket * 3, dtype=np.float32)
    out = wf._display_peaks(fine)
    assert out.tolist() == [
        float(frames_per_bucket - 1),
        float(frames_per_bucket * 2 - 1),
        float(frames_per_bucket * 3 - 1),
    ]


def test_display_peaks_keep_a_trailing_partial_bucket():
    frames_per_bucket = int(round(wf.WAVE_BUCKET_SECONDS * 1000.0 / wf.FINE_FRAME_MS))
    fine = np.zeros(frames_per_bucket + 1, dtype=np.float32)
    fine[-1] = 7.0
    out = wf._display_peaks(fine)
    assert out.tolist() == [0.0, 7.0]


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
    result = {"buckets": 4, "bucket_seconds": wf.WAVE_BUCKET_SECONDS,
              "duration_seconds": 12.5, "peaks": [0.1, 0.2, 0.3, 1.0]}
    wf._store_cache(mp4, result)

    assert wf._load_cache(mp4) == result

    mp4.write_bytes(b"\x00" * 999)
    assert wf._load_cache(mp4) == {}


def test_waveform_cache_rejects_a_stale_schema_version(make_recording):
    _, mp4 = make_recording()
    wf._store_cache(mp4, {"buckets": 2, "bucket_seconds": wf.WAVE_BUCKET_SECONDS,
                          "duration_seconds": 1.0, "peaks": [0.0, 1.0]})
    path = wf.waveform_path(mp4)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["version"] = wf._CACHE_VERSION + 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert wf._load_cache(mp4) == {}


def test_waveform_cache_rejects_a_different_bucket_width(make_recording):
    # 旧schema(bucket個数固定)のcacheはbucket_secondsを持たない。読める形に畳み直さず
    # 作り直させる(境界がbucketの整数倍でない限り近似になり表示位置がずれるため)。
    _, mp4 = make_recording()
    wf._store_cache(mp4, {"buckets": 2, "bucket_seconds": wf.WAVE_BUCKET_SECONDS * 2,
                          "duration_seconds": 1.0, "peaks": [0.0, 1.0]})
    assert wf._load_cache(mp4) == {}


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
        wf._decode_fine_peaks(_file_source(mp4))

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


_CLIP_GOP = 2.0


def _patch_clip_ffmpeg(monkeypatch, captured, duration=None, landed=None):
    """ffmpegを差し替える。copy経路はTS中間を1つ経由する2段なので、両方のcommandを記録する。

    ``captured["cut"]`` が1段目(切り出し)、``captured["cmd"]`` が最後に走ったcommand。
    ``landed`` を渡すと、切り出しが着地した位置(media軸)をその値にする。"""
    monkeypatch.setattr(clipper, "ffmpeg_available", lambda: True)

    async def fake_exec(*cmd, **kwargs):
        captured.setdefault("cmds", []).append(list(cmd))
        captured["cmd"] = list(cmd)
        if "mpegts" in cmd:
            captured["cut"] = list(cmd)
        if "concat" in cmd:
            # 中間dirは呼び出し側が必ず消すので、list fileの中身はここで採っておく。
            captured["list"] = clipper.Path(
                cmd[cmd.index("-i") + 1]).read_text(encoding="utf-8")
        out = clipper.Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00" * 8)

        async def communicate():
            # 連結後の出力に映像と音声が在るかの確認probeへ、在る場合の答えを返す。
            if "stream=codec_type" in cmd:
                return "video\naudio\n".encode(), b""
            return b"", b""

        return types.SimpleNamespace(returncode=0, communicate=communicate, kill=lambda: None)

    monkeypatch.setattr(clipper.asyncio, "create_subprocess_exec", fake_exec)

    async def fake_duration(path):
        return duration

    monkeypatch.setattr(clipper, "_duration_seconds", fake_duration)

    # copy経路はconcat側の走査と実測を通る。keyframeは_CLIP_GOP間隔に並んでいるものとする。
    async def fake_codec(source):
        return "h264"

    async def fake_keys(source, at, window):
        first = math.ceil(max(0.0, at) / _CLIP_GOP) * _CLIP_GOP
        return [Fraction(first + _CLIP_GOP * i).limit_denominator(1000)
                for i in range(int(window / _CLIP_GOP) + 2)
                if first + _CLIP_GOP * i <= at + window + 1e-9]

    async def fake_spans(path, input_args=()):
        cut = captured["cut"]
        aim = float(cut[cut.index("-ss") + 1])
        until = float(cut[cut.index("-to") + 1])
        # mp4入力の着地は「-ss 以下で最後のkeyframe」(keyframesの実測)。
        first = math.floor(aim / _CLIP_GOP) * _CLIP_GOP if landed is None else landed
        aframe = 1024 / 48000
        spans = {"video": concat_mod.Span(first, until - 1 / 30, 1 / 30, 300),
                 "audio": concat_mod.Span(first - 0.5, until - aframe, aframe, 500)}
        if pathlib.Path(path).suffix == ".ts":
            return spans
        # 連結の**出力**は窓の始点が0点になる。実装は中間の中の要求位置をこの軸で出すので、
        # 寄せないと出力側-ssへ原本の絶対時刻を渡してしまう。
        inpoint = None
        for line in (captured.get("list") or "").splitlines():
            if line.startswith("inpoint "):
                inpoint = float(line.split()[1])
                break
        if inpoint is None:
            return spans
        return {kind: span._replace(first=span.first - inpoint, last=span.last - inpoint)
                for kind, span in spans.items()}

    # 連結の出力には映像packetが隙間なく並び、どれもkeyframeであるものとして返す。実装は
    # 各partの先頭keyframeが生きているかをこの列で確かめる。
    async def fake_packets(path):
        return [(i / 30, True) for i in range(18000)]

    monkeypatch.setattr(concat_mod, "_video_packets", fake_packets)

    monkeypatch.setattr(concat_mod, "video_codec", fake_codec)
    monkeypatch.setattr(concat_mod.keyframes, "video_keyframes", fake_keys)
    monkeypatch.setattr(concat_mod, "stream_spans", fake_spans)


async def test_make_clip_puts_the_copy_seek_before_the_input(monkeypatch, make_recording):
    """出力側-ssはkeyframeが来るまでvideo packetを捨て、GOPより短い範囲では映像が1 frameも
    残らない(keyframe間隔17.67秒の実録画で音声のみのmp4になることを確認済み)。"""
    _, mp4 = make_recording()
    captured = {}
    _patch_clip_ffmpeg(monkeypatch, captured)

    info = await clipper.make_clip(mp4, 12.0, 23.6)
    cut = captured["cut"]
    assert cut.index("-ss") < cut.index("-i")
    assert cut[cut.index("-to") + 1] == "23.600"
    assert "-copyts" in cut
    assert "-t" not in cut
    assert "-c" in cut and cut[cut.index("-c") + 1] == "copy"
    assert info["encoder"] == "copy"
    assert info["precise"] is False
    assert info["normalized"] is False
    assert info["bytes"] == 8


async def test_make_clip_copy_starts_at_or_before_the_request(monkeypatch,
                                                             make_recording):
    """``-ss`` へ要求時刻をそのまま渡すと、映像は要求の**直後**のkeyframeから始まる。

    実録画での実測: 30秒の切り出しが「先頭1.99秒は音声だけ(映像なし)」で出て、要求した頭
    0.7秒ぶんの映像を失っていた。しかも尺は要求どおりに見えるので前置きは0と報告された。"""
    _, mp4 = make_recording()
    _patch_clip_ffmpeg(monkeypatch, {}, duration=13.6)

    info = await clipper.make_clip(mp4, 13.0, 23.6)
    # keyframeは2秒間隔なので12.0へ着地する = 要求より1秒手前から始まる。
    assert info["keyframe_lead_seconds"] == pytest.approx(1.0, abs=0.01)
    assert info["actual_start_seconds"] == pytest.approx(12.0, abs=0.01)


async def test_make_clip_copy_trims_the_audio_only_head(monkeypatch, make_recording):
    """切り出しは中間TSを1つ経由し、mux段の窓でaudioだけの区間を落とす。"""
    _, mp4 = make_recording()
    captured = {}
    _patch_clip_ffmpeg(monkeypatch, captured)

    await clipper.make_clip(mp4, 12.0, 23.6)
    runs = [c for c in captured["cmds"] if c[0] == "ffmpeg"]
    assert len(runs) == 2, "切り出し + mux の2段"
    mux = runs[-1]
    assert mux[mux.index("-f") + 1] == "concat"
    assert "inpoint" in captured["list"] and "outpoint" in captured["list"]


async def test_make_clip_normalize_burns_the_audio_in_the_mux_step(monkeypatch,
                                                                  make_recording):
    """音量の正規化はmux段で焼く。切り出し段はstream copyのまま。"""
    _, mp4 = make_recording()
    captured = {}
    _patch_clip_ffmpeg(monkeypatch, captured)
    monkeypatch.setattr(clipper.audio_norm, "probe_sample_rate", lambda src: 48000)

    await clipper.make_clip(
        mp4, 0.0, 4.0,
        normalize={"target_lufs": -14.0, "true_peak": -1.5, "bitrate_kbps": 192},
    )
    cut, mux = [c for c in captured["cmds"] if c[0] == "ffmpeg"]
    assert cut[cut.index("-c") + 1] == "copy"
    assert "-c:v" in mux and mux[mux.index("-c:v") + 1] == "copy"
    assert "-c:a" in mux


async def test_make_clip_reports_the_keyframe_lead(monkeypatch, make_recording):
    """stream copyは直前のkeyframeから始まるので、実尺は要求より長く実開始は手前になる。

    前置きは**実測した着地**から出す。尺の差から逆算すると、audioだけが手前から入っている
    ぶん(実測で約2秒)まで前置きに数え、内容を失った回は0と報告してしまう。"""
    _, mp4 = make_recording()
    _patch_clip_ffmpeg(monkeypatch, {}, duration=16.4, landed=193.6)

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
    assert "切り抜きの尺が要求と異なります" in caplog.text


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
    # **原本を直接復号しない**。原本へ-ssを渡す形は、出力側だと所要時間が開始位置に比例し
    # (実測: 2.4時間の録画から60秒を切るのに開始60秒で2.95s、7200秒で49.71s)、入力側だと
    # HLSが前方のsegmentへ飛んで頭の映像を失う(開始5000秒で映像が1.96秒遅れて始まった)。
    # copy経路で粗く切った短い中間を再encodeするので、最後のcommandの入力は原本ではない。
    assert pathlib.Path(cmd[cmd.index("-i") + 1]).name == "rough.mp4"
    # 中間は要求より前置きぶん手前から始まるので、その分だけ出力側-ssで捨てる。前置きは
    # 「要求以前の最後のkeyframe」までなので、1 GOPを超えることはない。
    assert cmd.index("-i") < cmd.index("-ss")
    assert 0.0 <= float(cmd[cmd.index("-ss") + 1]) <= _CLIP_GOP
    # 粗い切り出し(TS中間経由のcopy)が先に走っている。
    assert any("mpegts" in c for c in captured["cmds"])


async def test_make_clip_normalize_copies_video_and_reencodes_audio(monkeypatch, make_recording):
    _, mp4 = make_recording()
    captured = {}
    _patch_clip_ffmpeg(monkeypatch, captured)
    monkeypatch.setattr(clipper.audio_norm, "probe_sample_rate", lambda src: 48000)

    info = await clipper.make_clip(
        mp4, 0.0, 4.0,
        normalize={"target_lufs": -14.0, "true_peak": -1.5, "bitrate_kbps": 192},
    )
    # 正規化はmux段(2段目)で焼く。1段目の切り出しはstream copyのまま。
    cmd = [c for c in captured["cmds"] if c[0] == "ffmpeg"][-1]
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


# ------------------------------------------------------------------------ smart cut
#
# 先頭GOPだけを再encodeし、残りは原本のpacketをそのまま複製して繋ぐ経路。ffmpegを起こさない
# testは「commandの形」と「縮退の判定」を、実ffmpegのtestは「成果物」を見る。

H264_PARAMS = {
    "video": {"codec_name": "h264", "width": 720, "height": 1280, "resolutions": 1,
              "pix_fmt": "yuv420p", "profile": "High", "level": 40},
    "audio": {"codec_name": "aac", "sample_rate": "44100", "channels": 1},
}


def _plain_source(path="src.mp4", input_args=(), media_offset=0.0):
    return hls_source.Source(clipper.Path(path), tuple(input_args), bool(input_args),
                             media_offset)


def test_smart_plan_joins_at_the_first_keyframe_after_the_start():
    keys = [Fraction(0), Fraction(5), Fraction(42)]
    k, boundary, degenerate = clipper._smart_plan(keys, 1.0, 10.0, 1 / 30)
    assert (k, degenerate) == (Fraction(5), None)
    assert boundary == 10.0, "次のkeyframeが範囲外なら終端を境界に使う"


def test_smart_plan_uses_the_next_keyframe_as_the_boundary():
    keys = [Fraction(5), Fraction(8), Fraction(42)]
    k, boundary, _ = clipper._smart_plan(keys, 1.0, 10.0, 1 / 30)
    assert (k, boundary) == (Fraction(5), Fraction(8))


def test_smart_plan_reports_single_gop_when_the_range_holds_no_keyframe():
    """縮退は失敗ではない。範囲が1 GOPに収まるなら全体を再encodeする以外に手が無い。"""
    k, boundary, degenerate = clipper._smart_plan([Fraction(0)], 7.0, 20.0, 1 / 30)
    assert (k, boundary, degenerate) == (None, None, "single_gop")


def test_smart_plan_reports_single_gop_when_the_next_keyframe_is_past_the_end():
    k, _, degenerate = clipper._smart_plan([Fraction(42)], 7.0, 20.0, 1 / 30)
    assert (k, degenerate) == (None, "single_gop")


def test_smart_plan_reports_start_on_keyframe_within_one_frame():
    """headが1 frameも作れない差なら、再encodeせずcopyだけで要求どおりのIN点になる。"""
    keys = [Fraction(5), Fraction(42)]
    k, _, degenerate = clipper._smart_plan(keys, 5.0 - 1 / 90, 20.0, 1 / 30)
    assert (k, degenerate) == (Fraction(5), "start_on_keyframe")


def test_smart_plan_keeps_a_head_that_is_at_least_one_frame():
    keys = [Fraction(5), Fraction(42)]
    k, _, degenerate = clipper._smart_plan(keys, 5.0 - 1 / 20, 20.0, 1 / 30)
    assert (k, degenerate) == (Fraction(5), None)


def test_smart_plan_joins_after_the_last_resolution_change():
    """切替より手前で接合すると、そのままcopyするtailが混在解像度になり連結できない。
    切替以降で接合すればtailは単一解像度で、切替を跨ぐheadは焼き直す側なので揃えられる。"""
    keys = [Fraction(0), Fraction(2), Fraction(4), Fraction(6), Fraction(8)]
    k, boundary, degenerate = clipper._smart_plan(keys, 1.0, 10.0, 1 / 30, floor=5.5)
    assert (k, boundary, degenerate) == (Fraction(6), Fraction(8), None)


def test_smart_plan_ignores_a_resolution_change_before_the_request():
    keys = [Fraction(0), Fraction(2), Fraction(4)]
    k, _, _ = clipper._smart_plan(keys, 1.0, 10.0, 1 / 30, floor=0.5)
    assert k == Fraction(2), "要求より手前の切替は接合点を動かさない"


def test_smart_plan_degenerates_when_the_change_is_at_the_end():
    """切替が範囲の終盤なら接合できるkeyframeが残らない。範囲全体を焼く縮退になる。"""
    keys = [Fraction(0), Fraction(2), Fraction(4)]
    k, _, degenerate = clipper._smart_plan(keys, 1.0, 5.0, 1 / 30, floor=4.5)
    assert (k, degenerate) == (None, "single_gop")


def test_profile_arg_maps_the_probe_spelling():
    assert clipper._profile_arg("h264", "High") == "high"
    assert clipper._profile_arg("h264", "Constrained Baseline") == "baseline"
    assert clipper._profile_arg("hevc", "Main 10") == "main10"


def test_profile_arg_rejects_an_unknown_profile():
    """推測して焼くと、連結の照合を通ったあとで復号できないfileになる。"""
    with pytest.raises(RuntimeError):
        clipper._profile_arg("h264", "Some Future Profile")
    with pytest.raises(RuntimeError):
        clipper._profile_arg("h264", None)


def _head_args(**kwargs):
    args = {"rough": clipper.Path("rough.mp4"), "params": H264_PARAMS, "lead": 1.0,
            "seconds": 4.0, "dst": clipper.Path("head.ts"), "encoder": "libx264",
            "quality": 23, "size": (320, 240)}
    args.update(kwargs)
    return clipper._head_args(args["rough"], args["params"], args["lead"], args["seconds"],
                              args["dst"], args["encoder"], args["quality"], args["size"])


def test_head_args_read_the_rough_intermediate_not_the_source():
    """原本へ-ssを渡す形はどちらの側でも壊れる(入力側はHLSが前方へ飛び、出力側は開始位置に
    比例して遅い)。粗く切った中間を読み、前置きだけを出力側-ssで捨てる。"""
    args = _head_args()
    assert args[args.index("-i") + 1] == "rough.mp4"
    assert args.index("-i") < args.index("-ss")
    assert args[args.index("-ss") + 1] == "1.000"
    assert args[args.index("-t") + 1] == "4.000"


def test_head_args_never_disable_accurate_seek():
    """headは両streamを復号するので、accurate seekのままで要求位置ちょうどから始まる。
    -noaccurate_seekを付けると先頭がkeyframeへ戻り、smart cutの目的そのものが消える。"""
    args = _head_args()
    assert "-noaccurate_seek" not in args
    assert "-copyts" not in args


def test_head_args_force_the_tail_resolution():
    """配信中に解像度が変わる範囲では、headがその切替を跨ぐ。tailの解像度で焼かないと
    混在解像度になり連結の照合で落ちる。"""
    args = _head_args(size=(720, 1280))
    assert args[args.index("-s") + 1] == "720x1280"


def test_head_args_reencode_audio_to_aac_at_the_source_rate():
    """GOP途中からcopyできる音声は無い。rate/channelが原本と違えば連結の照合で落ちる。"""
    args = _head_args()
    assert args[args.index("-c:a") + 1] == "aac"
    assert args[args.index("-ar") + 1] == "44100"
    assert args[args.index("-ac") + 1] == "1"


def test_head_args_match_the_source_video_parameters():
    args = _head_args()
    assert args[args.index("-pix_fmt") + 1] == "yuv420p"
    assert args[args.index("-profile:v") + 1] == "high"
    assert args[args.index("-level") + 1] == "40"
    assert args[-3:] == ["-f", "mpegts", "head.ts"]


def test_head_args_leave_the_level_to_the_check_for_hevc():
    """HEVCのgeneral_level_idcは30倍の別scaleで、ffprobeの値をそのまま渡せない。"""
    params = {"video": {**H264_PARAMS["video"], "codec_name": "hevc", "profile": "Main",
                        "level": 120},
              "audio": H264_PARAMS["audio"]}
    args = _head_args(params=params, encoder="libx265", quality=27)
    assert "-level" not in args
    assert args[args.index("-profile:v") + 1] == "main"


def test_head_args_strip_the_mpegts_mux_delay():
    args = _head_args()
    assert args[args.index("-muxdelay") + 1] == "0"
    assert args[args.index("-muxpreload") + 1] == "0"


def test_tail_args_keep_the_seek_in_the_media_axis():
    """-ssはffmpegがcontainer start_timeを足すので、media軸の秒をそのまま渡す(実測)。"""
    source = _plain_source("index.m3u8", ("-allowed_extensions", "ALL"), 1.402)
    args = clipper._tail_args(source, 6.5, 20.0, clipper.Path("tail.ts"), "h264")
    assert args[args.index("-ss") + 1] == "6.500"
    assert args.index("-ss") < args.index("-i")


def test_tail_args_add_the_media_offset_to_the_absolute_end():
    """-toは-copyts下でcontainer軸のtimestampと比べられる。足さないと尾がその分短くなる。"""
    source = _plain_source("index.m3u8", ("-allowed_extensions", "ALL"), 1.402)
    args = clipper._tail_args(source, 6.5, 20.0, clipper.Path("tail.ts"), "h264")
    assert args[args.index("-to") + 1] == "21.402"
    assert "-copyts" in args


def test_tail_args_copy_and_convert_to_annex_b():
    source = _plain_source("index.m3u8", ("-allowed_extensions", "ALL"), 1.402)
    args = clipper._tail_args(source, 6.5, 20.0, clipper.Path("tail.ts"), "h264")
    assert args[args.index("-c") + 1] == "copy"
    assert args[args.index("-bsf:v") + 1] == "h264_mp4toannexb"
    assert args[args.index("-muxdelay") + 1] == "0"
    assert args[-3:] == ["-f", "mpegts", "tail.ts"]


async def test_smart_encoder_rejects_the_libx264_fallback(monkeypatch):
    """video_encoder_nameは要求codecが出せないと黙ってlibx264を返す。それをheadに使うと
    head=H.264 / tail=HEVC になり、繋いだfileは後半が復号できない。"""
    async def fake_encoder(codec):
        return "libx264"

    monkeypatch.setattr(clipper, "video_encoder_name", fake_encoder)
    with pytest.raises(RuntimeError) as excinfo:
        await clipper._smart_encoder("hevc")
    assert "hevc" in str(excinfo.value)


async def test_smart_encoder_accepts_an_encoder_of_the_same_family(monkeypatch):
    async def fake_encoder(codec):
        return "h264_nvenc"

    monkeypatch.setattr(clipper, "video_encoder_name", fake_encoder)
    assert await clipper._smart_encoder("h264") == "h264_nvenc"


async def test_landing_seconds_reports_where_the_tail_started(monkeypatch):
    async def fake_first_packet(path):
        return Fraction(1201, 240), True

    monkeypatch.setattr(clipper.keyframes, "first_packet", fake_first_packet)
    landed = await clipper._landing_seconds(clipper.Path("t.ts"), 5.0, 0.0, 1 / 30, {})
    assert landed == pytest.approx(5.004, abs=1e-3)


async def test_landing_seconds_accepts_a_forward_landing(monkeypatch):
    """HLSは12%の確率で狙いと別のkeyframeへ着く。着いた先も実在のkeyframeなので、そこを
    接合点に採り直せば要求どおりのIN点は保てる。ここで失敗させていた頃は、実測で開始
    5,000秒のような位置がまるごと切り出せなかった。"""
    async def fake_first_packet(path):
        return Fraction(6789, 1000), True

    monkeypatch.setattr(clipper.keyframes, "first_packet", fake_first_packet)
    landed = await clipper._landing_seconds(clipper.Path("t.ts"), 5.0, 0.0, 1 / 30, {})
    assert landed == pytest.approx(6.789)


async def test_landing_seconds_subtracts_the_media_offset(monkeypatch):
    async def fake_first_packet(path):
        return Fraction(6402, 1000), True

    monkeypatch.setattr(clipper.keyframes, "first_packet", fake_first_packet)
    assert await clipper._landing_seconds(
        clipper.Path("t.ts"), 5.0, 1.402, 1 / 30, {}) == pytest.approx(5.0)


async def test_landing_seconds_rejects_an_empty_part(monkeypatch):
    """0 byte出力はffmpegの終了コードに出ない(Output file is empty)。ここで捕まえる。"""
    async def fake_first_packet(path):
        return None, False

    monkeypatch.setattr(clipper.keyframes, "first_packet", fake_first_packet)
    with pytest.raises(RuntimeError) as excinfo:
        await clipper._landing_seconds(clipper.Path("t.ts"), 5.0, 0.0, 1 / 30, {})
    assert "1 packet" in str(excinfo.value)


async def test_landing_seconds_rejects_a_non_keyframe_start(monkeypatch):
    """keyframeでない位置から始まるtailは、そこからstream copyしても復号できない。"""
    async def fake_first_packet(path):
        return Fraction(5), False

    monkeypatch.setattr(clipper.keyframes, "first_packet", fake_first_packet)
    with pytest.raises(RuntimeError):
        await clipper._landing_seconds(clipper.Path("t.ts"), 5.0, 0.0, 1 / 30, {})


async def test_make_clip_rejects_smart_with_precise(make_recording):
    _, mp4 = make_recording()
    with pytest.raises(RuntimeError):
        await clipper.make_clip(mp4, 1.0, 5.0, precise=True, smart=True)


async def test_make_clip_rejects_smart_with_normalize(make_recording):
    """切り出し段のA/V不揃いが未解決の間、この経路に正規化を足してはいけない。"""
    _, mp4 = make_recording()
    with pytest.raises(RuntimeError):
        await clipper.make_clip(
            mp4, 1.0, 5.0, smart=True,
            normalize={"target_lufs": -14.0, "true_peak": -1.5, "bitrate_kbps": 192})


async def test_make_clip_copy_reports_its_mode(monkeypatch, make_recording):
    _, mp4 = make_recording()
    _patch_clip_ffmpeg(monkeypatch, {})
    info = await clipper.make_clip(mp4, 12.0, 23.6)
    assert info["mode"] == "copy"


# --- 実ffmpeg。commandの形が正しくても成果物が壊れることはあるので、出来たfileを見る ---

FPS = 30
FRAME = 1.0 / FPS
# keyframeをこの3点に固定した素材を使う。間隔37秒は実録画で確認された最大値に相当し、
# 「範囲が1 GOPに収まる」縮退も同じ素材で作れる。
LONG_GOP_KEYS = (0.0, 5.0, 42.0)


@pytest.fixture(scope="module")
def long_gop_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("longgop") / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=%d:duration=60" % FPS,
         "-f", "lavfi", "-i", "sine=frequency=440:duration=60",
         "-c:v", "libx264", "-force_key_frames", "0,5,42", "-sc_threshold", "0",
         "-g", "9999", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
        check=True, stdin=subprocess.DEVNULL)
    return path


@pytest.fixture
def long_gop_recording(long_gop_file, make_recording):
    _, mp4 = make_recording()
    shutil.copyfile(long_gop_file, mp4)
    return mp4


def _video_packets(path):
    """``[(pts_time, size, keyframeか), ...]``。pts不明のpacketは落とす。"""
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "packet=pts_time,size,flags", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL)
    rows = []
    for line in completed.stdout.splitlines():
        parts = line.strip().split(",")
        if len(parts) < 3:
            continue
        try:
            rows.append((float(parts[0]), int(parts[1]), parts[2].startswith("K")))
        except ValueError:
            continue
    return sorted(rows)


def _join_keyframe(rows, head_seconds):
    """接合点のkeyframeの時刻。

    「0の次のkeyframe」では見つからない: headの再encodeはlibx264自身のIDRも作る
    (実測で8.33秒間隔)。head尺から接合点を狙って一番近いkeyframeを採る。"""
    target = rows[0][0] + head_seconds
    return min((t for t, _, is_key in rows if is_key), key=lambda t: abs(t - target))


# 出力の先頭ptsと接合点は、要求から音声のぶんだけ後ろへずれる。切り分けの実測: 同じ素材を
# **映像だけ**で切って繋ぐと先頭ptsは 0.000000、接合点は 4.000000 でぴったり合う。音声を
# 含めると先頭 +0.023秒、接合点 +0.094秒になる。AAC frameが1024 sample(44.1kHzで23.2ms)の
# 量子化しかできず、headの音声が映像より1 frame長く終わるため、concat demuxerがその差だけ
# 後続を後ろへ置くことによる。doc/CLIP_TIMEBASE.md §6 の「切り出し段のA/V不揃い」と同根で、
# ここでは直さない(映像の側は上の実測どおり厳密である)。
AUDIO_SLACK = 0.15
# 尾はstream copyの粒度に留まる。実測の伸びは映像で2 frame、音声を含めて最大0.23秒。
TAIL_SLACK = 0.3


@pytest.mark.requires_ffmpeg
async def test_smart_cut_starts_exactly_at_the_request(long_gop_recording):
    """copyでは要求の4秒手前(keyframe 5.0の代わりに1.0)から始まる範囲を、要求どおりに切る。"""
    info = await clipper.make_clip(long_gop_recording, 1.0, 10.0, smart=True)

    assert info["mode"] == "smart"
    assert info["degenerate"] is None
    assert info["keyframe_lead_seconds"] == 0.0
    assert info["actual_start_seconds"] == 1.0
    assert info["join_seconds"] == 5.0
    assert info["head_seconds"] == 4.0
    assert info["copied_seconds"] == 5.0
    assert info["normalized"] is False

    rows = _video_packets(info["path"])
    assert rows[0][2], "先頭はkeyframeでなければならない"
    assert 0.0 <= rows[0][0] <= AUDIO_SLACK, "先頭ptsはほぼ0(音声のぶんだけ後ろ)"
    assert _join_keyframe(rows, 4.0) - rows[0][0] == pytest.approx(4.0, abs=AUDIO_SLACK)
    assert info["output_duration_seconds"] >= 9.0 - FRAME, "要求より短くしてはいけない"
    assert info["output_duration_seconds"] == pytest.approx(9.0, abs=TAIL_SLACK)


@pytest.mark.requires_ffmpeg
async def test_smart_cut_copies_the_tail_untouched(long_gop_recording):
    """尾が本当にcopyであること。

    packet sizeの**完全一致では見られない**: TS中間を経由するので、mpegts muxerが各packetへ
    AUD NALを足し(実測+6 byte)、``h264_mp4toannexb`` がIDRへSPS/PPSをin-bandで付ける
    (実測+45 byte)。原本のcompressed dataがそのままなら差は**packetごとに同じ定数**になり、
    再encodeが混ざれば定数にはならない(size列そのものが別物になる)。

    両端のpacketは定数から外れるので中身だけを見る: 先頭はin-bandのSPS/PPSぶん、末尾は複製の
    終端に付くNALぶん(実測+1246 byte)大きい。"""
    info = await clipper.make_clip(long_gop_recording, 1.0, 10.0, smart=True)

    out_rows = _video_packets(info["path"])
    join = _join_keyframe(out_rows, info["head_seconds"])
    src_sizes = [size for t, size, _ in _video_packets(long_gop_recording)
                 if t >= LONG_GOP_KEYS[1] - FRAME / 2]
    out_sizes = [size for t, size, _ in out_rows if t >= join - FRAME / 2]
    shared = min(len(src_sizes), len(out_sizes))
    assert shared >= 100, "比較できるpacketが足りない"

    deltas = [out - src for out, src in zip(out_sizes[1:shared - 1], src_sizes[1:shared - 1])]
    assert len(deltas) >= 100
    assert len(set(deltas)) == 1, f"packetごとの差が一定でない: {sorted(set(deltas))[:8]}"
    assert 0 <= deltas[0] <= 32, f"container側の付加分としては大きすぎる: {deltas[0]}"
    assert 0 < out_sizes[0] - src_sizes[0] < 200, "IDRの差はin-bandのSPS/PPSぶん"


@pytest.mark.requires_ffmpeg
async def test_smart_cut_join_decodes_without_errors(long_gop_recording):
    """headとtailでSPS/PPSが食い違うと、接合の直後だけ復号errorが出る。"""
    info = await clipper.make_clip(long_gop_recording, 1.0, 10.0, smart=True)
    join = _join_keyframe(_video_packets(info["path"]), info["head_seconds"])

    completed = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", "%.3f" % max(0.0, join - 1.0), "-t", "2.0",
         "-i", info["path"], "-f", "null", "-"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert completed.returncode == 0
    assert completed.stderr.strip() == ""


@pytest.mark.requires_ffmpeg
async def test_smart_cut_reencodes_the_whole_range_inside_one_gop(long_gop_recording):
    """縮退case。[7,20)はkeyframe 5.0と42.0の間に収まるので接合点が無い。"""
    info = await clipper.make_clip(long_gop_recording, 7.0, 20.0, smart=True)

    assert info["degenerate"] == "single_gop"
    assert info["join_seconds"] is None
    assert info["copied_seconds"] == 0.0
    assert info["head_seconds"] == 13.0
    assert info["encoder"] != "copy"
    # 全編再encodeなので尺はframe精度で合う(copyの粒度が入らない唯一のcase)。
    assert info["output_duration_seconds"] == pytest.approx(13.0, abs=2 * FRAME)
    rows = _video_packets(info["path"])
    assert 0.0 <= rows[0][0] <= AUDIO_SLACK


@pytest.mark.requires_ffmpeg
async def test_smart_cut_skips_the_head_when_the_start_is_a_keyframe(long_gop_recording):
    """縮退case。要求INが既にkeyframe上なら、再encodeせずcopyだけで要求どおりになる。"""
    info = await clipper.make_clip(long_gop_recording, 5.0, 20.0, smart=True)

    assert info["degenerate"] == "start_on_keyframe"
    assert info["head_seconds"] == 0.0
    assert info["join_seconds"] == 5.0
    assert info["copied_seconds"] == 15.0
    assert info["encoder"] == "copy"
    assert info["keyframe_lead_seconds"] == 0.0
    rows = _video_packets(info["path"])
    assert rows[0][2] and 0.0 <= rows[0][0] <= AUDIO_SLACK
    assert info["output_duration_seconds"] >= 15.0 - FRAME
    assert info["output_duration_seconds"] == pytest.approx(15.0, abs=TAIL_SLACK)


@pytest.mark.slow
@pytest.mark.requires_ffmpeg
async def test_smart_cut_handles_a_37_second_gop(long_gop_recording):
    """実録画の最大GOP相当。headが35秒になっても接合点は原本のkeyframeちょうどに来る。"""
    info = await clipper.make_clip(long_gop_recording, 7.0, 45.0, smart=True)

    assert info["degenerate"] is None
    assert info["join_seconds"] == 42.0
    assert info["head_seconds"] == 35.0
    assert info["copied_seconds"] == 3.0
    out_rows = _video_packets(info["path"])
    join = _join_keyframe(out_rows, info["head_seconds"]) - out_rows[0][0]
    assert join == pytest.approx(35.0, abs=AUDIO_SLACK)
    assert info["output_duration_seconds"] >= 38.0 - FRAME
    assert info["output_duration_seconds"] == pytest.approx(38.0, abs=TAIL_SLACK)


@pytest.fixture(scope="module")
def long_gop_hls(long_gop_file, tmp_path_factory):
    """同じ素材のHLS playlist。``(playlist, container start_time)``。

    mp4を入力にするtestではcontainer start_timeが0なので、media軸とcontainer軸を混同する
    欠陥が現れない。TS/HLSは0始まりにならない(実測1.4667秒)ので、そこを通す。"""
    work = tmp_path_factory.mktemp("longgophls")
    playlist = work / "index.m3u8"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(long_gop_file), "-c", "copy",
         "-f", "hls", "-hls_time", "2", "-hls_list_size", "0",
         "-hls_segment_filename", str(work / "seg%05d.ts"), str(playlist)],
        check=True, stdin=subprocess.DEVNULL)
    offset = hls_source._container_start_time(playlist)
    assert offset > 0, "0始まりのHLSではこのtestの意味が無い"
    return playlist, offset


@pytest.mark.requires_ffmpeg
async def test_smart_cut_on_an_hls_source_keeps_both_time_axes(
        monkeypatch, long_gop_recording, long_gop_hls):
    """HLS入力(container start_time != 0)でも要求どおりの範囲になること。

    ``-ss`` はmedia軸・``-to`` はcontainer軸という食い違いがあり、``-to`` へ
    ``media_offset`` を足し忘れると尾がその分(実測1.4667秒)短くなる。mp4のtestでは
    ``media_offset`` が0なので、この欠陥はここでしか出ない。

    貸し出し(``ffmpeg_source``)だけを差し替える。録画の採用集合playlistを組む側は
    recorderの領分で、ここで見たいのは軸の扱いである。"""
    playlist, offset = long_gop_hls

    @contextlib.contextmanager
    def lease_hls(src, prefer_hls=False):
        yield hls_source.Source(playlist, tuple(rec.HLS_INPUT_ARGS), True, offset)

    monkeypatch.setattr(clipper.hls_source, "ffmpeg_source", lease_hls)
    info = await clipper.make_clip(long_gop_recording, 1.0, 10.0, smart=True)

    assert info["degenerate"] is None
    # media軸の原点はcontainer start_time = 全streamの最小で、音声が映像より23ms早く始まる
    # ため、原本で5.000秒のkeyframeはmedia軸では5.023秒になる(実測)。切り出しの要求も同じ
    # 軸なので破綻はしない。
    assert info["join_seconds"] == pytest.approx(5.0, abs=AUDIO_SLACK)
    assert info["output_duration_seconds"] >= 9.0 - FRAME, "-toのcontainer軸を落とすと短くなる"
    assert info["output_duration_seconds"] == pytest.approx(9.0, abs=TAIL_SLACK)
    rows = _video_packets(info["path"])
    assert _join_keyframe(rows, 4.0) - rows[0][0] == pytest.approx(4.0, abs=AUDIO_SLACK)


@pytest.mark.requires_ffmpeg
async def test_smart_cut_moves_the_join_to_where_the_tail_landed(
        monkeypatch, long_gop_recording):
    """着地が狙いと違っても、そこを接合点に採り直せば要求どおりのIN点は保てる。

    以前はここで失敗させていたため、着地が飛ぶ位置(実録画で12%)は切り出せなかった。
    headをその位置まで焼くので、報告する接合点と成果物は一致する。"""
    async def landed_late(path):
        return Fraction(6789, 1000), True

    monkeypatch.setattr(clipper.keyframes, "first_packet", landed_late)
    info = await clipper.make_clip(long_gop_recording, 1.0, 10.0, smart=True)

    assert info["join_seconds"] == pytest.approx(6.789, abs=1e-3)
    assert info["head_seconds"] == pytest.approx(5.789, abs=1e-3)
    assert info["actual_start_seconds"] == 1.0
    assert not list(clipper.Path(info["path"]).parent.glob(".smartcut-*")), "中間dirが残っている"


@pytest.mark.requires_ffmpeg
async def test_smart_cut_falls_back_to_encoding_when_the_tail_lands_outside(
        monkeypatch, long_gop_recording):
    """着地が範囲の外なら、そのtailを繋ぐと要求範囲と食い違う。範囲全体を焼いて応え、
    縮退したことを報告する(黙って別の範囲を返さない)。"""
    async def landed_outside(path):
        return Fraction(99), True

    monkeypatch.setattr(clipper.keyframes, "first_packet", landed_outside)
    info = await clipper.make_clip(long_gop_recording, 1.0, 10.0, smart=True)

    assert info["degenerate"] == "tail_landed_outside"
    assert info["join_seconds"] is None
    assert info["copied_seconds"] == 0.0
    assert info["head_seconds"] == pytest.approx(9.0)
    assert info["output_duration_seconds"] == pytest.approx(9.0, abs=TAIL_SLACK)


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


async def test_keyframe_probe_uses_absolute_window_bounds(monkeypatch):
    """窓は ``開始%終了`` で渡す。

    尺で書く ``開始%+尺`` は実HLSに混ざるpts=N/Aのpacketで打ち切られ、0 frameしか返らない
    (実測: 3.1時間の録画で 0 frame 対 128 frame)。0 frameは「測れなかった」と同じNoneに
    化けて全frame decodeへ倒れるため、形式を誤っても壊れて見えず、遅くなるだけになる。"""
    captured = {}

    async def fake_run(args, **kwargs):
        captured["args"] = [str(a) for a in args]
        return types.SimpleNamespace(ok=True, returncode=0, stderr="",
                                     stdout="1.0\n3.0\n5.0\n")

    monkeypatch.setattr(th.ffprobe, "run", fake_run)
    source = types.SimpleNamespace(path=pathlib.Path("curated.m3u8"), input_args=())

    assert await th._max_keyframe_gap(source, 3600.0) == 2.0

    args = captured["args"]
    intervals = args[args.index("-read_intervals") + 1]
    assert "%+" not in intervals
    windows = intervals.split(",")
    assert len(windows) == th.KEYFRAME_PROBE_WINDOWS
    for window in windows:
        start, end = window.split("%")
        assert float(end) - float(start) == pytest.approx(th.KEYFRAME_PROBE_SPAN_SECONDS)


async def test_keyframe_probe_reports_none_when_nothing_was_read(monkeypatch):
    """1 frameも読めなければ推測せずNone。全decodeは遅いだけで、誤ったkeyframe-onlyは
    絵が複製されたspriteをcacheへ焼き付ける。"""
    async def fake_run(args, **kwargs):
        return types.SimpleNamespace(ok=True, returncode=0, stderr="", stdout="")

    monkeypatch.setattr(th.ffprobe, "run", fake_run)
    source = types.SimpleNamespace(path=pathlib.Path("curated.m3u8"), input_args=())
    assert await th._max_keyframe_gap(source, 3600.0) is None


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


def _file_source(path):
    """mp4をそのまま読むときのSource。probeはこの形しか受け取らない(HLSでは
    ``-i`` の前にdemuxer optionが要るため、pathだけでは足りない)。"""
    return hls_source.Source(th.Path(path), (), False)


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
    assert await th._max_keyframe_gap(_file_source(mp4), 1000.0) == pytest.approx(6.0)


async def test_max_keyframe_gap_samples_instead_of_scanning_the_whole_file(
        monkeypatch, make_recording):
    """全走査は利点とほぼ同額のcostになる(実測4.2秒 対 利点4.6秒)。"""
    _, mp4 = make_recording()
    captured = {}
    _patch_keyframe_probe(monkeypatch, b"10\n12\n", captured=captured)
    await th._max_keyframe_gap(_file_source(mp4), 1000.0)
    cmd = captured["cmd"]
    assert cmd[cmd.index("-skip_frame") + 1] == "nokey"
    intervals = cmd[cmd.index("-read_intervals") + 1]
    assert len(intervals.split(",")) == th.KEYFRAME_PROBE_WINDOWS


async def test_max_keyframe_gap_returns_none_when_it_cannot_measure(monkeypatch,
                                                                    make_recording):
    _, mp4 = make_recording()
    _patch_keyframe_probe(monkeypatch, b"", returncode=1)
    assert await th._max_keyframe_gap(_file_source(mp4), 1000.0) is None

    _patch_keyframe_probe(monkeypatch, b"100\n")
    assert await th._max_keyframe_gap(_file_source(mp4), 1000.0) is None


def _patch_sprite_build(monkeypatch, duration, gap, captured):
    """gridの決定からffmpeg起動までを差し替え、decode modeの選択だけを見る。"""
    async def fake_duration(source):
        return duration

    async def fake_widest(source):
        return 720, 1280

    async def fake_gap(source, dur):
        captured["probed"] = True
        return gap

    monkeypatch.setattr(th, "_probe_duration", fake_duration)
    monkeypatch.setattr(th, "_widest", fake_widest)
    monkeypatch.setattr(th, "_max_keyframe_gap", fake_gap)
    monkeypatch.setattr(th, "ffmpeg_available", lambda: True)

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = list(cmd)
        out = th.Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\xff\xd8")

        async def communicate():
            # 連結後の出力に映像と音声が在るかの確認probeへ、在る場合の答えを返す。
            if "stream=codec_type" in cmd:
                return "video\naudio\n".encode(), b""
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


async def test_sprite_forbids_the_filter_graph_from_being_rebuilt(monkeypatch,
                                                                  make_recording):
    """解像度が変わるとffmpegはgraphを作り直し、蓄積型の ``tile`` が貯めた分を捨てる。
    入力optionなので ``-i`` より前に無ければ効かない。"""
    _, mp4 = make_recording()
    captured = {}
    _patch_sprite_build(monkeypatch, duration=600.0, gap=2.0, captured=captured)

    await th.ensure_sprite(mp4)
    cmd = captured["cmd"]
    assert cmd[cmd.index("-reinit_filter") + 1] == "0"
    assert cmd.index("-reinit_filter") < cmd.index("-i")


def test_sprite_signature_covers_the_graph_reinit_decision(make_recording):
    """既存のspriteは寸法もtile数も正常なので、鍵を変えないと壊れたcacheが残り続ける。"""
    _, mp4 = make_recording()

    assert th._signature(mp4)["graph_reinit"] is False


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
