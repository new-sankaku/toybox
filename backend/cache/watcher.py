import os
import threading
from typing import Callable,Optional
from datetime import datetime
from middleware.logger import get_logger
from .config import FileCacheConfig
class FileWatcher:
    def __init__(self,config:FileCacheConfig,callback:Callable[[str,str,bool],None]):
        self._config=config
        self._callback=callback
        self._logger=get_logger()
        self._observer=None
        self._watching=False
        self._watch_path:Optional[str]=None
        self._debounce_events:dict={}
        self._debounce_lock=threading.Lock()
        self._debounce_timer:Optional[threading.Timer]=None
    @property
    def _debounce_seconds(self)->float:
        return self._config.watcher_debounce_ms/1000.0
    def start(self,path:str)->bool:
        if self._watching:
            self._logger.warning(f"FileWatcher already watching: {self._watch_path}")
            return False
        if not os.path.exists(path):
            self._logger.error(f"Watch path does not exist: {path}")
            return False
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
            ignore_dirs=self._config.ignore_dirs
            class Handler(FileSystemEventHandler):
                def __init__(inner_self,watcher:"FileWatcher"):
                    super().__init__()
                    inner_self.watcher=watcher
                def _should_ignore(inner_self,path:str)->bool:
                    parts=path.split(os.sep)
                    return any(p in ignore_dirs for p in parts)
                def on_created(inner_self,event):
                    if inner_self._should_ignore(event.src_path):
                        return
                    inner_self.watcher._handle_event(event.src_path,"created",event.is_directory)
                def on_modified(inner_self,event):
                    if inner_self._should_ignore(event.src_path):
                        return
                    inner_self.watcher._handle_event(event.src_path,"modified",event.is_directory)
                def on_deleted(inner_self,event):
                    if inner_self._should_ignore(event.src_path):
                        return
                    inner_self.watcher._handle_event(event.src_path,"deleted",event.is_directory)
                def on_moved(inner_self,event):
                    if inner_self._should_ignore(event.src_path):
                        return
                    inner_self.watcher._handle_event(event.src_path,"deleted",event.is_directory)
                    if not inner_self._should_ignore(event.dest_path):
                        inner_self.watcher._handle_event(event.dest_path,"created",event.is_directory)
            self._observer=Observer()
            self._observer.schedule(Handler(self),path,recursive=True)
            self._observer.start()
            self._watching=True
            self._watch_path=path
            self._logger.info(f"FileWatcher started watching: {path}")
            return True
        except ImportError:
            self._logger.warning("watchdog not installed, FileWatcher disabled")
            return False
        except Exception as e:
            self._logger.error(f"Failed to start FileWatcher: {e}",exc_info=True)
            return False
    def stop(self)->None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer=None
        self._watching=False
        self._watch_path=None
        if self._debounce_timer:
            self._debounce_timer.cancel()
            self._debounce_timer=None
        self._logger.info("FileWatcher stopped")
    def _handle_event(self,path:str,event_type:str,is_directory:bool)->None:
        with self._debounce_lock:
            self._debounce_events[path]={"event_type":event_type,"is_directory":is_directory,"time":datetime.now()}
            if self._debounce_timer:
                self._debounce_timer.cancel()
            self._debounce_timer=threading.Timer(self._debounce_seconds,self._flush_events)
            self._debounce_timer.start()
    def _flush_events(self)->None:
        with self._debounce_lock:
            events=dict(self._debounce_events)
            self._debounce_events.clear()
            self._debounce_timer=None
        for path,data in events.items():
            try:
                self._callback(path,data["event_type"],data["is_directory"])
            except Exception as e:
                self._logger.error(f"Error in FileWatcher callback for {path}: {e}",exc_info=True)
    @property
    def is_watching(self)->bool:
        return self._watching
    @property
    def watch_path(self)->Optional[str]:
        return self._watch_path
