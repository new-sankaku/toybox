"""Battle形式(個人戦/チーム戦)、スコアバーのsegment単位(陣営)、勝敗の判定。

collector(収集時)・video_overlay(焼き込み)・battle_migration(既存data再判定)・
analytics(全体解析)・履歴画面が同じruleを使うための単一の定義。Web(static/common.jsの
battleTopology/battleTeams/battleBarUnits)と同じ分割になるよう対応させてある。
"""
import statistics
from typing import Optional

from tictok.core.config import get_battle_gift_window_fallback_seconds

# 保存済みbattleがどのruleで判定されたかのversion。ruleを変えたら+1すると、起動時の
# battle_migrationが既存recordを再判定する。collectorは新規保存時にこの値を打つ。
BATTLE_TOPOLOGY_VERSION = 2

# 保存済みglove_eventがどの判定方式で決まったかのversion。方式を変えたら+1すると、起動時の
# glove_migrationが既存eventを再判定する。collectorは新規保存時にこの値を打つ。collectorと
# glove_migrationが同じ値を見るよう、定数はここ1箇所にだけ置く(両側に直書きすると片側だけ
# 上がって再判定が黙って空振りする)。
# 4: 時間軸を受信側時計からserver時計(create_time)へ統一。
GLOVE_EVENT_VERSION = 4

# PK確定scoreを拾う猶予(秒)。end_timeちょうどで切ってはいけない。
#
# end_timeはTikTokのbattle settingが持つserver時刻(end_time_ms)、score_seriesのtは
# 受信側の local 時刻で、両者は同じ時計ではない。さらに最終scoreを載せたarmies更新は
# PK終了の合図と前後して届く。実data 444戦の「最後にscoreが動いたsample」の分布は
#   end_timeの3秒前〜end_time: 325戦 / end_timeの0〜3秒後: 31戦
#   3〜30秒後: 1戦 / 30秒超後: 23戦 / 3秒より前: 64戦
# で、確定burstはend_timeの±3秒に集中し、30秒超後の変化はPK後のroster解体
# (相手hostが枠から抜けてmax(opp_scores)が残りメンバーへ落ちる)である。
# 猶予1〜10秒のどれでも判定結果は同一(plateau)、15秒では解体を巻き込み始めるため3.0とした。
#
# これはuserが調整する運用値ではなく「勝敗の定義」そのものなので設定には出さない
# (SETTING_DEFSへ出すと勝敗の定義自体を画面から書き換えられることになる)。
# analytics側の_BF_*定数・BATTLE_TOPOLOGY_VERSIONと同じ、rule moduleが持つ定数として置く。
BATTLE_SETTLE_GRACE_SECONDS = 3.0

# resolve_result()のbasis: 確定時点のscoreで判定した / TikTokから届いた値をそのまま使った。
BATTLE_RESULT_SETTLED = "settled"
BATTLE_RESULT_REPORTED = "reported"


def battle_type(participants) -> str:
    """participantsから個人戦("personal")/チーム戦("team")を判定する。

    **team構造の有無では判定できない**: TikTokは個人マルチ(1:1:1)も「1人陣営×N」の
    team構造(team_armies)で送るため、team_armiesの有無で決めると1:1:1がチーム戦になり、
    label・順位内訳・スコアバーの分割が全て崩れる。

    実際の見分けはteam_idの中身に出る:
      個人マルチ: 各hostのteam_idに**その host 自身のuser_id**が入る(=自分だけの陣営)。
      実チーム戦: 陣営placeholder("1"/"2"等)が入り、memberのuser_idとは一致しない。
    実data 272件で完全に分離することを確認済み(個人マルチ195 / 実チーム戦77)。

    team_idを持つ参加者が居ない(flat armies=team構造の無い1v1)か、team_idを持つ参加者が
    **全員** team_id == 自身のuser_id なら個人戦。陣営placeholderが1つでも有ればチーム戦。

    陣営の人数ではなくteam_idの中身で決めるのは、rosterが埋まる途中で判定が反転しない
    ため(人数ruleでは2v2の1人目が届いた時点で個人戦に見え、その間のscore_seriesが別
    semanticsで混ざる)。
    """
    tagged = [p for p in participants if p.get("team_id") is not None]
    if not tagged:
        return "personal"
    if all(str(p["team_id"]) == str(p.get("user_id") or "") for p in tagged):
        return "personal"
    return "team"


