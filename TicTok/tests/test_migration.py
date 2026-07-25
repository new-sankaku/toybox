import gzip
import json
import sqlite3

import pytest

from tictok import battle_migration, glove_migration
from tictok.core.battle import BATTLE_TOPOLOGY_VERSION

GV = glove_migration.GLOVE_EVENT_VERSION


@pytest.fixture
def conn(env_guard):
    from tictok.storage import SCHEMA

    c = sqlite3.connect(str(env_guard / "migration.db"))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.executescript(SCHEMA)
    c.execute(
        "INSERT INTO sessions (id, unique_id, status, started_at, bucket_seconds)"
        " VALUES (1, 'tester', 'ended', 0, 60)"
    )
    c.commit()
    try:
        yield c
    finally:
        c.close()


def _put_battle(conn, battle, session_id=1):
    conn.execute(
        "INSERT INTO battles (session_id, battle_id, data_json) VALUES (?, ?, ?)",
        (session_id, battle.get("battle_id", 0), json.dumps(battle, ensure_ascii=False)),
    )
    conn.commit()


def _stored_battles(conn):
    return [
        json.loads(r["data_json"])
        for r in conn.execute("SELECT data_json FROM battles ORDER BY rowid")
    ]


def _put_gift(conn, at, diamonds, session_id=1):
    conn.execute(
        "INSERT INTO events (session_id, time, create_time, kind, diamonds)"
        " VALUES (?, ?, ?, 'gift', ?)",
        (session_id, at, at, diamonds),
    )
    conn.commit()


def _series_to_jumps_input(points):
    return list(points)


def _window(start=100, end=200, multiple=5, own=True):
    return {"start": start, "end": end, "multiple": multiple, "own": own}


def _write_dump(log_dir, unique_id, session_id, records, rotated_stamp=None):
    log_dir.mkdir(parents=True, exist_ok=True)
    base = f"battle_raw_{unique_id}_{session_id}"
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    if rotated_stamp:
        path = log_dir / f"{base}-{rotated_stamp}.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(body)
    else:
        path = log_dir / f"{base}.jsonl"
        path.write_text(body, encoding="utf-8")
    return path


# 生dumpの時刻は epoch秒 (server時計)。再判定はこの軸だけを使い、record自身の "ts"
# (受信側の time.time()) は使わないので、fixtureは両者を意図的にずらしてある。
EPOCH = 1_700_000_000


def _armies_rec(ts, own_hid, score, battle_id=7, **payload_extra):
    """ts は battle内の相対秒。dumpには server時計(createTime, ms)として EPOCH+ts を、
    受信側時計 "ts" にはズレた値を書く。"""
    payload = {
        "battleId": battle_id,
        "armies": {own_hid: {"hostScore": score}},
        "baseMessage": {"createTime": (EPOCH + ts) * 1000},
    }
    payload.update(payload_extra)
    return {"ts": EPOCH + ts + _RECEIVER_SKEW, "kind": "LinkMicArmies", "payload": payload}


# 受信側時計のskew(秒)。突合窓(BEFORE 2.0 / AFTER 8.0)を確実に外れる大きさにしてある。
_RECEIVER_SKEW = 45.0


# --------------------------------------------------------------------------
# glove_migration: pure helpers
# --------------------------------------------------------------------------


def test_own_host_id_matches_only_own_side_with_same_handle():
    battle = {
        "participants": [
            {"side": "opp", "unique_id": "tester", "user_id": "999"},
            {"side": "own", "unique_id": "other", "user_id": "111"},
            {"side": "own", "unique_id": "tester", "user_id": 222},
        ]
    }
    assert glove_migration._own_host_id(battle, "tester") == "222"
    assert glove_migration._own_host_id(battle, "nobody") is None
    assert glove_migration._own_host_id({}, "tester") is None


def test_own_host_id_treats_missing_user_id_as_missing():
    """user_id欠落を文字列'None'にしない。呼び出し側のguardが弾けなくなるため。"""
    battle = {"participants": [{"side": "own", "unique_id": "tester"}]}
    assert glove_migration._own_host_id(battle, "tester") is None
    both = {"participants": [
        {"side": "own", "unique_id": "tester"},
        {"side": "own", "unique_id": "tester", "user_id": "h1"},
    ]}
    assert glove_migration._own_host_id(both, "tester") == "h1"


