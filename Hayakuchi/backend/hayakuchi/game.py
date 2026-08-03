"""Game進行

VADが発話開始を検出したら判定を始め、一定間隔で認識をやり直してMora点灯を送る。
発話終了で確定判定を出す。認識はBlockingのため別Threadへ逃がし、
音声取得のEvent loopを止めない。

途中の無音は必ずしも発話終了ではない。まだ言い切っていない段階での無音は
言い淀みとして扱い、判定を確定させずに続きを待つ。無音がさらに続いた場合のみ
ギブアップとして確定する。
"""
import asyncio
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable,Callable,Dict,List,Optional

import numpy as np
from pydantic import BaseModel

from middleware.logger import get_logger

from .audio_source import AudioSource
from .dataset import Phrase
from .engines.base import UNIT_PHONEME,Engine
from .mora import mora_text
from .phoneme import mora_to_phonemes
from .profile import (
 LevelRules,
 apply_result,
 load_profile,
 required_exp,
 save_profile,
 unlocked_difficulty,
)
from .realtime import ProgressiveJudge,max_combo,score_to_grade
from .score import ScoreRules,calculate
from .scoring import ScoringConfig
from .vad import EnergyVad,VadConfig,VadEvent

from schemas.events import (
 LevelEvent,
 MoraState,
 Phase,
 PhraseEvent,
 ProfileEvent,
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
 auto_next:bool
 hesitation_ms:float
 completion_ratio:float
 restart_cost:float
 restart_skip_threshold:int
 scoring:ScoringConfig
 vad:VadConfig
 score:ScoreRules
 levels:LevelRules


class GameSession:
 """1台の配信PC上で動くGame進行"""

 def __init__(
  self,
  engine:Engine,
  phrases:Dict[str,Phrase],
  config:GameConfig,
  publish:Publisher,
  profile_path:Path,
 ):
  self._engine=engine
  self._phrases=phrases
  self._config=config
  self._publish=publish
  self._profile_path=profile_path
  self._profile=load_profile(profile_path)
  self._logger=get_logger()
  self._phase=Phase.IDLE
  self._phrase:Optional[Phrase]=None
  self._judge:Optional[ProgressiveJudge]=None
  self._buffer:List[np.ndarray]=[]
  self._buffered_samples=0
  self._last_inference=0.0
  self._last_level=0.0
  self._last_result:Optional[ResultEvent]=None
  self._streak=0
  self._busy=False
  self._progress_task:Optional[asyncio.Task]=None
  self._hold_task:Optional[asyncio.Task]=None
  self._restarts=0
  self._best_combo=0
  self._silence_started_samples:Optional[int]=None

 @property
 def phase(self)->Phase:
  return self._phase

 def snapshot(self)->List[BaseModel]:
  """接続直後のClientへ現在の状態を復元するEvent列"""
  events:List[BaseModel]=[StateEvent(phase=self._phase),self._profile_event()]
  if self._phrase is not None:
   events.append(self._phrase_event(self._phrase))
  if self._last_result is not None:
   events.append(self._last_result)
  return events

 def _profile_event(self)->ProfileEvent:
  return ProfileEvent(
   level=self._profile.level,
   exp=self._profile.exp,
   exp_to_next=required_exp(self._profile.level,self._config.levels),
   total_score=self._profile.total_score,
   plays=self._profile.plays,
   clears=self._profile.clears,
   unlocked_difficulty=unlocked_difficulty(self._profile.level,self._config.levels),
  )

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
   restart_cost=self._config.restart_cost,
   restart_skip_threshold=self._config.restart_skip_threshold,
  )

 def _pick_phrase(self)->str:
  limit=unlocked_difficulty(self._profile.level,self._config.levels)
  pool=[
   key for key,phrase in sorted(self._phrases.items())
   if phrase.difficulty<=limit and (self._phrase is None or key!=self._phrase.id)
  ]
  if not pool:
   pool=[key for key,phrase in sorted(self._phrases.items()) if phrase.difficulty<=limit]
  if not pool:
   pool=sorted(self._phrases)
  return random.choice(pool)

 async def select(self,phrase_id:Optional[str]=None)->None:
  """出題する句を決めて待機状態にする"""
  self._cancel_hold()
  if phrase_id is None:
   phrase_id=self._pick_phrase()
  if phrase_id not in self._phrases:
   raise ValueError(f"unknown phrase id: {phrase_id}")
  self._phrase=self._phrases[phrase_id]
  self._judge=self._build_judge(self._phrase)
  self._last_result=None
  self._reset_attempt()
  await self._publish(self._phrase_event(self._phrase))
  await self._set_phase(Phase.READY)

 async def retry(self)->None:
  """今の句を最初からやり直す"""
  if self._phrase is None:
   raise ValueError("no phrase to retry")
  self._cancel_hold()
  self._last_result=None
  self._reset_attempt()
  await self._publish(self._phrase_event(self._phrase))
  await self._set_phase(Phase.READY)
  self._logger.info(f"retry: phrase={self._phrase.id}")

 async def give_up(self)->None:
  """挑戦を中断する。発話中なら結果を確定させる"""
  if self._phase!=Phase.LISTENING:
   await self.retry()
   return
  await self._finish(abandoned=True)

 async def override(self,passed:bool)->None:
  """配信者が判定を手動で覆す"""
  if self._last_result is None:
   raise ValueError("no result to override")
  if passed and not self._last_result.passed:
   self._streak+=1
  elif not passed and self._last_result.passed:
   self._streak=0
  self._last_result=self._last_result.model_copy(
   update={"passed":passed,"overridden":True,"streak":self._streak}
  )
  await self._publish(self._last_result)
  self._logger.info(f"result overridden by operator: passed={passed}")

 def _reset_attempt(self)->None:
  self._buffer=[]
  self._buffered_samples=0
  self._restarts=0
  self._best_combo=0
  self._silence_started_samples=None

 def _cancel_hold(self)->None:
  if self._hold_task is not None and not self._hold_task.done():
   self._hold_task.cancel()
  self._hold_task=None

 async def _hold_then_advance(self)->None:
  """結果表示のあと次の挑戦へ移す

  ここを戻さないと2回目の挑戦ができない。
  """
  try:
   await asyncio.sleep(self._config.result_hold_ms/1000.0)
  except asyncio.CancelledError:
   return
  if self._phase!=Phase.RESULT:
   return
  if self._config.auto_next:
   await self.select()
   return
  await self.retry()

 async def _set_phase(self,phase:Phase)->None:
  self._phase=phase
  await self._publish(StateEvent(phase=phase))

 def _elapsed_ms(self)->float:
  return self._buffered_samples/self._config.sample_rate*1000.0

 def _recognize(self,buffer:List[np.ndarray])->List[str]:
  audio=np.concatenate(buffer)
  result=self._engine.run(audio,self._config.sample_rate,[],"live")
  return result.hypothesis

 def _schedule_progress(self,hesitating:bool)->None:
  """認識を別Taskへ逃がす

  推論を待つ間もFrameの取り込みを止めないこと。ここを直列にすると
  取り込みが推論速度に律速され、音声が実時間から遅れていく。
  """
  if self._judge is None or self._busy:
   return
  self._busy=True
  self._progress_task=asyncio.create_task(
   self._emit_progress(list(self._buffer),self._elapsed_ms(),hesitating)
  )

 async def _emit_progress(
  self,buffer:List[np.ndarray],elapsed_ms:float,hesitating:bool
 )->None:
  try:
   hypothesis=await asyncio.to_thread(self._recognize,buffer)
   partial=self._judge.update(hypothesis)
   self._best_combo=max(self._best_combo,max_combo(partial.mora_states))
   await self._publish(ProgressEvent(
    lit_mora=partial.lit_mora,
    mora_states=[MoraState(state) for state in partial.mora_states],
    first_error_mora=partial.first_error_mora,
    combo=partial.combo,
    restarted=partial.restarted,
    hesitating=hesitating,
    elapsed_ms=elapsed_ms,
   ))
  finally:
   self._busy=False

 @property
 def hesitating(self)->bool:
  return self._silence_started_samples is not None

 async def _resolve_pause(self)->None:
  """無音を発話終了と言い淀みのどちらとして扱うかを決める

  進捗Eventは別Taskで遅れて届くため、その結果を待って判断すると
  言い切ったあとの判定が無駄に遅れる。ここで認識をやり直して即断する。
  """
  if self._judge is None or not self._buffer:
   return
  hypothesis=await asyncio.to_thread(self._recognize,list(self._buffer))
  partial=self._judge.update(hypothesis)
  if partial.lit_mora/max(self._judge.mora_count,1)>=self._config.completion_ratio:
   await self._finish(hypothesis=hypothesis)
   return
  self._silence_started_samples=self._buffered_samples

 async def _finish(
  self,abandoned:bool=False,hypothesis:Optional[List[str]]=None
 )->None:
  if self._judge is None or self._phrase is None or not self._buffer:
   await self._set_phase(Phase.READY)
   return
  duration_ms=self._elapsed_ms()
  if self._progress_task is not None and not self._progress_task.done():
   await self._progress_task
  if hypothesis is None:
   hypothesis=await asyncio.to_thread(self._recognize,list(self._buffer))
  result=self._judge.finalize(hypothesis)
  self._restarts+=self._judge.restart_count(hypothesis)
  states=self._judge.final_states(result)
  combo=max_combo(states)
  passed=(not abandoned) and result.accuracy>=self._config.pass_accuracy
  self._streak=self._streak+1 if passed else 0
  breakdown=calculate(
   difficulty=self._phrase.difficulty,
   accuracy=result.accuracy,
   duration_ms=duration_ms,
   mora_count=self._judge.mora_count,
   max_combo=combo,
   streak=self._streak,
   restarts=self._restarts,
   abandoned=abandoned,
   rules=self._config.score,
  )
  gained=apply_result(
   self._profile,self._phrase.id,breakdown.total,passed,self._config.levels
  )
  save_profile(self._profile_path,self._profile)
  first_error=(
   self._judge.origins[result.error_ref_indices[0]]
   if result.error_ref_indices else None
  )
  event=ResultEvent(
   phrase_id=self._phrase.id,
   passed=passed,
   abandoned=abandoned,
   grade=score_to_grade(result.accuracy,self._config.grades),
   accuracy=result.accuracy,
   duration_ms=duration_ms,
   mora_states=[MoraState(state) for state in states],
   first_error_mora=first_error,
   reference=mora_text(self._phrase.mora),
   hypothesis=" ".join(hypothesis),
   streak=self._streak,
   score=breakdown.total,
   breakdown=breakdown.to_dict(),
   max_combo=combo,
   restarts=self._restarts,
   best_score=self._profile.best_scores.get(self._phrase.id,0),
   levels_gained=gained,
  )
  self._last_result=event
  self._reset_attempt()
  await self._publish(event)
  await self._publish(self._profile_event())
  await self._set_phase(Phase.RESULT)
  self._cancel_hold()
  self._hold_task=asyncio.create_task(self._hold_then_advance())
  self._logger.info(
   f"result: phrase={self._phrase.id} accuracy={result.accuracy:.3f} passed={passed} "
   f"abandoned={abandoned} score={breakdown.total} restarts={self._restarts} "
   f"combo={combo} level={self._profile.level}"
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
    self._reset_attempt()
    self._buffer=[frame]
    self._buffered_samples=frame.size
    self._last_inference=now
    await self._set_phase(Phase.LISTENING)
    continue
   if self._phase!=Phase.LISTENING:
    continue
   self._buffer.append(frame)
   self._buffered_samples+=frame.size
   if event==VadEvent.SPEECH_START:
    self._silence_started_samples=None
   elif event==VadEvent.SPEECH_END:
    await self._resolve_pause()
    if self._phase!=Phase.LISTENING:
     continue
   if self._silence_started_samples is not None:
    quiet=self._buffered_samples-self._silence_started_samples
    if quiet/self._config.sample_rate*1000.0>=self._config.hesitation_ms:
     await self._finish(abandoned=True)
     continue
   if self._elapsed_ms()>=self._config.max_utterance_ms:
    await self._finish()
    continue
   if now-self._last_inference>=inference_interval:
    self._last_inference=now
    self._schedule_progress(self._silence_started_samples is not None)
