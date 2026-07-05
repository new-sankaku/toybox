import asyncio
import json
import logging
import os
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import Optional

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


def media_pts_from_segments(extinfs: list, durations: list,
                            mp4_duration: Optional[float]) -> Optional[list]:
    """Build the exact media->pts correspondence [[media, pts], ...] from each kept
    segment's #EXTINF (media span) and its real container duration (pts contribution),
    pinned so the last pts equals the finalized ``mp4_duration``. Returns None when
    any segment duration is missing or the inputs are unusable. Shared by the recorder
    (finalize) and the repair script so the axis is built identically."""
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


# Per-recording burn-in/timing artifacts live in this sibling directory of the
# recordings root, so the root itself holds only the .mp4 recordings. The names
# inside mirror the .mp4 stem (e.g. <stem>.timing.json) so each sidecar maps back
# to its recording.
SIDECAR_DIRNAME = ".sidecars"
TIMING_SUFFIX = ".timing.json"
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
    """Directory holding a recording's sidecar artifacts (kept out of the root)."""
    return Path(src).parent / SIDECAR_DIRNAME


def sidecar_path(src, suffix: str) -> Path:
    """Sidecar path for ``src`` with ``suffix`` (e.g. ``.overlay.mp4``)."""
    src = Path(src)
    return sidecar_dir(src) / (src.stem + suffix)


