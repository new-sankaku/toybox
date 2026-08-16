#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""段階0 の逆算。目標粗利から、集客の手段ごとに成立可否を出す。

設計上の制約（doc/AUTOMATION.md §2）:
  - 候補を生成しない。入力は人が決めた数値だけ
  - 閾値を code に埋めない。前提は引数か config file から読む
  - 平均を出力しない。分布で持つ
  - 判定は出すが、決定はしない
  - fallback しない。入力が欠けたら落とす

使い方:
  python tools/economics.py --goal 50000 --price 15000
  python tools/economics.py --goal 500000 --config config/economics.yaml --json
  python tools/economics.py --goal 92445 --price 15000 --sweep

前提の出所は doc/MARKET_RESEARCH.md §6.4 / §6.5、実測は doc/research/H_stock_params.md。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, asdict, field

# --- 既定値。すべて出所つき。code に埋めた「閾値」ではなく「前提の初期値」であり、
#     実測が取れた時点で --config か引数で上書きすること（MARKET_RESEARCH.md §4）。
DEFAULTS = {
    "margin": 0.70,              # 利益率。Acquire.com 2024・利益の出ている SaaS の平均71%（選び方による偏り あり・楽観側）
    "churn_monthly": 0.05,      # 月次解約。ChartMogul 2023・ARR $300k 未満帯の年次 retention 中央値 54.8% の換算
    "horizon_months": 18,        # 目標に到達したい月数。自分で選ぶ量
    "budget_hours_month": 30.33, # 可処分時間。週7時間 × 4.333
    # --- 個別の声かけ（1対1接触）
    "flow_conversion": 0.005,    # 見知らぬ相手への成約率。仮置き。段階5 の実測で置き換える
    "flow_hours_contact": 0.25,  # 1人あたりの時間。仮置き
    # --- 掲載・記事（掲載・記事）
    "stock_free_to_paid": 0.01,  # 無料→有料の転換率。仮置き。最も結論を動かす未測定値
    "stock_hours_month": 4.0,    # 掲載1本の維持。仮置き
    "stock_hours_build": 40.0,   # 掲載1本の構築。仮置き
    # --- 契約数そのものが食う時間
    "support_hours_contract": 0.25,  # 契約1件あたり月。仮置き（一次 source に原典が無い。§9）
}

# 実測: doc/research/H_stock_params.md §1
# WordPress 業務系22語×上位8件、2026-08-12。参入3年以内の掲載の「導入数 月あたりの導入増」
STOCK_MEASURED = {
    "measured_on": "2026-08-12",
    "source": "doc/research/H_stock_params.md",
    "ecosystem": "wordpress",
    "参入年次": "参入3年以内・上位8件に入れた掲載 n=23",
    "installs_per_month": {"p25": 6.3, "p50": 36.2, "p75": 90.8},
    "caveat": "上位8件に入れた掲載のみ。参入したが入れなかった掲載を分母に含まない（強い生き残りだけを見る偏り）",
}


@dataclass
class Assumptions:
    margin: float
    churn_monthly: float
    horizon_months: int
    budget_hours_month: float
    flow_conversion: float
    flow_hours_contact: float
    stock_free_to_paid: float
    stock_hours_month: float
    stock_hours_build: float
    support_hours_contract: float
    provenance: dict = field(default_factory=dict)


def load_assumptions(path: str | None, overrides: dict) -> Assumptions:
    values = dict(DEFAULTS)
    provenance = {k: "既定値" for k in values}
    if path:
        raw = _read_config(path)
        for k, v in raw.items():
            if k not in values:
                raise SystemExit(f"config に未知の項目があります: {k}")
            values[k] = float(v)
            provenance[k] = f"config:{path}"
    for k, v in overrides.items():
        if v is None:
            continue
        if k not in values:
            raise SystemExit(f"未知の引数: {k}")
        values[k] = float(v)
        provenance[k] = "引数"
    values["horizon_months"] = int(values["horizon_months"])
    return Assumptions(provenance=provenance, **values)


