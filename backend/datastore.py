import threading
from typing import Optional,Dict,List,Any

from models.database import init_db
from agent_settings import QualityCheckConfig
from services.project_service import ProjectService
from services.agent_service import AgentService
from services.workflow_service import WorkflowService
from services.simulation_service import SimulationService
from services.intervention_service import InterventionService
from services.trace_service import TraceService


class DataStore:
    def __init__(
        self,
        project_service:ProjectService,
        agent_service:AgentService,
        workflow_service:WorkflowService,
        simulation_service:SimulationService,
        intervention_service:InterventionService,
        trace_service:TraceService,
    ):
        init_db()
        self._project=project_service
        self._agent=agent_service
        self._workflow=workflow_service
        self._simulation=simulation_service
        self._intervention=intervention_service
        self._trace=trace_service
        self.subscriptions:Dict[str,set]={}
        self._lock=threading.Lock()
        self._project.init_sample_data_if_empty()

    def start_simulation(self):
        self._simulation.start_simulation()

    def stop_simulation(self):
        self._simulation.stop_simulation()

    def get_projects(self)->List[Dict]:
        return self._project.get_projects()

    def get_project(self,project_id:str)->Optional[Dict]:
        return self._project.get_project(project_id)

    def create_project(self,data:Dict)->Dict:
        return self._project.create_project(data)

    def update_project(self,project_id:str,data:Dict)->Optional[Dict]:
        return self._project.update_project(project_id,data)

    def delete_project(self,project_id:str)->bool:
        return self._project.delete_project(project_id)

    def start_project(self,project_id:str)->Optional[Dict]:
        return self._project.start_project(project_id)

    def pause_project(self,project_id:str)->Optional[Dict]:
        return self._project.pause_project(project_id)

    def resume_project(self,project_id:str)->Optional[Dict]:
        return self._project.resume_project(project_id)

    def initialize_project(self,project_id:str)->Optional[Dict]:
        return self._project.initialize_project(project_id)

    def brushup_project(
        self,project_id:str,options:Optional[Dict]=None
    )->Optional[Dict]:
        return self._project.brushup_project(project_id,options)

    def get_project_metrics(self,project_id:str)->Optional[Dict]:
        return self._project.get_project_metrics(project_id)

    def update_project_metrics(self,project_id:str,data:Dict)->Dict:
        return self._project.update_project_metrics(project_id,data)

    def refresh_project_metrics(self,project_id:str)->None:
        self._project.refresh_project_metrics(project_id)

    def accumulate_generation_counts(
        self,project_id:str,gen_counts:Dict[str,Any]
    )->None:
        self._project.accumulate_generation_counts(project_id,gen_counts)

    def get_ai_services(self,project_id:str)->Dict[str,Dict]:
        return self._project.get_ai_services(project_id)

    def update_ai_service(
        self,project_id:str,service_type:str,config:Dict
    )->Optional[Dict]:
        return self._project.update_ai_service(project_id,service_type,config)

    def update_ai_services(
        self,project_id:str,ai_services:Dict[str,Dict]
    )->Optional[Dict]:
        return self._project.update_ai_services(project_id,ai_services)

    def get_system_logs(self,project_id:str)->List[Dict]:
        return self._project.get_system_logs(project_id)

    def get_agents_by_project(
        self,project_id:str,include_workers:bool=True
    )->List[Dict]:
        return self._agent.get_agents_by_project(project_id,include_workers)

    def get_workers_by_parent(self,parent_agent_id:str)->List[Dict]:
        return self._agent.get_workers_by_parent(parent_agent_id)

    def get_agent(self,agent_id:str)->Optional[Dict]:
        return self._agent.get_agent(agent_id)

    def get_agent_logs(self,agent_id:str)->List[Dict]:
        return self._agent.get_agent_logs(agent_id)

    def create_agent(self,project_id:str,agent_type:str)->Dict:
        return self._agent.create_agent(project_id,agent_type)

    def create_worker_agent(
        self,
        project_id:str,
        parent_agent_id:str,
        worker_type:str,
        task:str,
    )->Dict:
        return self._agent.create_worker_agent(
            project_id,parent_agent_id,worker_type,task
        )

    def update_agent(self,agent_id:str,data:Dict)->Optional[Dict]:
        return self._agent.update_agent(agent_id,data)

    def add_agent_log(
        self,
        agent_id:str,
        level:str,
        message:str,
        progress:Optional[int]=None,
    )->None:
        self._agent.add_agent_log(agent_id,level,message,progress)

    def retry_agent(self,agent_id:str)->Optional[Dict]:
        return self._agent.retry_agent(agent_id)

    def pause_agent(self,agent_id:str)->Optional[Dict]:
        return self._agent.pause_agent(agent_id)

    def resume_agent(self,agent_id:str)->Optional[Dict]:
        return self._agent.resume_agent(agent_id)

    def get_retryable_agents(self,project_id:str)->List[Dict]:
        return self._agent.get_retryable_agents(project_id)

    def get_interrupted_agents(
        self,project_id:Optional[str]=None
    )->List[Dict]:
        return self._agent.get_interrupted_agents(project_id)

    def activate_agent_for_intervention(
        self,agent_id:str,intervention_id:str
    )->Dict:
        return self._agent.activate_agent_for_intervention(
            agent_id,intervention_id
        )

    def start_next_agents(self,project_id:str)->List[Dict]:
        return self._agent.start_next_agents(project_id)

    @property
    def agents(self)->Dict[str,Dict]:
        return self._agent.agents

    def create_agent_memory(
        self,
        category:str,
        agent_type:str,
        content:str,
        project_id:Optional[str]=None,
        source_project_id:Optional[str]=None,
        relevance_score:int=100,
    )->Dict:
        return self._agent.create_agent_memory(
            category,
            agent_type,
            content,
            project_id,
            source_project_id,
            relevance_score,
        )

    def get_agent_memories(
        self,
        agent_type:str,
        project_id:Optional[str]=None,
        categories:Optional[List[str]]=None,
        limit:int=10,
    )->List[Dict]:
        return self._agent.get_agent_memories(
            agent_type,project_id,categories,limit
        )

    def get_checkpoints_by_project(self,project_id:str)->List[Dict]:
        return self._workflow.get_checkpoints_by_project(project_id)

    def get_checkpoint(self,checkpoint_id:str)->Optional[Dict]:
        return self._workflow.get_checkpoint(checkpoint_id)

    def create_checkpoint(
        self,project_id:str,agent_id:str,data:Dict
    )->Dict:
        return self._workflow.create_checkpoint(project_id,agent_id,data)

    def resolve_checkpoint(
        self,
        checkpoint_id:str,
        resolution:str,
        feedback:Optional[str]=None,
    )->Optional[Dict]:
        return self._workflow.resolve_checkpoint(
            checkpoint_id,resolution,feedback
        )

    @property
    def checkpoints(self)->Dict[str,Dict]:
        return self._workflow.checkpoints

    def get_assets_by_project(self,project_id:str)->List[Dict]:
        return self._workflow.get_assets_by_project(project_id)

    def update_asset(
        self,project_id:str,asset_id:str,data:Dict
    )->Optional[Dict]:
        return self._workflow.update_asset(project_id,asset_id,data)

    def request_asset_regeneration(
        self,project_id:str,asset_id:str,feedback:str
    )->None:
        self._workflow.request_asset_regeneration(project_id,asset_id,feedback)

    def get_quality_settings(
        self,project_id:str
    )->Dict[str,QualityCheckConfig]:
        return self._workflow.get_quality_settings(project_id)

    def set_quality_setting(
        self,project_id:str,agent_type:str,config:QualityCheckConfig
    )->None:
        self._workflow.set_quality_setting(project_id,agent_type,config)

    def reset_quality_settings(self,project_id:str)->None:
        self._workflow.reset_quality_settings(project_id)

    def get_quality_setting_for_agent(
        self,project_id:str,agent_type:str
    )->QualityCheckConfig:
        return self._workflow.get_quality_setting_for_agent(
            project_id,agent_type
        )

    def get_auto_approval_rules(self,project_id:str)->List[Dict]:
        return self._workflow.get_auto_approval_rules(project_id)

    def set_auto_approval_rules(
        self,project_id:str,rules:List[Dict]
    )->List[Dict]:
        return self._workflow.set_auto_approval_rules(project_id,rules)

    def get_interventions_by_project(self,project_id:str)->List[Dict]:
        return self._intervention.get_interventions_by_project(project_id)

    def get_intervention(self,intervention_id:str)->Optional[Dict]:
        return self._intervention.get_intervention(intervention_id)

    def create_intervention(
        self,
        project_id:str,
        target_type:str,
        target_agent_id:Optional[str],
        priority:str,
        message:str,
        attached_file_ids:List[str],
    )->Dict:
        return self._intervention.create_intervention(
            project_id,
            target_type,
            target_agent_id,
            priority,
            message,
            attached_file_ids,
        )

    def acknowledge_intervention(
        self,intervention_id:str
    )->Optional[Dict]:
        return self._intervention.acknowledge_intervention(intervention_id)

    def process_intervention(self,intervention_id:str)->Optional[Dict]:
        return self._intervention.process_intervention(intervention_id)

    def deliver_intervention(self,intervention_id:str)->Optional[Dict]:
        return self._intervention.deliver_intervention(intervention_id)

    def delete_intervention(self,intervention_id:str)->bool:
        return self._intervention.delete_intervention(intervention_id)

    def get_pending_interventions_for_agent(
        self,agent_id:str
    )->List[Dict]:
        return self._intervention.get_pending_interventions_for_agent(agent_id)

    def add_intervention_response(
        self,
        intervention_id:str,
        sender:str,
        message:str,
        agent_id:str=None,
    )->Optional[Dict]:
        return self._intervention.add_intervention_response(
            intervention_id,sender,message,agent_id
        )

    def respond_to_intervention(
        self,intervention_id:str,message:str
    )->Optional[Dict]:
        return self._intervention.respond_to_intervention(
            intervention_id,message
        )

    def get_uploaded_files_by_project(self,project_id:str)->List[Dict]:
        return self._intervention.get_uploaded_files_by_project(project_id)

    def get_uploaded_file(self,file_id:str)->Optional[Dict]:
        return self._intervention.get_uploaded_file(file_id)

    def create_uploaded_file(
        self,
        project_id:str,
        filename:str,
        original_filename:str,
        mime_type:str,
        category:str,
        size_bytes:int,
        description:str,
    )->Dict:
        return self._intervention.create_uploaded_file(
            project_id,
            filename,
            original_filename,
            mime_type,
            category,
            size_bytes,
            description,
        )

    def delete_uploaded_file(self,file_id:str)->bool:
        return self._intervention.delete_uploaded_file(file_id)

    def update_uploaded_file(
        self,file_id:str,data:Dict
    )->Optional[Dict]:
        return self._intervention.update_uploaded_file(file_id,data)

    def get_traces_by_project(
        self,project_id:str,limit:int=100
    )->List[Dict]:
        return self._trace.get_traces_by_project(project_id,limit)

    def get_traces_by_agent(self,agent_id:str)->List[Dict]:
        return self._trace.get_traces_by_agent(agent_id)

    def get_trace(self,trace_id:str)->Optional[Dict]:
        return self._trace.get_trace(trace_id)

    def create_trace(
        self,
        project_id:str,
        agent_id:str,
        agent_type:str,
        input_context:Optional[Dict]=None,
        model_used:Optional[str]=None,
    )->Dict:
        return self._trace.create_trace(
            project_id,agent_id,agent_type,input_context,model_used
        )

    def update_trace_prompt(
        self,trace_id:str,prompt:str
    )->Optional[Dict]:
        return self._trace.update_trace_prompt(trace_id,prompt)

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
        return self._trace.complete_trace(
            trace_id,
            llm_response,
            output_data,
            tokens_input,
            tokens_output,
            status,
            output_summary,
        )

    def fail_trace(
        self,trace_id:str,error_message:str
    )->Optional[Dict]:
        return self._trace.fail_trace(trace_id,error_message)

    def delete_traces_by_project(self,project_id:str)->int:
        return self._trace.delete_traces_by_project(project_id)

    def get_llm_job(self,job_id:str)->Optional[Dict]:
        return self._trace.get_llm_job(job_id)

    def get_llm_jobs_by_agent(self,agent_id:str)->List[Dict]:
        return self._trace.get_llm_jobs_by_agent(agent_id)

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
        return self._trace.create_workflow_snapshot(
            project_id,
            agent_id,
            workflow_run_id,
            step_type,
            step_id,
            label,
            state_data,
            worker_tasks,
        )

    def get_workflow_snapshots_by_agent(self,agent_id:str)->List[Dict]:
        return self._trace.get_workflow_snapshots_by_agent(agent_id)

    def get_latest_workflow_snapshots(self,agent_id:str)->List[Dict]:
        return self._trace.get_latest_workflow_snapshots(agent_id)

    def get_workflow_snapshots_by_run(
        self,workflow_run_id:str
    )->List[Dict]:
        return self._trace.get_workflow_snapshots_by_run(workflow_run_id)

    def restore_workflow_snapshot(self,snapshot_id:str)->Optional[Dict]:
        return self._trace.restore_workflow_snapshot(snapshot_id)

    def get_workflow_snapshot(self,snapshot_id:str)->Optional[Dict]:
        return self._trace.get_workflow_snapshot(snapshot_id)

    def add_subscription(self,project_id:str,sid:str):
        with self._lock:
            if project_id not in self.subscriptions:
                self.subscriptions[project_id]=set()
            self.subscriptions[project_id].add(sid)

    def remove_subscription(self,project_id:str,sid:str):
        with self._lock:
            if project_id in self.subscriptions:
                self.subscriptions[project_id].discard(sid)

    def remove_all_subscriptions(self,sid:str):
        with self._lock:
            for project_id in self.subscriptions:
                self.subscriptions[project_id].discard(sid)

    def get_subscribers(self,project_id:str)->set:
        with self._lock:
            return self.subscriptions.get(project_id,set()).copy()
