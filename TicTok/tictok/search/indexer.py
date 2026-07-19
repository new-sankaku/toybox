"""転写segmentとcommentを横断検索indexへ正規化して投入する。

検索結果からの動画seekを焼き込み動画と一致させるため、commentのwall-clockから
mp4 PTSへの変換はvideo_overlayと同一のmapperを使う。単純な``time - started_at``は
mp4のmux overheadで最大20秒以上ずれるため使わない(_make_time_mapperのdocstring参照)。

変換はindex時に一度だけ行い、結果をsearch_hits.video_timeへ焼き付ける。検索queryごとに
mapperを組み直すと録画1本あたりffprobeが走るので、検索が実用速度に乗らない。
"""

import logging
from pathlib import Path
from typing import Optional

from tictok.record.video_overlay import (
    _load_media_pts,
    _load_timing_anchors,
    _make_time_mapper,
    _probe_duration_us,
)

logger = logging.getLogger(__name__)

SOURCE_STT = "stt"
SOURCE_COMMENT = "comment"


def build_time_mapper_sync(src: Path, started_at: float, ended_at: Optional[float]):
    """wall-clock -> mp4 PTS秒のmapperを同期で作る。

    ffprobeを避けるためvideo_durationは渡さない。media_ptsを持つ録画(現行recorderの
    出力)ではmapperがそもそも参照しないので精度は変わらず、持たない旧録画では素の
    wall offsetへ縮退する。heat barのように概位置で足りる用途のみに使うこと。"""
    anchors = _load_timing_anchors(src)
    media_pts = _load_media_pts(src)
    return _make_time_mapper(anchors, started_at, ended_at, None, None, media_pts)


def index_transcript(storage, recording: dict) -> int:
    """録画の転写segmentをindexへ投入する。segmentのstart/endは転写側で既にmedia軸へ
    再mapされている(transcription._media_time)ので、そのままvideo_timeにできる。"""
    transcript = storage.get_transcript(recording["id"])
    if transcript is None:
        return storage.replace_search_hits(recording["id"], SOURCE_STT, [])
    rows = []
    for segment in transcript.get("segments") or []:
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        rows.append({
            "session_id": recording.get("session_id"),
            "unique_id": recording["unique_id"],
            "started_at": recording["started_at"],
            "video_time": float(segment.get("start") or 0.0),
            "end_time": segment.get("end"),
            "nickname": None,
            "body": text,
        })
    count = storage.replace_search_hits(recording["id"], SOURCE_STT, rows)
    logger.info(
        "transcript indexed: recording_id=%d segments=%d", recording["id"], count,
        extra={"event": "search.transcript_indexed",
               "ctx": {"recording_id": recording["id"], "segments": count}},
    )
    return count


async def index_comments(storage, recording: dict, src: Optional[Path] = None) -> int:
    """録画窓のcommentをindexへ投入する。

    eventはrecording窓([started_at, ended_at])で絞る。session内に複数録画がある場合、
    session全eventを渡すと2本目以降の原点が壊れるため(焼き込みと同じ制約)。"""
    session_id = recording.get("session_id")
    if session_id is None:
        return storage.replace_search_hits(recording["id"], SOURCE_COMMENT, [])
    if src is None:
        src = Path(recording["path"])

    anchors = _load_timing_anchors(src)
    media_pts = _load_media_pts(src)
    # media_ptsがあればmapperはvideo_duration/pts_gapsを参照しない。無い旧録画のときだけ
    # 尺をprobeして、wall窓をmp4の実尺へ線形に載せるfallbackを効かせる。
    video_dur = None
    if not (media_pts and len(media_pts) >= 2):
        dur_us = await _probe_duration_us(src) if src.is_file() else None
        video_dur = dur_us / 1_000_000 if dur_us else None

    started_at = recording["started_at"]
    ended_at = recording.get("ended_at")
    to_pts = _make_time_mapper(anchors, started_at, ended_at, video_dur, None, media_pts)

    events = storage.iter_events(session_id, started_at, ended_at)
    rows = []
    for event in events:
        if event.get("kind") != "comment":
            continue
        body = (event.get("comment") or event.get("text") or "").strip()
        if not body:
            continue
        video_time = to_pts(event["time"])
        if video_time < 0:
            continue
        rows.append({
            "session_id": session_id,
            "unique_id": recording["unique_id"],
            "started_at": started_at,
            "video_time": round(video_time, 2),
            "end_time": None,
            "nickname": event.get("user_nickname"),
            "body": body,
        })
    count = storage.replace_search_hits(recording["id"], SOURCE_COMMENT, rows)
    logger.info(
        "comments indexed: recording_id=%d comments=%d", recording["id"], count,
        extra={"event": "search.comments_indexed",
               "ctx": {"recording_id": recording["id"], "comments": count,
                       "anchors": len(anchors) if anchors else 0,
                       "media_pts": len(media_pts) if media_pts else 0,
                       "video_duration_seconds": video_dur}},
    )
    return count
