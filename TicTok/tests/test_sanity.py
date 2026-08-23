import os
from pathlib import Path

from tictok.paths import PROJECT_ROOT


async def test_env_guard_keeps_paths_off_production(env_guard):
    for name in ("TICTOK_DB_PATH", "TICTOK_RECORD_DIR", "TICTOK_LOG_DIR", "TICTOK_JOURNAL_DIR"):
        value = Path(os.environ[name]).resolve()
        assert env_guard.resolve() in value.parents or value == env_guard.resolve()
        assert PROJECT_ROOT not in value.parents


def test_tmp_db_has_real_schema(tmp_db, db_read):
    names = {r[0] for r in db_read.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"sessions", "events", "users", "buckets"} <= names

    cols = {r["name"] for r in db_read.execute("PRAGMA table_info(events)")}
    from tictok.store._common import _events_insert_columns

    # 突き合わせるのは**DBへ書く列**であって、buffer/journalが運ぶ行の形
    # (_EVENTS_COLUMNS)ではない。internのCONTRACT以降は両者が食い違う — 生の
    # user_avatar はDBから消え、events側は user_avatar_id を持つ。
    missing = set(_events_insert_columns(tmp_db._intern_phase)) - cols
    assert not missing, f"migrations did not add: {sorted(missing)}"


def test_add_event_needs_flush_before_it_is_readable(
    tmp_db, db_read, make_session, gift_builder, env_guard
):
    session_id = make_session(unique_id="alice")
    tmp_db.add_event(session_id, gift_builder(gift_name="Galaxy", diamonds=1000))

    # 耐久journalは即書きだが、本番ではなくsandboxへ落ちていること。
    assert list((env_guard / "journal").glob("*")), "journal was not redirected into the sandbox"

    tmp_db.flush()
    row = db_read.execute(
        "SELECT kind, gift_name, diamonds FROM events WHERE session_id = ?", (session_id,)
    ).fetchone()
    assert (row["kind"], row["gift_name"], row["diamonds"]) == ("gift", "Galaxy", 1000)


def test_make_recording_follows_layout(tmp_root, make_recording):
    from tictok.core import layout

    stem, mp4 = make_recording(streamer="bob", when="20260101_120000")

    assert layout.streamer_of(stem) == "bob"
    assert mp4.parent == tmp_root / "bob" / "mp4"
    assert [p.name for p in layout.iter_sessions(tmp_root)] == [stem]
