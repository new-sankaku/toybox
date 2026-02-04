from typing import Optional,Dict,List

from models.database import session_scope
from repositories import AgentTraceRepository,LlmJobRepository
from repositories.workflow_snapshot import WorkflowSnapshotRepository
from events.event_bus import EventBus
from services.base_service import BaseService


class TraceService(BaseService):
    def __init__(self,event_bus:EventBus):
        super().__init__(event_bus)

    def get_traces_by_project(
        self,project_id:str,limit:int=100
    )->List[Dict]:
        with session_scope() as session:
            repo=AgentTraceRepository(session)
            return repo.get_by_project(project_id,limit)

    def get_traces_by_agent(self,agent_id:str)->List[Dict]:
        with session_scope() as session:
            repo=AgentTraceRepository(session)
            return repo.get_by_agent(agent_id)

    def get_trace(self,trace_id:str)->Optional[Dict]:
        with session_scope() as session:
            repo=AgentTraceRepository(session)
            trace=repo.get(trace_id)
            return repo.to_dict(trace) if trace else None

    def create_trace(
        self,
        project_id:str,
        agent_id:str,
        agent_type:str,
        input_context:Optional[Dict]=None,
        model_used:Optional[str]=None,
    )->Dict:
        with session_scope() as session:
            repo=AgentTraceRepository(session)
            return repo.create_trace(
                project_id,agent_id,agent_type,input_context,model_used
            )

    def update_trace_prompt(
        self,trace_id:str,prompt:str
    )->Optional[Dict]:
        with session_scope() as session:
            repo=AgentTraceRepository(session)
            return repo.update_prompt(trace_id,prompt)

    def complete_trace(
        self,
        trace_id:str,
        llm_response:str,
        output_data:Optional[Dict]=None,
        tokens_input:int=0,
        tokens_output:int=0,
        status:str="completed",
        output_summary:Optional[str]=None,
    )->Optional[Dict]:
        with session_scope() as session:
            repo=AgentTraceRepository(session)
            return repo.complete_trace(
                trace_id,
                llm_response,
                output_data,
                tokens_input,
                tokens_output,
                status,
                output_summary=output_summary,
            )

    def fail_trace(
        self,trace_id:str,error_message:str
    )->Optional[Dict]:
        with session_scope() as session:
            repo=AgentTraceRepository(session)
            return repo.fail_trace(trace_id,error_message)

    def delete_traces_by_project(self,project_id:str)->int:
        with session_scope() as session:
            repo=AgentTraceRepository(session)
            return repo.delete_by_project(project_id)

    def get_llm_job(self,job_id:str)->Optional[Dict]:
        with session_scope() as session:
            repo=LlmJobRepository(session)
            job=repo.get(job_id)
            return repo.to_dict(job) if job else None

    def get_llm_jobs_by_agent(self,agent_id:str)->List[Dict]:
        with session_scope() as session:
            repo=LlmJobRepository(session)
            return repo.get_by_agent(agent_id)

    def create_workflow_snapshot(
        self,
        project_id:str,
        agent_id:str,
        workflow_run_id:str,
        step_type:str,
        step_id:str,
        label:str,
        state_data:Dict,
        worker_tasks:List,
    )->Dict:
        with session_scope() as session:
            repo=WorkflowSnapshotRepository(session)
            return repo.create_snapshot(
                project_id,
                agent_id,
                workflow_run_id,
                step_type,
                step_id,
                label,
                state_data,
                worker_tasks,
            )

    def get_workflow_snapshots_by_agent(
        self,agent_id:str
    )->List[Dict]:
        with session_scope() as session:
            repo=WorkflowSnapshotRepository(session)
            return repo.get_by_agent(agent_id)

    def get_latest_workflow_snapshots(
        self,agent_id:str
    )->List[Dict]:
        with session_scope() as session:
            repo=WorkflowSnapshotRepository(session)
            return repo.get_latest_run_snapshots(agent_id)

    def get_workflow_snapshots_by_run(
        self,workflow_run_id:str
    )->List[Dict]:
        with session_scope() as session:
            repo=WorkflowSnapshotRepository(session)
            return repo.get_by_workflow_run(workflow_run_id)

    def restore_workflow_snapshot(
        self,snapshot_id:str
    )->Optional[Dict]:
        with session_scope() as session:
            repo=WorkflowSnapshotRepository(session)
            snapshot=repo.get(snapshot_id)
            if not snapshot:
                return None
            repo.invalidate_after(snapshot.workflow_run_id,snapshot_id)
            return repo.mark_restored(snapshot_id)

    def get_workflow_snapshot(self,snapshot_id:str)->Optional[Dict]:
        with session_scope() as session:
            repo=WorkflowSnapshotRepository(session)
            snapshot=repo.get(snapshot_id)
            return repo.to_dict(snapshot) if snapshot else None
