import os
import re
import asyncio
from typing import Dict,List,Set,Tuple
from .base import Skill,SkillResult,SkillContext,SkillCategory,SkillParameter
from .file_skills import FileSkillMixin


class DependencyGraphSkill(FileSkillMixin,Skill):
 name="dependency_graph"
 description="プロジェクトの依存関係グラフを解析します（import文解析）"
 category=SkillCategory.PROJECT
 parameters=[
  SkillParameter(name="operation",type="string",description="操作: analyze, detect_cycles, impact_analysis"),
  SkillParameter(name="path",type="string",description="解析対象のパスまたはファイル",required=False,default="."),
  SkillParameter(name="language",type="string",description="言語: python, javascript, typescript",required=False,default="python"),
 ]

 PYTHON_IMPORT_RE=re.compile(r'^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))',re.MULTILINE)
 JS_IMPORT_RE=re.compile(r'''(?:import\s+.*?\s+from\s+['"](.*?)['"]|require\s*\(\s*['"](.*?)['"]\s*\))''',re.MULTILINE)

 def __init__(self):
  super().__init__()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  operation=kwargs.get("operation","analyze")
  path=kwargs.get("path",".")
  language=kwargs.get("language","python")
  full_path=self._resolve_path(path,context)
  if not self._is_allowed(full_path,context):
   return SkillResult(success=False,error=f"Access denied: {path}")
  if operation=="analyze":
   return await asyncio.to_thread(self._analyze,full_path,language)
  elif operation=="detect_cycles":
   return await asyncio.to_thread(self._detect_cycles,full_path,language)
  elif operation=="impact_analysis":
   return await asyncio.to_thread(self._impact_analysis,full_path,language)
  else:
   return SkillResult(success=False,error=f"Unknown operation: {operation}. Use: analyze, detect_cycles, impact_analysis")

 def _get_extensions(self,language:str)->List[str]:
  ext_map={
   "python":[".py"],
   "javascript":[".js",".jsx",".mjs"],
   "typescript":[".ts",".tsx"],
  }
  return ext_map.get(language,[".py"])

 def _scan_files(self,base_path:str,extensions:List[str])->List[str]:
  files=[]
  if os.path.isfile(base_path):
   return [base_path]
  for root,dirs,filenames in os.walk(base_path):
   dirs[:]=[d for d in dirs if d not in ("node_modules",".git","__pycache__",".venv","venv")]
   for fname in filenames:
    if any(fname.endswith(ext) for ext in extensions):
     files.append(os.path.join(root,fname))
  return files

 def _extract_imports(self,filepath:str,language:str)->List[str]:
  try:
   with open(filepath,"r",encoding="utf-8",errors="replace") as f:
    content=f.read()
  except Exception:
   return []
  imports=[]
  if language=="python":
   for match in self.PYTHON_IMPORT_RE.finditer(content):
    module=match.group(1) or match.group(2)
    if module:
     imports.append(module)
  else:
   for match in self.JS_IMPORT_RE.finditer(content):
    module=match.group(1) or match.group(2)
    if module and not module.startswith("."):
     continue
    if module:
     imports.append(module)
  return imports

 def _build_graph(self,base_path:str,language:str)->Tuple[List[Dict],List[Dict]]:
  extensions=self._get_extensions(language)
  files=self._scan_files(base_path,extensions)
  nodes=[]
  edges=[]
  file_set=set()
  for fp in files:
   rel=os.path.relpath(fp,base_path)
   file_set.add(rel)
   nodes.append({"id":rel,"path":rel,"size":os.path.getsize(fp)})
  for fp in files:
   rel=os.path.relpath(fp,base_path)
   imports=self._extract_imports(fp,language)
   for imp in imports:
    target=self._resolve_import(imp,rel,language,file_set)
    if target:
     edges.append({"source":rel,"target":target,"type":"import"})
  return nodes,edges

 def _resolve_import(self,imp:str,source:str,language:str,file_set:Set[str])->str:
  if language=="python":
   path=imp.replace(".",os.sep)
   candidates=[path+".py",os.path.join(path,"__init__.py")]
   for c in candidates:
    c_normalized=c.replace(os.sep,"/")
    for f in file_set:
     if f.replace(os.sep,"/")==c_normalized or f.replace(os.sep,"/").endswith("/"+c_normalized):
      return f
  else:
   source_dir=os.path.dirname(source)
   resolved=os.path.normpath(os.path.join(source_dir,imp))
   resolved=resolved.replace(os.sep,"/")
   for ext in self._get_extensions(language):
    candidate=resolved+ext
    for f in file_set:
     if f.replace(os.sep,"/")==candidate:
      return f
   for f in file_set:
    if f.replace(os.sep,"/").startswith(resolved+"/") and os.path.basename(f).startswith("index"):
     return f
  return""

 def _analyze(self,base_path:str,language:str)->SkillResult:
  nodes,edges=self._build_graph(base_path,language)
  return SkillResult(success=True,output={"nodes":nodes,"edges":edges},metadata={"nodeCount":len(nodes),"edgeCount":len(edges)})

 def _detect_cycles(self,base_path:str,language:str)->SkillResult:
  nodes,edges=self._build_graph(base_path,language)
  adjacency:Dict[str,List[str]]={}
  for edge in edges:
   src=edge["source"]
   if src not in adjacency:
    adjacency[src]=[]
   adjacency[src].append(edge["target"])
  cycles=[]
  visited:Set[str]=set()
  path:List[str]=[]
  on_stack:Set[str]=set()
  def dfs(node:str):
   visited.add(node)
   path.append(node)
   on_stack.add(node)
   for neighbor in adjacency.get(node,[]):
    if neighbor not in visited:
     dfs(neighbor)
    elif neighbor in on_stack:
     cycle_start=path.index(neighbor)
     cycle=path[cycle_start:]+[neighbor]
     cycles.append(cycle)
   path.pop()
   on_stack.discard(node)
  for node_dict in nodes:
   nid=node_dict["id"]
   if nid not in visited:
    dfs(nid)
  return SkillResult(success=True,output={"cycles":cycles,"hasCycles":len(cycles)>0},metadata={"cycleCount":len(cycles)})

 def _impact_analysis(self,base_path:str,language:str)->SkillResult:
  nodes,edges=self._build_graph(base_path,language)
  reverse_adj:Dict[str,List[str]]={}
  for edge in edges:
   tgt=edge["target"]
   if tgt not in reverse_adj:
    reverse_adj[tgt]=[]
   reverse_adj[tgt].append(edge["source"])
  target_file=base_path
  if os.path.isfile(base_path):
   target_file=os.path.basename(base_path)
  impacted:Set[str]=set()
  queue=[target_file]
  while queue:
   current=queue.pop(0)
   for dep in reverse_adj.get(current,[]):
    if dep not in impacted:
     impacted.add(dep)
     queue.append(dep)
  return SkillResult(success=True,output={"file":target_file,"impactedFiles":sorted(impacted),"impactCount":len(impacted)},metadata={"impactCount":len(impacted)})
