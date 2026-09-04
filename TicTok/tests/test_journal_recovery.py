"""耐久journalからの復元(Storage.recover_from_journal)。

この経路は「batch writerの停滞やクラッシュでDBから欠けたeventを、取り込み時にdiskへ
書いた記録から埋め戻す」最後の防波堤である。誤ると静かにeventが恒久的に失われるため、
判定に使う件数と、実際に書き戻す行が食い違わないことをここで固定する。

中心にあるのは1つの不変条件である:

    件数だけを数えるpass(_count_journal_rows)と、行を組み立てるpass
    (_collect_journal_rows)は、同じfileに対して常に同じ件数でなければならない。

復元するか否かは前者の件数で決め(DBの行数と突き合わせる)、実際にDELETE→全置換するのは
後者の行なので、ここがずれると「DBの方が多いのに少ない方で上書きする」= event消失が
起きる。行幅の正規化(現行schemaより短い行はNULLで埋めて採用 / 長い行は不採用)が
片方にしか入っていない、といった食い違いを検出するのがこのtestの目的である。
"""
import gzip
import json

import pytest

from tictok.storage import _EVENTS_COLUMNS, Storage

EVENT_WIDTH = len(_EVENTS_COLUMNS)
VIEWER_WIDTH = 6


def _event_row(session_id, time_value, kind="comment", width=EVENT_WIDTH):
    """journalに載るevents行。widthで現行schemaより短い/長い行を作れる。"""
    row = [None] * EVENT_WIDTH
    row[0] = session_id
    row[1] = time_value
    row[3] = kind
    if width < EVENT_WIDTH:
        return row[:width]
    if width > EVENT_WIDTH:
        return row + ["extra"] * (width - EVENT_WIDTH)
    return row


def _viewer_row(session_id, time_value, viewers=5):
    return [session_id, time_value, None, viewers, None, None]


def _write_journal(path, records, compress=False):
    """recordsは (t, row) のlist。生の文字列を渡すとその行をそのまま書く。"""
    lines = []
    for record in records:
        if isinstance(record, str):
            lines.append(record)
        else:
            kind, row = record
            lines.append(json.dumps({"t": kind, "r": row}, ensure_ascii=False))
    body = "\n".join(lines) + "\n"
    if compress:
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(body)
    else:
        path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def journal_dir(env_guard, tmp_path, monkeypatch):
    """復元の入力だけを置く空のdirectory。

    env_guardへ明示的に依存するのは、あちらがTICTOK_JOURNAL_DIRを自分のsandboxへ
    向け直すためで、順序が入れ替わるとこのdirectoryが使われない。
    """
    path = tmp_path / "journal_only"
    path.mkdir()
    monkeypatch.setenv("TICTOK_JOURNAL_DIR", str(path))
    return path


@pytest.fixture
def storage(tmp_db_path):
    instance = Storage(str(tmp_db_path))
    try:
        yield instance
    finally:
        instance.close()


# ===== 中心の不変条件: 数えるpassと組み立てるpassが一致する =====================


