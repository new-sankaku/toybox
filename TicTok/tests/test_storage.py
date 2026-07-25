import logging
import sqlite3
import time

import pytest

from tictok.storage import (
    OPS_ERROR,
    OPS_INFO,
    OPS_WARNING,
    SESSION_STATUS_RESTRICTED,
    Storage,
    _identity_key,
    _session_ids_of,
    _to_int,
    _valid_owner_id,
)

log = logging.getLogger("tests.storage")


def _side_conn(path):
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


# ===== 純粋helper =====

@pytest.mark.parametrize(
    "user_id, unique_id, nickname, expected",
    [
        ("7300000000000000001", "alice", "Alice", "7300000000000000001"),
        ("", "alice", "Alice", "alice"),
        (None, "", "Alice", "Alice"),
        ("   ", " alice ", "Alice", "alice"),
        (0, "alice", "Alice", "alice"),
        (None, None, None, ""),
    ],
)
def test_identity_key_prefers_immutable_id_then_handle_then_nickname(
    user_id, unique_id, nickname, expected
):
    assert _identity_key(user_id, unique_id, nickname) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("12345678", True),
        ("1234567", False),
        ("730000000000000000", True),
        ("1", False),
        ("abcdefgh", False),
        ("1234567a", False),
        ("", False),
        (None, False),
        (" 12345678 ", True),
    ],
)
def test_valid_owner_id_rejects_short_and_nonnumeric(value, expected):
    assert _valid_owner_id(value) is expected


@pytest.mark.parametrize(
    "value, expected",
    [(None, 0), (5, 5), ("7", 7), ("3.9", 3), (2.9, 2), ("", 0), ("abc", 0), ([], 0)],
)
def test_to_int_never_raises_and_falls_back_to_zero(value, expected):
    assert _to_int(value) == expected


def test_session_ids_of_dedupes_sorts_and_skips_empty_rows():
    events = [(3, 1.0), (1, 2.0), (3, 3.0)]
    viewers = [(2, 4.0), ()]
    assert _session_ids_of(events, viewers) == [1, 2, 3]


def test_like_prefix_escapes_sql_wildcards():
    # kindは 'process.settings_updated' のように '_' を含む。escapeしないと別kindを巻き込む。
    assert Storage._like_prefix("job_") == "job\\_%"
    assert Storage._like_prefix("a%b") == "a\\%b%"
    assert Storage._like_prefix("a\\b") == "a\\\\b%"


# ===== batch writer / flush / 孤児event =====

def test_flush_persists_buffered_events_with_migrated_columns(
    tmp_db, db_read, make_session, event_builder
):
    session_id = make_session(status="connected")
    tmp_db.add_event(session_id, event_builder("comment", at=100.0, comment="hi", text="hi"))
    tmp_db.add_event(session_id, event_builder("like", at=101.0, count=7))
    tmp_db.flush()
    rows = db_read.execute(
        "SELECT kind, comment, count, identity_key FROM events"
        " WHERE session_id = ? ORDER BY time",
        (session_id,),
    ).fetchall()
    assert [r["kind"] for r in rows] == ["comment", "like"]
    assert rows[0]["comment"] == "hi"
    assert rows[1]["count"] == 7
    assert rows[0]["identity_key"] == "u1"


def test_delete_session_purges_buffered_events_and_writer_keeps_going(
    tmp_db, db_read, make_session, event_builder
):
    """session削除でbuffer滞留eventが孤児化しdrainがFK違反で永久に詰まる回帰(poison-pill)。"""
    doomed = make_session("doomed", status="connected")
    survivor = make_session("survivor", status="connected")
    for i in range(5):
        tmp_db.add_event(doomed, event_builder("comment", at=100.0 + i))

    assert tmp_db.delete_session(doomed) is True

    # 削除後も後続sessionの書き込みが通ること(=drainが詰まっていないこと)が本題。
    tmp_db.add_event(survivor, event_builder("comment", at=200.0))
    tmp_db.flush()

    assert db_read.execute(
        "SELECT COUNT(*) n FROM events WHERE session_id = ?", (doomed,)
    ).fetchone()["n"] == 0
    assert db_read.execute(
        "SELECT COUNT(*) n FROM events WHERE session_id = ?", (survivor,)
    ).fetchone()["n"] == 1


def test_delete_session_returns_false_for_unknown_id(tmp_db):
    assert tmp_db.delete_session(999999) is False


def test_drain_drops_orphan_rows_and_still_writes_live_sessions(
    tmp_db, tmp_db_path, db_read, make_session, event_builder
):
    """delete_sessionを経由せず消えたsessionのeventが混じっても、batch全体を道連れに
    せず生存sessionの分は確定すること。"""
    alive = make_session("alive", status="connected")
    gone = make_session("gone", status="connected")
    side = _side_conn(tmp_db_path)
    try:
        side.execute("DELETE FROM sessions WHERE id = ?", (gone,))
        side.commit()
    finally:
        side.close()

    tmp_db.add_event(alive, event_builder("comment", at=100.0))
    tmp_db.add_event(gone, event_builder("comment", at=101.0))
    tmp_db.add_event(alive, event_builder("comment", at=102.0))
    tmp_db.add_viewer_sample(gone, 103.0, None, 12, None, None)
    tmp_db.flush()

    assert db_read.execute(
        "SELECT COUNT(*) n FROM events WHERE session_id = ?", (alive,)
    ).fetchone()["n"] == 2
    assert db_read.execute(
        "SELECT COUNT(*) n FROM events WHERE session_id = ?", (gone,)
    ).fetchone()["n"] == 0
    assert db_read.execute(
        "SELECT COUNT(*) n FROM viewer_samples WHERE session_id = ?", (gone,)
    ).fetchone()["n"] == 0


def test_add_event_upsert_keeps_earlier_nonempty_user_attributes(
    tmp_db, db_read, make_session, event_builder
):
    session_id = make_session(status="connected")
    rich = event_builder.user(user_id="7300000000000000009", nickname="Alice",
                              avatar="http://a/1.png", fans_level=4)
    poor = event_builder.user(user_id="7300000000000000009", nickname="", avatar="",
                              fans_level=0)
    tmp_db.add_event(session_id, event_builder("comment", at=100.0, user=rich))
    tmp_db.add_event(session_id, event_builder("comment", at=101.0, user=poor))
    tmp_db.flush()
    row = db_read.execute(
        "SELECT * FROM users WHERE identity_key = ?", ("7300000000000000009",)
    ).fetchone()
    assert row["nickname"] == "Alice"
    assert row["avatar"] == "http://a/1.png"
    assert row["fans_level"] == 4
    assert row["last_seen"] == 101.0


def test_add_event_honours_the_identity_key_supplied_by_the_collector(
    tmp_db, db_read, make_session, event_builder
):
    """collectorが決めたidentity_keyをeventsにそのまま書く。ここでnicknameから再計算
    すると、表示用の "(unknown)" がkeyになり別人が1 identityへ畳まれる。"""
    session_id = make_session(status="connected")
    a = event_builder.user(user_id="", unique_id="", nickname="(unknown)", identity_key="")
    b = event_builder.user(user_id="", unique_id="", nickname="(unknown)", identity_key="")
    tmp_db.add_event(session_id, event_builder("comment", at=100.0, user=a))
    tmp_db.add_event(session_id, event_builder("comment", at=101.0, user=b))
    tmp_db.flush()
    keys = [r["identity_key"] for r in db_read.execute(
        "SELECT identity_key FROM events WHERE session_id = ?", (session_id,)
    )]
    assert keys == ["", ""]
    # 身元不明はusers表にも入らない("(unknown)"という1人を作らない)。
    assert db_read.execute(
        "SELECT COUNT(*) n FROM users WHERE identity_key = '(unknown)'"
    ).fetchone()["n"] == 0
    assert db_read.execute("SELECT COUNT(*) n FROM users").fetchone()["n"] == 0


def test_add_event_treats_unknown_nickname_as_missing(
    tmp_db, db_read, make_session, event_builder
):
    session_id = make_session(status="connected")
    user = event_builder.user(user_id="7300000000000000008", nickname="(unknown)")
    tmp_db.add_event(session_id, event_builder("comment", at=100.0, user=user))
    tmp_db.flush()
    row = db_read.execute(
        "SELECT nickname FROM users WHERE identity_key = ?", ("7300000000000000008",)
    ).fetchone()
    assert row["nickname"] == ""


def test_add_event_without_identifiable_user_creates_no_users_row(
    tmp_db, db_read, make_session, event_builder
):
    session_id = make_session(status="connected")
    anon = event_builder.user(user_id="", unique_id="", nickname="")
    tmp_db.add_event(session_id, event_builder("comment", at=100.0, user=anon))
    tmp_db.flush()
    assert db_read.execute("SELECT COUNT(*) n FROM users").fetchone()["n"] == 0
    assert db_read.execute("SELECT COUNT(*) n FROM events").fetchone()["n"] == 1


