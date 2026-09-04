"""退避の暦による層化・行数の急減による凍結・接続のDROP防御。

この3つは「誤ったDELETE/DROPから戻せること」を1つの目的で支えている。**外部processからの
DELETE/DROPは防げない**ので、testが確かめるのは防止ではなく「事故のあとで戻せる状態が
残るか」である —— 事故の前の姿が刈り取られないこと(凍結)、日数ぶんの姿が確かに在ること
(暦の層化)、そしてserver自身の接続が表を落とさないこと(authorizer)。
"""
import os
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pytest

from tests.test_server import client, server  # noqa: F401  (fixtureとして使う)
from tictok.core import dbmaint


# ---- 道具 ----------------------------------------------------------------------------


def _noon(day_offset: int, minute: int = 0) -> float:
    """day_offset日前の12:00(+minute分)のepoch秒。

    正午を基準にするのは、testを走らせた時刻に結果が依存しないようにするため。日付の境目を
    跨ぐ時刻を使うと、深夜に走らせた回だけ層の割り当てが変わる。"""
    day = date.today() - timedelta(days=day_offset)
    return datetime(day.year, day.month, day.day, 12, minute).timestamp()


def _touch_backup(when: float, reason: str = dbmaint.REASON_SCHEDULED, seq: int = 1,
                  mtime: Optional[float] = None):
    """list_backupsが拾える名前の退避fileを1つ置く。中身は見られないので1byteでよい。

    ``mtime`` を別に渡せるのは、file名の時刻とmtimeが食い違う状況(別driveへcopyし直した
    退避)を作るため。既定では一致させる。"""
    directory = dbmaint.backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime(dbmaint._STAMP_FORMAT, time.localtime(when))
    suffix = "" if seq == 1 else f"-{seq}"
    path = directory / f"tictok-{reason}-{stamp}{suffix}.db"
    path.write_bytes(b"x")
    stamped = when if mtime is None else mtime
    os.utime(path, (stamped, stamped))
    return path


def _freeze_stamp(monkeypatch, text: str):
    """退避file名の秒だけを固定する。他のformat(logの時刻)には触らない。"""
    real = time.strftime

    def _fake(fmt, *args):
        return text if fmt == dbmaint._STAMP_FORMAT else real(fmt, *args)

    monkeypatch.setattr(dbmaint.time, "strftime", _fake)


def _snapshot_events(path) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    finally:
        conn.close()


def _make_db(path, events: int, sessions: int = 3, **tables: int):
    """見張り対象の表だけを持つ小さなDB。count_guarded_rowsは無い表を飛ばす。

    ``settings=3`` のようにkeywordで表と行数を足せる(小さい手入力データの検証用)。"""
    wanted = {"sessions": sessions, "events": events, **tables}
    conn = sqlite3.connect(str(path))
    try:
        for table, rows in wanted.items():
            conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (id INTEGER PRIMARY KEY)")
            conn.execute(f"DELETE FROM {table}")
            conn.executemany(f"INSERT INTO {table} (id) VALUES (?)",
                             [(i,) for i in range(1, rows + 1)])
        conn.commit()
    finally:
        conn.close()
    return path


# ---- 世代の名前と並び順 ----------------------------------------------------------------


