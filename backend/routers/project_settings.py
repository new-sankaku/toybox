from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from pydantic import BaseModel
from core.dependencies import get_data_store

router = APIRouter()


class ProjectSettingsUpdate(BaseModel):
    settings: Dict[str, Any]


@router.get("/projects/{project_id}/settings")
async def get_project_settings(project_id: str):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.get("config", {})


@router.patch("/projects/{project_id}/settings")
async def update_project_settings(project_id: str, data: ProjectSettingsUpdate):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    current_config = project.get("config", {})
    current_config.update(data.settings)
    updated = data_store.update_project(project_id, {"config": current_config})
    return updated.get("config", {})
