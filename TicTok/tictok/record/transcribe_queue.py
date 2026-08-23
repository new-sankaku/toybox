"""検索indexの後追い構築。

文字起こしそのものは映像jobと同じ台帳(media_job_queue の kind=stt)で走る。専用queueを
分けていた頃の ``TranscribeQueue`` は、その台帳が「済み判定」を兼ねていたことだけを根拠に
存在していたが、済みの根拠は transcripts テーブルの有無であり、GPU枠も元から共通だったため、
分ける理由が残っていない。投入は server._enqueue_stt_jobs、実行は server._run_stt_job。
"""

import asyncio
import logging
from pathlib import Path
from typing import Callable

from tictok.search import indexer

logger = logging.getLogger(__name__)


def _backfill_targets(storage) -> tuple:
    """backfillの母集合を1回で引く。同期でstorageを触るのでthread側で呼ぶこと。"""
    return (storage.search_indexed_counts(), storage.transcribed_recording_ids(),
            storage.recordings_brief())


async def backfill_search_index(storage, resolve_path: Callable[[str], Path]) -> dict:
    """検索indexの未構築分を埋める。GPUを使わないのでqueueとは独立に走らせる。

    対象は2つ:
      - comment: 収集済みなので、起動時に一度均せば全録画が検索対象になる。
      - 文字起こし: この機能より前に作られたtranscriptはindex経路を通っていない。ここで拾わないと
        「文字起こし済みなのに音声で検索できない」録画が残り続ける。

    起動直後のserverはこのcoroutineと同じloopでrequestを捌いている。storageを触る所は
    すべて ``to_thread`` へ出す — loop上で書き込みlockを待つと、待っているのがevent loop
    自身になり、起動直後の画面がindexの張り終わりまで固まる。
    """
    indexed, transcribed, recordings = await asyncio.to_thread(_backfill_targets, storage)
    done = {"comments": 0, "transcripts": 0}
    # 失敗した録画のid。件数だけ数えて中身を捨てると、「検索に出ない録画が
    # ある」ことに誰も気付けない(backfillは起動時に黙って走るため)。
    failed: list = []
    for recording in recordings:
        recording_id = recording["id"]
        sources = indexed.get(recording_id, {})
        # sessionを失った録画(実測47本)はcommentのindexを持ちようが無い —
        # index_comments はsessionが無ければ0行で戻るだけで、次の起動でもまた
        # 「未index」に見える。行が作れない録画をこの経路の対象にしない。
        needs_comment = (indexer.SOURCE_COMMENT not in sources
                         and recording.get("session_id") is not None)
        needs_transcript = recording_id in transcribed and indexer.SOURCE_STT not in sources
        if not needs_comment and not needs_transcript:
            continue
        full = await asyncio.to_thread(storage.get_recording, recording_id)
        if full is None:
            continue
        try:
            path = resolve_path(full["path"])
        except Exception:
            # pathを解決できない録画。以前は数えも記録もせず素通りしていたため、
            # 「検索に出てこない録画がある」という症状の原因がどこにも残らなかった。
            failed.append(recording_id)
            logger.warning(
                "検索indexのbackfill: 録画 %d のpathを解決できません",
                recording_id, exc_info=True,
                extra={"event": "search.backfill_path_unresolved",
                       "ctx": {"recording_id": recording_id, "path": full.get("path")}},
            )
            continue
        try:
            if needs_transcript:
                await asyncio.to_thread(indexer.index_transcript, storage, full)
                done["transcripts"] += 1
            if needs_comment:
                await indexer.index_comments(storage, full, path)
                done["comments"] += 1
        except Exception:
            failed.append(recording_id)
            logger.exception(
                "検索indexのbackfillに失敗しました: recording_id=%d", recording_id,
                extra={"event": "search.backfill_failed",
                       "ctx": {"recording_id": recording_id}},
            )
            continue
        # 起動直後のI/Oを独占しないよう1件ごとに譲る。
        await asyncio.sleep(0)
    if failed:
        # 1件でも落ちていれば、完了logではなく警告として残す。infoの中に埋めると
        # 「完了した」という記録だけが目に入る。
        logger.warning(
            "検索indexのbackfillが %d 件の失敗を残して終了しました"
            "（comment=%d 文字起こし=%d）該当の録画は検索に出ません",
            len(failed), done["comments"], done["transcripts"],
            extra={"event": "search.backfill_incomplete",
                   "ctx": {**done, "failed": len(failed),
                           "failed_recording_ids": failed[:50]}},
        )
    elif done["comments"] or done["transcripts"]:
        logger.info(
            "検索indexのbackfillが完了しました（comment=%d 文字起こし=%d）",
            done["comments"], done["transcripts"],
            extra={"event": "search.backfill_completed", "ctx": done},
        )
    return {**done, "failed": len(failed)}
