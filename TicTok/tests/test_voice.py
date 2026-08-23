# -*- coding: utf-8 -*-
"""声区間(VAD)。

外すと、声の在る所が速く流れる — しかも飛ばしてはいないので、聞き逃した跡が残らない。
「声を狭める側へ倒れない」条件を1つずつ見る。
"""
import numpy as np
import pytest

from tictok.media import voice


def profile(probs, interval=0.1):
    return {"interval_seconds": interval, "duration_seconds": len(probs) * interval,
            "probs": list(probs)}


# sidecarへ実際に入る刻み。0.1秒を頼むと32msのVAD frame 3つ = 0.096秒に吸着する。cacheの
# 試験でここを0.1のまま作ると、_foldが決して書かない値のsidecarを相手にすることになる。
GRID = voice._snap_interval(0.1)[1]


def test_folding_takes_the_max_not_the_mean():
    """畳みは声を広げる側へ倒す。平均だと語頭の1 frameだけが高い所が薄まって消え、
    それは聞き手が戻らないと取り返せない失敗になる。"""
    frames = np.zeros(10, dtype=np.float32)
    frames[3] = 0.9                       # 10 frame中1つだけ声
    folded = voice._fold(frames, 10 * voice.VAD_FRAME_SAMPLES / voice.SAMPLE_RATE)
    assert folded["probs"] == [0.9]


def test_spans_come_from_the_threshold_at_query_time():
    """生確率を保存しているのは、後から閾値を掃引するため。"""
    p = profile([0.0, 0.3, 0.3, 0.0])
    assert voice.speech_spans(p, threshold=0.2, min_silence=0.0, min_speech=0.0) == [
        {"start": 0.1, "end": 0.3}]
    assert voice.speech_spans(p, threshold=0.5, min_silence=0.0, min_speech=0.0) == []


def test_a_short_gap_inside_speech_is_filled_not_split():
    """文中の息継ぎで区切ると、詰めるほどでもない隙間で速度が往復する。"""
    p = profile([0.9, 0.9, 0.0, 0.9, 0.9])
    assert voice.speech_spans(p, threshold=0.2, min_silence=0.3, min_speech=0.0) == [
        {"start": 0.0, "end": 0.5}]


def test_a_long_gap_stays_a_gap():
    p = profile([0.9] + [0.0] * 8 + [0.9])
    spans = voice.speech_spans(p, threshold=0.2, min_silence=0.3, min_speech=0.0)
    assert spans == [{"start": 0.0, "end": 0.1}, {"start": 0.9, "end": 1.0}]


def test_a_single_bin_of_speech_is_kept_by_default():
    """既定の最短は低く取る。0.1秒の1 binは雑音より音節である方が確からしく、残す代償は
    等速の0.1秒だけ。落とす代償は語頭を速く流すことである。"""
    p = profile([0.0, 0.9, 0.0])
    assert voice.speech_spans(p, threshold=0.2) == [{"start": 0.1, "end": 0.2}]


def test_a_single_bin_is_kept_on_the_real_grid_too():
    """実際の刻みは0.096秒(32msのVAD frame 3つ)で、0.1秒ちょうどには乗らない。最短を秒で
    比べると1 binの声が必ず落ちる — 落とさないつもりで置いた下限が、落としたくないものだけを
    落とすことになる。実録画では確率0.25の語がこれで丸ごと飛んでいた。"""
    p = profile([0.0, 0.25, 0.0], interval=0.096)
    assert voice.speech_spans(p, threshold=0.1) == [{"start": 0.096, "end": 0.192}]


def test_min_speech_drops_shorter_runs_when_asked():
    p = profile([0.0, 0.9, 0.0])
    assert voice.speech_spans(p, threshold=0.2, min_speech=0.5) == []


def test_an_empty_profile_yields_no_spans():
    """空を「全編が声」とも「全編が無音」とも読ませない。呼び出し側が計画を出さない。"""
    assert voice.speech_spans({"interval_seconds": 0.1, "probs": []}) == []
    assert voice.speech_spans({}) == []


def test_the_cache_follows_the_material_and_the_grid(tmp_path, monkeypatch):
    """素材が変わった録画に前の答えを当てない。刻みが違うcacheも畳み直さない。"""
    src = tmp_path / "x.mp4"
    src.write_bytes(b"\x00" * 4096)
    monkeypatch.setattr(voice, "_source_key", lambda p: {"size": p.stat().st_size})
    voice._store_cache(src, profile([0.9, 0.0], interval=GRID))

    assert voice._load_cache(src, 0.1)["probs"] == [0.9, 0.0]
    assert voice._load_cache(src, 0.2) == {}
    src.write_bytes(b"\x00" * 8192)
    assert voice._load_cache(src, 0.1) == {}


def test_the_cache_matches_the_grid_it_was_written_on(tmp_path, monkeypatch):
    """書く側だけが刻みを吸着し、照合側が要求値のまま比べていると ``0.096 != 0.1`` が必ず
    成立し、cacheは**1件も当たらない**(実測: 実運用のsidecar 212件中HIT 0件、再生画面を
    開くたびに全編のVADが走り直して1本あたり最大52.9秒)。書く経路(_fold)と読む経路を
    そのまま繋いで見る。"""
    src = tmp_path / "x.mp4"
    src.write_bytes(b"\x00" * 4096)
    monkeypatch.setattr(voice, "_source_key", lambda p: {"size": p.stat().st_size})
    frames = np.array([0.9, 0.1, 0.2, 0.0, 0.0, 0.0], dtype=np.float32)
    built = voice._fold(frames, 0.1)
    voice._store_cache(src, built)

    assert voice._load_cache(src, 0.1) == built


def test_the_threshold_is_not_part_of_the_cache_key(tmp_path, monkeypatch):
    """閾値を変えて解析がやり直しになるなら、生確率を保存している狙いが成立していない。"""
    src = tmp_path / "x.mp4"
    src.write_bytes(b"\x00" * 4096)
    monkeypatch.setattr(voice, "_source_key", lambda p: {"size": p.stat().st_size})
    voice._store_cache(src, profile([0.9, 0.0], interval=GRID))

    monkeypatch.setenv("TICTOK_VOICE_THRESHOLD", "0.9")
    assert voice._load_cache(src, 0.1)["probs"] == [0.9, 0.0]


def test_the_model_failing_is_an_error_not_silence(monkeypatch):
    """黙って「声が無かった」を返すと、その録画は全編が速く流れる。"""
    monkeypatch.setattr(voice, "_model", None)
    monkeypatch.setitem(__import__("sys").modules, "faster_whisper.vad", None)
    with pytest.raises(voice.VoiceError):
        voice._get_model()
