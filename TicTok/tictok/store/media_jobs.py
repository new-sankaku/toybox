"""映像job queue(焼き込み / Up出力 / 再mp4化)。

境界の理由: media_jobs表を1つのqueueとして扱う状態機械。claim(取得)〜finish(終了)の
遷移が互いに前提を共有するため、遷移methodを分散させない。

lock契約: lock保持前提のmethodは無い。claim_next_pending_media_job は
  1つの self._lock 区間の中でSELECT〜UPDATE〜commitまでを完結させる(取得競合を防ぐ)。
"""
import json
import sqlite3
import time
from typing import Optional


class MediaJobsMixin:
    """映像job queue(焼き込み / Up出力 / 再mp4化)。

    lockもDB接続も持たない。すべて Storage が所有する self._conn /
    self._lock / self._read_lock を借りる(mixinとして Storage に混ぜられる前提)。
    契約の詳細はmodule docstringを参照。
    """

    # ===== 映像job queue(焼き込み / Up出力 / 再mp4化) =====

    @staticmethod
    def _media_job_row(row: sqlite3.Row) -> dict:
        item = dict(row)
        item["result"] = json.loads(item.pop("result_json") or "{}")
        item["params"] = json.loads(item.pop("params_json", None) or "{}")
        return item

    def enqueue_media_job(self, job_id: str, kind: str, recording_id: int, *,
                          session_id: Optional[int] = None, group_id: str = "",
                          title: str = "", priority: int = 0,
                          params: Optional[dict] = None, sweep: bool = False) -> dict:
        """1件投入して行を返す。重複投入の抑止は呼び出し側(pending_media_job_for)で行う:
        「同じ焼き込みをもう一度」は再出力として正当な要求なので、ここでは拒まない。

        ``sweep`` は起動時sweepが自動で積んだ行の目印。workerはこの印の付いた行の同時実行
        本数を人の投入と別枠で絞る(claim_next_pending_media_job)。"""
        with self._lock:
            self._conn.execute(
                "INSERT INTO media_job_queue"
                " (job_id, kind, recording_id, session_id, group_id, title, state,"
                "  priority, queued_at, params_json, sweep)"
                " VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)",
                (job_id, kind, recording_id, session_id, group_id, title, priority,
                 time.time(), json.dumps(params or {}, ensure_ascii=False),
                 1 if sweep else 0),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM media_job_queue WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._media_job_row(row)

    def busy_recording_ids(self) -> set:
        """焼き込み/Up出力/転写が待機・実行中の録画id。

        文字起こしも同じ台帳(kind=stt)にいるので、1回のqueryで両方が入る。
        これらのjobはsrc mp4を実行中に読むため、消すと道半ばで壊れたjobだけが残る。
        容量整理の一括削除が対象から外すために使う。"""
        with self._lock:
            media = self._conn.execute(
                "SELECT DISTINCT recording_id FROM media_job_queue"
                " WHERE state IN ('pending', 'running') AND recording_id IS NOT NULL"
            ).fetchall()
        return {row["recording_id"] for row in media}

    def pending_media_job_for(self, kind: str, recording_id: int) -> Optional[dict]:
        """同じ録画・同じ種別で既に待機/実行中のjob。二重投入を弾くために使う。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM media_job_queue"
                " WHERE kind = ? AND recording_id = ? AND state IN ('pending', 'running')"
                " ORDER BY queued_at LIMIT 1",
                (kind, recording_id),
            ).fetchone()
        return self._media_job_row(row) if row else None

    def pending_media_job_keys(self) -> set:
        """待機/実行中の全jobの (kind, recording_id) 集合。一括画面は録画ごとに二重投入を
        弾く判定を行うが、録画数ぶんの個別queryを回すと重い。1回で引いて集合の照合にする。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT kind, recording_id FROM media_job_queue"
                " WHERE state IN ('pending', 'running')"
            ).fetchall()
        return {(row["kind"], row["recording_id"]) for row in rows}

    def media_job_recording_ids_in_states(self, kinds, states) -> dict:
        """``{kind: {recording_id, ...}}``。指定stateで終わった行を1件でも持つ録画を種別ごとに
        集める。起動時sweepが「前回そうなった録画」を自動で積み直さないために使う。

        sweepの候補判定は成果物の実在なので、失敗・skip・取り消しで終わった録画は成果物が
        無いまま残り、次の起動でまた候補に戻る。音声の無い録画のように結果が変わらないものは、
        これを毎回積み直すと台帳が同じ失敗で埋まる。台帳の行はprune_media_jobsで期限切れに
        なるため、この抑止は永久ではなく保持期間ぶんの猶予になる(環境が直れば戻ってくる)。"""
        if not kinds or not states:
            return {}
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT kind, recording_id FROM media_job_queue"
                " WHERE kind IN (%s) AND state IN (%s) AND recording_id IS NOT NULL"
                % (",".join("?" * len(kinds)), ",".join("?" * len(states))),
                list(kinds) + list(states),
            ).fetchall()
        out: dict = {kind: set() for kind in kinds}
        for row in rows:
            out[row["kind"]].add(row["recording_id"])
        return out

    def next_pending_media_job(self) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM media_job_queue WHERE state = 'pending'"
                " ORDER BY priority DESC, queued_at LIMIT 1"
            ).fetchone()
        return self._media_job_row(row) if row else None

    def claim_next_pending_media_job(self, sweep_limit: int = 0) -> Optional[dict]:
        """次の待機jobをrunningへ落として返す(無ければNone)。

        選ぶのと掴むのを1つのlockの中で済ませるのは、workerが複数居るときに同じ行を
        2人が拾わないため。取得と開始が別呼び出しだと、その隙間で同じ録画へ2本の
        ffmpegが走り、同じ出力fileを奪い合う。

        同じ録画に対する別種のjobも同時には出さない。再mp4化は録画のmp4を作り直して
        差し替えるので、その裏で同じmp4を読んでいる焼き込みは途中で足元を抜かれる。
        直列workerの時代はこれが起こり得なかったため、並列化と一緒に明示する。

        ``sweep_limit`` は起動時sweepが積んだ行の同時実行上限(0で無制限)。sweepは人が待って
        いない自動投入なので、workerを全部占めると人の投入がその後ろで待たされる。数え方と
        掴み方を同じlockの中に置くのは、上限判定と掴みが別呼び出しだと2人のworkerが同時に
        「まだ空きがある」と判断できてしまうため。"""
        with self._lock:
            sweep_clause = ""
            if sweep_limit > 0:
                running_sweeps = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM media_job_queue"
                    " WHERE state = 'running' AND sweep = 1"
                ).fetchone()["n"]
                if running_sweeps >= sweep_limit:
                    sweep_clause = " AND sweep = 0"
            row = self._conn.execute(
                "SELECT job_id FROM media_job_queue WHERE state = 'pending'"
                " AND (not_before IS NULL OR not_before <= ?)"
                + sweep_clause +
                " AND recording_id NOT IN ("
                "   SELECT recording_id FROM media_job_queue"
                "   WHERE state = 'running' AND recording_id IS NOT NULL)"
                " ORDER BY priority DESC, queued_at LIMIT 1",
                (time.time(),),
            ).fetchone()
            if row is None:
                return None
            job_id = row["job_id"]
            self._conn.execute(
                "UPDATE media_job_queue SET state = 'running', started_at = ?, pct = 0,"
                " stage = '', error = NULL WHERE job_id = ?",
                (time.time(), job_id),
            )
            self._conn.commit()
            claimed = self._conn.execute(
                "SELECT * FROM media_job_queue WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._media_job_row(claimed) if claimed else None

    def get_media_job(self, job_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM media_job_queue WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._media_job_row(row) if row else None

    def start_media_job(self, job_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE media_job_queue SET state = 'running', started_at = ?, pct = 0,"
                " stage = '', error = NULL WHERE job_id = ?",
                (time.time(), job_id),
            )
            self._conn.commit()

    def update_media_job_progress(self, job_id: str, pct: int, stage: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE media_job_queue SET pct = ?, stage = ? WHERE job_id = ?",
                (max(0, min(100, int(pct))), stage, job_id),
            )
            self._conn.commit()

    def finish_media_job(self, job_id: str, state: str, *, error: Optional[str] = None,
                         result: Optional[dict] = None) -> None:
        # stageは「いま何をしているか」であって終わり方ではない。終端で消さないと、取り消し
        # 要求時に書いた『取り消し中…』が終了後の行にも残り、stateはcancelledなのに画面は
        # まだ止めようとしているように見える。
        with self._lock:
            self._conn.execute(
                "UPDATE media_job_queue SET state = ?, finished_at = ?, error = ?, stage = '',"
                " pct = CASE WHEN ? = 'completed' THEN 100 ELSE pct END,"
                " result_json = COALESCE(?, result_json) WHERE job_id = ?",
                (state, time.time(), error, state,
                 json.dumps(result, ensure_ascii=False) if result is not None else None,
                 job_id),
            )
            self._conn.commit()

    def defer_media_job(self, job_id: str, not_before: float, stage: str) -> None:
        """実行中のjobを待機へ戻し、``not_before`` まで拾わせない。

        失敗ではないのでattemptも消費しないし、finished_atも書かない。前提(保存先volume)が
        戻れば同じ行がそのまま走り出す。``deferred_since`` は最初の1回だけ立て、以後の
        延長でも上書きしない — ここを毎回更新すると、待ち続けるjobが打ち切りに掛からない。"""
        with self._lock:
            self._conn.execute(
                "UPDATE media_job_queue SET state = 'pending', started_at = NULL,"
                " pct = 0, stage = ?, error = NULL, not_before = ?,"
                " deferred_since = COALESCE(deferred_since, ?) WHERE job_id = ?",
                (stage, not_before, time.time(), job_id),
            )
            self._conn.commit()

    REQUEUEABLE_STATES = ("failed", "interrupted", "cancelled")

    def requeue_media_jobs(self, job_ids, *, auto: bool = False) -> int:
        """終わってしまったjobを待機へ戻す。戻した件数を返す。

        対象は failed / interrupted / cancelled だけ。completed を戻せると「もう一度出力」と
        区別が付かなくなる(あれは新しい投入であって、同じ行の再開ではない)。``result_json``は
        捨てる: 失敗時の退避先が残ったままだと、起動時のrecoveryが次の実行で作った成果物を
        古い退避で上書きしかねない。

        ``auto`` は起動時の自動再開ぶん。回数を params へ数え、呼び出し側が上限で打ち切れる
        ようにする — processごと落とすjobを無条件に戻すと、起動のたびに同じ落ち方を繰り返す。
        """
        ids = [str(j) for j in job_ids]
        if not ids:
            return 0
        requeued = 0
        with self._lock:
            for job_id in ids:
                row = self._conn.execute(
                    "SELECT state, params_json FROM media_job_queue WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
                if row is None or row["state"] not in self.REQUEUEABLE_STATES:
                    continue
                params = json.loads(row["params_json"] or "{}")
                if auto:
                    params["auto_requeues"] = int(params.get("auto_requeues") or 0) + 1
                self._conn.execute(
                    "UPDATE media_job_queue SET state = 'pending', queued_at = ?,"
                    " started_at = NULL, finished_at = NULL, pct = 0, stage = '',"
                    " error = NULL, not_before = NULL, deferred_since = NULL,"
                    " result_json = '{}', params_json = ? WHERE job_id = ?",
                    (time.time(), json.dumps(params, ensure_ascii=False), job_id),
                )
                requeued += 1
            self._conn.commit()
        return requeued

    def set_media_job_result(self, job_id: str, result: dict) -> None:
        """実行の途中で判明した後始末情報を、終了を待たずに残す。再mp4化が元mp4を_backupへ
        退避した直後の退避先がこれで、processがここで落ちると起動時のrecoveryが唯一の
        復元手段になる(退避先を覚えていなければ、mp4の在り処は誰にも分からない)。"""
        with self._lock:
            self._conn.execute(
                "UPDATE media_job_queue SET result_json = ? WHERE job_id = ?",
                (json.dumps(result, ensure_ascii=False), job_id),
            )
            self._conn.commit()

    def list_media_jobs(self, limit: int = 200) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT q.*, r.filename, r.unique_id, r.path AS recording_path"
                " FROM media_job_queue q LEFT JOIN recordings r ON r.id = q.recording_id"
                " ORDER BY CASE q.state WHEN 'running' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,"
                " q.priority DESC, COALESCE(q.finished_at, q.started_at, q.queued_at) DESC"
                " LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._media_job_row(row) for row in rows]

    def media_job_durations(self, kind: str, limit: int = 50) -> list:
        """完了したjobの実測 (所要秒, 元録画の尺秒) を新しい順に返す。

        配信者まるごとの一括投入は所要時間を先に見せないと押せないが、その倍率を設定値や
        定数で持つとGPU・model・解像度が違う環境で必ず外れる。実績が1件も無ければ空listを
        返し、呼び出し側は「不明」と出す(推測値を出すと、根拠のある数字と区別できない)。

        尺の出所は実測(duration_seconds)だけ。壁時計で割ると、捕捉が停滞した録画や
        ended_atが再処理時刻に潰れた録画で分母が数十倍になり、倍率が桁ごと狂う。
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT q.started_at, q.finished_at, r.duration_seconds AS source"
                " FROM media_job_queue q JOIN recordings r ON r.id = q.recording_id"
                " WHERE q.kind = ? AND q.state = 'completed'"
                " AND q.started_at IS NOT NULL AND q.finished_at IS NOT NULL"
                " AND r.duration_seconds IS NOT NULL"
                " ORDER BY q.finished_at DESC LIMIT ?",
                (kind, limit),
            ).fetchall()
        pairs = []
        for row in rows:
            elapsed = row["finished_at"] - row["started_at"]
            if elapsed > 0 and row["source"] > 0:
                pairs.append((elapsed, row["source"]))
        return pairs

    def media_jobs_in_group(self, group_id: str) -> list:
        """session一括投入の1回分。group進捗はこの集合から毎回組み直す(集計値を別に持つと、
        片方だけ更新された瞬間に画面とDBが食い違う)。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM media_job_queue WHERE group_id = ? ORDER BY queued_at, id",
                (group_id,),
            ).fetchall()
        return [self._media_job_row(row) for row in rows]

    def cancel_pending_media_job(self, job_id: str) -> bool:
        """待機中のjobを取り消す。実行中はDB更新だけでは止まらない(worker側でtokenを
        投げる必要がある)ので、ここでは対象外にしている。"""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE media_job_queue SET state = 'cancelled', finished_at = ?, stage = ''"
                " WHERE job_id = ? AND state = 'pending'",
                (time.time(), job_id),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def interrupt_running_media_jobs(self) -> list:
        """起動時: 前回processが落ちて'running'のまま残った行を返し、'interrupted'にする。

        転写queueのようにここでpendingへ戻さないのは、映像jobが中途の成果物(退避したmp4・
        部分出力)を残したまま死んでいる可能性があるためで、後始末を済ませるまで自動で走らせては
        いけない。返した行はserver側のrecoveryが個別に処理し、原状へ戻した上で待機列へ戻す
        (``requeue_media_jobs(auto=True)``)。順序が逆だと、断片の上から作り直しが始まる。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM media_job_queue WHERE state = 'running'"
            ).fetchall()
            self._conn.execute(
                "UPDATE media_job_queue SET state = 'interrupted', finished_at = ?, stage = '',"
                " error = 'server再起動により中断されました。' WHERE state = 'running'",
                (time.time(),),
            )
            self._conn.commit()
        return [self._media_job_row(row) for row in rows]

    def prune_media_jobs(self, older_than_seconds: float) -> int:
        """終了済みの古い行を消す。0以下なら消さない(履歴を全部残す運用)。"""
        if older_than_seconds <= 0:
            return 0
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM media_job_queue"
                " WHERE state NOT IN ('pending', 'running') AND finished_at < ?",
                (time.time() - older_than_seconds,),
            )
            self._conn.commit()
        return cursor.rowcount
