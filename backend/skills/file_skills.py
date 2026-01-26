import os
import asyncio
from pathlib import Path
from typing import List,Optional
from .base import Skill,SkillResult,SkillContext,SkillCategory,SkillParameter


class FileReadSkill(Skill):
 name="file_read"
 description="ファイルの内容を読み取ります"
 category=SkillCategory.FILE
 parameters=[
  SkillParameter(name="path",type="string",description="読み取るファイルのパス"),
  SkillParameter(name="encoding",type="string",description="エンコーディング",required=False,default="utf-8"),
  SkillParameter(name="max_lines",type="integer",description="最大行数",required=False,default=1000),
 ]

 def __init__(self):
  super().__init__()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  path=kwargs.get("path","")
  encoding=kwargs.get("encoding","utf-8")
  max_lines=kwargs.get("max_lines",1000)
  if not path:
   return SkillResult(success=False,error="path is required")
  full_path=self._resolve_path(path,context)
  if not self._is_allowed(full_path,context):
   return SkillResult(success=False,error=f"Access denied: {path}")
  try:
   if not os.path.exists(full_path):
    return SkillResult(success=False,error=f"File not found: {path}")
   if not os.path.isfile(full_path):
    return SkillResult(success=False,error=f"Not a file: {path}")
   file_size=os.path.getsize(full_path)
   if file_size>context.max_output_size:
    return SkillResult(success=False,error=f"File too large: {file_size} bytes")
   content=await asyncio.to_thread(self._read_file,full_path,encoding,max_lines)
   return SkillResult(
    success=True,
    output=content,
    metadata={"path":full_path,"size":file_size,"lines":len(content.splitlines())}
   )
  except Exception as e:
   return SkillResult(success=False,error=str(e))

 def _read_file(self,path:str,encoding:str,max_lines:int)->str:
  with open(path,"r",encoding=encoding) as f:
   lines=[]
   for i,line in enumerate(f):
    if i>=max_lines:
     lines.append(f"\n... (truncated at {max_lines} lines)")
     break
    lines.append(line)
   return"".join(lines)

 def _resolve_path(self,path:str,context:SkillContext)->str:
  if os.path.isabs(path):
   return os.path.normpath(path)
  return os.path.normpath(os.path.join(context.working_dir,path))

 def _is_allowed(self,path:str,context:SkillContext)->bool:
  if not context.sandbox_enabled:
   return True
  norm_path=os.path.normpath(path)
  for denied in context.denied_paths:
   if norm_path.startswith(os.path.normpath(denied)):
    return False
  if not context.allowed_paths:
   return norm_path.startswith(os.path.normpath(context.working_dir))
  for allowed in context.allowed_paths:
   if norm_path.startswith(os.path.normpath(allowed)):
    return True
  return False


class FileWriteSkill(Skill):
 name="file_write"
 description="ファイルに内容を書き込みます"
 category=SkillCategory.FILE
 parameters=[
  SkillParameter(name="path",type="string",description="書き込むファイルのパス"),
  SkillParameter(name="content",type="string",description="書き込む内容"),
  SkillParameter(name="encoding",type="string",description="エンコーディング",required=False,default="utf-8"),
  SkillParameter(name="create_dirs",type="boolean",description="親ディレクトリを作成するか",required=False,default=True),
 ]

 def __init__(self):
  super().__init__()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  path=kwargs.get("path","")
  content=kwargs.get("content","")
  encoding=kwargs.get("encoding","utf-8")
  create_dirs=kwargs.get("create_dirs",True)
  if not path:
   return SkillResult(success=False,error="path is required")
  full_path=self._resolve_path(path,context)
  if not self._is_allowed(full_path,context):
   return SkillResult(success=False,error=f"Access denied: {path}")
  try:
   if create_dirs:
    parent=os.path.dirname(full_path)
    if parent and not os.path.exists(parent):
     os.makedirs(parent,exist_ok=True)
   await asyncio.to_thread(self._write_file,full_path,content,encoding)
   return SkillResult(
    success=True,
    output=f"Written {len(content)} bytes to {path}",
    metadata={"path":full_path,"size":len(content.encode(encoding))}
   )
  except Exception as e:
   return SkillResult(success=False,error=str(e))

 def _write_file(self,path:str,content:str,encoding:str)->None:
  with open(path,"w",encoding=encoding) as f:
   f.write(content)

 def _resolve_path(self,path:str,context:SkillContext)->str:
  if os.path.isabs(path):
   return os.path.normpath(path)
  return os.path.normpath(os.path.join(context.working_dir,path))

 def _is_allowed(self,path:str,context:SkillContext)->bool:
  if not context.sandbox_enabled:
   return True
  norm_path=os.path.normpath(path)
  for denied in context.denied_paths:
   if norm_path.startswith(os.path.normpath(denied)):
    return False
  if not context.allowed_paths:
   return norm_path.startswith(os.path.normpath(context.working_dir))
  for allowed in context.allowed_paths:
   if norm_path.startswith(os.path.normpath(allowed)):
    return True
  return False


