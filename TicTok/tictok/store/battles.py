"""Battle(対戦)とgift貢献の集計。

境界の理由: battles表の読み書きと、Battleの窓へgiftを割り当てる集計をまとめる。
窓確定後の貢献集計は不変なので _battle_contrib_cache に載せる — この cache の
所有者をここへ寄せるのが分割の主目的。

lock契約: lock保持前提のmethodは無い。貢献集計の読み取りは集計read専用接続
  (_read_connection)で流すので self._lock は取らない。read専用接続はcommit済みしか
  見ないため、**呼び出し側が先に flush() する**という不変条件だけが残る。flushの持ち場は
  battle_gift_contributions(単発の入口)と apply_battle_gift_contributions(loopの手前)で、
  cache越しの _cached_battle_gift_contributions は flush しない。

  以前は貢献集計そのものが flush + writer接続 で、しかも配信者profileと期間別rankingが
  それを **Battle 1件ごとに** loopで呼んでいた。実測でstreamer_profile 1 requestあたり
  write lockを214回(=2×111戦: flush 1回 + query 1回)、matrix 48.9回、ranking 105回。
  flushをloopの手前へ1回だけ出し、queryをread専用接続へ移すと、この経路のwrite lock取得は
  1 requestあたり1回(flushのdrain)になる。

  窓ごとに1本ずつ投げる形は、往復を1本へ畳んでも速くならない(実測: 760窓で
  1戦ずつ174〜192ms 対 まとめ引き230〜243ms、profile全体はcold/warmとも同値)。
  db.read_wait は往復のoverheadではなく**同時に走る別requestのSQL時間**なので、
  直列化される総仕事量は往復では減らない。畳むcodeは足さない。
"""
import json

from tictok.core.battle import annotate_result, gift_window_end, gift_window_fallback_duration

from tictok.store._common import _BATTLE_CONTRIB_CACHE_MAX

# 配信者集計(profile)が一度も読まないkey。SQL側で落としてPythonへ渡さない。落とす根拠は
# 「読む側が居ない」ことなので、読む側が増えたらここから減らすこと(読む列を並べる形に
# すると、読む側が増えたときに黙って欠ける)。実測: battle 945件 35.0MB のうち 4.1MB。
_BATTLE_PROFILE_UNUSED_PATHS = (
    "$.item_cards", "$.bonus_missions", "$.glove_events", "$.glove_windows",
    "$.battle_settings", "$.team_battle_result",
)
# 貢献者1件あたりのavatar/badge。profileの貢献集計が読むのは side / user_id / diamonds
# だけで、表示用の身元はusers表(最新)から解決し直す。実測: contributions 8.35MB のうち
# 7.03MB がこの3つ。
_BATTLE_PROFILE_CONTRIB_UNUSED = ("avatar", "gifter_badge", "member_badge")
# 畳んだBattleを覚えるsession数の上限。1 sessionぶんは戦数に比例するので、上限は
# 「同時に見る配信者の配信数」の桁で置く(実測: 配信者2人でbattleを持つsessionが176)。
_BATTLE_PROFILE_CACHE_MAX = 400


