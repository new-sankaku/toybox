"""転写segmentとcommentを横断検索indexへ正規化して投入する。

検索結果からの動画seekを焼き込み動画と一致させるため、commentのwall-clockから
再生の時間軸への変換はvideo_overlayと同一のmapperを使う。単純な``time - started_at``は
mp4のmux overheadで最大20秒以上ずれるため使わない(_make_time_mapperのdocstring参照)。

**軸は再生経路で決まる**(_playback_media_pts)。.tsが残る録画はHLSで再生され、player の
currentTime は playlist の EXTINF 累積 = media軸である。mp4でしか再生できない録画だけが
PTS軸になる。

変換はindex時に一度だけ行い、結果をsearch_hits.video_timeへ焼き付ける。検索queryごとに
mapperを組み直すと録画1本あたりffprobeが走るので、検索が実用速度に乗らない。焼き付けた
以上、素材の在り方(=再生経路)が変われば軸も変わる。作り直しは
scripts/repair_search_time_axis.py が行う。
"""

import logging
from pathlib import Path
from typing import Optional

from tictok.media import hls_source
from tictok.record.video_overlay import (
    _load_media_pts,
    _load_timing_anchors,
    _make_time_mapper,
    _probe_duration_us,
)

logger = logging.getLogger(__name__)

SOURCE_STT = "stt"
SOURCE_COMMENT = "comment"
SOURCE_LAUGH = "laugh"

AXIS_MEDIA = "media"
AXIS_PTS = "pts"


def playback_axis(src: Path) -> str:
    """この録画の秒がどの軸で読まれるか。HLS再生なら``media``、mp4再生なら``pts``。"""
    return AXIS_MEDIA if hls_source.plays_from_hls(src) else AXIS_PTS


def _playback_media_pts(src: Path, anchors: Optional[list]) -> Optional[list]:
    """playerの軸へ載せるための media->pts 対応を返す。

    録画時に作った ``media_pts`` は media -> **mp4のPTS** の対応で、mp4を再生する録画に
    しか正しくない。HLSで再生する録画にこれを掛けると、mp4のmux inflationぶんだけ
    commentが後ろへずれる(実測で最大21.5秒)。恒等の2点mapを返して既存の経路をそのまま
    恒等で通す — video_overlay._render_context の is_hls 分岐と同じ扱いである。"""
    if not hls_source.plays_from_hls(src):
        return _load_media_pts(src)
    if not anchors or len(anchors) < 2:
        return None
    media_end = float(anchors[-1][1])
    return [(0.0, 0.0), (media_end, media_end)] if media_end > 0 else None


def build_time_mapper_sync(src: Path, started_at: float, ended_at: Optional[float]):
    """wall-clock -> 再生の時間軸(秒)のmapperを同期で作る。

    ffprobeを避けるためvideo_durationは渡さない。media_ptsを持つ録画(現行recorderの
    出力)ではmapperがそもそも参照しないので精度は変わらず、持たない旧録画では素の
    wall offsetへ縮退する。heat barのように概位置で足りる用途のみに使うこと。"""
    anchors = _load_timing_anchors(src)
    return _make_time_mapper(anchors, started_at, ended_at, None, None,
                             _playback_media_pts(src, anchors))


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
        "転写をindexへ登録しました: recording_id=%d segments=%d", recording["id"], count,
        extra={"event": "search.transcript_indexed",
               "ctx": {"recording_id": recording["id"], "segments": count}},
    )
    return count


def laugh_windows(profile: dict, threshold: float, merge_gap: float,
                  min_seconds: float) -> list:
    """笑い確率の刻み列を「笑っていた窓」へ畳む。``[(start, end, peak), ...]``。

    畳むのは、確率列がhop刻み(既定1秒)の点列で、そのまま行にすると1回の笑いが数行へ
    割れるため。息継ぎで確率が1〜2刻み落ちるのは同じ笑いの中の出来事なので、
    ``merge_gap`` 以内の谷はつないでしまう。

    ``peak`` は窓の中の最大確率。強さの目安として行の本文へ出す — 閾値を超えたかどうか
    だけだと、はっきり笑った場面と辛うじて超えた場面が同じ顔で並ぶ。
    """
    interval = profile["interval_seconds"]
    probs = profile["probs"]
    if interval <= 0:
        return []
    gap_ticks = max(0, int(round(merge_gap / interval)))
    windows: list = []
    run_start = None
    run_peak = 0.0
    last_hit = None
    for i, value in enumerate(probs):
        if value < threshold:
            continue
        if run_start is None or (last_hit is not None and i - last_hit > gap_ticks + 1):
            if run_start is not None:
                windows.append((run_start, last_hit, run_peak))
            run_start, run_peak = i, value
        else:
            run_peak = max(run_peak, value)
        last_hit = i
    if run_start is not None:
        windows.append((run_start, last_hit, run_peak))
    out = []
    for first, last, peak in windows:
        start, end = first * interval, (last + 1) * interval
        if end - start + 1e-9 < min_seconds:
            continue
        out.append((round(start, 2), round(end, 2), round(peak, 3)))
    return out


