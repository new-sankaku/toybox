"""DBに焼き付いた秒を、その録画が**今どう再生されるか**の時間軸へ揃え直す。

検索hit・heat bar・字幕clickの秒は index 時に一度だけ計算してDBへ焼き付ける。焼き付けた
後で素材の在り方が変わると(mp4を消して.tsだけになった / A/Vズレ修復でmedia軸を作り直した)、
再生の軸だけが動き、焼き付けた秒は古い軸に取り残される。実測(録画00268): commentが末尾で
+133秒、文字起こしは+191秒ずれていた。

この scriptがすること:

  comment index ... eventの壁時計から、再生経路の軸(HLS=media / mp4=PTS)で引き直す。
                    根拠は timing.json の anchors なので、常に「今の軸」で再計算になる。
  time_axis     ... 実際に書いた軸を recordings へ記録する(二重変換の防止)。
  文字起こし    ... 検出のみ。古い軸の秒を今の軸へ戻す map はもう存在しない(作り直された
                    timing.json は修復後の軸しか記述しない)ため、直す手段はやり直しだけ。
                    ``--enqueue-transcripts`` で文字起こしqueueへ redo 投入できる。
  bookmark      ... 検出のみ。ユーザーが再生画面で付けた秒で、同じ理由で機械的には直せない。

対象外(触らない):
  * .tsが無くmp4だけの録画 — 再生も文字起こしもそのmp4のPTS軸で、焼き付いた秒は既に正しい。
  * 素材が1つも無い録画 — 再生できないので軸が定義できない。
  * anchors(timing.json)が無い録画 — 引き直す根拠が無い。素の wall offset で上書きすると、
    今より悪い値を「直した」と称して書くことになる。

保存先は1次(record_dir)・2次(record_dir_final)の両方を見る。mp4だけが2次へ移り.tsが1次に
残る経路があるため、片方だけを見ると素材無しと誤判定する(hls_source.session_dir_for と
同じ事情)。

Usage (TicTokディレクトリから、venvで):
    python scripts/repair_search_time_axis.py                  # dry-run(既定)
    python scripts/repair_search_time_axis.py --apply
    python scripts/repair_search_time_axis.py --recording 229 --apply
    python scripts/repair_search_time_axis.py --apply --enqueue-transcripts
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tictok.core import config, layout  # noqa: E402
from tictok.media import hls_source  # noqa: E402
from tictok.record.recorder import timing_path  # noqa: E402
from tictok.search import indexer  # noqa: E402
from tictok.storage import Storage  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("repair_search_time_axis")

# 文字起こしが「別の軸で作られた」と判定する尺の差。文字起こしの duration は復号したcontainerの終端で、
# 同じ素材から作られていれば実尺と秒未満で一致する。VADの丸めと最終segmentの端数を吸収する
# ぶんだけ余裕を持たせる。
TRANSCRIPT_DURATION_TOLERANCE = 2.0
# comment indexを「張り直す価値がある」と見なすズレ。丸め(video_timeは小数2桁)と anchors の
# 補間誤差は0.1秒未満に収まるので、それを超えたものだけを書き換える。
REINDEX_TOLERANCE = 0.5


def resolve_source(recording: dict) -> Path:
    """録画の身元mp4 path。実在するrootを優先して返す(移送でDBのpathが古いことがある)。

    実在しなくてもpathは返す — .tsしか無い録画では、このpathは「読める実体」ではなく
    sidecar(timing.json)と素材の解決に使う身元だからである。"""
    path = Path(recording["path"])
    if path.is_file():
        return path
    stem = Path(recording.get("filename") or path.name).stem
    streamer = layout.streamer_of(stem)
    if not streamer:
        return path
    for root in layout.record_roots():
        candidate = layout.mp4_path(root, stem, streamer)
        if candidate.is_file():
            return candidate
        # mp4が無くても、素材とsidecarが在るrootを身元にする。timing.jsonは
        # record_root_of(src)/.sidecars で解決されるので、rootを取り違えると
        # anchorsが読めない=引き直せない録画に見える。
        if layout.has_media(layout.session_dir(root, stem, streamer)) \
                and timing_path(candidate).is_file():
            return candidate
    return path


def media_duration_of(src: Path) -> float | None:
    """timing.json が記録している素材の実尺(media軸の終端)。無ければNone。"""
    try:
        data = json.loads(timing_path(src).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    duration = data.get("media_duration")
    if isinstance(duration, (int, float)) and duration > 0:
        return float(duration)
    anchors = data.get("anchors")
    if isinstance(anchors, list) and anchors:
        try:
            return float(anchors[-1][1])
        except (TypeError, ValueError, IndexError):
            return None
    return None


def comment_drift(storage, recording: dict, src: Path) -> tuple:
    """(現行DB値と再計算値の最大ズレ秒, 比較できた件数)。比較できなければ (None, 0)。

    比較は本文+nicknameが録画内で一意なcommentだけで行う。同一発言が複数あるとどの行が
    どのeventか決められず、対応を取り違えたぶんが「ズレ」として出てしまう。"""
    hits = storage.search_hits_for(recording["id"], indexer.SOURCE_COMMENT)
    if not hits:
        return None, 0
    anchors = indexer._load_timing_anchors(src)
    if not anchors:
        return None, 0
    to_axis = indexer._make_time_mapper(
        anchors, recording["started_at"], recording.get("ended_at"), None, None,
        indexer._playback_media_pts(src, anchors))
    stored: dict = {}
    for hit in hits:
        stored.setdefault((hit["nickname"], hit["body"]), []).append(hit["video_time"])
    worst = 0.0
    compared = 0
    for event in storage.iter_events(recording["session_id"], recording["started_at"],
                                     recording.get("ended_at")):
        if event.get("kind") != "comment":
            continue
        body = (event.get("comment") or event.get("text") or "").strip()
        if not body:
            continue
        values = stored.get((event.get("user_nickname"), body))
        if not values or len(values) != 1:
            continue
        worst = max(worst, abs(values[0] - to_axis(event["time"])))
        compared += 1
    return (worst, compared) if compared else (None, 0)


async def repair(args) -> int:
    storage = Storage(config.get_db_path())
    try:
        recordings = storage.recordings_brief()
        if args.recording:
            recordings = [r for r in recordings if r["id"] == args.recording]
        stats = {"reindexed": 0, "already": 0, "no_material": 0, "mp4_only": 0,
                 "no_anchors": 0, "no_comments": 0}
        stale_transcripts: list = []
        stale_bookmarks: list = []

        for brief in recordings:
            recording = storage.get_recording(brief["id"])
            if recording is None:
                continue
            src = resolve_source(recording)
            stem = Path(recording.get("filename") or "").stem
            plays_hls = hls_source.plays_from_hls(src)
            if not plays_hls:
                # mp4が在るならその軸のままで正しい。素材が1つも無ければ再生できない。
                stats["mp4_only" if src.is_file() else "no_material"] += 1
                continue

            axis = indexer.playback_axis(src)
            # --- 文字起こし(検出のみ) ---
            transcript = storage.get_transcript(recording["id"])
            media_duration = media_duration_of(src)
            if transcript and media_duration:
                stored_duration = transcript.get("duration")
                if stored_duration and abs(float(stored_duration) - media_duration) \
                        > TRANSCRIPT_DURATION_TOLERANCE:
                    stale_transcripts.append({
                        "id": recording["id"], "stem": stem,
                        "unique_id": recording["unique_id"],
                        "transcript_seconds": round(float(stored_duration), 2),
                        "media_seconds": round(media_duration, 2),
                        "gap": round(float(stored_duration) - media_duration, 2),
                    })
            # --- bookmark(検出のみ) ---
            marks = storage.list_bookmarks(recording["id"])
            if marks and media_duration:
                for mark in marks:
                    if mark.get("start") is not None and float(mark["start"]) > media_duration:
                        stale_bookmarks.append({"id": recording["id"], "stem": stem,
                                                "start": mark["start"]})

            # --- comment index ---
            worst, compared = comment_drift(storage, recording, src)
            if worst is None:
                if not indexer._load_timing_anchors(src):
                    stats["no_anchors"] += 1
                else:
                    stats["no_comments"] += 1
                continue
            if worst <= REINDEX_TOLERANCE and recording.get("time_axis") == axis:
                stats["already"] += 1
                continue
            logger.info("%s%s: comment %d件 最大ズレ %.1fs -> %s軸で張り直し",
                        "" if args.apply else "[dry-run] ", stem[:44], compared, worst, axis)
            if args.apply:
                await indexer.index_comments(storage, recording, src)
            stats["reindexed"] += 1

        logger.info(
            "\n%s comment index 張り直し %d / 既に一致 %d / mp4再生 %d / 素材無し %d"
            " / anchors無し %d / comment無し %d",
            "適用:" if args.apply else "[dry-run] 対象:",
            stats["reindexed"], stats["already"], stats["mp4_only"], stats["no_material"],
            stats["no_anchors"], stats["no_comments"])

        if stale_transcripts:
            stale_transcripts.sort(key=lambda t: -abs(t["gap"]))
            logger.info("\n別の軸で作られた文字起こし %d件(文字起こしのやり直しが必要):", len(stale_transcripts))
            for item in stale_transcripts:
                logger.info("  id=%-5d %-44s 文字起こし %.1fs / 実尺 %.1fs (%+.1fs)",
                            item["id"], item["stem"][:44], item["transcript_seconds"],
                            item["media_seconds"], item["gap"])
            if args.enqueue_transcripts and args.apply:
                added = storage.enqueue_transcriptions(
                    [(t["id"], t["unique_id"]) for t in stale_transcripts], redo=True)
                logger.info("  文字起こしqueueへ %d件を投入しました(serverが順に処理します)", added)
            else:
                logger.info("  文字起こしのやり直しには --apply --enqueue-transcripts を付けてください")

        if stale_bookmarks:
            logger.info("\n素材の尺を超えるbookmark %d件(手で付け直しが必要):",
                        len(stale_bookmarks))
            for item in stale_bookmarks:
                logger.info("  id=%-5d %-44s start=%.1fs", item["id"], item["stem"][:44],
                            item["start"])

        if not args.apply:
            logger.info("\n書き換えるには --apply を付けてください")
        return 0
    finally:
        storage.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="書き換える(既定はdry-run)")
    parser.add_argument("--recording", type=int, help="この録画IDだけを対象にする")
    parser.add_argument("--enqueue-transcripts", action="store_true",
                        help="軸の違う文字起こしを文字起こしqueueへredo投入する(--applyと併用)")
    args = parser.parse_args()
    return asyncio.run(repair(args))


if __name__ == "__main__":
    raise SystemExit(main())
