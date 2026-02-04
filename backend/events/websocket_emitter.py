from typing import Dict,Any,Optional
from events.event_bus import EventBus
from events.events import (
    SystemLogCreated,
    AgentStarted,
    AgentProgress,
    AgentCompleted,
    AgentFailed,
    AgentResumed,
    AgentRetried,
    CheckpointCreated,
    CheckpointResolved,
    AssetCreated,
    AssetUpdated,
    PhaseChanged,
    MetricsUpdated,
)
from middleware.logger import get_logger


class WebSocketEmitter:
    def __init__(self,event_bus:EventBus):
        self._sio=None
        self._event_bus=event_bus
        self._logger=get_logger()
        self._register_handlers()

    def set_sio(self,sio)->None:
        self._sio=sio

    def _emit(self,event:str,data:Dict[str,Any],project_id:str)->None:
        if self._sio:
            try:
                self._sio.emit(event,data,room=f"project:{project_id}")
            except Exception as e:
                self._logger.warning(f"WebSocketEmitter error emitting {event}: {e}")

    def _register_handlers(self)->None:
        self._event_bus.subscribe(SystemLogCreated,self._on_system_log_created)
        self._event_bus.subscribe(AgentStarted,self._on_agent_started)
        self._event_bus.subscribe(AgentProgress,self._on_agent_progress)
        self._event_bus.subscribe(AgentCompleted,self._on_agent_completed)
        self._event_bus.subscribe(AgentFailed,self._on_agent_failed)
        self._event_bus.subscribe(AgentResumed,self._on_agent_resumed)
        self._event_bus.subscribe(AgentRetried,self._on_agent_retried)
        self._event_bus.subscribe(CheckpointCreated,self._on_checkpoint_created)
        self._event_bus.subscribe(CheckpointResolved,self._on_checkpoint_resolved)
        self._event_bus.subscribe(AssetCreated,self._on_asset_created)
        self._event_bus.subscribe(AssetUpdated,self._on_asset_updated)
        self._event_bus.subscribe(PhaseChanged,self._on_phase_changed)
        self._event_bus.subscribe(MetricsUpdated,self._on_metrics_updated)

    def _on_system_log_created(self,event:SystemLogCreated)->None:
        self._emit(
            "system_log:created",
            {"projectId":event.project_id,"log":event.log},
            event.project_id,
        )

    def _on_agent_started(self,event:AgentStarted)->None:
        self._emit(
            "agent:started",
            {
                "agentId":event.agent_id,
                "projectId":event.project_id,
                "agent":event.agent,
            },
            event.project_id,
        )

    def _on_agent_progress(self,event:AgentProgress)->None:
        self._emit(
            "agent:progress",
            {
                "agentId":event.agent_id,
                "projectId":event.project_id,
                "progress":event.progress,
                "currentTask":event.current_task,
                "tokensUsed":event.tokens_used,
                "message":event.message,
            },
            event.project_id,
        )

    def _on_agent_completed(self,event:AgentCompleted)->None:
        data={"agentId":event.agent_id,"projectId":event.project_id}
        if event.agent:
            data["agent"]=event.agent
        self._emit("agent:completed",data,event.project_id)

    def _on_agent_failed(self,event:AgentFailed)->None:
        self._emit(
            "agent:failed",
            {
                "agentId":event.agent_id,
                "projectId":event.project_id,
                "reason":event.reason,
            },
            event.project_id,
        )

    def _on_agent_resumed(self,event:AgentResumed)->None:
        self._emit(
            "agent:resumed",
            {
                "agentId":event.agent_id,
                "projectId":event.project_id,
                "agent":event.agent,
                "reason":event.reason,
            },
            event.project_id,
        )

    def _on_agent_retried(self,event:AgentRetried)->None:
        self._emit(
            "agent:retry",
            {
                "agentId":event.agent_id,
                "projectId":event.project_id,
                "agent":event.agent,
                "previousStatus":event.previous_status,
            },
            event.project_id,
        )

    def _on_checkpoint_created(self,event:CheckpointCreated)->None:
        self._emit(
            "checkpoint:created",
            {
                "checkpointId":event.checkpoint_id,
                "projectId":event.project_id,
                "agentId":event.agent_id,
                "checkpoint":event.checkpoint,
                "autoApproved":event.auto_approved,
            },
            event.project_id,
        )

    def _on_checkpoint_resolved(self,event:CheckpointResolved)->None:
        self._emit(
            "checkpoint:resolved",
            {
                "checkpointId":event.checkpoint_id,
                "projectId":event.project_id,
                "checkpoint":event.checkpoint,
                "resolution":event.resolution,
            },
            event.project_id,
        )

    def _on_asset_created(self,event:AssetCreated)->None:
        self._emit(
            "asset:created",
            {
                "projectId":event.project_id,
                "asset":event.asset,
                "autoApproved":event.auto_approved,
            },
            event.project_id,
        )

    def _on_asset_updated(self,event:AssetUpdated)->None:
        self._emit(
            "asset:updated",
            {
                "projectId":event.project_id,
                "asset":event.asset,
                "autoApproved":event.auto_approved,
            },
            event.project_id,
        )

    def _on_phase_changed(self,event:PhaseChanged)->None:
        self._emit(
            "phase:changed",
            {
                "projectId":event.project_id,
                "phase":event.phase,
                "phaseName":event.phase_name,
            },
            event.project_id,
        )

    def _on_metrics_updated(self,event:MetricsUpdated)->None:
        self._emit(
            "metrics:update",
            {"projectId":event.project_id,"metrics":event.metrics},
            event.project_id,
        )