def index_laughter(storage, recording: dict, profile: dict,
                   threshold: Optional[float] = None) -> int:
    """録画の笑い声をindexへ投入する。

    確率列の秒は**そのままvideo_timeにできる**。laugh_audioは再生と同じ素材を
    ``hls_source.ffmpeg_source`` 経由で読み、波形と同じ ``aresample=async=1:first_pts=0``
    で穴を埋めているので、sample数がそのまま再生位置になる(転写と同じ扱いで、commentの
    ように壁時計から写す必要が無い)。

    本文に秒数と強さを書くのは、検索結果の行がそれだけで選べるようにするため。語で
    引けることも兼ねる — ``笑い声`` は3文字なのでtrigram FTSに乗る。
    """
    from tictok.core.config import (get_laugh_audio_threshold,
                                    get_laugh_index_merge_gap_seconds,
                                    get_laugh_index_min_seconds)

    threshold = get_laugh_audio_threshold() if threshold is None else threshold
    windows = laugh_windows(profile, threshold,
                            get_laugh_index_merge_gap_seconds(),
                            get_laugh_index_min_seconds())
    rows = [{
        "session_id": recording.get("session_id"),
        "unique_id": recording["unique_id"],
        "started_at": recording["started_at"],
        "video_time": start,
        "end_time": end,
        "nickname": None,
        "body": f"笑い声 {end - start:.0f}秒（強さ {peak:.2f}）",
    } for start, end, peak in windows]
    count = storage.replace_search_hits(recording["id"], SOURCE_LAUGH, rows)
    logger.info(
        "笑い声をindexへ登録しました: recording_id=%d windows=%d threshold=%.2f",
        recording["id"], count, threshold,
        extra={"event": "search.laughter_indexed",
               "ctx": {"recording_id": recording["id"], "windows": count,
                       "threshold": threshold,
                       "duration_seconds": profile.get("duration_seconds")}},
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
    media_pts = _playback_media_pts(src, anchors)
    # media_ptsがあればmapperはvideo_duration/pts_gapsを参照しない。無い旧録画のときだけ
    # 尺をprobeして、wall窓をmp4の実尺へ線形に載せるfallbackを効かせる。
    video_dur = None
    if not (media_pts and len(media_pts) >= 2):
        dur_us = await _probe_duration_us(src) if src.is_file() else None
        video_dur = dur_us / 1_000_000 if dur_us else None

    started_at = recording["started_at"]
    ended_at = recording.get("ended_at")
    to_pts = _make_time_mapper(anchors, started_at, ended_at, video_dur, None, media_pts)

    # ended_atが無い録画(crashで中断した行・確定の途中で落ちた行)は窓の終わりが決まらない。
    # そのままiter_eventsへ渡すとsession末尾まで開きっぱなしになり、同じsessionの後続録画の
    # commentを丸ごとこの録画のものとして取り込む(焼き込みで同じ形の事故があり、
    # doc/BUG_CHECKLIST.mdに記録がある)。次の録画が始まった時刻で閉じる。
    #
    # 閉じるのはeventの窓だけで、mapperには渡さない。mapperのended_atは「捕捉が終わった
    # 時刻」として壁時計の窓を実尺へ線形に載せるのに使われるので、別の意味の値を入れると
    # 秒そのものが歪む。
    window_end = ended_at
    if window_end is None:
        window_end = storage.next_recording_start(session_id, started_at)

    events = storage.iter_events(session_id, started_at, window_end)
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
    # 実際に書いた軸を録画へ記録する。migrate_time_axis_to_media.py はこの列で変換済みを
    # 判定するので、書いた側が名乗らないと同じ値へ二重に変換が掛かる。
    axis = playback_axis(src)
    storage.set_recording_time_axis(recording["id"], axis)
    logger.info(
        "commentをindexへ登録しました: recording_id=%d comments=%d axis=%s",
        recording["id"], count, axis,
        extra={"event": "search.comments_indexed",
               "ctx": {"recording_id": recording["id"], "comments": count, "time_axis": axis,
                       "anchors": len(anchors) if anchors else 0,
                       "media_pts": len(media_pts) if media_pts else 0,
                       "video_duration_seconds": video_dur,
                       "window_end": "ended_at" if ended_at is not None else (
                           "next_recording" if window_end is not None else "open")}},
    )
    return count
