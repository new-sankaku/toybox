"""Zhipu AI (智谱清言) プロバイダー"""
from typing import List,Optional,Dict,Any,Iterator
from middleware.logger import get_logger
from .base import (
 AIProvider,AIProviderConfig,ChatMessage,ChatResponse,
 StreamChunk,ModelInfo,MessageRole
)


class ZhipuProvider(AIProvider):
 """Zhipu AIプロバイダー"""

 @property
 def provider_id(self)->str:
  return"zhipu"

 @property
 def display_name(self)->str:
  return"Zhipu AI (智谱清言)"

 def get_available_models(self)->List[ModelInfo]:
  return self.load_models_from_config(self.provider_id)

 def _get_client(self):
  if self._client is None:
   try:
    from zhipuai import ZhipuAI
    api_key=self.config.api_key
    if not api_key:
     from config import get_config
     app_config=get_config()
     api_key=getattr(app_config.agent,"zhipu_api_key",None)
    self._client=ZhipuAI(api_key=api_key)
   except ImportError:
    raise ImportError("zhipuaiパッケージがインストールされていません: pip install zhipuai")
  return self._client

 def _convert_messages(self,messages:List[ChatMessage])->List[Dict[str,str]]:
  converted=[]
  for msg in messages:
   converted.append({"role":msg.role.value,"content":msg.content})
  return converted

 def chat(
  self,
  messages:List[ChatMessage],
  model:str,
  max_tokens:int=1024,
  temperature:float=0.7,
  **kwargs
 )->ChatResponse:
  client=self._get_client()
  msgs=self._convert_messages(messages)

  response=client.chat.completions.create(
   model=model,
   messages=msgs,
   max_tokens=max_tokens,
   temperature=temperature,
  )

  content=""
  if response.choices:
   content=response.choices[0].message.content or""

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
  max_tokens:int=1024,
  temperature:float=0.7,
  **kwargs
 )->Iterator[StreamChunk]:
  client=self._get_client()
  msgs=self._convert_messages(messages)

  response=client.chat.completions.create(
   model=model,
   messages=msgs,
   max_tokens=max_tokens,
   temperature=temperature,
   stream=True,
  )

  has_usage=False
  for chunk in response:
   if chunk.choices and chunk.choices[0].delta.content:
    content=chunk.choices[0].delta.content
    yield StreamChunk(content=content)
   usage=getattr(chunk,'usage',None)
   if usage:
    has_usage=True
    yield StreamChunk(
     content="",
     is_final=True,
     input_tokens=getattr(usage,'prompt_tokens',None),
     output_tokens=getattr(usage,'completion_tokens',None)
    )

  if not has_usage:
   yield StreamChunk(content="",is_final=True)

 def test_connection(self)->Dict[str,Any]:
  try:
   client=self._get_client()
   test_model=self.get_test_model_from_config(self.provider_id)
   response=client.chat.completions.create(
    model=test_model,
    messages=[{"role":"user","content":"Hi"}],
    max_tokens=10,
   )
   return {
    "success":True,
    "message":"Zhipu AI: 正常に接続できました"
   }
  except Exception as e:
   get_logger().error(f"Zhipu test_connection error: {e}",exc_info=True)
   error_str=str(e)
   if"api_key" in error_str.lower() or"auth" in error_str.lower():
    return {"success":False,"message":"認証エラー: APIキーが無効です"}
   return {"success":False,"message":f"エラー: {error_str}"}

 def validate_config(self)->bool:
  api_key=self.config.api_key
  if not api_key:
   try:
    from config import get_config
    app_config=get_config()
    api_key=getattr(app_config.agent,"zhipu_api_key",None)
   except Exception as e:
    get_logger().debug(f"Zhipu config validation: {e}")
  return bool(api_key)
