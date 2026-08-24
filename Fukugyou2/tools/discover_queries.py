#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程0 検索語の自動発見。人が検索語を書かずに、data から語を作ります。

## algorithm（選定理由は doc/METHOD.md §5A）

  1. 母集団の取得   query 無しで取れる構造 tag（show_hn）と、比較用の一般 story を
                    期間で層化 sampling します。ここに人の語は要りません。
  2. 標識づけ       製品化事例は config/screen.yaml の軸で、失敗事例は
                    config/discovery.yaml の「定義」で positive / negative に分けます。
                    人が書くのは「何を positive と呼ぶか」であり、検索語ではありません。
  3. keyness        positive と negative を分ける語を Dunning の対数尤度比 G^2 で選びます。
                    低頻度語に強く、corpus 比較の標準的な指標です（頻度差や TF-IDF より適切）。
  4. 歩留まり検証   候補語で実際に検索し、該当件数の帯・適合率・新規率を測ります。
                    閾値を満たした語だけ採用します。**生成した語をそのまま使いません。**
  5. 飽和まで反復   採用語の結果を positive に足して 3 に戻り、新規 positive が
                    増えなくなった round が続いたら終了します。

出力の語には、採用理由となった実測値が必ず併記されます。

使い方:
  python tools/discover_queries.py --kind product
  python tools/discover_queries.py --kind failure
  python tools/discover_queries.py --kind product --max-rounds 2 --dry-run
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import casebase as cb
import collect_cases as cc
import screen_cases as sc


LITERAL = re.compile(r"[a-z][a-z\-]{2,}")
ESCAPE = re.compile(r"\\[a-zA-Z]")


def condition_terms(screen: dict, conf: dict, kind: str) -> set[str]:
    """標識づけに使った語を集めます（正規表現からの文字列の抜き出し）。

    これを候補から外さないと、条件に書いた語が条件に合う事例を連れてくるだけになり、
    適合率が循環します。discovery が探すのは「条件に書いていない語」です。
    """
    text = " ".join(p for c in screen["conditions"] for p in c["any_of"])
    text += " " + " ".join(p for e in screen["exclude"] for p in e["any_of"])
    if kind == "failure":
        text += " " + " ".join(conf["failure_definition"]["phrases"])
    return set(LITERAL.findall(ESCAPE.sub(" ", text.lower())))


def load_stopwords(file_path: str) -> set[str]:
    words = set()
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("#"):
                continue
            words.update(w for w in line.split() if w)
    return words


def harvest(source: dict, conf: dict, tags: str, budget: cb.Budget, sleep: float) -> list[dict]:
    """query 無しで母集団を取ります。期間を等分し、各期間から同数を取ります。"""
    now = int(datetime.datetime.now().timestamp())
    span = int(conf["since_years"] * 365.25 * 24 * 3600)
    windows, per = int(conf["windows"]), int(conf["per_window"])
    step = span // windows
    hits = []
    for i in range(windows):
        hi = now - i * step
        lo = hi - step
        params = urllib.parse.urlencode({
            "tags": tags,
            "numericFilters": f"points>={conf['min_points']},created_at_i>={lo},created_at_i<{hi}",
            "hitsPerPage": per,
        })
        data, _, _ = cb.http_json(f"{source['by_date_endpoint']}?{params}",
                                  timeout=int(source["timeout_seconds"]), budget=budget)
        hits.extend(data.get("hits", []))
        time.sleep(sleep)
    return hits


def to_cases(hits: list[dict], source: dict, kind: str, query: str) -> list[dict]:
    today = cb.today().isoformat()
    out = []
    for h in hits:
        if not h.get("objectID") or not (h.get("title") or h.get("story_title")):
            continue
        out.append(cc.to_case(h, query, kind, source["item_url_template"], today))
    return out


