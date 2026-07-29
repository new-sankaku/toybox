"""取り込み経路(batch writer / 耐久journal / event投入)。

境界の理由: **このmixinはlock区間そのものである。** buffer入れ替えからcommitまでを
1つの self._lock 区間で完結させる _drain と、その内側でしか呼べない補助methodを
1 fileに閉じ込める。区間を跨いで呼ばれるのは delete_session(sessions mixin)が同じ
self._lock を取ることだけで、それが孤児判定のTOCTOUを防いでいる(_drain のcomment参照)。
耐久journalを同居させるのは、add_event が「journalへ追記 -> bufferへ投入」の2経路を
同時に持ち、片方だけを見ても取り込みの全体像が読めないため。

lock契約:
  取得順は self._lock -> self._buf_lock の一方向のみ。逆順は存在しない。
  _drain が self._lock を取り、その内側で self._buf_lock を取る。
  以下は self._lock 保持前提(呼び出し元は _drain のlock区間内):
    _log_backlog / _drop_orphan_rows / _write_batch_locked / _write_isolating_locked
    / _insert_rows_isolating / _upsert_users_locked / _rollback_and_requeue
  _rollback_and_requeue は末尾で self._buf_lock を取る(_lock 保持中なので取得順は保たれる)。
  _journal_append / _journal_handle_locked / _close_journal は self._journal_lock 系で、
  self._lock とは独立(どちらの向きにも入れ子にしていない)。
  add_event 系は self._buf_lock だけを取り、self._lock は取らない。
"""
import gzip
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

from tictok.core.config import (
    get_journal_dir,
    get_journal_retention_days,
    get_log_dir,
    get_log_progress_interval_seconds,
    get_storage_backlog_warn_rows,
)
from tictok.core.logging_setup import progress_interval_seconds

from tictok.store._common import (
    _EVENTS_COLUMNS,
    _EVENTS_INSERT_SQL,
    _VIEWERS_INSERT_SQL,
    _WRITE_BATCH_SIZE,
    _WRITE_FLUSH_INTERVAL_SECONDS,
    _identity_key,
    _session_ids_of,
    logger,
)


