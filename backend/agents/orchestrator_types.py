"""
Orchestrator Types Module

LeaderWorkerOrchestrator で使用されるデータクラスを定義
循環インポートを避けるため、別ファイルに分離
"""

from dataclasses import dataclass,field
from typing import Dict,Any,List,Optional


@dataclass
class QualityCheckResult:
    passed:bool
    issues:List[str]=field(default_factory=list)
    score:float=1.0
    retry_needed:bool=False
    human_review_needed:bool=False
    failed_criteria:List[str]=field(default_factory=list)
    improvement_suggestions:List[str]=field(default_factory=list)
    strengths:List[str]=field(default_factory=list)


@dataclass
class WorkerTaskResult:
    worker_type:str
    status:str="pending"
    output:Dict[str,Any]=field(default_factory=dict)
    quality_check:Optional[QualityCheckResult]=None
    retries:int=0
    error:Optional[str]=None
    tokens_used:int=0
    input_tokens:int=0
    output_tokens:int=0
    attempt_history:List[Dict[str,Any]]=field(default_factory=list)
    best_attempt_index:int=0