# ===== session lifecycle =====

def test_create_session_starts_as_connecting(tmp_db, make_session):
    session_id = make_session("tester", 10)
    item = tmp_db.get_session(session_id)
    assert item["status"] == "connecting"
    assert item["bucket_seconds"] == 10
    assert item["ended_at"] is None


def test_cleanup_stale_sessions_recovers_stats_from_events(
    tmp_db, make_session, event_builder, gift_builder
):
    session_id = make_session(status="connected")
    tmp_db.add_event(session_id, gift_builder(diamonds=10, repeat_count=3, at=100.0))
    tmp_db.add_event(session_id, event_builder("like", at=150.0, count=5))
    tmp_db.add_event(session_id, event_builder("comment", at=200.0, comment="x"))
    tmp_db.flush()

    assert tmp_db.cleanup_stale_sessions() == 1
    item = tmp_db.get_session(session_id)
    assert item["status"] == "disconnected"
    # ended_atは「最後にeventが届いた時刻」。プロセス落ちの終端はこれ以外に根拠が無い。
    assert item["ended_at"] == 200.0
    stats = item["stats"]
    assert stats["gifts"] == 3
    assert stats["diamonds"] == 10
    assert stats["likes_total"] == 5
    assert stats["comments"] == 1
    assert stats["events_total"] == 3
    assert stats["recovered"] is True


def test_cleanup_stale_sessions_leaves_finished_and_restricted_alone(tmp_db, make_session):
    done = make_session("done", status="disconnected")
    restricted = make_session("restricted", status=SESSION_STATUS_RESTRICTED)
    assert tmp_db.cleanup_stale_sessions() == 0
    assert tmp_db.get_session(done)["status"] == "disconnected"
    assert tmp_db.get_session(restricted)["status"] == SESSION_STATUS_RESTRICTED


def test_update_session_owner_ignores_bogus_owner_id_and_backfills_handle(
    tmp_db, make_session
):
    old = make_session("alice", status="connected")
    new = make_session("alice", status="connected")
    other = make_session("bob", status="connected")

    # team_id等の小さな値はowner数値IDとして採用しない。
    tmp_db.update_session_owner(new, "Alice", "http://a.png", user_id="2")
    assert tmp_db.get_session(new)["owner_user_id"] in (None, "")

    tmp_db.update_session_owner(new, "Alice", "http://a.png", user_id="7300000000000000001")
    assert tmp_db.get_session(new)["owner_user_id"] == "7300000000000000001"
    # 同一@handleの過去sessionへ伝播し、別handleは巻き込まない。
    assert tmp_db.get_session(old)["owner_user_id"] == "7300000000000000001"
    assert tmp_db.get_session(other)["owner_user_id"] in (None, "")


def test_latest_owner_picks_latest_nonempty_avatar_and_nickname_independently(
    tmp_db, make_session
):
    first = make_session("alice", status="connected")
    second = make_session("alice", status="connected")
    tmp_db.update_session_owner(first, "Alice", "")
    tmp_db.update_session_owner(second, "", "http://a/new.png")
    assert tmp_db.latest_owner("alice") == {
        "avatar": "http://a/new.png", "nickname": "Alice"
    }


def test_latest_owner_of_unknown_streamer_is_blank(tmp_db):
    assert tmp_db.latest_owner("nobody") == {"avatar": "", "nickname": ""}


def test_list_sessions_limit_zero_returns_all_and_fills_owner_nickname(
    tmp_db, make_session
):
    for _ in range(3):
        make_session("alice", status="connected")
    items = tmp_db.list_sessions(0)
    assert len(items) == 3
    # nicknameが未取得のsessionは@handleで代替する(最新配信のnicknameは借りない)。
    assert all(i["owner_nickname"] == "alice" for i in items)
    assert len(tmp_db.list_sessions(2)) == 2


def test_session_viewers_peak_falls_back_to_bucket_max(tmp_db, make_session):
    session_id = make_session(status="connected")
    timeline = [
        {"start": 0, "gifts": 0, "diamonds": 0, "comments": 0, "likes": 0,
         "joins": 0, "follows": 0, "shares": 0, "viewers": 12},
        {"start": 10, "gifts": 0, "diamonds": 0, "comments": 0, "likes": 0,
         "joins": 0, "follows": 0, "shares": 0, "viewers": 42},
    ]
    tmp_db.finalize_session(session_id, "disconnected", {"viewers": 3}, timeline, [])
    item = tmp_db.get_session(session_id)
    assert item["stats"]["viewers_peak"] == 42
    assert len(tmp_db.session_timeline(session_id)["buckets"]) == 2


def test_finalize_session_replaces_buckets_but_appends_markers(tmp_db, make_session):
    session_id = make_session(status="connected")
    bucket = {"start": 0, "gifts": 1, "diamonds": 2, "comments": 3, "likes": 4,
              "joins": 5, "follows": 6, "shares": 7, "viewers": 8}
    tmp_db.append_markers(session_id, [{"time": 1.0, "kind": "disconnect", "label": "a"}])
    tmp_db.finalize_session(
        session_id, "disconnected", {}, [bucket],
        [{"time": 2.0, "kind": "battle", "label": "b"}],
    )
    tmp_db.finalize_session(
        session_id, "disconnected", {}, [dict(bucket, start=10)],
        [{"time": 2.0, "kind": "battle", "label": "b"}],
    )
    timeline = tmp_db.session_timeline(session_id)
    assert [b["start"] for b in timeline["buckets"]] == [10]
    # markerは全置換ではなく追記かつ冪等。checkpoint済みの古いmarkerを消してはいけない。
    assert [m["label"] for m in timeline["markers"]] == ["a", "b"]


def test_append_markers_is_idempotent(tmp_db, make_session):
    session_id = make_session(status="connected")
    markers = [
        {"time": 1.0, "kind": "disconnect", "label": "x"},
        {"time": 2.0, "kind": "reconnect", "label": "y"},
    ]
    tmp_db.append_markers(session_id, markers)
    tmp_db.append_markers(session_id, markers + [{"time": 3.0, "kind": "b", "label": "z"}])
    got = tmp_db.session_timeline(session_id)["markers"]
    assert [m["label"] for m in got] == ["x", "y", "z"]


def test_find_restricted_session_folds_one_room_into_one_row(tmp_db, make_session):
    restricted = make_session("alice")
    tmp_db.update_session(restricted, SESSION_STATUS_RESTRICTED, room_id=777)
    normal = make_session("alice")
    tmp_db.update_session(normal, "connected", room_id=888)

    assert tmp_db.find_restricted_session("alice", 777) == restricted
    assert tmp_db.find_restricted_session("alice", "777") == restricted
    assert tmp_db.find_restricted_session("alice", 888) is None
    assert tmp_db.find_restricted_session("bob", 777) is None
    # room_id不明のときに任意の制限行へ吸い込まれてはいけない。
    assert tmp_db.find_restricted_session("alice", None) is None


def test_session_ids_for_users_follows_handle_rename_via_owner_id(tmp_db, make_session):
    old = make_session("alice_old", status="connected")
    new = make_session("alice_new", status="connected")
    unrelated = make_session("bob", status="connected")
    tmp_db.update_session_owner(old, "Alice", "", user_id="7300000000000000001")
    tmp_db.update_session_owner(new, "Alice", "", user_id="7300000000000000001")

    ids = tmp_db.session_ids_for_users(["alice_new"])
    assert ids == sorted([old, new])
    assert unrelated not in ids


# ===== event読み出し =====

def test_iter_events_window_is_inclusive_on_both_ends(tmp_db, make_session, event_builder):
    session_id = make_session(status="connected")
    for t in (99.0, 100.0, 150.0, 200.0, 201.0):
        tmp_db.add_event(session_id, event_builder("comment", at=t, comment=str(t)))
    got = tmp_db.iter_events(session_id, start=100.0, end=200.0)
    assert [e["time"] for e in got] == [100.0, 150.0, 200.0]
    assert len(tmp_db.iter_events(session_id)) == 5


def test_iter_events_flushes_before_reading(tmp_db, make_session, event_builder):
    session_id = make_session(status="connected")
    tmp_db.add_event(session_id, event_builder("comment", at=100.0, comment="a"))
    # add_eventはbuffer投入で即returnする。読み手が自分でflushしなければ落ちる読み取り。
    assert [e["comment"] for e in tmp_db.iter_events(session_id)] == ["a"]


def test_session_comments_prefers_comment_column_and_returns_newest_first(
    tmp_db, make_session, event_builder
):
    session_id = make_session(status="connected")
    tmp_db.add_event(session_id, event_builder("comment", at=100.0, comment="first"))
    tmp_db.add_event(session_id, event_builder("comment", at=101.0, text="legacy"))
    tmp_db.add_event(session_id, event_builder("comment", at=102.0, comment="", text=""))
    tmp_db.add_event(session_id, event_builder("like", at=103.0, count=1))
    assert tmp_db.session_comments(session_id, 10) == ["legacy", "first"]
    # LIMITは空commentを除外した後の件数に効く。直近が空commentでも要求件数まで埋まること。
    assert tmp_db.session_comments(session_id, 2) == ["legacy", "first"]
    assert tmp_db.session_comments(session_id, 1) == ["legacy"]


