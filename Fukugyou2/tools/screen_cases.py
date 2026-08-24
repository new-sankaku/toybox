#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程3 条件照合。config/screen.yaml の条件に何件該当したかを事例ごとに出します。

出すのは「4軸中N軸該当」までです。採否は書きません（doc/METHOD.md §5 規律8）。
閾値・条件は config 側にあり、この program には埋まっていません。

使い方:
  python tools/screen_cases.py
  python tools/screen_cases.py --cases log/cases-20260824.jsonl --pricing log/pricing-20260824.jsonl
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import casebase as cb


def compile_conditions(screen: dict) -> list[dict]:
    out = []
    for c in screen["conditions"]:
        if c["evidence"] not in ("text", "pricing"):
            raise SystemExit(f"条件 {c['id']} の evidence は text か pricing にしてください。")
        out.append({**c, "patterns": [re.compile(p) for p in c["any_of"]]})
    return out


def case_text(case: dict) -> str:
    return " \n".join(x for x in (case.get("title"), case.get("tagline"), case.get("story_text")) if x)


def evaluate(case: dict, conditions: list[dict], excludes: list[dict], pricing: dict | None) -> dict:
    text = case_text(case)
    hits, evidence = [], {}
    for c in conditions:
        if c["evidence"] == "text":
            for p in c["patterns"]:
                m = p.search(text)
                if m:
                    hits.append(c)
                    evidence[c["id"]] = text[max(0, m.start() - 30):m.end() + 30].strip()
                    break
        else:
            if pricing is None:
                continue
            found = next((m for m in pricing.get("matches", []) if m["pattern"] in c["any_of"]), None)
            if found:
                hits.append(c)
                evidence[c["id"]] = found["sample"]

    by_axis = Counter(c["axis"] for c in hits)
    marks = []
    for e in excludes:
        if any(p.search(text) for p in e["patterns"]):
            marks.append(e["id"])
    return {"matched": [c["id"] for c in hits], "by_axis": dict(by_axis),
            "evidence": evidence, "exclude_marks": marks}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="工程3: 条件照合（該当数を出すだけ）")
    ap.add_argument("--cases", help="既定は log/ の最新 cases-*.jsonl")
    ap.add_argument("--pricing", help="既定は log/ の最新 pricing-*.jsonl（無ければ未取得として扱います）")
    ap.add_argument("--screen", default=cb.path("config", "screen.yaml"))
    ap.add_argument("--categories", default=cb.path("config", "categories.yaml"))
    ap.add_argument("--out", default=cb.path("log"))
    ns = ap.parse_args(argv)

    screen = cb.load_yaml(ns.screen)
    axes = screen["axes"]
    conditions = compile_conditions(screen)
    excludes = [{**e, "patterns": [re.compile(p) for p in e["any_of"]]} for e in screen["exclude"]]
    cats = [{**c, "patterns": [re.compile(p) for p in c["assign_any_of"]]}
            for c in cb.load_yaml(ns.categories)["categories"]]

    cases_path = ns.cases or cb.latest(ns.out, "cases-*.jsonl", "tools/collect_cases.py")
    cases = cb.read_jsonl(cases_path)
    pricing_path = ns.pricing
    if pricing_path is None:
        try:
            pricing_path = cb.latest(ns.out, "pricing-*.jsonl", "tools/fetch_pricing.py")
        except SystemExit:
            pricing_path = None
    pricing = {r["case_id"]: r for r in cb.read_jsonl(pricing_path)} if pricing_path else {}

    print(f"事例 {cases_path}（{len(cases)}件）")
    print(f"価格 {pricing_path or '未取得'}（{len(pricing)}件）")

    items = []
    for c in cases:
        r = evaluate(c, conditions, excludes, pricing.get(c["case_id"]))
        axes_met = [a for a, spec in axes.items()
                    if r["by_axis"].get(a, 0) >= int(spec["conditions_required"])]
        assigned = [k["id"] for k in cats if any(p.search(case_text(c)) for p in k["patterns"])]
        items.append({
            "case_id": c["case_id"], "kind": c["kind"], "title": c["title"],
            "url": c["url"], "discussion_url": c["discussion_url"],
            "points": c.get("points"), "created_at": c.get("created_at"),
            "categories": assigned,
            "axes_met": axes_met, "axes_met_count": len(axes_met),
            "matched": r["matched"], "by_axis": r["by_axis"],
            "evidence": r["evidence"], "exclude_marks": r["exclude_marks"],
            "pricing_fetched": c["case_id"] in pricing,
        })

    dist = Counter(i["axes_met_count"] for i in items)
    cond_count = Counter(m for i in items for m in i["matched"])
    cat_count = Counter(k for i in items for k in i["categories"])
    summary = {
        "screened_on": cb.today().isoformat(),
        "cases_file": os.path.basename(cases_path),
        "pricing_file": os.path.basename(pricing_path) if pricing_path else None,
        "n_cases": len(items),
        "n_pricing_fetched": sum(1 for i in items if i["pricing_fetched"]),
        "axes_met_histogram": {str(k): dist[k] for k in sorted(dist)},
        "condition_hits": dict(cond_count.most_common()),
        "category_hits": dict(cat_count.most_common()),
        "uncategorized": sum(1 for i in items if not i["categories"]),
        "exclude_marked": sum(1 for i in items if i["exclude_marks"]),
    }
    items.sort(key=lambda i: (-i["axes_met_count"], -(i["points"] or 0)))
    out_path = os.path.join(ns.out, f"screen-{cb.stamp()}.json")
    cb.write_json(out_path, {"summary": summary, "axes": axes, "items": items})

    print(f"\n[ 該当軸数の分布 ] 全{len(items)}件")
    for k in sorted(dist):
        print(f"  {k}軸該当 {dist[k]:>4}件  {'#' * min(dist[k], 50)}")
    print("\n[ 軸ごとの内訳 ]")
    for a, spec in axes.items():
        n = sum(1 for i in items if a in i["axes_met"])
        print(f"  {spec['label']:<28} {n:>4}件 / {len(items)}件")
    print("\n[ 分類 ]")
    for k, n in cat_count.most_common():
        print(f"  {k:<16} {n:>4}件")
    print(f"  {'未分類':<16} {summary['uncategorized']:>4}件")
    if summary["exclude_marked"]:
        print(f"\n対象外の印 {summary['exclude_marked']}件（削除はしていません。見直せる形で残します）")
    if summary["n_pricing_fetched"] < len(items):
        print(f"\n注意: 価格の証拠が未取得の事例が {len(items) - summary['n_pricing_fetched']}件あります。"
              "Stock性の判定は、その分だけ弱い証拠に依っています。")
    print(f"\n書き出し: {out_path}")
    print("次: python tools/jp_market_check.py（日本側の実測）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
