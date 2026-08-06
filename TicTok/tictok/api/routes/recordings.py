"""録画そのものを読む口: 一覧・再生(mp4/HLS)・字幕・comment・波形・サムネ・切抜き候補。

**読む**routeと、その録画を消すrouteだけを置く。新しい成果物を作る投入(焼き込み・Up出力・
切り出し等)は routes.media にある。
"""

import asyncio
from pathlib import Path
from typing import Awaitable, Callable, NamedTuple, Optional
from urllib.parse import quote
from fastapi import HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from tictok.core.config import get_laugh_comment_min_w_run
from tictok.core import laugh_text
from tictok.record.recorder import ffmpeg_available
from tictok.record.transcription import STTError
from tictok.record.stt_worker import run_transcribe as stt_transcribe
from tictok.media import hls_source
from tictok.media import laugh_audio
from tictok.media import smile
from tictok.media.thumbnails import ensure_sprite, sprite_path
from tictok.media.waveform import (ensure_audio_profile, ensure_waveform, level_peak,
    silence_spans, silent_ratio)
from tictok.search import indexer
from tictok.record import subtitles
from tictok.record.upscale import cleanup_upscale_files
from tictok.core import spike
from tictok.storage import RECORDING_REVIEW_STATES, REVIEW_UNCHECKED
from tictok.record.video_overlay import _duration_seconds, cleanup_overlay_files
from fastapi import APIRouter
from tictok.api import files
from tictok.api import fsfacts
from tictok.api import media_jobs
from tictok.api import runtime

router = APIRouter()


@router.get("/api/recordings")
async def list_recordings() -> dict:
    # 一覧はpollingで叩かれ続ける。素のまま読むと、収集中のcommitがlockを握っている間
    # event loopごと止まり、他の全requestとWS配信が道連れになる。待つのはthread側にする。
    recordings = await asyncio.to_thread(
        runtime.storage.list_recordings, runtime.settings.get("session_list_limit"))
    return {
        "ffmpeg_available": ffmpeg_available(),
        "recordings": recordings,
    }


@router.get("/api/recordings/browse")
async def browse_recordings(unique_id: Optional[str] = None, limit: int = 200) -> dict:
    """検索語を持たない「録画をそのまま開く」ための一覧。

    シーン検索は語が無いと1件も返さないため、これが無いと「とりあえずこの配信を見る」
    ができず、当たる語を先に発明する必要がある。転写の有無まで返すのは、転写が無い
    録画は検索でそもそも当たらず、一覧側で見分けられないと選びようがないため。"""
    handle = runtime._normalize_unique_id(unique_id) if unique_id else None

    def _collect() -> list:
        transcribed = runtime.storage.transcribed_recording_ids()
        rows = (runtime.storage.recordings_for_user(handle) if handle
                else runtime.storage.list_recordings(max(1, min(limit, 2000))))
        # 実体の種別はdir単位に畳んだ一括版で引く。録画ごとにglob(.ts)+statを起こすと、
        # この一覧(実測198件)を開くたびに数百回のfs走査が走る。
        listed = [rec for rec in rows if rec["status"] in ("completed", "interrupted")]
        kinds_by_id = fsfacts.bulk_media_kinds(listed)
        items = []
        for rec in rows:
            # 中断録画(interrupted)も観られる。serverの再起動やcrashで確定を跨げなかった
            # だけで、segmentは揃っていることがある(実測: 588 segmentの中断録画がHLSで
            # 再生できた)。ここでstatusだけを見て捨てると、その録画へ辿る道が一覧から
            # 無くなる — session一括も同じ2状態を対象にしている。録画中(recording)は、
            # 尺も素材も動いている最中なので従来どおり除く。
            if rec["status"] not in ("completed", "interrupted"):
                continue
            # 実体が無い録画も行は残す。転写・検索・bookmarkはそのまま使えるので、
            # 一覧から消すとその録画へ辿る道が無くなる。開けないことは``media``が空である
            # ことで画面が示す(消すのではなく、何が在るかを名乗らせる)。
            media = kinds_by_id.get(rec["id"], [])
            items.append({
                "recording_id": rec["id"],
                "session_id": rec.get("session_id"),
                "unique_id": rec["unique_id"],
                "filename": rec.get("filename"),
                "started_at": rec.get("started_at"),
                "ended_at": rec.get("ended_at"),
                # 一覧の「尺」はここだけを見る。壁時計から出すと、捕捉の停滞も再処理も
                # 尺に化ける。測っていない録画はNULLのまま返し、画面は「—」と出す。
                "duration_seconds": rec.get("duration_seconds"),
                "has_transcript": rec["id"] in transcribed,
                "status": rec["status"],
                # 観たかどうかの印。一覧はこれで絞り込むので、列が無い旧行でも既定値を
                # 名乗らせる(空を返すと画面側がどの状態にも寄せられない)。
                "review_state": rec.get("review_state") or REVIEW_UNCHECKED,
                "review_updated_at": rec.get("review_updated_at"),
                # 実体の種別。filenameは``<stem>.mp4``という身元でしかないので、画面が
                # 「mp4というfileがある」と読ませないよう、実物が何かを併せて返す。
                "media": media,
                "file_exists": bool(media),
            })
        return items[:max(1, min(limit, 2000))]

    return {"recordings": await asyncio.to_thread(_collect)}


