import threading
from typing import Dict,List,Callable,Type,Any
from middleware.logger import get_logger


class EventBus:
    def __init__(self):
        self._subscribers:Dict[Type,List[Callable]]={}
        self._lock=threading.Lock()

    def subscribe(self,event_type:Type,handler:Callable)->None:
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type]=[]
            self._subscribers[event_type].append(handler)

    def publish(self,event:Any)->None:
        event_type=type(event)
        with self._lock:
            handlers=list(self._subscribers.get(event_type,[]))
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                get_logger().error(
                    f"EventBus handler error for {event_type.__name__}: {e}",
                    exc_info=True,
                )

    def unsubscribe(self,event_type:Type,handler:Callable)->None:
        with self._lock:
            if event_type in self._subscribers:
                self._subscribers[event_type]=[
                    h for h in self._subscribers[event_type] if h!=handler
                ]

    def clear(self)->None:
        with self._lock:
            self._subscribers.clear()