def test_same_second_generations_keep_the_newest_content(env_guard, tmp_path, monkeypatch):
    """同一秒に keep より多く作っても、直後に読める最新世代は最新の内容である。

    連番の若い名前は刈り取りで**後から空く**。空きを埋める実装だと、いま書いた内容が最古の
    名前を名乗り、直後の刈り取りがそれを消す —— 退避は成功しているのに、戻そうとすると古い
    内容しか出てこない。"""
    _freeze_stamp(monkeypatch, "20260902-120000")
    db = tmp_path / "gen.db"
    written = []
    for rows in (10, 20, 30, 40, 50):
        _make_db(db, events=rows)
        written.append((rows, dbmaint.create_backup(db, reason=dbmaint.REASON_MANUAL, keep=3)))

    listed = dbmaint.list_backups(dbmaint.REASON_MANUAL)
    assert len(listed) == 3, [item["name"] for item in listed]
    # 最新の世代 = 最後に書いた内容。
    assert _snapshot_events(listed[0]["path"]) == 50
    assert [item["seq"] for item in listed] == [5, 4, 3]
    assert [_snapshot_events(item["path"]) for item in listed] == [50, 40, 30]
    # 5本目は自分自身を消していない。
    assert Path(written[-1][1]["path"]).is_file()
    # 空いた連番(1・2)へ戻らない。次は必ず6。
    _make_db(db, events=60)
    sixth = dbmaint.create_backup(db, reason=dbmaint.REASON_MANUAL, keep=3)
    assert sixth["name"].endswith("-6.db")
    assert _snapshot_events(dbmaint.list_backups(dbmaint.REASON_MANUAL)[0]["path"]) == 60


def test_listing_order_is_by_name_not_string_and_not_mtime(env_guard):
    """並べる鍵は時刻と連番を分けた数値。file名の文字列順でもmtime順でもない。"""
    first = _touch_backup(_noon(0), seq=1)
    second = _touch_backup(_noon(0), seq=2)
    # 連番なしの ``.db`` は ``-2.db`` より文字列としては後、mtimeは1本目を新しくしておく。
    os.utime(first, (_noon(0) + 3600, _noon(0) + 3600))

    listed = dbmaint.list_backups(dbmaint.REASON_SCHEDULED)

    assert [item["name"] for item in listed] == [second.name, first.name]
    assert [item["seq"] for item in listed] == [2, 1]


def test_calendar_layers_read_the_name_not_the_mtime(env_guard):
    """別driveへcopyし直してmtimeが今になっても、暦の層はfile名の時刻で決まる。"""
    now = time.time()
    old = _touch_backup(_noon(300), mtime=now)
    recent = _touch_backup(_noon(0), mtime=now)

    result = dbmaint.prune_scheduled_backups(now=_noon(0))

    assert result["removed"] == [old.name]
    assert recent.exists() and not old.exists()


def test_count_retention_reads_the_name_not_the_mtime(env_guard, monkeypatch):
    """回数の刈り取り(manual / premigration)も同じ。mtimeで並べると新しい方が消える。"""
    monkeypatch.setattr(dbmaint, "get_db_backup_keep", lambda: 1)
    now = time.time()
    old = _touch_backup(_noon(9), reason=dbmaint.REASON_MANUAL, mtime=now)
    newest = _touch_backup(_noon(1), reason=dbmaint.REASON_MANUAL, mtime=now - 86400)

    removed = dbmaint.prune_backups(dbmaint.REASON_MANUAL)

    assert removed == [old.name]
    assert newest.exists() and not old.exists()


def test_sequence_exhaustion_fails_instead_of_reusing(env_guard, tmp_path, monkeypatch):
    """同じ秒の連番を使い切ったら失敗にする。空きを拾いに戻らない。"""
    _freeze_stamp(monkeypatch, "20260902-120000")
    monkeypatch.setattr(dbmaint, "_MAX_SEQ", 2)
    db = _make_db(tmp_path / "gen.db", events=10)
    dbmaint.create_backup(db, reason=dbmaint.REASON_MANUAL, keep=0)
    dbmaint.create_backup(db, reason=dbmaint.REASON_MANUAL, keep=0)

    with pytest.raises(dbmaint.MaintenanceError):
        dbmaint.create_backup(db, reason=dbmaint.REASON_MANUAL, keep=0)


# ---- (a) 暦による層化 ------------------------------------------------------------------


