from datetime import datetime
from typing import Optional,Dict,List,Any

from sqlalchemy.orm.attributes import flag_modified

from models.database import session_scope
from repositories import (
    ProjectRepository,
    MetricsRepository,
    SystemLogRepository,
)
from config_loaders.ai_provider_config import build_default_ai_services
from events.event_bus import EventBus
from services.base_service import BaseService
from services.project.metrics_calculator import MetricsCalculator
from services.project.state_manager import ProjectStateManager


class ProjectService(BaseService):
    def __init__(self,event_bus:EventBus):
        super().__init__(event_bus)
        self._metrics_calculator=MetricsCalculator(event_bus)
        self._state_manager=ProjectStateManager(self._add_system_log)

    def init_sample_data_if_empty(self)->None:
        with session_scope() as session:
            repo=ProjectRepository(session)
            if repo.get_all():
                return
            self._create_sample_project(session)

    def _create_sample_project(self,session)->None:
        now=datetime.now()
        proj_id="proj-001"
        from models.tables import Project,Agent,Metric
        from config_loaders.checkpoint_config import (
            get_auto_approval_rules as get_config_auto_approval_rules_fn,
        )

        project=Project(
            id=proj_id,
            name="パズルアクションゲーム",
            description="物理演算を使ったパズルゲーム。ボールを転がして障害物を避けながらゴールを目指す。",
            concept={
                "description":"ボールを転がしてゴールを目指すパズル。重力や摩擦をリアルに再現。",
                "platform":"web",
                "scope":"demo",
                "genre":"Puzzle",
                "targetAudience":"全年齢",
            },
            status="draft",
            current_phase=1,
            state={},
            config={
                "maxTokensPerAgent":100000,
                "autoApprovalRules":get_config_auto_approval_rules_fn(),
            },
            ai_services=dict(build_default_ai_services()),
            created_at=now,
            updated_at=now,
        )
        session.add(project)
        agents_data=self._get_sample_agents_data()
        for data in agents_data:
            agent=Agent(
                id=f"agent-{proj_id}-{data['type']}",
                project_id=proj_id,
                type=data["type"],
                phase=data["phase"],
                status="pending",
                progress=0,
                tokens_used=0,
                input_tokens=0,
                output_tokens=0,
                metadata_={"displayName":data["name"]},
                created_at=now,
            )
            session.add(agent)
        metric=Metric(
            project_id=proj_id,
            total_tokens_used=0,
            total_input_tokens=0,
            total_output_tokens=0,
            estimated_total_tokens=50000,
            tokens_by_type={},
            generation_counts={},
            elapsed_time_seconds=0,
            estimated_remaining_seconds=0,
            completed_tasks=0,
            total_tasks=6,
            progress_percent=0,
            current_phase=1,
            phase_name="Phase 1: 企画・設計",
            active_generations=0,
        )
        session.add(metric)
        session.flush()
        self._logger.info(f"Sample project {proj_id} created")

    def _get_sample_agents_data(self)->List[Dict]:
        return [
            {"type":"concept","name":"コンセプト","phase":0},
            {"type":"task_split_1","name":"タスク分割1","phase":1},
            {"type":"concept_detail","name":"コンセプト詳細","phase":2},
            {"type":"scenario","name":"シナリオ","phase":2},
            {"type":"world","name":"世界観","phase":2},
            {"type":"game_design","name":"ゲームデザイン","phase":2},
            {"type":"tech_spec","name":"技術仕様","phase":2},
            {"type":"task_split_2","name":"タスク分割2","phase":3},
            {"type":"data_design","name":"データ設計","phase":3},
            {"type":"asset_character","name":"キャラ","phase":4},
            {"type":"asset_background","name":"背景","phase":4},
            {"type":"asset_ui","name":"UI","phase":4},
            {"type":"asset_effect","name":"エフェクト","phase":4},
            {"type":"asset_bgm","name":"BGM","phase":4},
            {"type":"asset_voice","name":"ボイス","phase":4},
            {"type":"asset_sfx","name":"効果音","phase":4},
            {"type":"task_split_3","name":"タスク分割3","phase":5},
            {"type":"code","name":"コード","phase":6},
            {"type":"event","name":"イベント","phase":6},
            {"type":"ui_integration","name":"UI統合","phase":6},
            {"type":"asset_integration","name":"アセット統合","phase":6},
            {"type":"task_split_4","name":"タスク分割4","phase":7},
            {"type":"unit_test","name":"単体テスト","phase":8},
            {"type":"integration_test","name":"統合テスト","phase":8},
        ]

    def get_projects(self)->List[Dict]:
        with session_scope() as session:
            repo=ProjectRepository(session)
            return repo.get_all_dict()

    def get_project(self,project_id:str)->Optional[Dict]:
        with session_scope() as session:
            repo=ProjectRepository(session)
            return repo.get_dict(project_id)

    def create_project(self,data:Dict)->Dict:
        with session_scope() as session:
            repo=ProjectRepository(session)
            if"aiServices" not in data or not data["aiServices"]:
                data["aiServices"]=dict(build_default_ai_services())
            project=repo.create_from_dict(data)
            syslog_repo=SystemLogRepository(session)
            syslog_repo.add_log(project["id"],"info","System","プロジェクト作成")
            return project

    def update_project(self,project_id:str,data:Dict)->Optional[Dict]:
        with session_scope() as session:
            repo=ProjectRepository(session)
            return repo.update_from_dict(project_id,data)

    def delete_project(self,project_id:str)->bool:
        with session_scope() as session:
            repo=ProjectRepository(session)
            return repo.delete(project_id)

    def start_project(self,project_id:str)->Optional[Dict]:
        with session_scope() as session:
            return self._state_manager.start(session,project_id)

    def pause_project(self,project_id:str)->Optional[Dict]:
        with session_scope() as session:
            return self._state_manager.pause(session,project_id)

    def resume_project(self,project_id:str)->Optional[Dict]:
        with session_scope() as session:
            return self._state_manager.resume(session,project_id)

    def initialize_project(self,project_id:str)->Optional[Dict]:
        with session_scope() as session:
            return self._state_manager.initialize(
                session,project_id,self._logger
            )

    def brushup_project(
        self,project_id:str,options:Optional[Dict]=None
    )->Optional[Dict]:
        with session_scope() as session:
            return self._state_manager.brushup(
                session,project_id,options,self._logger
            )

    def get_project_metrics(self,project_id:str)->Optional[Dict]:
        with session_scope() as session:
            repo=MetricsRepository(session)
            return repo.get(project_id)

    def update_project_metrics(self,project_id:str,data:Dict)->Dict:
        with session_scope() as session:
            repo=MetricsRepository(session)
            return repo.create_or_update(project_id,data)

    def refresh_project_metrics(self,project_id:str)->None:
        with session_scope() as session:
            self._metrics_calculator.update_metrics(session,project_id)

    def _update_project_metrics(self,session,project_id:str)->None:
        self._metrics_calculator.update_metrics(session,project_id)

    def accumulate_generation_counts(
        self,project_id:str,gen_counts:Dict[str,Any]
    )->None:
        with session_scope() as session:
            self._metrics_calculator.accumulate_generation_counts(
                session,project_id,gen_counts
            )

    def get_ai_services(self,project_id:str)->Dict[str,Dict]:
        with session_scope() as session:
            repo=ProjectRepository(session)
            project=repo.get(project_id)
            if not project:
                return {}
            return project.ai_services or dict(build_default_ai_services())

    def update_ai_service(
        self,project_id:str,service_type:str,config:Dict
    )->Optional[Dict]:
        with session_scope() as session:
            repo=ProjectRepository(session)
            project=repo.get(project_id)
            if not project:
                return None
            ai_services=dict(
                project.ai_services or build_default_ai_services()
            )
            if service_type not in ai_services:
                return None
            ai_services[service_type]=dict(ai_services[service_type])
            ai_services[service_type].update(config)
            project.ai_services=ai_services
            flag_modified(project,"ai_services")
            project.updated_at=datetime.now()
            session.flush()
            return ai_services[service_type]

    def update_ai_services(
        self,project_id:str,ai_services:Dict[str,Dict]
    )->Optional[Dict]:
        with session_scope() as session:
            repo=ProjectRepository(session)
            project=repo.get(project_id)
            if not project:
                return None
            project.ai_services=ai_services
            flag_modified(project,"ai_services")
            project.updated_at=datetime.now()
            session.flush()
            return project.ai_services

    def get_system_logs(self,project_id:str)->List[Dict]:
        with session_scope() as session:
            repo=SystemLogRepository(session)
            return repo.get_by_project(project_id)
