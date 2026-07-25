"""グローブcrit判定の旧版eventを現行方式へ再判定する起動時migration。

対象は glove_events の v が現行版未満のeventを含むbattle。生dump
(logs/battle_raw_<unique_id>_<session_id>.jsonl)から自hostスコアのdelta系列と、
armiesがgiftを名指しした同定情報を再構成して再判定する。判定式は collector と同じで、
証拠は強い順に flag(TikTokがcritを明示) > attr(gift同定) > delta(額の厳密一致)。
一意に決まらないものは判定不能のまま推測しない。

再判定で決まらなかったeventは既存の判定結果を維持する(判定不能へ降格させない)。
生dumpは設定依存かつ回転するため、失われたbattleを再判定すると収集時にlive判定できて
いた結果を恒久的に捨てることになるため。処理後は全eventに現行版のvが付くので冪等。
"""
import gzip
import json
import logging
from pathlib import Path

from tictok.core import config
from tictok.core.battle import GLOVE_EVENT_VERSION
from tictok.core.logging_setup import progress_interval_seconds
from tictok.core.progress import IntervalGate

logger = logging.getLogger("tictok.glove_migration")

_MATCH_BEFORE_SEC = 2.0
_MATCH_AFTER_SEC = 8.0
_ATTR_MATCH_SEC = 3.0
_EPOCH_SECONDS_MIN = 1_000_000_000
_EPOCH_SECONDS_MAX = 100_000_000_000
_DEFAULT_MULTIPLE = 5
_METHOD_FLAG = "flag"
_METHOD_ATTR = "attr"
_METHOD_DELTA = "delta"


def _own_host_id(battle: dict, unique_id: str):
    for p in battle.get("participants") or []:
        if p.get("side") == "own" and p.get("unique_id") == unique_id:
            user_id = p.get("user_id")
            if user_id is None:
                continue
            return str(user_id)
    return None


def _field(obj: dict, camel: str, snake: str):
    """生dumpのfield名は途中でcamelCaseからsnake_caseへ変わっている(betterproto側の
    to_dict仕様変更)。どちらのdumpも読めないと、その期間のbattleはscore系列が空になり
    全eventが判定不能で恒久確定してしまうため、両表記を引く。"""
    if camel in obj:
        return obj[camel]
    return obj.get(snake)


def _dump_paths(log_dir: Path, unique_id: str, session_id: int) -> list:
    """そのsessionの生dumpを古い順に返す。圧縮設定がONだとcloseの度に
    <base>-<stamp>.jsonl.gz へ改名されるため、base fileだけを見ると回転済みの記録が
    まるごと読めず、再判定が黙って空振りする。"""
    base_name = f"battle_raw_{unique_id}_{session_id}"
    if not log_dir.is_dir():
        return []
    rotated = sorted(
        p for p in log_dir.iterdir()
        if p.name.startswith(f"{base_name}-") and p.name.endswith(".jsonl.gz")
    )
    base = log_dir / f"{base_name}.jsonl"
    return rotated + ([base] if base.is_file() else [])


