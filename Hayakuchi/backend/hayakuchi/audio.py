"""音声の読み書きとSample rate変換

外部Libraryへの依存を避けるため標準LibraryのwaveとNumPyのみで完結させる。
"""
import wave
from pathlib import Path
from typing import Tuple

import numpy as np

_INT16_SCALE=32768.0
_INT32_SCALE=2147483648.0
_INT8_OFFSET=128.0


def read_wav(path:Path)->Tuple[np.ndarray,int]:
 """WAVを読み込みMono float32 (-1.0..1.0) とSample rateを返す"""
 with wave.open(str(path),"rb") as handle:
  channels=handle.getnchannels()
  width=handle.getsampwidth()
  rate=handle.getframerate()
  frames=handle.readframes(handle.getnframes())
 if width==1:
  data=(np.frombuffer(frames,dtype=np.uint8).astype(np.float32)-_INT8_OFFSET)/_INT8_OFFSET
 elif width==2:
  data=np.frombuffer(frames,dtype="<i2").astype(np.float32)/_INT16_SCALE
 elif width==4:
  data=np.frombuffer(frames,dtype="<i4").astype(np.float32)/_INT32_SCALE
 else:
  raise ValueError(f"unsupported sample width: {width*8}bit ({path})")
 if channels>1:
  data=data.reshape(-1,channels).mean(axis=1)
 return data.astype(np.float32),rate


def write_wav(path:Path,samples:np.ndarray,sample_rate:int)->None:
 """Mono float32をInt16 PCM WAVとして書き出す"""
 path.parent.mkdir(parents=True,exist_ok=True)
 clipped=np.clip(samples,-1.0,1.0)
 pcm=(clipped*(_INT16_SCALE-1)).astype("<i2")
 with wave.open(str(path),"wb") as handle:
  handle.setnchannels(1)
  handle.setsampwidth(2)
  handle.setframerate(sample_rate)
  handle.writeframes(pcm.tobytes())


def resample(samples:np.ndarray,source_rate:int,target_rate:int)->np.ndarray:
 """Fourier法でSample rateを変換する"""
 if source_rate==target_rate or samples.size==0:
  return samples.astype(np.float32)
 target_length=int(round(samples.size*target_rate/source_rate))
 if target_length<=0:
  raise ValueError("resample target length is zero")
 spectrum=np.fft.rfft(samples)
 bins=target_length//2+1
 if bins<=spectrum.size:
  spectrum=spectrum[:bins]
 else:
  spectrum=np.concatenate([spectrum,np.zeros(bins-spectrum.size,dtype=spectrum.dtype)])
 resampled=np.fft.irfft(spectrum,n=target_length)*(target_length/samples.size)
 return resampled.astype(np.float32)


def duration_seconds(samples:np.ndarray,sample_rate:int)->float:
 """音声長を秒で返す"""
 return float(samples.size)/float(sample_rate)
