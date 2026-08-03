"""音声入力

配信者PCのMic入力から直接取得する。配信Streamから取ると platform の配信遅延が
判定経路に乗るため、Local取得であることが応答性の前提になる。

FileSourceは実時間相当の間隔でFrameを流すため、Micが無い環境でも
判定からOverlayまでを同じ経路で検証できる。
"""
import asyncio
from abc import ABC,abstractmethod
from pathlib import Path
from typing import AsyncIterator,Dict,Optional

import numpy as np

from .audio import read_wav,resample


class AudioSource(ABC):
 """Frame単位で音声を供給する"""

 def __init__(self,sample_rate:int,frame_size:int):
  self.sample_rate=sample_rate
  self.frame_size=frame_size

 @abstractmethod
 def frames(self)->AsyncIterator[np.ndarray]:
  """frame_size個のSampleを持つFrameを供給する"""


class FileSource(AudioSource):
 """WAVを実時間相当で流す検証用Source"""

 def __init__(self,sample_rate:int,frame_size:int,path:Path,loop_playback:bool=False,lead_silence_ms:float=500.0):
  super().__init__(sample_rate,frame_size)
  self.path=path
  self.loop_playback=loop_playback
  self.lead_silence_ms=lead_silence_ms

 def _load(self)->np.ndarray:
  samples,rate=read_wav(self.path)
  samples=resample(samples,rate,self.sample_rate)
  lead=np.zeros(int(self.sample_rate*self.lead_silence_ms/1000.0),dtype=np.float32)
  return np.concatenate([lead,samples,lead])

 async def frames(self)->AsyncIterator[np.ndarray]:
  interval=self.frame_size/self.sample_rate
  loop=asyncio.get_running_loop()
  started=loop.time()
  index=0
  while True:
   audio=self._load()
   for start in range(0,audio.size-self.frame_size+1,self.frame_size):
    index+=1
    delay=started+index*interval-loop.time()
    if delay>0:
     await asyncio.sleep(delay)
    yield audio[start:start+self.frame_size]
   if not self.loop_playback:
    return


class MicrophoneSource(AudioSource):
 """配信者PCのMic入力"""

 def __init__(self,sample_rate:int,frame_size:int,device:Optional[str]=None,queue_size:int=64):
  super().__init__(sample_rate,frame_size)
  self.device=device
  self.queue_size=queue_size

 async def frames(self)->AsyncIterator[np.ndarray]:
  try:
   import sounddevice
  except ImportError as error:
   raise RuntimeError(
    "microphone input requires sounddevice. install it with: pip install -r requirements.txt"
   ) from error
  loop=asyncio.get_running_loop()
  queue:asyncio.Queue=asyncio.Queue(maxsize=self.queue_size)

  def callback(indata,frame_count,time_info,status):
   frame=np.asarray(indata,dtype=np.float32).reshape(-1).copy()
   loop.call_soon_threadsafe(_offer,frame)

  def _offer(frame:np.ndarray)->None:
   if queue.full():
    queue.get_nowait()
   queue.put_nowait(frame)

  stream=sounddevice.InputStream(
   samplerate=self.sample_rate,
   blocksize=self.frame_size,
   channels=1,
   dtype="float32",
   device=self.device,
   callback=callback,
  )
  with stream:
   while True:
    yield await queue.get()


def create_source(definition:Dict,sample_rate:int,frame_size:int,base_dir:Path)->AudioSource:
 """Config定義から音声Sourceを生成する"""
 kind=definition.get("type")
 if kind=="microphone":
  return MicrophoneSource(sample_rate,frame_size,device=definition.get("device"))
 if kind=="file":
  path=Path(definition["path"])
  return FileSource(
   sample_rate,
   frame_size,
   path if path.is_absolute() else base_dir/path,
   loop_playback=bool(definition.get("loop",False)),
  )
 raise ValueError(f"unknown audio source type: {kind}. available=['microphone','file']")
