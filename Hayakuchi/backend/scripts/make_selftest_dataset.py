"""Harness検証用Datasetを生成するScript

実収録が揃う前に、Manifest読み込み・Condition適用・指標集計・Report出力までの
経路が通ることを確認するために使う。音声は合成信号であり音響的な意味を持たないため、
ここで得られる数値をEngineの精度として扱ってはならない。

使用方法:
 python scripts/make_selftest_dataset.py --out-dir data/selftest
"""
import argparse
import json
import sys
import zlib
from pathlib import Path

import numpy as np

BACKEND_ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(BACKEND_ROOT))

from hayakuchi.audio import write_wav
from hayakuchi.dataset import LABEL_NG,LABEL_OK,load_phrases
from hayakuchi.mora import mora_text,to_mora
from middleware.logger import get_logger,setup_logging

_SAMPLE_RATE=16000
_MORA_SECONDS=0.15
_BASE_FREQUENCY=140.0
_SUBSTITUTES={"キ":"チ","チ":"キ","シ":"ヒ","ヒ":"シ","ス":"ツ","ツ":"ス","マ":"ナ","ナ":"マ"}
_DEFAULT_SUBSTITUTE="ラ"


def parse_args()->argparse.Namespace:
 parser=argparse.ArgumentParser(description="build self-test dataset for the harness")
 parser.add_argument("--out-dir",default=str(BACKEND_ROOT/"data"/"selftest"))
 parser.add_argument("--phrases",default=str(BACKEND_ROOT/"data"/"phrases.json"))
 parser.add_argument("--speakers",type=int,default=3)
 parser.add_argument("--ok-per-phrase",type=int,default=1)
 parser.add_argument("--ng-per-phrase",type=int,default=1)
 return parser.parse_args()


def _synthesize(mora_count:int,seed:int)->np.ndarray:
 rng=np.random.default_rng(seed)
 length=int(_SAMPLE_RATE*_MORA_SECONDS*mora_count)
 time_axis=np.arange(length,dtype=np.float32)/_SAMPLE_RATE
 frequency=_BASE_FREQUENCY*(1.0+0.2*rng.random())
 envelope=0.5*(1.0-np.cos(2.0*np.pi*np.arange(length)/max(length-1,1)))
 tone=np.sin(2.0*np.pi*frequency*time_axis)+0.3*np.sin(2.0*np.pi*frequency*3.0*time_axis)
 return (0.4*envelope*tone).astype(np.float32)


def _mutate(mora:list,index:int)->list:
 mutated=list(mora)
 head=mutated[index][0]
 mutated[index]=_SUBSTITUTES.get(head,_DEFAULT_SUBSTITUTE)
 return mutated


def main()->int:
 args=parse_args()
 setup_logging(log_dir=str(BACKEND_ROOT/"logs"),log_file="selftest_dataset.log")
 logger=get_logger()
 out_dir=Path(args.out_dir)
 wav_dir=out_dir/"wav"
 phrases=load_phrases(Path(args.phrases))
 records=[]
 transcripts={}
 for speaker_index in range(args.speakers):
  speaker_id=f"s{speaker_index+1:02d}"
  for phrase in phrases.values():
   mora=phrase.mora
   for take in range(args.ok_per_phrase):
    sample_id=f"{speaker_id}__{phrase.id}__{LABEL_OK}{take+1:02d}"
    seed=zlib.crc32(sample_id.encode("utf-8"))
    write_wav(wav_dir/f"{sample_id}.wav",_synthesize(len(mora),seed),_SAMPLE_RATE)
    records.append((sample_id,phrase.id,LABEL_OK,speaker_id,None))
    transcripts[sample_id]=mora_text(mora)
   for take in range(args.ng_per_phrase):
    sample_id=f"{speaker_id}__{phrase.id}__{LABEL_NG}{take+1:02d}"
    seed=zlib.crc32(sample_id.encode("utf-8"))
    error_index=seed%len(mora)
    write_wav(wav_dir/f"{sample_id}.wav",_synthesize(len(mora),seed),_SAMPLE_RATE)
    records.append((sample_id,phrase.id,LABEL_NG,speaker_id,error_index))
    transcripts[sample_id]=mora_text(_mutate(mora,error_index))
 manifest_path=out_dir/"manifest.jsonl"
 with manifest_path.open("w",encoding="utf-8") as handle:
  for sample_id,phrase_id,label,speaker_id,error_index in records:
   handle.write(json.dumps({
    "id":sample_id,
    "audio":f"wav/{sample_id}.wav",
    "phrase_id":phrase_id,
    "label":label,
    "speaker_id":speaker_id,
    "error_mora_index":error_index,
    "note":"synthetic self-test sample",
   },ensure_ascii=False)+"\n")
 transcripts_path=out_dir/"transcripts_human.json"
 with transcripts_path.open("w",encoding="utf-8") as handle:
  json.dump(transcripts,handle,ensure_ascii=False,indent=2,sort_keys=True)
 logger.info(f"selftest dataset written: {out_dir} samples={len(records)}")
 logger.info(f"manifest: {manifest_path}")
 logger.info(f"transcripts: {transcripts_path}")
 return 0


if __name__=="__main__":
 sys.exit(main())
