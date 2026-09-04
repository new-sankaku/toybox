"""最終保存先が2系統あるときの移送と再同期のtest。

2系統は**振り分け先ではなく相互mirror**である。1台のdiskが壊れても二次保存のdataが残る
ようにするためのもので、両系統は常に同じ内容でなければならない。したがってこのfileが守って
いるのは次の3つで、どれか1つでも崩れると機能の目的そのものが無くなる:

  1. 1系統だけの構成では**今までとまったく同じmove**であること(回帰を出さない)。
  2. 2系統では全系統へ揃うこと。**片方にでも書けないなら移送そのものを行わず、元が残る**こと。
  3. 片系統が見えないときは、空のdirectoryを「同期済み」と読み違えないこと。

rootは ``runtime.RECORD_DIR`` ではなく毎testのtmpへ張る。runtimeはimport時に1度だけrootを
掴むmodule singletonで、全testが最初のtestのsandboxを共有するため(tests/test_server.py の
relocation_dirs と同じ理由)。
"""

from pathlib import Path

import pytest
from fastapi import HTTPException

from tictok.record import mirror

from tests.test_server import (  # noqa: F401  (fixtureとして使う)
    _make_relocatable, client, server,
)


@pytest.fixture
def mirror_dirs(server, tmp_path, monkeypatch):
    """作業先と最終保存先2系統をtmpへ振り替える。本番のrecordings配下には一切触れない。"""
    work = tmp_path / "work"
    final1 = tmp_path / "final1"
    final2 = tmp_path / "final2"
    for path in (work, final1, final2):
        path.mkdir()
    monkeypatch.setattr(server.runtime, "RECORD_DIR", work.resolve())
    monkeypatch.setattr(server.runtime, "FINAL_DIR", final1.resolve())
    monkeypatch.setattr(server.runtime, "FINAL_DIRS", [final1.resolve(), final2.resolve()])
    return work.resolve(), final1.resolve(), final2.resolve()


@pytest.fixture
def single_final_dir(server, tmp_path, monkeypatch):
    """最終保存先が1系統だけの現状の構成。"""
    work = tmp_path / "work"
    final = tmp_path / "final"
    work.mkdir()
    final.mkdir()
    monkeypatch.setattr(server.runtime, "RECORD_DIR", work.resolve())
    monkeypatch.setattr(server.runtime, "FINAL_DIR", final.resolve())
    monkeypatch.setattr(server.runtime, "FINAL_DIRS", [final.resolve()])
    return work.resolve(), final.resolve()


def _recording_files(server, root: Path, stem: str) -> dict:
    """その録画が ``root`` に持っているfileを ``相対path -> size`` で返す。"""
    from tictok.record.recorder import relocatable_artifact_paths

    found: dict = {}
    session = server.layout.session_dir(root, stem)
    if session.is_dir():
        for path in sorted(session.iterdir()):
            if path.is_file():
                found[path.relative_to(root).as_posix()] = path.stat().st_size
    mp4 = server.layout.mp4_path(root, stem)
    for path in [mp4, *relocatable_artifact_paths(mp4)]:
        if path.is_file():
            found[path.relative_to(root).as_posix()] = path.stat().st_size
    return found


# ---- (a) 1系統だけの構成 -------------------------------------------------------------

def test_single_final_dir_still_uses_the_plain_move(server, single_final_dir, monkeypatch):
    """最終保存先が1つなら今までどおり ``_move_recording_files`` のmoveを通る。

    同一volumeならrenameで済む経路をcopyへ置き換える理由が無く、mirrorの複製経路は2系統
    以上のときだけ意味を持つ。ここが崩れると、今動いている構成の移送が全部copyになる。
    """
    work, final = single_final_dir
    recording_id, src = _make_relocatable(server, work, segments=2)
    calls: list = []
    real_move = server.Recorder._move_recording_files

    def _spy(src_path, dst_path):
        calls.append((Path(src_path), Path(dst_path)))
        return real_move(src_path, dst_path)

    copies: list = []
    monkeypatch.setattr(server.Recorder, "_move_recording_files", staticmethod(_spy))
    monkeypatch.setattr(mirror, "copy_recording_files",
                        lambda *args: copies.append(args))

    plan = server.disk._relocation_plan()
    assert [item["dsts"] for item in plan["items"] if item["recording_id"] == recording_id] \
        == [[str(server.layout.mp4_path(final, src.stem))]]
    result = server.disk._run_relocation(plan)

    assert result["moved"] == 1, result
    assert len(calls) == 1 and calls[0][0] == src
    assert not copies, "1系統ではmirrorの複製経路を通らないこと"
    assert not src.is_file()
    assert server.layout.mp4_path(final, src.stem).is_file()


