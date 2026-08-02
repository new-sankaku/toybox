"""録画・収集・解析のすべてが通る単一のDB窓口。

`Storage` は1つのSQLite fileに対して **接続とlockを1組だけ** 持つ。methodはdomain別の
mixin(tictok/store/)へ分けてあるが、mixinは接続もlockも持たない — すべてこのclassの
self._conn / self._lock / self._read_lock を借りる。分けたのはfileの長さの問題であって、
所有者を分けたのではない。

なぜ独立classへ分けないのか:
    このclassのmethod同士は「lockを保持したまま呼ぶ/呼ばない」という暗黙契約で結合して
    いる(名前が _locked で終わるmethodは呼び出し元が self._lock を保持している前提)。
    独立classがそれぞれ接続やlockを持つ形にすると、lockの取得順とcommit境界が壊れ、
    deadlockまたは書き込みのatomicity喪失を招く。しかもその壊れ方はtestに出ない
    (deadlockは負荷とtimingに依存し、atomicity喪失は障害時にしか現れない)。
    mixinなら self は1つのままなので、契約はそのまま成立する。

lockは5本。所有者はすべてこのclassで、取得順は self._lock -> self._buf_lock の
一方向だけが存在する(他は互いに入れ子にしない):
    _lock          書き込み接続 self._conn の直列化
    _buf_lock      batch writerのbuffer(_event_buffer / _viewer_buffer / _pending_users)
    _read_lock     重い集計read専用接続 _LockedReader の直列化
    _journal_lock  耐久journalのfile handle
    _ops_fail_lock ops_events書き込み失敗の計数

分割の境界と、各mixinが負う lock 契約は、それぞれのmodule docstringに書いてある。
特に tictok/store/ingest.py(batch writerのlock区間そのもの)は、読まずに触ると事故る。

このmoduleは、分割前に tictok.storage が公開していた名前をすべてそのまま公開し続ける
(定数・schema・純粋helper)。実体は tictok.store._common にあり、ここは再exportである。
"""
import itertools
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from tictok import battle_migration, glove_migration, timemap_migration
from tictok.core import perf
from tictok.core.config import get_journal_enabled, get_log_dir

from tictok.store._common import (
    CONN_INSTRUMENTATION_VERSION,
    NON_IDENTITY_KEYS,
    OPS_ERROR,
    OPS_INFO,
    OPS_SEVERITY_ORDER,
    OPS_WARNING,
    RECORDING_REVIEW_STATES,
    REVIEW_CHECKED,
    REVIEW_CHECKING,
    REVIEW_UNCHECKED,
    SCHEMA,
    SESSION_STATUS_RESTRICTED,
    _BATTLE_CONTRIB_CACHE_MAX,
    _BATTLE_KEY_CONTRIB_DIAMONDS,
    _EVENTS_COLUMNS,
    _EVENTS_INSERT_SQL,
    _EXCLUDE_RESTRICTED,
    _EXCLUDE_RESTRICTED_NO_ALIAS,
    _LockedReader,
    _MIGRATION_BACKUP_KEY,
    _OPS_LOG_LEVELS,
    _ReadResult,
    _TIMEMAP_SELECTION_KEY,
    _SESSION_TOTALS_CTE,
    _SQLITE_FATAL_ERRORNAMES,
    _SQLITE_FATAL_MESSAGES,
    _STREAMER_TOTALS_SELECT,
    _USER_UPSERT_TTL_SECONDS,
    _VIEWERS_INSERT_SQL,
    _WRITE_BATCH_SIZE,
    _WRITE_FLUSH_INTERVAL_SECONDS,
    _coop_summary,
    _covering_recording,
    _identity_key,
    _migration_versions,
    _opponent_key,
    _session_ids_of,
    _session_row_to_dict,
    _to_int,
    _valid_owner_id,
    logger,
)
from tictok.store.maintenance import MaintenanceMixin
from tictok.store.ops_events import OpsEventsMixin
from tictok.store.ai_cache import AiCacheMixin
from tictok.store.ingest import IngestMixin
from tictok.store.sessions import SessionsMixin
from tictok.store.users import UsersMixin
from tictok.store.gifter_league import GifterLeagueMixin
from tictok.store.battles import BattlesMixin
from tictok.store.streamers import StreamersMixin
from tictok.store.analytics_store import AnalyticsMixin
from tictok.store.recordings import RecordingsMixin
from tictok.store.transcripts import TranscriptsMixin
from tictok.store.media_jobs import MediaJobsMixin
from tictok.store.settings_store import SettingsMixin

