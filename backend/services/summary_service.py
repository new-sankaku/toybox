import os
from typing import Optional,Dict,Any
from config_loader import get_context_policy_settings
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

 def generate_summary(self,content:str,agent_type:str,fallback_func=None)->str:
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
   return self._call_llm_summary(content,agent_type,llm_cfg)
  except Exception as e:
   get_logger().error(f"SummaryService LLM summary failed, using fallback: {e}",exc_info=True)
   if fallback_func:
    return fallback_func(content)
   return content[:settings.get("summary_max_length",10000)]

 def _call_llm_summary(self,content:str,agent_type:str,llm_cfg:dict)->str:
  provider_id=llm_cfg.get("provider","anthropic")
  model=llm_cfg.get("model","claude-haiku-4-5-20250116")
  max_tokens=llm_cfg.get("max_tokens",2048)
  input_max=llm_cfg.get("input_max_length",30000)
  env_key_map={
   "anthropic":"ANTHROPIC_API_KEY",
   "openai":"OPENAI_API_KEY",
   "google":"GOOGLE_API_KEY",
   "xai":"XAI_API_KEY",
   "deepseek":"DEEPSEEK_API_KEY",
  }
  api_key=os.environ.get(env_key_map.get(provider_id,"ANTHROPIC_API_KEY"))
  config=AIProviderConfig(api_key=api_key,timeout=60)
  provider=get_provider(provider_id,config)
  if not provider:
   raise RuntimeError(f"Summary provider not found: {provider_id}")
  prompt=f"""以下のエージェント出力を要約してください。

要約の要件:
-重要な決定事項を箇条書きで列挙
-成果物の構成（章立て・セクション）を簡潔に記述
-キーポイント（数値・名称・仕様値など）を保持
-不要な装飾・繰り返し・冗長な説明は除去

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
