"""容量の時系列から「あと何日で満杯か」を見積もる。

この module は純関数だけで構成する(I/O も設定読みも持たない)。予測の作法そのものを
test で固定したいためで、DB や filesystem を抱えると固定できない。

方針は最小二乗の直線あてはめ1本。容量の増減は「録画した分だけ減る」というほぼ線形の現象で、
観測が数十点しかない段階で非線形modelを当てても、当てはまりが良くなるのは過去だけである。

ただし**外挿は必ず区間で示す**。点推定の「あとX日」は、観測が2週間しかない状態で半年先を
断言してしまう。この module が返すのは常に (下限, 上限) と、その予測が観測期間の何倍先を
見ているか(extrapolation_ratio)である。倍率が大きすぎる予測は数値を返さず
``beyond_horizon`` として突き返す。
"""

import math
from typing import Optional

# 両側95%のt分位点。df=1..30を表で持ち、それ以上は正規近似(1.96)に落とす。
# 観測が数点しかない段階では正規近似の区間が実態より狭くなり、「あと30日」と細い幅で
# 言い切ってしまう。scipyを引くほどの話ではないので表で持つ。
_T95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
    15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056,
    27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}
_T95_LARGE = 1.96

STATUS_OK = "ok"
STATUS_INSUFFICIENT = "insufficient_data"
STATUS_NOT_SHRINKING = "not_shrinking"
STATUS_INCONCLUSIVE = "inconclusive"
STATUS_BEYOND_HORIZON = "beyond_horizon"

SECONDS_PER_DAY = 86400.0


def t95(df: int) -> float:
    if df <= 0:
        return float("inf")
    return _T95.get(df, _T95_LARGE)


def linear_fit(points: list) -> Optional[dict]:
    """(x, y) の最小二乗直線。傾きの標準誤差まで返す。

    x が全て同じ(時間が進んでいない)場合は傾きが定義できないので None。
    点が2点だと残差0で標準誤差も0になり、区間が「幅ゼロ」になる。これは精度が高いのではなく
    検証不能なだけなので、区間を要求する呼び出し側が df>=1 (3点以上) を課すこと。
    """
    n = len(points)
    if n < 2:
        return None
    mean_x = sum(p[0] for p in points) / n
    mean_y = sum(p[1] for p in points) / n
    sxx = sum((p[0] - mean_x) ** 2 for p in points)
    if sxx <= 0:
        return None
    sxy = sum((p[0] - mean_x) * (p[1] - mean_y) for p in points)
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x

    residuals = [p[1] - (intercept + slope * p[0]) for p in points]
    df = n - 2
    if df > 0:
        s2 = sum(r * r for r in residuals) / df
        slope_se = math.sqrt(s2 / sxx)
    else:
        s2 = 0.0
        slope_se = 0.0

    syy = sum((p[1] - mean_y) ** 2 for p in points)
    r2 = 1.0 - (sum(r * r for r in residuals) / syy) if syy > 0 else 1.0
    return {
        "slope": slope,
        "intercept": intercept,
        "slope_se": slope_se,
        "r2": r2,
        "n": n,
        "df": df,
    }


def forecast_days_to_full(samples: list, free_now: float, *, min_samples: int = 3,
                          max_extrapolation: float = 3.0) -> dict:
    """空き容量の時系列から満杯までの日数を区間で見積もる。

    ``samples`` は (epoch秒, 空きbytes) の列。``free_now`` は現在の空きbytes。

    返り値の ``status``:
      ``insufficient_data``  点が足りない/時間幅がない。数値は出さない
      ``not_shrinking``      傾きが0以上(減っていない)。満杯予測は存在しない
      ``inconclusive``       傾きの95%区間が0をまたぐ。「減っている」と言い切れない
      ``beyond_horizon``     予測が観測期間の max_extrapolation 倍より先。数値は出さない
      ``ok``                 days_low / days_high を返す

    区間は傾きの95%信頼区間を日数へ写したもの。傾きが急なほど早く尽きるので、
    傾きの下限・上限と日数の上限・下限が入れ替わる。
    """
    cleaned = sorted((float(t), float(v)) for t, v in samples)
    observed_days = (
        (cleaned[-1][0] - cleaned[0][0]) / SECONDS_PER_DAY if len(cleaned) >= 2 else 0.0
    )
    base = {
        "n": len(cleaned),
        "observed_days": observed_days,
        "free_bytes": free_now,
        "min_samples": min_samples,
        "max_extrapolation": max_extrapolation,
    }
    if len(cleaned) < max(2, min_samples) or observed_days <= 0:
        return {**base, "status": STATUS_INSUFFICIENT}

    # 日単位で回帰する。秒のままだと傾きが極端に小さく、読むときに毎回換算が要る。
    origin = cleaned[0][0]
    fit = linear_fit([((t - origin) / SECONDS_PER_DAY, v) for t, v in cleaned])
    if fit is None:
        return {**base, "status": STATUS_INSUFFICIENT}

    slope = fit["slope"]  # bytes/day (負なら減っている)
    stats = {**base, "slope_bytes_per_day": slope, "r2": fit["r2"], "df": fit["df"]}
    if slope >= 0:
        return {**stats, "status": STATUS_NOT_SHRINKING}

    margin = t95(fit["df"]) * fit["slope_se"]
    slope_hi = slope + margin  # 0に近い側 = 減りが遅い = 満杯まで長い
    slope_lo = slope - margin  # 急な側 = 早く尽きる
    stats["slope_ci"] = (slope_lo, slope_hi)
    if slope_hi >= 0:
        # 区間が0をまたぐ: 減少と言い切れない。点推定だけ出すと確からしさを偽る。
        return {**stats, "status": STATUS_INCONCLUSIVE}

    days = free_now / -slope
    days_low = free_now / -slope_lo    # 最も急な傾き = 最短
    days_high = free_now / -slope_hi   # 最も緩い傾き = 最長
    stats.update({"days_to_full": days, "days_low": days_low, "days_high": days_high,
                  "extrapolation_ratio": days / observed_days if observed_days else float("inf")})
    if days > observed_days * max_extrapolation:
        # 2週間の観測で半年先を言うのは外挿のしすぎ。数値は伏せ、「少なくともこの先まで
        # は持つ」という観測から言える形だけを返す。
        return {**stats, "status": STATUS_BEYOND_HORIZON,
                "beyond_days": observed_days * max_extrapolation}
    return {**stats, "status": STATUS_OK}


def daily_totals(rows: list) -> list:
    """(epoch秒, 量) を日ごとに合計して [(日付文字列, 量), ...] 昇順で返す。

    日境界はlocaltime。画面も他の集計もlocaltimeで見ているので、ここだけUTCにすると
    「今日の増加」が画面の今日とずれる。
    """
    import datetime

    buckets: dict = {}
    for ts, amount in rows:
        day = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        buckets[day] = buckets.get(day, 0) + (amount or 0)
    return sorted(buckets.items())


def completion_rate(done: int, total: int) -> Optional[float]:
    """完了率(%)。母数0のときは0%ではなくNone。

    「対象が無い」と「1件も終わっていない」は別の状態で、0%と書くと後者に見える。
    """
    if not total:
        return None
    return done / total * 100.0