def test_scheduled_prune_keeps_one_per_day_and_one_per_week(env_guard):
    """直近は1日1つ(その日の最初)、それより古い分は1週1つ、どちらでもない物は消える。"""
    kept_today = _touch_backup(_noon(0))
    newest = _touch_backup(_noon(0, 1))
    kept_1 = _touch_backup(_noon(1))
    drop_1 = _touch_backup(_noon(1, 1))
    kept_2 = _touch_backup(_noon(2))
    drop_2 = _touch_backup(_noon(2, 1))
    kept_20 = _touch_backup(_noon(20))
    drop_20 = _touch_backup(_noon(20, 1))
    kept_40 = _touch_backup(_noon(40))
    drop_200 = _touch_backup(_noon(200))

    result = dbmaint.prune_scheduled_backups(now=_noon(0))

    assert result["frozen"] is False
    assert sorted(result["removed"]) == sorted(
        p.name for p in (drop_1, drop_2, drop_20, drop_200))
    for path in (kept_today, newest, kept_1, kept_2, kept_20, kept_40):
        assert path.exists(), path.name
    for path in (drop_1, drop_2, drop_20, drop_200):
        assert not path.exists(), path.name
    # 層の内訳も名乗る。日次は3日ぶん、週次は20日前と40日前の2週。
    assert [entry["name"] for entry in result["daily"]] == [
        kept_2.name, kept_1.name, kept_today.name]
    assert [entry["name"] for entry in result["weekly"]] == [
        kept_40.name, kept_20.name]


def test_scheduled_prune_never_drops_the_newest(env_guard, monkeypatch):
    """保持数をどう縮めても最新の1本は残る。今取ったsnapshotを同じ呼び出しで消さないため。"""
    monkeypatch.setattr(dbmaint, "get_db_backup_keep_daily", lambda: 1)
    monkeypatch.setattr(dbmaint, "get_db_backup_keep_weekly", lambda: 1)
    old = _touch_backup(_noon(30))
    newest = _touch_backup(_noon(0, 5))

    result = dbmaint.prune_scheduled_backups(now=_noon(0))

    assert old.name in result["removed"]
    assert newest.exists()


def test_scheduled_prune_disabled_when_both_layers_zero(env_guard, monkeypatch):
    """0は「無効」。両方0なら1つも消さない(この設定群の0の規約)。"""
    monkeypatch.setattr(dbmaint, "get_db_backup_keep_daily", lambda: 0)
    monkeypatch.setattr(dbmaint, "get_db_backup_keep_weekly", lambda: 0)
    old = _touch_backup(_noon(400))
    recent = _touch_backup(_noon(0))

    result = dbmaint.prune_scheduled_backups(now=_noon(0))

    assert result["removed"] == []
    assert old.exists() and recent.exists()


def test_scheduled_prune_ignores_other_reasons(env_guard):
    """理由の違う世代は暦の刈り取りの対象外。premigrationは回数の側が持つ。"""
    manual = _touch_backup(_noon(300), reason=dbmaint.REASON_MANUAL)
    premigration = _touch_backup(_noon(300), reason=dbmaint.REASON_PRE_MIGRATION)
    _touch_backup(_noon(0))

    dbmaint.prune_scheduled_backups(now=_noon(0))

    assert manual.exists() and premigration.exists()


# ---- (b) 行数の急減で凍結する ----------------------------------------------------------


def test_row_guard_records_baseline_without_tripping(env_guard, tmp_path):
    db = _make_db(tmp_path / "guard.db", events=1000)

    first = dbmaint.check_row_guard(db)

    assert first["tripped"] is False
    assert first["counts"]["events"] == 1000
    assert first["previous"] == {}
    assert dbmaint.is_frozen() is None
    assert dbmaint.ledger_path().is_file()


def test_row_guard_trips_and_freezes_prune(env_guard, tmp_path):
    """急減を検知したら凍結する。**処理は止めず**、古い世代を刈るのだけをやめる。"""
    db = _make_db(tmp_path / "guard.db", events=10000)
    dbmaint.check_row_guard(db)
    expired = _touch_backup(_noon(300))
    _touch_backup(_noon(0))

    _make_db(db, events=9000)  # 10%・1,000行減。割合2%と最小幅500行の両方を超える。
    verdict = dbmaint.check_row_guard(db)

    assert verdict["tripped"] is True
    assert verdict["drops"] == [
        {"table": "events", "before": 10000, "after": 9000, "lost": 1000,
         "ratio": 0.1, "why": dbmaint.GUARD_RATIO}]
    frozen = dbmaint.is_frozen()
    assert frozen is not None and "events" in frozen["reason"]

    result = dbmaint.prune_scheduled_backups(now=_noon(0))
    assert result["frozen"] is True
    assert result["removed"] == []
    assert expired.exists(), "凍結中は事故の前の姿を刈ってはならない"


