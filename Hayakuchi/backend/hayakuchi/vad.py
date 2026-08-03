"""発話区間の検出

判定を開始・終了させるための発話端点検出。Frameごとの音量を、静音区間から
推定した雑音Floorと比較する。Floorを実測から更新するため、収録環境ごとの
Gain差に閾値が引きずられない。
"""
from dataclasses import dataclass
from enum import Enum
from typing import Dict,Optional

import numpy as np

_EPS=1e-10


class VadEvent(Enum):
 NONE="none"
 SPEECH_START="speech_start"
 SPEECH_END="speech_end"


@dataclass
class VadConfig:
 frame_ms:float=30.0
 start_offset_db:float=12.0
 end_offset_db:float=6.0
 start_frames:int=3
 hangover_ms:float=250.0
 min_speech_ms:float=300.0
 floor_adaptation:float=0.05
 initial_floor_db:float=-60.0

 @classmethod
 def from_dict(cls,data:Optional[Dict])->"VadConfig":
  data=data or {}
  default=cls()
  return cls(
   frame_ms=float(data.get("frame_ms",default.frame_ms)),
   start_offset_db=float(data.get("start_offset_db",default.start_offset_db)),
   end_offset_db=float(data.get("end_offset_db",default.end_offset_db)),
   start_frames=int(data.get("start_frames",default.start_frames)),
   hangover_ms=float(data.get("hangover_ms",default.hangover_ms)),
   min_speech_ms=float(data.get("min_speech_ms",default.min_speech_ms)),
   floor_adaptation=float(data.get("floor_adaptation",default.floor_adaptation)),
   initial_floor_db=float(data.get("initial_floor_db",default.initial_floor_db)),
  )


def _decibels(frame:np.ndarray)->float:
 return float(20.0*np.log10(np.sqrt(np.mean(np.square(frame)))+_EPS))


class EnergyVad:
 """音量Baseの発話端点検出"""

 def __init__(self,sample_rate:int,config:Optional[VadConfig]=None):
  self.sample_rate=sample_rate
  self.config=config or VadConfig()
  self.frame_size=int(sample_rate*self.config.frame_ms/1000.0)
  if self.frame_size<=0:
   raise ValueError("frame_ms is too short for the sample rate")
  self._hangover_frames=int(self.config.hangover_ms/self.config.frame_ms)
  self._min_speech_frames=int(self.config.min_speech_ms/self.config.frame_ms)
  self.reset()

 def reset(self)->None:
  """状態と雑音Floorを初期化する"""
  self._floor_db=self.config.initial_floor_db
  self._speaking=False
  self._above=0
  self._silence=0
  self._speech_frames=0

 @property
 def speaking(self)->bool:
  return self._speaking

 @property
 def floor_db(self)->float:
  return self._floor_db

 def push(self,frame:np.ndarray)->VadEvent:
  """1 Frameを与え、状態遷移があればEventを返す"""
  if frame.size!=self.frame_size:
   raise ValueError(f"frame size must be {self.frame_size}, got {frame.size}")
  level=_decibels(frame)
  if not self._speaking:
   rate=self.config.floor_adaptation
   self._floor_db=(1.0-rate)*self._floor_db+rate*level
  if level>self._floor_db+self.config.start_offset_db:
   self._above+=1
   self._silence=0
  else:
   self._above=0
   self._silence+=1
  if self._speaking:
   self._speech_frames+=1
   quiet=level<self._floor_db+self.config.end_offset_db
   if quiet and self._silence>=self._hangover_frames and self._speech_frames>=self._min_speech_frames:
    self._speaking=False
    self._above=0
    return VadEvent.SPEECH_END
   return VadEvent.NONE

  if self._above>=self.config.start_frames:
   self._speaking=True
   self._speech_frames=self._above
   return VadEvent.SPEECH_START
  return VadEvent.NONE
