"""成果物を作る投入と、その台帳(jobs)。

焼き込み・Up出力・再mp4化・音量正規化・ts結合・preview・切り出し・reel・文字起こし。どれも即時には
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
from tictok.core import config, ops_labels
from tictok.core.gpu import gpu_status
from tictok.media import clip_range, hls_source
from tictok.media import work as work_media
from tictok.media.clipper import make_clip
from tictok.media.reel import reel_path
from tictok.store import clip_presets
from tictok.record import audio_norm, bgm_remove
from tictok.record import media_queue
from tictok.record.transcription import stt_available
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
    recording, path, events, battles, transcript = await asyncio.to_thread(media_jobs._preview_sources, recording_id)
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
    recording, path, _events, _battles, _transcript = await asyncio.to_thread(media_jobs._preview_sources, recording_id)
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


@router.post("/api/recordings/{recording_id}/transcribe")
async def transcribe_recording(recording_id: int, corrections: str = "keep") -> dict:
    """1録画の文字起こしをqueueへ積む(kind=stt)。応答はjob_idで、進捗と結果はWSで届く。

    ``corrections`` は既にある訂正の扱い(``keep`` 引き継ぎ / ``discard`` 破棄)。誤りを
    1件ずつ直した後なら引き継ぎ、modelや時刻mapを変えたなら破棄が正しい。既に待機列に
    同じ録画の行が居る場合はそちらへ相乗りするので、**その行の指定が優先される** —
    応答の ``corrections`` は実際に効く方を返す。

    以前はこのrouteだけがqueueを通さずprocess内で走っていた。Job一覧には出るのに台帳へ行が
    無いため取り消しがmissingで空振りし、実処理は止まらないまま「取り消せるjobはありません」
    と出ていた。台帳へ載せれば取り消し・再実行・中断復帰が他の種別と同じになる。"""
    if not stt_available():
        raise HTTPException(
            status_code=503,
            detail="STTが利用できません。faster-whisperのinstallとTICTOK_STT_ENABLEDを確認してください。")
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    # 文字起こしはmp4でも素材(.ts)でも走る。mp4だけを見ていた頃は、同じ録画がqueue経路なら
    # 文字起こしできて録画詳細のbuttonからは404という食い違いになっていた。
    if not files._recording_source_exists(recording):
        raise HTTPException(status_code=404, detail="録画fileが存在しません。")
    # sweepが文字起こしのない録画を上限なしで積むので、人が開いた1本はほぼ必ず既に待機列に
    # 居る。ここで409を返すと「押しても何も始まらない」になるため、既にある行へ相乗りし、
    # その1本の順番だけを人の優先度へ上げる(同じ録画に2本は走らせない)。
    policy = media_jobs._corrections_policy({"corrections": corrections})
    existing = media_jobs.media_job_queue.pending_for("stt", recording_id)
    if existing is not None:
        await media_jobs.media_job_queue.promote(existing["job_id"])
        return {"job_id": existing["job_id"], "kind": "stt", "recording_id": recording_id,
                "state": existing["state"], "queued_at": existing["queued_at"],
                "corrections": ((existing.get("params") or {}).get("corrections")
                                or "keep")}
    queued = await media_jobs._enqueue_media_job(
        "stt", recording_id, recording=recording,
        stem=files._recording_label(recording), params={"corrections": policy})
    return {**queued, "corrections": policy}


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
async def list_jobs(state: str = "all", kind: str = "all", job: str = "",
                    limit: int = 200) -> dict:
    """待機中/実行中/過去のjobと、GPU排他の現況。画面のreload後もこれで進捗へ復帰する。

    ``state`` / ``kind`` はJob画面のfilterで、台帳をここで絞る。画面側だけで絞っていた頃は、
    一括投入が台帳の新しい``limit``行を埋めた日に、その前に失敗したjobが応答へ入らず
    「失敗・中断のみ」が0件と断定していた。``total`` は絞り込みに一致する台帳の全行数で、
    ``limit``で切れた分があることを画面が名乗るために返す。

    文字起こしも同じ台帳(kind=stt)に載るので一覧へ行として出る。件数を別に添えるのは、
    単発の文字起こしAPIのように台帳を通らないGPU実行があり、その時 gpu.active にだけ
    sttが出るためである(台帳0行で「実行中 stt」だけが出ると読み解けない)。

    ``job`` は1件の名指し(運用logの「このjobを見る」からの着地)。指されたjobが古くて
    ``limit``の外に居ても必ず応答へ入るよう、台帳をjob_idで直接引く。

    種別labelを同梱するのは、同じ訳語を画面にも置くと必ずずれるため
    (``core/ops_labels.py`` のdocstring)。種別filterの選択肢もこれから作る。取り消し・再実行が
    効くdomain(``queued_kinds``)を同梱するのも同じ理由で、画面が独自の一覧を持つと台帳へ
    種別が増えたときに黙って古いままになる。"""
    if state != "all" and state not in media_queue.STATE_FILTERS:
        raise HTTPException(status_code=400, detail=f"知らない状態filterです: {state}")
    if limit < 1:
        raise HTTPException(status_code=400, detail="limitは1以上で指定してください。")
    states = media_queue.STATE_FILTERS.get(state)
    domains = None if kind == "all" else (kind,)
    jobs, total = await asyncio.to_thread(
        media_jobs._job_page, states=states, domains=domains,
        job_id=job.strip() or None, limit=limit)
    return {
        "jobs": jobs,
        "total": total,
        "limit": limit,
        "gpu": gpu_status(),
        "stt": {"counts": await asyncio.to_thread(
            runtime.storage.count_media_jobs_by_state,
            "stt",
        )},
        "kind_labels": ops_labels.JOB_KIND_LABELS,
        # 取り消し・再実行が効くdomain。効くのはDBのqueueに載る映像jobだけで、容量scan等の
        # in-process jobは台帳に行が無い。画面側に同じ一覧を持たせていた頃は、台帳へ種別が
        # 増えても画面が黙って古いままだった(文字起こしのjobだけbuttonが出なかった)。
        "queued_kinds": list(media_jobs.QUEUED_JOB_DOMAINS),
    }


@router.post("/api/jobs/cancel-matching")
async def cancel_matching_jobs(kind: str = "all") -> dict:
    """種別で絞った未終了job(待機中・実行中)をまとめて取り消す。

    ``kind`` はJob画面の種別filterと同じ語(``all`` は全種別)。状態filterは受け取らない —
    取り消せるのは待機中と実行中だけで、それ以外を渡せる形にすると「失敗のみを取り消す」
    のような効かない指定を画面が作れてしまう。

    実行中の1本も止まる。数十分走った文字起こしやencodeが捨てられるので、確認は画面が出す。"""
    domains = None if kind == "all" else (kind,)
    snapshot = await asyncio.to_thread(
        media_jobs._job_snapshot, states=("pending", "running"), domains=domains,
        limit=100000)
    # 取り消せるのは台帳(DBのqueue)に載るjobだけ。容量scan等のin-process jobは台帳に行が
    # 無く、cancelは必ずmissingを返す。母数に混ぜると「N件中0件を取り消した」と出る。
    # 一括投入の合成行(job_id=group_id)も外す。中身は録画ごとの明細として同じ一覧に
    # 並んでいるので、合成行まで数えると同じ一括を二重に数えることになる。
    jobs = [job for job in snapshot
            if job["domain"] in media_jobs.QUEUED_JOB_DOMAINS
            and job.get("group_id") != job["job_id"]]
    cancelled = 0
    for job in jobs:
        outcome = await media_jobs.media_job_queue.cancel(job["job_id"])
        if outcome in ("cancelled", "cancelling"):
            cancelled += 1
    runtime.logger.info(
        "未終了jobを%d件取り消しました（種別=%s / 対象=%d件）", cancelled, kind, len(jobs),
        extra={"event": "media_queue.batch_cancelled",
               "ctx": {"kind": kind, "cancelled": cancelled, "total": len(jobs)}},
    )
    return {"cancelled": cancelled, "total": len(jobs)}


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
    # **録画1本に属さないjobが在る**(highlightの突き合わせ・書き出し)。そこへ
    # ``get_recording(None)`` を引くと必ずNoneが返り、「録画が見つかりません（削除済み）」
    # という**嘘の理由**で弾かれる —— 一度も録画を持たなかったjobを人が二度と再開できない。
    # 録画の実在を確かめるのは、録画を持つjobだけの問いである。
    owns_recording = job["recording_id"] is not None
    if job["state"] in runtime.storage.REQUEUEABLE_STATES:
        if owns_recording and await asyncio.to_thread(
                runtime.storage.get_recording, job["recording_id"]) is None:
            raise HTTPException(status_code=404, detail="録画が見つかりません（削除済み）。")
        await media_jobs.media_job_queue.requeue([job_id])
        return {"job_id": job_id, "requeued": 1, "total": 1}
    if not owns_recording:
        # 完了済みからのやり直しは「同じ行の再開」ではなく**新しい投入**である。録画を
        # 持たないjobの投入には、その種別ごとの前提(highlightの行のstatusで二重投入を
        # 抑える等)が要る —— ここで作ると台帳だけが増え、抑止を素通りした2本目が走る。
        # 出所の画面から投げ直してもらう方が、確実で説明もできる。
        raise HTTPException(
            status_code=409,
            detail="完了したこの種別のjobは、元の画面から実行し直してください"
                   "（録画に属さないjobなのでここからは作り直せません）。")
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
    # 未指定は設定の既定(clip_remove_bgm)に従う。
    remove_bgm: Optional[bool] = None
    # 未指定は設定の既定(clip_subtitles)に従う。書式は設定(clip_subtitle_formats)が決める。
    subtitles: Optional[bool] = None


class ClipRangeRequest(BaseModel):
    recording_id: int
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    label: Optional[str] = None
    # どの見どころから来た範囲か。書き出した事実をその行へ書き戻すためだけに使う
    # (範囲そのものはpayloadの値をそのまま使う — 行を引き直すと、投入後に詰め直された
    # IN/OUTで書き出すことになり、利用者が押した時に見えていた範囲と食い違う)。
    bookmark_id: Optional[int] = None


class ClipBatchRequest(BaseModel):
    items: list[ClipRangeRequest]
    variant: str = "source"
    normalize_audio: Optional[bool] = None
    remove_bgm: Optional[bool] = None
    subtitles: Optional[bool] = None
    precise: bool = False
    mode: Optional[str] = None


class StillRequest(BaseModel):
    """スクショ1枚。範囲を持たないので ``at`` の1点だけを受ける。"""

    at: float = Field(ge=0)
    variant: str = "source"
    label: Optional[str] = Field(default=None, max_length=200)


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
    remove_bgm = media_jobs._clip_remove_bgm(payload.remove_bgm)
    try:
        async with runtime._job_ops("clip", recording_id, stem=src.stem, variant=payload.variant,
                            **audio_norm.describe(normalize),
                            **bgm_remove.describe(remove_bgm)):
            mode = media_jobs._clip_mode(payload.mode, payload.precise)
            result = await make_clip(
                src, payload.start, payload.end, payload.label,
                precise=(mode == "precise"), normalize=normalize,
                smart=(mode == "smart"), remove_bgm=remove_bgm)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    # 字幕fileはmp4が出来てから添える。原点は要求した開始位置ではなく、make_clipが実測した
    # 実開始(actual_start_seconds)なので、切り出しが終わるまで確定しない。
    if media_jobs._clip_subtitles(payload.subtitles):
        await media_jobs._attach_clip_subtitles(result, recording_id, payload.variant)
    result["recording_id"] = recording_id
    result["variant"] = payload.variant
    result["route"] = "copy"
    return result


@router.post("/api/recordings/{recording_id}/still")
async def still_recording(recording_id: int, payload: StillRequest) -> dict:
    """再生位置の1 frameをpngで保存するjobを立てる(静止画の置き場 ``_screenshots`` へ出る)。

    素材版の実在は投入時に確かめる。workerで初めて落とすと、押した人は待った末に理由を
    知ることになる(切り出し・焼き込みと同じ作法)。"""
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    src = files._clip_source(recording, payload.variant)
    return await media_jobs._enqueue_media_job(
        "still", recording_id, recording=recording, stem=src.stem,
        priority=media_jobs.STILL_JOB_PRIORITY,
        params={"at": payload.at, "variant": payload.variant, "label": payload.label})


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
    # BGM除去を使えない構成なら、queueへ載せる前にここで弾く(判定はworkerでも同じ関数が
    # 行うが、120件を積んでから1件ずつ落ちるのでは押した人が理由に辿り着けない)。
    media_jobs._clip_remove_bgm(payload.remove_bgm)
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
            "remove_bgm": payload.remove_bgm,
            "subtitles": payload.subtitles,
            "mode": media_jobs._clip_mode(payload.mode, payload.precise),
            "ranges": [{"start": i.start, "end": i.end, "label": i.label,
                        "bookmark_id": i.bookmark_id} for i in items],
        }
        jobs_started.append(await media_jobs._enqueue_media_job(
            "clip_batch", recording_id, group_id=group_id, recording=recording,
            stem=f"{src.stem} ({len(items)}件)", params=params))
    return {"jobs": jobs_started, "group_id": group_id,
            "total": sum(len(v) for v in by_recording.values())}


@router.post("/api/reels")
async def create_reel_api(payload: ReelRequest) -> dict:
    """見どころの範囲を1本のmp4へ連結するjobを立てる。

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


