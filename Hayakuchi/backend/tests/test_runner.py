import json
from pathlib import Path

import numpy as np
import yaml

from hayakuchi.audio import write_wav
from hayakuchi.config import load_config
from hayakuchi.dataset import load_phrases
from hayakuchi.mora import mora_text
from hayakuchi.report import render_markdown
from hayakuchi.runner import run_benchmark

_BACKEND_ROOT=Path(__file__).resolve().parent.parent
_PHRASES=_BACKEND_ROOT/"data"/"phrases.json"
_SAMPLE_RATE=16000
_PHRASE_IDS=("nama_mugi","tokkyo_kyoka","basu_gasu")


def _tone(seconds:float,seed:int)->np.ndarray:
 rng=np.random.default_rng(seed)
 time_axis=np.arange(int(_SAMPLE_RATE*seconds),dtype=np.float32)/_SAMPLE_RATE
 return (0.4*np.sin(2.0*np.pi*(180.0+40.0*rng.random())*time_axis)).astype(np.float32)


def _build_dataset(root:Path):
 phrases=load_phrases(_PHRASES)
 records=[]
 transcripts={}
 for index,phrase_id in enumerate(_PHRASE_IDS):
  phrase=phrases[phrase_id]
  mora=phrase.mora
  ok_id=f"s01__{phrase_id}__ok01"
  ng_id=f"s01__{phrase_id}__ng01"
  write_wav(root/"wav"/f"{ok_id}.wav",_tone(len(mora)*0.15,index),_SAMPLE_RATE)
  write_wav(root/"wav"/f"{ng_id}.wav",_tone(len(mora)*0.15,index+100),_SAMPLE_RATE)
  error_index=len(mora)//2
  broken=list(mora)
  broken[error_index]="ラ"
  records.append({
   "id":ok_id,
   "audio":f"wav/{ok_id}.wav",
   "phrase_id":phrase_id,
   "label":"ok",
   "speaker_id":"s01",
  })
  records.append({
   "id":ng_id,
   "audio":f"wav/{ng_id}.wav",
   "phrase_id":phrase_id,
   "label":"ng",
   "speaker_id":"s01",
   "error_mora_index":error_index,
  })
  transcripts[ok_id]=mora_text(mora)
  transcripts[ng_id]=mora_text(broken)
 with (root/"manifest.jsonl").open("w",encoding="utf-8") as handle:
  for record in records:
   handle.write(json.dumps(record,ensure_ascii=False)+"\n")
 with (root/"transcripts.json").open("w",encoding="utf-8") as handle:
  json.dump(transcripts,handle,ensure_ascii=False)


def _write_config(base_dir:Path,dataset:Path)->Path:
 config_dir=base_dir/"config"
 config_dir.mkdir(parents=True,exist_ok=True)
 payload={
  "paths":{
   "phrases":str(_PHRASES),
   "manifest":str(dataset/"manifest.jsonl"),
   "audio_root":str(dataset),
   "asset_root":str(dataset),
   "output_dir":str(base_dir/"results"),
   "log_dir":str(base_dir/"logs"),
  },
  "scoring":{"substitution_cost":1.0,"deletion_cost":1.0,"insertion_cost":1.0},
  "metrics":{"target_far":0.05,"localization_tolerance":1,"latency_percentiles":[50,95]},
  "report":{"include_samples":True},
  "conditions":[
   {"id":"clean","label":"清音源","ops":[]},
   {"id":"noise","label":"Noise","ops":[{"type":"noise","snr_db":10.0}]},
  ],
  "engines":[
   {
    "id":"human_replay",
    "adapter":"replay",
    "enabled":True,
    "params":{"transcripts":str(dataset/"transcripts.json")},
   }
  ],
 }
 path=config_dir/"benchmark.yaml"
 with path.open("w",encoding="utf-8") as handle:
  yaml.safe_dump(payload,handle,allow_unicode=True)
 return path


def test_benchmark_runs_end_to_end(tmp_path):
 dataset=tmp_path/"dataset"
 dataset.mkdir()
 _build_dataset(dataset)
 config=load_config(_write_config(tmp_path/"backend",dataset))
 result=run_benchmark(config)
 assert result["sample_count"]==len(_PHRASE_IDS)*2
 engine=result["engines"][0]
 assert engine["engine_id"]=="human_replay"
 assert len(engine["conditions"])==2
 overall=engine["overall"]
 assert overall["roc_auc"]==1.0
 assert overall["eer"]==0.0
 assert overall["lm_correction_rate"]==0.0
 assert overall["localization_accuracy"]==1.0
 assert overall["latency_ms"]["p95"]>=0.0


def test_engine_and_condition_can_be_filtered(tmp_path):
 dataset=tmp_path/"dataset"
 dataset.mkdir()
 _build_dataset(dataset)
 config=load_config(_write_config(tmp_path/"backend",dataset))
 result=run_benchmark(config,engine_ids=["human_replay"],condition_ids=["clean"],limit=4)
 assert result["sample_count"]==4
 assert len(result["engines"][0]["conditions"])==1


def test_report_contains_engine_row(tmp_path):
 dataset=tmp_path/"dataset"
 dataset.mkdir()
 _build_dataset(dataset)
 config=load_config(_write_config(tmp_path/"backend",dataset))
 markdown=render_markdown(run_benchmark(config))
 assert "human_replay" in markdown
 assert "LM補正率" in markdown
