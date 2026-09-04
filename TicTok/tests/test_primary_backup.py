"""一次保存先の定期backup(tictok.record.primary_backup)。

見ているのは「元を残したまま控えを作る」機能の、壊れると気付けない性質だけである:
差分の判定・書きかけからの再開・削除を伝播させない猶予・始める前の空きの判定・
73万fileのpoolをarchiveへ畳む経路。
"""
import os
import shutil
import time
import zipfile
from collections import namedtuple
from pathlib import Path

import pytest

from tictok.core import config, layout
from tictok.record import primary_backup


def _write(path: Path, text: str, mtime=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def roots(env_guard, monkeypatch):
    """一次保存先(sandbox/recordings)と、別driveに見立てたbackup先。"""
    src = Path(env_guard) / "recordings"
    dest = Path(env_guard) / "backupdrive"
    src.mkdir(parents=True, exist_ok=True)
    dest.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TICTOK_RECORD_BACKUP_DIR", str(dest))
    layout.reset_pool_root()
    return src, dest


def _seed(src: Path) -> None:
    """録画1本ぶんの最小構成 + 使い捨ての退避。"""
    _write(src / "alice" / "ts" / "00001_alice_20260101_120000" / "seg0.ts", "seg0")
    _write(src / "alice" / "ts" / "00001_alice_20260101_120000" / "seg1.ts", "seg1")
    _write(src / "alice" / "mp4" / "00001_alice_20260101_120000.mp4", "movie")
    _write(src / "alice" / "_clips" / "00001_alice_20260101_120000_clip1.mp4", "clip")
    # 差し替えの退避。使い捨てなので控えには入らない。
    _write(src / "_backup" / "00001_alice_20260101_120000.mp4", "old movie")


def _tree(dest: Path) -> Path:
    return dest / primary_backup.PRIMARY_BACKUP_DIRNAME / primary_backup.TREE_DIRNAME


def _rels(root: Path) -> set:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


# ---------------- 設定 ----------------

def test_is_configured_requires_destination(roots, monkeypatch):
    assert primary_backup.is_configured() is True
    monkeypatch.setenv("TICTOK_RECORD_BACKUP_DIR", "")
    assert primary_backup.is_configured() is False


async def test_run_backup_refuses_when_not_configured(roots, monkeypatch):
    monkeypatch.setenv("TICTOK_RECORD_BACKUP_DIR", "")
    with pytest.raises(primary_backup.PrimaryBackupError):
        await primary_backup.run_backup()


async def test_run_backup_refuses_nested_roots(roots, monkeypatch):
    src, _dest = roots
    _seed(src)
    # backup先を一次保存先の中に置くと、写した物を次の走査が写し続ける。
    monkeypatch.setenv("TICTOK_RECORD_BACKUP_DIR", str(src / "inside"))
    with pytest.raises(primary_backup.PrimaryBackupError):
        await primary_backup.run_backup()


# ---------------- (a) 初回は全部写す ----------------

async def test_first_run_copies_everything_but_the_disposable_backup(roots):
    src, dest = roots
    _seed(src)

    result = await primary_backup.run_backup()

    tree = _tree(dest)
    assert _rels(tree) == {
        "alice/ts/00001_alice_20260101_120000/seg0.ts",
        "alice/ts/00001_alice_20260101_120000/seg1.ts",
        "alice/mp4/00001_alice_20260101_120000.mp4",
        "alice/_clips/00001_alice_20260101_120000_clip1.mp4",
    }
    assert result["copied"] == 4
    assert result["skipped"] == 0
    assert result["failed"] == 0
    # 元は残る。移送(relocate)と違い、これは控えを作る操作である。
    assert (src / "alice" / "mp4" / "00001_alice_20260101_120000.mp4").is_file()
    assert (tree / "alice" / "mp4" / "00001_alice_20260101_120000.mp4").read_text(
        encoding="utf-8") == "movie"


async def test_progress_reports_start_and_end(roots):
    src, _dest = roots
    _seed(src)
    seen: list = []

    await primary_backup.run_backup(on_progress=lambda d, t, c: seen.append((d, t, c)))

    assert seen[0][0] == 0
    assert seen[-1][0] == seen[-1][1] == 4


# ---------------- (b) 2回目は差分だけ ----------------

async def test_second_run_copies_only_changed_files(roots):
    src, dest = roots
    _seed(src)
    await primary_backup.run_backup()

    unchanged = await primary_backup.run_backup()
    assert unchanged["copied"] == 0
    assert unchanged["skipped"] == 4

    # 判定は size + mtime。sizeを変えずmtimeも動かさない書き換えは拾えない(module
    # docstringの通り、この保存先の中身では起きない形)ので、testも実際の変化を作る。
    changed = src / "alice" / "mp4" / "00001_alice_20260101_120000.mp4"
    _write(changed, "movie v2 longer", mtime=time.time() + 3600)

    result = await primary_backup.run_backup()
    assert result["copied"] == 1
    assert result["skipped"] == 3
    assert (_tree(dest) / "alice" / "mp4" / "00001_alice_20260101_120000.mp4").read_text(
        encoding="utf-8") == "movie v2 longer"


async def test_second_run_recopies_a_file_deleted_from_the_backup(roots):
    """控え側だけが消えたfileは写し直す。台帳ではなく写した先のstatで判定する効き目。"""
    src, dest = roots
    _seed(src)
    await primary_backup.run_backup()
    (_tree(dest) / "alice" / "ts" / "00001_alice_20260101_120000" / "seg0.ts").unlink()

    result = await primary_backup.run_backup()

    assert result["copied"] == 1
    assert (_tree(dest) / "alice" / "ts" / "00001_alice_20260101_120000"
            / "seg0.ts").is_file()


# ---------------- (c) 書きかけからの再開 ----------------

async def test_leftover_partial_is_swept_and_the_file_is_copied(roots):
    src, dest = roots
    _seed(src)
    tree = _tree(dest)
    # serverが写している最中に落ちた姿: 最終名は無く、書きかけだけが残っている。
    _write(tree / "alice" / "mp4"
           / ("00001_alice_20260101_120000.mp4" + primary_backup.PARTIAL_SUFFIX), "mov")

    result = await primary_backup.run_backup()

    assert result["swept_partials"] == 1
    assert result["copied"] == 4
    assert not list(tree.rglob("*" + primary_backup.PARTIAL_SUFFIX))
    assert (tree / "alice" / "mp4" / "00001_alice_20260101_120000.mp4").read_text(
        encoding="utf-8") == "movie"


async def test_leftover_pool_archive_partial_is_swept(roots):
    """取り消しが残したarchiveの書きかけを掃く。1本がGB規模で、作り直す条件を満たすまで
    誰も上書きしないため、掃かないとbackup先に居座り続ける。"""
    src, dest = roots
    _seed(src)
    _seed_pools(src)
    pool_dir = (dest / primary_backup.PRIMARY_BACKUP_DIRNAME
                / primary_backup.POOL_ARCHIVE_DIRNAME)
    pool_dir.mkdir(parents=True, exist_ok=True)
    _write(pool_dir / ("avatars-20200101-000000.zip" + primary_backup.PARTIAL_SUFFIX), "x")

    result = await primary_backup.run_backup()

    assert result["swept_partials"] == 1
    assert not list(pool_dir.glob("*" + primary_backup.PARTIAL_SUFFIX))


async def test_partial_is_not_counted_as_a_deleted_file(roots):
    """書きかけを「一次保存先から消えたfile」として台帳へ載せない。"""
    src, dest = roots
    _seed(src)
    await primary_backup.run_backup()
    _write(_tree(dest) / "alice" / ("ghost.mp4" + primary_backup.PARTIAL_SUFFIX), "x")

    result = await primary_backup.run_backup()

    assert result["marked_deleted"] == 0


# ---------------- (d) 削除の猶予 ----------------

async def test_deleted_source_file_is_kept_and_recorded(roots):
    src, dest = roots
    _seed(src)
    await primary_backup.run_backup()
    (src / "alice" / "_clips" / "00001_alice_20260101_120000_clip1.mp4").unlink()

    result = await primary_backup.run_backup()

    assert result["marked_deleted"] == 1
    assert result["deleted"] == 0
    # 既定(0日)は消さない。誤削除を控えへ伝播させないため。
    assert (_tree(dest) / "alice" / "_clips"
            / "00001_alice_20260101_120000_clip1.mp4").is_file()
    ledger = primary_backup._load_ledger(dest / primary_backup.PRIMARY_BACKUP_DIRNAME)
    assert "alice/_clips/00001_alice_20260101_120000_clip1.mp4" in ledger["deleted"]


async def test_deleted_source_file_is_removed_after_the_grace_period(roots, monkeypatch):
    src, dest = roots
    _seed(src)
    await primary_backup.run_backup()
    rel = "alice/_clips/00001_alice_20260101_120000_clip1.mp4"
    (src / rel).unlink()
    monkeypatch.setattr(config, "get_record_backup_keep_deleted_days", lambda: 7)

    marked = await primary_backup.run_backup()
    assert marked["deleted"] == 0

    # 消えたと気付いた日を8日前へ動かす(猶予は台帳の日時から数える)。
    root = dest / primary_backup.PRIMARY_BACKUP_DIRNAME
    ledger = primary_backup._load_ledger(root)
    ledger["deleted"][rel] = time.time() - 8 * 86400
    primary_backup._save_ledger(root, ledger)

    result = await primary_backup.run_backup()

    assert result["deleted"] == 1
    assert not (_tree(dest) / rel).exists()
    assert rel not in primary_backup._load_ledger(root)["deleted"]


async def test_file_returning_to_the_source_clears_the_deletion_mark(roots, monkeypatch):
    src, dest = roots
    _seed(src)
    await primary_backup.run_backup()
    rel = "alice/_clips/00001_alice_20260101_120000_clip1.mp4"
    (src / rel).unlink()
    await primary_backup.run_backup()

    _write(src / rel, "clip")
    monkeypatch.setattr(config, "get_record_backup_keep_deleted_days", lambda: 7)
    result = await primary_backup.run_backup()

    assert result["restored"] == 1
    root = dest / primary_backup.PRIMARY_BACKUP_DIRNAME
    assert rel not in primary_backup._load_ledger(root)["deleted"]


# ---------------- (e) 空きが足りなければ始めない ----------------

async def test_refuses_to_start_when_the_destination_is_short_on_space(roots, monkeypatch):
    src, dest = roots
    _seed(src)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage(1000, 999, 1))

    with pytest.raises(primary_backup.PrimaryBackupError):
        await primary_backup.run_backup()

    # 1byteも書かない。溢れたあとの木は、次の走査から見ると「写し済み」に見える。
    assert not _rels(_tree(dest))


