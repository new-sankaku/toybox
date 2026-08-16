"""文字起こしsegmentとcommentを横断検索indexへ正規化して投入する。

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
import time
from pathlib import Path
from typing import Optional

from tictok.media import hls_source
from tictok.record.recorder import PTS_DISCONTINUITY_MIN_SECONDS
from tictok.record.video_overlay import (
    _load_media_pts,
    _load_timing_anchors,
    _make_time_mapper,
    _probe_duration_us,
    _probe_pts_gaps,
)

logger = logging.getLogger(__name__)

SOURCE_STT = "stt"
SOURCE_COMMENT = "comment"
SOURCE_LAUGH = "laugh"

# 笑い声indexの張り方の版。窓の作り方(除外の効かせ方を含む)を変えたら+1する。録画へ
# 記録した版が現行と違うindexは、一括処理の笑い声分析が対象へ戻して張り直す。
# 1 = 共演中を外さない(この版で張った行は列を持たないのでNULLとして残る) /
# 2 = 共演中(コラボ・Battle)をDBの窓で外す。
LAUGH_INDEX_VERSION = 2

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


async def build_playback_mapper(src: Path, started_at: float,
                                ended_at: Optional[float]) -> tuple:
    """wall-clock -> 再生の時間軸(秒)のmapperと、その組み立ての内訳を返す。

    commentの秒を作るのも、既存の秒を検算するのも、必ずこの1箇所を通すこと。片方だけが
    違う材料でmapperを組むと、張り直す必要のない録画を「ズレている」と判定する。"""
    anchors = _load_timing_anchors(src)
    media_pts = _playback_media_pts(src, anchors)
    info = {"anchors": len(anchors) if anchors else 0,
            "media_pts": len(media_pts) if media_pts else 0,
            "video_duration_seconds": None, "pts_gaps": 0, "pts_pad_seconds": 0.0}
    if media_pts and len(media_pts) >= 2:
        # 録画時に作った対応表があれば、mapperはvideo_duration/pts_gapsを参照しない。
        return _make_time_mapper(anchors, started_at, ended_at, None, None, media_pts), info

    dur_us = await _probe_duration_us(src) if src.is_file() else None
    video_dur = dur_us / 1_000_000 if dur_us else None
    info["video_duration_seconds"] = video_dur
    # mp4が素材(anchorsのmedia軸、無ければ捕捉の壁時計窓)より長い録画は、A/Vズレ修復より
    # 前のconcatが素材に無い時間を書き足している。その水増しには凍結区間が混じり、単一
    # scaleへ畳むと録画全体へ塗り広げられるので、穴の位置を実測して写像へ渡す。全packetを
    # 舐めるprobeなので、水増しが凍結区間1つぶんに満たない録画では走らせない。
    # 穴はmp4の中にしか無い。HLSで再生する録画にmp4の穴を持ち込むと、playerが辿らない
    # 時間軸へcommentを載せることになる。
    pts_gaps = None
    span = anchors[-1][1] if (anchors and len(anchors) >= 2) else (
        (ended_at - started_at) if ended_at else None)
    if video_dur and span and not hls_source.plays_from_hls(src) \
            and video_dur - span > PTS_DISCONTINUITY_MIN_SECONDS:
        pts_gaps = await _probe_pts_gaps(src)
        info["pts_gaps"] = len(pts_gaps)
        info["pts_pad_seconds"] = round(sum(end - start for start, end in pts_gaps), 2)
    return (_make_time_mapper(anchors, started_at, ended_at, video_dur, pts_gaps, media_pts),
            info)


def index_transcript(storage, recording: dict) -> int:
    """録画の文字起こしsegmentをindexへ投入する。segmentのstart/endは文字起こし側で既にmedia軸へ
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
        "文字起こしをindexへ登録しました: recording_id=%d segments=%d", recording["id"], count,
        extra={"event": "search.transcript_indexed",
               "ctx": {"recording_id": recording["id"], "segments": count}},
    )
    return count


