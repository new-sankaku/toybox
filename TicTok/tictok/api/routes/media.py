"""成果物を作る投入と、その台帳(jobs)。

焼き込み・Up出力・再mp4化・音量正規化・ts結合・preview・切り出し・reel。どれも即時には
行わず ``media_jobs`` のqueueへ積み、進捗はjob台帳が持つ。1件ずつの投入と、session単位の
まとめ投入が同じ場所に居るのは、どちらも同じqueueの入口だから。
"""

import asyncio
import secrets
import time
from typing import Optional
from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from tictok.core.gpu import gpu_status
from tictok.media.clipper import make_clip
from tictok.media.reel import reel_path
from tictok.record import audio_norm
from tictok.record.upscale import upscale_status
from tictok.record.video_overlay import (NothingToDrawError, overlay_enabled, preview_paths,
    preview_still)
from fastapi import APIRouter
from tictok.api import disk
from tictok.api import files
from tictok.api import media_jobs
from tictok.api import runtime

router = APIRouter()


@router.post("/api/recordings/{recording_id}/preview/still")
async def preview_still_api(recording_id: int, at: Optional[float] = None) -> dict:
    """焼き込み設定の静止画プレビュー。動画encode・comment layerのpipe・CFR pre-passを
    通らないので数秒で返る。``at`` 未指定ならComment/Gift/Battleが最も濃い時刻を自動で選ぶ。"""
    recording, path, events, battles, transcript = media_jobs._preview_sources(recording_id)
    try:
        result = await preview_still(
            str(path), recording["started_at"], recording.get("ended_at"),
            events, runtime.settings, battles=battles, transcript=transcript, at_seconds=at,
        )
    except NothingToDrawError as exc:
        # 入力に描く対象が無いだけで、serverは正常。_preview_sourcesの他の前提不成立と
        # 同じ409に揃える(5xxにすると監視とlogがserver errorとして数える)。
        raise HTTPException(status_code=409, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "recording_id": recording_id,
        "at_seconds": result["at_seconds"],
        "window_auto": result["window_auto"],
        "comments_drawn": result["comments_drawn"],
        "video_duration_seconds": result["video_duration_seconds"],
        "url": f"/api/recordings/{recording_id}/preview/still.png?v={int(time.time())}",
    }


@router.get("/api/recordings/{recording_id}/preview/still.png")
async def preview_still_image(recording_id: int) -> FileResponse:
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    still = preview_paths(files._safe_recording_path(recording["path"]))[0]
    if not still.is_file():
        raise HTTPException(status_code=404, detail="プレビュー画像がまだ生成されていません。")
    # 設定を変えるたびに作り直す一時的な確認物なので、browserにcacheさせない。
    return FileResponse(still, media_type="image/png",
                        headers={"Cache-Control": "no-store"})


@router.post("/api/recordings/{recording_id}/preview/clip")
async def preview_clip_api(recording_id: int) -> dict:
    """焼き込み設定の動画プレビューをqueueへ載せる。本出力と同じ解像度・codec・qualityで、
    尺だけをmedia PTS窓で切る。応答はjob_idのみ(完了はWSのjob_updateで届く)。"""
    recording, path, _events, _battles, _transcript = media_jobs._preview_sources(recording_id)
    return await media_jobs._enqueue_media_job("overlay_preview", recording_id, recording=recording,
                                    stem=path.stem)


@router.get("/api/recordings/{recording_id}/preview/clip.mp4")
async def preview_clip_video(recording_id: int) -> FileResponse:
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    clip = preview_paths(files._safe_recording_path(recording["path"]))[1]
    if not clip.is_file():
        raise HTTPException(status_code=404, detail="プレビュー動画がまだ生成されていません。")
    return FileResponse(clip, media_type="video/mp4",
                        headers={"Cache-Control": "no-store"})