def test_field_prefers_camel_and_falls_back_to_snake():
    assert glove_migration._field({"hostScore": 1, "host_score": 2}, "hostScore", "host_score") == 1
    assert glove_migration._field({"host_score": 2}, "hostScore", "host_score") == 2
    assert glove_migration._field({}, "hostScore", "host_score") is None
    # 明示的なNullは「存在するがNone」として返す(snakeへ落ちない)。
    assert glove_migration._field({"hostScore": None}, "hostScore", "host_score") is None


def test_dump_paths_returns_rotated_first_then_base(tmp_path):
    log_dir = tmp_path / "logs"
    _write_dump(log_dir, "tester", 1, [], rotated_stamp="20260102")
    _write_dump(log_dir, "tester", 1, [], rotated_stamp="20260101")
    _write_dump(log_dir, "tester", 1, [])
    # 別sessionのdumpは混ざらない。
    _write_dump(log_dir, "tester", 2, [])
    paths = glove_migration._dump_paths(log_dir, "tester", 1)
    assert [p.name for p in paths] == [
        "battle_raw_tester_1-20260101.jsonl.gz",
        "battle_raw_tester_1-20260102.jsonl.gz",
        "battle_raw_tester_1.jsonl",
    ]


def test_dump_paths_missing_dir_and_missing_base(tmp_path):
    assert glove_migration._dump_paths(tmp_path / "nope", "tester", 1) == []
    log_dir = tmp_path / "logs"
    _write_dump(log_dir, "tester", 1, [], rotated_stamp="20260101")
    assert [p.suffix for p in glove_migration._dump_paths(log_dir, "tester", 1)] == [".gz"]


def test_iter_armies_reads_gzip_and_plain_and_skips_foreign_records(tmp_path):
    log_dir = tmp_path / "logs"
    _write_dump(
        log_dir, "tester", 1,
        [_armies_rec(1, "h1", 10)],
        rotated_stamp="20260101",
    )
    log_dir_base = log_dir / f"battle_raw_tester_1.jsonl"
    log_dir_base.write_text(
        "\n".join([
            "not json at all",
            json.dumps({"ts": 2, "kind": "Gift", "payload": {"battleId": 7}}),
            json.dumps(_armies_rec(3, "h1", 20, battle_id=8)),
            json.dumps({"ts": 4, "kind": "LinkMicArmies", "payload": {"battleId": "x"}}),
            json.dumps(_armies_rec(5, "h1", 30)),
            json.dumps({"ts": 6, "kind": "LinkMicArmies",
                        "payload": {"battle_id": 7, "armies": {"h1": {"host_score": 40}}}}),
        ]) + "\n",
        encoding="utf-8",
    )
    got = [(rec["ts"], glove_migration._own_score(payload, "h1"))
           for rec, payload in glove_migration._iter_armies(log_dir, "tester", 1, 7)]
    assert got == [(EPOCH + 1 + _RECEIVER_SKEW, 10),
                   (EPOCH + 5 + _RECEIVER_SKEW, 30), (6, 40)]


def test_own_score_prefers_team_users_entry_over_armies():
    payload = {
        "armies": {"h1": {"hostScore": 10}, "h2": {"hostScore": 99}},
        "teamArmies": [{"teamUsers": [{"userIdStr": "h1", "score": 55},
                                      {"userIdStr": "h2", "score": 77}]}],
    }
    assert glove_migration._own_score(payload, "h1") == 55
    assert glove_migration._own_score({"armies": {"h2": {"hostScore": 5}}}, "h1") is None


def test_load_battle_signals_keeps_prev_at_running_max(tmp_path):
    log_dir = tmp_path / "logs"
    _write_dump(log_dir, "tester", 1, [
        _armies_rec(10, "h1", 100),
        _armies_rec(11, "h1", 50),
        _armies_rec(12, "h1", 120, giftId=900, giftSentTime=(EPOCH + 12) * 1000),
    ])
    series, attrs = glove_migration._load_battle_signals(log_dir, "tester", 1, 7, "h1")
    assert series == [(EPOCH + 10, 100), (EPOCH + 11, 50), (EPOCH + 12, 120)]
    # scoreの下落でprevを下げない: deltaは 120-100 であって 120-50 ではない。
    assert len(attrs) == 1
    assert attrs[0]["delta"] == 20
    assert attrs[0]["gid"] == 900
    assert attrs[0]["t"] == float(EPOCH + 12)
    assert attrs[0]["flag"] is False


def test_load_battle_signals_without_own_host_is_empty(tmp_path):
    log_dir = tmp_path / "logs"
    _write_dump(log_dir, "tester", 1, [_armies_rec(10, "h1", 100)])
    assert glove_migration._load_battle_signals(log_dir, "tester", 1, 7, None) == ([], [])