class BattlesMixin:
    """Battle(対戦)とgift貢献の集計。

    lockもDB接続も持たない。すべて Storage が所有する self._conn /
    self._lock / _read_connection() を借りる(mixinとして Storage に混ぜられる前提)。
    契約の詳細はmodule docstringを参照。
    """

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
        # 畳んだBattle(profile_battles)はこのsessionのdata_jsonから作ったもの。書き換えた
        # なら捨てる。runtimeにbattles.data_jsonを書くのはここだけなので、捨てる場所もここ
        # 1箇所で足りる。
        self._profile_battle_cache().pop(session_id, None)

    def battle_gift_contributions(self, session_id: int, start_time, end_time) -> list:
        """Battleの時間窓内に自陣(監視配信者)へ送られたGiftをUser単位で集計する。
        TikTokのarmies eventは相手陣の合計スコアのみで、誰がいくら実弾を送ったかの
        User単位内訳(user_armies/diamond_score)を欠くことが多い。実弾の出どころは
        確実に記録しているGift eventから復元する。相手陣のGiftは別Roomのため取得不可。
        窓境界(battle_setting.*_ms)はTikTokサーバ時刻なので、eventもサーバ時刻の
        create_timeで突合する(欠落eventのみ受信時刻timeで代用)。

        単発の入口なのでここが flush() を持つ。loopで呼ぶ経路は
        _cached_battle_gift_contributions を直接使い、flushは手前で1回だけ行う。"""
        self.flush()
        return self._battle_gift_rows(session_id, start_time, end_time)

    def _profile_battle_cache(self) -> dict:
        """配信者集計向けに畳んだBattleのprocess内cache(session_id -> list)。

        Storage.__init__が持つ他のcacheと並ぶ物だが、生成は初回のここで行う。
        dict.setdefaultはGIL下でatomicなので、同時requestが来ても実体は1つになる。"""
        return self.__dict__.setdefault("_battle_profile_cache", {})

    def profile_battles(self, conn, session_ids: list) -> dict:
        """配信者集計(profile)が使う形へ畳んだBattleを session_id -> list で返す。
        listの並びは保存順(=そのsessionがBattleを見た順)、dictの並びは引数の順。

        畳む理由: 配信者profileはこの配信者の全Battleのdata_jsonを毎requestでparseして
        いた。実測で1配信者945戦・35.0MBを json.loads に掛けており、warm 1,080msのうち
        約400msがこのparse、SQLがさらに84msだった。実際に読んでいるのは
          勝敗判定(annotate_result): result / aborted / end_time / score_series /
                                     own_score / opp_score
          窓の解決: battle_id / start_time / end_time / duration / ongoing
          集計と履歴: type / participants / opponents / contributions(side,user_id,diamonds)
        だけで、bytesの大半は誰も読まない — score_series 15.4MB(うち profileが触らない
        parts が 14.1MB)、contributionsのavatar/badge 7.0MB、item_cards等 4.1MB。

        score_seriesは annotate_result が確定判定を battle 本体へ書き戻した後は誰も読まない
        ので、覚える前に落とす。判定そのものは core.battle のままで、ここは「畳んだ結果を
        覚える」だけ — SQLへ勝敗ruleを写さない。

        **cacheがprocess内で完結してよい理由**: battles.data_json をruntimeに書き換えるのは
        save_battles(収集中session)だけで、そこでこのcacheを捨てている。他の書き手
        (battle_migration / glove_migration / owner_user_idの補完)は全て Storage.__init__ の
        起動時blockで、collectorが動き出す前に走り切る。よってこのcacheがそれらを跨ぐことは
        起こり得ず、版も指紋も要らない。DBへ置かない理由でもある: migrate_battle_topology は
        「cache無効化は不要(cacheが読むのは start_time/end_time/battle_id/glove_events だけ)」
        という前提で書かれており、result や type を永続cacheへ載せるとその前提を黙って壊す。
        """
        cache = self._profile_battle_cache()
        missing = [sid for sid in session_ids if sid not in cache]
        if missing:
            paths = ",".join("?" * len(_BATTLE_PROFILE_UNUSED_PATHS))
            rows = conn.execute(
                f"SELECT b.session_id AS session_id, json_remove(b.data_json, {paths}) AS body"
                " FROM battles b"
                " WHERE b.session_id IN (SELECT je.value FROM json_each(?) je)"
                # 保存順(collectorが見た順)を保つ。同着のBattleが並んだときに履歴の並びが
                # 変わらないよう、順序を運任せにしない。
                " ORDER BY b.rowid",
                (*_BATTLE_PROFILE_UNUSED_PATHS, json.dumps(missing)),
            ).fetchall()
            built: dict = {sid: [] for sid in missing}
            for row in rows:
                built[row["session_id"]].append(self._folded_battle(row["body"]))
            for session_id, battles in built.items():
                # dictは挿入順を保つので、あふれたら古い方から捨てる(貢献集計cacheと同じ)。
                if len(cache) >= _BATTLE_PROFILE_CACHE_MAX:
                    for stale in list(cache)[:_BATTLE_PROFILE_CACHE_MAX // 4]:
                        del cache[stale]
                cache[session_id] = battles
        return {sid: cache[sid] for sid in session_ids if sid in cache}

    @staticmethod
    def _folded_battle(body: str) -> dict:
        """1戦ぶんのdata_jsonを、配信者集計が読む形へ畳む。

        呼び出し側が同じdictを何度も読むので、破壊的に書き換えないこと(annotate_resultは
        2度目以降no-opで、ここで1度だけ通す)。"""
        battle = annotate_result(json.loads(body))
        battle.pop("score_series", None)
        for contribution in battle.get("contributions") or ():
            for field in _BATTLE_PROFILE_CONTRIB_UNUSED:
                contribution.pop(field, None)
        return battle

    @staticmethod
    def _gift_contribution(row) -> dict:
        return {
            # identity_key/giftsは配信者profileのBattle gifter集計が使う。Battle card側は
            # 参照しない(この関数を貢献集計の単一の入口にするために持たせている)。
            "key": row["key"],
            "user_id": row["user_id"] or "",
            "unique_id": row["unique_id"] or "",
            "nickname": row["nickname"] or "(unknown)",
            "avatar": row["avatar"] or "",
            "side": "own",
            "diamonds": row["diamonds"] or 0,
            "gifts": row["gifts"] or 0,
            "fans_level": row["fans_level"] or 0,
            "gifter_level": row["gifter_level"] or 0,
            "gifter_badge": row["gifter_badge"] or "",
            "member_badge": row["member_badge"] or "",
        }

    def _battle_gift_rows(self, session_id: int, start_time, end_time) -> list:
        """battle_gift_contributionsの本体(flushしない)。read専用接続で流すので、未commitの
        eventまで要る呼び出し側は先に flush() しておくこと。

        絞りは (session_id, kind) で、plannerに idx_events_session_kind_time を選ばせる
        ためにこの順で書いてある。統計(sqlite_stat1)が無いと同じSQLでも
        idx_events_kind_identity が選ばれ、Battle 1件ごとに全gift eventを走査する
        (実測: 1,417窓で4,596ms 対 526ms)。統計はStorage.__init__のensure_planner_statsが
        維持する。

        窓の数だけ呼ばれる(配信者profileで実測760回)が、まとめて1本のqueryへ畳んでも
        速くはならない — module docstringの実測を参照。"""
        upper = end_time if end_time is not None else 9_999_999_999
        rows = self._read_connection().execute(
            "SELECT e.identity_key AS key,"
            " COALESCE(NULLIF(MAX(e.user_id), ''), u.user_id) AS user_id,"
            " COALESCE(NULLIF(MAX(e.user_unique_id), ''), u.unique_id) AS unique_id,"
            " COALESCE(NULLIF(MAX(e.user_nickname), ''), u.nickname) AS nickname,"
            # avatar/badgeは event_strings へinternしてある(doc/DB_INTERN.md)。
            # **MAX(e.user_avatar_id) にしてはならない** ―― 元のMAXは値そのものの辞書順
            # 最大で、idの最大(=最初に見た順)とは別物である。値へJOINしてからMAXを採る。
            " COALESCE(NULLIF(MAX(av.value), ''), u.avatar) AS avatar, SUM(e.diamonds) AS diamonds,"
            " SUM(e.gift_count) AS gifts,"
            # Lv/badgeはその時点で変動する属性。users表(最新)へfallbackすると過去の値を
            # 捏造するため、このSessionのevent(point-in-time)のみ。無ければ非表示。
            # fans_level/gifter_levelはINTEGERで、internの対象ではない(比較対象も0)。
            " NULLIF(MAX(e.user_fans_level), 0) AS fans_level,"
            " NULLIF(MAX(e.user_gifter_level), 0) AS gifter_level,"
            " NULLIF(MAX(gbv.value), '') AS gifter_badge,"
            " NULLIF(MAX(mbv.value), '') AS member_badge"
            " FROM events e LEFT JOIN users u ON u.identity_key = e.identity_key"
            " LEFT JOIN event_strings av ON av.id = e.user_avatar_id"
            " LEFT JOIN event_strings gbv ON gbv.id = e.user_gifter_badge_id"
            " LEFT JOIN event_strings mbv ON mbv.id = e.user_member_badge_id"
            " WHERE e.session_id = ? AND e.kind = 'gift'"
            " AND COALESCE(e.create_time, e.time) >= ? AND COALESCE(e.create_time, e.time) <= ?"
            " GROUP BY e.identity_key HAVING SUM(e.diamonds) > 0 ORDER BY diamonds DESC",
            (session_id, start_time or 0, upper),
        ).fetchall()
        return [self._gift_contribution(row) for row in rows]

    def _cached_battle_gift_contributions(self, session_id: int, battle: dict,
                                          start, end) -> list:
        """終了済みBattleの貢献集計をcache越しに引く。窓が確定している(進行中でなく、
        end_timeとbattle_idを持つ)Battleだけをcacheに載せる — 進行中は窓が伸び続けるので
        覚えてはいけない。

        Battle cardと配信者profileが同じ集計を別々に引いていたため、profileはBattle 1件に
        つき1 query(実測では1配信者100 battleで100 query)を毎回払っていた。窓の解き方は
        呼び出し側が持ち、ここは覚えるかどうかだけを決める。cacheが効いている限り、2回目
        以降の配信者profileはこの経路でSQLをほとんど投げない(実測: 1回目で636件載り、
        2回目以降のprofileは1,080ms中72ms)。

        **flushしない。** loopから1件ずつ呼ばれる位置なので、ここに置くとBattleの数だけ
        write lockを取り直すことになる(実測: streamer_profile 1 requestで214回)。未commitの
        eventまで要るのは進行中Battleを含む収集中sessionだけで、その判断は「今このrequestで
        何を読むか」を知っている呼び出し側にしか出来ない。呼び出し元(loopの手前)で
        flush() すること。"""
        battle_id = battle.get("battle_id")
        cache_key = (
            (session_id, battle_id, start, end)
            if (not battle.get("ongoing") and end is not None and battle_id)
            else None
        )
        if cache_key is not None and cache_key in self._battle_contrib_cache:
            return self._battle_contrib_cache[cache_key]
        gift = self._battle_gift_rows(session_id, start, end)
        if cache_key is not None:
            # 以前この cache を養っていたのは収集中sessionのBattle cardだけで、母数は
            # 「今の配信のBattle」だった。配信者profileが入ったことで母数が全sessionの
            # Battleへ広がるため、上限を設ける(dictは挿入順を保つので古い方から捨てる)。
            if len(self._battle_contrib_cache) >= _BATTLE_CONTRIB_CACHE_MAX:
                for stale in list(self._battle_contrib_cache)[:_BATTLE_CONTRIB_CACHE_MAX // 4]:
                    del self._battle_contrib_cache[stale]
            self._battle_contrib_cache[cache_key] = gift
        return gift

    def apply_battle_gift_contributions(self, session_id: int, battles: list) -> list:
        """各Battleの監視配信者(自陣host)の貢献をGift eventから再構成して差し替える。
        相手陣(side!=own)と、チーム戦の味方host(別Roomのためarmies由来)の貢献はそのまま
        残す。host_idで宛先配信者を保持し、配信者別の集計に使う。live snapshot / history
        両方で同じ集計を使う。

        貢献集計はread専用接続で流すので、loopへ入る前にここで1回だけ確定させる。以前は
        Battle 1件ごとにflushしていたため、Battleの数だけwrite lockを取り直していた。"""
        self.flush()
        starts = sorted(
            b["start_time"] for b in battles if b.get("start_time") is not None
        )
        fallback_duration = gift_window_fallback_duration(battles)
        for battle in battles:
            own_host = next(
                (p.get("user_id") for p in battle.get("participants", []) if p.get("is_own")),
                None,
            )
            start = battle.get("start_time")
            end = gift_window_end(battle, starts, fallback_duration)
            # 終了済みBattleは窓が確定しているので貢献集計をキャッシュし、再集計は進行中のみ。
            gift = self._cached_battle_gift_contributions(session_id, battle, start, end)
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
        # 勝敗は保存値ではなくPK確定時点で判定し直す(DBは書き換えない)。履歴画面・
        # 焼き込み・解析が同じ判定を見るための単一の入口。
        battles = [annotate_result(json.loads(row["data_json"])) for row in rows]
        self.apply_battle_gift_contributions(session_id, battles)
        battles.sort(key=lambda b: b.get("start_time", 0), reverse=True)
        return battles
