import asyncio
import threading
import time
from typing import Optional,Dict,Any,Callable
from models.database import session_scope
from repositories.llm_job import LlmJobRepository
from providers.registry import get_provider
from providers.base import AIProviderConfig,ChatMessage,MessageRole
from config_loader import get_provider_max_concurrent,get_provider_group,get_group_max_concurrent


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
  self._job_callbacks:Dict[str,Callable[[Dict],None]]={}
  self._initialized=True

 def start(self)->None:
  if self._running:
   return
  self._running=True
  self._thread=threading.Thread(target=self._worker_loop,daemon=True)
  self._thread.start()
  print("[LlmJobQueue] Started")

 def stop(self)->None:
  self._running=False
  if self._thread:
   self._thread.join(timeout=5)
   self._thread=None
  print("[LlmJobQueue] Stopped")

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
  max_tokens:int=4096,
  priority:int=0,
  callback:Optional[Callable[[Dict],None]]=None,
 )->Dict[str,Any]:
  with session_scope() as session:
   repo=LlmJobRepository(session)
   job=repo.create_job(
    project_id=project_id,
    agent_id=agent_id,
    provider_id=provider_id,
    model=model,
    prompt=prompt,
    max_tokens=max_tokens,
    priority=priority,
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
    print(f"[LlmJobQueue] Worker error: {e}")
   time.sleep(self._poll_interval)

 def _get_provider_active_count(self,provider_id:str)->int:
  provider_jobs=self._active_jobs_by_provider.get(provider_id,{})
  return len([j for j in provider_jobs.values() if j])

 def _get_group_active_count(self,group_id:str)->int:
  group_jobs=self._active_jobs_by_group.get(group_id,{})
  return len([j for j in group_jobs.values() if j])

 def _can_start_job(self,provider_id:str,job_id:str)->bool:
  if job_id in self._active_jobs_by_provider.get(provider_id,{}):
   return False
  group_id=get_provider_group(provider_id)
  if group_id:
   group_max=get_group_max_concurrent(group_id)
   if self._get_group_active_count(group_id)>=group_max:
    return False
  else:
   provider_max=get_provider_max_concurrent(provider_id)
   if self._get_provider_active_count(provider_id)>=provider_max:
    return False
  return True

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
     if provider_id not in self._active_jobs_by_provider:
      self._active_jobs_by_provider[provider_id]={}
     self._active_jobs_by_provider[provider_id][job.id]=True
     group_id=get_provider_group(provider_id)
     if group_id:
      if group_id not in self._active_jobs_by_group:
       self._active_jobs_by_group[group_id]={}
      self._active_jobs_by_group[group_id][job.id]=True
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
    messages=[ChatMessage(role=MessageRole.USER,content=job.prompt)]
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
    repo.fail_job(job_id,str(e))
   self._notify_completion(job_id)
  finally:
   if provider_id in self._active_jobs_by_provider:
    self._active_jobs_by_provider[provider_id].pop(job_id,None)
   group_id=get_provider_group(provider_id)
   if group_id and group_id in self._active_jobs_by_group:
    self._active_jobs_by_group[group_id].pop(job_id,None)

 def _notify_completion(self,job_id:str)->None:
  job=self.get_job_status(job_id)
  if not job:
   return
  callback=self._job_callbacks.pop(job_id,None)
  if callback:
   try:
    callback(job)
   except Exception as e:
    print(f"[LlmJobQueue] Callback error: {e}")


def get_llm_job_queue()->LlmJobQueue:
 return LlmJobQueue()
