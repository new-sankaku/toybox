"""映像job(焼き込み / Up出力 / 再mp4化 / 音量正規化)の永続queue。

文字起こしqueueと同じ形だが、支える要求が2つ多い。

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
import re
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
                "reprocess": "bulk_reprocess", "audionorm": "bulk_audionorm",
                "pack": "bulk_pack"}
# 実行が終わったstate。pending/runningの補集合として書くと、新しいstateを足したときに
# 「終わっていないのに終了扱い」へ静かに転ぶので列挙する。
FINISHED_STATES = ("completed", "failed", "cancelled", "skipped", "interrupted")

# 専用laneで拾う種別。条件は2つとも満たすものだけ:
#   1. 人がその場で待つ1 clickの操作で、実処理が数秒で終わる
#   2. 録画にも中間fileにも書き込まない(読んで別fileを1つ出すだけ)
# 通常のworkerは既定で2本、しかも同じ録画で走っているjobがあると次を拾わない。スクショを
# その列に入れると、長い焼き込みの裏で押した1枚が数時間保存されないままになる。laneは順番
# ではなく**枠**を分ける仕組みで、順番の優先度(priority)とは別物である。
INSTANT_KINDS = ("still",)

# 画面の状態filter → 台帳のstate。Job画面のselectはこのkeyを送る。台帳を絞るのは画面では
# なくここで、「新しい200行に紛れなかった古い失敗」が0件として消えないようにする。
STATE_FILTERS = {
    "active": ("pending", "running"),
    "failed": ("failed", "interrupted"),
}

# 畳んだ表示用domain → 畳む前のkind。GROUP_DOMAINS/BULK_DOMAINSの逆引きで、対応表を
# 2つ持たない(片方だけ足すと種別filterが黙って0件になる)。
_FOLDED_TO_KIND = {domain: kind
                   for mapping in (GROUP_DOMAINS, BULK_DOMAINS)
                   for kind, domain in mapping.items()}


# 段階名から詳細を落とすための括弧。段階名は「(3/6) アイコン・絵文字を取得中（ギフト
# アイコン 12/48）」の形で、括弧の中は数frameごとに動く。段階が変わったかの判定にそのまま
# 使うと、同じ段階が数千件の履歴になる。
_STAGE_DETAIL = re.compile(r"（[^（）]*）")


def stage_phase(stage: str) -> str:
    """段階名から進行中の詳細(frame位置・件数)を落とした、段階そのものの名前。

    履歴に残すのはこちら。詳細まで含めて残すと「どの段階に何秒かけたか」ではなく
    「1秒ごとの位置log」になり、行が数千件へ膨らんで読む対象でなくなる。"""
    return _STAGE_DETAIL.sub("", stage or "").strip()


def db_kind_for_domain(domain: str) -> str:
    """画面のdomain名 → 台帳のkind。

    session_*/bulk_* は録画ごとの行を畳んだ表示専用の名前で、台帳にその文字列を持つ行は
    無い。畳む前のkind(overlay等)へ戻して引く。それ以外のdomainはkindと同じ語なのでその
    まま返す — 台帳に載らないdomain(容量scan等)は0件になるが、それが事実である。"""
    return _FOLDED_TO_KIND.get(domain, domain)


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
        # 通ってきた段階と、その段階へ入った時刻。終わったjobのstageは空にされるので、
        # 「どこで何秒かかったか / どこで落ちたか」はこれ以外に辿る先が無い。
        "stages": row.get("stages") or [],
        "pct": row.get("pct") or 0,
        "index": 0,
        "total": 1,
        # 待機中はNoneのまま渡す。queued_atで埋めると、順番待ちの時間が「実行にかかった
        # 時間」として画面に積み上がり、まだ1秒も動いていないjobが何時間もかかったように
        # 読める。DBのstarted_atも「実行を始めた時刻」なので、payloadだけ意味をずらさない。
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "message": row.get("error") or "",
        "group_id": row.get("group_id") or "",
        "queued_at": row.get("queued_at"),
        # 待機中でも「順番待ち」と「前提の復帰待ち」は別物。画面が同じ『待機中』として
        # 並べると、進まない理由が読めない。
        "not_before": row.get("not_before"),
        "filename": row.get("filename"),
        "unique_id": row.get("unique_id"),
        # 起動時sweepが自動で積んだ行。人が投げた覚えのないjobが並ぶ理由を画面が名乗れる
        # ようにする(同時実行を別枠で絞っているのもこの印)。
        "sweep": bool(row.get("sweep")),
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
    started = [r["started_at"] for r in rows if r.get("started_at")]
    queued = [r["queued_at"] for r in rows if r.get("queued_at")]
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
        # groupの開始は「最初のmemberが動き出した時刻」。1件も動いていない一括はNone
        # (=まだ所要時間が無い)で、投入時刻はqueued_atが別に名乗る。
        "started_at": min(started) if started else None,
        "finished_at": max((r.get("finished_at") or 0) for r in rows) or None,
        "queued_at": min(queued) if queued else None,
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
        # job_id -> 最後に履歴へ残した段階名。段階が変わった1回だけ追記するための目印で、
        # process内に留めてよい(再起動を跨いだ行はinterruptedになり、次の実行はclaimで
        # 履歴ごと作り直す)。
        self._last_phase: dict[str, str] = {}
        # group_id -> 最後にgroupのまとめ行を配った時刻。進捗tickでのgroup再集計を間引く。
        self._last_group_emit: dict[str, float] = {}
        # 集計済みのgroup_id。同時に終わった2件が同じ集計を二重に残さないための目印で、
        # process内に留めてよい(再起動を跨ぐと、そのgroupは既に終わっているので通らない)。
        self._summarized: set = set()

    # ===== lifecycle =====

    def start(self) -> None:
        workers = config.get_media_queue_workers()
        self._tasks = [asyncio.create_task(self._run()) for _ in range(workers)]
        instant = config.get_media_queue_instant_workers()
        self._tasks += [
            asyncio.create_task(self._run(kinds=INSTANT_KINDS, allow_busy_recording=True))
            for _ in range(instant)
        ]
        if workers > 1 or instant:
            logger.info(
                "media queue: 並列 worker %d 本（即時lane %d 本）で開始しました",
                workers, instant,
                extra={"event": "media_queue.workers_started",
                       "ctx": {"workers": workers, "instant_workers": instant,
                               "instant_kinds": list(INSTANT_KINDS)}},
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
                      params: Optional[dict] = None, sweep: bool = False) -> dict:
        row = self._storage.enqueue_media_job(
            job_id, kind, recording_id, session_id=session_id, group_id=group_id,
            title=title, priority=priority, params=params, sweep=sweep,
        )
        logger.info(
            "media queue: %s をqueueへ投入しました（recording %s）", kind, recording_id,
            extra={"event": "media_queue.enqueued",
                   "ctx": {"job_id": job_id, "kind": kind, "recording_id": recording_id,
                           "session_id": session_id, "group_id": group_id}},
        )
        self._wake.set()
        await self._emit(row)
        return row

    def _insert_many(self, specs: list) -> list:
        return [self._storage.enqueue_media_job(**spec) for spec in specs]

    async def enqueue_many(self, specs: list) -> list:
        """複数のjobを1回の投入として積む。``specs`` は ``enqueue_media_job`` のkeyword引数。

        1本ずつ ``enqueue`` を呼ぶと、投入のたびに待機列全件(list_media_jobs)とgroup全件を
        引き直すので、N本の投入が**N²のquery**になる。しかもそれは同期queryなのでevent loop
        の上で起きる — 配信者まるごとの一括(数百本)を積む間、収集も他の画面も止まっていた。
        行の書き込みはthreadでまとめ、配信は最後に1回だけ行う。

        途中経過を配らないことで画面が失うものは無い。``_emit_pending`` が待機中の行を
        **全件**、正しい順番付きで配り直すため、受け取る最終状態は1本ずつ配ったときと同じ
        である(投入中にworkerが拾った行は、workerの開始側が自分で配る)。"""
        if not specs:
            return []
        rows = await asyncio.to_thread(self._insert_many, specs)
        logger.info(
            "media queue: %d件をまとめてqueueへ投入しました", len(rows),
            extra={"event": "media_queue.enqueued_many",
                   "ctx": {"count": len(rows),
                           "kinds": sorted({r["kind"] for r in rows}),
                           "group_ids": sorted({r.get("group_id") or "" for r in rows})}},
        )
        self._wake.set()
        await self._emit_pending()
        for group_id in dict.fromkeys(row.get("group_id") or "" for row in rows):
            await self._emit_group(group_id, gate=False)
        return rows

    def pending_for(self, kind: str, recording_id: int) -> Optional[dict]:
        return self._storage.pending_media_job_for(kind, recording_id)

    async def promote(self, job_id: str, priority: int = 0) -> bool:
        """既に待機列に居る行の順番を上げる。人が今その1本を待っている場合に使う。

        順番が変わるのは当事者の行だけではないので、待機列は全件配り直す(``_emit_pending``)。
        既に実行中・既に同じ優先度の行では何もせずFalseを返す。"""
        if not await asyncio.to_thread(self._storage.promote_media_job, job_id, priority):
            return False
        await self._emit_pending()
        return True

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

    def _pending_in_order(self) -> list:
        """待機中の行を、workerが次に拾う順(priority DESC, queued_at)に並べたもの。
        ここが実際の実行順と食い違うと、待機列の表示が嘘になる。"""
        pending = [r for r in self._storage.list_media_jobs(1000)
                   if r["state"] == "pending"]
        pending.sort(key=lambda r: (-(r.get("priority") or 0), r.get("queued_at") or 0))
        return pending

    def _queue_positions(self) -> dict:
        """{job_id: 順番(1始まり)}。"""
        return {r["job_id"]: i + 1 for i, r in enumerate(self._pending_in_order())}

    def list_jobs(self, limit: int = 200, *, states=None, kinds=None, job_id=None) -> list:
        """単体jobと、session一括投入をgroupへ畳んだjobの一覧。

        ``states`` / ``kinds`` / ``job_id`` は台帳を引く時点の絞り込み。畳んだgroup行はgroup
        全件から組み直すので、条件に一致した明細1件からでもその一括の全体像が出る(逆に、
        group行自体は条件に一致しないことがある — 一致した明細を消さないのは画面側の仕事)。"""
        rows = self._storage.list_media_jobs(limit, states=states, kinds=kinds, job_id=job_id)
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

    async def _run(self, kinds: Optional[tuple] = None,
                   allow_busy_recording: bool = False) -> None:
        """1本のworker。``kinds`` を渡すとその種別だけを拾う専用lane(:data:`INSTANT_KINDS`)。"""
        poll = config.get_media_queue_poll_seconds()
        while not self._stopping:
            # 取得と同時にrunningへ落とす。workerが複数居るとき、選んでから開始を書くまでの
            # 隙間に別のworkerが同じ行を拾えてしまう。
            job = self._storage.claim_next_pending_media_job(
                sweep_limit=config.get_media_queue_sweep_concurrency(),
                kinds=kinds, allow_busy_recording=allow_busy_recording)
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
                "media jobを取り消しました: %s（%s）", job_id, job["kind"],
                extra={"event": "media_queue.job_cancelled",
                       "ctx": {"job_id": job_id, "kind": job["kind"],
                               "recording_id": job.get("recording_id")}},
            )
            self._storage.finish_media_job(job_id, "cancelled", error="取り消しました。")
        except JobSkipped as exc:
            logger.info(
                "media jobをskipしました: %s（%s）%s", job_id, job["kind"], exc,
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
                "media jobが失敗しました: %s（%s）", job_id, job["kind"],
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
            self._last_phase.pop(job_id, None)
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
                "media jobの待機を打ち切りました: %s（%s）%s", job_id, job["kind"], exc.reason,
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
            "media jobを %.0fs 保留します: %s（%s）%s", wait, job_id, job["kind"], exc.reason,
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
                    "media jobの %d/%d 回目が失敗したため %.1fs 後に再試行します: %s（%s）",
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
        # 段階が変わった時だけ履歴へ1件足す。詳細(frame位置)は毎回動くので、それを落とした
        # 段階名で比べる。空の段階名は履歴に残さない — 終端でstageを消す書き込みと、まだ
        # 段階名を持たない開始直後が、中身の無い1件として並ぶ。
        phase = stage_phase(stage)
        changed = bool(phase) and self._last_phase.get(job_id) != phase
        if changed:
            self._last_phase[job_id] = phase
        self._storage.update_media_job_progress(
            job_id, pct, stage, phase=phase if changed else None)
        # 進捗tickはjob 1本で数十〜数百回鳴る。当事者の行は毎回配り、groupのまとめ行だけを
        # 間引く(group全件のqueryを伴うのはそちらだけである)。
        await self._emit(self._storage.get_media_job(job_id), gate_group=True)

    async def _emit_pending(self) -> None:
        """待機列の順番を配り直す。1件が動き出す/終わるたびに後続の順番が繰り上がるので、
        当事者の行だけを配ると、残りの行が古い順番を表示したまま残る。

        並べ替えに使った行をそのまま配る。以前はjob_idだけを取り出してから1件ずつ
        get_media_jobで引き直しており、待機N件につきN回の余計なqueryを、jobの開始と
        終了のたびに払っていた。"""
        for position, row in enumerate(self._pending_in_order(), start=1):
            await self._broadcast({"type": "job_update",
                                   "job": job_payload(row, position)})

    async def _emit_group(self, group_id: str, *, gate: bool) -> None:
        """一括投入のまとめ行を配る。

        まとめ行はgroup全件をDBから引き直して作るので、memberの進捗tickごとに呼ぶと、
        数百本のgroupでは1%動くたび数百行のqueryがevent loop上で走る。``gate`` を立てた
        呼び出しは最小間隔で間引く — 間引いた更新は捨てるが、次の配信が最新のgroup状態を
        そのまま運ぶので、表示が古いまま固定されることはない。

        状態遷移(投入・開始・終了・取り消し)の呼び出しは ``gate=False`` で必ず通す。
        そこを間引くと、終わったgroupが終わったように見えない時間が生まれる。"""
        if not group_id:
            return
        now = time.monotonic()
        if gate:
            last = self._last_group_emit.get(group_id)
            if (last is not None
                    and now - last < config.get_media_job_group_emit_min_interval_seconds()):
                return
        group = group_payload(self._storage.media_jobs_in_group(group_id))
        if group is None:
            return
        if group["state"] in FINISHED_STATES:
            # 終わったgroupの目印は残さない。残すと、requeueで動き出したときの初回が
            # 間引かれ、再開が画面に出ないまま進む。台帳の伸びも同時に止まる。
            self._last_group_emit.pop(group_id, None)
        else:
            self._last_group_emit[group_id] = now
        await self._broadcast({"type": "job_update", "job": group})

    async def _emit(self, row: Optional[dict], *, gate_group: bool = False) -> None:
        if row is None:
            return
        position = 0
        if row["state"] == "pending":
            position = self._queue_positions().get(row["job_id"], 0)
        await self._broadcast({"type": "job_update", "job": job_payload(row, position)})
        await self._emit_group(row.get("group_id") or "", gate=gate_group)
