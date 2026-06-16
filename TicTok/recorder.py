import asyncio
import json
import logging
import os
import shutil
import signal
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("tictok.recorder")

STATE_IDLE = "idle"
STATE_RECORDING = "recording"
STATE_STOPPING = "stopping"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"

# Preference order (high -> low). TikTok quality keys vary per stream.
QUALITY_PREFERENCE = ["origin", "uhd", "hd", "sd", "ld"]
HEALTHY_WAIT_SECONDS = 14
MIN_SEGMENTS = 2
MAX_LAUNCH_ATTEMPTS = 4
SEGMENT_SECONDS = 2


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


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

    def __init__(self, unique_id: str, record_dir: str) -> None:
        self.unique_id = unique_id
        self._record_dir = Path(record_dir)
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

    async def start(self, room_info: dict, on_finalize=None) -> None:
        if self.is_active:
            raise RuntimeError("既に録画中です。")
        if not ffmpeg_available():
            raise RuntimeError("ffmpegが見つかりません。録画にはffmpegのinstallが必要です。")
        url, quality = extract_stream_url(room_info)
        if not url:
            raise RuntimeError("配信のstream URLを取得できませんでした（録画不可）。")
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        self.base = f"{self.unique_id}_{stamp}"
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
                "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
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
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                proc.send_signal(sig)
            except ProcessLookupError:
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

    async def _finalize(self) -> None:
        self.ended_at = time.time()
        if self._has_segments() and self.playlist and self.playlist.exists():
            mp4_path = self._mp4_path
            if await self._concat_to_mp4(self.playlist, mp4_path):
                self.output_path = mp4_path
                shutil.rmtree(self.hls_dir, ignore_errors=True)
                if self.state != STATE_FAILED:
                    self.state = STATE_COMPLETED
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

    async def _concat_to_mp4(self, playlist: Path, dst: Path) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
                "-i", str(playlist), "-c", "copy", "-movflags", "+faststart", str(dst),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            return proc.returncode == 0 and dst.exists() and dst.stat().st_size > 0
        except Exception:
            logger.exception("concat to mp4 failed for %s", self.unique_id)
            return False

    async def stop(self) -> None:
        if not self.is_active:
            return
        self._stop_requested = True
        self.state = STATE_STOPPING
        if self._proc is not None:
            await self._terminate(self._proc)
        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=30)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.warning("recording task slow to finalize for %s", self.unique_id)
