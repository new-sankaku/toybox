import asyncio
import threading
import time
from typing import Optional,Dict,Any,Callable
from models.database import session_scope
from repositories.llm_job import LlmJobRepository
from providers.registry import get_provider
from providers.base import AIProviderConfig,ChatMessage,MessageRole
from config_loader import get_provider_max_concurrent,get_provider_group,get_group_max_concurrent,get_token_budget_settings
from agents.exceptions import TokenBudgetExceededError
from middleware.logger import get_logger

MAX_JOB_RETRIES=3


class LlmJobQueue:
 _instance:Optional["LlmJobQueue"]=None
 _lock=threading.Lock()

 def __new__(cls):
  if cls._instance is None:
   with cls._lock:
    if cls._instance is None:
     cls._instance=super().__new__(cls)
     cls._instance._initialized=False
  return cls._instance

 def __init__(self):
  if self._initialized:
   return
  self._poll_interval=1.0
  self._running=False
  self._thread:Optional[threading.Thread]=None
  self._active_jobs_by_provider:Dict[str,Dict[str,bool]]={}
  self._active_jobs_by_group:Dict[str,Dict[str,bool]]={}
  self._active_jobs_lock=threading.Lock()
  self._job_callbacks:Dict[str,Callable[[Dict],None]]={}
  self._initialized=True

 def start(self)->None:
  if self._running:
   return
  self._running=True
  self._thread=threading.Thread(target=self._worker_loop,daemon=True)
  self._thread.start()
  get_logger().info("LlmJobQueue started")

 def stop(self)->None:
  self._running=False
  if self._thread:
   self._thread.join(timeout=5)
   self._thread=None
  get_logger().info("LlmJobQueue stopped")

 def cleanup_project_jobs(self,project_id:str)->int:
  with session_scope() as session:
   repo=LlmJobRepository(session)
   return repo.cleanup_project_jobs(project_id)

 def submit_job(
  self,
  project_id:str,
  agent_id:str,
  provider_id:str,
  model:str,
  prompt:str,
  max_tokens:int=32768,
  priority:int=0,
  callback:Optional[Callable[[Dict],None]]=None,
  system_prompt:Optional[str]=None,
 )->Dict[str,Any]:
  with session_scope() as session:
   repo=LlmJobRepository(session)
   budget=get_token_budget_settings()
   limit=budget.get("default_limit",500000)
   warning_pct=budget.get("warning_threshold_percent",80)
   enforcement=budget.get("enforcement","hard")
   used=repo.get_project_token_usage(project_id)
   warning_at=int(limit*warning_pct/100)
   if used>=warning_at:
    get_logger().warning(f"token budget warning: project={project_id} used={used}/{limit} ({int(used/limit*100)}%)")
   if enforcement=="hard" and used>=limit:
    raise TokenBudgetExceededError(project_id,used,limit)
   job=repo.create_job(
    project_id=project_id,
    agent_id=agent_id,
    provider_id=provider_id,
    model=model,
    prompt=prompt,
    max_tokens=max_tokens,
    priority=priority,
    system_prompt=system_prompt,
   )
   if callback:
    self._job_callbacks[job["id"]]=callback
   return job

 def get_job_status(self,job_id:str)->Optional[Dict[str,Any]]:
  with session_scope() as session:
   repo=LlmJobRepository(session)
   job=repo.get(job_id)
   return repo.to_dict(job) if job else None

 def wait_for_job(self,job_id:str,timeout:float=300.0)->Optional[Dict[str,Any]]:
  start=time.time()
  while time.time()-start<timeout:
   job=self.get_job_status(job_id)
   if job and job["status"] in ("completed","failed"):
    return job
   time.sleep(0.5)
  return None

 async def wait_for_job_async(self,job_id:str,timeout:float=300.0)->Optional[Dict[str,Any]]:
  start=time.time()
  while time.time()-start<timeout:
   job=self.get_job_status(job_id)
   if job and job["status"] in ("completed","failed"):
    return job
   await asyncio.sleep(0.5)
  return None

 def _worker_loop(self)->None:
  while self._running:
   try:
    self._process_pending_jobs()
   except Exception as e:
    get_logger().error(f"LlmJobQueue worker error: {e}",exc_info=True)
   time.sleep(self._poll_interval)

 def _get_provider_active_count(self,provider_id:str)->int:
  with self._active_jobs_lock:
   provider_jobs=self._active_jobs_by_provider.get(provider_id,{})
   return len([j for j in provider_jobs.values() if j])

 def _get_group_active_count(self,group_id:str)->int:
  with self._active_jobs_lock:
   group_jobs=self._active_jobs_by_group.get(group_id,{})
   return len([j for j in group_jobs.values() if j])

 def _can_start_job(self,provider_id:str,job_id:str)->bool:
  with self._active_jobs_lock:
   if job_id in self._active_jobs_by_provider.get(provider_id,{}):
    return False
   group_id=get_provider_group(provider_id)
   if group_id:
    group_max=get_group_max_concurrent(group_id)
    group_jobs=self._active_jobs_by_group.get(group_id,{})
    if len([j for j in group_jobs.values() if j])>=group_max:
     return False
   else:
    provider_max=get_provider_max_concurrent(provider_id)
    provider_jobs=self._active_jobs_by_provider.get(provider_id,{})
    if len([j for j in provider_jobs.values() if j])>=provider_max:
     return False
  return True

 def _register_active_job(self,job_id:str,provider_id:str)->None:
  with self._active_jobs_lock:
   if provider_id not in self._active_jobs_by_provider:
    self._active_jobs_by_provider[provider_id]={}
   self._active_jobs_by_provider[provider_id][job_id]=True
   group_id=get_provider_group(provider_id)
   if group_id:
    if group_id not in self._active_jobs_by_group:
     self._active_jobs_by_group[group_id]={}
    self._active_jobs_by_group[group_id][job_id]=True

 def _unregister_active_job(self,job_id:str,provider_id:str)->None:
  with self._active_jobs_lock:
   if provider_id in self._active_jobs_by_provider:
    self._active_jobs_by_provider[provider_id].pop(job_id,None)
   group_id=get_provider_group(provider_id)
   if group_id and group_id in self._active_jobs_by_group:
    self._active_jobs_by_group[group_id].pop(job_id,None)

 def _process_pending_jobs(self)->None:
  with session_scope() as session:
   repo=LlmJobRepository(session)
   pending_jobs=repo.get_pending_jobs(limit=20)
   for job in pending_jobs:
    provider_id=job.provider_id
    if not self._can_start_job(provider_id,job.id):
     continue
    claimed=repo.claim_job(job.id)
    if claimed:
     self._register_active_job(job.id,provider_id)
     thread=threading.Thread(target=self._execute_job,args=(job.id,provider_id),daemon=True)
     thread.start()

 def _execute_job(self,job_id:str,provider_id:str)->None:
  try:
   with session_scope() as session:
    repo=LlmJobRepository(session)
    job=repo.get(job_id)
    if not job:
     return
    provider=get_provider(job.provider_id,AIProviderConfig(timeout=120))
    if not provider:
     repo.fail_job(job_id,f"Provider not found: {job.provider_id}")
     self._notify_completion(job_id)
     return
    messages=[]
    if job.system_prompt:
     messages.append(ChatMessage(role=MessageRole.SYSTEM,content=job.system_prompt))
    messages.append(ChatMessage(role=MessageRole.USER,content=job.prompt))
    response=provider.chat(messages=messages,model=job.model,max_tokens=job.max_tokens)
    repo.complete_job(
     job_id=job_id,
     response_content=response.content,
     tokens_input=response.input_tokens,
     tokens_output=response.output_tokens,
    )
    self._notify_completion(job_id)
  except Exception as e:
   with session_scope() as session:
    repo=LlmJobRepository(session)
    job=repo.get(job_id)
    if job and job.retry_count<MAX_JOB_RETRIES:
     repo.retry_job(job_id)
     get_logger().warning(f"LlmJobQueue job {job_id} retry ({job.retry_count+1}/{MAX_JOB_RETRIES}): {e}")
    else:
     repo.fail_job(job_id,str(e))
     self._notify_completion(job_id)
  finally:
   self._unregister_active_job(job_id,provider_id)

 def _notify_completion(self,job_id:str)->None:
  job=self.get_job_status(job_id)
  if not job:
   return
  callback=self._job_callbacks.pop(job_id,None)
  if callback:
   try:
    callback(job)
   except Exception as e:
    get_logger().error(f"LlmJobQueue callback error for job {job_id}: {e}",exc_info=True)


def get_llm_job_queue()->LlmJobQueue:
 return LlmJobQueue()
