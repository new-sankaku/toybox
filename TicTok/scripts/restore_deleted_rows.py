"""消えた行の退避(``row_trash``)を一覧し、元の表へ戻す。

DELETE triggerが積んだ退避行を人が読み、選び、戻すための口である。仕組みと対象表の
線引き・保持日数の根拠は :mod:`tictok.store.row_trash` に在る。

**退避が在っても戻す手段が無ければ意味が無い。** そのためのscriptで、行うことは2つだけ:

  一覧   何がいつ消えたかを表名と期間で絞って見る(既定の動作)
  復元   選んだ退避行を元の表へINSERTし直す(``--restore``)

**既に同じidの行が在れば戻さない。** 戻すつもりで現行の行を壊すのは、この仕組みが防ごうと
している事故そのものである。判定は退避行のPRIMARY KEYで行い、当たった行は理由付きで飛ばす。

**既定はdry-run。** ``--restore`` だけでは1行も書かず、何が戻せて何が戻せないかを出す。
``--apply`` を足したときにだけ実際に書き込む(``purge_streamers.py`` と同じ流儀)。

外部キーは有効にして戻す。参照先(録画・グループ)が既に消えている退避行は、孤児として
静かに入るのではなくその行だけが失敗し、理由が一覧に出る。戻すべきは先に親のほうである。

Usage (TicTok directory から venv で実行):
    python scripts/restore_deleted_rows.py
    python scripts/restore_deleted_rows.py --table bookmarks --since 2026-08-01
    python scripts/restore_deleted_rows.py --restore --table bookmarks --days 7
    python scripts/restore_deleted_rows.py --restore --id 41,42,43 --apply
"""

from __future__ import annotations

import argparse
import datetime
import logging
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tictok.core.config import get_db_path
from tictok.store import row_trash

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("restore_deleted_rows")

_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")


def _parse_time(text: str) -> float:
    """``--since`` / ``--until`` の時刻。書いた人のlocal timeとして読む。

    退避行の ``deleted_at`` はUTC基準のepoch秒だが、epochは絶対時刻なので基準の違いは
    ここで解ける。画面もlogもlocal timeで並ぶので、入力もそちらへ揃える。"""
    for fmt in _DATE_FORMATS:
        try:
            return time.mktime(time.strptime(text, fmt))
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"日時として読めません（{' / '.join(_DATE_FORMATS)}）: {text!r}")


def _stamp(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    # 参照先を失った行を孤児のまま入れない。戻す順序(親が先)を人へ返すための設定である。
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _summary(conn: sqlite3.Connection) -> None:
    rows = row_trash.counts_by_table(conn)
    if not rows:
        logger.info("退避された行はありません")
        return
    logger.info("表ごとの退避:")
    for row in rows:
        logger.info(
            "  %-24s %6d 件  %s 〜 %s",
            row["table_name"], row["rows"], _stamp(row["oldest"]), _stamp(row["newest"]))


def _show(rows: list) -> None:
    if not rows:
        logger.info("該当する退避行はありません")
        return
    logger.info("%-8s %-24s %-19s %s", "id", "表", "消えた時刻", "行")
    for row in rows:
        body = row["row_json"]
        if len(body) > 160:
            body = body[:157] + "..."
        logger.info("%-8d %-24s %-19s %s",
                    row["id"], row["table_name"], _stamp(row["deleted_at"]), body)


def _restore(conn: sqlite3.Connection, rows: list, apply: bool) -> int:
    restored = 0
    skipped = 0
    failed = 0
    for row in rows:
        # 1行ずつSAVEPOINTで包む。1件が親を失っていても、残りの復元は続けたい ——
        # 一括で巻き戻すと「どれが戻せたのか」を人がもう一度調べ直すことになる。
        conn.execute("SAVEPOINT restore_row")
        try:
            result = row_trash.restore_row(conn, row, apply=apply)
        except sqlite3.Error as exc:
            conn.execute("ROLLBACK TO restore_row")
            failed += 1
            logger.error("  id=%d %s: 戻せませんでした（%s: %s）",
                         row["id"], row["table_name"], type(exc).__name__, exc,
                         exc_info=True)
            continue
        finally:
            conn.execute("RELEASE restore_row")
        if result["ok"]:
            restored += 1
        else:
            skipped += 1
        note = ""
        if result["dropped_columns"]:
            note += f" / 今の表に無い列は捨てます: {', '.join(result['dropped_columns'])}"
        if result["missing_columns"]:
            note += f" / 退避に無い列はDEFAULT: {', '.join(result['missing_columns'])}"
        logger.info("  id=%-6d %-24s %-19s %s%s",
                    result["id"], result["table"], _stamp(result["deleted_at"]),
                    result["reason"], note)
    if apply:
        conn.commit()
    logger.info("%s %d 件 / 戻さなかった %d 件 / 失敗 %d 件",
                "戻した" if apply else "戻せる（dry-run）", restored, skipped, failed)
    return failed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", default=get_db_path(), help="対象のDB(既定は serverと同じ)")
    parser.add_argument("--table", help="表名で絞る")
    parser.add_argument("--since", type=_parse_time, help="この時刻以降に消えた行だけ")
    parser.add_argument("--until", type=_parse_time, help="この時刻より前に消えた行だけ")
    parser.add_argument("--days", type=float, help="直近N日に消えた行だけ(--sinceの略記)")
    parser.add_argument("--id", help="退避行のidを直接指定(カンマ区切り)")
    parser.add_argument("--limit", type=int, default=200, help="一覧の最大件数(既定200)")
    parser.add_argument("--restore", action="store_true", help="戻す(既定はdry-run)")
    parser.add_argument("--apply", action="store_true", help="実際に書き込む")
    args = parser.parse_args(argv)

    if args.table and args.table not in row_trash.ROW_TRASH_TABLES:
        logger.error("退避の対象ではない表です: %s（対象: %s）",
                     args.table, ", ".join(row_trash.ROW_TRASH_TABLES))
        return 2
    since = args.since
    if args.days is not None:
        # --days と --since を両方書いた場合は、狭いほう(新しいほう)を採る。
        floor = time.time() - args.days * 86400.0
        since = floor if since is None else max(since, floor)
    if args.apply and not args.restore:
        logger.error("--apply は --restore と一緒に指定してください")
        return 2

    conn = _connect(args.db)
    try:
        if args.id:
            wanted = {int(part) for part in args.id.split(",") if part.strip()}
            rows = [row for row in row_trash.list_rows(conn, table=args.table)
                    if row["id"] in wanted]
            unknown = wanted - {row["id"] for row in rows}
            if unknown:
                logger.error("退避行が見つかりません: %s",
                             ", ".join(str(i) for i in sorted(unknown)))
                return 2
        else:
            rows = row_trash.list_rows(
                conn, table=args.table, since=since, until=args.until,
                limit=None if args.restore else args.limit)
        if not args.restore:
            _summary(conn)
            _show(rows)
            return 0
        logger.info("戻す対象 %d 件%s", len(rows), "" if args.apply else "（dry-run）")
        failed = _restore(conn, rows, args.apply)
        return 1 if failed else 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
