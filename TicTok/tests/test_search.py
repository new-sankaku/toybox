import json
import sqlite3
import threading
from pathlib import Path

import pytest

from tictok.core import layout
from tictok.record.recorder import timing_path
from tictok.search import indexer
from tictok.search.normalize import (FOLD_VERSION, MentionNames, blank_mention, fold,
                                     index_fold, mark)
from tictok.search.query import MIN_FTS_CHARS, QueryError, parse


# ===== query.parse =====


def test_parse_single_long_term_becomes_bare_phrase():
    out = parse("ramen")
    assert out["match"] == '"ramen"'
    assert out["like_all"] == []
    assert out["like_none"] == []
    assert out["terms"] == ["ramen"]
    assert out["or_mode"] is False


def test_parse_multiple_long_terms_are_and_joined_and_parenthesised():
    out = parse("  ramen   umai  ")
    assert out["match"] == '("ramen" AND "umai")'
    assert out["terms"] == ["ramen", "umai"]


def test_parse_quoted_span_stays_one_phrase():
    out = parse('"zaru ramen"')
    assert out["match"] == '"zaru ramen"'
    assert out["terms"] == ["zaru ramen"]


def test_parse_negation_becomes_single_binary_not():
    out = parse("ramen -cup -soup")
    assert out["match"] == '"ramen" NOT ("cup" OR "soup")'
    assert out["terms"] == ["ramen"]


def test_parse_or_switches_every_positive_to_or():
    out = parse("ramen OR udon OR soba")
    assert out["match"] == '("ramen" OR "udon" OR "soba")'
    assert out["or_mode"] is True
    assert "OR" not in out["terms"]


def test_parse_short_terms_go_to_like_not_match():
    out = parse("ab")
    assert len("ab") < MIN_FTS_CHARS
    assert out["match"] is None
    assert out["like_all"] == ["%ab%"]


def test_parse_mixes_match_and_like_when_lengths_differ():
    out = parse("ramen ab")
    assert out["match"] == '"ramen"'
    assert out["like_all"] == ["%ab%"]
    assert out["terms"] == ["ramen", "ab"]


def test_parse_long_negative_falls_back_to_like_when_no_matchable_positive():
    out = parse("ab -instant")
    assert out["match"] is None
    assert out["like_all"] == ["%ab%"]
    assert out["like_none"] == ["%instant%"]


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_parse_rejects_empty_input(raw):
    with pytest.raises(QueryError):
        parse(raw)


@pytest.mark.parametrize("raw", ["-cup", '-"cup ramen"', '""', "OR"])
def test_parse_rejects_input_without_any_positive(raw):
    with pytest.raises(QueryError):
        parse(raw)


@pytest.mark.parametrize(
    "term,expected",
    [("a%", "%a\\%%"), ("a_", "%a\\_%"), ("a\\", "%a\\\\%")],
)
def test_parse_escapes_like_wildcards(term, expected):
    assert parse(term)["like_all"] == [expected]


def test_parse_doubles_embedded_quotes_for_fts():
    out = parse('ramen"')
    assert out["match"] == '"ramen"""'
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE t USING fts5(body, tokenize='trigram')")
    conn.execute("INSERT INTO t(body) VALUES (?)", ['say ramen" now'])
    assert conn.execute("SELECT count(*) FROM t WHERE t MATCH ?", [out["match"]]).fetchone()[0] == 1
    conn.close()


def test_parse_treats_lone_hyphen_as_a_term_not_a_negation():
    out = parse("-")
    assert out["terms"] == ["-"]
    assert out["like_all"] == ["%-%"]


def test_parse_keeps_internal_hyphen_positive():
    out = parse("live-stream")
    assert out["terms"] == ["live-stream"]
    assert out["match"] == '"live-stream"'


def test_parse_quoted_phrase_containing_or_stays_and_mode():
    # フレーズの中身は語であって演算子ではない。ANDのつもりの検索をORへ倒さない。
    out = parse('"a OR b" ramen')
    assert out["or_mode"] is False
    # MATCH式へ載る語は畳んだ形(index側も同じ形)。英大文字は小文字へ寄る。
    assert out["match"] == '("a or b" AND "ramen")'


def test_parse_bare_or_still_switches_to_or_mode():
    out = parse("aaa OR bbb")
    assert out["or_mode"] is True
    assert out["match"] == '("aaa" OR "bbb")'


