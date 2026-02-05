"""
Worker Executor Module

Worker実行（DAG並列、逐次、単一Worker）を担当
"""

from dataclasses import asdict
from typing import Any,Callable,Dict,List,Optional,Set,TYPE_CHECKING

from ..base import AgentContext,AgentType,AgentStatus
from ..orchestrator_types import WorkerTaskResult
from middleware.logger import get_logger

if TYPE_CHECKING:
    from .quality_controller import QualityController
    from .snapshot_manager import SnapshotManager
    from ..runner_protocol import AgentRunnerProtocol


class WorkerExecutor:
    def __init__(
        self,
        agent_runner:"AgentRunnerProtocol",
        quality_controller:"QualityController",
        snapshot_manager:"SnapshotManager",
        quality_settings:Dict[str,Any],
        on_progress:Optional[Callable[[str,int,str],None]]=None,
        on_worker_created:Optional[Callable[[str,str],str]]=None,
        on_worker_status:Optional[Callable[[str,str,Dict],None]]=None,
        on_worker_speech:Optional[Callable[[str,str],None]]=None,
    ):
        self.agent_runner=agent_runner
        self.quality_controller=quality_controller
        self.snapshot_manager=snapshot_manager
        self.quality_settings=quality_settings
        self.on_progress=on_progress
        self.on_worker_created=on_worker_created
        self.on_worker_status=on_worker_status
        self.on_worker_speech=on_worker_speech

    async def run_workers_dag(
        self,
        leader_context:AgentContext,
        leader_output,
        worker_tasks:List[Dict[str,Any]],
        results:Dict[str,Any],
        workflow_run_id:str="",
        completed_worker_ids:Optional[Set[str]]=None,
    )->Dict[str,Any]:
        from ..task_dispatcher import TaskDAG,execute_dag_parallel

        _completed=completed_worker_ids or set()
        total_workers=len(worker_tasks)
        dag=TaskDAG(worker_tasks)
        layers=dag.get_execution_layers()
        layer_count=len(layers)
        get_logger().info(
            f"DAG構築完了: {total_workers}タスク, {layer_count}レイヤー, レイヤー構成={[len(l) for l in layers]}"
        )
        self._emit_progress(
            leader_context.agent_type.value,
            30,
            f"Worker並列実行開始 ({total_workers}タスク, {layer_count}レイヤー)",
        )

        async def _exec_single(task_data:Dict[str,Any])->WorkerTaskResult:
            worker_type=task_data.get("worker","")
            task_id=task_data.get("id","")
            if task_id in _completed or worker_type in _completed:
                get_logger().info(f"スナップショットからスキップ: {worker_type}")
                return WorkerTaskResult(
                    worker_type=worker_type,
                    status="completed",
                    output={"content":"(スナップショットから復元)","type":"document"},
                )
            task_description=task_data.get("task","")
            qc_config=self.quality_settings.get(worker_type,{})
            qc_enabled=qc_config.get("enabled",True)
            max_retries=qc_config.get("maxRetries",3)
            wr=await self.execute_worker(
                leader_context=leader_context,
                worker_type=worker_type,
                task=task_description,
                leader_output=leader_output.output,
                quality_check_enabled=qc_enabled,
                max_retries=max_retries,
            )
            if wr.status=="completed" and workflow_run_id:
                self.snapshot_manager.save_snapshot(
                    project_id=leader_context.project_id,
                    agent_id=leader_context.agent_id,
                    workflow_run_id=workflow_run_id,
                    step_type="worker_completed",
                    step_id=worker_type,
                    label=f"Worker完了: {worker_type}",
                    state_data=asdict(wr),
                    worker_tasks=worker_tasks,
                )
            return wr

        def _on_layer_start(layer_idx:int,layer_task_ids:list)->None:
            progress=30+int(((layer_idx)/max(layer_count,1))*50)
            parallel_label="並列" if len(layer_task_ids)>1 else"単独"
            task_names=[
                dag.get_task(tid).get("worker","?")
                for tid in layer_task_ids
                if dag.get_task(tid)
            ]
            self._emit_progress(
                leader_context.agent_type.value,
                progress,
                f"Layer {layer_idx + 1}/{layer_count} ({parallel_label}): {', '.join(task_names)}",
            )

        dag_results=await execute_dag_parallel(dag,_exec_single,on_layer_start=_on_layer_start)

        for tid,result in dag_results:
            if isinstance(result,Exception):
                task_data=dag.get_task(tid)
                wt=task_data.get("worker",tid) if task_data else tid
                wr=WorkerTaskResult(worker_type=wt,status="failed",error=str(result))
            else:
                wr=result
            results["worker_results"].append(asdict(wr))
            if wr.status=="needs_human_review":
                task_data=dag.get_task(tid)
                results["human_review_required"].append(
                    {
                        "worker_type":wr.worker_type,
                        "task":task_data.get("task","") if task_data else"",
                        "issues":wr.quality_check.issues if wr.quality_check else [],
                    }
                )
        return results

    async def run_workers_sequential(
        self,
        leader_context:AgentContext,
        leader_output,
        worker_tasks:List[Dict[str,Any]],
        results:Dict[str,Any],
        workflow_run_id:str="",
        completed_worker_ids:Optional[Set[str]]=None,
    )->Dict[str,Any]:
        _completed=completed_worker_ids or set()
        total_workers=len(worker_tasks)
        self._emit_progress(
            leader_context.agent_type.value,30,f"Worker逐次実行開始 ({total_workers}タスク)"
        )
        for i,worker_task in enumerate(worker_tasks):
            worker_type=worker_task.get("worker","")
            task_id=worker_task.get("id","")
            task_description=worker_task.get("task","")
            progress=30+int((i/max(total_workers,1))*50)
            if task_id in _completed or worker_type in _completed:
                get_logger().info(f"スナップショットからスキップ: {worker_type}")
                results["worker_results"].append(
                    asdict(
                        WorkerTaskResult(
                            worker_type=worker_type,
                            status="completed",
                            output={"content":"(スナップショットから復元)","type":"document"},
                        )
                    )
                )
                continue
            self._emit_progress(leader_context.agent_type.value,progress,f"{worker_type} 実行中")
            qc_config=self.quality_settings.get(worker_type,{})
            qc_enabled=qc_config.get("enabled",True)
            max_retries=qc_config.get("maxRetries",3)
            worker_result=await self.execute_worker(
                leader_context=leader_context,
                worker_type=worker_type,
                task=task_description,
                leader_output=leader_output.output,
                quality_check_enabled=qc_enabled,
                max_retries=max_retries,
            )
            results["worker_results"].append(asdict(worker_result))
            if worker_result.status=="completed" and workflow_run_id:
                self.snapshot_manager.save_snapshot(
                    project_id=leader_context.project_id,
                    agent_id=leader_context.agent_id,
                    workflow_run_id=workflow_run_id,
                    step_type="worker_completed",
                    step_id=worker_type,
                    label=f"Worker完了: {worker_type}",
                    state_data=asdict(worker_result),
                    worker_tasks=worker_tasks,
                )
            if worker_result.status=="needs_human_review":
                results["human_review_required"].append(
                    {
                        "worker_type":worker_type,
                        "task":task_description,
                        "issues":worker_result.quality_check.issues
                        if worker_result.quality_check
                        else [],
                    }
                )
        return results

    async def execute_worker(
        self,
        leader_context:AgentContext,
        worker_type:str,
        task:str,
        leader_output:Dict[str,Any],
        quality_check_enabled:bool,
        max_retries:int,
    )->WorkerTaskResult:
        result=WorkerTaskResult(worker_type=worker_type)

        try:
            try:
                agent_type=AgentType(worker_type)
            except ValueError:
                result.status="failed"
                result.error=f"Unknown worker type: {worker_type}"
                return result

            worker_id=f"{leader_context.agent_id}-{worker_type}"
            if self.on_worker_created:
                worker_id=self.on_worker_created(worker_type,task) or worker_id

            worker_on_progress=None
            if self.on_worker_status:

                def _make_progress_cb(wid):
                    def cb(p,t):
                        self.on_worker_status(wid,"running",{"progress":p,"currentTask":t})

                    return cb

                worker_on_progress=_make_progress_cb(worker_id)

            worker_on_speech=None
            if self.on_worker_speech:

                def _make_speech_cb(wid):
                    def cb(msg):
                        self.on_worker_speech(wid,msg)

                    return cb

                worker_on_speech=_make_speech_cb(worker_id)

            worker_context=AgentContext(
                project_id=leader_context.project_id,
                agent_id=worker_id,
                agent_type=agent_type,
                project_concept=leader_context.project_concept,
                previous_outputs={},
                config=leader_context.config,
                assigned_task=task,
                leader_analysis=leader_output,
                on_progress=worker_on_progress,
                on_log=leader_context.on_log,
                on_speech=worker_on_speech,
            )

            if self.on_worker_status:
                self.on_worker_status(worker_id,"running",{"currentTask":task})

            if quality_check_enabled:
                result=await self.quality_controller.run_with_quality_check(
                    worker_context=worker_context,
                    worker_type=worker_type,
                    max_retries=max_retries,
                )
            else:
                output=await self.agent_runner.run_agent(worker_context)
                result.status="completed" if output.status==AgentStatus.COMPLETED else"failed"
                result.output=output.output
                result.tokens_used=output.tokens_used
                if output.error:
                    result.error=output.error

            if self.on_worker_status:
                if result.status=="completed":
                    self.on_worker_status(
                        worker_id,
                        "completed",
                        {
                            "tokensUsed":result.tokens_used,
                            "inputTokens":result.input_tokens,
                            "outputTokens":result.output_tokens,
                        },
                    )
                elif result.status=="failed":
                    self.on_worker_status(worker_id,"failed",{"error":result.error})
                elif result.status=="needs_human_review":
                    self.on_worker_status(worker_id,"waiting_approval",{"currentTask":"レビュー待ち"})

        except Exception as e:
            result.status="failed"
            result.error=str(e)
            if self.on_worker_status and"worker_id" in locals():
                self.on_worker_status(worker_id,"failed",{"error":str(e)})

        return result

    def _emit_progress(self,agent_type:str,progress:int,message:str):
        if self.on_progress:
            self.on_progress(agent_type,progress,message)
