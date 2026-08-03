"""発話中の逐次判定

一定間隔で認識をやり直し、正解列の先頭からどこまで言えたかを求める。
Overlayでは確定したMoraを順に点灯させ、崩れたMoraでその場に印を出す。

MoraのStateは3種類。
- ok: 正しく言えたことが確定した
- error: 崩れたことが確定した
- pending: まだ発話が届いていない

先頭付近のMoraは音声が届き切っていないため一時的に誤りへ倒れる。
Overlayでの点滅を避けるため、先端からerror_margin_mora個は誤り表示を保留する。
確定判定はfinalizeで別途行うため、この保留が最終結果へ影響することはない。
"""
from dataclasses import dataclass,field
from typing import Dict,List,Optional,Sequence

from .alignment import DELETE,MATCH,SUBSTITUTE,align_prefix
from .scoring import Judgement,ScoringConfig,judge

STATE_OK="ok"
STATE_ERROR="error"
STATE_PENDING="pending"


@dataclass
class PartialJudgement:
 consumed_units:int
 distance:float
 mora_states:List[str]
 lit_mora:int
 first_error_mora:Optional[int]=None


@dataclass
class ProgressiveJudge:
 """正解列に対する発話の到達位置と崩れを逐次的に求める"""
 reference:Sequence[str]
 origins:Sequence[int]
 mora_count:int
 config:ScoringConfig=field(default_factory=ScoringConfig)
 error_margin_mora:int=2

 def __post_init__(self):
  if len(self.reference)!=len(self.origins):
   raise ValueError("reference and origins must have the same length")
  if self.mora_count<=0:
   raise ValueError("mora_count must be positive")
  self._mora_end=[0]*self.mora_count
  for unit_index,mora_index in enumerate(self.origins):
   self._mora_end[mora_index]=unit_index+1

 def update(self,hypothesis:Sequence[str])->PartialJudgement:
  """途中経過のMora Stateを返す"""
  result=align_prefix(
   self.reference,
   hypothesis,
   substitution_cost=self.config.substitution_cost,
   deletion_cost=self.config.deletion_cost,
   insertion_cost=self.config.insertion_cost,
  )
  states=[STATE_PENDING]*self.mora_count
  edge=self.origins[result.consumed-1] if result.consumed>0 else -1
  stable=edge-self.error_margin_mora
  for op in result.ops:
   if op.ref_index is None or op.ref_index>=result.consumed:
    continue
   if op.op not in (SUBSTITUTE,DELETE):
    continue
   mora_index=self.origins[op.ref_index]
   if mora_index>stable:
    continue
   states[mora_index]=STATE_ERROR
  for index,end in enumerate(self._mora_end):
   if states[index]==STATE_PENDING and end<=result.consumed:
    states[index]=STATE_OK
  lit=0
  for state in states:
   if state==STATE_PENDING:
    break
   lit+=1
  errors=[index for index,state in enumerate(states) if state==STATE_ERROR]
  return PartialJudgement(
   consumed_units=result.consumed,
   distance=result.distance,
   mora_states=states,
   lit_mora=lit,
   first_error_mora=errors[0] if errors else None,
  )

 def finalize(self,hypothesis:Sequence[str])->Judgement:
  """発話終了後の確定判定を返す"""
  return judge(self.reference,hypothesis,self.config)

 def final_states(self,result:Judgement)->List[str]:
  """確定判定からMora Stateを組み立てる"""
  states=[STATE_OK]*self.mora_count
  for unit_index in result.error_ref_indices:
   states[self.origins[unit_index]]=STATE_ERROR
  return states


def mora_error_indices(origins:Sequence[int],unit_indices:Sequence[int])->List[int]:
 """単位indexの誤り位置をMora indexへ変換する"""
 return sorted({origins[index] for index in unit_indices})


def score_to_grade(accuracy:float,thresholds:Dict[str,float])->str:
 """Accuracyを表示用の段階へ変換する"""
 for grade,minimum in sorted(thresholds.items(),key=lambda item:-item[1]):
  if accuracy>=minimum:
   return grade
 raise ValueError("no grade matches the accuracy; check grade thresholds in config")
