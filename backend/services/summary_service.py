from typing import Optional,Dict,Any
from config_loader import get_context_policy_settings,get_summary_directive
from providers.registry import get_provider
from providers.base import AIProviderConfig,ChatMessage,MessageRole
from middleware.logger import get_logger


class SummaryService:
 _instance=None

 def __new__(cls):
  if cls._instance is None:
   cls._instance=super().__new__(cls)
   cls._instance._initialized=False
  return cls._instance

 def __init__(self):
  if self._initialized:
   return
  self._initialized=True

 def generate_summary(self,content:str,agent_type:str,fallback_func=None,project_id:Optional[str]=None)->str:
  if not content:
   return""
  settings=get_context_policy_settings()
  llm_cfg=settings.get("llm_summary",{})
  if not llm_cfg.get("enabled",False):
   if fallback_func:
    return fallback_func(content)
   return content[:settings.get("summary_max_length",10000)]
  min_len=llm_cfg.get("min_content_length",500)
  if len(content)<min_len:
   return content
  try:
   return self._call_llm_summary(content,agent_type,llm_cfg,project_id)
  except Exception as e:
   get_logger().error(f"SummaryService LLM summary failed, using fallback: {e}",exc_info=True)
   if fallback_func:
    return fallback_func(content)
   return content[:settings.get("summary_max_length",10000)]

 def _call_llm_summary(self,content:str,agent_type:str,llm_cfg:dict,project_id:Optional[str]=None)->str:
  from services.llm_resolver import resolve_llm_for_project,resolve_with_env_key

  usage_category=llm_cfg.get("usage_category","llm_low")
  resolved=resolve_llm_for_project(project_id,usage_category)
  provider_id=resolved["provider"]
  model=resolved["model"]

  if not provider_id or not model:
   raise RuntimeError(f"Summary LLM not resolved: usage_category={usage_category} project_id={project_id}")

  max_tokens=llm_cfg.get("max_tokens",2048)
  input_max=llm_cfg.get("input_max_length",30000)

  api_key=resolve_with_env_key(provider_id)
  config=AIProviderConfig(api_key=api_key,timeout=60)
  provider=get_provider(provider_id,config)
  if not provider:
   raise RuntimeError(f"Summary provider not found: {provider_id}")

  directive=get_summary_directive()
  directive_section=""
  if directive:
   directive_section=f"\n\n## 保持方針\n{directive}"

  prompt=f"""以下のエージェント出力を要約してください。

要約の要件:
-重要な決定事項を箇条書きで列挙
-成果物の構成（章立て・セクション）を簡潔に記述
-キーポイント（数値・名称・仕様値など）を保持
-不要な装飾・繰り返し・冗長な説明は除去{directive_section}

エージェントタイプ:{agent_type}

---出力内容---
{content[:input_max]}"""
  messages=[
   ChatMessage(role=MessageRole.USER,content=prompt),
  ]
  response=provider.chat(messages=messages,model=model,max_tokens=max_tokens)
  return response.content


def get_summary_service()->SummaryService:
 return SummaryService()
