"""録画row(recordings表)と、容量・退避の観測。

境界の理由: 録画fileの身元(path/size/状態遷移)を持つ単一tableのCRUD。容量sample・
storage scanを同居させるのは、どちらも「録画が何バイト載っているか」を測るもので、
recordingsのsizeと同じ数字を別の粒度で見ているだけだからである。

lock契約: lock保持前提のmethodは無い。各methodが自分で self._lock を取る。
"""
import json
import time
from pathlib import Path
from typing import Optional

from tictok.store._common import RECORDING_REVIEW_STATES


class RecordingsMixin:
    """録画row(recordings表)と、容量・退避の観測。

    lockもDB接続も持たない。すべて Storage が所有する self._conn /
    self._lock / self._read_lock を借りる(mixinとして Storage に混ぜられる前提)。
    契約の詳細はmodule docstringを参照。
    """

    def create_recording(self, session_id, unique_id, path, filename, quality, started_at) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO recordings (session_id, unique_id, path, filename, quality, status, started_at)"
                " VALUES (?, ?, ?, ?, ?, 'recording', ?)",
                (session_id, unique_id, path, filename, quality, started_at),
            )
            self._conn.commit()
            return cursor.lastrowid

    def update_recording(self, recording_id, status, path, filename, ended_at, size,
                         error=None, duration_seconds=None) -> None:
        """live captureが終わった録画を確定させる。ended_atは捕捉が終わった時刻そのもの。

        duration_secondsは測れたときだけ渡す。測れなかった(ffprobeが無い等)場合に既存の
        実測値を消さないよう、Noneは「据え置き」であって「不明で上書き」ではない。"""
        with self._lock:
            self._conn.execute(
                "UPDATE recordings SET status = ?, path = ?, filename = ?, ended_at = ?, bytes = ?,"
                " error = ?, duration_seconds = COALESCE(?, duration_seconds)"
                " WHERE id = ?",
                (status, path, filename, ended_at, size, error, duration_seconds, recording_id),
            )
            self._conn.commit()

    def update_rebuilt_recording(self, recording_id, status, path, filename, size,
                                 error=None, duration_seconds=None,
                                 ended_at_if_missing=None) -> None:
        """既存録画を素材(.ts)から作り直した/拾い直した結果を書き戻す。

        **ended_atを現在時刻で上書きしてはならない**。作り直しは中身を作り直すだけで、
        捕捉が終わった時刻を変えない。update_recordingを流用していたため、起動時の復旧と
        再mp4化が実行時刻をended_atへ書き込み、DBの尺が「録画開始〜再処理時刻」に化けて
        いた(実測: 3時間の録画が177時間、同じbatchで処理した行は同一のended_atになるため
        古い行ほど尺が伸び、一覧では下へ行くほど増える見え方になる)。ended_atはrecording
        窓としてeventの絞り込みと焼き込みの時刻mapにも使われるので、被害は表示に留まらない。

        ended_at_if_missingは、そもそもended_atを持たない行(中断のまま終わった録画)を
        埋めるためだけの値。既にended_atがある行には触れない。"""
        with self._lock:
            self._conn.execute(
                "UPDATE recordings SET status = ?, path = ?, filename = ?, bytes = ?, error = ?,"
                " ended_at = COALESCE(ended_at, ?),"
                " duration_seconds = COALESCE(?, duration_seconds)"
                " WHERE id = ?",
                (status, path, filename, size, error, ended_at_if_missing,
                 duration_seconds, recording_id),
            )
            self._conn.commit()

    def set_recording_duration(self, recording_id: int, seconds: float) -> bool:
        """実測した尺だけを書き戻す。是正scriptと、中身を作り直さずに尺だけ確定させる
        経路が使う。0以下は測定失敗なので受け付けない(尺0の録画は存在しない)。"""
        if not seconds or seconds <= 0:
            return False
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE recordings SET duration_seconds = ? WHERE id = ?", (seconds, recording_id))
            self._conn.commit()
        return cursor.rowcount > 0

    def list_recordings(self, limit: int) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM recordings ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def recordings_for_session(self, session_id: int) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM recordings WHERE session_id = ? ORDER BY started_at", (session_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def recordings_for_user(self, unique_id: str) -> list:
        """配信者1人ぶんの全録画。容量整理の画面が対象を並べるための入力で、statusは
        絞らない(中断・失敗した録画こそHLSが残って容量を食っているため)。新しい順。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM recordings WHERE unique_id = ? ORDER BY started_at DESC",
                (unique_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_recording(self, recording_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_recording_for_read(self, recording_id: int) -> Optional[dict]:
        """読むだけの経路のための1件取得。集計read専用の接続を使う。

        HLS segmentの配信は再生中ずっと毎秒叩かれる(実測で4.2時間に886 request)。writer接続で
        引くとcollectorのevent書き出しと同じlockを取り合い、そのlock待ちがrouteの所要時間の
        40%(最悪1本で9.4秒)を占めていた。recordingsの書き込みはどれも即commitなので、
        read接続からも最新の行が見える。

        read接続は重い集計と直列化される点だけ引き換えになるが、収集中は常時書き込みが続く
        writer側と違い、集計は人が操作したときにしか走らない。"""
        row = self._read_connection().execute(
            "SELECT * FROM recordings WHERE id = ?", (recording_id,)
        ).fetchone()
        return dict(row) if row else None

    def next_recording_start(self, session_id: int, after: float) -> Optional[float]:
        """同じsessionで``after``より後に始まった録画のうち、最も早い開始時刻。無ければNone。

        ended_atを持たない録画(crashで中断した行・確定の途中で落ちた行)のevent窓を閉じる
        ために使う。開いたままにすると、その録画のcommentとして後続の録画ぶんまで取り込む。
        自分自身を含めないよう厳密に ``>`` で切る(同一時刻に2本は始まらない)。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT MIN(started_at) AS next_start FROM recordings"
                " WHERE session_id = ? AND started_at > ?",
                (session_id, after),
            ).fetchone()
        return row["next_start"] if row and row["next_start"] is not None else None

    def recordings_brief(self) -> list:
        """Lightweight per-recording info for list-level done badges: each finished
        recording's session, path (to test for a burned-in output file) and whether a
        transcript exists. One query so the session list can aggregate cheaply."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT r.id, r.session_id, r.path,"
                " (t.recording_id IS NOT NULL) AS has_transcript"
                " FROM recordings r LEFT JOIN transcripts t ON t.recording_id = r.id"
                " WHERE r.status IN ('completed', 'interrupted')"
            ).fetchall()
        return [dict(row) for row in rows]

    def recordings_by_stem(self) -> dict:
        """file名のstem -> 録画の身元(id / 配信者 / 開始時刻)。

        切り出し成果物はDBに行を持たず、file名のstemだけが録画への手掛かりになる。一覧を
        出すたびにfile1本ごと ``get_recording`` を引くと件数ぶんqueryが飛ぶので、1回の走査で
        引き当てられるようにここで畳む。stemはfilenameを優先する(中断録画のpathはmp4では
        なくrecord dirを指すことがある — files._recording_stemと同じ理由)。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, unique_id, filename, path, started_at FROM recordings"
            ).fetchall()
        found: dict = {}
        for row in rows:
            raw = row["filename"] or Path(row["path"] or "").name
            stem = Path(raw).stem if raw else ""
            if stem:
                found[stem] = {"recording_id": row["id"], "unique_id": row["unique_id"],
                               "started_at": row["started_at"]}
        return found

    def transcribed_recording_ids(self) -> set:
        """Recording ids that have a stored transcript (existence only, no payload)."""
        with self._lock:
            rows = self._conn.execute("SELECT recording_id FROM transcripts").fetchall()
        return {row["recording_id"] for row in rows}

    def current_transcript_recording_ids(self, timemap_version: int) -> set:
        """字幕として使える文字起こしを持つ録画のid。

        「行がある」では足りない。文字起こしの内容は同じ形のまま意味が変わってきた:

          * 時刻mapの版が古い文字起こし … 尺が伸びるほど後ろへずれる(timemap_migrationが選別する)
          * 語ごとの時刻を持たない文字起こし … cueを語の端で締められず、segmentの終端が次の
            segmentの開始まで伸びる。実測でSRTがtimelineを覆う割合は中央値97.7%(語の時刻が
            あれば62.0%、表示単位へ割れば48.4%)で、無音の上に関係のないcueが出続ける。

        どちらも再文字起こしでしか直らないので、一括投入の「済み」から外す母集団をここで引く。
        ``transcribed_recording_ids`` は「行があるか」のままにする — 検索indexのbackfillは
        中身の新旧に関係なく全件を対象にする必要がある。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT recording_id FROM transcripts"
                " WHERE timemap_version = ? AND word_times = 1",
                (timemap_version,),
            ).fetchall()
        return {row["recording_id"] for row in rows}

    def delete_recording(self, recording_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM recordings WHERE id = ?", (recording_id,)
            ).fetchone()
            if row is None:
                return None
            self._conn.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))
            self._conn.commit()
        return dict(row)

    def completed_recordings_with_paths(self) -> list:
        """完了録画のid/所在/容量。最終保存先への退避対象を選ぶための入力。

        pathの所属judgeとfileの実在確認は呼び出し側(server)が行う。record_dir /
        record_dir_final を知っているのはserver側で、ここへ持ち込むとstorageが設定に
        依存することになる。
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, unique_id, path, filename, bytes, started_at"
                " FROM recordings WHERE status = 'completed' AND path IS NOT NULL"
                " ORDER BY started_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def update_recording_bytes(self, recording_id: int, size: int) -> bool:
        """録画のbytesだけを書き換える。中身を差し替えたが所在も状態も変わらない場合
        (混在解像度normalizeの再回収)に使う。update_recordingは status/path/ended_at まで
        書き戻すので、ここで使うと呼び出し側が持っていない値で既存行を潰しかねない。"""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE recordings SET bytes = ? WHERE id = ?", (size, recording_id))
            self._conn.commit()
        return cursor.rowcount > 0

    def set_recording_reprocessed(self, recording_id: int, at: Optional[float]) -> bool:
        """録画を.tsから作り直した時刻を書く。``at=None``で未実施へ戻す。

        一括の「済み」判定はこの列だけを見る。作り直したmp4はfileから見分けが付かない
        (元と同じ名前・同じ場所の別内容)ので、file側から推測してはいけない。"""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE recordings SET reprocessed_at = ? WHERE id = ?", (at, recording_id))
            self._conn.commit()
        return cursor.rowcount > 0

    def set_recording_time_axis(self, recording_id: int, axis: str) -> bool:
        """この録画のDBに焼き付いた秒がどの軸の値かを書く(``media`` / ``pts``)。

        再生経路で決まる事実であり、推測してはいけない。indexを張り直した側が、実際に
        書いた軸をそのまま記録する。scripts/migrate_time_axis_to_media.py はこの列を見て
        変換済みを飛ばすので、正しく無いと同じ値へ二重に変換が掛かる。"""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE recordings SET time_axis = ? WHERE id = ?", (axis, recording_id))
            self._conn.commit()
        return cursor.rowcount > 0

    def set_laugh_index_meta(self, recording_id: int, meta: Optional[dict]) -> bool:
        """笑い声indexを張った条件を記録する(``None``で未記録へ戻す)。

        indexを張った側だけがこの条件を知っている。「行が在る=済み」で代用できないのは、
        共演中を外す設定を変えた後も古い行がそのまま済みに見えるためで、一括処理の
        済み判定はここを見て条件の違う録画を対象へ戻す。"""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE recordings SET laugh_index_json = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False) if meta is not None else None,
                 recording_id),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def laugh_index_meta_map(self) -> dict:
        """recording_id -> 笑い声indexを張った条件。列がNULLの録画はkeyごと現れない。

        一括処理の済み判定と録画一覧の両方が録画数ぶん必要とするので、母集合単位で
        1回だけ引く(録画ごとにget_recordingを叩くと行を丸ごと読んで捨てることになる)。"""
        rows = self._read_connection().execute(
            "SELECT id, laugh_index_json FROM recordings WHERE laugh_index_json IS NOT NULL"
        ).fetchall()
        out: dict = {}
        for row in rows:
            try:
                out[row["id"]] = json.loads(row["laugh_index_json"])
            except ValueError:
                # 読めない値は「条件が分からない」= 未記録と同じ扱い。ここで既定値を
                # 作ると、張っていない条件で張ったと名乗ることになる。
                continue
        return out

    def set_recording_audio_normalized(self, recording_id: int, at: Optional[float],
                                       lufs: Optional[float]) -> bool:
        """録画本体の音量正規化の適用状態を書く。``at=None``で未適用へ戻す。

        mp4を作り直す操作は、正規化を伴わなかったなら必ずNoneで呼んで消すこと。残したまま
        にすると一括画面が「処理済」と数え、実際には素の音量のmp4が対象から外れる。
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE recordings SET audio_normalized_at = ?, audio_normalized_lufs = ?"
                " WHERE id = ?",
                (at, lufs if at is not None else None, recording_id))
            self._conn.commit()
        return cursor.rowcount > 0

    def update_recording_path(self, recording_id: int, path: str) -> bool:
        """録画の所在を書き換える。移送が**成功した後にだけ**呼ぶこと。

        serverは再生・出力でrecordings.pathの絶対pathをそのまま使う(_safe_recording_path)。
        file を動かしてDBを更新しないと再生が壊れ、逆にDBだけ更新するともっと悪い
        (存在しないpathを指す)。filenameは移送で変わらないので触らない。
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE recordings SET path = ? WHERE id = ?", (path, recording_id))
            self._conn.commit()
        return cursor.rowcount > 0

    def set_recording_protected(self, recording_id: int, protected: bool) -> bool:
        """保持policyの自動削除から除外するflagを立てる/下ろす。存在しない録画はFalse。"""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE recordings SET protected = ? WHERE id = ?",
                (1 if protected else 0, recording_id),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def set_recording_review(self, recording_id: int, state: str) -> Optional[dict]:
        """確認状態(未確認/確認中/確認済)を書き換え、更新後の録画行を返す。

        未知の値は受け付けない(ValueError)。画面が読めない印を残すと、その録画は
        どの状態にも属さなくなり、一覧の絞り込みからも消える。存在しない録画はNone。"""
        if state not in RECORDING_REVIEW_STATES:
            raise ValueError(f"unknown review state: {state}")
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE recordings SET review_state = ?, review_updated_at = ? WHERE id = ?",
                (state, time.time(), recording_id),
            )
            self._conn.commit()
            if cursor.rowcount <= 0:
                return None
            row = self._conn.execute(
                "SELECT * FROM recordings WHERE id = ?", (recording_id,)).fetchone()
        return dict(row) if row else None

    def recordings_for_retention(self) -> list:
        """保持policyの候補選定に必要な全録画。文字起こしの有無まで含めるのは、生録画を消すと
        文字起こしも道連れ(transcriptsはON DELETE CASCADE)になることを画面で示すため。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT r.*, (t.recording_id IS NOT NULL) AS has_transcript"
                " FROM recordings r LEFT JOIN transcripts t ON t.recording_id = r.id"
                " ORDER BY r.started_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def save_storage_scan(self, payload: dict, duration_ms: float) -> None:
        """容量内訳の走査結果を1行cacheへ全置換で保存する。"""
        with self._lock:
            self._conn.execute(
                "INSERT INTO storage_scan (id, scanned_at, duration_ms, payload_json)"
                " VALUES (1, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET scanned_at = excluded.scanned_at,"
                " duration_ms = excluded.duration_ms, payload_json = excluded.payload_json",
                (time.time(), duration_ms, json.dumps(payload, ensure_ascii=False)),
            )
            self._conn.commit()

    def get_storage_scan(self) -> Optional[dict]:
        """保存済みの走査結果。まだ一度も走査していなければNone(空の内訳ではない)。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT scanned_at, duration_ms, payload_json FROM storage_scan WHERE id = 1"
            ).fetchone()
        if row is None:
            return None
        return {
            "scanned_at": row["scanned_at"],
            "duration_ms": row["duration_ms"],
            "usage": json.loads(row["payload_json"]),
        }

    def db_file_bytes(self) -> dict:
        """開いているDB本体とWAL/SHMのbyte数。

        env(TICTOK_DB_PATH)を読み直さず、実際に開いているpathを見る。envは後から変わり得る
        ので、読み直すと「いま計測しているDB」と別のfileを測ることになる。
        WALをdbと分けて出すのはcheckpointの判断材料になるため(実測19MB規模まで育つ)。
        """
        base = Path(self._db_path)
        out = {"db": 0, "wal": 0, "shm": 0}
        for key, suffix in (("db", ""), ("wal", "-wal"), ("shm", "-shm")):
            try:
                out[key] = (base.parent / (base.name + suffix)).stat().st_size
            except OSError:
                out[key] = 0
        return out

    def add_capacity_sample(self, payload: dict, sampled_at: Optional[float] = None) -> dict:
        """容量snapshotを1件追記する。storage_scan(1行cache)とは別で、こちらは履歴。"""
        now = time.time() if sampled_at is None else sampled_at
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO capacity_samples (sampled_at, payload_json) VALUES (?, ?)",
                (now, json.dumps(payload, ensure_ascii=False)),
            )
            self._conn.commit()
        return {"id": cursor.lastrowid, "sampled_at": now, "payload": payload}

    def latest_capacity_sample(self) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT sampled_at, payload_json FROM capacity_samples"
                " ORDER BY sampled_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return {"sampled_at": row["sampled_at"], "payload": json.loads(row["payload_json"])}

    def list_capacity_samples(self, since: Optional[float] = None, limit: int = 400) -> list:
        sql = "SELECT sampled_at, payload_json FROM capacity_samples"
        params: tuple = ()
        if since is not None:
            sql += " WHERE sampled_at >= ?"
            params = (since,)
        sql += " ORDER BY sampled_at DESC LIMIT ?"
        with self._lock:
            rows = self._conn.execute(sql, (*params, limit)).fetchall()
        samples = [
            {"sampled_at": r["sampled_at"], "payload": json.loads(r["payload_json"])}
            for r in rows
        ]
        samples.reverse()
        return samples

    def capacity_db_counts(self) -> dict:
        """健全性reportの母数。全てindexかtable走査で数十ms(実測)。"""
        with self._lock:
            rows = {}
            for name in ("events", "sessions", "users", "recordings", "transcripts",
                         "search_hits", "ops_events", "bookmarks"):
                rows[name] = self._conn.execute(
                    f"SELECT COUNT(*) AS c FROM {name}").fetchone()["c"]
            recordings = [
                dict(r) for r in self._conn.execute(
                    "SELECT status, COUNT(*) AS n, COALESCE(SUM(bytes), 0) AS bytes"
                    " FROM recordings GROUP BY status")
            ]
            transcribed = self._conn.execute(
                "SELECT COUNT(*) AS c FROM recordings r"
                " JOIN transcripts t ON t.recording_id = r.id"
                " WHERE r.status = 'completed'").fetchone()["c"]
            media_jobs = [
                dict(r) for r in self._conn.execute(
                    "SELECT kind, state, COUNT(*) AS n FROM media_job_queue"
                    " GROUP BY kind, state")
            ]
            transcribe_queue = [
                dict(r) for r in self._conn.execute(
                    "SELECT state, COUNT(*) AS n FROM transcribe_queue GROUP BY state")
            ]
        return {
            "rows": rows,
            "recordings_by_status": recordings,
            "transcribed_completed": transcribed,
            "media_jobs": media_jobs,
            "transcribe_queue": transcribe_queue,
        }

    def recording_bytes_by_day(self, limit_days: int = 120) -> list:
        """録画の日次増加(bytes)の実績。

        drive空きと違い、こちらは**遡って算出できる**: recordingsがstarted_atとbytesを
        最初から持っているためで、sampleを貯め始めるのを待つ必要がない(実測34日ぶん)。
        画面ではsample由来の系列と混ぜず、由来を分けて示すこと。
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT DATE(started_at, 'unixepoch', 'localtime') AS day,"
                " COUNT(*) AS recordings, COALESCE(SUM(bytes), 0) AS bytes"
                " FROM recordings WHERE started_at IS NOT NULL"
                " GROUP BY day ORDER BY day DESC LIMIT ?",
                (limit_days,),
            ).fetchall()
        return [
            {"day": r["day"], "recordings": r["recordings"], "bytes": r["bytes"]}
            for r in reversed(rows)
        ]

    def mark_stale_recordings(self) -> int:
        """On startup, recordings left 'recording' are orphaned (process died)."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE recordings SET status = 'interrupted' WHERE status = 'recording'"
            )
            self._conn.commit()
        return cursor.rowcount

    def recordings_for_recovery(self) -> list:
        """クラッシュで中断した録画(status='recording'/'interrupted')を返す。捕捉済みHLS
        segmentがディスクに残っていればmp4へ再finalizeできるため、起動時の復元対象を列挙する。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, session_id, unique_id, path, filename, status, started_at, ended_at"
                " FROM recordings"
                " WHERE status IN ('recording', 'interrupted') ORDER BY started_at"
            ).fetchall()
        return [dict(row) for row in rows]
