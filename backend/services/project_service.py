import random
from datetime import datetime,timedelta
from typing import Optional,Dict,List,Any

from sqlalchemy.orm.attributes import flag_modified

from models.database import session_scope,init_db
from repositories import (
    ProjectRepository,
    AgentRepository,
    CheckpointRepository,
    SystemLogRepository,
    AssetRepository,
    MetricsRepository,
)
from config_loaders.ai_provider_config import build_default_ai_services
from config_loaders.checkpoint_config import get_auto_approval_rules as get_config_auto_approval_rules
from config_loaders.agent_config import (
    get_ui_phases,
    get_agent_definitions,
    get_generation_type_for_agent,
    get_generation_metrics_categories,
    get_agent_generation_metrics,
    get_agent_assets,
)
from events.event_bus import EventBus
from events.events import MetricsUpdated
from services.base_service import BaseService


class ProjectService(BaseService):
    def __init__(self,event_bus:EventBus):
        super().__init__(event_bus)

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
        from config_loaders.checkpoint_config import get_auto_approval_rules as get_config_auto_approval_rules_fn

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
        agents_data=[
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
            repo=ProjectRepository(session)
            p=repo.get(project_id)
            if not p:
                return None
            if p.status in ("draft","paused"):
                p.status="running"
                p.updated_at=datetime.now()
                session.flush()
                self._add_system_log(
                    session,project_id,"info","System","プロジェクト開始"
                )
            return repo.to_dict(p)

    def pause_project(self,project_id:str)->Optional[Dict]:
        with session_scope() as session:
            repo=ProjectRepository(session)
            p=repo.get(project_id)
            if not p:
                return None
            if p.status=="running":
                p.status="paused"
                p.updated_at=datetime.now()
                session.flush()
                self._add_system_log(
                    session,project_id,"info","System","プロジェクト一時停止"
                )
            return repo.to_dict(p)

    def resume_project(self,project_id:str)->Optional[Dict]:
        with session_scope() as session:
            repo=ProjectRepository(session)
            p=repo.get(project_id)
            if not p:
                return None
            if p.status=="paused":
                p.status="running"
                p.updated_at=datetime.now()
                session.flush()
                self._add_system_log(
                    session,project_id,"info","System","プロジェクト再開"
                )
            return repo.to_dict(p)

    def initialize_project(self,project_id:str)->Optional[Dict]:
        with session_scope() as session:
            proj_repo=ProjectRepository(session)
            agent_repo=AgentRepository(session)
            cp_repo=CheckpointRepository(session)
            syslog_repo=SystemLogRepository(session)
            asset_repo=AssetRepository(session)
            metrics_repo=MetricsRepository(session)
            project=proj_repo.get(project_id)
            if not project:
                return None
            now=datetime.now()
            project.status="draft"
            project.current_phase=1
            project.updated_at=now
            agent_repo.delete_by_project(project_id)
            cp_repo.delete_by_project(project_id)
            syslog_repo.delete_by_project(project_id)
            asset_repo.delete_by_project(project_id)
            ui_phases=get_ui_phases()
            agent_defs=get_agent_definitions()
            for phase_idx,phase in enumerate(ui_phases):
                for agent_type in phase.get("agents",[]):
                    agent_def=agent_defs.get(agent_type,{})
                    display_name=(
                        agent_def.get("shortLabel")
                        or agent_def.get("label")
                        or agent_type
                    )
                    agent_repo.create_from_dict(
                        project_id,
                        {
                            "type":agent_type,
                            "phase":phase_idx,
                            "metadata":{"displayName":display_name},
                        },
                    )
            metrics_repo.delete(project_id)
            metrics_repo.create_or_update(
                project_id,
                {
                    "estimatedTotalTokens":50000,
                    "totalTasks":6,
                    "currentPhase":1,
                    "phaseName":"Phase 1: 企画・設計",
                },
            )
            self._add_system_log(
                session,project_id,"info","System","プロジェクト初期化完了"
            )
            self._logger.info(f"Project {project_id} initialized")
            return proj_repo.to_dict(project)

    def brushup_project(
        self,project_id:str,options:Optional[Dict]=None
    )->Optional[Dict]:
        with session_scope() as session:
            proj_repo=ProjectRepository(session)
            agent_repo=AgentRepository(session)
            project=proj_repo.get(project_id)
            if not project or project.status!="completed":
                return None
            opts=options or {}
            selected_agents:List[str]=opts.get("selectedAgents",[])
            agent_options:Dict[str,List[str]]=opts.get("agentOptions",{})
            agent_instructions:Dict[str,str]=opts.get("agentInstructions",{})
            presets:List[str]=opts.get("presets",[])
            custom_instruction:str=opts.get("customInstruction","")
            reference_image_ids:List[str]=opts.get("referenceImageIds",[])
            project.status="draft"
            project.current_phase=1
            project.updated_at=datetime.now()
            if (
                presets
                or custom_instruction
                or reference_image_ids
                or agent_options
                or agent_instructions
            ):
                brushup_config={
                    "presets":presets,
                    "agentOptions":agent_options,
                    "agentInstructions":agent_instructions,
                    "customInstruction":custom_instruction,
                    "referenceImageIds":reference_image_ids,
                }
                if project.config:
                    import json

                    config=(
                        json.loads(project.config)
                        if isinstance(project.config,str)
                        else project.config
                    )
                    config["brushupConfig"]=brushup_config
                    project.config=(
                        json.dumps(config)
                        if isinstance(project.config,str)
                        else config
                    )
            agents=agent_repo.get_by_project(project_id)
            for agent_dict in agents:
                should_reset=(
                    len(selected_agents)==0
                    or agent_dict["type"] in selected_agents
                )
                if should_reset:
                    agent=agent_repo.get(agent_dict["id"])
                    agent.status="pending"
                    agent.progress=0
                    agent.current_task=None
                    agent.started_at=None
                    agent.completed_at=None
                    agent.error=None
            session.flush()
            agent_names=(
                ",".join(selected_agents) if selected_agents else"全エージェント"
            )
            preset_names=",".join(presets) if presets else"なし"
            log_msg=f"ブラッシュアップ開始: エージェント={agent_names}, プリセット={preset_names}"
            if agent_options:
                log_msg+=f", オプション指定あり"
            if agent_instructions:
                log_msg+=f", 個別指示あり"
            if custom_instruction:
                log_msg+=f", 全体指示あり"
            self._add_system_log(session,project_id,"info","System",log_msg)
            self._logger.info(
                f"Project {project_id} brushup started: {agent_names}"
            )
            return proj_repo.to_dict(project)

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
            self._update_project_metrics(session,project_id)

    def _update_project_metrics(self,session,project_id:str)->None:
        agent_repo=AgentRepository(session)
        proj_repo=ProjectRepository(session)
        metrics_repo=MetricsRepository(session)
        agents=agent_repo.get_by_project(project_id)
        project=proj_repo.get(project_id)
        if not project:
            return
        total_input=sum(a.get("inputTokens",0) for a in agents)
        total_output=sum(a.get("outputTokens",0) for a in agents)
        completed_count=len([a for a in agents if a["status"]=="completed"])
        total_count=len(agents)
        total_progress=sum(a["progress"] for a in agents)
        overall_progress=(
            int(total_progress/total_count) if total_count>0 else 0
        )
        tokens_by_type={}
        for agent in agents:
            gen_type=get_generation_type_for_agent(agent["type"])
            if gen_type not in tokens_by_type:
                tokens_by_type[gen_type]={"input":0,"output":0}
            tokens_by_type[gen_type]["input"]+=agent.get("inputTokens",0)
            tokens_by_type[gen_type]["output"]+=agent.get("outputTokens",0)
        running_agent=next(
            (a for a in agents if a["status"]=="running"),None
        )
        estimated_remaining=0
        if running_agent and running_agent["progress"]>0:
            elapsed=(
                datetime.now()
                -datetime.fromisoformat(running_agent["startedAt"])
            ).total_seconds()
            rate=running_agent["progress"]/elapsed if elapsed>0 else 1
            remaining_progress=100-running_agent["progress"]
            remaining_agents=len(
                [a for a in agents if a["status"]=="pending"]
            )
            estimated_remaining=(
                (remaining_progress/rate)+(remaining_agents*100/rate)
                if rate>0
                else 0
            )
        active_generations=len(
            [a for a in agents if a["status"]=="running"]
        )
        existing_metrics=metrics_repo.get(project_id)
        generation_counts=(
            existing_metrics.get("generationCounts",{})
            if existing_metrics
            else {}
        )
        metrics_data={
            "projectId":project_id,
            "totalTokensUsed":total_input+total_output,
            "totalInputTokens":total_input,
            "totalOutputTokens":total_output,
            "estimatedTotalTokens":50000,
            "tokensByType":tokens_by_type,
            "generationCounts":generation_counts,
            "elapsedTimeSeconds":int(
                (datetime.now()-project.created_at).total_seconds()
            ),
            "estimatedRemainingSeconds":int(estimated_remaining),
            "estimatedEndTime":(
                datetime.now()+timedelta(seconds=estimated_remaining)
            ).isoformat()
            if estimated_remaining>0
            else None,
            "completedTasks":completed_count,
            "totalTasks":total_count,
            "progressPercent":overall_progress,
            "currentPhase":project.current_phase,
            "phaseName":f"Phase {project.current_phase}",
            "activeGenerations":active_generations,
        }
        metrics_repo.create_or_update(project_id,metrics_data)
        self._event_bus.publish(
            MetricsUpdated(project_id=project_id,metrics=metrics_data)
        )

    def accumulate_generation_counts(
        self,project_id:str,gen_counts:Dict[str,Any]
    )->None:
        with session_scope() as session:
            metrics_repo=MetricsRepository(session)
            existing=metrics_repo.get(project_id)
            generation_counts=(
                existing.get("generationCounts",{}) if existing else {}
            )
            categories=get_generation_metrics_categories()
            for category,values in gen_counts.items():
                if category not in generation_counts:
                    cat_config=categories.get(category,{})
                    generation_counts[category]={
                        "count":0,
                        "unit":cat_config.get("unit",""),
                        "calls":0,
                    }
                entry=generation_counts[category]
                if"calls" not in entry:
                    entry["calls"]=0
                entry["count"]=entry.get("count",0)+values.get("count",0)
                entry["calls"]+=values.get("calls",0)
            metrics_repo.create_or_update(
                project_id,{"generationCounts":generation_counts}
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
