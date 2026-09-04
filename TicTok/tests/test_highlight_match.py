"""highlightのsegment単位の突き合わせ(:mod:`tictok.media.highlight_match`)。

ここのtestは**ffmpegもDBも使わない**。指紋(hashと時刻の配列)を合成し、moduleの判断だけを
確かめる。実素材での検証は ``scripts/highlight_poc.py run`` と doc/HIGHLIGHT_MATCH.md の
「実物のhighlightで判ったこと」にある。
"""
import pathlib

import numpy as np
import pytest

from tictok.media import audio_fingerprint as afp
from tictok.media import highlight_match as hm


def _frames(seconds: float) -> int:
    return int(round(seconds / afp.FRAME_SECONDS))


def _query(seconds: float, seed: int, per_second: int = 24) -> afp.Fingerprint:
    """highlight側の指紋。時刻はhighlightの先頭起点のframe番号。"""
    rng = np.random.default_rng(seed)
    frames = _frames(seconds)
    n = max(1, int(seconds * per_second))
    times = np.sort(rng.integers(0, frames, n)).astype(np.int32)
    # hashが衝突すると票が二重に入るので、一意にしておく。
    hashes = rng.choice(1 << 24, size=n, replace=False).astype(np.uint32)
    return afp.Fingerprint(hashes, times, frames, n)


def _index(parts, seconds: float, noise: int = 0, seed: int = 7) -> afp.Fingerprint:
    """録画側の指紋。``parts`` は ``(query, base秒)`` の列で、その位置へ置く。"""
    rng = np.random.default_rng(seed)
    hashes = [np.zeros(0, np.uint32)]
    times = [np.zeros(0, np.int32)]
    for query, base in parts:
        hashes.append(query.hashes)
        times.append(query.times + _frames(base))
    if noise:
        hashes.append(rng.integers(1 << 24, 1 << 30, noise).astype(np.uint32))
        times.append(rng.integers(0, _frames(seconds), noise).astype(np.int32))
    return afp.sort_by_hash(afp.Fingerprint(
        np.concatenate(hashes), np.concatenate(times), _frames(seconds), 0))


# ===== 窓の切り出し =====

def test_slice_query_keeps_absolute_times():
    """切った後も時刻がhighlightの先頭起点のままなので、alignのoffsetがそのままbaseになる。

    ここがmoduleの土台である。窓ごとに音を切り出して指紋を作り直す作りに戻すと、offsetが
    窓の先頭起点になり、baseを出すのに窓の開始秒を引く必要が出る(そして引き忘れる)。"""
    query = _query(20.0, seed=1)
    index = _index([(query, 100.0)], 600.0, noise=5000)
    for start in (0.0, 6.0, 12.0):
        sub = hm._slice_query(query, start, start + 6.0)
        assert sub.hashes.size > 0
        assert sub.times.min() >= _frames(start)
        found = afp.align(sub, index)
        assert found is not None
        assert found.offset_seconds == pytest.approx(100.0, abs=afp.FRAME_SECONDS)


def test_window_starts_covers_the_tail():
    """末尾の窓を落とすと最後のgift演出が丸ごと消える。"""
    starts = hm._window_starts(10.0, 6.0, 1.5)
    assert starts[0] == 0.0
    assert starts[-1] + 6.0 == pytest.approx(10.0)
    assert hm._window_starts(3.0, 6.0, 1.5) == [0.0]


# ===== gift窓のsub-index =====

def test_gift_windows_merges_overlaps_and_clips():
    gifts = [{"media_time": 10.0}, {"media_time": 18.0}, {"media_time": 100.0},
             {"media_time": 2.0}]
    windows = hm.gift_windows(gifts, lead=5.0, tail=15.0, span=110.0)
    assert windows == [(0.0, 33.0), (95.0, 110.0)]


def test_restrict_to_windows_keeps_only_the_windows():
    """gift窓への絞り込みは、cacheした配列を切るだけで再decodeしない。"""
    query = _query(4.0, seed=2)
    index = _index([(query, 50.0), (query, 300.0)], 600.0, noise=2000)
    kept = hm.restrict_to_windows(index, [(45.0, 60.0)])
    assert kept.hashes.size < index.hashes.size
    seconds = kept.times * afp.FRAME_SECONDS
    assert seconds.min() >= 45.0 and seconds.max() < 60.0
    # 窓の中の当たりは残り、窓の外(300秒)の当たりは消える。
    assert afp.align(query, kept).offset_seconds == pytest.approx(50.0,
                                                                 abs=afp.FRAME_SECONDS)
    assert hm.restrict_to_windows(index, []).hashes.size == 0


# ===== 系列のlabeling =====

def _scans(rows):
    return [{"start": i * hm.FINE_HOP, "hypotheses": h} for i, h in enumerate(rows)]


def test_label_rejects_a_short_rival_inside_a_run():
    """得票だけで窓ごとにargmaxを採ると列が飛ぶ。切り替えの費用がgift演出の連続性を守る。

    実測でぶつかった形をそのまま置いてある ―― 同じ曲を別の日にも流していると、その区間の
    音は2本の録画に同じ形で在り、途中の数窓だけ相手が上回る。"""
    run = [(1154, 500.0, 60, 20.0)]
    rival = [(1084, 8000.0, 150, 40.0), (1154, 500.0, 60, 20.0)]
    scans = _scans([run, run, rival, rival, rival, run, run])
    table = hm._cluster_bases(scans, hm.BASE_TOLERANCE)
    labels = hm._label(scans, table, hm.LABEL_SWITCH_COST, hm.LABEL_NONE_COST)
    assert len({label for label in labels}) == 1
    assert labels[0][0] == 1154


def test_label_bridges_a_short_dropout_inside_one_fragment():
    """同じbaseに挟まれた短い無得票はgift演出を割らない。

    giftのアニメの音が配信の音を覆う区間では票が落ちる。gift演出は連続しているので、そこで
    切ってはいけない ―― 実素材では2窓ぶん(1.0秒)の穴が普通に空く。"""
    run = [(1154, 500.0, 60, 20.0)]
    scans = _scans([run, run, [], [], run, run])
    table = hm._cluster_bases(scans, hm.BASE_TOLERANCE)
    labels = hm._label(scans, table, hm.LABEL_SWITCH_COST, hm.LABEL_NONE_COST)
    assert len(set(labels)) == 1 and labels[0][0] == 1154


def test_label_marks_a_long_dropout_as_none():
    """跨げないほど長く票が無ければ「どの録画でもない」にする。gift演出の間の穴はこうなる。"""
    run = [(1154, 500.0, 60, 20.0)]
    other = [(1153, 900.0, 60, 20.0)]
    scans = _scans([run, run, [], [], [], [], other, other])
    table = hm._cluster_bases(scans, hm.BASE_TOLERANCE)
    labels = hm._label(scans, table, hm.LABEL_SWITCH_COST, hm.LABEL_NONE_COST)
    assert labels[0][0] == 1154 and labels[-1][0] == 1153
    assert None in labels[2:6]


def test_cluster_bases_merges_the_jitter_between_windows():
    """baseは窓のまたぎで数十msずれる。そのままkeyにすると同じgift演出が複数の状態へ割れる。"""
    scans = _scans([[(1, 500.00, 40, 9.0)], [(1, 500.03, 40, 9.0)], [(1, 512.00, 40, 9.0)]])
    table = hm._cluster_bases(scans, hm.BASE_TOLERANCE)
    assert len(table[1]) == 2
    assert hm._state_of(table, 1, 500.00) == hm._state_of(table, 1, 500.03)
    assert hm._state_of(table, 1, 512.00) != hm._state_of(table, 1, 500.00)


def test_runs_places_the_boundary_between_window_centres():
    scans = _scans([[], [], [], []])
    labels = [(1, 0), (1, 0), (2, 0), (2, 0)]
    runs = hm._runs(labels, scans, hm.FINE_WINDOW, 4.0)
    assert len(runs) == 2
    assert runs[0]["start"] == 0.0 and runs[1]["end"] == 4.0
    # 中心は start + window/2。1窓目の run は index 1 で終わり、2つ目は index 2 で始まる。
    assert runs[0]["end"] == pytest.approx((0.5 + hm.FINE_WINDOW / 2 + 1.0
                                            + hm.FINE_WINDOW / 2) / 2)
    assert runs[1]["start"] == runs[0]["end"]


