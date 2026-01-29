from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.dependencies import get_data_store
from schemas import OutputSettingsSchema, CostSettingsSchema

router = APIRouter()


class ProjectSettingsUpdate(BaseModel):
    settings: Dict[str, Any]


class OutputSettings(BaseModel):
    default_dir: str = "outputs"


class CostServiceSettings(BaseModel):
    enabled: bool = True
    monthly_limit: float = 10.0


class CostSettings(BaseModel):
    global_enabled: bool = True
    global_monthly_limit: float = 100.0
    alert_threshold: int = 80
    stop_on_budget_exceeded: bool = False
    services: Dict[str, CostServiceSettings] = {}


@router.get("/projects/{project_id}/settings", response_model=Dict[str, Any])
async def get_project_settings(project_id: str):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.get("config", {})


@router.patch("/projects/{project_id}/settings", response_model=Dict[str, Any])
async def update_project_settings(project_id: str, data: ProjectSettingsUpdate):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    current_config = project.get("config", {})
    current_config.update(data.settings)
    updated = data_store.update_project(project_id, {"config": current_config})
    return updated.get("config", {})


@router.get("/projects/{project_id}/settings/output", response_model=OutputSettingsSchema)
async def get_output_settings(project_id: str):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    config = project.get("config", {})
    return config.get("output", {"default_dir": "outputs"})


@router.put("/projects/{project_id}/settings/output", response_model=OutputSettingsSchema)
async def update_output_settings(project_id: str, data: OutputSettings):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    config = project.get("config", {})
    config["output"] = data.model_dump()
    data_store.update_project(project_id, {"config": config})
    return config["output"]


@router.get("/projects/{project_id}/settings/cost", response_model=CostSettingsSchema)
async def get_cost_settings(project_id: str):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    config = project.get("config", {})
    return config.get(
        "cost",
        {
            "global_enabled": True,
            "global_monthly_limit": 100.0,
            "alert_threshold": 80,
            "stop_on_budget_exceeded": False,
            "services": {},
        },
    )


@router.put("/projects/{project_id}/settings/cost", response_model=CostSettingsSchema)
async def update_cost_settings(project_id: str, data: CostSettings):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    config = project.get("config", {})
    config["cost"] = data.model_dump()
    data_store.update_project(project_id, {"config": config})
    return config["cost"]


@router.get("/projects/{project_id}/settings/ai-providers", response_model=List[Dict[str, Any]])
async def get_ai_providers_settings(project_id: str):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    config = project.get("config", {})
    return config.get("ai_providers", [])


@router.put("/projects/{project_id}/settings/ai-providers", response_model=List[Dict[str, Any]])
async def update_ai_providers_settings(project_id: str, providers: List[Dict[str, Any]]):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    config = project.get("config", {})
    config["ai_providers"] = providers
    data_store.update_project(project_id, {"config": config})
    return config["ai_providers"]
