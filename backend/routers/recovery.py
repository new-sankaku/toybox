from typing import List
from fastapi import APIRouter, Request, HTTPException
from core.dependencies import get_data_store
from schemas import RecoveryStatusResponse, RecoveryRetryAllResponse, AgentSchema

router = APIRouter()


@router.get("/recovery/status", response_model=RecoveryStatusResponse)
async def get_recovery_status():
    data_store = get_data_store()
    interrupted = data_store.get_interrupted_agents()
    projects = set()
    for agent in interrupted:
        projects.add(agent.get("projectId"))
    return {
        "interrupted_agents": len(interrupted),
        "interrupted_projects": len(projects),
    }


@router.get("/recovery/interrupted", response_model=List[AgentSchema])
async def get_interrupted_agents():
    data_store = get_data_store()
    return data_store.get_interrupted_agents()


@router.post("/recovery/retry-all", response_model=RecoveryRetryAllResponse)
async def retry_all_interrupted(request: Request):
    data_store = get_data_store()
    recovery_service = request.app.state.recovery_service
    result = recovery_service.recover_interrupted_agents()
    return result