# ---- (b) 2系統へ揃う -----------------------------------------------------------------

def test_relocation_writes_every_final_dir_and_clears_the_source(server, mirror_dirs):
    """2系統では全系統へ同じ内容が揃い、作業先からは実体が消える。"""
    work, final1, final2 = mirror_dirs
    recording_id, src = _make_relocatable(server, work, segments=3)
    stem = src.stem
    before = _recording_files(server, work, stem)
    assert before, "前提: 作業先に実体が在ること"

    plan = server.disk._relocation_plan()
    assert plan["final_dirs"] == [str(final1), str(final2)]
    result = server.disk._run_relocation(plan)

    assert result["moved"] == 1, result
    assert _recording_files(server, final1, stem) == before
    assert _recording_files(server, final2, stem) == before
    assert _recording_files(server, work, stem) == {}
    # DBのpathは代表(1系統目)を指す。読み出しはどちらの系統からでも同じ内容が読める。
    row = server.runtime.storage.get_recording(recording_id)
    assert row["path"] == str(server.layout.mp4_path(final1, stem))


def test_relocation_carries_clips_to_every_final_dir(server, mirror_dirs):
    """成果物(切り出し)も全系統へ随伴する。台帳がfile systemだけなので、片系統だけに在る
    1本は誰も居場所を辿れない。"""
    work, final1, final2 = mirror_dirs
    _recording_id, src = _make_relocatable(server, work, unique_id="alice", segments=1)
    clip = server.layout.clips_dir(work, "alice") / f"{src.stem}_clip_0_10.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"\x11" * 512)

    result = server.disk._run_relocation(server.disk._relocation_plan())

    assert result["clips_moved"] == 1, result
    rel = clip.relative_to(work)
    assert (final1 / rel).read_bytes() == b"\x11" * 512
    assert (final2 / rel).read_bytes() == b"\x11" * 512
    assert not clip.exists()


# ---- (c) 片方に書けない ---------------------------------------------------------------

def test_relocation_is_not_performed_when_one_final_dir_cannot_be_written(
        server, mirror_dirs, monkeypatch):
    """2系統目に書けないなら移送しない。1系統目へ書けた分も消し、元は作業先に残る。

    片側だけが最新という状態を作らないことがこの機能の全部である(それが、次の障害で気付か
    ないままdataを失う唯一の経路である)。
    """
    work, final1, final2 = mirror_dirs
    recording_id, src = _make_relocatable(server, work, segments=3)
    stem = src.stem
    before = _recording_files(server, work, stem)
    real_copy = mirror.copy_file

    def _copy(src_path, dst_path):
        if str(dst_path).startswith(str(final2)):
            raise OSError("test: 2系統目に書けません")
        return real_copy(src_path, dst_path)

    monkeypatch.setattr(mirror, "copy_file", _copy)
    result = server.disk._run_relocation(server.disk._relocation_plan())

    assert result["moved"] == 0
    assert len(result["failures"]) == 1, result
    assert _recording_files(server, work, stem) == before, "元が作業先に残ること"
    assert _recording_files(server, final1, stem) == {}, "書けた側は巻き戻すこと"
    assert _recording_files(server, final2, stem) == {}
    row = server.runtime.storage.get_recording(recording_id)
    assert row["path"] == str(src), "移送していない録画のpathは書き換えないこと"


# ---- (d) 再同期 -----------------------------------------------------------------------

def test_resync_fills_the_gaps_in_both_directions(server, mirror_dirs):
    """片方にしか無いfileを、在る方から欠けている方へ複製する。向きは片方向ではない。"""
    work, final1, final2 = mirror_dirs
    only1 = final1 / "alice" / "mp4" / "00001_alice_20260101_000000.mp4"
    only2 = final2 / "alice" / "_clips" / "00002_alice_20260101_000000_clip.mp4"
    for path, blob in ((only1, b"\x01" * 300), (only2, b"\x02" * 200)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)

    plan = server.disk._mirror_plan()
    assert plan["enabled"] is True
    assert plan["total_items"] == 2, plan
    assert plan["total_bytes"] == 500

    result = server.disk._run_mirror_resync(plan)

    assert result["copied"] == 2 and not result["failures"], result
    assert (final2 / only1.relative_to(final1)).read_bytes() == b"\x01" * 300
    assert (final1 / only2.relative_to(final2)).read_bytes() == b"\x02" * 200
    # 元は消さない。移送と違い、再同期は両系統を同じにするだけの操作である。
    assert only1.is_file() and only2.is_file()
    assert server.disk._mirror_plan()["total_items"] == 0


