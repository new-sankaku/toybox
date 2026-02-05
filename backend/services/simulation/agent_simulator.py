"""
Agent Simulator Module

エージェント進捗シミュレーションを担当
"""

import random
from datetime import datetime
from typing import Dict

from repositories import (
    AgentRepository,
    AgentLogRepository,
    SystemLogRepository,
)
from config_loaders.message_config import (
    get_initial_task,
    get_task_for_progress,
    get_milestones,
)
from events.event_bus import EventBus
from events.events import (
    AgentStarted,
    AgentProgress,
    AgentCompleted,
    AgentResumed,
    SystemLogCreated,
)

from .checkpoint_generator import CheckpointGenerator
from .asset_generator import AssetGenerator
from .trace_generator import TraceGenerator
from .metrics_updater import MetricsUpdater


class AgentSimulator:
    def __init__(
        self,
        event_bus:EventBus,
        checkpoint_generator:CheckpointGenerator,
        asset_generator:AssetGenerator,
        trace_generator:TraceGenerator,
        metrics_updater:MetricsUpdater,
    ):
        self._event_bus=event_bus
        self._checkpoint_generator=checkpoint_generator
        self._asset_generator=asset_generator
        self._trace_generator=trace_generator
        self._metrics_updater=metrics_updater

    def start_agent(self,session,agent_dict:Dict)->None:
        agent_repo=AgentRepository(session)
        agent=agent_repo.get(agent_dict["id"])
        now=datetime.now()
        agent.status="running"
        agent.progress=0
        agent.started_at=now
        agent.current_task=get_initial_task(agent.type)
        session.flush()
        display_name=(
            agent.metadata_.get("displayName",agent.type)
            if agent.metadata_
            else agent.type
        )
        self._add_agent_log(session,agent.id,"info",f"{display_name}エージェント起動",0)
        self._add_system_log(
            session,
            agent.project_id,
            "info",
            agent.type,
            f"{display_name}開始",
        )
        self._event_bus.publish(
            AgentStarted(
                project_id=agent.project_id,
                agent_id=agent.id,
                agent=agent_repo.to_dict(agent),
            )
        )

    def simulate_agent(self,session,agent_dict:Dict)->None:
        if agent_dict["status"]=="waiting_approval":
            return
        agent_repo=AgentRepository(session)
        agent=agent_repo.get(agent_dict["id"])
        increment=random.randint(2,5)
        new_progress=min(100,agent.progress+increment)
        token_increment=random.randint(30,80)
        input_increment=int(token_increment*0.3)
        output_increment=token_increment-input_increment
        agent.tokens_used+=token_increment
        agent.input_tokens+=input_increment
        agent.output_tokens+=output_increment
        old_progress=agent.progress
        agent.progress=new_progress
        agent.current_task=get_task_for_progress(agent.type,new_progress)
        session.flush()
        self._check_milestone_logs(session,agent,old_progress,new_progress)
        self._checkpoint_generator.check_checkpoint_creation(
            session,agent,old_progress,new_progress
        )
        self._asset_generator.check_asset_generation(
            session,agent,old_progress,new_progress
        )
        self._trace_generator.check_trace_generation(
            session,agent,old_progress,new_progress
        )
        agent=agent_repo.get(agent_dict["id"])
        if agent.status=="waiting_approval":
            self._event_bus.publish(
                AgentProgress(
                    project_id=agent.project_id,
                    agent_id=agent.id,
                    progress=new_progress,
                    current_task="承認待ち",
                    tokens_used=agent.tokens_used,
                    message=f"承認待ち (進捗: {new_progress}%)",
                )
            )
            return
        self._event_bus.publish(
            AgentProgress(
                project_id=agent.project_id,
                agent_id=agent.id,
                progress=new_progress,
                current_task=agent.current_task,
                tokens_used=agent.tokens_used,
                message=f"進捗: {new_progress}%",
            )
        )
        if new_progress>=100:
            self._complete_agent(session,agent)

    def _complete_agent(self,session,agent)->None:
        now=datetime.now()
        agent.status="completed"
        agent.progress=100
        agent.completed_at=now
        agent.current_task=None
        session.flush()
        display_name=(
            agent.metadata_.get("displayName",agent.type)
            if agent.metadata_
            else agent.type
        )
        self._add_agent_log(session,agent.id,"info",f"{display_name}完了",100)
        self._add_system_log(
            session,
            agent.project_id,
            "info",
            agent.type,
            f"{display_name}完了",
        )
        agent_repo=AgentRepository(session)
        self._metrics_updater.finalize_generation_count(session,agent,agent.project_id)
        self._event_bus.publish(
            AgentCompleted(
                project_id=agent.project_id,
                agent_id=agent.id,
                agent=agent_repo.to_dict(agent),
            )
        )
        self._resume_paused_subsequent_agents(session,agent)

    def _resume_paused_subsequent_agents(self,session,completed_agent)->None:

        agent_repo=AgentRepository(session)
        syslog_repo=SystemLogRepository(session)
        agents=agent_repo.get_by_project(completed_agent.project_id)
        completed_phase=completed_agent.phase or 0
        for agent_dict in agents:
            if agent_dict["status"]!="paused":
                continue
            agent_phase=agent_dict.get("phase",0)
            if agent_phase<=completed_phase:
                continue
            if not self._can_start_agent(
                session,agent_dict["type"],completed_agent.project_id
            ):
                continue
            agent=agent_repo.get(agent_dict["id"])
            agent.status="running"
            agent.updated_at=datetime.now()
            session.flush()
            display_name=(
                agent.metadata_.get("displayName",agent.type)
                if agent.metadata_
                else agent.type
            )
            syslog_repo.add_log(
                agent.project_id,
                "info",
                "System",
                f"エージェント {display_name} を自動再開",
            )
            self._event_bus.publish(
                AgentResumed(
                    project_id=agent.project_id,
                    agent_id=agent.id,
                    agent=agent_repo.to_dict(agent),
                    reason="previous_agent_completed",
                )
            )

    def _can_start_agent(self,session,agent_type:str,project_id:str)->bool:
        from repositories import CheckpointRepository,AssetRepository
        from config_loaders.workflow_config import get_workflow_dependencies

        workflow_deps=get_workflow_dependencies()
        dependencies=workflow_deps.get(agent_type,[])
        agent_repo=AgentRepository(session)
        agents=agent_repo.get_by_project(project_id)
        for dep_type in dependencies:
            dep_agent=next((a for a in agents if a["type"]==dep_type),None)
            if not dep_agent or dep_agent["status"]!="completed":
                return False
            cp_repo=CheckpointRepository(session)
            pending_cps=[
                c for c in cp_repo.get_by_agent(dep_agent["id"]) if c["status"]=="pending"
            ]
            if pending_cps:
                return False
            asset_repo=AssetRepository(session)
            pending_assets=asset_repo.get_pending_by_agent(dep_agent["id"])
            if pending_assets:
                return False
        return True

    def _check_milestone_logs(
        self,session,agent,old_progress:int,new_progress:int
    )->None:
        milestones=get_milestones(agent.type)
        for milestone_progress,level,message in milestones:
            if old_progress<milestone_progress<=new_progress:
                self._add_agent_log(session,agent.id,level,message,milestone_progress)
                if level in ("warn","error"):
                    self._add_system_log(
                        session,
                        agent.project_id,
                        level,
                        agent.type,
                        message,
                    )

    def _add_agent_log(
        self,
        session,
        agent_id:str,
        level:str,
        message:str,
        progress:int=None,
    )->None:
        repo=AgentLogRepository(session)
        repo.add_log(agent_id,level,message,progress)

    def _add_system_log(
        self,
        session,
        project_id:str,
        level:str,
        source:str,
        message:str,
    )->None:
        repo=SystemLogRepository(session)
        log_dict=repo.add_log(project_id,level,source,message)
        self._event_bus.publish(SystemLogCreated(project_id=project_id,log=log_dict))
