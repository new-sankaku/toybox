"""ギフターの配信者リーグ帯の取得待ち行列と、その結果(users表)。

境界の理由: users表の属性更新ではあるが、待ち行列という別の寿命を持つ状態を伴う。
users mixinはevent取り込みのhot pathを持つため、外部取得の都合で膨らませない。

なぜqueueをDBに置くか: 取得は1件15秒間隔で流す(TikTok側のレート制限を実測で踏んだ
ためで、tictok/collect/gifter_league.py 参照)。当日ぶんが数百件になるとprocessの寿命を
またぐので、memory上のqueueだと再起動のたびに当日ぶんが丸ごと落ちる。

lock契約: lock保持前提のmethodは無い。各methodが自分で self._lock を取る。
"""
import time
from typing import Optional

from tictok.store._common import NON_IDENTITY_KEYS, logger

# 母集合を絞るためのsession側の遡り幅。gift eventそのものの窓(since)より広く取る必要が
# ある — 長時間の配信は窓より前に始まっており、開始時刻で切ると進行中の配信のgiftが
# まるごと母集合から落ちる。
_SESSION_LOOKBACK_SECONDS = 3 * 86400.0

# @handleとして成立する文字だけで出来ているか。identity_keyのfallbackはnicknameまで
# 下りるため、handle欄に空白入りの表示名が入っている行が実在する(実DBで3人、うち1人は
# 通算86万コイン)。そのまま照会するとTikTokは当然「そんなuserは居ない」を返し、こちらは
# それを「確認して配信者ではなかった」と確定させてしまう — 見ていないものを見たことに
# するので、対象を決める時点で外す(未確認のまま残す)。
_VALID_HANDLE_GLOB = "*[^A-Za-z0-9._]*"


