"""
Leader Worker Orchestrator Module

Leader/Worker パターンでマルチエージェントオーケストレーションを実行
各サブモジュールを組み合わせてメインフローを提供
"""

import json
import re
import uuid as _uuid
from typing import Any,Callable,Dict,List,Optional

from ..base import AgentContext,AgentOutput,AgentStatus
from ..runner_protocol import AgentRunnerProtocol
from ..task_dispatcher import normalize_worker_tasks
from .snapshot_manager import SnapshotManager
from .quality_controller import QualityController
from .worker_executor import WorkerExecutor
from .output_integrator import OutputIntegrator
from middleware.logger import get_logger


class LeaderWorkerOrchestrator:
    def __init__(
        self,
        agent_runner:AgentRunnerProtocol,
        quality_settings:Dict[str,Any],
        on_progress:Optional[Callable[[str,int,str],None]]=None,
        on_checkpoint:Optional[Callable[[str,Dict],None]]=None,
        on_worker_created:Optional[Callable[[str,str],str]]=None,
        on_worker_status:Optional[Callable[[str,str,Dict],None]]=None,
        on_worker_speech:Optional[Callable[[str,str],None]]=None,
    ):
        self.agent_runner=agent_runner
        self.quality_settings=quality_settings
        self.on_progress=on_progress
        self.on_checkpoint=on_checkpoint
        self.on_worker_created=on_worker_created
        self.on_worker_status=on_worker_status
        self.on_worker_speech=on_worker_speech

        self._snapshot_manager=SnapshotManager(self._get_trace_service)
        self._quality_controller=QualityController(agent_runner,self._get_agent_service)
        self._worker_executor=WorkerExecutor(
            agent_runner=agent_runner,
            quality_controller=self._quality_controller,
            snapshot_manager=self._snapshot_manager,
            quality_settings=quality_settings,
            on_progress=on_progress,
            on_worker_created=on_worker_created,
            on_worker_status=on_worker_status,
            on_worker_speech=on_worker_speech,
        )
        self._output_integrator=OutputIntegrator(
            agent_runner=agent_runner,
            quality_controller=self._quality_controller,
            quality_settings=quality_settings,
            on_progress=on_progress,
        )
        self._output_integrator.set_worker_executor(self._worker_executor)

    def _get_trace_service(self):
        return self.agent_runner.get_trace_service()

    def _get_agent_service(self):
        return self.agent_runner.get_agent_service()

    async def run_leader_with_workers(self,leader_context:AgentContext)->Dict[str,Any]:
        results={
            "leader_output":{},
            "worker_results":[],
            "final_output":{},
            "checkpoint":None,
            "human_review_required":[],
        }

        resumable=self._snapshot_manager.load_completed_workers(leader_context.agent_id)
        workflow_run_id=resumable["workflow_run_id"] if resumable else f"wf-{_uuid.uuid4().hex[:12]}"

        if resumable and resumable.get("worker_tasks"):
            get_logger().info(f"ワークフロー再開: {len(resumable['completed_workers'])}件のWorker完了済み")
            worker_tasks=resumable["worker_tasks"]
            leader_output_snap=self._snapshot_manager.get_leader_output_from_snapshots(workflow_run_id)
            if leader_output_snap:
                results["leader_output"]=leader_output_snap
                leader_output=AgentOutput(
                    agent_id=leader_context.agent_id,
                    agent_type=leader_context.agent_type,
                    status=AgentStatus.COMPLETED,
                    output=leader_output_snap,
                )
            else:
                resumable=None

        if not resumable or not resumable.get("worker_tasks"):
            self._emit_progress(leader_context.agent_type.value,10,"Leader分析開始")

            leader_output=await self.agent_runner.run_agent(leader_context)
            results["leader_output"]=leader_output.output

            if leader_output.status==AgentStatus.FAILED:
                return results

            worker_tasks=self._extract_worker_tasks(leader_output.output)

            self._snapshot_manager.save_snapshot(
                project_id=leader_context.project_id,
                agent_id=leader_context.agent_id,
                workflow_run_id=workflow_run_id,
                step_type="leader_completed",
                step_id="leader",
                label="Leader分析完了",
                state_data=leader_output.output,
                worker_tasks=worker_tasks,
            )

        total_workers=len(worker_tasks)
        completed_worker_ids=set(resumable["completed_workers"].keys()) if resumable else set()

        if self.agent_runner.get_project_dag_enabled(leader_context):
            results=await self._worker_executor.run_workers_dag(
                leader_context,leader_output,worker_tasks,results,workflow_run_id,completed_worker_ids
            )
        else:
            results=await self._worker_executor.run_workers_sequential(
                leader_context,leader_output,worker_tasks,results,workflow_run_id,completed_worker_ids
            )

        self._emit_progress(leader_context.agent_type.value,85,"Leader統合中")

        final_output=await self._output_integrator.integrate_outputs(
            leader_context=leader_context,
            leader_output=leader_output.output,
            worker_results=results["worker_results"],
        )
        results["final_output"]=final_output

        self._snapshot_manager.save_snapshot(
            project_id=leader_context.project_id,
            agent_id=leader_context.agent_id,
            workflow_run_id=workflow_run_id,
            step_type="integration_completed",
            step_id="integration",
            label="統合完了",
            state_data=final_output,
            worker_tasks=worker_tasks,
        )

        self._emit_progress(leader_context.agent_type.value,95,"承認生成")

        checkpoint_data={
            "type":f"{leader_context.agent_type.value}_review",
            "title":f"{leader_context.agent_type.value} 成果物レビュー",
            "output":final_output,
            "worker_summary":{
                "total":total_workers,
                "completed":sum(1 for r in results["worker_results"] if r["status"]=="completed"),
                "failed":sum(1 for r in results["worker_results"] if r["status"]=="failed"),
                "needs_review":len(results["human_review_required"]),
            },
            "human_review_required":results["human_review_required"],
        }
        results["checkpoint"]=checkpoint_data

        if self.on_checkpoint:
            self.on_checkpoint(checkpoint_data["type"],checkpoint_data)

        self._emit_progress(leader_context.agent_type.value,100,"完了")

        return results

    def _extract_worker_tasks(self,leader_output:Dict[str,Any])->List[Dict[str,Any]]:
        content=leader_output.get("content","")

        json_match=re.search(r"```json\s*([\s\S]*?)\s*```",str(content))
        if json_match:
            try:
                data=json.loads(json_match.group(1))
                raw=data.get("worker_tasks",[])
                return normalize_worker_tasks(raw)
            except json.JSONDecodeError:
                pass

        if isinstance(leader_output,dict) and"worker_tasks" in leader_output:
            raw=leader_output.get("worker_tasks",[])
            return normalize_worker_tasks(raw)

        return []

    def _emit_progress(self,agent_type:str,progress:int,message:str):
        if self.on_progress:
            self.on_progress(agent_type,progress,message)
