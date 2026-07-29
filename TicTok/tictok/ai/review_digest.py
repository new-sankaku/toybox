"""AI講評へ渡す入力の組み立て。

配信者profileだけを渡していた頃、講評の「時間帯傾向」はheatmapの上位5セル(=最も稼いだ
15分枠を並べただけ)を根拠に語られていた。1回の大口ギフトでも上位に来るセルで、
配信全体の傾向ではない。全体解析(analytics)側には信頼区間・標本数・被覆率付きの推定量が
既に計算されているので、そちらを渡す。

ただし全体解析の母集団は**監視対象の配信者すべて**であって、この配信者ではない。混ぜて
渡すとmodelはそれをこの配信者の実績として書く。よって

  - この配信者由来の値  → ``streamer``
  - 横断の参考値        → ``cross_streamer_reference``

と入れ物を分け、prompt側でも用途を明示する(ai_analysis._REVIEW_RULES)。

すべての指標に n / ci / significant / coverage を同梱する。有意でない値を落として渡さない
のは、「無い」と「弱い」の区別が付かなくなるため。判断はmodelへ委ね、根拠の弱さを言葉に
出させる。
"""

from typing import Optional

from tictok.core.config import get_ai_review_min_observations

# 横断参考値として渡す時間帯の件数。全72 slot(20分刻み)を渡すとpromptがそれだけで
# 埋まるので、指数の高い順に絞る。件数はslot全体のうちのごく一部という位置付けを
# 崩さない範囲(1日の1/6程度)。
_TOP_SLOTS = 12
_DOW_LABELS = ("日", "月", "火", "水", "木", "金", "土")


def _significant(n: Optional[int], ci: Optional[list] = None,
                 reference: Optional[float] = None) -> Optional[bool]:
    """標本数が足りているか、CIがあるならreference値を跨いでいないか。

    Noneは「判定できない」。Falseと同じ扱いにするとmodelは「有意でない」と読むが、
    実際には測っていないだけのことがあるため区別する。
    """
    if n is None:
        return None
    if n < get_ai_review_min_observations():
        return False
    if ci is None or reference is None:
        return None
    low, high = ci[0], ci[1]
    return low > reference or high < reference


def _stat(value, n: Optional[int], *, ci: Optional[list] = None,
          reference: Optional[float] = None, note: str = "") -> dict:
    """1つの推定量を、確からしさの材料ごと1つのdictにまとめる。"""
    out = {"value": value, "n": n, "significant": _significant(n, ci, reference)}
    if ci is not None:
        out["ci95"] = ci
    if reference is not None:
        out["reference"] = reference
    if note:
        out["note"] = note
    return out


def _time_index_digest(time_index: dict) -> dict:
    """時間帯index(全配信の平均を1.0とした相対倍率)の上位slot。

    セルごとにその倍率が何観測から出たものかが違うので、必ずセル単位でnを付ける。
    """
    slots = []
    for slot in time_index["slots"]:
        cell = slot["all"]
        if cell["index"] is None:
            continue
        minute = slot["minute"]
        slots.append({
            "時刻": f"{minute // 60:02d}:{minute % 60:02d}",
            "index": cell["index"],
            "n": cell["n"],
            "significant": _significant(cell["n"]),
        })
    slots.sort(key=lambda s: s["index"], reverse=True)
    return {
        "指標": time_index["metric"],
        "説明": "1.0が全配信の平均。20分刻み。値が大きい時間帯ほどレートが高い。",
        "上位時間帯": slots[:_TOP_SLOTS],
        "n_sessions": time_index["n_sessions"],
        "n_observations": time_index["n_observations"],
    }


def _retention_digest(retention: dict) -> dict:
    overall = retention["overall"]
    hours = [h for h in retention["by_hour"] if h["join_rate"] is not None]
    hours.sort(key=lambda h: h["join_rate"], reverse=True)
    return {
        "入室あたり同接押し上げ": _stat(
            overall["lift_per_join"], overall["joins"],
            note="平常drift(入室の無いbucketの平均変化)を差し引いた推定値。"),
        "入室レート上位時刻": [
            {"時刻": f"{h['hour']:02d}時", "件_分": h["join_rate"], "平均同接": h["viewers"]}
            for h in hours[:6]
        ],
        "n_sessions": retention["n_sessions"],
    }


