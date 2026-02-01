from typing import Optional,List,Dict,Any
from datetime import datetime
from uuid import uuid4
from sqlalchemy.orm import Session
from models.tables import Asset
from .base import BaseRepository

class AssetRepository(BaseRepository[Asset]):
 def __init__(self,session:Session):
  super().__init__(session,Asset)

 def to_dict(self,a:Asset)->Dict[str,Any]:
  return {
   "id":a.id,
   "agentId":a.agent_id,
   "name":a.name,
   "type":a.type,
   "agent":a.agent,
   "size":a.size,
   "url":a.url,
   "thumbnail":a.thumbnail,
   "duration":a.duration,
   "approvalStatus":a.approval_status,
   "createdAt":a.created_at.isoformat() if a.created_at else None,
  }

 def get_by_project(self,project_id:str)->List[Dict]:
  assets=self.session.query(Asset).filter(Asset.project_id==project_id).all()
  return [self.to_dict(a) for a in assets]

 def get_pending_by_agent(self,agent_id:str)->List[Asset]:
  return self.session.query(Asset).filter(Asset.agent_id==agent_id,Asset.approval_status=="pending").all()

 def create_from_dict(self,project_id:str,data:Dict)->Dict:
  asset=Asset(
   id=data.get("id",f"asset-{uuid4().hex[:8]}"),
   project_id=project_id,
   agent_id=data.get("agentId"),
   name=data["name"],
   type=data["type"],
   agent=data.get("agent"),
   size=data.get("size"),
   url=data.get("url"),
   thumbnail=data.get("thumbnail"),
   duration=data.get("duration"),
   approval_status=data.get("approvalStatus","pending"),
   created_at=datetime.now()
  )
  self.create(asset)
  return self.to_dict(asset)

 def update_from_dict(self,project_id:str,asset_id:str,data:Dict)->Optional[Dict]:
  a=self.session.query(Asset).filter(Asset.id==asset_id,Asset.project_id==project_id).first()
  if not a:
   return None
  if"approvalStatus" in data:
   a.approval_status=data["approvalStatus"]
  if"name" in data:
   a.name=data["name"]
  self.update(a)
  return self.to_dict(a)

 def delete_by_project(self,project_id:str)->int:
  count=self.session.query(Asset).filter(Asset.project_id==project_id).delete()
  self.session.flush()
  return count
