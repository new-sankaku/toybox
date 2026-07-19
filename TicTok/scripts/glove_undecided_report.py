"""Report why glove (Critical Strike) gifts ended up undecided, from the raw captures.

The crit rate is computed only over gifts whose multiplier could be pinned down, so the
undecided share is the main limit on how much the coin-band table can say. The per-event
reason is deliberately not persisted (it is not actionable per gift and would grow every
battle payload), so this script reconstructs it by replaying the raw Battle captures in
logs/battle_raw_*.jsonl with the exact judgement order the collector uses.

Requires the "battle_debug_capture" setting to have been on while collecting — that is
what writes the captures. Without them a battle is reported as NO_CAPTURE and nothing
about it can be said.

Reasons, in the order the judgement tries them:
    ATTR_MERGED      armies named the gift, but the score delta is not a whole multiple
                     of it (another gift landed in the same score update)
    ATTR_AMBIGUOUS   armies named the gift, but the bonus-time multiplier is unknown or
                     equals the window multiplier, so a crit and a normal gift would
                     move the score by the same amount
    MULT_UNKNOWN     no naming, and the bonus-time multiplier is unknown
    MULT_EQ_CRIT     no naming, and bonus-time multiplier == window multiplier
    BOTH_HIT         no naming, and both the normal and the crit amount are present
    NO_HIT_MERGED    no naming, neither amount matched, but a larger delta is in the
                     window (the gift's contribution is folded into it)
    NO_HIT_SHORT     no naming, neither amount matched, deltas present but all smaller
    NO_HIT_NO_DELTA  no naming, no score delta in the match window at all

Two more buckets are about bookkeeping rather than evidence:
    STALE_VERSION    the replay resolves it but the stored event is still undecided, i.e.
                     the startup migration has not re-judged this battle yet. Expect a
                     large count before the first run on an older database, and roughly
                     zero after. A handful can persist: the replay consumes evidence in
                     one fixed pass while collection interleaved it with live traffic.
    KEPT_FROM_LIVE   the replay cannot resolve it but the verdict recorded during
                     collection stands (a decided event is never demoted to undecided).

Read-only: the database is opened in read-only mode and never written.

Usage (run from the TicTok directory):
    python scripts/glove_undecided_report.py
    python scripts/glove_undecided_report.py --db tictok.db --log-dir logs
    python scripts/glove_undecided_report.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tictok.glove_migration import (  # noqa: E402
    _ATTR_MATCH_SEC, _DEFAULT_MULTIPLE, _MATCH_AFTER_SEC, _MATCH_BEFORE_SEC,
    _load_battle_signals, _multiplier_at, _own_host_id,
)

COIN_BANDS = [(0, 100), (100, 500), (500, 1000), (1000, 3000),
              (3000, 6000), (6000, 12000), (12000, None)]


def _unit_coins(conn: sqlite3.Connection) -> dict:
    """gift_id -> 単価。判定不能eventはcoinsが埋まっていないことがあるため補完に使う。"""
    out = {}
    for row in conn.execute(
        "SELECT gift_id, diamonds, gift_count FROM events"
        " WHERE kind = 'gift' AND gift_id IS NOT NULL AND gift_count > 0"
    ):
        if row["gift_count"]:
            out[row["gift_id"]] = (row["diamonds"] or 0) / row["gift_count"]
    return out


def _consume(jumps, t, amount):
    """判定側と同じ消費規則: 完全一致を優先し、無ければ複合deltaから差し引く。"""
    for jump in jumps:
        if t - _MATCH_BEFORE_SEC <= jump[0] <= t + _MATCH_AFTER_SEC and jump[1] == amount:
            jump[1] = 0
            return True
    for jump in jumps:
        if t - _MATCH_BEFORE_SEC <= jump[0] <= t + _MATCH_AFTER_SEC and jump[1] > amount:
            jump[1] -= amount
            return True
    return False


def _offwindow_consume(conn, session_id, windows, jumps, missions):
    """窓外giftの通常寄与を先に消費し、窓中giftとの偶然一致を避ける(判定側と同じ前処理)。"""
    if not (windows and jumps):
        return
    t_lo = min(w["start"] for w in windows) - 120
    t_hi = max(w["end"] for w in windows) + 120
    for gift in conn.execute(
        "SELECT create_time t, diamonds total FROM events"
        " WHERE session_id = ? AND kind = 'gift' AND create_time BETWEEN ? AND ?"
        " ORDER BY create_time",
        (session_id, t_lo, t_hi),
    ):
        gt = gift["t"]
        if any(w["start"] <= gt <= w["end"] for w in windows):
            continue
        m = _multiplier_at(missions, gt)
        if m is not None:
            _consume(jumps, gt, (gift["total"] or 0) * m)


def _classify(ev, windows, missions, jumps, attrs):
    """判定順どおりに辿り、決まらなかった地点を理由として返す。"""
    t = ev.get("t") or 0
    total = ev.get("total") or 0
    multiple = _DEFAULT_MULTIPLE
    for w in windows:
        if w["start"] <= t <= w["end"]:
            multiple = w.get("multiple") or _DEFAULT_MULTIPLE
    m = _multiplier_at(missions, t)
    if total <= 0:
        return "NO_TOTAL"

    named = None
    for entry in attrs:
        if entry["used"] or entry["gid"] != ev.get("gift_id"):
            continue
        if abs(entry["t"] - t) > _ATTR_MATCH_SEC:
            continue
        named = entry
        break
    if named is not None:
        if named["flag"]:
            named["used"] = True
            return "DECIDED"
        if m is None or m == multiple:
            return "ATTR_AMBIGUOUS"
        ratio = named["delta"] / total
        hit = int(round(ratio)) if abs(ratio - round(ratio)) < 0.01 else None
        if hit in (multiple, m):
            named["used"] = True
            return "DECIDED"
        return "ATTR_MERGED"

    if m is None:
        return "MULT_UNKNOWN"
    want_normal, want_crit = total * m, total * multiple
    if want_normal == want_crit:
        return "MULT_EQ_CRIT"
    cands = [j for j in jumps
             if t - _MATCH_BEFORE_SEC <= j[0] <= t + _MATCH_AFTER_SEC and j[1] > 0]
    hit_normal = any(j[1] == want_normal for j in cands)
    hit_crit = any(j[1] == want_crit for j in cands)
    if hit_normal and hit_crit:
        return "BOTH_HIT"
    if hit_normal != hit_crit:
        _consume(jumps, t, want_crit if hit_crit else want_normal)
        return "DECIDED"
    if not cands:
        return "NO_HIT_NO_DELTA"
    if any(j[1] > want_crit for j in cands):
        return "NO_HIT_MERGED"
    return "NO_HIT_SHORT"


def _band_of(coins):
    for lo, hi in COIN_BANDS:
        if coins >= lo and (hi is None or coins < hi):
            return f"{lo}-{hi if hi is not None else ''}"
    return "?"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="tictok.db")
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.is_file():
        print(f"database not found: {db_path}", file=sys.stderr)
        return 1
    log_dir = Path(args.log_dir)

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    unit = _unit_coins(conn)

    reasons = Counter()
    per_band = defaultdict(Counter)
    methods = Counter()
    captures_missing = 0
    battles = 0

    for row in conn.execute(
        "SELECT b.battle_id bid, b.session_id sid, b.data_json d, s.unique_id uid"
        " FROM battles b JOIN sessions s ON s.id = b.session_id"
    ):
        try:
            battle = json.loads(row["d"])
        except (ValueError, TypeError):
            continue
        events = battle.get("glove_events") or []
        if not events:
            continue
        battles += 1
        windows = [w for w in (battle.get("glove_windows") or []) if w.get("own")]
        own_hid = _own_host_id(battle, row["uid"])
        series, attrs = _load_battle_signals(
            log_dir, row["uid"], row["sid"], int(row["bid"]), own_hid
        )
        have_capture = bool(series)
        if not have_capture:
            captures_missing += 1
        jumps = [[t1, s1 - s0] for (t0, s0), (t1, s1) in zip(series, series[1:]) if s1 > s0]
        missions = battle.get("bonus_missions")
        _offwindow_consume(conn, row["sid"], windows, jumps, missions)

        # 全eventを保存順で再生する。判定済のものも証拠(名指し同定・score delta)を同じ
        # 順序で消費させないと、以降のeventが余った証拠に誤って当たり結果がずれる。
        for ev in sorted(events, key=lambda e: e.get("t") or 0):
            coins = ev.get("coins")
            if coins is None:
                coins = unit.get(ev.get("gift_id")) or 0
            band = _band_of(coins)
            replay = "NO_CAPTURE" if not have_capture else _classify(
                ev, windows, missions, jumps, attrs
            )
            stored_decided = ev.get("crit") is not None
            if replay == "DECIDED":
                if stored_decided:
                    reason = "DECIDED"
                    methods[ev.get("method") or "(live, pre-attr)"] += 1
                else:
                    # 現行方式なら決まるのに保存側が判定不能 = 旧版のまま再判定されていない。
                    reason = "STALE_VERSION"
            elif stored_decided:
                # 再生では決まらないが収集時のlive判定が残っている(降格させない規則)。
                reason = "KEPT_FROM_LIVE"
                methods[ev.get("method") or "(live, pre-attr)"] += 1
            else:
                reason = replay
            reasons[reason] += 1
            per_band[band][reason] += 1

    total = sum(reasons.values())
    decided = reasons["DECIDED"] + reasons["KEPT_FROM_LIVE"]
    if args.json:
        print(json.dumps({
            "battles": battles, "events": total, "decided": decided,
            "captures_missing_battles": captures_missing,
            "reasons": dict(reasons), "methods": dict(methods),
            "per_band": {k: dict(v) for k, v in per_band.items()},
        }, ensure_ascii=False, indent=2))
        return 0

    if not total:
        print("no glove events found")
        return 0
    print(f"battles with glove events : {battles} (raw capture missing: {captures_missing})")
    print(f"glove events              : {total}")
    print(f"decided                   : {decided} ({decided / total * 100:.1f}%)")
    print()
    print("=== how the decided ones were resolved ===")
    for method, n in methods.most_common():
        print(f"  {method:<16} {n:5d}")
    print()
    print("=== why the rest are undecided ===")
    undecided = total - decided
    resolved = ("DECIDED", "KEPT_FROM_LIVE")
    for reason, n in reasons.most_common():
        if reason in resolved:
            continue
        share = f"({n / undecided * 100:5.1f}%)" if undecided else ""
        print(f"  {reason:<16} {n:5d} {share}")
    print()
    print("=== per coin band ===")
    print(f"  {'band':<12} {'events':>7} {'decided':>8} {'rate':>7}  top reason")
    for lo, hi in COIN_BANDS:
        band = f"{lo}-{hi if hi is not None else ''}"
        counts = per_band.get(band)
        if not counts:
            continue
        n = sum(counts.values())
        dec = sum(counts[r] for r in resolved)
        top = [(k, v) for k, v in counts.most_common() if k not in resolved][:1]
        top_s = f"{top[0][0]} ({top[0][1]})" if top else "-"
        print(f"  {band:<12} {n:7d} {dec:8d} {dec / n * 100:6.1f}%  {top_s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
