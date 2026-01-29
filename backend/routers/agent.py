from fastapi import APIRouter,Request,HTTPException,Query
from core.dependencies import get_data_store,get_socket_manager
from middleware.error_handler import NotFoundError,ValidationError,ApiError

router=APIRouter()


def _get_execution_service(request:Request):
 return getattr(request.app.state,'agent_execution_service',None)


@router.get("/projects/{project_id}/agents")
async def list_project_agents(project_id:str,includeWorkers:bool=True):
 data_store=get_data_store()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="Project not found")
 return data_store.get_agents_by_project(project_id,include_workers=includeWorkers)


@router.get("/projects/{project_id}/agents/leaders")
async def list_project_leaders(project_id:str):
 data_store=get_data_store()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="Project not found")
 return data_store.get_agents_by_project(project_id,include_workers=False)


@router.get("/agents/{agent_id}")
async def get_agent(agent_id:str):
 data_store=get_data_store()
 agent=data_store.get_agent(agent_id)
 if not agent:
  raise HTTPException(status_code=404,detail="Agent not found")
 return agent


@router.get("/agents/{agent_id}/workers")
async def list_agent_workers(agent_id:str):
 data_store=get_data_store()
 agent=data_store.get_agent(agent_id)
 if not agent:
  raise HTTPException(status_code=404,detail="Agent not found")
 return data_store.get_workers_by_parent(agent_id)


@router.get("/agents/{agent_id}/logs")
async def get_agent_logs(agent_id:str):
 data_store=get_data_store()
 agent=data_store.get_agent(agent_id)
 if not agent:
  raise HTTPException(status_code=404,detail="Agent not found")
 return data_store.get_agent_logs(agent_id)


@router.post("/agents/{agent_id}/execute")
async def execute_agent(agent_id:str,request:Request):
 data_store=get_data_store()
 execution_service=_get_execution_service(request)
 if not execution_service:
  raise HTTPException(status_code=503,detail="Agent execution service not available")
 agent=data_store.get_agent(agent_id)
 if not agent:
  raise HTTPException(status_code=404,detail="Agent not found")
 project_id=agent.get("projectId")
 if not project_id:
  raise HTTPException(status_code=400,detail="Agent has no project")
 try:
  result=await execution_service.execute_agent(project_id,agent_id)
 except Exception as e:
  raise HTTPException(status_code=500,detail=f"Execution failed: {str(e)}")
 if result.get("success"):
  return {"success":True,"output":result.get("output")}
 else:
  raise HTTPException(status_code=400,detail=result.get("error","Unknown error"))


@router.post("/agents/{agent_id}/execute-with-workers")
async def execute_leader_with_workers(agent_id:str,request:Request):
 data_store=get_data_store()
 execution_service=_get_execution_service(request)
 if not execution_service:
  raise HTTPException(status_code=503,detail="Agent execution service not available")
 agent=data_store.get_agent(agent_id)
 if not agent:
  raise HTTPException(status_code=404,detail="Agent not found")
 project_id=agent.get("projectId")
 if not project_id:
  raise HTTPException(status_code=400,detail="Agent has no project")
 agent_type=agent.get("type","")
 if not agent_type.endswith("_leader"):
  raise HTTPException(status_code=400,detail="Agent must be a leader type")
 try:
  result=await execution_service.execute_leader_with_workers(project_id,agent_id)
 except Exception as e:
  raise HTTPException(status_code=500,detail=f"Execution failed: {str(e)}")
 if result.get("success"):
  return {"success":True,"results":result.get("results")}
 else:
  raise HTTPException(status_code=400,detail=result.get("error","Unknown error"))


@router.post("/agents/{agent_id}/cancel")
async def cancel_agent(agent_id:str,request:Request):
 data_store=get_data_store()
 execution_service=_get_execution_service(request)
 if not execution_service:
  raise HTTPException(status_code=503,detail="Agent execution service not available")
 agent=data_store.get_agent(agent_id)
 if not agent:
  raise HTTPException(status_code=404,detail="Agent not found")
 cancelled=execution_service.cancel_agent(agent_id)
 if cancelled:
  return {"success":True,"message":"Agent cancelled"}
 else:
  return {"success":False,"message":"Agent not running or already completed"}


@router.post("/agents/{agent_id}/retry")
async def retry_agent(agent_id:str):
 data_store=get_data_store()
 agent=data_store.get_agent(agent_id)
 if not agent:
  raise HTTPException(status_code=404,detail="Agent not found")
 retryable_statuses={"failed","interrupted"}
 if agent.get("status") not in retryable_statuses:
  raise HTTPException(status_code=400,detail=f"Agent status must be one of {retryable_statuses} to retry")
 result=data_store.retry_agent(agent_id)
 if result:
  return {"success":True,"agent":result}
 else:
  raise HTTPException(status_code=500,detail="Failed to retry agent")


@router.post("/agents/{agent_id}/pause")
async def pause_agent(agent_id:str):
 data_store=get_data_store()
 socket_manager=get_socket_manager()
 agent=data_store.get_agent(agent_id)
 if not agent:
  raise HTTPException(status_code=404,detail="Agent not found")
 pausable_statuses={"running","waiting_approval"}
 if agent.get("status") not in pausable_statuses:
  raise HTTPException(status_code=400,detail=f"Agent status must be one of {pausable_statuses} to pause")
 result=data_store.pause_agent(agent_id)
 if result:
  await socket_manager.emit_to_project('agent:paused',{
   "agentId":agent_id,
   "projectId":result["projectId"],
   "agent":result
  },result['projectId'])
  return {"success":True,"agent":result}
 else:
  raise HTTPException(status_code=500,detail="Failed to pause agent")


@router.post("/agents/{agent_id}/resume")
async def resume_agent(agent_id:str):
 data_store=get_data_store()
 socket_manager=get_socket_manager()
 agent=data_store.get_agent(agent_id)
 if not agent:
  raise HTTPException(status_code=404,detail="Agent not found")
 resumable_statuses={"paused","waiting_response"}
 if agent.get("status") not in resumable_statuses:
  raise HTTPException(status_code=400,detail=f"Agent status must be one of {resumable_statuses} to resume")
 result=data_store.resume_agent(agent_id)
 if result:
  await socket_manager.emit_to_project('agent:resumed',{
   "agentId":agent_id,
   "projectId":result["projectId"],
   "agent":result
  },result['projectId'])
  return {"success":True,"agent":result}
 else:
  raise HTTPException(status_code=500,detail="Failed to resume agent")


@router.get("/projects/{project_id}/agents/retryable")
async def get_retryable_agents(project_id:str):
 data_store=get_data_store()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="Project not found")
 return data_store.get_retryable_agents(project_id)


@router.get("/projects/{project_id}/agents/interrupted")
async def get_interrupted_agents(project_id:str):
 data_store=get_data_store()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="Project not found")
 return data_store.get_interrupted_agents(project_id)
