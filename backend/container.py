from dependency_injector import containers,providers

from events.event_bus import EventBus
from events.websocket_emitter import WebSocketEmitter
from services.project_service import ProjectService
from services.agent_service import AgentService
from services.workflow_service import WorkflowService
from services.simulation import SimulationService
from services.intervention_service import InterventionService
from services.trace_service import TraceService
from services.subscription_manager import SubscriptionManager
from services.backup_service import BackupService
from services.archive_service import ArchiveService
from services.recovery_service import RecoveryService
from services.agent_execution_service import AgentExecutionService


class Container(containers.DeclarativeContainer):
    db_path=providers.Dependency(instance_of=str,default="")
    sio=providers.Dependency(default=None)

    event_bus=providers.Singleton(EventBus)

    websocket_emitter=providers.Singleton(
        WebSocketEmitter,
        event_bus=event_bus,
    )

    project_service=providers.Singleton(
        ProjectService,
        event_bus=event_bus,
    )

    agent_service=providers.Singleton(
        AgentService,
        event_bus=event_bus,
    )

    workflow_service=providers.Singleton(
        WorkflowService,
        event_bus=event_bus,
    )

    simulation_service=providers.Singleton(
        SimulationService,
        event_bus=event_bus,
    )

    intervention_service=providers.Singleton(
        InterventionService,
        event_bus=event_bus,
    )

    trace_service=providers.Singleton(
        TraceService,
        event_bus=event_bus,
    )

    subscription_manager=providers.Singleton(
        SubscriptionManager,
    )

    backup_service=providers.Singleton(
        BackupService,
        db_path=db_path,
        max_backups=10,
    )

    archive_service=providers.Singleton(
        ArchiveService,
        retention_days=30,
    )

    recovery_service=providers.Singleton(
        RecoveryService,
        sio=sio,
    )

    agent_execution_service=providers.Singleton(
        AgentExecutionService,
        project_service=project_service,
        agent_service=agent_service,
        workflow_service=workflow_service,
        intervention_service=intervention_service,
        trace_service=trace_service,
        event_bus=event_bus,
        sio=sio,
    )
