"""意味検索indexを構築する。serverを起動せずに回すための入口。

画面の「意味検索indexを更新」と同じ ``semantic.build_index`` を呼ぶ。差分buildなので、
中断しても再実行すれば続きから進む(group単位でcommitされる)。

``--fresh`` は既存のindexを ``.bak`` へ退避してから全件を作り直す。vector fileは追記専用で、
passageを作り直すと旧行が穴として残るため、張り直しを重ねた後は作り直した方がfileが縮む。
消さずに退避するのは、埋め込みserverが落ちて空のindexだけが残る事故を戻せるようにするため。

注意: serverを起動すると ``run.bat`` が同じvenvのpython processを巻き添えで落とす。
このscriptを走らせている間はserverを起動しないこと(落ちても再実行で続きから進む)。

Usage (TicTokディレクトリから、venvで):
    python scripts/rebuild_semantic_index.py            # 差分build
    python scripts/rebuild_semantic_index.py --fresh    # 退避して全件作り直し
    python scripts/rebuild_semantic_index.py --status   # 現況を出すだけ
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tictok.core import config  # noqa: E402
from tictok.search import semantic  # noqa: E402
from tictok.storage import Storage  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("rebuild_semantic_index")

# 進捗を出す間隔。batchごとに鳴るcallbackをそのまま流すと、logが埋め込みより忙しくなる。
PROGRESS_INTERVAL_SECONDS = 30.0


def report(storage) -> dict:
    status = semantic.index_status(storage)
    logger.info(
        "index: passages=%s 録画=%s model=%s / 張り直し待ち=%s group(%s passage)"
        " 未index=%s group",
        f"{status['passages']:,}", status["recordings"], status["index_model"],
        status["stale_groups"], f"{status['stale_passages']:,}",
        status["unindexed_groups"],
    )
    return status


def stash_existing() -> list:
    """既存のindexを .bak へ退避する。戻したfileのlistを返す。"""
    moved = []
    for path in (semantic.vector_path(), semantic.meta_path()):
        if not path.is_file():
            continue
        backup = path.with_suffix(path.suffix + ".bak")
        if backup.exists():
            backup.unlink()
        path.rename(backup)
        moved.append(backup)
        logger.info("退避しました: %s -> %s (%.1f MB)", path.name, backup.name,
                    backup.stat().st_size / 1e6)
    return moved


async def run(args) -> int:
    storage = Storage(config.get_db_path())
    try:
        logger.info("DB=%s  埋め込み=%s / %s", config.get_db_path(),
                    semantic.get_semantic_base_url(), semantic.get_semantic_model())
        report(storage)
        if args.status:
            return 0
        if args.fresh:
            stash_existing()

        started = time.time()
        state = {"at": 0.0}

        def on_progress(info: dict) -> None:
            stage = info.get("stage")
            if stage == "start":
                logger.info("開始: %s group / %s hits", info.get("groups"),
                            f"{info.get('hits', 0):,}")
                return
            if stage not in ("embed", "group_done"):
                return
            now = time.time()
            if now - state["at"] < PROGRESS_INTERVAL_SECONDS:
                return
            state["at"] = now
            done, total = info.get("done") or 0, info.get("total") or 0
            elapsed = now - started
            # 残り時間は実測rateから出す。件数だけでは「あと何時間か」が読めない。
            rate = done / elapsed if elapsed > 0 and done else 0
            eta = (total - done) / rate if rate else 0
            logger.info("  %5.1f%%  %s/%s hits  経過 %.0f分  残り 約%.0f分",
                        done * 100 / total if total else 0, f"{done:,}", f"{total:,}",
                        elapsed / 60, eta / 60)

        result = await semantic.build_index(storage, on_progress=on_progress)
        logger.info(
            "完了: %s group / %s hits / %s passage / %.1f 分 / vector %.1f MB",
            result["groups"], f"{result['hits']:,}", f"{result['passages']:,}",
            result["elapsed_seconds"] / 60, result["vector_bytes"] / 1e6)
        report(storage)
        return 0
    except semantic.SemanticError as exc:
        logger.error("中断しました: %s", exc)
        return 1
    finally:
        storage.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh", action="store_true",
                        help="既存indexを.bakへ退避して全件を作り直す")
    parser.add_argument("--status", action="store_true", help="現況を出すだけ")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
