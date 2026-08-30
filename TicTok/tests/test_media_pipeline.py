"""End-to-end checks on the bytes ffmpeg actually produces.

Every other test in this suite stubs ffmpeg out and asserts on the argv we build.
That covers our branching but not the muxer's behaviour, which is where the video
defects have actually lived: the concat demuxer opening a ~0.1s hole in the audio at
every segment boundary, the container running ~5% past the media axis, the burn-in
landing comments on the wrong second. None of those change our argv, so none of them
were visible to an argv assertion.

These tests synthesise a real HLS capture, run the real finalize path over it, and
assert on the finalized file. They need ffmpeg on PATH and take a few seconds:

    pytest -m requires_ffmpeg          # just these
    pytest -m "not slow"               # everything else
"""
import shutil
import subprocess

import pytest

from tictok.core.layout import mp4_path as layout_mp4_path
from tictok.record import hls_pack
from tictok.record import recorder as rec
from tictok.record import video_overlay as vo

pytestmark = [
    pytest.mark.requires_ffmpeg,
    pytest.mark.slow,
    pytest.mark.skipif(
        not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
        reason="needs a real ffmpeg/ffprobe on PATH",
    ),
]

SEGMENTS = 8
SEGMENT_SECONDS = 2
# Inside every segment of the real stream the audio starts this far ahead of the
# video. Reproducing that offset is the whole point of the fixture (see below).
AUDIO_LEAD = 0.2
# The synthetic source is an unbroken sine, so any silence in the output is an
# artifact of our own muxing rather than content. 440Hz over a whole number of
# 2s segments closes the phase, so the joins are inaudible in a correct file.
TONE_HZ = 440


# --------------------------------------------------------------------------
# fixture: a captured HLS directory, shaped like the real one
# --------------------------------------------------------------------------


_MUX = ["-muxdelay", "0", "-muxpreload", "0"]


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", *args],
                   check=True, capture_output=True)


def make_video(path, width=160, height=120, seconds=SEGMENT_SECONDS):
    _ffmpeg("-f", "lavfi", "-i",
            "testsrc2=size=%dx%d:rate=30:duration=%d" % (width, height, seconds),
            "-c:v", "libx264", "-preset", "ultrafast", "-g", str(seconds * 30),
            *_MUX, str(path))


def make_audio(path, rate=44100, channels=1, seconds=SEGMENT_SECONDS):
    _ffmpeg("-f", "lavfi", "-i",
            "sine=frequency=%d:duration=%d:sample_rate=%d" % (TONE_HZ, seconds, rate),
            "-ac", str(channels), "-c:a", "aac", *_MUX, str(path))


def make_segment(path, video, audio, index, base_offset=0.0):
    """One capture segment, carrying the property that made the concat demuxer
    misbehave: the audio starts AUDIO_LEAD ahead of the video inside the segment.

    This has to be built segment by segment. ffmpeg's own hls muxer cuts on a video
    keyframe and starts each segment's audio at or after that cut, so segments it
    produces have the audio *trailing* — the opposite of the live source, whose
    packager carries audio from before the keyframe. A fixture built with the hls
    muxer cannot reproduce the defect, and every assertion below then passes against
    the broken implementation. -itsoffset shifts the video against the audio;
    -output_ts_offset stamps the pair onto the timeline so segments join seamlessly.
    """
    _ffmpeg("-itsoffset", str(AUDIO_LEAD), "-i", str(video), "-i", str(audio),
            "-map", "0:v", "-map", "1:a", "-c", "copy", "-copyts",
            "-output_ts_offset", str(base_offset + index * SEGMENT_SECONDS),
            *_MUX, str(path))


def write_index(hls, names, extinf=SEGMENT_SECONDS):
    """The captured playlist. Deliberately NOT terminated with #EXT-X-ENDLIST: live
    capture is force-terminated on stop (on Windows send_signal maps SIGTERM to
    TerminateProcess), so ffmpeg never gets to close it. finalize must cope."""
    body = ["#EXTM3U", "#EXT-X-VERSION:6",
            "#EXT-X-TARGETDURATION:%d" % (int(extinf) + 1)]
    for name in names:
        body.append("#EXTINF:%.6f," % extinf)
        body.append(name)
    (hls / "index.m3u8").write_text("\n".join(body) + "\n", encoding="utf-8")


def build_capture(hls, count=SEGMENTS, base_offset=0.0):
    """A clean capture of ``count`` uniform segments.

    ``base_offset`` は配信側のtimestampが0から始まらない実配信を再現する(実測1.438s)。
    既定の0は「たまたま0始まり」のcaptureで、offsetを引き忘れる欠陥を隠してしまう。"""
    make_video(hls / "v.ts")
    make_audio(hls / "a.ts")
    names = []
    for i in range(count):
        name = "seg%05d.ts" % i
        make_segment(hls / name, hls / "v.ts", hls / "a.ts", i, base_offset)
        names.append(name)
    (hls / "v.ts").unlink()
    (hls / "a.ts").unlink()
    write_index(hls, names)
    return names


def recorder_for(hls):
    r = rec.Recorder.__new__(rec.Recorder)
    r.hls_dir = hls
    r.playlist = hls / "index.m3u8"
    r.base = "fixture"
    r.unique_id = "fixture"
    r._volume_paths = lambda: []
    # 音量正規化は再mp4化からしか渡らない。ここで見たいのは結合そのものなので素のまま。
    r._normalize_audio = None
    return r


@pytest.fixture(scope="module")
def hls_capture(tmp_path_factory):
    hls = tmp_path_factory.mktemp("hls")
    build_capture(hls)
    return hls