def _corpus(journal_dir):
    """現実に起こりうる行の形を全部入れたjournal。

    - 現行schemaちょうどの行
    - 現行schemaより短い行(列を足す前のjournal。NULLで埋めて採用する)
    - 現行schemaより長い行(新しい版が書いた記録。列の対応が決められないので不採用)
    - viewer sample行
    - 空行 / 壊れたJSON / "r"を持たないrecord / 未知のt
    - 複数session、複数file、.gz
    """
    plain = _write_journal(journal_dir / "events-20260101.jsonl", [
        ("e", _event_row(1, 100.0)),
        ("e", _event_row(1, 101.0, width=EVENT_WIDTH - 12)),   # 短い: 採用
        ("e", _event_row(1, 102.0, width=EVENT_WIDTH + 3)),    # 長い: 不採用
        ("v", _viewer_row(1, 103.0)),
        "",                                                     # 空行
        "   ",                                                  # 空白のみ
        "{ this is not json",                                   # 壊れたJSON
        json.dumps({"t": "e"}),                                 # "r"が無い
        json.dumps({"t": "x", "r": _event_row(1, 104.0)}),      # 未知のt
        ("e", _event_row(2, 105.0)),
        ("v", _viewer_row(2, 106.0)),
    ])
    gz = _write_journal(journal_dir / "events-20260102.jsonl.gz", [
        ("e", _event_row(1, 200.0)),
        ("e", _event_row(2, 201.0, width=EVENT_WIDTH - 1)),     # 短い: 採用
        ("e", _event_row(2, 202.0, width=EVENT_WIDTH + 1)),     # 長い: 不採用
        ("v", _viewer_row(2, 203.0)),
        ("v", _viewer_row(3, 204.0)),
    ], compress=True)
    return [plain, gz]


def test_count_pass_and_collect_pass_agree_on_every_row_shape(storage, journal_dir):
    """**この試験がこの経路の要である。**

    数えるpassと組み立てるpassが、あらゆる行の形について同じ件数を出すこと。
    片方だけが行幅の正規化を持っていれば、ここで必ず落ちる。
    """
    paths = _corpus(journal_dir)

    event_counts, viewer_counts, _marks = storage._count_journal_rows(paths)
    events_by_sid, viewers_by_sid = storage._collect_journal_rows(paths)

    assert event_counts == {sid: len(rows) for sid, rows in events_by_sid.items()}
    assert viewer_counts == {sid: len(rows) for sid, rows in viewers_by_sid.items()}

    # 期待値そのものも固定する(両passが「同じように間違えている」のを見逃さないため)。
    # session 1: 100.0と101.0(短い行)と200.0を採用、102.0(長い行)は不採用。
    # session 2: 105.0と201.0(短い行)を採用、202.0(長い行)は不採用。
    assert event_counts == {1: 3, 2: 2}
    assert viewer_counts == {1: 1, 2: 2, 3: 1}


def test_short_rows_are_padded_to_the_current_schema_width(storage, journal_dir):
    """列を足す前のjournalは、不足分をNULLで埋めて採用する(値の捏造ではなく未計測)。"""
    paths = [_write_journal(journal_dir / "events-20260101.jsonl", [
        ("e", _event_row(1, 100.0, width=EVENT_WIDTH - 5)),
    ])]

    event_counts, _, _ = storage._count_journal_rows(paths)
    events_by_sid, _ = storage._collect_journal_rows(paths)

    assert event_counts == {1: 1}
    (row,) = events_by_sid[1]
    assert len(row) == EVENT_WIDTH
    assert row[-5:] == (None,) * 5


def test_overlong_rows_are_dropped_by_both_passes(storage, journal_dir):
    """現行schemaより列が多い記録は復元しない。位置がずれたまま入れる方が有害である。"""
    paths = [_write_journal(journal_dir / "events-20260101.jsonl", [
        ("e", _event_row(1, 100.0, width=EVENT_WIDTH + 2)),
        ("e", _event_row(1, 101.0)),
    ])]

    event_counts, _, _ = storage._count_journal_rows(paths)
    events_by_sid, _ = storage._collect_journal_rows(paths)

    assert event_counts == {1: 1}
    assert len(events_by_sid[1]) == 1


def test_collect_pass_can_be_restricted_to_the_sessions_that_need_restoring(
    storage, journal_dir
):
    """組み立ては復元が要るsessionだけに絞れる(絞っても件数は変わらない)。"""
    paths = _corpus(journal_dir)

    event_counts, viewer_counts, _ = storage._count_journal_rows(paths)
    events_by_sid, viewers_by_sid = storage._collect_journal_rows(paths, wanted={2})

    assert set(events_by_sid) <= {2}
    assert set(viewers_by_sid) <= {2}
    assert len(events_by_sid[2]) == event_counts[2]
    assert len(viewers_by_sid[2]) == viewer_counts[2]
    # 絞っても、絞らないときと同じ行が同じ順で出る。
    full_events, full_viewers = storage._collect_journal_rows(paths)
    assert events_by_sid[2] == full_events[2]
    assert viewers_by_sid[2] == full_viewers[2]


