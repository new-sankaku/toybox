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
import json
from typing import Optional

# Battleのグローブ(Critical Strike card)刺さり率をギフト単価で集約するcoin帯。
GLOVE_COIN_BUCKETS = [
    (1, 15), (16, 50), (51, 100), (101, 500), (501, 1000),
    (1001, 3000), (3001, 6000), (6001, 12000), (12001, 25000), (25001, 45000),
]

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

# per-session payloadのschema version。計算ロジックを変えたら該当kindを+1すると
# 既存cache行がlazyに再計算される。
CACHE_VERSIONS = {
    "summary": 1,
    "time_index": 1,
    "relations": 1,
    "peri_share": 1,
    "peri_battle": 1,
    "battle_ratio": 1,
    "glove": 1,
    "join_quality": 1,
    "scale_efficiency": 1,
    "retention": 1,
    "join_context": 1,
    "organic": 1,
}
KINDS = tuple(CACHE_VERSIONS)

_SQL_HOUR = "CAST(strftime('%H', {col}, 'unixepoch', 'localtime') AS INTEGER)"


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


def _partial_spearman(a: list, b: list, control: list) -> Optional[float]:
    """control(scale=同接)の影響を除いたa,bの偏順位相関。ランク残差同士のPearson。"""
    if len(a) < 4:
        return None
    ra, rb, rc = _rank_average(a), _rank_average(b), _rank_average(control)

    def _residualize(y: list, x: list):
        n = len(x)
        mx = sum(x) / n
        my = sum(y) / n
        sxx = sum((xi - mx) ** 2 for xi in x)
        if sxx <= 0:
            return None
        sxy = sum((x[i] - mx) * (y[i] - my) for i in range(n))
        slope = sxy / sxx
        return [y[i] - (my + slope * (x[i] - mx)) for i in range(n)]

    era = _residualize(ra, rc)
    erb = _residualize(rb, rc)
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
    step = max(1, n // lorenz_points)
    running = 0
    for i, v in enumerate(vals):
        running += v
        if (i + 1) % step == 0 or i == n - 1:
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


def _peri_aggregate(windows: list):
    """baseline差分済みの窓群(各長さ同一)を平均し、95%CI半幅を返す。標本不足は(None,None)。"""
    n = len(windows)
    if n < _PERI_MIN_EVENTS:
        return None, None
    length = len(windows[0])
    mean = [sum(w[i] for w in windows) / n for i in range(length)]
    if n < 2:
        return mean, [0.0] * length
    ci = []
    for i in range(length):
        var = sum((w[i] - mean[i]) ** 2 for w in windows) / (n - 1)
        ci.append(1.96 * (var ** 0.5) / (n ** 0.5))
    return mean, ci


def _chunked(seq: list, size: int = 500):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


# ---- per-session payload計算 -------------------------------------------------
# 各関数は1 sessionの中間集計(JSON化可能なdict)を返す。終了済みsessionでは結果が
# 不変になるよう、session内で閉じた情報+その時点で確定済みの外部情報のみを使う。

def _payload_summary(conn, sess: dict) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS nb, COALESCE(SUM(joins), 0) AS j,"
        " COALESCE(SUM(diamonds), 0) AS d, COALESCE(SUM(comments), 0) AS c"
        " FROM buckets WHERE session_id = ?",
        (sess["id"],),
    ).fetchone()
    return {
        "nb": row["nb"],
        "act": row["nb"] * (sess["bucket_seconds"] or 0),
        "j": row["j"],
        "d": row["d"],
        "c": row["c"],
    }


