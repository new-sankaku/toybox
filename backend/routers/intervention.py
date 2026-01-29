from fastapi import APIRouter,Request,HTTPException
from typing import List,Optional
from pydantic import BaseModel
from core.dependencies import get_data_store,get_socket_manager

router=APIRouter()


class InterventionCreate(BaseModel):
 targetType:str="all"
 targetAgentId:Optional[str]=None
 priority:str="normal"
 message:str
 attachedFileIds:List[str]=[]


class InterventionResponse(BaseModel):
 message:str


@router.get("/projects/{project_id}/interventions")
async def list_interventions(project_id:str):
 data_store=get_data_store()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="プロジェクトが見つかりません")
 return data_store.get_interventions_by_project(project_id)


@router.post("/projects/{project_id}/interventions",status_code=201)
async def create_intervention(project_id:str,data:InterventionCreate,request:Request):
 data_store=get_data_store()
 socket_manager=get_socket_manager()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="プロジェクトが見つかりません")
 if data.targetType not in ("all","specific"):
  raise HTTPException(status_code=400,detail="対象タイプが不正です")
 if data.targetType=="specific" and not data.targetAgentId:
  raise HTTPException(status_code=400,detail="specific の場合は targetAgentId が必須です")
 if data.targetAgentId:
  agent=data_store.get_agent(data.targetAgentId)
  if not agent or agent["projectId"]!=project_id:
   raise HTTPException(status_code=404,detail="エージェントが見つかりません")
 if data.priority not in ("normal","urgent"):
  raise HTTPException(status_code=400,detail="優先度が不正です")
 if not data.message.strip():
  raise HTTPException(status_code=400,detail="メッセージは必須です")
 intervention=data_store.create_intervention(
  project_id=project_id,
  target_type=data.targetType,
  target_agent_id=data.targetAgentId,
  priority=data.priority,
  message=data.message,
  attached_file_ids=data.attachedFileIds
 )
 await socket_manager.emit_to_project('intervention:created',{
  "interventionId":intervention["id"],
  "projectId":project_id,
  "intervention":intervention
 },project_id)
 if data.priority=="urgent":
  data_store.pause_project(project_id)
  await socket_manager.emit_to_project('project:paused',{
   "projectId":project_id,
   "reason":"urgent_intervention",
   "interventionId":intervention["id"]
  },project_id)
 if data.targetType=="specific" and data.targetAgentId:
  activation_result=data_store.activate_agent_for_intervention(data.targetAgentId,intervention["id"])
  if activation_result.get("activated"):
   activated_agent=activation_result["agent"]
   await socket_manager.emit_to_project('agent:activated',{
    "agentId":data.targetAgentId,
    "projectId":project_id,
    "agent":activated_agent,
    "previousStatus":activation_result.get("previousStatus"),
    "interventionId":intervention["id"]
   },project_id)
   for paused_agent in activation_result.get("pausedAgents",[]):
    await socket_manager.emit_to_project('agent:paused',{
     "agentId":paused_agent["id"],
     "projectId":project_id,
     "agent":paused_agent,
     "reason":"subsequent_phase_pause"
    },project_id)
   if activation_result.get("previousStatus")!="waiting_response":
    execution_service=getattr(request.app.state,'agent_execution_service',None)
    if execution_service:
     await execution_service.re_execute_agent(project_id,data.targetAgentId)
  intervention["activationResult"]=activation_result
 return intervention


@router.get("/interventions/{intervention_id}")
async def get_intervention(intervention_id:str):
 data_store=get_data_store()
 intervention=data_store.get_intervention(intervention_id)
 if not intervention:
  raise HTTPException(status_code=404,detail="介入が見つかりません")
 return intervention


@router.delete("/interventions/{intervention_id}",status_code=204)
async def delete_intervention(intervention_id:str):
 data_store=get_data_store()
 socket_manager=get_socket_manager()
 intervention=data_store.get_intervention(intervention_id)
 if not intervention:
  raise HTTPException(status_code=404,detail="介入が見つかりません")
 project_id=intervention["projectId"]
 success=data_store.delete_intervention(intervention_id)
 if success:
  await socket_manager.emit_to_project('intervention:deleted',{
   "interventionId":intervention_id,
   "projectId":project_id
  },project_id)
 return None


@router.post("/interventions/{intervention_id}/respond")
async def respond_to_intervention(intervention_id:str,data:InterventionResponse):
 data_store=get_data_store()
 socket_manager=get_socket_manager()
 intervention=data_store.get_intervention(intervention_id)
 if not intervention:
  raise HTTPException(status_code=404,detail="介入が見つかりません")
 result=data_store.respond_to_intervention(intervention_id,data.message)
 if result:
  await socket_manager.emit_to_project('intervention:responded',{
   "interventionId":intervention_id,
   "projectId":intervention["projectId"],
   "message":data.message
  },intervention["projectId"])
 return result


@router.get("/agents/{agent_id}/pending-interventions")
async def get_pending_interventions_for_agent(agent_id:str):
 data_store=get_data_store()
 return data_store.get_pending_interventions_for_agent(agent_id)