def test_multiplier_at_windows():
    missions = [{"reward_start_ts": 100, "reward_duration": 10,
                 "multiplier": 3, "achieved": True}]
    assert glove_migration._multiplier_at(missions, 99) == 1
    assert glove_migration._multiplier_at(missions, 100) == 3
    assert glove_migration._multiplier_at(missions, 110) == 3
    assert glove_migration._multiplier_at(missions, 110.1) == 1
    assert glove_migration._multiplier_at(None, 100) == 1
    unachieved = [{"reward_start_ts": 100, "reward_duration": 10,
                   "multiplier": 3, "achieved": False}]
    assert glove_migration._multiplier_at(unachieved, 105) is None
    unknown = [{"reward_start_ts": 100, "reward_duration": 10,
                "multiplier": 0, "achieved": True}]
    assert glove_migration._multiplier_at(unknown, 105) is None


# --------------------------------------------------------------------------
# glove_migration: _resolve_by_attr
# --------------------------------------------------------------------------


def _attr(gid=900, t=150.0, delta=500, flag=False):
    return {"gid": gid, "t": t, "delta": delta, "flag": flag, "used": False}


def test_resolve_by_attr_flag_wins_even_without_known_multiplier():
    entries = [_attr(flag=True)]
    ev = {"gift_id": 900, "t": 150.0}
    assert glove_migration._resolve_by_attr(entries, ev, 100, 5, None) == (True, 5, 500, "flag")
    assert entries[0]["used"] is True


def test_resolve_by_attr_uses_ratio_when_multipliers_differ():
    ev = {"gift_id": 900, "t": 150.0}
    assert glove_migration._resolve_by_attr([_attr(delta=500)], ev, 100, 5, 1) \
        == (True, 5, 500, "attr")
    assert glove_migration._resolve_by_attr([_attr(delta=100)], ev, 100, 5, 1) \
        == (False, 1, 100, "attr")
    # 5でも1でもない倍率は推測しない。
    assert glove_migration._resolve_by_attr([_attr(delta=300)], ev, 100, 5, 1) is None


def test_resolve_by_attr_skips_when_normal_and_crit_are_indistinguishable():
    ev = {"gift_id": 900, "t": 150.0}
    assert glove_migration._resolve_by_attr([_attr()], ev, 100, 5, 5) is None
    assert glove_migration._resolve_by_attr([_attr()], ev, 100, 5, None) is None


def test_resolve_by_attr_requires_gift_id_and_time_window():
    ev = {"gift_id": 900, "t": 150.0}
    assert glove_migration._resolve_by_attr([_attr(gid=901)], ev, 100, 5, 1) is None
    assert glove_migration._resolve_by_attr([_attr(t=153.0)], ev, 100, 5, 1) is not None
    assert glove_migration._resolve_by_attr([_attr(t=153.01)], ev, 100, 5, 1) is None


def test_resolve_by_attr_does_not_reuse_a_consumed_entry():
    entries = [_attr(delta=500)]
    ev = {"gift_id": 900, "t": 150.0}
    assert glove_migration._resolve_by_attr(entries, ev, 100, 5, 1) is not None
    assert glove_migration._resolve_by_attr(entries, ev, 100, 5, 1) is None


# --------------------------------------------------------------------------
# glove_migration: _migrate_battle (厳密一致v2)
# --------------------------------------------------------------------------


def _glove_battle(events, windows=None, missions=None):
    return {
        "glove_windows": windows if windows is not None else [_window()],
        "glove_events": events,
        "bonus_missions": missions,
    }


def test_migrate_battle_delta_match_normal_and_crit(conn):
    battle = _glove_battle([{"t": 150, "total": 100}])
    series = [(149, 0), (150, 100)]
    stats = glove_migration._migrate_battle(conn, battle, 1, series, [])
    ev = battle["glove_events"][0]
    assert (ev["crit"], ev["mult"], ev["score_delta"], ev["method"]) == (False, 1, 100, "delta")
    assert ev["v"] == GV
    assert stats == {"crit": 0, "normal": 1, "undecided": 0, "kept": 0}

    battle = _glove_battle([{"t": 150, "total": 100}])
    stats = glove_migration._migrate_battle(conn, battle, 1, [(149, 0), (150, 500)], [])
    ev = battle["glove_events"][0]
    assert (ev["crit"], ev["mult"], ev["score_delta"], ev["method"]) == (True, 5, 500, "delta")
    assert stats["crit"] == 1


