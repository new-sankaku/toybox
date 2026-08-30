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
    _value_for_intern,
    _EVENT_STRING_CACHE_MAX,
    _EVENTS_COLUMNS,
    _INTERN_PHASE_CONTRACT,
    _INTERN_PHASE_EXPAND,
    _VIEWERS_INSERT_SQL,
    _WRITE_BATCH_SIZE,
    _WRITE_FLUSH_INTERVAL_SECONDS,
    _identity_key,
    _interned_event_positions,
    _session_ids_of,
    _string_hash,
    logger,
)


# journalの件数cacheの版。行の読み方(_iter_journal_rows)を変えて件数が動きうるときに
# 上げる。上げるとcacheは丸ごと無効になり、次の起動が頭から数え直す。
_COUNT_CACHE_VERSION = 1


class IngestMixin:
    """取り込み経路(batch writer / 耐久journal / event投入)。

    lockもDB接続も持たない。すべて Storage が所有する self._conn /
    self._lock / _read_connection() を借りる(mixinとして Storage に混ぜられる前提)。
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

    # ----- 重複文字列のintern(生の値 -> event_strings.id) -------------------------------
    # bufferとjournalは生の文字列を運び、idへの差し替えはここ — 書き出し直前のlock区間 —
    # でだけ起きる。journalに生値を残すのは意図的で、そうしないと旧形式のjournalをreplayした
    # ときにURL文字列がINTEGER列へ黙って入り(SQLiteは動的型)、以後JOINが一致せずavatarが
    # 静かに消える。生値のままなら、今後intern対象の列を増やしてもjournalは無傷である。

    def _intern_values_locked(self, values: set) -> None:
        """未知の値を event_strings へ確定させ、cacheへ載せる。self._lock保持前提。

        1 event毎に別queryを出さないため、batch全体ぶんを1度にまとめて引く。DBへ行くのは
        cache未hitぶんだけで、実測は1 batch(50行)あたり mean 11.98 / p95 28件。

        新しいidは自分で採番する。INSERTのたびにlast_insert_rowidを取りに戻ると、新規の
        件数ぶん往復が増えるためである。採番が競合しないのは、この接続へ書く経路
        (batch writer / 隔離書き込み / journal復元 / migration)がすべて self._lock の
        内側にあるからで、writerは常に1つしか居ない。
        """
        if not values:
            return
        if self._next_string_id is None:
            self._next_string_id = self._conn.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 FROM event_strings").fetchone()[0]
        cache = self._string_cache
        hashes = sorted({_string_hash(value) for value in values})
        # SQLiteの変数上限へ触れないよう分けて引く。
        for i in range(0, len(hashes), 400):
            chunk = hashes[i:i + 400]
            placeholders = ",".join("?" * len(chunk))
            for row in self._conn.execute(
                f"SELECT id, value FROM event_strings WHERE hash IN ({placeholders})", chunk
            ):
                # hashで絞ってから value を実比較する。hashが衝突しても、別の値を同じidへ
                # 畳むことはない(衝突の可能性を確率で無視しているのではない)。
                if row["value"] in values:
                    cache[row["value"]] = row["id"]
        fresh = [value for value in values if value not in cache]
        if not fresh:
            return
        rows = []
        for value in fresh:
            rows.append((self._next_string_id, _string_hash(value), value))
            cache[value] = self._next_string_id
            self._next_string_id += 1
        self._conn.executemany(
            "INSERT INTO event_strings (id, hash, value) VALUES (?, ?, ?)", rows)

    def _intern_forget_after_rollback(self) -> None:
        """rollbackでevent_stringsへのINSERTが巻き戻った後、cacheを捨てて採番を採り直す。

        巻き戻ったidをcacheが持ったままだと、以後のeventが**存在しないidを参照する**行に
        なり、JOINが一致せずavatarとbadgeが静かに消える。どのidが巻き戻ったかを追わずに
        丸ごと捨てるのは、rollbackが失敗経路でしか起きないためで、hit率を惜しむ場面ではない
        (再構築は次のbatchが引き直すだけで済む)。
        """
        self._string_cache.clear()
        self._next_string_id = None

    def _event_rows_for_insert_locked(self, rows: list) -> list:
        """buffer/journalの生の行を、今の段階のDB列順へ組み替える。self._lock保持前提。

        EXPANDでは旧列とid列の両方へ書く(行は3つ長くなる)。読み出し側は書き換え済みの
        箇所も未着手の箇所も同じ答えを得るので、両者が共存できる。CONTRACTでは旧列がもう
        無いので、生の値の位置をidへ差し替えて同じ幅で書く。

        **渡されたrowsは書き換えない。** 失敗時に_drainが再キューするのはこの生の行で、
        ここで潰すと再試行がidだけの行を旧列へ入れにいく。
        """
        if self._intern_phase < _INTERN_PHASE_EXPAND or not rows:
            return rows
        positions = self._interned_positions
        columns = self._interned_columns
        cache = self._string_cache
        missing = set()
        for row in rows:
            for pos, column in zip(positions, columns):
                # 保存する値はここで決まる。avatarは署名queryを落とす(_common.py参照)。
                # 生の行そのものは書き換えない — 失敗時に_drainが再キューするのはこの行で、
                # journalにも生値のまま残す約束がある。
                value = _value_for_intern(column, row[pos])
                if value is not None and value not in cache:
                    missing.add(value)
        self._intern_values_locked(missing)
        if len(cache) > _EVENT_STRING_CACHE_MAX:
            # 上限は「際限なく伸びない」ための天井で、hit率のためではない(_common.py参照)。
            # 捨て方は_USER_CACHE_MAXに揃える — 挿入順の古い方から1/4。
            for stale in list(cache)[:_EVENT_STRING_CACHE_MAX // 4]:
                del cache[stale]
        contract = self._intern_phase >= _INTERN_PHASE_CONTRACT
        out = []
        for row in rows:
            ids = tuple(
                None if row[pos] is None else cache[_value_for_intern(column, row[pos])]
                for pos, column in zip(positions, columns))
            if contract:
                new = list(row)
                for pos, value in zip(positions, ids):
                    new[pos] = value
                out.append(tuple(new))
            else:
                # EXPANDでは旧列とid列の両方へ書く。**旧列にも正規化後の値を入れる** —
                # 生のURLを旧列に残すと、旧列を読む箇所とJOINで読む箇所が違う答えを返し、
                # 「両者が同じ答えを得る」というEXPANDの存在理由が崩れる。
                new = list(row)
                for pos, column in zip(positions, columns):
                    new[pos] = _value_for_intern(column, row[pos])
                out.append(tuple(new) + ids)
        return out

    def _write_batch_locked(self, events: list, viewers: list, users: list) -> None:
        """高速経路: event/viewerをexecutemanyで一括INSERTし、userを1件ずつupsertする。
        self._lock保持前提。commitは呼び出し元(_drain)が行う。"""
        if events:
            self._conn.executemany(
                self._events_insert_sql, self._event_rows_for_insert_locked(events))
        if viewers:
            self._conn.executemany(_VIEWERS_INSERT_SQL, viewers)
        self._upsert_users_locked(users)

    def _write_isolating_locked(self, events: list, viewers: list, users: list) -> None:
        """隔離経路: batch INSERTがIntegrityErrorで失敗した後、1行ずつINSERTし直す。
        呼び出し前にrollback済み(部分INSERTは巻き戻し済み)であること。IntegrityErrorの行だけ
        dead-letterへ退避してdropし、残りは確定させる。OperationalError(一時障害)は隔離せず
        上位へ送出して全体再キューさせる。"""
        # 隔離はrollbackの後から始まる。直前のbatchでevent_stringsへ入れたidも巻き戻って
        # いるので、cacheを捨ててから引き直す(でないと存在しないidを参照する行を書く)。
        self._intern_forget_after_rollback()
        bad_events = self._insert_rows_isolating(
            self._events_insert_sql, self._event_rows_for_insert_locked(events), events)
        bad_viewers = self._insert_rows_isolating(_VIEWERS_INSERT_SQL, viewers, viewers)
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

    def _insert_rows_isolating(self, sql: str, rows: list, raw_rows: list) -> list:
        """rowsを1行ずつINSERTし、IntegrityErrorの行だけを返して隔離対象にする。
        OperationalError(一時障害)はそのまま送出し、上位で全体rollback+再キューさせる。

        raw_rowsは同じ並びの「intern前の行」。**返すのはこちらである。** dead-letterは人が
        読んで手で復旧するfileなので、event_stringsのidだけを書き出しても復旧材料にならない
        (idの指す先はrollbackで消えていることもある)。
        """
        bad: list = []
        for row, raw in zip(rows, raw_rows):
            try:
                self._conn.execute(sql, row)
            except sqlite3.IntegrityError:
                bad.append(raw)
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
        # event_stringsへのINSERTも巻き戻っている。cacheに残すと、再キューした行が次の
        # 周期で存在しないidを参照して書かれる。
        self._intern_forget_after_rollback()
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
        置換後はstats_json/buckets/analytics cacheをeventから再構成する。

        journalは2 passで読む。1 pass目(_count_journal_rows)はsession別の件数だけを数え、
        2 pass目(_collect_journal_rows)は復元が要るsessionの行だけを組み立てる。復元の
        要否はDBの行数との比較だけで決まるので、通常の起動 — 復元が1件も要らない起動 —
        で保持期間ぶんの記録を行に開く理由が無い(実測でjournalは568MB/15日ぶん)。
        pruneは最後のまま動かさない: 先に回すと、保持期間を過ぎたfileが、この起動で
        復元に寄与しないまま消える(本来復元できたeventを失う経路になる)。"""
        summary = {"sessions": 0, "events": 0, "viewers": 0}
        if not self._journal_enabled:
            return summary
        # 2つのpassは同じfile集合を読む(間にpruneを挟まない)。
        paths = self._journal_files()
        event_counts, viewer_counts = self._count_journal_rows(paths)
        candidates = self._journal_restore_candidates(event_counts, viewer_counts)
        if not candidates:
            self._prune_journal()
            return summary
        events_by_sid, viewers_by_sid = self._collect_journal_rows(
            paths, wanted=candidates, limits=(event_counts, viewer_counts)
        )
        with self._lock:
            for sid in sorted(candidates):
                j_events = events_by_sid.get(sid, [])
                j_viewers = viewers_by_sid.get(sid, [])
                # 判断はDELETEと同じlock区間で取り直す。候補選びは「行を組み立てる価値が
                # あるか」を件数で見ただけで、その後にDBが動いていない保証は無い。
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
                        # journalは生の文字列を運ぶ。書き出し経路と同じ名寄せを必ず通す
                        # (通さないとURL文字列がINTEGER列へ黙って入り、avatarが消える)。
                        self._conn.executemany(
                            self._events_insert_sql,
                            self._event_rows_for_insert_locked(j_events))
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
                    self._intern_forget_after_rollback()
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

    def _journal_restore_candidates(self, event_counts: dict, viewer_counts: dict) -> set:
        """行を組み立てる価値があるsessionのidを、件数だけで絞り込む。

        ここは「2 pass目を走らせるか」を決める門であって、復元の可否ではない。実際に
        DELETE→全置換してよいかは、置換と同じlock区間でDBを見直して決める
        (lockを跨いだ判断は、その間にDBが動けば古くなる)。門は緩い側へ倒してある —
        件数が不整合なsessionもここは通り、警告と見送りは置換側が行う。
        """
        candidates: set = set()
        with self._lock:
            for sid in sorted(set(event_counts) | set(viewer_counts)):
                if self._conn.execute(
                    "SELECT 1 FROM sessions WHERE id = ?", (sid,)
                ).fetchone() is None:
                    continue  # 削除済み/未作成: resurrectしない
                db_ev = self._conn.execute(
                    "SELECT COUNT(*) c FROM events WHERE session_id = ?", (sid,)
                ).fetchone()["c"]
                db_vw = self._conn.execute(
                    "SELECT COUNT(*) c FROM viewer_samples WHERE session_id = ?", (sid,)
                ).fetchone()["c"]
                if (db_ev < event_counts.get(sid, 0)
                        or db_vw < viewer_counts.get(sid, 0)):
                    candidates.add(sid)
        return candidates

    def _journal_files(self) -> list:
        journal_dir = Path(get_journal_dir())
        if not journal_dir.is_dir():
            return []
        files = list(journal_dir.glob("events-*.jsonl")) + list(journal_dir.glob("events-*.jsonl.gz"))
        return sorted(files)

    def _iter_journal_rows(self, path: Path, log_anomalies: bool = True,
                           start_offset: int = 0, progress: Optional[list] = None):
        """journal file 1本を ``(kind, session_id, row)`` で流す。kindは 'e' / 'v'。

        **行の読み方をここ1箇所にしか置かないことがこのmethodの目的である。** 復元するか
        否かは件数を数えるpass(_count_journal_rows)が決め、実際にDELETE→全置換するのは
        行を組み立てるpass(_collect_journal_rows)なので、両者の解釈 — 壊れた行のskip、
        events行の幅の正規化 — が少しでも食い違うと、件数で下した判断と書き戻す中身が
        ずれる。別々に書けば、片方だけ直った瞬間に静かにeventが失われる。

        log_anomalies=False は2 pass目のため。同じfileの同じ異常を二度は報告しない。

        binaryで開いてbyte列のままjson.loadsへ渡す。text modeのdecodeは行の解釈に何も
        足さないうえ、実測でこのloopの1/4を占めていた(350MBで1.4s)。壊れたbyte列は
        json.loadsが弾くので、部分書き込みの扱いは行単位のskipのまま変わらない
        (text modeでは行の取り出しそのものが例外になり、file 1本を丸ごと諦めていた)。

        start_offset/progress は数え直しを避けるためのもの(_count_journal_rows)。
        start_offset は**行頭でなければならない**。progressは ``[位置, 再開してよいか]``
        の2要素listで、progress[0] へ「次に再開してよい位置」= 最後に読み切った行の直後の
        byte位置を書く。改行で終わっていないfile末尾(書き込み中に落ちた行)に当たったときは
        その行を返したうえで progress[1] を False にする — 返した行を位置に含められない
        以上、そのfileは続きから数えてはならない(同じ行を二度数えることになる)。返すこと
        自体は変えない。ここで落とすと、DBから欠けた最後の1件が復元されなくなる。
        """
        overlong = 0
        consumed = start_offset
        try:
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(path, "rb") as fh:
                if start_offset:
                    fh.seek(start_offset)
                for raw in fh:
                    if raw.endswith(b"\n"):
                        consumed += len(raw)
                        if progress is not None:
                            progress[0] = consumed
                    elif progress is not None:
                        progress[1] = False
                    line = raw.strip()
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
                        yield "e", sid, row
                    elif rec.get("t") == "v":
                        yield "v", sid, row
        except Exception:
            logger.exception(
                "journal file %s を読めませんでした", path,
                extra={"event": "storage.journal_read_failed", "ctx": {"path": str(path)}},
            )
        if overlong and log_anomalies:
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

    def _count_journal_rows(self, paths: list) -> tuple:
        """session別の件数だけを数える(``(events, viewers)`` の2 dict)。

        行そのものは持たない。復元が要るかどうかはDBの行数との比較だけで決まるので、
        通常の起動 — 復元が1件も要らない起動 — で保持期間ぶんの記録をmemoryへ載せる
        必要はない(実測で journal は 568MB / 15日ぶんあり、行に開くとその数倍になる)。

        数えた結果は ``_count_cache_path`` へ「どこまで数えたか(byte位置)」付きで残し、
        次の起動はその続きだけを数える。journalは追記onlyなので、既に数えた区間の
        件数は二度と変わらない。cacheが無い/合わない場合は頭から数え直すだけで、
        出る数は同じである(全走査との一致は起動ごとに確かめられる類のものではないため、
        導入時に実journal 350MBで突き合わせて確認してある)。

        これが要るのは、数える対象が保持期間ぶん全部で、しかも起動のたびに同じ数字を
        出し直していたため(実測で毎起動6〜10秒、37回中で実際に復元が要ったのは1回)。
        """
        cache = self._load_count_cache()
        entries: dict = {}
        events: dict = {}
        viewers: dict = {}
        for path in paths:
            size = path.stat().st_size
            prev = cache.get(path.name)
            # .gz(回転済み)は追記されないので、途中から数える意味が無い。しかもoffsetは
            # 展開後のbyte数でfile sizeとは別物なので、指紋はsize一致にする。
            resumable = path.suffix != ".gz"
            if prev is None:
                usable = False
            elif resumable:
                # 追記onlyなので、数えた位置までの中身は変わらない。位置よりfileが短い =
                # 前提が崩れている(別のfileに置き換わった)ので使わない。
                usable = prev["offset"] <= size
            else:
                usable = prev["size"] == size
            counts = {"e": dict(prev["e"]), "v": dict(prev["v"])} if usable else {"e": {}, "v": {}}
            start = prev["offset"] if usable else 0
            progress = [start, True]
            if not usable or (resumable and start < size):
                for kind, sid, _row in self._iter_journal_rows(
                    path, start_offset=start, progress=progress
                ):
                    bucket = counts[kind]
                    bucket[sid] = bucket.get(sid, 0) + 1
            if progress[1]:
                entries[path.name] = {"offset": progress[0], "size": size,
                                      "e": counts["e"], "v": counts["v"]}
            # progress[1]がFalse = 書きかけの行が末尾に在る。その行は数に入れてあるが位置
            # には含められないので、このfileはcacheへ残さない(次回は頭から数える)。cacheの
            # 有無で件数が変わらないことの方が、1 fileぶんの走査より重い。
            for sid, n in counts["e"].items():
                events[sid] = events.get(sid, 0) + n
            for sid, n in counts["v"].items():
                viewers[sid] = viewers.get(sid, 0) + n
        self._save_count_cache(entries)
        return events, viewers

    def _count_cache_path(self) -> Path:
        return Path(get_journal_dir()) / "count_cache.json"

    def _load_count_cache(self) -> dict:
        """file名 -> {"offset": int, "size": int, "e": {sid: n}, "v": {sid: n}} を返す。

        読めない・版が違う・形が違うなら空を返す(=全部数え直す)。cacheはjournalそのもの
        から作り直せる派生物なので、疑わしければ捨てる方を既定にしてある。
        """
        try:
            raw = json.loads(self._count_cache_path().read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except Exception:
            logger.exception(
                "journalの件数cacheを読めませんでした。数え直します",
                extra={"event": "storage.journal_count_cache_unreadable"},
            )
            return {}
        if not isinstance(raw, dict) or raw.get("version") != _COUNT_CACHE_VERSION:
            return {}
        out = {}
        for name, entry in (raw.get("files") or {}).items():
            try:
                out[name] = {
                    "offset": int(entry["offset"]),
                    "size": int(entry["size"]),
                    # JSONのkeyは文字列になるのでsession_idへ戻す。
                    "e": {int(k): int(v) for k, v in entry["e"].items()},
                    "v": {int(k): int(v) for k, v in entry["v"].items()},
                }
            except Exception:
                return {}
        return out

    def _save_count_cache(self, entries: dict) -> None:
        """数えた結果を書き出す。best-effort(失敗しても起動は続ける)。

        entriesには今回見たfileしか入らないので、pruneで消えたfileの行はここで落ちる。
        """
        payload = {
            "version": _COUNT_CACHE_VERSION,
            "files": {
                name: {"offset": entry["offset"], "size": entry["size"],
                       "e": {str(k): v for k, v in entry["e"].items()},
                       "v": {str(k): v for k, v in entry["v"].items()}}
                for name, entry in entries.items()
            },
        }
        path = self._count_cache_path()
        tmp = path.with_suffix(".json.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(path)
        except Exception:
            logger.exception(
                "journalの件数cacheを書けませんでした",
                extra={"event": "storage.journal_count_cache_write_failed"},
            )

    def _collect_journal_rows(self, paths: list, wanted=None, limits=None) -> tuple:
        """復元に使う行を組み立てる(``(events_by_sid, viewers_by_sid)``)。

        wantedを渡すとそのsessionぶんだけを持つ。limitsは ``(events, viewers)`` の件数
        dictで、session毎の取り込み上限になる。上限を置くのは、数えたあとにjournalが
        伸びる可能性があるため: journalは追記のみなので数えた行は先頭から同じ順で
        現れるが、後から増えた行まで拾うと「件数で下した判断」より多くを書き戻す
        ことになる。
        """
        events_by_sid: dict = {}
        viewers_by_sid: dict = {}
        event_limits, viewer_limits = limits if limits is not None else (None, None)
        for path in paths:
            for kind, sid, row in self._iter_journal_rows(path, log_anomalies=False):
                if wanted is not None and sid not in wanted:
                    continue
                if kind == "e":
                    bucket, cap = events_by_sid, event_limits
                else:
                    bucket, cap = viewers_by_sid, viewer_limits
                rows = bucket.setdefault(sid, [])
                if cap is not None and len(rows) >= cap.get(sid, 0):
                    continue
                rows.append(row)
        return events_by_sid, viewers_by_sid

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
            entry.get("extra"),
            entry.get("message_id"),
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
        # avatarはeventsと同じ event_strings へ相乗りする(実測 141,708行 / 39.1MB /
        # distinct 21,689)。この経路はbatch writerを通らないので、旧列との併記(EXPAND)は
        # 要らない — 読み手が1つも無い表なので、書き換えを待つ相手が居ないためである。
        avatar_pos = 9
        with self._lock:
            interned = self._intern_phase >= _INTERN_PHASE_EXPAND
            if interned:
                self._intern_values_locked(
                    {v for v in (_value_for_intern("user_avatar", p[avatar_pos])
                                 for p in params) if v is not None})
                cache = self._string_cache
                params = [
                    p[:avatar_pos]
                    + (None if p[avatar_pos] is None
                       else cache[_value_for_intern("user_avatar", p[avatar_pos])],)
                    for p in params
                ]
            column = "user_avatar_id" if interned else "user_avatar"
            try:
                self._conn.executemany(
                    "INSERT INTO contributor_samples (session_id, time, create_time, rank,"
                    f" score, identity_key, user_id, user_unique_id, user_nickname, {column})"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    params,
                )
                self._conn.commit()
            except Exception:
                # commitできなかった以上、直前にevent_stringsへ入れたidも確定していない。
                # cacheに残すと以後の行が存在しないidを参照する。
                self._intern_forget_after_rollback()
                raise

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
