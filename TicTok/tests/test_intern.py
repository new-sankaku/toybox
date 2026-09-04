"""eventsの重複文字列のintern(event_strings表とmigrationの2段階)。

この経路が壊れる壊れ方は「例外が出る」ではなく「avatarとbadgeが静かに消える」である。
id列が指す先が無ければJOINは黙ってNULLを返し、画面には既定のアイコンが並ぶだけで、
どこにもerrorは残らない。だからここで固定するのは主に次の4つになる:

  - 生の値がid経由で**元のまま**読み戻ること(NULLと空文字の区別を含む)
  - bufferとjournalは生の文字列を運び続けること。旧形式のjournalをreplayしたときに
    URL文字列がINTEGER列へ入る(SQLiteは動的型なので黙って通る)経路を作らない
  - 旧列を落とすのは全行の突き合わせが通ったときだけであること
  - rollbackで巻き戻ったidをcacheが持ち越さないこと
"""
import json
from pathlib import Path
import sqlite3

import pytest

from tictok.store import _common, maintenance
from tictok.storage import Storage


@pytest.fixture
def target_phase(monkeypatch):
    """段階の目標を、testが必要とする値へ固定する。

    `_INTERN_TARGET_PHASE` は**運用の進み具合で変わる値**である(EXPANDで止めて読み出しの
    書き換えを載せ、揃ってからCONTRACTへ上げる)。EXPAND段階そのものを確かめるtestが
    globalの値をそのまま使うと、目標が上がった日に「実装は正しいのにtestだけが落ちる」。
    段階を前提にするtestは必ずこれで自分の段階を宣言すること。
    """
    def _set(phase):
        monkeypatch.setattr(_common, "_INTERN_TARGET_PHASE", phase)
        monkeypatch.setattr(maintenance, "_INTERN_TARGET_PHASE", phase)
        return phase
    return _set


@pytest.fixture
def expand_db(tmp_db_path, target_phase):
    """EXPAND段階で止めたStorageを開くfactory。旧列とid列の両方が在る状態。"""
    target_phase(_common._INTERN_PHASE_EXPAND)
    opened = []

    def _open():
        storage = Storage(str(tmp_db_path))
        opened.append(storage)
        return storage
    try:
        yield _open
    finally:
        for storage in opened:
            storage.close()


def _avatar(n):
    """実物と同じ形の署名付きURL。長さも桁も本番に合わせる(短い文字列だと、重複が
    畳めているかどうかがbyteに現れない)。**collectorへ届く値**であって、保存される値では
    ない — 保存側は署名を落とす(_stored)。"""
    return (f"https://p16-common-sign.tiktokcdn.com/tos-alisg-avt-0068/{n:032x}"
            "~tplv-tiktok-shrink:72:72.webp?dr=14561&x-expires=1781874000"
            f"&x-signature=sig{n}%3D&t=4d5b0474&idc=my2")


def _stored(n):
    """_avatar(n) がDBへ入るときの形。署名queryを落としたpathだけが残る。

    これがbyte一致でないと、同じ画像が署名の本数ぶん別値として貯まる(署名を落とす理由その
    ものが失われる)。badgeには署名が付かないので、あちらは _avatar と違い落ちる部分が無い。"""
    return _avatar(n).partition("?")[0]


def _rows(conn):
    return conn.execute(
        "SELECT e.id, av.value AS avatar, gbv.value AS gifter_badge, mbv.value AS member_badge"
        " FROM events e"
        " LEFT JOIN event_strings av ON av.id = e.user_avatar_id"
        " LEFT JOIN event_strings gbv ON gbv.id = e.user_gifter_badge_id"
        " LEFT JOIN event_strings mbv ON mbv.id = e.user_member_badge_id"
        " ORDER BY e.id"
    ).fetchall()


# ===== 書き込み経路 =========================================================


