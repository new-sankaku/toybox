import asyncio
import threading
import time
from typing import Optional,Dict,Any,Callable
from models.database import session_scope
from repositories.llm_job import LlmJobRepository
from providers.registry import get_provider
from providers.base import AIProviderConfig
from services.concurrency_controller import ConcurrencyController
from services.token_budget_validator import TokenBudgetValidator
from services.llm_message_builder import LlmMessageBuilder,LlmStreamExecutor
from middleware.logger import get_logger

MAX_JOB_RETRIES=3


class LlmJobQueue:
    _instance:Optional["LlmJobQueue"]=None
    _lock=threading.Lock()

    def __new__(cls,*args,**kwargs):
        if kwargs.get("_skip_singleton"):
            return super().__new__(cls)
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance=super().__new__(cls)
                    cls._instance._initialized=False
        return cls._instance

    def __init__(self,concurrency_controller:Optional[ConcurrencyController]=None,token_validator:Optional[TokenBudgetValidator]=None,_skip_singleton:bool=False):
        if hasattr(self,"_initialized") and self._initialized:
            return
        self._poll_interval=1.0
        self._running=False
        self._thread:Optional[threading.Thread]=None
        self._concurrency=concurrency_controller or ConcurrencyController()
        self._token_validator=token_validator or TokenBudgetValidator()
        self._job_callbacks:Dict[str,Callable[[Dict],None]]={}
        self._speech_callbacks:Dict[str,Callable[[str],None]]={}
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
            return LlmJobRepository(session).cleanup_project_jobs(project_id)

    def submit_job(self,project_id:str,agent_id:str,provider_id:str,model:str,prompt:str,max_tokens:int=32768,priority:int=0,callback:Optional[Callable[[Dict],None]]=None,system_prompt:Optional[str]=None,temperature:Optional[str]=None,messages_json:Optional[str]=None,on_speech:Optional[Callable[[str],None]]=None,token_budget:Optional[Dict[str,Any]]=None,tools_json:Optional[str]=None)->Dict[str,Any]:
        with session_scope() as session:
            repo=LlmJobRepository(session)
            used=repo.get_project_token_usage(project_id)
            self._token_validator.validate_and_raise(project_id,used,token_budget)
            job=repo.create_job(project_id=project_id,agent_id=agent_id,provider_id=provider_id,model=model,prompt=prompt,max_tokens=max_tokens,priority=priority,system_prompt=system_prompt,temperature=temperature,messages_json=messages_json,tools_json=tools_json)
            if callback:
                self._job_callbacks[job["id"]]=callback
            if on_speech:
                self._speech_callbacks[job["id"]]=on_speech
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

    def _process_pending_jobs(self)->None:
        with session_scope() as session:
            repo=LlmJobRepository(session)
            for job in repo.get_pending_jobs(limit=20):
                if not self._concurrency.can_start_job(job.provider_id,job.id):
                    continue
                if repo.claim_job(job.id):
                    self._concurrency.register_job(job.id,job.provider_id)
                    threading.Thread(target=self._execute_job,args=(job.id,job.provider_id),daemon=True).start()

    def _execute_job(self,job_id:str,provider_id:str)->None:
        try:
            self._execute_job_internal(job_id,provider_id)
        except Exception as e:
            self._handle_job_error(job_id,e)
        finally:
            self._concurrency.unregister_job(job_id,provider_id)

    def _execute_job_internal(self,job_id:str,provider_id:str)->None:
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
            messages=LlmMessageBuilder.build_messages(job)
            chat_kwargs=LlmMessageBuilder.build_chat_kwargs(job,messages)
            speech_cb=self._speech_callbacks.pop(job_id,None)
            self._execute_with_streaming(repo,job_id,provider,chat_kwargs,speech_cb)
            self._notify_completion(job_id)

    def _execute_with_streaming(self,repo:LlmJobRepository,job_id:str,provider,chat_kwargs:Dict[str,Any],speech_cb:Optional[Callable[[str],None]])->None:
        executor=LlmStreamExecutor(provider,chat_kwargs)
        try:
            content,input_tokens,output_tokens,tool_calls=executor.execute_stream(speech_cb)
        except Exception as stream_err:
            get_logger().warning(f"LlmJobQueue stream fallback for job {job_id}: {stream_err}")
            content,input_tokens,output_tokens,tool_calls=executor.execute_fallback(speech_cb)
        response_content=LlmMessageBuilder.serialize_tool_calls_response(content,tool_calls)
        repo.complete_job(job_id=job_id,response_content=response_content,tokens_input=input_tokens,tokens_output=output_tokens)

    def _handle_job_error(self,job_id:str,error:Exception)->None:
        self._speech_callbacks.pop(job_id,None)
        with session_scope() as session:
            repo=LlmJobRepository(session)
            job=repo.get(job_id)
            if job and job.retry_count<MAX_JOB_RETRIES:
                repo.retry_job(job_id)
                get_logger().warning(f"LlmJobQueue job {job_id} retry ({job.retry_count+1}/{MAX_JOB_RETRIES}): {error}")
            else:
                repo.fail_job(job_id,str(error))
                self._notify_completion(job_id)

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