class IngestMixin:
    """取り込み経路(batch writer / 耐久journal / event投入)。

    lockもDB接続も持たない。すべて Storage が所有する self._conn /
    self._lock / self._read_lock を借りる(mixinとして Storage に混ぜられる前提)。
    契約の詳細はmodule docstringを参照。
    """

    def _writer_loop(self) -> None:
        while True:
            with self._flush_cond:
                self._flush_cond.wait(timeout=_WRITE_FLUSH_INTERVAL_SECONDS)
                closed = self._closed
            # drainの例外でwriterスレッドを死なせない(死ぬと以降の全書き込みが黙って
            # バッファに滞留したまま失われる)。失敗行は_drain側で再キューされ次周期で再試行。
            try:
                self._drain()
            except Exception as exc:
                # 詳細(件数・session_ids・sqlite error種別)は_drain側の失敗logが持つ。ここは
                # 「writerスレッドが生きたまま次周期へ進んだ」ことだけを1行残す。
                logger.warning(
                    "storage writerの書き出し周期が失敗しました（次の周期で再試行します）",
                    exc_info=True,
                    extra={"event": "storage.writer_cycle_failed",
                           "ctx": {"exc_type": type(exc).__name__}},
                )
            if closed:
                return

    def _drain(self) -> None:
        """バッファ済みのevent/viewer sample/user upsertを1 transactionで書き出す。
        writerスレッドと同期flush()の双方から呼ばれるため、buffer入れ替えからcommitまで
        DB lockを保持し、flush()呼び出し時に進行中の書き込み完了を確実に待たせる。"""
        with self._lock:
            with self._buf_lock:
                events = self._event_buffer
                viewers = self._viewer_buffer
                users = self._pending_users
                if not (events or viewers or users):
                    return
                self._event_buffer = []
                self._viewer_buffer = []
                self._pending_users = []
                # backlogの測定はここでしか行わない。len(self._event_buffer)には_buf_lockが
                # 必要で、既にそれを保持しているこの地点なら新規のlock取得がゼロで済む。
                # 別の場所で測ると_lock -> _buf_lockの取得順を崩すdeadlock riskを新設する。
                backlog = len(events) + len(viewers) + len(users)
            self._log_backlog(backlog, events, viewers)
            # session削除とbuffer滞留の競合で、既に消えたsessionを参照する孤児行が残ることが
            # ある(events/viewer_samplesはsessions(id)へFK)。これを含めてexecutemanyすると
            # FK違反でbatchごと失敗し、下のexcept再キューで永久に詰まる(poison-pill)。孤児は
            # 再試行しても成功しない永続エラーなので、insert前にDB実在のsession_idで濾し取り除く。
            # delete_sessionはself._lockを取ってからDELETEするため、この判定〜commitの間に
            # 対象sessionが消えることはなく(TOCTOU無し)、判定は確定的。
            events, viewers = self._drop_orphan_rows(events, viewers)
            try:
                self._write_batch_locked(events, viewers, users)
                self._conn.commit()
            except sqlite3.OperationalError as exc:
                # 一時障害(DB lock/busy/disk full/I/O)。再試行で回復し得るので、rollbackの上で
                # 未確定分を先頭へ戻し次周期で再試行する。1行の永続不良ではないため隔離しない。
                self._rollback_and_requeue(events, viewers, users, exc)
                raise
            except sqlite3.IntegrityError as exc:
                # 制約違反(想定外の不正行)。executemanyは違反行でbatch全体を失敗させるので、
                # このまま再キューすると其の1行が後続すべてを永久に道連れにする(poison-pill)。
                # rollbackしてから1行ずつ入れ直し、違反行だけを隔離(dead-letterへ退避)して
                # 残りは確定させる。全体を止めない。
                logger.warning(
                    "storageのbatchで制約違反が発生したため、1行ずつ入れ直して該当行を隔離します",
                    exc_info=True,
                    extra={"event": "storage.integrity_isolation_started",
                           "ctx": {"events": len(events), "viewers": len(viewers),
                                   "users": len(users),
                                   "session_ids": _session_ids_of(events, viewers),
                                   "error": str(exc)}},
                )
                try:
                    self._conn.rollback()
                except Exception:
                    logger.exception(
                        "storageのrollbackに失敗しました",
                        extra={"event": "storage.rollback_failed",
                               "ctx": {"session_ids": _session_ids_of(events, viewers)}},
                    )
                try:
                    self._write_isolating_locked(events, viewers, users)
                    self._conn.commit()
                except sqlite3.OperationalError as inner:
                    # 隔離中に一時障害が出たら、全体をrollbackして次周期へ再キュー(再試行で回復)。
                    self._rollback_and_requeue(events, viewers, users, inner)
                    raise
            except Exception as exc:
                # 想定外(DB corruption等のDatabaseErrorや実装バグ)。bufferは既に空にしている
                # ため、ここで捨てるとevent/viewerが黙って失われる。判別不能な障害は一時障害と
                # 同様に扱い、rollbackの上で再キューして次周期に委ねる(誤って全損させない)。
                self._rollback_and_requeue(events, viewers, users, exc)
                raise

    def _log_backlog(self, backlog: int, events: list, viewers: list) -> None:
        """batch writerが遅れてbufferが積み上がっていることを報告する。writerスレッドは
        ContextVarを継承しない常駐threadなので、相関は自動注入されない。誰の書き込みが
        滞っているかを追えるようsession_idsをctxへ明示する。

        DEBUG時はprogress_interval_seconds()が0を返し毎周期出る(通常はgateで間引く)。"""
        if backlog < get_storage_backlog_warn_rows():
            return
        now = time.monotonic()
        interval = progress_interval_seconds(get_log_progress_interval_seconds())
        if now - self._backlog_logged_at < interval:
            return
        self._backlog_logged_at = now
        logger.warning(
            "storageの書き込みbufferが滞留しています（1 batchあたり %d 行）", backlog,
            extra={"event": "storage.write_backlogged",
                   "ctx": {"backlog_rows": backlog, "events": len(events),
                           "viewers": len(viewers),
                           "session_ids": _session_ids_of(events, viewers)}},
        )

    def _drop_orphan_rows(self, events: list, viewers: list) -> tuple:
        """buffer済みevent/viewer行のうち、参照先sessionが既にDBから消えている孤児を取り除く。
        両表ともsession_idは各tupleの先頭要素。呼び出し元(_drain)がself._lockを保持している間に
        呼ぶ前提で、判定に使うsessions実在チェックとその後のinsert/commitは同一lock区間内に収まる。"""
        session_ids = {row[0] for row in events} | {row[0] for row in viewers}
        if not session_ids:
            return events, viewers
        placeholders = ",".join("?" * len(session_ids))
        alive = {
            r["id"]
            for r in self._conn.execute(
                f"SELECT id FROM sessions WHERE id IN ({placeholders})",
                tuple(session_ids),
            )
        }
        if len(alive) == len(session_ids):
            return events, viewers
        kept_events = [row for row in events if row[0] in alive]
        kept_viewers = [row for row in viewers if row[0] in alive]
        logger.warning(
            "event %d 件 / viewer %d 件を破棄しました（削除済みsession %s を参照）",
            len(events) - len(kept_events),
            len(viewers) - len(kept_viewers),
            sorted(session_ids - alive),
            extra={"event": "storage.orphan_rows_dropped",
                   "ctx": {"events": len(events) - len(kept_events),
                           "viewers": len(viewers) - len(kept_viewers),
                           "session_ids": sorted(session_ids - alive)}},
        )
        return kept_events, kept_viewers

    def _write_batch_locked(self, events: list, viewers: list, users: list) -> None:
        """高速経路: event/viewerをexecutemanyで一括INSERTし、userを1件ずつupsertする。
        self._lock保持前提。commitは呼び出し元(_drain)が行う。"""
        if events:
            self._conn.executemany(_EVENTS_INSERT_SQL, events)
        if viewers:
            self._conn.executemany(_VIEWERS_INSERT_SQL, viewers)
        self._upsert_users_locked(users)

    def _write_isolating_locked(self, events: list, viewers: list, users: list) -> None:
        """隔離経路: batch INSERTがIntegrityErrorで失敗した後、1行ずつINSERTし直す。
        呼び出し前にrollback済み(部分INSERTは巻き戻し済み)であること。IntegrityErrorの行だけ
        dead-letterへ退避してdropし、残りは確定させる。OperationalError(一時障害)は隔離せず
        上位へ送出して全体再キューさせる。"""
        bad_events = self._insert_rows_isolating(_EVENTS_INSERT_SQL, events)
        bad_viewers = self._insert_rows_isolating(_VIEWERS_INSERT_SQL, viewers)
        self._upsert_users_locked(users)
        if bad_events or bad_viewers:
            quarantine_path = self._quarantine(bad_events, bad_viewers)
            # data喪失(DBには二度と入らない行)なのでerror。dead-letterに退避してあるとはいえ
            # 自動で戻る経路は無く、人が見て手で復旧する以外に回復手段が無い。
            logger.error(
                "DBの制約に違反した event %d 行 / viewer %d 行を隔離しました"
                "（DBには入っておらず、手動での復旧が必要です）",
                len(bad_events), len(bad_viewers),
                extra={"event": "storage.rows_quarantined",
                       "ctx": {"events": len(bad_events), "viewers": len(bad_viewers),
                               "session_ids": _session_ids_of(bad_events, bad_viewers),
                               "path": quarantine_path}},
            )

    def _insert_rows_isolating(self, sql: str, rows: list) -> list:
        """rowsを1行ずつINSERTし、IntegrityErrorの行だけを返して隔離対象にする。
        OperationalError(一時障害)はそのまま送出し、上位で全体rollback+再キューさせる。"""
        bad: list = []
        for row in rows:
            try:
                self._conn.execute(sql, row)
            except sqlite3.IntegrityError:
                bad.append(row)
        return bad

    def _upsert_users_locked(self, users: list) -> None:
        for user, ts, key in users:
            # 1 userのupsert失敗(想定外の型/制約)で同バッチのevent/viewerごと巻き込まないよう
            # 個別に隔離する。userプロフィールはevents側にも冗長に残るため1件のskipは名寄せ精度の
            # 軽微な劣化に留まる。
            try:
                self._upsert_user_locked(user, ts, key=key, use_cache=True)
            except Exception:
                logger.exception("userのupsertに失敗したためこの1件をskipします（key=%s）", key)

    def _quarantine(self, bad_events: list, bad_viewers: list) -> str:
        """制約違反でDBに入らなかった行をdead-letterファイルへ退避する。黙って捨てず、
        後から原因調査・手動復旧できるようにする(生journalとは別の最終防波堤)。退避先pathを
        返し、呼び出し元のlogが「どこを見ればよいか」を示せるようにする。"""
        path = Path(get_log_dir()) / "storage_quarantine.jsonl"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                for row in bad_events:
                    fh.write(json.dumps({"table": "events", "row": row}, ensure_ascii=False, default=str) + "\n")
                for row in bad_viewers:
                    fh.write(json.dumps({"table": "viewer_samples", "row": row}, ensure_ascii=False, default=str) + "\n")
        except Exception:
            # dead-letterにも書けない = 行が完全に失われた。最後の記録手段まで失った状態。
            logger.error(
                "storageのdead-letterへ書き出せず、event %d 行 / viewer %d 行が失われました",
                len(bad_events), len(bad_viewers),
                exc_info=True,
                extra={"event": "storage.quarantine_write_failed",
                       "ctx": {"events": len(bad_events), "viewers": len(bad_viewers),
                               "path": str(path),
                               "session_ids": _session_ids_of(bad_events, bad_viewers),
                               **self._db_space_ctx()}},
            )
        return str(path)

    def _rollback_and_requeue(self, events: list, viewers: list, users: list,
                              exc: BaseException) -> None:
        """一時障害時: rollbackして未確定分をbuffer先頭へ戻し、次のdrain周期で再試行させる。

        levelは障害の性質で分ける。lock/busyは再試行で回復する遅延(warning)だが、disk full /
        I-O / 破損は再試行しても入らず書き込みが恒久的に失われる(error)。両者はsqlite3側では
        同じOperationalErrorなので、exc_typeだけでは永久に切り分けられない。"""
        fatal = self._is_fatal_sqlite(exc)
        session_ids = _session_ids_of(events, viewers)
        logger.log(
            logging.ERROR if fatal else logging.WARNING,
            "storageの書き出しに失敗したためrollbackし、event %d 件 / viewer %d 件 / "
            "user %d 件をqueueへ戻します",
            len(events), len(viewers), len(users),
            exc_info=True,
            extra={"event": "storage.drain_requeued",
                   "ctx": {"events": len(events), "viewers": len(viewers),
                           "users": len(users), "session_ids": session_ids,
                           "retryable": not fatal, **self._sqlite_error_ctx(exc)}},
        )
        try:
            self._conn.rollback()
        except Exception:
            logger.exception(
                "storageのrollbackに失敗しました",
                extra={"event": "storage.rollback_failed",
                       "ctx": {"session_ids": session_ids}},
            )
        with self._buf_lock:
            self._event_buffer = events + self._event_buffer
            self._viewer_buffer = viewers + self._viewer_buffer
            self._pending_users = users + self._pending_users

    # ----- 耐久journal(取り込み時点でdiskへ追記する最終防波堤) --------------------------

    def _journal_append(self, kind: str, row: tuple) -> None:
        """1 event/viewer行を日次ローテートのNDJSONへ追記する。batched writerとは独立の経路で、
        best-effort(失敗しても本流は止めない)。flush()はOS page cacheまで(fsyncはしない、
        battle_rawと同水準)。プロセスクラッシュは耐えるが電源断は非対象。"""
        if not self._journal_enabled:
            return
        try:
            line = json.dumps({"t": kind, "r": list(row)}, ensure_ascii=False, default=str)
        except Exception:
            logger.exception(
                "journalの1件をJSONにできませんでした（kind=%s）", kind,
                extra={"event": "storage.journal_serialize_failed", "ctx": {"kind": kind}},
            )
            return
        with self._journal_lock:
            try:
                fh = self._journal_handle_locked()
                fh.write(line + "\n")
                fh.flush()
            except Exception:
                logger.exception(
                    "event journalへ追記できませんでした",
                    extra={"event": "storage.journal_append_failed",
                           "ctx": {"kind": kind, "journal_day": self._journal_day}},
                )

    def _journal_handle_locked(self):
        day = time.strftime("%Y%m%d", time.localtime())
        if self._journal_fh is not None and self._journal_day == day:
            return self._journal_fh
        if self._journal_fh is not None:
            try:
                self._journal_fh.close()
            except Exception:
                logger.exception("回転前のjournal handleを閉じられませんでした")
        journal_dir = Path(get_journal_dir())
        journal_dir.mkdir(parents=True, exist_ok=True)
        self._journal_fh = (journal_dir / f"events-{day}.jsonl").open("a", encoding="utf-8")
        self._journal_day = day
        return self._journal_fh

    def _close_journal(self) -> None:
        with self._journal_lock:
            if self._journal_fh is not None:
                try:
                    self._journal_fh.close()
                except Exception:
                    logger.exception("journal handleを閉じられませんでした")
                self._journal_fh = None
                self._journal_day = None

    def recover_from_journal(self) -> dict:
        """起動時: journalの各sessionについて、DBに欠けているevent/viewerを復元する。
        batched writerの停滞やクラッシュ・再起動でbuffer滞留分が失われても、取り込み時に
        journalへ残っているので後から埋め戻せる。安全のため:
          - session行が無い(=削除済み/未作成)ならresurrectしない(削除の意思を尊重)。
          - DBがjournalと同数以上なら何もしない。
          - journalがDBを『全項目で上回る』時のみ、当該sessionのevent/viewerをidempotentに
            全置換して復元する(count混在=不整合はskipしてwarn、誤clobber回避)。
        置換後はstats_json/buckets/analytics cacheをeventから再構成する。"""
        summary = {"sessions": 0, "events": 0, "viewers": 0}
        if not self._journal_enabled:
            return summary
        events_by_sid: dict = {}
        viewers_by_sid: dict = {}
        for path in self._journal_files():
            self._read_journal_file(path, events_by_sid, viewers_by_sid)
        session_ids = sorted(set(events_by_sid) | set(viewers_by_sid))
        with self._lock:
            for sid in session_ids:
                j_events = events_by_sid.get(sid, [])
                j_viewers = viewers_by_sid.get(sid, [])
                exists = self._conn.execute(
                    "SELECT bucket_seconds FROM sessions WHERE id = ?", (sid,)
                ).fetchone()
                if exists is None:
                    continue  # 削除済み/未作成: resurrectしない
                db_ev = self._conn.execute(
                    "SELECT COUNT(*) c FROM events WHERE session_id = ?", (sid,)
                ).fetchone()["c"]
                db_vw = self._conn.execute(
                    "SELECT COUNT(*) c FROM viewer_samples WHERE session_id = ?", (sid,)
                ).fetchone()["c"]
                if db_ev >= len(j_events) and db_vw >= len(j_viewers):
                    continue  # DBが同数以上: 復元不要
                if len(j_events) < db_ev or len(j_viewers) < db_vw:
                    # journalがどちらかでDBを下回る=不整合。全置換するとDB側の分を失うのでskip。
                    logger.warning(
                        "journalからの復元でsession %d をskipしました: 件数が不整合です"
                        "（db ev=%d vw=%d, journal ev=%d vw=%d）人の確認が必要です",
                        sid, db_ev, db_vw, len(j_events), len(j_viewers),
                        extra={"event": "storage.journal_recovery_skipped",
                               "ctx": {"restore_session_id": sid, "db_events": db_ev,
                                       "db_viewers": db_vw, "journal_events": len(j_events),
                                       "journal_viewers": len(j_viewers)}},
                    )
                    continue
                try:
                    self._conn.execute("DELETE FROM events WHERE session_id = ?", (sid,))
                    self._conn.execute("DELETE FROM viewer_samples WHERE session_id = ?", (sid,))
                    if j_events:
                        self._conn.executemany(_EVENTS_INSERT_SQL, j_events)
                    if j_viewers:
                        self._conn.executemany(_VIEWERS_INSERT_SQL, j_viewers)
                    self._recompute_session_stats_locked(sid)
                    self._rebuild_buckets_locked(sid, exists["bucket_seconds"])
                    self._conn.commit()
                    self._refresh_session_analytics_locked(sid)
                    self._conn.commit()
                except Exception:
                    logger.exception(
                        "session %d のjournalからの復元に失敗したためrollbackします", sid,
                        extra={"event": "storage.journal_recovery_failed",
                               "ctx": {"restore_session_id": sid,
                                       "journal_events": len(j_events),
                                       "journal_viewers": len(j_viewers)}},
                    )
                    try:
                        self._conn.rollback()
                    except Exception:
                        logger.exception(
                            "journalからの復元中にrollbackが失敗しました",
                            extra={"event": "storage.journal_rollback_failed",
                                   "ctx": {"restore_session_id": sid}},
                        )
                    continue
                summary["sessions"] += 1
                summary["events"] += len(j_events) - db_ev
                summary["viewers"] += len(j_viewers) - db_vw
                logger.info(
                    "journalからの復元: session %d を復元しました（event +%d, viewer +%d）",
                    sid, len(j_events) - db_ev, len(j_viewers) - db_vw,
                )
        if summary["sessions"]:
            logger.info("journalからの復元が完了しました: %s", summary)
        self._prune_journal()
        return summary

    def _journal_files(self) -> list:
        journal_dir = Path(get_journal_dir())
        if not journal_dir.is_dir():
            return []
        files = list(journal_dir.glob("events-*.jsonl")) + list(journal_dir.glob("events-*.jsonl.gz"))
        return sorted(files)

    def _read_journal_file(self, path: Path, events_by_sid: dict, viewers_by_sid: dict) -> None:
        overlong = 0
        try:
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        row = tuple(rec["r"])
                        sid = row[0]
                    except Exception:
                        continue  # 壊れた行はskip(部分書き込み耐性)
                    if rec.get("t") == "e":
                        # journalのrowは位置固定なので、列を足した後は旧journalが短くなる。
                        # 不足分はNULL(=計装前で未計測)で埋める。値の捏造ではなく、当時
                        # 実際に観測していなかったことをそのまま表す。
                        if len(row) < len(_EVENTS_COLUMNS):
                            row = row + (None,) * (len(_EVENTS_COLUMNS) - len(row))
                        elif len(row) > len(_EVENTS_COLUMNS):
                            overlong += 1
                            continue
                        events_by_sid.setdefault(sid, []).append(row)
                    elif rec.get("t") == "v":
                        viewers_by_sid.setdefault(sid, []).append(row)
        except Exception:
            logger.exception(
                "journal file %s を読めませんでした", path,
                extra={"event": "storage.journal_read_failed", "ctx": {"path": str(path)}},
            )
        if overlong:
            # 列数がSCHEMAより多いjournal = 新しいTicTokが書いた記録を古い版が読んでいる。
            # 列の対応が決められないので復元しない(位置ずれのまま入れる方が有害)。
            logger.warning(
                "journal file %s に現行のevents schemaより列が多い event %d 行があります"
                "（現行は %d 列）この版では復元できません",
                path, overlong, len(_EVENTS_COLUMNS),
                extra={"event": "storage.journal_row_too_wide",
                       "ctx": {"path": str(path), "rows": overlong,
                               "columns": len(_EVENTS_COLUMNS)}},
            )

    def _prune_journal(self) -> None:
        days = get_journal_retention_days()
        if days <= 0:
            return
        cutoff = time.time() - days * 86400
        removed = 0
        for path in self._journal_files():
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except Exception:
                logger.exception("journal file %s を削除できませんでした", path)
        if removed:
            logger.info("journal fileを %d 件削除しました（%d 日より古いもの）", removed, days)

    def flush(self) -> None:
        """バッファ済み書き込みを同期的に確定する。未flushのeventを必要とする読み取り
        (comment抽出・export・Battle貢献の再構成・session確定)の直前に呼ぶ。"""
        self._drain()

    def add_event(self, session_id: int, entry: dict) -> None:
        user = entry.get("user") or {}
        # collectorが決めたidentity_keyをそのまま使う(空文字=身元不明も尊重する)。ここで
        # nicknameから再計算すると、表示用の "(unknown)" がkeyになり別人のeventが1
        # identityへ畳まれる。keyを持たないdict(逆引き補完前のentry等)だけ計算する。
        if "identity_key" in user:
            identity_key = user["identity_key"]
        else:
            identity_key = _identity_key(
                user.get("user_id"), user.get("unique_id"), user.get("nickname")
            )
        params = (
            session_id,
            entry["time"],
            entry.get("create_time"),
            entry["kind"],
            user.get("user_id"),
            user.get("unique_id"),
            user.get("nickname"),
            identity_key,
            user.get("avatar"),
            entry.get("text"),
            entry.get("comment"),
            entry.get("gift_name"),
            entry.get("repeat_count"),
            entry.get("diamonds"),
            entry.get("count"),
            entry.get("gift_image"),
            entry.get("gift_id"),
            user.get("fans_level") or 0,
            user.get("gifter_level") or 0,
            user.get("gifter_badge") or "",
            user.get("member_badge") or "",
            entry.get("emotes"),
            entry.get("enter_source"),
            entry.get("enter_type"),
            entry.get("enter_reason"),
            entry.get("follow_status"),
            entry.get("follower_count"),
            entry.get("is_subscriber"),
            entry.get("is_moderator"),
            entry.get("is_gift_giver"),
            entry.get("share_type"),
            entry.get("share_target"),
            entry.get("content_language"),
            entry.get("comment_tag"),
        )
        # DB bufferへ積む前に耐久journalへ追記する。プロセスがこの直後に死んでも、eventは
        # diskに残り起動時recoverで復元できる(paramsはeventsの行tupleそのもの)。
        self._journal_append("e", params)
        with self._buf_lock:
            self._event_buffer.append(params)
            if identity_key:
                self._pending_users.append((user, entry["time"], identity_key))
            if len(self._event_buffer) + len(self._viewer_buffer) >= _WRITE_BATCH_SIZE:
                self._flush_cond.notify()

    def add_viewer_sample(
        self,
        session_id: int,
        ts: float,
        create_time: Optional[float],
        viewers: int,
        total_viewers: Optional[int],
        anonymous: Optional[int],
    ) -> None:
        """RoomUserSeqの同接系列をnative cadenceで永続化する。退室eventは配信側が出さない
        ため、net流入(Δ同接)はこの系列でしか測れない。bucketの10s丸め・timeline上限では
        長時間配信の系列が欠落するので、生sampleを別表に残す。"""
        row = (session_id, ts, create_time, viewers, total_viewers, anonymous)
        self._journal_append("v", row)
        with self._buf_lock:
            self._viewer_buffer.append(row)
            if len(self._event_buffer) + len(self._viewer_buffer) >= _WRITE_BATCH_SIZE:
                self._flush_cond.notify()

    def add_contributor_samples(
        self, session_id: int, ts: float, create_time: Optional[float], rows: list
    ) -> None:
        """RoomUserSeqの上位貢献者snapshotを1 messageぶんまとめて保存する。rowsは
        {rank, score, user{user_id, unique_id, nickname, avatar}} のlist。
        呼び出し側が間引き済みである前提の低頻度書き込みなので、event/viewerのbatch writerは
        通さず同期で書く(writerのbuffer/journal形式を増やさない)。

        identity_keyは_identity_key(不変user_id -> unique_id -> nickname)で採るが、users表への
        upsertは行わない。この経路のuserにはLv/badgeが載っておらず、upsertすると空の属性で
        既存profileを触りにいく余地を作るだけだからである。"""
        if not rows:
            return
        params = []
        for row in rows:
            user = row.get("user") or {}
            params.append(
                (
                    session_id,
                    ts,
                    create_time,
                    row.get("rank"),
                    row.get("score"),
                    _identity_key(
                        user.get("user_id"), user.get("unique_id"), user.get("nickname")
                    )
                    or None,
                    user.get("user_id") or None,
                    user.get("unique_id") or None,
                    user.get("nickname") or None,
                    user.get("avatar") or None,
                )
            )
        with self._lock:
            self._conn.executemany(
                "INSERT INTO contributor_samples (session_id, time, create_time, rank, score,"
                " identity_key, user_id, user_unique_id, user_nickname, user_avatar)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                params,
            )
            self._conn.commit()

    def add_follower_sample(
        self, session_id: int, ts: float, create_time: Optional[float], follower_count: int
    ) -> None:
        """FollowEventが運ぶ配信者のfollower総数を1点記録する。値が動いた時だけ呼ぶ想定。"""
        with self._lock:
            self._conn.execute(
                "INSERT INTO follower_samples (session_id, time, create_time, follower_count)"
                " VALUES (?, ?, ?, ?)",
                (session_id, ts, create_time, follower_count),
            )
            self._conn.commit()