def battle_sides(participants) -> list:
    """スコアバーのsegment単位(陣営)を左→右の固定順で返す。Web(common.jsの
    battleBarUnits/battleTeams)と同じ分割: チーム戦はteam_idごと、個人戦は参加者ごと。

    自陣を先頭、敵陣は代表(最高score member)の降順で安定配置する。戻り値は
    [(member_ids, is_own), ...] で、member_idsはその陣営に属する参加者のuser_id。
    陣営数<=2なら自陣/敵陣の2極、3以上ならN分割(個人マルチ)になる。
    """
    is_team = battle_type(participants) == "team"
    groups: dict = {}
    for p in participants:
        pid = str(p.get("user_id") or "")
        if not pid:
            continue
        own = bool(p.get("is_own")) or p.get("side") == "own"
        if is_team:
            # team_idが唯一の陣営grouping key。欠落(旧parser由来のlegacy data)時のみsideへ。
            tid = p.get("team_id")
            key = f"t{tid}" if tid is not None else ("own" if own else "opp")
        else:
            key = pid
        g = groups.setdefault(key, {"ids": [], "own": False, "best": 0})
        g["ids"].append(pid)
        g["own"] = g["own"] or own
        g["best"] = max(g["best"], p.get("score") or 0)
    ordered = sorted(groups.values(), key=lambda g: (not g["own"], -g["best"]))
    return [(tuple(g["ids"]), g["own"]) for g in ordered]


def result_from_scores(own: int, opp: int) -> str:
    """2極scoreから勝敗label。oppは常に「最も強い敵陣営のscore」(合計ではない)。"""
    return "win" if own > opp else "lose" if own < opp else "draw"


def settled_scores(battle: dict) -> Optional[tuple]:
    """PK確定時点の (自陣score, 敵陣score, その時刻) を返す。確定できなければNone。

    score_seriesはPK終了後も記録が続き、
      - 相手hostが枠から抜けるとopp(=max(opp_scores))が残りメンバーへ落ちる
      - 全員抜ければ own/opp とも0になる
    ため、系列の最終値は勝負の結果ではない。逆にend_timeちょうどで切ると、確定scoreを
    載せた最後のarmies更新が数百ms遅れて届いた戦(実data 444戦中31戦)を取りこぼす。
    そこで end_time + BATTLE_SETTLE_GRACE_SECONDS 以前の最後のsampleを確定値とする。
    """
    end_time = battle.get("end_time")
    if end_time is None:
        return None
    cutoff = end_time + BATTLE_SETTLE_GRACE_SECONDS
    for sample in reversed(battle.get("score_series") or []):
        t = sample.get("t")
        if t is None or t > cutoff:
            continue
        return sample.get("own") or 0, sample.get("opp") or 0, t
    return None


