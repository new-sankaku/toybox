import json
import logging
import sqlite3
import threading
import time
from typing import Optional

from tictok import analytics

logger = logging.getLogger("tictok.storage")

# 書き込みは単一writerスレッドでバッチ化する。add_event/add_viewer_sampleはキュー投入で
# 即returnし、writerがN件または一定間隔でexecutemany+1commitへまとめる。
_WRITE_BATCH_SIZE = 50
_WRITE_FLUSH_INTERVAL_SECONDS = 0.2
# 同一identity_keyの属性が変わらない限り、この秒数はusers表のupsertを間引く(live取り込みのみ)。
_USER_UPSERT_TTL_SECONDS = 60.0
# 1戦のBattle貢献者を「主力貢献者」とみなすcoin(diamond)下限。この閾値以上を投げた
# 貢献者を1戦ごとに数え、過去全Battleの平均人数を出す。
_BATTLE_KEY_CONTRIB_DIAMONDS = 100

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unique_id TEXT NOT NULL,
    room_id TEXT,
    status TEXT NOT NULL,
    started_at REAL NOT NULL,
    ended_at REAL,
    note TEXT NOT NULL DEFAULT '',
    bucket_seconds INTEGER NOT NULL,
    stats_json TEXT NOT NULL DEFAULT '{}',
    owner_nickname TEXT,
    owner_avatar TEXT,
    league TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_unique_id ON sessions(unique_id);
CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions(started_at);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    time REAL NOT NULL,
    create_time REAL,
    kind TEXT NOT NULL,
    user_id TEXT,
    user_unique_id TEXT,
    user_nickname TEXT,
    identity_key TEXT,
    text TEXT,
    gift_name TEXT,
    gift_count INTEGER,
    diamonds INTEGER,
    gift_image TEXT,
    gift_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, kind);