def test_collect_pass_never_exceeds_the_counted_rows_when_the_file_grew(
    storage, journal_dir
):
    """2 passの間にjournalが伸びても、判定に使った件数を超えて取り込まない。

    journalは追記のみなので、1 pass目が数えた行は2 pass目でも先頭から同じ順で現れる。
    後から増えた行まで取り込むと「件数で決めた判断」と「書き戻す行」がずれるため、
    1 pass目の件数を上限にする。
    """
    path = journal_dir / "events-20260101.jsonl"
    _write_journal(path, [("e", _event_row(1, 100.0)), ("e", _event_row(1, 101.0))])

    event_counts, viewer_counts, _ = storage._count_journal_rows([path])
    assert event_counts == {1: 2}

    # 1 pass目と2 pass目のあいだにcollectorが書き足した状況。
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"t": "e", "r": _event_row(1, 102.0)}) + "\n")
        fh.write(json.dumps({"t": "v", "r": _viewer_row(1, 103.0)}) + "\n")

    events_by_sid, viewers_by_sid = storage._collect_journal_rows(
        [path], limits=(event_counts, viewer_counts))

    assert len(events_by_sid[1]) == 2
    assert [row[1] for row in events_by_sid[1]] == [100.0, 101.0]
    assert viewers_by_sid.get(1, []) == []


def test_unreadable_journal_file_does_not_abort_the_other_files(storage, journal_dir):
    """壊れたfileがあっても、他のfileの記録は数えられる/組み立てられる。"""
    broken = journal_dir / "events-20260101.jsonl.gz"
    broken.write_bytes(b"this is not gzip")
    good = _write_journal(journal_dir / "events-20260102.jsonl", [
        ("e", _event_row(1, 100.0)),
    ])

    event_counts, _, _ = storage._count_journal_rows([broken, good])
    events_by_sid, _ = storage._collect_journal_rows([broken, good])

    assert event_counts == {1: 1}
    assert len(events_by_sid[1]) == 1


# ===== 復元そのもののsemantics(既存の挙動を固定する) =========================


def _session_with_events(storage, count, unique_id="someone"):
    """DB側だけにeventを積む。この仕込み自体はjournalへ書かない — 書くと復元の入力が
    testの意図した中身と混ざり、何を根拠に復元したのかが読めなくなる。"""
    storage._journal_enabled = False
    try:
        session_id = storage.create_session(unique_id, 10)
        for i in range(count):
            storage.add_event(session_id, {
                "time": 1000.0 + i, "kind": "comment", "comment": f"c{i}",
                "user": {"user_id": f"u{i}", "unique_id": f"h{i}", "nickname": f"n{i}"},
            })
        storage.flush()
    finally:
        storage._journal_enabled = True
    return session_id


def _db_counts(storage, session_id):
    with storage._lock:
        events = storage._conn.execute(
            "SELECT COUNT(*) c FROM events WHERE session_id = ?", (session_id,)
        ).fetchone()["c"]
        viewers = storage._conn.execute(
            "SELECT COUNT(*) c FROM viewer_samples WHERE session_id = ?", (session_id,)
        ).fetchone()["c"]
    return events, viewers


def test_restores_events_missing_from_the_db(storage, journal_dir):
    """journalがDBを全項目で上回るときだけ、そのsessionを全置換で復元する。"""
    session_id = _session_with_events(storage, 2)
    _write_journal(journal_dir / "events-20260101.jsonl", [
        ("e", _event_row(session_id, 1000.0)),
        ("e", _event_row(session_id, 1001.0)),
        ("e", _event_row(session_id, 1002.0)),
        ("v", _viewer_row(session_id, 1003.0)),
    ])

    summary = storage.recover_from_journal()

    assert summary["sessions"] == 1
    assert summary["events"] == 1
    assert summary["viewers"] == 1
    assert _db_counts(storage, session_id) == (3, 1)