# ---------------- 進行中の録画を外す ----------------

SESSION = "alice/ts/00001_alice_20260101_120000"

# 進行中の録画1本につき呼ぶ側が渡す3つ。置き場が3箇所に分かれているため
# (tictok.core.layout)、1つでも欠けるとその置き場のfileだけが書き込み中のまま写る。
# **拡張子を付けない接頭辞**で渡す ―― 1 stemから派生が複数出て、走っている最中にも増える。
IN_FLIGHT = (
    "alice/ts/00001_alice_20260101_120000",
    "alice/mp4/00001_alice_20260101_120000",
    ".sidecars/00001_alice_20260101_120000",
)

# 覆えているべき物と、巻き込んではいけない物。**照合そのものを直接叩く**ためのtable。
# 以前これが無く、`/` の境目しか見ていない照合で mp4 と sidecar が素通りしていたのに、
# 高い階層のtestは全部通っていた。
_COVERAGE = [
    ("ts配下",      "alice/ts/00001_alice_20260101_120000/seg0.ts", True),
    ("完成mp4",     "alice/mp4/00001_alice_20260101_120000.mp4", True),
    ("焼き込み",    "alice/mp4/00001_alice_20260101_120000.overlay.mp4", True),
    ("波形",        ".sidecars/00001_alice_20260101_120000.waveform.json", True),
    ("別stem",      "alice/mp4/00001_alice_20260101_1200002.mp4", False),
]


