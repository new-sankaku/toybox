from datetime import datetime
from typing import Dict,List
from .base import BaseService
from models.database import session_scope
from repositories import ProjectRepository,QualitySettingsRepository
from agent_settings import get_default_quality_settings,QualityCheckConfig
from config_loader import get_auto_approval_rules as get_config_auto_approval_rules


class SettingsService(BaseService):

 def get_quality_settings(self,project_id:str)->Dict[str,QualityCheckConfig]:
  with session_scope() as session:
   repo = QualitySettingsRepository(session)
   return repo.get_all(project_id)

 def set_quality_setting(self,project_id:str,agent_type:str,config:QualityCheckConfig)->None:
  with session_scope() as session:
   repo = QualitySettingsRepository(session)
   repo.set(project_id,agent_type,config)

 def reset_quality_settings(self,project_id:str)->None:
  with session_scope() as session:
   repo = QualitySettingsRepository(session)
   repo.reset(project_id)

 def get_quality_setting_for_agent(self,project_id:str,agent_type:str)->QualityCheckConfig:
  settings = self.get_quality_settings(project_id)
  return settings.get(agent_type,QualityCheckConfig())

 def get_auto_approval_rules(self,project_id:str)->List[Dict]:
  with session_scope() as session:
   repo = ProjectRepository(session)
   project = repo.get(project_id)
   if not project:
    return []
   return (project.config or {}).get("autoApprovalRules",get_config_auto_approval_rules())

 def set_auto_approval_rules(self,project_id:str,rules:List[Dict])->List[Dict]:
  with session_scope() as session:
   repo = ProjectRepository(session)
   project = repo.get(project_id)
   if not project:
    return []
   config = project.config or {}
   config["autoApprovalRules"] = rules
   project.config = config
   project.updated_at = datetime.now()
   session.flush()
   return rules
