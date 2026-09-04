import asyncio
import errno
import fnmatch
import json
import logging
import os
import re
import shutil
import signal
import sys
import time
import uuid
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Optional

from tictok.core import cancel
from tictok.core import config
from tictok.core import ffprobe
from tictok.core import layout
from tictok.core import orphan_capture
from tictok.core.logctx import ctx_recording_id, ctx_session_id, ctx_unique_id
from tictok.core.logging_setup import is_debug_enabled, progress_interval_seconds
from tictok.core.progress import pump_ffmpeg_progress
from tictok.record import hls_pack

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

# 確定処理(timing map・検証・最終保存先への移送)が今この瞬間掴んでいる録画のid。移送は
# session dirを丸ごと別volumeへ複製して元を消すので、その足元で素材を触るjob(ts結合・
# 再mp4化・焼き込み)が走ると読み手も移送も壊れる。
#
# DBのstatusでは代わりにならない。確定中でもDB行は「録画中」ではなく、復旧で確定する録画に
# 至っては interrupted のままなので、jobs側の「録画中は触らない」guardを素通りする(実測
# 2026-07-26 13:10、起動時のts結合sweepが復旧中の録画を束ね、移送のcopyが消えたばかりの
# segmentを掴んでFileNotFoundで落ちた)。同一processの単一instance運用なので、排他はここ
# (process内のset)で足りる。
_finalizing_ids: set = set()


@contextmanager
def finalizing_scope(recording_id):
    """``recording_id`` を確定処理中として登録する。DB行を持たないRecorderでは何もしない。"""
    rid = int(recording_id) if recording_id is not None else None
    if rid is not None:
        _finalizing_ids.add(rid)
    try:
        yield
    finally:
        if rid is not None:
            _finalizing_ids.discard(rid)


def is_finalizing(recording_id) -> bool:
    """その録画の確定処理が走っている最中か。素材を触るjobの投入・実行judgeに使う。"""
    return recording_id is not None and int(recording_id) in _finalizing_ids

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
# ``Path.glob("seg*.ts")`` と同じ判定を1回のscandirで下すためのmatcher。normcaseを噛ませて
# あるので、Windowsの大小無視までglobと一致する(patternは normcase 済みの綴りへ変換する)。
_SEGMENT_NAME_MATCH = re.compile(fnmatch.translate(os.path.normcase("seg*.ts"))).match
# How long ffmpeg keeps retrying a dropped input before giving up. Absorbs brief
# host-side blips that reuse the same stream URL. A full host re-broadcast
# reissues the URL, which ffmpeg cannot follow; that case is handled upstream by
# the collector restarting the recording on websocket reconnect.
RECONNECT_DELAY_MAX = 30

