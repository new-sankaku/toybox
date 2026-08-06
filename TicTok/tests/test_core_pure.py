import json

import pytest

from tictok.core import cancel as cancel_mod
from tictok.core.battle import (
    BATTLE_RESULT_REPORTED,
    BATTLE_RESULT_SETTLED,
    BATTLE_SETTLE_GRACE_SECONDS,
    annotate_result,
    battle_sides,
    battle_type,
    resolve_result,
    result_from_scores,
    settled_scores,
)
from tictok.core.cancel import (
    CancelToken,
    JobCancelled,
    check_cancelled,
    current_token,
    forget_process,
    is_cancelled,
    register_process,
    token_scope,
)
from tictok.core.jsonio import JS_MAX_SAFE_INTEGER, JsSafeJSONResponse, js_safe
from tictok.core.spike import MIN_BUCKETS, detect_spikes, window_bucket_count


# ---------------------------------------------------------------- battle_type


def _p(user_id, team_id=None, score=0, own=False):
    p = {"user_id": user_id, "score": score}
    if team_id is not None:
        p["team_id"] = team_id
    if own:
        p["is_own"] = True
    return p


def test_battle_type_flat_1v1_without_team_ids_is_personal():
    assert battle_type([_p("1", own=True), _p("2")]) == "personal"


def test_battle_type_personal_multi_is_personal_despite_team_structure():
    # 個人マルチ: team_id にその host 自身の user_id が入る。
    parts = [_p("11", team_id="11", own=True), _p("22", team_id="22"), _p("33", team_id="33")]
    assert battle_type(parts) == "personal"


def test_battle_type_placeholder_team_ids_is_team():
    parts = [_p("11", team_id="1", own=True), _p("22", team_id="1"),
             _p("33", team_id="2"), _p("44", team_id="2")]
    assert battle_type(parts) == "team"


def test_battle_type_compares_team_id_and_user_id_as_strings():
    # int の team_id と str の user_id が混ざっても個人マルチと判定されること。
    assert battle_type([_p("11", team_id=11), _p("22", team_id=22)]) == "personal"


def test_battle_type_single_placeholder_makes_the_whole_battle_team():
    parts = [_p("11", team_id="11", own=True), _p("22", team_id="1")]
    assert battle_type(parts) == "team"


def test_battle_type_missing_user_id_with_team_id_is_team():
    assert battle_type([{"team_id": "1", "user_id": None}]) == "team"


def test_battle_type_untagged_participants_do_not_break_personal_detection():
    # team_id を持たない参加者は判定母集団から外れる(roster が埋まる途中)。
    parts = [_p("11", team_id="11", own=True), _p("22")]
    assert battle_type(parts) == "personal"


# --------------------------------------------------------------- battle_sides


def test_battle_sides_personal_multi_splits_per_participant_own_first():
    parts = [_p("22", team_id="22", score=300), _p("11", team_id="11", score=100, own=True),
             _p("33", team_id="33", score=200)]
    assert battle_sides(parts) == [(("11",), True), (("22",), False), (("33",), False)]


def test_battle_sides_team_battle_groups_by_team_id():
    parts = [_p("11", team_id="1", score=50, own=True), _p("22", team_id="1", score=10),
             _p("33", team_id="2", score=500), _p("44", team_id="2", score=5)]
    assert battle_sides(parts) == [(("11", "22"), True), (("33", "44"), False)]


def test_battle_sides_orders_opponents_by_best_member_score_descending():
    parts = [_p("11", score=0, own=True), _p("22", score=10), _p("33", score=999)]
    assert [ids for ids, _ in battle_sides(parts)] == [("11",), ("33",), ("22",)]


def test_battle_sides_accepts_side_own_marker():
    parts = [{"user_id": "11", "score": 1, "side": "own"}, _p("22", score=5)]
    assert battle_sides(parts)[0] == (("11",), True)


def test_battle_sides_skips_participants_without_user_id():
    parts = [_p("11", own=True), {"user_id": None, "score": 9}, {"score": 3}]
    assert battle_sides(parts) == [(("11",), True)]


def test_battle_sides_legacy_missing_team_id_falls_back_to_side():
    # team 戦と判定された上で team_id が欠けた legacy 行は own/opp へ寄せる。
    parts = [{"user_id": "11", "score": 5, "is_own": True},
             _p("22", team_id="2", score=50), _p("33", team_id="2", score=1)]
    assert battle_sides(parts) == [(("11",), True), (("22", "33"), False)]


