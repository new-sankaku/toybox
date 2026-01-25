"""OpenAI プロバイダー"""
from typing import List,Optional,Dict,Any,Iterator
from .base import (
 AIProvider,AIProviderConfig,ChatMessage,ChatResponse,
 StreamChunk,ModelInfo,MessageRole
)


class OpenAIProvider(AIProvider):
 """OpenAIプロバイダー"""

 @property
 def provider_id(self)->str:
  return "openai"

 @property
 def display_name(self)->str:
  return "OpenAI"

 def get_available_models(self)->List[ModelInfo]:
  models = self.load_models_from_config(self.provider_id)
  if models:
   return models
  return [
   ModelInfo(
    id="gpt-4o",
    name="GPT-4o",
    max_tokens=16384,
    supports_vision=True,
    supports_tools=True,
    input_cost_per_1k=0.0025,
    output_cost_per_1k=0.01
   ),
  ]

 def _get_client(self):
  if self._client is None:
   try:
    import openai
    api_key = self.config.api_key
    kwargs = {"api_key":api_key,"timeout":self.config.timeout}
    if self.config.base_url:
     kwargs["base_url"] = self.config.base_url
    self._client = openai.OpenAI(**kwargs)
   except ImportError:
    raise ImportError("openaiパッケージがインストールされていません")
  return self._client

 def _convert_messages(self,messages:List[ChatMessage])->List[Dict]:
  return [{"role":m.role.value,"content":m.content} for m in messages]

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
   **kwargs
  )

  choice = response.choices[0]
  content = choice.message.content or ""

  return ChatResponse(
   content=content,
   model=response.model,
   input_tokens=response.usage.prompt_tokens if response.usage else 0,
   output_tokens=response.usage.completion_tokens if response.usage else 0,
   total_tokens=response.usage.total_tokens if response.usage else 0,
   finish_reason=choice.finish_reason,
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

  stream = client.chat.completions.create(
   model=model,
   messages=msgs,
   max_tokens=max_tokens,
   temperature=temperature,
   stream=True,
   stream_options={"include_usage":True},
   **kwargs
  )

  for chunk in stream:
   if chunk.choices and chunk.choices[0].delta.content:
    yield StreamChunk(content=chunk.choices[0].delta.content)
   if chunk.usage:
    yield StreamChunk(
     content="",
     is_final=True,
     input_tokens=chunk.usage.prompt_tokens,
     output_tokens=chunk.usage.completion_tokens
    )

 def test_connection(self)->Dict[str,Any]:
  try:
   client = self._get_client()
   test_model = self.get_test_model_from_config(self.provider_id)
   if not test_model:
    test_model = "gpt-4o-mini"
   response = client.chat.completions.create(
    model=test_model,
    max_tokens=10,
    messages=[{"role":"user","content":"Hi"}]
   )
   return {
    "success":True,
    "message":"OpenAI API: 正常に接続できました"
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
  return bool(self.config.api_key)
