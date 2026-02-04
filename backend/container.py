from dependency_injector import containers,providers

from events.event_bus import EventBus
from events.websocket_emitter import WebSocketEmitter
from services.project_service import ProjectService
from services.agent_service import AgentService
from services.workflow_service import WorkflowService
from services.simulation_service import SimulationService
from services.intervention_service import InterventionService
from services.trace_service import TraceService


class Container(containers.DeclarativeContainer):
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