# --------------------------------------------------------- result_from_scores


@pytest.mark.parametrize("own,opp,expected", [
    (10, 5, "win"), (5, 10, "lose"), (7, 7, "draw"), (0, 0, "draw"), (1, 0, "win"),
])
def test_result_from_scores(own, opp, expected):
    assert result_from_scores(own, opp) == expected


# ------------------------------------------------------------- settled_scores


def test_settled_scores_none_without_end_time():
    assert settled_scores({"score_series": [{"t": 1, "own": 1, "opp": 2}]}) is None


def test_settled_scores_ignores_post_battle_roster_teardown():
    battle = {"end_time": 100.0, "score_series": [
        {"t": 95.0, "own": 10, "opp": 5},
        {"t": 102.0, "own": 20, "opp": 30},
        {"t": 140.0, "own": 0, "opp": 0},
    ]}
    assert settled_scores(battle) == (20, 30, 102.0)


def test_settled_scores_grace_boundary_is_inclusive():
    at = 100.0 + BATTLE_SETTLE_GRACE_SECONDS
    battle = {"end_time": 100.0, "score_series": [{"t": 50.0, "own": 1, "opp": 1},
                                                  {"t": at, "own": 9, "opp": 8}]}
    assert settled_scores(battle) == (9, 8, at)


def test_settled_scores_excludes_sample_just_past_the_grace():
    at = 100.0 + BATTLE_SETTLE_GRACE_SECONDS + 0.001
    battle = {"end_time": 100.0, "score_series": [{"t": 50.0, "own": 1, "opp": 1},
                                                  {"t": at, "own": 9, "opp": 8}]}
    assert settled_scores(battle) == (1, 1, 50.0)


def test_settled_scores_none_when_every_sample_is_past_the_cutoff():
    battle = {"end_time": 100.0, "score_series": [{"t": 200.0, "own": 9, "opp": 8}]}
    assert settled_scores(battle) is None


def test_settled_scores_none_for_empty_series():
    assert settled_scores({"end_time": 100.0, "score_series": []}) is None


def test_settled_scores_skips_samples_without_timestamp():
    battle = {"end_time": 100.0, "score_series": [{"t": 90.0, "own": 3, "opp": 4},
                                                  {"t": None, "own": 99, "opp": 99}]}
    assert settled_scores(battle) == (3, 4, 90.0)


def test_settled_scores_treats_missing_scores_as_zero():
    battle = {"end_time": 100.0, "score_series": [{"t": 90.0}]}
    assert settled_scores(battle) == (0, 0, 90.0)


# ------------------------------------------------------------- resolve_result


def test_resolve_result_settled_overrides_reported_flip():
    battle = {"result": "win", "end_time": 100.0, "score_series": [
        {"t": 99.0, "own": 100, "opp": 250},
        {"t": 200.0, "own": 0, "opp": 0},
    ]}
    resolved = resolve_result(battle)
    assert resolved["result"] == "lose"
    assert resolved["basis"] == BATTLE_RESULT_SETTLED
    assert resolved["reason"] is None
    assert (resolved["own"], resolved["opp"], resolved["at"]) == (100, 250, 99.0)
    assert resolved["reported"] == "win"


def test_resolve_result_aborted_is_not_rejudged():
    resolved = resolve_result({"result": "win", "aborted": 1, "end_time": 100.0,
                               "score_series": [{"t": 99.0, "own": 1, "opp": 9}]})
    assert resolved["basis"] == BATTLE_RESULT_REPORTED
    assert resolved["reason"] == "aborted"
    assert resolved["result"] == "win"
    assert resolved["own"] is None and resolved["opp"] is None


def test_resolve_result_ongoing_when_end_time_missing():
    resolved = resolve_result({"result": None, "score_series": [{"t": 1.0, "own": 1, "opp": 2}]})
    assert resolved["basis"] == BATTLE_RESULT_REPORTED
    assert resolved["reason"] == "ongoing"


def test_resolve_result_no_series_when_ended_without_usable_samples():
    resolved = resolve_result({"result": "draw", "end_time": 100.0, "score_series": []})
    assert resolved["reason"] == "no_series"
    assert resolved["result"] == "draw"


# ------------------------------------------------------------ annotate_result