def _entry_source_digest(entry_source: dict) -> dict:
    joins = entry_source["joins"]
    engaged = entry_source["engaged"]
    return {
        "流入元": {
            "内訳": joins["surfaces"][:6],
            "coverage": joins["coverage"],
            "measured": joins["measured"],
            "note": "coverageは流入元を取得できた入室の割合。残りは計測不能で、0件ではない。",
        },
        "入室者のfollow関係": {
            "内訳": joins["follow"]["breakdown"],
            "coverage": joins["follow"]["coverage"],
            "measured": joins["follow"]["measured"],
        },
        "反応した視聴者のfollow関係": {
            "内訳": engaged["breakdown"],
            "coverage": engaged["coverage"],
            "measured": engaged["measured"],
        },
        "n_sessions_measured": entry_source["n_sessions_measured"],
        "n_sessions": entry_source["n_sessions"],
    }


def _battle_flow_digest(battle_flow: dict) -> dict:
    checkpoint = battle_flow["checkpoint"]
    tail = battle_flow["tail"]["raw"]

    def _rate(entry: dict) -> dict:
        # 勝率は0.5を跨がないときだけ「偏りがある」と言える。
        return _stat(entry["rate"], entry["n"], ci=entry["ci"], reference=0.5)

    return {
        "対象battle数": battle_flow["n_eligible"],
        "リード交代回数": {
            "中央値": battle_flow["lead_changes"]["median"],
            "n": battle_flow["lead_changes"]["n"],
        },
        f"残り{checkpoint['seconds']}秒リード時の勝率": _rate(checkpoint["own"]),
        f"残り{checkpoint['seconds']}秒ビハインド時の勝率": _rate(checkpoint["opp"]),
        # 逆転率には「偏りが無い状態」の基準値が無い(半分が逆転する、という帰無仮説は
        # 意味を成さない)ので、CIは示すが有意判定は標本数だけで行う。
        "逆転率": _stat(checkpoint["comeback"]["rate"], checkpoint["comeback"]["n"],
                     ci=checkpoint["comeback"]["ci"]),
        f"終盤{battle_flow['tail']['seconds']}秒の得点シェア": {
            "中央値": tail["median"],
            "一様配分の中央値": tail["uniform_median"],
            "n": tail["n"],
            "終盤型": tail["heavy"], "平坦": tail["flat"], "序中盤型": tail["light"],
        },
        "note": ("リード時の勝率は記述統計であり戦術の効果ではない"
                 "(リードしている側はそもそも強いという選択効果を含む)。"),
    }


def _ratio_percent(ratio):
    """0-1の比率をpercentへ。未計測(None)はNoneのまま返す(0で埋めない)。"""
    return None if ratio is None else round(ratio * 100, 2)


def _coverage_digest(coverage: dict) -> dict:
    """解析そのものの信頼度。欠測が多ければ上の指標も割り引いて読む必要がある。"""
    return {
        "収集欠測秒_中央値": coverage["gaps"]["seconds"]["median"],
        "欠測を計測できたsession数": coverage["gaps"]["n_sessions"],
        "同接sampling間隔_中央値秒": coverage["sampling"]["median"]["median"],
        "録画率_percent中央値": coverage["recording"]["ratio"]["median"],
        # analytics側は録画率をpercent、転写率を比率で返す。単位を揃えずに渡すと
        # modelが比率をそのままpercentとして読み(0.9451→"0.9451%")、100倍ずれた
        # 講評になる。ここでpercentへ統一し、key名にも単位を明示する。
        "転写率_percent": _ratio_percent(coverage["transcript"]["ratio"]),
        "n_sessions": coverage["n_sessions"],
        "note": "収集の健全性。欠測が大きいsessionが多いほど、他の指標の推定も粗くなる。",
    }


