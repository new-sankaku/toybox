import os
import asyncio
import platform
from typing import Dict,List,Any,Optional
from dataclasses import dataclass,field
from .base import SkillContext,SkillResult,SkillCategory
from .registry import get_skill_registry
from middleware.logger import get_logger


@dataclass
class SkillExecutionConfig:
 working_dir:str
 allowed_skills:List[str]=field(default_factory=list)
 sandbox_enabled:bool=True
 allowed_paths:List[str]=field(default_factory=list)
 denied_paths:List[str]=field(default_factory=list)
 timeout_seconds:int=120
 max_output_size:int=100000


class SkillExecutor:
 def __init__(self,project_id:str,agent_id:str,config:SkillExecutionConfig):
  self.project_id=project_id
  self.agent_id=agent_id
  self.config=config
  self._registry=get_skill_registry()
  self._execution_history:List[Dict[str,Any]]=[]

 def get_available_skills(self)->List[Dict[str,Any]]:
  all_skills=self._registry.get_schemas()
  if not self.config.allowed_skills:
   return all_skills
  return [s for s in all_skills if s["name"] in self.config.allowed_skills]

 def get_skill_schemas_for_llm(self)->List[Dict[str,Any]]:
  skills=self.get_available_skills()
  tools=[]
  for skill in skills:
   tools.append({
    "name":skill["name"],
    "description":skill["description"],
    "input_schema":skill["parameters"],
   })
  return tools

 async def execute_skill(self,skill_name:str,**kwargs)->SkillResult:
  if self.config.allowed_skills and skill_name not in self.config.allowed_skills:
   return SkillResult(success=False,error=f"Skill not allowed: {skill_name}")
  context=SkillContext(
   project_id=self.project_id,
   agent_id=self.agent_id,
   working_dir=self.config.working_dir,
   allowed_paths=self.config.allowed_paths,
   denied_paths=self.config.denied_paths,
   timeout_seconds=self.config.timeout_seconds,
   max_output_size=self.config.max_output_size,
   sandbox_enabled=self.config.sandbox_enabled,
  )
  result=await self._registry.execute(skill_name,context,**kwargs)
  self._execution_history.append({
   "skill":skill_name,
   "params":kwargs,
   "success":result.success,
   "error":result.error,
  })
  return result

 async def execute_tool_call(self,tool_call:Dict[str,Any])->Dict[str,Any]:
  skill_name=tool_call.get("name","")
  params=tool_call.get("input",{})
  result=await self.execute_skill(skill_name,**params)
  return {
   "tool_use_id":tool_call.get("id",""),
   "type":"tool_result",
   "content":self._format_result(result),
   "is_error":not result.success,
  }

 def _format_result(self,result:SkillResult)->str:
  if not result.success:
   return f"Error: {result.error}"
  output=result.output
  if isinstance(output,dict):
   import json
   return json.dumps(output,ensure_ascii=False,indent=2)
  if isinstance(output,list):
   import json
   return json.dumps(output,ensure_ascii=False,indent=2)
  return str(output)

 def get_execution_history(self)->List[Dict[str,Any]]:
  return self._execution_history.copy()

 def clear_history(self)->None:
  self._execution_history.clear()


def create_skill_executor(
 project_id:str,
 agent_id:str,
 agent_type:str,
 working_dir:str,
 skill_config:Optional[Dict[str,Any]]=None
)->SkillExecutor:
 from config_loader import load_yaml_config
 if skill_config is None:
  try:
   skill_config=load_yaml_config("skills.yaml")
  except Exception as e:
   get_logger().error(f"Failed to load skills.yaml: {e}")
   skill_config={}
 mapping=skill_config.get("agent_skill_mapping",{})
 allowed_skills=mapping.get(agent_type,mapping.get("default",[]))
 sandbox_cfg=skill_config.get("sandbox",{})
 effective_working_dir=_get_project_output_dir(project_id,sandbox_cfg,working_dir)
 denied_paths=_get_denied_paths_for_platform(sandbox_cfg)
 config=SkillExecutionConfig(
  working_dir=effective_working_dir,
  allowed_skills=allowed_skills,
  sandbox_enabled=sandbox_cfg.get("enabled",True),
  allowed_paths=[effective_working_dir],
  denied_paths=denied_paths,
  timeout_seconds=sandbox_cfg.get("timeout_seconds",120),
  max_output_size=sandbox_cfg.get("max_output_size",100000),
 )
 return SkillExecutor(project_id,agent_id,config)


def _get_denied_paths_for_platform(sandbox_cfg:Dict[str,Any])->List[str]:
 is_windows=platform.system().lower()=="windows"
 if is_windows:
  return sandbox_cfg.get("denied_paths_windows",[])
 else:
  return sandbox_cfg.get("denied_paths_linux",[])


def _get_project_output_dir(project_id:str,sandbox_cfg:Dict[str,Any],fallback_dir:str)->str:
 output_base=sandbox_cfg.get("output_base","./output")
 if not os.path.isabs(output_base):
  backend_dir=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
  output_base=os.path.join(backend_dir,output_base)
 project_output_dir=os.path.join(output_base,project_id)
 os.makedirs(project_output_dir,exist_ok=True)
 return project_output_dir