@pytest.mark.parametrize("label,rel,covered", _COVERAGE)
def test_exclusion_covers_every_place_a_recording_writes(label, rel, covered):
    """除外の照合は ``/`` と ``.`` の両方を境目に見る。

    ``/`` だけだと ``alice/mp4/<stem>`` が ``<stem>.mp4`` に一致せず、進行中の録画の
    mp4とsidecarが素通りで写る。``.`` を境目にしても別stemは巻き込まない。"""
    assert primary_backup._is_excluded(rel, frozenset(IN_FLIGHT)) is covered


@pytest.mark.parametrize("label,rel,covered", _COVERAGE)
def test_walk_holds_back_every_place_a_recording_writes(tmp_path, label, rel, covered):
    """照合だけでなく、**実際に写す経路**(走査)からも外れていること。

    照合(``_is_excluded``)を使うのは削除の伝播だけで、copyするかを決めるのは走査である。
    片方だけ直しても、書き込み中のmp4は控えへ写り続ける。"""
    for _l, path, _c in _COVERAGE:
        _write(tmp_path / path, "x")

    seen = {r for r, _s, _m in
            primary_backup._iter_tree(tmp_path, (), frozenset(IN_FLIGHT))}

    assert (rel not in seen) is covered


async def test_in_flight_recording_is_held_back_from_every_place(roots):
    """録画中の3箇所すべてが控えへ写らない(素材・mp4と派生・sidecar)。"""
    src, dest = roots
    _seed(src)
    _write(src / "alice" / "mp4" / "00001_alice_20260101_120000.overlay.mp4", "overlay")
    _write(src / ".sidecars" / "00001_alice_20260101_120000.waveform.json", "{}")
    # 別の録画。巻き込まれずに写ること。
    _write(src / "alice" / "mp4" / "00002_alice_20260102_120000.mp4", "other")

    result = await primary_backup.run_backup(exclude_rels=IN_FLIGHT)

    assert _rels(_tree(dest)) == {
        "alice/mp4/00002_alice_20260102_120000.mp4",
        "alice/_clips/00001_alice_20260101_120000_clip1.mp4",
    }
    assert result["excluded"] == 3
    assert sorted(result["excluded_rels"]) == sorted(IN_FLIGHT)


async def test_excluded_path_is_not_copied(roots):
    """外したpath以下は1 fileも写らない(書き込み中の.tsを控えへ持ち込まない)。"""
    src, dest = roots
    _seed(src)

    result = await primary_backup.run_backup(exclude_rels=[SESSION])

    assert _rels(_tree(dest)) == {
        "alice/mp4/00001_alice_20260101_120000.mp4",
        "alice/_clips/00001_alice_20260101_120000_clip1.mp4",
    }
    assert result["copied"] == 2
    assert result["excluded"] == 1
    assert result["excluded_rels"] == [SESSION]


async def test_excluded_files_are_never_marked_deleted(roots):
    """外している間に削除の印を付けない。除外は「まだ見ていない」で「消えた」ではない。

    印が付くと、一次保存先に**実在するfile**の控えが猶予切れで消される ―― 控えを取る
    操作が控えを壊す形になる。"""
    src, dest = roots
    _seed(src)
    await primary_backup.run_backup()
    assert (_tree(dest) / SESSION / "seg0.ts").is_file()

    result = await primary_backup.run_backup(exclude_rels=[SESSION])

    assert result["marked_deleted"] == 0
    root = dest / primary_backup.PRIMARY_BACKUP_DIRNAME
    assert primary_backup._load_ledger(root)["deleted"] == {}
    # 控えは残ったまま。
    assert (_tree(dest) / SESSION / "seg0.ts").is_file()


async def test_exclusion_does_not_disturb_an_existing_deletion_mark(roots, monkeypatch):
    """既に付いている印も、除外の下なら動かさない(猶予の起点が黙って今日へ動かない)。"""
    src, dest = roots
    _seed(src)
    await primary_backup.run_backup()
    (src / SESSION / "seg1.ts").unlink()
    await primary_backup.run_backup()
    root = dest / primary_backup.PRIMARY_BACKUP_DIRNAME
    marked_at = primary_backup._load_ledger(root)["deleted"][f"{SESSION}/seg1.ts"]

    await primary_backup.run_backup(exclude_rels=[SESSION])

    assert primary_backup._load_ledger(root)["deleted"][f"{SESSION}/seg1.ts"] == marked_at


