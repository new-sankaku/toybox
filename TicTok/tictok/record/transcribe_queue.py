"""配信者単位で投入する一括転写queue。

STTはtranscription._transcribe_lockで完全に直列化されており、並列に走らせても速くならない
(むしろVRAMを奪い合う)。よってworkerは常に1本で、queueはDBに置いて中断・再起動をまたぐ。

1本終わるごとにtranscriptを保存し、その場で検索indexへ反映してからbroadcastする。
全件終了を待たずに検索結果へ現れるので、長時間のqueueでも先に終わった分から使える。
"""

import asyncio
import logging
from pathlib import Path
from typing import Callable, Optional

from tictok.core import config
from tictok.record.transcription import STTError, stt_available
from tictok.record.transcription import transcribe as stt_transcribe
from tictok.search import indexer

logger = logging.getLogger(__name__)

IDLE_POLL_SECONDS = 5.0


class TranscribeQueue:
    def __init__(self, storage, broadcast: Callable, resolve_path: Callable[[str], Path]):
        self._storage = storage
        self._broadcast = broadcast
        self._resolve_path = resolve_path
        self._task: Optional[asyncio.Task] = None
        self._wake = asyncio.Event()
        self._stopping = False
        self._current: Optional[int] = None

    # ===== lifecycle =====

    def start(self) -> None:
        # 前回processが'running'のまま落ちた行は誰も進めない。pendingへ戻して拾い直す。
        revived = self._storage.reset_running_transcriptions()
        if revived:
            logger.info(
                "transcribe queue: revived %d interrupted job(s)", revived,
                extra={"event": "stt.queue_revived", "ctx": {"revived": revived}},
            )
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ===== 投入 =====

    def enqueue_streamer(self, unique_id: Optional[str], priority: int = 0) -> dict:
        """配信者の未転写録画をまとめて投入する。unique_idがNoneなら全配信者。"""
        pending = self._storage.untranscribed_recordings(unique_id)
        added = self._storage.enqueue_transcriptions(
            [(row["id"], row["unique_id"]) for row in pending], priority)
        if added:
            self._wake.set()
        logger.info(
            "transcribe queue: enqueued %d recording(s) for %s", added, unique_id or "all",
            extra={"event": "stt.queue_enqueued",
                   "ctx": {"unique_id": unique_id, "added": added, "candidates": len(pending)}},
        )
        return {"added": added, "candidates": len(pending)}

    def enqueue_recordings(self, recording_ids: list, priority: int = 0) -> dict:
        """録画を1本単位で投入する。再生中の1本だけを転写したい導線から使う。"""
        entries = []
        for recording_id in recording_ids:
            recording = self._storage.get_recording(recording_id)
            if recording is None:
                raise ValueError(f"recording {recording_id} が存在しません")
            entries.append((recording["id"], recording["unique_id"]))
        added = self._storage.enqueue_transcriptions(entries, priority)
        if added:
            self._wake.set()
        logger.info(
            "transcribe queue: enqueued %d recording(s) by id", added,
            extra={"event": "stt.queue_enqueued",
                   "ctx": {"recording_ids": recording_ids, "added": added,
                           "candidates": len(entries)}},
        )
        return {"added": added, "candidates": len(entries)}

    def cancel(self, recording_ids: Optional[list] = None) -> int:
        return self._storage.cancel_transcriptions(recording_ids)

    def status(self) -> dict:
        items = self._storage.list_transcribe_queue()
        counts: dict = {}
        for item in items:
            counts[item["state"]] = counts.get(item["state"], 0) + 1
        return {
            "available": stt_available(),
            "running": self._current,
            "counts": counts,
            "items": items,
        }

    # ===== worker =====

    async def _run(self) -> None:
        while not self._stopping:
            job = self._storage.next_pending_transcription()
            if job is None:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=IDLE_POLL_SECONDS)
                except asyncio.TimeoutError:
                    pass
                continue
            await self._process(job)

    async def _process(self, job: dict) -> None:
        recording_id = job["recording_id"]
        recording = self._storage.get_recording(recording_id)
        if recording is None:
            self._storage.set_transcription_state(
                recording_id, "failed", error="録画が見つかりません。")
            await self._emit()
            return
        try:
            path = self._resolve_path(recording["path"])
        except Exception as exc:
            self._storage.set_transcription_state(recording_id, "failed", error=str(exc))
            await self._emit()
            return
        if not path.is_file():
            self._storage.set_transcription_state(
                recording_id, "failed", error="録画fileが存在しません。")
            await self._emit()
            return

        self._current = recording_id
        self._storage.set_transcription_state(recording_id, "running")
        await self._emit()
        loop = asyncio.get_running_loop()
        last_pct = -1

        def on_progress(done: float, total: float) -> None:
            nonlocal last_pct
            pct = min(100, int(done / total * 100)) if total > 0 else 0
            if pct == last_pct:
                return
            last_pct = pct
            self._storage.update_transcription_pct(recording_id, pct)
            asyncio.run_coroutine_threadsafe(
                self._broadcast({"type": "transcribe_progress",
                                 "recording_id": recording_id, "pct": pct}), loop)

        try:
            result = await self._transcribe_with_retry(recording_id, path, on_progress)
        except STTError as exc:
            self._current = None
            self._storage.set_transcription_state(recording_id, "failed", error=str(exc))
            logger.warning(
                "transcribe queue job failed: recording_id=%d", recording_id, exc_info=True,
                extra={"event": "stt.queue_job_failed", "ctx": {"recording_id": recording_id}},
            )
            await self._emit()
            return
        except Exception as exc:
            self._current = None
            self._storage.set_transcription_state(recording_id, "failed", error=str(exc))
            logger.exception(
                "transcribe queue job crashed: recording_id=%d", recording_id,
                extra={"event": "stt.queue_job_crashed", "ctx": {"recording_id": recording_id}},
            )
            await self._emit()
            return

        self._storage.save_transcript(recording_id, result)
        # 保存直後にindexへ反映する。ここを後回しにすると、queue完走まで検索に出てこない。
        await asyncio.to_thread(indexer.index_transcript, self._storage, recording)
        self._current = None
        self._storage.set_transcription_state(recording_id, "done")
        await self._broadcast({"type": "transcribe_progress",
                               "recording_id": recording_id, "pct": 100})
        await self._emit(indexed=recording_id)

    async def _transcribe_with_retry(self, recording_id: int, path: Path,
                                     on_progress: Callable) -> dict:
        """転写を実行し、失敗が残り試行回数の範囲なら待ってから実行し直す。

        STTはGPUと録画fileの両方を掴むため、他jobがVRAMを解放する途中のCUDA確保失敗や、
        退避直後のfileが一時的に開けない、といった数秒で消える失敗で落ちる。1発failedに
        すると人が投げ直すまで転写されないままになるので、設定回数まで試す。
        """
        attempts = max(1, config.get_transcribe_job_attempts())
        backoff = config.get_transcribe_job_retry_backoff_seconds()
        for attempt in range(1, attempts + 1):
            try:
                return await asyncio.to_thread(stt_transcribe, str(path), on_progress)
            except Exception:
                if attempt >= attempts:
                    raise
                wait = backoff * attempt
                logger.warning(
                    "transcribe attempt %d/%d failed, retrying in %.1fs: recording_id=%d",
                    attempt, attempts, wait, recording_id, exc_info=True,
                    extra={"event": "stt.queue_job_retry",
                           "ctx": {"recording_id": recording_id, "attempt": attempt,
                                   "attempts": attempts, "wait_seconds": round(wait, 1)}},
                )
                await asyncio.sleep(wait)

    async def _emit(self, indexed: Optional[int] = None) -> None:
        message = {"type": "transcribe_queue", "status": self.status()}
        if indexed is not None:
            message["indexed_recording_id"] = indexed
        await self._broadcast(message)


