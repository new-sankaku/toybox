from hayakuchi.alignment import DELETE,INSERT,MATCH,SUBSTITUTE,align
from hayakuchi.mora import to_mora
from hayakuchi.scoring import ScoringConfig,judge


def test_identical_sequence_has_zero_distance():
 reference=to_mora("なまむぎ")
 result=align(reference,reference)
 assert result.distance==0.0
 assert all(op.op==MATCH for op in result.ops)


def test_substitution_is_detected_at_expected_index():
 reference=to_mora("なまむぎなまごめ")
 hypothesis=to_mora("なまむにゃまごめ")
 result=judge(reference,hypothesis)
 assert result.first_error_index==3
 assert not result.exact_match


def test_deletion_reduces_accuracy():
 reference=to_mora("なまむぎ")
 hypothesis=to_mora("なまぎ")
 result=judge(reference,hypothesis)
 assert result.distance==1.0
 assert result.accuracy==0.75
 assert any(op.op==DELETE for op in result.ops)


def test_insertion_is_recorded():
 reference=to_mora("なまむぎ")
 hypothesis=to_mora("なまむむぎ")
 result=judge(reference,hypothesis)
 assert any(op.op==INSERT for op in result.ops)
 assert result.accuracy<1.0


def test_exact_match_gives_full_accuracy():
 reference=to_mora("とうきょうとっきょきょかきょく")
 result=judge(reference,list(reference))
 assert result.accuracy==1.0
 assert result.exact_match
 assert result.first_error_index is None


def test_accuracy_is_clamped_at_zero():
 reference=to_mora("なま")
 hypothesis=to_mora("あいうえおかきくけこ")
 result=judge(reference,hypothesis)
 assert result.accuracy==0.0


def test_costs_are_configurable():
 reference=to_mora("なまむぎ")
 hypothesis=to_mora("なまむ")
 strict=judge(reference,hypothesis,ScoringConfig(deletion_cost=2.0))
 loose=judge(reference,hypothesis,ScoringConfig(deletion_cost=0.5))
 assert strict.accuracy<loose.accuracy


def test_substitute_op_is_used_when_lengths_match():
 result=align(["ア","イ"],["ア","ウ"])
 assert [op.op for op in result.ops]==[MATCH,SUBSTITUTE]
