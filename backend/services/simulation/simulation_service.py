"""
Simulation Service Module

シミュレーションサービスのコア制御
各サブモジュールを組み合わせてメインフローを提供
"""

import threading
import time
from datetime import datetime
from typing import Dict,List,Optional

from models.database import session_scope
from repositories import (
    ProjectRepository,
    AgentRepository,
    CheckpointRepository,
    AssetRepository,
    SystemLogRepository,
)
from config_loaders.workflow_config import get_workflow_dependencies
from events.event_bus import EventBus
from events.events import SystemLogCreated
from middleware.logger import get_logger

from .checkpoint_generator import CheckpointGenerator
from .asset_generator import AssetGenerator
from .trace_generator import TraceGenerator
from .metrics_updater import MetricsUpdater
from .agent_simulator import AgentSimulator


class SimulationService:
    def __init__(self,event_bus:EventBus):
        self._event_bus=event_bus
        self._simulation_running=False
        self._simulation_thread:Optional[threading.Thread]=None
        self._lock=threading.Lock()
        self._logger=get_logger()

        self._metrics_updater=MetricsUpdater(event_bus)
        self._checkpoint_generator=CheckpointGenerator(
            event_bus,self._add_system_log
        )
        self._asset_generator=AssetGenerator(
            event_bus,
            self._add_system_log,
            self._metrics_updater.increment_generation_count,
        )
        self._trace_generator=TraceGenerator()
        self._agent_simulator=AgentSimulator(
            event_bus,
            self._checkpoint_generator,
            self._asset_generator,
            self._trace_generator,
            self._metrics_updater,
        )

    def start_simulation(self)->None:
        if self._simulation_running:
            return
        self._simulation_running=True
        self._simulation_thread=threading.Thread(
            target=self._simulation_loop,daemon=True
        )
        self._simulation_thread.start()
        self._logger.info("Simulation started")

    def stop_simulation(self)->None:
        self._simulation_running=False
        if self._simulation_thread:
            self._simulation_thread.join(timeout=2)
        self._logger.info("Simulation stopped")

    def _simulation_loop(self)->None:
        while self._simulation_running:
            try:
                with self._lock:
                    self._tick_simulation()
            except Exception as e:
                self._logger.error(f"Simulation tick error: {e}",exc_info=True)
            time.sleep(1)

    def _tick_simulation(self)->None:
        with session_scope() as session:
            repo=ProjectRepository(session)
            for p in repo.get_all():
                if p.status=="running":
                    self._simulate_project(session,p.id)

    def _can_start_agent(self,session,agent_type:str,project_id:str)->bool:
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

    def _get_next_agents_to_start(self,session,project_id:str)->List[Dict]:
        agent_repo=AgentRepository(session)
        agents=agent_repo.get_by_project(project_id)
        pending=[a for a in agents if a["status"]=="pending"]
        return [
            a for a in pending if self._can_start_agent(session,a["type"],project_id)
        ]

    def _simulate_project(self,session,project_id:str)->None:
        proj_repo=ProjectRepository(session)
        agent_repo=AgentRepository(session)
        project=proj_repo.get(project_id)
        if not project:
            return
        agents=agent_repo.get_by_project(project_id)
        running_agents=[a for a in agents if a["status"]=="running"]
        if running_agents:
            for agent in running_agents:
                self._agent_simulator.simulate_agent(session,agent)
        else:
            ready_agents=self._get_next_agents_to_start(session,project_id)
            if ready_agents:
                for agent in ready_agents:
                    self._agent_simulator.start_agent(session,agent)
            else:
                completed=all(a["status"]=="completed" for a in agents)
                if completed:
                    project.status="completed"
                    project.updated_at=datetime.now()
                    self._add_system_log(
                        session,project_id,"info","System","プロジェクト完了！"
                    )
        self._metrics_updater.update_project_metrics(session,project_id)

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
