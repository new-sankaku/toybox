"""Zhipu AI (智谱清言) プロバイダー"""
from typing import List,Optional,Dict,Any,Iterator
from .base import (
 AIProvider,AIProviderConfig,ChatMessage,ChatResponse,
 StreamChunk,ModelInfo,MessageRole
)


class ZhipuProvider(AIProvider):
 """Zhipu AIプロバイダー"""

 @property
 def provider_id(self)->str:
  return "zhipu"

 @property
 def display_name(self)->str:
  return "Zhipu AI (智谱清言)"

 def get_available_models(self)->List[ModelInfo]:
  return [
   ModelInfo(
    id="glm-4-plus",
    name="GLM-4 Plus",
    max_tokens=128000,
    supports_vision=False,
    supports_tools=True,
    input_cost_per_1k=0.05,
    output_cost_per_1k=0.05
   ),
   ModelInfo(
    id="glm-4-flash",
    name="GLM-4 Flash",
    max_tokens=128000,
    supports_vision=False,
    supports_tools=True,
    input_cost_per_1k=0.0001,
    output_cost_per_1k=0.0001
   ),
   ModelInfo(
    id="glm-4v-plus",
    name="GLM-4V Plus",
    max_tokens=8192,
    supports_vision=True,
    supports_tools=False,
    input_cost_per_1k=0.01,
    output_cost_per_1k=0.01
   ),
  ]

 def _get_client(self):
  if self._client is None:
   try:
    from zhipuai import ZhipuAI
    api_key = self.config.api_key
    if not api_key:
     from config import get_config
     app_config = get_config()
     api_key = getattr(app_config.agent,"zhipu_api_key",None)
    self._client = ZhipuAI(api_key=api_key)
   except ImportError:
    raise ImportError("zhipuaiパッケージがインストールされていません: pip install zhipuai")
  return self._client

 def _convert_messages(self,messages:List[ChatMessage])->List[Dict[str,str]]:
  converted = []
  for msg in messages:
   converted.append({"role":msg.role.value,"content":msg.content})
  return converted

 def chat(
  self,
  messages:List[ChatMessage],
  model:str,
  max_tokens:int = 1024,
  temperature:float = 0.7,
  **kwargs
 )->ChatResponse:
  client = self._get_client()
  msgs = self._convert_messages(messages)

  response = client.chat.completions.create(
   model=model,
   messages=msgs,
   max_tokens=max_tokens,
   temperature=temperature,
  )

  content = ""
  if response.choices:
   content = response.choices[0].message.content or ""

  return ChatResponse(
   content=content,
   model=response.model,
   input_tokens=response.usage.prompt_tokens if response.usage else 0,
   output_tokens=response.usage.completion_tokens if response.usage else 0,
   total_tokens=response.usage.total_tokens if response.usage else 0,
   finish_reason=response.choices[0].finish_reason if response.choices else None,
   raw_response=response
  )

 def chat_stream(
  self,
  messages:List[ChatMessage],
  model:str,
  max_tokens:int = 1024,
  temperature:float = 0.7,
  **kwargs
 )->Iterator[StreamChunk]:
  client = self._get_client()
  msgs = self._convert_messages(messages)

  response = client.chat.completions.create(
   model=model,
   messages=msgs,
   max_tokens=max_tokens,
   temperature=temperature,
   stream=True,
  )

  total_content = ""
  for chunk in response:
   if chunk.choices and chunk.choices[0].delta.content:
    content = chunk.choices[0].delta.content
    total_content += content
    yield StreamChunk(content=content)

  yield StreamChunk(
   content="",
   is_final=True,
  )

 def test_connection(self)->Dict[str,Any]:
  try:
   client = self._get_client()
   response = client.chat.completions.create(
    model="glm-4-flash",
    messages=[{"role":"user","content":"Hi"}],
    max_tokens=10,
   )
   return {
    "success":True,
    "message":"Zhipu AI: 正常に接続できました"
   }
  except Exception as e:
   error_str = str(e)
   if "api_key" in error_str.lower() or "auth" in error_str.lower():
    return {"success":False,"message":"認証エラー: APIキーが無効です"}
   return {"success":False,"message":f"エラー: {error_str}"}

 def validate_config(self)->bool:
  api_key = self.config.api_key
  if not api_key:
   try:
    from config import get_config
    app_config = get_config()
    api_key = getattr(app_config.agent,"zhipu_api_key",None)
   except:
    pass
  return bool(api_key)
