import json
import sqlite3
import threading
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

import pytest

from tictok.core import layout
from tictok.record.recorder import timing_path
from tictok.search import cutlist_export, indexer
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
    assert out["match"] == '("a OR b" AND "ramen")'


def test_parse_bare_or_still_switches_to_or_mode():
    out = parse("aaa OR bbb")
    assert out["or_mode"] is True
    assert out["match"] == '("aaa" OR "bbb")'


def test_parse_phrase_that_is_only_or_is_a_term_not_an_operator():
    out = parse('"OR"')
    assert out["or_mode"] is False
    assert out["terms"] == ["OR"]
    assert out["match"] is None
    assert out["like_all"] == ["%OR%"]


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


# ===== cutlist_export =====


FPS30 = Fraction(30, 1)
FPS2997 = Fraction(30000, 1001)


def _media(fps=FPS30, width=1080, height=1920, duration=None,
           audio_channels=None, audio_rate=None):
    return {"fps": fps, "width": width, "height": height, "duration": duration,
            "audio_channels": audio_channels, "audio_rate": audio_rate}


def _cut(unique_id="s", start=0.0, end=1.0, fps=FPS30, **extra):
    cut = {"unique_id": unique_id, "start": start, "end": end,
           "media": _media(fps) if fps is not None else None}
    cut.update(extra)
    return cut


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0.0, "00:00:00:00"),
        (1.5, "00:00:01:15"),
        (59.0, "00:00:59:00"),
        (60.0, "00:01:00:00"),
        (3661.0, "01:01:01:00"),
        (-5.0, "00:00:00:00"),
    ],
)
def test_timecode_at_boundaries(seconds, expected):
    assert cutlist_export._timecode(seconds, FPS30) == expected


def test_timecode_rounds_frames_rather_than_truncating():
    assert cutlist_export._timecode(0.98, FPS30) == "00:00:00:29"
    # 29.7 frame は切り上げられるので、境界直前でも次の秒へ繰り上がる。
    assert cutlist_export._timecode(0.99, FPS30) == "00:00:01:00"
    assert cutlist_export._timecode(1.0, FPS30) == "00:00:01:00"


def test_is_drop_frame_only_for_ntsc_fractional_rates():
    assert cutlist_export.is_drop_frame(FPS2997) is True
    assert cutlist_export.is_drop_frame(Fraction(60000, 1001)) is True
    assert cutlist_export.is_drop_frame(FPS30) is False
    assert cutlist_export.is_drop_frame(Fraction(60, 1)) is False


def test_drop_frame_labels_skip_two_at_each_minute_but_not_the_tenth():
    tc = cutlist_export._timecode_frames
    # 最初の1分は取りこぼしが無く、1800 frame目で ;00 と ;01 を飛ばして ;02 になる。
    assert tc(1799, FPS2997) == "00:00:59;29"
    assert tc(1800, FPS2997) == "00:01:00;02"
    # 10分ごとは飛ばさないので、label と実経過時間がここで揃う。
    assert tc(17982, FPS2997) == "00:10:00;00"


def test_drop_frame_uses_semicolon_separator():
    assert ";" in cutlist_export._timecode(1.0, FPS2997)
    assert ";" not in cutlist_export._timecode(1.0, FPS30)


def test_to_csv_header_and_row_shape():
    csv_text = cutlist_export.to_csv([
        _cut(unique_id="streamer", filename="a.mp4", path="C:/rec/a.mp4",
             start=12.5, end=20.0, label="best bit"),
    ])
    lines = csv_text.strip().split("\n")
    assert lines[0].split(",") == [
        "unique_id", "filename", "path", "start_seconds", "end_seconds",
        "duration_seconds", "fps", "start_timecode", "end_timecode", "label",
    ]
    assert lines[1] == (
        "streamer,a.mp4,C:/rec/a.mp4,12.500,20.000,7.500,30.000000,"
        "00:00:12:15,00:00:20:00,best bit"
    )


def test_to_csv_defaults_optional_fields_to_empty_and_quotes_commas():
    csv_text = cutlist_export.to_csv([_cut(label="a,b")])
    row = csv_text.strip().split("\n")[1]
    assert row == 's,,,0.000,1.000,1.000,30.000000,00:00:00:00,00:00:01:00,"a,b"'


def test_to_csv_keeps_seconds_but_blanks_timecode_when_fps_is_unmeasurable():
    # CSVは秒を無損失で持つので、fpsが測れなくても行自体は正しい。推測値では埋めない。
    csv_text = cutlist_export.to_csv([_cut(start=0.0, end=1.0, fps=None)])
    row = csv_text.strip().split("\n")[1]
    assert row == "s,,,0.000,1.000,1.000,,,,"


