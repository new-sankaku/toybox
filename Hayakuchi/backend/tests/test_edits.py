import numpy as np
import pytest

from hayakuchi.edits import Edit,apply_edit,load_edits

_SAMPLE_RATE=16000


def _ramp(seconds:float=1.0)->np.ndarray:
 return np.linspace(0.0,1.0,int(_SAMPLE_RATE*seconds),dtype=np.float32)


def test_cut_removes_requested_duration():
 original=_ramp()
 edit=Edit(id="cut",label="cut",kind="cut",position=0.5,duration_ms=100.0)
 edited=apply_edit(original,_SAMPLE_RATE,edit)
 assert edited.size==original.size-int(_SAMPLE_RATE*0.1)


def test_repeat_extends_by_requested_duration():
 original=_ramp()
 edit=Edit(id="repeat",label="repeat",kind="repeat",position=0.5,duration_ms=100.0)
 edited=apply_edit(original,_SAMPLE_RATE,edit)
 assert edited.size==original.size+int(_SAMPLE_RATE*0.1)


def test_swap_keeps_length_but_reorders():
 original=_ramp()
 edit=Edit(id="swap",label="swap",kind="swap",position=0.4,duration_ms=100.0)
 edited=apply_edit(original,_SAMPLE_RATE,edit)
 assert edited.size==original.size
 assert not np.array_equal(edited,original)


def test_edit_on_too_short_audio_raises():
 edit=Edit(id="cut",label="cut",kind="cut",position=0.9,duration_ms=500.0)
 with pytest.raises(ValueError):
  apply_edit(_ramp(0.3),_SAMPLE_RATE,edit)


def test_unknown_kind_raises():
 with pytest.raises(ValueError):
  Edit.from_dict({"id":"x","kind":"reverse","position":0.5,"duration_ms":100.0})


def test_position_outside_range_raises():
 with pytest.raises(ValueError):
  Edit.from_dict({"id":"x","kind":"cut","position":1.0,"duration_ms":100.0})


def test_load_edits_requires_entries():
 with pytest.raises(ValueError):
  load_edits([])


def test_load_edits_parses_definitions():
 edits=load_edits([{"id":"cut_40","label":"cut","kind":"cut","position":0.4,"duration_ms":180.0}])
 assert edits[0].kind=="cut"
 assert edits[0].duration_ms==180.0
