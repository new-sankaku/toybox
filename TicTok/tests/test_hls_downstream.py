"""下流処理がmp4の無い録画を .ts から読めること。

mp4は原本ではなく派生物になったので、mp4を消した録画でも切抜き・sprite・波形・文字起こし・
連結・Up出力が動かなければ、その録画は機能から丸ごと消える。ここで見るのは2点:

  1. 入力が**採用集合だけの終端済みVOD playlist**であること。captureのindex.m3u8を渡すと、
     源のtimestampが壊れてEXTINFが7.8時間になったsegmentが時間軸へ戻ってくる
  2. 寸法を1組のprobeで決めていないこと。混在解像度ではその1組が全編を代表しない

末尾の実ffmpeg testだけは、argvではなく**出来た成果物**を見る。argv assertionは
「正しく組み立てた」ことしか言わないので、HLSが実際に読めるかは別に確かめる。
"""
import json
import shutil
import subprocess
from tests.conftest import popen_via
import types

import numpy as np
import pytest

from tictok.core import layout
from tictok.media import clipper, hls_source, reel
from tictok.media import concat as concat_mod
from tictok.media import thumbnails as th
from tictok.media import loudness as ld
from tictok.media import waveform as wf
from tictok.record import recorder as rec
from tictok.record import upscale

from tests.test_hls_source import build_recording

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="needs a real ffmpeg/ffprobe on PATH",
)


def hls_only(tmp_root, **kwargs):
    """mp4を持たない録画。retentionがmp4を消した後の、これから普通になる形。"""
    return build_recording(tmp_root, with_mp4=False, **kwargs)


def first_input_command(cmds):
    """入力を開いた最初のcommand。codecを1つ引くprobeなど、-i を持たないcommandは飛ばす。"""
    for cmd in cmds:
        if "-i" in [str(a) for a in cmd]:
            return cmd
    raise AssertionError("入力を開いたcommandがありません")


def assert_reads_the_curated_playlist(args, session):
    """ffmpegの引数列が、束ねられた採用集合のplaylistを入力にしているか。"""
    args = [str(a) for a in args]
    index = args.index("-i")
    playlist = args[index + 1]
    assert playlist.endswith(".m3u8"), playlist
    assert playlist.startswith(str(session)), playlist
    assert hls_source.CURATED_PREFIX in playlist, "captureのindex.m3u8を直接渡している"
    for option in rec.HLS_INPUT_ARGS:
        assert option in args[:index], f"{option} が -i より前にない"
    body = json.dumps(sorted(p.name for p in session.iterdir()))
    assert "index.m3u8" in body


def capture_exec(monkeypatch, module, captured, stdout=b""):
    async def fake_exec(*cmd, **kwargs):
        captured.setdefault("cmds", []).append(list(cmd))
        out = module.Path(cmd[-1])
        if not str(out).startswith("-") and out.suffix in (".mp4", ".jpg", ".ts"):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"\x00" * 8)

        async def communicate():
            # 切り出しは素材のcodecを1つ引き、出力に映像と音声が在るかを確かめる。
            # 在る場合の答えを返しておかないと、経路の途中で落ちて引数を見られない。
            if "stream=codec_name" in cmd:
                return b"h264", b""
            if "stream=codec_type" in cmd:
                return "video\naudio\n".encode(), b""
            if "packet=pts,flags:stream=time_base" in cmd:
                # keyframe走査。2秒間隔のkeyframeが並んでいる形で答える。
                rows = "".join(f"packet,{i * 180000},K__,\n" for i in range(40))
                return (rows + "stream,1/90000\n").encode(), b""
            if "packet=pts_time" in cmd:
                # partの実測span。audioがvideoより手前から始まるのが実測の姿。
                step = 1024 / 48000 if "a:0" in cmd else 1 / 30
                base = -0.5 if "a:0" in cmd else 0.0
                count = 260 if "a:0" in cmd else 150
                return json.dumps({"packets": [
                    {"pts_time": f"{base + i * step:.6f}"} for i in range(count)
                ]}).encode(), b""
            return stdout, b""

        return types.SimpleNamespace(returncode=0, communicate=communicate,
                                     kill=lambda: None)

    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(subprocess, "Popen", popen_via(fake_exec))
    return captured


# --------------------------------------------------------------------------
# 切抜き
# --------------------------------------------------------------------------


