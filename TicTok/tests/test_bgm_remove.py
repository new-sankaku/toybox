"""BGM除去(出力から話し声だけを残す)の境界。

実処理はGPUと別venvが要るのでtestでは動かさない。ここで守るのは、その周りにある
「動かす前に決まっていること」である。

  1. 使えない構成のまま受け付けないこと。掛からなかった出力が ``.nobgm`` を名乗ると、
     file名が中身の嘘をつく(一覧は名前からしか素性を読めない)
  2. BGM除去した出力が、同じ範囲のBGM入りと別のfileになること
  3. 掛けていないことも含めてlogのctxに残ること
"""
import pytest
from fastapi import HTTPException

from tictok.media.clipper import clip_path, parse_clip_name
from tictok.record import bgm_remove


# ===== 出力名 =====
# 同じ範囲からBGM入り・BGM無しの両方を出せる必要がある。片方が片方を上書きすると、
# 「BGMを消して出し直したら元が消えた」という失い方をする。


def test_bgm_removed_clip_is_a_separate_file(tmp_path):
    src = tmp_path / "00042_u_20250101_120000.mp4"
    plain = clip_path(src, 10.0, 20.0, "見どころ")
    nobgm = clip_path(src, 10.0, 20.0, "見どころ", suffix="nobgm")
    assert plain != nobgm
    assert nobgm.name.endswith(".nobgm.mp4")


def test_bgm_removed_name_is_readable_as_its_own_kind():
    """一覧はfile名からしか素性を読めない。規約外に落ちると絞り込みから消える。"""
    parsed = parse_clip_name("00042_u_20250101_120000_000010-000020.nobgm.mp4")
    assert parsed is not None
    assert parsed["kind"] == "nobgm"
    assert (parsed["start"], parsed["end"]) == (10.0, 20.0)


def test_bgm_removed_keeps_the_existing_variant_mark(tmp_path):
    """用途の印とBGM除去の印は積み重なる。片方が片方を消すと、別用途の成果物が同名になる。"""
    src = tmp_path / "00042_u_20250101_120000.mp4"
    out = clip_path(src, 10.0, 20.0, None, suffix="short.nobgm")
    assert out.name.endswith(".short.nobgm.mp4")


# ===== 投入時のcheck =====


def test_disabled_is_reported_not_silently_skipped(monkeypatch):
    monkeypatch.setattr(bgm_remove.config, "get_bgm_remove_enabled", lambda: False)
    reason = bgm_remove.unavailable_reason()
    assert reason and "TICTOK_BGM_REMOVE_ENABLED" in reason


def test_missing_interpreter_is_reported(monkeypatch):
    monkeypatch.setattr(bgm_remove.config, "get_bgm_remove_enabled", lambda: True)
    monkeypatch.setattr(bgm_remove.config, "get_bgm_remove_python",
                        lambda: "does/not/exist/python.exe")
    reason = bgm_remove.unavailable_reason()
    assert reason and "TICTOK_BGM_REMOVE_PYTHON" in reason


def test_request_is_rejected_when_unavailable(monkeypatch):
    """使えない構成で要求されたら、queueへ載せずにその場で断る。"""
    from tictok.api import media_jobs

    monkeypatch.setattr(bgm_remove.config, "get_bgm_remove_enabled", lambda: False)
    with pytest.raises(HTTPException) as caught:
        media_jobs._clip_remove_bgm(True)
    assert caught.value.status_code == 400
    # 掛けない要求は、使えない構成でも通る(既存の切り出しを止めない)。
    assert media_jobs._clip_remove_bgm(False) is False


def test_available_config_passes(monkeypatch, tmp_path):
    interpreter = tmp_path / "python.exe"
    interpreter.write_text("", encoding="utf-8")
    monkeypatch.setattr(bgm_remove.config, "get_bgm_remove_enabled", lambda: True)
    monkeypatch.setattr(bgm_remove.config, "get_bgm_remove_python", lambda: str(interpreter))
    assert bgm_remove.unavailable_reason() is None


# ===== logのctx =====


def test_describe_states_both_outcomes():
    """掛けていないことも明示的に残す。key自体が無いと、古いlogと区別できない。"""
    assert bgm_remove.describe(False) == {"bgm_removed": False}
    applied = bgm_remove.describe(True)
    assert applied["bgm_removed"] is True
    assert applied["bgm_model"]
