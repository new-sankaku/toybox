"""全体解析(配信者横断)の集約ロジック。

集約は「配信(session)単位」の中間集計(payload)と「横断reduce」の2段に分離する。
終了済みsessionのpayloadはstorageのanalytics_session_cache表へ永続化され、
配信者データの削除はsessions行のON DELETE CASCADEでcacheごと消える(全体へ丸めた
集約を持たないため、後からの削除で整合が壊れない)。収集中sessionは毎回その場で
payloadを計算する(session_id indexが効くため軽い)。

per-session計算(compute_payload)はsqlite接続を受け取る純関数。reduce_*は
(sessионのメタdict, payload)のリストを受けてAPI応答を組み立てる。
"""

import bisect
import functools
import hashlib
import json
import logging
import math
import random
import threading
import time
from typing import Optional

from tictok.core import config
from tictok.core.battle import BATTLE_SETTLE_GRACE_SECONDS, resolve_result
from tictok.core.logctx import log_context

logger = logging.getLogger("tictok.analytics")

# Battleのグローブ(Critical Strike card)刺さり率をギフト単価で集約するcoin帯。
GLOVE_COIN_BUCKETS = [
    (1, 15), (16, 50), (51, 100), (101, 500), (501, 1000),
    (1001, 3000), (3001, 6000), (6001, 12000), (12001, 25000), (25001, 45000),
]

# ギフトSKU構成(何の価格帯で課金されているか)の単価帯。TikTokの実際の価格点(1/5/20/
# 99/199/299/500/1000/1500/10000/29999 coin 等)が帯の境界を跨がないよう、桁の変わり目と
# 「500 coin級」「1000 coin級」の実務上の区切りで刻む。最上帯は上限を持たない
# (Universe級の高額SKUを範囲外で落とすと、コインのシェアが合計100%にならなくなる)。
GIFT_SKU_COIN_BUCKETS = [
    (1, 9), (10, 99), (100, 499), (500, 999),
    (1000, 4999), (5000, 19999), (20000, None),
]
# 反復購入とみなす最低送信回数。2回目が発生したかどうかを見る。
_SKU_REPEAT_MIN = 2
# SKU一覧に載せる上限(コイン降順)。全SKUを返すと画面が読めないため。
_SKU_TOP_LIMIT = 25
# identity_keyを畳むdigestのbit数。48bitなら10万identityでも衝突期待値は1e-5未満。
_SKU_IDENTITY_DIGEST_BYTES = 6

# 横断集計で扱う指標。indexは加算できるcount系のみ(viewersは水準値なので除外)。
INDEX_METRICS = ("joins", "comments", "diamonds", "likes", "follows")
RELATION_METRICS = ["joins", "comments", "diamonds", "likes", "follows", "viewers"]

# organic入室(§15)のMVPヒューリスティック係数。宝箱/boost/share由来のノイズ入室を
# 落とすため、各入室に genuineness weight w∈[0,1] を与える。実証(§15.1)で
# 再訪19%/engagement署名2.17倍/収束的妥当性0.83→0.93 を確認済み。将来は§15の
# PU learning/潜在クラスへ置換予定のため、係数は名前付き定数として一元管理する。
_ORGANIC_WEIGHT_BASE = 0.15      # 一見(1回きり・無反応)の下限
_ORGANIC_WEIGHT_RETURNING = 0.45  # 同一配信者の過去sessionに入室歴あり(再訪)
_ORGANIC_WEIGHT_ENGAGED = 0.30    # 入室後に発話/反応(comment/like/gift/follow)
_ORGANIC_WEIGHT_LEVEL = 0.10      # fans_level or gifter_level を保有
# share直後の入室バーストを識別する反応窓(秒)。実証でピーク約3.6倍・60秒で2.92倍。
_ORGANIC_SHARE_WINDOW_SECONDS = 60.0
_ORGANIC_EVENT_KINDS = ("join", "share", "comment", "like", "gift", "follow", "subscribe")

# peri-event(event周辺)解析の定数。session.bucket_secondsと独立に生eventから再bin化する。
_PERI_BIN_SECONDS = 10           # 解析bin幅
_PERI_PRE_BINS = 6               # event前(-60s)
_PERI_POST_BINS = 18             # event後(+180s)
_PERI_BASELINE_BINS = 3          # baseline=窓先頭3bin(-60..-40s)。onset直前はanticipationで汚染するため除外
_PERI_PLACEBO_RATIO = 3          # placebo(帰無)標本を実event数の約N倍だけ系統抽出
_PERI_MIN_EVENTS = 5             # これ未満は集計不能扱い
_PERI_BATTLE_REFRACTORY_SECONDS = 300.0  # battle markerは1戦で複数発火。初回に集約する不応期
_PERI_SHARE_REFRACTORY_SECONDS = 20.0    # share連打を1 onsetへ集約
# cold-open除外: 配信開始直後はalgorithmic cold-start push+つけたてshare洪水でjoinが
# 押し上がり、baseline自体が不安定。開始からこの秒数内に始まるonsetは測定対象から外し、
# placeboにも使わない。
_PERI_COLD_OPEN_SECONDS = 300.0

# Battle展開(残り時間軸)の解析定数。時間軸はTikTok server権威値のend_timeを原点とした
# 残り時間で統一する(start_timeはmatchmakingの都合で前後するため揃わない)。
_BF_BIN_SECONDS = 30             # 残り時間軸のbin幅
_BF_MAX_REMAINING = 300          # 遡る上限(実測でPKの中央値は約305秒)
_BF_LEAD_CHECKPOINT_SECONDS = 60  # 「残り1分リード」のcheckpoint
_BF_TAIL_SECONDS = 60            # 終盤集中度を測る末尾窓
# これより短いbattleは残り時間軸のbinが埋まらず、集中度の分母も安定しないため対象外。
_BF_MIN_DURATION_SECONDS = 120
# リード交代回数のヒストグラムを畳む上限(これ以上は「N回以上」へまとめる)。
_BF_LEAD_CHANGE_CAP = 6

# 収集カバレッジ(F10)。viewer_samplesの欠測窓を測る分位。
_CV_GAP_PERCENTILE = 95.0
# sampling間隔を測るには最低限これだけのsampleが要る(1点では間隔が定義できない)。
_CV_MIN_SAMPLES = 3

# 滞在時間(Little則 W = L / λ)。L=同時接続、λ=到着率=viewer_samples.total_viewers
# (累積来場counter)の時間微分。Little則は定常状態でしか成り立たないため、窓を細かく
# 切り、窓内が定常とみなせるものだけを採用する(不採用は推定不能として別掲する)。
_DW_WINDOW_SECONDS = 300.0        # 推定1点あたりの窓幅
_DW_SUBBIN_SECONDS = 60.0         # 窓内の定常性を測る小bin
_DW_MIN_SUBBINS = 4               # 分散を測るのに要る最低小bin数
_DW_MIN_WINDOW_FILL = 0.6         # 窓の端が欠けた分を許す下限(実観測span / 窓幅)
# 到着が少なすぎる窓はλの相対誤差が大きく、W=L/λが発散する。Poisson変動係数
# 1/√k がこの件数で約35%に収まる水準。
_DW_MIN_ARRIVALS = 8
# 定常性の判定は素の変動係数ではなく分散対平均比(index of dispersion / Fano因子)で行う。
# 定常Poisson到着でも小binの件数はばらつき、素のCVは件数が少ないだけで閾値を超えて
# しまう(λ一定でもCV≈1/√k)。Fano因子は定常Poissonなら件数によらず1へ寄るため、
# 「λが窓内で動いた」ぶんだけを検出できる。
_DW_MAX_DISPERSION = 3.0
# 同接の水準そのものが窓内で動いている場合もLは代表値にならない。窓の前半後半で
# 時間加重平均を比べ、相対差がこれを超える窓は採らない。
_DW_MAX_LEVEL_DRIFT = 0.35
# sampling欠測の許容。Lは階段保持の時間積分で求めるため多少の間隔ゆらぎには強いが、
# 大穴が空いた窓は同接の水準も到着も追えていない。
_DW_MAX_SAMPLE_GAP_SECONDS = 120.0
_DW_MAX_GAP_SHARE = 0.20
# 配信/配信者を1点として出すのに要る最低数。
_DW_MIN_SESSION_WINDOWS = 3
_DW_MIN_STREAMER_SESSIONS = 2
# 窓を「入れ替わりが速い / 常連が居座る」に分ける、その配信者自身の中央値に対する比。
# 絶対秒ではなく配信者内の相対で切る(total_viewersの定義が非公開で、絶対値を配信者間で
# 比べられないため)。
_DW_CHURN_RATIO = 0.80
_DW_STICKY_RATIO = 1.25
# 時刻別の棒を実勢として読ませてよい最低窓数。これ未満の時刻は値を出しつつ、
# 参考値であることが見て分かるよう画面側で区別する(消すと「その時刻は配信が無い」に
# 見えてしまうため、消さずに弱める)。
_DW_MIN_HOUR_WINDOWS = 20
# 窓を不採用にした理由。payloadは件数の配列で持つのでキー順を固定する。
_DW_REJECT_KEYS = ("short", "gap", "cover", "reset", "noarr", "unstable", "drift")

# 配信の異常検知(session間の水準比較)。core/spike.pyがsession内の瞬間peakを見るのに対し、
# こちらは「その配信者のいつも」と1配信まるごとの水準を比べる。spike.pyの設計判断
# (生の単位では配信ごとに規模が桁で違い横断しきい値が無意味)とは矛盾しない。ここでは
# 配信者自身の履歴を基準に正規化してから比べるため、規模の違いは基準側に吸収される。
_AN_METRICS = ("viewers_med", "coins_per_min", "comments_per_min", "joins_per_min",
               "follow_per_join")
# 露出量の下限。短い配信・分母の小さい比率を「異常」と呼ばないための門。実測で、
# これを入れる前は「31入室中3フォロー=通常の16倍」のような小分母のノイズが上位を
# 占めていた。
_AN_MIN_SPAN_SECONDS = 1800.0   # 観測できたevent範囲がこの秒数未満の配信は対象外
_AN_MIN_EVENTS = 100            # 相互作用eventの最低数
_AN_MIN_JOINS_FOR_RATIO = 200   # follow率の分母。これ未満は比率が桁で暴れる
_AN_MIN_VIEWER_SAMPLES = 30     # 同接の代表値を出すのに要るsample数
# 収集の失敗を「異常な配信」と読まないため、event数は相互作用のみで数える。system は
# collector自身の記録で配信の活動ではない(実測で、全100件がsystemだけの収集失敗
# sessionが「Comment 0件の異常」として上位に出ていた)。
_AN_NON_ACTIVITY_KINDS = ("system",)
# 判定に要る同一配信者の他配信の本数。これ未満は「判定不能」にする。経験p値が到達
# できる最小値は 1/(本数+1) なので、10本を切ると最も外れた配信でもp>0.09にしかならず、
# 有意水準に触れることすらできない。MADも数点では尺度として安定しない。
_AN_MIN_BASELINE = 10
# Benjamini-Hochberg の false discovery rate。
_AN_FDR_Q = 0.10

# session内の水準shift(変化点)検出。順位CUSUM(Pettitt)+ block permutation。
_AN_CP_BIN_SECONDS = 120.0
_AN_CP_MIN_BINS = 12
_AN_CP_MIN_SEGMENT = 4
_AN_CP_PERMUTATIONS = 199
# permutationのblock長。同接系列は自己相関が強く(実測でlag1のACF中央値+0.71)、
# 1点ずつ入れ替える帰無分布では「時間構造があること」自体を検出してしまう
# (実測で57本中48本=84%が有意になった)。ACFが概ね0へ落ちるlag8(16分)を
# blockとして丸ごと入れ替え、短期の自己相関を保った帰無分布にする(同30%)。
_AN_CP_BLOCK_BINS = 8
_AN_CP_ALPHA = 0.05
# 統計的に有意でも、水準が数%動いただけの変化点は運用上の意味が無い。比でこれだけ
# 離れたものを「明確なshift」として扱う。上下の閾値は比の対数で概ね対称にしてある
# (log0.75=-0.29 / log1.35=+0.30)。0.75と1.25のような算術的な対称にすると、
# 下がる側だけが厳しくなる。
_AN_CP_MIN_RATIO_DROP = 0.75
_AN_CP_MIN_RATIO_RISE = 1.35

# 入室後の初回反応までの時間(activation funnel)。1観測 = (session, 人)。
_AC_ACTION_KINDS = ("comment", "like", "gift", "follow", "share")
# likeは平均13.9個/eventのbatch送信(実測: count最大15で頭打ち)で、timestampはbatchが
# flushされた時刻である。したがって初回like時刻は実際の行動より遅く出る(上方bias)。
# 一方でlikeは初回反応の61.8%を占めるため、除くと「反応」の大半が消える。どちらか一方
# では誤読するので、含む系列と除く系列の両方を必ず出す。
_AC_BATCHED_KINDS = ("like",)
# 生存時間の life-table 区間(秒)。初回反応は数十秒〜数時間に広く散るため、短時間側を
# 細かく、長時間側を粗く刻む。最後は上限なしのbin。
_AC_BIN_EDGES = (10, 20, 30, 45, 60, 90, 120, 180, 300, 450,
                 600, 900, 1200, 1800, 2700, 3600, 5400, 7200)
# 画面で「入室からN分後までに反応した割合」を出す時点(秒)。
_AC_HORIZONS = (60, 300, 900, 1800, 3600)
# cluster bootstrapの反復数。sessionを単位に復元抽出してCIを作る(同一配信内の視聴者は
# 独立でないため、人単位のGreenwood分散ではCIが過小に出る)。
_AC_BOOTSTRAP = 200
# CIを出すのに要る最低session数。これ未満はCIを出さない(1 clusterでは分散が測れない)。
_AC_MIN_SESSIONS = 3

# per-session payloadのschema version。計算ロジックを変えたら該当kindを+1すると
# 既存cache行がlazyに再計算される。
CACHE_VERSIONS = {
    "summary": 2,
    "time_index": 3,
    "relations": 1,
    "peri_share": 3,
    "peri_battle": 4,
    "battle_ratio": 2,
    "glove": 3,
    "join_quality": 2,
    "scale_efficiency": 2,
    "retention": 2,
    "join_context": 3,
    "organic": 3,
    "entry_source": 1,
    "battle_flow": 2,
    "coverage": 1,
    "gift_sku": 1,
    "dwell": 1,
    "anomaly": 1,
    "activation": 1,
}
KINDS = tuple(CACHE_VERSIONS)

_SQL_HOUR = "CAST(strftime('%H', {col}, 'unixepoch', 'localtime') AS INTEGER)"
_SQL_DOW = "CAST(strftime('%w', {col}, 'unixepoch', 'localtime') AS INTEGER)"  # 0=日..6=土
# 平日=月〜金(dow 1..5)、休日=土日(dow 0,6)。祝日はdowで判別できないため含めない。
_HOLIDAY_DOW = frozenset({0, 6})
# 15分slot(0..95) = hour*4 + minute//15。organic系(①')で使用。
_SQL_SLOT15 = (
    "(CAST(strftime('%H', {col}, 'unixepoch', 'localtime') AS INTEGER) * 4"
    " + CAST(strftime('%M', {col}, 'unixepoch', 'localtime') AS INTEGER) / 15)"
)
_DAY_SLOTS_15 = 96
# 20分slot(0..71) = hour*3 + minute//20。時間帯index(①)で使用。
_SQL_SLOT20 = (
    "(CAST(strftime('%H', {col}, 'unixepoch', 'localtime') AS INTEGER) * 3"
    " + CAST(strftime('%M', {col}, 'unixepoch', 'localtime') AS INTEGER) / 20)"
)
_DAY_SLOTS_20 = 72
# 時間帯系(①/①')の集計対象は、20分以上継続した配信に限る。20分経つ前に切れた短時間
# 配信は入室傾向の標本として不安定なため除外する。収集中(ended_at未確定)はまだ切れて
# いないため除外しない。
_MIN_SESSION_SECONDS = 20 * 60
# ①のセル1観測は、20分slotの一定割合以上を観測できたものだけ採る。配信の開始/終了が
# slotの端をわずかに跨いだだけの観測は分母が数十秒しかなく、開始直後のjoin burst等で
# レートが系統的に上振れて中央値を歪めるため。
_TI_SLOT_SECONDS = 20 * 60
_TI_MIN_SLOT_COVERAGE = 0.25


# ---- 統計ヘルパー -----------------------------------------------------------
# median/percentileはspike・外れ値に強く、全体解析の「一時的な上振れ下振れに
# 左右されない」方針の中核。Spearman(順位相関)も外れ値・非線形に頑健なため採用。

def _percentile(values: list, pct: float) -> float:
    """線形補間パーセンタイル(numpy非依存)。pctは0..100。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return float(ordered[low] * (1 - frac) + ordered[high] * frac)


def _median(values: list) -> float:
    return _percentile(values, 50.0)


# t分布の0.975分位(df=1..30)。小標本の95%CIを正規近似(1.96)で作ると過小被覆になるため、
# CI半幅の係数はこの表で補正する。df>30は正規近似へ収束。
_T975 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
    15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 21: 2.080,
    22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048,
    29: 2.045, 30: 2.042,
}


def _t_975(df: int) -> float:
    if df < 1:
        return _T975[1]
    return _T975.get(df, 1.96)


def _wilson_ci(k: int, n: int) -> Optional[list]:
    """二項比率のWilson 95%CI(%)。n=0はNone。点推定より小標本で信頼できる区間を返す。"""
    if n <= 0:
        return None
    z = 1.96
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return [round(max(0.0, center - half) * 100, 1), round(min(1.0, center + half) * 100, 1)]


def _rank_average(values: list) -> list:
    """同順位に平均順位を割り当てるランク付け(Spearman用)。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # 1始まり
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def _pearson(xs: list, ys: list) -> Optional[float]:
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    return sxy / (sxx * syy) ** 0.5


def _spearman(xs: list, ys: list) -> Optional[float]:
    """Spearman順位相関: ランクに変換してPearson。外れ値・非線形に頑健。"""
    if len(xs) < 3:
        return None
    return _pearson(_rank_average(xs), _rank_average(ys))


def _spearman_significant(r: Optional[float], n: int, k_controls: int = 0) -> Optional[bool]:
    """Spearman(偏)相関のt近似による両側5%有意判定。df = n - 2 - 制御変数の数。
    小標本の相関は偶然±1近くへ振れやすく、点推定の濃淡だけでは誤読を招くため、
    有意でないセルはfrontendで控えめに表示する。"""
    if r is None:
        return None
    df = n - 2 - k_controls
    if df < 1:
        return False
    denom = 1 - r * r
    if denom <= 1e-12:
        # |r|=1はt近似が発散する。順位のpermutation下で両側p=2/n!なので、
        # p<0.05にはn>=5が必要。
        return n >= 5
    t = abs(r) * ((df / denom) ** 0.5)
    return t > _t_975(df)


def _solve_linear(m: list, v: list) -> Optional[list]:
    """小規模な正規方程式用のGauss消去(部分pivot)。特異ならNone。"""
    n = len(v)
    a = [row[:] + [v[i]] for i, row in enumerate(m)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(a[r][c]))
        if abs(a[p][c]) < 1e-12:
            return None
        a[c], a[p] = a[p], a[c]
        for r in range(n):
            if r != c:
                f = a[r][c] / a[c][c]
                for j in range(c, n + 1):
                    a[r][j] -= f * a[c][j]
    return [a[i][n] / a[i][i] for i in range(n)]


