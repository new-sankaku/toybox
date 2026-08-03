"""収録条件のSimulation

清音源1本から、Noise・BGM回り込み・Voice Changer相当のPitch shift・過大入力を
再現し、条件別に判定精度を比較できるようにする。乱数はSample IDとCondition IDから
決定的に導出するため、実行環境やOSが変わっても同一結果になる。
"""
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict,List,Optional

import numpy as np

from .audio import read_wav,resample

_EPS=1e-12
_WEIGHT_FLOOR=1e-3
_SEMITONES_PER_OCTAVE=12.0


@dataclass(frozen=True)
class Condition:
 id:str
 label:str
 ops:List[Dict]

 @classmethod
 def from_dict(cls,data:Dict)->"Condition":
  return cls(
   id=str(data["id"]),
   label=str(data.get("label",data["id"])),
   ops=list(data.get("ops",[])),
  )


def load_conditions(entries:List[Dict])->List[Condition]:
 """Config記載のCondition定義を読み込む"""
 if not entries:
  raise ValueError("no condition is defined in config")
 return [Condition.from_dict(entry) for entry in entries]


def _seed(sample_id:str,condition_id:str)->int:
 return zlib.crc32(f"{sample_id}|{condition_id}".encode("utf-8"))


def _rms(samples:np.ndarray)->float:
 return float(np.sqrt(np.mean(np.square(samples))+_EPS))


def _apply_snr(signal:np.ndarray,noise:np.ndarray,snr_db:float)->np.ndarray:
 target=_rms(signal)/(10.0**(snr_db/20.0))
 scaled=noise*(target/_rms(noise))
 return signal+scaled


def _white_noise(length:int,rng:np.random.Generator)->np.ndarray:
 return rng.standard_normal(length).astype(np.float32)


def _tile_to_length(source:np.ndarray,length:int,rng:np.random.Generator)->np.ndarray:
 if source.size==0:
  raise ValueError("mix source is empty")
 repeats=int(np.ceil((length+source.size)/source.size))
 tiled=np.tile(source,repeats)
 offset=int(rng.integers(0,source.size))
 return tiled[offset:offset+length]


def _stft(samples:np.ndarray,n_fft:int,hop:int)->np.ndarray:
 window=np.hanning(n_fft+1)[:-1].astype(np.float32)
 padded=np.concatenate([np.zeros(n_fft//2,dtype=np.float32),samples,np.zeros(n_fft,dtype=np.float32)])
 frame_count=1+(padded.size-n_fft)//hop
 frames=np.lib.stride_tricks.as_strided(
  padded,
  shape=(frame_count,n_fft),
  strides=(padded.strides[0]*hop,padded.strides[0]),
 )
 return np.fft.rfft(frames*window,axis=1)


def _istft(spectrum:np.ndarray,n_fft:int,hop:int)->np.ndarray:
 window=np.hanning(n_fft+1)[:-1].astype(np.float32)
 frames=np.fft.irfft(spectrum,n=n_fft,axis=1)*window
 length=(frames.shape[0]-1)*hop+n_fft
 output=np.zeros(length,dtype=np.float32)
 weight=np.zeros(length,dtype=np.float32)
 squared=(window**2).astype(np.float32)
 for index in range(frames.shape[0]):
  start=index*hop
  output[start:start+n_fft]+=frames[index]
  weight[start:start+n_fft]+=squared
 covered=weight>_WEIGHT_FLOOR
 output[covered]/=weight[covered]
 output[~covered]=0.0
 return output[n_fft//2:]


def _time_stretch(samples:np.ndarray,rate:float,n_fft:int=1024,hop:int=256)->np.ndarray:
 """Phase Vocoderで音高を保ったまま長さをrate倍にする"""
 spectrum=_stft(samples,n_fft,hop)
 if spectrum.shape[0]<2:
  return samples
 magnitude=np.abs(spectrum)
 phase=np.angle(spectrum)
 positions=np.arange(0,spectrum.shape[0]-1,1.0/rate)
 lower=np.floor(positions).astype(int)
 fraction=(positions-lower).reshape(-1,1)
 stretched_magnitude=magnitude[lower]*(1.0-fraction)+magnitude[lower+1]*fraction
 expected=2.0*np.pi*hop*np.arange(spectrum.shape[1])/n_fft
 delta=phase[lower+1]-phase[lower]-expected
 delta=delta-2.0*np.pi*np.round(delta/(2.0*np.pi))
 increments=expected+delta
 accumulated=np.empty_like(increments)
 accumulated[0]=phase[lower[0]]
 if increments.shape[0]>1:
  accumulated[1:]=accumulated[0]+np.cumsum(increments[:-1],axis=0)
 return _istft(stretched_magnitude*np.exp(1j*accumulated),n_fft,hop)


def _pitch_shift(samples:np.ndarray,semitones:float,sample_rate:int)->np.ndarray:
 if abs(semitones)<_EPS:
  return samples
 factor=2.0**(semitones/_SEMITONES_PER_OCTAVE)
 stretched=_time_stretch(samples,factor)
 shifted=resample(stretched,int(round(sample_rate*factor)),sample_rate)
 if shifted.size<samples.size:
  return np.concatenate([shifted,np.zeros(samples.size-shifted.size,dtype=np.float32)])
 return shifted[:samples.size]


def apply_condition(
 samples:np.ndarray,
 sample_rate:int,
 condition:Condition,
 sample_id:str,
 asset_root:Optional[Path]=None,
)->np.ndarray:
 """Condition定義に従い音声を加工する"""
 rng=np.random.default_rng(_seed(sample_id,condition.id))
 output=samples.astype(np.float32)
 for op in condition.ops:
  kind=op.get("type")
  if kind=="noise":
   output=_apply_snr(output,_white_noise(output.size,rng),float(op["snr_db"]))
  elif kind=="mix":
   source_path=Path(op["source"])
   if asset_root is not None and not source_path.is_absolute():
    source_path=asset_root/source_path
   source,source_rate=read_wav(source_path)
   source=resample(source,source_rate,sample_rate)
   output=_apply_snr(output,_tile_to_length(source,output.size,rng),float(op["snr_db"]))
  elif kind=="pitch_shift":
   output=_pitch_shift(output,float(op["semitones"]),sample_rate)
  elif kind=="gain":
   output=output*(10.0**(float(op["db"])/20.0))
  elif kind=="clip":
   ceiling=float(op.get("ceiling",1.0))
   output=np.clip(output,-ceiling,ceiling)
  else:
   raise ValueError(f"unknown condition op: {kind} (condition={condition.id})")
 return output.astype(np.float32)