def test_avatar_and_badges_round_trip_through_the_intern_table(
    tmp_db, db_read, make_session, event_builder
):
    """生の値 -> id -> 生の値。ここが1文字でも変われば解析の入力が変わる。"""
    session_id = make_session()
    user = event_builder.user(
        avatar=_avatar(1),
        gifter_badge="https://p16-webcast.tiktokcdn.com/webcast-va/lv30.png~tplv-obj.image",
        member_badge="https://p16-webcast.tiktokcdn.com/webcast-va/fans_lv40.png~tplv-obj.image",
    )
    tmp_db.add_event(session_id, event_builder("comment", user=user))
    tmp_db.flush()

    row = _rows(db_read)[0]
    assert row["avatar"] == _stored(1)
    assert "x-signature" not in row["avatar"]   # 署名は保存しない
    assert row["avatar"] != user["avatar"]      # 届いた値とは違う(落としている)
    assert row["gifter_badge"] == user["gifter_badge"]
    assert row["member_badge"] == user["member_badge"]


def test_the_same_string_is_stored_once_however_many_events_carry_it(
    tmp_db, db_read, make_session, event_builder
):
    """internの目的そのもの。同じURLの100 eventがintern表の1行に畳まれること。"""
    session_id = make_session()
    user = event_builder.user(avatar=_avatar(7))
    for _ in range(100):
        tmp_db.add_event(session_id, event_builder("like", user=user))
    tmp_db.flush()

    assert db_read.execute(
        "SELECT COUNT(*) FROM event_strings WHERE value = ?", (_stored(7),)
    ).fetchone()[0] == 1
    # 100行すべてが同じidを指す。
    assert db_read.execute(
        "SELECT COUNT(DISTINCT user_avatar_id) FROM events").fetchone()[0] == 1


def test_null_and_empty_string_stay_apart(tmp_db, db_read, make_session, event_builder):
    """NULL=計装前で未計測 / 空文字=届いたが空。同じNULLへ潰すと被覆率が出せなくなる。
    読み出し側の NULLIF(MAX(...), '') もこの区別に乗っている。"""
    session_id = make_session()
    tmp_db.add_event(session_id, event_builder("comment", user=event_builder.user(avatar=None)))
    tmp_db.add_event(session_id, event_builder("comment", user=event_builder.user(avatar="")))
    tmp_db.add_event(session_id, event_builder("comment", user=event_builder.user(avatar=_avatar(2))))
    tmp_db.flush()

    avatars = [r["avatar"] for r in _rows(db_read)]
    assert avatars == [None, "", _stored(2)]
    # NULLの行はid自体を持たない。空文字はintern表に1行を持つ。
    ids = [r[0] for r in db_read.execute("SELECT user_avatar_id FROM events ORDER BY id")]
    assert ids[0] is None and ids[1] is not None


def test_the_buffer_and_journal_keep_the_raw_string(
    tmp_db, make_session, event_builder, env_guard
):
    """**journalに載るのは生の文字列で、idではない。**

    idを載せると、そのjournalは event_strings と組でなければ意味を持たなくなる。
    復元は「DBが壊れた/欠けた」場面で走るので、DB側の表と組でしか読めない記録は
    最後の防波堤にならない。旧形式のreplayでURLがINTEGER列へ入る経路も同時に塞ぐ。
    """
    session_id = make_session()
    url = _avatar(3)
    tmp_db.add_event(session_id, event_builder("comment", user=event_builder.user(avatar=url)))

    lines = []
    # journalは専用threadが書くので、読む前に書き切りを待つ。
    assert tmp_db.wait_journal_idle()
    for path in sorted((env_guard / "journal").glob("events-*.jsonl")):
        lines += [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]
    events = [r["r"] for r in lines if r["t"] == "e"]
    assert len(events) == 1
    position = _common._EVENTS_COLUMNS.index("user_avatar")
    assert events[0][position] == url, "journalにidが載っている(生値でなければならない)"


