import subprocess
import types

import pytest

from tictok.core import layout
from tictok.media import reel


def _streams(codec="h264", width=720, height=1280, pix_fmt="yuv420p",
             profile="Main", level=31, sample_rate="48000", channels=2):
    return {
        "video": {"codec_name": codec, "width": width, "height": height,
                  "pix_fmt": pix_fmt, "profile": profile, "level": level},
        "audio": {"codec_name": "aac", "sample_rate": sample_rate, "channels": channels},
    }


def _patch_reel_ffmpeg(monkeypatch, captured, streams=None, durations=None):
    """ffmpeg / ffprobe を差し替え、実行されたcommandだけを記録する。"""
    monkeypatch.setattr(reel, "ffmpeg_available", lambda: True)

    async def fake_probe(src):
        return (streams or {}).get(reel.Path(src).name) or _streams()

    monkeypatch.setattr(reel, "_probe_streams", fake_probe)

    async def fake_exec(*cmd, **kwargs):
        captured.setdefault("cmds", []).append(list(cmd))
        out = reel.Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00" * 8)

        async def communicate():
            return b"", b""

        return types.SimpleNamespace(returncode=0, communicate=communicate,
                                     kill=lambda: None)

    monkeypatch.setattr(reel.asyncio, "create_subprocess_exec", fake_exec)

    async def fake_duration(path):
        # 中間TSはkeyframe境界のぶん要求より長く出る。reel本体はその合計になる。
        return (durations or {}).get(reel.Path(path).suffix, 12.0)

    monkeypatch.setattr(reel, "_duration_seconds", fake_duration)


def test_reel_path_lands_in_the_shared_clips_dir(make_recording, tmp_root):
    stem, mp4 = make_recording(streamer="some.user_x")
    out = reel.reel_path(mp4, 10.0, 130.0, 3)
    assert out.parent == layout.clips_dir(tmp_root, "some.user_x")
    assert out.name == f"{stem}_reel3_000010-000210.mp4"


def test_reel_path_sanitises_the_label_but_keeps_japanese(make_recording):
    _, mp4 = make_recording()
    out = reel.reel_path(mp4, 0, 1, 2, label="神回/まとめ:")
    assert out.name.endswith("_神回_まとめ.mp4")


async def test_make_reel_rejects_an_empty_range_list(monkeypatch):
    monkeypatch.setattr(reel, "ffmpeg_available", lambda: True)
    with pytest.raises(RuntimeError, match="連結する範囲がありません"):
        await reel.make_reel([])


async def test_make_reel_rejects_a_backwards_range(monkeypatch, make_recording):
    _, mp4 = make_recording()
    monkeypatch.setattr(reel, "ffmpeg_available", lambda: True)
    with pytest.raises(RuntimeError, match="終了位置は開始位置より後"):
        await reel.make_reel([{"src": mp4, "start": 30.0, "end": 30.0}])


async def test_make_reel_rejects_a_missing_source(monkeypatch, tmp_path):
    monkeypatch.setattr(reel, "ffmpeg_available", lambda: True)
    with pytest.raises(RuntimeError, match="録画fileが存在しません"):
        await reel.make_reel([{"src": tmp_path / "gone.mp4", "start": 0, "end": 5}])


async def test_make_reel_cuts_with_input_seek_and_copyts(monkeypatch, make_recording):
    """出力側-ssはGOPより短い範囲の映像を丸ごと落とすので、必ず入力側-ss + -to + -copyts。"""
    _, mp4 = make_recording()
    captured = {}
    _patch_reel_ffmpeg(monkeypatch, captured)

    await reel.make_reel([{"src": mp4, "start": 30.0, "end": 45.0}])
    cut = captured["cmds"][0]
    assert cut.index("-ss") < cut.index("-i")
    assert cut[cut.index("-ss") + 1] == "30.000"
    assert cut[cut.index("-to") + 1] == "45.000"
    assert "-copyts" in cut
    assert cut[cut.index("-c") + 1] == "copy"
    assert cut[cut.index("-bsf:v") + 1] == "h264_mp4toannexb"
    assert cut[cut.index("-f") + 1] == "mpegts"


