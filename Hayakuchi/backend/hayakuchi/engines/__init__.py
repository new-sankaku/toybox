"""Engine Registry

利用するEngineはConfigのadapter名で解決する。Model IDやDeviceもConfig側に置き、
Code側にはModel固有の値を持たせない。
"""
from typing import Dict,List,Type

from .base import Engine,EngineResult
from .hf_ctc import HuggingFaceCtcEngine
from .replay import ReplayEngine
from .seq2seq_asr import Seq2SeqAsrEngine

_ADAPTERS:Dict[str,Type[Engine]]={
 "replay":ReplayEngine,
 "hf_ctc":HuggingFaceCtcEngine,
 "seq2seq_asr":Seq2SeqAsrEngine,
}


def available_adapters()->List[str]:
 """登録済みAdapter名を返す"""
 return sorted(_ADAPTERS)


def create_engine(definition:Dict)->Engine:
 """Config定義からEngine instanceを生成する"""
 adapter=definition.get("adapter")
 if adapter not in _ADAPTERS:
  raise ValueError(
   f"unknown engine adapter: {adapter}. available={available_adapters()}"
  )
 return _ADAPTERS[adapter](str(definition["id"]),definition.get("params",{}))


__all__=["Engine","EngineResult","available_adapters","create_engine"]