# ---------------------------------------------------------------------------------------
# short(縦の短尺動画)
# ---------------------------------------------------------------------------------------


class ClipPresetRequest(BaseModel):
    """shortの型の作成・更新。値は :data:`tictok.store.clip_presets.PRESET_FIELDS` の
    keyだけを受け、値域の判定はstore側の1箇所で行う(画面は通すがDBが弾く、を作らない)。"""

    name: Optional[str] = None
    values: dict = Field(default_factory=dict)


class ClipPresetOrderRequest(BaseModel):
    preset_ids: list[int]


class ShortRange(BaseModel):
    """人が選んだ範囲。録画はpathが指すので ``recording_id`` は持たない。"""

    start: float = Field(ge=0)
    end: float = Field(gt=0)
    label: Optional[str] = None


class ShortRequest(BaseModel):
    preset_id: Optional[int] = None
    # 未指定なら設定の既定本数。0や負は「作らない」ではなく指定誤りなので受けない。
    limit: Optional[int] = Field(default=None, ge=1, le=50)
    # 題名・説明・hashtag・表紙位置をAIに作らせるか。AIが未設定なら投入時に断る。
    ai: bool = False
    # 範囲を人が選ぶ場合。渡すと候補算出も吸着も行わず、その範囲のまま作る。
    ranges: list[ShortRange] = Field(default_factory=list)