def laugh_windows(profile: dict, threshold: float, merge_gap: float,
                  min_seconds: float, exclude_spans: Optional[list] = None) -> list:
    """笑い確率の刻み列を「笑っていた窓」へ畳む。``[(start, end, peak), ...]``。

    畳むのは、確率列がhop刻み(既定1秒)の点列で、そのまま行にすると1回の笑いが数行へ
    割れるため。息継ぎで確率が1〜2刻み落ちるのは同じ笑いの中の出来事なので、
    ``merge_gap`` 以内の谷はつないでしまう。

    ``peak`` は窓の中の最大確率。強さの目安として行の本文へ出す — 閾値を超えたかどうか
    だけだと、はっきり笑った場面と辛うじて超えた場面が同じ笑い顔で並ぶ。

    ``exclude_spans`` (``[(start, end), ...]`` 動画時間の秒)に入る刻みは閾値を超えて
    いなかったものとして扱う。窓の作り方はここでは決めない(``laugh_audio.laugh_seconds``
    と同じ口)。除外した刻みは**谷ではなく切れ目**である — 除外区間を挟んだ前後を
    ``merge_gap`` でつなぐと、共演中を跨いで1つの窓になり、外したはずの秒が窓の長さへ
    戻ってくる。
    """
    interval = profile["interval_seconds"]
    probs = profile["probs"]
    if interval <= 0:
        return []
    # 刻みの数え方はengine側(laugh_seconds)と同じ1箇所から借りる。同じ除外窓で
    # 「一覧に出る秒」と「候補の秒」が違う数え方をすると、同じ配信に2つの答えが出る。
    # importがmethodの中に在るのは、indexerはffmpeg周りを引き込む重い側だからである。
    from tictok.media.laugh_audio import excluded_ticks

    excluded = excluded_ticks(exclude_spans, interval, 0, len(probs))
    gap_ticks = max(0, int(round(merge_gap / interval)))
    windows: list = []
    run_start = None
    run_peak = 0.0
    last_hit = None
    for i, value in enumerate(probs):
        if i in excluded:
            # 切れ目。ここで畳まずに閉じておかないと、次のhitがmerge_gap以内なら
            # 除外区間ごと1つの窓へ飲み込まれる。
            if run_start is not None:
                windows.append((run_start, last_hit, run_peak))
                run_start, last_hit = None, None
            continue
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


def _windows_seconds(windows: list) -> float:
    """``laugh_windows`` が返した窓の合計秒。窓は重ならないので単純な和でよい。"""
    return sum(end - start for start, end, _peak in windows)


def coop_spans(storage, recording: dict, profile: dict,
               src: Optional[Path] = None, mode: Optional[str] = None) -> tuple:
    """この録画の共演区間を**動画時間の秒**で返す。``(spans, meta)``。

    出所はDB(collab_windows / battles)で、窓は壁時計である。commentと同じmapperで
    動画時間へ写してから返す — 生の ``time - started_at`` は最大20秒以上ずれるので、
    そのまま笑い声の刻みに当てると外す場所が数十秒単位で動く。

    ``meta`` は「何をどれだけ外したか」で、そのままindexの条件として録画へ残る。
    ``collab_observed`` がFalseなら、その配信は現行ruleでコラボを観測できた時期より前で、
    **1秒も外れていない**(記録の無いことを「コラボが無かった」とは読まない)。
    """
    from tictok.core.intervals import merge_intervals, subtract_intervals, total_span

    meta = {"mode": mode, "collab_observed": True,
            "collab_seconds": 0.0, "battle_seconds": 0.0}
    session_id = recording.get("session_id")
    if mode == "none" or session_id is None:
        # sessionを持たない録画にはDB側の事実が無い。窓を作れないことは名乗る。
        meta["collab_observed"] = session_id is not None
        return [], meta
    windows = storage.coop_windows_for_session(session_id)
    meta["collab_observed"] = windows["collab_observed"]
    battle_wall = list(windows["battle"]) if mode == "coop" else []
    if not windows["collab"] and not battle_wall:
        return [], meta

    if src is None:
        src = Path(recording["path"])
    started_at = recording["started_at"]
    ended_at = recording.get("ended_at")
    # 窓の終わりが決まっていない録画は次の録画の開始で閉じる(index_commentsと同じ理由:
    # 開きっぱなしにすると同じsessionの後続録画の窓までこの録画へ写る)。
    window_end = ended_at
    if window_end is None:
        window_end = storage.next_recording_start(session_id, started_at)
    to_pts = build_time_mapper_sync(src, started_at, ended_at)
    duration = profile.get("duration_seconds")

    def _to_video(wall: list) -> list:
        out = []
        for start, end in wall:
            if start is None:
                continue
            # 終端を名乗らない窓(収集断・進行中のBattle)は自分の窓の終わりまでとみなす。
            # 「いつ切れたか分からない」を「もう切れていた」と読むと、外すべき秒が残る。
            finish = end if end is not None else window_end
            if window_end is not None and finish is not None:
                finish = min(finish, window_end)
            if finish is None or finish <= start:
                continue
            lo = max(0.0, to_pts(max(start, started_at)))
            hi = to_pts(finish)
            if duration is not None:
                hi = min(hi, float(duration))
            if hi > lo:
                out.append((lo, hi))
        return merge_intervals(out)

    collab = _to_video(windows["collab"])
    battle = _to_video(battle_wall)
    meta["collab_seconds"] = round(total_span(collab), 2)
    # Battleぶんは「コラボと重なっていない秒」で数える。両者は同じLinkMicの上で起きて
    # 重なり得るので、そのまま足すと外した秒の合計が実際より長く見える。
    meta["battle_seconds"] = round(
        total_span(subtract_intervals(battle, collab)), 2)
    return merge_intervals(collab + battle), meta