def test_journal_recovery_interns_the_raw_rows(storage_with_journal, db_read_for):
    """復元経路も同じ名寄せを通ること。通さないとURLがINTEGER列へ黙って入り、
    以後JOINが一致せずavatarが消える。"""
    storage, journal_dir = storage_with_journal
    session_id = storage.create_session("someone", 10)
    storage._journal_enabled = False
    try:
        storage.add_event(session_id, {"time": 1000.0, "kind": "comment",
                                       "user": {"user_id": "u1", "unique_id": "h1",
                                                "nickname": "n1"}})
        storage.flush()
    finally:
        storage._journal_enabled = True

    url = _avatar(4)
    row = [None] * len(_common._EVENTS_COLUMNS)
    row[0] = session_id
    row[3] = "comment"
    position = _common._EVENTS_COLUMNS.index("user_avatar")
    lines = []
    for i in range(2):
        entry = list(row)
        entry[1] = 1000.0 + i
        entry[position] = url
        lines.append(json.dumps({"t": "e", "r": entry}, ensure_ascii=False))
    (journal_dir / "events-20260101.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert storage.recover_from_journal()["sessions"] == 1

    conn = db_read_for(storage)
    try:
        avatars = [r["avatar"] for r in _rows(conn)]
    finally:
        conn.close()
    assert avatars == [_stored(4), _stored(4)]


# ===== hash衝突 =============================================================


def test_a_hash_collision_does_not_merge_two_different_strings(
    tmp_db, db_read, make_session, event_builder
):
    """hashは引くための絞り込みでしかない。**同じhashの別の値を同じidへ畳まないこと。**

    衝突を偶然に任せず、同じhashを持つ偽の行を先に置いて確かめる(実際の衝突確率は
    64bitで292k件に対し2.3e-9なので、待っていても起きない)。
    """
    session_id = make_session()
    url = _avatar(5)
    with tmp_db._lock:
        tmp_db._conn.execute(
            "INSERT INTO event_strings (id, hash, value) VALUES (?, ?, ?)",
            (9_000_001, _common._string_hash(url), "別の値だが同じhash"),
        )
        tmp_db._conn.commit()

    tmp_db.add_event(session_id, event_builder("comment", user=event_builder.user(avatar=url)))
    tmp_db.flush()

    assert _rows(db_read)[0]["avatar"] == _stored(5)
    assert db_read.execute(
        "SELECT user_avatar_id FROM events").fetchone()[0] != 9_000_001


def test_the_hash_does_not_move_between_processes():
    """PYTHONHASHSEEDで変わるhash()を使っていないこと。保存したhashが次の起動で
    引けなくなると、同じ文字列がintern表に積み上がる。"""
    assert _common._string_hash("abc") == _common._string_hash("abc")
    assert _common._string_hash("abc") == -2_829_645_022_057_097_895


# ===== rollback =============================================================


def test_a_rollback_does_not_leave_rolled_back_ids_in_the_cache(tmp_db, make_session,
                                                                event_builder):
    """rollbackでevent_stringsへのINSERTも巻き戻る。cacheが持ち越すと、以後のeventが
    **存在しないidを参照する行**になり、JOINが一致せずavatarが消える。"""
    session_id = make_session()
    tmp_db.add_event(session_id, event_builder("comment", user=event_builder.user(avatar=_avatar(6))))
    tmp_db.flush()
    assert tmp_db._string_cache

    with tmp_db._lock:
        tmp_db._conn.execute(
            "INSERT INTO event_strings (id, hash, value) VALUES (?, ?, ?)",
            (9_100_001, 1, "確定させない値"))
        tmp_db._conn.rollback()
        tmp_db._intern_forget_after_rollback()
    assert tmp_db._string_cache == {}
    assert tmp_db._next_string_id is None

    # 巻き戻した後も、書き込みは実在するidを指し続ける。
    tmp_db.add_event(session_id, event_builder("comment", user=event_builder.user(avatar=_avatar(6))))
    tmp_db.flush()
    with tmp_db._lock:
        orphans = tmp_db._conn.execute(
            "SELECT COUNT(*) FROM events e WHERE e.user_avatar_id IS NOT NULL"
            " AND NOT EXISTS (SELECT 1 FROM event_strings s WHERE s.id = e.user_avatar_id)"
        ).fetchone()[0]
    assert orphans == 0


# ===== migrationの2段階 =====================================================


def test_expand_keeps_the_old_columns_so_both_readers_agree(expand_db, tmp_db_path,
                                                            event_builder):
    """EXPANDでは旧列とid列の両方に同じ真実が在る。書き換え済みの読み出し箇所と
    未着手の箇所が共存できるのはこの段階だけである。"""
    storage = expand_db()
    assert storage._intern_phase == _common._INTERN_PHASE_EXPAND
    session_id = storage.create_session("tester", 60)
    url = _avatar(8)
    storage.add_event(session_id, event_builder("comment", user=event_builder.user(avatar=url)))
    storage.flush()

    conn = sqlite3.connect(str(tmp_db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT e.user_avatar, av.value AS joined FROM events e"
            " LEFT JOIN event_strings av ON av.id = e.user_avatar_id").fetchone()
    finally:
        conn.close()
    # EXPANDでは旧列とid列の両方へ同じ(正規化後の)値が入る。片方だけ生のURLにすると、
    # 旧列を読む箇所とJOINで読む箇所が違う答えを返す。
    assert row["user_avatar"] == _stored(8) == row["joined"]


def test_contract_drops_the_old_columns_and_keeps_every_value(tmp_db_path, target_phase):
    """EXPANDからCONTRACTまで進めて、旧列が消えても値が1つも変わらないこと。"""
    target_phase(_common._INTERN_PHASE_EXPAND)
    storage = Storage(str(tmp_db_path))
    try:
        session_id = storage.create_session("tester", 60)
        expected = []
        for i in range(50):
            url = _avatar(i % 7)          # 重複させてinternが効く形にする
            badge = f"https://p16-webcast.tiktokcdn.com/webcast-va/lv{i % 3}.png~tplv-obj.image"
            storage.add_event(session_id, {
                "time": 1000.0 + i, "kind": "gift", "diamonds": 1, "gift_name": "Rose",
                "user": {"user_id": f"u{i}", "unique_id": f"h{i}", "nickname": f"n{i}",
                         "avatar": url, "gifter_badge": badge, "member_badge": ""},
            })
            # 保存されるのは署名を落とした形。badgeは署名が付かないのでそのまま。
            expected.append((url.partition("?")[0], badge, ""))
        storage.flush()
    finally:
        storage.close()

    target_phase(_common._INTERN_PHASE_CONTRACT)
    storage = Storage(str(tmp_db_path))
    try:
        assert storage._intern_phase == _common._INTERN_PHASE_CONTRACT
        with storage._lock:
            columns = {r["name"] for r in storage._conn.execute("PRAGMA table_info(events)")}
            assert "user_avatar" not in columns
            assert "user_gifter_badge" not in columns
            assert "user_member_badge" not in columns
            got = [(r["avatar"], r["gifter_badge"], r["member_badge"])
                   for r in _rows(storage._conn)]
        assert got == expected
    finally:
        storage.close()


def test_contract_refuses_to_drop_when_a_single_row_disagrees(tmp_db_path, target_phase):
    """**唯一の安全弁。** 落としてしまえば元の値はどこにも残らないので、1行でも
    食い違うなら進まないこと。"""
    # 仕込みはEXPANDで行う。globalの目標が既にCONTRACTだと、この最初の起動が旧列を
    # 落としてしまい、「食い違う1行」を作る前に前提が消える。
    target_phase(_common._INTERN_PHASE_EXPAND)
    storage = Storage(str(tmp_db_path))
    try:
        session_id = storage.create_session("tester", 60)
        for i in range(5):
            storage.add_event(session_id, {
                "time": 1000.0 + i, "kind": "comment",
                "user": {"user_id": f"u{i}", "unique_id": f"h{i}", "nickname": f"n{i}",
                         "avatar": _avatar(i)},
            })
        storage.flush()
        # 1行だけ、id列を「値と食い違う」状態にする。
        with storage._lock:
            storage._conn.execute(
                "UPDATE events SET user_avatar_id = NULL WHERE id ="
                " (SELECT MIN(id) FROM events)")
            storage._conn.commit()
    finally:
        storage.close()

    target_phase(_common._INTERN_PHASE_CONTRACT)
    storage = Storage(str(tmp_db_path))
    try:
        # 段階は上がらず、旧列は残る。
        assert storage._intern_phase == _common._INTERN_PHASE_EXPAND
        with storage._lock:
            columns = {r["name"] for r in storage._conn.execute("PRAGMA table_info(events)")}
        assert "user_avatar" in columns
    finally:
        storage.close()


def test_the_migration_resumes_instead_of_starting_over(tmp_db_path, target_phase):
    """id埋めは「id列がNULLの行」が再開条件そのもの。途中で落ちた形を作って、
    次の起動が残りだけを埋めることを確かめる。"""
    # 旧列が在る段階でなければ「途中で落ちた形」を作れない。
    target_phase(_common._INTERN_PHASE_EXPAND)
    storage = Storage(str(tmp_db_path))
    try:
        session_id = storage.create_session("tester", 60)
        for i in range(30):
            storage.add_event(session_id, {
                "time": 1000.0 + i, "kind": "comment",
                "user": {"user_id": f"u{i}", "unique_id": f"h{i}", "nickname": f"n{i}",
                         "avatar": _avatar(i)},
            })
        storage.flush()
        # 途中で落ちた状態を作る: 半分のid列をNULLへ戻す(旧列は残っている)。
        with storage._lock:
            storage._conn.execute(
                "UPDATE events SET user_avatar_id = NULL WHERE id % 2 = 0")
            storage._conn.execute(
                "INSERT OR REPLACE INTO db_maintenance (key, value) VALUES (?, ?)",
                (_common._INTERN_PHASE_KEY, str(_common._INTERN_PHASE_NONE)))
            storage._conn.commit()
    finally:
        storage.close()

    storage = Storage(str(tmp_db_path))
    try:
        with storage._lock:
            missing = storage._conn.execute(
                "SELECT COUNT(*) FROM events WHERE user_avatar IS NOT NULL"
                " AND user_avatar_id IS NULL").fetchone()[0]
            mismatched = storage._conn.execute(
                "SELECT COUNT(*) FROM events e LEFT JOIN event_strings s"
                " ON s.id = e.user_avatar_id WHERE e.user_avatar IS NOT s.value").fetchone()[0]
        assert missing == 0 and mismatched == 0
    finally:
        storage.close()


def test_a_contracted_db_does_not_get_the_old_columns_back(tmp_db_path, target_phase):
    """CONTRACT済みのDBで目標をEXPANDへ戻しても、空の旧列を復活させないこと。

    復活させると、書き込みはid列だけへ行くので旧列には黙ってNULLが並び、旧列を読む
    箇所が「avatarが無い」と報告し始める。段階は前へしか進まない。
    """
    target_phase(_common._INTERN_PHASE_EXPAND)
    storage = Storage(str(tmp_db_path))
    try:
        session_id = storage.create_session("tester", 60)
        storage.add_event(session_id, {
            "time": 1000.0, "kind": "comment",
            "user": {"user_id": "u1", "unique_id": "h1", "nickname": "n1",
                     "avatar": _avatar(9)}})
        storage.flush()
    finally:
        storage.close()

    target_phase(_common._INTERN_PHASE_CONTRACT)
    Storage(str(tmp_db_path)).close()

    target_phase(_common._INTERN_PHASE_EXPAND)
    storage = Storage(str(tmp_db_path))
    try:
        with storage._lock:
            columns = {r["name"] for r in storage._conn.execute("PRAGMA table_info(events)")}
        assert "user_avatar" not in columns
        assert storage._intern_phase == _common._INTERN_PHASE_CONTRACT
    finally:
        storage.close()


def test_the_temporary_value_index_is_not_left_behind(tmp_db, db_read):
    """valueのUNIQUE indexは実測81.5MBで、常設にすると回収分の28%を食い潰す。
    id埋めのあいだだけ張って必ず落とすこと。"""
    left = db_read.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name = ?",
        (tmp_db._INTERN_TEMP_INDEX,)).fetchone()[0]
    assert left == 0


# ===== 退避 =================================================================


def test_the_premigration_backup_covers_a_db_that_only_has_events(tmp_db_path, monkeypatch):
    """退避の判定(has_rows)がeventsを見ていること。battlesとtranscriptsが空で
    eventsだけ在るDBが、退避なしで旧列を落とすのを防ぐ唯一の条件である。"""
    from tictok.store import maintenance

    storage = Storage(str(tmp_db_path))
    try:
        session_id = storage.create_session("tester", 60)
        storage.add_event(session_id, {"time": 1000.0, "kind": "comment",
                                       "user": {"user_id": "u1", "unique_id": "h1",
                                                "nickname": "n1", "avatar": _avatar(10)}})
        storage.flush()
        with storage._lock:
            assert storage._conn.execute("SELECT COUNT(*) FROM battles").fetchone()[0] == 0
            assert storage._conn.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 0
            # markerを消して「次の起動でmigrationが走る」状態にする。
            storage._conn.execute("DELETE FROM db_maintenance WHERE key = ?",
                                  (_common._MIGRATION_BACKUP_KEY,))
            storage._conn.commit()
    finally:
        storage.close()

    taken = {}

    def _fake_backup(path, reason):
        taken["path"] = path
        return {"path": str(path), "bytes": 0}

    monkeypatch.setattr(maintenance.dbmaint, "create_backup", _fake_backup)
    storage = Storage(str(tmp_db_path))
    try:
        assert storage.premigration_backup["taken"] is True, storage.premigration_backup
    finally:
        storage.close()


@pytest.fixture
def storage_with_journal(tmp_db_path, env_guard):
    journal_dir = env_guard / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    storage = Storage(str(tmp_db_path))
    try:
        yield storage, journal_dir
    finally:
        storage.close()


@pytest.fixture
def db_read_for():
    def _open(storage):
        conn = sqlite3.connect(storage._db_path)
        conn.row_factory = sqlite3.Row
        return conn
    return _open


def test_a_snapshot_lands_next_to_its_own_database(tmp_path, monkeypatch):
    """退避先はDBの隣。**project rootに固定してはいけない。**

    固定していたため、sandboxのDBを開いたtestが本番の backups/ へ退避を書いていた。世代は
    理由ごとに刈られるので、393KBのtest退避3つが `premigration` の枠を埋め、実測で1.85GBの
    migration前退避が **test 1回の実行で消えた**。退避が無いことはlogに残らず、戻したく
    なった時にしか分からない。
    """
    from tictok.core import config

    monkeypatch.delenv("TICTOK_DB_BACKUP_DIR", raising=False)
    monkeypatch.setenv("TICTOK_DB_PATH", str(tmp_path / "sandbox" / "tictok.db"))
    assert Path(config.get_db_backup_dir()) == tmp_path / "sandbox" / "backups"

    # 明示された値は尊重する(別volumeへ逃がす運用がある)。
    monkeypatch.setenv("TICTOK_DB_BACKUP_DIR", str(tmp_path / "elsewhere"))
    assert Path(config.get_db_backup_dir()) == tmp_path / "elsewhere"
