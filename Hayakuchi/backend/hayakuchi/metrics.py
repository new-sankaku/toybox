"""判定Engineの評価指標

Game体験に直結する指標を優先する。
- false_reject_rate: 正しく言えたのにFAILと判定された割合。配信では最も体験を損なう
- lm_correction_rate: 噛んだ音声をEngineが正解文へ「直して」しまった割合。
  Language Model内蔵Modelを失格判定するための指標
- localization_accuracy: 崩れたMora位置を当てられた割合。誤り位置のOverlay表示に必要
"""
from dataclasses import dataclass,field
from typing import Dict,List,Optional,Sequence,Tuple

import numpy as np

_EPS=1e-12


@dataclass
class SampleOutcome:
 sample_id:str
 label:str
 accuracy:float
 exact_match:bool
 predicted_error_index:Optional[int]
 truth_error_index:Optional[int]
 elapsed_ms:float
 audio_seconds:float


@dataclass
class MetricSummary:
 sample_count:int
 ok_count:int
 ng_count:int
 roc_auc:float
 eer:float
 eer_threshold:float
 threshold_at_target_far:float
 false_reject_rate_at_target_far:float
 target_far:float
 lm_correction_rate:float
 localization_accuracy:float
 localization_evaluated:int
 latency_ms:Dict[str,float]=field(default_factory=dict)
 real_time_factor:Dict[str,float]=field(default_factory=dict)

 def to_dict(self)->Dict:
  return {
   "sample_count":self.sample_count,
   "ok_count":self.ok_count,
   "ng_count":self.ng_count,
   "roc_auc":self.roc_auc,
   "eer":self.eer,
   "eer_threshold":self.eer_threshold,
   "threshold_at_target_far":self.threshold_at_target_far,
   "false_reject_rate_at_target_far":self.false_reject_rate_at_target_far,
   "target_far":self.target_far,
   "lm_correction_rate":self.lm_correction_rate,
   "localization_accuracy":self.localization_accuracy,
   "localization_evaluated":self.localization_evaluated,
   "latency_ms":self.latency_ms,
   "real_time_factor":self.real_time_factor,
  }


def _thresholds(scores:np.ndarray)->np.ndarray:
 unique=np.unique(scores)
 step=np.diff(unique).min() if unique.size>1 else 1.0
 return np.concatenate([unique-step/2.0,[unique[-1]+step/2.0]])


def error_rates(scores:np.ndarray,is_ok:np.ndarray,threshold:float)->Tuple[float,float]:
 """閾値におけるFalse Accept RateとFalse Reject Rateを返す"""
 ng_scores=scores[~is_ok]
 ok_scores=scores[is_ok]
 far=float(np.mean(ng_scores>=threshold)) if ng_scores.size else 0.0
 frr=float(np.mean(ok_scores<threshold)) if ok_scores.size else 0.0
 return far,frr


def roc_auc(scores:Sequence[float],is_ok:Sequence[bool])->float:
 """Score高い方をOKとしたROC AUCを算出する"""
 scores=np.asarray(scores,dtype=float)
 is_ok=np.asarray(is_ok,dtype=bool)
 positives=scores[is_ok]
 negatives=scores[~is_ok]
 if positives.size==0 or negatives.size==0:
  return float("nan")
 order=np.argsort(scores,kind="mergesort")
 ranks=np.empty(scores.size,dtype=float)
 sorted_scores=scores[order]
 index=0
 while index<sorted_scores.size:
  end=index
  while end+1<sorted_scores.size and sorted_scores[end+1]==sorted_scores[index]:
   end+=1
  average_rank=(index+end)/2.0+1.0
  ranks[order[index:end+1]]=average_rank
  index=end+1
 rank_sum=float(ranks[is_ok].sum())
 return (rank_sum-positives.size*(positives.size+1)/2.0)/(positives.size*negatives.size)


def equal_error_rate(scores:Sequence[float],is_ok:Sequence[bool])->Tuple[float,float]:
 """FARとFRRが一致する点のEERと閾値を返す"""
 scores=np.asarray(scores,dtype=float)
 is_ok=np.asarray(is_ok,dtype=bool)
 if scores.size==0 or is_ok.all() or (~is_ok).all():
  return float("nan"),float("nan")
 best=(float("inf"),float("nan"),float("nan"))
 for threshold in _thresholds(scores):
  far,frr=error_rates(scores,is_ok,threshold)
  gap=abs(far-frr)
  if gap<best[0]:
   best=(gap,(far+frr)/2.0,float(threshold))
 return best[1],best[2]


def threshold_for_far(scores:Sequence[float],is_ok:Sequence[bool],target_far:float)->Tuple[float,float]:
 """目標FAR以下を満たす閾値と、そのときのFRRを返す"""
 scores=np.asarray(scores,dtype=float)
 is_ok=np.asarray(is_ok,dtype=bool)
 if scores.size==0 or is_ok.all() or (~is_ok).all():
  return float("nan"),float("nan")
 best=(float("nan"),float("inf"))
 for threshold in _thresholds(scores):
  far,frr=error_rates(scores,is_ok,threshold)
  if far<=target_far and frr<best[1]:
   best=(float(threshold),frr)
 return best


def percentiles(values:Sequence[float],requested:Sequence[int])->Dict[str,float]:
 """指定Percentileを算出する"""
 values=np.asarray(values,dtype=float)
 if values.size==0:
  return {f"p{int(item)}":float("nan") for item in requested}
 return {f"p{int(item)}":float(np.percentile(values,item)) for item in requested}


def summarize(
 outcomes:List[SampleOutcome],
 target_far:float,
 localization_tolerance:int,
 latency_percentiles:Sequence[int],
)->MetricSummary:
 """Sample単位の結果を集計する"""
 if not outcomes:
  raise ValueError("no outcome to summarize")
 scores=[item.accuracy for item in outcomes]
 is_ok=[item.label=="ok" for item in outcomes]
 ng_outcomes=[item for item in outcomes if item.label=="ng"]
 eer,eer_threshold=equal_error_rate(scores,is_ok)
 threshold,frr=threshold_for_far(scores,is_ok,target_far)
 corrections=[item.exact_match for item in ng_outcomes]
 localizable=[
  item for item in ng_outcomes
  if item.truth_error_index is not None and item.predicted_error_index is not None
 ]
 hits=[
  item for item in localizable
  if abs(item.predicted_error_index-item.truth_error_index)<=localization_tolerance
 ]
 latencies=[item.elapsed_ms for item in outcomes]
 factors=[
  item.elapsed_ms/1000.0/max(item.audio_seconds,_EPS)
  for item in outcomes if item.audio_seconds>0
 ]
 return MetricSummary(
  sample_count=len(outcomes),
  ok_count=sum(is_ok),
  ng_count=len(ng_outcomes),
  roc_auc=roc_auc(scores,is_ok),
  eer=eer,
  eer_threshold=eer_threshold,
  threshold_at_target_far=threshold,
  false_reject_rate_at_target_far=frr,
  target_far=target_far,
  lm_correction_rate=float(np.mean(corrections)) if corrections else float("nan"),
  localization_accuracy=len(hits)/len(localizable) if localizable else float("nan"),
  localization_evaluated=len(localizable),
  latency_ms=percentiles(latencies,latency_percentiles),
  real_time_factor=percentiles(factors,latency_percentiles),
 )
