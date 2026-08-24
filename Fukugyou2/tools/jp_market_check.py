#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程4 日本側の実測。分類ごとに、日本語圏と英語圏の言及量を数えます。

測るのは「言及の件数」だけです。需要そのものではありません（doc/METHOD.md §6 の限界）。
判定はしません。数字と取得日と出所を出すところで止めます。

  英語圏 : Hacker News の該当件数（en_terms）
  日本語圏: Qiita の総件数（total-count header）と Zenn の取得件数（上限つき）

Qiita は認証なしで 60 req/h です。残数 header を見て、足りなくなったら
その場で止めて「未測定」として残します（代替値では埋めません）。
環境変数 QIITA_TOKEN があれば使います（1000 req/h）。

使い方:
  python tools/jp_market_check.py --limit 4
  QIITA_TOKEN=xxxx python tools/jp_market_check.py --limit 10
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import casebase as cb


def hn_count(source: dict, term: str) -> int:
    params = urllib.parse.urlencode({"query": term, "tags": "story", "hitsPerPage": 1})
    data, _, _ = cb.http_json(f"{source['search_endpoint']}?{params}", timeout=int(source["timeout_seconds"]))
    return int(data.get("nbHits", 0))


def qiita_count(source: dict, term: str, token: str | None) -> tuple[int, int | None]:
    params = urllib.parse.urlencode({"query": term, "per_page": 1})
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    _, _, head = cb.http_json(f"{source['search_endpoint']}?{params}", headers=headers,
                              timeout=int(source["timeout_seconds"]))
    total = int(head.get(source["total_count_header"], 0))
    remaining = int(head["rate-remaining"]) if "rate-remaining" in head else None
    return total, remaining


def zenn_count(source: dict, term: str) -> tuple[int, bool]:
    """総件数を返さない API のため、上限 page までの実数と 打ち切りの有無 を返します。"""
    total, page, truncated = 0, 1, False
    for _ in range(int(source["max_pages"])):
        params = urllib.parse.urlencode({"q": term, "source": "articles", "order": "daily", "page": page})
        data, _, _ = cb.http_json(f"{source['search_endpoint']}?{params}", timeout=int(source["timeout_seconds"]))
        total += len(data.get("articles", []))
        nxt = data.get("next_page")
        if not nxt:
            return total, False
        page, truncated = nxt, True
        time.sleep(float(source["sleep_seconds"]))
    return total, truncated


