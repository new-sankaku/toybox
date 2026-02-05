from datetime import datetime
from typing import Optional,Dict,List

from sqlalchemy.orm.attributes import flag_modified

from models.database import session_scope
from repositories import ProjectRepository,CheckpointRepository
from agent_settings import QualityCheckConfig
from config_loaders.checkpoint_config import (
    get_auto_approval_rules as get_config_auto_approval_rules,
)
from events.event_bus import EventBus
from services.base_service import BaseService
from services.workflow.checkpoint_resolver import CheckpointResolver
from services.workflow.phase_manager import PhaseManager
from services.workflow.asset_manager import AssetManager
from services.workflow.quality_settings_manager import QualitySettingsManager
from services.workflow.auto_approval_handler import AutoApprovalHandler


class WorkflowService(BaseService):
    def __init__(self,event_bus:EventBus):
        super().__init__(event_bus)
        self._checkpoint_resolver=CheckpointResolver(event_bus,self._add_system_log)
        self._phase_manager=PhaseManager(event_bus,self._add_system_log)
        self._asset_manager=AssetManager(event_bus,self._add_system_log)
        self._quality_settings_manager=QualitySettingsManager()
        self._auto_approval_handler=AutoApprovalHandler(event_bus,self._add_system_log)

    def get_checkpoints_by_project(self,project_id:str)->List[Dict]:
        with session_scope() as session:
            repo=CheckpointRepository(session)
            return repo.get_by_project(project_id)

    def get_checkpoint(self,checkpoint_id:str)->Optional[Dict]:
        with session_scope() as session:
            repo=CheckpointRepository(session)
            return repo.get_dict(checkpoint_id)

    def create_checkpoint(
        self,
        project_id:str,
        agent_id:str,
        data:Dict,
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
            result=self._checkpoint_resolver.resolve(
                session,
                checkpoint_id,
                resolution,
                feedback,
            )
            if resolution=="approved" and result:
                cp_repo=CheckpointRepository(session)
                cp=cp_repo.get(checkpoint_id)
                if cp:
                    self._phase_manager.check_phase_advancement(session,cp.project_id)
            return result

    def get_assets_by_project(self,project_id:str)->List[Dict]:
        with session_scope() as session:
            return self._asset_manager.get_by_project(session,project_id)

    def update_asset(
        self,
        project_id:str,
        asset_id:str,
        data:Dict,
    )->Optional[Dict]:
        with session_scope() as session:
            return self._asset_manager.update(session,project_id,asset_id,data)

    def request_asset_regeneration(
        self,
        project_id:str,
        asset_id:str,
        feedback:str,
    )->None:
        with session_scope() as session:
            self._asset_manager.request_regeneration(
                session,project_id,asset_id,feedback
            )

    def get_quality_settings(self,project_id:str)->Dict[str,QualityCheckConfig]:
        with session_scope() as session:
            return self._quality_settings_manager.get_all(session,project_id)

    def set_quality_setting(
        self,
        project_id:str,
        agent_type:str,
        config:QualityCheckConfig,
    )->None:
        with session_scope() as session:
            self._quality_settings_manager.set(session,project_id,agent_type,config)

    def reset_quality_settings(self,project_id:str)->None:
        with session_scope() as session:
            self._quality_settings_manager.reset(session,project_id)

    def get_quality_setting_for_agent(
        self,
        project_id:str,
        agent_type:str,
    )->QualityCheckConfig:
        with session_scope() as session:
            return self._quality_settings_manager.get_for_agent(
                session,project_id,agent_type
            )

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
        self,
        project_id:str,
        rules:List[Dict],
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

            self._auto_approval_handler.approve_pending_checkpoints(session,project_id,rules)
            self._auto_approval_handler.approve_pending_assets(session,project_id,rules)

            return rules

    @property
    def checkpoints(self)->Dict[str,Dict]:
        result={}
        with session_scope() as session:
            repo=CheckpointRepository(session)
            for cp in session.query(repo.model).all():
                result[cp.id]=repo.to_dict(cp)
        return result
