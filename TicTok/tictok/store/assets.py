"""素材pool(Userアイコン / Giftアイコン / Emote)を名乗るための読み出し。

境界の理由: 素材の実体はdiskのpool(``layout.avatar_pool_dir`` 他)に在り、DBは1 byteも
持っていない。ここに在るのは「そのfileが誰の・何のものか」を名乗るための読み出しと、
走査結果のsnapshotだけである:

  ``asset_user_page``   avatarのfile名の素になるuser(users表)。avatarのfile名は
                        ``sha1(unique_id or nickname)`` で、disk側にはその鍵しか無い。
                        鍵から人へ戻す道はusers表にしか無いので、一覧の源はdiskではなく
                        こちらになる。
  ``asset_user_keys``   その鍵から人へ戻すための全件。file名を人が読める形にする経路
                        (1件のdownload・ZIP・「名前を辿れる素材の点数」の算出)が使う。
  ``gift_names_by_id``  gift_idに対する表示名(events)。実測500msかかるので、呼ぶのは
                        走査(rescan)の契機だけで、結果は下のsnapshotへ載せる。
  ``get_asset_scans`` / ``save_asset_scan``
                        種別ごとの走査結果(``asset_scan`` 表)。素材pageは常にこれを
                        返し、diskは歩かない(表のSQL commentに理由がある)。

users mixinへ寄せなかったのは、gift名の解決がusers表と無関係な events の読み出しであり、
離すと素材画面のDB読み取りが2箇所に散るためである。

lock契約:
  読み取り(``asset_user_page`` / ``asset_user_keys`` / ``gift_names_by_id``)は集計read専用
  接続(``_read_connection``)で流すので self._lock は取らない。read専用接続はcommit済みしか
  見ないが、gift名もuserの最終観測時刻も0.2秒の遅れが意味を変えない値なので、呼び出し側の
  flushは要らない。
  snapshotの読み書き(``get_asset_scans`` / ``save_asset_scan``)だけは self._lock を自分で
  取り、writer接続を使う —— 書いた直後に同じ値を読み返して応答へ載せるため
  (``storage_scan`` と同じ作法)。lock保持前提のmethodは無い。
"""

import json
import time
from typing import Optional

from tictok.store._common import NON_IDENTITY_KEYS

# 素材画面のUserアイコン一覧が受け付ける並び順。SQLの列名へはここでしか変換しない
# (client由来の文字列をSQLへ入れる口を1つに絞る)。size / mtime が無いのは、その2つが
# diskのfileの属性でありusers表に無いためで、代用は置かない — 別の値で黙って並べると、
# 押した並び順と出てくる順が食い違う。freq は asset_avatar_freq との結合が要るので、
# これを選ぶと母集団が変わる(asset_user_page のdocstring)。
ASSET_USER_SORTS = {"name": "u.nickname", "last_seen": "u.last_seen", "freq": "f.uses"}

# 身元を名乗れない行を外す条件。avatarのfile名は ``sha1(unique_id or nickname)`` なので、
# そのどちらも空の行は sha1("") という誰の物でもない単一の鍵を指す。実測で193,360行中1行。
_IDENTIFIED = "COALESCE(NULLIF(unique_id, ''), NULLIF(nickname, '')) IS NOT NULL"


