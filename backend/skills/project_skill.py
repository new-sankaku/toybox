import asyncio
import os
import json
from pathlib import Path
from typing import List,Dict,Any,Optional
from .base import Skill,SkillResult,SkillContext,SkillCategory,SkillParameter


class ProjectAnalyzeSkill(Skill):
 name="project_analyze"
 description="プロジェクトの構造を解析し、概要を返します"
 category=SkillCategory.PROJECT
 parameters=[
  SkillParameter(name="path",type="string",description="解析するプロジェクトのパス",required=False,default="."),
  SkillParameter(name="depth",type="integer",description="解析する深さ",required=False,default=3),
  SkillParameter(name="include_content",type="boolean",description="主要ファイルの内容を含めるか",required=False,default=False),
 ]

 IMPORTANT_FILES=[
  "package.json",
  "requirements.txt",
  "setup.py",
  "pyproject.toml",
  "Cargo.toml",
  "go.mod",
  "pom.xml",
  "build.gradle",
  "Makefile",
  "Dockerfile",
  "docker-compose.yml",
  "README.md",
  ".gitignore",
 ]

 IGNORE_DIRS=[
  "node_modules",
  "__pycache__",
  ".git",
  ".venv",
  "venv",
  "dist",
  "build",
  ".next",
  ".nuxt",
  "target",
  "vendor",
 ]

 LANGUAGE_EXTENSIONS={
  ".py":"Python",
  ".js":"JavaScript",
  ".ts":"TypeScript",
  ".tsx":"TypeScript React",
  ".jsx":"JavaScript React",
  ".go":"Go",
  ".rs":"Rust",
  ".java":"Java",
  ".kt":"Kotlin",
  ".swift":"Swift",
  ".cs":"C#",
  ".cpp":"C++",
  ".c":"C",
  ".rb":"Ruby",
  ".php":"PHP",
  ".lua":"Lua",
  ".gdscript":"GDScript",
 }

 def __init__(self):
  super().__init__()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  path=kwargs.get("path",".")
  depth=kwargs.get("depth",3)
  include_content=kwargs.get("include_content",False)
  if path==".":
   full_path=context.working_dir
  elif os.path.isabs(path):
   full_path=path
  else:
   full_path=os.path.join(context.working_dir,path)
  full_path=os.path.normpath(full_path)
  if not os.path.exists(full_path):
   return SkillResult(success=False,error=f"Path not found: {path}")
  if not os.path.isdir(full_path):
   return SkillResult(success=False,error=f"Not a directory: {path}")
  try:
   analysis=await asyncio.to_thread(self._analyze_project,full_path,depth,include_content)
   return SkillResult(success=True,output=analysis,metadata={"path":full_path})
  except Exception as e:
   return SkillResult(success=False,error=str(e))

 def _analyze_project(self,path:str,depth:int,include_content:bool)->Dict[str,Any]:
  result={
   "project_root":path,
   "project_name":os.path.basename(path),
   "structure":self._build_tree(path,depth),
   "languages":{},
   "file_counts":{},
   "important_files":{},
   "project_type":None,
   "total_files":0,
   "total_dirs":0,
  }
  lang_counts:Dict[str,int]={}
  ext_counts:Dict[str,int]={}
  for root,dirs,files in os.walk(path):
   dirs[:]=[d for d in dirs if d not in self.IGNORE_DIRS]
   result["total_dirs"]+=len(dirs)
   result["total_files"]+=len(files)
   for f in files:
    ext=os.path.splitext(f)[1].lower()
    ext_counts[ext]=ext_counts.get(ext,0)+1
    if ext in self.LANGUAGE_EXTENSIONS:
     lang=self.LANGUAGE_EXTENSIONS[ext]
     lang_counts[lang]=lang_counts.get(lang,0)+1
    if f in self.IMPORTANT_FILES:
     rel_path=os.path.relpath(os.path.join(root,f),path)
     file_info={"path":rel_path}
     if include_content:
      try:
       with open(os.path.join(root,f),"r",encoding="utf-8",errors="ignore") as fp:
        content=fp.read(5000)
        file_info["content"]=content
      except Exception:
       pass
     result["important_files"][f]=file_info
  result["languages"]=dict(sorted(lang_counts.items(),key=lambda x:-x[1]))
  result["file_counts"]=dict(sorted(ext_counts.items(),key=lambda x:-x[1])[:20])
  result["project_type"]=self._detect_project_type(result["important_files"],result["languages"])
  return result

 def _build_tree(self,path:str,max_depth:int,current_depth:int=0)->List[Dict[str,Any]]:
  if current_depth>=max_depth:
   return []
  items=[]
  try:
   entries=sorted(os.listdir(path))
  except PermissionError:
   return []
  dirs_first=sorted(entries,key=lambda x:(not os.path.isdir(os.path.join(path,x)),x))
  for name in dirs_first:
   if name in self.IGNORE_DIRS or name.startswith("."):
    continue
   full=os.path.join(path,name)
   if os.path.isdir(full):
    children=self._build_tree(full,max_depth,current_depth+1)
    items.append({"name":name,"type":"directory","children":children})
   else:
    items.append({"name":name,"type":"file"})
   if len(items)>50:
    items.append({"name":"...","type":"truncated"})
    break
  return items

 def _detect_project_type(self,important_files:Dict,languages:Dict)->Optional[str]:
  if "package.json" in important_files:
   content=important_files["package.json"].get("content","")
   if "react" in content.lower():
    return"React Application"
   if "vue" in content.lower():
    return"Vue.js Application"
   if "next" in content.lower():
    return"Next.js Application"
   if "electron" in content.lower():
    return"Electron Application"
   return"Node.js Project"
  if "requirements.txt" in important_files or"pyproject.toml" in important_files:
   if "GDScript" in languages:
    return"Godot Game (Python tools)"
   return"Python Project"
  if "Cargo.toml" in important_files:
   return"Rust Project"
  if "go.mod" in important_files:
   return"Go Project"
  if "pom.xml" in important_files or"build.gradle" in important_files:
   return"Java Project"
  if languages:
   primary=max(languages,key=languages.get)
   return f"{primary} Project"
  return"Unknown Project Type"
