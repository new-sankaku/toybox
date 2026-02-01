import os
from typing import List,Optional
from .base import Skill,SkillResult,SkillContext,SkillCategory,SkillParameter
from .file_skills import FileSkillMixin

class FileMetadataSkill(FileSkillMixin,Skill):
 name="file_metadata"
 description="ファイルのメタデータ（用途説明・タグ・サイズ等）を取得・検索・設定します"
 category=SkillCategory.FILE
 parameters=[
  SkillParameter(name="path",type="string",description="対象ファイルパス",required=False),
  SkillParameter(name="action",type="string",description="操作（get/search/most_accessed/recently_modified/add_tag/remove_tag/set_description）",required=False,default="get"),
  SkillParameter(name="file_type",type="string",description="検索用ファイルタイプ（source/config/doc/asset）",required=False),
  SkillParameter(name="language",type="string",description="検索用言語（python/javascript等）",required=False),
  SkillParameter(name="tag",type="string",description="検索/追加/削除するタグ",required=False),
  SkillParameter(name="description",type="string",description="検索キーワードまたは設定する説明文",required=False),
  SkillParameter(name="limit",type="integer",description="検索結果の上限",required=False,default=20),
 ]
 def __init__(self):
  super().__init__()
 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  path=kwargs.get("path")
  action=kwargs.get("action","get")
  file_type=kwargs.get("file_type")
  language=kwargs.get("language")
  tag=kwargs.get("tag")
  description=kwargs.get("description")
  limit=kwargs.get("limit",20)
  try:
   fm=self.get_file_manager()
   if not fm:
    return SkillResult(success=False,error="FileManager not initialized")
   store=fm._get_metadata_store()
   if action=="get":
    if not path:
     return SkillResult(success=False,error="path is required for get action")
    full_path=self._resolve_path(path,context)
    if not self._is_allowed(full_path,context):
     return SkillResult(success=False,error=f"Access denied: {path}")
    metadata=store.get(full_path)
    if metadata is None:
     return SkillResult(success=False,error=f"No metadata found for: {path}")
    return SkillResult(success=True,output=metadata,metadata={"action":"get","path":full_path})
   elif action=="search":
    tags=[tag] if tag else None
    results=store.search(file_type=file_type,language=language,tags=tags,description=description,limit=limit)
    return SkillResult(success=True,output=results,metadata={"action":"search","count":len(results)})
   elif action=="most_accessed":
    results=store.get_most_accessed(limit)
    return SkillResult(success=True,output=results,metadata={"action":"most_accessed","count":len(results)})
   elif action=="recently_modified":
    results=store.get_recently_modified(limit)
    return SkillResult(success=True,output=results,metadata={"action":"recently_modified","count":len(results)})
   elif action=="add_tag":
    if not path or not tag:
     return SkillResult(success=False,error="path and tag are required for add_tag")
    full_path=self._resolve_path(path,context)
    if not self._is_allowed(full_path,context):
     return SkillResult(success=False,error=f"Access denied: {path}")
    success=store.add_tag(full_path,tag)
    return SkillResult(success=success,output=f"Tag '{tag}' added" if success else"Failed to add tag")
   elif action=="remove_tag":
    if not path or not tag:
     return SkillResult(success=False,error="path and tag are required for remove_tag")
    full_path=self._resolve_path(path,context)
    if not self._is_allowed(full_path,context):
     return SkillResult(success=False,error=f"Access denied: {path}")
    success=store.remove_tag(full_path,tag)
    return SkillResult(success=success,output=f"Tag '{tag}' removed" if success else"Failed to remove tag")
   elif action=="set_description":
    if not path or not description:
     return SkillResult(success=False,error="path and description are required for set_description")
    full_path=self._resolve_path(path,context)
    if not self._is_allowed(full_path,context):
     return SkillResult(success=False,error=f"Access denied: {path}")
    success=store.set_description(full_path,description)
    return SkillResult(success=success,output=f"Description set" if success else"Failed to set description")
   else:
    return SkillResult(success=False,error=f"Unknown action: {action}")
  except Exception as e:
   return SkillResult(success=False,error=str(e))