async def test_clipping_a_recording_without_an_mp4_reads_its_segments(tmp_root,
                                                                      monkeypatch):
    mp4, session = hls_only(tmp_root)
    monkeypatch.setattr(clipper, "ffmpeg_available", lambda: True)
    captured = capture_exec(monkeypatch, clipper, {})

    await clipper.make_clip(mp4, 1.0, 3.0)

    assert_reads_the_curated_playlist(first_input_command(captured["cmds"]), session)


async def test_clipping_leaves_no_playlist_behind(tmp_root, monkeypatch):
    """session dirはretentionと容量集計が数えている置き場。切るたびに1 file増えては困る。"""
    mp4, session = hls_only(tmp_root)
    monkeypatch.setattr(clipper, "ffmpeg_available", lambda: True)
    capture_exec(monkeypatch, clipper, {})

    await clipper.make_clip(mp4, 1.0, 3.0)

    assert list(session.glob(hls_source.CURATED_PREFIX + "*")) == []


# --------------------------------------------------------------------------
# sprite
# --------------------------------------------------------------------------


def patch_sprite(monkeypatch, captured, duration=600.0, found=((160, 120),)):
    monkeypatch.setattr(th, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(th, "ffprobe_available", lambda: True)

    async def fake_resolutions(source):
        captured["probe_source"] = source
        return set(found)

    monkeypatch.setattr(th.hls_source, "resolutions", fake_resolutions)

    async def fake_exec(*cmd, **kwargs):
        captured.setdefault("cmds", []).append(list(cmd))
        out = th.Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\xff\xd8")

        async def communicate():
            # 尺のprobeは core.ffprobe の共通形式(素の1行)で答える。
            payload = f"{duration}\n".encode()
            return (payload if "ffprobe" in cmd[0] else b""), b""

        return types.SimpleNamespace(returncode=0, communicate=communicate,
                                     kill=lambda: None)

    monkeypatch.setattr(th.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(subprocess, "Popen", popen_via(fake_exec))
    return captured


async def test_sprite_for_a_recording_without_an_mp4_reads_its_segments(tmp_root,
                                                                        monkeypatch):
    mp4, session = hls_only(tmp_root)
    captured = patch_sprite(monkeypatch, {})

    await th.ensure_sprite(mp4)

    assert_reads_the_curated_playlist(captured["cmds"][-1], session)


async def test_the_tile_aspect_comes_from_the_widest_resolution(tmp_root, monkeypatch):
    """1組のprobeで決めると、切替後のframeがその比へ引き伸ばされる。両方を包む枠から
    採れば、混在したどのframeも同じ歪み方をしない。"""
    mp4, _ = hls_only(tmp_root)
    captured = patch_sprite(monkeypatch, {}, found=((160, 640), (120, 320)))

    grid = await th.ensure_sprite(mp4)

    # 包む枠は 160x640。tile幅120に対して高さは 120 * 640/160 = 480。
    assert grid["tile_height"] == 480
    assert captured["probe_source"].is_hls is True


async def test_the_sprite_cache_key_follows_the_segments(tmp_root, monkeypatch):
    """mp4が無い録画ではplaylistのstatしか無く、それはsegmentの入れ替わりを映さない。
    素材そのものを数えていないと、録画が変わってもcacheが当たり続ける。"""
    import os

    mp4, session = hls_only(tmp_root)
    before = th._signature(mp4)
    assert before["segments"] == 3

    (session / "seg00001.ts").write_bytes(b"\x47" * 376)
    os.utime(session / "seg00001.ts", (1_800_000_000.0, 1_800_000_000.0))

    assert th._signature(mp4) != before


def test_an_existing_mp4_keeps_its_old_sprite_cache_key(tmp_root):
    """既存cacheの鍵を変えない。1 fieldでもずれると全録画のspriteが作り直しになる。"""
    mp4, _ = build_recording(tmp_root)
    stat = mp4.stat()

    signature = th._signature(mp4)

    assert signature["mtime"] == stat.st_mtime and signature["size"] == stat.st_size
    assert "segments" not in signature


# --------------------------------------------------------------------------
# 波形
# --------------------------------------------------------------------------


def test_waveform_for_a_recording_without_an_mp4_reads_its_segments(tmp_root,
                                                                    monkeypatch):
    mp4, session = hls_only(tmp_root)
    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        raise OSError("blocked")

    monkeypatch.setattr(wf.subprocess, "Popen", fake_popen)

    with pytest.raises(RuntimeError):
        wf._build(mp4, 1.0)

    assert_reads_the_curated_playlist(captured["args"], session)


def test_the_waveform_cache_key_follows_the_segments(tmp_root):
    mp4, session = hls_only(tmp_root)
    key = wf._source_key(mp4)

    assert key["segments"] == 3
    # mp4のcache(segmentsの項が無い)を.tsのcacheと取り違えない。
    assert wf._key_matches({"mtime": key["mtime"], "size": key["size"]}, key) is False
    assert wf._key_matches(dict(key), key) is True


async def test_waveform_reports_a_recording_with_no_material_as_missing(tmp_root):
    mp4, session = hls_only(tmp_root)
    for seg in session.glob("seg*.ts"):
        seg.unlink()

    with pytest.raises(RuntimeError):
        await wf.ensure_waveform(mp4)


# --------------------------------------------------------------------------
# 文字起こし
# --------------------------------------------------------------------------


async def test_transcription_of_a_recording_without_an_mp4_reads_its_segments(
        tmp_root, tmp_db, monkeypatch):
    """文字起こしだけはffmpegを起こさずPyAVがpathを直接開く。渡すのがcaptureのindexだと、
    終端が無いためlive streamと見なされて返ってこない。採用集合のVOD playlistを渡し、
    使い終わったら必ず消すこと。"""
    # importはtestの中で行う。tictok.api.runtime は import 時に Storage / instance lock /
    # record dir を掴むので、module levelで読むと本番を掴む。
    import tictok.server  # noqa: F401  applicationの組み立てを一度通す
    from tictok.api import media_jobs, runtime
    from tictok.search import indexer

    mp4, session = hls_only(tmp_root)
    session_id = tmp_db.create_session("tester", 60)
    recording_id = tmp_db.create_recording(
        session_id, "tester", str(mp4), mp4.name, "hd", 1_700_000_000.0)
    seen = {}

    def fake_transcribe(path, on_progress=None):
        seen["path"] = path
        return {"segments": [], "text": ""}

    monkeypatch.setattr(media_jobs, "stt_transcribe", fake_transcribe)
    monkeypatch.setattr(runtime.storage, "save_transcript", lambda *a, **k: None)
    monkeypatch.setattr(indexer, "index_transcript", lambda *a, **k: None)

    recording = {"id": recording_id, "session_id": session_id, "unique_id": "tester",
                 "path": str(mp4), "filename": mp4.name}
    await media_jobs._transcribe_into_storage(recording, mp4, None)

    assert seen["path"].endswith(".m3u8")
    assert hls_source.CURATED_PREFIX in seen["path"]
    assert seen["path"].startswith(str(session))
    assert list(session.glob(hls_source.CURATED_PREFIX + "*")) == []


async def _noop_broadcast(*args, **kwargs):
    return None


# --------------------------------------------------------------------------
# 連結
# --------------------------------------------------------------------------


async def test_reel_refuses_a_source_that_changes_resolution_inside_itself(tmp_root,
                                                                          monkeypatch):
    """avcC(mp4のcodec設定)は先頭fileのものが1つだけ書かれるので、途中で解像度が変わる
    素材を繋ぐと切替後が復号できない。包む枠が同じでも繋げない。"""
    mp4_a, _ = build_recording(tmp_root, stem="00001_tester_20260101_120000")
    mp4_b, _ = build_recording(tmp_root, stem="00002_tester_20260101_130000")
    monkeypatch.setattr(reel, "ffmpeg_available", lambda: True)

    async def fake_probe(source):
        mixed = source.path.name.startswith("00002")
        return {"video": {"codec_name": "h264", "width": 720, "height": 1280,
                          "resolutions": 2 if mixed else 1, "pix_fmt": "yuv420p",
                          "profile": "Main", "level": 31},
                "audio": {"codec_name": "aac", "sample_rate": "48000", "channels": 2}}

    monkeypatch.setattr(concat_mod, "probe_stream_params", fake_probe)

    with pytest.raises(RuntimeError, match="配信中に切り替わった解像度の数"):
        await reel.make_reel([{"src": mp4_a, "start": 0, "end": 5},
                              {"src": mp4_b, "start": 0, "end": 5}])


async def test_reel_cuts_a_recording_without_an_mp4_from_its_segments(tmp_root,
                                                                      monkeypatch):
    mp4, session = hls_only(tmp_root)
    monkeypatch.setattr(reel, "ffmpeg_available", lambda: True)

    async def fake_probe(source):
        return {"video": {"codec_name": "h264", "width": 720, "height": 1280,
                          "resolutions": 1, "pix_fmt": "yuv420p",
                          "profile": "Main", "level": 31},
                "audio": {"codec_name": "aac", "sample_rate": "48000", "channels": 2}}

    monkeypatch.setattr(concat_mod, "probe_stream_params", fake_probe)

    async def fake_duration(path):
        return 5.0

    monkeypatch.setattr(reel, "_duration_seconds", fake_duration)
    captured = capture_exec(monkeypatch, concat_mod, {})

    await reel.make_reel([{"src": mp4, "start": 0, "end": 5}])

    assert_reads_the_curated_playlist(first_input_command(captured["cmds"]), session)
    assert list(session.glob(hls_source.CURATED_PREFIX + "*")) == []


# --------------------------------------------------------------------------
# Up出力
# --------------------------------------------------------------------------


def test_upscale_signature_separates_an_mp4_from_its_segments(tmp_root, monkeypatch):
    """mp4が在る録画の鍵は今までと同じ形のまま。Up出力は1本で数時間かかるので、
    鍵の形が変わると既にある出力が一斉に作り直しになる。"""
    mp4, _ = build_recording(tmp_root)
    model = tmp_root / "model.pth"
    model.write_bytes(b"\x00")

    with_mp4 = upscale._signature(mp4, str(model), "libx264", 23)
    mp4.unlink()
    without_mp4 = upscale._signature(mp4, str(model), "libx264", 23)

    assert with_mp4 != without_mp4


def test_upscale_probe_takes_the_widest_resolution(tmp_root, monkeypatch):
    """raw pipeにはframe境界が無く、読み手は width*height*3 byteずつ切り出すだけ。
    寸法を1組のprobeで決めると、切替点から先の全frameがずれたまま最後まで進む。"""
    mp4, _ = build_recording(tmp_root)
    monkeypatch.setattr(upscale, "ffprobe_available", lambda: True)

    def fake_run(args, **kwargs):
        payload = json.dumps({
            "streams": [{"width": 320, "height": 640, "r_frame_rate": "30/1"}],
            "format": {"duration": "12.0"},
        }).encode()
        return types.SimpleNamespace(stdout=payload, stderr=b"", returncode=0)

    monkeypatch.setattr(upscale.subprocess, "run", fake_run)
    monkeypatch.setattr(upscale.hls_source, "resolutions_sync",
                        lambda source: {(320, 640), (720, 1280)})

    width, height, fps, duration, distinct = upscale._probe_video(
        hls_source.Source(mp4, (), False))

    assert (width, height) == (720, 1280)
    assert distinct == 2
    assert (fps, duration) == (30.0, 12.0)


# --------------------------------------------------------------------------
# 実ffmpeg: argvではなく出来た物を見る
# --------------------------------------------------------------------------


SEGMENT_SECONDS = 2


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", *args],
                   check=True, capture_output=True)


def build_real_recording(tmp_root, segments=4, stem="00001_tester_20260101_120000"):
    """実ffmpegで作った .ts だけの録画(mp4は無い)。"""
    session = layout.session_dir(tmp_root, stem, "tester")
    session.mkdir(parents=True, exist_ok=True)
    names = []
    for i in range(segments):
        name = "seg%05d.ts" % i
        _ffmpeg("-f", "lavfi", "-i",
                "testsrc2=size=160x120:rate=30:duration=%d" % SEGMENT_SECONDS,
                "-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % SEGMENT_SECONDS,
                "-c:v", "libx264", "-preset", "ultrafast", "-g", str(SEGMENT_SECONDS * 30),
                "-c:a", "aac", "-copyts", "-output_ts_offset", str(i * SEGMENT_SECONDS),
                "-muxdelay", "0", "-muxpreload", "0", str(session / name))
        names.append(name)
    body = ["#EXTM3U", "#EXT-X-VERSION:6", "#EXT-X-TARGETDURATION:3"]
    for name in names:
        body.append("#EXTINF:%.6f," % SEGMENT_SECONDS)
        body.append(name)
    (session / "index.m3u8").write_text("\n".join(body) + "\n", encoding="utf-8")
    mp4 = layout.mp4_path(tmp_root, stem, "tester")
    mp4.parent.mkdir(parents=True, exist_ok=True)
    return mp4, session


@needs_ffmpeg
@pytest.mark.requires_ffmpeg
@pytest.mark.slow
async def test_a_clip_cut_from_segments_is_a_real_playable_mp4(tmp_root):
    """argv assertionは「正しく組み立てた」ことしか言わない。HLSが実際に読めて、
    要求した範囲の映像と音声が本当に出てくるところまで見る。"""
    mp4, _ = build_real_recording(tmp_root)

    result = await clipper.make_clip(mp4, 2.0, 6.0)

    out = th.Path(result["path"])
    assert out.is_file() and out.stat().st_size > 0
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type:format=duration", "-of", "json", str(out)],
        capture_output=True, text=True, check=True).stdout
    info = json.loads(probe)
    kinds = {s["codec_type"] for s in info["streams"]}
    assert kinds == {"video", "audio"}
    # stream copyは要求以前のkeyframeから始まるので、実尺は要求4秒より前置きのぶん長い。
    # 短い側は許さない: 要求した範囲を失っていないことがこのtestの主眼である。
    lead = result["keyframe_lead_seconds"]
    assert lead >= 0.0
    assert float(info["format"]["duration"]) == pytest.approx(4.0 + lead, abs=0.5)
    assert result["actual_start_seconds"] == pytest.approx(2.0 - lead, abs=0.01)


