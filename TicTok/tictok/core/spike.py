"""bucket系列からの盛り上がり(spike)検出。

録画単位の切り抜き候補が使う判定層。検出器を複数持つと、同じ配信に対して画面ごとに
別々の時刻を指し示すことになるため、判定はここに1つだけ置く。

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
# 笑い系の指標は「窓内で合計できる量」にしてある(秒数・件数)。audio_peakは本来peakなので
# 窓内合計は近似でしかないが、laugh_*は最初から積算量なのでdiamonds/commentsと意味論が揃う。
OPTIONAL_METRICS = ("audio_peak", "laugh_comment", "laugh_audio", "smile")


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
                  zscore_min: Optional[float] = None,
                  weights: Optional[dict] = None,
                  min_values: Optional[dict] = None) -> list:
    """spike候補を時刻順で返す。

    ``buckets`` は storage の bucket 行(start / diamonds / comments を持つ dict 相当)で、
    start昇順・等間隔であることを前提とする。戻り値の ``start`` は窓の先頭bucketのstart
    (wall-clock)で、窓の実長は呼び出し側が bucket_seconds × window_buckets で持つ。

    値が取れない指標は捏造せず0として扱う(bucketの列はNOT NULLだが、NULLが来たときに
    その窓だけ落とすと系列の長さが指標間でずれる)。

    ``weights`` は指標ごとのz倍率(未指定は1.0)。「笑い重視」はこれで表す。
    ``min_values`` は指標ごとの窓内合計の絶対下限で、これを下回る窓はその指標では候補に
    しない。**zero-inflatedな指標には必須**である: 笑い系の系列はほとんどが0なので標準偏差が
    極小になり、ごく僅かな笑いが大きなzを叩く。実測では「窓内1件だけ」の窓が中央値z=1.50を
    得て、22.1%のsessionでそれだけでz>=2.0を超えた。これはfallbackではなく判定条件の追加
    (「1件の笑いは笑っている場面ではない」という定義)である。

    どちらも未指定なら既存の挙動と完全に同一。配信者pageの見どころは影響を受けない。
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
        zs, baseline = computed
        weight = float((weights or {}).get(metric, 1.0))
        if weight != 1.0:
            zs = [z * weight for z in zs]
        stats[metric] = (zs, baseline)
    if not stats:
        return []
    candidates = []
    for i, start in enumerate(starts):
        # 絶対下限を満たさない指標は、その窓では候補の根拠にしない(系列の作り方と
        # z-scoreの母集団は一切変えない — 変えると同じ配信の他の窓の判定まで動く)。
        scored = {m: (z[i], baseline) for m, (z, baseline) in stats.items()
                  if series[m][i] >= float((min_values or {}).get(m, 0.0))}
        if not scored:
            continue
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
