import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from tictok.media import hls_source
from tictok.media import keyframes as kf
from tictok.record import recorder as rec


# 実測したffprobeの出力そのまま。MPEG-TSは各行の末尾に空fieldが1つ付き、programを持つ
# 入力では program,stream,... も出る。
TS_OUTPUT = """packet,453000,___,
packet,468000,___,
packet,492000,K__,
packet,495000,___,
program,stream,1/90000
stream,1/90000
"""

MP4_OUTPUT = """packet,0,K__
packet,3000,___
stream,1/90000
"""


def _source(path="fake.m3u8", input_args=("-f", "hls"), is_hls=True, media_offset=0.0):
    return hls_source.Source(Path(path), tuple(input_args), is_hls, media_offset)


def _stub_probe(monkeypatch, text, seen=None):
    async def _fake(cmd, path):
        if seen is not None:
            seen.append(list(cmd))
        return text

    monkeypatch.setattr(kf, "_run_probe", _fake)


# --------------------------------------------------------------------- parse

def test_parse_reads_time_base_as_a_fraction():
    time_base, _ = kf._parse_probe(TS_OUTPUT)
    assert time_base == Fraction(1, 90000)
    assert isinstance(time_base, Fraction)


def test_parse_keeps_integer_pts_and_keyframe_flag():
    _, packets = kf._parse_probe(TS_OUTPUT)
    assert packets == [(453000, False), (468000, False), (492000, True), (495000, False)]


def test_parse_handles_the_mp4_shape_without_trailing_field():
    time_base, packets = kf._parse_probe(MP4_OUTPUT)
    assert time_base == Fraction(1, 90000)
    assert packets == [(0, True), (3000, False)]


def test_parse_skips_na_pts_without_raising():
    """pts=N/A のpacketは正常に混ざる(実測で約2.4%)。float()へ渡して落ちてはいけない。"""
    text = "packet,N/A,K__,\npacket,492000,K__,\npacket,N/A,___,\nstream,1/90000\n"
    _, packets = kf._parse_probe(text)
    assert packets == [(492000, True)]


def test_parse_returns_none_when_no_stream_section():
    time_base, packets = kf._parse_probe("packet,0,K__\n")
    assert time_base is None
    assert packets == [(0, True)]


# ----------------------------------------------------------- video_keyframes

async def test_video_keyframes_returns_exact_fractions(monkeypatch):
    _stub_probe(monkeypatch, TS_OUTPUT)
    keys = await kf.video_keyframes(_source(), 5.0, 3.0)
    assert keys == [Fraction(492000, 90000)]
    assert all(isinstance(k, Fraction) for k in keys)


async def test_video_keyframes_sorts_and_dedupes_dts_ordered_packets(monkeypatch):
    text = ("packet,4500,K__,\npacket,900,K__,\npacket,900,K__,\n"
            "packet,2700,___,\nstream,1/90000\n")
    _stub_probe(monkeypatch, text)
    keys = await kf.video_keyframes(_source(), 0.0, 1.0)
    assert keys == [Fraction(900, 90000), Fraction(4500, 90000)]


async def test_video_keyframes_subtracts_the_media_offset(monkeypatch):
    _stub_probe(monkeypatch, "packet,132000,K__,\nstream,1/90000\n")
    keys = await kf.video_keyframes(_source(media_offset=1.402), 0.0, 5.0)
    assert keys[0] == Fraction(132000, 90000) - Fraction(1.402)
    assert float(keys[0]) == pytest.approx(0.06466, abs=1e-5)


async def test_video_keyframes_adds_the_media_offset_to_the_probe_window(monkeypatch):
    """窓もcontainer軸で解釈されるので、要求(media軸)へoffsetを足して渡す。"""
    seen = []
    _stub_probe(monkeypatch, TS_OUTPUT, seen)
    await kf.video_keyframes(_source(media_offset=1.402), 10.0, 4.0)
    interval = seen[0][seen[0].index("-read_intervals") + 1]
    start, end = interval.split("%")
    assert float(start) == pytest.approx(11.402)
    assert float(end) == pytest.approx(15.402)


