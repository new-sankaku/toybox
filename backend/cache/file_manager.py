from typing import Any,Dict,List,Optional,TYPE_CHECKING
from pathlib import Path
import hashlib
import os
from datetime import datetime
from .config import FileCacheConfig,get_file_cache_config
from middleware.logger import get_logger
if TYPE_CHECKING:
 from .content_cache import FileContentCache
 from .tree_cache import FileTreeCache
 from .metadata_store import FileMetadataStore
 from .watcher import FileWatcher
class FileManager:
 _instance:Optional["FileManager"]=None
 def __new__(cls,project_id:str=None,working_dir:str=None):
  if cls._instance is None:
   cls._instance=super().__new__(cls)
   cls._instance._initialized=False
  return cls._instance
 def __init__(self,project_id:str=None,working_dir:str=None):
  if self._initialized:
   if project_id:
    self._project_id=project_id
   if working_dir:
    self._working_dir=working_dir
   return
  self._config=get_file_cache_config()
  self._project_id=project_id or"default"
  self._working_dir=working_dir or os.getcwd()
  self._content_cache:Optional["FileContentCache"]=None
  self._tree_cache:Optional["FileTreeCache"]=None
  self._metadata_store:Optional["FileMetadataStore"]=None
  self._watcher:Optional["FileWatcher"]=None
  self._logger=get_logger()
  self._initialized=True
 def _get_content_cache(self)->"FileContentCache":
  if self._content_cache is None:
   from .content_cache import FileContentCache
   self._content_cache=FileContentCache(self._config)
  return self._content_cache
 def _get_tree_cache(self)->"FileTreeCache":
  if self._tree_cache is None:
   from .tree_cache import FileTreeCache
   self._tree_cache=FileTreeCache(self._config,self._project_id)
  return self._tree_cache
 def _get_metadata_store(self)->"FileMetadataStore":
  if self._metadata_store is None:
   from .metadata_store import FileMetadataStore
   self._metadata_store=FileMetadataStore(self._project_id)
  return self._metadata_store
 def _get_watcher(self)->"FileWatcher":
  if self._watcher is None:
   from .watcher import FileWatcher
   self._watcher=FileWatcher(self._config,self._on_file_changed)
  return self._watcher
 def _on_file_changed(self,path:str,event_type:str)->None:
  self._logger.info(f"File changed: {path} ({event_type})")
  self.invalidate_cache(path)
 async def read_file(self,path:str,encoding:str="utf-8",max_lines:int=None)->Dict[str,Any]:
  if not self._config.enabled:
   return await self._read_file_direct(path,encoding,max_lines)
  full_path=self._resolve_path(path)
  content_cache=self._get_content_cache()
  cached=content_cache.get(full_path)
  if cached is not None:
   if self._config.track_access_stats:
    self._get_metadata_store().record_access(full_path)
   content=cached
   if max_lines:
    lines=content.split("\n")
    content="\n".join(lines[:max_lines])
   return {"content":content,"from_cache":True,"path":full_path}
  result=await self._read_file_direct(full_path,encoding,max_lines)
  if result.get("success",True):
   content_cache.put(full_path,result.get("content",""))
   self._ensure_basic_metadata(full_path,result.get("content",""))
   if self._config.track_access_stats:
    self._get_metadata_store().record_access(full_path)
  return result
 async def _read_file_direct(self,path:str,encoding:str,max_lines:int=None)->Dict[str,Any]:
  import asyncio
  try:
   def read_sync():
    with open(path,"r",encoding=encoding) as f:
     if max_lines:
      lines=[]
      for i,line in enumerate(f):
       if i>=max_lines:
        break
       lines.append(line)
      return"".join(lines)
     return f.read()
   content=await asyncio.to_thread(read_sync)
   return {"content":content,"from_cache":False,"path":path,"success":True}
  except Exception as e:
   return {"content":"","from_cache":False,"path":path,"success":False,"error":str(e)}
 async def write_file(self,path:str,content:str,encoding:str="utf-8",agent_id:str=None)->Dict[str,Any]:
  import asyncio
  full_path=self._resolve_path(path)
  try:
   parent=os.path.dirname(full_path)
   if parent and not os.path.exists(parent):
    os.makedirs(parent,exist_ok=True)
   def write_sync():
    with open(full_path,"w",encoding=encoding) as f:
     f.write(content)
   await asyncio.to_thread(write_sync)
   if self._config.enabled:
    self._get_content_cache().put(full_path,content)
    self._get_tree_cache().invalidate_path(os.path.dirname(full_path))
    metadata=self._build_metadata(full_path,content,agent_id)
    self._get_metadata_store().upsert(metadata)
   return {"success":True,"path":full_path,"size":len(content.encode(encoding))}
  except Exception as e:
   return {"success":False,"path":full_path,"error":str(e)}
 async def edit_file(self,path:str,old_string:str,new_string:str,encoding:str="utf-8",replace_all:bool=False,agent_id:str=None)->Dict[str,Any]:
  import asyncio
  full_path=self._resolve_path(path)
  try:
   def edit_sync():
    with open(full_path,"r",encoding=encoding) as f:
     content=f.read()
    count=content.count(old_string)
    if count==0:
     return {"error":"old_string not found in file","count":0}
    if not replace_all and count>1:
     return {"error":f"old_string found {count} times. Use replace_all=true","count":0}
    if replace_all:
     new_content=content.replace(old_string,new_string)
    else:
     new_content=content.replace(old_string,new_string,1)
    with open(full_path,"w",encoding=encoding) as f:
     f.write(new_content)
    return {"content":new_content,"count":count if replace_all else 1}
   result=await asyncio.to_thread(edit_sync)
   if"error" in result:
    return {"success":False,"path":full_path,"error":result["error"]}
   if self._config.enabled:
    self._get_content_cache().put(full_path,result["content"])
    metadata=self._build_metadata(full_path,result["content"],agent_id)
    self._get_metadata_store().upsert(metadata)
   return {"success":True,"path":full_path,"replacements":result["count"]}
  except Exception as e:
   return {"success":False,"path":full_path,"error":str(e)}
 async def list_directory(self,path:str=".",pattern:str="*",recursive:bool=False,max_items:int=100)->Dict[str,Any]:
  import asyncio
  import fnmatch
  full_path=self._resolve_path(path)
  if self._config.enabled:
   tree_cache=self._get_tree_cache()
   cached=tree_cache.get(full_path,pattern,recursive)
   if cached is not None:
    items=cached[:max_items]
    return {"items":items,"path":full_path,"count":len(items),"from_cache":True}
  try:
   def list_sync():
    items=[]
    if recursive:
     for root,dirs,files in os.walk(full_path):
      for name in files+dirs:
       if len(items)>=max_items:
        return items
       if fnmatch.fnmatch(name,pattern):
        item_path=os.path.join(root,name)
        items.append(self._get_item_info(item_path,full_path))
    else:
     for name in os.listdir(full_path):
      if len(items)>=max_items:
       break
      if fnmatch.fnmatch(name,pattern):
       item_path=os.path.join(full_path,name)
       items.append(self._get_item_info(item_path,full_path))
    return items
   items=await asyncio.to_thread(list_sync)
   if self._config.enabled:
    tree_cache=self._get_tree_cache()
    tree_cache.put(full_path,pattern,recursive,items)
   return {"items":items,"path":full_path,"count":len(items),"from_cache":False}
  except Exception as e:
   return {"items":[],"path":full_path,"count":0,"error":str(e)}
 def _get_item_info(self,item_path:str,base_path:str)->Dict[str,Any]:
  try:
   stat=os.stat(item_path)
   is_dir=os.path.isdir(item_path)
   return {
    "name":os.path.basename(item_path),
    "path":os.path.relpath(item_path,base_path),
    "type":"directory" if is_dir else"file",
    "size":0 if is_dir else stat.st_size,
    "modified":stat.st_mtime,
   }
  except OSError:
   return {
    "name":os.path.basename(item_path),
    "path":os.path.relpath(item_path,base_path),
    "type":"unknown",
    "size":0,
    "modified":0,
   }
 def _build_metadata(self,path:str,content:str,agent_id:str=None)->Dict[str,Any]:
  file_hash=hashlib.sha256(content.encode("utf-8")).hexdigest()
  ext=os.path.splitext(path)[1].lower()
  file_type=self._detect_file_type(ext)
  language=self._detect_language(ext)
  return {
   "path":path,
   "file_type":file_type,
   "mime_type":self._get_mime_type(ext),
   "size":len(content.encode("utf-8")),
   "hash":file_hash,
   "encoding":"utf-8",
   "language":language,
   "line_count":content.count("\n")+1 if content else 0,
   "agent_modified":agent_id,
   "modified_at":datetime.now(),
  }
 def _ensure_basic_metadata(self,path:str,content:str)->None:
  try:
   store=self._get_metadata_store()
   existing=store.get(path)
   if existing is None:
    metadata=self._build_metadata(path,content,None)
    store.upsert(metadata)
  except Exception:
   pass
 def _detect_file_type(self,ext:str)->str:
  source_exts={".py",".js",".ts",".tsx",".jsx",".java",".go",".rs",".c",".cpp",".h"}
  config_exts={".json",".yaml",".yml",".toml",".ini",".env"}
  doc_exts={".md",".txt",".rst",".adoc"}
  if ext in source_exts:
   return"source"
  if ext in config_exts:
   return"config"
  if ext in doc_exts:
   return"doc"
  return"asset"
 def _detect_language(self,ext:str)->Optional[str]:
  lang_map={
   ".py":"python",".js":"javascript",".ts":"typescript",
   ".tsx":"typescript",".jsx":"javascript",".java":"java",
   ".go":"go",".rs":"rust",".c":"c",".cpp":"cpp",
   ".h":"c",".lua":"lua",".gd":"gdscript",".cs":"csharp",
  }
  return lang_map.get(ext)
 def _get_mime_type(self,ext:str)->str:
  mime_map={
   ".py":"text/x-python",".js":"text/javascript",".ts":"text/typescript",
   ".json":"application/json",".yaml":"text/yaml",".yml":"text/yaml",
   ".md":"text/markdown",".txt":"text/plain",".html":"text/html",
   ".css":"text/css",".xml":"application/xml",
  }
  return mime_map.get(ext,"application/octet-stream")
 def _resolve_path(self,path:str)->str:
  if os.path.isabs(path):
   return os.path.normpath(path)
  return os.path.normpath(os.path.join(self._working_dir,path))
 def invalidate_cache(self,path:str=None)->None:
  if path:
   full_path=self._resolve_path(path)
   if self._content_cache:
    self._content_cache.invalidate(full_path)
   if self._tree_cache:
    self._tree_cache.invalidate_path(os.path.dirname(full_path))
  else:
   if self._content_cache:
    self._content_cache.clear()
   if self._tree_cache:
    self._tree_cache.clear()
 def get_metadata(self,path:str)->Optional[Dict[str,Any]]:
  full_path=self._resolve_path(path)
  return self._get_metadata_store().get(full_path)
 def start_watching(self,path:str=None)->None:
  if not self._config.watcher_enabled:
   return
  watch_path=path or self._working_dir
  self._get_watcher().start(watch_path)
 def stop_watching(self)->None:
  if self._watcher:
   self._watcher.stop()
 def get_cache_stats(self)->Dict[str,Any]:
  stats={"enabled":self._config.enabled}
  if self._content_cache:
   stats["content_cache"]=self._content_cache.get_stats()
  if self._tree_cache:
   stats["tree_cache"]=self._tree_cache.get_stats()
  return stats
 @classmethod
 def reset(cls)->None:
  if cls._instance:
   cls._instance.stop_watching()
   cls._instance=None
def get_file_manager(project_id:str=None,working_dir:str=None)->FileManager:
 return FileManager(project_id,working_dir)
