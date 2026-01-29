from typing import Optional, Dict, Any
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from middleware.logger import get_logger
from schemas import (
    ArchiveStatsResponse,
    ArchiveCleanupResponse,
    ArchiveEstimateResponse,
    ArchiveRetentionResponse,
    ArchiveExportResponse,
    ArchiveExportAndCleanupResponse,
    AutoArchiveResponse,
    ArchiveListResponse,
)

router = APIRouter()


class RetentionRequest(BaseModel):
    retentionDays: int


class ExportRequest(BaseModel):
    projectId: str


@router.get("/archive/stats", response_model=Dict[str, Any])
async def get_archive_stats(request: Request, projectId: Optional[str] = None):
    archive_service = request.app.state.archive_service
    stats = archive_service.get_data_statistics(project_id=projectId)
    return stats


@router.post("/archive/cleanup", response_model=ArchiveCleanupResponse)
async def cleanup_archive(request: Request, data: Optional[ExportRequest] = None):
    archive_service = request.app.state.archive_service
    try:
        project_id = data.projectId if data else None
        result = archive_service.cleanup_old_traces(project_id=project_id)
        return {"success": True, "deleted": result}
    except Exception as e:
        get_logger().error(f"Cleanup failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="クリーンアップに失敗しました")


@router.get("/archive/estimate", response_model=ArchiveEstimateResponse)
async def estimate_cleanup(request: Request, projectId: Optional[str] = None):
    archive_service = request.app.state.archive_service
    return archive_service.estimate_cleanup_size(project_id=projectId)


@router.put("/archive/retention", response_model=ArchiveRetentionResponse)
async def set_retention(data: RetentionRequest, request: Request):
    archive_service = request.app.state.archive_service
    archive_service.set_retention_days(data.retentionDays)
    return {"retention_days": data.retentionDays}


@router.post("/archive/export", response_model=ArchiveExportResponse)
async def export_archive(data: ExportRequest, request: Request):
    archive_service = request.app.state.archive_service
    try:
        zip_path = archive_service.export_traces_to_zip(data.projectId)
        if not zip_path:
            raise HTTPException(status_code=404, detail="エクスポートするデータがありません")
        import os

        return {"filename": os.path.basename(zip_path)}
    except HTTPException:
        raise
    except Exception as e:
        get_logger().error(f"Export failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="エクスポートに失敗しました")


@router.post("/archive/export-and-cleanup", response_model=ArchiveExportAndCleanupResponse)
async def export_and_cleanup(data: ExportRequest, request: Request):
    archive_service = request.app.state.archive_service
    try:
        result = archive_service.archive_and_cleanup(data.projectId)
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("error", "エクスポートに失敗しました"))
        import os

        return {
            "filename": os.path.basename(result.get("zipPath", "")),
            "deleted": result.get("deleted", {}).get("traces", 0),
        }
    except HTTPException:
        raise
    except Exception as e:
        get_logger().error(f"Export and cleanup failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="エクスポート＆クリーンアップに失敗しました")


@router.post("/archive/auto-archive", response_model=AutoArchiveResponse)
async def auto_archive(request: Request):
    archive_service = request.app.state.archive_service
    try:
        result = archive_service.archive_old_traces()
        return {"archived": result.get("archived", 0)}
    except Exception as e:
        get_logger().error(f"Auto archive failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="自動アーカイブに失敗しました")


@router.get("/archives", response_model=ArchiveListResponse)
async def list_archives(request: Request):
    archive_service = request.app.state.archive_service
    archives = archive_service.list_archives()
    return {"archives": archives}


@router.delete("/archives/{archive_name}", status_code=204)
async def delete_archive(archive_name: str, request: Request):
    archive_service = request.app.state.archive_service
    success = archive_service.delete_archive(archive_name)
    if not success:
        raise HTTPException(status_code=404, detail="アーカイブが見つかりません")
    return None


@router.get("/archives/{archive_name}/download")
async def download_archive(archive_name: str, request: Request):
    archive_service = request.app.state.archive_service
    import os

    archive_dir = archive_service._archive_dir
    file_path = os.path.join(archive_dir, archive_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="アーカイブが見つかりません")
    return FileResponse(path=file_path, filename=archive_name, media_type="application/octet-stream")
