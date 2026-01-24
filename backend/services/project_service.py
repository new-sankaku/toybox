from datetime import datetime
from typing import Optional,Dict,List
from .base import BaseService
from models.database import session_scope
from repositories import ProjectRepository,SystemLogRepository
from ai_config import build_default_ai_services


class ProjectService(BaseService):

 def get_all(self)->List[Dict]:
  with session_scope() as session:
   repo = ProjectRepository(session)
   return repo.get_all_dict()

 def get(self,project_id:str)->Optional[Dict]:
  with session_scope() as session:
   repo = ProjectRepository(session)
   return repo.get_dict(project_id)

 def create(self,data:Dict)->Dict:
  with session_scope() as session:
   repo = ProjectRepository(session)
   if "aiServices" not in data or not data["aiServices"]:
    data["aiServices"] = dict(build_default_ai_services())
   project = repo.create_from_dict(data)
   syslog_repo = SystemLogRepository(session)
   syslog_repo.add_log(project["id"],"info","System","プロジェクト作成")
   return project

 def update(self,project_id:str,data:Dict)->Optional[Dict]:
  with session_scope() as session:
   repo = ProjectRepository(session)
   return repo.update_from_dict(project_id,data)

 def delete(self,project_id:str)->bool:
  with session_scope() as session:
   repo = ProjectRepository(session)
   return repo.delete(project_id)

 def start(self,project_id:str)->Optional[Dict]:
  with session_scope() as session:
   repo = ProjectRepository(session)
   syslog_repo = SystemLogRepository(session)
   p = repo.get(project_id)
   if not p:
    return None
   if p.status in ("draft","paused"):
    p.status = "running"
    p.updated_at = datetime.now()
    session.flush()
    syslog_repo.add_log(project_id,"info","System","プロジェクト開始")
   return repo.to_dict(p)

 def pause(self,project_id:str)->Optional[Dict]:
  with session_scope() as session:
   repo = ProjectRepository(session)
   syslog_repo = SystemLogRepository(session)
   p = repo.get(project_id)
   if not p:
    return None
   if p.status == "running":
    p.status = "paused"
    p.updated_at = datetime.now()
    session.flush()
    syslog_repo.add_log(project_id,"info","System","プロジェクト一時停止")
   return repo.to_dict(p)

 def resume(self,project_id:str)->Optional[Dict]:
  with session_scope() as session:
   repo = ProjectRepository(session)
   syslog_repo = SystemLogRepository(session)
   p = repo.get(project_id)
   if not p:
    return None
   if p.status == "paused":
    p.status = "running"
    p.updated_at = datetime.now()
    session.flush()
    syslog_repo.add_log(project_id,"info","System","プロジェクト再開")
   return repo.to_dict(p)

 def get_ai_services(self,project_id:str)->Dict[str,Dict]:
  with session_scope() as session:
   repo = ProjectRepository(session)
   project = repo.get(project_id)
   if not project:
    return {}
   return project.ai_services or dict(build_default_ai_services())

 def update_ai_service(self,project_id:str,service_type:str,config:Dict)->Optional[Dict]:
  with session_scope() as session:
   repo = ProjectRepository(session)
   project = repo.get(project_id)
   if not project:
    return None
   ai_services = project.ai_services or dict(build_default_ai_services())
   if service_type not in ai_services:
    return None
   ai_services[service_type].update(config)
   project.ai_services = ai_services
   project.updated_at = datetime.now()
   session.flush()
   return ai_services[service_type]

 def update_ai_services(self,project_id:str,ai_services:Dict[str,Dict])->Optional[Dict]:
  with session_scope() as session:
   repo = ProjectRepository(session)
   project = repo.get(project_id)
   if not project:
    return None
   project.ai_services = ai_services
   project.updated_at = datetime.now()
   session.flush()
   return project.ai_services