@router.get("/api/clip-presets")
async def list_clip_presets_api() -> dict:
    """shortの型の一覧と、各列の値域。画面はこのfieldsを見てformを組む。"""
    presets = await asyncio.to_thread(runtime.storage.list_clip_presets)
    return {"presets": presets,
            "fields": {key: {k: v for k, v in spec.items() if k != "type"}
                       | {"type": spec["type"].__name__}
                       for key, spec in clip_presets.PRESET_FIELDS.items()}}


@router.post("/api/clip-presets")
async def create_clip_preset_api(payload: ClipPresetRequest) -> dict:
    try:
        preset_id = await asyncio.to_thread(
            runtime.storage.create_clip_preset, payload.name or "", payload.values)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return await asyncio.to_thread(runtime.storage.get_clip_preset, preset_id)


@router.patch("/api/clip-presets/{preset_id}")
async def update_clip_preset_api(preset_id: int, payload: ClipPresetRequest) -> dict:
    try:
        found = await asyncio.to_thread(
            runtime.storage.update_clip_preset, preset_id, payload.name, payload.values)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not found:
        raise HTTPException(status_code=404, detail="この型はもうありません。")
    return await asyncio.to_thread(runtime.storage.get_clip_preset, preset_id)


@router.delete("/api/clip-presets/{preset_id}")
async def delete_clip_preset_api(preset_id: int) -> dict:
    removed = await asyncio.to_thread(runtime.storage.delete_clip_preset, preset_id)
    if not removed:
        raise HTTPException(status_code=404, detail="この型はもうありません。")
    return {"deleted": True, "preset_id": preset_id}