def _payload_time_index(conn, sess: dict) -> dict:
    """(date,hour)ごとの全指標bucket合計。1観測 = (session,date,hour)。"""
    rows = conn.execute(
        "SELECT CAST(strftime('%w', start, 'unixepoch', 'localtime') AS INTEGER) AS dow,"
        f" {_SQL_HOUR.format(col='start')} AS hour,"
        " COUNT(*) AS nb, SUM(joins) AS joins, SUM(comments) AS comments,"
        " SUM(diamonds) AS diamonds, SUM(likes) AS likes, SUM(follows) AS follows"
        " FROM buckets WHERE session_id = ?"
        " GROUP BY strftime('%Y-%m-%d', start, 'unixepoch', 'localtime'), hour",
        (sess["id"],),
    ).fetchall()
    return {
        "cells": [
            [r["dow"], r["hour"], r["nb"], r["joins"] or 0, r["comments"] or 0,
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
        onset_rows = conn.execute(
            "SELECT time FROM markers WHERE session_id = ? AND kind = 'battle'", (sid,)
        ).fetchall()
    refractory_bins = max(1, int(refractory // bin_s))
    onset_abs = _collapse_onsets(
        sorted({int(r["time"] // bin_s) for r in onset_rows}), refractory_bins
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
        guard = pre + post
        forbidden: set = set()
        for ob in onset_bins:
            forbidden.update(range(ob - guard, ob + guard + 1))
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
    """Battle窓内 vs 窓外のレート比(session内の各battle)。battle_idの横断dedupは
    reduce側で行うため、窓が有効な全battleを順序どおり記録する。"""
    sid = sess["id"]
    s_start = sess["started_at"]
    s_end = sess["ended_at"]
    rows = conn.execute(
        "SELECT battle_id AS bid, data_json AS d FROM battles WHERE session_id = ?"
        " ORDER BY rowid",
        (sid,),
    ).fetchall()
    battles = []
    totals = None
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
        if s_end is None:
            # 収集中sessionは窓外時間が確定しない。確定後(finalize)に集計する。
            continue
        duration = s_end - s_start
        inside = min(end_time, s_end) - max(start_time, s_start)
        if inside <= 0 or duration <= inside:
            continue
        outside = duration - inside
        if totals is None:
            trows = conn.execute(
                "SELECT kind, COUNT(*) AS c, COALESCE(SUM(diamonds), 0) AS d"
                " FROM events WHERE session_id = ? GROUP BY kind",
                (sid,),
            ).fetchall()
            totals = {r["kind"]: {"c": r["c"], "d": r["d"]} for r in trows}
        irows = conn.execute(
            "SELECT kind, COUNT(*) AS c, COALESCE(SUM(diamonds), 0) AS d"
            " FROM events WHERE session_id = ? AND time >= ? AND time < ? GROUP BY kind",
            (sid, start_time, end_time),
        ).fetchall()
        inside_stat = {r["kind"]: {"c": r["c"], "d": r["d"]} for r in irows}
        up = {}
        for metric, kind in (("joins", "join"), ("comments", "comment"), ("follows", "follow")):
            in_c = inside_stat.get(kind, {}).get("c", 0)
            out_c = totals.get(kind, {}).get("c", 0) - in_c
            in_rate = in_c / inside
            out_rate = out_c / outside
            up[metric] = (in_rate / out_rate) if out_rate > 0 else None
        in_d = inside_stat.get("gift", {}).get("d", 0)
        out_d = totals.get("gift", {}).get("d", 0) - in_d
        in_dr = in_d / inside
        out_dr = out_d / outside
        up["diamonds"] = (in_dr / out_dr) if out_dr > 0 else None
        rec["up"] = up
    return {"battles": battles}


def _payload_glove(conn, sess: dict) -> dict:
    """自陣グローブ窓中ギフトの(単価, crit)記録。単価不明分のgift_id→単価解決は
    後から観測が増えるほど解けるためreduce側(全期間の単価表)で行う。"""
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
            [ev.get("gift_id"), ev.get("coins"), 1 if ev.get("crit") else 0]
            for ev in (battle.get("glove_events") or [])
        ]
    return {"battles": battles}


def _payload_join_quality(conn, sess: dict) -> dict:
    """時間帯別の入室数と、うち初見(users.first_seenが当該session開始以降)の数。"""
    rows = conn.execute(
        f"SELECT {_SQL_HOUR.format(col='e.time')} AS hour,"
        " SUM(CASE WHEN u.first_seen IS NOT NULL AND u.first_seen >= ? THEN 1 ELSE 0 END) AS newcomers,"
        " COUNT(*) AS total"
        " FROM events e LEFT JOIN users u ON u.identity_key = e.identity_key"
        " WHERE e.session_id = ? AND e.kind = 'join'"
        " GROUP BY hour",
        (sess["started_at"], sess["id"]),
    ).fetchall()
    return {"h": [[r["hour"], r["newcomers"] or 0, r["total"] or 0] for r in rows]}


def _payload_scale_efficiency(conn, sess: dict) -> dict:
    peak = conn.execute(
        "SELECT MAX(viewers) AS p FROM buckets WHERE session_id = ?", (sess["id"],)
    ).fetchone()["p"]
    coins = conn.execute(
        "SELECT COALESCE(SUM(diamonds), 0) AS c FROM events"
        " WHERE session_id = ? AND kind = 'gift'",
        (sess["id"],),
    ).fetchone()["c"]
    return {"peak": peak or 0, "coins": coins or 0}


def _payload_retention(conn, sess: dict) -> dict:
    """時刻別の入室/同接と、session内の連続bucket間の同接純増(stick rate分子分母)。"""
    rows = conn.execute(
        f"SELECT joins, viewers, {_SQL_HOUR.format(col='start')} AS hour"
        " FROM buckets WHERE session_id = ? ORDER BY start",
        (sess["id"],),
    ).fetchall()
    hours = [[0, 0, 0] for _ in range(24)]  # [joins, viewers_sum, viewers_cnt]
    total_joins = 0
    net_change = 0
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
            total_joins += j
            net_change += delta
    return {"h": hours, "tj": total_joins, "nc": net_change}


def _payload_join_context(conn, sess: dict) -> dict:
    """Battle中 / コラボ(非BattleのLinkMic)中 / 平時 の秒数と入室数(session内)。"""
    sid = sess["id"]
    s_start = sess["started_at"]
    nb = conn.execute(
        "SELECT COUNT(*) AS n FROM buckets WHERE session_id = ?", (sid,)
    ).fetchone()["n"]
    sec = (nb or 0) * (sess["bucket_seconds"] or 0)
    # 収集中(ended_atなし)は稼働秒で終端を近似。
    span_end = sess["ended_at"] if sess["ended_at"] is not None else (s_start + sec)

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
    return {
        "bs": _total_span(b_ints),
        "cs": _total_span(collab_only),
        "as": sec,
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
        f" {_SQL_HOUR.format(col='time')} AS hour"
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
    # 2周目: join を weight 付けし時刻別に集約。share反応窓の判定も行う。
    hours = [[0, 0.0, 0] for _ in range(24)]  # [raw, organic, share_window]
    tot = {"raw": 0, "organic": 0.0, "returning": 0, "engaged": 0,
           "leveled": 0, "share_window": 0}
    for r in ev_rows:
        if r["kind"] != "join":
            continue
        key, h = r["key"], r["hour"]
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
        hours[h][0] += 1
        hours[h][1] += w
        tot["raw"] += 1
        tot["organic"] += w
        if is_returning:
            tot["returning"] += 1
        if is_engaged:
            tot["engaged"] += 1
        if has_level:
            tot["leveled"] += 1
        if in_window:
            hours[h][2] += 1
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
    return {"h": hours, "tot": tot, "stick": [stick_gain, stick_joins]}


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
}


def compute_payload(conn, sess: dict, kind: str) -> dict:
    return _PAYLOAD_FUNCS[kind](conn, sess)


# ---- 横断reduce(API応答の組み立て) --------------------------------------------
# rowsは (sessメタdict, payload dict) のリスト。呼び出し側でstarted_at昇順に揃える。

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


# time_indexのpayload cell内の指標位置([dow, hour, nb, joins, comments, diamonds, likes, follows])。
_TI_CELL_POS = {m: 3 + i for i, m in enumerate(INDEX_METRICS)}


def reduce_time_index(rows: list, metric: str) -> dict:
    """時間帯インデックス: 各配信の平均レートを1.0とした時間帯ごとの相対倍率。
    配信ごとに自分の平均で正規化してから配信横断で中央値を取るので、規模差・外れ値
    に強い。曜日(月〜日)別に分割。1観測 = (session,date,hour)。"""
    pos = _TI_CELL_POS.get(metric)
    if pos is None:
        raise ValueError(f"unsupported index metric: {metric}")
    dow_buckets = [[[] for _ in range(24)] for _ in range(7)]
    all_buckets = [[] for _ in range(24)]
    n_sessions = 0
    for _, payload in rows:
        cells = payload["cells"]
        base_val = sum(c[pos] or 0 for c in cells)
        base_nb = sum(c[2] or 0 for c in cells)
        if base_nb <= 0 or base_val <= 0:
            continue
        baseline_rate = base_val / base_nb
        contributed = False
        for c in cells:
            nb = c[2] or 0
            if nb <= 0:
                continue
            hour_rate = (c[pos] or 0) / nb
            index = hour_rate / baseline_rate
            all_buckets[c[1]].append(index)
            dow_buckets[c[0]][c[1]].append(index)
            contributed = True
        if contributed:
            n_sessions += 1

    def _cell(values: list) -> dict:
        n = len(values)
        return {"index": round(_median(values), 3) if n else None, "n": n}

    hours = []
    for h in range(24):
        hours.append(
            {
                "hour": h,
                "all": _cell(all_buckets[h]),
                # dow[0..6] = 日..土。frontendは表示順を月始まりに並べ替える。
                "dow": [_cell(dow_buckets[d][h]) for d in range(7)],
            }
        )
    return {
        "metric": metric,
        "hours": hours,
        "n_sessions": n_sessions,
        "n_observations": sum(len(b) for b in all_buckets),
    }


def reduce_relations(rows: list) -> dict:
    """指標間の関連(配信単位)。1配信 = 1観測として、Spearman順位相関で突き合わせる。
    素の相関はscale交絡(大箱は全指標が同時に多い)で過大になるため、同接(viewers)を
    制御した偏相関を併せて返す。"""
    obs = [p for _, p in rows if p["n"] > 0]
    columns = {m: [p[m] or 0 for p in obs] for m in RELATION_METRICS}
    matrix = {}
    partial = {}
    control = columns["viewers"]
    for a in RELATION_METRICS:
        matrix[a] = {}
        partial[a] = {}
        for b in RELATION_METRICS:
            matrix[a][b] = 1.0 if a == b else _spearman(columns[a], columns[b])
            if a == b:
                partial[a][b] = 1.0
            elif a == "viewers" or b == "viewers":
                # 制御変数自身との偏相関は定義できない。
                partial[a][b] = None
            else:
                partial[a][b] = _partial_spearman(columns[a], columns[b], control)
    return {
        "metrics": RELATION_METRICS,
        "matrix": matrix,
        "partial": partial,
        "control": "viewers",
        "n_sessions": len(obs),
    }


def reduce_peri(rows: list, treatment: str) -> dict:
    """event-study(peri-event)の横断pool。各sessionの差分済み窓を集めて平均し、
    placebo帯・95%CIと共に返す。"""
    bin_s = _PERI_BIN_SECONDS
    pre, post = _PERI_PRE_BINS, _PERI_POST_BINS
    win_len = pre + post + 1
    ev_windows: list = []
    pl_windows: list = []
    total_joins = 0
    total_bins = 0
    n_sessions = 0
    for _, p in rows:
        if not p.get("q"):
            continue
        total_joins += p["j"]
        total_bins += p["b"]
        n_sessions += 1
        ev_windows.extend(p["ev"])
        pl_windows.extend(p["pl"])
    lags = [(-pre + i) * bin_s for i in range(win_len)]
    baseline_rate = (total_joins / total_bins) if total_bins else 0.0
    mean, ci = _peri_aggregate(ev_windows)
    pmean, pci = _peri_aggregate(pl_windows)
    if mean is None:
        return {
            "treatment": treatment,
            "available": False,
            "n_events": len(ev_windows),
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
        "n_events": len(ev_windows),
        "n_placebo": len(pl_windows),
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


def reduce_glove(rows: list, unit_coins: dict) -> dict:
    """グローブ(Critical Strike card=gift 5倍化)のcoin帯別発動率。unit_coinsは
    gift_id→単価(全期間のGift eventから解決)で、単価未記録のグローブ窓ギフトを補完する。"""
    buckets = [{"lo": lo, "hi": hi, "gifts": 0, "crits": 0} for lo, hi in GLOVE_COIN_BUCKETS]

    def _bucket_for(coins: float):
        for b in buckets:
            if b["lo"] <= coins <= b["hi"]:
                return b
        return None

    n_windows = n_battles = unresolved = 0
    seen = set()
    for _, payload in rows:
        for rec in payload["battles"]:
            bid = rec["bid"]
            if bid:
                if bid in seen:
                    continue
                seen.add(bid)
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
                    continue
                b["gifts"] += 1
                if crit:
                    b["crits"] += 1
    out_buckets = [
        {
            "label": f"{b['lo']}-{b['hi']}",
            "lo": b["lo"], "hi": b["hi"],
            "gifts": b["gifts"], "crits": b["crits"],
            "rate": (b["crits"] / b["gifts"] * 100) if b["gifts"] else None,
        }
        for b in buckets
    ]
    total_gifts = sum(b["gifts"] for b in buckets)
    total_crits = sum(b["crits"] for b in buckets)
    return {
        "buckets": out_buckets,
        "total_gifts": total_gifts,
        "total_crits": total_crits,
        "overall_rate": (total_crits / total_gifts * 100) if total_gifts else None,
        "n_windows": n_windows,
        "n_battles": n_battles,
        "unresolved": unresolved,
    }


def reduce_join_quality(rows: list) -> dict:
    """入室の質: 入室者のうち初見(我々が初めて観測)の比率を時間帯別に。"""
    by_hour = [[0, 0] for _ in range(24)]
    for _, payload in rows:
        for hour, new, total in payload["h"]:
            by_hour[hour][0] += new
            by_hour[hour][1] += total
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
    }


def reduce_scale_efficiency(rows: list, owners: dict) -> dict:
    """規模 vs 効率: 配信者ごとに 平均同接(規模) と 同接あたりコイン(効率)。
    Peakは配信ごとの中央値で頑健化。1点=配信者。"""
    by_uid: dict = {}
    for sess, payload in rows:
        g = by_uid.setdefault(sess["unique_id"], {"peaks": [], "coins": 0})
        g["peaks"].append(payload["peak"] or 0)
        g["coins"] += payload["coins"] or 0
    result = []
    for uid, g in by_uid.items():
        peaks = [p for p in g["peaks"] if p > 0]
        if not peaks:
            continue
        median_peak = _median(peaks)
        sum_peaks = sum(peaks)
        owner = owners.get(uid)
        result.append(
            {
                "unique_id": uid,
                "nickname": (owner["nickname"] if owner else "") or uid,
                "avatar": (owner["avatar"] if owner else "") or "",
                "sessions": len(g["peaks"]),
                "avg_viewers": round(median_peak, 1),
                "coins": g["coins"],
                "coins_per_viewer": round(g["coins"] / sum_peaks, 2) if sum_peaks > 0 else 0.0,
            }
        )
    result.sort(key=lambda x: x["coins"], reverse=True)
    return {"streamers": result}


def reduce_retention(rows: list) -> dict:
    """入室→定着: 時刻別の入室(棒)と平均同接(線)、全体のstick rate(=Σ純増/Σ入室)。"""
    hour_joins = [0] * 24
    hour_view_sum = [0] * 24
    hour_view_cnt = [0] * 24
    total_joins = 0
    net_change = 0
    for _, payload in rows:
        for h in range(24):
            j, vsum, vcnt = payload["h"][h]
            hour_joins[h] += j
            hour_view_sum[h] += vsum
            hour_view_cnt[h] += vcnt
        total_joins += payload["tj"]
        net_change += payload["nc"]
    by_hour = [
        {
            "hour": h,
            "joins": hour_joins[h],
            "viewers": round(hour_view_sum[h] / hour_view_cnt[h], 1) if hour_view_cnt[h] else None,
        }
        for h in range(24)
    ]
    return {
        "overall": {
            "joins": total_joins,
            "net_change": net_change,
            "retained_per_join": round(net_change / total_joins, 3) if total_joins else None,
        },
        "by_hour": by_hour,
    }


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


def reduce_organic(rows: list) -> dict:
    hours = [{"raw": 0, "organic": 0.0, "share_window": 0} for _ in range(24)]
    tot = {"raw": 0, "organic": 0.0, "returning": 0, "engaged": 0,
           "leveled": 0, "share_window": 0}
    stick_gain = 0
    stick_joins = 0
    for _, payload in rows:
        for h in range(24):
            raw, organic, sw = payload["h"][h]
            hours[h]["raw"] += raw
            hours[h]["organic"] += organic
            hours[h]["share_window"] += sw
        for k in tot:
            tot[k] += payload["tot"][k]
        stick_gain += payload["stick"][0]
        stick_joins += payload["stick"][1]
    for h in hours:
        h["organic"] = round(h["organic"], 2)
    tot["organic"] = round(tot["organic"], 1)
    return {
        "hours": [{"hour": h, **hours[h]} for h in range(24)],
        "totals": tot,
        "returning_ratio": round(tot["returning"] / tot["raw"], 3) if tot["raw"] else 0.0,
        "engaged_ratio": round(tot["engaged"] / tot["raw"], 3) if tot["raw"] else 0.0,
        "share_window_ratio": round(tot["share_window"] / tot["raw"], 3) if tot["raw"] else 0.0,
        "organic_ratio": round(tot["organic"] / tot["raw"], 3) if tot["raw"] else 0.0,
        "stick_rate": round(stick_gain / stick_joins, 3) if stick_joins else None,
        "n_sessions": len(rows),
        "share_window_seconds": _ORGANIC_SHARE_WINDOW_SECONDS,
    }
