#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""段階C の検算: AI が出した抽出結果の引用が、全文に実在するかを機械照合する。

これは AI の代わりではなく、AI の監査です。
2026-08-18 に、snippet を全文と誤認した抽出をそのまま採用する失敗をしました。
引用が原文に無ければ、その項目は「記載なし」に落とします。

入力の JSON は AI が埋めます（1件1 object）:
  {"slug": "...", "fields": {"pain": {"value": "...", "quote": "原文そのまま"} , ...}}

使い方:
  python tools/discovery/verify_quotes.py --bodies log/bodies/ --extract log/extract.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import unicodedata
from pathlib import Path


def normalize(s: str) -> str:
    """照合用の正規化。全角半角と空白の揺れだけを吸収し、語は変えない。"""
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"\s+", "", s)


def verify(body: str, quote: str) -> tuple[bool, float]:
    """(完全一致したか, 最長一致率) を返す。"""
    nb, nq = normalize(body), normalize(quote)
    if not nq:
        return False, 0.0
    if nq in nb:
        return True, 1.0
    best = 0
    for size in range(len(nq), 0, -max(1, len(nq) // 40)):
        for start in range(0, len(nq) - size + 1):
            if nq[start:start + size] in nb:
                best = size
                break
        if best:
            break
    return False, best / len(nq)


def main() -> int:
    p = argparse.ArgumentParser(description="AI 抽出の引用を全文と照合する")
    p.add_argument("--bodies", required=True)
    p.add_argument("--extract", required=True, help="AI が埋めた抽出結果 JSON")
    p.add_argument("--min-ratio", type=float, default=1.0,
                   help="この一致率未満の引用は不採用にする（既定は完全一致のみ）")
    a = p.parse_args()

    today = datetime.date.today().isoformat()
    items = json.loads(Path(a.extract).read_text(encoding="utf-8"))
    if isinstance(items, dict):
        items = items.get("items", [])

    bodies = {f.stem: f.read_text(encoding="utf-8") for f in Path(a.bodies).glob("*.txt")}
    total = ok = dropped = missing = 0
    report = []

    for it in items:
        slug = it["slug"]
        body = bodies.get(slug)
        if body is None:
            print(f"  本文なし: {slug}（照合できないので全項目を記載なしに落とします）")
            missing += 1
            report.append({"slug": slug, "body_found": False, "fields": {}})
            continue

        fields = {}
        for name, f in it.get("fields", {}).items():
            total += 1
            quote = (f or {}).get("quote") or ""
            hit, ratio = verify(body, quote)
            accepted = hit or ratio >= a.min_ratio
            if accepted:
                ok += 1
            else:
                dropped += 1
            fields[name] = {"value": f.get("value") if accepted else "記載なし（引用が原文に不在）",
                            "quote": quote, "match_ratio": round(ratio, 3),
                            "accepted": accepted}
        report.append({"slug": slug, "body_found": True, "fields": fields})

    print(f"\n照合日 {today} / 項目 {total}件")
    print(f"  引用が原文に実在  : {ok}件")
    print(f"  不在のため記載なし: {dropped}件")
    print(f"  本文が無く照合不能: {missing}件\n")
    for r in report:
        bad = [n for n, f in r["fields"].items() if not f["accepted"]]
        mark = "NG" if bad or not r["body_found"] else "OK"
        print(f"  [{mark}] {r['slug'][:52]}" + (f"  落とした項目: {', '.join(bad)}" if bad else ""))

    out = Path(a.extract).with_name(f"verified-{today.replace('-', '')}.json")
    out.write_text(json.dumps({"verified_on": today, "min_ratio": a.min_ratio,
                               "items": report}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n書き出し: {out}")
    print("**引用が原文に無い項目は、AI が何と書いていても採用しません。**")
    return 1 if dropped or missing else 0


if __name__ == "__main__":
    sys.exit(main())