def test_parse_phrase_that_is_only_or_is_a_term_not_an_operator():
    out = parse('"OR"')
    assert out["or_mode"] is False
    assert out["terms"] == ["OR"]
    assert out["match"] is None
    assert out["like_all"] == ["%or%"]


def test_parse_or_with_negation_keeps_or_mode_and_the_exclusion():
    out = parse("a -b OR c")
    assert out["or_mode"] is True
    assert out["terms"] == ["a", "c"]
    assert out["like_all"] == ["%a%", "%c%"]
    assert out["like_none"] == ["%b%"]

    long_out = parse("ramen -cup OR udon")
    assert long_out["or_mode"] is True
    assert long_out["match"] == '("ramen" OR "udon") NOT ("cup")'


@pytest.mark.parametrize(
    "raw,hits,misses",
    [
        ('"a OR b" ramen', ['x a OR b y ramen z'], ['a OR b only', 'ramen only']),
        ("aaa OR bbb", ["aaa here", "bbb here"], ["ccc here"]),
        ("ramen -cup OR udon", ["ramen here", "udon here"], ["cup ramen", "soba"]),
    ],
)
def test_parse_match_expressions_are_valid_fts5_trigram_syntax(raw, hits, misses):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE t USING fts5(body, tokenize='trigram')")
    for body in hits + misses:
        conn.execute("INSERT INTO t(body) VALUES (?)", [body])
    expr = parse(raw)["match"]
    found = {r[0] for r in conn.execute("SELECT body FROM t WHERE t MATCH ?", [expr])}
    conn.close()
    assert found == set(hits)


# ===== normalize (表記ゆれの畳み込み) =====


@pytest.mark.parametrize("raw,expected", [
    ("うざ", "ウザ"),
    ("ウザ", "ウザ"),
    ("ヴぁゝゞ", "ヴァヽヾ"),
    ("ＡＢＣ１２３", "abc123"),
    ("Ramen", "ramen"),
    ("ｱｲｳ", "アイウ"),
    ("５０％", "50%"),
    ("空　白", "空 白"),
    ("ウサ", "ウサ"),      # 濁点は畳まない(ウザとウサは別語)
    ("ツ", "ツ"),          # 小書きも畳まない(ッとツは別語)
])
def test_fold_normalizes_the_written_form(raw, expected):
    assert fold(raw) == expected


@pytest.mark.parametrize("raw", [
    "うざい", "ｳｻﾞｲ", "ＡＢ①㍿", "😀👍", "が゙", "ﾞﾟ゛゜", "", "ＡＢＣ",
])
def test_fold_keeps_the_character_count(raw):
    """畳んだ本文の位置をそのまま原文へ当てて強調するので、長さが変わってはいけない。"""
    assert len(fold(raw)) == len(raw)


def test_fold_keeps_the_character_count_for_every_code_point():
    """1文字→1文字であることをUnicode全域で担保する。文字起こしにもコメントにも何が来るか
    分からない以上、代表例だけでは前提が崩れたことに気付けない。"""
    assert [ch for ch in map(chr, range(0x110000)) if len(fold(ch)) != 1] == []


def test_mark_wraps_the_original_text_not_the_folded_one():
    marked = mark("前ウザい後うざい", ["ウザ"])
    assert marked == "前\x02ウザ\x03い後\x02うざ\x03い"


def test_mark_merges_overlapping_terms_into_one_span():
    """囲みが入れ子になると、画面側の分割が強調の対応を取り違える。"""
    marked = mark("ラーメン屋", ["ラーメ", "ーメン"])
    assert marked == "\x02ラーメン\x03屋"


def test_mark_without_a_hit_leaves_the_body_untouched():
    assert mark("うどん", ["ラーメン"]) == "うどん"


# ===== normalize (返信の宛先を索引から外す) =====


def test_blank_mention_removes_the_leading_reply_target():
    assert blank_mention("@よい おやすみ") == "    おやすみ"


def test_blank_mention_keeps_the_character_count():
    body = "＠ニヤてち ところで なんの話ですか？"
    assert len(blank_mention(body)) == len(body)


def test_blank_mention_ignores_an_at_sign_that_is_not_at_the_head():
    body = "(@￣ρ￣@)ｚｚｚｚ"
    assert blank_mention(body) == body


def test_blank_mention_blanks_a_body_that_is_only_a_mention():
    assert blank_mention("@よい") == "   "


