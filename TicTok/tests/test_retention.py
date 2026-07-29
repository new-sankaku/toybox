"""保持policyの資産序列。素材(.ts)が残る録画ではmp4は派生物、素材が原本になる。

ここでの関心は「何が原本か」の判定だけなので、DBもserverも通さず retention module へ
直接dictを渡す。実際の削除(素材dirのrmtree・mp4のunlink)はserver側のtestで見る。
"""
import os
from pathlib import Path

import pytest

from tictok.record import retention
from tictok.record.upscale import upscale_artifact_paths
from tictok.record.video_overlay import overlay_artifact_paths

DAY = 86400.0
NOW = 100 * DAY


def _resolve(recording):
    path = recording.get("path")
    return Path(path) if path else None


def _touch(path: Path, mtime: float, size: int = 8) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def make_rec(tmp_path):
    """録画1本ぶんのdictと実mp4。DBは通さない(retentionはdictのkeyしか見ない)。"""
    counter = {"n": 0}

    def _make(*, mp4_size=100, mp4_mtime=NOW - 30 * DAY, ended_at=DAY, **extra):
        counter["n"] += 1
        stem = f"{counter['n']:05d}_tester_20260101_120000"
        mp4 = tmp_path / "tester" / "mp4" / f"{stem}.mp4"
        if mp4_size:
            _touch(mp4, mp4_mtime, mp4_size)
        recording = {
            "id": counter["n"],
            "path": str(mp4),
            "filename": mp4.name,
            "unique_id": "tester",
            "status": "completed",
            "ended_at": ended_at,
            "protected": 0,
        }
        recording.update(extra)
        return recording

    return _make


def _has(*recordings):
    """素材が残っている録画のidを名指しするhas_media。"""
    ids = {rec["id"] for rec in recordings}
    return lambda rec: rec["id"] in ids


def _usage(**by_id):
    """recording_id -> (bytes, files, mtime) を返すmedia_usage。"""
    table = {int(key.lstrip("r")): value for key, value in by_id.items()}

    def _lookup(recording):
        size, files, mtime = table.get(recording["id"], (0, 0, 0.0))
        return {"bytes": size, "files": files, "mtime": mtime}

    return _lookup


# ---- ② 派生物: 素材が残る録画のmp4はここへ落ちる --------------------------------------


def test_the_mp4_becomes_a_derived_file_when_the_material_remains(make_rec):
    recording = make_rec(mp4_size=100)
    items = retention.derived_candidates([recording], _resolve, DAY, NOW,
                                         has_media=_has(recording))
    assert [i["recording_id"] for i in items] == [recording["id"]]
    assert items[0]["bytes"] == 100
    assert items[0]["includes_source"] is True
    assert items[0]["source_bytes"] == 100


def test_the_mp4_stays_out_of_the_derived_phase_without_material(make_rec):
    """素材の無い録画のmp4は唯一の再取得不能資産。派生物として消してはならない。"""
    recording = make_rec(mp4_size=100)
    _touch(overlay_artifact_paths(Path(recording["path"]))[0], NOW - 30 * DAY, size=7)
    items = retention.derived_candidates([recording], _resolve, DAY, NOW,
                                         has_media=_has())
    assert [i["recording_id"] for i in items] == [recording["id"]]
    # 焼き込みだけが対象。mp4のbytesは含まない。
    assert items[0]["bytes"] == 7
    assert items[0]["includes_source"] is False
    assert items[0]["source_bytes"] == 0


def test_the_mp4_is_protected_when_no_material_check_is_supplied(make_rec):
    """判定手段を渡されないときは素材が無い側に倒す(分からないまま原本を派生物にしない)。"""
    recording = make_rec(mp4_size=100)
    assert retention.derived_candidates([recording], _resolve, DAY, NOW) == []


def test_the_derived_phase_still_ages_on_the_newest_file(make_rec):
    recording = make_rec(mp4_size=100, mp4_mtime=NOW - 60.0)
    has_media = _has(recording)
    assert retention.derived_candidates([recording], _resolve, DAY, NOW,
                                        has_media=has_media) == []
    os.utime(recording["path"], (NOW - 30 * DAY, NOW - 30 * DAY))
    items = retention.derived_candidates([recording], _resolve, DAY, NOW, has_media=has_media)
    assert [i["recording_id"] for i in items] == [recording["id"]]


def test_a_protected_recording_keeps_its_mp4_even_with_material(make_rec):
    recording = make_rec(mp4_size=100, protected=1)
    assert retention.derived_candidates([recording], _resolve, DAY, NOW,
                                        has_media=_has(recording)) == []


def test_a_recording_still_being_written_is_never_a_derived_candidate(make_rec):
    recording = make_rec(mp4_size=100, status="recording")
    assert retention.derived_candidates([recording], _resolve, DAY, NOW,
                                        has_media=_has(recording)) == []