def resolve_result(battle: dict) -> dict:
    """勝敗の単一judge。履歴画面・解析・焼き込みはすべてこれを通す。

    battles表の result は「最後に届いたarmies更新の時点」の値で、PK後のroster解体まで
    含んでしまう(実data 444戦中4戦が勝敗まで反転し、うち2戦は0対0のdrawに潰れていた)。
    保存値を書き換えると TikTok から届いた元dataが失われるため、DBはそのままに読み出し側で
    確定時点の判定へ揃える。

    戻り値:
      result   確定時点で判定した勝敗。確定できないときはbattles表の値をそのまま返す。
      basis    settled(確定時点で判定) / reported(保存値のまま)。
      reason   basisがreportedのときの理由。ongoing / no_series / aborted。
      own,opp  確定時点の2極score(basisがreportedならNone)。
      at       確定値を採ったsampleの時刻(同上)。
      reported battles表のresult(元data)。
    """
    reported = battle.get("result")
    base = {"result": reported, "basis": BATTLE_RESULT_REPORTED, "reason": None,
            "own": None, "opp": None, "at": None, "reported": reported}
    if battle.get("aborted"):
        # 成立しなかったPK。勝負が無いので判定し直す対象ではない。
        return {**base, "reason": "aborted"}
    settled = settled_scores(battle)
    if settled is None:
        return {**base, "reason": "ongoing" if battle.get("end_time") is None else "no_series"}
    own, opp, at = settled
    return {"result": result_from_scores(own, opp), "basis": BATTLE_RESULT_SETTLED,
            "reason": None, "own": own, "opp": opp, "at": at, "reported": reported}


def annotate_result(battle: dict) -> dict:
    """読み出したbattle dictへ確定判定を反映する(破壊的、同じdictを返す)。

    result と2極score(own_score/opp_score)を確定時点の値へ置き換え、元dataは
    *_reported に残す。resultだけ差し替えるとscoreと矛盾した表示(loseなのに自陣が
    大差でリードして見える)になるため、両方まとめて確定時点へ揃える。

    DBへ書き戻す経路(collector._battle_public → storage.save_battles)ではこれを
    呼ばないこと: 保存dataは TikTok から届いたままにしておき、判定は読み出しのたびに行う。

    2度目以降は何もしない。読み出し経路が入れ子になった場合(collector snapshot →
    server)に、確定値で *_reported を上書きして元dataを失わないため。
    """
    if "result_reported" in battle:
        return battle
    resolved = resolve_result(battle)
    battle["result_reported"] = resolved["reported"]
    battle["own_score_reported"] = battle.get("own_score")
    battle["opp_score_reported"] = battle.get("opp_score")
    battle["result_basis"] = resolved["basis"]
    battle["result_reason"] = resolved["reason"]
    battle["result"] = resolved["result"]
    if resolved["basis"] == BATTLE_RESULT_SETTLED:
        battle["own_score"] = resolved["own"]
        battle["opp_score"] = resolved["opp"]
    return battle


def gift_window_fallback_duration(battles: list) -> float:
    """同一sessionのBattle群から、窓を閉じるためのfallback長を実観測で決める。
    明示durationとstart/end差の中央値を使い、1件も観測できない場合のみ既定値。"""
    observed = [b["duration"] for b in battles if b.get("duration")]
    observed += [
        b["end_time"] - b["start_time"]
        for b in battles
        if b.get("end_time") is not None
        and b.get("start_time") is not None
        and b["end_time"] > b["start_time"]
    ]
    if observed:
        return statistics.median(observed)
    return float(get_battle_gift_window_fallback_seconds())


def gift_window_end(battle: dict, starts: list, fallback_duration: float) -> Optional[float]:
    """Battleの貢献集計に使うgift窓の終端。startsは同一sessionの全Battle開始時刻(昇順)。

    end_time_msを欠くBattleを無制限の窓にしない: Battle後〜配信終了までの通常Giftが
    貢献に合算され、連続PKでは同じGiftが複数Battleへ二重帰属するため。所定durationで
    閉じ、それも無い終了済みBattleは次Battleの開始で、さらに無ければfallback長で打ち切る。
    進行中Battleは意図的に開いたまま(live giftを集計)Noneを返す。"""
    start = battle.get("start_time")
    end = battle.get("end_time")
    if end is not None or start is None:
        return end
    if battle.get("duration"):
        return start + battle["duration"]
    if battle.get("ongoing"):
        return None
    return next((s for s in starts if s > start), None) or start + fallback_duration