def test_blank_mention_cuts_at_the_known_name_not_at_the_first_space():
    """表示名そのものに空白があると、空白で切った残りが索引へ残って結局その名前で当たる。"""
    names = MentionNames(["Maiza Santos"])
    assert blank_mention("@Maiza Santos please gift", names) == " " * 14 + "please gift"
    # 名前を知らなければ空白で切るしかなく、後半が索引へ残る。
    assert "Santos" in blank_mention("@Maiza Santos please gift")


def test_blank_mention_falls_back_to_the_first_space_for_an_unknown_name():
    assert blank_mention("@ギフ禁のきき どぞ", MentionNames(["別人"])) == " " * 8 + "どぞ"


def test_mention_names_takes_the_longest_match():
    long_name = "よい【そのギフト】🐢"
    names = MentionNames(["よい", long_name])
    assert names.match_length(long_name + " ありがと") == len(long_name)


def test_index_fold_folds_after_dropping_the_target():
    # 宛先を外したうえで表記ゆれを畳む(「うざ」は「ウザ」の形で索引へ載る)。
    assert index_fold("@ウザ うざい") == "    ウザイ"


# ===== indexer =====


@pytest.fixture
def recording(tmp_db, make_session, tmp_root):
    session_id = make_session("streamer", status="connected")
    path = tmp_root / "streamer" / "mp4" / "00001_streamer_20260101_120000.mp4"
    rec_id = tmp_db.create_recording(
        session_id, "streamer", str(path), path.name, "hd", 1000.0)
    return {"id": rec_id, "session_id": session_id, "unique_id": "streamer",
            "started_at": 1000.0, "ended_at": 1600.0, "path": str(path)}


def test_index_transcript_without_transcript_clears_the_index(tmp_db, recording):
    tmp_db.replace_search_hits(recording["id"], indexer.SOURCE_STT, [{
        "session_id": recording["session_id"], "unique_id": "streamer",
        "started_at": 1000.0, "video_time": 1.0, "end_time": None,
        "nickname": None, "body": "stale"}])
    assert indexer.index_transcript(tmp_db, recording) == 0
    assert tmp_db.search_hits_for(recording["id"], indexer.SOURCE_STT) == []


def test_index_transcript_skips_blank_segments_and_keeps_media_times(tmp_db, recording):
    tmp_db.save_transcript(recording["id"], {"segments": [
        {"start": 0.0, "end": 2.5, "text": " hello "},
        {"start": 3.0, "end": 4.0, "text": "   "},
        {"start": 5.0, "end": 6.0, "text": ""},
        {"start": 7.25, "end": 9.0, "text": "world"},
    ]})
    assert indexer.index_transcript(tmp_db, recording) == 2
    rows = tmp_db.search_hits_for(recording["id"], indexer.SOURCE_STT)
    assert [(r["video_time"], r["end_time"], r["body"]) for r in rows] == [
        (0.0, 2.5, "hello"), (7.25, 9.0, "world")]
    assert all(r["nickname"] is None for r in rows)
    assert all(r["started_at"] == 1000.0 for r in rows)


def test_index_transcript_treats_missing_start_as_zero(tmp_db, recording):
    tmp_db.save_transcript(recording["id"], {"segments": [{"end": 1.0, "text": "x"}]})
    assert indexer.index_transcript(tmp_db, recording) == 1
    assert tmp_db.search_hits_for(recording["id"], indexer.SOURCE_STT)[0]["video_time"] == 0.0


async def test_index_comments_without_session_clears_the_index(tmp_db, recording):
    orphan = dict(recording, session_id=None)
    assert await indexer.index_comments(tmp_db, orphan) == 0
    assert tmp_db.search_hits_for(recording["id"], indexer.SOURCE_COMMENT) == []


async def test_index_comments_filters_kinds_blanks_and_pre_roll(
        tmp_db, recording, event_builder):
    sid = recording["session_id"]
    tmp_db.add_event(sid, event_builder("comment", at=995.0, comment="too early"))
    tmp_db.add_event(sid, event_builder("comment", at=1000.0, comment="at zero"))
    tmp_db.add_event(sid, event_builder("like", at=1010.0, comment="not a comment"))
    tmp_db.add_event(sid, event_builder("comment", at=1020.0, comment="   "))
    tmp_db.add_event(sid, event_builder("comment", at=1030.456, comment=" kept "))
    tmp_db.flush()

    assert await indexer.index_comments(tmp_db, recording) == 2
    rows = tmp_db.search_hits_for(recording["id"], indexer.SOURCE_COMMENT)
    assert [(r["video_time"], r["body"]) for r in rows] == [(0.0, "at zero"), (30.46, "kept")]
    assert all(r["end_time"] is None for r in rows)
    assert all(r["session_id"] == sid for r in rows)


