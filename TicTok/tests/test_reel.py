import math
import subprocess
from tests.conftest import popen_via
import types
from fractions import Fraction

import pytest

from tictok.core import layout
from tictok.media import concat as concat_mod
from tictok.media import reel

# fakeの素材はkeyframeがこの間隔で並んでいるものとして扱う。
_GOP = 2.0


def _fake_keyframes(monkeypatch, gop=_GOP):
    """``[at, at+window]`` に ``gop`` 間隔でkeyframeが並んでいるものとして返す。"""
    async def fake_keys(source, at, window):
        first = math.ceil(max(0.0, at) / gop) * gop
        keys = [Fraction(t).limit_denominator(1000)
                for t in (first + gop * i for i in range(int(window / gop) + 2))
                if t <= at + window + 1e-9]
        if not keys:
            raise concat_mod.keyframes.NoKeyframes("走査窓にkeyframeがありません。")
        return keys

    monkeypatch.setattr(concat_mod.keyframes, "video_keyframes", fake_keys)


def _spans(video_first, until, *, audio_lead=0.5, vframe=1 / 30,
           aframe=1024 / 48000):
    """partの実測spanを組む。audioがvideoより ``audio_lead`` 秒手前から入る形が実測の姿。"""
    return {"video": concat_mod.Span(video_first, until - vframe, vframe, 300),
            "audio": concat_mod.Span(video_first - audio_lead, until - aframe,
                                     aframe, 500)}


def _fake_packet_times(monkeypatch, first=0.0, frame=1 / 30, seconds=600.0):
    """連結の出力に映像packetが隙間なく並び、どれもkeyframeであるものとして返す。

    実装は各partの先頭keyframeが生きているかをこの列で確かめる。"""
    rows = [(first + frame * i, True) for i in range(int(seconds / frame))]
    monkeypatch.setattr(concat_mod, "_video_packets", _async_value(rows))


def _fake_spans_from_command(monkeypatch, captured, gop=_GOP, **kwargs):
    """直前に組んだcut commandの ``-ss``/``-to`` から、着地したpartのspanを作る。

    mp4入力の着地は「``-ss`` 以下で最後のkeyframe」(``keyframes`` の実測)。"""
    async def fake_spans(path, input_args=()):
        cuts = [cmd for cmd in captured["cmds"] if "-ss" in cmd and "-to" in cmd]
        if not cuts:
            raise AssertionError("cut commandが1つも走っていません")
        cmd = cuts[-1]
        aim = float(cmd[cmd.index("-ss") + 1])
        until = float(cmd[cmd.index("-to") + 1])
        return _spans(math.floor(aim / gop) * gop, until, **kwargs)

    monkeypatch.setattr(concat_mod, "stream_spans", fake_spans)


def _streams(codec="h264", width=720, height=1280, resolutions=1, pix_fmt="yuv420p",
             profile="Main", level=31, sample_rate="48000", channels=2):
    return {
        "video": {"codec_name": codec, "width": width, "height": height,
                  "resolutions": resolutions,
                  "pix_fmt": pix_fmt, "profile": profile, "level": level},
        "audio": {"codec_name": "aac", "sample_rate": sample_rate, "channels": channels},
    }