def test_resync_never_overwrites_a_file_whose_size_differs(server, mirror_dirs):
    """同名でsizeが違うfileは触らず、件数だけを返す。どちらが正しいかは人が決める。"""
    work, final1, final2 = mirror_dirs
    rel = Path("alice") / "mp4" / "00003_alice_20260101_000000.mp4"
    (final1 / rel).parent.mkdir(parents=True, exist_ok=True)
    (final2 / rel).parent.mkdir(parents=True, exist_ok=True)
    (final1 / rel).write_bytes(b"\x01" * 400)
    (final2 / rel).write_bytes(b"\x02" * 100)

    plan = server.disk._mirror_plan()
    assert plan["total_items"] == 0
    assert plan["diverged_count"] == 1
    assert plan["diverged"][0]["rel"] == rel.as_posix()

    result = server.disk._run_mirror_resync(plan)

    assert result["copied"] == 0
    assert result["diverged_count"] == 1
    assert (final1 / rel).read_bytes() == b"\x01" * 400
    assert (final2 / rel).read_bytes() == b"\x02" * 100


def test_resync_leaves_the_cross_recording_pools_alone(server, mirror_dirs):
    """録画横断のpool(avatars等)は突き合わせない。置き場はwork rootただ1つで、最終保存先に
    在るのはdriveを丸ごと写した頃の名残であり、複製しても誰も読まない。"""
    work, final1, final2 = mirror_dirs
    avatar = final1 / "avatars" / "by-id" / "123.jpg"
    avatar.parent.mkdir(parents=True, exist_ok=True)
    avatar.write_bytes(b"\x00" * 16)

    plan = server.disk._mirror_plan()

    assert plan["total_items"] == 0, plan
    assert not (final2 / "avatars").exists()


def test_resync_api_reports_the_plan_and_copies_on_confirm(server, client, mirror_dirs):
    """dry-runと実行の2段。既定はdry-runで、confirmが無ければ1 fileも複製しない。"""
    work, final1, final2 = mirror_dirs
    only1 = final1 / "alice" / "mp4" / "00004_alice_20260101_000000.mp4"
    only1.parent.mkdir(parents=True, exist_ok=True)
    only1.write_bytes(b"\x03" * 128)

    listed = client.get("/api/storage/mirror").json()
    assert listed["enabled"] is True and listed["total_items"] == 1
    assert "files" not in listed["items"][0], "応答に実行用のfile名の一覧は載せないこと"
    assert listed["current"] is True

    dry = client.post("/api/storage/mirror/resync", json={"confirm": False}).json()
    assert dry["applied"] is False
    assert not (final2 / only1.relative_to(final1)).exists()

    applied = client.post("/api/storage/mirror/resync", json={"confirm": True}).json()
    assert applied["applied"] is True
    assert applied["result"]["copied"] == 1
    assert (final2 / only1.relative_to(final1)).read_bytes() == b"\x03" * 128
    # 実行後に返すplanは**実行前**に採ったもの。それを「残り」として描かせないために、
    # 現在の状態でないことを応答自身が名乗る(取り直すには全走査をもう一度回すことになる)。
    assert applied["plan"]["current"] is False
    assert applied["plan"]["total_items"] == 1


def test_resync_is_refused_without_a_second_final_dir(server, client, single_final_dir):
    """相手が居ない構成では再同期そのものを断る。"""
    assert client.post("/api/storage/mirror/resync", json={"confirm": True}).status_code == 409
    assert server.disk._mirror_plan()["enabled"] is False


# ---- 片系統が見えない -----------------------------------------------------------------

def test_a_missing_final_dir_stops_the_relocation_instead_of_looking_synced(
        server, mirror_dirs):
    """外れているdiskを「空」と読まない。移送対象を1本も出さず、見えない系統を名乗る。"""
    work, final1, final2 = mirror_dirs
    _recording_id, src = _make_relocatable(server, work, segments=2)
    final2.rmdir()

    plan = server.disk._relocation_plan()

    assert plan["enabled"] is True, "設定は生きている(見えていないだけである)"
    assert plan["unavailable_dirs"] == [str(final2)]
    assert plan["items"] == [], "見えない系統が在る間は1本も移送対象にしないこと"
    assert src.is_file()


