import math

import pytest

from tictok import analytics as an


def _approx(x, y, tol=1e-9):
    return math.isclose(x, y, rel_tol=0, abs_tol=tol)


# ---- 統計ヘルパー -----------------------------------------------------------

class TestPercentile:
    def test_empty_is_zero_not_none(self):
        assert an._percentile([], 50.0) == 0.0
        assert an._median([]) == 0.0

    def test_single_value_ignores_pct(self):
        assert an._percentile([7], 0.0) == 7.0
        assert an._percentile([7], 100.0) == 7.0

    def test_linear_interpolation(self):
        # rank = 0.25*(4-1) = 0.75 → 1*0.25 + 2*0.75
        assert _approx(an._percentile([1, 2, 3, 4], 25.0), 1.75)
        assert _approx(an._percentile([1, 2, 3, 4], 75.0), 3.25)

    def test_median_even_and_odd(self):
        assert _approx(an._median([1, 2, 3, 4]), 2.5)
        assert _approx(an._median([5, 1, 3]), 3.0)

    def test_input_is_not_mutated(self):
        values = [3, 1, 2]
        an._percentile(values, 50.0)
        assert values == [3, 1, 2]


class TestWilsonCi:
    def test_zero_denominator_is_none(self):
        assert an._wilson_ci(0, 0) is None
        assert an._wilson_ci(3, -1) is None

    def test_symmetric_half_split(self):
        assert an._wilson_ci(5, 10) == [23.7, 76.3]

    def test_zero_successes_floors_at_zero(self):
        lo, hi = an._wilson_ci(0, 10)
        assert lo == 0.0
        assert 0.0 < hi < 100.0

    def test_all_successes_caps_at_hundred(self):
        lo, hi = an._wilson_ci(10, 10)
        assert hi == 100.0
        assert 0.0 < lo < 100.0


