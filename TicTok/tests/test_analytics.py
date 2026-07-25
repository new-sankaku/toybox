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


def _dwell_samples(seconds=600.0, step=5.0, viewers=60, rate=0.5, start=0.0, total0=0):
    """定常な観測列。rate=1秒あたりの到着数で累積counterを伸ばす。"""
    out = []
    n = int(seconds / step) + 1
    for i in range(n):
        t = start + i * step
        level = viewers(i) if callable(viewers) else viewers
        out.append((t, level, total0 + int(round(rate * i * step))))
    return out


class TestDwellWindows:
    def test_stationary_window_recovers_little_law(self):
        # L=60人・λ=0.5人/秒 なら W = 60/0.5 = 120秒。
        windows, rejects = an._dwell_windows(_dwell_samples(), [])
        assert windows, rejects
        for _hour, level, arrivals, span, _cmts in windows:
            assert _approx(level * span / arrivals, 120.0, tol=1.0)

    def test_arrival_burst_is_rejected_as_unstable(self):
        # 1つの窓の中で、到着が1つの小binへ固まっている=λが定常ではない。
        samples = []
        for i in range(60):
            t = i * 5.0
            total = 0 if t < 120.0 else (60 if t >= 180.0 else int((t - 120.0)))
            samples.append((t, 60, total))
        windows, rejects = an._dwell_windows(samples, [])
        assert rejects["unstable"] >= 1
        assert not windows

    def test_level_drift_is_rejected(self):
        # 同接が窓内で倍以上動く=Lが代表値にならない。
        samples = _dwell_samples(viewers=lambda i: 20 + i)
        _windows, rejects = an._dwell_windows(samples, [])
        assert rejects["drift"] >= 1

    def test_counter_rollback_is_rejected_not_treated_as_arrivals(self):
        samples = [(i * 5.0, 60, 500 if i < 30 else 10) for i in range(70)]
        _windows, rejects = an._dwell_windows(samples, [])
        assert rejects["reset"] >= 1

    def test_too_few_arrivals_is_rejected(self):
        samples = [(i * 5.0, 60, i // 60) for i in range(121)]
        windows, rejects = an._dwell_windows(samples, [])
        assert not windows
        assert rejects["noarr"] >= 1

    def test_large_sampling_gap_is_rejected(self):
        # 観測が150秒途切れた窓。窓の長さ自体は足りているので「短い」ではなく穴で落ちる。
        samples = [(i * 5.0, 60, i) for i in range(21)]
        samples += [(250.0, 60, 60), (260.0, 60, 62), (270.0, 60, 64)]
        _windows, rejects = an._dwell_windows(samples, [])
        assert rejects["gap"] >= 1
        assert rejects["short"] == 0

    def test_level_is_time_weighted_not_sample_weighted(self):
        # 同接20の帯は密に、同接80の帯は疎にsamplingした列。どちらの帯も実時間は
        # 等しいので時間加重平均は50付近になる。sample数で平均すると密な20側へ
        # 大きく寄る(約29)ため、両者は明確に区別できる。
        samples = []
        for block in range(10):
            level = 20 if block % 2 == 0 else 80
            base = block * 30.0
            times = [base + k * 5.0 for k in range(6)] if level == 20 else [base]
            for t in times:
                samples.append((t, level, int(t * 0.2)))
        samples.append((299.0, 20, int(299.0 * 0.2)))
        windows, rejects = an._dwell_windows(samples, [])
        assert windows, rejects
        assert 45.0 < windows[0][1] < 55.0

    def test_comments_are_counted_inside_the_window(self):
        samples = _dwell_samples(seconds=300.0)
        comments = [10.0, 20.0, 30.0, 9000.0]
        windows, _rejects = an._dwell_windows(samples, comments)
        assert windows
        assert windows[0][4] == 3


class TestReduceDwell:
    def _payload(self, dwell=120.0, n=6, comments=0, arr=1000, vmin=2000.0, avgv=60.0):
        # arrivals=span*level/dwell となるよう窓を作る。
        span, level = 300.0, 60.0
        arrivals = int(round(span * level / dwell))
        return {
            "w": [[12, level, arrivals, span, comments] for _ in range(n)],
            "rej": [0] * len(an._DW_REJECT_KEYS),
            "vmin": vmin, "arr": arr, "jn": int(arr * 0.8), "avgv": avgv,
        }

    def test_dwell_and_turnover_are_reciprocal(self):
        rows = [(_sess(i, "a"), self._payload()) for i in range(1, 5)]
        out = an.reduce_dwell(rows)
        assert _approx(out["overall"]["dwell_seconds"], 120.0, tol=0.5)
        assert _approx(out["overall"]["turnover_per_hour"], 30.0, tol=0.5)

    def test_sessions_with_too_few_windows_are_not_estimated(self):
        rows = [(_sess(1, "a"), self._payload(n=an._DW_MIN_SESSION_WINDOWS - 1))]
        out = an.reduce_dwell(rows)
        assert out["n_estimated"] == 0
        assert out["overall"] is None

    def test_rejected_windows_are_reported_not_filled(self):
        payload = self._payload()
        payload["rej"] = [1] * len(an._DW_REJECT_KEYS)
        out = an.reduce_dwell([(_sess(1, "a"), payload)])
        assert sum(out["rejects"].values()) == len(an._DW_REJECT_KEYS)
        assert out["candidates"] == out["windows"] + len(an._DW_REJECT_KEYS)

    def test_streamer_needs_multiple_sessions(self):
        rows = [(_sess(1, "solo"), self._payload())]
        assert an.reduce_dwell(rows)["streamers"] == []

    def test_cross_check_ratio_is_a_per_session_median(self):
        # 合計比は大きい配信1本に支配されるため、配信ごとに取った比の中央値であること。
        rows = [
            (_sess(1, "a"), self._payload(arr=10) | {"jn": 8}),
            (_sess(2, "a"), self._payload(arr=10) | {"jn": 8}),
            (_sess(3, "a"), self._payload(arr=10000) | {"jn": 2000}),
        ]
        out = an.reduce_dwell(rows)
        assert _approx(out["cross_check"]["ratio"], 0.8, tol=1e-6)
        assert out["cross_check"]["n"] == 3

    def test_mix_splits_windows_against_the_streamer_own_median(self):
        # 短い滞在の窓と長い滞在の窓を半々で持たせると、churn/stickyの両方が立つ。
        fast = [[12, 60.0, 300, 300.0, 0]] * 4    # W=60秒
        slow = [[12, 60.0, 60, 300.0, 0]] * 4     # W=300秒
        payload = self._payload()
        payload["w"] = fast + slow
        rows = [(_sess(i, "a"), payload) for i in (1, 2)]
        mix = an.reduce_dwell(rows)["streamers"][0]["mix"]
        assert mix["churn"] > 0.4 and mix["sticky"] > 0.4
        assert _approx(mix["churn"] + mix["sticky"] + mix["steady"], 1.0, tol=1e-6)

    def test_empty_rows_report_nothing_rather_than_zero(self):
        out = an.reduce_dwell([])
        assert out["overall"] is None
        assert out["crude_dwell_seconds"] is None
        assert out["cross_check"]["ratio"] is None
        assert out["streamers"] == [] and out["hours"] == []


class TestRobustStats:
    def test_mad_ignores_a_single_extreme(self):
        # 1本だけ桁違いでも尺度が壊れないこと(標準偏差ならここで跳ね上がる)。
        assert an._mad([1, 2, 3, 4, 5]) == 1.0
        assert an._mad([1, 2, 3, 4, 100000]) == 1.0

    def test_robust_z_scales_like_a_standard_deviation(self):
        # 正規標本ではMAD*1.4826 ≈ σ。1σぶん離れた点のzは概ね1になる。
        baseline = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
        z = an._robust_z(_median_plus(baseline, 1.4826 * an._mad(baseline)), baseline)
        assert 0.9 < z < 1.1

    def test_robust_z_is_none_when_scale_is_undefined(self):
        # MAD=0で微小な差を無限大のzにしない。
        assert an._robust_z(5.0, [3, 3, 3, 3, 3]) is None
        assert an._robust_z(5.0, [3]) is None

    def test_empirical_p_floor_is_bounded_by_baseline_size(self):
        baseline = list(range(20))
        p = an._empirical_p(9999.0, baseline)
        assert _approx(p, 1 / (len(baseline) + 1))

    def test_empirical_p_is_two_sided(self):
        baseline = [10] * 5 + [0, 20]
        assert _approx(an._empirical_p(0.0, baseline), an._empirical_p(20.0, baseline))

    def test_empirical_p_of_a_typical_value_is_large(self):
        assert an._empirical_p(10.0, list(range(0, 21))) > 0.9


class TestBenjaminiHochberg:
    def test_preserves_input_order(self):
        q = an.benjamini_hochberg([0.5, 0.01, 0.2])
        assert len(q) == 3
        assert q[1] < q[0] and q[1] < q[2]

    def test_is_monotone_in_rank(self):
        ps = [0.001, 0.008, 0.02, 0.3, 0.9]
        q = an.benjamini_hochberg(ps)
        assert q == sorted(q)

    def test_never_exceeds_one(self):
        assert all(v <= 1.0 for v in an.benjamini_hochberg([0.9, 0.95, 0.99]))

    def test_single_test_leaves_p_unchanged(self):
        assert _approx(an.benjamini_hochberg([0.03])[0], 0.03)

    def test_empty(self):
        assert an.benjamini_hochberg([]) == []


class TestChangepointStatistic:
    def test_finds_the_split_of_a_clear_step(self):
        values = [1] * 20 + [9] * 20
        _stat, at = an._rank_cusum(an._rank_average(values), 4)
        assert at == 20

    def test_refuses_splits_inside_the_minimum_segment(self):
        # 端に段があっても最小segment長を割る位置は返さない。
        values = [1] + [9] * 19
        _stat, at = an._rank_cusum(an._rank_average(values), 5)
        assert at is None or 5 <= at <= 15

    def test_too_short_series_has_no_split(self):
        assert an._rank_cusum([1.0, 2.0, 3.0], 4) == (0.0, None)

    def test_flat_series_yields_no_signal(self):
        stat, _at = an._rank_cusum(an._rank_average([5] * 30), 4)
        assert _approx(stat, 0.0, tol=1e-9)

    def test_block_shuffle_preserves_length_and_multiset(self):
        import random as _random
        seq = list(range(20))
        out = an._block_shuffled(seq, 4, _random.Random(1))
        assert len(out) == len(seq)
        assert set(out) <= set(seq)


def _median_plus(values, delta):
    return an._median(values) + delta


class TestReduceAnomaly:
    def _payload(self, metrics=None, cp=None, span=3600.0, ev=500):
        return {"m": metrics if metrics is not None else {}, "span": span,
                "ev": ev, "cp": cp}

    def _rows(self, n=15, uid="a", value=10.0, spike_value=None):
        rows = []
        for i in range(n):
            v = value if (spike_value is None or i < n - 1) else spike_value
            # baselineに幅を持たせる(MAD=0だと尺度が定義できず判定不能になる)。
            v = v + (i % 3) - 1
            rows.append((_sess(i + 1, uid, started=1000.0 + i),
                         self._payload({"coins_per_min": v})))
        return rows

    def test_streamer_without_enough_history_is_not_judged(self):
        rows = self._rows(n=an._AN_MIN_BASELINE)
        out = an.reduce_anomaly(rows)
        assert out["findings"] == []
        short = [c for c in out["coverage"] if c["status"] == "insufficient"]
        assert short and short[0]["unique_id"] == "a"

    def test_baseline_excludes_the_session_under_test(self):
        rows = self._rows(n=16, value=10.0, spike_value=1000.0)
        out = an.reduce_anomaly(rows)
        top = out["findings"][0]
        # 自分をbaselineへ混ぜていれば中央値が跳ね上がり、この逸脱は出ない。
        assert top["session_id"] == 16
        assert top["typical"] < 20
        assert top["z"] > 10
        assert top["baseline"] == 15

    def test_reports_the_normal_range_alongside_the_deviation(self):
        out = an.reduce_anomaly(self._rows(n=16, spike_value=1000.0))
        top = out["findings"][0]
        assert top["p25"] <= top["typical"] <= top["p75"]
        assert top["label"]

    def test_significance_uses_bh_not_raw_p(self):
        out = an.reduce_anomaly(self._rows(n=16, spike_value=1000.0))
        top = out["findings"][0]
        assert top["q"] >= top["p"]
        assert top["significant"] == (top["q"] < out["fdr_q"])

    def test_power_reports_the_detection_floor(self):
        out = an.reduce_anomaly(self._rows(n=16, spike_value=1000.0))
        power = out["power"]
        assert power["tests"] == len(out["findings"])
        assert _approx(power["best_p"], 1 / 16, tol=1e-3)
        assert power["reachable"] is (power["best_p"] <= power["needed_p"])

    def test_sessions_without_measurable_metrics_are_counted_separately(self):
        rows = self._rows(n=16) + [(_sess(99, "a"), self._payload({}))]
        out = an.reduce_anomaly(rows)
        assert out["n_sessions"] == 17
        assert out["n_measured"] == 16

    def test_changepoint_shift_needs_both_significance_and_magnitude(self):
        big = {"at": 500.0, "before": 40.0, "after": 8.0, "p": 0.005, "bins": 30}
        tiny = {"at": 500.0, "before": 10.0, "after": 9.8, "p": 0.005, "bins": 30}
        noisy = {"at": 500.0, "before": 40.0, "after": 8.0, "p": 0.9, "bins": 30}
        rows = [
            (_sess(1, "a"), self._payload(cp=big)),
            (_sess(2, "a"), self._payload(cp=tiny)),
            (_sess(3, "a"), self._payload(cp=noisy)),
        ]
        shifts = an.reduce_anomaly(rows)["changepoints"]["shifts"]
        assert [s["session_id"] for s in shifts] == [1]

    def test_empty_rows_do_not_fabricate_results(self):
        out = an.reduce_anomaly([])
        assert out["findings"] == [] and out["n_significant"] == 0
        assert out["power"] is None
        assert out["changepoints"]["shifts"] == []


class TestObservedSpan:
    """稼働秒をbucketsから切り離した移行の回帰test。bucketsが無くても測れること。"""

    def _conn(self, tmp_db_path, events=(), viewers=()):
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            "CREATE TABLE events (session_id INT, time REAL, kind TEXT, diamonds INT);"
            "CREATE TABLE viewer_samples (session_id INT, time REAL, viewers INT);"
        )
        conn.executemany("INSERT INTO events VALUES (?,?,?,?)", events)
        conn.executemany("INSERT INTO viewer_samples VALUES (?,?,?)", viewers)
        return conn

    def test_ended_session_uses_ended_at(self):
        conn = self._conn(None, events=[(1, 1500.0, "join", 0)])
        assert an._observed_span(conn, _sess(1, ended=5000.0)) == 4000.0

    def test_live_session_falls_back_to_the_last_observation(self):
        # 収集中はended_atが無い。bucketsに頼らず、最後に届いたeventで終端を決める。
        conn = self._conn(None, events=[(1, 1500.0, "join", 0), (1, 3400.0, "comment", 0)])
        sess = _sess(1)
        sess["ended_at"] = None
        assert an._observed_span(conn, sess) == 2400.0

    def test_live_session_considers_viewer_samples_too(self):
        conn = self._conn(None, events=[(1, 1500.0, "join", 0)],
                          viewers=[(1, 4000.0, 10)])
        sess = _sess(1)
        sess["ended_at"] = None
        assert an._observed_span(conn, sess) == 3000.0

    def test_session_without_any_observation_is_zero_not_negative(self):
        conn = self._conn(None)
        sess = _sess(1)
        sess["ended_at"] = None
        assert an._observed_span(conn, sess) == 0.0

    def test_summary_counts_events_not_buckets(self):
        # bucketsを1行も持たない配信でも集計できること(切断で終わった配信が該当)。
        conn = self._conn(None, events=[
            (1, 1100.0, "join", 0), (1, 1200.0, "join", 0),
            (1, 1300.0, "comment", 0), (1, 1400.0, "gift", 50),
        ])
        out = an._payload_summary(conn, _sess(1, ended=4000.0))
        assert out["j"] == 2
        assert out["c"] == 1
        assert out["d"] == 50
        assert out["act"] == 3000.0
        assert out["nb"] == 50  # 3000秒 / bucket 60秒


class TestLifeTable:
    def _table(self, pairs):
        """(events, censored) の並びを bin 数へ合わせて詰める。"""
        n = len(an._AC_BIN_EDGES) + 1
        out = [[0, 0] for _ in range(n)]
        for i, (ev, cs) in enumerate(pairs):
            out[i] = [ev, cs]
        return out

    def test_no_censoring_matches_the_plain_ratio(self):
        # 母数はtable自身の合計(反応+打ち切り)。100人中、最初のbinで25人・次で25人が
        # 反応し、残り50人は最後まで観測できた場合。
        curve = an._life_table_curve(self._table([(25, 0), (25, 0), (0, 50)]))
        assert _approx(curve[0], 0.25, tol=1e-9)
        assert _approx(curve[1], 0.5, tol=1e-9)

    def test_censored_people_are_not_counted_as_non_responders(self):
        # どちらも100人・2番目のbinで25人が反応。違いは最初のbinで50人が配信終了で
        # 抜けたかどうか。抜けた人を「反応しなかった」と数えないぶん、率は高く出る。
        censored = an._life_table_curve(self._table([(0, 50), (25, 0), (0, 25)]))
        plain = an._life_table_curve(self._table([(0, 0), (25, 0), (0, 75)]))
        assert _approx(censored[1], 0.5, tol=1e-9)
        assert _approx(plain[1], 0.25, tol=1e-9)
        assert censored[1] > plain[1]

    def test_curve_is_monotone_non_decreasing(self):
        curve = an._life_table_curve(self._table([(5, 3), (4, 10), (2, 40), (1, 5)]))
        assert all(b >= a - 1e-12 for a, b in zip(curve, curve[1:]))

    def test_empty_table_is_none_not_zero(self):
        assert an._life_table_curve(self._table([])) is None

    def test_everyone_responding_reaches_one(self):
        curve = an._life_table_curve(self._table([(10, 0)]))
        assert _approx(curve[0], 1.0, tol=1e-9)

    def test_median_latency_is_over_responders_only(self):
        # 9割が反応しない状況でも、反応した人の中央値は求まる。
        table = self._table([(10, 0), (10, 900)])
        median = an._ac_median_latency(table)
        assert median is not None
        assert an._AC_BIN_EDGES[0] <= median <= an._AC_BIN_EDGES[1]

    def test_median_latency_none_without_responders(self):
        assert an._ac_median_latency(self._table([(0, 50)])) is None

    def test_bin_index_places_values_in_order(self):
        assert an._ac_bin_index(0) == 0
        assert an._ac_bin_index(an._AC_BIN_EDGES[0] - 0.001) == 0
        assert an._ac_bin_index(an._AC_BIN_EDGES[0]) == 1
        assert an._ac_bin_index(10 ** 9) == len(an._AC_BIN_EDGES)


class TestReduceActivation:
    def _payload(self, n=100, responded=10, at_bin=0, censored_bin=None, **extra):
        size = len(an._AC_BIN_EDGES) + 1
        wl = [[0, 0] for _ in range(size)]
        nl = [[0, 0] for _ in range(size)]
        wl[at_bin][0] = responded
        nl[at_bin][0] = responded // 2
        rest_wl = n - responded
        rest_nl = n - responded // 2
        idx = size - 1 if censored_bin is None else censored_bin
        wl[idx][1] = rest_wl
        nl[idx][1] = rest_nl
        base = {"n": n, "wl": wl, "nl": nl,
                "act": responded, "act_j": responded, "gift": 0, "gift_j": 0}
        base.update(extra)
        return base

    def _rows(self, count=5, **kw):
        return [(_sess(i + 1, "a", started=1000.0 + i), self._payload(**kw))
                for i in range(count)]

    def test_both_series_are_returned(self):
        out = an.reduce_activation(self._rows())
        assert set(out["series"]) == {"wl", "nl"}
        assert out["series"]["wl"]["activated"] > out["series"]["nl"]["activated"]

    def test_person_counts_accumulate_across_sessions(self):
        out = an.reduce_activation(self._rows(count=4, n=50))
        assert out["n_persons"] == 200
        assert out["n_sessions"] == 4

    def test_horizons_are_non_decreasing(self):
        out = an.reduce_activation(self._rows())
        values = [h["activated"] for h in out["series"]["wl"]["horizons"]]
        assert all(b >= a for a, b in zip(values, values[1:]))

    def test_ci_needs_enough_session_clusters(self):
        few = an.reduce_activation(self._rows(count=an._AC_MIN_SESSIONS - 1))
        assert all(h["ci"] is None for h in few["series"]["wl"]["horizons"])
        many = an.reduce_activation(self._rows(count=6))
        assert any(h["ci"] is not None for h in many["series"]["wl"]["horizons"])

    def test_ci_brackets_the_point_estimate(self):
        out = an.reduce_activation(self._rows(count=8))
        for h in out["series"]["wl"]["horizons"]:
            if h["ci"] is not None and h["activated"] is not None:
                assert h["ci"][0] <= h["activated"] + 1e-6
                assert h["activated"] <= h["ci"][1] + 1e-6

    def test_ci_is_deterministic_across_calls(self):
        # 同じdataで画面の値が呼ぶたび揺れないこと。
        a = an.reduce_activation(self._rows(count=6))
        b = an.reduce_activation(self._rows(count=6))
        assert a["series"]["wl"]["horizons"] == b["series"]["wl"]["horizons"]

    def test_coverage_reports_the_missing_join_population(self):
        rows = self._rows(count=3)
        rows = [(s, dict(p, act=100, act_j=60, gift=40, gift_j=10)) for s, p in rows]
        cov = an.reduce_activation(rows)["coverage"]
        assert cov["actors"] == 300 and cov["actors_with_join"] == 180
        assert _approx(cov["ratio"], 0.6, tol=1e-9)
        assert cov["missing"] == 120
        # ギフト送信者のほうが取りこぼしが多いことが数値で出ること。
        assert cov["gifter_ratio"] < cov["ratio"]

    def test_sessions_without_joins_are_skipped(self):
        rows = self._rows(count=2) + [(_sess(9, "a"), {"n": 0, "wl": [], "nl": [],
                                                       "act": 0, "act_j": 0,
                                                       "gift": 0, "gift_j": 0})]
        out = an.reduce_activation(rows)
        assert out["n_sessions"] == 2

    def test_empty_rows_do_not_fabricate(self):
        out = an.reduce_activation([])
        assert out["n_persons"] == 0
        assert out["coverage"] is None
        assert out["series"]["wl"]["curve"] is None
        assert out["series"]["wl"]["median_latency"] is None


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
