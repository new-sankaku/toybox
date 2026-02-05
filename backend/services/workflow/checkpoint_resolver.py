from datetime import datetime
from typing import Optional,Dict,Callable

from events.event_bus import EventBus
from events.events import (
    AgentCompleted,
    AgentFailed,
    AgentProgress,
    CheckpointResolved,
)
from repositories import CheckpointRepository,AgentRepository
from middleware.logger import get_logger


RESOLUTION_LABELS={
    "approved":"承認",
    "rejected":"却下",
    "revision_requested":"修正要求",
}


class CheckpointResolver:
    def __init__(
        self,
        event_bus:EventBus,
        add_system_log:Callable,
    ):
        self._event_bus=event_bus
        self._add_system_log=add_system_log
        self._logger=get_logger()

    def resolve(
        self,
        session,
        checkpoint_id:str,
        resolution:str,
        feedback:Optional[str]=None,
    )->Optional[Dict]:
        cp_repo=CheckpointRepository(session)
        agent_repo=AgentRepository(session)

        cp=cp_repo.get(checkpoint_id)
        if not cp:
            return None

        result=cp_repo.resolve(checkpoint_id,resolution,feedback)
        project_id=cp.project_id

        self._add_system_log(
            session,
            project_id,
            "info",
            "System",
            f"チェックポイント{RESOLUTION_LABELS.get(resolution, resolution)}: {cp.title}",
        )

        agent=agent_repo.get(cp.agent_id)
        agent_status=self._handle_agent_state_change(
            session,
            cp_repo,
            agent,
            cp,
            checkpoint_id,
            resolution,
            project_id,
        )

        self._event_bus.publish(
            CheckpointResolved(
                project_id=project_id,
                checkpoint_id=checkpoint_id,
                checkpoint=result or {},
                resolution=resolution,
                agent_id=cp.agent_id,
                agent_status=agent_status,
            )
        )

        return result

    def _handle_agent_state_change(
        self,
        session,
        cp_repo:CheckpointRepository,
        agent,
        cp,
        checkpoint_id:str,
        resolution:str,
        project_id:str,
    )->str:
        if not agent:
            return""

        if resolution=="rejected":
            self._handle_rejection(session,agent,project_id)
        elif resolution=="revision_requested":
            self._handle_revision_request(session,cp_repo,agent,checkpoint_id,project_id)
        else:
            self._handle_approval(session,cp_repo,agent,checkpoint_id,project_id)

        return agent.status

    def _handle_rejection(self,session,agent,project_id:str)->None:
        agent.status="failed"
        agent.current_task="却下により中止"
        session.flush()

        self._add_system_log(
            session,
            project_id,
            "warn",
            "System",
            f"{agent.type}が却下されました",
        )

        self._event_bus.publish(
            AgentFailed(
                project_id=project_id,
                agent_id=agent.id,
                reason="rejected",
            )
        )

    def _handle_revision_request(
        self,
        session,
        cp_repo:CheckpointRepository,
        agent,
        checkpoint_id:str,
        project_id:str,
    )->None:
        cp_repo.delete(checkpoint_id)
        agent.progress=80
        agent.status="running"
        agent.current_task="修正中..."
        session.flush()

        self._add_system_log(
            session,
            project_id,
            "info",
            "System",
            f"{agent.type}が修正を開始",
        )

        self._event_bus.publish(
            AgentProgress(
                project_id=project_id,
                agent_id=agent.id,
                progress=80,
                current_task="修正中...",
                tokens_used=agent.tokens_used,
                message="修正要求により再実行",
            )
        )

    def _handle_approval(
        self,
        session,
        cp_repo:CheckpointRepository,
        agent,
        checkpoint_id:str,
        project_id:str,
    )->None:
        other_pending=cp_repo.get_pending_by_agent(agent.id)
        other_pending=[c for c in other_pending if c.id!=checkpoint_id]

        if not other_pending and agent.status=="waiting_approval":
            agent.status="completed"
            agent.progress=100
            agent.completed_at=datetime.now()
            agent.current_task=None
            session.flush()

            self._add_system_log(
                session,
                project_id,
                "info",
                "System",
                f"{agent.type}が承認されました",
            )

            self._event_bus.publish(
                AgentCompleted(
                    project_id=project_id,
                    agent_id=agent.id,
                )
            )
