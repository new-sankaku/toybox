from fastapi import APIRouter,Request,HTTPException
from typing import Dict,Any,Optional,List
from pydantic import BaseModel
from config_loader import get_status_labels
from core.dependencies import get_data_store,get_socket_manager
from middleware.logger import get_logger

router=APIRouter()


class ProjectCreate(BaseModel):
 name:str
 description:Optional[str]=None
 concept:Optional[Dict[str,Any]]=None
 aiServices:Optional[Dict[str,Any]]=None


class ProjectUpdate(BaseModel):
 name:Optional[str]=None
 description:Optional[str]=None
 status:Optional[str]=None
 concept:Optional[Dict[str,Any]]=None
 config:Optional[Dict[str,Any]]=None


class BrushupOptions(BaseModel):
 selectedAgents:List[str]=[]
 agentOptions:Dict[str,List[str]]={}
 agentInstructions:Dict[str,str]={}
 clearAssets:bool=False
 presets:List[str]=[]
 customInstruction:str=""
 referenceImageIds:List[str]=[]


@router.get("/projects")
async def list_projects():
 data_store=get_data_store()
 return data_store.get_projects()


@router.post("/projects",status_code=201)
async def create_project(data:ProjectCreate):
 data_store=get_data_store()
 socket_manager=get_socket_manager()
 project=data_store.create_project(data.model_dump(exclude_none=True))
 await socket_manager.emit('project:updated',project)
 return project


@router.patch("/projects/{project_id}")
async def update_project(project_id:str,data:ProjectUpdate):
 data_store=get_data_store()
 socket_manager=get_socket_manager()
 project=data_store.update_project(project_id,data.model_dump(exclude_none=True))
 if not project:
  raise HTTPException(status_code=404,detail="プロジェクトが見つかりません")
 await socket_manager.emit('project:updated',project)
 return project


@router.delete("/projects/{project_id}",status_code=204)
async def delete_project(project_id:str):
 data_store=get_data_store()
 success=data_store.delete_project(project_id)
 if not success:
  raise HTTPException(status_code=404,detail="プロジェクトが見つかりません")
 return None


@router.post("/projects/{project_id}/start")
async def start_project(project_id:str):
 data_store=get_data_store()
 socket_manager=get_socket_manager()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="プロジェクトが見つかりません")
 current_status=project["status"]
 if current_status not in ("draft","paused"):
  status_label=get_status_labels().get(current_status,current_status)
  raise HTTPException(
   status_code=400,
   detail=f"プロジェクトを開始できません。現在のステータス「{status_label}」では開始操作は実行できません。"
  )
 from services.llm_job_queue import get_llm_job_queue
 job_queue=get_llm_job_queue()
 cleaned=job_queue.cleanup_project_jobs(project_id)
 if cleaned>0:
  get_logger().info(f"start_project: cleaned {cleaned} incomplete jobs for project {project_id}")
 project=data_store.update_project(project_id,{"status":"running"})
 await socket_manager.emit_to_project('project:status_changed',{
  "projectId":project_id,
  "status":"running",
  "previousStatus":project.get("status","draft")
 },project_id)
 return project


@router.post("/projects/{project_id}/pause")
async def pause_project(project_id:str):
 data_store=get_data_store()
 socket_manager=get_socket_manager()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="プロジェクトが見つかりません")
 current_status=project["status"]
 if current_status!="running":
  status_label=get_status_labels().get(current_status,current_status)
  raise HTTPException(
   status_code=400,
   detail=f"プロジェクトを一時停止できません。現在のステータス「{status_label}」では一時停止操作は実行できません。"
  )
 project=data_store.update_project(project_id,{"status":"paused"})
 await socket_manager.emit_to_project('project:status_changed',{
  "projectId":project_id,
  "status":"paused",
  "previousStatus":"running"
 },project_id)
 return project