def test_migrate_battle_ambiguous_delta_stays_undecided(conn):
    battle = _glove_battle([{"t": 150, "total": 100}])
    # 通常額(100)とcrit額(500)の両方が窓内に居る → 一意に決まらないので判定しない。
    series = [(149, 0), (150, 100), (151, 600)]
    stats = glove_migration._migrate_battle(conn, battle, 1, series, [])
    ev = battle["glove_events"][0]
    assert "crit" not in ev
    assert ev["v"] == GV
    assert stats["undecided"] == 1


def test_migrate_battle_never_demotes_existing_verdict(conn):
    battle = _glove_battle([{"t": 150, "total": 100, "crit": True, "mult": 5}])
    stats = glove_migration._migrate_battle(conn, battle, 1, [], [])
    ev = battle["glove_events"][0]
    assert ev["crit"] is True and ev["mult"] == 5
    assert ev["v"] == GV
    assert stats == {"crit": 0, "normal": 0, "undecided": 0, "kept": 1}


def test_migrate_battle_jump_time_window_bounds(conn):
    def run(jump_t):
        battle = _glove_battle([{"t": 100, "total": 10}])
        glove_migration._migrate_battle(conn, battle, 1, [(0, 0), (jump_t, 10)], [])
        return battle["glove_events"][0].get("crit", "undecided")

    assert run(98.0) is False
    assert run(97.9) == "undecided"
    assert run(108.0) is False
    assert run(108.1) == "undecided"


def test_migrate_battle_consumes_jump_so_two_gifts_do_not_share_it(conn):
    battle = _glove_battle([{"t": 100, "total": 10}, {"t": 101, "total": 10}])
    stats = glove_migration._migrate_battle(conn, battle, 1, [(0, 0), (100, 10)], [])
    first, second = battle["glove_events"]
    assert first["crit"] is False
    assert "crit" not in second
    assert stats == {"crit": 0, "normal": 1, "undecided": 1, "kept": 0}


def test_migrate_battle_skips_when_normal_equals_crit_amount(conn):
    missions = [{"reward_start_ts": 100, "reward_duration": 100,
                 "multiplier": 5, "achieved": True}]
    battle = _glove_battle([{"t": 150, "total": 100}], missions=missions)
    stats = glove_migration._migrate_battle(conn, battle, 1, [(149, 0), (150, 500)], [])
    assert "crit" not in battle["glove_events"][0]
    assert stats["undecided"] == 1


def test_migrate_battle_unknown_multiplier_blocks_delta_match(conn):
    missions = [{"reward_start_ts": 100, "reward_duration": 100,
                 "multiplier": 2, "achieved": False}]
    battle = _glove_battle([{"t": 150, "total": 100}], missions=missions)
    stats = glove_migration._migrate_battle(conn, battle, 1, [(149, 0), (150, 500)], [])
    assert "crit" not in battle["glove_events"][0]
    assert stats["undecided"] == 1


def test_migrate_battle_uses_mission_multiplier_for_normal_amount(conn):
    missions = [{"reward_start_ts": 100, "reward_duration": 100,
                 "multiplier": 2, "achieved": True}]
    battle = _glove_battle([{"t": 150, "total": 100}], missions=missions)
    glove_migration._migrate_battle(conn, battle, 1, [(149, 0), (150, 200)], [])
    ev = battle["glove_events"][0]
    assert (ev["crit"], ev["mult"], ev["score_delta"]) == (False, 2, 200)


def test_migrate_battle_zero_total_is_never_judged(conn):
    battle = _glove_battle([{"t": 150, "total": 0}])
    stats = glove_migration._migrate_battle(conn, battle, 1, [(149, 0), (150, 500)], [])
    assert "crit" not in battle["glove_events"][0]
    assert stats["undecided"] == 1


def test_migrate_battle_leaves_current_version_events_untouched(conn):
    battle = _glove_battle([{"t": 150, "total": 100, "v": GV, "crit": False}])
    stats = glove_migration._migrate_battle(conn, battle, 1, [(149, 0), (150, 500)], [])
    assert battle["glove_events"][0]["crit"] is False
    assert stats == {"crit": 0, "normal": 0, "undecided": 0, "kept": 0}


