from datetime import datetime
from typing import Dict,Callable
from events.events import (
    AgentStarted,AgentProgress,AgentCompleted,AgentFailed,
    AgentCreated,AgentWaitingResponse,
    CheckpointCreated,InterventionAcknowledged,
)
from middleware.logger import get_logger


class AgentEventEmitter:
    def __init__(
        self,
        agent_service,
        workflow_service,
        intervention_service,
        event_bus=None,
        sio=None,
    )->None:
        self._agent_service=agent_service
        self._workflow_service=workflow_service
        self._intervention_service=intervention_service
        self._event_bus=event_bus
        self._sio=sio
        self._logger=get_logger()

    def _emit_socket(self,event:str,data:Dict,project_id:str)->None:
        if self._sio:
            try:
                self._sio.emit(event,data,room=f"project:{project_id}")
            except Exception as e:
                self._logger.error(f"Error emitting {event}: {e}",exc_info=True)

    def emit_started(self,agent_id:str,project_id:str)->None:
        if self._event_bus:
            agent=self._agent_service.get_agent(agent_id)
            self._event_bus.publish(AgentStarted(
                project_id=project_id,
                agent_id=agent_id,
                agent=agent,
            ))

    def emit_completed(self,agent_id:str,project_id:str)->None:
        if self._event_bus:
            agent=self._agent_service.get_agent(agent_id)
            self._event_bus.publish(AgentCompleted(
                project_id=project_id,
                agent_id=agent_id,
                agent=agent,
            ))

    def emit_failed(self,agent_id:str,project_id:str,reason:str)->None:
        if self._event_bus:
            self._event_bus.publish(AgentFailed(
                project_id=project_id,
                agent_id=agent_id,
                reason=reason,
            ))

    def emit_progress(
        self,
        agent_id:str,
        project_id:str,
        progress:int,
        task:str,
        message:str="",
    )->None:
        self._agent_service.update_agent(agent_id,{
            "progress":progress,
            "currentTask":task,
        })
        if self._event_bus:
            self._event_bus.publish(AgentProgress(
                project_id=project_id,
                agent_id=agent_id,
                progress=progress,
                current_task=task,
                message=message,
            ))
        self._check_pending_interventions(agent_id,project_id)

    def _check_pending_interventions(self,agent_id:str,project_id:str)->None:
        pending=self._intervention_service.get_pending_interventions_for_agent(agent_id)
        if not pending:
            return
        agent=self._agent_service.get_agent(agent_id)
        if not agent or agent.get("status")!="running":
            return
        for intervention in pending:
            acked=self._intervention_service.acknowledge_intervention(intervention["id"])
            if self._event_bus:
                self._event_bus.publish(InterventionAcknowledged(
                    project_id=project_id,
                    intervention_id=intervention["id"],
                    intervention=acked,
                ))
        self._agent_service.update_agent(agent_id,{
            "status":"waiting_response",
            "currentTask":"連絡を確認中",
        })
        if self._event_bus:
            self._event_bus.publish(AgentWaitingResponse(
                project_id=project_id,
                agent_id=agent_id,
                agent=self._agent_service.get_agent(agent_id),
            ))

    def emit_log(
        self,
        agent_id:str,
        project_id:str,
        level:str,
        message:str,
    )->None:
        self._agent_service.add_agent_log(agent_id,level,message)
        self._emit_socket("agent:log",{
            "agentId":agent_id,
            "entry":{
                "id":f"{agent_id}_{datetime.now().timestamp()}",
                "timestamp":datetime.now().isoformat(),
                "level":level,
                "message":message,
            }
        },project_id)

    def emit_checkpoint(
        self,
        agent_id:str,
        project_id:str,
        cp_type:str,
        data:Dict,
    )->None:
        checkpoint=self._workflow_service.create_checkpoint(project_id,agent_id,{
            "type":cp_type,
            "title":data.get("title","レビュー"),
            "description":data.get("description",""),
            "output":data.get("output",{}),
        })
        self._agent_service.update_agent(agent_id,{"status":"waiting_approval"})
        if self._event_bus:
            self._event_bus.publish(CheckpointCreated(
                project_id=project_id,
                checkpoint_id=checkpoint.get("id",""),
                agent_id=agent_id,
                checkpoint=checkpoint,
            ))
        self.emit_pool_speech(agent_id,project_id,"waiting_approval")

    def emit_speech(
        self,
        agent_id:str,
        project_id:str,
        message:str,
        source:str="llm",
    )->None:
        self._emit_socket("agent:speech",{
            "agentId":agent_id,
            "projectId":project_id,
            "message":message,
            "source":source,
            "timestamp":datetime.now().isoformat(),
        },project_id)

    def emit_pool_speech(self,agent_id:str,project_id:str,condition:str)->None:
        try:
            agent=self._agent_service.get_agent(agent_id)
            if not agent:
                return
            agent_type=agent.get("type","")
            from services.agent_speech_service import get_agent_speech_service
            comment=get_agent_speech_service().get_pool_comment(agent_type,condition)
            if comment:
                self.emit_speech(agent_id,project_id,comment,"pool")
        except Exception as e:
            self._logger.error(f"emit_pool_speech error: {e}",exc_info=True)

    def emit_waiting_provider(
        self,
        agent_id:str,
        project_id:str,
        provider_id:str,
        attempt:int,
    )->None:
        self._emit_socket("agent:waiting_provider",{
            "agentId":agent_id,
            "projectId":project_id,
            "providerId":provider_id,
            "attempt":attempt,
        },project_id)

    def emit_worker_created(
        self,
        project_id:str,
        parent_agent_id:str,
        worker_type:str,
        task:str,
    )->str:
        worker=self._agent_service.create_worker_agent(
            project_id,parent_agent_id,worker_type,task
        )
        worker_id=worker["id"]
        if self._event_bus:
            self._event_bus.publish(AgentCreated(
                project_id=project_id,
                agent_id=worker_id,
                parent_agent_id=parent_agent_id,
                agent=worker,
            ))
        return worker_id

    def emit_worker_status(
        self,
        project_id:str,
        worker_id:str,
        status:str,
        data:Dict,
    )->None:
        update_data={"status":status}
        if status=="running":
            update_data["startedAt"]=datetime.now().isoformat()
            update_data["progress"]=data.get("progress",0)
        elif status=="completed":
            update_data["completedAt"]=datetime.now().isoformat()
            update_data["progress"]=100
            update_data["tokensUsed"]=data.get("tokensUsed",0)
            update_data["inputTokens"]=data.get("inputTokens",0)
            update_data["outputTokens"]=data.get("outputTokens",0)
        elif status=="failed":
            update_data["error"]=data.get("error","")
        if"currentTask" in data:
            update_data["currentTask"]=data["currentTask"]
        self._agent_service.update_agent(worker_id,update_data)
        self._emit_socket(f"agent:{status}",{
            "agentId":worker_id,
            "projectId":project_id,
            "agent":self._agent_service.get_agent(worker_id)
        },project_id)

    def create_callbacks(
        self,
        agent_id:str,
        project_id:str,
    )->Dict[str,Callable]:
        return {
            "on_progress":lambda p,t:self.emit_progress(agent_id,project_id,p,t),
            "on_log":lambda l,m:self.emit_log(agent_id,project_id,l,m),
            "on_checkpoint":lambda t,d:self.emit_checkpoint(agent_id,project_id,t,d),
            "on_speech":lambda msg:self.emit_speech(agent_id,project_id,msg,"llm"),
        }