class TestRankAndCorrelation:
    def test_rank_average_assigns_mean_rank_to_ties(self):
        assert an._rank_average([10, 20, 20, 30]) == [1.0, 2.5, 2.5, 4.0]

    def test_spearman_perfect_monotone(self):
        assert _approx(an._spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        assert _approx(an._spearman([1, 2, 3, 4], [40, 30, 20, 10]), -1.0)

    def test_spearman_is_rank_based_not_linear(self):
        # 単調だが非線形。Pearsonなら1未満、Spearmanは1.0。
        xs = [1, 2, 3, 4, 5]
        ys = [1, 2, 4, 8, 1000]
        assert _approx(an._spearman(xs, ys), 1.0)
        assert an._pearson(xs, ys) < 0.9

    def test_too_few_points_is_none(self):
        assert an._spearman([1, 2], [1, 2]) is None
        assert an._pearson([1, 2], [1, 2]) is None

    def test_constant_column_is_none(self):
        assert an._pearson([1, 1, 1], [1, 2, 3]) is None
        assert an._spearman([1, 1, 1], [1, 2, 3]) is None


class TestSpearmanSignificance:
    def test_none_r_propagates(self):
        assert an._spearman_significant(None, 100) is None

    def test_df_below_one_is_false(self):
        assert an._spearman_significant(0.9, 3, k_controls=1) is False

    def test_perfect_correlation_needs_five_points(self):
        assert an._spearman_significant(1.0, 4) is False
        assert an._spearman_significant(1.0, 5) is True

    def test_moderate_r_small_n_not_significant(self):
        assert an._spearman_significant(0.5, 4) is False

    def test_strong_r_large_n_significant(self):
        assert an._spearman_significant(0.8, 30) is True

    def test_t975_falls_back_to_normal_beyond_table(self):
        assert an._t_975(0) == an._T975[1]
        assert an._t_975(1) == 12.706
        assert an._t_975(31) == 1.96


class TestLinearAlgebra:
    def test_solve_diagonal_system(self):
        assert an._solve_linear([[2.0, 0.0], [0.0, 4.0]], [2.0, 8.0]) == [1.0, 2.0]

    def test_singular_system_is_none(self):
        assert an._solve_linear([[1.0, 1.0], [2.0, 2.0]], [1.0, 2.0]) is None

    def test_ols_residuals_are_zero_for_exact_fit(self):
        xs = [[1.0, 2.0, 3.0, 4.0]]
        y = [3.0, 5.0, 7.0, 9.0]  # y = 2x + 1
        residuals = an._ols_residuals(y, xs)
        assert all(_approx(r, 0.0, 1e-8) for r in residuals)

    def test_partial_spearman_requires_enough_points(self):
        controls = [[1.0, 2.0, 3.0]]
        assert an._partial_spearman([1, 2, 3], [1, 2, 3], controls) is None

    def test_partial_spearman_removes_the_control(self):
        # a,bは素で完全相関だが、両者ともcontrolの単調変換なので偏相関は消える。
        a = [1, 2, 3, 4, 5, 6]
        b = [2, 4, 6, 8, 10, 12]
        controls = [[10, 20, 30, 40, 50, 60]]
        assert _approx(an._spearman(a, b), 1.0)
        assert an._partial_spearman(a, b, controls) is None


# ---- 区間演算 ---------------------------------------------------------------

class TestIntervals:
    def test_merge_sorts_joins_and_drops_empty(self):
        merged = an._merge_intervals([(5, 7), (1, 3), (3, 4), (10, 10), (9, 8)])
        assert merged == [(1, 4), (5, 7)]

    def test_merge_of_nothing_is_empty(self):
        assert an._merge_intervals([]) == []
        assert an._merge_intervals([(5, 5)]) == []

    def test_merge_absorbs_contained_interval(self):
        assert an._merge_intervals([(0, 100), (10, 20)]) == [(0, 100)]

    def test_subtract_punches_a_hole(self):
        assert an._subtract_intervals([(0, 10)], [(3, 5)]) == [(0, 3), (5, 10)]

    def test_subtract_full_overlap_is_empty(self):
        assert an._subtract_intervals([(0, 10)], [(0, 10)]) == []
        assert an._subtract_intervals([(2, 8)], [(0, 100)]) == []

    def test_subtract_disjoint_is_identity(self):
        assert an._subtract_intervals([(0, 10)], [(20, 30)]) == [(0, 10)]

    def test_subtract_trims_edges(self):
        assert an._subtract_intervals([(0, 10)], [(-5, 2), (8, 50)]) == [(2, 8)]

    def test_in_intervals_is_half_open(self):
        ints = [(0, 3), (10, 12)]
        assert an._in_intervals(0, ints) is True
        assert an._in_intervals(2.999, ints) is True
        assert an._in_intervals(3, ints) is False
        assert an._in_intervals(5, ints) is False
        assert an._in_intervals(11, ints) is True

    def test_total_span_sums_lengths(self):
        assert an._total_span([(0, 3), (10, 12)]) == 5


# ---- 集中度 -----------------------------------------------------------------

class TestConcentration:
    def test_empty_returns_neutral_shape(self):
        out = an.concentration([])
        assert out == {"gini": 0.0, "n_users": 0, "total": 0, "lorenz": [], "top": []}

    def test_perfect_equality_has_zero_gini(self):
        out = an.concentration([1, 1, 1, 1])
        assert out["gini"] == 0.0
        assert out["n_users"] == 4
        assert out["total"] == 4

    def test_nonpositive_values_are_dropped_from_denominator(self):
        out = an.concentration([0, -5, 3, None])
        assert out["n_users"] == 1
        assert out["total"] == 3
        assert out["gini"] == 0.0

    def test_skewed_distribution_has_high_gini_and_top_share(self):
        out = an.concentration([1] * 99 + [10000])
        assert out["gini"] > 0.9
        top1 = next(t for t in out["top"] if t["pct"] == 1)
        assert top1["users"] == 1
        assert top1["share"] > 0.99

    def test_lorenz_starts_at_origin_and_ends_at_one(self):
        out = an.concentration([1, 2, 3, 4])
        assert out["lorenz"][0] == {"p": 0.0, "share": 0.0}
        assert out["lorenz"][-1] == {"p": 1.0, "share": 1.0}

    def test_lorenz_never_exceeds_the_requested_point_budget(self):
        for n in list(range(1, 130)) + [200, 401, 1000]:
            for points in (5, 12, 40):
                out = an.concentration([1] * n, lorenz_points=points)
                assert len(out["lorenz"]) <= points, (n, points)
                assert out["lorenz"][0] == {"p": 0.0, "share": 0.0}
                assert out["lorenz"][-1] == {"p": 1.0, "share": 1.0}

    def test_lorenz_points_are_monotonic_and_evenly_spread(self):
        out = an.concentration(list(range(1, 501)))
        ps = [p["p"] for p in out["lorenz"]]
        shares = [p["share"] for p in out["lorenz"]]
        assert ps == sorted(ps) and shares == sorted(shares)
        gaps = [b - a for a, b in zip(ps, ps[1:])]
        assert max(gaps) - min(gaps) < 0.01

    def test_top_bucket_always_has_at_least_one_user(self):
        out = an.concentration([5, 5, 5])
        for t in out["top"]:
            assert t["users"] >= 1


# ---- peri-event ------------------------------------------------------------

class TestPeriHelpers:
    def test_collapse_onsets_keeps_first_per_refractory(self):
        assert an._collapse_onsets([0, 1, 2, 10, 11, 20], 5) == [0, 10, 20]

    def test_collapse_onsets_keeps_all_when_far_apart(self):
        assert an._collapse_onsets([0, 100, 200], 5) == [0, 100, 200]

    def test_aggregate_below_min_events_is_unavailable(self):
        windows = [[1.0, 2.0] for _ in range(an._PERI_MIN_EVENTS - 1)]
        assert an._peri_aggregate([windows]) == (None, None)

    def test_aggregate_single_cluster_zero_variance(self):
        windows = [[1.0, 2.0] for _ in range(5)]
        mean, ci = an._peri_aggregate([windows])
        assert mean == [1.0, 2.0]
        assert ci == [0.0, 0.0]

    def test_aggregate_uses_cluster_robust_variance(self):
        clusters = [[[0.0], [2.0], [0.0]], [[2.0], [0.0]]]
        mean, ci = an._peri_aggregate(clusters)
        assert _approx(mean[0], 0.8)
        # CR1: (G/(G-1)) * Σ(Σ residual)^2 / n^2, half-width = t(G-1)*sqrt(var)
        assert _approx(ci[0], 12.706 * 0.16, 1e-6)

    def test_empty_clusters_are_ignored(self):
        assert an._peri_aggregate([[], []]) == (None, None)


class TestChunked:
    def test_splits_by_size_without_loss(self):
        chunks = list(an._chunked(list(range(7)), size=3))
        assert chunks == [[0, 1, 2], [3, 4, 5], [6]]

    def test_empty_yields_nothing(self):
        assert list(an._chunked([], size=3)) == []


# ---- battle flow ヘルパー ----------------------------------------------------

class TestBattleFlowHelpers:
    def test_step_before_first_sample_is_zero(self):
        assert an._bf_step([(10.0, 5, 3)], 5.0, 1) == 0

    def test_step_is_inclusive_at_sample_time(self):
        series = [(10.0, 5, 3), (20.0, 9, 4)]
        assert an._bf_step(series, 10.0, 1) == 5
        assert an._bf_step(series, 19.999, 1) == 5
        assert an._bf_step(series, 20.0, 2) == 4
        assert an._bf_step(series, 999.0, 1) == 9

    def test_crit_extra_only_counts_resolved_crits(self):
        battle = {
            "glove_events": [
                {"crit": None},
                {"crit": False, "score_delta": 100, "mult": 5, "t": 1},
                {"crit": True, "score_delta": 500, "mult": 5, "t": 3},
                {"crit": True, "score_delta": 100, "mult": 1, "t": 4},
                {"crit": True, "score_delta": None, "mult": 5, "t": 5},
            ]
        }
        extras, unresolved = an._bf_crit_extra(battle)
        assert extras == [(3.0, 400.0)]
        assert unresolved == 3

    def test_crit_extra_of_empty_battle(self):
        assert an._bf_crit_extra({}) == ([], 0)

    def test_extra_before_is_inclusive_and_cumulative(self):
        extras = [(3.0, 400.0), (9.0, 100.0)]
        assert an._bf_extra_before(extras, 2.0) == 0.0
        assert an._bf_extra_before(extras, 3.0) == 400.0
        assert an._bf_extra_before(extras, 9.0) == 500.0


def _sample(t, own, parts):
    opp = max((p.get("score") or 0) for p in parts if p.get("side") != "own") if parts else 0
    return {"t": t, "own": own, "opp": opp, "parts": parts}


class TestRivalSeries:
    def test_series_shorter_than_two_is_rejected(self):
        assert an._bf_rival_series({"score_series": [{"t": 1, "own": 1, "opp": 0}]}, 100) == (
            None, "no_series",
        )
        assert an._bf_rival_series({}, 100) == (None, "no_series")

    def test_all_samples_after_settle_time_is_rejected(self):
        battle = {"score_series": [{"t": 50, "own": 1, "opp": 0, "parts": []},
                                   {"t": 60, "own": 2, "opp": 0, "parts": []}]}
        assert an._bf_rival_series(battle, 10) == (None, "no_series")

    def test_one_versus_one_passes_through_opp(self):
        parts = [{"id": "a", "side": "own", "score": 20}, {"id": "b", "side": "opp", "score": 9}]
        battle = {"score_series": [_sample(1, 10, parts), _sample(2, 20, parts)]}
        series, form = an._bf_rival_series(battle, 100)
        assert form == "1v1"
        assert series == [(1, 10, 9), (2, 20, 9)]

    def test_team_battle_requires_exactly_two_teams(self):
        two = [{"id": "a", "side": "own", "team_id": 1, "score": 5},
               {"id": "b", "side": "opp", "team_id": 2, "score": 3}]
        three = two + [{"id": "c", "side": "opp", "team_id": 3, "score": 1}]
        ok = {"type": "team", "score_series": [_sample(1, 5, two), _sample(2, 5, two)]}
        assert an._bf_rival_series(ok, 100)[1] == "team"
        bad = {"type": "team", "score_series": [_sample(1, 5, three), _sample(2, 5, three)]}
        assert an._bf_rival_series(bad, 100) == (None, "chimera")

    def test_multi_reconstructs_top_rival(self):
        p1 = [{"id": "a", "side": "own", "score": 10},
              {"id": "b", "side": "opp", "score": 5},
              {"id": "c", "side": "opp", "score": 2}]
        p2 = [{"id": "a", "side": "own", "score": 20},
              {"id": "b", "side": "opp", "score": 9},
              {"id": "c", "side": "opp", "score": 3}]
        battle = {"score_series": [_sample(1, 10, p1), _sample(2, 20, p2)]}
        series, form = an._bf_rival_series(battle, 100)
        assert form == "multi"
        # opp列はキメラ(max)ではなく直近rival(b)の実スコア。
        assert series == [(1, 10, 5), (2, 20, 9)]

    def test_multi_with_tied_leaders_is_chimera(self):
        parts = [{"id": "a", "side": "own", "score": 10},
                 {"id": "b", "side": "opp", "score": 5},
                 {"id": "c", "side": "opp", "score": 5}]
        battle = {"score_series": [_sample(1, 10, parts), _sample(2, 10, parts)]}
        assert an._bf_rival_series(battle, 100) == (None, "chimera")

    def test_multi_with_late_joining_rival_is_chimera(self):
        early = [{"id": "a", "side": "own", "score": 10},
                 {"id": "c", "side": "opp", "score": 2}]
        late = [{"id": "a", "side": "own", "score": 20},
                {"id": "b", "side": "opp", "score": 9},
                {"id": "c", "side": "opp", "score": 3}]
        battle = {"score_series": [_sample(1, 10, early), _sample(2, 20, late)]}
        assert an._bf_rival_series(battle, 100) == (None, "chimera")

    def test_reference_sample_is_taken_at_settle_time_not_last(self):
        # 確定時点ではbが首位。その後roster解体でbが消えcだけが残る。
        settled = [{"id": "a", "side": "own", "score": 20},
                   {"id": "b", "side": "opp", "score": 9},
                   {"id": "c", "side": "opp", "score": 3}]
        collapsed = [{"id": "a", "side": "own", "score": 20},
                     {"id": "b", "side": "opp", "score": 9},
                     {"id": "c", "side": "opp", "score": 3}]
        battle = {"score_series": [_sample(1, 10, settled), _sample(2, 20, settled),
                                   _sample(500, 20, collapsed)]}
        series, form = an._bf_rival_series(battle, 10)
        assert form == "multi"
        assert [s[2] for s in series] == [9, 9, 9]


class TestRateAndTailStats:
    def test_rate_with_zero_denominator(self):
        assert an._bf_rate(0, 0) == {"n": 0, "k": 0, "rate": None, "ci": None}

    def test_rate_rounds_to_four_places(self):
        out = an._bf_rate(1, 3)
        assert out["rate"] == 0.3333
        assert out["ci"] is not None

    def test_tail_stats_empty(self):
        out = an._bf_tail_stats([], [])
        assert out["n"] == 0
        assert out["median"] is None
        assert (out["heavy"], out["flat"], out["light"]) == (0, 0, 0)

    def test_tail_stats_classifies_against_uniform(self):
        shares = [0.5, 0.1, 0.2]
        uniform = [0.2, 0.2, 0.2]
        out = an._bf_tail_stats(shares, uniform)
        assert out["n"] == 3
        assert (out["heavy"], out["flat"], out["light"]) == (1, 1, 1)
        assert out["median"] == 0.2
        assert out["uniform_median"] == 0.2

    def test_tail_stats_boundaries_are_inclusive_for_heavy_and_light(self):
        # 比がちょうど1.5 / 0.5 になる値(float誤差の出ない組)。
        out = an._bf_tail_stats([0.75, 0.25], [0.5, 0.5])
        assert (out["heavy"], out["light"], out["flat"]) == (1, 1, 0)


class TestCvStat:
    def test_empty_is_none_not_zero(self):
        assert an._cv_stat([]) == {"n": 0, "median": None, "p25": None,
                                   "p75": None, "max": None}

    def test_values_are_rounded_to_two_places(self):
        out = an._cv_stat([1.0, 2.0, 3.0, 4.0])
        assert out == {"n": 4, "median": 2.5, "p25": 1.75, "p75": 3.25, "max": 4.0}


class TestEntryBreakdown:
    def test_top_n_and_rest_folded(self):
        out = an._entry_breakdown({"a": 5, "b": 3, "c": 1}, 9, 2)
        assert [o["key"] for o in out] == ["a", "b", "(その他)"]
        assert out[-1]["count"] == 1
        assert out[0]["ratio"] == round(5 / 9, 4)

    def test_no_rest_row_when_within_limit(self):
        out = an._entry_breakdown({"a": 5, "b": 3}, 8, 5)
        assert [o["key"] for o in out] == ["a", "b"]

    def test_ties_break_alphabetically(self):
        out = an._entry_breakdown({"b": 2, "a": 2}, 4, 5)
        assert [o["key"] for o in out] == ["a", "b"]

    def test_zero_denominator_yields_none_ratio(self):
        out = an._entry_breakdown({"a": 5}, 0, 5)
        assert out[0]["ratio"] is None

    def test_follow_breakdown_always_lists_all_statuses(self):
        out = an._follow_breakdown({"following": 2}, 4)
        assert [o["key"] for o in out] == list(an.FOLLOW_STATUSES)
        assert out[0] == {"key": "following", "count": 2, "ratio": 0.5}
        assert all(o["count"] == 0 and o["ratio"] == 0.0 for o in out[1:])

    def test_follow_breakdown_zero_denominator(self):
        out = an._follow_breakdown({}, 0)
        assert all(o["ratio"] is None for o in out)


class TestSessionLongEnough:
    def test_live_session_is_always_included(self):
        assert an._session_long_enough({"started_at": 0, "ended_at": None}) is True

    def test_boundary_is_inclusive(self):
        assert an._session_long_enough({"started_at": 0, "ended_at": 1200}) is True
        assert an._session_long_enough({"started_at": 0, "ended_at": 1199}) is False


# ---- 横断reduce -------------------------------------------------------------

def _sess(sid=1, uid="a", started=1000.0, ended=5000.0, bucket=60, owner="a"):
    return {"id": sid, "unique_id": uid, "started_at": started, "ended_at": ended,
            "bucket_seconds": bucket, "owner_key": owner}


class TestReduceSummary:
    def test_empty_rows(self):
        out = an.reduce_summary([])
        assert out == {"streamers": 0, "sessions": 0, "first_at": None, "last_at": None,
                       "buckets": 0, "active_seconds": 0, "joins": 0, "diamonds": 0,
                       "comments": 0}

    def test_live_session_uses_started_at_as_end(self):
        rows = [
            (_sess(1, "a", 100, 200), {"nb": 2, "act": 120, "j": 5, "d": 10, "c": 3}),
            (_sess(2, "a", 300, None), {"nb": 1, "act": 60, "j": 1, "d": 0, "c": 2}),
        ]
        out = an.reduce_summary(rows)
        assert out["first_at"] == 100
        assert out["last_at"] == 300
        assert out["streamers"] == 1
        assert out["sessions"] == 2
        assert (out["joins"], out["diamonds"], out["comments"]) == (6, 10, 5)
        assert out["active_seconds"] == 180


class TestReduceTimeIndex:
    def test_unknown_metric_raises(self):
        with pytest.raises(ValueError):
            an.reduce_time_index([], "viewers")

    def test_index_is_relative_to_session_mean(self):
        cells = [[1, 0, 10, 10, 0, 0, 0, 0], [1, 1, 10, 30, 0, 0, 0, 0]]
        out = an.reduce_time_index([(_sess(), {"cells": cells})], "joins")
        assert out["n_sessions"] == 1
        assert out["n_observations"] == 2
        assert out["slots"][0]["all"] == {"index": 0.5, "n": 1}
        assert out["slots"][1]["all"] == {"index": 1.5, "n": 1}
        assert out["slots"][0]["dow"][1] == {"index": 0.5, "n": 1}
        assert out["slots"][0]["dow"][0] == {"index": None, "n": 0}

    def test_low_coverage_cells_are_excluded_from_the_distribution(self):
        # bucket 60s → min_nb = 1200*0.25/60 = 5。nb=2のcellは分布に入らないが
        # session平均(baseline)には効く。
        cells = [[1, 0, 10, 10, 0, 0, 0, 0], [1, 5, 2, 100, 0, 0, 0, 0]]
        out = an.reduce_time_index([(_sess(), {"cells": cells})], "joins")
        assert out["n_observations"] == 1
        assert out["slots"][5]["all"]["n"] == 0
        # baseline = 110/12、slot0 rate = 1.0
        assert out["slots"][0]["all"]["index"] == round(1.0 / (110 / 12), 3)

    def test_short_sessions_are_dropped_entirely(self):
        cells = [[1, 0, 10, 10, 0, 0, 0, 0], [1, 1, 10, 30, 0, 0, 0, 0]]
        rows = [(_sess(started=0, ended=600), {"cells": cells})]
        out = an.reduce_time_index(rows, "joins")
        assert out["n_sessions"] == 0
        assert out["n_observations"] == 0

    def test_session_with_no_metric_volume_is_skipped(self):
        cells = [[1, 0, 10, 0, 0, 0, 0, 0]]
        out = an.reduce_time_index([(_sess(), {"cells": cells})], "joins")
        assert out["n_sessions"] == 0

    def test_slots_cover_the_whole_day(self):
        out = an.reduce_time_index([], "joins")
        assert len(out["slots"]) == an._DAY_SLOTS_20
        assert out["slots"][-1]["minute"] == (an._DAY_SLOTS_20 - 1) * 20
        assert all(len(s["dow"]) == 7 for s in out["slots"])


class TestReduceJoinQuality:
    def test_hours_and_ratios(self):
        rows = [
            (_sess(), {"h": [[10, 3, 8]], "excl": 2}),
            (_sess(2), {"h": [[10, 1, 2], [23, 0, 5]], "excl": 1}),
        ]
        out = an.reduce_join_quality(rows)
        h10 = out["hours"][10]
        assert h10 == {"hour": 10, "new": 4, "returning": 6, "total": 10, "new_ratio": 0.4}
        assert out["hours"][23]["new_ratio"] == 0.0
        assert out["total"] == 15
        assert out["new"] == 4
        assert out["excluded"] == 3
        assert out["n_sessions"] == 2

    def test_empty_hour_ratio_is_zero_not_division_error(self):
        out = an.reduce_join_quality([(_sess(), {"h": [], "excl": 0})])
        assert len(out["hours"]) == 24
        assert all(h["new_ratio"] == 0.0 for h in out["hours"])
        assert out["new_ratio"] == 0.0


class TestReduceRetention:
    def _payload(self, jb, nb, hours=None):
        h = [[0, 0, 0] for _ in range(24)]
        for idx, triple in (hours or {}).items():
            h[idx] = list(triple)
        return {"h": h, "jb": list(jb), "nb": list(nb)}

    def test_lift_subtracts_the_drift_of_quiet_buckets(self):
        # drift = -4/2 = -2.0 → lift = (10 - (-2*2)) / 5 = 2.8
        rows = [(_sess(), self._payload(jb=[10, 5, 2], nb=[-4, 2]))]
        out = an.reduce_retention(rows)
        assert out["overall"]["lift_per_join"] == 2.8

    def test_no_quiet_buckets_means_zero_drift(self):
        rows = [(_sess(), self._payload(jb=[10, 5, 2], nb=[0, 0]))]
        assert an.reduce_retention(rows)["overall"]["lift_per_join"] == 2.0

    def test_no_joins_means_lift_is_none(self):
        rows = [(_sess(), self._payload(jb=[0, 0, 0], nb=[-4, 2]))]
        assert an.reduce_retention(rows)["overall"]["lift_per_join"] is None

    def test_join_rate_is_normalised_per_minute_of_observation(self):
        rows = [(_sess(bucket=60), self._payload([0, 0, 0], [0, 0], {7: (6, 30, 3)}))]
        out = an.reduce_retention(rows)
        assert out["by_hour"][7]["joins"] == 6
        assert out["by_hour"][7]["join_rate"] == 2.0
        assert out["by_hour"][7]["viewers"] == 10.0
        assert out["by_hour"][8]["join_rate"] is None
        assert out["by_hour"][8]["viewers"] is None
        assert out["overall"]["joins"] == 6


class TestReduceJoinContext:
    def _payload(self, **kw):
        base = {"bs": 0.0, "cs": 0.0, "as": 0.0, "bj": 0, "cj": 0, "nj": 0,
                "nb": 0, "ncl": 0}
        base.update(kw)
        return base

    def test_normal_seconds_is_the_remainder(self):
        rows = [(_sess(), self._payload(bs=100, cs=50, **{"as": 1000},
                                        bj=10, cj=5, nj=30, nb=2, ncl=1))]
        out = an.reduce_join_context(rows)
        assert out["battle"] == {"joins": 10, "seconds": 100, "per_min": 6.0}
        assert out["collab"] == {"joins": 5, "seconds": 50, "per_min": 6.0}
        assert out["normal"]["seconds"] == 850
        assert out["normal"]["per_min"] == round(30 / (850 / 60), 3)
        assert out["total_joins"] == 45
        assert (out["n_battles"], out["n_collabs"]) == (2, 1)

    def test_normal_seconds_never_goes_negative(self):
        rows = [(_sess(), self._payload(bs=600, cs=600, **{"as": 1000}, nj=3))]
        out = an.reduce_join_context(rows)
        assert out["normal"]["seconds"] == 0
        assert out["normal"]["per_min"] is None

    def test_empty_rows(self):
        out = an.reduce_join_context([])
        assert out["total_joins"] == 0
        assert out["battle"]["per_min"] is None


class TestReduceGlove:
    def _row(self, owner="a", bid="b1", events=None, windows=2, ok=1):
        return (
            _sess(owner=owner),
            {"battles": [{"bid": bid, "ok": ok, "w": windows, "ev": events or []}]},
        )

    def test_rate_is_over_decided_gifts_only(self):
        events = [
            [1, 10, 1],       # 1-15帯 crit
            [1, 10, 0],       # 1-15帯 通常
            [2, None, 1],     # 単価をunit_coinsで解決 → 16-50帯
            [3, 99999, 1],    # 帯の外
            [4, None, None],  # 単価も解決できない
            [1, 12, None],    # 判定不能 → undecidedのみ
        ]
        out = an.reduce_glove([self._row(events=events)], {2: 30})
        first = out["buckets"][0]
        assert (first["gifts"], first["crits"], first["undecided"]) == (2, 1, 1)
        assert first["rate"] == 50.0
        second = out["buckets"][1]
        assert (second["gifts"], second["crits"]) == (1, 1)
        assert out["total_gifts"] == 3
        assert out["total_crits"] == 2
        assert out["undecided"] == 1
        assert out["unresolved"] == 1
        assert out["range_out"] == 1
        assert out["overall_rate"] == pytest.approx(200 / 3)
        assert out["n_windows"] == 2
        assert out["n_battles"] == 1

    def test_dedup_is_per_owner_not_per_battle_id(self):
        same_owner = [self._row(owner="a", bid="b1", events=[[1, 10, 1]]),
                      self._row(owner="a", bid="b1", events=[[1, 10, 1]])]
        assert an.reduce_glove(same_owner, {})["total_gifts"] == 1
        both_owners = [self._row(owner="a", bid="b1", events=[[1, 10, 1]]),
                       self._row(owner="z", bid="b1", events=[[1, 10, 1]])]
        assert an.reduce_glove(both_owners, {})["total_gifts"] == 2

    def test_unparsed_battle_contributes_nothing(self):
        rows = [(_sess(), {"battles": [{"bid": "b1", "ok": 0}]})]
        out = an.reduce_glove(rows, {})
        assert out["total_gifts"] == 0
        assert out["n_windows"] == 0
        assert out["n_battles"] == 0

    def test_empty_buckets_have_none_rate_and_ci(self):
        out = an.reduce_glove([], {})
        assert len(out["buckets"]) == len(an.GLOVE_COIN_BUCKETS)
        assert all(b["rate"] is None and b["ci"] is None for b in out["buckets"])
        assert out["overall_rate"] is None

    def test_bucket_edges_are_inclusive(self):
        lo, hi = an.GLOVE_COIN_BUCKETS[0]
        rows = [self._row(bid=None, events=[[1, lo, 1], [1, hi, 0]])]
        out = an.reduce_glove(rows, {})
        assert out["buckets"][0]["gifts"] == 2
        assert out["range_out"] == 0


class TestReduceBattleRatio:
    def test_median_and_quartiles_of_uplift(self):
        rows = [
            (_sess(), {"battles": [{"bid": "x", "up": {"joins": 1.0, "comments": None,
                                                       "follows": 2.0, "diamonds": 4.0}}]}),
            (_sess(2), {"battles": [{"bid": "y", "up": {"joins": 3.0, "comments": 5.0,
                                                        "follows": 2.0, "diamonds": None}}]}),
        ]
        out = an.reduce_battle_ratio(rows)
        assert out["metrics"]["joins"] == {"median": 2.0, "p25": 1.5, "p75": 2.5, "n": 2}
        assert out["metrics"]["comments"] == {"median": 5.0, "p25": 5.0, "p75": 5.0, "n": 1}
        assert out["n_battles"] == 2

    def test_battle_id_is_deduped_across_sessions(self):
        rec = {"bid": "x", "up": {"joins": 9.0}}
        rows = [(_sess(), {"battles": [rec]}), (_sess(2), {"battles": [rec]})]
        out = an.reduce_battle_ratio(rows)
        assert out["metrics"]["joins"]["n"] == 1
        assert out["n_battles"] == 1

    def test_battles_without_uplift_are_ignored(self):
        rows = [(_sess(), {"battles": [{"bid": "x", "up": None}]})]
        out = an.reduce_battle_ratio(rows)
        assert out["metrics"]["joins"] == {"median": None, "p25": None, "p75": None, "n": 0}


class TestReducePeri:
    def _payload(self, spike_at=None, n_windows=5, j=100, b=200):
        win_len = an._PERI_PRE_BINS + an._PERI_POST_BINS + 1
        window = [0.0] * win_len
        if spike_at is not None:
            window[spike_at] = 1.0
        return {"q": 1, "j": j, "b": b, "ev": [list(window) for _ in range(n_windows)],
                "pl": []}

    def test_too_few_events_is_unavailable(self):
        rows = [(_sess(), self._payload(spike_at=8, n_windows=2))]
        out = an.reduce_peri(rows, "share")
        assert out["available"] is False
        assert out["n_events"] == 2
        assert out["baseline_rate"] == 0.5
        assert "uplift" not in out

    def test_uplift_peak_and_cumulative(self):
        rows = [(_sess(), self._payload(spike_at=8))]
        out = an.reduce_peri(rows, "share")
        assert out["available"] is True
        assert out["n_events"] == 5
        assert len(out["lags"]) == an._PERI_PRE_BINS + an._PERI_POST_BINS + 1
        assert out["lags"][an._PERI_PRE_BINS] == 0
        assert out["uplift"][8] == 1.0
        assert out["peak"]["lag"] == 20
        assert out["peak"]["uplift"] == 1.0
        assert out["peak"]["pct"] == 200.0
        assert out["cumulative"] == 1.0
        assert out["sig"][8] is True
        assert out["pre_rise"] is False

    def test_pre_rise_flags_reverse_causality(self):
        # baseline binより後・onset前(index 3..5)の立ち上がり。
        rows = [(_sess(), self._payload(spike_at=5))]
        out = an.reduce_peri(rows, "share")
        assert out["pre_rise"] is True

    def test_sessions_without_windows_still_feed_baseline(self):
        rows = [(_sess(), {"q": 1, "j": 60, "b": 30, "ev": [], "pl": []})]
        out = an.reduce_peri(rows, "battle")
        assert out["available"] is False
        assert out["n_sessions"] == 1
        assert out["baseline_rate"] == 2.0

    def test_unusable_sessions_are_skipped(self):
        out = an.reduce_peri([(_sess(), {"q": 0})], "share")
        assert out["n_sessions"] == 0
        assert out["baseline_rate"] == 0.0


class TestReduceScaleEfficiency:
    def test_coins_per_viewer_hour_and_median_scale(self):
        rows = [
            (_sess(1, "a"), {"avgv": 10.0, "coins": 100, "vmin": 120.0, "peak": 20}),
            (_sess(2, "a"), {"avgv": 30.0, "coins": 200, "vmin": 120.0, "peak": 40}),
        ]
        out = an.reduce_scale_efficiency(rows, {})
        assert len(out["streamers"]) == 1
        s = out["streamers"][0]
        assert s["sessions"] == 2
        assert s["avg_viewers"] == 20.0
        assert s["coins"] == 300
        assert s["coins_per_viewer_hour"] == 75.0
        assert s["nickname"] == "a"

    def test_sessions_without_viewer_data_are_dropped(self):
        rows = [(_sess(1, "a"), {"avgv": 0.0, "coins": 999, "vmin": 0.0})]
        assert an.reduce_scale_efficiency(rows, {})["streamers"] == []

    def test_sorted_by_coins_descending_and_owner_metadata_used(self):
        rows = [
            (_sess(1, "small"), {"avgv": 5.0, "coins": 10, "vmin": 60.0}),
            (_sess(2, "big"), {"avgv": 5.0, "coins": 500, "vmin": 60.0}),
        ]
        owners = {"big": {"nickname": "Big One", "avatar": "http://x/a.png"}}
        out = an.reduce_scale_efficiency(rows, owners)
        assert [s["unique_id"] for s in out["streamers"]] == ["big", "small"]
        assert out["streamers"][0]["nickname"] == "Big One"
        assert out["streamers"][1]["avatar"] == ""


class TestReduceEntrySource:
    def _payload(self, src=None, jfs=None, efs=None, roles=None,
                 jt=10, jm=8, jfm=6, et=4, em=3):
        return {
            "j": {"total": jt, "measured": jm, "fm": jfm,
                  "src": src or {}, "fs": jfs or {}},
            "e": {"total": et, "measured": em, "fs": efs or {},
                  "roles": roles or {"sub": [0, 0], "mod": [0, 0], "gg": [0, 0]}},
        }

    def test_coverage_uses_measured_over_total(self):
        rows = [(_sess(), self._payload(src={"following-live_cover": 8}))]
        out = an.reduce_entry_source(rows)
        assert out["joins"]["coverage"] == 0.8
        assert out["joins"]["unmeasured"] == 2
        assert out["joins"]["follow"]["coverage"] == 0.6
        assert out["engaged"]["coverage"] == 0.75
        assert out["n_sessions_measured"] == 1

    def test_surface_is_the_prefix_before_the_first_dash(self):
        src = {"following-live_cover": 5, "following-push": 3, "homepage_hot-x": 2}
        rows = [(_sess(), self._payload(src=src, jm=10, jt=10))]
        out = an.reduce_entry_source(rows)
        surfaces = {s["key"]: s["count"] for s in out["joins"]["surfaces"]}
        assert surfaces == {"following": 8, "homepage_hot": 2}

    def test_role_ratio_uses_its_own_measured_denominator(self):
        rows = [(_sess(), self._payload(roles={"sub": [3, 10], "mod": [0, 0], "gg": [1, 2]}))]
        out = an.reduce_entry_source(rows)
        assert out["engaged"]["roles"]["sub"] == {"count": 3, "measured": 10, "ratio": 0.3}
        assert out["engaged"]["roles"]["mod"]["ratio"] is None

    def test_session_with_nothing_measured_is_not_counted_as_measured(self):
        rows = [(_sess(), self._payload(jt=5, jm=0, jfm=0, et=0, em=0))]
        out = an.reduce_entry_source(rows)
        assert out["n_sessions"] == 1
        assert out["n_sessions_measured"] == 0

    def test_empty_rows_have_none_coverage(self):
        out = an.reduce_entry_source([])
        assert out["joins"]["coverage"] is None
        assert out["engaged"]["coverage"] is None
        assert out["follow_statuses"] == list(an.FOLLOW_STATUSES)


class TestReduceBattleFlow:
    def _rec(self, **kw):
        rec = {"bid": "b1", "ok": 1, "why": None, "form": "1v1", "dur": 300.0,
               "res": "win", "res_diff": 0, "lc": 2, "cp": "own", "cu": 0,
               "tail": [50, 100], "tail_adj": [50, 100],
               "bins": [10] * (an._BF_MAX_REMAINING // an._BF_BIN_SECONDS)}
        rec.update(kw)
        return rec

    def test_descriptive_stats_of_one_battle(self):
        rows = [(_sess(), {"battles": [self._rec()]})]
        out = an.reduce_battle_flow(rows)
        assert out["n_battles"] == 1
        assert out["n_eligible"] == 1
        assert out["forms"]["1v1"] == 1
        assert out["lead_changes"]["median"] == 2.0
        assert out["lead_changes"]["max"] == 2
        assert out["checkpoint"]["own"]["n"] == 1
        assert out["checkpoint"]["own"]["rate"] == 1.0
        # 残り1分でリードしていて勝ち → 逆転ではない
        assert out["checkpoint"]["comeback"] == {"n": 1, "k": 0, "rate": 0.0,
                                                 "ci": an._wilson_ci(0, 1)}
        # tail share 0.5 / uniform 0.2 = 2.5 → heavy
        assert out["tail"]["raw"]["heavy"] == 1
        assert out["tail"]["raw"]["median"] == 0.5
        assert out["bins"][0] == {"from": 0, "to": 30, "share": 0.1,
                                  "median_share": 0.1, "n": 1}

    def test_comeback_when_lead_flips(self):
        rows = [(_sess(), {"battles": [self._rec(cp="opp", res="win")]})]
        out = an.reduce_battle_flow(rows)
        assert out["checkpoint"]["comeback"]["k"] == 1
        assert out["checkpoint"]["opp"]["rate"] == 1.0

    def test_draw_is_excluded_from_comeback_but_counted_in_checkpoint(self):
        rows = [(_sess(), {"battles": [self._rec(res="draw")]})]
        out = an.reduce_battle_flow(rows)
        assert out["checkpoint"]["own"]["n"] == 1
        assert out["checkpoint"]["own"]["k"] == 0
        assert out["checkpoint"]["comeback"]["n"] == 0

    def test_exclusion_reasons_are_tallied(self):
        battles = [self._rec(bid="a", ok=0, why="chimera"),
                   self._rec(bid="b", ok=0, why="short"),
                   self._rec(bid="c", ok=0, why="mystery")]
        out = an.reduce_battle_flow([(_sess(), {"battles": battles})])
        assert out["n_battles"] == 3
        assert out["n_eligible"] == 0
        assert out["excluded"]["chimera"] == 1
        assert out["excluded"]["short"] == 1
        assert sum(out["excluded"].values()) == 2

    def test_battle_id_deduped_across_sessions(self):
        rec = self._rec()
        rows = [(_sess(1), {"battles": [rec]}), (_sess(2), {"battles": [rec]})]
        out = an.reduce_battle_flow(rows)
        assert out["n_battles"] == 1
        assert out["n_sessions"] == 2

    def test_unbounded_bins_are_not_counted_in_the_denominator(self):
        n_bins = an._BF_MAX_REMAINING // an._BF_BIN_SECONDS
        bins = [10] + [None] * (n_bins - 1)
        out = an.reduce_battle_flow([(_sess(), {"battles": [self._rec(bins=bins)]})])
        assert out["bins"][0]["n"] == 1
        assert out["bins"][1]["n"] == 0
        assert out["bins"][1]["share"] is None

    def test_lead_change_histogram_is_capped(self):
        battles = [self._rec(bid=f"b{i}", lc=lc)
                   for i, lc in enumerate([0, 3, 9, 20])]
        out = an.reduce_battle_flow([(_sess(), {"battles": battles})])
        hist = {h["changes"]: h["count"] for h in out["lead_changes"]["hist"]}
        assert hist == {0: 1, 3: 1, an._BF_LEAD_CHANGE_CAP: 2}
        capped = [h for h in out["lead_changes"]["hist"] if h["capped"]]
        assert len(capped) == 1

    def test_empty_rows(self):
        out = an.reduce_battle_flow([])
        assert out["n_battles"] == 0
        assert out["lead_changes"]["median"] is None
        assert out["tail"]["raw"]["n"] == 0


class TestReduceOrganic:
    def _payload(self, slots=None, tot=None, stick=(0, 0)):
        empty = [[0, 0.0, 0] for _ in range(an._DAY_SLOTS_15)]
        wd = [list(x) for x in empty]
        he = [list(x) for x in empty]
        for slot, (raw, organic, sw) in (slots or {}).items():
            wd[slot] = [raw, organic, sw]
        base = {"raw": 0, "organic": 0.0, "returning": 0, "engaged": 0,
                "leveled": 0, "share_window": 0}
        base.update(tot or {})
        return {"wd": wd, "he": he, "tot": base, "stick": list(stick)}

    def test_ratios_use_raw_joins_as_denominator(self):
        tot = {"raw": 100, "organic": 42.5, "returning": 20, "engaged": 30,
               "leveled": 5, "share_window": 10}
        rows = [(_sess(), self._payload(slots={4: (100, 42.5, 10)}, tot=tot,
                                        stick=(30, 60)))]
        out = an.reduce_organic(rows)
        assert out["returning_ratio"] == 0.2
        assert out["engaged_ratio"] == 0.3
        assert out["share_window_ratio"] == 0.1
        assert out["organic_ratio"] == 0.425
        assert out["stick_rate"] == 0.5
        assert out["weekday_raw"] == 100
        assert out["holiday_raw"] == 0
        assert out["weekday"][4] == {"slot": 4, "minute": 60, "raw": 100,
                                     "organic": 42.5, "share_window": 10}
        assert out["n_sessions"] == 1

    def test_no_joins_gives_zero_ratios_and_none_stick(self):
        out = an.reduce_organic([(_sess(), self._payload())])
        assert out["returning_ratio"] == 0.0
        assert out["organic_ratio"] == 0.0
        assert out["stick_rate"] is None

    def test_short_sessions_are_excluded(self):
        rows = [(_sess(started=0, ended=600),
                 self._payload(tot={"raw": 50, "returning": 50}))]
        out = an.reduce_organic(rows)
        assert out["n_sessions"] == 0
        assert out["totals"]["raw"] == 0

    def test_series_covers_all_slots(self):
        out = an.reduce_organic([])
        assert len(out["weekday"]) == an._DAY_SLOTS_15
        assert len(out["holiday"]) == an._DAY_SLOTS_15
        assert out["slot_minutes"] == 15


class TestReduceCoverage:
    def _payload(self, dur=1000.0, inst=1, delay=5.0, gaps=None, smp=None):
        return {"dur": dur, "inst": inst, "delay": delay, "gaps": gaps, "smp": smp}

    def test_gap_ratio_is_percent_of_session_duration(self):
        gaps = {"sec": 30.0, "n": 2, "unplanned": 1, "open_end": 0}
        rows = [(_sess(1), self._payload(gaps=gaps))]
        out = an.reduce_coverage(rows, [])
        assert out["gaps"]["n_sessions"] == 1
        assert out["gaps"]["seconds"]["median"] == 30.0
        assert out["gaps"]["ratio"]["median"] == 3.0
        assert out["gaps"]["count"] == 2
        assert out["gaps"]["unplanned"] == 1

    def test_uninstrumented_sessions_are_not_zero_but_absent(self):
        rows = [(_sess(1), self._payload(inst=0, delay=None, gaps=None))]
        out = an.reduce_coverage(rows, [])
        assert out["instrumented"] == {"measured": 0, "unmeasured": 1, "coverage": 0.0}
        assert out["gaps"]["n_sessions"] == 0
        assert out["gaps"]["seconds"]["median"] is None
        assert out["start_delay"]["n"] == 0

    def test_recording_ratio_sums_split_recordings_and_caps_at_one(self):
        rows = [(_sess(1), self._payload(dur=1000.0))]
        media = [
            {"session_id": 1, "started_at": 0.0, "ended_at": 400.0,
             "status": "completed", "has_transcript": 1},
            {"session_id": 1, "started_at": 500.0, "ended_at": 900.0,
             "status": "completed", "has_transcript": 0},
        ]
        out = an.reduce_coverage(rows, media)
        assert out["recording"]["n_sessions"] == 1
        assert out["recording"]["ratio"]["median"] == 80.0
        assert out["recording"]["full"] == 0
        assert out["transcript"] == {"recordings": 2, "transcribed": 1, "ratio": 0.5}

    def test_recording_ratio_clamped_to_one_on_clock_skew(self):
        rows = [(_sess(1), self._payload(dur=100.0))]
        media = [{"session_id": 1, "started_at": 0.0, "ended_at": 5000.0,
                  "status": "completed", "has_transcript": 1}]
        out = an.reduce_coverage(rows, media)
        assert out["recording"]["ratio"]["median"] == 100.0
        assert out["recording"]["full"] == 1

    def test_open_ended_recording_makes_the_session_unmeasurable(self):
        rows = [(_sess(1), self._payload(dur=1000.0))]
        media = [
            {"session_id": 1, "started_at": 0.0, "ended_at": 400.0,
             "status": "completed", "has_transcript": 0},
            {"session_id": 1, "started_at": 500.0, "ended_at": None,
             "status": "recording", "has_transcript": 0},
        ]
        out = an.reduce_coverage(rows, media)
        assert out["recording"]["n_sessions"] == 0
        assert out["recording"]["unmeasured_sessions"] == 1
        assert out["transcript"]["recordings"] == 1

    def test_session_without_any_recording_counts_as_zero_coverage(self):
        rows = [(_sess(1), self._payload(dur=1000.0))]
        out = an.reduce_coverage(rows, [])
        assert out["recording"]["n_sessions"] == 1
        assert out["recording"]["none"] == 1
        assert out["recording"]["ratio"]["median"] == 0.0

    def test_live_session_has_no_duration_and_is_not_ended(self):
        rows = [(_sess(1), self._payload(dur=None))]
        out = an.reduce_coverage(rows, [])
        assert out["n_sessions"] == 1
        assert out["n_sessions_ended"] == 0
        assert out["recording"]["n_sessions"] == 0

    def test_sampling_worst_is_the_max_across_sessions(self):
        rows = [
            (_sess(1), self._payload(smp={"n": 5, "median": 2.0, "p95": 4.0, "max": 9.0})),
            (_sess(2), self._payload(smp={"n": 5, "median": 4.0, "p95": 6.0, "max": 3.0})),
        ]
        out = an.reduce_coverage(rows, [])
        assert out["sampling"]["n_sessions"] == 2
        assert out["sampling"]["median"]["median"] == 3.0
        assert out["sampling"]["worst"] == 9.0

    def test_empty_rows(self):
        out = an.reduce_coverage([], [])
        assert out["n_sessions"] == 0
        assert out["instrumented"]["coverage"] is None
        assert out["transcript"]["ratio"] is None


class TestReduceRelations:
    def _rows(self, n=6):
        rows = []
        for i in range(n):
            p = {"joins": i + 1, "comments": (i + 1) * 2, "diamonds": (n - i),
                 "likes": i + 1, "follows": 1, "viewers": (i + 1) * 3, "n": 10}
            rows.append((_sess(i), p))
        return rows

    def test_diagonal_is_one_and_significant(self):
        out = an.reduce_relations(self._rows())
        for m in an.RELATION_METRICS:
            assert out["matrix"][m][m] == 1.0
            assert out["partial"][m][m] == 1.0
            assert out["sig"][m][m] is True

    def test_monotone_pair_is_perfectly_correlated(self):
        out = an.reduce_relations(self._rows())
        assert _approx(out["matrix"]["joins"]["comments"], 1.0)
        assert _approx(out["matrix"]["joins"]["diamonds"], -1.0)
        assert out["sig"]["joins"]["comments"] is True

    def test_partial_against_the_control_itself_is_none(self):
        out = an.reduce_relations(self._rows())
        for m in an.RELATION_METRICS:
            if m != "viewers":
                assert out["partial"]["viewers"][m] is None
                assert out["partial"][m]["viewers"] is None

    def test_sessions_without_buckets_are_dropped(self):
        rows = self._rows() + [(_sess(99), {m: 0 for m in an.RELATION_METRICS} | {"n": 0})]
        out = an.reduce_relations(rows)
        assert out["n_sessions"] == 6
        assert out["control"] == "viewers+duration"

    def test_matrix_is_symmetric(self):
        out = an.reduce_relations(self._rows())
        for a in an.RELATION_METRICS:
            for b in an.RELATION_METRICS:
                ra, rb = out["matrix"][a][b], out["matrix"][b][a]
                assert (ra is None and rb is None) or _approx(ra, rb, 1e-9)


class TestCacheVersionContract:
    def test_every_kind_has_a_payload_function_and_a_version(self):
        assert set(an.CACHE_VERSIONS) == set(an._PAYLOAD_FUNCS)
        assert set(an.KINDS) == set(an.CACHE_VERSIONS)
        assert all(isinstance(v, int) and v >= 1 for v in an.CACHE_VERSIONS.values())

    def test_index_metrics_map_onto_time_index_cell_positions(self):
        assert list(an._TI_CELL_POS) == list(an.INDEX_METRICS)
        assert min(an._TI_CELL_POS.values()) == 3
        assert set(an.INDEX_METRICS) <= set(an.RELATION_METRICS)

    def test_glove_coin_buckets_are_contiguous_and_ordered(self):
        for (_, hi), (lo, _) in zip(an.GLOVE_COIN_BUCKETS, an.GLOVE_COIN_BUCKETS[1:]):
            assert lo == hi + 1
        assert all(lo <= hi for lo, hi in an.GLOVE_COIN_BUCKETS)
