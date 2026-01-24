"""Anthropic (Claude) プロバイダー"""
from typing import List,Optional,Dict,Any,Iterator
from .base import (
 AIProvider,AIProviderConfig,ChatMessage,ChatResponse,
 StreamChunk,ModelInfo,MessageRole
)


class AnthropicProvider(AIProvider):
 """Anthropicプロバイダー"""

 @property
 def provider_id(self)->str:
  return "anthropic"

 @property
 def display_name(self)->str:
  return "Anthropic (Claude)"

 def get_available_models(self)->List[ModelInfo]:
  return [
   ModelInfo(
    id="claude-sonnet-4-20250514",
    name="Claude Sonnet 4",
    max_tokens=8192,
    supports_vision=True,
    supports_tools=True,
    input_cost_per_1k=0.003,
    output_cost_per_1k=0.015
   ),
   ModelInfo(
    id="claude-3-5-sonnet-20241022",
    name="Claude 3.5 Sonnet",
    max_tokens=8192,
    supports_vision=True,
    supports_tools=True,
    input_cost_per_1k=0.003,
    output_cost_per_1k=0.015
   ),
   ModelInfo(
    id="claude-3-5-haiku-20241022",
    name="Claude 3.5 Haiku",
    max_tokens=8192,
    supports_vision=True,
    supports_tools=True,
    input_cost_per_1k=0.001,
    output_cost_per_1k=0.005
   ),
   ModelInfo(
    id="claude-3-haiku-20240307",
    name="Claude 3 Haiku",
    max_tokens=4096,
    supports_vision=True,
    supports_tools=True,
    input_cost_per_1k=0.00025,
    output_cost_per_1k=0.00125
   ),
  ]

 def _get_client(self):
  if self._client is None:
   try:
    import anthropic
    api_key = self.config.api_key
    if not api_key:
     from config import get_config
     app_config = get_config()
     api_key = app_config.agent.anthropic_api_key
    self._client = anthropic.Anthropic(
     api_key=api_key,
     timeout=self.config.timeout,
     max_retries=self.config.max_retries
    )
   except ImportError:
    raise ImportError("anthropicパッケージがインストールされていません")
  return self._client

 def _convert_messages(self,messages:List[ChatMessage])->tuple:
  system = None
  converted = []
  for msg in messages:
   if msg.role == MessageRole.SYSTEM:
    system = msg.content
   else:
    converted.append({"role":msg.role.value,"content":msg.content})
  return system,converted

 def chat(
  self,
  messages:List[ChatMessage],
  model:str,
  max_tokens:int = 1024,
  temperature:float = 0.7,
  **kwargs
 )->ChatResponse:
  client = self._get_client()
  system,msgs = self._convert_messages(messages)

  params = {
   "model":model,
   "max_tokens":max_tokens,
   "temperature":temperature,
   "messages":msgs,
  }
  if system:
   params["system"] = system

  response = client.messages.create(**params)

  content = ""
  if response.content:
   content = response.content[0].text

  return ChatResponse(
   content=content,
   model=response.model,
   input_tokens=response.usage.input_tokens,
   output_tokens=response.usage.output_tokens,
   total_tokens=response.usage.input_tokens + response.usage.output_tokens,
   finish_reason=response.stop_reason,
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
  system,msgs = self._convert_messages(messages)

  params = {
   "model":model,
   "max_tokens":max_tokens,
   "temperature":temperature,
   "messages":msgs,
  }
  if system:
   params["system"] = system

  with client.messages.stream(**params) as stream:
   for text in stream.text_stream:
    yield StreamChunk(content=text)

   final_message = stream.get_final_message()
   yield StreamChunk(
    content="",
    is_final=True,
    input_tokens=final_message.usage.input_tokens,
    output_tokens=final_message.usage.output_tokens
   )

 def test_connection(self)->Dict[str,Any]:
  try:
   client = self._get_client()
   response = client.messages.create(
    model="claude-3-haiku-20240307",
    max_tokens=10,
    messages=[{"role":"user","content":"Hi"}]
   )
   return {
    "success":True,
    "message":"Anthropic API: 正常に接続できました"
   }
  except Exception as e:
   error_type = type(e).__name__
   if "AuthenticationError" in error_type:
    return {"success":False,"message":"認証エラー: APIキーが無効です"}
   elif "RateLimitError" in error_type:
    return {"success":False,"message":"レート制限: しばらく待ってから再試行してください"}
   elif "APIConnectionError" in error_type:
    return {"success":False,"message":"接続エラー: APIサーバーに接続できません"}
   return {"success":False,"message":f"エラー: {str(e)}"}

 def validate_config(self)->bool:
  api_key = self.config.api_key
  if not api_key:
   from config import get_config
   app_config = get_config()
   api_key = app_config.agent.anthropic_api_key
  return bool(api_key)
