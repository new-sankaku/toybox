"""
Quality Evaluator Module

RuleBasedChecker と LLMEvaluator を組み合わせた品質評価のファサード
"""

from typing import Dict,Any,List,Optional,TYPE_CHECKING

from config_loaders.principle_config import load_principles_for_agent,get_principle_settings
from middleware.logger import get_logger

from .rule_based_checker import RuleBasedChecker
from .llm_evaluator import LLMEvaluator,extract_rubrics
from .insight_saver import InsightSaver

if TYPE_CHECKING:
    from ..orchestrator_types import QualityCheckResult


class PrincipleBasedQualityEvaluator:
    """
    原則ベースの品質評価器

    RuleBasedChecker と LLMEvaluator を組み合わせて品質評価を行う
    """

    def __init__(
        self,
        rule_checker:Optional[RuleBasedChecker]=None,
        llm_evaluator:Optional[LLMEvaluator]=None,
        insight_saver:Optional[InsightSaver]=None,
    ):
        self._settings=get_principle_settings()
        self._rule_checker=rule_checker or RuleBasedChecker()
        max_tokens=self._settings.get("quality_check_max_tokens",2048)
        self._llm_evaluator=llm_evaluator or LLMEvaluator(max_tokens=max_tokens)
        self._insight_saver=insight_saver or InsightSaver()

    async def evaluate(
        self,
        output:Dict[str,Any],
        agent_type:str,
        project_id:Optional[str]=None,
        enabled_principles:Optional[List[str]]=None,
        quality_settings:Optional[Dict[str,Any]]=None,
        principle_overrides:Optional[Dict[str,List[str]]]=None,
        agent_service:Any=None,
    )->"QualityCheckResult":
        """品質評価を実行"""
        from ..orchestrator_types import QualityCheckResult

        content=output.get("content","")
        settings=dict(self._settings)
        if quality_settings:
            settings.update(quality_settings)

        rule_result=self._rule_checker.check(content,agent_type)
        if not rule_result["passed"]:
            return QualityCheckResult(
                passed=False,
                issues=rule_result["issues"],
                score=rule_result["score"],
                retry_needed=True,
                failed_criteria=rule_result.get("failed_criteria",[]),
                improvement_suggestions=rule_result.get("issues",[]),
            )

        principles_text=load_principles_for_agent(
            agent_type,enabled_principles,principle_overrides
        )
        if not principles_text:
            return QualityCheckResult(passed=True,score=1.0)

        rubrics=extract_rubrics(principles_text)
        if not rubrics.strip():
            return QualityCheckResult(passed=True,score=1.0)

        try:
            llm_result=await self._evaluate_with_llm(
                str(content),rubrics,project_id,settings
            )
            return self._build_result(
                llm_result,settings,agent_type,project_id,agent_service
            )
        except Exception as e:
            get_logger().error(
                f"QualityEvaluator: LLM評価失敗、ルールベースにフォールバック: {e}",
                exc_info=True,
            )
            return QualityCheckResult(passed=True,score=0.8)

    async def _evaluate_with_llm(
        self,
        content:str,
        rubrics:str,
        project_id:Optional[str],
        settings:Dict[str,Any],
    )->Dict[str,Any]:
        """LLM評価を実行（エスカレーション対応）"""
        usage_cat=settings.get("quality_check_usage_category","llm_low")
        llm_result=await self._llm_evaluator.evaluate(
            content,rubrics,project_id,usage_cat
        )
        normalized=llm_result.get("average_score",3.0)/5.0

        escalation=settings.get("escalation",{})
        if not escalation.get("enabled",False):
            return llm_result

        tier2_min=escalation.get("tier2_score_min",0.5)
        tier2_max=escalation.get("tier2_score_max",0.7)
        if tier2_min<=normalized<=tier2_max:
            tier2_cat=escalation.get("tier2_usage_category","llm_mid")
            get_logger().info(
                f"QualityEvaluator: スコア{normalized:.2f}で境界帯、Tier2({tier2_cat})で再評価"
            )
            llm_result=await self._llm_evaluator.evaluate(
                content,rubrics,project_id,tier2_cat
            )

        return llm_result

    def _build_result(
        self,
        llm_result:Dict[str,Any],
        settings:Dict[str,Any],
        agent_type:str,
        project_id:Optional[str],
        agent_service:Any,
    )->"QualityCheckResult":
        """評価結果を構築"""
        from ..orchestrator_types import QualityCheckResult

        threshold=settings.get("quality_threshold",0.6)
        normalized=llm_result.get("average_score",3.0)/5.0

        hallucinations=llm_result.get("hallucination_warnings",[])
        if hallucinations:
            get_logger().warning(
                f"QualityEvaluator: Hallucination検出 [{agent_type}]: {hallucinations}"
            )

        all_issues=llm_result.get("improvement_suggestions",[])
        if hallucinations:
            all_issues=[f"[Hallucination] {h}" for h in hallucinations]+all_issues

        passed=normalized>=threshold and not hallucinations
        qc=QualityCheckResult(
            passed=passed,
            issues=all_issues if not passed else [],
            score=normalized,
            retry_needed=not passed,
            failed_criteria=llm_result.get("failed_criteria",[]),
            improvement_suggestions=all_issues,
            strengths=llm_result.get("strengths",[]),
        )

        if not passed:
            self._insight_saver.save(
                agent_type,project_id,passed,llm_result,agent_service
            )

        return qc


_evaluator_instance:Optional[PrincipleBasedQualityEvaluator]=None


def get_quality_evaluator()->PrincipleBasedQualityEvaluator:
    """品質評価器のシングルトンインスタンスを取得"""
    global _evaluator_instance
    if _evaluator_instance is None:
        _evaluator_instance=PrincipleBasedQualityEvaluator()
    return _evaluator_instance
