"""監視対象(live中の配信者)の追加・停止・録画開始/停止と、live中の実況値。

対象は「今つながっている配信」で、終わった録画は routes.recordings 側が扱う。
"""

import asyncio
from typing import Optional
from fastapi import HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from fastapi import APIRouter
from tictok.api import runtime

router = APIRouter()


class MonitorRequest(BaseModel):
    unique_id: str = Field(min_length=1, max_length=80)
    # None: keep the target's existing preference (used by restart); a new target
    # then defaults to saving video. Explicit true/false sets it on add.
    record_video: Optional[bool] = None


class RecordVideoRequest(BaseModel):
    record_video: bool


@router.get("/api/monitors")
async def list_monitors() -> dict:
    return {"monitors": runtime.manager.snapshots()}


@router.post("/api/monitors")
async def add_monitor(request: MonitorRequest) -> dict:
    unique_id = runtime._normalize_unique_id(request.unique_id)
    try:
        collector = await runtime.manager.start(unique_id, record_video=request.record_video)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return collector.snapshot()


@router.post("/api/monitors/{unique_id}/stop")
async def stop_monitor(unique_id: str) -> dict:
    collector = runtime._get_collector(unique_id)
    try:
        await runtime.manager.stop(unique_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return collector.snapshot()


@router.delete("/api/monitors/{unique_id}")
async def remove_monitor(unique_id: str) -> dict:
    runtime._get_collector(unique_id)
    await runtime.manager.remove(unique_id)
    return {"removed": unique_id}


@router.post("/api/monitors/{unique_id}/record/start")
async def start_recording(unique_id: str) -> dict:
    collector = runtime._get_collector(unique_id)
    try:
        await runtime.manager.start_recording(unique_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return collector.snapshot()


@router.post("/api/monitors/{unique_id}/record/stop")
async def stop_recording(unique_id: str) -> dict:
    collector = runtime._get_collector(unique_id)
    try:
        await runtime.manager.stop_recording(unique_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return collector.snapshot()


@router.post("/api/monitors/{unique_id}/record-video")
async def set_record_video(unique_id: str, request: RecordVideoRequest) -> dict:
    collector = runtime._get_collector(unique_id)
    await runtime.manager.set_record_video(unique_id, request.record_video)
    return collector.snapshot()


@router.get("/api/monitors/{unique_id}/record/live/{filename}")
async def live_recording(unique_id: str, filename: str) -> Response:
    path = runtime.manager.live_recording_file(unique_id, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="ライブ録画が見つかりません。")
    if path.suffix == ".m3u8":
        # ライブ録画中のplaylistはrecorderが追記し続けるため、stat時のsizeでContent-Length
        # を決めるFileResponseだと送信body長が超過し"Response content longer than
        # Content-Length"で落ちる。読み込んだbytesを返せばContent-Lengthが実体長と一致する。
        data = await asyncio.to_thread(path.read_bytes)
        return Response(
            content=data,
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "no-cache"},
        )
    return FileResponse(path, media_type="video/mp2t", headers={"Cache-Control": "no-cache"})


@router.get("/api/monitors/{unique_id}/timeline")
async def monitor_timeline(unique_id: str) -> dict:
    return runtime._get_collector(unique_id).timeline_snapshot()


@router.get("/api/monitors/{unique_id}/summary")
async def monitor_summary(unique_id: str) -> dict:
    return runtime._get_collector(unique_id).summary_snapshot()


@router.get("/api/monitors/{unique_id}/battles")
async def monitor_battles(unique_id: str) -> dict:
    return runtime._get_collector(unique_id).battles_snapshot()


@router.get("/api/monitors/{unique_id}/history-stats")
async def monitor_history_stats(unique_id: str, limit: int = runtime.HISTORY_COMPARE_LIMIT) -> dict:
    limit = max(1, min(limit, 50))
    # 配信ごとの実績を遡って畳む重い集計。監視画面が開いている間ずっと叩かれるので、
    # event loop 側で回すと収集中のcommit待ちと相まって全画面が固まる。
    return await asyncio.to_thread(
        runtime.storage.streamer_history_stats, unique_id, limit)
