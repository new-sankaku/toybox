import uuid
from datetime import datetime
from typing import Optional,List,Dict,Any
from sqlalchemy.orm import Session
from sqlalchemy import and_,update
from .base import BaseRepository
from models.tables import LlmJob


class LlmJobRepository(BaseRepository[LlmJob]):
 def __init__(self,session:Session):
  super().__init__(session,LlmJob)

 def create_job(
  self,
  project_id:str,
  agent_id:str,
  provider_id:str,
  model:str,
  prompt:str,
  max_tokens:int=16384,
  priority:int=0,
  system_prompt:Optional[str]=None,
 )->Dict[str,Any]:
  job=LlmJob(
   id=f"job-{uuid.uuid4().hex[:12]}",
   project_id=project_id,
   agent_id=agent_id,
   provider_id=provider_id,
   model=model,
   system_prompt=system_prompt,
   prompt=prompt,
   max_tokens=max_tokens,
   priority=priority,
   status="pending",
   created_at=datetime.now(),
  )
  self.session.add(job)
  self.session.flush()
  return self.to_dict(job)

 def get_pending_jobs(self,limit:int=10)->List[LlmJob]:
  return self.session.query(LlmJob).filter(
   LlmJob.status=="pending"
  ).order_by(LlmJob.priority.desc(),LlmJob.created_at.asc()).limit(limit).all()

 def get_running_count(self)->int:
  return self.session.query(LlmJob).filter(LlmJob.status=="running").count()

 def claim_job(self,job_id:str)->Optional[LlmJob]:
  stmt=update(LlmJob).where(
   and_(LlmJob.id==job_id,LlmJob.status=="pending")
  ).values(status="running",started_at=datetime.now())
  result=self.session.execute(stmt)
  self.session.flush()
  if result.rowcount==0:
   return None
  return self.get(job_id)

 def complete_job(
  self,
  job_id:str,
  response_content:str,
  tokens_input:int=0,
  tokens_output:int=0,
 )->Optional[Dict[str,Any]]:
  job=self.get(job_id)
  if not job:
   return None
  job.status="completed"
  job.response_content=response_content
  job.tokens_input=tokens_input
  job.tokens_output=tokens_output
  job.completed_at=datetime.now()
  self.session.flush()
  return self.to_dict(job)

 def fail_job(self,job_id:str,error_message:str)->Optional[Dict[str,Any]]:
  job=self.get(job_id)
  if not job:
   return None
  job.status="failed"
  job.error_message=error_message
  job.retry_count+=1
  job.completed_at=datetime.now()
  self.session.flush()
  return self.to_dict(job)

 def retry_job(self,job_id:str)->Optional[Dict[str,Any]]:
  job=self.get(job_id)
  if not job or job.status not in ("failed","running"):
   return None
  job.status="pending"
  job.started_at=None
  job.completed_at=None
  job.error_message=None
  self.session.flush()
  return self.to_dict(job)

 def set_external_job_id(self,job_id:str,external_id:str)->Optional[Dict[str,Any]]:
  job=self.get(job_id)
  if not job:
   return None
  job.external_job_id=external_id
  self.session.flush()
  return self.to_dict(job)

 def get_by_external_id(self,external_id:str)->Optional[LlmJob]:
  return self.session.query(LlmJob).filter(LlmJob.external_job_id==external_id).first()

 def get_by_agent(self,agent_id:str)->List[Dict[str,Any]]:
  jobs=self.session.query(LlmJob).filter(LlmJob.agent_id==agent_id).order_by(LlmJob.created_at.desc()).all()
  return [self.to_dict(j) for j in jobs]

 def cleanup_project_jobs(self,project_id:str)->int:
  incomplete_jobs=self.session.query(LlmJob).filter(
   and_(LlmJob.project_id==project_id,LlmJob.status.in_(["pending","running"]))
  ).all()
  count=len(incomplete_jobs)
  for job in incomplete_jobs:
   self.session.delete(job)
  self.session.flush()
  return count

 def to_dict(self,job:LlmJob)->Dict[str,Any]:
  return {
   "id":job.id,
   "projectId":job.project_id,
   "agentId":job.agent_id,
   "providerId":job.provider_id,
   "model":job.model,
   "status":job.status,
   "priority":job.priority,
   "systemPrompt":job.system_prompt,
   "prompt":job.prompt,
   "maxTokens":job.max_tokens,
   "responseContent":job.response_content,
   "tokensInput":job.tokens_input,
   "tokensOutput":job.tokens_output,
   "errorMessage":job.error_message,
   "retryCount":job.retry_count,
   "externalJobId":job.external_job_id,
   "createdAt":job.created_at.isoformat() if job.created_at else None,
   "startedAt":job.started_at.isoformat() if job.started_at else None,
   "completedAt":job.completed_at.isoformat() if job.completed_at else None,
  }
