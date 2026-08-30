"""session lifecycle・session単位の読み出し・bucket再構築。

境界の理由: sessions表とその従属表(markers / buckets / envelopes / collab_windows)を
1つの単位として扱う。stats/bucketの再計算helperをここに置くのは、呼び出し元4箇所のうち
3箇所(finalize_session / cleanup_stale_sessions / backfill_missing_buckets)が
sessionのlifecycle methodだからである。

lock契約:
  以下は self._lock 保持前提。呼び出し元は必ず with self._lock: の内側にいる:
    _recompute_session_stats_locked  <- recover_from_journal(ingest)
    _rebuild_buckets_locked          <- recover_from_journal(ingest) /
                                       cleanup_stale_sessions / backfill_missing_buckets
    _fill_missing_buckets_locked     <- finalize_session
    _append_markers_locked           <- finalize_session / append_markers
  delete_session は self._lock を取ってから DELETE する。これは飾りではなく、
  batch writer(_drain)の孤児判定〜commitと同じlockで直列化するための契約である
  (ingest mixin の _drain のcomment参照)。lockを外すとTOCTOUが復活する。
"""
import json
import time
from typing import Optional

from tictok.store._common import (
    CONN_INSTRUMENTATION_VERSION,
    SESSION_STATUS_RESTRICTED,
    _session_row_to_dict,
    _valid_owner_id,
    logger,
)


