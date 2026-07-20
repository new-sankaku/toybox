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
