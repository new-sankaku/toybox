"""判定Engineの共通Interface

Engineは音声からMora列を返すことだけに責任を持ち、Score算出と閾値判断は
scoring/metrics側に置く。これによりModelを差し替えても評価軸が動かない。
"""
import time
from abc import ABC,abstractmethod
from dataclasses import dataclass,field
from typing import Dict,List,Optional,Sequence

import numpy as np

from ..mora import to_mora


@dataclass
class EngineResult:
 hypothesis:List[str]
 raw_text:str
 elapsed_ms:float=0.0
 confidences:Optional[List[float]]=None
 extra:Dict=field(default_factory=dict)


class Engine(ABC):
 """音声をMora列へ変換するEngineの基底Class"""

 def __init__(self,engine_id:str,params:Optional[Dict]=None):
  self.engine_id=engine_id
  self.params=params or {}
  self._prepared=False

 @property
 def target_sample_rate(self)->int:
  return int(self.params.get("target_sample_rate",16000))

 def prepare(self)->None:
  """Model読み込みなどの初期化を行う"""
  self._prepared=True

 @abstractmethod
 def recognize(self,samples:np.ndarray,sample_rate:int,reference:Sequence[str])->EngineResult:
  """音声を認識しMora列を含むResultを返す"""

 def run(self,samples:np.ndarray,sample_rate:int,reference:Sequence[str],sample_id:str)->EngineResult:
  """初期化を保証したうえで認識を実行し、所要時間を計測する"""
  if not self._prepared:
   self.prepare()
  self._current_sample_id=sample_id
  started=time.perf_counter()
  result=self.recognize(samples,sample_rate,reference)
  result.elapsed_ms=(time.perf_counter()-started)*1000.0
  return result

 @staticmethod
 def text_to_mora(text:str)->List[str]:
  """認識Textを共通のMora列表現へ変換する"""
  return to_mora(text)
