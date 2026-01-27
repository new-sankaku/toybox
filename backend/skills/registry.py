from typing import Dict,List,Optional,Type
from .base import Skill,SkillCategory,SkillContext,SkillResult

_registry:Optional["SkillRegistry"]=None


class SkillRegistry:
 def __init__(self):
  self._skills:Dict[str,Skill]={}
  self._by_category:Dict[SkillCategory,List[str]]={}

 def register(self,skill:Skill)->None:
  self._skills[skill.name]=skill
  category=skill.category
  if category not in self._by_category:
   self._by_category[category]=[]
  if skill.name not in self._by_category[category]:
   self._by_category[category].append(skill.name)

 def get(self,name:str)->Optional[Skill]:
  return self._skills.get(name)

 def get_by_category(self,category:SkillCategory)->List[Skill]:
  names=self._by_category.get(category,[])
  return [self._skills[n] for n in names if n in self._skills]

 def list_all(self)->List[Skill]:
  return list(self._skills.values())

 def list_names(self)->List[str]:
  return list(self._skills.keys())

 def get_schemas(self)->List[Dict]:
  return [s.get_schema() for s in self._skills.values()]

 async def execute(self,skill_name:str,context:SkillContext,**kwargs)->SkillResult:
  skill=self.get(skill_name)
  if not skill:
   return SkillResult(success=False,error=f"Skill not found: {skill_name}")
  validation_error=skill.validate_params(**kwargs)
  if validation_error:
   return SkillResult(success=False,error=validation_error)
  return await skill.execute(context,**kwargs)


def get_skill_registry()->SkillRegistry:
 global _registry
 if _registry is None:
  _registry=SkillRegistry()
  _register_default_skills(_registry)
 return _registry


def _register_default_skills(registry:SkillRegistry)->None:
 from .file_skills import FileReadSkill,FileWriteSkill,FileEditSkill,FileListSkill
 from .bash_skill import BashExecuteSkill
 from .python_skill import PythonExecuteSkill
 from .project_skill import ProjectAnalyzeSkill
 from .build_skills import CodeBuildSkill,CodeTestSkill,CodeLintSkill
 from .asset_skills import ImageGenerateSkill,BgmGenerateSkill,SfxGenerateSkill,VoiceGenerateSkill
 from .search_skills import CodeSearchSkill,FileSearchSkill
 from .web_skills import WebFetchSkill
 registry.register(FileReadSkill())
 registry.register(FileWriteSkill())
 registry.register(FileEditSkill())
 registry.register(FileListSkill())
 registry.register(BashExecuteSkill())
 registry.register(PythonExecuteSkill())
 registry.register(ProjectAnalyzeSkill())
 registry.register(CodeBuildSkill())
 registry.register(CodeTestSkill())
 registry.register(CodeLintSkill())
 registry.register(ImageGenerateSkill())
 registry.register(BgmGenerateSkill())
 registry.register(SfxGenerateSkill())
 registry.register(VoiceGenerateSkill())
 registry.register(CodeSearchSkill())
 registry.register(FileSearchSkill())
 registry.register(WebFetchSkill())