# ===== 穴を映像で埋める =====
#
# 実素材の数字は doc/HIGHLIGHT_MATCH.md にある。ここで確かめるのは判断だけで、frameは読まない。


def _prepared(start: float, end: float, cand=None, base: float = 0.0) -> dict:
    """``_build_segments`` が作る途中の形。``cand`` が None の項目が「穴」である。"""
    item = {"run": {"state": None if cand is None else (1, 0), "start": start, "end": end},
            "cand": cand}
    if cand is not None:
        item["base"] = base
    return item


def test_self_similarity_is_one_for_a_still_scene():
    """同じ絵が続くあいだ相関は1。別の絵に変わったframeだけが谷になる。"""
    rng = np.random.default_rng(3)
    still = rng.normal(size=(1, 4, 4)).astype(np.float32)
    other = rng.normal(size=(1, 4, 4)).astype(np.float32)
    frames = hm._normalize_frames(np.concatenate([np.repeat(still, 4, axis=0), other,
                                                  np.repeat(still, 4, axis=0)]))
    sim = hm._self_similarity(frames, 1)
    assert sim[0] == pytest.approx(1.0, abs=1e-5)
    assert sim[3] < 0.5 and sim[4] < 0.5


def test_shots_are_the_gaps_between_the_walls():
    assert hm._shots([(2.0, 2.6), (8.0, 8.4)], 12.0) == [(0.0, 2.0), (2.6, 8.0), (8.4, 12.0)]


def test_home_shot_is_where_the_fragment_spends_most_of_itself():
    """端で決めない。gift演出の尻が次の場面へはみ出していても、家は元の場面のままである。"""
    shots = [(0.0, 10.0), (10.4, 20.0)]
    assert hm._home_shot(shots, (2.0, 10.9)) == (0.0, 10.0)
    assert hm._home_shot(shots, (9.8, 18.0)) == (10.4, 20.0)


def test_extend_gaps_fills_the_hole_up_to_the_wall():
    """穴に壁が在れば、そこまで伸ばして止まる。"""
    left, gap = _prepared(0.0, 10.0, cand=object()), _prepared(10.0, 14.0)
    out = hm._extend_gaps([left, gap], [(11.0, 11.4)], 14.0)
    assert left["run"]["end"] == pytest.approx(11.0)
    assert gap["run"]["start"] == pytest.approx(11.0)
    assert len(out) == 2


def test_extend_gaps_does_not_reach_into_the_next_shot():
    """尻が次の場面へ0.5秒はみ出しているだけのgift演出に、その場面を渡さない。

    実測で Strong Finish のgift演出がこの形で次の場面(4.13秒)を丸ごと吸収し、後半4秒が別の
    場面(全画面のavatar)になった。"""
    left, gap = _prepared(0.0, 10.5, cand=object()), _prepared(10.5, 15.0)
    hm._extend_gaps([left, gap], [(9.8, 10.0)], 15.0)
    assert left["run"]["end"] == pytest.approx(10.5)
    assert gap["run"] == {"state": None, "start": 10.5, "end": 15.0}


def test_extend_gaps_gives_the_shot_to_the_longer_side():
    """両隣が同じ場面に居るときは、その場面との重なりが長い側が全部を採る。"""
    left = _prepared(0.0, 10.2, cand=object())      # 家は [0.0, 9.6]、この場面には0.2秒だけ
    gap = _prepared(10.2, 14.0)
    right = _prepared(14.0, 19.0, cand=object())    # 家は [10.0, 20.0] で5.0秒
    out = hm._extend_gaps([left, gap, right], [(9.6, 10.0)], 20.0)
    assert left["run"]["end"] == pytest.approx(10.2)
    assert right["run"]["start"] == pytest.approx(10.2)
    assert [item["cand"] for item in out] == [left["cand"], right["cand"]]


def test_extend_gaps_leaves_the_hole_when_both_sides_are_even():
    """重なりが競っているなら、どちらとも言えないので音の境目のまま残す。"""
    left = _prepared(0.0, 10.0, cand=object())
    gap = _prepared(10.0, 14.0)
    right = _prepared(14.0, 24.0, cand=object())
    out = hm._extend_gaps([left, gap, right], [], 24.0)
    assert (left["run"]["end"], right["run"]["start"]) == (10.0, 14.0)
    assert len(out) == 3


def test_extend_gaps_stops_at_the_far_limit():
    """壁が見つからないほど長い穴は、上限までしか伸ばさない。"""
    left, gap = _prepared(0.0, 10.0, cand=object()), _prepared(10.0, 40.0)
    hm._extend_gaps([left, gap], [], 40.0)
    assert left["run"]["end"] == pytest.approx(10.0 + hm.EXTEND_MAX_SECONDS)


def test_guard_switch_drops_a_switch_without_a_wall():
    """繋ぎの裏付けが無い切り替わりは捨てる(gift演出を測っている)。"""
    run = {"start": 27.75, "end": 33.25}
    assert hm._guard_switch([(26.1, 27.5)], run, (29.1, None)) == (None, None)
    # 窓の頭に繋ぎが掛かっていれば、その測りは残す。
    assert hm._guard_switch([(27.6, 28.2)], run, (29.1, None)) == (29.1, None)


# ===== roomの決定 =====

class _Cand(hm._Candidate):
    """指紋も素材も持たない候補。``_pick_room`` が見るのは ``id`` と ``room_key`` だけ。"""

    def __init__(self, rid, session_id, room_id=""):
        super().__init__({"id": rid, "session_id": session_id, "room_id": room_id},
                         None, None, 0.0)


def test_pick_room_narrows_to_the_winner():
    pool = [_Cand(1153, 601, "R1"), _Cand(1154, 601, "R1"), _Cand(1084, 575, "R2")]
    scans = _scans([[(1153, 100.0, 300, 9.0), (1084, 800.0, 50, 4.0)],
                    [(1154, 200.0, 300, 9.0), (1084, 800.0, 50, 4.0)]])
    found = hm._pick_room(scans, pool)
    assert found["room_id"] == "R1" and found["narrowed"] is True
    assert found["session_id"] is None
    assert found["recordings"] == [1153, 1154]


def test_pick_room_keeps_recordings_from_every_session_of_the_room():
    """**接続断で1回の配信が複数sessionに割れる。** sessionで絞ると、highlightのmontageが
    切れ目をまたいだときに片側のgift演出が丸ごと落ちる。

    実測の形をそのまま置いてある ―― room 7677205833033992980 は session 562/563/565/567/569 に
    割れており、録画は 1054/1055/1057/1059/1061 である。票が立つのは 1054 と 1061 だけでも、
    残す候補は同じroomの5本でなければならない。"""
    rooms = {1054: 562, 1055: 563, 1057: 565, 1059: 567, 1061: 569}
    pool = [_Cand(rid, sid, "7677205833033992980") for rid, sid in rooms.items()]
    pool.append(_Cand(1084, 575, "OTHER"))
    scans = _scans([[(1054, 100.0, 300, 9.0)], [(1061, 200.0, 280, 9.0)],
                    [(1084, 800.0, 30, 4.0)]])
    found = hm._pick_room(scans, pool)
    assert found["room_id"] == "7677205833033992980"
    assert found["recordings"] == [1054, 1055, 1057, 1059, 1061]


def test_pick_room_keeps_a_blank_room_id_as_its_own_group():
    """``room_id`` が空のsession(実測5/300)は独立した塊にする。他roomへ混ぜず、
    session_idへ黙って落としもしない ―― 落ちたことが ``label`` と ``session_id`` に出る。"""
    pool = [_Cand(1, 10, ""), _Cand(2, 20, ""), _Cand(3, 30, "R")]
    scans = _scans([[(1, 100.0, 300, 9.0), (2, 200.0, 200, 9.0), (3, 300.0, 20, 4.0)]])
    found = hm._pick_room(scans, pool)
    assert found["room_id"] is None and found["session_id"] == 10
    assert found["recordings"] == [1]
    assert "10" in found["label"]