def test_row_guard_ignores_small_drop_and_growth(env_guard, tmp_path):
    """減っても閾値以下なら検知しない。増加でも検知しない。"""
    db = _make_db(tmp_path / "guard.db", events=10000)
    dbmaint.check_row_guard(db)

    _make_db(db, events=9900)  # 1%。割合の閾値2%以下。
    assert dbmaint.check_row_guard(db)["tripped"] is False

    _make_db(db, events=50000)
    assert dbmaint.check_row_guard(db)["tripped"] is False
    assert dbmaint.is_frozen() is None


def test_row_guard_disabled_by_zero_thresholds(env_guard, tmp_path, monkeypatch):
    """割合も行数も0なら、0行化以外は検知しない。台帳の更新だけは続ける。"""
    monkeypatch.setattr(dbmaint, "get_db_guard_drop_ratio", lambda: 0.0)
    monkeypatch.setattr(dbmaint, "get_db_guard_drop_rows", lambda: 0)
    db = _make_db(tmp_path / "guard.db", events=10000)
    dbmaint.check_row_guard(db)

    _make_db(db, events=1)
    verdict = dbmaint.check_row_guard(db)

    assert verdict["tripped"] is False
    assert dbmaint.is_frozen() is None
    # 検知しない設定でも台帳は更新される(閾値を戻した日から比較が効くように)。
    assert verdict["counts"]["events"] == 1


def test_row_guard_keeps_first_detection_on_repeat(env_guard, tmp_path):
    """凍結中に更に減っても、凍結の記録は最初の検知のまま。事故の起点を上書きしない。"""
    db = _make_db(tmp_path / "guard.db", events=10000)
    dbmaint.check_row_guard(db)
    _make_db(db, events=5000)
    dbmaint.check_row_guard(db)
    first = dbmaint.is_frozen()

    _make_db(db, events=2000)
    dbmaint.check_row_guard(db)

    assert dbmaint.is_frozen() == first


# ---- (b-2) 3本の物差し: 0行化・絶対数・割合の最小幅 --------------------------------------


def test_emptied_table_always_trips(env_guard, tmp_path):
    """行が在った表が0行になったら、件数がいくら小さくても検知する。

    ``DROP TABLE`` して作り直しても ``DELETE FROM <表>`` でも最終形は同じ0行で、これが
    小さい手入力データ(settings / monitored_targets / clip_groups)を守る唯一の条件である。"""
    db = _make_db(tmp_path / "guard.db", events=10, settings=121)
    dbmaint.check_row_guard(db)

    _make_db(db, events=10, settings=0)
    verdict = dbmaint.check_row_guard(db)

    assert verdict["tripped"] is True
    assert [(d["table"], d["why"]) for d in verdict["drops"]] == [
        ("settings", dbmaint.GUARD_EMPTIED)]
    assert dbmaint.is_frozen() is not None


def test_emptied_trips_even_with_every_threshold_disabled(env_guard, tmp_path, monkeypatch):
    """0行化には閾値が無い。割合も行数も切ってあっても鳴る(独立した条件)。"""
    monkeypatch.setattr(dbmaint, "get_db_guard_drop_ratio", lambda: 0.0)
    monkeypatch.setattr(dbmaint, "get_db_guard_drop_rows", lambda: 0)
    db = _make_db(tmp_path / "guard.db", events=10, bookmarks=192)
    dbmaint.check_row_guard(db)

    _make_db(db, events=10, bookmarks=0)

    assert dbmaint.check_row_guard(db)["drops"] == [
        {"table": "bookmarks", "before": 192, "after": 0, "lost": 192,
         "ratio": 1.0, "why": dbmaint.GUARD_EMPTIED}]


