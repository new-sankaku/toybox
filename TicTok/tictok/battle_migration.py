"""既存battleの形式(個人戦/チーム戦)と2極スコアを現行ruleで再判定する起動時migration。

旧collectorはteam構造(team_armies)の有無だけでtypeを付けていたため、TikTokが「1人陣営×N」の
team構造で送る**個人マルチ(1:1:1)が全てチーム戦**になっていた。その結果:
  - スコアバーが自陣/敵陣合計の2極に潰れる(焼き込み・Web)。
  - opp_scoreが「敵全員の合計」(type=="team"のsum分岐)になり、resultがほぼ必ずloseになる。
現行ruleはcore.battleがparticipantsのteam_idから形式を導出する(battle_type)。

再計算は3陣営以上(=個人マルチ)のbattleに限る。2陣営(1v1/実チーム戦NvM)ではmax==sumで
旧値と同値のため触らない。3陣営以上では各陣営=1hostなので、陣営scoreはparticipantsの
host別scoreからopp_score/resultを推測なしで正確に復元できる。score_seriesのoppはsampleが
parts(host別score)を持つ時だけ同様に復元し、partsが無い古いsample(parts導入前のsession)は
復元不能なのでそのまま残す。

処理後は topo_v=2 が付くため冪等で、2度目以降の起動は即no-opになる。
"""
import json

from tictok.core.battle import (
    BATTLE_TOPOLOGY_VERSION,
    battle_sides,
    battle_type,
    result_from_scores,
)


def _side_totals(sides: list, score_by_id: dict) -> tuple:
    """(自陣total, [敵陣totals])。陣営totalは所属memberのscore合計。"""
    own_total = 0
    opp_totals = []
    for ids, is_own in sides:
        total = sum(score_by_id.get(pid, 0) for pid in ids)
        if is_own:
            own_total = max(own_total, total)
        else:
            opp_totals.append(total)
    return own_total, opp_totals


def _migrate_battle(battle: dict) -> dict:
    """1battleを現行ruleへ再判定する。破壊的にbattleを書き換え、変更点を返す。"""
    parts = battle.get("participants") or []
    old_type = battle.get("type")
    new_type = battle_type(parts)
    battle["type"] = new_type
    battle["topo_v"] = BATTLE_TOPOLOGY_VERSION
    changed = {"retyped": int(old_type != new_type), "rescored": 0, "reresulted": 0}

    sides = battle_sides(parts)
    if len(sides) < 3:
        # 2陣営以下は opp=max==sum で旧値と同値。触らない(実チーム戦のteam_total_score
        # 由来のscoreをmember合計で上書きしてしまわないため)。
        return changed

    score_by_id = {str(p.get("user_id") or ""): (p.get("score") or 0) for p in parts}
    _, opp_totals = _side_totals(sides, score_by_id)
    if opp_totals:
        new_opp = max(opp_totals)
        if battle.get("opp_score") != new_opp:
            battle["opp_score"] = new_opp
            changed["rescored"] = 1
        # ここで書き戻すのは「TikTokから届いた最後のarmies更新」の2極値であって、PK確定時点の
        # 勝敗ではない。確定時点の判定は読み出し側(core.battle.annotate_result)が行う。
        new_result = result_from_scores(battle.get("own_score") or 0, new_opp)
        if battle.get("result") != new_result:
            battle["result"] = new_result
            changed["reresulted"] = 1

    for sample in battle.get("score_series") or []:
        # parts(host別score)を持たない古いsampleは陣営別内訳を復元できない。旧collectorの
        # 2極値をそのまま残す。ここで0埋めして書き換えると、復元ではなく破壊になる。
        if not sample.get("parts"):
            continue
        by_id = {str(pt.get("id") or ""): (pt.get("score") or 0) for pt in sample["parts"]}
        _, sample_opps = _side_totals(sides, by_id)
        if sample_opps:
            sample["opp"] = max(sample_opps)
    return changed


def migrate_battle_topology(conn) -> dict:
    """未再判定のbattleを現行ruleで再判定してbattles表へ書き戻す。commitは呼び出し側。
    battle形式/opp_score/resultはanalytics cacheのどのkindも読まない(cacheはstart_time/
    end_time/battle_id/glove_eventsのみ参照)ため、cache無効化は不要。"""
    rows = conn.execute(
        "SELECT rowid AS rid, data_json AS d FROM battles"
        f" WHERE data_json NOT LIKE '%\"topo_v\": {BATTLE_TOPOLOGY_VERSION}%'"
    ).fetchall()
    totals = {"battles": 0, "retyped": 0, "rescored": 0, "reresulted": 0}
    for row in rows:
        try:
            battle = json.loads(row["d"])
        except (ValueError, TypeError):
            continue
        changed = _migrate_battle(battle)
        conn.execute(
            "UPDATE battles SET data_json = ? WHERE rowid = ?",
            (json.dumps(battle, ensure_ascii=False), row["rid"]),
        )
        totals["battles"] += 1
        for key in ("retyped", "rescored", "reresulted"):
            totals[key] += changed[key]
    return totals
