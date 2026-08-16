"""切り抜きへ添える字幕file(sidecar)。

ここが守るのは1点に尽きる — **時刻の原点は要求した開始位置ではない**。stream copyの
切り出しは要求より手前のkeyframeから始まるので(実録画で最大6.1秒)、要求値を引いた字幕は
全cueがその差だけずれる。ずれた字幕は「それらしいが合っていない」形で出るため、再生して
みるまで誰も気付けない。

併せて、書けない場合に黙って0件にしない(理由を名乗る)ことと、装飾つきASSが焼き込みと
同じpresetから組まれることを守る。
"""
from pathlib import Path

import pytest

from tictok.media import clip_subtitles
from tictok.media.clipper import parse_clip_name
from tictok.record import subtitles, telop_styles
from tictok.record import video_overlay as vo
from tictok.record.transcription import TIMEMAP_VERSION


def _transcript(segments, version=TIMEMAP_VERSION) -> dict:
    return {"segments": segments, "timemap_version": version, "duration": 3600.0}


def _settings() -> dict:
    settings = dict.fromkeys(vo.OVERLAY_KEYS, 0)
    settings.update({
        "video_overlay_subtitle_font_size": 48,
        "video_overlay_subtitle_position_percent": 80,
        "video_overlay_subtitle_style": telop_styles.DEFAULT_STYLE_VALUE,
        "video_overlay_subtitle_animation": 1,
        "video_overlay_subtitle_max_lines": 4,
        "video_overlay_min_height": 720,
    })
    return settings


def _clip(path: Path, *, start=100.0, end=130.0, origin=97.5, duration=32.5) -> dict:
    """make_clipの戻り値のうち、字幕fileの書き出しが読む欄だけを持つ。

    ``origin``(実開始)が ``start``(要求)より手前なのが既定の形である — copy経路では常に
    こうなる。両者が同じ値のtestだけを書くと、原点の取り違えを1件も落とせない。"""
    return {"path": str(path), "start": start, "end": end,
            "actual_start_seconds": origin, "output_duration_seconds": duration}


# ===== 窓の切り出しと原点 =====


def test_slice_shifts_to_the_actual_start_not_the_request():
    segments = [{"start": 100.0, "end": 103.0, "text": "はじめ"},
                {"start": 120.0, "end": 122.0, "text": "なか"}]
    # 実開始97.5秒 = 要求100秒より2.5秒手前から始まる切り抜き。
    out = subtitles.slice_segments(segments, 97.5, 32.5)
    assert [(s["start"], s["end"]) for s in out] == [(2.5, 5.5), (22.5, 24.5)]


def test_slice_keeps_the_speech_that_straddles_each_edge():
    """窓の端に掛かる発話は落とさず、時刻だけ内側へ詰める。

    切り抜きの中で確かに聞こえている言葉なので、落とすと聞こえているのに字幕が無い区間が
    できる。textは切らない(どこで切れたかは分からず、按分は時刻の捏造になる)。"""
    segments = [{"start": 90.0, "end": 101.0, "text": "またぎ頭"},
                {"start": 125.0, "end": 140.0, "text": "またぎ尻"}]
    out = subtitles.slice_segments(segments, 97.5, 32.5)
    assert [(s["start"], s["end"], s["text"]) for s in out] == [
        (0.0, 3.5, "またぎ頭"), (27.5, 32.5, "またぎ尻")]


def test_slice_drops_what_is_not_in_the_clip():
    segments = [{"start": 10.0, "end": 20.0, "text": "前"},
                {"start": 500.0, "end": 505.0, "text": "後"},
                {"start": 105.0, "end": 106.0, "text": "中"}]
    out = subtitles.slice_segments(segments, 97.5, 32.5)
    assert [s["text"] for s in out] == ["中"]


def test_slice_moves_word_times_and_drops_words_outside():
    segments = [{"start": 95.0, "end": 106.0, "text": "あいう",
                 "words": [{"start": 95.0, "end": 96.0, "text": "あ"},
                           {"start": 100.0, "end": 101.0, "text": "い"},
                           {"start": 105.0, "end": 106.0, "text": "う"}]}]
    out = subtitles.slice_segments(segments, 97.5, 32.5)
    assert [(w["text"], w["start"]) for w in out[0]["words"]] == [("い", 2.5), ("う", 7.5)]


