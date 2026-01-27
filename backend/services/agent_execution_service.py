import asyncio
import os
import threading
from datetime import datetime
from typing import Optional,Dict,Any,Callable
from agents.base import AgentContext,AgentType,AgentStatus,AgentOutput
from agents.api_runner import ApiAgentRunner,LeaderWorkerOrchestrator
from agents.exceptions import ProviderUnavailableError,MaxRetriesExceededError
from agents.retry_strategy import wait_for_provider_available
from providers.health_monitor import get_health_monitor
from config_loader import get_workflow_dependencies
from middleware.logger import get_logger


class AgentExecutionService:
 def __init__(self,data_store,sio=None):
  self._data_store=data_store
  self._sio=sio
  self._agent_runner:Optional[ApiAgentRunner]=None
  self._running_agents:Dict[str,bool]={}
  self._lock=threading.Lock()
  self._logger=get_logger()

 def set_agent_runner(self,runner:ApiAgentRunner)->None:
  self._agent_runner=runner
  if runner:
   runner.set_data_store(self._data_store)
   runner.set_status_callback(self._on_agent_status_change)

 def _on_agent_status_change(self,agent_id:str,status:AgentStatus)->None:
  self._update_agent_status(agent_id,status)

 def _update_agent_status(self,agent_id:str,status:AgentStatus)->None:
  status_map={
   AgentStatus.PENDING:"pending",
   AgentStatus.RUNNING:"running",
   AgentStatus.WAITING_APPROVAL:"waiting_approval",
   AgentStatus.WAITING_RESPONSE:"waiting_response",
   AgentStatus.WAITING_PROVIDER:"waiting_provider",
   AgentStatus.PAUSED:"paused",
   AgentStatus.COMPLETED:"completed",
   AgentStatus.FAILED:"failed",
  }
  self._data_store.update_agent(agent_id,{"status":status_map.get(status,"running")})

 def _emit_event(self,event:str,data:Dict,project_id:str)->None:
  if self._sio:
   try:
    self._sio.emit(event,data,room=f"project:{project_id}")
   except Exception as e:
    self._logger.error(f"Error emitting {event}: {e}",exc_info=True)

 async def execute_agent(self,project_id:str,agent_id:str)->Dict[str,Any]:
  if not self._agent_runner:
   self._logger.warning(f"execute_agent called but agent_runner not configured: agent_id={agent_id}")
   return {"success":False,"error":"Agent runner not configured"}
  agent=self._data_store.get_agent(agent_id)
  if not agent:
   self._logger.warning(f"execute_agent: agent not found: agent_id={agent_id}")
   return {"success":False,"error":"Agent not found"}
  project=self._data_store.get_project(project_id)
  if not project:
   self._logger.warning(f"execute_agent: project not found: project_id={project_id}")
   return {"success":False,"error":"Project not found"}
  if not self._can_start_agent(project_id,agent["type"]):
   self._logger.info(f"execute_agent: dependencies not met: agent_type={agent['type']} project_id={project_id}")
   return {"success":False,"error":"Dependencies not met"}
  try:
   agent_type=AgentType(agent["type"])
  except ValueError:
   return {"success":False,"error":f"Unknown agent type: {agent['type']}"}
  self._data_store.update_agent(agent_id,{
   "status":"running",
   "progress":0,
   "startedAt":datetime.now().isoformat(),
   "currentTask":"初期化中"
  })
  self._emit_event("agent:started",{
   "agentId":agent_id,
   "projectId":project_id,
   "agent":self._data_store.get_agent(agent_id)
  },project_id)
  context=AgentContext(
   project_id=project_id,
   agent_id=agent_id,
   agent_type=agent_type,
   project_concept=project.get("concept",{}),
   previous_outputs=self._get_previous_outputs(project_id,agent["type"]),
   config=project.get("config",{}),
   on_progress=lambda p,t:self._on_progress(agent_id,project_id,p,t),
   on_log=lambda l,m:self._on_log(agent_id,project_id,l,m),
   on_checkpoint=lambda t,d:self._on_checkpoint(agent_id,project_id,t,d),
  )
  with self._lock:
   self._running_agents[agent_id]=True
  try:
   provider_id=self._get_provider_id_for_agent(project,agent["type"])
   if provider_id:
    health_monitor=get_health_monitor()
    health=health_monitor.get_health_status(provider_id)
    if health and not health.available:
     def on_waiting(attempt:int)->None:
      self._data_store.update_agent(agent_id,{
       "status":"waiting_provider",
       "currentTask":f"API接続待機中 ({provider_id}, 確認{attempt}回目)",
      })
      self._emit_event("agent:waiting_provider",{
       "agentId":agent_id,
       "projectId":project_id,
       "providerId":provider_id,
       "attempt":attempt,
      },project_id)
     def on_recovered(attempt:int)->None:
      self._data_store.update_agent(agent_id,{
       "status":"running",
       "currentTask":"API接続回復、処理再開",
      })
      self._emit_event("agent:progress",{
       "agentId":agent_id,
       "projectId":project_id,
       "message":f"API接続回復 ({attempt}回の確認後)",
      },project_id)
     await wait_for_provider_available(
      health_monitor,
      provider_id,
      check_interval=10.0,
      on_waiting=on_waiting,
      on_recovered=on_recovered,
     )
   output=await self._agent_runner.run_agent(context)
   if output.status==AgentStatus.COMPLETED:
    self._data_store.update_agent(agent_id,{
     "status":"completed",
     "progress":100,
     "completedAt":datetime.now().isoformat(),
     "currentTask":None,
     "tokensUsed":output.tokens_used,
    })
    self._emit_event("agent:completed",{
     "agentId":agent_id,
     "projectId":project_id,
     "agent":self._data_store.get_agent(agent_id)
    },project_id)
    return {"success":True,"output":output.output}
   else:
    self._data_store.update_agent(agent_id,{
     "status":"failed",
     "error":output.error,
     "currentTask":None,
    })
    self._emit_event("agent:failed",{
     "agentId":agent_id,
     "projectId":project_id,
     "error":output.error
    },project_id)
    return {"success":False,"error":output.error}
  except Exception as e:
   self._logger.error(f"execute_agent failed: agent_id={agent_id} project_id={project_id} error={e}",exc_info=True)
   self._data_store.update_agent(agent_id,{
    "status":"failed",
    "error":str(e),
    "currentTask":None,
   })
   self._emit_event("agent:failed",{
    "agentId":agent_id,
    "projectId":project_id,
    "error":str(e)
   },project_id)
   return {"success":False,"error":str(e)}
  finally:
   with self._lock:
    self._running_agents.pop(agent_id,None)

 async def execute_leader_with_workers(
  self,
  project_id:str,
  leader_agent_id:str
 )->Dict[str,Any]:
  if not self._agent_runner:
   return {"success":False,"error":"Agent runner not configured"}
  agent=self._data_store.get_agent(leader_agent_id)
  if not agent:
   return {"success":False,"error":"Leader agent not found"}
  project=self._data_store.get_project(project_id)
  if not project:
   return {"success":False,"error":"Project not found"}
  try:
   agent_type=AgentType(agent["type"])
  except ValueError:
   return {"success":False,"error":f"Unknown agent type: {agent['type']}"}
  quality_settings=self._data_store.get_quality_settings(project_id)
  quality_dict={k:{"enabled":v.enabled,"maxRetries":v.max_retries} for k,v in quality_settings.items()}
  orchestrator=LeaderWorkerOrchestrator(
   agent_runner=self._agent_runner,
   quality_settings=quality_dict,
   on_progress=lambda t,p,m:self._on_progress(leader_agent_id,project_id,p,m),
   on_checkpoint=lambda t,d:self._on_checkpoint(leader_agent_id,project_id,t,d),
   on_worker_created=lambda w,t:self._on_worker_created(project_id,leader_agent_id,w,t),
   on_worker_status=lambda w,s,d:self._on_worker_status(project_id,w,s,d),
  )
  self._data_store.update_agent(leader_agent_id,{
   "status":"running",
   "progress":0,
   "startedAt":datetime.now().isoformat(),
   "currentTask":"Leader実行開始"
  })
  self._emit_event("agent:started",{
   "agentId":leader_agent_id,
   "projectId":project_id,
   "agent":self._data_store.get_agent(leader_agent_id)
  },project_id)
  context=AgentContext(
   project_id=project_id,
   agent_id=leader_agent_id,
   agent_type=agent_type,
   project_concept=project.get("concept",{}),
   previous_outputs=self._get_previous_outputs(project_id,agent["type"]),
   config=project.get("config",{}),
   on_progress=lambda p,t:self._on_progress(leader_agent_id,project_id,p,t),
   on_log=lambda l,m:self._on_log(leader_agent_id,project_id,l,m),
  )
  with self._lock:
   self._running_agents[leader_agent_id]=True
  try:
   provider_id=self._get_provider_id_for_agent(project,agent["type"])
   if provider_id:
    health_monitor=get_health_monitor()
    health=health_monitor.get_health_status(provider_id)
    if health and not health.available:
     def on_waiting_leader(attempt:int)->None:
      self._data_store.update_agent(leader_agent_id,{
       "status":"waiting_provider",
       "currentTask":f"API接続待機中 ({provider_id}, 確認{attempt}回目)",
      })
      self._emit_event("agent:waiting_provider",{
       "agentId":leader_agent_id,
       "projectId":project_id,
       "providerId":provider_id,
       "attempt":attempt,
      },project_id)
     def on_recovered_leader(attempt:int)->None:
      self._data_store.update_agent(leader_agent_id,{
       "status":"running",
       "currentTask":"API接続回復、処理再開",
      })
     await wait_for_provider_available(
      health_monitor,
      provider_id,
      check_interval=10.0,
      on_waiting=on_waiting_leader,
      on_recovered=on_recovered_leader,
     )
   results=await orchestrator.run_leader_with_workers(context)
   if results.get("human_review_required"):
    self._data_store.update_agent(leader_agent_id,{
     "status":"waiting_approval",
     "currentTask":"レビュー待ち",
    })
   else:
    self._data_store.update_agent(leader_agent_id,{
     "status":"completed",
     "progress":100,
     "completedAt":datetime.now().isoformat(),
     "currentTask":None,
    })
    self._emit_event("agent:completed",{
     "agentId":leader_agent_id,
     "projectId":project_id,
     "agent":self._data_store.get_agent(leader_agent_id)
    },project_id)
   return {"success":True,"results":results}
  except Exception as e:
   self._logger.error(f"execute_leader_with_workers failed: leader_id={leader_agent_id} project_id={project_id} error={e}",exc_info=True)
   self._data_store.update_agent(leader_agent_id,{
    "status":"failed",
    "error":str(e),
    "currentTask":None,
   })
   self._emit_event("agent:failed",{
    "agentId":leader_agent_id,
    "projectId":project_id,
    "error":str(e)
   },project_id)
   return {"success":False,"error":str(e)}
  finally:
   with self._lock:
    self._running_agents.pop(leader_agent_id,None)

 def _get_provider_id_for_agent(self,project:Dict,agent_type:str)->Optional[str]:
  ai_services=project.get("aiServices",{})
  text_service=ai_services.get("text",{})
  return text_service.get("provider")

 def _can_start_agent(self,project_id:str,agent_type:str)->bool:
  workflow_deps=get_workflow_dependencies()
  dependencies=workflow_deps.get(agent_type,[])
  agents=self._data_store.get_agents_by_project(project_id)
  for dep_type in dependencies:
   dep_agent=next((a for a in agents if a["type"]==dep_type),None)
   if not dep_agent or dep_agent["status"]!="completed":
    return False
  return True

 def _get_previous_outputs(self,project_id:str,agent_type:str)->Dict[str,Any]:
  workflow_deps=get_workflow_dependencies()
  dependencies=workflow_deps.get(agent_type,[])
  agents=self._data_store.get_agents_by_project(project_id)
  outputs={}
  for dep_type in dependencies:
   dep_agent=next((a for a in agents if a["type"]==dep_type),None)
   if dep_agent and dep_agent["status"]=="completed":
    traces=self._data_store.get_traces_by_agent(dep_agent["id"])
    if traces:
     latest=traces[0]
     outputs[dep_type]={"content":latest.get("llmResponse","")}
  return outputs

 def _on_progress(self,agent_id:str,project_id:str,progress:int,task:str)->None:
  self._data_store.update_agent(agent_id,{
   "progress":progress,
   "currentTask":task,
  })
  self._emit_event("agent:progress",{
   "agentId":agent_id,
   "projectId":project_id,
   "progress":progress,
   "currentTask":task,
  },project_id)
  self._check_pending_interventions(agent_id,project_id)

 def _check_pending_interventions(self,agent_id:str,project_id:str)->None:
  pending=self._data_store.get_pending_interventions_for_agent(agent_id)
  if not pending:
   return
  agent=self._data_store.get_agent(agent_id)
  if not agent or agent.get("status")!="running":
   return
  for intervention in pending:
   self._data_store.acknowledge_intervention(intervention["id"])
   self._emit_event("intervention:acknowledged",{
    "interventionId":intervention["id"],
    "projectId":project_id,
    "agentId":agent_id,
   },project_id)
  self._data_store.update_agent(agent_id,{
   "status":"waiting_response",
   "currentTask":"連絡を確認中",
  })
  self._emit_event("agent:waiting_response",{
   "agentId":agent_id,
   "projectId":project_id,
   "agent":self._data_store.get_agent(agent_id),
   "interventionCount":len(pending),
  },project_id)

 def _on_log(self,agent_id:str,project_id:str,level:str,message:str)->None:
  self._data_store.add_agent_log(agent_id,level,message)
  self._emit_event("agent:log",{
   "agentId":agent_id,
   "entry":{
    "id":f"{agent_id}_{datetime.now().timestamp()}",
    "timestamp":datetime.now().isoformat(),
    "level":level,
    "message":message,
   }
  },project_id)

 def _on_checkpoint(self,agent_id:str,project_id:str,cp_type:str,data:Dict)->None:
  self._data_store.create_checkpoint(project_id,agent_id,{
   "type":cp_type,
   "title":data.get("title","レビュー"),
   "description":data.get("description",""),
   "output":data.get("output",{}),
  })
  self._data_store.update_agent(agent_id,{"status":"waiting_approval"})
  self._emit_event("checkpoint:created",{
   "projectId":project_id,
   "agentId":agent_id,
   "checkpoint":data,
  },project_id)

 def _on_worker_created(self,project_id:str,parent_agent_id:str,worker_type:str,task:str)->str:
  worker=self._data_store.create_worker_agent(project_id,parent_agent_id,worker_type,task)
  worker_id=worker["id"]
  self._emit_event("agent:created",{
   "agentId":worker_id,
   "projectId":project_id,
   "parentAgentId":parent_agent_id,
   "agent":worker
  },project_id)
  return worker_id

 def _on_worker_status(self,project_id:str,worker_id:str,status:str,data:Dict)->None:
  update_data={"status":status}
  if status=="running":
   update_data["startedAt"]=datetime.now().isoformat()
   update_data["progress"]=data.get("progress",0)
  elif status=="completed":
   update_data["completedAt"]=datetime.now().isoformat()
   update_data["progress"]=100
   update_data["tokensUsed"]=data.get("tokensUsed",0)
   update_data["inputTokens"]=data.get("inputTokens",0)
   update_data["outputTokens"]=data.get("outputTokens",0)
  elif status=="failed":
   update_data["error"]=data.get("error","")
  if"currentTask" in data:
   update_data["currentTask"]=data["currentTask"]
  self._data_store.update_agent(worker_id,update_data)
  self._emit_event(f"agent:{status}",{
   "agentId":worker_id,
   "projectId":project_id,
   "agent":self._data_store.get_agent(worker_id)
  },project_id)

 def get_running_agents(self)->Dict[str,bool]:
  with self._lock:
   return dict(self._running_agents)

 def cancel_agent(self,agent_id:str)->bool:
  with self._lock:
   if agent_id in self._running_agents:
    self._running_agents.pop(agent_id,None)
    self._data_store.update_agent(agent_id,{
     "status":"failed",
     "error":"キャンセルされました",
     "currentTask":None,
    })
    agent=self._data_store.get_agent(agent_id)
    if agent:
     project_id=agent.get("projectId","")
     self._emit_event("agent:failed",{
      "agentId":agent_id,
      "projectId":project_id,
      "error":"キャンセルされました"
     },project_id)
    return True
  return False

 def re_execute_agent(self,project_id:str,agent_id:str)->None:
  def _run():
   loop=asyncio.new_event_loop()
   asyncio.set_event_loop(loop)
   try:
    agent=self._data_store.get_agent(agent_id)
    if not agent:
     self._logger.warning(f"re_execute_agent: agent not found: agent_id={agent_id}")
     return
    self._logger.info(f"re_execute_agent: starting agent_id={agent_id} type={agent.get('type','')} project_id={project_id}")
    if agent.get("type","").endswith("_leader"):
     loop.run_until_complete(self.execute_leader_with_workers(project_id,agent_id))
    else:
     loop.run_until_complete(self.execute_agent(project_id,agent_id))
   except Exception as e:
    self._logger.error(f"re_execute_agent failed: agent_id={agent_id} error={e}",exc_info=True)
   finally:
    loop.close()
  thread=threading.Thread(target=_run,daemon=True)
  thread.start()