async def test_index_comments_ignores_events_outside_the_recording_window(
        tmp_db, recording, event_builder):
    sid = recording["session_id"]
    tmp_db.add_event(sid, event_builder("comment", at=1500.0, comment="inside"))
    tmp_db.add_event(sid, event_builder("comment", at=1700.0, comment="next recording"))
    tmp_db.flush()
    assert await indexer.index_comments(tmp_db, recording) == 1
    rows = tmp_db.search_hits_for(recording["id"], indexer.SOURCE_COMMENT)
    assert [r["body"] for r in rows] == ["inside"]


async def test_index_comments_closes_an_open_window_at_the_next_recording(
        tmp_db, recording, event_builder, tmp_root):
    """ended_atが無い録画(crash中断)の窓を、同じsessionの次の録画の開始で閉じること。

    開いたままにすると後続録画のcommentをこの録画のものとして取り込む。"""
    sid = recording["session_id"]
    crashed = dict(recording, ended_at=None)
    nxt = tmp_root / "streamer" / "mp4" / "00002_streamer_20260101_130000.mp4"
    tmp_db.create_recording(sid, "streamer", str(nxt), nxt.name, "hd", 1600.0)
    tmp_db.add_event(sid, event_builder("comment", at=1500.0, comment="この録画"))
    tmp_db.add_event(sid, event_builder("comment", at=1900.0, comment="次の録画"))
    tmp_db.flush()

    assert await indexer.index_comments(tmp_db, crashed) == 1
    rows = tmp_db.search_hits_for(recording["id"], indexer.SOURCE_COMMENT)
    assert [r["body"] for r in rows] == ["この録画"]


async def test_index_comments_keeps_the_window_open_when_nothing_follows(
        tmp_db, recording, event_builder):
    """次の録画が無ければ閉じる根拠が無いので開いたままにする。ここで勝手に切ると、
    session最後の録画(ended_atが無いまま残った行)のcommentを落とすことになる。"""
    sid = recording["session_id"]
    crashed = dict(recording, ended_at=None)
    tmp_db.add_event(sid, event_builder("comment", at=1500.0, comment="窓の中"))
    tmp_db.add_event(sid, event_builder("comment", at=9000.0, comment="ずっと後"))
    tmp_db.flush()

    assert await indexer.index_comments(tmp_db, crashed) == 2


def test_next_recording_start_ignores_itself_and_other_sessions(
        tmp_db, make_session, tmp_root):
    """境界は厳密に ``>``。自分自身を拾うと窓が即座に潰れて0件になる。"""
    session_id = make_session("streamer", status="connected")
    other = make_session("streamer", status="connected")
    path = tmp_root / "streamer" / "mp4" / "00001_streamer_20260101_120000.mp4"
    tmp_db.create_recording(session_id, "streamer", str(path), path.name, "hd", 1000.0)
    tmp_db.create_recording(session_id, "streamer", str(path), path.name, "hd", 1600.0)
    tmp_db.create_recording(other, "streamer", str(path), path.name, "hd", 1200.0)

    assert tmp_db.next_recording_start(session_id, 1000.0) == 1600.0
    assert tmp_db.next_recording_start(session_id, 1600.0) is None


# ===== 時間軸 — 焼き付ける秒は「その録画が再生される軸」でなければならない =====


def _write_axis_material(tmp_root, recording, *, with_index: bool):
    """録画の素材(.ts)とtiming.jsonを置く。``media_pts`` はmedia軸とPTS軸が別物になる値
    (mp4のmux inflation相当)にして、どちらの軸で焼いたかを見分けられるようにする。"""
    path = Path(recording["path"])
    session = layout.session_dir(tmp_root, path.stem, "streamer")
    session.mkdir(parents=True, exist_ok=True)
    (session / "seg00000.ts").write_bytes(b"\x47" * 188)
    if with_index:
        (session / layout.PLAYLIST_NAME).write_text(
            "#EXTM3U\n#EXTINF:600.000000,\nseg00000.ts\n", encoding="utf-8")
    timing_path(path).parent.mkdir(parents=True, exist_ok=True)
    timing_path(path).write_text(json.dumps({
        "version": 2,
        "media_duration": 600.0,
        # wall 1000..1600 -> media 0..600(起動latencyなし)。
        "anchors": [[1000.0, 0.0], [1600.0, 600.0]],
        # media 600 が mp4では 660 になる録画(=10%のinflation)。
        "media_pts": [[0.0, 0.0], [600.0, 660.0]],
    }), encoding="utf-8")


