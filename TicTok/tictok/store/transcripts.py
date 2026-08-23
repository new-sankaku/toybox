"""文字起こし・横断検索index・見どころ(=切り出し候補)・一括文字起こしqueue。

境界の理由: 「録画の中身に対して人が付けた印」をまとめる。文字起こし(機械)・検索hit(機械)・
bookmark(人)は別tableだが、いずれもrecording_idと秒数を鍵にした同じ形で、
時間軸の扱い(media軸 / PTS軸)という共通の落とし穴を持つ。

見どころは印であると同時に**素材の候補**でもある(範囲を持つ行がmp4にできる)。以前は
切り出し候補を cut_list という別表に持って『昇格』で写していたが、写した先で値が変わる
という前提が実データで成立しておらず(21件中20件が完全一致)、行を増やすだけの操作に
なっていたので表ごと畳んだ。

lock契約: lock保持前提のmethodは無い。各methodが自分で self._lock を取る。
  search_scenes と search_hit_groups は _read_connection() 側を使う。
"""
import json
import time
from typing import NamedTuple, Optional

from tictok.search.normalize import MENTION_HEADS, index_fold, mark
from tictok.store._common import CUT_SAME_RANGE_TOLERANCE, logger


class _SceneQuery(NamedTuple):
    """search_scenesが流す2本のSQL。件数と1ページ分はWHEREを共有する。"""

    mode: str
    count_sql: str
    page_sql: str
    params: list


def _build_scene_query(parsed: dict, sources: list, unique_ids: list | None,
                       since: float | None, until: float | None,
                       order: str) -> _SceneQuery:
    """検索条件をSQLへ組み立てる。

    実行から切り離してあるのは、join順が反転していないことをEXPLAIN QUERY PLANで
    検査できるようにするため(理由は下のCROSS JOINの注記)。
    """
    where = ["h.source IN (%s)" % ",".join("?" * len(sources))]
    params: list = list(sources)
    if unique_ids:
        where.append("h.unique_id IN (%s)" % ",".join("?" * len(unique_ids)))
        params.extend(unique_ids)
    if since is not None:
        where.append("h.started_at >= ?")
        params.append(since)
    if until is not None:
        where.append("h.started_at <= ?")
        params.append(until)

    # 短い語(trigramでindexできない2文字以下)はLIKEで後段濾過する。MATCHと併用する
    # 限り走査対象はMATCHの結果に限られるので、全表LIKEにはならない。照合先は原文では
    # なく畳んだ本文(body_norm) — patternも畳んであるので、「ウザ」で「うざ」が当たる。
    for pattern in parsed["like_all"]:
        where.append("h.body_norm LIKE ? ESCAPE '\\'")
        params.append(pattern)
    for pattern in parsed["like_none"]:
        where.append("h.body_norm NOT LIKE ? ESCAPE '\\'")
        params.append(pattern)

    columns = ("h.id, h.source, h.recording_id, h.session_id, h.unique_id,"
               " h.started_at, h.video_time, h.end_time, h.nickname, h.body")
    if parsed["match"]:
        mode = "fts"
        # join順はCROSS JOINで固定する。素のJOINだと、unique_idやsourceの等値条件が
        # 付いた瞬間にplannerがidx_search_hits_uidを選び、search_hits側を外側に回して
        # 1行ごとにFTS照合する経路へ倒れる(実測: 配信者を選んだ検索が35ms -> 56秒)。
        # MATCHはFTS側を外側に置かない限り安くならないので、順序は固定でよい。
        base = ("FROM search_fts f CROSS JOIN search_hits h ON h.id = f.rowid"
                " WHERE search_fts MATCH ? AND " + " AND ".join(where))
        params = [parsed["match"]] + params
        order_sql = ("ORDER BY bm25(search_fts)" if order == "rank"
                     else "ORDER BY h.started_at DESC, h.video_time")
    else:
        # 肯定語が全て2文字以下。indexが使えないので全表走査に落ちる。
        mode = "like"
        base = "FROM search_hits h WHERE " + " AND ".join(where)
        order_sql = "ORDER BY h.started_at DESC, h.video_time"

    return _SceneQuery(
        mode=mode,
        count_sql="SELECT COUNT(*) AS n " + base,
        page_sql=("SELECT " + columns + " " + base + " " + order_sql
                  + " LIMIT ? OFFSET ?"),
        params=params,
    )