def test_annotate_result_rewrites_both_result_and_scores():
    battle = {"result": "win", "own_score": 0, "opp_score": 0, "end_time": 100.0,
              "score_series": [{"t": 99.0, "own": 100, "opp": 250}, {"t": 300.0, "own": 0, "opp": 0}]}
    annotate_result(battle)
    assert battle["result"] == "lose"
    assert (battle["own_score"], battle["opp_score"]) == (100, 250)
    assert battle["result_reported"] == "win"
    assert (battle["own_score_reported"], battle["opp_score_reported"]) == (0, 0)
    assert battle["result_basis"] == BATTLE_RESULT_SETTLED


def test_annotate_result_returns_the_same_object():
    battle = {"result": "win", "end_time": None}
    assert annotate_result(battle) is battle


def test_annotate_result_is_idempotent_and_keeps_the_original_data():
    battle = {"result": "win", "own_score": 0, "opp_score": 0, "end_time": 100.0,
              "score_series": [{"t": 99.0, "own": 100, "opp": 250}]}
    annotate_result(battle)
    annotate_result(battle)
    assert battle["own_score_reported"] == 0
    assert battle["result_reported"] == "win"
    assert battle["own_score"] == 100


def test_annotate_result_leaves_scores_alone_when_not_settled():
    battle = {"result": "win", "own_score": 5, "opp_score": 7, "aborted": 1}
    annotate_result(battle)
    assert (battle["own_score"], battle["opp_score"]) == (5, 7)
    assert battle["result"] == "win"
    assert battle["result_basis"] == BATTLE_RESULT_REPORTED
    assert battle["result_reason"] == "aborted"


# -------------------------------------------------------- window_bucket_count


@pytest.mark.parametrize("bucket_seconds,window_seconds,expected", [
    (10, 60, 6),
    (10, 5, 1),      # 0.5 bucket でも窓は消えない
    (10, 0, 1),
    (10, 1, 1),
    (60, 3600, 60),
    (2.5, 10, 4),
])
def test_window_bucket_count(bucket_seconds, window_seconds, expected):
    assert window_bucket_count(bucket_seconds, window_seconds) == expected


@pytest.mark.parametrize("bad", [0, -1, -0.5])
def test_window_bucket_count_rejects_non_positive_bucket(bad):
    with pytest.raises(ValueError):
        window_bucket_count(bad, 60)


def test_window_bucket_count_uses_bankers_rounding_on_exact_halves():
    # round() の偶数丸め。15s/10s は 2 だが 25s/10s も 2 になる(3 ではない)。
    assert window_bucket_count(10, 15) == 2
    assert window_bucket_count(10, 25) == 2


# --------------------------------------------------------------- detect_spikes


def _buckets(diamonds, comments=None, start=1000.0, step=10.0, extra=None):
    comments = comments if comments is not None else [0] * len(diamonds)
    out = []
    for i, d in enumerate(diamonds):
        b = {"start": start + i * step, "diamonds": d, "comments": comments[i]}
        if extra:
            for key, values in extra.items():
                if values[i] is not None:
                    b[key] = values[i]
        out.append(b)
    return out


def test_detect_spikes_finds_the_single_outlier_with_exact_z_and_ratio():
    # [0]*9 + [10] → mean=1, std=3, z=3.0 ちょうど。
    spikes = detect_spikes(_buckets([0] * 9 + [10]), zscore_min=3.0)
    assert len(spikes) == 1
    spike = spikes[0]
    assert spike["index"] == 9
    assert spike["start"] == 1000.0 + 9 * 10.0
    assert spike["metric"] == "diamonds"
    assert spike["zscore"] == pytest.approx(3.0)
    assert spike["baseline"] == pytest.approx(1.0)
    assert spike["ratio"] == pytest.approx(10.0)


def test_detect_spikes_threshold_is_inclusive_at_the_boundary():
    buckets = _buckets([0] * 9 + [10])
    assert len(detect_spikes(buckets, zscore_min=3.0)) == 1
    assert detect_spikes(buckets, zscore_min=3.0001) == []


def test_detect_spikes_drops_metrics_with_zero_variance_but_keeps_their_values():
    spikes = detect_spikes(_buckets([0] * 9 + [10]), metrics=("diamonds", "comments"),
                           zscore_min=3.0)
    assert list(spikes[0]["zscores"]) == ["diamonds"]
    assert spikes[0]["values"]["comments"] == 0.0


