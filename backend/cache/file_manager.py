from typing import Any,Dict,List,Optional,TYPE_CHECKING
import os
import hashlib
from datetime import datetime
from .config import FileCacheConfig,get_file_cache_config
from .content_cache import ProjectFileCache
from middleware.logger import get_logger
if TYPE_CHECKING:
    from .watcher import FileWatcher
    from .metadata_store import FileMetadataStore
_project_caches:Dict[str,ProjectFileCache]={}
_project_watchers:Dict[str,"FileWatcher"]={}
_project_metadata_stores:Dict[str,"FileMetadataStore"]={}
class FileManager:
    def __init__(self,project_id:str,working_dir:str):
        self._config=get_file_cache_config()
        self._project_id=project_id
        self._working_dir=os.path.normpath(working_dir)
        self._logger=get_logger()
        self._cache:Optional[ProjectFileCache]=None
        self._watcher:Optional["FileWatcher"]=None
        self._metadata_store:Optional["FileMetadataStore"]=None
    def _get_cache(self)->ProjectFileCache:
        global _project_caches
        if self._project_id not in _project_caches:
            _project_caches[self._project_id]=ProjectFileCache(self._config,self._project_id,self._working_dir)
        return _project_caches[self._project_id]
    def _get_watcher(self)->"FileWatcher":
        global _project_watchers
        if self._project_id not in _project_watchers:
            from .watcher import FileWatcher
            _project_watchers[self._project_id]=FileWatcher(self._config,self._on_file_changed)
        return _project_watchers[self._project_id]
    def _get_metadata_store(self)->"FileMetadataStore":
        global _project_metadata_stores
        if self._project_id not in _project_metadata_stores:
            from .metadata_store import FileMetadataStore
            _project_metadata_stores[self._project_id]=FileMetadataStore(self._project_id)
        return _project_metadata_stores[self._project_id]
    def initialize(self)->Dict[str,Any]:
        if not self._config.enabled:
            return {"enabled":False}
        if not os.path.exists(self._working_dir):
            os.makedirs(self._working_dir,exist_ok=True)
        cache=self._get_cache()
        stats=cache.load_all()
        self._logger.info(f"FileManager initialized for project {self._project_id}: {stats}")
        if self._config.watcher_enabled:
            watcher=self._get_watcher()
            watcher.start(self._working_dir)
        return stats
    def _on_file_changed(self,full_path:str,event_type:str,is_directory:bool)->None:
        rel_path=os.path.relpath(full_path,self._working_dir)
        self._logger.debug(f"File changed: {rel_path} ({event_type}, is_dir={is_directory})")
        cache=self._get_cache()
        if is_directory:
            if event_type=="created":
                cache.add_dir(rel_path)
            elif event_type=="deleted":
                cache.remove_dir(rel_path)
        else:
            if event_type=="deleted":
                cache.remove_file(rel_path)
                self._get_metadata_store().delete(full_path)
            else:
                cache.update_file_from_disk(rel_path)
                entry=cache.get_file(rel_path)
                if entry and entry.content:
                    metadata=self._build_metadata(full_path,entry.content,None)
                    self._get_metadata_store().upsert(metadata)
    def _to_rel_path(self,path:str)->str:
        if os.path.isabs(path):
            return os.path.relpath(path,self._working_dir)
        return path
    def _to_full_path(self,path:str)->str:
        if os.path.isabs(path):
            return os.path.normpath(path)
        return os.path.normpath(os.path.join(self._working_dir,path))
    async def read_file(self,path:str,encoding:str="utf-8",max_lines:int=None)->Dict[str,Any]:
        rel_path=self._to_rel_path(path)
        full_path=self._to_full_path(path)
        if self._config.enabled:
            cache=self._get_cache()
            if cache.is_loaded:
                content=cache.get_file_content(rel_path)
                if content is not None:
                    if max_lines:
                        lines=content.split("\n")
                        content="\n".join(lines[:max_lines])
                    if self._config.track_access_stats:
                        self._get_metadata_store().record_access(full_path)
                    return {"content":content,"from_cache":True,"path":full_path,"success":True}
        return await self._read_file_direct(full_path,encoding,max_lines)
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
            if self._config.enabled:
                rel_path=self._to_rel_path(path)
                cache=self._get_cache()
                cache.put_file(rel_path,content)
            return {"content":content,"from_cache":False,"path":path,"success":True}
        except Exception as e:
            return {"content":"","from_cache":False,"path":path,"success":False,"error":str(e)}
    async def write_file(self,path:str,content:str,encoding:str="utf-8",agent_id:str=None)->Dict[str,Any]:
        import asyncio
        rel_path=self._to_rel_path(path)
        full_path=self._to_full_path(path)
        try:
            parent=os.path.dirname(full_path)
            if parent and not os.path.exists(parent):
                os.makedirs(parent,exist_ok=True)
            def write_sync():
                with open(full_path,"w",encoding=encoding) as f:
                    f.write(content)
            await asyncio.to_thread(write_sync)
            if self._config.enabled:
                cache=self._get_cache()
                cache.put_file(rel_path,content)
                metadata=self._build_metadata(full_path,content,agent_id)
                self._get_metadata_store().upsert(metadata)
            return {"success":True,"path":full_path,"size":len(content.encode(encoding))}
        except Exception as e:
            return {"success":False,"path":full_path,"error":str(e)}
    async def edit_file(self,path:str,old_string:str,new_string:str,encoding:str="utf-8",replace_all:bool=False,agent_id:str=None)->Dict[str,Any]:
        import asyncio
        rel_path=self._to_rel_path(path)
        full_path=self._to_full_path(path)
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
                cache=self._get_cache()
                cache.put_file(rel_path,result["content"])
                metadata=self._build_metadata(full_path,result["content"],agent_id)
                self._get_metadata_store().upsert(metadata)
            return {"success":True,"path":full_path,"replacements":result["count"]}
        except Exception as e:
            return {"success":False,"path":full_path,"error":str(e)}
    async def list_directory(self,path:str=".",pattern:str="*",recursive:bool=False,max_items:int=100)->Dict[str,Any]:
        rel_path=self._to_rel_path(path)
        full_path=self._to_full_path(path)
        if self._config.enabled:
            cache=self._get_cache()
            if cache.is_loaded:
                items=cache.list_dir(rel_path)
                if pattern!="*":
                    import fnmatch
                    items=[i for i in items if fnmatch.fnmatch(i["name"],pattern)]
                items=items[:max_items]
                return {"items":items,"path":full_path,"count":len(items),"from_cache":True}
        return await self._list_dir_direct(full_path,pattern,recursive,max_items)
    async def _list_dir_direct(self,path:str,pattern:str,recursive:bool,max_items:int)->Dict[str,Any]:
        import asyncio
        import fnmatch
        try:
            def list_sync():
                items=[]
                if recursive:
                    for root,dirs,files in os.walk(path):
                        for name in files+dirs:
                            if len(items)>=max_items:
                                return items
                            if fnmatch.fnmatch(name,pattern):
                                item_path=os.path.join(root,name)
                                items.append(self._get_item_info(item_path,path))
                else:
                    for name in os.listdir(path):
                        if len(items)>=max_items:
                            break
                        if fnmatch.fnmatch(name,pattern):
                            item_path=os.path.join(path,name)
                            items.append(self._get_item_info(item_path,path))
                return items
            items=await asyncio.to_thread(list_sync)
            return {"items":items,"path":path,"count":len(items),"from_cache":False}
        except Exception as e:
            return {"items":[],"path":path,"count":0,"error":str(e)}
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
    def search_files(self,pattern:str,max_results:int=100)->List[str]:
        if self._config.enabled:
            cache=self._get_cache()
            if cache.is_loaded:
                results=cache.search_files(pattern)
                return results[:max_results]
        return []
    def search_content(self,pattern:str,file_pattern:str="*",case_sensitive:bool=True,max_results:int=100,context_lines:int=2)->List[Dict[str,Any]]:
        if self._config.enabled:
            cache=self._get_cache()
            if cache.is_loaded:
                return cache.search_content(pattern,file_pattern,case_sensitive,max_results,context_lines)
        return []
    def get_tree(self,rel_path:str="",max_depth:int=3)->List[Dict[str,Any]]:
        if self._config.enabled:
            cache=self._get_cache()
            if cache.is_loaded:
                return cache.get_tree(rel_path,max_depth)
        return []
    def get_all_files(self)->Dict[str,Any]:
        if self._config.enabled:
            cache=self._get_cache()
            if cache.is_loaded:
                return {k:{"size":v.size,"mtime":v.mtime,"is_binary":v.is_binary} for k,v in cache.get_all_files().items()}
        return {}
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
    def get_metadata(self,path:str)->Optional[Dict[str,Any]]:
        full_path=self._to_full_path(path)
        return self._get_metadata_store().get(full_path)
    def stop(self)->None:
        global _project_watchers
        if self._project_id in _project_watchers:
            _project_watchers[self._project_id].stop()
            del _project_watchers[self._project_id]
    def get_cache_stats(self)->Dict[str,Any]:
        stats={"enabled":self._config.enabled}
        if self._config.enabled:
            cache=self._get_cache()
            stats["cache"]=cache.get_stats()
            watcher=self._get_watcher() if self._project_id in _project_watchers else None
            if watcher:
                stats["watcher"]={"watching":watcher.is_watching,"path":watcher.watch_path}
        return stats
    @classmethod
    def clear_project(cls,project_id:str)->None:
        global _project_caches,_project_watchers,_project_metadata_stores
        if project_id in _project_watchers:
            _project_watchers[project_id].stop()
            del _project_watchers[project_id]
        if project_id in _project_caches:
            _project_caches[project_id].clear()
            del _project_caches[project_id]
        if project_id in _project_metadata_stores:
            del _project_metadata_stores[project_id]
def get_file_manager(project_id:str,working_dir:str)->FileManager:
    return FileManager(project_id,working_dir)