@router.post("/api/recordings/{recording_id}/output")
async def output_recording(recording_id: int) -> dict:
    """設定でComment/Gift演出が有効なら、収集eventを焼き込んだ動画をrecordings folderへ
    出力する。実処理は永続queueのworkerが行い、この応答はjob_idを即時返す(出力file名は
    完了時のjob resultで届く)。録画・空き容量のcheckは投入時に済ませ、実行を待たずに
    弾けるようにしている。"""
    recording, path = media_jobs._recording_for_output(recording_id)
    return await media_jobs._enqueue_media_job("overlay", recording_id, recording=recording,
                                    stem=path.stem)


@router.post("/api/recordings/{recording_id}/reprocess")
async def reprocess_recording(recording_id: int) -> dict:
    """録画をその保持HLS(.ts)から、実録画と同一のfinalizeパイプライン(concat→timing map再生成→
    単一解像度normalize)で作り直す。混在解像度でPlayerがカクつく録画を、元の.tsから正しく1解像度へ
    直すための経路。mp4は上書きせず既存を _backup/ へ退避し、成功時のみ差し替える(失敗時は復元)。.ts
    が残っていない録画は再mp4化できない。進捗は reprocess_progress でWS通知。"""
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    if recording.get("status") == "recording":
        raise HTTPException(status_code=409, detail="録画中のため再mp4化できません。")
    return await media_jobs._enqueue_media_job("reprocess", recording_id, recording=recording,
                                    stem=files._recording_label(recording))


@router.post("/api/recordings/{recording_id}/pack")
async def pack_recording(recording_id: int) -> dict:
    """録画の素材(.ts)を、解像度が連続する塊ごとに1 fileへ束ね直す。

    中身は再encodeせずbyte連結で、playlistが ``#EXT-X-BYTERANGE`` で束の中を指すようになる
    (実測: 5,628 file -> 9 file、byte差0)。走査・backup・移送のすべてがfile数に比例して重く
    なるのを畳むための操作で、映像そのものは1 byteも変わらない。実処理は永続queueのworkerで、
    この応答はjob_idを即時返す。"""
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    if recording.get("status") == "recording":
        raise HTTPException(status_code=409, detail="録画中のためts結合できません。")
    if not files._recording_media_dirs(recording):
        raise HTTPException(status_code=409, detail="この録画は.tsが残っていません。")
    return await media_jobs._enqueue_media_job("pack", recording_id, recording=recording,
                                    stem=files._recording_label(recording))


@router.post("/api/recordings/{recording_id}/audionorm")
async def audionorm_recording(recording_id: int) -> dict:
    """録画そのもののmp4の音量を正規化する(映像はstream copy、音声だけ再encode)。

    再mp4化と違い.tsを必要としないので、segmentを消した後の録画にも効く。元のmp4は
    _backup/へ退避し、成功時だけ差し替える。進捗は audionorm_progress でWS通知。"""
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    if recording.get("status") == "recording":
        raise HTTPException(status_code=409, detail="録画中のため音量正規化できません。")
    path = files._existing_recording_file(recording)
    if path is None:
        raise HTTPException(status_code=404, detail="録画fileが存在しません（削除済みか録画失敗）。")
    # 出力は映像copyぶんそのまま、つまり元mp4とほぼ同じ容量を同じvolumeへ書く。
    disk._require_disk_space([path.parent], "audionorm", recording_id=recording_id)
    return await media_jobs._enqueue_media_job("audionorm", recording_id, recording=recording,
                                    stem=files._recording_label(recording))


@router.get("/api/upscale/status")
async def upscale_status_api() -> dict:
    return upscale_status()


@router.post("/api/recordings/{recording_id}/upscale-output")
async def upscale_output_recording(recording_id: int) -> dict:
    """AI高画質化(超解像)出力。焼き込みが有効な場合はまず通常の出力(焼き込み)を確保し
    (進捗はoutput_progress)、その動画をローカルAI modelで高画質化して .up.mp4 として
    recordings folderへ出力する(進捗はupscale_progress)。実処理は永続queueのworkerで、
    この応答はjob_idを即時返す。"""
    recording, path = media_jobs._recording_for_output(recording_id)
    return await media_jobs._enqueue_media_job("upscale", recording_id, recording=recording,
                                    stem=path.stem)


