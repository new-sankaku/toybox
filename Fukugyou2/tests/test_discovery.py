import pytest

import casebase as cb
import collect_cases as cc
import discover_queries as dq

CONF = cb.load_yaml(cb.path("config", "discovery.yaml"))
SCREEN = cb.load_yaml(cb.path("config", "screen.yaml"))


def test_title_parsing_returns_none_instead_of_guessing():
    name, tagline = cc.parse_title("Show HN: Acme – invoice OCR for accountants")
    assert name == "Acme" and tagline.startswith("invoice OCR")
    assert cc.parse_title("A blog post about invoices") == (None, None)


def test_to_query_quotes_phrases_and_passes_and_queries():
    assert dq.to_query("workflow") == "workflow"
    assert dq.to_query("workflow automation") == '"workflow automation"'
    assert dq.to_query('+"shutting down" money') == '"shutting down" money'


def test_condition_terms_pulls_label_vocabulary_out_of_the_regexes():
    terms = dq.condition_terms(SCREEN, CONF, "product")
    assert {"invoice", "subscription", "payroll"} <= terms
    failure_terms = dq.condition_terms(SCREEN, CONF, "failure")
    assert "shutting" in failure_terms and "postmortem" in failure_terms


def test_failure_labeler_uses_the_definition_not_search_terms():
    label = dq.make_labeler("failure", CONF, SCREEN)
    assert label({"title": "We are shutting down Foo", "tagline": None, "story_text": None})
    assert not label({"title": "Show HN: a new invoice tool", "tagline": None, "story_text": None})


def test_product_labeler_requires_the_configured_number_of_axes():
    label = dq.make_labeler("product", CONF, SCREEN)
    strong = {"title": "Show HN: invoice OCR", "tagline": None,
              "story_text": "We automate invoice extraction. $29/month subscription, 300 customers."}
    weak = {"title": "Show HN: a wallpaper app", "tagline": None, "story_text": None}
    assert label(strong) and not label(weak)


def test_propose_reserves_slots_for_paired_queries():
    pos = [["invoice", "ocr"], ["invoice", "billing"], ["invoice", "ledger"]]
    neg = [["game"], ["game", "fun"], ["photo"]]

    class Sco(dict):
        pass
    sco = {"ngram_max": 1, "min_count": 2, "min_docs": 2, "top_k": 10,
           "pair_with_accepted": True, "max_anchors": 2, "max_pair_terms": 4}
    cases_pos = [{"title": " ".join(d), "tagline": None, "story_text": None} for d in pos]
    cases_neg = [{"title": " ".join(d), "tagline": None, "story_text": None} for d in neg]
    cand = dq.propose(cases_pos, cases_neg, set(), sco, set(), ["saas"], limit=6)
    assert any(c.startswith("+saas ") for c in cand)
    assert len(cand) <= 6


def test_discovery_config_declares_a_metric_for_every_kind():
    metrics = CONF["validation"]["metric_by_kind"]
    assert set(metrics) == {"product", "failure"}
    assert set(metrics.values()) <= {"precision", "yield"}


def test_saturation_settings_are_finite():
    sat = CONF["saturation"]
    assert sat["max_rounds"] >= 1 and sat["patience"] >= 1
    assert all(v > 0 for v in CONF["budget"].values())