def _ols_residuals(y: list, xs: list) -> Optional[list]:
    """yを説明変数列xs+切片へ最小二乗回帰した残差。多重共線で解けなければNone。"""
    n = len(y)
    cols = [[1.0] * n] + xs
    k = len(cols)
    xtx = [[sum(cols[i][t] * cols[j][t] for t in range(n)) for j in range(k)] for i in range(k)]
    xty = [sum(cols[i][t] * y[t] for t in range(n)) for i in range(k)]
    beta = _solve_linear(xtx, xty)
    if beta is None:
        return None
    return [y[t] - sum(beta[i] * cols[i][t] for i in range(k)) for t in range(n)]


def _partial_spearman(a: list, b: list, controls: list) -> Optional[float]:
    """controls(説明変数列のリスト)の影響を除いたa,bの偏順位相関。ランクをcontrolランク群へ
    重回帰した残差同士のPearson。同接だけでなく配信長も制御できるようにする(相関対象が
    SUM累積のため、長い配信ほど全指標が一斉に膨らむ交絡はpeak同接では説明されない)。"""
    if len(a) < len(controls) + 3:
        return None
    ra, rb = _rank_average(a), _rank_average(b)
    rcs = [_rank_average(c) for c in controls]
    era = _ols_residuals(ra, rcs)
    erb = _ols_residuals(rb, rcs)
    if era is None or erb is None:
        return None
    return _pearson(era, erb)


def _merge_intervals(intervals: list) -> list:
    """[(start,end),...] を重なり/隣接を統合してソート済み非重複区間へ。"""
    clean = [(a, b) for a, b in intervals if b > a]
    if not clean:
        return []
    clean.sort()
    merged = [list(clean[0])]
    for a, b in clean[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def _subtract_intervals(base: list, cut: list) -> list:
    """base区間群から cut区間群を差し引く(base, cut は非重複ソート済み前提でなくてよい)。"""
    base = _merge_intervals(base)
    cut = _merge_intervals(cut)
    result = []
    for a, b in base:
        segments = [(a, b)]
        for ca, cb in cut:
            next_segments = []
            for sa, sb in segments:
                if cb <= sa or ca >= sb:
                    next_segments.append((sa, sb))
                    continue
                if ca > sa:
                    next_segments.append((sa, min(ca, sb)))
                if cb < sb:
                    next_segments.append((max(cb, sa), sb))
            segments = next_segments
        result.extend(s for s in segments if s[1] > s[0])
    return result


def _in_intervals(t: float, intervals: list) -> bool:
    """t が非重複ソート済み区間群のいずれかに入るか(端は[start,end))。"""
    for a, b in intervals:
        if a <= t < b:
            return True
        if a > t:
            break
    return False


def _total_span(intervals: list) -> float:
    return sum(b - a for a, b in intervals)


def concentration(values: list, lorenz_points: int = 40) -> dict:
    """収益/発言の集中度。Gini係数・Lorenz曲線・上位N%シェアを返す。valuesは各ユーザーの
    貢献量(コインやComment数)。少数の重課金/常連にどれだけ偏っているかを定量化する。"""
    vals = sorted(v for v in values if v and v > 0)
    n = len(vals)
    total = sum(vals)
    if n == 0 or total <= 0:
        return {"gini": 0.0, "n_users": n, "total": total, "lorenz": [], "top": []}
    # Gini(昇順): (2*Σ i*x_i)/(n*Σx) - (n+1)/n
    cum_index = sum((i + 1) * v for i, v in enumerate(vals))
    gini = (2 * cum_index) / (n * total) - (n + 1) / n
    # Lorenz曲線(下位から累積): 人口累積比 vs 価値累積比。点は最大lorenz_pointsへ間引く。
    lorenz = [{"p": 0.0, "share": 0.0}]
    keep = max(1, lorenz_points - 1)  # 原点を含めてlorenz_points点に収める
    if n <= keep:
        picks = set(range(1, n + 1))
    else:
        picks = {max(1, round(j * n / keep)) for j in range(1, keep + 1)}
    running = 0
    for i, v in enumerate(vals):
        running += v
        if (i + 1) in picks:
            lorenz.append({"p": round((i + 1) / n, 4), "share": round(running / total, 4)})
    # 上位N%(降順)のシェア。
    desc = vals[::-1]
    top = []
    for pct in (1, 5, 10, 25, 50):
        k = max(1, round(n * pct / 100))
        top.append({"pct": pct, "users": k, "share": round(sum(desc[:k]) / total, 4)})
    return {"gini": round(gini, 4), "n_users": n, "total": total, "lorenz": lorenz, "top": top}


def _collapse_onsets(sorted_bins: list, refractory_bins: int) -> list:
    """昇順bin列から、不応期内の後続を落として初回のみ残す。"""
    out = []
    last = None
    for b in sorted_bins:
        if last is None or (b - last) >= refractory_bins:
            out.append(b)
            last = b
    return out


def _peri_aggregate(clusters: list):
    """baseline差分済み窓のsession別クラスタ群を平均し、95%CI半幅を返す。標本不足は
    (None,None)。同一session内の窓は重複・自己相関があり独立標本ではない(不応期20s ≪
    窓幅250sで、近接onsetの窓は大部分の生データを共有する)ため、素のSE(σ/√n)では
    CIが過小になり有意が出やすく歪む。sessionをクラスタとしたsandwich分散(CR1)+
    t(G-1)で補正する。クラスタが1つしか無いときは補正不能なので素のSE+t(n-1)に落ちる
    (その場合は過小気味である点に注意)。"""
    groups = [c for c in clusters if c]
    windows = [w for c in groups for w in c]
    n = len(windows)
    if n < _PERI_MIN_EVENTS:
        return None, None
    length = len(windows[0])
    mean = [sum(w[i] for w in windows) / n for i in range(length)]
    if n < 2:
        return mean, [0.0] * length
    ng = len(groups)
    ci = []
    if ng >= 2:
        t = _t_975(ng - 1)
        for i in range(length):
            s = 0.0
            for g in groups:
                e = sum(w[i] - mean[i] for w in g)
                s += e * e
            var_mean = (ng / (ng - 1)) * s / (n * n)
            ci.append(t * (var_mean ** 0.5))
    else:
        t = _t_975(n - 1)
        for i in range(length):
            var = sum((w[i] - mean[i]) ** 2 for w in windows) / (n - 1)
            ci.append(t * (var ** 0.5) / (n ** 0.5))
    return mean, ci


def _mad(values: list, center: Optional[float] = None) -> float:
    """中央絶対偏差。外れ値そのものを探すので、baselineは平均・標準偏差では作れない
    (検出したい1本が自分でbaselineを膨らませ、自分を平凡に見せてしまう)。"""
    if not values:
        return 0.0
    med = _median(values) if center is None else center
    return _median([abs(v - med) for v in values])


def _robust_z(value: float, baseline: list) -> Optional[float]:
    """baseline(自分を除いた同一配信者の他配信)に対する頑健z。

    1.4826はMADを正規分布の標準偏差と同じ尺度へ揃える定数。MAD=0(他配信が同じ値ばかり)
    では尺度が定義できないのでNone(0除算を避けるために小さい数を入れると、わずかな差が
    無限大のzに化ける)。"""
    if len(baseline) < 2:
        return None
    med = _median(baseline)
    mad = _mad(baseline, med)
    if mad <= 0:
        return None
    return (value - med) / (1.4826 * mad)


def _empirical_p(value: float, baseline: list) -> Optional[float]:
    """baselineの中で「中央値からこれ以上離れている」割合(両側)。

    分布を仮定しない。正規近似のp値を使わないのは、実測でこのdataの裾が正規より
    桁違いに重いため(|z|>3で約13倍、|z|>4で約375倍)。正規のp値を当てると、
    ただの重い裾を「極めて有意な異常」として大量に出してしまう。
    到達できる最小値は 1/(n+1) で、baselineの本数が検出力の上限を決める。"""
    if not baseline:
        return None
    med = _median(baseline)
    dev = abs(value - med)
    at_least = sum(1 for v in baseline if abs(v - med) >= dev)
    return (at_least + 1) / (len(baseline) + 1)


def benjamini_hochberg(pvalues: list) -> list:
    """BH法のq値(FDR調整済みp)。入力と同じ並びで返す。

    指標×配信の数だけ検定するため、素のp値をそのまま閾値に当てると偽陽性が積み上がる。
    q値は単調になるよう後ろから累積minを取る(BHの標準手順)。"""
    n = len(pvalues)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: pvalues[i])
    out = [1.0] * n
    running = 1.0
    for rank in range(n - 1, -1, -1):
        i = order[rank]
        running = min(running, pvalues[i] * n / (rank + 1))
        out[i] = min(1.0, running)
    return out


def _rank_cusum(rank_values: list, min_segment: int):
    """順位CUSUMの最大絶対値と分割位置(Pettittの変化点統計量)。

    水準そのものではなく順位で見るのは、1本の高額ギフトや瞬間的なspikeで変化点が
    決まらないようにするため。分割位置の前後には最低segment長を要求する
    (端で切ると片側が数点になり、統計量が不安定になる)。"""
    n = len(rank_values)
    if n < 2 * min_segment:
        return 0.0, None
    mean = sum(rank_values) / n
    best, at, running = 0.0, None, 0.0
    for k in range(n - 1):
        running += rank_values[k] - mean
        if k + 1 < min_segment or n - (k + 1) < min_segment:
            continue
        if abs(running) > best:
            best, at = abs(running), k + 1
    return best, at