def measure(terms: list[str], fn, failures: list, label: str) -> dict:
    out = {}
    for t in terms:
        try:
            out[t] = fn(t)
        except cb.SourceError as e:
            failures.append({"where": label, "term": t, "error": str(e)})
            cb.eprint(f"    失敗: {label} / {t} — {e}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="工程4: 分類ごとの 日本語圏 / 英語圏 の言及量")
    ap.add_argument("--categories", default=cb.path("config", "categories.yaml"))
    ap.add_argument("--sources", default=cb.path("config", "sources.yaml"))
    ap.add_argument("--limit", type=int, default=4, help="測る分類の上限（Qiita の 60 req/h に対する保護）")
    ap.add_argument("--only", nargs="*", help="分類 id を指定して測る")
    ap.add_argument("--out", default=cb.path("log"))
    ns = ap.parse_args(argv)

    src = cb.load_yaml(ns.sources)
    hn, qiita, zenn = src["hn_algolia"], src["qiita"], src["zenn"]
    cats = cb.load_yaml(ns.categories)["categories"]
    if ns.only:
        cats = [c for c in cats if c["id"] in ns.only]
        if not cats:
            raise SystemExit(f"分類 id が見つかりません: {ns.only}")
    if len(cats) > ns.limit:
        raise SystemExit(f"分類が {len(cats)} 件あり、--limit {ns.limit} を超えました。"
                         f"Qiita は認証なし 60 req/h です。--only で絞るか --limit を明示的に上げてください。")

    token = os.environ.get(qiita["token_env"])
    print(f"取得日 {cb.today()} / 分類 {len(cats)}件 / Qiita token {'あり' if token else 'なし（60 req/h）'}")

    results, failures, stopped = [], [], None
    for c in cats:
        print(f"\n[{c['id']}] {c['label']}")
        row = {"id": c["id"], "label": c["label"], "measured_on": cb.today().isoformat()}

        row["en_hn"] = measure(c["en_terms"], lambda t: hn_count(hn, t), failures, "hn")
        time.sleep(float(hn["sleep_seconds"]))

        q_demand, q_supply, remaining = {}, {}, None
        for bucket, terms in (("demand", c["jp_demand_terms"]), ("supply", c["jp_supply_terms"])):
            for t in terms:
                if remaining is not None and remaining < 3:
                    stopped = f"Qiita の残り request が {remaining} 件になったため中断しました"
                    break
                try:
                    total, remaining = qiita_count(qiita, t, token)
                    (q_demand if bucket == "demand" else q_supply)[t] = total
                except cb.SourceError as e:
                    failures.append({"where": "qiita", "term": t, "error": str(e)})
                    cb.eprint(f"    失敗: qiita / {t} — {e}")
                time.sleep(float(qiita["sleep_seconds"]))
            if stopped:
                break
        row["jp_qiita_demand"], row["jp_qiita_supply"] = q_demand, q_supply
        row["qiita_rate_remaining"] = remaining

        row["jp_zenn_demand"] = measure(c["jp_demand_terms"], lambda t: zenn_count(zenn, t), failures, "zenn")
        time.sleep(float(zenn["sleep_seconds"]))

        en_total = sum(row["en_hn"].values())
        jp_demand_total = sum(q_demand.values())
        jp_supply_total = sum(q_supply.values())
        row["totals"] = {
            "en_hn": en_total,
            "jp_qiita_demand": jp_demand_total,
            "jp_qiita_supply": jp_supply_total,
            "jp_per_en": round(jp_demand_total / en_total, 3) if en_total else None,
            "demand_per_supply": round(jp_demand_total / jp_supply_total, 3) if jp_supply_total else None,
        }
        t = row["totals"]
        print(f"  英語圏 HN {t['en_hn']:>6} 件 / 日本 Qiita 需要語 {t['jp_qiita_demand']:>6} 件 "
              f"/ 供給語 {t['jp_qiita_supply']:>6} 件")
        print(f"  日本÷英語 {t['jp_per_en']} / 需要÷供給 {t['demand_per_supply']}"
              f"  Zenn（上限つき実数）{sum(v[0] for v in row['jp_zenn_demand'].values())}")
        results.append(row)
        if stopped:
            cb.eprint(f"  中断: {stopped}")
            break

    if not results:
        raise SystemExit("1件も測定できませんでした。代替値では埋めません。")

    n_this_run = len(results)
    out_path = os.path.join(ns.out, f"jp-market-{cb.stamp()}.json")
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            kept = [c for c in json.load(f)["categories"] if c["id"] not in {r["id"] for r in results}]
        results = kept + results
    cb.write_json(out_path, {
        "measured_on": cb.today().isoformat(),
        "sources": {"hn": hn["search_endpoint"], "qiita": qiita["search_endpoint"], "zenn": zenn["search_endpoint"]},
        "limits": ["言及量は需要ではありません（代理指標です）",
                   "Qiita / Zenn は技術者に偏るため、非 IT 業界の需要は過小に出ます",
                   "Zenn は総件数を返さないため、上限 page までの実数です",
                   f"この file には {len(results)} 分類が入っています（分類ごとの測定日は measured_on を見てください）"],
        "stopped": stopped,
        "failures": failures,
        "categories": results,
    })
    print(f"\n今回の測定 {n_this_run}/{len(cats)}分類 / file 内 合計 {len(results)}分類 / 失敗 {len(failures)}件")
    if stopped:
        print(f"中断: {stopped}（未測定は未測定のまま残しています）")
    print(f"書き出し: {out_path}")
    print("次: python tools/transfer_matrix.py（他業界への転用）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
