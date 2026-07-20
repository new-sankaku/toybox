"""bucket系列からの盛り上がり(spike)検出。

配信者pageの「見どころ」(storage.streamer_highlights)と、録画単位の切り抜き候補が同じ
判定を使うための共通層。検出器を2系統持つと、同じ配信に対して2画面が別々の時刻を指し
示すことになる。

判定はsession内のz-score: bucket系列を窓幅ぶん移動合計した系列を作り、その平均・標準
偏差から外れ値を拾う。母集団をsession内に閉じるのは、配信ごとに規模(同接・ギフト額)が
桁で違い、横断のしきい値が意味を持たないため。

窓は**秒**で受けて各sessionのbucket_secondsからbucket個数を導く。bucket_secondsは
session単位で可変(既定10秒)なので、bucket個数で持つとsession間で窓の実長が変わる。

必須の入力はdiamondsとcommentsのみ。joinsは純増ではなく交絡し、viewersはbuckets列に既に
別系列として存在する。録画のある区間では、呼び出し側が各bucketへ音声の区間peakを
``audio_peak``として載せられる(OPTIONAL_METRICS)。歓声や笑い声はギフトにもコメントにも
現れないことがあり、その盛り上がりを拾える一方、録画の無いsessionには存在しない値なので
必須にはしない。
"""

from typing import Optional

from tictok.core.config import get_highlight_zscore

# これ未満のbucket数では平均も標準偏差も意味を持たない(従来の見どころ判定と同値)。
MIN_BUCKETS = 5
# 全bucketが必ず持つ指標。値は常に全指標ぶん返し、しきい値判定だけをmetricsで絞る。
METRICS = ("diamonds", "comments")
# bucketに載っていることもある指標。音声由来の値(audio_peak)は録画がある区間でしか
# 作れないので、必須にすると録画の無いsession(配信者pageの見どころ)が判定できなくなる。
# bucket全件がkeyを持つときだけ系列を作り、欠けているものは黙って0で埋めない。
OPTIONAL_METRICS = ("audio_peak",)


def window_bucket_count(bucket_seconds: float, window_seconds: float) -> int:
    """窓の秒数を、そのsessionのbucket幅で何個ぶんかへ直す。"""
    if bucket_seconds <= 0:
        raise ValueError("bucket_secondsは正の値である必要があります。")
    return max(1, int(round(float(window_seconds) / float(bucket_seconds))))


def _rolling_sums(values: list, count: int) -> list:
    """index iの値を[i, i+count)の合計にした系列。末尾は窓が埋まらないので落とす。"""
    if count <= 1:
        return list(values)
    if len(values) < count:
        return []
    total = sum(values[:count])
    sums = [total]
    for i in range(count, len(values)):
        total += values[i] - values[i - count]
        sums.append(total)
    return sums


def _zscores(series: list) -> Optional[tuple]:
    """(z-score系列, 平均)。母集団が小さい/分散0で判定不能ならNone。"""
    n = len(series)
    if n < MIN_BUCKETS:
        return None
    mean = sum(series) / n
    std = (sum((v - mean) ** 2 for v in series) / n) ** 0.5
    if std <= 0:
        return None
    return [(v - mean) / std for v in series], mean


def detect_spikes(buckets: list, window_buckets: int = 1,
                  metrics: tuple = ("diamonds",),
                  zscore_min: Optional[float] = None) -> list:
    """spike候補を時刻順で返す。

    ``buckets`` は storage の bucket 行(start / diamonds / comments を持つ dict 相当)で、
    start昇順・等間隔であることを前提とする。戻り値の ``start`` は窓の先頭bucketのstart
    (wall-clock)で、窓の実長は呼び出し側が bucket_seconds × window_buckets で持つ。

    値が取れない指標は捏造せず0として扱う(bucketの列はNOT NULLだが、NULLが来たときに
    その窓だけ落とすと系列の長さが指標間でずれる)。
    """
    if window_buckets < 1:
        raise ValueError("window_bucketsは1以上である必要があります。")
    if zscore_min is None:
        zscore_min = get_highlight_zscore()
    known = METRICS + OPTIONAL_METRICS
    unknown = [m for m in metrics if m not in known]
    if unknown:
        raise ValueError(f"未知の指標です: {unknown}")
    available = METRICS + tuple(
        m for m in OPTIONAL_METRICS if all(m in b for b in buckets)
    )
    missing = [m for m in metrics if m not in available]
    if missing:
        raise ValueError(f"bucketに載っていない指標を要求されました: {missing}")
    series = {}
    for metric in available:
        values = [float(b[metric] or 0) for b in buckets]
        series[metric] = _rolling_sums(values, window_buckets)
    starts = [b["start"] for b in buckets][: len(series[METRICS[0]])]
    if not starts:
        return []
    stats = {}
    for metric in metrics:
        computed = _zscores(series[metric])
        if computed is None:
            continue
        stats[metric] = computed
    if not stats:
        return []
    candidates = []
    for i, start in enumerate(starts):
        scored = {m: (z[i], baseline) for m, (z, baseline) in stats.items()}
        best_metric = max(scored, key=lambda m: scored[m][0])
        best_z = scored[best_metric][0]
        if best_z < zscore_min:
            continue
        values = {m: series[m][i] for m in available}
        baseline = scored[best_metric][1]
        candidates.append({
            "start": start,
            "index": i,
            "metric": best_metric,
            "zscore": best_z,
            "baseline": baseline,
            "ratio": (values[best_metric] / baseline) if baseline > 0 else 0.0,
            "values": values,
            "zscores": {m: scored[m][0] for m in scored},
        })
    return candidates