@router.post("/api/sessions/{session_id}/output")
async def output_session(session_id: int) -> dict:
    """Session内の全録画を焼き込み出力する。実処理はserver側のbackground jobで、応答は
    job_idを即時返す(進捗はWSのjob_update、reload後は /api/jobs で復元できる)。"""
    return await media_jobs._start_session_output(session_id, upscale=False)


@router.post("/api/sessions/{session_id}/upscale-output")
async def upscale_output_session(session_id: int) -> dict:
    """Session内の全録画をUp出力(AI高画質化)する。焼き込みが有効なら録画ごとに焼き込み→
    高画質化の順で走る。実処理はserver側のbackground job。"""
    return await media_jobs._start_session_output(session_id, upscale=True)


@router.get("/api/jobs")
async def list_jobs() -> dict:
    """待機中/実行中/過去のjobと、GPU排他の現況。画面のreload後もこれで進捗へ復帰する。

    文字起こしも同じ台帳(kind=stt)に載るので一覧へ行として出る。件数を別に添えるのは、
    単発の文字起こしAPIのように台帳を通らないGPU実行があり、その時 gpu.active にだけ
    sttが出るためである(台帳0行で「実行中 stt」だけが出ると読み解けない)。"""
    return {
        "jobs": await asyncio.to_thread(media_jobs._job_snapshot),
        "gpu": gpu_status(),
        "stt": {"counts": await asyncio.to_thread(
            runtime.storage.count_media_jobs_by_state,
            "stt",
        )},
    }


@router.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict:
    """jobを取り消す。待機中はqueueから外すだけ、実行中はffmpegをkillして部分fileを片付ける
    (frame単位でしか止まらないため、応答は『取り消し中』で実際の終了は少し後になる)。
    session一括のgroup idを渡すと、そのgroupの未終了jobをまとめて取り消す。"""
    group = await asyncio.to_thread(runtime.storage.media_jobs_in_group, job_id)
    if group:
        outcomes = [await media_jobs.media_job_queue.cancel(row["job_id"]) for row in group]
        cancelled = sum(1 for o in outcomes if o in ("cancelled", "cancelling"))
        if cancelled == 0:
            raise HTTPException(status_code=409, detail="取り消せるjobがありません（既に終了しています）。")
        return {"job_id": job_id, "cancelled": cancelled, "total": len(group)}
    outcome = await media_jobs.media_job_queue.cancel(job_id)
    if outcome == "missing":
        raise HTTPException(status_code=404, detail="jobが見つかりません。")
    if outcome == "finished":
        raise HTTPException(status_code=409, detail="このjobは既に終了しています。")
    return {"job_id": job_id, "state": outcome}


