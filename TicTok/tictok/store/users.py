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
  _backfill_users(maintenance)、save_peer_identity(コラボ相手の身元)で、いずれも
  lock 区間の内側から辿り着く。
  _latest_owner_handles_locked / _owner_handles_locked も self._lock 保持前提で、
  呼び出し元(streamer_index / streamer_profile / streamer_cohort /
  streamer_history_stats / session_ids_for_users / aggregate_dashboard)は
  すべて with self._lock: の内側で呼ぶ。
"""
import json
import time
from typing import Optional

from tictok.core.league import display_league, display_league_sql
from tictok.search.normalize import MentionNames
from tictok.store._common import (
    NON_IDENTITY_KEYS,
    USER_ALIAS_MAX,
    _MENTION_NAMES_TTL_SECONDS,
    _USER_CACHE_MAX,
    _USER_UPSERT_TTL_SECONDS,
    _identity_key,
    _to_int,
    logger,
)


class UsersMixin:
    """User名寄せ(identity)・配信者handle解決・Fan台帳・発掘候補。

    lockもDB接続も持たない。すべて Storage が所有する self._conn /
    self._lock / _read_connection() を借りる(mixinとして Storage に混ぜられる前提)。
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

    def _load_mention_names(self, conn) -> MentionNames:
        """既知の表示名(と@handle)を読む。接続は呼び出し側が選ぶ。

        lock契約の都合で口を分けてある。索引の投入は self._lock を取る前に読める(read側)が、
        起動時のmigrationは既に self._lock を保持しているので書き込み接続で読むしかない。
        """
        rows = conn.execute(
            "SELECT nickname AS name FROM users WHERE nickname IS NOT NULL AND nickname != ''"
            " UNION"
            " SELECT unique_id FROM users WHERE unique_id IS NOT NULL AND unique_id != ''"
        ).fetchall()
        return MentionNames(row[0] for row in rows)

    def mention_names(self) -> MentionNames:
        """本文の先頭メンションを索引から外すための、既知の表示名。

        出所がusers表なのは、名前の切れ目が表示名そのものでしか決まらないため(空白を含む
        表示名がある)。全観測userの台帳はここだけである。

        実測31.8万件・読み込み0.4秒。録画1本ごとのindex投入で毎回引くには重いのでTTLで持つ。
        保持中に現れた新規userへのメンションは名前で切れず空白へ落ちるが、その録画を張り直せば
        直る種類のズレなので、常に最新であることより読み込みの安さを取る。
        """
        now = time.time()
        if (self._mention_names is not None
                and now - self._mention_names_at < _MENTION_NAMES_TTL_SECONDS):
            return self._mention_names
        names = self._load_mention_names(self._read_connection())
        self._mention_names = names
        self._mention_names_at = now
        return names

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

    def peer_identities(self, user_ids) -> dict:
        """user_id -> 表示できる身元(nickname/@handle/avatar)。users表(名寄せの唯一の真実)を
        主keyで引く。identity_keyは不変user_id優先なので、これは主key照合である。

        名前も@handleも無い行は返さない。IDだけの行を返すと、呼び出し側は「解決できた」と
        読んで数値IDを名前の位置へ出すことになる。"""
        keys = [str(uid).strip() for uid in user_ids if str(uid or "").strip()]
        if not keys:
            return {}
        placeholders = ",".join("?" * len(keys))
        with self._lock:
            rows = self._conn.execute(
                "SELECT identity_key, unique_id, nickname, avatar FROM users"
                f" WHERE identity_key IN ({placeholders})",
                keys,
            ).fetchall()
        out: dict = {}
        for row in rows:
            nickname = (row["nickname"] or "").strip()
            unique_id = (row["unique_id"] or "").strip()
            if not nickname and not unique_id:
                continue
            out[row["identity_key"]] = {
                "nickname": nickname,
                "unique_id": unique_id,
                "avatar": row["avatar"] or "",
            }
        return out

    def save_peer_identity(
        self, user_id: str, unique_id: str, nickname: str, avatar: str,
        room_id: str = "", now: Optional[float] = None,
    ) -> str:
        """コラボ相手(共演者)の身元をusers表へ残す。LinkLayerはuser_idとroom_idしか
        名乗らないため、collectorが相手のroom_infoを引いた結果をここへ書く。次のprocessは
        通信せずに名前を出せる。

        broadcaster/league/league_checked_atには触らない。あれはリーグ取得workerが
        「@handleで照会して確かめた」という別の観測で、こちらは室を1つ見ただけである。
        room_idは過去の室でもleagueを引けるので、判っている値として残す。"""
        now = time.time() if now is None else now
        with self._lock:
            key = self._upsert_user_locked(
                {"user_id": str(user_id or ""), "unique_id": unique_id or "",
                 "nickname": nickname or "", "avatar": avatar or ""},
                now,
                key=str(user_id or "").strip(),
            )
            if key and room_id:
                self._conn.execute(
                    "UPDATE users SET broadcaster_room_id = ? WHERE identity_key = ?",
                    (str(room_id), key),
                )
            self._conn.commit()
        return key

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
        空でも最新配信のidentityは借りない。nicknameが空なら@handle(unique_id)で代替する。

        身元を一度も観測できなかった古い行のアイコンは、画面側が/api/avatar?id=…で
        unique_id単位のpoolを引いて描く(表示だけの補完で、行の値は空のまま)。"""
        if not item.get("owner_nickname"):
            item["owner_nickname"] = item.get("unique_id") or ""
        if not item.get("owner_avatar"):
            item["owner_avatar"] = ""
        return item

    def _unidentified_gift_summary(self, conn) -> dict:
        """台帳から外した身元不明eventの規模。黙って除外すると「Fan台帳の合計がSessionの
        coin合計と合わない」理由が画面から辿れなくなるため、件数と額を返して明示する。
        接続は呼び出し元から受け取る(台帳本体と同じ接続・同じ時点で数えるため)。"""
        placeholders = ",".join("?" for _ in NON_IDENTITY_KEYS)
        row = conn.execute(
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
        # gift eventとcomment eventを全期間ぶん走査する(実測で合わせて421ms)。書き込み接続で
        # 流すとその間collectorのevent書き出しが同じlockで待たされるので、同じ形のgifter集計を
        # 持つstreamer_profileと同様に集計read専用の接続を使う。
        conn = self._read_connection()
        rows = conn.execute(
            # 表示名はusers表を優先する。MAX(e.user_unique_id)は辞書順の最大を拾うだけで
            # 「最新のhandle」ではなく、実測では改名前の自動生成handle(user0000000000001)が
            # 現handle(viewer_01)を押しのけた。users表は毎eventで最新へupsertされる
            # 唯一の真実なので、eventの値はusers側が空のときだけ使う。
            "SELECT e.identity_key AS key, s.unique_id AS owner,"
            " COALESCE(NULLIF(u.user_id, ''), MAX(e.user_id)) AS user_id,"
            " COALESCE(NULLIF(u.unique_id, ''), MAX(e.user_unique_id)) AS unique_id,"
            " COALESCE(NULLIF(u.nickname, ''), MAX(e.user_nickname)) AS nickname,"
            # avatarは event_strings へinternしてある。**MAX(e.user_avatar_id) にしては
            # ならない** ―― 元のMAXは値そのものの辞書順最大で、idの最大(=最初に見た順)とは
            # 別物である。値へJOINしてから MAX を採ることで、旧と同じ行が出る。
            " COALESCE(NULLIF(u.avatar, ''), MAX(av.value)) AS avatar,"
            " u.gifter_level AS gifter_level, u.fans_level AS fans_level,"
            # この視聴者自身が配信者である場合のリーグ帯(取れていなければ空=非表示)。
            f" {display_league_sql('u')} AS league,"
            " u.first_seen AS first_seen,"
            " u.last_seen AS last_seen, SUM(e.diamonds) AS diamonds,"
            " SUM(e.gift_count) AS gifts, COUNT(DISTINCT e.session_id) AS sessions,"
            " MIN(e.time) AS first_gift, MAX(e.time) AS last_gift"
            " FROM events e JOIN sessions s ON s.id = e.session_id"
            " LEFT JOIN users u ON u.identity_key = e.identity_key"
            " LEFT JOIN event_strings av ON av.id = e.user_avatar_id"
            " WHERE e.kind = 'gift'" + exclude +
            " GROUP BY e.identity_key, s.unique_id",
            NON_IDENTITY_KEYS,
        ).fetchall()
        # commentは別kindなのでgiftの集計には相乗りできない。identity単位の件数だけを
        # 軽く引いて畳む(実測14ms)。全kindの横断走査は一覧には重すぎる。
        comment_rows = conn.execute(
            "SELECT e.identity_key AS key, COUNT(*) AS comments FROM events e"
            " WHERE e.kind = 'comment'" + exclude + " GROUP BY e.identity_key",
            NON_IDENTITY_KEYS,
        ).fetchall()
        unidentified = self._unidentified_gift_summary(conn)

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
                    "fans_level": row["fans_level"] or 0,
                    "league": row["league"] or "",
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
                " fans_level, gifter_level, gifter_badge, member_badge, league,"
                " broadcaster, league_checked_at, first_seen, last_seen"
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
            "member_badge": identity["member_badge"] or "",
            # この視聴者自身が配信者かどうか。leagueはD帯を落とした表示用の値で、
            # broadcasterはNULL(未確認)と0(確認して配信者ではない)を区別する。
            "league": display_league(identity["league"]),
            "broadcaster": (
                None if identity["broadcaster"] is None else bool(identity["broadcaster"])
            ),
            "league_checked_at": identity["league_checked_at"],
            "first_seen": identity["first_seen"],
            "last_seen": identity["last_seen"],
            "diamonds": sum(s["diamonds"] for s in sessions),
            "gifts": sum(s["gifts"] for s in sessions),
            "activity": {r["kind"]: r["n"] for r in kind_rows},
            "streamers": streamers,
            "sessions": sessions,
        }

    def set_user_alias(self, identity_key: str, alias: str) -> dict:
        """投稿へ貼る文面で名前の代わりに出す省略形を1人ぶん置く。空なら行ごと消す。

        users表へ書かないのは、あちらがeventの来るたび最新の非空値で上書きされるためで
        ある(次の配信で消えて付け直しになる)。人が付けた層は別の表に置く。

        1人を指さないkey(NON_IDENTITY_KEYS)は受け取らない —— '' や '(unknown)' は複数の
        別人が畳まれた跡なので、省略形を付けると別人の名前として貼られる。
        """
        key = (identity_key or "").strip()
        if key in NON_IDENTITY_KEYS:
            raise ValueError(f"1人を指さないidentity_keyです: {identity_key!r}")
        text = " ".join((alias or "").split())
        if len(text) > USER_ALIAS_MAX:
            raise ValueError(
                f"省略形は{USER_ALIAS_MAX}文字までです: {len(text)}文字")
        with self._lock:
            if text:
                self._conn.execute(
                    "INSERT INTO user_aliases (identity_key, alias, updated_at)"
                    " VALUES (?, ?, ?) ON CONFLICT(identity_key) DO UPDATE SET"
                    " alias = excluded.alias, updated_at = excluded.updated_at",
                    (key, text, time.time()),
                )
            else:
                self._conn.execute(
                    "DELETE FROM user_aliases WHERE identity_key = ?", (key,))
            self._conn.commit()
        return {"identity_key": key, "alias": text}

    def list_user_aliases(self) -> dict:
        """identity_key -> 省略形。付いている人だけが入る(空の行は置かない)。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT identity_key, alias FROM user_aliases").fetchall()
        return {row["identity_key"]: row["alias"] for row in rows}

    def _merge_person_locked(self, conn, key: str) -> dict:
        """束ねの画面へ出す1人ぶんの名乗り。users表に行が無いkeyも名前を作らずに返す ——
        束ねた相手が最近現れていないだけで、束ね自体は残っているためである。"""
        row = conn.execute(
            "SELECT u.identity_key AS identity_key, u.user_id AS user_id,"
            " u.unique_id AS unique_id, u.nickname AS nickname, u.avatar AS avatar,"
            " COALESCE(a.alias, '') AS alias"
            " FROM users u LEFT JOIN user_aliases a ON a.identity_key = u.identity_key"
            " WHERE u.identity_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return {"identity_key": key, "user_id": "", "unique_id": "",
                    "nickname": "(unknown)", "avatar": "", "alias": ""}
        return {
            "identity_key": row["identity_key"],
            "user_id": row["user_id"] or "",
            "unique_id": row["unique_id"] or "",
            "nickname": row["nickname"] or "(unknown)",
            "avatar": row["avatar"] or "",
            "alias": row["alias"] or "",
        }

    def _merge_key_locked(self, key: str) -> str:
        """そのkeyの集計先。束ねられている側なら主のkey、そうでなければ自分自身。"""
        row = self._conn.execute(
            "SELECT primary_key FROM user_merges WHERE member_key = ?", (key,)
        ).fetchone()
        return row["primary_key"] if row else key

    def merge_users(self, member_key: str, primary_key: str) -> dict:
        """サブアカウント(member)を主アカウント(primary)へ束ねる。

        束ねるのは日のGifterの集計だけで、eventもusers表も書き換えない —— 観測した
        事実(どのアカウントが投げたか)は残したまま、人の判断だけを別の層に置く
        (省略形をuser_aliasesへ分けたのと同じ理由)。

        段は作らない。primaryが既に誰かへ束ねられていればその主へ寄せ、memberが主に
        なっている束ねはその全員ごと連れて行く。段を許すと「AはBへ、BはCへ」の途中で
        環ができ、集計の畳み先が引く順で変わる。

        1人を指さないkey(NON_IDENTITY_KEYS)は受け取らない —— '' や '(unknown)' は
        複数の別人が畳まれた跡なので、束ねると無関係の人のコインが1人に積まれる。
        """
        member = (member_key or "").strip()
        primary = (primary_key or "").strip()
        for key in (member, primary):
            if key in NON_IDENTITY_KEYS:
                raise ValueError(f"1人を指さないidentity_keyです: {key!r}")
        if member == primary:
            raise ValueError("同じアカウントは束ねられません")
        with self._lock:
            primary = self._merge_key_locked(primary)
            if primary == member:
                # 主にしようとした相手が、既にこのアカウントのサブである。ここで書くと
                # 主とサブが入れ替わる(人が意図したのか読めない)ので、外してから束ね直す。
                raise ValueError("既にこのアカウントへ束ねている相手です")
            now = time.time()
            # memberが主だった束ねは、その全員ごと新しい主へ寄せる。置き去りにすると、
            # 主だけが移って残りが「主の居ない束ね」になる。
            self._conn.execute(
                "UPDATE user_merges SET primary_key = ?, updated_at = ?"
                " WHERE primary_key = ?", (primary, now, member))
            self._conn.execute(
                "INSERT INTO user_merges (member_key, primary_key, updated_at)"
                " VALUES (?, ?, ?) ON CONFLICT(member_key) DO UPDATE SET"
                " primary_key = excluded.primary_key,"
                " updated_at = excluded.updated_at",
                (member, primary, now))
            self._conn.commit()
        logger.info(
            "サブアカウントを束ねました",
            extra={"event": "user_merge_set",
                   "ctx": {"member_key": member, "primary_key": primary}})
        return self.user_merge_group(primary)

    def unmerge_user(self, member_key: str) -> dict:
        """束ねを1件外す。外すのはサブ側の行だけで、同じ主の他のサブは残る。"""
        member = (member_key or "").strip()
        with self._lock:
            self._conn.execute(
                "DELETE FROM user_merges WHERE member_key = ?", (member,))
            self._conn.commit()
        logger.info(
            "サブアカウントの束ねを外しました",
            extra={"event": "user_merge_cleared", "ctx": {"member_key": member}})
        return {"member_key": member}

    def user_merge_group(self, primary_key: str) -> dict:
        """主1人ぶんの束ね(主+サブの名乗り)。サブが1人も居なければmembersは空。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT member_key, updated_at FROM user_merges"
                " WHERE primary_key = ? ORDER BY updated_at",
                (primary_key,),
            ).fetchall()
            group = {
                "primary": self._merge_person_locked(self._conn, primary_key),
                "members": [self._merge_person_locked(self._conn, row["member_key"])
                            for row in rows],
                "updated_at": max([row["updated_at"] for row in rows], default=0.0),
            }
        return group

    def list_user_merges(self) -> list:
        """束ねの一覧。1件が主1人ぶんで、直近に触った束ねが先。

        名乗りまで込みで返すのは、束ねたサブが日の顔ぶれから消えるためである ——
        keyだけ返すと、外したい相手を画面から選べなくなる。
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT member_key, primary_key, updated_at FROM user_merges"
            ).fetchall()
            groups: dict = {}
            for row in rows:
                group = groups.setdefault(
                    row["primary_key"],
                    {"primary": self._merge_person_locked(self._conn, row["primary_key"]),
                     "members": [], "updated_at": 0.0})
                group["members"].append(
                    self._merge_person_locked(self._conn, row["member_key"]))
                group["updated_at"] = max(group["updated_at"], row["updated_at"] or 0.0)
        return sorted(groups.values(), key=lambda g: -g["updated_at"])

    def user_merge_map(self) -> dict:
        """``{サブのidentity_key: 主のidentity_key}``。束ねられている人だけが入る。

        束ねを**畳み先の辞書として**読む唯一の口である。:meth:`list_user_merges` は名乗り
        まで込みの一覧(画面が束ねの中身を出すためのもの)なので、集計や照合があれを解いて
        畳み先を組み立てると、畳み方の規則が読む側の数だけ増える。

        段は作らない規則が :meth:`merge_users` に在るので、1回引けば畳み先が決まる ——
        値をもう一度この辞書で引き直す必要は無い(引き直しても同じ値になる)。
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT member_key, primary_key FROM user_merges").fetchall()
        return {row["member_key"]: row["primary_key"] for row in rows}

    def user_person_key(self, identity_key) -> str:
        """そのkeyの畳み先。束ねられていれば主のkey、そうでなければ自分自身。

        1件だけ引く口である(:meth:`user_merge_map` は全件)。切り出す直前の照合
        (:func:`tictok.media.highlight_export.verify_item`)がここを通るのは、**あの場では
        手元の値を1つも信用せずDBを引き直す**という約束のためで、計画の段で作った辞書を
        渡さない —— 計画から書き出しまでの間に束ねが変わっていれば、変わった後の答えで
        判ずるのが正しい。
        """
        key = (identity_key or "").strip()
        if not key:
            return ""
        with self._lock:
            return self._merge_key_locked(key)

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
