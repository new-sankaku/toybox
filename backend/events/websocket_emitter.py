from typing import Dict,Any
from events.event_bus import EventBus
from events.events import (
    SystemLogCreated,
    AgentStarted,
    AgentProgress,
    AgentCompleted,
    AgentFailed,
    AgentResumed,
    AgentRetried,
    AgentPaused,
    AgentActivated,
    AgentCreated,
    AgentWaitingResponse,
    AgentSnapshotRestored,
    CheckpointCreated,
    CheckpointResolved,
    AssetCreated,
    AssetUpdated,
    AssetBulkUpdated,
    AssetRegenerationRequested,
    PhaseChanged,
    MetricsUpdated,
    ProjectUpdated,
    ProjectStatusChanged,
    ProjectInitialized,
    ProjectPaused,
    InterventionCreated,
    InterventionAcknowledged,
    InterventionProcessed,
    InterventionDeleted,
    InterventionResponseAdded,
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
        self._event_bus.subscribe(ProjectUpdated,self._on_project_updated)
        self._event_bus.subscribe(ProjectStatusChanged,self._on_project_status_changed)
        self._event_bus.subscribe(ProjectInitialized,self._on_project_initialized)
        self._event_bus.subscribe(ProjectPaused,self._on_project_paused)
        self._event_bus.subscribe(AgentPaused,self._on_agent_paused)
        self._event_bus.subscribe(AgentActivated,self._on_agent_activated)
        self._event_bus.subscribe(AgentCreated,self._on_agent_created)
        self._event_bus.subscribe(AgentWaitingResponse,self._on_agent_waiting_response)
        self._event_bus.subscribe(AgentSnapshotRestored,self._on_agent_snapshot_restored)
        self._event_bus.subscribe(InterventionCreated,self._on_intervention_created)
        self._event_bus.subscribe(InterventionAcknowledged,self._on_intervention_acknowledged)
        self._event_bus.subscribe(InterventionProcessed,self._on_intervention_processed)
        self._event_bus.subscribe(InterventionDeleted,self._on_intervention_deleted)
        self._event_bus.subscribe(InterventionResponseAdded,self._on_intervention_response_added)
        self._event_bus.subscribe(AssetBulkUpdated,self._on_asset_bulk_updated)
        self._event_bus.subscribe(AssetRegenerationRequested,self._on_asset_regeneration_requested)

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
                "error":event.reason,
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
        data={
            "checkpointId":event.checkpoint_id,
            "projectId":event.project_id,
            "checkpoint":event.checkpoint,
            "resolution":event.resolution,
        }
        if event.agent_id:
            data["agentId"]=event.agent_id
        if event.agent_status:
            data["agentStatus"]=event.agent_status
        self._emit("checkpoint:resolved",data,event.project_id)

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

    def _on_project_updated(self,event:ProjectUpdated)->None:
        self._emit(
            "project:updated",
            {"projectId":event.project_id,"updates":event.project},
            event.project_id,
        )

    def _on_project_status_changed(self,event:ProjectStatusChanged)->None:
        data={
            "projectId":event.project_id,
            "status":event.status,
            "previousStatus":event.previous_status,
        }
        if event.retried_agents:
            data["retriedAgents"]=event.retried_agents
        if event.reason:
            data["reason"]=event.reason
        if event.intervention_id:
            data["interventionId"]=event.intervention_id
        self._emit("project:status_changed",data,event.project_id)

    def _on_project_initialized(self,event:ProjectInitialized)->None:
        self._emit(
            "project:initialized",
            {"projectId":event.project_id},
            event.project_id,
        )

    def _on_project_paused(self,event:ProjectPaused)->None:
        data={"projectId":event.project_id}
        if event.reason:
            data["reason"]=event.reason
        if event.intervention_id:
            data["interventionId"]=event.intervention_id
        self._emit("project:paused",data,event.project_id)

    def _on_agent_paused(self,event:AgentPaused)->None:
        self._emit(
            "agent:paused",
            {
                "agentId":event.agent_id,
                "projectId":event.project_id,
                "agent":event.agent,
                "reason":event.reason,
            },
            event.project_id,
        )

    def _on_agent_activated(self,event:AgentActivated)->None:
        data={
            "agentId":event.agent_id,
            "projectId":event.project_id,
            "agent":event.agent,
            "previousStatus":event.previous_status,
        }
        if event.intervention_id:
            data["interventionId"]=event.intervention_id
        self._emit("agent:activated",data,event.project_id)

    def _on_agent_created(self,event:AgentCreated)->None:
        data={
            "agentId":event.agent_id,
            "projectId":event.project_id,
            "agent":event.agent,
        }
        if event.parent_agent_id:
            data["parentAgentId"]=event.parent_agent_id
        self._emit("agent:created",data,event.project_id)

    def _on_agent_waiting_response(self,event:AgentWaitingResponse)->None:
        data={
            "agentId":event.agent_id,
            "projectId":event.project_id,
            "agent":event.agent,
        }
        if event.intervention_id:
            data["interventionId"]=event.intervention_id
        if event.question:
            data["question"]=event.question
        self._emit("agent:waiting_response",data,event.project_id)

    def _on_agent_snapshot_restored(self,event:AgentSnapshotRestored)->None:
        self._emit(
            "agent:snapshot_restored",
            {
                "agentId":event.agent_id,
                "projectId":event.project_id,
                "snapshotId":event.snapshot_id,
                "snapshot":event.snapshot,
            },
            event.project_id,
        )

    def _on_intervention_created(self,event:InterventionCreated)->None:
        self._emit(
            "intervention:created",
            {
                "interventionId":event.intervention_id,
                "projectId":event.project_id,
                "intervention":event.intervention,
            },
            event.project_id,
        )

    def _on_intervention_acknowledged(self,event:InterventionAcknowledged)->None:
        self._emit(
            "intervention:acknowledged",
            {
                "interventionId":event.intervention_id,
                "projectId":event.project_id,
                "intervention":event.intervention,
            },
            event.project_id,
        )

    def _on_intervention_processed(self,event:InterventionProcessed)->None:
        self._emit(
            "intervention:processed",
            {
                "interventionId":event.intervention_id,
                "projectId":event.project_id,
                "intervention":event.intervention,
            },
            event.project_id,
        )

    def _on_intervention_deleted(self,event:InterventionDeleted)->None:
        self._emit(
            "intervention:deleted",
            {
                "interventionId":event.intervention_id,
                "projectId":event.project_id,
            },
            event.project_id,
        )

    def _on_intervention_response_added(self,event:InterventionResponseAdded)->None:
        data={
            "interventionId":event.intervention_id,
            "projectId":event.project_id,
            "intervention":event.intervention,
        }
        if event.sender:
            data["sender"]=event.sender
        if event.agent_id:
            data["agentId"]=event.agent_id
        self._emit("intervention:response_added",data,event.project_id)

    def _on_asset_bulk_updated(self,event:AssetBulkUpdated)->None:
        self._emit(
            "assets:bulk_updated",
            {
                "projectId":event.project_id,
                "assets":event.assets,
                "status":event.status,
            },
            event.project_id,
        )

    def _on_asset_regeneration_requested(self,event:AssetRegenerationRequested)->None:
        self._emit(
            "asset:regeneration_requested",
            {
                "projectId":event.project_id,
                "assetId":event.asset_id,
                "feedback":event.feedback,
            },
            event.project_id,
        )
