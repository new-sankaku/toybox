"""配信者別の集計画面(履歴・profile・cohort・見どころ)と全体dashboard。

境界の理由: 「1人の配信者」あるいは「監視配信者の横並び」を人が読む形へ組み立てる
読み取り専用の集計。個々のtableのCRUDは持たず、他mixinが書いたものを読むだけである。
重い集計が集中するため、_read_connection() を使う箇所もここに偏る。

lock契約: lock保持前提のmethodは無い。身元解決(_owner_handles_locked /
  _latest_owner_handles_locked(users))を使うmethodは、その呼び出しだけを自分で取った
  self._lock の内側に置く。集計本体を _read_connection() で流すmethodはそれ以外に
  self._lock を取らない(session_rankings は身元解決を使わないため一度も取らない)。
"""
import json
import time
from datetime import datetime, timedelta

from tictok.core.battle import annotate_result, gift_window_end, gift_window_fallback_duration
from tictok.core.collab import COLLAB_WINDOW_VERSION
from tictok.core.league import display_league_sql

from tictok.store._common import (
    _BATTLE_KEY_CONTRIB_DIAMONDS,
    _BATTLE_NO_CONTEST_SCORE,
    _EXCLUDE_RESTRICTED,
    _EXCLUDE_RESTRICTED_NO_ALIAS,
    _SESSION_TOTALS_CTE,
    _STREAMER_TOTALS_SELECT,
    _coop_summary,
    _covering_recording,
    _opponent_key,
    logger,
)


# 実弾(コイン)の大口帯。その日の合計で判定するため、1回のGiftの額ではなく同じ人の同日の
# 積み上げで数える。帯は排他(100〜1K / 1K〜5K / …)にして、同じ人を帯の数だけ数えない。
# 閾値はここが唯一の定義で、labelごと画面へ渡す(frontend側で数値を再掲しない)。
# 10K以上は元の3帯(10K〜50K / 50K〜100K / 100K↑)では中が見えないので、既存の境目
# (10K・50K・100K)を保ったまま内側を割る。境目を動かすと過去に読んだ帯の人数と
# 意味が変わるため、割るときは足すだけにする。
_WHALE_TIERS = (
    100,
    1000, 5000, 10000, 20000, 30000, 40000, 50000, 75000, 100000, 200000, 300000,
)

# 最上段の合計が名乗る下限。「大口」と呼ぶのは1K以上で、その手前の100〜1Kは大口へ育つ前の
# 層として帯だけ出し、合計には積まない(合計が全帯の和でなくなるのはこのためで、画面側も
# 同じ下限から段の名前と案内文を作る)。帯の境目そのものを指すこと — 境目に無い額を置くと
# 合計がどの帯からの積み上げなのか対応が取れない。indexは不一致ならimport時に落とす。
_WHALE_TOTAL_MIN = 1000
_WHALE_TOTAL_INDEX = _WHALE_TIERS.index(_WHALE_TOTAL_MIN)

# cohortで「その日その人が居た」と数えるevent。giftだけでなく在室の痕跡すべてを採るのが
# cohortの母集合の定義で、この並びがcacheに載る値を決めるため、変えたら版を上げること。
_COHORT_EVENT_KINDS = (
    "join", "comment", "like", "follow", "share", "subscribe", "gift",
)
# streamer_cohortのsession単位cache。analytics_session_cache表を間借りする(session削除で
# ON DELETE CASCADEが効き、表を増やさずに済む)。
# 版をanalytics.CACHE_VERSIONSへ置かないのは、あちらのkind一覧が
# 「analytics.compute_payloadが計算できるもの」の定義でもあるためで、混ぜるとfinalize時の
# 全kind計算がこのkindを計算しようとして落ちる。
# payloadの形か日の切り方を変えたらここを+1すると、既存cache行がlazyに作り直される。
_COHORT_CACHE_KIND = "cohort_daily"
_COHORT_CACHE_VERSION = 1
# 時間帯heatmap(曜日×時×15分)のsession単位cache。cohortと同じ間借り。cellの刻みか
# strftimeの書式を変えたら+1する。
_HEATMAP_CACHE_KIND = "heatmap_quarter"
_HEATMAP_CACHE_VERSION = 1
# 同接の水準(時間加重平均・宝箱窓を除いた平均・観測秒)のsession単位cache。cohort/heatmapと
# 同じ間借り。_viewer_levels は既にsession単位のdictを返すので、そのまま1行ずつ載る。
# 平均の出し方・gapの上限・宝箱窓の扱いを変えたら+1する。
_VIEWER_LEVEL_CACHE_KIND = "viewer_level"
_VIEWER_LEVEL_CACHE_VERSION = 1


def _coin_label(value: int) -> str:
    """コイン額の短縮表記(1000→1K, 100000→100K)。帯のlabelに使う。"""
    if value >= 1000:
        scaled = value / 1000
        return (f"{scaled:.0f}" if scaled == int(scaled) else f"{scaled:g}") + "K"
    return str(value)


# ---- 期間別ランキングの期間 ----
# 暦どおりに切る(月=1日〜末日 / 週=月曜〜日曜 / 日=0時〜24時)。ローカル時刻で切るのは
# heatmap・cohortと同じ軸へ揃えるためで、画面ごとに日の境目が違う状態を作らない。
# SQL側の式(_PERIOD_SQL)とPython側の_period_keyは同じ境界を出すこと。片方だけ直すと、
# 期間の一覧と一覧の中身が別の切り方になり、合計が合わない。
RANKING_GRANULARITIES = ("month", "week", "day")
_PERIOD_SQL = {
    "month": "strftime('%Y-%m', {col}, 'unixepoch', 'localtime')",
    # 週の代表はその週の月曜。'weekday 0' は次の日曜(その日が日曜ならその日)へ送るので、
    # 6日戻すと同じ週の月曜になる。
    "week": "date({col}, 'unixepoch', 'localtime', 'weekday 0', '-6 days')",
    "day": "date({col}, 'unixepoch', 'localtime')",
}
# 期間の一覧に載せる上限と、一覧を組むループの止め値。時刻が壊れた行が1つ混じるだけで
# 1970年からの日付が並ぶため、無制限に回さない。切ったときは件数を画面へ返す(黙って
# 切ると「この配信者はこの期間しか配信していない」と読めてしまう)。
_RANKING_PERIOD_MAX = 2000
_RANKING_PERIOD_SCAN_MAX = 40000
# 人×期間の一覧が持つ列(期間)と行(人)。列を増やすほどBattle窓の解決が伸びるので上限を
# 置く。上限は粒度ごとに違う — 月は1列の中に入る戦が日の30倍あり、同じ列数では持たない。
_MATRIX_COLUMNS = {"day": 14, "week": 12, "month": 12}
_MATRIX_COLUMNS_MAX = {"day": 60, "week": 26, "month": 24}
_MATRIX_ROWS = 40


def _period_key(ts: float, granularity: str) -> str:
    """POSIX秒が属する期間のkey。週は その週の月曜(YYYY-MM-DD)で名乗る。"""
    d = datetime.fromtimestamp(ts)
    if granularity == "month":
        return d.strftime("%Y-%m")
    if granularity == "week":
        return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")
    return d.strftime("%Y-%m-%d")


def _period_bounds(key: str, granularity: str) -> tuple:
    """期間keyの [start, end) をPOSIX秒で返す。endは次の期間の開始そのもの。"""
    if granularity == "month":
        year, month = int(key[:4]), int(key[5:7])
        start = datetime(year, month, 1)
        end = datetime(year + month // 12, month % 12 + 1, 1)
    else:
        start = datetime.strptime(key, "%Y-%m-%d")
        end = start + timedelta(days=7 if granularity == "week" else 1)
    return start.timestamp(), end.timestamp()


def _period_dates(key: str, granularity: str) -> tuple:
    """期間keyの最初の日と最後の日を 'YYYY-MM-DD' で返す。カレンダーの端に使う。"""
    start, end = _period_bounds(key, granularity)
    return (datetime.fromtimestamp(start).strftime("%Y-%m-%d"),
            datetime.fromtimestamp(end - 1).strftime("%Y-%m-%d"))


def _date_to_period(text: str, granularity: str) -> str:
    """カレンダーで選んだ 'YYYY-MM-DD' を、その日の属する期間keyへ寄せる。

    月・週の粒度でも画面は日付で選ぶ。7/15を選んだら「7月」「その週」を指したことにする —
    月の1日・週の月曜だけを有効にすると、選べない日をcalendarが黙って弾くことになる。
    """
    try:
        d = datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"日付の形式が不正です: {text}") from exc
    return _period_key(d.timestamp(), granularity)


def _period_range(first: str, last: str, granularity: str) -> tuple:
    """firstからlastまでの期間keyを1つも飛ばさずに並べ、(一覧, 落とした件数)を返す。

    ギフトも配信も無かった期間を抜くと、「その週は誰も投げていない」が「その週は無かった」
    に化ける。上限に当たったときは新しい側を残す(古い側を見たい場合より頻度が高い)。
    """
    keys = []
    key = first
    while key <= last and len(keys) < _RANKING_PERIOD_SCAN_MAX:
        keys.append(key)
        key = _period_key(_period_bounds(key, granularity)[1], granularity)
    dropped = max(0, len(keys) - _RANKING_PERIOD_MAX)
    return keys[dropped:], dropped


def _unknown_identity(identity_key: str) -> dict:
    """users表に行の無いidentity_keyの受け皿。名前を作らず「取れていない」と名乗る。
    起きるのは、Gift eventだけが在ってuser行がまだ書かれていない収集中の一瞬である。"""
    return {
        "identity_key": identity_key, "user_id": "", "unique_id": "",
        "nickname": "(unknown)", "avatar": "", "fans_level": 0, "gifter_level": 0,
        "gifter_badge": "", "member_badge": "", "league": "",
    }


def _whale_tier_defs() -> list:
    defs = []
    for i, low in enumerate(_WHALE_TIERS):
        high = _WHALE_TIERS[i + 1] if i + 1 < len(_WHALE_TIERS) else None
        low_label = _coin_label(low)
        label = f"{low_label}〜{_coin_label(high)}" if high else f"{low_label}↑"
        # min_labelは帯の下限そのものの表記。積み上げ合計の呼び名(「1K↑ 合計」)に使う。
        # 画面側でlabelを切り出すと、帯の書式を変えたとき静かに壊れる。
        defs.append({"min": low, "max": high, "label": label, "min_label": low_label})
    return defs


def _whale_total_def() -> dict:
    """最上段(合計)の定義。下限額とその表記、どの帯から積むかを画面へ渡す。
    画面側で帯の並びから割り出させると、帯を足したときに合計の起点が黙ってずれる。"""
    return {
        "min": _WHALE_TOTAL_MIN,
        "min_label": _coin_label(_WHALE_TOTAL_MIN),
        "from_tier": _WHALE_TOTAL_INDEX,
    }


def _whale_tier_index(coins: int):
    """coinsが属する排他帯のindex。最小帯にも満たなければNone(どの帯にも入らない)。"""
    idx = None
    for i, low in enumerate(_WHALE_TIERS):
        if coins >= low:
            idx = i
    return idx


# 1日ぶんの帯に添える顔ぶれの上限。人数そのものはtiersが持つので、この一覧は表示用で
# あって数の根拠ではない(切っても人数は狂わない)。実測では下限100コインでも1日38人が最大
# だが、荒れた日にpayloadが際限なく伸びないよう天井を置く。
_WHALE_ROSTER_PER_DAY = 100


def _battle_no_contest(battle: dict) -> bool:
    """全ての陣営のscoreが下限以下だった(=勝負が成立していない)Battleか。

    opp_scoreは常に「最も強い敵陣営」のscore(合計ではない)なので、自陣とこの2値の最大が
    閾値以下なら、どの陣営も閾値を越えていない。チーム戦のown_scoreは陣営合計で、個々の
    memberはそれ以下だから同じ判定で足りる。

    判定はannotate_result後の値に対して行うこと。確定時点のscoreと保存値(PK後のroster
    解体を含む)は食い違い、後者では成立した勝負が0対0に潰れて見えることがある。
    """
    return max(battle.get("own_score") or 0, battle.get("opp_score") or 0) <= _BATTLE_NO_CONTEST_SCORE


