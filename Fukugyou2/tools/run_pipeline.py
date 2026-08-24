#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程0〜6 を順に流します。Windows / Linux のどちらでも同じ動きです。

途中で失敗したら、そこで止めます（後続を代替値で進めません）。
価格の取得と日本側の測定は外部 API の利用上限があるため、既定を小さくしています。

使い方:
  python tools/run_pipeline.py
  python tools/run_pipeline.py --no-discover          # 人が書いた検索語で回す
  python tools/run_pipeline.py --jp-discover          # 日本語の語の発見も回す（Qiita の上限に注意）
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import casebase as cb

HERE = os.path.dirname(os.path.abspath(__file__))


def run(script: str, args: list[str]) -> None:
    cmd = [sys.executable, os.path.join(HERE, script), *args]
    print(f"\n{'=' * 72}\n$ {' '.join(cmd[1:])}\n{'=' * 72}")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise SystemExit(f"{script} が失敗しました（終了 code {r.returncode}）。ここで止めます。")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="工程0〜6 の連続実行")
    ap.add_argument("--no-discover", action="store_true",
                    help="検索語の自動発見を行わず、config/queries_*.txt を使います")
    ap.add_argument("--jp-discover", action="store_true",
                    help="日本語の語の発見も行います（Qiita は認証なし 60 request/時）")
    ap.add_argument("--discover-rounds", type=int, default=3)
    ap.add_argument("--hits", type=int, default=20, help="1検索語あたりの取得件数")
    ap.add_argument("--min-points", type=int, default=30)
    ap.add_argument("--pricing-limit", type=int, default=30, help="価格 page を見に行く事例数")
    ap.add_argument("--pricing-min-points", type=int, default=100)
    ap.add_argument("--categories", nargs="*", default=["billing", "field_ops", "compliance", "doc_generation"],
                    help="日本側を測る分類 id（Qiita は認証なし 60 req/h）")
    ap.add_argument("--top", type=int, default=5, help="転用 worksheet にする事例数")
    ns = ap.parse_args(argv)

    queries = {}
    for kind in ("product", "failure"):
        if ns.no_discover:
            queries[kind] = cb.path("config", f"queries_{kind}.txt")
            continue
        run("discover_queries.py", ["--kind", kind, "--max-rounds", str(ns.discover_rounds)])
        auto = cb.path("config", f"queries_auto-{kind}-{cb.stamp()}.txt")
        if not os.path.exists(auto):
            raise SystemExit(f"{auto} が作られていません。工程0 の出力を確認してください。")
        queries[kind] = auto

    for kind in ("product", "failure"):
        run("collect_cases.py", ["--queries", queries[kind], "--kind", kind,
                                 "--hits", str(ns.hits), "--min-points", str(ns.min_points)])
    run("fetch_pricing.py", ["--limit", str(ns.pricing_limit), "--min-points", str(ns.pricing_min_points)])
    run("screen_cases.py", [])
    if ns.jp_discover:
        run("discover_jp_terms.py", ["--only", *ns.categories[:2], "--limit", "2"])
    run("jp_market_check.py", ["--only", *ns.categories, "--limit", str(len(ns.categories))])
    run("transfer_matrix.py", ["--top", str(ns.top)])
    run("build_report.py", [])
    print("\n完了しました。log/report-*.md と log/transfer-*.md を読んでください。")
    print(f"使った検索語: {', '.join(os.path.basename(v) for v in queries.values())}")
    print("採否は書いてありません。決めるのは人です（doc/METHOD.md §5 規律8）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
