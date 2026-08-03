"""Seq2Seq音声認識ModelによるEngine

Decoder側にLanguage Modelを内包するため、噛んだ発話を正解文へ補正する
可能性がある。採用候補ではなく、lm_correction_rateを実測して失格を確認する
ためのControl群として置く。
"""
from typing import Dict,Optional,Sequence

import numpy as np

from ..audio import resample
from .base import Engine,EngineResult


class Seq2SeqAsrEngine(Engine):
 """Transformersの Seq2Seq音声認識Modelを用いたControl用Engine"""

 def __init__(self,engine_id:str,params:Optional[Dict]=None):
  super().__init__(engine_id,params)
  self._pipeline=None

 def prepare(self)->None:
  try:
   from transformers import pipeline
  except ImportError as error:
   raise RuntimeError(
    f"engine '{self.engine_id}' requires torch and transformers. "
    "install them with: pip install -r requirements-model.txt"
   ) from error
  self._pipeline=pipeline(
   task="automatic-speech-recognition",
   model=self.params["model_id"],
   device=self.params.get("device","cpu"),
  )
  super().prepare()

 def recognize(self,samples:np.ndarray,sample_rate:int,reference:Sequence[str])->EngineResult:
  target_rate=self.target_sample_rate
  audio=resample(samples,sample_rate,target_rate)
  generate_kwargs=dict(self.params.get("generate_kwargs",{}))
  output=self._pipeline(
   {"raw":audio,"sampling_rate":target_rate},
   generate_kwargs=generate_kwargs,
  )
  text=output["text"] if isinstance(output,dict) else str(output)
  return EngineResult(hypothesis=self.text_to_mora(text),raw_text=text)
