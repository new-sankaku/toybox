from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel
from core.dependencies import get_socket_manager
from schemas import NavigatorSuccessResponse

router = APIRouter()


class NavigateRequest(BaseModel):
    targetPath: str
    params: Optional[dict] = None


class MessageRequest(BaseModel):
    projectId: Optional[str] = None
    text: str
    priority: Optional[str] = "normal"


@router.post("/navigator/message", response_model=NavigatorSuccessResponse)
async def send_message(data: MessageRequest):
    socket_manager = get_socket_manager()
    payload = {"text": data.text, "priority": data.priority}
    if data.projectId:
        await socket_manager.emit_to_project("navigator:message", payload, data.projectId)
    else:
        await socket_manager.emit("navigator:message", payload)
    return {"success": True}


@router.post("/navigator/broadcast", response_model=NavigatorSuccessResponse)
async def broadcast_navigation(data: NavigateRequest):
    socket_manager = get_socket_manager()
    await socket_manager.emit("navigate", {"path": data.targetPath, "params": data.params or {}})
    return {"success": True}
