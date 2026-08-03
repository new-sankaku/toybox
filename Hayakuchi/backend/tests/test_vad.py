import numpy as np
import pytest

from hayakuchi.vad import EnergyVad,VadConfig,VadEvent

_SAMPLE_RATE=16000


def _config(**overrides)->VadConfig:
 base={"frame_ms":30.0,"start_frames":3,"hangover_ms":150.0,"min_speech_ms":120.0}
 base.update(overrides)
 return VadConfig.from_dict(base)


def _feed(vad:EnergyVad,frame:np.ndarray,count:int):
 events=[]
 for _ in range(count):
  events.append(vad.push(frame))
 return events


def test_silence_produces_no_event():
 vad=EnergyVad(_SAMPLE_RATE,_config())
 silence=np.zeros(vad.frame_size,dtype=np.float32)
 assert set(_feed(vad,silence,20))=={VadEvent.NONE}
 assert not vad.speaking


def test_speech_start_is_detected():
 vad=EnergyVad(_SAMPLE_RATE,_config())
 silence=np.zeros(vad.frame_size,dtype=np.float32)
 speech=np.full(vad.frame_size,0.3,dtype=np.float32)
 _feed(vad,silence,10)
 events=_feed(vad,speech,5)
 assert VadEvent.SPEECH_START in events
 assert vad.speaking


def test_speech_end_is_detected_after_hangover():
 vad=EnergyVad(_SAMPLE_RATE,_config())
 silence=np.zeros(vad.frame_size,dtype=np.float32)
 speech=np.full(vad.frame_size,0.3,dtype=np.float32)
 _feed(vad,silence,10)
 _feed(vad,speech,10)
 events=_feed(vad,silence,20)
 assert VadEvent.SPEECH_END in events
 assert not vad.speaking


def test_short_burst_does_not_end_before_min_speech():
 vad=EnergyVad(_SAMPLE_RATE,_config(min_speech_ms=600.0))
 silence=np.zeros(vad.frame_size,dtype=np.float32)
 speech=np.full(vad.frame_size,0.3,dtype=np.float32)
 _feed(vad,silence,10)
 _feed(vad,speech,4)
 events=_feed(vad,silence,8)
 assert VadEvent.SPEECH_END not in events


def test_noise_floor_adapts_to_loud_room():
 quiet=EnergyVad(_SAMPLE_RATE,_config())
 noisy=EnergyVad(_SAMPLE_RATE,_config())
 rng=np.random.default_rng(0)
 _feed(quiet,(rng.standard_normal(quiet.frame_size)*0.001).astype(np.float32),40)
 _feed(noisy,(rng.standard_normal(noisy.frame_size)*0.05).astype(np.float32),40)
 assert noisy.floor_db>quiet.floor_db


def test_reset_restores_initial_state():
 vad=EnergyVad(_SAMPLE_RATE,_config())
 speech=np.full(vad.frame_size,0.3,dtype=np.float32)
 _feed(vad,speech,5)
 vad.reset()
 assert not vad.speaking
 assert vad.floor_db==vad.config.initial_floor_db


def test_wrong_frame_size_raises():
 vad=EnergyVad(_SAMPLE_RATE,_config())
 with pytest.raises(ValueError):
  vad.push(np.zeros(vad.frame_size+1,dtype=np.float32))
