from datetime import datetime
from typing import Optional,Dict,List,Callable

from events.event_bus import EventBus
from events.events import AgentCompleted
from repositories import AssetRepository,AgentRepository,CheckpointRepository
from middleware.logger import get_logger


class AssetManager:
    def __init__(
        self,
        event_bus:EventBus,
        add_system_log:Callable,
    ):
        self._event_bus=event_bus
        self._add_system_log=add_system_log
        self._logger=get_logger()

    def get_by_project(self,session,project_id:str)->List[Dict]:
        repo=AssetRepository(session)
        return repo.get_by_project(project_id)

    def update(
        self,
        session,
        project_id:str,
        asset_id:str,
        data:Dict,
    )->Optional[Dict]:
        repo=AssetRepository(session)
        asset=repo.get(asset_id)
        if not asset or asset.project_id!=project_id:
            return None

        old_status=asset.approval_status
        result=repo.update_from_dict(project_id,asset_id,data)
        new_status=data.get("approvalStatus")

        if new_status and old_status=="pending" and new_status=="approved":
            self._handle_approval(session,asset,project_id)

        return result

    def _handle_approval(self,session,asset,project_id:str)->None:
        if not asset.agent_id:
            return

        agent_repo=AgentRepository(session)
        cp_repo=CheckpointRepository(session)
        asset_repo=AssetRepository(session)

        agent=agent_repo.get(asset.agent_id)
        if not agent:
            return

        pending_assets=[
            a
            for a in asset_repo.get_pending_by_agent(asset.agent_id)
            if a.id!=asset.id
        ]
        pending_cps=cp_repo.get_pending_by_agent(asset.agent_id)

        if not pending_assets and not pending_cps and agent.status=="waiting_approval":
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

    def request_regeneration(
        self,
        session,
        project_id:str,
        asset_id:str,
        feedback:str,
    )->bool:
        asset_repo=AssetRepository(session)
        asset=asset_repo.get(asset_id)
        if not asset or asset.project_id!=project_id:
            return False

        self._add_system_log(
            session,
            project_id,
            "info",
            "System",
            f"アセット「{asset.name}」の再生成がリクエストされました: {feedback[:100]}",
        )
        return True
