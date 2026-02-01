from typing import Any,Dict,Optional
from collections import OrderedDict
from datetime import datetime
import threading
from .config import FileCacheConfig
class CacheEntry:
 __slots__=("content","size","created_at","last_accessed_at","access_count")
 def __init__(self,content:str):
  self.content=content
  self.size=len(content.encode("utf-8"))
  self.created_at=datetime.now()
  self.last_accessed_at=datetime.now()
  self.access_count=1
 def touch(self)->None:
  self.last_accessed_at=datetime.now()
  self.access_count+=1
class FileContentCache:
 def __init__(self,config:FileCacheConfig):
  self._config=config
  self._cache:OrderedDict[str,CacheEntry]=OrderedDict()
  self._lock=threading.RLock()
  self._current_size_bytes=0
  self._hits=0
  self._misses=0
 @property
 def _max_size_bytes(self)->int:
  return self._config.content_max_size_mb*1024*1024
 @property
 def _max_items(self)->int:
  return self._config.content_max_items
 @property
 def _max_age_seconds(self)->int:
  return self._config.content_max_age_seconds
 def get(self,path:str)->Optional[str]:
  with self._lock:
   entry=self._cache.get(path)
   if entry is None:
    self._misses+=1
    return None
   age=(datetime.now()-entry.last_accessed_at).total_seconds()
   if age>self._max_age_seconds:
    self._remove_entry(path)
    self._misses+=1
    return None
   entry.touch()
   self._cache.move_to_end(path)
   self._hits+=1
   return entry.content
 def put(self,path:str,content:str)->None:
  with self._lock:
   new_size=len(content.encode("utf-8"))
   if new_size>self._max_size_bytes:
    return
   if path in self._cache:
    self._remove_entry(path)
   while self._should_evict(new_size):
    self._evict_oldest()
   entry=CacheEntry(content)
   self._cache[path]=entry
   self._current_size_bytes+=entry.size
 def _should_evict(self,additional_size:int)->bool:
  if len(self._cache)>=self._max_items:
   return True
  if self._current_size_bytes+additional_size>self._max_size_bytes:
   return True
  return False
 def _evict_oldest(self)->None:
  if not self._cache:
   return
  oldest_key=next(iter(self._cache))
  self._remove_entry(oldest_key)
 def _remove_entry(self,path:str)->None:
  entry=self._cache.pop(path,None)
  if entry:
   self._current_size_bytes-=entry.size
 def invalidate(self,path:str)->None:
  with self._lock:
   self._remove_entry(path)
 def clear(self)->None:
  with self._lock:
   self._cache.clear()
   self._current_size_bytes=0
 def contains(self,path:str)->bool:
  with self._lock:
   return path in self._cache
 def get_stats(self)->Dict[str,Any]:
  with self._lock:
   total_requests=self._hits+self._misses
   hit_rate=self._hits/total_requests if total_requests>0 else 0.0
   return {
    "items":len(self._cache),
    "max_items":self._max_items,
    "size_bytes":self._current_size_bytes,
    "max_size_bytes":self._max_size_bytes,
    "hits":self._hits,
    "misses":self._misses,
    "hit_rate":round(hit_rate,4),
   }
 def cleanup_expired(self)->int:
  with self._lock:
   now=datetime.now()
   expired=[]
   for path,entry in self._cache.items():
    age=(now-entry.last_accessed_at).total_seconds()
    if age>self._max_age_seconds:
     expired.append(path)
   for path in expired:
    self._remove_entry(path)
   return len(expired)
