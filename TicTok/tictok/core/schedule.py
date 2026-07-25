"""配信時間帯の推定に基づくlive-check probe予算の再配分。

同じ総probe量のまま、配信が始まりやすい時間帯の確認間隔を詰め、始まりにくい時間帯を
広げる。総量は ProbeGate の live_check_max_per_min が別途上限を掛けており、ここは
その予算の配分だけを決める(増量はしない)。

推定はsession開始時刻のhour-of-day分布に限る。probeを消費するのは待機中のcollector
だけであり、待機が終わる瞬間 = session開始なので、最適化すべき対象はsession開始時刻の
分布そのものになる。曜日x時間帯(168 cell)は実測でout-of-sampleの改善が出なかったため
採らない(1か月/110本では1 cellあたり1本未満で、曜日は雑音しか乗らない)。

配分則は sqrt allocation。平均検出遅延 sum_h p_h * iv_h / 2 を総量 sum_h 1/iv_h 一定の
条件で最小化すると iv_h ∝ p_h^-1/2 が得られる。確率に反比例させる素朴な配分(iv_h ∝
1/p_h)は偏りの小さい配信者で平均・最悪ともに一律配分より悪化することを実測で確認済み。
"""

import datetime
import math
import time

HOURS_PER_DAY = 24

# hour-of-day分布の平滑化kernel(循環畳み込み、+-2時間)。配信開始は日ごとに前後するため、
# 観測された1本は隣接時間帯の証拠でもある。1か月規模のdata量では、この平滑化が無いと
# 空cellが最大間隔に張り付く。
SMOOTHING_KERNEL = (0.25, 0.5, 1.0, 0.5, 0.25)

# 予算配分の解を二分探索で求めるときの反復上限と許容誤差。
_BUDGET_ITERATIONS = 60
_BUDGET_TOLERANCE = 1e-9


def hour_of(timestamp: float) -> int:
    """timestampをlocal timeのhour-of-dayへ落とす。profile構築と参照で同じ関数を通す
    限り、tzの取り方が何であれ自己整合する。"""
    return datetime.datetime.fromtimestamp(timestamp).hour


def build_hour_profile(start_times, floor: float) -> tuple:
    """session開始時刻から、hour-of-dayごとの配信開始確率を推定する。

    ``floor`` は一様分布との混合比で、推定の事前分布にあたる。0なら観測のみ、1なら
    完全一様。観測が無い時間帯の確率がゼロへ落ちないようにするのはこの項の役目で、
    後段の最大間隔clampとは独立に効く。
    """
    counts = [0.0] * HOURS_PER_DAY
    for timestamp in start_times:
        counts[hour_of(timestamp)] += 1.0

    half = len(SMOOTHING_KERNEL) // 2
    smoothed = [0.0] * HOURS_PER_DAY
    for hour in range(HOURS_PER_DAY):
        for offset, weight in enumerate(SMOOTHING_KERNEL):
            smoothed[hour] += counts[(hour + offset - half) % HOURS_PER_DAY] * weight

    total = sum(smoothed)
    if total <= 0:
        return tuple([1.0 / HOURS_PER_DAY] * HOURS_PER_DAY)
    uniform = floor / HOURS_PER_DAY
    return tuple((1.0 - floor) * (value / total) + uniform for value in smoothed)


def interval_factors(profile, min_factor: float, max_factor: float) -> tuple:
    """確率profileを live_check_interval への倍率へ変換する。

    倍率は sqrt allocation (factor ∝ p^-1/2) を [min_factor, max_factor] でclampし、
    総probe量が一様配分とちょうど等しくなるようscaleを二分探索で決める。clampが効いた
    ぶんを吸収せずにscaleすると総量が一様配分を超え得るため、clamp後の総量そのものを
    目的関数にして解く。
    """
    shape = [value ** -0.5 for value in profile]

    def factors_for(scale: float) -> list:
        return [min(max_factor, max(min_factor, scale * s)) for s in shape]

    def budget(scale: float) -> float:
        # 一様配分の総probe量を HOURS_PER_DAY として測った相対量。単調減少。
        return sum(1.0 / f for f in factors_for(scale))

    low, high = 1e-6, 1e6
    for _ in range(_BUDGET_ITERATIONS):
        mid = math.sqrt(low * high)
        if budget(mid) > HOURS_PER_DAY:
            low = mid
        else:
            high = mid
        if high - low < _BUDGET_TOLERANCE:
            break
    return tuple(factors_for(high))


