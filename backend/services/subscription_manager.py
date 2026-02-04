import threading
from typing import Dict,Set


class SubscriptionManager:
    def __init__(self):
        self.subscriptions:Dict[str,Set[str]]={}
        self._lock=threading.Lock()

    def add_subscription(self,project_id:str,sid:str):
        with self._lock:
            if project_id not in self.subscriptions:
                self.subscriptions[project_id]=set()
            self.subscriptions[project_id].add(sid)

    def remove_subscription(self,project_id:str,sid:str):
        with self._lock:
            if project_id in self.subscriptions:
                self.subscriptions[project_id].discard(sid)

    def remove_all_subscriptions(self,sid:str):
        with self._lock:
            for project_id in self.subscriptions:
                self.subscriptions[project_id].discard(sid)

    def get_subscribers(self,project_id:str)->set:
        with self._lock:
            return self.subscriptions.get(project_id,set()).copy()