def test_pick_room_does_not_narrow_without_a_margin():
    """1位が僅差なら絞らない。黙って1位を採ると、録画していない配信のhighlightを
    投げられたときに何かを名乗ってしまう。"""
    pool = [_Cand(1, 10, "A"), _Cand(2, 20, "B")]
    scans = _scans([[(1, 100.0, 100, 9.0), (2, 200.0, 90, 9.0)]])
    found = hm._pick_room(scans, pool)
    assert found["narrowed"] is False and found["reason"]


def test_pick_room_does_not_leak_the_internal_key():
    """塊の鍵はtupleで、画面やstore層が読む形ではない。戻り値へ出さない。"""
    pool = [_Cand(1, 10, "A")]
    found = hm._pick_room(_scans([[(1, 100.0, 100, 9.0)]]), pool)
    assert "key" not in found
    assert set(found) == {"room_id", "session_id", "label", "votes", "runner_up",
                          "narrowed", "recordings", "reason"}


# ===== 境界の追い込み =====

def test_support_marks_only_the_matching_offset():
    query = _query(6.0, seed=3)
    index = _index([(query, 300.0)], 600.0, noise=3000)
    at = hm._support(query, index, _frames(300.0), hm.BOUNDARY_TOLERANCE_FRAMES)
    off = hm._support(query, index, _frames(300.0) + 8, hm.BOUNDARY_TOLERANCE_FRAMES)
    assert at.sum() == query.hashes.size
    assert off.sum() == 0


def test_boundary_finds_the_changepoint():
    """境目はhopの刻みでしか出ない。hashの帰属が入れ替わる点で指紋の分解能まで詰める。"""
    query = _query(8.0, seed=4)
    cut = 5.0
    head = hm._slice_query(query, 0.0, cut)
    tail = hm._slice_query(query, cut, 8.0)
    left = _index([(head, 100.0)], 600.0, noise=3000, seed=11)
    right = _index([(tail, 400.0)], 600.0, noise=3000, seed=12)
    at = hm._boundary(query, {"index": left, "base": 100.0},
                      {"index": right, "base": 400.0}, 3.0, 7.0)
    assert at == pytest.approx(cut, abs=0.15)


def test_boundary_gives_up_when_nothing_distinguishes_the_sides():
    """決められないときにそれらしい値を返してはいけない。粗い位置を残す。"""
    query = _query(8.0, seed=5)
    empty = _index([], 600.0, noise=2000)
    assert hm._boundary(query, {"index": empty, "base": 1.0},
                        {"index": empty, "base": 2.0}, 3.0, 7.0) is None


# ===== 追い込み =====

def test_refine_keeps_the_coarse_base_when_the_correlation_is_low():
    """効かなかった追い込みの位置を黙って採ってはいけない。相関は実測のまま返す。"""
    whole = np.zeros(int(6.0 * afp.SAMPLE_RATE), dtype=np.float32)
    rng = np.random.default_rng(6)
    whole[:] = rng.standard_normal(whole.size).astype(np.float32) * 0.1

    def pcm_at(_rid, _start, length):
        return rng.standard_normal(int(length * afp.SAMPLE_RATE)).astype(np.float32) * 0.1

    base, corr = hm._refine_base(whole, 0.0, 6.0, 500.0, pcm_at)
    assert corr < hm.MIN_CORR
    assert base == 500.0


def test_confidence_needs_all_three():
    assert hm._confidence(hm.MIN_SEGMENT_VOTES, hm.MIN_RATIO, hm.MIN_CORR) == "high"
    assert hm._confidence(hm.MIN_SEGMENT_VOTES - 1, 99.0, 0.99) == "low"
    assert hm._confidence(999, hm.MIN_RATIO - 0.1, 0.99) == "low"
    assert hm._confidence(999, 99.0, hm.MIN_CORR - 0.01) == "low"


# ===== 点 =====

def test_score_puts_every_line_at_the_same_place():
    """線ちょうどは3つとも50。目盛りが違っても「線からの距離」で読めるようにする。"""
    assert hm._score_decade(hm.MIN_SEGMENT_VOTES, hm.MIN_SEGMENT_VOTES) == 50.0
    assert hm._score_decade(hm.MIN_RATIO, hm.MIN_RATIO) == 50.0
    assert hm._score_bounded(hm.MIN_CORR, hm.MIN_CORR, hm.SCORE_CORR_TOP) == 50.0
    assert hm.match_score(hm.MIN_SEGMENT_VOTES, hm.MIN_RATIO, hm.MIN_CORR) == 50


def test_score_takes_the_weakest_of_the_three():
    """**平均しない。** 票と比の高さで相関の低さを覆い隠すと、繋ぎを跨いだgift演出が
    合格点で並ぶ ―― 実測 hl18(票237・比5.6・相関0.24)は平均なら62点だった。"""
    found = hm.score_of(237, 5.64, 0.239)
    assert found["weakest"] == "corr"
    assert found["score"] == min(found["parts"].values())
    assert found["score"] < hm.SCORE_PASS
    # 3つとも余裕で通っているgift演出は高い点になる(実測の当たり)。
    assert hm.match_score(297, 99.0, 0.999) > 95


def test_score_and_confidence_never_disagree():
    """点が線に届くことと ``confidence`` が "high" であることは同じ意味でなければならない。

    別々の式で出すと、境目に居るgift演出だけが「点は50なのに低」という読めない形で並ぶ。
    丸めの向き(切り捨て)がここを守っている。"""
    for votes in (0, 1, 19, 20, 21, 200, 604):
        for ratio in (0.0, 2.99, 3.0, 3.01, 90.0):
            for corr in (-0.7, 0.0, 0.49, 0.5, 0.51, 1.0):
                sure = hm.match_score(votes, ratio, corr) >= hm.SCORE_PASS
                assert sure == (hm._confidence(votes, ratio, corr) == "high"),                     (votes, ratio, corr)


def test_score_never_leaves_the_range():
    for args in ((0, 0.0, -9.0), (10 ** 9, 10 ** 9, 5.0)):
        assert 0 <= hm.match_score(*args) <= 100


# ===== 繋ぎでgift演出を割る =====

def _cand_for(index):
    """``by_id`` に入れる最小の候補。割る段が読むのは ``index`` だけである。"""
    return type("C", (), {"id": 1, "index": index})()


def _run(start: float, end: float, base: float) -> dict:
    return {"state": (1, 0), "start": start, "end": end, "base": base,
            "center_first": start, "center_last": end}


def test_split_at_wall_cuts_where_the_base_jumps():
    """繋ぎと base の不連続が揃った所で割る。**実測 hl18 がこの形**である ――
    10.57秒の1つのgift演出の中に base 2604.884 と 2604.768 の2場面が在り、間に繋ぎが在った。"""
    query = _query(12.0, seed=21)
    cut = 6.0
    head = hm._slice_query(query, 0.0, cut)
    tail = hm._slice_query(query, cut, 12.0)
    index = _index([(head, 100.0), (tail, 400.0)], 900.0, noise=4000, seed=22)
    runs = hm.split_runs_at_walls(query, [_run(0.0, 12.0, 100.0)],
                                  {1: _cand_for(index)}, [(5.5, 6.5)])
    assert len(runs) == 2
    assert runs[0]["end"] == pytest.approx(cut, abs=0.3)
    assert runs[1]["start"] == runs[0]["end"]
    # 割った側は**自分のbase**を持つ。群の代表値へ戻すと、片方が0.1秒ずれた位置で切られる。
    assert runs[0]["base"] == pytest.approx(100.0, abs=0.05)
    assert runs[1]["base"] == pytest.approx(400.0, abs=0.05)


def test_split_at_wall_leaves_one_scene_alone():
    """繋ぎだけでは割らない。**全画面のgift演出は繋ぎと区別が付かない** ―― 実測で
    21.5秒の1場面の中に壁が5つ在り、どれも両側の base が同じだった。"""
    query = _query(12.0, seed=23)
    index = _index([(query, 100.0)], 900.0, noise=4000, seed=24)
    runs = hm.split_runs_at_walls(query, [_run(0.0, 12.0, 100.0)],
                                  {1: _cand_for(index)}, [(5.5, 6.5)])
    assert len(runs) == 1


