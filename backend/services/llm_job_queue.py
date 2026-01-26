import asyncio
import threading
import time
from datetime import datetime
from typing import Optional,Dict,Any,Callable
from models.database import session_scope
from repositories.llm_job import LlmJobRepository
from providers.registry import get_provider
from providers.base import AIProviderConfig,ChatMessage,MessageRole
from config_loader import get_llm_queue_config


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
  config=get_llm_queue_config()
  self._max_concurrent=config.get("max_concurrent",3)
  self._poll_interval=config.get("poll_interval",1.0)
  self._stale_timeout_minutes=config.get("stale_timeout_minutes",30)
  self._running=False
  self._thread:Optional[threading.Thread]=None
  self._active_jobs:Dict[str,bool]={}
  self._job_callbacks:Dict[str,Callable[[Dict],None]]={}
  self._sio=None
  self._initialized=True

 def set_socketio(self,sio)->None:
  self._sio=sio

 def set_max_concurrent(self,limit:int)->None:
  self._max_concurrent=max(1,limit)

 def start(self)->None:
  if self._running:
   return
  self._running=True
  self._thread=threading.Thread(target=self._worker_loop,daemon=True)
  self._thread.start()
  print(f"[LlmJobQueue] Started with max_concurrent={self._max_concurrent}")

 def stop(self)->None:
  self._running=False
  if self._thread:
   self._thread.join(timeout=5)
   self._thread=None
  print("[LlmJobQueue] Stopped")

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
    self._cleanup_stale_jobs()
    self._process_pending_jobs()
   except Exception as e:
    print(f"[LlmJobQueue] Worker error: {e}")
   time.sleep(self._poll_interval)

 def _cleanup_stale_jobs(self)->None:
  with session_scope() as session:
   repo=LlmJobRepository(session)
   count=repo.cleanup_stale_jobs(self._stale_timeout_minutes)
   if count>0:
    print(f"[LlmJobQueue] Reset {count} stale jobs")

 def _process_pending_jobs(self)->None:
  active_count=len([j for j in self._active_jobs.values() if j])
  available_slots=self._max_concurrent-active_count
  if available_slots<=0:
   return
  with session_scope() as session:
   repo=LlmJobRepository(session)
   pending_jobs=repo.get_pending_jobs(limit=available_slots)
   for job in pending_jobs:
    if job.id not in self._active_jobs:
     claimed=repo.claim_job(job.id)
     if claimed:
      self._active_jobs[job.id]=True
      thread=threading.Thread(target=self._execute_job,args=(job.id,),daemon=True)
      thread.start()

 def _execute_job(self,job_id:str)->None:
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
   self._active_jobs.pop(job_id,None)

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
  if self._sio:
   self._sio.emit("llm_job:completed",{"jobId":job_id,"job":job})

 def get_stats(self)->Dict[str,Any]:
  with session_scope() as session:
   repo=LlmJobRepository(session)
   running=repo.get_running_count()
   pending=len(repo.get_pending_jobs(limit=100))
  return {
   "maxConcurrent":self._max_concurrent,
   "activeJobs":len([j for j in self._active_jobs.values() if j]),
   "runningInDb":running,
   "pendingInDb":pending,
  }


def get_llm_job_queue()->LlmJobQueue:
 return LlmJobQueue()