async def test_video_keyframes_asks_for_an_absolute_end_not_a_duration(monkeypatch):
    """窓は ``start%end`` で渡す。``start%+尺`` 形式は実素材で走査が空振りする。

    実HLS録画での実測: seek直後の先頭packetの ``pts`` が ``N/A`` だと ``+尺`` 形式は尺を
    決められず、その1 packetだけを返して読むのを止める(45秒窓でkeyframe 0本)。同じ窓を
    絶対終端で渡せば1,131 packet・keyframe 23本が返る。``pts=N/A`` はMPEG-TSのsegment境界で
    正常に混ざるものなので、``+尺`` 形式では実素材の走査が丸ごと失敗する。"""
    seen = []
    _stub_probe(monkeypatch, TS_OUTPUT, seen)
    await kf.video_keyframes(_source(), 100.0, 45.0)
    interval = seen[0][seen[0].index("-read_intervals") + 1]
    assert "%+" not in interval
    assert interval.startswith("100.")


async def test_video_keyframes_clamps_a_window_that_starts_before_zero(monkeypatch):
    seen = []
    _stub_probe(monkeypatch, TS_OUTPUT, seen)
    await kf.video_keyframes(_source(), -2.0, 5.0)
    interval = seen[0][seen[0].index("-read_intervals") + 1]
    start, end = interval.split("%")
    assert float(start) == pytest.approx(0.0)
    assert float(end) == pytest.approx(3.0)


async def test_video_keyframes_passes_the_source_input_args(monkeypatch):
    seen = []
    _stub_probe(monkeypatch, TS_OUTPUT, seen)
    await kf.video_keyframes(_source(input_args=("-allowed_extensions", "ALL")), 0.0, 1.0)
    cmd = seen[0]
    assert cmd[:2] == ["ffprobe", "-v"]
    assert "-allowed_extensions" in cmd
    assert cmd.index("-allowed_extensions") < cmd.index("-select_streams")


async def test_video_keyframes_raises_when_the_window_has_no_keyframe(monkeypatch):
    _stub_probe(monkeypatch, "packet,453000,___,\npacket,468000,___,\nstream,1/90000\n")
    with pytest.raises(kf.NoKeyframes):
        await kf.video_keyframes(_source(), 5.0, 3.0)


async def test_video_keyframes_raises_when_only_na_keyframes_are_in_the_window(monkeypatch):
    _stub_probe(monkeypatch, "packet,N/A,K__,\nstream,1/90000\n")
    with pytest.raises(kf.NoKeyframes):
        await kf.video_keyframes(_source(), 5.0, 3.0)


async def test_video_keyframes_raises_without_a_time_base(monkeypatch):
    _stub_probe(monkeypatch, "packet,900,K__\n")
    with pytest.raises(RuntimeError) as excinfo:
        await kf.video_keyframes(_source(), 0.0, 1.0)
    assert not isinstance(excinfo.value, kf.NoKeyframes)


async def test_video_keyframes_rejects_a_non_positive_window(monkeypatch):
    _stub_probe(monkeypatch, TS_OUTPUT)
    with pytest.raises(ValueError):
        await kf.video_keyframes(_source(), 5.0, 0.0)


# ---------------------------------------------------------- first_at_or_after

def test_first_at_or_after_takes_the_exact_hit():
    keys = [Fraction(1), Fraction(3), Fraction(5)]
    assert kf.first_at_or_after(keys, 3) == Fraction(3)


def test_first_at_or_after_takes_the_next_one():
    keys = [Fraction(1), Fraction(3), Fraction(5)]
    assert kf.first_at_or_after(keys, 3.2) == Fraction(5)


def test_first_at_or_after_returns_none_past_the_last_key():
    assert kf.first_at_or_after([Fraction(1), Fraction(3)], 3.5) is None


def test_first_at_or_after_on_an_empty_list():
    assert kf.first_at_or_after([], 0.0) is None


# ------------------------------------------------------------- seek_target

def test_seek_target_aims_half_a_gop_inside_the_gop():
    k, k_next = Fraction(10), Fraction(276, 10)
    target = kf.seek_target(k, Fraction(0), k_next, is_hls=False)
    assert target == (k + k_next) / 2
    assert target - k == (k_next - k) / 2


