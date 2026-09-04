"""消えた行の退避(row単位のundo)。

守りたい性質は4つで、どれが崩れても「事故のあと戻せない」に直結する:

  * 誰が消しても残る(server自身・FK cascade・**外部processの接続**)
  * 対象表の列が増えたら、triggerがその列も残すようになる
  * 保持日数を過ぎたぶんだけが刈られる
  * 戻せる。かつ**現行の行を上書きしない**
"""
import json
import sqlite3
import time

import pytest

from tictok.store import row_trash


def _side_conn(path):
    """serverの接続とは別の接続。sqlite3.exeやDB browserと同じ立場である。"""
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _trash(conn, table=None):
    return row_trash.list_rows(conn, table=table)


def _make_recording(storage) -> int:
    return storage.create_recording(None, "alice", "rec.ts", "rec.ts", "hd", time.time())


# ===== 誰が消しても残る =====

def test_direct_delete_is_captured(tmp_db, tmp_db_path):
    rid = _make_recording(tmp_db)
    mark = tmp_db.add_bookmark(rid, "alice", 12.5, 20.0, memo="ここ")

    assert tmp_db.delete_bookmark(mark["id"]) is True

    conn = _side_conn(tmp_db_path)
    try:
        rows = _trash(conn, "bookmarks")
        assert len(rows) == 1
        payload = json.loads(rows[0]["row_json"])
        assert payload["id"] == mark["id"]
        assert payload["memo"] == "ここ"
        # end はSQLの予約語。引用しないとtriggerの作成自体が通らないので、値まで確かめる。
        assert payload["end"] == 20.0
        assert rows[0]["row_pk"] == str(mark["id"])
    finally:
        conn.close()


def test_cascade_delete_is_captured(tmp_db, tmp_db_path):
    rid = _make_recording(tmp_db)
    tmp_db.add_bookmark(rid, "alice", 1.0, 2.0, memo="a")
    tmp_db.add_bookmark(rid, "alice", 3.0, 4.0, memo="b")
    tmp_db.upsert_corrections(rid, [{"start": 1.0, "src": "こんにちわ", "dst": "こんにちは"}])

    # 録画を消すと bookmarks / transcript_corrections が FK cascade で落ちる。
    assert tmp_db.delete_recording(rid) is not None

    conn = _side_conn(tmp_db_path)
    try:
        assert len(_trash(conn, "bookmarks")) == 2
        assert len(_trash(conn, "transcript_corrections")) == 1
    finally:
        conn.close()


def test_delete_from_another_connection_is_captured(tmp_db, tmp_db_path):
    """**authorizerが効かない穴**を塞げているか。triggerはschemaの一部なので、serverの
    接続を通らない削除でも発火する。"""
    rid = _make_recording(tmp_db)
    mark = tmp_db.add_bookmark(rid, "alice", 5.0, 6.0, memo="外から消す")

    conn = _side_conn(tmp_db_path)
    try:
        conn.execute("DELETE FROM bookmarks WHERE id = ?", (mark["id"],))
        conn.commit()
        rows = _trash(conn, "bookmarks")
        assert len(rows) == 1
        assert json.loads(rows[0]["row_json"])["memo"] == "外から消す"
    finally:
        conn.close()


def test_settings_update_is_not_captured_but_delete_is(tmp_db, tmp_db_path):
    """settingsは upsert で更新される。**「値を変えた」は退避の対象外**である
    (その領域を守るのは core/settings_export の世代)。"""
    tmp_db.set_settings({"record_dir": "D:/rec"})
    tmp_db.set_settings({"record_dir": "E:/rec"})

    conn = _side_conn(tmp_db_path)
    try:
        assert _trash(conn, "settings") == []
        conn.execute("DELETE FROM settings WHERE key = 'record_dir'")
        conn.commit()
        rows = _trash(conn, "settings")
        assert len(rows) == 1
        assert json.loads(rows[0]["row_json"]) == {"key": "record_dir", "value": "E:/rec"}
    finally:
        conn.close()