@needs_ffmpeg
@pytest.mark.requires_ffmpeg
@pytest.mark.slow
async def test_a_gain_curve_built_from_segments_lands_on_the_target(tmp_root):
    """曲線は実際に測った値でなければ意味が無い。素材は既知の正弦波(振幅0.125 = -21.76 LUFS)
    なので、目標との差がそのまま答えになる。argv assertionでは、filter chainが受理される
    ことも、時刻とframeが対応していることも言えない。"""
    mp4, _ = build_real_recording(tmp_root)
    params = {"target_lufs": -14.0, "ceiling_dbfs": -1.5,
              "max_boost_db": 12.0, "max_cut_db": 12.0}

    curve = await ld.ensure_gain_curve(mp4, params)

    assert curve["step_seconds"] == ld.STEP_SECONDS
    assert curve["duration_seconds"] == pytest.approx(4 * SEGMENT_SECONDS, abs=0.3)
    assert len(curve["gains"]) == pytest.approx(
        4 * SEGMENT_SECONDS / ld.STEP_SECONDS, abs=0.3 / ld.STEP_SECONDS)
    # 正弦波の統合ラウドネスは -21.76 LUFS。目標 -14 との差 7.76 dB へ収まる。
    assert curve["integrated_lufs"] == pytest.approx(-21.76, abs=0.5)
    assert min(curve["gains"]) == pytest.approx(7.76, abs=0.8)
    assert max(curve["gains"]) == pytest.approx(7.76, abs=0.8)
    # 曲線はcacheされ、2度目はffmpegを回さない(同じ値が返る)。
    assert (await ld.ensure_gain_curve(mp4, params))["gains"] == curve["gains"]