def test_session_comments_limit_is_not_eaten_by_empty_comments(
    tmp_db, make_session, event_builder
):
    """直近が空commentだらけでも、LIMITは実本文のある行に効くこと。空をPython側で
    捨てるとLIMITが空行に食われ、要求件数より少なく(最悪0件)返ってAI分析の入力が痩せる。"""
    session_id = make_session(status="connected")
    for i in range(3):
        tmp_db.add_event(session_id, event_builder("comment", at=100.0 + i, comment=f"c{i}"))
    for i in range(5):
        tmp_db.add_event(session_id, event_builder("comment", at=200.0 + i, comment="", text=""))
    tmp_db.add_event(session_id, event_builder("comment", at=300.0, comment=None, text=None))
    assert tmp_db.session_comments(session_id, 3) == ["c2", "c1", "c0"]


def test_session_comments_keeps_whitespace_only_bodies(tmp_db, make_session, event_builder):
    """「空」の定義はNULLと空文字だけ。空白のみの本文までSQLで落とすと定義がずれる。"""
    session_id = make_session(status="connected")
    tmp_db.add_event(session_id, event_builder("comment", at=100.0, comment="  "))
    assert tmp_db.session_comments(session_id, 10) == ["  "]


def test_session_summary_aggregates_gifts_and_hides_missing_levels(
    tmp_db, make_session, gift_builder, event_builder
):
    session_id = make_session(status="connected")
    whale = event_builder.user(user_id="7300000000000000001", nickname="Whale",
                               gifter_level=7)
    minnow = event_builder.user(user_id="7300000000000000002", nickname="Minnow")
    tmp_db.add_event(session_id, gift_builder("Rose", diamonds=10, repeat_count=2,
                                              at=100.0, user=whale))
    tmp_db.add_event(session_id, gift_builder("Rose", diamonds=5, repeat_count=1,
                                              at=101.0, user=whale))
    tmp_db.add_event(session_id, gift_builder("Lion", diamonds=1, repeat_count=1,
                                              at=102.0, user=minnow))
    tmp_db.flush()
    summary = tmp_db.session_summary(session_id)

    assert [u["nickname"] for u in summary["users"]] == ["Whale", "Minnow"]
    top = summary["users"][0]
    assert top["diamonds"] == 15
    assert top["gifts"] == 3
    assert top["items"]["Rose"] == {"count": 3, "diamonds": 15}
    assert top["gifter_level"] == 7
    # Lv/badgeはpoint-in-timeのみ。未観測は0(非表示)で、捏造して埋めない。
    assert summary["users"][1]["gifter_level"] == 0
    assert [g["name"] for g in summary["gifts"]] == ["Rose", "Lion"]


def test_battle_gift_contributions_uses_server_time_window(
    tmp_db, make_session, gift_builder, event_builder
):
    session_id = make_session(status="connected")
    user = event_builder.user(user_id="7300000000000000001", nickname="Whale")
    # create_time(サーバ時刻)が窓内、受信時刻timeは窓外。突合はcreate_time優先。
    tmp_db.add_event(session_id, gift_builder(diamonds=50, at=999.0, user=user,
                                              create_time=150.0))
    # 窓の外。
    tmp_db.add_event(session_id, gift_builder(diamonds=7, at=100.0, user=user,
                                              create_time=300.0))
    # diamonds 0 は貢献として数えない。
    tmp_db.add_event(session_id, gift_builder(diamonds=0, at=101.0, user=user,
                                              create_time=160.0))
    rows = tmp_db.battle_gift_contributions(session_id, 100.0, 200.0)
    assert len(rows) == 1
    assert rows[0]["diamonds"] == 50
    assert rows[0]["side"] == "own"


# ===== ops_events =====

def test_record_ops_event_rejects_unknown_severity(tmp_db):
    with pytest.raises(ValueError):
        tmp_db.record_ops_event(log, "test.kind", "msg", severity="critical")


def test_record_ops_event_returns_unique_ops_ids_and_persists(tmp_db, make_session):
    session_id = make_session(status="connected")
    first = tmp_db.record_ops_event(log, "test.a", "one", session_id=session_id)
    second = tmp_db.record_ops_event(log, "test.a", "two", session_id=session_id)
    assert first != second
    items = tmp_db.list_ops_events(session_id=session_id)
    assert {i["ops_id"] for i in items} == {first, second}
    assert all(i["detail"] == {} for i in items)


def test_ops_events_survive_session_deletion(tmp_db, make_session):
    """ops_eventsはFKを張らない。session削除後も障害当時の行が残ること。"""
    session_id = make_session(status="connected")
    tmp_db.record_ops_event(log, "test.boom", "died", severity=OPS_ERROR,
                            session_id=session_id)
    assert tmp_db.delete_session(session_id) is True
    items = tmp_db.list_ops_events(session_id=session_id)
    assert len(items) == 1
    assert items[0]["session_unique_id"] is None


def test_ops_events_kind_prefix_escapes_underscore(tmp_db):
    tmp_db.record_ops_event(log, "job_start", "a")
    tmp_db.record_ops_event(log, "jobXstart", "b")
    assert {i["kind"] for i in tmp_db.list_ops_events(kind_prefix="job_")} == {"job_start"}


def test_count_ops_events_by_severity(tmp_db):
    tmp_db.record_ops_event(log, "k", "a", severity=OPS_INFO)
    tmp_db.record_ops_event(log, "k", "b", severity=OPS_WARNING)
    tmp_db.record_ops_event(log, "k", "c", severity=OPS_WARNING)
    assert tmp_db.count_ops_events_by_severity() == {OPS_INFO: 1, OPS_WARNING: 2}


def test_list_ops_events_keyset_paging_has_no_overlap(tmp_db):
    for i in range(5):
        tmp_db.record_ops_event(log, "k", f"m{i}")
    page1 = tmp_db.list_ops_events(limit=2)
    assert len(page1) == 2
    cursor = page1[-1]
    page2 = tmp_db.list_ops_events(limit=2, before_ts=cursor["ts"], before_id=cursor["id"])
    assert len(page2) == 2
    assert {i["id"] for i in page1}.isdisjoint({i["id"] for i in page2})
    all_ids = [i["id"] for i in tmp_db.list_ops_events(limit=10)]
    assert [i["id"] for i in page1 + page2] == all_ids[:4]


@pytest.mark.parametrize("bad", [-1, 0, -100])
def test_list_ops_events_rejects_non_positive_limit(tmp_db, bad):
    """SQLiteはLIMIT -1を無制限と解釈する。素通しすると1requestで全件を読み込む。"""
    for i in range(3):
        tmp_db.record_ops_event(log, "k", f"m{i}")
    with pytest.raises(ValueError):
        tmp_db.list_ops_events(limit=bad)


def test_list_ops_events_none_limit_uses_configured_default(tmp_db, monkeypatch):
    monkeypatch.setattr("tictok.storage.get_ops_events_query_limit", lambda: 2)
    for i in range(5):
        tmp_db.record_ops_event(log, "k", f"m{i}")
    assert len(tmp_db.list_ops_events()) == 2


def test_ops_event_detail_is_truncated_but_says_so(tmp_db, monkeypatch):
    monkeypatch.setattr("tictok.storage.get_ops_events_detail_max_chars", lambda: 40)
    tmp_db.record_ops_event(log, "k", "big", detail={"stderr": "x" * 500})
    item = tmp_db.list_ops_events(kind="k")[0]
    assert item["detail"]["truncated_chars"] > 0
    assert len(item["detail"]["detail"]) == 40


def test_ops_event_kinds_reports_counts(tmp_db):
    tmp_db.record_ops_event(log, "b.kind", "1")
    tmp_db.record_ops_event(log, "a.kind", "2")
    tmp_db.record_ops_event(log, "a.kind", "3")
    assert tmp_db.ops_event_kinds() == [
        {"kind": "a.kind", "count": 2},
        {"kind": "b.kind", "count": 1},
    ]


# ===== AI分析cache =====

def test_ai_analysis_roundtrip_and_replace(tmp_db, make_session):
    session_id = make_session(status="connected")
    tmp_db.save_ai_analysis("summary", "session", str(session_id), session_id=session_id,
                            model="m1", prompt_version=1, input_signature="sig1",
                            payload={"a": 1})
    tmp_db.save_ai_analysis("summary", "session", str(session_id), session_id=session_id,
                            model="m2", prompt_version=2, input_signature="sig2",
                            payload={"a": 2})
    got = tmp_db.get_ai_analysis("summary", "session", str(session_id))
    assert got["model"] == "m2"
    assert got["prompt_version"] == 2
    assert got["payload"] == {"a": 2}
    assert tmp_db.get_ai_analysis("summary", "session", "nope") is None