def test_a_missing_final_dir_is_recorded_as_an_ops_event(server, mirror_dirs):
    """diskが外れていた事実を運用logに残す。後から「なぜあの日から片方が古いのか」に
    答えられる唯一の手掛かりになる。"""
    work, final1, final2 = mirror_dirs
    final2.rmdir()

    with pytest.raises(HTTPException) as excinfo:
        server.disk._require_mirrors_available("最終保存先への退避")
    assert excinfo.value.status_code == 409

    events = server.runtime.storage.list_ops_events(limit=20)
    unavailable = [e for e in events if e["kind"] == "storage.mirror_unavailable"]
    assert unavailable, "見えない系統がops_eventとして残ること"
    assert unavailable[0]["severity"] == "warning"
    assert unavailable[0]["detail"]["missing"] == [str(final2)]


def test_resync_does_not_scan_while_a_final_dir_is_missing(server, mirror_dirs):
    """見えない系統が在る間は突き合わせない。空に見えるrootを相手にすると、最終保存先の中身を
    丸ごと(実測2026-09-02で12,340 file / 0.59TB)複製する計画が出てしまう。"""
    work, final1, final2 = mirror_dirs
    (final1 / "alice").mkdir()
    (final1 / "alice" / "x.mp4").write_bytes(b"\x00" * 8)
    final2.rmdir()

    plan = server.disk._mirror_plan()

    assert plan["unavailable_dirs"] == [str(final2)]
    assert plan["items"] == [] and plan["total_items"] == 0


# ---- 突き合わせた結果を残す ----------------------------------------------------------
# 走査は両rootの全dirを辿るので画面を開くたびには回せない。残さなければ「最後に揃っていると
# 確かめたのはいつか」に誰も答えられず、二重化が効いているかはその1点でしか読めない。

def test_a_scan_records_when_it_ran_and_what_it_found(server, mirror_dirs):
    work, final1, final2 = mirror_dirs
    (final1 / "alice").mkdir()
    (final1 / "alice" / "x.mp4").write_bytes(b"\x00" * 8)

    server.disk._mirror_plan()
    check = server.disk.mirror_check_status()

    assert check["at"], "走査した時刻を残すこと"
    assert check["missing_items"] == 1
    assert check["stale"] is False
    # 系統ごとに分けて残す。合計だけでは、どちらのdriveが古いのかを名指しできない。
    assert check["missing_by_dst"] == {str(final2): {"count": 1, "bytes": 8}}


def test_a_scan_that_never_ran_is_not_recorded_as_synced(server, mirror_dirs):
    """見えない系統が在る回は走査していない。それを0件として残すと、突き合わせていない
    ことが「揃っている」として記録に残る。"""
    work, final1, final2 = mirror_dirs
    final2.rmdir()

    server.disk._mirror_plan()

    assert server.disk.mirror_check_status()["at"] is None


def test_a_resync_marks_the_saved_result_as_stale(server, mirror_dirs):
    """残っている要約は再同期の瞬間から実行前の姿になる。0件へ書き換えないのは、複製に
    失敗した分まで「揃った」と読ませないためである。"""
    work, final1, final2 = mirror_dirs
    (final1 / "alice").mkdir()
    (final1 / "alice" / "x.mp4").write_bytes(b"\x00" * 8)
    server.disk._mirror_plan()

    server.disk.invalidate_mirror_check()
    check = server.disk.mirror_check_status()

    assert check["stale"] is True
    assert check["missing_items"] == 1, "件数は残す(実行前の姿であることだけを名乗る)"


def test_a_result_taken_for_other_drives_is_discarded(server, mirror_dirs, monkeypatch):
    """別の2 driveについての答えを「最後に確かめた日」として出すと、設定を変えた日から
    誰も確かめていないことが隠れる。"""
    work, final1, final2 = mirror_dirs
    (final1 / "alice").mkdir()
    (final1 / "alice" / "x.mp4").write_bytes(b"\x00" * 8)
    server.disk._mirror_plan()
    assert server.disk.mirror_check_status()["at"]

    other = final2.parent / "final3"
    other.mkdir()
    monkeypatch.setattr(server.runtime, "FINAL_DIRS", [final1, other])
    monkeypatch.setattr(server.runtime, "FINAL_DIR", final1)

    assert server.disk.mirror_check_status()["at"] is None