def test_seek_target_on_hls_aims_at_the_previous_gop():
    """HLSは要求より後ろのkeyframeへ飛ぶことがある(実測12%)。飛び先をkにする。"""
    k_prev, k = Fraction(10), Fraction(276, 10)
    target = kf.seek_target(k, k_prev, Fraction(45), is_hls=True)
    assert k_prev < target < k
    assert target == (k_prev + k) / 2


def test_seek_target_returns_a_fraction_from_float_inputs():
    target = kf.seek_target(27.6, 10.0, 45.2, is_hls=False)
    assert isinstance(target, Fraction)


def test_seek_target_needs_the_next_key_on_a_plain_input():
    with pytest.raises(ValueError):
        kf.seek_target(Fraction(10), Fraction(0), None, is_hls=False)


def test_seek_target_needs_the_previous_key_on_hls():
    with pytest.raises(ValueError):
        kf.seek_target(Fraction(10), None, Fraction(20), is_hls=True)


def test_seek_target_rejects_neighbours_on_the_wrong_side():
    with pytest.raises(ValueError):
        kf.seek_target(Fraction(10), Fraction(0), Fraction(10), is_hls=False)
    with pytest.raises(ValueError):
        kf.seek_target(Fraction(10), Fraction(10), Fraction(20), is_hls=True)


# ------------------------------------------------------------- 回帰(16.3→33.9)

def _copy_span(keys, ss_text: str, end: Fraction) -> Fraction:
    """``-ss <ss_text> -i src -to <end> -copyts`` のstream copyが出す尺。

    stream copyは要求時刻の**直前のkeyframe**から始まる。``concat.cut_part`` は ``-ss`` を
    ``f"{start:.3f}"`` で渡すので、丸めはここに現れる。"""
    start = float(ss_text)
    began = max((k for k in keys if k <= start), default=None)
    assert began is not None
    return end - began


def test_naming_the_keyframe_itself_loses_a_whole_gop():
    """reelの実記録: 0.0003秒の丸めで16.3秒の切り出しが33.9秒になった。

    keyframeを秒で持ち回る形(``-ss`` に狙点そのものを渡す)が、実際にその結果を出すこと。"""
    keys = [Fraction(900000, 90000), Fraction(2484003, 90000), Fraction(4068003, 90000)]
    k = keys[1]
    end = k + Fraction(163, 10)

    naive = _copy_span(keys, f"{float(k):.3f}", end)
    assert float(naive) == pytest.approx(33.9, abs=0.01)


def test_seek_target_keeps_the_requested_16_3_seconds():
    """同じ素材・同じ丸めでも、半GOP内側を狙えば要求どおり16.3秒で出る。"""
    keys = [Fraction(900000, 90000), Fraction(2484003, 90000), Fraction(4068003, 90000)]
    k = keys[1]
    end = k + Fraction(163, 10)

    target = kf.seek_target(k, keys[0], keys[2], is_hls=False)
    fixed = _copy_span(keys, f"{float(target):.3f}", end)
    assert float(fixed) == pytest.approx(16.3, abs=0.01)


def test_hls_seek_target_still_lands_on_k_when_the_seek_jumps_forward():
    """HLSが1つ後ろのkeyframeへ飛んだ場合でも、着地はkであって内容を失わない。"""
    keys = [Fraction(900000, 90000), Fraction(2484003, 90000), Fraction(4068003, 90000)]
    k = keys[1]
    target = kf.seek_target(k, keys[0], keys[2], is_hls=True)

    landed_normally = max(key for key in keys if key <= float(f"{float(target):.3f}"))
    jumped_forward = kf.first_at_or_after(keys, target)
    assert landed_normally == keys[0]
    assert jumped_forward == k


# ------------------------------------------------------------- first_packet

async def test_first_packet_reports_the_pts_and_the_keyframe_flag(monkeypatch):
    seen = []
    _stub_probe(monkeypatch, "packet,132000,K__,\nprogram,stream,1/90000\nstream,1/90000\n", seen)
    pts, is_key = await kf.first_packet(Path("out.mp4"))
    assert pts == Fraction(132000, 90000)
    assert is_key is True
    interval = seen[0][seen[0].index("-read_intervals") + 1]
    assert interval == "%+#1"


