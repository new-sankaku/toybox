from datetime import datetime
from typing import Dict,List,Optional
from models.database import session_scope
from repositories import ProjectRepository,AgentRepository,SystemLogRepository
from middleware.logger import get_logger


class RecoveryService:
 def __init__(self,sio=None):
  self._sio=sio

 def set_sio(self,sio)->None:
  self._sio=sio

 def _emit_event(self,event:str,data:Dict,project_id:str)->None:
  if self._sio:
   try:
    self._sio.emit(event,data,room=f"project:{project_id}")
   except Exception as e:
    get_logger().warning(f"RecoveryService: error emitting {event}: {e}")

 def recover_interrupted_agents(self)->Dict[str,any]:
  """
  サーバー起動時に呼び出し、running状態のAgentをinterruptedに変更する
  """
  result={"recovered_agents":[],"recovered_projects":[]}
  with session_scope() as session:
   agent_repo=AgentRepository(session)
   proj_repo=ProjectRepository(session)
   syslog_repo=SystemLogRepository(session)
   all_projects=proj_repo.get_all()
   for project in all_projects:
    if project.status=="running":
     project.status="interrupted"
     project.updated_at=datetime.now()
     result["recovered_projects"].append(project.id)
     syslog_repo.add_log(project.id,"warn","System","サーバー再起動によりプロジェクトが中断されました")
    agents=agent_repo.get_by_project(project.id)
    for agent_dict in agents:
     if agent_dict["status"] in ("running","waiting_provider"):
      agent=agent_repo.get(agent_dict["id"])
      if agent:
       agent.status="interrupted"
       agent.current_task="サーバー再起動により中断"
       agent.updated_at=datetime.now()
       session.flush()
       result["recovered_agents"].append({
        "agentId":agent.id,
        "projectId":project.id,
        "previousStatus":agent_dict["status"],
        "type":agent.type
       })
       syslog_repo.add_log(project.id,"warn","System",f"エージェント {agent.type} が中断されました（再試行可能）")
   session.flush()
  if result["recovered_agents"]:
   get_logger().info(f"RecoveryService: recovered {len(result['recovered_agents'])} interrupted agents")
  if result["recovered_projects"]:
   get_logger().info(f"RecoveryService: recovered {len(result['recovered_projects'])} interrupted projects")
  return result

 def get_interrupted_agents(self,project_id:Optional[str]=None)->List[Dict]:
  """
  中断されたAgentの一覧を取得
  """
  with session_scope() as session:
   agent_repo=AgentRepository(session)
   if project_id:
    agents=agent_repo.get_by_project(project_id)
   else:
    agents=[agent_repo.to_dict(a) for a in agent_repo.get_all()]
   return [a for a in agents if a["status"]=="interrupted"]

 def get_retryable_agents(self,project_id:str)->List[Dict]:
  """
  再試行可能なAgent（failed,interrupted）の一覧を取得
  """
  with session_scope() as session:
   agent_repo=AgentRepository(session)
   agents=agent_repo.get_by_project(project_id)
   retryable_statuses={"failed","interrupted"}
   return [a for a in agents if a["status"] in retryable_statuses]
