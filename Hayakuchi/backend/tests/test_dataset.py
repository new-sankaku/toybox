import json
from pathlib import Path

import pytest

from hayakuchi.dataset import load_manifest,load_phrases

_PHRASES=Path(__file__).resolve().parent.parent/"data"/"phrases.json"


def _write_manifest(tmp_path:Path,entries)->Path:
 path=tmp_path/"manifest.jsonl"
 with path.open("w",encoding="utf-8") as handle:
  for entry in entries:
   handle.write(json.dumps(entry,ensure_ascii=False)+"\n")
 return path


def _entry(**overrides):
 entry={
  "id":"s01__nama_mugi__ok01",
  "audio":"wav/s01__nama_mugi__ok01.wav",
  "phrase_id":"nama_mugi",
  "label":"ok",
  "speaker_id":"s01",
 }
 entry.update(overrides)
 return entry


def test_phrases_are_loaded_with_mora():
 phrases=load_phrases(_PHRASES)
 assert "nama_mugi" in phrases
 assert phrases["nama_mugi"].mora[0]=="ナ"
 assert all(phrase.mora for phrase in phrases.values())


def test_manifest_resolves_audio_path(tmp_path):
 phrases=load_phrases(_PHRASES)
 manifest=_write_manifest(tmp_path,[_entry()])
 samples=load_manifest(manifest,phrases,tmp_path)
 assert samples[0].audio==tmp_path/"wav"/"s01__nama_mugi__ok01.wav"


def test_unknown_phrase_id_raises(tmp_path):
 phrases=load_phrases(_PHRASES)
 manifest=_write_manifest(tmp_path,[_entry(phrase_id="missing")])
 with pytest.raises(ValueError):
  load_manifest(manifest,phrases,tmp_path)


def test_invalid_label_raises(tmp_path):
 phrases=load_phrases(_PHRASES)
 manifest=_write_manifest(tmp_path,[_entry(label="maybe")])
 with pytest.raises(ValueError):
  load_manifest(manifest,phrases,tmp_path)


def test_duplicated_sample_id_raises(tmp_path):
 phrases=load_phrases(_PHRASES)
 manifest=_write_manifest(tmp_path,[_entry(),_entry()])
 with pytest.raises(ValueError):
  load_manifest(manifest,phrases,tmp_path)


def test_error_index_out_of_range_raises(tmp_path):
 phrases=load_phrases(_PHRASES)
 manifest=_write_manifest(tmp_path,[_entry(label="ng",error_mora_index=999)])
 with pytest.raises(ValueError):
  load_manifest(manifest,phrases,tmp_path)


def test_ok_sample_with_error_index_raises(tmp_path):
 phrases=load_phrases(_PHRASES)
 manifest=_write_manifest(tmp_path,[_entry(error_mora_index=2)])
 with pytest.raises(ValueError):
  load_manifest(manifest,phrases,tmp_path)


def test_empty_manifest_raises(tmp_path):
 phrases=load_phrases(_PHRASES)
 manifest=_write_manifest(tmp_path,[])
 with pytest.raises(ValueError):
  load_manifest(manifest,phrases,tmp_path)