async def test_first_packet_reports_a_non_keyframe_landing(monkeypatch):
    _stub_probe(monkeypatch, "packet,3000,___\nstream,1/90000\n")
    pts, is_key = await kf.first_packet(Path("out.mp4"))
    assert pts == Fraction(3000, 90000)
    assert is_key is False


async def test_first_packet_on_an_unreadable_file(monkeypatch):
    _stub_probe(monkeypatch, "")
    assert await kf.first_packet(Path("out.mp4")) == (None, False)


async def test_first_packet_on_an_na_pts(monkeypatch):
    _stub_probe(monkeypatch, "packet,N/A,K__,\nstream,1/90000\n")
    assert await kf.first_packet(Path("out.mp4")) == (None, False)


# ------------------------------------------------- 実ffmpeg(-m requires_ffmpeg)
#
# 上までは1本もffmpegを起こさない。ここから下だけが実binaryを要る: keyframeの位置は
# 測れても、``-ss`` がどこへ着地するかはffmpegに聞く以外に確かめようが無い。

_REAL_FFMPEG = (
    pytest.mark.requires_ffmpeg,
    pytest.mark.slow,
    pytest.mark.skipif(
        not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
        reason="needs a real ffmpeg/ffprobe on PATH",
    ),
)


def needs_ffmpeg(fn):
    for mark in _REAL_FFMPEG:
        fn = mark(fn)
    return fn


GOP_SECONDS = 2.0


@pytest.fixture(scope="module")
def hls_clip(tmp_path_factory):
    """keyframe 2秒間隔の20秒clipをHLS playlistとして貸す。``(Source, keys)``。

    container start_timeが0でない素材にするためTSを経由する(実録画と同じ形)。"""
    encoders = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-encoders"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if b"libx264" not in encoders.stdout:
        pytest.skip("needs libx264")
    work = tmp_path_factory.mktemp("keyframes")
    raw = work / "src.ts"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc=size=320x240:rate=30:duration=20",
         "-c:v", "libx264", "-g", "60", "-f", "mpegts", str(raw)], check=True)
    playlist = work / "index.m3u8"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-c", "copy", "-f", "hls",
         "-hls_time", "2", "-hls_list_size", "0",
         "-hls_segment_filename", str(work / "seg%05d.ts"), str(playlist)], check=True)
    source = hls_source.Source(playlist, tuple(rec.HLS_INPUT_ARGS), True,
                               hls_source._container_start_time(playlist))
    return source


def _cut(source, ss: float, end: float, out: Path) -> None:
    """``concat.cut_part`` と同じ引数順で切る。muxerの+1.4秒だけは着地が見えるよう外す。"""
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{ss:.3f}", *source.input_args,
         "-i", str(source.path), "-to", f"{end:.3f}", "-copyts", "-c", "copy",
         "-muxdelay", "0", "-muxpreload", "0", "-f", "mpegts", str(out)], check=True)


async def _land(source, ss: float, tmp_path: Path) -> float:
    """``-ss ss`` で切ったときに実際に始まる位置(media軸・秒)。"""
    out = tmp_path / "cut.ts"
    _cut(source, ss, ss + 4.0, out)
    pts, is_key = await kf.first_packet(out)
    assert is_key, "stream copyの先頭はkeyframeのはず"
    return float(pts) - source.media_offset


@needs_ffmpeg
async def test_real_probe_finds_the_keyframes_on_the_media_axis(hls_clip):
    """窓は絶対終端で渡すので、``5%11`` の窓には10.0秒のkeyframeも入る。

    ``5%+6`` 形式は尺を**最初に返ったpacket**(seekで4.0秒から読み始める)から数えるため
    10.0秒に届かなかった。絶対終端の方が要求どおりで、窓の外の手前のkeyframe(4.0秒)が
    返るのは変わらない — seekは直前のkeyframe近辺から読み始めるためで、事実なので捨てない。"""
    keys = await kf.video_keyframes(hls_clip, 5.0, 6.0)
    assert [float(k) for k in keys] == [pytest.approx(t, abs=1e-3)
                                        for t in (4.0, 6.0, 8.0, 10.0)]


@needs_ffmpeg
async def test_real_probe_window_does_not_scan_the_whole_file(hls_clip):
    keys = await kf.video_keyframes(hls_clip, 5.0, 6.0)
    assert max(keys) < 18.0


