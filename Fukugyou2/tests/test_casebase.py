import os

import pytest

import casebase as cb


def test_log_likelihood_sign():
    assert cb.log_likelihood(10, 1, 1000, 1000) > 0
    assert cb.log_likelihood(1, 10, 1000, 1000) < 0
    assert cb.log_likelihood(5, 5, 1000, 1000) == pytest.approx(0.0, abs=1e-9)


def test_keyness_min_docs_drops_single_document_terms():
    target = [["invoice", "ocr", "brandname", "brandname", "brandname"], ["invoice", "billing"]]
    background = [["game"], ["game", "fun"]]
    terms = {r["term"] for r in cb.keyness(target, background, min_count=2, top_k=10, min_docs=2,
                                           min_g2=0.0, min_log_ratio=0.0)}
    assert "invoice" in terms
    assert "brandname" not in terms


def test_keyness_cuts_by_significance_and_effect_size():
    target = [["invoice"] for _ in range(3)]
    background = [["invoice"] for _ in range(3)]
    assert cb.keyness(target, background, min_count=2, min_g2=10.828, min_log_ratio=1.0) == []
    strong_t = [["invoice", "ocr"] for _ in range(40)]
    strong_b = [["game", "photo"] for _ in range(40)]
    rows = cb.keyness(strong_t, strong_b, min_count=3, min_g2=10.828, min_log_ratio=1.0)
    assert {r["term"] for r in rows} == {"invoice", "ocr"}
    assert all(r["g2"] >= 10.828 and r["log_ratio"] >= 1.0 for r in rows)


def test_keyness_refuses_empty_corpora():
    with pytest.raises(ValueError):
        cb.keyness([], [["a"]], min_count=1)


def test_log_likelihood_uses_the_full_2x2_form():
    assert cb.log_likelihood(500, 100, 10000, 10000) == pytest.approx(299.3512, abs=1e-3)
    with pytest.raises(ValueError):
        cb.log_likelihood(1, 1, 0, 10)


def test_wilson_lower_bound_rejects_small_samples():
    assert cb.wilson_lower(4, 20) == pytest.approx(0.081, abs=0.002)
    assert cb.wilson_lower(20, 20) == pytest.approx(0.839, abs=0.002)
    with pytest.raises(ValueError):
        cb.wilson_lower(0, 0)


def test_retry_wait_rejects_negative_and_nan_retry_after():
    assert cb._retry_wait(0, 1.0, "-5") == 0.0
    assert cb._retry_wait(0, 1.0, "nan") == 1.0
    assert cb._retry_wait(0, 1.0, "120") == 60.0
    assert cb._retry_wait(0, 1.0, "Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


def test_atomic_write_keeps_the_old_file_when_serialisation_fails(tmp_path):
    path = str(tmp_path / "cases.jsonl")
    cb.write_jsonl(path, [{"case_id": "hn:1"}])
    class Unserialisable:
        pass
    with pytest.raises(TypeError):
        cb.write_jsonl(path, [{"case_id": "hn:2", "x": Unserialisable()}])
    assert cb.read_jsonl(path) == [{"case_id": "hn:1"}]
    assert not [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")]


def test_budget_counts_one_request_per_call_not_per_retry(monkeypatch):
    b = cb.Budget({"example.test": 2})
    b.spend("https://example.test/a")
    assert b.report()["example.test"] == 1


def test_tokenize_strips_urls_entities_and_percent_encoding():
    text = 'See https://foo.com/a?b=1 &quot;great&quot; %2F <b>invoice</b> tool'
    assert cb.tokenize_en(text, set()) == ["see", "great", "invoice", "tool"]


def test_norm_url_ignores_scheme_www_query_and_trailing_slash():
    assert cb.norm_url("https://www.Example.com/a/?x=1") == cb.norm_url("http://example.com/a")
    assert cb.norm_url(None) is None


def test_distribution_reports_quartiles_not_mean():
    d = cb.distribution([1, 2, 3, 4, 100])
    assert d["p50"] == 3 and d["max"] == 100
    assert "mean" not in d and "avg" not in d


def test_merge_cases_deduplicates_by_id_and_url(tmp_path):
    path = str(tmp_path / "cases.jsonl")
    a = {"case_id": "hn:1", "url": "https://x.test/a", "kind": "product", "points": 10}
    b = {"case_id": "hn:2", "url": "https://www.x.test/a/", "kind": "product", "points": 5}
    c = {"case_id": "hn:3", "url": "https://y.test/b", "kind": "product", "points": 1}
    added, dup, rows = cb.merge_cases(path, [a, b, c])
    assert (added, dup) == (2, 1)
    added2, dup2, rows2 = cb.merge_cases(path, [a, c])
    assert (added2, dup2) == (0, 2)
    assert len(rows2) == 2


def test_budget_stops_over_the_cap():
    b = cb.Budget({"example.test": 2})
    b.spend("https://example.test/1")
    b.spend("https://example.test/2")
    with pytest.raises(SystemExit):
        b.spend("https://example.test/3")


def test_load_terms_refuses_to_exceed_limit(tmp_path):
    p = tmp_path / "terms.txt"
    p.write_text("# note\na\nb\nc\n", encoding="utf-8")
    assert cb.load_terms(str(p), 3, "語") == ["a", "b", "c"]
    with pytest.raises(SystemExit):
        cb.load_terms(str(p), 2, "語")


def test_manifest_records_reproducibility_fields(tmp_path):
    m = cb.Manifest("unit_test", {"a": 1, "_secret": "x"})
    m.count(added=3)
    m.fail(term="t", error="boom")
    path = m.write(str(tmp_path), cb.Budget())
    import json
    data = json.loads(open(path, encoding="utf-8").read())
    assert data["params"] == {"a": 1}
    assert data["counts"]["added"] == 3 and data["failures"][0]["term"] == "t"
    assert "python" in data and "started_at" in data and "ended_at" in data
    assert os.path.basename(path).endswith("-unit_test.json")