def test_absolute_row_count_trips_below_the_ratio(env_guard, tmp_path, monkeypatch):
    """割合の下をくぐる大量削除を行数で捕まえる。

    割合の許容量はDBが育つほど増える(2%は154万行の今なら3万行、1,500万行なら30万行)ので、
    行数の側が天井を固定する。"""
    monkeypatch.setattr(dbmaint, "get_db_guard_drop_rows", lambda: 600)
    db = _make_db(tmp_path / "guard.db", events=100000)
    dbmaint.check_row_guard(db)

    _make_db(db, events=99300)  # 0.7%。割合2%には届かないが700行。
    verdict = dbmaint.check_row_guard(db)

    assert verdict["tripped"] is True
    assert verdict["drops"][0]["why"] == dbmaint.GUARD_ROWS
    assert verdict["drops"][0]["lost"] == 700


def test_ratio_needs_a_minimum_absolute_drop(env_guard, tmp_path):
    """割合は最小幅未満の減少には当てない。小さい表で通常運用のたびに鳴らないため。

    実測の通常運用(markers は1 sessionあたり最大351行)を下回る減少は、割合をいくら
    超えても事故と判定しない。"""
    db = _make_db(tmp_path / "guard.db", events=10, markers=11823)
    dbmaint.check_row_guard(db)

    _make_db(db, events=10, markers=11472)  # 3.0%。割合2%は超えるが351行。
    verdict = dbmaint.check_row_guard(db)

    assert verdict["tripped"] is False
    assert dbmaint.is_frozen() is None


def test_routine_operations_on_small_tables_do_not_trip(env_guard, tmp_path):
    """実測した通常操作では鳴らない。誤検知が日常になれば凍結は意味を失う。

    bookmarksの「表示中をすべて削除」(最大のグループで59行)、監視対象の1件解除、
    グループの1件削除、文字起こし修正の1件削除 —— どれも実DBで数えた実際の操作量。"""
    db = _make_db(tmp_path / "guard.db", events=10, bookmarks=192, monitored_targets=3,
                  clip_groups=19, transcript_corrections=1070, clip_presets=2)
    dbmaint.check_row_guard(db)

    _make_db(db, events=10, bookmarks=133, monitored_targets=2,
             clip_groups=18, transcript_corrections=1069, clip_presets=1)
    verdict = dbmaint.check_row_guard(db)

    assert verdict["drops"] == []
    assert dbmaint.is_frozen() is None


def test_human_tables_are_guarded(env_guard):
    """人がやり直すしか復旧手段が無い表を、件数が小さいことを理由に外していない。"""
    for table in ("settings", "monitored_targets", "bookmarks", "clip_groups",
                  "clip_presets", "transcript_corrections"):
        assert table in dbmaint.GUARDED_TABLES, table


def test_row_guard_skips_missing_tables(env_guard, tmp_path):
    """在る表だけを数える。数えられないことと0行を混同すると、schemaが増えた日に全件が
    急減に見える。"""
    db = _make_db(tmp_path / "guard.db", events=10)

    counts = dbmaint.count_guarded_rows(db)

    assert set(counts) == {"sessions", "events"}


def test_backup_of_scheduled_reason_carries_guard_and_freeze(env_guard, tmp_path):
    """create_backup(reason=scheduled)がsnapshotの前に見張り、後で暦の刈り取りを行う。"""
    db = _make_db(tmp_path / "guard.db", events=1000)
    expired = _touch_backup(_noon(300))

    first = dbmaint.create_backup(db, reason=dbmaint.REASON_SCHEDULED)
    assert first["guard"]["tripped"] is False
    assert first["prune_frozen"] is False
    assert not expired.exists(), "凍結していなければ暦の外の世代は消える"
    assert dbmaint.list_backups(dbmaint.REASON_SCHEDULED)

    stale = _touch_backup(_noon(280))
    _make_db(db, events=100)
    second = dbmaint.create_backup(db, reason=dbmaint.REASON_SCHEDULED)

    assert second["guard"]["tripped"] is True
    assert second["prune_frozen"] is True
    assert second["pruned"] == []
    assert stale.exists()
    # 退避そのものは止まらない。事故に気付いた回のsnapshotこそ要る。
    assert second["integrity_ok"] is True
    assert dbmaint.integrity_check_file(second["path"])["ok"] is True


