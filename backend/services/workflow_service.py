from datetime import datetime
from typing import Optional,Dict,List

from sqlalchemy.orm.attributes import flag_modified

from models.database import session_scope
from repositories import (
    ProjectRepository,
    AgentRepository,
    CheckpointRepository,
    AssetRepository,
    QualitySettingsRepository,
)
from agent_settings import QualityCheckConfig
from config_loader import (
    get_checkpoint_category_map,
    get_auto_approval_rules as get_config_auto_approval_rules,
)
from events.event_bus import EventBus
from events.events import (
    AgentCompleted,
    AgentFailed,
    AgentProgress,
    CheckpointResolved,
    AssetUpdated,
    PhaseChanged,
)
from services.base_service import BaseService


class WorkflowService(BaseService):
    def __init__(self,event_bus:EventBus):
        super().__init__(event_bus)

    def get_checkpoints_by_project(self,project_id:str)->List[Dict]:
        with session_scope() as session:
            repo=CheckpointRepository(session)
            return repo.get_by_project(project_id)

    def get_checkpoint(self,checkpoint_id:str)->Optional[Dict]:
        with session_scope() as session:
            repo=CheckpointRepository(session)
            return repo.get_dict(checkpoint_id)

    def create_checkpoint(
        self,project_id:str,agent_id:str,data:Dict
    )->Dict:
        with session_scope() as session:
            repo=CheckpointRepository(session)
            return repo.create_from_dict(
                {**data,"projectId":project_id,"agentId":agent_id}
            )

    def resolve_checkpoint(
        self,
        checkpoint_id:str,
        resolution:str,
        feedback:Optional[str]=None,
    )->Optional[Dict]:
        with session_scope() as session:
            cp_repo=CheckpointRepository(session)
            agent_repo=AgentRepository(session)
            cp=cp_repo.get(checkpoint_id)
            if not cp:
                return None
            result=cp_repo.resolve(checkpoint_id,resolution,feedback)
            project_id=cp.project_id
            status_text={
                "approved":"承認",
                "rejected":"却下",
                "revision_requested":"修正要求",
            }
            self._add_system_log(
                session,
                project_id,
                "info",
                "System",
                f"チェックポイント{status_text.get(resolution, resolution)}: {cp.title}",
            )
            agent=agent_repo.get(cp.agent_id)
            if agent:
                if resolution=="rejected":
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
                elif resolution=="revision_requested":
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
                else:
                    other_pending=cp_repo.get_pending_by_agent(cp.agent_id)
                    other_pending=[
                        c for c in other_pending if c.id!=checkpoint_id
                    ]
                    if (
                        not other_pending
                        and agent.status=="waiting_approval"
                    ):
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
            agent_status=agent.status if agent else""
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
            if resolution=="approved":
                self._check_phase_advancement(session,project_id)
            return result

    def _check_phase_advancement(self,session,project_id:str)->None:
        proj_repo=ProjectRepository(session)
        cp_repo=CheckpointRepository(session)
        project=proj_repo.get(project_id)
        if not project:
            return
        current_phase=project.current_phase
        project_checkpoints=cp_repo.get_by_project(project_id)
        phase1_types={
            "concept_review",
            "task_review_1",
            "concept_detail_review",
            "scenario_review",
            "world_review",
            "game_design_review",
            "tech_spec_review",
        }
        if current_phase==1:
            phase1_checkpoints=[
                c
                for c in project_checkpoints
                if c["type"] in phase1_types
            ]
            if phase1_checkpoints and all(
                c["status"]=="approved" for c in phase1_checkpoints
            ):
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
                self._logger.info(
                    f"Project {project_id} advanced to Phase 2"
                )

    def get_assets_by_project(self,project_id:str)->List[Dict]:
        with session_scope() as session:
            repo=AssetRepository(session)
            return repo.get_by_project(project_id)

    def update_asset(
        self,project_id:str,asset_id:str,data:Dict
    )->Optional[Dict]:
        with session_scope() as session:
            repo=AssetRepository(session)
            asset=repo.get(asset_id)
            if not asset or asset.project_id!=project_id:
                return None
            old_status=asset.approval_status
            result=repo.update_from_dict(project_id,asset_id,data)
            new_status=data.get("approvalStatus")
            if (
                new_status
                and old_status=="pending"
                and new_status=="approved"
            ):
                self._handle_asset_approval(session,asset,project_id)
            return result

    def _handle_asset_approval(
        self,session,asset,project_id:str
    )->None:
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
        if (
            not pending_assets
            and not pending_cps
            and agent.status=="waiting_approval"
        ):
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

    def request_asset_regeneration(
        self,project_id:str,asset_id:str,feedback:str
    )->None:
        with session_scope() as session:
            asset_repo=AssetRepository(session)
            asset=asset_repo.get(asset_id)
            if not asset or asset.project_id!=project_id:
                return
            self._add_system_log(
                session,
                project_id,
                "info",
                "System",
                f"アセット「{asset.name}」の再生成がリクエストされました: {feedback[:100]}",
            )

    def get_quality_settings(
        self,project_id:str
    )->Dict[str,QualityCheckConfig]:
        with session_scope() as session:
            repo=QualitySettingsRepository(session)
            return repo.get_all(project_id)

    def set_quality_setting(
        self,project_id:str,agent_type:str,config:QualityCheckConfig
    )->None:
        with session_scope() as session:
            repo=QualitySettingsRepository(session)
            repo.set(project_id,agent_type,config)

    def reset_quality_settings(self,project_id:str)->None:
        with session_scope() as session:
            repo=QualitySettingsRepository(session)
            repo.reset(project_id)

    def get_quality_setting_for_agent(
        self,project_id:str,agent_type:str
    )->QualityCheckConfig:
        settings=self.get_quality_settings(project_id)
        return settings.get(agent_type,QualityCheckConfig())

    def get_auto_approval_rules(self,project_id:str)->List[Dict]:
        with session_scope() as session:
            repo=ProjectRepository(session)
            project=repo.get(project_id)
            if not project:
                return []
            return (project.config or {}).get(
                "autoApprovalRules",get_config_auto_approval_rules()
            )

    def set_auto_approval_rules(
        self,project_id:str,rules:List[Dict]
    )->List[Dict]:
        with session_scope() as session:
            repo=ProjectRepository(session)
            project=repo.get(project_id)
            if not project:
                return []
            config=dict(project.config or {})
            config["autoApprovalRules"]=rules
            project.config=config
            flag_modified(project,"config")
            project.updated_at=datetime.now()
            session.flush()
            self._auto_approve_pending_checkpoints(
                session,project_id,rules
            )
            self._auto_approve_pending_assets(session,project_id,rules)
            return rules

    def _auto_approve_pending_checkpoints(
        self,session,project_id:str,rules:List[Dict]
    )->None:
        enabled_categories={
            r["category"] for r in rules if r.get("enabled")
        }
        if not enabled_categories:
            return
        category_map=get_checkpoint_category_map()
        from models.tables import Checkpoint

        pending_cps=(
            session.query(Checkpoint)
            .filter(
                Checkpoint.project_id==project_id,
                Checkpoint.status=="pending",
            )
            .all()
        )
        cp_repo=CheckpointRepository(session)
        agent_repo=AgentRepository(session)
        now=datetime.now()
        for cp in pending_cps:
            cp_category=category_map.get(cp.type,"document")
            if cp_category in enabled_categories:
                cp.status="approved"
                cp.resolved_at=now
                cp.updated_at=now
                session.flush()
                self._add_system_log(
                    session,
                    project_id,
                    "info",
                    "System",
                    f"自動承認(設定変更): {cp.title}",
                )
                agent=agent_repo.get(cp.agent_id)
                agent_status=""
                if agent and agent.status=="waiting_approval":
                    other_pending=cp_repo.get_pending_by_agent(cp.agent_id)
                    if not other_pending:
                        agent.status="running"
                        session.flush()
                if agent:
                    agent_status=agent.status
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

    def _auto_approve_pending_assets(
        self,session,project_id:str,rules:List[Dict]
    )->None:
        enabled_categories={
            r["category"] for r in rules if r.get("enabled")
        }
        if not enabled_categories:
            return
        from models.tables import Asset

        pending_assets=(
            session.query(Asset)
            .filter(
                Asset.project_id==project_id,
                Asset.approval_status=="pending",
            )
            .all()
        )
        asset_repo=AssetRepository(session)
        for asset in pending_assets:
            if asset.type in enabled_categories:
                asset.approval_status="approved"
                session.flush()
                self._add_system_log(
                    session,
                    project_id,
                    "info",
                    "System",
                    f"アセット自動承認(設定変更): {asset.name}",
                )
                self._event_bus.publish(
                    AssetUpdated(
                        project_id=project_id,
                        asset=asset_repo.to_dict(asset),
                        auto_approved=True,
                    )
                )

    @property
    def checkpoints(self)->Dict[str,Dict]:
        result={}
        with session_scope() as session:
            repo=CheckpointRepository(session)
            for cp in session.query(repo.model).all():
                result[cp.id]=repo.to_dict(cp)
        return result