async def test_index_comments_uses_the_media_axis_when_the_recording_plays_from_hls(
        tmp_db, recording, event_builder, tmp_root):
    """.tsが残る録画はHLSで再生され、playerの秒はmedia軸。mp4のPTSを掛けてはいけない。"""
    _write_axis_material(tmp_root, recording, with_index=True)
    tmp_db.add_event(recording["session_id"],
                     event_builder("comment", at=1300.0, comment="半分の位置"))
    tmp_db.flush()

    assert await indexer.index_comments(tmp_db, recording) == 1
    row = tmp_db.search_hits_for(recording["id"], indexer.SOURCE_COMMENT)[0]
    assert row["video_time"] == 300.0
    assert tmp_db.get_recording(recording["id"])["time_axis"] == indexer.AXIS_MEDIA


async def test_index_comments_uses_the_pts_axis_when_only_the_mp4_can_be_played(
        tmp_db, recording, event_builder, tmp_root):
    """再生listが無ければ再生はmp4。その録画の秒はmp4のPTS軸で、media_ptsを掛けるのが正しい。"""
    _write_axis_material(tmp_root, recording, with_index=False)
    tmp_db.add_event(recording["session_id"],
                     event_builder("comment", at=1300.0, comment="半分の位置"))
    tmp_db.flush()

    assert await indexer.index_comments(tmp_db, recording) == 1
    row = tmp_db.search_hits_for(recording["id"], indexer.SOURCE_COMMENT)[0]
    assert row["video_time"] == 330.0
    assert tmp_db.get_recording(recording["id"])["time_axis"] == indexer.AXIS_PTS


async def test_index_comments_falls_back_to_text_and_records_nickname(
        tmp_db, recording, event_builder):
    sid = recording["session_id"]
    user = event_builder.user(nickname="Nick")
    tmp_db.add_event(sid, event_builder("comment", at=1100.0, user=user, text="from text"))
    tmp_db.flush()
    assert await indexer.index_comments(tmp_db, recording) == 1
    row = tmp_db.search_hits_for(recording["id"], indexer.SOURCE_COMMENT)[0]
    assert row["body"] == "from text"
    assert row["nickname"] == "Nick"


# ===== storage.search_scenes (FTS5 trigram 経路) =====


@pytest.fixture
def seeded(tmp_db, recording):
    def _seed(bodies, source=indexer.SOURCE_STT):
        rows = [{"session_id": recording["session_id"], "unique_id": "streamer",
                 "started_at": 1000.0, "video_time": float(i), "end_time": None,
                 "nickname": None, "body": body} for i, body in enumerate(bodies)]
        tmp_db.replace_search_hits(recording["id"], source, rows)
        return rows

    return _seed


def _bodies(result):
    return sorted(item["body"] for item in result["items"])


def test_search_scenes_finds_a_mid_word_substring_via_trigram(tmp_db, seeded):
    seeded(["今日のラーメンは最高", "カップ麺の話", "no match here"])
    result = tmp_db.search_scenes("ラーメン", [indexer.SOURCE_STT])
    assert result["mode"] == "fts"
    assert result["total"] == 1
    assert _bodies(result) == ["今日のラーメンは最高"]
    assert result["terms"] == ["ラーメン"]


def test_search_scenes_and_requires_both_terms(tmp_db, seeded):
    seeded(["ラーメンが美味しい", "ラーメンだけ", "美味しいうどん"])
    result = tmp_db.search_scenes("ラーメン 美味しい", [indexer.SOURCE_STT])
    assert _bodies(result) == ["ラーメンが美味しい"]


def test_search_scenes_or_widens_the_result(tmp_db, seeded):
    seeded(["ラーメンだけ", "うどんだけ", "そばだけ"])
    result = tmp_db.search_scenes("ラーメン OR うどん", [indexer.SOURCE_STT])
    assert _bodies(result) == ["うどんだけ", "ラーメンだけ"]


