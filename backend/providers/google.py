"""Google (Gemini) プロバイダー"""
from typing import List,Optional,Dict,Any,Iterator
from .base import (
 AIProvider,AIProviderConfig,ChatMessage,ChatResponse,
 StreamChunk,ModelInfo,MessageRole
)


class GoogleProvider(AIProvider):
 """Googleプロバイダー (Gemini)"""

 @property
 def provider_id(self)->str:
  return "google"

 @property
 def display_name(self)->str:
  return "Google (Gemini)"

 def get_available_models(self)->List[ModelInfo]:
  models = self.load_models_from_config(self.provider_id)
  if models:
   return models
  return [
   ModelInfo(
    id="gemini-2.0-flash",
    name="Gemini 2.0 Flash",
    max_tokens=8192,
    supports_vision=True,
    supports_tools=True,
    input_cost_per_1k=0.0001,
    output_cost_per_1k=0.0004
   ),
  ]

 def _get_client(self):
  if self._client is None:
   try:
    import google.generativeai as genai
    api_key = self.config.api_key
    genai.configure(api_key=api_key)
    self._client = genai
   except ImportError:
    raise ImportError("google-generativeaiパッケージがインストールされていません")
  return self._client

 def _convert_messages(self,messages:List[ChatMessage])->tuple:
  system = None
  history = []
  for msg in messages:
   if msg.role == MessageRole.SYSTEM:
    system = msg.content
   elif msg.role == MessageRole.USER:
    history.append({"role":"user","parts":[msg.content]})
   elif msg.role == MessageRole.ASSISTANT:
    history.append({"role":"model","parts":[msg.content]})
  return system,history

 def chat(
  self,
  messages:List[ChatMessage],
  model:str,
  max_tokens:int = 1024,
  temperature:float = 0.7,
  **kwargs
 )->ChatResponse:
  genai = self._get_client()
  system,history = self._convert_messages(messages)

  generation_config = {
   "max_output_tokens":max_tokens,
   "temperature":temperature,
  }

  model_instance = genai.GenerativeModel(
   model_name=model,
   system_instruction=system,
   generation_config=generation_config
  )

  if len(history) > 1:
   chat = model_instance.start_chat(history=history[:-1])
   last_msg = history[-1]["parts"][0] if history else ""
   response = chat.send_message(last_msg)
  else:
   last_msg = history[-1]["parts"][0] if history else ""
   response = model_instance.generate_content(last_msg)

  content = response.text if hasattr(response,"text") else ""

  input_tokens = 0
  output_tokens = 0
  if hasattr(response,"usage_metadata"):
   input_tokens = getattr(response.usage_metadata,"prompt_token_count",0)
   output_tokens = getattr(response.usage_metadata,"candidates_token_count",0)

  return ChatResponse(
   content=content,
   model=model,
   input_tokens=input_tokens,
   output_tokens=output_tokens,
   total_tokens=input_tokens + output_tokens,
   finish_reason="stop",
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
  genai = self._get_client()
  system,history = self._convert_messages(messages)

  generation_config = {
   "max_output_tokens":max_tokens,
   "temperature":temperature,
  }

  model_instance = genai.GenerativeModel(
   model_name=model,
   system_instruction=system,
   generation_config=generation_config
  )

  last_msg = history[-1]["parts"][0] if history else ""

  if len(history) > 1:
   chat = model_instance.start_chat(history=history[:-1])
   response = chat.send_message(last_msg,stream=True)
  else:
   response = model_instance.generate_content(last_msg,stream=True)

  for chunk in response:
   if hasattr(chunk,"text") and chunk.text:
    yield StreamChunk(content=chunk.text)

  yield StreamChunk(content="",is_final=True)

 def test_connection(self)->Dict[str,Any]:
  try:
   genai = self._get_client()
   test_model = self.get_test_model_from_config(self.provider_id)
   if not test_model:
    test_model = "gemini-2.0-flash"
   model = genai.GenerativeModel(test_model)
   response = model.generate_content("Hi")
   return {
    "success":True,
    "message":"Google Gemini API: 正常に接続できました"
   }
  except Exception as e:
   error_msg = str(e).lower()
   if "api key" in error_msg or "authentication" in error_msg:
    return {"success":False,"message":"認証エラー: APIキーが無効です"}
   elif "quota" in error_msg or "rate" in error_msg:
    return {"success":False,"message":"レート制限: しばらく待ってから再試行してください"}
   return {"success":False,"message":f"エラー: {str(e)}"}

 def validate_config(self)->bool:
  return bool(self.config.api_key)