class AssetsMixin:
    """素材poolのfileを名乗るための読み出し。

    lockもDB接続も持たない。すべて Storage が所有する self._read_connection() を借りる。
    契約の詳細はmodule docstringを参照。
    """

    @staticmethod
    def _asset_like(text: str) -> str:
        """LIKEのmeta文字を無効化した部分一致pattern。ESCAPE句と対で使う。

        検索語には '_' を含む handle(``some_user``)が普通に来る。escapeしないと '_' が
        任意1文字として当たり、``someXuser`` まで拾う。"""
        escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    def asset_user_page(self, q: str, sort: str, order: str,
                        limit: int, offset: int, streamer: str = "") -> tuple:
        """素材画面のUserアイコン一覧の1ページと、絞り込みに一致する総数を返す。

        源は **users表であってdiskの走査ではない**。poolのfile名は
        ``sha1(unique_id or nickname)`` の40桁hexで、file側には人へ戻す情報が一切無い。
        diskを一覧の源にすると、22万件の鍵だけが並んで誰のものか読めない画面になる。

        cacheの有無で行を落とさないのは呼び出し側(route)の責務。ここは「名乗れるuser」を
        そのまま返し、fileが在るかは触らない — DBの行数とdiskのfile数が一致しないのは
        普通の状態(取得に失敗したuser、poolに残っていてusers表に居ないfile)なので、
        どちらか片方を真として他方を切ると総数が嘘になる。

        **母集団を変えるのは ``streamer`` だけである。** 配信者を指定すると
        ``asset_avatar_freq`` との内部結合になり、その配信者の配信に一度も現れていない人は
        行として出ない(``total`` にもそのまま出る)。

        ``sort='freq'`` は母集団を変えない。出現回数を持たない人(実測で193,359人中
        105,000人弱、contributor sampleやコラボ相手の身元だけが入っている人)も外部結合で
        残し、末尾へ回す —— 並べ替えを選んだだけで一覧から人が消えるのは、絞り込みと
        並べ替えの区別が画面から読めなくなる。0を入れて並べないので、その人の応答には
        出現回数の項目自体が載らない。

        ``sort`` / ``order`` は route が :data:`ASSET_USER_SORTS` で検証済みの値を渡す。
        並びを安定させるため第2 keyに identity_key を置く: nickname も last_seen も
        出現回数も重複するので、これが無いとpageを跨いで同じ行が二度出たり抜けたりする。
        """
        column = ASSET_USER_SORTS[sort]
        direction = "DESC" if order == "desc" else "ASC"
        where = [_IDENTIFIED]
        params: list = []
        where = [w.replace("unique_id", "u.unique_id").replace("nickname", "u.nickname")
                 for w in where]
        joined = bool(streamer) or sort == "freq"
        if streamer:
            # 絞り込み。その配信者に現れた人だけを残す。
            source = ("users u JOIN asset_avatar_freq f"
                      " ON f.identity_key = u.identity_key AND f.streamer = ?")
            params.append(streamer)
        elif sort == "freq":
            # 並べ替えだけ。全配信者の合計(streamer='')を外部結合で添える —— 内部結合に
            # すると、並べ替えを選んだだけで出現回数を持たない人が消える。
            source = ("users u LEFT JOIN asset_avatar_freq f"
                      " ON f.identity_key = u.identity_key AND f.streamer = ''")
        else:
            source = "users u"
        if q:
            where.append("(u.unique_id LIKE ? ESCAPE '\\'"
                         " OR u.nickname LIKE ? ESCAPE '\\')")
            like = self._asset_like(q)
            params.extend([like, like])
        clause = " WHERE " + " AND ".join(where)
        conn = self._read_connection()
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM {source}{clause}", params
        ).fetchone()["n"]
        rows = conn.execute(
            "SELECT u.identity_key AS identity_key, u.user_id AS user_id,"
            " u.unique_id AS unique_id, u.nickname AS nickname,"
            " u.last_seen AS last_seen,"
            + (" f.uses AS uses" if joined else " NULL AS uses")
            + f" FROM {source}{clause}"
            + f" ORDER BY {column} {direction}, u.identity_key ASC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return [dict(row) for row in rows], int(total or 0)

    def asset_streamers(self) -> list:
        """素材画面が配信者filterに並べる配信者。``[{unique_id, label}]``。

        表示名の決め方は他画面と同じ —— 最新sessionの空でない ``owner_nickname``、無ければ
        ``unique_id``(``_latest_owners`` / ``_fill_owner`` と同じrule)。@handleを改名した
        配信者でlabelが不定にならないよう、相関subqueryで最新の1件を決定的に選ぶ。

        画面に配信者を書かせないためにserverが配る。書かせると、監視対象が増えた日に
        画面だけが黙って古いままになる。"""
        rows = self._read_connection().execute(
            "SELECT unique_id,"
            " (SELECT owner_nickname FROM sessions s2 WHERE s2.unique_id = s.unique_id"
            "  AND owner_nickname IS NOT NULL AND owner_nickname != ''"
            "  ORDER BY started_at DESC LIMIT 1) AS nickname"
            " FROM sessions s GROUP BY unique_id ORDER BY unique_id"
        ).fetchall()
        return [{"unique_id": row["unique_id"],
                 "label": row["nickname"] or row["unique_id"]}
                for row in rows]

    def asset_user_keys(self) -> list:
        """身元を名乗れる全userの (user key, unique_id, nickname)。

        user key は avatar poolのfile名を作るのに使う値そのもの(``unique_id`` が在れば
        それ、無ければ ``nickname``)で、呼び出し側が ``avatar_key()`` に掛けて40桁hexへ
        変換する。sha1をSQLで計算できないため、鍵からuserへ戻すにはこの全件を1度読んで
        逆引きを組むしかない(実測: 193,359行の読み出し0.26秒 + sha1 0.27秒)。

        一覧には使わない。使うのはfile名を人が読める形にする経路 —— 1件のdownloadと
        ZIPのまとめ —— だけで、どちらも人が押したときにしか走らない。
        """
        rows = self._read_connection().execute(
            "SELECT unique_id, nickname FROM users WHERE " + _IDENTIFIED
        ).fetchall()
        return [
            ((row["unique_id"] or row["nickname"] or ""),
             row["unique_id"] or "", row["nickname"] or "")
            for row in rows
        ]

    def get_asset_scans(self) -> dict:
        """種別ごとの走査結果 {kind: {...}}。まだ走査していない種別は**現れない**。

        現れない種別を0件として返さない。「素材が1つも無い」と「まだ数えていない」は
        別の事実で、混ぜると画面が『0件』と嘘をつく(``get_storage_scan`` がNoneを返して
        『まだ走査していない』を名乗るのと同じ理由)。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT kind, scanned_at, duration_ms, item_count, listable_count,"
                " total_bytes, payload_json FROM asset_scan"
            ).fetchall()
        return {
            row["kind"]: {
                "scanned_at": row["scanned_at"],
                "duration_ms": row["duration_ms"],
                "count": row["item_count"],
                "listable": row["listable_count"],
                "bytes": row["total_bytes"],
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        }

    def save_asset_scan(self, kind: str, count: int, listable: int, total_bytes: int,
                        duration_ms: float, payload: Optional[dict] = None) -> None:
        """1種別の走査結果を全置換で保存する。

        ``count``(diskに在る点数)と ``listable``(そのうち一覧に出せる点数)は必ず一緒に
        渡す。表のSQL commentの通り、別々の契機で採ると2つの数字がいつの時点のものか
        読めなくなる。

        ``payload`` を省略すると**保存済みのものを残す**。安い種別(gift_icon / emote)は
        一覧を作るついでにdirを歩いて件数を数え直すが、その経路はpayloadの中身
        (eventsから引いたgift名・実測500ms)を持っていない。省略を「空で上書き」にすると、
        一覧を1回開くだけでgift名が全部消える。"""
        values = (kind, time.time(), duration_ms, int(count), int(listable),
                  int(total_bytes))
        keep = ("scanned_at = excluded.scanned_at, duration_ms = excluded.duration_ms,"
                " item_count = excluded.item_count,"
                " listable_count = excluded.listable_count,"
                " total_bytes = excluded.total_bytes")
        with self._lock:
            if payload is None:
                self._conn.execute(
                    "INSERT INTO asset_scan (kind, scanned_at, duration_ms, item_count,"
                    " listable_count, total_bytes) VALUES (?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(kind) DO UPDATE SET " + keep,
                    values,
                )
            else:
                self._conn.execute(
                    "INSERT INTO asset_scan (kind, scanned_at, duration_ms, item_count,"
                    " listable_count, total_bytes, payload_json)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(kind) DO UPDATE SET " + keep
                    + ", payload_json = excluded.payload_json",
                    (*values, json.dumps(payload, ensure_ascii=False)),
                )
            self._conn.commit()

    def asset_event_stats(self) -> dict:
        """events を **1度だけ** 舐めて、素材画面が使う集計をまとめて作る。

        返すのは3種:

          ``gift``   {gift_id: {"name", "sends", "coins"}}
          ``emote``  {配信者: {emote_id: 使われた回数}}
          ``avatar`` {配信者: {identity_key: 出現回数}}

        **1度で済ませるのが要点。** 3つはGROUP BYの鍵が違う(gift_id / 配信者×emote_id /
        配信者×人)ので、SQLに任せると走査が3回になる。実測(events 1,256,138行)では
        SQLで別々に引くと 141ms + 462ms + 2,223ms = 2.8秒、必要な列だけを1度読んで
        Python側で畳むと1.8秒だった。3つとも走査のときにしか作らない値なので、
        まとめて採る方に寄せている。

        ``avatar`` の鍵が ``identity_key`` なのは、頻度表の1行が指すのが「素材」ではなく
        「人」だからである(一覧はusers表と結合して引く)。poolのfile名はその人の
        ``sha1(unique_id or nickname)`` だが、それは行を描くときに引き直せばよく、ここで
        変換すると同じ鍵へ畳まれた別人の回数が混ざる。

        ``coins`` は1個あたりの単価(``diamonds / gift_count``)の**最小値**。同じgiftでも
        グローブのcritは単価の5倍で届くため(``glove_migration``)、最大を採ると素の値段
        ではなく会心の値段を名乗ることになる。実測では457件中456件で単価は一定、
        ぶれるのは1件だけだった。

        ``sends`` は ``gift_count`` の合計(=送られた個数)であって event数ではない。
        連打は1 eventに ``repeat_count`` 個まとまって届くので、event数で数えると100連打が
        1回になる。実測で ``gift_count`` がNULLの行は0件である。

        gift名は同じgift_idで**最後に観測した**ものを採る。人が探すのは「今その素材が何と
        呼ばれているか」であって、過去に最も多く流れた呼び名ではない(実測では457件すべてで
        名前は1つだけ、衝突は0件)。引けなかったgift_idは ``name`` が空になる —— それらしい
        代替名は作らない。
        """
        conn = self._read_connection()
        owners = {row["id"]: row["unique_id"]
                  for row in conn.execute("SELECT id, unique_id FROM sessions")}
        gift: dict = {}
        emote: dict = {}
        avatar: dict = {}
        for (session_id, kind, at, gift_id, gift_name, gift_count, diamonds,
             identity_key, emotes) in conn.execute(
                "SELECT session_id, kind, time, gift_id, gift_name, gift_count,"
                " diamonds, identity_key, emotes FROM events"):
            owner = owners.get(session_id)
            if owner is None:
                continue
            if identity_key and identity_key not in NON_IDENTITY_KEYS:
                seen = avatar.setdefault(owner, {})
                seen[identity_key] = seen.get(identity_key, 0) + 1
            if kind == "gift" and gift_id is not None:
                self._fold_gift(gift, int(gift_id), at, gift_name, gift_count, diamonds)
            elif emotes:
                self._fold_emotes(emote.setdefault(owner, {}), emotes)
        return {"gift": gift, "emote": emote, "avatar": avatar}

    @staticmethod
    def _fold_gift(gift: dict, gift_id: int, at, name, count, diamonds) -> None:
        row = gift.get(gift_id)
        if row is None:
            row = gift[gift_id] = {"name": "", "sends": 0, "coins": None, "_at": None}
        row["sends"] += int(count or 0)
        unit = (diamonds / count) if (diamonds is not None and count) else None
        if unit is not None and (row["coins"] is None or unit < row["coins"]):
            row["coins"] = unit
        name = (name or "").strip()
        if name and (row["_at"] is None or (at is not None and at >= row["_at"])):
            row["name"] = name
            row["_at"] = at

    @staticmethod
    def _fold_emotes(counts: dict, raw) -> None:
        """1件のcommentが運んだ絵文字を数える。

        ``events.emotes`` はJSONのlistをそのまま入れたTEXT列。壊れた行1つで走査全体を
        落とさないよう、読めない値は飛ばす(その絵文字の回数が数えられないだけで、
        他の集計は正しいままである)。"""
        try:
            items = json.loads(raw)
        except (TypeError, ValueError):
            return
        if not isinstance(items, list):
            return
        for item in items:
            emote_id = (item or {}).get("id") if isinstance(item, dict) else None
            if emote_id:
                counts[str(emote_id)] = counts.get(str(emote_id), 0) + 1

    def asset_avatar_freq_exists(self) -> bool:
        """出現回数の表に行が在るか。summaryが「集計済みか」を答えるのに使う。

        COUNTではなく1行の有無だけを見る —— 19万行を数える必要は無く、答えたい問いは
        「採ってあるか」だからである。snapshotのpayloadに持たせないのは、集計の実体が
        この表であり、payloadの印と表の中身がずれる余地を作らないためである。"""
        row = self._read_connection().execute(
            "SELECT 1 FROM asset_avatar_freq LIMIT 1").fetchone()
        return row is not None

    def save_asset_avatar_freq(self, rows: list) -> int:
        """配信者ごとの出現回数を全置換で保存する。``rows`` は ``(配信者, identity_key,
        回数)`` の並びで、``配信者=''`` が全配信者の合計である。

        走査のたびに丸ごと入れ替える。差分更新にしないのは、eventが消える経路(session
        削除)が在り、増分だけを足すと消えたぶんが永久に残るためである。実測93,621行の
        入れ替えで、1回の transaction に収める(途中で落ちた表を人が見る余地を作らない)。
        """
        with self._lock:
            self._conn.execute("DELETE FROM asset_avatar_freq")
            self._conn.executemany(
                "INSERT INTO asset_avatar_freq (streamer, identity_key, uses)"
                " VALUES (?, ?, ?)", rows)
            self._conn.commit()
        return len(rows)
