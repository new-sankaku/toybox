"""判定Score算出

Engineの出力Mora列を正解Mora列と比較し、Game側が使うScoreと誤り位置を得る。
二値判定ではなく連続値のAccuracyを返すことで、閾値をあとから較正できるようにする。
"""
from dataclasses import dataclass,field
from typing import Dict,List,Optional,Sequence

from .alignment import DELETE,INSERT,MATCH,SUBSTITUTE,AlignOp,align


@dataclass
class ScoringConfig:
 substitution_cost:float=1.0
 deletion_cost:float=1.0
 insertion_cost:float=1.0

 @classmethod
 def from_dict(cls,data:Optional[Dict])->"ScoringConfig":
  data=data or {}
  return cls(
   substitution_cost=float(data.get("substitution_cost",1.0)),
   deletion_cost=float(data.get("deletion_cost",1.0)),
   insertion_cost=float(data.get("insertion_cost",1.0)),
  )


@dataclass
class Judgement:
 accuracy:float
 distance:float
 exact_match:bool
 error_ref_indices:List[int]=field(default_factory=list)
 first_error_index:Optional[int]=None
 ops:List[AlignOp]=field(default_factory=list)


def judge(
 reference:Sequence[str],
 hypothesis:Sequence[str],
 config:Optional[ScoringConfig]=None,
)->Judgement:
 """正解Mora列に対する認識結果のAccuracyと誤りMora位置を算出する"""
 config=config or ScoringConfig()
 if not reference:
  raise ValueError("reference mora sequence is empty")
 result=align(
  reference,
  hypothesis,
  substitution_cost=config.substitution_cost,
  deletion_cost=config.deletion_cost,
  insertion_cost=config.insertion_cost,
 )
 error_indices:List[int]=[]
 pending_ref_index=0
 for op in result.ops:
  if op.op==MATCH:
   pending_ref_index=op.ref_index+1
   continue
  if op.op in (SUBSTITUTE,DELETE):
   error_indices.append(op.ref_index)
   pending_ref_index=op.ref_index+1
   continue
  if op.op==INSERT:
   error_indices.append(min(pending_ref_index,len(reference)-1))
 error_indices=sorted(set(error_indices))
 accuracy=1.0-result.distance/len(reference)
 accuracy=min(1.0,max(0.0,accuracy))
 return Judgement(
  accuracy=accuracy,
  distance=result.distance,
  exact_match=list(reference)==list(hypothesis),
  error_ref_indices=error_indices,
  first_error_index=error_indices[0] if error_indices else None,
  ops=result.ops,
 )
