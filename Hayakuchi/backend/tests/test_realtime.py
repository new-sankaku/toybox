import pytest

from hayakuchi.alignment import align_prefix
from hayakuchi.mora import to_mora
from hayakuchi.phoneme import mora_to_phonemes
from hayakuchi.realtime import (
 STATE_ERROR,
 STATE_OK,
 STATE_PENDING,
 ProgressiveJudge,
 score_to_grade,
)

_GRADES={"S":1.0,"A":0.95,"B":0.85,"C":0.7,"D":0.0}


def _judge(text:str)->ProgressiveJudge:
 mora=to_mora(text)
 reference,origins=mora_to_phonemes(mora)
 return ProgressiveJudge(reference=reference,origins=origins,mora_count=len(mora))


def test_prefix_alignment_ignores_unspoken_tail():
 result=align_prefix(["a","b","c","d"],["a","b"])
 assert result.distance==0.0
 assert result.consumed==2


def test_prefix_alignment_counts_error_inside_prefix():
 result=align_prefix(["a","b","c","d"],["a","x"])
 assert result.distance==1.0
 assert result.consumed==2


def test_empty_hypothesis_consumes_nothing():
 result=align_prefix(["a","b","c"],[])
 assert result.consumed==0
 assert result.distance==0.0


def test_progress_lights_mora_in_order():
 judge=_judge("なまむぎ")
 partial=judge.update(["n","a","m","a"])
 assert partial.lit_mora==2
 assert partial.mora_states[:2]==[STATE_OK,STATE_OK]
 assert partial.mora_states[2:]==[STATE_PENDING,STATE_PENDING]


def test_progress_marks_error_where_it_breaks():
 judge=_judge("なまむぎ")
 judge.error_margin_mora=0
 partial=judge.update(["n","a","m","a","n","u"])
 assert partial.first_error_mora==2
 assert partial.mora_states[2]==STATE_ERROR


def test_progress_is_empty_before_any_speech():
 judge=_judge("なまむぎ")
 partial=judge.update([])
 assert partial.lit_mora==0
 assert set(partial.mora_states)=={STATE_PENDING}


def test_partial_mora_is_not_lit_until_complete():
 judge=_judge("きゃく")
 partial=judge.update(["ky"])
 assert partial.mora_states[0]==STATE_PENDING


def test_finalize_matches_full_utterance():
 judge=_judge("なまむぎ")
 reference,_=mora_to_phonemes(to_mora("なまむぎ"))
 result=judge.finalize(reference)
 assert result.accuracy==1.0
 assert judge.final_states(result)==[STATE_OK]*4


def test_final_states_mark_error_mora():
 judge=_judge("なまむぎ")
 hypothesis,_=mora_to_phonemes(to_mora("なまむに"))
 result=judge.finalize(hypothesis)
 states=judge.final_states(result)
 assert states[3]==STATE_ERROR
 assert states[:3]==[STATE_OK]*3


def test_progress_survives_devoiced_normalization_case():
 judge=_judge("ますか")
 partial=judge.update(["m","a","s","u"])
 assert partial.lit_mora==2
 assert partial.first_error_mora is None


def test_mismatched_origins_raise():
 with pytest.raises(ValueError):
  ProgressiveJudge(reference=["a","b"],origins=[0],mora_count=1)


def test_grade_boundaries():
 assert score_to_grade(1.0,_GRADES)=="S"
 assert score_to_grade(0.96,_GRADES)=="A"
 assert score_to_grade(0.86,_GRADES)=="B"
 assert score_to_grade(0.0,_GRADES)=="D"


def test_error_near_the_leading_edge_is_held_back():
 judge=_judge("なまむぎなまごめ")
 judge.error_margin_mora=2
 partial=judge.update(["n","a","m","a","n","u"])
 assert partial.first_error_mora is None


def test_error_is_shown_once_the_edge_moves_past_it():
 judge=_judge("なまむぎなまごめ")
 judge.error_margin_mora=2
 partial=judge.update(["n","a","m","a","n","u","g","i","n","a","m","a"])
 assert partial.first_error_mora==2
