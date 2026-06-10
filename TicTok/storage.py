import json
import logging
import sqlite3
import threading
import time
from typing import Optional

logger = logging.getLogger("tictok.storage")

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
    stats_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    time REAL NOT NULL,
    kind TEXT NOT NULL,
    user_unique_id TEXT,
    user_nickname TEXT,
    text TEXT,
    gift_name TEXT,
    gift_count INTEGER,
    diamonds INTEGER
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, kind);
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
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _session_row_to_dict(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["stats"] = json.loads(item.pop("stats_json"))
    return item


class Storage:
    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.commit()
        logger.info("storage initialized: %s", db_path)

    def _migrate(self) -> None:
        columns = [row["name"] for row in self._conn.execute("PRAGMA table_info(events)")]
        if "comment" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN comment TEXT")
            logger.info("migrated events table: added comment column")
        if "count" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN count INTEGER")
            logger.info("migrated events table: added count column")

    def close(self) -> None:
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
                    " COALESCE(SUM(CASE WHEN kind = 'share' THEN 1 ELSE 0 END), 0) AS shares"
                    " FROM events WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                stats = {
                    "gifts": agg["gifts"],
                    "diamonds": agg["diamonds"],
                    "comments": agg["comments"],
                    "joins": agg["joins"],
                    "follows": agg["follows"],
                    "shares": agg["shares"],
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

    def add_event(self, session_id: int, entry: dict) -> None:
        user = entry.get("user") or {}
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (session_id, time, kind, user_unique_id, user_nickname, text, comment, gift_name, gift_count, diamonds, count)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    entry["time"],
                    entry["kind"],
                    user.get("unique_id"),
                    user.get("nickname"),
                    entry.get("text"),
                    entry.get("comment"),
                    entry.get("gift_name"),
                    entry.get("repeat_count"),
                    entry.get("diamonds"),
                    entry.get("count"),
                ),
            )
            self._conn.commit()

    def finalize_session(
        self, session_id: int, status: str, stats: dict, timeline: list, markers: list
    ) -> None:
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
        logger.info("session finalized: id=%d status=%s", session_id, status)

    def list_sessions(self, limit: int) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_session_row_to_dict(row) for row in rows]

    def get_session(self, session_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return _session_row_to_dict(row) if row else None

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
            user_rows = self._conn.execute(
                "SELECT COALESCE(NULLIF(user_unique_id, ''), user_nickname) AS key,"
                " MAX(user_unique_id) AS unique_id, MAX(user_nickname) AS nickname,"
                " SUM(gift_count) AS gifts, SUM(diamonds) AS diamonds"
                " FROM events WHERE session_id = ? AND kind = 'gift'"
                " GROUP BY key ORDER BY diamonds DESC, gifts DESC LIMIT 100",
                (session_id,),
            ).fetchall()
            item_rows = self._conn.execute(
                "SELECT COALESCE(NULLIF(user_unique_id, ''), user_nickname) AS key,"
                " gift_name, SUM(gift_count) AS count"
                " FROM events WHERE session_id = ? AND kind = 'gift'"
                " GROUP BY key, gift_name",
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
            items_by_user.setdefault(row["key"], {})[row["gift_name"]] = row["count"]
        users = []
        for row in user_rows:
            users.append(
                {
                    "unique_id": row["unique_id"] or "",
                    "nickname": row["nickname"] or "(unknown)",
                    "gifts": row["gifts"] or 0,
                    "diamonds": row["diamonds"] or 0,
                    "items": items_by_user.get(row["key"], {}),
                }
            )
        return {"users": users, "gifts": [dict(g) for g in gift_rows]}

    def iter_events(self, session_id: int) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT time, kind, user_unique_id, user_nickname, text, comment, gift_name, gift_count, diamonds, count"
                " FROM events WHERE session_id = ? ORDER BY time",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

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

    def session_rankings(self, limit: int) -> dict:
        with self._lock:
            rows = self._conn.execute(
                "SELECT s.id, s.unique_id, s.started_at, s.ended_at,"
                " COALESCE(json_extract(s.stats_json, '$.likes_total'),"
                "   (SELECT SUM(e.count) FROM events e WHERE e.session_id = s.id AND e.kind = 'like'), 0) AS likes,"
                " (SELECT COUNT(*) FROM events e WHERE e.session_id = s.id AND e.kind = 'comment') AS comments,"
                " (SELECT COALESCE(SUM(e.diamonds), 0) FROM events e WHERE e.session_id = s.id AND e.kind = 'gift') AS diamonds,"
                " COALESCE(json_extract(s.stats_json, '$.battle_points'), 0) AS battle_points"
                " FROM sessions s",
            ).fetchall()
        sessions = [dict(row) for row in rows]

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
            streamer_rows = self._conn.execute(
                "SELECT s.unique_id, COUNT(DISTINCT s.id) AS sessions,"
                " COALESCE(SUM(CASE WHEN e.kind = 'gift' THEN e.gift_count ELSE 0 END), 0) AS gifts,"
                " COALESCE(SUM(CASE WHEN e.kind = 'gift' THEN e.diamonds ELSE 0 END), 0) AS diamonds,"
                " COALESCE(SUM(CASE WHEN e.kind = 'comment' THEN 1 ELSE 0 END), 0) AS comments,"
                " MAX(s.started_at) AS last_started_at"
                " FROM sessions s LEFT JOIN events e ON e.session_id = s.id"
                " GROUP BY s.unique_id ORDER BY diamonds DESC",
            ).fetchall()
            gifter_rows = self._conn.execute(
                "SELECT COALESCE(NULLIF(user_unique_id, ''), user_nickname) AS key,"
                " MAX(user_unique_id) AS unique_id, MAX(user_nickname) AS nickname,"
                " SUM(gift_count) AS gifts, SUM(diamonds) AS diamonds,"
                " COUNT(DISTINCT session_id) AS sessions"
                " FROM events WHERE kind = 'gift'"
                " GROUP BY key ORDER BY diamonds DESC, gifts DESC LIMIT 50",
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
            "streamers": [dict(row) for row in streamer_rows],
            "top_gifters": [
                {
                    "unique_id": row["unique_id"] or "",
                    "nickname": row["nickname"] or "(unknown)",
                    "gifts": row["gifts"] or 0,
                    "diamonds": row["diamonds"] or 0,
                    "sessions": row["sessions"],
                }
                for row in gifter_rows
            ],
            "top_gifts": [dict(row) for row in gift_rows],
            "recent_sessions": [dict(row) for row in reversed(session_rows)],
        }
