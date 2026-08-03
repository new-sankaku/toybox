"""CTC音響ModelによるEngine

Language Modelを介さずGreedy復号するため、噛んだ発話が正解文へ補正されない。
早口言葉判定の本命候補。Model IDはConfigから与える。
"""
from typing import Dict,List,Optional,Sequence

import numpy as np

from ..audio import resample
from .base import Engine,EngineResult


class HuggingFaceCtcEngine(Engine):
 """Transformersの CTC Modelを用いた認識Engine"""

 def __init__(self,engine_id:str,params:Optional[Dict]=None):
  super().__init__(engine_id,params)
  self._model=None
  self._processor=None
  self._torch=None

 def prepare(self)->None:
  try:
   import torch
   from transformers import AutoModelForCTC,AutoProcessor
  except ImportError as error:
   raise RuntimeError(
    f"engine '{self.engine_id}' requires torch and transformers. "
    "install them with: pip install -r requirements-model.txt"
   ) from error
  model_id=self.params["model_id"]
  device=self.params.get("device","cpu")
  self._torch=torch
  self._processor=AutoProcessor.from_pretrained(model_id)
  self._model=AutoModelForCTC.from_pretrained(model_id).to(device).eval()
  super().prepare()

 def _decode(self,logits)->str:
  predicted=self._torch.argmax(logits,dim=-1)
  return self._processor.batch_decode(predicted)[0]

 def _confidences(self,logits)->List[float]:
  probabilities=self._torch.softmax(logits,dim=-1)
  values,_=probabilities.max(dim=-1)
  return values.squeeze(0).tolist()

 def recognize(self,samples:np.ndarray,sample_rate:int,reference:Sequence[str])->EngineResult:
  target_rate=self.target_sample_rate
  audio=resample(samples,sample_rate,target_rate)
  inputs=self._processor(
   audio,
   sampling_rate=target_rate,
   return_tensors="pt",
  )
  device=self.params.get("device","cpu")
  inputs={key:value.to(device) for key,value in inputs.items()}
  with self._torch.inference_mode():
   logits=self._model(**inputs).logits
  text=self._decode(logits)
  return EngineResult(
   hypothesis=self.text_to_mora(text),
   raw_text=text,
   confidences=self._confidences(logits),
  )
