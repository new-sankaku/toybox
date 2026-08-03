"""Language Model補正の検出Script

正解Textを一切必要としない。任意の日本語音声に対し、音声側を改変したうえで
Engine出力が改変前と変化するかだけを見る。変化しないEngineは、実際に鳴っている音では
なく言語的な尤もらしさを返しており、早口言葉の判定には使用できない。

Engine定義はBenchmarkのConfigをそのまま使う。

使用方法:
 python scripts/run_lm_bias_check.py --audio-dir data/probe
"""
import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(BACKEND_ROOT))

import yaml

from hayakuchi.alignment import align
from hayakuchi.audio import duration_seconds,read_wav
from hayakuchi.config import load_config
from hayakuchi.edits import apply_edit,load_edits
from hayakuchi.engines import create_engine
from middleware.logger import get_logger,setup_logging


def parse_args()->argparse.Namespace:
 parser=argparse.ArgumentParser(description="detect language model correction bias")
 parser.add_argument("--config",default=str(BACKEND_ROOT/"config"/"benchmark.yaml"))
 parser.add_argument("--edits",default=str(BACKEND_ROOT/"config"/"edits.yaml"))
 parser.add_argument("--audio-dir",required=True)
 parser.add_argument("--engine",action="append",dest="engines")
 parser.add_argument("--limit",type=int,default=None)
 parser.add_argument("--stem",default="lm_bias")
 return parser.parse_args()


def _load_edits(path:Path):
 with path.open("r",encoding="utf-8") as handle:
  payload=yaml.safe_load(handle)
 return load_edits(payload["edits"])


def _evaluate(engine,edits,clips,logger)->dict:
 reflected=0
 total=0
 details=[]
 for name,samples,sample_rate in clips:
  baseline=engine.run(samples,sample_rate,[],f"{name}:original")
  entry={
   "audio":name,
   "seconds":duration_seconds(samples,sample_rate),
   "original":baseline.raw_text,
   "original_ms":baseline.elapsed_ms,
   "edits":[],
  }
  for edit in edits:
   modified=apply_edit(samples,sample_rate,edit)
   result=engine.run(modified,sample_rate,[],f"{name}:{edit.id}")
   distance=align(baseline.hypothesis,result.hypothesis).distance
   changed=result.hypothesis!=baseline.hypothesis
   reflected+=int(changed)
   total+=1
   entry["edits"].append({
    "edit_id":edit.id,
    "changed":changed,
    "unit_distance":distance,
    "text":result.raw_text,
    "elapsed_ms":result.elapsed_ms,
   })
  details.append(entry)
 rate=reflected/total if total else float("nan")
 logger.info(f"{engine.engine_id}: edit_reflection_rate={rate:.3f} ({reflected}/{total})")
 return {
  "engine_id":engine.engine_id,
  "output_unit":engine.output_unit,
  "edit_reflection_rate":rate,
  "reflected":reflected,
  "total":total,
  "details":details,
 }


def main()->int:
 args=parse_args()
 config=load_config(Path(args.config))
 setup_logging(log_dir=str(config.log_dir),log_file="lm_bias.log")
 logger=get_logger()
 audio_dir=Path(args.audio_dir)
 paths=sorted(audio_dir.glob("*.wav"))
 if args.limit is not None:
  paths=paths[:args.limit]
 if not paths:
  logger.error(f"no wav file found in {audio_dir}")
  return 1
 edits=_load_edits(Path(args.edits))
 clips=[]
 for path in paths:
  samples,sample_rate=read_wav(path)
  clips.append((path.name,samples,sample_rate))
 wanted=set(args.engines) if args.engines else None
 reports=[]
 try:
  for definition in config.engines:
   engine_id=str(definition["id"])
   if wanted is not None and engine_id not in wanted:
    continue
   if wanted is None and not definition.get("enabled",True):
    continue
   engine=create_engine(definition)
   engine.prepare()
   reports.append(_evaluate(engine,edits,clips,logger))
 except Exception:
  logger.exception("lm bias check failed")
  return 1
 if not reports:
  logger.error("no engine was evaluated")
  return 1
 config.output_dir.mkdir(parents=True,exist_ok=True)
 out_path=config.output_dir/f"{args.stem}.json"
 with out_path.open("w",encoding="utf-8") as handle:
  json.dump({"clips":len(clips),"edits":[edit.id for edit in edits],"engines":reports},handle,ensure_ascii=False,indent=2)
 logger.info(f"result written: {out_path}")
 return 0


if __name__=="__main__":
 sys.exit(main())
