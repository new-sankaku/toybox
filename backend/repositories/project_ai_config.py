"""プロジェクトAI設定リポジトリ"""
from typing import Optional,List
from datetime import datetime
from sqlalchemy.orm import Session
from models.tables import ProjectAiConfig


class ProjectAiConfigRepository:
 def __init__(self,session:Session):
  self.session = session

 def get(self,project_id:str,usage_category:str)->Optional[ProjectAiConfig]:
  return self.session.query(ProjectAiConfig).filter(
   ProjectAiConfig.project_id == project_id,
   ProjectAiConfig.usage_category == usage_category
  ).first()

 def get_by_project(self,project_id:str)->List[ProjectAiConfig]:
  return self.session.query(ProjectAiConfig).filter(
   ProjectAiConfig.project_id == project_id
  ).all()

 def save(
  self,
  project_id:str,
  usage_category:str,
  provider_id:str,
  model_id:str,
  custom_params:dict = None
 )->ProjectAiConfig:
  existing = self.get(project_id,usage_category)
  if existing:
   existing.provider_id = provider_id
   existing.model_id = model_id
   existing.custom_params = custom_params
   existing.updated_at = datetime.now()
   self.session.flush()
   return existing
  else:
   new_config = ProjectAiConfig(
    project_id=project_id,
    usage_category=usage_category,
    provider_id=provider_id,
    model_id=model_id,
    custom_params=custom_params,
   )
   self.session.add(new_config)
   self.session.flush()
   return new_config

 def delete(self,project_id:str,usage_category:str)->bool:
  existing = self.get(project_id,usage_category)
  if existing:
   self.session.delete(existing)
   self.session.flush()
   return True
  return False

 def delete_all_for_project(self,project_id:str)->int:
  deleted = self.session.query(ProjectAiConfig).filter(
   ProjectAiConfig.project_id == project_id
  ).delete()
  self.session.flush()
  return deleted