@needs_ffmpeg
async def test_real_probe_past_the_end_never_invents_a_key(hls_clip):
    """終端より後ろの窓では、窓の中のkeyframeを名乗らせない。

    **どちらの終わり方になるかをassertしてはいけない。** 終端より後ろのseekに対する
    ffprobeの反応はdemuxerで割れる(いずれも実測):

    - HLS demuxer: seekに失敗して終了コード1 → ``RuntimeError``
    - 生の .ts: seekが終端へ丸められ**末尾packetを1本返す** → その1本にK flagが付いて
      いれば ``video_keyframes`` は素材末尾のkeyframeを返して**正常終了する**

    窓を0.001秒にするとpacketは1本しか読まれないので、後者では「その1本がkeyframeだったか」
    という coin flip がそのまま結果になる。以前ここを ``pytest.raises`` で固定していたところ、
    full suiteで1度だけ赤くなった(単体・file単位・再実行では再現せず、原因は未特定)。
    ffprobeのどちらの反応も**捏造ではない**ので、両方を許して「窓の中のkeyframeを返さない」
    ことだけを見る。この不変条件はどちらの経路でも確定的に成り立つ。

    「keyframeが1つも無ければ例外」の厳密な検証はmock側のtest
    (``test_video_keyframes_raises_when_the_window_has_no_keyframe`` ほか)が持っている。"""
    window = (1000.0, 0.001)
    try:
        keys = await kf.video_keyframes(hls_clip, *window)
    except RuntimeError:
        return
    assert keys, "例外を出さずに空listを返すのは契約違反"
    assert not [k for k in keys if window[0] <= float(k) <= sum(window)]
    assert max(float(k) for k in keys) < 20.0, "20秒の素材より後ろの時刻は存在しない"


@needs_ffmpeg
async def test_real_seek_onto_the_keyframe_itself_loses_a_gop(hls_clip, tmp_path):
    """狙点そのものを ``-ss`` へ渡すと1 GOP手前へ落ちる(concatの16.3→33.9と同じ現象)。"""
    keys = await kf.video_keyframes(hls_clip, 5.0, 6.0)
    k = keys[1]
    assert await _land(hls_clip, float(k), tmp_path) == pytest.approx(
        float(k) - GOP_SECONDS, abs=1e-3)


@needs_ffmpeg
async def test_real_seek_target_lands_exactly_on_k(hls_clip, tmp_path):
    keys = await kf.video_keyframes(hls_clip, 5.0, 6.0)
    k = keys[1]
    target = kf.seek_target(k, keys[0], keys[2], is_hls=False)
    assert await _land(hls_clip, float(target), tmp_path) == pytest.approx(
        float(k), abs=1e-3)


@needs_ffmpeg
async def test_real_hls_seek_target_never_lands_after_k(hls_clip, tmp_path):
    """HLS側は内容を失わない方に倒す。飛ばなければk_prev、飛べばk。kより後ろは無い。"""
    keys = await kf.video_keyframes(hls_clip, 5.0, 6.0)
    k = keys[1]
    target = kf.seek_target(k, keys[0], keys[2], is_hls=True)
    landed = await _land(hls_clip, float(target), tmp_path)
    assert landed <= float(k) + 1e-3
    assert landed == pytest.approx(float(keys[0]), abs=1e-3)


@needs_ffmpeg
async def test_real_mpegts_muxer_shifts_the_output_by_1_4_seconds(hls_clip, tmp_path):
    """``first_packet`` の値をそのまま要求と比べてはいけない、の実証。"""
    keys = await kf.video_keyframes(hls_clip, 5.0, 6.0)
    target = kf.seek_target(keys[1], keys[0], keys[2], is_hls=False)
    out = tmp_path / "muxed.ts"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{float(target):.3f}", *hls_clip.input_args,
         "-i", str(hls_clip.path), "-to", f"{float(target) + 4:.3f}", "-copyts",
         "-c", "copy", "-f", "mpegts", str(out)], check=True)
    pts, _ = await kf.first_packet(out)
    expected = float(keys[1]) + hls_clip.media_offset + 1.4
    assert float(pts) == pytest.approx(expected, abs=1e-3)