def test_manual_prune_is_frozen_too(env_guard, tmp_path, monkeypatch):
    """凍結は回数の世代にも効く。premigrationの1本こそ事故の前の姿である。"""
    monkeypatch.setattr(dbmaint, "get_db_backup_keep", lambda: 1)
    db = _make_db(tmp_path / "guard.db", events=1000)
    dbmaint.check_row_guard(db)
    _make_db(db, events=100)
    dbmaint.check_row_guard(db)

    old = _touch_backup(_noon(9), reason=dbmaint.REASON_PRE_MIGRATION)
    _touch_backup(_noon(1), reason=dbmaint.REASON_PRE_MIGRATION)

    assert dbmaint.prune_backups(dbmaint.REASON_PRE_MIGRATION) == []
    assert old.exists()


# ---- (c) 凍結の解除 --------------------------------------------------------------------


def test_unfreeze_restores_pruning(env_guard, tmp_path):
    db = _make_db(tmp_path / "guard.db", events=1000)
    dbmaint.check_row_guard(db)
    _make_db(db, events=100)
    dbmaint.check_row_guard(db)
    expired = _touch_backup(_noon(300))
    _touch_backup(_noon(0))

    assert dbmaint.prune_scheduled_backups(now=_noon(0))["frozen"] is True
    result = dbmaint.unfreeze_prune()

    assert result["was_frozen"] is True
    assert dbmaint.is_frozen() is None
    after = dbmaint.prune_scheduled_backups(now=_noon(0))
    assert after["frozen"] is False
    assert expired.name in after["removed"]
    assert not expired.exists()


def test_unfreeze_when_not_frozen_is_a_no_op(env_guard):
    result = dbmaint.unfreeze_prune()

    assert result["was_frozen"] is False
    assert result["frozen"] is None


def test_guard_status_reports_freeze_and_counts(env_guard, tmp_path):
    db = _make_db(tmp_path / "guard.db", events=1000)
    dbmaint.check_row_guard(db)
    _make_db(db, events=100)
    dbmaint.check_row_guard(db)

    status = dbmaint.guard_status()

    assert status["frozen"] is not None
    assert status["counts"]["events"] == 100
    assert "events" in status["tables"]
    assert status["ratio"] == pytest.approx(0.02)


def test_ledger_lives_next_to_the_backups_not_in_the_db(env_guard, tmp_path):
    """台帳は退避先に置く。守る対象と同じfileへ入れると、事故と一緒に失われる。"""
    db = _make_db(tmp_path / "guard.db", events=10)
    dbmaint.check_row_guard(db)

    assert dbmaint.ledger_path().parent == dbmaint.backup_dir()
    conn = sqlite3.connect(str(db))
    try:
        names = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()
    assert names == {"sessions", "events"}


def test_broken_ledger_is_read_as_empty(env_guard, tmp_path):
    """台帳が壊れていてもbackupは止めない。守る仕組みが守る対象を止めてはならない。"""
    dbmaint.backup_dir().mkdir(parents=True, exist_ok=True)
    dbmaint.ledger_path().write_text("{ not json", encoding="utf-8")
    db = _make_db(tmp_path / "guard.db", events=1000)

    verdict = dbmaint.check_row_guard(db)

    assert verdict["previous"] == {}
    assert verdict["tripped"] is False
    assert dbmaint.read_ledger()["counts"]["events"] == 1000


