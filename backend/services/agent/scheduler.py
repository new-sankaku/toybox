from datetime import datetime
from typing import Dict,List

from models.database import session_scope
from repositories import (
    ProjectRepository,
    AgentRepository,
    CheckpointRepository,
    AssetRepository,
)
from config_loaders.workflow_config import get_workflow_dependencies
from config_loaders.message_config import get_initial_task
from events.event_bus import EventBus
from events.events import AgentStarted
from services.base_service import BaseService


class AgentScheduler(BaseService):
    def __init__(self,event_bus:EventBus):
        super().__init__(event_bus)

    def start_next_agents(self,project_id:str)->List[Dict]:
        with session_scope() as session:
            proj_repo=ProjectRepository(session)
            project=proj_repo.get(project_id)
            if not project or project.status!="running":
                return []
            ready_agents=self._get_next_agents_to_start(session,project_id)
            started=[]
            for agent_dict in ready_agents:
                self._start_agent(session,agent_dict)
                started.append(agent_dict)
            return started

    def _can_start_agent(
        self,session,agent_type:str,project_id:str
    )->bool:
        workflow_deps=get_workflow_dependencies()
        dependencies=workflow_deps.get(agent_type,[])
        agent_repo=AgentRepository(session)
        agents=agent_repo.get_by_project(project_id)
        for dep_type in dependencies:
            dep_agent=next(
                (a for a in agents if a["type"]==dep_type),None
            )
            if not dep_agent or dep_agent["status"]!="completed":
                return False
            cp_repo=CheckpointRepository(session)
            pending_cps=[
                c
                for c in cp_repo.get_by_agent(dep_agent["id"])
                if c["status"]=="pending"
            ]
            if pending_cps:
                return False
            asset_repo=AssetRepository(session)
            pending_assets=asset_repo.get_pending_by_agent(dep_agent["id"])
            if pending_assets:
                return False
        return True

    def _get_next_agents_to_start(
        self,session,project_id:str
    )->List[Dict]:
        agent_repo=AgentRepository(session)
        agents=agent_repo.get_by_project(project_id)
        pending=[a for a in agents if a["status"]=="pending"]
        return [
            a
            for a in pending
            if self._can_start_agent(session,a["type"],project_id)
        ]

    def _start_agent(self,session,agent_dict:Dict)->None:
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
        self._add_agent_log(
            session,agent.id,"info",f"{display_name}エージェント起動",0
        )
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
