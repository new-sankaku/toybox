"""process全体で1つしかない物と、その組み上げ順。

serverの起動はここで起きる: logの初期化 -> Storage -> 単一instance lock -> 起動時復旧 ->
設定 -> 録画dir解決 -> avatar/gift cache -> 通知 -> collector manager。この順序は
それぞれの行のcommentが理由を持っているので、並べ替えないこと。

**この層は tictok.api の他moduleを一切importしない。** 下から上への参照が無いことが、
route moduleを好きな順で読み込めることの根拠になっている。

module levelの名前(``RECORD_DIR`` / ``storage`` / ``settings`` など)は、testが
``monkeypatch.setattr(runtime, ...)`` で差し替える対象でもある。参照する側は
``from ... import`` で束ねずに ``runtime.RECORD_DIR`` と呼び出し時に引くこと —
束ねると差し替えが自分のbindingへ届かず、patchが黙って効かなくなる。
"""

import asyncio
import atexit
import logging
import mimetypes
import re
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from fastapi import HTTPException, WebSocket
from tictok.paths import PROJECT_ROOT
from tictok.core.logging_setup import setup_logging
from tictok.core.logctx import log_context
from tictok.core.jsonio import js_safe
from tictok.media.asset_prefetch import AssetPrefetcher
from tictok.media.avatar_pool import AvatarPool
from tictok.media.avatar_proxy import AvatarProxy
from tictok.media.emote_pool import EmotePool
from tictok.media.gift_icons import GiftIconCache
from tictok.core.config import (ConfigError, get_asset_prefetch_concurrency,
    get_asset_prefetch_enabled, get_asset_prefetch_queue_size,
    get_asset_prefetch_rate_per_second, get_avatar_fetch_attempts,
    get_avatar_fetch_backoff_seconds, get_avatar_fetch_concurrency, dotenv_summary,
    get_db_path, get_job_retention_seconds, get_websocket_send_timeout_seconds,
    validate_env)
from tictok.collect.manager import CollectorManager
from tictok.core import ops_labels
from tictok.core.process_lock import ProcessLock, ProcessLockError
from tictok.core import layout
from tictok.record.recorder import migrate_sidecars
from tictok.record.media_queue import JobSkipped
from tictok.core import cancel
from tictok.core.settings import Settings
from tictok.core.notify import Notifier
from tictok.storage import Storage


# Configure logging before anything below it runs. The module-level Storage,
# the single-instance lock, journal recovery and the schema migration all execute
# at import time; configured any later, their output never reaches the log files.
setup_logging(profile="server")

logger = logging.getLogger("tictok.server")

BASE_DIR = PROJECT_ROOT
STATIC_DIR = BASE_DIR / "static"
# Windowsのmimetypesはregistry(HKCR)を読むため .js が text/plain に化ける環境がある。
# 現状のclassic scriptは動くが、module scriptはMIME厳格checkで実行拒否されるので、
# registryに依らずRFC 9239の値へ固定する。
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
# Resolved at startup from settings (see init below). A UI change to either dir
# therefore takes effect on the next server start, not mid-run.
# RECORD_DIR = working dir (SSD): live recording, HLS, avatar/gift caches.
# FINAL_DIR  = final dir (HDD): completed mp4s relocate here (== RECORD_DIR when unset).
RECORD_DIR: Path
FINAL_DIR: Path
# Roots a stored recording path is allowed to resolve under (both dirs, deduped).
_RECORD_ROOTS: list[Path] = []
UNIQUE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.]{1,64}$")
# Number of recent finished sessions averaged for the monitor page's
# "past streams" comparison (今回 / 前回 / 平均 / 自己Best).
HISTORY_COMPARE_LIMIT = 5
# A finished recording's bytes are immutable, so playback can cache them privately;
# a still-recording file keeps changing and must not be cached.
RECORDING_CACHE_MAX_AGE_SECONDS = 86400
# 容量samplerが「採る時期か」を確認しに来る間隔。実際に採るかは前回sampleからの経過で
# 決まる(capacity_sample_interval_hours)ので、これは設定ではなく確認の粒度である。
# 短くしても採取が増えるわけではなく、設定変更が反映されるまでの遅れが縮むだけ。
CAPACITY_SAMPLER_TICK_SECONDS = 900
# 画面と回帰へ渡すsampleの上限。policyではなく描画量の上限なので設定にはしない
# (日次sampleなら400件で13か月ぶんになる)。
CAPACITY_HISTORY_LIMIT = 400


