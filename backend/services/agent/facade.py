from typing import Optional,Dict,List

from events.event_bus import EventBus
from services.base_service import BaseService
from services.agent.query_service import AgentQueryService
from services.agent.lifecycle_manager import AgentLifecycleManager
from services.agent.scheduler import AgentScheduler
from services.agent.memory_manager import AgentMemoryManager


class AgentService(BaseService):
    def __init__(self,event_bus:EventBus):
        super().__init__(event_bus)
        self._query=AgentQueryService(event_bus)
        self._lifecycle=AgentLifecycleManager(event_bus)
        self._scheduler=AgentScheduler(event_bus)
        self._memory=AgentMemoryManager(event_bus)

    def get_agents_by_project(
        self,project_id:str,include_workers:bool=True
    )->List[Dict]:
        return self._query.get_agents_by_project(project_id,include_workers)

    def get_workers_by_parent(self,parent_agent_id:str)->List[Dict]:
        return self._query.get_workers_by_parent(parent_agent_id)

    def get_agent(self,agent_id:str)->Optional[Dict]:
        return self._query.get_agent(agent_id)

    def get_agent_logs(self,agent_id:str)->List[Dict]:
        return self._query.get_agent_logs(agent_id)

    def create_agent(self,project_id:str,agent_type:str)->Dict:
        return self._query.create_agent(project_id,agent_type)

    def create_worker_agent(
        self,
        project_id:str,
        parent_agent_id:str,
        worker_type:str,
        task:str,
    )->Dict:
        return self._query.create_worker_agent(
            project_id,parent_agent_id,worker_type,task
        )

    def update_agent(self,agent_id:str,data:Dict)->Optional[Dict]:
        return self._query.update_agent(agent_id,data)

    def add_agent_log(
        self,
        agent_id:str,
        level:str,
        message:str,
        progress:Optional[int]=None,
    )->None:
        self._query.add_agent_log(agent_id,level,message,progress)

    @property
    def agents(self)->Dict[str,Dict]:
        return self._query.agents

    def retry_agent(self,agent_id:str)->Optional[Dict]:
        return self._lifecycle.retry_agent(agent_id)

    def pause_agent(self,agent_id:str)->Optional[Dict]:
        return self._lifecycle.pause_agent(agent_id)

    def resume_agent(self,agent_id:str)->Optional[Dict]:
        return self._lifecycle.resume_agent(agent_id)

    def get_retryable_agents(self,project_id:str)->List[Dict]:
        return self._lifecycle.get_retryable_agents(project_id)

    def get_interrupted_agents(
        self,project_id:Optional[str]=None
    )->List[Dict]:
        return self._lifecycle.get_interrupted_agents(project_id)

    def activate_agent_for_intervention(
        self,agent_id:str,intervention_id:str
    )->Dict:
        return self._lifecycle.activate_agent_for_intervention(
            agent_id,intervention_id
        )

    def start_next_agents(self,project_id:str)->List[Dict]:
        return self._scheduler.start_next_agents(project_id)

    def create_agent_memory(
        self,
        category:str,
        agent_type:str,
        content:str,
        project_id:Optional[str]=None,
        source_project_id:Optional[str]=None,
        relevance_score:int=100,
    )->Dict:
        return self._memory.create_agent_memory(
            category,
            agent_type,
            content,
            project_id,
            source_project_id,
            relevance_score,
        )

    def get_agent_memories(
        self,
        agent_type:str,
        project_id:Optional[str]=None,
        categories:Optional[List[str]]=None,
        limit:int=10,
    )->List[Dict]:
        return self._memory.get_agent_memories(
            agent_type,project_id,categories,limit
        )
