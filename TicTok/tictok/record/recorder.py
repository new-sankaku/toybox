import asyncio
import errno
import json
import logging
import os
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import Optional

from tictok.core import cancel
from tictok.core import config
from tictok.core import layout
from tictok.core.logctx import ctx_recording_id, ctx_session_id, ctx_unique_id
from tictok.core.logging_setup import is_debug_enabled, progress_interval_seconds
from tictok.core.progress import pump_ffmpeg_progress

logger = logging.getLogger("tictok.recorder")

# Windows subprocesses reject SIGINT via send_signal (raises ValueError); only
# SIGTERM/CTRL_* are accepted. HLS is stream-copied with the playlist flushed
# per segment, so terminating loses at most the in-progress segment.
_TERMINATE_SIGNALS = (signal.SIGTERM,) if sys.platform == "win32" else (signal.SIGINT, signal.SIGTERM)

STATE_IDLE = "idle"
STATE_RECORDING = "recording"
STATE_STOPPING = "stopping"
STATE_FINALIZING = "finalizing"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"

# Log levels for the ops severities (Storage.OPS_INFO / OPS_WARNING / OPS_ERROR),
# used when a Recorder runs without a Storage and only Layer1 is available.
_OPS_SEVERITY_LEVELS = {
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}

# Preference order (high -> low). TikTok quality keys vary per stream.
QUALITY_PREFERENCE = ["origin", "uhd", "hd", "sd", "ld"]
HEALTHY_WAIT_SECONDS = 14
MIN_SEGMENTS = 2
MAX_LAUNCH_ATTEMPTS = 4
SEGMENT_SECONDS = 2
# How long ffmpeg keeps retrying a dropped input before giving up. Absorbs brief
# host-side blips that reuse the same stream URL. A full host re-broadcast
# reissues the URL, which ffmpeg cannot follow; that case is handled upstream by
# the collector restarting the recording on websocket reconnect.
RECONNECT_DELAY_MAX = 30

# A glitched source timestamp can inflate a single HLS segment's media span
# (EXTINF) far beyond the real wall-clock time it took to capture, baking a
# phantom gap (a multi-minute frozen frame) into the concatenated mp4 and
# poisoning the comment burn-in's time map. A segment is treated as a PTS
# discontinuity when its EXTINF exceeds the wall time it spanned by BOTH this
# ratio AND this absolute floor; the ratio test is the real discriminator, so a
# genuine stream freeze (where media advances together with wall) and ordinary
# segment-length jitter are never misclassified.
PTS_DISCONTINUITY_RATIO = 3.0
PTS_DISCONTINUITY_MIN_SECONDS = 30.0
# Segment mtimes are the wall side of the timing map, so a wall clock that moves
# backwards (NTP correction, DST, a manual set) would emit anchors out of order.
# The burn-in sorts anchors by wall, which reorders the media column with them, so
# the map has to be kept strictly ascending at the source: an anchor that would not
# advance is nudged by this much instead.
ANCHOR_MIN_STEP_SECONDS = 0.001


# ----------------------------------------------------------- diagnostic helpers
# Shared by the recorder, the upscale renderer and the transcriber (all of which
# drive external processes or long GPU jobs) so that "which command failed", "how
# much disk was left" and "how often may a long job speak" are answered the same
# way everywhere.


class ProgressGate:
    """Rate limiter for the periodic progress line of a long-running job.

    Two independent gates, because either one alone is insufficient:

    * a time interval bounds how *often* a job speaks, but not how many lines it
      emits in total — a job running at 0.23 fps (107x real time) would emit
      thousands of lines against a fixed interval;
    * a completion-percent step bounds the *total* line count deterministically
      (100 / step), but says nothing while a job is stalled at the same percent.

    The interval also grows geometrically per emitted line, so the first minutes of
    a job — the ones that matter when it dies early — stay densely logged while a
    long run thins out. At DEBUG both gates open (every tick is emitted), which is
    the point of raising the level.
    """

    def __init__(self) -> None:
        self._interval = progress_interval_seconds(config.get_log_progress_interval_seconds())
        self._max_interval = config.get_log_progress_interval_max_seconds()
        self._growth = max(1.0, config.get_log_progress_interval_growth())
        self._step = 0.0 if is_debug_enabled() else config.get_log_progress_percent_step()
        self._last_at = time.monotonic()
        self._last_percent = None

    def due(self, percent: Optional[float] = None) -> bool:
        """True when a progress line may be emitted now; records the emission."""
        now = time.monotonic()
        if now - self._last_at < self._interval:
            return False
        if percent is not None and self._step > 0 and self._last_percent is not None:
            if percent - self._last_percent < self._step:
                return False
        self._last_at = now
        self._last_percent = percent
        self._interval = min(self._max_interval, self._interval * self._growth)
        return True


def _volume_key(path) -> str:
    """Identifier of the storage volume holding ``path``.

    The working dir (SSD), the final dir (HDD), the DB and the logs can each live on
    a different drive — ``_relocate_to_final`` exists precisely because of that — so a
    single "free bytes" number cannot answer which drive filled up. On Windows the
    drive letter is the volume; elsewhere the enclosing mount point is."""
    # Resolved first: a relative path has neither drive nor anchor, so keying it
    # directly would report the working directory as a volume of its own and split one
    # physical drive across two entries.
    path = Path(path).resolve()
    if sys.platform == "win32":
        return (path.drive or path.anchor or str(path)).upper()
    probe = path
    while not os.path.ismount(probe) and probe != probe.parent:
        probe = probe.parent
    return str(probe)


def _existing_ancestor(path) -> Optional[Path]:
    probe = Path(path)
    while not probe.exists():
        if probe == probe.parent:
            return None
        probe = probe.parent
    return probe


def disk_free_by_volume(paths) -> dict:
    """``{volume: {"free_bytes": int, "total_bytes": int, "path": str}}`` for the
    volumes backing ``paths`` (duplicates collapse onto one entry per volume).

    Disk exhaustion has surfaced here as symptoms with no visible relation to disk —
    avatars vanishing from a burn-in and emoji turning monochrome — because nothing
    ever measured free space. Measuring per volume rather than in aggregate is what
    makes the result actionable."""
    report: dict = {}
    for path in paths:
        if not path:
            continue
        anchor = _existing_ancestor(path)
        if anchor is None:
            # A configured directory whose whole path is absent — a final dir on a
            # drive that is not mounted, for instance. Reporting nothing for it would
            # read as "this volume is fine".
            logger.warning(
                "no existing directory on the path to %s; its free space is unknown", path,
                extra={"event": "recording.disk_check_failed",
                       "ctx": {"path": str(path), "reason": "path_absent"}},
            )
            continue
        volume = _volume_key(anchor)
        if volume in report:
            continue
        try:
            usage = shutil.disk_usage(str(anchor))
        except OSError:
            logger.warning(
                "could not read free space for %s", anchor,
                extra={"event": "recording.disk_check_failed",
                       "ctx": {"path": str(anchor), "volume": volume}},
                exc_info=True,
            )
            continue
        report[volume] = {
            "free_bytes": usage.free,
            "total_bytes": usage.total,
            "path": str(anchor),
        }
    return report


def log_disk_preflight(event: str, paths, stage: str, **extra_ctx) -> dict:
    """Measure and log free space on every volume in ``paths`` before doing work that
    writes a large intermediate. Warns when any volume is below the configured floor.
    Returns the report so the caller can attach it to a later failure log.

    Must be called *before* any cleanup: a failure path that unlinks a partial
    encode or removes an HLS directory frees gigabytes, so a sample taken after it
    shows a healthy volume and hides the cause."""
    report = disk_free_by_volume(paths)
    floor = config.get_log_disk_low_bytes()
    low = sorted(v for v, info in report.items() if info["free_bytes"] < floor)
    ctx = {"volumes": report, "low_bytes_threshold": floor, "stage": stage, **extra_ctx}
    if low:
        ctx["low_volumes"] = low
        logger.warning(
            "low free disk space on %s before %s", ", ".join(low), stage,
            extra={"event": event, "ctx": ctx},
        )
    else:
        logger.info("disk space checked before %s", stage, extra={"event": event, "ctx": ctx})
    return report


def tail_text(path, chars: Optional[int] = None) -> str:
    """Last ``chars`` characters of a text file (ffmpeg's stderr log), or "" when it
    cannot be read. The cause of an ffmpeg failure is always at the tail."""
    limit = config.get_log_ffmpeg_stderr_chars() if chars is None else chars
    try:
        path = Path(path)
        if not path.is_file():
            return ""
        size = path.stat().st_size
        with path.open("rb") as handle:
            # Read a generous byte window: a character is up to 4 bytes in UTF-8.
            handle.seek(max(0, size - limit * 4))
            raw = handle.read()
    except OSError:
        return ""
    return raw.decode("utf-8", "replace")[-limit:]


def ffmpeg_ctx(args, returncode=None, stderr_log=None, stderr_text=None) -> dict:
    """Diagnostic context for an ffmpeg/ffprobe invocation: the exact command line,
    the exit code and the tail of its stderr. Without all three, an external-process
    failure is only reproducible by guessing which arguments were used."""
    ctx: dict = {"cmd": " ".join(str(a) for a in args)}
    if returncode is not None:
        ctx["exit_code"] = returncode
    if stderr_log is not None:
        # Not "path": a caller's ctx usually already carries the path of the file being
        # produced, and the stderr log is a different file.
        ctx["stderr_path"] = str(stderr_log)
        tail = tail_text(stderr_log)
        if tail:
            ctx["stderr_tail"] = tail
    if stderr_text:
        limit = config.get_log_ffmpeg_stderr_chars()
        ctx["stderr_tail"] = stderr_text[-limit:]
    return ctx


def _oserror_ctx(exc: BaseException) -> dict:
    """Exception type / errno / OS error code, so a write failure can be told apart
    from a permission failure without re-reading the stack trace."""
    ctx = {"exc_type": type(exc).__name__, "error": str(exc)}
    number = getattr(exc, "errno", None)
    if number is not None:
        ctx["errno"] = number
        ctx["errno_name"] = errno.errorcode.get(number, "")
    winerror = getattr(exc, "winerror", None)
    if winerror is not None:
        ctx["winerror"] = winerror
    return ctx


def media_pts_from_segments(extinfs: list, durations: list,
                            mp4_duration: Optional[float]) -> Optional[list]:
    """Build the exact media->pts correspondence [[media, pts], ...] from each kept
    segment's #EXTINF (media span) and its pts contribution, pinned so the last pts
    equals the finalized ``mp4_duration``. Returns None when any duration is missing
    or the inputs are unusable. Shared by the recorder (finalize, where the HLS
    demuxer makes the contribution the #EXTINF itself) and the repair script (which
    probes the .ts container durations to rebuild the axis of an mp4 muxed by an
    older build through the concat demuxer), so the axis is built identically."""
    if not extinfs or len(extinfs) != len(durations):
        return None
    if any(d is None or d <= 0 for d in durations):
        return None
    if not mp4_duration or mp4_duration <= 0:
        return None
    cum_media = cum_pts = 0.0
    points: list = []
    for extinf, dur in zip(extinfs, durations):
        cum_media += extinf
        cum_pts += dur
        points.append((round(cum_media, 6), cum_pts))
    if cum_pts <= 0:
        return None
    # Probed segment durations sum to within a few ms of the mp4 duration; normalise
    # so the endpoints match exactly.
    k = mp4_duration / cum_pts
    return [[0.0, 0.0]] + [[m, round(p * k, 6)] for m, p in points]


def is_pts_discontinuity(extinf: float, wall_seconds: float) -> bool:
    """True if a segment's media span (EXTINF) exceeds the real wall time it took
    to capture by enough to be a source-timestamp glitch rather than jitter or a
    genuine freeze (where media advances in step with wall)."""
    return (
        extinf > max(wall_seconds, SEGMENT_SECONDS) * PTS_DISCONTINUITY_RATIO
        and extinf - wall_seconds > PTS_DISCONTINUITY_MIN_SECONDS
    )


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def _normalize_filter(target_w: int, target_h: int, mode: str) -> str:
    """ffmpeg -vf chain that maps a frame of any size onto a fixed target canvas.
    'stretch' fills the canvas (may distort a rendition whose aspect ratio differs);
    'pad' (default) preserves each rendition's aspect ratio and letterboxes the rest,
    so no frame is geometrically distorted. setsar=1 pins square pixels so mixed input
    SARs cannot re-introduce a display-size change."""
    if mode == "stretch":
        return f"scale={target_w}:{target_h},setsar=1"
    return (
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
        f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    )


async def replace_with_retry(tmp: Path, dst: Path, attempts: int = 22,
                             delay: float = 1.0, max_delay: float = 30.0) -> bool:
    """os.replace(tmp, dst) with retries. On Windows a transient lock on dst — an AV
    scan, or a media player holding the file open — raises PermissionError; retrying lets
    the lock clear instead of discarding a completed re-encode. Returns True on success;
    on persistent failure ``tmp`` is left in place for the caller to decide.

    The wait grows exponentially from ``delay`` to ``max_delay``, which with the defaults
    spans roughly nine minutes. A flat 30s window used to be the whole budget, and a
    single recording lost its normalization to it: a browser preview held the mp4 open
    across the retries, the swap failed, and the mixed-resolution stream-copy stayed in
    place while the completed re-encode was orphaned. The locks worth surviving are
    human-scale (someone scrubbing through the recording, a full-file AV scan), so the
    budget has to be too — and backoff keeps the cost of waiting that long negligible."""
    wait = delay
    for i in range(attempts):
        try:
            os.replace(tmp, dst)
            return True
        except OSError:
            if i == attempts - 1:
                return False
            if i and i % 5 == 0:
                logger.info(
                    "%s is still locked; retrying the swap (attempt %d/%d)",
                    dst.name, i + 1, attempts,
                    extra={"event": "recording.replace_retried",
                           "ctx": {"path": str(dst), "attempt": i + 1,
                                   "attempts": attempts, "wait_seconds": wait}},
                )
            await asyncio.sleep(wait)
            wait = min(wait * 2, max_delay)
    return False