class RecordingReviewRequest(BaseModel):
    state: str


@router.patch("/api/recordings/{recording_id}/review")
async def set_recording_review_api(recording_id: int, payload: RecordingReviewRequest) -> dict:
    """録画1本の確認状態(未確認/確認中/確認済)を書き換える。

    印はoperatorが手で動かすものだけにしてある。再生や出力で自動的に進めると、少し覗いた
    だけの録画にも印が付き、「観たかどうか」を問う印としては読めなくなる。"""
    if payload.state not in RECORDING_REVIEW_STATES:
        raise HTTPException(
            status_code=400,
            detail=f"確認状態は {'/'.join(RECORDING_REVIEW_STATES)} のいずれかです。",
        )
    updated = await asyncio.to_thread(
        runtime.storage.set_recording_review, recording_id, payload.state)
    if updated is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    return {
        "recording_id": recording_id,
        "review_state": updated["review_state"],
        "review_updated_at": updated["review_updated_at"],
    }


@router.get("/api/recordings/{recording_id}/play")
async def play_recording(recording_id: int, variant: str = "source") -> FileResponse:
    """Stream a finished recording for in-browser playback (highlight deep-link).
    FileResponse honours the Range header, so the <video> element can seek to the
    highlight offset without downloading the whole file.

    variantで素材版(元録画/焼き込み出力/Up出力)を選ぶ。切り出しと同じ版をそのまま観られない限り、
    利用者は出力結果を確認する手段が無い(pathをcopyして外部playerで開くしかない)。無い版は
    黙ってsourceへ落とさず404を返す(頼んだ版と違うものを再生すると出来を誤認する)。

    HLSと同じくread接続から引く。Range要求はseekのたびに飛ぶので、writer接続では
    再生操作がcollectorの書き込み待ちに乗る。"""
    recording = await asyncio.to_thread(
        runtime.storage.get_recording_for_read, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    if variant not in files.CLIP_VARIANTS:
        raise HTTPException(status_code=400, detail=f"未知の素材版です: {variant}")
    path = files._resolved_recording_path(recording)
    if variant != "source":
        path = files._clip_source(recording, variant)
    elif not path.is_file():
        raise HTTPException(status_code=404, detail="録画fileが存在しません。")
    media_type = {".ts": "video/mp2t", ".webm": "video/webm", ".mkv": "video/x-matroska"}.get(
        path.suffix, "video/mp4"
    )
    if recording["status"] == "recording":
        headers = {"Cache-Control": "no-cache"}
    else:
        headers = {"Cache-Control": f"private, max-age={runtime.RECORDING_CACHE_MAX_AGE_SECONDS}"}
    return FileResponse(path, media_type=media_type, headers=headers)


@router.get("/api/recordings/{recording_id}/playback")
async def recording_playback(recording_id: int, variant: str = "source") -> dict:
    """この録画をどの経路で再生するかを返す。

    素材(.ts)が残っている録画はHLSで直接観る。mp4しか残っていない録画はmp4で観る。どちらに
    なるかは録画ごとの素材の在り方で決まるので、画面側に推測させず、実物を見るこちらで確定
    させる。焼き込み・Up出力はmp4としてしか存在しない(HLSは元録画の素材)ため常にmp4。"""
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    if variant not in files.CLIP_VARIANTS:
        raise HTTPException(status_code=400, detail=f"未知の素材版です: {variant}")
    hls_dir = (await asyncio.to_thread(fsfacts.recording_hls_dir, recording)
               if variant == "source" else None)
    if hls_dir is not None:
        return {"recording_id": recording_id, "variant": variant, "mode": "hls",
                "url": f"/api/recordings/{recording_id}/hls/{files._HLS_PLAYLIST_NAME}"}
    query = "" if variant == "source" else f"?variant={variant}"
    return {"recording_id": recording_id, "variant": variant, "mode": "mp4",
            "url": f"/api/recordings/{recording_id}/play{query}"}


def _hls_target(recording: dict, filename: str) -> tuple:
    """(HLS再生dir, 返してよいfile)。どちらも見つからなければNone。

    dirの解決はTTL cacheを通す(再生の間ずっと同じ答えを返すため)。file側は毎回statする —
    束ね直しでsegmentは実際に入れ替わるので、そこを覚えると消えたfileを指し続ける。"""
    hls_dir = fsfacts.recording_hls_dir(recording)
    if hls_dir is None:
        return None, None
    return hls_dir, files._hls_member(hls_dir, filename)


@router.get("/api/recordings/{recording_id}/hls/{filename}")
async def recording_hls(recording_id: int, filename: str) -> Response:
    """確定録画のHLS playlist / segmentを返す。

    playlistは読み込んだ本文を返す(FileResponseはstat時のsizeでContent-Lengthを決めるため、
    録画中のように追記され得るfileでは実体長と食い違う)。segmentはFileResponseで返して
    Range要求に応える — 束ね済み録画のplaylistは ``#EXT-X-BYTERANGE`` で1本のpack*.tsの中を
    指すので、範囲取得が効かないと再生できない。

    行の取得はread接続から引く。ここは再生中ずっと毎秒叩かれる唯一のrouteで、writer接続で
    引いていた頃はlock待ちがこのrouteの所要時間の40%(最悪1本で9.4秒)を占めていた。

    dirの解決とfileの実在確認もthreadで行う。segment 1本ごとにrecord rootの数だけ
    is_dir・素材のglob・statを起こしており、それがloop上に残っていた。"""
    recording = await asyncio.to_thread(
        runtime.storage.get_recording_for_read, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    hls_dir, path = await asyncio.to_thread(_hls_target, recording, filename)
    if hls_dir is None:
        raise HTTPException(status_code=404, detail="この録画は.tsが残っていません。")
    if path is None:
        raise HTTPException(status_code=404, detail="HLS fileが見つかりません。")
    if path.suffix == ".m3u8":
        if recording["status"] != "recording":
            text = await asyncio.to_thread(files._finalized_playlist, recording, hls_dir)
            if text is None:
                raise HTTPException(status_code=404, detail="再生できるsegmentがありません。")
        else:
            text = await asyncio.to_thread(
                path.read_text, encoding="utf-8", errors="replace")
        # playlistは束ね直し(hls_pack)で中身が入れ替わるので持たせない。segmentのbytesは
        # 確定録画では変わらないため、そちらだけcacheさせる。
        return Response(content=text, media_type="application/vnd.apple.mpegurl",
                        headers={"Cache-Control": "no-cache"})
    if recording["status"] == "recording":
        headers = {"Cache-Control": "no-cache"}
    else:
        headers = {"Cache-Control": f"private, max-age={runtime.RECORDING_CACHE_MAX_AGE_SECONDS}"}
    return FileResponse(path, media_type="video/mp2t", headers=headers)


@router.get("/api/recordings/{recording_id}/transcript")
async def get_transcript_api(recording_id: int) -> dict:
    if await asyncio.to_thread(runtime.storage.get_recording, recording_id) is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    transcript = await asyncio.to_thread(runtime.storage.get_transcript, recording_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="この録画の文字起こしはまだありません。")
    return transcript


def _transcript_basename(recording: dict) -> str:
    """字幕fileのbase名。録画file名と揃えるとNLEで動画と自動で紐づく。

    中断録画のpathはmp4ではなくrecord dir自体を指すことがあるため、stemはfilename優先で
    取り、それも無ければrecording idで代用する(pathからstemを引くと'recordings'になる)。"""
    name = (recording.get("filename") or "").strip()
    if name:
        return Path(name).stem
    return f"recording_{recording['id']}"


@router.get("/api/recordings/{recording_id}/transcript/export")
async def export_transcript_api(recording_id: int, format: str = "srt") -> Response:
    """転写を字幕file(SRT/VTT)または素のtextで書き出す。

    timecodeは元録画mp4のmedia軸(PTS)基準。焼き込み出力・Up出力は再encodeを挟むので、
    それらに対するPTS一致は保証しない。時刻mapが現行版でないtranscriptも書き出しは通すが、
    ズレている可能性を応答headerで明示する(外部で直せるsidecarなので拒否はしない)。"""
    if format not in subtitles.EXPORT_FORMATS:
        raise HTTPException(
            status_code=400,
            detail="formatはsrt・vtt・txtのいずれかを指定してください。",
        )
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    transcript = await asyncio.to_thread(runtime.storage.get_transcript, recording_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="この録画の文字起こしはまだありません。")
    # timecodeは元録画mp4のmedia軸なので、打ち切りもその実尺で測る(transcriptのdurationは
    # gapless長からの換算値で、実尺そのものではない)。ffprobeが無ければNone=打ち切らない。
    media_duration = await _duration_seconds(files._safe_recording_path(recording["path"]))
    body = subtitles.render(format, transcript, media_duration)
    if not body.strip():
        raise HTTPException(status_code=404, detail="書き出せるsegmentがありません。")
    suffix, media_type, encoding = subtitles.EXPORT_FORMATS[format]
    filename = _transcript_basename(recording) + suffix
    # 配信者IDに非ASCIIが混じるとheaderへ素で載せられないので、RFC 5987のfilename*を併記する。
    filename_star = quote(filename, safe="")
    stale = not subtitles.timemap_current(transcript.get("timemap_version"))
    runtime.logger.info(
        "転写を書き出しました: recording_id=%d format=%s segments=%d",
        recording_id, format, len(transcript.get("segments") or []),
        extra={"event": "subtitle.exported",
               "ctx": {"recording_id": recording_id, "format": format,
                       "timemap_version": transcript.get("timemap_version"),
                       "timemap_stale": stale,
                       "segments": len(transcript.get("segments") or [])}},
    )
    return Response(
        content=body.encode(encoding),
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename_star}",
            "X-Tictok-Timemap-Stale": "1" if stale else "0",
        },
    )


