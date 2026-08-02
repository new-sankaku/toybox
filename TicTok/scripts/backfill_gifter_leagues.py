"""過去のギフター全員を、リーグ取得の待ち行列へ一度だけ積む。

常時の取り込み（`GifterLeagueWorker`）は「直近24時間にgiftした人」しか積まない。userの
指定どおり「5日経って**再登場した**ときに取り直す」ためで、窓を広げたままにすると、もう
来ていない人まで5日ごとに引き直し続けることになる。そのため過去ぶんの初回取得だけは、
この一度きりのscriptで積む。

積むだけで、取得そのものはserverのworkerが既定15秒に1人ずつ流す。**serverを止める必要は
無い**（queueはDBに在るため、動いているworkerがそのまま拾う）。多重に流れることも無い。

注意: 取れるのは**今日のリーグ**であって、その人がgiftした当時のリーグではない。リーグは
日次変動し、過去の値は復元できない（doc/GIFTER_LEAGUE.md）。「配信者かどうか」は安定した
属性なので、ライバー比率の分子としてはこのままで足りる。

閾値の目安（2026-08-02の実DB、通算コインで絞った場合）:
    >=5000   360人 / 1.5時間 / ギフト全体の94.3%
    >=1000   770人 / 3.2時間 / 98.2%   <- 既定。これ以下は誤差の範囲(userの判断)
    >=100  1,282人 / 5.3時間 / 99.1%
    全員   7,217人 / 30.1時間 / 99.2%

「対象のコイン」に出るのは**これから積む人**のぶんだけで、既に確認済みの人と、handleとして
成立しない行は含まない。総額に対する割合はその分だけ低く出る。

Usage (run from the TicTok directory):
    python scripts/backfill_gifter_leagues.py --dry-run
    python scripts/backfill_gifter_leagues.py
    python scripts/backfill_gifter_leagues.py --min-coin 1000
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tictok.store._common import NON_IDENTITY_KEYS
from tictok.store.gifter_league import _VALID_HANDLE_GLOB

# 未取得の人を通算コインで数える。1人1行で、既に確認済みの人は数えない。
_PENDING_SQL = f"""
SELECT e.identity_key AS key,
       COALESCE(NULLIF(MAX(u.unique_id), ''), MAX(e.user_unique_id)) AS unique_id,
       SUM(e.diamonds) AS coin
  FROM events e
  LEFT JOIN users u ON u.identity_key = e.identity_key
 WHERE e.kind = 'gift'
   AND e.identity_key IS NOT NULL
   AND e.identity_key NOT IN ({",".join("?" * len(NON_IDENTITY_KEYS))})
   AND u.league_checked_at IS NULL
 GROUP BY e.identity_key
HAVING coin >= ?
   AND COALESCE(NULLIF(MAX(u.unique_id), ''), MAX(e.user_unique_id)) <> ''
   -- handleとして成立しない行(表示名が混じっている)は照会できない。常時の取り込みと
   -- 同じ条件で外す(理由は tictok/store/gifter_league.py)。
   AND COALESCE(NULLIF(MAX(u.unique_id), ''), MAX(e.user_unique_id)) NOT GLOB ?
 ORDER BY coin DESC
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="tictok.db")
    parser.add_argument(
        "--min-coin", type=int, default=1000,
        help="通算でこのコイン数以上を投げた人だけを積む(既定1000)",
    )
    parser.add_argument(
        "--interval", type=float, default=15.0,
        help="所要時間の見積りに使う1人あたりの秒数(既定15=serverの既定値)",
    )
    parser.add_argument("--dry-run", action="store_true", help="積まずに件数だけ出す")
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.is_file():
        print(f"DBが見つかりません: {db_path}")
        return 1

    # 積む対象の確定は読み取り専用の接続で行う。serverが動いたまま実行できるようにする
    # ためで、書き込むのは最後のINSERTだけに閉じる。
    read = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    read.row_factory = sqlite3.Row
    read.execute("PRAGMA cache_size=-65536")
    try:
        rows = read.execute(
            _PENDING_SQL, (*NON_IDENTITY_KEYS, args.min_coin, _VALID_HANDLE_GLOB)
        ).fetchall()
        already = read.execute(
            "SELECT COUNT(*) AS n FROM league_queue"
        ).fetchone()["n"]
        total_coin = read.execute(
            "SELECT COALESCE(SUM(diamonds), 0) AS n FROM events WHERE kind = 'gift'"
        ).fetchone()["n"]
    except sqlite3.OperationalError as exc:
        # league_queue / users.league_checked_at が無い = migration前のDB。
        print(f"DBがまだリーグ取得に対応していません（serverを一度起動してください）: {exc}")
        return 1
    finally:
        read.close()

    covered = sum(r["coin"] or 0 for r in rows)
    hours = len(rows) * args.interval / 3600.0
    print(f"DB              : {db_path}")
    print(f"待ち行列(現在)  : {already} 人")
    print(f"積む対象        : {len(rows)} 人 (通算コイン >= {args.min_coin})")
    print(f"所要の見積り    : {hours:.1f} 時間 ({args.interval:.0f}秒/人)")
    if total_coin:
        print(f"対象のコイン    : {covered:,} / gift総額 {total_coin:,}"
              f" ({covered / total_coin * 100:.1f}%)")
    for row in rows[:5]:
        print(f"  例: @{row['unique_id']} ({row['coin']:,} コイン)")

    if args.dry_run:
        print("\n--dry-run のため積んでいません。")
        return 0

    now = time.time()
    write = sqlite3.connect(str(db_path), timeout=30.0)
    try:
        write.execute("PRAGMA busy_timeout=30000")
        cur = write.executemany(
            "INSERT OR IGNORE INTO league_queue"
            " (identity_key, unique_id, enqueued_at, attempts, next_attempt_at, last_error)"
            " VALUES (?, ?, ?, 0, 0, '')",
            # 既に積まれている当日ぶんを後ろへ回さないよう、enqueued_atは現在時刻にする
            # (待ち行列はenqueued_at順に流れる)。
            [(row["key"], row["unique_id"], now) for row in rows],
        )
        write.commit()
        added = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        pending = write.execute("SELECT COUNT(*) AS n FROM league_queue").fetchone()[0]
    finally:
        write.close()

    print(f"\n{added} 人を待ち行列へ積みました（待機 {pending} 人）。")
    print("serverのworkerがそのまま流します。再起動は不要です。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