def test_leaves_the_db_alone_when_it_already_has_as_many_rows(storage, journal_dir):
    """DBが同数以上なら何もしない。ここで全置換するとDB側の分を失う。"""
    session_id = _session_with_events(storage, 3)
    _write_journal(journal_dir / "events-20260101.jsonl", [
        ("e", _event_row(session_id, 1000.0)),
        ("e", _event_row(session_id, 1001.0)),
    ])

    summary = storage.recover_from_journal()

    assert summary == {"sessions": 0, "events": 0, "viewers": 0, "resurrected": 0}
    assert _db_counts(storage, session_id) == (3, 0)


def test_skips_the_session_when_the_counts_are_inconsistent(storage, journal_dir):
    """片方でDBを下回るjournalは不整合。全置換するとDB側の分を失うのでskipする。"""
    session_id = _session_with_events(storage, 2)
    with storage._lock:
        storage._conn.execute(
            "INSERT INTO viewer_samples (session_id, time, create_time, viewers,"
            " total_viewers, anonymous) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, 1000.0, None, 5, None, None))
        storage._conn.commit()
    # eventは上回るがviewerは下回る。
    _write_journal(journal_dir / "events-20260101.jsonl", [
        ("e", _event_row(session_id, 1000.0)),
        ("e", _event_row(session_id, 1001.0)),
        ("e", _event_row(session_id, 1002.0)),
    ])

    summary = storage.recover_from_journal()

    assert summary == {"sessions": 0, "events": 0, "viewers": 0, "resurrected": 0}
    assert _db_counts(storage, session_id) == (2, 1)


def test_does_not_resurrect_a_deleted_session(storage, journal_dir):
    """session行が無いなら復元しない(削除の意思を尊重する)。"""
    _write_journal(journal_dir / "events-20260101.jsonl", [
        ("e", _event_row(4242, 1000.0)),
        ("e", _event_row(4242, 1001.0)),
    ])

    summary = storage.recover_from_journal()

    assert summary == {"sessions": 0, "events": 0, "viewers": 0, "resurrected": 0}
    with storage._lock:
        assert storage._conn.execute(
            "SELECT COUNT(*) c FROM events WHERE session_id = 4242"
        ).fetchone()["c"] == 0


def test_rebuilds_stats_and_buckets_after_restoring(storage, journal_dir):
    """置換後はstats_jsonとbucketをeventから作り直す(復元しただけでは画面が空になる)。"""
    session_id = _session_with_events(storage, 1)
    with storage._lock:
        storage._conn.execute("DELETE FROM buckets WHERE session_id = ?", (session_id,))
        storage._conn.commit()
    _write_journal(journal_dir / "events-20260101.jsonl", [
        ("e", _event_row(session_id, 1000.0)),
        ("e", _event_row(session_id, 1001.0)),
        ("e", _event_row(session_id, 1002.0)),
    ])

    storage.recover_from_journal()

    with storage._lock:
        buckets = storage._conn.execute(
            "SELECT COUNT(*) c FROM buckets WHERE session_id = ?", (session_id,)
        ).fetchone()["c"]
        stats = storage._conn.execute(
            "SELECT stats_json FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()["stats_json"]
    assert buckets > 0
    assert json.loads(stats)["events_total"] == 3


def test_does_nothing_when_the_journal_is_disabled(storage, journal_dir):
    """journalを切っている環境では、fileが在っても読みに行かない。"""
    session_id = _session_with_events(storage, 1)
    _write_journal(journal_dir / "events-20260101.jsonl", [
        ("e", _event_row(session_id, 1000.0)),
        ("e", _event_row(session_id, 1001.0)),
    ])
    storage._journal_enabled = False

    assert storage.recover_from_journal() == {"sessions": 0, "events": 0, "viewers": 0, "resurrected": 0}
    assert _db_counts(storage, session_id) == (1, 0)


def test_prune_runs_after_the_scan_so_expiring_files_still_contribute(
    storage, journal_dir, monkeypatch
):
    """保持期間を過ぎたfileも、消える前にその起動の復元へ寄与する。

    pruneを走査より先に回すと、本来復元できたeventが復元されないままjournalごと
    消える経路ができる。順序はここで固定する。
    """
    import time as time_module

    session_id = _session_with_events(storage, 1)
    old = _write_journal(journal_dir / "events-20260101.jsonl", [
        ("e", _event_row(session_id, 1000.0)),
        ("e", _event_row(session_id, 1001.0)),
    ])
    # 保持期間より古いmtimeにして、この起動でpruneの対象になるようにする。
    stale = time_module.time() - 400 * 86400
    import os

    os.utime(old, (stale, stale))
    monkeypatch.setattr(
        "tictok.store.ingest.get_journal_retention_days", lambda: 1)

    summary = storage.recover_from_journal()

    assert summary["sessions"] == 1
    assert _db_counts(storage, session_id) == (2, 0)
    assert not old.exists()


# ===== 数え直しを避けるcache ===================================================
#
# journalは保持期間ぶん全部が数える対象で、起動のたびに同じ数字を出し直していた
# (実測350MBで6〜10秒)。追記onlyなので、既に数えた区間の件数は二度と変わらない。
# ここで固定するのは1点だけ: **cacheが在っても無くても、出る件数は全走査と同じ。**


def test_count_cache_gives_the_same_numbers_as_a_full_scan(storage, journal_dir):
    """2回目の数え上げ(cacheあり)が、1回目(全走査)と同じ件数を返す。"""
    paths = _corpus(journal_dir)

    first = storage._count_journal_rows(paths)
    assert (journal_dir / "count_cache.json").is_file()
    second = storage._count_journal_rows(paths)

    assert second == first


def test_appended_rows_are_counted_once_and_only_once(storage, journal_dir):
    """cacheの続きから数えても、追記ぶんが二重に乗らない。"""
    path = _write_journal(journal_dir / "events-20260101.jsonl", [
        ("e", _event_row(1, 100.0)),
        ("v", _viewer_row(1, 101.0)),
    ])
    assert storage._count_journal_rows([path]) == ({1: 1}, {1: 1}, {})

    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"t": "e", "r": _event_row(1, 102.0)}) + "\n")

    assert storage._count_journal_rows([path]) == ({1: 2}, {1: 1}, {})