@router.post("/api/clip-presets/order")
async def reorder_clip_presets_api(payload: ClipPresetOrderRequest) -> dict:
    count = await asyncio.to_thread(
        runtime.storage.reorder_clip_presets, payload.preset_ids)
    return {"ordered": count}


@router.get("/api/recordings/{recording_id}/short-plan")
async def short_plan_api(recording_id: int, preset_id: Optional[int] = None,
                         limit: Optional[int] = None) -> dict:
    """作らずに、どの範囲でどう作るかだけを返す。

    生成は1本あたり分単位かかる操作なので、範囲の妥当性を成果物を見て確かめる形にすると
    確認のcostが実行のcostと同じになる。**捨てた候補も理由つきで返す** — 数だけが減ると、
    検出が弱いのか範囲確定で落ちているのかを切り分ける手段が無い。
    """
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    preset = await asyncio.to_thread(
        media_jobs._short_preset, {"preset_id": preset_id})
    path = files._resolved_recording_path(recording)
    plan = await media_jobs._plan_short_ranges(
        recording_id, path, preset, {"limit": limit})
    return {
        "recording_id": recording_id,
        "preset": preset,
        "candidate_count": plan.get("candidate_count", 0),
        "chapters": len(plan.get("chapters") or []),
        "segments": len(plan.get("segments") or []),
        "ranges": [{k: v for k, v in item.items() if k != "candidate"}
                   for item in plan["ranges"]],
        "rejected": [{"start": item.get("start"), "end": item.get("end"),
                      "seconds": item.get("seconds"), "peak": item.get("peak"),
                      "reason": item["rejected"],
                      "reason_label": clip_range.REJECT_LABELS[item["rejected"]]}
                     for item in plan.get("rejected") or []],
    }