# 分割前の tictok.storage が公開していた名前。importしている側(server / collector /
# core.notify / test)を書き換えずに済ませるため、ここから再exportし続ける。
__all__ = [
    "Storage",
    "CONN_INSTRUMENTATION_VERSION",
    "NON_IDENTITY_KEYS",
    "OPS_ERROR",
    "OPS_INFO",
    "OPS_SEVERITY_ORDER",
    "OPS_WARNING",
    "RECORDING_REVIEW_STATES",
    "REVIEW_CHECKED",
    "REVIEW_CHECKING",
    "REVIEW_UNCHECKED",
    "SCHEMA",
    "SESSION_STATUS_RESTRICTED",
    "_BATTLE_CONTRIB_CACHE_MAX",
    "_BATTLE_KEY_CONTRIB_DIAMONDS",
    "_EVENTS_COLUMNS",
    "_EVENTS_INSERT_SQL",
    "_EXCLUDE_RESTRICTED",
    "_EXCLUDE_RESTRICTED_NO_ALIAS",
    "_LockedReader",
    "_MIGRATION_BACKUP_KEY",
    "_OPS_LOG_LEVELS",
    "_ReadResult",
    "_TIMEMAP_SELECTION_KEY",
    "_SESSION_TOTALS_CTE",
    "_SQLITE_FATAL_ERRORNAMES",
    "_SQLITE_FATAL_MESSAGES",
    "_STREAMER_TOTALS_SELECT",
    "_USER_UPSERT_TTL_SECONDS",
    "_VIEWERS_INSERT_SQL",
    "_WRITE_BATCH_SIZE",
    "_WRITE_FLUSH_INTERVAL_SECONDS",
    "_coop_summary",
    "_covering_recording",
    "_identity_key",
    "_migration_versions",
    "_opponent_key",
    "_session_ids_of",
    "_session_row_to_dict",
    "_to_int",
    "_valid_owner_id",
    "logger",
]