@needs_ffmpeg
@pytest.mark.requires_ffmpeg
@pytest.mark.slow
async def test_a_waveform_built_from_segments_covers_the_whole_recording(tmp_root):
    """波形のx軸はplayerの再生位置と一致していなければならない。素材を.tsから読むよう
    にしたせいで尺が縮む(=末尾へ向かって波形がずれる)ことがないかを、尺で直接見る。"""
    mp4, _ = build_real_recording(tmp_root)

    result = await wf.ensure_waveform(mp4)

    # bucketは時間刻みなので、本数も尺から決まる。
    assert len(result["peaks"]) == pytest.approx(
        4 * SEGMENT_SECONDS / wf.WAVE_BUCKET_SECONDS, abs=0.3 / wf.WAVE_BUCKET_SECONDS)
    assert result["bucket_seconds"] == wf.WAVE_BUCKET_SECONDS
    assert result["duration_seconds"] == pytest.approx(4 * SEGMENT_SECONDS, abs=0.3)
    assert max(result["peaks"]) > 0.5, "無音になっている(音声を読めていない)"


@needs_ffmpeg
@pytest.mark.requires_ffmpeg
@pytest.mark.slow
async def test_a_sprite_built_from_segments_has_the_tiles_it_promised(tmp_root):
    mp4, session = build_real_recording(tmp_root)

    grid = await th.ensure_sprite(mp4)

    sprite = th.Path(grid["path"])
    assert sprite.is_file() and sprite.stat().st_size > 0
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", str(sprite)],
        capture_output=True, text=True, check=True).stdout
    width, height = [int(v) for v in probe.strip().split(",") if v]
    assert width == grid["tile_width"] * grid["columns"]
    assert height == grid["tile_height"] * grid["rows"]
    assert list(session.glob(hls_source.CURATED_PREFIX + "*")) == []


