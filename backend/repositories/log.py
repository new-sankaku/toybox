from typing import List,Dict,Any
from datetime import datetime
from uuid import uuid4
from sqlalchemy.orm import Session
from models.tables import AgentLog,SystemLog
from .base import BaseRepository

class AgentLogRepository(BaseRepository[AgentLog]):
 def __init__(self,session:Session):
  super().__init__(session,AgentLog)

 def to_dict(self,l:AgentLog)->Dict[str,Any]:
  return {
   "id":l.id,
   "timestamp":l.created_at.isoformat() if l.created_at else None,
   "level":l.level,
   "message":l.message,
   "progress":l.progress,
   "metadata":l.metadata_ or {},
  }

 def get_by_agent(self,agent_id:str)->List[Dict]:
  logs=self.session.query(AgentLog).filter(AgentLog.agent_id==agent_id).order_by(AgentLog.created_at).all()
  return [self.to_dict(l) for l in logs]

 def add_log(self,agent_id:str,level:str,message:str,progress:int=None)->Dict:
  log=AgentLog(
   id=f"log-{uuid4().hex[:8]}",
   agent_id=agent_id,
   level=level,
   message=message,
   progress=progress,
   metadata_={},
   created_at=datetime.now()
  )
  self.create(log)
  return self.to_dict(log)

 def delete_by_agent(self,agent_id:str)->int:
  count=self.session.query(AgentLog).filter(AgentLog.agent_id==agent_id).delete()
  self.session.flush()
  return count

class SystemLogRepository(BaseRepository[SystemLog]):
 def __init__(self,session:Session):
  super().__init__(session,SystemLog)

 def to_dict(self,l:SystemLog)->Dict[str,Any]:
  return {
   "id":l.id,
   "timestamp":l.created_at.isoformat() if l.created_at else None,
   "level":l.level,
   "source":l.source,
   "message":l.message,
   "details":l.details,
  }

 def get_by_project(self,project_id:str)->List[Dict]:
  logs=self.session.query(SystemLog).filter(SystemLog.project_id==project_id).order_by(SystemLog.created_at).all()
  return [self.to_dict(l) for l in logs]

 def add_log(self,project_id:str,level:str,source:str,message:str,details:str=None)->Dict:
  log=SystemLog(
   id=f"syslog-{uuid4().hex[:8]}",
   project_id=project_id,
   level=level,
   source=source,
   message=message,
   details=details,
   created_at=datetime.now()
  )
  self.create(log)
  return self.to_dict(log)

 def delete_by_project(self,project_id:str)->int:
  count=self.session.query(SystemLog).filter(SystemLog.project_id==project_id).delete()
  self.session.flush()
  return count