def _async_value(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner


def _patch_reel_ffmpeg(monkeypatch, captured, streams=None, durations=None):
    """ffmpeg / ffprobe を差し替え、実行されたcommandだけを記録する。"""
    monkeypatch.setattr(reel, "ffmpeg_available", lambda: True)

    async def fake_probe(source):
        return (streams or {}).get(reel.Path(source.path).name) or _streams()

    monkeypatch.setattr(concat_mod, "probe_stream_params", fake_probe)

    async def fake_exec(*cmd, **kwargs):
        captured.setdefault("cmds", []).append(list(cmd))
        out = reel.Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00" * 8)

        async def communicate():
            # 連結後の出力に映像と音声が在るかの確認probeへ、在る場合の答えを返す。
            if "stream=codec_type" in cmd:
                return "video\naudio\n".encode(), b""
            return b"", b""

        return types.SimpleNamespace(returncode=0, communicate=communicate,
                                     kill=lambda: None)

    monkeypatch.setattr(concat_mod.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(subprocess, "Popen", popen_via(fake_exec))

    async def fake_duration(path):
        # 中間TSはkeyframe境界のぶん要求より長く出る。reel本体はその合計になる。
        return (durations or {}).get(reel.Path(path).suffix, 12.0)

    monkeypatch.setattr(reel, "_duration_seconds", fake_duration)
    _fake_keyframes(monkeypatch)
    _fake_spans_from_command(monkeypatch, captured)
    _fake_packet_times(monkeypatch)


def test_reel_path_lands_in_the_streamers_clips_dir(make_recording, tmp_root):
    stem, mp4 = make_recording(streamer="some.user_x")
    out = reel.reel_path(mp4, 10.0, 130.0, 3)
    assert out.parent == layout.clips_dir(tmp_root, "some.user_x")
    assert out.name == f"{stem}_reel3_000010-000210.mp4"


def test_reel_path_stays_in_the_work_root_for_a_relocated_recording(tmp_root, tmp_path):
    """連結も切り出しと同じ置き方。録画が最終保存先に在っても一時保存先へ出る。"""
    mp4 = layout.mp4_path(tmp_path / "final", "00042_some.user_x_20260101_120000",
                          "some.user_x")
    assert reel.reel_path(mp4, 10.0, 130.0, 3).parent == layout.clips_dir(
        tmp_root, "some.user_x")


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
    assert cut[cut.index("-to") + 1] == "45.000"
    assert "-copyts" in cut
    assert cut[cut.index("-c") + 1] == "copy"
    assert cut[cut.index("-bsf:v") + 1] == "h264_mp4toannexb"
    assert cut[cut.index("-f") + 1] == "mpegts"
    # 中間fileの軸を入力のcontainer軸へ揃える。これが無いとmpegts muxerの約1.4秒の
    # initial offsetのぶん、連結時に渡す inpoint が実timestampとずれる。
    assert cut[cut.index("-muxdelay") + 1] == "0"
    assert cut[cut.index("-muxpreload") + 1] == "0"


async def test_make_reel_starts_at_or_before_the_requested_time(monkeypatch,
                                                               make_recording):
    """``-ss`` へ要求時刻をそのまま渡すと、映像は要求の**直後**のkeyframeから始まる。

    実録画(HLS、keyframe約1.96秒間隔)の実測: 要求 container 301.402 に対し映像は 302.082 から
    始まり、直前のkeyframe 300.121 が実在するのに落ちた = 要求した範囲の映像を最大1 GOP失う。
    狙点を要求以前のkeyframeへ寄せ、着地が要求以前であることを実測で確かめる。"""
    _, mp4 = make_recording()
    _patch_reel_ffmpeg(monkeypatch, {})

    result = await reel.make_reel([{"src": mp4, "start": 31.0, "end": 45.0}])
    # keyframeは2秒間隔なので30.0へ着地する = 要求より1秒手前から始まる。
    assert result["parts"][0]["lead_seconds"] == pytest.approx(1.0, abs=0.01)


async def test_cut_part_fails_when_it_lands_past_the_requested_start(monkeypatch,
                                                                    tmp_path):
    """着地が要求より後ろなら要求した場面の頭が欠ける。黙って通さず失敗させる。"""
    async def fake_run(cmd, event, ctx, message):
        reel.Path(cmd[-1]).write_bytes(b"\x00" * 8)

    monkeypatch.setattr(concat_mod, "run", fake_run)
    _fake_keyframes(monkeypatch)
    monkeypatch.setattr(concat_mod, "stream_spans",
                        _async_value(_spans(32.0, 45.0)))

    source = types.SimpleNamespace(path=tmp_path / "src.mp4", input_args=(),
                                   is_hls=False, media_offset=0.0)
    with pytest.raises(RuntimeError, match="要求より後ろから始まりました"):
        await concat_mod.cut_part(source, 30.0, 45.0, tmp_path / "p0.ts", "h264")


async def test_aim_ladder_offers_earlier_gops_after_the_first(monkeypatch, tmp_path):
    """狙点は1つでは足りない。HLSは12%の確率で狙いより後ろへ着地するので、1 GOPずつ
    手前へ下げられるようにしておく。"""
    _fake_keyframes(monkeypatch)
    source = types.SimpleNamespace(path=tmp_path / "src.m3u8", input_args=(),
                                   is_hls=True, media_offset=0.0)
    ladder = await concat_mod._aim_ladder(source, 31.0, 45.0, 45.0)
    keys = [float(k) for _, k in ladder]
    assert keys == sorted(keys, reverse=True), "手前のGOPほど後ろの候補"
    assert keys[0] == 30.0
    # HLSの狙点は1つ手前のGOPの内側(k_prevとkの中点)。着地はk_prevかkで、どちらもk以前。
    assert ladder[0][0] == pytest.approx(29.0)


async def test_aim_ladder_aims_inside_the_first_gop_not_before_it(monkeypatch, tmp_path):
    """素材の最初のkeyframeでは、手前ではなく**次のkeyframeとの中点**を狙う。

    合成HLS(keyframeが0.023/5.023/42.0秒)での実測: ``-ss`` 0〜0.05は**2つ目**のkeyframeへ
    着地し、0.5〜4.9は1つ目へ着地した。「最初のkeyframeの半分を狙う」形は飛ぶ側だった。"""
    async def only_first(source, at, window):
        return [Fraction(0), Fraction(5)]

    monkeypatch.setattr(concat_mod.keyframes, "video_keyframes", only_first)
    source = types.SimpleNamespace(path=tmp_path / "src.m3u8", input_args=(),
                                   is_hls=True, media_offset=0.0)
    ladder = await concat_mod._aim_ladder(source, 1.0, 10.0, 45.0)
    assert ladder == [(pytest.approx(2.5), Fraction(0))]


async def test_cut_part_retries_one_gop_earlier_when_it_lands_late(monkeypatch, tmp_path):
    """前方へ飛んだ回でも、1 GOP手前を狙い直せば要求した内容を失わずに済む。"""
    aims = []

    async def fake_run(cmd, event, ctx, message):
        aims.append(float(cmd[cmd.index("-ss") + 1]))
        reel.Path(cmd[-1]).write_bytes(b"\x00" * 8)

    async def fake_spans(path, input_args=()):
        # 1回目は要求(30.0)より後ろの32.0へ着地し、狙い直した2回目で30.0に着く。
        return _spans(32.0 if len(aims) == 1 else 30.0, 45.0)

    monkeypatch.setattr(concat_mod, "run", fake_run)
    monkeypatch.setattr(concat_mod, "stream_spans", fake_spans)
    _fake_keyframes(monkeypatch)
    source = types.SimpleNamespace(path=tmp_path / "src.m3u8", input_args=(),
                                   is_hls=True, media_offset=0.0)
    cut = await concat_mod.cut_part(source, 30.0, 45.0, tmp_path / "p0.ts", "h264")
    assert len(aims) == 2 and aims[1] < aims[0], "1 GOP手前を狙い直す"
    assert cut.media_start == 30.0


async def test_concat_detects_a_video_head_that_survived_but_lost_its_start(monkeypatch,
                                                                           tmp_path):
    """先頭keyframeが落ちても、partに次のkeyframeがあれば映像streamは**残る**。

    stream有無だけを見ると素通りする。合成素材の実測では152 packetが2 packetまで落ちた回が
    「成功」として返っていた。窓の始点と出力の映像先頭がずれていないかまで見ること。"""
    seen = []

    async def fake_run(cmd, event, ctx, message):
        seen.append(ctx.get("inpoint_back"))
        reel.Path(cmd[-1]).write_bytes(b"\x00" * 8)

    monkeypatch.setattr(concat_mod, "run", fake_run)
    monkeypatch.setattr(concat_mod, "_missing_streams", _async_value([]))
    part = concat_mod.CutPart(tmp_path / "p0.ts", _spans(30.0, 45.0)["video"],
                              _spans(30.0, 45.0)["audio"], 29.98, 45.0, 30.0, 0.0)

    async def fake_packets(path):
        # 出力の映像は窓の始点(29.98)から0.02秒後に始まるはず。実際は次のkeyframeまで飛ぶ。
        first = 0.02 if len(seen) > 1 else 5.0
        return [(first + i / 30, True) for i in range(300)]

    monkeypatch.setattr(concat_mod, "_video_packets", fake_packets)
    await concat_mod.concat_parts([part], tmp_path / "out.mp4", tmp_path / "parts.txt")
    assert seen == [0, 1], "映像の頭が落ちていれば窓を下げてやり直す"


async def test_concat_list_trims_each_part_to_the_video_range(monkeypatch, tmp_path):
    """partの先頭に付いたaudioだけの区間を落として、videoと同じ範囲へ揃えること。

    揃えないと、concat demuxerが次のfileへ与えるoffsetがfile全体の尺(=長い方=audio)で
    決まるため、接合ごとにvideoへ穴が空く(実録画5範囲で合計10.5秒)。"""
    async def fake_run(cmd, event, ctx, message):
        reel.Path(cmd[-1]).write_bytes(b"\x00" * 8)

    monkeypatch.setattr(concat_mod, "run", fake_run)
    monkeypatch.setattr(concat_mod, "_missing_streams", _async_value([]))
    _fake_keyframes(monkeypatch)
    spans = _spans(30.0, 45.0, audio_lead=2.0)
    monkeypatch.setattr(concat_mod, "stream_spans", _async_value(spans))
    _fake_packet_times(monkeypatch)

    source = types.SimpleNamespace(path=tmp_path / "src.mp4", input_args=(),
                                   is_hls=False, media_offset=0.0)
    cut = await concat_mod.cut_part(source, 30.0, 45.0, tmp_path / "p0.ts", "h264")
    # inpointはaudio packetの境界ちょうど、かつvideo先頭の直前(1 packet以内)。境界の途中に
    # 置くと音が約75ms先行し、余裕を広げるとその分だけ残存ずれが増える(どちらも実測)。
    audio = spans["audio"]
    assert cut.inpoint < 30.0
    assert 30.0 - cut.inpoint <= audio.frame
    assert (cut.inpoint - audio.first) % audio.frame == pytest.approx(0.0, abs=1e-9)
    assert cut.outpoint == pytest.approx(min(spans["video"].end, audio.end))

    list_path = tmp_path / "parts.txt"
    await concat_mod.concat_parts([cut], tmp_path / "out.mp4", list_path)
    written = list_path.read_text(encoding="utf-8")
    assert f"inpoint {cut.inpoint:.6f}" in written
    assert f"outpoint {cut.outpoint:.6f}" in written


async def test_concat_parts_still_takes_plain_paths(monkeypatch, tmp_path):
    """smart cutは自分で作ったhead/tailを繋ぐだけで揃える窓が無いので、Pathでも呼べること。"""
    captured = {}

    async def fake_run(cmd, event, ctx, message):
        captured["cmd"] = list(cmd)

    monkeypatch.setattr(concat_mod, "run", fake_run)
    monkeypatch.setattr(concat_mod, "_missing_streams", _async_value([]))
    list_path = tmp_path / "parts.txt"
    await concat_mod.concat_parts([tmp_path / "a.ts", tmp_path / "b.ts"],
                                  tmp_path / "out.mp4", list_path)
    written = list_path.read_text(encoding="utf-8")
    assert "inpoint" not in written and "outpoint" not in written
    assert written.count("file '") == 2


async def test_make_reel_concatenates_the_parts_in_the_given_order(monkeypatch,
                                                                   make_recording):
    _, mp4 = make_recording()
    captured = {}
    _patch_reel_ffmpeg(monkeypatch, captured)

    result = await reel.make_reel([{"src": mp4, "start": 300.0, "end": 310.0},
                                   {"src": mp4, "start": 10.0, "end": 20.0}])
    concat = [c for c in captured["cmds"] if c[0] == "ffmpeg"][-1]
    assert concat[concat.index("-f") + 1] == "concat"
    assert concat[concat.index("-safe") + 1] == "0"
    assert concat[concat.index("-fflags") + 1] == "+genpts"
    assert concat[concat.index("-c") + 1] == "copy"
    assert concat[concat.index("-movflags") + 1] == "+faststart"
    # 時刻順へ並べ替えず、渡された順のまま繋ぐ。
    assert [part["start"] for part in result["parts"]] == [300.0, 10.0]


async def test_make_reel_reports_the_keyframe_lead(monkeypatch, make_recording):
    """stream copyはkeyframeでしか切れないので実尺は要求より長い。その差を返すこと。

    前置きは**実測した着地**から出す。尺の差から逆算すると、audioだけが手前から入っている
    ぶん(実測で約2秒)まで前置きに数えてしまう。"""
    _, mp4 = make_recording()
    _patch_reel_ffmpeg(monkeypatch, {}, durations={".mp4": 24.0})

    result = await reel.make_reel([{"src": mp4, "start": 1.0, "end": 10.0},
                                   {"src": mp4, "start": 61.5, "end": 70.0}])
    # keyframeは2秒間隔なので0.0と60.0へ着地する。
    assert [part["lead_seconds"] for part in result["parts"]] == [1.0, 1.5]
    assert result["requested_seconds"] == 17.5
    assert result["lead_seconds"] == 2.5
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
    cut_exec = concat_mod.asyncio.create_subprocess_exec

    async def failing(*cmd, **kwargs):
        if "concat" in cmd:
            async def communicate():
                return b"", b"boom"

            return types.SimpleNamespace(returncode=1, communicate=communicate,
                                         kill=lambda: None)
        return await cut_exec(*cmd, **kwargs)

    monkeypatch.setattr(concat_mod.asyncio, "create_subprocess_exec", failing)

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


# ===== concat.cut_part: -ss と -to の軸が違う =====


@pytest.mark.asyncio
async def test_cut_part_shifts_only_to_onto_the_container_axis(monkeypatch, tmp_path):
    """``-ss`` はmedia軸、``-to`` はcontainer軸。同じcommandの中で軸が違う。

    media軸の値をそのまま ``-to`` へ渡すと、末尾が container start_time ぶん早く切れる。
    実録画(container start_time 1.43秒)で media 100→110 を要求して ``-to 110`` を渡すと
    内容は media 98.6〜108.7 で終わり、**要求した末尾1.43秒が落ちる**。

    この非対称は ``-muxdelay 0 -muxpreload 0`` 無しで測ると見えない(mpegts の約1.4秒
    initial offset が偶然打ち消して「media軸だ」と読めてしまう)。
    """
    captured = {}

    async def fake_run(cmd, event, ctx, message):
        captured["cmd"] = list(cmd)
        reel.Path(cmd[-1]).write_bytes(b"\x00" * 8)

    monkeypatch.setattr(concat_mod, "run", fake_run)
    _fake_keyframes(monkeypatch)
    # 要求100秒に対し、keyframe 98秒へ着地した場合のspan(container軸なのでoffsetを足す)。
    monkeypatch.setattr(concat_mod, "stream_spans",
                        _async_value(_spans(98.0 + 1.43, 111.43)))

    source = types.SimpleNamespace(
        path=tmp_path / "src.m3u8", input_args=("-allowed_extensions", "ALL"),
        is_hls=True, media_offset=1.43)
    await concat_mod.cut_part(source, 100.0, 110.0, tmp_path / "p0.ts", "h264")

    cmd = captured["cmd"]
    # HLSの狙点は「要求以前の最後のkeyframe」と1つ手前の中点。どちらの着地規則でも要求より
    # 手前に着く。media軸の値をそのまま渡す(ffmpegがcontainer start_timeを足して解釈する)。
    assert cmd[cmd.index("-ss") + 1] == "99.000", "-ss はmedia軸のまま渡す"
    assert cmd[cmd.index("-to") + 1] == "111.430", "-to はcontainer軸へ足し戻す"


@pytest.mark.asyncio
async def test_cut_part_leaves_to_alone_when_the_source_starts_at_zero(monkeypatch, tmp_path):
    """mp4入力は container start_time が0なので、足し戻しても値は変わらない。"""
    captured = {}

    async def fake_run(cmd, event, ctx, message):
        captured["cmd"] = list(cmd)
        reel.Path(cmd[-1]).write_bytes(b"\x00" * 8)

    monkeypatch.setattr(concat_mod, "run", fake_run)
    _fake_keyframes(monkeypatch)
    monkeypatch.setattr(concat_mod, "stream_spans", _async_value(_spans(30.0, 45.0)))

    source = types.SimpleNamespace(path=tmp_path / "src.mp4", input_args=(),
                                   is_hls=False, media_offset=0.0)
    await concat_mod.cut_part(source, 30.0, 45.0, tmp_path / "p0.ts", "h264")
    cmd = captured["cmd"]
    assert cmd[cmd.index("-to") + 1] == "45.000"


async def test_concat_moves_the_window_back_when_the_keyframe_is_dropped(monkeypatch,
                                                                        tmp_path):
    """窓の始点が際どいとconcat demuxerは先頭のkeyframeを落とし、GOPが1つしか入らないpartでは
    映像streamが出力から丸ごと消える(合成素材で実測: frame 33ms・余裕15msで映像0 packet)。
    ffmpegはこれをerrorにしないので、確かめて1 packetずつ下げてやり直すこと。"""
    seen = []

    async def fake_run(cmd, event, ctx, message):
        if "inpoint_back" in ctx:
            seen.append(ctx["inpoint_back"])

    monkeypatch.setattr(concat_mod, "run", fake_run)

    async def fake_missing(out):
        # 1回目は映像が入らず、下げた2回目で入る。
        return ["映像"] if len(seen) == 1 else []

    monkeypatch.setattr(concat_mod, "_missing_streams", fake_missing)
    _fake_keyframes(monkeypatch)
    spans = _spans(30.0, 45.0, audio_lead=2.0)
    monkeypatch.setattr(concat_mod, "stream_spans", _async_value(spans))
    _fake_packet_times(monkeypatch)

    source = types.SimpleNamespace(path=tmp_path / "src.mp4", input_args=(),
                                   is_hls=False, media_offset=0.0)
    cut = await concat_mod.cut_part(source, 30.0, 45.0, tmp_path / "p0.ts", "h264")
    list_path = tmp_path / "parts.txt"
    await concat_mod.concat_parts([cut], tmp_path / "out.mp4", list_path)

    assert seen == [0, 1], "映像が入らなければ窓を1 packet下げてやり直す"
    written = list_path.read_text(encoding="utf-8")
    expected = cut.inpoint - spans["audio"].frame
    assert f"inpoint {expected:.6f}" in written


async def test_concat_fails_after_moving_the_window_back_a_bounded_number_of_times(
        monkeypatch, tmp_path):
    """下げ切って窓の始点を外しても映像が入らないなら原因は窓ではない。失敗させる。"""
    seen = []

    async def fake_run(cmd, event, ctx, message):
        if "inpoint_back" in ctx:
            seen.append(ctx["inpoint_back"])

    monkeypatch.setattr(concat_mod, "run", fake_run)
    monkeypatch.setattr(concat_mod, "_missing_streams", _async_value(["映像"]))
    _fake_keyframes(monkeypatch)
    monkeypatch.setattr(concat_mod, "stream_spans",
                        _async_value(_spans(30.0, 45.0, audio_lead=2.0)))

    source = types.SimpleNamespace(path=tmp_path / "src.mp4", input_args=(),
                                   is_hls=False, media_offset=0.0)
    cut = await concat_mod.cut_part(source, 30.0, 45.0, tmp_path / "p0.ts", "h264")
    with pytest.raises(RuntimeError, match="映像が入りませんでした"):
        await concat_mod.concat_parts([cut], tmp_path / "out.mp4",
                                      tmp_path / "parts.txt")
    # 梯子の段 + 始点を外した1回。
    assert seen == list(range(concat_mod.WIDEN_ATTEMPTS + 2))


async def test_concat_drops_the_window_start_when_widening_never_helps(monkeypatch,
                                                                      tmp_path):
    """keyframe間隔が10〜17秒の録画では、窓の始点をpartの先頭packetより後ろへ置いた時点で
    concat demuxerが先頭keyframeを飛び越す。始点を1 packetずつ下げても閾値に届かず、届く所まで
    下げると**audio packetは1つも落ちない**(実測: 644 packetのpartで映像が入る始点はどれも
    644 packetのまま)。全か無かなので、下げ切った先=始点を書かない、へ倒して要求した映像を守る。"""
    written = []

    async def fake_run(cmd, event, ctx, message):
        if "inpoint_back" in ctx:
            written.append((tmp_path / "parts.txt").read_text(encoding="utf-8"))

    async def fake_missing(out):
        # 窓の始点を書いている間はずっと映像が入らない。外した回で初めて入る。
        return [] if "inpoint" not in written[-1] else ["映像"]

    monkeypatch.setattr(concat_mod, "run", fake_run)
    monkeypatch.setattr(concat_mod, "_missing_streams", fake_missing)
    _fake_keyframes(monkeypatch)
    spans = _spans(30.0, 45.0, audio_lead=0.2)
    monkeypatch.setattr(concat_mod, "stream_spans", _async_value(spans))
    _fake_packet_times(monkeypatch, first=0.2)

    source = types.SimpleNamespace(path=tmp_path / "src.mp4", input_args=(),
                                   is_hls=False, media_offset=0.0)
    cut = await concat_mod.cut_part(source, 30.0, 45.0, tmp_path / "p0.ts", "h264")
    await concat_mod.concat_parts([cut], tmp_path / "out.mp4", tmp_path / "parts.txt")

    assert "inpoint" in written[0], "まずは最小の余裕から試す"
    assert "inpoint" not in written[-1], "下げ切ったら始点を書かない"
    assert "outpoint" in written[-1], "終端は揃えたまま"