@router.get("/api/recordings/{recording_id}/comments")
async def get_recording_comments_api(recording_id: int) -> dict:
    """録画窓のcommentを動画時間軸で返す(player下段のcomment panel用)。

    search_hits(source=comment)をそのまま使う。video_timeはindex時にmp4 PTSへ変換済みで
    焼き込み・検索hitと同じ軸なので、ここで時刻変換を挟まずに再生位置と突き合わせられる。
    index未構築の録画は起動時のbackfillが埋めるため、ここでは空で返る。"""
    if await asyncio.to_thread(runtime.storage.get_recording, recording_id) is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    rows = await asyncio.to_thread(
        runtime.storage.search_hits_for, recording_id, indexer.SOURCE_COMMENT)
    return {
        "recording_id": recording_id,
        "items": [
            {"id": row["id"], "t": row["video_time"],
             "nickname": row["nickname"], "body": row["body"]}
            for row in rows
        ],
    }


@router.post("/api/recordings/{recording_id}/transcribe")
async def transcribe_recording(recording_id: int) -> dict:
    """Run local STT over a finished recording and cache the transcript. Progress is
    broadcast over the websocket as transcribe_progress while segments decode."""
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    path = files._resolved_recording_path(recording)
    # queue経路(transcribe_queue)と同じ条件・同じ入力にする。あちらは hls_source で .ts を
    # 読めるのに、単発だけがmp4を要求していたため、同じ録画がqueueなら転写できて録画詳細の
    # buttonからは404という食い違いになっていた。
    if not files._recording_source_exists(recording):
        raise HTTPException(status_code=404, detail="録画fileが存在しません。")
    loop = asyncio.get_running_loop()
    async with runtime._tracked_job("stt", f"文字起こし {path.stem}", recording_id=recording_id,
                            session_id=recording.get("session_id")) as job_id:
        async def _report(pct: int) -> None:
            await runtime.hub.broadcast(
                {"type": "transcribe_progress", "recording_id": recording_id, "pct": pct}
            )
            await runtime.jobs.progress(job_id, pct, stage="文字起こし")

        def on_progress(done: float, total: float) -> None:
            pct = min(100, int(done / total * 100)) if total > 0 else 0
            asyncio.run_coroutine_threadsafe(_report(pct), loop)

        try:
            async with runtime._job_ops("stt", recording_id, stem=path.stem,
                                job_registry_id=job_id):
                # mp4が無い録画は.tsのHLSから転写する(transcribe_queueと同じ貸し出し方)。
                async with hls_source.ffmpeg_source_async(path) as source:
                    result = await asyncio.to_thread(
                        stt_transcribe, str(source.path), on_progress)
        except STTError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        await asyncio.to_thread(runtime.storage.save_transcript, recording_id, result)
        # 保存と同時に検索indexへ反映する。ここを省くと単発転写した録画だけが検索に出ない。
        await asyncio.to_thread(indexer.index_transcript, runtime.storage, recording)
        await _report(100)
    return {
        "recording_id": recording_id,
        "language": result["language"],
        "model": result["model"],
        "duration": result["duration"],
        "text": result["text"],
        "segments": result["segments"],
        "segments_count": len(result["segments"]),
    }


