import numpy as np
import pytest

from hayakuchi.audio import read_wav,resample,write_wav
from hayakuchi.conditions import Condition,apply_condition,load_conditions

_SAMPLE_RATE=16000


def _sine(frequency:float,seconds:float=1.0,sample_rate:int=_SAMPLE_RATE)->np.ndarray:
 time_axis=np.arange(int(sample_rate*seconds),dtype=np.float32)/sample_rate
 return (0.5*np.sin(2.0*np.pi*frequency*time_axis)).astype(np.float32)


def _dominant_frequency(samples:np.ndarray,sample_rate:int)->float:
 spectrum=np.abs(np.fft.rfft(samples*np.hanning(samples.size)))
 return float(np.fft.rfftfreq(samples.size,1.0/sample_rate)[int(np.argmax(spectrum))])


def test_wav_roundtrip_preserves_signal(tmp_path):
 original=_sine(440.0,0.2)
 path=tmp_path/"tone.wav"
 write_wav(path,original,_SAMPLE_RATE)
 loaded,rate=read_wav(path)
 assert rate==_SAMPLE_RATE
 assert loaded.size==original.size
 assert np.max(np.abs(loaded-original))<1e-3


def test_resample_changes_length_and_keeps_frequency():
 original=_sine(440.0,1.0)
 converted=resample(original,_SAMPLE_RATE,8000)
 assert converted.size==8000
 assert abs(_dominant_frequency(converted,8000)-440.0)<5.0


def test_noise_condition_lowers_signal_to_noise_ratio():
 original=_sine(440.0,0.5)
 condition=Condition(id="noise",label="noise",ops=[{"type":"noise","snr_db":10.0}])
 noisy=apply_condition(original,_SAMPLE_RATE,condition,"sample-1")
 residual=noisy-original
 measured=20.0*np.log10(np.sqrt(np.mean(original**2))/np.sqrt(np.mean(residual**2)))
 assert abs(measured-10.0)<1.0


def test_condition_result_is_deterministic():
 original=_sine(440.0,0.3)
 condition=Condition(id="noise",label="noise",ops=[{"type":"noise","snr_db":15.0}])
 first=apply_condition(original,_SAMPLE_RATE,condition,"sample-1")
 second=apply_condition(original,_SAMPLE_RATE,condition,"sample-1")
 other=apply_condition(original,_SAMPLE_RATE,condition,"sample-2")
 assert np.array_equal(first,second)
 assert not np.array_equal(first,other)


def test_pitch_shift_raises_frequency_and_keeps_length():
 original=_sine(220.0,1.0)
 condition=Condition(id="vc",label="vc",ops=[{"type":"pitch_shift","semitones":12.0}])
 shifted=apply_condition(original,_SAMPLE_RATE,condition,"sample-1")
 assert shifted.size==original.size
 assert abs(_dominant_frequency(shifted,_SAMPLE_RATE)-440.0)<15.0


def test_pitch_shift_down_lowers_frequency():
 original=_sine(440.0,1.0)
 condition=Condition(id="vc",label="vc",ops=[{"type":"pitch_shift","semitones":-12.0}])
 shifted=apply_condition(original,_SAMPLE_RATE,condition,"sample-1")
 assert shifted.size==original.size
 assert abs(_dominant_frequency(shifted,_SAMPLE_RATE)-220.0)<15.0


def test_gain_and_clip_are_applied_in_order():
 original=_sine(440.0,0.1)
 condition=Condition(
  id="overdrive",
  label="overdrive",
  ops=[{"type":"gain","db":20.0},{"type":"clip","ceiling":0.9}],
 )
 processed=apply_condition(original,_SAMPLE_RATE,condition,"sample-1")
 assert np.max(np.abs(processed))<=0.9+1e-6
 assert np.mean(np.abs(processed))>np.mean(np.abs(original))


def test_unknown_op_raises():
 condition=Condition(id="bad",label="bad",ops=[{"type":"reverb"}])
 with pytest.raises(ValueError):
  apply_condition(_sine(440.0,0.1),_SAMPLE_RATE,condition,"sample-1")


def test_load_conditions_requires_entries():
 with pytest.raises(ValueError):
  load_conditions([])


def test_waveform_points_keep_both_extremes():
 from hayakuchi.audio import waveform_points
 frame=np.concatenate([np.full(120,-0.6,dtype=np.float32),np.full(120,0.8,dtype=np.float32)])
 points=waveform_points(frame,2)
 assert points==pytest.approx([-0.6,-0.6,0.8,0.8],abs=1e-6)


def test_waveform_points_reject_zero_buckets():
 from hayakuchi.audio import waveform_points
 with pytest.raises(ValueError):
  waveform_points(np.zeros(10,dtype=np.float32),0)


def test_waveform_points_on_empty_frame():
 from hayakuchi.audio import waveform_points
 assert waveform_points(np.zeros(0,dtype=np.float32),4)==[]
