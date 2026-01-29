import time
from functools import wraps
from typing import Dict,Optional,Callable,Any
from collections import defaultdict
import threading
from fastapi import Request,Response
from fastapi.responses import JSONResponse


class RateLimiter:
 def __init__(self,default_limit:int=60,default_window:int=60,cleanup_interval:int=300):
  self._default_limit=default_limit
  self._default_window=default_window
  self._requests:Dict[str,list]=defaultdict(list)
  self._lock=threading.Lock()
  self._endpoint_limits:Dict[str,tuple]={}
  self._cleanup_interval=cleanup_interval
  self._last_cleanup=time.time()
  self._cleanup_thread:Optional[threading.Thread]=None

 def start_cleanup_thread(self)->None:
  if self._cleanup_thread is None or not self._cleanup_thread.is_alive():
   self._cleanup_thread=threading.Thread(target=self._cleanup_loop,daemon=True)
   self._cleanup_thread.start()

 def _cleanup_loop(self)->None:
  while True:
   time.sleep(self._cleanup_interval)
   self._global_cleanup()

 def _global_cleanup(self)->None:
  with self._lock:
   now=time.time()
   max_window=max((w for _,w in self._endpoint_limits.values()),default=self._default_window)
   stale_clients=[
    cid for cid,timestamps in self._requests.items()
    if not timestamps or now-max(timestamps)>max_window*2
   ]
   for cid in stale_clients:
    del self._requests[cid]

 def set_limit(self,endpoint:str,limit:int,window:int=60)->None:
  self._endpoint_limits[endpoint]=(limit,window)

 def _get_client_id(self,request:Request)->str:
  if request.client:
   return request.client.host or"unknown"
  return "unknown"

 def _get_limit_for_endpoint(self,endpoint:str)->tuple:
  return self._endpoint_limits.get(endpoint,(self._default_limit,self._default_window))

 def _cleanup_old_requests(self,client_id:str,window:int)->None:
  now=time.time()
  self._requests[client_id]=[t for t in self._requests[client_id] if now-t<window]

 def is_allowed(self,request:Request,endpoint:Optional[str]=None)->tuple:
  client_id=self._get_client_id(request)
  limit,window=self._get_limit_for_endpoint(endpoint or"")
  with self._lock:
   self._cleanup_old_requests(client_id,window)
   current_count=len(self._requests[client_id])
   if current_count>=limit:
    retry_after=int(window-(time.time()-self._requests[client_id][0]))
    return False,{"limit":limit,"remaining":0,"retry_after":max(1,retry_after)}
   self._requests[client_id].append(time.time())
   return True,{"limit":limit,"remaining":limit-current_count-1,"retry_after":0}

 def get_stats(self)->Dict[str,Any]:
  with self._lock:
   return {
    "total_clients":len(self._requests),
    "endpoint_limits":dict(self._endpoint_limits),
    "default_limit":self._default_limit,
    "default_window":self._default_window,
   }


_limiter:Optional[RateLimiter]=None


def create_limiter(default_limit:int=60,default_window:int=60)->RateLimiter:
 global _limiter
 _limiter=RateLimiter(default_limit,default_window)
 return _limiter


def get_limiter()->Optional[RateLimiter]:
 return _limiter


def init_rate_limiter(default_limit:int=60,default_window:int=60)->RateLimiter:
 limiter=create_limiter(default_limit,default_window)
 limiter.set_limit("/api/ai/chat",30,60)
 limiter.set_limit("/api/ai/chat/stream",30,60)
 limiter.set_limit("/api/projects/<project_id>/start",10,60)
 limiter.set_limit("/api/agents/<agent_id>/execute",10,60)
 limiter.start_cleanup_thread()
 return limiter


async def rate_limit_middleware(request:Request,call_next:Callable)->Response:
 limiter=get_limiter()
 if limiter is None:
  return await call_next(request)
 endpoint=request.url.path
 allowed,info=limiter.is_allowed(request,endpoint)
 if not allowed:
  response=JSONResponse(
   status_code=429,
   content={
    "error":{
     "code":"RATE_LIMIT_EXCEEDED",
     "message":"リクエスト制限を超過しました",
     "details":info
    }
   }
  )
  response.headers["X-RateLimit-Limit"]=str(info["limit"])
  response.headers["X-RateLimit-Remaining"]=str(info["remaining"])
  response.headers["Retry-After"]=str(info["retry_after"])
  return response
 response=await call_next(request)
 response.headers["X-RateLimit-Limit"]=str(info["limit"])
 response.headers["X-RateLimit-Remaining"]=str(info["remaining"])
 return response