@router.get("/api/recordings/{recording_id}/path")
async def recording_path_api(recording_id: int) -> dict:
    """編集ソフトへ渡すための実file path。録画本体に加え、焼き込み・高画質化の出力が
    あればそれらのpathも返す(素材としてどれを使うかは利用者が選ぶ)。

    ``exists`` はmp4の有無ではなく**この録画の実体の有無**である。mp4だけを見ていた頃は、
    素材が丸ごと残っている録画に対して画面が「動画fileは削除されています」「元録画が
    ありません」と出していた。``media`` で実体が .ts かmp4かを名乗り、素材しか無い録画では
    渡すpathもsession dir(seg*.ts)にする — 実在しないmp4 pathを「録画本体」として渡すと、
    編集ソフトで開けないpathを掴ませることになる。"""
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    path = files._resolved_recording_path(recording)
    found = files._variant_paths(path, recording)
    media_dirs = files._recording_media_dirs(recording)
    source_media = "mp4" if path.is_file() else ("ts" if media_dirs else "")
    source_path = path if path.is_file() else (media_dirs[0] if media_dirs else path)
    # ``media`` は録画の実体一覧(list)、``media_kind`` はその版1つの実体(str)。同じ名前で
    # 形を変えると受け手が取り違えるので、endpoint間で名前と形を対応させる。
    variants = []
    if "source" in found:
        variants.append({"kind": "source", "path": str(source_path),
                         "exists": True, "media_kind": source_media})
    variants += [{"kind": kind, "path": str(found[kind]), "exists": True, "media_kind": "mp4"}
                 for kind in files.CLIP_VARIANTS if kind != "source" and kind in found]
    # 確認状態もここで返す。録画を開くたびに必ず引くendpointなので、再生画面の印を
    # 出すためだけの往復を増やさずに済む(検索hit経由で開いた録画は一覧の値を持たない)。
    return {"recording_id": recording_id, "path": str(source_path),
            "exists": files._recording_source_exists(recording),
            "media": files._recording_media_kinds(recording), "variants": variants,
            "review_state": recording.get("review_state") or REVIEW_UNCHECKED}


@router.get("/api/recordings/{recording_id}/locate")
async def recording_locate_api(recording_id: int, at: float) -> dict:
    """壁時計の時刻(epoch秒)が、この録画の何秒地点かを返す(Battle履歴から対戦の場面へ
    飛ぶための変換)。

    生の ``at - started_at`` を使ってはならない。event側の壁時計と録画の時間軸は、起動
    latency・再接続の穴・mux分だけずれ続ける。heat barや検索hitと同じmapperを通すことで、
    同じplayerの上で同じ位置を指す。"""
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    path = files._resolved_recording_path(recording)
    to_pts = await asyncio.to_thread(
        indexer.build_time_mapper_sync, path, recording["started_at"], recording.get("ended_at"))
    return {"recording_id": recording_id, "at": at,
            "video_time": round(max(0.0, to_pts(at)), 2)}