def test_slice_without_duration_does_not_clamp_the_tail():
    """実尺を測れなかった回は打ち切らない。推測で窓を閉じると、鳴っている発話を落とす。"""
    segments = [{"start": 100.0, "end": 400.0, "text": "長い"}]
    out = subtitles.slice_segments(segments, 97.5, None)
    assert out[0]["end"] == 302.5


# ===== 書式 =====


def test_parse_formats_refuses_unknown_spelling():
    assert clip_subtitles.parse_formats("srt, ass ,srt") == ("srt", "ass")
    assert clip_subtitles.parse_formats("") == ()
    with pytest.raises(ValueError):
        clip_subtitles.parse_formats("srt,sub")


def test_subtitle_files_are_named_like_the_clip():
    """字幕fileはmp4と同じ名前で拡張子だけが違う。NLEもplayerもこれで自動的に紐づく。"""
    parsed = parse_clip_name("00400_p_20260729_220601_025716-025719_ガンダム.srt")
    assert parsed["kind"] == "subtitle" and parsed["subtitle_format"] == "srt"
    assert parsed["label"] == "ガンダム"
    nobgm = parse_clip_name("00400_p_20260729_220601_025716-025719.nobgm.ass")
    assert nobgm["kind"] == "subtitle" and nobgm["subtitle_format"] == "ass"


# ===== 書き出し =====


async def test_writes_srt_on_the_clip_axis(tmp_path):
    out = tmp_path / "00400_p_20260729_220601_000140-000210.mp4"
    out.write_bytes(b"")
    report = await clip_subtitles.write_for_clip(
        _clip(out), _transcript([{"start": 100.0, "end": 103.0, "text": "はじめ"}]),
        _settings(), formats=("srt",))
    assert report["written"] == ["srt"]
    body = out.with_suffix(".srt").read_text(encoding="utf-8")
    # 要求(100秒)ではなく実開始(97.5秒)からの2.5秒。ここが要求値になる退行を落とす。
    assert "00:00:02,500 --> 00:00:05,500" in body
    assert "はじめ" in body
    assert not list(tmp_path.glob(".*.tmp"))


async def test_anchor_cue_pins_the_head_without_moving_the_speech(tmp_path):
    """先頭が0秒でない切り抜きは、0秒へ空のcueを1件足す。

    NLEによっては字幕fileをdragで置くと先頭cueが落とした位置へ吸着し、頭の無音ぶんだけ全cueが
    早くなる(DaVinci Resolve)。錨があれば先頭cueの位置が成果物の先頭と一致する。発話のcueは
    1つも動かないことを併せて見る — 動かすなら時刻の捏造になる。"""
    out = tmp_path / "00400_p_20260729_220601_000140-000210.mp4"
    out.write_bytes(b"")
    settings = _settings()
    settings["clip_subtitle_anchor"] = 1
    report = await clip_subtitles.write_for_clip(
        _clip(out), _transcript([{"start": 100.0, "end": 103.0, "text": "はじめ"}]),
        settings, formats=("srt", "vtt"))
    assert report["anchor"] is True
    srt = out.with_suffix(".srt").read_text(encoding="utf-8")
    # 錨は0秒から、長さは上限(0.5秒)まで。中身は半角空白なので字は出ない。
    assert srt.startswith("1\n00:00:00,000 --> 00:00:00,500\n \n")
    # 発話は実開始からの2.5秒のまま。番号だけが1つ後ろへ送られる。
    assert "2\n00:00:02,500 --> 00:00:05,500\nはじめ" in srt
    vtt = out.with_suffix(".vtt").read_text(encoding="utf-8")
    assert "00:00:00.000 --> 00:00:00.500\n \n" in vtt


async def test_no_anchor_when_the_head_is_already_at_zero(tmp_path):
    """先頭が0秒から始まる切り抜きには足さない(足す理由が無く、空のcueが増えるだけ)。"""
    out = tmp_path / "00400_p_20260729_220601_000140-000210.mp4"
    out.write_bytes(b"")
    settings = _settings()
    settings["clip_subtitle_anchor"] = 1
    report = await clip_subtitles.write_for_clip(
        _clip(out), _transcript([{"start": 97.5, "end": 103.0, "text": "はじめ"}]),
        settings, formats=("srt",))
    assert report["anchor"] is False
    assert out.with_suffix(".srt").read_text(encoding="utf-8").startswith(
        "1\n00:00:00,000 --> 00:00:05,500\nはじめ")