def test_a_missing_mp4_with_material_offers_only_the_real_artifacts(make_rec):
    """②でmp4を消した後の状態。無いfileを「消せる」と数えない。"""
    recording = make_rec(mp4_size=0)
    _touch(upscale_artifact_paths(Path(recording["path"]))[0], NOW - 30 * DAY, size=5)
    items = retention.derived_candidates([recording], _resolve, DAY, NOW,
                                         has_media=_has(recording))
    assert items[0]["bytes"] == 5
    assert items[0]["includes_source"] is False


# ---- ③ 原本: 素材が残る録画では素材そのもの ------------------------------------------


def test_the_source_phase_points_at_the_material_when_it_remains(make_rec):
    recording = make_rec(mp4_size=100)
    items = retention.source_candidates(
        [recording], _resolve, DAY, NOW,
        has_media=_has(recording), media_usage=_usage(r1=(4096, 3, NOW - 30 * DAY)))
    assert [i["recording_id"] for i in items] == [recording["id"]]
    assert items[0]["media"] is True
    # 素材ぶんだけ。mp4は②が数えており、両方へ載せると解放見込みが実在しない量まで膨らむ。
    assert items[0]["bytes"] == 4096
    assert items[0]["files"] == 3


def test_the_source_phase_points_at_the_mp4_without_material(make_rec):
    recording = make_rec(mp4_size=100)
    items = retention.source_candidates([recording], _resolve, DAY, NOW,
                                        has_media=_has(), media_usage=_usage())
    assert items[0]["media"] is False
    assert items[0]["bytes"] == 100


def test_the_source_phase_lists_material_whose_mp4_is_already_gone(make_rec):
    """②がmp4を消した録画。素材はまだ原本として残っているので、③の候補であり続ける。"""
    recording = make_rec(mp4_size=0)
    items = retention.source_candidates(
        [recording], _resolve, DAY, NOW,
        has_media=_has(recording), media_usage=_usage(r1=(4096, 3, NOW - 30 * DAY)))
    assert [i["recording_id"] for i in items] == [recording["id"]]
    assert items[0]["bytes"] == 4096


def test_the_source_phase_ignores_an_empty_material_reading(make_rec):
    """素材が在ると言われても実体が読めなければ、素材を原本と主張しない。"""
    recording = make_rec(mp4_size=0)
    assert retention.source_candidates(
        [recording], _resolve, DAY, NOW,
        has_media=_has(recording), media_usage=_usage()) == []


def test_the_source_phase_uses_the_material_mtime_when_ended_at_is_missing(make_rec):
    recording = make_rec(mp4_size=0, ended_at=None)
    usage = _usage(r1=(4096, 3, NOW - 60.0))
    has_media = _has(recording)
    assert retention.source_candidates([recording], _resolve, DAY, NOW,
                                       has_media=has_media, media_usage=usage) == []
    old = retention.source_candidates([recording], _resolve, 30.0, NOW,
                                      has_media=has_media, media_usage=usage)
    assert [i["recording_id"] for i in old] == [recording["id"]]


def test_a_protected_recording_keeps_its_material(make_rec):
    recording = make_rec(mp4_size=100, protected=1)
    assert retention.source_candidates(
        [recording], _resolve, DAY, NOW,
        has_media=_has(recording), media_usage=_usage(r1=(4096, 3, 1.0))) == []


# ---- plan ---------------------------------------------------------------------------


def test_build_plan_hands_the_material_check_to_both_phases(make_rec, tmp_path):
    recording = make_rec(mp4_size=100)
    rules = {"transient_hours": 0, "derived_days": 1, "source_days": 1,
             "source_enabled": 1}
    plan = retention.build_plan(
        [recording], [tmp_path], _resolve, rules, NOW,
        has_media=_has(recording), media_usage=_usage(r1=(4096, 3, NOW - 30 * DAY)))
    assert [p["phase"] for p in plan["phases"]] == list(retention.PHASE_ORDER)
    derived, source = plan["phases"][1], plan["phases"][2]
    assert derived["items"][0]["includes_source"] is True
    assert source["items"][0]["media"] is True
    # ②のmp4と③の素材は別のfile。合計は両方を足したもので、二重計上ではない。
    assert plan["total_bytes"] == 100 + 4096


def test_build_plan_without_a_material_check_keeps_the_old_ordering(make_rec, tmp_path):
    """素材を見ない呼び出しでは、従来どおりmp4が③の原本として扱われる。"""
    recording = make_rec(mp4_size=100)
    rules = {"transient_hours": 0, "derived_days": 1, "source_days": 1,
             "source_enabled": 1}
    plan = retention.build_plan([recording], [tmp_path], _resolve, rules, NOW)
    assert plan["phases"][1]["items"] == []
    assert plan["phases"][2]["items"][0]["bytes"] == 100
