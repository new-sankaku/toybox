from typing import Optional,Callable
from models.database import session_scope


class BaseService:
 def __init__(self,sio=None):
  self._sio = sio

 def set_sio(self,sio):
  self._sio = sio

 def _emit_event(self,event:str,data:dict,project_id:str):
  if self._sio:
   try:
    self._sio.emit(event,data,room=f"project:{project_id}")
   except Exception as e:
    print(f"[Service] Error emitting {event}: {e}")