def test_ledger_from_another_db_is_not_compared(env_guard, tmp_path):
    """退避先を共有しても、別のDBの行数と比べて凍結しない。"""
    big = _make_db(tmp_path / "big.db", events=10000)
    small = _make_db(tmp_path / "small.db", events=10)
    dbmaint.check_row_guard(big)

    verdict = dbmaint.check_row_guard(small)

    assert verdict["previous"] == {}
    assert verdict["tripped"] is False


# ---- 画面から見える形 ------------------------------------------------------------------


def test_status_api_reports_guard_and_layers(client):  # noqa: F811
    _touch_backup(_noon(0))
    _touch_backup(_noon(30))

    payload = client.get("/api/maintenance/status").json()

    assert payload["guard"]["frozen"] is None
    assert "events" in payload["guard"]["tables"]
    assert payload["scheduled"]["keep_daily"] == 14
    assert payload["scheduled"]["keep_weekly"] == 8
    assert len(payload["scheduled"]["daily"]) == 1
    assert len(payload["scheduled"]["weekly"]) == 1
    # 既存のkeyを壊していない。
    for key in ("db", "backups", "backup_dir", "keep", "before_migration",
                "premigration", "running"):
        assert key in payload


def test_backup_api_records_the_freeze_in_ops_events(client):  # noqa: F811
    """凍結したまま退避した回は、画面のops一覧に必ず1行残る。

    logだけでは足りない。「退避folderが減らない」は凍結の症状なのに、logを開くまで凍結が
    原因だと分からない。"""
    dbmaint.freeze_prune("testの凍結", [{"table": "events", "before": 1000, "after": 100,
                                         "lost": 900, "ratio": 0.9}])

    assert client.post("/api/maintenance/backup").status_code == 200

    kinds = [row["kind"] for row in client.get("/api/ops/events?limit=50").json()["events"]]
    assert "maintenance.prune_frozen" in kinds


def test_unfreeze_api_releases_the_freeze(client):  # noqa: F811
    dbmaint.freeze_prune("testの凍結", [{"table": "events", "before": 10, "after": 1,
                                         "lost": 9, "ratio": 0.9}])

    payload = client.post("/api/maintenance/unfreeze").json()

    assert payload["was_frozen"] is True
    assert payload["guard"]["frozen"] is None
    assert dbmaint.is_frozen() is None
    # 2度目は何も起きない(解除済みを解除しても失敗にしない)。
    assert client.post("/api/maintenance/unfreeze").json()["was_frozen"] is False


# ---- (d) 接続のDROP防御 ----------------------------------------------------------------


def _guarded_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (a INTEGER)")
    conn.execute("CREATE INDEX idx_t_a ON t(a)")
    conn.execute("CREATE VIEW v_t AS SELECT a FROM t")
    dbmaint.attach_drop_guard(conn)
    return conn


@pytest.mark.parametrize("sql", [
    "DROP TABLE t",
    "DROP INDEX idx_t_a",
    "DROP VIEW v_t",
])
def test_drop_is_denied_by_default(sql):
    conn = _guarded_conn()
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(sql)
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 't'").fetchone()[0] == 1
    finally:
        conn.close()


def test_drop_passes_inside_the_allowed_window():
    conn = _guarded_conn()
    try:
        with dbmaint.allow_schema_drops():
            conn.execute("DROP VIEW v_t")
            conn.execute("DROP TABLE t")
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 't'").fetchone()[0] == 0
        # 窓を抜ければ元どおり拒否する。
        conn.execute("CREATE TABLE t2 (a INTEGER)")
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DROP TABLE t2")
    finally:
        conn.close()


def test_allowed_window_is_per_thread():
    """許可はそれを開いたthreadにだけ効く。接続は複数threadで共有される。"""
    conn = _guarded_conn()
    denied = []
    try:
        with dbmaint.allow_schema_drops():
            def _other():
                try:
                    conn.execute("DROP TABLE t")
                    denied.append(False)
                except sqlite3.DatabaseError:
                    denied.append(True)

            worker = threading.Thread(target=_other)
            worker.start()
            worker.join(timeout=10)
        assert denied == [True]
    finally:
        conn.close()