async def test_make_reel_concatenates_the_parts_in_the_given_order(monkeypatch,
                                                                   make_recording):
    _, mp4 = make_recording()
    captured = {}
    _patch_reel_ffmpeg(monkeypatch, captured)

    result = await reel.make_reel([{"src": mp4, "start": 300.0, "end": 310.0},
                                   {"src": mp4, "start": 10.0, "end": 20.0}])
    concat = captured["cmds"][-1]
    assert concat[concat.index("-f") + 1] == "concat"
    assert concat[concat.index("-safe") + 1] == "0"
    assert concat[concat.index("-fflags") + 1] == "+genpts"
    assert concat[concat.index("-c") + 1] == "copy"
    assert concat[concat.index("-movflags") + 1] == "+faststart"
    # 時刻順へ並べ替えず、渡された順のまま繋ぐ。
    assert [part["start"] for part in result["parts"]] == [300.0, 10.0]


async def test_make_reel_reports_the_keyframe_lead(monkeypatch, make_recording):
    """stream copyはkeyframeでしか切れないので実尺は要求より長い。その差を返すこと。"""
    _, mp4 = make_recording()
    _patch_reel_ffmpeg(monkeypatch, {}, durations={".ts": 12.0, ".mp4": 24.0})

    result = await reel.make_reel([{"src": mp4, "start": 0.0, "end": 10.0},
                                   {"src": mp4, "start": 60.0, "end": 70.0}])
    assert [part["lead_seconds"] for part in result["parts"]] == [2.0, 2.0]
    assert result["requested_seconds"] == 20.0
    assert result["lead_seconds"] == 4.0
    assert result["output_duration_seconds"] == 24.0


async def test_make_reel_removes_the_intermediate_workdir(monkeypatch, make_recording,
                                                          tmp_root):
    _, mp4 = make_recording()
    _patch_reel_ffmpeg(monkeypatch, {})

    result = await reel.make_reel([{"src": mp4, "start": 0.0, "end": 10.0}])
    clips = layout.clips_dir(tmp_root, layout.streamer_of(mp4.stem))
    assert reel.Path(result["path"]).is_file()
    assert not [p for p in clips.iterdir() if p.is_dir()]


async def test_make_reel_refuses_sources_with_different_resolutions(monkeypatch,
                                                                    make_recording):
    _, first = make_recording()
    _, second = make_recording()
    _patch_reel_ffmpeg(monkeypatch, {}, streams={second.name: _streams(width=640)})

    with pytest.raises(RuntimeError, match="幅 720 と 640"):
        await reel.make_reel([{"src": first, "start": 0.0, "end": 10.0},
                              {"src": second, "start": 0.0, "end": 10.0}])


async def test_make_reel_refuses_sources_with_different_h264_profiles(monkeypatch,
                                                                      make_recording):
    """実DBには同一session内でMainとHighが混ざる録画がある。mp4のavcCは1つしか持てないので、
    黙って繋ぐと後半が復号できない。"""
    _, first = make_recording()
    _, second = make_recording()
    _patch_reel_ffmpeg(monkeypatch, {}, streams={second.name: _streams(profile="High")})

    with pytest.raises(RuntimeError, match="profile Main と High"):
        await reel.make_reel([{"src": first, "start": 0.0, "end": 10.0},
                              {"src": second, "start": 0.0, "end": 10.0}])


async def test_make_reel_refuses_sources_with_different_audio_rates(monkeypatch,
                                                                    make_recording):
    _, first = make_recording()
    _, second = make_recording()
    _patch_reel_ffmpeg(monkeypatch, {},
                       streams={second.name: _streams(sample_rate="44100")})

    with pytest.raises(RuntimeError, match="sample rate 48000 と 44100"):
        await reel.make_reel([{"src": first, "start": 0.0, "end": 10.0},
                              {"src": second, "start": 0.0, "end": 10.0}])


