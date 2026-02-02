from typing import Any,Dict,List,Optional,Set
from dataclasses import dataclass,field
from datetime import datetime
import threading
import os
import re
import fnmatch
from .config import FileCacheConfig
@dataclass
class FileEntry:
    path:str
    content:Optional[str]=None
    size:int=0
    mtime:float=0
    is_binary:bool=False
    created_at:datetime=field(default_factory=datetime.now)
    last_accessed_at:datetime=field(default_factory=datetime.now)
    access_count:int=0
    def touch(self)->None:
        self.last_accessed_at=datetime.now()
        self.access_count+=1
@dataclass
class DirEntry:
    path:str
    children:List[str]=field(default_factory=list)
    mtime:float=0
class ProjectFileCache:
    def __init__(self,config:FileCacheConfig,project_id:str,working_dir:str):
        self._config=config
        self._project_id=project_id
        self._working_dir=os.path.normpath(working_dir)
        self._files:Dict[str,FileEntry]={}
        self._dirs:Dict[str,DirEntry]={}
        self._lock=threading.RLock()
        self._current_size_bytes=0
        self._hits=0
        self._misses=0
        self._loaded=False
    @property
    def is_loaded(self)->bool:
        return self._loaded
    def _is_binary_content(self,data:bytes,sample_size:int=8192)->bool:
        if data.startswith((
            b'\xef\xbb\xbf',
            b'\xff\xfe\x00\x00',
            b'\x00\x00\xfe\xff',
            b'\xff\xfe',
            b'\xfe\xff',
        )):
            return False
        sample=data[:sample_size]
        return b'\x00' in sample
    def load_all(self)->Dict[str,Any]:
        with self._lock:
            self._files.clear()
            self._dirs.clear()
            self._current_size_bytes=0
            stats={"files":0,"dirs":0,"binary":0,"skipped":0,"total_size":0}
            ignore_dirs=self._config.ignore_dirs
            max_file_size=self._config.max_file_size_bytes
            for root,dirs,files in os.walk(self._working_dir):
                dirs[:]=[d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
                rel_root=os.path.relpath(root,self._working_dir)
                if rel_root==".":
                    rel_root=""
                children=[]
                for d in dirs:
                    child_path=os.path.join(rel_root,d) if rel_root else d
                    children.append(child_path)
                for f in files:
                    child_path=os.path.join(rel_root,f) if rel_root else f
                    children.append(child_path)
                try:
                    dir_stat=os.stat(root)
                    self._dirs[rel_root]=DirEntry(path=rel_root,children=children,mtime=dir_stat.st_mtime)
                    stats["dirs"]+=1
                except OSError:
                    pass
                for filename in files:
                    filepath=os.path.join(root,filename)
                    rel_path=os.path.join(rel_root,filename) if rel_root else filename
                    try:
                        file_stat=os.stat(filepath)
                        entry=FileEntry(
                            path=rel_path,
                            size=file_stat.st_size,
                            mtime=file_stat.st_mtime,
                        )
                        if file_stat.st_size>max_file_size:
                            entry.is_binary=True
                            stats["skipped"]+=1
                        else:
                            with open(filepath,"rb") as f:
                                data=f.read()
                            if self._is_binary_content(data):
                                entry.is_binary=True
                                stats["binary"]+=1
                            else:
                                entry.content=data.decode("utf-8",errors="replace")
                                entry.is_binary=False
                                self._current_size_bytes+=len(data)
                        self._files[rel_path]=entry
                        stats["files"]+=1
                        stats["total_size"]+=file_stat.st_size
                    except OSError:
                        pass
            self._loaded=True
            return stats
    def get_file(self,rel_path:str)->Optional[FileEntry]:
        with self._lock:
            entry=self._files.get(rel_path)
            if entry:
                entry.touch()
                self._hits+=1
            else:
                self._misses+=1
            return entry
    def get_file_content(self,rel_path:str)->Optional[str]:
        entry=self.get_file(rel_path)
        if entry and not entry.is_binary:
            return entry.content
        return None
    def put_file(self,rel_path:str,content:str,mtime:float=None)->None:
        with self._lock:
            if rel_path in self._files:
                old_entry=self._files[rel_path]
                if old_entry.content:
                    self._current_size_bytes-=len(old_entry.content.encode("utf-8"))
            entry=FileEntry(
                path=rel_path,
                content=content,
                size=len(content.encode("utf-8")),
                mtime=mtime or datetime.now().timestamp(),
                is_binary=False,
            )
            self._files[rel_path]=entry
            self._current_size_bytes+=entry.size
            dir_path=os.path.dirname(rel_path)
            self._update_dir_children(dir_path,rel_path,add=True)
    def remove_file(self,rel_path:str)->None:
        with self._lock:
            if rel_path in self._files:
                entry=self._files.pop(rel_path)
                if entry.content:
                    self._current_size_bytes-=len(entry.content.encode("utf-8"))
                dir_path=os.path.dirname(rel_path)
                self._update_dir_children(dir_path,rel_path,add=False)
    def update_file_from_disk(self,rel_path:str)->bool:
        full_path=os.path.join(self._working_dir,rel_path)
        if not os.path.exists(full_path):
            self.remove_file(rel_path)
            return False
        try:
            file_stat=os.stat(full_path)
            ext=os.path.splitext(rel_path)[1].lower()
            is_binary=ext in self._config.binary_extensions
            with self._lock:
                if rel_path in self._files:
                    old_entry=self._files[rel_path]
                    if old_entry.content:
                        self._current_size_bytes-=len(old_entry.content.encode("utf-8"))
                entry=FileEntry(
                    path=rel_path,
                    size=file_stat.st_size,
                    mtime=file_stat.st_mtime,
                    is_binary=is_binary,
                )
                if not is_binary and file_stat.st_size<=self._config.max_file_size_bytes:
                    try:
                        with open(full_path,"r",encoding="utf-8",errors="replace") as f:
                            entry.content=f.read()
                        self._current_size_bytes+=len(entry.content.encode("utf-8"))
                    except Exception:
                        entry.is_binary=True
                self._files[rel_path]=entry
                dir_path=os.path.dirname(rel_path)
                self._update_dir_children(dir_path,rel_path,add=True)
            return True
        except OSError:
            return False
    def get_dir(self,rel_path:str)->Optional[DirEntry]:
        with self._lock:
            return self._dirs.get(rel_path)
    def add_dir(self,rel_path:str)->None:
        with self._lock:
            if rel_path not in self._dirs:
                full_path=os.path.join(self._working_dir,rel_path)
                try:
                    dir_stat=os.stat(full_path)
                    self._dirs[rel_path]=DirEntry(path=rel_path,children=[],mtime=dir_stat.st_mtime)
                except OSError:
                    self._dirs[rel_path]=DirEntry(path=rel_path,children=[],mtime=datetime.now().timestamp())
                parent_path=os.path.dirname(rel_path)
                if parent_path and parent_path in self._dirs:
                    if rel_path not in self._dirs[parent_path].children:
                        self._dirs[parent_path].children.append(rel_path)
    def remove_dir(self,rel_path:str)->None:
        with self._lock:
            if rel_path in self._dirs:
                del self._dirs[rel_path]
            parent_path=os.path.dirname(rel_path)
            if parent_path and parent_path in self._dirs:
                children=self._dirs[parent_path].children
                if rel_path in children:
                    children.remove(rel_path)
    def _update_dir_children(self,dir_path:str,child_path:str,add:bool)->None:
        if dir_path=="" or dir_path==".":
            dir_path=""
        if dir_path in self._dirs:
            children=self._dirs[dir_path].children
            if add and child_path not in children:
                children.append(child_path)
            elif not add and child_path in children:
                children.remove(child_path)
    def list_dir(self,rel_path:str)->List[Dict[str,Any]]:
        with self._lock:
            if rel_path=="" or rel_path==".":
                rel_path=""
            dir_entry=self._dirs.get(rel_path)
            if not dir_entry:
                return []
            items=[]
            for child in dir_entry.children:
                child_name=os.path.basename(child)
                if child in self._dirs:
                    items.append({"name":child_name,"path":child,"type":"directory","size":0,"modified":self._dirs[child].mtime})
                elif child in self._files:
                    f=self._files[child]
                    items.append({"name":child_name,"path":child,"type":"file","size":f.size,"modified":f.mtime})
            return items
    def search_files(self,pattern:str)->List[str]:
        with self._lock:
            results=[]
            for path in self._files.keys():
                filename=os.path.basename(path)
                if fnmatch.fnmatch(filename,pattern):
                    results.append(path)
            return results
    def search_content(self,pattern:str,file_pattern:str="*",case_sensitive:bool=True,max_results:int=100,context_lines:int=2)->List[Dict[str,Any]]:
        with self._lock:
            flags=0 if case_sensitive else re.IGNORECASE
            try:
                regex=re.compile(pattern,flags)
            except re.error:
                regex=re.compile(re.escape(pattern),flags)
            results=[]
            for path,entry in self._files.items():
                if len(results)>=max_results:
                    break
                if entry.is_binary or entry.content is None:
                    continue
                filename=os.path.basename(path)
                if not fnmatch.fnmatch(filename,file_pattern):
                    continue
                lines=entry.content.split("\n")
                for i,line in enumerate(lines):
                    if len(results)>=max_results:
                        break
                    if regex.search(line):
                        start=max(0,i-context_lines)
                        end=min(len(lines),i+context_lines+1)
                        context=[{"line_no":j+1,"content":lines[j],"is_match":j==i} for j in range(start,end)]
                        results.append({"file":path,"line_no":i+1,"line":line,"context":context})
            return results
    def get_all_files(self)->Dict[str,FileEntry]:
        with self._lock:
            return dict(self._files)
    def get_all_dirs(self)->Dict[str,DirEntry]:
        with self._lock:
            return dict(self._dirs)
    def get_tree(self,rel_path:str="",max_depth:int=3)->List[Dict[str,Any]]:
        with self._lock:
            return self._build_tree(rel_path,max_depth,0)
    def _build_tree(self,rel_path:str,max_depth:int,current_depth:int)->List[Dict[str,Any]]:
        if current_depth>=max_depth:
            return []
        dir_entry=self._dirs.get(rel_path)
        if not dir_entry:
            return []
        items=[]
        dirs_first=sorted(dir_entry.children,key=lambda x:(x not in self._dirs,os.path.basename(x)))
        for child in dirs_first:
            name=os.path.basename(child)
            if child in self._dirs:
                children=self._build_tree(child,max_depth,current_depth+1)
                items.append({"name":name,"type":"directory","children":children})
            elif child in self._files:
                items.append({"name":name,"type":"file"})
            if len(items)>100:
                items.append({"name":"...","type":"truncated"})
                break
        return items
    def clear(self)->None:
        with self._lock:
            self._files.clear()
            self._dirs.clear()
            self._current_size_bytes=0
            self._loaded=False
    def get_stats(self)->Dict[str,Any]:
        with self._lock:
            total_requests=self._hits+self._misses
            hit_rate=self._hits/total_requests if total_requests>0 else 0.0
            binary_count=sum(1 for f in self._files.values() if f.is_binary)
            text_count=len(self._files)-binary_count
            return {
                "loaded":self._loaded,
                "files":len(self._files),
                "text_files":text_count,
                "binary_files":binary_count,
                "dirs":len(self._dirs),
                "size_bytes":self._current_size_bytes,
                "size_mb":round(self._current_size_bytes/(1024*1024),2),
                "max_size_mb":self._config.content_max_size_mb,
                "hits":self._hits,
                "misses":self._misses,
                "hit_rate":round(hit_rate,4),
            }