def test_migrate_battle_window_multiple_selected_by_event_time(conn):
    windows = [_window(100, 200, multiple=5), _window(300, 400, multiple=10)]
    battle = _glove_battle([{"t": 350, "total": 100}], windows=windows)
    glove_migration._migrate_battle(conn, battle, 1, [(349, 0), (350, 1000)], [])
    ev = battle["glove_events"][0]
    assert (ev["crit"], ev["mult"], ev["score_delta"]) == (True, 10, 1000)


def test_migrate_battle_ignores_opponent_windows_and_uses_default_multiple(conn):
    """敵陣窓は自陣の倍率ではない。窓が引けないeventは既定倍率5で判定される。"""
    _put_gift(conn, at=148, diamonds=100)
    battle = _glove_battle([{"t": 150, "total": 100}], windows=[_window(own=False)])
    stats = glove_migration._migrate_battle(conn, battle, 1, [(149, 0), (150, 500)], [])
    ev = battle["glove_events"][0]
    assert (ev["crit"], ev["mult"], ev["score_delta"]) == (True, 5, 500)
    assert stats["crit"] == 1


def test_migrate_battle_attr_beats_delta(conn):
    battle = _glove_battle([{"t": 150, "total": 100, "gift_id": 900}])
    attrs = [_attr(gid=900, t=150.0, delta=500, flag=True)]
    glove_migration._migrate_battle(conn, battle, 1, [(149, 0), (150, 100)], attrs)
    ev = battle["glove_events"][0]
    assert (ev["crit"], ev["method"], ev["score_delta"]) == (True, "flag", 500)


def test_migrate_battle_attr_verdict_consumes_its_jump(conn):
    """attr/flagで決めたeventも自分のjumpを消費する。残すと同じ+500を後続の別giftが
    crit額の一意一致として再利用でき、偽critが増える(delta経路と同じ原則)。"""
    battle = _glove_battle([{"t": 150, "total": 100, "gift_id": 900},
                            {"t": 151, "total": 100, "gift_id": 901}])
    attrs = [_attr(gid=900, t=150.0, delta=500, flag=True)]
    stats = glove_migration._migrate_battle(conn, battle, 1, [(149, 0), (150, 500)], attrs)
    first, second = battle["glove_events"]
    assert (first["method"], first["crit"]) == ("flag", True)
    assert "crit" not in second
    assert stats == {"crit": 1, "normal": 0, "undecided": 1, "kept": 0}


def test_migrate_battle_jumps_follow_running_max_so_attr_consume_hits_its_own_jump(conn):
    """scoreが一度下がる場面でも、jumpはattr deltaと同じrunning-max定義で作る。

    隣接差分でjumpを作ると、下落を挟んだjump本体(+70)がattrのdelta(+20)と食い違い、
    consumeが完全一致に失敗して部分減算に落ちる。すると残った+50を後続giftが
    「crit額の一意一致」として拾い、消したはずの偽critが別の形で復活する。"""
    battle = _glove_battle([{"t": 150, "total": 100, "gift_id": 900},
                            {"t": 151, "total": 10, "gift_id": 901}])
    attrs = [_attr(gid=900, t=150.0, delta=20, flag=True)]
    series = [(149, 100), (150, 50), (150.5, 120)]
    stats = glove_migration._migrate_battle(conn, battle, 1, series, attrs)
    first, second = battle["glove_events"]
    assert (first["method"], first["crit"], first["score_delta"]) == ("flag", True, 20)
    # 後続giftは根拠が無いので判定不能のまま。偽crit(+50 == 10*5)を作らない。
    assert "crit" not in second
    assert stats == {"crit": 1, "normal": 0, "undecided": 1, "kept": 0}


def test_running_max_jumps_ignores_score_dips():
    assert glove_migration._running_max_jumps(
        [(149, 100), (150, 50), (150.5, 120)]
    ) == [[150.5, 20]]
    assert glove_migration._running_max_jumps([(1, 0), (2, 10), (3, 30)]) == [[2, 10], [3, 20]]
    assert glove_migration._running_max_jumps([]) == []


def test_glove_event_version_is_shared_by_collector_and_migration():
    """判定版数は core.battle の1箇所だけに置く。collectorとmigrationが別々のliteralを
    持つと、片側だけ上げたときに再判定が黙って空振りする(migrationは全eventをskip)。"""
    from tictok.collect import collector
    from tictok.core import battle as core_battle

    assert glove_migration.GLOVE_EVENT_VERSION is core_battle.GLOVE_EVENT_VERSION
    assert collector.GLOVE_EVENT_VERSION is core_battle.GLOVE_EVENT_VERSION