async def test_make_reel_refuses_a_codec_without_an_annexb_filter(monkeypatch,
                                                                  make_recording):
    _, mp4 = make_recording()
    _patch_reel_ffmpeg(monkeypatch, {}, streams={mp4.name: _streams(codec="vp9")})

    with pytest.raises(RuntimeError, match="連結に対応していない映像codec"):
        await reel.make_reel([{"src": mp4, "start": 0.0, "end": 10.0}])


async def test_make_reel_deletes_the_output_when_the_concat_fails(monkeypatch,
                                                                  make_recording):
    _, mp4 = make_recording()
    _patch_reel_ffmpeg(monkeypatch, {})
    cut_exec = reel.asyncio.create_subprocess_exec

    async def failing(*cmd, **kwargs):
        if "concat" in cmd:
            async def communicate():
                return b"", b"boom"

            return types.SimpleNamespace(returncode=1, communicate=communicate,
                                         kill=lambda: None)
        return await cut_exec(*cmd, **kwargs)

    monkeypatch.setattr(reel.asyncio, "create_subprocess_exec", failing)

    with pytest.raises(RuntimeError, match="見どころの連結に失敗"):
        await reel.make_reel([{"src": mp4, "start": 0.0, "end": 10.0}])
    out = reel.reel_path(mp4, 0.0, 10.0, 1)
    assert not out.exists()
    # 失敗しても中間fileを残さない(reel本体とほぼ同容量あるため)。
    assert not [p for p in out.parent.iterdir() if p.is_dir()]


async def test_make_reel_reports_progress_to_completion(monkeypatch, make_recording):
    _, mp4 = make_recording()
    _patch_reel_ffmpeg(monkeypatch, {})
    seen = []

    async def on_progress(stage, pct):
        seen.append((stage, pct))

    await reel.make_reel([{"src": mp4, "start": 0.0, "end": 10.0},
                          {"src": mp4, "start": 30.0, "end": 40.0}],
                         on_progress=on_progress)
    assert [pct for _, pct in seen] == sorted(pct for _, pct in seen)
    assert seen[-1][1] == 100


def _synthesise(dst, seconds=12, gop=60):
    """既知のGOPを持つ実mp4を作る。連結の正しさはffmpegの挙動そのものなので、
    mockでは確かめられない(出力側-ssが映像を落とす等はcommandの形からは見えない)。"""
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=30:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:v", "libx264", "-g", str(gop), "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(dst)],
        check=True, stdin=subprocess.DEVNULL)


def _probe(path, entries):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", entries, "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout.split()
    return [v for v in out if v]


@pytest.mark.requires_ffmpeg
async def test_make_reel_really_concatenates_two_ranges(make_recording):
    _, mp4 = make_recording()
    _synthesise(mp4)

    result = await reel.make_reel([{"src": mp4, "start": 1.0, "end": 3.0},
                                   {"src": mp4, "start": 7.0, "end": 9.0}])
    out = reel.Path(result["path"])
    assert out.is_file()
    # GOPは2秒なので各範囲はその手前のkeyframe(0秒/6秒)から始まり、3秒ぶんずつになる。
    assert result["parts"][0]["seconds"] == pytest.approx(3.0, abs=0.3)
    assert result["parts"][1]["seconds"] == pytest.approx(3.0, abs=0.3)
    assert result["output_duration_seconds"] == pytest.approx(6.0, abs=0.5)
    # 出力側-ssで切ると短い範囲は映像が1 frameも入らない。実frameがあることを必ず見る。
    counted = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True).stdout.strip()
    assert int(counted) > 100
    assert _probe(out, "stream=codec_type") == ["video", "audio"]
