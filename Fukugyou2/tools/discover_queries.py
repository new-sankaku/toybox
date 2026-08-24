#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程0 検索語の自動発見。人が検索語を書かずに、data から語を作ります。

## algorithm（選定理由は doc/METHOD.md §5A）

  1. 母集団の取得   query 無しで引ける構造 tag（Hacker News の show_hn）を期間で分け、
                    各期間から **無作為 page** を引きます。日付降順の先頭だけを取ると
                    期間の末尾しか見ないため、無作為抽出にしています（seed は記録します）。
  2. 標識づけ       製品化事例は config/screen.yaml の軸、失敗事例は
                    config/discovery.yaml の定義で positive / negative に分けます。
  3. keyness        positive と negative を分ける語を選びます。有意性（G^2、chi^2(1) の
                    臨界値で足切り）と効果量（Log Ratio）の両方を課します。
  4. 掛け合わせ     効いた語 × 新しい語 の AND query も候補にします（擬似適合性 feedback）。
  5. 歩留まりの実測 候補で実際に検索し、該当件数・適合率・新規獲得数を測ります。
                    適合率は **Wilson score interval の下限**で判定します（点推定は小標本で甘い）。
  6. 飽和まで反復   新規 positive が増えない round が続いたら終了します。

**標識づけに使った語は、語幹単位で候補から除外します。** 完全一致で除外すると
automat → automation のような語形変化がすり抜け、条件が自分自身を引く循環になります。

使い方:
  python tools/discover_queries.py --kind product
  python tools/discover_queries.py --kind failure
  python tools/discover_queries.py --kind product --dry-run   # 何も書き出しません
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import random
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
STEM_PREFIX_MIN = 5


def condition_terms(screen: dict, conf: dict, kind: str) -> set[str]:
    """標識づけに使った語（正規表現の中の文字列）を集めます。

    これを候補から外さないと、条件に書いた語が条件に合う事例を連れてくるだけになり、
    発見が起きません。除外は語幹の前方一致で行います（§5A）。
    """
    text = " ".join(p for c in screen["conditions"] for p in c["any_of"])
    text += " " + " ".join(p for e in screen["exclude"] for p in e["any_of"])
    if kind == "failure":
        text += " " + " ".join(conf["failure_definition"]["phrases"])
    return set(LITERAL.findall(ESCAPE.sub(" ", text.lower())))


def is_label_vocabulary(term: str, stems: set[str]) -> bool:
    """語幹一致で「標識に使った語」かを判定します。automat は automation を含みます。"""
    for token in term.split():
        if token in stems:
            return True
        if any(len(s) >= STEM_PREFIX_MIN and token.startswith(s) for s in stems):
            return True
    return False


def load_stopwords(file_path: str) -> set[str]:
    if not os.path.exists(file_path):
        raise SystemExit(f"{file_path} がありません。")
    words = set()
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("#"):
                continue
            words.update(w for w in line.split() if w)
    return words


