"""効果音の置き方。

この機能の事故は「鳴っているが浮いている」形で出る。件数や設定値を見ても検出できず、
成果物を聴くまで気付けない。ここで守るのは、聴かなくても判定できる部分:

  1. 置く時刻を**検出しない**（構造から決まる時刻しか受けない）
  2. 種類を跨いで重なった組は片方を落とす（同一msの2音は1つの濁った塊にしかならない）
  3. 素材は指紋で固定し、違えば代替せずに止める
  4. 素材の外へ置く指定は捨て、**捨てた数を報告する**
"""

import pytest

from tictok.media import sfx


def test_the_joint_and_the_first_telop_do_not_fire_together():
    """シーンの頭は発話の開始へ吸着させるので、継ぎ目の時刻とそのシーン最初のテロップの
    時刻は一致する。実素材で作った作品を測って、計画12箇所のうち2組が同一msに重なって
    いた — 例外ではなく、シーンが増えるだけ必ず起きる。
    """
    plan = sfx.plan_cues(joints=[18.031, 36.088],
                         telops=[0.0, 11.32, 18.031, 36.088, 45.5],
                         duration=54.0)
    at = [c["at"] for c in plan["cues"]]
    assert len(at) == len(set(at)), at
    assert plan["dropped"]["cross"] == 2
    # 残るのは継ぎ目の方。構造の区切りを示す音で、消すと画面の切り替わりに何も鳴らない。
    kinds = {c["at"]: c["slot"] for c in plan["cues"]}
    assert kinds[18.031] == "transition"
    assert kinds[36.088] == "transition"


def test_the_surviving_cue_does_not_depend_on_the_order_they_arrive():
    """時刻順に見て「後から来た方を落とす」形にすると、継ぎ目が先か後かで結果が変わる。"""
    a = sfx.plan_cues(joints=[10.0], telops=[10.05], duration=30.0)
    b = sfx.plan_cues(joints=[10.05], telops=[10.0], duration=30.0)
    assert [c["slot"] for c in a["cues"]] == ["transition"]
    assert [c["slot"] for c in b["cues"]] == ["transition"]


def test_the_same_kind_in_a_burst_is_thinned():
    """入れすぎが品質を落とす主因。ギフトが連続した区間で音が重なって潰れる。"""
    plan = sfx.plan_cues(gifts=[1.0, 1.2, 1.4, 5.0], duration=30.0)
    assert [c["at"] for c in plan["cues"]] == [1.0, 5.0]
    assert plan["dropped"]["gap"] == 2


def test_cues_outside_the_work_are_counted_not_just_dropped():
    """ffmpegは範囲外のadelayを黙って無視する。数えないと「置いたつもりの音が無い」
    理由が誰にも分からなくなる。"""
    plan = sfx.plan_cues(telops=[-1.0, 5.0, 99.0], duration=30.0)
    assert [c["at"] for c in plan["cues"]] == [5.0]
    assert plan["dropped"]["outside"] == 2


def test_the_total_is_capped_and_the_overflow_is_reported():
    plan = sfx.plan_cues(telops=[i * sfx.MIN_GAP_SECONDS for i in range(sfx.MAX_CUES + 5)],
                         duration=10_000.0)
    assert len(plan["cues"]) == sfx.MAX_CUES
    assert plan["dropped"]["overflow"] == 5


def test_a_time_inside_a_removed_silence_has_no_place_to_go():
    """詰めた区間へ落ちた行は写し先が無い。近い所へ寄せると、無音を消した場所で音が鳴る。"""
    keeps = [(0.0, 5.0), (8.0, 12.0)]
    assert sfx.remap_to_output(2.0, keeps) == 2.0
    # 8.0以降は詰めたぶん(3秒)だけ手前へ寄る。
    assert sfx.remap_to_output(9.0, keeps) == 6.0
    # 5.0-8.0は落とした区間。
    assert sfx.remap_to_output(6.5, keeps) is None


def test_without_tightening_the_time_is_unchanged():
    """詰めていない作品で写し替えを掛けると、そこが新しいずれの発生源になる。"""
    assert sfx.remap_to_output(12.34, []) == 12.34


def test_every_asset_declares_a_measured_gain():
    """素材の大きさはばらばらなので、同じvolumeを掛けると鳴る音の大きさが揃わない。"""
    for slot, asset in sfx.MANIFEST.items():
        assert asset.slot == slot
        assert len(asset.sha256) == 64
        # 実測peakからTARGET_PEAK_DBまでの差。0dB(=無補正)は「測っていない」の徴候。
        assert asset.gain_db == round(sfx.TARGET_PEAK_DB - asset.peak_db, 2)
        assert asset.gain_db != 0.0


def test_every_asset_passes_the_acceptance_rules_it_was_chosen_by():
    """manifestの実測値が、宣言した条件を満たしていること。

    条件を緩めて既存の採用を通す変更を、testが黙って許さないようにする。
    """
    for slot, asset in sfx.MANIFEST.items():
        rule = sfx.ACCEPTANCE[slot]
        ms = asset.seconds * 1000
        assert rule["min_ms"] <= ms <= rule["max_ms"], (slot, ms)


def test_a_replaced_upstream_file_stops_the_render(tmp_path, monkeypatch):
    """配布元が同じpathで別の物を配り始めたときに、黙って別の音を焼かない。"""
    monkeypatch.setattr(sfx, "SFX_DIR", tmp_path)
    monkeypatch.setattr(
        sfx.urllib.request, "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(OSError("network is disabled in tests")))
    with pytest.raises(RuntimeError, match="取得できませんでした"):
        sfx.ensure_assets(("transition",))


def test_one_input_per_sound_even_when_it_fires_many_times():
    """cueの数だけ入力を開くと、数十回鳴る作品でffmpegのinput上限とcommand長に近づく。"""
    cues = [{"at": float(i), "slot": "telop"} for i in range(20)]
    cues.append({"at": 30.0, "slot": "transition"})
    graph = sfx.filter_complex(cues, sfx.MANIFEST)
    assert graph.count("asplit") == 2  # 使った種類の数だけ
    assert "[1:a]" in graph and "[2:a]" in graph and "[3:a]" not in graph
    # 本編の音を基準にする。normalize=0でないと、入力が増えるほど本編が小さくなる。
    assert "normalize=0" in graph and "duration=first" in graph
    assert graph.count("adelay=") == len(cues)