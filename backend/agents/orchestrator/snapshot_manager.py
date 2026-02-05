"""
Snapshot Manager Module

ワークフロースナップショットの保存・読み込みを担当
"""

from typing import Any,Dict,List,Optional

from middleware.logger import get_logger


class SnapshotManager:
    def __init__(self,get_trace_service_func):
        self._get_trace_service=get_trace_service_func

    def save_snapshot(
        self,
        project_id:str,
        agent_id:str,
        workflow_run_id:str,
        step_type:str,
        step_id:str,
        label:str,
        state_data:Dict[str,Any],
        worker_tasks:List[Dict[str,Any]],
    )->None:
        ts=self._get_trace_service()
        if not ts:
            return
        try:
            ts.create_workflow_snapshot(
                project_id=project_id,
                agent_id=agent_id,
                workflow_run_id=workflow_run_id,
                step_type=step_type,
                step_id=step_id,
                label=label,
                state_data=state_data,
                worker_tasks=worker_tasks,
            )
        except Exception as e:
            get_logger().error(f"スナップショット保存失敗: {e}",exc_info=True)

    def load_completed_workers(self,agent_id:str)->Optional[Dict[str,Any]]:
        ts=self._get_trace_service()
        if not ts:
            return None
        try:
            snapshots=ts.get_latest_workflow_snapshots(agent_id)
            if not snapshots:
                return None
            completed_workers={}
            worker_tasks=None
            workflow_run_id=None
            for snap in snapshots:
                if snap["status"]=="invalidated":
                    continue
                workflow_run_id=snap["workflowRunId"]
                if snap["stepType"]=="worker_completed":
                    state=snap.get("stateData",{})
                    completed_workers[snap["stepId"]]=state
                if snap.get("workerTasks"):
                    worker_tasks=snap["workerTasks"]
            if not completed_workers:
                return None
            return {
                "workflow_run_id":workflow_run_id,
                "completed_workers":completed_workers,
                "worker_tasks":worker_tasks,
            }
        except Exception as e:
            get_logger().error(f"スナップショット読み込み失敗: {e}",exc_info=True)
            return None

    def get_leader_output_from_snapshots(
        self,workflow_run_id:str
    )->Optional[Dict[str,Any]]:
        ts=self._get_trace_service()
        if not ts:
            return None
        try:
            snapshots=ts.get_workflow_snapshots_by_run(workflow_run_id)
            for snap in snapshots:
                if snap["stepType"]=="leader_completed" and snap["status"]!="invalidated":
                    return snap.get("stateData",{})
            return None
        except Exception:
            return None
