"""Repair the own host name on team battles stored before the team_armies parsing
fix. Those battles registered the own team as a single nameless side=="own"
participant keyed by a synthetic id (the team_id) with is_own never set, so the
history view renders the monitored streamer as "(unknown)". The own side is, by
definition, the monitored streamer, so its identity is recoverable from the
session owner — this is the only part of the legacy data that can be restored
safely (opponent team membership was never persisted and cannot be reconstructed).

Safe-by-construction: a battle is only touched when it has NO is_own participant
AND exactly one nameless side=="own" participant — no ambiguity about which record
is the own host. Idempotent: a battle already carrying an is_own participant is
skipped, so re-running is a no-op.

Usage (run from the TicTok directory):
    python scripts/repair_battle_own_host.py            # dry-run, report only
    python scripts/repair_battle_own_host.py --apply    # write changes
    python scripts/repair_battle_own_host.py --db other.db
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tictok.core.config import get_db_path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("tictok.repair")


def _session_owners(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT id, unique_id, owner_nickname, owner_avatar FROM sessions"
    ).fetchall()
    return {
        r[0]: {"unique_id": r[1] or "", "nickname": r[2] or "", "avatar": r[3] or ""}
        for r in rows
    }


def _repair_battle(battle: dict, owner: dict) -> bool:
    """Set is_own and the owner's display fields on the sole nameless own-side host.
    Returns True when the battle was modified."""
    parts = battle.get("participants") or []
    if any(p.get("is_own") for p in parts):
        return False
    candidates = [p for p in parts if p.get("side") == "own" and not p.get("nickname")]
    if len(candidates) != 1:
        return False
    if not (owner.get("nickname") or owner.get("unique_id")):
        return False
    host = candidates[0]
    host["is_own"] = True
    host["nickname"] = owner.get("nickname") or host.get("nickname", "")
    host["unique_id"] = owner.get("unique_id") or host.get("unique_id", "")
    if owner.get("avatar"):
        host["avatar"] = owner["avatar"]
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=get_db_path(), help="SQLite DB path")
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        owners = _session_owners(conn)
        rows = conn.execute(
            "SELECT rowid, session_id, battle_id, data_json FROM battles"
        ).fetchall()
        repaired = []
        for rowid, session_id, battle_id, data_json in rows:
            battle = json.loads(data_json)
            owner = owners.get(session_id, {})
            if _repair_battle(battle, owner):
                repaired.append((rowid, session_id, battle_id, owner.get("nickname"), battle))

        for _rowid, session_id, battle_id, nickname, _battle in repaired:
            logger.info(
                "%s session=%s battle=%s -> 自陣のhost = %r",
                "REPAIR" if args.apply else "WOULD REPAIR",
                session_id,
                battle_id,
                nickname,
            )

        if args.apply and repaired:
            # Target by rowid: (session_id, battle_id) is not unique — legacy team
            # battles are all stored with battle_id=0, and a keyed UPDATE would
            # rewrite every such sibling with the last battle's JSON.
            conn.executemany(
                "UPDATE battles SET data_json = ? WHERE rowid = ?",
                [
                    (json.dumps(b, ensure_ascii=False), rowid)
                    for rowid, _sid, _bid, _nick, b in repaired
                ],
            )
            conn.commit()

        logger.info(
            "%s battle %d件%s",
            "Repaired" if args.apply else "Would repair",
            len(repaired),
            "" if args.apply else " (dry-run; pass --apply to write)",
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