def test_search_scenes_negation_excludes(tmp_db, seeded):
    seeded(["ラーメン美味しい", "カップラーメンの話"])
    result = tmp_db.search_scenes("ラーメン -カップ", [indexer.SOURCE_STT])
    assert _bodies(result) == ["ラーメン美味しい"]


def test_search_scenes_short_query_falls_back_to_like_mode(tmp_db, seeded):
    seeded(["寿司が好き", "うどんが好き"])
    result = tmp_db.search_scenes("寿司", [indexer.SOURCE_STT])
    assert result["mode"] == "like"
    assert _bodies(result) == ["寿司が好き"]


def test_search_scenes_like_mode_escapes_sql_wildcards(tmp_db, seeded):
    seeded(["割引 5%引き", "5x引き"])
    result = tmp_db.search_scenes("5%", [indexer.SOURCE_STT])
    assert result["mode"] == "like"
    assert _bodies(result) == ["割引 5%引き"]


def test_search_scenes_highlights_the_hit_in_fts_mode(tmp_db, seeded):
    seeded(["前ラーメン後"])
    item = tmp_db.search_scenes("ラーメン", [indexer.SOURCE_STT])["items"][0]
    assert "\x02" in item["snippet"] and "\x03" in item["snippet"]
    assert item["snippet"].replace("\x02", "").replace("\x03", "") == "前ラーメン後"


@pytest.mark.parametrize("query,mode", [
    ("うざい", "fts"),      # 3文字以上: FTSの索引語も畳んだ形で入っている
    ("ウザい", "fts"),
    ("ウザ", "like"),       # 2文字以下: LIKEも畳んだ本文(body_norm)を見る
    ("うざ", "like"),
])
def test_search_scenes_matches_across_hiragana_and_katakana(tmp_db, seeded, query, mode):
    seeded(["それうざい", "それウザい", "関係ない話"])
    result = tmp_db.search_scenes(query, [indexer.SOURCE_STT])
    assert result["mode"] == mode
    assert _bodies(result) == ["それうざい", "それウザい"]


def test_search_scenes_matches_across_width_and_case(tmp_db, seeded):
    seeded(["ＬＩＶＥ配信", "live配信", "関係ない話"])
    assert len(tmp_db.search_scenes("LIVE", [indexer.SOURCE_STT])["items"]) == 2
    assert len(tmp_db.search_scenes("ｌｉｖｅ", [indexer.SOURCE_STT])["items"]) == 2


def test_search_scenes_keeps_the_written_form_of_the_body_in_the_snippet(tmp_db, seeded):
    """畳んだ本文を索引しているので、返す本文まで畳んでしまうと画面の文字が化ける。"""
    seeded(["それうざい"])
    item = tmp_db.search_scenes("ウザい", [indexer.SOURCE_STT])["items"][0]
    assert item["body"] == "それうざい"
    assert item["snippet"] == "それ\x02うざい\x03"


def test_search_scenes_highlights_in_like_mode_too(tmp_db, seeded):
    """2文字以下の検索はFTSを通らないが、強調はFTS経路と同じに出す。"""
    seeded(["前うざ後"])
    result = tmp_db.search_scenes("ウザ", [indexer.SOURCE_STT])
    assert result["mode"] == "like"
    assert result["items"][0]["snippet"] == "前\x02うざ\x03後"


def test_search_scenes_negation_also_folds_the_written_form(tmp_db, seeded):
    seeded(["うざいけど好き", "好きなだけ"])
    result = tmp_db.search_scenes("好き -ウザい", [indexer.SOURCE_STT])
    assert _bodies(result) == ["好きなだけ"]


def _downgrade_search_index(path):
    """畳み込みを入れる前のDBの姿へ戻す(索引は原文のbody列・版markerも無い)。"""
    conn = sqlite3.connect(str(path))
    conn.execute("DROP TABLE search_fts")
    conn.execute("ALTER TABLE search_hits DROP COLUMN body_norm")
    conn.execute("CREATE VIRTUAL TABLE search_fts USING fts5("
                 " body, content='search_hits', content_rowid='id', tokenize='trigram')")
    conn.execute("INSERT INTO search_fts(search_fts) VALUES('rebuild')")
    conn.execute("DELETE FROM db_maintenance WHERE key = 'search_fold_version'")
    conn.commit()
    conn.close()