@asynccontextmanager
async def _job_ops(domain: str, recording_id: Optional[int], **detail):
    """Bracket a long-running post-processing job (burn-in, upscale, transcription)
    with ops_events transitions and a job id.

    These jobs run across worker threads and ffmpeg sub-processes, so a single bound
    ``job_id`` is what joins their log lines to the Layer2 row. Recording the pair
    here rather than inside the job modules keeps those modules free of a Storage
    handle, which they cannot import without a cycle through this module.
    """
    job_id = secrets.token_hex(4)
    started = time.monotonic()
    with log_context(job_id=job_id, recording_id=recording_id):
        storage.record_ops_event(
            logger, f"{domain}.job_started", f"{ops_labels.job_domain_label(domain)}を開始しました",
            recording_id=recording_id, job_id=job_id, detail=detail,
        )
        try:
            yield job_id
        except cancel.JobCancelled:
            # JobCancelledはBaseExceptionなので下のexcept Exceptionには入らない。ここで拾わ
            # ないと、job_startedだけが残り終端の遷移が無いops_events行になる。取り消しは
            # 正常な終わり方なのでseverityは既定(info)のまま — errorにするとnavのbadgeが
            # 点き、userが自分で取り消したのに障害として提示される。
            storage.record_ops_event(
                logger, f"{domain}.job_cancelled",
                f"{ops_labels.job_domain_label(domain)}を取り消しました",
                recording_id=recording_id, job_id=job_id,
                duration_ms=(time.monotonic() - started) * 1000, detail=detail,
            )
            raise
        except JobSkipped as exc:
            # 作る物が無くて何も出力しなかった、という正常な終わり方。job_failedにすると
            # severity=errorでnavのbadgeが点き、入力の性質が障害として提示される。
            storage.record_ops_event(
                logger, f"{domain}.job_skipped",
                f"{ops_labels.job_domain_label(domain)}は対象がなく何も出力しませんでした: {exc}",
                recording_id=recording_id, job_id=job_id,
                duration_ms=(time.monotonic() - started) * 1000,
                detail={**detail, "reason": str(exc)},
            )
            raise
        except Exception as exc:
            storage.record_ops_event(
                logger, f"{domain}.job_failed",
                f"{ops_labels.job_domain_label(domain)}に失敗しました: {exc}",
                severity="error", recording_id=recording_id, job_id=job_id,
                duration_ms=(time.monotonic() - started) * 1000,
                detail={**detail, "error": type(exc).__name__}, exc_info=True,
            )
            raise
        storage.record_ops_event(
            logger, f"{domain}.job_completed", f"{ops_labels.job_domain_label(domain)}が完了しました",
            recording_id=recording_id, job_id=job_id,
            duration_ms=(time.monotonic() - started) * 1000, detail=detail,
        )


