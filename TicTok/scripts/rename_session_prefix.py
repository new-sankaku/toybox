"""既存録画のファイル名へ zero-pad した Session 番号 prefix を後付けする一回限りの移行。

新規録画は recorder が ``{session番号5桁}_{unique_id}_{stamp}`` で出力するが、既存の
録画は prefix が無い。本 script は recordings DB を辿り、session_id を持ち実体が
存在する録画について、mp4 本体・retain された HLS dir・``.sidecars`` 配下の sidecar を
prefix 付きへ rename し、DB の path/filename を更新する。

session_id を持たない古い行（session 管理導入前 / 中断）や、実体が無い行は、付与すべき
番号が無いため触らない（誤った番号を捏造しない）。

既定は dry-run。``--apply`` で実際に変更する。Windows/Linux 双方で動作する。
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tictok.core import layout
from tictok.core.config import get_db_path, record_dir_from_db
from tictok.record.recorder import SIDECAR_DIRNAME, session_prefix

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("tictok.rename_session_prefix")


def _old_base(filename: str, path: Path, record_dir: Path) -> str | None:
    """録画行から rename 対象の base（拡張子なしの stem）を導く。完了録画は mp4 名、
    HLS fallback は親 dir 名。導けない場合は None。"""
    if filename.endswith(".mp4"):
        return filename[:-4]
    if filename == "index.m3u8" and path.parent != record_dir:
        return path.parent.name
    return None


def _plan_row(row: sqlite3.Row, record_dir: Path) -> dict | None:
    """1 録画行の rename 計画を返す（対象が無ければ None）。"""
    session_id = row["session_id"]
    if session_id is None:
        return None
    old_base = _old_base(row["filename"] or "", Path(row["path"] or ""), record_dir)
    if not old_base:
        return None
    prefix = f"{session_prefix(session_id)}_"
    if old_base.startswith(prefix):
        return None  # 既に付与済み
    new_base = prefix + old_base

    # old_base and new_base share the same streamer, so every move stays within the
    # same <streamer>/{ts,mp4} folders — only the stem's session prefix changes.
    moves: list[tuple[Path, Path]] = []
    mp4 = layout.mp4_path(record_dir, old_base)
    if mp4.is_file():
        moves.append((mp4, layout.mp4_path(record_dir, new_base)))
    # The burned-in overlay mp4 lives in the mp4 folder next to its source, so it renames
    # alongside the recording rather than with the .sidecars artifacts below.
    overlay = layout.mp4_dir(record_dir, old_base) / f"{old_base}.overlay.mp4"
    if overlay.is_file():
        moves.append((overlay, layout.mp4_dir(record_dir, new_base) / f"{new_base}.overlay.mp4"))
    hls = layout.session_dir(record_dir, old_base)
    if hls.is_dir():
        moves.append((hls, layout.session_dir(record_dir, new_base)))
    sidecar_dir = record_dir / SIDECAR_DIRNAME
    if sidecar_dir.is_dir():
        for art in sorted(sidecar_dir.iterdir()):
            if art.is_file() and art.name.startswith(old_base + "."):
                rest = art.name[len(old_base):]
                moves.append((art, sidecar_dir / (new_base + rest)))
    if not moves:
        return None  # 実体が無い（中断で HLS も mp4 も残っていない）

    old_path = row["path"] or ""
    new_path = old_path.replace(old_base, new_base) if old_base in old_path else old_path
    new_filename = (row["filename"] or "").replace(old_base, new_base)
    return {
        "id": row["id"],
        "old_base": old_base,
        "new_base": new_base,
        "moves": moves,
        "new_path": new_path,
        "new_filename": new_filename,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    parser.add_argument("--db", default=None, help="recordings DB path (default: project setting)")
    parser.add_argument("--record-dir", default=None, help="recordings dir (default: project setting)")
    args = parser.parse_args()

    db_path = args.db or get_db_path()
    record_dir = Path(args.record_dir) if args.record_dir else Path(record_dir_from_db(db_path))
    if not record_dir.is_dir():
        logger.error("recordings directory not found: %s", record_dir)
        return 1

    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, session_id, unique_id, status, filename, path FROM recordings ORDER BY id"
    ).fetchall()

    plans = [p for p in (_plan_row(r, record_dir) for r in rows) if p]
    skipped = len(rows) - len(plans)

    # 衝突検査: 同一 rename 先が既存ファイル/別計画と重ならないこと。
    targets: dict[str, int] = {}
    safe_plans: list[dict] = []
    for plan in plans:
        conflict = False
        for src, dst in plan["moves"]:
            if dst.exists() and dst != src:
                logger.warning("  [skip id=%s] 既に存在: %s", plan["id"], dst.name)
                conflict = True
                break
            prev = targets.get(str(dst).lower())
            if prev is not None:
                logger.warning("  [skip id=%s] rename 先が id=%s と衝突: %s", plan["id"], prev, dst.name)
                conflict = True
                break
        if conflict:
            continue
        for _src, dst in plan["moves"]:
            targets[str(dst).lower()] = plan["id"]
        safe_plans.append(plan)

    for plan in safe_plans:
        logger.info("id=%s  %s  ->  %s  (%d file/dir)", plan["id"], plan["old_base"], plan["new_base"], len(plan["moves"]))

    if not args.apply:
        logger.info(
            "dry-run: %d 件を rename 予定 / %d 件は対象外（session_id 無し・実体無し・付与済み）。"
            "適用は --apply。", len(safe_plans), skipped,
        )
        conn.close()
        return 0

    applied = 0
    for plan in safe_plans:
        try:
            for src, dst in plan["moves"]:
                os.replace(src, dst)
            conn.execute(
                "UPDATE recordings SET path = ?, filename = ? WHERE id = ?",
                (plan["new_path"], plan["new_filename"], plan["id"]),
            )
            conn.commit()
            applied += 1
        except OSError:
            conn.rollback()
            logger.warning("  [fail id=%s] rename 失敗（ファイルロック?）", plan["id"], exc_info=True)
    conn.close()
    logger.info("applied: %d 件を rename・DB 更新 / %d 件は対象外。", applied, skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
