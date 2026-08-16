"""short 1本ぶんの範囲確定(media/clip_range)。

この層が壊れると、出来上がったshortを再生するまで誰も気付かない(尺は正しく、mp4も出来て
いて、ただ話の途中で始まっている)。そのため見るのは「出力が在るか」ではなく、確定の
過程そのものである:

  1. 山は範囲の中央ではなく ``peak_position`` の位置に来る
  2. 吸着先が遠ければ**動かさない**(遠くの境界へ引っ張って山を押し出さない)
  3. 無音spanの向き — 無音の明けが開始側、無音の始まりが終了側
  4. 章の外へは出さない。どの章にも入らない候補では章で挟まない
  5. 尺が範囲外の候補は**捨てる**。縮めて通さない
  6. 重なりは確定後の範囲で見る(候補の点では離れていても範囲は膨らむ)
"""

import pytest

from tictok.media import clip_range


def preset(**overrides) -> dict:
    base = {
        "min_seconds": 15.0, "target_seconds": 30.0, "max_seconds": 60.0,
        "peak_position": 0.65, "snap_speech": 1, "snap_silence": 1,
        "snap_max_shift_seconds": 3.0, "chapter_clamp": 1, "tighten": 0,
    }
    base.update(overrides)
    return base


def candidate(start: float, end: float, zscore: float = 3.0) -> dict:
    return {"start": start, "end": end, "zscore": zscore}


def test_peak_sits_at_the_configured_position():
    """山は中央ではなく ``peak_position`` の位置。頭に助走が付くことがshortの前提。"""
    plan = clip_range.plan_range(candidate(100, 110), preset(), duration=600)
    assert plan["peak"] == 105.0
    assert plan["seconds"] == 30.0
    # 山の手前が 30*0.65 = 19.5秒、後ろが 10.5秒。
    assert plan["start"] == pytest.approx(85.5)
    assert plan["end"] == pytest.approx(115.5)


def test_edges_snap_to_speech_boundaries():
    segments = [{"start": 84.0, "end": 90.0}, {"start": 110.0, "end": 117.0}]
    plan = clip_range.plan_range(
        candidate(100, 110), preset(), duration=600, segments=segments)
    assert plan["start"] == pytest.approx(84.0)
    assert plan["end"] == pytest.approx(117.0)
    assert plan["snapped"] == {"start": clip_range.SNAP_SPEECH,
                               "end": clip_range.SNAP_SPEECH}


def test_far_boundaries_do_not_move_the_edge():
    """吸着先が上限より遠ければ動かさない。動かすと山が範囲の外へ出る。"""
    segments = [{"start": 60.0, "end": 70.0}, {"start": 130.0, "end": 140.0}]
    plan = clip_range.plan_range(
        candidate(100, 110), preset(), duration=600, segments=segments)
    assert plan["start"] == pytest.approx(85.5)
    assert plan["end"] == pytest.approx(115.5)
    assert plan["snapped"] == {"start": None, "end": None}


def test_speech_segment_end_is_not_an_opening_point():
    """segmentの ``end`` を開始位置に採ると、次の発話の途中から始まる。開始側の吸着先は
    ``start`` だけであること。"""
    starts, ends = clip_range.speech_boundaries([{"start": 10.0, "end": 20.0}])
    assert starts == [10.0]
    assert ends == [20.0]


def test_silence_boundaries_point_the_other_way():
    """無音spanは発話segmentと向きが逆 — 明けた瞬間が開始、始まる瞬間が終了。"""
    starts, ends = clip_range.silence_boundaries([{"start": 84.0, "end": 86.0}])
    assert starts == [86.0]
    assert ends == [84.0]

    plan = clip_range.plan_range(
        candidate(100, 110), preset(snap_speech=0), duration=600,
        silences=[{"start": 84.0, "end": 86.0}, {"start": 116.0, "end": 118.0}])
    assert plan["start"] == pytest.approx(86.0)
    assert plan["end"] == pytest.approx(116.0)
    assert plan["snapped"] == {"start": clip_range.SNAP_SILENCE,
                               "end": clip_range.SNAP_SILENCE}


def test_range_stays_inside_the_chapter():
    chapters = [{"start": 100.0, "end": 200.0, "title": "本題"}]
    plan = clip_range.plan_range(
        candidate(100, 110), preset(), duration=600, chapters=chapters)
    assert plan["start"] == pytest.approx(100.0)
    # 手前で当たったぶんは後ろへ回す(窓を短くしない)。
    assert plan["seconds"] == pytest.approx(30.0)
    assert plan["chapter"] == {"start": 100.0, "end": 200.0}