@router.post("/api/jobs/{job_id}/retry")
async def retry_job(job_id: str) -> dict:
    """止まったjobをもう一度走らせる。一括のgroup idを渡すと、そのgroupの失敗・中断ぶんを
    まとめて待機列へ戻す。

    失敗・中断・取り消しは**同じ行を戻す**(新しい行を足さない)。一括投入のgroupは「N本中
    M本」で数えられているので、失敗行を残したまま新規行を足すと母数だけが増え、group行が
    何度やり直しても完了に到達しない。完了済みのjobを指した場合だけは新規投入になる
    (あれは再開ではなく『もう一度出力する』という別の要求)。"""
    group = await asyncio.to_thread(runtime.storage.media_jobs_in_group, job_id)
    if group:
        targets = [row["job_id"] for row in group
                   if row["state"] in runtime.storage.REQUEUEABLE_STATES]
        if not targets:
            raise HTTPException(status_code=409,
                                detail="再投入できるjobがありません（失敗した録画はありません）。")
        requeued = await media_jobs.media_job_queue.requeue(targets)
        runtime.logger.info(
            "job %d件を再投入しました（group %s）", requeued, job_id,
            extra={"event": "media_queue.group_requeued",
                   "ctx": {"group_id": job_id, "requeued": requeued, "total": len(group)}},
        )
        return {"job_id": job_id, "requeued": requeued, "total": len(group)}
    job = await asyncio.to_thread(runtime.storage.get_media_job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="jobが見つかりません。")
    if job["state"] in ("pending", "running"):
        raise HTTPException(status_code=409, detail="このjobはまだ実行中です。")
    if job["state"] in runtime.storage.REQUEUEABLE_STATES:
        if await asyncio.to_thread(
                runtime.storage.get_recording, job["recording_id"]) is None:
            raise HTTPException(status_code=404, detail="録画が見つかりません（削除済み）。")
        await media_jobs.media_job_queue.requeue([job_id])
        return {"job_id": job_id, "requeued": 1, "total": 1}
    recording = await asyncio.to_thread(runtime.storage.get_recording, job["recording_id"])
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません（削除済み）。")
    if job["kind"] in ("overlay", "upscale"):
        # 空き容量と録画fileの有無は投入時に確認する(再実行でも新規と同じ関門を通す)。
        media_jobs._recording_for_output(job["recording_id"])
    return await media_jobs._enqueue_media_job(
        job["kind"], job["recording_id"], group_id=job.get("group_id") or "",
        recording=recording,
        stem=files._recording_label(recording),
        params=job.get("params") or None,
    )


