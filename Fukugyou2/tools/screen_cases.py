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
        out.append({**c, "patterns": [re.compile(p) for p in c["any_of"]],
                    "not_near_patterns": [re.compile(p) for p in c.get("not_near", [])]})
    return out


def match_in_context(cond: dict, text: str, window: int):
    """一致を探し、その前後に打ち消し語があるものは数えません。

    `$7/month VPS` は継続課金の証拠ではなく、著者が払う原価です。文字列だけを見ると
    売価と原価を区別できないため、周辺の語で打ち消します。
    """
    for p in cond["patterns"]:
        for m in p.finditer(text):
            ctx = text[max(0, m.start() - window):m.end() + window]
            if any(n.search(ctx) for n in cond["not_near_patterns"]):
                continue
            return m, ctx.strip()
    return None, None


def case_text(case: dict) -> str:
    return " \n".join(x for x in (case.get("title"), case.get("tagline"), case.get("story_text")) if x)


def evaluate(case: dict, conditions: list[dict], excludes: list[dict], pricing: dict | None,
             context_window: int = 70) -> dict:
    text = case_text(case)
    hits, evidence = [], {}
    for c in conditions:
        if c["evidence"] == "text":
            m, ctx = match_in_context(c, text, context_window)
            if m:
                hits.append(c)
                evidence[c["id"]] = ctx
        else:
            if pricing is None:
                continue
            found = next((m for m in pricing.get("matches", []) if m["pattern"] in c["any_of"]), None)
            if found:
                hits.append(c)
                evidence[c["id"]] = found["sample"]

    by_axis = Counter(c["axis"] for c in hits)
    has_price_evidence = bool((pricing or {}).get("matches"))
    marks = []
    for e in excludes:
        if e.get("unless_pricing_evidence") and has_price_evidence:
            continue
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
        r = evaluate(c, conditions, excludes, pricing.get(c["case_id"]),
                     int(screen.get("context_window", 70)))
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
            "pricing_state": pricing.get(c["case_id"], {}).get("state", "not_attempted"),
        })

    dist = Counter(i["axes_met_count"] for i in items)
    cond_count = Counter(m for i in items for m in i["matched"])
    cat_count = Counter(k for i in items for k in i["categories"])
    summary = {
        "screened_on": cb.today().isoformat(),
        "cases_file": os.path.basename(cases_path),
        "pricing_file": os.path.basename(pricing_path) if pricing_path else None,
        "n_cases": len(items),
        "pricing_states": dict(Counter(i["pricing_state"] for i in items)),
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
    st = summary["pricing_states"]
    print(f"\n[ 価格 page の状態 ] 取得 {st.get('fetched', 0)}件 / 取得失敗 {st.get('failed', 0)}件 / "
          f"取りに行っていない {st.get('not_attempted', 0)}件")
    if st.get("fetched", 0) < len(items):
        print("  注意: 取得できていない事例の Stock性は、価格表ではなく本文の語に依っています。")
    print(f"\n書き出し: {out_path}")
    print("次: python tools/jp_market_check.py（日本側の実測）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
