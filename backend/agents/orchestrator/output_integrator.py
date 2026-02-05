"""
Output Integrator Module

Worker出力のLLM統合+Conditional Routingを担当
"""

import json
import re
from typing import Any,Callable,Dict,List,Optional,TYPE_CHECKING

from ..base import AgentContext
from ..orchestrator_types import QualityCheckResult
from config_loaders.principle_config import load_principles_for_agent
from middleware.logger import get_logger

if TYPE_CHECKING:
    from ..runner_protocol import AgentRunnerProtocol
    from .quality_controller import QualityController


class OutputIntegrator:
    def __init__(
        self,
        agent_runner:"AgentRunnerProtocol",
        quality_controller:"QualityController",
        quality_settings:Dict[str,Any],
        on_progress:Optional[Callable[[str,int,str],None]]=None,
    ):
        self.agent_runner=agent_runner
        self.quality_controller=quality_controller
        self.quality_settings=quality_settings
        self.on_progress=on_progress
        self._worker_executor=None

    def set_worker_executor(self,executor):
        self._worker_executor=executor

    async def integrate_outputs(
        self,
        leader_context:AgentContext,
        leader_output:Dict[str,Any],
        worker_results:List[Dict[str,Any]],
        routing_cycle:int=0,
        max_routing_cycles:int=2,
    )->Dict[str,Any]:
        worker_outputs={}
        worker_texts=[]
        for result in worker_results:
            wt=result.get("worker_type","unknown")
            worker_outputs[wt]={
                "status":result.get("status"),
                "output":result.get("output",{}),
            }
            content=result.get("output",{}).get("content","")
            if content and result.get("status")=="completed":
                worker_texts.append(f"### {wt}\n{str(content)[:3000]}")

        integrated={
            "type":"document",
            "format":"markdown",
            "leader_summary":leader_output,
            "worker_outputs":worker_outputs,
            "metadata":{
                "agent_type":leader_context.agent_type.value,
                "worker_count":len(worker_results),
                "completed_count":sum(1 for r in worker_results if r.get("status")=="completed"),
                "routing_cycle":routing_cycle,
            },
        }

        if not worker_texts:
            return integrated

        try:
            adv_integration=leader_context.config.get("advancedSettings",{}) if leader_context.config else {}
            enabled_principles_integration=adv_integration.get("enabledPrinciples")
            principle_overrides_integration=adv_integration.get("principleOverrides")
            principles_text=load_principles_for_agent(
                leader_context.agent_type.value,enabled_principles_integration,principle_overrides_integration
            )
            leader_content=leader_output.get("content","")[:3000] if isinstance(leader_output,dict) else""
            workers_combined="\n\n".join(worker_texts)[:10000]

            integration_prompt=f"""## Leader分析
{leader_content}

## Worker出力一覧
{workers_combined}

## 指示
上記のLeader分析とWorker出力を統合し、一貫性のある統合ドキュメントを生成してください。
以下の観点で統合してください:
-全体の一貫性（矛盾がないか）
-コアファンタジーとの整合性
-重複の排除と情報の補完
-各Worker出力の長所を活かした統合

統合ドキュメントをMarkdown形式で出力してください。"""

            system_prompt="あなたはゲーム開発プロジェクトの統合リーダーです。複数の専門家の出力を一貫性のあるドキュメントに統合します。"
            if principles_text:
                rubric_section=principles_text[:4000]
                system_prompt+=f"\n\n## 品質基準\n{rubric_section}"

            resolved_model=self.agent_runner.resolve_model_for_agent(leader_context)
            resolved_provider=self.agent_runner.resolve_provider_for_agent(leader_context)

            job_queue=self.agent_runner.get_job_queue()
            temperature=self.agent_runner.get_project_temperature(leader_context,leader_context.agent_type.value)
            job=job_queue.submit_job(
                project_id=leader_context.project_id,
                agent_id=f"{leader_context.agent_id}-integration",
                provider_id=resolved_provider,
                model=resolved_model,
                prompt=integration_prompt,
                max_tokens=self.agent_runner.max_tokens,
                system_prompt=system_prompt,
                temperature=str(temperature),
                token_budget=self.agent_runner.get_project_token_budget(leader_context),
            )
            result=await job_queue.wait_for_job_async(job["id"],timeout=300.0)
            if result and result["status"]=="completed":
                integrated["content"]=result["responseContent"]
                integrated["metadata"]["integration_method"]="llm"
                get_logger().info(f"LLM統合完了: {leader_context.agent_type.value}")

                leader_adv_qc=leader_context.config.get("advancedSettings",{}) if leader_context.config else {}
                leader_enabled_principles_qc=leader_adv_qc.get("enabledPrinciples")
                leader_principle_overrides_qc=leader_adv_qc.get("principleOverrides")
                leader_quality_settings=leader_adv_qc.get("qualityCheck")
                qc_result=await self.quality_controller.perform_quality_check(
                    integrated,
                    leader_context.agent_type.value,
                    leader_context.project_id,
                    leader_enabled_principles_qc,
                    leader_quality_settings,
                    principle_overrides=leader_principle_overrides_qc,
                )
                if not qc_result.passed:
                    if routing_cycle<max_routing_cycles:
                        get_logger().info(
                            f"統合品質不合格 score={qc_result.score:.2f}、Leaderへ差し戻し (cycle {routing_cycle + 1}/{max_routing_cycles})"
                        )
                        additional_results=await self._route_back_to_leader(
                            leader_context,
                            leader_output,
                            worker_results,
                            qc_result,
                        )
                        if additional_results:
                            combined_results=worker_results+additional_results
                            return await self.integrate_outputs(
                                leader_context,
                                leader_output,
                                combined_results,
                                routing_cycle=routing_cycle+1,
                                max_routing_cycles=max_routing_cycles,
                            )
                    get_logger().info(f"統合品質不合格 score={qc_result.score:.2f}、再統合実行 (最終リトライ)")
                    feedback=(
                        "\n".join(f"- {s}" for s in qc_result.improvement_suggestions)
                        if qc_result.improvement_suggestions
                        else""
                    )
                    retry_prompt=f"""{integration_prompt}

## 品質チェックフィードバック（前回統合の指摘事項）
{feedback}

上記の指摘を踏まえ、改善した統合ドキュメントを出力してください。"""
                    retry_job=job_queue.submit_job(
                        project_id=leader_context.project_id,
                        agent_id=f"{leader_context.agent_id}-integration-retry",
                        provider_id=resolved_provider,
                        model=resolved_model,
                        prompt=retry_prompt,
                        max_tokens=self.agent_runner.max_tokens,
                        system_prompt=system_prompt,
                        temperature=str(temperature),
                        token_budget=self.agent_runner.get_project_token_budget(leader_context),
                    )
                    retry_result=await job_queue.wait_for_job_async(retry_job["id"],timeout=300.0)
                    if retry_result and retry_result["status"]=="completed":
                        integrated["content"]=retry_result["responseContent"]
                        integrated["metadata"]["integration_retried"]=True
                        get_logger().info(f"統合再実行完了: {leader_context.agent_type.value}")
            else:
                get_logger().warning(f"LLM統合失敗、マージモードで出力: {leader_context.agent_type.value}")
        except Exception as e:
            get_logger().error(f"統合LLM呼び出しエラー: {e}",exc_info=True)

        return integrated

    async def _route_back_to_leader(
        self,
        leader_context:AgentContext,
        leader_output:Dict[str,Any],
        current_worker_results:List[Dict[str,Any]],
        qc_result:QualityCheckResult,
    )->Optional[List[Dict[str,Any]]]:
        from dataclasses import asdict
        from ..task_dispatcher import normalize_worker_tasks

        issues_text=(
            "\n".join(f"- {i}" for i in qc_result.issues) if qc_result.issues else"品質スコアが基準に達していません"
        )
        suggestions_text=(
            "\n".join(f"- {s}" for s in qc_result.improvement_suggestions) if qc_result.improvement_suggestions else""
        )
        existing_workers=", ".join(r.get("worker_type","?") for r in current_worker_results)

        routing_prompt=f"""## 統合品質チェック結果
スコア:{qc_result.score:.2f}（基準未達）

### 問題点
{issues_text}

### 改善提案
{suggestions_text}

### 既存Worker
{existing_workers}

## 指示
上記の品質チェック結果を踏まえ、不足を補うための追加Workerタスクを生成してください。
既存Workerと重複しないよう、新しい観点での作業を割り当ててください。
出力はJSON形式でworker_tasksリストを含めてください。"""

        try:
            resolved_model=self.agent_runner.resolve_model_for_agent(leader_context)
            resolved_provider=self.agent_runner.resolve_provider_for_agent(leader_context)
            job_queue=self.agent_runner.get_job_queue()
            temperature=self.agent_runner.get_project_temperature(leader_context,leader_context.agent_type.value)

            system_prompt=f"あなたはゲーム開発の専門家です。品質向上のための追加作業を計画します。\n\n## プロジェクト情報\n{leader_context.project_concept or '（未定義）'}"

            job=job_queue.submit_job(
                project_id=leader_context.project_id,
                agent_id=f"{leader_context.agent_id}-routing",
                provider_id=resolved_provider,
                model=resolved_model,
                prompt=routing_prompt,
                max_tokens=self.agent_runner.max_tokens,
                system_prompt=system_prompt,
                temperature=str(temperature),
                token_budget=self.agent_runner.get_project_token_budget(leader_context),
            )
            result=await job_queue.wait_for_job_async(job["id"],timeout=300.0)
            if not result or result["status"]!="completed":
                get_logger().warning("Conditional Routing: Leader追加タスク生成失敗")
                return None

            content=result["responseContent"]
            json_match=re.search(r"```json\s*([\s\S]*?)\s*```",content)
            if json_match:
                data=json.loads(json_match.group(1))
                additional_tasks=normalize_worker_tasks(data.get("worker_tasks",[]))
            else:
                get_logger().warning("Conditional Routing: 追加タスクのJSON抽出失敗")
                return None

            if not additional_tasks:
                return None

            get_logger().info(f"Conditional Routing: 追加Worker {len(additional_tasks)}件を実行")
            self._emit_progress(leader_context.agent_type.value,87,f"追加Worker実行中 ({len(additional_tasks)}件)")

            if not self._worker_executor:
                get_logger().error("Conditional Routing: WorkerExecutor未設定")
                return None

            additional_results=[]
            for task_data in additional_tasks:
                worker_type=task_data.get("worker","")
                task_desc=task_data.get("task","")
                qc_config=self.quality_settings.get(worker_type,{})
                wr=await self._worker_executor.execute_worker(
                    leader_context=leader_context,
                    worker_type=worker_type,
                    task=task_desc,
                    leader_output=leader_output,
                    quality_check_enabled=qc_config.get("enabled",True),
                    max_retries=qc_config.get("maxRetries",2),
                )
                additional_results.append(asdict(wr))

            return additional_results

        except Exception as e:
            get_logger().error(f"Conditional Routing失敗: {e}",exc_info=True)
            return None

    def _emit_progress(self,agent_type:str,progress:int,message:str):
        if self.on_progress:
            self.on_progress(agent_type,progress,message)