def test_detect_spikes_returns_empty_when_every_requested_metric_is_flat():
    assert detect_spikes(_buckets([5] * 10), metrics=("diamonds",), zscore_min=0.0) == []


def test_detect_spikes_needs_at_least_min_buckets():
    assert detect_spikes(_buckets([0] * (MIN_BUCKETS - 1) + [10])[:MIN_BUCKETS - 1],
                         zscore_min=0.5) == []
    assert len(detect_spikes(_buckets([0] * (MIN_BUCKETS - 1) + [10]), zscore_min=0.5)) >= 1


def test_detect_spikes_rolling_window_sums_and_drops_the_trailing_partial_window():
    # 6 bucket / 窓2 → 系列長5, mean=2, std=4, 最後の窓の z=2.0。
    spikes = detect_spikes(_buckets([0, 0, 0, 0, 0, 10]), window_buckets=2, zscore_min=2.0)
    assert len(spikes) == 1
    assert spikes[0]["index"] == 4
    assert spikes[0]["start"] == 1000.0 + 4 * 10.0
    assert spikes[0]["values"]["diamonds"] == pytest.approx(10.0)
    assert spikes[0]["zscore"] == pytest.approx(2.0)


def test_detect_spikes_returns_empty_when_window_is_longer_than_the_series():
    assert detect_spikes(_buckets([1, 2, 3]), window_buckets=5, zscore_min=0.0) == []


@pytest.mark.parametrize("bad", [0, -1])
def test_detect_spikes_rejects_non_positive_window(bad):
    with pytest.raises(ValueError):
        detect_spikes(_buckets([1] * 10), window_buckets=bad)


def test_detect_spikes_rejects_unknown_metric():
    with pytest.raises(ValueError, match="未知の指標"):
        detect_spikes(_buckets([1] * 10), metrics=("joins",), zscore_min=1.0)


def test_detect_spikes_rejects_audio_peak_when_any_bucket_lacks_it():
    peaks = [0.1] * 9 + [None]
    buckets = _buckets([1] * 10, extra={"audio_peak": peaks})
    with pytest.raises(ValueError, match="bucketに載っていない"):
        detect_spikes(buckets, metrics=("audio_peak",), zscore_min=1.0)


def test_detect_spikes_uses_audio_peak_when_every_bucket_carries_it():
    peaks = [0.0] * 9 + [10.0]
    buckets = _buckets([0] * 10, extra={"audio_peak": peaks})
    spikes = detect_spikes(buckets, metrics=("audio_peak",), zscore_min=3.0)
    assert len(spikes) == 1
    assert spikes[0]["metric"] == "audio_peak"
    assert spikes[0]["values"]["audio_peak"] == pytest.approx(10.0)


def test_detect_spikes_picks_the_metric_with_the_highest_zscore():
    diamonds = [0] * 9 + [10]          # z = 3.0
    comments = [0] * 8 + [10, 10]      # z < 3.0 (外れ値が2個で分散が広い)
    spikes = detect_spikes(_buckets(diamonds, comments),
                           metrics=("diamonds", "comments"), zscore_min=1.0)
    last = [s for s in spikes if s["index"] == 9][0]
    assert last["metric"] == "diamonds"
    assert last["zscores"]["diamonds"] > last["zscores"]["comments"]


def test_detect_spikes_null_metric_values_count_as_zero():
    buckets = _buckets([0] * 9 + [10])
    buckets[0]["diamonds"] = None
    spikes = detect_spikes(buckets, zscore_min=3.0)
    assert len(spikes) == 1
    assert spikes[0]["values"]["diamonds"] == pytest.approx(10.0)


def test_detect_spikes_empty_buckets():
    assert detect_spikes([], zscore_min=1.0) == []


def test_detect_spikes_ratio_is_zero_when_baseline_is_not_positive():
    # 負値ばかりで平均<=0 のとき、比は捏造せず 0.0。
    buckets = _buckets([-10, -10, -10, -10, -10, 0])
    spikes = detect_spikes(buckets, zscore_min=1.0)
    assert spikes and all(s["ratio"] == 0.0 for s in spikes)


# --------------------------------------------------------------------- jsonio


def test_js_safe_keeps_max_safe_integer_numeric():
    assert js_safe(JS_MAX_SAFE_INTEGER) == JS_MAX_SAFE_INTEGER
    assert isinstance(js_safe(JS_MAX_SAFE_INTEGER), int)