def test_load_battle_signals_uses_the_server_clock_not_the_receiver_clock(tmp_path):
    """seriesの時刻は payloadのcreateTime(server時計)。record自身の "ts" は受信側の
    time.time()で、突合相手(glove_eventのt)と軸が違う。"""
    log_dir = tmp_path / "logs"
    _write_dump(log_dir, "tester", 1, [_armies_rec(10, "h1", 100)])
    series, _ = glove_migration._load_battle_signals(log_dir, "tester", 1, 7, "h1")
    assert series == [(EPOCH + 10, 100)]


def test_load_battle_signals_skips_records_without_a_server_create_time(tmp_path):
    """server時計が無いrecordは軸に載せられないので捨てる(受信側時計へは落とさない)。"""
    log_dir = tmp_path / "logs"
    rec = _armies_rec(10, "h1", 100)
    rec["payload"].pop("baseMessage")
    _write_dump(log_dir, "tester", 1, [rec, _armies_rec(11, "h1", 200)])
    series, _ = glove_migration._load_battle_signals(log_dir, "tester", 1, 7, "h1")
    assert series == [(EPOCH + 11, 200)]


def test_migrate_battle_attr_consume_leaves_other_jumps_intact(conn):
    """消費するのは名指しされたdelta1本だけ。別jumpを持つ後続critを巻き添えにしない。"""
    battle = _glove_battle([{"t": 150, "total": 100, "gift_id": 900},
                            {"t": 151, "total": 100, "gift_id": 901}])
    attrs = [_attr(gid=900, t=150.0, delta=500, flag=True)]
    stats = glove_migration._migrate_battle(
        conn, battle, 1, [(149, 0), (150, 500), (151, 1000)], attrs
    )
    first, second = battle["glove_events"]
    assert (first["method"], first["crit"], first["score_delta"]) == ("flag", True, 500)
    assert (second["method"], second["crit"], second["score_delta"]) == ("delta", True, 500)
    assert stats["crit"] == 2


def test_migrate_battle_preconsumes_outside_window_gift_exactly(conn):
    """窓外giftの通常寄与がcrit額と偶然一致するときの偽critを、先消費が防ぐ。"""
    _put_gift(conn, at=148, diamonds=50)
    battle = _glove_battle([{"t": 150, "total": 10}], windows=[_window(149, 250, 5)])
    series = [(140, 0), (148, 50), (151, 60)]
    stats = glove_migration._migrate_battle(conn, battle, 1, series, [])
    ev = battle["glove_events"][0]
    assert (ev["crit"], ev["score_delta"], ev["mult"]) == (False, 10, 1)
    assert stats["normal"] == 1


def test_migrate_battle_preconsume_falls_back_to_partial_subtraction(conn):
    _put_gift(conn, at=149, diamonds=30)
    battle = _glove_battle([{"t": 151, "total": 20}], windows=[_window(150, 250, 5)])
    # 窓外gift(30)と窓内gift(20)が1本のjump(50)へ合流している。
    stats = glove_migration._migrate_battle(conn, battle, 1, [(140, 0), (150, 50)], [])
    ev = battle["glove_events"][0]
    assert (ev["crit"], ev["score_delta"]) == (False, 20)
    assert stats["normal"] == 1


def test_migrate_battle_does_not_preconsume_gifts_inside_the_window(conn):
    _put_gift(conn, at=150, diamonds=50)
    battle = _glove_battle([{"t": 150, "total": 10}], windows=[_window(149, 250, 5)])
    stats = glove_migration._migrate_battle(conn, battle, 1, [(140, 0), (150, 50)], [])
    # 窓内giftは消費されないので、50 は crit額(10x5)として一意に一致する。
    assert battle["glove_events"][0]["crit"] is True
    assert stats["crit"] == 1


# --------------------------------------------------------------------------
# glove_migration: migrate_glove_events (end to end / 冪等)
# --------------------------------------------------------------------------


def _e2e_battle():
    return {
        "battle_id": 7,
        "participants": [
            {"side": "own", "unique_id": "tester", "user_id": "h1"},
            {"side": "opp", "unique_id": "rival", "user_id": "h2"},
        ],
        "glove_windows": [_window(EPOCH + 100, EPOCH + 200, 5)],
        "glove_events": [{"t": EPOCH + 150, "total": 100}],
    }


