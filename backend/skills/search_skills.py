import os
import re
import asyncio
import fnmatch
from typing import List,Dict,Any,Optional
from .base import Skill,SkillResult,SkillContext,SkillCategory,SkillParameter
from middleware.logger import get_logger

HARD_MAX_RESULTS=200
MAX_SEARCH_FILE_SIZE=524288


class CodeSearchSkill(Skill):
 name="code_search"
 description="コード内をテキスト検索します（grep的な機能）"
 category=SkillCategory.FILE
 parameters=[
  SkillParameter(name="pattern",type="string",description="検索パターン（正規表現対応）"),
  SkillParameter(name="path",type="string",description="検索対象ディレクトリ",required=False,default="."),
  SkillParameter(name="file_pattern",type="string",description="ファイルパターン（例: *.py, *.ts）",required=False,default="*"),
  SkillParameter(name="case_sensitive",type="boolean",description="大文字小文字を区別",required=False,default=True),
  SkillParameter(name="max_results",type="integer",description="最大結果数",required=False,default=100),
  SkillParameter(name="context_lines",type="integer",description="前後の行数",required=False,default=2),
 ]

 BINARY_EXTENSIONS={".png",".jpg",".jpeg",".gif",".bmp",".ico",".webp",".mp3",".wav",".ogg",".mp4",".avi",".mov",".webm",".zip",".tar",".gz",".7z",".rar",".exe",".dll",".so",".dylib",".pyc",".pyo",".class",".o",".obj",".pdf",".doc",".docx",".xls",".xlsx",".ttf",".otf",".woff",".woff2",".eot"}

 IGNORE_DIRS={"node_modules","__pycache__",".git",".venv","venv","dist","build",".next","target","vendor",".idea",".vscode"}

 def __init__(self):
  super().__init__()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  pattern=kwargs.get("pattern","")
  path=kwargs.get("path",".")
  file_pattern=kwargs.get("file_pattern","*")
  case_sensitive=kwargs.get("case_sensitive",True)
  max_results=kwargs.get("max_results",100)
  context_lines=kwargs.get("context_lines",2)
  if not pattern:
   return SkillResult(success=False,error="pattern is required")
  config_max=context.restrictions.get("max_results",HARD_MAX_RESULTS)
  hard_max=min(config_max,HARD_MAX_RESULTS)
  max_results=min(max_results,hard_max)
  context_lines=min(context_lines,5)
  if path==".":
   full_path=context.working_dir
  elif os.path.isabs(path):
   full_path=path
  else:
   full_path=os.path.join(context.working_dir,path)
  if not os.path.exists(full_path):
   return SkillResult(success=False,error=f"Path not found: {path}")
  try:
   search_result=await asyncio.to_thread(
    self._search,full_path,pattern,file_pattern,case_sensitive,max_results,context_lines
   )
   results=search_result["results"]
   skipped=search_result["skipped_files"]
   truncated=len(results)>=max_results
   metadata={"pattern":pattern,"total_matches":len(results),"truncated":truncated,"max_results_applied":max_results}
   if skipped:
    metadata["skipped_files"]=skipped
    metadata["skipped_reason"]=f"{len(skipped)} file(s) skipped due to size limit ({MAX_SEARCH_FILE_SIZE} bytes)"
   return SkillResult(success=True,output=results,metadata=metadata)
  except re.error as e:
   return SkillResult(success=False,error=f"Invalid regex pattern: {e}")
  except Exception as e:
   return SkillResult(success=False,error=str(e))

 def _search(self,path:str,pattern:str,file_pattern:str,case_sensitive:bool,max_results:int,context_lines:int)->Dict[str,Any]:
  flags=0 if case_sensitive else re.IGNORECASE
  try:
   regex=re.compile(pattern,flags)
  except re.error:
   regex=re.compile(re.escape(pattern),flags)
  results=[]
  skipped_files=[]
  for root,dirs,files in os.walk(path):
   dirs[:]=[d for d in dirs if d not in self.IGNORE_DIRS]
   for filename in files:
    if len(results)>=max_results:
     return {"results":results,"skipped_files":skipped_files}
    if not fnmatch.fnmatch(filename,file_pattern):
     continue
    ext=os.path.splitext(filename)[1].lower()
    if ext in self.BINARY_EXTENSIONS:
     continue
    filepath=os.path.join(root,filename)
    try:
     file_size=os.path.getsize(filepath)
     if file_size>MAX_SEARCH_FILE_SIZE:
      rel_path=os.path.relpath(filepath,path)
      skipped_files.append({"file":rel_path,"size":file_size,"reason":f"exceeds {MAX_SEARCH_FILE_SIZE} bytes"})
      get_logger().debug(f"Skipped large file during search {filepath}: {file_size} bytes > {MAX_SEARCH_FILE_SIZE}")
      continue
     matches=self._search_file(filepath,regex,context_lines,path)
     for match in matches:
      if len(results)>=max_results:
       return {"results":results,"skipped_files":skipped_files}
      results.append(match)
    except Exception as e:
     get_logger().debug(f"Skipped file during search {filepath}: {e}")
     continue
  return {"results":results,"skipped_files":skipped_files}

 def _search_file(self,filepath:str,regex:re.Pattern,context_lines:int,base_path:str)->List[Dict[str,Any]]:
  results=[]
  try:
   with open(filepath,"r",encoding="utf-8",errors="ignore") as f:
    lines=f.readlines()
  except Exception as e:
   get_logger().debug(f"Failed to read file {filepath}: {e}")
   return results
  rel_path=os.path.relpath(filepath,base_path)
  for i,line in enumerate(lines):
   if regex.search(line):
    start=max(0,i-context_lines)
    end=min(len(lines),i+context_lines+1)
    context=[{"line_no":j+1,"content":lines[j].rstrip(),"is_match":j==i} for j in range(start,end)]
    results.append({
     "file":rel_path,
     "line_no":i+1,
     "line":line.rstrip(),
     "context":context,
    })
  return results


