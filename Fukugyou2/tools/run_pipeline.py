#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程1〜6 を順に流します。Windows / Linux のどちらでも同じ動きです。

途中で失敗したら、そこで止めます（後続を代替値で進めません）。
価格の取得と日本側の測定は外部 API の利用上限があるため、既定を小さくしています。

使い方:
  python tools/run_pipeline.py
  python tools/run_pipeline.py --pricing-limit 40 --categories billing booking
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
    ap = argparse.ArgumentParser(description="工程1〜6 の連続実行")
    ap.add_argument("--hits", type=int, default=20, help="1検索語あたりの取得件数")
    ap.add_argument("--min-points", type=int, default=30)
    ap.add_argument("--pricing-limit", type=int, default=30, help="価格 page を見に行く事例数")
    ap.add_argument("--pricing-min-points", type=int, default=100)
    ap.add_argument("--categories", nargs="*", default=["billing", "field_ops", "compliance", "doc_generation"],
                    help="日本側を測る分類 id（Qiita は認証なし 60 req/h）")
    ap.add_argument("--top", type=int, default=5, help="転用 worksheet にする事例数")
    ns = ap.parse_args(argv)

    run("collect_cases.py", ["--queries", cb.path("config", "queries_product.txt"), "--kind", "product",
                             "--hits", str(ns.hits), "--min-points", str(ns.min_points)])
    run("collect_cases.py", ["--queries", cb.path("config", "queries_failure.txt"), "--kind", "failure",
                             "--hits", str(ns.hits), "--min-points", str(ns.min_points)])
    run("fetch_pricing.py", ["--limit", str(ns.pricing_limit), "--min-points", str(ns.pricing_min_points)])
    run("screen_cases.py", [])
    run("jp_market_check.py", ["--only", *ns.categories, "--limit", str(len(ns.categories))])
    run("transfer_matrix.py", ["--top", str(ns.top)])
    run("build_report.py", [])
    print("\n完了しました。log/report-*.md と log/transfer-*.md を読んでください。")
    print("採否は書いてありません。決めるのは人です（doc/METHOD.md §5 規律8）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
