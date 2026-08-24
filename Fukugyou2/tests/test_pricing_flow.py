import json

import pytest

import build_report as br
import casebase as cb
import fetch_pricing as fp
import screen_cases as sc

SCREEN = cb.load_yaml(cb.path("config", "screen.yaml"))
SOURCES = cb.load_yaml(cb.path("config", "sources.yaml"))


def test_pricing_links_are_taken_from_config_not_hardcoded():
    html = '<a href="/about">a</a><a href="/pricing">price</a><a href="/plans">p</a>'
    links = fp.pricing_links(html, "https://x.test/", SOURCES["page_fetch"]["pricing_paths"])
    assert "https://x.test/pricing" in links
    assert "https://x.test/about" not in links


def test_link_following_actually_fetches_the_second_page(tmp_path, monkeypatch):
    """回帰 test: 以前は list(urls) の複製を回していたため、2 page 目を永久に取りませんでした。"""
    pages = {
        "https://x.test/robots.txt": "User-agent: *\nAllow: /",
        "https://x.test/": '<html><a href="/pricing">Pricing</a></html>',
        "https://x.test/pricing": "<html><body>Pro $29 /mo billed monthly</body></html>",
    }
    seen = []

    def fake_text(url, timeout=30, max_bytes=0, budget=None):
        seen.append(url)
        if url not in pages:
            raise cb.SourceError(f"HTTP 404 {url}", status=404)
        return pages[url], url, 200

    monkeypatch.setattr(cb, "http_text", fake_text)
    cases = str(tmp_path / "cases-20260101.jsonl")
    cb.write_jsonl(cases, [{"case_id": "hn:1", "kind": "product", "title": "t",
                            "url": "https://x.test/", "points": 100}])
    fp.main(["--cases", cases, "--out", str(tmp_path), "--limit", "5", "--kind", "product"])
    rows = cb.read_jsonl(str(tmp_path / f"pricing-{cb.stamp()}.jsonl"))
    assert "https://x.test/pricing" in seen
    assert len(rows[0]["pages"]) == 2
    assert rows[0]["matches"] and rows[0]["state"] == "fetched"


def test_three_pricing_states_stay_separate_in_the_report():
    """『取得したが証拠なし』『取得失敗』『取りに行っていない』を混ぜないこと。"""
    marks = br.axis_marks(SCREEN["axes"])
    items = [
        {"case_id": "a", "title": "fetched", "url": "u", "discussion_url": "d", "points": 1,
         "created_at": "2026-01-01", "categories": [], "axes_met": [], "axes_met_count": 0,
         "pricing_state": "fetched"},
        {"case_id": "b", "title": "failed", "url": "u", "discussion_url": "d", "points": 1,
         "created_at": "2026-01-01", "categories": [], "axes_met": [], "axes_met_count": 0,
         "pricing_state": "failed"},
        {"case_id": "c", "title": "not attempted", "url": "u", "discussion_url": "d", "points": 1,
         "created_at": "2026-01-01", "categories": [], "axes_met": [], "axes_met_count": 0,
         "pricing_state": "not_attempted"},
    ]
    cells = [r.split("|")[6].strip() for r in br.case_rows(items, {}, 10, marks)]
    assert cells == ["×", "取得失敗", "未取得"]


def test_axis_marks_follow_the_config_not_a_hardcoded_table():
    marks = br.axis_marks({"stock": {}, "ai": {}, "proof": {}, "b2b": {}, "moat": {}})
    assert len(set(marks.values())) == 5
    assert marks["stock"] == "S"


def test_cost_is_not_counted_as_recurring_revenue():
    """`$7/month VPS` は継続課金の証拠ではありません（著者が払う原価です）。"""
    conditions = sc.compile_conditions(SCREEN)
    window = int(SCREEN["context_window"])
    cost = {"title": "Show HN: I put an AI agent on a $7/month VPS", "tagline": None, "story_text": None}
    price = {"title": "Show HN: my invoice tool", "tagline": None,
             "story_text": "Plans start at $29/month per seat for teams."}
    cond = next(c for c in conditions if c["id"] == "stock_subscription_word")
    assert sc.match_in_context(cond, sc.case_text(cost), window)[0] is None
    assert sc.match_in_context(cond, sc.case_text(price), window)[0] is not None


def test_recurring_theme_is_not_recurring_revenue():
    conditions = sc.compile_conditions(SCREEN)
    cond = next(c for c in conditions if c["id"] == "stock_subscription_word")
    text = "A recurring theme we ran into was that agents are slow."
    assert sc.match_in_context(cond, text, int(SCREEN["context_window"]))[0] is None


def test_open_source_mark_is_lifted_by_real_pricing_evidence():
    conditions = sc.compile_conditions(SCREEN)
    excludes = [{**e, "patterns": [__import__("re").compile(p) for p in e["any_of"]]}
                for e in SCREEN["exclude"]]
    case = {"title": "Show HN: an open-source Zapier alternative", "tagline": None, "story_text": None}
    assert "oss_or_template" in sc.evaluate(case, conditions, excludes, None)["exclude_marks"]
    with_price = sc.evaluate(case, conditions, excludes, {"matches": [{"pattern": "p", "sample": "$29 /mo"}]})
    assert "oss_or_template" not in with_price["exclude_marks"]
