from typing import Optional,Dict,List

from models.database import session_scope
from repositories import AgentRepository,AgentLogRepository
from events.event_bus import EventBus
from services.base_service import BaseService


class AgentQueryService(BaseService):
    def __init__(self,event_bus:EventBus):
        super().__init__(event_bus)

    def get_agents_by_project(
        self,project_id:str,include_workers:bool=True
    )->List[Dict]:
        with session_scope() as session:
            repo=AgentRepository(session)
            return repo.get_by_project(project_id,include_workers=include_workers)

    def get_workers_by_parent(self,parent_agent_id:str)->List[Dict]:
        with session_scope() as session:
            repo=AgentRepository(session)
            return repo.get_workers_by_parent(parent_agent_id)

    def get_agent(self,agent_id:str)->Optional[Dict]:
        with session_scope() as session:
            repo=AgentRepository(session)
            return repo.get_dict(agent_id)

    def get_agent_logs(self,agent_id:str)->List[Dict]:
        with session_scope() as session:
            repo=AgentLogRepository(session)
            return repo.get_by_agent(agent_id)

    def create_agent(self,project_id:str,agent_type:str)->Dict:
        with session_scope() as session:
            repo=AgentRepository(session)
            return repo.create_from_dict(project_id,{"type":agent_type})

    def create_worker_agent(
        self,
        project_id:str,
        parent_agent_id:str,
        worker_type:str,
        task:str,
    )->Dict:
        with session_scope() as session:
            repo=AgentRepository(session)
            return repo.create_worker(
                project_id,parent_agent_id,worker_type,task
            )

    def update_agent(self,agent_id:str,data:Dict)->Optional[Dict]:
        with session_scope() as session:
            repo=AgentRepository(session)
            return repo.update_from_dict(agent_id,data)

    def add_agent_log(
        self,
        agent_id:str,
        level:str,
        message:str,
        progress:Optional[int]=None,
    )->None:
        with session_scope() as session:
            repo=AgentLogRepository(session)
            repo.add_log(agent_id,level,message,progress)

    @property
    def agents(self)->Dict[str,Dict]:
        result={}
        with session_scope() as session:
            repo=AgentRepository(session)
            for agent in repo.get_all():
                result[agent.id]=repo.to_dict(agent)
        return result
