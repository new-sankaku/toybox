"""全体解析(配信者横断)のsession単位cacheと集計API。

境界の理由: 集計そのものは tictok.analytics が持ち、ここはその入出力(payloadの
永続化cacheと、cacheからの読み出し)だけを担う。cacheの版管理(CACHE_VERSIONS)と
再計算契機を1箇所に閉じることが目的。

lock契約:
  _refresh_session_analytics_locked は self._lock 保持前提。呼び出し元は
  recover_from_journal(ingest)と finalize_session(sessions)で、どちらもlock区間の内側。
  _ensure_analytics_cache / _analytics_rows は自分で self._lock を取る。
"""
import json
import time

from tictok import analytics
from tictok.core.config import get_log_progress_interval_seconds
from tictok.core.logging_setup import progress_interval_seconds
from tictok.core.progress import IntervalGate

from tictok.store._common import SESSION_STATUS_RESTRICTED, _EXCLUDE_RESTRICTED, logger


class AnalyticsMixin:
    """全体解析(配信者横断)のsession単位cacheと集計API。

    lockもDB接続も持たない。すべて Storage が所有する self._conn /
    self._lock / self._read_lock を借りる(mixinとして Storage に混ぜられる前提)。
    契約の詳細はmodule docstringを参照。
    """

    # ---- 全体解析(配信者横断) ------------------------------------------
    # 監視配信者を横断した集約。新規収集は行わず既存DBの再集約のみ。集約は配信(session)
    # 単位の中間集計(payload)までに留めてanalytics_session_cacheへ永続化する(終了済み
    # sessionは不変なので1回だけ計算し、収集中sessionは毎回その場で計算)。全体へ丸めた
    # 集約を持たないため、配信者データの削除はsessionsのON DELETE CASCADEで整合が保てる。
    # sinceは集計対象の下限started_at(0=全期間)。母集団のサンプル数を各所で返し、
    # 少数での断定を防ぐ。

    _ANALYTICS_SESSION_SELECT = (
        "SELECT s.id AS id, s.unique_id AS unique_id, s.started_at AS started_at,"
        " s.ended_at AS ended_at, s.bucket_seconds AS bucket_seconds, s.status AS status,"
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

    def _ensure_analytics_cache(self, kind: str) -> int:
        """終了済みで未計算(またはlogic version不一致)のsessionのpayloadを計算・保存する。
        finalizeを通らず終了したsession(異常終了の復旧等)もここで拾う。

        **lockはsession 1件ごとに取り直す(lock保持のまま全件回さない)**。CACHE_VERSIONSを
        1つ上げると全履歴が再計算対象になり、以前はその全走査をDB lockを握ったまま行って
        いた。待たされるのは解析画面だけではない: 同じlockを使う全ての読み書き — 別tabの
        録画一覧も、収集中sessionのevent書き込みも — が止まるため、userには「アプリ全体が
        固まった」ように見える。1件ごとに手放せば、他のrequestがその隙間へ入れる。

        件数が変わるのは「他のrequestが割り込める」点だけで、結果は変わらない。埋めている
        最中に追加されたsessionはcacheに載らないまま読み出しへ抜けるが、その場合は
        _analytics_rows がその場で計算する経路(収集中sessionと同じ)へ落ちる。
        """
        version = analytics.CACHE_VERSIONS[kind]
        with self._lock:
            rows = self._conn.execute(
                self._ANALYTICS_SESSION_SELECT
                + " FROM sessions s"
                " LEFT JOIN analytics_session_cache c ON c.session_id = s.id AND c.kind = ?"
                " WHERE s.ended_at IS NOT NULL AND (c.session_id IS NULL OR c.version != ?)"
                + _EXCLUDE_RESTRICTED,
                (kind, version),
            ).fetchall()
        gate = IntervalGate(progress_interval_seconds(get_log_progress_interval_seconds()))
        for index, row in enumerate(rows):
            # 1件ぶんの計算と書き込みだけをlockの中で行う。connectionはthread safeでは
            # ないので、計算をlockの外へ出すことはできない(隙間を作るのが目的で、
            # 排他を弱めるのが目的ではない)。
            with self._lock:
                payload = analytics.compute_payload(
                    self._conn, self._analytics_sess_dict(row), kind
                )
                self._conn.execute(
                    "INSERT OR REPLACE INTO analytics_session_cache"
                    " (session_id, kind, version, payload_json, computed_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (row["id"], kind, version, json.dumps(payload), time.time()),
                )
            if gate.ready():
                logger.info(
                    "解析cache: session %d/%d 件を計算しました（kind=%s）",
                    index + 1, len(rows), kind,
                    extra={"event": "analytics.cache_progress",
                           "ctx": {"kind": kind, "done": index + 1, "total": len(rows)}},
                )
        if rows:
            with self._lock:
                self._conn.commit()
            logger.info(
                "解析cache: session %d 件を計算しました（kind=%s）", len(rows), kind
            )
        return len(rows)

    def _analytics_rows(self, kind: str, since: float) -> list:
        """(sessionメタ, per-session payload)の列をstarted_at昇順で返す。終了済みは
        cacheから読み、収集中sessionはその場で計算する(session単位indexで軽い)。

        収集中sessionのその場計算はbufferではなくDBを読むため、先に確定させる。終了済み
        分はfinalize_sessionがflush後にcacheを作るので既に整合している。"""
        self.flush()
        # cache埋めはlockの外で行う(中で1件ごとに取り直す)。ここをlockの中へ戻すと、
        # 全session再計算のあいだDBに触る全ての処理が止まる。
        self._ensure_analytics_cache(kind)
        with self._lock:
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
        # 制限sessionはevent 0件なので全体解析の対象外(cacheも作らない)。
        if row["status"] == SESSION_STATUS_RESTRICTED:
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

    def analytics_entry_source(self, since: float = 0.0) -> dict:
        """流入元(clientEnterSource)と視聴者のfollow関係の内訳。計装前のsessionは
        計測不能として分母から外し、被覆率を併記する。"""
        # 収集中sessionはその場でeventを読むため、batch writerに滞留した分を先に確定する。
        self.flush()
        return analytics.reduce_entry_source(self._analytics_rows("entry_source", since))

    def analytics_battle_flow(self, since: float = 0.0) -> dict:
        """Battle展開(残り時間軸): リード交代・残り1分時点のリード別勝率・終盤集中度。"""
        return analytics.reduce_battle_flow(self._analytics_rows("battle_flow", since))

    def analytics_coverage(self, since: float = 0.0) -> dict:
        """収集カバレッジ: 開始遅延・切断欠測・sampling間隔・録画率・STT率。

        録画のended_atも転写もsessionが終わった後から埋まるため、この2つはsession単位
        payload cacheへ載せず、都度素データから集計する(cacheすると永久に古い値になる)。"""
        # 収集中sessionのsampling間隔はviewer_samplesをその場で読むため、batch writerに
        # 滞留したsampleを先に確定させる(読み取り前flush)。
        self.flush()
        rows = self._analytics_rows("coverage", since)
        with self._lock:
            media = self._conn.execute(
                "SELECT r.session_id AS session_id, r.started_at AS started_at,"
                " r.ended_at AS ended_at, r.status AS status,"
                " (t.recording_id IS NOT NULL) AS has_transcript"
                " FROM recordings r"
                " JOIN sessions s ON s.id = r.session_id"
                " LEFT JOIN transcripts t ON t.recording_id = r.id"
                " WHERE s.started_at >= ?" + _EXCLUDE_RESTRICTED,
                (since,),
            ).fetchall()
        return analytics.reduce_coverage(rows, media)

    def analytics_organic_entries(self, since: float = 0.0) -> dict:
        """organic入室(§15): ノイズ入室を落としたgenuineness weight付き時間帯カーブ。"""
        return analytics.reduce_organic(self._analytics_rows("organic", since))