def streamer_digest(profile: dict) -> dict:
    """配信者profileだけから作れる部分(この配信者の実績)。"""
    battles = profile["battles"]
    heatmap_top = sorted(profile["heatmap"], key=lambda c: c["diamonds"], reverse=True)[:5]
    coop = profile.get("coop")
    digest = {
        "配信者": profile["identity"]["nickname"],
        "配信回数": profile["count"],
        "通算": profile["totals"],
        "平均": {k: round(v) for k, v in profile["average"].items()},
        "自己ベスト": profile["best"],
        "収益集中度": profile["concentration"],
        "Battle": {
            k: battles[k]
            for k in ("count", "wins", "losses", "win_rate", "avg_own_score",
                      "avg_opp_score", "battle_diamond_share")
        },
        "上位gifter": [
            {"name": g["nickname"], "diamonds": g["diamonds"], "出現session": g["sessions"]}
            for g in profile["gifters"][:10]
        ],
        "Battle上位gifter": [
            {"name": g["nickname"], "diamonds": g["diamonds"], "出現battle": g["battles"]}
            for g in battles.get("gifters", [])[:8]
        ],
        "稼いだ15分枠top": [
            {
                "曜日": _DOW_LABELS[c["dow"]],
                "時刻": f"{c['hour']:02d}:{c['quarter'] * 15:02d}",
                "コイン": c["diamonds"],
            }
            for c in heatmap_top
        ],
        "稼いだ15分枠topのnote": (
            "この配信者の合計コインが多かった枠を並べたもの。1回の大口ギフトでも上位に来る"
            "ため、時間帯の傾向としては読めない。時間帯の傾向は"
            "cross_streamer_reference.時間帯index を見ること。"),
    }
    # 共演構成は配信の組み立て方そのもの(ソロで回すのか、コラボ・Battleに寄せるのか)を
    # 表すので、講評の材料に載せる。取れない配信者では入れ物ごと出さない。
    if coop and coop.get("active_seconds"):
        digest["共演構成"] = {
            "配信時間に占めるコラボ比率(%)": round(coop["collab_share"], 1),
            "配信時間に占めるBattle比率(%)": round(coop["battle_share"], 1),
            "ソロ比率(%)": round(coop["solo_share"], 1),
            "Battle回数/時": round(coop["battles_per_hour"], 2),
            "コラボ回数/時": round(coop["collabs_per_hour"], 2),
            "平均コラボ長(分)": round(coop["avg_collab_seconds"] / 60, 1),
            "コラボした配信数": coop["sessions_with_collab"],
            "集計対象の配信数": coop["sessions"],
            "note": ("コラボはBattle以外のLinkMic。BattleもLinkMic上で起きるため、"
                     "重なった時間はBattle側にだけ数えている。"),
        }
    return digest


def review_input(profile: dict, *, time_index: Optional[dict] = None,
                 retention: Optional[dict] = None,
                 entry_source: Optional[dict] = None,
                 battle_flow: Optional[dict] = None,
                 coverage: Optional[dict] = None) -> dict:
    """講評modelへ渡す入力dict。

    解析側の引数はいずれもanalytics reducerの戻り値をそのまま受ける。取得できなかった
    ものはNoneのまま渡してよい(その項目は入れ物ごと出さない)。空dictや0で埋めない。
    """
    reference: dict = {}
    if time_index is not None:
        reference["時間帯index"] = _time_index_digest(time_index)
    if retention is not None:
        reference["入室と定着"] = _retention_digest(retention)
    if entry_source is not None:
        reference["流入元"] = _entry_source_digest(entry_source)
    if battle_flow is not None:
        reference["Battle展開"] = _battle_flow_digest(battle_flow)
    if coverage is not None:
        reference["収集カバレッジ"] = _coverage_digest(coverage)
    payload = {"streamer": streamer_digest(profile)}
    if reference:
        payload["cross_streamer_reference"] = reference
        payload["統計の読み方"] = {
            "min_observations": get_ai_review_min_observations(),
            "significant": ("true=標本数が足りかつCIがreferenceを跨がない、"
                            "false=標本不足、null=判定材料なし"),
            "母集団": ("cross_streamer_referenceは監視対象の配信者全体の集計であり、"
                     "この配信者だけの実績ではない。"),
        }
    return payload
