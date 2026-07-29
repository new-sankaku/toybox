"""文字起こし・横断検索index・切り出し候補・見どころ・一括転写queue。

境界の理由: 「録画の中身に対して人が付けた印」をまとめる。転写(機械)・検索hit(機械)・
cut/bookmark(人)は別tableだが、いずれもrecording_idと秒数を鍵にした同じ形で、
時間軸の扱い(media軸 / PTS軸)という共通の落とし穴を持つ。

lock契約: lock保持前提のmethodは無い。各methodが自分で self._lock を取る。
  search_scenes と search_hit_groups は _read_connection() 側(self._read_lock)を使う。
"""
import json
import time
from typing import Optional

from tictok.store._common import logger


class TranscriptsMixin:
    """文字起こし・横断検索index・切り出し候補・見どころ・一括転写queue。

    lockもDB接続も持たない。すべて Storage が所有する self._conn /
    self._lock / self._read_lock を借りる(mixinとして Storage に混ぜられる前提)。
    契約の詳細はmodule docstringを参照。
    """

    def get_transcript(self, recording_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT recording_id, language, model, text, segments_json, duration,"
                " created_at, timemap_version, timemap_anchors, timemap_drift_seconds"
                " FROM transcripts WHERE recording_id = ?",
                (recording_id,),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["segments"] = json.loads(item.pop("segments_json"))
        return item

    def save_transcript(self, recording_id: int, result: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO transcripts (recording_id, language, model, text, segments_json,"
                " duration, created_at, timemap_version, timemap_anchors, timemap_drift_seconds)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(recording_id) DO UPDATE SET"
                " language = excluded.language, model = excluded.model, text = excluded.text,"
                " segments_json = excluded.segments_json, duration = excluded.duration,"
                " created_at = excluded.created_at, timemap_version = excluded.timemap_version,"
                " timemap_anchors = excluded.timemap_anchors,"
                " timemap_drift_seconds = excluded.timemap_drift_seconds",
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
                ),
            )
            self._conn.commit()
        logger.info(
            "転写を保存しました: recording_id=%d", recording_id,
            extra={"event": "stt.transcript_saved",
                   "ctx": {"timemap_version": result.get("timemap_version"),
                           "timemap_anchors": result.get("timemap_anchors"),
                           "timemap_drift_seconds": result.get("timemap_drift_seconds"),
                           "segments": len(result.get("segments", []))}},
        )

    # ===== 横断検索index =====

    def replace_search_hits(self, recording_id: int, source: str, rows: list) -> int:
        """1録画・1source分のindexを差し替える。external content FTSはcontent表を
        DELETEしただけでは索引が残るので、必ず先に'delete'commandで索引を抜く。"""
        with self._lock:
            self._conn.execute(
                "INSERT INTO search_fts(search_fts, rowid, body)"
                " SELECT 'delete', id, body FROM search_hits"
                " WHERE recording_id = ? AND source = ?",
                (recording_id, source),
            )
            self._conn.execute(
                "DELETE FROM search_hits WHERE recording_id = ? AND source = ?",
                (recording_id, source),
            )
            for row in rows:
                cursor = self._conn.execute(
                    "INSERT INTO search_hits (source, recording_id, session_id, unique_id,"
                    " started_at, video_time, end_time, nickname, body)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    ),
                )
                self._conn.execute(
                    "INSERT INTO search_fts(rowid, body) VALUES (?, ?)",
                    (cursor.lastrowid, row["body"]),
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

    def search_scenes(self, query: str, sources: list, unique_ids: list | None = None,
                      since: float | None = None, until: float | None = None,
                      order: str = "time", limit: int = 200, offset: int = 0) -> dict:
        """転写segmentとcommentを横断して部分一致検索する。

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
        # 限り走査対象はMATCHの結果に限られるので、全表LIKEにはならない。
        for pattern in parsed["like_all"]:
            where.append("h.body LIKE ? ESCAPE '\\'")
            params.append(pattern)
        for pattern in parsed["like_none"]:
            where.append("h.body NOT LIKE ? ESCAPE '\\'")
            params.append(pattern)

        if parsed["match"]:
            mode = "fts"
            base = ("FROM search_fts f JOIN search_hits h ON h.id = f.rowid"
                    " WHERE search_fts MATCH ? AND " + " AND ".join(where))
            params = [parsed["match"]] + params
            # snippet()の最終引数はtoken数だが、trigramでは1 token≒1文字(3文字窓を1文字ずつ
            # 作る)なので、語数のつもりの値を渡すとその文字数で切れる。1行=1コメント/1発話で
            # 元々短く、切る必要が無いのでhighlight()で全文を返す(LIKE経路とも表示が揃う)。
            select_extra = ", highlight(search_fts, 0, '\x02', '\x03') AS snippet"
            order_sql = ("ORDER BY bm25(search_fts)" if order == "rank"
                         else "ORDER BY h.started_at DESC, h.video_time")
        else:
            # 肯定語が全て2文字以下。indexが使えないので全表走査に落ちる。
            mode = "like"
            base = "FROM search_hits h WHERE " + " AND ".join(where)
            select_extra = ", h.body AS snippet"
            order_sql = "ORDER BY h.started_at DESC, h.video_time"

        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) AS n " + base, params).fetchone()["n"]
            rows = self._conn.execute(
                "SELECT h.id, h.source, h.recording_id, h.session_id, h.unique_id,"
                " h.started_at, h.video_time, h.end_time, h.nickname, h.body"
                + select_extra + " " + base + " " + order_sql + " LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
        return {"total": total, "mode": mode, "hint": "", "terms": parsed["terms"],
                "items": [dict(row) for row in rows]}

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

    def search_hit_groups(self) -> list:
        """(recording_id, source)ごとの件数と最大id。意味検索の差分build判定に使う。

        search_indexed_countsと同じ理由で集計read専用の接続を使う(34ms)。"""
        rows = self._read_connection().execute(
            "SELECT recording_id, source, COUNT(*) AS n, MAX(id) AS max_id"
            " FROM search_hits GROUP BY recording_id, source"
        ).fetchall()
        return [dict(row) for row in rows]

    # ===== 切り出し候補(cut list) =====

    def add_cut(self, recording_id: int, unique_id: str, start: float, end: float,
                label: str = "") -> dict:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO cut_list (recording_id, unique_id, start, end, label, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (recording_id, unique_id, start, end, label, time.time()),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM cut_list WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return dict(row)

    def list_cuts(self) -> list:
        """cut listをNLEへ渡せる形で返す。pathはrecordingsから引く(移動後の値は
        呼び出し側が解決する)。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT c.*, r.path, r.filename, r.started_at AS recording_started_at"
                " FROM cut_list c LEFT JOIN recordings r ON r.id = c.recording_id"
                " ORDER BY c.unique_id, r.started_at, c.start"
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_cut(self, cut_id: int) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM cut_list WHERE id = ?", (cut_id,))
            self._conn.commit()
        return cursor.rowcount > 0

    def clear_cuts(self) -> int:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM cut_list")
            self._conn.commit()
        return cursor.rowcount

    # ===== 見どころ(bookmark) =====

    def add_bookmark(self, recording_id: int, unique_id: str, start: float,
                     end: Optional[float] = None, memo: str = "",
                     source_hit_id: Optional[int] = None) -> dict:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO bookmarks"
                " (recording_id, unique_id, start, end, memo, source_hit_id, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (recording_id, unique_id, start, end, memo, source_hit_id, time.time()),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM bookmarks WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return dict(row)

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
        録画のfilename/開始時刻はどの配信のどこかを示すために結合する。"""
        sql = ("SELECT b.*, r.filename, r.started_at AS recording_started_at"
               " FROM bookmarks b LEFT JOIN recordings r ON r.id = b.recording_id")
        params: tuple = ()
        if recording_id is not None:
            sql += " WHERE b.recording_id = ?"
            params = (recording_id,)
        sql += " ORDER BY r.started_at DESC, b.start"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def update_bookmark_memo(self, bookmark_id: int, memo: str) -> Optional[dict]:
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

    # ===== 一括転写queue =====

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