def test_a_line_without_its_newline_is_counted_but_not_cached(storage, journal_dir):
    """改行で終わっていない最終行は、数には入れるがcacheには残さない。

    その行は「どこまで読んだか」に記録できない。数えたうえで位置を進めれば次の起動で
    二度数え、数えなければDBから欠けた最後の1件が復元されなくなる。どちらも避けるため、
    この行が在るfileはcacheの対象から外して次回は頭から数える。
    """
    path = _write_journal(journal_dir / "events-20260101.jsonl", [
        ("e", _event_row(1, 100.0)),
    ])
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"t": "e", "r": _event_row(1, 101.0)}))   # 改行なし

    # 全走査と同じ2件。何度数えても増えない。
    assert storage._count_journal_rows([path]) == ({1: 2}, {}, {})
    assert storage._count_journal_rows([path]) == ({1: 2}, {}, {})
    cached = json.loads((journal_dir / "count_cache.json").read_text(encoding="utf-8"))
    assert path.name not in cached["files"]

    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n")

    assert storage._count_journal_rows([path]) == ({1: 2}, {}, {})
    assert storage._count_journal_rows([path]) == ({1: 2}, {}, {})


def test_an_unusable_cache_is_counted_from_scratch(storage, journal_dir):
    """cacheが壊れている/版が違う/fileが縮んだときは、頭から数え直して同じ数を出す。"""
    paths = _corpus(journal_dir)
    expected = storage._count_journal_rows(paths)
    cache = journal_dir / "count_cache.json"

    cache.write_text("これはJSONではない", encoding="utf-8")
    assert storage._count_journal_rows(paths) == expected

    cache.write_text(json.dumps({"version": 0, "files": {}}), encoding="utf-8")
    assert storage._count_journal_rows(paths) == expected

    # 数えた位置よりfileが短い = 追記onlyの前提が崩れている。cacheは使えない。
    stored = json.loads(cache.read_text(encoding="utf-8"))
    for entry in stored["files"].values():
        entry["offset"] += 10_000
    cache.write_text(json.dumps(stored), encoding="utf-8")
    assert storage._count_journal_rows(paths) == expected