def test_ai_analysis_unreadable_payload_is_not_reported_as_unanalyzed(tmp_db, tmp_db_path):
    tmp_db.save_ai_analysis("summary", "streamer", "alice", session_id=None,
                            model="m", prompt_version=1, input_signature="s",
                            payload={"a": 1})
    side = _side_conn(tmp_db_path)
    try:
        side.execute("UPDATE ai_analysis SET payload_json = '{broken'")
        side.commit()
    finally:
        side.close()
    got = tmp_db.get_ai_analysis("summary", "streamer", "alice")
    assert got is not None
    assert got["payload"] is None
    assert got["payload_unreadable"] is True


# ===== 映像job queue =====

@pytest.fixture
def recording_id(tmp_db, make_session):
    session_id = make_session("alice", status="connected")
    return tmp_db.create_recording(session_id, "alice", "/x/a.mp4", "a.mp4", "hd", 100.0)


def test_media_job_progress_is_clamped_and_completion_forces_full(tmp_db, recording_id):
    tmp_db.enqueue_media_job("j1", "burn", recording_id, params={"mode": "b"})
    tmp_db.start_media_job("j1")
    tmp_db.update_media_job_progress("j1", 150, "encoding")
    assert tmp_db.get_media_job("j1")["pct"] == 100
    tmp_db.update_media_job_progress("j1", -5, "encoding")
    job = tmp_db.get_media_job("j1")
    assert job["pct"] == 0
    assert job["state"] == "running"
    assert job["params"] == {"mode": "b"}

    tmp_db.finish_media_job("j1", "completed", result={"path": "/out.mp4"})
    job = tmp_db.get_media_job("j1")
    assert job["pct"] == 100
    assert job["result"] == {"path": "/out.mp4"}
    # stageは「いま何をしているか」なので終端では消す(『取り消し中…』が残らないこと)。
    assert job["stage"] == ""
    assert job["error"] is None


def test_finish_media_job_failure_keeps_progress_and_records_error(tmp_db, recording_id):
    tmp_db.enqueue_media_job("j1", "burn", recording_id)
    tmp_db.start_media_job("j1")
    tmp_db.update_media_job_progress("j1", 37, "encoding")
    tmp_db.finish_media_job("j1", "failed", error="ffmpeg died")
    job = tmp_db.get_media_job("j1")
    assert job["pct"] == 37
    assert job["state"] == "failed"
    assert job["error"] == "ffmpeg died"
    assert job["result"] == {}


def test_pending_media_job_for_matches_kind_and_ignores_finished(tmp_db, recording_id):
    tmp_db.enqueue_media_job("j1", "burn", recording_id)
    assert tmp_db.pending_media_job_for("burn", recording_id)["job_id"] == "j1"
    assert tmp_db.pending_media_job_for("upscale", recording_id) is None
    tmp_db.finish_media_job("j1", "completed")
    assert tmp_db.pending_media_job_for("burn", recording_id) is None


def test_next_pending_media_job_orders_by_priority_then_queue_time(tmp_db, recording_id):
    tmp_db.enqueue_media_job("low", "burn", recording_id, priority=0)
    tmp_db.enqueue_media_job("high", "burn", recording_id, priority=5)
    assert tmp_db.next_pending_media_job()["job_id"] == "high"
    tmp_db.start_media_job("high")
    assert tmp_db.next_pending_media_job()["job_id"] == "low"


def test_claim_takes_one_job_at_a_time_and_marks_it_running(tmp_db, recording_id,
                                                            make_session):
    """workerが複数居ても同じ行を2人が拾わないこと。選ぶのと掴むのが別呼び出しだと、
    その隙間に同じ録画へ2本のffmpegが走り、同じ出力fileを奪い合う。"""
    other = tmp_db.create_recording(make_session("b"), "b", "b.mp4", "b.mp4", "hd", 1.0)
    tmp_db.enqueue_media_job("low", "burn", other, priority=0)
    tmp_db.enqueue_media_job("high", "burn", recording_id, priority=5)

    first = tmp_db.claim_next_pending_media_job()
    assert first["job_id"] == "high"
    assert first["state"] == "running"
    assert first["started_at"]

    second = tmp_db.claim_next_pending_media_job()
    assert second["job_id"] == "low"

    assert tmp_db.claim_next_pending_media_job() is None


def test_claim_never_runs_two_jobs_for_the_same_recording(tmp_db, recording_id,
                                                          make_session):
    """同じ録画へ2本同時に出さない。再mp4化はmp4を作り直して差し替えるので、その裏で
    同じmp4を読んでいる焼き込みは途中で足元を抜かれる。"""
    other = tmp_db.create_recording(make_session("b"), "b", "b.mp4", "b.mp4", "hd", 1.0)
    # 同じ録画への2本は priority で順番を確定させる(queued_at はWindowsの時計分解能で
    # 同着になり得るため、順序の主張には使わない)。
    tmp_db.enqueue_media_job("burn", "overlay", recording_id, priority=9)
    tmp_db.enqueue_media_job("again", "reprocess", recording_id, priority=8)
    tmp_db.enqueue_media_job("other", "overlay", other, priority=1)

    assert tmp_db.claim_next_pending_media_job()["job_id"] == "burn"
    # 2本目は同じ録画のjobを飛ばして、別の録画へ進む。
    assert tmp_db.claim_next_pending_media_job()["job_id"] == "other"
    assert tmp_db.claim_next_pending_media_job() is None

    tmp_db.finish_media_job("burn", "completed")
    assert tmp_db.claim_next_pending_media_job()["job_id"] == "again"


def test_cancel_pending_media_job_refuses_running(tmp_db, recording_id):
    tmp_db.enqueue_media_job("j1", "burn", recording_id)
    tmp_db.start_media_job("j1")
    # 実行中はDB更新だけでは止まらないので取り消し対象外。
    assert tmp_db.cancel_pending_media_job("j1") is False
    assert tmp_db.get_media_job("j1")["state"] == "running"

    tmp_db.enqueue_media_job("j2", "burn", recording_id)
    assert tmp_db.cancel_pending_media_job("j2") is True
    assert tmp_db.get_media_job("j2")["state"] == "cancelled"
    assert tmp_db.cancel_pending_media_job("nope") is False


def test_interrupt_running_media_jobs_does_not_requeue(tmp_db, recording_id):
    tmp_db.enqueue_media_job("running", "burn", recording_id)
    tmp_db.enqueue_media_job("waiting", "burn", recording_id)
    tmp_db.start_media_job("running")
    interrupted = tmp_db.interrupt_running_media_jobs()
    assert [j["job_id"] for j in interrupted] == ["running"]
    # 中途の成果物が残り得るため、pendingへ戻して自動再実行してはいけない。
    assert tmp_db.get_media_job("running")["state"] == "interrupted"
    assert tmp_db.get_media_job("running")["error"]
    assert tmp_db.get_media_job("waiting")["state"] == "pending"


def test_prune_media_jobs_keeps_active_rows_and_honours_disabled(tmp_db, recording_id):
    tmp_db.enqueue_media_job("old", "burn", recording_id)
    tmp_db.finish_media_job("old", "completed")
    tmp_db.enqueue_media_job("pending", "burn", recording_id)
    tmp_db.enqueue_media_job("running", "burn", recording_id)
    tmp_db.start_media_job("running")

    assert tmp_db.prune_media_jobs(0) == 0
    assert tmp_db.prune_media_jobs(-1) == 0
    assert tmp_db.get_media_job("old") is not None

    # Windowsのtime.time()は分解能が粗い(約16ms)。閾値はそれより大きく取る。
    time.sleep(0.05)
    assert tmp_db.prune_media_jobs(0.01) == 1
    assert tmp_db.get_media_job("old") is None
    assert tmp_db.get_media_job("pending") is not None
    assert tmp_db.get_media_job("running") is not None


def test_media_jobs_cascade_when_recording_is_deleted(tmp_db, recording_id):
    tmp_db.enqueue_media_job("j1", "burn", recording_id)
    assert tmp_db.delete_recording(recording_id) is not None
    # 孤児jobを残すとworkerが存在しない録画をpickして失敗し続ける。
    assert tmp_db.get_media_job("j1") is None


# ===== 一括転写queue =====

def test_enqueue_transcriptions_skips_active_and_revives_failed(tmp_db, recording_id):
    assert tmp_db.enqueue_transcriptions([(recording_id, "alice")]) == 1
    # pending中の再投入は待ち行列を膨らませない。
    assert tmp_db.enqueue_transcriptions([(recording_id, "alice")]) == 0
    tmp_db.set_transcription_state(recording_id, "running")
    assert tmp_db.enqueue_transcriptions([(recording_id, "alice")]) == 0

    tmp_db.set_transcription_state(recording_id, "failed", error="boom")
    assert tmp_db.enqueue_transcriptions([(recording_id, "alice")], priority=3) == 1
    row = tmp_db.next_pending_transcription()
    assert row["state"] == "pending"
    assert row["priority"] == 3
    assert row["error"] is None
    assert row["pct"] == 0