class SessionsMixin:
    """session lifecycle・session単位の読み出し・bucket再構築。

    lockもDB接続も持たない。すべて Storage が所有する self._conn /
    self._lock / _read_connection() を借りる(mixinとして Storage に混ぜられる前提)。
    契約の詳細はmodule docstringを参照。
    """

    def _recompute_session_stats_locked(self, session_id: int,
                                        provenance: str = "recovered") -> None:
        """restore後、eventからstats_jsonのevent由来項目を再構成する。集計の定義は
        cleanup_stale_sessionsと厳密に一致させる(likes=count合計/gifts=gift_count合計等)。
        viewers系はviewer_samplesのground truthから補う。

        provenanceは「なぜ作り直したか」をstats_jsonへ残すkey。既定の 'recovered' は
        journalからの復元で、確定後に行が増えたことを表す。行が減る作り直し(接続時の
        遡りの掃除など)を同じ名前で残すと、後から読んだときに増減が逆に読める。"""
        agg = self._conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN kind='gift' THEN gift_count ELSE 0 END),0) gifts,"
            " COALESCE(SUM(CASE WHEN kind='gift' THEN diamonds ELSE 0 END),0) diamonds,"
            " COALESCE(SUM(CASE WHEN kind='comment' THEN 1 ELSE 0 END),0) comments,"
            " COALESCE(SUM(CASE WHEN kind='join' THEN 1 ELSE 0 END),0) joins,"
            " COALESCE(SUM(CASE WHEN kind='follow' THEN 1 ELSE 0 END),0) follows,"
            " COALESCE(SUM(CASE WHEN kind='share' THEN 1 ELSE 0 END),0) shares,"
            " COALESCE(SUM(CASE WHEN kind='like' THEN count ELSE 0 END),0) likes,"
            " COALESCE(SUM(CASE WHEN kind='subscribe' THEN 1 ELSE 0 END),0) subscribes,"
            " COALESCE(SUM(CASE WHEN kind='battle' THEN 1 ELSE 0 END),0) battles,"
            " COUNT(*) events_total FROM events WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        vw = self._conn.execute(
            "SELECT MAX(viewers) peak, MAX(total_viewers) total FROM viewer_samples WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        row = self._conn.execute(
            "SELECT stats_json FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        stats = json.loads(row["stats_json"]) if row and row["stats_json"] else {}
        stats.update({
            "likes_total": agg["likes"],
            "comments": agg["comments"],
            "gifts": agg["gifts"],
            "diamonds": agg["diamonds"],
            "follows": agg["follows"],
            "shares": agg["shares"],
            "joins": agg["joins"],
            "subscribes": agg["subscribes"],
            "battles": agg["battles"],
            "events_total": agg["events_total"],
            provenance: True,
        })
        if vw and vw["peak"] is not None:
            stats["viewers_peak"] = max(stats.get("viewers_peak") or 0, vw["peak"])
        self._conn.execute(
            "UPDATE sessions SET stats_json = ? WHERE id = ?",
            (json.dumps(stats), session_id),
        )

    def _rebuild_buckets_locked(self, session_id: int, bucket_seconds: int) -> None:
        """restore後のeventからtimeline bucketを再構成する。各指標はeventの厳密な集計
        (bucketの定義と一致)、viewersはbucket窓内のviewer_samples最大値(ground truth)。"""
        bs = int(bucket_seconds) or 10
        self._conn.execute("DELETE FROM buckets WHERE session_id = ?", (session_id,))
        self._conn.execute(
            "INSERT INTO buckets (session_id, start, gifts, diamonds, comments, likes, joins, follows, shares, viewers)"
            " SELECT ?, CAST(time / ? AS INTEGER) * ?,"
            " COALESCE(SUM(CASE WHEN kind='gift' THEN gift_count END),0),"
            " COALESCE(SUM(CASE WHEN kind='gift' THEN diamonds END),0),"
            " COALESCE(SUM(CASE WHEN kind='comment' THEN 1 END),0),"
            " COALESCE(SUM(CASE WHEN kind='like' THEN count END),0),"
            " COALESCE(SUM(CASE WHEN kind='join' THEN 1 END),0),"
            " COALESCE(SUM(CASE WHEN kind='follow' THEN 1 END),0),"
            " COALESCE(SUM(CASE WHEN kind='share' THEN 1 END),0), 0"
            " FROM events WHERE session_id = ? GROUP BY CAST(time / ? AS INTEGER)",
            (session_id, bs, bs, session_id, bs),
        )
        self._conn.execute(
            "UPDATE buckets SET viewers = COALESCE((SELECT MAX(vs.viewers) FROM viewer_samples vs"
            " WHERE vs.session_id = buckets.session_id AND vs.time >= buckets.start"
            " AND vs.time < buckets.start + ?), viewers) WHERE session_id = ?",
            (bs, session_id),
        )

    def _fill_missing_buckets_locked(self, session_id: int, bucket_seconds: int) -> int:
        """eventに在るのにbucketが無い時間帯だけをeventから補い、補った本数を返す。

        collector側のtimelineはdeque(既定2160 = 10秒bucketで6時間)で、超えると**先頭から**
        落ちる。確定時にそのdequeでbucketを全置換するので、6時間を超える配信は**冒頭が
        丸ごと消える**(実測で3 sessionが上限ちょうどの2160本、計1.89時間の欠落)。

        既存のbucketは1本も書き換えない。生きているbucketには収集中に観測したviewersが
        入っており、eventから作り直すとviewer_samplesのsample間隔ぶんだけ粗くなる。
        欠けている時間帯だけを足す。
        """
        bs = int(bucket_seconds) or 10
        cur = self._conn.execute(
            "INSERT INTO buckets (session_id, start, gifts, diamonds, comments, likes, joins, follows, shares, viewers)"
            " SELECT ?, CAST(time / ? AS INTEGER) * ?,"
            " COALESCE(SUM(CASE WHEN kind='gift' THEN gift_count END),0),"
            " COALESCE(SUM(CASE WHEN kind='gift' THEN diamonds END),0),"
            " COALESCE(SUM(CASE WHEN kind='comment' THEN 1 END),0),"
            " COALESCE(SUM(CASE WHEN kind='like' THEN count END),0),"
            " COALESCE(SUM(CASE WHEN kind='join' THEN 1 END),0),"
            " COALESCE(SUM(CASE WHEN kind='follow' THEN 1 END),0),"
            " COALESCE(SUM(CASE WHEN kind='share' THEN 1 END),0), 0"
            " FROM events e WHERE e.session_id = ?"
            " GROUP BY CAST(time / ? AS INTEGER)"
            " HAVING NOT EXISTS (SELECT 1 FROM buckets b WHERE b.session_id = ?"
            "                    AND b.start = CAST(e.time / ? AS INTEGER) * ?)",
            (session_id, bs, bs, session_id, bs, session_id, bs, bs),
        )
        filled = cur.rowcount or 0
        if filled:
            self._conn.execute(
                "UPDATE buckets SET viewers = COALESCE((SELECT MAX(vs.viewers) FROM viewer_samples vs"
                " WHERE vs.session_id = buckets.session_id AND vs.time >= buckets.start"
                " AND vs.time < buckets.start + ?), viewers)"
                " WHERE session_id = ? AND viewers = 0",
                (bs, session_id),
            )
        return filled

    def cleanup_stale_sessions(self) -> int:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, bucket_seconds FROM sessions"
                " WHERE status IN ('connecting', 'connected', 'reconnecting')"
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
                # bucketも必ず作る。ここを飛ばすと、見どころ・切り抜き候補・heat bar・
                # peak_viewersが「静かに空」になる(実測でsession 144本中60本がこの状態だった)。
                # 落ちるのは長時間で不安定な配信に偏るため、欠けたことに気付く手段が無い。
                self._rebuild_buckets_locked(session_id, row["bucket_seconds"])
            self._conn.commit()
        if rows:
            logger.warning("前回起動時の中断session %d 件を回収しました", len(rows))
        return len(rows)

    def backfill_missing_buckets(self) -> int:
        """eventを持つのにbucketが無いsessionのbucketを作り直し、直した数を返す。

        cleanup_stale_sessionsが長らくbucketを作らなかったため、process強制終了で回収された
        sessionにbucketが残っていない。そのsessionでは見どころ・切り抜き候補・heat bar・
        peak_viewersが黙って空になる。bucketはeventとviewer_samplesから完全に再構成できる
        ので、起動時に一度だけ埋める。

        bucketが1本でも在るsessionには触らない。既存のbucketには収集中にしか採れない値
        (viewersの実測)が入っており、再構成で上書きするとその瞬間の観測を失う。
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT s.id, s.bucket_seconds FROM sessions s"
                " WHERE NOT EXISTS (SELECT 1 FROM buckets b WHERE b.session_id = s.id)"
                "   AND EXISTS (SELECT 1 FROM events e WHERE e.session_id = s.id)"
            ).fetchall()
            for row in rows:
                self._rebuild_buckets_locked(row["id"], row["bucket_seconds"])
            if rows:
                self._conn.commit()
        if rows:
            total = self._conn.execute(
                "SELECT COUNT(*) AS n FROM buckets WHERE session_id IN (%s)"
                % ",".join("?" * len(rows)),
                [row["id"] for row in rows],
            ).fetchone()["n"]
            logger.warning(
                "session %d 件のbucketを作り直しました（bucket %d 本）", len(rows), total,
                extra={"event": "storage.buckets_backfilled",
                       "ctx": {"sessions": len(rows), "buckets": total,
                               "session_ids": [row["id"] for row in rows][:50]}},
            )
        return len(rows)

    def create_session(self, unique_id: str, bucket_seconds: int) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO sessions (unique_id, status, started_at, bucket_seconds,"
                " conn_instrumentation) VALUES (?, ?, ?, ?, ?)",
                (unique_id, "connecting", time.time(), bucket_seconds,
                 CONN_INSTRUMENTATION_VERSION),
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
            # bucketも同じ理由で欠ける。上のtimelineはdequeなので上限超過時は先頭が落ちて
            # おり、全置換した直後のbucketには冒頭が無い。eventに在って欠けている時間帯
            # だけを足す(既存bucketのviewersは触らない)。
            bucket_seconds = (self._conn.execute(
                "SELECT bucket_seconds FROM sessions WHERE id = ?", (session_id,)
            ).fetchone() or {"bucket_seconds": 10})["bucket_seconds"]
            filled = self._fill_missing_buckets_locked(session_id, bucket_seconds)
            # markerだけは追記(全置換ではない)。collector側のdequeが上限を超えたsessionでは
            # 途中checkpointで残した古いmarkerがメモリ上に無いため、全置換すると確定時に
            # それらを消してしまう。
            self._append_markers_locked(session_id, markers)
            self._conn.commit()
            # 確定したsessionの全体解析payloadをここで1回だけ計算して永続化する。
            self._refresh_session_analytics_locked(session_id)
        if filled:
            logger.warning(
                "session %d: memory上のtimelineに無かったbucket %d 本をeventから補いました",
                session_id, filled,
                extra={"event": "storage.buckets_filled_from_events",
                       "ctx": {"session_id": session_id, "filled": filled,
                               "timeline_buckets": len(timeline)}},
            )
        logger.info("sessionを確定しました: id=%d status=%s", session_id, status)

    def list_sessions(self, limit: int) -> list:
        # limit<=0は全件(履歴のfilter/検索が最新N件に頭打ちにならないよう)。SQLiteはLIMIT -1で無制限。
        sql_limit = limit if limit and limit > 0 else -1
        with self._lock:
            rows = self._conn.execute(
                "SELECT s.*,"
                " (SELECT COUNT(*) FROM recordings r WHERE r.session_id = s.id"
                "  AND r.status IN ('completed', 'interrupted')) AS recording_count,"
                " (SELECT MAX(viewers) FROM buckets b WHERE b.session_id = s.id)"
                "  AS bucket_peak_viewers"
                " FROM sessions s ORDER BY s.started_at DESC LIMIT ?",
                (sql_limit,),
            ).fetchall()
        return [self._fill_owner(_session_row_to_dict(row)) for row in rows]

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
        return self._fill_owner(_session_row_to_dict(row))

    def set_note(self, session_id: int, note: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE sessions SET note = ? WHERE id = ?", (note, session_id)
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def delete_session(self, session_id: int) -> bool:
        # sessionを消すと、まだwriterがdrainしていない同sessionのbuffer済みevent/viewerは
        # 参照先を失う(events/viewer_samplesはsessions(id)へFK)。そのままdrainすると
        # FK違反でbatchごと失敗し、_drainの再キューで永久に詰まる(poison-pill)。
        # 削除に先立ちbufferから該当sessionの行を取り除き、孤児を作らない。
        with self._buf_lock:
            self._event_buffer = [e for e in self._event_buffer if e[0] != session_id]
            self._viewer_buffer = [v for v in self._viewer_buffer if v[0] != session_id]
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM sessions WHERE id = ?", (session_id,)
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def find_restricted_session(self, unique_id: str, room_id) -> Optional[int]:
        """同一roomについて既に書かれている制限sessionのidを返す(無ければNone)。
        制限holdは再確認のたびにconnectを撃ち直すため、1つの配信で制限行が何本も
        並びうる。DBに問い合わせて畳み込むことで、collector側の状態に依存せず
        (プロセス再起動を跨いでも)1 room = 1行を保てる。"""
        if room_id is None:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM sessions"
                " WHERE unique_id = ? AND room_id = ? AND status = ?"
                " ORDER BY started_at LIMIT 1",
                (unique_id, str(room_id), SESSION_STATUS_RESTRICTED),
            ).fetchone()
        return row["id"] if row is not None else None

    def extend_session_end(self, session_id: int) -> None:
        """sessionの終了時刻を現在時刻まで延ばす。畳み込んだ制限行が「最後にいつまで
        録画できない状態だったか」を示すようにするため。"""
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET ended_at = ? WHERE id = ?", (time.time(), session_id)
            )
            self._conn.commit()

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
        return self.sessions_summary([session_id])

    def sessions_summary(self, session_ids: list) -> dict:
        """複数sessionをまとめた貢献集計(1件なら従来のsession詳細と同じ)。

        履歴の「マージ表示」はこの1本しか使えない。client側で各sessionの結果を足すのは
        2つの理由で誤る: ①この一覧は ``LIMIT 100`` で切ってあるので、どのsessionでも
        101位のuserは合算しても現れない ②名寄せの鍵 identity_key はAPIへ出しておらず、
        @handleで突き合わせると改名したuserが別人に割れる。合算はSQLのGROUP BYで行う。"""
        if not session_ids:
            return {"users": [], "gifts": []}
        ph = ",".join("?" * len(session_ids))
        ids = tuple(session_ids)
        with self._lock:
            # 表示属性はその時(このSession)のsnapshotを優先し、欠けていればusers表(最新)へ
            # fallbackする。名寄せ(identity_key)と切り離すことで過去の見え方を保持する。
            user_rows = self._conn.execute(
                "SELECT e.identity_key AS key,"
                " COALESCE(NULLIF(MAX(e.user_id), ''), u.user_id) AS user_id,"
                " COALESCE(NULLIF(MAX(e.user_unique_id), ''), u.unique_id) AS unique_id,"
                " COALESCE(NULLIF(MAX(e.user_nickname), ''), u.nickname) AS nickname,"
                # avatar/badgeは event_strings へinternしてある。**MAX(...\_id) にしては
                # ならない** ―― 元のMAXは値そのものの辞書順最大で、idの最大(=最初に見た順)
                # とは別物である。値へJOINしてから MAX を採ることで、旧と同じ行が出る。
                # NULL(計装前で未計測)はid列もNULL、空文字はevent_stringsに1行を持つので、
                # 下のNULLIFはinternの前後で同じに働く。
                " COALESCE(NULLIF(MAX(av.value), ''), u.avatar) AS avatar,"
                " SUM(e.gift_count) AS gifts, SUM(e.diamonds) AS diamonds,"
                # Lv/badgeはその時点で変動する属性。users表(最新)へfallbackすると過去の値を
                # 捏造するため、このSessionのevent(point-in-time)のみ。無ければ非表示。
                " NULLIF(MAX(e.user_fans_level), 0) AS fans_level,"
                " NULLIF(MAX(e.user_gifter_level), 0) AS gifter_level,"
                " NULLIF(MAX(gbv.value), '') AS gifter_badge,"
                " NULLIF(MAX(mbv.value), '') AS member_badge"
                " FROM events e LEFT JOIN users u ON u.identity_key = e.identity_key"
                " LEFT JOIN event_strings av ON av.id = e.user_avatar_id"
                " LEFT JOIN event_strings gbv ON gbv.id = e.user_gifter_badge_id"
                " LEFT JOIN event_strings mbv ON mbv.id = e.user_member_badge_id"
                f" WHERE e.session_id IN ({ph}) AND e.kind = 'gift'"
                " GROUP BY e.identity_key ORDER BY diamonds DESC, gifts DESC LIMIT 100",
                ids,
            ).fetchall()
            # gift_id/gift_imageはicon表示のための身元。gift_nameとは1対1なので、この
            # groupの中では代表値を1つ取れば足りる(gift_imageは古いeventでNULLになり得る
            # ため、MAXで値のある行を拾う)。
            item_rows = self._conn.execute(
                "SELECT identity_key AS key,"
                " gift_name, SUM(gift_count) AS count, SUM(diamonds) AS diamonds,"
                " MAX(gift_id) AS gift_id, MAX(gift_image) AS gift_image"
                f" FROM events WHERE session_id IN ({ph}) AND kind = 'gift'"
                " GROUP BY identity_key, gift_name",
                ids,
            ).fetchall()
            gift_rows = self._conn.execute(
                "SELECT gift_name AS name, SUM(gift_count) AS count, SUM(diamonds) AS diamonds,"
                " MAX(CASE WHEN gift_count > 0 THEN diamonds / gift_count ELSE 0 END) AS diamonds_each,"
                " MAX(gift_id) AS gift_id, MAX(gift_image) AS gift_image"
                f" FROM events WHERE session_id IN ({ph}) AND kind = 'gift'"
                " GROUP BY gift_name ORDER BY diamonds DESC, count DESC LIMIT 100",
                ids,
            ).fetchall()
        items_by_user: dict = {}
        for row in item_rows:
            items_by_user.setdefault(row["key"], {})[row["gift_name"]] = {
                "count": row["count"] or 0,
                "diamonds": row["diamonds"] or 0,
                "gift_id": int(row["gift_id"] or 0),
                "gift_image": row["gift_image"] or "",
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
        gifts = []
        for row in gift_rows:
            gift = dict(row)
            gift["gift_id"] = int(gift.get("gift_id") or 0)
            gift["gift_image"] = gift.get("gift_image") or ""
            gifts.append(gift)
        return {"users": users, "gifts": gifts}

    def session_comments(self, session_id: int, limit: int) -> list:
        """Most recent comment texts for a session, for AI analysis. The text lives in
        the `comment` column (add_event stores entry['comment']); fall back to `text`.

        本文が空の行はSQL側で落とす。Python側で落とすとLIMITが空行込みで先に効き、
        直近が空commentばかりのsessionで要求件数より少なく(最悪0件)返ってしまう。
        「空」の定義はNULLと空文字だけ(空白のみの本文は落とさない)。"""
        self.flush()
        with self._lock:
            rows = self._conn.execute(
                "SELECT comment, text FROM events"
                " WHERE session_id = ? AND kind = 'comment'"
                " AND COALESCE(NULLIF(comment, ''), NULLIF(text, '')) IS NOT NULL"
                " ORDER BY time DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [(row["comment"] or row["text"] or "") for row in rows]

    def iter_events(self, session_id: int, start: float | None = None, end: float | None = None,
                    kinds=None) -> list:
        """Events for a session, ordered by arrival time. When start/end (wall-clock
        seconds, the same axis as recorder.started_at) are given, only events inside
        [start, end] are returned so a single recording of a multi-recording session
        is fed only its own events, not the whole session's.

        kindsを渡すとその種別だけをSQL側で絞る(Noneは全kind)。呼び出し側が全kindを読んで
        からPythonで捨てるのは、必要量の何倍もの行を運ぶことになる — likeとjoinだけで
        event全体の81%を占めるため、commentだけが要る用途では実測7倍の行を読んでいた。
        idx_events_session_kind_time(session_id, kind, time)がそのまま効く形にしてある。
        空のkindsは「どの種別も許さない」であって全kindではないので、0件を返す。"""
        if kinds is not None:
            kinds = list(kinds)
            if not kinds:
                return []
        self.flush()
        sql = (
            "SELECT time, create_time, kind, user_unique_id, user_nickname, text, comment, gift_name, gift_count, diamonds, count, gift_image, gift_id, emotes"
            " FROM events WHERE session_id = ?"
        )
        params: list = [session_id]
        if kinds is not None:
            sql += " AND kind IN (%s)" % ",".join("?" * len(kinds))
            params.extend(kinds)
        if start is not None:
            sql += " AND time >= ?"
            params.append(start)
        if end is not None:
            sql += " AND time <= ?"
            params.append(end)
        sql += " ORDER BY time"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def _append_markers_locked(self, session_id: int, markers: list) -> int:
        """未保存のmarkerだけをINSERTする(既存行は消さない)。DELETE→INSERTの全置換に
        してはいけない: collector側のmarkerは容量上限つきdequeで保持されるため、上限を
        超えたsessionでは「既に永続化した古いmarkerがメモリ上から消えている」状態が正常に
        起きる。そこで全置換すると、既に残した行をcheckpointが消し直してしまう。
        重複判定keyは(time, kind, label)。timeはepoch秒のfloatで、同一kind・同一labelが
        同一floatに乗ることは実質無いため、これで冪等になる。"""
        rows = self._conn.execute(
            "SELECT time, kind, label FROM markers WHERE session_id = ?", (session_id,)
        ).fetchall()
        stored = {(r["time"], r["kind"], r["label"]) for r in rows}
        fresh = [
            (session_id, m["time"], m["kind"], m["label"])
            for m in markers
            if (m["time"], m["kind"], m["label"]) not in stored
        ]
        if fresh:
            self._conn.executemany(
                "INSERT INTO markers (session_id, time, kind, label) VALUES (?, ?, ?, ?)",
                fresh,
            )
        return len(fresh)

    def append_markers(self, session_id: int, markers: list) -> None:
        """markerを中間永続化する。finalize_sessionと同じ追記方式なので、途中checkpointと
        最終確定のどちらが先でも結果は同じになる。非graceful終了で接続系marker(切断・再接続)
        やBattle/Collab markerが全損すると復元する手段が他に無いため、finalizeを待たずに残す。"""
        with self._lock:
            self._append_markers_locked(session_id, markers)
            self._conn.commit()

    def set_session_live_create_time(self, session_id: int, live_create_time: float) -> None:
        """room_infoが返す配信開始時刻(epoch秒)をsessionへ確定する。取得できない場合は
        呼ばない(NULLのまま=計測不能)。"""
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET live_create_time = ? WHERE id = ?",
                (live_create_time, session_id),
            )
            self._conn.commit()

    def save_envelopes(self, session_id: int, rows: list) -> None:
        """宝箱/Portalをsession単位で全置換する。battles/collab_windowsと同じ冪等な作法。

        collector側が envelope_id で重複を畳んだ結果を渡す前提。ここでUNIQUE制約を張らない
        のは、envelope_idがNULLで届く回(HIDE通知など)があり、NULL同士は制約で畳めないため
        (畳めない回を弾くと実測が欠ける)。
        """
        with self._lock:
            self._conn.execute("DELETE FROM envelopes WHERE session_id = ?", (session_id,))
            self._conn.executemany(
                "INSERT INTO envelopes (session_id, kind, envelope_id, time, create_time,"
                " business_type, diamond_count, people_count, trans_count, unpack_at,"
                " sender_user_id, sender_unique_id, data_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        session_id, r.get("kind") or "envelope", r.get("envelope_id"),
                        r.get("time"), r.get("create_time"), r.get("business_type"),
                        r.get("diamond_count"), r.get("people_count"), r.get("trans_count"),
                        r.get("unpack_at"), r.get("sender_user_id"),
                        r.get("sender_unique_id"),
                        json.dumps(r.get("data") or {}, ensure_ascii=False),
                    )
                    for r in rows
                ],
            )
            self._conn.commit()

    def session_envelopes(self, session_id: int) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT kind, envelope_id, time, create_time, business_type,"
                " diamond_count, people_count, trans_count, unpack_at,"
                " sender_user_id, sender_unique_id, data_json"
                " FROM envelopes WHERE session_id = ? ORDER BY time",
                (session_id,),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["data"] = json.loads(item.pop("data_json") or "{}")
            out.append(item)
        return out

    def save_collab_windows(self, session_id: int, windows: list) -> None:
        """コラボ(非BattleのLinkMic)接続窓を保存。Battle窓の差し引きは分析側で行う。

        versionは窓を作った判定ruleの版(core.collab.COLLAB_WINDOW_VERSION)。版を持たない
        窓は旧rule(v1)の収集物なので1として残す — 分析側が現行版だけを集計するための印で、
        ここで現行版を打ってしまうと旧dataが新ruleを名乗る。"""
        with self._lock:
            self._conn.execute("DELETE FROM collab_windows WHERE session_id = ?", (session_id,))
            self._conn.executemany(
                "INSERT INTO collab_windows"
                " (session_id, channel_id, start, end, guests_max, version, data_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        session_id,
                        str(w.get("channel_id") or ""),
                        w["start"],
                        w.get("end"),
                        w.get("guests_max", 0) or 0,
                        int(w.get("version") or 1),
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

    def coop_windows_for_session(self, session_id: int) -> dict:
        """このsessionの「誰かと一緒に映っていた/声が乗っていた」窓(wall-clock秒)。

        ``{"collab": [(start, end|None)], "battle": [(start, end|None)],
        "collab_observed": bool}``。終端が決まっていない窓は ``end=None`` で返す
        (収集断や進行中のBattle) — 呼び出し側が自分の窓の終わりでclipすること。

        **コラボは現行rule版の窓だけ**を返す(``core.collab.COLLAB_WINDOW_VERSION``)。
        旧rule(v1)はfinishでしか窓を閉じず、間のソロ時間を丸ごとコラボに数えていたので、
        混ぜると単独の場面まで一緒に外れる(streamer_profileと同じ扱い)。

        ``collab_observed`` は「このsessionが現行ruleでコラボを観測できた時期のものか」。
        境目は現行ruleで最初にコラボ窓を記録したsessionの開始時刻で、それより前のsessionは
        コラボが**無かった**のか**記録が無い**のかを区別できない。Falseの窓を「コラボ無し」
        として扱うと、外したつもりで1秒も外れていない結果を渡すことになる。

        Battleの時刻はTikTokのserver時計(battle_setting.*_ms)で、collab窓とsessionは
        こちらの時計である。両者を同じ軸として扱うのは共演構成(_coop_summary)と同じで、
        NTPの効いた環境では差は秒単位に収まる。
        """
        from tictok.core.collab import COLLAB_WINDOW_VERSION

        with self._lock:
            collab = self._conn.execute(
                "SELECT start, end FROM collab_windows"
                " WHERE session_id = ? AND version = ? ORDER BY start",
                (session_id, COLLAB_WINDOW_VERSION),
            ).fetchall()
            battle_rows = self._conn.execute(
                "SELECT data_json FROM battles WHERE session_id = ?", (session_id,)
            ).fetchall()
            since = self._conn.execute(
                "SELECT MIN(s.started_at) AS since FROM collab_windows cw"
                " JOIN sessions s ON s.id = cw.session_id WHERE cw.version = ?",
                (COLLAB_WINDOW_VERSION,),
            ).fetchone()["since"]
            started_at = self._conn.execute(
                "SELECT started_at FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        battles = []
        for row in battle_rows:
            battle = json.loads(row["data_json"] or "{}")
            # 中止された戦は枠として時間を使っていない(collectorも保存対象から外している)。
            if battle.get("aborted") or battle.get("start_time") is None:
                continue
            battles.append((float(battle["start_time"]), battle.get("end_time")))
        battles.sort()
        observed = (since is not None and started_at is not None
                    and started_at["started_at"] >= since)
        return {
            "collab": [(row["start"], row["end"]) for row in collab],
            "battle": battles,
            "collab_observed": bool(observed),
        }

    def session_buckets(self, session_id: int, start: float | None = None,
                        end: float | None = None) -> list:
        """sessionの時間bucket(既定10秒粒度)。録画窓で絞ればheat barの素材になる。"""
        sql = ("SELECT start, gifts, diamonds, comments, likes, joins, follows, shares, viewers"
               " FROM buckets WHERE session_id = ?")
        params: list = [session_id]
        if start is not None:
            sql += " AND start >= ?"
            params.append(start)
        if end is not None:
            sql += " AND start <= ?"
            params.append(end)
        sql += " ORDER BY start"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
