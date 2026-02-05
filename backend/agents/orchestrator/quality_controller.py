"""
Quality Controller Module

品質チェック+リトライロジックを担当
"""

from typing import Any,Dict,List,Optional,TYPE_CHECKING

from ..base import AgentContext,AgentStatus
from ..orchestrator_types import QualityCheckResult,WorkerTaskResult
from middleware.logger import get_logger

if TYPE_CHECKING:
    from ..runner_protocol import AgentRunnerProtocol


class QualityController:
    def __init__(self,agent_runner:"AgentRunnerProtocol",get_agent_service_func):
        self.agent_runner=agent_runner
        self._get_agent_service=get_agent_service_func

    async def run_with_quality_check(
        self,
        worker_context:AgentContext,
        worker_type:str,
        max_retries:int=3,
    )->WorkerTaskResult:
        result=WorkerTaskResult(worker_type=worker_type)

        for retry in range(max_retries):
            result.retries=retry
            output=await self.agent_runner.run_agent(worker_context)

            if output.status==AgentStatus.FAILED:
                result.attempt_history.append(
                    {
                        "attempt":retry,
                        "score":0.0,
                        "output":{},
                        "error":output.error,
                    }
                )
                result.error=output.error
                continue

            result.output=output.output
            worker_adv=worker_context.config.get("advancedSettings",{}) if worker_context.config else {}
            worker_enabled_principles=worker_adv.get("enabledPrinciples")
            worker_principle_overrides=worker_adv.get("principleOverrides")
            worker_quality_settings=worker_adv.get("qualityCheck")
            qc_result=await self.perform_quality_check(
                output.output,
                worker_type,
                worker_context.project_id,
                worker_enabled_principles,
                worker_quality_settings,
                principle_overrides=worker_principle_overrides,
            )
            result.quality_check=qc_result

            result.attempt_history.append(
                {
                    "attempt":retry,
                    "score":qc_result.score,
                    "output":output.output,
                }
            )

            if qc_result.passed:
                result.status="completed"
                result.best_attempt_index=retry
                if qc_result.strengths:
                    get_logger().info(
                        f"品質チェック合格 [{worker_type}] 強み: {', '.join(qc_result.strengths[:3])}"
                    )
                return result

            get_logger().info(
                f"品質チェック不合格 [{worker_type}] score={qc_result.score:.2f} retry={retry + 1}/{max_retries}"
            )
            if retry<max_retries-1:
                result.status="needs_retry"
                retry_feedback={
                    "issues":qc_result.issues,
                    "failed_criteria":qc_result.failed_criteria,
                    "improvement_suggestions":qc_result.improvement_suggestions,
                }
                worker_context.previous_outputs[f"{worker_type}_previous_attempt"]=retry_feedback
            else:
                best_idx=max(
                    range(len(result.attempt_history)),
                    key=lambda i:result.attempt_history[i].get("score",0),
                )
                result.best_attempt_index=best_idx
                best=result.attempt_history[best_idx]
                if best.get("output"):
                    result.output=best["output"]
                    get_logger().info(
                        f"品質チェック最大リトライ到達 [{worker_type}] 最良スコア={best.get('score', 0):.2f} (attempt {best_idx})"
                    )
                result.status="needs_human_review"
                result.quality_check.human_review_needed=True
                return result

        return result

    async def perform_quality_check(
        self,
        output:Dict[str,Any],
        worker_type:str,
        project_id:Optional[str]=None,
        enabled_principles:Optional[List[str]]=None,
        quality_settings:Optional[Dict[str,Any]]=None,
        principle_overrides:Optional[Dict[str,List[str]]]=None,
    )->QualityCheckResult:
        from ..quality_evaluator import get_quality_evaluator

        evaluator=get_quality_evaluator()
        try:
            return await evaluator.evaluate(
                output,
                worker_type,
                project_id=project_id,
                enabled_principles=enabled_principles,
                quality_settings=quality_settings,
                principle_overrides=principle_overrides,
                agent_service=self._get_agent_service(),
            )
        except Exception as e:
            get_logger().error(f"品質評価エラー（ルールベースにフォールバック）: {e}",exc_info=True)
            issues=[]
            score=1.0
            content=output.get("content","")
            if not content or len(str(content))<50:
                issues.append("出力内容が不十分です")
                score-=0.3
            passed=score>=0.7 and len(issues)==0
            return QualityCheckResult(
                passed=passed,
                issues=issues,
                score=score,
                retry_needed=not passed,
            )
