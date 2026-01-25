"""モックプロバイダー - テスト/デモ用"""
import time
import random
from typing import List,Optional,Dict,Any,Iterator
from .base import (
 AIProvider,AIProviderConfig,ChatMessage,ChatResponse,
 StreamChunk,ModelInfo,MessageRole
)


class MockProvider(AIProvider):
 """モックプロバイダー（テスト/デモ用）"""

 @property
 def provider_id(self)->str:
  return"mock"

 @property
 def display_name(self)->str:
  return"Mock (テスト用)"

 def get_available_models(self)->List[ModelInfo]:
  return [
   ModelInfo(
    id="mock-fast",
    name="Mock Fast",
    max_tokens=4096,
    supports_vision=False,
    supports_tools=False,
    input_cost_per_1k=0,
    output_cost_per_1k=0
   ),
   ModelInfo(
    id="mock-standard",
    name="Mock Standard",
    max_tokens=8192,
    supports_vision=True,
    supports_tools=True,
    input_cost_per_1k=0,
    output_cost_per_1k=0
   ),
  ]

 def _generate_mock_response(self,messages:List[ChatMessage])->str:
  last_msg=messages[-1].content if messages else""

  responses=[
   "了解しました。ご依頼の内容を確認しました。",
   "処理を開始します。結果をお待ちください。",
   "分析が完了しました。以下が結果です。",
   "ご質問ありがとうございます。こちらが回答です。",
   "タスクを実行しました。正常に完了しました。",
  ]

  base_response=random.choice(responses)
  if len(last_msg)>20:
   return f"{base_response}\n\n入力: {last_msg[:50]}..."
  return base_response

 def chat(
  self,
  messages:List[ChatMessage],
  model:str,
  max_tokens:int=1024,
  temperature:float=0.7,
  **kwargs
 )->ChatResponse:
  time.sleep(random.uniform(0.1,0.3))

  content=self._generate_mock_response(messages)
  input_tokens=sum(len(m.content.split())*2 for m in messages)
  output_tokens=len(content.split())*2

  return ChatResponse(
   content=content,
   model=model,
   input_tokens=input_tokens,
   output_tokens=output_tokens,
   total_tokens=input_tokens+output_tokens,
   finish_reason="stop",
   raw_response=None
  )

 def chat_stream(
  self,
  messages:List[ChatMessage],
  model:str,
  max_tokens:int=1024,
  temperature:float=0.7,
  **kwargs
 )->Iterator[StreamChunk]:
  content=self._generate_mock_response(messages)
  words=content.split()

  for word in words:
   time.sleep(random.uniform(0.02,0.05))
   yield StreamChunk(content=word+" ")

  input_tokens=sum(len(m.content.split())*2 for m in messages)
  output_tokens=len(words)*2

  yield StreamChunk(
   content="",
   is_final=True,
   input_tokens=input_tokens,
   output_tokens=output_tokens
  )

 def test_connection(self)->Dict[str,Any]:
  time.sleep(0.1)
  return {
   "success":True,
   "message":"モック接続: 正常に接続できました"
  }

 def validate_config(self)->bool:
  return True