def test_count_cache_does_not_change_what_gets_restored(storage, journal_dir):
    """cacheを挟んでも、復元される行はcacheが無いときと同じ。"""
    session_id = _session_with_events(storage, 1)
    _write_journal(journal_dir / "events-20260101.jsonl", [
        ("e", _event_row(session_id, 1000.0)),
        ("e", _event_row(session_id, 1001.0)),
    ])
    storage._count_journal_rows(storage._journal_files())   # cacheを作らせておく

    summary = storage.recover_from_journal()

    assert summary["sessions"] == 1
    assert _db_counts(storage, session_id) == (2, 0)


# ===== sessionの印: 行ごと蘇らせる / 別の配信へ混ぜない / idを再利用しない ==============
#
# journalにはevent/viewerしか無かったので、DBを古いsnapshotへ戻すとそれ以降の配信は
# 「session行が無い」だけで黙って戻らなかった。さらに sessions.id はAUTOINCREMENTで
# その連番もsnapshotと一緒に戻るため、復元後の最初の配信が失われた配信のidを取り、次の
# 起動で別配信者のeventがその配信へ混ざる(scratchpadの id_reuse_probe.py で実測)。
# ここで固定するのはその3点である。


def _session_mark(session_id, unique_id="alice", started_at=1000.0, bucket_seconds=10):
    return [session_id, unique_id, started_at, bucket_seconds, 1]


def _session_row(storage, session_id):
    with storage._lock:
        return storage._conn.execute(
            "SELECT unique_id, status, started_at, bucket_seconds FROM sessions WHERE id = ?",
            (session_id,)).fetchone()


def _journal_lines(journal_dir):
    lines = []
    for path in sorted(journal_dir.glob("events-*.jsonl")):
        lines += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                  if line.strip()]
    return lines


def test_create_and_delete_leave_marks_in_the_journal(storage, journal_dir):
    """作成は 's'(誰の・いつからの配信か)、削除は 'd' として残る。"""
    session_id = storage.create_session("alice", 10)
    assert storage.delete_session(session_id) is True

    marks = [line for line in _journal_lines(journal_dir) if line["t"] in ("s", "d")]

    assert marks[0]["t"] == "s"
    assert marks[0]["r"][:2] == [session_id, "alice"]
    assert marks[0]["r"][3] == 10
    assert marks[1] == {"t": "d", "r": [session_id]}


