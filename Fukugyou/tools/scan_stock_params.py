#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""掲載からの集客数を実測する。doc/research/H_stock_params.md の再現用。

測るのは「導入数の月あたりの増加」= active_installs ÷ 登録からの経過月数。

設計上の制約（doc/AUTOMATION.md §2）:
  - 候補を生成しない。keyword は人が書いた file から読む
  - 全走査しない。--limit と --top が必須の上限
  - 平均を出さない。分布（p25 / 中央値 / p75）で出す
  - 取得日を出力に刻む
  - 生 response を保存する
  - API 失敗時は fallback せず、失敗として記録して落とす
  - 判定は出すが、決定はしない

使い方:
  python tools/scan_stock_params.py --keywords config/keywords_business.txt
  python tools/scan_stock_params.py --keywords config/keywords_business.txt --out log/
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request

API = "https://api.wordpress.org/plugins/info/1.2/"
MONTH_DAYS = 30.44
UA = "Fukugyou-market-research/1.0 (+doc/research/H_stock_params.md)"


def pct(values, q):
    v = sorted(values)
    if not v:
        return None
    k = (len(v) - 1) * q
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def fetch(keyword: str, top: int, timeout: int) -> dict:
    """1 keyword ぶん取得。失敗したら例外を上げる（fallback しない）。"""
    qs = urllib.parse.urlencode({
        "action": "query_plugins",
        "request[search]": keyword,
        "request[per_page]": top,
    })
    req = urllib.request.Request(API + "?" + qs, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def parse_date(text: str):
    try:
        return datetime.date(*map(int, text[:10].split("-")))
    except Exception:
        return None


def collect(keywords, top, today, timeout, sleep, min_age_months):
    rows, raw, failures = [], {}, []
    for kw in keywords:
        try:
            data = fetch(kw, top, timeout)
        except Exception as e:
            failures.append({"keyword": kw, "error": repr(e)})
            print(f"  失敗: {kw} — {e}", file=sys.stderr)
            continue
        raw[kw] = data
        for rank, p in enumerate(data.get("plugins", []), 1):
            added = parse_date(p.get("added", ""))
            if added is None:
                continue
            age_m = (today - added).days / MONTH_DAYS
            if age_m < min_age_months:
                continue          # 若すぎる掲載は増加が不安定なので除外
            installs = p.get("active_installs") or 0
            last = parse_date(p.get("last_updated", ""))
            rows.append({
                "keyword": kw, "rank": rank, "slug": p.get("slug"),
                "hits": data.get("info", {}).get("results"),
                "age_months": round(age_m, 1),
                "active_installs": installs,
                "installs_per_month": installs / age_m if age_m else 0.0,
                "months_since_update": round((today - last).days / MONTH_DAYS, 1) if last else None,
            })
        time.sleep(sleep)
    return rows, raw, failures


def summarize(rows, today):
    参入年次s = [(6, 36, "参入3年以内"), (36, 72, "3〜6年"), (72, 120, "6〜10年"), (120, 10**9, "10年超")]
    out = {"measured_on": today.isoformat(), "n_items": len(rows),
           "n_keywords": len({r["keyword"] for r in rows}), "参入年次s": []}
    for lo, hi, label in 参入年次s:
        v = [r["installs_per_month"] for r in rows if lo <= r["age_months"] < hi]
        if len(v) < 5:
            continue          # 小標本の 百分位 は出さない
        out["参入年次s"].append({
            "label": label, "n": len(v),
            "installs_per_month": {"p25": round(pct(v, .25), 1),
                                   "p50": round(statistics.median(v), 1),
                                   "p75": round(pct(v, .75), 1)},
        })
    kws = sorted({r["keyword"] for r in rows})
    newcomer = {k: [r for r in rows if r["keyword"] == k and r["age_months"] < 36] for k in kws}
    out["gate_condition_A"] = {
        "definition": "上位N件に、直近3年に登録された掲載が1件以上あるか",
        "passed": [k for k in kws if newcomer[k]],
        "failed": [k for k in kws if not newcomer[k]],
    }
    out["best_newcomer_rate"] = {
        k: round(max(r["installs_per_month"] for r in newcomer[k]), 1)
        for k in kws if newcomer[k]
    }
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="掲載からの集客数を実測（doc/research/H_stock_params.md）")
    ap.add_argument("--keywords", required=True, help="keyword を1行1語で書いた file")
    ap.add_argument("--limit", type=int, default=30, help="扱う keyword の上限（全走査の禁止）")
    ap.add_argument("--top", type=int, default=8, help="1語あたり上位何件を見るか")
    ap.add_argument("--min-age-months", type=float, default=6.0, help="これ未満の掲載は除外")
    ap.add_argument("--out", default="log", help="出力先 directory")
    ap.add_argument("--timeout", type=int, default=40)
    ap.add_argument("--sleep", type=float, default=0.4, help="request 間隔（秒）")
    ns = ap.parse_args(argv)

    keywords = [l.strip() for l in open(ns.keywords, encoding="utf-8")
                if l.strip() and not l.startswith("#")]
    if len(keywords) > ns.limit:
        raise SystemExit(f"keyword が {len(keywords)} 語あります。--limit {ns.limit} を超えました。"
                         f"全走査は禁止です（AUTOMATION.md §2 制約2）。--limit を明示的に上げてください。")

    today = datetime.date.today()
    stamp = today.strftime("%Y%m%d")
    print(f"取得 {today} / keyword {len(keywords)}語 × 上位{ns.top}件")

    rows, raw, failures = collect(keywords, ns.top, today, ns.timeout, ns.sleep, ns.min_age_months)
    if not rows:
        raise SystemExit("1件も取得できませんでした。代替値では埋めません（制約6）。")

    raw_dir = os.path.join(ns.out, "raw", "wordpress", stamp)
    os.makedirs(raw_dir, exist_ok=True)
    for kw, data in raw.items():
        safe = urllib.parse.quote(kw, safe="")
        with open(os.path.join(raw_dir, f"{safe}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    summary = summarize(rows, today)
    summary["failures"] = failures
    summary["params"] = {"top": ns.top, "min_age_months": ns.min_age_months,
                         "keywords_file": ns.keywords}
    path = os.path.join(ns.out, f"stock-params-{stamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "items": rows}, f, ensure_ascii=False, indent=1)

    print(f"\n取得 {summary['n_items']}件 / {summary['n_keywords']}語")
    if failures:
        print(f"失敗 {len(failures)}語（欠損は欠損のまま残しています）")
    print("\n[ 導入数の月あたりの増加 ]")
    for c in summary["参入年次s"]:
        p = c["installs_per_month"]
        print(f"  {c['label']:<12} n={c['n']:>3}  p25 {p['p25']:>8.1f} / 中央値 {p['p50']:>8.1f} / p75 {p['p75']:>9.1f}")
    A = summary["gate_condition_A"]
    print(f"\n[ 関門の条件A ] 上位{ns.top}件に直近3年の参入あり: "
          f"{len(A['passed'])}/{len(A['passed']) + len(A['failed'])}語")
    if A["failed"]:
        print("  無い語（新規参入が上位に入れていない領域）:")
        print("    " + ", ".join(A["failed"]))
    print(f"\n書き出し: {path}")
    print(f"生 response: {raw_dir}/")
    print("\n必要な増加数との比較は tools/economics.py で出してください。判定は出しますが決定はしません。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
