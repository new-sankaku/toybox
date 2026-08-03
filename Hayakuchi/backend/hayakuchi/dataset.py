"""Phrase定義とEvaluation Datasetの読み込み

Manifestは1行1SampleのJSONL。正解Mora列はPhrase定義から解決するため、
Manifest側にKanaを重複保持しない。
"""
import json
from dataclasses import dataclass,field
from pathlib import Path
from typing import Dict,List,Optional

from .mora import to_mora

LABEL_OK="ok"
LABEL_NG="ng"
_LABELS=frozenset((LABEL_OK,LABEL_NG))


@dataclass(frozen=True)
class Phrase:
 id:str
 display:str
 kana:str
 difficulty:int
 tags:List[str]=field(default_factory=list)

 @property
 def mora(self)->List[str]:
  return to_mora(self.kana)


@dataclass(frozen=True)
class Sample:
 id:str
 audio:Path
 phrase_id:str
 label:str
 speaker_id:str
 error_mora_index:Optional[int]=None
 note:str=""


def load_phrases(path:Path)->Dict[str,Phrase]:
 """Phrase定義JSONを読み込む"""
 with path.open("r",encoding="utf-8") as handle:
  payload=json.load(handle)
 phrases:Dict[str,Phrase]={}
 for entry in payload["phrases"]:
  phrase=Phrase(
   id=str(entry["id"]),
   display=str(entry["display"]),
   kana=str(entry["kana"]),
   difficulty=int(entry["difficulty"]),
   tags=list(entry.get("tags",[])),
  )
  if not phrase.mora:
   raise ValueError(f"phrase has no mora: {phrase.id}")
  if phrase.id in phrases:
   raise ValueError(f"duplicated phrase id: {phrase.id}")
  phrases[phrase.id]=phrase
 return phrases


def load_manifest(path:Path,phrases:Dict[str,Phrase],audio_root:Optional[Path]=None)->List[Sample]:
 """Evaluation ManifestのJSONLを読み込み、Phrase定義との整合を検証する"""
 audio_root=audio_root or path.parent
 samples:List[Sample]=[]
 seen=set()
 with path.open("r",encoding="utf-8") as handle:
  for line_number,line in enumerate(handle,start=1):
   line=line.strip()
   if not line:
    continue
   entry=json.loads(line)
   sample_id=str(entry["id"])
   if sample_id in seen:
    raise ValueError(f"duplicated sample id: {sample_id} (line {line_number})")
   seen.add(sample_id)
   label=str(entry["label"])
   if label not in _LABELS:
    raise ValueError(f"invalid label: {label} (line {line_number})")
   phrase_id=str(entry["phrase_id"])
   if phrase_id not in phrases:
    raise ValueError(f"unknown phrase id: {phrase_id} (line {line_number})")
   error_index=entry.get("error_mora_index")
   if error_index is not None:
    error_index=int(error_index)
    if not 0<=error_index<len(phrases[phrase_id].mora):
     raise ValueError(f"error_mora_index out of range: {sample_id} (line {line_number})")
   if label==LABEL_OK and error_index is not None:
    raise ValueError(f"ok sample must not have error_mora_index: {sample_id} (line {line_number})")
   audio=Path(entry["audio"])
   if not audio.is_absolute():
    audio=audio_root/audio
   samples.append(Sample(
    id=sample_id,
    audio=audio,
    phrase_id=phrase_id,
    label=label,
    speaker_id=str(entry.get("speaker_id","unknown")),
    error_mora_index=error_index,
    note=str(entry.get("note","")),
   ))
 if not samples:
  raise ValueError(f"manifest has no sample: {path}")
 return samples


def missing_audio(samples:List[Sample])->List[Sample]:
 """音声Fileが存在しないSampleを列挙する"""
 return [sample for sample in samples if not sample.audio.exists()]