async def test_excluded_path_is_copied_on_the_next_run_without_it(roots):
    """録画が終わって除外が外れれば、次の回で写される。"""
    src, dest = roots
    _seed(src)
    await primary_backup.run_backup(exclude_rels=[SESSION])
    _write(src / SESSION / "seg2.ts", "seg2")

    result = await primary_backup.run_backup()

    assert result["excluded"] == 0
    assert result["excluded_rels"] == []
    assert _rels(_tree(dest) / "alice" / "ts") == {
        "00001_alice_20260101_120000/seg0.ts",
        "00001_alice_20260101_120000/seg1.ts",
        "00001_alice_20260101_120000/seg2.ts",
    }


async def test_no_exclusion_behaves_exactly_as_before(roots):
    src, dest = roots
    _seed(src)

    result = await primary_backup.run_backup(exclude_rels=[])

    assert result["copied"] == 4
    assert result["excluded"] == 0
    assert len(_rels(_tree(dest))) == 4


async def test_a_single_excluded_file_is_held_back(roots):
    """dirだけでなくfile単体でも外せる(確定直前のmp4など)。"""
    src, dest = roots
    _seed(src)

    await primary_backup.run_backup(
        exclude_rels=["alice/mp4/00001_alice_20260101_120000.mp4"])

    assert not (_tree(dest) / "alice" / "mp4").exists()
    assert (_tree(dest) / SESSION / "seg0.ts").is_file()


async def test_absolute_exclusion_paths_are_accepted(roots):
    """呼ぶ側はDBの録画pathを持っているので、絶対pathでも通す。"""
    src, dest = roots
    _seed(src)

    result = await primary_backup.run_backup(exclude_rels=[src / SESSION])

    assert result["excluded_rels"] == [SESSION]
    assert not (_tree(dest) / SESSION).exists()


async def test_an_exclusion_outside_the_source_is_refused(roots, tmp_path):
    """一次保存先の外を指す絶対pathは投げる。

    黙って一致しないままにすると、外したつもりの録画が普通に写される ―― 除外が効いて
    いないことに気付けない形がいちばん悪い。"""
    src, _dest = roots
    _seed(src)

    with pytest.raises(primary_backup.PrimaryBackupError, match="外のpath"):
        await primary_backup.run_backup(exclude_rels=[tmp_path / "どこか" / "別のfile"])


async def test_empty_exclusion_entries_are_dropped(roots):
    """空の項目でroot自身を外さない。

    残ると一次保存先が丸ごと控えから落ち、しかも結果は「写した件数0」で、差分が無かった
    正常な回と見分けが付かない。"""
    src, dest = roots
    _seed(src)

    result = await primary_backup.run_backup(exclude_rels=["", "  ", "/", "."])

    assert result["copied"] == 4
    assert result["excluded"] == 0
    assert len(_rels(_tree(dest))) == 4


async def test_a_stale_exclusion_is_not_counted(roots):
    """既に消えた録画を指したまま呼ばれるのは正常。件数には混ぜない。"""
    src, _dest = roots
    _seed(src)

    result = await primary_backup.run_backup(
        exclude_rels=["bob/ts/09999_bob_20200101_000000"])

    assert result["copied"] == 4
    assert result["excluded"] == 0


async def test_pools_are_not_affected_by_exclusions(roots):
    """poolは録画1本に属さないので除外の対象外。"""
    src, dest = roots
    _seed(src)
    _seed_pools(src)

    result = await primary_backup.run_backup(exclude_rels=[SESSION])

    pools = {entry["name"]: entry for entry in result["pools"]}
    assert pools[layout.AVATAR_POOL_DIRNAME]["archived"] is True
    assert pools[layout.AVATAR_POOL_DIRNAME]["files"] == 5


def test_excluded_directory_subtree_is_not_walked(tmp_path):
    """除外したdirectoryの下は歩きもしない。

    録画中のsession dirは束ね前で実測11,285 entriesあり、一致してから捨てるのでは
    除外の費用がそのまま走査の費用になる。"""
    _write(tmp_path / "keep.ts", "k")
    for i in range(50):
        _write(tmp_path / "busy" / f"seg{i}.ts", "x")

    seen = {rel for rel, _s, _m in
            primary_backup._iter_tree(tmp_path, (), frozenset({"busy"}))}

    assert seen == {"keep.ts"}


# ---------------- backup先が外れたとき ----------------

async def test_refuses_to_start_when_the_destination_is_gone(roots, monkeypatch):
    """外付けHDDがbusから落ちた状態では始めない。"""
    src, dest = roots
    _seed(src)
    monkeypatch.setenv("TICTOK_RECORD_BACKUP_DIR", str(dest / "detached"))

    with pytest.raises(primary_backup.PrimaryBackupError, match="見つかりません"):
        await primary_backup.run_backup()

    # 親folderを勝手に作らない。作ると、driveが外れたまま systemのdriveへ写し始める。
    assert not (dest / "detached").exists()


async def test_refuses_to_start_when_the_destination_is_read_only(roots, monkeypatch):
    """実在しても書けないなら始めない(I/O errorでread-onlyへ落ちたdrive)。

    実在の確認だけを通して4分かけてarchiveを作ってから気付くのでは、確かめた意味が無い。"""
    src, _dest = roots
    _seed(src)
    real_write = Path.write_bytes

    def _blocked(self, data):
        if self.name == primary_backup.WRITE_PROBE_NAME:
            raise OSError(13, "書き込みが拒否されました")
        return real_write(self, data)

    monkeypatch.setattr(Path, "write_bytes", _blocked)

    with pytest.raises(primary_backup.PrimaryBackupError, match="書き込めません"):
        await primary_backup.run_backup()


async def test_write_probe_leaves_nothing_behind(roots):
    src, dest = roots
    _seed(src)

    await primary_backup.run_backup()

    root = dest / primary_backup.PRIMARY_BACKUP_DIRNAME
    assert not (root / primary_backup.WRITE_PROBE_NAME).exists()


