from datetime import datetime
from typing import Optional,List,Dict,Any
from sqlalchemy.orm import Session
from sqlalchemy import and_,or_,func
from .base import BaseRepository
from models.tables import AgentMemory


class AgentMemoryRepository(BaseRepository[AgentMemory]):
 def __init__(self,session:Session):
  super().__init__(session,AgentMemory)

 def create_memory(
  self,
  category:str,
  agent_type:str,
  content:str,
  project_id:Optional[str]=None,
  source_project_id:Optional[str]=None,
  relevance_score:int=100,
 )->Dict[str,Any]:
  memory=AgentMemory(
   project_id=project_id,
   category=category,
   agent_type=agent_type,
   content=content,
   source_project_id=source_project_id,
   relevance_score=relevance_score,
   access_count=0,
   created_at=datetime.now(),
  )
  self.session.add(memory)
  self.session.flush()
  return self.to_dict(memory)

 def get_memories_for_agent(
  self,
  agent_type:str,
  project_id:Optional[str]=None,
  categories:Optional[List[str]]=None,
  limit:int=10,
 )->List[Dict[str,Any]]:
  query=self.session.query(AgentMemory).filter(
   AgentMemory.agent_type==agent_type,
  )
  if project_id:
   query=query.filter(
    or_(AgentMemory.project_id==project_id,AgentMemory.project_id.is_(None))
   )
  else:
   query=query.filter(AgentMemory.project_id.is_(None))
  if categories:
   query=query.filter(AgentMemory.category.in_(categories))
  memories=query.order_by(
   AgentMemory.relevance_score.desc(),
   AgentMemory.created_at.desc()
  ).limit(limit).all()
  for m in memories:
   m.access_count+=1
  self.session.flush()
  return [self.to_dict(m) for m in memories]

 def find_duplicate(self,agent_type:str,content:str,category:str)->Optional[AgentMemory]:
  return self.session.query(AgentMemory).filter(
   and_(
    AgentMemory.agent_type==agent_type,
    AgentMemory.content==content,
    AgentMemory.category==category,
   )
  ).first()

 def delete_by_project(self,project_id:str)->int:
  memories=self.session.query(AgentMemory).filter(
   AgentMemory.project_id==project_id
  ).all()
  count=len(memories)
  for m in memories:
   self.session.delete(m)
  self.session.flush()
  return count

 def get_all_global(self,limit:int=50)->List[Dict[str,Any]]:
  memories=self.session.query(AgentMemory).filter(
   AgentMemory.project_id.is_(None)
  ).order_by(AgentMemory.relevance_score.desc()).limit(limit).all()
  return [self.to_dict(m) for m in memories]

 def to_dict(self,memory:AgentMemory)->Dict[str,Any]:
  return {
   "id":memory.id,
   "projectId":memory.project_id,
   "category":memory.category,
   "agentType":memory.agent_type,
   "content":memory.content,
   "sourceProjectId":memory.source_project_id,
   "relevanceScore":memory.relevance_score,
   "accessCount":memory.access_count,
   "createdAt":memory.created_at.isoformat() if memory.created_at else None,
  }
