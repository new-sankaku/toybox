#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程5 転用。事例 × 業界 の格子をつくり、人が埋める worksheet を出します。

既定は空欄の worksheet です。program は転用先を決めません。
--hypothesis を付けたときだけ LLM に下書きを書かせますが、出力は別 file に分け、
1行ごとに「仮説（未検証）」と「検証方法」を必ず付けます。証拠と混ぜません。

事例の並びは screen の該当軸数の順です（機械的な並び替えであり、採否ではありません）。

使い方:
  python tools/transfer_matrix.py --top 5
  python tools/transfer_matrix.py --top 5 --hypothesis
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import casebase as cb
import llm_client

QUESTIONS = ("同型の業務があるか", "誰が金を払うか", "data はどこにあるか", "規制・商習慣の壁", "最初の検証")

SYSTEM = """あなたは事業企画の下調べを手伝います。守る規則:
1. 事実を作らないでください。知らないことは「不明」と書きます。
2. 各行に必ず「検証方法」を書きます。1週間以内・費用1万円以内で真偽が分かる方法に限ります。
3. 市場規模の推計や、出典の無い数字を書かないでください。
4. 日本国内の商習慣・規制に限って書きます。
5. 出力は指示された markdown 表のみとし、前置きと後書きを書かないでください。"""

USER = """次の事例を、日本の別業界に転用できるかを検討します。

## 事例
- 題名: {title}
- URL: {url}
- 分類: {categories}
- 該当した軸: {axes}

## 対象業界
{industries}

## 出力
業界ごとに1行、次の列で markdown 表を作ってください。
| 業界 | 同型の業務があるか | 誰が金を払うか | data はどこにあるか | 規制・商習慣の壁 | 最初の検証（1週間・1万円以内） |
すべての行は仮説です。断定形で書かないでください。"""


def worksheet(industries: list[str]) -> str:
    head = "| 業界 | " + " | ".join(QUESTIONS) + " |"
    sep = "|---" * (len(QUESTIONS) + 1) + "|"
    rows = [f"| {n} |" + " |" * len(QUESTIONS) for n in industries]
    return "\n".join([head, sep, *rows])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="工程5: 事例 × 業界 の転用 worksheet")
    ap.add_argument("--screen", help="既定は log/ の最新 screen-*.json")
    ap.add_argument("--industries", default=cb.path("config", "industries_jp.txt"))
    ap.add_argument("--top", type=int, default=5, help="worksheet にする事例数（該当軸数の順）")
    ap.add_argument("--industries-limit", type=int, default=30)
    ap.add_argument("--min-axes", type=int, default=2, help="この軸数未満の事例は worksheet にしない")
    ap.add_argument("--hypothesis", action="store_true", help="LLM に下書きを書かせる（別 file に出力）")
    ap.add_argument("--llm-config", default=cb.path("config", "llm.yaml"))
    ap.add_argument("--out", default=cb.path("log"))
    ns = ap.parse_args(argv)

    screen_path = ns.screen or cb.latest(ns.out, "screen-*.json", "tools/screen_cases.py")
    with open(screen_path, encoding="utf-8") as f:
        screen = json.load(f)
    industries = cb.load_terms(ns.industries, ns.industries_limit, "業界")

    picked = [i for i in screen["items"] if i["axes_met_count"] >= ns.min_axes and not i["exclude_marks"]][:ns.top]
    if not picked:
        raise SystemExit(f"該当軸 {ns.min_axes} 以上の事例がありません。"
                         "--min-axes を下げるか、収集をやり直してください（条件は緩めないでください）。")

    day = cb.today()
    lines = [f"# 転用 worksheet（{day}）", "",
             f"入力: `{os.path.basename(screen_path)}` / 事例 {len(picked)}件 × 業界 {len(industries)}件", "",
             "空欄は人が埋めます。program は転用先を決めません（doc/METHOD.md §5 規律1）。",
             "1つでも「不明」が残る行は、その行の検証を先にやってください。", ""]
    for n, case in enumerate(picked, 1):
        lines += [f"## {n}. {case['title']}", "",
                  f"- 出所: {case['url']}",
                  f"- 議論: {case['discussion_url']}",
                  f"- 分類: {', '.join(case['categories']) or '未分類'}",
                  f"- 該当軸: {', '.join(case['axes_met']) or 'なし'}（{case['axes_met_count']}/4）", "",
                  worksheet(industries), ""]
    out_path = os.path.join(ns.out, f"transfer-{cb.stamp(day)}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"worksheet: {out_path}（事例 {len(picked)}件 × 業界 {len(industries)}件）")

    if not ns.hypothesis:
        print("下書きが要る場合は --hypothesis を付けてください（別 file に、仮説として出力します）。")
        return 0

    conf = llm_client.load_config(ns.llm_config)
    print(f"LLM 下書き: provider {conf['provider']} / model {conf['model']}")
    draft = [f"# 転用 仮説（未検証）（{day}）", "",
             f"**この file の内容はすべて仮説です。** LLM（{conf['provider']} / {conf['model']}）の下書きであり、",
             "証拠ではありません。検証して初めて `transfer-*.md` に転記してください。", ""]
    failures = []
    for n, case in enumerate(picked, 1):
        prompt = USER.format(title=case["title"], url=case["url"],
                             categories=", ".join(case["categories"]) or "未分類",
                             axes=", ".join(case["axes_met"]) or "なし",
                             industries="\n".join(f"- {i}" for i in industries))
        try:
            text = llm_client.complete(conf, SYSTEM, prompt)
        except cb.SourceError as e:
            failures.append({"case_id": case["case_id"], "error": str(e)})
            cb.eprint(f"  失敗: {case['title'][:40]} — {e}")
            continue
        draft += [f"## {n}. {case['title']}", "", f"- 出所: {case['url']}", "", text.strip(), ""]
        print(f"  [{n}/{len(picked)}] {case['title'][:56]}")

    if failures:
        draft += ["## 失敗", ""] + [f"- {f['case_id']}: {f['error']}" for f in failures] + [""]
    draft_path = os.path.join(ns.out, f"transfer-hypotheses-{cb.stamp(day)}.md")
    with open(draft_path, "w", encoding="utf-8") as f:
        f.write("\n".join(draft))
    print(f"仮説（未検証）: {draft_path}")
    if failures:
        print(f"失敗 {len(failures)}件（欠損は欠損のまま残しています）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
