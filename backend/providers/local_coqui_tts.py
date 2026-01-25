"""ローカルCoqui TTSプロバイダー - 音声合成専用"""
import requests
from typing import List,Optional,Dict,Any,Iterator
from .base import (
 AIProvider,AIProviderConfig,ChatMessage,ChatResponse,
 StreamChunk,ModelInfo
)


class LocalCoquiTTSProvider(AIProvider):
 """ローカルCoqui TTSプロバイダー（音声合成専用）"""

 DEFAULT_BASE_URL="http://127.0.0.1:5002"

 @property
 def provider_id(self)->str:
  return"local-coqui-tts"

 @property
 def display_name(self)->str:
  return"Coqui TTS (ローカル)"

 def _get_base_url(self)->str:
  return self.config.base_url or self.DEFAULT_BASE_URL

 def get_available_models(self)->List[ModelInfo]:
  return [
   ModelInfo(
    id="xtts_v2",
    name="XTTS v2 (多言語・音声クローン対応)",
    max_tokens=0,
    supports_vision=False,
    supports_tools=False,
    input_cost_per_1k=0,
    output_cost_per_1k=0
   ),
   ModelInfo(
    id="vits",
    name="VITS (高速)",
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
  raise NotImplementedError("Coqui TTSは音声合成専用です。chat()メソッドはサポートされていません。")

 def chat_stream(
  self,
  messages:List[ChatMessage],
  model:str,
  max_tokens:int=1024,
  temperature:float=0.7,
  **kwargs
 )->Iterator[StreamChunk]:
  raise NotImplementedError("Coqui TTSは音声合成専用です。chat_stream()メソッドはサポートされていません。")

 def test_connection(self)->Dict[str,Any]:
  base_url=self._get_base_url()
  try:
   response=requests.get(
    f"{base_url}/api/tts-status",
    timeout=self.config.timeout
   )
   if response.status_code==200:
    status=response.json()
    return {
     "success":True,
     "message":f"Coqui TTS接続成功 (モデル: {status.get('model','不明')})"
    }
   response=requests.get(base_url,timeout=self.config.timeout)
   if response.status_code==200:
    return {
     "success":True,
     "message":"Coqui TTS接続成功"
    }
   return {
    "success":False,
    "message":f"Coqui TTS接続失敗: HTTP {response.status_code}"
   }
  except requests.exceptions.ConnectionError:
   return {
    "success":False,
    "message":f"Coqui TTSに接続できません ({base_url})"
   }
  except requests.exceptions.Timeout:
   return {
    "success":False,
    "message":"Coqui TTS接続タイムアウト"
   }
  except Exception as e:
   return {
    "success":False,
    "message":f"Coqui TTS接続エラー: {str(e)}"
   }

 def synthesize(
  self,
  text:str,
  speaker_id:Optional[str]=None,
  language:str="ja",
  speed:float=1.0,
  **kwargs
 )->Dict[str,Any]:
  base_url=self._get_base_url()
  params={"text":text,"language":language}
  if speaker_id:
   params["speaker_id"]=speaker_id
  if speed!=1.0:
   params["speed"]=speed
  try:
   response=requests.get(
    f"{base_url}/api/tts",
    params=params,
    timeout=max(self.config.timeout,120)
   )
   if response.status_code==200:
    content_type=response.headers.get("Content-Type","")
    if"audio" in content_type:
     return {
      "success":True,
      "audio_data":response.content,
      "content_type":content_type,
      "message":"音声合成が完了しました"
     }
    return {
     "success":True,
     "response":response.json(),
     "message":"音声合成が完了しました"
    }
   return {
    "success":False,
    "message":f"音声合成失敗: HTTP {response.status_code}"
   }
  except requests.exceptions.Timeout:
   return {
    "success":False,
    "message":"音声合成タイムアウト"
   }
  except Exception as e:
   return {
    "success":False,
    "message":f"音声合成エラー: {str(e)}"
   }

 def get_speakers(self)->Dict[str,Any]:
  base_url=self._get_base_url()
  try:
   response=requests.get(
    f"{base_url}/api/speakers",
    timeout=self.config.timeout
   )
   if response.status_code==200:
    speakers=response.json()
    return {
     "success":True,
     "speakers":speakers,
     "message":f"{len(speakers)}人の話者が利用可能です"
    }
   return {
    "success":False,
    "speakers":[],
    "message":f"話者一覧取得失敗: HTTP {response.status_code}"
   }
  except Exception as e:
   return {
    "success":False,
    "speakers":[],
    "message":f"話者一覧取得エラー: {str(e)}"
   }

 def get_languages(self)->Dict[str,Any]:
  base_url=self._get_base_url()
  try:
   response=requests.get(
    f"{base_url}/api/languages",
    timeout=self.config.timeout
   )
   if response.status_code==200:
    languages=response.json()
    return {
     "success":True,
     "languages":languages,
     "message":f"{len(languages)}言語が利用可能です"
    }
   return {
    "success":False,
    "languages":[],
    "message":f"言語一覧取得失敗: HTTP {response.status_code}"
   }
  except Exception as e:
   return {
    "success":False,
    "languages":[],
    "message":f"言語一覧取得エラー: {str(e)}"
   }

 def validate_config(self)->bool:
  return True