def test_to_csv_empty_cuts_still_emits_header_only():
    assert cutlist_export.to_csv([]).strip().count("\n") == 0


def test_to_edl_accumulates_the_record_timeline():
    edl = cutlist_export.to_edl([
        _cut(filename="a.mp4", start=10.0, end=12.0),
        _cut(filename="b.mp4", start=100.0, end=103.0),
    ])
    lines = edl.split("\n")
    assert lines[0] == "TITLE: tictok_cutlist"
    assert lines[1] == "FCM: NON-DROP FRAME"
    events = [ln for ln in lines if ln.startswith("00")]
    assert events[0].endswith("00:00:10:00 00:00:12:00 00:00:00:00 00:00:02:00")
    # 2本目のrecord inは1本目の尺(2s)から始まる。
    assert events[1].endswith("00:01:40:00 00:01:43:00 00:00:02:00 00:00:05:00")
    assert events[0].startswith("001  AX       AA/V  C")
    assert events[1].startswith("002  AX       AA/V  C")


def test_to_edl_marks_fcm_drop_frame_for_ntsc_material():
    edl = cutlist_export.to_edl([_cut(start=0.0, end=1.0, fps=FPS2997)])
    assert edl.split("\n")[1] == "FCM: DROP FRAME"


def test_to_edl_omits_source_and_comment_lines_when_absent():
    edl = cutlist_export.to_edl([_cut()])
    assert "* FROM CLIP NAME: " in edl
    assert "* SOURCE FILE:" not in edl
    assert "* COMMENT:" not in edl


def test_to_edl_custom_title():
    edl = cutlist_export.to_edl([_cut()], title="mine")
    assert edl.startswith("TITLE: mine\nFCM: NON-DROP FRAME")


def test_to_edl_refuses_empty_cuts():
    with pytest.raises(cutlist_export.CutlistExportError):
        cutlist_export.to_edl([], title="mine")


def test_to_edl_refuses_material_whose_fps_could_not_be_measured():
    # 推測fpsでtimecodeを作らない、が設計上の要件。
    with pytest.raises(cutlist_export.CutlistExportError) as excinfo:
        cutlist_export.to_edl([_cut(filename="a.mp4", fps=None)])
    assert "a.mp4" in str(excinfo.value)


def test_to_edl_refuses_mixed_frame_rates():
    # EDLはlist全体で1つのtimebaseしか持てないため混在は書き出さない。
    with pytest.raises(cutlist_export.CutlistExportError) as excinfo:
        cutlist_export.to_edl([
            _cut(filename="a.mp4", fps=FPS30),
            _cut(filename="b.mp4", fps=FPS2997),
        ])
    assert "FCPXML" in str(excinfo.value)


def test_to_edl_clamps_reversed_range_on_the_record_side_only():
    # 実挙動の記録: record側はmax(0)で潰れるが、source out < source in はそのまま出る。
    edl = cutlist_export.to_edl([_cut(start=10.0, end=5.0)])
    event = [ln for ln in edl.split("\n") if ln.startswith("001")][0]
    assert event.endswith("00:00:10:00 00:00:05:00 00:00:00:00 00:00:00:00")


def test_timecode_frame_field_follows_the_measured_fps():
    """同じ秒でもfpsが違えばframe桁は変わる。実録画は25/30/60fpsが混ざっており、
    既定値で決め打ちするとNLE上の位置が素材ごとにずれる。"""
    assert cutlist_export._timecode(22.5, Fraction(25, 1)) == "00:00:22:12"
    assert cutlist_export._timecode(22.5, FPS30) == "00:00:22:15"
    assert cutlist_export._timecode(22.5, Fraction(60, 1)) == "00:00:22:30"


def test_to_edl_timecode_follows_the_measured_fps():
    """source側もrecord側も、素材の実測fpsで数える。"""
    edl = cutlist_export.to_edl([_cut(start=10.0, end=32.5, fps=Fraction(25, 1))])
    event = [ln for ln in edl.split("\n") if ln.startswith("001")][0]
    assert event.endswith("00:00:10:00 00:00:32:12 00:00:00:00 00:00:22:12")


