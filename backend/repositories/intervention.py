from typing import Optional,List,Dict,Any
from datetime import datetime
from uuid import uuid4
from sqlalchemy.orm import Session
from models.tables import Intervention
from .base import BaseRepository

class InterventionRepository(BaseRepository[Intervention]):
 def __init__(self,session:Session):
  super().__init__(session,Intervention)

 def to_dict(self,i:Intervention)->Dict[str,Any]:
  return {
   "id":i.id,
   "projectId":i.project_id,
   "targetType":i.target_type,
   "targetAgentId":i.target_agent_id,
   "priority":i.priority,
   "message":i.message,
   "attachedFileIds":i.attached_file_ids or [],
   "status":i.status,
   "createdAt":i.created_at.isoformat() if i.created_at else None,
   "deliveredAt":i.delivered_at.isoformat() if i.delivered_at else None,
   "acknowledgedAt":i.acknowledged_at.isoformat() if i.acknowledged_at else None,
   "processedAt":i.processed_at.isoformat() if i.processed_at else None,
  }

 def get_by_project(self,project_id:str)->List[Dict]:
  ints=self.session.query(Intervention).filter(Intervention.project_id==project_id).all()
  return [self.to_dict(i) for i in ints]

 def get_dict(self,id:str)->Optional[Dict]:
  i=self.get(id)
  return self.to_dict(i) if i else None

 def create_from_dict(self,data:Dict)->Dict:
  intervention=Intervention(
   id=f"int-{uuid4().hex[:8]}",
   project_id=data["projectId"],
   target_type=data.get("targetType","all"),
   target_agent_id=data.get("targetAgentId"),
   priority=data.get("priority","normal"),
   message=data["message"],
   attached_file_ids=data.get("attachedFileIds",[]),
   status="pending",
   created_at=datetime.now()
  )
  self.create(intervention)
  return self.to_dict(intervention)

 def acknowledge(self,id:str)->Optional[Dict]:
  i=self.get(id)
  if not i:
   return None
  i.status="acknowledged"
  i.acknowledged_at=datetime.now()
  self.update(i)
  return self.to_dict(i)

 def process(self,id:str)->Optional[Dict]:
  i=self.get(id)
  if not i:
   return None
  i.status="processed"
  i.processed_at=datetime.now()
  self.update(i)
  return self.to_dict(i)

 def deliver(self,id:str)->Optional[Dict]:
  i=self.get(id)
  if not i:
   return None
  i.status="delivered"
  i.delivered_at=datetime.now()
  self.update(i)
  return self.to_dict(i)
