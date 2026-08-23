# -*- coding: utf-8 -*-
"""無言の早送りの速度計画。

外すと「速く流れてしまった所」が観る側に残らない(飛ばしていないので、聞き逃したことに
気付けるのは違和感だけ)。声の前後を守る条件と、判定できない録画では計画を出さない条件を
1つずつ見る。声の区間はVAD(media/voice.py)が出す — 語の時刻で代用していた版は速い区間の
4.4〜43.8%が実際には声だった。
"""
import pytest

from tictok.media import pace


def spans(*pairs):
    return [{"start": float(a), "end": float(b)} for a, b in pairs]


def test_gaps_between_speech_become_fast_stretches():
    plan = pace.pace_plan(30.0, spans((0, 1), (20, 21)))
    # 声の後ろは0.1秒、手前は0.3秒(既定)。
    assert plan["fast"] == [{"start": 1.1, "end": 19.7}, {"start": 21.1, "end": 30.0}]
    assert plan["speech_spans"] == 2


def test_pause_inside_a_sentence_is_left_alone():
    """声の間0.3秒は既定(前後0.1秒+最短0.5秒)では速度を変えない。文中の息継ぎで速度が
    往復すると、詰まる時間より切り替えの方が目に付く。"""
    plan = pace.pace_plan(20.0, spans((0, 1), (1.3, 2)))
    assert [s for s in plan["fast"] if s["end"] <= 2.5] == []


def test_the_guard_before_speech_is_thicker_than_the_one_after():
    """語頭が速い速度で流れるのは聞き手が戻らないと取り返せない唯一の失敗。速度を上げるのが
    遅れる側は一瞬を損するだけなので、厚みは手前に寄せる(実測で手前0.1→0.3秒の代償は
    実効倍率0.08)。最初の版で実際に報告された症状がこれである。"""
    plan = pace.pace_plan(60.0, spans((10, 11)))
    assert plan["fast"][0]["end"] == pytest.approx(9.7)    # 声の0.3秒手前で等速へ戻す
    assert plan["fast"][1]["start"] == pytest.approx(11.1)  # 声の0.1秒後に速くする
    assert plan["onset_guard_seconds"] > plan["lead_seconds"]


def test_speech_is_never_inside_a_fast_stretch():
    plan = pace.pace_plan(60.0, spans((0, 1), (10, 11), (30, 31)))
    for span in plan["fast"]:
        for word in ((0, 1), (10, 11), (30, 31)):
            assert span["end"] <= word[0] or span["start"] >= word[1]


def test_reactions_are_content_not_a_gap():
    """語が無くても反応(笑い・叫び・息を呑む・拍手)が在る所は速くしない。実測では
    class listを笑いだけから全部入りへ広げても総速度は0.03〜0.08倍しか落ちない —
    取りこぼす方が高く付く。"""
    reactions = [{"start": 10.0, "end": 12.0}]
    plan = pace.pace_plan(30.0, spans((0, 1)), reactions)
    assert plan["reaction_spans"] == 1
    for span in plan["fast"]:
        assert span["end"] <= 10.0 or span["start"] >= 12.0


def test_no_plan_without_speech_spans():
    """声の区間が分からない録画では計画を出さない。それらしい計画を出すより、画面が理由を
    名乗れる空の方が良い。"""
    assert pace.pace_plan(30.0, None)["fast"] == []
    assert pace.pace_plan(30.0, [])["fast"] == []


def test_no_plan_without_a_duration():
    """尺が分からない録画(実測53/454件)では最後の語で代用しない。語の後ろに続く時間が
    内容として等速で残り、効かない理由が読めなくなる。"""
    assert pace.pace_plan(None, spans((0, 1)))["fast"] == []
    assert pace.pace_plan(0.0, spans((0, 1)))["fast"] == []


def test_overlapping_speech_does_not_split_a_gap():
    """区間は重なって届くことがある。束ねずに隙間を取ると、実際には声が在る所が速い区間
    として出る。"""
    plan = pace.pace_plan(30.0, spans((0, 5), (2, 8), (7, 9)))
    assert plan["fast"] == [{"start": 9.1, "end": 30.0}]


def test_effective_rate_uses_both_lanes():
    plan = pace.pace_plan(100.0, spans((0, 50)))
    content = plan["content_seconds"]
    assert pace.effective_rate(plan, 1.6) == pytest.approx(
        100.0 / (content / 1.6 + plan["fast_seconds"] / 6.0), abs=0.01)


def test_effective_rate_is_none_without_a_plan():
    assert pace.effective_rate(pace.pace_plan(30.0, None), 1.6) is None


def test_reaction_spans_read_the_reaction_series_not_the_laugh_one():
    """笑いの列で代用しない。反応を見ているつもりで笑いしか見ていない状態が黙って続く。"""
    from tictok.media import laugh_audio

    profile = {"interval_seconds": 1.0,
               "probs": [0.9, 0.9, 0.0],            # 笑い
               "reaction_probs": [0.0, 0.0, 0.9]}   # 反応(叫び等)
    assert laugh_audio.reaction_spans(profile, 0.5) == [{"start": 2.0, "end": 3.0}]
    assert laugh_audio.laugh_spans(profile, 0.5) == [{"start": 0.0, "end": 2.0}]


def test_reaction_spans_are_empty_for_an_old_sidecar():
    """反応の列を持たない古いsidecarは空を返す(笑いで埋めない)。"""
    from tictok.media import laugh_audio

    assert laugh_audio.reaction_spans({"interval_seconds": 1.0, "probs": [0.9]}) == []