def test_to_fcpxml_is_well_formed_and_lands_on_frame_boundaries(tmp_path):
    # pathは実在しなくてよいが、file:// URLにできる絶対pathである必要がある
    # (絶対pathの綴りはOSで違うので、tmp_pathから組む)。
    src = str(tmp_path / "a.mp4")
    xml = cutlist_export.to_fcpxml([
        _cut(filename="a.mp4", path=src, start=10.0, end=20.0,
             label="笑 <確認> & test"),
        _cut(filename="a.mp4", path=src, start=30.0, end=35.5),
    ])
    root = ET.fromstring(xml)
    assert root.get("version") == cutlist_export.FCPXML_VERSION
    # 同じfileを2度切ってもasset/formatは共有する。id重複はFCP側で読み込みが壊れる。
    ids = [el.get("id") for el in root.find("resources")]
    assert len(ids) == len(set(ids))
    assert len(root.findall(".//asset")) == 1
    # 時刻はframe数から組み立てた有理秒。frameDurationの整数倍でない値はNLEが丸める。
    clips = root.findall(".//asset-clip")
    assert [c.get("offset") for c in clips] == ["0s", "300/30s"]
    assert [c.get("start") for c in clips] == ["300/30s", "900/30s"]
    assert [c.get("duration") for c in clips] == ["300/30s", "165/30s"]
    assert clips[0].find("note").text == "笑 <確認> & test"


def test_to_fcpxml_carries_a_format_per_source_so_mixed_rates_are_fine(tmp_path):
    """EDLと違いFCPXMLは素材ごとにframe rateを持てる。混在はこちらで出す。"""
    xml = cutlist_export.to_fcpxml([
        _cut(filename="a.mp4", path=str(tmp_path / "a.mp4"), fps=Fraction(25, 1)),
        _cut(filename="b.mp4", path=str(tmp_path / "b.mp4"), fps=Fraction(60, 1)),
    ])
    root = ET.fromstring(xml)
    formats = {el.get("id"): el.get("frameDuration") for el in root.iter("format")}
    assert set(formats.values()) == {"1/25s", "1/60s"}
    clips = root.findall(".//asset-clip")
    assert formats[clips[0].get("format")] == "1/25s"
    assert formats[clips[1].get("format")] == "1/60s"


def test_to_fcpxml_keeps_ntsc_rational_frame_duration_and_marks_drop_frame(tmp_path):
    # 29.97はfloatに落とすと30000/1001へ戻らない。有理数のまま持つことが要件。
    xml = cutlist_export.to_fcpxml([_cut(path=str(tmp_path / "a.mp4"), fps=FPS2997)])
    root = ET.fromstring(xml)
    assert root.find(".//format").get("frameDuration") == "1001/30000s"
    assert root.find(".//sequence").get("tcFormat") == "DF"


def test_to_fcpxml_refuses_material_whose_fps_could_not_be_measured():
    with pytest.raises(cutlist_export.CutlistExportError) as excinfo:
        cutlist_export.to_fcpxml([_cut(filename="a.mp4", fps=None)])
    assert "a.mp4" in str(excinfo.value)


async def test_resolve_timebases_probes_each_file_once(monkeypatch, tmp_path):
    calls = []

    async def fake_probe(path):
        calls.append(Path(path))
        return _media(Fraction(25, 1)), None

    monkeypatch.setattr(cutlist_export, "_probe_media", fake_probe)
    first, second = tmp_path / "a.mp4", tmp_path / "b.mp4"
    resolved = await cutlist_export.resolve_timebases([
        _cut(path=str(first), fps=None),
        _cut(path=str(first), fps=None),
        _cut(path=str(second), fps=None),
    ])
    # 同じfileを何度切ってもffprobeは1回。cut listは同一録画から何十本も出る。
    assert calls == [first, second]
    assert [c["media"]["fps"] for c in resolved] == [Fraction(25, 1)] * 3


async def test_resolve_timebases_leaves_unprobeable_cuts_unmeasured(monkeypatch, tmp_path):
    """ffprobeが失敗した素材へ既定fpsを与えない。frame基準の形式側で止めるため、
    未解決はNoneのまま残す。"""
    async def fail_probe(path):
        return None, "映像streamがありません"

    monkeypatch.setattr(cutlist_export, "_probe_media", fail_probe)
    resolved = await cutlist_export.resolve_timebases(
        [_cut(path=str(tmp_path / "a.mp4"), fps=None)])
    assert resolved[0]["media"] is None
    # 失敗理由は潰さずcutへ載せる。汎用errorに畳むとuserが原因を切り分けられない。
    assert resolved[0]["media_error"] == "映像streamがありません"
    # pathが無いcutはffprobeを起こしようがないので、そもそも測りに行かない。
    pathless = await cutlist_export.resolve_timebases([_cut(fps=None)])
    assert pathless[0]["media"] is None
    assert pathless[0]["media_error"] == "cutにfileのpathがありません"


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


def test_search_scenes_source_filter_is_applied(tmp_db, seeded):
    seeded(["転写のラーメン"], source=indexer.SOURCE_STT)
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
