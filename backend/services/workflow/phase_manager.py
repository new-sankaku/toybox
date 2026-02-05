from datetime import datetime
from typing import Callable,Set

from events.event_bus import EventBus
from events.events import PhaseChanged
from repositories import ProjectRepository,CheckpointRepository
from middleware.logger import get_logger


PHASE1_CHECKPOINT_TYPES:Set[str]={
    "concept_review",
    "task_review_1",
    "concept_detail_review",
    "scenario_review",
    "world_review",
    "game_design_review",
    "tech_spec_review",
}


class PhaseManager:
    def __init__(
        self,
        event_bus:EventBus,
        add_system_log:Callable,
    ):
        self._event_bus=event_bus
        self._add_system_log=add_system_log
        self._logger=get_logger()

    def check_phase_advancement(self,session,project_id:str)->None:
        proj_repo=ProjectRepository(session)
        cp_repo=CheckpointRepository(session)

        project=proj_repo.get(project_id)
        if not project:
            return

        current_phase=project.current_phase
        if current_phase!=1:
            return

        project_checkpoints=cp_repo.get_by_project(project_id)
        phase1_checkpoints=[
            c for c in project_checkpoints if c["type"] in PHASE1_CHECKPOINT_TYPES
        ]

        if not phase1_checkpoints:
            return

        all_approved=all(c["status"]=="approved" for c in phase1_checkpoints)
        if not all_approved:
            return

        project.current_phase=2
        project.updated_at=datetime.now()
        session.flush()

        self._add_system_log(
            session,
            project_id,
            "info",
            "System",
            "Phase 2: 実装 に移行しました",
        )

        self._event_bus.publish(
            PhaseChanged(
                project_id=project_id,
                phase=2,
                phase_name="Phase 2: 実装",
            )
        )

        self._logger.info(f"Project {project_id} advanced to Phase 2")