def test_migrate_glove_events_end_to_end_and_invalidates_cache(conn, tmp_path):
    log_dir = tmp_path / "logs"
    _write_dump(log_dir, "tester", 1, [
        _armies_rec(148, "h1", 0),
        _armies_rec(151, "h1", 500),
    ])
    _put_battle(conn, _e2e_battle())
    conn.executemany(
        "INSERT INTO analytics_session_cache (session_id, kind, version, payload_json,"
        " computed_at) VALUES (?, ?, 1, '{}', 0)",
        [(1, "glove"), (1, "gift")],
    )
    conn.commit()

    totals = glove_migration.migrate_glove_events(conn, log_dir)
    conn.commit()

    assert totals == {"battles": 1, "crit": 1, "normal": 0, "undecided": 0, "kept": 0}
    ev = _stored_battles(conn)[0]["glove_events"][0]
    assert (ev["crit"], ev["mult"], ev["score_delta"], ev["method"], ev["v"]) \
        == (True, 5, 500, "delta", GV)
    kinds = {r["kind"] for r in conn.execute("SELECT kind FROM analytics_session_cache")}
    assert kinds == {"gift"}


def test_migrate_glove_events_is_idempotent(conn, tmp_path):
    log_dir = tmp_path / "logs"
    _write_dump(log_dir, "tester", 1, [
        _armies_rec(148, "h1", 0),
        _armies_rec(151, "h1", 500),
    ])
    _put_battle(conn, _e2e_battle())
    glove_migration.migrate_glove_events(conn, log_dir)
    conn.commit()
    first = _stored_battles(conn)

    second_totals = glove_migration.migrate_glove_events(conn, log_dir)
    conn.commit()
    assert second_totals == {"battles": 0, "crit": 0, "normal": 0, "undecided": 0, "kept": 0}
    assert _stored_battles(conn) == first


def test_migrate_glove_events_without_dump_keeps_live_verdicts(conn, tmp_path):
    battle = _e2e_battle()
    battle["glove_events"] = [{"t": 150, "total": 100, "crit": True, "mult": 5,
                               "score_delta": 500, "method": "flag"}]
    _put_battle(conn, battle)
    totals = glove_migration.migrate_glove_events(conn, tmp_path / "no_logs")
    conn.commit()
    assert totals["kept"] == 1
    ev = _stored_battles(conn)[0]["glove_events"][0]
    assert (ev["crit"], ev["method"], ev["v"]) == (True, "flag", GV)


def test_migrate_glove_events_skips_rows_without_glove_events(conn, tmp_path):
    _put_battle(conn, {"battle_id": 1, "glove_events": []})
    _put_battle(conn, {"battle_id": 2, "participants": []})
    totals = glove_migration.migrate_glove_events(conn, tmp_path / "logs")
    assert totals["battles"] == 0
    assert _stored_battles(conn) == [{"battle_id": 1, "glove_events": []},
                                     {"battle_id": 2, "participants": []}]


def test_migrate_glove_events_ignores_unparsable_row(conn, tmp_path):
    conn.execute(
        "INSERT INTO battles (session_id, battle_id, data_json)"
        " VALUES (1, 7, '{\"glove_events\": [{broken')"
    )
    conn.commit()
    totals = glove_migration.migrate_glove_events(conn, tmp_path / "logs")
    assert totals["battles"] == 0
    row = conn.execute("SELECT data_json d FROM battles").fetchone()
    assert row["d"] == '{"glove_events": [{broken'


# --------------------------------------------------------------------------
# battle_migration
# --------------------------------------------------------------------------


def _multi_parts():
    return [
        {"user_id": "1", "team_id": "1", "side": "own", "is_own": True, "score": 300},
        {"user_id": "2", "team_id": "2", "side": "opp", "score": 200},
        {"user_id": "3", "team_id": "3", "side": "opp", "score": 150},
    ]


def _team_parts():
    return [
        {"user_id": "1", "team_id": "10", "side": "own", "is_own": True, "score": 300},
        {"user_id": "2", "team_id": "10", "side": "own", "is_own": True, "score": 50},
        {"user_id": "3", "team_id": "20", "side": "opp", "score": 200},
        {"user_id": "4", "team_id": "20", "side": "opp", "score": 150},
    ]


def test_side_totals_sums_members_and_keeps_opponents_separate():
    sides = [(("1",), True), (("2", "3"), False), (("4",), False)]
    scores = {"1": 300, "2": 200, "3": 10, "4": 150}
    assert battle_migration._side_totals(sides, scores) == (300, [210, 150])


