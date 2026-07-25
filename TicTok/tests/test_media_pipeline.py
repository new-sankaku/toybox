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

from tictok.record import recorder as rec

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


def make_segment(path, video, audio, index):
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
            "-output_ts_offset", str(index * SEGMENT_SECONDS), *_MUX, str(path))


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


def build_capture(hls, count=SEGMENTS):
    """A clean capture of ``count`` uniform segments."""
    make_video(hls / "v.ts")
    make_audio(hls / "a.ts")
    names = []
    for i in range(count):
        name = "seg%05d.ts" % i
        make_segment(hls / name, hls / "v.ts", hls / "a.ts", i)
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
    r._keep_hls = True
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

    extinf_sum = sum(extinf for _, extinf, _, _ in kept)
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
    assert {p.name for p, _, _, _ in kept} == on_disk


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

    assert [p.name for p, _, _, _ in kept] == names
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