def test_split_at_wall_ignores_a_wall_at_the_edge():
    """端に寄った壁で割ると、gift演出として成り立たない欠片が出る。"""
    query = _query(12.0, seed=25)
    cut = 0.5
    head = hm._slice_query(query, 0.0, cut)
    tail = hm._slice_query(query, cut, 12.0)
    index = _index([(head, 100.0), (tail, 400.0)], 900.0, noise=4000, seed=26)
    runs = hm.split_runs_at_walls(query, [_run(0.0, 12.0, 400.0)],
                                  {1: _cand_for(index)}, [(0.4, 0.6)])
    assert len(runs) == 1


def test_split_at_wall_leaves_a_hole_alone():
    """どの録画にも当たらなかった区間は割らない。比べる base が無い。"""
    query = _query(12.0, seed=27)
    hole = {"state": None, "start": 0.0, "end": 12.0, "base": None,
            "center_first": 0.0, "center_last": 12.0}
    assert hm.split_runs_at_walls(query, [hole], {}, [(5.5, 6.5)]) == [hole]


# ===== gift =====

def _item(index, media_start, seconds, rid=1154):
    """``_assign_gifts`` が受ける ``prepared`` の1件。"""
    return {"run": {"start": index * seconds, "end": (index + 1) * seconds},
            "cand": _Cand(rid, 601, "R"), "base": media_start - index * seconds,
            "media_start": media_start}


def _gift(event_id, media_time, diamonds, name, nickname="u"):
    return {"id": event_id, "media_time": media_time, "diamonds": diamonds,
            "gift_name": name, "user_nickname": nickname, "gift_id": 1, "gift_image": "",
            "user_unique_id": nickname, "user_id": 1, "identity_key": nickname}


def test_primary_is_the_most_expensive_not_the_nearest():
    """差分が見ているのは画面の広い面積の変化で、それを起こすのは全画面演出を持つ高額gift
    だけである。安価なgiftが直前に挟まっただけで答えが入れ替わってはいけない
    (実測で6000💎が10💎に負けた)。"""
    prepared = [_item(0, 100.0, 10.0)]
    rows = {1154: [_gift(1, 100.0, 6000, "Goal Highlight"), _gift(2, 104.9, 10, "Rose")]}
    hm._assign_gifts(prepared, rows, hm.GIFT_LEAD)
    got = prepared[0]["gifts"]
    assert [g["gift_name"] for g in got] == ["Goal Highlight", "Rose"]
    assert [g["gift_name"] for g in got if g["primary"]] == ["Goal Highlight"]


def test_primary_is_decided_inside_the_segment_only():
    """**範囲内が1件でもあれば、lead窓のgiftは主になれない。**

    実測で踏んだ形である ―― highlight 55.75–59.66秒に映っているのは Spartan Helmet 399💎
    (gift 57.43s / 演出は59.0から)なのに、0.76秒手前の Galaxy 1000💎 が「窓の中で最も高額」
    で勝ち、兜の区間に別人の名前が付いた。出力はgifterごとに1本ずつ作るので、これは
    giftが1件落ちるだけでなく**別人の名前が付く**誤りになる。"""
    prepared = [_item(0, 55.75, 3.91)]
    rows = {1154: [_gift(1, 54.99, 1000, "Galaxy", "セクハラ珍たん"),
                   _gift(2, 57.43, 399, "Spartan Helmet", "🟡むらたろう")]}
    hm._assign_gifts(prepared, rows, hm.GIFT_LEAD)
    got = prepared[0]["gifts"]
    assert [g["inside"] for g in got] == [False, True]
    assert [g["gift_name"] for g in got if g["primary"]] == ["Spartan Helmet"]


def test_primary_falls_back_to_the_lead_window_only_when_nothing_is_inside():
    """演出はgift eventより後に出るので、範囲内が空ならsegmentの手前も見る。"""
    prepared = [_item(0, 100.0, 6.0)]
    rows = {1154: [_gift(1, 96.0, 5000, "Flying Jets")]}
    hm._assign_gifts(prepared, rows, hm.GIFT_LEAD)
    got = prepared[0]["gifts"]
    assert [(g["gift_name"], g["inside"], g["primary"]) for g in got] \
        == [("Flying Jets", False, True)]
    assert got[0]["at"] < prepared[0]["run"]["start"]


def test_assign_gifts_never_hands_the_same_event_to_two_segments():
    """同じ ``event_id`` は必ず1つのsegmentにしか現れない。出力はgifterごとに1本ずつ作るので、
    二度現れると同じgiftで2本出来る。"""
    # 2つ目のsegmentのlead窓(95〜100)は、1つ目のsegmentの範囲(90〜100)を丸ごと含む。
    prepared = [_item(0, 90.0, 10.0), _item(1, 100.0, 10.0)]
    rows = {1154: [_gift(1, 96.0, 1000, "Galaxy")]}
    hm._assign_gifts(prepared, rows, hm.GIFT_LEAD)
    assert [g["event_id"] for g in prepared[0]["gifts"]] == [1]
    assert prepared[1]["gifts"] == []


def test_assign_gifts_gives_a_shared_lead_window_to_the_earlier_segment():
    """lead窓を2つのsegmentが共有したら、**highlightの時間順で手前**のsegmentが取る。
    走査順で帰属が変わらないよう、passBは ``prepared`` の順に固定してある。"""
    prepared = [_item(0, 100.0, 6.0), _item(1, 103.0, 6.0)]
    rows = {1154: [_gift(1, 99.0, 1000, "Galaxy")]}
    hm._assign_gifts(prepared, rows, hm.GIFT_LEAD)
    assert [g["event_id"] for g in prepared[0]["gifts"]] == [1]
    assert prepared[1]["gifts"] == []


def test_gift_view_carries_no_effect_flag():
    """``gifts`` に演出の印は載せない。

    一度 ``has_effect`` を載せたが**外した**。検出器が拾えているのはgift演出の継ぎ目だけで、
    本物の演出(Fireworks 1088💎)と演出が映っていないもの(Galaxy 1000💎)を同じ値で返す ――
    区別できない印を画面に出すと人がそれを信じ始める。信じられない警告が並ぶのは、警告が
    無いことより悪い。演出区間そのものは :attr:`Segment.effect` に**診断用として**残っている。"""
    view = hm._gift_view({"id": 1, "media_time": 10.0, "diamonds": 99}, base=5.0, inside=True)
    assert "has_effect" not in view
    assert view["at"] == pytest.approx(5.0) and view["event_id"] == 1


def test_gifts_of_uses_the_recording_window_not_the_session(monkeypatch, tmp_db, db_read):
    """1つのsessionは録画を複数本束ねる。session全体からgiftを採ると別の録画のgiftが
    混ざり、時刻mapperが録画の終端へ丸めた位置に並ぶ。"""
    session_id = tmp_db.create_session("tester", 60)
    base = 1_700_000_000.0
    for at, diamonds, name in ((10.0, 100, "in"), (2000.0, 200, "another recording")):
        tmp_db.add_event(session_id, {"kind": "gift", "time": base + at, "gift_name": name,
                                      "diamonds": diamonds, "user_unique_id": "u",
                                      "user_nickname": "u", "gift_id": 1, "gift_count": 1})
    tmp_db.flush()
    monkeypatch.setattr(hm, "time_mapper", lambda src, rec: (lambda t: t - rec["started_at"]))
    recording = {"id": 1, "session_id": session_id, "started_at": base,
                 "ended_at": base + 100.0, "duration_seconds": 100.0}
    found = hm.gifts_of(db_read, recording, None)
    assert [g["gift_name"] for g in found] == ["in"]
    assert found[0]["media_time"] == pytest.approx(10.0)


def test_gifts_of_honours_min_diamonds(monkeypatch, tmp_db, db_read):
    session_id = tmp_db.create_session("tester", 60)
    base = 1_700_000_000.0
    for at, diamonds, name in ((10.0, 10, "cheap"), (20.0, 6000, "rich")):
        tmp_db.add_event(session_id, {"kind": "gift", "time": base + at, "gift_name": name,
                                      "diamonds": diamonds, "user_unique_id": "u",
                                      "user_nickname": "u", "gift_id": 1, "gift_count": 1})
    tmp_db.flush()
    monkeypatch.setattr(hm, "time_mapper", lambda src, rec: (lambda t: t - rec["started_at"]))
    recording = {"id": 1, "session_id": session_id, "started_at": base,
                 "ended_at": base + 100.0, "duration_seconds": 100.0}
    assert [g["gift_name"] for g in hm.gifts_of(db_read, recording, None, 1000)] == ["rich"]