def test_guard_leaves_normal_statements_alone():
    """DELETEは拒否しない。行の削除はUIの正常な機能そのもので、そちらは凍結の側で構える。"""
    conn = _guarded_conn()
    try:
        conn.executemany("INSERT INTO t (a) VALUES (?)", [(i,) for i in range(100)])
        conn.execute("DELETE FROM t WHERE a < 10")
        conn.execute("UPDATE t SET a = a + 1")
        conn.execute("CREATE TABLE t3 (a INTEGER)")
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 90
        assert conn.execute("SELECT COUNT(*) FROM v_t").fetchone()[0] == 90
    finally:
        conn.close()


# ---- 退避先の異常系(driveの消失・落ちた回の残骸) -------------------------------------------


def test_stale_partials_are_swept_before_the_next_snapshot(env_guard, tmp_path):
    """落ちた回の書きかけ(.partial)は次の退避の頭で消える。

    次の世代は別の名前を取るので、残った書きかけを誰も上書きしない。1本がDBと同じ大きさ
    なので、掃かないと落ちた回数ぶん退避先を食う。"""
    db = _make_db(tmp_path / "gen.db", events=10)
    directory = dbmaint.backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stale = directory / "tictok-scheduled-20260101-000000.db.partial"
    stale.write_bytes(b"x" * 1024)
    other = directory / "row-ledger.json.999.partial"
    other.write_text("{}", encoding="utf-8")

    result = dbmaint.create_backup(db, reason=dbmaint.REASON_MANUAL, keep=3)

    assert not stale.exists()
    assert result["swept_partials"] == [stale.name]
    # 退避のsnapshotの名前でない物には触らない。
    assert other.exists()
    assert Path(result["path"]).is_file()


def test_backup_dir_parent_is_never_created(env_guard, tmp_path, monkeypatch):
    """退避先の親folderが無ければ作らずに断る(driveが外れたときにsystem driveへ
    同じpathの空folderを生やして、そこへ世代を積まないため)。直下だけは作る。"""
    db = _make_db(tmp_path / "gen.db", events=10)
    missing = tmp_path / "unplugged" / "db"
    monkeypatch.setenv("TICTOK_DB_BACKUP_DIR", str(missing))

    with pytest.raises(dbmaint.MaintenanceError, match="親folder"):
        dbmaint.create_backup(db, reason=dbmaint.REASON_MANUAL, keep=3)
    assert not missing.exists()
    assert not missing.parent.exists()

    missing.parent.mkdir()
    result = dbmaint.create_backup(db, reason=dbmaint.REASON_MANUAL, keep=3)
    assert Path(result["path"]).parent == missing.resolve()


def test_failed_snapshot_reports_its_own_error_even_if_cleanup_fails(env_guard, tmp_path,
                                                                   monkeypatch):
    """snapshotが落ちた後の書きかけの削除に失敗しても、記録に残るのは退避が落ちた理由の方。

    driveごと外れたときはunlinkも落ちる。それを通すと、logに残るのは「書きかけを消せない」
    で、退避が失敗した本当の理由が読めない。"""
    db = _make_db(tmp_path / "gen.db", events=10)

    def _broken_check(path):
        return {"ok": False, "problems": ["壊れています"]}

    monkeypatch.setattr(dbmaint, "integrity_check_file", _broken_check)
    real_unlink = Path.unlink

    def _unlink(self, missing_ok=False):
        # 書きかけが実在する = snapshotを書いた後の後始末。その時点でdriveが外れたことにする。
        if self.name.endswith(dbmaint._PARTIAL_SUFFIX) and self.exists():
            raise OSError("driveが外れました")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", _unlink)

    with pytest.raises(dbmaint.MaintenanceError, match="integrity_check"):
        dbmaint.create_backup(db, reason=dbmaint.REASON_MANUAL, keep=3)