class ClipRequest(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    label: Optional[str] = None
    # precise は旧clientとの互換。新しい指定は mode を使う。
    precise: bool = False
    mode: Optional[str] = None
    variant: str = "source"
    # 未指定は設定の既定(clip_normalize_audio)に従う。
    normalize_audio: Optional[bool] = None


class ClipRangeRequest(BaseModel):
    recording_id: int
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    label: Optional[str] = None


class ClipBatchRequest(BaseModel):
    items: list[ClipRangeRequest]
    variant: str = "source"
    normalize_audio: Optional[bool] = None
    precise: bool = False
    mode: Optional[str] = None


class ReelRequest(BaseModel):
    items: list[ClipRangeRequest]
    variant: str = "source"
    label: Optional[str] = Field(default=None, max_length=200)


@router.post("/api/recordings/{recording_id}/clip")
async def clip_recording(recording_id: int, payload: ClipRequest) -> dict:
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    route = files._clip_route(recording, payload.variant)
    if route == "render":
        # 全尺の焼き込み出力が無いので、この範囲だけを焼く。GPUを使い数分かかるため
        # 同期では返さない(応答の形が経路で変わるので、clientはrouteで分岐する)。
        # 前提の検査は投入時に済ませる。workerで初めて落とすと、GPUの順番を待った末に
        # 失敗することになる(焼き込み本体と同じ作法)。
        if not overlay_enabled(runtime.settings):
            raise HTTPException(
                status_code=409,
                detail="焼き込みの設定が全てOFFです。Comment/Gift/Battle/字幕のいずれかを"
                       "有効にしてください。",
            )
        if recording.get("session_id") is None:
            raise HTTPException(
                status_code=409,
                detail="この録画にはSessionが紐づいておらず、焼き込むeventがありません。",
            )
        disk._require_disk_space(disk._disk_volume_paths(), "clip_overlay", recording_id=recording_id)
        row = await media_jobs._enqueue_media_job(
            "clip_overlay", recording_id, recording=recording,
            stem=files._recording_stem(recording),
            params={"start": payload.start, "end": payload.end,
                    "label": payload.label, "variant": payload.variant},
        )
        row.update({"route": "render", "variant": payload.variant})
        return row
    src = files._clip_source(recording, payload.variant)
    normalize = media_jobs._clip_normalize(payload.normalize_audio)
    try:
        async with runtime._job_ops("clip", recording_id, stem=src.stem, variant=payload.variant,
                            **audio_norm.describe(normalize)):
            mode = media_jobs._clip_mode(payload.mode, payload.precise)
            result = await make_clip(
                src, payload.start, payload.end, payload.label,
                precise=(mode == "precise"), normalize=normalize,
                smart=(mode == "smart"))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    result["recording_id"] = recording_id
    result["variant"] = payload.variant
    result["route"] = "copy"
    return result


@router.post("/api/clips/batch")
async def clip_batch_api(payload: ClipBatchRequest) -> dict:
    """複数の範囲をまとめて切り出す。録画ごとに1 jobへ束ねてqueueへ載せ、job_idを返す。

    切り出し1本は秒で終わるが、精密(再encode)を選ぶと1本が分単位になる。browserのloopで
    回すとtabを閉じた時点で残りが起動すらしないため、実行はserver側のqueueへ寄せている。"""
    if not payload.items:
        raise HTTPException(status_code=400, detail="切り出す範囲がありません。")
    if payload.variant not in files.CLIP_VARIANTS:
        raise HTTPException(status_code=400, detail=f"未知の素材版です: {payload.variant}")
    disk._require_disk_space(disk._disk_volume_paths(), "clip_batch", items=len(payload.items))
    by_recording: dict = {}
    for item in payload.items:
        if item.end <= item.start:
            raise HTTPException(status_code=400, detail="終了位置は開始位置より後にしてください。")
        by_recording.setdefault(item.recording_id, []).append(item)
    group_id = secrets.token_hex(4) if len(by_recording) > 1 else ""
    jobs_started = []
    for recording_id, items in by_recording.items():
        recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
        if recording is None:
            raise HTTPException(status_code=404, detail="録画が見つかりません。")
        # 素材が無い版を指定していれば、queueへ載せる前にここで弾く。
        src = files._clip_source(recording, payload.variant)
        params = {
            "variant": payload.variant,
            "normalize_audio": payload.normalize_audio,
            "mode": media_jobs._clip_mode(payload.mode, payload.precise),
            "ranges": [{"start": i.start, "end": i.end, "label": i.label} for i in items],
        }
        jobs_started.append(await media_jobs._enqueue_media_job(
            "clip_batch", recording_id, group_id=group_id, recording=recording,
            stem=f"{src.stem} ({len(items)}件)", params=params))
    return {"jobs": jobs_started, "group_id": group_id,
            "total": sum(len(v) for v in by_recording.values())}


@router.post("/api/reels")
async def create_reel_api(payload: ReelRequest) -> dict:
    """切り出しリストの範囲を1本のmp4へ連結するjobを立てる。

    ``items`` の並びがそのまま尺順になる(make_reelは並べ替えない)。時刻順へ整えないのは、
    「表示した順と違う順で繋がれた」方が「順序を指定できない」より悪い誤認を生むため。
    """
    if not payload.items:
        raise HTTPException(status_code=422, detail="連結する範囲がありません。")
    for item in payload.items:
        if item.end <= item.start:
            raise HTTPException(status_code=422, detail="終了位置は開始位置より後にしてください。")
    items = await media_jobs._reel_items([i.model_dump() for i in payload.items], payload.variant)
    first = items[0]
    out = reel_path(first["src"], first["start"], items[-1]["end"], len(items), payload.label)
    disk._require_disk_space([out.parent], "reel", parts=len(items))
    # 代表recording_idは必ず入れる。NULLにするとclaimのSQLが `NULL NOT IN (...)` になり、
    # 実行中のjobが1件でもある間はこの行が拾われない(空くまで待機のまま止まる)。
    recording_id = int(payload.items[0].recording_id)
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    row = await media_jobs._enqueue_media_job(
        "reel", recording_id, recording=recording, stem=first["src"].stem,
        params={"ranges": [i.model_dump() for i in payload.items],
                "variant": payload.variant, "label": payload.label},
    )
    row.update({"output_name": out.name, "parts": len(items),
                "variant": payload.variant})
    return row
