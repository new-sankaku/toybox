#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程2 価格の証拠。事例の site を実際に見に行き、継続課金の表示を採取します。

「Stock型か」は本人の宣伝文ではなく、価格表で判定するのが最も硬い証拠です。
判定はしません。合致した文字列とその出所 URL を残すだけです。

robots.txt を尊重し、1事例あたりの request は config/sources.yaml の上限までです。
取得できなかったものは、取得できなかったこととして記録します（代替値で埋めません）。

使い方:
  python tools/fetch_pricing.py --limit 40
  python tools/fetch_pricing.py --cases log/cases-20260824.jsonl --limit 40
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import urllib.parse
import urllib.robotparser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import casebase as cb

TAG = re.compile(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>|<[^>]+>")
SPACE = re.compile(r"\s+")
HREF = re.compile(r"""(?i)href\s*=\s*["']([^"']+)["']""")


def pricing_links(html: str, base: str, paths: list[str]) -> list[str]:
    """本文中の link から、config/sources.yaml の pricing_paths に当たるものを拾います。"""
    keys = [p.strip("/").lower() for p in paths]
    out = []
    for href in HREF.findall(html):
        low = href.lower()
        if any(k in low for k in keys):
            out.append(urllib.parse.urljoin(base, href))
    return out
SKIP_HOSTS = ("news.ycombinator.com",)


def to_text(html: str) -> str:
    return SPACE.sub(" ", TAG.sub(" ", html)).strip()


def robots_allowed(url: str, cache: dict, timeout: int) -> bool | None:
    """RFC 9309 の扱い。200 は解釈、401/403 は全面禁止、その他 4xx は不在＝許可、
    取得不能（5xx・通信断）は None＝不明。不明なものは取りに行きません。"""
    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in cache:
        try:
            text, _, _ = cb.http_text(origin + "/robots.txt", timeout=timeout, max_bytes=200_000)
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(text.splitlines())
            cache[origin] = rp
        except cb.SourceError as e:
            if e.status in (401, 403):
                cache[origin] = False
            elif e.status is not None and 400 <= e.status < 500:
                cache[origin] = True
            else:
                cache[origin] = None
    rp = cache[origin]
    if isinstance(rp, bool) or rp is None:
        return rp
    return rp.can_fetch(cb.UA, url)


def match_all(patterns: list[re.Pattern], text: str, limit: int = 3) -> list[dict]:
    out = []
    for p in patterns:
        for m in list(p.finditer(text))[:limit]:
            s = max(0, m.start() - 40)
            out.append({"pattern": p.pattern, "sample": text[s:m.end() + 40].strip()})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="工程2: 事例 site から価格の証拠を採取")
    ap.add_argument("--cases", help="既定は log/ の最新 cases-*.jsonl")
    ap.add_argument("--screen", default=cb.path("config", "screen.yaml"))
    ap.add_argument("--sources", default=cb.path("config", "sources.yaml"))
    ap.add_argument("--limit", type=int, default=40, help="見に行く事例数の上限（全走査の禁止）")
    ap.add_argument("--min-points", type=int, default=0, help="この点数未満の事例は見に行かない")
    ap.add_argument("--kind", choices=["product", "failure"], default="product",
                    help="価格表があるのは製品化事例です。既定は product のみを見に行きます")
    ap.add_argument("--out", default=cb.path("log"))
    ns = ap.parse_args(argv)

    conf = cb.load_yaml(ns.sources)["page_fetch"]
    screen = cb.load_yaml(ns.screen)
    patterns = [re.compile(p) for c in screen["conditions"] if c["evidence"] == "pricing" for p in c["any_of"]]
    if not patterns:
        raise SystemExit("config/screen.yaml に evidence: pricing の条件がありません。")

    cases_path = ns.cases or cb.latest(ns.out, "cases-*.jsonl", "tools/collect_cases.py")
    cases = [c for c in cb.read_jsonl(cases_path) if not c["case_id"].endswith("-failures")]
    day_stamp = cb.stamp()
    out_path = os.path.join(ns.out, f"pricing-{day_stamp}.jsonl")
    done = {r["case_id"] for r in cb.read_jsonl(out_path)} if os.path.exists(out_path) else set()

    targets = []
    for c in cases:
        if c["case_id"] in done or (c.get("points") or 0) < ns.min_points:
            continue
        if ns.kind and c.get("kind") != ns.kind:
            continue
        host = urllib.parse.urlsplit(c["url"]).netloc.lower()
        if not c["url"].startswith("http") or host.endswith(SKIP_HOSTS):
            continue
        targets.append(c)
    targets.sort(key=lambda c: -(c.get("points") or 0))
    dropped = max(0, len(targets) - ns.limit)
    targets = targets[:ns.limit]

    print(f"入力 {cases_path}")
    print(f"対象 {len(targets)}件（取得済み {len(done)}件は飛ばします / 上限 --limit {ns.limit}）")

    budget = cb.Budget(cb.load_yaml(ns.sources).get("budget", {}))
    manifest = cb.Manifest("fetch_pricing", vars(ns))
    rows, cache = [], {}
    timeout, sleep = int(conf["timeout_seconds"]), float(conf["sleep_seconds"])
    for i, c in enumerate(targets, 1):
        rec = {"case_id": c["case_id"], "title": c["title"], "url": c["url"],
               "fetched_on": cb.today().isoformat(), "robots": None, "state": "not_attempted",
               "pages": [], "matches": [], "errors": []}
        allowed = robots_allowed(c["url"], cache, timeout)
        rec["robots"] = {True: "allowed", False: "disallowed", None: "unknown"}[allowed]
        if allowed is not True:
            rec["errors"].append(f"robots {rec['robots']} のため取得しません")
            rec["state"] = "not_attempted"
            rows.append(rec)
            print(f"  [{i:>3}/{len(targets)}] skip robots={rec['robots']:<10} {c['title'][:48]}")
            continue

        urls, i = [c["url"]], 0
        while i < len(urls) and len(rec["pages"]) < int(conf["max_pages_per_case"]):
            u = urls[i]
            i += 1
            try:
                html, final, status = cb.http_text(u, timeout=timeout, budget=budget)
            except cb.SourceError as e:
                rec["errors"].append(str(e))
                continue
            cb.save_raw("pages", f"{c['case_id']}-{len(rec['pages'])}", html, day_stamp, ns.out, ext="html")
            text = to_text(html)
            rec["pages"].append({"url": final, "status": status, "text_length": len(text)})
            rec["matches"].extend(match_all(patterns, text))
            if not rec["matches"] and len(rec["pages"]) < int(conf["max_pages_per_case"]):
                for nxt in pricing_links(html, final, conf["pricing_paths"]):
                    if nxt not in urls and robots_allowed(nxt, cache, timeout) is True:
                        urls.append(nxt)
                        break
            time.sleep(sleep)

        rec["state"] = "fetched" if rec["pages"] else "failed"
        rows.append(rec)
        mark = f"価格の証拠 {len(rec['matches'])}件" if rec["matches"] else (
            "取得失敗" if rec["state"] == "failed" else "証拠なし")
        print(f"  [{i:>3}/{len(targets)}] {mark:<16} {c['title'][:48]}")

    cb.write_jsonl(out_path, cb.read_jsonl(out_path) + rows if os.path.exists(out_path) else rows)
    hit = sum(1 for r in rows if r["matches"])
    fetched = sum(1 for r in rows if r["state"] == "fetched")
    failed = sum(1 for r in rows if r["state"] == "failed")
    skipped = sum(1 for r in rows if r["state"] == "not_attempted")
    manifest.count(targets=len(rows), with_evidence=hit, fetched=fetched,
                   failed=failed, not_attempted=skipped, dropped_over_limit=dropped)
    manifest.output(out_path)
    manifest.write(ns.out, budget)
    if dropped:
        print(f"\n注意: --limit {ns.limit} を超えた {dropped}件は見に行っていません（黙って切りません）。")
    print(f"\n価格の証拠あり {hit}件 / 取得したが証拠なし {fetched - hit}件 / "
          f"取得失敗 {failed}件 / 取りに行かなかった {skipped}件")
    print(f"書き出し: {out_path}")
    print(f"生 HTML: {os.path.join(ns.out, 'raw', 'pages', day_stamp)}/（git には入れません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