class Storage(
    MaintenanceMixin,
    OpsEventsMixin,
    AiCacheMixin,
    IngestMixin,
    SessionsMixin,
    UsersMixin,
    GifterLeagueMixin,
    BattlesMixin,
    StreamersMixin,
    AnalyticsMixin,
    RecordingsMixin,
    TranscriptsMixin,
    MediaJobsMixin,
    SettingsMixin,
):
    """単一のDB窓口。分割の理由・lockの所有と取得順はmodule docstringを参照。"""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        # 接続とlockはどちらも計測付き。SQLの実行時間と順番待ちを別々に積むためで、
        # request contextの外(collector・録画・起動sweep)では計測は素通りする。
        self._conn = sqlite3.connect(db_path, check_same_thread=False,
                                     factory=perf.TimedConnection)
        self._conn.perf_phase = "db.write_conn"
        self._conn.row_factory = sqlite3.Row
        self._lock = perf.TimedLock("db.write_wait")
        # 重い集計read専用の接続。実体は _read_connection が遅延生成し、_read_lockで
        # 直列化する(_lockとは別物 — 集計が書き込みを待たせないためにこれを分けている)。
        self._reader: Optional[_LockedReader] = None
        self._read_init_lock = threading.Lock()
        self._read_lock = perf.TimedLock("db.read_wait")
        # 書き込みバッチ用のバッファ(DB lockとは別のlockで保護)。identity_key単位の
        # upsert間引きキャッシュもここで持つ(liveの高頻度取り込みのみ対象)。
        self._buf_lock = threading.Lock()
        self._flush_cond = threading.Condition(self._buf_lock)
        self._event_buffer: list = []
        self._viewer_buffer: list = []
        self._pending_users: list = []
        self._user_cache: dict = {}
        # 終了済みBattleの窓は固定なので貢献集計を1度だけ計算してキャッシュする。
        self._battle_contrib_cache: dict = {}
        self._closed = False
        # 追記型の耐久journal。batched SQLite writerとは独立に、取り込み時点でeventをdiskへ
        # 追記する最終防波堤。writer停滞やクラッシュでもここに残り、起動時recoverで復元できる。
        self._journal_enabled = get_journal_enabled()
        self._journal_lock = threading.Lock()
        self._journal_fh = None
        self._journal_day = None
        # ops_events(Layer2)。ops_idはprocess起動ごとのtokenと連番で組み、再起動をまたいでも
        # 衝突しない。DB書き込みが失敗してもLayer1のlogにはこのidが載るので、行が無いこと自体を
        # 後から追跡できる。itertools.countの__next__はCPythonでatomicなので追加lockは不要。
        self._ops_run_token = os.urandom(4).hex()
        self._ops_seq = itertools.count(1)
        self._ops_fail_lock = threading.Lock()
        self._ops_write_failures = 0
        self._ops_first_failure_logged = False
        # ops_eventsの観測者(通知機構)。ops_eventsは障害系・session lifecycleの単一の口なので、
        # 通知のために別の計装を各所へ足す代わりに、ここへ1本ぶら下げる。
        self._ops_observer = None
        # backlog警告の間隔gate(writerスレッド専用に触るのでlock不要)。
        self._backlog_logged_at = 0.0
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA foreign_keys=ON")
            # 既定のpage cacheは2MB。DBは実測850MBあり、集計系がeventsを走査するたびに
            # page cacheから溢れてdiskへ戻っていた(events全scanが103ms→59ms)。負値はKB指定。
            self._conn.execute("PRAGMA cache_size=-131072")
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.commit()
        # 破壊的migrationの直前に退避する。glove/battleのmigrationはbattles.data_jsonを
        # in-placeで書き換え、元の値はどこにも残らない。lockの外なのは、退避が自分のread接続を
        # 開くためで、ここはまだwriter threadも起動していない起動直後の単独実行区間である。
        premigration_backup = self._backup_before_migrations()
        with self._lock:
            # 「この選別ruleでの選別は完走済み」。timemapの選別だけがこれを見る(下記)。
            timemap_selection = str(timemap_migration.SELECTION_VERSION)
            timemap_done = (
                self._get_maintenance_locked(_TIMEMAP_SELECTION_KEY) == timemap_selection)
            # 旧方式judgeのグローブcrit event(vマーカー無し)を新方式へ再判定する。
            # 冪等で、対象が無ければno-op。collectorはまだ動いていない起動時のみ安全。
            glove_stats = glove_migration.migrate_glove_events(self._conn, get_log_dir())
            if glove_stats["battles"]:
                logger.info("グローブのcrit判定をv2へ移行しました: %s", glove_stats)
            # 旧ruleでチーム戦扱いされていた個人マルチ(1:1:1)のtype/opp_score/resultを
            # 現行ruleへ再判定する。冪等で、対象が無ければno-op。
            topo_stats = battle_migration.migrate_battle_topology(self._conn)
            if topo_stats["battles"]:
                logger.info("battleの構造判定をv2へ移行しました: %s", topo_stats)
            # 旧版の時刻mapで作られた文字起こしを素材の実尺で選別する。畳む対象が無かった
            # ものは現行版と同じ時刻なので昇格させ、食い違うものだけ据え置く。冪等。
            #
            # glove/battleと違い、同じ選別ruleでは二度走らせない。据え置いた行は版1のまま
            # 残り続けるので、毎起動で同じ母集合を測り直すことになる。しかも物差し
            # (material_media_seconds)は採用集合のplaylist解析かffprobeで、1件あたり数百ms
            # かかる — writer threadを起こす前のこの区間でそれを繰り返すと、据え置きが増える
            # ほど起動が延びる。据え置いた行は再転写でしか動かず、再転写は現行版で保存する。
            if timemap_done:
                timemap_stats = {"checked": 0, "promoted": 0, "kept": 0, "skipped": "done"}
            else:
                timemap_stats = timemap_migration.migrate_timemap_version(
                    self._conn, timemap_migration.material_span)
                self._set_maintenance_locked(_TIMEMAP_SELECTION_KEY, timemap_selection)
            if timemap_stats["checked"]:
                logger.info("文字起こしの時刻map版を選別しました: %s", timemap_stats)
            pruned_ops = self._prune_ops_events_locked()
            self._set_maintenance_locked(_MIGRATION_BACKUP_KEY, _migration_versions())
            self._conn.commit()
        self.premigration_backup = premigration_backup
        self._writer = threading.Thread(
            target=self._writer_loop, name="storage-writer", daemon=True
        )
        self._writer.start()
        logger.info(
            "storageを初期化しました（db=%s）", db_path,
            extra={"event": "storage.initialized",
                   "ctx": {"path": str(Path(db_path).resolve()),
                           "ops_events_pruned": pruned_ops,
                           "journal_enabled": self._journal_enabled,
                           **self._db_space_ctx()}},
        )

    # ----- 集計read専用の接続 ------------------------------------------------------------

    def _read_connection(self) -> _LockedReader:
        """重い集計queryを流すための読み取り専用接続。

        書き込みと読み取りが1本の接続と1つのlockを共有していたため、数百msかかる集計
        (配信者cohort 640ms・profile・全体dashboard)を実行している間、collectorのevent
        書き出し(_drainは同じlockを取る)が止まっていた。WALは書き手1本と読み手複数の同時
        実行を許すので、集計だけを別接続へ逃がして本流と干渉させない。

        接続は1本で、_read_lockで直列化する。threadごとに持てば集計同士も並行になるが、
        page cacheが接続ごとに積み上がる(to_threadのpoolは数十threadあり、集計は数百MBの
        表を舐める)。集計は人の操作で走るものなので、互いに待つ側の代償の方が軽い。

        見えるのはcommit済みの内容。writerは0.2秒周期でcommitするため、通常の集計はここで
        足りる。未commitのbufferまで必要とする読み取り(Battle貢献の再構成など)は、これまで
        どおり呼び出し側が先にflush()する — flush()はwriter接続でcommitまで済ませるので、
        戻った時点でこちらからも見える。
        """
        with self._read_init_lock:
            if self._reader is None:
                conn = sqlite3.connect(
                    f"{Path(self._db_path).resolve().as_uri()}?mode=ro",
                    uri=True, check_same_thread=False, factory=perf.TimedConnection)
                conn.perf_phase = "db.read"
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA busy_timeout=5000")
                conn.execute("PRAGMA cache_size=-65536")
                self._reader = _LockedReader(conn, self._read_lock)
            return self._reader

    def close(self) -> None:
        with self._flush_cond:
            self._closed = True
            self._flush_cond.notify()
        self._writer.join(timeout=5.0)
        # 最終drainが例外を投げてもconn.close()(WAL checkpoint)は必ず走らせる。
        try:
            self._drain()
        except Exception as exc:
            logger.error(
                "close時の最終書き出しに失敗しました（buffer上の行はjournalにのみ残ります）",
                exc_info=True,
                extra={"event": "storage.final_drain_failed",
                       "ctx": self._sqlite_error_ctx(exc)},
            )
        self._close_journal()
        # ops_eventsの書き込み失敗は本流を止めないので、ここで累計を必ず1行出す。閾値を設けて
        # 「少なければ黙る」設計にすると、失敗が数件で終わった時に1行も残らず穴になる。
        with self._ops_fail_lock:
            failures = self._ops_write_failures
        logger.log(
            logging.WARNING if failures else logging.INFO,
            "storageを終了しました（ops eventの書き込み失敗: %d 件）", failures,
            extra={"event": "storage.closed",
                   "ctx": {"ops_write_failures": failures, **self._db_space_ctx()}},
        )
        # 集計read接続を先に畳む。WAL checkpointはwriter接続のcloseで走るので、読み手が
        # 残っているとcheckpointが取れずWALが切り詰められないまま終わる。
        with self._read_init_lock:
            reader, self._reader = self._reader, None
        if reader is not None:
            reader.close()
        with self._lock:
            self._conn.close()
