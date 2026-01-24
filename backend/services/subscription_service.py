import threading
from typing import Dict
from .base import BaseService


class SubscriptionService(BaseService):

 def __init__(self,sio=None):
  super().__init__(sio)
  self._subscriptions:Dict[str,set] = {}
  self._lock = threading.Lock()

 def add(self,project_id:str,sid:str):
  with self._lock:
   if project_id not in self._subscriptions:
    self._subscriptions[project_id] = set()
   self._subscriptions[project_id].add(sid)

 def remove(self,project_id:str,sid:str):
  with self._lock:
   if project_id in self._subscriptions:
    self._subscriptions[project_id].discard(sid)

 def remove_all(self,sid:str):
  with self._lock:
   for project_id in self._subscriptions:
    self._subscriptions[project_id].discard(sid)

 def get_subscribers(self,project_id:str)->set:
  with self._lock:
   return self._subscriptions.get(project_id,set()).copy()
