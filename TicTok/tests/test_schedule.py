import datetime
import time

import pytest

from tictok.core.schedule import (
    HOURS_PER_DAY,
    UNIFORM_FACTORS,
    ScheduleProfile,
    ScheduleProfiler,
    build_hour_profile,
    build_schedule_profile,
    hour_of,
    interval_factors,
)


class FakeSettings:
    def __init__(self, **values):
        self._values = values

    def get(self, key):
        return self._values[key]


def _settings(**overrides):
    values = {
        "live_check_schedule_enabled": 1,
        "live_check_schedule_floor": 0.35,
        "live_check_schedule_min_factor": 0.5,
        "live_check_schedule_max_factor": 2.0,
        "live_check_schedule_min_sessions": 8,
        "live_check_schedule_window_days": 90,
        "live_check_schedule_refresh_seconds": 3600,
    }
    values.update(overrides)
    return FakeSettings(**values)


def _ts(days_ago: int, hour: int) -> float:
    """local timeで days_ago 日前の hour時ちょうど。profileもlocal timeで刻むため、
    tzを跨いでも test と実装が同じ軸に乗る。固定日付だと保存期間windowの外へ落ちて
    いつか勝手に壊れるので、常に現在からの相対で作る。"""
    midnight = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return (midnight - datetime.timedelta(days=days_ago) + datetime.timedelta(hours=hour)).timestamp()


def _budget(factors) -> float:
    """一様配分を1.0としたときの総probe量。"""
    return sum(1.0 / f for f in factors) / HOURS_PER_DAY


# ---------------- build_hour_profile ----------------


def test_profile_is_a_distribution():
    profile = build_hour_profile([_ts(d, 20) for d in range(10)], floor=0.35)
    assert len(profile) == HOURS_PER_DAY
    assert sum(profile) == pytest.approx(1.0)
    assert all(p > 0 for p in profile)


def test_profile_peaks_at_the_observed_hour():
    profile = build_hour_profile([_ts(d, 20) for d in range(10)], floor=0.35)
    assert profile.index(max(profile)) == 20


def test_smoothing_spreads_evidence_to_neighbouring_hours():
    # 20時の観測は19時/21時の証拠でもある(配信開始は日ごとに前後する)。
    profile = build_hour_profile([_ts(d, 20) for d in range(10)], floor=0.35)
    assert profile[19] > profile[17]
    assert profile[21] > profile[23]


def test_floor_keeps_unobserved_hours_above_zero():
    profile = build_hour_profile([_ts(d, 20) for d in range(10)], floor=0.35)
    # 観測から遠い時間帯でも一様混合ぶんが必ず残る。
    assert profile[8] >= 0.35 / HOURS_PER_DAY


def test_empty_history_is_uniform():
    assert build_hour_profile([], floor=0.35) == pytest.approx(
        [1.0 / HOURS_PER_DAY] * HOURS_PER_DAY
    )


# ---------------- interval_factors ----------------


def test_total_probe_budget_matches_uniform_allocation():
    # 再配分であって増量ではない。ProbeGateの総量上限を侵さない前提そのもの。
    profile = build_hour_profile([_ts(d, 20) for d in range(20)], floor=0.35)
    factors = interval_factors(profile, min_factor=0.5, max_factor=2.0)
    assert _budget(factors) == pytest.approx(1.0, abs=1e-6)


def test_budget_never_exceeds_uniform_even_when_clamps_bind():
    # clampが強く効く設定でも総量が一様配分を超えないこと(超えると外部APIへの負荷上限
    # を破る)。
    profile = build_hour_profile([_ts(d, 20) for d in range(50)], floor=0.05)
    factors = interval_factors(profile, min_factor=0.9, max_factor=1.05)
    assert _budget(factors) <= 1.0 + 1e-9


def test_likely_hours_get_shorter_intervals_than_quiet_hours():
    profile = build_hour_profile([_ts(d, 20) for d in range(20)], floor=0.35)
    factors = interval_factors(profile, min_factor=0.5, max_factor=2.0)
    assert factors[20] < 1.0 < factors[8]


def test_factors_respect_the_configured_bounds():
    profile = build_hour_profile([_ts(d, 20) for d in range(50)], floor=0.02)
    factors = interval_factors(profile, min_factor=0.5, max_factor=1.5)
    assert min(factors) >= 0.5 - 1e-9
    assert max(factors) <= 1.5 + 1e-9


def test_max_factor_bounds_the_worst_case_detection_interval():
    # 予測を外しても、確認間隔が live_check_interval * max_factor を超えないことが
    # 取り逃し防止の最低保証。
    profile = build_hour_profile([_ts(d, 20) for d in range(100)], floor=0.35)
    factors = interval_factors(profile, min_factor=0.5, max_factor=2.0)
    assert max(factors) <= 2.0 + 1e-9


def test_uniform_profile_yields_uniform_factors():
    flat = tuple([1.0 / HOURS_PER_DAY] * HOURS_PER_DAY)
    factors = interval_factors(flat, min_factor=0.5, max_factor=2.0)
    assert factors == pytest.approx([1.0] * HOURS_PER_DAY)


def test_sqrt_allocation_is_gentler_than_proportional():
    # 配分則の選定根拠。確率に反比例させる素朴な配分より偏りが小さく、外した時の
    # 悪化が抑えられる。
    profile = build_hour_profile([_ts(d, 20) for d in range(20)], floor=0.35)
    factors = interval_factors(profile, min_factor=0.1, max_factor=10.0)
    ratio = max(factors) / min(factors)
    proportional = max(profile) / min(profile)
    assert ratio == pytest.approx(proportional ** 0.5, rel=0.05)


# ---------------- build_schedule_profile ----------------


