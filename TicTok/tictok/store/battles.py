"""Battle(対戦)とgift貢献の集計。

境界の理由: battles表の読み書きと、Battleの窓へgiftを割り当てる集計をまとめる。
窓確定後の貢献集計は不変なので _battle_contrib_cache に載せる — この cache の
所有者をここへ寄せるのが分割の主目的。

lock契約: lock保持前提のmethodは無い。battle_gift_contributions は自分で
  self._lock を取り、その外で flush() を呼ぶ(未commitのbufferまで必要とするため)。
"""
import json

from tictok.core.battle import annotate_result, gift_window_end, gift_window_fallback_duration

from tictok.store._common import _BATTLE_CONTRIB_CACHE_MAX


class BattlesMixin:
    """Battle(対戦)とgift貢献の集計。

    lockもDB接続も持たない。すべて Storage が所有する self._conn /
    self._lock / self._read_lock を借りる(mixinとして Storage に混ぜられる前提)。
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
                " SUM(e.gift_count) AS gifts,"
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
            for row in rows
        ]

    def _cached_battle_gift_contributions(self, session_id: int, battle: dict,
                                          start, end) -> list:
        """終了済みBattleの貢献集計をcache越しに引く。窓が確定している(進行中でなく、
        end_timeとbattle_idを持つ)Battleだけをcacheに載せる — 進行中は窓が伸び続けるので
        覚えてはいけない。

        Battle cardと配信者profileが同じ集計を別々に引いていたため、profileはBattle 1件に
        つき1 query(実測では1配信者100 battleで100 query)を毎回払っていた。窓の解き方は
        呼び出し側が持ち、ここは覚えるかどうかだけを決める。"""
        battle_id = battle.get("battle_id")
        cache_key = (
            (session_id, battle_id, start, end)
            if (not battle.get("ongoing") and end is not None and battle_id)
            else None
        )
        if cache_key is not None and cache_key in self._battle_contrib_cache:
            return self._battle_contrib_cache[cache_key]
        gift = self.battle_gift_contributions(session_id, start, end)
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
        両方で同じ集計を使う。"""
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