async def test_anchor_can_be_turned_off(tmp_path):
    out = tmp_path / "00400_p_20260729_220601_000140-000210.mp4"
    out.write_bytes(b"")
    settings = _settings()
    settings["clip_subtitle_anchor"] = 0
    report = await clip_subtitles.write_for_clip(
        _clip(out), _transcript([{"start": 100.0, "end": 103.0, "text": "はじめ"}]),
        settings, formats=("srt",))
    assert report["anchor"] is False
    assert out.with_suffix(".srt").read_text(encoding="utf-8").startswith(
        "1\n00:00:02,500 --> 00:00:05,500\nはじめ")


async def test_writes_decorated_ass_from_the_burn_in_preset(tmp_path, monkeypatch):
    # 実寸の取得とfontの実測は外部process。装飾がpresetから来ることを見たいので、その2つ
    # だけを固定する(組み立てそのものは本物を通す)。
    monkeypatch.setattr(vo, "_probe_dimensions",
                        lambda *a, **k: _resolved((720, 1280, 30.0)))
    monkeypatch.setattr(vo, "telop_metrics", lambda cfg: _resolved(((1.0, 0.55), None)))
    monkeypatch.setattr(vo, "ensure_telop_font", lambda style: Path("assets/fonts/x.otf"))
    out = tmp_path / "00400_p_20260729_220601_000140-000210.mp4"
    out.write_bytes(b"")
    settings = _settings()
    report = await clip_subtitles.write_for_clip(
        _clip(out), _transcript([{"start": 100.0, "end": 103.0, "text": "はじめ"}]),
        settings, formats=("ass",))
    assert report["written"] == ["ass"]
    body = out.with_suffix(".ass").read_text(encoding="utf-8")
    style = telop_styles.style_for(settings["video_overlay_subtitle_style"])
    # 座標系は成果物の実寸。別の寸法だと、playerが比で伸縮して位置も字の大きさもずれる。
    assert "PlayResX: 720" in body and "PlayResY: 1280" in body
    # 書体・色・縁は焼き込みと同じpresetの行がそのまま入る。
    for line in telop_styles.style_lines(style, vo._subtitle_font(vo.overlay_settings(settings), 1280)):
        assert line in body
    assert "Dialogue: " in body and "0:00:02.50,0:00:05.50" in body
    assert report["font_family"] == style.font_family


def _resolved(value):
    """awaitできる済みの値。monkeypatchでasync関数を差し替えるために使う。"""
    async def _call():
        return value

    return _call()


async def test_refuses_variants_whose_axis_is_not_guaranteed(tmp_path):
    """焼き込み出力・Up出力から切った物には出さない。合っている保証が無いため。"""
    out = tmp_path / "00400_p_20260729_220601_000140-000210.mp4"
    out.write_bytes(b"")
    report = await clip_subtitles.write_for_clip(
        _clip(out), _transcript([{"start": 100.0, "end": 103.0, "text": "はじめ"}]),
        _settings(), formats=("srt",), variant="overlay")
    assert report["reason"] == clip_subtitles.REASON_VARIANT
    assert report["message"] and not out.with_suffix(".srt").exists()


async def test_refuses_a_transcript_from_an_old_time_map(tmp_path):
    out = tmp_path / "00400_p_20260729_220601_000140-000210.mp4"
    out.write_bytes(b"")
    report = await clip_subtitles.write_for_clip(
        _clip(out), _transcript([{"start": 100.0, "end": 103.0, "text": "はじめ"}], version=1),
        _settings(), formats=("srt",))
    assert report["reason"] == clip_subtitles.REASON_TIMEMAP_STALE
    assert not out.with_suffix(".srt").exists()


async def test_says_why_when_there_is_nothing_to_write(tmp_path):
    out = tmp_path / "00400_p_20260729_220601_000140-000210.mp4"
    out.write_bytes(b"")
    empty = await clip_subtitles.write_for_clip(
        _clip(out), None, _settings(), formats=("srt",))
    assert empty["reason"] == clip_subtitles.REASON_NO_TRANSCRIPT
    outside = await clip_subtitles.write_for_clip(
        _clip(out), _transcript([{"start": 5.0, "end": 6.0, "text": "遠い"}]),
        _settings(), formats=("srt",))
    assert outside["reason"] == clip_subtitles.REASON_NO_SEGMENTS
    assert not out.with_suffix(".srt").exists()
