from typing import Any,Dict,List,Optional
from datetime import datetime
import threading
import json
from .config import FileCacheConfig
class TreeCacheKey:
 __slots__=("path","pattern","recursive")
 def __init__(self,path:str,pattern:str,recursive:bool):
  self.path=path
  self.pattern=pattern
  self.recursive=recursive
 def __hash__(self):
  return hash((self.path,self.pattern,self.recursive))
 def __eq__(self,other):
  if not isinstance(other,TreeCacheKey):
   return False
  return self.path==other.path and self.pattern==other.pattern and self.recursive==other.recursive
 def to_string(self)->str:
  return f"{self.path}|{self.pattern}|{self.recursive}"
 @classmethod
 def from_string(cls,s:str)->"TreeCacheKey":
  parts=s.split("|")
  return cls(parts[0],parts[1],parts[2]=="True")
class TreeCacheEntry:
 __slots__=("items","created_at")
 def __init__(self,items:List[Dict[str,Any]]):
  self.items=items
  self.created_at=datetime.now()
class FileTreeCache:
 def __init__(self,config:FileCacheConfig,project_id:str):
  self._config=config
  self._project_id=project_id
  self._cache:Dict[TreeCacheKey,TreeCacheEntry]={}
  self._lock=threading.RLock()
  self._hits=0
  self._misses=0
  if config.tree_persist_to_db:
   self._load_from_db()
 @property
 def _ttl_seconds(self)->int:
  return self._config.tree_ttl_seconds
 def get(self,path:str,pattern:str,recursive:bool)->Optional[List[Dict[str,Any]]]:
  key=TreeCacheKey(path,pattern,recursive)
  with self._lock:
   entry=self._cache.get(key)
   if entry is None:
    self._misses+=1
    return None
   age=(datetime.now()-entry.created_at).total_seconds()
   if age>self._ttl_seconds:
    del self._cache[key]
    self._misses+=1
    return None
   self._hits+=1
   return entry.items
 def put(self,path:str,pattern:str,recursive:bool,items:List[Dict[str,Any]])->None:
  key=TreeCacheKey(path,pattern,recursive)
  with self._lock:
   self._cache[key]=TreeCacheEntry(items)
   if self._config.tree_persist_to_db:
    self._save_entry_to_db(key,items)
 def invalidate_path(self,path:str)->None:
  with self._lock:
   keys_to_remove=[k for k in self._cache.keys() if k.path==path or k.path.startswith(path+"/") or k.path.startswith(path+"\\")]
   for key in keys_to_remove:
    del self._cache[key]
   if self._config.tree_persist_to_db:
    self._delete_entries_from_db(path)
 def clear(self)->None:
  with self._lock:
   self._cache.clear()
   if self._config.tree_persist_to_db:
    self._clear_db()
 def get_stats(self)->Dict[str,Any]:
  with self._lock:
   total_requests=self._hits+self._misses
   hit_rate=self._hits/total_requests if total_requests>0 else 0.0
   return {
    "entries":len(self._cache),
    "ttl_seconds":self._ttl_seconds,
    "hits":self._hits,
    "misses":self._misses,
    "hit_rate":round(hit_rate,4),
    "persist_enabled":self._config.tree_persist_to_db,
   }
 def cleanup_expired(self)->int:
  with self._lock:
   now=datetime.now()
   expired=[]
   for key,entry in self._cache.items():
    age=(now-entry.created_at).total_seconds()
    if age>self._ttl_seconds:
     expired.append(key)
   for key in expired:
    del self._cache[key]
   return len(expired)
 def _load_from_db(self)->None:
  try:
   from models.database import session_scope
   from models.tables import FileTreeCacheTable
   with session_scope() as session:
    rows=session.query(FileTreeCacheTable).filter_by(project_id=self._project_id).all()
    for row in rows:
     key=TreeCacheKey.from_string(row.cache_key)
     items=json.loads(row.items_json)
     created_at=row.created_at
     age=(datetime.now()-created_at).total_seconds()
     if age<=self._ttl_seconds:
      entry=TreeCacheEntry(items)
      entry.created_at=created_at
      self._cache[key]=entry
  except Exception:
   pass
 def _save_entry_to_db(self,key:TreeCacheKey,items:List[Dict[str,Any]])->None:
  try:
   from models.database import session_scope
   from models.tables import FileTreeCacheTable
   with session_scope() as session:
    cache_key_str=key.to_string()
    existing=session.query(FileTreeCacheTable).filter_by(project_id=self._project_id,cache_key=cache_key_str).first()
    if existing:
     existing.items_json=json.dumps(items,ensure_ascii=False)
     existing.created_at=datetime.now()
    else:
     entry=FileTreeCacheTable(project_id=self._project_id,cache_key=cache_key_str,items_json=json.dumps(items,ensure_ascii=False))
     session.add(entry)
  except Exception:
   pass
 def _delete_entries_from_db(self,path:str)->None:
  try:
   from models.database import session_scope
   from models.tables import FileTreeCacheTable
   with session_scope() as session:
    session.query(FileTreeCacheTable).filter(
     FileTreeCacheTable.project_id==self._project_id,
     FileTreeCacheTable.cache_key.like(f"{path}%")
    ).delete(synchronize_session=False)
  except Exception:
   pass
 def _clear_db(self)->None:
  try:
   from models.database import session_scope
   from models.tables import FileTreeCacheTable
   with session_scope() as session:
    session.query(FileTreeCacheTable).filter_by(project_id=self._project_id).delete()
  except Exception:
   pass
