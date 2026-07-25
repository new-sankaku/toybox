"""映像job(焼き込み / Up出力 / 再mp4化 / 音量正規化)の永続queue。

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
import time
from typing import Callable, Optional

from tictok.core import config
from tictok.core.cancel import CancelToken, JobCancelled, token_scope

logger = logging.getLogger(__name__)

# DBのkind → 画面/registryのdomain名。単体jobはkindがそのままdomainになる。
GROUP_DOMAINS = {"overlay": "session_overlay", "upscale": "session_upscale"}
# 配信者まるごとの一括投入のdomain。session_*と分けるのは、こちらのgroupが複数sessionへ
# またがるため。session_*のまま出すと履歴画面が先頭録画のsession行1つを掴み、そのsessionに
# 属さない録画まで含む進捗と件数をそこへ貼り付けてしまう。
BULK_DOMAINS = {"overlay": "bulk_overlay", "upscale": "bulk_upscale",
                "reprocess": "bulk_reprocess", "audionorm": "bulk_audionorm"}
# 実行が終わったstate。pending/runningの補集合として書くと、新しいstateを足したときに
# 「終わっていないのに終了扱い」へ静かに転ぶので列挙する。
FINISHED_STATES = ("completed", "failed", "cancelled", "skipped", "interrupted")


class JobDeferred(Exception):
    """まだ実行できないので待機へ戻す、という保留。失敗ではない。

    保存先volumeが見えない・親dirが消えている、といった前提不成立は、数十秒のretryでは
    埋まらない一方で人の介入も要らない(挿し直せば戻る)。これをfailedにすると、一括投入の
    残りが黙って欠落し、しかも作りかけのfileだけが残る。attemptを消費せず待つことで、
    投入した内容がそのまま最後まで走り切る。
    """

    def __init__(self, reason: str, retry_after: Optional[float] = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


class JobSkipped(Exception):
    """やることが無かったので何も作らずに終わった、という正常終了。

    「描く対象が1件も無い」ような入力側の前提不成立は、serverから見れば異常ではない。
    Exceptionのまま外へ抜けると job=failed(赤badge)・ops_events severity=error になり、
    userは自分の選んだ録画の性質を障害として提示される。理由付きのskipped stateへ落とす
    ため、失敗と型で分ける。
    """


def job_payload(row: dict, queue_position: int = 0) -> dict:
    """DBの1行を、WSとJobRegistryが使うjob objectの形へ揃える。画面側が単体jobとsession
    jobを同じhandlerで扱えるよう、keyは JobRegistry.start と完全に一致させること。

    ``queue_position`` は待機中jobの順番(1始まり、0は不明/対象外)。「待機中」としか
    出せないと、3時間jobの後ろに並んだのか次に始まるのかが区別できない。"""
    return {
        "queue_position": queue_position,
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
        # 待機中でも「順番待ち」と「前提の復帰待ち」は別物。画面が同じ『待機中』として
        # 並べると、進まない理由が読めない。
        "not_before": row.get("not_before"),
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
    # 一括かSessionかは投入時のparamsで決める。session_idの数から推測すると、1 sessionしか
    # 持たない配信者への一括投入がSession出力として畳まれてしまう。
    bulk = bool((first.get("params") or {}).get("bulk"))
    domain = (BULK_DOMAINS if bulk else GROUP_DOMAINS).get(first["kind"])
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
        # memberが1件も動いていない一括投入は「実行中 0%」ではなく待機中。長いjobの後ろに
        # 並んだSession出力が実行中として描かれると、待機2件・実行2件が区別できなくなる。
        state = "running" if (running or done) else "pending"
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
        # 一括は特定のsessionに属さない。ここにidを載せると、履歴画面がそのsession行へ
        # group全体の進捗を貼ってしまう。
        "session_id": None if bulk else first.get("session_id"),
        "state": state,
        "stage": stage,
        # 未完了(running/pending)は実測%、終了状態だけが100。pendingを100と描くと、
        # まだ1件も始まっていないgroupが完了済みに見える。
        "pct": pct if state in ("running", "pending") else 100,
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
        self._tasks: list = []
        self._wake = asyncio.Event()
        self._stopping = False
        self._tokens: dict[str, CancelToken] = {}
        self._last_progress: dict[str, tuple] = {}
        # 集計済みのgroup_id。同時に終わった2件が同じ集計を二重に残さないための目印で、
        # process内に留めてよい(再起動を跨ぐと、そのgroupは既に終わっているので通らない)。
        self._summarized: set = set()

    # ===== lifecycle =====

    def start(self) -> None:
        workers = config.get_media_queue_workers()
        self._tasks = [asyncio.create_task(self._run()) for _ in range(workers)]
        if workers > 1:
            logger.info(
                "media queue: %d concurrent worker(s)", workers,
                extra={"event": "media_queue.workers_started",
                       "ctx": {"workers": workers}},
            )

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks = []

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

    async def requeue(self, job_ids) -> int:
        """終わってしまったjobを同じ行のまま待機へ戻す。戻した件数を返す。

        新しい行として投げ直すのではなく元の行を戻すのは、一括投入のgroupが「N本中M本」で
        数えられているため。失敗行を残したまま新規行を足すと母数だけが増え、groupは何度
        やり直しても完了しない。"""
        requeued = self._storage.requeue_media_jobs(job_ids)
        if not requeued:
            return 0
        # 戻したgroupはもう一度終わる。集計済みの目印を外さないと、2周目の結果が
        # ops_eventsに残らない(1周目の失敗だけが最後の記録として残ってしまう)。
        for job_id in job_ids:
            row = self._storage.get_media_job(job_id)
            if row and row.get("group_id"):
                self._summarized.discard(row["group_id"])
        self._wake.set()
        for job_id in job_ids:
            await self._emit(self._storage.get_media_job(job_id))
        await self._emit_pending()
        return requeued

    async def cancel(self, job_id: str) -> str:
        """取り消し結果を返す: 'cancelled'(待機中を取消) / 'cancelling'(実行中へ中断要求) /
        'missing'(該当なし、または前回processの残骸running行) / 'finished'(既に終了)。"""
        job = self._storage.get_media_job(job_id)
        if job is None:
            return "missing"
        if job["state"] == "pending":
            if not self._storage.cancel_pending_media_job(job_id):
                return "finished"
            await self._emit(self._storage.get_media_job(job_id))
            return "cancelled"
        if job["state"] == "running":
            token = self._tokens.get(job_id)
            if token is None:
                # workerが持っていない実行中行は前回processの残骸。startup recoveryが
                # interruptedへ倒すので、ここで勝手にstateを書き換えない。
                return "missing"
            token.cancel()
            await self._update_progress(job_id, job.get("pct") or 0, "取り消し中…")
            return "cancelling"
        return "finished"

    def _queue_positions(self) -> dict:
        """{job_id: 順番(1始まり)}。workerが次に拾う順(priority DESC, queued_at)と
        同じ並びで数える。ここが実際の実行順と食い違うと、待機列の表示が嘘になる。"""
        pending = [r for r in self._storage.list_media_jobs(1000)
                   if r["state"] == "pending"]
        pending.sort(key=lambda r: (-(r.get("priority") or 0), r.get("queued_at") or 0))
        return {r["job_id"]: i + 1 for i, r in enumerate(pending)}

    def list_jobs(self, limit: int = 200) -> list:
        """単体jobと、session一括投入をgroupへ畳んだjobの一覧。"""
        rows = self._storage.list_media_jobs(limit)
        positions = self._queue_positions()
        payloads = [job_payload(row, positions.get(row["job_id"], 0)) for row in rows]
        group_ids = {row["group_id"] for row in rows if row.get("group_id")}
        for gid in group_ids:
            # 畳む元はlimitで切られたrowsではなく、group全件を引き直したものを使う。
            # rowsから作ると、limitを超える一括投入(配信者まるごとは数百本になる)の
            # group行が「200本中N本」と、実際より小さい母数で進捗を出してしまう。
            group = group_payload(self._storage.media_jobs_in_group(gid))
            if group is not None:
                payloads.append(group)
        return payloads

    # ===== worker =====

    async def _run(self) -> None:
        poll = config.get_media_queue_poll_seconds()
        while not self._stopping:
            # 取得と同時にrunningへ落とす。workerが複数居るとき、選んでから開始を書くまでの
            # 隙間に別のworkerが同じ行を拾えてしまう。
            job = self._storage.claim_next_pending_media_job()
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
        # stateはclaimで既にrunning。ここで書き直すとstarted_atが後ろへずれる。
        await self._emit(self._storage.get_media_job(job_id))
        # 1件動き出したので後続の順番が1つずつ繰り上がる。
        await self._emit_pending()

        async def report(stage: str, pct: int) -> None:
            await self._update_progress(job_id, pct, stage)

        deferred = False
        try:
            with token_scope(token):
                result = await self._run_with_retry(job, report, token)
        except JobDeferred as exc:
            deferred = self._defer(job, exc)
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
            if not deferred:
                self._storage.finish_media_job(job_id, "completed", result=result)
        finally:
            self._tokens.pop(job_id, None)
            self._last_progress.pop(job_id, None)
        await self._emit(self._storage.get_media_job(job_id))
        await self._emit_pending()
        if not deferred:
            self._summarize_group(job)

    def _summarize_group(self, job: dict) -> None:
        """一括投入が終わり切ったところで、成功と失敗の件数をops_eventsへ1行残す。

        group行の進捗はJob画面を開いていれば見えるが、開いていなければ何も残らない。
        一括は数時間かかるので「投げて寝る」のが普通の使い方であり、朝に欠落へ気付ける
        場所が要る。ops_eventsはNotifierの観測点でもあるので、webhookもここから届く。"""
        group_id = job.get("group_id") or ""
        if not group_id or group_id in self._summarized:
            return
        rows = self._storage.media_jobs_in_group(group_id)
        if not rows or any(r["state"] not in FINISHED_STATES for r in rows):
            return
        self._summarized.add(group_id)
        failed = [r for r in rows if r["state"] in ("failed", "interrupted")]
        done = [r for r in rows if r["state"] == "completed"]
        severity = "warning" if failed else "info"
        self._storage.record_ops_event(
            logger, "media_queue.group_finished",
            f"{job['kind']}の一括処理が終わりました: 完了 {len(done)}件 / 失敗 {len(failed)}件"
            f"（対象 {len(rows)}件）",
            severity=severity, job_id=group_id,
            detail={"kind": job["kind"], "total": len(rows), "completed": len(done),
                    "failed": len(failed),
                    "failed_job_ids": [r["job_id"] for r in failed][:20],
                    "first_error": failed[0].get("error") if failed else None},
        )

    def _defer(self, job: dict, exc: JobDeferred) -> bool:
        """保留を待機へ書き戻す。総待ち時間を超えていたらfailedへ倒し、Falseを返す。"""
        job_id = job["job_id"]
        row = self._storage.get_media_job(job_id) or job
        waited = time.time() - (row.get("deferred_since") or time.time())
        limit = config.get_media_job_defer_timeout_seconds()
        if waited > limit:
            message = f"{exc.reason}（{int(waited // 60)}分待っても解消しませんでした）"
            logger.error(
                "media job gave up waiting: %s (%s) %s", job_id, job["kind"], exc.reason,
                extra={"event": "media_queue.job_defer_timeout",
                       "ctx": {"job_id": job_id, "kind": job["kind"],
                               "recording_id": job.get("recording_id"),
                               "reason": exc.reason, "waited_seconds": round(waited)}},
            )
            self._storage.finish_media_job(job_id, "failed", error=message)
            return False
        wait = exc.retry_after or config.get_media_job_defer_seconds()
        self._storage.defer_media_job(
            job_id, time.time() + wait, f"{exc.reason} 復帰を待っています…")
        logger.warning(
            "media job deferred for %.0fs: %s (%s) %s", wait, job_id, job["kind"], exc.reason,
            extra={"event": "media_queue.job_deferred",
                   "ctx": {"job_id": job_id, "kind": job["kind"],
                           "recording_id": job.get("recording_id"),
                           "reason": exc.reason, "wait_seconds": round(wait),
                           "waited_seconds": round(waited)}},
        )
        return True

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
            except (JobCancelled, JobSkipped, JobDeferred):
                # 保留(JobDeferred)もここでは捕まえない。10秒後に投げ直したところで
                # volumeは戻っておらず、attemptだけを食い潰して失敗が確定する。
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

    async def _emit_pending(self) -> None:
        """待機列の順番を配り直す。1件が動き出す/終わるたびに後続の順番が繰り上がるので、
        当事者の行だけを配ると、残りの行が古い順番を表示したまま残る。"""
        positions = self._queue_positions()
        for job_id, position in positions.items():
            row = self._storage.get_media_job(job_id)
            if row is not None:
                await self._broadcast({"type": "job_update",
                                       "job": job_payload(row, position)})

    async def _emit(self, row: Optional[dict]) -> None:
        if row is None:
            return
        position = 0
        if row["state"] == "pending":
            position = self._queue_positions().get(row["job_id"], 0)
        await self._broadcast({"type": "job_update", "job": job_payload(row, position)})
        group_id = row.get("group_id") or ""
        if not group_id:
            return
        group = group_payload(self._storage.media_jobs_in_group(group_id))
        if group is not None:
            await self._broadcast({"type": "job_update", "job": group})
