"""DeepSeek プロバイダー"""
from typing import List,Optional,Dict,Any,Iterator
from .base import (
 AIProvider,AIProviderConfig,ChatMessage,ChatResponse,
 StreamChunk,ModelInfo,MessageRole
)


class DeepSeekProvider(AIProvider):
 """DeepSeekプロバイダー（OpenAI互換API）"""

 DEEPSEEK_BASE_URL = "https://api.deepseek.com"

 @property
 def provider_id(self)->str:
  return "deepseek"

 @property
 def display_name(self)->str:
  return "DeepSeek"

 def get_available_models(self)->List[ModelInfo]:
  return [
   ModelInfo(
    id="deepseek-chat",
    name="DeepSeek Chat (V3)",
    max_tokens=8192,
    supports_vision=False,
    supports_tools=True,
    input_cost_per_1k=0.00014,
    output_cost_per_1k=0.00028
   ),
   ModelInfo(
    id="deepseek-reasoner",
    name="DeepSeek Reasoner (R1)",
    max_tokens=8192,
    supports_vision=False,
    supports_tools=False,
    input_cost_per_1k=0.00055,
    output_cost_per_1k=0.00219
   ),
  ]

 def _get_client(self):
  if self._client is None:
   try:
    from openai import OpenAI
    api_key = self.config.api_key
    if not api_key:
     from config import get_config
     app_config = get_config()
     api_key = getattr(app_config.agent,"deepseek_api_key",None)
    base_url = self.config.base_url or self.DEEPSEEK_BASE_URL
    self._client = OpenAI(
     api_key=api_key,
     base_url=base_url,
     timeout=self.config.timeout,
     max_retries=self.config.max_retries,
    )
   except ImportError:
    raise ImportError("openaiパッケージがインストールされていません: pip install openai")
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

  for chunk in response:
   if chunk.choices and chunk.choices[0].delta.content:
    content = chunk.choices[0].delta.content
    yield StreamChunk(content=content)

  yield StreamChunk(
   content="",
   is_final=True,
  )

 def test_connection(self)->Dict[str,Any]:
  try:
   client = self._get_client()
   response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role":"user","content":"Hi"}],
    max_tokens=10,
   )
   return {
    "success":True,
    "message":"DeepSeek: 正常に接続できました"
   }
  except Exception as e:
   error_str = str(e)
   if "api_key" in error_str.lower() or "auth" in error_str.lower() or "401" in error_str:
    return {"success":False,"message":"認証エラー: APIキーが無効です"}
   if "rate" in error_str.lower() or "429" in error_str:
    return {"success":False,"message":"レート制限: しばらく待ってから再試行してください"}
   return {"success":False,"message":f"エラー: {error_str}"}

 def validate_config(self)->bool:
  api_key = self.config.api_key
  if not api_key:
   try:
    from config import get_config
    app_config = get_config()
    api_key = getattr(app_config.agent,"deepseek_api_key",None)
   except:
    pass
  return bool(api_key)