def test_the_fixture_reproduces_the_audio_lead(hls_capture):
    """Guards the fixture itself. If a future ffmpeg stops honouring the offsets, the
    segments silently become well-formed and every test below turns into a no-op that
    passes against a broken implementation."""
    seg = hls_capture / "seg00002.ts"

    v = _packets(seg, "v")[0][0]
    a = _packets(seg, "a")[0][0]

    assert a < v, "fixture segment has audio at %.3f, video at %.3f" % (a, v)
    assert abs((v - a) - AUDIO_LEAD) < 0.05


@pytest.fixture(scope="module")
def finalized(hls_capture, tmp_path_factory):
    """(mp4_path, kept) after running the real concat over the captured segments."""
    import asyncio

    work = tmp_path_factory.mktemp("final")
    r = recorder_for(hls_capture)

    kept = r._playlist_segments()
    mp4 = work / "fixture.mp4"
    assert asyncio.run(r._concat_to_mp4(mp4)) is True
    return mp4, kept, r


# --------------------------------------------------------------------------
# probes
# --------------------------------------------------------------------------


def _packets(path, stream):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-i", str(path), "-select_streams", stream,
         "-show_entries", "packet=pts_time,duration_time", "-of", "csv=p=0"],
        capture_output=True, text=True, check=True,
    ).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(",")
        if len(parts) >= 2:
            try:
                rows.append((float(parts[0]), float(parts[1])))
            except ValueError:
                continue
    return rows


def _stream_duration(path, stream):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries",
         "stream=duration", "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(out.strip().splitlines()[0])


def _silence_starts(path, after=1.0):
    """Silence run starts, ignoring the encoder's priming at the very head."""
    err = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a",
         "-af", "silencedetect=noise=-50dB:d=0.05", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    starts = []
    for line in err.splitlines():
        if "silence_start:" in line:
            try:
                starts.append(float(line.split("silence_start:")[1].strip()))
            except ValueError:
                continue
    return [s for s in starts if s >= after]


# --------------------------------------------------------------------------
# the audio track must cover its own timeline
# --------------------------------------------------------------------------


def test_finalized_audio_has_no_pts_gaps(finalized):
    """The bug: the concat demuxer left ~0.1s of unbacked timeline at every segment
    boundary. Filling those holes clicks; packing them away drifts Chrome ahead of the
    video. Neither is fixable downstream, so the join must not open them."""
    mp4, _, _ = finalized

    packets = _packets(mp4, "a")
    gaps = [(pts, pts - prev_end)
            for (pts, _), prev_end in zip(packets[1:],
                                          (p + d for p, d in packets))
            if pts - prev_end > 0.02]

    assert gaps == [], "audio timeline has %d hole(s): %s" % (len(gaps), gaps[:5])


def test_finalized_audio_is_continuous_sound(finalized):
    """The audible symptom, asserted directly: the source is an unbroken sine, so a
    silent run anywhere in the output is stuffing that covers a hole we created."""
    mp4, _, _ = finalized

    assert _silence_starts(mp4) == []


def test_audio_and_video_durations_agree(finalized):
    """The sync indicator (container length is not one): the two tracks must span the
    same timeline, or players that honour timestamps and players that pack samples
    will disagree about where the audio belongs."""
    mp4, _, _ = finalized

    assert abs(_stream_duration(mp4, "a") - _stream_duration(mp4, "v")) < 0.2


# --------------------------------------------------------------------------
# the container timeline must equal the media timeline the burn-in maps against
# --------------------------------------------------------------------------


def test_container_does_not_run_past_the_media_axis(finalized):
    """The concat demuxer inflated the container ~5% past the media (#EXTINF) axis.
    Comments, battle panels and gift slots are all placed on the media axis, so any
    inflation has to be modelled per segment or every overlay lands late."""
    mp4, kept, _ = finalized

    extinf_sum = sum(extinf for _, extinf, _, _, _ in kept)
    container = _stream_duration(mp4, "a")

    # The concat demuxer inflates this fixture by ~9%; the HLS demuxer leaves ~0.7%,
    # which is the AAC encoder padding one segment's worth of frames, not drift.
    assert abs(container - extinf_sum) / extinf_sum < 0.03, (
        "container %.3fs vs media axis %.3fs" % (container, extinf_sum))


async def test_media_pts_axis_is_near_identity(finalized):
    """With the HLS demuxer a segment contributes exactly its #EXTINF, so the map the
    burn-in uses should be a straight line. This is the single axis every overlay
    (comments, battle, gifts) is placed on -- see video_overlay._anchor_mappers."""
    mp4, kept, r = finalized

    media_pts = await r._build_media_pts(kept, mp4)

    assert media_pts is not None
    span = media_pts[-1][0]
    worst = max(abs(pts - media) for media, pts in media_pts)
    assert worst / span < 0.03, "media->pts bends by %.3fs over %.1fs" % (worst, span)


# --------------------------------------------------------------------------
# the segment set the mux sees
# --------------------------------------------------------------------------


def test_every_captured_segment_reaches_the_mux(hls_capture, finalized):
    """A segment silently missing from the join loses that slice of the broadcast and
    shifts everything after it against the wall-clock anchors."""
    _, kept, _ = finalized

    on_disk = {p.name for p in hls_capture.glob("seg*.ts")}
    assert {p.name for p, _, _, _, _ in kept} == on_disk


def test_vod_playlist_is_what_the_demuxer_reads(finalized, hls_capture):
    """The captured index is never terminated (capture is hard-killed), so the mux must
    be driven by the VOD playlist written at finalize -- otherwise the HLS demuxer
    treats the list as live and seeks to the live edge."""
    _, _, _ = finalized

    written = hls_capture / rec.VOD_PLAYLIST_NAME
    assert written.is_file()
    body = written.read_text(encoding="utf-8")
    assert "#EXT-X-PLAYLIST-TYPE:VOD" in body
    assert body.rstrip().endswith("#EXT-X-ENDLIST")
    assert "#EXT-X-ENDLIST" not in (hls_capture / "index.m3u8").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# what a multi-hour live broadcast actually throws at finalize