async def test_stops_after_consecutive_failures_and_reports_it_as_stopped(roots, monkeypatch):
    """途中でbackup先が居なくなったら中断する。失敗ではなく「途中で止めた」として名乗る。"""
    src, dest = roots
    _seed(src)
    for i in range(60):
        _write(src / "alice" / "ts" / "00001_alice_20260101_120000" / f"seg{i:03d}.ts",
               f"seg{i}")
    monkeypatch.setattr(primary_backup, "MAX_CONSECUTIVE_FAILURES", 5)

    def _gone(src_path, dst_path):
        raise OSError(6, "デバイスが接続されていません")

    monkeypatch.setattr(primary_backup, "_copy_one", _gone)

    result = await primary_backup.run_backup()

    assert result["stopped"]
    assert "外れた可能性" in result["stopped"]
    # 全部を舐めない。舐めると運用logに原因を指さない「失敗63件」だけが残る。
    assert result["failed"] == 5
    assert result["remaining"] > 0
    # 止めた回は控えを1件も減らさない。
    assert result["deleted"] == 0
    assert result["marked_deleted"] == 0


async def test_a_single_locked_file_does_not_stop_the_run(roots, monkeypatch):
    """散発的な失敗では止まらない。成功でcounterが0へ戻ること。

    録画中のfileが掴まれているのは正常で、そこで止めると1本のlockのためにbackupが
    永久に取れないという別の壊れ方になる。"""
    src, _dest = roots
    _seed(src)
    for i in range(60):
        _write(src / "alice" / "ts" / "00001_alice_20260101_120000" / f"seg{i:03d}.ts",
               f"seg{i}")
    monkeypatch.setattr(primary_backup, "MAX_CONSECUTIVE_FAILURES", 5)

    real_copy = primary_backup._copy_one
    seen: list = []

    def _flaky(src_path, dst_path):
        seen.append(src_path)
        # 4本に1本は掴まれている。連続はしないので中断の条件には届かない。
        if len(seen) % 4 == 0:
            raise OSError(32, "他のprocessが使用中です")
        return real_copy(src_path, dst_path)

    monkeypatch.setattr(primary_backup, "_copy_one", _flaky)

    result = await primary_backup.run_backup()

    assert result["stopped"] == ""
    assert result["failed"] > primary_backup.MAX_CONSECUTIVE_FAILURES
    assert result["copied"] > 0


async def test_a_stopped_run_continues_from_where_it_left_off(roots, monkeypatch):
    """中断した回の残りは、次回が続きから進める。"""
    src, dest = roots
    _seed(src)
    monkeypatch.setattr(primary_backup, "MAX_CONSECUTIVE_FAILURES", 2)
    # monkeypatch.undo() は使わない。env_guard が張った TICTOK_RECORD_DIR まで戻り、
    # 2回目の実行が**本番の**録画folderを掴む。driveが戻ったことは旗で表す。
    detached = {"now": True}
    real_copy = primary_backup._copy_one

    def _maybe_gone(src_path, dst_path):
        if detached["now"]:
            raise OSError(6, "デバイスが接続されていません")
        return real_copy(src_path, dst_path)

    monkeypatch.setattr(primary_backup, "_copy_one", _maybe_gone)
    stopped = await primary_backup.run_backup()
    assert stopped["stopped"]
    assert stopped["copied"] == 0

    detached["now"] = False
    result = await primary_backup.run_backup()

    assert result["stopped"] == ""
    assert result["copied"] == 4
    assert not list(_tree(dest).rglob("*" + primary_backup.PARTIAL_SUFFIX))


async def test_a_stopped_run_does_not_touch_the_pool_ledger(roots, monkeypatch):
    """止めた回はarchiveを作らず、作った事にもしない。

    作った事にすると、次回は指紋が一致して作り直しを見送り、控えに載らないpoolが残る。"""
    src, dest = roots
    _seed(src)
    _seed_pools(src)
    monkeypatch.setattr(primary_backup, "MAX_CONSECUTIVE_FAILURES", 2)

    def _gone(src_path, dst_path):
        raise OSError(6, "デバイスが接続されていません")

    monkeypatch.setattr(primary_backup, "_copy_one", _gone)
    result = await primary_backup.run_backup()

    assert result["stopped"]
    pools = {entry["name"]: entry for entry in result["pools"]}
    assert pools[layout.AVATAR_POOL_DIRNAME]["archived"] is False
    root = dest / primary_backup.PRIMARY_BACKUP_DIRNAME
    assert primary_backup._load_ledger(root)["pools"] == {}
    assert not list((root / primary_backup.POOL_ARCHIVE_DIRNAME).glob("*.zip"))


async def test_last_run_reports_a_stopped_run(roots, monkeypatch):
    src, _dest = roots
    _seed(src)
    monkeypatch.setattr(primary_backup, "MAX_CONSECUTIVE_FAILURES", 2)
    monkeypatch.setattr(primary_backup, "_copy_one",
                        lambda s, d: (_ for _ in ()).throw(OSError(6, "外れました")))

    await primary_backup.run_backup()

    assert primary_backup.last_run()["stopped"]


# ---------------- (f) poolはarchiveへ畳む ----------------

def _seed_pools(src: Path, count: int = 5) -> None:
    # 実物のavatarは1枚数KBある。極端に小さいfileで埋めると、1枚足しただけで
    # bytesの変化率(POOL_REBUILD_BYTES_RATIO)が閾値を越え、件数の判定を見ずに済んでしまう。
    for i in range(count):
        _write(src / layout.AVATAR_POOL_DIRNAME / "by-id" / f"{i:04d}.img",
               f"img{i}" + "0" * 4096)
    _write(src / layout.EMOTE_POOL_DIRNAME / "e0.png", "emote")
    _write(src / layout.GIFT_ICON_POOL_DIRNAME / "g0.png", "gift")


