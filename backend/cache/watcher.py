import os
import threading
from typing import Callable,Optional,Set
from datetime import datetime
from middleware.logger import get_logger
from .config import FileCacheConfig
class FileWatcher:
 def __init__(self,config:FileCacheConfig,callback:Callable[[str,str],None]):
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
   class Handler(FileSystemEventHandler):
    def __init__(inner_self,watcher:"FileWatcher"):
     super().__init__()
     inner_self.watcher=watcher
    def on_created(inner_self,event):
     if not event.is_directory:
      inner_self.watcher._handle_event(event.src_path,"created")
    def on_modified(inner_self,event):
     if not event.is_directory:
      inner_self.watcher._handle_event(event.src_path,"modified")
    def on_deleted(inner_self,event):
     if not event.is_directory:
      inner_self.watcher._handle_event(event.src_path,"deleted")
    def on_moved(inner_self,event):
     if not event.is_directory:
      inner_self.watcher._handle_event(event.src_path,"moved")
      inner_self.watcher._handle_event(event.dest_path,"created")
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
 def _handle_event(self,path:str,event_type:str)->None:
  with self._debounce_lock:
   self._debounce_events[path]={"event_type":event_type,"time":datetime.now()}
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
    self._callback(path,data["event_type"])
   except Exception as e:
    self._logger.error(f"Error in FileWatcher callback for {path}: {e}",exc_info=True)
 @property
 def is_watching(self)->bool:
  return self._watching
 @property
 def watch_path(self)->Optional[str]:
  return self._watch_path
class PollingFileWatcher:
 def __init__(self,config:FileCacheConfig,callback:Callable[[str,str],None]):
  self._config=config
  self._callback=callback
  self._logger=get_logger()
  self._watching=False
  self._watch_path:Optional[str]=None
  self._file_states:dict={}
  self._poll_thread:Optional[threading.Thread]=None
  self._stop_event=threading.Event()
  self._poll_interval=5.0
 def start(self,path:str)->bool:
  if self._watching:
   return False
  if not os.path.exists(path):
   return False
  self._watch_path=path
  self._file_states=self._scan_files(path)
  self._stop_event.clear()
  self._poll_thread=threading.Thread(target=self._poll_loop,daemon=True)
  self._poll_thread.start()
  self._watching=True
  self._logger.info(f"PollingFileWatcher started watching: {path}")
  return True
 def stop(self)->None:
  self._stop_event.set()
  if self._poll_thread:
   self._poll_thread.join(timeout=10)
   self._poll_thread=None
  self._watching=False
  self._watch_path=None
  self._logger.info("PollingFileWatcher stopped")
 def _poll_loop(self)->None:
  while not self._stop_event.wait(self._poll_interval):
   if self._watch_path:
    self._check_changes()
 def _check_changes(self)->None:
  if not self._watch_path:
   return
  new_states=self._scan_files(self._watch_path)
  old_paths=set(self._file_states.keys())
  new_paths=set(new_states.keys())
  created=new_paths-old_paths
  deleted=old_paths-new_paths
  common=old_paths&new_paths
  for path in created:
   self._callback(path,"created")
  for path in deleted:
   self._callback(path,"deleted")
  for path in common:
   if new_states[path]!=self._file_states[path]:
    self._callback(path,"modified")
  self._file_states=new_states
 def _scan_files(self,root:str)->dict:
  states={}
  for dirpath,_,filenames in os.walk(root):
   for filename in filenames:
    filepath=os.path.join(dirpath,filename)
    try:
     stat=os.stat(filepath)
     states[filepath]=(stat.st_mtime,stat.st_size)
    except OSError:
     pass
  return states
 @property
 def is_watching(self)->bool:
  return self._watching
 @property
 def watch_path(self)->Optional[str]:
  return self._watch_path