#
# Each case below was found by building the shape and running the real finalize
# path over it, not by reading the code. The three that assert on a defect
# (duplicate names, a rewound clock, a single segment) were all reproducing real
# misbehaviour when written.
# --------------------------------------------------------------------------


def _finalize(hls, tmp_path):
    """Run the real concat + timing map over ``hls``; return (mp4, kept, timing)."""
    import asyncio
    import json

    r = recorder_for(hls)
    kept = r._playlist_segments()
    mp4 = tmp_path / "out.mp4"
    assert asyncio.run(r._concat_to_mp4(mp4)) is True
    asyncio.run(r._write_timing_map(mp4))
    tpath = rec.timing_path(mp4)
    timing = json.loads(tpath.read_text(encoding="utf-8")) if tpath.is_file() else None
    return mp4, kept, timing


def test_a_repeated_segment_name_is_not_muxed_twice(tmp_path):
    """ffmpeg's hls muxer restarts its segment counter, so relaunching into the same
    directory (append_list) can list a name twice. Muxing both replays that slice: the
    container outruns the media axis and every overlay after the repeat lands seconds
    late. Measured before the guard: media axis 10.0s, container 14.27s."""
    hls = tmp_path / "hls"
    hls.mkdir()
    names = build_capture(hls, count=4)
    write_index(hls, names + [names[2]])          # seg00002 listed twice

    mp4, kept, timing = _finalize(hls, tmp_path)

    assert [p.name for p, _, _, _, _ in kept] == names
    media = timing["media_duration"]
    container = _stream_duration(mp4, "v")
    assert abs(container - media) / media < 0.03, (
        "container %.3fs vs media axis %.3fs" % (container, media))


def test_a_rewound_wall_clock_still_yields_ordered_anchors(tmp_path):
    """Segment mtimes are the wall side of the timing map, and an NTP correction or a
    DST change can move them backwards. The burn-in sorts anchors by wall
    (video_overlay._load_timing_anchors), which reorders the media column with them --
    so an out-of-order pair does not misplace one comment, it corrupts the whole map."""
    import os

    hls = tmp_path / "hls"
    hls.mkdir()
    names = build_capture(hls, count=6)
    base = 1_700_000_000.0
    for i, name in enumerate(names):
        stamp = base + i * SEGMENT_SECONDS - (30.0 if i >= 3 else 0.0)
        os.utime(hls / name, (stamp, stamp))

    _, kept, timing = _finalize(hls, tmp_path)

    assert len(kept) == len(names), "a clock rewind must not discard segments"
    walls = [w for w, _ in timing["anchors"]]
    assert walls == sorted(walls)
    assert len(set(walls)) == len(walls), "anchors must be strictly ascending"


def test_a_single_segment_recording_still_gets_a_timing_map(tmp_path):
    """The zero point is the second anchor, so one segment is enough. Requiring two
    silently denied a map to every very short recording -- and to any recording whose
    other segments were dropped -- leaving its comment sync to the approximate model."""
    hls = tmp_path / "hls"
    hls.mkdir()
    build_capture(hls, count=1)

    _, kept, timing = _finalize(hls, tmp_path)

    assert len(kept) == 1
    assert timing is not None and len(timing["anchors"]) >= 2


def test_an_empty_segment_freezes_rather_than_shifting(tmp_path):
    """A write that never landed loses that media, but the surrounding segments keep
    their own timestamps, so the hole stays a hole instead of pulling everything after
    it earlier. Losing content is survivable; shifting the axis silently is not."""
    hls = tmp_path / "hls"
    hls.mkdir()
    names = build_capture(hls, count=6)
    (hls / names[3]).write_bytes(b"")

    mp4, kept, timing = _finalize(hls, tmp_path)

    assert len(kept) == len(names), "the media time still elapsed; keep the entry"
    pts = sorted(p for p, _ in _packets(mp4, "v"))
    holes = [(a, b - a) for a, b in zip(pts, pts[1:]) if b - a > 0.5]
    assert len(holes) == 1, "expected exactly one freeze, got %s" % (holes,)
    assert abs(holes[0][1] - SEGMENT_SECONDS) < 0.5
    container = _stream_duration(mp4, "v")
    assert abs(container - timing["media_duration"]) / timing["media_duration"] < 0.03


def test_a_mid_stream_resolution_change_keeps_both_resolutions(tmp_path):
    """Broadcasters switch resolution mid-stream. The join is a stream copy, so both
    must survive it intact -- collapsing them is the normalize step's job, and it can
    only do that if the frames are still here."""
    hls = tmp_path / "hls"
    hls.mkdir()
    make_video(hls / "small.ts", 160, 120)
    make_video(hls / "large.ts", 320, 240)
    make_audio(hls / "a.ts")
    names = []
    for i in range(6):
        name = "seg%05d.ts" % i
        make_segment(hls / name, hls / ("small.ts" if i < 3 else "large.ts"),
                     hls / "a.ts", i)
        names.append(name)
    for tmp in ("small.ts", "large.ts", "a.ts"):
        (hls / tmp).unlink()
    write_index(hls, names)

    mp4, _, _ = _finalize(hls, tmp_path)

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
         "frame=width,height", "-of", "csv=p=0", str(mp4)],
        capture_output=True, text=True, check=True).stdout
    sizes = {line.strip().rstrip(",") for line in out.splitlines() if line.strip()}
    assert "160,120" in sizes and "320,240" in sizes, sizes


