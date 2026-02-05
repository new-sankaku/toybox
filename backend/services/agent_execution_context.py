from datetime import datetime
from typing import Dict,Any,Optional,Callable
from agents.base import AgentContext,AgentType
from agents.retry_strategy import wait_for_provider_available
from providers.health_monitor import get_health_monitor
from config_loaders.workflow_config import get_workflow_dependencies
from middleware.logger import get_logger


class AgentExecutionContextBuilder:
    def __init__(
        self,
        project_service,
        agent_service,
        trace_service,
    )->None:
        self._project_service=project_service
        self._agent_service=agent_service
        self._trace_service=trace_service
        self._logger=get_logger()

    def validate_agent(self,agent_id:str)->Optional[Dict[str,Any]]:
        agent=self._agent_service.get_agent(agent_id)
        if not agent:
            self._logger.warning(f"Agent not found: agent_id={agent_id}")
        return agent

    def validate_project(self,project_id:str)->Optional[Dict[str,Any]]:
        project=self._project_service.get_project(project_id)
        if not project:
            self._logger.warning(f"Project not found: project_id={project_id}")
        return project

    def can_start_agent(self,project_id:str,agent_type:str)->bool:
        workflow_deps=get_workflow_dependencies()
        dependencies=workflow_deps.get(agent_type,[])
        agents=self._agent_service.get_agents_by_project(project_id)
        for dep_type in dependencies:
            dep_agent=next((a for a in agents if a["type"]==dep_type),None)
            if not dep_agent or dep_agent["status"]!="completed":
                return False
        return True

    def get_previous_outputs(self,project_id:str,agent_type:str)->Dict[str,Any]:
        workflow_deps=get_workflow_dependencies()
        dependencies=workflow_deps.get(agent_type,[])
        agents=self._agent_service.get_agents_by_project(project_id)
        outputs={}
        for dep_type in dependencies:
            dep_agent=next((a for a in agents if a["type"]==dep_type),None)
            if dep_agent and dep_agent["status"]=="completed":
                traces=self._trace_service.get_traces_by_agent(dep_agent["id"])
                if traces:
                    latest=traces[0]
                    entry={"content":latest.get("llmResponse","")}
                    summary=latest.get("outputSummary") or latest.get("output_summary")
                    if summary:
                        entry["summary"]=summary
                    outputs[dep_type]=entry
        return outputs

    def build_context(
        self,
        project:Dict[str,Any],
        agent:Dict[str,Any],
        callbacks:Dict[str,Callable],
    )->AgentContext:
        agent_type=AgentType(agent["type"])
        advanced_settings=project.get("advancedSettings",{})
        agent_config=dict(project.get("config",{}))
        agent_config["advancedSettings"]=advanced_settings
        return AgentContext(
            project_id=project["id"],
            agent_id=agent["id"],
            agent_type=agent_type,
            project_concept=project.get("concept",{}),
            previous_outputs=self.get_previous_outputs(project["id"],agent["type"]),
            config=agent_config,
            on_progress=callbacks.get("on_progress"),
            on_log=callbacks.get("on_log"),
            on_checkpoint=callbacks.get("on_checkpoint"),
            on_speech=callbacks.get("on_speech"),
        )

    def mark_agent_running(self,agent_id:str,current_task:str="初期化中")->None:
        self._agent_service.update_agent(agent_id,{
            "status":"running",
            "progress":0,
            "startedAt":datetime.now().isoformat(),
            "currentTask":current_task,
        })

    def mark_agent_completed(
        self,
        agent_id:str,
        tokens_used:int=0,
    )->None:
        self._agent_service.update_agent(agent_id,{
            "status":"completed",
            "progress":100,
            "completedAt":datetime.now().isoformat(),
            "currentTask":None,
            "tokensUsed":tokens_used,
        })

    def mark_agent_failed(self,agent_id:str,error:str)->None:
        self._agent_service.update_agent(agent_id,{
            "status":"failed",
            "error":error,
            "currentTask":None,
        })

    def mark_agent_waiting_approval(self,agent_id:str)->None:
        self._agent_service.update_agent(agent_id,{
            "status":"waiting_approval",
            "currentTask":"レビュー待ち",
        })

    def get_provider_id(self,project:Dict,agent_type:str)->Optional[str]:
        ai_services=project.get("aiServices",{})
        text_service=ai_services.get("text",{})
        return text_service.get("provider")

    async def wait_for_provider_if_needed(
        self,
        project:Dict,
        agent_id:str,
        agent_type:str,
        on_waiting:Callable[[int],None],
        on_recovered:Callable[[int],None],
    )->None:
        provider_id=self.get_provider_id(project,agent_type)
        if not provider_id:
            return
        health_monitor=get_health_monitor()
        health=health_monitor.get_health_status(provider_id)
        if health and not health.available:
            await wait_for_provider_available(
                health_monitor,
                provider_id,
                check_interval=10.0,
                on_waiting=on_waiting,
                on_recovered=on_recovered,
            )
