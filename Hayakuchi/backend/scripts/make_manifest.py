"""収録済み音声からEvaluation Manifestの雛形を生成するScript

想定File名: {speaker_id}__{phrase_id}__{label}{連番}.wav
 例: s01__nama_mugi__ok01.wav / s01__nama_mugi__ng03.wav

error_mora_indexは聴取による注釈が必要なためnullで出力する。
NG Sampleの注釈が埋まるまでLocalization指標は算出されない。

使用方法:
 python scripts/make_manifest.py --audio-dir data/wav --out data/manifest.jsonl
"""
import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(BACKEND_ROOT))

from hayakuchi.audio import read_wav
from hayakuchi.dataset import LABEL_NG,LABEL_OK,load_phrases
from middleware.logger import get_logger,setup_logging

_SEPARATOR="__"
_LABELS=(LABEL_OK,LABEL_NG)


def parse_args()->argparse.Namespace:
 parser=argparse.ArgumentParser(description="build evaluation manifest from recordings")
 parser.add_argument("--audio-dir",required=True)
 parser.add_argument("--out",required=True)
 parser.add_argument("--phrases",default=str(BACKEND_ROOT/"data"/"phrases.json"))
 parser.add_argument("--audio-root",default=str(BACKEND_ROOT/"data"))
 parser.add_argument("--min-sample-rate",type=int,default=16000)
 return parser.parse_args()


def _parse_name(stem:str):
 parts=stem.split(_SEPARATOR)
 if len(parts)!=3:
  raise ValueError(f"unexpected file name: {stem}")
 speaker_id,phrase_id,tail=parts
 for label in _LABELS:
  if tail.startswith(label):
   return speaker_id,phrase_id,label
 raise ValueError(f"label not found in file name: {stem}")


def main()->int:
 args=parse_args()
 setup_logging(log_dir=str(BACKEND_ROOT/"logs"),log_file="make_manifest.log")
 logger=get_logger()
 audio_dir=Path(args.audio_dir)
 audio_root=Path(args.audio_root)
 if not audio_dir.is_dir():
  logger.error(f"audio dir not found: {audio_dir}")
  return 1
 phrases=load_phrases(Path(args.phrases))
 records=[]
 rejected=0
 for path in sorted(audio_dir.glob("*.wav")):
  try:
   speaker_id,phrase_id,label=_parse_name(path.stem)
  except ValueError as error:
   logger.warning(str(error))
   rejected+=1
   continue
  if phrase_id not in phrases:
   logger.warning(f"unknown phrase id: {phrase_id} ({path.name})")
   rejected+=1
   continue
  samples,sample_rate=read_wav(path)
  if sample_rate<args.min_sample_rate:
   logger.warning(f"sample rate too low: {sample_rate}Hz ({path.name})")
   rejected+=1
   continue
  if samples.size==0:
   logger.warning(f"empty audio: {path.name}")
   rejected+=1
   continue
  records.append({
   "id":path.stem,
   "audio":str(path.resolve().relative_to(audio_root.resolve()).as_posix()),
   "phrase_id":phrase_id,
   "label":label,
   "speaker_id":speaker_id,
   "error_mora_index":None,
   "note":"",
  })
 if not records:
  logger.error("no valid recording was found")
  return 1
 out_path=Path(args.out)
 out_path.parent.mkdir(parents=True,exist_ok=True)
 with out_path.open("w",encoding="utf-8") as handle:
  for record in records:
   handle.write(json.dumps(record,ensure_ascii=False)+"\n")
 pending=[record["id"] for record in records if record["label"]==LABEL_NG]
 logger.info(f"manifest written: {out_path} records={len(records)} rejected={rejected}")
 logger.info(f"error_mora_index annotation pending: {len(pending)} sample(s)")
 return 0


if __name__=="__main__":
 sys.exit(main())
