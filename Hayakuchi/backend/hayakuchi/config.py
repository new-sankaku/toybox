"""Benchmark設定の読み込み

Model IDやDevice、閾値、収録条件はすべてこのConfig経由で与える。
Config内の相対PathはBackend rootを基準に解決する。
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Dict,List

import yaml

from .conditions import Condition,load_conditions
from .game import GameConfig
from .profile import LevelRules
from .score import ScoreRules
from .scoring import ScoringConfig
from .vad import VadConfig


@dataclass
class GameServerConfig:
 base_dir:Path
 phrases_path:Path
 web_root:Path
 log_dir:Path
 host:str
 port:int
 engine:Dict
 source:Dict
 profile_path:Path
 game:"GameConfig"


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


def load_game_config(path:Path)->GameServerConfig:
 """Game Server Config YAMLを読み込む"""
 path=path.resolve()
 base_dir=path.parent.parent
 with path.open("r",encoding="utf-8") as handle:
  payload=yaml.safe_load(handle)

 def _resolve(value:str)->Path:
  candidate=Path(value)
  return candidate if candidate.is_absolute() else base_dir/candidate

 paths=payload["paths"]
 server=payload["server"]
 game=payload["game"]
 audio=payload["audio"]
 grades=game["grades"]
 if not grades:
  raise ValueError("no grade is defined in config")
 return GameServerConfig(
  base_dir=base_dir,
  phrases_path=_resolve(paths["phrases"]),
  web_root=_resolve(paths["web_root"]),
  profile_path=_resolve(paths["profile"]),
  log_dir=_resolve(paths["log_dir"]),
  host=str(server["host"]),
  port=int(server["port"]),
  engine=payload["engine"],
  source=audio["source"],
  game=GameConfig(
   sample_rate=int(audio["sample_rate"]),
   inference_interval_ms=float(game["inference_interval_ms"]),
   level_interval_ms=float(game["level_interval_ms"]),
   pass_accuracy=float(game["pass_accuracy"]),
   grades={str(key):float(value) for key,value in grades.items()},
   max_utterance_ms=float(game["max_utterance_ms"]),
   error_margin_mora=int(game["error_margin_mora"]),
   hesitation_ms=float(game["hesitation_ms"]),
   completion_ratio=float(game["completion_ratio"]),
   restart_cost=float(game["restart_cost"]),
   restart_skip_threshold=int(game["restart_skip_threshold"]),
   result_hold_ms=float(game["result_hold_ms"]),
   auto_next=bool(game["auto_next"]),
   scoring=ScoringConfig.from_dict(payload.get("scoring")),
   vad=VadConfig.from_dict(payload.get("vad")),
   score=ScoreRules.from_dict(payload.get("score")),
   levels=LevelRules.from_dict(payload.get("levels")),
  ),
 )