def test_js_safe_stringifies_beyond_max_safe_integer():
    assert js_safe(JS_MAX_SAFE_INTEGER + 1) == str(JS_MAX_SAFE_INTEGER + 1)
    assert js_safe(7664176088063052545) == "7664176088063052545"


def test_js_safe_uses_absolute_value_for_negatives():
    assert js_safe(-(JS_MAX_SAFE_INTEGER + 1)) == str(-(JS_MAX_SAFE_INTEGER + 1))
    assert js_safe(-JS_MAX_SAFE_INTEGER) == -JS_MAX_SAFE_INTEGER


def test_js_safe_does_not_stringify_booleans():
    assert js_safe(True) is True
    assert js_safe(False) is False
    assert js_safe({"ok": True}) == {"ok": True}


def test_js_safe_leaves_floats_and_strings_alone():
    assert js_safe(1e300) == 1e300
    assert js_safe("7664176088063052545") == "7664176088063052545"
    assert js_safe(None) is None


def test_js_safe_recurses_into_nested_containers():
    big = JS_MAX_SAFE_INTEGER + 5
    value = {"detail": {"room_id": big, "counts": [1, big, {"user_id": big}]}}
    assert js_safe(value) == {
        "detail": {"room_id": str(big), "counts": [1, str(big), {"user_id": str(big)}]},
    }


def test_js_safe_normalises_tuples_to_lists():
    assert js_safe((1, 2)) == [1, 2]


def test_js_safe_response_render_emits_the_id_as_a_string():
    body = JsSafeJSONResponse({"room_id": 7664176088063052545, "count": 12}).body
    assert json.loads(body) == {"room_id": "7664176088063052545", "count": 12}


# --------------------------------------------------------------------- cancel


class FakeProcess:
    def __init__(self, returncode=None):
        self.returncode = returncode
        self.kills = 0

    def kill(self):
        self.kills += 1
        self.returncode = -9


def test_cancel_kills_registered_processes():
    token = CancelToken("j1")
    a, b = FakeProcess(), FakeProcess()
    token.register_process(a)
    token.register_process(b)
    assert not token.cancelled
    token.cancel()
    assert token.cancelled
    assert (a.kills, b.kills) == (1, 1)


def test_cancel_is_idempotent():
    token = CancelToken("j1")
    proc = FakeProcess()
    token.register_process(proc)
    token.cancel()
    token.cancel()
    assert proc.kills == 1


def test_register_after_cancel_kills_immediately():
    token = CancelToken("j1")
    token.cancel()
    late = FakeProcess()
    token.register_process(late)
    assert late.kills == 1


def test_forget_process_detaches_it_from_the_cancel():
    token = CancelToken("j1")
    proc = FakeProcess()
    token.register_process(proc)
    token.forget_process(proc)
    token.forget_process(proc)
    token.cancel()
    assert proc.kills == 0


def test_cancel_skips_already_exited_processes():
    token = CancelToken("j1")
    done = FakeProcess(returncode=0)
    token.register_process(done)
    token.cancel()
    assert done.kills == 0


def test_cancel_survives_a_process_that_refuses_to_die():
    class Stubborn(FakeProcess):
        def kill(self):
            raise OSError("gone")

    token = CancelToken("j1")
    token.register_process(Stubborn())
    token.cancel()
    assert token.cancelled


def test_check_raises_job_cancelled_carrying_the_job_id():
    token = CancelToken("burn-42")
    token.check()
    token.cancel()
    with pytest.raises(JobCancelled) as excinfo:
        token.check()
    assert excinfo.value.job_id == "burn-42"


def test_job_cancelled_is_not_an_exception_subclass():
    # broad `except Exception` の render fallback に飲まれてはいけない。
    assert issubclass(JobCancelled, BaseException)
    assert not issubclass(JobCancelled, Exception)
    token = CancelToken("j1")
    token.cancel()
    caught = None
    try:
        token.check()
    except Exception:  # noqa: BLE001
        caught = "exception"
    except JobCancelled:
        caught = "cancelled"
    assert caught == "cancelled"


def test_module_helpers_are_no_ops_outside_a_job():
    assert current_token() is None
    assert is_cancelled() is False
    check_cancelled()
    proc = FakeProcess()
    register_process(proc)
    forget_process(proc)
    assert proc.kills == 0


