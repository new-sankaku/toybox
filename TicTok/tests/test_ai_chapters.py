import json

import pytest

from tictok.ai import ai_analysis
from tictok.ai.ai_analysis import AIError
from tictok.record import subtitles
from tictok.record.transcription import TIMEMAP_VERSION


def seg(start, end, text):
    return {"start": start, "end": end, "text": text}


@pytest.fixture
def ai_on(monkeypatch):
    monkeypatch.setenv("TICTOK_AI_ENABLED", "1")
    monkeypatch.setenv("TICTOK_AI_MODEL", "test-model")


def transcript(segments, timemap_version=TIMEMAP_VERSION):
    return {"segments": segments, "timemap_version": timemap_version}


# --------------------------------------------------------------------------
# chunking
# --------------------------------------------------------------------------


def test_chapter_chunks_never_splits_a_segment(monkeypatch):
    monkeypatch.setenv("TICTOK_AI_CHAPTER_CHUNK_CHARS", "60")
    segments = [seg(i * 10.0, i * 10.0 + 5.0, "x" * 20) for i in range(6)]
    chunks = ai_analysis.chapter_chunks(segments)
    assert sum(len(c) for c in chunks) == len(segments)
    assert [s for chunk in chunks for s in chunk] == segments


def test_chapter_chunks_single_oversized_segment_is_kept_whole(monkeypatch):
    monkeypatch.setenv("TICTOK_AI_CHAPTER_CHUNK_CHARS", "10")
    segments = [seg(0.0, 1.0, "y" * 500)]
    assert ai_analysis.chapter_chunks(segments) == [segments]


# --------------------------------------------------------------------------
# 候補の採り方: modelが返すのは行番号だけで、秒はsegmentから引く
# --------------------------------------------------------------------------


def test_select_candidates_takes_time_from_segments_not_from_model():
    chunk = [seg(10.0, 12.0, "a"), seg(30.0, 32.0, "b")]
    data = {"chapters": [{"line": 2, "title": "話題B", "start": 999.0}]}
    got = ai_analysis._select_candidates(data, chunk)
    assert got == [{"start": 30.0, "title": "話題B", "quote": "b"}]


def test_select_candidates_drops_out_of_range_lines():
    chunk = [seg(10.0, 12.0, "a")]
    data = {"chapters": [{"line": 0, "title": "前"}, {"line": 9, "title": "後"},
                         {"line": 1, "title": "有効"}]}
    assert [c["title"] for c in ai_analysis._select_candidates(data, chunk)] == ["有効"]


def test_select_candidates_dedupes_same_segment_and_sorts():
    chunk = [seg(50.0, 51.0, "a"), seg(10.0, 11.0, "b")]
    data = {"chapters": [{"line": 1, "title": "一度目"}, {"line": 1, "title": "二度目"},
                         {"line": 2, "title": "早い方"}]}
    got = ai_analysis._select_candidates(data, chunk)
    assert [(c["start"], c["title"]) for c in got] == [(10.0, "早い方"), (50.0, "一度目")]


def test_select_candidates_drops_malformed_entries():
    chunk = [seg(1.0, 2.0, "a")]
    data = {"chapters": ["not a dict", {"line": "x", "title": "t"}, {"line": 1, "title": "  "}]}
    assert ai_analysis._select_candidates(data, chunk) == []


# --------------------------------------------------------------------------
# 間引き
# --------------------------------------------------------------------------


def test_thin_drops_chapters_closer_than_min_gap():
    chapters = [{"start": 0.0}, {"start": 20.0}, {"start": 100.0}]
    assert [c["start"] for c in ai_analysis._thin(chapters, 60.0, 10)] == [0.0, 100.0]


def test_thin_caps_count():
    chapters = [{"start": float(i * 100)} for i in range(10)]
    assert len(ai_analysis._thin(chapters, 60.0, 3)) == 3


# --------------------------------------------------------------------------
# 区間の確定
# --------------------------------------------------------------------------


def test_finalize_extends_first_chapter_over_leading_silence_only():
    segments = [seg(5.0, 6.0, "a"), seg(100.0, 101.0, "b")]
    chapters = [{"start": 5.0, "title": "冒頭", "quote": "a"}]
    got = ai_analysis._finalize(chapters, segments, 200.0)
    assert got[0]["start"] == 0.0


