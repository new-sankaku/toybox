from typing import Dict,Any,Optional
from middleware.logger import get_logger


def resolve_llm_for_project(project_id:Optional[str],usage_category:str)->Dict[str,str]:
 if project_id:
  try:
   from models.database import session_scope
   from repositories.project_ai_config import ProjectAiConfigRepository
   with session_scope() as session:
    repo=ProjectAiConfigRepository(session)
    config=repo.get(project_id,usage_category)
    if config:
     return {"provider":config.provider_id,"model":config.model_id}
  except Exception as e:
   get_logger().error(f"llm_resolver: project config lookup failed: {e}",exc_info=True)
 return _get_usage_category_default(usage_category)


def _get_usage_category_default(usage_category:str)->Dict[str,str]:
 try:
  from config_loader import get_ai_providers_config
  ai_config=get_ai_providers_config()
  for cat in ai_config.get("usage_categories",[]):
   if cat.get("id")==usage_category:
    default=cat.get("default",{})
    return {"provider":default.get("provider",""),"model":default.get("model","")}
 except Exception as e:
  get_logger().error(f"llm_resolver: usage_category default lookup failed: {e}",exc_info=True)
 return {"provider":"","model":""}


def resolve_with_env_key(provider_id:str)->str:
 import os
 from config_loader import get_provider_env_key
 env_key=get_provider_env_key(provider_id)
 return os.environ.get(env_key,"") if env_key else""