@router.get("/api/recordings/{recording_id}/heat")
async def recording_heat_api(recording_id: int) -> dict:
    """録画窓のcomment/gift密度を動画時間軸へ載せて返す(seek bar下のheat bar用)。

    bucketの時刻はwall-clockなので、commentのindexと同じmapperで動画時間へ変換する。
    ここで生の差分を使うと焼き込み動画とheatの位置がずれる。"""
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    session_id = recording.get("session_id")
    if session_id is None:
        return {"recording_id": recording_id, "points": []}
    path = files._resolved_recording_path(recording)
    started_at = recording["started_at"]
    ended_at = recording.get("ended_at")
    to_pts = await asyncio.to_thread(
        indexer.build_time_mapper_sync, path, started_at, ended_at)
    buckets = await asyncio.to_thread(
        runtime.storage.session_buckets,
        session_id,
        started_at,
        ended_at,
    )
    points = [
        {
            "t": round(to_pts(bucket["start"]), 2),
            "comments": bucket["comments"],
            "gifts": bucket["gifts"],
            "diamonds": bucket["diamonds"],
            "likes": bucket["likes"],
            "viewers": bucket["viewers"],
        }
        for bucket in buckets
    ]
    return {"recording_id": recording_id, "points": points}


class _MaterialMetric(NamedTuple):
    """素材(録画そのもの)を解析して各bucketへ載せるper-bucket指標の登録項。

    diamonds/comments/laugh_commentはDBのeventだけで作れるが、音声・映像から作る指標は
    「有効かを設定で見る → 解析engineを回す → 判定できない録画では外す → 重みと下限を
    設定から引く」という同じ4手順を必ず踏む。指標ごとに候補APIの本体へifを積むと、
    その4手順が少しずつ違う枝に分かれて失敗の扱いが揃わなくなるため、登録表で持つ。

    ``attach`` は値を載せられたら None を、載せられなかったら理由(logのctx)を返す。
    載せられない場合に0で埋めてはならない — 「笑っていなかった」という観測を捏造する。
    """

    key: str
    setting: str
    weight_setting: str
    min_setting: str
    # どちらも呼ぶためのもの。``object`` のままだと型検査が「呼べない」と言う。
    label: Callable[[dict], str]
    attach: Callable[..., Awaitable[Optional[dict]]]


async def _attach_laugh_audio(path: Path, buckets: list, bucket_seconds: int,
                              to_pts) -> Optional[dict]:
    """各bucketへ ``laugh_audio``(窓内で笑い声が出ていた秒数)を載せる。

    確率列は動画時間軸なので、bucketの窓をwall-clockから動画時間へ写してから引く
    (audio_peakと同じ理由: 生の差分を使うと焼き込み動画とずれる)。

    modelが未配置・未導入のときは ``LaughAudioError`` がそのまま上がる。ここで捕まえて
    笑い抜きの候補を返すと、利用者は「笑いの無い配信」と読む — 呼び出し側で503にする。

    ``clip_candidate_laugh_audio_solo_only`` が立っていれば、画面に顔が2つ以上映って
    いる間の笑い声を数えない。コラボ中の笑いは共演者のものかもしれず、どの顔が配信者かを
    画面から決める手段が無いため(smile module docstringと同じ制約)。窓は映像から作る —
    DBの ``collab_windows`` はLinkMic channelの有無であって人数ではなく、実測で
    ``guests_max`` が811窓中805窓で0のままだった。
    """
    profile = await laugh_audio.ensure_laugh_profile(path)
    exclude_spans = None
    if int(runtime.settings.get("clip_candidate_laugh_audio_solo_only")):
        # 顔検出のmodelが無ければ SmileError がそのまま上がる。ここで黙って除外なしに
        # 落とすと、「コラボを外した候補」として外れていない候補を渡すことになる。
        faces_profile = await smile.ensure_smile_profile(path)
        exclude_spans = smile.multi_face_spans(faces_profile)
    seconds = [
        laugh_audio.laugh_seconds(profile, to_pts(bucket["start"]),
                                  to_pts(bucket["start"] + bucket_seconds),
                                  exclude_spans=exclude_spans)
        for bucket in buckets
    ]
    outside = next((i for i, value in enumerate(seconds) if value is None), None)
    if outside is not None:
        return {"bucket_start": buckets[outside]["start"],
                "laugh_duration_seconds": profile["duration_seconds"]}
    for bucket, value in zip(buckets, seconds):
        bucket["laugh_audio"] = value
    return None


async def _attach_smile(path: Path, buckets: list, bucket_seconds: int,
                        to_pts) -> Optional[dict]:
    """各bucketへ ``smile``(窓内で笑顔と判定できた秒数)を載せる。

    ``laugh_audio`` と同じく動画時間軸なので、bucketの窓を写してから引く。

    「笑顔」と名乗れるのは**顔がちょうど1つ映っている標本だけ**である(smile module
    docstring: 配信者を画面から特定する手段が無く、battle・collabでは複数の顔が映る)。
    判定できない標本は数えないので、そういう区間の値は実際より小さく出る。
    """
    profile = await smile.ensure_smile_profile(path)
    seconds = [
        smile.smile_seconds(profile, to_pts(bucket["start"]),
                            to_pts(bucket["start"] + bucket_seconds))
        for bucket in buckets
    ]
    outside = next((i for i, value in enumerate(seconds) if value is None), None)
    if outside is not None:
        return {"bucket_start": buckets[outside]["start"],
                "smile_duration_seconds": profile["duration_seconds"]}
    for bucket, value in zip(buckets, seconds):
        bucket["smile"] = value
    return None


