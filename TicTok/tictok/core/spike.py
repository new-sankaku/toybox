"""bucket系列からの盛り上がり(spike)検出。

配信者pageの「見どころ」(storage.streamer_highlights)と、録画単位の切り抜き候補が同じ
判定を使うための共通層。検出器を2系統持つと、同じ配信に対して2画面が別々の時刻を指し
示すことになる。

判定はsession内のz-score: bucket系列を窓幅ぶん移動合計した系列を作り、その平均・標準
偏差から外れ値を拾う。母集団をsession内に閉じるのは、配信ごとに規模(同接・ギフト額)が
桁で違い、横断のしきい値が意味を持たないため。

窓は**秒**で受けて各sessionのbucket_secondsからbucket個数を導く。bucket_secondsは
session単位で可変(既定10秒)なので、bucket個数で持つとsession間で窓の実長が変わる。

入力はdiamondsとcommentsのみ。joinsは純増ではなく交絡し、viewersはbuckets列に既に
別系列として存在する。
"""

from typing import Optional

# 既定のしきい値。storage.streamer_highlightsが従来から使っている値で、変更すると
# 配信者pageの見どころが変わる。録画単位の候補検出は設定値(clip_candidate_zscore)を
# 明示的に渡す。
HIGHLIGHT_ZSCORE = 2.0
# これ未満のbucket数では平均も標準偏差も意味を持たない(従来の見どころ判定と同値)。
MIN_BUCKETS = 5
# 対応する指標。値は全指標ぶん常に返し、しきい値判定だけをmetricsで絞る。
METRICS = ("diamonds", "comments")


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
                  zscore_min: float = HIGHLIGHT_ZSCORE) -> list:
    """spike候補を時刻順で返す。

    ``buckets`` は storage の bucket 行(start / diamonds / comments を持つ dict 相当)で、
    start昇順・等間隔であることを前提とする。戻り値の ``start`` は窓の先頭bucketのstart
    (wall-clock)で、窓の実長は呼び出し側が bucket_seconds × window_buckets で持つ。

    値が取れない指標は捏造せず0として扱う(bucketの列はNOT NULLだが、NULLが来たときに
    その窓だけ落とすと系列の長さが指標間でずれる)。
    """
    if window_buckets < 1:
        raise ValueError("window_bucketsは1以上である必要があります。")
    unknown = [m for m in metrics if m not in METRICS]
    if unknown:
        raise ValueError(f"未知の指標です: {unknown}")
    series = {}
    for metric in METRICS:
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
        values = {m: series[m][i] for m in METRICS}
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