def test_a_pts_wraparound_mid_recording_is_absorbed(tmp_path):
    """MPEG-TS timestamps are 33 bits at 90kHz, so they wrap every 2^33/90000 =
    95443.7s (~26.5h). The broadcaster's encoder clock has been running long before we
    tune in, so the wrap can land inside a recording of any length.

    This matters more than it used to: the concat demuxer re-based every segment onto
    its own offset, which hid a wrap, while the HLS demuxer carries the segments' own
    timestamps. Guarding it keeps that trade visible."""
    wrap = 2 ** 33 / 90000.0
    hls = tmp_path / "hls"
    hls.mkdir()
    make_video(hls / "v.ts")
    make_audio(hls / "a.ts")
    names = []
    for i in range(6):
        name = "seg%05d.ts" % i
        # Straddle the wrap: the first segments sit just below it, the rest just above.
        _ffmpeg("-itsoffset", str(AUDIO_LEAD), "-i", str(hls / "v.ts"),
                "-i", str(hls / "a.ts"), "-map", "0:v", "-map", "1:a",
                "-c", "copy", "-copyts",
                "-output_ts_offset", "%.3f" % (wrap - 6.0 + i * SEGMENT_SECONDS),
                *_MUX, str(hls / name))
        names.append(name)
    (hls / "v.ts").unlink()
    (hls / "a.ts").unlink()
    write_index(hls, names)

    mp4, kept, timing = _finalize(hls, tmp_path)

    assert len(kept) == len(names)
    media = timing["media_duration"]
    assert abs(_stream_duration(mp4, "v") - media) / media < 0.03
    assert max(abs(p - m) for m, p in timing["media_pts"]) / media < 0.03


# --------------------------------------------------------------------------
# a resolution change INSIDE one segment
#
# The case above switches on a segment boundary, which is the minority: measured
# on the real stream, 29 of 40 resolution changes land inside a single segment.
# A boundary switch is visible to anything that looks at one dimension per file;
# an in-segment switch is not, and it is the shape that actually occurs.
# --------------------------------------------------------------------------


HALF_SECONDS = SEGMENT_SECONDS // 2


def make_split_segment(path, video_a, video_b, audio, index):
    """One capture segment whose resolution changes partway through the file.

    Two half-length segments carrying different video are byte-concatenated. MPEG-TS
    is self-delimiting and every segment carries its own PAT/PMT, so the result is a
    single file with a second SPS -- and therefore a second keyframe -- in the middle,
    which is what the live packager writes when the broadcaster switches mid-segment.
    """
    halves = []
    for n, video in enumerate((video_a, video_b)):
        part = path.parent / ("%s.half%d.ts" % (path.stem, n))
        _ffmpeg("-itsoffset", str(AUDIO_LEAD), "-i", str(video), "-i", str(audio),
                "-map", "0:v", "-map", "1:a", "-c", "copy", "-copyts",
                "-output_ts_offset",
                str(index * SEGMENT_SECONDS + n * HALF_SECONDS), *_MUX, str(part))
        halves.append(part)
    path.write_bytes(b"".join(p.read_bytes() for p in halves))
    for part in halves:
        part.unlink()


def build_split_capture(hls, count=6, switch_at=2, small=(160, 120), large=(320, 240)):
    """A capture that changes resolution inside segment ``switch_at`` -- the segments
    before it are uniformly ``small``, the ones after uniformly ``large``."""
    make_video(hls / "small.ts", *small)
    make_video(hls / "large.ts", *large)
    make_video(hls / "small_half.ts", *small, seconds=HALF_SECONDS)
    make_video(hls / "large_half.ts", *large, seconds=HALF_SECONDS)
    make_audio(hls / "a.ts")
    make_audio(hls / "a_half.ts", seconds=HALF_SECONDS)
    names = []
    for i in range(count):
        name = "seg%05d.ts" % i
        if i == switch_at:
            make_split_segment(hls / name, hls / "small_half.ts",
                               hls / "large_half.ts", hls / "a_half.ts", i)
        else:
            source = "small.ts" if i < switch_at else "large.ts"
            make_segment(hls / name, hls / source, hls / "a.ts", i)
        names.append(name)
    for tmp in ("small.ts", "large.ts", "small_half.ts", "large_half.ts",
                "a.ts", "a_half.ts"):
        (hls / tmp).unlink()
    write_index(hls, names)
    return names