def test_set_transcription_state_done_forces_full_pct(tmp_db, recording_id):
    tmp_db.enqueue_transcriptions([(recording_id, "alice")])
    tmp_db.set_transcription_state(recording_id, "running")
    tmp_db.update_transcription_pct(recording_id, 40)
    tmp_db.set_transcription_state(recording_id, "done")
    item = tmp_db.list_transcribe_queue()[0]
    assert item["state"] == "done"
    assert item["pct"] == 100
    assert item["finished_at"] is not None
    assert tmp_db.next_pending_transcription() is None


def test_cancel_transcriptions_only_touches_pending(tmp_db, make_session):
    session_id = make_session("alice", status="connected")
    rec_a = tmp_db.create_recording(session_id, "alice", "/a.mp4", "a.mp4", "hd", 1.0)
    rec_b = tmp_db.create_recording(session_id, "alice", "/b.mp4", "b.mp4", "hd", 2.0)
    tmp_db.enqueue_transcriptions([(rec_a, "alice"), (rec_b, "alice")])
    tmp_db.set_transcription_state(rec_a, "running")

    assert tmp_db.cancel_transcriptions() == 1
    assert tmp_db.count_transcribe_queue_by_state() == {"running": 1, "cancelled": 1}
    # runningはSTT実行中で止める手段が無いので、再起動時にpendingへ戻す。
    assert tmp_db.reset_running_transcriptions() == 1
    assert tmp_db.count_transcribe_queue_by_state() == {"pending": 1, "cancelled": 1}


def test_untranscribed_recordings_excludes_queued_and_unfinished(tmp_db, make_session):
    session_id = make_session("alice", status="connected")
    done = tmp_db.create_recording(session_id, "alice", "/a.mp4", "a.mp4", "hd", 1.0)
    queued = tmp_db.create_recording(session_id, "alice", "/b.mp4", "b.mp4", "hd", 2.0)
    fresh = tmp_db.create_recording(session_id, "alice", "/c.mp4", "c.mp4", "hd", 3.0)
    other = tmp_db.create_recording(session_id, "bob", "/d.mp4", "d.mp4", "hd", 4.0)
    for rid in (done, queued, fresh, other):
        tmp_db.update_recording(rid, "completed", "/x", "x.mp4", 10.0, 1)
    # 未完了の録画は候補にしない。
    still_recording = tmp_db.create_recording(session_id, "alice", "/e.mp4", "e.mp4",
                                              "hd", 5.0)
    tmp_db.save_transcript(done, {"text": "t", "segments": []})
    tmp_db.enqueue_transcriptions([(queued, "alice")])

    assert {r["id"] for r in tmp_db.untranscribed_recordings("alice")} == {fresh}
    all_ids = {r["id"] for r in tmp_db.untranscribed_recordings()}
    assert other in all_ids
    assert still_recording not in all_ids


# ===== 録画 / 転写 =====

def test_update_rebuilt_recording_never_moves_ended_at(tmp_db, make_session):
    """作り直しは捕捉が終わった時刻を動かさない。

    復旧と再mp4化がupdate_recordingを流用し、Recorder._finalizeが打つ「今」をended_atへ
    書き戻していたため、DBの尺が「録画開始〜再処理時刻」に化けていた。"""
    session_id = make_session("alice", status="connected")
    rec = tmp_db.create_recording(session_id, "alice", "/a.mp4", "a.mp4", "hd", 1000.0)
    tmp_db.update_recording(rec, "completed", "/a.mp4", "a.mp4", 1300.0, 100)

    tmp_db.update_rebuilt_recording(rec, "completed", "/b.mp4", "b.mp4", 200,
                                    duration_seconds=280.0,
                                    ended_at_if_missing=9_999_999.0)

    row = tmp_db.get_recording(rec)
    assert row["ended_at"] == 1300.0
    assert row["path"] == "/b.mp4"
    assert row["bytes"] == 200
    assert row["duration_seconds"] == 280.0


def test_update_rebuilt_recording_fills_only_a_missing_ended_at(tmp_db, make_session):
    """中断のまま終わってended_atを持たない行だけは埋める。"""
    session_id = make_session("alice", status="connected")
    rec = tmp_db.create_recording(session_id, "alice", "/a.mp4", "a.mp4", "hd", 1000.0)

    tmp_db.update_rebuilt_recording(rec, "completed", "/a.mp4", "a.mp4", 10,
                                    ended_at_if_missing=1250.0)

    assert tmp_db.get_recording(rec)["ended_at"] == 1250.0


def test_measured_duration_survives_an_update_that_could_not_measure(tmp_db, make_session):
    """尺を測れなかった書き戻しが、測れていた値を消してはいけない。

    Noneは「据え置き」であって「不明で上書き」ではない(ffprobeが一時的に無い環境で
    再mp4化を通すと、それまでの実測が消える)。"""
    session_id = make_session("alice", status="connected")
    rec = tmp_db.create_recording(session_id, "alice", "/a.mp4", "a.mp4", "hd", 1000.0)
    tmp_db.update_recording(rec, "completed", "/a.mp4", "a.mp4", 1300.0, 100,
                            duration_seconds=280.0)

    tmp_db.update_recording(rec, "completed", "/a.mp4", "a.mp4", 1300.0, 100)
    assert tmp_db.get_recording(rec)["duration_seconds"] == 280.0

    tmp_db.update_rebuilt_recording(rec, "completed", "/a.mp4", "a.mp4", 100)
    assert tmp_db.get_recording(rec)["duration_seconds"] == 280.0


def test_set_recording_duration_refuses_a_zero_measurement(tmp_db, make_session):
    """尺0の録画は存在しない。0は測定失敗なので、実測値を潰させない。"""
    session_id = make_session("alice", status="connected")
    rec = tmp_db.create_recording(session_id, "alice", "/a.mp4", "a.mp4", "hd", 1000.0)

    assert tmp_db.set_recording_duration(rec, 42.0) is True
    assert tmp_db.set_recording_duration(rec, 0.0) is False
    assert tmp_db.get_recording(rec)["duration_seconds"] == 42.0


def test_mark_stale_recordings_marks_only_in_flight(tmp_db, make_session):
    session_id = make_session("alice", status="connected")
    live = tmp_db.create_recording(session_id, "alice", "/a.mp4", "a.mp4", "hd", 1.0)
    done = tmp_db.create_recording(session_id, "alice", "/b.mp4", "b.mp4", "hd", 2.0)
    tmp_db.update_recording(done, "completed", "/b.mp4", "b.mp4", 5.0, 100)

    assert tmp_db.mark_stale_recordings() == 1
    assert tmp_db.get_recording(live)["status"] == "interrupted"
    assert tmp_db.get_recording(done)["status"] == "completed"
    assert [r["id"] for r in tmp_db.recordings_for_recovery()] == [live]
    assert tmp_db.mark_stale_recordings() == 0


def test_transcript_roundtrip_and_cascade_on_recording_delete(tmp_db, make_session):
    session_id = make_session("alice", status="connected")
    rec = tmp_db.create_recording(session_id, "alice", "/a.mp4", "a.mp4", "hd", 1.0)
    tmp_db.save_transcript(rec, {"language": "ja", "model": "large", "text": "hello",
                                 "segments": [{"start": 0.0, "end": 1.0, "text": "hi"}],
                                 "duration": 12.5, "timemap_version": 2,
                                 "timemap_anchors": 3, "timemap_drift_seconds": 0.5})
    got = tmp_db.get_transcript(rec)
    assert got["segments"] == [{"start": 0.0, "end": 1.0, "text": "hi"}]
    assert got["timemap_version"] == 2
    assert tmp_db.transcribed_recording_ids() == {rec}

    # 上書き保存は差し替え(重複行を作らない)。
    tmp_db.save_transcript(rec, {"text": "redo", "segments": []})
    assert tmp_db.get_transcript(rec)["text"] == "redo"

    tmp_db.delete_recording(rec)
    assert tmp_db.get_transcript(rec) is None


def test_set_recording_protected_reports_missing_row(tmp_db, make_session):
    session_id = make_session("alice", status="connected")
    rec = tmp_db.create_recording(session_id, "alice", "/a.mp4", "a.mp4", "hd", 1.0)
    assert tmp_db.set_recording_protected(rec, True) is True
    assert tmp_db.get_recording(rec)["protected"] == 1
    assert tmp_db.set_recording_protected(rec, False) is True
    assert tmp_db.get_recording(rec)["protected"] == 0
    assert tmp_db.set_recording_protected(999999, True) is False


# ===== 横断検索index =====