# ===== 演出区間 =====

def test_spans_merges_short_gaps_and_drops_short_runs():
    hot = np.zeros(60, dtype=bool)
    hot[10:15] = True           # 1.0秒
    hot[17:22] = True           # 0.4秒あけて 1.0秒 -> 繋がる
    hot[40:41] = True           # 0.2秒 -> 落ちる
    spans = hm._spans(hot, offset=5.0)
    assert spans == [(5.0 + 10 / hm.DIFF_FPS, 5.0 + 22 / hm.DIFF_FPS)]


def test_effects_puts_the_threshold_between_the_two_levels():
    """閾値は2つの山の間に置く。底は下位5%で名乗り、分離度が値で出る。"""
    quiet = np.full(60, 0.05) + np.linspace(-0.02, 0.02, 60)
    loud = np.full(40, 0.85)
    found = hm._effects({0: (np.concatenate([quiet, loud]), 0)})
    assert 0.07 < found[0]["level"] < 0.85
    assert found[0]["floor"] < 0.05
    assert found[0]["eta"] > 0.9


def test_effects_survives_material_that_is_mostly_effect():
    """**演出が素材の半分を超えても閾値は演出の台地より下に来る。**

    highlightはgift地点だけを繋いだmontageなので、これが普通の形である。中央値で底を
    推定していた頃はここで閾値が台地より高くなり、演出区間が1つも出なかった。"""
    quiet = np.full(20, 0.03)
    loud = np.full(80, 0.80)
    found = hm._effects({0: (np.concatenate([quiet, loud]), 0)})
    assert found[0]["level"] < 0.80
    assert (np.concatenate([quiet, loud]) > found[0]["level"]).sum() == 80


def test_shows_are_split_only_when_the_counts_agree():
    """見せ場へ割ってよいのは、演出の数と載ったgiftの数が一致したときだけである。

    一致しないときに前から詰めると、演出の途中の落ち込みで2つに割れた1つの演出を
    2人へ分ける(実測: Flying Jets 5000💎 の1つの演出が2区間に割れていた)。"""
    run = {"start": 14.74, "end": 35.69}
    spans = [(14.94, 20.54), (21.54, 25.54), (26.54, 30.14), (31.54, 32.14)]
    assert hm._show_splits(spans, run, 4) == [21.34, 26.34, 31.34]
    assert hm._show_splits(spans, run, 3) == []
    assert hm._show_splits(spans, run, 5) == []
    assert hm._show_splits(spans[:1], run, 1) == []


def test_shows_are_not_split_into_slivers():
    """切って残らない欠片は作らない。窓としても代表frameとしても意味を持たない。"""
    run = {"start": 0.0, "end": 6.0}
    assert hm._show_splits([(0.0, 1.0), (1.2, 2.0)], run, 2) == []


def test_shows_go_to_the_gifts_in_value_order():
    """見せ場は高額な順に渡す。実測(hl12)で画面の並びは 6599→2000→1200→399 だった。

    **届いた順ではない。** 1200💎 は 2000💎 より2.5ミリ秒早く届いていながら、画面には
    後から出た。"""
    bursts = [[{"diamonds": 1200, "media_time": 1346.3424}],
              [{"diamonds": 2000, "media_time": 1346.3450}],
              [{"diamonds": 6599, "media_time": 1343.8265}]]
    assert [b[0]["diamonds"] for b in hm._show_order(bursts)] == [6599, 2000, 1200]


def test_shows_count_bursts_not_gift_rows():
    """連投は1つの見せ場として数える。実測(hl18)の Ramune 200💎 ×4 は0.92秒の間に届いた
    1回の combo burst で、画面に出る演出は1つだった。件数で数えると、演出の途中の落ち込みで
    4区間に割れたcurveと「4件」が一致し、1つの演出を4つへ割ってしまう。"""
    combo = [{"identity_key": "a", "gift_id": "9001", "diamonds": 200, "media_time": t}
             for t in (10.0, 10.3, 10.6, 10.9)]
    assert len(hm._show_bursts(combo)) == 1
    mixed = combo + [{"identity_key": "b", "gift_id": "8002", "diamonds": 999,
                      "media_time": 12.0}]
    assert [len(b) for b in hm._show_bursts(mixed)] == [4, 1]
    # 間に別の人が挟まれば、そこで演出が切り替わっている。
    split = [combo[0], mixed[-1], combo[1]]
    assert [len(b) for b in hm._show_bursts(split)] == [1, 1, 1]


def test_shows_go_to_the_bursts_by_the_dearest_one():
    """塊の値は中で最も高額な1件。合計で採ると、安いgiftの連投が1発の高額giftを追い越す。"""
    cheap = [{"diamonds": 200, "media_time": 1.0}, {"diamonds": 200, "media_time": 1.2},
             {"diamonds": 200, "media_time": 1.4}]
    rich = [{"diamonds": 500, "media_time": 2.0}]
    assert hm._show_order([cheap, rich]) == [rich, cheap]


def test_a_segment_with_one_gifter_is_never_split():
    """割る目的は別人の見せ場が続くのを止めることなので、1人しか居なければ止める物が無い。"""
    one = {"cand": object(), "gifts": [{"identity_key": "a"}, {"identity_key": "a"}]}
    two = {"cand": object(), "gifts": [{"identity_key": "a"}, {"identity_key": "b"}]}
    assert hm._worth_splitting(one) is False
    assert hm._worth_splitting(two) is True
    assert hm._worth_splitting({"cand": None, "gifts": []}) is False


def test_shows_are_not_split_when_the_floor_stays_high():
    """素の画面が素に見えていない素材では割らない(位置合わせの失敗を測っている)。"""
    assert hm._split_allowed({0: {"floor": 0.02, "level": 0.43}}) is True
    assert hm._split_allowed({0: {"floor": 0.28, "level": 0.57}}) is False
    assert hm._split_allowed({}) is False


# ===== 入口 =====

def test_match_highlight_rejects_an_unknown_scope(tmp_path):
    with pytest.raises(ValueError):
        hm.match_highlight(None, tmp_path / "x.mp4", "tester", scope="everything")


def test_match_highlight_reports_a_missing_file(tmp_path):
    with pytest.raises(hm.HighlightMatchError):
        hm.match_highlight(None, tmp_path / "missing.mp4", "tester", scope="all")


# ===== 候補の窓を段で広げる =====
#
# ``match_highlight`` は段を回すだけの薄いwrapperで、1回ぶんの照合は ``_match_once`` にある。
# ここのtestは**段の回り方だけ**を見る ―― ``_match_once`` は実素材とffmpegが要るので、
# monkeypatchで差し替えるか(段の順序を見る側)、ffmpegと素材だけを外して本体を走らせる
# (窓の実時刻と進捗の名乗りを見る側)。
#
# 段にしてよい理由は実測にある(2026-09-02 / pomiiiip)。候補を14本→33本にしても通しは
# 18.0秒→19.9秒で、通しの8〜9割は候補の量と無関係な「gift演出の詰め」(ffmpegでframeを出す段)
# である。候補に比例するのは読み込みと粗い走査だけ(録画1本あたり0.094秒)で、**外れた段は
# 1.0秒で終わる**(当たりが無ければ詰めるgift演出が無い)。よって「狭い窓で試して、1本も
# 当たらなければ広げてもう一度」はほぼ ただである。


def _segment(recording_id, index=0):
    return hm.Segment(index=index, start=float(index), end=float(index) + 1.0,
                      recording_id=recording_id, media_start=None if recording_id is None
                      else 100.0, votes=300, ratio=9.0, corr=0.9,
                      confidence="none" if recording_id is None else "high")


