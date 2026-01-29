from fastapi import APIRouter
from typing import Optional
from pydantic import BaseModel
from core.dependencies import get_socket_manager

router = APIRouter()


class NavigateRequest(BaseModel):
    targetPath: str
    params: Optional[dict] = None


@router.post("/navigator/broadcast")
async def broadcast_navigation(data: NavigateRequest):
    socket_manager = get_socket_manager()
    await socket_manager.emit("navigate", {"path": data.targetPath, "params": data.params or {}})
    return {"success": True}