def test_replace_search_hits_drops_stale_fts_entries(tmp_db, make_session):
    session_id = make_session("alice", status="connected")
    rec = tmp_db.create_recording(session_id, "alice", "/a.mp4", "a.mp4", "hd", 1.0)
    row = {"unique_id": "alice", "started_at": 1.0, "video_time": 3.0,
           "session_id": session_id, "body": "hello world"}
    assert tmp_db.replace_search_hits(rec, "comment", [row]) == 1
    assert tmp_db.search_scenes("hello", ["comment"])["total"] == 1

    tmp_db.replace_search_hits(rec, "comment", [dict(row, body="goodbye moon")])
    # external content FTSはcontent表のDELETEだけでは索引が残る(=消したはずの語が引ける)。
    assert tmp_db.search_scenes("hello", ["comment"])["total"] == 0
    assert tmp_db.search_scenes("goodbye", ["comment"])["total"] == 1
    assert tmp_db.search_indexed_counts()[rec] == {"comment": 1}


def test_search_scenes_falls_back_to_like_for_short_terms(tmp_db, make_session):
    session_id = make_session("alice", status="connected")
    rec = tmp_db.create_recording(session_id, "alice", "/a.mp4", "a.mp4", "hd", 1.0)
    tmp_db.replace_search_hits(rec, "stt", [
        {"unique_id": "alice", "started_at": 1.0, "video_time": 3.0,
         "session_id": session_id, "body": "配信ありがとう"},
    ])
    # trigramは3文字未満のtokenを作らないので2文字queryはLIKE走査へ落ちる。
    short = tmp_db.search_scenes("配信", ["stt"])
    assert short["mode"] == "like"
    assert short["total"] == 1
    long_q = tmp_db.search_scenes("ありがとう", ["stt"])
    assert long_q["mode"] == "fts"
    assert long_q["total"] == 1


def test_search_scenes_degrades_gracefully_on_empty_or_bad_query(tmp_db):
    assert tmp_db.search_scenes("hello", [])["total"] == 0
    # 除外語だけの入力はerrorではなく空 + hintで返す(画面が落ちない)。
    bad = tmp_db.search_scenes("-hello", ["comment"])
    assert bad["total"] == 0
    assert bad["hint"]


# ===== settings / 監視対象 =====

def test_add_monitored_target_preserves_existing_record_video_preference(tmp_db):
    tmp_db.add_monitored_target("alice", record_video=True)
    tmp_db.set_target_record_video("alice", False)
    # 監視の再起動で設定を踏み潰さない。
    tmp_db.add_monitored_target("alice", record_video=True)
    assert tmp_db.get_target_record_video("alice") is False

    tmp_db.remove_monitored_target("alice")
    # 未登録は録画するのが既定。
    assert tmp_db.get_target_record_video("alice") is True
    tmp_db.add_monitored_target("alice", record_video=True)
    assert tmp_db.list_monitored_targets() == [{"unique_id": "alice", "record_video": True}]


def test_set_settings_upserts_and_stringifies(tmp_db):
    tmp_db.set_settings({"a": 1, "b": "x"})
    tmp_db.set_settings({"a": 2})
    stored = tmp_db.get_settings()
    assert stored["a"] == "2"
    assert stored["b"] == "x"


def test_storage_scan_is_none_until_first_scan(tmp_db):
    assert tmp_db.get_storage_scan() is None
    tmp_db.save_storage_scan({"total": 10}, 123.0)
    tmp_db.save_storage_scan({"total": 20}, 456.0)
    got = tmp_db.get_storage_scan()
    assert got["usage"] == {"total": 20}
    assert got["duration_ms"] == 456.0


# ===== 切り出し / 見どころ =====

def test_cut_list_add_delete_and_clear(tmp_db, make_session):
    session_id = make_session("alice", status="connected")
    rec = tmp_db.create_recording(session_id, "alice", "/a.mp4", "a.mp4", "hd", 1.0)
    cut = tmp_db.add_cut(rec, "alice", 10.0, 20.0, "good")
    assert cut["start"] == 10.0
    assert cut["label"] == "good"
    tmp_db.add_cut(rec, "alice", 30.0, 40.0)
    assert len(tmp_db.list_cuts()) == 2
    assert tmp_db.delete_cut(cut["id"]) is True
    assert tmp_db.delete_cut(cut["id"]) is False
    assert tmp_db.clear_cuts() == 1
    assert tmp_db.list_cuts() == []


def test_bookmark_point_keeps_null_end_and_memo_is_editable(tmp_db, make_session):
    session_id = make_session("alice", status="connected")
    rec = tmp_db.create_recording(session_id, "alice", "/a.mp4", "a.mp4", "hd", 1.0)
    point = tmp_db.add_bookmark(rec, "alice", 5.0)
    span = tmp_db.add_bookmark(rec, "alice", 8.0, end=12.0, memo="range")
    # end IS NULL が点、endを持てば範囲。
    assert point["end"] is None
    assert span["end"] == 12.0

    assert tmp_db.update_bookmark_memo(point["id"], "later")["memo"] == "later"
    assert tmp_db.update_bookmark_memo(999999, "x") is None
    assert [b["id"] for b in tmp_db.list_bookmarks(rec)] == [point["id"], span["id"]]
    assert tmp_db.delete_bookmark(point["id"]) is True
    assert tmp_db.delete_bookmark(point["id"]) is False


# ===== close時の最終drain =====

def test_close_flushes_buffered_events(tmp_db, tmp_db_path, make_session, event_builder):
    """closeはwriter停止後に最終drainを走らせる。buffer滞留分を落とさないこと。"""
    session_id = make_session("alice", status="connected")
    for i in range(3):
        tmp_db.add_event(session_id, event_builder("comment", at=500.0 + i))
    tmp_db.close()

    side = _side_conn(tmp_db_path)
    try:
        n = side.execute(
            "SELECT COUNT(*) n FROM events WHERE session_id = ?", (session_id,)
        ).fetchone()["n"]
    finally:
        side.close()
    assert n == 3


# ===== 未監視配信者の発見(discovery) =====

def _battle(battle_id, start_time, opponents):
    return {
        "battle_id": battle_id,
        "start_time": start_time,
        "opponents": [
            {"unique_id": handle, "nickname": handle.upper(), "avatar": "", "user_id": ""}
            for handle in opponents
        ],
    }


def test_discovery_ranks_by_time_decayed_contact_count(tmp_db, make_session):
    """順位は生の対戦数ではなく時間減衰つきの和。回数で劣る直近の相手が、
    古いだけの多数回の相手を上回ること(この逆転こそが減衰を入れる理由)。"""
    now = time.time()
    session_id = make_session("owner")
    battles = []
    # stale: 4戦だが全て半減期4つぶん(112日)前 → 重みは 4 * 0.0625 = 0.25
    battles += [_battle(100 + i, now - 112 * 86400, ["stale"]) for i in range(4)]
    # fresh: 2戦だが直近 → 重みはほぼ 2.0
    battles += [_battle(200 + i, now - 3600, ["fresh"]) for i in range(2)]
    tmp_db.save_battles(session_id, battles)

    result = tmp_db.discovery_candidates(min_contacts=2, half_life_days=28.0, limit=10)
    handles = [c["unique_id"] for c in result["candidates"]]
    assert handles == ["fresh", "stale"]
    by_handle = {c["unique_id"]: c for c in result["candidates"]}
    assert by_handle["stale"]["contacts"] == 4
    assert by_handle["fresh"]["contacts"] == 2
    assert by_handle["fresh"]["score"] > by_handle["stale"]["score"]


def test_discovery_excludes_monitored_and_dismissed(tmp_db, make_session):
    now = time.time()
    session_id = make_session("owner")
    tmp_db.save_battles(
        session_id,
        [_battle(i, now - 3600, ["rival", "friend", "other"]) for i in range(1, 4)],
    )
    assert {c["unique_id"] for c in
            tmp_db.discovery_candidates(3, 14.0, 10)["candidates"]} == {"rival", "friend", "other"}

    # 監視へ昇格した相手は候補から外れる(既存のmonitored_targetsが唯一の判定元)。
    tmp_db.add_monitored_target("rival", record_video=True)
    # 却下した相手も外れる。候補は毎回導出するので、記録しないと出続ける。
    tmp_db.dismiss_discovery_candidate("friend")
    result = tmp_db.discovery_candidates(3, 14.0, 10)
    assert [c["unique_id"] for c in result["candidates"]] == ["other"]
    assert result["dismissed"] == 1

    # 却下は取り消せる。
    tmp_db.restore_discovery_candidate("friend")
    assert {c["unique_id"] for c in
            tmp_db.discovery_candidates(3, 14.0, 10)["candidates"]} == {"friend", "other"}
    assert tmp_db.list_dismissed_candidates() == []


def test_discovery_counts_a_battle_once_per_opponent_across_observers(tmp_db, make_session):
    """同じBattleを複数の監視配信者が別sessionで観測しても接触は1回。
    素直に数えると同陣営に2人監視しているだけで対戦数が倍に化ける。"""
    now = time.time()
    for owner in ("owner_a", "owner_b"):
        session_id = make_session(owner)
        tmp_db.save_battles(session_id, [_battle(9001, now - 3600, ["rival"])])

    result = tmp_db.discovery_candidates(min_contacts=1, half_life_days=14.0, limit=10)
    assert [c["unique_id"] for c in result["candidates"]] == ["rival"]
    assert result["candidates"][0]["contacts"] == 1
    # どの監視配信者の相手だったかは両方残す(候補を見て判断する材料になる)。
    assert result["candidates"][0]["via"] == ["owner_a", "owner_b"]