async def test_pools_are_archived_instead_of_copied_file_by_file(roots):
    src, dest = roots
    _seed(src)
    _seed_pools(src)

    result = await primary_backup.run_backup()

    tree = _tree(dest)
    # poolのfileは木の側には1件も現れない(73万fileを1本ずつ写さないための分岐)。
    assert not any(rel.startswith(layout.AVATAR_POOL_DIRNAME) for rel in _rels(tree))
    pools = {entry["name"]: entry for entry in result["pools"]}
    assert pools[layout.AVATAR_POOL_DIRNAME]["archived"] is True
    assert pools[layout.AVATAR_POOL_DIRNAME]["files"] == 5

    archive = (dest / primary_backup.PRIMARY_BACKUP_DIRNAME
               / primary_backup.POOL_ARCHIVE_DIRNAME
               / pools[layout.AVATAR_POOL_DIRNAME]["archive"])
    with zipfile.ZipFile(str(archive)) as zf:
        names = set(zf.namelist())
    assert f"{layout.AVATAR_POOL_DIRNAME}/by-id/0000.img" in names
    assert len(names) == 5


async def test_pool_archive_is_not_rebuilt_while_the_difference_is_small(roots):
    src, _dest = roots
    _seed(src)
    _seed_pools(src)
    await primary_backup.run_backup()

    _write(src / layout.AVATAR_POOL_DIRNAME / "by-id" / "9999.img", "img9999")
    result = await primary_backup.run_backup()

    pools = {entry["name"]: entry for entry in result["pools"]}
    assert pools[layout.AVATAR_POOL_DIRNAME]["archived"] is False
    assert pools[layout.AVATAR_POOL_DIRNAME]["reason"] == ""


async def test_pool_archive_is_rebuilt_once_enough_files_appeared(roots, monkeypatch):
    src, dest = roots
    _seed(src)
    _seed_pools(src)
    await primary_backup.run_backup()
    monkeypatch.setattr(primary_backup, "POOL_REBUILD_FILE_DELTA", 3)

    for i in range(100, 104):
        _write(src / layout.AVATAR_POOL_DIRNAME / "by-id" / f"{i:04d}.img", f"img{i}")
    result = await primary_backup.run_backup()

    pools = {entry["name"]: entry for entry in result["pools"]}
    assert pools[layout.AVATAR_POOL_DIRNAME]["archived"] is True
    assert "件数差" in pools[layout.AVATAR_POOL_DIRNAME]["reason"]
    archives = sorted((dest / primary_backup.PRIMARY_BACKUP_DIRNAME
                       / primary_backup.POOL_ARCHIVE_DIRNAME).glob("avatars-*.zip"))
    # 1つ前の世代は残す(作り直した物が壊れていた場合に戻れるように)。
    assert 1 <= len(archives) <= primary_backup.POOL_KEEP_GENERATIONS


async def test_unchanged_pool_is_decided_without_walking_it(roots, monkeypatch):
    """安い指紋(directoryのmtime)だけで「作り直し不要」に至る。

    poolを毎回全走査すると、判定のためだけにavatarsで1.73秒(実測)を払う。何も足されて
    いない回は5回のstat(実測115マイクロ秒)で済ませる。"""
    src, _dest = roots
    _seed(src)
    _seed_pools(src)
    await primary_backup.run_backup()

    walked: list = []
    real_walk = primary_backup._walk_pool
    monkeypatch.setattr(primary_backup, "_walk_pool",
                        lambda pool: walked.append(pool) or real_walk(pool))

    result = await primary_backup.run_backup()

    assert walked == []
    pools = {entry["name"]: entry for entry in result["pools"]}
    assert pools[layout.AVATAR_POOL_DIRNAME]["scanned"] is False
    assert pools[layout.AVATAR_POOL_DIRNAME]["archived"] is False


async def test_added_pool_file_makes_the_cheap_fingerprint_miss(roots, monkeypatch):
    """fileが1本増えればdirectoryのmtimeが動き、2段目の全走査へ進む。"""
    src, _dest = roots
    _seed(src)
    _seed_pools(src)
    await primary_backup.run_backup()

    walked: list = []
    real_walk = primary_backup._walk_pool
    monkeypatch.setattr(primary_backup, "_walk_pool",
                        lambda pool: walked.append(pool) or real_walk(pool))
    _write(src / layout.AVATAR_POOL_DIRNAME / "by-id" / "7777.img", "img7777")

    result = await primary_backup.run_backup()

    assert (src / layout.AVATAR_POOL_DIRNAME) in walked
    pools = {entry["name"]: entry for entry in result["pools"]}
    assert pools[layout.AVATAR_POOL_DIRNAME]["scanned"] is True
    # 走ったが閾値には届かないので作り直さない。
    assert pools[layout.AVATAR_POOL_DIRNAME]["archived"] is False


async def test_walked_pool_is_not_walked_again_while_unchanged(roots, monkeypatch):
    """閾値に届かず作り直さなかった回も、見た姿は台帳へ残す(次回の走査を省くため)。

    件数の基準は動かさない ―― 動かすと少しずつの増加が毎回「前回比ゼロ」になり、
    閾値へ永久に届かなくなる。"""
    src, dest = roots
    _seed(src)
    _seed_pools(src)
    await primary_backup.run_backup()
    _write(src / layout.AVATAR_POOL_DIRNAME / "by-id" / "7777.img", "img7777")
    await primary_backup.run_backup()

    root = dest / primary_backup.PRIMARY_BACKUP_DIRNAME
    record = primary_backup._load_ledger(root)["pools"][layout.AVATAR_POOL_DIRNAME]
    assert record["files"] == 5           # 基準はarchiveを作った時のまま

    walked: list = []
    real_walk = primary_backup._walk_pool
    monkeypatch.setattr(primary_backup, "_walk_pool",
                        lambda pool: walked.append(pool) or real_walk(pool))
    await primary_backup.run_backup()

    assert walked == []