def test_events_has_no_trigger(tmp_db, tmp_db_path):
    """eventsとviewer_samplesには掛けない。1 sessionの削除で36,892行(実測)がcascadeし、
    書き込みが倍になる —— そちらは journal の再生と割合の見張りが守る領域である。"""
    conn = _side_conn(tmp_db_path)
    try:
        names = {row["name"] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'")}
        assert row_trash.trigger_name("bookmarks") in names
        assert row_trash.trigger_name("events") not in names
        assert row_trash.trigger_name("viewer_samples") not in names
        assert names == {row_trash.trigger_name(t) for t in row_trash.ROW_TRASH_TABLES}
    finally:
        conn.close()


# ===== 定義が変わったら作り直す =====

def test_triggers_are_stable_when_nothing_changed(tmp_db):
    """2度目のensureで作り直さない。毎起動で作り直す状態は、指紋が効いていない印である。"""
    with tmp_db._lock:
        result = row_trash.ensure_triggers(tmp_db._conn)
    assert result["created"] == []
    assert result["replaced"] == []


def test_new_column_rebuilds_the_trigger(tmp_db, tmp_db_path):
    """対象表に列が増えたら、その列も残すtriggerへ作り直される。作り直さないと、足した列の
    値だけが消えても残らない —— 一番気付きにくい壊れ方である。"""
    with tmp_db._lock:
        tmp_db._conn.execute("ALTER TABLE clip_groups ADD COLUMN owner TEXT")
        result = row_trash.ensure_triggers(tmp_db._conn)
        tmp_db._conn.commit()
    assert result["replaced"] == ["clip_groups"]

    group = tmp_db.add_group("新しい棚")
    conn = _side_conn(tmp_db_path)
    try:
        conn.execute("UPDATE clip_groups SET owner = 'alice' WHERE id = ?", (group["id"],))
        conn.execute("DELETE FROM clip_groups WHERE id = ?", (group["id"],))
        conn.commit()
        payload = json.loads(_trash(conn, "clip_groups")[0]["row_json"])
        assert payload["owner"] == "alice"
    finally:
        conn.close()


def test_without_triggers_allows_dropping_a_column(tmp_db):
    """triggerは列を名指しするので、SQLiteはその列を参照するtriggerが在る間 DROP COLUMN を
    拒否する。対象6表から列を落とすmigrationは without_triggers で包む必要がある。"""
    with tmp_db._lock:
        tmp_db._conn.execute("ALTER TABLE clip_groups ADD COLUMN owner TEXT")
        row_trash.ensure_triggers(tmp_db._conn)
        with pytest.raises(sqlite3.OperationalError):
            tmp_db._conn.execute("ALTER TABLE clip_groups DROP COLUMN owner")
        with row_trash.without_triggers(tmp_db._conn):
            tmp_db._conn.execute("ALTER TABLE clip_groups DROP COLUMN owner")
        tmp_db._conn.commit()
        # 抜けた時点でtriggerは戻っている。
        assert tmp_db._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'trigger' AND name = ?",
            (row_trash.trigger_name("clip_groups"),)).fetchone() is not None


def test_dropped_trigger_is_restored(tmp_db):
    """外から ``DROP TRIGGER`` された場合も、実物と突き合わせているので同じ経路で戻る。"""
    from tictok.core import dbmaint

    with tmp_db._lock:
        with dbmaint.allow_schema_drops():
            tmp_db._conn.execute(f"DROP TRIGGER {row_trash.trigger_name('settings')}")
        result = row_trash.ensure_triggers(tmp_db._conn)
        tmp_db._conn.commit()
    assert result["created"] == ["settings"]


# ===== 保持 =====

def test_prune_removes_only_expired_rows(tmp_db, tmp_db_path):
    now = time.time()
    conn = _side_conn(tmp_db_path)
    try:
        conn.executemany(
            "INSERT INTO row_trash (table_name, row_pk, deleted_at, row_json)"
            " VALUES ('settings', 'k', ?, '{}')",
            [(now - 400 * 86400,), (now - 366 * 86400,), (now - 10 * 86400,)],
        )
        conn.commit()
        assert row_trash.prune(conn, 365, now=now) == 2
        conn.commit()
        rows = _trash(conn, "settings")
        assert len(rows) == 1
        assert rows[0]["deleted_at"] == pytest.approx(now - 10 * 86400)
        # 0は「刈らない」(この設定群の規約)。
        assert row_trash.prune(conn, 0, now=now) == 0
    finally:
        conn.close()