class GifterLeagueMixin:
    """ギフターのリーグ取得の待ち行列と結果。

    lockもDB接続も持たない。すべて Storage が所有する self._conn / self._lock を借りる
    (mixinとして Storage に混ぜられる前提)。契約の詳細はmodule docstringを参照。
    """

    def enqueue_gifter_leagues(
        self, since: float, min_coin: int, recheck_seconds: float, now: Optional[float] = None
    ) -> int:
        """``since`` 以降にgiftした視聴者のうち、通算 ``min_coin`` 以上を投げた人を待ち行列へ積む。

        既に確認済みの人は ``recheck_seconds`` を過ぎて再登場したときだけ積み直す。リーグ帯は
        日次で変動するので確認は一度きりにできないが、毎日全員を引き直す必要も無い。

        母集合を「``since`` 以降に開始したsession」で絞るのは走査量のためである。eventは
        100万行を超えており、kindだけで絞ると当日の集計に全期間が乗る。
        """
        now = time.time() if now is None else now
        placeholders = ",".join("?" * len(NON_IDENTITY_KEYS))
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO league_queue"
                " (identity_key, unique_id, enqueued_at, attempts, next_attempt_at, last_error)"
                " SELECT e.identity_key,"
                "  COALESCE(NULLIF(MAX(u.unique_id), ''), MAX(e.user_unique_id)), ?, 0, 0, ''"
                " FROM events e JOIN sessions s ON s.id = e.session_id"
                " LEFT JOIN users u ON u.identity_key = e.identity_key"
                " WHERE s.started_at >= ? AND e.kind = 'gift' AND e.time >= ?"
                f" AND e.identity_key IS NOT NULL AND e.identity_key NOT IN ({placeholders})"
                " GROUP BY e.identity_key"
                " HAVING SUM(e.diamonds) >= ?"
                "  AND COALESCE(NULLIF(MAX(u.unique_id), ''), MAX(e.user_unique_id)) <> ''"
                "  AND COALESCE(NULLIF(MAX(u.unique_id), ''), MAX(e.user_unique_id))"
                "      NOT GLOB ?"
                "  AND (MAX(u.league_checked_at) IS NULL OR MAX(u.league_checked_at) <= ?)",
                (now, since - _SESSION_LOOKBACK_SECONDS, since, *NON_IDENTITY_KEYS,
                 min_coin, _VALID_HANDLE_GLOB, now - recheck_seconds),
            )
            self._conn.commit()
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    def next_gifter_league_target(self, now: Optional[float] = None) -> Optional[dict]:
        """待ち行列の先頭1件。既知のroom_idも返す(終了済みの室でも引けるので使い回す)。"""
        now = time.time() if now is None else now
        with self._lock:
            row = self._conn.execute(
                "SELECT q.identity_key, q.unique_id, q.attempts,"
                " COALESCE(u.broadcaster_room_id, '') AS room_id"
                " FROM league_queue q LEFT JOIN users u ON u.identity_key = q.identity_key"
                " WHERE q.next_attempt_at <= ?"
                " ORDER BY q.enqueued_at, q.identity_key LIMIT 1",
                (now,),
            ).fetchone()
        return dict(row) if row is not None else None

    def save_gifter_league(
        self,
        identity_key: str,
        broadcaster: bool,
        room_id: str = "",
        league: str = "",
        now: Optional[float] = None,
    ) -> None:
        """取得結果を確定して待ち行列から降ろす。

        leagueの生値をそのまま保存する。D帯を落とすのは表示側の判断で、ここで捨てると
        判断を変えたときに取り直しになる(tictok/core/league.py 参照)。
        """
        now = time.time() if now is None else now
        with self._lock:
            # gifterのusers行は取り込み時に作られるが、行が無いまま結果を捨てないよう
            # 先に確保する(捨てると待ち行列だけ減って永久に取り直されない)。
            self._conn.execute(
                "INSERT OR IGNORE INTO users (identity_key, first_seen, last_seen)"
                " VALUES (?, ?, ?)",
                (identity_key, now, now),
            )
            self._conn.execute(
                "UPDATE users SET broadcaster = ?, broadcaster_room_id = ?, league = ?,"
                " league_checked_at = ? WHERE identity_key = ?",
                (1 if broadcaster else 0, room_id or "", league or "", now, identity_key),
            )
            self._conn.execute(
                "DELETE FROM league_queue WHERE identity_key = ?", (identity_key,)
            )
            self._conn.commit()

    def defer_gifter_league(
        self, identity_key: str, error: str, retry_after: float, max_attempts: int
    ) -> bool:
        """失敗を記録して再試行を先送りする。上限に達したら待ち行列から降ろす。

        降ろすときも users には何も書かない。「確認したが配信者ではなかった」と「確認でき
        なかった」を同じ値にしないためで、翌日giftすれば未確認として積み直される。
        戻り値は「まだ待ち行列に残っているか」。
        """
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT attempts FROM league_queue WHERE identity_key = ?", (identity_key,)
            ).fetchone()
            if row is None:
                return False
            attempts = int(row["attempts"]) + 1
            if attempts >= max_attempts:
                self._conn.execute(
                    "DELETE FROM league_queue WHERE identity_key = ?", (identity_key,)
                )
                self._conn.commit()
                logger.warning(
                    "リーグ取得を %d 回失敗したため待ち行列から降ろしました（%s）: %s",
                    attempts, identity_key, error,
                    extra={"event": "league.queue_dropped",
                           "ctx": {"identity_key": identity_key, "attempts": attempts,
                                   "error": error}},
                )
                return False
            self._conn.execute(
                "UPDATE league_queue SET attempts = ?, next_attempt_at = ?, last_error = ?"
                " WHERE identity_key = ?",
                (attempts, now + retry_after, error[:200], identity_key),
            )
            self._conn.commit()
        return True

    def gifter_league_stats(self) -> dict:
        """待ち行列と取得済みの件数。運用画面とlogの両方から同じ数字を見るため。"""
        with self._lock:
            pending = self._conn.execute(
                "SELECT COUNT(*) AS n, MIN(enqueued_at) AS oldest FROM league_queue"
            ).fetchone()
            done = self._conn.execute(
                "SELECT COUNT(*) AS checked,"
                " SUM(CASE WHEN broadcaster = 1 THEN 1 ELSE 0 END) AS broadcasters,"
                " SUM(CASE WHEN league <> '' THEN 1 ELSE 0 END) AS with_league"
                " FROM users WHERE league_checked_at IS NOT NULL"
            ).fetchone()
        return {
            "pending": pending["n"] or 0,
            "oldest_enqueued_at": pending["oldest"],
            "checked": done["checked"] or 0,
            "broadcasters": done["broadcasters"] or 0,
            "with_league": done["with_league"] or 0,
        }
