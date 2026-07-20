"""映像job(焼き込み / Up出力 / 再mp4化)の永続queue。

転写queueと同じ形だが、支える要求が2つ多い。

1. **投入意図がprocessをまたぐ**。焼き込み＋超解像は実時間の数倍かかるため、投入から完了まで
   の間にserverが再起動する運用が普通にある。in-processの台帳(server.JobRegistry)だけでは
   「投げたはずの処理」が再起動で消え、operatorは何が済んで何が消えたのか判別できない。
   よってstateはDBが正で、registryは進捗の即時配信だけを担う。
2. **cancelできる**。GPU jobは一度走り出すと数時間戻らないので、間違えて投げたjobを止める
   手段が要る。待機中はDBのstateを変えるだけで済むが、実行中はtoken(core.cancel)を投げて
   ffmpegをkillし、部分fileを掃除させる。

workerは常に1本。GPU semaphore(core.gpu)は同時実行を止めるが、待たせるだけでqueueの順序も
全体像も持たない。ここで直列化しておけば「いま何をしていて、次に何をするか」が1箇所で答え
られる。
"""

import asyncio
import logging
from typing import Callable, Optional

from tictok.core import config
from tictok.core.cancel import CancelToken, JobCancelled, token_scope

logger = logging.getLogger(__name__)

# DBのkind → 画面/registryのdomain名。単体jobはkindがそのままdomainになる。
GROUP_DOMAINS = {"overlay": "session_overlay", "upscale": "session_upscale"}
# 実行が終わったstate。pending/runningの補集合として書くと、新しいstateを足したときに
# 「終わっていないのに終了扱い」へ静かに転ぶので列挙する。
FINISHED_STATES = ("completed", "failed", "cancelled", "skipped", "interrupted")


class JobSkipped(Exception):
    """やることが無かったので何も作らずに終わった、という正常終了。

    「描く対象が1件も無い」ような入力側の前提不成立は、serverから見れば異常ではない。
    Exceptionのまま外へ抜けると job=failed(赤badge)・ops_events severity=error になり、
    userは自分の選んだ録画の性質を障害として提示される。理由付きのskipped stateへ落とす
    ため、失敗と型で分ける。
    """


def job_payload(row: dict) -> dict:
    """DBの1行を、WSとJobRegistryが使うjob objectの形へ揃える。画面側が単体jobとsession
    jobを同じhandlerで扱えるよう、keyは JobRegistry.start と完全に一致させること。"""
    return {
        "job_id": row["job_id"],
        "domain": row["kind"],
        "title": row.get("title") or "",
        "recording_id": row.get("recording_id"),
        "session_id": row.get("session_id"),
        "state": row["state"],
        "stage": row.get("stage") or "",
        "pct": row.get("pct") or 0,
        "index": 0,
        "total": 1,
        "started_at": row.get("started_at") or row.get("queued_at"),
        "finished_at": row.get("finished_at"),
        "message": row.get("error") or "",
        "group_id": row.get("group_id") or "",
        "queued_at": row.get("queued_at"),
        "filename": row.get("filename"),
        "unique_id": row.get("unique_id"),
        "result": row.get("result") or {},
    }


def group_payload(rows: list) -> Optional[dict]:
    """同一group_id(session一括投入の1回分)の行から、session単位のjob objectを合成する。

    履歴画面のSession行は session_overlay / session_upscale というdomainの1 jobを見て進捗を
    描く。実体を録画ごとの行へ分割してもその見え方を変えないために、ここで畳み直す。
    """
    if not rows:
        return None
    first = rows[0]
    domain = GROUP_DOMAINS.get(first["kind"])
    if domain is None:
        return None
    total = len(rows)
    done = [r for r in rows if r["state"] in FINISHED_STATES]
    running = [r for r in rows if r["state"] == "running"]
    pct = int((len(done) * 100 + sum(r.get("pct") or 0 for r in running)) / total)
    failed = [r for r in rows if r["state"] in ("failed", "interrupted")]
    cancelled = [r for r in rows if r["state"] == "cancelled"]
    skipped = [r for r in rows if r["state"] == "skipped"]
    if len(done) < total:
        state = "running"
        message = ""
    elif failed:
        state = "failed"
        message = f"{len(failed)}件の録画を出力できませんでした（{failed[0].get('error') or ''}）"
    elif cancelled and len(cancelled) == total:
        state = "cancelled"
        message = "取り消しました。"
    elif skipped and len(skipped) == total:
        state = "skipped"
        message = skipped[0].get("error") or ""
    else:
        state = "completed"
        # skipped(作る物が無かった)を出力済みに数えると件数が実態と合わなくなる。
        message = f"{total - len(cancelled) - len(skipped)}件の録画を出力しました"
    stage = ""
    index = len(done)
    if running:
        index = min(total, len(done) + 1)
        stage = f"({index}/{total}) {running[0].get('stage') or ''}".strip()
    return {
        "job_id": first["group_id"],
        "domain": domain,
        "title": first.get("title") or "",
        "recording_id": None,
        "session_id": first.get("session_id"),
        "state": state,
        "stage": stage,
        "pct": 100 if state != "running" else pct,
        "index": index,
        "total": total,
        "started_at": min((r.get("started_at") or r.get("queued_at")) for r in rows),
        "finished_at": max((r.get("finished_at") or 0) for r in rows) or None,
        "message": message,
        "group_id": first["group_id"],
    }


