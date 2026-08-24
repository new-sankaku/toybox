#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程1 収集。Hacker News から 製品化済み事例・失敗事例を集めて一覧にします。

集めるだけです。要約も採点も分類もしません（doc/METHOD.md §5 規律1）。
検索語は人が config/queries_*.txt に書きます。program は語を生成しません。

使い方:
  python tools/collect_cases.py --queries config/queries_product.txt --kind product
  python tools/collect_cases.py --queries config/queries_failure.txt --kind failure --min-points 30

同じ日の実行は同じ file に併合されます（重複は case_id と URL で落とします）。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import casebase as cb

TITLE_PATTERN = re.compile(r"^(?:Show HN|Launch HN|Ask HN)\s*:\s*(?P<name>[^–—\-|:]{2,60}?)\s*[–—\-|:]\s*(?P<tagline>.+)$")


def parse_title(title: str) -> tuple[str | None, str | None]:
    m = TITLE_PATTERN.match(title.strip())
    if not m:
        return None, None
    return m.group("name").strip(), m.group("tagline").strip()


def search(source: dict, query: str, hits: int, min_points: int, since_epoch: int | None,
           budget: "cb.Budget | None" = None) -> tuple[list[dict], list[dict], int]:
    per_page = min(hits, int(source["max_hits_per_page"]))
    numeric = [f"points>={min_points}"]
    if since_epoch is not None:
        numeric.append(f"created_at_i>={since_epoch}")
    collected, pages, page, nb_hits = [], [], 0, 0
    while len(collected) < hits:
        params = urllib.parse.urlencode({
            "query": query,
            "tags": "story",
            "numericFilters": ",".join(numeric),
            "hitsPerPage": per_page,
            "page": page,
        })
        data, _, _ = cb.http_json(f"{source['search_endpoint']}?{params}",
                                  timeout=int(source["timeout_seconds"]), budget=budget)
        pages.append(data)
        nb_hits = data.get("nbHits", 0)
        got = data.get("hits", [])
        collected.extend(got)
        page += 1
        if not got or page >= data.get("nbPages", 0):
            break
        time.sleep(float(source["sleep_seconds"]))
    return collected[:hits], pages, nb_hits


def to_case(hit: dict, query: str, kind: str, item_template: str, fetched_on: str) -> dict:
    oid = str(hit.get("objectID"))
    title = hit.get("title") or hit.get("story_title") or ""
    name, tagline = parse_title(title)
    discussion = item_template.format(id=oid)
    return cb.new_case(
        case_id=f"hn:{oid}",
        source="hn_algolia",
        source_id=oid,
        kind=kind,
        title=title,
        product_name=name,
        tagline=tagline,
        url=hit.get("url") or discussion,
        discussion_url=discussion,
        points=hit.get("points"),
        num_comments=hit.get("num_comments"),
        created_at=hit.get("created_at"),
        author=hit.get("author"),
        story_text=hit.get("story_text"),
        query=query,
        fetched_on=fetched_on,
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="工程1 収集: Hacker News から事例を集める")
    ap.add_argument("--queries", required=True, help="検索語を1行1語で書いた file")
    ap.add_argument("--kind", required=True, choices=["product", "failure"], help="製品化済み / 失敗事例")
    ap.add_argument("--sources", default=cb.path("config", "sources.yaml"))
    ap.add_argument("--limit", type=int, default=20, help="扱う検索語の上限（全走査の禁止）")
    ap.add_argument("--hits", type=int, default=30, help="1語あたりの取得件数")
    ap.add_argument("--min-points", type=int, default=20, help="この点数未満の投稿は取らない")
    ap.add_argument("--since-years", type=float, default=8.0, help="何年前までを対象にするか")
    ap.add_argument("--out", default=cb.path("log"))
    ns = ap.parse_args(argv)

    source = cb.load_yaml(ns.sources)["hn_algolia"]
    queries = cb.load_terms(ns.queries, ns.limit, "検索語")
    day = cb.today()
    day_stamp = cb.stamp(day)
    since = int((datetime.datetime.now() - datetime.timedelta(days=365.25 * ns.since_years)).timestamp())

    out_path = os.path.join(ns.out, f"cases-{day_stamp}.jsonl")
    manifest = cb.Manifest("collect_cases", vars(ns))
    budget = cb.Budget()
    rows = cb.read_jsonl(out_path) if os.path.exists(out_path) else []

    print(f"取得日 {day} / {source['label']} / 検索語 {len(queries)}語 × 最大{ns.hits}件 / {ns.min_points}点以上")
    added, dup, failures = 0, 0, []
    for i, q in enumerate(queries, 1):
        try:
            hits, pages, nb = search(source, q, ns.hits, ns.min_points, since, budget)
        except cb.SourceError as e:
            failures.append({"query": q, "error": str(e)})
            cb.eprint(f"  失敗: {q} — {e}")
            continue
        cb.save_raw("hn", f"{ns.kind}-{q}", json.dumps({"query": q, "pages": pages}, ensure_ascii=False),
                    day_stamp, ns.out)
        cases = [to_case(h, q, ns.kind, source["item_url_template"], day.isoformat()) for h in hits]
        new_here, dup_here, rows = cb.merge_cases(out_path, cases)
        added += new_here
        dup += dup_here
        print(f"  [{i:>2}/{len(queries)}] {q[:44]:<44} 該当{nb:>6}件 取得{len(hits):>3} 新規{new_here:>3}")
        time.sleep(float(source["sleep_seconds"]))

    if not rows:
        raise SystemExit("1件も取得できませんでした。代替値では埋めません（doc/METHOD.md §5 規律3）。")

    manifest.count(added=added, duplicated=dup, total=len(rows), queries=len(queries))
    for f in failures:
        manifest.fail(**f)
    manifest.output(out_path)
    manifest.write(ns.out, budget)
    if failures:
        cb.write_json(os.path.join(ns.out, f"cases-{day_stamp}-failures.json"), failures)

    print(f"\n新規 {added}件 / 重複 {dup}件 / file 内 合計 {len(rows)}件")
    if failures:
        print(f"失敗 {len(failures)}語（欠損は欠損のまま残しています）")
    pts = [r["points"] for r in rows if r.get("points") is not None]
    d = cb.distribution([float(p) for p in pts])
    if d:
        print(f"点数の分布 n={d['n']} p25 {d['p25']:.0f} / 中央値 {d['p50']:.0f} / p75 {d['p75']:.0f} / 最大 {d['max']:.0f}")
    print(f"\n書き出し: {out_path}")
    print("次: python tools/fetch_pricing.py（価格の証拠）→ python tools/screen_cases.py（条件照合）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