def make_labeler(kind: str, conf: dict, screen: dict):
    """positive の定義を返します。検索語ではなく定義であることが要点です。"""
    if kind == "product":
        conditions = sc.compile_conditions(screen)
        excludes = [{**e, "patterns": [re.compile(p) for p in e["any_of"]]} for e in screen["exclude"]]
        axes = screen["axes"]
        need = int(conf["scoring"]["positive_min_axes"])

        def label(case: dict) -> bool:
            r = sc.evaluate(case, conditions, excludes, None)
            met = sum(1 for a, spec in axes.items()
                      if r["by_axis"].get(a, 0) >= int(spec["conditions_required"]))
            return met >= need and not r["exclude_marks"]
        return label

    phrases = conf["failure_definition"]["phrases"]
    pat = re.compile("|".join(re.escape(p) for p in phrases), re.IGNORECASE)

    def label(case: dict) -> bool:
        return bool(pat.search(sc.case_text(case)))
    return label


def docs_of(cases: list[dict], stop: set[str], ngram_max: int) -> list[list[str]]:
    docs = []
    for c in cases:
        tokens = cb.tokenize_en(sc.case_text(c), stop)
        terms = list(tokens)
        for n in range(2, ngram_max + 1):
            terms += cb.ngrams(tokens, n)
        docs.append(terms)
    return docs


def to_query(term: str) -> str:
    """2語の連なりは phrase として、掛け合わせは AND として検索します。"""
    if term.startswith("+"):
        return term[1:]
    return f'"{term}"' if " " in term else term