UNIFORM_FACTORS = tuple([1.0] * HOURS_PER_DAY)


class ScheduleProfile:
    """ある配信者の時間帯別 live-check 間隔倍率。"""

    def __init__(self, factors, sample_count: int) -> None:
        self.factors = tuple(factors)
        self.sample_count = sample_count

    @property
    def uniform(self) -> bool:
        return self.factors == UNIFORM_FACTORS

    def factor_at(self, timestamp: float) -> float:
        return self.factors[hour_of(timestamp)]

    def peak_hours(self, count: int = 4) -> list:
        """最も間隔が詰まる(=配信されやすいと推定した)時間帯。log用。"""
        ordered = sorted(range(HOURS_PER_DAY), key=lambda h: self.factors[h])
        return sorted(ordered[:count])


def build_schedule_profile(
    start_times, *, floor: float, min_factor: float, max_factor: float, min_sessions: int
) -> ScheduleProfile:
    """観測が ``min_sessions`` に満たない配信者は一様配分のままにする。

    偏りを推定する材料が無い状態は「偏りが無い」と同義であり、一様配分がそのまま事後
    分布になる。少数の観測から間隔を動かすと、たまたま観測された時間帯以外の検出を
    確実に遅らせるだけになる。
    """
    samples = list(start_times)
    if len(samples) < min_sessions:
        return ScheduleProfile(UNIFORM_FACTORS, len(samples))
    profile = build_hour_profile(samples, floor)
    return ScheduleProfile(interval_factors(profile, min_factor, max_factor), len(samples))


class ScheduleProfiler:
    """配信者ごとのScheduleProfileを、履歴を1回読むだけで作り置きするcache。

    ``history_provider`` は (unique_id, started_at) の列を新しい順に返す呼び出し可能。
    全配信者ぶんを1回で受け取り、TTLが切れるまで使い回す。collector個別にDBを引くと
    監視数に比例してstorage lockを取ることになるため、集約は意図的。
    """

    def __init__(self, history_provider, settings, time_source=time.monotonic) -> None:
        self._history_provider = history_provider
        self._settings = settings
        self._time_source = time_source
        self._profiles: dict = {}
        self._loaded_at = None

    def _refresh(self) -> None:
        floor = self._settings.get("live_check_schedule_floor")
        min_factor = self._settings.get("live_check_schedule_min_factor")
        max_factor = self._settings.get("live_check_schedule_max_factor")
        min_sessions = self._settings.get("live_check_schedule_min_sessions")
        window_days = self._settings.get("live_check_schedule_window_days")

        cutoff = time.time() - window_days * 86400.0
        grouped: dict = {}
        for unique_id, started_at in self._history_provider():
            if started_at is None or started_at < cutoff:
                continue
            grouped.setdefault(unique_id, []).append(started_at)

        self._profiles = {
            unique_id: build_schedule_profile(
                starts, floor=floor, min_factor=min_factor,
                max_factor=max_factor, min_sessions=min_sessions,
            )
            for unique_id, starts in grouped.items()
        }
        self._loaded_at = self._time_source()

    def profile_for(self, unique_id: str) -> ScheduleProfile:
        if not self._settings.get("live_check_schedule_enabled"):
            return ScheduleProfile(UNIFORM_FACTORS, 0)
        ttl = self._settings.get("live_check_schedule_refresh_seconds")
        now = self._time_source()
        if self._loaded_at is None or now - self._loaded_at >= ttl:
            self._refresh()
        profile = self._profiles.get(unique_id)
        if profile is None:
            # 履歴がまだ1本も無い配信者。一様配分が事後分布そのもの。
            return ScheduleProfile(UNIFORM_FACTORS, 0)
        return profile
