"""録画の尺(duration_seconds)を実fileから埋め、潰された ended_at を是正する。

## 直そうとしている壊れ方

録画行の ended_at は「捕捉が終わった時刻」でなければならない。ところが起動時の復旧
(recover_interrupted_recordings)と再mp4化(reprocess)が、Recorder._finalize が打つ
``ended_at = time.time()`` をそのままDBへ書き戻していた。作り直しは中身を作り直すだけで
捕捉が終わった時刻を動かさないのに、**実行した時刻**が ended_at になっていた。

batchで走ると、その回に処理した全行の ended_at が同じ時刻に揃う。started_at は元のまま
なので、古い録画ほど差が開く。新しい順に並ぶ一覧では下へ行くほど尺が伸び、積算している
ように見える(実測: 3時間13分の録画が34時間、3時間13分の別録画が177時間)。

被害は表示に留まらない。ended_at は recording 窓としてeventの絞り込み(焼き込み・検索
index)にも使われるため、潰れた行では次の録画ぶんのcommentまで巻き込む。

## このscriptがすること

1. **尺の測定**: 録画1本ごとに実fileを探し、ffprobeで実尺を測って duration_seconds へ
   入れる。mp4が無くHLS(seg*.ts)が残っていれば playlist の EXTINF 合計を使う。どちらも
   無ければ未測定(NULL)のまま残す。壁時計からの推定はしない — その推定こそが直そうと
   している値である。
2. **ended_at の是正**: 「捕捉の終わりではありえない」ことを証拠で示せて、**かつ正しい値を
   計算できる行だけ**を直す。置き換える値は常に ``started_at + 実尺`` — 捕捉は実時間で
   進むので、録画開始に実尺を足した時刻が捕捉の終わりに当たる。証拠は次の2つ:
     (a) 実尺証拠   — ended_at - started_at が、測った実尺の DURATION_FACTOR 倍 +
                      DURATION_GRACE を超える。捕捉停滞ぶん壁時計が伸びるのは正常
                      (実測で最大1.6倍)なので、正常な伸びと混ざらない幅を取ってある。
     (b) 再処理の指紋 — reprocessed_at と ended_at がほぼ同時刻。再mp4化がended_atへ
                      実行時刻を書いた跡そのもの。録画直後に作り直した正常な行を巻き込ま
                      ないよう、壁時計が実尺を明確に超えている場合にだけ採る。

   **sessions.ended_at を上限に使ってはいけない**。sessionの ended_at は最初の切断で
   埋まり、その後も録画は続く(実測: session#291は21:12に ended だが、その配信の録画は
   01:18まで4本続いていた)。これを上限として丸めると、2.7GBの録画が6秒に化ける。

   実尺を測れない行は、疑わしくても既定では直さない。上限で丸めるのも、壁時計から推定
   するのも「測っていない数字を測ったように見せる」ことになる。件数とidを報告して残す。
   ``--clear-broken-ended-at`` を付けたときだけ、それらの ended_at を NULL(不明)にする。

## 尺の出所(mp4を消した録画でも大抵は残っている)

現行mp4 > HLSのEXTINF合計 > timing map(``.timing.json``の``media_duration``) >
thumb sheet(``.thumbs.json``) > 既存のduration_seconds(文字起こし由来) > ``_backup``の退避mp4。
どれもその録画をffprobeで測って書かれた値で、壁時計からの推定ではない。現行mp4が残る
12本で突き合わせた誤差は timing map が最大3.9秒(2.3%)、thumb sheet はほぼ完全一致。

1つも残っていない録画(fileも派生物も削除済み)は、どんなplayerでも測りようがない。

既定はdry-run。--apply を付けたときだけ書き込む。serverは止めてから実行すること
(録画中・job実行中の行を掴むと、走っている処理の書き込みと競合する)。

Usage (TicTok directory から venv で実行):
    python scripts/repair_recording_durations.py                 # dry-run
    python scripts/repair_recording_durations.py --apply         # 書き込む
    python scripts/repair_recording_durations.py --unique-id pomiiiip
    python scripts/repair_recording_durations.py --durations-only --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
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
from tictok.media import thumbnails
from tictok.record import backups
from tictok.record import recorder as recorder_mod
from tictok.record.recorder import Recorder, ffprobe_available

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("repair_recording_durations")

# 壁時計は捕捉が停滞したぶん実尺より長くなる。実測で最大1.6倍だったので、正常な伸びと
# 混ざらないよう倍率と下駄の両方で離す(短い録画が倍率だけで引っかからないように)。
DURATION_FACTOR = 3.0
DURATION_GRACE = 3600.0
# 再mp4化の指紋で拾うときの最小の食い違い。ここを緩めると、録画直後に作り直した正常な行
# (ended_atもreprocessed_atも本当に近い)まで書き換えてしまう。
FINGERPRINT_FACTOR = 1.2
FINGERPRINT_GRACE = 300.0
# reprocessed_at と ended_at を「同時刻」と見なす幅。再mp4化はended_atを打った後も後段の
# 検証と書き戻しが続くため、実測で20分ほど離れる。
FINGERPRINT_WINDOW = 3600.0

SRC_MP4 = "mp4"
SRC_HLS = "HLS(EXTINF)"
SRC_TIMING = "timing map"
SRC_THUMBS = "thumb sheet"
SRC_STORED = "既存値(文字起こし)"
SRC_BACKUP = "_backup"
SOURCES = (SRC_MP4, SRC_HLS, SRC_TIMING, SRC_THUMBS, SRC_STORED, SRC_BACKUP)

WHY_DURATION = "実尺に対して壁時計が過大"
WHY_REPROCESS = "再mp4化の時刻がended_atに残っている"


def _roots(db_path: str) -> list[Path]:
    """走査対象のrecord root。serverと同じ解決(DB設定 > 環境変数 > 既定)を辿る。"""
    roots: list[Path] = []
    for raw in (record_dir_from_db(db_path), final_record_dir_from_db(db_path)):
        root = Path(raw).resolve()
        if root not in roots:
            roots.append(root)
    return roots


def _open_ro(db_path: str) -> sqlite3.Connection:
    """読み取り専用で開く。通常のconnectはDBが無いと空のfileを作ってしまい、path指定を
    間違えたときに黙って0件で通る。URIはPOSIX区切りでないとWindowsで開けない。"""
    conn = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _has_duration_column(db_path: str) -> bool:
    """duration_seconds列が既にあるか。列を足すのはserver起動時のmigrationの仕事で、
    ここでは作らない(schemaの定義箇所が2つに割れると、片方だけ直る状態が生まれる)。"""
    conn = _open_ro(db_path)
    try:
        return any(row["name"] == "duration_seconds"
                   for row in conn.execute("PRAGMA table_info(recordings)"))
    finally:
        conn.close()


def _rows(db_path: str, unique_id: str | None) -> list[sqlite3.Row]:
    sql = ("SELECT id, unique_id, status, path, filename, started_at, ended_at,"
           " duration_seconds, reprocessed_at FROM recordings")
    params: tuple = ()
    if unique_id:
        sql += " WHERE unique_id = ?"
        params = (unique_id,)
    sql += " ORDER BY id"
    conn = _open_ro(db_path)
    try:
        return list(conn.execute(sql, params))
    finally:
        conn.close()


def _stem(row: sqlite3.Row) -> str:
    return Path(row["filename"] or row["path"] or "").stem


def _mp4_for(row: sqlite3.Row, roots: list[Path]) -> Path | None:
    """この録画の現行mp4。DB行のpathを最優先し、行が古い場合に備えて両rootも探す。"""
    raw = row["path"] or ""
    if raw.lower().endswith(".mp4") and Path(raw).is_file():
        return Path(raw)
    stem = _stem(row)
    if not stem:
        return None
    for root in roots:
        candidate = layout.mp4_path(root, stem)
        if candidate.is_file():
            return candidate
    return None


def _hls_seconds(row: sqlite3.Row, roots: list[Path]) -> float | None:
    """HLS playlistのEXTINF合計 = 素材そのものの実尺。読めなければNone。

    server側の _hls_media_seconds と同じ読み方。mp4が既に無い(容量整理で消した)録画でも、
    .tsを残してあれば尺だけは確定できる。"""
    stem = _stem(row)
    if not stem:
        return None
    for root in roots:
        playlist = layout.session_dir(root, stem) / "index.m3u8"
        try:
            text = playlist.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        total = 0.0
        for line in text.splitlines():
            if not line.startswith("#EXTINF:"):
                continue
            try:
                total += float(line[len("#EXTINF:"):].split(",", 1)[0])
            except ValueError:
                continue
        if total > 0:
            return total
    return None


def _sidecar_seconds(stem: str, roots: list[Path]) -> tuple[float | None, str | None]:
    """mp4が消えていても残っている派生物から実尺を拾う。

    どちらもその録画のmp4をffprobeで測って書かれた値で、壁時計からの推定ではない:
      - ``.timing.json`` の ``media_duration``  … recorderがfinalizeで書く
      - ``.thumbs.json`` の ``sprite.duration_seconds`` … サムネsheet生成時の実測

    現行mp4が残っている12本で突き合わせた実測誤差は、timing mapが最大3.9秒(2.3%)、
    thumb sheetは1本を除き完全一致(その1本は生成後に再mp4化された古い世代で3%差)。
    直そうとしている誤差が10〜90000倍であることを思えば、十分な精度である。"""
    for root in roots:
        directory = root / recorder_mod.SIDECAR_DIRNAME
        for suffix, pick, source in (
            (recorder_mod.TIMING_SUFFIX,
             lambda d: d.get("media_duration"), SRC_TIMING),
            (thumbnails.META_SUFFIX,
             lambda d: (d.get("sprite") or {}).get("duration_seconds"), SRC_THUMBS),
        ):
            path = directory / (stem + suffix)
            if not path.is_file():
                continue
            try:
                seconds = pick(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, AttributeError):
                logger.warning("派生物を読めません: %s", path, exc_info=True)
                continue
            if seconds and seconds > 0:
                return float(seconds), source
    return None, None


async def _probe(path: Path) -> float | None:
    """mp4の実尺。finalizeが使う実装をそのまま借りる(ここで別のffprobe呼び出しを書くと、
    尺の出所が2つに割れる)。"""
    probe = Recorder("", str(path.parent), None)
    probe.base = path.stem
    return await probe._measure_duration(path)


async def _measure(row: sqlite3.Row, roots: list[Path]) -> tuple[float | None, str | None]:
    """(実尺秒, 出所)。測れなければ (None, None)。

    mp4を消してしまった録画でも、その録画を測って書かれた値は方々に残っている。証拠の
    強い順に試す:
      1. 現行mp4          — その録画そのもの
      2. HLS(EXTINF合計)  — mp4を消しても.tsが残っていれば素材の尺は確定する
      3. timing map / thumb sheet — 生成時にffprobeで測った値(_sidecar_seconds)
      4. 既存のduration_seconds — migrationが文字起こし(transcripts.duration)から埋めた値。
         文字起こしはmp4そのものを読んで作られており、fileからの推測ではない
      5. _backup の退避mp4 — ここまで全て無い録画の最後の手段。**旧経路(concat
         demuxer)で作った退避は幻の音声穴でtimestampが伸びており、同じ内容を作り直すと
         尺だけが数%縮む**(実測: 4151秒 -> 4000秒、frame数は同一)。数%長い側に外れる
         可能性を承知で使う — event窓は広い側に外れる方が安全(狭めるとcommentが落ちる)

    どれも「測った値」であって壁時計からの推定ではない。1つも無ければNoneを返す。
    """
    mp4 = _mp4_for(row, roots)
    if mp4 is not None:
        seconds = await _probe(mp4)
        if seconds:
            return seconds, SRC_MP4
    seconds = _hls_seconds(row, roots)
    if seconds:
        return seconds, SRC_HLS
    stem = _stem(row)
    if stem:
        seconds, source = _sidecar_seconds(stem, roots)
        if seconds:
            return seconds, source
    stored = row["duration_seconds"]
    if stored and stored > 0:
        return float(stored), SRC_STORED
    for backup in (backups.backups_for(stem, roots) if stem else []):
        seconds = await _probe(backup)
        if seconds:
            return seconds, SRC_BACKUP
    return None, None


def _ended_at_verdict(row: sqlite3.Row, measured: float | None) -> tuple[float | None, str]:
    """(置き換えるended_at, 理由)。直す必要が無ければ (None, "")。

    実尺を測れていない行は、どれだけ疑わしくても直さない。置き換える正しい値を計算できず、
    上限で丸めれば「測っていない数字を測ったように見せる」ことになる。"""
    ended, started = row["ended_at"], row["started_at"]
    if not ended or not started or ended <= started or not measured:
        return None, ""
    wall = ended - started
    if wall > measured * DURATION_FACTOR + DURATION_GRACE:
        return started + measured, WHY_DURATION
    reprocessed = row["reprocessed_at"]
    if reprocessed and abs(ended - reprocessed) <= FINGERPRINT_WINDOW \
            and wall > measured * FINGERPRINT_FACTOR + FINGERPRINT_GRACE:
        return started + measured, WHY_REPROCESS
    return None, ""


def _overlapping_ids(rows: list[sqlite3.Row]) -> set:
    """次の録画の開始より後に終わっている録画のid。

    1人の配信者の録画は重ならない(collectorは1本ずつしか回さない)。次の開始より後に
    終わっている ended_at は、その値が捕捉の終わりでない証拠になる。sessionの終了と違い、
    この上限は実際に観測された事実なので誤検出しない。"""
    by_streamer: dict = {}
    for row in rows:
        if row["started_at"]:
            by_streamer.setdefault(row["unique_id"], []).append(row)
    flagged = set()
    for series in by_streamer.values():
        series.sort(key=lambda r: r["started_at"])
        for current, following in zip(series, series[1:]):
            if current["ended_at"] and current["ended_at"] > following["started_at"]:
                flagged.add(current["id"])
    return flagged


def _fmt(seconds: float | None) -> str:
    if not seconds or seconds <= 0:
        return "—"
    total = int(seconds)
    return f"{total // 3600}:{total // 60 % 60:02d}:{total % 60:02d}"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="実際に書き込む(既定はdry-run)")
    parser.add_argument("--unique-id", help="この配信者の録画だけを対象にする")
    parser.add_argument("--durations-only", action="store_true",
                        help="尺の測定だけ行い、ended_atは触らない")
    parser.add_argument("--clear-broken-ended-at", action="store_true",
                        help="実尺を測れず、かつ次の録画より後に終わっている行のended_atを"
                             "NULL(不明)にする。既定は触らない")
    args = parser.parse_args()

    if not ffprobe_available():
        logger.error("ffprobeがPATHにありません。尺を測れないため中止します。")
        return 2

    db_path = get_db_path()
    if not _has_duration_column(db_path):
        logger.error(
            "recordings表にduration_seconds列がありません。列の追加はserver起動時の"
            "migrationが行います。serverを一度起動してから実行してください。")
        return 2
    roots = _roots(db_path)
    logger.info("DB: %s", db_path)
    logger.info("録画root: %s", " / ".join(str(r) for r in roots))

    rows = _rows(db_path, args.unique_id)
    if not rows:
        logger.info("対象の録画行がありません。")
        return 0

    overlapping = _overlapping_ids(rows)
    duration_updates: list[tuple[int, float]] = []
    ended_updates: list[tuple[int, float]] = []
    unmeasured: list[sqlite3.Row] = []
    unrepairable: list[sqlite3.Row] = []
    by_source = {name: 0 for name in SOURCES}

    for row in rows:
        measured, source = await _measure(row, roots)
        if measured is None:
            unmeasured.append(row)
        else:
            by_source[source] += 1
            if row["duration_seconds"] is None or \
                    abs(row["duration_seconds"] - measured) > 1.0:
                duration_updates.append((row["id"], measured))
        if args.durations_only:
            continue
        new_ended, why = _ended_at_verdict(row, measured)
        if new_ended is None:
            # 実尺が無いまま「次の録画の開始より後に終わっている」行。壊れている証拠は
            # あるが正しい値を計算できないので触らない。件数を伏せると「全部直った」と
            # 読めてしまうため、必ず別掲する。
            if measured is None and row["id"] in overlapping:
                unrepairable.append(row)
            continue
        ended_updates.append((row["id"], new_ended))
        logger.info(
            "  id=%-5s %-16s 尺 %-10s %-10s ended_at %s -> %s  (%s)",
            row["id"], (row["unique_id"] or "")[:16],
            _fmt(measured), source,
            _fmt(row["ended_at"] - row["started_at"]),
            _fmt(new_ended - row["started_at"]), why,
        )

    logger.info("")
    logger.info("録画 %d本: 実尺を測れた %d本 (%s)、測れない %d本",
                len(rows), len(rows) - len(unmeasured),
                " / ".join(f"{name} {by_source[name]}" for name in SOURCES),
                len(unmeasured))
    logger.info("duration_seconds を書く: %d本", len(duration_updates))
    if not args.durations_only:
        logger.info("ended_at を是正する: %d本", len(ended_updates))
        if unrepairable:
            # 壊れている証拠(次の録画の開始より後に終わっている)はあるのに、実尺が測れず
            # 正しい値を出せない行。黙って落とすと「全部直った」と読めてしまうので別掲する。
            logger.warning("壊れているが是正できない(実尺を測れない): %d本 -> id=%s",
                           len(unrepairable),
                           ",".join(str(r["id"]) for r in unrepairable))
            if args.clear_broken_ended_at:
                logger.warning("  上記のended_atをNULL(不明)にします")
            else:
                logger.warning("  既定では触りません(--clear-broken-ended-at でNULLにできます)")
    if unmeasured:
        logger.info("尺が未測定のまま残る(測る対象が1つも残っていない): %d本", len(unmeasured))

    cleared = [r["id"] for r in unrepairable] if (
        args.clear_broken_ended_at and not args.durations_only) else []

    if not args.apply:
        logger.info("")
        logger.info("dry-runです。書き込むには --apply を付けてください。")
        return 0
    if not duration_updates and not ended_updates and not cleared:
        logger.info("書き込む変更がありません。")
        return 0

    # 書き換えるended_atは元の値がどこにも残らない(上書き)。押す前の状態へ戻せるよう、
    # 書き込みの直前に丸ごと退避する。VACUUM INTOはWALの内容も畳んだ1 fileを作る。
    backup = Path(db_path).with_name(
        f"{Path(db_path).name}.bak-durations-{time.strftime('%Y%m%d-%H%M%S')}")
    if backup.exists():
        logger.error("退避先が既にあります: %s", backup)
        return 2
    source = _open_ro(db_path)
    try:
        source.execute("VACUUM INTO ?", (backup.as_posix(),))
    finally:
        source.close()
    logger.info("DBを退避しました: %s", backup)

    conn = sqlite3.connect(db_path, timeout=30)
    try:
        with conn:
            conn.executemany(
                "UPDATE recordings SET duration_seconds = ? WHERE id = ?",
                [(seconds, rid) for rid, seconds in duration_updates])
            conn.executemany(
                "UPDATE recordings SET ended_at = ? WHERE id = ?",
                [(ended, rid) for rid, ended in ended_updates])
            # 「壊れていると判っているが真の値を知りようがない」行はNULL(不明)にする。
            # 上限で丸めると測った値と見分けが付かなくなるので、丸めるのではなく落とす。
            # analyticsのカバレッジはended_atが無い録画をそのsessionごと計測不能として
            # 扱うので、NULLは黙って0になる値ではなく「測っていない」として伝わる。
            conn.executemany(
                "UPDATE recordings SET ended_at = NULL WHERE id = ?",
                [(rid,) for rid in cleared])
    finally:
        conn.close()
    logger.info("書き込みました: duration_seconds %d本 / ended_at %d本 / ended_atをNULLに %d本",
                len(duration_updates), len(ended_updates), len(cleared))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
