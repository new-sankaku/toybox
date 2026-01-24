"""AIプロバイダー抽象基底クラス"""
from abc import ABC,abstractmethod
from dataclasses import dataclass,field
from typing import List,Optional,Dict,Any,Iterator
from enum import Enum


class MessageRole(str,Enum):
 SYSTEM = "system"
 USER = "user"
 ASSISTANT = "assistant"


@dataclass
class ChatMessage:
 role:MessageRole
 content:str

 def to_dict(self)->Dict[str,str]:
  return {"role":self.role.value,"content":self.content}


@dataclass
class ChatResponse:
 content:str
 model:str
 input_tokens:int
 output_tokens:int
 total_tokens:int
 finish_reason:Optional[str] = None
 raw_response:Optional[Any] = None


@dataclass
class StreamChunk:
 content:str
 is_final:bool = False
 input_tokens:Optional[int] = None
 output_tokens:Optional[int] = None


@dataclass
class AIProviderConfig:
 api_key:Optional[str] = None
 base_url:Optional[str] = None
 timeout:int = 60
 max_retries:int = 2
 extra:Dict[str,Any] = field(default_factory=dict)


@dataclass
class ModelInfo:
 id:str
 name:str
 max_tokens:int
 supports_vision:bool = False
 supports_tools:bool = False
 input_cost_per_1k:Optional[float] = None
 output_cost_per_1k:Optional[float] = None


class AIProvider(ABC):
 """AIプロバイダー抽象基底クラス"""

 def __init__(self,config:Optional[AIProviderConfig] = None):
  self.config = config or AIProviderConfig()
  self._client = None

 @property
 @abstractmethod
 def provider_id(self)->str:
  """プロバイダー識別子"""
  pass

 @property
 @abstractmethod
 def display_name(self)->str:
  """表示名"""
  pass

 @abstractmethod
 def get_available_models(self)->List[ModelInfo]:
  """利用可能なモデル一覧"""
  pass

 @abstractmethod
 def chat(
  self,
  messages:List[ChatMessage],
  model:str,
  max_tokens:int = 1024,
  temperature:float = 0.7,
  **kwargs
 )->ChatResponse:
  """チャットcompletion API"""
  pass

 @abstractmethod
 def chat_stream(
  self,
  messages:List[ChatMessage],
  model:str,
  max_tokens:int = 1024,
  temperature:float = 0.7,
  **kwargs
 )->Iterator[StreamChunk]:
  """ストリーミングチャットAPI"""
  pass

 @abstractmethod
 def test_connection(self)->Dict[str,Any]:
  """接続テスト"""
  pass

 def validate_config(self)->bool:
  """設定の検証"""
  return True

 def get_default_model(self)->str:
  """デフォルトモデルを返す"""
  models = self.get_available_models()
  return models[0].id if models else ""
