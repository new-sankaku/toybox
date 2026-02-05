from typing import Optional,Dict,List

from models.database import session_scope
from repositories.agent_memory import AgentMemoryRepository
from events.event_bus import EventBus
from services.base_service import BaseService


class AgentMemoryManager(BaseService):
    def __init__(self,event_bus:EventBus):
        super().__init__(event_bus)

    def create_agent_memory(
        self,
        category:str,
        agent_type:str,
        content:str,
        project_id:Optional[str]=None,
        source_project_id:Optional[str]=None,
        relevance_score:int=100,
    )->Dict:
        with session_scope() as session:
            repo=AgentMemoryRepository(session)
            existing=repo.find_duplicate(agent_type,content,category)
            if existing:
                existing.relevance_score=min(
                    existing.relevance_score+10,200
                )
                session.flush()
                return repo.to_dict(existing)
            return repo.create_memory(
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
        with session_scope() as session:
            repo=AgentMemoryRepository(session)
            return repo.get_memories_for_agent(
                agent_type,project_id,categories,limit
            )