def test_discovery_skips_opponents_without_handle(tmp_db, make_session):
    """unique_idが無い相手は監視を開始する手段が無いので候補にしない。
    nicknameで代用すると昇格できない候補が並ぶ。"""
    now = time.time()
    session_id = make_session("owner")
    tmp_db.save_battles(
        session_id,
        [{"battle_id": 1, "start_time": now - 3600,
          "opponents": [{"unique_id": "", "nickname": "名無し"},
                        {"unique_id": "named", "nickname": "Named"}]}],
    )
    result = tmp_db.discovery_candidates(min_contacts=1, half_life_days=14.0, limit=10)
    assert [c["unique_id"] for c in result["candidates"]] == ["named"]
    assert result["skipped_unidentified"] == 1


def test_discovery_skips_battles_missing_time_or_id(tmp_db, make_session):
    """start_time/battle_idはどちらも減衰と重複除外に必須。欠けた記録に代わりの値を
    当てると、実際には無かった接触を作ることになるので数えない。"""
    now = time.time()
    session_id = make_session("owner")
    tmp_db.save_battles(
        session_id,
        [
            {"battle_id": 0, "start_time": now, "opponents": [{"unique_id": "a"}]},
            {"battle_id": 5, "start_time": None, "opponents": [{"unique_id": "b"}]},
            _battle(6, now - 3600, ["c"]),
        ],
    )
    result = tmp_db.discovery_candidates(min_contacts=1, half_life_days=14.0, limit=10)
    assert [c["unique_id"] for c in result["candidates"]] == ["c"]
    assert result["skipped_incomplete"] == 2


def test_discovery_limit_caps_rows_but_reports_full_eligible_count(tmp_db, make_session):
    """件数制限は表示だけを絞る。総数を返さないと「これで全部」と読めてしまう。"""
    now = time.time()
    session_id = make_session("owner")
    tmp_db.save_battles(
        session_id,
        [_battle(i, now - 3600, [f"rival{i:02d}"]) for i in range(1, 21)],
    )
    result = tmp_db.discovery_candidates(min_contacts=1, half_life_days=14.0, limit=5)
    assert len(result["candidates"]) == 5
    assert result["eligible"] == 20
    assert result["seen"] == 20


def test_discovery_rejects_non_positive_half_life(tmp_db):
    with pytest.raises(ValueError):
        tmp_db.discovery_candidates(min_contacts=1, half_life_days=0.0, limit=5)


# ===== Fan台帳 =====

def _gift(gift_builder, key, diamonds, at, repeat=1):
    """identity_keyがuser_idから決まることを利用して、視聴者を数値IDで作り分ける。"""
    return gift_builder(
        diamonds=diamonds, repeat_count=repeat, at=at,
        user={"user_id": key, "unique_id": f"handle{key}", "nickname": f"Fan {key}",
              "avatar": "", "fans_level": 0, "gifter_level": 0,
              "gifter_badge": "", "member_badge": ""},
    )


def test_fan_ledger_aggregates_across_streamers_with_per_streamer_split(
    tmp_db, make_session, gift_builder
):
    """台帳は配信者を跨いで合算し、内訳を額つきで返す。額を伏せて「2人へ投げた」とだけ
    出すと、3コインの相手も本命と同格に見えてしまう。"""
    a = make_session("ownerA")
    b = make_session("ownerB")
    tmp_db.add_event(a, _gift(gift_builder, "7001", 1000, at=100.0))
    tmp_db.add_event(a, _gift(gift_builder, "7001", 500, at=200.0))
    tmp_db.add_event(b, _gift(gift_builder, "7001", 3, at=300.0))
    tmp_db.add_event(b, _gift(gift_builder, "7002", 50, at=400.0))
    tmp_db.flush()

    result = tmp_db.fan_ledger(min_diamonds=0, limit=10)
    assert [f["identity_key"] for f in result["fans"]] == ["7001", "7002"]
    top = result["fans"][0]
    assert top["diamonds"] == 1503
    assert top["sessions"] == 2
    assert top["streamer_count"] == 2
    # 内訳は額の降順。偏りが読み取れること。
    assert [(s["unique_id"], s["diamonds"]) for s in top["streamers"]] == [
        ("ownerA", 1500), ("ownerB", 3),
    ]
    assert result["total_gifters"] == 2
    assert result["multi_streamer"] == 1


def test_fan_ledger_excludes_non_identity_keys(tmp_db, make_session, gift_builder, event_builder):
    """'(unknown)' と空keyは1人の視聴者ではない。台帳に並べると巨大な偽fanになる。
    除外した分は黙って消さず、件数と額を返す。"""
    session_id = make_session("owner")
    tmp_db.add_event(session_id, _gift(gift_builder, "7001", 100, at=100.0))
    for key in ("", "(unknown)"):
        # identity_keyはuser dict側で指定する(collectorが決めた値をstorageが尊重する経路)。
        tmp_db.add_event(session_id, gift_builder(
            diamonds=9999, at=200.0,
            user={"user_id": "", "unique_id": "", "nickname": key, "avatar": "",
                  "fans_level": 0, "gifter_level": 0, "gifter_badge": "",
                  "member_badge": "", "identity_key": key},
        ))
    tmp_db.flush()

    result = tmp_db.fan_ledger(min_diamonds=0, limit=10)
    assert [f["identity_key"] for f in result["fans"]] == ["7001"]
    assert all(f["identity_key"] not in ("", "(unknown)") for f in result["fans"])
    # 除外分が見えること(合計が合わない理由を画面から辿れるようにするため)。
    assert result["unidentified"]["gift_events"] == 2
    assert result["unidentified"]["diamonds"] == 19998


def test_fan_ledger_totals_reconcile_with_gift_events(tmp_db, make_session, gift_builder):
    """台帳の合計 + 除外分 = gift eventの総額。(identity, 配信者)で割って畳む集計が
    coinを取りこぼしても二重計上してもいないことの検算。"""
    a = make_session("ownerA")
    b = make_session("ownerB")
    for i, (session_id, key, coins) in enumerate([
        (a, "7001", 100), (a, "7002", 250), (b, "7001", 70), (b, "7003", 5),
        (a, "7001", 30), (b, "7002", 8),
    ]):
        tmp_db.add_event(session_id, _gift(gift_builder, key, coins, at=100.0 + i))
    tmp_db.flush()

    result = tmp_db.fan_ledger(min_diamonds=0, limit=100)
    ledger_total = sum(f["diamonds"] for f in result["fans"])
    assert ledger_total + result["unidentified"]["diamonds"] == 463


def test_fan_ledger_threshold_and_limit_report_full_counts(tmp_db, make_session, gift_builder):
    """閾値と件数制限は表示を絞るだけ。総数を返さないと「これで全部」と読める。"""
    session_id = make_session("owner")
    for i in range(10):
        tmp_db.add_event(session_id, _gift(gift_builder, f"70{i:02d}", (i + 1) * 100, at=100.0 + i))
    tmp_db.flush()

    result = tmp_db.fan_ledger(min_diamonds=500, limit=3)
    assert len(result["fans"]) == 3
    assert result["eligible"] == 6
    assert result["total_gifters"] == 10
    # 上位から順に出ること。
    assert [f["diamonds"] for f in result["fans"]] == [1000, 900, 800]


def test_fan_ledger_prefers_users_table_handle_over_stale_event_handle(
    tmp_db, make_session, gift_builder
):
    """表示handleはusers表(最新へupsertされる)を優先する。eventのMAX()は辞書順の最大を
    拾うだけで、実測では改名前の自動生成handleが現handleを押しのけた。"""
    session_id = make_session("owner")
    tmp_db.add_event(session_id, gift_builder(
        diamonds=10, at=100.0,
        user={"user_id": "7001", "unique_id": "zzz_old_handle", "nickname": "Old",
              "avatar": "", "fans_level": 0, "gifter_level": 0,
              "gifter_badge": "", "member_badge": ""},
    ))
    tmp_db.add_event(session_id, gift_builder(
        diamonds=10, at=200.0,
        user={"user_id": "7001", "unique_id": "current_handle", "nickname": "Now",
              "avatar": "", "fans_level": 0, "gifter_level": 0,
              "gifter_badge": "", "member_badge": ""},
    ))
    tmp_db.flush()

    fan = tmp_db.fan_ledger(min_diamonds=0, limit=10)["fans"][0]
    assert fan["unique_id"] == "current_handle"