async def test_missing_archive_forces_a_rebuild_even_when_nothing_changed(roots):
    """archiveの実体が消えていれば、指紋を見るまでもなく作り直す。"""
    src, dest = roots
    _seed(src)
    _seed_pools(src)
    await primary_backup.run_backup()
    pool_dir = (dest / primary_backup.PRIMARY_BACKUP_DIRNAME
                / primary_backup.POOL_ARCHIVE_DIRNAME)
    for path in pool_dir.glob("avatars-*.zip"):
        path.unlink()

    result = await primary_backup.run_backup()

    pools = {entry["name"]: entry for entry in result["pools"]}
    assert pools[layout.AVATAR_POOL_DIRNAME]["archived"] is True
    assert pools[layout.AVATAR_POOL_DIRNAME]["reason"] == "初回"


# ---------------- archiveの健全性 ----------------

async def test_unhealthy_new_archive_is_discarded_and_prunes_nothing(roots, monkeypatch):
    """壊れたarchiveで健全な世代を置き換えない。

    置き換えてしまうと、backupを取る操作そのものが「控えがあるのに戻せない」状態を作る。"""
    src, dest = roots
    _seed(src)
    _seed_pools(src)
    await primary_backup.run_backup()
    pool_dir = (dest / primary_backup.PRIMARY_BACKUP_DIRNAME
                / primary_backup.POOL_ARCHIVE_DIRNAME)
    healthy = sorted(pool_dir.glob("avatars-*.zip"))
    assert len(healthy) == 1

    # 書き終えたはずのarchiveが実は途中で切れている(diskが埋まった回に起きる形)。
    real_build = primary_backup._build_pool_archive

    def _truncating_build(src_pool, dest_dir, name, now):
        path, written = real_build(src_pool, dest_dir, name, now)
        if name == layout.AVATAR_POOL_DIRNAME:
            path.write_bytes(path.read_bytes()[: 64])
        return path, written

    monkeypatch.setattr(primary_backup, "_build_pool_archive", _truncating_build)
    monkeypatch.setattr(primary_backup, "POOL_REBUILD_FILE_DELTA", 2)
    monkeypatch.setattr(primary_backup, "POOL_KEEP_GENERATIONS", 1)
    for i in range(200, 204):
        _write(src / layout.AVATAR_POOL_DIRNAME / "by-id" / f"{i:04d}.img", f"img{i}")

    result = await primary_backup.run_backup()

    pools = {entry["name"]: entry for entry in result["pools"]}
    assert pools[layout.AVATAR_POOL_DIRNAME]["archived"] is False
    assert result["failed"] == 1
    # 健全な世代がそのまま残り、壊れた物は残らない。
    assert sorted(pool_dir.glob("avatars-*.zip")) == healthy


def test_pool_archives_order_puts_the_same_second_sequel_first(tmp_path):
    """同じ秒に2本作ったときの新旧。名前の文字列順では逆になる('-' < '.')ので、
    文字列順に頼ると刈り取りが**新しい世代**を消す。"""
    for stamp in ("avatars-20260101-000000.zip", "avatars-20260101-000000-2.zip",
                  "avatars-20260101-000001.zip"):
        (tmp_path / stamp).write_bytes(b"")

    order = [p.name for p in primary_backup._pool_archives(tmp_path, "avatars")]

    assert order == ["avatars-20260101-000001.zip", "avatars-20260101-000000-2.zip",
                     "avatars-20260101-000000.zip"]


def test_pool_archives_ignores_names_outside_the_convention(tmp_path):
    """規約外の名前は世代として数えない(刈り取りの対象にしない)。"""
    (tmp_path / "avatars-20260101-000000.zip").write_bytes(b"")
    (tmp_path / "avatars-手で置いた控え.zip").write_bytes(b"")

    order = [p.name for p in primary_backup._pool_archives(tmp_path, "avatars")]

    assert order == ["avatars-20260101-000000.zip"]


def test_next_archive_target_never_reuses_a_freed_number(tmp_path):
    """空いた若い番号を埋めない。埋めると最新の内容が最古の名前を名乗る。"""
    now = 1767225600.0
    first = primary_backup._next_archive_target(tmp_path, "avatars", now)
    first.write_bytes(b"")
    second = primary_backup._next_archive_target(tmp_path, "avatars", now)
    second.write_bytes(b"")
    assert second.name.endswith("-2.zip")

    first.unlink()          # 刈り取りが古い方を消し、連番なしの名前が空く
    third = primary_backup._next_archive_target(tmp_path, "avatars", now)

    assert third != first
    assert third.name.endswith("-3.zip")


def test_same_second_generations_keep_the_newest_content(tmp_path):
    """同じ秒に世代を重ねても、最新の中身が残り最新として並ぶ。

    「空いている名前を拾う」実装だと、刈り取りが空けた若い番号を次が埋め、その最新の
    archiveを直後の刈り取りが最古と見なして消す ―― 出来たばかりの控えが、作った操作
    自身に消される。健全性を確かめる意味もそこで消える(確かめた物が残らない)。"""
    pool = tmp_path / "avatars"
    dest = tmp_path / "pools"
    now = 1767225600.0
    newest = None
    for i in range(5):
        _write(pool / f"{i:02d}.img", f"内容{i}")
        newest, _written = primary_backup._build_pool_archive(pool, dest, "avatars", now)
        primary_backup._prune_pool_archives(dest, "avatars")

    kept = primary_backup._pool_archives(dest, "avatars")

    assert newest in kept
    assert kept[0] == newest
    assert len(kept) == primary_backup.POOL_KEEP_GENERATIONS
    with zipfile.ZipFile(str(newest)) as zf:
        assert len(zf.namelist()) == 5