# 素材由来のper-bucket指標。足すときはengine側を書いてからここへ1 entry追加する。
_MATERIAL_METRICS = (
    _MaterialMetric(
        key="laugh_audio",
        setting="clip_candidate_laugh_audio",
        weight_setting="clip_candidate_laugh_audio_weight",
        min_setting="clip_candidate_laugh_audio_min_seconds",
        label=lambda item: f"笑い声{item['laugh_audio']:g}秒",
        attach=_attach_laugh_audio,
    ),
    _MaterialMetric(
        key="smile",
        setting="clip_candidate_smile",
        weight_setting="clip_candidate_smile_weight",
        min_setting="clip_candidate_smile_min_seconds",
        label=lambda item: f"笑顔{item['smile']:g}秒",
        attach=_attach_smile,
    ),
)

# 候補badgeの文言。指標を足したらここも足すこと(素通りするとKeyErrorで気付ける)。
_CANDIDATE_LABELS = {
    "diamonds": lambda item: f"ダイヤ{item['diamonds']}",
    "comments": lambda item: f"コメント{item['comments']}",
    "audio_peak": lambda item: "音量",
    "laugh_comment": lambda item: f"笑い{item['laugh_comment']}",
    **{metric.key: metric.label for metric in _MATERIAL_METRICS},
}
# 窓が重なった候補を畳むときに、代表となった窓から引き継ぐkey。
_CANDIDATE_REPRESENTATIVE_KEYS = (
    "zscore", "metric", "diamonds", "comments", "ratio", "silent_ratio", "laugh_comment",
    *(metric.key for metric in _MATERIAL_METRICS),
)