def index_laughter(storage, recording: dict, profile: dict,
                   threshold: Optional[float] = None,
                   src: Optional[Path] = None) -> int:
    """録画の笑い声をindexへ投入する。

    確率列の秒は**そのままvideo_timeにできる**。laugh_audioは再生と同じ素材を
    ``hls_source.ffmpeg_source`` 経由で読み、波形と同じ ``aresample=async=1:first_pts=0``
    で穴を埋めているので、sample数がそのまま再生位置になる(文字起こしと同じ扱いで、commentの
    ように壁時計から写す必要が無い)。

    本文に秒数と強さを書くのは、一覧の行がそれだけで選べるようにするため。**語では
    引かせない** — 音が根拠で本文に当たる語が無く、語の検索へ混ぜると「笑い声」と
    打ったときだけ出る隠しmodeになる。並べ替えの根拠は本文ではなくscore(窓の最大確率)で、
    画面は専用の一覧(``/api/search/laughs``)から引く。

    共演中(コラボ・Battle)の窓は既定で**行にしない**(``get_laugh_index_exclude_coop``)。
    共演中の音声には相手の声が乗っており、どの笑いが配信者のものかを音から決める手段が
    無いためで、外した条件は録画へ記録する — 条件を変えたときに、古い条件で張ったindexが
    済みのまま残らないようにする(一括処理の済み判定がこの記録を見る)。
    """
    from tictok.core.config import (get_laugh_audio_threshold,
                                    get_laugh_index_exclude_coop,
                                    get_laugh_index_merge_gap_seconds,
                                    get_laugh_index_min_seconds)

    threshold = get_laugh_audio_threshold() if threshold is None else threshold
    mode = get_laugh_index_exclude_coop()
    spans, meta = coop_spans(storage, recording, profile, src=src, mode=mode)
    merge_gap = get_laugh_index_merge_gap_seconds()
    min_seconds = get_laugh_index_min_seconds()
    windows = laugh_windows(profile, threshold, merge_gap, min_seconds,
                            exclude_spans=spans)
    # 外した結果どれだけ消えたかは、除外なしの窓と比べたときにしか出せない。残すのは
    # 「0件の録画」が解析の失敗なのか共演で埋まっていたのかを後から読むためで、確率列を
    # もう一度走査するだけ(実測で3時間の録画でも数ms)。**窓の数では測れない** —
    # 共演を挟んで1つの窓が2つに割れるので、外したのに数が増える。
    meta["windows"] = len(windows)
    meta["excluded_laugh_seconds"] = round(
        _windows_seconds(laugh_windows(profile, threshold, merge_gap, min_seconds))
        - _windows_seconds(windows), 2) if spans else 0.0
    rows = [{
        "session_id": recording.get("session_id"),
        "unique_id": recording["unique_id"],
        "started_at": recording["started_at"],
        "video_time": start,
        "end_time": end,
        "nickname": None,
        # 種別は行の種別欄が名乗るので、本文で「笑い声」と繰り返さない。
        "body": f"{end - start:.0f}秒（強さ {peak:.2f}）",
        "score": peak,
    } for start, end, peak in windows]
    count = storage.replace_search_hits(recording["id"], SOURCE_LAUGH, rows)
    meta["version"] = LAUGH_INDEX_VERSION
    meta["threshold"] = threshold
    meta["indexed_at"] = time.time()
    storage.set_laugh_index_meta(recording["id"], meta)
    logger.info(
        "笑い声をindexへ登録しました: recording_id=%d windows=%d threshold=%.2f"
        "（共演の除外=%s コラボ%.0f秒 Battle%.0f秒 数えなかった笑い%.0f秒）",
        recording["id"], count, threshold, mode,
        meta["collab_seconds"], meta["battle_seconds"], meta["excluded_laugh_seconds"],
        extra={"event": "search.laughter_indexed",
               "ctx": {"recording_id": recording["id"], "windows": count,
                       "threshold": threshold,
                       "duration_seconds": profile.get("duration_seconds"),
                       **meta}},
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

    started_at = recording["started_at"]
    ended_at = recording.get("ended_at")
    to_pts, axis_info = await build_playback_mapper(src, started_at, ended_at)

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
                       **axis_info,
                       "window_end": "ended_at" if ended_at is not None else (
                           "next_recording" if window_end is not None else "open")}},
    )
    return count