def _keyframe_sizes(path):
    """Distinct (w, h) across the video keyframes of ``path``, read straight from
    ffprobe so the assertion does not depend on our own parsing of its output."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-skip_frame", "nokey", "-select_streams", "v:0",
         "-show_entries", "frame=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout
    sizes = set()
    for line in out.splitlines():
        parts = [p for p in line.strip().split(",") if p]
        if len(parts) >= 2:
            sizes.add((int(parts[0]), int(parts[1])))
    return sizes


def test_the_split_segment_really_switches_inside_one_file(tmp_path):
    """Guards the fixture. If the halves stop being joined into one file this case
    silently degrades into the boundary switch already covered above, and every
    assertion below passes without an in-segment change ever existing."""
    hls = tmp_path / "hls"
    hls.mkdir()
    names = build_split_capture(hls)

    assert _keyframe_sizes(hls / names[2]) == {(160, 120), (320, 240)}
    assert _keyframe_sizes(hls / names[1]) == {(160, 120)}
    assert _keyframe_sizes(hls / names[3]) == {(320, 240)}


async def test_the_keyframe_probe_sees_a_switch_inside_a_segment(tmp_path):
    """probe_mp4_resolutions is the only thing that decides a recording is mixed. It
    scans keyframes precisely so an in-segment switch cannot hide: a probe reading one
    dimension per file (or per segment) would call this recording uniform and hand the
    player a track that changes size mid-playback."""
    hls = tmp_path / "hls"
    hls.mkdir()
    build_split_capture(hls)
    r = recorder_for(hls)
    mp4 = tmp_path / "out.mp4"
    assert await r._concat_to_mp4(mp4) is True

    assert await rec.probe_mp4_resolutions(mp4) == {(160, 120), (320, 240)}
    # The concat runs the same probe over the playlist in parallel; the two paths must
    # agree, or normalization silently depends on which one answered.
    assert r._concat_resolutions == {(160, 120), (320, 240)}


async def test_a_switch_inside_a_segment_is_normalized_to_one_resolution(tmp_path):
    """The player-visible defect: a track that changes size mid-file freezes or zooms
    in the browser. Normalization is what collapses it, and it only runs when the probe
    above reported the switch -- so this is the end of that chain, asserted on the
    finished file rather than on the decision to run."""
    hls = tmp_path / "hls"
    hls.mkdir()
    build_split_capture(hls)
    r = recorder_for(hls)
    mp4 = tmp_path / "out.mp4"
    assert await r._concat_to_mp4(mp4) is True
    assert len(_keyframe_sizes(mp4)) == 2

    await r._normalize_mixed_resolution(mp4)

    # The largest seen becomes the canvas; every smaller frame is fitted onto it.
    assert _keyframe_sizes(mp4) == {(320, 240)}


async def test_normalizing_an_in_segment_switch_keeps_the_whole_recording(tmp_path):
    """A re-encode that stops early still exits 0. Losing the tail here would replace a
    good recording with a truncated one, and a source that changes resolution mid-GOP
    is exactly where the decoder is most likely to stall."""
    hls = tmp_path / "hls"
    hls.mkdir()
    names = build_split_capture(hls)
    r = recorder_for(hls)
    mp4 = tmp_path / "out.mp4"
    assert await r._concat_to_mp4(mp4) is True
    before = _stream_duration(mp4, "v")

    await r._normalize_mixed_resolution(mp4)

    after = _stream_duration(mp4, "v")
    assert abs(after - before) / before < 0.05, (
        "%d segment(s): %.3fs -> %.3fs" % (len(names), before, after))


# --------------------------------------------------------------------------
# the burn-in canvas, on mixed material
#
# _probe_dimensions reads stream=width,height, which is ONE pair, and that pair
# becomes the output canvas for the whole burn-in (_render_dimensions, scale_to).
# These record what that produces today for a source carrying more than one
# resolution; they are not a statement that it is the right answer.
# --------------------------------------------------------------------------


def mixed_resolution_mp4(work, first, second):
    """An mp4 whose video track changes from ``first`` to ``second`` halfway."""
    work.mkdir(parents=True, exist_ok=True)
    make_video(work / "h0.ts", first[0], first[1], HALF_SECONDS)
    make_video(work / "h1.ts", second[0], second[1], HALF_SECONDS)
    make_audio(work / "ha.ts", seconds=HALF_SECONDS)
    make_split_segment(work / "mixed.ts", work / "h0.ts", work / "h1.ts",
                       work / "ha.ts", 0)
    out = work / "mixed.mp4"
    _ffmpeg("-fflags", "+genpts", "-i", str(work / "mixed.ts"), "-c:v", "copy",
            "-c:a", "aac", "-avoid_negative_ts", "make_zero", str(out))
    return out


async def test_probe_dimensions_covers_every_resolution_not_just_the_opening_one(tmp_path):
    """The dimension probe must answer for the whole recording, not for whichever
    resolution the file happens to open on. It used to answer with the opening pair, so
    the burn-in and the normalizer disagreed about what the same recording was."""
    small_first = mixed_resolution_mp4(tmp_path / "a", (160, 120), (320, 240))
    large_first = mixed_resolution_mp4(tmp_path / "b", (320, 240), (160, 120))

    assert (await vo._probe_dimensions(small_first))[:2] == (320, 240)
    assert (await vo._probe_dimensions(large_first))[:2] == (320, 240)

    assert await rec.probe_mp4_resolutions(small_first) == {(160, 120), (320, 240)}
    assert await rec.probe_mp4_resolutions(large_first) == {(160, 120), (320, 240)}


async def test_the_render_canvas_covers_the_whole_recording(tmp_path, monkeypatch):
    """width/height/scale_to for the burn-in must describe the whole recording. Order
    must not matter: the same two resolutions produce the same canvas either way."""
    monkeypatch.setattr(vo, "_font_em", {(vo.COMMENT_FONT, False, None): (1.0, 0.5)})
    cfg = {"video_overlay_min_height": 1920, "video_overlay_icon_percent": 5,
           "video_overlay_quality": 21, "video_overlay_codec": 1,
           "video_overlay_subtitles": 0}
    small_first = mixed_resolution_mp4(tmp_path / "a", (160, 120), (320, 240))
    large_first = mixed_resolution_mp4(tmp_path / "b", (320, 240), (160, 120))

    opens_small = await vo._render_context(small_first, cfg, None)
    opens_large = await vo._render_context(large_first, cfg, None)

    assert (opens_small["src_w"], opens_small["src_h"]) == (320, 240)
    assert (opens_large["src_w"], opens_large["src_h"]) == (320, 240)
    assert (opens_small["width"], opens_small["height"]) == (2560, 1920)
    assert (opens_large["width"], opens_large["height"]) == (2560, 1920)
    assert opens_small["scale_to"] == (2560, 1920)


async def test_an_aspect_changing_switch_lands_on_a_canvas_that_holds_both(
        tmp_path, monkeypatch):
    """The case that actually distorted: two resolutions with different aspect ratios.
    The canvas has to bound both, so neither stretch is squeezed and the order it was
    recorded in cannot change the output shape."""
    monkeypatch.setattr(vo, "_font_em", {(vo.COMMENT_FONT, False, None): (1.0, 0.5)})
    cfg = {"video_overlay_min_height": 960, "video_overlay_icon_percent": 5,
           "video_overlay_quality": 21, "video_overlay_codec": 1,
           "video_overlay_subtitles": 0}
    opens_portrait = mixed_resolution_mp4(tmp_path / "a", (120, 160), (160, 120))
    opens_landscape = mixed_resolution_mp4(tmp_path / "b", (160, 120), (120, 160))

    portrait = await vo._render_context(opens_portrait, cfg, None)
    landscape = await vo._render_context(opens_landscape, cfg, None)

    assert (portrait["width"], portrait["height"]) == (960, 960)
    assert (landscape["width"], landscape["height"]) == (960, 960)
    assert await rec.probe_mp4_resolutions(opens_portrait) == \
        await rec.probe_mp4_resolutions(opens_landscape)


# --------------------------------------------------------------------------
# packing, from the recorder's side
#
# hls_pack deletes every segment file. Everything finalize knows about a segment
# (order, #EXTINF, wall-clock mtime) has to survive that deletion, because the
# timing map is built from it after the files are gone.
# --------------------------------------------------------------------------


async def test_packing_does_not_move_the_wall_axis(tmp_path):
    """Segment mtimes are one side of every timing-map anchor, and packing deletes the
    files that carry them. If a single wall shifts, the burn-in puts comments on the
    wrong second for the whole recording -- and it fails silently, because the packed
    recording is otherwise perfectly playable."""
    import os

    hls = tmp_path / "hls"
    hls.mkdir()
    names = build_capture(hls, count=4)
    for i, name in enumerate(names):
        stamp = 1_700_000_000.0 + i * SEGMENT_SECONDS
        os.utime(hls / name, (stamp, stamp))
    r = recorder_for(hls)
    before = r._playlist_segments()

    assert (await hls_pack.pack_session(hls))["packed"] is True

    after = r._playlist_segments()
    assert [(extinf, wall, disc) for _, extinf, wall, disc, _ in after] == \
        [(extinf, wall, disc) for _, extinf, wall, disc, _ in before]
    # Before packing a segment is its own file; after, it is a range inside the pack,
    # and the ranges have to tile it without a gap or the mux reads torn TS packets.
    assert all(byterange is None for *_, byterange in before)
    ranges = [byterange for *_, byterange in after]
    assert all(r is not None for r in ranges)
    assert ranges[0][0] == 0
    for (offset, length), (next_offset, _) in zip(ranges, ranges[1:]):
        assert offset + length == next_offset


async def test_a_packed_recording_still_finalizes_to_the_same_mp4(tmp_path):
    """Packing is a byte-level rearrangement, so the mux must not be able to tell. This
    is the assertion that makes packing safe to run on a recording that has not been
    finalized yet: the segments are gone, and only the byte ranges stand in for them."""
    hls = tmp_path / "hls"
    hls.mkdir()
    build_capture(hls, count=4)
    loose = tmp_path / "loose.mp4"
    assert await recorder_for(hls)._concat_to_mp4(loose) is True

    assert (await hls_pack.pack_session(hls))["packed"] is True
    packed = tmp_path / "packed.mp4"
    assert await recorder_for(hls)._concat_to_mp4(packed) is True

    assert abs(_stream_duration(packed, "v") - _stream_duration(loose, "v")) < 0.05
    assert len(_packets(packed, "v")) == len(_packets(loose, "v"))


# ===== finalize: mp4を作らずに録画を確定する =====


def _finalize_recorder(hls, record_dir, stem="fixture"):  # noqa: D401
    """finalize() を最後まで通せる最小のRecorder。__new__で組むのは他のfixtureと同じ
    (capture側の起動経路はここでの関心事ではない)。"""
    import time as _time

    r = recorder_for(hls)
    r.base = stem
    r._record_dir = record_dir
    r._final_dir = record_dir          # 移送は別経路。ここでは走らせない
    r.state = rec.STATE_RECORDING
    r.error = None
    r.started_at = _time.time() - 60
    r.ended_at = _time.time()
    r.duration_seconds = None
    r.output_path = None
    r.recording_id = None
    r.quality = None
    r._launch_attempts = 1
    r._capture_args = []
    r._disk_report = []
    r._on_finalize = None
    r._on_notify = None
    r._on_ops = None
    r._ops_sink = None
    r._notify_cb = None
    r._live_bookmarks = []
    r._storage = None
    r._mp4_path = layout_mp4_path(record_dir, r.base, r.unique_id)
    r._mp4_path.parent.mkdir(parents=True, exist_ok=True)
    return r


@pytest.fixture(scope="module")
def finalized_recording(hls_capture, tmp_path_factory):
    """実際の finalize() を1本通した結果。"""
    import asyncio

    from tictok.core import layout

    # layout規約どおりのstemを使う。hls_sourceはmp4の名前から配信者とsession dirを解くので、
    # 規約外の名前だと「素材が無い」に見えてしまう(fixtureの都合で本番と違う結論が出る)。
    record_dir = tmp_path_factory.mktemp("recroot")
    stem = "00001_fixture_20260101_120000"
    hls = layout.session_dir(record_dir, stem, "fixture")
    hls.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(hls_capture, hls)
    r = _finalize_recorder(hls, record_dir, stem)
    asyncio.run(r._finalize())
    return r


def test_finalize_does_not_build_an_mp4(finalized_recording):
    """録画の実体は .ts である。焼き込みが .ts を直接読むようになり、中間mp4を要求する
    下流が居なくなったので、finalizeは配信全長を書き直す結合passを走らせない。"""
    r = finalized_recording
    assert r.state == rec.STATE_COMPLETED
    assert r.output_path is not None
    assert r.output_path.suffix == ".mp4"
    assert not r.output_path.exists(), "finalizeがmp4を作っている"


def test_finalize_keeps_the_mp4_path_as_the_recordings_identity(finalized_recording):
    """実在しないmp4 pathを指すのは意図的。sidecarの在処もhls_sourceが .ts を引く鍵も
    この名前から決まるので、playlist pathへ振り替えてはいけない。"""
    from tictok.media import hls_source

    r = finalized_recording
    assert hls_source.has_hls_source(r.output_path)
    assert hls_source.session_dir_for(r.output_path) == r.hls_dir


def test_finalize_measures_the_duration_from_the_media_axis(finalized_recording):
    """尺はEXTINF累計。焼き込みが開くplaylistの尺と定義上同一でなければならない。"""
    r = finalized_recording
    expected = sum(extinf for _, extinf, _, _, _ in r._playlist_segments())
    assert r.duration_seconds == pytest.approx(expected)


def test_finalize_leaves_the_segments_in_place(finalized_recording):
    """素材を消さない。ここが原本である。"""
    from tictok.core import layout

    r = finalized_recording
    assert layout.has_media(r.hls_dir)


def test_finalize_builds_an_mp4_only_when_explicitly_asked(hls_capture, tmp_path_factory):
    """「mp4化」operationは今も本物のmp4を出す。

    finalizeの既定がmp4を作らなくなったので、この引数が落ちると操作は成功したのにfileが
    無い、という壊れ方をする。同じfinalize経路の両モードを1本で押さえる。"""
    import asyncio

    from tictok.core import layout

    record_dir = tmp_path_factory.mktemp("recroot_mp4")
    stem = "00002_fixture_20260101_130000"
    hls = layout.session_dir(record_dir, stem, "fixture")
    hls.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(hls_capture, hls)
    r = _finalize_recorder(hls, record_dir, stem)

    asyncio.run(r._finalize(build_mp4=True))

    assert r.state == rec.STATE_COMPLETED
    assert r.output_path.is_file(), "build_mp4=Trueでmp4が作られていない"
    assert r.output_path.stat().st_size > 0
    # 原本は消えない。mp4は書き出しであって置き換えではない。
    assert layout.has_media(hls)


def test_transcription_puts_the_media_axis_at_zero_for_hls(tmp_path_factory):
    """文字起こしの時刻は**playerがseekする軸**(0始まり)で出す。

    文字起こしだけはffmpegではなくPyAVで自前decodeしており、**PyAVはffmpegと違って
    containerの先頭を0へ寄せない**。HLSのsegmentは0始まりとは限らず(実配信の実測で
    1.438s)、引かずに出すと全segmentがそのぶん後ろへずれて字幕clickのseekが丸ごと
    ずれる。ffmpeg経由の他の下流では起きない、この経路だけの穴である。"""
    av = pytest.importorskip("av")

    from tictok.core import layout
    from tictok.media import hls_source
    from tictok.record.transcription import _decode_audio_with_media_map

    # 0始まりでないcaptureを作る。共有fixtureは0始まりで、offsetを引き忘れる欠陥を
    # そのまま通してしまう(この test を書いた時に実際に通った)。
    record_dir = tmp_path_factory.mktemp("recroot_stt")
    stem = "00003_fixture_20260101_140000"
    hls = layout.session_dir(record_dir, stem, "fixture")
    hls.mkdir(parents=True, exist_ok=True)
    build_capture(hls, count=2, base_offset=1.438)
    mp4 = layout.mp4_path(record_dir, stem, "fixture")
    mp4.parent.mkdir(parents=True, exist_ok=True)

    with hls_source.ffmpeg_source(mp4, prefer_hls=True) as source:
        with av.open(str(source.path), mode="r", metadata_errors="ignore") as probe:
            start = (probe.start_time or 0) / av.time_base
        _audio, _gapless, media, _drift = _decode_audio_with_media_map(str(source.path))

    assert media, "anchorが1つも作られていない"
    assert media[0] == pytest.approx(0.0, abs=1e-6), (
        "media軸が%.3fsから始まっている (containerのstart_time=%.3fsを引けていない)"
        % (media[0], start))


def _blank_audio_packets(path):
    """``path``(TS)の音声PIDのpacketをすべて潰し、音声が1frameも復号できないsegmentに
    する。潰した数を返す。

    PMTは触らないので、音声streamは「在るがsample rateも channel数も名乗らない」状態に
    なる — 先頭segmentの音声headerが読めない実録画と同じ形である。"""
    import json

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=id", "-of", "json", str(path)],
        check=True, capture_output=True, text=True)
    pid = int(json.loads(probe.stdout)["streams"][0]["id"], 16)
    data = bytearray(path.read_bytes())
    hit = 0
    for off in range(0, len(data) - 187, 188):
        if data[off] != 0x47:
            continue
        if (((data[off + 1] & 0x1F) << 8) | data[off + 2]) != pid:
            continue
        data[off + 4:off + 188] = b"\xff" * 184
        hit += 1
    path.write_bytes(bytes(data))
    return hit


def test_transcription_reads_the_sample_rate_from_the_decoded_frames(tmp_path_factory):
    """先頭segmentの音声が読めない録画でも文字起こしは復号できる。

    実配信で、HLSのplaylistを開いた直後の ``stream.rate`` が 0(channelsも0、profileも
    unknown)になる録画が出た(rid=1070)。frameを1枚復号すればそこに 48000 が入っている
    のに、開いた時点の値で割ると文字起こしが丸ごと ZeroDivisionError で落ちる。sample
    rateは**復号したframe**から採らなければならない。"""
    av = pytest.importorskip("av")

    from tictok.core import layout
    from tictok.media import hls_source
    from tictok.record.transcription import _decode_audio_with_media_map

    record_dir = tmp_path_factory.mktemp("recroot_stt_rate")
    stem = "00004_fixture_20260101_150000"
    hls = layout.session_dir(record_dir, stem, "fixture")
    hls.mkdir(parents=True, exist_ok=True)
    names = build_capture(hls, count=8)
    # 潰すのは1本では足りない。demuxerは開くときに数秒ぶん先読みするので、健全な音声が
    # その窓に入ると sample rate が埋まってしまい、再現したい状態にならない(実録画は
    # 先頭16.3秒ぶんの音声が読めなかった)。
    for name in names[:4]:
        assert _blank_audio_packets(hls / name), "%s の音声packetを潰せていない" % name
    mp4 = layout.mp4_path(record_dir, stem, "fixture")
    mp4.parent.mkdir(parents=True, exist_ok=True)

    with hls_source.ffmpeg_source(mp4, prefer_hls=True) as source:
        with av.open(str(source.path), mode="r", metadata_errors="ignore") as probe:
            declared = probe.streams.audio[0].rate
        # fixtureそのものの番人。ここが 0 でなければ欠陥を再現できておらず、以下は
        # 壊れた実装に対しても通ってしまう。
        assert not declared, (
            "開いた直後のstream.rateが%sで、再現したい状態(0)になっていない" % declared)
        audio, _gapless, media, _drift = _decode_audio_with_media_map(str(source.path))

    assert len(audio) > 0, "音声を1sampleも復号できていない"
    assert media, "anchorが1つも作られていない"


def test_finalize_leaves_the_recording_in_the_working_dir(hls_capture, tmp_path_factory):
    """確定は最終保存先へ移さない。最終保存先が設定済みでも素材は一時保存先に残る。

    移送はcross-volumeのcopyで、1.6GBの録画で6分かかった実測がある。いつ払うかは人が
    決める(動画容量画面の「最終保存先へ移動」)ので、確定の側からは起こさない。"""
    import asyncio

    from tictok.core import layout

    work = tmp_path_factory.mktemp("relo_work")
    final = tmp_path_factory.mktemp("relo_final")
    stem = "00004_fixture_20260101_150000"
    hls = layout.session_dir(work, stem, "fixture")
    hls.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(hls_capture, hls)
    r = _finalize_recorder(hls, work, stem)
    r._final_dir = final

    asyncio.run(r._finalize())

    assert r.state == rec.STATE_COMPLETED
    assert layout.has_media(hls), "素材が一時保存先から消えている"
    assert not layout.has_media(layout.session_dir(final, stem, "fixture")), \
        "確定が最終保存先へ移送している"
    assert r.hls_dir == hls
    # 素材の在処が動いていないので、byte数もそのまま測れる。
    assert r.snapshot()["bytes"] > 0


# ===== 文字起こし: 幻のtimestamp jumpの畳み込み =====
#
# 採用集合のplaylistは源のtimestampが壊れたsegmentを落とすが、その隣のsegmentが持つPTSは
# 壊れたまま残る。ffmpegは #EXT-X-DISCONTINUITY で貼り直すのにPyAVは貼り直さないため、
# 復号側の時刻だけが飛ぶ。実測(00126)は playlist 10297.4s に対し PyAV 38586.1s。


def test_phantom_jump_is_folded_back_to_the_playlist_span():
    from tictok.record.transcription import _rebase_phantom_jumps

    # 音声は連続(gapless 0..100)だが、60s地点でmedia軸だけが28288秒飛んでいる。
    gapless = [0.0, 60.0, 60.5, 100.0]
    media = [0.0, 60.0, 28348.5, 28388.0]
    out, absorbed, count = _rebase_phantom_jumps(gapless, media, playlist_total=100.0)
    assert count == 1
    assert round(absorbed) == 28288
    assert out[-1] == pytest.approx(100.0, abs=0.5)


def test_a_real_audio_gap_inside_the_playlist_span_is_left_alone():
    """音声が実在しない本物の穴(実測34.2s)は経過時間そのもの。畳むと字幕が手前へずれる。"""
    from tictok.record.transcription import _rebase_phantom_jumps

    gapless = [0.0, 50.0, 50.0, 100.0]
    media = [0.0, 50.0, 84.2, 134.2]
    out, absorbed, count = _rebase_phantom_jumps(gapless, media, playlist_total=135.0)
    assert (count, absorbed) == (0, 0.0)
    assert out == media


def test_without_a_playlist_the_map_is_never_rewritten():
    """mp4を直接読んだ時は権威になる尺が無い。根拠が無いまま書き換えてはいけない。"""
    from tictok.record.transcription import _rebase_phantom_jumps

    media = [0.0, 60.0, 28348.5]
    out, absorbed, count = _rebase_phantom_jumps([0.0, 60.0, 60.5], media, playlist_total=None)
    assert (count, absorbed, out) == (0, 0.0, media)


def test_playlist_total_sums_extinf(tmp_path):
    from tictok.record.transcription import _playlist_media_total

    playlist = tmp_path / "x.m3u8"
    playlist.write_text("#EXTM3U\n#EXTINF:2.000,\na.ts\n#EXT-X-DISCONTINUITY\n"
                        "#EXTINF:1.500,\nb.ts\n#EXT-X-ENDLIST\n", encoding="utf-8")
    assert _playlist_media_total(str(playlist)) == pytest.approx(3.5)
    assert _playlist_media_total(str(tmp_path / "x.mp4")) is None
