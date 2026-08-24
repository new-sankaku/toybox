#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""段階B: 粗い取捨選択（規則ベース）。AI を使わず、機械的に判定できるものだけを見ます。

判定は出しますが決定はしません（AUTOMATION.md §2 制約8）。
閾値は config/discovery_rules.yaml から読みます（制約3）。

使い方:
  python tools/discovery/screen.py --bodies log/bodies/ --rules config/discovery_rules.yaml
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

NAV_WORDS = ["ログイン", "会員登録", "新規登録", "トレンド", "シェアする", "はてなブックマーク",
             "いいねしたユーザー", "記事を削除", "お問い合わせ", "利用規約", "検索"]


def load_rules(path: Path) -> dict:
    """yaml が無い環境でも動くよう、必要な構造だけを読む簡易 parser。"""
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except ImportError:
        raise SystemExit("pyyaml が要ります: pip install pyyaml")


def count_hits(text: str, markers) -> list[str]:
    return [m for m in markers if m in text]


def count_patterns(text: str, patterns) -> list[str]:
    return [p for p in patterns if re.search(p, text)]


def screen(text: str, r: dict) -> dict:
    flags, evidence = [], {}

    if len(text) < r["body"]["min_chars"]:
        flags.append("body_too_short")
    evidence["chars"] = len(text)

    nav = sum(text.count(w) for w in NAV_WORDS)
    nav_ratio = nav * 6 / max(len(text), 1)
    evidence["nav_ratio"] = round(nav_ratio, 3)
    if nav_ratio > r["body"]["nav_ratio_max"]:
        flags.append("nav_heavy")

    fp = count_hits(text, r["first_person"]["markers"])
    evidence["first_person"] = fp
    if len(fp) < r["first_person"]["min_hits"]:
        flags.append("no_first_person")

    tp = count_hits(text, r["third_party_report"]["markers"])
    evidence["third_party"] = tp
    if len(tp) >= r["third_party_report"]["min_hits"]:
        flags.append("third_party_report")

    price = count_patterns(text, r["promotion"]["price_patterns"])
    solicit = count_hits(text, r["promotion"]["solicit_markers"])
    evidence["price"], evidence["solicit"] = price, solicit
    if (price and solicit) if r["promotion"]["require_both"] else (price or solicit):
        flags.append("promotion")

    weak = count_hits(text, r["build_motive"]["weak_motive_markers"])
    evidence["weak_motive"] = weak
    if weak:
        flags.append("weak_motive")

    q = count_patterns(text, r["quantified_pain"]["patterns"])
    evidence["quantified"] = q
    if len(q) < r["quantified_pain"]["min_distinct"]:
        flags.append("no_quantified_pain")

    inv = count_hits(text, r["investment"]["markers"])
    evidence["investment"] = inv
    if len(inv) < r["investment"]["min_hits"]:
        flags.append("no_investment")

    return {"flags": flags, "evidence": evidence}


def main() -> int:
    p = argparse.ArgumentParser(description="粗い取捨選択（規則ベース）")
    p.add_argument("--bodies", required=True, help="fetch_body.py の出力 directory")
    p.add_argument("--rules", required=True)
    p.add_argument("--json", action="store_true")
    a = p.parse_args()

    rules = load_rules(Path(a.rules))
    today = datetime.date.today().isoformat()
    files = sorted(Path(a.bodies).glob("*.txt"))
    if not files:
        raise SystemExit(f"本文 file がありません: {a.bodies}")

    rows = []
    for f in files:
        res = screen(f.read_text(encoding="utf-8"), rules)
        rows.append({"slug": f.stem, **res})

    order = rules["report"]["flags_order"]
    rows.sort(key=lambda x: (len(x["flags"]), [order.index(g) for g in x["flags"]] or [99]))

    print(f"判定日 {today} / 規則 v{rules['meta']['version']} / 対象 {len(rows)}件\n")
    print(f"{'旗':>3}  {'字数':>6}  slug / 立った旗")
    print("-" * 78)
    for r in rows:
        print(f"{len(r['flags']):>3}  {r['evidence']['chars']:>6}  {r['slug'][:44]}")
        if r["flags"]:
            print(f"        └ {' / '.join(r['flags'])}")

    clean = [r for r in rows if not r["flags"]]
    print(f"\n旗ゼロ: {len(clean)}件 / {len(rows)}件")
    print("**旗が立った＝棄却ではありません。人が本文を見る対象を絞るための印です。**")

    out = Path(a.bodies) / f"screen-{today.replace('-', '')}.json"
    out.write_text(json.dumps({"screened_on": today, "rules_version": rules["meta"]["version"],
                               "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"書き出し: {out}")
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