def harvest(source: dict, conf: dict, tags: str, budget: cb.Budget, sleep: float,
            rng: random.Random, out_dir: str, day_stamp: str) -> tuple[list[dict], list[dict]]:
    """query 無しで母集団を取ります。期間を等分し、各期間から無作為な page を引きます。"""
    now = int(datetime.datetime.now().timestamp())
    span = int(conf["since_years"] * 365.25 * 24 * 3600)
    windows, per = int(conf["windows"]), int(conf["per_window"])
    step = span // windows
    hits, sampled = [], []
    for i in range(windows):
        hi, lo = now - i * step, now - (i + 1) * step
        base = {"tags": tags,
                "numericFilters": f"points>={conf['min_points']},created_at_i>={lo},created_at_i<{hi}",
                "hitsPerPage": per}
        data, raw, _ = cb.http_json(f"{source['by_date_endpoint']}?{urllib.parse.urlencode(base)}",
                                    timeout=int(source["timeout_seconds"]), budget=budget)
        cb.save_raw("hn-corpus", f"{tags}-w{i}-p0", raw, day_stamp, out_dir)
        hits.extend(data.get("hits", []))
        pages = min(int(data.get("nbPages", 1)), max(1, 1000 // per))
        page = rng.randrange(pages) if pages > 1 else 0
        sampled.append({"window": i, "nb_hits": data.get("nbHits"), "pages_available": pages,
                        "sampled_page": page})
        if page:
            time.sleep(sleep)
            data2, raw2, _ = cb.http_json(
                f"{source['by_date_endpoint']}?{urllib.parse.urlencode({**base, 'page': page})}",
                timeout=int(source["timeout_seconds"]), budget=budget)
            cb.save_raw("hn-corpus", f"{tags}-w{i}-p{page}", raw2, day_stamp, out_dir)
            hits.extend(data2.get("hits", []))
        time.sleep(sleep)
    return hits, sampled


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
    """n-gram は stopword 除去の**前**に作ります。

    除去後に作ると「browser for automations」から "browser automations" という
    存在しない phrase が生まれ、完全一致検索が空振りします。
    """
    docs = []
    for c in cases:
        raw_tokens = cb.tokenize_en(sc.case_text(c), set())
        terms = [w for w in raw_tokens if w not in stop]
        for n in range(2, ngram_max + 1):
            terms += [g for g in cb.ngrams(raw_tokens, n)
                      if not any(w in stop for w in g.split())]
        docs.append(terms)
    return docs


def to_query(term: str) -> str:
    """2語の連なりは phrase として、掛け合わせは AND として検索します。"""
    if term.startswith("+"):
        return term[1:]
    return f'"{term}"' if " " in term else term


def propose(pos: list[dict], neg: list[dict], stop: set[str], sco: dict,
            tried: set[str], anchors: list[str], limit: int) -> list[dict]:
    """keyness 上位語と、採用済み語との掛け合わせを候補にします。

    戻り値は keyness の実測値つきの row です（採用理由を log に残すため）。
    """
    ranked = cb.keyness(docs_of(pos, stop, int(sco["ngram_max"])),
                        docs_of(neg, stop, int(sco["ngram_max"])),
                        min_count=int(sco["min_count"]), top_k=int(sco["top_k"]),
                        min_docs=int(sco["min_docs"]), min_g2=float(sco["min_g2"]),
                        min_log_ratio=float(sco["min_log_ratio"]))
    by_term = {r["term"]: r for r in ranked}
    singles = [r for r in ranked if r["term"] not in tried]
    pairs = []
    if sco.get("pair_with_accepted") and anchors:
        for a in anchors[:int(sco["max_anchors"])]:
            for t in [r["term"] for r in ranked][:int(sco["max_pair_terms"])]:
                if t in a or a.strip('"') in t:
                    continue
                pair = f"+{a} {t}"
                if pair not in tried:
                    pairs.append({**by_term[t], "term": pair, "paired_with": a})
    if not pairs:
        return singles[:limit]
    half = max(1, limit // 2)
    return singles[:limit - min(half, len(pairs))] + pairs[:half]


def validate(cand: dict, source: dict, conf: dict, kind: str, label, known: set[str],
             min_points: int, since: int, budget: cb.Budget, seed_phrases: list[str]) -> dict:
    """候補語を実際に引いて、採否の根拠になる実測値を返します。

    指標は種別で変えます。標識が語そのものである失敗事例では、適合率は
    「定義した語を含む query は定義に合う」という循環になるため使いません。
    """
    v = conf["validation"]
    term = cand["term"]
    query = to_query(term)
    hits, _, nb = cc.search(source, query, int(v["hits_per_query"]), min_points, since, budget)
    cases = to_cases(hits, source, kind, query)
    positives = [c for c in cases if label(c)]
    fetched = len(cases)
    new_positives = [c for c in positives if c["case_id"] not in known]
    metric = v["metric_by_kind"][kind]
    m = {
        "term": term, "query": query, "metric": metric,
        "g2": cand.get("g2"), "log_ratio": cand.get("log_ratio"),
        "paired_with": cand.get("paired_with"),
        "seeded": any(p.lower() in query.lower() for p in seed_phrases),
        "total_hits": nb, "fetched": fetched, "positives": len(positives),
        "new_positives": len(new_positives),
        "precision": round(len(positives) / fetched, 3) if fetched else None,
        "precision_lower": round(cb.wilson_lower(len(positives), fetched), 3) if fetched else None,
        "novelty": round(sum(1 for c in cases if c["case_id"] not in known) / fetched, 3) if fetched else None,
    }
    reasons = []
    if fetched == 0:
        reasons.append("測定不能（取得0件）")
    if nb < int(v["min_total_hits"]):
        reasons.append(f"該当が少なすぎます（{nb} < {v['min_total_hits']}）")
    if nb > int(v["max_total_hits"]):
        reasons.append(f"一般語すぎます（{nb} > {v['max_total_hits']}）")
    if metric == "precision" and m["precision_lower"] is not None \
            and m["precision_lower"] < float(v["min_precision"]):
        reasons.append(f"適合率の下限 {m['precision_lower']} < {v['min_precision']}")
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
    ap.add_argument("--seed", type=int, help="母集団 sampling の乱数 seed（既定は日付から決まります）")
    ap.add_argument("--dry-run", action="store_true", help="config にも事例 file にも書き込みません")
    ap.add_argument("--out", default=cb.path("log"))
    ns = ap.parse_args(argv)

    conf = cb.load_yaml(ns.discovery)
    source = cb.load_yaml(ns.sources)["hn_algolia"]
    screen = cb.load_yaml(ns.screen)
    stop = load_stopwords(cb.path(conf["scoring"]["stopwords_file"]))
    stems = condition_terms(screen, conf, ns.kind) if conf["scoring"].get("exclude_condition_terms") else set()
    label = make_labeler(ns.kind, conf, screen)
    budget = cb.Budget(conf["budget"])
    manifest = cb.Manifest("discover_queries", vars(ns))
    sleep = float(source["sleep_seconds"])
    day_stamp = cb.stamp()
    seed = ns.seed if ns.seed is not None else int(day_stamp)
    rng = random.Random(seed)
    manifest.count(sampling_seed=seed)
    cases_path = os.path.join(ns.out, f"cases-{day_stamp}.jsonl")
    known = {c["case_id"] for c in (cb.read_jsonl(cases_path) if os.path.exists(cases_path) else [])}
    since_years = float(conf["corpus"]["since_years"])
    since = int((datetime.datetime.now() - datetime.timedelta(days=365.25 * since_years)).timestamp())
    min_points = int(conf["corpus"]["min_points"])
    seed_phrases = conf["failure_definition"]["phrases"] if ns.kind == "failure" else []

    try:
        print(f"取得日 {cb.today()} / 種別 {ns.kind} / 既知の事例 {len(known)}件 / seed {seed}")
        print("[1] 母集団の取得（検索語を使いません）")
        target_tag = conf["corpus"]["tags"] if ns.kind == "product" else conf["corpus"]["background_tags"]
        t_hits, t_sample = harvest(source, conf["corpus"], target_tag, budget, sleep, rng, ns.out, day_stamp)
        target = to_cases(t_hits, source, ns.kind, f"corpus:{target_tag}")
        background = []
        if target_tag != conf["corpus"]["background_tags"]:
            b_hits, _ = harvest(source, conf["corpus"], conf["corpus"]["background_tags"],
                                budget, sleep, rng, ns.out, day_stamp)
            background = to_cases(b_hits, source, ns.kind, "corpus:background")
        seeded_queries = []
        if ns.kind == "failure":
            for ph in seed_phrases:
                query = f'"{ph}"'
                hits, _, nb = cc.search(source, query, int(conf["validation"]["hits_per_query"]),
                                        min_points, since, budget)
                cases = to_cases(hits, source, ns.kind, query)
                target += cases
                seeded_queries.append({
                    "term": ph, "query": query, "metric": "definition", "discovered": False,
                    "seeded": True, "total_hits": nb, "fetched": len(cases),
                    "positives": sum(1 for c in cases if label(c)),
                    "new_positives": sum(1 for c in cases
                                         if label(c) and c["case_id"] not in known),
                    "g2": None, "log_ratio": None, "precision": None, "precision_lower": None,
                    "novelty": None, "accepted": True, "rejected_for": [], "round": 0})
                time.sleep(sleep)

        pool = {c["case_id"]: c for c in target + background}
        pos = [c for c in pool.values() if label(c)]
        neg = [c for c in pool.values() if not label(c)]
        covered = sum(s["sampled_page"] > 0 for s in t_sample)
        print(f"    母集団 {len(pool)}件（無作為 page を引けた期間 {covered}/{len(t_sample)}）"
              f" → positive {len(pos)}件 / negative {len(neg)}件")
        manifest.count(pool=len(pool), positives=len(pos), negatives=len(neg), windows=t_sample)
        if len(pos) < int(conf["scoring"]["min_count"]) or not neg:
            raise SystemExit(f"positive {len(pos)}件 / negative {len(neg)}件では語を作れません。"
                             "config/discovery.yaml の corpus を広げてください。")

        rounds, accepted, tried, no_gain, paired_tried = [], [], set(), 0, False
        max_rounds = ns.max_rounds or int(conf["saturation"]["max_rounds"])
        sco, sat = conf["scoring"], conf["saturation"]
        for r in range(1, max_rounds + 1):
            anchors = [to_query(m["term"]) for m in accepted] or [f'"{p}"' for p in seed_phrases]
            cand = [c for c in propose(pos, neg, stop, sco, tried,
                                       anchors, int(conf["validation"]["max_candidates_per_round"]))
                    if not is_label_vocabulary(c["term"].lstrip("+"), stems)]
            print(f"\n[2] round {r}: 候補 {len(cand)}語")
            if not cand:
                print("    候補が尽きました（keyness の閾値を満たす未試行の語がありません）。")
                break
            results, new_pos = [], 0
            for c in cand:
                tried.add(c["term"])
                paired_tried = paired_tried or c["term"].startswith("+")
                try:
                    m = validate(c, source, conf, ns.kind, label, known, min_points, since,
                                 budget, seed_phrases)
                except cb.SourceError as e:
                    manifest.fail(term=c["term"], error=str(e))
                    cb.eprint(f"    失敗: {c['term']} — {e}")
                    continue
                cases = m.pop("cases")
                results.append(m)
                mark = "採用" if m["accepted"] else "却下"
                pl = m["precision_lower"]
                print(f"    {mark} {m['query'][:30]:<30} 該当{m['total_hits']:>6} "
                      f"適合率下限{(f'{pl:.2f}' if pl is not None else '  —'):>6} "
                      f"新規{m['new_positives']:>3}件 G²{(m['g2'] or 0):>7.1f}"
                      + ("" if m["accepted"] else f"  ← {m['rejected_for'][0]}"))
                if m["accepted"]:
                    accepted.append({**m, "round": r})
                    fresh = [x for x in cases if label(x) and x["case_id"] not in {p["case_id"] for p in pos}]
                    pos += fresh
                    new_pos += len(fresh)
                    if not ns.dry_run:
                        added, _, _ = cb.merge_cases(cases_path, cases)
                        manifest.add(**{f"cases_added_round{r}": added})
                    known |= {x["case_id"] for x in cases}
                time.sleep(sleep)
            rounds.append({"round": r, "candidates": results, "new_positives": new_pos})
            print(f"    round {r}: 採用 {sum(1 for m in results if m['accepted'])}語 / 新規 positive {new_pos}件")
            if not paired_tried:
                continue          # 掛け合わせを一度も試していない round は飽和判定に数えない
            no_gain = no_gain + 1 if new_pos < int(sat["min_new_positives"]) else 0
            if no_gain >= int(sat["patience"]):
                print(f"\n    収穫の無い round が {no_gain} 回続いたため終了します（飽和）。")
                break

        discovered = len(accepted)
        accepted = [{**m, "discovered": True} for m in accepted] + seeded_queries
        if not accepted:
            raise SystemExit(
                "採用された語が0語です。**閾値を緩めないでください。** 緩めると、後の工程すべてが\n"
                "雑音に乗ります。これは母集団の側の問題です。取れる手は2つです。\n"
                "  1. 母集団を変える（config/discovery.yaml の corpus を広げる、"
                "または doc/ENGINEERING.md §3 のとおり情報源を足す）\n"
                "  2. 人が書いた語で回す（tools/run_pipeline.py --no-discover）。"
                "その場合、探索の幅は人の語彙で止まります")
        if not discovered:
            print(f"\n**拡張語は0語でした。** 標識に使った語を除くと、閾値"
                  f"（G² >= {sco['min_g2']} かつ 効果量 >= {sco['min_log_ratio']}）を満たす語が"
                  "母集団にありません。検索語は定義の phrase そのものになります。")

        key = "precision_lower" if conf["validation"]["metric_by_kind"][ns.kind] == "precision" else "new_positives"
        accepted.sort(key=lambda m: (not m.get("discovered"), -(m[key] or 0)))
        run_at = manifest.data["started_at"][11:19].replace(":", "")
        out_json = os.path.join(ns.out, f"discovery-{ns.kind}-{day_stamp}-{run_at}.json")
        cb.write_json(out_json, {"kind": ns.kind, "discovered_on": cb.today().isoformat(),
                                 "sampling_seed": seed, "windows": t_sample,
                                 "corpus": {"target": len(target), "background": len(background),
                                            "positives": len(pos)},
                                 "accepted": accepted, "rounds": rounds})
        manifest.output(out_json)

        query_path = cb.path("config", f"queries_auto-{ns.kind}-{day_stamp}.txt")
        if not ns.dry_run:
            v = conf["validation"]
            lines = [f"# {ns.kind} の検索語（{cb.today()} / 自動発見 {discovered}語・定義由来 "
                     f"{len(seeded_queries)}語）",
                     f"# 生成: tools/discover_queries.py / 実測値は log/{os.path.basename(out_json)}",
                     f"# 採用条件: 適合率の下限(Wilson) >= {v['min_precision']} または "
                     f"新規 positive >= {v['min_new_positives']} / "
                     f"該当 {v['min_total_hits']}〜{v['max_total_hits']}件"]
            if any(m["seeded"] for m in accepted):
                lines.append("# 注: 失敗事例側は人が書いた定義から出発します（doc/METHOD.md §5A）。"
                             "どの語が自動発見でどの語が定義由来かは file 末尾に書いています。")
            lines.append("")
            lines += [f'{m["query"]}' for m in accepted]
            lines.append("")
            lines.append("# 内訳: " + " / ".join(
                f'{m["query"]} = ' + ("自動発見" if m.get("discovered") else "定義由来（人が書いた語）")
                for m in accepted))
            cb.write_text_file(query_path, "\n".join(lines) + "\n")
            manifest.output(query_path)

        manifest.count(accepted=len(accepted), discovered=discovered, seeded=len(seeded_queries),
                       tried=len(tried), rounds=len(rounds))
        print(f"\n採用 {len(accepted)}語（うち自動発見 {discovered}語 / 定義由来 {len(seeded_queries)}語）"
              f" / 試行 {len(tried)}語 / round {len(rounds)}")
        print("  " + ", ".join(m["query"] for m in accepted[:10]))
        print(f"\n記録: {out_json}")
        print(f"検索語: {query_path}" + ("（--dry-run のため書いていません）" if ns.dry_run else ""))
        print(f"request: {budget.report()}")
        return 0
    finally:
        manifest.write(ns.out, budget)


if __name__ == "__main__":
    sys.exit(main())
