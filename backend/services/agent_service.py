from typing import Optional,Dict,List
from .base import BaseService
from models.database import session_scope
from repositories import AgentRepository,AgentLogRepository


class AgentService(BaseService):

 def get_by_project(self,project_id:str)->List[Dict]:
  with session_scope() as session:
   repo = AgentRepository(session)
   return repo.get_by_project(project_id)

 def get(self,agent_id:str)->Optional[Dict]:
  with session_scope() as session:
   repo = AgentRepository(session)
   return repo.get_dict(agent_id)

 def get_logs(self,agent_id:str)->List[Dict]:
  with session_scope() as session:
   repo = AgentLogRepository(session)
   return repo.get_by_agent(agent_id)

 def create(self,project_id:str,agent_type:str)->Dict:
  with session_scope() as session:
   repo = AgentRepository(session)
   return repo.create_from_dict(project_id,{"type":agent_type})

 def update(self,agent_id:str,data:Dict)->Optional[Dict]:
  with session_scope() as session:
   repo = AgentRepository(session)
   return repo.update_from_dict(agent_id,data)

 def add_log(self,agent_id:str,level:str,message:str,progress:Optional[int]=None):
  with session_scope() as session:
   repo = AgentLogRepository(session)
   repo.add_log(agent_id,level,message,progress)