def test_finalize_does_not_pull_a_later_first_chapter_back_to_zero():
    """1章目が最初のsegmentより後ろから始まるとき、0秒へ寄せてはならない。

    寄せると、その章が実際に始まる前の別の話題の区間まで1章目の表題が覆い、引用も自分の
    開始位置を指さなくなる(実測で踏んだ壊れ方の回帰test)。"""
    segments = [seg(0.0, 1.0, "冒頭の別の話題"), seg(107.0, 108.0, "神の写真の撮り方")]
    chapters = [{"start": 107.0, "title": "神の写真の撮り方", "quote": "神の写真の撮り方"}]
    got = ai_analysis._finalize(chapters, segments, 200.0)
    assert got[0]["start"] == 107.0


def test_finalize_sets_end_to_next_start_and_tail_to_duration():
    segments = [seg(0.0, 1.0, "a"), seg(50.0, 51.0, "b")]
    chapters = [{"start": 0.0, "title": "1", "quote": "a"},
                {"start": 50.0, "title": "2", "quote": "b"}]
    got = ai_analysis._finalize(chapters, segments, 300.0)
    assert [(c["start"], c["end"]) for c in got] == [(0.0, 50.0), (50.0, 300.0)]


def test_finalize_falls_back_to_last_segment_end_without_duration():
    segments = [seg(0.0, 1.0, "a"), seg(50.0, 77.0, "b")]
    chapters = [{"start": 0.0, "title": "1", "quote": "a"}]
    assert ai_analysis._finalize(chapters, segments, None)[0]["end"] == 77.0


# --------------------------------------------------------------------------
# 拒否条件
# --------------------------------------------------------------------------


async def test_analyze_chapters_rejects_stale_timemap(ai_on, monkeypatch):
    called = []

    async def boom(*args, **kwargs):
        called.append(1)
        raise AssertionError("時刻mapが古いtranscriptでLLMを呼んではいけない")

    monkeypatch.setattr(ai_analysis, "_chat", boom)
    with pytest.raises(AIError, match="古い時刻map"):
        await ai_analysis.analyze_chapters(
            transcript([seg(0.0, 1.0, "a")], timemap_version=None), 100.0)
    assert not called


async def test_analyze_chapters_rejects_timemap_version_from_the_future(ai_on, monkeypatch):
    async def boom(*args, **kwargs):
        raise AssertionError("現行版でない時刻mapでLLMを呼んではいけない")

    monkeypatch.setattr(ai_analysis, "_chat", boom)
    with pytest.raises(AIError, match="古い時刻map"):
        await ai_analysis.analyze_chapters(
            transcript([seg(0.0, 1.0, "a")], timemap_version=TIMEMAP_VERSION + 1), 100.0)


async def test_analyze_chapters_rejects_transcript_without_usable_segments(ai_on):
    with pytest.raises(AIError, match="使える発話がありません"):
        await ai_analysis.analyze_chapters(
            transcript([{"start": None, "end": None, "text": "x"}]), 100.0)


async def test_analyze_chapters_requires_ai_enabled(monkeypatch):
    monkeypatch.setenv("TICTOK_AI_ENABLED", "0")
    with pytest.raises(AIError, match="AI機能が無効"):
        await ai_analysis.analyze_chapters(transcript([seg(0.0, 1.0, "a")]), 100.0)


# --------------------------------------------------------------------------
# map-reduce 全体
# --------------------------------------------------------------------------


def stub_chat(monkeypatch, replies):
    """_chatを差し替え、schema_nameごとに用意した応答を順に返す。"""
    calls = []

    async def fake(messages, schema, schema_name):
        calls.append((schema_name, messages))
        queue = replies[schema_name]
        return json.dumps(queue.pop(0), ensure_ascii=False)

    monkeypatch.setattr(ai_analysis, "_chat", fake)
    return calls


async def test_analyze_chapters_single_chunk_skips_the_merge_step(ai_on, monkeypatch):
    monkeypatch.setenv("TICTOK_AI_CHAPTER_CHUNK_CHARS", "100000")
    monkeypatch.setenv("TICTOK_AI_CHAPTER_MIN_SECONDS", "10")
    segments = [seg(0.0, 5.0, "冒頭"), seg(100.0, 105.0, "次の話題")]
    calls = stub_chat(monkeypatch, {
        "chapter_candidates": [{"chapters": [{"line": 1, "title": "冒頭"},
                                             {"line": 2, "title": "次の話題"}]}],
    })
    result = await ai_analysis.analyze_chapters(transcript(segments), 200.0)
    assert [name for name, _ in calls] == ["chapter_candidates"]
    assert result["reduced"] is False
    assert [(c["start"], c["title"]) for c in result["chapters"]] == [
        (0.0, "冒頭"), (100.0, "次の話題")]


