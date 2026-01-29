from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from pydantic import BaseModel
from core.dependencies import get_data_store, get_socket_manager

router = APIRouter()


def _get_phase_name(phase: int) -> str:
    phase_names = {1: "Phase 1: 企画・設計", 2: "Phase 2: 実装", 3: "Phase 3: 統合・テスト"}
    return phase_names.get(phase, f"Phase {phase}")


@router.get("/projects/{project_id}/ai-requests/stats")
async def get_ai_request_stats(project_id: str):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    agents = data_store.get_agents_by_project(project_id)
    total = len(agents)
    processing = len([a for a in agents if a["status"] == "running"])
    pending = len([a for a in agents if a["status"] == "pending"])
    completed = len([a for a in agents if a["status"] == "completed"])
    failed = len([a for a in agents if a["status"] == "failed"])
    return {"total": total, "processing": processing, "pending": pending, "completed": completed, "failed": failed}


@router.get("/projects/{project_id}/metrics")
async def get_project_metrics(project_id: str):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    metrics = data_store.get_project_metrics(project_id)
    if not metrics:
        metrics = {
            "projectId": project_id,
            "totalTokensUsed": 0,
            "estimatedTotalTokens": 50000,
            "elapsedTimeSeconds": 0,
            "estimatedRemainingSeconds": 0,
            "estimatedEndTime": None,
            "completedTasks": 0,
            "totalTasks": 0,
            "progressPercent": 0,
            "currentPhase": project.get("currentPhase", 1),
            "phaseName": _get_phase_name(project.get("currentPhase", 1)),
            "generationCounts": {
                "images": {"count": 0, "unit": "枚", "calls": 0},
                "music": {"count": 0, "unit": "曲", "calls": 0},
                "sfx": {"count": 0, "unit": "個", "calls": 0},
                "voice": {"count": 0, "unit": "件", "calls": 0},
                "code": {"count": 0, "unit": "行", "calls": 0},
                "documents": {"count": 0, "unit": "件", "calls": 0},
                "scenarios": {"count": 0, "unit": "本", "calls": 0},
            },
        }
    return metrics


@router.get("/projects/{project_id}/logs")
async def get_project_logs(project_id: str):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return data_store.get_system_logs(project_id)


@router.get("/projects/{project_id}/assets")
async def get_project_assets(project_id: str):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return data_store.get_assets_by_project(project_id)


@router.patch("/projects/{project_id}/assets/{asset_id}")
async def update_project_asset(project_id: str, asset_id: str, data: Dict[str, Any]):
    data_store = get_data_store()
    socket_manager = get_socket_manager()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    asset = data_store.update_asset(project_id, asset_id, data)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    await socket_manager.emit_to_project("asset:updated", {"projectId": project_id, "asset": asset}, project_id)
    return asset