def build_switching_recording(tmp_root, stem="00002_tester_20260101_120000",
                              first=(160, 120), second=(240, 180)):
    """途中で解像度が変わる .ts だけの録画。前半を赤・後半を青にして、tileが**何秒の絵か**を
    色で言い当てられるようにする。実streamでは解像度は配信中に何度も変わる。"""
    session = layout.session_dir(tmp_root, stem, "tester")
    session.mkdir(parents=True, exist_ok=True)
    names = []
    for i in range(6):
        width, height = first if i < 3 else second
        name = "seg%05d.ts" % i
        _ffmpeg("-f", "lavfi", "-i",
                "color=c=%s:size=%dx%d:rate=30:duration=%d"
                % ("red" if i < 3 else "blue", width, height, SEGMENT_SECONDS),
                "-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % SEGMENT_SECONDS,
                "-c:v", "libx264", "-preset", "ultrafast", "-g", str(SEGMENT_SECONDS * 30),
                "-c:a", "aac", "-copyts", "-output_ts_offset", str(i * SEGMENT_SECONDS),
                "-muxdelay", "0", "-muxpreload", "0", str(session / name))
        names.append(name)
    body = ["#EXTM3U", "#EXT-X-VERSION:6", "#EXT-X-TARGETDURATION:3"]
    for name in names:
        body.append("#EXTINF:%.6f," % SEGMENT_SECONDS)
        body.append(name)
    (session / "index.m3u8").write_text("\n".join(body) + "\n", encoding="utf-8")
    mp4 = layout.mp4_path(tmp_root, stem, "tester")
    mp4.parent.mkdir(parents=True, exist_ok=True)
    return mp4, session


