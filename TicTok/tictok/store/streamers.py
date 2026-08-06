"""配信者別の集計画面(履歴・profile・cohort・見どころ)と全体dashboard。

境界の理由: 「1人の配信者」あるいは「監視配信者の横並び」を人が読む形へ組み立てる
読み取り専用の集計。個々のtableのCRUDは持たず、他mixinが書いたものを読むだけである。
重い集計が集中するため、_read_connection() を使う箇所もここに偏る。

lock契約: lock保持前提のmethodは無い。身元解決(_owner_handles_locked /
  _latest_owner_handles_locked(users))を使うmethodは、その呼び出しだけを自分で取った
  self._lock の内側に置く。集計本体を _read_connection() で流すmethodはそれ以外に
  self._lock を取らない(session_rankings は身元解決を使わないため一度も取らない)。
"""
import json

from tictok.core.battle import annotate_result, gift_window_end, gift_window_fallback_duration
from tictok.core.league import display_league_sql

from tictok.store._common import (
    _BATTLE_KEY_CONTRIB_DIAMONDS,
    _EXCLUDE_RESTRICTED,
    _EXCLUDE_RESTRICTED_NO_ALIAS,
    _SESSION_TOTALS_CTE,
    _STREAMER_TOTALS_SELECT,
    _coop_summary,
    _covering_recording,
    _opponent_key,
    logger,
)


def _liver_share(
    row=None,
    gift_diamonds=0,
    checked_diamonds=0,
    liver_diamonds=0,
    gifters=0,
    checked_gifters=0,
    liver_gifters=0,
) -> dict:
    """ギフトに占めるライバー(自分でも配信している人)の割合を、2つの物差しで返す。

    コイン基準と人数基準は別物で、片方だけでは読み違える。1人の大口ライバーが居れば
    コイン比率は跳ね上がるが人数比率は動かない。逆に少額のライバーが大勢居れば人数比率
    だけが上がる。どちらの分母かを名前に持たせて、独立した項目として返す。

    **分母はどちらも全体**(そのギフト全額 / gift実績のある全員)。「コイン全体に占める
    ライバーの割合」という問いにそのまま答える形にする。リーグの確認は待ち行列で順に
    進むため、未確認の人はライバーに数えられない — つまりこの比率は**下限**で、確認が
    進むほど実態へ上がっていく。どこまで確認できているかは coverage で別に返す。

    確認が1件も済んでいなければ比率は None。そこを0%にすると「ライバーが居ないと確認
    できた」と読めてしまうが、実際には何も判っていない。
    """
    if row is not None:
        gift_diamonds = row["gift_diamonds"] or 0
        checked_diamonds = row["checked_diamonds"] or 0
        liver_diamonds = row["liver_diamonds"] or 0
        gifters = row["gifters"] or 0
        checked_gifters = row["checked_gifters"] or 0
        liver_gifters = row["liver_gifters"] or 0
    return {
        # コイン基準
        "liver_diamonds": liver_diamonds,
        "liver_gift_diamonds": gift_diamonds,
        "liver_coin_share": (
            (liver_diamonds / gift_diamonds * 100) if gift_diamonds and checked_diamonds else None
        ),
        "liver_checked_diamonds": checked_diamonds,
        "liver_coin_coverage": (checked_diamonds / gift_diamonds * 100) if gift_diamonds else 0.0,
        # 人数基準
        "liver_gifters": liver_gifters,
        "liver_total_gifters": gifters,
        "liver_gifter_share": (
            (liver_gifters / gifters * 100) if gifters and checked_gifters else None
        ),
        "liver_checked_gifters": checked_gifters,
        "liver_gifter_coverage": (checked_gifters / gifters * 100) if gifters else 0.0,
    }