CREATE INDEX IF NOT EXISTS idx_events_session_kind_time ON events(session_id, kind, time);
CREATE TABLE IF NOT EXISTS users (
    identity_key TEXT PRIMARY KEY,
    user_id TEXT,
    unique_id TEXT,
    nickname TEXT,
    avatar TEXT,
    fans_level INTEGER NOT NULL DEFAULT 0,
    gifter_level INTEGER NOT NULL DEFAULT 0,
    gifter_badge TEXT NOT NULL DEFAULT '',
    member_badge TEXT NOT NULL DEFAULT '',
    first_seen REAL,
    last_seen REAL
);
CREATE TABLE IF NOT EXISTS buckets (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    start INTEGER NOT NULL,
    gifts INTEGER NOT NULL,
    diamonds INTEGER NOT NULL,
    comments INTEGER NOT NULL,
    likes INTEGER NOT NULL,
    joins INTEGER NOT NULL,
    follows INTEGER NOT NULL,
    shares INTEGER NOT NULL,
    viewers INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_buckets_session ON buckets(session_id);
CREATE TABLE IF NOT EXISTS markers (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    time REAL NOT NULL,
    kind TEXT NOT NULL,
    label TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_markers_session ON markers(session_id);
CREATE TABLE IF NOT EXISTS battles (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    battle_id INTEGER NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_battles_session ON battles(session_id);
CREATE TABLE IF NOT EXISTS collab_windows (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    channel_id TEXT,
    start REAL NOT NULL,
    end REAL,
    guests_max INTEGER NOT NULL DEFAULT 0,
    data_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_collab_session ON collab_windows(session_id);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    unique_id TEXT NOT NULL,
    path TEXT NOT NULL,
    filename TEXT NOT NULL,
    quality TEXT,
    status TEXT NOT NULL,
    error TEXT,
    started_at REAL NOT NULL,
    ended_at REAL,
    bytes INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_recordings_session ON recordings(session_id);
CREATE TABLE IF NOT EXISTS monitored_targets (
    unique_id TEXT PRIMARY KEY,
    added_at REAL NOT NULL,
    record_video INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS transcripts (
    recording_id INTEGER PRIMARY KEY REFERENCES recordings(id) ON DELETE CASCADE,
    language TEXT,
    model TEXT,
    text TEXT NOT NULL DEFAULT '',
    segments_json TEXT NOT NULL DEFAULT '[]',
    duration REAL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS viewer_samples (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    time REAL NOT NULL,
    create_time REAL,
    viewers INTEGER NOT NULL,
    total_viewers INTEGER,
    anonymous INTEGER
);
CREATE INDEX IF NOT EXISTS idx_viewer_samples_session ON viewer_samples(session_id);
CREATE TABLE IF NOT EXISTS analytics_session_cache (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    version INTEGER NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    computed_at REAL NOT NULL,
    PRIMARY KEY (session_id, kind)
);
"""

def _session_row_to_dict(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["stats"] = json.loads(item.pop("stats_json"))
    if "bucket_peak_viewers" in item:
        # stats_jsonのviewersは最終値。最大同接は収集中に保持したviewers_peakを使い、
        # それが無い旧sessionはbucketsのMAXから復元する(それも無ければ最終値)。
        bucket_peak = item.pop("bucket_peak_viewers")
        item["stats"]["viewers_peak"] = (
            item["stats"].get("viewers_peak")
            or bucket_peak
            or item["stats"].get("viewers", 0)
            or 0
        )
    return item


def _identity_key(user_id, unique_id, nickname) -> str:
    """同一User判定の不変ID優先フォールバック: 数値user_id -> @unique_id -> nickname。
    events.identity_key(SQL側のCOALESCE)と完全に一致させること。"""
    return (str(user_id or "").strip()
            or (unique_id or "").strip()
            or (nickname or "").strip())


def _valid_owner_id(user_id) -> bool:
    """配信者の数値アカウントIDとして妥当か。TikTokの実IDは長い数値で、team_id等の
    小さな値(例: '1','2')が誤ってown-host user_idに混入したゴミを弾く。"""
    s = str(user_id or "").strip()
    return s.isdigit() and len(s) >= 8


class Storage:
    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
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
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.commit()
        self._writer = threading.Thread(
            target=self._writer_loop, name="storage-writer", daemon=True
        )
        self._writer.start()
        logger.info("storage initialized: %s", db_path)

    def _writer_loop(self) -> None:
        while True:
            with self._flush_cond:
                self._flush_cond.wait(timeout=_WRITE_FLUSH_INTERVAL_SECONDS)
                closed = self._closed
            self._drain()
            if closed:
                return

    def _drain(self) -> None:
        """バッファ済みのevent/viewer sample/user upsertを1 transactionで書き出す。
        writerスレッドと同期flush()の双方から呼ばれるため、buffer入れ替えからcommitまで
        DB lockを保持し、flush()呼び出し時に進行中の書き込み完了を確実に待たせる。"""
        with self._lock:
            with self._buf_lock:
                events = self._event_buffer
                viewers = self._viewer_buffer
                users = self._pending_users
                if not (events or viewers or users):
                    return
                self._event_buffer = []
                self._viewer_buffer = []
                self._pending_users = []
            if events:
                self._conn.executemany(
                    "INSERT INTO events (session_id, time, create_time, kind, user_id, user_unique_id, user_nickname, identity_key, user_avatar, text, comment, gift_name, gift_count, diamonds, count, gift_image, gift_id, user_fans_level, user_gifter_level, user_gifter_badge, user_member_badge)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    events,
                )
            if viewers:
                self._conn.executemany(
                    "INSERT INTO viewer_samples (session_id, time, create_time, viewers, total_viewers, anonymous)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    viewers,
                )
            for user, ts, key in users:
                self._upsert_user_locked(user, ts, key=key, use_cache=True)
            self._conn.commit()

    def flush(self) -> None:
        """バッファ済み書き込みを同期的に確定する。未flushのeventを必要とする読み取り
        (comment抽出・export・Battle貢献の再構成・session確定)の直前に呼ぶ。"""
        self._drain()

    def _migrate(self) -> None:
        columns = [row["name"] for row in self._conn.execute("PRAGMA table_info(events)")]
        if "comment" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN comment TEXT")
            logger.info("migrated events table: added comment column")
        if "count" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN count INTEGER")
            logger.info("migrated events table: added count column")
        if "user_avatar" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN user_avatar TEXT")
            logger.info("migrated events table: added user_avatar column")
        if "gift_image" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN gift_image TEXT")
            logger.info("migrated events table: added gift_image column")
        if "gift_id" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN gift_id INTEGER")
            logger.info("migrated events table: added gift_id column")
        if "user_id" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN user_id TEXT")
            logger.info("migrated events table: added user_id column")
        if "user_fans_level" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN user_fans_level INTEGER")
            logger.info("migrated events table: added user_fans_level column")
        if "user_gifter_badge" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN user_gifter_badge TEXT")
            logger.info("migrated events table: added user_gifter_badge column")
        if "user_member_badge" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN user_member_badge TEXT")
            logger.info("migrated events table: added user_member_badge column")
        if "user_gifter_level" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN user_gifter_level INTEGER")
            logger.info("migrated events table: added user_gifter_level column")
        user_columns = [row["name"] for row in self._conn.execute("PRAGMA table_info(users)")]
        if "gifter_level" not in user_columns:
            self._conn.execute("ALTER TABLE users ADD COLUMN gifter_level INTEGER NOT NULL DEFAULT 0")
            logger.info("migrated users table: added gifter_level column")
        if "create_time" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN create_time REAL")
            logger.info("migrated events table: added create_time column")
        if "identity_key" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN identity_key TEXT")
            # 既存eventのidentity_keyを不変ID優先(user_id -> unique_id -> nickname)で確定。
            # TRIM込みでPython側の_identity_key(strip)と完全一致させる。
            self._conn.execute(
                "UPDATE events SET identity_key = COALESCE("
                " NULLIF(TRIM(user_id), ''), NULLIF(TRIM(user_unique_id), ''),"
                " TRIM(user_nickname))"
            )
            logger.info("migrated events table: added identity_key column and backfilled")
        # 新規/既存いずれのDBでもindexを保証する(columnはSCHEMAまたは上のALTERで存在)。
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_identity ON events(identity_key)"
        )
        # kind単独絞り込み(全体解析のconcentration/gift単価表)用のcovering index。
        # events本体は1行が重く(text/json列)、これが無いとkind条件が全表scanになる。
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_kind_identity"
            " ON events(kind, identity_key, diamonds, session_id, time)"
        )
        # 逆引き補完 + users表再構成。identity_key列が既にある旧migration適用済みDBにも
        # 一度だけ効かせるため、column追加とは独立にsettings markerで管理する。
        if not self._migration_done("reverse_link_v1"):
            self._reverse_link_identities()
            self._conn.execute("DELETE FROM users")
            self._backfill_users()
            self._mark_migration("reverse_link_v1")
        session_columns = [row["name"] for row in self._conn.execute("PRAGMA table_info(sessions)")]
        if "owner_nickname" not in session_columns:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN owner_nickname TEXT")
            logger.info("migrated sessions table: added owner_nickname column")
        if "owner_avatar" not in session_columns:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN owner_avatar TEXT")
            logger.info("migrated sessions table: added owner_avatar column")
        if "owner_user_id" not in session_columns:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN owner_user_id TEXT")
            logger.info("migrated sessions table: added owner_user_id column")
        if "league" not in session_columns:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN league TEXT")
            logger.info("migrated sessions table: added league column")
        target_columns = [row["name"] for row in self._conn.execute("PRAGMA table_info(monitored_targets)")]
        if "record_video" not in target_columns:
            self._conn.execute(
                "ALTER TABLE monitored_targets ADD COLUMN record_video INTEGER NOT NULL DEFAULT 1"
            )
            logger.info("migrated monitored_targets table: added record_video column")
        # 配信者の不変数値IDをBattleのis_own participantから復元してsessionsへ補完し、
        # ゴミ(team_id混入等)のown-host user_idを実IDへ修復する。marker一度きり。
        if not self._migration_done("owner_user_id_v1"):
            self._backfill_owner_user_ids()
            self._mark_migration("owner_user_id_v1")

    def _upsert_user_locked(
        self, user: dict, ts: float, key: Optional[str] = None, use_cache: bool = False
    ) -> str:
        """Userの正規化プロフィールをusers表(唯一の真実)に反映する。identity_keyで名寄せし、
        変更されうる属性(名前/@handle/avatar/Lv/badge)は最新の非空値で上書きする。lock保持前提。
        keyが指定された場合はそれを使う(逆引き補完済みeventのidentity_keyを尊重するため)。
        use_cache時は属性が変わらない限り一定時間(TTL)はupsertを間引く(liveの高頻度取り込み用。
        last_seenの更新がTTL分遅れる副作用は許容。backfill等の正確性重視の呼び出しは間引かない)。"""
        key = key or _identity_key(
            user.get("user_id"), user.get("unique_id"), user.get("nickname")
        )
        if not key:
            return ""
        nickname = (user.get("nickname") or "").strip()
        if nickname == "(unknown)":
            nickname = ""
        if use_cache:
            attr = (
                str(user.get("user_id") or ""),
                user.get("unique_id") or "",
                nickname,
                user.get("avatar") or "",
                int(user.get("fans_level") or 0),
                int(user.get("gifter_level") or 0),
                user.get("gifter_badge") or "",
                user.get("member_badge") or "",
            )
            cached = self._user_cache.get(key)
            if (
                cached is not None
                and cached[0] == attr
                and (ts - cached[1]) < _USER_UPSERT_TTL_SECONDS
            ):
                return key
            self._user_cache[key] = (attr, ts)
        self._conn.execute(
            "INSERT INTO users (identity_key, user_id, unique_id, nickname, avatar,"
            " fans_level, gifter_level, gifter_badge, member_badge, first_seen, last_seen)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(identity_key) DO UPDATE SET"
            "  user_id = COALESCE(NULLIF(excluded.user_id, ''), users.user_id),"
            "  unique_id = COALESCE(NULLIF(excluded.unique_id, ''), users.unique_id),"
            "  nickname = COALESCE(NULLIF(excluded.nickname, ''), users.nickname),"
            "  avatar = COALESCE(NULLIF(excluded.avatar, ''), users.avatar),"
            "  fans_level = CASE WHEN excluded.fans_level > 0 THEN excluded.fans_level ELSE users.fans_level END,"
            "  gifter_level = CASE WHEN excluded.gifter_level > 0 THEN excluded.gifter_level ELSE users.gifter_level END,"
            "  gifter_badge = COALESCE(NULLIF(excluded.gifter_badge, ''), users.gifter_badge),"
            "  member_badge = COALESCE(NULLIF(excluded.member_badge, ''), users.member_badge),"
            "  last_seen = excluded.last_seen",
            (
                key,
                str(user.get("user_id") or ""),
                user.get("unique_id") or "",
                nickname,
                user.get("avatar") or "",
                int(user.get("fans_level") or 0),
                int(user.get("gifter_level") or 0),
                user.get("gifter_badge") or "",
                user.get("member_badge") or "",
                ts,
                ts,
            ),
        )
        return key

    def _migration_done(self, name: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM settings WHERE key = ?", (f"_migration:{name}",)
        ).fetchone()
        return row is not None

    def _mark_migration(self, name: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, '1')",
            (f"_migration:{name}",),
        )

    def _backfill_owner_user_ids(self) -> None:
        """配信者(owner)の不変数値IDをBattleのis_own participantから復元する。@handleごとに
        妥当な数値IDを多数決で1つ選び(ゴミIDは除外)、その@handleの全sessionへ補完。さらに
        battles.data_json内のown-hostのゴミuser_id(team_id混入等)を実IDへ修復する。lock保持前提。"""
        from collections import Counter
        battle_rows = self._conn.execute(
            "SELECT b.rowid AS rid, b.data_json AS d, s.unique_id AS handle"
            " FROM battles b JOIN sessions s ON s.id = b.session_id"
        ).fetchall()
        parsed = []
        votes: dict = {}
        for r in battle_rows:
            try:
                battle = json.loads(r["d"])
            except (ValueError, TypeError):
                continue
            parsed.append((r["rid"], r["handle"], battle))
            for p in battle.get("participants", []) or []:
                if p.get("is_own") and _valid_owner_id(p.get("user_id")):
                    votes.setdefault(r["handle"], Counter())[str(p["user_id"])] += 1
        handle_owner = {h: c.most_common(1)[0][0] for h, c in votes.items() if c}
        if not handle_owner:
            logger.info("owner_user_id backfill: no owner numeric id recoverable")
            return
        # 各@handleの全sessionへ数値owner IDを補完(未設定のみ)。
        filled = 0
        for handle, owner_id in handle_owner.items():
            cur = self._conn.execute(
                "UPDATE sessions SET owner_user_id = ?"
                " WHERE unique_id = ? AND (owner_user_id IS NULL OR owner_user_id = '')",
                (owner_id, handle),
            )
            filled += cur.rowcount
        # battles内のown-hostゴミIDを実IDへ修復。
        repaired = 0
        for rid, handle, battle in parsed:
            owner_id = handle_owner.get(handle)
            if not owner_id:
                continue
            changed = False
            for p in battle.get("participants", []) or []:
                if p.get("is_own") and not _valid_owner_id(p.get("user_id")):
                    p["user_id"] = owner_id
                    changed = True
            if changed:
                self._conn.execute(
                    "UPDATE battles SET data_json = ? WHERE rowid = ?",
                    (json.dumps(battle, ensure_ascii=False), rid),
                )
                repaired += 1
        logger.info(
            "owner_user_id backfill: %d handles resolved, %d sessions filled, %d battles repaired",
            len(handle_owner), filled, repaired,
        )

    def _reverse_link_identities(self) -> None:
        """@handle止まり(数値user_id空)の古いeventを、同じ@handleを持つ数値user_id付き
        eventから逆引きして数値IDへ名寄せし直す(events.identity_keyを数値IDへ更新)。
        1つの@handleが複数の数値user_idに対応する曖昧なケースは、handle使い回しによる
        誤結合を避けるため変更しない。migration一度きり。lock保持前提。"""
        # @handle -> 対応する数値user_idの集合。
        rows = self._conn.execute(
            "SELECT user_unique_id AS handle, user_id"
            " FROM events"
            " WHERE user_unique_id IS NOT NULL AND user_unique_id != ''"
            "   AND user_id IS NOT NULL AND user_id != ''"
            " GROUP BY user_unique_id, user_id"
        ).fetchall()
        handle_to_ids: dict = {}
        for row in rows:
            handle_to_ids.setdefault(row["handle"], set()).add(row["user_id"])
        unambiguous = [
            (uid_set.pop(), handle)
            for handle, uid_set in handle_to_ids.items()
            if len(uid_set) == 1
        ]
        if not unambiguous:
            return
        # user_unique_id検索を高速化(逆引きUPDATEのため)。
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_uhandle ON events(user_unique_id)"
        )
        updated = 0
        for numeric_id, handle in unambiguous:
            cur = self._conn.execute(
                "UPDATE events SET identity_key = ?"
                " WHERE (user_id IS NULL OR user_id = '') AND user_unique_id = ?"
                "   AND identity_key != ?",
                (numeric_id, handle, numeric_id),
            )
            updated += cur.rowcount
        logger.info(
            "reverse-linked %d handle-only events to numeric user_id (%d unambiguous handles)",
            updated,
            len(unambiguous),
        )

    def _backfill_users(self) -> None:
        """既存eventからusers表を再構成する(migration一度きり)。時系列順に同じupsert
        を適用するので、live取り込みと完全に同じ最新値上書きロジックになる。lock保持前提。"""
        rows = self._conn.execute(
            "SELECT identity_key, user_id, user_unique_id AS unique_id, user_nickname AS nickname,"
            " user_avatar AS avatar, user_fans_level AS fans_level,"
            " user_gifter_level AS gifter_level,"
            " user_gifter_badge AS gifter_badge, user_member_badge AS member_badge, time"
            " FROM events WHERE identity_key IS NOT NULL AND identity_key != ''"
            " ORDER BY time"
        ).fetchall()
        count = 0
        for row in rows:
            # events.identity_key(逆引き補完済み)を尊重。recomputeするとhandle止まりへ戻る。
            if self._upsert_user_locked(dict(row), row["time"] or 0, key=row["identity_key"]):
                count += 1
        logger.info("backfilled users table from %d events", count)

    def close(self) -> None:
        with self._flush_cond:
            self._closed = True
            self._flush_cond.notify()
        self._writer.join(timeout=5.0)
        self._drain()
        with self._lock:
            self._conn.close()

    def cleanup_stale_sessions(self) -> int:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM sessions WHERE status IN ('connecting', 'connected', 'reconnecting')"
            ).fetchall()
            for row in rows:
                session_id = row["id"]
                agg = self._conn.execute(
                    "SELECT MAX(time) AS last_time,"
                    " COALESCE(SUM(CASE WHEN kind = 'gift' THEN gift_count ELSE 0 END), 0) AS gifts,"
                    " COALESCE(SUM(CASE WHEN kind = 'gift' THEN diamonds ELSE 0 END), 0) AS diamonds,"
                    " COALESCE(SUM(CASE WHEN kind = 'comment' THEN 1 ELSE 0 END), 0) AS comments,"
                    " COALESCE(SUM(CASE WHEN kind = 'join' THEN 1 ELSE 0 END), 0) AS joins,"
                    " COALESCE(SUM(CASE WHEN kind = 'follow' THEN 1 ELSE 0 END), 0) AS follows,"
                    " COALESCE(SUM(CASE WHEN kind = 'share' THEN 1 ELSE 0 END), 0) AS shares,"
                    " COALESCE(SUM(CASE WHEN kind = 'like' THEN count ELSE 0 END), 0) AS likes,"
                    " COALESCE(SUM(CASE WHEN kind = 'subscribe' THEN 1 ELSE 0 END), 0) AS subscribes,"
                    " COALESCE(SUM(CASE WHEN kind = 'battle' THEN 1 ELSE 0 END), 0) AS battles,"
                    " COUNT(*) AS events_total"
                    " FROM events WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                stats = {
                    "viewers": 0,
                    "total_viewers": 0,
                    "anonymous": 0,
                    "likes_total": agg["likes"],
                    "comments": agg["comments"],
                    "gifts": agg["gifts"],
                    "diamonds": agg["diamonds"],
                    "follows": agg["follows"],
                    "shares": agg["shares"],
                    "joins": agg["joins"],
                    "subscribes": agg["subscribes"],
                    "battles": agg["battles"],
                    "battle_points": 0,
                    "events_total": agg["events_total"],
                    "connected_at": None,
                    "recovered": True,
                }
                self._conn.execute(
                    "UPDATE sessions SET status = 'disconnected', ended_at = ?, stats_json = ? WHERE id = ?",
                    (agg["last_time"] or time.time(), json.dumps(stats), session_id),
                )
            self._conn.commit()
        if rows:
            logger.warning("recovered %d stale sessions from previous run", len(rows))
        return len(rows)

    def create_session(self, unique_id: str, bucket_seconds: int) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO sessions (unique_id, status, started_at, bucket_seconds) VALUES (?, ?, ?, ?)",
                (unique_id, "connecting", time.time(), bucket_seconds),
            )
            self._conn.commit()
            return cursor.lastrowid

    def update_session(self, session_id: int, status: str, room_id: Optional[int] = None) -> None:
        with self._lock:
            if room_id is not None:
                self._conn.execute(
                    "UPDATE sessions SET status = ?, room_id = ? WHERE id = ?",
                    (status, str(room_id), session_id),
                )
            else:
                self._conn.execute(
                    "UPDATE sessions SET status = ? WHERE id = ?", (status, session_id)
                )
            self._conn.commit()

    def update_session_owner(
        self, session_id: int, nickname: str, avatar: str, user_id: str = ""
    ) -> None:
        owner_id = str(user_id or "") if _valid_owner_id(user_id) else ""
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET owner_nickname = ?, owner_avatar = ?,"
                " owner_user_id = COALESCE(NULLIF(?, ''), owner_user_id) WHERE id = ?",
                (nickname or None, avatar or None, owner_id, session_id),
            )
            # 数値owner IDが取れたら、同一@handleの過去sessionで未設定の分にも伝播させる。
            if owner_id:
                row = self._conn.execute(
                    "SELECT unique_id FROM sessions WHERE id = ?", (session_id,)
                ).fetchone()
                if row:
                    self._conn.execute(
                        "UPDATE sessions SET owner_user_id = ?"
                        " WHERE unique_id = ? AND (owner_user_id IS NULL OR owner_user_id = '')",
                        (owner_id, row["unique_id"]),
                    )
            self._conn.commit()

    def update_session_league(self, session_id: int, league: str) -> None:
        """配信者リーグ帯(例:A1/B3)をsessionへ記録する。デイリー変動を配信単位で残すため、
        接続時に取得したその時点の値をそのsessionにだけ保存する(過去sessionへは伝播しない)。
        空値では上書きしない(捏造・消去を避ける)。"""
        if not league:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET league = ? WHERE id = ?", (league, session_id)
            )
            self._conn.commit()

    def add_event(self, session_id: int, entry: dict) -> None:
        user = entry.get("user") or {}
        identity_key = _identity_key(
            user.get("user_id"), user.get("unique_id"), user.get("nickname")
        )
        params = (
            session_id,
            entry["time"],
            entry.get("create_time"),
            entry["kind"],
            user.get("user_id"),
            user.get("unique_id"),
            user.get("nickname"),
            identity_key,
            user.get("avatar"),
            entry.get("text"),
            entry.get("comment"),
            entry.get("gift_name"),
            entry.get("repeat_count"),
            entry.get("diamonds"),
            entry.get("count"),
            entry.get("gift_image"),
            entry.get("gift_id"),
            user.get("fans_level") or 0,
            user.get("gifter_level") or 0,
            user.get("gifter_badge") or "",
            user.get("member_badge") or "",
        )
        with self._buf_lock:
            self._event_buffer.append(params)
            if identity_key:
                self._pending_users.append((user, entry["time"], identity_key))
            if len(self._event_buffer) + len(self._viewer_buffer) >= _WRITE_BATCH_SIZE:
                self._flush_cond.notify()

    def add_viewer_sample(
        self,
        session_id: int,
        ts: float,
        create_time: Optional[float],
        viewers: int,
        total_viewers: Optional[int],
        anonymous: Optional[int],
    ) -> None:
        """RoomUserSeqの同接系列をnative cadenceで永続化する。退室eventは配信側が出さない
        ため、net流入(Δ同接)はこの系列でしか測れない。bucketの10s丸め・timeline上限では
        長時間配信の系列が欠落するので、生sampleを別表に残す。"""
        with self._buf_lock:
            self._viewer_buffer.append(
                (session_id, ts, create_time, viewers, total_viewers, anonymous)
            )
            if len(self._event_buffer) + len(self._viewer_buffer) >= _WRITE_BATCH_SIZE:
                self._flush_cond.notify()

    def finalize_session(
        self, session_id: int, status: str, stats: dict, timeline: list, markers: list
    ) -> None:
        self.flush()
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET status = ?, ended_at = ?, stats_json = ? WHERE id = ?",
                (status, time.time(), json.dumps(stats), session_id),
            )
            self._conn.execute("DELETE FROM buckets WHERE session_id = ?", (session_id,))
            self._conn.executemany(
                "INSERT INTO buckets (session_id, start, gifts, diamonds, comments, likes, joins, follows, shares, viewers)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        session_id,
                        b["start"],
                        b["gifts"],
                        b["diamonds"],
                        b["comments"],
                        b["likes"],
                        b["joins"],
                        b["follows"],
                        b["shares"],
                        b["viewers"],
                    )
                    for b in timeline
                ],
            )
            self._conn.execute("DELETE FROM markers WHERE session_id = ?", (session_id,))
            self._conn.executemany(
                "INSERT INTO markers (session_id, time, kind, label) VALUES (?, ?, ?, ?)",
                [(session_id, m["time"], m["kind"], m["label"]) for m in markers],
            )
            self._conn.commit()
            # 確定したsessionの全体解析payloadをここで1回だけ計算して永続化する。
            self._refresh_session_analytics_locked(session_id)
        logger.info("session finalized: id=%d status=%s", session_id, status)

    def _latest_owners(self) -> dict:
        owners = self._conn.execute(
            "SELECT unique_id,"
            " (SELECT owner_avatar FROM sessions s2 WHERE s2.unique_id = s.unique_id"
            "  AND owner_avatar IS NOT NULL AND owner_avatar != ''"
            "  ORDER BY started_at DESC LIMIT 1) AS avatar,"
            " (SELECT owner_nickname FROM sessions s3 WHERE s3.unique_id = s.unique_id"
            "  AND owner_nickname IS NOT NULL AND owner_nickname != ''"
            "  ORDER BY started_at DESC LIMIT 1) AS nickname"
            " FROM sessions s GROUP BY unique_id"
        ).fetchall()
        return {row["unique_id"]: row for row in owners}

    def _latest_owner_handles_locked(self) -> dict:
        """owner group key(owner_user_id優先) -> 最新sessionの表示@handle。相関subqueryを
        グループ毎に評価する代わりに1回の走査で決定する(streamer_index/dashboard共通)。
        lock保持前提。"""
        rows = self._conn.execute(
            "SELECT COALESCE(NULLIF(owner_user_id, ''), unique_id) AS okey, unique_id"
            " FROM sessions ORDER BY started_at DESC"
        ).fetchall()
        out: dict = {}
        for row in rows:
            if row["okey"] not in out:
                out[row["okey"]] = row["unique_id"]
        return out

    def latest_owner(self, unique_id: str) -> dict:
        """配信者(unique_id)の最後に判明したowner identity(avatar/nickname)を返す。
        live未接続でもキャッシュ済みのアイコン/表示名を出すために使う。identity系は
        point-in-timeが無ければ永続sessionへfallbackする方針。avatarとnicknameは
        それぞれ最新の非空値を独立に採用する。見つからなければ空文字。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT"
                " (SELECT owner_avatar FROM sessions WHERE unique_id = ?"
                "  AND owner_avatar IS NOT NULL AND owner_avatar != ''"
                "  ORDER BY started_at DESC LIMIT 1) AS avatar,"
                " (SELECT owner_nickname FROM sessions WHERE unique_id = ?"
                "  AND owner_nickname IS NOT NULL AND owner_nickname != ''"
                "  ORDER BY started_at DESC LIMIT 1) AS nickname",
                (unique_id, unique_id),
            ).fetchone()
        return {
            "avatar": (row["avatar"] if row else "") or "",
            "nickname": (row["nickname"] if row else "") or "",
        }

    def _owner_handles_locked(self, unique_id: str) -> list:
        """同一配信者(不変owner数値ID)に属する全@handleを返す。owner_user_idが判れば
        それを共有する全handleを、無ければ入力handle単体を返す。@handle変更が起きても
        配信者単位で履歴を束ねられる。lock保持前提。"""
        row = self._conn.execute(
            "SELECT owner_user_id FROM sessions"
            " WHERE unique_id = ? AND owner_user_id IS NOT NULL AND owner_user_id != ''"
            " LIMIT 1",
            (unique_id,),
        ).fetchone()
        if row and row["owner_user_id"]:
            rows = self._conn.execute(
                "SELECT DISTINCT unique_id FROM sessions WHERE owner_user_id = ?",
                (row["owner_user_id"],),
            ).fetchall()
            handles = [r["unique_id"] for r in rows]
            if handles:
                return handles
        return [unique_id]

    def _fill_owner(self, item: dict, owners: dict) -> dict:
        latest = owners.get(item["unique_id"])
        if latest:
            if not item.get("owner_avatar"):
                item["owner_avatar"] = latest["avatar"] or ""
            if not item.get("owner_nickname"):
                item["owner_nickname"] = latest["nickname"] or ""
        return item

    def list_sessions(self, limit: int) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT s.*,"
                " (SELECT COUNT(*) FROM recordings r WHERE r.session_id = s.id"
                "  AND r.status IN ('completed', 'interrupted')) AS recording_count,"
                " (SELECT MAX(viewers) FROM buckets b WHERE b.session_id = s.id)"
                "  AS bucket_peak_viewers"
                " FROM sessions s ORDER BY s.started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            owners = self._latest_owners()
        return [self._fill_owner(_session_row_to_dict(row), owners) for row in rows]

    def get_session(self, session_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT s.*,"
                " (SELECT MAX(viewers) FROM buckets b WHERE b.session_id = s.id)"
                "  AS bucket_peak_viewers"
                " FROM sessions s WHERE s.id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            owners = self._latest_owners()
        return self._fill_owner(_session_row_to_dict(row), owners)

    def set_note(self, session_id: int, note: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE sessions SET note = ? WHERE id = ?", (note, session_id)
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def delete_session(self, session_id: int) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM sessions WHERE id = ?", (session_id,)
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def session_ids_for_users(self, unique_ids: list) -> list:
        """指定配信者に属する全session idを返す。owner-identityで@handle変更を辿るため、
        改名を跨いでもその配信者の履歴を漏れなく対象にできる(ユーザー単位の一括削除用)。"""
        with self._lock:
            handles: set = set()
            for unique_id in unique_ids:
                handles.update(self._owner_handles_locked(unique_id))
            if not handles:
                return []
            placeholders = ",".join("?" * len(handles))
            rows = self._conn.execute(
                f"SELECT id FROM sessions WHERE unique_id IN ({placeholders}) ORDER BY id",
                tuple(handles),
            ).fetchall()
        return [row["id"] for row in rows]

    def session_timeline(self, session_id: int) -> dict:
        with self._lock:
            buckets = self._conn.execute(
                "SELECT start, gifts, diamonds, comments, likes, joins, follows, shares, viewers"
                " FROM buckets WHERE session_id = ? ORDER BY start",
                (session_id,),
            ).fetchall()
            markers = self._conn.execute(
                "SELECT time, kind, label FROM markers WHERE session_id = ? ORDER BY time",
                (session_id,),
            ).fetchall()
        return {
            "buckets": [dict(b) for b in buckets],
            "markers": [dict(m) for m in markers],
        }

    def session_summary(self, session_id: int) -> dict:
        with self._lock:
            # 表示属性はその時(このSession)のsnapshotを優先し、欠けていればusers表(最新)へ
            # fallbackする。名寄せ(identity_key)と切り離すことで過去の見え方を保持する。
            user_rows = self._conn.execute(
                "SELECT e.identity_key AS key,"
                " COALESCE(NULLIF(MAX(e.user_id), ''), u.user_id) AS user_id,"
                " COALESCE(NULLIF(MAX(e.user_unique_id), ''), u.unique_id) AS unique_id,"
                " COALESCE(NULLIF(MAX(e.user_nickname), ''), u.nickname) AS nickname,"
                " COALESCE(NULLIF(MAX(e.user_avatar), ''), u.avatar) AS avatar,"
                " SUM(e.gift_count) AS gifts, SUM(e.diamonds) AS diamonds,"
                # Lv/badgeはその時点で変動する属性。users表(最新)へfallbackすると過去の値を
                # 捏造するため、このSessionのevent(point-in-time)のみ。無ければ非表示。
                " NULLIF(MAX(e.user_fans_level), 0) AS fans_level,"
                " NULLIF(MAX(e.user_gifter_level), 0) AS gifter_level,"
                " NULLIF(MAX(e.user_gifter_badge), '') AS gifter_badge,"
                " NULLIF(MAX(e.user_member_badge), '') AS member_badge"
                " FROM events e LEFT JOIN users u ON u.identity_key = e.identity_key"
                " WHERE e.session_id = ? AND e.kind = 'gift'"
                " GROUP BY e.identity_key ORDER BY diamonds DESC, gifts DESC LIMIT 100",
                (session_id,),
            ).fetchall()
            item_rows = self._conn.execute(
                "SELECT identity_key AS key,"
                " gift_name, SUM(gift_count) AS count, SUM(diamonds) AS diamonds"
                " FROM events WHERE session_id = ? AND kind = 'gift'"
                " GROUP BY identity_key, gift_name",
                (session_id,),
            ).fetchall()
            gift_rows = self._conn.execute(
                "SELECT gift_name AS name, SUM(gift_count) AS count, SUM(diamonds) AS diamonds,"
                " MAX(CASE WHEN gift_count > 0 THEN diamonds / gift_count ELSE 0 END) AS diamonds_each"
                " FROM events WHERE session_id = ? AND kind = 'gift'"
                " GROUP BY gift_name ORDER BY diamonds DESC, count DESC LIMIT 100",
                (session_id,),
            ).fetchall()
        items_by_user: dict = {}
        for row in item_rows:
            items_by_user.setdefault(row["key"], {})[row["gift_name"]] = {
                "count": row["count"] or 0,
                "diamonds": row["diamonds"] or 0,
            }
        users = []
        for row in user_rows:
            users.append(
                {
                    "user_id": row["user_id"] or "",
                    "unique_id": row["unique_id"] or "",
                    "nickname": row["nickname"] or "(unknown)",
                    "avatar": row["avatar"] or "",
                    "gifts": row["gifts"] or 0,
                    "diamonds": row["diamonds"] or 0,
                    "fans_level": row["fans_level"] or 0,
                    "gifter_level": row["gifter_level"] or 0,
                    "gifter_badge": row["gifter_badge"] or "",
                    "member_badge": row["member_badge"] or "",
                    "items": items_by_user.get(row["key"], {}),
                }
            )
        return {"users": users, "gifts": [dict(g) for g in gift_rows]}

    def session_comments(self, session_id: int, limit: int) -> list:
        """Most recent comment texts for a session, for AI analysis. The text lives in
        the `comment` column (add_event stores entry['comment']); fall back to `text`."""
        self.flush()
        with self._lock:
            rows = self._conn.execute(
                "SELECT comment, text FROM events"
                " WHERE session_id = ? AND kind = 'comment'"
                " ORDER BY time DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [(row["comment"] or row["text"] or "") for row in rows if (row["comment"] or row["text"])]

    def iter_events(self, session_id: int) -> list:
        self.flush()
        with self._lock:
            rows = self._conn.execute(
                "SELECT time, create_time, kind, user_unique_id, user_nickname, text, comment, gift_name, gift_count, diamonds, count, gift_image, gift_id"
                " FROM events WHERE session_id = ? ORDER BY time",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_battles(self, session_id: int, battles: list) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM battles WHERE session_id = ?", (session_id,))
            self._conn.executemany(
                "INSERT INTO battles (session_id, battle_id, data_json) VALUES (?, ?, ?)",
                [
                    (session_id, b.get("battle_id", 0), json.dumps(b, ensure_ascii=False))
                    for b in battles
                ],
            )
            self._conn.commit()

    def save_collab_windows(self, session_id: int, windows: list) -> None:
        """コラボ(非BattleのLinkMic)接続窓を保存。Battle窓の差し引きは分析側で行う。"""
        with self._lock:
            self._conn.execute("DELETE FROM collab_windows WHERE session_id = ?", (session_id,))
            self._conn.executemany(
                "INSERT INTO collab_windows (session_id, channel_id, start, end, guests_max, data_json)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        session_id,
                        str(w.get("channel_id") or ""),
                        w["start"],
                        w.get("end"),
                        w.get("guests_max", 0) or 0,
                        json.dumps(w, ensure_ascii=False),
                    )
                    for w in windows
                    if w.get("start") is not None
                ],
            )
            self._conn.commit()

    def collab_windows_for_session(self, session_id: int) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT channel_id, start, end, guests_max FROM collab_windows"
                " WHERE session_id = ? ORDER BY start",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def battle_gift_contributions(self, session_id: int, start_time, end_time) -> list:
        """Battleの時間窓内に自陣(監視配信者)へ送られたGiftをUser単位で集計する。
        TikTokのarmies eventは相手陣の合計スコアのみで、誰がいくら実弾を送ったかの
        User単位内訳(user_armies/diamond_score)を欠くことが多い。実弾の出どころは
        確実に記録しているGift eventから復元する。相手陣のGiftは別Roomのため取得不可。
        窓境界(battle_setting.*_ms)はTikTokサーバ時刻なので、eventもサーバ時刻の
        create_timeで突合する(欠落eventのみ受信時刻timeで代用)。"""
        upper = end_time if end_time is not None else 9_999_999_999
        self.flush()
        with self._lock:
            rows = self._conn.execute(
                "SELECT e.identity_key AS key,"
                " COALESCE(NULLIF(MAX(e.user_id), ''), u.user_id) AS user_id,"
                " COALESCE(NULLIF(MAX(e.user_unique_id), ''), u.unique_id) AS unique_id,"
                " COALESCE(NULLIF(MAX(e.user_nickname), ''), u.nickname) AS nickname,"
                " COALESCE(NULLIF(MAX(e.user_avatar), ''), u.avatar) AS avatar, SUM(e.diamonds) AS diamonds,"
                # Lv/badgeはその時点で変動する属性。users表(最新)へfallbackすると過去の値を
                # 捏造するため、このSessionのevent(point-in-time)のみ。無ければ非表示。
                " NULLIF(MAX(e.user_fans_level), 0) AS fans_level,"
                " NULLIF(MAX(e.user_gifter_level), 0) AS gifter_level,"
                " NULLIF(MAX(e.user_gifter_badge), '') AS gifter_badge,"
                " NULLIF(MAX(e.user_member_badge), '') AS member_badge"
                " FROM events e LEFT JOIN users u ON u.identity_key = e.identity_key"
                " WHERE e.session_id = ? AND e.kind = 'gift'"
                " AND COALESCE(e.create_time, e.time) >= ? AND COALESCE(e.create_time, e.time) <= ?"
                " GROUP BY e.identity_key HAVING SUM(e.diamonds) > 0 ORDER BY diamonds DESC",
                (session_id, start_time or 0, upper),
            ).fetchall()
        return [
            {
                "user_id": row["user_id"] or "",
                "unique_id": row["unique_id"] or "",
                "nickname": row["nickname"] or "(unknown)",
                "avatar": row["avatar"] or "",
                "side": "own",
                "diamonds": row["diamonds"] or 0,
                "fans_level": row["fans_level"] or 0,
                "gifter_level": row["gifter_level"] or 0,
                "gifter_badge": row["gifter_badge"] or "",
                "member_badge": row["member_badge"] or "",
            }
            for row in rows
        ]

    def apply_battle_gift_contributions(self, session_id: int, battles: list) -> list:
        """各Battleの監視配信者(自陣host)の貢献をGift eventから再構成して差し替える。
        相手陣(side!=own)と、チーム戦の味方host(別Roomのためarmies由来)の貢献はそのまま
        残す。host_idで宛先配信者を保持し、配信者別の集計に使う。live snapshot / history
        両方で同じ集計を使う。"""
        starts = sorted(
            b["start_time"] for b in battles if b.get("start_time") is not None
        )
        for battle in battles:
            own_host = next(
                (p.get("user_id") for p in battle.get("participants", []) if p.get("is_own")),
                None,
            )
            start = battle.get("start_time")
            end = battle.get("end_time")
            # end_time_msを欠くBattleを無制限の窓にしない: Battle後〜配信終了までの通常
            # Giftが貢献に合算され、連続PKでは同じGiftが複数Battleへ二重帰属するため。
            # 所定durationで閉じ、それも無い終了済みBattleは次Battleの開始で打ち切る。
            if end is None and start is not None and battle.get("duration"):
                end = start + battle["duration"]
            if end is None and start is not None and not battle.get("ongoing"):
                end = next((s for s in starts if s > start), None)
            # 終了済みBattleは窓が確定しているので貢献集計をキャッシュし、再集計は進行中のみ。
            bid = battle.get("battle_id")
            cache_key = (
                (session_id, bid, start, end)
                if (not battle.get("ongoing") and end is not None and bid)
                else None
            )
            if cache_key is not None and cache_key in self._battle_contrib_cache:
                gift = self._battle_contrib_cache[cache_key]
            else:
                gift = self.battle_gift_contributions(session_id, start, end)
                if cache_key is not None:
                    self._battle_contrib_cache[cache_key] = gift
            gift_by_id = {g["user_id"]: g for g in gift if g.get("user_id")}
            matched = set()
            result = []
            for c in battle.get("contributions", []):
                is_own_host = c.get("side") == "own" and (
                    not own_host or c.get("host_id") in (None, "", own_host)
                )
                gid = c.get("user_id")
                if is_own_host and gid and gid in gift_by_id:
                    # armies由来の貢献(score=バトルスコア)に、Gift event由来の実弾(コイン)を
                    # 数値IDで突合して上書きし、@handle等の表示情報も補完する。
                    g = gift_by_id[gid]
                    c["diamonds"] = g["diamonds"]
                    c["unique_id"] = g.get("unique_id") or c.get("unique_id", "")
                    c["nickname"] = c.get("nickname") or g.get("nickname")
                    c["avatar"] = c.get("avatar") or g.get("avatar")
                    c["host_id"] = own_host or c.get("host_id")
                    # メンバーLv/バッジはGift event由来(armiesには無い)。取得できた分だけ付与。
                    c["fans_level"] = g.get("fans_level") or c.get("fans_level", 0)
                    c["gifter_level"] = g.get("gifter_level") or c.get("gifter_level", 0)
                    c["gifter_badge"] = g.get("gifter_badge") or c.get("gifter_badge", "")
                    c["member_badge"] = g.get("member_badge") or c.get("member_badge", "")
                    matched.add(gid)
                result.append(c)
            # armiesに無い(=PKスコア内訳が来ていない)自陣貢献者は、Gift eventから追加する
            # (この場合バトルスコアは不明=score 0)。
            for g in gift:
                if g.get("user_id") and g["user_id"] in matched:
                    continue
                result.append({
                    "user_id": g.get("user_id", ""),
                    "unique_id": g.get("unique_id", ""),
                    "nickname": g.get("nickname", "(unknown)"),
                    "avatar": g.get("avatar", ""),
                    "side": "own",
                    "host_id": own_host or "",
                    "score": 0,
                    "diamonds": g.get("diamonds", 0),
                    "fans_level": g.get("fans_level", 0),
                    "gifter_level": g.get("gifter_level", 0),
                    "gifter_badge": g.get("gifter_badge", ""),
                    "member_badge": g.get("member_badge", ""),
                })
            battle["contributions"] = result
        return battles

    def battles_for_session(self, session_id: int) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT data_json FROM battles WHERE session_id = ?", (session_id,)
            ).fetchall()
        battles = [json.loads(row["data_json"]) for row in rows]
        self.apply_battle_gift_contributions(session_id, battles)
        battles.sort(key=lambda b: b.get("start_time", 0), reverse=True)
        return battles

    def streamer_history_stats(self, unique_id: str, limit: int) -> dict:
        """Per-streamer comparison of recent finished sessions: today's run is the
        live snapshot (supplied by the caller); this returns the previous session,
        the recent average, and the personal best for each metric. Peak viewers is
        read from the buckets table (the finalized stats keep only the last value)."""
        with self._lock:
            handles = self._owner_handles_locked(unique_id)
            ph = ",".join("?" * len(handles))
            rows = self._conn.execute(
                "SELECT s.id, s.started_at, s.ended_at, s.stats_json,"
                " (SELECT MAX(viewers) FROM buckets b WHERE b.session_id = s.id) AS peak_viewers"
                f" FROM sessions s WHERE s.unique_id IN ({ph}) AND s.ended_at IS NOT NULL"
                " ORDER BY s.started_at DESC LIMIT ?",
                (*handles, limit),
            ).fetchall()
        sessions = []
        for row in rows:
            stats = json.loads(row["stats_json"])
            sessions.append(
                {
                    "session_id": row["id"],
                    "started_at": row["started_at"],
                    "gifts": stats.get("gifts", 0) or 0,
                    "diamonds": stats.get("diamonds", 0) or 0,
                    "comments": stats.get("comments", 0) or 0,
                    "viewers": stats.get("viewers_peak")
                    or row["peak_viewers"]
                    or stats.get("viewers", 0)
                    or 0,
                    "duration": (row["ended_at"] - row["started_at"]) if row["ended_at"] else 0,
                }
            )
        metrics = ["gifts", "diamonds", "comments", "viewers", "duration"]
        count = len(sessions)
        average = {
            m: (sum(s[m] for s in sessions) / count) if count else 0 for m in metrics
        }
        best = {m: max((s[m] for s in sessions), default=0) for m in metrics}
        return {
            "unique_id": unique_id,
            "count": count,
            "sessions": sessions,
            "last": sessions[0] if sessions else None,
            "average": average,
            "best": best,
        }

    def streamer_index(self) -> list:
        """List every monitored streamer with lifetime totals, for the streamer
        analytics page's left-hand selector. Identity (nickname/avatar) is the most
        recent non-empty owner record."""
        with self._lock:
            # GROUP BYは配信者identity(owner_user_id優先)。bare columnのs.unique_idは
            # SQLiteでは任意の行から取られ@handle改名者でラベルが不定になるため、表示用
            # handleは最新sessionのものを相関subqueryで決定的に選ぶ。
            rows = self._conn.execute(
                "SELECT COALESCE(NULLIF(s.owner_user_id, ''), s.unique_id) AS okey,"
                " COUNT(DISTINCT s.id) AS sessions,"
                " COALESCE(SUM(CASE WHEN e.kind = 'gift' THEN e.diamonds ELSE 0 END), 0) AS diamonds,"
                " COALESCE(SUM(CASE WHEN e.kind = 'gift' THEN e.gift_count ELSE 0 END), 0) AS gifts,"
                " COALESCE(SUM(CASE WHEN e.kind = 'comment' THEN 1 ELSE 0 END), 0) AS comments,"
                " MAX(s.started_at) AS last_started_at"
                " FROM sessions s LEFT JOIN events e ON e.session_id = s.id"
                " GROUP BY COALESCE(NULLIF(s.owner_user_id, ''), s.unique_id) ORDER BY diamonds DESC, sessions DESC",
            ).fetchall()
            handles = self._latest_owner_handles_locked()
            owners = self._latest_owners()
        result = []
        for row in rows:
            handle = handles.get(row["okey"], row["okey"])
            owner = owners.get(handle)
            result.append(
                {
                    "unique_id": handle,
                    "nickname": (owner["nickname"] if owner else "") or handle,
                    "avatar": (owner["avatar"] if owner else "") or "",
                    "sessions": row["sessions"],
                    "diamonds": row["diamonds"] or 0,
                    "gifts": row["gifts"] or 0,
                    "comments": row["comments"] or 0,
                    "last_started_at": row["last_started_at"],
                }
            )
        return result

    def streamer_profile(self, unique_id: str, limit: int = 200) -> dict:
        """Cross-session profile for one streamer: lifetime/average/best metrics,
        per-session series, the streamer's own gifter base (with loyalty + revenue
        concentration), and battle record (win rate, scores, opponents, the share of
        revenue earned during battle windows). Peak viewers comes from buckets; the
        finalized stats keep only the last viewer count."""
        with self._lock:
            handles = self._owner_handles_locked(unique_id)
            ph = ",".join("?" * len(handles))
            session_rows = self._conn.execute(
                "SELECT s.id, s.started_at, s.ended_at, s.stats_json,"
                " (SELECT MAX(viewers) FROM buckets b WHERE b.session_id = s.id) AS peak_viewers"
                f" FROM sessions s WHERE s.unique_id IN ({ph})"
                " ORDER BY s.started_at DESC LIMIT ?",
                (*handles, limit),
            ).fetchall()
            gifter_rows = self._conn.execute(
                "SELECT e.identity_key AS key,"
                " COALESCE(NULLIF(MAX(e.user_id), ''), u.user_id) AS user_id,"
                " COALESCE(NULLIF(MAX(e.user_unique_id), ''), u.unique_id) AS unique_id,"
                " COALESCE(NULLIF(MAX(e.user_nickname), ''), u.nickname) AS nickname,"
                " COALESCE(NULLIF(MAX(e.user_avatar), ''), u.avatar) AS avatar, SUM(e.gift_count) AS gifts,"
                " SUM(e.diamonds) AS diamonds, COUNT(DISTINCT e.session_id) AS sessions"
                " FROM events e JOIN sessions s ON s.id = e.session_id"
                " LEFT JOIN users u ON u.identity_key = e.identity_key"
                f" WHERE s.unique_id IN ({ph}) AND e.kind = 'gift'"
                " GROUP BY e.identity_key ORDER BY diamonds DESC, gifts DESC",
                tuple(handles),
            ).fetchall()
            # Time-of-day distribution from the bucket time-series, so a session's
            # coins/comments land in the hours they actually happened (not all on the
            # start hour). 'localtime' matches the browser on this localhost app, so
            # the day/hour grid lines up with the rest of the (browser-local) UI.
            heatmap_rows = self._conn.execute(
                "SELECT CAST(strftime('%w', b.start, 'unixepoch', 'localtime') AS INTEGER) AS dow,"
                " CAST(strftime('%H', b.start, 'unixepoch', 'localtime') AS INTEGER) AS hour,"
                " CAST(strftime('%M', b.start, 'unixepoch', 'localtime') AS INTEGER) / 15 AS quarter,"
                " SUM(b.diamonds) AS diamonds, SUM(b.comments) AS comments,"
                " SUM(s.bucket_seconds) AS active_seconds"
                " FROM buckets b JOIN sessions s ON s.id = b.session_id"
                f" WHERE s.unique_id IN ({ph})"
                " GROUP BY dow, hour, quarter",
                tuple(handles),
            ).fetchall()
            # Oldest session first so that, when the same battle_id is saved under
            # more than one session (e.g. two server instances collected the same
            # room concurrently), the copy kept by the dedup below is the one whose
            # session saw the battle from its start — the most complete record.
            battle_rows = self._conn.execute(
                "SELECT b.session_id AS session_id, b.data_json AS data_json"
                " FROM battles b JOIN sessions s ON s.id = b.session_id"
                f" WHERE s.unique_id IN ({ph})"
                " ORDER BY s.started_at ASC, b.session_id ASC",
                tuple(handles),
            ).fetchall()
            owners = self._latest_owners()
            owner = owners.get(unique_id)
            # Reconstruct each battle's own-side gifters (who fueled the battle, and
            # by how much) from gift events inside the battle window, the same way
            # battle_gift_contributions does. The opponent's gifters live in a
            # different room and are not in this session's events, so this is the
            # monitored streamer's own battle gifters only. Aggregated across every
            # past battle it answers "which gifters keep showing up in battles".
            battle_diamonds = 0
            battle_gifters: dict = {}
            parsed_battles = []
            # battle_id is TikTok's globally-unique PK id, so the same physical battle
            # carries the same id across sessions. Dedup on it to keep concurrent-
            # collection duplicates from inflating every battle metric. id 0/missing is
            # treated as un-dedupable (old/synthetic records) and kept as-is.
            seen_battle_ids = set()
            dropped_duplicates = 0
            for brow in battle_rows:
                battle = json.loads(brow["data_json"])
                start_time = battle.get("start_time")
                if start_time is None:
                    continue
                battle_id = battle.get("battle_id")
                if battle_id:
                    if battle_id in seen_battle_ids:
                        dropped_duplicates += 1
                        continue
                    seen_battle_ids.add(battle_id)
                upper = battle.get("end_time")
                upper = upper if upper is not None else 9_999_999_999
                contrib_rows = self._conn.execute(
                    "SELECT e.identity_key AS key,"
                    " COALESCE(NULLIF(MAX(e.user_id), ''), u.user_id) AS user_id,"
                    " COALESCE(NULLIF(MAX(e.user_unique_id), ''), u.unique_id) AS unique_id,"
                    " COALESCE(NULLIF(MAX(e.user_nickname), ''), u.nickname) AS nickname,"
                    " COALESCE(NULLIF(MAX(e.user_avatar), ''), u.avatar) AS avatar, SUM(e.gift_count) AS gifts, SUM(e.diamonds) AS diamonds"
                    " FROM events e LEFT JOIN users u ON u.identity_key = e.identity_key"
                    " WHERE e.session_id = ? AND e.kind = 'gift' AND e.time >= ? AND e.time <= ?"
                    " GROUP BY e.identity_key HAVING SUM(e.diamonds) > 0",
                    (brow["session_id"], start_time, upper),
                ).fetchall()
                window_diamonds = 0
                key_contributors = 0
                for crow in contrib_rows:
                    diamonds = crow["diamonds"] or 0
                    window_diamonds += diamonds
                    if diamonds >= _BATTLE_KEY_CONTRIB_DIAMONDS:
                        key_contributors += 1
                    key = crow["key"]
                    if not key:
                        continue
                    g = battle_gifters.setdefault(
                        key,
                        {
                            "user_id": crow["user_id"] or "",
                            "unique_id": crow["unique_id"] or "",
                            "nickname": crow["nickname"] or "(unknown)",
                            "avatar": crow["avatar"] or "",
                            "diamonds": 0,
                            "gifts": 0,
                            "battles": 0,
                        },
                    )
                    g["diamonds"] += diamonds
                    g["gifts"] += crow["gifts"] or 0
                    g["battles"] += 1
                    if crow["avatar"] and not g["avatar"]:
                        g["avatar"] = crow["avatar"]
                battle_diamonds += window_diamonds
                parsed_battles.append(
                    {
                        "battle": battle,
                        "session_id": brow["session_id"],
                        "window_diamonds": window_diamonds,
                        "key_contributors": key_contributors,
                    }
                )

        if dropped_duplicates:
            logger.info(
                "streamer_profile: dropped %d duplicate battle(s) by battle_id for %s"
                " (concurrent-collection artifact)",
                dropped_duplicates,
                unique_id,
            )

        identity = {
            "unique_id": unique_id,
            "nickname": (owner["nickname"] if owner else "") or unique_id,
            "avatar": (owner["avatar"] if owner else "") or "",
        }

        sessions = []
        for row in session_rows:
            stats = json.loads(row["stats_json"])
            sessions.append(
                {
                    "session_id": row["id"],
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "duration": (row["ended_at"] - row["started_at"]) if row["ended_at"] else 0,
                    "gifts": stats.get("gifts", 0) or 0,
                    "diamonds": stats.get("diamonds", 0) or 0,
                    "comments": stats.get("comments", 0) or 0,
                    "likes": stats.get("likes_total", 0) or 0,
                    "viewers": stats.get("viewers_peak")
                    or row["peak_viewers"]
                    or stats.get("viewers", 0)
                    or 0,
                    "battles": stats.get("battles", 0) or 0,
                    "battle_points": stats.get("battle_points", 0) or 0,
                }
            )
        metrics = ["gifts", "diamonds", "comments", "likes", "viewers", "duration", "battle_points"]
        count = len(sessions)
        totals = {m: sum(s[m] for s in sessions) for m in metrics}
        average = {m: (totals[m] / count if count else 0) for m in metrics}
        best = {m: max((s[m] for s in sessions), default=0) for m in metrics}

        gifters = [
            {
                "user_id": row["user_id"] or "",
                "unique_id": row["unique_id"] or "",
                "nickname": row["nickname"] or "(unknown)",
                "avatar": row["avatar"] or "",
                "gifts": row["gifts"] or 0,
                "diamonds": row["diamonds"] or 0,
                "sessions": row["sessions"] or 0,
            }
            for row in gifter_rows
        ]
        gifter_total_diamonds = sum(g["diamonds"] for g in gifters)

        def _share(top_n: int) -> float:
            if not gifter_total_diamonds:
                return 0.0
            return sum(g["diamonds"] for g in gifters[:top_n]) / gifter_total_diamonds * 100

        concentration = {
            "total_gifters": len(gifters),
            "total_diamonds": gifter_total_diamonds,
            "top1": _share(1),
            "top5": _share(5),
            "top10": _share(10),
            "repeat_gifters": sum(1 for g in gifters if g["sessions"] >= 2),
            "once_gifters": sum(1 for g in gifters if g["sessions"] == 1),
        }

        battles = [pb["battle"] for pb in parsed_battles]
        wins = sum(1 for b in battles if b.get("result") == "win")
        losses = sum(1 for b in battles if b.get("result") == "lose")
        draws = sum(1 for b in battles if b.get("result") == "draw")
        decided = wins + losses
        own_score_sum = sum(b.get("own_score", 0) or 0 for b in battles)
        opp_score_sum = sum(b.get("opp_score", 0) or 0 for b in battles)
        battle_count = len(battles)
        opponents: dict = {}
        for b in battles:
            for opp in b.get("opponents", []) or []:
                key = opp.get("unique_id") or opp.get("nickname") or opp.get("user_id")
                if not key:
                    continue
                stat = opponents.setdefault(
                    key,
                    {
                        "unique_id": opp.get("unique_id", ""),
                        "nickname": opp.get("nickname", "(unknown)"),
                        "avatar": opp.get("avatar", ""),
                        "battles": 0,
                        "wins": 0,
                        "losses": 0,
                    },
                )
                stat["battles"] += 1
                if b.get("result") == "win":
                    stat["wins"] += 1
                elif b.get("result") == "lose":
                    stat["losses"] += 1
        opponent_list = sorted(opponents.values(), key=lambda o: o["battles"], reverse=True)
        battle_gifter_list = sorted(battle_gifters.values(), key=lambda g: g["diamonds"], reverse=True)

        # Per-battle history (newest first) — the chronological record behind the
        # aggregate: each battle's scores, result, primary opponent and the coins
        # raised in its window. The frontend reverses it for a score-over-battles
        # trend chart and lists it as a table.
        history = []
        for pb in parsed_battles:
            b = pb["battle"]
            opps = b.get("opponents", []) or []
            opp = max(opps, key=lambda o: o.get("score", 0) or 0, default=None) if opps else None
            history.append(
                {
                    "session_id": pb["session_id"],
                    "started_at": b.get("start_time"),
                    "ended_at": b.get("end_time"),
                    "type": b.get("type") or "personal",
                    "own_score": b.get("own_score", 0) or 0,
                    "opp_score": b.get("opp_score", 0) or 0,
                    "result": b.get("result"),
                    "diamonds": pb["window_diamonds"],
                    "key_contributors": pb["key_contributors"],
                    "opponent_count": len(opps),
                    "opponent": {
                        "unique_id": opp.get("unique_id", ""),
                        "nickname": opp.get("nickname", "") or "(unknown)",
                        "avatar": opp.get("avatar", ""),
                    }
                    if opp
                    else None,
                }
            )
        history.sort(key=lambda h: h["started_at"] or 0, reverse=True)

        # 1戦あたり「主力貢献者(coin >= 閾値)」の平均人数。過去全Battleを集約した指標。
        key_contrib_sum = sum(pb["key_contributors"] for pb in parsed_battles)
        battle_summary = {
            "count": battle_count,
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "win_rate": (wins / decided * 100) if decided else 0,
            "avg_own_score": (own_score_sum / battle_count) if battle_count else 0,
            "avg_opp_score": (opp_score_sum / battle_count) if battle_count else 0,
            "key_contrib_threshold": _BATTLE_KEY_CONTRIB_DIAMONDS,
            "key_contrib_total": key_contrib_sum,
            "avg_key_contributors": (key_contrib_sum / battle_count) if battle_count else 0,
            "battle_diamonds": battle_diamonds,
            "battle_diamond_share": (battle_diamonds / totals["diamonds"] * 100) if totals["diamonds"] else 0,
            "opponents": opponent_list[:30],
            "gifters": battle_gifter_list[:30],
            "history": history[:80],
        }

        heatmap = [
            {
                "dow": row["dow"],
                "hour": row["hour"],
                "quarter": row["quarter"],
                "diamonds": row["diamonds"] or 0,
                "comments": row["comments"] or 0,
                "active_seconds": row["active_seconds"] or 0,
            }
            for row in heatmap_rows
        ]

        return {
            "identity": identity,
            "count": count,
            "sessions": sessions,
            "totals": totals,
            "average": average,
            "best": best,
            "gifters": gifters[:100],
            "concentration": concentration,
            "battles": battle_summary,
            "heatmap": heatmap,
        }

    def streamer_cohort(self, unique_id: str) -> dict:
        """Daily viewer cohort/retention for one streamer. A viewer counts as
        present on a day if they produced any watch-side event (entering the room,
        commenting, liking, following, sharing, subscribing, or gifting) — presence
        is what matters here, not whether they gifted. For each day: active viewers,
        new (first-ever visit this day) vs returning, and retention = share of the
        previous active day's viewers who came back to watch this day. Days are
        local-time so they line up with the browser-local UI."""
        with self._lock:
            handles = self._owner_handles_locked(unique_id)
            ph = ",".join("?" * len(handles))
            rows = self._conn.execute(
                "SELECT e.identity_key AS key,"
                " strftime('%Y-%m-%d', e.time, 'unixepoch', 'localtime') AS ymd,"
                " SUM(e.diamonds) AS diamonds"
                " FROM events e JOIN sessions s ON s.id = e.session_id"
                f" WHERE s.unique_id IN ({ph})"
                " AND e.kind IN ('join', 'comment', 'like', 'follow', 'share', 'subscribe', 'gift')"
                " GROUP BY e.identity_key, ymd",
                tuple(handles),
            ).fetchall()
        by_day: dict = {}
        first_seen: dict = {}
        for row in rows:
            ymd = row["ymd"]
            key = row["key"]
            if not ymd or not key:
                continue
            by_day.setdefault(ymd, {})[key] = row["diamonds"] or 0
            if key not in first_seen or ymd < first_seen[key]:
                first_seen[key] = ymd
        days = []
        prev_keys: set = set()
        for ymd in sorted(by_day.keys()):
            keys = set(by_day[ymd].keys())
            new = {k for k in keys if first_seen[k] == ymd}
            retained = keys & prev_keys
            days.append(
                {
                    "date": ymd,
                    "active": len(keys),
                    "new": len(new),
                    "returning": len(keys) - len(new),
                    "retained": len(retained),
                    "retention": (len(retained) / len(prev_keys) * 100) if prev_keys else 0,
                    "diamonds": sum(by_day[ymd].values()),
                }
            )
            prev_keys = keys
        return {"days": days}

    def streamer_highlights(self, unique_id: str, session_limit: int = 50, top: int = 15) -> list:
        """Auto-detected spike moments across a streamer's recent sessions. A bucket
        is a highlight when its coin value is a statistical outlier within its session
        (z-score >= 2 over that session's coin buckets); the biggest spike per session
        is kept and the top ones returned, tagged if a recording covers the moment."""
        highlights = []
        with self._lock:
            handles = self._owner_handles_locked(unique_id)
            ph = ",".join("?" * len(handles))
            session_rows = self._conn.execute(
                f"SELECT id, started_at FROM sessions WHERE unique_id IN ({ph})"
                " ORDER BY started_at DESC LIMIT ?",
                (*handles, session_limit),
            ).fetchall()
            session_ids = [s["id"] for s in session_rows]
            buckets_by_session: dict = {}
            if session_ids:
                bph = ",".join("?" * len(session_ids))
                for brow in self._conn.execute(
                    f"SELECT session_id, start, diamonds, comments FROM buckets"
                    f" WHERE session_id IN ({bph}) ORDER BY session_id, start",
                    tuple(session_ids),
                ).fetchall():
                    buckets_by_session.setdefault(brow["session_id"], []).append(brow)
            for session in session_rows:
                buckets = buckets_by_session.get(session["id"], [])
                values = [b["diamonds"] or 0 for b in buckets]
                n = len(values)
                if n < 5:
                    continue
                mean = sum(values) / n
                std = (sum((v - mean) ** 2 for v in values) / n) ** 0.5
                if std <= 0:
                    continue
                best = None
                for bucket in buckets:
                    value = bucket["diamonds"] or 0
                    if value <= 0:
                        continue
                    zscore = (value - mean) / std
                    if zscore < 2.0:
                        continue
                    if best is None or value > best["diamonds"]:
                        best = {
                            "session_id": session["id"],
                            "time": bucket["start"],
                            "diamonds": value,
                            "comments": bucket["comments"] or 0,
                            "baseline": mean,
                            "ratio": (value / mean) if mean > 0 else 0,
                            "zscore": zscore,
                        }
                if best:
                    highlights.append(best)
            recordings = self._conn.execute(
                f"SELECT id, session_id, started_at, ended_at FROM recordings"
                f" WHERE unique_id IN ({ph}) AND status IN ('completed', 'interrupted')",
                tuple(handles),
            ).fetchall()
        recs = [dict(r) for r in recordings]
        for highlight in highlights:
            cover = next(
                (
                    r
                    for r in recs
                    if r["session_id"] == highlight["session_id"]
                    and r["started_at"] <= highlight["time"]
                    and (r["ended_at"] is None or highlight["time"] <= r["ended_at"])
                ),
                None,
            )
            highlight["has_recording"] = cover is not None
            highlight["recording_id"] = cover["id"] if cover else None
            # Seconds into the recording to jump to, for deep-linked playback.
            highlight["offset"] = (
                max(0, highlight["time"] - cover["started_at"]) if cover else None
            )
        highlights.sort(key=lambda h: h["diamonds"], reverse=True)
        return highlights[:top]

    # ---- 全体解析(配信者横断) ------------------------------------------
    # 監視配信者を横断した集約。新規収集は行わず既存DBの再集約のみ。集約は配信(session)
    # 単位の中間集計(payload)までに留めてanalytics_session_cacheへ永続化する(終了済み
    # sessionは不変なので1回だけ計算し、収集中sessionは毎回その場で計算)。全体へ丸めた
    # 集約を持たないため、配信者データの削除はsessionsのON DELETE CASCADEで整合が保てる。
    # sinceは集計対象の下限started_at(0=全期間)。母集団のサンプル数を各所で返し、
    # 少数での断定を防ぐ。

    _ANALYTICS_SESSION_SELECT = (
        "SELECT s.id AS id, s.unique_id AS unique_id, s.started_at AS started_at,"
        " s.ended_at AS ended_at, s.bucket_seconds AS bucket_seconds,"
        " COALESCE(NULLIF(s.owner_user_id, ''), s.unique_id) AS owner_key"
    )

    @staticmethod
    def _analytics_sess_dict(row) -> dict:
        return {
            "id": row["id"],
            "unique_id": row["unique_id"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "bucket_seconds": row["bucket_seconds"],
            "owner_key": row["owner_key"],
        }

    def _ensure_analytics_cache_locked(self, kind: str) -> int:
        """終了済みで未計算(またはlogic version不一致)のsessionのpayloadを計算・保存する。
        finalizeを通らず終了したsession(異常終了の復旧等)もここで拾う。lock保持前提。"""
        version = analytics.CACHE_VERSIONS[kind]
        rows = self._conn.execute(
            self._ANALYTICS_SESSION_SELECT
            + " FROM sessions s"
            " LEFT JOIN analytics_session_cache c ON c.session_id = s.id AND c.kind = ?"
            " WHERE s.ended_at IS NOT NULL AND (c.session_id IS NULL OR c.version != ?)",
            (kind, version),
        ).fetchall()
        for row in rows:
            payload = analytics.compute_payload(
                self._conn, self._analytics_sess_dict(row), kind
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO analytics_session_cache"
                " (session_id, kind, version, payload_json, computed_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (row["id"], kind, version, json.dumps(payload), time.time()),
            )
        if rows:
            self._conn.commit()
            logger.info(
                "analytics cache: computed %d sessions for kind=%s", len(rows), kind
            )
        return len(rows)

    def _analytics_rows(self, kind: str, since: float) -> list:
        """(sessionメタ, per-session payload)の列をstarted_at昇順で返す。終了済みは
        cacheから読み、収集中sessionはその場で計算する(session単位indexで軽い)。"""
        with self._lock:
            self._ensure_analytics_cache_locked(kind)
            rows = self._conn.execute(
                self._ANALYTICS_SESSION_SELECT
                + ", c.payload_json AS payload_json FROM sessions s"
                " LEFT JOIN analytics_session_cache c ON c.session_id = s.id AND c.kind = ?"
                " WHERE s.started_at >= ? ORDER BY s.started_at",
                (kind, since),
            ).fetchall()
            out = []
            for row in rows:
                sess = self._analytics_sess_dict(row)
                if sess["ended_at"] is not None and row["payload_json"] is not None:
                    out.append((sess, json.loads(row["payload_json"])))
                else:
                    out.append((sess, analytics.compute_payload(self._conn, sess, kind)))
        return out

    def _refresh_session_analytics_locked(self, session_id: int) -> None:
        """session確定直後に全kindのpayloadを計算し保存する。lock保持前提。"""
        row = self._conn.execute(
            self._ANALYTICS_SESSION_SELECT + " FROM sessions s WHERE s.id = ?",
            (session_id,),
        ).fetchone()
        if row is None or row["ended_at"] is None:
            return
        sess = self._analytics_sess_dict(row)
        now = time.time()
        for kind in analytics.KINDS:
            payload = analytics.compute_payload(self._conn, sess, kind)
            self._conn.execute(
                "INSERT OR REPLACE INTO analytics_session_cache"
                " (session_id, kind, version, payload_json, computed_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    session_id,
                    kind,
                    analytics.CACHE_VERSIONS[kind],
                    json.dumps(payload),
                    now,
                ),
            )
        self._conn.commit()

    def analytics_summary(self, since: float = 0.0) -> dict:
        """全体解析の母集団サマリ(何本の配信・何時間・何bucketを基に集計しているか)。"""
        return analytics.reduce_summary(self._analytics_rows("summary", since))

    def analytics_time_index(self, metric: str = "joins", since: float = 0.0) -> dict:
        """時間帯インデックス: 各配信の平均レートを1.0とした時間帯ごとの相対倍率。"""
        if metric not in analytics.INDEX_METRICS:
            raise ValueError(f"unsupported index metric: {metric}")
        return analytics.reduce_time_index(
            self._analytics_rows("time_index", since), metric
        )

    def analytics_relations(self, since: float = 0.0) -> dict:
        """指標間の関連(配信単位)のSpearman順位相関+同接(規模)制御の偏相関。"""
        return analytics.reduce_relations(self._analytics_rows("relations", since))

    def analytics_share_uplift(self, since: float = 0.0) -> dict:
        """Share→入室のevent-study(placebo帯・95%CI付き)。"""
        return analytics.reduce_peri(self._analytics_rows("peri_share", since), "share")

    def analytics_battle_uplift(self, since: float = 0.0) -> dict:
        """Battle→入室のevent-study(placebo/CI補正)。baseline非補正の旧レート比は
        ratio_metricsとして参考併記する。"""
        result = analytics.reduce_peri(
            self._analytics_rows("peri_battle", since), "battle"
        )
        result["ratio_metrics"] = analytics.reduce_battle_ratio(
            self._analytics_rows("battle_ratio", since)
        )
        return result

    def analytics_glove_crit_rate(self, since: float = 0.0) -> dict:
        """Battleのグローブ(5倍化)のcoin帯別発動率。単価不明分は全期間のGift event由来の
        gift_id→単価表で解決する(観測が増えるほど後から解ける)。"""
        rows = self._analytics_rows("glove", since)
        with self._lock:
            coin_rows = self._conn.execute(
                "SELECT gift_id, diamonds, gift_count FROM events"
                " WHERE kind = 'gift' AND gift_id IS NOT NULL AND gift_count > 0"
            ).fetchall()
        # gift_id→単価(diamonds_each)。同一gift_idは価格一定なので代表値でよい。
        unit_coins: dict = {}
        for r in coin_rows:
            gid, cnt = r["gift_id"], r["gift_count"] or 0
            if gid is None or cnt <= 0:
                continue
            unit_coins[gid] = (r["diamonds"] or 0) / cnt
        return analytics.reduce_glove(rows, unit_coins)

    def analytics_join_quality(self, since: float = 0.0) -> dict:
        """入室の質: 入室者のうち初見(初観測)の比率を時間帯別に。"""
        return analytics.reduce_join_quality(self._analytics_rows("join_quality", since))

    def analytics_scale_efficiency(self, since: float = 0.0) -> dict:
        """規模 vs 効率: 配信者ごとの平均同接(規模)と同接あたりコイン(効率)。"""
        rows = self._analytics_rows("scale_efficiency", since)
        with self._lock:
            owners = self._latest_owners()
        return analytics.reduce_scale_efficiency(rows, owners)

    def analytics_retention(self, since: float = 0.0) -> dict:
        """入室→定着: 時刻別の入室と平均同接、全体stick rate(=Σ純増/Σ入室)。"""
        return analytics.reduce_retention(self._analytics_rows("retention", since))

    def analytics_concentration(self, since: float = 0.0) -> dict:
        """ギフト/コメントの集中度(横断)。identity_key単位でgiftコインとComment数を集計し、
        Gini係数・Lorenz曲線・上位N%シェアを返す。User横断の貢献量が必要なためsession単位
        cacheでは持たず、covering index(kind, identity_key, ...)で素データを直接集計する
        (素データと同時に消えるため削除でも整合が壊れない)。"""
        with self._lock:
            gift_rows = self._conn.execute(
                "SELECT e.identity_key AS key, SUM(e.diamonds) AS v"
                " FROM events e JOIN sessions s ON s.id = e.session_id"
                " WHERE e.kind = 'gift' AND s.started_at >= ?"
                " GROUP BY e.identity_key",
                (since,),
            ).fetchall()
            comment_rows = self._conn.execute(
                "SELECT e.identity_key AS key, COUNT(*) AS v"
                " FROM events e JOIN sessions s ON s.id = e.session_id"
                " WHERE e.kind = 'comment' AND s.started_at >= ?"
                " GROUP BY e.identity_key",
                (since,),
            ).fetchall()
        gifts = analytics.concentration([r["v"] or 0 for r in gift_rows if r["key"]])
        comments = analytics.concentration(
            [r["v"] or 0 for r in comment_rows if r["key"]]
        )
        return {"gifts": gifts, "comments": comments}

    def analytics_join_context(self, since: float = 0.0) -> dict:
        """入室のコンテキスト別(Battle中/コラボ中/平時)の入室数・秒・分レート。"""
        return analytics.reduce_join_context(self._analytics_rows("join_context", since))

    def analytics_organic_entries(self, since: float = 0.0) -> dict:
        """organic入室(§15): ノイズ入室を落としたgenuineness weight付き時間帯カーブ。"""
        return analytics.reduce_organic(self._analytics_rows("organic", since))

    def create_recording(self, session_id, unique_id, path, filename, quality, started_at) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO recordings (session_id, unique_id, path, filename, quality, status, started_at)"
                " VALUES (?, ?, ?, ?, ?, 'recording', ?)",
                (session_id, unique_id, path, filename, quality, started_at),
            )
            self._conn.commit()
            return cursor.lastrowid

    def update_recording(self, recording_id, status, path, filename, ended_at, size, error=None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE recordings SET status = ?, path = ?, filename = ?, ended_at = ?, bytes = ?, error = ?"
                " WHERE id = ?",
                (status, path, filename, ended_at, size, error, recording_id),
            )
            self._conn.commit()

    def list_recordings(self, limit: int) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM recordings ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def recordings_for_session(self, session_id: int) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM recordings WHERE session_id = ? ORDER BY started_at", (session_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def get_recording(self, recording_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()
        return dict(row) if row else None

    def recordings_brief(self) -> list:
        """Lightweight per-recording info for list-level done badges: each finished
        recording's session, path (to test for a burned-in output file) and whether a
        transcript exists. One query so the session list can aggregate cheaply."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT r.id, r.session_id, r.path,"
                " (t.recording_id IS NOT NULL) AS has_transcript"
                " FROM recordings r LEFT JOIN transcripts t ON t.recording_id = r.id"
                " WHERE r.status IN ('completed', 'interrupted')"
            ).fetchall()
        return [dict(row) for row in rows]

    def transcribed_recording_ids(self) -> set:
        """Recording ids that have a stored transcript (existence only, no payload)."""
        with self._lock:
            rows = self._conn.execute("SELECT recording_id FROM transcripts").fetchall()
        return {row["recording_id"] for row in rows}

    def delete_recording(self, recording_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()
            if row is None:
                return None
            self._conn.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))
            self._conn.commit()
        return dict(row)

    def mark_stale_recordings(self) -> int:
        """On startup, recordings left 'recording' are orphaned (process died)."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE recordings SET status = 'interrupted' WHERE status = 'recording'"
            )
            self._conn.commit()
        return cursor.rowcount

    def get_transcript(self, recording_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT recording_id, language, model, text, segments_json, duration, created_at"
                " FROM transcripts WHERE recording_id = ?",
                (recording_id,),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["segments"] = json.loads(item.pop("segments_json"))
        return item

    def save_transcript(self, recording_id: int, result: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO transcripts (recording_id, language, model, text, segments_json, duration, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(recording_id) DO UPDATE SET"
                " language = excluded.language, model = excluded.model, text = excluded.text,"
                " segments_json = excluded.segments_json, duration = excluded.duration,"
                " created_at = excluded.created_at",
                (
                    recording_id,
                    result.get("language"),
                    result.get("model"),
                    result.get("text", ""),
                    json.dumps(result.get("segments", []), ensure_ascii=False),
                    result.get("duration"),
                    time.time(),
                ),
            )
            self._conn.commit()
        logger.info("transcript saved: recording_id=%d", recording_id)

    def get_settings(self) -> dict:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def set_settings(self, values: dict) -> None:
        with self._lock:
            self._conn.executemany(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                [(key, str(value)) for key, value in values.items()],
            )
            self._conn.commit()

    def add_monitored_target(self, unique_id: str, record_video: bool = True) -> None:
        # ON CONFLICT DO NOTHING keeps an existing target's record_video preference
        # intact when the same monitor is (re)started; a removed-then-readded target
        # has no row, so the supplied value is applied fresh.
        with self._lock:
            self._conn.execute(
                "INSERT INTO monitored_targets (unique_id, added_at, record_video) VALUES (?, ?, ?)"
                " ON CONFLICT(unique_id) DO NOTHING",
                (unique_id, time.time(), 1 if record_video else 0),
            )
            self._conn.commit()

    def set_target_record_video(self, unique_id: str, record_video: bool) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE monitored_targets SET record_video = ? WHERE unique_id = ?",
                (1 if record_video else 0, unique_id),
            )
            self._conn.commit()

    def get_target_record_video(self, unique_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT record_video FROM monitored_targets WHERE unique_id = ?",
                (unique_id,),
            ).fetchone()
        return bool(row["record_video"]) if row is not None else True

    def remove_monitored_target(self, unique_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM monitored_targets WHERE unique_id = ?", (unique_id,)
            )
            self._conn.commit()

    def list_monitored_targets(self) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT unique_id, record_video FROM monitored_targets ORDER BY added_at"
            ).fetchall()
        return [
            {"unique_id": row["unique_id"], "record_video": bool(row["record_video"])}
            for row in rows
        ]

    def session_rankings(self, limit: int) -> dict:
        with self._lock:
            base_rows = self._conn.execute(
                "SELECT id, unique_id, started_at, ended_at, stats_json FROM sessions",
            ).fetchall()
            agg_rows = self._conn.execute(
                "SELECT session_id,"
                " SUM(CASE WHEN kind = 'like' THEN count ELSE 0 END) AS like_count,"
                " SUM(CASE WHEN kind = 'comment' THEN 1 ELSE 0 END) AS comments,"
                " SUM(CASE WHEN kind = 'gift' THEN diamonds ELSE 0 END) AS diamonds"
                " FROM events GROUP BY session_id",
            ).fetchall()
        agg = {r["session_id"]: r for r in agg_rows}
        sessions = []
        for row in base_rows:
            a = agg.get(row["id"])
            stats = json.loads(row["stats_json"])
            likes_total = stats.get("likes_total")
            likes = likes_total if likes_total is not None else ((a["like_count"] if a else 0) or 0)
            sessions.append(
                {
                    "id": row["id"],
                    "unique_id": row["unique_id"],
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "likes": likes,
                    "comments": (a["comments"] if a else 0) or 0,
                    "diamonds": (a["diamonds"] if a else 0) or 0,
                    "battle_points": stats.get("battle_points") or 0,
                }
            )

        def ranked(metric: str) -> list:
            ordered = sorted(sessions, key=lambda s: s[metric] or 0, reverse=True)
            return [
                {
                    "session_id": s["id"],
                    "unique_id": s["unique_id"],
                    "started_at": s["started_at"],
                    "ended_at": s["ended_at"],
                    "value": s[metric] or 0,
                }
                for s in ordered[:limit]
            ]

        return {
            "likes": ranked("likes"),
            "comments": ranked("comments"),
            "gifts": ranked("diamonds"),
            "battles": ranked("battle_points"),
        }

    def aggregate_dashboard(self) -> dict:
        with self._lock:
            totals = self._conn.execute(
                "SELECT"
                " (SELECT COUNT(*) FROM sessions) AS sessions,"
                " COALESCE(SUM(CASE WHEN kind = 'gift' THEN gift_count ELSE 0 END), 0) AS gifts,"
                " COALESCE(SUM(CASE WHEN kind = 'gift' THEN diamonds ELSE 0 END), 0) AS diamonds,"
                " COALESCE(SUM(CASE WHEN kind = 'comment' THEN 1 ELSE 0 END), 0) AS comments,"
                " (SELECT COALESCE(SUM(json_extract(stats_json, '$.likes_total')), 0) FROM sessions) AS likes,"
                " (SELECT COALESCE(SUM(CASE WHEN ended_at IS NOT NULL THEN ended_at - started_at ELSE 0 END), 0) FROM sessions) AS duration"
                " FROM events"
            ).fetchone()
            # 表示用handleの選び方はstreamer_indexと同じ(最新sessionのものを決定的に)。
            streamer_rows = self._conn.execute(
                "SELECT COALESCE(NULLIF(s.owner_user_id, ''), s.unique_id) AS okey,"
                " COUNT(DISTINCT s.id) AS sessions,"
                " COALESCE(SUM(CASE WHEN e.kind = 'gift' THEN e.gift_count ELSE 0 END), 0) AS gifts,"
                " COALESCE(SUM(CASE WHEN e.kind = 'gift' THEN e.diamonds ELSE 0 END), 0) AS diamonds,"
                " COALESCE(SUM(CASE WHEN e.kind = 'comment' THEN 1 ELSE 0 END), 0) AS comments,"
                " MAX(s.started_at) AS last_started_at"
                " FROM sessions s LEFT JOIN events e ON e.session_id = s.id"
                " GROUP BY COALESCE(NULLIF(s.owner_user_id, ''), s.unique_id) ORDER BY diamonds DESC",
            ).fetchall()
            streamer_handles = self._latest_owner_handles_locked()
            gifter_rows = self._conn.execute(
                "SELECT e.identity_key AS key,"
                " COALESCE(NULLIF(MAX(e.user_id), ''), u.user_id) AS user_id,"
                " COALESCE(NULLIF(MAX(e.user_unique_id), ''), u.unique_id) AS unique_id,"
                " COALESCE(NULLIF(MAX(e.user_nickname), ''), u.nickname) AS nickname,"
                " COALESCE(NULLIF(MAX(e.user_avatar), ''), u.avatar) AS avatar,"
                " SUM(e.gift_count) AS gifts, SUM(e.diamonds) AS diamonds,"
                " COUNT(DISTINCT e.session_id) AS sessions"
                " FROM events e LEFT JOIN users u ON u.identity_key = e.identity_key"
                " WHERE e.kind = 'gift'"
                " GROUP BY e.identity_key ORDER BY diamonds DESC, gifts DESC LIMIT 50",
            ).fetchall()
            gift_rows = self._conn.execute(
                "SELECT gift_name AS name, SUM(gift_count) AS count, SUM(diamonds) AS diamonds"
                " FROM events WHERE kind = 'gift'"
                " GROUP BY gift_name ORDER BY diamonds DESC, count DESC LIMIT 50",
            ).fetchall()
            session_rows = self._conn.execute(
                "SELECT id, unique_id, started_at,"
                " COALESCE(json_extract(stats_json, '$.diamonds'), 0) AS diamonds,"
                " COALESCE(json_extract(stats_json, '$.gifts'), 0) AS gifts,"
                " COALESCE(json_extract(stats_json, '$.comments'), 0) AS comments"
                " FROM sessions ORDER BY started_at DESC LIMIT 30",
            ).fetchall()
        return {
            "totals": dict(totals),
            "streamers": [
                {
                    "unique_id": streamer_handles.get(row["okey"], row["okey"]),
                    "sessions": row["sessions"],
                    "gifts": row["gifts"],
                    "diamonds": row["diamonds"],
                    "comments": row["comments"],
                    "last_started_at": row["last_started_at"],
                }
                for row in streamer_rows
            ],
            "top_gifters": [
                {
                    "user_id": row["user_id"] or "",
                    "unique_id": row["unique_id"] or "",
                    "nickname": row["nickname"] or "(unknown)",
                    "avatar": row["avatar"] or "",
                    "gifts": row["gifts"] or 0,
                    "diamonds": row["diamonds"] or 0,
                    "sessions": row["sessions"],
                }
                for row in gifter_rows
            ],
            "top_gifts": [dict(row) for row in gift_rows],
            "recent_sessions": [dict(row) for row in reversed(session_rows)],
        }