def _read_config(path: str) -> dict:
    """yaml があれば yaml、無ければ `key: value` の最小構文で読む。fallback ではなく、
    どちらで読んだかを明示して落とす方針。"""
    text = open(path, encoding="utf-8").read()
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise SystemExit(f"{path} の中身が辞書ではありません")
        return data
    except ImportError:
        out = {}
        for i, line in enumerate(text.splitlines(), 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if ":" not in line:
                raise SystemExit(f"{path}:{i} を解釈できません（yaml を入れるか `key: value` で書いてください）")
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
        return out


def required_monthly_gain(target_contracts: float, churn: float, months: int) -> float:
    """目標 B 件に T か月で到達するのに必要な月次獲得。db/dt = M - c*b の解。

    維持に必要な数（c*B）ではない点に注意。その率ちょうどで獲得しても目標には到達しない
    （MARKET_RESEARCH.md §6.5.1 の訂正）。
    """
    if churn <= 0:
        return target_contracts / months
    return churn * target_contracts / (1.0 - math.exp(-churn * months))


def flow_ceiling(a: Assumptions) -> float:
    """個別の声かけだけで維持できる契約数の上限。単価にも目標にも目標までの月数にも依存しない。"""
    contacts_per_month = a.budget_hours_month / a.flow_hours_contact
    return contacts_per_month * a.flow_conversion / a.churn_monthly


def evaluate(goal_profit: float, price: float, a: Assumptions) -> dict:
    if price <= 0 or goal_profit <= 0:
        raise SystemExit("目標粗利と単価は正の数で指定してください")

    revenue_needed = goal_profit / a.margin
    contracts = revenue_needed / price
    gain = required_monthly_gain(contracts, a.churn_monthly, a.horizon_months)

    support_hours = contracts * a.support_hours_contract
    support_share = support_hours / a.budget_hours_month

    ceiling = flow_ceiling(a)
    flow_contacts_needed = gain / a.flow_conversion
    flow_hours_needed = flow_contacts_needed * a.flow_hours_contact

    stock_needed = gain / a.stock_free_to_paid
    m = STOCK_MEASURED["installs_per_month"]
    stock_vs = {k: (v, v >= stock_needed) for k, v in m.items()}

    return {
        "input": {"goal_profit_month": goal_profit, "price_month": price},
        "revenue_needed_month": revenue_needed,
        "target_contracts": contracts,
        "required_monthly_gain": gain,
        "support": {
            "hours_month": support_hours,
            "share_of_budget": support_share,
            "verdict": "不可（対応だけで予算超過）" if support_share > 1.0
                       else ("要注意（予算の半分超）" if support_share > 0.5 else "収まる"),
        },
        "flow": {
            "ceiling_contracts": ceiling,
            "ratio_to_ceiling": contracts / ceiling if ceiling else None,
            "contacts_needed_month": flow_contacts_needed,
            "hours_needed_month": flow_hours_needed,
            "verdict": "可" if contracts <= ceiling else "不可",
            "min_price_if_flow_only": revenue_needed / ceiling if ceiling else None,
        },
        "stock": {
            "installs_needed_month": stock_needed,
            "measured": stock_vs,
            "verdict": ("可（実測の中央値で届く）" if m["p50"] >= stock_needed
                        else "可（上位25%なら届く）" if m["p75"] >= stock_needed
                        else "不可（実測の範囲では届かない）"),
            "hours_month": a.stock_hours_month,
            "hours_build": a.stock_hours_build,
        },
    }


def fmt(r: dict, a: Assumptions) -> str:
    L = []
    p = r["input"]
    L.append("=" * 68)
    L.append(f"目標粗利 月{p['goal_profit_month']:,.0f}円 / 単価 月{p['price_month']:,.0f}円")
    L.append("=" * 68)
    L.append(f"必要な月次収入      {r['revenue_needed_month']:>12,.0f} 円   (利益率 {a.margin:.0%})")
    L.append(f"目標契約数          {r['target_contracts']:>12,.1f} 件")
    L.append(f"必要な月次獲得      {r['required_monthly_gain']:>12,.2f} 件   "
             f"(解約 月{a.churn_monthly:.1%} / {a.horizon_months}か月で到達)")
    L.append("")
    s = r["support"]
    L.append("[ 契約数そのものが食う時間 ]")
    L.append(f"  対応工数          {s['hours_month']:>12,.1f} 時間/月  "
             f"= 可処分の {s['share_of_budget']:.0%}  → {s['verdict']}")
    L.append("")
    f = r["flow"]
    L.append("[ 個別の声かけだけの場合 ]")
    L.append(f"  維持できる上限    {f['ceiling_contracts']:>12,.1f} 件   "
             f"(可処分{a.budget_hours_month:.1f}h ÷ 1接触{a.flow_hours_contact}h × 成約{a.flow_conversion:.1%} ÷ 解約{a.churn_monthly:.1%})")
    L.append(f"  目標との比        {f['ratio_to_ceiling']:>12,.2f} 倍   → {f['verdict']}")
    L.append(f"  この手段で成立する最低単価  月{f['min_price_if_flow_only']:>10,.0f} 円")
    L.append("")
    t = r["stock"]
    L.append("[ 掲載を1本持つ場合 ]")
    L.append(f"  必要な導入の増加    {t['installs_needed_month']:>12,.1f} 件/月 (転換 {a.stock_free_to_paid:.1%})")
    for k, (v, ok) in t["measured"].items():
        L.append(f"    実測 {k:<4}        {v:>10,.1f} 件/月  {'○ 届く' if ok else '× 届かない'}")
    L.append(f"  → {t['verdict']}   (構築{t['hours_build']:.0f}h + 維持{t['hours_month']:.0f}h/月)")
    L.append("")
    L.append(f"  実測の出所: {STOCK_MEASURED['source']} ({STOCK_MEASURED['measured_on']}, {STOCK_MEASURED['参入年次']})")
    L.append(f"  ※ {STOCK_MEASURED['caveat']}")
    L.append("")
    L.append("[ 前提の出所 ]")
    for k, v in sorted(a.provenance.items()):
        if v != "既定値":
            L.append(f"  {k:<24} {v}")
    unmeasured = [k for k in ("flow_conversion", "stock_free_to_paid", "support_hours_contract",
                              "flow_hours_contact") if a.provenance.get(k) == "既定値"]
    if unmeasured:
        L.append(f"  ** 未実測のまま使った前提: {', '.join(unmeasured)}")
        L.append("     段階1（返信率）と段階5（成約率）の実測で置き換えてください。")
        L.append("     判定は出しましたが、決定はしていません（AUTOMATION.md §2 制約8）。")
    return "\n".join(L)


def sweep(goal: float, a: Assumptions, prices) -> str:
    rows = []
    for pr in prices:
        r = evaluate(goal, pr, a)
        rows.append((pr, r["target_contracts"], r["flow"]["verdict"],
                     r["support"]["hours_month"], r["stock"]["installs_needed_month"],
                     r["stock"]["verdict"]))
    w = "%-12s %10s %8s %12s %14s  %s"
    out = [f"目標粗利 月{goal:,.0f}円", "",
           w % ("単価", "契約数", "個別の声かけ", "対応h/月", "必要導入/月", "掲載・記事")]
    out.append("-" * 88)
    for pr, c, fv, sh, si, sv in rows:
        out.append(w % (f"月{pr:,.0f}円", f"{c:,.1f}", fv, f"{sh:,.1f}", f"{si:,.1f}", sv))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="段階0 の逆算（doc/MARKET_RESEARCH.md §6.5）")
    ap.add_argument("--goal", type=float, required=True, help="目標粗利/月（円）")
    ap.add_argument("--price", type=float, help="単価/月（円）。--sweep 時は不要")
    ap.add_argument("--sweep", action="store_true", help="複数の単価で一覧を出す")
    ap.add_argument("--config", help="前提を書いた file（yaml、または `key: value`）")
    ap.add_argument("--json", action="store_true", help="機械可読で出す")
    for k in DEFAULTS:
        ap.add_argument(f"--{k.replace('_', '-')}", type=float, default=None)
    ns = ap.parse_args(argv)

    overrides = {k: getattr(ns, k) for k in DEFAULTS}
    a = load_assumptions(ns.config, overrides)

    if ns.sweep:
        prices = [4500, 15000, 50000, 150000]
        if ns.json:
            print(json.dumps({"assumptions": asdict(a),
                              "results": [evaluate(ns.goal, p, a) for p in prices]},
                             ensure_ascii=False, indent=1))
        else:
            print(sweep(ns.goal, a, prices))
        return 0

    if ns.price is None:
        ap.error("--price を指定してください（または --sweep）")
    r = evaluate(ns.goal, ns.price, a)
    if ns.json:
        print(json.dumps({"assumptions": asdict(a), "result": r,
                          "stock_measured": STOCK_MEASURED}, ensure_ascii=False, indent=1))
    else:
        print(fmt(r, a))
    return 0


if __name__ == "__main__":
    sys.exit(main())
