"""AIプロバイダーヘルスモニター"""
import threading
import time
from typing import Dict,Optional,Callable,Any,Set
from datetime import datetime
from middleware.logger import get_logger
from .base import HealthCheckResult
from .registry import ProviderRegistry


class ProviderHealthMonitor:
 """プロバイダーのヘルス状態を定期監視"""
 _instance:Optional["ProviderHealthMonitor"]=None
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
  self._health_states:Dict[str,HealthCheckResult]={}
  self._check_interval=10
  self._running=False
  self._thread:Optional[threading.Thread]=None
  self._on_health_change:Optional[Callable[[str,HealthCheckResult],None]]=None
  self._socket_manager=None
  self._initialized=True

 def set_check_interval(self,seconds:int)->None:
  self._check_interval=max(5,seconds)

 def set_socket_manager(self,socket_manager)->None:
  self._socket_manager=socket_manager

 def set_socketio(self,sio)->None:
  pass

 def set_health_change_callback(self,callback:Callable[[str,HealthCheckResult],None])->None:
  self._on_health_change=callback

 def start(self)->None:
  if self._running:
   return
  self._running=True
  self._thread=threading.Thread(target=self._monitor_loop,daemon=True)
  self._thread.start()

 def stop(self)->None:
  self._running=False
  if self._thread:
   self._thread.join(timeout=2)
   self._thread=None

 def get_health_status(self,provider_id:str)->Optional[HealthCheckResult]:
  return self._health_states.get(provider_id)

 def get_all_health_status(self)->Dict[str,Dict[str,Any]]:
  return {
   pid:state.to_dict() for pid,state in self._health_states.items()
  }

 def check_provider_now(self,provider_id:str)->HealthCheckResult:
  provider=ProviderRegistry.get_fresh(provider_id)
  if not provider:
   result=HealthCheckResult(
    available=False,
    error=f"プロバイダーが見つかりません: {provider_id}",
    checked_at=datetime.now(),
   )
  elif not provider.validate_config():
   result=HealthCheckResult(
    available=False,
    error="APIキーが設定されていません",
    checked_at=datetime.now(),
   )
  else:
   result=provider.health_check()
  self._update_health_state(provider_id,result)
  return result

 def _get_active_provider_ids(self)->Set[str]:
  from ai_config import get_usage_categories
  ids=set()
  for cat in get_usage_categories():
   d=cat.get('default',{})
   pid=d.get('provider','')
   if pid:
    ids.add(pid)
  return ids

 def _monitor_loop(self)->None:
  while self._running:
   self._check_all_providers()
   time.sleep(self._check_interval)

 def _check_all_providers(self)->None:
  active_ids=self._get_active_provider_ids()
  for provider_id in active_ids:
   if provider_id=="mock":
    continue
   if not ProviderRegistry.is_registered(provider_id):
    continue
   try:
    self.check_provider_now(provider_id)
   except Exception:
    self._update_health_state(
     provider_id,
     HealthCheckResult(
      available=False,
      error="ヘルスチェック中に例外が発生しました",
      checked_at=datetime.now(),
     )
    )

 def _update_health_state(self,provider_id:str,result:HealthCheckResult)->None:
  previous=self._health_states.get(provider_id)
  self._health_states[provider_id]=result
  state_changed=(
   previous is None or
   previous.available!=result.available
  )
  if state_changed:
   status="available" if result.available else"unavailable"
   msg=f"プロバイダー {provider_id} の状態が変化: {status}"
   if result.error:
    msg+=f" ({result.error})"
   get_logger().info(msg)
   if self._on_health_change:
    self._on_health_change(provider_id,result)
   if self._socket_manager:
    try:
     import asyncio
     try:
      loop=asyncio.get_running_loop()
      asyncio.create_task(self._socket_manager.emit("provider_health_changed",{
       "provider_id":provider_id,
       "health":result.to_dict(),
      }))
     except RuntimeError:
      pass
    except Exception as e:
     get_logger().warning(f"Error emitting health change: {e}")


def get_health_monitor()->ProviderHealthMonitor:
 return ProviderHealthMonitor()