def _stage_result(days, recording_ids) -> dict:
    """``_match_once`` 1回ぶんの戻り値のうち、段の判断が読む部分だけを持つ形。"""
    now = 1_700_000_000.0
    return {"seconds": 60.0,
            "segments": [_segment(rid, i) for i, rid in enumerate(recording_ids)],
            "pool": 7, "pool_hours": 12.5, "elapsed": 1.0,
            "scope": {"days": days, "pool": 7,
                      "window_start": now - float(days) * 86400.0, "window_end": now},
            "room": {}, "skipped": [], "timings": {}}


def _stub_stages(monkeypatch, hits: dict) -> list:
    """``_match_once`` を差し替え、``hits`` に載っている段だけ当たりを返す。

    返り値は呼び出しの記録。段を1つ試すたびに1件増える。"""
    calls: list = []

    def fake(conn, highlight, streamer, *, days, stage_label="", **kwargs):
        calls.append({"days": days, "stage_label": stage_label})
        return _stage_result(days, hits.get(days, ()))

    monkeypatch.setattr(hm, "_match_once", fake)
    return calls


def _stub_material(monkeypatch, tmp_path, seconds: float = 10.0):
    """``_match_once`` から**ffmpegと素材だけ**を外す。段の名乗りと窓の実時刻は本物が作る。

    差し替えるのは復号と指紋(実素材が要る部分)で、残すのは候補の窓の計算・進捗の文言・
    戻り値の ``scope`` である。走査が空を返すので、結果は「候補は在ったが1本も当たらな
    かった」= 段を広げる合図そのものになる。"""
    highlight = tmp_path / "hl.mp4"
    highlight.write_bytes(b"\x00")
    empty = afp.Fingerprint(np.zeros(0, np.uint32), np.zeros(0, np.int32), 0, 0)
    monkeypatch.setattr(hm, "_probe_duration", lambda path: seconds)
    monkeypatch.setattr(hm, "candidates", lambda conn, streamer, days: [
        {"id": 1154, "session_id": 601, "room_id": "R1", "duration_seconds": 3600.0,
         "path": str(tmp_path / "rec.ts")}])
    monkeypatch.setattr(hm, "_source_path", lambda row: pathlib.Path(row["path"]))
    monkeypatch.setattr(hm, "fingerprint_of", lambda src, refresh=False: empty)
    monkeypatch.setattr(hm, "gifts_of", lambda conn, row, src, min_diamonds=0: [])
    monkeypatch.setattr(hm, "_scan", lambda *args, **kwargs: [])
    monkeypatch.setattr(afp, "fingerprint_stream", lambda *args, **kwargs: empty)
    monkeypatch.setattr(afp, "decode_pcm", lambda *args, **kwargs: np.zeros(0, np.float32))
    return highlight


def test_matched_recordings_are_unique_and_sorted():
    """「空振りしたか」の判定はここ1つ。段を広げるかどうかも、画面が「この窓では当たりま
    せんでした」と名乗るかどうかも同じ問いで、2箇所で数えると必ず片方だけ条件が変わる。"""
    result = {"segments": [_segment(1154), _segment(None, 1), _segment(1153, 2),
                           _segment(1154, 3)]}
    assert hm.matched_recordings(result) == [1153, 1154]
    assert hm.matched_recordings({"segments": [_segment(None)]}) == []
    assert hm.matched_recordings({"segments": []}) == []
    assert hm.matched_recordings({}) == []


def test_match_highlight_stops_at_the_first_stage_that_hits(monkeypatch):
    """1段目で当たったら2段目は走らせない。走らせると、狭い段で決まった答えを広い窓の
    候補で上書きし得るうえ、掛けた時間もそのぶん無駄になる。"""
    monkeypatch.setattr(hm.config, "get_highlight_match_day_stages", lambda: (14.0, 30.0))
    calls = _stub_stages(monkeypatch, {14.0: [1154, 1153]})
    result = hm.match_highlight(None, pathlib.Path("hl.mp4"), "tester")
    assert [c["days"] for c in calls] == [14.0]
    assert result["scope"]["days_tried"] == [14.0]
    assert result["scope"]["day_stages"] == [14.0, 30.0]
    assert result["scope"]["days"] == 14.0
    assert result["matched_recordings"] == [1153, 1154]


def test_match_highlight_widens_until_a_stage_hits(monkeypatch):
    """1段目で1本も当たらなければ広げ、**当たった段の結果**を返す。"""
    monkeypatch.setattr(hm.config, "get_highlight_match_day_stages",
                        lambda: (7.0, 14.0, 30.0))
    calls = _stub_stages(monkeypatch, {30.0: [1084]})
    result = hm.match_highlight(None, pathlib.Path("hl.mp4"), "tester")
    assert [c["days"] for c in calls] == [7.0, 14.0, 30.0]
    assert result["scope"]["days_tried"] == [7.0, 14.0, 30.0]
    assert result["scope"]["days"] == 30.0
    assert result["matched_recordings"] == [1084]
    # 段の名乗りに括弧を入れてはいけない(下の畳み込みのtestを参照)。
    assert all("（" not in c["stage_label"] and "）" not in c["stage_label"] for c in calls)


def test_match_highlight_returns_the_last_stage_when_no_stage_hits(monkeypatch, tmp_path):
    """全部の段で外れても例外にしない。**最後の段の結果**を返し、窓の実際の範囲と試した段を
    名乗る。

    「TikTokが選ばなかった」と「候補の窓の外だった」は別のことで、人がその2つを切り分け
    られる材料はこれだけである(窓は「今」から遡って張られるので、段の一番外より古い配信の
    ハイライトは原理的に当たらない)。"""
    highlight = _stub_material(monkeypatch, tmp_path)
    monkeypatch.setattr(hm.config, "get_highlight_match_day_stages",
                        lambda: (7.0, 14.0, 30.0))
    result = hm.match_highlight(None, highlight, "tester")
    assert result["segments"] == []
    assert result["matched_recordings"] == []
    scope = result["scope"]
    assert scope["day_stages"] == [7.0, 14.0, 30.0]
    assert scope["days_tried"] == [7.0, 14.0, 30.0]
    assert scope["days"] == 30.0
    # 窓は最後に走った段のもの。日数だけでは「いつからいつまでを見たのか」が判らない。
    assert scope["window_end"] - scope["window_start"] == pytest.approx(30.0 * 86400.0)
    assert scope["window_start"] < scope["window_end"]


def test_match_highlight_uses_only_the_days_it_was_given(monkeypatch, tmp_path):
    """日数を明示したら段は使わない ―― 設定も引かない。画面から日数を指定する道である。"""
    highlight = _stub_material(monkeypatch, tmp_path)
    monkeypatch.setattr(hm.config, "get_highlight_match_day_stages",
                        lambda: pytest.fail("days を明示したら段の設定は引かない"))
    messages: list = []
    result = hm.match_highlight(None, highlight, "tester", days=90.0,
                                progress=lambda done, total, msg: messages.append(msg))
    assert result["scope"]["days"] == 90.0
    assert result["scope"]["day_stages"] == [90.0]
    assert result["scope"]["days_tried"] == [90.0]
    assert result["scope"]["window_end"] - result["scope"]["window_start"] \
        == pytest.approx(90.0 * 86400.0)
    # 段が1つなら名乗りは付かない。付けると、日数を指定しただけの照合が「1/1段目」を名乗る。
    assert messages and all("（" not in msg for msg in messages)


@pytest.mark.parametrize("days", [0, -1.0, float("nan")])
def test_match_highlight_rejects_a_non_positive_days(monkeypatch, tmp_path, days):
    """0や負の日数は窓にならない。黙って段へ落とすと、指定したつもりの窓と走る窓が食い違う。"""
    highlight = _stub_material(monkeypatch, tmp_path)
    monkeypatch.setattr(hm.config, "get_highlight_match_day_stages",
                        lambda: pytest.fail("不正な days で段へ落ちてはいけない"))
    with pytest.raises(ValueError):
        hm.match_highlight(None, highlight, "tester", days=days)


