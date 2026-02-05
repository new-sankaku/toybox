"""
Checkpoint Generator Module

シミュレーション用チェックポイント生成を担当
"""

import uuid
from datetime import datetime
from typing import Callable,List

from repositories import CheckpointRepository,ProjectRepository
from config_loaders.agent_config import get_agent_checkpoints
from config_loaders.mock_config import get_checkpoint_content
from config_loaders.checkpoint_config import get_checkpoint_category_map
from events.event_bus import EventBus
from events.events import CheckpointCreated


class CheckpointGenerator:
    def __init__(
        self,
        event_bus:EventBus,
        add_system_log_func:Callable,
    ):
        self._event_bus=event_bus
        self._add_system_log=add_system_log_func

    def check_checkpoint_creation(
        self,
        session,
        agent,
        old_progress:int,
        new_progress:int,
    )->None:
        checkpoint_points=self._get_checkpoint_points(agent.type)
        for cp_progress,cp_type,cp_title in checkpoint_points:
            if old_progress<cp_progress<=new_progress:
                cp_repo=CheckpointRepository(session)
                existing=[
                    c for c in cp_repo.get_by_agent(agent.id) if c["type"]==cp_type
                ]
                if not existing:
                    self._create_agent_checkpoint(session,agent,cp_type,cp_title)

    def _should_auto_approve(
        self,session,project_id:str,cp_type:str
    )->bool:
        proj_repo=ProjectRepository(session)
        project=proj_repo.get(project_id)
        if not project:
            return False
        rules=(project.config or {}).get("autoApprovalRules",[])
        if not rules:
            return False
        category=get_checkpoint_category_map().get(cp_type,"document")
        for rule in rules:
            if rule.get("category")==category:
                return rule.get("enabled",False)
        return False

    def _create_agent_checkpoint(
        self,session,agent,cp_type:str,title:str
    )->None:
        cp_id=f"cp-{uuid.uuid4().hex[:8]}"
        now=datetime.now()
        content=self._generate_checkpoint_content(agent.type,cp_type)
        auto_approve=self._should_auto_approve(session,agent.project_id,cp_type)
        category=get_checkpoint_category_map().get(cp_type,"document")
        from models.tables import Checkpoint

        display_name=(
            agent.metadata_.get("displayName",agent.type)
            if agent.metadata_
            else agent.type
        )
        checkpoint=Checkpoint(
            id=cp_id,
            project_id=agent.project_id,
            agent_id=agent.id,
            type=cp_type,
            title=title,
            description=f"{display_name}の成果物を確認してください",
            content_category=category,
            output={
                "type":"document",
                "format":"markdown",
                "content":content,
            },
            status="approved" if auto_approve else"pending",
            resolved_at=now if auto_approve else None,
            created_at=now,
            updated_at=now,
        )
        session.add(checkpoint)
        session.flush()
        if auto_approve:
            self._add_system_log(
                session,
                agent.project_id,
                "info",
                "System",
                f"自動承認: {title}",
            )
        else:
            agent.status="waiting_approval"
            session.flush()
            self._add_system_log(
                session,
                agent.project_id,
                "info",
                "System",
                f"承認作成: {title}",
            )
        cp_repo=CheckpointRepository(session)
        self._event_bus.publish(
            CheckpointCreated(
                project_id=agent.project_id,
                checkpoint_id=cp_id,
                agent_id=agent.id,
                checkpoint=cp_repo.to_dict(checkpoint),
                auto_approved=auto_approve,
            )
        )

    def _get_checkpoint_points(self,agent_type:str)->List[tuple]:
        checkpoints=get_agent_checkpoints(agent_type)
        return [
            (
                c.get("progress",90),
                c.get("type","review"),
                c.get("title","レビュー"),
            )
            for c in checkpoints
        ]

    def _generate_checkpoint_content(self,agent_type:str,cp_type:str)->str:
        return get_checkpoint_content(cp_type)
