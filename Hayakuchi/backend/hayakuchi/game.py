"""Game進行

VADが発話開始を検出したら判定を始め、一定間隔で認識をやり直してMora点灯を送る。
発話終了で確定判定を出す。認識はBlockingのため別Threadへ逃がし、
音声取得のEvent loopを止めない。
"""
import asyncio
import random
import time
from dataclasses import dataclass
from typing import Awaitable,Callable,Dict,List,Optional

import numpy as np
from pydantic import BaseModel

from middleware.logger import get_logger

from .audio_source import AudioSource
from .dataset import Phrase
from .engines.base import UNIT_PHONEME,Engine
from .mora import mora_text
from .phoneme import mora_to_phonemes
from .realtime import ProgressiveJudge,score_to_grade
from .scoring import ScoringConfig
from .vad import EnergyVad,VadConfig,VadEvent

from schemas.events import (
 LevelEvent,
 MoraState,
 Phase,
 PhraseEvent,
 ProgressEvent,
 ResultEvent,
 StateEvent,
)

Publisher=Callable[[BaseModel],Awaitable[None]]


@dataclass
class GameConfig:
 sample_rate:int
 inference_interval_ms:float
 level_interval_ms:float
 pass_accuracy:float
 grades:Dict[str,float]
 max_utterance_ms:float
 error_margin_mora:int
 result_hold_ms:float
 scoring:ScoringConfig
 vad:VadConfig