class FileListSkill(Skill):
 name="file_list"
 description="ディレクトリの内容を一覧表示します"
 category=SkillCategory.FILE
 parameters=[
  SkillParameter(name="path",type="string",description="一覧表示するディレクトリのパス",required=False,default="."),
  SkillParameter(name="pattern",type="string",description="フィルタパターン（glob形式）",required=False,default="*"),
  SkillParameter(name="recursive",type="boolean",description="再帰的に検索するか",required=False,default=False),
  SkillParameter(name="max_items",type="integer",description="最大表示件数",required=False,default=100),
 ]

 def __init__(self):
  super().__init__()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  path=kwargs.get("path",".")
  pattern=kwargs.get("pattern","*")
  recursive=kwargs.get("recursive",False)
  max_items=kwargs.get("max_items",100)
  full_path=self._resolve_path(path,context)
  if not self._is_allowed(full_path,context):
   return SkillResult(success=False,error=f"Access denied: {path}")
  try:
   if not os.path.exists(full_path):
    return SkillResult(success=False,error=f"Directory not found: {path}")
   if not os.path.isdir(full_path):
    return SkillResult(success=False,error=f"Not a directory: {path}")
   items=await asyncio.to_thread(self._list_dir,full_path,pattern,recursive,max_items)
   return SkillResult(
    success=True,
    output=items,
    metadata={"path":full_path,"count":len(items),"truncated":len(items)>=max_items}
   )
  except Exception as e:
   return SkillResult(success=False,error=str(e))

 def _list_dir(self,path:str,pattern:str,recursive:bool,max_items:int)->List[dict]:
  import fnmatch
  items=[]
  if recursive:
   for root,dirs,files in os.walk(path):
    for name in files+dirs:
     if len(items)>=max_items:
      return items
     if fnmatch.fnmatch(name,pattern):
      full=os.path.join(root,name)
      items.append(self._get_item_info(full,path))
  else:
   for name in os.listdir(path):
    if len(items)>=max_items:
     break
    if fnmatch.fnmatch(name,pattern):
     full=os.path.join(path,name)
     items.append(self._get_item_info(full,path))
  return items

 def _get_item_info(self,full_path:str,base_path:str)->dict:
  stat=os.stat(full_path)
  rel_path=os.path.relpath(full_path,base_path)
  return {
   "name":os.path.basename(full_path),
   "path":rel_path,
   "type":"directory" if os.path.isdir(full_path) else"file",
   "size":stat.st_size if os.path.isfile(full_path) else 0,
   "modified":stat.st_mtime,
  }

 def _resolve_path(self,path:str,context:SkillContext)->str:
  if os.path.isabs(path):
   return os.path.normpath(path)
  return os.path.normpath(os.path.join(context.working_dir,path))

 def _is_allowed(self,path:str,context:SkillContext)->bool:
  if not context.sandbox_enabled:
   return True
  norm_path=os.path.normpath(path)
  for denied in context.denied_paths:
   if norm_path.startswith(os.path.normpath(denied)):
    return False
  if not context.allowed_paths:
   return norm_path.startswith(os.path.normpath(context.working_dir))
  for allowed in context.allowed_paths:
   if norm_path.startswith(os.path.normpath(allowed)):
    return True
  return False