async def _probe_duration_seconds(path: Path) -> Optional[float]:
    """Container duration in seconds via ffprobe, or None on failure. Module-level twin of
    Recorder._probe_duration for callers without a Recorder instance."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nokey=1:noprint_wrappers=1", str(path),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        return float(out.decode("ascii", "replace").strip())
    except (OSError, ValueError):
        return None


# 再回収時の差し替えretry回数。既定のbackoffで概ね1分。
RECLAIM_REPLACE_ATTEMPTS = 7

# 単一解像度re-encodeの出力が、入力の尺の何割を保っていれば完成と見なすか。scale/padは
# frameを増減させないので、正常な再encodeは尺がそのまま残る。下回るのは途中でdecodeが
# 止まった場合だけで、実測では 872秒 / 10675秒 (8%) まで落ちた。
REENCODE_MIN_COVERAGE = 0.98


def normalize_tmp_path(mp4_path) -> Path:
    """混在解像度re-encodeの出力先(<mp4>.norm.tmp)。"""
    mp4_path = Path(mp4_path)
    return mp4_path.with_suffix(mp4_path.suffix + NORMALIZE_TMP_SUFFIX)


def normalize_marker_path(tmp) -> Path:
    """完了印(<mp4>.norm.tmp.done)のpath。"""
    tmp = Path(tmp)
    return tmp.with_name(tmp.name + NORMALIZE_DONE_SUFFIX)


def _write_normalize_marker(tmp: Path, timing_mode: str, target_w: int, target_h: int) -> None:
    """re-encode完了印を書く。差し替えが失敗しても、後からこのfileを見れば「完成品である
    こと」と「timing mapを捨てるべきか(cfr)」が判るようにする。書けなくても再encode自体は
    成功しているので、失敗は記録するだけで握り潰す。"""
    marker = normalize_marker_path(tmp)
    try:
        marker.write_text(json.dumps({
            "timing_mode": timing_mode,
            "width": target_w,
            "height": target_h,
            "size_bytes": tmp.stat().st_size if tmp.is_file() else 0,
            "completed_at": time.time(),
        }), encoding="utf-8")
    except OSError:
        logger.warning(
            "could not write the normalization marker for %s; a failed swap would leave "
            "the re-encode unreclaimable", tmp.name,
            extra={"event": "recording.normalize_marker_write_failed",
                   "ctx": {"path": str(marker)}},
            exc_info=True,
        )


def read_normalize_marker(tmp) -> Optional[dict]:
    """完了印の中身。無い/壊れている場合はNone(=完成品と見なさない)。"""
    try:
        data = json.loads(normalize_marker_path(tmp).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


async def commit_normalized(tmp: Path, mp4_path: Path, timing_mode: str,
                            attempts: Optional[int] = None) -> bool:
    """完成した正規化mp4を本来のpathへ差し替える。CFRへ落ちていればtiming mapを捨て、
    成功したら完了印を消す。差し替えの成否を返す。録画finalizeと再回収sweepの双方が
    通る唯一の出口にして、片方だけ後始末を忘れる形にならないようにする。"""
    kwargs = {} if attempts is None else {"attempts": attempts}
    if not await replace_with_retry(tmp, mp4_path, **kwargs):
        return False
    if timing_mode == "cfr":
        # CFR fallbackはframe timelineを作り直すので、直前に書いたmedia->pts mapはもう
        # 一致しない。捨てて、焼き込みにはwall-clock近似へ落ちてもらう。
        timing_path(mp4_path).unlink(missing_ok=True)
    normalize_marker_path(tmp).unlink(missing_ok=True)
    return True


async def reencode_single_resolution(
    src: Path, dst: Path, target_w: int, target_h: int,
    mode: str, codec: str, base_quality: int, on_progress=None,
    audio_copy: bool = False,
):
    """Re-encode ``src`` to ``dst`` at a single fixed resolution. Returns the timing mode
    used — ``"passthrough"`` (every input timestamp preserved, so a companion media->pts
    timing map stays valid) or ``"cfr"`` — or ``None`` on failure.

    Passthrough is tried first. A few recordings carry a pathological timestamp near the
    start (the stream-copied HLS join can leave a single frame with a ~2^32 duration that
    the mp4 muxer rejects with "Invalid argument"); passthrough cannot mux those, so the
    encode is retried at a constant frame rate, which regenerates a clean timeline. CFR
    breaks the media->pts map, so a caller that keeps a timing sidecar must drop it when
    this returns ``"cfr"``. When ``on_progress`` is given it is awaited with an integer
    percent as encoding proceeds. Shared by the recorder's finalize and the maintenance
    script.

    ``audio_copy`` stream-copies the audio instead of re-encoding it. finalize経路の入力は
    直前のconcatが自分で書いたAAC(aresample済み・単一parameter)なので、ここで焼き直しても
    世代劣化とencode時間を足すだけになる。入力の素性を保証できない維持scriptは既定のまま
    re-encodeする(古い録画には解像度切替をまたぐ生AACが残っていて、copyではmuxできない)。"""
    # Lazy import: video_overlay imports from this module, so a top-level import would
    # be circular. These helpers are pure/probe-only (no settings coupling).
    from tictok.record.video_overlay import (
        _encoder_args,
        _mapped_quality,
        video_encoder_name,
    )

    codec = codec if codec in ("auto", "h264", "hevc", "av1") else "auto"
    encoder = await video_encoder_name(codec)
    quality = _mapped_quality(encoder, base_quality)
    vf = _normalize_filter(target_w, target_h, mode)
    total_us = None
    if on_progress is not None:
        secs = await _probe_duration_seconds(src)
        total_us = int(secs * 1_000_000) if secs and secs > 0 else None

    # ffmpeg's stderr goes to a file rather than a pipe: stdout is already being drained
    # for progress, and a second pipe could fill and deadlock the encoder on a source
    # that spews warnings. The tail is what the failure logs quote.
    log_path = Path(str(dst) + FFMPEG_LOG_SUFFIX)

    async def _run(timing_args: list) -> bool:
        args = [
            "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
            "-i", str(src),
            # -bf 0: a mixed-resolution source carries jittery/duplicate DTS from the
            # stream-copied HLS join; with B-frames the encoder emits reordered packets
            # whose DTS the mp4 muxer cannot place after the demuxer bumps duplicates,
            # aborting with "Not yet implemented (patches welcome)". Disabling B-frames
            # keeps DTS==PTS so every packet is muxable; the slight size cost is fine
            # for a compatibility pass and it improves seekability.
            "-vf", vf, *timing_args, "-bf", "0",
            *_encoder_args(encoder, quality), "-pix_fmt", "yuv420p",
            # Re-encode audio (not copy): the source audio's parameters change at each
            # resolution switch and some segments carry corrupt AAC, which the mp4
            # muxer rejects on a stream copy. aresample regenerates continuous
            # timestamps so the audio track stays muxable and in sync.
            *(["-c:a", "copy"] if audio_copy
              else ["-c:a", "aac", "-b:a", "192k", "-af", "aresample=async=1"]),
            "-movflags", "+faststart",
            # Machine-readable progress on stdout so the caller can surface a percent.
            "-progress", "pipe:1", "-nostats",
            # Force the muxer: dst is a temp name (e.g. ".mp4.norm.tmp") that ffmpeg
            # cannot map to a format by extension, so it must be specified explicitly.
            "-f", "mp4", str(dst),
        ]
        logger.debug(
            "starting resolution normalization re-encode of %s", src.name,
            extra={"event": "process.ffmpeg_started",
                   "ctx": {"stage": "normalize", "stem": src.stem, **ffmpeg_ctx(args)}},
        )
        try:
            with open(log_path, "ab") as log_file:
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=log_file,
                )
                # 再mp4化の取り消しがこのre-encodeにも届くようにする(録画時のfinalizeは
                # job context外なのでno-op)。
                cancel.register_process(proc)
                try:
                    await _consume_ffmpeg_progress(proc, total_us, on_progress)
                    await proc.wait()
                finally:
                    cancel.forget_process(proc)
        except Exception:
            logger.error(
                "resolution normalization re-encode failed to launch for %s", src.name,
                extra={"event": "process.ffmpeg_launch_failed",
                       "ctx": {"stage": "normalize", "stem": src.stem, **ffmpeg_ctx(args)}},
                exc_info=True,
            )
            return False
        if proc.returncode == 0 and dst.exists() and dst.stat().st_size > 0:
            return True
        logger.warning(
            "resolution normalization re-encode of %s exited %s", src.name, proc.returncode,
            extra={"event": "process.ffmpeg_failed",
                   "ctx": {"stage": "normalize", "stem": src.stem,
                           **ffmpeg_ctx(args, proc.returncode, log_path)}},
        )
        return False

    async def _covers_source(timing_mode: str) -> bool:
        """出来た出力が入力の尺を保っているか。exit 0 は「最後まで読めた」を意味しない。

        実測(2026-07-23, pomiiiip_20260618_222816): 途中でsegment分割が止まった録画は、
        stream copyでは177.9分そのまま通るのに、この再encodeでは順に読んだdecoderが
        14.5分の地点で止まり、**ffmpegは0で正常終了して**91%を捨てた出力を残した。その
        出力が元mp4と差し替えられ、178分の録画が14.5分になった(seekすれば復号できるので、
        素材が壊れているわけではない)。尺で突き合わせない限り、この落ち方は検出できない。"""
        if not src_seconds:
            logger.warning(
                "could not measure %s; the re-encode's completeness is unverified", src.name,
                extra={"event": "recording.reencode_unverified",
                       "ctx": {"stem": src.stem, "timing_mode": timing_mode,
                               "path": str(dst)}},
            )
            return True
        out_seconds = await _probe_duration_seconds(dst)
        if out_seconds and out_seconds >= src_seconds * REENCODE_MIN_COVERAGE:
            return True
        logger.error(
            "re-encode of %s stopped early: %.0fs of %.0fs (%s timing)",
            src.name, out_seconds or 0.0, src_seconds, timing_mode,
            extra={"event": "recording.reencode_incomplete",
                   "ctx": {"stem": src.stem, "timing_mode": timing_mode,
                           "produced_seconds": round(out_seconds or 0.0, 1),
                           "source_seconds": round(src_seconds, 1),
                           "path": str(dst)}},
        )
        return False

    started = time.monotonic()
    src_seconds = await _probe_duration_seconds(src)
    if await _run(["-fps_mode", "passthrough"]) and await _covers_source("passthrough"):
        log_path.unlink(missing_ok=True)
        _write_normalize_marker(dst, "passthrough", target_w, target_h)
        logger.info(
            "re-encoded %s to a single resolution (passthrough timing)", src.name,
            extra={"event": "recording.reencode_completed",
                   "ctx": {"stem": src.stem, "timing_mode": "passthrough",
                           "width": target_w, "height": target_h, "encoder": encoder,
                           "duration_ms": int((time.monotonic() - started) * 1000)}},
        )
        return "passthrough"
    dst.unlink(missing_ok=True)
    # 直前の実行が残した完了印を道連れにする。tmpを消した後に印だけ残ると、再回収sweepが
    # 「完成品が在る」と読み違える。
    normalize_marker_path(dst).unlink(missing_ok=True)
    # 理由は2つある: muxできなかった(病的なtimestamp)か、途中でdecodeが止まって尺が
    # 足りなかったか。どちらだったかは直前のlog(process.ffmpeg_failed /
    # recording.reencode_incomplete)が数字付きで残している。
    logger.warning(
        "passthrough re-encode did not produce a complete output for %s; retrying as CFR",
        src.name,
        extra={"event": "recording.reencode_retried",
               "ctx": {"stem": src.stem, "timing_mode": "cfr", "path": str(log_path)}},
    )
    if await _run(["-fps_mode", "cfr", "-r", "30"]) and await _covers_source("cfr"):
        log_path.unlink(missing_ok=True)
        _write_normalize_marker(dst, "cfr", target_w, target_h)
        logger.info(
            "re-encoded %s to a single resolution (CFR timing)", src.name,
            extra={"event": "recording.reencode_completed",
                   "ctx": {"stem": src.stem, "timing_mode": "cfr",
                           "width": target_w, "height": target_h, "encoder": encoder,
                           "duration_ms": int((time.monotonic() - started) * 1000)}},
        )
        return "cfr"
    # 出力を残さない。中身の足りないtmpを置いたままにすると、起動時のsweepが完了印を見て
    # 「完成品が在る」と読み、切れた方を差し替えてしまう。
    dst.unlink(missing_ok=True)
    normalize_marker_path(dst).unlink(missing_ok=True)
    logger.error(
        "both passthrough and CFR re-encodes failed for %s", src.name,
        extra={"event": "recording.reencode_failed",
               "ctx": {"stem": src.stem, "encoder": encoder,
                       "width": target_w, "height": target_h,
                       "duration_ms": int((time.monotonic() - started) * 1000),
                       "path": str(log_path)}},
    )
    return None


async def _consume_ffmpeg_progress(proc, total_us, on_progress) -> None:
    """Drain ffmpeg's ``-progress pipe:1`` stream, awaiting ``on_progress(pct)`` as the
    encode advances. Draining stdout also prevents the pipe from filling and stalling the
    encoder, so it runs even when no callback is registered."""
    last_pct = -1
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        if on_progress is None or not total_us:
            continue
        text = line.decode("ascii", "replace").strip()
        if text.startswith("out_time_us="):
            try:
                done_us = int(text.split("=", 1)[1])
            except ValueError:
                continue
            pct = max(0, min(99, int(done_us / total_us * 100)))
            if pct != last_pct:
                last_pct = pct
                try:
                    await on_progress(pct)
                except Exception:
                    logger.debug(
                        "re-encode progress callback failed at %d%%", pct,
                        extra={"event": "recording.progress_callback_failed",
                               "ctx": {"percent": pct}},
                        exc_info=True,
                    )


async def probe_mp4_resolutions(mp4_path: Path, input_args: tuple = ()) -> set:
    """Distinct (width, height) present across the mp4's video keyframes.

    A mid-stream resolution change needs a new SPS and therefore a keyframe (IDR), so
    scanning only keyframes (``-skip_frame nokey``) catches every distinct resolution
    while decoding a few hundred frames instead of the whole file. This reads the final
    concatenated mp4 rather than the individual HLS segments: many .ts segments start
    mid-GOP with no in-band SPS, so a per-segment stream probe returns no dimensions for
    them and can miss a resolution entirely — the very reason some mixed recordings
    slipped past normalization. Returns an empty set on probe failure. Shared by the
    recorder's finalize and the maintenance script.

    The scan is retried a few times because a keyframe decode can abort early on a
    transiently busy disk (right after a large concat) or a corrupt frame, exiting
    non-zero with only a partial resolution list — which would look like a single
    resolution and silently skip normalization. The last, most complete result wins.

    ``input_args`` はHLS再生listを直接読ませるためのdemuxer option(HLS_INPUT_ARGS)。連結後の
    mp4と同じdecoder経路を通るので結果は一致する(segment単位のstream probeとは別物)。concat
    と同時に走らせて、mp4を頭から読み直す一巡ぶんを消すために使う。"""
    args = [
        "ffprobe", "-v", "error", *input_args, "-select_streams", "v:0",
        "-skip_frame", "nokey", "-show_entries", "frame=width,height",
        "-of", "csv=p=0", str(mp4_path),
    ]
    best: set = set()
    for attempt in range(3):
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            out, err = await proc.communicate()
        except OSError as exc:
            logger.error(
                "keyframe resolution probe could not run for %s", mp4_path.name,
                extra={"event": "process.ffprobe_launch_failed",
                       "ctx": {"stage": "resolutions", "stem": mp4_path.stem,
                               **ffmpeg_ctx(args), **_oserror_ctx(exc)}},
                exc_info=True,
            )
            return best
        seen = set()
        for line in out.decode("ascii", "replace").splitlines():
            parts = line.strip().split(",")
            if len(parts) >= 2:
                try:
                    seen.add((int(parts[0]), int(parts[1])))
                except ValueError:
                    continue
        if len(seen) > len(best):
            best = seen
        # A clean full scan (exit 0) is authoritative; only retry when ffprobe aborted,
        # since that can truncate the list and hide a resolution.
        if proc.returncode == 0:
            return seen
        logger.warning(
            "keyframe resolution probe of %s aborted (attempt %d); retrying",
            mp4_path.name, attempt + 1,
            extra={"event": "process.ffprobe_retried",
                   "ctx": {"stage": "resolutions", "stem": mp4_path.stem,
                           "attempt": attempt + 1, "partial_resolutions": len(seen),
                           **ffmpeg_ctx(args, proc.returncode,
                                        stderr_text=err.decode("utf-8", "replace"))}},
        )
        await asyncio.sleep(1)
    logger.error(
        "keyframe resolution probe of %s never completed cleanly; mixed-resolution "
        "detection may be incomplete", mp4_path.name,
        extra={"event": "process.ffprobe_failed",
               "ctx": {"stage": "resolutions", "stem": mp4_path.stem,
                       "partial_resolutions": len(best), **ffmpeg_ctx(args)}},
    )
    return best


async def reclaim_normalized_mp4(mp4_path) -> str:
    """完了印の付いた .norm.tmp を、本来のmp4へ差し替え直す。

    正規化は「re-encode成功 → 差し替え」の2段で、後段だけがOS都合(再生中・AV scan)で失敗し
    うる。失敗すると混在解像度の元mp4が残り、直ったfileは誰にも拾われないまま保持policyの
    削除対象になる — 壊れた方が生き残り直った方が消える。この関数がその唯一の救済路で、
    起動時sweepと焼き込み直前の両方から呼ばれる。

    返り値は "reclaimed"(差し替えた) / "locked"(まだ掴まれている) / "invalid"(完成品ではない)
    / "none"(対象なし)。破棄は「印はあるがtmpが無い」時だけに限り、疑わしい物は残す。"""
    mp4_path = Path(mp4_path)
    tmp = normalize_tmp_path(mp4_path)
    marker = read_normalize_marker(tmp)
    if marker is None:
        return "none"
    if not tmp.is_file():
        # 印だけが残った(tmpは既に手動で当てられたか消された)。印は無意味なので片付ける。
        normalize_marker_path(tmp).unlink(missing_ok=True)
        return "none"
    # 印はffmpegのexit 0後にしか書かれないが、印を書いた後にprocessが落ちてfileが途中まで
    # しか残っていない可能性は残る。当てる前に必ず実fileを見る(派生metricではなく成果物で
    # 確かめる)。単一解像度であることまで確認して、混在mp4を混在mp4で置き換えない。
    distinct = await probe_mp4_resolutions(tmp)
    if len(distinct) != 1:
        logger.error(
            "normalized leftover %s is not a single-resolution mp4 (%d found); leaving both "
            "files in place", tmp.name, len(distinct),
            extra={"event": "recording.normalize_reclaim_rejected",
                   "ctx": {"path": str(tmp), "stem": mp4_path.stem,
                           "distinct_resolutions": sorted(f"{w}x{h}" for w, h in distinct)}},
        )
        return "invalid"
    timing_mode = marker.get("timing_mode") or "passthrough"
    # 再回収は「retryのretry」。ここで粘っても起動sweepと次の出力jobが何度でも来るので、
    # finalize本体(数分)より短く切って、startupや焼き込みの前段を長く塞がない。
    if not await commit_normalized(tmp, mp4_path, timing_mode, attempts=RECLAIM_REPLACE_ATTEMPTS):
        logger.warning(
            "normalized output for %s is still waiting: %s is locked. Close it in any "
            "player and it will be swapped in at the next attempt", mp4_path.name, mp4_path.name,
            extra={"event": "recording.normalize_reclaim_deferred",
                   "ctx": {"path": str(tmp), "stem": mp4_path.stem,
                           "size_bytes": tmp.stat().st_size if tmp.is_file() else 0}},
        )
        return "locked"
    logger.info(
        "reclaimed the normalized mp4 for %s (%dx%d, %s timing)", mp4_path.stem,
        marker.get("width") or 0, marker.get("height") or 0, timing_mode,
        extra={"event": "recording.normalize_reclaimed",
               "ctx": {"path": str(mp4_path), "stem": mp4_path.stem,
                       "timing_mode": timing_mode,
                       "width": marker.get("width"), "height": marker.get("height"),
                       "size_bytes": mp4_path.stat().st_size if mp4_path.is_file() else 0}},
    )
    return "reclaimed"


async def reclaim_pending_normalizations(storage, roots) -> int:
    """起動時sweep: 差し替え待ちの正規化mp4をすべて拾い直す。差し替えた件数を返す。

    前回processの終了時に掴まれていたfileも、再起動後は大抵解放されている。ここを通さないと
    救済は次の録画まで一度も走らない。"""
    reclaimed = 0
    seen: set = set()
    for row in storage.recordings_for_retention():
        stem = Path(row.get("filename") or "").stem
        if not stem:
            continue
        for root in roots:
            mp4_path = layout.mp4_path(Path(root), stem)
            if mp4_path in seen:
                continue
            seen.add(mp4_path)
            try:
                if await reclaim_normalized_mp4(mp4_path) == "reclaimed":
                    reclaimed += 1
                    # 中身が別fileに変わったのでbytesを取り直す。放置すると容量画面と
                    # 保持policyが元mp4のサイズで計算し続ける(再encodeで数倍変わる)。
                    storage.update_recording_bytes(row["id"], mp4_path.stat().st_size)
            except Exception:
                logger.exception(
                    "could not reclaim the normalized mp4 for %s", stem,
                    extra={"event": "recording.normalize_reclaim_failed",
                           "ctx": {"stem": stem, "path": str(mp4_path)}},
                )
    if reclaimed:
        logger.info(
            "startup sweep swapped in %d normalized recording(s) that a locked file had "
            "left orphaned", reclaimed,
            extra={"event": "recording.normalize_reclaim_swept",
                   "ctx": {"reclaimed": reclaimed}},
        )
    return reclaimed


# Per-recording burn-in/timing artifacts live in this sibling directory of the
# recordings root, so the root itself holds only the .mp4 recordings. The names
# inside mirror the .mp4 stem (e.g. <stem>.timing.json) so each sidecar maps back
# to its recording.
SIDECAR_DIRNAME = ".sidecars"
TIMING_SUFFIX = ".timing.json"
# finalizeで書き出すVOD playlist。captureのindex.m3u8は強制終了で#EXT-X-ENDLISTが
# 付かずliveと誤認されるため、mux用に終端済みのlistを別名で用意する(hls_dir内)。
VOD_PLAYLIST_NAME = "concat_vod.m3u8"

# HLS再生listを入力にするffmpeg/ffprobeのdemuxer option。concatとkeyframe probeの双方が
# 同じ入力の開き方をするよう、1箇所に置く。
HLS_INPUT_ARGS = ("-allowed_extensions", "ALL",
                  "-protocol_whitelist", "file,crypto,data")
# ffmpegのstderrを落とす先。出力fileのpathへそのまま連結して使う。
FFMPEG_LOG_SUFFIX = ".ffmpeg.log"
# 混在解像度のre-encode先。成功すれば元mp4へrenameし、失敗すれば消す一時fileだが、
# processが落ちるとmp4の隣に残り続ける(元mp4とほぼ同容量)。保持policyの掃除対象。
NORMALIZE_TMP_SUFFIX = ".norm.tmp"
# 完了印。re-encodeがexit 0で終わった直後に書き、差し替え成功で消す。これが在る
# .norm.tmp は「捨て残し」ではなく「正しく直ったが置き換えられなかった成果物」であり、
# 元mp4より価値が高い。中断した中間fileと完成品を区別する唯一の手段なので、保持policyの
# 掃除対象から外し、再回収(reclaim)の入口として使う。
NORMALIZE_DONE_SUFFIX = ".done"
# The burned-in overlay mp4 is the user-facing output and belongs in the recordings
# root alongside its source (see video_overlay.overlay_paths); migrate_sidecars
# relocates any that an earlier .sidecars-era build left under SIDECAR_DIRNAME.
OVERLAY_SUFFIX = ".overlay.mp4"
# Suffixes of everything that used to sit next to the .mp4 and now belongs under
# SIDECAR_DIRNAME (persistent maps/caches plus transient render leftovers). Used
# by migrate_sidecars to relocate artifacts written by older recordings. The
# overlay mp4 is intentionally excluded — it stays in the root.
SIDECAR_SUFFIXES = (
    ".timing.json", ".overlay.ass", ".overlay.meta",
    ".comments.mov", ".ffmpeg.log",
)


def sidecar_dir(src) -> Path:
    """Directory holding a recording's sidecar artifacts, kept at the record root's
    .sidecars (not next to the nested mp4), so all sidecars stay in one place."""
    return layout.record_root_of(src) / SIDECAR_DIRNAME


def sidecar_path(src, suffix: str) -> Path:
    """Sidecar path for ``src`` with ``suffix`` (e.g. ``.overlay.mp4``)."""
    src = Path(src)
    return sidecar_dir(src) / (src.stem + suffix)


def timing_path(src) -> Path:
    """Sibling wall->media timing map written by the recorder at finalize."""
    return sidecar_path(src, TIMING_SUFFIX)


def relocatable_artifact_paths(src) -> list:
    """``src``の位置から解決される持続fileすべて(mp4本体は含まない)。移送で一緒に運ぶ集合。

    列挙元は削除・容量表示と同じ関数で、定義を二重に持たない。renderが作って自分で消す
    中間物(CFR base・comment layer)は入れない — 移送は完了録画にしか起きず、そこに在る
    中間物は定義上どのrenderも参照しない孤児で、起動時のsweepが回収する。

    importが関数内なのは、video_overlay/upscale/thumbnails/waveformがこのmoduleを
    import しており、module levelで取ると循環するため。"""
    from tictok.media.thumbnails import thumbnail_artifact_paths
    from tictok.media.waveform import waveform_artifact_paths
    from tictok.record.upscale import upscale_artifact_paths
    from tictok.record.video_overlay import overlay_artifact_paths

    src = Path(src)
    return [
        *overlay_artifact_paths(src),
        *upscale_artifact_paths(src),
        timing_path(src),
        *thumbnail_artifact_paths(src),
        *waveform_artifact_paths(src),
    ]


# Recording filenames are prefixed with the zero-padded session number so they
# sort and group by session in the recordings folder (e.g. 00042_user_<stamp>.mp4).
SESSION_PREFIX_WIDTH = 5


def session_prefix(session_id) -> str:
    """Zero-padded session-number prefix for a recording filename."""
    return f"{int(session_id):0{SESSION_PREFIX_WIDTH}d}"


def migrate_sidecars(record_dir) -> int:
    """Reconcile a recording folder's layout with the current convention: transient
    render artifacts live under ``.sidecars`` while .mp4 recordings (the source and
    the burned-in overlay) sit in the root. Moves root-level render artifacts that
    older recordings wrote next to the .mp4 into ``.sidecars``, and moves overlay
    mp4 files that an earlier .sidecars-era build left under ``.sidecars`` back into
    the root. Idempotent; returns the number of files moved."""
    root = Path(record_dir)
    if not root.is_dir():
        return 0
    dest_dir = root / SIDECAR_DIRNAME
    moved = 0

    def _relocate(entry: Path, dest: Path) -> None:
        nonlocal moved
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(entry, dest)
            moved += 1
        except OSError as exc:
            logger.warning(
                "failed to migrate recording artifact %s to the current layout", entry.name,
                extra={"event": "recording.sidecar_migration_failed",
                       "ctx": {"path": str(entry), "stem": entry.stem, **_oserror_ctx(exc)}},
                exc_info=True,
            )

    for entry in root.iterdir():
        if not entry.is_file():
            continue
        if any(entry.name.endswith(s) for s in SIDECAR_SUFFIXES):
            _relocate(entry, dest_dir / entry.name)

    if dest_dir.is_dir():
        for entry in dest_dir.iterdir():
            if entry.is_file() and entry.name.endswith(OVERLAY_SUFFIX):
                _relocate(entry, root / entry.name)

    if moved:
        logger.info(
            "migrated %d recording artifact(s) to the current layout", moved,
            extra={"event": "recording.sidecars_migrated",
                   "ctx": {"moved": moved, "path": str(root)}},
        )
    return moved


def _rung_summary(data: dict) -> str:
    """Human-readable one-line inventory of the stream's quality rungs for logging:
    ``origin(1080x1920 4000k flv/hls) hd(720x1280 900k flv) ...``. The recorder only
    ever gets the top *offered* rung, so this makes it visible whether a higher rung
    (origin/uhd) exists at the source at all, or the ceiling is source-side."""
    parts = []
    for name, entry in data.items():
        main = (entry or {}).get("main") or {}
        params: dict = {}
        raw = main.get("sdk_params")
        if isinstance(raw, str) and raw:
            try:
                params = json.loads(raw)
            except ValueError:
                params = {}
        elif isinstance(raw, dict):
            params = raw
        res = params.get("resolution") or entry.get("resolution") or "?"
        vb = params.get("vbitrate")
        vb_k = f"{int(vb) // 1000}k" if isinstance(vb, (int, float)) and vb else "?"
        proto = "/".join(p for p in ("flv", "hls") if main.get(p)) or "none"
        parts.append(f"{name}({res} {vb_k} {proto})")
    return " ".join(parts) if parts else "(none)"


def extract_stream_url(room_info: dict, quality_pref: str = "") -> tuple[Optional[str], Optional[str]]:
    """Return (flv_url, quality_label) for the best available quality, or (None, None)."""
    stream_url = (room_info or {}).get("stream_url") or {}
    try:
        sdk_data = stream_url["live_core_sdk_data"]["pull_data"]["stream_data"]
        data = json.loads(sdk_data)["data"]
    except (KeyError, TypeError, ValueError):
        data = {}

    if data:
        available = [q for q in data.keys() if q != "ao"] or list(data.keys())
        order = []
        if quality_pref and quality_pref in available:
            order.append(quality_pref)
        order.extend(q for q in QUALITY_PREFERENCE if q in available and q not in order)
        order.extend(q for q in available if q not in order)
        chosen = next((q for q in order if (data.get(q, {}).get("main") or {}).get("flv")
                       or (data.get(q, {}).get("main") or {}).get("hls")), None)
        logger.info(
            "stream quality rungs: %s | chosen=%s", _rung_summary(data), chosen,
            extra={"event": "recording.quality_selected",
                   "ctx": {"chosen": chosen, "offered": sorted(data.keys()),
                           "requested": quality_pref or None,
                           "rungs": _rung_summary(data)}},
        )
        for quality in order:
            try:
                main = data[quality]["main"]
                url = main.get("flv") or main.get("hls")
                if url:
                    return url, quality
            except (KeyError, TypeError):
                continue

    flv_map = stream_url.get("flv_pull_url") or {}
    if isinstance(flv_map, dict) and flv_map:
        for label in ("FULL_HD1", "HD1", "SD2", "SD1"):
            if flv_map.get(label):
                return flv_map[label], label.lower()
        first_label, first_url = next(iter(flv_map.items()))
        return first_url, str(first_label).lower()

    return None, None


class Recorder:
    """Records a TikTok LIVE stream to disk via ffmpeg as HLS (live-previewable),
    then concatenates the segments into a single mp4 on stop. Stream copy only."""

    def __init__(self, unique_id: str, record_dir: str, session_id: int, keep_hls: bool = False,
                 final_dir: Optional[str] = None, storage=None,
                 normalize_audio: Optional[dict] = None) -> None:
        # ``storage`` is optional so the recorder stays usable from maintenance scripts
        # that have no DB open. When given, recording lifecycle transitions are written
        # to ops_events (Layer2) in addition to the log (Layer1); when absent only the
        # log carries them. It is never used for anything else.
        self._storage = storage
        # audio_norm.targets() を渡すと、segmentの結合と同時に音量を正規化する。live録画の
        # finalizeでは渡さない(録画したままの音量を原本として残す)。渡すのは再mp4化だけで、
        # あちらは元mp4を_backup/へ退避してから作り直すため原本が失われない。結合passは
        # もともと音声をAACへ再encodeしているので、正規化を足しても追加passは発生しない。
        self._normalize_audio = normalize_audio
        self.unique_id = unique_id
        self._record_dir = Path(record_dir)
        # Working dir (record_dir, SSD) holds HLS + the mp4 during capture/finalize; a
        # completed mp4 is relocated to final_dir (HDD) at the end of _finalize. When
        # final_dir is unset or equals the working dir there is no split (no relocation).
        self._final_dir = Path(final_dir) if final_dir else self._record_dir
        # Session number that owns this recording; prefixed (zero-padded) onto the
        # output filename so recordings group by session on disk.
        self.session_id = session_id
        # When set, the HLS intermediate (segments/playlist/concat list) is kept
        # after the mp4 is built, for diagnosing the mp4-PTS vs segment timeline.
        self._keep_hls = keep_hls
        self.state = STATE_IDLE
        self.quality: Optional[str] = None
        self.error: Optional[str] = None
        self.started_at: Optional[float] = None
        self.ended_at: Optional[float] = None
        # 出来たmp4の実尺(秒)。ffprobeで測れたときだけ入る。壁時計(ended_at - started_at)
        # とは別物で、捕捉の停滞ぶんだけ壁時計の方が長くなる。
        self.duration_seconds: Optional[float] = None
        self.base: Optional[str] = None
        self.hls_dir: Optional[Path] = None
        self.playlist: Optional[Path] = None
        self.output_path: Optional[Path] = None
        self.recording_id: Optional[int] = None
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._task: Optional[asyncio.Task] = None
        self._stop_requested = False
        self._on_finalize = None
        self._on_notify = None
        # Free space per volume as measured at launch, carried so a later failure can
        # be compared against the state before any cleanup ran.
        self._disk_report: dict = {}
        self._launch_attempts = 0
        self._capture_args: list = []
        # concatと並行して走らせたkeyframe走査の結果(set|None)。Noneは「取れなかった」。
        self._concat_resolutions = None

    @property
    def is_active(self) -> bool:
        return self.state in (STATE_RECORDING, STATE_STOPPING)

    def _ops(self, kind: str, message: str, *, severity: str = "info",
             duration_ms=None, detail: Optional[dict] = None, exc_info=False) -> None:
        """Record one recording-lifecycle transition.

        With a Storage attached the transition lands in both the log (Layer1) and the
        ops_events table (Layer2) under the same name; without one — maintenance
        scripts construct a Recorder with no DB — only the log carries it. The
        severity strings match Storage's OPS_* constants; they are written literally
        rather than imported so that recorder.py does not depend on storage.py."""
        if self._storage is not None:
            self._storage.record_ops_event(
                logger, kind, message,
                severity=severity,
                unique_id=self.unique_id,
                session_id=self.session_id,
                recording_id=self.recording_id,
                duration_ms=duration_ms,
                detail=detail,
                exc_info=exc_info,
            )
            return
        ctx = dict(detail or {})
        if duration_ms is not None:
            ctx["duration_ms"] = duration_ms
        logger.log(
            _OPS_SEVERITY_LEVELS[severity], message,
            extra={"event": kind, "ctx": ctx}, exc_info=exc_info,
        )

    def _live_bytes(self) -> int:
        if self.hls_dir is None or not self.hls_dir.exists():
            return 0
        return sum(f.stat().st_size for f in self.hls_dir.glob("seg*.ts"))

    def progress_token(self) -> tuple[int, int]:
        """Cheap monotonic capture-progress signal for stall detection: (segment
        count, newest segment size). It advances whenever ffmpeg writes video —
        either a new seg*.ts appears or the open segment grows — and freezes
        entirely when the source silently stalls (the CDN stops serving new
        segments) even though ffmpeg stays alive retrying the now-dead URL. Only
        the newest segment is stat()ed, so polling stays O(1) over a long
        recording. Segment names are zero-padded, so the lexical max is the
        highest index (newest)."""
        if self.hls_dir is None or not self.hls_dir.exists():
            return (0, 0)
        segs = list(self.hls_dir.glob("seg*.ts"))
        if not segs:
            return (0, 0)
        try:
            newest = max(segs, key=lambda p: p.name)
            return (len(segs), newest.stat().st_size)
        except OSError:
            return (len(segs), 0)

    def snapshot(self) -> dict:
        if self.output_path is not None and self.output_path.exists():
            size = self.output_path.stat().st_size
        else:
            size = self._live_bytes()
        return {
            "state": self.state,
            "quality": self.quality,
            "error": self.error,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "bytes": size,
            "filename": self.output_path.name if self.output_path else None,
            "recording_id": self.recording_id,
            "live": self.state == STATE_RECORDING and self.playlist is not None and self.playlist.exists(),
        }

    def live_file(self, filename: str) -> Optional[Path]:
        """Return a path inside the active HLS dir for serving to the browser player."""
        if self.hls_dir is None:
            return None
        # Only allow plain HLS playlist/segment filenames (no traversal, no logs).
        if "/" in filename or "\\" in filename or ".." in filename:
            return None
        if not (filename.endswith(".m3u8") or filename.endswith(".ts")):
            return None
        candidate = (self.hls_dir / filename).resolve()
        if self.hls_dir.resolve() not in candidate.parents:
            return None
        return candidate if candidate.is_file() else None

    def _volume_paths(self) -> list:
        """Every volume this recording depends on. The working dir (HLS + the mp4
        during capture), the final dir (relocation target), the DB and the logs are
        routinely on different drives, and only a per-volume reading identifies which
        one filled up."""
        return [self._record_dir, self._final_dir, config.get_db_path(), config.get_log_dir()]

    async def start(self, room_info: dict, on_finalize=None, on_notify=None) -> None:
        if self.is_active:
            raise RuntimeError("既に録画中です。")
        if not ffmpeg_available():
            logger.error(
                "cannot start recording for %s: ffmpeg is not installed", self.unique_id,
                extra={"event": "recording.start_failed",
                       "ctx": {"reason": "ffmpeg_missing"}},
            )
            raise RuntimeError("ffmpegが見つかりません。録画にはffmpegのinstallが必要です。")
        # Preflight the disk before anything is written. Measuring only after a failure
        # is useless here: the failure paths remove the HLS tree or a partial encode and
        # free the very space whose exhaustion caused the failure.
        self._disk_report = log_disk_preflight(
            "recording.disk_checked", self._volume_paths(), stage="launch",
        )
        url, quality = extract_stream_url(room_info)
        if not url:
            logger.error(
                "cannot start recording for %s: no stream URL in room info", self.unique_id,
                extra={"event": "recording.start_failed",
                       "ctx": {"reason": "no_stream_url"}},
            )
            raise RuntimeError("配信のstream URLを取得できませんでした（録画不可）。")
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        self.base = f"{session_prefix(self.session_id)}_{self.unique_id}_{stamp}"
        self.hls_dir = layout.session_dir(self._record_dir, self.base, self.unique_id)
        self.hls_dir.mkdir(parents=True, exist_ok=True)
        self.playlist = self.hls_dir / "index.m3u8"
        self.output_path = layout.mp4_path(self._record_dir, self.base, self.unique_id)
        self.quality = quality
        self.error = None
        self.started_at = time.time()
        self.ended_at = None
        self.duration_seconds = None
        self._stop_requested = False
        self._on_finalize = on_finalize
        self._on_notify = on_notify
        self.state = STATE_RECORDING
        # output_path doesn't exist until finalize; reset so snapshot reports live bytes.
        self.output_path = None
        self._mp4_path = layout.mp4_path(self._record_dir, self.base, self.unique_id)
        self._mp4_path.parent.mkdir(parents=True, exist_ok=True)
        self._task = asyncio.create_task(self._run(url), name=f"tictok-rec-{self.unique_id}")
        self._ops(
            "recording.started",
            f"@{self.unique_id} の録画を開始しました（画質 {quality}）",
            detail={"quality": quality, "stem": self.base, "path": str(self.hls_dir),
                    "segment_seconds": SEGMENT_SECONDS,
                    "final_dir": str(self._final_dir), "keep_hls": self._keep_hls},
        )

    async def _run(self, url: str) -> None:
        # Correlation must be bound inside this task: asyncio copies the context at
        # task creation, so ids set by the caller after start() returns never reach
        # here. unique_id/session_id are known now; recording_id is assigned by the
        # caller immediately after start(), so it is re-read each iteration rather
        # than bound once.
        ctx_unique_id.set(self.unique_id)
        ctx_session_id.set(self.session_id)
        log_path = self.hls_dir / "ffmpeg.log"
        attempt = 0
        try:
            while not self._stop_requested:
                ctx_recording_id.set(self.recording_id)
                attempt += 1
                self._launch_attempts = attempt
                proc = await self._launch(url, log_path)
                self._proc = proc
                healthy = await self._await_healthy(proc)
                if healthy:
                    # Playlist/segments now exist; tell the UI it can preview.
                    if proc.returncode is None and not self._stop_requested:
                        await self._notify()
                    await proc.wait()
                    if proc.returncode not in (0, None) and not self._stop_requested:
                        # ffmpeg gave up on its own (the source URL died and reconnect
                        # was exhausted). Capture ends here; the collector restarts a
                        # recording when the websocket reconnects.
                        logger.warning(
                            "capture process for %s exited %s on its own",
                            self.unique_id, proc.returncode,
                            extra={"event": "recording.capture_ended",
                                   "ctx": {"attempt": attempt, "segments": self._segment_count(),
                                           **ffmpeg_ctx(self._capture_args, proc.returncode, log_path)}},
                        )
                    break
                await self._terminate(proc)
                if self._stop_requested or attempt >= MAX_LAUNCH_ATTEMPTS:
                    if not self._has_segments():
                        logger.error(
                            "recording for %s never became healthy after %d attempt(s)",
                            self.unique_id, attempt,
                            extra={"event": "recording.launch_failed",
                                   "ctx": {"attempts": attempt, "max_attempts": MAX_LAUNCH_ATTEMPTS,
                                           "healthy_wait_seconds": HEALTHY_WAIT_SECONDS,
                                           "min_segments": MIN_SEGMENTS,
                                           "segments": self._segment_count(),
                                           "stop_requested": self._stop_requested,
                                           **ffmpeg_ctx(self._capture_args, proc.returncode, log_path)}},
                        )
                        raise RuntimeError(
                            f"録画を開始できませんでした（{attempt}回試行、stream接続不良）。"
                        )
                    break
                logger.warning(
                    "recording attempt %d unhealthy for %s, retrying", attempt, self.unique_id,
                    extra={"event": "recording.launch_retried",
                           "ctx": {"attempt": attempt, "max_attempts": MAX_LAUNCH_ATTEMPTS,
                                   "segments": self._segment_count(),
                                   **ffmpeg_ctx(self._capture_args, proc.returncode, log_path)}},
                )
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            if self._proc is not None:
                await self._terminate(self._proc)
            raise
        except Exception as exc:
            logger.exception(
                "recording failed for %s", self.unique_id,
                extra={"event": "recording.capture_failed",
                       "ctx": {"attempts": attempt, "segments": self._segment_count(),
                               "error": str(exc)}},
            )
            self.error = str(exc)
            self.state = STATE_FAILED
        finally:
            self._proc = None
            await self._finalize()

    def _segment_count(self) -> int:
        if self.hls_dir is None or not self.hls_dir.exists():
            return 0
        return len(list(self.hls_dir.glob("seg*.ts")))

    async def _launch(self, url: str, log_path: Path) -> asyncio.subprocess.Process:
        args = [
            "ffmpeg", "-nostdin", "-y", "-loglevel", "warning",
            "-fflags", "+discardcorrupt", "-analyzeduration", "10M", "-probesize", "10M",
            "-reconnect", "1", "-reconnect_streamed", "1",
            "-reconnect_on_network_error", "1", "-reconnect_on_http_error", "4xx,5xx",
            "-reconnect_delay_max", str(RECONNECT_DELAY_MAX),
            "-i", url,
            "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
            "-f", "hls", "-hls_time", str(SEGMENT_SECONDS), "-hls_list_size", "0",
            "-hls_flags", "append_list+independent_segments",
            "-hls_segment_filename", str(self.hls_dir / "seg%05d.ts"),
            str(self.playlist),
        ]
        # Kept so every failure log for this recording can quote the exact command line
        # without re-deriving (and possibly mis-stating) it.
        self._capture_args = args
        logger.debug(
            "launching capture process for %s", self.unique_id,
            extra={"event": "process.ffmpeg_started",
                   "ctx": {"stage": "capture", "attempt": self._launch_attempts,
                           "stderr_path": str(log_path), **ffmpeg_ctx(args)}},
        )
        log_file = open(log_path, "ab")
        try:
            return await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=log_file,
            )
        except Exception:
            logger.error(
                "capture process for %s failed to launch", self.unique_id,
                extra={"event": "process.ffmpeg_launch_failed",
                       "ctx": {"stage": "capture", "attempt": self._launch_attempts,
                               **ffmpeg_ctx(args)}},
                exc_info=True,
            )
            raise
        finally:
            log_file.close()

    async def _await_healthy(self, proc: asyncio.subprocess.Process) -> bool:
        for _ in range(HEALTHY_WAIT_SECONDS):
            await asyncio.sleep(1)
            if proc.returncode is not None:
                return self._has_segments()
            if self._has_segments():
                return True
        return self._has_segments()

    def _has_segments(self) -> bool:
        return self._segment_count() >= MIN_SEGMENTS

    async def _terminate(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        for sig in _TERMINATE_SIGNALS:
            try:
                proc.send_signal(sig)
            except (ProcessLookupError, ValueError):
                return
            try:
                await asyncio.wait_for(proc.wait(), timeout=8)
                return
            except asyncio.TimeoutError:
                continue
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass

    async def _notify(self) -> None:
        if self._on_notify is not None:
            try:
                await self._on_notify()
            except Exception:
                logger.exception(
                    "recording notify callback failed for %s", self.unique_id,
                    extra={"event": "recording.notify_failed", "ctx": {"state": self.state}},
                )

    async def finalize_recovered_hls(self, base: str, progress=None, mp4_root=None) -> None:
        """既存HLSディレクトリ(base)を、live captureを伴わずconcat→mp4化する。録画中にプロセスが
        クラッシュして_finalizeを走らせられなかった録画を、起動時に復元するために使う。start()を
        経ないのでpath類をここで確定してから通常のfinalize経路を再利用する。``progress``が
        あれば concat→timing→normalize の各段階を JobProgress へ報告する(履歴からの
        再mp4化で使用)。以前は単一解像度re-encodeの%しか出しておらず、均一解像度の録画
        (=通常ケース)では一度も報告されないまま0%から100%へ飛んでいた。

        ``mp4_root`` を渡すと、.tsを読むroot(``record_dir``)と別のrootへmp4を書く。既に
        完成してfinal dirへ移送済みの録画を作り直す場合、segmentはwork rootに残る一方で
        mp4の住所はfinal rootであり、両者は一致しない。既定(None)は従来どおりsegmentと
        同じroot。live captureが無い経路なので、一旦work rootへ書いてから移送する理由も
        無い(数十GBを二度書きしない)。"""
        self.base = base
        self.hls_dir = layout.session_dir(self._record_dir, base)
        self.playlist = self.hls_dir / "index.m3u8"
        self._mp4_path = layout.mp4_path(mp4_root or self._record_dir, base)
        self._mp4_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path = None
        self.started_at = self.started_at or time.time()
        await self._finalize(progress=progress)

    def _hls_log_path(self) -> Optional[Path]:
        if self.hls_dir is None:
            return None
        path = self.hls_dir / "ffmpeg.log"
        return path if path.is_file() else None

    async def _finalize(self, progress=None) -> None:
        self.ended_at = time.time()
        started_ms = time.monotonic()
        # Sample free space now, while every artifact of this recording is still on
        # disk. The failure branches below remove the HLS tree, so a sample taken from
        # an except block would show a volume that the cleanup has just freed.
        self._disk_report = disk_free_by_volume(self._volume_paths())
        segments = self._segment_count()
        duration_seconds = (
            round(self.ended_at - self.started_at, 3) if self.started_at else None
        )
        # Capture has ended; concat/validation is post-processing that no longer
        # blocks a new recording (is_active excludes STATE_FINALIZING).
        if self.state != STATE_FAILED:
            self.state = STATE_FINALIZING
        await self._notify()
        if self._has_segments():
            mp4_path = self._mp4_path
            if await self._concat_to_mp4(mp4_path, progress=progress):
                self.output_path = mp4_path
                # Persist the wall->media->pts timing map while the HLS source
                # still exists, so the burn-in can lock comments to the video
                # timeline.
                if progress is not None:
                    await progress.set("timing", 0.0)
                await self._write_timing_map(mp4_path)
                if progress is not None:
                    await progress.done("timing")
                # If the source switched resolution mid-broadcast, the stream-copied
                # mp4 carries mixed resolutions in one track (players freeze/zoom at
                # each switch). Re-encode to a single resolution, timestamps preserved
                # so the timing map above stays valid. Detected from the concatenated
                # mp4's keyframes; a no-op for uniform streams.
                await self._normalize_mixed_resolution(mp4_path, progress=progress)
                # 配信中に押された見どころをmp4のPTS軸へ載せ直す。正規化の後に置くのは、
                # CFR再encodeへ落ちるとtiming mapが破棄されるため。前に置くと、既に無効な
                # mapで確定させてしまう。
                await self._remap_live_bookmarks(mp4_path)
                # 尺は出来上がったmp4から測る。移送(_relocate_to_final)より前に測るのは、
                # 移送先が別volumeで、失敗すれば所在が変わるため。中身は同じなので値は同じ。
                self.duration_seconds = await self._measure_duration(mp4_path)
                # Keep the HLS source until the mp4 is confirmed playable. If
                # ffprobe is unavailable we cannot confirm, so keep HLS too.
                if not ffprobe_available():
                    logger.warning(
                        "ffprobe unavailable; keeping HLS for %s (mp4 unverified)", self.unique_id,
                        extra={"event": "recording.validation_skipped",
                               "ctx": {"reason": "no_ffprobe", "stem": self.base,
                                       "path": str(self.hls_dir)}},
                    )
                    if self.state != STATE_FAILED:
                        self.state = STATE_COMPLETED
                elif await self._validate_mp4(mp4_path):
                    if self.state != STATE_FAILED:
                        self.state = STATE_COMPLETED
                    if not self._keep_hls:
                        shutil.rmtree(self.hls_dir, ignore_errors=True)
                        # Relocate only in the clean path (mp4 validated, HLS removed).
                        # keep_hls / unverified paths retain the HLS in the working dir,
                        # so the mp4 stays beside it rather than splitting the pair.
                        await self._relocate_to_final()
                    else:
                        logger.info(
                            "keeping HLS for %s (diagnostic): %s", self.unique_id, self.hls_dir,
                            extra={"event": "recording.hls_retained",
                                   "ctx": {"reason": "keep_hls", "stem": self.base,
                                           "path": str(self.hls_dir), "segments": segments}},
                        )
                else:
                    # 検証に失敗したmp4をsnapshotへ晒さない。再生可能な成果物は温存
                    # したHLSなので、concat失敗branchと同様にplaylistを指す。
                    self.output_path = self.playlist
                    if self.state != STATE_FAILED:
                        self.state = STATE_FAILED
                        self.error = self.error or "mp4の検証に失敗しました（HLSを保持しています）。"
                    self._ops(
                        "recording.validation_failed",
                        f"確定したmp4に再生できる映像がありません（@{self.unique_id}）。"
                        f"HLS segmentは残します",
                        severity="error",
                        detail={"stem": self.base, "path": str(mp4_path),
                                "size_bytes": mp4_path.stat().st_size if mp4_path.is_file() else 0,
                                "segments": segments, "volumes": self._disk_report},
                    )
            else:
                # Keep HLS dir as the fallback artifact (still playable).
                self.output_path = self.playlist
                if self.state != STATE_FAILED:
                    self.state = STATE_FAILED
                    self.error = self.error or "mp4への変換に失敗しました（HLSは残っています）。"
                self._ops(
                    "recording.concat_failed",
                    f"mp4を組み立てられませんでした（@{self.unique_id}）。HLS segmentは残します",
                    severity="error",
                    detail={"stem": self.base, "segments": segments,
                            "path": str(self.hls_dir), "volumes": self._disk_report},
                )
        else:
            if self.state != STATE_FAILED:
                self.state = STATE_FAILED
                self.error = self.error or "録画Dataが空でした（stream接続不良）。"
            # The empty finalize: capture produced fewer than MIN_SEGMENTS segments and
            # everything is about to be deleted. This is the only record that the
            # attempt happened at all, so it carries the capture command, ffmpeg's exit
            # trail and the pre-cleanup free space — the three things an "empty
            # recording" report is otherwise missing.
            self._ops(
                "recording.empty_finalized",
                f"録画に使える映像が無かったため破棄しました（@{self.unique_id}）",
                severity="error",
                duration_ms=int((self.ended_at - self.started_at) * 1000) if self.started_at else None,
                detail={"stem": self.base, "segments": segments,
                        "min_segments": MIN_SEGMENTS, "attempts": self._launch_attempts,
                        "path": str(self.hls_dir), "volumes": self._disk_report,
                        **ffmpeg_ctx(self._capture_args, stderr_log=self._hls_log_path())},
            )
            shutil.rmtree(self.hls_dir, ignore_errors=True)
        if self._on_finalize is not None:
            try:
                await self._on_finalize(self)
            except Exception:
                logger.exception(
                    "recording finalize callback failed for %s", self.unique_id,
                    extra={"event": "recording.finalize_callback_failed",
                           "ctx": {"state": self.state, "stem": self.base}},
                )
        size_bytes = (
            self.output_path.stat().st_size
            if self.output_path is not None and self.output_path.is_file() else 0
        )
        self._ops(
            "recording.finalized",
            f"@{self.unique_id} の録画を確定しました（状態 {self.state}）",
            severity="info" if self.state == STATE_COMPLETED else "warning",
            duration_ms=int((time.monotonic() - started_ms) * 1000),
            detail={"state": self.state, "stem": self.base,
                    "path": str(self.output_path) if self.output_path else "",
                    "size_bytes": size_bytes, "segments": segments,
                    # 壁時計(capture_seconds)と実尺(media_seconds)は別物。両方残すと、捕捉が
                    # どれだけ停滞したかがlogだけで読める。
                    "capture_seconds": duration_seconds,
                    "media_seconds": self.duration_seconds, "error": self.error},
        )

    async def _relocate_to_final(self) -> None:
        """Move the finished mp4 (and its timing sidecar) from the working dir (SSD) to
        the final dir (HDD). The move is cross-volume, so it runs off the event loop via
        shutil.move (copy+unlink). On failure the mp4 stays in the working dir and keeps
        serving as output_path (still playable/renderable): no fake final location, and
        the working dir is an allowed record root so output/delete still resolve it."""
        if self._final_dir == self._record_dir:
            return
        src = self.output_path
        if src is None or not src.is_file():
            return
        dst = layout.mp4_path(self._final_dir, self.base)
        size_bytes = src.stat().st_size
        started = time.monotonic()
        try:
            moved_derived = await asyncio.to_thread(self._move_recording_files, src, dst)
        except OSError as exc:
            # Degraded but not lost: the mp4 stays in the working dir, which is an
            # allowed record root, so playback and rendering still resolve it.
            logger.warning(
                "failed to relocate recording %s to final dir %s; kept at %s",
                src.name, self._final_dir, src,
                extra={"event": "recording.relocation_failed",
                       "ctx": {"stem": self.base, "path": str(src),
                               "final_dir": str(self._final_dir),
                               "size_bytes": size_bytes,
                               "volumes": self._disk_report, **_oserror_ctx(exc)}},
                exc_info=True,
            )
            # Drop a partial copy left by an interrupted cross-volume move so a later
            # scan does not mistake it for a complete recording (src is still intact).
            if src.is_file() and dst.is_file():
                try:
                    dst.unlink()
                except OSError as unlink_exc:
                    logger.error(
                        "could not remove the partial copy left by the failed relocation "
                        "of %s; a later scan may mistake it for a complete recording",
                        src.name,
                        extra={"event": "recording.partial_copy_orphaned",
                               "ctx": {"stem": self.base, "path": str(dst),
                                       **_oserror_ctx(unlink_exc)}},
                        exc_info=True,
                    )
            return
        self.output_path = dst
        logger.info(
            "relocated recording %s -> %s (%d derived file(s))", src.name, dst, moved_derived,
            extra={"event": "recording.relocated",
                   "ctx": {"stem": self.base, "path": str(dst),
                           "final_dir": str(self._final_dir), "size_bytes": size_bytes,
                           "derived_moved": moved_derived,
                           "duration_ms": int((time.monotonic() - started) * 1000)}},
        )

    @staticmethod
    def _move_recording_files(src: Path, dst: Path) -> int:
        """Move the mp4 and every artifact derived from it. Runs in a thread. Returns the
        number of derived files moved. A failed mp4 move raises (caller keeps the working
        copy); a failed derived move is logged but not fatal.

        すべての派生fileは現在のmp4位置から解決される(``record_root_of``)。mp4だけを移すと
        残りは旧rootに取り残され、誰も見に行かなくなる:焼き込み済みの``.overlay.mp4``は
        画面から消え(実測12.1GBが不可視のまま残っていた)、``.timing.json``が欠けた録画は
        焼き込みが概算timingに落ちてコメントがズレ、``.overlay.meta``が欠ければcacheが
        当たらず全編を再encodeする。掃除もmp4基準なので、録画を消しても旧rootの残骸は
        永久に残る。ゆえにmp4と派生fileは常に一緒に動かす。

        staticmethod: this never touched ``self``, and the ops-screen "relocate to the
        final dir" action has to move the same set for recordings that finished long ago
        (no Recorder instance exists for those). Making it static lets that path reuse
        this verbatim instead of growing a second mover that could drift from this one.
        ``self._move_recording_files(src, dst)`` still resolves as before.
        """
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        moved = 0
        for src_path, dst_path in zip(relocatable_artifact_paths(src),
                                      relocatable_artifact_paths(dst)):
            if not src_path.is_file():
                continue
            try:
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src_path), str(dst_path))
                moved += 1
            except OSError as exc:
                logger.warning(
                    "relocated mp4 but failed to move derived file %s for %s",
                    src_path.name, src.name,
                    extra={"event": "recording.derived_relocation_failed",
                           "ctx": {"stem": src.stem, "path": str(src_path),
                                   "dst": str(dst_path), **_oserror_ctx(exc)}},
                    exc_info=True,
                )
        return moved

    async def _concat_audio_args(self, first_segment: Path) -> list:
        """結合passの音声引数。既定は録画時と同じAAC 192k、``normalize_audio``を渡された
        ときだけloudnormを重ねる。

        Lazy import: audio_normはこのmoduleからffmpeg_ctx/ffprobe_availableを取るので、
        top-levelで入れると循環する。
        """
        base = ["-c:a", "aac", "-b:a", "192k", "-af", "aresample=async=1:first_pts=0"]
        if not self._normalize_audio:
            return base
        from tictok.record import audio_norm
        # loudnormは入力に関わらず192kHzを出す。sourceの実rateへ戻さないと音声dataだけが
        # 倍に膨らむため、結合前に1本目の.tsから実値を測る(全segmentで同じrate)。
        rate = await asyncio.to_thread(audio_norm.probe_sample_rate, first_segment)
        return audio_norm.encode_args(**self._normalize_audio, sample_rate=rate,
                                      resample="async=1:first_pts=0")

    async def _concat_to_mp4(self, dst: Path, progress=None) -> bool:
        # Join the segments through the HLS demuxer, driven by the terminated VOD
        # playlist written here rather than the captured index: on stop ffmpeg is
        # force-terminated (Windows send_signal maps SIGTERM to TerminateProcess, a
        # hard kill), so the captured index never gets an #EXT-X-ENDLIST tag and the
        # demuxer would treat it as a live stream — seeking to the live edge and
        # blocking on further reads. The playlist written here is explicitly VOD and
        # terminated, so the whole recording is read from the first segment.
        #
        # The concat demuxer cannot be used here. It re-bases each .ts onto a
        # cumulative offset derived from that file's overall duration, but inside every
        # segment the audio starts ~0.1s ahead of the video. The difference opens a
        # ~0.1s hole in the audio at every segment boundary — the source itself is
        # gap-free — which either drifts (samples packed) or clicks (holes stuffed with
        # silence) depending on how they are filled, and inflates the container ~5%
        # past the real media span. The HLS demuxer honours the segments' own
        # timestamps, so no hole is opened and no inflation is introduced.
        started = time.monotonic()
        kept = self._playlist_segments()
        if not kept:
            logger.error(
                "no usable HLS segments to concatenate for %s", self.unique_id,
                extra={"event": "recording.concat_aborted",
                       "ctx": {"stem": self.base, "path": str(self.hls_dir),
                               "reason": "no_segments"}},
            )
            return False
        list_path = self.hls_dir / VOD_PLAYLIST_NAME
        if not self._write_vod_playlist(kept, list_path):
            return False
        segments = [seg for seg, _, _, _ in kept]
        # 解像度のkeyframe走査を、concatと同じ再生listに対して並行で走らせる。連結後のmp4を
        # 頭から読み直すのと結果は同じで(同じdemuxer→decoder経路)、順番に走らせていたその
        # 一巡ぶん(実測: 349MBで14秒、1.2GBで50秒)がまるごと消える。concatはこの間ずっと
        # 同じ.tsを読んでいるので、二度目の読み出しはOSのcacheに当たる。
        self._concat_resolutions = None
        probe_task = (
            asyncio.create_task(probe_mp4_resolutions(list_path, HLS_INPUT_ARGS))
            if ffprobe_available() else None
        )
        try:
            # Live TS segments carry arbitrary start PTS/DTS; without genpts +
            # avoid_negative_ts the muxed mp4 gets non-monotonic/negative
            # timestamps that some players refuse to play.
            #
            # Audio is re-encoded (not copied) through aresample so a genuine hole in
            # the source is filled with silence rather than packed away: packing makes
            # Chrome run the audio ahead of the video by the full deficit while VLC
            # honours the timestamps and stays in sync, so the same file plays
            # differently per player. With the HLS demuxer the boundaries themselves no
            # longer produce holes, leaving this to act only on real source loss. Video
            # stays a stream copy, so picture quality and the timestamps the comment
            # burn-in maps against are untouched.
            # 分母は再生listのEXTINFの総和。数時間ぶんの.tsを1本のffmpegで通すこの pass が
            # 再mp4化の実時間の大半で、以前はここが完全に無報告だった。
            total_us = int(sum(extinf for _, extinf, _, _ in kept) * 1_000_000)
            report = (progress.cb("concat", total_us / 1_000_000)
                      if (progress is not None and total_us > 0) else None)
            args = [
                "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
                *(["-progress", "pipe:1", "-nostats"] if report else []),
                "-allowed_extensions", "ALL",
                "-protocol_whitelist", "file,crypto,data",
                "-fflags", "+genpts",
                "-i", str(list_path),
                "-c:v", "copy",
                *await self._concat_audio_args(segments[0]),
                "-movflags", "+faststart",
                "-avoid_negative_ts", "make_zero", str(dst),
            ]
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=(asyncio.subprocess.PIPE if report else asyncio.subprocess.DEVNULL),
                stderr=asyncio.subprocess.PIPE,
            )
            # communicate()は両streamを読むので、進捗をpumpする間はstderrを別taskで
            # 読む。片方だけ放置するとpipe bufferが埋まってffmpegが止まる。
            # 再mp4化から呼ばれた時だけ、この ffmpeg を job の cancel 対象にする
            # (通常録画のfinalizeはjob context外なのでno-op)。登録が無いと、userの
            # 取り消しが数時間走るconcatに届かない。
            cancel.register_process(proc)
            try:
                err_task = asyncio.create_task(proc.stderr.read())
                if report:
                    await pump_ffmpeg_progress(proc.stdout, total_us, report)
                err = await err_task
                await proc.wait()
            finally:
                cancel.forget_process(proc)
            stderr_text = err.decode("utf-8", "replace")
            if cancel.is_cancelled():
                # killされたffmpegは本物の失敗と同じ非0を返す。取り消しをerrorとして
                # 記録しないよう、returncodeを見る前に判定する。
                dst.unlink(missing_ok=True)
                cancel.check_cancelled()
            size_bytes = dst.stat().st_size if dst.exists() else 0
            if proc.returncode == 0 and size_bytes > 0:
                # 並行probeの結果を受け取る。空(=probeが1件も解像度を返せなかった)なら
                # 持ち越さない: normalize側が連結後mp4を読み直して判定し直す。
                if probe_task is not None:
                    self._concat_resolutions = (await probe_task) or None
                logger.info(
                    "concatenated %d segment(s) of %s into an mp4",
                    len(segments), self.unique_id,
                    extra={"event": "recording.concatenated",
                           "ctx": {"stem": self.base, "path": str(dst),
                                   "segments": len(segments), "size_bytes": size_bytes,
                                   "duration_ms": int((time.monotonic() - started) * 1000)}},
                )
                # pumpは99%上限なので、閉じないとこの段階が永久に「進行中」で残る。
                if progress is not None:
                    await progress.done("concat")
                return True
            logger.error(
                "concat to mp4 failed for %s (exit %s, %d bytes written)",
                self.unique_id, proc.returncode, size_bytes,
                extra={"event": "process.ffmpeg_failed",
                       "ctx": {"stage": "concat", "stem": self.base,
                               "segments": len(segments), "size_bytes": size_bytes,
                               "volumes": disk_free_by_volume(self._volume_paths()),
                               **ffmpeg_ctx(args, proc.returncode, stderr_text=stderr_text)}},
            )
            return False
        except Exception:
            logger.exception(
                "concat to mp4 failed to run for %s", self.unique_id,
                extra={"event": "process.ffmpeg_launch_failed",
                       "ctx": {"stage": "concat", "stem": self.base,
                               "segments": len(segments)}},
            )
            return False
        finally:
            # probeは再生listを読んでいる。listを消す前・この関数を抜ける前に必ず畳む。
            if probe_task is not None and not probe_task.done():
                probe_task.cancel()
                try:
                    await probe_task
                except (asyncio.CancelledError, Exception):
                    pass
            # Keep the VOD playlist alongside the segments when retaining HLS, so the
            # exact segment order/durations fed to the muxer can be inspected later.
            if not self._keep_hls:
                list_path.unlink(missing_ok=True)

    def _playlist_segments(self) -> list:
        """Ordered ``[(path, extinf, wall, discontinuous), ...]`` for the segments that
        make up this recording, with PTS-discontinuity segments removed.

        The playlist (kept via append_list) is the authority for both order and media
        span: a .ts on disk with no playlist entry is an unindexed partial write and is
        excluded rather than muxed. A segment's real wall duration is its file-mtime
        delta from the previous entry; when its EXTINF dwarfs that, it carries a
        glitched source timestamp that would bake a phantom gap into the mp4, so it is
        dropped — logged, never silently. ``discontinuous`` marks an entry that follows
        a dropped/unusable one or that the source itself flagged, so the VOD playlist
        can carry an #EXT-X-DISCONTINUITY and the demuxer re-bases across the timestamp
        jump instead of muxing the jump as elapsed time.

        The concat and the timing map both build on this, so the two cannot disagree
        about which segments the finalized mp4 contains."""
        if self.playlist is None or not self.playlist.is_file() or self.hls_dir is None:
            return []
        try:
            lines = self.playlist.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            logger.warning(
                "HLS playlist read failed for %s", self.unique_id,
                extra={"event": "recording.playlist_read_failed",
                       "ctx": {"stem": self.base, "path": str(self.playlist)}},
                exc_info=True,
            )
            return []
        kept: list = []
        dropped: list = []
        unusable = 0
        duplicates: list = []
        empties: list = []
        rewinds = 0
        seen: set = set()
        pending: Optional[float] = None
        prev_wall: Optional[float] = None
        marked = False   # the source flagged a discontinuity before the next entry
        carry = False    # the preceding entry was dropped, so the next one jumps
        for line in lines:
            line = line.strip()
            if line == "#EXT-X-DISCONTINUITY":
                marked = True
            elif line.startswith("#EXTINF:"):
                try:
                    pending = float(line[len("#EXTINF:"):].split(",", 1)[0])
                except ValueError:
                    pending = None
            elif line and not line.startswith("#"):
                extinf, pending = pending, None
                seg = self.hls_dir / line
                try:
                    st = seg.stat() if extinf is not None else None
                except OSError:
                    st = None
                if extinf is None or st is None:
                    unusable += 1
                    carry = True
                    continue
                if line in seen:
                    # ffmpeg's hls muxer restarts its segment counter, so a relaunch
                    # into the same directory (append_list) can list a name twice. Both
                    # entries resolve to one file, so muxing both replays that slice:
                    # the container outruns the media axis and every overlay after the
                    # repeat lands seconds off. Keep the first occurrence, which is the
                    # only choice that leaves the timeline ascending.
                    duplicates.append(line)
                    continue
                seen.add(line)
                if st.st_size == 0:
                    # Its #EXTINF still counts: the segment's timestamps are preserved
                    # by the mux, so the media time really did elapse and the result is
                    # an honest freeze rather than a shift. Worth surfacing all the same
                    # -- an empty segment means a write that did not land.
                    empties.append(line)
                wall = st.st_mtime
                if prev_wall is not None and wall <= prev_wall:
                    # The wall clock moved backwards or stalled (NTP correction, DST, a
                    # manual set). Anchors must come out strictly ascending: the burn-in
                    # sorts them by wall (video_overlay._load_timing_anchors), so an
                    # out-of-order pair does not merely misplace one comment, it
                    # reorders the media column and corrupts the whole map.
                    rewinds += 1
                    wall = prev_wall + ANCHOR_MIN_STEP_SECONDS
                delta = wall - prev_wall if prev_wall is not None else None
                prev_wall = wall
                if delta is not None and is_pts_discontinuity(extinf, delta):
                    dropped.append((line, extinf, delta))
                    carry = True
                    continue
                kept.append((seg, extinf, wall, marked or carry))
                marked = carry = False
        if dropped:
            logger.warning(
                "%s: dropping %d PTS-discontinuity segment(s) to avoid a phantom gap: %s",
                self.unique_id, len(dropped),
                ", ".join("%s(EXTINF=%.1fs wall=%.1fs)" % (n, e, w) for n, e, w in dropped),
                extra={"event": "recording.segments_dropped",
                       "ctx": {"stem": self.base, "dropped": len(dropped),
                               "segments": len(kept) + len(dropped) + unusable,
                               "phantom_seconds": round(sum(e - w for _, e, w in dropped), 3),
                               "dropped_segments": [
                                   {"stem": n, "extinf_seconds": round(e, 3),
                                    "wall_seconds": round(w, 3)} for n, e, w in dropped
                               ]}},
            )
        if unusable:
            logger.warning(
                "%s: %d playlist entry/entries had no usable segment file or #EXTINF",
                self.unique_id, unusable,
                extra={"event": "recording.playlist_entries_unusable",
                       "ctx": {"stem": self.base, "unusable": unusable,
                               "segments": len(kept) + len(dropped) + unusable}},
            )
        if duplicates:
            logger.warning(
                "%s: playlist listed %d segment name(s) more than once; kept the first "
                "occurrence of each: %s", self.unique_id, len(duplicates),
                ", ".join(duplicates[:10]),
                extra={"event": "recording.playlist_entries_duplicated",
                       "ctx": {"stem": self.base, "duplicates": len(duplicates),
                               "duplicate_segments": duplicates[:50],
                               "segments": len(kept) + len(dropped) + unusable}},
            )
        if empties:
            logger.warning(
                "%s: %d segment file(s) are empty; that media is lost and plays as a "
                "freeze: %s", self.unique_id, len(empties), ", ".join(empties[:10]),
                extra={"event": "recording.segments_empty",
                       "ctx": {"stem": self.base, "empty": len(empties),
                               "empty_segments": empties[:50],
                               "segments": len(kept) + len(dropped) + unusable}},
            )
        if rewinds:
            logger.warning(
                "%s: the wall clock failed to advance across %d segment boundary/ies; "
                "anchors were nudged to stay ordered and comment sync near them is "
                "approximate", self.unique_id, rewinds,
                extra={"event": "recording.wall_clock_rewound",
                       "ctx": {"stem": self.base, "rewinds": rewinds,
                               "segments": len(kept) + len(dropped) + unusable}},
            )
        return kept

    def _write_vod_playlist(self, kept: list, path: Path) -> bool:
        """Write the terminated VOD playlist the HLS demuxer reads at finalize.

        #EXT-X-PLAYLIST-TYPE:VOD plus #EXT-X-ENDLIST is what stops the demuxer from
        treating the captured (never-ended) capture index as a live stream."""
        target = max(int(extinf) + 1 for _, extinf, _, _ in kept)
        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:6",
            "#EXT-X-PLAYLIST-TYPE:VOD",
            "#EXT-X-MEDIA-SEQUENCE:0",
            "#EXT-X-INDEPENDENT-SEGMENTS",
            "#EXT-X-TARGETDURATION:%d" % target,
        ]
        for seg, extinf, _, discontinuous in kept:
            if discontinuous:
                lines.append("#EXT-X-DISCONTINUITY")
            lines.append("#EXTINF:%.6f," % extinf)
            # Bare names resolve relative to the playlist's own directory.
            lines.append(seg.name)
        lines.append("#EXT-X-ENDLIST")
        try:
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as exc:
            logger.error(
                "failed to write the VOD playlist for %s", self.unique_id,
                extra={"event": "recording.concat_list_write_failed",
                       "ctx": {"stem": self.base, "path": str(path),
                               "segments": len(kept),
                               "volumes": disk_free_by_volume(self._volume_paths()),
                               **_oserror_ctx(exc)}},
                exc_info=True,
            )
            return False
        return True

    async def _probe_duration(self, path: Path) -> Optional[float]:
        """Container duration (seconds) via ffprobe, or None on failure."""
        if not ffprobe_available():
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=nokey=1:noprint_wrappers=1", str(path),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        except (OSError, asyncio.TimeoutError):
            # Called once per HLS segment, so this is guarded rather than emitted: a
            # long recording has thousands of segments and the aggregate outcome is
            # reported by the caller as timing_map_degraded.
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "duration probe did not complete for %s", path.name,
                    extra={"event": "process.ffprobe_failed",
                           "ctx": {"stage": "duration", "path": str(path)}},
                    exc_info=True,
                )
            return None
        try:
            return float(out.decode("ascii", "replace").strip())
        except ValueError:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "duration probe returned no duration for %s", path.name,
                    extra={"event": "process.ffprobe_failed",
                           "ctx": {"stage": "duration", "path": str(path),
                                   "exit_code": proc.returncode}},
                )
            return None

    async def _normalize_mixed_resolution(self, mp4_path: Path, progress=None) -> None:
        """When the source switched resolution mid-broadcast, the stream-copied mp4 carries
        several resolutions in one video track — valid, but many players freeze/zoom at each
        switch. Re-encode such a recording to a single resolution (the largest seen), fitting
        every frame onto that canvas while preserving the original frame timestamps so the
        timing map written just before stays valid. A uniform-resolution recording is left as
        the lossless stream-copy. Best-effort: on failure the original mp4 is kept and the
        problem is logged (the recording is not lost). ``on_progress`` (if given) is awaited
        with the re-encode percent."""
        # The probe runs before the config gate and before the uniform-resolution
        # shortcut, and its result is always logged. Previously both of those returned
        # in silence, so on a host with normalization disabled or without ffprobe the
        # fact that a recording was mixed-resolution was recorded nowhere at all —
        # exactly the blind spot that made the original player freezes take so long to
        # attribute. The probe is a keyframe-only scan, so it is cheap enough to pay for
        # unconditionally.
        enabled = config.get_normalize_mixed_resolution()
        has_tools = ffmpeg_available() and ffprobe_available()
        # concatが同じ内容を並行走査済みならそれを使う(_concat_to_mp4を参照)。連結後mp4を
        # もう一巡読む必要が無くなるだけで、判定そのものは同じ。
        distinct = self._concat_resolutions
        if distinct is None:
            distinct = await probe_mp4_resolutions(mp4_path) if ffprobe_available() else set()
        summary = sorted(f"{w}x{h}" for w, h in distinct)
        if not has_tools:
            skip_reason = "no_ffprobe" if not ffprobe_available() else "no_ffmpeg"
        elif not enabled:
            skip_reason = "disabled"
        elif len(distinct) <= 1:
            skip_reason = "uniform"
        else:
            skip_reason = ""
        logger.info(
            "recording %s carries %d distinct resolution(s): %s%s",
            self.unique_id, len(distinct), ", ".join(summary) or "unknown",
            f" (normalization skipped: {skip_reason})" if skip_reason else "",
            extra={"event": "recording.resolutions_probed",
                   "ctx": {"stem": self.base, "path": str(mp4_path),
                           "distinct_resolutions": summary,
                           "distinct": len(distinct),
                           "mixed": len(distinct) > 1,
                           "normalize_enabled": enabled,
                           "skip_reason": skip_reason or None}},
        )
        if skip_reason:
            # 均一解像度・normalize無効・ffprobe不在のいずれか。この段階は走らないので、
            # 重みから外して残りの段階だけで100%へ届くようにする。ここを外さないと
            # 通常ケース(均一解像度)の再mp4化が60%で頭打ちになる。
            if progress is not None:
                progress.disable("normalize")
            if len(distinct) > 1:
                logger.warning(
                    "recording %s is mixed-resolution but normalization was skipped (%s); "
                    "players may freeze or zoom at each switch point",
                    self.unique_id, skip_reason,
                    extra={"event": "recording.normalization_skipped",
                           "ctx": {"stem": self.base, "skip_reason": skip_reason,
                                   "distinct_resolutions": summary}},
                )
            return
        # Largest width and height seen become the canvas; every smaller/differently-shaped
        # rendition is fitted onto it. Round up to even for yuv420p chroma subsampling.
        target_w = max(w for w, _ in distinct)
        target_h = max(h for _, h in distinct)
        target_w += target_w % 2
        target_h += target_h % 2
        mode = config.get_normalize_scale_mode()
        started = time.monotonic()
        logger.info(
            "normalizing mixed-resolution recording %s: %d distinct (%s) -> %dx%d (mode=%s)",
            self.unique_id, len(distinct), ", ".join(summary), target_w, target_h, mode,
            extra={"event": "recording.normalization_started",
                   "ctx": {"stem": self.base, "distinct_resolutions": summary,
                           "width": target_w, "height": target_h, "scale_mode": mode,
                           "codec": config.get_normalize_codec(),
                           "quality": config.get_normalize_quality(),
                           "volumes": disk_free_by_volume(self._volume_paths())}},
        )
        tmp = normalize_tmp_path(mp4_path)
        try:
            ok = await reencode_single_resolution(
                mp4_path, tmp, target_w, target_h, mode,
                config.get_normalize_codec(), config.get_normalize_quality(),
                on_progress=(progress.cb("normalize") if progress is not None else None),
                # 入力は直前の_concat_to_mp4が書いたmp4。音声はそこで一度aacへ揃えてある。
                audio_copy=True,
            )
            if ok and progress is not None:
                await progress.done("normalize")
        except Exception:
            logger.exception(
                "resolution normalization failed for %s", self.unique_id,
                extra={"event": "recording.normalization_failed",
                       "ctx": {"stem": self.base, "path": str(mp4_path),
                               "width": target_w, "height": target_h,
                               "duration_ms": int((time.monotonic() - started) * 1000),
                               "volumes": disk_free_by_volume(self._volume_paths())}},
            )
            tmp.unlink(missing_ok=True)
            return
        if not ok:
            logger.error(
                "resolution normalization produced no valid output for %s; keeping the "
                "mixed-resolution stream-copy mp4", self.unique_id,
                extra={"event": "recording.normalization_failed",
                       "ctx": {"stem": self.base, "path": str(mp4_path),
                               "width": target_w, "height": target_h,
                               "distinct_resolutions": summary,
                               "duration_ms": int((time.monotonic() - started) * 1000),
                               "volumes": disk_free_by_volume(self._volume_paths())}},
            )
            tmp.unlink(missing_ok=True)
            return
        if not await commit_normalized(tmp, mp4_path, ok):
            # 完成したre-encodeは消さずに残す(一時的なlockで捨てない)。元の混在mp4もその場に
            # 残るので、この時点では「壊れた方が使われている」状態。完了印を添えてあるため、
            # 次のserver起動時のsweepと次の焼き込み直前に自動で拾い直される。
            logger.error(
                "could not swap normalized mp4 into place for %s (destination locked); "
                "the re-encode is kept at %s and will be reclaimed at the next startup "
                "sweep or output job", self.unique_id, tmp.name,
                extra={"event": "recording.normalized_output_orphaned",
                       "ctx": {"stem": self.base, "path": str(tmp),
                               "size_bytes": tmp.stat().st_size if tmp.is_file() else 0,
                               "timing_mode": ok, "width": target_w, "height": target_h,
                               "reclaimable": read_normalize_marker(tmp) is not None,
                               "duration_ms": int((time.monotonic() - started) * 1000)}},
            )
            return
        if ok == "cfr":
            # commit_normalized already dropped the now-mismatched media->pts map; the
            # comment burn-in falls back to its wall-clock approximation.
            logger.warning(
                "resolution-normalized recording %s -> %dx%d via CFR fallback; dropped the "
                "timing map (comment sync will be approximate)", self.unique_id, target_w, target_h,
                extra={"event": "recording.timing_map_dropped",
                       "ctx": {"stem": self.base, "reason": "cfr_reencode",
                               "path": str(timing_path(mp4_path)),
                               "width": target_w, "height": target_h,
                               "duration_ms": int((time.monotonic() - started) * 1000)}},
            )
        else:
            logger.info(
                "resolution-normalized recording %s -> %dx%d",
                self.unique_id, target_w, target_h,
                extra={"event": "recording.normalized",
                       "ctx": {"stem": self.base, "path": str(mp4_path),
                               "width": target_w, "height": target_h,
                               "distinct_resolutions": summary, "timing_mode": ok,
                               "size_bytes": mp4_path.stat().st_size if mp4_path.is_file() else 0,
                               "duration_ms": int((time.monotonic() - started) * 1000)}},
            )

    async def _write_timing_map(self, mp4_path: Path) -> None:
        """Persist the wall->media->pts timing map beside the mp4.

        Comments are stamped with the collector's wall-clock, but the recorded
        video's timeline is the stream's media PTS; startup latency, reconnect
        gaps and encoder clock skew make the two drift apart over time. Each HLS
        segment gives an anchor: its #EXTINF accumulates the media position, and
        its file mtime is the wall-clock at which that media was written. The
        burn-in interpolates through these to place each comment on the real
        video timeline. The first-frame zero point is prepended (mtime(seg0) -
        extinf0). Written at finalize while the HLS dir still exists.

        The media->pts half is stored alongside so the burn-in never has to assume the
        two axes match. Since the mp4 is muxed through the HLS demuxer they do match
        (see _build_media_pts); the correspondence is written out regardless, both to
        pin the endpoint to the finalized duration and so a recording made by an older
        build — whose container ran ~5% long — stays distinguishable from one made by
        this one. Best-effort (falls back to the scale model when the probe fails)."""
        out = timing_path(mp4_path)
        try:
            if self.playlist is None or not self.playlist.is_file() or self.hls_dir is None:
                logger.warning(
                    "no HLS playlist for %s; the comment timing map cannot be built",
                    self.unique_id,
                    extra={"event": "recording.timing_map_skipped",
                           "ctx": {"stem": self.base, "reason": "no_playlist",
                                   "path": str(self.playlist) if self.playlist else ""}},
                )
                return
            # Exactly the segments the concat muxed, so the media axis stays gap-free
            # and aligned with the finalized mp4.
            kept = self._playlist_segments()
            if not kept:
                logger.warning(
                    "no usable segment in the playlist of %s; the comment timing map "
                    "cannot be built", self.unique_id,
                    extra={"event": "recording.timing_map_skipped",
                           "ctx": {"stem": self.base, "reason": "no_segments",
                                   "segments": 0}},
                )
                return
            # One segment is enough: the zero point prepended below is the second
            # anchor. Requiring two silently denied a map to every very short
            # recording, and to any recording whose other segments were dropped.
            media = 0.0
            anchors: list[tuple[float, float]] = []
            for _, extinf, wall, _ in kept:
                media += extinf
                anchors.append((wall, round(media, 6)))
            # Prepend the first-frame zero point: media 0 at the start of seg0.
            anchors.insert(0, (anchors[0][0] - anchors[0][1], 0.0))

            media_pts = await self._build_media_pts(kept, mp4_path)
            payload = {
                "version": 2 if media_pts else 1,
                "media_duration": anchors[-1][1],
                "anchors": [[w, m] for w, m in anchors],
            }
            if media_pts:
                payload["media_pts"] = media_pts
        except Exception:
            # Building the map failed (playlist parse / probe orchestration). The
            # recording survives; the burn-in falls back to a wall-clock approximation.
            logger.warning(
                "could not build the comment timing map for %s", self.unique_id,
                extra={"event": "recording.timing_map_skipped",
                       "ctx": {"stem": self.base, "reason": "build_error",
                               "path": str(self.playlist) if self.playlist else ""}},
                exc_info=True,
            )
            return
        serialized = json.dumps(payload)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(serialized, encoding="utf-8")
        except OSError as exc:
            # A distinct failure point from the build above: this is a disk write, and
            # its usual cause is a full volume. Sharing one warning with the probe path
            # made the two indistinguishable in the log, and neither carried the free
            # space that would have identified the cause. No automatic retry exists, so
            # the map is permanently lost for this recording -> error.
            logger.error(
                "failed to write the comment timing map for %s; comment sync for this "
                "recording will be approximate", self.unique_id,
                extra={"event": "recording.timing_map_write_failed",
                       "ctx": {"stem": self.base, "path": str(out),
                               "size_bytes": len(serialized.encode("utf-8")),
                               "anchors": len(payload.get("anchors") or []),
                               "volumes": disk_free_by_volume(self._volume_paths()),
                               **_oserror_ctx(exc)}},
                exc_info=True,
            )
            return
        logger.info(
            "wrote the comment timing map for %s (%d anchors, %.1fs of media)",
            self.unique_id, len(payload.get("anchors") or []), payload.get("media_duration") or 0.0,
            extra={"event": "recording.timing_map_written",
                   "ctx": {"stem": self.base, "path": str(out),
                           "timemap_version": payload.get("version"),
                           "anchors": len(payload.get("anchors") or []),
                           "media_pts_points": len(payload.get("media_pts") or []),
                           "media_duration_seconds": payload.get("media_duration")}},
        )

    async def _build_media_pts(self, kept: list, mp4_path: Path) -> Optional[list]:
        """Exact media->pts correspondence [[media, pts], ...], or None when the mp4
        cannot be probed (the burn-in then falls back to the single-scale model).

        The HLS demuxer carries each segment's own timestamps into the mp4, so a
        segment contributes exactly its #EXTINF to the container timeline and the two
        axes coincide — no per-segment mux overhead to model. The endpoint is still
        pinned to the finalized duration, which absorbs the sub-second residual
        between the spans the source declares and the ones it actually delivers."""
        mp4_dur = await self._probe_duration(mp4_path)
        extinfs = [extinf for _, extinf, _, _ in kept]
        media_pts = media_pts_from_segments(extinfs, extinfs, mp4_dur)
        if media_pts is None:
            logger.warning(
                "timing map for %s: the finalized mp4 could not be probed; media->pts "
                "falls back to the scale model", self.unique_id,
                extra={"event": "recording.timing_map_degraded",
                       "ctx": {"stem": self.base, "reason": "mp4_probe_failed",
                               "segments": len(extinfs),
                               "media_duration_seconds": mp4_dur}},
            )
        return media_pts

    async def _remap_live_bookmarks(self, mp4_path: Path) -> None:
        """配信中に押された見どころを、wall-clockからmp4のPTS軸へ載せ直す。

        押下時点ではwall-clockしか判らないが、mp4のPTS軸はmux inflationのぶん進みが速い。
        実測(本番録画): 5分の録画で39秒、37分で128秒、112分で340秒。時間が延びるほど開くので、
        押した位置を wall - started_at のまま残すと長時間配信ほど印が使い物にならない。

        変換は焼き込みと同じ _make_time_mapper を使う。ここで別実装を持つと、同じ録画に対して
        焼き込みのコメント位置と見どころの位置が食い違う。

        timing mapが無い/anchorが足りない場合は**確定させない**。pts_mapped=0のまま残せば
        画面が暫定値として扱えるが、ここで書き込むと暫定値が確定値として固定される。
        (解像度正規化がCFR再encodeへ落ちるとtiming mapは破棄されるため、実際に起こり得る。)
        """
        if self._storage is None or self.recording_id is None or not self.started_at:
            return
        pending = self._storage.list_unmapped_bookmarks(self.recording_id)
        if not pending:
            return
        # Lazy import: video_overlay imports from this module (see reencode_single_resolution).
        from tictok.record.video_overlay import (
            _load_media_pts,
            _load_timing_anchors,
            _make_time_mapper,
        )

        anchors = _load_timing_anchors(mp4_path)
        if not anchors:
            logger.warning(
                "live bookmarks for %s keep their provisional wall-clock position "
                "(%d marker(s)): no timing map to map them onto the mp4 timeline",
                self.unique_id, len(pending),
                extra={"event": "recording.bookmark_remap_skipped",
                       "ctx": {"stem": self.base, "markers": len(pending),
                               "reason": "no_timing_anchors"}},
            )
            return
        media_pts = _load_media_pts(mp4_path)
        video_duration = await self._probe_duration(mp4_path)
        mapper = _make_time_mapper(
            anchors, self.started_at, self.ended_at, video_duration, None, media_pts)

        mapped = []
        shifts = []
        for row in pending:
            pts = mapper(row["live_wall"])
            mapped.append((row["id"], pts))
            shifts.append(pts - row["start"])
        applied = self._storage.apply_bookmark_pts(mapped)
        worst = max((abs(s) for s in shifts), default=0.0)
        logger.info(
            "remapped %d live bookmark(s) for %s onto the mp4 timeline "
            "(largest correction %.1fs)", applied, self.unique_id, worst,
            extra={"event": "recording.bookmarks_remapped",
                   "ctx": {"stem": self.base, "markers": applied,
                           "max_shift_seconds": round(worst, 3),
                           "media_pts_points": len(media_pts or []),
                           "anchors": len(anchors)}},
        )

    async def _measure_duration(self, path: Path) -> Optional[float]:
        """DBへ残す実尺(秒)。測れなければNone。

        壁時計から推定しないのは、その推定こそが直そうとしている値だからである。捕捉が
        停滞した秒も再接続の待ちもended_at - started_atには載るが、動画には載らない。
        測れないなら「未測定」として残す方が、それらしい数字を置くより扱いやすい。

        測定そのものは_probe_durationに任せる(尺の出所を1つに保つ)。こちらは録画1本に
        つき1回しか呼ばれないので、segmentごとのprobeと違い失敗をwarningで出してよい。"""
        seconds = await self._probe_duration(path)
        if seconds and seconds > 0:
            return seconds
        logger.warning(
            "could not measure the duration of %s; leaving it unmeasured", path.name,
            extra={"event": "recording.duration_unmeasured",
                   "ctx": {"stem": self.base, "path": str(path),
                           "ffprobe": ffprobe_available()}},
        )
        return None

    async def _validate_mp4(self, path: Path) -> bool:
        """Confirm the mp4 has a decodable video stream before discarding HLS."""
        args = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await proc.communicate()
            if proc.returncode == 0 and b"video" in out:
                return True
            logger.warning(
                "mp4 validation of %s found no video stream (exit %s)",
                path.name, proc.returncode,
                extra={"event": "process.ffprobe_failed",
                       "ctx": {"stage": "validate", "stem": self.base, "path": str(path),
                               **ffmpeg_ctx(args, proc.returncode,
                                            stderr_text=err.decode("utf-8", "replace"))}},
            )
            return False
        except Exception:
            logger.exception(
                "mp4 validation could not run for %s", self.unique_id,
                extra={"event": "process.ffprobe_launch_failed",
                       "ctx": {"stage": "validate", "stem": self.base,
                               "path": str(path), **ffmpeg_ctx(args)}},
            )
            return False

    async def stop(self, wait: bool = False) -> None:
        """Stop the capture. By default returns once ffmpeg is terminated and
        lets finalize (mp4 concat) run in the background so a new recording can
        start immediately. Pass wait=True (shutdown/monitor stop) to block until
        the mp4 is fully written."""
        if self.is_active:
            self._stop_requested = True
            if self.state == STATE_RECORDING:
                self.state = STATE_STOPPING
            if self._proc is not None:
                await self._terminate(self._proc)
        if wait and self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=60)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.warning(
                    "recording task slow to finalize for %s; continuing without it",
                    self.unique_id,
                    extra={"event": "recording.finalize_timed_out",
                           "ctx": {"stem": self.base, "state": self.state}},
                )


def _row_points_at_file(row: dict) -> bool:
    """DB行のpathが実在するmp4を指しているか。

    finalizeがmp4を作った後・DB更新前に落ちると、行のpathは録画開始時に入れた録画dirの
    ままで残る。この行は status を interrupted に直しても出力・再生の入口(path.is_file())
    を全て素通りできないため、mp4があるかどうかとは別に必ず判定する。"""
    raw = row.get("path") or ""
    return bool(raw) and Path(raw).is_file()


def _finalized_mp4(base: str, dirs) -> Optional[Path]:
    """完成mp4が working dir(finalize済み) か final dir(移送済み) にあれば返す。"""
    for d in dirs:
        path = layout.mp4_path(d, base)
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


async def _reattach_orphan_mp4(storage, row: dict, base: str, mp4_path: Path) -> bool:
    """finalize済みなのにDB行が指していないmp4へ、行を張り直す。

    HLS segmentが残っていない以上この録画を作り直す手段は無く、放置すると2GBの完成品が
    「録画fileが存在しません」として出力も再生もできないまま残る。ffprobeが動画streamを
    確認できない場合だけは張り直さない(壊れたfileをcompletedとして提示しない)。"""
    recorder = Recorder("", str(mp4_path.parent), row.get("session_id"), storage=storage)
    recorder.recording_id = row.get("id")
    recorder.base = base
    if ffprobe_available() and not await recorder._validate_mp4(mp4_path):
        logger.error(
            "orphan mp4 for recording id=%s has no decodable video stream; leaving the "
            "row interrupted", row.get("id"),
            extra={"event": "recording.reattach_failed",
                   "ctx": {"stem": base, "path": str(mp4_path),
                           "size_bytes": mp4_path.stat().st_size}},
        )
        return False
    stat = mp4_path.stat()
    # mp4の書き上がり時刻が、この録画が実際に終わった時刻。ended_atが既にあればそれを残す
    # (張り直しは所在を直すだけで、捕捉が終わった時刻を動かさない)。
    duration = await recorder._measure_duration(mp4_path)
    storage.update_rebuilt_recording(
        row["id"], STATE_COMPLETED, str(mp4_path), mp4_path.name, stat.st_size, None,
        duration_seconds=duration, ended_at_if_missing=stat.st_mtime)
    logger.warning(
        "reattached recording id=%s to its finalized mp4 %s (DB row pointed at %s)",
        row.get("id"), mp4_path, row.get("path"),
        extra={"event": "recording.reattached",
               "ctx": {"stem": base, "path": str(mp4_path), "stale_path": row.get("path"),
                       "size_bytes": stat.st_size}},
    )
    return True


async def recover_interrupted_recordings(storage, record_dir, keep_hls: bool = False,
                                         final_dir=None) -> int:
    """起動時、クラッシュで中断した録画の捕捉済みHLS segmentをmp4へ再finalizeしてDB行を復旧する。
    プロセスが録画中に落ちると_finalizeが走らずDB行はseg*.tsを指さないまま(pathは録画dir、
    filenameは未生成mp4)残り、seg*.tsは孤立して再生不能になる。ここでconcat→mp4化し、成功した
    録画をcompletedとして実mp4パス/サイズで更新する。

    mp4は出来たがDB更新の前に落ちた場合(例: 混在解像度のnormalize中)も同じ壊れ方をする。
    segmentが残っていれば作り直し、残っていなければ出来ているmp4へ行を張り直す。segmentも
    mp4も無いものは既存のinterruptedのまま残す(mark_stale_recordingsの後始末に委ねる)。"""
    if not ffmpeg_available():
        logger.error(
            "ffmpeg unavailable; interrupted recordings cannot be recovered and their "
            "HLS segments stay unplayable",
            extra={"event": "recording.recovery_skipped", "ctx": {"reason": "ffmpeg_missing"}},
        )
        return 0
    record_dir = Path(record_dir)
    final_dir = Path(final_dir) if final_dir else record_dir
    log_disk_preflight(
        "recording.disk_checked",
        [record_dir, final_dir, config.get_db_path(), config.get_log_dir()],
        stage="recovery",
    )
    recovered = 0
    candidates = 0
    reattached = 0
    for row in storage.recordings_for_recovery():
        filename = row.get("filename") or ""
        base = Path(filename).stem if filename else ""
        if not base:
            continue
        # 復旧対象は「行が実fileを指していない」ものだけ。mp4の有無で判定すると、mp4は
        # 出来ているのに行が録画dirを指したままの録画(finalizeの途中でprocessが落ちた場合)
        # を「復旧不要」と読み違え、行が直らないまま残り続ける。
        if _row_points_at_file(row):
            continue
        existing = _finalized_mp4(base, {record_dir, final_dir})
        hls_dir = layout.session_dir(record_dir, base)
        has_segments = hls_dir.is_dir() and any(hls_dir.glob("seg*.ts"))
        if existing is not None and not has_segments:
            # 作り直す材料(seg*.ts)が無いので、出来ているmp4へ行を張り直す。作り直しでは
            # なく突き合わせなので、再生可能かをffprobeで確かめてからcompletedにする。
            if await _reattach_orphan_mp4(storage, row, base, existing):
                reattached += 1
            continue
        if not has_segments:
            continue  # 再finalizeできるsegmentが残っていない
        # Counted here, not per DB row: rows that already have an mp4 or have no
        # segments left were not recovery attempts and must not make the summary read
        # as a failure rate.
        candidates += 1
        recorder = Recorder(row.get("unique_id") or "", str(record_dir), row.get("session_id"),
                            keep_hls=keep_hls, final_dir=str(final_dir), storage=storage)
        recorder.recording_id = row.get("id")
        try:
            await recorder.finalize_recovered_hls(base)
        except Exception:
            logger.exception(
                "failed to recover interrupted recording id=%s", row.get("id"),
                extra={"event": "recording.recovery_failed",
                       "ctx": {"stem": base, "path": str(hls_dir),
                               "segments": len(list(hls_dir.glob("seg*.ts")))}},
            )
            continue
        snap = recorder.snapshot()
        if recorder.output_path is not None and snap.get("bytes", 0) > 0:
            # 復旧は落ちた録画を作り直すだけで、捕捉が終わった時刻を「今」にはしない。
            # ended_atを持たない行(中断のまま終わった録画)だけ、捕捉開始+実尺で埋める。
            # 捕捉は実時間で進むので、録画開始に尺を足した時刻が捕捉の終わりに当たる。
            ended_at_if_missing = (
                row["started_at"] + recorder.duration_seconds
                if row.get("started_at") and recorder.duration_seconds else None
            )
            storage.update_rebuilt_recording(
                row["id"],
                recorder.state,
                str(recorder.output_path),
                recorder.output_path.name,
                snap["bytes"],
                recorder.error,
                duration_seconds=recorder.duration_seconds,
                ended_at_if_missing=ended_at_if_missing,
            )
            recovered += 1
            logger.info(
                "recovered interrupted recording id=%s -> %s (%s)",
                row.get("id"), recorder.output_path, recorder.state,
                extra={"event": "recording.recovered",
                       "ctx": {"stem": base, "path": str(recorder.output_path),
                               "state": recorder.state, "size_bytes": snap["bytes"]}},
            )
        else:
            logger.error(
                "interrupted recording id=%s produced no usable mp4; its HLS segments "
                "remain unplayable", row.get("id"),
                extra={"event": "recording.recovery_failed",
                       "ctx": {"stem": base, "state": recorder.state,
                               "path": str(hls_dir), "size_bytes": snap.get("bytes", 0),
                               "error": recorder.error}},
            )
    if candidates or reattached:
        logger.warning(
            "recovered %d of %d interrupted recordings from the previous run "
            "(+%d reattached to an existing mp4)",
            recovered, candidates, reattached,
            extra={"event": "recording.recovery_completed",
                   "ctx": {"recovered": recovered, "candidates": candidates,
                           "reattached": reattached}},
        )
    return recovered + reattached
