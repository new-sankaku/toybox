from datetime import datetime
from typing import Dict, List, Callable

from events.event_bus import EventBus
from events.events import CheckpointResolved, AssetUpdated
from repositories import CheckpointRepository, AgentRepository, AssetRepository
from config_loaders.checkpoint_config import get_checkpoint_category_map


class AutoApprovalHandler:
    def __init__(
        self,
        event_bus: EventBus,
        add_system_log: Callable,
    ):
        self._event_bus = event_bus
        self._add_system_log = add_system_log

    def approve_pending_checkpoints(
        self,
        session,
        project_id: str,
        rules: List[Dict],
    ) -> None:
        enabled_categories = {r["category"] for r in rules if r.get("enabled")}
        if not enabled_categories:
            return

        category_map = get_checkpoint_category_map()
        from models.tables import Checkpoint

        pending_cps = (
            session.query(Checkpoint)
            .filter(
                Checkpoint.project_id == project_id,
                Checkpoint.status == "pending",
            )
            .all()
        )

        cp_repo = CheckpointRepository(session)
        agent_repo = AgentRepository(session)
        now = datetime.now()

        for cp in pending_cps:
            cp_category = category_map.get(cp.type, "document")
            if cp_category not in enabled_categories:
                continue

            cp.status = "approved"
            cp.resolved_at = now
            cp.updated_at = now
            session.flush()

            self._add_system_log(
                session, project_id, "info", "System",
                f"自動承認(設定変更): {cp.title}",
            )

            agent = agent_repo.get(cp.agent_id)
            agent_status = ""
            if agent and agent.status == "waiting_approval":
                other_pending = cp_repo.get_pending_by_agent(cp.agent_id)
                if not other_pending:
                    agent.status = "running"
                    session.flush()
            if agent:
                agent_status = agent.status

            self._event_bus.publish(
                CheckpointResolved(
                    project_id=project_id,
                    checkpoint_id=cp.id,
                    checkpoint=cp_repo.to_dict(cp),
                    resolution="approved",
                    agent_id=cp.agent_id,
                    agent_status=agent_status,
                )
            )

    def approve_pending_assets(
        self,
        session,
        project_id: str,
        rules: List[Dict],
    ) -> None:
        enabled_categories = {r["category"] for r in rules if r.get("enabled")}
        if not enabled_categories:
            return

        from models.tables import Asset

        pending_assets = (
            session.query(Asset)
            .filter(
                Asset.project_id == project_id,
                Asset.approval_status == "pending",
            )
            .all()
        )

        asset_repo = AssetRepository(session)
        for asset in pending_assets:
            if asset.type not in enabled_categories:
                continue

            asset.approval_status = "approved"
            session.flush()

            self._add_system_log(
                session, project_id, "info", "System",
                f"アセット自動承認(設定変更): {asset.name}",
            )

            self._event_bus.publish(
                AssetUpdated(
                    project_id=project_id,
                    asset=asset_repo.to_dict(asset),
                    auto_approved=True,
                )
            )
