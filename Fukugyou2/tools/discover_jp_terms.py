#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程0b 日本語の語の自動発見。分類ごとの日本語の語を、Qiita の tag から広げます。

日本語は分かち書きが無いため、英語と同じ n-gram では語を切り出せません。
形態素解析を持ち込む代わりに、**Qiita の tag をそのまま語の単位として使います**。
tag は投稿者が付けた既存の語彙なので、切り出しが不要で、表記ゆれも比較的少ない単位です。

  1. 対象 corpus  分類の既存の需要語で記事を引き、その tag を集めます
  2. 比較 corpus  query 無しの新着記事を取り、その tag を集めます（一般的な話題の分布）
  3. keyness      対象に偏る tag を G^2 で選びます
  4. 検証         提案 tag で引き直し、総件数が帯に入るかと、**元の分類の tag を含む記事の割合**
                  （適合率）を実測します。帯に入るだけでは「Qiita で人気の tag」に過ぎません
  5. 出力         config/jp_terms_auto-YYYYMMDD.yaml（分類ごとの提案語と実測値）

**限界:** Qiita の tag は技術名に偏ります。非 IT 業界の語は出ません。
出力は `config/categories.yaml` を自動で書き換えず、別 file に出します。採否は人が決めます。

使い方:
  python tools/discover_jp_terms.py --only billing
  QIITA_TOKEN=xxxx python tools/discover_jp_terms.py --only billing compliance --limit 2
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.parse
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import casebase as cb


def qiita_items(source: dict, params: dict, token: str | None, budget: cb.Budget) -> tuple[list[dict], int | None]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    data, _, head = cb.http_json(f"{source['search_endpoint']}?{urllib.parse.urlencode(params)}",
                                 headers=headers, timeout=int(source["timeout_seconds"]), budget=budget)
    total = int(head[source["total_count_header"]]) if source["total_count_header"] in head else None
    return data if isinstance(data, list) else [], total