def timing_path(src) -> Path:
    """Sibling wall->media timing map written by the recorder at finalize."""
    return sidecar_path(src, TIMING_SUFFIX)


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
        except OSError:
            logger.warning("failed to migrate sidecar %s", entry, exc_info=True)

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
        logger.info("migrated %d recording artifact(s) to the current layout", moved)
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
        logger.info("stream quality rungs: %s | chosen=%s", _rung_summary(data), chosen)
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

    def __init__(self, unique_id: str, record_dir: str, session_id: int, keep_hls: bool = False) -> None:
        self.unique_id = unique_id
        self._record_dir = Path(record_dir)
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

    @property
    def is_active(self) -> bool:
        return self.state in (STATE_RECORDING, STATE_STOPPING)

    def _live_bytes(self) -> int:
        if self.hls_dir is None or not self.hls_dir.exists():
            return 0
        return sum(f.stat().st_size for f in self.hls_dir.glob("seg*.ts"))

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

    async def start(self, room_info: dict, on_finalize=None, on_notify=None) -> None:
        if self.is_active:
            raise RuntimeError("既に録画中です。")
        if not ffmpeg_available():
            raise RuntimeError("ffmpegが見つかりません。録画にはffmpegのinstallが必要です。")
        url, quality = extract_stream_url(room_info)
        if not url:
            raise RuntimeError("配信のstream URLを取得できませんでした（録画不可）。")
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        self.base = f"{session_prefix(self.session_id)}_{self.unique_id}_{stamp}"
        self.hls_dir = self._record_dir / self.base
        self.hls_dir.mkdir(parents=True, exist_ok=True)
        self.playlist = self.hls_dir / "index.m3u8"
        self.output_path = self._record_dir / f"{self.base}.mp4"
        self.quality = quality
        self.error = None
        self.started_at = time.time()
        self.ended_at = None
        self._stop_requested = False
        self._on_finalize = on_finalize
        self._on_notify = on_notify
        self.state = STATE_RECORDING
        # output_path doesn't exist until finalize; reset so snapshot reports live bytes.
        self.output_path = None
        self._mp4_path = self._record_dir / f"{self.base}.mp4"
        self._task = asyncio.create_task(self._run(url), name=f"tictok-rec-{self.unique_id}")
        logger.info("recording started: %s quality=%s -> %s", self.unique_id, quality, self.hls_dir)

    async def _run(self, url: str) -> None:
        log_path = self.hls_dir / "ffmpeg.log"
        attempt = 0
        try:
            while not self._stop_requested:
                attempt += 1
                proc = await self._launch(url, log_path)
                self._proc = proc
                healthy = await self._await_healthy(proc)
                if healthy:
                    # Playlist/segments now exist; tell the UI it can preview.
                    if proc.returncode is None and not self._stop_requested:
                        await self._notify()
                    await proc.wait()
                    break
                await self._terminate(proc)
                if self._stop_requested or attempt >= MAX_LAUNCH_ATTEMPTS:
                    if not self._has_segments():
                        raise RuntimeError(
                            f"録画を開始できませんでした（{attempt}回試行、stream接続不良）。"
                        )
                    break
                logger.warning("recording attempt %d unhealthy for %s, retrying", attempt, self.unique_id)
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            if self._proc is not None:
                await self._terminate(self._proc)
            raise
        except Exception as exc:
            logger.exception("recording failed for %s", self.unique_id)
            self.error = str(exc)
            self.state = STATE_FAILED
        finally:
            self._proc = None
            await self._finalize()

    async def _launch(self, url: str, log_path: Path) -> asyncio.subprocess.Process:
        log_file = open(log_path, "ab")
        try:
            return await asyncio.create_subprocess_exec(
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
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=log_file,
            )
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
        if self.hls_dir is None or not self.hls_dir.exists():
            return False
        return len(list(self.hls_dir.glob("seg*.ts"))) >= MIN_SEGMENTS

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
                logger.exception("recording notify callback failed for %s", self.unique_id)

    async def _finalize(self) -> None:
        self.ended_at = time.time()
        # Capture has ended; concat/validation is post-processing that no longer
        # blocks a new recording (is_active excludes STATE_FINALIZING).
        if self.state != STATE_FAILED:
            self.state = STATE_FINALIZING
        await self._notify()
        if self._has_segments():
            mp4_path = self._mp4_path
            if await self._concat_to_mp4(mp4_path):
                self.output_path = mp4_path
                # Persist the wall->media->pts timing map while the HLS source
                # still exists, so the burn-in can lock comments to the video
                # timeline.
                await self._write_timing_map(mp4_path)
                # Keep the HLS source until the mp4 is confirmed playable. If
                # ffprobe is unavailable we cannot confirm, so keep HLS too.
                if not ffprobe_available():
                    logger.warning(
                        "ffprobe unavailable; keeping HLS for %s (mp4 unverified)", self.unique_id
                    )
                    if self.state != STATE_FAILED:
                        self.state = STATE_COMPLETED
                elif await self._validate_mp4(mp4_path):
                    if not self._keep_hls:
                        shutil.rmtree(self.hls_dir, ignore_errors=True)
                    else:
                        logger.info("keeping HLS for %s (diagnostic): %s", self.unique_id, self.hls_dir)
                    if self.state != STATE_FAILED:
                        self.state = STATE_COMPLETED
                else:
                    # 検証に失敗したmp4をsnapshotへ晒さない。再生可能な成果物は温存
                    # したHLSなので、concat失敗branchと同様にplaylistを指す。
                    self.output_path = self.playlist
                    if self.state != STATE_FAILED:
                        self.state = STATE_FAILED
                        self.error = self.error or "mp4の検証に失敗しました（HLSを保持しています）。"
            else:
                # Keep HLS dir as the fallback artifact (still playable).
                self.output_path = self.playlist
                if self.state != STATE_FAILED:
                    self.state = STATE_FAILED
                    self.error = self.error or "mp4への変換に失敗しました（HLSは残っています）。"
        else:
            if self.state != STATE_FAILED:
                self.state = STATE_FAILED
                self.error = self.error or "録画Dataが空でした（stream接続不良）。"
            shutil.rmtree(self.hls_dir, ignore_errors=True)
        if self._on_finalize is not None:
            try:
                await self._on_finalize(self)
            except Exception:
                logger.exception("recording finalize callback failed for %s", self.unique_id)
        logger.info("recording finalized: %s state=%s file=%s", self.unique_id, self.state, self.output_path)

    async def _concat_to_mp4(self, dst: Path) -> bool:
        # Concatenate the .ts segments directly via the concat demuxer rather
        # than reading the m3u8: on stop ffmpeg is force-terminated (Windows
        # send_signal maps SIGTERM to TerminateProcess, a hard kill), so the
        # playlist never gets an #EXT-X-ENDLIST tag. The HLS demuxer would then
        # treat it as a live stream — seeking to the live edge (dropping all but
        # the last few segments) and blocking on further reads — yielding a
        # broken, moov-less mp4. The .ts files are the complete ordered source.
        segments = sorted(self.hls_dir.glob("seg*.ts"))
        if not segments:
            return False
        # Exclude PTS-discontinuity segments: a glitched source timestamp inflates
        # one segment's media span (EXTINF) far past the wall time it took to
        # capture, and concatenating it bakes a phantom multi-minute frozen gap
        # into the mp4. Dropping it (~one segment of real content) yields a
        # continuous, real-time timeline that the comment burn-in can track.
        segments = self._drop_discontinuity_segments(segments)
        if not segments:
            return False
        list_path = self.hls_dir / "concat_list.txt"
        try:
            # Bare names resolve relative to the list file's own directory.
            list_path.write_text(
                "".join(f"file '{seg.name}'\n" for seg in segments),
                encoding="utf-8",
            )
        except OSError:
            logger.exception("failed to write concat list for %s", self.unique_id)
            return False
        try:
            # Live TS segments carry arbitrary start PTS/DTS; without genpts +
            # avoid_negative_ts the muxed mp4 gets non-monotonic/negative
            # timestamps that some players refuse to play.
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
                "-fflags", "+genpts",
                "-f", "concat", "-safe", "0", "-i", str(list_path),
                "-c", "copy", "-movflags", "+faststart",
                "-avoid_negative_ts", "make_zero", str(dst),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            return proc.returncode == 0 and dst.exists() and dst.stat().st_size > 0
        except Exception:
            logger.exception("concat to mp4 failed for %s", self.unique_id)
            return False
        finally:
            # Keep the concat list alongside the segments when retaining HLS, so the
            # exact segment order/durations fed to the muxer can be inspected later.
            if not self._keep_hls:
                list_path.unlink(missing_ok=True)

    def _segment_extinf(self) -> dict:
        """{segment_filename: EXTINF_seconds} parsed from the HLS playlist. The
        playlist (kept via append_list) records every segment's media duration;
        only the values are read here (no HLS demux), so the live-playlist caveat
        in _concat_to_mp4 does not apply."""
        out: dict[str, float] = {}
        if self.playlist is None or not self.playlist.is_file():
            return out
        try:
            lines = self.playlist.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return out
        pending: Optional[float] = None
        for line in lines:
            line = line.strip()
            if line.startswith("#EXTINF:"):
                try:
                    pending = float(line[len("#EXTINF:"):].split(",", 1)[0])
                except ValueError:
                    pending = None
            elif line and not line.startswith("#"):
                if pending is not None:
                    out[line] = pending
                pending = None
        return out

    def _drop_discontinuity_segments(self, segments: list) -> list:
        """Return ``segments`` (ascending) with PTS-discontinuity segments removed.
        A segment's real wall duration is its file-mtime delta from the previous
        segment; when its EXTINF dwarfs that, it carries a glitched timestamp that
        would bake a phantom gap into the mp4. Logged, never silently dropped."""
        extinf = self._segment_extinf()
        mtimes: list = []
        for seg in segments:
            try:
                mtimes.append(seg.stat().st_mtime)
            except OSError:
                mtimes.append(None)
        kept: list = []
        dropped: list = []
        for i, seg in enumerate(segments):
            ei = extinf.get(seg.name)
            wall = mtimes[i] - mtimes[i - 1] if i > 0 and mtimes[i] is not None and mtimes[i - 1] is not None else None
            if ei is not None and wall is not None and is_pts_discontinuity(ei, wall):
                dropped.append((seg.name, ei, wall))
                continue
            kept.append(seg)
        if dropped:
            logger.warning(
                "%s: dropping %d PTS-discontinuity segment(s) to avoid a phantom gap: %s",
                self.unique_id, len(dropped),
                ", ".join("%s(EXTINF=%.1fs wall=%.1fs)" % (n, e, w) for n, e, w in dropped),
            )
        return kept

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
            return None
        try:
            return float(out.decode("ascii", "replace").strip())
        except ValueError:
            return None

    async def _probe_segment_durations(self, segments: list) -> list:
        """Per-segment container duration in ``segments`` order (None on failure).
        Bounded concurrency keeps a long recording's finalize from launching
        thousands of ffprobes at once; the bound tracks the machine's CPU count since
        each probe is a short, I/O-bound subprocess that oversubscribes cores well."""
        sem = asyncio.Semaphore(min(32, max(8, (os.cpu_count() or 4) * 2)))

        async def one(seg: Path):
            async with sem:
                return await self._probe_duration(seg)

        return list(await asyncio.gather(*(one(s) for s in segments)))

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

        The concatenated mp4's PTS runs longer than the media (EXTINF) axis by a
        roughly fixed per-segment mux overhead; modelling that as one proportional
        scale drifts comments by tens of seconds mid-stream (segment lengths vary),
        so each kept segment's real PTS contribution is probed and stored as an
        exact media->pts correspondence. Probed while the segments still exist and
        normalised so the last point equals the finalized mp4 duration; best-effort
        (falls back to the scale model when a probe is unavailable)."""
        try:
            if self.playlist is None or not self.playlist.is_file() or self.hls_dir is None:
                return
            # Ordered kept segments (path, extinf, wall), applying the same
            # PTS-discontinuity filter as the concat (see _drop_discontinuity_segments)
            # so the media axis stays gap-free and aligned with the finalized mp4.
            kept: list[tuple[Path, float, float]] = []
            pending: Optional[float] = None
            prev_wall: Optional[float] = None
            for line in self.playlist.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line.startswith("#EXTINF:"):
                    try:
                        pending = float(line[len("#EXTINF:"):].split(",", 1)[0])
                    except ValueError:
                        pending = None
                elif line and not line.startswith("#"):
                    if pending is None:
                        continue
                    seg = self.hls_dir / line
                    try:
                        wall = seg.stat().st_mtime
                    except OSError:
                        pending = None
                        continue
                    wall_delta = wall - prev_wall if prev_wall is not None else None
                    prev_wall = wall
                    if wall_delta is not None and is_pts_discontinuity(pending, wall_delta):
                        pending = None
                        continue
                    kept.append((seg, pending, wall))
                    pending = None
            if len(kept) < 2:
                return
            media = 0.0
            anchors: list[tuple[float, float]] = []
            for _, extinf, wall in kept:
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
            out = timing_path(mp4_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload), encoding="utf-8")
        except Exception:
            logger.warning("failed to write timing map for %s", self.unique_id, exc_info=True)

    async def _build_media_pts(self, kept: list, mp4_path: Path) -> Optional[list]:
        """Exact media->pts correspondence [[media, pts], ...] from each kept
        segment's real PTS contribution, or None when the segments/mp4 cannot be
        probed (the burn-in then falls back to the single-scale model)."""
        # The whole-mp4 duration probe is a full scan; overlap it with the per-segment
        # probes instead of running it as a separate serial step after them.
        durations, mp4_dur = await asyncio.gather(
            self._probe_segment_durations([seg for seg, _, _ in kept]),
            self._probe_duration(mp4_path),
        )
        media_pts = media_pts_from_segments([extinf for _, extinf, _ in kept], durations, mp4_dur)
        if media_pts is None:
            logger.info(
                "timing map for %s: segment duration probe incomplete; media->pts "
                "falls back to the scale model", self.unique_id,
            )
        return media_pts

    async def _validate_mp4(self, path: Path) -> bool:
        """Confirm the mp4 has a decodable video stream before discarding HLS."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                str(path),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await proc.communicate()
            return proc.returncode == 0 and b"video" in out
        except Exception:
            logger.exception("mp4 validation failed for %s", self.unique_id)
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
                logger.warning("recording task slow to finalize for %s", self.unique_id)