def test_token_scope_binds_and_restores_the_active_token():
    outer = CancelToken("outer")
    inner = CancelToken("inner")
    with token_scope(outer) as bound:
        assert bound is outer
        assert current_token() is outer
        with token_scope(inner):
            assert current_token() is inner
        assert current_token() is outer
    assert current_token() is None


def test_token_scope_restores_even_when_the_block_raises():
    token = CancelToken("j1")
    with pytest.raises(RuntimeError):
        with token_scope(token):
            raise RuntimeError("boom")
    assert current_token() is None


def test_module_helpers_route_to_the_active_token():
    token = CancelToken("j1")
    proc = FakeProcess()
    with token_scope(token):
        register_process(proc)
        assert is_cancelled() is False
        check_cancelled()
        token.cancel()
        assert is_cancelled() is True
        assert proc.kills == 1
        with pytest.raises(JobCancelled):
            check_cancelled()


def test_forget_process_via_module_helper():
    token = CancelToken("j1")
    proc = FakeProcess()
    with token_scope(token):
        register_process(proc)
        forget_process(proc)
    token.cancel()
    assert proc.kills == 0


def test_cancel_token_scope_does_not_leak_into_a_sibling_context():
    token = CancelToken("j1")
    token.cancel()
    with token_scope(token):
        assert is_cancelled() is True
    assert is_cancelled() is False
    assert cancel_mod.current_token() is None


# ------------------------------------------- detect_spikes: weights / min_values


def _laugh(values):
    """laugh_comment だけを載せた bucket 列。diamonds/comments は全て0。"""
    return _buckets([0] * len(values), extra={"laugh_comment": values})


def test_min_values_suppresses_a_single_hit_in_a_zero_inflated_metric():
    """笑い系は系列のほぼ全てが0なので、1件でも大きなzが出る。

    下限を置かないと「ほとんど笑わない配信のたった1件」が候補を占領する。実測では
    窓内1件だけの窓が中央値z=1.50を得て、22.1%のsessionでz>=2.0を超えた。
    """
    buckets = _laugh([0] * 9 + [1])
    metrics = ("laugh_comment",)
    assert len(detect_spikes(buckets, metrics=metrics, zscore_min=2.0)) == 1
    assert detect_spikes(buckets, metrics=metrics, zscore_min=2.0,
                         min_values={"laugh_comment": 2.0}) == []


def test_min_values_keeps_windows_that_clear_the_floor():
    buckets = _laugh([0] * 9 + [5])
    got = detect_spikes(buckets, metrics=("laugh_comment",), zscore_min=2.0,
                        min_values={"laugh_comment": 2.0})
    assert [c["values"]["laugh_comment"] for c in got] == [5]


def test_min_values_does_not_change_the_zscore_population():
    """下限は候補化の条件だけを変える。系列もz-scoreの母集団も動かさない
    (動かすと同じ配信の他の窓の判定まで変わる)。"""
    buckets = _laugh([0] * 8 + [3, 9])
    plain = {c["start"]: c["zscore"] for c in
             detect_spikes(buckets, metrics=("laugh_comment",), zscore_min=1.0)}
    floored = detect_spikes(buckets, metrics=("laugh_comment",), zscore_min=1.0,
                            min_values={"laugh_comment": 5.0})
    assert len(floored) == 1
    assert floored[0]["zscore"] == plain[floored[0]["start"]]


def test_weights_scale_the_zscore_of_one_metric_only():
    buckets = _buckets([0] * 9 + [10], extra={"laugh_comment": [0] * 9 + [10]})
    metrics = ("diamonds", "laugh_comment")
    plain = detect_spikes(buckets, metrics=metrics, zscore_min=3.0)[0]
    assert plain["zscore"] == pytest.approx(3.0)
    weighted = detect_spikes(buckets, metrics=metrics, zscore_min=3.0,
                             weights={"laugh_comment": 2.0})[0]
    assert weighted["metric"] == "laugh_comment"
    assert weighted["zscore"] == pytest.approx(6.0)
    # 重み付けしていない側のzは動かない。
    assert weighted["zscores"]["diamonds"] == pytest.approx(3.0)


def test_weights_and_min_values_default_to_the_previous_behaviour():
    """未指定なら既存の挙動と完全に同一。配信者pageの見どころは影響を受けない。"""
    buckets = _buckets([0] * 9 + [10])
    assert (detect_spikes(buckets, zscore_min=3.0)
            == detect_spikes(buckets, zscore_min=3.0, weights=None, min_values=None))