class StreamersMixin:
    """配信者別の集計画面(履歴・profile・cohort・見どころ)と全体dashboard。

    lockもDB接続も持たない。すべて Storage が所有する self._conn /
    self._lock / self._read_lock を借りる(mixinとして Storage に混ぜられる前提)。
    契約の詳細はmodule docstringを参照。
    """

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
                + _EXCLUDE_RESTRICTED
                + " ORDER BY s.started_at DESC LIMIT ?",
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
        # GROUP BYは配信者identity(owner_user_id優先)。bare columnのs.unique_idは
        # SQLiteでは任意の行から取られ@handle改名者でラベルが不定になるため、表示用
        # handleは最新sessionのものを相関subqueryで決定的に選ぶ。
        conn = self._read_connection()
        rows = conn.execute(
            _SESSION_TOTALS_CTE + _STREAMER_TOTALS_SELECT +
            f" WHERE 1=1{_EXCLUDE_RESTRICTED}"
            " GROUP BY okey ORDER BY diamonds DESC, sessions DESC",
        ).fetchall()
        # 配信者ごとの「ギフトに占めるライバー(自分でも配信している人)の割合」。
        # 分子・分母をどちらもgift eventから採るのは、比率の両側を同じ物差しで測るため
        # (sessionのstats_jsonとgift eventは確定タイミングが違い、混ぜると比率が歪む)。
        # 未確認の人を「ライバーではない」に丸めると過小評価になるので、判定済みぶんを
        # 分母にした比率と、その判定済みが全体のどれだけかを別々に返す(実測65ms)。
        liver_rows = conn.execute(
            "SELECT COALESCE(NULLIF(s.owner_user_id, ''), s.unique_id) AS okey,"
            " COALESCE(SUM(e.diamonds), 0) AS gift_diamonds,"
            " COALESCE(SUM(CASE WHEN u.league_checked_at IS NOT NULL THEN e.diamonds"
            "  ELSE 0 END), 0) AS checked_diamonds,"
            f" COALESCE(SUM(CASE WHEN {display_league_sql('u')} <> '' THEN e.diamonds"
            "  ELSE 0 END), 0) AS liver_diamonds,"
            " COUNT(DISTINCT e.identity_key) AS gifters,"
            " COUNT(DISTINCT CASE WHEN u.league_checked_at IS NOT NULL"
            "  THEN e.identity_key END) AS checked_gifters,"
            f" COUNT(DISTINCT CASE WHEN {display_league_sql('u')} <> ''"
            "  THEN e.identity_key END) AS liver_gifters"
            " FROM events e JOIN sessions s ON s.id = e.session_id"
            " LEFT JOIN users u ON u.identity_key = e.identity_key"
            f" WHERE e.kind = 'gift'{_EXCLUDE_RESTRICTED}"
            " GROUP BY okey",
        ).fetchall()
        livers = {r["okey"]: r for r in liver_rows}
        with self._lock:
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
                    **_liver_share(livers.get(row["okey"])),
                }
            )
        return result

    def streamer_profile(self, unique_id: str, limit: int = 200) -> dict:
        """Cross-session profile for one streamer: lifetime/average/best metrics,
        per-session series, the streamer's own gifter base (with loyalty + revenue
        concentration), and battle record (win rate, scores, opponents, the share of
        revenue earned during battle windows). Peak viewers comes from buckets; the
        finalized stats keep only the last viewer count."""
        # 配信者1人ぶんのsession/gifter/heatmap/battleをまとめて引く。どれもこの配信者の
        # 全期間が対象で、書き込み接続で流すとその間collectorのevent書き出しが待たされる。
        # 身元解決(handle集合・最新owner)だけはwriter接続のhelperなのでlockの内側に残す。
        with self._lock:
            handles = self._owner_handles_locked(unique_id)
            owners = self._latest_owners()
        owner = owners.get(unique_id)
        conn = self._read_connection()
        ph = ",".join("?" * len(handles))
        session_rows = conn.execute(
            "SELECT s.id, s.started_at, s.ended_at, s.stats_json,"
            " (SELECT MAX(viewers) FROM buckets b WHERE b.session_id = s.id) AS peak_viewers"
            f" FROM sessions s WHERE s.unique_id IN ({ph})"
            + _EXCLUDE_RESTRICTED
            + " ORDER BY s.started_at DESC LIMIT ?",
            (*handles, limit),
        ).fetchall()
        # 表示属性はusers表(最新)を優先する。ここはsessionを跨いだ通算集計で、
        # 「そのSessionでの見え方」という基準が存在しないため、最新の身元で1人を1行に
        # 示すのが正しい。session単位のsession_summary/battle_gift_contributionsは逆に
        # point-in-timeを優先する(そちらは過去の見え方を保つのが目的)。
        #
        # event側をMAX()で優先してはいけない: MAX()は辞書順の最大を返すだけで「最新の
        # handle」ではない。実測では改名前の自動生成handle user5037930325926 が現handle
        # harehare12345 を、user9487377432719 が chikudenchi0807 を押しのけていた。
        gifter_rows = conn.execute(
            "SELECT e.identity_key AS key,"
            " COALESCE(NULLIF(u.user_id, ''), MAX(e.user_id)) AS user_id,"
            " COALESCE(NULLIF(u.unique_id, ''), MAX(e.user_unique_id)) AS unique_id,"
            " COALESCE(NULLIF(u.nickname, ''), MAX(e.user_nickname)) AS nickname,"
            " COALESCE(NULLIF(u.avatar, ''), MAX(e.user_avatar)) AS avatar, SUM(e.gift_count) AS gifts,"
            # Lv/badgeとリーグはusers表(最新)を使う。ここはsessionを跨いだ通算集計で、
            # 「そのSessionでの見え方」という基準が存在しないため、identity列と同じく最新の
            # 値で1人を1行に示すのが正しい(point-in-time厳守はsession単位の
            # battle_gift_contributions側の話である)。
            f" u.fans_level AS fans_level, u.gifter_level AS gifter_level,"
            " u.gifter_badge AS gifter_badge, u.member_badge AS member_badge,"
            f" {display_league_sql('u')} AS league, u.league_checked_at AS league_checked_at,"
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
        heatmap_rows = conn.execute(
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
        battle_rows = conn.execute(
            "SELECT b.session_id AS session_id, b.data_json AS data_json"
            " FROM battles b JOIN sessions s ON s.id = b.session_id"
            f" WHERE s.unique_id IN ({ph})"
            " ORDER BY s.started_at ASC, b.session_id ASC",
            tuple(handles),
        ).fetchall()
        # Battle履歴から「その対戦の動画」へ辿るための、時刻の当たり先。中断録画も
        # 素材は揃っていることがあり、statusで捨てるとその録画へ辿る道が無くなる。
        recording_rows = [
            dict(r)
            for r in conn.execute(
                f"SELECT id, session_id, started_at, ended_at FROM recordings"
                f" WHERE unique_id IN ({ph}) AND status IN ('completed', 'interrupted')",
                tuple(handles),
            ).fetchall()
        ]
        # コラボ(非BattleのLinkMic)の窓。Battle窓と同じwall-clock軸で「配信時間の
        # どれだけを共演に使ったか」を出すために引く。集計対象はsession_rowsと同じ
        # session集合(制限中を除く直近limit件)へ後で絞る — 分母(配信時間)と分子が
        # 別のsession集合になると比率が意味を失う。
        collab_rows = [
            (r["session_id"], r["start"], r["end"])
            for r in conn.execute(
                "SELECT cw.session_id AS session_id, cw.start AS start, cw.end AS end"
                " FROM collab_windows cw JOIN sessions s ON s.id = cw.session_id"
                f" WHERE s.unique_id IN ({ph})",
                tuple(handles),
            ).fetchall()
        ]
        # 収集中(ended_atなし)のsessionには終端が無い。最後に何かが届いた時刻を終端に
        # 使う(analytics._observed_spanと同じ根拠)。started_atで潰すと、その配信の窓が
        # まるごと落ちる。
        open_ids = [r["id"] for r in session_rows if r["ended_at"] is None]
        observed_end: dict = {}
        if open_ids:
            oph = ",".join("?" * len(open_ids))
            observed_end = {
                r["session_id"]: r["last"]
                for r in conn.execute(
                    "SELECT session_id, MAX(t) AS last FROM ("
                    f"  SELECT session_id, MAX(time) AS t FROM events"
                    f"   WHERE session_id IN ({oph}) GROUP BY session_id"
                    f"  UNION ALL SELECT session_id, MAX(time) FROM viewer_samples"
                    f"   WHERE session_id IN ({oph}) GROUP BY session_id"
                    ") GROUP BY session_id",
                    (*open_ids, *open_ids),
                ).fetchall()
                if r["last"] is not None
            }

        # 各Battleの自陣貢献を、Battle cardと同じ窓・同じ入口(battle_gift_contributions)で
        # 復元する。窓解決は同一sessionの他Battle(次Battle開始・duration中央値)に依存する
        # ためsession単位でまとめて解く。窓を自前で持つと、end_timeを欠くBattleが無制限窓に
        # なりBattle後の通常Giftまで貢献へ混入する(実測: 貢献者0人→12人, coin 26→19397)。
        # battle_gift_contributionsは自身でlockを取るのでlockの外で回す。
        battles_by_session: dict = {}
        for brow in battle_rows:
            battles_by_session.setdefault(brow["session_id"], []).append(
                annotate_result(json.loads(brow["data_json"]))
            )

        battle_diamonds = 0
        battle_team_diamonds = 0
        # 相手陣のgifterは別Roomのためこのsessionのeventには無い。ここに集まるのは監視配信者
        # 自身のBattle gifterだけで、全Battleを通して「Battleに必ず現れるgifter」を表す。
        battle_gifters: dict = {}
        parsed_battles = []
        # battle_id is TikTok's globally-unique PK id, so the same physical battle
        # carries the same id across sessions. Dedup on it to keep concurrent-
        # collection duplicates from inflating every battle metric. id 0/missing is
        # treated as un-dedupable (old/synthetic records) and kept as-is.
        seen_battle_ids = set()
        dropped_duplicates = 0
        for session_id, session_battles in battles_by_session.items():
            # 窓解決には(重複除外前の)そのsessionの全Battleを使う。除外されるのは別session
            # が同じBattleを重複収集した分で、このsessionの「次Battle開始」は変わらないため。
            starts = sorted(
                b["start_time"] for b in session_battles if b.get("start_time") is not None
            )
            fallback_duration = gift_window_fallback_duration(session_battles)
            for battle in session_battles:
                start_time = battle.get("start_time")
                if start_time is None:
                    continue
                battle_id = battle.get("battle_id")
                if battle_id:
                    if battle_id in seen_battle_ids:
                        dropped_duplicates += 1
                        continue
                    seen_battle_ids.add(battle_id)
                end_time = gift_window_end(battle, starts, fallback_duration)
                gift = self._cached_battle_gift_contributions(
                    session_id, battle, start_time, end_time)

                # 自室のGift eventで実測できる分。これが監視配信者自身の貢献者である。
                window_diamonds = 0
                key_contributors = 0
                for g in gift:
                    diamonds = g["diamonds"]
                    window_diamonds += diamonds
                    if diamonds >= _BATTLE_KEY_CONTRIB_DIAMONDS:
                        key_contributors += 1
                    key = g["key"]
                    if not key:
                        continue
                    agg = battle_gifters.setdefault(
                        key,
                        {
                            "user_id": g["user_id"],
                            "unique_id": g["unique_id"],
                            "nickname": g["nickname"],
                            "avatar": g["avatar"],
                            "diamonds": 0,
                            "gifts": 0,
                            "battles": 0,
                        },
                    )
                    agg["diamonds"] += diamonds
                    agg["gifts"] += g["gifts"]
                    agg["battles"] += 1
                    if g["avatar"] and not agg["avatar"]:
                        agg["avatar"] = g["avatar"]

                # チーム戦のteam集約armiesは味方hostの貢献者も自陣hostへ寄って届く
                # (team集約のanchorが実hostに解決できないため、host別に分けられない)。
                # 実測できる自室分とは別に、armies由来のチーム全体分も併記する。集計方法は
                # Battle card(apply_battle_gift_contributions)と揃える。
                gift_by_id = {g["user_id"]: g for g in gift if g["user_id"]}
                team_diamonds = 0
                team_key_contributors = 0
                matched = set()
                for c in battle.get("contributions", []) or []:
                    if c.get("side") != "own":
                        continue
                    cid = c.get("user_id")
                    if cid and cid in gift_by_id:
                        matched.add(cid)
                        coins = gift_by_id[cid]["diamonds"]
                    else:
                        coins = c.get("diamonds") or 0
                    team_diamonds += coins
                    if coins >= _BATTLE_KEY_CONTRIB_DIAMONDS:
                        team_key_contributors += 1
                for g in gift:
                    if g["user_id"] and g["user_id"] in matched:
                        continue
                    team_diamonds += g["diamonds"]
                    if g["diamonds"] >= _BATTLE_KEY_CONTRIB_DIAMONDS:
                        team_key_contributors += 1

                battle_diamonds += window_diamonds
                battle_team_diamonds += team_diamonds
                parsed_battles.append(
                    {
                        "battle": battle,
                        "session_id": session_id,
                        "window_diamonds": window_diamonds,
                        "key_contributors": key_contributors,
                        "team_diamonds": team_diamonds,
                        "team_key_contributors": team_key_contributors,
                    }
                )

        if dropped_duplicates:
            logger.info(
                "streamer_profile: battle %d 件をbattle_id重複として除外しました"
                "（%s の同時収集による重複）",
                dropped_duplicates,
                unique_id,
            )

        # 共演構成(コラボ / Battle / ソロ)。Battle窓は重複除外後のparsed_battlesを使う
        # (同じBattleを2 instanceが収集した分を足すと、その時間だけ二重に計上される)。
        session_spans = [
            (
                row["id"],
                row["started_at"],
                row["ended_at"]
                if row["ended_at"] is not None
                else observed_end.get(row["id"], row["started_at"]),
            )
            for row in session_rows
        ]
        coop = _coop_summary(
            session_spans,
            collab_rows,
            [
                (pb["session_id"], pb["battle"].get("start_time"), pb["battle"].get("end_time"))
                for pb in parsed_battles
            ],
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
                # identity_keyはFan台帳の主キー。名前からその人の横断実績へ飛ぶ導線に使う。
                "identity_key": row["key"] or "",
                "user_id": row["user_id"] or "",
                "unique_id": row["unique_id"] or "",
                "nickname": row["nickname"] or "(unknown)",
                "avatar": row["avatar"] or "",
                "fans_level": row["fans_level"] or 0,
                "gifter_level": row["gifter_level"] or 0,
                "gifter_badge": row["gifter_badge"] or "",
                "member_badge": row["member_badge"] or "",
                # この視聴者自身が配信者である場合のリーグ帯。取れていなければ空=非表示。
                "league": row["league"] or "",
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

        # ギフトに占めるライバーの割合。gifters は全件で、表示用に切り詰めるのは後段の
        # gifters[:100] だけなので、ここは母集合の全員から数える。
        concentration = {
            "total_gifters": len(gifters),
            "total_diamonds": gifter_total_diamonds,
            "top1": _share(1),
            "top5": _share(5),
            "top10": _share(10),
            "repeat_gifters": sum(1 for g in gifters if g["sessions"] >= 2),
            "once_gifters": sum(1 for g in gifters if g["sessions"] == 1),
            **_liver_share(
                gift_diamonds=gifter_total_diamonds,
                checked_diamonds=sum(
                    row["diamonds"] or 0
                    for row in gifter_rows
                    if row["league_checked_at"] is not None
                ),
                liver_diamonds=sum(
                    row["diamonds"] or 0 for row in gifter_rows if row["league"]
                ),
                gifters=len(gifters),
                checked_gifters=sum(
                    1 for row in gifter_rows if row["league_checked_at"] is not None
                ),
                liver_gifters=sum(1 for row in gifter_rows if row["league"]),
            ),
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
                key = _opponent_key(opp)
                if not key:
                    continue
                stat = opponents.setdefault(
                    key,
                    {
                        # 履歴側(opponent_keys)と突き合わせるためのkey。表示名やhandleから
                        # 画面が組み直すと、handleを持たない相手で別人と混ざる。
                        "key": key,
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
            # own_scoreはチーム戦ではチーム合計。監視配信者1人ぶんのscoreは participants の
            # 自hostが持つ。個人戦(個人マルチ含む)は自陣host=1人なのでown_scoreと同値。
            # チーム戦で自hostを特定できない古いrecordはNone(不明)にする。0を入れると
            # 「そのBattleは無得点だった」と読める偽の実測値になるため。
            btype = b.get("type") or "personal"
            own_host = next(
                (p for p in (b.get("participants") or []) if p.get("is_own")), None
            )
            if own_host is not None:
                own_host_score = own_host.get("score", 0) or 0
            else:
                own_host_score = (b.get("own_score", 0) or 0) if btype != "team" else None
            history.append(
                {
                    "session_id": pb["session_id"],
                    "battle_id": b.get("battle_id"),
                    "started_at": b.get("start_time"),
                    "ended_at": b.get("end_time"),
                    "type": btype,
                    "own_score": b.get("own_score", 0) or 0,
                    "own_host_score": own_host_score,
                    "opp_score": b.get("opp_score", 0) or 0,
                    "result": b.get("result"),
                    "diamonds": pb["window_diamonds"],
                    "team_diamonds": pb["team_diamonds"],
                    "key_contributors": pb["key_contributors"],
                    "team_key_contributors": pb["team_key_contributors"],
                    "opponent_count": len(opps),
                    # 表に出す相手は最高scoreの1人だが、絞り込みは参加した全員に当てる。
                    # 代表1人だけをkeyにすると、チーム戦・個人マルチで格下だった相手から
                    # その対戦へ辿れない(対戦相手別の戦数と履歴の件数も食い違う)。
                    "opponent_keys": [k for k in (_opponent_key(o) for o in opps) if k],
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
        # 各Battleを含む録画(あれば)。画面はこれを根拠に「その対戦の動画へ飛ぶ」を出す。
        # 動画の何秒地点かはここでは出さない — 壁時計と動画の時間軸は一致せず、変換には
        # 録画fileの時刻anchorが要る(server側 /api/recordings/{id}/locate が担う)。
        for h in history:
            cover = _covering_recording(recording_rows, h["session_id"], h["started_at"])
            h["recording_id"] = cover["id"] if cover else None

        # 1戦あたり「主力貢献者(coin >= 閾値)」の平均人数。過去全Battleを集約した指標。
        # 自室のGift eventで実測した分と、armies由来のチーム全体分の両方を出す(チーム戦は
        # 味方hostの貢献者を自陣hostと分離できないため、片方だけでは実態を表さない)。
        key_contrib_sum = sum(pb["key_contributors"] for pb in parsed_battles)
        team_key_contrib_sum = sum(pb["team_key_contributors"] for pb in parsed_battles)
        # 自hostのscoreが不明なBattleは平均の母数からも外す(0として均すと平均が下振れする)。
        own_host_scores = [h["own_host_score"] for h in history if h["own_host_score"] is not None]
        battle_summary = {
            "count": battle_count,
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "win_rate": (wins / decided * 100) if decided else 0,
            "avg_own_score": (own_score_sum / battle_count) if battle_count else 0,
            "avg_own_host_score": (sum(own_host_scores) / len(own_host_scores)) if own_host_scores else 0,
            "own_host_score_count": len(own_host_scores),
            "avg_opp_score": (opp_score_sum / battle_count) if battle_count else 0,
            "key_contrib_threshold": _BATTLE_KEY_CONTRIB_DIAMONDS,
            "key_contrib_total": key_contrib_sum,
            "avg_key_contributors": (key_contrib_sum / battle_count) if battle_count else 0,
            "team_key_contrib_total": team_key_contrib_sum,
            "avg_team_key_contributors": (team_key_contrib_sum / battle_count) if battle_count else 0,
            "battle_diamonds": battle_diamonds,
            "battle_team_diamonds": battle_team_diamonds,
            "battle_diamond_share": (battle_diamonds / totals["diamonds"] * 100) if totals["diamonds"] else 0,
            # 対戦相手は全件返す。上位30名で切ると「31位以降は0戦」と読めてしまい、
            # 画面の絞り込みも app.js の対戦成績突合(pkVsRecord)も裾の相手に当たらない。
            # 件数は配信者あたり数百で、絞り込み/並べ替えはFrontendが持つ。
            "opponents": opponent_list,
            "gifters": battle_gifter_list[:30],
            # 履歴も件数を切らない。直近80戦で切っていた頃は、対戦相手別で選んだ相手の
            # 対戦が1件も出ないこと(実測: 1配信者313戦)が普通にあり、「対戦数5」と出て
            # いる相手の動画へ辿れなかった。相手別の追跡が裾まで届くことを優先する。
            "history": history,
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
            # ライバーだけを抜いた一覧。gifters[:100] から絞ると、コイン順で100位より下の
            # ライバーが消えて「誰が投げたか」が欠ける(比率の分子には入っているのに一覧に
            # 居ない、という食い違いになる)ため、母集合から直接採る。
            "livers": [g for g in gifters if g["league"]][:50],
            "concentration": concentration,
            "battles": battle_summary,
            "coop": coop,
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
        # この配信者の視聴側eventを全期間ぶん走査する(実測640ms)。書き込み接続で流すと
        # その間collectorのevent書き出しが待たされるので、集計read専用の接続を使う。
        rows = self._read_connection().execute(
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

    def session_rankings(self, limit: int) -> dict:
        # session全件とevent全件のGROUP BY。書き込み接続で流すと、その間ずっとcollectorの
        # event書き出しが同じlockで待たされる(実測: eventのGROUP BYだけでwarm 1.06秒、
        # page cacheが冷えていれば7.4秒)。streamer_index / aggregate_dashboardと同じく
        # 集計read専用の接続へ逃がす。
        conn = self._read_connection()
        base_rows = conn.execute(
            "SELECT id, unique_id, started_at, ended_at, stats_json FROM sessions",
        ).fetchall()
        agg_rows = conn.execute(
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
        # 全sessionを跨ぐ通算集計。1本でも数百msかかる質の読み取りなので、書き込み接続を
        # 掴まず集計read専用の接続で流す(この画面は履歴のKPI帯として定期的に叩かれる)。
        conn = self._read_connection()
        with self._lock:
            streamer_handles = self._latest_owner_handles_locked()
        totals = conn.execute(
            _SESSION_TOTALS_CTE +
            "SELECT"
            " (SELECT COUNT(*) FROM sessions) AS sessions,"
            " (SELECT COUNT(*) FROM recordings) AS recordings,"
            " COALESCE(SUM(gifts), 0) AS gifts,"
            " COALESCE(SUM(diamonds), 0) AS diamonds,"
            " COALESCE(SUM(comments), 0) AS comments,"
            " (SELECT COALESCE(SUM(json_extract(stats_json, '$.likes_total')), 0) FROM sessions) AS likes,"
            " (SELECT COALESCE(SUM(CASE WHEN ended_at IS NOT NULL THEN ended_at - started_at ELSE 0 END), 0) FROM sessions) AS duration"
            " FROM session_totals"
        ).fetchone()
        # 表示用handleの選び方はstreamer_indexと同じ(最新sessionのものを決定的に)。
        streamer_rows = conn.execute(
            _SESSION_TOTALS_CTE + _STREAMER_TOTALS_SELECT +
            " GROUP BY okey ORDER BY diamonds DESC",
        ).fetchall()
        # 全sessionを跨ぐ通算集計なので表示属性はusers表(最新)を優先する
        # (理由はstreamer_profileのgifter集計と同じ)。
        # 上位50を先に確定させ、表示属性はその50件ぶんだけ引く。1本のGROUP BYで表示属性まで
        # 一緒にMAXすると、全gift eventでeventsの行本体を読みに行く(index idx_events_kind_
        # identityは金額側しか覆わない)。表示属性はusers表が正で、MAXはusers行が無い/空の
        # ときのfallbackにすぎないため、上位50件に絞ってから引いても答えは同じ(実測46→22ms)。
        gifter_rows = conn.execute(
            "WITH top AS ("
            " SELECT identity_key AS key, SUM(gift_count) AS gifts,"
            " SUM(diamonds) AS diamonds, COUNT(DISTINCT session_id) AS sessions"
            " FROM events WHERE kind = 'gift' GROUP BY identity_key"
            " ORDER BY diamonds DESC, gifts DESC LIMIT 50)"
            " SELECT t.key AS key,"
            " COALESCE(NULLIF(u.user_id, ''), (SELECT MAX(user_id) FROM events"
            "   WHERE kind = 'gift' AND identity_key = t.key)) AS user_id,"
            " COALESCE(NULLIF(u.unique_id, ''), (SELECT MAX(user_unique_id) FROM events"
            "   WHERE kind = 'gift' AND identity_key = t.key)) AS unique_id,"
            " COALESCE(NULLIF(u.nickname, ''), (SELECT MAX(user_nickname) FROM events"
            "   WHERE kind = 'gift' AND identity_key = t.key)) AS nickname,"
            " COALESCE(NULLIF(u.avatar, ''), (SELECT MAX(user_avatar) FROM events"
            "   WHERE kind = 'gift' AND identity_key = t.key)) AS avatar,"
            " u.fans_level AS fans_level, u.gifter_level AS gifter_level,"
            " u.gifter_badge AS gifter_badge, u.member_badge AS member_badge,"
            f" {display_league_sql('u')} AS league,"
            " t.gifts AS gifts, t.diamonds AS diamonds, t.sessions AS sessions"
            " FROM top t LEFT JOIN users u ON u.identity_key = t.key"
            " ORDER BY t.diamonds DESC, t.gifts DESC",
        ).fetchall()
        gift_rows = conn.execute(
            "SELECT gift_name AS name, SUM(gift_count) AS count, SUM(diamonds) AS diamonds"
            " FROM events WHERE kind = 'gift'"
            " GROUP BY gift_name ORDER BY diamonds DESC, count DESC LIMIT 50",
        ).fetchall()
        session_rows = conn.execute(
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
                    "fans_level": row["fans_level"] or 0,
                    "gifter_level": row["gifter_level"] or 0,
                    "gifter_badge": row["gifter_badge"] or "",
                    "member_badge": row["member_badge"] or "",
                    "league": row["league"] or "",
                    "gifts": row["gifts"] or 0,
                    "diamonds": row["diamonds"] or 0,
                    "sessions": row["sessions"],
                }
                for row in gifter_rows
            ],
            "top_gifts": [dict(row) for row in gift_rows],
            "recent_sessions": [dict(row) for row in reversed(session_rows)],
        }