def test_fan_profile_returns_session_ledger_not_raw_events(tmp_db, make_session, gift_builder):
    """明細はSession粒度まで畳んだもの。実測で最上位のfanは47,000行(大半like)を持ち、
    生eventを返すのは一覧としても転送量としても成立しない。"""
    a = make_session("ownerA")
    b = make_session("ownerB")
    tmp_db.add_event(a, _gift(gift_builder, "7001", 100, at=100.0))
    tmp_db.add_event(a, _gift(gift_builder, "7001", 200, at=150.0))
    tmp_db.add_event(b, _gift(gift_builder, "7001", 40, at=300.0))
    tmp_db.flush()

    profile = tmp_db.fan_profile("7001")
    assert profile["diamonds"] == 340
    assert [s["unique_id"] for s in profile["streamers"]] == ["ownerA", "ownerB"]
    assert profile["streamers"][0]["diamonds"] == 300
    assert len(profile["sessions"]) == 2
    assert "events" not in profile
    # 窓の両端が畳まれていること。
    own_a = next(s for s in profile["streamers"] if s["unique_id"] == "ownerA")
    assert own_a["first_gift"] == 100.0 and own_a["last_gift"] == 150.0


def test_fan_profile_rejects_non_identity_and_reports_missing(tmp_db):
    for key in ("", "(unknown)"):
        with pytest.raises(ValueError):
            tmp_db.fan_profile(key)
    assert tmp_db.fan_profile("no-such-identity") == {}


# ===== live見どころ(wall-clock -> PTS再map) =====

def _recording(tmp_db, session_id, unique_id="alice", started_at=1000.0):
    return tmp_db.create_recording(session_id, unique_id, "/a.mp4", "a.mp4", "hd", started_at)


def test_live_bookmark_is_stored_unmapped_with_its_wall_clock(tmp_db, make_session):
    """押下時に確定できるのはwall-clockだけ。startは暫定値で、pts_mapped=0が
    「まだmp4のPTS軸ではない」ことを示す。"""
    session_id = make_session("alice")
    rec = _recording(tmp_db, session_id, started_at=1000.0)
    bm = tmp_db.add_live_bookmark(rec, "alice", wall_time=1300.0,
                                  provisional_start=300.0, memo="いい場面")
    assert bm["live_wall"] == 1300.0
    assert bm["start"] == 300.0
    assert bm["pts_mapped"] == 0
    assert bm["memo"] == "いい場面"
    assert bm["end"] is None
    assert [b["id"] for b in tmp_db.list_unmapped_bookmarks(rec)] == [bm["id"]]


def test_apply_bookmark_pts_confirms_only_what_was_remapped(tmp_db, make_session):
    """再mapできた行だけが確定する。渡さなかった行は暫定のまま残り、
    画面が「これは暫定値」と言い続けられる。"""
    session_id = make_session("alice")
    rec = _recording(tmp_db, session_id)
    a = tmp_db.add_live_bookmark(rec, "alice", 1300.0, 300.0)
    b = tmp_db.add_live_bookmark(rec, "alice", 1400.0, 400.0)

    assert tmp_db.apply_bookmark_pts([(a["id"], 315.5)]) == 1
    remaining = tmp_db.list_unmapped_bookmarks(rec)
    assert [r["id"] for r in remaining] == [b["id"]]
    rows = {r["id"]: r for r in tmp_db.list_bookmarks(rec)}
    assert rows[a["id"]]["start"] == pytest.approx(315.5)
    assert rows[a["id"]]["pts_mapped"] == 1
    assert rows[b["id"]]["start"] == 400.0
    assert rows[b["id"]]["pts_mapped"] == 0
    assert tmp_db.apply_bookmark_pts([]) == 0


def test_bookmarks_made_from_video_time_are_already_mapped(tmp_db, make_session):
    """/videosから作る既存経路はstartが最初からPTS軸。live_wall無し・pts_mapped=1で、
    finalizeの再map対象に混ざらないこと。"""
    session_id = make_session("alice")
    rec = _recording(tmp_db, session_id)
    bm = tmp_db.add_bookmark(rec, "alice", 12.5, end=20.0, memo="後から")
    assert bm["live_wall"] is None
    assert bm["pts_mapped"] == 1
    assert tmp_db.list_unmapped_bookmarks(rec) == []


# ===== 表示handleの解決: 通算集計はusers表、session単位はpoint-in-time =====


def _renamed_gifter(tmp_db, gift_builder, session_id, *, old="zzz_old_handle",
                    new="aaa_new_handle", user_id="7300000000000000009"):
    """同じuser_idで改名した視聴者。MAX()は辞書順最大(=old)を拾うため、
    users表(最新=new)と食い違う。実DBで踏んだのと同じ形。"""
    def _user(handle, nickname):
        return {"user_id": user_id, "unique_id": handle, "nickname": nickname,
                "avatar": "", "fans_level": 0, "gifter_level": 0,
                "gifter_badge": "", "member_badge": ""}

    tmp_db.add_event(session_id, gift_builder(
        diamonds=10, at=100.0, user=_user(old, "Old Name")))
    tmp_db.add_event(session_id, gift_builder(
        diamonds=10, at=200.0, user=_user(new, "New Name")))
    tmp_db.flush()


def test_streamer_profile_shows_the_current_handle_not_the_lexicographic_max(
    tmp_db, make_session, gift_builder
):
    """配信者profileのgifterはsessionを跨ぐ通算集計なので、最新の身元で出すこと。

    MAX(e.user_unique_id)は辞書順の最大を返すだけで「最新のhandle」ではない。実DBでは
    改名前の自動生成handle(user5037930325926)が現handle(harehare12345)を押しのけていた。
    """
    session_id = make_session("streamer")
    tmp_db.update_session(session_id, "ended")
    _renamed_gifter(tmp_db, gift_builder, session_id)

    gifters = tmp_db.streamer_profile("streamer")["gifters"]
    top = next(g for g in gifters if g["user_id"] == "7300000000000000009")
    assert top["unique_id"] == "aaa_new_handle"
    assert top["nickname"] == "New Name"
    # 辞書順最大(old)を拾っていないこと。
    assert top["unique_id"] != "zzz_old_handle"


def test_aggregate_dashboard_shows_the_current_handle(tmp_db, make_session, gift_builder):
    """全体dashboardも通算集計なので同じ規則。"""
    session_id = make_session("streamer")
    tmp_db.update_session(session_id, "ended")
    _renamed_gifter(tmp_db, gift_builder, session_id)

    gifters = tmp_db.aggregate_dashboard()["top_gifters"]
    top = next(g for g in gifters if g["user_id"] == "7300000000000000009")
    assert top["unique_id"] == "aaa_new_handle"


def test_session_summary_keeps_the_point_in_time_view(tmp_db, make_session, gift_builder):
    """session単位の表示は「そのSessionでの見え方」を保つ(通算集計とは逆の規則)。

    users表(最新)を優先すると、過去のSessionを開いたときに当時と違うhandleが出る。
    ここはsessionのsnapshotなので、eventが持つ値を優先する既存の設計意図を維持する。
    """
    session_id = make_session("streamer")
    _renamed_gifter(tmp_db, gift_builder, session_id)

    users = tmp_db.session_summary(session_id)["users"]
    top = next(u for u in users if u["user_id"] == "7300000000000000009")
    # users表(最新)ではなくevent側の値であること。
    assert top["unique_id"] == "zzz_old_handle"


def test_gifter_user_id_is_unchanged_by_the_handle_rule(tmp_db, make_session, gift_builder):
    """user_idはbattle貢献の突合keyなので、解決規則を変えても値が動かないこと。

    identity_keyがuser_idそのものなので両方式は一致する(実DB1171人で差0を確認)。
    ここが動くとbattle_gift_contributionsの突合が変わる。
    """
    session_id = make_session("streamer")
    tmp_db.update_session(session_id, "ended")
    _renamed_gifter(tmp_db, gift_builder, session_id)

    profile_ids = {g["user_id"] for g in tmp_db.streamer_profile("streamer")["gifters"]}
    summary_ids = {u["user_id"] for u in tmp_db.session_summary(session_id)["users"]}
    assert "7300000000000000009" in profile_ids
    assert profile_ids == summary_ids


def test_levels_stay_point_in_time_in_cross_session_aggregates(
    tmp_db, make_session, gift_builder
):
    """Lv/badgeはusers表へ寄せない(観測していない過去の値を捏造しないため)。
    handleの規則を変えたときに巻き込んでいないことの確認。"""
    session_id = make_session("streamer")
    tmp_db.update_session(session_id, "ended")
    tmp_db.add_event(session_id, gift_builder(
        diamonds=10, at=100.0,
        user={"user_id": "7300000000000000010", "unique_id": "lvuser",
              "nickname": "Lv User", "avatar": "", "fans_level": 0,
              "gifter_level": 5, "gifter_badge": "", "member_badge": ""}))
    tmp_db.flush()

    users = tmp_db.session_summary(session_id)["users"]
    top = next(u for u in users if u["user_id"] == "7300000000000000010")
    assert top["gifter_level"] == 5
