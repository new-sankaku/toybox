"""ローカルAudioCraftプロバイダー - 音楽・効果音生成専用"""
import requests
from typing import List,Optional,Dict,Any,Iterator
from .base import (
 AIProvider,AIProviderConfig,ChatMessage,ChatResponse,
 StreamChunk,ModelInfo
)


class LocalAudioCraftProvider(AIProvider):
 """ローカルAudioCraftプロバイダー（音楽・効果音生成専用）"""

 DEFAULT_BASE_URL="http://127.0.0.1:7860"

 @property
 def provider_id(self)->str:
  return"local-audiocraft"

 @property
 def display_name(self)->str:
  return"AudioCraft (ローカル)"

 def _get_base_url(self)->str:
  return self.config.base_url or self.DEFAULT_BASE_URL

 def get_available_models(self)->List[ModelInfo]:
  return [
   ModelInfo(
    id="musicgen-small",
    name="MusicGen Small",
    max_tokens=0,
    supports_vision=False,
    supports_tools=False,
    input_cost_per_1k=0,
    output_cost_per_1k=0
   ),
   ModelInfo(
    id="musicgen-medium",
    name="MusicGen Medium",
    max_tokens=0,
    supports_vision=False,
    supports_tools=False,
    input_cost_per_1k=0,
    output_cost_per_1k=0
   ),
   ModelInfo(
    id="musicgen-large",
    name="MusicGen Large",
    max_tokens=0,
    supports_vision=False,
    supports_tools=False,
    input_cost_per_1k=0,
    output_cost_per_1k=0
   ),
   ModelInfo(
    id="audiogen-medium",
    name="AudioGen Medium (効果音)",
    max_tokens=0,
    supports_vision=False,
    supports_tools=False,
    input_cost_per_1k=0,
    output_cost_per_1k=0
   ),
  ]

 def chat(
  self,
  messages:List[ChatMessage],
  model:str,
  max_tokens:int=1024,
  temperature:float=0.7,
  **kwargs
 )->ChatResponse:
  raise NotImplementedError("AudioCraftは音声生成専用です。chat()メソッドはサポートされていません。")

 def chat_stream(
  self,
  messages:List[ChatMessage],
  model:str,
  max_tokens:int=1024,
  temperature:float=0.7,
  **kwargs
 )->Iterator[StreamChunk]:
  raise NotImplementedError("AudioCraftは音声生成専用です。chat_stream()メソッドはサポートされていません。")

 def test_connection(self)->Dict[str,Any]:
  base_url=self._get_base_url()
  try:
   response=requests.get(
    f"{base_url}/api/health",
    timeout=self.config.timeout
   )
   if response.status_code==200:
    return {
     "success":True,
     "message":"AudioCraft接続成功"
    }
   response=requests.get(base_url,timeout=self.config.timeout)
   if response.status_code==200:
    return {
     "success":True,
     "message":"AudioCraft接続成功 (Gradio UI)"
    }
   return {
    "success":False,
    "message":f"AudioCraft接続失敗: HTTP {response.status_code}"
   }
  except requests.exceptions.ConnectionError:
   return {
    "success":False,
    "message":f"AudioCraftに接続できません ({base_url})"
   }
  except requests.exceptions.Timeout:
   return {
    "success":False,
    "message":"AudioCraft接続タイムアウト"
   }
  except Exception as e:
   return {
    "success":False,
    "message":f"AudioCraft接続エラー: {str(e)}"
   }

 def generate_audio(
  self,
  prompt:str,
  model:str="musicgen-medium",
  duration:float=10.0,
  temperature:float=1.0,
  top_k:int=250,
  top_p:float=0.0,
  cfg_coef:float=3.0,
  **kwargs
 )->Dict[str,Any]:
  base_url=self._get_base_url()
  try:
   response=requests.post(
    f"{base_url}/api/generate",
    json={
     "prompt":prompt,
     "model":model,
     "duration":duration,
     "temperature":temperature,
     "top_k":top_k,
     "top_p":top_p,
     "cfg_coef":cfg_coef
    },
    timeout=max(self.config.timeout,300)
   )
   if response.status_code==200:
    result=response.json()
    return {
     "success":True,
     "audio_path":result.get("audio_path"),
     "audio_base64":result.get("audio_base64"),
     "duration":result.get("duration"),
     "message":"音声生成が完了しました"
    }
   return {
    "success":False,
    "message":f"音声生成失敗: HTTP {response.status_code}"
   }
  except requests.exceptions.Timeout:
   return {
    "success":False,
    "message":"音声生成タイムアウト（長い音声の場合は時間がかかります）"
   }
  except Exception as e:
   return {
    "success":False,
    "message":f"音声生成エラー: {str(e)}"
   }

 def generate_music(
  self,
  prompt:str,
  duration:float=30.0,
  model:str="musicgen-medium",
  **kwargs
 )->Dict[str,Any]:
  return self.generate_audio(prompt=prompt,model=model,duration=duration,**kwargs)

 def generate_sfx(
  self,
  prompt:str,
  duration:float=5.0,
  **kwargs
 )->Dict[str,Any]:
  return self.generate_audio(prompt=prompt,model="audiogen-medium",duration=duration,**kwargs)

 def validate_config(self)->bool:
  return True
