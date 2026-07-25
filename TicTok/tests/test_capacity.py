import math

import pytest

from tictok.core import capacity

DAY = capacity.SECONDS_PER_DAY
GB = 1024 ** 3


def _samples(start, free_start, per_day, days, jitter=None):
    """1日1点で free が per_day ずつ変化する列。"""
    out = []
    for i in range(days):
        value = free_start + per_day * i
        if jitter:
            value += jitter[i % len(jitter)]
        out.append((start + i * DAY, value))
    return out


# ===== linear_fit =====

def test_linear_fit_recovers_a_known_slope():
    fit = capacity.linear_fit([(0.0, 100.0), (1.0, 90.0), (2.0, 80.0), (3.0, 70.0)])
    assert fit["slope"] == pytest.approx(-10.0)
    assert fit["intercept"] == pytest.approx(100.0)
    assert fit["r2"] == pytest.approx(1.0)
    assert fit["slope_se"] == pytest.approx(0.0)


def test_linear_fit_needs_two_distinct_x():
    assert capacity.linear_fit([(1.0, 5.0)]) is None
    # x が動いていない = 傾きが定義できない。0を返すと「変化なし」と誤読される。
    assert capacity.linear_fit([(1.0, 5.0), (1.0, 9.0)]) is None


# ===== forecast: 足りないものは出さない =====

def test_forecast_refuses_when_samples_are_too_few():
    result = capacity.forecast_days_to_full(
        _samples(0, 100 * GB, -1 * GB, 2), 100 * GB, min_samples=3)
    assert result["status"] == capacity.STATUS_INSUFFICIENT
    assert "days_to_full" not in result


def test_forecast_refuses_when_no_time_has_passed():
    same_instant = [(1000.0, 50 * GB), (1000.0, 49 * GB), (1000.0, 48 * GB)]
    result = capacity.forecast_days_to_full(same_instant, 48 * GB)
    assert result["status"] == capacity.STATUS_INSUFFICIENT


def test_forecast_reports_growth_instead_of_a_bogus_deadline():
    """空きが増えているときに満杯予測は存在しない。負の日数や巨大な日数を返さないこと。"""
    result = capacity.forecast_days_to_full(
        _samples(0, 50 * GB, +2 * GB, 6), 60 * GB)
    assert result["status"] == capacity.STATUS_NOT_SHRINKING
    assert "days_to_full" not in result
    assert result["slope_bytes_per_day"] > 0


def test_forecast_is_inconclusive_when_the_slope_ci_crosses_zero():
    """ばらつきが大きく「減っている」と言い切れない場合は数値を出さない。
    点推定だけ出すと、確からしさを偽ることになる。"""
    noisy = _samples(0, 100 * GB, -0.05 * GB, 8, jitter=[+8 * GB, -8 * GB, +6 * GB, -7 * GB])
    result = capacity.forecast_days_to_full(noisy, 100 * GB)
    assert result["status"] == capacity.STATUS_INCONCLUSIVE
    assert "days_to_full" not in result
    assert result["slope_ci"][1] >= 0


# ===== forecast: 外挿のしすぎを断る =====

def test_forecast_refuses_to_extrapolate_far_beyond_the_observed_window():
    """7日の観測で1000日先を言わない。観測期間の max_extrapolation 倍を超えたら数値を伏せる。"""
    result = capacity.forecast_days_to_full(
        _samples(0, 500 * GB, -0.5 * GB, 7), 500 * GB, max_extrapolation=3.0)
    assert result["status"] == capacity.STATUS_BEYOND_HORIZON
    assert result["observed_days"] == pytest.approx(6.0)
    # 「少なくともここまでは持つ」という観測から言える形だけを返す。
    assert result["beyond_days"] == pytest.approx(18.0)


def test_forecast_returns_an_interval_within_the_horizon():
    result = capacity.forecast_days_to_full(
        _samples(0, 100 * GB, -10 * GB, 8), 30 * GB, max_extrapolation=5.0)
    assert result["status"] == capacity.STATUS_OK
    assert result["days_to_full"] == pytest.approx(3.0, rel=0.05)
    # 区間であること。点推定を挟むこと。
    assert result["days_low"] <= result["days_to_full"] <= result["days_high"]
    assert result["observed_days"] == pytest.approx(7.0)


def test_forecast_interval_widens_when_the_data_is_noisier():
    """同じ傾きでも、ばらつきが大きいほど区間は広い。区間幅が精度を表していること。"""
    clean = capacity.forecast_days_to_full(
        _samples(0, 100 * GB, -5 * GB, 10), 50 * GB, max_extrapolation=100.0)
    noisy = capacity.forecast_days_to_full(
        _samples(0, 100 * GB, -5 * GB, 10, jitter=[+3 * GB, -3 * GB, +2 * GB, -2 * GB]),
        50 * GB, max_extrapolation=100.0)
    assert clean["status"] == capacity.STATUS_OK
    assert noisy["status"] == capacity.STATUS_OK
    clean_width = clean["days_high"] - clean["days_low"]
    noisy_width = noisy["days_high"] - noisy["days_low"]
    assert noisy_width > clean_width


def test_forecast_interval_narrows_as_observation_grows():
    """観測が伸びれば区間は締まる。3日と20日で同じ幅を返すなら、区間は情報を持っていない。"""
    jitter = [+2 * GB, -2 * GB, +1 * GB, -1 * GB]
    short = capacity.forecast_days_to_full(
        _samples(0, 100 * GB, -5 * GB, 4, jitter=jitter), 80 * GB, max_extrapolation=100.0)
    long = capacity.forecast_days_to_full(
        _samples(0, 100 * GB, -5 * GB, 20, jitter=jitter), 80 * GB, max_extrapolation=100.0)
    assert short["status"] == capacity.STATUS_OK and long["status"] == capacity.STATUS_OK
    assert (long["days_high"] - long["days_low"]) < (short["days_high"] - short["days_low"])


def test_t95_is_wider_for_small_samples_than_the_normal_approximation():
    """点が少ないときに正規近似(1.96)を使うと区間が実態より狭くなる。"""
    assert capacity.t95(1) > capacity.t95(5) > capacity.t95(30) >= 1.96
    assert capacity.t95(500) == pytest.approx(1.96)


# ===== 補助 =====

def test_daily_totals_sums_per_local_day():
    import datetime

    def at(day, hour):
        return datetime.datetime(2026, 7, day, hour).timestamp()

    rows = [(at(1, 1), 10), (at(1, 23), 5), (at(2, 12), 7)]
    assert capacity.daily_totals(rows) == [("2026-07-01", 15), ("2026-07-02", 7)]


def test_completion_rate_distinguishes_no_targets_from_none_done():
    assert capacity.completion_rate(0, 0) is None      # 対象なし
    assert capacity.completion_rate(0, 10) == 0.0      # 1件も終わっていない
    assert capacity.completion_rate(5, 10) == pytest.approx(50.0)


def test_forecast_carries_the_inputs_it_used():
    """出た数字がどの条件で出たかをpayloadだけで追えること(画面が併記するため)。"""
    result = capacity.forecast_days_to_full(
        _samples(0, 100 * GB, -10 * GB, 6), 40 * GB, min_samples=3, max_extrapolation=4.0)
    assert result["n"] == 6
    assert result["min_samples"] == 3
    assert result["max_extrapolation"] == 4.0
    assert result["observed_days"] == pytest.approx(5.0)
    assert math.isfinite(result["r2"])