def _liver_share(
    row=None,
    gift_diamonds=0,
    checked_diamonds=0,
    liver_diamonds=0,
    gifters=0,
    checked_gifters=0,
    liver_gifters=0,
) -> dict:
    """ギフトに占めるライバー(自分でも配信している人)の割合を、2つの物差しで返す。

    コイン基準と人数基準は別物で、片方だけでは読み違える。1人の大口ライバーが居れば
    コイン比率は跳ね上がるが人数比率は動かない。逆に少額のライバーが大勢居れば人数比率
    だけが上がる。どちらの分母かを名前に持たせて、独立した項目として返す。

    **分母はどちらも全体**(そのギフト全額 / gift実績のある全員)。「コイン全体に占める
    ライバーの割合」という問いにそのまま答える形にする。リーグの確認は待ち行列で順に
    進むため、未確認の人はライバーに数えられない — つまりこの比率は**下限**で、確認が
    進むほど実態へ上がっていく。どこまで確認できているかは coverage で別に返す。

    確認が1件も済んでいなければ比率は None。そこを0%にすると「ライバーが居ないと確認
    できた」と読めてしまうが、実際には何も判っていない。
    """
    if row is not None:
        gift_diamonds = row["gift_diamonds"] or 0
        checked_diamonds = row["checked_diamonds"] or 0
        liver_diamonds = row["liver_diamonds"] or 0
        gifters = row["gifters"] or 0
        checked_gifters = row["checked_gifters"] or 0
        liver_gifters = row["liver_gifters"] or 0
    return {
        # コイン基準
        "liver_diamonds": liver_diamonds,
        "liver_gift_diamonds": gift_diamonds,
        "liver_coin_share": (
            (liver_diamonds / gift_diamonds * 100) if gift_diamonds and checked_diamonds else None
        ),
        "liver_checked_diamonds": checked_diamonds,
        "liver_coin_coverage": (checked_diamonds / gift_diamonds * 100) if gift_diamonds else 0.0,
        # 人数基準
        "liver_gifters": liver_gifters,
        "liver_total_gifters": gifters,
        "liver_gifter_share": (
            (liver_gifters / gifters * 100) if gifters and checked_gifters else None
        ),
        "liver_checked_gifters": checked_gifters,
        "liver_gifter_coverage": (checked_gifters / gifters * 100) if gifters else 0.0,
    }


# 同接の階段保持積分でbucketの間を埋める上限。bucket行はeventの無い窓に存在しないので
# 隣り合うbucketの間は空く。短い空白は「静かだっただけ」で直前の同接が続いているが、
# これを超える空白は収集そのものが落ちていた区間で、直前の値を持ち越すと居なかった人を
# 数えることになる(実測: あるsessionで名目4.74時間に対し観測は2.37時間しかない)。
# 上限を超えた空白は平均の分母(観測秒)からも外す。
_VIEWER_GAP_CAP_SECONDS = 60
# 宝箱(红包)の入室誘引窓の尾。告知(envelopes.time)から開封(unpack_at)までの待ちで人が
# 流れ込み、開封後に引く。尾の長さは孤立宝箱(前後20分に他の宝箱が無い)22件の実測で決めた。
# 直前の素の水準に対し開封時点2.77倍・+60秒2.21倍・+120秒1.81倍・+180秒1.51倍で、
# 以降は+900秒まで1.3〜1.5倍の緩い高止まりになる。切りたいのは急増ぶんなので、減衰が
# 平らになる+180秒で窓を閉じる。残る高止まりぶんは窓外へ残るため、この線は
# 「宝箱の影響を消した同接」ではなく「宝箱窓を除いた同接」である。
_ENVELOPE_TAIL_SECONDS = 180


def _envelope_windows(conn, session_ids: list) -> dict:
    """session別の宝箱窓(重なりを畳んだ [開始, 終了] の時刻昇順list)。"""
    if not session_ids:
        return {}
    ph = ",".join("?" * len(session_ids))
    windows: dict = {}
    for row in conn.execute(
        "SELECT session_id, time, COALESCE(unpack_at, time) + ? AS until FROM envelopes"
        f" WHERE session_id IN ({ph}) AND kind = 'envelope' ORDER BY session_id, time",
        (_ENVELOPE_TAIL_SECONDS, *session_ids),
    ):
        merged = windows.setdefault(row["session_id"], [])
        if merged and row["time"] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], row["until"])
        else:
            merged.append([row["time"], row["until"]])
    return windows


def _viewer_levels(conn, session_ids: list) -> dict:
    """session別の同接水準。bucketのviewersを階段保持で時間積分し、時間加重平均と、
    宝箱窓を除いた時間加重平均を返す。

    単純な AVG(viewers) は使えない。bucket行はeventの無い窓に存在しないため、賑わった
    区間だけが濃く効く(実測で最大+33%: 27.9対21.0)。滞在時間推定(analytics)が同じ理由で
    階段保持の時間積分を採っているのと同じ作法である。

    宝箱窓を除いた平均は「素の視聴」の水準。実測では窓内の同接が窓外の2〜5.6倍あり、
    宝箱を何回落としたかで全体平均がいくらでも動く(あるsessionで全体35.0に対し窓外9.8)。

    返す観測秒(observed)は、上限を超える空白を除いた実際に観測できていた時間。
    コメント率の分母もこれを使う ―― 名目の配信時間で割ると、収集が落ちた配信だけ
    率が半分に見える。
    """
    if not session_ids:
        return {}
    ph = ",".join("?" * len(session_ids))
    rows = conn.execute(
        "SELECT b.session_id AS sid, b.start AS start, b.viewers AS viewers,"
        " s.bucket_seconds AS bucket_seconds"
        " FROM buckets b JOIN sessions s ON s.id = b.session_id"
        f" WHERE b.session_id IN ({ph}) ORDER BY b.session_id, b.start",
        tuple(session_ids),
    ).fetchall()
    windows = _envelope_windows(conn, session_ids)
    levels: dict = {}
    total = len(rows)
    for i, row in enumerate(rows):
        sid = row["sid"]
        nxt = rows[i + 1] if i + 1 < total else None
        # 最後のbucketは次が無いのでbucket幅ぶんだけ続いたものとして数える。
        span = (
            min(nxt["start"] - row["start"], _VIEWER_GAP_CAP_SECONDS)
            if nxt is not None and nxt["sid"] == sid
            else (row["bucket_seconds"] or 0)
        )
        level = levels.get(sid)
        if level is None:
            merged = windows.get(sid) or []
            level = levels[sid] = {
                "sum": 0.0, "observed": 0.0, "sum_nobox": 0.0, "nobox": 0.0,
                "windows": merged, "cursor": 0,
            }
        level["sum"] += row["viewers"] * span
        level["observed"] += span
        # 窓は時刻昇順で、bucketも時刻昇順。今どの窓まで来たかを持って前へだけ進める。
        merged = level["windows"]
        cursor = level["cursor"]
        while cursor < len(merged) and merged[cursor][1] < row["start"]:
            cursor += 1
        level["cursor"] = cursor
        if cursor < len(merged) and merged[cursor][0] <= row["start"]:
            continue
        level["sum_nobox"] += row["viewers"] * span
        level["nobox"] += span
    return {
        sid: {
            "viewers_avg": (lv["sum"] / lv["observed"]) if lv["observed"] else None,
            "observed_seconds": lv["observed"],
            "viewers_avg_nobox": (lv["sum_nobox"] / lv["nobox"]) if lv["nobox"] else None,
            "nobox_seconds": lv["nobox"],
        }
        for sid, lv in levels.items()
    }