class EventHub:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def register(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
            total = len(self._connections)
        logger.info(
            "websocketのclientが接続しました（合計 %d）", total,
            extra={"event": "http.websocket_connected", "ctx": {"connections": total}},
        )

    async def unregister(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
            total = len(self._connections)
        logger.info(
            "websocketのclientが切断しました（合計 %d）", total,
            extra={"event": "http.websocket_disconnected", "ctx": {"connections": total}},
        )

    async def _send_one(self, connection: WebSocket, payload: dict,
                        timeout: float, message_type) -> Optional[str]:
        """1接続へ送る。届いたらNone、駄目だった理由("timeout"/"error")を返す。

        上限を設けるのは、埋まった送信bufferへのsendが相手の受信を待って返らないため。
        待つ側はbroadcast本体で、そこにはcollectorのevent処理が乗っている。"""
        try:
            if timeout > 0:
                await asyncio.wait_for(connection.send_json(payload), timeout)
            else:
                await connection.send_json(payload)
        except asyncio.TimeoutError:
            logger.debug(
                "websocket接続への送信が%.1f秒で終わらないため切り離します", timeout,
                extra={"event": "http.websocket_send_timeout",
                       "ctx": {"message_type": message_type, "timeout_seconds": timeout}},
            )
            return "timeout"
        except Exception:
            logger.debug(
                "応答しないwebsocket接続を切り離します", exc_info=True,
                extra={"event": "http.websocket_send_failed",
                       "ctx": {"message_type": message_type}},
            )
            return "error"
        return None

    async def _close_quietly(self, connection: WebSocket, timeout: float) -> None:
        """時間切れで切り離した接続を実際に閉じる。

        集合から外すだけでは、生きているtabが更新を受け取らないまま「接続中」を表示し続ける。
        閉じればbrowserのoncloseが張り直す(static/common.js)。閉じる操作自体も詰まった
        transportの上を通るので、同じ上限で縛って結果は問わない。"""
        try:
            if timeout > 0:
                await asyncio.wait_for(connection.close(), timeout)
            else:
                await connection.close()
        except Exception:
            pass

    async def broadcast(self, message: dict) -> None:
        """Push one update to every connected page.

        A send that raises means that client missed this update; it is dropped here and
        the browser reconnects on its own, so the individual failure is degradation
        rather than loss. The per-connection reason stays at debug (a closing tab
        produces one routinely) while the fact that a live update was lost is reported
        once per broadcast at warning.

        送信は接続ごとに並行で行う。直列に await していた頃は、応答しないclient 1枚が
        後続の全clientと**呼び出し元**(収集中のcollector、job台帳)を自分の詰まりに巻き込んで
        いた。1接続あたりの上限も同じ理由で要る — 並行にしただけでは、broadcast全体が
        最も遅い1接続の速度に張り付く。
        """
        async with self._lock:
            connections = list(self._connections)
        if not connections:
            return
        # WSはHTTPのresponse classを通らないので、int64の桁落ち対策はここで掛ける。
        # 送信前に1回だけ変換し、接続ごとに繰り返さない。
        payload = js_safe(message)
        message_type = message.get("type")
        timeout = get_websocket_send_timeout_seconds()
        results = await asyncio.gather(*(
            self._send_one(connection, payload, timeout, message_type)
            for connection in connections
        ))
        dead = [connection for connection, reason in zip(connections, results) if reason]
        if not dead:
            return
        timed_out = [connection for connection, reason in zip(connections, results)
                     if reason == "timeout"]
        # 時間切れのtransportは生きたまま詰まっていることがある。集合から外すだけでは
        # そのtabが黙って更新を失い続けるので、閉じて張り直させる。
        if timed_out:
            await asyncio.gather(*(
                self._close_quietly(connection, timeout) for connection in timed_out
            ))
        async with self._lock:
            for connection in dead:
                self._connections.discard(connection)
            total = len(self._connections)
        logger.warning(
            "broadcast中に到達できないwebsocket clientを %d件 切り離しました（うち時間切れ %d件、合計 %d）",
            len(dead), len(timed_out), total,
            extra={"event": "http.websocket_clients_dropped",
                   "ctx": {"dropped": len(dead), "timed_out": len(timed_out),
                           "connections": total, "message_type": message_type}},
        )


class JobRegistry:
    """実行中/直近終了した長時間jobの台帳。

    Progress used to live only in the browser: the page registered a callback when the
    button was clicked, so a reload threw the registration away and neither completion nor
    failure ever arrived — the job kept running invisibly. The authoritative state is here
    instead, and a connecting websocket is handed the whole snapshot, so a reloaded (or
    second) page picks the running job back up.

    Finished jobs linger for a retention window so a reload immediately after completion
    still shows the outcome rather than an empty list, which reads as "nothing happened".
    """

    def __init__(self, broadcast) -> None:
        self._broadcast = broadcast
        self._jobs: dict[str, dict] = {}

    def _prune(self) -> None:
        cutoff = time.time() - get_job_retention_seconds()
        for job_id, job in list(self._jobs.items()):
            if job["state"] != "running" and (job.get("finished_at") or 0) < cutoff:
                del self._jobs[job_id]

    async def start(self, job_id: str, domain: str, title: str, *,
                    recording_id: Optional[int] = None,
                    session_id: Optional[int] = None, total: int = 1) -> dict:
        self._prune()
        job = {
            "job_id": job_id, "domain": domain, "title": title,
            "recording_id": recording_id, "session_id": session_id,
            "state": "running", "stage": "", "pct": 0,
            "index": 0, "total": total,
            "started_at": time.time(), "finished_at": None, "message": "",
        }
        self._jobs[job_id] = job
        await self._broadcast({"type": "job_update", "job": dict(job)})
        return job

    async def progress(self, job_id: str, pct: int, *, stage: Optional[str] = None,
                       index: Optional[int] = None) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        pct = max(0, min(100, int(pct)))
        if stage is not None:
            job["stage"] = stage
        if index is not None:
            job["index"] = index
        # The per-frame callbacks fire far more often than the percentage changes; only
        # a real change is worth a broadcast to every connected page.
        if job["pct"] == pct and stage is None and index is None:
            return
        job["pct"] = pct
        await self._broadcast({"type": "job_update", "job": dict(job)})

    async def finish(self, job_id: str, state: str, *, message: str = "") -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job["state"] = state
        job["message"] = message
        job["finished_at"] = time.time()
        if state == "completed":
            job["pct"] = 100
        await self._broadcast({"type": "job_update", "job": dict(job)})

    def snapshot(self) -> list:
        self._prune()
        return [dict(job) for job in
                sorted(self._jobs.values(), key=lambda j: j["started_at"])]


hub = EventHub()
jobs = JobRegistry(hub.broadcast)
# 走っている意味検索buildのtask。asyncioはrunning taskを強参照しないため、ここで
# 持っていないとGCがbuildを黙って回収し得る。
_semantic_build_tasks: set = set()


@asynccontextmanager
async def _tracked_job(domain: str, title: str, *, recording_id: Optional[int] = None,
                       session_id: Optional[int] = None, total: int = 1):
    """Register a job so its progress survives a browser reload, and always mark it
    finished — a failure that left the entry ``running`` would be a spinner nothing ever
    clears, which is the very symptom this replaces."""
    job_id = secrets.token_hex(4)
    await jobs.start(job_id, domain, title, recording_id=recording_id,
                     session_id=session_id, total=total)
    try:
        yield job_id
    except HTTPException as exc:
        await jobs.finish(job_id, "failed", message=str(exc.detail))
        raise
    except Exception as exc:
        await jobs.finish(job_id, "failed", message=str(exc))
        raise
    await jobs.finish(job_id, "completed")


# The .env load happens while config is first imported, which is before any log
# handler exists (logging_setup imports config), so it reports itself here instead.
logger.info(
    "環境設定fileを読み込みました（存在=%s 適用=%d件）",
    dotenv_summary()["present"], dotenv_summary()["applied"],
    extra={"event": "process.dotenv_loaded", "ctx": dotenv_summary()},
)
# 読み込んだ環境変数が値として使えるかを、ここで全件まとめて確かめる。個々のgetterは呼ばれた
# 時点で例外にするが、値の多くはmedia jobの実行中にしか読まれないので、.envの1文字の誤りが
# 数時間後のjob失敗として現れる(config.validate_envのdocstring)。
# lockより**前**に置くのは、設定が誤っていて起動できないprocessが、その手前でinstance lockと
# cleanup_stale_sessionsを通ってしまうと、先に動いているprocessのlive sessionを畳んでから
# 死ぬため。読むだけの検査なので、この位置なら何も壊さずに引き返せる。
try:
    validate_env()
except ConfigError as exc:
    logger.error(
        "起動できません: %s", exc, exc_info=True,
        extra={"event": "process.config_env_invalid_startup"},
    )
    raise SystemExit(1)
_startup_started = time.perf_counter()
storage = Storage(get_db_path())
# Acquire the single-instance lock before cleanup_stale_sessions() — that call
# finalizes every connecting/connected session unconditionally, so a second
# process starting here would otherwise terminate the first process's live
# session and both would then collect the same rooms in parallel.
instance_lock = ProcessLock(get_db_path() + ".lock")
try:
    instance_lock.acquire()
except ProcessLockError as exc:
    logger.error(
        "起動できません: %s", exc, exc_info=True,
        extra={"event": "process.instance_lock_conflicted",
               "ctx": {"path": get_db_path() + ".lock"}},
    )
    raise SystemExit(1)
atexit.register(instance_lock.release)
logger.info(
    "単一instanceのlockを取得しました",
    extra={"event": "process.instance_lock_acquired",
           "ctx": {"path": get_db_path() + ".lock"}},
)
# batched writerの停滞/クラッシュ/再起動でbuffer滞留分が失われても、取り込み時にdiskへ
# 追記した耐久journalから欠損eventを復元する。stale finalizeより前に走らせ、復元済みeventで
# stats/bucketが再構成された状態にする。
_journal_summary = storage.recover_from_journal()
_stale_sessions = storage.cleanup_stale_sessions()
# cleanup_stale_sessionsが長らくbucketを作らなかった時代のsessionを埋める。回収済みの行は
# もうcleanupの対象条件(connecting/connected/reconnecting)に入らないので、上の修正だけでは
# 過去分が永久に欠けたままになる。
_backfilled_buckets = storage.backfill_missing_buckets()
_stale_recordings = storage.mark_stale_recordings()
# One line for the whole crash-recovery step. Each call already reports its own
# anomalies; this states the outcome and its cost, which is what tells a "why did the
# server take a minute to come up" question apart from a "what did it repair" one.
storage.record_ops_event(
    logger,
    "process.startup_recovery_completed",
    "起動時の復旧: journalから {sessions}件のsessionを復元（event +{events}件、"
    "viewer +{viewers}件）、残っていた {stale_sessions}件のsessionを確定、"
    "{stale_recordings}件の録画を中断扱いにしました"
    "（bucketを補完したsession {backfilled}件）".format(
        stale_sessions=_stale_sessions, stale_recordings=_stale_recordings,
        backfilled=_backfilled_buckets, **_journal_summary
    ),
    duration_ms=round((time.perf_counter() - _startup_started) * 1000.0, 1),
    detail={
        "journal_sessions": _journal_summary["sessions"],
        "journal_events": _journal_summary["events"],
        "journal_viewers": _journal_summary["viewers"],
        "stale_sessions": _stale_sessions,
        "stale_recordings": _stale_recordings,
        "backfilled_bucket_sessions": _backfilled_buckets,
    },
)
settings = Settings(storage)
# The record dirs are UI-configurable settings; resolve them before anything roots off
# them (sidecar migration, avatar/gift caches, the recorder). settings.get returns the
# DB value if set, else the env var, else the default. FINAL_DIR falls back to the
# working dir when unset (no split; completed recordings are not relocated).
RECORD_DIR = Path(settings.get("record_dir")).resolve()
_final_setting = settings.get("record_dir_final")
FINAL_DIR = Path(_final_setting).resolve() if _final_setting else RECORD_DIR
_RECORD_ROOTS = [RECORD_DIR] if FINAL_DIR == RECORD_DIR else [RECORD_DIR, FINAL_DIR]
# 録画横断のpool(avatars/emotes/gift_icons)はwork rootにしか存在しない。書く側(下のcache)と
# 読む側(焼き込み)が同じ値を使うよう、serverが解決した実物をlayoutへ渡す。
layout.set_pool_root(RECORD_DIR)
# 素材を探すrootも、serverが解決した実物を渡す(推測させない)。移送が片方だけ済んだ録画で、
# mp4のrootに素材が無くてももう一方を見に行けるようにするため。
layout.set_record_roots(_RECORD_ROOTS)
# Relocate sidecars older recordings wrote next to the .mp4 into per-folder .sidecars/,
# so each recordings root holds only the .mp4 files. Run on both roots (idempotent).
_migrated_sidecars = sum(migrate_sidecars(_root) for _root in _RECORD_ROOTS)
logger.info(
    "録画directoryを解決しました（work=%s final=%s, sidecar %d件を移行）",
    RECORD_DIR, FINAL_DIR, _migrated_sidecars,
    extra={"event": "process.record_dirs_resolved",
           "ctx": {"path": str(RECORD_DIR), "final_path": str(FINAL_DIR),
                   "split": FINAL_DIR != RECORD_DIR,
                   "sidecars_migrated": _migrated_sidecars}},
)
avatar_pool = AvatarPool(
    cache_dir=layout.avatar_pool_dir(),
    legacy_dir=layout.pool_root() / layout.AVATAR_POOL_DIRNAME / "commenter",
    concurrency=get_avatar_fetch_concurrency(),
    attempts=get_avatar_fetch_attempts(),
    backoff_seconds=get_avatar_fetch_backoff_seconds(),
)
avatar_proxy = AvatarProxy(cache_dir=layout.pool_root() / layout.AVATAR_POOL_DIRNAME, pool=avatar_pool)
gift_icons = GiftIconCache(cache_dir=layout.gift_icon_pool_dir())
emote_pool = EmotePool(cache_dir=layout.emote_pool_dir())
# 焼き込みassetの先行取得。event着信時にpoolへ落としておき、焼き込みをcache hitで済ませる。
# 無効時はNoneのまま渡す(collector側は未接続として扱い、capture時のpool保存は行われない)。
# workerはevent loopが要るのでlifespanで起こす(``startup.py``)。
asset_prefetch = (
    AssetPrefetcher(
        gift_icons=gift_icons,
        avatar_pool=avatar_pool,
        emote_pool=emote_pool,
        concurrency=get_asset_prefetch_concurrency(),
        queue_size=get_asset_prefetch_queue_size(),
        rate_per_second=get_asset_prefetch_rate_per_second(),
    )
    if get_asset_prefetch_enabled()
    else None
)
# 通知(webhook)。ops_eventsは障害系とsession lifecycleの単一の口なので、そこへ観測者として
# 1本ぶら下げるだけで切断・録画停止・再接続打ち切り・LIVE開始が揃う。coin rateとBattle開始は
# ops_eventsに乗らないためcollectorから直接渡す。送信はここでは行わず、lifespanで起こす
# worker taskがqueue越しに行う(通知の失敗が収集・録画を止めないため)。
notifier = Notifier(storage, settings)
storage.set_ops_observer(notifier.on_ops_event)
manager = CollectorManager(
    broadcast=hub.broadcast, storage=storage, settings=settings,
    gift_icons=gift_icons, avatar_proxy=avatar_proxy,
    asset_prefetch=asset_prefetch, notifier=notifier,
)


# 一括転写のworkerは1本(STT自体がprocess内で直列化されている)。queueの実体はDB側にあり、
# processが落ちても投入内容は残る。


def _missing_record_roots() -> list:
    """今この瞬間に見えていない record root。

    外付けHDDがbusから落ちる・network driveが切れると、rootごと消える。実測(2026-07-24
    03:48)では一括再mp4化の最中にfinal dirが消え、書き込み中のffmpegが-22で死に、10秒後の
    retryは「.tsが見つかりません」で即failedになった。復帰後も誰も拾い直さないため、
    録画は書きかけのmp4を指したまま残った。これはfailedではなく待つべき事象である。"""
    return [str(root) for root in _RECORD_ROOTS if not root.is_dir()]


def _normalize_unique_id(raw: str) -> str:
    unique_id = raw.strip().lstrip("@").strip()
    if not UNIQUE_ID_PATTERN.match(unique_id):
        raise HTTPException(
            status_code=422,
            detail="TikTok IDの形式が不正です。英数字・'_'・'.' のみ使用できます。",
        )
    return unique_id


def _get_collector(unique_id: str):
    collector = manager.get(unique_id)
    if collector is None:
        raise HTTPException(status_code=404, detail=f"@{unique_id} は監視対象に存在しません。")
    return collector


def _get_session_or_404(session_id: int) -> dict:
    session = storage.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} が見つかりません。")
    return session
