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
# Minimum bytes that must appear quickly to consider the connection healthy.
HEALTHY_BYTES = 50_000
HEALTHY_WAIT_SECONDS = 12
MAX_LAUNCH_ATTEMPTS = 4


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

    # Fallback: legacy flat flv pull url map.
    flv_map = stream_url.get("flv_pull_url") or {}
    if isinstance(flv_map, dict) and flv_map:
        for label in ("FULL_HD1", "HD1", "SD2", "SD1"):
            if flv_map.get(label):
                return flv_map[label], label.lower()
        first_label, first_url = next(iter(flv_map.items()))
        return first_url, str(first_label).lower()

    return None, None


class Recorder:
    """Records a TikTok LIVE stream to disk via ffmpeg (stream copy, no re-encode)."""

    def __init__(self, unique_id: str, record_dir: str) -> None:
        self.unique_id = unique_id
        self._record_dir = Path(record_dir)
        self.state = STATE_IDLE
        self.quality: Optional[str] = None
        self.error: Optional[str] = None
        self.started_at: Optional[float] = None
        self.ended_at: Optional[float] = None
        self.ts_path: Optional[Path] = None
        self.output_path: Optional[Path] = None
        self.recording_id: Optional[int] = None
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._task: Optional[asyncio.Task] = None
        self._stop_requested = False

    @property
    def is_active(self) -> bool:
        return self.state in (STATE_RECORDING, STATE_STOPPING)

    def snapshot(self) -> dict:
        size = 0
        path = self.output_path or self.ts_path
        if path is not None and path.exists():
            size = path.stat().st_size
        return {
            "state": self.state,
            "quality": self.quality,
            "error": self.error,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "bytes": size,
            "filename": self.output_path.name if self.output_path else None,
            "recording_id": self.recording_id,
        }

    async def start(self, room_info: dict, on_finalize=None) -> None:
        if self.is_active:
            raise RuntimeError("既に録画中です。")
        if not ffmpeg_available():
            raise RuntimeError("ffmpegが見つかりません。録画にはffmpegのinstallが必要です。")
        url, quality = extract_stream_url(room_info)
        if not url:
            raise RuntimeError("配信のstream URLを取得できませんでした（録画不可）。")
        self._record_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        base = f"{self.unique_id}_{stamp}"
        self.ts_path = self._record_dir / f"{base}.ts"
        self.output_path = self.ts_path
        self.quality = quality
        self.error = None
        self.started_at = time.time()
        self.ended_at = None
        self._stop_requested = False
        self.state = STATE_RECORDING
        self._on_finalize = on_finalize
        self._task = asyncio.create_task(self._run(url), name=f"tictok-rec-{self.unique_id}")
        logger.info("recording started: %s quality=%s -> %s", self.unique_id, quality, self.ts_path)

    async def _run(self, url: str) -> None:
        log_path = self.ts_path.with_suffix(".ts.log")
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
                # Unhealthy: corrupt/failed connection. Kill and retry.
                await self._terminate(proc)
                if self._stop_requested or attempt >= MAX_LAUNCH_ATTEMPTS:
                    if not self._has_data():
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
                "-i", url, "-c", "copy", "-f", "mpegts", str(self.ts_path),
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
                return self._has_data()
            if self._has_data():
                return True
        return self._has_data()

    def _has_data(self) -> bool:
        return self.ts_path is not None and self.ts_path.exists() and self.ts_path.stat().st_size > HEALTHY_BYTES

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
        if self.ts_path and self.ts_path.exists() and self.ts_path.stat().st_size > HEALTHY_BYTES:
            mp4_path = self.ts_path.with_suffix(".mp4")
            if await self._remux_to_mp4(self.ts_path, mp4_path):
                self.output_path = mp4_path
                try:
                    self.ts_path.unlink()
                except OSError:
                    logger.debug("could not remove intermediate ts", exc_info=True)
            else:
                self.output_path = self.ts_path
            if self.state != STATE_FAILED:
                self.state = STATE_COMPLETED
        else:
            if self.state != STATE_FAILED:
                self.state = STATE_FAILED
                self.error = self.error or "録画Dataが空でした（stream接続不良）。"
            if self.ts_path and self.ts_path.exists() and self.ts_path.stat().st_size == 0:
                try:
                    self.ts_path.unlink()
                except OSError:
                    pass
        callback = getattr(self, "_on_finalize", None)
        if callback is not None:
            try:
                await callback(self)
            except Exception:
                logger.exception("recording finalize callback failed for %s", self.unique_id)
        logger.info("recording finalized: %s state=%s file=%s", self.unique_id, self.state, self.output_path)

    async def _remux_to_mp4(self, src: Path, dst: Path) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
                "-i", str(src), "-c", "copy", "-movflags", "+faststart", str(dst),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            return proc.returncode == 0 and dst.exists() and dst.stat().st_size > 0
        except Exception:
            logger.exception("remux to mp4 failed for %s", self.unique_id)
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