def _reopen(path):
    from tictok.storage import Storage
    return Storage(str(path))


def test_migration_folds_rows_written_before_the_index_was_folded(
        tmp_db, tmp_db_path, seeded):
    """既に貯まっている索引(原文で作られたもの)も、起動時に畳み直されること。"""
    seeded(["それうざい"])
    tmp_db.close()
    _downgrade_search_index(tmp_db_path)

    storage = _reopen(tmp_db_path)
    try:
        assert _bodies(storage.search_scenes("ウザい", [indexer.SOURCE_STT])) == ["それうざい"]
        assert _bodies(storage.search_scenes("ウザ", [indexer.SOURCE_STT])) == ["それうざい"]
    finally:
        storage.close()


def test_migration_reruns_when_the_folding_rule_version_changes(
        tmp_db, tmp_db_path, seeded, monkeypatch):
    """畳むruleを変えたら索引を作り直すこと。queryだけ新ruleで畳まれると、その語だけ
    当たらないという形で静かに壊れる。"""
    seeded(["それうざい"])
    tmp_db.close()
    conn = sqlite3.connect(str(tmp_db_path))
    # 索引を「古いruleで畳んだ状態」に見立てて壊しておく。作り直しが走ればここは
    # 上書きされ、走らなければ残る。
    conn.execute("UPDATE search_hits SET body_norm = '畳み損ね'")
    conn.execute("INSERT INTO search_fts(search_fts) VALUES('rebuild')")
    conn.commit()
    conn.close()

    unchanged = _reopen(tmp_db_path)
    try:
        assert unchanged.search_scenes("ウザい", [indexer.SOURCE_STT])["total"] == 0
    finally:
        unchanged.close()

    monkeypatch.setattr("tictok.search.normalize.FOLD_VERSION", FOLD_VERSION + 1)
    bumped = _reopen(tmp_db_path)
    try:
        assert _bodies(bumped.search_scenes("ウザい", [indexer.SOURCE_STT])) == ["それうざい"]
    finally:
        bumped.close()


def test_search_scenes_source_filter_is_applied(tmp_db, seeded):
    seeded(["文字起こしのラーメン"], source=indexer.SOURCE_STT)
    seeded(["コメントのラーメン"], source=indexer.SOURCE_COMMENT)
    assert _bodies(tmp_db.search_scenes("ラーメン", [indexer.SOURCE_COMMENT])) == ["コメントのラーメン"]
    assert tmp_db.search_scenes("ラーメン", [])["total"] == 0


def test_search_scenes_reports_hint_instead_of_raising_on_bad_query(tmp_db, seeded):
    seeded(["ラーメン"])
    result = tmp_db.search_scenes("-カップ", [indexer.SOURCE_STT])
    assert result["total"] == 0
    assert result["items"] == []
    assert result["mode"] == "none"
    assert result["hint"]


@pytest.mark.parametrize("query", [
    '"', '""ramen', "ramen*", "ramen^", "ramen:body", "NEAR(a b)", "a AND", "ramen(",
    "ramen)", "{a}", "[a]", "ramen'", "ramen\\", "ラーメン*OR", "-", "% _", "a OR",
    "AND OR NOT", "ramen -", "*", "ramen\"\"cup",
])
def test_search_scenes_never_raises_on_punctuation_queries(tmp_db, seeded, query):
    seeded(["ラーメン", "ramen time"])
    result = tmp_db.search_scenes(query, [indexer.SOURCE_STT])
    assert result["mode"] in {"fts", "like", "none"}
    assert isinstance(result["total"], int)


def test_search_scenes_limit_and_offset_page_without_changing_total(tmp_db, seeded):
    seeded([f"ラーメン{i}" for i in range(5)])
    first = tmp_db.search_scenes("ラーメン", [indexer.SOURCE_STT], limit=2)
    second = tmp_db.search_scenes("ラーメン", [indexer.SOURCE_STT], limit=2, offset=2)
    assert first["total"] == second["total"] == 5
    assert len(first["items"]) == len(second["items"]) == 2
    assert not set(_bodies(first)) & set(_bodies(second))


