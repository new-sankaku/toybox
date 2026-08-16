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
from tictok.core.battle import battle_type, gift_window_end, gift_window_fallback_duration
from tictok.core.config import get_laugh_comment_min_w_run
from tictok.core import laugh_text
from tictok.record.recorder import ffmpeg_available
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
from tictok.api import battles
from tictok.api import candidates
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
    ができず、当たる語を先に発明する必要がある。文字起こしの有無まで返すのは、文字起こしが無い
    録画は検索でそもそも当たらず、一覧側で見分けられないと選びようがないため。

    笑い声は合計秒・窓の数と、**indexを張った条件**まで返す。並べ替えの根拠としてだけ
    でなく、0秒が「笑っていない」なのか「まだ解析していない」なのかを画面が見分けるのに
    要る(条件を持たない録画は後者、または共演中を外す前に張ったindexである)。"""
    handle = runtime._normalize_unique_id(unique_id) if unique_id else None

    def _collect() -> list:
        transcribed = runtime.storage.transcribed_recording_ids()
        laughs = runtime.storage.laugh_totals_by_recording()
        laugh_meta = runtime.storage.laugh_index_meta_map()
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
            # 実体が無い録画も行は残す。文字起こし・検索・bookmarkはそのまま使えるので、
            # 一覧から消すとその録画へ辿る道が無くなる。開けないことは``media``が空である
            # ことで画面が示す(消すのではなく、何が在るかを名乗らせる)。
            media = kinds_by_id.get(rec["id"], [])
            laugh = laughs.get(rec["id"])
            meta = laugh_meta.get(rec["id"]) or {}
            # 笑い声。解析した記録も行も無い録画は0ではなくNULLで返す ―― 未解析と
            # 「解析して0件」を同じ0にすると、並べ替えの末尾が両者の混ざった塊になる。
            analysed = bool(laugh or meta)
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
                "laugh_seconds": (laugh or {}).get("seconds", 0.0) if analysed else None,
                "laugh_windows": (laugh or {}).get("windows", 0) if analysed else None,
                # indexを張ったときの共演の除外条件。未記録(=NULL)なら、この仕組みより
                # 前に張ったindexで、共演中の笑い声がそのまま入っている。
                "laugh_exclude": meta.get("mode"),
                # 現行ruleでコラボを観測できた時期のsessionか。Falseなら記録が無いので
                # 1秒も外れていない(「コラボが無かった」ではない)。
                "laugh_collab_observed": meta.get("collab_observed"),
                "laugh_excluded_seconds": (
                    round(meta["collab_seconds"] + meta["battle_seconds"], 2)
                    if "collab_seconds" in meta else None),
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


class TranscriptCorrection(BaseModel):
    """1件の訂正。``start`` と ``src`` の組がその発話の身元になる。"""

    start: float
    src: str
    dst: str
    origin: str = "human"
    confidence: Optional[str] = None
    note: Optional[str] = None


class TranscriptCorrectionsRequest(BaseModel):
    corrections: list[TranscriptCorrection]


class TranscriptCorrectionStateRequest(BaseModel):
    ids: list[int]
    state: str


@router.get("/api/recordings/{recording_id}/transcript/corrections")
async def list_transcript_corrections_api(recording_id: int,
                                          include_discarded: bool = False) -> dict:
    """この録画の訂正。``orphan`` は再文字起こしで貼り直せなかったもの。

    保留を件数ではなく中身で返すのは、人が「どこへ当てるはずだったか」を見て手当てするか
    捨てるかを決めるため。機械が近い行へ寄せることはしない。"""
    if await asyncio.to_thread(runtime.storage.get_recording, recording_id) is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    states = ("active", "orphan", "discarded") if include_discarded else ("active", "orphan")
    rows = await asyncio.to_thread(
        runtime.storage.list_corrections, recording_id, states)
    return {
        "recording_id": recording_id,
        "corrections": rows,
        "active": sum(1 for row in rows if row["state"] == "active"),
        "orphan": sum(1 for row in rows if row["state"] == "orphan"),
    }


@router.post("/api/recordings/{recording_id}/transcript/corrections")
async def upsert_transcript_corrections_api(
        recording_id: int, payload: TranscriptCorrectionsRequest) -> dict:
    """訂正をまとめて入れる。同じ (start, src) は上書きなので、何度流しても同じ状態になる。

    入れた瞬間から字幕の書き出し・切り抜き字幕・焼き込み・検索が訂正後の文字を使う
    (すべて ``get_transcript`` を通るため)。**既存の検索indexは張り直しが要る** — 索引は
    文字列を写し取った別の行で、重ね合わせは通らない。"""
    if await asyncio.to_thread(runtime.storage.get_recording, recording_id) is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    if await asyncio.to_thread(
            runtime.storage.get_transcript, recording_id, True) is None:
        raise HTTPException(status_code=404, detail="この録画の文字起こしはまだありません。")
    try:
        result = await asyncio.to_thread(
            runtime.storage.upsert_corrections, recording_id,
            [row.model_dump() for row in payload.corrections])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    transcript = await asyncio.to_thread(runtime.storage.get_transcript, recording_id)
    return {"recording_id": recording_id, **result,
            "applied": transcript.get("corrections_applied", 0)}


@router.patch("/api/recordings/{recording_id}/transcript/corrections")
async def set_transcript_correction_state_api(
        recording_id: int, payload: TranscriptCorrectionStateRequest) -> dict:
    """訂正の状態を変える(適用/保留/破棄)。破棄しても行は消さない — 後から戻せるように。"""
    if await asyncio.to_thread(runtime.storage.get_recording, recording_id) is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    try:
        changed = await asyncio.to_thread(
            runtime.storage.set_correction_state, payload.ids, payload.state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"recording_id": recording_id, "changed": changed, "state": payload.state}


@router.delete("/api/recordings/{recording_id}/transcript/corrections/{correction_id}")
async def delete_transcript_correction_api(recording_id: int,
                                           correction_id: int) -> dict:
    """入れ間違えた訂正を本当に消す(取り消しの既定は破棄であって削除ではない)。"""
    removed = await asyncio.to_thread(
        runtime.storage.delete_correction, correction_id)
    if not removed:
        raise HTTPException(status_code=404, detail="訂正が見つかりません。")
    return {"recording_id": recording_id, "correction_id": correction_id, "deleted": True}


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
    """文字起こしを字幕file(SRT/VTT)または素のtextで書き出す。

    timecodeは元録画mp4のmedia軸(PTS)基準。焼き込み出力・Up出力は再encodeを挟むので、
    それらに対するPTS一致は保証しない。時刻mapが現行版でないtranscriptも書き出しは通すが、
    ズレている可能性を応答headerで明示する(外部で直せるsidecarなので拒否はしない)。

    SRT/VTTは語の時刻で表示単位へ割る(``subtitles.render``)。割らないとsegmentの終端が次の
    segmentの開始まで伸び、間の無音までcueに入る。txtは原稿として使う書式なので割らない。"""
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
    body = subtitles.render(format, transcript, media_duration, runtime.settings)
    if not body.strip():
        raise HTTPException(status_code=404, detail="書き出せるsegmentがありません。")
    suffix, media_type, encoding = subtitles.EXPORT_FORMATS[format]
    filename = _transcript_basename(recording) + suffix
    # 配信者IDに非ASCIIが混じるとheaderへ素で載せられないので、RFC 5987のfilename*を併記する。
    filename_star = quote(filename, safe="")
    stale = not subtitles.timemap_current(transcript.get("timemap_version"))
    runtime.logger.info(
        "文字起こしを書き出しました: recording_id=%d format=%s segments=%d",
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


def _battle_wall_window(battle: dict) -> Optional[tuple]:
    """Battleが壁時計のどの区間かを (start, end) で返す。窓を持たないrecordはNone。

    始点はscore_seriesの1点目を優先する(start_timeはTikTokのbattle settingが持つserver
    時刻で、seriesのtは受信側時計。片方だけを使うと録画との突合で系統的にずれる)。
    焼き込みの窓解決(_battle_media_windows)と同じ決め方にしてある。"""
    series = battle.get("score_series") or []
    start = series[0].get("t") if series else battle.get("start_time")
    end = battle.get("end_time") or (series[-1].get("t") if series else None)
    if start is None or end is None:
        return None
    return start, end


def _battles_in_window(fought: list, started_at: float, ended_at) -> list:
    """録画窓に掛かるBattleを、seriesとgift窓つきで古い順に返す。

    ordinalは**session内の通し番号**(1戦目・2戦目…)で、録画に掛かった分だけを数え直す
    ことはしない — 1 sessionを複数本に録った2本目が「1戦目」を名乗ると、同じPKが録画に
    よって別の番号で呼ばれる。
    """
    upper = ended_at if ended_at is not None else float("inf")
    starts = sorted(b["start_time"] for b in fought if b.get("start_time") is not None)
    fallback = gift_window_fallback_duration(fought)
    ordered = sorted(fought, key=lambda b: b.get("start_time") or 0)
    out = []
    for ordinal, battle in enumerate(ordered, start=1):
        window = _battle_wall_window(battle)
        if window is None:
            continue
        start, end = window
        if end < started_at or start > upper:
            continue
        out.append({
            "battle": battle,
            "ordinal": ordinal,
            "start": start,
            "end": end,
            # giftの帰属窓はcore.battleのruleに従う(貢献集計と同じ窓でなければ、同じgiftが
            # 画面のpanelとBattle cardで別のPKのものとして数えられる)。
            "gift_window": (battle.get("start_time"), gift_window_end(battle, starts, fallback)),
        })
    return out


def _gift_battle_ordinal(entries: list, at: float):
    """gift 1件がどのPKの窓で飛んだか(session内の通し番号)。どのPKにも入らなければNone。

    窓は重ならない(gift_window_endが次のBattleの開始で閉じる)ので、最初に入った1つで
    決まる。進行中Battleの窓は開いたまま(end=None)なのでそれ以降は全てそのPKへ入る。

    battle_idではなくordinalで名指すのは、battle_idを持たない古いrecordが0で保存され、
    同じsessionに2件あると別のPKのgiftが1つのPKへ畳まれるため。"""
    for entry in entries:
        start, end = entry["gift_window"]
        if start is None or at < start:
            continue
        if end is None or at <= end:
            return entry["ordinal"]
    return None


def _battle_payload(entry: dict, to_pts, started_at: float, ended_at) -> dict:
    """1戦ぶんの表示data。時刻はすべて動画の秒(score推移をplayerの位置と重ねるため)。"""
    battle = entry["battle"]
    upper = ended_at if ended_at is not None else float("inf")
    participants = battle.get("participants") or []
    return {
        "battle_id": battle.get("battle_id") or 0,
        "ordinal": entry["ordinal"],
        "type": battle.get("type") or battle_type(participants),
        "start": round(max(0.0, to_pts(entry["start"])), 2),
        "end": round(max(0.0, to_pts(entry["end"])), 2),
        # 録画を跨いだPK。この録画には片側しか映っていないことを名乗らないと、途中から
        # 立ち上がる曲線が「そのPKの全体」に見える。
        "partial": bool(entry["start"] < started_at or entry["end"] > upper),
        "aborted": bool(battle.get("aborted")),
        "ongoing": bool(battle.get("ongoing")),
        "result": battle.get("result"),
        "own_score": int(battle.get("own_score") or 0),
        "opp_score": int(battle.get("opp_score") or 0),
        "opponents": [p.get("nickname") or p.get("unique_id") or ""
                      for p in participants if not p.get("is_own")],
        # 陣営(participant)。再生画面のスコアバーはこの分割で描く(1v1=2分割、個人マルチ=
        # 人数ぶん、チーム戦=チーム数)。ここのscoreは確定値で、再生位置での値はseriesの
        # partsから引く。nicknameは陣営の名乗り(barのhover)にしか使わない。
        "participants": [
            {"user_id": str(p.get("user_id") or ""),
             "nickname": p.get("nickname") or "",
             "unique_id": p.get("unique_id") or "",
             "is_own": bool(p.get("is_own")),
             "side": p.get("side"),
             "team_id": p.get("team_id"),
             "score": int(p.get("score") or 0)}
            for p in participants
        ],
        # 録画の窓の外のsampleは載せない。写像は録画の中の時刻にしか意味が無く、外側を
        # 渡すと0秒や末尾へ潰れた点が端にぶら下がる。
        "series": [
            {"t": round(to_pts(sample["t"]), 2),
             "own": int(sample.get("own") or 0), "opp": int(sample.get("opp") or 0),
             # その時刻の陣営別score。名前はparticipantsが持つので、sampleごとには
             # 繰り返さない(user_idと、陣営を決めるside/team_idだけを載せる)。
             # 記録側のkeyは"id"(collector._append_score_sample)で、participantsの
             # user_idと同じ値。画面が2つのkeyを覚えずに済むよう、ここで名前を揃える。
             "parts": [
                 {"user_id": str(part.get("id") or ""),
                  "score": int(part.get("score") or 0),
                  "side": part.get("side"),
                  "team_id": part.get("team_id")}
                 for part in (sample.get("parts") or [])
             ]}
            for sample in (battle.get("score_series") or [])
            if sample.get("t") is not None and started_at <= sample["t"] <= upper
        ],
    }


@router.get("/api/recordings/{recording_id}/gifts")
async def recording_gifts_api(recording_id: int) -> dict:
    """録画窓のgiftを1件ずつ、掛かっているPK(Battle)のscore推移と併せて動画時間軸で返す
    (timelineのicon、および再生画面の「PK・ギフト」panel用)。

    heatは窓ごとの密度なので「どれだけ来たか」しか読めない。**何が**飛んだのかは
    gift別のiconでしか判らないので、こちらは個々のeventをそのまま返す。時刻はheat・
    commentと同じmapperを通す(生の差分だと焼き込み動画や検索hitと位置がずれる)。

    ``icons`` はgift_id→icon URLで、画像を出せるgiftだけが載る。載らないgiftも
    ``items`` には残す — icon画像が無いことは「giftが飛ばなかった」ではない。

    ``uid`` は送り主のavatarを引くkey。avatar poolのkey規則(unique_id、無ければ
    nickname)に揃えてあるので、画面は ``/api/avatar?id=`` にそのまま渡せば、焼き込みや
    履歴と同じ1枚を得る。eventはavatar URLを持たないため、ここでURLは返さない。

    ``battles`` はこの録画に掛かったPKのscore推移、``items[].battle`` はそのgiftが飛んだ
    PKのordinal(どのPKにも入らなければ null)。gift一覧とPKを別のrouteに分けると同じevent列を
    2度読み、片方だけが別の窓で数えることになるので1つの口にまとめてある。

    ``battles[].participants`` は陣営(名前・side・team_id)、``series[].parts`` はその時刻の
    陣営別score。再生画面のスコアバーは再生位置での実値で分割するため、確定scoreだけでは
    足りない(個人マルチ3本目・チーム別の内訳が出せない)。

    ``items`` に載るのは**自室(味方陣)のgift**だけである。相手陣のコインは相手Roomの
    listenerがBattleの貢献・scoreへ入れるが、eventとしては保存していない。"""
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    session_id = recording.get("session_id")
    if session_id is None:
        return {"recording_id": recording_id, "items": [], "icons": {}, "battles": []}
    path = files._resolved_recording_path(recording)
    started_at = recording["started_at"]
    ended_at = recording.get("ended_at")
    to_pts = await asyncio.to_thread(
        indexer.build_time_mapper_sync, path, started_at, ended_at)
    rows = await asyncio.to_thread(
        runtime.storage.iter_events, session_id, started_at, ended_at, ["gift"])
    # 収集中のsessionはBattleがまだDBに無い(session終了時にしか永続化されない)。録画中の
    # 録画を開いた時に「PKなし」と名乗らないよう、履歴画面と同じ入口で引く。
    fought = await battles.battles_for_session(recording["unique_id"], session_id)
    entries = _battles_in_window(fought, started_at, ended_at)
    items = []
    icons: dict = {}
    for row in rows:
        gift_id = int(row.get("gift_id") or 0)
        # 帰属はserver時刻(create_time)で見る。窓の境界(battle_setting.*_ms)がserver時刻
        # なので、受信時刻のまま突合すると端のgiftが隣のPKへ流れる(欠落時のみtimeで代用)。
        at = row.get("create_time") or row["time"]
        items.append({
            "t": round(to_pts(row["time"]), 2),
            "gift_id": gift_id,
            "name": row.get("gift_name") or "",
            "count": int(row.get("gift_count") or 1),
            "diamonds": int(row.get("diamonds") or 0),
            "nickname": row.get("user_nickname") or "",
            "uid": row.get("user_unique_id") or row.get("user_nickname") or "",
            "battle": _gift_battle_ordinal(entries, at),
        })
        if gift_id and gift_id not in icons:
            url = await asyncio.to_thread(
                runtime.gift_icon_url, gift_id, row.get("gift_image") or "")
            if url:
                icons[gift_id] = url
    return {"recording_id": recording_id, "items": items,
            "icons": {str(gift_id): url for gift_id, url in icons.items()},
            "battles": [_battle_payload(entry, to_pts, started_at, ended_at)
                        for entry in entries]}




@router.get("/api/recordings/{recording_id}/clip-candidates")
async def recording_clip_candidates_api(recording_id: int) -> dict:
    """録画窓の盛り上がりから切り出し候補を出す。時刻は動画時間軸(秒)。

    実体は :func:`tictok.api.candidates.compute_clip_candidates`。short の一括生成が同じ
    候補から範囲を決めるため、算出はrouteの外に置いてある。"""
    return await candidates.compute_clip_candidates(recording_id)


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
