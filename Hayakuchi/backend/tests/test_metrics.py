import math

import numpy as np

from hayakuchi.metrics import (
 SampleOutcome,
 equal_error_rate,
 error_rates,
 percentiles,
 roc_auc,
 summarize,
 threshold_for_far,
)


def _outcome(sample_id,label,accuracy,exact_match=False,predicted=None,truth=None,elapsed=100.0):
 return SampleOutcome(
  sample_id=sample_id,
  label=label,
  accuracy=accuracy,
  exact_match=exact_match,
  predicted_error_index=predicted,
  truth_error_index=truth,
  elapsed_ms=elapsed,
  audio_seconds=2.0,
 )


def test_roc_auc_is_one_for_separable_scores():
 assert roc_auc([0.9,0.95,0.2,0.1],[True,True,False,False])==1.0


def test_roc_auc_is_half_for_identical_scores():
 assert roc_auc([0.5,0.5,0.5,0.5],[True,True,False,False])==0.5


def test_roc_auc_is_zero_for_inverted_scores():
 assert roc_auc([0.1,0.2,0.9,0.95],[True,True,False,False])==0.0


def test_error_rates_at_threshold():
 far,frr=error_rates(
  np.array([1.0,0.9,0.4,0.2]),
  np.array([True,True,False,False]),
  0.5,
 )
 assert far==0.0
 assert frr==0.0


def test_equal_error_rate_is_zero_for_separable_scores():
 eer,threshold=equal_error_rate([1.0,0.9,0.3,0.2],[True,True,False,False])
 assert eer==0.0
 assert 0.3<threshold<0.9


def test_threshold_for_far_returns_lowest_false_reject():
 threshold,frr=threshold_for_far([1.0,0.9,0.3,0.2],[True,True,False,False],0.0)
 assert frr==0.0
 assert threshold>0.3


def test_percentiles_handle_empty_input():
 result=percentiles([],[50,95])
 assert math.isnan(result["p50"])


def test_summarize_reports_lm_correction_rate():
 outcomes=[
  _outcome("a","ok",1.0,exact_match=True),
  _outcome("b","ok",0.95),
  _outcome("c","ng",1.0,exact_match=True,predicted=None,truth=2),
  _outcome("d","ng",0.8,predicted=2,truth=2),
 ]
 summary=summarize(outcomes,target_far=0.05,localization_tolerance=1,latency_percentiles=[50,95])
 assert summary.ok_count==2
 assert summary.ng_count==2
 assert summary.lm_correction_rate==0.5


def test_summarize_reports_localization_accuracy_within_tolerance():
 outcomes=[
  _outcome("a","ok",1.0,exact_match=True),
  _outcome("b","ng",0.8,predicted=3,truth=2),
  _outcome("c","ng",0.8,predicted=9,truth=2),
 ]
 summary=summarize(outcomes,target_far=0.05,localization_tolerance=1,latency_percentiles=[50])
 assert summary.localization_evaluated==2
 assert summary.localization_accuracy==0.5


def test_summarize_computes_real_time_factor():
 outcomes=[
  _outcome("a","ok",1.0,elapsed=1000.0),
  _outcome("b","ng",0.5,elapsed=1000.0,predicted=1,truth=1),
 ]
 summary=summarize(outcomes,target_far=0.05,localization_tolerance=1,latency_percentiles=[50])
 assert summary.real_time_factor["p50"]==0.5
