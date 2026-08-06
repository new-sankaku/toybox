"""既存書き起こしを再生するEngine

Modelを動かさずにHarnessを検証する用途と、人手書き起こしを流し込んで
「人間が聞いた場合の上限値」をBaselineとして測る用途に使う。
Model推論の代替ではないため、実Modelの結果として扱ってはならない。
"""
import json
from pathlib import Path
from typing import Dict,Optional,Sequence

import numpy as np

from .base import Engine,EngineResult


class ReplayEngine(Engine):
 """Sample IDに紐づく書き起こしを返すEngine"""

 def __init__(self,engine_id:str,params:Optional[Dict]=None):
  super().__init__(engine_id,params)
  self._transcripts:Dict[str,str]={}

 def prepare(self)->None:
  path=Path(self.params["transcripts"])
  with path.open("r",encoding="utf-8") as handle:
   payload=json.load(handle)
  self._transcripts={str(key):str(value) for key,value in payload.items()}
  super().prepare()

 def recognize(self,samples:np.ndarray,sample_rate:int,reference:Sequence[str])->EngineResult:
  sample_id=getattr(self,"_current_sample_id","")
  if sample_id not in self._transcripts:
   raise KeyError(f"transcript not found for sample: {sample_id}")
  text=self._transcripts[sample_id]
  return EngineResult(hypothesis=self.text_to_mora(text),raw_text=text)
