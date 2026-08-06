"""Benchmarkの実行

Engine × Condition × Sampleの総当たりで判定を行い、指標を集計する。
音声の読み込みはSample単位で1回に抑え、Conditionの加工は都度適用する。
"""
import time
from dataclasses import asdict
from datetime import datetime,timezone
from typing import Dict,List,Optional,Sequence,Tuple

from middleware.logger import get_logger

from .audio import duration_seconds,read_wav
from .conditions import Condition,apply_condition
from .config import BenchmarkConfig
from .dataset import Phrase,Sample,load_manifest,load_phrases,missing_audio
from .engines import create_engine
from .engines.base import UNIT_PHONEME
from .metrics import SampleOutcome,summarize
from .mora import mora_text
from .phoneme import mora_to_phonemes
from .scoring import judge


def _select(items:Sequence,identifiers:Optional[Sequence[str]],key)->List:
 if not identifiers:
  return list(items)
 wanted=set(identifiers)
 selected=[item for item in items if key(item) in wanted]
 missing=wanted-{key(item) for item in selected}
 if missing:
  raise ValueError(f"unknown identifier: {sorted(missing)}")
 return selected


def reference_units(phrase:Phrase,unit:str)->Tuple[List[str],List[int]]:
 """Engineの出力単位に合わせた正解列と、単位ごとの由来Mora indexを返す"""
 if unit==UNIT_PHONEME:
  return mora_to_phonemes(phrase.mora)
 mora=phrase.mora
 return mora,list(range(len(mora)))


def _sample_payload(
 sample:Sample,
 phrase:Phrase,
 outcome:SampleOutcome,
 raw_text:str,
 hypothesis:List[str],
)->Dict:
 return {
  "sample_id":sample.id,
  "phrase_id":phrase.id,
  "speaker_id":sample.speaker_id,
  "label":sample.label,
  "reference":mora_text(phrase.mora),
  "hypothesis":mora_text(hypothesis),
  "raw_text":raw_text,
  "accuracy":outcome.accuracy,
  "exact_match":outcome.exact_match,
  "truth_error_index":outcome.truth_error_index,
  "predicted_error_index":outcome.predicted_error_index,
  "elapsed_ms":outcome.elapsed_ms,
  "audio_seconds":outcome.audio_seconds,
 }


def run_benchmark(
 config:BenchmarkConfig,
 engine_ids:Optional[Sequence[str]]=None,
 condition_ids:Optional[Sequence[str]]=None,
 limit:Optional[int]=None,
)->Dict:
 """Benchmarkを実行し結果Dictを返す"""
 logger=get_logger()
 phrases=load_phrases(config.phrases_path)
 samples=load_manifest(config.manifest_path,phrases,config.audio_root)
 absent=missing_audio(samples)
 if absent:
  raise FileNotFoundError(
   f"{len(absent)} audio file(s) are missing. first={absent[0].audio}"
  )
 if limit is not None:
  samples=samples[:limit]
 conditions=_select(config.conditions,condition_ids,lambda item:item.id)
 definitions=_select(
  [item for item in config.engines if item.get("enabled",True)],
  engine_ids,
  lambda item:str(item["id"]),
 )
 if not definitions:
  raise ValueError("no enabled engine is selected")
 logger.info(
  f"benchmark start: engines={len(definitions)} conditions={len(conditions)} samples={len(samples)}"
 )
 audio_cache={
  sample.id:read_wav(sample.audio) for sample in samples
 }
 engine_reports=[]
 for definition in definitions:
  engine_reports.append(
   _run_engine(config,definition,conditions,samples,phrases,audio_cache,logger)
  )
 return {
  "generated_at":datetime.now(timezone.utc).isoformat(),
  "manifest":str(config.manifest_path),
  "sample_count":len(samples),
  "metrics_config":asdict(config.metrics),
  "engines":engine_reports,
 }


def _run_engine(
 config:BenchmarkConfig,
 definition:Dict,
 conditions:List[Condition],
 samples:List[Sample],
 phrases:Dict[str,Phrase],
 audio_cache:Dict,
 logger,
)->Dict:
 engine_id=str(definition["id"])
 engine=create_engine(definition)
 started=time.perf_counter()
 engine.prepare()
 load_ms=(time.perf_counter()-started)*1000.0
 unit=engine.output_unit
 logger.info(
  f"engine ready: {engine_id} adapter={definition['adapter']} unit={unit} load_ms={load_ms:.1f}"
 )
 units={phrase_id:reference_units(phrase,unit) for phrase_id,phrase in phrases.items()}
 condition_reports=[]
 all_outcomes:List[SampleOutcome]=[]
 for condition in conditions:
  outcomes:List[SampleOutcome]=[]
  payloads:List[Dict]=[]
  for sample in samples:
   raw_samples,sample_rate=audio_cache[sample.id]
   processed=apply_condition(
    raw_samples,sample_rate,condition,sample.id,config.asset_root
   )
   phrase=phrases[sample.phrase_id]
   reference,origins=units[sample.phrase_id]
   result=engine.run(processed,sample_rate,reference,sample.id)
   judgement=judge(reference,result.hypothesis,config.scoring)
   predicted_index=(
    origins[judgement.first_error_index]
    if judgement.first_error_index is not None else None
   )
   outcome=SampleOutcome(
    sample_id=sample.id,
    label=sample.label,
    accuracy=judgement.accuracy,
    exact_match=judgement.exact_match,
    predicted_error_index=predicted_index,
    truth_error_index=sample.error_mora_index,
    elapsed_ms=result.elapsed_ms,
    audio_seconds=duration_seconds(processed,sample_rate),
   )
   outcomes.append(outcome)
   if config.include_samples:
    payloads.append(
     _sample_payload(sample,phrase,outcome,result.raw_text,result.hypothesis)
    )
  summary=summarize(
   outcomes,
   config.metrics.target_far,
   config.metrics.localization_tolerance,
   config.metrics.latency_percentiles,
  )
  logger.info(
   f"{engine_id}/{condition.id}: auc={summary.roc_auc:.3f} eer={summary.eer:.3f} "
   f"lm_correction={summary.lm_correction_rate:.3f} p95={summary.latency_ms.get('p95',float('nan')):.1f}ms"
  )
  condition_reports.append({
   "condition_id":condition.id,
   "condition_label":condition.label,
   "summary":summary.to_dict(),
   "samples":payloads,
  })
  all_outcomes.extend(outcomes)
 overall=summarize(
  all_outcomes,
  config.metrics.target_far,
  config.metrics.localization_tolerance,
  config.metrics.latency_percentiles,
 )
 return {
  "engine_id":engine_id,
  "adapter":str(definition["adapter"]),
  "params":definition.get("params",{}),
  "load_ms":load_ms,
  "overall":overall.to_dict(),
  "conditions":condition_reports,
 }
