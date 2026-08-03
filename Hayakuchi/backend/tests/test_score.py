import pytest

from hayakuchi.profile import (
 LevelRules,
 Profile,
 apply_result,
 load_profile,
 required_exp,
 save_profile,
 unlocked_difficulty,
)
from hayakuchi.score import ScoreRules,calculate

_RULES=ScoreRules()
_LEVELS=LevelRules()


def _score(**overrides)->int:
 base=dict(
  difficulty=3,accuracy=1.0,duration_ms=2000.0,mora_count=13,
  max_combo=13,streak=0,restarts=0,abandoned=False,rules=_RULES,
 )
 base.update(overrides)
 return calculate(**base).total


def test_perfect_beats_partial():
 assert _score(accuracy=1.0)>_score(accuracy=0.85)


def test_losing_perfection_costs_more_than_the_next_step():
 full=_score(accuracy=1.0)
 near=_score(accuracy=0.9)
 far=_score(accuracy=0.8)
 assert full-near>near-far


def test_faster_scores_higher():
 assert _score(duration_ms=1500.0)>_score(duration_ms=2500.0)


def test_speed_bonus_never_negative():
 slow=calculate(
  difficulty=1,accuracy=1.0,duration_ms=99000.0,mora_count=4,
  max_combo=4,streak=0,restarts=0,abandoned=False,rules=_RULES,
 )
 assert slow.speed==0
 assert slow.total>0


def test_harder_phrase_scores_higher():
 assert _score(difficulty=5)>_score(difficulty=1)


def test_streak_multiplier_is_capped():
 capped=_score(streak=_RULES.streak_cap)
 beyond=_score(streak=_RULES.streak_cap+50)
 assert capped==beyond


def test_restart_reduces_but_does_not_zero():
 clean=_score(restarts=0)
 once=_score(restarts=1)
 assert 0<once<clean


def test_abandoned_scores_zero():
 breakdown=calculate(
  difficulty=5,accuracy=0.9,duration_ms=1000.0,mora_count=10,
  max_combo=9,streak=5,restarts=0,abandoned=True,rules=_RULES,
 )
 assert breakdown.total==0


def test_required_exp_grows_with_level():
 assert required_exp(2,_LEVELS)>required_exp(1,_LEVELS)


def test_required_exp_rejects_zero_level():
 with pytest.raises(ValueError):
  required_exp(0,_LEVELS)


def test_apply_result_levels_up_and_records_best():
 profile=Profile()
 gained=apply_result(profile,"nama_mugi",required_exp(1,_LEVELS),True,_LEVELS)
 assert gained==1
 assert profile.level==2
 assert profile.clears==1
 assert profile.best_scores["nama_mugi"]==required_exp(1,_LEVELS)


def test_best_score_keeps_the_highest():
 profile=Profile()
 apply_result(profile,"x",500,True,_LEVELS)
 apply_result(profile,"x",200,True,_LEVELS)
 assert profile.best_scores["x"]==500


def test_failed_attempt_still_counts_as_play():
 profile=Profile()
 apply_result(profile,"x",50,False,_LEVELS)
 assert profile.plays==1
 assert profile.clears==0


def test_difficulty_unlocks_with_level():
 assert unlocked_difficulty(1,_LEVELS)==1
 assert unlocked_difficulty(1+_LEVELS.unlock_every,_LEVELS)==2
 assert unlocked_difficulty(999,_LEVELS)==_LEVELS.max_difficulty


def test_profile_round_trip(tmp_path):
 path=tmp_path/"profile.json"
 profile=Profile(level=4,exp=120,total_score=9000,plays=30,clears=21,best_scores={"a":800})
 save_profile(path,profile)
 assert load_profile(path)==profile


def test_missing_profile_returns_initial_state(tmp_path):
 assert load_profile(tmp_path/"absent.json")==Profile()
