import asyncio
from typing import Any,Dict,List,Optional,TYPE_CHECKING
from .base import Skill,SkillResult,SkillContext,SkillCategory,SkillParameter
from middleware.logger import get_logger

if TYPE_CHECKING:
 from services.agent_service import AgentService
 from services.agent_execution_service import AgentExecutionService


class SpawnWorkerSkill(Skill):
 name="spawn_worker"
 description="新しいワーカーエージェントを生成して実行します（リーダー専用）"
 category=SkillCategory.ORCHESTRATION
 parameters=[
  SkillParameter(name="operation",type="string",description="操作: spawn, spawn_batch, list_workers"),
  SkillParameter(name="worker_type",type="string",description="ワーカーのタイプ（spawn時）",required=False),
  SkillParameter(name="task",type="string",description="ワーカーに割り当てるタスク（spawn時）",required=False),
  SkillParameter(name="workers",type="array",description="バッチ生成するワーカー定義のリスト（spawn_batch時）",required=False,default=[]),
 ]

 def __init__(self,agent_service:"AgentService",execution_service:"AgentExecutionService",event_bus=None):
  super().__init__()
  self._agent_service=agent_service
  self._execution_service=execution_service
  self._event_bus=event_bus

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  operation=kwargs.get("operation","")
  if operation=="spawn":
   return await self._spawn_worker(context,kwargs)
  elif operation=="spawn_batch":
   return await self._spawn_batch(context,kwargs)
  elif operation=="list_workers":
   return self._list_workers(context)
  else:
   return SkillResult(success=False,error=f"Unknown operation: {operation}. Use: spawn, spawn_batch, list_workers")

 async def _spawn_worker(self,context:SkillContext,kwargs:Dict)->SkillResult:
  worker_type=kwargs.get("worker_type","")
  task=kwargs.get("task","")
  if not worker_type:
   return SkillResult(success=False,error="worker_type is required")
  if not task:
   return SkillResult(success=False,error="task is required")
  try:
   worker=self._agent_service.create_worker_agent(
    context.project_id,context.agent_id,worker_type,task
   )
   worker_id=worker["id"]
   if self._event_bus:
    try:
     from events.events import AgentCreated
     self._event_bus.publish(AgentCreated(project_id=context.project_id,agent_id=worker_id,parent_agent_id=context.agent_id,agent=worker))
    except Exception as e:
     get_logger().warning(f"Failed to publish AgentCreated: {e}")
   try:
    result=await self._execution_service.execute_agent(context.project_id,worker_id)
    return SkillResult(success=True,output={
     "workerId":worker_id,
     "workerType":worker_type,
     "task":task,
     "executionResult":result,
    },metadata={"workerId":worker_id})
   except Exception as e:
    get_logger().error(f"Worker execution failed: {e}",exc_info=True)
    return SkillResult(success=True,output={
     "workerId":worker_id,
     "workerType":worker_type,
     "task":task,
     "executionResult":{"success":False,"error":str(e)},
    },metadata={"workerId":worker_id,"executionError":str(e)})
  except Exception as e:
   get_logger().error(f"spawn_worker failed: {e}",exc_info=True)
   return SkillResult(success=False,error=f"Failed to spawn worker: {e}")

 async def _spawn_batch(self,context:SkillContext,kwargs:Dict)->SkillResult:
  workers=kwargs.get("workers",[])
  if not workers:
   return SkillResult(success=False,error="workers list is required and must not be empty")
  results=[]
  for worker_def in workers:
   wtype=worker_def.get("worker_type","")
   wtask=worker_def.get("task","")
   if not wtype or not wtask:
    results.append({"success":False,"error":"worker_type and task are required for each worker"})
    continue
   result=await self._spawn_worker(context,{"worker_type":wtype,"task":wtask})
   results.append(result.to_dict())
  success_count=sum(1 for r in results if r.get("success",False))
  return SkillResult(success=True,output={
   "total":len(workers),
   "succeeded":success_count,
   "failed":len(workers)-success_count,
   "results":results,
  },metadata={"total":len(workers),"succeeded":success_count})

 def _list_workers(self,context:SkillContext)->SkillResult:
  try:
   workers=self._agent_service.get_workers_by_parent(context.agent_id)
   summary=[{
    "id":w["id"],
    "type":w["type"],
    "status":w["status"],
    "progress":w["progress"],
    "task":w.get("currentTask",""),
   } for w in workers]
   return SkillResult(success=True,output=summary,metadata={"count":len(summary)})
  except Exception as e:
   return SkillResult(success=False,error=f"Failed to list workers: {e}")
