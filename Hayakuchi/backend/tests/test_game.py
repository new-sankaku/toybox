import asyncio
from pathlib import Path
from typing import AsyncIterator,List

import numpy as np
import pytest

from hayakuchi.audio_source import AudioSource
from hayakuchi.dataset import Phrase
from hayakuchi.engines.base import UNIT_PHONEME,Engine,EngineResult
from hayakuchi.game import GameConfig,GameSession
from hayakuchi.mora import to_mora
from hayakuchi.phoneme import mora_to_phonemes
from hayakuchi.profile import LevelRules
from hayakuchi.score import ScoreRules
from hayakuchi.scoring import ScoringConfig
from hayakuchi.vad import VadConfig

_SAMPLE_RATE=16000
_FRAME_MS=30.0
_FRAME=int(_SAMPLE_RATE*_FRAME_MS/1000.0)
_KANA="なまむぎ"
_PHRASE=Phrase(id="p",display="生麦",kana=_KANA,difficulty=1)
_UNITS,_=mora_to_phonemes(to_mora(_KANA))
_LOUD_PER_UNIT=3
_FULL=len(_UNITS)*_LOUD_PER_UNIT+4


class PaceEngine(Engine):
 """発話した長さに比例してPhonemeを返す検証用Engine"""

 def __init__(self):
  super().__init__("pace",{"output_unit":UNIT_PHONEME})
  self._prepared=True

 def recognize(self,samples,sample_rate,reference)->EngineResult:
  loud=int(np.count_nonzero(np.abs(samples)>0.05)//_FRAME)
  count=min(len(_UNITS),loud//_LOUD_PER_UNIT)
  return EngineResult(hypothesis=list(_UNITS[:count]),raw_text="")


class ScriptSource(AudioSource):
 def __init__(self,frames:List[np.ndarray]):
  super().__init__(_SAMPLE_RATE,_FRAME)
  self._frames=frames

 async def frames(self)->AsyncIterator[np.ndarray]:
  for frame in self._frames:
   await asyncio.sleep(0)
   yield frame


def _loud(count:int)->List[np.ndarray]:
 return [np.full(_FRAME,0.3,dtype=np.float32) for _ in range(count)]


def _quiet(count:int)->List[np.ndarray]:
 return [np.zeros(_FRAME,dtype=np.float32) for _ in range(count)]


def _config(**overrides)->GameConfig:
 base=dict(
  sample_rate=_SAMPLE_RATE,
  inference_interval_ms=30.0,
  level_interval_ms=100000.0,
  pass_accuracy=0.9,
  grades={"S":1.0,"A":0.9,"D":0.0},
  max_utterance_ms=60000.0,
  error_margin_mora=0,
  result_hold_ms=100000.0,
  auto_next=False,
  hesitation_ms=600.0,
  completion_ratio=0.85,
  restart_cost=3.0,
  restart_skip_threshold=3,
  waveform_buckets=4,
  time_limit_enabled=False,
  limit_ms_per_mora=260.0,
  limit_minimum_ms=2500.0,
  scoring=ScoringConfig(),
  vad=VadConfig(frame_ms=_FRAME_MS,start_frames=2,hangover_ms=90.0,min_speech_ms=60.0),
  score=ScoreRules(),
  levels=LevelRules(),
 )
 base.update(overrides)
 return GameConfig(**base)


async def _play(frames:List[np.ndarray],tmp_path:Path,**overrides):
 events=[]

 async def publish(event):
  events.append(event)

 session=GameSession(
  PaceEngine(),{"p":_PHRASE},_config(**overrides),publish,tmp_path/"profile.json"
 )
 await session.select("p")
 await session.run(ScriptSource(frames))
 for task in list(asyncio.all_tasks()-{asyncio.current_task()}):
  if not task.done():
   await asyncio.wait_for(task,timeout=2)
 return session,[event for event in events if event.type=="result"]


@pytest.mark.asyncio
async def test_full_utterance_is_judged_as_clear(tmp_path):
 frames=_quiet(6)+_loud(_FULL)+_quiet(10)
 _,results=await _play(frames,tmp_path)
 assert len(results)==1
 assert results[0].passed
 assert not results[0].abandoned
 assert results[0].score>0


@pytest.mark.asyncio
async def test_pause_in_the_middle_is_treated_as_hesitation(tmp_path):
 half=_FULL//2
 frames=_quiet(6)+_loud(half)+_quiet(8)+_loud(_FULL-half)+_quiet(10)
 _,results=await _play(frames,tmp_path)
 assert len(results)==1
 assert results[0].passed
 assert not results[0].abandoned


@pytest.mark.asyncio
async def test_long_silence_while_incomplete_gives_up(tmp_path):
 frames=_quiet(6)+_loud(_LOUD_PER_UNIT*2)+_quiet(40)
 _,results=await _play(frames,tmp_path)
 assert len(results)==1
 assert results[0].abandoned
 assert not results[0].passed
 assert results[0].score==0


@pytest.mark.asyncio
async def test_give_up_command_finishes_the_attempt(tmp_path):
 events=[]

 async def publish(event):
  events.append(event)

 session=GameSession(
  PaceEngine(),{"p":_PHRASE},_config(),publish,tmp_path/"profile.json"
 )
 await session.select("p")
 task=asyncio.create_task(session.run(ScriptSource(_quiet(4)+_loud(200))))
 for _ in range(200):
  await asyncio.sleep(0)
  if session.phase.value=="listening":
   break
 await session.give_up()
 task.cancel()
 results=[event for event in events if event.type=="result"]
 assert results and results[0].abandoned


@pytest.mark.asyncio
async def test_retry_clears_the_pending_result(tmp_path):
 events=[]

 async def publish(event):
  events.append(event)

 session=GameSession(
  PaceEngine(),{"p":_PHRASE},_config(),publish,tmp_path/"profile.json"
 )
 await session.select("p")
 await session.run(ScriptSource(_quiet(6)+_loud(_FULL)+_quiet(10)))
 await session.retry()
 assert session.phase.value=="ready"


@pytest.mark.asyncio
async def test_profile_is_persisted_between_sessions(tmp_path):
 frames=_quiet(6)+_loud(_FULL)+_quiet(10)
 first,_=await _play(frames,tmp_path)
 second,_=await _play(frames,tmp_path)
 events=[event for event in second.snapshot() if event.type=="profile"]
 assert events[0].plays>=2


@pytest.mark.asyncio
async def test_time_limit_scales_with_mora_count(tmp_path):
 events=[]

 async def publish(event):
  events.append(event)

 session=GameSession(
  PaceEngine(),{"p":_PHRASE},
  _config(time_limit_enabled=True,limit_ms_per_mora=300.0,limit_minimum_ms=100.0),
  publish,tmp_path/"profile.json",
 )
 await session.select("p")
 phrase=[event for event in events if event.type=="phrase"][0]
 assert phrase.limit_ms==pytest.approx(len(_PHRASE.mora)*300.0)


@pytest.mark.asyncio
async def test_time_limit_respects_the_minimum(tmp_path):
 events=[]

 async def publish(event):
  events.append(event)

 session=GameSession(
  PaceEngine(),{"p":_PHRASE},
  _config(time_limit_enabled=True,limit_ms_per_mora=1.0,limit_minimum_ms=4000.0),
  publish,tmp_path/"profile.json",
 )
 await session.select("p")
 phrase=[event for event in events if event.type=="phrase"][0]
 assert phrase.limit_ms==4000.0


@pytest.mark.asyncio
async def test_slow_utterance_times_out(tmp_path):
 frames=_quiet(6)+_loud(_FULL)+_quiet(10)
 _,results=await _play(
  frames,tmp_path,time_limit_enabled=True,limit_ms_per_mora=30.0,limit_minimum_ms=200.0
 )
 assert len(results)==1
 assert results[0].timed_out
 assert not results[0].passed
 assert not results[0].abandoned


@pytest.mark.asyncio
async def test_timeout_still_awards_partial_score(tmp_path):
 frames=_quiet(6)+_loud(_FULL)+_quiet(10)
 _,results=await _play(
  frames,tmp_path,time_limit_enabled=True,limit_ms_per_mora=40.0,limit_minimum_ms=300.0
 )
 assert results[0].timed_out
 assert results[0].score>0


@pytest.mark.asyncio
async def test_fast_enough_utterance_is_not_timed_out(tmp_path):
 frames=_quiet(6)+_loud(_FULL)+_quiet(10)
 _,results=await _play(
  frames,tmp_path,time_limit_enabled=True,limit_ms_per_mora=600.0,limit_minimum_ms=2000.0
 )
 assert not results[0].timed_out
 assert results[0].passed


@pytest.mark.asyncio
async def test_disabled_time_limit_reports_no_limit(tmp_path):
 events=[]

 async def publish(event):
  events.append(event)

 session=GameSession(
  PaceEngine(),{"p":_PHRASE},_config(time_limit_enabled=False),publish,tmp_path/"profile.json"
 )
 await session.select("p")
 phrase=[event for event in events if event.type=="phrase"][0]
 assert phrase.limit_ms==0.0