# 源の測定(_probe_source)を最後に走らせた時刻。unique_id別。失敗した録画は復旧loopが
# 約1分ごとに作り直すので、Recorder instanceの外で覚えないと同じ測定を毎回繰り返す。
_source_probe_at: dict = {}

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
    a different drive — the split between the two record roots exists precisely because
    of that — so a single "free bytes" number cannot answer which drive filled up. On
    Windows the drive letter is the volume; elsewhere the enclosing mount point is."""
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
                "%s までのpathに実在するdirectoryが無いため空き容量が分かりません", path,
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
                "%s の空き容量を読み取れません", anchor,
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
            "%s の空き容量が不足しています（%s の実行前）", ", ".join(low), stage,
            extra={"event": event, "ctx": ctx},
        )
    else:
        logger.info("%s の実行前に空き容量を確認しました", stage,
                    extra={"event": event, "ctx": ctx})
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


# PATH上の実行fileの有無はprocessの寿命で変わらない。Windowsの ``shutil.which`` は
# PATH x PATHEXT ぶんの存在確認を毎回叩くため、収集のsnapshotのように高頻度で通る経路で
# 効いてくる。
@lru_cache(maxsize=1)
def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


@lru_cache(maxsize=1)
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
                    "%s がまだlockされています。差し替えを再試行します（%d/%d 回目）",
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
        return await ffprobe.duration_seconds(path)
    except OSError:
        return None


# 再回収時の差し替えretry回数。既定のbackoffで概ね1分。
RECLAIM_REPLACE_ATTEMPTS = 7

# 単一解像度re-encodeの出力が、入力の尺の何割を保っていれば完成と見なすか。scale/padは
# frameを増減させないので、正常な再encodeは尺がそのまま残る。下回るのは途中でdecodeが
# 止まった場合だけで、実測では 872秒 / 10675秒 (8%) まで落ちた。
REENCODE_MIN_COVERAGE = 0.98


_COPY_CHUNK = 1 << 20


def _copy_durable(src: Path, dst: Path) -> int:
    """srcをdstへ複製し、**diskへ着くまで待って**からbytes数を返す。

    ``shutil.copy`` は書き込みがOSのcacheへ入った時点で返る。外付けdriveがcopyの途中で
    busから外れると、失敗はcallが返ったずっと後に「遅延書き込みの失敗」として現れるため、
    直後にsizeを確かめても cache 上の値を読むだけで「着いた」証明にならない。ここで fsync
    するのは、その値を根拠に元を消すからである。"""
    written = 0
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        while True:
            chunk = fin.read(_COPY_CHUNK)
            if not chunk:
                break
            fout.write(chunk)
            written += len(chunk)
        fout.flush()
        os.fsync(fout.fileno())
    shutil.copystat(src, dst)
    return written


def render_vod_playlist(kept: list, absolute: bool = False) -> str:
    """``_playlist_segments`` が採った集合を、終端済みVOD playlistとして描く。

    ``#EXT-X-PLAYLIST-TYPE:VOD`` と ``#EXT-X-ENDLIST`` が、終端の付かないcapture index
    (停止時のffmpegは強制終了されるので付かない)をlive streamと見なす挙動を止める。

    finalizeと再生の両方がここを通る。captureのindex.m3u8をそのまま再生に出すと、
    ``_playlist_segments`` が落としたsegment — 源のtimestampが壊れてEXTINFだけが巨大に
    なったもの — が再生の時間軸に戻ってくる。実測では132録画中6件がこれに当たり、
    1本のEXTINFが 2156s / 3760s / **28287s(7.8時間)** だった。落とす判断と描く場所を
    一致させておかないと、mp4の秒と再生の秒が録画によって何時間もずれる。"""
    target = max(int(extinf) + 1 for _, extinf, _, _, _ in kept)
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:6",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-INDEPENDENT-SEGMENTS",
        "#EXT-X-TARGETDURATION:%d" % target,
    ]
    for seg, extinf, _, discontinuous, byterange in kept:
        if discontinuous:
            lines.append("#EXT-X-DISCONTINUITY")
        lines.append("#EXTINF:%.6f," % extinf)
        if byterange is not None:
            # 束ね済みの録画では複数segmentが1 fileに入っているので、entryはそのfileの
            # 一部を指す。この行が無いとdemuxerは束の先頭から全体を1 segmentとして読む。
            lines.append("#EXT-X-BYTERANGE:%d@%d" % (byterange[1], byterange[0]))
        # Bare names resolve relative to the playlist's own directory, so a playlist
        # written anywhere else has to spell the segments out in full.
        lines.append(str(seg.resolve()) if absolute else seg.name)
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


def write_curated_playlist(hls_dir, dst, unique_id: str = "") -> Optional[Path]:
    """その録画の採用集合だけを指す終端済みVOD playlistを ``dst`` へ書き、pathを返す。
    採用できるsegmentが無ければNone。

    **HLSをffmpegの入力にする処理は、captureのindex.m3u8ではなく必ずこれを使う。** 生の
    indexには源のtimestampが壊れたsegmentが残っており、実測でEXTINFが 28287秒(7.8時間)の
    ものがあった。そのまま食わせると、2.9時間の録画が10.7時間として読まれる。終端tagが
    無い(停止時のffmpegは強制終了される)ためlive扱いで待ち続ける問題も同時に避けられる。

    ``dst`` は session dir の外でもよい(一時dirへ書いて捨てる使い方を想定している)。その場合は
    segmentをfull pathで書く: playlistの参照は素のfile名だと**playlist自身のdirectory**から
    解決されるので、別の場所へ置くと参照が全て外れる。外れてもffmpegはstreamが無いだけの
    正常終了に見えることがあり、静かに空の結果を返す。"""
    hls_dir = Path(hls_dir)
    recorder = Recorder(unique_id or hls_dir.name,
                        str(layout.record_root_of(hls_dir.parent)), None)
    recorder.hls_dir = hls_dir
    recorder.playlist = hls_dir / "index.m3u8"
    recorder.base = hls_dir.name
    kept = recorder._playlist_segments()
    if not kept:
        return None
    dst = Path(dst)
    dst.write_text(render_vod_playlist(kept, absolute=dst.parent.resolve() != hls_dir.resolve()),
                   encoding="utf-8")
    return dst


def curated_span_seconds(hls_dir, unique_id: str = "") -> Optional[float]:
    """その録画の採用集合が名乗る尺(秒)。採用できるsegmentが無ければNone。

    ``write_curated_playlist`` が書くのと**同じ集合**を測る。下流(文字起こし・切り出し・焼き込み)
    がffmpegへ渡すのはその集合なので、「素材が何秒あるか」を問う側もここを見なければ、
    読む対象と測る対象が別物になる。

    ``recordings.duration_seconds`` も finalize が書いた ``timing.json`` も使えない。
    どちらも確定した瞬間のsnapshotで、その後にdirが太れば置き去りになる(実測: 録画行
    12.0秒に対し採用集合 16,861.8秒)。"""
    hls_dir = Path(hls_dir)
    recorder = Recorder(unique_id or hls_dir.name,
                        str(layout.record_root_of(hls_dir.parent)), None)
    recorder.hls_dir = hls_dir
    recorder.playlist = hls_dir / "index.m3u8"
    recorder.base = hls_dir.name
    kept = recorder._playlist_segments()
    if not kept:
        return None
    total = sum(entry[1] for entry in kept)
    return total if total > 0 else None


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
            "%s の正規化の完了印を書けません（差し替えが失敗すると再encodeを"
            "回収できなくなります）", tmp.name,
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
            "%s の解像度を揃える再encodeを開始します", src.name,
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
                "%s の解像度を揃える再encodeを起動できません", src.name,
                extra={"event": "process.ffmpeg_launch_failed",
                       "ctx": {"stage": "normalize", "stem": src.stem, **ffmpeg_ctx(args)}},
                exc_info=True,
            )
            return False
        if proc.returncode == 0 and dst.exists() and dst.stat().st_size > 0:
            return True
        logger.warning(
            "%s の解像度を揃える再encodeが %s で終了しました", src.name, proc.returncode,
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
                "%s の尺を測れないため再encodeの完全性を検証できません", src.name,
                extra={"event": "recording.reencode_unverified",
                       "ctx": {"stem": src.stem, "timing_mode": timing_mode,
                               "path": str(dst)}},
            )
            return True
        out_seconds = await _probe_duration_seconds(dst)
        if out_seconds and out_seconds >= src_seconds * REENCODE_MIN_COVERAGE:
            return True
        logger.error(
            "%s の再encodeが途中で止まりました: %.0fs / %.0fs（timing %s）",
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
            "%s を単一解像度へ再encodeしました（timing passthrough）", src.name,
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
        "%s のpassthrough再encodeが完全な出力になりませんでした。CFRで再試行します",
        src.name,
        extra={"event": "recording.reencode_retried",
               "ctx": {"stem": src.stem, "timing_mode": "cfr", "path": str(log_path)}},
    )
    if await _run(["-fps_mode", "cfr", "-r", "30"]) and await _covers_source("cfr"):
        log_path.unlink(missing_ok=True)
        _write_normalize_marker(dst, "cfr", target_w, target_h)
        logger.info(
            "%s を単一解像度へ再encodeしました（timing CFR）", src.name,
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
        "%s はpassthroughとCFRのどちらの再encodeも失敗しました", src.name,
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
                        "再encodeの進捗callbackが %d%% で失敗しました", pct,
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
    args = ffprobe.keyframe_resolution_args(mp4_path, input_args)
    best: set = set()
    for attempt in range(3):
        try:
            result = await ffprobe.run(args)
        except OSError as exc:
            logger.error(
                "%s のkeyframe解像度のprobeを起動できません", mp4_path.name,
                extra={"event": "process.ffprobe_launch_failed",
                       "ctx": {"stage": "resolutions", "stem": mp4_path.stem,
                               **ffmpeg_ctx(args), **_oserror_ctx(exc)}},
                exc_info=True,
            )
            return best
        seen = set(ffprobe.parse_resolution_csv(result.stdout))
        if len(seen) > len(best):
            best = seen
        # A clean full scan (exit 0) is authoritative; only retry when ffprobe aborted,
        # since that can truncate the list and hide a resolution.
        if result.ok:
            return seen
        logger.warning(
            "%s のkeyframe解像度のprobeが中断しました（%d 回目）。再試行します",
            mp4_path.name, attempt + 1,
            extra={"event": "process.ffprobe_retried",
                   "ctx": {"stage": "resolutions", "stem": mp4_path.stem,
                           "attempt": attempt + 1, "partial_resolutions": len(seen),
                           **ffmpeg_ctx(args, result.returncode,
                                        stderr_text=result.stderr)}},
        )
        # timeoutは再試行しない。返らない入力は3回やっても返らず、待ちだけが3倍になる。
        if result.timed_out:
            return best
        await asyncio.sleep(1)
    logger.error(
        "%s のkeyframe解像度のprobeが一度も正常終了しませんでした。混在解像度の"
        "検出は不完全な可能性があります", mp4_path.name,
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
            "正規化の残り %s は単一解像度のmp4ではありません（%d 種類）。両方のfileを"
            "そのまま残します", tmp.name, len(distinct),
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
            "%s の正規化した出力は待機中です: %s がlockされています。playerで開いていれば"
            "閉じると次の試行で差し替わります", mp4_path.name, mp4_path.name,
            extra={"event": "recording.normalize_reclaim_deferred",
                   "ctx": {"path": str(tmp), "stem": mp4_path.stem,
                           "size_bytes": tmp.stat().st_size if tmp.is_file() else 0}},
        )
        return "locked"
    logger.info(
        "%s の正規化済みmp4を差し替えました（%dx%d, timing %s）", mp4_path.stem,
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
                    "%s の正規化済みmp4を差し替えられません", stem,
                    extra={"event": "recording.normalize_reclaim_failed",
                           "ctx": {"stem": stem, "path": str(mp4_path)}},
                )
    if reclaimed:
        logger.info(
            "起動時のsweepでlockのため取り残されていた正規化済み録画 %d 件を"
            "差し替えました", reclaimed,
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
    from tictok.media.loudness import gain_artifact_paths
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
        *gain_artifact_paths(src),
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
                "録画の付随file %s を現在のlayoutへ移せません", entry.name,
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
            "録画の付随file %d 件を現在のlayoutへ移しました", moved,
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
            "配信の画質段: %s | 選択=%s", _rung_summary(data), chosen,
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

    # ``session_id`` はNoneを取る。recordings.session_idが ``ON DELETE SET NULL`` で、
    # session削除後の録画は実測374本中136本がNULLだからである。保守経路(再mp4化・
    # 再生playlistの描き直し)はその行からRecorderを組むので、intに狭めると実態と食い違う。
    # なおNoneのままfile名を作ることはできない(session_prefixがintを要求する)。それらの
    # 経路はbaseを自分で入れ直すので通らない — 通ってしまったら落ちるのが正しい。
    # 確定中だけ持つ採用segmentの写し(_playlist_segments参照)。classの既定をNoneにして
    # あるのは、試験が ``__new__`` で組む最小のRecorder(hls_dirとplaylistだけを持つ)からも
    # _playlist_segments を呼べるようにするため。
    _finalize_kept: Optional[list] = None

    def __init__(self, unique_id: str, record_dir: str, session_id: Optional[int],
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
        # Working dir (record_dir, SSD) holds the HLS segments and the mp4 for the whole
        # life of the recording. Moving a completed recording to final_dir (HDD) is a
        # manual action (the capacity screen / POST /api/storage/relocate) — finalize
        # never moves anything. final_dir is still recorded here because the free space of
        # the destination volume is part of this recording's disk report.
        self._final_dir = Path(final_dir) if final_dir else self._record_dir
        # Session number that owns this recording; prefixed (zero-padded) onto the
        # output filename so recordings group by session on disk.
        self.session_id = session_id
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
        # 確定中だけ持つ採用segmentの写し(_playlist_segments参照)。確定の外ではNone。
        self._finalize_kept: Optional[list] = None
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
        """録画実体のbyte数。束ね(hls_pack)後は pack*.ts になるので、seg*.ts だけを見ると
        束ねた録画が0byteに見える。layout.media_files が唯一の判定に揃えてある。"""
        if self.hls_dir is None or not self.hls_dir.exists():
            return 0
        total = 0
        for f in layout.media_files(self.hls_dir):
            try:
                total += f.stat().st_size
            except OSError:
                continue
        return total

    def progress_token(self) -> tuple[int, int]:
        """Cheap monotonic capture-progress signal for stall detection: (segment
        count, newest segment size). It advances whenever ffmpeg writes video —
        either a new seg*.ts appears or the open segment grows — and freezes
        entirely when the source silently stalls (the CDN stops serving new
        segments) even though ffmpeg stays alive retrying the now-dead URL.
        Segment names are zero-padded, so the lexical max is the highest index
        (newest).

        costはdirectoryの列挙1回 + 最新1本への ``stat`` 1回。**O(1)ではない** — 以前ここは
        「最新の1本しかstatしないのでpollingはO(1)」と書いていたが、それはstatの回数の話
        でしかなく、列挙は録画が伸びるほど重くなる(実測5,400 segment: ``Path.glob`` 版
        10.2ms / 現行のscandir版 7.5ms)。この監査でその一文が「ここは軽い」という誤った
        判断を招いたので、正確に書き直してある。

        **sizeを ``os.scandir`` の ``DirEntry.stat()`` から取ってはいけない。** Windowsでは
        開いたままのfileのsizeがdirectory entryの古い値のまま返る(実測: 4,096 byte書き込み
        済み・flush済みのfileを0 byteと報告した)。それはffmpegがいま書いているsegment
        そのものの状態なので、使うと「開いているsegmentが伸びている」ことを検出できず、
        録画中に誤ってstallと判定して不要な再接続を起こす。列挙は名前だけを見て、sizeは
        最新1本を ``stat`` で取り直すこと。"""
        if self.hls_dir is None or not self.hls_dir.exists():
            return (0, 0)
        count = 0
        newest = ""
        try:
            with os.scandir(self.hls_dir) as entries:
                for entry in entries:
                    if not _SEGMENT_NAME_MATCH(os.path.normcase(entry.name)):
                        continue
                    count += 1
                    if entry.name > newest:
                        newest = entry.name
        except PermissionError:
            return (0, 0)
        if not count:
            return (0, 0)
        try:
            return (count, (self.hls_dir / newest).stat().st_size)
        except OSError:
            return (count, 0)

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
                "%s の録画を開始できません: ffmpegがinstallされていません", self.unique_id,
                extra={"event": "recording.start_failed",
                       "ctx": {"reason": "ffmpeg_missing"}},
            )
            raise RuntimeError("ffmpegが見つかりません。録画にはffmpegのinstallが必要です。")
        # Preflight the disk before anything is written. Measuring only after a failure
        # is useless here: the failure paths remove the HLS tree or a partial encode and
        # free the very space whose exhaustion caused the failure.
        self._disk_report = await asyncio.to_thread(
            log_disk_preflight,
            "recording.disk_checked", self._volume_paths(), stage="launch",
        )
        url, quality = extract_stream_url(room_info)
        if not url:
            logger.error(
                "%s の録画を開始できません: room infoにstream URLがありません", self.unique_id,
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
                    "final_dir": str(self._final_dir)},
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
                            "%s の録画processが自ら %s で終了しました",
                            self.unique_id, proc.returncode,
                            extra={"event": "recording.capture_ended",
                                   "ctx": {"attempt": attempt, "segments": self._segment_count(),
                                           **ffmpeg_ctx(self._capture_args, proc.returncode, log_path)}},
                        )
                    break
                await self._terminate(proc)
                if self._stop_requested or attempt >= MAX_LAUNCH_ATTEMPTS:
                    if not self._has_segments():
                        probe = {} if self._stop_requested else await self._probe_source(url)
                        logger.error(
                            "%s の録画が %d 回の試行でも安定しませんでした",
                            self.unique_id, attempt,
                            extra={"event": "recording.launch_failed",
                                   "ctx": {"attempts": attempt, "max_attempts": MAX_LAUNCH_ATTEMPTS,
                                           "healthy_wait_seconds": HEALTHY_WAIT_SECONDS,
                                           "min_segments": MIN_SEGMENTS,
                                           "segments": self._segment_count(),
                                           "stop_requested": self._stop_requested,
                                           **probe,
                                           **ffmpeg_ctx(self._capture_args, proc.returncode, log_path)}},
                        )
                        raise RuntimeError(
                            f"録画を開始できませんでした（{attempt}回試行、stream接続不良）。"
                        )
                    break
                logger.warning(
                    "%d 回目の録画が安定しないため再試行します（%s）", attempt, self.unique_id,
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
                "%s の録画が失敗しました", self.unique_id,
                extra={"event": "recording.capture_failed",
                       "ctx": {"attempts": attempt, "segments": self._segment_count(),
                               "error": str(exc)}},
            )
            self.error = str(exc)
            self.state = STATE_FAILED
        finally:
            self._proc = None
            # 捕捉が終わったdirの目印は必ず消す。残すと次の起動が、既に別の用途へ回された
            # かもしれないpidを探しに行くことになる。
            if self.hls_dir is not None:
                orphan_capture.clear(self.hls_dir)
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
            "%s の録画processを起動します", self.unique_id,
            extra={"event": "process.ffmpeg_started",
                   "ctx": {"stage": "capture", "attempt": self._launch_attempts,
                           "stderr_path": str(log_path), **ffmpeg_ctx(args)}},
        )
        log_file = open(log_path, "ab")
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=log_file,
            )
            # 捕捉processの身元をdirへ残す。serverが後始末を通らずに死ぬと(hard kill・
            # コンソールのCLOSE・native crash)、Windowsは子を道連れにしないためこのffmpegが
            # 生き残り、主の居ないdirへ書き続ける。次の起動がこの目印で回収する。
            orphan_capture.mark(self.hls_dir, proc.pid)
            return proc
        except Exception:
            logger.error(
                "%s の録画processを起動できません", self.unique_id,
                extra={"event": "process.ffmpeg_launch_failed",
                       "ctx": {"stage": "capture", "attempt": self._launch_attempts,
                               **ffmpeg_ctx(args)}},
                exc_info=True,
            )
            raise
        finally:
            log_file.close()

    async def _probe_source(self, url: str) -> dict:
        """1 segmentも書けずに終わったとき、源が今何を返しているのかを一度だけ測る。

        捕捉は -loglevel warning で走らせるため、この型の失敗(接続は張れているのにpacketが
        来ない)ではstderrが空のまま終わり、後から原因を絞れない。同じ入力を短時間 ``-f null``
        へ流してinfo段を吐かせ、失敗logへ畳み込む。frameが0なら源が出していない、frameが
        立つのにsegmentが無いならこちら側(muxer/keyframe待ち)、と読み分けられる。

        測定は配信者ごとに間引く。復旧loopは失敗を約1分ごとに繰り返すので、毎回測るとその
        ぶん復帰が遅れ、同じ内容がlogへ積み上がる。"""
        seconds = config.get_record_source_probe_seconds()
        if seconds <= 0 or self.hls_dir is None:
            return {}
        interval = config.get_record_source_probe_interval_seconds()
        now = time.time()
        last = _source_probe_at.get(self.unique_id)
        if last is not None and now - last < interval:
            return {"probe_skipped": "throttled",
                    "probe_last_seconds_ago": round(now - last, 1)}
        _source_probe_at[self.unique_id] = now
        args = [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "info", "-nostats",
            # 源が黙り込んだ場合にffmpeg自身で切り上げさせる。これが無いと、取得できない
            # ことの確認に外側のtimeoutぶんだけ復帰を待たせる。
            "-rw_timeout", str(int(seconds * 1_000_000)),
            "-analyzeduration", "10M", "-probesize", "10M",
            "-i", url,
            "-map", "0:v:0?", "-map", "0:a:0?", "-c", "copy",
            "-t", f"{seconds:g}", "-f", "null", "-",
        ]
        log_path = self.hls_dir / "probe.ffmpeg.log"
        started = time.time()
        timed_out = False
        try:
            with open(log_path, "wb") as log_file:
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=log_file,
                )
        except OSError as exc:
            return {"probe_error": str(exc)}
        try:
            await asyncio.wait_for(proc.wait(), timeout=seconds * 3 + 10)
        except asyncio.TimeoutError:
            timed_out = True
            await self._terminate(proc)
        tail = tail_text(log_path, config.get_log_source_probe_chars())
        log_path.unlink(missing_ok=True)
        return {"probe_cmd": " ".join(args),
                "probe_exit_code": proc.returncode,
                "probe_elapsed_seconds": round(time.time() - started, 1),
                "probe_timed_out": timed_out,
                "probe_stderr_tail": tail}

    async def _await_healthy(self, proc: asyncio.subprocess.Process) -> bool:
        # segment数の確認はdirのglob。1秒ごとにloop上で行うと、diskが応答しない間は
        # loopごと止まる(確定側と同じ理由でthreadへ)。
        for _ in range(HEALTHY_WAIT_SECONDS):
            await asyncio.sleep(1)
            if proc.returncode is not None:
                return await asyncio.to_thread(self._has_segments)
            if await asyncio.to_thread(self._has_segments):
                return True
        return await asyncio.to_thread(self._has_segments)

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
                    "%s の録画通知callbackが失敗しました", self.unique_id,
                    extra={"event": "recording.notify_failed", "ctx": {"state": self.state}},
                )

    async def finalize_recovered_hls(self, base: str, progress=None, mp4_root=None,
                                     build_mp4: bool = False) -> None:
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
        # ``build_mp4`` は「mp4化」operation専用。復旧(crash後の確定)は通常のfinalizeと
        # 同じ結果にしなければならないので既定はFalseで、mp4は作らない。
        await self._finalize(progress=progress, build_mp4=build_mp4)

    def _hls_log_path(self) -> Optional[Path]:
        if self.hls_dir is None:
            return None
        path = self.hls_dir / "ffmpeg.log"
        return path if path.is_file() else None

    async def _finalize_from_segments(self, mp4_path: Path, segments: int,
                                      build_mp4: bool, progress) -> None:
        """素材が揃った録画の確定処理。時刻map・見どころ・尺・検証。

        ``build_mp4`` は「mp4化」operationから来た時だけTrueで、その場合だけ書き出した
        mp4を単一解像度へ揃える。原本の .ts は常に無傷で、確定の主語はそちらである。

        最終保存先への移送はここでは行わない。確定した録画は一時保存先に残り、動画容量画面の
        「最終保存先へ移動」(POST /api/storage/relocate)でだけ動く。"""
        if progress is not None:
            await progress.set("timing", 0.0)
        await self._write_timing_map(mp4_path)
        if progress is not None:
            await progress.done("timing")
        if build_mp4:
            # 外へ出すfileだけ単一解像度へ揃える。混在のままだとplayerが切替のたびに
            # 固まる/急拡大する。原本の .ts は触らない。
            await self._normalize_mixed_resolution(mp4_path, progress=progress)
        # 配信中に押された見どころをmedia軸へ載せ直す。
        await self._remap_live_bookmarks(mp4_path)
        # 尺はEXTINF累計。焼き込みが開くplaylistの尺と定義上同一になる。
        self.duration_seconds = self._measure_media_seconds()
        if not ffprobe_available():
            logger.warning(
                "ffprobeが使えないため %s の素材を検証していません", self.unique_id,
                extra={"event": "recording.validation_skipped",
                       "ctx": {"reason": "no_ffprobe", "stem": self.base,
                               "path": str(self.hls_dir)}},
            )
            if self.state != STATE_FAILED:
                self.state = STATE_COMPLETED
            return
        if await self._validate_source():
            if self.state != STATE_FAILED:
                self.state = STATE_COMPLETED
            return
        if self.state != STATE_FAILED:
            self.state = STATE_FAILED
            self.error = self.error or "録画素材に再生できる映像がありません。"
        self._ops(
            "recording.validation_failed",
            f"録画素材に再生できる映像がありません（@{self.unique_id}）。segmentは残します",
            severity="error",
            detail={"stem": self.base, "path": str(self.hls_dir),
                    "size_bytes": self._live_bytes(),
                    "segments": segments, "volumes": self._disk_report},
        )

    async def _finalize(self, progress=None, build_mp4: bool = False) -> None:
        # 確定の間じゅうこの録画を「触るな」と名乗っておく(``finalizing_scope`` 参照)。
        # 掴む範囲は移送だけでなく確定全体にする: timing mapも検証も同じsegmentを読む。
        with finalizing_scope(self.recording_id):
            await self._finalize_body(progress=progress, build_mp4=build_mp4)

    async def _finalize_body(self, progress=None, build_mp4: bool = False) -> None:
        self.ended_at = time.time()
        started_ms = time.monotonic()
        # Sample free space now, while every artifact of this recording is still on
        # disk. The failure branches below remove the HLS tree, so a sample taken from
        # an except block would show a volume that the cleanup has just freed.
        # diskを触る下ごしらえ(空き容量・segment数・採用segmentの走査)は全部threadで済ませ、
        # 以降の確定はその写しを使う。loop上で行うと、diskが応答しない間(Windows Updateの
        # 復元ポイント作成で実測17〜19秒)loopごと止まってlive接続が切れ、再接続 -> 別fileで
        # 録画再開 -> その確定でまた止まる、という連鎖になっていた(2026-09-03の監査)。
        self._disk_report = await asyncio.to_thread(disk_free_by_volume, self._volume_paths())
        segments = await asyncio.to_thread(self._segment_count)
        duration_seconds = (
            round(self.ended_at - self.started_at, 3) if self.started_at else None
        )
        # Capture has ended; concat/validation is post-processing that no longer
        # blocks a new recording (is_active excludes STATE_FINALIZING).
        if self.state != STATE_FAILED:
            self.state = STATE_FINALIZING
        await self._notify()
        if segments >= MIN_SEGMENTS:
            self._finalize_kept = await asyncio.to_thread(self._playlist_segments)
            try:
                # 録画の実体は .ts である。以前はここでmp4へ結合していたが、それを要求して
                # いたのは焼き込みだけで、その焼き込みが .ts を直接読むようになった(再生は
                # HLS、文字起こし・切抜き・thumbnail・波形・Up出力はhls_source経由)。結合
                # passは配信全長を1本書き直す最も重いI/Oで、誰も読まないfileのために毎回
                # 払っていた。mp4が要る場合は「mp4化」operationで作る。
                #
                # ``_mp4_path`` はfileではなく**録画の身元**として残す。sidecar(timing map・
                # 焼き込み出力・thumbnail)の在処も、hls_sourceが .ts を引く鍵も、この名前から
                # 決まる。実在しないpathを指すのは意図的である。
                mp4_path = self._mp4_path
                self.output_path = mp4_path
                # 「mp4化」operationからだけ結合を走らせる。ここで作ったmp4は、以降この録画の
                # 入力ではなく**書き出し**として扱われる(焼き込みも下流も原本の .ts を読む)。
                if build_mp4 and not await self._concat_to_mp4(mp4_path, progress=progress):
                    if self.state != STATE_FAILED:
                        self.state = STATE_FAILED
                        self.error = self.error or "mp4への変換に失敗しました（素材は残っています）。"
                    self._ops(
                        "recording.concat_failed",
                        f"mp4を組み立てられませんでした（@{self.unique_id}）。segmentは残します",
                        severity="error",
                        detail={"stem": self.base, "segments": segments,
                                "path": str(self.hls_dir), "volumes": self._disk_report},
                    )
                else:
                    await self._finalize_from_segments(mp4_path, segments, build_mp4, progress)
            finally:
                self._finalize_kept = None
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
            await asyncio.to_thread(shutil.rmtree, self.hls_dir, ignore_errors=True)
        if self._on_finalize is not None:
            try:
                await self._on_finalize(self)
            except Exception:
                logger.exception(
                    "%s の録画の確定callbackが失敗しました", self.unique_id,
                    extra={"event": "recording.finalize_callback_failed",
                           "ctx": {"state": self.state, "stem": self.base}},
                )
        size_bytes = await asyncio.to_thread(self._output_size_bytes)
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

    def _output_size_bytes(self) -> int:
        if self.output_path is None or not self.output_path.is_file():
            return 0
        return self.output_path.stat().st_size

    @staticmethod
    def _write_sidecar_text(out: Path, text: str) -> None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")

    @staticmethod
    def _move_session_dir(src: Path, dst: Path) -> int:
        """Move the recording's HLS session dir so it follows its mp4 across roots.
        Returns the bytes moved (0 when there was nothing to move). Runs in a thread.

        The segments are the recording itself, not an intermediate, so this does not hand
        them to ``shutil.move`` and trust it: it copies, checks that every file arrived at
        its full size, and only then removes the source. A cross-volume move is
        copy+unlink internally, and an interruption partway through would otherwise delete
        segments that never landed.

        Moved before the mp4 (see ``_move_recording_files``): this is the large, slow half
        and therefore the half that actually fails on a full disk or an I/O error. Failing
        here leaves the whole recording untouched in the working root; failing after the
        mp4 had already moved would strand the pair across two volumes instead.

        Each file is fsync'd before it counts as arrived. Checking sizes straight after a
        plain copy only proves the write reached the OS cache, and the destination here is
        an external drive: one that drops off the bus mid-copy reports "delayed write
        failed" long after the call returned, and a size check served from cache would
        have already licensed deleting the source."""
        stem = src.stem
        src_dir = layout.session_dir(layout.record_root_of(src), stem)
        dst_dir = layout.session_dir(layout.record_root_of(dst), stem)
        if src_dir == dst_dir or not src_dir.is_dir():
            return 0
        expected = {p.name: p.stat().st_size for p in src_dir.iterdir() if p.is_file()}
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
            for name in expected:
                _copy_durable(src_dir / name, dst_dir / name)
            arrived = {p.name: p.stat().st_size for p in dst_dir.iterdir() if p.is_file()}
        except OSError:
            shutil.rmtree(dst_dir, ignore_errors=True)
            raise
        missing = [name for name, size in expected.items() if arrived.get(name) != size]
        if missing:
            shutil.rmtree(dst_dir, ignore_errors=True)
            raise OSError(
                "%d of %d segment file(s) did not arrive intact at %s (e.g. %s)"
                % (len(missing), len(expected), dst_dir, ", ".join(missing[:3]))
            )
        shutil.rmtree(src_dir, ignore_errors=True)
        return sum(expected.values())

    @staticmethod
    def _move_recording_files(src: Path, dst: Path) -> int:
        """Move the mp4, the HLS segments it was built from, and every artifact derived
        from it. Runs in a thread. Returns the number of derived files moved. A failed
        segment or mp4 move raises (caller keeps the working copy); a failed derived move
        is logged but not fatal.

        録画の実体である.tsは、mp4と必ず同じrootに置く。別rootへ分かれると、artifactを
        mp4基準(``record_root_of``)で解く側と、素材を.ts基準で解く側が違うvolumeを指し、
        再mp4化のたびに録画が root 間を往復する。

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
        Recorder._move_session_dir(src, dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        # mp4は「作られていれば移す」に変わった。finalizeはもう作らないので、多くの録画で
        # ここは存在しない。無い物をmoveしようとすると移送全体が失敗し、素材だけ移った
        # 中途半端な状態(実測: K:に残骸が残る)になるので、在るときだけ動かす。
        if src.is_file():
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
                    "mp4は移送しましたが派生file %s を移せませんでした（%s）",
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
                "%s には結合できるHLS segmentがありません", self.unique_id,
                extra={"event": "recording.concat_aborted",
                       "ctx": {"stem": self.base, "path": str(self.hls_dir),
                               "reason": "no_segments"}},
            )
            return False
        list_path = self.hls_dir / VOD_PLAYLIST_NAME
        if not self._write_vod_playlist(kept, list_path):
            return False
        segments = [seg for seg, _, _, _, _ in kept]
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
            total_us = int(sum(extinf for _, extinf, _, _, _ in kept) * 1_000_000)
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
                    "segment %d 件を結合してmp4にしました（%s）",
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
                "%s のmp4への結合が失敗しました（exit %s, 書き込み %d bytes）",
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
                "%s のmp4への結合を実行できません", self.unique_id,
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
            # The VOD playlist stays alongside the segments: it is the authority for the
            # segment order and #EXTINF durations that define the recording's media axis,
            # so it outlives the mux that produced it.

    def _segment_facts(self) -> Optional[list]:
        """この録画を構成するsegment 1本ごとの事実を、順序どおりに返す。

        ``[{"name","extinf","disc","wall","size","path","byterange"}, ...]``。読めなければ
        None。``byterange`` は束ね済み録画でのみ ``(offset, length)`` を持つ。

        素材の置かれ方は2通りある。**未結合**なら1 segment = 1 fileで、wallはそのfileの
        mtime、sizeはそのfileのsize。**束ね済み**(tictok.record.hls_pack)なら複数segmentが
        1 fileへ連結されていてfile自体がもう無いので、束ねる直前に ``segments.json`` へ
        固定した値を読む。どちらもここで同じ形に均し、以降の判定(重複・空・巻き戻し・PTS
        不連続)は素材の置かれ方を知らずに済む。

        wallを取り違えるとtiming mapのanchorがずれ、焼き込みのコメントが録画全体で
        ずれる。束ねる側とここが同じ表を見ていることが、その一致の根拠になる。"""
        if self.hls_dir is None:
            return None
        snapshot = hls_pack.read_snapshot(self.hls_dir)
        if snapshot is not None:
            return [{
                "name": s["name"], "extinf": s["extinf"], "disc": bool(s["disc"]),
                "wall": s["wall"], "size": s["size"],
                "path": self.hls_dir / s["pack"],
                "byterange": (s["offset"], s["length"]),
            } for s in snapshot["segments"]]
        if hls_pack.is_packed(self.hls_dir):
            # 束ねた後は元のsegment fileが無いので、下のplaylist経路へ流すと全entryが
            # 「fileが無い」と判定され、素材ごと失われた録画に見える。読めないことを
            # 読めないまま返す。
            logger.error(
                "%s はts結合済みですが %s が無い、または読めません。未結合のsegmentとしては"
                "読み取りません", self.unique_id, hls_pack.SNAPSHOT_NAME,
                extra={"event": "recording.pack_snapshot_unreadable",
                       "ctx": {"stem": self.base, "path": str(self.hls_dir),
                               "snapshot": str(hls_pack.snapshot_path(self.hls_dir))}},
            )
            return None
        if self.playlist is None or not self.playlist.is_file():
            return None
        try:
            text = self.playlist.read_text(encoding="utf-8", errors="replace")
        except OSError:
            logger.warning(
                "%s のHLS再生listを読み取れません", self.unique_id,
                extra={"event": "recording.playlist_read_failed",
                       "ctx": {"stem": self.base, "path": str(self.playlist)}},
                exc_info=True,
            )
            return None
        facts = []
        for entry in hls_pack.parse_playlist(text):
            seg = self.hls_dir / entry["name"]
            try:
                st = seg.stat()
            except OSError:
                st = None
            facts.append({
                "name": entry["name"], "extinf": entry["extinf"], "disc": entry["disc"],
                "wall": st.st_mtime if st else None,
                "size": st.st_size if st else 0,
                "path": seg, "byterange": None,
            })
        return facts

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
        about which segments the finalized mp4 contains.

        確定の間は ``_finalize_body`` がthreadで1度だけ走査した結果(``_finalize_kept``)を
        返す。timing map・尺・検証・結合の4箇所がそれぞれ呼ぶが、ffmpegは既に終わっていて
        segmentは増えないので答えは同じであり、segmentごとのstat(未packで最大2,800本)を
        loop上で4回繰り返す理由が無い(2026-09-03の監査でstall stack 26件中5件がここ)。"""
        if self._finalize_kept is not None:
            return self._finalize_kept
        if self.hls_dir is None:
            return []
        facts = self._segment_facts()
        if facts is None:
            return []
        kept: list = []
        dropped: list = []
        unusable = 0
        duplicates: list = []
        empties: list = []
        rewinds = 0
        seen: set = set()
        prev_wall: Optional[float] = None
        carry = False    # the preceding entry was dropped, so the next one jumps
        for fact in facts:
                line = fact["name"]
                extinf, seg = fact["extinf"], fact["path"]
                marked = fact["disc"]
                if extinf is None or fact["wall"] is None:
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
                if fact["size"] == 0:
                    # Its #EXTINF still counts: the segment's timestamps are preserved
                    # by the mux, so the media time really did elapse and the result is
                    # an honest freeze rather than a shift. Worth surfacing all the same
                    # -- an empty segment means a write that did not land.
                    empties.append(line)
                wall = fact["wall"]
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
                kept.append((seg, extinf, wall, marked or carry, fact["byterange"]))
                carry = False
        if dropped:
            logger.warning(
                "%s: 幻の穴を避けるためPTS不連続なsegment %d 件を除外します: %s",
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
                "%s: 再生listの %d 件に使えるsegment fileまたは#EXTINFがありません",
                self.unique_id, unusable,
                extra={"event": "recording.playlist_entries_unusable",
                       "ctx": {"stem": self.base, "unusable": unusable,
                               "segments": len(kept) + len(dropped) + unusable}},
            )
        if duplicates:
            logger.warning(
                "%s: 再生listに %d 件のsegment名が重複していたため、最初の1件だけを"
                "残しました: %s", self.unique_id, len(duplicates),
                ", ".join(duplicates[:10]),
                extra={"event": "recording.playlist_entries_duplicated",
                       "ctx": {"stem": self.base, "duplicates": len(duplicates),
                               "duplicate_segments": duplicates[:50],
                               "segments": len(kept) + len(dropped) + unusable}},
            )
        if empties:
            logger.warning(
                "%s: segment file %d 件が空です。その部分の映像は失われ再生は静止します: %s",
                self.unique_id, len(empties), ", ".join(empties[:10]),
                extra={"event": "recording.segments_empty",
                       "ctx": {"stem": self.base, "empty": len(empties),
                               "empty_segments": empties[:50],
                               "segments": len(kept) + len(dropped) + unusable}},
            )
        if rewinds:
            logger.warning(
                "%s: segment境界 %d 箇所で壁時計が進みませんでした。順序を保つためanchorを"
                "ずらしたので、その付近のcommentの同期は概算です", self.unique_id, rewinds,
                extra={"event": "recording.wall_clock_rewound",
                       "ctx": {"stem": self.base, "rewinds": rewinds,
                               "segments": len(kept) + len(dropped) + unusable}},
            )
        return kept

    def _write_vod_playlist(self, kept: list, path: Path) -> bool:
        """Write the terminated VOD playlist the HLS demuxer reads at finalize."""
        try:
            path.write_text(render_vod_playlist(kept), encoding="utf-8")
        except OSError as exc:
            logger.error(
                "%s のVOD再生listを書き出せません", self.unique_id,
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
            result = await ffprobe.run(
                ffprobe.duration_args(path),
                timeout=ffprobe.SEGMENT_TIMEOUT_SECONDS)
        except OSError:
            # Called once per HLS segment, so this is guarded rather than emitted: a
            # long recording has thousands of segments and the aggregate outcome is
            # reported by the caller as timing_map_degraded.
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "%s の尺のprobeが完了しませんでした", path.name,
                    extra={"event": "process.ffprobe_failed",
                           "ctx": {"stage": "duration", "path": str(path)}},
                    exc_info=True,
                )
            return None
        seconds = ffprobe.parse_duration(result.stdout)
        if seconds is None:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "%s の尺のprobeが尺を返しませんでした", path.name,
                    extra={"event": "process.ffprobe_failed",
                           "ctx": {"stage": "duration", "path": str(path),
                                   "exit_code": result.returncode}},
                )
        return seconds

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
            "録画 %s は解像度 %d 種類を含みます: %s%s",
            self.unique_id, len(distinct), ", ".join(summary) or "unknown",
            f"（正規化をskip: {skip_reason}）" if skip_reason else "",
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
                    "録画 %s は混在解像度ですが正規化をskipしました（%s）。playerが切替点ごとに"
                    "固まる、または急拡大する可能性があります",
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
            "混在解像度の録画 %s を揃えます: %d 種類（%s）-> %dx%d（mode=%s）",
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
                "%s の解像度を揃える処理が失敗しました", self.unique_id,
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
                "%s の解像度を揃える処理が有効な出力を作れませんでした。混在解像度の"
                "stream copy mp4をそのまま使います", self.unique_id,
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
                "%s の正規化済みmp4を差し替えられません（差し替え先がlockされています）。"
                "再encodeは %s に残し、次の起動時sweepか出力jobで拾い直します",
                self.unique_id, tmp.name,
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
                "録画 %s の解像度を %dx%d へ揃えました（CFRで代替）。timing mapは破棄したため"
                "commentの同期は概算になります", self.unique_id, target_w, target_h,
                extra={"event": "recording.timing_map_dropped",
                       "ctx": {"stem": self.base, "reason": "cfr_reencode",
                               "path": str(timing_path(mp4_path)),
                               "width": target_w, "height": target_h,
                               "duration_ms": int((time.monotonic() - started) * 1000)}},
            )
        else:
            logger.info(
                "録画 %s の解像度を %dx%d へ揃えました",
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
                    "%s にHLS再生listが無いためcommentのtiming mapを作れません",
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
                    "%s の再生listに使えるsegmentが無いためcommentのtiming mapを"
                    "作れません", self.unique_id,
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
            for _, extinf, wall, _, _ in kept:
                media += extinf
                anchors.append((wall, round(media, 6)))
            # Prepend the first-frame zero point: media 0 at the start of seg0.
            anchors.insert(0, (anchors[0][0] - anchors[0][1], 0.0))

            # media_pts は media軸 -> **mp4のPTS軸** の対応で、mp4を入力にする時にしか
            # 意味がない。finalizeがmp4を作らなくなったので、在るときだけ作る(再mp4化で
            # 作られた録画と、mp4しか無い古い録画のため)。無い場合は焼き込み側がHLSの
            # 時刻軸=media軸と判断して恒等で扱う(video_overlay._render_context)。
            media_pts = (await self._build_media_pts(kept, mp4_path)
                         if mp4_path.is_file() else None)
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
                "%s のcommentのtiming mapを組み立てられません", self.unique_id,
                extra={"event": "recording.timing_map_skipped",
                       "ctx": {"stem": self.base, "reason": "build_error",
                               "path": str(self.playlist) if self.playlist else ""}},
                exc_info=True,
            )
            return
        serialized = json.dumps(payload)
        try:
            await asyncio.to_thread(self._write_sidecar_text, out, serialized)
        except OSError as exc:
            # A distinct failure point from the build above: this is a disk write, and
            # its usual cause is a full volume. Sharing one warning with the probe path
            # made the two indistinguishable in the log, and neither carried the free
            # space that would have identified the cause. No automatic retry exists, so
            # the map is permanently lost for this recording -> error.
            logger.error(
                "%s のcommentのtiming mapを書き出せません。この録画のcommentの同期は"
                "概算になります", self.unique_id,
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
            "%s のcommentのtiming mapを書き出しました（anchor %d 件, media %.1fs）",
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
        extinfs = [extinf for _, extinf, _, _, _ in kept]
        media_pts = media_pts_from_segments(extinfs, extinfs, mp4_dur)
        if media_pts is None:
            logger.warning(
                "%s のtiming map: 確定したmp4をprobeできなかったため、media->ptsは"
                "scale modelで代替します", self.unique_id,
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
                "%s の配信中の見どころ %d 件は暫定の壁時計位置のまま残します: "
                "mp4の時刻軸へ載せ替えるtiming mapがありません",
                self.unique_id, len(pending),
                extra={"event": "recording.bookmark_remap_skipped",
                       "ctx": {"stem": self.base, "markers": len(pending),
                               "reason": "no_timing_anchors"}},
            )
            return
        media_pts = _load_media_pts(mp4_path)
        # mp4が在ればその軸へ、無ければ素材のmedia軸へ載せる。存在しないfileへffprobeを
        # 掛けると毎回warningが出るだけで何も得られないので、先にEXTINF累計を使う。
        video_duration = (await self._probe_duration(mp4_path) if mp4_path.is_file()
                          else self._measure_media_seconds())
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
            "配信中の見どころ %d 件を %s のmp4の時刻軸へ載せ直しました"
            "（最大の補正 %.1fs）", applied, self.unique_id, worst,
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
            "%s の尺を測れないため未測定のまま残します", path.name,
            extra={"event": "recording.duration_unmeasured",
                   "ctx": {"stem": self.base, "path": str(path),
                           "ffprobe": ffprobe_available()}},
        )
        return None

    def _measure_media_seconds(self) -> Optional[float]:
        """採用したsegmentのEXTINF累計。これがこの録画のmedia軸の全長である。

        ffprobeを起こさないのは速いからではなく、**これが定義そのもの**だからである。
        焼き込みも同じcurated playlistを開き、HLS demuxerはEXTINFから尺を返す(実測で
        11256.381993s と累計が完全一致)。ここで別の測り方をすると、DBの尺と焼き込みの
        時間軸が食い違う。"""
        kept = self._playlist_segments()
        if not kept:
            return None
        total = sum(extinf for _, extinf, _, _, _ in kept)
        return total if total > 0 else None

    async def _validate_source(self) -> bool:
        """採用集合が復号できる映像を持つか。mp4を作らなくなったので、検証の対象は
        原本の .ts になった。終端済みのVOD playlist越しに見るのは、captureのindexが
        #EXT-X-ENDLIST を持たずliveと見なされて待ち続けるためである。"""
        session = self.hls_dir
        if session is None:
            return False
        probe = session / (".validate-" + uuid.uuid4().hex[:8] + ".m3u8")
        try:
            # write_curated_playlistは別のRecorderを組んで採用集合を走査し直す(確定中の写し
            # _finalize_keptは見ない)ので、そのstatと書き込みはthreadで行う。
            written = await asyncio.to_thread(
                write_curated_playlist, session, probe, self.unique_id)
            if written is None:
                return False
            return await self._validate_mp4(probe, tuple(HLS_INPUT_ARGS))
        finally:
            await asyncio.to_thread(probe.unlink, missing_ok=True)

    async def _validate_mp4(self, path: Path, input_args: tuple = ()) -> bool:
        """Confirm the input has a decodable video stream before treating it as complete."""
        args = [
            "ffprobe", "-v", "error", *input_args, "-select_streams", "v:0",
            "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path),
        ]
        try:
            result = await ffprobe.run(args)
            if result.ok and "video" in result.stdout:
                return True
            logger.warning(
                "%s の検証で映像streamが見つかりませんでした（exit %s）",
                path.name, result.returncode,
                extra={"event": "process.ffprobe_failed",
                       "ctx": {"stage": "validate", "stem": self.base, "path": str(path),
                               **ffmpeg_ctx(args, result.returncode,
                                            stderr_text=result.stderr)}},
            )
            return False
        except Exception:
            logger.exception(
                "%s の検証を実行できません", self.unique_id,
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
                    "%s の録画の確定が遅いため待たずに続行します",
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
            "録画 id=%s の孤立したmp4に復号できる映像streamがありません。DB行はinterrupted"
            "のまま残します", row.get("id"),
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
        "録画 id=%s を確定済みのmp4 %s へ張り直しました（DB行は %s を指していました）",
        row.get("id"), mp4_path, row.get("path"),
        extra={"event": "recording.reattached",
               "ctx": {"stem": base, "path": str(mp4_path), "stale_path": row.get("path"),
                       "size_bytes": stat.st_size}},
    )
    return True