def _block_shuffled(seq: list, block: int, rng) -> list:
    """circular block permutation。連続blockを丸ごと並べ替え、短期の自己相関を保つ。"""
    n = len(seq)
    out = []
    for _ in range((n + block - 1) // block):
        start = rng.randrange(n)
        out.extend(seq[(start + k) % n] for k in range(block))
    return out[:n]


def _identity_digest(identity_key: str) -> str:
    """identity_keyをcache payload用の短いdigestへ。session跨ぎで同一人物を突き合わせる
    ためだけに使うので、決定論的でありさえすればよい(暗号用途ではない)。"""
    return hashlib.blake2b(
        identity_key.encode("utf-8"), digest_size=_SKU_IDENTITY_DIGEST_BYTES
    ).hexdigest()


def _chunked(seq: list, size: int = 500):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


# ---- per-session payload計算 -------------------------------------------------
# 各関数は1 sessionの中間集計(JSON化可能なdict)を返す。終了済みsessionでは結果が
# 不変になるよう、session内で閉じた情報+その時点で確定済みの外部情報のみを使う。

def _observed_span(conn, sess: dict) -> float:
    """この配信を実際に観測できた秒数。

    bucketsの本数×bucket幅を稼働秒に使わない。bucketsはfinalize_sessionでしか書かれず、
    切断で終わった配信(実測で110本中43本)には1行も残らないため、稼働秒がまるごと0に
    なってしまう。eventsとviewer_samplesは収集中に永続化されるので、そちらの実観測範囲を
    使えば全配信で測れる。終端はended_at、収集中は最後に何かが届いた時刻。"""
    row = conn.execute(
        "SELECT MAX(t) AS last FROM ("
        "  SELECT MAX(time) AS t FROM events WHERE session_id = ?"
        "  UNION ALL SELECT MAX(time) FROM viewer_samples WHERE session_id = ?)",
        (sess["id"], sess["id"]),
    ).fetchone()
    end = sess["ended_at"]
    if end is None:
        end = row["last"] if row and row["last"] is not None else sess["started_at"]
    return max(0.0, end - sess["started_at"])


def _payload_summary(conn, sess: dict) -> dict:
    row = conn.execute(
        "SELECT COALESCE(SUM(kind = 'join'), 0) AS j,"
        " COALESCE(SUM(CASE WHEN kind = 'gift' THEN diamonds ELSE 0 END), 0) AS d,"
        " COALESCE(SUM(kind = 'comment'), 0) AS c"
        " FROM events WHERE session_id = ?",
        (sess["id"],),
    ).fetchone()
    seconds = _observed_span(conn, sess)
    bucket_seconds = sess["bucket_seconds"] or 0
    return {
        # nbは「bucket表の行数」ではなく、観測できた秒数をbucket幅で割った相当数。
        # 意味を揃えたまま、bucketsの無い配信でも測れるようにする。
        "nb": int(seconds // bucket_seconds) if bucket_seconds > 0 else 0,
        "act": round(seconds, 1),
        "j": row["j"],
        "d": row["d"],
        "c": row["c"],
    }


def _payload_time_index(conn, sess: dict) -> dict:
    """(date,slot20)ごとの全指標bucket合計。1観測 = (session,date,20分slot)。"""
    rows = conn.execute(
        "SELECT CAST(strftime('%w', start, 'unixepoch', 'localtime') AS INTEGER) AS dow,"
        f" {_SQL_SLOT20.format(col='start')} AS slot,"
        " COUNT(*) AS nb, SUM(joins) AS joins, SUM(comments) AS comments,"
        " SUM(diamonds) AS diamonds, SUM(likes) AS likes, SUM(follows) AS follows"
        " FROM buckets WHERE session_id = ?"
        " GROUP BY strftime('%Y-%m-%d', start, 'unixepoch', 'localtime'), slot",
        (sess["id"],),
    ).fetchall()
    return {
        "cells": [
            [r["dow"], r["slot"], r["nb"], r["joins"] or 0, r["comments"] or 0,
             r["diamonds"] or 0, r["likes"] or 0, r["follows"] or 0]
            for r in rows
        ]
    }


def _payload_relations(conn, sess: dict) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS n, SUM(joins) AS joins, SUM(comments) AS comments,"
        " SUM(diamonds) AS diamonds, SUM(likes) AS likes, SUM(follows) AS follows,"
        " MAX(viewers) AS viewers"
        " FROM buckets WHERE session_id = ?",
        (sess["id"],),
    ).fetchone()
    return {m: row[m] for m in RELATION_METRICS} | {"n": row["n"]}


def _payload_peri(conn, sess: dict, treatment: str) -> dict:
    """event周辺の入室uplift窓(session内)。生joinイベントを固定binへ再構築し、各onset窓を
    baseline(窓先頭)で差分する。同時に、onsetから離れたbinを系統抽出したplacebo(帰無)窓を
    作り、見かけの山が「活発な時間帯」由来でないかの対照に使う。"""
    bin_s = _PERI_BIN_SECONDS
    pre, post = _PERI_PRE_BINS, _PERI_POST_BINS
    win_len = pre + post + 1
    sid = sess["id"]
    times = [
        r["time"]
        for r in conn.execute(
            "SELECT time FROM events WHERE session_id = ? AND kind = 'join'", (sid,)
        ).fetchall()
    ]
    if not times:
        return {"q": 0}
    lo = int(min(times) // bin_s)
    hi = int(max(times) // bin_s)
    width = hi - lo + 1
    if width < win_len + 1:
        return {"q": 0}
    counts = [0] * width
    for t in times:
        counts[int(t // bin_s) - lo] += 1
    # treatment onset源(share event / battle marker)。受信時刻で統一。
    if treatment == "share":
        refractory = _PERI_SHARE_REFRACTORY_SECONDS
        onset_rows = conn.execute(
            "SELECT time FROM events WHERE session_id = ? AND kind = 'share'", (sid,)
        ).fetchall()
    else:
        refractory = _PERI_BATTLE_REFRACTORY_SECONDS
        # onsetはmarker受信時刻ではなくbattle_settingの実開始時刻を使う。markerは
        # begin/update/FINISHの受信毎に発火するため、begin→FINISHが不応期(300s)を
        # 超える長尺battleではFINISHが同一battle内の第2 onsetとして採用され、
        # battle終盤の高活動区間がbaselineに入って窓が歪む。
        onset_rows = []
        for br in conn.execute(
            "SELECT data_json FROM battles WHERE session_id = ?", (sid,)
        ).fetchall():
            try:
                bt = json.loads(br["data_json"])
            except (ValueError, TypeError):
                continue
            st = bt.get("start_time")
            if st is not None:
                onset_rows.append({"time": st})
    refractory_bins = max(1, int(refractory // bin_s))
    # cold-open除外: 開始直後に始まるonsetはcold-start push+share洪水と交絡するため落とす。
    cold_cut_bin = int((sess["started_at"] + _PERI_COLD_OPEN_SECONDS) // bin_s)
    onset_abs = _collapse_onsets(
        sorted({
            int(r["time"] // bin_s)
            for r in onset_rows
            if int(r["time"] // bin_s) >= cold_cut_bin
        }),
        refractory_bins,
    )
    onset_bins = sorted({ob - lo for ob in onset_abs if lo <= ob <= hi})

    def _extract(center: int):
        if center - pre < 0 or center + post >= width:
            return None
        seg = counts[center - pre : center + post + 1]
        base = sum(seg[:_PERI_BASELINE_BINS]) / _PERI_BASELINE_BINS
        return [v - base for v in seg]

    ev_windows = []
    real = []
    for ob in onset_bins:
        w = _extract(ob)
        if w is not None:
            ev_windows.append(w)
            real.append(ob)
    pl_windows = []
    if real:
        # placebo: onsetからguard bin以上離れたeligible binを系統(等間隔)抽出。
        # 自treatmentの近傍に加え、他の入室ドライバ(share/battle/portal/宝箱/コラボ)の
        # 近傍・窓も除外する。これらの区間はjoinが押し上がるため、placebo(帰無)に選ぶと
        # 比較帯が汚染され、本物の効果が有意になりにくい方向へ歪む。
        confound_rows = conn.execute(
            "SELECT time FROM events WHERE session_id = ? AND kind = 'share'"
            " UNION ALL"
            " SELECT time FROM markers"
            "   WHERE session_id = ? AND kind IN ('battle', 'portal', 'envelope')",
            (sid, sid),
        ).fetchall()
        guard = pre + post
        forbidden: set = set()
        # cold-open区間はplaceboにも使わない。
        if cold_cut_bin - lo > 0:
            forbidden.update(range(0, cold_cut_bin - lo))
        for ob in onset_bins:
            forbidden.update(range(ob - guard, ob + guard + 1))
        for cr in confound_rows:
            cb = int(cr["time"] // bin_s) - lo
            forbidden.update(range(cb - guard, cb + guard + 1))
        # コラボ(非BattleのLinkMic)窓中もjoinが持ち上がるため窓全体+guardを除外する。
        for cw in conn.execute(
            "SELECT start, end FROM collab_windows WHERE session_id = ?", (sid,)
        ).fetchall():
            cs = int(cw["start"] // bin_s) - lo
            ce = (int(cw["end"] // bin_s) - lo) if cw["end"] is not None else (hi - lo)
            forbidden.update(range(cs - guard, ce + guard + 1))
        eligible = [c for c in range(pre, width - post) if c not in forbidden]
        if eligible:
            want = min(len(real) * _PERI_PLACEBO_RATIO, len(eligible))
            stride = max(1, len(eligible) // want) if want else 1
            for c in eligible[::stride][:want]:
                w = _extract(c)
                if w is not None:
                    pl_windows.append(w)
    return {"q": 1, "j": len(times), "b": width, "ev": ev_windows, "pl": pl_windows}


def _payload_peri_share(conn, sess: dict) -> dict:
    return _payload_peri(conn, sess, "share")


def _payload_peri_battle(conn, sess: dict) -> dict:
    return _payload_peri(conn, sess, "battle")


def _payload_battle_ratio(conn, sess: dict) -> dict:
    """Battle窓内 vs 窓外のレート比(session内の各battle)。「窓外」は全battleの時間と
    eventを除いた真の平時とする(あるbattleの外に他battleの盛り上がりを含めると、
    基準が持ち上がって倍率が過小に出るため)。battle_idの横断dedupはreduce側で行う
    ため、窓が有効な全battleを順序どおり記録する。"""
    sid = sess["id"]
    s_start = sess["started_at"]
    s_end = sess["ended_at"]
    rows = conn.execute(
        "SELECT battle_id AS bid, data_json AS d FROM battles WHERE session_id = ?"
        " ORDER BY rowid",
        (sid,),
    ).fetchall()
    battles = []
    parsed = []
    for br in rows:
        try:
            battle = json.loads(br["d"])
        except (ValueError, TypeError):
            continue
        start_time = battle.get("start_time")
        end_time = battle.get("end_time")
        if start_time is None or end_time is None or end_time <= start_time:
            continue
        rec = {"bid": br["bid"], "up": None}
        battles.append(rec)
        parsed.append((rec, start_time, end_time))
    if s_end is None or not parsed:
        # 収集中sessionは窓外時間が確定しない。確定後(finalize)に集計する。
        return {"battles": battles}
    duration = s_end - s_start
    union = _merge_intervals(
        [
            (max(st, s_start), min(en, s_end))
            for _, st, en in parsed
            if min(en, s_end) > max(st, s_start)
        ]
    )
    outside = duration - _total_span(union)
    if outside <= 0:
        return {"battles": battles}
    trows = conn.execute(
        "SELECT kind, COUNT(*) AS c, COALESCE(SUM(diamonds), 0) AS d"
        " FROM events WHERE session_id = ? GROUP BY kind",
        (sid,),
    ).fetchall()
    totals = {r["kind"]: {"c": r["c"], "d": r["d"]} for r in trows}
    # 全battle窓union内のevent量。窓外量 = 総量 - union内量。
    union_stat: dict = {}
    for a, b in union:
        for r in conn.execute(
            "SELECT kind, COUNT(*) AS c, COALESCE(SUM(diamonds), 0) AS d"
            " FROM events WHERE session_id = ? AND time >= ? AND time < ? GROUP BY kind",
            (sid, a, b),
        ).fetchall():
            u = union_stat.setdefault(r["kind"], {"c": 0, "d": 0})
            u["c"] += r["c"]
            u["d"] += r["d"]
    for rec, start_time, end_time in parsed:
        inside = min(end_time, s_end) - max(start_time, s_start)
        if inside <= 0:
            continue
        irows = conn.execute(
            "SELECT kind, COUNT(*) AS c, COALESCE(SUM(diamonds), 0) AS d"
            " FROM events WHERE session_id = ? AND time >= ? AND time < ? GROUP BY kind",
            (sid, start_time, end_time),
        ).fetchall()
        inside_stat = {r["kind"]: {"c": r["c"], "d": r["d"]} for r in irows}
        up = {}
        for metric, kind in (("joins", "join"), ("comments", "comment"), ("follows", "follow")):
            in_c = inside_stat.get(kind, {}).get("c", 0)
            out_c = totals.get(kind, {}).get("c", 0) - union_stat.get(kind, {}).get("c", 0)
            in_rate = in_c / inside
            out_rate = out_c / outside
            up[metric] = (in_rate / out_rate) if out_rate > 0 else None
        in_d = inside_stat.get("gift", {}).get("d", 0)
        out_d = totals.get("gift", {}).get("d", 0) - union_stat.get("gift", {}).get("d", 0)
        in_dr = in_d / inside
        out_dr = out_d / outside
        up["diamonds"] = (in_dr / out_dr) if out_dr > 0 else None
        rec["up"] = up
    return {"battles": battles}


def _payload_glove(conn, sess: dict) -> dict:
    """自陣グローブ窓中ギフトの(単価, crit)記録。critは三値(1=crit / 0=通常 /
    None=判定不能: scoreのdelta厳密一致が一意に成立しなかったgift)で、判定不能は
    reduce側で分母に入れない。単価不明分のgift_id→単価解決は後から観測が増える
    ほど解けるためreduce側(全期間の単価表)で行う。"""
    rows = conn.execute(
        "SELECT battle_id AS bid, data_json AS d FROM battles WHERE session_id = ?"
        " ORDER BY rowid",
        (sess["id"],),
    ).fetchall()
    battles = []
    for row in rows:
        rec = {"bid": row["bid"], "ok": 0}
        battles.append(rec)
        try:
            battle = json.loads(row["d"])
        except (ValueError, TypeError):
            continue
        rec["ok"] = 1
        rec["w"] = sum(1 for w in (battle.get("glove_windows") or []) if w.get("own"))
        rec["ev"] = [
            [
                ev.get("gift_id"),
                ev.get("coins"),
                None if ev.get("crit") is None else (1 if ev.get("crit") else 0),
            ]
            for ev in (battle.get("glove_events") or [])
        ]
    return {"battles": battles}


def _payload_join_quality(conn, sess: dict) -> dict:
    """時間帯別の入室人数(時間帯ごとのユニークidentity)と、うち初見(users.first_seenが
    当該session開始以降)の人数。join eventは同一人物の離脱→再入室で多重発火するため、
    人数はDISTINCT identityで数える。identityが取れない/users未登録のjoinは新規・常連の
    どちらにも分類できないので人数に混ぜず、件数だけ別掲する(excl)。"""
    rows = conn.execute(
        "SELECT hour,"
        " SUM(CASE WHEN fs IS NOT NULL AND fs >= ? THEN 1 ELSE 0 END) AS newcomers,"
        " SUM(CASE WHEN fs IS NULL THEN 1 ELSE 0 END) AS unknown,"
        " COUNT(*) AS total"
        " FROM ("
        f"  SELECT DISTINCT e.identity_key, {_SQL_HOUR.format(col='e.time')} AS hour,"
        "   u.first_seen AS fs"
        "   FROM events e LEFT JOIN users u ON u.identity_key = e.identity_key"
        "   WHERE e.session_id = ? AND e.kind = 'join' AND e.identity_key != ''"
        " ) GROUP BY hour",
        (sess["started_at"], sess["id"]),
    ).fetchall()
    anon = conn.execute(
        "SELECT COUNT(*) AS c FROM events"
        " WHERE session_id = ? AND kind = 'join' AND identity_key = ''",
        (sess["id"],),
    ).fetchone()["c"]
    excl = (anon or 0) + sum(r["unknown"] or 0 for r in rows)
    return {
        "h": [
            [r["hour"], r["newcomers"] or 0, (r["total"] or 0) - (r["unknown"] or 0)]
            for r in rows
        ],
        "excl": excl,
    }


def _payload_scale_efficiency(conn, sess: dict) -> dict:
    """規模(平均同接)と効率の分子分母。効率の分母は視聴量(viewer-minutes=Σ同接×bucket分)。
    Peak(瞬間値)で割ると総コインが配信の長さに比例して膨らむ分が残り「1視聴あたり」に
    ならないため、時間で積分した視聴量を使う。"""
    row = conn.execute(
        "SELECT MAX(viewers) AS p, AVG(viewers) AS a, COALESCE(SUM(viewers), 0) AS v"
        " FROM buckets WHERE session_id = ?",
        (sess["id"],),
    ).fetchone()
    coins = conn.execute(
        "SELECT COALESCE(SUM(diamonds), 0) AS c FROM events"
        " WHERE session_id = ? AND kind = 'gift'",
        (sess["id"],),
    ).fetchone()["c"]
    vmin = (row["v"] or 0) * (sess["bucket_seconds"] or 0) / 60.0
    return {
        "peak": row["p"] or 0,
        "avgv": round(row["a"] or 0.0, 2),
        "vmin": round(vmin, 1),
        "coins": coins or 0,
    }


def _dwell_windows(samples: list, comment_times: list):
    """viewer_samplesの並びを固定幅の窓へ切り、Little則が使える窓だけを返す。

    samplesは (time, viewers, total_viewers) の時刻昇順。返り値は
    (採用窓のlist, 不採用理由のcounter dict)。採用窓は
    [時刻(hour), L(時間加重平均同接), 到着数, 実観測秒, 窓内Comment数]。

    Lは単純平均ではなく階段保持の時間積分にする。sampling間隔は一定ではなく
    (中央値2.6秒に対しp99は33秒)、単純平均では間隔の詰まった区間が過大に効く。
    時間積分ならviewer-minutesと同じ定義になり、間隔のゆらぎに影響されない。"""
    rejects = {k: 0 for k in _DW_REJECT_KEYS}
    windows = []
    n = len(samples)
    i = 0
    while i < n:
        head = samples[i][0]
        j = i
        while j < n and samples[j][0] < head + _DW_WINDOW_SECONDS:
            j += 1
        seg = samples[i:j]
        i = j
        if len(seg) < 2:
            rejects["short"] += 1
            continue
        span = seg[-1][0] - seg[0][0]
        if (span < _DW_WINDOW_SECONDS * _DW_MIN_WINDOW_FILL
                or span < _DW_MIN_SUBBINS * _DW_SUBBIN_SECONDS):
            rejects["short"] += 1
            continue
        gaps = [b[0] - a[0] for a, b in zip(seg, seg[1:])]
        if max(gaps) > _DW_MAX_SAMPLE_GAP_SECONDS:
            rejects["gap"] += 1
            continue
        stale = sum(g for g in gaps if g > _DW_SUBBIN_SECONDS)
        if stale / span > _DW_MAX_GAP_SHARE:
            rejects["cover"] += 1
            continue
        totals = [s[2] for s in seg]
        # 累積counterが減る窓はsession境界かcounterの作り直し。差分を到着数と読めない。
        if any(b < a for a, b in zip(totals, totals[1:])):
            rejects["reset"] += 1
            continue
        arrivals = totals[-1] - totals[0]
        if arrivals < _DW_MIN_ARRIVALS:
            rejects["noarr"] += 1
            continue
        area = sum(a[1] * (b[0] - a[0]) for a, b in zip(seg, seg[1:]))
        level = area / span
        if level <= 0:
            rejects["noarr"] += 1
            continue
        # 小binごとの到着数を累積counterのbin端の値から差分で取る。
        base = seg[0][0]
        n_bins = int(span // _DW_SUBBIN_SECONDS)
        edges = []
        k = 0
        for b in range(n_bins + 1):
            edge = base + b * _DW_SUBBIN_SECONDS
            while k + 1 < len(seg) and seg[k + 1][0] <= edge:
                k += 1
            edges.append(seg[k][2])
        counts = [b - a for a, b in zip(edges, edges[1:])]
        if len(counts) < _DW_MIN_SUBBINS:
            rejects["short"] += 1
            continue
        mean_count = sum(counts) / len(counts)
        if mean_count <= 0:
            rejects["noarr"] += 1
            continue
        variance = sum((c - mean_count) ** 2 for c in counts) / (len(counts) - 1)
        if variance / mean_count > _DW_MAX_DISPERSION:
            rejects["unstable"] += 1
            continue
        mid = base + span / 2
        first_area = sum(
            a[1] * (b[0] - a[0]) for a, b in zip(seg, seg[1:]) if a[0] < mid
        )
        first_span = sum((b[0] - a[0]) for a, b in zip(seg, seg[1:]) if a[0] < mid)
        second_span = span - first_span
        if first_span <= 0 or second_span <= 0:
            rejects["short"] += 1
            continue
        drift = abs((area - first_area) / second_span - first_area / first_span) / level
        if drift > _DW_MAX_LEVEL_DRIFT:
            rejects["drift"] += 1
            continue
        comments = bisect.bisect_left(comment_times, seg[-1][0]) - bisect.bisect_left(
            comment_times, seg[0][0]
        )
        hour = int(time.localtime(base).tm_hour)
        windows.append([hour, round(level, 3), arrivals, round(span, 1), comments])
    return windows, rejects


def _payload_dwell(conn, sess: dict) -> dict:
    """滞在時間(Little則)の素材。定常とみなせる窓ごとの同接水準・到着数・Comment数。

    配信まるごとの粗い推定値(視聴量÷総来場者)も併せて持つ。分子の視聴量は⑧規模vs効率と
    同じ定義でなければならないため、_payload_scale_efficiencyをそのまま呼んで揃える
    (viewer-minutesの定義を二重に持つと、同じ画面の2箇所で違う視聴量が出る)。"""
    sid = sess["id"]
    samples = [
        (r["time"], r["viewers"], r["total_viewers"])
        for r in conn.execute(
            "SELECT time, viewers, total_viewers FROM viewer_samples"
            " WHERE session_id = ? ORDER BY time",
            (sid,),
        )
        if r["total_viewers"] is not None
    ]
    comment_times = [
        r["time"] for r in conn.execute(
            "SELECT time FROM events WHERE session_id = ? AND kind = 'comment'"
            " ORDER BY time",
            (sid,),
        )
    ]
    windows, rejects = _dwell_windows(samples, comment_times)
    scale = _payload_scale_efficiency(conn, sess)
    # 全体の到着数は「窓に切らない」session全体の累積counterの伸び。窓の合計とは
    # 一致しない(不採用窓ぶんが入るため)ので別に持つ。
    arrivals = 0
    if len(samples) >= 2:
        arrivals = max(0, samples[-1][2] - samples[0][2])
    joins = conn.execute(
        "SELECT COUNT(*) AS c FROM events WHERE session_id = ? AND kind = 'join'",
        (sid,),
    ).fetchone()["c"]
    return {
        "w": windows,
        "rej": [rejects[k] for k in _DW_REJECT_KEYS],
        "vmin": scale["vmin"],
        "arr": arrivals,
        "jn": joins or 0,
        "avgv": scale["avgv"],
    }


def _payload_anomaly(conn, sess: dict) -> dict:
    """異常検知の素材: 1配信ぶんの水準指標と、session内の水準shift(変化点)。

    水準指標はbucketsではなくevents/viewer_samplesから作る。bucketsはfinalize_session
    でしか書かれず、切断で終わった配信(status=disconnected)には残らない。実測でbuckets
    を持つのは109本中67本で、欠けるのは長時間・不安定な配信に偏るため、bucketsを基準に
    すると母集団が系統的に歪む(events基準なら同じ配信者で16本→49本になる)。"""
    sid = sess["id"]
    placeholders = ", ".join("?" * len(_AN_NON_ACTIVITY_KINDS))
    agg = conn.execute(
        "SELECT COUNT(*) AS n, MIN(time) AS t0, MAX(time) AS t1,"
        " COALESCE(SUM(CASE WHEN kind = 'gift' THEN diamonds ELSE 0 END), 0) AS coins,"
        " COALESCE(SUM(kind = 'comment'), 0) AS comments,"
        " COALESCE(SUM(kind = 'join'), 0) AS joins,"
        " COALESCE(SUM(kind = 'follow'), 0) AS follows"
        f" FROM events WHERE session_id = ? AND kind NOT IN ({placeholders})",
        (sid, *_AN_NON_ACTIVITY_KINDS),
    ).fetchone()
    samples = [
        (r["time"], r["viewers"]) for r in conn.execute(
            "SELECT time, viewers FROM viewer_samples WHERE session_id = ? ORDER BY time",
            (sid,),
        )
    ]
    span = (agg["t1"] - agg["t0"]) if agg["t0"] is not None else 0.0
    metrics = {}
    if (agg["n"] or 0) >= _AN_MIN_EVENTS and span >= _AN_MIN_SPAN_SECONDS:
        minutes = span / 60.0
        metrics["coins_per_min"] = round((agg["coins"] or 0) / minutes, 4)
        metrics["comments_per_min"] = round((agg["comments"] or 0) / minutes, 4)
        metrics["joins_per_min"] = round((agg["joins"] or 0) / minutes, 4)
        if (agg["joins"] or 0) >= _AN_MIN_JOINS_FOR_RATIO:
            metrics["follow_per_join"] = round((agg["follows"] or 0) / agg["joins"], 6)
        if len(samples) >= _AN_MIN_VIEWER_SAMPLES:
            metrics["viewers_med"] = _median([v for _t, v in samples])
    return {
        "m": metrics,
        "span": round(span, 1),
        "ev": agg["n"] or 0,
        "cp": _changepoint(sid, samples),
    }


def _changepoint(session_id: int, samples: list) -> Optional[dict]:
    """session内の水準shift。順位CUSUMで最も割れる時点を採り、block permutationで
    「配信のいつもの起伏でもこの程度は出る」かを確かめる。

    乱数はsession_idで固定する。payloadはcacheへ載るので、同じ配信を再計算したときに
    違うp値が出てはならない。"""
    if len(samples) < 2:
        return None
    base = samples[0][0]
    bins: dict = {}
    for t, viewers in samples:
        bins.setdefault(int((t - base) // _AN_CP_BIN_SECONDS), []).append(viewers)
    # 観測の穴はbinごと落とす(0で埋めると、切断を「同接0への急落」として検出する)。
    index = sorted(bins)
    values = [_median(bins[i]) for i in index]
    if len(values) < _AN_CP_MIN_BINS:
        return None
    rank_values = _rank_average(values)
    stat, at = _rank_cusum(rank_values, _AN_CP_MIN_SEGMENT)
    if at is None:
        return None
    rng = random.Random(session_id)
    exceed = sum(
        1 for _ in range(_AN_CP_PERMUTATIONS)
        if _rank_cusum(_block_shuffled(rank_values, _AN_CP_BLOCK_BINS, rng),
                       _AN_CP_MIN_SEGMENT)[0] >= stat
    )
    before = _median(values[:at])
    after = _median(values[at:])
    return {
        "at": round(base + index[at] * _AN_CP_BIN_SECONDS, 1),
        "before": round(before, 2),
        "after": round(after, 2),
        "p": round((exceed + 1) / (_AN_CP_PERMUTATIONS + 1), 4),
        "bins": len(values),
    }


def _ac_bin_index(seconds: float) -> int:
    """秒をlife-tableのbin indexへ。上限を超えたものは最後のbinへ入れる。"""
    return bisect.bisect_right(_AC_BIN_EDGES, seconds)


def _payload_activation(conn, sess: dict) -> dict:
    """入室後の初回反応までの時間(life-table形式)と、入室の取りこぼしを測る材料。

    1観測 = (この配信, 1人)。入室時刻が分からないと潜時の原点が無いので、母集団は
    「join eventが記録された人」に限る。ただし実測では、行動した人の35%はjoinが
    記録されておらず、しかもその層はgift率が高い(81% vs 55%)。母集団が engaged 側へ
    欠けているぶんは reduce 側で被覆として返し、画面で但し書きにする。

    既存の_payload_organicは同じ材料を読みながらengagedをboolのsetにしてしまい潜時を
    捨てている。あちらはorganic weightの入力で用途が違うため、payloadは分ける。"""
    # NON_IDENTITY_KEYSはstorage側の単一定義。storageがanalyticsをimportしているため
    # module levelでimportすると循環するので、呼び出し時に解決する。
    from tictok.storage import NON_IDENTITY_KEYS

    sid = sess["id"]
    kinds = ("join",) + _AC_ACTION_KINDS
    rows = conn.execute(
        "SELECT time AS t, kind, identity_key AS k FROM events"
        f" WHERE session_id = ? AND kind IN ({','.join('?' * len(kinds))})"
        f" AND identity_key NOT IN ({','.join('?' * len(NON_IDENTITY_KEYS))})"
        " ORDER BY time",
        (sid, *kinds, *NON_IDENTITY_KEYS),
    ).fetchall()

    first_join: dict = {}
    first_any: dict = {}
    first_slow: dict = {}   # batch送信のkindを除いた初回反応
    gifted: set = set()
    actors: set = set()
    last_seen = sess["started_at"]
    for r in rows:
        key, kind, t = r["k"], r["kind"], r["t"]
        if t > last_seen:
            last_seen = t
        if kind == "join":
            first_join.setdefault(key, t)
            continue
        actors.add(key)
        if kind == "gift":
            gifted.add(key)
        first_any.setdefault(key, t)
        if kind not in _AC_BATCHED_KINDS:
            first_slow.setdefault(key, t)

    end = sess["ended_at"] if sess["ended_at"] is not None else last_seen
    n_bins = len(_AC_BIN_EDGES) + 1
    with_batched = [[0, 0] for _ in range(n_bins)]
    without_batched = [[0, 0] for _ in range(n_bins)]

    for key, joined in first_join.items():
        horizon = end - joined
        if horizon <= 0:
            continue
        for table, firsts in ((with_batched, first_any), (without_batched, first_slow)):
            acted = firsts.get(key)
            # 入室より前の反応は、その入室に対する反応ではない(再入室した常連など)。
            # 潜時が負になるので観測から外し、打ち切りとして扱う。
            if acted is not None and acted >= joined:
                table[_ac_bin_index(acted - joined)][0] += 1
            else:
                table[_ac_bin_index(horizon)][1] += 1

    joined_keys = set(first_join)
    return {
        "n": len(first_join),
        "wl": with_batched,
        "nl": without_batched,
        # 被覆: 行動した人のうち何人にjoinが残っているか。gift率は欠落の偏りの証拠。
        "act": len(actors),
        "act_j": len(actors & joined_keys),
        "gift": len(gifted),
        "gift_j": len(gifted & joined_keys),
    }


def _payload_retention(conn, sess: dict) -> dict:
    """時刻別の入室/同接と、入室押し上げ推定の分子分母。同接の変化を「入室があった
    bucket(jb)」と「入室のないbucket(nb)」に分けて持ち、reduce側で平常の増減(drift=
    nbの平均変化)を差し引く。入室bucketの変化だけを合算すると、退室が支配的な静かな
    局面が系統的に脱落して押し上げが過大に出るため。"""
    rows = conn.execute(
        f"SELECT joins, viewers, {_SQL_HOUR.format(col='start')} AS hour"
        " FROM buckets WHERE session_id = ? ORDER BY start",
        (sess["id"],),
    ).fetchall()
    hours = [[0, 0, 0] for _ in range(24)]  # [joins, viewers_sum, viewers_cnt]
    jb_delta = jb_joins = jb_cnt = 0
    nb_delta = nb_cnt = 0
    prev_viewers = None
    for r in rows:
        v = r["viewers"] or 0
        j = r["joins"] or 0
        h = r["hour"]
        hours[h][0] += j
        hours[h][1] += v
        hours[h][2] += 1
        if prev_viewers is None:
            prev_viewers = v
            continue
        delta = v - prev_viewers
        prev_viewers = v
        if j > 0:
            jb_delta += delta
            jb_joins += j
            jb_cnt += 1
        else:
            nb_delta += delta
            nb_cnt += 1
    return {"h": hours, "jb": [jb_delta, jb_joins, jb_cnt], "nb": [nb_delta, nb_cnt]}


def _payload_join_context(conn, sess: dict) -> dict:
    """Battle中 / コラボ(非BattleのLinkMic)中 / 平時 の秒数と入室数(session内)。"""
    sid = sess["id"]
    s_start = sess["started_at"]
    # 収集中(ended_atなし)は実観測範囲で終端を近似する。bucketsは切断で終わった配信に
    # 残らないため、本数から稼働秒を出すと終端がs_startへ潰れ、窓が全部空になる。
    span_end = sess["ended_at"]
    if span_end is None:
        span_end = s_start + _observed_span(conn, sess)

    def clip(a, b):
        lo = max(a, s_start)
        hi = min(b, span_end)
        return (lo, hi) if hi > lo else None

    b_ints = []
    n_battles = 0
    seen_b = set()
    for br in conn.execute(
        "SELECT battle_id, data_json FROM battles WHERE session_id = ?", (sid,)
    ).fetchall():
        try:
            bt = json.loads(br["data_json"])
        except (ValueError, TypeError):
            continue
        st, en = bt.get("start_time"), bt.get("end_time")
        if st is None or en is None or en <= st:
            continue
        bid = br["battle_id"]
        if bid:
            if bid in seen_b:
                continue
            seen_b.add(bid)
        c = clip(st, en)
        if c:
            b_ints.append(c)
            n_battles += 1
    b_ints = _merge_intervals(b_ints)

    c_ints = []
    n_collabs = 0
    for w in conn.execute(
        "SELECT start, end FROM collab_windows WHERE session_id = ?", (sid,)
    ).fetchall():
        en = w["end"] if w["end"] is not None else span_end
        c = clip(w["start"], en)
        if c:
            c_ints.append(c)
            n_collabs += 1
    c_ints = _merge_intervals(c_ints)
    collab_only = _subtract_intervals(c_ints, b_ints)

    battle_joins = collab_joins = normal_joins = 0
    for r in conn.execute(
        "SELECT time FROM events WHERE session_id = ? AND kind = 'join'", (sid,)
    ).fetchall():
        if _in_intervals(r["time"], b_ints):
            battle_joins += 1
        elif _in_intervals(r["time"], collab_only):
            collab_joins += 1
        else:
            normal_joins += 1
    # 総稼働はbattle/collab秒と同じ区間(wall-clock)基準に統一する。bucket数×bucket秒
    # だと、収集断を跨ぐbattleがbs側だけ全長計上され、normal秒(=as-bs-cs)が過小になる。
    return {
        "bs": _total_span(b_ints),
        "cs": _total_span(collab_only),
        "as": span_end - s_start,
        "bj": battle_joins,
        "cj": collab_joins,
        "nj": normal_joins,
        "nb": n_battles,
        "ncl": n_collabs,
    }


def _payload_organic(conn, sess: dict) -> dict:
    """organic入室(§15): 各入室のgenuineness weightを時間帯別に集約(session内)。
    再訪は「同一配信者の過去session(全期間)に入室歴あり」で判定する。過去に固定される
    定義なのでsession終了時に確定し、後続の収集で書き換わらない。"""
    sid = sess["id"]
    ev_rows = conn.execute(
        "SELECT time AS t, kind, identity_key AS key,"
        f" {_SQL_SLOT15.format(col='time')} AS slot,"
        f" {_SQL_DOW.format(col='time')} AS dow"
        " FROM events WHERE session_id = ? AND identity_key != ''"
        f" AND kind IN ({','.join('?' * len(_ORGANIC_EVENT_KINDS))})"
        " ORDER BY time",
        (sid, *_ORGANIC_EVENT_KINDS),
    ).fetchall()
    # 1周目: 初回入室時刻・engaged(入室後の反応)・share時刻。
    first_join: dict = {}
    engaged: set = set()
    share_times: list = []
    for r in ev_rows:
        key, kind = r["key"], r["kind"]
        if kind == "join":
            if key not in first_join:
                first_join[key] = r["t"]
        elif kind == "share":
            share_times.append(r["t"])
        else:
            fj = first_join.get(key)
            if fj is not None and r["t"] >= fj:
                engaged.add(key)
    join_keys = list(first_join)
    # 再訪: 同一配信者(owner_key)の過去sessionへの入室歴。
    prior_ids = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM sessions"
            " WHERE COALESCE(NULLIF(owner_user_id, ''), unique_id) = ?"
            " AND started_at < ? AND id != ?",
            (sess["owner_key"], sess["started_at"], sid),
        ).fetchall()
    ]
    returning: set = set()
    if prior_ids and join_keys:
        for chunk in _chunked(prior_ids):
            ph = ",".join("?" * len(chunk))
            for r in conn.execute(
                f"SELECT DISTINCT identity_key AS key FROM events"
                f" WHERE session_id IN ({ph}) AND kind = 'join'",
                tuple(chunk),
            ).fetchall():
                returning.add(r["key"])
        returning &= set(join_keys)
    # level保有: users表のfans/gifter level(session確定時点のsnapshot)。
    leveled: set = set()
    for chunk in _chunked(join_keys):
        ph = ",".join("?" * len(chunk))
        for r in conn.execute(
            f"SELECT identity_key AS key FROM users"
            f" WHERE identity_key IN ({ph}) AND (fans_level > 0 OR gifter_level > 0)",
            tuple(chunk),
        ).fetchall():
            leveled.add(r["key"])
    # 2周目: join を weight 付けし15分slot別に集約。share反応窓の判定も行う。
    # grp[0]=平日(月〜金), grp[1]=休日(土日)。曜日別に2系列で返す。
    grp = [[[0, 0.0, 0] for _ in range(_DAY_SLOTS_15)] for _ in range(2)]  # [raw, organic, share_window]
    tot = {"raw": 0, "organic": 0.0, "returning": 0, "engaged": 0,
           "leveled": 0, "share_window": 0}
    for r in ev_rows:
        if r["kind"] != "join":
            continue
        key, s = r["key"], r["slot"]
        g = 1 if r["dow"] in _HOLIDAY_DOW else 0
        is_returning = key in returning
        is_engaged = key in engaged
        has_level = key in leveled
        w = _ORGANIC_WEIGHT_BASE
        if is_returning:
            w += _ORGANIC_WEIGHT_RETURNING
        if is_engaged:
            w += _ORGANIC_WEIGHT_ENGAGED
        if has_level:
            w += _ORGANIC_WEIGHT_LEVEL
        w = min(1.0, w)
        in_window = False
        if share_times:
            idx = bisect.bisect_right(share_times, r["t"]) - 1
            if idx >= 0 and 0 <= r["t"] - share_times[idx] <= _ORGANIC_SHARE_WINDOW_SECONDS:
                in_window = True
        grp[g][s][0] += 1
        grp[g][s][1] += w
        tot["raw"] += 1
        tot["organic"] += w
        if is_returning:
            tot["returning"] += 1
        if is_engaged:
            tot["engaged"] += 1
        if has_level:
            tot["leveled"] += 1
        if in_window:
            grp[g][s][2] += 1
            tot["share_window"] += 1
    # 集計stick-rate(§15.1)の分子分母: session内の連続bucket間の同接差を正側のみ。
    stick_gain = 0
    stick_joins = 0
    prev_viewers = None
    for r in conn.execute(
        "SELECT joins, viewers FROM buckets WHERE session_id = ? ORDER BY start",
        (sid,),
    ).fetchall():
        v = r["viewers"] or 0
        j = r["joins"] or 0
        if prev_viewers is None:
            prev_viewers = v
            continue
        if j > 0:
            stick_gain += max(0, v - prev_viewers)
            stick_joins += j
        prev_viewers = v
    return {"wd": grp[0], "he": grp[1], "tot": tot, "stick": [stick_gain, stick_joins]}


def _payload_entry_source(conn, sess: dict) -> dict:
    """流入元(clientEnterSource)と視聴者のfollow関係のpoint-in-time集計(session内)。

    列がNULLの行はこの計装より前に収集したもので、「不明と観測した」のではなく
    「計測していない」。集計から除外し、被覆率(measured/total)として別に返す。
    値が 'unknown' の行は届いた上で空だったもので、これは独立カテゴリとして数える。"""
    sid = sess["id"]
    src: dict = {}
    join_fs: dict = {}
    join_total = join_measured = join_follow_measured = 0
    for r in conn.execute(
        "SELECT enter_source AS s, follow_status AS f, COUNT(*) AS n FROM events"
        " WHERE session_id = ? AND kind = 'join' GROUP BY s, f",
        (sid,),
    ).fetchall():
        n = r["n"]
        join_total += n
        if r["s"] is not None:
            join_measured += n
            src[r["s"]] = src.get(r["s"], 0) + n
        if r["f"] is not None:
            join_follow_measured += n
            join_fs[r["f"]] = join_fs.get(r["f"], 0) + n

    eng_fs: dict = {}
    eng_total = eng_measured = 0
    roles = {"sub": [0, 0], "mod": [0, 0], "gg": [0, 0]}  # [該当数, 計測数]
    for r in conn.execute(
        "SELECT follow_status AS f, COUNT(*) AS n,"
        " COALESCE(SUM(CASE WHEN is_subscriber IS NOT NULL THEN 1 ELSE 0 END), 0) AS subm,"
        " COALESCE(SUM(COALESCE(is_subscriber, 0)), 0) AS subt,"
        " COALESCE(SUM(CASE WHEN is_moderator IS NOT NULL THEN 1 ELSE 0 END), 0) AS modm,"
        " COALESCE(SUM(COALESCE(is_moderator, 0)), 0) AS modt,"
        " COALESCE(SUM(CASE WHEN is_gift_giver IS NOT NULL THEN 1 ELSE 0 END), 0) AS ggm,"
        " COALESCE(SUM(COALESCE(is_gift_giver, 0)), 0) AS ggt"
        " FROM events WHERE session_id = ? AND kind IN ('comment', 'gift') GROUP BY f",
        (sid,),
    ).fetchall():
        eng_total += r["n"]
        if r["f"] is not None:
            eng_measured += r["n"]
            eng_fs[r["f"]] = eng_fs.get(r["f"], 0) + r["n"]
        roles["sub"][0] += r["subt"]
        roles["sub"][1] += r["subm"]
        roles["mod"][0] += r["modt"]
        roles["mod"][1] += r["modm"]
        roles["gg"][0] += r["ggt"]
        roles["gg"][1] += r["ggm"]

    return {
        "j": {"total": join_total, "measured": join_measured,
              "fm": join_follow_measured, "src": src, "fs": join_fs},
        "e": {"total": eng_total, "measured": eng_measured, "fs": eng_fs,
              "roles": roles},
    }


def _bf_rival_series(battle: dict, settle_time: float):
    """score_seriesを (t, own, rival) の非キメラ系列へ直す。戻り値は (series, 形式)。

    `score_series.opp` は max(opp_scores) のため、敵が3陣営以上ある個人マルチでは
    sampleごとに別人へ入れ替わる**キメラ系列**になる。リード交代や終盤の競り合いを
    そのまま出すと無意味なので、母集団は
      - 1v1(参加者2人) / 実チーム戦(陣営2つ): oppがそのまま単一の相手を指す
      - 個人マルチ: parts[]から**直近rival**(最新sampleで首位の敵)の系列を再構成でき、
        その相手が全sampleに居るときのみ
    に限る。再構成できない場合は (None, 理由) を返す。"""
    series = battle.get("score_series") or []
    if len(series) < 2:
        return None, "no_series"
    # 陣営と直近rivalはPK確定時点(core.battle.settled_scoresと同じ窓)の状態で決める。
    # score_seriesはPK終了後もroster解体まで記録が続き、相手hostが抜けると首位が
    # 入れ替わる/scoreが0へ落ちるため、最終sampleで決めてはいけない。
    reference = next((s for s in reversed(series) if s["t"] <= settle_time), None)
    if reference is None:
        return None, "no_series"
    last_parts = reference.get("parts") or []
    if battle.get("type") == "team":
        teams = {str(p.get("team_id")) for p in last_parts if p.get("team_id") is not None}
        if len(teams) != 2:
            return None, "chimera"
        return [(s["t"], s["own"], s["opp"]) for s in series], "team"
    ids = {str(p.get("id")) for p in last_parts if p.get("id")}
    if len(ids) == 2:
        return [(s["t"], s["own"], s["opp"]) for s in series], "1v1"
    opponents = [p for p in last_parts if p.get("side") != "own" and p.get("id")]
    if not opponents:
        return None, "chimera"
    top = max((p.get("score") or 0) for p in opponents)
    leaders = [p for p in opponents if (p.get("score") or 0) == top]
    # 首位が同点で複数居ると「直近rival」が一意に決まらない。推測せず対象外にする。
    if len(leaders) != 1:
        return None, "chimera"
    rival_id = str(leaders[0].get("id"))
    out = []
    for s in series:
        scores = {str(p.get("id")): (p.get("score") or 0) for p in (s.get("parts") or [])}
        if rival_id not in scores:
            # rosterが揃う前のsampleにrivalが居ない=途中参加。系列が繋がらないので外す。
            return None, "chimera"
        out.append((s["t"], s["own"], scores[rival_id]))
    return out, "multi"


def _bf_step(series: list, t: float, index: int) -> int:
    """時刻tにおけるscore(階段関数)。tより前のsampleが無ければ0(battle開始時のscore)。"""
    lo, hi = 0, len(series)
    while lo < hi:
        mid = (lo + hi) // 2
        if series[mid][0] <= t:
            lo = mid + 1
        else:
            hi = mid
    return series[lo - 1][index] if lo else 0


def _bf_crit_extra(battle: dict):
    """グローブcritで上乗せされたぶんの自陣scoreを (時刻, 上乗せ) の昇順listで返す。
    第2要素は倍率不明でcritを差し引けなかったevent数(=補正後系列の過小補正の量)。

    crit=Noneは判定不能で、critだったかどうかが分からない。推測で差し引くと補正後の
    系列が捏造になるため差し引かず、件数だけ返して注記に回す。"""
    extras = []
    unresolved = 0
    for ev in (battle.get("glove_events") or []):
        if ev.get("crit") is None:
            unresolved += 1
            continue
        if not ev.get("crit"):
            continue
        delta, mult = ev.get("score_delta"), ev.get("mult")
        t = ev.get("t")
        if delta is None or not mult or mult <= 1 or t is None:
            unresolved += 1
            continue
        extras.append((float(t), delta - delta / mult))
    extras.sort()
    return extras, unresolved


def _bf_extra_before(extras: list, t: float) -> float:
    total = 0.0
    for et, value in extras:
        if et > t:
            break
        total += value
    return total


def _payload_battle_flow(conn, sess: dict) -> dict:
    """Battle 1戦ごとの展開(残り時間軸)。リード交代・残り1分時点のリード・末尾集中度を
    記述統計としてだけ持つ(横断のdedupと率の算出はreduce側)。"""
    rows = conn.execute(
        "SELECT battle_id AS bid, data_json AS d FROM battles WHERE session_id = ?"
        " ORDER BY rowid",
        (sess["id"],),
    ).fetchall()
    battles = []
    for row in rows:
        rec = {"bid": row["bid"], "ok": 0, "why": "parse"}
        battles.append(rec)
        try:
            battle = json.loads(row["d"])
        except (ValueError, TypeError):
            continue
        if battle.get("aborted"):
            rec["why"] = "aborted"
            continue
        start_time, end_time = battle.get("start_time"), battle.get("end_time")
        if start_time is None or end_time is None or end_time <= start_time:
            rec["why"] = "no_end"
            continue
        duration = end_time - start_time
        if duration < _BF_MIN_DURATION_SECONDS:
            rec["why"] = "short"
            continue
        # 確定scoreを載せた最後のarmies更新はend_timeと前後して届く。切り口はcore.battleに
        # 一本化し、履歴画面・焼き込みと同じ窓を使う。
        settle_time = end_time + BATTLE_SETTLE_GRACE_SECONDS
        series, form = _bf_rival_series(battle, settle_time)
        if series is None:
            rec["why"] = form
            continue
        # 勝敗はcore.battle.resolve_result(=履歴画面の表示と同じ判定)を使う。battles表の
        # resultはPK後のroster解体まで含んだ最後のarmies更新の値なので、差異は件数だけ別掲する。
        resolved = resolve_result(battle)
        rec.update({"ok": 1, "why": None, "form": form, "dur": round(duration, 1),
                    "res": resolved["result"],
                    "res_diff": 1 if resolved["reported"] != resolved["result"] else 0})

        # リード交代: 優劣が反転した回数。同点を挟んでも符号が戻れば交代とは数えない。
        changes = 0
        sign = 0
        for _, own, rival in series:
            cur = 1 if own > rival else (-1 if own < rival else 0)
            if cur and sign and cur != sign:
                changes += 1
            if cur:
                sign = cur
        rec["lc"] = changes

        checkpoint = end_time - _BF_LEAD_CHECKPOINT_SECONDS
        c_own, c_rival = _bf_step(series, checkpoint, 1), _bf_step(series, checkpoint, 2)
        rec["cp"] = "own" if c_own > c_rival else ("opp" if c_own < c_rival else "tie")

        extras, unresolved = _bf_crit_extra(battle)
        rec["cu"] = unresolved
        tail_start = end_time - _BF_TAIL_SECONDS
        # 総得点は勝敗と同じ確定時点で採る(end_timeで切ると、確定burstが数百ms遅れて
        # 届いた戦だけ総得点が小さく出て、resと矛盾する)。
        total_raw = _bf_step(series, settle_time, 1)
        tail_raw = total_raw - _bf_step(series, tail_start, 1)
        rec["tail"] = [tail_raw, total_raw]
        total_adj = total_raw - _bf_extra_before(extras, settle_time)
        tail_adj = total_adj - (_bf_step(series, tail_start, 1)
                                - _bf_extra_before(extras, tail_start))
        # critの上乗せを引いて総得点が0以下になるのは突合の破綻。補正値を出さない。
        rec["tail_adj"] = [tail_adj, total_adj] if total_adj > 0 and tail_adj >= 0 else None

        # 残り時間binごとの自陣得点。battleの尺に収まるbinだけを埋め、覆っていないbinは
        # 分母にも入れない(短いbattleを0得点として混ぜると序盤帯が薄く出る)。
        bins = []
        for i in range(_BF_MAX_REMAINING // _BF_BIN_SECONDS):
            r_from = i * _BF_BIN_SECONDS
            r_to = r_from + _BF_BIN_SECONDS
            if r_to > duration:
                bins.append(None)
                continue
            # 残り0の側の端だけは確定時点まで含める(total_rawと同じ切り口に揃える)。
            upper = settle_time if r_from == 0 else end_time - r_from
            gain = _bf_step(series, upper, 1) - _bf_step(series, end_time - r_to, 1)
            bins.append(gain)
        rec["bins"] = bins
    return {"battles": battles}


def _payload_coverage(conn, sess: dict) -> dict:
    """収集の穴(欠測)を測る素材。sessionが終わった時点で確定する値だけを持つ。

    録画カバレッジとSTT率は後から変わる(finalizeより後にmp4のended_atが埋まり、
    転写は数日後に走ることもある)ため、ここへは入れずreduce側で都度集計する。"""
    sid = sess["id"]
    s_start, s_end = sess["started_at"], sess["ended_at"]
    meta = conn.execute(
        "SELECT live_create_time, conn_instrumentation FROM sessions WHERE id = ?",
        (sid,),
    ).fetchone()
    live_create = meta["live_create_time"] if meta else None
    instrumented = (meta["conn_instrumentation"] if meta else None) is not None

    markers = conn.execute(
        "SELECT time, kind FROM markers WHERE session_id = ?"
        " AND kind IN ('connect', 'reconnect', 'disconnect', 'disconnect_unplanned')"
        " ORDER BY time",
        (sid,),
    ).fetchall()
    first_connect = next((m["time"] for m in markers if m["kind"] == "connect"), None)

    # 収集開始遅延 = 配信そのものの開始(server権威値) → 実際に繋がった時刻。
    # どちらかが無ければ「計測不能」でNoneのまま(started_atで代用すると遅延0に化ける)。
    delay = None
    if live_create is not None and first_connect is not None and first_connect >= live_create:
        delay = first_connect - live_create

    # 切断による欠測秒。計装前のsessionは切断markerが残っていないため、0ではなくNone。
    # 閉じた窓(切断→再接続)だけを数える。末尾の切断はsessionの終了そのものなので
    # 欠測には含めず、件数だけ別に持つ。
    gaps = None
    if instrumented:
        total = 0.0
        closed = 0
        unplanned = 0
        pending = None
        for m in markers:
            kind = m["kind"]
            if kind in ("disconnect", "disconnect_unplanned"):
                if pending is None:
                    pending = (m["time"], kind == "disconnect_unplanned")
            elif pending is not None:
                total += max(0.0, m["time"] - pending[0])
                closed += 1
                unplanned += 1 if pending[1] else 0
                pending = None
        gaps = {"sec": round(total, 1), "n": closed, "unplanned": unplanned,
                "open_end": 1 if pending is not None else 0}

    # 同接sampleの間隔。旧sessionでも正しく出る(markerに依存しない)。
    times = [r["time"] for r in conn.execute(
        "SELECT time FROM viewer_samples WHERE session_id = ? ORDER BY time", (sid,)
    ).fetchall()]
    sampling = None
    if len(times) >= _CV_MIN_SAMPLES:
        diffs = [b - a for a, b in zip(times, times[1:]) if b > a]
        if diffs:
            sampling = {"n": len(diffs),
                        "median": round(_median(diffs), 2),
                        "p95": round(_percentile(diffs, _CV_GAP_PERCENTILE), 2),
                        "max": round(max(diffs), 2)}

    return {
        "dur": round(s_end - s_start, 1) if s_end is not None else None,
        "inst": 1 if instrumented else 0,
        "delay": round(delay, 1) if delay is not None else None,
        "gaps": gaps,
        "smp": sampling,
    }


def _gift_battle_windows(conn, sess: dict) -> list:
    """session内のbattle窓(非重複・sessionの範囲へclamp済み)。start/endの揃わない
    battle行は窓として使えないので落とす。"""
    s_start = sess["started_at"]
    s_end = sess["ended_at"]
    spans = []
    for row in conn.execute(
        "SELECT data_json AS d FROM battles WHERE session_id = ? ORDER BY rowid",
        (sess["id"],),
    ).fetchall():
        try:
            battle = json.loads(row["d"])
        except (ValueError, TypeError):
            continue
        start_time = battle.get("start_time")
        end_time = battle.get("end_time")
        if start_time is None or end_time is None or end_time <= start_time:
            continue
        lo = max(start_time, s_start)
        hi = min(end_time, s_end) if s_end is not None else end_time
        if hi > lo:
            spans.append((lo, hi))
    return _merge_intervals(spans)


def _payload_gift_sku(conn, sess: dict) -> dict:
    """ギフトSKU構成の素材。gift eventをgift_id単位へ畳み、battle窓内/外に分けて持つ。

    単価帯への割り当てはreduce側で行う。単価(1個あたりcoin)はgift_id単位でしか安定せず、
    gift_countが記録されていないeventが混ざるsessionでは自session内だけでは解けないため
    (glove(§⑨)と同じ考え方で、観測が増えるほど後から解ける)。

    反復購入率のために送り手ごとの送信回数も持つ。identity_keyは生で持つとcache payloadが
    session数×送り手数まで膨らむので、48bitのdigestへ畳んで持つ(この規模の識別子数では
    衝突確率が無視できる。用途はsession跨ぎの同一人物判定のみで、復号は不要)。
    identityの取れない匿名giftは反復の分母に入れられないため、件数だけ別掲する。"""
    windows = _gift_battle_windows(conn, sess)
    # [events, coins, events_in_battle, coins_in_battle, price_coins, price_units]
    # price_*はgift_count>0のeventのみ(単価=price_coins/price_units)。
    gifts: dict = {}
    senders: dict = {}
    names: dict = {}
    no_gift_id = [0, 0]
    anon = 0
    for row in conn.execute(
        "SELECT time, gift_id, gift_name, gift_count, diamonds, identity_key"
        " FROM events WHERE session_id = ? AND kind = 'gift' ORDER BY time",
        (sess["id"],),
    ).fetchall():
        coins = row["diamonds"] or 0
        gid = row["gift_id"]
        if gid is None:
            no_gift_id[0] += 1
            no_gift_id[1] += coins
            continue
        key = str(gid)
        rec = gifts.setdefault(key, [0, 0, 0, 0, 0, 0])
        rec[0] += 1
        rec[1] += coins
        if _in_intervals(row["time"], windows):
            rec[2] += 1
            rec[3] += coins
        count = row["gift_count"] or 0
        if count > 0:
            rec[4] += coins
            rec[5] += count
        name = (row["gift_name"] or "").strip()
        if name:
            names[key] = name
        identity = row["identity_key"] or ""
        if identity:
            by_sender = senders.setdefault(key, {})
            digest = _identity_digest(identity)
            by_sender[digest] = by_sender.get(digest, 0) + 1
        else:
            anon += 1
    return {
        "g": gifts,
        "names": names,
        "s": senders,
        "no_id": no_gift_id,
        "anon": anon,
        "battle_sec": round(_total_span(windows), 1),
    }


_PAYLOAD_FUNCS = {
    "summary": _payload_summary,
    "time_index": _payload_time_index,
    "relations": _payload_relations,
    "peri_share": _payload_peri_share,
    "peri_battle": _payload_peri_battle,
    "battle_ratio": _payload_battle_ratio,
    "glove": _payload_glove,
    "join_quality": _payload_join_quality,
    "scale_efficiency": _payload_scale_efficiency,
    "retention": _payload_retention,
    "join_context": _payload_join_context,
    "organic": _payload_organic,
    "entry_source": _payload_entry_source,
    "battle_flow": _payload_battle_flow,
    "coverage": _payload_coverage,
    "gift_sku": _payload_gift_sku,
    "dwell": _payload_dwell,
    "anomaly": _payload_anomaly,
    "activation": _payload_activation,
}


# ---- 計装 -------------------------------------------------------------------
# 全体解析は「per-session payload計算(cache miss時のみ)」→「横断reduce」の2段で、
# 遅い時にどちらが遅いのかがlogから即断できることを最優先にする。reduceの1行に
# 自stageの所要時間と、その裏で走ったpayload計算の合計時間・件数を併記する。

# stage内で計算したpayloadの件数/時間。payload計算(storage側のcache埋め)とreduceは
# 同一呼び出しchain=同一threadで連続するため、thread localが両者を結ぶ最も軽い手段
# (ContextVarはto_thread越しにcopyされるが書き戻せない)。session終了時のcache
# 更新のようにreduceを伴わないpayload計算は回収されずに残るので、同じthreadで後から
# 走ったreduceが1回だけ多めに数えることがある(計測用metaであり結果には影響しない)。
_compute_local = threading.local()


def _compute_counters() -> dict:
    counters = getattr(_compute_local, "counters", None)
    if counters is None:
        counters = {}
        _compute_local.counters = counters
    return counters


def _record_compute(kind: str, sess: dict, duration_ms: float) -> None:
    """1 sessionぶんのpayload計算を集計に積み、遅いものだけ個別に残す。"""
    # ended_at未確定=収集中sessionは仕様上毎回計算する(cacheしない)。version不一致や
    # 未計算による本当のcache missと区別できるよう別々に数える。
    live = sess.get("ended_at") is None
    slot = _compute_counters().setdefault(kind, [0, 0, 0.0])
    slot[0 if live else 1] += 1
    slot[2] += duration_ms
    if duration_ms >= config.get_log_slow_analytics_payload_ms():
        logger.warning(
            "slow analytics payload: kind=%s took %.0fms for one session",
            kind, duration_ms,
            extra={"event": "analytics.payload_slow",
                   "ctx": {"kind": kind, "duration_ms": round(duration_ms, 1),
                           "version": CACHE_VERSIONS[kind], "live": live}},
        )
    elif logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "analytics payload computed: kind=%s in %.1fms", kind, duration_ms,
            extra={"event": "analytics.payload_computed",
                   "ctx": {"kind": kind, "duration_ms": round(duration_ms, 1),
                           "version": CACHE_VERSIONS[kind], "live": live}},
        )


def compute_payload(conn, sess: dict, kind: str) -> dict:
    """1 sessionぶんの中間集計。cacheに無い/CACHE_VERSIONS不一致、または収集中session
    の時だけ呼ばれるので、呼び出し回数がそのままcache missの件数になる。

    相関IDは自動注入に任せる(ここはHTTP requestのcontextで走るためsession_idが
    bindされていない)。"""
    with log_context(session_id=sess.get("id"), unique_id=sess.get("unique_id")):
        started = time.perf_counter()
        payload = _PAYLOAD_FUNCS[kind](conn, sess)
        _record_compute(kind, sess, (time.perf_counter() - started) * 1000.0)
    return payload


def _stage(kind):
    """reduce_*を1 stageとして計装する。kindは固定文字列か、rows以降の引数から
    kindを決める callable(reduce_periのように treatment でcache kindが変わるため)。"""

    def decorate(func):
        @functools.wraps(func)
        def wrapper(rows, *args, **kwargs):
            resolved = kind(*args, **kwargs) if callable(kind) else kind
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "analytics stage started: %s (%d sessions)", resolved, len(rows),
                    extra={"event": "analytics.stage_started",
                           "ctx": {"kind": resolved, "rows": len(rows)}},
                )
            started = time.perf_counter()
            try:
                result = func(rows, *args, **kwargs)
            except Exception:
                _compute_counters().pop(resolved, None)
                logger.error(
                    "analytics stage failed: %s (%d sessions)", resolved, len(rows),
                    exc_info=True,
                    extra={"event": "analytics.stage_failed",
                           "ctx": {"kind": resolved, "rows": len(rows),
                                   "duration_ms": round((time.perf_counter() - started) * 1000.0, 1)}},
                )
                raise
            _log_stage_completed(
                resolved, len(rows), (time.perf_counter() - started) * 1000.0
            )
            return result

        return wrapper

    return decorate


def _log_stage_completed(kind: str, rows: int, duration_ms: float) -> None:
    live, missed, compute_ms = _compute_counters().pop(kind, (0, 0, 0.0))
    total_ms = duration_ms + compute_ms
    ctx = {
        "kind": kind,
        "version": CACHE_VERSIONS.get(kind),
        "rows": rows,
        "duration_ms": round(duration_ms, 1),
        "compute_ms": round(compute_ms, 1),
        "total_ms": round(total_ms, 1),
        # cache hit = 今回計算しなかった終了済みsession。missはversion不一致か未計算。
        "cache_hits": max(0, rows - live - missed),
        "cache_misses": missed,
        "computed_live": live,
    }
    message = (
        f"analytics stage {kind}: {rows} sessions in {total_ms:.0f}ms"
        f" (reduce {duration_ms:.0f}ms, payload {compute_ms:.0f}ms for"
        f" {missed + live} sessions)"
    )
    if total_ms >= config.get_log_slow_analytics_ms():
        logger.warning(
            "slow " + message,
            extra={"event": "analytics.stage_slow", "ctx": ctx},
        )
    else:
        logger.info(message, extra={"event": "analytics.stage_completed", "ctx": ctx})


# ---- 横断reduce(API応答の組み立て) --------------------------------------------
# rowsは (sessメタdict, payload dict) のリスト。呼び出し側でstarted_at昇順に揃える。

@_stage("summary")
def reduce_summary(rows: list) -> dict:
    started = [s["started_at"] for s, _ in rows]
    ended = [
        s["ended_at"] if s["ended_at"] is not None else s["started_at"] for s, _ in rows
    ]
    return {
        "streamers": len({s["unique_id"] for s, _ in rows}),
        "sessions": len(rows),
        "first_at": min(started) if started else None,
        "last_at": max(ended) if ended else None,
        "buckets": sum(p["nb"] for _, p in rows),
        "active_seconds": sum(p["act"] for _, p in rows),
        "joins": sum(p["j"] for _, p in rows),
        "diamonds": sum(p["d"] for _, p in rows),
        "comments": sum(p["c"] for _, p in rows),
    }


# time_indexのpayload cell内の指標位置([dow, slot20, nb, joins, comments, diamonds, likes, follows])。
_TI_CELL_POS = {m: 3 + i for i, m in enumerate(INDEX_METRICS)}


def _session_long_enough(sess: dict) -> bool:
    """時間帯系の集計対象か。20分以上継続した配信のみ採る。収集中(ended_at未確定)は
    まだ切れていないため対象に含める。"""
    started = sess.get("started_at")
    ended = sess.get("ended_at")
    if ended is None or started is None:
        return True
    return (ended - started) >= _MIN_SESSION_SECONDS


@_stage("time_index")
def reduce_time_index(rows: list, metric: str) -> dict:
    """時間帯インデックス: 各配信の平均レートを1.0とした20分slotごとの相対倍率。
    配信ごとに自分の平均で正規化してから配信横断で中央値を取るので、規模差・外れ値
    に強い。曜日(月〜日)別に分割。1観測 = (session,date,20分slot)。20分経つ前に切れた
    配信は除外する。"""
    pos = _TI_CELL_POS.get(metric)
    if pos is None:
        raise ValueError(f"unsupported index metric: {metric}")
    dow_buckets = [[[] for _ in range(_DAY_SLOTS_20)] for _ in range(7)]
    all_buckets = [[] for _ in range(_DAY_SLOTS_20)]
    n_sessions = 0
    for sess, payload in rows:
        if not _session_long_enough(sess):
            continue
        cells = payload["cells"]
        base_val = sum(c[pos] or 0 for c in cells)
        base_nb = sum(c[2] or 0 for c in cells)
        if base_nb <= 0 or base_val <= 0:
            continue
        baseline_rate = base_val / base_nb
        # slotの端を数十秒だけ跨いだ観測(低coverage)は分母が小さくレートが暴れるため、
        # slot長の一定割合以上を観測できた観測だけをセルの分布に入れる。
        bucket_s = sess.get("bucket_seconds") or 0
        min_nb = (
            (_TI_SLOT_SECONDS * _TI_MIN_SLOT_COVERAGE) / bucket_s if bucket_s > 0 else 0
        )
        contributed = False
        for c in cells:
            nb = c[2] or 0
            if nb <= 0 or nb < min_nb:
                continue
            slot_rate = (c[pos] or 0) / nb
            index = slot_rate / baseline_rate
            all_buckets[c[1]].append(index)
            dow_buckets[c[0]][c[1]].append(index)
            contributed = True
        if contributed:
            n_sessions += 1

    def _cell(values: list) -> dict:
        n = len(values)
        return {"index": round(_median(values), 3) if n else None, "n": n}

    slots = []
    for s in range(_DAY_SLOTS_20):
        slots.append(
            {
                "slot": s,
                "minute": s * 20,
                "all": _cell(all_buckets[s]),
                # dow[0..6] = 日..土。frontendは表示順を月始まりに並べ替える。
                "dow": [_cell(dow_buckets[d][s]) for d in range(7)],
            }
        )
    return {
        "metric": metric,
        "slots": slots,
        "n_sessions": n_sessions,
        "n_observations": sum(len(b) for b in all_buckets),
    }


@_stage("relations")
def reduce_relations(rows: list) -> dict:
    """指標間の関連(配信単位)。1配信 = 1観測として、Spearman順位相関で突き合わせる。
    素の相関はscale交絡(大箱は全指標が同時に多い)で過大になるため、同接(viewers)と
    配信長(bucket数)を制御した偏相関を併せて返す。相関対象はSUM累積なので、長い配信
    ほど全指標が一斉に膨らむ分はpeak同接だけでは除けない。小標本の偶然相関を濃色で
    断定しないよう、t近似の5%有意判定(sig)も返す。"""
    obs = [p for _, p in rows if p["n"] > 0]
    columns = {m: [p[m] or 0 for p in obs] for m in RELATION_METRICS}
    controls = [columns["viewers"], [p["n"] or 0 for p in obs]]
    n_obs = len(obs)
    matrix = {}
    partial = {}
    sig = {}
    for a in RELATION_METRICS:
        matrix[a] = {}
        partial[a] = {}
        sig[a] = {}
        for b in RELATION_METRICS:
            r = 1.0 if a == b else _spearman(columns[a], columns[b])
            matrix[a][b] = r
            sig[a][b] = True if a == b else _spearman_significant(r, n_obs)
            if a == b:
                partial[a][b] = 1.0
            elif a == "viewers" or b == "viewers":
                # 制御変数自身との偏相関は定義できない。
                partial[a][b] = None
            else:
                partial[a][b] = _partial_spearman(columns[a], columns[b], controls)
    return {
        "metrics": RELATION_METRICS,
        "matrix": matrix,
        "partial": partial,
        "sig": sig,
        "control": "viewers+duration",
        "n_sessions": n_obs,
    }


@_stage(lambda treatment: f"peri_{treatment}")
def reduce_peri(rows: list, treatment: str) -> dict:
    """event-study(peri-event)の横断pool。各sessionの差分済み窓を集めて平均し、
    placebo帯・95%CIと共に返す。"""
    bin_s = _PERI_BIN_SECONDS
    pre, post = _PERI_PRE_BINS, _PERI_POST_BINS
    win_len = pre + post + 1
    # 窓はsession別のクラスタのまま渡す(session内の窓は重複・自己相関があり独立でない)。
    ev_clusters: list = []
    pl_clusters: list = []
    n_events = 0
    n_placebo = 0
    total_joins = 0
    total_bins = 0
    n_sessions = 0
    for _, p in rows:
        if not p.get("q"):
            continue
        total_joins += p["j"]
        total_bins += p["b"]
        n_sessions += 1
        if p["ev"]:
            ev_clusters.append(p["ev"])
            n_events += len(p["ev"])
        if p["pl"]:
            pl_clusters.append(p["pl"])
            n_placebo += len(p["pl"])
    lags = [(-pre + i) * bin_s for i in range(win_len)]
    baseline_rate = (total_joins / total_bins) if total_bins else 0.0
    mean, ci = _peri_aggregate(ev_clusters)
    pmean, pci = _peri_aggregate(pl_clusters)
    if mean is None:
        return {
            "treatment": treatment,
            "available": False,
            "n_events": n_events,
            "n_sessions": n_sessions,
            "bin_seconds": bin_s,
            "lags": lags,
            "baseline_rate": round(baseline_rate, 3),
        }
    if pmean is None:
        pmean = [0.0] * win_len
        pci = [0.0] * win_len
    sig = [
        bool(abs(mean[i]) > ci[i] and abs(mean[i]) > (abs(pmean[i]) + pci[i]))
        for i in range(win_len)
    ]
    peak_lag, peak_val = None, None
    for i in range(pre + 1, win_len):
        if peak_val is None or mean[i] > peak_val:
            peak_val, peak_lag = mean[i], lags[i]
    # 因果方向の注意: onset直前(-30..-10s)に有意な立ち上がりがあれば、入室が先で
    # treatmentが後(逆/同時因果)の疑いをpre_riseとして立てる。
    pre_rise = any(sig[i] and mean[i] > 0 for i in range(_PERI_BASELINE_BINS, pre))
    cumulative = sum(mean[pre:])
    return {
        "treatment": treatment,
        "available": True,
        "n_events": n_events,
        "n_placebo": n_placebo,
        "n_sessions": n_sessions,
        "bin_seconds": bin_s,
        "baseline_rate": round(baseline_rate, 3),
        "lags": lags,
        "uplift": [round(x, 3) for x in mean],
        "ci": [round(x, 3) for x in ci],
        "placebo": [round(x, 3) for x in pmean],
        "placebo_ci": [round(x, 3) for x in pci],
        "sig": sig,
        "peak": {
            "lag": peak_lag,
            "uplift": round(peak_val, 3),
            "pct": round(peak_val / baseline_rate * 100, 0) if baseline_rate else None,
        },
        "cumulative": round(cumulative, 2),
        "pre_rise": bool(pre_rise),
    }


@_stage("battle_ratio")
def reduce_battle_ratio(rows: list) -> dict:
    """(参考)Battle窓内 vs 窓外のレート比の中央値+IQR。baseline非補正のため単独では
    交絡に注意。event-study(placebo補正)と併読する前提。battle_idは配信者双方が監視
    対象のとき重複しうるため横断でdedupする(初出のsessionを採用)。"""
    metrics = ["joins", "comments", "follows", "diamonds"]
    uplifts = {m: [] for m in metrics}
    seen = set()
    for _, payload in rows:
        for rec in payload["battles"]:
            bid = rec["bid"]
            if bid:
                if bid in seen:
                    continue
                seen.add(bid)
            up = rec["up"]
            if not up:
                continue
            for m in metrics:
                if up.get(m) is not None:
                    uplifts[m].append(up[m])
    result = {}
    for m, vals in uplifts.items():
        result[m] = {
            "median": round(_median(vals), 3) if vals else None,
            "p25": round(_percentile(vals, 25), 3) if vals else None,
            "p75": round(_percentile(vals, 75), 3) if vals else None,
            "n": len(vals),
        }
    return {"metrics": result, "n_battles": len(seen)}


@_stage("glove")
def reduce_glove(rows: list, unit_coins: dict) -> dict:
    """グローブ(Critical Strike card=gift 5倍化)のcoin帯別発動率。分母=判定済
    (crit=1/0)のみで、判定不能(crit=None)は率に入れず件数だけ別掲する(推測で
    埋めると率が歪むため)。unit_coinsはgift_id→単価(全期間のGift eventから解決)で、
    単価未記録のグローブ窓ギフトを補完する。"""
    buckets = [
        {"lo": lo, "hi": hi, "gifts": 0, "crits": 0, "undecided": 0}
        for lo, hi in GLOVE_COIN_BUCKETS
    ]

    def _bucket_for(coins: float):
        for b in buckets:
            if b["lo"] <= coins <= b["hi"]:
                return b
        return None

    n_windows = n_battles = unresolved = range_out = 0
    seen = set()
    for sess, payload in rows:
        for rec in payload["battles"]:
            bid = rec["bid"]
            if bid:
                # battle_idは対戦双方を監視していると両sessionに現れるが、payloadは
                # 各session owner視点の「自陣」ギフトで互いに素。bidだけでdedupすると
                # 後着owner側の標本を丸ごと捨てるため、(owner, bid)でdedupする。
                key = (sess["owner_key"], bid)
                if key in seen:
                    continue
                seen.add(key)
            if not rec.get("ok"):
                continue
            n_windows += rec.get("w") or 0
            events = rec.get("ev") or []
            if events:
                n_battles += 1
            for gift_id, coins, crit in events:
                if coins is None:
                    coins = unit_coins.get(gift_id)
                if not coins or coins <= 0:
                    unresolved += 1
                    continue
                b = _bucket_for(coins)
                if b is None:
                    range_out += 1
                    continue
                if crit is None:
                    b["undecided"] += 1
                    continue
                b["gifts"] += 1
                if crit:
                    b["crits"] += 1
    out_buckets = [
        {
            "label": f"{b['lo']}-{b['hi']}",
            "lo": b["lo"], "hi": b["hi"],
            "gifts": b["gifts"], "crits": b["crits"], "undecided": b["undecided"],
            "rate": (b["crits"] / b["gifts"] * 100) if b["gifts"] else None,
            "ci": _wilson_ci(b["crits"], b["gifts"]),
        }
        for b in buckets
    ]
    total_gifts = sum(b["gifts"] for b in buckets)
    total_crits = sum(b["crits"] for b in buckets)
    total_undecided = sum(b["undecided"] for b in buckets)
    return {
        "buckets": out_buckets,
        "total_gifts": total_gifts,
        "total_crits": total_crits,
        "undecided": total_undecided,
        "overall_rate": (total_crits / total_gifts * 100) if total_gifts else None,
        "overall_ci": _wilson_ci(total_crits, total_gifts),
        "n_windows": n_windows,
        "n_battles": n_battles,
        "unresolved": unresolved,
        "range_out": range_out,
    }


def _sku_unit_coins(rows: list) -> dict:
    """gift_id→単価(1個あたりcoin)。集計対象期間のgift event全体から解く。

    単価はgift_idごとに一定なので、gift_countが記録されたeventのcoinと個数を全て足して
    割る(1 eventだけを代表に採るより、記録漏れや端数の影響を受けにくい)。gift_countが
    1件も記録されていないgift_idは解けないため表に載せず、reduce側で除外扱いにする
    (推測で埋めると単価帯の構成そのものが作り物になる)。"""
    coins: dict = {}
    units: dict = {}
    for _, payload in rows:
        for gid, rec in payload["g"].items():
            coins[gid] = coins.get(gid, 0) + rec[4]
            units[gid] = units.get(gid, 0) + rec[5]
    return {gid: coins[gid] / units[gid] for gid, n in units.items() if n > 0 and coins[gid] > 0}


def _sku_bucket_index(unit: float) -> Optional[int]:
    for i, (lo, hi) in enumerate(GIFT_SKU_COIN_BUCKETS):
        if unit >= lo and (hi is None or unit <= hi):
            return i
    return None


@_stage("gift_sku")
def reduce_gift_sku(rows: list) -> dict:
    """ギフトSKU構成の記述統計。「誰が」(concentration)に対する「何で」の側。

    出すのは3つ。(1)コイン/件数が単価帯ごとにどう分かれているか、(2)単価帯ごとの反復
    購入率(同一配信者へその帯のギフトを2回以上送った人の割合)、(3)battle窓内と窓外での
    構成差。いずれも記述統計であり、帯ごとの差が「その価格帯を置いたから売れた」ことを
    意味しない(何を出すかは配信者と視聴者の状態に依存しており、統制していない)。

    反復購入率のdedupは配信者(owner_key)単位。同じ人が別の配信者へ送った分を1人として
    畳むと「1人が複数回」と「別配信で1回ずつ」が混ざり、配信者から見た反復の意味が
    失われるため、(owner_key, identity)を1単位として数える。gift event自体はsessionが
    配信者1人に属するので横断で重複しない(battleのように双方向へ現れる素材ではない)。"""
    unit_coins = _sku_unit_coins(rows)
    buckets = [
        {"lo": lo, "hi": hi, "coins": 0, "events": 0,
         "coins_battle": 0, "events_battle": 0}
        for lo, hi in GIFT_SKU_COIN_BUCKETS
    ]
    # 帯ごと (owner_key, identity digest) -> その帯での送信回数。
    senders: list = [dict() for _ in GIFT_SKU_COIN_BUCKETS]
    skus: dict = {}
    unresolved_events = unresolved_coins = 0
    no_id_events = no_id_coins = anon_events = 0
    battle_seconds = 0.0

    for sess, payload in rows:
        owner = sess["owner_key"]
        battle_seconds += payload.get("battle_sec") or 0.0
        no_id_events += payload["no_id"][0]
        no_id_coins += payload["no_id"][1]
        anon_events += payload.get("anon") or 0
        for gid, rec in payload["g"].items():
            unit = unit_coins.get(gid)
            index = _sku_bucket_index(unit) if unit else None
            if index is None:
                # 単価が解けないSKUは帯へ入れない(glove(§⑨)のunresolvedと同じ扱い)。
                unresolved_events += rec[0]
                unresolved_coins += rec[1]
                continue
            b = buckets[index]
            b["events"] += rec[0]
            b["coins"] += rec[1]
            b["events_battle"] += rec[2]
            b["coins_battle"] += rec[3]
            sku = skus.setdefault(gid, {"coins": 0, "events": 0, "unit": unit,
                                        "name": "", "bucket": index})
            sku["coins"] += rec[1]
            sku["events"] += rec[0]
            name = payload["names"].get(gid)
            if name:
                sku["name"] = name
        for gid, by_sender in payload["s"].items():
            unit = unit_coins.get(gid)
            index = _sku_bucket_index(unit) if unit else None
            if index is None:
                continue
            target = senders[index]
            for digest, count in by_sender.items():
                key = (owner, digest)
                target[key] = target.get(key, 0) + count

    total_coins = sum(b["coins"] for b in buckets)
    total_events = sum(b["events"] for b in buckets)
    battle_coins = sum(b["coins_battle"] for b in buckets)
    outside_coins = total_coins - battle_coins

    out_buckets = []
    for b, by_sender in zip(buckets, senders):
        n_senders = len(by_sender)
        repeaters = sum(1 for n in by_sender.values() if n >= _SKU_REPEAT_MIN)
        coins_outside = b["coins"] - b["coins_battle"]
        out_buckets.append({
            "label": f"{b['lo']}-{b['hi']}" if b["hi"] is not None else f"{b['lo']}+",
            "lo": b["lo"], "hi": b["hi"],
            "coins": b["coins"],
            "events": b["events"],
            "coin_share": (b["coins"] / total_coins) if total_coins else None,
            "event_share": (b["events"] / total_events) if total_events else None,
            "senders": n_senders,
            "repeat_senders": repeaters,
            "repeat_rate": (repeaters / n_senders * 100) if n_senders else None,
            "repeat_ci": _wilson_ci(repeaters, n_senders),
            "coins_battle": b["coins_battle"],
            "coins_outside": coins_outside,
            # battle内外それぞれのコインを100%としたときの、この帯の構成比。
            # 「battle中は高額へ寄るか」を帯の間で比較できる形にする。
            "coin_share_battle": (b["coins_battle"] / battle_coins) if battle_coins else None,
            "coin_share_outside": (coins_outside / outside_coins) if outside_coins else None,
        })

    top = sorted(skus.items(), key=lambda kv: -kv[1]["coins"])[:_SKU_TOP_LIMIT]
    return {
        "buckets": out_buckets,
        "top_skus": [
            {"gift_id": int(gid), "name": sku["name"],
             "unit_coins": round(sku["unit"], 2),
             "bucket": out_buckets[sku["bucket"]]["label"],
             "coins": sku["coins"], "events": sku["events"],
             "coin_share": (sku["coins"] / total_coins) if total_coins else None}
            for gid, sku in top
        ],
        "total_coins": total_coins,
        "total_events": total_events,
        "battle_coins": battle_coins,
        "outside_coins": outside_coins,
        "battle_seconds": round(battle_seconds, 1),
        "n_skus": len(skus),
        # 帯へ入れられなかった分。捏造せずに件数として残す(母数から外れている量が
        # 見えないと、シェアが何に対する割合なのか判断できない)。
        "unresolved_events": unresolved_events,
        "unresolved_coins": unresolved_coins,
        "no_gift_id_events": no_id_events,
        "no_gift_id_coins": no_id_coins,
        "anonymous_events": anon_events,
    }


@_stage("join_quality")
def reduce_join_quality(rows: list) -> dict:
    """入室の質: 入室者(時間帯ごとのユニーク人数)のうち初見(我々が初めて観測)の比率を
    時間帯別に。識別できない入室(excluded)は分類できないため率の母数に入れず件数のみ返す。"""
    by_hour = [[0, 0] for _ in range(24)]
    excluded = 0
    for _, payload in rows:
        for hour, new, total in payload["h"]:
            by_hour[hour][0] += new
            by_hour[hour][1] += total
        excluded += payload.get("excl") or 0
    hours = []
    tot_new = 0
    tot_all = 0
    for h in range(24):
        new, total = by_hour[h]
        tot_new += new
        tot_all += total
        hours.append(
            {
                "hour": h,
                "new": new,
                "returning": total - new,
                "total": total,
                "new_ratio": round(new / total, 3) if total else 0.0,
            }
        )
    return {
        "hours": hours,
        "total": tot_all,
        "new": tot_new,
        "new_ratio": round(tot_new / tot_all, 3) if tot_all else 0.0,
        "excluded": excluded,
        "n_sessions": len(rows),
    }


@_stage("scale_efficiency")
def reduce_scale_efficiency(rows: list, owners: dict) -> dict:
    """規模 vs 効率: 配信者ごとに 規模=配信ごとの平均同接の中央値 と
    効率=総コイン÷総視聴時間(コイン/同接・時間=1人が1時間視聴するあたりのコイン)。
    視聴時間(viewer-hours)で割ることで、配信が長いほど効率が高く見える交絡を除く。
    1点=配信者。同接データのない(平均同接0の)sessionは統計・件数に入れない。"""
    by_uid: dict = {}
    for sess, payload in rows:
        avgv = payload.get("avgv") or 0
        if avgv <= 0:
            continue
        g = by_uid.setdefault(sess["unique_id"], {"avgs": [], "coins": 0, "vmin": 0.0})
        g["avgs"].append(avgv)
        g["coins"] += payload["coins"] or 0
        g["vmin"] += payload.get("vmin") or 0.0
    result = []
    for uid, g in by_uid.items():
        viewer_hours = g["vmin"] / 60.0
        owner = owners.get(uid)
        result.append(
            {
                "unique_id": uid,
                "nickname": (owner["nickname"] if owner else "") or uid,
                "avatar": (owner["avatar"] if owner else "") or "",
                "sessions": len(g["avgs"]),
                "avg_viewers": round(_median(g["avgs"]), 1),
                "coins": g["coins"],
                "coins_per_viewer_hour": (
                    round(g["coins"] / viewer_hours, 2) if viewer_hours > 0 else 0.0
                ),
            }
        )
    result.sort(key=lambda x: x["coins"], reverse=True)
    return {"streamers": result}


def _dwell_mean_ci(values: list):
    """配信ごとに1点へ畳んだ滞在時間の平均と95%CI半幅。

    1配信=1クラスタ、1クラスタ=1観測なので、素のt区間がそのままcluster-robustになる
    (同一配信内の窓は隣接窓が同じ視聴者集団を共有していて独立ではないため、窓を直接
    数え上げてSEを作るとCIが過小に出る)。2点未満はCIを出さない。"""
    n = len(values)
    if n == 0:
        return None, None
    mean = sum(values) / n
    if n < 2:
        return mean, None
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return mean, _t_975(n - 1) * (var ** 0.5) / (n ** 0.5)


def _dwell_session_stats(payload: dict):
    """1配信ぶんの採用窓から、その配信の代表滞在時間などを求める。窓が足りなければNone。"""
    windows = payload.get("w") or []
    if len(windows) < _DW_MIN_SESSION_WINDOWS:
        return None
    dwells = []
    watch_minutes = 0.0
    comments = 0
    seconds = 0.0
    levels = []
    for hour, level, arrivals, span, cmts in windows:
        if arrivals <= 0 or span <= 0:
            continue
        dwells.append(level * span / arrivals)
        watch_minutes += level * span / 60.0
        comments += cmts
        seconds += span
        levels.append(level)
    if not dwells:
        return None
    return {
        "dwell": _median(dwells),
        "level": _median(levels),
        "seconds": seconds,
        "comments_per_watch_minute": (comments / watch_minutes) if watch_minutes > 0 else None,
        "windows": windows,
        "n_windows": len(dwells),
    }


def _dwell_share(windows: list):
    """窓を「その配信者自身の窓の中央値」との比で3分し、観測時間ベースのシェアを返す。

    基準は配信単位の代表値ではなく窓の中央値を使う。窓ごとの滞在時間は右に裾を引くため、
    配信ごとに中央値へ畳んだ値を基準にすると分布の中心がずれ、半分より多くの窓が
    「居座り」側へ倒れてしまう。"""
    measured = [
        (level * span / arrivals, span)
        for _hour, level, arrivals, span, _cmts in windows
        if arrivals > 0 and span > 0
    ]
    if not measured:
        return None
    reference = _median([d for d, _ in measured])
    if reference <= 0:
        return None
    total = sum(span for _, span in measured)
    churn = sum(span for d, span in measured if d / reference < _DW_CHURN_RATIO)
    sticky = sum(span for d, span in measured if d / reference > _DW_STICKY_RATIO)
    return {"churn": round(churn / total, 4), "sticky": round(sticky / total, 4),
            "steady": round((total - churn - sticky) / total, 4),
            "window_median": round(reference, 1)}


@_stage("dwell")
def reduce_dwell(rows: list) -> dict:
    """視聴者1人あたりの平均滞在時間(Little則 W = L / λ)と、入れ替わりの速さ。

    λは総来場counter(total_viewers)の伸びで、TikTokはこのcounterの定義を公開していない
    (ユニークか延べか、匿名を含むかが不明)。よってWの絶対秒は他の配信者や外部の数字と
    比べられない。同一配信者の中での相対比較にのみ使える。この但し書きは画面側にも出す。

    推定できなかった窓は理由別に数えて返す。埋めないのは、定常でない区間へ無理に
    Little則を当てた値は「それらしい秒数」に見えてしまい、実測と区別が付かないため。"""
    rejects = {k: 0 for k in _DW_REJECT_KEYS}
    per_session = []
    crude = []
    join_ratios = []
    n_windows = 0
    for sess, payload in rows:
        for key, count in zip(_DW_REJECT_KEYS, payload.get("rej") or []):
            rejects[key] += count
        arrivals = payload.get("arr") or 0
        # counterの伸びと入室eventの比。配信ごとに取ってから中央値にする(合計比は
        # 大きい配信1本に支配され、比が揃っているかどうかが見えなくなる)。
        if arrivals > 0:
            join_ratios.append((payload.get("jn") or 0) / arrivals)
        vmin = payload.get("vmin") or 0.0
        if arrivals > 0 and vmin > 0:
            crude.append(vmin * 60.0 / arrivals)
        stats = _dwell_session_stats(payload)
        if stats is None:
            continue
        n_windows += stats["n_windows"]
        stats["unique_id"] = sess["unique_id"]
        stats["avgv"] = payload.get("avgv") or 0.0
        per_session.append(stats)

    candidates = n_windows + sum(rejects.values())
    dwells = [s["dwell"] for s in per_session]
    mean, ci = _dwell_mean_ci(dwells)
    overall = None
    if mean is not None and mean > 0:
        # 代表値は中央値。配信ごとの滞在時間は右に裾を引き、平均は長い数本に引かれる。
        # CIは平均に対してしか厳密に出せないため、平均±CIは精度の目安として併記する。
        center = _median(dwells)
        overall = {
            "dwell_seconds": round(center, 1),
            "mean": round(mean, 1),
            "ci": round(ci, 1) if ci is not None else None,
            "p25": round(_percentile(dwells, 25), 1),
            "p75": round(_percentile(dwells, 75), 1),
            "turnover_per_hour": round(3600.0 / center, 1) if center > 0 else None,
            "n_sessions": len(dwells),
        }

    by_uid: dict = {}
    for stats in per_session:
        by_uid.setdefault(stats["unique_id"], []).append(stats)
    streamers = []
    for uid, group in by_uid.items():
        if len(group) < _DW_MIN_STREAMER_SESSIONS:
            continue
        values = [s["dwell"] for s in group]
        s_mean, s_ci = _dwell_mean_ci(values)
        reference = _median(values)
        windows = [w for s in group for w in s["windows"]]
        streamers.append({
            "unique_id": uid,
            "sessions": len(group),
            "windows": sum(s["n_windows"] for s in group),
            "dwell_seconds": round(reference, 1),
            "mean": round(s_mean, 1),
            "ci": round(s_ci, 1) if s_ci is not None else None,
            "p25": round(_percentile(values, 25), 1),
            "p75": round(_percentile(values, 75), 1),
            "turnover_per_hour": round(3600.0 / reference, 1) if reference > 0 else None,
            "avg_viewers": round(_median([s["level"] for s in group]), 1),
            "mix": _dwell_share(windows),
        })
    streamers.sort(key=lambda s: s["windows"], reverse=True)

    hours = []
    by_hour: dict = {}
    for stats in per_session:
        for hour, level, arrivals, span, _cmts in stats["windows"]:
            if arrivals > 0 and span > 0:
                by_hour.setdefault(hour, []).append(level * span / arrivals)
    for hour in sorted(by_hour):
        values = by_hour[hour]
        hours.append([hour, round(_median(values), 1), len(values)])

    # 妥当性check: 滞在が長いと推定された配信では、視聴時間あたりのCommentも多いはず。
    # 同接(部屋の大きさでchatの速さが変わる)を統制した偏順位相関で見る。Wの分子である
    # 同接そのものとの相関は定義上必ず正になるため、独立なComment側で確かめる。
    paired = [s for s in per_session if s["comments_per_watch_minute"] is not None]
    engagement = None
    if len(paired) >= 3:
        rho = _partial_spearman(
            [s["dwell"] for s in paired],
            [s["comments_per_watch_minute"] for s in paired],
            [[s["avgv"] for s in paired]],
        )
        engagement = {
            "rho": None if rho is None else round(rho, 3),
            "significant": _spearman_significant(rho, len(paired), 1),
            "n": len(paired),
        }

    return {
        "n_sessions": len(rows),
        "n_estimated": len(per_session),
        "windows": n_windows,
        "candidates": candidates,
        "window_seconds": _DW_WINDOW_SECONDS,
        "hour_min_windows": _DW_MIN_HOUR_WINDOWS,
        "rejects": rejects,
        "overall": overall,
        "crude_dwell_seconds": round(_median(crude), 1) if crude else None,
        "crude_n": len(crude),
        "cross_check": {
            "ratio": round(_median(join_ratios), 3) if join_ratios else None,
            "p10": round(_percentile(join_ratios, 10), 3) if join_ratios else None,
            "p90": round(_percentile(join_ratios, 90), 3) if join_ratios else None,
            "n": len(join_ratios),
        },
        "streamers": streamers,
        "hours": hours,
        "engagement": engagement,
    }


_AN_METRIC_LABELS = {
    "viewers_med": "同接(中央値)",
    "coins_per_min": "コイン/分",
    "comments_per_min": "Comment/分",
    "joins_per_min": "入室/分",
    "follow_per_join": "フォロー率(入室あたり)",
}


@_stage("anomaly")
def reduce_anomaly(rows: list) -> dict:
    """配信の異常検知: その配信者自身の過去分布に対する1配信まるごとの水準の逸脱。

    baselineは必ず「自分を除いた」同一配信者の他配信(leave-one-out)。判定したい配信を
    baselineに混ぜると、外れているほど基準が自分に引き寄せられ、逸脱が過小に出る。

    有意性はBH法でFDRを制御する。p値は分布を仮定しない経験p値で、到達できる最小値が
    1/(baseline本数+1)であるため、現在のdata量では多重検定を通過しない。これは手法の
    不備ではなくdata量の上限なので、埋めずに「検出力不足」として本数とともに返す。"""
    per_streamer: dict = {}
    changepoints = []
    n_measured = 0
    for sess, payload in rows:
        metrics = payload.get("m") or {}
        if metrics:
            n_measured += 1
        per_streamer.setdefault(sess["unique_id"], []).append((sess, metrics))
        cp = payload.get("cp")
        if cp:
            before, after = cp.get("before") or 0.0, cp.get("after") or 0.0
            ratio = (after / before) if before > 0 else None
            changepoints.append({
                "session_id": sess["id"],
                "unique_id": sess["unique_id"],
                "started_at": sess["started_at"],
                "at": cp.get("at"),
                "before": before,
                "after": after,
                "ratio": None if ratio is None else round(ratio, 3),
                "p": cp.get("p"),
                "bins": cp.get("bins"),
            })

    findings = []
    coverage = []
    for uid, entries in sorted(per_streamer.items()):
        for metric in _AN_METRICS:
            values = [(s, m[metric]) for s, m in entries if metric in m]
            n = len(values)
            baseline_n = max(0, n - 1)
            if baseline_n < _AN_MIN_BASELINE:
                coverage.append({"unique_id": uid, "metric": metric, "sessions": n,
                                 "status": "insufficient", "baseline": baseline_n})
                continue
            # 到達できる最小p値。これがBHを通れないなら、この配信者・指標では
            # どれだけ外れた配信があっても有意判定は出せない。
            coverage.append({"unique_id": uid, "metric": metric, "sessions": n,
                             "status": "ok", "baseline": baseline_n,
                             "min_p": round(1.0 / (baseline_n + 1), 4)})
            for sess, value in values:
                others = [v for s2, v in values if s2["id"] != sess["id"]]
                z = _robust_z(value, others)
                p = _empirical_p(value, others)
                if z is None or p is None:
                    continue
                findings.append({
                    "session_id": sess["id"],
                    "unique_id": uid,
                    "started_at": sess["started_at"],
                    "metric": metric,
                    "label": _AN_METRIC_LABELS[metric],
                    "value": round(value, 4),
                    "typical": round(_median(others), 4),
                    "p25": round(_percentile(others, 25), 4),
                    "p75": round(_percentile(others, 75), 4),
                    "z": round(z, 2),
                    "p": round(p, 4),
                    "baseline": len(others),
                })

    qvalues = benjamini_hochberg([f["p"] for f in findings])
    for finding, q in zip(findings, qvalues):
        finding["q"] = round(q, 4)
        finding["significant"] = q < _AN_FDR_Q
    findings.sort(key=lambda f: -abs(f["z"]))

    # 検出力の上限。経験p値が到達できる最小値は 1/(baseline+1) で、BHで最小順位の
    # 検定が通るには p <= q/検定数 が要る。両者から「有意判定が出せる最小のbaseline
    # 本数」が決まる。届いていないなら、どれだけ外れた配信があっても有意にはならない。
    n_tests = len(findings)
    power = None
    if n_tests:
        needed_p = _AN_FDR_Q / n_tests
        best_p = min(f["p"] for f in findings)
        power = {
            "tests": n_tests,
            "needed_p": round(needed_p, 6),
            "best_p": round(best_p, 4),
            "needed_baseline": int(math.ceil(1.0 / needed_p)) - 1,
            "reachable": best_p <= needed_p,
        }

    shifts = [
        c for c in changepoints
        if c["p"] is not None and c["p"] <= _AN_CP_ALPHA and c["ratio"] is not None
        and (c["ratio"] <= _AN_CP_MIN_RATIO_DROP or c["ratio"] >= _AN_CP_MIN_RATIO_RISE)
    ]
    shifts.sort(key=lambda c: c["ratio"])

    return {
        "n_sessions": len(rows),
        "n_measured": n_measured,
        "metrics": list(_AN_METRICS),
        "labels": _AN_METRIC_LABELS,
        "fdr_q": _AN_FDR_Q,
        "min_baseline": _AN_MIN_BASELINE,
        "findings": findings,
        "n_significant": sum(1 for f in findings if f["significant"]),
        "power": power,
        "coverage": coverage,
        "changepoints": {
            "tested": len(changepoints),
            "alpha": _AN_CP_ALPHA,
            "bin_seconds": _AN_CP_BIN_SECONDS,
            "block_bins": _AN_CP_BLOCK_BINS,
            "significant": sum(
                1 for c in changepoints if c["p"] is not None and c["p"] <= _AN_CP_ALPHA
            ),
            "shifts": shifts,
        },
    }


def _life_table_curve(table: list) -> Optional[list]:
    """life-tableから累積反応率 1-S(t) をbin境界ごとに返す。

    打ち切り(配信終了で観測が切れた人)を「反応しなかった」と数えると反応率が下に歪む。
    区間ごとに、その区間で打ち切られた人を半分だけリスク集合から引くactuarial補正
    (n - c/2)を入れたKaplan-Meier系の推定量を使う。リスク集合が尽きたらそこで打ち切る。"""
    survival = 1.0
    out = []
    at_risk = sum(ev + cens for ev, cens in table)
    if at_risk <= 0:
        return None
    for events, censored in table:
        effective = at_risk - censored / 2.0
        if effective > 0:
            survival *= 1.0 - events / effective
        out.append(1.0 - survival)
        at_risk -= events + censored
    return out


def _ac_median_latency(table: list) -> Optional[float]:
    """反応した人だけを母集団にした初回反応までの中央値(秒)。

    全体の中央値は定義できない(9割が最後まで反応しないため生存曲線が0.5を下回らない)。
    「反応した人はどれくらいで反応するか」に限れば意味があるので、そちらを返す。
    binの中で線形補間する。"""
    total = sum(ev for ev, _c in table)
    if total <= 0:
        return None
    half = total / 2.0
    cumulative = 0
    low = 0.0
    for i, (events, _censored) in enumerate(table):
        high = _AC_BIN_EDGES[i] if i < len(_AC_BIN_EDGES) else None
        if cumulative + events >= half:
            if high is None or events <= 0:
                return low
            return low + (high - low) * (half - cumulative) / events
        cumulative += events
        if high is None:
            return low
        low = high
    return low


def _ac_horizon_values(curve: Optional[list]) -> dict:
    """bin境界の累積反応率から、画面に出す時点(_AC_HORIZONS)の値を引く。"""
    if curve is None:
        return {h: None for h in _AC_HORIZONS}
    out = {}
    for horizon in _AC_HORIZONS:
        idx = bisect.bisect_left(_AC_BIN_EDGES, horizon)
        out[horizon] = curve[min(idx, len(curve) - 1)]
    return out


def _ac_bootstrap_ci(tables: list, rng) -> dict:
    """sessionを単位にした復元抽出で、各時点の95%CIをpercentileで作る。

    同一配信の視聴者は独立でない(同じ配信者・同じ時間帯・同じ盛り上がりを共有する)ため、
    人を独立標本として扱うGreenwood分散ではCIが過小に出る。clusterごと入れ替える。"""
    if len(tables) < _AC_MIN_SESSIONS:
        return {h: None for h in _AC_HORIZONS}
    n_bins = len(_AC_BIN_EDGES) + 1
    samples: dict = {h: [] for h in _AC_HORIZONS}
    for _ in range(_AC_BOOTSTRAP):
        picked = [tables[rng.randrange(len(tables))] for _ in range(len(tables))]
        pooled = [[0, 0] for _ in range(n_bins)]
        for table in picked:
            for i, (ev, cens) in enumerate(table):
                pooled[i][0] += ev
                pooled[i][1] += cens
        values = _ac_horizon_values(_life_table_curve(pooled))
        for h, v in values.items():
            if v is not None:
                samples[h].append(v)
    out = {}
    for h, vals in samples.items():
        out[h] = (
            [round(_percentile(vals, 2.5), 4), round(_percentile(vals, 97.5), 4)]
            if len(vals) >= _AC_BOOTSTRAP // 2 else None
        )
    return out


@_stage("activation")
def reduce_activation(rows: list) -> dict:
    """入室後どれくらいで最初の反応が出るか、そして何割が無反応のまま去るか。

    likeを含む系列と除く系列を必ず並べて返す。likeはbatch送信で時刻が遅れて付くため
    含む系列は「遅く見える」方向へ、除く系列は初回反応の61.8%を落とすため「反応が
    少なく見える」方向へ、それぞれ別方向に歪む。片方だけでは誤読する。"""
    n_bins = len(_AC_BIN_EDGES) + 1
    pooled = {"wl": [[0, 0] for _ in range(n_bins)], "nl": [[0, 0] for _ in range(n_bins)]}
    per_session = {"wl": [], "nl": []}
    n_persons = 0
    cov = {"act": 0, "act_j": 0, "gift": 0, "gift_j": 0}
    n_sessions = 0
    for _sess, payload in rows:
        if not payload.get("n"):
            continue
        n_sessions += 1
        n_persons += payload["n"]
        for key in ("wl", "nl"):
            table = payload.get(key) or []
            if not table:
                continue
            per_session[key].append(table)
            for i, (ev, cens) in enumerate(table):
                pooled[key][i][0] += ev
                pooled[key][i][1] += cens
        for key in cov:
            cov[key] += payload.get(key) or 0

    rng = random.Random(0)  # 同じdataなら同じCIを返す(画面の値が呼ぶたび揺れないように)
    series = {}
    for key, label in (("wl", "likeを含む"), ("nl", "likeを除く")):
        curve = _life_table_curve(pooled[key])
        point = _ac_horizon_values(curve)
        ci = _ac_bootstrap_ci(per_session[key], rng)
        events = sum(ev for ev, _c in pooled[key])
        series[key] = {
            "label": label,
            "curve": None if curve is None else [round(v, 4) for v in curve],
            "horizons": [
                {"seconds": h,
                 "activated": None if point[h] is None else round(point[h], 4),
                 "ci": ci[h]}
                for h in _AC_HORIZONS
            ],
            "activated": events,
            "activated_ratio": round(events / n_persons, 4) if n_persons else None,
            # 反応した人に限った中央値。全体の中央値は9割が反応しないため存在しない。
            "median_latency": _ac_median_latency(pooled[key]),
        }

    # 被覆: 行動が観測された人のうち、入室が記録されていた割合。ここが低いほど
    # 「入室した人の何%が反応するか」の母集団が欠ける。
    coverage = None
    if cov["act"]:
        missing = cov["act"] - cov["act_j"]
        coverage = {
            "actors": cov["act"],
            "actors_with_join": cov["act_j"],
            "ratio": round(cov["act_j"] / cov["act"], 4),
            "missing": missing,
            # 欠落が engaged 側へ偏っている証拠。gift送信者に限った入室記録率を並べる。
            "gifters": cov["gift"],
            "gifters_with_join": cov["gift_j"],
            "gifter_ratio": round(cov["gift_j"] / cov["gift"], 4) if cov["gift"] else None,
        }

    return {
        "n_sessions": n_sessions,
        "n_persons": n_persons,
        "bin_edges": list(_AC_BIN_EDGES),
        "horizons": list(_AC_HORIZONS),
        "series": series,
        "coverage": coverage,
        "bootstrap": _AC_BOOTSTRAP,
    }


@_stage("retention")
def reduce_retention(rows: list) -> dict:
    """入室→押し上げ: 時刻別の入室レート(棒・件/分)と平均同接(線)、全体の
    「1入室あたりの同接押し上げ」推定。押し上げ = (入室bucketの同接変化の合計 −
    平常drift×入室bucket数) ÷ 入室数。driftは入室のないbucketの平均変化で、
    入室と無関係な増減(自然減など)を差し引く。棒を件/分に正規化するのは、観測時間の
    多い時刻ほど合計が大きく見える偏りを除くため。"""
    hour_joins = [0] * 24
    hour_minutes = [0.0] * 24
    hour_view_sum = [0] * 24
    hour_view_cnt = [0] * 24
    jb_delta = jb_joins = jb_cnt = 0
    nb_delta = nb_cnt = 0
    for sess, payload in rows:
        bucket_min = (sess["bucket_seconds"] or 0) / 60.0
        for h in range(24):
            j, vsum, vcnt = payload["h"][h]
            hour_joins[h] += j
            hour_view_sum[h] += vsum
            hour_view_cnt[h] += vcnt
            hour_minutes[h] += vcnt * bucket_min
        d, tj, cnt = payload["jb"]
        jb_delta += d
        jb_joins += tj
        jb_cnt += cnt
        d, cnt = payload["nb"]
        nb_delta += d
        nb_cnt += cnt
    drift = (nb_delta / nb_cnt) if nb_cnt else 0.0
    lift = ((jb_delta - drift * jb_cnt) / jb_joins) if jb_joins else None
    by_hour = [
        {
            "hour": h,
            "joins": hour_joins[h],
            "join_rate": (
                round(hour_joins[h] / hour_minutes[h], 2) if hour_minutes[h] > 0 else None
            ),
            "viewers": round(hour_view_sum[h] / hour_view_cnt[h], 1) if hour_view_cnt[h] else None,
        }
        for h in range(24)
    ]
    return {
        "overall": {
            "joins": sum(hour_joins),
            "lift_per_join": round(lift, 3) if lift is not None else None,
        },
        "by_hour": by_hour,
        "n_sessions": len(rows),
    }


@_stage("join_context")
def reduce_join_context(rows: list) -> dict:
    battle_seconds = collab_seconds = active_seconds = 0.0
    battle_joins = collab_joins = normal_joins = 0
    n_battles = n_collabs = 0
    for _, p in rows:
        battle_seconds += p["bs"]
        collab_seconds += p["cs"]
        active_seconds += p["as"]
        battle_joins += p["bj"]
        collab_joins += p["cj"]
        normal_joins += p["nj"]
        n_battles += p["nb"]
        n_collabs += p["ncl"]
    total_joins = battle_joins + collab_joins + normal_joins
    normal_seconds = max(0.0, active_seconds - battle_seconds - collab_seconds)

    def _ctx(joins, seconds):
        return {
            "joins": joins,
            "seconds": round(seconds),
            "per_min": round(joins / (seconds / 60), 3) if seconds > 0 else None,
        }

    return {
        "battle": _ctx(battle_joins, battle_seconds),
        "collab": _ctx(collab_joins, collab_seconds),
        "normal": _ctx(normal_joins, normal_seconds),
        "total_joins": total_joins,
        "n_battles": n_battles,
        "n_collabs": n_collabs,
        # コラボ収集は導入済み(table存在)。窓が採れると n_collabs>0 になる。
        "collab_available": True,
    }


@_stage("organic")
def reduce_organic(rows: list) -> dict:
    # 平日(月〜金)/休日(土日)の2系列に別集約。keyはpayload側の "wd"/"he"。
    # 20分経つ前に切れた配信は①と同様に除外する(slotは15分単位のまま)。
    groups = {k: [[0, 0.0, 0] for _ in range(_DAY_SLOTS_15)] for k in ("wd", "he")}
    tot = {"raw": 0, "organic": 0.0, "returning": 0, "engaged": 0,
           "leveled": 0, "share_window": 0}
    stick_gain = 0
    stick_joins = 0
    n_sessions = 0
    for sess, payload in rows:
        if not _session_long_enough(sess):
            continue
        n_sessions += 1
        for k, agg in groups.items():
            for s in range(_DAY_SLOTS_15):
                raw, organic, sw = payload[k][s]
                agg[s][0] += raw
                agg[s][1] += organic
                agg[s][2] += sw
        for k in tot:
            tot[k] += payload["tot"][k]
        stick_gain += payload["stick"][0]
        stick_joins += payload["stick"][1]
    tot["organic"] = round(tot["organic"], 1)

    def _series(agg: list) -> list:
        return [
            {"slot": s, "minute": s * 15, "raw": agg[s][0],
             "organic": round(agg[s][1], 2), "share_window": agg[s][2]}
            for s in range(_DAY_SLOTS_15)
        ]

    return {
        "slot_minutes": 15,
        "weekday": _series(groups["wd"]),
        "holiday": _series(groups["he"]),
        "weekday_raw": sum(s[0] for s in groups["wd"]),
        "holiday_raw": sum(s[0] for s in groups["he"]),
        "totals": tot,
        "returning_ratio": round(tot["returning"] / tot["raw"], 3) if tot["raw"] else 0.0,
        "engaged_ratio": round(tot["engaged"] / tot["raw"], 3) if tot["raw"] else 0.0,
        "share_window_ratio": round(tot["share_window"] / tot["raw"], 3) if tot["raw"] else 0.0,
        "organic_ratio": round(tot["organic"] / tot["raw"], 3) if tot["raw"] else 0.0,
        "stick_rate": round(stick_gain / stick_joins, 3) if stick_joins else None,
        "n_sessions": n_sessions,
        "share_window_seconds": _ORGANIC_SHARE_WINDOW_SECONDS,
    }


# 流入元(clientEnterSource)は "<surface>-<component>" 形式で届く。前半のsurfaceだけを
# 機械的に切り出して粗い括りを併記する。値の意味づけ(discovery/referred等)は
# こちらの解釈でしかないため行わず、TikTokが送ってきた文字列のまま提示する。
_ENTRY_SOURCE_SEPARATOR = "-"
# 流入元の内訳listの上限。これを超えた分は「その他」へ畳む(件数は失わない)。
_ENTRY_SOURCE_TOP_N = 20
FOLLOW_STATUSES = ("following", "mutual", "not_following", "unknown")


def _entry_breakdown(counts: dict, total_measured: int, limit: int) -> list:
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    out = [
        {"key": key, "count": n,
         "ratio": round(n / total_measured, 4) if total_measured else None}
        for key, n in ordered[:limit]
    ]
    rest = sum(n for _, n in ordered[limit:])
    if rest:
        out.append({"key": "(その他)", "count": rest,
                    "ratio": round(rest / total_measured, 4) if total_measured else None})
    return out


def _follow_breakdown(counts: dict, measured: int) -> list:
    return [
        {"key": key, "count": counts.get(key, 0),
         "ratio": round(counts.get(key, 0) / measured, 4) if measured else None}
        for key in FOLLOW_STATUSES
    ]


@_stage("entry_source")
def reduce_entry_source(rows: list) -> dict:
    """流入元とfollow関係の横断集計。分母は必ず「計測できた行」だけにし、計測できた
    session数と被覆率を併記する。計装前のsessionは0件として混ぜず、母数から外す。"""
    src: dict = {}
    join_fs: dict = {}
    eng_fs: dict = {}
    roles = {"sub": [0, 0], "mod": [0, 0], "gg": [0, 0]}
    join_total = join_measured = join_follow_measured = 0
    eng_total = eng_measured = 0
    n_sessions = 0
    n_sessions_measured = 0
    for _, p in rows:
        n_sessions += 1
        j, e = p["j"], p["e"]
        join_total += j["total"]
        join_measured += j["measured"]
        join_follow_measured += j["fm"]
        eng_total += e["total"]
        eng_measured += e["measured"]
        if j["measured"] or j["fm"] or e["measured"]:
            n_sessions_measured += 1
        for key, n in j["src"].items():
            src[key] = src.get(key, 0) + n
        for key, n in j["fs"].items():
            join_fs[key] = join_fs.get(key, 0) + n
        for key, n in e["fs"].items():
            eng_fs[key] = eng_fs.get(key, 0) + n
        for key, pair in e["roles"].items():
            roles[key][0] += pair[0]
            roles[key][1] += pair[1]
    surfaces: dict = {}
    for key, n in src.items():
        surface = key.split(_ENTRY_SOURCE_SEPARATOR, 1)[0] or key
        surfaces[surface] = surfaces.get(surface, 0) + n

    def _role(pair):
        hits, measured = pair
        return {"count": hits, "measured": measured,
                "ratio": round(hits / measured, 4) if measured else None}

    return {
        "joins": {
            "total": join_total,
            "measured": join_measured,
            "unmeasured": join_total - join_measured,
            "coverage": round(join_measured / join_total, 4) if join_total else None,
            "sources": _entry_breakdown(src, join_measured, _ENTRY_SOURCE_TOP_N),
            "surfaces": _entry_breakdown(surfaces, join_measured, _ENTRY_SOURCE_TOP_N),
            "follow": {
                "measured": join_follow_measured,
                "unmeasured": join_total - join_follow_measured,
                "coverage": round(join_follow_measured / join_total, 4) if join_total else None,
                "breakdown": _follow_breakdown(join_fs, join_follow_measured),
            },
        },
        "engaged": {
            "total": eng_total,
            "measured": eng_measured,
            "unmeasured": eng_total - eng_measured,
            "coverage": round(eng_measured / eng_total, 4) if eng_total else None,
            "breakdown": _follow_breakdown(eng_fs, eng_measured),
            "roles": {key: _role(pair) for key, pair in roles.items()},
        },
        "n_sessions": n_sessions,
        "n_sessions_measured": n_sessions_measured,
        "follow_statuses": list(FOLLOW_STATUSES),
    }


# 展開の類型: 末尾窓の得点シェアが一様(tail/duration)の何倍かで分ける。閾値は
# 「一様の1.5倍以上なら終盤型」「0.5倍以下なら序中盤型」という素朴な区切りで、
# 分布から推定した境界ではないため類型名は記述のみに使う。
_BF_TAIL_HEAVY_RATIO = 1.5
_BF_TAIL_LIGHT_RATIO = 0.5
_BF_FORMS = ("1v1", "team", "multi")
_BF_EXCLUSION_REASONS = ("parse", "aborted", "no_end", "short", "no_series", "chimera")


def _bf_rate(k: int, n: int) -> dict:
    return {"n": n, "k": k,
            "rate": round(k / n, 4) if n else None,
            "ci": _wilson_ci(k, n)}


def _bf_tail_stats(shares: list, uniform: list) -> dict:
    """末尾窓の得点シェアの分布と、一様配分に対する類型内訳。"""
    if not shares:
        return {"n": 0, "median": None, "p25": None, "p75": None,
                "uniform_median": None, "heavy": 0, "flat": 0, "light": 0}
    heavy = flat = light = 0
    for share, uni in zip(shares, uniform):
        if uni <= 0:
            continue
        ratio = share / uni
        if ratio >= _BF_TAIL_HEAVY_RATIO:
            heavy += 1
        elif ratio <= _BF_TAIL_LIGHT_RATIO:
            light += 1
        else:
            flat += 1
    return {
        "n": len(shares),
        "median": round(_median(shares), 4),
        "p25": round(_percentile(shares, 25), 4),
        "p75": round(_percentile(shares, 75), 4),
        "uniform_median": round(_median(uniform), 4),
        "heavy": heavy, "flat": flat, "light": light,
    }


@_stage("battle_flow")
def reduce_battle_flow(rows: list) -> dict:
    """Battle展開の横断記述統計。母集団は相手が一意に定まるbattleのみ(1v1・実チーム戦・
    直近rivalを再構成できた個人マルチ)。battle_idは配信者双方が監視対象のとき重複しうる
    ため横断でdedupする(初出のsessionを採用)。

    「残り1分リード時の勝率」は記述統計であって戦術の効果ではない。リードしている側は
    そもそも強い/相手が弱い/課金が乗っているという選択効果を含むため、因果として読めない。"""
    seen = set()
    n_total = 0
    excluded = {reason: 0 for reason in _BF_EXCLUSION_REASONS}
    forms = {form: 0 for form in _BF_FORMS}
    lead_changes = []
    checkpoint = {"own": [0, 0], "opp": [0, 0], "tie": [0, 0]}  # [勝ち, 件数]
    comeback_n = comeback_k = 0
    tail_shares, tail_uniform = [], []
    adj_shares, adj_uniform = [], []
    unresolved_battles = 0
    result_diff = 0
    n_bins = _BF_MAX_REMAINING // _BF_BIN_SECONDS
    bin_gain = [0] * n_bins
    bin_total = [0] * n_bins
    bin_n = [0] * n_bins
    # pooled share(合計÷合計)は少数の高額ギフトに支配されるため、battle単位シェアの
    # 中央値も併記する。両者が大きく離れる帯は「一部のbattleだけで起きたこと」。
    bin_shares = [[] for _ in range(n_bins)]
    n_sessions = 0
    for _, payload in rows:
        n_sessions += 1
        for rec in payload["battles"]:
            bid = rec["bid"]
            if bid:
                if bid in seen:
                    continue
                seen.add(bid)
            n_total += 1
            if not rec["ok"]:
                reason = rec.get("why")
                if reason in excluded:
                    excluded[reason] += 1
                continue
            forms[rec["form"]] = forms.get(rec["form"], 0) + 1
            result_diff += rec.get("res_diff", 0)
            lead_changes.append(rec["lc"])
            result = rec.get("res")
            slot = checkpoint.get(rec["cp"])
            if slot is not None and result in ("win", "lose", "draw"):
                slot[1] += 1
                slot[0] += 1 if result == "win" else 0
                # 逆転: 残り1分時点の優劣が最終結果でひっくり返ったか(引き分けは除く)。
                if rec["cp"] in ("own", "opp") and result in ("win", "lose"):
                    comeback_n += 1
                    if (rec["cp"] == "own") != (result == "win"):
                        comeback_k += 1
            duration = rec["dur"]
            uniform = _BF_TAIL_SECONDS / duration if duration else 0
            tail_raw, total_raw = rec["tail"]
            if total_raw > 0 and uniform > 0:
                tail_shares.append(tail_raw / total_raw)
                tail_uniform.append(uniform)
            adj = rec.get("tail_adj")
            if adj and adj[1] > 0 and uniform > 0:
                adj_shares.append(adj[0] / adj[1])
                adj_uniform.append(uniform)
            if rec.get("cu"):
                unresolved_battles += 1
            for i, gain in enumerate(rec["bins"]):
                if gain is None:
                    continue
                bin_gain[i] += gain
                bin_total[i] += total_raw
                bin_n[i] += 1
                if total_raw > 0:
                    bin_shares[i].append(gain / total_raw)

    hist = {}
    for value in lead_changes:
        key = min(value, _BF_LEAD_CHANGE_CAP)
        hist[key] = hist.get(key, 0) + 1
    bins = [
        {"from": i * _BF_BIN_SECONDS, "to": (i + 1) * _BF_BIN_SECONDS,
         "share": round(bin_gain[i] / bin_total[i], 4) if bin_total[i] else None,
         "median_share": round(_median(bin_shares[i]), 4) if bin_shares[i] else None,
         "n": bin_n[i]}
        for i in range(n_bins)
    ]
    return {
        "n_battles": n_total,
        "n_eligible": sum(forms.values()),
        "n_sessions": n_sessions,
        "excluded": excluded,
        "forms": forms,
        "result_diff": result_diff,
        "lead_changes": {
            "n": len(lead_changes),
            "median": round(_median(lead_changes), 2) if lead_changes else None,
            "p75": round(_percentile(lead_changes, 75), 2) if lead_changes else None,
            "max": max(lead_changes) if lead_changes else None,
            "hist": [{"changes": key, "count": hist[key],
                      "capped": key >= _BF_LEAD_CHANGE_CAP}
                     for key in sorted(hist)],
        },
        "checkpoint": {
            "seconds": _BF_LEAD_CHECKPOINT_SECONDS,
            "own": _bf_rate(checkpoint["own"][0], checkpoint["own"][1]),
            "opp": _bf_rate(checkpoint["opp"][0], checkpoint["opp"][1]),
            "tie": _bf_rate(checkpoint["tie"][0], checkpoint["tie"][1]),
            "comeback": _bf_rate(comeback_k, comeback_n),
        },
        "tail": {
            "seconds": _BF_TAIL_SECONDS,
            "raw": _bf_tail_stats(tail_shares, tail_uniform),
            "adjusted": _bf_tail_stats(adj_shares, adj_uniform),
            "unresolved_battles": unresolved_battles,
            "heavy_ratio": _BF_TAIL_HEAVY_RATIO,
            "light_ratio": _BF_TAIL_LIGHT_RATIO,
        },
        "bins": bins,
        "bin_seconds": _BF_BIN_SECONDS,
        "min_duration_seconds": _BF_MIN_DURATION_SECONDS,
    }


def _cv_stat(values: list) -> dict:
    """指標ごとに対象session数を必ず併記する。値が無ければ0ではなくNone(計測不能)。"""
    if not values:
        return {"n": 0, "median": None, "p25": None, "p75": None, "max": None}
    return {"n": len(values),
            "median": round(_median(values), 2),
            "p25": round(_percentile(values, 25), 2),
            "p75": round(_percentile(values, 75), 2),
            "max": round(max(values), 2)}


@_stage("coverage")
def reduce_coverage(rows: list, media: list) -> dict:
    """収集カバレッジ。指標ごとに母数が違うので、対象session数を個別に返す。

    接続系markerの計装(conn_instrumentation)より前のsessionは切断が記録されておらず、
    欠測秒数を0と出すと「存在しない健全性」の提示になる。計測不能として別掲し、
    欠測系の分母には一切入れない。録画率・STT率・sampling間隔は旧sessionでも正しい。

    mediaは (session_id, 録画のstarted_at/ended_at/status, 転写有無)の生row列。録画の
    ended_atも転写もsessionが終わった後から埋まるため、payload cacheへは載せず都度集計する。"""
    n_sessions = 0
    n_instrumented = 0
    n_ended = 0
    delays = []
    gap_seconds = []
    gap_ratios = []
    gap_count = 0
    gap_unplanned = 0
    gap_open_end = 0
    n_gap_measured = 0
    sample_median = []
    sample_p95 = []
    sample_max = []
    durations = {}
    for sess, payload in rows:
        n_sessions += 1
        duration = payload["dur"]
        if duration is not None:
            n_ended += 1
            durations[sess["id"]] = duration
        if payload["inst"]:
            n_instrumented += 1
        if payload["delay"] is not None:
            delays.append(payload["delay"])
        gaps = payload["gaps"]
        if gaps is not None and duration:
            n_gap_measured += 1
            gap_seconds.append(gaps["sec"])
            gap_ratios.append(gaps["sec"] / duration)
            gap_count += gaps["n"]
            gap_unplanned += gaps["unplanned"]
            gap_open_end += gaps["open_end"]
        smp = payload["smp"]
        if smp:
            sample_median.append(smp["median"])
            sample_p95.append(smp["p95"])
            sample_max.append(smp["max"])

    # 録画カバレッジ: session窓へclampした録画秒 / session秒。ended_atが無い録画
    # (収録中・中断)は尺が確定していないので、そのsessionごと計測不能にする。
    recorded = {}
    unknown_span = set()
    rec_total = 0
    rec_transcribed = 0
    for row in media:
        sid = row["session_id"]
        if row["status"] == "completed":
            rec_total += 1
            rec_transcribed += 1 if row["has_transcript"] else 0
        if sid is None or sid not in durations:
            continue
        started, ended = row["started_at"], row["ended_at"]
        if started is None or ended is None or ended <= started:
            unknown_span.add(sid)
            continue
        recorded[sid] = recorded.get(sid, 0.0) + (ended - started)
    rec_ratios = []
    for sid, duration in durations.items():
        if sid in unknown_span or duration <= 0:
            continue
        # 録画は分割されうるので合計する。clock skewでsession尺を超える場合は1.0止め。
        rec_ratios.append(min(1.0, recorded.get(sid, 0.0) / duration))

    return {
        "n_sessions": n_sessions,
        "n_sessions_ended": n_ended,
        "instrumented": {
            "measured": n_instrumented,
            "unmeasured": n_sessions - n_instrumented,
            "coverage": round(n_instrumented / n_sessions, 4) if n_sessions else None,
        },
        "start_delay": _cv_stat(delays),
        "gaps": {
            "n_sessions": n_gap_measured,
            "seconds": _cv_stat(gap_seconds),
            "ratio": _cv_stat([r * 100 for r in gap_ratios]),
            "total_seconds": round(sum(gap_seconds), 1),
            "count": gap_count,
            "unplanned": gap_unplanned,
            "open_end": gap_open_end,
        },
        "sampling": {
            "n_sessions": len(sample_median),
            "median": _cv_stat(sample_median),
            "p95": _cv_stat(sample_p95),
            "worst": round(max(sample_max), 2) if sample_max else None,
            "percentile": _CV_GAP_PERCENTILE,
        },
        "recording": {
            "n_sessions": len(rec_ratios),
            "unmeasured_sessions": len(unknown_span),
            "ratio": _cv_stat([r * 100 for r in rec_ratios]),
            "full": sum(1 for r in rec_ratios if r >= 0.99),
            "none": sum(1 for r in rec_ratios if r <= 0.0),
        },
        "transcript": {
            "recordings": rec_total,
            "transcribed": rec_transcribed,
            "ratio": round(rec_transcribed / rec_total, 4) if rec_total else None,
        },
    }
