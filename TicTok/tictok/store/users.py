"""User名寄せ(identity)・配信者handle解決・Fan台帳・発掘候補。

境界の理由: users表とidentity_keyを軸にした読み書きをまとめる。配信者のhandle解決
(_owner_handles_locked / _latest_owners / _fill_owner)を同居させるのは、配信者もまた
user_id優先のidentityで名寄せされる同じ問題だからで、streamers/analyticsの双方から
同じ解決規則で引かれる。

upsert間引きcache(_user_cache)の所有者もここ。上限は _USER_CACHE_MAX で、溢れたら
挿入順の古い方から1/4を捨てる — battles mixinの _battle_contrib_cache と同じ扱いである
(同じclassに2種類のcache戦略を並べない)。

lock契約:
  _upsert_user_locked は self._lock 保持前提。呼び出し元は _upsert_users_locked(ingest)と
  _backfill_users(maintenance)で、いずれも lock 区間の内側から辿り着く。
  _latest_owner_handles_locked / _owner_handles_locked も self._lock 保持前提で、
  呼び出し元(streamer_index / streamer_profile / streamer_cohort / streamer_highlights /
  streamer_history_stats / session_ids_for_users / aggregate_dashboard)は
  すべて with self._lock: の内側で呼ぶ。
"""
import json
import time
from typing import Optional

from tictok.store._common import (
    NON_IDENTITY_KEYS,
    _USER_CACHE_MAX,
    _USER_UPSERT_TTL_SECONDS,
    _identity_key,
    _to_int,
    logger,
)


