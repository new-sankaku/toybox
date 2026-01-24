from datetime import datetime
from typing import Optional,Dict,List
from .base import BaseService
from models.database import session_scope
from repositories import CheckpointRepository,AgentRepository,ProjectRepository,SystemLogRepository


class CheckpointService(BaseService):

 def get_by_project(self,project_id:str)->List[Dict]:
  with session_scope() as session:
   repo = CheckpointRepository(session)
   return repo.get_by_project(project_id)

 def get(self,checkpoint_id:str)->Optional[Dict]:
  with session_scope() as session:
   repo = CheckpointRepository(session)
   return repo.get_dict(checkpoint_id)

 def create(self,project_id:str,agent_id:str,data:Dict)->Dict:
  with session_scope() as session:
   repo = CheckpointRepository(session)
   return repo.create_from_dict({**data,"projectId":project_id,"agentId":agent_id})

 def resolve(self,checkpoint_id:str,resolution:str,feedback:Optional[str]=None)->Optional[Dict]:
  with session_scope() as session:
   cp_repo = CheckpointRepository(session)
   agent_repo = AgentRepository(session)
   syslog_repo = SystemLogRepository(session)
   cp = cp_repo.get(checkpoint_id)
   if not cp:
    return None
   result = cp_repo.resolve(checkpoint_id,resolution,feedback)
   project_id = cp.project_id
   status_text = {"approved":"承認","rejected":"却下","revision_requested":"修正要求"}
   syslog_repo.add_log(project_id,"info","System",f"チェックポイント{status_text.get(resolution,resolution)}: {cp.title}")
   agent = agent_repo.get(cp.agent_id)
   if agent:
    other_pending = cp_repo.get_pending_by_agent(cp.agent_id)
    other_pending = [c for c in other_pending if c.id != checkpoint_id]
    if not other_pending and agent.status == "waiting_approval":
     agent.status = "running"
     session.flush()
   if resolution == "approved":
    self._check_phase_advancement(session,project_id)
   return result

 def _check_phase_advancement(self,session,project_id:str):
  proj_repo = ProjectRepository(session)
  cp_repo = CheckpointRepository(session)
  syslog_repo = SystemLogRepository(session)
  project = proj_repo.get(project_id)
  if not project:
   return
  current_phase = project.current_phase
  project_checkpoints = cp_repo.get_by_project(project_id)
  phase1_types = {"concept_review","task_review_1","concept_detail_review","scenario_review","world_review","game_design_review","tech_spec_review"}
  if current_phase == 1:
   phase1_checkpoints = [c for c in project_checkpoints if c["type"] in phase1_types]
   if phase1_checkpoints and all(c["status"] == "approved" for c in phase1_checkpoints):
    project.current_phase = 2
    project.updated_at = datetime.now()
    session.flush()
    syslog_repo.add_log(project_id,"info","System","Phase 2: 実装 に移行しました")
    print(f"[CheckpointService] Project {project_id} advanced to Phase 2")