def _sprite_tiles(sprite, grid):
    """sprite sheetをtileごとのrgb arrayへ切り分ける。"""
    raw = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(sprite),
         "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        capture_output=True, check=True).stdout
    sheet = np.frombuffer(raw, dtype=np.uint8).reshape(
        grid["tile_height"] * grid["rows"], grid["tile_width"] * grid["columns"], 3)
    tiles = []
    for i in range(grid["count"]):
        row, column = divmod(i, grid["columns"])
        tiles.append(sheet[row * grid["tile_height"]:(row + 1) * grid["tile_height"],
                           column * grid["tile_width"]:(column + 1) * grid["tile_width"]])
    return tiles


@needs_ffmpeg
@pytest.mark.requires_ffmpeg
@pytest.mark.slow
async def test_a_sprite_keeps_its_head_when_the_resolution_changes(tmp_root):
    """解像度が変わるとffmpegはfilter graphを作り直し、蓄積型の ``tile`` が貯めた分を捨てる。
    実録画(3.68時間・最後の変更が2481秒)ではtile *i* に (i+55)*45秒 の絵が入り、末尾55枚が
    黒だった。寸法もtile数も正常なので、成果物の**中身**を見ない限り気付けない。"""
    mp4, _ = build_switching_recording(tmp_root)

    grid = await th.ensure_sprite(mp4)

    tiles = _sprite_tiles(th.Path(grid["path"]), grid)
    # 変更点(6秒=tile 3)ちょうどのtileはどちらの色でもよい。その前後だけを見る。
    assert all(int(t[..., 0].mean()) > int(t[..., 2].mean()) for t in tiles[:3]), \
        "前半が赤でない(頭のtileが落ちて全体が前へ詰まっている)"
    assert all(int(t[..., 2].mean()) > int(t[..., 0].mean()) for t in tiles[4:]), \
        "後半が青でない"
    assert all(t.std() > 1.0 for t in tiles), "黒で埋められたtileがある"