class MediaJobQueue:
    """DB backedの映像job worker。1本ずつ実行し、状態はDBを正として配信する。"""

    def __init__(self, storage, broadcast: Callable, runner: Callable) -> None:
        self._storage = storage
        self._broadcast = broadcast
        # runner(job, report) -> dict。実処理(焼き込み/Up出力/再mp4化)はserver側の既存helperを
        # 使うため、queueは実処理を一切知らない。
        self._runner = runner
        self._task: Optional[asyncio.Task] = None
        self._wake = asyncio.Event()
        self._stopping = False
        self._tokens: dict[str, CancelToken] = {}
        self._last_progress: dict[str, tuple] = {}

    # ===== lifecycle =====

    def start(self) -> None:
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

    # ===== 投入 / 取り消し =====

    async def enqueue(self, job_id: str, kind: str, recording_id: int, *,
                      session_id: Optional[int] = None, group_id: str = "",
                      title: str = "", priority: int = 0,
                      params: Optional[dict] = None) -> dict:
        row = self._storage.enqueue_media_job(
            job_id, kind, recording_id, session_id=session_id, group_id=group_id,
            title=title, priority=priority, params=params,
        )
        logger.info(
            "media queue: enqueued %s for recording %s", kind, recording_id,
            extra={"event": "media_queue.enqueued",
                   "ctx": {"job_id": job_id, "kind": kind, "recording_id": recording_id,
                           "session_id": session_id, "group_id": group_id}},
        )
        self._wake.set()
        await self._emit(row)
        return row

    def pending_for(self, kind: str, recording_id: int) -> Optional[dict]:
        return self._storage.pending_media_job_for(kind, recording_id)

    async def cancel(self, job_id: str) -> str:
        """取り消し結果を返す: 'cancelled'(待機中を取消) / 'cancelling'(実行中へ中断要求) /
        'missing'(該当なし) / 'finished'(既に終了) / 'unsupported'(中断点が無い種別)。"""
        job = self._storage.get_media_job(job_id)
        if job is None:
            return "missing"
        if job["state"] == "pending":
            if not self._storage.cancel_pending_media_job(job_id):
                return "finished"
            await self._emit(self._storage.get_media_job(job_id))
            return "cancelled"
        if job["state"] == "running":
            if job["kind"] == "reprocess":
                # 再mp4化はrecorderのfinalize pipeline(concat→timing→normalize)をそのまま
                # 呼ぶ経路で、中断点を持たない。止められないものを「取り消しました」と
                # 表示すると、退避中のmp4の扱いを誤解させるので拒否する。
                return "unsupported"
            token = self._tokens.get(job_id)
            if token is None:
                # workerが持っていない実行中行は前回processの残骸。startup recoveryが
                # interruptedへ倒すので、ここで勝手にstateを書き換えない。
                return "missing"
            token.cancel()
            await self._update_progress(job_id, job.get("pct") or 0, "取り消し中…")
            return "cancelling"
        return "finished"

    def list_jobs(self, limit: int = 200) -> list:
        """単体jobと、session一括投入をgroupへ畳んだjobの一覧。"""
        rows = self._storage.list_media_jobs(limit)
        payloads = [job_payload(row) for row in rows]
        groups: dict = {}
        for row in rows:
            gid = row.get("group_id") or ""
            if gid:
                groups.setdefault(gid, []).append(row)
        for gid, members in groups.items():
            group = group_payload(members)
            if group is not None:
                payloads.append(group)
        return payloads

    # ===== worker =====

    async def _run(self) -> None:
        poll = config.get_media_queue_poll_seconds()
        while not self._stopping:
            job = self._storage.next_pending_media_job()
            if job is None:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=poll)
                except asyncio.TimeoutError:
                    pass
                continue
            await self._process(job)

    async def _process(self, job: dict) -> None:
        job_id = job["job_id"]
        token = CancelToken(job_id)
        self._tokens[job_id] = token
        self._storage.start_media_job(job_id)
        await self._emit(self._storage.get_media_job(job_id))

        async def report(stage: str, pct: int) -> None:
            await self._update_progress(job_id, pct, stage)

        try:
            with token_scope(token):
                result = await self._run_with_retry(job, report, token)
        except JobCancelled:
            logger.info(
                "media job cancelled: %s (%s)", job_id, job["kind"],
                extra={"event": "media_queue.job_cancelled",
                       "ctx": {"job_id": job_id, "kind": job["kind"],
                               "recording_id": job.get("recording_id")}},
            )
            self._storage.finish_media_job(job_id, "cancelled", error="取り消しました。")
        except JobSkipped as exc:
            logger.info(
                "media job skipped: %s (%s) %s", job_id, job["kind"], exc,
                extra={"event": "media_queue.job_skipped",
                       "ctx": {"job_id": job_id, "kind": job["kind"],
                               "recording_id": job.get("recording_id"),
                               "reason": str(exc)}},
            )
            self._storage.finish_media_job(job_id, "skipped", error=str(exc))
        except Exception as exc:
            # HTTPExceptionのdetailはuserへ出す日本語文言なので、str(exc)より優先する。
            detail = getattr(exc, "detail", None)
            message = detail if isinstance(detail, str) else str(exc)
            logger.exception(
                "media job failed: %s (%s)", job_id, job["kind"],
                extra={"event": "media_queue.job_failed",
                       "ctx": {"job_id": job_id, "kind": job["kind"],
                               "recording_id": job.get("recording_id")}},
            )
            self._storage.finish_media_job(job_id, "failed", error=message)
        else:
            self._storage.finish_media_job(job_id, "completed", result=result)
        finally:
            self._tokens.pop(job_id, None)
            self._last_progress.pop(job_id, None)
        await self._emit(self._storage.get_media_job(job_id))

    async def _run_with_retry(self, job: dict, report: Callable, token: CancelToken):
        """runnerを実行し、失敗が残り試行回数の範囲なら待ってから実行し直す。

        1発失敗=永久failedにすると、出力先fileがantivirusに掴まれていた・disk busyで
        ffmpegの起動が弾かれた、といった数秒で消える事象が「人が投げ直すまで直らない
        失敗」として残る。取り消し(JobCancelled)と入力側の前提不成立(JobSkipped)は
        再試行しても結果が変わらないので、ここでは捕まえずそのまま外へ通す。
        """
        attempts = max(1, config.get_media_job_attempts())
        backoff = config.get_media_job_retry_backoff_seconds()
        job_id = job["job_id"]
        for attempt in range(1, attempts + 1):
            try:
                return await self._runner(job, report)
            except (JobCancelled, JobSkipped):
                raise
            except Exception:
                if attempt >= attempts:
                    raise
                wait = backoff * attempt
                logger.warning(
                    "media job attempt %d/%d failed, retrying in %.1fs: %s (%s)",
                    attempt, attempts, wait, job_id, job["kind"], exc_info=True,
                    extra={"event": "media_queue.job_retry",
                           "ctx": {"job_id": job_id, "kind": job["kind"],
                                   "recording_id": job.get("recording_id"),
                                   "attempt": attempt, "attempts": attempts,
                                   "wait_seconds": round(wait, 1)}},
                )
                await self._update_progress(
                    job_id, job.get("pct") or 0,
                    f"失敗したため再試行します（{attempt + 1}/{attempts}）…")
                await asyncio.sleep(wait)
                # 待っている間に取り消されたなら、再試行せず取り消しとして畳む。
                token.check()

    async def _update_progress(self, job_id: str, pct: int, stage: str) -> None:
        # 同じ(段階, %)の再通知はDB書き込みも配信も省く。frame単位のcallbackはpctが変わらない
        # 間も鳴り続けるため、ここで落とさないと1 jobで数万回のUPDATEになる。
        if self._last_progress.get(job_id) == (pct, stage):
            return
        self._last_progress[job_id] = (pct, stage)
        self._storage.update_media_job_progress(job_id, pct, stage)
        await self._emit(self._storage.get_media_job(job_id))

    async def _emit(self, row: Optional[dict]) -> None:
        if row is None:
            return
        await self._broadcast({"type": "job_update", "job": job_payload(row)})
        group_id = row.get("group_id") or ""
        if not group_id:
            return
        group = group_payload(self._storage.media_jobs_in_group(group_id))
        if group is not None:
            await self._broadcast({"type": "job_update", "job": group})
