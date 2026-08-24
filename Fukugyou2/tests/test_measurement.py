import json

import pytest

import casebase as cb
import discover_jp_terms as jt
import jp_market_check as jm

SOURCES = cb.load_yaml(cb.path("config", "sources.yaml"))
CATEGORIES = cb.load_yaml(cb.path("config", "categories.yaml"))
DISCOVERY = cb.load_yaml(cb.path("config", "discovery.yaml"))


def test_missing_total_count_header_is_a_failure_not_zero(monkeypatch):
    """『取れなかった』を『言及0件』にしないこと（規律3）。"""
    monkeypatch.setattr(cb, "http_json", lambda *a, **kw: ({}, "{}", {}))
    with pytest.raises(cb.SourceError):
        jm.qiita_count(SOURCES["qiita"], "請求書", None, cb.Budget())


def test_missing_nbhits_is_a_failure_not_zero(monkeypatch):
    monkeypatch.setattr(cb, "http_json", lambda *a, **kw: ({}, "{}", {}))
    with pytest.raises(cb.SourceError):
        jm.hn_count(SOURCES["hn_algolia"], "invoice", cb.Budget())


def test_unknown_category_id_stops_instead_of_being_ignored():
    with pytest.raises(SystemExit):
        jm.main(["--only", "billing", "typo_id", "--limit", "5"])
    with pytest.raises(SystemExit):
        jt.main(["--only", "nope", "--limit", "5"])


def test_every_category_has_the_terms_the_tools_read():
    for c in CATEGORIES["categories"]:
        assert c["en_terms"] and c["jp_demand_terms"] and c["jp_supply_terms"], c["id"]
        assert len(c["jp_demand_terms"]) >= int(DISCOVERY["jp_expansion"]["min_terms"]), c["id"]


def test_sources_declare_a_request_budget_for_every_host_used():
    hosts = set(SOURCES["budget"])
    assert {"hn.algolia.com", "qiita.com", "zenn.dev"} <= hosts


def test_discovery_thresholds_are_stricter_than_chance():
    sco = DISCOVERY["scoring"]
    assert sco["min_g2"] >= 3.841, "chi^2(1) p=.05 未満の閾値は偶然と区別できません"
    assert sco["min_log_ratio"] > 0, "効果量の下限が無いと G^2 だけで順位が決まります"