def build_mixed_ts(session, first=(160, 120), second=(240, 180)):
    """1本の中で解像度が変わる .ts。実streamでは解像度変化40回のうち29回がこの形。

    既定の2組はどちらのframe byte数も他方の倍数にならない(57,600 と 129,600)。倍数だと、
    出てきたraw byte数がどちらの寸法でも割り切れてしまい、何で出ているのか判別できない。"""
    halves = []
    for n, (width, height) in enumerate((first, second)):
        part = session / ("half%d.ts" % n)
        _ffmpeg("-f", "lavfi", "-i",
                "testsrc2=size=%dx%d:rate=30:duration=1" % (width, height),
                "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                "-c:v", "libx264", "-preset", "ultrafast", "-g", "30",
                "-c:a", "aac", "-copyts", "-output_ts_offset", str(n),
                "-muxdelay", "0", "-muxpreload", "0", str(part))
        halves.append(part)
    joined = session / "mixed.ts"
    joined.write_bytes(b"".join(p.read_bytes() for p in halves))
    for part in halves:
        part.unlink()
    return joined


def _raw_frame_size(mixed, vf):
    """``vf`` で復号したraw rgb24の出力が、どの寸法のframeで出ているか。"""
    raw = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(mixed),
         "-map", "0:v:0", "-vf", vf,
         "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        capture_output=True, check=True).stdout
    fits = [(w, h) for w, h in ((160, 120), (240, 180)) if len(raw) % (w * h * 3) == 0]
    assert len(fits) == 1, "%d bytes が %s のどれとも一意に対応しない" % (len(raw), fits)
    return fits[0]


@needs_ffmpeg
@pytest.mark.requires_ffmpeg
@pytest.mark.slow
def test_the_sync_resolution_probe_sees_a_switch_inside_one_file(tmp_root):
    """Up出力はGPUに張り付いたblocking経路なので、走査だけ同期版を持っている。本家と
    同じ物が見えていなければ、混在の録画だけ判定が食い違う。"""
    session = tmp_root / "probe"
    session.mkdir(parents=True, exist_ok=True)
    mixed = build_mixed_ts(session)

    found = hls_source.resolutions_sync(hls_source.Source(mixed, (), False))

    assert found == {(160, 120), (240, 180)}


@needs_ffmpeg
@pytest.mark.requires_ffmpeg
@pytest.mark.slow
def test_upscale_probes_a_mixed_file_as_its_enclosing_frame(tmp_root, monkeypatch):
    session = tmp_root / "probe"
    session.mkdir(parents=True, exist_ok=True)
    mixed = build_mixed_ts(session)
    monkeypatch.setattr(upscale, "ffprobe_available", lambda: True)

    width, height, fps, duration, distinct = upscale._probe_video(
        hls_source.Source(mixed, (), False))

    assert (width, height) == (240, 180)
    assert distinct == 2
    assert duration > 0 and fps > 0


@needs_ffmpeg
@pytest.mark.requires_ffmpeg
@pytest.mark.slow
def test_a_mixed_source_is_decoded_at_its_opening_size_without_the_geometry_filter(
        tmp_root):
    """守っている物の対照。何も指定しないとffmpegはfilter graphを**開いた所の寸法**で
    固定し、切替後の大きい絵をそこへ縮めてから渡す。Up出力に渡る素材が、実在する画素を
    捨てた後の物になるということ。"""
    session = tmp_root / "probe"
    session.mkdir(parents=True, exist_ok=True)
    mixed = build_mixed_ts(session, first=(160, 120), second=(240, 180))

    assert _raw_frame_size(mixed, "fps=30.000000") == (160, 120)


@needs_ffmpeg
@pytest.mark.requires_ffmpeg
@pytest.mark.slow
def test_the_geometry_filter_decodes_a_mixed_source_at_its_enclosing_frame(tmp_root,
                                                                          monkeypatch):
    """Up出力の中核。枠を明示すれば、大きい側の区間はその大きさのままmodelへ渡る。
    ついでにframeの大きさが最後まで一定になるので、``frame_bytes`` ずつ切り出す
    読み手ともずれない。"""
    session = tmp_root / "probe"
    session.mkdir(parents=True, exist_ok=True)
    mixed = build_mixed_ts(session, first=(160, 120), second=(240, 180))
    monkeypatch.setattr(upscale, "ffprobe_available", lambda: True)
    source = hls_source.Source(mixed, (), False)
    width, height, fps, _, distinct = upscale._probe_video(source)
    assert distinct == 2, "fixtureが混在解像度になっていない"

    geometry = upscale._normalize_filter(
        width, height, upscale.get_normalize_scale_mode()) + ","

    assert _raw_frame_size(mixed, f"{geometry}fps={fps:.6f}") == (240, 180)