class StreamersMixin:
    """配信者別の集計画面(履歴・profile・cohort・見どころ)と全体dashboard。

    lockもDB接続も持たない。すべて Storage が所有する self._conn /
    self._lock / _read_connection() を借りる(mixinとして Storage に混ぜられる前提)。
    契約の詳細はmodule docstringを参照。
    """

    def streamer_history_stats(self, unique_id: str, limit: int) -> dict:
        """Per-streamer comparison of recent finished sessions: today's run is the
        live snapshot (supplied by the caller); this returns the previous session,
        the recent average, and the personal best for each metric. Peak viewers is
        read from the buckets table (the finalized stats keep only the last value)."""
        with self._lock:
            handles = self._owner_handles_locked(unique_id)
            ph = ",".join("?" * len(handles))
            rows = self._conn.execute(
                "SELECT s.id, s.started_at, s.ended_at, s.stats_json,"
                " (SELECT MAX(viewers) FROM buckets b WHERE b.session_id = s.id) AS peak_viewers"
                f" FROM sessions s WHERE s.unique_id IN ({ph}) AND s.ended_at IS NOT NULL"
                + _EXCLUDE_RESTRICTED
                + " ORDER BY s.started_at DESC LIMIT ?",
                (*handles, limit),
            ).fetchall()
        sessions = []
        for row in rows:
            stats = json.loads(row["stats_json"])
            sessions.append(
                {
                    "session_id": row["id"],
                    "started_at": row["started_at"],
                    "gifts": stats.get("gifts", 0) or 0,
                    "diamonds": stats.get("diamonds", 0) or 0,
                    "comments": stats.get("comments", 0) or 0,
                    "viewers": stats.get("viewers_peak")
                    or row["peak_viewers"]
                    or stats.get("viewers", 0)
                    or 0,
                    "duration": (row["ended_at"] - row["started_at"]) if row["ended_at"] else 0,
                }
            )
        metrics = ["gifts", "diamonds", "comments", "viewers", "duration"]
        count = len(sessions)
        average = {
            m: (sum(s[m] for s in sessions) / count) if count else 0 for m in metrics
        }
        best = {m: max((s[m] for s in sessions), default=0) for m in metrics}
        return {
            "unique_id": unique_id,
            "count": count,
            "sessions": sessions,
            "last": sessions[0] if sessions else None,
            "average": average,
            "best": best,
        }

    def streamer_index(self) -> list:
        """List every monitored streamer with lifetime totals, for the streamer
        analytics page's left-hand selector. Identity (nickname/avatar) is the most
        recent non-empty owner record."""
        # GROUP BYは配信者identity(owner_user_id優先)。bare columnのs.unique_idは
        # SQLiteでは任意の行から取られ@handle改名者でラベルが不定になるため、表示用
        # handleは最新sessionのものを相関subqueryで決定的に選ぶ。
        conn = self._read_connection()
        rows = conn.execute(
            _SESSION_TOTALS_CTE + _STREAMER_TOTALS_SELECT +
            f" WHERE 1=1{_EXCLUDE_RESTRICTED}"
            " GROUP BY okey ORDER BY diamonds DESC, sessions DESC",
        ).fetchall()
        # 配信者ごとの「ギフトに占めるライバー(自分でも配信している人)の割合」。
        # 分子・分母をどちらもgift eventから採るのは、比率の両側を同じ物差しで測るため
        # (sessionのstats_jsonとgift eventは確定タイミングが違い、混ぜると比率が歪む)。
        # 未確認の人を「ライバーではない」に丸めると過小評価になるので、判定済みぶんを
        # 分母にした比率と、その判定済みが全体のどれだけかを別々に返す(実測65ms)。
        liver_rows = conn.execute(
            "SELECT COALESCE(NULLIF(s.owner_user_id, ''), s.unique_id) AS okey,"
            " COALESCE(SUM(e.diamonds), 0) AS gift_diamonds,"
            " COALESCE(SUM(CASE WHEN u.league_checked_at IS NOT NULL THEN e.diamonds"
            "  ELSE 0 END), 0) AS checked_diamonds,"
            f" COALESCE(SUM(CASE WHEN {display_league_sql('u')} <> '' THEN e.diamonds"
            "  ELSE 0 END), 0) AS liver_diamonds,"
            " COUNT(DISTINCT e.identity_key) AS gifters,"
            " COUNT(DISTINCT CASE WHEN u.league_checked_at IS NOT NULL"
            "  THEN e.identity_key END) AS checked_gifters,"
            f" COUNT(DISTINCT CASE WHEN {display_league_sql('u')} <> ''"
            "  THEN e.identity_key END) AS liver_gifters"
            " FROM events e JOIN sessions s ON s.id = e.session_id"
            " LEFT JOIN users u ON u.identity_key = e.identity_key"
            f" WHERE e.kind = 'gift'{_EXCLUDE_RESTRICTED}"
            " GROUP BY okey",
        ).fetchall()
        livers = {r["okey"]: r for r in liver_rows}
        with self._lock:
            handles = self._latest_owner_handles_locked()
            owners = self._latest_owners()
        result = []
        for row in rows:
            handle = handles.get(row["okey"], row["okey"])
            owner = owners.get(handle)
            result.append(
                {
                    "unique_id": handle,
                    "nickname": (owner["nickname"] if owner else "") or handle,
                    "avatar": (owner["avatar"] if owner else "") or "",
                    "sessions": row["sessions"],
                    "diamonds": row["diamonds"] or 0,
                    "gifts": row["gifts"] or 0,
                    "comments": row["comments"] or 0,
                    "last_started_at": row["last_started_at"],
                    **_liver_share(livers.get(row["okey"])),
                }
            )
        return result

    def streamer_profile(self, unique_id: str, limit: int = 200) -> dict:
        """Cross-session profile for one streamer: lifetime/average/best metrics,
        per-session series, the streamer's own gifter base (with loyalty + revenue
        concentration), and battle record (win rate, scores, opponents, the share of
        revenue earned during battle windows). Peak viewers comes from buckets; the
        finalized stats keep only the last viewer count."""
        # 配信者1人ぶんのsession/gifter/heatmap/battleをまとめて引く。どれもこの配信者の
        # 全期間が対象で、書き込み接続で流すとその間collectorのevent書き出しが待たされる。
        # 身元解決(handle集合・最新owner)だけはwriter接続のhelperなのでlockの内側に残す。
        #
        # Battle貢献(_cached_battle_gift_contributions)はread専用接続で流すので、収集中
        # sessionの未commit分をここで1回だけ確定させる。以前はBattle 1件ごとにflushして
        # いたため、1 requestでwrite lockを214回(=2×111戦)取り直していた。
        self.flush()
        with self._lock:
            handles = self._owner_handles_locked(unique_id)
            owners = self._latest_owners()
        owner = owners.get(unique_id)
        conn = self._read_connection()
        ph = ",".join("?" * len(handles))
        session_rows = conn.execute(
            "SELECT s.id, s.started_at, s.ended_at, s.stats_json,"
            " (SELECT MAX(viewers) FROM buckets b WHERE b.session_id = s.id) AS peak_viewers"
            f" FROM sessions s WHERE s.unique_id IN ({ph})"
            + _EXCLUDE_RESTRICTED
            + " ORDER BY s.started_at DESC LIMIT ?",
            (*handles, limit),
        ).fetchall()
        # 表示属性はusers表(最新)を優先する。ここはsessionを跨いだ通算集計で、
        # 「そのSessionでの見え方」という基準が存在しないため、最新の身元で1人を1行に
        # 示すのが正しい。session単位のsession_summary/battle_gift_contributionsは逆に
        # point-in-timeを優先する(そちらは過去の見え方を保つのが目的)。
        #
        # event側をMAX()で優先してはいけない: MAX()は辞書順の最大を返すだけで「最新の
        # handle」ではない。実測では改名前の自動生成handle user5037930325926 が現handle
        # harehare12345 を、user9487377432719 が chikudenchi0807 を押しのけていた。
        gifter_rows = conn.execute(
            "SELECT e.identity_key AS key,"
            " COALESCE(NULLIF(u.user_id, ''), MAX(e.user_id)) AS user_id,"
            " COALESCE(NULLIF(u.unique_id, ''), MAX(e.user_unique_id)) AS unique_id,"
            " COALESCE(NULLIF(u.nickname, ''), MAX(e.user_nickname)) AS nickname,"
            # avatarは event_strings へinternしてある(doc/DB_INTERN.md)。値へJOINしてから
            # MAXを採ること ―― idの最大は辞書順最大と一致しない。
            " COALESCE(NULLIF(u.avatar, ''), MAX(av.value)) AS avatar, SUM(e.gift_count) AS gifts,"
            # Lv/badgeとリーグはusers表(最新)を使う。ここはsessionを跨いだ通算集計で、
            # 「そのSessionでの見え方」という基準が存在しないため、identity列と同じく最新の
            # 値で1人を1行に示すのが正しい(point-in-time厳守はsession単位の
            # battle_gift_contributions側の話である)。
            f" u.fans_level AS fans_level, u.gifter_level AS gifter_level,"
            " u.gifter_badge AS gifter_badge, u.member_badge AS member_badge,"
            f" {display_league_sql('u')} AS league, u.league_checked_at AS league_checked_at,"
            " SUM(e.diamonds) AS diamonds, COUNT(DISTINCT e.session_id) AS sessions"
            " FROM events e JOIN sessions s ON s.id = e.session_id"
            " LEFT JOIN users u ON u.identity_key = e.identity_key"
            " LEFT JOIN event_strings av ON av.id = e.user_avatar_id"
            f" WHERE s.unique_id IN ({ph}) AND e.kind = 'gift'"
            " GROUP BY e.identity_key ORDER BY diamonds DESC, gifts DESC",
            tuple(handles),
        ).fetchall()
        # Time-of-day distribution from the bucket time-series, so a session's
        # coins/comments land in the hours they actually happened (not all on the
        # start hour). 'localtime' matches the browser on this localhost app, so
        # the day/hour grid lines up with the rest of the (browser-local) UI.
        # 数え直しはsession単位cache越し(_heatmap_cells)。
        heatmap = self._heatmap_cells(conn, handles, ph)
        # Oldest session first so that, when the same battle_id is saved under
        # more than one session (e.g. two server instances collected the same
        # room concurrently), the copy kept by the dedup below is the one whose
        # session saw the battle from its start — the most complete record.
        battle_session_ids = [
            row["session_id"]
            for row in conn.execute(
                "SELECT DISTINCT b.session_id AS session_id, s.started_at AS started_at"
                " FROM battles b JOIN sessions s ON s.id = b.session_id"
                f" WHERE s.unique_id IN ({ph})"
                " ORDER BY s.started_at ASC, b.session_id ASC",
                tuple(handles),
            ).fetchall()
        ]
        # Battle履歴から「その対戦の動画」へ辿るための、時刻の当たり先。中断録画も
        # 素材は揃っていることがあり、statusで捨てるとその録画へ辿る道が無くなる。
        recording_rows = [
            dict(r)
            for r in conn.execute(
                f"SELECT id, session_id, started_at, ended_at FROM recordings"
                f" WHERE unique_id IN ({ph}) AND status IN ('completed', 'interrupted')",
                tuple(handles),
            ).fetchall()
        ]
        # コラボ(非BattleのLinkMic)の窓。Battle窓と同じwall-clock軸で「配信時間の
        # どれだけを共演に使ったか」を出すために引く。集計対象はsession_rowsと同じ
        # session集合(制限中を除く直近limit件)へ後で絞る — 分母(配信時間)と分子が
        # 別のsession集合になると比率が意味を失う。
        # **現行版の窓だけ**を読む。旧rule(v1)の窓はfinishでしか閉じておらず、間のソロ
        # 時間を丸ごとコラボに数えている(録画照合で窓の中の大半がソロだった)。補正材料が
        # DBに残っていないので、混ぜずに捨てる。
        collab_rows = [
            (r["session_id"], r["start"], r["end"])
            for r in conn.execute(
                "SELECT cw.session_id AS session_id, cw.start AS start, cw.end AS end"
                " FROM collab_windows cw JOIN sessions s ON s.id = cw.session_id"
                f" WHERE s.unique_id IN ({ph}) AND cw.version = ?",
                (*handles, COLLAB_WINDOW_VERSION),
            ).fetchall()
        ]
        # コラボ窓の収集が始まる前の配信は「コラボが無かった」のか「記録が無い」のかを
        # 区別できない。0%として混ぜるとその配信時間が丸ごとソロへ化ける(実測: ある
        # 配信者でソロ32.1%→4.9%、コラボ49.8%→75.0%)ので、共演構成の集計対象から外す。
        # 境目は「現行ruleで最初にコラボ窓を記録したsessionの開始時刻」。そのsessionより
        # 前は現行ruleでの観測が存在しない。窓の時刻(MIN(cw.start))ではなくsessionの開始で
        # 切るのは、窓は必ずsession開始より後に立つため、窓時刻で切るとその最初のsession
        # 自身が対象から落ちるためである。
        collab_since = conn.execute(
            "SELECT MIN(s.started_at) AS since FROM collab_windows cw"
            " JOIN sessions s ON s.id = cw.session_id WHERE cw.version = ?",
            (COLLAB_WINDOW_VERSION,),
        ).fetchone()["since"]
        # 同接の水準(時間加重平均・宝箱窓を除いた平均・観測秒)。集計対象はsession_rowsと
        # 同じsession集合に限る ―― 制限中や窓の外のsessionまで走らせると、画面に出ない
        # 行のためにbucketを走査することになる。
        # bucketを1本も持たないsessionはcacheへ載せない。起動時の backfill_missing_buckets
        # が後から作り直す対象がまさにそれで、空のまま覚えると作り直した後も空のままになる
        # (heatmapと同じ理由・同じ判定)。
        level_ids = [row["id"] for row in session_rows]
        # コインの日次。推移のコイン段はこの日別合計を描く ―― sessionを1本=1点で並べると、
        # 同じ配信がreconnectで最大7本のsessionに割れ(実測: 配信者×日の71.7%が2本以上)、
        # さらにsessionの35.6%が日を跨ぐため、session合計を開始日へ寄せた「日次」は実際の
        # その日のコインと一致しない。event時刻でその場で数え直す。
        # 対象はsession_rowsと同じsession集合。画面の他の数字(通算KPI・大口の日次人数)と
        # 突き合わせられるよう、母集合を揃える。
        # コインを持つeventはgiftだけ(実測: 全1,415,612件中diamonds>0はgift 34,657件のみ)
        # なのでkindで絞る。日付はlocaltime ―― 画面の他の日付と同じ物差しに揃える。
        daily_coins = [
            {"date": row["ymd"], "diamonds": row["diamonds"] or 0}
            for row in conn.execute(
                "SELECT strftime('%Y-%m-%d', e.time, 'unixepoch', 'localtime') AS ymd,"
                " SUM(e.diamonds) AS diamonds FROM events e"
                " WHERE e.session_id IN (SELECT je.value FROM json_each(?) je)"
                "   AND e.kind = 'gift'"
                " GROUP BY ymd ORDER BY ymd",
                (json.dumps(level_ids),),
            ).fetchall()
            if row["ymd"]
        ]
        cacheable = [
            row["id"] for row in conn.execute(
                "SELECT s.id AS id FROM sessions s"
                f" WHERE s.id IN ({','.join('?' * len(level_ids))})"
                "   AND s.ended_at IS NOT NULL"
                "   AND EXISTS (SELECT 1 FROM buckets b WHERE b.session_id = s.id)",
                tuple(level_ids),
            ).fetchall()
        ] if level_ids else []
        viewer_levels = self._cached_session_payloads(
            conn, cacheable, _VIEWER_LEVEL_CACHE_KIND, _VIEWER_LEVEL_CACHE_VERSION,
            _viewer_levels)
        viewer_levels.update(
            _viewer_levels(conn, [i for i in level_ids if i not in viewer_levels]))
        # 宝箱の収集開始。これより前の配信は「宝箱を落とさなかった」のか「記録していない」
        # のかを区別できないので、宝箱を除いた同接は出さない(出すと、記録の無い期間だけ
        # 素の同接が高かったように読める)。collab_sinceと同じ理由・同じ形の境目である。
        envelope_since = conn.execute(
            "SELECT MIN(s.started_at) AS since FROM envelopes e"
            " JOIN sessions s ON s.id = e.session_id WHERE e.kind = 'envelope'"
        ).fetchone()["since"]
        # 収集中(ended_atなし)のsessionには終端が無い。最後に何かが届いた時刻を終端に
        # 使う(analytics._observed_spanと同じ根拠)。started_atで潰すと、その配信の窓が
        # まるごと落ちる。
        open_ids = [r["id"] for r in session_rows if r["ended_at"] is None]
        observed_end: dict = {}
        if open_ids:
            oph = ",".join("?" * len(open_ids))
            observed_end = {
                r["session_id"]: r["last"]
                for r in conn.execute(
                    "SELECT session_id, MAX(t) AS last FROM ("
                    f"  SELECT session_id, MAX(time) AS t FROM events"
                    f"   WHERE session_id IN ({oph}) GROUP BY session_id"
                    f"  UNION ALL SELECT session_id, MAX(time) FROM viewer_samples"
                    f"   WHERE session_id IN ({oph}) GROUP BY session_id"
                    ") GROUP BY session_id",
                    (*open_ids, *open_ids),
                ).fetchall()
                if r["last"] is not None
            }

        # 各Battleの自陣貢献を、Battle cardと同じ窓・同じ入口(battle_gift_contributions)で
        # 復元する。窓解決は同一sessionの他Battle(次Battle開始・duration中央値)に依存する
        # ためsession単位でまとめて解く。窓を自前で持つと、end_timeを欠くBattleが無制限窓に
        # なりBattle後の通常Giftまで貢献へ混入する(実測: 貢献者0人→12人, coin 26→19397)。
        # _cached_battle_gift_contributionsはlockを取らないのでlockの外で回す。
        # data_jsonのparseはprofile_battlesが畳んで覚える(実測: 945戦35.0MBのparseに
        # 約400ms掛かっていた)。sessionの並びは上のqueryのまま古い順で渡す。
        battles_by_session = self.profile_battles(conn, battle_session_ids)

        battle_diamonds = 0
        battle_team_diamonds = 0
        # 相手陣のgifterは別Roomのためこのsessionのeventには無い。ここに集まるのは監視配信者
        # 自身のBattle gifterだけで、全Battleを通して「Battleに必ず現れるgifter」を表す。
        battle_gifters: dict = {}
        parsed_battles = []
        # 共演構成(配信時間の内訳)が使う窓は、成立しなかったBattleも含む全戦ぶん。枠として
        # 時間は使われているため、Battle分析から外す戦をここから落とすとソロ時間へ化ける。
        battle_windows = []
        # battle_id is TikTok's globally-unique PK id, so the same physical battle
        # carries the same id across sessions. Dedup on it to keep concurrent-
        # collection duplicates from inflating every battle metric. id 0/missing is
        # treated as un-dedupable (old/synthetic records) and kept as-is.
        seen_battle_ids = set()
        dropped_duplicates = 0
        dropped_no_contest = 0
        for session_id, session_battles in battles_by_session.items():
            # 窓解決には(重複除外前の)そのsessionの全Battleを使う。除外されるのは別session
            # が同じBattleを重複収集した分で、このsessionの「次Battle開始」は変わらないため。
            starts = sorted(
                b["start_time"] for b in session_battles if b.get("start_time") is not None
            )
            fallback_duration = gift_window_fallback_duration(session_battles)
            for battle in session_battles:
                start_time = battle.get("start_time")
                if start_time is None:
                    continue
                battle_id = battle.get("battle_id")
                if battle_id:
                    if battle_id in seen_battle_ids:
                        dropped_duplicates += 1
                        continue
                    seen_battle_ids.add(battle_id)
                battle_windows.append((session_id, start_time, battle.get("end_time")))
                if _battle_no_contest(battle):
                    dropped_no_contest += 1
                    continue
                end_time = gift_window_end(battle, starts, fallback_duration)
                gift = self._cached_battle_gift_contributions(
                    session_id, battle, start_time, end_time)

                # 自室のGift eventで実測できる分。これが監視配信者自身の貢献者である。
                window_diamonds = 0
                key_contributors = 0
                for g in gift:
                    diamonds = g["diamonds"]
                    window_diamonds += diamonds
                    if diamonds >= _BATTLE_KEY_CONTRIB_DIAMONDS:
                        key_contributors += 1
                    key = g["key"]
                    if not key:
                        continue
                    agg = battle_gifters.setdefault(
                        key,
                        {
                            # 表示属性をここで確定させてはいけない。gの身元はそのsession
                            # での見え方(point-in-time)で、setdefaultだと最初に当たった
                            # Battle=最古のsessionの名前が最後まで残る。通算表としての
                            # 身元は集計後にusers表(最新)へ解決し直す(下の身元解決)。
                            # ここに置く値は、その解決に載らなかった場合の観測値である。
                            "identity_key": key,
                            "user_id": g["user_id"],
                            "unique_id": g["unique_id"],
                            "nickname": g["nickname"],
                            "avatar": g["avatar"],
                            "league": "",
                            "fans_level": g["fans_level"],
                            "gifter_level": g["gifter_level"],
                            "gifter_badge": g["gifter_badge"],
                            "member_badge": g["member_badge"],
                            "diamonds": 0,
                            "gifts": 0,
                            "battles": 0,
                        },
                    )
                    agg["diamonds"] += diamonds
                    agg["gifts"] += g["gifts"]
                    agg["battles"] += 1
                    if g["avatar"] and not agg["avatar"]:
                        agg["avatar"] = g["avatar"]

                # チーム戦のteam集約armiesは味方hostの貢献者も自陣hostへ寄って届く
                # (team集約のanchorが実hostに解決できないため、host別に分けられない)。
                # 実測できる自室分とは別に、armies由来のチーム全体分も併記する。集計方法は
                # Battle card(apply_battle_gift_contributions)と揃える。
                gift_by_id = {g["user_id"]: g for g in gift if g["user_id"]}
                team_diamonds = 0
                team_key_contributors = 0
                matched = set()
                for c in battle.get("contributions", []) or []:
                    if c.get("side") != "own":
                        continue
                    cid = c.get("user_id")
                    if cid and cid in gift_by_id:
                        matched.add(cid)
                        coins = gift_by_id[cid]["diamonds"]
                    else:
                        coins = c.get("diamonds") or 0
                    team_diamonds += coins
                    if coins >= _BATTLE_KEY_CONTRIB_DIAMONDS:
                        team_key_contributors += 1
                for g in gift:
                    if g["user_id"] and g["user_id"] in matched:
                        continue
                    team_diamonds += g["diamonds"]
                    if g["diamonds"] >= _BATTLE_KEY_CONTRIB_DIAMONDS:
                        team_key_contributors += 1

                battle_diamonds += window_diamonds
                battle_team_diamonds += team_diamonds
                parsed_battles.append(
                    {
                        "battle": battle,
                        "session_id": session_id,
                        "window_diamonds": window_diamonds,
                        "key_contributors": key_contributors,
                        "team_diamonds": team_diamonds,
                        "team_key_contributors": team_key_contributors,
                    }
                )

        if dropped_duplicates:
            logger.info(
                "streamer_profile: battle %d 件をbattle_id重複として除外しました"
                "（%s の同時収集による重複）",
                dropped_duplicates,
                unique_id,
            )
        if dropped_no_contest:
            logger.info(
                "streamer_profile: battle %d 件を不成立（全陣営のscoreが%d以下）として"
                "Battle分析から除外しました（%s）",
                dropped_no_contest,
                _BATTLE_NO_CONTEST_SCORE,
                unique_id,
            )

        # 共演構成(コラボ / Battle / ソロ)。Battle窓は重複除外後のbattle_windowsを使う
        # (同じBattleを2 instanceが収集した分を足すと、その時間だけ二重に計上される)。
        session_spans = [
            (
                row["id"],
                row["started_at"],
                row["ended_at"]
                if row["ended_at"] is not None
                else observed_end.get(row["id"], row["started_at"]),
            )
            for row in session_rows
        ]
        # 現行ruleの窓が1件も無い間は、コラボは「0%」ではなく**未計測**である。0%として
        # 出すとその時間が全部ソロに見え、旧ruleと逆向きの嘘になる。この場合はsessionを
        # 絞らずに集計し(Battle側の値は窓に依存せず正しい)、collab_available=Falseで
        # コラボ・ソロ・共演計を名乗らないことを画面へ伝える。
        collab_available = collab_since is not None
        observed_spans = [
            span for span in session_spans if not collab_available or span[1] >= collab_since
        ]
        coop = _coop_summary(observed_spans, collab_rows, battle_windows)
        # 何をもって集計対象としたかを画面へ渡す。除外を黙って行うと、Battle回数が
        # Battle分析の対戦数と食い違う理由が読めなくなる。
        coop["collab_available"] = collab_available
        coop["collab_window_version"] = COLLAB_WINDOW_VERSION
        coop["collab_since"] = collab_since
        coop["unobserved_sessions"] = len(session_spans) - len(observed_spans)

        identity = {
            "unique_id": unique_id,
            "nickname": (owner["nickname"] if owner else "") or unique_id,
            "avatar": (owner["avatar"] if owner else "") or "",
        }

        sessions = []
        for row in session_rows:
            stats = json.loads(row["stats_json"])
            level = viewer_levels.get(row["id"]) or {}
            covered = envelope_since is not None and row["started_at"] >= envelope_since
            sessions.append(
                {
                    "session_id": row["id"],
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "duration": (row["ended_at"] - row["started_at"]) if row["ended_at"] else 0,
                    "gifts": stats.get("gifts", 0) or 0,
                    "diamonds": stats.get("diamonds", 0) or 0,
                    "comments": stats.get("comments", 0) or 0,
                    "likes": stats.get("likes_total", 0) or 0,
                    "viewers": stats.get("viewers_peak")
                    or row["peak_viewers"]
                    or stats.get("viewers", 0)
                    or 0,
                    # 同接の水準。viewersはPeak(瞬間値)、viewers_avgは観測時間で加重した
                    # 平均、viewers_avg_noboxは宝箱窓を除いた平均。bucketの無いsessionは
                    # 平均を持たないのでNone(0にすると「誰も居なかった」と読める)。
                    "viewers_avg": level.get("viewers_avg"),
                    "viewers_avg_nobox": level.get("viewers_avg_nobox") if covered else None,
                    "nobox_seconds": level.get("nobox_seconds", 0.0) if covered else 0.0,
                    "observed_seconds": level.get("observed_seconds", 0.0),
                    "battles": stats.get("battles", 0) or 0,
                    "battle_points": stats.get("battle_points", 0) or 0,
                }
            )
        metrics = ["gifts", "diamonds", "comments", "likes", "viewers", "duration", "battle_points"]
        count = len(sessions)
        totals = {m: sum(s[m] for s in sessions) for m in metrics}
        average = {m: (totals[m] / count if count else 0) for m in metrics}
        best = {m: max((s[m] for s in sessions), default=0) for m in metrics}
        # 通算の同接水準。average["viewers"]は各配信のPeakを配信数で割った物なので、
        # 「1配信あたりのPeak」であって同接の平均ではない。こちらは観測時間で加重する
        # (10分の配信と6時間の配信を同じ重みで平均しない)。averageへ混ぜないのは、
        # あちらがmetricsから機械的に作られる形で、API側でも同じ式で作り直されるため。
        observed_total = sum(s["observed_seconds"] for s in sessions)
        nobox_total = sum(s["nobox_seconds"] for s in sessions)
        viewer_level = {
            "avg": (
                sum((s["viewers_avg"] or 0) * s["observed_seconds"] for s in sessions) / observed_total
                if observed_total else None
            ),
            "avg_nobox": (
                sum((s["viewers_avg_nobox"] or 0) * s["nobox_seconds"] for s in sessions) / nobox_total
                if nobox_total else None
            ),
            "observed_seconds": observed_total,
            "nobox_seconds": nobox_total,
            "envelope_since": envelope_since,
        }

        gifters = [
            {
                # identity_keyはFan台帳の主キー。名前からその人の横断実績へ飛ぶ導線に使う。
                "identity_key": row["key"] or "",
                "user_id": row["user_id"] or "",
                "unique_id": row["unique_id"] or "",
                "nickname": row["nickname"] or "(unknown)",
                "avatar": row["avatar"] or "",
                "fans_level": row["fans_level"] or 0,
                "gifter_level": row["gifter_level"] or 0,
                "gifter_badge": row["gifter_badge"] or "",
                "member_badge": row["member_badge"] or "",
                # この視聴者自身が配信者である場合のリーグ帯。取れていなければ空=非表示。
                "league": row["league"] or "",
                "gifts": row["gifts"] or 0,
                "diamonds": row["diamonds"] or 0,
                "sessions": row["sessions"] or 0,
            }
            for row in gifter_rows
        ]
        gifter_total_diamonds = sum(g["diamonds"] for g in gifters)

        def _share(top_n: int) -> float:
            if not gifter_total_diamonds:
                return 0.0
            return sum(g["diamonds"] for g in gifters[:top_n]) / gifter_total_diamonds * 100

        # ギフトに占めるライバーの割合。gifters は全件で、表示用に切り詰めるのは後段の
        # gifters[:100] だけなので、ここは母集合の全員から数える。
        concentration = {
            "total_gifters": len(gifters),
            "total_diamonds": gifter_total_diamonds,
            "top1": _share(1),
            "top5": _share(5),
            "top10": _share(10),
            "repeat_gifters": sum(1 for g in gifters if g["sessions"] >= 2),
            "once_gifters": sum(1 for g in gifters if g["sessions"] == 1),
            **_liver_share(
                gift_diamonds=gifter_total_diamonds,
                checked_diamonds=sum(
                    row["diamonds"] or 0
                    for row in gifter_rows
                    if row["league_checked_at"] is not None
                ),
                liver_diamonds=sum(
                    row["diamonds"] or 0 for row in gifter_rows if row["league"]
                ),
                gifters=len(gifters),
                checked_gifters=sum(
                    1 for row in gifter_rows if row["league_checked_at"] is not None
                ),
                liver_gifters=sum(1 for row in gifter_rows if row["league"]),
            ),
        }

        battles = [pb["battle"] for pb in parsed_battles]
        wins = sum(1 for b in battles if b.get("result") == "win")
        losses = sum(1 for b in battles if b.get("result") == "lose")
        draws = sum(1 for b in battles if b.get("result") == "draw")
        decided = wins + losses
        own_score_sum = sum(b.get("own_score", 0) or 0 for b in battles)
        opp_score_sum = sum(b.get("opp_score", 0) or 0 for b in battles)
        battle_count = len(battles)
        opponents: dict = {}
        for b in battles:
            for opp in b.get("opponents", []) or []:
                key = _opponent_key(opp)
                if not key:
                    continue
                stat = opponents.setdefault(
                    key,
                    {
                        # 履歴側(opponent_keys)と突き合わせるためのkey。表示名やhandleから
                        # 画面が組み直すと、handleを持たない相手で別人と混ざる。
                        "key": key,
                        # 監視画面のコラボ相手はLinkLayer由来の数値user_idしか名乗らない
                        # (Playerはroom_idとuidの2 fieldのみ)。keyの中身に頼らず、この
                        # fieldで突合できるようにする。
                        "user_id": opp.get("user_id", ""),
                        "unique_id": opp.get("unique_id", ""),
                        "nickname": opp.get("nickname", "(unknown)"),
                        "avatar": opp.get("avatar", ""),
                        "battles": 0,
                        "wins": 0,
                        "losses": 0,
                    },
                )
                # 同じ相手でも表示情報の載らない戦がある(実data 1921件中24件)。1戦目が
                # それだと相手が名前なしのまま固定されるので、後の戦で判った分を埋める。
                for field in ("user_id", "unique_id", "avatar"):
                    if not stat[field] and opp.get(field):
                        stat[field] = opp[field]
                if stat["nickname"] == "(unknown)" and opp.get("nickname"):
                    stat["nickname"] = opp["nickname"]
                stat["battles"] += 1
                if b.get("result") == "win":
                    stat["wins"] += 1
                elif b.get("result") == "lose":
                    stat["losses"] += 1
        opponent_list = sorted(opponents.values(), key=lambda o: o["battles"], reverse=True)
        # Battle Gifterの身元をGifter一覧と同じ基準(users表=最新)へ揃える。集計はどちらも
        # identity_key単位で一致しているのに、表示だけがBattle側はevent由来だった。しかも
        # 源のMAX()は辞書順の最大であって最新のhandleではなく、その上でsetdefaultが最古の
        # Battleの値を固定するため、改名した人が2つの表で別名に見えていた。どちらも全期間の
        # 通算表で「そのSessionでの見え方」という基準を持たないので、最新の身元で揃える
        # (point-in-time厳守はsession単位のbattle_gift_contributions側=Battle cardの話)。
        # gifter_rowsはこの配信者の全gift eventが母集合なので、Battle Gifterはその部分集合。
        gifter_by_key = {g["identity_key"]: g for g in gifters if g["identity_key"]}
        for key, agg in battle_gifters.items():
            latest = gifter_by_key.get(key)
            # 収集中の配信では、gifter_rows(読取り接続)を読んだ後に届いたgiftがBattle側
            # (writer接続でflush済みを読む)にだけ現れうる。その1件は観測値のまま出し、
            # 次の読み込みで最新の身元に揃う。
            if latest is None:
                continue
            for field in ("user_id", "unique_id", "nickname", "avatar", "league",
                          "fans_level", "gifter_level", "gifter_badge", "member_badge"):
                agg[field] = latest[field]
        battle_gifter_list = sorted(battle_gifters.values(), key=lambda g: g["diamonds"], reverse=True)

        # Per-battle history (newest first) — the chronological record behind the
        # aggregate: each battle's scores, result, primary opponent and the coins
        # raised in its window. The frontend reverses it for a score-over-battles
        # trend chart and lists it as a table.
        history = []
        for pb in parsed_battles:
            b = pb["battle"]
            opps = b.get("opponents", []) or []
            opp = max(opps, key=lambda o: o.get("score", 0) or 0, default=None) if opps else None
            # own_scoreはチーム戦ではチーム合計。監視配信者1人ぶんのscoreは participants の
            # 自hostが持つ。個人戦(個人マルチ含む)は自陣host=1人なのでown_scoreと同値。
            # チーム戦で自hostを特定できない古いrecordはNone(不明)にする。0を入れると
            # 「そのBattleは無得点だった」と読める偽の実測値になるため。
            btype = b.get("type") or "personal"
            own_host = next(
                (p for p in (b.get("participants") or []) if p.get("is_own")), None
            )
            if own_host is not None:
                own_host_score = own_host.get("score", 0) or 0
            else:
                own_host_score = (b.get("own_score", 0) or 0) if btype != "team" else None
            history.append(
                {
                    "session_id": pb["session_id"],
                    "battle_id": b.get("battle_id"),
                    "started_at": b.get("start_time"),
                    "ended_at": b.get("end_time"),
                    "type": btype,
                    "own_score": b.get("own_score", 0) or 0,
                    "own_host_score": own_host_score,
                    "opp_score": b.get("opp_score", 0) or 0,
                    "result": b.get("result"),
                    "diamonds": pb["window_diamonds"],
                    "team_diamonds": pb["team_diamonds"],
                    "key_contributors": pb["key_contributors"],
                    "team_key_contributors": pb["team_key_contributors"],
                    "opponent_count": len(opps),
                    # 表に出す相手は最高scoreの1人だが、絞り込みは参加した全員に当てる。
                    # 代表1人だけをkeyにすると、チーム戦・個人マルチで格下だった相手から
                    # その対戦へ辿れない(対戦相手別の戦数と履歴の件数も食い違う)。
                    "opponent_keys": [k for k in (_opponent_key(o) for o in opps) if k],
                    # 監視画面のコラボ相手(数値user_idしか名乗らない)から、その相手が出た
                    # 戦へ辿るための軸。opponent_keysの中身に頼らず明示する。
                    "opponent_user_ids": [
                        str(o["user_id"]) for o in opps if o.get("user_id")
                    ],
                    "opponent": {
                        "unique_id": opp.get("unique_id", ""),
                        "nickname": opp.get("nickname", "") or "(unknown)",
                        "avatar": opp.get("avatar", ""),
                    }
                    if opp
                    else None,
                }
            )
        history.sort(key=lambda h: h["started_at"] or 0, reverse=True)
        # 各Battleを含む録画(あれば)。画面はこれを根拠に「その対戦の動画へ飛ぶ」を出す。
        # 動画の何秒地点かはここでは出さない — 壁時計と動画の時間軸は一致せず、変換には
        # 録画fileの時刻anchorが要る(server側 /api/recordings/{id}/locate が担う)。
        for h in history:
            cover = _covering_recording(recording_rows, h["session_id"], h["started_at"])
            h["recording_id"] = cover["id"] if cover else None

        # 1戦あたり「主力貢献者(coin >= 閾値)」の平均人数。過去全Battleを集約した指標。
        # 自室のGift eventで実測した分と、armies由来のチーム全体分の両方を出す(チーム戦は
        # 味方hostの貢献者を自陣hostと分離できないため、片方だけでは実態を表さない)。
        key_contrib_sum = sum(pb["key_contributors"] for pb in parsed_battles)
        team_key_contrib_sum = sum(pb["team_key_contributors"] for pb in parsed_battles)
        # 自hostのscoreが不明なBattleは平均の母数からも外す(0として均すと平均が下振れする)。
        own_host_scores = [h["own_host_score"] for h in history if h["own_host_score"] is not None]
        battle_summary = {
            "count": battle_count,
            # 不成立として外した戦数と、その閾値。件数を出さないと「対戦数」が実際の枠数と
            # 食い違う理由が画面から判らなくなる(閾値も画面で数値を再掲しない)。
            "no_contest": dropped_no_contest,
            "no_contest_score": _BATTLE_NO_CONTEST_SCORE,
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "win_rate": (wins / decided * 100) if decided else 0,
            "avg_own_score": (own_score_sum / battle_count) if battle_count else 0,
            "avg_own_host_score": (sum(own_host_scores) / len(own_host_scores)) if own_host_scores else 0,
            "own_host_score_count": len(own_host_scores),
            "avg_opp_score": (opp_score_sum / battle_count) if battle_count else 0,
            "key_contrib_threshold": _BATTLE_KEY_CONTRIB_DIAMONDS,
            "key_contrib_total": key_contrib_sum,
            "avg_key_contributors": (key_contrib_sum / battle_count) if battle_count else 0,
            "team_key_contrib_total": team_key_contrib_sum,
            "avg_team_key_contributors": (team_key_contrib_sum / battle_count) if battle_count else 0,
            "battle_diamonds": battle_diamonds,
            "battle_team_diamonds": battle_team_diamonds,
            "battle_diamond_share": (battle_diamonds / totals["diamonds"] * 100) if totals["diamonds"] else 0,
            # 対戦相手は全件返す。上位30名で切ると「31位以降は0戦」と読めてしまい、
            # 画面の絞り込みも app.js の対戦成績突合(pkVsRecord)も裾の相手に当たらない。
            # 件数は配信者あたり数百で、絞り込み/並べ替えはFrontendが持つ。
            "opponents": opponent_list,
            "gifters": battle_gifter_list[:30],
            # 履歴も件数を切らない。直近80戦で切っていた頃は、対戦相手別で選んだ相手の
            # 対戦が1件も出ないこと(実測: 1配信者313戦)が普通にあり、「対戦数5」と出て
            # いる相手の動画へ辿れなかった。相手別の追跡が裾まで届くことを優先する。
            "history": history,
        }

        return {
            "identity": identity,
            "count": count,
            "sessions": sessions,
            "totals": totals,
            "average": average,
            "best": best,
            "viewer_level": viewer_level,
            # コインの日次合計(event時刻ベース)。推移のコイン段が読む。
            "daily_coins": daily_coins,
            "gifters": gifters[:100],
            # ライバーだけを抜いた一覧。gifters[:100] から絞ると、コイン順で100位より下の
            # ライバーが消えて「誰が投げたか」が欠ける(比率の分子には入っているのに一覧に
            # 居ない、という食い違いになる)ため、母集合から直接採る。
            "livers": [g for g in gifters if g["league"]][:50],
            "concentration": concentration,
            "battles": battle_summary,
            "coop": coop,
            "heatmap": heatmap,
        }

    def streamer_cohort(self, unique_id: str) -> dict:
        """Daily viewer cohort/retention for one streamer. A viewer counts as
        present on a day if they produced any watch-side event (entering the room,
        commenting, liking, following, sharing, subscribing, or gifting) — presence
        is what matters here, not whether they gifted. For each day: active viewers,
        new (first-ever visit this day), retained (present on the previous active day
        as well), and retention = share of the previous active day's viewers who came
        back to watch this day — None on the first day, which has nothing to compare
        against. Days are local-time so they line up with the browser-local UI.

        大口帯(tiers)も同じ走査から出す。1人1日ぶんのコイン合計はこの集計が既に持って
        いるので、帯の人数のためだけに全期間をもう一度走らせない。

        帯の顔ぶれ(whales_list)も併せて返す。人数だけでは「同じ常連が毎日居るのか、
        日替わりで別人が来ているのか」が読めないためである。身元は人ぶんしか無い(日数×人
        ではない)ので、日ごとの一覧はidentity_keyと額だけを持ち、名前・アイコンは
        peopleへ1人1件で畳む。"""
        with self._lock:
            handles = self._owner_handles_locked(unique_id)
        ph = ",".join("?" * len(handles))
        # 書き込み接続で流すとその間collectorのevent書き出しが待たされるので、集計read専用の
        # 接続を使う。走査そのものはsession単位cache越しに行う(_cohort_day_index)。
        conn = self._read_connection()
        session_rows = conn.execute(
            f"SELECT id, ended_at FROM sessions WHERE unique_id IN ({ph})", tuple(handles)
        ).fetchall()
        by_day = self._cohort_day_index(conn, session_rows)
        first_seen: dict = {}
        for ymd, coins_by_key in by_day.items():
            for key in coins_by_key:
                if key not in first_seen or ymd < first_seen[key]:
                    first_seen[key] = ymd
        days = []
        prev_keys: set = set()
        whale_keys: set = set()
        for ymd in sorted(by_day.keys()):
            keys = set(by_day[ymd].keys())
            new = {k for k in keys if first_seen[k] == ymd}
            retained = keys & prev_keys
            tiers = [0] * len(_WHALE_TIERS)
            whales_list = []
            # identity_key順に見る。同額が並んだときの一覧の順と、上限で切ったときに
            # 誰が残るかを、cacheの埋まり具合(=どのsessionから畳んだか)で変えないため。
            for key, coins in sorted(by_day[ymd].items()):
                idx = _whale_tier_index(coins)
                if idx is not None:
                    tiers[idx] += 1
                    whales_list.append({"key": key, "coins": coins, "tier": idx})
            # 額の多い順。切るときも上から残す(下から欠けるほうが読み手の期待に近い)。
            whales_list.sort(key=lambda w: -w["coins"])
            del whales_list[_WHALE_ROSTER_PER_DAY:]
            whale_keys.update(w["key"] for w in whales_list)
            days.append(
                {
                    "date": ymd,
                    "active": len(keys),
                    "new": len(new),
                    # 前回配信日にも居た人。この日のActiveは new / retained / 残り(復帰)で
                    # 過不足なく分かれる(newは初観測なのでretainedと重ならない)。
                    "retained": len(retained),
                    # 比べる前の日が無い初日は率が存在しない。0を入れると「全員離脱した日」
                    # として棒・線に描かれてしまうので、無いものは無いまま返す。
                    "retention": (len(retained) / len(prev_keys) * 100) if prev_keys else None,
                    "diamonds": sum(by_day[ymd].values()),
                    "tiers": tiers,
                    # 合計は全帯の和ではなく、大口の下限以上だけを積む。手前の帯
                    # (100〜1K)は内訳として出すが、大口の人数には数えない。
                    "whales": sum(tiers[_WHALE_TOTAL_INDEX:]),
                    # 顔ぶれ。tiersが人数で、こちらは誰かの一覧(上限で切れうる)。
                    "whales_list": whales_list,
                }
            )
            prev_keys = keys
        return {
            "days": days,
            "tiers": _whale_tier_defs(),
            "total": _whale_total_def(),
            "people": self._whale_people(conn, handles, whale_keys),
        }

    def _cohort_day_index(self, conn, session_rows) -> dict:
        """cohortの素材 {日付: {identity_key: その日のコイン合計}} を組み立てる。

        以前はこの配信者の全期間を毎回1本のGROUP BYで数え直していた。indexは効いていて
        full scanも無く(SEARCH s USING COVERING INDEX idx_sessions_unique_started →
        SEARCH e USING INDEX idx_events_session_kind_time)、遅いのは畳む作業そのもの
        だった: 実測で105万行を14.6万groupへ畳んで cold 5,016ms / warm 2,405〜3,025ms、
        うちstrftime('localtime')が約1.3秒。同条件のCOUNT(*)だけなら328msなので、SQLの
        書き方を変えても取り返せない。

        終了済みsessionのeventは増えないので、session単位まで畳んだ中間結果を残し、次から
        は新しいsessionぶんだけ計算する。日別への畳み込みはsessionを跨いで足せる(同じ日に
        2本配信していれば両方のコインが同じ日へ乗る)ので、session単位で切っても全期間を
        1本で数えたのと同じ値になる。

        収集中(未終了)のsessionはcacheに載せない — まだeventが増えるため、毎回その場で
        数える。"""
        cached = self._ensure_cohort_cache(conn, session_rows)
        live_ids = [row["id"] for row in session_rows if row["id"] not in cached]
        by_day: dict = {}
        for payload in (*cached.values(), *self._cohort_payloads(conn, live_ids).values()):
            for ymd, coins_by_key in payload.items():
                day = by_day.setdefault(ymd, {})
                for key, coins in coins_by_key.items():
                    day[key] = day.get(key, 0) + coins
        return by_day

    def _cohort_payloads(self, conn, session_ids: list) -> dict:
        """指定sessionぶんの {日付: {identity_key: コイン合計}} をsession単位で返す。

        keyか日付が空のeventは落とす。落としてよいのは、この2つがcohortの座標そのもの
        (誰が・いつ)で、欠けた行はどの日の誰にも数えられないためである。JSONのobject
        keyにはnullを置けないので、cacheへ載せる前のこの位置で落とす。"""
        out: dict = {sid: {} for sid in session_ids}
        if not session_ids:
            return out
        kph = ",".join("?" * len(_COHORT_EVENT_KINDS))
        rows = conn.execute(
            "SELECT e.session_id AS session_id, e.identity_key AS key,"
            " strftime('%Y-%m-%d', e.time, 'unixepoch', 'localtime') AS ymd,"
            " SUM(e.diamonds) AS diamonds FROM events e"
            " WHERE e.session_id IN (SELECT je.value FROM json_each(?) je)"
            f" AND e.kind IN ({kph})"
            " GROUP BY e.session_id, e.identity_key, ymd",
            (json.dumps(session_ids), *_COHORT_EVENT_KINDS),
        ).fetchall()
        for row in rows:
            if not row["ymd"] or not row["key"]:
                continue
            out[row["session_id"]].setdefault(row["ymd"], {})[row["key"]] = row["diamonds"] or 0
        return out

    def _ensure_cohort_cache(self, conn, session_rows) -> dict:
        """終了済みsessionのcohort payloadを作って保存し、session_id -> payload を返す。"""
        return self._cached_session_payloads(
            conn, [row["id"] for row in session_rows if row["ended_at"] is not None],
            _COHORT_CACHE_KIND, _COHORT_CACHE_VERSION, self._cohort_payloads)

    def _cached_session_payloads(self, conn, session_ids: list, kind: str, version: int,
                                 compute) -> dict:
        """session単位payloadのcacheを読み、未計算ぶんだけcomputeして保存する。

        作法は全体解析の _ensure_analytics_cache と同じ: 置き場は analytics_session_cache
        (session削除のON DELETE CASCADEが既にあり、表を増やさずに済む)、計算はread専用接続、
        write lockはcache行のINSERTのぶんだけ。versionを上げると既存行がlazyに作り直される。

        **cacheに載せてよいsessionを選ぶのは呼び出し側**である。判断の材料(終了済みか、
        素材が揃っているか)はcacheの種類ごとに違い、ここからは見えない。

        版をanalytics.CACHE_VERSIONSへ置かないのは、あちらのkind一覧が
        「analytics.compute_payloadが計算できるもの」の定義でもあるためで、混ぜるとfinalize時の
        全kind計算がこれらのkindを計算しようとして落ちる。"""
        payloads: dict = {}
        if not session_ids:
            return payloads
        for row in conn.execute(
            "SELECT session_id, payload_json FROM analytics_session_cache"
            " WHERE kind = ? AND version = ?"
            " AND session_id IN (SELECT je.value FROM json_each(?) je)",
            (kind, version, json.dumps(session_ids)),
        ).fetchall():
            payloads[row["session_id"]] = json.loads(row["payload_json"])
        missing = [sid for sid in session_ids if sid not in payloads]
        if not missing:
            return payloads
        computed = compute(conn, missing)
        now = time.time()
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO analytics_session_cache"
                " (session_id, kind, version, payload_json, computed_at)"
                " VALUES (?, ?, ?, ?, ?)",
                [
                    (sid, kind, version, json.dumps(payload), now)
                    for sid, payload in computed.items()
                ],
            )
            self._conn.commit()
        logger.info(
            "配信者集計cache: session %d 件を計算しました（kind=%s）", len(computed), kind,
            extra={"event": "streamers.cache_filled",
                   "ctx": {"kind": kind, "sessions": len(computed), "version": version}},
        )
        payloads.update(computed)
        return payloads

    def _heatmap_cells(self, conn, handles: list, ph: str) -> list:
        """時間帯heatmap(曜日×時×15分)のcellを、session単位cache越しに組み立てる。

        bucketの時系列から出すのは、1配信のコイン・コメントを開始時刻の1時間へ寄せずに
        実際に起きた時間帯へ落とすため。'localtime'で切るのはこのlocalhost appの画面
        (browserのlocal時刻)と同じ格子に載せるためで、**日と時の境目の意味はcacheにしても
        変えていない** — 同じstrftimeを、全期間に対して毎回ではなくsessionごとに1度だけ
        通しているだけである。

        毎回数え直していた頃は実測205〜246ms掛かっていた。bucketは1配信者で141,068行あり、
        1行につき strftime('localtime') を3回呼ぶ(曜日・時・分)ので、42万回の時刻変換が
        そのまま画面の待ち時間になっていた。

        cacheに載せるのは**終了済みで、かつbucketが1本以上あるsession**だけである。bucketが
        0本のsessionを載せてはいけない: 起動時のbackfill_missing_bucketsが後から作り直す
        対象がまさにそれで、空のcellを覚えると作り直した後も空のままになる。"""
        session_rows = conn.execute(
            "SELECT s.id AS id, (s.ended_at IS NOT NULL"
            "  AND EXISTS (SELECT 1 FROM buckets b WHERE b.session_id = s.id)) AS cacheable"
            f" FROM sessions s WHERE s.unique_id IN ({ph})",
            tuple(handles),
        ).fetchall()
        cached = self._cached_session_payloads(
            conn, [row["id"] for row in session_rows if row["cacheable"]],
            _HEATMAP_CACHE_KIND, _HEATMAP_CACHE_VERSION, self._heatmap_payloads)
        live = [row["id"] for row in session_rows if row["id"] not in cached]
        cells: dict = {}
        for payload in (*cached.values(), *self._heatmap_payloads(conn, live).values()):
            for cell in payload:
                key = (cell[0], cell[1], cell[2])
                acc = cells.setdefault(key, [0, 0, 0])
                acc[0] += cell[3]
                acc[1] += cell[4]
                acc[2] += cell[5]
        # 曜日→時→15分の昇順。畳む前の1本のGROUP BYが返していた順と同じにする。
        return [
            {"dow": dow, "hour": hour, "quarter": quarter,
             "diamonds": acc[0], "comments": acc[1], "active_seconds": acc[2]}
            for (dow, hour, quarter), acc in sorted(cells.items())
        ]

    def _heatmap_payloads(self, conn, session_ids: list) -> dict:
        """指定sessionぶんのheatmap cellを session_id -> [[曜日,時,15分,coin,comment,秒], ...]。

        strftimeは1行につき1回だけ呼び、'%w%H%M'を1つの文字列で受けてから桁で割る(曜日1桁・
        時2桁・分2桁で固定長)。曜日・時・分を別々に呼ぶと同じ時刻変換を3回払うことになる。
        内側でその文字列ごとに畳んでから15分へ丸めるのは、外側のGROUP BYが見る行数を
        bucket数から分単位のcell数へ落とすためである(実測: 205ms → 109ms、出力は同一)。"""
        out: dict = {sid: [] for sid in session_ids}
        if not session_ids:
            return out
        for row in conn.execute(
            "SELECT session_id AS session_id, CAST(substr(k, 1, 1) AS INTEGER) AS dow,"
            " CAST(substr(k, 2, 2) AS INTEGER) AS hour,"
            " CAST(substr(k, 4, 2) AS INTEGER) / 15 AS quarter,"
            " SUM(d) AS diamonds, SUM(c) AS comments, SUM(a) AS active_seconds FROM ("
            "  SELECT b.session_id AS session_id,"
            "   strftime('%w%H%M', b.start, 'unixepoch', 'localtime') AS k,"
            "   SUM(b.diamonds) AS d, SUM(b.comments) AS c, SUM(s.bucket_seconds) AS a"
            "   FROM buckets b JOIN sessions s ON s.id = b.session_id"
            "   WHERE b.session_id IN (SELECT je.value FROM json_each(?) je)"
            "   GROUP BY b.session_id, k)"
            " GROUP BY session_id, dow, hour, quarter",
            (json.dumps(session_ids),),
        ).fetchall():
            out[row["session_id"]].append([
                row["dow"], row["hour"], row["quarter"],
                row["diamonds"] or 0, row["comments"] or 0, row["active_seconds"] or 0,
            ])
        return out

    def _whale_people(self, conn, handles: list, keys: set) -> dict:
        """大口の身元(表示名・@id・アイコン)をidentity_keyごとに1件だけ返す。

        日ごとの一覧へ埋め込むと同じ人の身元を日数ぶん繰り返すことになる(実測で1人が
        数十日に出る)。users表(最新)を主にして、一度も観測できていない列だけをevent
        記録値で補う — profileのGifter一覧と同じ解決規則。"""
        out: dict = {}
        keys = [k for k in keys if k]
        if not keys or not handles:
            return out
        ph = ",".join("?" * len(handles))
        # keyの数だけplaceholderを並べるので、SQLiteの変数上限へ触れないよう分けて引く。
        for i in range(0, len(keys), 400):
            chunk = keys[i:i + 400]
            kph = ",".join("?" * len(chunk))
            rows = conn.execute(
                "SELECT e.identity_key AS key,"
                " COALESCE(NULLIF(u.unique_id, ''), MAX(e.user_unique_id)) AS unique_id,"
                " COALESCE(NULLIF(u.nickname, ''), MAX(e.user_nickname)) AS nickname,"
                # avatarは event_strings へintern済み。値へJOINしてからMAXを採る。
                " COALESCE(NULLIF(u.avatar, ''), MAX(av.value)) AS avatar"
                " FROM events e JOIN sessions s ON s.id = e.session_id"
                " LEFT JOIN users u ON u.identity_key = e.identity_key"
                " LEFT JOIN event_strings av ON av.id = e.user_avatar_id"
                f" WHERE s.unique_id IN ({ph}) AND e.kind = 'gift'"
                f" AND e.identity_key IN ({kph})"
                " GROUP BY e.identity_key",
                (*handles, *chunk),
            ).fetchall()
            for row in rows:
                out[row["key"]] = {
                    "unique_id": row["unique_id"] or "",
                    "nickname": row["nickname"] or "",
                    "avatar": row["avatar"] or "",
                }
        return out

    def streamer_gifter_ranking(self, unique_id: str, granularity: str = "month",
                                period: str = "", limit: int = 100) -> dict:
        """配信者1人のGifter / Battle Gifterを、暦で切った期間ごとに並べたランキング。

        通算のstreamer_profileとは別の入口で、効くのはこの2つの一覧だけ。KPI・推移・
        Battle成績は通算のまま残す(既存の数字の意味を変えないため)。

        順位の動きを読めるように、選んだ期間とその1つ前の期間を同じ規則で集計して順位差を
        付ける。前の期間に居なかった人はdeltaをNoneで返す — 0や大きな数で埋めると「急上昇」
        として描かれてしまう。

        身元はstreamer_profileと同じくusers表(最新)で解決する。どちらも複数sessionを畳んだ
        表で、「そのSessionでの見え方」という基準を持たないためである。

        Battleはstart_timeの属する期間へ数える。窓は次Battleの開始まで伸びうるので、期間を
        跨いだ窓のGiftもその戦の期間に入る(戦を2つの期間へ割らない)。
        """
        if granularity not in RANKING_GRANULARITIES:
            raise ValueError(f"未知の粒度です: {granularity}")
        with self._lock:
            handles = self._owner_handles_locked(unique_id)
        # 全期間ぶんのGift eventを触るので、書き込み接続で流すとcollectorのevent書き出しが
        # その間待たされる(streamer_profile / cohortと同じ理由)。
        conn = self._read_connection()
        ph = ",".join("?" * len(handles))
        empty = {
            "granularity": granularity, "period": "", "prev_period": "",
            "periods": [], "gifters": [], "battle_gifters": [],
            "battles": 0, "diamonds": 0, "dropped_periods": 0,
        }

        # 期間の一覧はGiftではなく配信の在った範囲から作る。Giftのあった期間だけを並べると、
        # 「配信したが誰も投げなかった」期間が一覧から消える。
        span = conn.execute(
            "SELECT MIN(s.started_at) AS first, MAX(COALESCE(s.ended_at, s.started_at)) AS last"
            f" FROM sessions s WHERE s.unique_id IN ({ph})" + _EXCLUDE_RESTRICTED,
            tuple(handles),
        ).fetchone()
        totals_rows = conn.execute(
            f"SELECT {_PERIOD_SQL[granularity].format(col='e.time')} AS p,"
            " SUM(e.diamonds) AS diamonds, SUM(e.gift_count) AS gifts"
            " FROM events e JOIN sessions s ON s.id = e.session_id"
            f" WHERE s.unique_id IN ({ph}) AND e.kind = 'gift'"
            " GROUP BY p",
            tuple(handles),
        ).fetchall()
        totals = {r["p"]: (r["diamonds"] or 0, r["gifts"] or 0) for r in totals_rows if r["p"]}
        edges = list(totals)
        if span["first"] is not None:
            # 収集中のsessionはended_atを持たない。Giftが今の期間まで届いているので、
            # totals側のkeyと併せて端を決める。
            edges += [_period_key(span["first"], granularity),
                      _period_key(span["last"], granularity)]
        if not edges:
            return empty
        keys, dropped = _period_range(min(edges), max(edges), granularity)
        if not keys:
            return empty
        if dropped:
            logger.warning(
                "期間別ランキングの期間一覧が上限を超えたため古い側を切りました",
                extra={"event": "ranking_periods_truncated", "unique_id": unique_id,
                       "granularity": granularity, "dropped": dropped},
            )

        selected = period if period in set(keys) else keys[-1]
        index = keys.index(selected)
        prev = keys[index - 1] if index > 0 else ""

        def _gift_ranking(key: str) -> list:
            """その期間にGiftを投げた人をコイン順に。順位差のために全件返す(表示側で切る)。"""
            if not key:
                return []
            start, end = _period_bounds(key, granularity)
            rows = conn.execute(
                "SELECT e.identity_key AS key,"
                " COALESCE(NULLIF(u.user_id, ''), MAX(e.user_id)) AS user_id,"
                " COALESCE(NULLIF(u.unique_id, ''), MAX(e.user_unique_id)) AS unique_id,"
                " COALESCE(NULLIF(u.nickname, ''), MAX(e.user_nickname)) AS nickname,"
                # avatarは event_strings へintern済み。値へJOINしてからMAXを採る。
                " COALESCE(NULLIF(u.avatar, ''), MAX(av.value)) AS avatar,"
                " u.fans_level AS fans_level, u.gifter_level AS gifter_level,"
                " u.gifter_badge AS gifter_badge, u.member_badge AS member_badge,"
                f" {display_league_sql('u')} AS league,"
                " SUM(e.diamonds) AS diamonds, SUM(e.gift_count) AS gifts,"
                " COUNT(DISTINCT e.session_id) AS sessions"
                " FROM events e JOIN sessions s ON s.id = e.session_id"
                " LEFT JOIN users u ON u.identity_key = e.identity_key"
                " LEFT JOIN event_strings av ON av.id = e.user_avatar_id"
                f" WHERE s.unique_id IN ({ph}) AND e.kind = 'gift'"
                " AND e.time >= ? AND e.time < ?"
                " GROUP BY e.identity_key"
                " ORDER BY diamonds DESC, gifts DESC",
                (*handles, start, end),
            ).fetchall()
            return [
                {
                    "identity_key": row["key"],
                    "user_id": row["user_id"] or "",
                    "unique_id": row["unique_id"] or "",
                    "nickname": row["nickname"] or "(unknown)",
                    "avatar": row["avatar"] or "",
                    "fans_level": row["fans_level"] or 0,
                    "gifter_level": row["gifter_level"] or 0,
                    "gifter_badge": row["gifter_badge"] or "",
                    "member_badge": row["member_badge"] or "",
                    "league": row["league"] or "",
                    "diamonds": row["diamonds"] or 0,
                    "gifts": row["gifts"] or 0,
                    "sessions": row["sessions"] or 0,
                }
                for row in rows
                if row["key"]
            ]

        battle_agg, battle_counts = self._battle_gifter_periods(
            conn, handles, ph, granularity, {k for k in (selected, prev) if k})
        identities = self._latest_identities(
            conn, {k for period_agg in battle_agg.values() for k in period_agg})

        def _battle_ranking(key: str) -> list:
            if not key:
                return []
            rows = []
            for ik, agg in battle_agg.get(key, {}).items():
                row = dict(identities.get(ik) or _unknown_identity(ik))
                row.update(agg)
                rows.append(row)
            rows.sort(key=lambda g: (g["diamonds"], g["gifts"]), reverse=True)
            return rows

        def _with_rank_delta(current: list, previous: list) -> list:
            prev_rank = {g["identity_key"]: i + 1 for i, g in enumerate(previous)}
            ranked = []
            for i, row in enumerate(current[:limit]):
                row = dict(row)
                row["rank"] = i + 1
                before = prev_rank.get(row["identity_key"])
                row["prev_rank"] = before
                # 前の期間に居なかった=初登場。Noneのまま返し、画面側で「new」と出す。
                row["rank_delta"] = (before - row["rank"]) if before else None
                ranked.append(row)
            return ranked

        current_gifters = _gift_ranking(selected)
        current_battle = _battle_ranking(selected)
        return {
            "granularity": granularity,
            "period": selected,
            # 空文字は「比べる前の期間が無い」。画面はこれを見て順位差の列を—にする。
            "prev_period": prev,
            "periods": [
                {"key": k, "diamonds": totals.get(k, (0, 0))[0], "gifts": totals.get(k, (0, 0))[1]}
                for k in keys
            ],
            "gifters": _with_rank_delta(current_gifters, _gift_ranking(prev)),
            "battle_gifters": _with_rank_delta(current_battle, _battle_ranking(prev)),
            # 一覧はlimitで切るが、人数は切る前の全員。画面上部の集中度chip(通算のGifter数)と
            # 並ぶので、この期間に何人居たのかを切られていない値で名乗る。
            "gifter_count": len(current_gifters),
            "battle_gifter_count": len(current_battle),
            "battles": battle_counts.get(selected, 0),
            "diamonds": totals.get(selected, (0, 0))[0],
            "dropped_periods": dropped,
        }

    def streamer_gifter_matrix(self, unique_id: str, granularity: str = "day",
                               since: str = "", until: str = "",
                               columns: int = 0) -> dict:
        """配信の在った期間を列、Gifterを行にした一覧(人×期間)。

        期間を1つ選ぶstreamer_gifter_rankingと違い、同じ人を期間を跨いで横へ並べる。
        「その期間の中で誰が上か」と「その人が続いているか」を、期間を選び直さずに読む口。

        列は「Giftの在った期間」と「配信の在った期間」の合併にする。sessionの開始日だけで
        組むと日を跨いだ配信の深夜ぶんが列から落ち、そのGiftがどこにも載らない。

        since/untilはカレンダーで選んだ日付('YYYY-MM-DD')で、その日の属する期間まで含む。
        指定が無ければ新しい側から既定の列数を取る。
        """
        if granularity not in RANKING_GRANULARITIES:
            raise ValueError(f"未知の粒度です: {granularity}")
        limit = max(1, min(int(columns or _MATRIX_COLUMNS[granularity]),
                           _MATRIX_COLUMNS_MAX[granularity]))
        since_key = _date_to_period(since, granularity) if since else ""
        until_key = _date_to_period(until, granularity) if until else ""
        if since_key and until_key and since_key > until_key:
            raise ValueError("期間の開始が終了より後です")
        with self._lock:
            handles = self._owner_handles_locked(unique_id)
        # 期間別ランキングと同じく全期間ぶんのGift eventを触るので読み取り専用接続で流す。
        conn = self._read_connection()
        ph = ",".join("?" * len(handles))
        empty = {
            "granularity": granularity, "since": since, "until": until,
            "periods": [], "gifters": [], "battle_gifters": [],
            "gifter_count": 0, "battle_gifter_count": 0, "older_periods": 0,
            "first_date": "", "last_date": "",
        }
        period_sql = _PERIOD_SQL[granularity]
        totals = {}
        for row in conn.execute(
            f"SELECT {period_sql.format(col='e.time')} AS p,"
            " SUM(e.diamonds) AS diamonds, SUM(e.gift_count) AS gifts"
            " FROM events e JOIN sessions s ON s.id = e.session_id"
            f" WHERE s.unique_id IN ({ph}) AND e.kind = 'gift'"
            " GROUP BY p",
            tuple(handles),
        ).fetchall():
            if row["p"]:
                totals[row["p"]] = (row["diamonds"] or 0, row["gifts"] or 0)
        session_periods = {
            row["p"]
            for row in conn.execute(
                f"SELECT DISTINCT {period_sql.format(col='s.started_at')} AS p"
                f" FROM sessions s WHERE s.unique_id IN ({ph})" + _EXCLUDE_RESTRICTED,
                tuple(handles),
            ).fetchall()
            if row["p"]
        }
        all_keys = sorted(set(totals) | session_periods)
        if not all_keys:
            return empty
        # カレンダーの端。指定した範囲に1つも入らなかったときも返す — 「記録が無い」と
        # 「選んだ範囲に無い」を画面が描き分けられるようにするため。
        empty["first_date"] = _period_dates(all_keys[0], granularity)[0]
        empty["last_date"] = _period_dates(all_keys[-1], granularity)[1]
        in_range = [
            key for key in all_keys
            if (not since_key or key >= since_key) and (not until_key or key <= until_key)
        ]
        keys = in_range[-limit:]
        if not keys:
            return empty
        key_set = set(keys)
        start = _period_bounds(keys[0], granularity)[0]
        end = _period_bounds(keys[-1], granularity)[1]

        gift_cells: dict = {}
        for row in conn.execute(
            "SELECT e.identity_key AS key,"
            f" {period_sql.format(col='e.time')} AS p,"
            " SUM(e.diamonds) AS diamonds, SUM(e.gift_count) AS gifts"
            " FROM events e JOIN sessions s ON s.id = e.session_id"
            f" WHERE s.unique_id IN ({ph}) AND e.kind = 'gift'"
            " AND e.time >= ? AND e.time < ?"
            " GROUP BY e.identity_key, p",
            (*handles, start, end),
        ).fetchall():
            if not row["key"] or row["p"] not in key_set:
                continue
            gift_cells.setdefault(row["key"], {})[row["p"]] = {
                "diamonds": row["diamonds"] or 0, "gifts": row["gifts"] or 0,
            }

        battle_agg, battle_counts = self._battle_gifter_periods(
            conn, handles, ph, granularity, key_set)
        battle_cells: dict = {}
        for key, per_identity in battle_agg.items():
            for identity_key, agg in per_identity.items():
                battle_cells.setdefault(identity_key, {})[key] = {
                    "diamonds": agg["diamonds"], "gifts": agg["gifts"],
                    "battles": agg["battles"],
                }
        identities = self._latest_identities(
            conn, set(gift_cells) | set(battle_cells))

        def _rows(cells: dict) -> tuple:
            ranked = sorted(
                cells.items(),
                key=lambda kv: (sum(c["diamonds"] for c in kv[1].values()),
                                sum(c["gifts"] for c in kv[1].values())),
                reverse=True,
            )
            out = []
            for identity_key, per_period in ranked[:_MATRIX_ROWS]:
                row = dict(identities.get(identity_key) or _unknown_identity(identity_key))
                row["cells"] = per_period
                row["diamonds"] = sum(c["diamonds"] for c in per_period.values())
                row["gifts"] = sum(c["gifts"] for c in per_period.values())
                # 投げた期間の数。粒度で意味が変わるので画面が「N 日」「N 週」と名乗る。
                row["periods"] = len(per_period)
                out.append(row)
            return out, len(ranked)

        gifters, gifter_count = _rows(gift_cells)
        battle_gifters, battle_gifter_count = _rows(battle_cells)
        return {
            "granularity": granularity,
            "since": since,
            "until": until,
            "first_date": empty["first_date"],
            "last_date": empty["last_date"],
            "periods": [
                {"key": key, "diamonds": totals.get(key, (0, 0))[0],
                 "gifts": totals.get(key, (0, 0))[1],
                 "battles": battle_counts.get(key, 0)}
                for key in keys
            ],
            "gifters": gifters,
            "battle_gifters": battle_gifters,
            # 行は_MATRIX_ROWSで切るが、人数は切る前の全員。
            "gifter_count": gifter_count,
            "battle_gifter_count": battle_gifter_count,
            # 上限で出せなかった古い期間の数。黙って切ると「これしか配信していない」と
            # 読める。範囲の外は「選ばなかった」ぶんなので、ここには数えない。
            "older_periods": max(0, len(in_range) - len(keys)),
        }

    def _battle_gifter_periods(self, conn, handles, ph, granularity, wanted: set) -> tuple:
        """欲しい期間ぶんだけ、Battle窓のGift貢献をidentity_key単位で積む。

        窓の解き方(次Battleの開始まで/fallback)はstreamer_profileと同じ。重複収集された
        同じBattleはbattle_idで落とす — これを忘れるとBattle数もコインも二重に乗る。

        Battle貢献はread専用接続で流すので、loopへ入る前にここで1回だけ確定させる。以前は
        Battle 1件ごとにflushしていたため、write lockの取得が1 requestあたりmatrix 48.9回・
        ranking 105回に達していた。
        """
        self.flush()
        # data_jsonは1戦あたりが大きく(実測: 1配信者699戦で23MB)、全戦をparseするだけで
        # 440ms掛かる。窓の解決に要るのは時刻だけなのでjson_extractで引き、実体をparseする
        # のは見ている期間の戦だけにする。annotate_resultはresultとscoreにしか触れないので、
        # ここで抜く時刻はannotate後の値と一致する。
        light_rows = conn.execute(
            "SELECT b.rowid AS rowid, b.session_id AS session_id,"
            " json_extract(b.data_json, '$.battle_id') AS battle_id,"
            " json_extract(b.data_json, '$.start_time') AS start_time,"
            " json_extract(b.data_json, '$.end_time') AS end_time,"
            " json_extract(b.data_json, '$.duration') AS duration"
            " FROM battles b JOIN sessions s ON s.id = b.session_id"
            f" WHERE s.unique_id IN ({ph})"
            " ORDER BY s.started_at ASC, b.session_id ASC",
            tuple(handles),
        ).fetchall()
        rows_by_session: dict = {}
        for row in light_rows:
            rows_by_session.setdefault(row["session_id"], []).append(row)

        agg_by_period: dict = {key: {} for key in wanted}
        counts = {key: 0 for key in wanted}
        seen_battle_ids: set = set()
        # (rowid) -> その戦を数える期間と、窓を閉じるための材料。
        targets: dict = {}
        for session_id, rows in rows_by_session.items():
            # 窓の解決には(期間で絞る前の)そのsessionの全戦を使う。「次Battleの開始」は
            # 見ている期間とは関係なく決まる。
            starts = sorted(r["start_time"] for r in rows if r["start_time"] is not None)
            fallback_duration = gift_window_fallback_duration(
                [{"duration": r["duration"], "start_time": r["start_time"],
                  "end_time": r["end_time"]} for r in rows]
            )
            for row in rows:
                start_time = row["start_time"]
                if start_time is None:
                    continue
                battle_id = row["battle_id"]
                if battle_id:
                    # 重複判定は期間で絞る前に行う。絞ってから数えると、同じBattleの
                    # 重複が「見ている期間の側」に残るかどうかで結果が変わる。
                    if battle_id in seen_battle_ids:
                        continue
                    seen_battle_ids.add(battle_id)
                key = _period_key(start_time, granularity)
                if key not in agg_by_period:
                    continue
                targets[row["rowid"]] = (session_id, key, starts, fallback_duration)

        for rowid, data_json in self._battle_bodies(conn, list(targets)):
            session_id, key, starts, fallback_duration = targets[rowid]
            battle = annotate_result(json.loads(data_json))
            # 勝負が成立しなかった戦はBattle分析から外す(判定はannotate後の値で行う)。
            if _battle_no_contest(battle):
                continue
            counts[key] += 1
            end_time = gift_window_end(battle, starts, fallback_duration)
            for g in self._cached_battle_gift_contributions(
                    session_id, battle, battle.get("start_time"), end_time):
                identity_key = g["key"]
                if not identity_key:
                    continue
                agg = agg_by_period[key].setdefault(
                    identity_key, {"diamonds": 0, "gifts": 0, "battles": 0})
                agg["diamonds"] += g["diamonds"]
                agg["gifts"] += g["gifts"]
                agg["battles"] += 1
        return agg_by_period, counts

    def _battle_bodies(self, conn, rowids: list):
        """rowid指定でbattleの実体を引く。SQLiteの変数上限に当たらないよう分割する。"""
        for start in range(0, len(rowids), 500):
            chunk = rowids[start:start + 500]
            rph = ",".join("?" * len(chunk))
            for row in conn.execute(
                f"SELECT rowid AS rowid, data_json FROM battles WHERE rowid IN ({rph})",
                tuple(chunk),
            ).fetchall():
                yield row["rowid"], row["data_json"]

    def _latest_identities(self, conn, keys: set) -> dict:
        """identity_key -> 最新の表示属性(users表)。SQLiteの変数上限に当たらないよう分割
        して引く。1回のINに全員を並べると、Battleの多い月で静かに落ちる。"""
        found: dict = {}
        pending = [k for k in keys if k]
        for start in range(0, len(pending), 500):
            chunk = pending[start:start + 500]
            kph = ",".join("?" * len(chunk))
            for row in conn.execute(
                "SELECT identity_key, user_id, unique_id, nickname, avatar,"
                " fans_level, gifter_level, gifter_badge, member_badge,"
                f" {display_league_sql('users')} AS league"
                f" FROM users WHERE identity_key IN ({kph})",
                tuple(chunk),
            ).fetchall():
                found[row["identity_key"]] = {
                    "identity_key": row["identity_key"],
                    "user_id": row["user_id"] or "",
                    "unique_id": row["unique_id"] or "",
                    "nickname": row["nickname"] or "(unknown)",
                    "avatar": row["avatar"] or "",
                    "fans_level": row["fans_level"] or 0,
                    "gifter_level": row["gifter_level"] or 0,
                    "gifter_badge": row["gifter_badge"] or "",
                    "member_badge": row["member_badge"] or "",
                    "league": row["league"] or "",
                }
        return found

    def session_rankings(self, limit: int) -> dict:
        # session全件とevent全件のGROUP BY。書き込み接続で流すと、その間ずっとcollectorの
        # event書き出しが同じlockで待たされる(実測: eventのGROUP BYだけでwarm 1.06秒、
        # page cacheが冷えていれば7.4秒)。streamer_index / aggregate_dashboardと同じく
        # 集計read専用の接続へ逃がす。
        conn = self._read_connection()
        base_rows = conn.execute(
            "SELECT id, unique_id, started_at, ended_at, stats_json FROM sessions",
        ).fetchall()
        agg_rows = conn.execute(
            "SELECT session_id,"
            " SUM(CASE WHEN kind = 'like' THEN count ELSE 0 END) AS like_count,"
            " SUM(CASE WHEN kind = 'comment' THEN 1 ELSE 0 END) AS comments,"
            " SUM(CASE WHEN kind = 'gift' THEN diamonds ELSE 0 END) AS diamonds"
            " FROM events GROUP BY session_id",
        ).fetchall()
        agg = {r["session_id"]: r for r in agg_rows}
        sessions = []
        for row in base_rows:
            a = agg.get(row["id"])
            stats = json.loads(row["stats_json"])
            likes_total = stats.get("likes_total")
            likes = likes_total if likes_total is not None else ((a["like_count"] if a else 0) or 0)
            sessions.append(
                {
                    "id": row["id"],
                    "unique_id": row["unique_id"],
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "likes": likes,
                    "comments": (a["comments"] if a else 0) or 0,
                    "diamonds": (a["diamonds"] if a else 0) or 0,
                    "battle_points": stats.get("battle_points") or 0,
                }
            )

        def ranked(metric: str) -> list:
            ordered = sorted(sessions, key=lambda s: s[metric] or 0, reverse=True)
            return [
                {
                    "session_id": s["id"],
                    "unique_id": s["unique_id"],
                    "started_at": s["started_at"],
                    "ended_at": s["ended_at"],
                    "value": s[metric] or 0,
                }
                for s in ordered[:limit]
            ]

        return {
            "likes": ranked("likes"),
            "comments": ranked("comments"),
            "gifts": ranked("diamonds"),
            "battles": ranked("battle_points"),
        }

    def aggregate_dashboard(self) -> dict:
        # 全sessionを跨ぐ通算集計。1本でも数百msかかる質の読み取りなので、書き込み接続を
        # 掴まず集計read専用の接続で流す(この画面は履歴のKPI帯として定期的に叩かれる)。
        conn = self._read_connection()
        with self._lock:
            streamer_handles = self._latest_owner_handles_locked()
        totals = conn.execute(
            _SESSION_TOTALS_CTE +
            "SELECT"
            " (SELECT COUNT(*) FROM sessions) AS sessions,"
            " (SELECT COUNT(*) FROM recordings) AS recordings,"
            " COALESCE(SUM(gifts), 0) AS gifts,"
            " COALESCE(SUM(diamonds), 0) AS diamonds,"
            " COALESCE(SUM(comments), 0) AS comments,"
            " (SELECT COALESCE(SUM(json_extract(stats_json, '$.likes_total')), 0) FROM sessions) AS likes,"
            " (SELECT COALESCE(SUM(CASE WHEN ended_at IS NOT NULL THEN ended_at - started_at ELSE 0 END), 0) FROM sessions) AS duration"
            " FROM session_totals"
        ).fetchone()
        # 表示用handleの選び方はstreamer_indexと同じ(最新sessionのものを決定的に)。
        streamer_rows = conn.execute(
            _SESSION_TOTALS_CTE + _STREAMER_TOTALS_SELECT +
            " GROUP BY okey ORDER BY diamonds DESC",
        ).fetchall()
        # 全sessionを跨ぐ通算集計なので表示属性はusers表(最新)を優先する
        # (理由はstreamer_profileのgifter集計と同じ)。
        # 上位50を先に確定させ、表示属性はその50件ぶんだけ引く。1本のGROUP BYで表示属性まで
        # 一緒にMAXすると、全gift eventでeventsの行本体を読みに行く(index idx_events_kind_
        # identityは金額側しか覆わない)。表示属性はusers表が正で、MAXはusers行が無い/空の
        # ときのfallbackにすぎないため、上位50件に絞ってから引いても答えは同じ(実測46→22ms)。
        gifter_rows = conn.execute(
            "WITH top AS ("
            " SELECT identity_key AS key, SUM(gift_count) AS gifts,"
            " SUM(diamonds) AS diamonds, COUNT(DISTINCT session_id) AS sessions"
            " FROM events WHERE kind = 'gift' GROUP BY identity_key"
            " ORDER BY diamonds DESC, gifts DESC LIMIT 50)"
            " SELECT t.key AS key,"
            " COALESCE(NULLIF(u.user_id, ''), (SELECT MAX(user_id) FROM events"
            "   WHERE kind = 'gift' AND identity_key = t.key)) AS user_id,"
            " COALESCE(NULLIF(u.unique_id, ''), (SELECT MAX(user_unique_id) FROM events"
            "   WHERE kind = 'gift' AND identity_key = t.key)) AS unique_id,"
            " COALESCE(NULLIF(u.nickname, ''), (SELECT MAX(user_nickname) FROM events"
            "   WHERE kind = 'gift' AND identity_key = t.key)) AS nickname,"
            # ここだけ相関subquery形。avatarは event_strings へintern済みなので、JOINを
            # 足すのではなくsubquery側を書き換える。**MAX(user_avatar_id) では駄目で**、
            # 値へJOINしてからMAXを採ること(idの最大は辞書順最大と一致しない)。
            # 内側のJOINで落ちるのはid列がNULLの行だが、元のMAXもNULLは無視するので
            # 同じ答えになる(1件も残らなければ双方ともNULL)。
            " COALESCE(NULLIF(u.avatar, ''), (SELECT MAX(av.value) FROM events e2"
            "   JOIN event_strings av ON av.id = e2.user_avatar_id"
            "   WHERE e2.kind = 'gift' AND e2.identity_key = t.key)) AS avatar,"
            " u.fans_level AS fans_level, u.gifter_level AS gifter_level,"
            " u.gifter_badge AS gifter_badge, u.member_badge AS member_badge,"
            f" {display_league_sql('u')} AS league,"
            " t.gifts AS gifts, t.diamonds AS diamonds, t.sessions AS sessions"
            " FROM top t LEFT JOIN users u ON u.identity_key = t.key"
            " ORDER BY t.diamonds DESC, t.gifts DESC",
        ).fetchall()
        gift_rows = conn.execute(
            "SELECT gift_name AS name, SUM(gift_count) AS count, SUM(diamonds) AS diamonds"
            " FROM events WHERE kind = 'gift'"
            " GROUP BY gift_name ORDER BY diamonds DESC, count DESC LIMIT 50",
        ).fetchall()
        session_rows = conn.execute(
            "SELECT id, unique_id, started_at,"
            " COALESCE(json_extract(stats_json, '$.diamonds'), 0) AS diamonds,"
            " COALESCE(json_extract(stats_json, '$.gifts'), 0) AS gifts,"
            " COALESCE(json_extract(stats_json, '$.comments'), 0) AS comments"
            " FROM sessions ORDER BY started_at DESC LIMIT 30",
        ).fetchall()
        return {
            "totals": dict(totals),
            "streamers": [
                {
                    "unique_id": streamer_handles.get(row["okey"], row["okey"]),
                    "sessions": row["sessions"],
                    "gifts": row["gifts"],
                    "diamonds": row["diamonds"],
                    "comments": row["comments"],
                    "last_started_at": row["last_started_at"],
                }
                for row in streamer_rows
            ],
            "top_gifters": [
                {
                    "user_id": row["user_id"] or "",
                    "unique_id": row["unique_id"] or "",
                    "nickname": row["nickname"] or "(unknown)",
                    "avatar": row["avatar"] or "",
                    "fans_level": row["fans_level"] or 0,
                    "gifter_level": row["gifter_level"] or 0,
                    "gifter_badge": row["gifter_badge"] or "",
                    "member_badge": row["member_badge"] or "",
                    "league": row["league"] or "",
                    "gifts": row["gifts"] or 0,
                    "diamonds": row["diamonds"] or 0,
                    "sessions": row["sessions"],
                }
                for row in gifter_rows
            ],
            "top_gifts": [dict(row) for row in gift_rows],
            "recent_sessions": [dict(row) for row in reversed(session_rows)],
        }