async def test_analyze_chapters_merge_step_cannot_invent_times(ai_on, monkeypatch):
    """reduce段は「どの候補を残すか」だけを決める。候補外のidは落とし、残した候補の時刻は
    map段で確定したものから動かさない。"""
    monkeypatch.setenv("TICTOK_AI_CHAPTER_CHUNK_CHARS", "40")
    monkeypatch.setenv("TICTOK_AI_CHAPTER_MIN_SECONDS", "10")
    segments = [seg(0.0, 5.0, "あ" * 30), seg(100.0, 105.0, "い" * 30)]
    calls = stub_chat(monkeypatch, {
        "chapter_candidates": [
            {"chapters": [{"line": 1, "title": "前半"}]},
            {"chapters": [{"line": 1, "title": "後半"}]},
        ],
        "chapter_merge": [
            {"chapters": [{"id": 1, "title": "整えた前半"},
                          {"id": 99, "title": "存在しない候補"}]},
        ],
    })
    result = await ai_analysis.analyze_chapters(transcript(segments), 200.0)
    assert [name for name, _ in calls] == [
        "chapter_candidates", "chapter_candidates", "chapter_merge"]
    assert result["reduced"] is True
    assert result["candidate_count"] == 2
    # 候補外のidは章にならない。残った章の時刻はsegment由来のまま。
    assert [(c["start"], c["title"]) for c in result["chapters"]] == [(0.0, "整えた前半")]
    assert result["chapters"][0]["quote"] == "あ" * 30


async def test_analyze_chapters_raises_when_no_boundary_found(ai_on, monkeypatch):
    monkeypatch.setenv("TICTOK_AI_CHAPTER_CHUNK_CHARS", "100000")
    stub_chat(monkeypatch, {"chapter_candidates": [{"chapters": []}]})
    with pytest.raises(AIError, match="話題の切れ目"):
        await ai_analysis.analyze_chapters(transcript([seg(0.0, 5.0, "a")]), 200.0)


# --------------------------------------------------------------------------
# 書き出し
# --------------------------------------------------------------------------


def test_usable_chapters_drops_incomplete_entries():
    chapters = [{"start": 0.0, "end": 10.0, "title": "ok"},
                {"start": None, "end": 10.0, "title": "no start"},
                {"start": 10.0, "end": 10.0, "title": "zero length"},
                {"start": 20.0, "end": 30.0, "title": "   "}]
    assert subtitles.usable_chapters(chapters) == [{"start": 0.0, "end": 10.0, "title": "ok"}]


def test_usable_chapters_clamps_to_media_duration():
    chapters = [{"start": 0.0, "end": 999.0, "title": "a"},
                {"start": 500.0, "end": 600.0, "title": "過ぎた章"}]
    got = subtitles.usable_chapters(chapters, media_duration=100.0)
    assert got == [{"start": 0.0, "end": 100.0, "title": "a"}]


def test_to_vtt_chapters_numbers_cues():
    chapters = [{"start": 0.0, "end": 61.5, "title": "第1"},
                {"start": 61.5, "end": 120.0, "title": "第2"}]
    assert subtitles.to_vtt_chapters(chapters) == (
        "WEBVTT\n\n"
        "1\n00:00:00.000 --> 00:01:01.500\n第1\n\n"
        "2\n00:01:01.500 --> 00:02:00.000\n第2\n"
    )


def test_to_chapter_text_uses_short_timecode_below_one_hour():
    chapters = [{"start": 0.0, "end": 61.0, "title": "第1"},
                {"start": 61.0, "end": 3700.0, "title": "第2"},
                {"start": 3700.0, "end": 4000.0, "title": "第3"}]
    assert subtitles.to_chapter_text(chapters) == "0:00 第1\n1:01 第2\n1:01:40 第3\n"


def test_to_chapter_text_empty_input():
    assert subtitles.to_chapter_text([]) == ""


def test_render_chapters_rejects_unknown_format():
    with pytest.raises(ValueError):
        subtitles.render_chapters("srt", [])


def test_every_declared_chapter_format_can_be_rendered():
    """CHAPTER_FORMATSはAPIが受け付ける形式の一覧でもある。render_chapters側と食い違うと、
    endpointが受理したあとで500になる。"""
    chapters = [{"start": 0.0, "end": 10.0, "title": "第1"}]
    for fmt in subtitles.CHAPTER_FORMATS:
        assert subtitles.render_chapters(fmt, chapters)