@router.post("/api/recordings/{recording_id}/short")
async def create_short_api(recording_id: int, payload: ShortRequest) -> dict:
    """1録画からshortをまとめて作るjobを立てる。

    範囲の確定も生成もworkerで行う。ここでするのは、待った末に落ちる条件(型が無い・字幕の
    材料が無い・AIが未設定・空き容量)を投入時に確かめることだけである。
    """
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    for item in payload.ranges:
        if item.end <= item.start:
            raise HTTPException(status_code=422, detail="終了位置は開始位置より後にしてください。")
    path = files._resolved_recording_path(recording)
    disk._require_disk_space([path.parent], "short", ranges=len(payload.ranges))
    params = {
        "preset_id": payload.preset_id,
        "limit": payload.limit,
        "ai": payload.ai,
        "ranges": [{"start": i.start, "end": i.end, "label": i.label}
                   for i in payload.ranges],
    }
    return await media_jobs._enqueue_media_job(
        "short", recording_id, recording=recording, stem=path.stem, params=params)


# ---------------------------------------------------------------------------------------
# 作品(グループ1件 -> 完成品1本)
# ---------------------------------------------------------------------------------------


class WorkRequest(BaseModel):
    """グループを作品にする指定。範囲はグループが持つので、ここには渡さない。"""

    preset_id: Optional[int] = None


