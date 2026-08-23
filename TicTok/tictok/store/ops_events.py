"""ops_events(Layer2: 状態遷移のDB記録)。

境界の理由: 障害・lifecycleの記録は他の全domainから呼ばれる横断機能で、どのtableの
持ち物でもない。書き込み(record_ops_event)と読み出し(list/count/kinds)を同じ場所に
置くのは、絞り込み条件(_ops_events_filters)を一覧とbadgeで共有する必要があるため。

lock契約:
  _write_ops_event は自分で self._lock を取り、その区間内でcommitまで完結させる。
  したがって record_ops_event は lock を保持したまま呼んではならない(docstring参照)。
  _prune_ops_events_locked のみ lock 保持前提で、呼び出し元は Storage.__init__。
"""
import json
import logging
import time
from typing import Optional

from tictok.core.config import (
    get_ops_events_detail_max_chars,
    get_ops_events_query_limit,
    get_ops_events_retention_days,
)
from tictok.core.logctx import current_context

from tictok.store._common import OPS_INFO, OPS_SEVERITY_ORDER, _OPS_LOG_LEVELS, logger


class OpsEventsMixin:
    """ops_events(Layer2: 状態遷移のDB記録)。

    lockもDB接続も持たない。すべて Storage が所有する self._conn /
    self._lock / _read_connection() を借りる(mixinとして Storage に混ぜられる前提)。
    契約の詳細はmodule docstringを参照。
    """

    # ----- ops_events(Layer2: 状態遷移のDB記録) ----------------------------------------

    def record_ops_event(
        self,
        log: logging.Logger,
        kind: str,
        message: str,
        *,
        severity: str = OPS_INFO,
        unique_id=None,
        session_id=None,
        recording_id=None,
        job_id=None,
        duration_ms=None,
        detail: Optional[dict] = None,
        exc_info=False,
    ) -> str:
        """状態遷移をlog(Layer1)とops_events表(Layer2)へ1回の呼び出しで両方記録する。

        logger引数が必須なのは意図的である。この関数の中で getLogger("tictok.storage") を
        使うと、collectorやrecorderの状態遷移まで全てstorage名義のlogになり、module別に
        logを抽出する運用が壊れる。呼び出し元は自分のmodule loggerを渡すこと。

        Layer1のeventとLayer2のkindには同一文字列が入る(別名を作らない)。両者はops_idで
        結合でき、job_idは焼き込みやupscaleのようにsub-process/worker threadを跨ぐ処理の
        log群とops_eventsを突き合わせるための鍵になる。

        相関ID(unique_id/session_id/recording_id)はLayer1には自動注入されるが、DBの列には
        値そのものが要るのでcurrent_context()から補う。明示引数が渡された場合はそちらを優先
        する(contextの外、例えばworker threadから呼ぶ場合)。

        DB書き込みの失敗は本流を止めない。ただし無音にもせず、最初の1件をerrorで出した上で
        累計をcloseで必ず報告する。self._lockを取るので、lockを保持したまま呼ばないこと。
        """
        level = _OPS_LOG_LEVELS.get(severity)
        if level is None:
            raise ValueError(f"unknown ops severity: {severity!r}")
        ops_id = f"{self._ops_run_token}-{next(self._ops_seq)}"
        bound = current_context()
        unique_id = bound.get("unique_id") if unique_id is None else unique_id
        session_id = bound.get("session_id") if session_id is None else session_id
        recording_id = bound.get("recording_id") if recording_id is None else recording_id

        log_ctx = dict(detail or {})
        log_ctx["ops_id"] = ops_id
        if job_id is not None:
            log_ctx["job_id"] = job_id
        if duration_ms is not None:
            log_ctx["duration_ms"] = duration_ms
        log.log(level, message, extra={"event": kind, "ctx": log_ctx}, exc_info=exc_info)

        self._write_ops_event(
            ops_id, kind, severity, message, unique_id, session_id,
            recording_id, job_id, duration_ms, detail,
        )
        self._notify_ops_observer(kind, severity, message, unique_id, detail)
        return ops_id

    def set_ops_observer(self, observer) -> None:
        """ops_eventが記録されるたびに呼ばれるcallbackを1つ登録する(通知機構用)。

        DB書き込みの後に呼ぶ。順序を逆にすると、通知は届いたのに運用logにその行が無いという
        状態が起こり得る。
        """
        self._ops_observer = observer

    def _notify_ops_observer(self, kind, severity, message, unique_id, detail) -> None:
        """観測者へ配る。record_ops_eventはあらゆるthreadから、しばしば障害処理の最中に
        呼ばれるので、観測者側の失敗を呼び出し元へ返さない。通知が落ちても記録は残る。"""
        observer = self._ops_observer
        if observer is None:
            return
        try:
            observer(kind, severity, message, unique_id, detail)
        except Exception:
            logger.exception(
                "ops eventのobserverが失敗しました（event自体は記録済み, kind=%s）", kind,
                extra={"event": "storage.ops_observer_failed", "ctx": {"kind": kind}},
            )

    def _write_ops_event(self, ops_id, kind, severity, message, unique_id,
                         session_id, recording_id, job_id, duration_ms, detail) -> None:
        """ops_events表への1行INSERT。障害の記録が障害を増やしてはならないので、あらゆる例外を
        捕まえて呼び出し元へ返さない。代わりに失敗数を数え、close()が必ず1行報告する。"""
        try:
            payload = self._ops_detail_json(detail)
            with self._lock:
                self._conn.execute(
                    "INSERT INTO ops_events (ops_id, ts, kind, severity, message, unique_id,"
                    " session_id, recording_id, job_id, duration_ms, detail)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (ops_id, time.time(), kind, severity, message,
                     str(unique_id) if unique_id is not None else None,
                     session_id, recording_id,
                     str(job_id) if job_id is not None else None,
                     duration_ms, payload),
                )
                self._conn.commit()
        except Exception:
            with self._ops_fail_lock:
                self._ops_write_failures += 1
                first = not self._ops_first_failure_logged
                self._ops_first_failure_logged = True
            if first:
                # 2件目以降は数えるだけにする。DBが落ちている間は全ops eventが失敗するため、
                # 毎回出すと本来診断したいlogを押し流す。累計はcloseで必ず出る。
                logger.error(
                    "ops eventをDBへ保存できませんでした（logの出力は続行, kind=%s）", kind,
                    exc_info=True,
                    extra={"event": "storage.ops_event_write_failed",
                           "ctx": {"ops_id": ops_id, "kind": kind, **self._db_space_ctx()}},
                )

    def _ops_detail_json(self, detail) -> str:
        """detailをJSON化する。想定外に大きなpayload(ffmpegのstderr全文等)でops_eventsが
        DB最大の表になるのを防ぐため上限で切るが、切ったこと自体を行に残して黙らせない。"""
        if not detail:
            return "{}"
        text = json.dumps(detail, ensure_ascii=False, default=str)
        limit = get_ops_events_detail_max_chars()
        if len(text) > limit:
            return json.dumps(
                {"truncated_chars": len(text) - limit, "detail": text[:limit]},
                ensure_ascii=False,
            )
        return text

    def _prune_ops_events_locked(self) -> int:
        """保持期間を過ぎたops_eventsを削除する(起動時1回)。lock保持前提、commitは呼び出し元。"""
        days = get_ops_events_retention_days()
        if days <= 0:
            return 0
        cursor = self._conn.execute(
            "DELETE FROM ops_events WHERE ts < ?", (time.time() - days * 86400,)
        )
        return max(cursor.rowcount, 0)

    @staticmethod
    def _like_prefix(text: str) -> str:
        """LIKEのmeta文字を無効化した前方一致pattern。ESCAPE句と対で使う。kindは
        'process.settings_updated' のように '_' を含むので、escapeしないと '_' が
        任意1文字として当たり、別kindを巻き込む。"""
        escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return escaped + "%"

    def _ops_events_filters(self, *, severity: Optional[str], kind: Optional[str],
                            kind_prefix: Optional[str], unique_id: Optional[str],
                            session_id: Optional[int], job_id: Optional[str],
                            since: Optional[float], until: Optional[float],
                            min_severity: Optional[str] = None) -> tuple:
        """list/countで同一の絞り込みを組む。両者で条件がずれるとbadgeの件数と一覧の
        件数が食い違うため、SQLの組み立ては1箇所に置く。"""
        clauses = []
        params: list = []
        if min_severity is not None:
            # 「warning以上」の閾値指定。severity列は文字列で大小比較ができないため、
            # 重大度の順序(OPS_SEVERITY_ORDER)から該当する値を並べてINで引く。
            if min_severity not in OPS_SEVERITY_ORDER:
                raise ValueError(f"unknown ops severity: {min_severity!r}")
            levels = OPS_SEVERITY_ORDER[OPS_SEVERITY_ORDER.index(min_severity):]
            clauses.append(f"o.severity IN ({','.join('?' * len(levels))})")
            params.extend(levels)
        for column, value in (("o.severity", severity), ("o.kind", kind),
                              ("o.unique_id", unique_id), ("o.session_id", session_id),
                              ("o.job_id", job_id)):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        if kind_prefix:
            clauses.append("o.kind LIKE ? ESCAPE '\\'")
            params.append(self._like_prefix(kind_prefix))
        if since is not None:
            clauses.append("o.ts >= ?")
            params.append(since)
        if until is not None:
            clauses.append("o.ts <= ?")
            params.append(until)
        return clauses, params

    def list_ops_events(self, *, limit: Optional[int] = None, severity: Optional[str] = None,
                        kind: Optional[str] = None, kind_prefix: Optional[str] = None,
                        unique_id: Optional[str] = None, session_id: Optional[int] = None,
                        job_id: Optional[str] = None, since: Optional[float] = None,
                        until: Optional[float] = None, offset: int = 0,
                        before_ts: Optional[float] = None,
                        before_id: Optional[int] = None,
                        min_severity: Optional[str] = None) -> list:
        """画面表示用の一覧。sessions/recordingsはLEFT JOINで引く: ops_eventsはFKを張らず
        session削除後も残るため、INNER JOINだと障害当時の行が消えて見える。

        ページングはkeyset(before_ts + before_id)を既定にする。この表は末尾に行が増え続けるので、
        OFFSETだと読み込み中に新しい行が入るたび境界の行が重複・欠落する。offsetも受けるが、
        keysetを指定したときはそちらを優先する。

        limitはNoneのときだけ設定値の既定を使う。0以下は拒否する: SQLiteはLIMIT -1を
        「無制限」と解釈するため、素通しすると1requestでops_events全件を読み込んでしまう。
        全件取得はこの一覧の契約に無い。"""
        if limit is not None:
            limit = int(limit)
            if limit <= 0:
                raise ValueError(f"limitは1以上を指定してください: {limit}")
        clauses, params = self._ops_events_filters(
            severity=severity, kind=kind, kind_prefix=kind_prefix, unique_id=unique_id,
            session_id=session_id, job_id=job_id, since=since, until=until,
            min_severity=min_severity,
        )
        keyset = before_ts is not None and before_id is not None
        if keyset:
            # tsは同値が並び得る(同一ops_idの連続記録)ので、idを第2 keyにして順序を確定させる。
            clauses.append("(o.ts < ? OR (o.ts = ? AND o.id < ?))")
            params.extend([before_ts, before_ts, before_id])
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit if limit is not None else get_ops_events_query_limit())
        tail = " LIMIT ?"
        if not keyset and offset:
            tail += " OFFSET ?"
            params.append(int(offset))
        with self._lock:
            rows = self._conn.execute(
                "SELECT o.*, s.unique_id AS session_unique_id, s.started_at AS session_started_at,"
                " s.status AS session_status, r.filename AS recording_filename,"
                " r.status AS recording_status"
                " FROM ops_events o"
                " LEFT JOIN sessions s ON s.id = o.session_id"
                " LEFT JOIN recordings r ON r.id = o.recording_id"
                f"{where} ORDER BY o.ts DESC, o.id DESC{tail}",
                tuple(params),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            try:
                item["detail"] = json.loads(item.get("detail") or "{}")
            except ValueError:
                # 行を落とすより、読めなかった生文字列をそのまま見せる方が診断に足る。
                item["detail"] = {"unparsed": item.get("detail")}
            items.append(item)
        return items

    def count_ops_events_by_severity(self, *, since: Optional[float] = None,
                                     until: Optional[float] = None,
                                     kind_prefix: Optional[str] = None) -> dict:
        """severity別の件数。header badge用にCOUNT(*)だけを引く軽量query(一覧を取って
        数えると1画面ぶんの上限に切られて件数が嘘になる)。"""
        clauses, params = self._ops_events_filters(
            severity=None, kind=None, kind_prefix=kind_prefix, unique_id=None,
            session_id=None, job_id=None, since=since, until=until,
        )
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT o.severity AS severity, COUNT(*) AS n FROM ops_events o{where}"
                " GROUP BY o.severity",
                tuple(params),
            ).fetchall()
        return {row["severity"]: row["n"] for row in rows}

    def ops_event_kinds(self, *, since: Optional[float] = None) -> list:
        """記録されているkindの一覧(件数付き)。filterの候補をhard-codeせず実データから出す。"""
        clauses, params = self._ops_events_filters(
            severity=None, kind=None, kind_prefix=None, unique_id=None,
            session_id=None, job_id=None, since=since, until=None,
        )
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT o.kind AS kind, COUNT(*) AS n FROM ops_events o{where}"
                " GROUP BY o.kind ORDER BY o.kind",
                tuple(params),
            ).fetchall()
        return [{"kind": row["kind"], "count": row["n"]} for row in rows]

    def ops_event_unique_ids(self, *, since: Optional[float] = None) -> list:
        """記録に出てくる配信者の一覧(件数付き)。配信者filterの候補に使う。

        配信者一覧(streamer_index)ではなくops_events自身から引く。監視を外した配信者の
        障害記録は残り続けるので、一覧側から候補を作ると「表には居るのに選べない」行が出る。"""
        clauses, params = self._ops_events_filters(
            severity=None, kind=None, kind_prefix=None, unique_id=None,
            session_id=None, job_id=None, since=since, until=None,
        )
        clauses.append("o.unique_id IS NOT NULL AND o.unique_id <> ''")
        where = " WHERE " + " AND ".join(clauses)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT o.unique_id AS unique_id, COUNT(*) AS n FROM ops_events o{where}"
                " GROUP BY o.unique_id ORDER BY o.unique_id",
                tuple(params),
            ).fetchall()
        return [{"unique_id": row["unique_id"], "count": row["n"]} for row in rows]