def test_match_highlight_refuses_to_run_with_no_stage_at_all(monkeypatch, tmp_path):
    """段が空なら1回も走らない。既定へ落として取り繕うと、設定を直したつもりの人が
    「効いていない」ことに気付けない。"""
    highlight = _stub_material(monkeypatch, tmp_path)
    monkeypatch.setattr(hm.config, "get_highlight_match_day_stages", lambda: ())
    with pytest.raises(hm.HighlightMatchError):
        hm.match_highlight(None, highlight, "tester")



def test_missing_material_does_not_widen_the_window(monkeypatch, tmp_path):
    """**素材そのものが無いのは、窓を広げれば消える失敗ではない。**

    段を広げる条件は ``NoCandidates`` だけにしてある。``HighlightMatchError`` をまとめて
    捕まえていた頃は、highlightのmp4が無いだけでも段の数だけ再試行され、そのたびに
    「候補なし」というlogが出ていた —— 素材が無いのだから、logの理由が事実と食い違う。
    """
    # 本物の ``_match_once`` を通す。素材の実在を見ているのはあちらなので、差し替えると
    # この性質そのものが消える。呼ばれた回数だけを覗く。
    real = hm._match_once
    calls: list = []

    def spy(*args, **kwargs):
        calls.append(kwargs.get("days"))
        return real(*args, **kwargs)

    monkeypatch.setattr(hm, "_match_once", spy)
    monkeypatch.setattr(hm.config, "get_highlight_match_day_stages", lambda: (14.0, 30.0))
    with pytest.raises(hm.HighlightMatchError) as caught:
        hm.match_highlight(None, tmp_path / "居ない.mp4", "tester")
    # **1段目で落ちる。** 段の数だけ再試行してはいけない。
    assert calls == [14.0]
    assert not isinstance(caught.value, hm.NoCandidates)


def test_no_candidates_widens_and_names_the_window(monkeypatch, tmp_path):
    """候補が1本も無い段は広げる。**最後の段まで来て初めて投げる。**

    しばらく配信していない配信者のハイライトを入れたときに、広い段を持っているのに
    1段目で落ちてはいけない。上がる例外の文言は配信者と日数を名乗る —— 「候補がありません」
    だけでは、どの窓を見て言っているのかが読めない。"""
    seen: list = []

    def fake(conn, highlight, streamer, *, days, stage_label="", **kwargs):
        seen.append(days)
        raise hm.NoCandidates(f"候補の録画がありません（{streamer} / 直近{days:g}日）。")

    monkeypatch.setattr(hm, "_match_once", fake)
    monkeypatch.setattr(hm.config, "get_highlight_match_day_stages", lambda: (14.0, 30.0))
    with pytest.raises(hm.NoCandidates) as caught:
        hm.match_highlight(None, tmp_path / "hl.mp4", "居ない配信者")
    assert seen == [14.0, 30.0]
    assert "居ない配信者" in str(caught.value) and "30日" in str(caught.value)


def test_day_stage_options_are_all_readable_by_config():
    """設定画面の選択肢は**実際に効く値**でなければならない。

    この設定はDB > 環境変数 > 既定の順で解決されるが、``SETTING_DEFS`` に無い間はDBの枝が
    画面から到達できず、docstringの「DB設定」が嘘になっていた。項目を足した以上、そこから
    選べる値が全部 :func:`config._parse_day_stages` を通ることを確かめる —— 通らない値を
    選択肢に置くと、保存した瞬間に照合が ConfigError で落ちる。"""
    from tictok.core import config, settings

    definition = settings.SETTING_DEFS["highlight_match_day_stages"]
    assert definition["type"] is str and definition["options"]
    # 既定の文字列は config の既定そのものから組む(数字を2箇所に書かない)。
    assert definition["default"] == ",".join(
        f"{value:g}" for value in config.HIGHLIGHT_MATCH_DAY_STAGES_DEFAULT)
    for option in definition["options"]:
        stages = config._parse_day_stages(option["value"], "settings")
        assert stages and list(stages) == sorted(stages), option["value"]
    # 既定の選択肢が実際の既定と同じ段であること。
    assert config._parse_day_stages(definition["default"], "settings") == \
        config.HIGHLIGHT_MATCH_DAY_STAGES_DEFAULT

def test_stage_labels_fold_into_the_same_phase_whatever_the_stage(monkeypatch, tmp_path):
    """段の名乗りは ``media_queue.stage_phase`` を通すと**段の数によらず同じ段階名**になる。

    jobの段階履歴は全角括弧の中を落として段階名を作るが、その正規表現は入れ子を見ない。
    ``stage_label`` の中に括弧を入れると畳み切れず、段の数だけ別々の段階が履歴へ並ぶ ――
    「どの段階に何秒かけたか」が読めなくなるので、これは退行testである。"""
    from tictok.record import media_queue

    highlight = _stub_material(monkeypatch, tmp_path)
    monkeypatch.setattr(hm.config, "get_highlight_match_day_stages",
                        lambda: (7.0, 14.0, 30.0))
    messages: list = []
    hm.match_highlight(None, highlight, "tester",
                       progress=lambda done, total, msg: messages.append(msg))
    # 名乗りそのものは段ごとに違う(人が見るのはこちら)。
    assert len(set(messages)) > 3
    assert any("1/3段目" in msg for msg in messages)
    # 履歴へ畳むと段階の名前だけが残る。段が3つでも段階は増えない。
    phases = {media_queue.stage_phase(msg) for msg in messages}
    assert phases == {"指紋を読み込みます", "粗い走査", "細かい走査", "segmentを詰めます"}
    assert all("（" not in phase and "）" not in phase for phase in phases)


def test_match_highlight_names_the_streamer_and_the_days_when_nothing_is_a_candidate(
        monkeypatch, tmp_path):
    """候補が0本のときの文言に配信者と日数が入る。**この2つが無いと直しようがない** ――
    「配信者の綴りが違う」のか「その窓に録画が無い」のかが読めない。"""
    highlight = _stub_material(monkeypatch, tmp_path)
    monkeypatch.setattr(hm, "candidates", lambda conn, streamer, days: [])
    monkeypatch.setattr(hm.config, "get_highlight_match_day_stages", lambda: (30.0,))
    with pytest.raises(hm.HighlightMatchError) as err:
        hm.match_highlight(None, highlight, "pomiiiip")
    assert "pomiiiip" in str(err.value) and "30" in str(err.value)

    with pytest.raises(hm.HighlightMatchError) as err:
        hm.match_highlight(None, highlight, "", days=14.0)
    assert "すべての配信者" in str(err.value) and "14" in str(err.value)


# ===== 実物の真値（回帰） =====
#
# 実物のhighlight 1本の真値は tests/data/highlight_truth_pomiiiip.json にある。目視(演出の
# frame)とDBのgift eventで確定したもので、合否は**giftの名前・gifter・gift演出の並び順**で採る
# (gift演出の秒とbaseは3秒hopの粗い推定なので参考値)。
#
# 突き合わせ本体を走らせるには53.9時間ぶんの録画と本番DBが要るので、ここでは2段に分ける。
#
#   1. 照合の判定そのもの(:func:`_compare`)にはtestを張る。真値と食い違う出力を通さない
#      ことを、gifterの取り違え・gift演出の欠落・並びの入れ替えで確かめる。
#   2. 実素材での実行は ``TICTOK_HIGHLIGHT_TRUTH=1`` を立てたときだけ走る。素材が在る機械
#      でのみ意味があり、conftestのsandboxを壊さないよう本番DBは読み取り専用で明示的に開く。
#
# 実素材で走らせる:
#   TICTOK_HIGHLIGHT_TRUTH=1 venv/Scripts/python.exe -m pytest tests/test_highlight_match.py -k truth

import json
import os
import sqlite3

TRUTH_PATH = pathlib.Path(__file__).resolve().parent / "data" / "highlight_truth_pomiiiip.json"


def _truth() -> dict:
    return json.loads(TRUTH_PATH.read_text(encoding="utf-8"))


def _key(fragment: dict) -> tuple:
    """真値のgift演出から、突き合わせに使う項目だけを抜く。

    秒とbaseは見ない ―― 真値の側が3秒hopの粗い推定である。"""
    return (fragment["recording_id"], fragment["gift_name"], fragment["user_nickname"])