def test_deleted_at_is_epoch_seconds(tmp_db, tmp_db_path):
    """triggerが入れる時刻は epoch秒。ここがずれると保持日数が意味を持たない。"""
    before = time.time()
    tmp_db.add_monitored_target("bob")
    tmp_db.remove_monitored_target("bob")
    after = time.time()
    conn = _side_conn(tmp_db_path)
    try:
        stamp = _trash(conn, "monitored_targets")[0]["deleted_at"]
        assert before - 2.0 <= stamp <= after + 2.0
    finally:
        conn.close()


# ===== 復元 =====

def test_restore_puts_the_row_back(tmp_db, tmp_db_path):
    rid = _make_recording(tmp_db)
    mark = tmp_db.add_bookmark(rid, "alice", 30.0, 40.0, memo="戻す対象")
    tmp_db.delete_bookmark(mark["id"])

    conn = _side_conn(tmp_db_path)
    try:
        trash_row = _trash(conn, "bookmarks")[0]
        dry = row_trash.restore_row(conn, trash_row, apply=False)
        assert dry["ok"] is True and dry["restored"] is False
        assert conn.execute("SELECT COUNT(*) FROM bookmarks").fetchone()[0] == 0

        done = row_trash.restore_row(conn, trash_row, apply=True)
        conn.commit()
        assert done["restored"] is True
        row = conn.execute("SELECT * FROM bookmarks WHERE id = ?", (mark["id"],)).fetchone()
        assert row["memo"] == "戻す対象"
        assert row["start"] == 30.0 and row["end"] == 40.0
        # 退避行は残す。戻した後も「いつ消えたか」の記録が要る。
        assert len(_trash(conn, "bookmarks")) == 1
    finally:
        conn.close()


def test_restore_never_overwrites_an_existing_row(tmp_db, tmp_db_path):
    """戻すつもりで現行を壊さない。同じidの行が在れば理由付きで飛ばす。"""
    rid = _make_recording(tmp_db)
    mark = tmp_db.add_bookmark(rid, "alice", 1.0, 2.0, memo="古い")
    tmp_db.delete_bookmark(mark["id"])

    conn = _side_conn(tmp_db_path)
    try:
        trash_row = _trash(conn, "bookmarks")[0]
        # 同じidの別の行が既に在る状態を作る。
        conn.execute(
            "INSERT INTO bookmarks (id, recording_id, unique_id, start, end, memo,"
            " pts_mapped, origin, created_at) VALUES (?, ?, 'alice', 9.0, 9.5, '今の行',"
            " 1, 'manual', ?)",
            (mark["id"], rid, time.time()))
        conn.commit()

        result = row_trash.restore_row(conn, trash_row, apply=True)
        conn.commit()
        assert result["ok"] is False and result["restored"] is False
        assert "既に在る" in result["reason"]
        row = conn.execute("SELECT memo FROM bookmarks WHERE id = ?", (mark["id"],)).fetchone()
        assert row["memo"] == "今の行"
    finally:
        conn.close()


def test_restore_reports_column_drift(tmp_db, tmp_db_path):
    """退避した後に落ちた列は捨て、足された列はDEFAULTで埋まる。どちらも結果に載る ——
    戻した行が元と同じでないなら、それを名指しで言えなければならない。"""
    rid = _make_recording(tmp_db)
    group = tmp_db.add_group("棚")
    tmp_db.delete_group(group["id"])

    conn = _side_conn(tmp_db_path)
    try:
        trash_row = _trash(conn, "clip_groups")[0]
        conn.execute("ALTER TABLE clip_groups ADD COLUMN owner TEXT")
        stale = dict(trash_row)
        payload = json.loads(stale["row_json"])
        payload["gone"] = "落ちた列の値"
        stale["row_json"] = json.dumps(payload)
        result = row_trash.restore_row(conn, stale, apply=True)
        conn.commit()
        assert result["restored"] is True
        assert result["dropped_columns"] == ["gone"]
        assert result["missing_columns"] == ["owner"]
        row = conn.execute(
            "SELECT * FROM clip_groups WHERE id = ?", (group["id"],)).fetchone()
        assert row["name"] == "棚" and row["owner"] is None
    finally:
        conn.close()
