"""Benchmark設定の読み込み

Model IDやDevice、閾値、収録条件はすべてこのConfig経由で与える。
Config内の相対PathはBackend rootを基準に解決する。
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Dict,List

import yaml

from .conditions import Condition,load_conditions
from .scoring import ScoringConfig


@dataclass
class MetricsConfig:
 target_far:float
 localization_tolerance:int
 latency_percentiles:List[int]


@dataclass
class BenchmarkConfig:
 base_dir:Path
 phrases_path:Path
 manifest_path:Path
 audio_root:Path
 asset_root:Path
 output_dir:Path
 log_dir:Path
 scoring:ScoringConfig
 metrics:MetricsConfig
 conditions:List[Condition]
 engines:List[Dict]
 include_samples:bool

 def resolve(self,value:str)->Path:
  """Backend rootを基準に相対Pathを解決する"""
  path=Path(value)
  return path if path.is_absolute() else self.base_dir/path


def load_config(path:Path)->BenchmarkConfig:
 """Benchmark Config YAMLを読み込む"""
 path=path.resolve()
 base_dir=path.parent.parent
 with path.open("r",encoding="utf-8") as handle:
  payload=yaml.safe_load(handle)
 paths=payload["paths"]
 metrics=payload["metrics"]

 def _resolve(value:str)->Path:
  candidate=Path(value)
  return candidate if candidate.is_absolute() else base_dir/candidate

 engines=payload["engines"]
 if not engines:
  raise ValueError("no engine is defined in config")
 return BenchmarkConfig(
  base_dir=base_dir,
  phrases_path=_resolve(paths["phrases"]),
  manifest_path=_resolve(paths["manifest"]),
  audio_root=_resolve(paths["audio_root"]),
  asset_root=_resolve(paths["asset_root"]),
  output_dir=_resolve(paths["output_dir"]),
  log_dir=_resolve(paths["log_dir"]),
  scoring=ScoringConfig.from_dict(payload.get("scoring")),
  metrics=MetricsConfig(
   target_far=float(metrics["target_far"]),
   localization_tolerance=int(metrics["localization_tolerance"]),
   latency_percentiles=[int(item) for item in metrics["latency_percentiles"]],
  ),
  conditions=load_conditions(payload["conditions"]),
  engines=engines,
  include_samples=bool(payload.get("report",{}).get("include_samples",True)),
 )
