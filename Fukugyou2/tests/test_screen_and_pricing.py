import re

import pytest

import casebase as cb
import fetch_pricing as fp
import screen_cases as sc

SCREEN = cb.load_yaml(cb.path("config", "screen.yaml"))


def case(title, story_text=None, tagline=None):
    return {"title": title, "tagline": tagline, "story_text": story_text}


def test_every_condition_regex_compiles_and_names_a_known_axis():
    axes = set(SCREEN["axes"])
    for c in SCREEN["conditions"]:
        assert c["axis"] in axes, c["id"]
        for p in c["any_of"]:
            re.compile(p)


def test_evaluate_counts_axes_and_keeps_evidence():
    conditions = sc.compile_conditions(SCREEN)
    excludes = [{**e, "patterns": [re.compile(p) for p in e["any_of"]]} for e in SCREEN["exclude"]]
    r = sc.evaluate(case("Show HN: Invoice OCR", "We automate invoice extraction. $29/month, 200 customers."),
                    conditions, excludes, None)
    assert r["by_axis"].get("stock", 0) >= 1
    assert r["by_axis"].get("ai", 0) >= 1
    assert r["by_axis"].get("b2b", 0) >= 1
    assert r["evidence"]


def test_exclude_marks_but_does_not_delete():
    conditions = sc.compile_conditions(SCREEN)
    excludes = [{**e, "patterns": [re.compile(p) for p in e["any_of"]]} for e in SCREEN["exclude"]]
    r = sc.evaluate(case("Show HN: an NFT wallet for web3 traders"), conditions, excludes, None)
    assert "crypto" in r["exclude_marks"]


def test_pricing_condition_needs_pricing_evidence_not_text():
    conditions = sc.compile_conditions(SCREEN)
    excludes = []
    text_only = sc.evaluate(case("$29 /mo billed monthly"), conditions, excludes, None)
    assert "stock_pricing_page" not in text_only["matched"]
    pattern = next(c for c in SCREEN["conditions"] if c["id"] == "stock_pricing_page")["any_of"][0]
    with_page = sc.evaluate(case("anything"), conditions, excludes,
                            {"matches": [{"pattern": pattern, "sample": "$29 /mo"}]})
    assert "stock_pricing_page" in with_page["matched"]


def test_html_to_text_drops_script_and_style():
    html = "<html><head><style>a{}</style><script>var x=1</script></head><body><p>Pro $29 /mo</p></body></html>"
    text = fp.to_text(html)
    assert "var x" not in text and "a{}" not in text
    assert "Pro $29 /mo" in text


def test_pricing_patterns_match_a_real_pricing_layout():
    patterns = [re.compile(p) for c in SCREEN["conditions"] if c["evidence"] == "pricing" for p in c["any_of"]]
    text = fp.to_text("<div>Freelancer, $25 /mo · Team ¥1,200 / 月 · billed annually</div>")
    assert len(fp.match_all(patterns, text)) >= 2


@pytest.mark.parametrize("status,expected", [(401, False), (403, False), (404, True), (500, None)])
def test_robots_status_follows_rfc9309(monkeypatch, status, expected):
    def fake(url, timeout=30, max_bytes=0):
        raise cb.SourceError(f"HTTP {status}", status=status)
    monkeypatch.setattr(cb, "http_text", fake)
    assert fp.robots_allowed("https://example.test/page", {}, 5) is expected


def test_robots_disallow_is_respected(monkeypatch):
    monkeypatch.setattr(cb, "http_text",
                        lambda url, timeout=30, max_bytes=0: ("User-agent: *\nDisallow: /private", url, 200))
    cache = {}
    assert fp.robots_allowed("https://example.test/private/x", cache, 5) is False
    assert fp.robots_allowed("https://example.test/public", cache, 5) is True
