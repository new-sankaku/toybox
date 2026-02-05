import json
from datetime import datetime
from typing import Dict,List,Optional,Callable

from repositories import (
    ProjectRepository,
    AgentRepository,
    CheckpointRepository,
    SystemLogRepository,
    AssetRepository,
    MetricsRepository,
)
from config_loaders.agent_config import get_ui_phases,get_agent_definitions


class ProjectStateManager:
    def __init__(self,add_system_log:Callable):
        self._add_system_log=add_system_log

    def start(self,session,project_id:str)->Optional[Dict]:
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

    def pause(self,session,project_id:str)->Optional[Dict]:
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

    def resume(self,session,project_id:str)->Optional[Dict]:
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

    def initialize(self,session,project_id:str,logger)->Optional[Dict]:
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
        logger.info(f"Project {project_id} initialized")
        return proj_repo.to_dict(project)

    def brushup(
        self,
        session,
        project_id:str,
        options:Optional[Dict],
        logger,
    )->Optional[Dict]:
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
            self._apply_brushup_config(
                project,
                presets,
                agent_options,
                agent_instructions,
                custom_instruction,
                reference_image_ids,
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
            log_msg+=", オプション指定あり"
        if agent_instructions:
            log_msg+=", 個別指示あり"
        if custom_instruction:
            log_msg+=", 全体指示あり"
        self._add_system_log(session,project_id,"info","System",log_msg)
        logger.info(
            f"Project {project_id} brushup started: {agent_names}"
        )
        return proj_repo.to_dict(project)

    def _apply_brushup_config(
        self,
        project,
        presets:List[str],
        agent_options:Dict[str,List[str]],
        agent_instructions:Dict[str,str],
        custom_instruction:str,
        reference_image_ids:List[str],
    )->None:
        brushup_config={
            "presets":presets,
            "agentOptions":agent_options,
            "agentInstructions":agent_instructions,
            "customInstruction":custom_instruction,
            "referenceImageIds":reference_image_ids,
        }
        if not project.config:
            return
        is_str=isinstance(project.config,str)
        config=json.loads(project.config) if is_str else project.config
        config["brushupConfig"]=brushup_config
        project.config=json.dumps(config) if is_str else config
