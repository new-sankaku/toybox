from fastapi import APIRouter, Request, HTTPException
from core.dependencies import get_data_store

router = APIRouter()


@router.get("/recovery/interrupted")
async def get_interrupted_agents():
    data_store = get_data_store()
    return data_store.get_interrupted_agents()


@router.post("/recovery/retry-all")
async def retry_all_interrupted(request: Request):
    data_store = get_data_store()
    recovery_service = request.app.state.recovery_service
    result = recovery_service.recover_interrupted_agents()
    return result