@router.get("/api/groups/{group_id}/work-plan")
async def work_plan_api(group_id: int, preset_id: Optional[int] = None) -> dict:
    """作らずに、何をどの順で繋ぐかだけを返す。

    生成は分単位かかる操作なので、中身の確認を成果物を見て行う形にすると、確認のcostが
    実行のcostと同じになる（short の下見と同じ理由）。

    ``part_ready`` は「前回作った中間が今も在る」という**事実**であって、「焼き直さない」
    という予言ではない。焼き込みのcache判定は設定・event・文字起こしまで見る別の場所が持っており、
    そこが焼き直すと決めればこの値に関わらず切り出しから作り直される。
    """
    group = await asyncio.to_thread(runtime.storage.get_group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="グループが見つかりません。")
    preset = await asyncio.to_thread(
        media_jobs._short_preset, {"preset_id": preset_id})
    cuts = [row for row
            in await asyncio.to_thread(runtime.storage.bookmarks_in_group, group_id)
            if row.get("end") is not None]
    codec = config.get_short_codec()

    def _collect() -> list:
        scenes = []
        for index, cut in enumerate(cuts):
            recording = runtime.storage.get_recording(int(cut["recording_id"]))
            # 素材が無いシーンは投入してから落ちる。下見の目的はそれを先に見せることなので、
            # 見つからないことを行として残す(黙って除くと件数だけが減る)。
            path = (files._resolved_recording_path(recording)
                    if recording is not None else None)
            state = (work_media.scene_cache_state(
                        path, float(cut["start"]), float(cut["end"]), preset, codec)
                     if path is not None else {})
            scenes.append({
                "position": index + 1,
                "bookmark_id": cut["id"],
                "recording_id": cut["recording_id"],
                "unique_id": cut["unique_id"],
                "start": cut["start"],
                "end": cut["end"],
                "seconds": round(float(cut["end"]) - float(cut["start"]), 3),
                "label": cut["memo"] or "",
                "source_missing": path is None or not hls_source.available(path),
                # 焼き込みにはSessionのeventが要る。紐づいていない録画は投入時に断られる。
                "no_session": recording is not None and recording.get("session_id") is None,
                **state,
            })
        return scenes

    scenes = await asyncio.to_thread(_collect)
    burns = [name for key, name in (("subtitles", "字幕"), ("comments", "コメント"),
                                    ("gifts", "ギフト"), ("score_bar", "スコアバー"))
             if int(preset.get(key) or 0)]
    return {
        "group_id": group_id,
        "group": group["name"],
        "preset": preset,
        "scenes": scenes,
        "scene_count": len(scenes),
        "requested_seconds": round(sum(s["seconds"] for s in scenes), 3),
        # 何を焼くか。押す前に読めないと、テロップ入りのつもりで素の連結が出る。
        "burns": burns,
        "tighten": bool(int(preset.get("tighten") or 0)),
        "upscale": bool(int(preset.get("upscale") or 0)),
        "cache_bytes": sum(s.get("cache_bytes") or 0 for s in scenes),
        # 投入すれば落ちると分かっている条件。ここに1つでも在れば押させない。
        "blocking": [s["position"] for s in scenes
                     if s["source_missing"] or (burns and s["no_session"])],
    }


@router.post("/api/groups/{group_id}/work")
async def create_work_api(group_id: int, payload: WorkRequest) -> dict:
    """グループ1件を、投稿できるmp4 1本にするjobを立てる。

    ``reel``(切り出しの連結)との違いは、あちらがstream copyで繋ぐだけの**素材**なのに対し、
    こちらは各シーンにテロップを焼き、間を詰め、検品まで通した**完成品**であること。素材が
    要る場面もあるので、reelは残して別の口にしている。

    シーンの並びはグループの ``position``(=人が決めた書き出し順)。ここでは渡さない —
    渡す形にすると、画面が並びを組み立て直すたびにDBの並びと食い違う余地が生まれる。

    投入時に確かめるのは「待った末に落ちる条件」だけ(グループが空・録画が消えている・
    空き容量)。実際の生成はworkerで行う。
    """
    group = await asyncio.to_thread(runtime.storage.get_group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="グループが見つかりません。")
    cuts = [row for row
            in await asyncio.to_thread(runtime.storage.bookmarks_in_group, group_id)
            if row.get("end") is not None]
    if not cuts:
        raise HTTPException(
            status_code=422,
            detail=f"グループ「{group['name']}」に尺のある見どころがありません。"
                   "先に追加してください。")
    recording_id = int(cuts[0]["recording_id"])
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(
            status_code=404, detail="先頭シーンの録画が見つかりません（削除済み）。")
    path = files._resolved_recording_path(recording)
    # 中間はシーンぶんの再encode物が同時に載る。空きの判定は出力と同じvolumeで行う
    # (make_workが中間をそこへ置くため)。
    disk._require_disk_space([path.parent], "work", parts=len(cuts))
    row = await media_jobs._enqueue_media_job(
        "work", recording_id, recording=recording,
        stem=f"{group['name']} ({len(cuts)}シーン)",
        params={"group_id": group_id, "preset_id": payload.preset_id})
    row.update({"group_id": group_id, "group": group["name"], "scenes": len(cuts)})
    return row
