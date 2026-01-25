"""AIプロバイダーヘルスモニター"""
import threading
import time
from typing import Dict,Optional,Callable,Any
from datetime import datetime
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
  self._sio=None
  self._initialized=True

 def set_check_interval(self,seconds:int)->None:
  self._check_interval=max(5,seconds)

 def set_socketio(self,sio)->None:
  self._sio=sio

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

 def _monitor_loop(self)->None:
  while self._running:
   self._check_all_providers()
   time.sleep(self._check_interval)

 def _check_all_providers(self)->None:
  providers=ProviderRegistry.list_providers()
  for provider_info in providers:
   provider_id=provider_info["id"]
   if provider_id=="mock":
    continue
   try:
    self.check_provider_now(provider_id)
   except Exception as e:
    self._update_health_state(
     provider_id,
     HealthCheckResult(
      available=False,
      error=str(e),
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
   if self._on_health_change:
    self._on_health_change(provider_id,result)
   if self._sio:
    self._sio.emit("provider_health_changed",{
     "provider_id":provider_id,
     "health":result.to_dict(),
    })


def get_health_monitor()->ProviderHealthMonitor:
 return ProviderHealthMonitor()