class UsersMixin:
    """User名寄せ(identity)・配信者handle解決・Fan台帳・発掘候補。

    lockもDB接続も持たない。すべて Storage が所有する self._conn /
    self._lock / self._read_lock を借りる(mixinとして Storage に混ぜられる前提)。
    契約の詳細はmodule docstringを参照。
    """

    def _upsert_user_locked(
        self, user: dict, ts: float, key: Optional[str] = None, use_cache: bool = False
    ) -> str:
        """Userの正規化プロフィールをusers表(唯一の真実)に反映する。identity_keyで名寄せし、
        変更されうる属性(名前/@handle/avatar/Lv/badge)は最新の非空値で上書きする。lock保持前提。
        keyが指定された場合はそれを使う(逆引き補完済みeventのidentity_keyを尊重するため)。
        use_cache時は属性が変わらない限り一定時間(TTL)はupsertを間引く(liveの高頻度取り込み用。
        last_seenの更新がTTL分遅れる副作用は許容。backfill等の正確性重視の呼び出しは間引かない)。"""
        # keyが明示されたらそのまま使う。空文字(身元不明)を偽値として拾ってnicknameから
        # 再計算すると、表示用の "(unknown)" で別人が1行へ畳まれる。
        if key is None:
            key = _identity_key(
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
                _to_int(user.get("fans_level")),
                _to_int(user.get("gifter_level")),
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
            # 新しいkeyを載せる時だけ上限を見る(dictは挿入順を保つので古い方から捨てる。
            # _battle_contrib_cacheと同じ扱い)。既存keyの入れ替え — TTL切れや属性変更 —
            # ではdictは伸びないため、そこで捨てるとTTL内のuserを巻き添えにhit率だけが落ちる。
            if cached is None and len(self._user_cache) >= _USER_CACHE_MAX:
                for stale in list(self._user_cache)[:_USER_CACHE_MAX // 4]:
                    del self._user_cache[stale]
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
                _to_int(user.get("fans_level")),
                _to_int(user.get("gifter_level")),
                user.get("gifter_badge") or "",
                user.get("member_badge") or "",
                ts,
                ts,
            ),
        )
        return key

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

    def _fill_owner(self, item: dict) -> dict:
        """履歴の各sessionは、そのsession自身が確定したowner identityで表示する。
        新配信で配信者が改名/アイコン変更しても過去sessionへは遡及させない方針のため、
        空でも最新配信のidentityは借りない。nicknameが空なら@handle(unique_id)で代替する。"""
        if not item.get("owner_nickname"):
            item["owner_nickname"] = item.get("unique_id") or ""
        if not item.get("owner_avatar"):
            item["owner_avatar"] = ""
        return item

    def _unidentified_gift_summary(self) -> dict:
        """台帳から外した身元不明eventの規模。黙って除外すると「Fan台帳の合計がSessionの
        coin合計と合わない」理由が画面から辿れなくなるため、件数と額を返して明示する。"""
        placeholders = ",".join("?" for _ in NON_IDENTITY_KEYS)
        row = self._conn.execute(
            "SELECT COUNT(*) AS events, COALESCE(SUM(diamonds), 0) AS diamonds"
            " FROM events WHERE kind = 'gift'"
            f" AND (identity_key IS NULL OR identity_key IN ({placeholders}))",
            NON_IDENTITY_KEYS,
        ).fetchone()
        return {"gift_events": row["events"] or 0, "diamonds": row["diamonds"] or 0}

    def fan_ledger(self, min_diamonds: int, limit: int) -> dict:
        """視聴者を主語にしたgift台帳。誰がどの配信者へ幾ら投げたかを横断で集計する。

        既存の配信者別gifter集計(streamer_profile)と同じqueryの形を使い、配信者での絞りを
        外して「identity_key × 配信者」で割る。こうすると1度の走査で通算と配信者別内訳の
        両方が出るので、内訳のために引き直さなくて済む。

        gift eventを持つ視聴者だけを台帳に載せる。events全kindを横断すると視聴者は35,000人
        規模になり(実測)、一覧として使えないうえ走査も一桁遅くなる。commentしかしない視聴者は
        別の指標であり、台帳の主題(誰が幾ら投じたか)とは分けて扱う。
        """
        placeholders = ",".join("?" for _ in NON_IDENTITY_KEYS)
        exclude = (
            f" AND e.identity_key IS NOT NULL AND e.identity_key NOT IN ({placeholders})"
        )
        with self._lock:
            rows = self._conn.execute(
                # 表示名はusers表を優先する。MAX(e.user_unique_id)は辞書順の最大を拾うだけで
                # 「最新のhandle」ではなく、実測では改名前の自動生成handle(user5037930325926)が
                # 現handle(harehare12345)を押しのけた。users表は毎eventで最新へupsertされる
                # 唯一の真実なので、eventの値はusers側が空のときだけ使う。
                "SELECT e.identity_key AS key, s.unique_id AS owner,"
                " COALESCE(NULLIF(u.user_id, ''), MAX(e.user_id)) AS user_id,"
                " COALESCE(NULLIF(u.unique_id, ''), MAX(e.user_unique_id)) AS unique_id,"
                " COALESCE(NULLIF(u.nickname, ''), MAX(e.user_nickname)) AS nickname,"
                " COALESCE(NULLIF(u.avatar, ''), MAX(e.user_avatar)) AS avatar,"
                " u.gifter_level AS gifter_level, u.first_seen AS first_seen,"
                " u.last_seen AS last_seen, SUM(e.diamonds) AS diamonds,"
                " SUM(e.gift_count) AS gifts, COUNT(DISTINCT e.session_id) AS sessions,"
                " MIN(e.time) AS first_gift, MAX(e.time) AS last_gift"
                " FROM events e JOIN sessions s ON s.id = e.session_id"
                " LEFT JOIN users u ON u.identity_key = e.identity_key"
                " WHERE e.kind = 'gift'" + exclude +
                " GROUP BY e.identity_key, s.unique_id",
                NON_IDENTITY_KEYS,
            ).fetchall()
            # commentは別kindなのでgiftの集計には相乗りできない。identity単位の件数だけを
            # 軽く引いて畳む(実測14ms)。全kindの横断走査は一覧には重すぎる。
            comment_rows = self._conn.execute(
                "SELECT e.identity_key AS key, COUNT(*) AS comments FROM events e"
                " WHERE e.kind = 'comment'" + exclude + " GROUP BY e.identity_key",
                NON_IDENTITY_KEYS,
            ).fetchall()
            unidentified = self._unidentified_gift_summary()

        comments = {r["key"]: r["comments"] or 0 for r in comment_rows}
        fans: dict = {}
        for row in rows:
            fan = fans.setdefault(
                row["key"],
                {
                    "identity_key": row["key"],
                    "user_id": row["user_id"] or "",
                    "unique_id": row["unique_id"] or "",
                    "nickname": row["nickname"] or row["unique_id"] or "(unknown)",
                    "avatar": row["avatar"] or "",
                    "gifter_level": row["gifter_level"] or 0,
                    "first_seen": row["first_seen"],
                    "last_seen": row["last_seen"],
                    "diamonds": 0,
                    "gifts": 0,
                    "sessions": 0,
                    "comments": comments.get(row["key"], 0),
                    "first_gift": None,
                    "last_gift": None,
                    "streamers": [],
                },
            )
            fan["diamonds"] += row["diamonds"] or 0
            fan["gifts"] += row["gifts"] or 0
            fan["sessions"] += row["sessions"] or 0
            for field, source, pick in (
                ("first_gift", "first_gift", min), ("last_gift", "last_gift", max),
            ):
                value = row[source]
                if value is not None:
                    current = fan[field]
                    fan[field] = value if current is None else pick(current, value)
            fan["streamers"].append(
                {
                    "unique_id": row["owner"],
                    "diamonds": row["diamonds"] or 0,
                    "gifts": row["gifts"] or 0,
                    "sessions": row["sessions"] or 0,
                }
            )

        for fan in fans.values():
            # 配信者別は必ず額の降順。「2人へ投げている」だけでは実態が分からず、実測では
            # 286,946 対 3 coin のような極端な偏りが普通にある。額を並べて出す。
            fan["streamers"].sort(key=lambda s: -s["diamonds"])
            fan["streamer_count"] = len(fan["streamers"])

        eligible = [f for f in fans.values() if f["diamonds"] >= min_diamonds]
        eligible.sort(key=lambda f: (-f["diamonds"], -f["gifts"]))
        multi = sum(1 for f in fans.values() if f["streamer_count"] > 1)
        logger.info(
            "fan台帳: %d 件を表示（対象 %d 件, gifter %d 人, 複数配信者 %d 人,"
            " min_diamonds=%d）",
            min(len(eligible), limit), len(eligible), len(fans), multi, min_diamonds,
            extra={"event": "storage.fan_ledger_scanned",
                   "ctx": {"gifters": len(fans), "eligible": len(eligible),
                           "multi_streamer": multi,
                           "unidentified_gift_events": unidentified["gift_events"]}},
        )
        return {
            "fans": eligible[:limit],
            "eligible": len(eligible),
            "total_gifters": len(fans),
            "multi_streamer": multi,
            "unidentified": unidentified,
            "min_diamonds": min_diamonds,
            "limit": limit,
            "generated_at": time.time(),
        }

    def fan_profile(self, identity_key: str) -> dict:
        """1人ぶんの台帳。配信者別の内訳とSession単位の明細を返す。

        eventの生行は返さない。実測で最上位のfanは47,000行(大半がlike)を持ち、明細として
        読めないうえ転送も走査も無駄になる。Session粒度まで畳んだものが台帳の単位である。
        """
        if identity_key in NON_IDENTITY_KEYS:
            raise ValueError("identity_key は1人の視聴者を指しません")
        with self._lock:
            identity = self._conn.execute(
                "SELECT identity_key, user_id, unique_id, nickname, avatar,"
                " fans_level, gifter_level, gifter_badge, first_seen, last_seen"
                " FROM users WHERE identity_key = ?",
                (identity_key,),
            ).fetchone()
            if identity is None:
                return {}
            session_rows = self._conn.execute(
                "SELECT e.session_id AS session_id, s.unique_id AS owner,"
                " s.started_at AS started_at, SUM(e.diamonds) AS diamonds,"
                " SUM(e.gift_count) AS gifts, MIN(e.time) AS first_gift,"
                " MAX(e.time) AS last_gift"
                " FROM events e JOIN sessions s ON s.id = e.session_id"
                " WHERE e.identity_key = ? AND e.kind = 'gift'"
                " GROUP BY e.session_id ORDER BY s.started_at DESC",
                (identity_key,),
            ).fetchall()
            kind_rows = self._conn.execute(
                "SELECT kind, COUNT(*) AS n FROM events WHERE identity_key = ?"
                " GROUP BY kind",
                (identity_key,),
            ).fetchall()

        sessions = [
            {
                "session_id": r["session_id"],
                "unique_id": r["owner"],
                "started_at": r["started_at"],
                "diamonds": r["diamonds"] or 0,
                "gifts": r["gifts"] or 0,
                "first_gift": r["first_gift"],
                "last_gift": r["last_gift"],
            }
            for r in session_rows
        ]
        by_streamer: dict = {}
        for s in sessions:
            entry = by_streamer.setdefault(
                s["unique_id"],
                {"unique_id": s["unique_id"], "diamonds": 0, "gifts": 0, "sessions": 0,
                 "first_gift": None, "last_gift": None},
            )
            entry["diamonds"] += s["diamonds"]
            entry["gifts"] += s["gifts"]
            entry["sessions"] += 1
            for field, pick in (("first_gift", min), ("last_gift", max)):
                value = s[field]
                if value is not None:
                    current = entry[field]
                    entry[field] = value if current is None else pick(current, value)
        streamers = sorted(by_streamer.values(), key=lambda e: -e["diamonds"])
        return {
            "identity_key": identity["identity_key"],
            "user_id": identity["user_id"] or "",
            "unique_id": identity["unique_id"] or "",
            "nickname": identity["nickname"] or identity["unique_id"] or "(unknown)",
            "avatar": identity["avatar"] or "",
            "fans_level": identity["fans_level"] or 0,
            "gifter_level": identity["gifter_level"] or 0,
            "gifter_badge": identity["gifter_badge"] or "",
            "first_seen": identity["first_seen"],
            "last_seen": identity["last_seen"],
            "diamonds": sum(s["diamonds"] for s in sessions),
            "gifts": sum(s["gifts"] for s in sessions),
            "activity": {r["kind"]: r["n"] for r in kind_rows},
            "streamers": streamers,
            "sessions": sessions,
        }

    def dismiss_discovery_candidate(self, unique_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO discovery_dismissed (unique_id, dismissed_at) VALUES (?, ?)"
                " ON CONFLICT(unique_id) DO UPDATE SET dismissed_at = excluded.dismissed_at",
                (unique_id, time.time()),
            )
            self._conn.commit()

    def restore_discovery_candidate(self, unique_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM discovery_dismissed WHERE unique_id = ?", (unique_id,)
            )
            self._conn.commit()

    def list_dismissed_candidates(self) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT unique_id, dismissed_at FROM discovery_dismissed"
                " ORDER BY dismissed_at DESC"
            ).fetchall()
        return [
            {"unique_id": row["unique_id"], "dismissed_at": row["dismissed_at"]}
            for row in rows
        ]

    def discovery_candidates(
        self, min_contacts: int, half_life_days: float, limit: int
    ) -> dict:
        """未監視だがBattleで繰り返し当たっている配信者を、接触の多い順に返す。

        順位は「時間減衰つき接触回数」= Σ 0.5^(経過日数 / 半減期) で決める。生の回数だけ
        で並べると、もう当たらなくなった相手がいつまでも上位に居座り、逆に直近だけを見ると
        たまたま1回当たった相手が常連を押しのける。半減期つきの減衰和は両方を1つの値に
        まとめる標準的なやり方で、半減期は設定で変えられる。

        同じBattleは(battle_id, 相手)単位で1回だけ数える。1つのBattleを複数の監視配信者が
        別々のsessionで観測する(同陣営に2人監視している/両陣営とも監視対象)ため、素直に
        数えると同じ対戦が接触2回に化ける。

        start_time / battle_id を欠くBattleは数えない。どちらも減衰にも重複除外にも必須で、
        代わりの値を当てると「実際には無かった接触」を作ることになる。
        """
        if half_life_days <= 0:
            raise ValueError("half_life_days must be positive")
        with self._lock:
            rows = self._conn.execute(
                "SELECT b.data_json AS data_json, s.unique_id AS own_id"
                " FROM battles b JOIN sessions s ON s.id = b.session_id"
            ).fetchall()
            monitored = {
                r["unique_id"]
                for r in self._conn.execute("SELECT unique_id FROM monitored_targets")
            }
            dismissed = {
                r["unique_id"]
                for r in self._conn.execute("SELECT unique_id FROM discovery_dismissed")
            }

        now = time.time()
        aggregated: dict = {}
        seen_contacts = set()
        skipped_unidentified = 0
        skipped_incomplete = 0
        for row in rows:
            battle = json.loads(row["data_json"])
            start_time = battle.get("start_time")
            battle_id = battle.get("battle_id")
            if start_time is None or not battle_id:
                skipped_incomplete += 1
                continue
            age_days = max(0.0, (now - start_time) / 86400.0)
            weight = 0.5 ** (age_days / half_life_days)
            for opponent in battle.get("opponents", []) or []:
                # unique_id(=@handle)が無い相手は監視を開始する手段が無い。nicknameは
                # 変わるうえ重複するので、代わりのkeyにはできない。
                handle = (opponent.get("unique_id") or "").strip()
                if not handle:
                    skipped_unidentified += 1
                    continue
                if handle in monitored or handle in dismissed:
                    continue
                entry = aggregated.setdefault(
                    handle,
                    {
                        "unique_id": handle,
                        "nickname": opponent.get("nickname") or handle,
                        "avatar": opponent.get("avatar") or "",
                        "user_id": opponent.get("user_id") or "",
                        "contacts": 0,
                        "score": 0.0,
                        "first_contact": start_time,
                        "last_contact": start_time,
                        "via": set(),
                    },
                )
                # viaは重複観測でも積む。「同じBattleを2人が見た」ことは接触2回では
                # ないが、その相手が2人の監視配信者と当たっている事実は候補の判断材料
                # であり、1件目の観測者だけ残すとその情報が落ちる。
                entry["via"].add(row["own_id"])
                if not entry["avatar"] and opponent.get("avatar"):
                    entry["avatar"] = opponent["avatar"]
                contact = (battle_id, handle)
                if contact in seen_contacts:
                    continue
                seen_contacts.add(contact)
                entry["contacts"] += 1
                entry["score"] += weight
                entry["first_contact"] = min(entry["first_contact"], start_time)
                entry["last_contact"] = max(entry["last_contact"], start_time)

        eligible = [e for e in aggregated.values() if e["contacts"] >= min_contacts]
        eligible.sort(key=lambda e: (-e["score"], -e["last_contact"]))
        candidates = []
        for entry in eligible[:limit]:
            candidate = dict(entry)
            candidate["via"] = sorted(entry["via"])
            candidate["score"] = round(entry["score"], 3)
            candidates.append(candidate)

        logger.info(
            "配信者の候補: %d 件を表示（対象 %d 件, 観測 %d 件, min_contacts=%d,"
            " half_life=%.1f日）",
            len(candidates), len(eligible), len(aggregated), min_contacts, half_life_days,
            extra={"event": "storage.discovery_scanned",
                   "ctx": {"shown": len(candidates), "eligible": len(eligible),
                           "seen": len(aggregated), "monitored": len(monitored),
                           "dismissed": len(dismissed),
                           "skipped_unidentified": skipped_unidentified,
                           "skipped_incomplete": skipped_incomplete}},
        )
        return {
            "candidates": candidates,
            "eligible": len(eligible),
            "seen": len(aggregated),
            "dismissed": len(dismissed),
            "skipped_unidentified": skipped_unidentified,
            "skipped_incomplete": skipped_incomplete,
            "min_contacts": min_contacts,
            "half_life_days": half_life_days,
            "limit": limit,
            "generated_at": now,
        }
