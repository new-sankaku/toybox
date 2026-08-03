"""CTC音響ModelによるEngine

Language Modelを介さずGreedy復号するため、噛んだ発話が正解文へ補正されない。
早口言葉判定の本命候補。Model IDと出力単位はConfigから与える。

復号はProcessorのbatch_decodeに任せずToken列で受け取る。Phoneme Modelでは
"ky" と "k"+"y" のように連結後の文字列が曖昧になるため、Token境界を保つ必要がある。
"""
from typing import Dict,List,Optional,Sequence

import numpy as np

from ..audio import resample
from ..mora import mora_text
from ..phoneme import normalize_phonemes
from .base import UNIT_PHONEME,Engine,EngineResult


class HuggingFaceCtcEngine(Engine):
 """Transformersの CTC Modelを用いた認識Engine"""

 def __init__(self,engine_id:str,params:Optional[Dict]=None):
  super().__init__(engine_id,params)
  self._model=None
  self._processor=None
  self._torch=None
  self._tokens:List[str]=[]
  self._blank_id=0

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
  torch.set_num_threads(int(self.params.get("num_threads",torch.get_num_threads())))
  tokenizer=self._processor.tokenizer
  vocabulary=tokenizer.get_vocab()
  self._tokens=[token for token,_ in sorted(vocabulary.items(),key=lambda item:item[1])]
  blank=tokenizer.pad_token_id
  if blank is None:
   raise RuntimeError(f"engine '{self.engine_id}' has no CTC blank token")
  self._blank_id=int(blank)
  super().prepare()

 def _collapse(self,ids:Sequence[int])->List[str]:
  tokens:List[str]=[]
  previous=None
  for token_id in ids:
   if token_id!=previous and token_id!=self._blank_id:
    tokens.append(self._tokens[token_id])
   previous=token_id
  return tokens

 def recognize(self,samples:np.ndarray,sample_rate:int,reference:Sequence[str])->EngineResult:
  target_rate=self.target_sample_rate
  audio=resample(samples,sample_rate,target_rate)
  device=self.params.get("device","cpu")
  inputs=self._processor(audio,sampling_rate=target_rate,return_tensors="pt")
  inputs={key:value.to(device) for key,value in inputs.items()}
  with self._torch.inference_mode():
   logits=self._model(**inputs).logits
  probabilities=self._torch.softmax(logits,dim=-1)
  best=self._torch.argmax(logits,dim=-1)[0].tolist()
  tokens=self._collapse(best)
  if self.output_unit==UNIT_PHONEME:
   hypothesis=normalize_phonemes(tokens)
   raw_text=" ".join(tokens)
  else:
   raw_text="".join("" if token=="|" else token for token in tokens)
   hypothesis=self.text_to_mora(raw_text)
  confidence=float(probabilities.max(dim=-1).values.mean().item())
  return EngineResult(
   hypothesis=hypothesis,
   raw_text=raw_text,
   extra={"mean_confidence":confidence,"token_text":mora_text(tokens)},
  )