class GameSession:
 """1台の配信PC上で動くGame進行"""

 def __init__(
  self,
  engine:Engine,
  phrases:Dict[str,Phrase],
  config:GameConfig,
  publish:Publisher,
 ):
  self._engine=engine
  self._phrases=phrases
  self._config=config
  self._publish=publish
  self._logger=get_logger()
  self._phase=Phase.IDLE
  self._phrase:Optional[Phrase]=None
  self._judge:Optional[ProgressiveJudge]=None
  self._buffer:List[np.ndarray]=[]
  self._buffered_samples=0
  self._last_inference=0.0
  self._last_level=0.0
  self._last_result:Optional[ResultEvent]=None
  self._busy=False
  self._progress_task:Optional[asyncio.Task]=None
  self._hold_task:Optional[asyncio.Task]=None

 @property
 def phase(self)->Phase:
  return self._phase

 @property
 def phrase(self)->Optional[Phrase]:
  return self._phrase

 def snapshot(self)->List[BaseModel]:
  """接続直後のClientへ現在の状態を復元するEvent列"""
  events:List[BaseModel]=[StateEvent(phase=self._phase)]
  if self._phrase is not None:
   events.append(self._phrase_event(self._phrase))
  if self._last_result is not None:
   events.append(self._last_result)
  return events

 @staticmethod
 def _phrase_event(phrase:Phrase)->PhraseEvent:
  return PhraseEvent(
   phrase_id=phrase.id,
   display=phrase.display,
   mora=phrase.mora,
   difficulty=phrase.difficulty,
  )

 def _build_judge(self,phrase:Phrase)->ProgressiveJudge:
  mora=phrase.mora
  if self._engine.output_unit==UNIT_PHONEME:
   reference,origins=mora_to_phonemes(mora)
  else:
   reference,origins=mora,list(range(len(mora)))
  return ProgressiveJudge(
   reference=reference,
   origins=origins,
   mora_count=len(mora),
   config=self._config.scoring,
   error_margin_mora=self._config.error_margin_mora,
  )

 async def select(self,phrase_id:Optional[str]=None)->None:
  """出題する句を決めて待機状態にする"""
  if phrase_id is None:
   phrase_id=random.choice(sorted(self._phrases))
  if phrase_id not in self._phrases:
   raise ValueError(f"unknown phrase id: {phrase_id}")
  self._cancel_hold()
  self._phrase=self._phrases[phrase_id]
  self._judge=self._build_judge(self._phrase)
  self._last_result=None
  self._buffer=[]
  self._buffered_samples=0
  await self._publish(self._phrase_event(self._phrase))
  await self._set_phase(Phase.READY)

 async def override(self,passed:bool)->None:
  """配信者が判定を手動で覆す"""
  if self._last_result is None:
   raise ValueError("no result to override")
  self._last_result=self._last_result.model_copy(
   update={"passed":passed,"overridden":True}
  )
  await self._publish(self._last_result)
  self._logger.info(f"result overridden by operator: passed={passed}")

 def _cancel_hold(self)->None:
  if self._hold_task is not None and not self._hold_task.done():
   self._hold_task.cancel()
  self._hold_task=None

 async def _hold_then_ready(self)->None:
  """結果表示のあと同じ句のまま待機へ戻す

  ここを戻さないと2回目の挑戦ができない。句の変更はselectで行う。
  """
  try:
   await asyncio.sleep(self._config.result_hold_ms/1000.0)
  except asyncio.CancelledError:
   return
  if self._phase==Phase.RESULT:
   await self._set_phase(Phase.READY)

 async def _set_phase(self,phase:Phase)->None:
  self._phase=phase
  await self._publish(StateEvent(phase=phase))

 def _elapsed_ms(self)->float:
  return self._buffered_samples/self._config.sample_rate*1000.0

 def _recognize(self,buffer:List[np.ndarray])->List[str]:
  audio=np.concatenate(buffer)
  result=self._engine.run(audio,self._config.sample_rate,[],"live")
  return result.hypothesis

 def _schedule_progress(self)->None:
  """認識を別Taskへ逃がす

  推論を待つ間もFrameの取り込みを止めないこと。ここを直列にすると
  取り込みが推論速度に律速され、音声が実時間から遅れていく。
  """
  if self._judge is None or self._busy:
   return
  self._busy=True
  self._progress_task=asyncio.create_task(
   self._emit_progress(list(self._buffer),self._elapsed_ms())
  )

 async def _emit_progress(self,buffer:List[np.ndarray],elapsed_ms:float)->None:
  try:
   hypothesis=await asyncio.to_thread(self._recognize,buffer)
   partial=self._judge.update(hypothesis)
   await self._publish(ProgressEvent(
    lit_mora=partial.lit_mora,
    mora_states=[MoraState(state) for state in partial.mora_states],
    first_error_mora=partial.first_error_mora,
    elapsed_ms=elapsed_ms,
   ))
  finally:
   self._busy=False

 async def _finish(self)->None:
  if self._judge is None or self._phrase is None or not self._buffer:
   await self._set_phase(Phase.READY)
   return
  duration_ms=self._elapsed_ms()
  if self._progress_task is not None and not self._progress_task.done():
   await self._progress_task
  hypothesis=await asyncio.to_thread(self._recognize,list(self._buffer))
  result=self._judge.finalize(hypothesis)
  states=self._judge.final_states(result)
  first_error=(
   self._judge.origins[result.error_ref_indices[0]]
   if result.error_ref_indices else None
  )
  event=ResultEvent(
   phrase_id=self._phrase.id,
   passed=result.accuracy>=self._config.pass_accuracy,
   grade=score_to_grade(result.accuracy,self._config.grades),
   accuracy=result.accuracy,
   duration_ms=duration_ms,
   mora_states=[MoraState(state) for state in states],
   first_error_mora=first_error,
   reference=mora_text(self._phrase.mora),
   hypothesis=" ".join(hypothesis),
  )
  self._last_result=event
  self._buffer=[]
  self._buffered_samples=0
  await self._publish(event)
  await self._set_phase(Phase.RESULT)
  self._cancel_hold()
  self._hold_task=asyncio.create_task(self._hold_then_ready())
  self._logger.info(
   f"result: phrase={self._phrase.id} accuracy={result.accuracy:.3f} "
   f"passed={event.passed} duration={duration_ms:.0f}ms"
  )

 async def run(self,source:AudioSource)->None:
  """音声Sourceを消費し続けるMain loop"""
  vad=EnergyVad(self._config.sample_rate,self._config.vad)
  level_interval=self._config.level_interval_ms/1000.0
  inference_interval=self._config.inference_interval_ms/1000.0
  async for frame in source.frames():
   event=vad.push(frame)
   now=time.perf_counter()
   if now-self._last_level>=level_interval:
    self._last_level=now
    await self._publish(LevelEvent(
     level_db=float(20.0*np.log10(np.sqrt(np.mean(np.square(frame)))+1e-10)),
     floor_db=vad.floor_db,
     speaking=vad.speaking,
    ))
   if event==VadEvent.SPEECH_START and self._phase==Phase.READY:
    self._buffer=[frame]
    self._buffered_samples=frame.size
    self._last_inference=now
    await self._set_phase(Phase.LISTENING)
    continue
   if self._phase!=Phase.LISTENING:
    continue
   self._buffer.append(frame)
   self._buffered_samples+=frame.size
   if event==VadEvent.SPEECH_END or self._elapsed_ms()>=self._config.max_utterance_ms:
    await self._finish()
    continue
   if now-self._last_inference>=inference_interval:
    self._last_inference=now
    self._schedule_progress()