def test_too_few_sessions_stays_uniform():
    profile = build_schedule_profile(
        [_ts(d, 20) for d in range(5)],
        floor=0.35, min_factor=0.5, max_factor=2.0, min_sessions=8,
    )
    assert profile.uniform
    assert profile.sample_count == 5


def test_enough_sessions_produces_a_shaped_profile():
    profile = build_schedule_profile(
        [_ts(d, 20) for d in range(20)],
        floor=0.35, min_factor=0.5, max_factor=2.0, min_sessions=8,
    )
    assert not profile.uniform
    assert profile.factor_at(_ts(99, 20)) < profile.factor_at(_ts(99, 8))


def test_peak_hours_report_the_tightest_cells():
    profile = build_schedule_profile(
        [_ts(d, 20) for d in range(20)],
        floor=0.35, min_factor=0.5, max_factor=2.0, min_sessions=8,
    )
    assert 20 in profile.peak_hours(3)


def test_bimodal_history_keeps_both_peaks():
    # 実配信者は昼と夜の2山を持つ(streamer_aが11時と22時)。片方へ寄せない。
    starts = [_ts(d, 11) for d in range(10)] + [_ts(d, 22) for d in range(10)]
    profile = build_schedule_profile(
        starts, floor=0.35, min_factor=0.5, max_factor=2.0, min_sessions=8,
    )
    assert profile.factor_at(_ts(99, 11)) < 1.0
    assert profile.factor_at(_ts(99, 22)) < 1.0
    assert profile.factor_at(_ts(99, 4)) > 1.0


def test_midnight_wrap_is_circular():
    # 23時と0時は隣。循環畳み込みでないと年に一度の境目で分布が割れる。
    starts = [_ts(d, 23) for d in range(15)]
    profile = build_schedule_profile(
        starts, floor=0.35, min_factor=0.5, max_factor=2.0, min_sessions=8,
    )
    assert profile.factor_at(_ts(99, 0)) < profile.factor_at(_ts(99, 12))


# ---------------- ScheduleProfiler ----------------


def test_profiler_groups_history_per_streamer():
    history = (
        [("alice", _ts(d, 20)) for d in range(20)]
        + [("bob", _ts(d, 9)) for d in range(20)]
    )
    profiler = ScheduleProfiler(lambda: history, _settings(), time_source=lambda: 0.0)
    alice = profiler.profile_for("alice")
    bob = profiler.profile_for("bob")
    assert alice.factor_at(_ts(99, 20)) < alice.factor_at(_ts(99, 9))
    assert bob.factor_at(_ts(99, 9)) < bob.factor_at(_ts(99, 20))


def test_profiler_reads_history_once_per_ttl():
    calls = []

    def history():
        calls.append(1)
        return [("alice", _ts(d, 20)) for d in range(20)]

    clock = [0.0]
    profiler = ScheduleProfiler(history, _settings(live_check_schedule_refresh_seconds=100),
                                time_source=lambda: clock[0])
    for _ in range(5):
        profiler.profile_for("alice")
    assert len(calls) == 1
    clock[0] = 150.0
    profiler.profile_for("alice")
    assert len(calls) == 2


def test_profiler_returns_uniform_for_an_unknown_streamer():
    profiler = ScheduleProfiler(lambda: [], _settings(), time_source=lambda: 0.0)
    assert profiler.profile_for("nobody").uniform


def test_disabled_profiler_never_reads_history():
    calls = []

    def history():
        calls.append(1)
        return []

    profiler = ScheduleProfiler(history, _settings(live_check_schedule_enabled=0),
                                time_source=lambda: 0.0)
    assert profiler.profile_for("alice").uniform
    assert calls == []


def test_profiler_ignores_history_outside_the_window():
    # 半年前の生活pattern は現在の予測材料にならない。
    old = [("alice", _ts(400 + d, 3)) for d in range(30)]
    recent = [("alice", _ts(d, 20)) for d in range(20)]
    profiler = ScheduleProfiler(lambda: old + recent,
                                _settings(live_check_schedule_window_days=90),
                                time_source=lambda: 0.0)
    profile = profiler.profile_for("alice")
    assert profile.sample_count == 20
    assert profile.factor_at(_ts(99, 20)) < profile.factor_at(_ts(99, 3))


def test_profiler_skips_rows_with_no_start_time():
    history = [("alice", None)] + [("alice", _ts(d, 20)) for d in range(20)]
    profiler = ScheduleProfiler(lambda: history, _settings(), time_source=lambda: 0.0)
    assert profiler.profile_for("alice").sample_count == 20


# ---------------- collector integration ----------------


def test_collector_without_a_profiler_keeps_the_plain_interval():
    from tictok.collect.collector import TikTokCollector

    collector = TikTokCollector.__new__(TikTokCollector)
    collector._schedule_profiler = None
    assert collector._schedule_factor() == 1.0


def test_collector_applies_the_profile_of_its_own_streamer():
    from tictok.collect.collector import TikTokCollector

    now_hour = hour_of(time.time())
    history = [("alice", _ts(d, now_hour)) for d in range(1, 21)]
    profiler = ScheduleProfiler(lambda: history, _settings(), time_source=lambda: 0.0)
    collector = TikTokCollector.__new__(TikTokCollector)
    collector._schedule_profiler = profiler
    collector.unique_id = "alice"
    # いまの時刻に山を作ったので、いまの倍率は1.0未満(=確認が詰まる)になる。
    assert collector._schedule_factor() < 1.0


def test_uniform_profile_factor_is_exactly_one():
    profile = ScheduleProfile(UNIFORM_FACTORS, 0)
    assert profile.factor_at(_ts(0, 13)) == 1.0
    assert profile.uniform