def test_search_scenes_filters_by_unique_id(tmp_db, recording):
    rows = [{"session_id": recording["session_id"], "unique_id": uid,
             "started_at": 1000.0, "video_time": 0.0, "end_time": None,
             "nickname": None, "body": body}
            for uid, body in (("alice", "アリスのラーメン"), ("bob", "ボブのラーメン"))]
    tmp_db.replace_search_hits(recording["id"], indexer.SOURCE_STT, rows)
    result = tmp_db.search_scenes("ラーメン", [indexer.SOURCE_STT], ["alice"])
    assert result["total"] == 1
    assert _bodies(result) == ["アリスのラーメン"]


@pytest.mark.parametrize("unique_ids", [None, ["alice"]])
def test_search_scenes_always_drives_the_join_from_the_fts_table(tmp_db, unique_ids):
    """配信者で絞ってもFTS側が外側であること。

    素のJOINだと、plannerがidx_search_hits_uidの等値条件に釣られてsearch_hits側を
    外側に回し、当たった行ごとにFTS照合する経路へ倒れる(実測: 件数のqueryが33ms→50秒)。
    行数の少ないtest DBでも同じ反転が起きるので、planを直接見て縛る。
    """
    from tictok.store.transcripts import _build_scene_query

    built = _build_scene_query(parse("ラーメン"),
                               [indexer.SOURCE_STT, indexer.SOURCE_COMMENT],
                               unique_ids, None, None, "time")
    reader = tmp_db._read_connection()
    for sql, params in ((built.count_sql, built.params),
                        (built.page_sql, built.params + [50, 0])):
        plan = [row["detail"] for row in
                reader.execute("EXPLAIN QUERY PLAN " + sql, params)]
        assert "VIRTUAL TABLE" in plan[0], (sql, plan)
        assert not any("idx_search_hits_uid" in step for step in plan), (sql, plan)


def test_search_scenes_does_not_hold_the_writer_lock(tmp_db, seeded):
    """検索はwriter接続を使わない。使うとcollectorのevent書き出しが検索の間止まる。"""
    seeded(["ラーメン"])
    done: list = []
    thread = threading.Thread(
        target=lambda: done.append(
            tmp_db.search_scenes("ラーメン", [indexer.SOURCE_STT])))
    with tmp_db._lock:
        thread.start()
        thread.join(timeout=10.0)
        finished = not thread.is_alive()
    thread.join(timeout=10.0)
    assert finished, "writer lockの保持中に検索が返らなかった"
    assert done[0]["total"] == 1


def test_replace_search_hits_drops_the_stale_fts_index(tmp_db, seeded):
    seeded(["古いラーメン"])
    seeded(["新しいうどん"])
    assert tmp_db.search_scenes("ラーメン", [indexer.SOURCE_STT])["total"] == 0
    assert tmp_db.search_scenes("うどん", [indexer.SOURCE_STT])["total"] == 1


# ===== search_scenes — 返信の宛先は索引に載せない =====


def test_search_scenes_does_not_match_the_reply_target(tmp_db, seeded):
    """@よい への返信が「よい」で全部出てくると、その人宛の返信が検索を埋める。"""
    seeded(["@よい おやすみなさいー", "よい香りがする"], source=indexer.SOURCE_COMMENT)
    result = tmp_db.search_scenes("よい", [indexer.SOURCE_COMMENT])
    assert _bodies(result) == ["よい香りがする"]


def test_search_scenes_still_finds_the_reply_body(tmp_db, seeded):
    """外すのは宛先だけ。返信の中身は今まで通り引ける。"""
    seeded(["@よい おやすみなさいー"], source=indexer.SOURCE_COMMENT)
    result = tmp_db.search_scenes("おやすみ", [indexer.SOURCE_COMMENT])
    # 画面に出す本文は原文のまま。誰への返信かは読めていなければならない。
    assert _bodies(result) == ["@よい おやすみなさいー"]


def test_search_scenes_cuts_the_target_at_a_known_name_with_a_space(
        tmp_db, tmp_db_path, seeded):
    """表示名に空白があっても、名前の後半で引っかからないこと。"""
    tmp_db.flush()
    with tmp_db._lock:
        tmp_db._conn.execute(
            "INSERT INTO users (identity_key, nickname) VALUES ('k1', 'Maiza Santos')")
        tmp_db._conn.commit()
    seeded(["@Maiza Santos please gift"], source=indexer.SOURCE_COMMENT)
    assert tmp_db.search_scenes("Santos", [indexer.SOURCE_COMMENT])["total"] == 0
    assert tmp_db.search_scenes("gift", [indexer.SOURCE_COMMENT])["total"] == 1