def _attach_laugh_comments(session_id: int, buckets: list, bucket_seconds: int) -> None:
    """各bucketへ ``laugh_comment``(笑いcommentの件数)を載せる。

    bucketsへ列を足さないのは、判定patternを運用しながら調整するものだからで、patternを
    変えるたびにschema migrationと全session backfillが要る設計は誤りである。3時間・comment
    2万件でも正規表現の走査は数十msで済む。

    丸めは ``CAST(time / bs) * bs``(storage._rebuild_buckets_locked)と同じ式を使う。
    独自に丸めると既存bucketと1つずれる。
    """
    compiled = laugh_text.compile_patterns(min_w_run=get_laugh_comment_min_w_run())
    starts = {b["start"] for b in buckets}
    counts: dict = {}
    bodies = []
    rows = []
    for event in runtime.storage.iter_events(session_id, kinds=("comment",)):
        # 旧録画は text 列に入っている(storage側もCOALESCEで両方見ている)。
        body = (event.get("comment") or event.get("text") or "").strip()
        if not body:
            continue
        rows.append((int(event["time"] // bucket_seconds) * bucket_seconds, body))
        bodies.append(body)
    templates = laugh_text.template_bodies(bodies)
    for start, body in rows:
        if start not in starts or body in templates:
            continue
        if laugh_text.classify(body, compiled) is not None:
            counts[start] = counts.get(start, 0) + 1
    for bucket in buckets:
        bucket["laugh_comment"] = counts.get(bucket["start"], 0)


async def _attach_material_metrics(recording_id: int, path: Path, buckets: list,
                                   bucket_seconds: int, to_pts, metrics: tuple,
                                   weights: dict, min_values: dict) -> tuple:
    """有効になっている素材由来の指標を各bucketへ載せ、判定に使うmetricsを返した上で
    ``weights`` / ``min_values`` へその指標ぶんを書き込む。

    下限(min_values)は指標ごとに必須である。素材由来の指標はどれもほとんどの窓で0なので、
    下限が無いとごく僅かな検出が大きなz-scoreを叩いて候補を占領する(spike.detect_spikes)。
    """
    for metric in _MATERIAL_METRICS:
        if not int(runtime.settings.get(metric.setting)):
            continue
        try:
            skipped = await metric.attach(path, buckets, bucket_seconds, to_pts)
        except hls_source.SourceMissing as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except RuntimeError as exc:
            # 有効なのに解析できない(model未配置・engine未導入・解析失敗)ならここで失敗を
            # 返す。黙って先へ進めると「その指標では盛り上がりが無かった」結果と見分けが
            # 付かず、笑いを見ているつもりで見ていない候補一覧を渡すことになる。
            raise HTTPException(status_code=503, detail=str(exc))
        if skipped is not None:
            runtime.logger.info(
                "切り抜き候補: %s の指標をrecording %s では判定から外しました"
                "（解析した素材の外に出るbucketがあります）", metric.key, recording_id,
                extra={"event": "clip.material_metric_skipped",
                       "ctx": {"recording_id": recording_id, "metric": metric.key,
                               **skipped}},
            )
            continue
        metrics = metrics + (metric.key,)
        weights[metric.key] = float(runtime.settings.get(metric.weight_setting))
        min_values[metric.key] = float(runtime.settings.get(metric.min_setting))
    return metrics


def _merge_candidates(items: list) -> list:
    """時刻順に並んだ候補のうち、範囲が重なるものを1つへ畳む。移動窓は1 bucketずつずれた
    窓を連続で拾うため、畳まないと同じ盛り上がりが何本ものclipになる。"""
    merged: list = []
    for item in sorted(items, key=lambda c: c["start"]):
        if merged and item["start"] <= merged[-1]["end"]:
            prev = merged[-1]
            prev["end"] = max(prev["end"], item["end"])
            if item["zscore"] > prev["zscore"]:
                # 代表値は最も外れている窓のものを残す(合算すると窓の重なりを二重に数える)。
                prev.update({k: item[k] for k in _CANDIDATE_REPRESENTATIVE_KEYS
                             if k in item})
            continue
        merged.append(dict(item))
    return merged


@router.get("/api/recordings/{recording_id}/clip-candidates")
async def recording_clip_candidates_api(recording_id: int) -> dict:
    """録画窓の盛り上がりから切り出し候補を出す。時刻は動画時間軸(秒)。

    判定は core.spike で、窓だけを設定の秒数へ広げる。窓に入るbucket数はsessionのbucket幅から導くので、bucket幅の違う
    session間でも窓の実長は揃う。"""
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    window_seconds = int(runtime.settings.get("clip_candidate_window_seconds"))
    pad_before = int(runtime.settings.get("clip_pad_before_seconds"))
    pad_after = int(runtime.settings.get("clip_pad_after_seconds"))
    lead = int(runtime.settings.get("clip_candidate_lead_seconds"))
    empty = {"recording_id": recording_id, "window_seconds": window_seconds,
             "pad_before_seconds": pad_before, "pad_after_seconds": pad_after,
             "lead_seconds": lead, "candidates": []}
    session_id = recording.get("session_id")
    if session_id is None:
        return empty
    session = await asyncio.to_thread(runtime.storage.get_session, session_id)
    if session is None:
        return empty
    bucket_seconds = session.get("bucket_seconds")
    if not bucket_seconds:
        # bucket幅が無いsessionは窓のbucket数を出せない。推測で埋めると窓の実長が嘘になる。
        return empty
    started_at = recording["started_at"]
    ended_at = recording.get("ended_at")
    buckets = await asyncio.to_thread(
        runtime.storage.session_buckets,
        session_id,
        started_at,
        ended_at,
    )
    window_buckets = spike.window_bucket_count(bucket_seconds, window_seconds)
    path = files._resolved_recording_path(recording)
    to_pts = await asyncio.to_thread(
        indexer.build_time_mapper_sync, path, started_at, ended_at)
    # 指標は設定で増える(音声・映像・笑い)。要素数まで固定した型にすると、
    # 足すたびに型が変わったと言われる。
    metrics: tuple = spike.METRICS
    profile = None
    if int(runtime.settings.get("clip_candidate_audio")):
        try:
            profile = await ensure_audio_profile(path)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        # 音声は動画時間軸なので、各bucketの窓を動画時間へ写してからpeakを引く。
        # 録画の外へ落ちるbucketがあるとlevelの取れない窓ができるため、その録画では
        # 音声を判定から外す(0で埋めると「無音だった」という観測を作ってしまう)。
        outside = next((b for b in buckets
                        if level_peak(profile, to_pts(b["start"]),
                                      to_pts(b["start"] + bucket_seconds)) is None), None)
        if outside is None:
            for bucket in buckets:
                bucket["audio_peak"] = level_peak(
                    profile, to_pts(bucket["start"]),
                    to_pts(bucket["start"] + bucket_seconds))
            metrics = metrics + ("audio_peak",)
        else:
            runtime.logger.info(
                "切り抜き候補: 音声の指標をrecording %s では判定から外しました"
                "（録音の外に出るbucketがあります）", recording_id,
                extra={"event": "clip.audio_metric_skipped",
                       "ctx": {"recording_id": recording_id,
                               "bucket_start": outside["start"],
                               "audio_duration_seconds": profile["duration_seconds"]}},
            )
    weights: dict = {}
    min_values: dict = {}
    if int(runtime.settings.get("clip_candidate_laugh_comment")):
        await asyncio.to_thread(
            _attach_laugh_comments, session_id, buckets, bucket_seconds)
        metrics = metrics + ("laugh_comment",)
        weights["laugh_comment"] = float(runtime.settings.get("clip_candidate_laugh_weight"))
        # 笑いの系列はほぼ全てが0で標準偏差が極小になるため、下限を置かないと
        # 「ほとんど笑わない配信のたった1件」がzを叩いて候補を占領する。
        min_values["laugh_comment"] = float(
            runtime.settings.get("clip_candidate_laugh_min_comments"))
    metrics = await _attach_material_metrics(
        recording_id, path, buckets, bucket_seconds, to_pts, metrics, weights, min_values)
    found = spike.detect_spikes(
        buckets, window_buckets=window_buckets, metrics=metrics,
        zscore_min=float(runtime.settings.get("clip_candidate_zscore")),
        weights=weights or None, min_values=min_values or None)
    if not found:
        return empty
    video_seconds = await _duration_seconds(path)
    span = bucket_seconds * window_buckets
    items = []
    for candidate in found:
        start = to_pts(candidate["start"]) - lead - pad_before
        end = to_pts(candidate["start"] + span) + pad_after
        start = max(0.0, start)
        if video_seconds is not None:
            end = min(end, video_seconds)
        if end <= start:
            continue
        item = {
            "start": round(start, 2),
            "end": round(end, 2),
            "zscore": round(candidate["zscore"], 2),
            "metric": candidate["metric"],
            "ratio": round(candidate["ratio"], 2),
            "diamonds": int(candidate["values"]["diamonds"]),
            "comments": int(candidate["values"]["comments"]),
            # 生値を並記する。「なぜこの候補なのか」をその場で反証できる状態にしておく
            # (候補が的外れでも気付きにくい種類の機能なので、表示は検証手段でもある)。
            "laugh_comment": int(candidate["values"].get("laugh_comment", 0)),
        }
        # 素材由来の指標は、載せられた録画にだけkeyを付ける。判定していない録画でも0を
        # 入れると、画面には「笑い声0秒」と出て検出していないことが読めなくなる。
        for metric in _MATERIAL_METRICS:
            if metric.key in candidate["values"]:
                item[metric.key] = round(float(candidate["values"][metric.key]), 2)
        items.append(item)
    merged = _merge_candidates(items)
    merged.sort(key=lambda c: c["zscore"], reverse=True)
    limit = int(runtime.settings.get("clip_candidate_limit"))
    for item in merged:
        item["label"] = _CANDIDATE_LABELS[item["metric"]](item)
        if profile is not None:
            # 無音割合は畳んだ後の区間で測る。代表窓の値を引き継ぐと、窓が伸びた分の
            # 無音が数に入らず実態とずれる。判定できなければNoneのまま。
            item["silent_ratio"] = silent_ratio(profile, item["start"], item["end"])
    return {**empty, "candidates": merged[:limit]}


@router.get("/api/recordings/{recording_id}/waveform")
async def recording_waveform_api(recording_id: int) -> dict:
    """seek bar用の音声波形。無音・BGM・発話の区別が付くので切り所の判断に使う。

    解像度はserver側の時間刻み(waveform.WAVE_BUCKET_SECONDS)で固定。拡大表示は同じ列を
    画面側で畳んで使う(別解像度を要求させると録画全体のdecodeがやり直しになる)。
    無音区間(silences)も同梱する — snapとシーン選択の吸着先で、profileは波形と同じ
    decodeから既にcacheされているため追加costは無い。

    初回はcontainerを丸ごと読むため長尺(3.9時間)で90秒級かかる。画面側は波形checkboxが
    ONのときだけ呼ぶこと(OFFの利用者の録画openで走らせるとdiskを占有する)。"""
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    path = files._resolved_recording_path(recording)
    # 判定は素材まで含める。waveformは hls_source 経由で .ts を読める(media/waveform.py)
    # ので、mp4の有無で断ると新しい録画すべてで波形が出ない。
    if not files._recording_source_exists(recording):
        raise HTTPException(status_code=404, detail="録画fileが存在しません。")
    try:
        result = await ensure_waveform(path)
        profile = await ensure_audio_profile(path)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    result["silences"] = silence_spans(profile)
    result["recording_id"] = recording_id
    return result


@router.get("/api/recordings/{recording_id}/thumbnails")
async def recording_thumbnails_api(recording_id: int) -> dict:
    """seek bar hover用のsprite sheetを用意して仕様を返す。

    3時間級の録画では初回生成に十数秒かかる(keyframeのみのdecodeでも尺なりの読み込みが
    要る)ため、hoverの瞬間ではなく録画を開いた時点で呼ぶこと。2回目以降はcache hitで即返る。"""
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    path = files._resolved_recording_path(recording)
    # 波形と同じ理由で素材まで見る(media/thumbnails.py は hls_source 経由)。
    if not files._recording_source_exists(recording):
        raise HTTPException(status_code=404, detail="録画fileが存在しません。")
    try:
        spec = await ensure_sprite(path)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    spec["recording_id"] = recording_id
    spec["url"] = f"/api/recordings/{recording_id}/thumbnails.jpg"
    spec.pop("path", None)
    return spec


@router.get("/api/recordings/{recording_id}/thumbnails.jpg")
async def recording_thumbnails_image(recording_id: int) -> FileResponse:
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    sprite = sprite_path(files._resolved_recording_path(recording))
    if not sprite.is_file():
        raise HTTPException(status_code=404, detail="sprite未生成です。")
    return FileResponse(
        sprite, media_type="image/jpeg",
        headers={"Cache-Control": f"private, max-age={runtime.RECORDING_CACHE_MAX_AGE_SECONDS}"},
    )


@router.delete("/api/recordings/{recording_id}")
async def delete_recording(recording_id: int) -> dict:
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    if recording["status"] == "recording":
        raise HTTPException(status_code=409, detail="録画中のfileは削除できません。先に停止してください。")
    path = files._safe_recording_path(recording["path"])

    # 素材のsession dirは束ね前で数千fileある(実測で最大11,285)。走査もrmtreeもloop上で
    # 回すと、1本消す間serverが丸ごと止まる。
    def _remove() -> None:
        try:
            if path.is_file():
                path.unlink()
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"file削除に失敗しました: {exc}")
        cleanup_overlay_files(path)
        cleanup_upscale_files(path)
        files._unlink_quietly(files._recording_cache_paths(path))
        files._remove_recording_ts(recording)

    await asyncio.to_thread(_remove)
    await asyncio.to_thread(runtime.storage.delete_recording, recording_id)
    return {"deleted": recording_id}
