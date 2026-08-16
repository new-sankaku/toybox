"""short の題名・説明・hashtag・表紙位置(ai_analysis.analyze_clip_meta)。

章立てと同じ約束がここでも中心にある — **秒はmodelに書かせない**。表紙の位置はmodelが
選んだ行番号から、こちら側がsegmentの ``start`` を引いて決める。壊れると「それらしいが
その瞬間を指していない表紙」が出て、そこへseekして初めて分かる種類の誤りになる。

  1. 表紙の秒は行番号から引く。応答に秒が入っていても使わない
  2. 範囲外の行番号は近い行へ寄せずに落とす(表紙なしで返る)
  3. 題名・説明の上限は復号後に確定させる(cacheの値と画面の値を同じにする)
  4. hashtagは語だけへ均す(「#」付きで返ってきても二重にしない)
  5. 範囲に掛かる発話は端がはみ出していても採る
"""

import json

import pytest

from tictok.ai import ai_analysis


@pytest.fixture
def ai_on(monkeypatch):
    monkeypatch.setenv("TICTOK_AI_ENABLED", "1")
    monkeypatch.setenv("TICTOK_AI_MODEL", "test-model")


def segments() -> list:
    return [
        {"start": 0.0, "end": 5.0, "text": "始まる前の雑談"},
        {"start": 9.0, "end": 12.0, "text": "この後とんでもないことが起きます"},
        {"start": 12.0, "end": 16.0, "text": "うわ、今の見た？"},
        {"start": 16.0, "end": 21.0, "text": "もう一回やってみるね"},
        {"start": 40.0, "end": 44.0, "text": "別の話題"},
    ]


def stub_chat(monkeypatch, payload: dict):
    async def fake(messages, schema, schema_name):
        assert schema_name == "clip_meta"
        return json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(ai_analysis, "_chat", fake)


def test_clip_target_id_keeps_milliseconds():
    """吸着で範囲は数百ms動く。秒で丸めると別の範囲が同じcache行を指す。"""
    assert ai_analysis.clip_target_id(7, 12.3456, 45.0) == "7:12.346-45.000"
    assert ai_analysis.clip_target_id(7, 12.3, 45.0) != ai_analysis.clip_target_id(7, 12.4, 45.0)


def test_clip_lines_takes_segments_that_straddle_the_edge():
    lines = ai_analysis.clip_lines(segments(), 10.0, 20.0)
    assert [line["text"] for line in lines] == [
        "この後とんでもないことが起きます", "うわ、今の見た？", "もう一回やってみるね"]


def test_clip_lines_drops_segments_outside_and_empty_text():
    rows = [{"start": 0.0, "end": 5.0, "text": "   "},
            {"start": 30.0, "end": 35.0, "text": "範囲外"}]
    assert ai_analysis.clip_lines(rows, 10.0, 20.0) == []


def test_hashtags_are_reduced_to_bare_words():
    cleaned = ai_analysis._clean_hashtags(
        ["#配信", "配信", " 神 回 ", "#", "", "切り抜き#雑談"], 5)
    # 「#」を落とし、重複と空を捨て、語中で切れる文字より前だけを残す。
    assert cleaned == ["配信", "神", "切り抜き"]


def test_hashtags_stop_at_the_configured_limit():
    assert ai_analysis._clean_hashtags(["a", "b", "c", "d"], 2) == ["a", "b"]


@pytest.mark.asyncio
async def test_cover_seconds_come_from_the_line_not_from_the_model(ai_on, monkeypatch):
    stub_chat(monkeypatch, {"title": "とんでもないことが起きた",
                            "description": "配信中の出来事", "hashtags": ["切り抜き"],
                            "cover_line": 2, "cover_seconds": 999.0})
    result = await ai_analysis.analyze_clip_meta(segments(), 10.0, 20.0)
    # 2行目は 12.0秒 のsegment。応答の 999.0 は使わない。
    assert result["cover_line"] == 2
    assert result["cover_seconds"] == 12.0


@pytest.mark.asyncio
async def test_out_of_range_cover_line_leaves_the_cover_unset(ai_on, monkeypatch):
    stub_chat(monkeypatch, {"title": "題名", "description": "説明",
                            "hashtags": [], "cover_line": 99})
    result = await ai_analysis.analyze_clip_meta(segments(), 10.0, 20.0)
    assert result["cover_line"] is None
    assert result["cover_seconds"] is None


@pytest.mark.asyncio
async def test_title_and_description_are_clamped_after_decoding(ai_on, monkeypatch):
    monkeypatch.setenv("TICTOK_AI_CLIP_TITLE_CHARS", "5")
    monkeypatch.setenv("TICTOK_AI_CLIP_DESCRIPTION_CHARS", "8")
    stub_chat(monkeypatch, {"title": "あ" * 40, "description": "い" * 40,
                            "hashtags": [], "cover_line": 1})
    result = await ai_analysis.analyze_clip_meta(segments(), 10.0, 20.0)
    assert result["title"] == "あ" * 5
    assert result["description"] == "い" * 8


@pytest.mark.asyncio
async def test_empty_title_is_an_error_not_an_empty_short(ai_on, monkeypatch):
    stub_chat(monkeypatch, {"title": "  ", "description": "説明",
                            "hashtags": [], "cover_line": 1})
    with pytest.raises(ai_analysis.AIError):
        await ai_analysis.analyze_clip_meta(segments(), 10.0, 20.0)


@pytest.mark.asyncio
async def test_range_without_speech_is_refused(ai_on, monkeypatch):
    async def boom(*args, **kwargs):
        raise AssertionError("発話が無い範囲でmodelを呼んではならない")

    monkeypatch.setattr(ai_analysis, "_chat", boom)
    with pytest.raises(ai_analysis.AIError):
        await ai_analysis.analyze_clip_meta(segments(), 100.0, 120.0)


@pytest.mark.asyncio
async def test_disabled_ai_raises_instead_of_inventing_a_title(monkeypatch):
    monkeypatch.setenv("TICTOK_AI_ENABLED", "0")
    with pytest.raises(ai_analysis.AIError):
        await ai_analysis.analyze_clip_meta(segments(), 10.0, 20.0)


def test_schema_bounds_the_cover_line_to_the_lines_presented():
    schema = ai_analysis._clip_json_schema(3)
    assert schema["properties"]["cover_line"]["maximum"] == 3
    assert schema["required"] == ["title", "description", "hashtags", "cover_line"]
