from typing import Optional,List,Dict,Any
from datetime import datetime
from sqlalchemy.orm import Session
from models.tables import Agent
from .base import BaseRepository

class AgentRepository(BaseRepository[Agent]):
 def __init__(self,session:Session):
  super().__init__(session,Agent)

 def to_dict(self,a:Agent)->Dict[str,Any]:
  return {
   "id":a.id,
   "projectId":a.project_id,
   "type":a.type,
   "phase":a.phase,
   "status":a.status,
   "progress":a.progress,
   "currentTask":a.current_task,
   "tokensUsed":a.tokens_used,
   "inputTokens":a.input_tokens,
   "outputTokens":a.output_tokens,
   "startedAt":a.started_at.isoformat() if a.started_at else None,
   "completedAt":a.completed_at.isoformat() if a.completed_at else None,
   "error":a.error,
   "parentAgentId":a.parent_agent_id,
   "metadata":a.metadata_ or {},
   "createdAt":a.created_at.isoformat() if a.created_at else None,
  }

 def get_by_project(self,project_id:str)->List[Dict]:
  agents=self.session.query(Agent).filter(Agent.project_id==project_id).all()
  return [self.to_dict(a) for a in agents]

 def get_dict(self,id:str)->Optional[Dict]:
  a=self.get(id)
  return self.to_dict(a) if a else None

 def create_from_dict(self,project_id:str,data:Dict)->Dict:
  now=datetime.now()
  agent=Agent(
   id=data.get("id",f"agent-{project_id}-{data['type']}"),
   project_id=project_id,
   type=data["type"],
   phase=data.get("phase",0),
   status=data.get("status","pending"),
   progress=0,
   current_task=None,
   tokens_used=0,
   input_tokens=0,
   output_tokens=0,
   started_at=None,
   completed_at=None,
   error=None,
   parent_agent_id=None,
   metadata_=data.get("metadata",{}),
   created_at=now
  )
  self.create(agent)
  return self.to_dict(agent)

 def update_from_dict(self,id:str,data:Dict)->Optional[Dict]:
  a=self.get(id)
  if not a:
   return None
  if "status" in data:
   a.status=data["status"]
  if "progress" in data:
   a.progress=data["progress"]
  if "currentTask" in data:
   a.current_task=data["currentTask"]
  if "tokensUsed" in data:
   a.tokens_used=data["tokensUsed"]
  if "inputTokens" in data:
   a.input_tokens=data["inputTokens"]
  if "outputTokens" in data:
   a.output_tokens=data["outputTokens"]
  if "startedAt" in data:
   a.started_at=datetime.fromisoformat(data["startedAt"]) if data["startedAt"] else None
  if "completedAt" in data:
   a.completed_at=datetime.fromisoformat(data["completedAt"]) if data["completedAt"] else None
  if "error" in data:
   a.error=data["error"]
  if "metadata" in data:
   a.metadata_=data["metadata"]
  self.update(a)
  return self.to_dict(a)

 def delete_by_project(self,project_id:str)->int:
  count=self.session.query(Agent).filter(Agent.project_id==project_id).delete()
  self.session.flush()
  return count