async def recover_interrupted_recordings(storage, record_dir, final_dir=None) -> int:
    """起動時、クラッシュで中断した録画の捕捉済みHLS segmentをmp4へ再finalizeしてDB行を復旧する。
    プロセスが録画中に落ちると_finalizeが走らずDB行はseg*.tsを指さないまま(pathは録画dir、
    filenameは未生成mp4)残り、seg*.tsは孤立して再生不能になる。ここでconcat→mp4化し、成功した
    録画をcompletedとして実mp4パス/サイズで更新する。

    mp4は出来たがDB更新の前に落ちた場合(例: 混在解像度のnormalize中)も同じ壊れ方をする。
    segmentが残っていれば作り直し、残っていなければ出来ているmp4へ行を張り直す。segmentも
    mp4も無いものは既存のinterruptedのまま残す(mark_stale_recordingsの後始末に委ねる)。"""
    if not ffmpeg_available():
        logger.error(
            "ffmpegが使えないため中断した録画を復旧できず、HLS segmentは再生できない"
            "ままになります",
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
    # 待機/実行中のjobが掴んでいる録画には手を出さない。復旧はsegmentを読んでmp4の在処を
    # 決め直し、最後にsession dirごと最終保存先へ移す処理なので、同じ素材を読み書きしている
    # jobの足元を抜くことになる(逆向きは ``finalizing_scope`` が塞ぐが、jobが先に走り出して
    # いた場合はこちらが譲るしかない)。見送った録画はinterruptedのまま残り、次の起動で拾う。
    busy_ids = {rid for _kind, rid in storage.pending_media_job_keys()}
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
        # 素材はwork rootとは限らない。移送済みの録画はfinal rootに在り、work rootだけを
        # 見ると「作り直す材料が無い」と判断して行が永久にinterruptedのまま残る(実測1件:
        # 素材はK:に589 segment在るのに画面から辿れなくなった)。
        # 判定に ``layout.has_media`` を使うのも必須で、``seg*.ts`` だけを数えると
        # 束ね済み(pack*.ts)の録画が全部「素材無し」になる。
        hls_root = next(
            (root for root in (record_dir, final_dir)
             if layout.has_media(layout.session_dir(root, base))),
            None)
        hls_dir = layout.session_dir(hls_root or record_dir, base)
        has_segments = hls_root is not None
        if existing is not None and not has_segments:
            # 作り直す材料(seg*.ts)が無いので、出来ているmp4へ行を張り直す。作り直しでは
            # なく突き合わせなので、再生可能かをffprobeで確かめてからcompletedにする。
            if await _reattach_orphan_mp4(storage, row, base, existing):
                reattached += 1
            continue
        if not has_segments:
            continue  # 再finalizeできるsegmentが残っていない
        if row.get("id") in busy_ids:
            logger.warning(
                "中断した録画 id=%s はmedia jobが掴んでいます。復旧は次回の起動へ"
                "見送ります", row.get("id"),
                extra={"event": "recording.recovery_deferred",
                       "ctx": {"stem": base, "path": str(hls_dir),
                               "recording_id": row.get("id")}},
            )
            continue
        # Counted here, not per DB row: rows that already have an mp4 or have no
        # segments left were not recovery attempts and must not make the summary read
        # as a failure rate.
        candidates += 1
        # 素材が在るrootをrecord dirとして渡す。work root固定で渡すと、final rootの録画に
        # 対して存在しないdirを見に行き、素材ゼロとして確定してしまう。
        recorder = Recorder(row.get("unique_id") or "", str(hls_root), row.get("session_id"),
                            final_dir=str(final_dir), storage=storage)
        recorder.recording_id = row.get("id")
        try:
            await recorder.finalize_recovered_hls(base)
        except Exception:
            logger.exception(
                "中断した録画 id=%s の復旧に失敗しました", row.get("id"),
                extra={"event": "recording.recovery_failed",
                       "ctx": {"stem": base, "path": str(hls_dir),
                               "segments": len(layout.media_files(hls_dir))}},
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
                "中断した録画 id=%s を復旧しました -> %s（%s）",
                row.get("id"), recorder.output_path, recorder.state,
                extra={"event": "recording.recovered",
                       "ctx": {"stem": base, "path": str(recorder.output_path),
                               "state": recorder.state, "size_bytes": snap["bytes"]}},
            )
        else:
            logger.error(
                "中断した録画 id=%s から使えるmp4を作れませんでした。HLS segmentは再生"
                "できないままです", row.get("id"),
                extra={"event": "recording.recovery_failed",
                       "ctx": {"stem": base, "state": recorder.state,
                               "path": str(hls_dir), "size_bytes": snap.get("bytes", 0),
                               "error": recorder.error}},
            )
    if candidates or reattached:
        logger.warning(
            "前回の実行で中断した録画 %d / %d 件を復旧しました"
            "（既存mp4への張り直し %d 件）",
            recovered, candidates, reattached,
            extra={"event": "recording.recovery_completed",
                   "ctx": {"recovered": recovered, "candidates": candidates,
                           "reattached": reattached}},
        )
    return recovered + reattached