async def backfill_search_index(storage, resolve_path: Callable[[str], Path]) -> dict:
    """検索indexの未構築分を埋める。GPUを使わないのでqueueとは独立に走らせる。

    対象は2つ:
      - comment: 収集済みなので、起動時に一度均せば全録画が検索対象になる。
      - 転写: この機能より前に作られたtranscriptはindex経路を通っていない。ここで拾わないと
        「文字起こし済みなのに音声で検索できない」録画が残り続ける。
    """
    indexed = storage.search_indexed_counts()
    transcribed = storage.transcribed_recording_ids()
    done = {"comments": 0, "transcripts": 0}
    for recording in storage.recordings_brief():
        recording_id = recording["id"]
        sources = indexed.get(recording_id, {})
        needs_comment = indexer.SOURCE_COMMENT not in sources
        needs_transcript = recording_id in transcribed and indexer.SOURCE_STT not in sources
        if not needs_comment and not needs_transcript:
            continue
        full = storage.get_recording(recording_id)
        if full is None:
            continue
        try:
            path = resolve_path(full["path"])
        except Exception:
            continue
        try:
            if needs_transcript:
                indexer.index_transcript(storage, full)
                done["transcripts"] += 1
            if needs_comment:
                await indexer.index_comments(storage, full, path)
                done["comments"] += 1
        except Exception:
            logger.exception(
                "search index backfill failed: recording_id=%d", recording_id,
                extra={"event": "search.backfill_failed",
                       "ctx": {"recording_id": recording_id}},
            )
            continue
        # 起動直後のI/Oを独占しないよう1件ごとに譲る。
        await asyncio.sleep(0)
    if done["comments"] or done["transcripts"]:
        logger.info(
            "search index backfill completed (comments=%d transcripts=%d)",
            done["comments"], done["transcripts"],
            extra={"event": "search.backfill_completed", "ctx": done},
        )
    return done
