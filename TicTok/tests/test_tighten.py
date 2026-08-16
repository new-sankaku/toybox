"""間の詰め(media/tighten)の計画と、silencedetectの読み取り。

実際のencodeは合成素材で確認済み(12秒/無音2箇所 -> 6.53秒、h264 30fps CFR)。ここで見るのは
その手前の判断で、壊れても出力は出来てしまう部分である:

  1. 落とすのは無音の**真ん中**で、両端は残す(語頭・語尾が欠けて聞こえるのを防ぐ)
  2. 詰めるに値しない無音は詰めない(下限未満・落とせる量が僅か)
  3. 落とすものが無ければ区間は全体1つ。呼び出し側が再encodeを省ける形で返る
  4. 末尾まで続く無音の ``silence_end`` は開始と対にならない並びで来る
"""

import pytest

from tictok.media import tighten


def test_cut_is_taken_from_the_middle_of_the_silence():
    plan = tighten.plan_keeps(
        12.0, [{"start": 3.0, "end": 6.0}],
        min_silence_seconds=1.2, keep_seconds=0.5)
    # 無音3.0秒のうち0.5秒を残す。残す位置は両端(前0.25秒・後0.25秒)。
    assert plan["keeps"] == [(0.0, 3.25), (5.75, 12.0)]
    assert plan["removed_seconds"] == pytest.approx(2.5)
    assert plan["kept_seconds"] == pytest.approx(9.5)
    assert plan["cuts"] == 1


def test_short_silences_are_left_alone():
    plan = tighten.plan_keeps(
        12.0, [{"start": 3.0, "end": 3.8}],
        min_silence_seconds=1.2, keep_seconds=0.25)
    assert plan["cuts"] == 0
    assert plan["keeps"] == [(0.0, 12.0)]
    assert plan["removed_seconds"] == pytest.approx(0.0)


def test_silence_that_barely_exceeds_the_kept_gap_is_not_cut():
    """接合を1つ増やす代償に見合わない詰めはしない。"""
    length = tighten.MIN_REMOVAL_SECONDS / 2.0
    plan = tighten.plan_keeps(
        12.0, [{"start": 3.0, "end": 4.5 + length}],
        min_silence_seconds=1.2, keep_seconds=1.5)
    assert plan["cuts"] == 0


def test_silence_running_past_the_end_is_clamped_to_the_duration():
    """報告された無音が尺を超えていても、落とすのは実在する範囲だけ。末尾側に残る
    0.25秒は規則どおりの「残す半分」で、shortが音の切れ目で終わる余韻になる。"""
    plan = tighten.plan_keeps(
        12.0, [{"start": 9.0, "end": 14.0}],
        min_silence_seconds=1.2, keep_seconds=0.5)
    assert plan["keeps"] == [(0.0, 9.25), (11.75, 12.0)]
    assert plan["kept_seconds"] == pytest.approx(9.5)


def test_multiple_silences_produce_one_keep_each_side():
    plan = tighten.plan_keeps(
        12.0, [{"start": 3.0, "end": 6.0}, {"start": 8.0, "end": 10.0}],
        min_silence_seconds=1.2, keep_seconds=0.5)
    assert plan["keeps"] == [(0.0, 3.25), (5.75, 8.25), (9.75, 12.0)]
    assert plan["cuts"] == 2


def test_select_expression_is_a_union_of_intervals():
    expression = tighten._select_expression([(0.0, 3.25), (5.75, 12.0)])
    assert expression == "between(t,0.000,3.250)+between(t,5.750,12.000)"


def test_silence_log_is_read_as_pairs():
    text = (
        "[silencedetect @ 0000] silence_start: 3.019\n"
        "[silencedetect @ 0000] silence_end: 6.014 | silence_duration: 2.995\n"
        "[silencedetect @ 0000] silence_start: 9.009\n"
        "[silencedetect @ 0000] silence_end: 12.005 | silence_duration: 2.996\n"
    )
    assert tighten.parse_silence_log(text) == [
        {"start": 3.019, "end": 6.014}, {"start": 9.009, "end": 12.005}]


def test_silence_end_without_a_start_is_recovered_from_the_duration():
    """開始を取り逃した末尾の無音を捨てると、末尾の間だけが詰められない。"""
    text = "[silencedetect @ 0000] silence_end: 12.0 | silence_duration: 3.0\n"
    assert tighten.parse_silence_log(text) == [{"start": 9.0, "end": 12.0}]


def test_negative_silence_start_is_clamped_to_zero():
    text = ("[silencedetect @ 0000] silence_start: -0.012\n"
            "[silencedetect @ 0000] silence_end: 2.5 | silence_duration: 2.512\n")
    assert tighten.parse_silence_log(text) == [{"start": 0.0, "end": 2.5}]