def test_verify_pool_archive_rejects_a_short_count(tmp_path):
    archive = tmp_path / "avatars-20260101-000000.zip"
    with zipfile.ZipFile(str(archive), "w") as zf:
        zf.writestr("avatars/a.img", "a")
    assert primary_backup._verify_pool_archive(archive, 1) == ""
    assert "件数が合いません" in primary_backup._verify_pool_archive(archive, 2)


def test_verify_pool_archive_rejects_an_unopenable_file(tmp_path):
    broken = tmp_path / "avatars-20260101-000000.zip"
    broken.write_bytes(b"not a zip at all")
    assert "開けません" in primary_backup._verify_pool_archive(broken, 1)


async def test_old_pool_generations_are_pruned(roots, monkeypatch):
    src, dest = roots
    _seed(src)
    _seed_pools(src)
    pool_dir = (dest / primary_backup.PRIMARY_BACKUP_DIRNAME
                / primary_backup.POOL_ARCHIVE_DIRNAME)
    pool_dir.mkdir(parents=True, exist_ok=True)
    for stamp in ("20200101-000000", "20200102-000000", "20200103-000000"):
        (pool_dir / f"avatars-{stamp}.zip").write_bytes(b"")

    await primary_backup.run_backup()

    assert len(list(pool_dir.glob("avatars-*.zip"))) == \
        primary_backup.POOL_KEEP_GENERATIONS


# ---------------- 台帳 ----------------

async def test_last_run_returns_the_previous_summary(roots):
    src, _dest = roots
    _seed(src)
    assert primary_backup.last_run() is None

    result = await primary_backup.run_backup()

    stored = primary_backup.last_run()
    assert stored["copied"] == result["copied"]
    assert stored["dest"] == result["dest"]


async def test_unreadable_ledger_does_not_stop_the_backup(roots):
    src, dest = roots
    _seed(src)
    root = dest / primary_backup.PRIMARY_BACKUP_DIRNAME
    root.mkdir(parents=True, exist_ok=True)
    (root / primary_backup.LEDGER_NAME).write_text("{ broken", encoding="utf-8")

    result = await primary_backup.run_backup()

    assert result["copied"] == 4


# ---------------- (h) 写す先の同一性 ----------------
#
# 外付けdriveのletterは入れ替わる。「K:\Backup」に別のdriveが見えている状態で走ると、
# 台帳が無いので初回として31GBを丸ごと写し始め、本物の控えは古いまま置き去りになる。
# driveが外れた状態は _require_destination_available が捕まえるが、別のdriveが同じ場所に
# 居る状態は親folderが在るので素通りする。それを識別子の突き合わせで止める。

async def test_first_run_adopts_a_root_id_and_returns_it(roots):
    src, dest = roots
    _seed(src)

    result = await primary_backup.run_backup(expected_root_id=None)

    marker = primary_backup.backup_root() / primary_backup.ROOT_ID_NAME
    assert marker.is_file()
    assert result["root_id"] == marker.read_text(encoding="utf-8").strip()
    assert result["root_id_adopted"] is True
    assert len(result["root_id"]) == 32


async def test_matching_root_id_passes_and_is_not_readopted(roots):
    src, dest = roots
    _seed(src)
    first = await primary_backup.run_backup(expected_root_id=None)

    result = await primary_backup.run_backup(expected_root_id=first["root_id"])

    assert result["root_id"] == first["root_id"]
    assert result["root_id_adopted"] is False


async def test_a_different_drive_at_the_same_path_is_refused_before_writing(roots):
    """識別子の無いbackup先(=letterが入れ替わって別のdriveが見えている)へは1byteも写さない。"""
    src, dest = roots
    _seed(src)

    with pytest.raises(primary_backup.PrimaryBackupError, match="識別子"):
        await primary_backup.run_backup(expected_root_id="0" * 32)

    assert not _tree(dest).exists() or _rels(_tree(dest)) == set()


async def test_a_mismatched_root_id_is_refused(roots):
    src, dest = roots
    _seed(src)
    first = await primary_backup.run_backup(expected_root_id=None)
    marker = primary_backup.backup_root() / primary_backup.ROOT_ID_NAME
    marker.write_text("f" * 32 + "\n", encoding="utf-8")
    _write(src / "alice" / "mp4" / "00002_alice_20260102_120000.mp4", "new")

    with pytest.raises(primary_backup.PrimaryBackupError, match="一致しません"):
        await primary_backup.run_backup(expected_root_id=first["root_id"])

    assert "alice/mp4/00002_alice_20260102_120000.mp4" not in _rels(_tree(dest))


async def test_restoring_an_old_db_adopts_the_existing_root_id(roots):
    """DBを古いsnapshotへ戻すと控えが無くなる(None)。その時は控え側が正で、backup先に
    在る識別子をそのまま採用する ―― 新しい識別子を作ってしまうと、次の周期で「一致しない」
    として本物の控えを拒む。"""
    src, dest = roots
    _seed(src)
    first = await primary_backup.run_backup(expected_root_id=None)

    result = await primary_backup.run_backup(expected_root_id=None)

    assert result["root_id"] == first["root_id"]
    assert result["root_id_adopted"] is True