def test_resurrects_a_session_whose_row_was_lost_with_the_snapshot(storage, journal_dir):
    """作成の印があり削除の印が無いsessionは、行ごと作り直してからeventを入れる。"""
    _write_journal(journal_dir / "events-20260101.jsonl", [
        ("s", _session_mark(4242, "alice", 1000.0)),
        ("e", _event_row(4242, 1001.0)),
        ("e", _event_row(4242, 1002.0)),
        ("v", _viewer_row(4242, 1003.0)),
    ])

    summary = storage.recover_from_journal()

    assert summary == {"sessions": 1, "events": 2, "viewers": 1, "resurrected": 1}
    row = _session_row(storage, 4242)
    assert (row["unique_id"], row["started_at"], row["bucket_seconds"]) == ("alice", 1000.0, 10)
    assert _db_counts(storage, 4242) == (2, 1)
    # 蘇った行は 'connecting' のまま。確定は直後の cleanup_stale_sessions に任せる
    # (中断sessionと同じ手順で、最後のeventの時刻で畳む)。
    assert row["status"] == "connecting"
    assert storage.cleanup_stale_sessions() == 1
    row = _session_row(storage, 4242)
    assert row["status"] == "disconnected"


def test_does_not_resurrect_a_session_deleted_after_it_was_created(storage, journal_dir):
    """'s' の後に 'd' があれば消した配信。削除の意思を尊重する。"""
    _write_journal(journal_dir / "events-20260101.jsonl", [
        ("s", _session_mark(4242)),
        ("e", _event_row(4242, 1001.0)),
        ("d", [4242]),
    ])

    summary = storage.recover_from_journal()

    assert summary == {"sessions": 0, "events": 0, "viewers": 0, "resurrected": 0}
    assert _session_row(storage, 4242) is None


def test_refuses_to_pour_events_into_a_different_session_with_the_same_id(storage, journal_dir):
    """同じidの行が別の配信(unique_id/started_atが違う)なら、件数が上回っていても触らない。"""
    session_id = _session_with_events(storage, 1, unique_id="carol")
    _write_journal(journal_dir / "events-20260101.jsonl", [
        ("s", _session_mark(session_id, "bob", 500.0)),
        ("e", _event_row(session_id, 501.0)),
        ("e", _event_row(session_id, 502.0)),
        ("e", _event_row(session_id, 503.0)),
    ])

    summary = storage.recover_from_journal()

    assert summary == {"sessions": 0, "events": 0, "viewers": 0, "resurrected": 0}
    assert _db_counts(storage, session_id) == (1, 0)
    assert _session_row(storage, session_id)["unique_id"] == "carol"


def test_restoring_an_old_snapshot_does_not_reuse_a_session_id(storage, journal_dir):
    """連番がjournalの最大idより手前に戻っていたら進める。

    id_reuse_probe.py の再現: snapshotを戻した後の最初の create_session が、journalに
    残る失われた配信のidを取らないこと。"""
    _write_journal(journal_dir / "events-20260101.jsonl", [
        ("s", _session_mark(7, "bob", 500.0)),
        ("e", _event_row(7, 501.0)),
    ])

    storage.recover_from_journal()
    new_id = storage.create_session("carol", 10)

    assert new_id > 7
    assert _session_row(storage, 7)["unique_id"] == "bob"


def test_sequence_is_advanced_even_when_the_journal_has_no_marks(storage, journal_dir):
    """印の無い旧journalでも、idの再利用だけは止める(蘇らせはしない)。"""
    _write_journal(journal_dir / "events-20260101.jsonl", [
        ("e", _event_row(9, 501.0)),
    ])

    summary = storage.recover_from_journal()

    assert summary == {"sessions": 0, "events": 0, "viewers": 0, "resurrected": 0}
    assert _session_row(storage, 9) is None
    assert storage.create_session("carol", 10) > 9


def test_marks_survive_the_count_cache(storage, journal_dir):
    """印はcacheにも載る。cacheを挟んだ2回目も1回目と同じ印を返す。"""
    _write_journal(journal_dir / "events-20260101.jsonl", [
        ("s", _session_mark(1)),
        ("s", _session_mark(2, "bob")),
        ("d", [2]),
        ("e", _event_row(1, 100.0)),
    ])
    paths = storage._journal_files()

    first = storage._count_journal_rows(paths)
    second = storage._count_journal_rows(paths)

    assert first == second
    assert first[2] == {1: ("s", tuple(_session_mark(1))), 2: ("d",)}