class TranscriptsMixin:
    """文字起こし・横断検索index・切り出し候補・見どころ・一括文字起こしqueue。

    lockもDB接続も持たない。すべて Storage が所有する self._conn /
    self._lock / _read_connection() を借りる(mixinとして Storage に混ぜられる前提)。
    契約の詳細はmodule docstringを参照。
    """

    def get_transcript(self, recording_id: int, raw: bool = False) -> Optional[dict]:
        """文字起こし。既定では**訂正を重ねて**返す。

        字幕の書き出し(srt/vtt/ass)・切り抜き字幕・焼き込み・検索index・章立ては、いずれも
        ここを通って本文を得る。重ねる場所をここに1つ置くことで、訂正が全部の出口へ同時に
        効く(逆に、ここを迂回する経路を足すとその出口だけ直っていない文字が出る)。

        ``raw=True`` は生のまま。文字起こしそのものを比べたい経路(再文字起こしの照合・
        訂正画面の原文表示)だけが使う。
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT recording_id, language, model, text, segments_json, duration,"
                " created_at, timemap_version, timemap_anchors, timemap_drift_seconds,"
                " word_times"
                " FROM transcripts WHERE recording_id = ?",
                (recording_id,),
            ).fetchone()
            corrections = ([] if raw or row is None
                           else self._corrections_locked(recording_id, ("active",)))
        if row is None:
            return None
        item = dict(row)
        item["segments"] = json.loads(item.pop("segments_json"))
        if not corrections:
            item["corrections_applied"] = 0
            return item

        from tictok.record.corrections import apply_to_segments

        applied = apply_to_segments(item["segments"], corrections)
        item["segments"] = applied["segments"]
        # 本文も差し替える。textはsegmentのtextの連結そのもの(実測: 31,443文字で完全一致)
        # なので、ここを直さないと検索と章立てだけが訂正前の文字を見続ける。
        item["text"] = "".join(seg.get("text") or "" for seg in item["segments"])
        item["corrections_applied"] = applied["applied"]
        if applied["orphans"]:
            # 重ねる側で当たらなかった = DBのstateとsegmentが食い違っている。数だけ残す
            # (直し方は再文字起こし時の貼り直しか、画面からの手当て)。
            logger.warning(
                "訂正 %d 件が現在のsegmentに当たりません: recording_id=%d",
                len(applied["orphans"]), recording_id,
                extra={"event": "transcript.corrections_unmatched",
                       "ctx": {"recording_id": recording_id,
                               "unmatched": len(applied["orphans"])}},
            )
        return item

    def save_transcript(self, recording_id: int, result: dict,
                        corrections: str = "keep") -> None:
        word_times = any(seg.get("words") for seg in result.get("segments", []))
        with self._lock:
            self._conn.execute(
                "INSERT INTO transcripts (recording_id, language, model, text, segments_json,"
                " duration, created_at, timemap_version, timemap_anchors, timemap_drift_seconds,"
                " word_times)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(recording_id) DO UPDATE SET"
                " language = excluded.language, model = excluded.model, text = excluded.text,"
                " segments_json = excluded.segments_json, duration = excluded.duration,"
                " created_at = excluded.created_at, timemap_version = excluded.timemap_version,"
                " timemap_anchors = excluded.timemap_anchors,"
                " timemap_drift_seconds = excluded.timemap_drift_seconds,"
                " word_times = excluded.word_times",
                (
                    recording_id,
                    result.get("language"),
                    result.get("model"),
                    result.get("text", ""),
                    json.dumps(result.get("segments", []), ensure_ascii=False),
                    result.get("duration"),
                    time.time(),
                    result.get("timemap_version"),
                    result.get("timemap_anchors"),
                    result.get("timemap_drift_seconds"),
                    1 if word_times else 0,
                ),
            )
            # 訂正の引き継ぎは同じlock区間で決める。別のAPIに割ると、新しい本文と古い訂正が
            # 並んだ瞬間に読み出しが走り、当たらない訂正が保留として画面に出る。
            carried = self._carry_corrections_locked(
                recording_id, result.get("segments", []), corrections)
            self._conn.commit()
        logger.info(
            "文字起こしを保存しました: recording_id=%d", recording_id,
            extra={"event": "stt.transcript_saved",
                   "ctx": {"timemap_version": result.get("timemap_version"),
                           "timemap_anchors": result.get("timemap_anchors"),
                           "timemap_drift_seconds": result.get("timemap_drift_seconds"),
                           "word_times": bool(word_times),
                           "segments": len(result.get("segments", []))}},
        )
        if carried:
            logger.info(
                "文字起こしの訂正を%s: recording_id=%d 貼り直し=%d 保留=%d 破棄=%d",
                "引き継ぎました" if corrections == "keep" else "破棄しました",
                recording_id, carried["matched"], carried["orphaned"],
                carried["discarded"],
                extra={"event": "transcript.corrections_carried",
                       "ctx": {"recording_id": recording_id, **carried}},
            )

    # ===== 横断検索index =====

    def replace_search_hits(self, recording_id: int, source: str, rows: list) -> int:
        """1録画・1source分のindexを差し替える。external content FTSはcontent表を
        DELETEしただけでは索引が残るので、必ず先に'delete'commandで索引を抜く。"""
        # 表示名の読み出しは _read_connection() 側なので、self._lock を取る前に済ませる
        # (lockの入れ子は _lock -> _buf_lock の一方向しか存在しない)。宛先を持つ本文が
        # 1件も無いsource(文字起こし・笑い声)では引かない。
        names = (self.mention_names()
                 if any((row["body"] or "")[:1] in MENTION_HEADS for row in rows) else None)
        with self._lock:
            self._conn.execute(
                "INSERT INTO search_fts(search_fts, rowid, body_norm)"
                " SELECT 'delete', id, body_norm FROM search_hits"
                " WHERE recording_id = ? AND source = ?",
                (recording_id, source),
            )
            self._conn.execute(
                "DELETE FROM search_hits WHERE recording_id = ? AND source = ?",
                (recording_id, source),
            )
            for row in rows:
                # 索引するのは宛先を外して表記ゆれを畳んだ本文。原文(body)は画面に出す
                # ために残す。
                body_norm = index_fold(row["body"], names)
                cursor = self._conn.execute(
                    "INSERT INTO search_hits (source, recording_id, session_id, unique_id,"
                    " started_at, video_time, end_time, nickname, body, body_norm, score)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        source,
                        recording_id,
                        row.get("session_id"),
                        row["unique_id"],
                        row["started_at"],
                        row["video_time"],
                        row.get("end_time"),
                        row.get("nickname"),
                        row["body"],
                        body_norm,
                        row.get("score"),
                    ),
                )
                self._conn.execute(
                    "INSERT INTO search_fts(rowid, body_norm) VALUES (?, ?)",
                    (cursor.lastrowid, body_norm),
                )
            self._conn.commit()
        return len(rows)

    def search_indexed_counts(self) -> dict:
        """recording_idごとのindex済み件数(source別)。画面のbadge用。

        search_hitsの全走査(36万行のindex scanで20ms)なので集計read専用の接続で流す。
        書き込み接続で流すと、その間collectorのevent書き出しが同じlockで待たされる。
        search_hitsはeventのbufferを経由せず即commitされるので、read接続から見える。"""
        rows = self._read_connection().execute(
            "SELECT recording_id, source, COUNT(*) AS n FROM search_hits"
            " GROUP BY recording_id, source"
        ).fetchall()
        out: dict = {}
        for row in rows:
            out.setdefault(row["recording_id"], {})[row["source"]] = row["n"]
        return out

    def laugh_totals_by_recording(self) -> dict:
        """recording_id -> {"seconds": 笑い声の合計秒, "windows": 窓の数}。

        録画一覧を笑い声の多い順で並べるための集計。合計秒を持つのは、窓の数だけでは
        「短い笑いが多い録画」と「長く笑っている録画」が同じ顔で並ぶため。

        値の出所はindexの行そのものなので、共演中を外して張り直せばこの合計も一緒に
        減る(除外した秒が並び順に残らない)。search_indexed_countsと同じ理由で集計
        read専用の接続を使う。"""
        from tictok.search.indexer import SOURCE_LAUGH

        rows = self._read_connection().execute(
            "SELECT recording_id, COUNT(*) AS n,"
            " SUM(COALESCE(end_time, video_time) - video_time) AS seconds"
            " FROM search_hits WHERE source = ? GROUP BY recording_id",
            (SOURCE_LAUGH,),
        ).fetchall()
        return {row["recording_id"]: {"seconds": round(row["seconds"] or 0.0, 2),
                                      "windows": row["n"]}
                for row in rows}

    def search_scenes(self, query: str, sources: list, unique_ids: list | None = None,
                      since: float | None = None, until: float | None = None,
                      order: str = "time", limit: int = 200, offset: int = 0) -> dict:
        """文字起こしsegmentとcommentを横断して部分一致検索する。

        trigram tokenizerは3文字未満のtokenを作らないため、1-2文字のqueryはMATCHでは
        引けない。その場合だけbodyのLIKE走査へ落とす(件数が伸びるとFTSより遅いので、
        利用側は3文字以上を促すこと)。"""
        from tictok.search.query import QueryError, parse as parse_query

        if not sources:
            return {"total": 0, "items": [], "mode": "none", "hint": ""}
        try:
            parsed = parse_query(query)
        except QueryError as exc:
            return {"total": 0, "items": [], "mode": "none", "hint": str(exc)}

        built = _build_scene_query(parsed, sources, unique_ids, since, until, order)
        # 集計read専用の接続で流す。writer接続で流すと、検索している間ずっとcollectorの
        # event書き出しが同じlockで待たされる(この検索は50万行のFTSを舐める)。
        # search_hitsはeventのbufferを経由せず即commitされるので、read接続から見える。
        reader = self._read_connection()
        total = reader.execute(built.count_sql, built.params).fetchone()["n"]
        rows = reader.execute(built.page_sql, built.params + [limit, offset]).fetchall()
        # 一致箇所の囲みはここで付ける。FTSのhighlight()が返すのは索引している列
        # (=畳んだ本文)なので、そのまま出すと画面の文字が「うざい」から「ウザイ」へ化ける。
        # 畳み込みは文字数を保つので、畳んだ形で見つけた位置を原文へそのまま当てられる。
        items = []
        for row in rows:
            item = dict(row)
            item["snippet"] = mark(item["body"], parsed["terms"])
            items.append(item)
        return {"total": total, "mode": built.mode, "hint": "",
                "terms": parsed["terms"], "items": items}

    def laugh_scenes(self, unique_ids: list | None = None, order: str = "time",
                     limit: int = 200, offset: int = 0) -> dict:
        """笑い声の窓を語で絞らずに列挙する。行の形は search_scenes と同じ。

        検索と別のmethodなのは、この行が**語を持たない**ため。音そのものが根拠なので
        本文に当たる語が無く、語での検索へ混ぜると「笑い声」と打った時だけ出る隠しmodeに
        なる(実際そうなっていた)。ここは語を受け取らず、代わりに強さ・長さで並べ替える。

        ``order`` は 'time'(配信が新しい順) / 'strength'(強い順) / 'length'(長い順)。
        強さがNULLの行(score列より前に入れた笑い声)はDESCの末尾へ落ちる — 値を持たない
        行を先頭に置くと、一覧の頭が「強さの分からない行」で埋まる。
        """
        # source名の出所はindexer。ここで文字列を書くと、indexerが名前を変えたときに
        # 一覧だけが黙って0件になる。import は method 内(indexerはffmpeg周りを引き込む
        # ので、store の import 時に連れてくると循環する) — search_scenes と同じ作法。
        from tictok.search.indexer import SOURCE_LAUGH

        where = ["h.source = ?"]
        params: list = [SOURCE_LAUGH]
        if unique_ids:
            where.append("h.unique_id IN (%s)" % ",".join("?" * len(unique_ids)))
            params.extend(unique_ids)
        # 同順位の中は常に「新しい配信の頭から」。tie-breakを置かないと、同じ強さの行が
        # pageをまたぐたび入れ替わり、「さらに読み込む」で同じ窓が二度出る。
        tail = "h.started_at DESC, h.video_time"
        order_sql = {
            "strength": f"ORDER BY h.score DESC, {tail}",
            "length": f"ORDER BY (h.end_time - h.video_time) DESC, {tail}",
        }.get(order, f"ORDER BY {tail}")
        base = "FROM search_hits h WHERE " + " AND ".join(where)
        # scoreは並べ替えの根拠であって、行に載せる値ではない。画面の種別欄でscoreを出す枠は
        # 意味検索の類似度が使っており、同じ枠へ強さを流すと同じ数字が本文と2箇所に出る。
        columns = ("h.id, h.source, h.recording_id, h.session_id, h.unique_id,"
                   " h.started_at, h.video_time, h.end_time, h.nickname, h.body")
        # 検索と同じく集計read専用の接続で流す(writer接続を塞ぐと録画中のevent書き出しが待つ)。
        reader = self._read_connection()
        total = reader.execute("SELECT COUNT(*) AS n " + base, params).fetchone()["n"]
        rows = reader.execute(
            f"SELECT {columns} {base} {order_sql} LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        # 語で当てていないので囲む場所が無い。画面は検索hitと同じ列を描くため、原文を
        # そのままsnippetとして渡す。
        items = []
        for row in rows:
            item = dict(row)
            item["snippet"] = item["body"]
            items.append(item)
        return {"total": total, "mode": "laugh", "hint": "", "terms": [], "items": items}

    def search_hits_for(self, recording_id: int, source: str) -> list:
        """1録画・1source分のindex行を時間順で返す。意味検索がpassageへ束ねる際に使う。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, source, recording_id, session_id, unique_id, started_at,"
                " video_time, end_time, nickname, body FROM search_hits"
                " WHERE recording_id = ? AND source = ?"
                " ORDER BY video_time, id",
                (recording_id, source),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_hit(self, hit_id: int) -> Optional[dict]:
        """id指定で1行返す。意味検索が返すidを画面表示用の行へ引き当てるのに使う。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT id, source, recording_id, session_id, unique_id, started_at,"
                " video_time, end_time, nickname, body FROM search_hits WHERE id = ?",
                (hit_id,),
            ).fetchone()
        return dict(row) if row else None

    def search_hit_times(self, hit_ids: list) -> dict:
        """id -> {video_time, end_time} を引く。意味検索が位置を都度解決するのに使う。

        意味検索は本文とvectorを自前のindexへ持つが、**秒だけはここから引き直す**。
        index側にも構築時の秒が入っているものの、文字起こしのやり直しや時間軸の張り直しで
        search_hits側だけが動くと、意味検索だけが古い軸を名乗り続けるため
        (実測: 134 group / 最大約20分のズレ)。存在しないidは戻り値に現れない — 呼び出し側は
        「indexが指す行はもう無い」= その結果を出せない、として扱うこと。

        集計read専用の接続で流す(search_hitsはbufferを経由せず即commitされる)。"""
        out: dict = {}
        if not hit_ids:
            return out
        reader = self._read_connection()
        # SQLiteの変数上限(既定999)に触れないよう分割する。意味検索は1回で数百idを引く。
        for start in range(0, len(hit_ids), 500):
            chunk = [int(h) for h in hit_ids[start : start + 500]]
            rows = reader.execute(
                "SELECT id, video_time, end_time FROM search_hits WHERE id IN (%s)"
                % ",".join("?" * len(chunk)),
                chunk,
            ).fetchall()
            for row in rows:
                out[row["id"]] = {"video_time": row["video_time"],
                                  "end_time": row["end_time"]}
        return out

    def search_hit_groups(self) -> list:
        """(recording_id, source)ごとの件数と最大id。意味検索の差分build判定に使う。

        search_indexed_countsと同じ理由で集計read専用の接続を使う(34ms)。"""
        rows = self._read_connection().execute(
            "SELECT recording_id, source, COUNT(*) AS n, MAX(id) AS max_id"
            " FROM search_hits GROUP BY recording_id, source"
        ).fetchall()
        return [dict(row) for row in rows]

    # ===== 切り抜きグループ(clip group) =====
    # 見どころ(bookmarks)を「切り抜き動画1本のグループ」単位で束ねる。所属は排他
    # (group_id 1つ)で、グループ間の共用は行の複製で表す: グループごとにIN/OUTの詰め方が
    # 変わるため、所属を共有すると片方の調整が他方のグループを黙って壊す。

    def list_groups(self) -> list:
        """グループ一覧。件数・合計尺を併記する(選ぶ根拠が「素材が何分あるか」のため)。
        並びはpositionの昇順(人が棚を並べ替えた順)で、未採番は作成順で後ろへ置く。

        件数は2つ出す。``item_count`` は所属する見どころの全件で、``ranged_count`` は
        そのうち範囲を持つ(=mp4にできる)件数である。合計尺は範囲付きだけの和なので、
        件数を1つしか出さないと「10件あるのに0秒」という読めない組み合わせが出る。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT g.id, g.name, g.memo, g.position, g.created_at,"
                " (SELECT COUNT(*) FROM bookmarks b WHERE b.group_id = g.id)"
                "   AS item_count,"
                " (SELECT COUNT(*) FROM bookmarks b"
                "   WHERE b.group_id = g.id AND b.end IS NOT NULL) AS ranged_count,"
                " (SELECT COALESCE(SUM(b.end - b.start), 0) FROM bookmarks b"
                "   WHERE b.group_id = g.id AND b.end IS NOT NULL) AS ranged_seconds"
                " FROM clip_groups g"
                " ORDER BY (g.position IS NULL), g.position, g.created_at, g.id"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_group(self, group_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM clip_groups WHERE id = ?", (group_id,)).fetchone()
        return dict(row) if row else None

    def add_group(self, name: str, memo: str = "") -> dict:
        """グループを作る。同名が既にあればその行を返す(検索語からの1-click作成を冪等に
        する。同名が2つ並ぶと、追加先としてどちらを指しているか誰にも分からなくなる)。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM clip_groups WHERE name = ?", (name,)).fetchone()
            if row is not None:
                return dict(row)
            # 棚の末尾へ足す。採番せずに置くと、並べ替え済みの棚では新しいグループだけが
            # 「未採番=末尾」の塊へ入り、以後の並べ替えのたび位置が飛ぶ。
            position = self._conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM clip_groups").fetchone()[0]
            cursor = self._conn.execute(
                "INSERT INTO clip_groups (name, memo, position, created_at)"
                " VALUES (?, ?, ?, ?)",
                (name, memo, int(position), time.time()),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM clip_groups WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return dict(row)

    def update_group(self, group_id: int, name: Optional[str] = None,
                     memo: Optional[str] = None) -> Optional[dict]:
        with self._lock:
            if name is not None:
                self._conn.execute(
                    "UPDATE clip_groups SET name = ? WHERE id = ?", (name, group_id))
            if memo is not None:
                self._conn.execute(
                    "UPDATE clip_groups SET memo = ? WHERE id = ?", (memo, group_id))
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM clip_groups WHERE id = ?", (group_id,)).fetchone()
        return dict(row) if row else None

    def delete_group(self, group_id: int) -> bool:
        """グループを消す。中の見どころは消さず未分類へ戻す(範囲の指定はグループの解散より
        長生きする)。FK pragmaは有効化していないため、SET NULL相当は自前で行う。
        書き出し順(position)はグループの中でしか意味を持たないので一緒に落とす。"""
        with self._lock:
            self._conn.execute(
                "UPDATE bookmarks SET group_id = NULL, position = NULL WHERE group_id = ?",
                (group_id,))
            cursor = self._conn.execute(
                "DELETE FROM clip_groups WHERE id = ?", (group_id,))
            self._conn.commit()
        return cursor.rowcount > 0

    def reorder_groups(self, group_ids: list) -> int:
        """棚(グループ一覧)の表示順をgroup_idsの順へ振り直す。listへ無いグループは現状の
        相対順のまま後ろへ、存在しないidは黙って無視する。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM clip_groups"
                " ORDER BY (position IS NULL), position, created_at, id").fetchall()
            current = [row["id"] for row in rows]
            members = set(current)
            wanted = [int(g) for g in group_ids if int(g) in members]
            seen = set(wanted)
            ordered = wanted + [gid for gid in current if gid not in seen]
            for position, group_id in enumerate(ordered):
                self._conn.execute(
                    "UPDATE clip_groups SET position = ? WHERE id = ?", (position, group_id))
            self._conn.commit()
        return len(ordered)

    def merge_groups(self, source_id: int, target_id: int) -> dict:
        """source_idの中身をtarget_idへ全て移してsource_idを消す(統合)。

        相対順を保ったままtargetの末尾へ足す(書き出し順は移した先でも「Aの並びの後ろにB」に
        なる)。3回のAPIに割ると、途中で失敗したときに「中身は移ったが空のグループが残る」
        「一部だけ移った」という半端な状態が画面に出るため、1つのlock区間で行う。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM bookmarks WHERE group_id = ?"
                " ORDER BY (position IS NULL), position, start, id", (source_id,)).fetchall()
            next_position = self._next_group_position(target_id)
            for offset, row in enumerate(rows):
                self._conn.execute(
                    "UPDATE bookmarks SET group_id = ?, position = ? WHERE id = ?",
                    (target_id, next_position + offset, row["id"]))
            self._conn.execute("DELETE FROM clip_groups WHERE id = ?", (source_id,))
            self._conn.commit()
        return {"bookmarks": len(rows)}

    def _next_group_position(self, group_id: int) -> int:
        """グループ内の次のposition。lock保持前提。"""
        row = self._conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM bookmarks WHERE group_id = ?",
            (group_id,)).fetchone()
        return int(row[0])

    def _bookmarks_in_display_order(self, bookmark_ids: list) -> list:
        """指定idの行を表示順(position→start)で返す。lock保持前提。move/copyが移動先でも
        元の相対順を保つための並びで、id順にすると追加順へ勝手に並び替わる。"""
        placeholders = ",".join("?" * len(bookmark_ids))
        return self._conn.execute(
            f"SELECT * FROM bookmarks WHERE id IN ({placeholders})"
            " ORDER BY (position IS NULL), position, start, id",
            [int(b) for b in bookmark_ids]).fetchall()

    def set_bookmark_group(self, bookmark_ids: list, group_id: Optional[int]) -> int:
        """所属変更(move)。相対順を保ったまま移動先グループの末尾へ足す。Noneで未分類へ戻す
        (書き出し順はグループの中でしか意味を持たないので一緒に落とす)。"""
        if not bookmark_ids:
            return 0
        with self._lock:
            rows = self._bookmarks_in_display_order(bookmark_ids)
            if group_id is None:
                for row in rows:
                    self._conn.execute(
                        "UPDATE bookmarks SET group_id = NULL, position = NULL WHERE id = ?",
                        (row["id"],))
            else:
                next_position = self._next_group_position(group_id)
                for offset, row in enumerate(rows):
                    self._conn.execute(
                        "UPDATE bookmarks SET group_id = ?, position = ? WHERE id = ?",
                        (group_id, next_position + offset, row["id"]))
            self._conn.commit()
        return len(rows)

    def copy_bookmarks_to_group(self, bookmark_ids: list,
                                group_id: Optional[int]) -> int:
        """複製(copy)。グループごとに独立してIN/OUTを詰められるよう、所属の共有ではなく
        行ごと複製する。複製先の末尾へ相対順を保って足す。

        書き出しの記録(exported_at/exported_path)は写さない。あれは「この行を書き出した」
        という過去の事実で、今作った複製にはまだ何も起きていない。"""
        if not bookmark_ids:
            return 0
        with self._lock:
            rows = self._bookmarks_in_display_order(bookmark_ids)
            next_position = (self._next_group_position(group_id)
                             if group_id is not None else None)
            for offset, row in enumerate(rows):
                self._conn.execute(
                    "INSERT INTO bookmarks (recording_id, unique_id, start, end, memo,"
                    " source_hit_id, live_wall, pts_mapped, group_id, position, origin,"
                    " created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (row["recording_id"], row["unique_id"], row["start"], row["end"],
                     row["memo"], row["source_hit_id"], row["live_wall"],
                     row["pts_mapped"], group_id,
                     None if next_position is None else next_position + offset,
                     row["origin"], time.time()))
            self._conn.commit()
        return len(rows)

    def reorder_group_bookmarks(self, group_id: int, bookmark_ids: list) -> int:
        """グループ内の並びをbookmark_idsの順へ振り直す。この並びがmp4の書き出し順
        (=「1本に連結」「作品にする」の繋ぐ順)になる。listへ無い行(並行追加など)は現状の
        相対順のまま後ろへ、グループ外のidは黙って無視する(他グループのpositionを
        書き換えない)。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM bookmarks WHERE group_id = ?"
                " ORDER BY (position IS NULL), position, start, id", (group_id,)).fetchall()
            current = [row["id"] for row in rows]
            members = set(current)
            wanted = [int(b) for b in bookmark_ids if int(b) in members]
            ordered = wanted + [bid for bid in current if bid not in set(wanted)]
            for position, bookmark_id in enumerate(ordered):
                self._conn.execute(
                    "UPDATE bookmarks SET position = ? WHERE id = ?",
                    (position, bookmark_id))
            self._conn.commit()
        return len(ordered)

    # ===== 見どころ(bookmark) =====

    def _insert_bookmark_locked(self, recording_id: int, unique_id: str, start: float,
                                end: Optional[float], memo: str,
                                source_hit_id: Optional[int],
                                group_id: Optional[int], origin: str) -> dict:
        position = (self._next_group_position(group_id)
                    if group_id is not None else None)
        cursor = self._conn.execute(
            "INSERT INTO bookmarks"
            " (recording_id, unique_id, start, end, memo, source_hit_id, group_id,"
            "  position, origin, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (recording_id, unique_id, start, end, memo, source_hit_id, group_id,
             position, origin, time.time()),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT * FROM bookmarks WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return dict(row)

    def add_bookmark(self, recording_id: int, unique_id: str, start: float,
                     end: Optional[float] = None, memo: str = "",
                     source_hit_id: Optional[int] = None,
                     group_id: Optional[int] = None,
                     origin: str = "manual") -> dict:
        """見どころを1件足す。``end`` を持てば範囲(=mp4にできる素材)、無ければ点。"""
        with self._lock:
            return self._insert_bookmark_locked(
                recording_id, unique_id, start, end, memo, source_hit_id,
                group_id, origin)

    def _find_ranged_bookmark_locked(self, recording_id: int, start: float,
                                     end: float, tolerance: float) -> Optional[dict]:
        """同じ録画の同じ範囲を指す行。無ければ ``None``。lock保持前提。

        端が1 frame以下ずれた行も同じ場面として扱う。範囲は無音への吸着やframe境界で
        わずかに動くので、厳密一致だけを見ると同じ場面の行が何本も並ぶ。同じ範囲が複数
        在れば最も古い行を返す(書き戻し先を毎回同じ行に定めるため)。"""
        row = self._conn.execute(
            "SELECT * FROM bookmarks WHERE recording_id = ? AND end IS NOT NULL"
            " AND ABS(start - ?) <= ? AND ABS(end - ?) <= ?"
            " ORDER BY id LIMIT 1",
            (int(recording_id), float(start), float(tolerance),
             float(end), float(tolerance)),
        ).fetchone()
        return dict(row) if row is not None else None

    def add_bookmark_if_absent(self, recording_id: int, unique_id: str, start: float,
                               end: float, memo: str = "", origin: str = "auto",
                               tolerance: float = CUT_SAME_RANGE_TOLERANCE) -> dict:
        """同じ範囲の行が在ればそれを返し、無ければ作る(shortの自動生成の書き戻し先)。

        探すのと作るのを**同じlockの中で**行う。別々に呼ぶと、同じ録画へshortのjobが
        重なった時に双方が「無い」を見てから作り、同じ範囲の行が2本並ぶ。所属(group_id)を
        受け取らないのは、既に在る行の所属を機械が動かさないためである(人が決めた棚を
        書き戻しが勝手に変えない)。既に在る行の ``origin`` も動かさない ―― 人が付けた
        見どころと同じ範囲をshortが作ったからといって、その行は機械の物にならない。"""
        with self._lock:
            found = self._find_ranged_bookmark_locked(
                recording_id, start, end, tolerance)
            if found is not None:
                return found
            return self._insert_bookmark_locked(
                recording_id, unique_id, start, end, memo, None, None, origin)

    def add_live_bookmark(self, recording_id: int, unique_id: str, wall_time: float,
                          provisional_start: float, memo: str = "") -> dict:
        """配信を見ている最中に押された見どころ。

        押した瞬間に確定できるのはwall-clockだけで、mp4のPTS軸へはまだ載せられない
        (finalizeでtiming mapが書かれるまで対応が存在しない)。そこでwall-clockから出した
        暫定値をstartに入れ、pts_mapped=0で「まだPTS軸ではない」と明示する。確定は
        remap_live_bookmarks()が行う。

        provisional_startは録画開始からの経過秒。実測では最終的なPTSと数十〜数百秒ずれる
        (112分の録画で340秒)ので、確定値として扱ってはならない。"""
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO bookmarks"
                " (recording_id, unique_id, start, end, memo, source_hit_id,"
                "  live_wall, pts_mapped, created_at)"
                " VALUES (?, ?, ?, NULL, ?, NULL, ?, 0, ?)",
                (recording_id, unique_id, provisional_start, memo, wall_time, time.time()),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM bookmarks WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return dict(row)

    def list_unmapped_bookmarks(self, recording_id: int) -> list:
        """まだPTS軸へ載せていないlive見どころ(finalizeの再map対象)。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, start, live_wall FROM bookmarks"
                " WHERE recording_id = ? AND pts_mapped = 0 AND live_wall IS NOT NULL"
                " ORDER BY live_wall",
                (recording_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def apply_bookmark_pts(self, mapped: list) -> int:
        """再map結果を確定させる。mappedは [(bookmark_id, pts_start), ...]。

        再mapできなかった行はここへ渡さないこと。pts_mapped=0のまま残せば画面が暫定値だと
        言えるが、ここを通すと暫定値が確定値として固定されてしまう。"""
        if not mapped:
            return 0
        with self._lock:
            cursor = self._conn.executemany(
                "UPDATE bookmarks SET start = ?, pts_mapped = 1 WHERE id = ?",
                [(float(pts), int(bookmark_id)) for bookmark_id, pts in mapped],
            )
            self._conn.commit()
        return cursor.rowcount

    def list_bookmarks(self, recording_id: Optional[int] = None) -> list:
        """見どころ一覧。recording_id指定で1録画分(seek bar描画用)、無指定で全件(一覧tab用)。
        録画のpath/filename/開始時刻はどの配信のどこかを示すために結合する
        (pathは書き出しの入口でもある ―― 移動後の値は呼び出し側が解決する)。"""
        sql = ("SELECT b.*, r.path, r.filename, r.started_at AS recording_started_at"
               " FROM bookmarks b LEFT JOIN recordings r ON r.id = b.recording_id")
        params: tuple = ()
        if recording_id is not None:
            sql += " WHERE b.recording_id = ?"
            params = (recording_id,)
        sql += " ORDER BY r.started_at DESC, b.start"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def bookmarks_in_group(self, group_id: int) -> list:
        """グループ1件の見どころを**書き出し順**で返す。作品(work)が繋ぐ順そのもの。

        :meth:`list_bookmarks` の並び(配信の新しい順→位置)とは別物である。作品は時刻順とは
        限らない並びを人が決めるためのもので、``position`` がその意思そのものだからである。
        ``position`` がNULLの行は末尾へ回す(グループへ入れた時に採番されるので、通常は
        既存行の移行分だけがここへ来る)。

        点(``end IS NULL``)も返す。除くのは呼び出し側の仕事である ―― ここで黙って落とすと、
        画面が「グループに5件」と数えたものが4シーンで書き出され、消えた1件の理由が
        どこにも出ない。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT b.*, r.path, r.filename, r.started_at AS recording_started_at,"
                " r.session_id AS recording_session_id, r.ended_at AS recording_ended_at"
                " FROM bookmarks b LEFT JOIN recordings r ON r.id = b.recording_id"
                " WHERE b.group_id = ?"
                " ORDER BY (b.position IS NULL), b.position, b.start, b.id",
                (int(group_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_bookmark_exported(self, bookmark_id: int, path: str,
                               exported_at: Optional[float] = None) -> bool:
        """この見どころをmp4として書き出したことを記録する。

        記録するのは「いつ・どこへ書いたか」だけで、そのfileが今も在るかは持たない。出力先の
        掃除はDBを通らないので、在るかどうかを持てば必ず実態と食い違う。同じ範囲を出し直せば
        同じpathを上書きするので、値も上書きで足りる(履歴は持たない)。"""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE bookmarks SET exported_at = ?, exported_path = ? WHERE id = ?",
                (exported_at if exported_at is not None else time.time(), path,
                 bookmark_id))
            self._conn.commit()
        return cursor.rowcount > 0

    def clear_bookmarks(self, group_id: Optional[int] = None,
                        only_ungrouped: bool = False) -> int:
        """見どころの一括削除。group_id指定でそのグループの分だけ、only_ungroupedで未分類
        だけ。画面の「表示中をすべて削除」は表示中の絞り込みに従う(全てを消す操作ではない)。"""
        sql = "DELETE FROM bookmarks"
        params: tuple = ()
        if group_id is not None:
            sql += " WHERE group_id = ?"
            params = (group_id,)
        elif only_ungrouped:
            sql += " WHERE group_id IS NULL"
        with self._lock:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
        return cursor.rowcount

    def get_bookmark(self, bookmark_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM bookmarks WHERE id = ?", (bookmark_id,)).fetchone()
        return dict(row) if row else None

    def update_bookmark_range(self, bookmark_id: int, start: Optional[float] = None,
                              end: Optional[float] = None,
                              end_given: bool = False) -> Optional[dict]:
        """見どころの位置と範囲を直す。対象が無ければ None、値が不正なら ValueError。

        ``start=None`` は「触らない」。``end`` は ``end_given=True`` のときだけ書き換え、
        その値が None なら範囲を捨てて点へ戻す。点と範囲は同じ行の上を行き来する
        (配信中に押した点へ後から尺を与えるのが最も多い直し方である)ので、
        「範囲を消す」と「endに触らない」を呼び出し側が区別できる形にする。

        **pts_mapped=0の行は断る。** 配信中に押した見どころのstartはwall-clockから出した
        暫定値で、録画のfinalizeでmp4のPTS軸へ載せ直される(実測で数十〜数百秒動く)。
        ここで手を入れても再mapが上書きするうえ、手で入れたendだけが残れば
        start < end という前提も黙って崩れる。

        **書き出し済みの印は消さない。** 「いつ・どこへ書いたか」は過去の事実で、範囲を
        変えたことで無かったことにはならない(その出力fileは今も在る)。次に書き出せば
        新しいpathで上書きされる。
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM bookmarks WHERE id = ?", (bookmark_id,)).fetchone()
            if row is None:
                return None
            if not row["pts_mapped"]:
                raise ValueError(
                    "配信中に記録した見どころです。位置は録画の確定後に定まるので、"
                    "それまでは編集できません。")
            new_start = float(row["start"] if start is None else start)
            new_end = end if end_given else row["end"]
            if new_end is not None:
                new_end = float(new_end)
            if new_start < 0:
                raise ValueError("位置は0秒以降にしてください。")
            if new_end is not None and new_end <= new_start:
                raise ValueError("尺は0より長くしてください。")
            self._conn.execute(
                "UPDATE bookmarks SET start = ?, end = ? WHERE id = ?",
                (new_start, new_end, bookmark_id))
            self._conn.commit()
            updated = self._conn.execute(
                "SELECT * FROM bookmarks WHERE id = ?", (bookmark_id,)).fetchone()
        return dict(updated)

    def update_bookmark_memo(self, bookmark_id: int, memo: str) -> Optional[dict]:
        """メモを書き換える。メモは覚え書きであり、mp4を書き出すときのfile名でもある。

        表が2つに割れていた頃は、同じ言葉を見どころのメモと切り出しのラベルが別々に持ち、
        片方を直すともう片方が古い言葉のまま残った(直したはずのfile名が黙って戻る)。
        統合後は列が1つなので、揃える仕組みそのものが要らない。"""
        with self._lock:
            self._conn.execute(
                "UPDATE bookmarks SET memo = ? WHERE id = ?", (memo, bookmark_id))
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM bookmarks WHERE id = ?", (bookmark_id,)).fetchone()
        return dict(row) if row else None

    def delete_bookmark(self, bookmark_id: int) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
            self._conn.commit()
        return cursor.rowcount > 0

    def delete_bookmarks(self, bookmark_ids: list) -> int:
        """見どころの一括削除。1件ずつのDELETEをn回投げると、途中で失敗したときに
        どこまで消えたかが画面から分からなくなる。"""
        if not bookmark_ids:
            return 0
        with self._lock:
            placeholders = ",".join("?" * len(bookmark_ids))
            cursor = self._conn.execute(
                f"DELETE FROM bookmarks WHERE id IN ({placeholders})",
                [int(b) for b in bookmark_ids])
            self._conn.commit()
        return cursor.rowcount

    # ===== 一括文字起こしqueue =====

    def count_media_jobs_by_state(self, kind: str) -> dict:
        """その種別のstate別件数。画面が待ち行列の実状を数字で併記するための軽量query
        (一覧を取って数えると、表示しない全行をpollのたびに読むことになる)。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT state, COUNT(*) AS n FROM media_job_queue WHERE kind = ?"
                " GROUP BY state", (kind,),
            ).fetchall()
        return {row["state"]: row["n"] for row in rows}

    def untranscribed_recordings(self, unique_id: str | None = None) -> list:
        """文字起こしもqueue登録もされていない完了録画。配信者単位の一括投入に使う。

        「済み」の根拠はtranscriptsの存在であって、queueの行ではない。queueを見るのは
        待機/実行中を二重に積まないためだけで、終わった行(completed/failed等)は候補から
        外さない — 失敗した録画は積み直せるべきである。"""
        sql = ("SELECT r.id, r.unique_id, r.filename, r.path, r.started_at, r.ended_at"
               " FROM recordings r"
               " LEFT JOIN transcripts t ON t.recording_id = r.id"
               " LEFT JOIN media_job_queue q ON q.recording_id = r.id AND q.kind = 'stt'"
               "   AND q.state IN ('pending', 'running')"
               " WHERE r.status = 'completed' AND t.recording_id IS NULL"
               " AND q.recording_id IS NULL")
        params: list = []
        if unique_id:
            sql += " AND r.unique_id = ?"
            params.append(unique_id)
        sql += " ORDER BY r.started_at DESC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
