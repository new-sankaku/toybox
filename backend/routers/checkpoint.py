from fastapi import APIRouter,Request,HTTPException
from typing import Optional
from pydantic import BaseModel
from core.dependencies import get_data_store,get_socket_manager

router=APIRouter()


class ResolveCheckpoint(BaseModel):
 resolution:str
 feedback:Optional[str]=None


@router.get("/projects/{project_id}/checkpoints")
async def list_project_checkpoints(project_id:str):
 data_store=get_data_store()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="プロジェクトが見つかりません")
 return data_store.get_checkpoints_by_project(project_id)


@router.post("/checkpoints/{checkpoint_id}/resolve")
async def resolve_checkpoint(checkpoint_id:str,data:ResolveCheckpoint,request:Request):
 data_store=get_data_store()
 socket_manager=get_socket_manager()
 if data.resolution not in ("approved","rejected","revision_requested"):
  raise HTTPException(status_code=400,detail="解決タイプが不正です。approved, rejected, revision_requested のいずれかを指定してください")
 checkpoint=data_store.resolve_checkpoint(checkpoint_id,data.resolution,data.feedback)
 if not checkpoint:
  raise HTTPException(status_code=404,detail="チェックポイントが見つかりません")
 agent_id=checkpoint["agentId"]
 project_id=checkpoint["projectId"]
 agent=data_store.get_agent(agent_id)
 agent_status=agent["status"] if agent else None
 await socket_manager.emit_to_project('checkpoint:resolved',{
  "checkpointId":checkpoint_id,
  "projectId":project_id,
  "agentId":agent_id,
  "resolution":data.resolution,
  "feedback":data.feedback,
  "agentStatus":agent_status
 },project_id)
 if data.resolution=="revision_requested":
  execution_service=getattr(request.app.state,'agent_execution_service',None)
  if execution_service:
   await execution_service.re_execute_agent(project_id,agent_id)
 return checkpoint
