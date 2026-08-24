#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程6 一覧化。ここまでの出力を1枚の markdown にまとめます。

新しい判定はしません。既に測った数字を並べ替えて表にするだけです。
欠損（未取得・失敗）は消さずに、欠損として節を立てて残します。

使い方:
  python tools/build_report.py
  python tools/build_report.py --top 40
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import casebase as cb

AXIS_MARK = {"stock": "S", "ai": "A", "proof": "P", "b2b": "B"}


def optional_json(out_dir: str, pattern: str):
    found = sorted(glob.glob(os.path.join(out_dir, pattern)))
    if not found:
        return None, None
    with open(found[-1], encoding="utf-8") as f:
        return json.load(f), os.path.basename(found[-1])


def axis_cell(item: dict) -> str:
    return "".join(AXIS_MARK[a] for a in ("stock", "ai", "proof", "b2b") if a in item["axes_met"]) or "—"


def case_rows(items: list[dict], pricing: dict, limit: int) -> list[str]:
    rows = []
    for i in items[:limit]:
        price = "○" if pricing.get(i["case_id"], {}).get("matches") else ("×" if i["pricing_fetched"] else "未取得")
        title = i["title"].replace("|", "/")[:70]
        rows.append(f"| [{title}]({i['url']}) | {i['axes_met_count']}/4 {axis_cell(i)} | "
                    f"{', '.join(i['categories']) or '—'} | {i['points'] or '—'} | "
                    f"{(i['created_at'] or '')[:10]} | {price} | [HN]({i['discussion_url']}) |")
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="工程6: 一覧の markdown を作る")
    ap.add_argument("--out", default=cb.path("log"))
    ap.add_argument("--top", type=int, default=40, help="一覧に載せる件数")
    ns = ap.parse_args(argv)

    screen_path = cb.latest(ns.out, "screen-*.json", "tools/screen_cases.py")
    with open(screen_path, encoding="utf-8") as f:
        screen = json.load(f)
    jp, jp_name = optional_json(ns.out, "jp-market-*.json")
    pricing_files = sorted(glob.glob(os.path.join(ns.out, "pricing-*.jsonl")))
    pricing = {r["case_id"]: r for r in cb.read_jsonl(pricing_files[-1])} if pricing_files else {}

    s = screen["summary"]
    items = screen["items"]
    products = [i for i in items if i["kind"] == "product"]
    failures = [i for i in items if i["kind"] == "failure"]
    head = "| 事例 | 該当軸 | 分類 | HN点数 | 投稿日 | 価格の証拠 | 議論 |"
    sep = "|---|---|---|---|---|---|---|"

    L = [f"# 事例 一覧（{cb.today()}）", "",
         f"入力: `{s['cases_file']}` / `{s.get('pricing_file') or '価格 未取得'}`"
         + (f" / `{jp_name}`" if jp_name else ""), "",
         "軸の記号は S=Stock性 A=AI自動化性 P=証拠性 B=法人が払うか です。",
         "**この一覧は採否を書きません。** 条件に何件該当したかと、その出所だけを載せます。", "",
         "---", "", "## 1. 数え上げ", "",
         f"- 事例 {s['n_cases']}件（製品化 {len(products)}件 / 失敗・撤退 {len(failures)}件）",
         f"- 価格 page を実際に見に行った事例 {s['n_pricing_fetched']}件",
         f"- 対象外の印がついた事例 {s['exclude_marked']}件（削除していません）",
         f"- 未分類 {s['uncategorized']}件", "",
         "### 該当軸数の分布", "", "| 該当軸数 | 件数 |", "|---|---|"]
    L += [f"| {k}軸 | {v}件 |" for k, v in s["axes_met_histogram"].items()]
    L += ["", "### 条件ごとの該当数", "", "| 条件 | 件数 |", "|---|---|"]
    L += [f"| {k} | {v}件 |" for k, v in s["condition_hits"].items()]

    L += ["", "---", "", f"## 2. 製品化された事例（該当軸数の順・上位{min(ns.top, len(products))}件）", "", head, sep]
    L += case_rows(products, pricing, ns.top)

    L += ["", "---", "", "## 3. 失敗・撤退の事例", "",
          "生き残りだけを見る偏りを消すための節です。**ここが空なら収集をやり直してください。**", ""]
    if failures:
        L += [head, sep] + case_rows(failures, pricing, ns.top)
    else:
        L += ["**0件です。** `python tools/collect_cases.py --queries config/queries_failure.txt --kind failure` "
              "を実行してください。"]

    L += ["", "---", "", "## 4. 日本側の実測", ""]
    if jp:
        L += ["| 分類 | 英語圏 HN | 日本 Qiita 需要語 | 日本 Qiita 供給語 | 日本÷英語 | 需要÷供給 |", "|---|---|---|---|---|---|"]
        for c in jp["categories"]:
            t = c["totals"]
            L.append(f"| {c['label']} | {t['en_hn']} | {t['jp_qiita_demand']} | {t['jp_qiita_supply']} | "
                     f"{t['jp_per_en'] if t['jp_per_en'] is not None else '—'} | "
                     f"{t['demand_per_supply'] if t['demand_per_supply'] is not None else '—'} |")
        L += ["", "**限界（この数字で言えないこと）:**", ""] + [f"- {x}" for x in jp["limits"]]
        if jp.get("stopped"):
            L += ["", f"- 中断: {jp['stopped']}"]
    else:
        L += ["未測定です。`python tools/jp_market_check.py --only <分類id>` を実行してください。"]

    L += ["", "---", "", "## 5. 欠損の記録", ""]
    missing = s["n_cases"] - s["n_pricing_fetched"]
    L += [f"- 価格の証拠が未取得: {missing}件（Stock性の判定はその分だけ弱い証拠に依っています）"]
    if jp and jp.get("failures"):
        L += [f"- 日本側の測定失敗: {len(jp['failures'])}件"]
    fail_files = sorted(glob.glob(os.path.join(ns.out, "cases-*-failures.json")))
    if fail_files:
        with open(fail_files[-1], encoding="utf-8") as f:
            L += [f"- 収集時に失敗した検索語: {len(json.load(f))}語（`{os.path.basename(fail_files[-1])}`）"]

    L += ["", "---", "", "## 6. 次にやること", "",
          "1. 上位の事例の価格 page を人が見て、Stock性の○×を確かめる（機械の○は表示の一致でしかありません）",
          "2. 失敗事例の本文を読み、**なぜ畳んだか**を `doc/METHOD.md §3` の型で分類する",
          "3. `tools/transfer_matrix.py` の worksheet を埋める（空欄のまま次に進まないこと）",
          "4. 日本側の言及量が多い分類から、実際に困っている人を1人見つけて話を聞く", ""]

    out_path = os.path.join(ns.out, f"report-{cb.stamp()}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"一覧: {out_path}")
    print(f"事例 {s['n_cases']}件（製品化 {len(products)} / 失敗 {len(failures)}）"
          f" / 日本側の実測 {'あり' if jp else 'なし'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