def tags_of(items: list[dict]) -> list[list[str]]:
    return [[t["name"].lower() for t in it.get("tags", [])] for it in items]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="工程0b: 日本語の語を Qiita の tag から広げる")
    ap.add_argument("--categories", default=cb.path("config", "categories.yaml"))
    ap.add_argument("--discovery", default=cb.path("config", "discovery.yaml"))
    ap.add_argument("--sources", default=cb.path("config", "sources.yaml"))
    ap.add_argument("--only", nargs="*", help="分類 id を指定")
    ap.add_argument("--limit", type=int, default=2, help="扱う分類の上限（Qiita は認証なし 60 req/h）")
    ap.add_argument("--out", default=cb.path("log"))
    ns = ap.parse_args(argv)

    conf = cb.load_yaml(ns.discovery)
    jp = conf["jp_expansion"]
    qiita = cb.load_yaml(ns.sources)["qiita"]
    cats = cb.load_yaml(ns.categories)["categories"]
    if ns.only:
        unknown = set(ns.only) - {c["id"] for c in cats}
        if unknown:
            raise SystemExit(f"分類 id が config/categories.yaml にありません: {sorted(unknown)}")
        cats = [c for c in cats if c["id"] in ns.only]
    if len(cats) > ns.limit:
        raise SystemExit(f"分類が {len(cats)} 件あり、--limit {ns.limit} を超えました。"
                         "Qiita は認証なし 60 request/時です。--only で絞ってください。")

    token = os.environ.get(qiita["token_env"])
    budget = cb.Budget(conf["budget"])
    manifest = cb.Manifest("discover_jp_terms", vars(ns))
    sleep = float(qiita["sleep_seconds"])
    print(f"取得日 {cb.today()} / 分類 {len(cats)}件 / Qiita token {'あり' if token else 'なし（60 req/h）'}")

    print("[1] 比較 corpus（query 無しの新着記事）")
    background, seen_bg = [], set()
    for page in range(1, int(jp["background_pages"]) + 1):
        items, _ = qiita_items(qiita, {"per_page": int(jp["background_per_page"]), "page": page},
                               token, budget)
        for it in items:
            if it.get("id") not in seen_bg:
                seen_bg.add(it.get("id"))
                background.append(it)
        time.sleep(sleep)
    bg_docs = tags_of(background)
    print(f"    {len(background)}件 / tag {sum(len(d) for d in bg_docs)}個")

    results, failures = [], []
    for c in cats:
        print(f"\n[2] {c['id']} {c['label']}")
        target, known_terms = [], {t.lower() for t in c["jp_demand_terms"] + c["jp_supply_terms"]}
        tag_seeds: dict[str, set[str]] = {}
        for term in c["jp_demand_terms"]:
            try:
                items, _ = qiita_items(qiita, {"query": term, "per_page": int(jp["items_per_term"])}, token, budget)
            except cb.SourceError as e:
                failures.append({"category": c["id"], "term": term, "error": str(e)})
                cb.eprint(f"    失敗: {term} — {e}")
                continue
            items = [it for it in items if it.get("id") not in {x.get("id") for x in target}]
            target.extend(items)
            for doc in tags_of(items):
                for tag in doc:
                    tag_seeds.setdefault(tag, set()).add(term)
            time.sleep(sleep)
        if not target:
            failures.append({"category": c["id"], "error": "対象記事が0件です"})
            cb.eprint("    対象記事が0件のため、この分類は飛ばします（代替値では埋めません）。")
            continue

        target_tags = {t for doc in tags_of(target) for t in doc}
        ranked = cb.keyness(tags_of(target), bg_docs, min_count=int(jp["min_count"]),
                            top_k=int(jp["top_k"]), min_docs=int(jp["min_docs"]),
                            min_g2=float(conf["scoring"]["min_g2"]),
                            min_log_ratio=float(conf["scoring"]["min_log_ratio"]))
        proposals = []
        for r in ranked:
            if r["term"] in known_terms:
                continue
            if len(tag_seeds.get(r["term"], ())) < int(jp["min_terms"]):
                continue
            try:
                sample, total = qiita_items(qiita, {"query": r["term"],
                                                    "per_page": int(jp["validate_items"])}, token, budget)
            except cb.SourceError as e:
                failures.append({"category": c["id"], "term": r["term"], "error": str(e)})
                continue
            time.sleep(sleep)
            related = sum(1 for doc in tags_of(sample)
                          if (set(doc) - {r["term"]}) & (target_tags - {r["term"]}))
            precision = round(related / len(sample), 3) if sample else None
            lower = round(cb.wilson_lower(related, len(sample)), 3) if sample else None
            reasons = []
            if total is None:
                reasons.append("総件数が取れませんでした")
            elif not (int(jp["min_total_hits"]) <= total <= int(jp["max_total_hits"])):
                reasons.append(f"総件数 {total} が帯 {jp['min_total_hits']}〜{jp['max_total_hits']} の外です")
            if lower is None:
                reasons.append("測定不能（記事0件）")
            elif lower < float(jp["min_precision"]):
                reasons.append(f"適合率の下限 {lower} < {jp['min_precision']}")
            ok = not reasons
            row = {"term": r["term"], "g2": r["g2"], "log_ratio": r["log_ratio"],
                   "target_docs": r["target_docs"], "seed_terms": sorted(tag_seeds.get(r["term"], ())),
                   "qiita_total": total, "precision": precision, "precision_lower": lower,
                   "accepted": ok}
            if reasons:
                row["rejected_for"] = reasons
            proposals.append(row)
            mark = "採用" if ok else "却下"
            print(f"    {mark} {r['term'][:22]:<22} G^2 {r['g2']:>7} 記事{r['target_docs']:>3}件 "
                  f"語{len(row['seed_terms'])}種 総件数 {total} 適合率下限 {lower}")

        results.append({"id": c["id"], "label": c["label"], "target_items": len(target),
                        "proposals": proposals,
                        "accepted": [p["term"] for p in proposals if p["accepted"]]})

    if not results:
        raise SystemExit("1分類も測定できませんでした。代替値では埋めません。")

    day_stamp = cb.stamp()
    run_at = manifest.data["started_at"][11:19].replace(":", "")
    out_json = os.path.join(ns.out, f"discovery-jp-{day_stamp}-{run_at}.json")
    cb.write_json(out_json, {"discovered_on": cb.today().isoformat(),
                             "background_items": len(background),
                             "limits": ["Qiita の tag は技術名に偏るため、非 IT 業界の語は出ません",
                                        "tag は投稿者が付けた語であり、困りごとの言葉とは限りません"],
                             "failures": failures, "categories": results})
    yaml_path = cb.path("config", f"jp_terms_auto-{day_stamp}.yaml")
    lines = [f"# 分類ごとの日本語の提案語（自動発見 {cb.today()}）。人が書いた語ではありません。",
             f"# 実測値は log/{os.path.basename(out_json)} にあります。",
             "# categories.yaml へは自動反映しません。採否は人が決めます。", "categories:"]
    for r in results:
        lines.append(f"  - id: {r['id']}")
        lines.append(f"    label: {r['label']}")
        lines.append("    proposed_terms: [" + ", ".join(f'"{t}"' for t in r["accepted"]) + "]")
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    manifest.count(categories=len(results), proposals=sum(len(r["proposals"]) for r in results),
                   accepted=sum(len(r["accepted"]) for r in results))
    for f_ in failures:
        manifest.fail(**f_)
    manifest.output(out_json)
    manifest.output(yaml_path)
    manifest.write(ns.out, budget)
    print(f"\n提案 {sum(len(r['accepted']) for r in results)}語 / 失敗 {len(failures)}件")
    print(f"記録: {out_json}")
    print(f"提案語: {yaml_path}")
    print(f"request: {budget.report()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
