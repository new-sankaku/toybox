from typing import Optional,List,Dict,Any
from datetime import datetime
from sqlalchemy.orm import Session
from models.tables import Project
from .base import BaseRepository

def generate_output_dir()->str:
 return f"output/{datetime.now().strftime('%Y%m%d%H%M%S')}"

class ProjectRepository(BaseRepository[Project]):
 def __init__(self,session:Session):
  super().__init__(session,Project)

 def to_dict(self,p:Project)->Dict[str,Any]:
  config=p.config or {}
  result={
   "id":p.id,
   "name":p.name,
   "description":p.description or"",
   "concept":p.concept or {},
   "status":p.status,
   "currentPhase":p.current_phase,
   "state":p.state or {},
   "config":config,
   "aiServices":p.ai_services or {},
   "createdAt":p.created_at.isoformat() if p.created_at else None,
   "updatedAt":p.updated_at.isoformat() if p.updated_at else None,
  }
  if"outputSettings" in config:
   result["outputSettings"]=config["outputSettings"]
  if"advancedSettings" in config:
   result["advancedSettings"]=config["advancedSettings"]
  return result

 def get_all_dict(self)->List[Dict]:
  return [self.to_dict(p) for p in self.get_all()]

 def get_dict(self,id:str)->Optional[Dict]:
  p=self.get(id)
  return self.to_dict(p) if p else None

 def create_from_dict(self,data:Dict)->Dict:
  from uuid import uuid4
  now=datetime.now()
  config=data.get("config",{})
  if"outputSettings" not in config:
   config["outputSettings"]={"default_dir":generate_output_dir()}
  project=Project(
   id=f"proj-{uuid4().hex[:8]}",
   name=data.get("name","新規プロジェクト"),
   description=data.get("description",""),
   concept=data.get("concept",{}),
   status="draft",
   current_phase=1,
   state={},
   config=config,
   ai_services=data.get("aiServices",{}),
   created_at=now,
   updated_at=now
  )
  self.create(project)
  return self.to_dict(project)

 def update_from_dict(self,id:str,data:Dict)->Optional[Dict]:
  p=self.get(id)
  if not p:
   return None
  if"name" in data:
   p.name=data["name"]
  if"description" in data:
   p.description=data["description"]
  if"concept" in data:
   p.concept=data["concept"]
  if"status" in data:
   p.status=data["status"]
  if"currentPhase" in data:
   p.current_phase=data["currentPhase"]
  if"state" in data:
   p.state=data["state"]
  if"config" in data:
   p.config=data["config"]
  if"aiServices" in data:
   p.ai_services=data["aiServices"]
  if"outputSettings" in data:
   config=p.config or {}
   config["outputSettings"]=data["outputSettings"]
   p.config=config
  if"advancedSettings" in data:
   config=p.config or {}
   config["advancedSettings"]=data["advancedSettings"]
   p.config=config
  p.updated_at=datetime.now()
  self.update(p)
  return self.to_dict(p)
