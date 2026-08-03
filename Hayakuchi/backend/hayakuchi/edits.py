"""音声への発話内容の改変

収録条件のSimulation（conditions）とは目的が異なる。conditionsは「同じ発話を
別の環境で録った状態」を作るのに対し、editsは「別の発話になった状態」を作る。

正解Textを持たない音源でもLanguage Modelによる補正を検出できる点が重要で、
改変前後でEngine出力が変化しなければ、そのEngineは実際の音ではなく
言語的な尤もらしさを出力していることになる。
"""
from dataclasses import dataclass
from typing import Callable,Dict,List

import numpy as np

CUT="cut"
REPEAT="repeat"
SWAP="swap"


@dataclass(frozen=True)
class Edit:
 id:str
 label:str
 kind:str
 position:float
 duration_ms:float

 @classmethod
 def from_dict(cls,data:Dict)->"Edit":
  kind=str(data["kind"])
  if kind not in _APPLIERS:
   raise ValueError(f"unknown edit kind: {kind}. available={sorted(_APPLIERS)}")
  position=float(data["position"])
  if not 0.0<position<1.0:
   raise ValueError(f"edit position must be within (0,1): {position}")
  return cls(
   id=str(data["id"]),
   label=str(data.get("label",data["id"])),
   kind=kind,
   position=position,
   duration_ms=float(data["duration_ms"]),
  )


def _span(samples:np.ndarray,sample_rate:int,edit:Edit):
 width=int(sample_rate*edit.duration_ms/1000.0)
 if width<=0:
  raise ValueError(f"edit duration is too short: {edit.duration_ms}ms")
 start=int(samples.size*edit.position)
 return start,width


def _cut(samples:np.ndarray,sample_rate:int,edit:Edit)->np.ndarray:
 start,width=_span(samples,sample_rate,edit)
 if start+width>=samples.size:
  raise ValueError(f"audio is too short for edit: {edit.id}")
 return np.concatenate([samples[:start],samples[start+width:]])


def _repeat(samples:np.ndarray,sample_rate:int,edit:Edit)->np.ndarray:
 start,width=_span(samples,sample_rate,edit)
 if start+width>=samples.size:
  raise ValueError(f"audio is too short for edit: {edit.id}")
 segment=samples[start:start+width]
 return np.concatenate([samples[:start+width],segment,samples[start+width:]])


def _swap(samples:np.ndarray,sample_rate:int,edit:Edit)->np.ndarray:
 start,width=_span(samples,sample_rate,edit)
 if start+2*width>=samples.size:
  raise ValueError(f"audio is too short for edit: {edit.id}")
 first=samples[start:start+width]
 second=samples[start+width:start+2*width]
 return np.concatenate([samples[:start],second,first,samples[start+2*width:]])


_APPLIERS:Dict[str,Callable[[np.ndarray,int,Edit],np.ndarray]]={
 CUT:_cut,
 REPEAT:_repeat,
 SWAP:_swap,
}


def load_edits(entries:List[Dict])->List[Edit]:
 """Config記載のEdit定義を読み込む"""
 if not entries:
  raise ValueError("no edit is defined in config")
 return [Edit.from_dict(entry) for entry in entries]


def apply_edit(samples:np.ndarray,sample_rate:int,edit:Edit)->np.ndarray:
 """発話内容を改変した音声を返す"""
 return _APPLIERS[edit.kind](samples.astype(np.float32),sample_rate,edit).astype(np.float32)