def propose(pos: list[dict], neg: list[dict], stop: set[str], sco: dict,
            tried: set[str], anchors: list[str], limit: int) -> list[str]:
    """keyness 上位語と、採用済み語との掛け合わせを候補にします。

    単語1語の query は該当が広すぎて適合率が落ちるため、擬似適合性 feedback と同じ要領で
    「効いた語 × 新しい語」の AND query を作ります。
    """
    ranked = cb.keyness(docs_of(pos, stop, int(sco["ngram_max"])),
                        docs_of(neg, stop, int(sco["ngram_max"])),
                        min_count=int(sco["min_count"]), top_k=int(sco["top_k"]),
                        min_docs=int(sco["min_docs"]))
    terms = [t["term"] for t in ranked]
    singles = [t for t in terms if t not in tried]
    pairs = []
    if sco.get("pair_with_accepted") and anchors:
        for a in anchors[:int(sco["max_anchors"])]:
            for t in terms[:int(sco["max_pair_terms"])]:
                if t in a or a.strip('"') in t:
                    continue
                pair = f"+{a} {t}"
                if pair not in tried:
                    pairs.append(pair)
    if not pairs:
        return singles[:limit]
    half = max(1, limit // 2)
    return singles[:limit - min(half, len(pairs))] + pairs[:half]


def validate(term: str, source: dict, conf: dict, kind: str, label, known: set[str],
             min_points: int, since: int, budget: cb.Budget) -> dict:
    """候補語を実際に引いて、採否の根拠になる実測値を返します。

    指標は種別で変えます。標識が語そのものである失敗事例では、適合率は
    「定義した語を含む query は定義に合う」という循環になるため使いません。
    """
    v = conf["validation"]
    hits, _, nb = cc.search(source, to_query(term), int(v["hits_per_query"]), min_points, since, budget)
    cases = to_cases(hits, source, kind, to_query(term))
    positives = [c for c in cases if label(c)]
    fetched = len(cases)
    new_positives = [c for c in positives if c["case_id"] not in known]
    metric = v["metric_by_kind"][kind]
    m = {
        "term": term, "query": to_query(term), "total_hits": nb, "fetched": fetched,
        "positives": len(positives), "new_positives": len(new_positives), "metric": metric,
        "precision": round(len(positives) / fetched, 3) if fetched else 0.0,
        "novelty": round(sum(1 for c in cases if c["case_id"] not in known) / fetched, 3) if fetched else 0.0,
    }
    reasons = []
    if metric == "precision" and nb < int(v["min_total_hits"]):
        reasons.append(f"該当が少なすぎます（{nb} < {v['min_total_hits']}）")
    if nb > int(v["max_total_hits"]):
        reasons.append(f"一般語すぎます（{nb} > {v['max_total_hits']}）")
    if metric == "precision" and m["precision"] < float(v["min_precision"]):
        reasons.append(f"適合率 {m['precision']} < {v['min_precision']}")
    if metric == "yield" and m["new_positives"] < int(v["min_new_positives"]):
        reasons.append(f"新規 positive {m['new_positives']} < {v['min_new_positives']}")
    m["accepted"] = not reasons
    m["rejected_for"] = reasons
    m["cases"] = cases
    return m


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="工程0: 検索語の自動発見（人は語を書きません）")
    ap.add_argument("--kind", required=True, choices=["product", "failure"])
    ap.add_argument("--discovery", default=cb.path("config", "discovery.yaml"))
    ap.add_argument("--sources", default=cb.path("config", "sources.yaml"))
    ap.add_argument("--screen", default=cb.path("config", "screen.yaml"))
    ap.add_argument("--max-rounds", type=int, help="config の値を上書きします")
    ap.add_argument("--dry-run", action="store_true", help="config への語の書き出しを行いません")
    ap.add_argument("--out", default=cb.path("log"))
    ns = ap.parse_args(argv)

    conf = cb.load_yaml(ns.discovery)
    source = cb.load_yaml(ns.sources)["hn_algolia"]
    screen = cb.load_yaml(ns.screen)
    stop = load_stopwords(cb.path(conf["scoring"]["stopwords_file"]))
    if conf["scoring"].get("exclude_condition_terms"):
        stop |= condition_terms(screen, conf, ns.kind)
    label = make_labeler(ns.kind, conf, screen)
    budget = cb.Budget(conf["budget"])
    manifest = cb.Manifest("discover_queries", vars(ns))
    sleep = float(source["sleep_seconds"])
    day_stamp = cb.stamp()
    cases_path = os.path.join(ns.out, f"cases-{day_stamp}.jsonl")
    known = {c["case_id"] for c in (cb.read_jsonl(cases_path) if os.path.exists(cases_path) else [])}
    since = int((datetime.datetime.now() - datetime.timedelta(days=365.25 * conf["corpus"]["since_years"])).timestamp())
    min_points = int(conf["corpus"]["min_points"])

    print(f"取得日 {cb.today()} / 種別 {ns.kind} / 既知の事例 {len(known)}件")
    print("[1] 母集団の取得（検索語を使いません）")
    target_tag = conf["corpus"]["tags"] if ns.kind == "product" else conf["corpus"]["background_tags"]
    target = to_cases(harvest(source, conf["corpus"], target_tag, budget, sleep), source, ns.kind, f"corpus:{target_tag}")
    background = to_cases(harvest(source, conf["corpus"], conf["corpus"]["background_tags"], budget, sleep),
                          source, ns.kind, "corpus:background")
    if ns.kind == "failure":
        for ph in conf["failure_definition"]["phrases"]:
            hits, _, _ = cc.search(source, f'"{ph}"', int(conf["validation"]["hits_per_query"]),
                                   min_points, since, budget)
            target += to_cases(hits, source, ns.kind, f'"{ph}"')
            time.sleep(sleep)

    pool = {c["case_id"]: c for c in target + background}
    pos = [c for c in pool.values() if label(c)]
    neg = [c for c in pool.values() if not label(c)]
    print(f"    母集団 {len(pool)}件 → positive {len(pos)}件 / negative {len(neg)}件")
    if len(pos) < int(conf["scoring"]["min_count"]):
        raise SystemExit(f"positive が {len(pos)}件しかありません。母集団（config/discovery.yaml の corpus）"
                         "を広げてください。少ない標本で語を作ると、雑音を拾います。")

    seed_anchors = ([f'"{p}"' for p in conf["failure_definition"]["phrases"]]
                    if ns.kind == "failure" else [])
    rounds, accepted, tried, no_gain = [], [], set(), 0
    max_rounds = ns.max_rounds or int(conf["saturation"]["max_rounds"])
    sco, sat = conf["scoring"], conf["saturation"]
    for r in range(1, max_rounds + 1):
        anchors = [m["term"].lstrip("+") for m in accepted] or seed_anchors
        cand = propose(pos, neg, stop, sco, tried, anchors,
                       int(conf["validation"]["max_candidates_per_round"]))
        print(f"\n[2] round {r}: 候補 {len(cand)}語")
        if not cand:
            print("    候補が尽きました。")
            break
        results, new_pos = [], 0
        for term in cand:
            tried.add(term)
            try:
                m = validate(term, source, conf, ns.kind, label, known, min_points, since, budget)
            except cb.SourceError as e:
                manifest.fail(term=term, error=str(e))
                cb.eprint(f"    失敗: {term} — {e}")
                continue
            cases = m.pop("cases")
            results.append(m)
            mark = "採用" if m["accepted"] else "却下"
            print(f"    {mark} {to_query(term)[:30]:<30} 該当{m['total_hits']:>6} 適合率{m['precision']:>5} "
                  f"新規{m['new_positives']:>3}件" + ("" if m["accepted"] else f"  ← {m['rejected_for'][0]}"))
            if m["accepted"]:
                accepted.append({**m, "round": r})
                fresh = [c for c in cases if label(c) and c["case_id"] not in {p["case_id"] for p in pos}]
                pos += fresh
                new_pos += len(fresh)
                added, _, _ = cb.merge_cases(cases_path, cases)
                known |= {c["case_id"] for c in cases}
                manifest.count(**{f"cases_added_round{r}": added})
            time.sleep(sleep)
        rounds.append({"round": r, "candidates": results, "new_positives": new_pos})
        print(f"    round {r}: 採用 {sum(1 for m in results if m['accepted'])}語 / 新規 positive {new_pos}件")
        no_gain = no_gain + 1 if new_pos < int(sat["min_new_positives"]) else 0
        if no_gain >= int(sat["patience"]):
            print(f"\n    収穫の無い round が {no_gain} 回続いたため終了します（飽和）。")
            break

    if not accepted:
        raise SystemExit("採用された語がありません。閾値（config/discovery.yaml の validation）が"
                         "厳しすぎるか、母集団が小さすぎます。閾値を緩める前に母集団を広げてください。")

    accepted.sort(key=lambda m: (-m["precision"], -m["new_positives"]))
    run_at = manifest.data["started_at"][11:19].replace(":", "")
    out_json = os.path.join(ns.out, f"discovery-{ns.kind}-{day_stamp}-{run_at}.json")
    cb.write_json(out_json, {"kind": ns.kind, "discovered_on": cb.today().isoformat(),
                             "corpus": {"target": len(target), "background": len(background),
                                        "positives": len(pos)},
                             "accepted": accepted, "rounds": rounds})
    manifest.output(out_json)

    query_path = cb.path("config", f"queries_auto-{ns.kind}-{day_stamp}.txt")
    if not ns.dry_run:
        lines = [f"# {ns.kind} の検索語（自動発見 {cb.today()}）。人が書いた語ではありません。",
                 f"# 生成: tools/discover_queries.py / 実測値は log/{os.path.basename(out_json)} にあります。",
                 f"# 採用条件: 適合率 >= {conf['validation']['min_precision']} / "
                 f"該当 {conf['validation']['min_total_hits']}〜{conf['validation']['max_total_hits']}件", ""]
        lines += [m["query"] for m in accepted]
        with open(query_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        manifest.output(query_path)

    manifest.count(accepted=len(accepted), tried=len(tried), rounds=len(rounds), positives=len(pos))
    manifest.write(ns.out, budget)
    print(f"\n採用 {len(accepted)}語 / 試行 {len(tried)}語 / round {len(rounds)}")
    print("  " + ", ".join(m["query"] for m in accepted[:10]))
    print(f"\n記録: {out_json}")
    print(f"検索語: {query_path}" + ("（--dry-run のため書いていません）" if ns.dry_run else ""))
    print(f"request: {budget.report()}")
    print(f"\n次: python tools/collect_cases.py --queries {os.path.relpath(query_path, cb.ROOT)} --kind {ns.kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