def _iter_armies(log_dir: Path, unique_id: str, session_id: int, battle_id: int):
    """そのbattleのLinkMicArmies recordを記録順に流す。"""
    for path in _dump_paths(log_dir, unique_id, session_id):
        opener = gzip.open if path.suffix == ".gz" else open
        try:
            with opener(path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if rec.get("kind") != "LinkMicArmies":
                        continue
                    payload = rec.get("payload") or {}
                    try:
                        if int(_field(payload, "battleId", "battle_id") or 0) != battle_id:
                            continue
                    except (TypeError, ValueError):
                        continue
                    yield rec, payload
        except OSError:
            # 読めないdumpがあっても再判定自体は続ける(既存判定は降格させないので安全)。
            logger.warning("failed to read the battle raw capture %s", path, exc_info=True)


def _armies_create_time(payload: dict):
    """armies recordのserver時刻(CommonMessageData.create_time)を秒で返す。無ければNone。

    再判定の突合相手(glove_eventのt・events.create_time・glove窓のeffect_time_sec)は全て
    TikTok server時計なので、series側も同じ軸に載せる。生dumpの rec['ts'] は受信側の
    time.time()で、数秒のskewだけで正しいjumpが突合窓から外れるため使わない。"""
    base = _field(payload, "baseMessage", "base_message") or {}
    raw = _field(base, "createTime", "create_time")
    try:
        value = int(raw or 0)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    if value > _EPOCH_SECONDS_MAX:
        value = value / 1000.0
    if value < _EPOCH_SECONDS_MIN:
        return None
    return float(value)


def _own_score(payload: dict, own_hid: str):
    own = None
    for hid, army in (payload.get("armies") or {}).items():
        if hid != own_hid:
            continue
        host_score = _field(army, "hostScore", "host_score")
        if host_score is not None:
            own = int(host_score)
    for ta in _field(payload, "teamArmies", "team_armies") or []:
        for tu in _field(ta, "teamUsers", "team_users") or []:
            if _field(tu, "userIdStr", "user_id_str") == own_hid \
                    and tu.get("score") is not None:
                own = int(tu["score"])
    return own


def _load_battle_signals(log_dir: Path, unique_id: str, session_id: int,
                         battle_id: int, own_hid: str):
    """生dumpから再判定の材料を1passで取り出す。
    series: 自host個人scoreの(server時刻, score)系列。額の厳密一致に使う。
    attrs : armiesが名指ししたgift(gift_id + gift_sent_time)へ同定できたscore delta。
            collector側の _glove_record_attr と同じ証拠を後から再構成したもの。

    server時刻(create_time)を持たないrecordは軸に載せられないので丸ごと飛ばす。受信側時計
    へ落とすFallbackはしない。全recordが欠落しているdumpでは signals が空になり、その
    battleの全eventは既存判定を維持したまま(kept)になる。"""
    series: list = []
    attrs: list = []
    if not own_hid:
        return series, attrs
    prev = None
    for rec, payload in _iter_armies(log_dir, unique_id, session_id, battle_id):
        own = _own_score(payload, own_hid)
        if own is None:
            continue
        ts = _armies_create_time(payload)
        if ts is None:
            continue
        series.append((ts, own))
        if prev is not None and own > prev:
            gift_id = _field(payload, "giftId", "gift_id")
            sent_ms = _field(payload, "giftSentTime", "gift_sent_time")
            if gift_id and sent_ms:
                try:
                    attrs.append({
                        "gid": int(gift_id),
                        "t": float(sent_ms) / 1000.0,
                        "delta": own - prev,
                        "flag": bool(_field(payload, "triggerCriticalStrike",
                                            "trigger_critical_strike")),
                        "used": False,
                    })
                except (TypeError, ValueError):
                    pass
        if prev is None or own > prev:
            prev = own
    return series, attrs


def _resolve_by_attr(entries: list, ev: dict, total: int, multiple: int, m):
    """名指し同定されたdeltaでcritを決める。決まらなければNone。"""
    for entry in entries:
        if entry["used"] or entry["gid"] != ev.get("gift_id"):
            continue
        if abs(entry["t"] - (ev.get("t") or 0)) > _ATTR_MATCH_SEC:
            continue
        if entry["flag"]:
            entry["used"] = True
            return True, multiple, entry["delta"], _METHOD_FLAG
        # 倍率タイムが不明、または窓倍率と同値のときは実効倍率が通常とcritで同じ値になり
        # 判別材料にならない。額一致側の want_normal == want_crit と同じ除外。
        if m is None or m == multiple:
            continue
        ratio = entry["delta"] / total
        hit = int(round(ratio)) if abs(ratio - round(ratio)) < 0.01 else None
        if hit == multiple:
            crit = True
        elif hit == m:
            crit = False
        else:
            continue
        entry["used"] = True
        return crit, (multiple if crit else m), entry["delta"], _METHOD_ATTR
    return None


def _multiplier_at(missions, t):
    """時刻tの倍率タイム倍率。倍率タイム外=1、reward期間中だが倍率不明/未達成=None。"""
    for mission in missions or []:
        start = mission.get("reward_start_ts") or 0
        duration = mission.get("reward_duration") or 0
        if start and start <= t <= start + duration:
            multiplier = int(mission.get("multiplier") or 0)
            return multiplier if multiplier > 0 and mission.get("achieved") else None
    return 1


def _running_max_jumps(series: list) -> list:
    """scoreの増分[t, delta]列。基準prevはrunning-maxで進める(scoreが一時的に下がっても
    下げない)。_load_battle_signalsのattr delta、およびcollectorの _glove_deltas と同じ
    定義にするための単一の導出。隣接差分にすると、score下落を挟んだときにattrのdeltaと
    jump本体が食い違い、attr判定のconsumeが無関係なjumpを部分減算して偽critを生む。"""
    jumps: list = []
    prev = None
    for t, score in series:
        if prev is not None and score > prev:
            jumps.append([t, score - prev])
        if prev is None or score > prev:
            prev = score
    return jumps


def _migrate_battle(conn, battle: dict, session_id: int, series: list,
                    attrs: list) -> dict:
    windows = [w for w in (battle.get("glove_windows") or []) if w.get("own")]
    events = sorted(battle.get("glove_events") or [], key=lambda e: e.get("t") or 0)
    jumps = _running_max_jumps(series)
    missions = battle.get("bonus_missions")
    stats = {"crit": 0, "normal": 0, "undecided": 0, "kept": 0}

    def consume(t, amount):
        for j in jumps:
            if t - _MATCH_BEFORE_SEC <= j[0] <= t + _MATCH_AFTER_SEC and j[1] == amount:
                j[1] = 0
                return True
        for j in jumps:
            if t - _MATCH_BEFORE_SEC <= j[0] <= t + _MATCH_AFTER_SEC and j[1] > amount:
                j[1] -= amount
                return True
        return False

    if events and windows and jumps:
        # 窓外giftの通常寄与(m×額)を先に消費し、窓中giftとの偶然一致(偽crit)を防ぐ。
        t_lo = min(w["start"] for w in windows) - 120
        t_hi = max(w["end"] for w in windows) + 120
        for g in conn.execute(
            "SELECT create_time t, diamonds total FROM events"
            " WHERE session_id = ? AND kind = 'gift' AND create_time BETWEEN ? AND ?"
            " ORDER BY create_time",
            (session_id, t_lo, t_hi),
        ):
            gt = g["t"]
            if any(w["start"] <= gt <= w["end"] for w in windows):
                continue
            m = _multiplier_at(missions, gt)
            if m is not None:
                consume(gt, (g["total"] or 0) * m)

    for ev in events:
        if (ev.get("v") or 0) >= GLOVE_EVENT_VERSION:
            continue
        t, total = ev.get("t") or 0, ev.get("total") or 0
        multiple = _DEFAULT_MULTIPLE
        for w in windows:
            if w["start"] <= t <= w["end"]:
                multiple = w.get("multiple") or _DEFAULT_MULTIPLE
        m = _multiplier_at(missions, t)
        verdict = None
        if total > 0:
            verdict = _resolve_by_attr(attrs, ev, total, multiple, m)
            if verdict is not None:
                consume(t, verdict[2])
        if verdict is None and total > 0 and m is not None:
            want_normal, want_crit = total * m, total * multiple
            if want_normal != want_crit:
                candidates = [
                    j for j in jumps
                    if t - _MATCH_BEFORE_SEC <= j[0] <= t + _MATCH_AFTER_SEC and j[1] > 0
                ]
                hit_normal = any(j[1] == want_normal for j in candidates)
                hit_crit = any(j[1] == want_crit for j in candidates)
                if hit_normal != hit_crit:
                    delta = want_crit if hit_crit else want_normal
                    consume(t, delta)
                    verdict = (hit_crit, multiple if hit_crit else m, delta, _METHOD_DELTA)
        # 判定不能へは決して降格させない。生dumpが失われたbattleでは再判定できないため、
        # ここで上書きすると収集時にlive判定できていた結果を恒久的に捨てることになる。
        if verdict is None:
            ev["v"] = GLOVE_EVENT_VERSION
            stats["kept" if ev.get("crit") is not None else "undecided"] += 1
            continue
        crit, mult, delta, method = verdict
        ev["crit"] = crit
        ev["mult"] = mult
        ev["score_delta"] = delta
        ev["method"] = method
        ev["v"] = GLOVE_EVENT_VERSION
        stats["crit" if crit else "normal"] += 1
    return stats


def migrate_glove_events(conn, log_dir) -> dict:
    """旧方式のglove_eventsを新方式で再判定してbattles表へ書き戻す。commitは呼び出し側。
    書き換えたsessionのglove analytics cacheは無効化する。"""
    log_dir = Path(log_dir)
    rows = conn.execute(
        "SELECT b.rowid rid, b.battle_id bid, b.session_id sid, b.data_json d,"
        " s.unique_id uid FROM battles b JOIN sessions s ON s.id = b.session_id"
        " WHERE b.data_json LIKE '%\"glove_events\": [{%'"
    ).fetchall()
    totals = {"battles": 0, "crit": 0, "normal": 0, "undecided": 0, "kept": 0}
    touched_sessions = set()
    # この再判定は Storage.__init__ の中、つまりserverが待ち受けを始める**前**に走る。
    # battle毎に生dump(.jsonl.gz)を全行解凍してparseするため、対象が多いと数分かかる。
    # 進捗を出さないと、userには「serverが起動しない」としか見えない(HTTPも上がって
    # いないので画面から確かめる手段が無く、logだけが唯一の手がかりになる)。
    if rows:
        logger.info(
            "glove migration: re-judging %d battle(s) from the raw captures; "
            "the server starts once this finishes", len(rows),
            extra={"event": "glove_migration.started", "ctx": {"candidates": len(rows)}},
        )
    gate = IntervalGate(progress_interval_seconds(config.get_log_progress_interval_seconds()))
    for index, row in enumerate(rows):
        if gate.ready():
            logger.info(
                "glove migration: %d/%d battle(s) scanned (%d rewritten)",
                index, len(rows), totals["battles"],
                extra={"event": "glove_migration.progress",
                       "ctx": {"scanned": index, "candidates": len(rows),
                               "rewritten": totals["battles"]}},
            )
        try:
            battle = json.loads(row["d"])
        except (ValueError, TypeError):
            continue
        events = battle.get("glove_events") or []
        if not events or all((e.get("v") or 0) >= GLOVE_EVENT_VERSION for e in events):
            continue
        own_hid = _own_host_id(battle, row["uid"])
        series, attrs = _load_battle_signals(
            log_dir, row["uid"], row["sid"], int(row["bid"]), own_hid
        )
        stats = _migrate_battle(conn, battle, row["sid"], series, attrs)
        conn.execute(
            "UPDATE battles SET data_json = ? WHERE rowid = ?",
            (json.dumps(battle, ensure_ascii=False), row["rid"]),
        )
        totals["battles"] += 1
        for key in ("crit", "normal", "undecided", "kept"):
            totals[key] += stats[key]
        touched_sessions.add(row["sid"])
    if touched_sessions:
        conn.executemany(
            "DELETE FROM analytics_session_cache WHERE kind = 'glove' AND session_id = ?",
            [(sid,) for sid in touched_sessions],
        )
    return totals
