"""保持する配信者以外の録画を、DBとdiskからまとめて削除する。

監視を外した配信者の録画は、誰も消さないまま残り続ける。sessionを消しても録画行は
残る設計(``files._delete_session_recording``: 素材が在る録画は行を残す)であり、
retentionは配信者を区別しないため、「もう追っていない配信者」という単位で片付ける
経路がどこにも無い。このscriptがその単位を受け持つ。

削除するもの:

  disk  <root>/<配信者>/ 一式(ts/ の素材、mp4/ の元mp4・焼き込み・Up出力、
        _clips/ の切り出し成果物、_screenshots/ のスクショ)
        <root>/.sidecars/ の当該録画ぶん(波形・sprite・timing map)
        <root>/_clips/<配信者>/(配信者folderの下へ移す前の実体)と
        <root>/_backup/ の当該録画ぶん
  DB    recordings 行(FK cascadeで transcripts / search_hits / bookmarks /
        media_job_queue / transcribe_queue が連鎖削除される)
        sessions 行(cascadeで events / buckets / viewer_samples / markers /
        battles / contributor_samples / collab_windows / envelopes /
        follower_samples / analytics_session_cache / ai_analysis も落ちる)
        monitored_targets 行
  意味検索  semantic_index.db の passages / indexed 行

search_fts は external content FTS5 なので、search_hits を消しただけでは索引が残る
(``Storage.replace_search_hits`` と同じ理由)。cascadeはtriggerを通らないため、
このscriptは削除の**前**に 'delete' commandで索引を抜く。既存のUIからの録画削除
(``DELETE /api/recordings/{id}``)はこれを行っておらず、索引に迷子の行を残す。

残すもの:

  users        視聴者の名寄せ表。保持する配信者のsessionからも参照される
  ops_events   運用log。何をいつ消したかを後から辿るための記録そのもの
  avatars/emotes/gift_icons  録画横断のpool(``layout.pool_root``)。共有資産で、
               配信者ごとに切り分けられない

既定はdry-run。``--apply`` のときだけ実際に消す。``--apply`` はserverの停止を要求する
(instance lockで確認し、動いていれば中断する)。dry-runは読むだけなので稼働中でも走る。

実体を手で消す場合は ``--db-only`` を使う。``--list-files`` で削除対象のpathを
書き出せるので、それを入力にすればDBとdiskで対象がずれない。

Usage (TicTok directory から venv で実行):
    python scripts/purge_streamers.py --keep streamer_c,streamer_a,streamer_b
    python scripts/purge_streamers.py --keep ... --list-files purge_targets.txt
    python scripts/purge_streamers.py --keep ... --apply --db-only --vacuum
    python scripts/purge_streamers.py --keep ... --apply --vacuum
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tictok.core import layout
from tictok.core.config import (
    final_record_dir_from_db,
    get_db_path,
    record_dir_from_db,
)
from tictok.core.process_lock import ProcessLock, ProcessLockError

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("purge_streamers")

SEMANTIC_DB_NAME = "semantic_index.db"
BACKUP_DIRNAME = "_backup"
# 配信者名では切り分けられない共有dir。root直下の走査で配信者folderと取り違えない。
SHARED_DIRS = layout.NON_STREAMER_DIRS


def _record_roots() -> list[Path]:
    """走査対象のrecord root。serverと同じ解決(DB設定 > 環境変数 > 既定)を辿る。"""
    db_path = get_db_path()
    work = Path(record_dir_from_db(db_path)).resolve()
    final = Path(final_record_dir_from_db(db_path)).resolve()
    return [work] if work == final else [work, final]


def _dir_bytes(path: Path) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    return total


def _fmt_bytes(size: int) -> str:
    return f"{size / 1024 ** 3:8.2f} GB"


def _plan_files(roots: list[Path], keep: set[str]) -> tuple[list[tuple[Path, str, int]], set[str]]:
    """消すpathの一覧を (path, 分類, bytes) で返す。第2返り値はdiskに居た配信者名。

    DBは参照しない。行を先に消しても、あるいは行がもう無い配信者folderが残っていても、
    同じ結果になるようにするため — 録画行とdiskの実体は既にずれている(sessionを消した
    録画がその状態)。"""
    targets: list[tuple[Path, str, int]] = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name in SHARED_DIRS:
                continue
            seen.add(entry.name)
            if entry.name in keep:
                continue
            targets.append((entry, "録画folder", _dir_bytes(entry)))
        # 成果物は配信者folderの下(``<配信者>/_clips/``・``<配信者>/_screenshots/``)へ出るので、
        # 上の「録画folder」で一緒に消える。ここで見るのは root直下に残る旧い置き場だけ
        # (``scripts/migrate_clips_layout.py`` で移す前の実体)。
        for shared in layout.ARTIFACT_DIRNAMES:
            shared_dir = root / shared
            if not shared_dir.is_dir():
                continue
            for entry in sorted(shared_dir.iterdir()):
                if not entry.is_dir():
                    continue
                seen.add(entry.name)
                if entry.name in keep:
                    continue
                targets.append((entry, "切り出し", _dir_bytes(entry)))
        for shared in (".sidecars", BACKUP_DIRNAME):
            shared_dir = root / shared
            if not shared_dir.is_dir():
                continue
            for dirpath, _dirnames, filenames in os.walk(shared_dir):
                for name in filenames:
                    _stem, owner = layout.artifact_owner(name)
                    if owner is None:
                        # 命名規則外は誰のものか判定できない。消さずに残す。
                        continue
                    seen.add(owner)
                    if owner in keep:
                        continue
                    path = Path(dirpath) / name
                    try:
                        size = path.stat().st_size
                    except OSError:
                        size = 0
                    label = "退避mp4" if shared == BACKUP_DIRNAME else "sidecar"
                    targets.append((path, label, size))
    return targets, seen


def _plan_db(conn: sqlite3.Connection, keep: list[str]) -> dict:
    holes = ",".join("?" * len(keep))
    count = lambda sql: conn.execute(sql, keep).fetchone()[0]  # noqa: E731
    drop_rec = f"(SELECT id FROM recordings WHERE unique_id NOT IN ({holes}))"
    drop_ses = f"(SELECT id FROM sessions WHERE unique_id NOT IN ({holes}))"
    return {
        "recordings": count(f"SELECT COUNT(*) FROM recordings WHERE unique_id NOT IN ({holes})"),
        "sessions": count(f"SELECT COUNT(*) FROM sessions WHERE unique_id NOT IN ({holes})"),
        "monitored": count(
            f"SELECT COUNT(*) FROM monitored_targets WHERE unique_id NOT IN ({holes})"),
        "transcripts": count(
            f"SELECT COUNT(*) FROM transcripts WHERE recording_id IN {drop_rec}"),
        "search_hits": count(
            f"SELECT COUNT(*) FROM search_hits WHERE recording_id IN {drop_rec}"),
        "bookmarks": count(f"SELECT COUNT(*) FROM bookmarks WHERE recording_id IN {drop_rec}"),
        "media_jobs": count(
            f"SELECT COUNT(*) FROM media_job_queue WHERE recording_id IN {drop_rec}"),
        "transcribe_queue": count(
            f"SELECT COUNT(*) FROM transcribe_queue WHERE recording_id IN {drop_rec}"),
        "events": count(f"SELECT COUNT(*) FROM events WHERE session_id IN {drop_ses}"),
        "buckets": count(f"SELECT COUNT(*) FROM buckets WHERE session_id IN {drop_ses}"),
        "viewer_samples": count(
            f"SELECT COUNT(*) FROM viewer_samples WHERE session_id IN {drop_ses}"),
    }


def _apply_db(conn: sqlite3.Connection, keep: list[str]) -> None:
    """DB側を消す。FTSの索引を抜いてから本体をDELETEする(順序が逆だと索引が孤児になる)。"""
    holes = ",".join("?" * len(keep))
    conn.execute("PRAGMA foreign_keys=ON")
    drop_rec = f"(SELECT id FROM recordings WHERE unique_id NOT IN ({holes}))"
    conn.execute(
        "INSERT INTO search_fts(search_fts, rowid, body_norm)"
        f" SELECT 'delete', id, body_norm FROM search_hits WHERE recording_id IN {drop_rec}",
        keep,
    )
    # sessionを先に消す。recordings.session_id は ON DELETE SET NULL なので、録画行を
    # 先に消しても孤児sessionが残るだけで、順序による取りこぼしは無い。
    conn.execute(f"DELETE FROM sessions WHERE unique_id NOT IN ({holes})", keep)
    conn.execute(f"DELETE FROM recordings WHERE unique_id NOT IN ({holes})", keep)
    conn.execute(f"DELETE FROM monitored_targets WHERE unique_id NOT IN ({holes})", keep)
    conn.commit()


def _plan_semantic(path: Path, keep: list[str]) -> int:
    if not path.is_file():
        return 0
    holes = ",".join("?" * len(keep))
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute(
            f"SELECT COUNT(*) FROM passages WHERE unique_id NOT IN ({holes})", keep
        ).fetchone()[0]
    finally:
        conn.close()


def _apply_semantic(path: Path, keep: list[str]) -> None:
    """意味検索indexから該当passageを抜く。

    vector本体(``semantic_vectors.bin``)は追記専用でrownoが行位置そのものなので、
    削っても詰められない。検索側は「metadataに存在しないrownoは結果から落ちる」前提で
    書かれている(``semantic.search`` の穴の扱い)ので、passage行だけを消せばよい。"""
    if not path.is_file():
        return
    holes = ",".join("?" * len(keep))
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            f"DELETE FROM indexed WHERE recording_id IN"
            f" (SELECT recording_id FROM passages WHERE unique_id NOT IN ({holes}))", keep)
        conn.execute(f"DELETE FROM passages WHERE unique_id NOT IN ({holes})", keep)
        conn.commit()
    finally:
        conn.close()


def _backup_db(db_path: Path) -> Path:
    """消す前のDBを丸ごと複製する。sqliteのbackup APIを使うのは、WALの内容まで
    含めた一貫したcopyを取るため(fileのcopyではWAL側の未反映分を取りこぼす)。"""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = db_path.with_name(f"{db_path.name}.bak-purge-{stamp}")
    src = sqlite3.connect(str(db_path))
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", required=True,
                        help="残す配信者のunique_id(コンマ区切り)。これ以外は全て消す")
    parser.add_argument("--apply", action="store_true", help="実際に削除する(既定はdry-run)")
    parser.add_argument("--db-only", action="store_true",
                        help="diskには触らずDBと意味検索indexだけを消す(実体は手で消す場合)")
    parser.add_argument("--list-files", metavar="PATH",
                        help="削除対象のpath一覧をfileへ書き出す(手で消すための入力)")
    parser.add_argument("--vacuum", action="store_true",
                        help="削除後にVACUUMしてDBのfile sizeを縮める")
    parser.add_argument("--no-backup", action="store_true",
                        help="削除前のDB複製を作らない(非推奨)")
    args = parser.parse_args()

    keep = [name.strip().lstrip("@") for name in args.keep.split(",") if name.strip()]
    if not keep:
        logger.error("--keep が空です。全消しは受け付けません。")
        return 2

    db_path = Path(get_db_path()).resolve()
    # serverが動いていると、録画中のfileを消しに行くうえ、DBの書き込みとも競合する。
    # 縛るのは``--apply``だけにする — 何をどれだけ消すことになるかは、収集を止めずに
    # 確かめられる必要がある(止めれば配信を取り逃す)。dry-runは全て読むだけである。
    lock = ProcessLock(str(db_path) + ".lock") if args.apply else None
    if lock is not None:
        try:
            lock.acquire()
        except ProcessLockError as exc:
            logger.error("serverが動いています。先に停止してください: %s", exc)
            return 2

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            known = {row[0] for row in conn.execute("SELECT DISTINCT unique_id FROM recordings")}
            # 綴りを1文字間違えると、残すはずの配信者が丸ごと削除対象になる。DBに
            # 録画が1本も無い名前を保持指定として受け取らない。
            unknown = [name for name in keep if name not in known]
            if unknown:
                logger.error("録画が1本も無い配信者を --keep に指定しています: %s",
                             ", ".join(unknown))
                logger.error("綴りを確認してください。既知の配信者: %s",
                             ", ".join(sorted(known)))
                return 2
            db_plan = _plan_db(conn, keep)
            drop_names = sorted(name for name in known if name not in keep)
        finally:
            conn.close()

        roots = _record_roots()
        missing = [str(root) for root in roots if not root.is_dir()]
        if missing:
            logger.error("record rootが見えません(外付けの接続を確認してください): %s",
                         ", ".join(missing))
            return 2

        file_plan, disk_names = _plan_files(roots, set(keep))
        semantic_path = db_path.parent / SEMANTIC_DB_NAME
        semantic_rows = _plan_semantic(semantic_path, keep)

        logger.info("残す配信者: %s", ", ".join(keep))
        logger.info("消す配信者: %d名 %s", len(drop_names), ", ".join(drop_names))
        orphan = sorted(disk_names - known - set(keep))
        if orphan:
            logger.info("DBに録画行の無いfolderも対象です: %s", ", ".join(orphan))

        logger.info("")
        logger.info("--- disk ---")
        by_label: dict[str, list[int]] = {}
        for _path, label, size in file_plan:
            bucket = by_label.setdefault(label, [0, 0])
            bucket[0] += 1
            bucket[1] += size
        for label, (count, size) in sorted(by_label.items()):
            logger.info("  %-10s %5d件 %s", label, count, _fmt_bytes(size))
        total_bytes = sum(size for _p, _l, size in file_plan)
        logger.info("  %-10s %5d件 %s", "合計", len(file_plan), _fmt_bytes(total_bytes))
        if args.db_only:
            logger.info("  --db-only のためdiskには触りません")

        if args.list_files:
            # 手で消すための入力なので、pathだけを1行1件で出す(件数や見出しは混ぜない)。
            listing = Path(args.list_files)
            listing.write_text(
                "".join(f"{path}\n" for path, _label, _size in file_plan), encoding="utf-8")
            logger.info("  path一覧を書き出しました: %s", listing)

        logger.info("")
        logger.info("--- DB ---")
        logger.info("  recordings       %6d行 (これを消すと以下が連鎖削除)", db_plan["recordings"])
        logger.info("    transcripts    %6d行", db_plan["transcripts"])
        logger.info("    search_hits    %6d行 (FTS索引も同時に抜きます)", db_plan["search_hits"])
        logger.info("    bookmarks      %6d行", db_plan["bookmarks"])
        logger.info("    media_job_queue %5d行", db_plan["media_jobs"])
        logger.info("    transcribe_queue %4d行", db_plan["transcribe_queue"])
        logger.info("  sessions         %6d行 (これを消すと以下が連鎖削除)", db_plan["sessions"])
        logger.info("    events         %6d行", db_plan["events"])
        logger.info("    buckets        %6d行", db_plan["buckets"])
        logger.info("    viewer_samples %6d行", db_plan["viewer_samples"])
        logger.info("  monitored_targets %5d行", db_plan["monitored"])
        logger.info("  意味検索passages  %5d行", semantic_rows)

        if not args.apply:
            logger.info("")
            logger.info("dry-runです。実行するには --apply を付けてください。")
            return 0

        logger.info("")
        if not args.no_backup:
            backup = _backup_db(db_path)
            logger.info("DBを複製しました: %s", backup.name)

        write_conn = sqlite3.connect(str(db_path))
        try:
            _apply_db(write_conn, keep)
            logger.info("DBから削除しました(recordings %d行 / sessions %d行)",
                        db_plan["recordings"], db_plan["sessions"])
            if args.vacuum:
                write_conn.execute("VACUUM")
                logger.info("VACUUMしました")
        finally:
            write_conn.close()

        _apply_semantic(semantic_path, keep)
        if semantic_rows:
            logger.info("意味検索indexから %d passageを抜きました", semantic_rows)

        if args.db_only:
            logger.info("diskは残しました(%s 相当)。手で消してください。",
                        _fmt_bytes(total_bytes).strip())
            return 0

        removed_bytes = 0
        failed = 0
        for path, _label, size in file_plan:
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            except OSError:
                logger.exception("削除に失敗しました: %s", path)
                failed += 1
                continue
            removed_bytes += size
        logger.info("diskから削除しました: %s (失敗 %d件)", _fmt_bytes(removed_bytes), failed)
        return 1 if failed else 0
    finally:
        if lock is not None:
            lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