class FileSearchSkill(Skill):
 name="file_search"
 description="ファイル名でファイルを検索します"
 category=SkillCategory.FILE
 parameters=[
  SkillParameter(name="pattern",type="string",description="ファイル名パターン（glob形式、例: *.py, test_*.ts）"),
  SkillParameter(name="path",type="string",description="検索対象ディレクトリ",required=False,default="."),
  SkillParameter(name="max_results",type="integer",description="最大結果数",required=False,default=100),
  SkillParameter(name="include_hidden",type="boolean",description="隠しファイルを含める",required=False,default=False),
 ]

 IGNORE_DIRS={"node_modules","__pycache__",".git",".venv","venv","dist","build",".next","target","vendor"}

 def __init__(self):
  super().__init__()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  pattern=kwargs.get("pattern","*")
  path=kwargs.get("path",".")
  max_results=kwargs.get("max_results",100)
  include_hidden=kwargs.get("include_hidden",False)
  config_max=context.restrictions.get("max_results",HARD_MAX_RESULTS)
  hard_max=min(config_max,HARD_MAX_RESULTS)
  max_results=min(max_results,hard_max)
  if path==".":
   full_path=context.working_dir
  elif os.path.isabs(path):
   full_path=path
  else:
   full_path=os.path.join(context.working_dir,path)
  if not os.path.exists(full_path):
   return SkillResult(success=False,error=f"Path not found: {path}")
  try:
   results=await asyncio.to_thread(self._search,full_path,pattern,max_results,include_hidden)
   truncated=len(results)>=max_results
   return SkillResult(
    success=True,
    output=results,
    metadata={"pattern":pattern,"total_found":len(results),"truncated":truncated,"max_results_applied":max_results}
   )
  except Exception as e:
   return SkillResult(success=False,error=str(e))

 def _search(self,path:str,pattern:str,max_results:int,include_hidden:bool)->List[Dict[str,Any]]:
  results=[]
  for root,dirs,files in os.walk(path):
   if not include_hidden:
    dirs[:]=[d for d in dirs if not d.startswith(".") and d not in self.IGNORE_DIRS]
   else:
    dirs[:]=[d for d in dirs if d not in self.IGNORE_DIRS]
   for filename in files:
    if len(results)>=max_results:
     return results
    if not include_hidden and filename.startswith("."):
     continue
    if fnmatch.fnmatch(filename,pattern):
     filepath=os.path.join(root,filename)
     rel_path=os.path.relpath(filepath,path)
     try:
      stat=os.stat(filepath)
      results.append({
       "name":filename,
       "path":rel_path,
       "size":stat.st_size,
       "modified":stat.st_mtime,
      })
     except Exception as e:
      get_logger().debug(f"Failed to stat file {filepath}: {e}")
      results.append({"name":filename,"path":rel_path})
  return results