def test_multi_host_battle_is_retyped_and_rescored_to_strongest_opponent():
    battle = {"type": "team", "own_score": 300, "opp_score": 350, "result": "lose",
              "participants": _multi_parts()}
    changed = battle_migration._migrate_battle(battle)
    assert battle["type"] == "personal"
    assert battle["opp_score"] == 200
    assert battle["result"] == "win"
    assert battle["topo_v"] == BATTLE_TOPOLOGY_VERSION
    assert changed == {"retyped": 1, "rescored": 1, "reresulted": 1}


def test_two_sided_team_battle_keeps_its_scores():
    battle = {"type": "team", "own_score": 350, "opp_score": 350, "result": "draw",
              "participants": _team_parts()}
    changed = battle_migration._migrate_battle(battle)
    assert battle["type"] == "team"
    assert (battle["opp_score"], battle["result"]) == (350, "draw")
    assert battle["topo_v"] == BATTLE_TOPOLOGY_VERSION
    assert changed == {"retyped": 0, "rescored": 0, "reresulted": 0}


def test_flat_one_vs_one_is_personal_and_untouched():
    battle = {"type": "personal", "own_score": 10, "opp_score": 20, "result": "lose",
              "participants": [
                  {"user_id": "1", "side": "own", "is_own": True, "score": 10},
                  {"user_id": "2", "side": "opp", "score": 20},
              ]}
    changed = battle_migration._migrate_battle(battle)
    assert battle["type"] == "personal"
    assert (battle["opp_score"], battle["result"]) == (20, "lose")
    assert changed == {"retyped": 0, "rescored": 0, "reresulted": 0}


def test_empty_participants_only_gets_stamped():
    battle = {"type": "team", "opp_score": 5, "participants": []}
    changed = battle_migration._migrate_battle(battle)
    assert battle["type"] == "personal"
    assert battle["opp_score"] == 5
    assert battle["topo_v"] == BATTLE_TOPOLOGY_VERSION
    assert changed["retyped"] == 1


def test_score_series_opponent_restored_only_where_parts_exist():
    battle = {"type": "team", "own_score": 300, "opp_score": 350, "result": "lose",
              "participants": _multi_parts(),
              "score_series": [
                  {"t": 1, "own": 100, "opp": 260},
                  {"t": 2, "own": 300, "opp": 350,
                   "parts": [{"id": "1", "score": 300}, {"id": "2", "score": 200},
                             {"id": "3", "score": 150}]},
              ]}
    battle_migration._migrate_battle(battle)
    assert battle["score_series"][0]["opp"] == 260
    assert battle["score_series"][1]["opp"] == 200


def test_migrate_battle_topology_end_to_end_and_idempotent(conn):
    _put_battle(conn, {"battle_id": 1, "type": "team", "own_score": 300,
                       "opp_score": 350, "result": "lose", "participants": _multi_parts()})
    _put_battle(conn, {"battle_id": 2, "type": "team", "own_score": 350,
                       "opp_score": 350, "result": "draw", "participants": _team_parts()})

    totals = battle_migration.migrate_battle_topology(conn)
    conn.commit()
    assert totals == {"battles": 2, "retyped": 1, "rescored": 1, "reresulted": 1}
    first = _stored_battles(conn)
    assert [b["type"] for b in first] == ["personal", "team"]

    again = battle_migration.migrate_battle_topology(conn)
    conn.commit()
    assert again == {"battles": 0, "retyped": 0, "rescored": 0, "reresulted": 0}
    assert _stored_battles(conn) == first


def test_migrate_battle_topology_skips_already_stamped_rows(conn):
    stale = {"battle_id": 1, "type": "team", "own_score": 300, "opp_score": 350,
             "result": "lose", "participants": _multi_parts(),
             "topo_v": BATTLE_TOPOLOGY_VERSION}
    _put_battle(conn, stale)
    assert battle_migration.migrate_battle_topology(conn)["battles"] == 0
    assert _stored_battles(conn)[0]["type"] == "team"


def test_migrate_battle_topology_leaves_unparsable_row_alone(conn):
    conn.execute("INSERT INTO battles (session_id, battle_id, data_json) VALUES (1, 9, 'oops')")
    _put_battle(conn, {"battle_id": 1, "participants": _multi_parts(),
                       "own_score": 300, "opp_score": 350, "result": "lose"})
    totals = battle_migration.migrate_battle_topology(conn)
    conn.commit()
    assert totals["battles"] == 1
    rows = [r["d"] for r in conn.execute("SELECT data_json d FROM battles ORDER BY rowid")]
    assert rows[0] == "oops"
    assert json.loads(rows[1])["opp_score"] == 200