def _wanted(truth: dict) -> list:
    """真値のgiftを、highlightの時間順に並べる。

    gift演出の主(``fragments`` の本体)と、同じgift演出に入る他のgift(``also_present``)を1つの列に
    する。**1つのgift演出=1giftではない**ので、主だけを並べると Galaxy 1000💎 のように「画面には
    映っているが主ではない」giftが検証から漏れる。gift演出の中の順は ``at`` で決める。"""
    out = []
    for fragment in truth["fragments"]:
        rows = [fragment] + list(fragment.get("also_present") or [])
        for row in sorted(rows, key=lambda r: r["at"]):
            out.append((fragment["recording_id"], row["gift_name"], row["user_nickname"]))
    return out


def _found(segments) -> list:
    """出力のgiftを時刻順に並べる。連続する同じ ``(録画, gift, gifter)`` は1つに畳む。

    **segment単位ではなくgift単位で並べる。** 1つのsegmentに複数のgiftが入るので
    (実測の最後のgift演出に Galaxy 1000💎 と Spartan Helmet 399💎)、segmentごとに1件だけ採ると
    真値の側のgift演出と噛み合わない。

    畳むのは、同じgiftを続けて投げるとeventがその回数だけ立つためである(実測: Hearts 199💎 が
    2msずつ離れた6件、Galaxy 1000💎 が2件。``message_id`` は別で ``fan_ticket_count`` は
    件数ぶんの合計なので、**重複ではなく本当に複数回投げている**)。真値は画面に見えた演出の
    単位で数えてあるので、投げた回数と数え合わせても意味がない。"""
    out: list = []
    for s in segments:
        for g in s.gifts:
            key = (s.recording_id, g["gift_name"], g["user_nickname"])
            if not out or out[-1] != key:
                out.append(key)
    return out


def _compare(segments, truth: dict) -> list:
    """真値のgift演出が、出力に**この順で**現れることを確かめる。食い違いを並べ、空なら合格。

    出力にはこれ以外のgiftも載る ―― 1つのsegmentに複数のgiftが入るようにしたのが今回の
    変更で、``gift_lead`` で手前へ伸ばした窓のgiftもそこに並ぶ。**多いことは欠落ではない**
    ので失格にしない。落ちること・入れ替わることだけを見る。"""
    got = _found(segments)
    want = _wanted(truth)
    failed, at = [], 0
    for i, key in enumerate(want):
        try:
            at = got.index(key, at) + 1
        except ValueError:
            failed.append(f"真値 #{i} {key} が出力に（この順では）ありません。出力={got}")
    return failed


class _Seg:
    """`_compare` へ渡すだけの最小のsegment。"""

    def __init__(self, recording_id, gifts):
        self.recording_id = recording_id
        self.gifts = [{"gift_name": name, "user_nickname": nick} for name, nick in gifts]


def _observed(truth: dict) -> list:
    """真値をそのまま「正しい出力」に見立てたsegmentの列。"""
    out = []
    for fragment in truth["fragments"]:
        rows = sorted([fragment] + list(fragment.get("also_present") or []),
                      key=lambda r: r["at"])
        out.append(_Seg(fragment["recording_id"],
                        [(r["gift_name"], r["user_nickname"]) for r in rows]))
    return out


def test_truth_fixture_has_the_ten_fragments():
    truth = _truth()
    assert len(truth["fragments"]) == 10
    assert {f["recording_id"] for f in truth["fragments"]} == {1153, 1154}
    # 99💎階層が入っていること。ここが落ちるなら下限98の根拠が消えている。
    assert min(f["diamonds"] for f in truth["fragments"]) == 99
    # 最後のgift演出の主は Spartan Helmet 399💎。**Galaxy 1000💎 ではない** ―― 画面に映って
    # いるのは兜(t≈59-60)で、Galaxy はgift演出の0.76秒手前のgiftである。旧規則はここで
    # 別人の名前を付けていた。
    last = truth["fragments"][-1]
    assert (last["gift_name"], last["diamonds"]) == ("Spartan Helmet", 399)
    assert [g["gift_name"] for g in last["also_present"]] == ["Galaxy"]
    assert all(not g["primary"] for g in last["also_present"])


def test_compare_accepts_the_verified_output():
    truth = _truth()
    assert _compare(_observed(truth), truth) == []


def test_compare_catches_a_wrong_gifter():
    truth = _truth()
    segments = _observed(truth)
    segments[4].gifts[0]["user_nickname"] = "別人"
    assert _compare(segments, truth)


def test_compare_allows_extra_gifts_in_one_segment():
    """1つのsegmentに複数のgiftが載るのが今回の変更なので、多いことを失格にしない。

    実物の最後のgift演出には Galaxy 1000💎 と Spartan Helmet 399💎 の両方が入る。真値の10行が
    この順で並んでいれば合格である。"""
    truth = _truth()
    segments = _observed(truth)
    segments[-1].gifts.append({"gift_name": "Spartan Helmet",
                               "user_nickname": "🟡むらたろう🍑🏌️‍♂️🍔"})
    segments[0].gifts.insert(0, {"gift_name": "口笛はなぜ", "user_nickname": "おニャンコ🐢💤"})
    assert _compare(segments, truth) == []


def test_compare_folds_a_burst_of_the_same_gift():
    """同じgiftを続けて投げるとeventがその回数だけ立つ(実測 Hearts 199💎 が6件)。
    真値は画面に見えた演出の単位なので、投げた回数と数え合わせない。"""
    truth = _truth()
    segments = _observed(truth)
    segments[4].gifts *= 6
    assert _compare(segments, truth) == []


def test_compare_catches_a_missing_fragment():
    truth = _truth()
    segments = _observed(truth)
    del segments[5]
    assert _compare(segments, truth)


def test_compare_catches_a_reordered_fragment():
    truth = _truth()
    segments = _observed(truth)
    segments[7], segments[8] = segments[8], segments[7]
    assert _compare(segments, truth)


@pytest.mark.skipif(not os.environ.get("TICTOK_HIGHLIGHT_TRUTH"),
                    reason="実素材(53.9時間の録画と本番DB)が要る。TICTOK_HIGHLIGHT_TRUTH=1 で走る")
def test_truth_on_the_real_material():
    """実物のhighlight 1本を通しで走らせ、真値と突き合わせる。

    conftestのsandboxは壊さない。envはtmpのままで、本番DBだけ読み取り専用で明示的に開く
    (指紋sidecarは既に在るので書き込みも起きない)。"""
    from tictok.core import config, layout
    from tictok.paths import PROJECT_ROOT

    truth = _truth()
    db = PROJECT_ROOT / "tictok.db"
    highlight = (PROJECT_ROOT / "recordings" / truth["streamer"]
                 / layout.HIGHLIGHT_LEGACY_DIRNAME / truth["highlight"])
    if not db.is_file() or not highlight.is_file():
        pytest.skip(f"素材がありません: {highlight}")
    # 録画の実体を解決するrootを本番へ向ける。conftestがtest後に必ず戻す。
    layout.set_record_roots([config.record_dir_from_db(str(db)),
                             config.final_record_dir_from_db(str(db))])
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        result = hm.match_highlight(conn, highlight, truth["streamer"])
    finally:
        conn.close()
    assert result["scope"]["min_diamonds"] == 98, "設定の演出gift下限が98でない"
    assert _compare(result["segments"], truth) == []
    # 候補はLIVE room単位で絞る。この配信は接続断で割れていないので録画は2本。
    assert result["room"]["narrowed"] and result["room"]["room_id"]
    assert result["room"]["recordings"] == [1153, 1154]
    # 同じ ``event_id`` が2つのsegmentに現れない。出力はgifterごとに1本ずつ作るので、
    # 二度現れると同じgiftで2本出来る。
    ids = [g["event_id"] for s in result["segments"] for g in s.gifts]
    assert len(ids) == len(set(ids))
    # 真値の10行に加えて、最後のgift演出で Galaxy 1000💎 に隠れていた1件が出ること。ここが
    # 出ないなら ``primary`` が範囲内へ閉じていない(範囲外の高額giftが勝っている)。
    names = {(g["gift_name"], g["user_nickname"]) for s in result["segments"] for g in s.gifts}
    assert ("Spartan Helmet", "🟡むらたろう🍑🏌️‍♂️🍔") in names