def test_candidate_outside_every_chapter_is_not_clamped():
    """章立ては録画全体を覆う保証を持たない。どの章にも入らない山を近い章へ寄せると、
    根拠の無い位置で挟むことになる。"""
    chapters = [{"start": 300.0, "end": 400.0, "title": "別の話題"}]
    plan = clip_range.plan_range(
        candidate(100, 110), preset(), duration=600, chapters=chapters)
    assert plan["chapter"] is None
    assert plan["start"] == pytest.approx(85.5)


def test_too_short_after_snapping_is_rejected():
    """吸着で縮んで下限を割ったら捨てる。縮めたまま通すと話の途中で切れたshortが出る。"""
    segments = [{"start": 90.0, "end": 112.0}]
    plan = clip_range.plan_range(
        candidate(100, 110), preset(min_seconds=25.0, snap_max_shift_seconds=5.0),
        duration=600, segments=segments)
    assert plan["rejected"] == clip_range.REJECT_TOO_SHORT
    assert plan["seconds"] == pytest.approx(22.0)


def test_snap_that_breaks_the_upper_limit_is_partially_undone():
    """上限を超えたら、遠くへ動いた側の吸着だけを取り消す。両方戻すと吸着が効かない録画と
    区別が付かなくなる。"""
    segments = [{"start": 81.5, "end": 90.0}, {"start": 110.0, "end": 116.5}]
    plan = clip_range.plan_range(
        candidate(100, 110), preset(max_seconds=32.0, snap_max_shift_seconds=5.0),
        duration=600, segments=segments)
    assert plan.get("rejected") is None
    assert plan["start"] == pytest.approx(85.5)          # 遠い側(4.0秒)の吸着を取り消した
    assert plan["end"] == pytest.approx(116.5)           # 近い側(1.0秒)は残る
    assert plan["snapped"] == {"start": None, "end": clip_range.SNAP_SPEECH}


def test_too_long_is_rejected_unless_tightening_is_on():
    # 両側が3秒ずつ外へ吸着して36秒になる。片側を取り消しても33秒で上限に収まらない。
    segments = [{"start": 87.0, "end": 95.0}, {"start": 115.0, "end": 123.0}]
    args = dict(duration=600, segments=segments)
    strict = clip_range.plan_range(
        candidate(100, 110), preset(max_seconds=32.0, snap_max_shift_seconds=5.0,
                                    peak_position=0.5),
        **args)
    assert strict["rejected"] == clip_range.REJECT_TOO_LONG

    loose = clip_range.plan_range(
        candidate(100, 110), preset(max_seconds=32.0, snap_max_shift_seconds=5.0,
                                    peak_position=0.5, tighten=1),
        **args)
    assert loose.get("rejected") is None
    assert loose["needs_tighten"] is True


def test_no_room_at_the_edge_of_the_recording():
    plan = clip_range.plan_range(candidate(2, 6), preset(), duration=10.0)
    assert plan["rejected"] == clip_range.REJECT_NO_ROOM
    assert plan["room_seconds"] == pytest.approx(10.0)


def test_overlapping_ranges_keep_the_stronger_candidate():
    """候補の点は12秒離れていても、確定後の範囲は重なる。判定は範囲で行うこと。"""
    result = clip_range.plan_ranges(
        [candidate(100, 110, zscore=2.5), candidate(112, 122, zscore=4.0)],
        preset(), duration=600)
    assert [r["peak"] for r in result["ranges"]] == [117.0]
    assert [r["rejected"] for r in result["rejected"]] == [clip_range.REJECT_OVERLAP]


def test_ranges_already_taken_are_avoided_but_not_returned():
    taken = [{"start": 80.0, "end": 120.0}]
    result = clip_range.plan_ranges(
        [candidate(100, 110)], preset(), duration=600, taken=taken)
    assert result["ranges"] == []
    assert result["rejected"][0]["rejected"] == clip_range.REJECT_OVERLAP
    assert result["rejected"][0]["overlaps"] == {"start": 80.0, "end": 120.0}


def test_limit_stops_after_enough_ranges():
    candidates = [candidate(100 + i * 200, 110 + i * 200, zscore=5.0 - i)
                  for i in range(4)]
    result = clip_range.plan_ranges(candidates, preset(), duration=2000, limit=2)
    assert len(result["ranges"]) == 2
    # 強い順に採るので、残るのは zscore の大きい2件。
    assert [r["peak"] for r in result["ranges"]] == [105.0, 305.0]