@router.post("/projects/{project_id}/resume")
async def resume_project(project_id:str):
 data_store=get_data_store()
 socket_manager=get_socket_manager()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="プロジェクトが見つかりません")
 current_status=project["status"]
 resumable_statuses={"paused","interrupted"}
 if current_status not in resumable_statuses:
  status_label=get_status_labels().get(current_status,current_status)
  raise HTTPException(
   status_code=400,
   detail=f"プロジェクトを再開できません。現在のステータス「{status_label}」では再開操作は実行できません。"
  )
 from services.llm_job_queue import get_llm_job_queue
 job_queue=get_llm_job_queue()
 cleaned=job_queue.cleanup_project_jobs(project_id)
 if cleaned>0:
  get_logger().info(f"resume_project: cleaned {cleaned} incomplete jobs for project {project_id}")
 retried_count=0
 if current_status=="interrupted":
  interrupted_agents=data_store.get_interrupted_agents(project_id)
  for agent in interrupted_agents:
   result=data_store.retry_agent(agent["id"])
   if result:
    retried_count+=1
  if retried_count>0:
   get_logger().info(f"resume_project: auto-retried {retried_count} interrupted agents for project {project_id}")
 project=data_store.update_project(project_id,{"status":"running"})
 await socket_manager.emit_to_project('project:status_changed',{
  "projectId":project_id,
  "status":"running",
  "previousStatus":current_status,
  "retriedAgents":retried_count
 },project_id)
 return project


@router.post("/projects/{project_id}/initialize")
async def initialize_project(project_id:str):
 data_store=get_data_store()
 socket_manager=get_socket_manager()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="プロジェクトが見つかりません")
 from services.llm_job_queue import get_llm_job_queue
 job_queue=get_llm_job_queue()
 cleaned=job_queue.cleanup_project_jobs(project_id)
 if cleaned>0:
  get_logger().info(f"initialize_project: cleaned {cleaned} incomplete jobs for project {project_id}")
 project=data_store.initialize_project(project_id)
 await socket_manager.emit_to_project('project:initialized',{"projectId":project_id},project_id)
 return project


@router.post("/projects/{project_id}/brushup")
async def brushup_project(project_id:str,options:BrushupOptions):
 data_store=get_data_store()
 socket_manager=get_socket_manager()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="プロジェクトが見つかりません")
 if project["status"]!="completed":
  raise HTTPException(status_code=400,detail="完了したプロジェクトのみブラッシュアップできます")
 project=data_store.brushup_project(project_id,options.model_dump())
 await socket_manager.emit_to_project('project:status_changed',{
  "projectId":project_id,
  "status":"draft",
  "previousStatus":"completed"
 },project_id)
 return project


@router.get("/projects/{project_id}/ai-services")
async def get_project_ai_services(project_id:str):
 data_store=get_data_store()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="プロジェクトが見つかりません")
 return data_store.get_ai_services(project_id)


@router.put("/projects/{project_id}/ai-services")
async def update_project_ai_services(project_id:str,data:Dict[str,Any]):
 data_store=get_data_store()
 socket_manager=get_socket_manager()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="プロジェクトが見つかりません")
 ai_services=data_store.update_ai_services(project_id,data)
 if ai_services is None:
  raise HTTPException(status_code=400,detail="AI設定の更新に失敗しました")
 await socket_manager.emit('project:updated',data_store.get_project(project_id))
 return ai_services


@router.patch("/projects/{project_id}/ai-services/{service_type}")
async def update_project_ai_service(project_id:str,service_type:str,data:Dict[str,Any]):
 data_store=get_data_store()
 socket_manager=get_socket_manager()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="プロジェクトが見つかりません")
 result=data_store.update_ai_service(project_id,service_type,data)
 if result is None:
  raise HTTPException(status_code=404,detail=f"サービスが見つかりません: {service_type}")
 await socket_manager.emit('project:updated',data_store.get_project(project_id))
 return result
