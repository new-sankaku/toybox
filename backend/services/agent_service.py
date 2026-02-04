from datetime import datetime
from typing import Optional,Dict,List

from models.database import session_scope
from repositories import (
    ProjectRepository,
    AgentRepository,
    AgentLogRepository,
    SystemLogRepository,
    CheckpointRepository,
    AssetRepository,
)
from repositories.workflow_snapshot import WorkflowSnapshotRepository
from repositories.agent_memory import AgentMemoryRepository
from config_loader import get_workflow_dependencies,get_initial_task
from events.event_bus import EventBus
from events.events import AgentStarted,AgentRetried
from services.base_service import BaseService


class AgentService(BaseService):
    def __init__(self,event_bus:EventBus):
        super().__init__(event_bus)

    def get_agents_by_project(
        self,project_id:str,include_workers:bool=True
    )->List[Dict]:
        with session_scope() as session:
            repo=AgentRepository(session)
            return repo.get_by_project(project_id,include_workers=include_workers)

    def get_workers_by_parent(self,parent_agent_id:str)->List[Dict]:
        with session_scope() as session:
            repo=AgentRepository(session)
            return repo.get_workers_by_parent(parent_agent_id)

    def get_agent(self,agent_id:str)->Optional[Dict]:
        with session_scope() as session:
            repo=AgentRepository(session)
            return repo.get_dict(agent_id)

    def get_agent_logs(self,agent_id:str)->List[Dict]:
        with session_scope() as session:
            repo=AgentLogRepository(session)
            return repo.get_by_agent(agent_id)

    def create_agent(self,project_id:str,agent_type:str)->Dict:
        with session_scope() as session:
            repo=AgentRepository(session)
            return repo.create_from_dict(project_id,{"type":agent_type})

    def create_worker_agent(
        self,
        project_id:str,
        parent_agent_id:str,
        worker_type:str,
        task:str,
    )->Dict:
        with session_scope() as session:
            repo=AgentRepository(session)
            return repo.create_worker(
                project_id,parent_agent_id,worker_type,task
            )

    def update_agent(self,agent_id:str,data:Dict)->Optional[Dict]:
        with session_scope() as session:
            repo=AgentRepository(session)
            return repo.update_from_dict(agent_id,data)

    def add_agent_log(
        self,
        agent_id:str,
        level:str,
        message:str,
        progress:Optional[int]=None,
    )->None:
        with session_scope() as session:
            repo=AgentLogRepository(session)
            repo.add_log(agent_id,level,message,progress)

    def retry_agent(self,agent_id:str)->Optional[Dict]:
        with session_scope() as session:
            agent_repo=AgentRepository(session)
            syslog_repo=SystemLogRepository(session)
            agent=agent_repo.get(agent_id)
            if not agent:
                return None
            retryable_statuses={"failed","interrupted"}
            if agent.status not in retryable_statuses:
                return None
            old_status=agent.status
            agent.status="pending"
            agent.progress=0
            agent.current_task=None
            agent.started_at=None
            agent.completed_at=None
            agent.error=None
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
                f"エージェント {display_name} を再試行待ちに設定（前状態: {old_status}）",
            )
            result=agent_repo.to_dict(agent)
            self._event_bus.publish(
                AgentRetried(
                    project_id=agent.project_id,
                    agent_id=agent.id,
                    agent=result,
                    previous_status=old_status,
                )
            )
            return result

    def pause_agent(self,agent_id:str)->Optional[Dict]:
        with session_scope() as session:
            agent_repo=AgentRepository(session)
            syslog_repo=SystemLogRepository(session)
            agent=agent_repo.get(agent_id)
            if not agent:
                return None
            pausable_statuses={"running","waiting_approval"}
            if agent.status not in pausable_statuses:
                return None
            old_status=agent.status
            agent.status="paused"
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
                f"エージェント {display_name} を一時停止（前状態: {old_status}）",
            )
            return agent_repo.to_dict(agent)

    def resume_agent(self,agent_id:str)->Optional[Dict]:
        with session_scope() as session:
            agent_repo=AgentRepository(session)
            syslog_repo=SystemLogRepository(session)
            agent=agent_repo.get(agent_id)
            if not agent:
                return None
            resumable_statuses={"paused","waiting_response"}
            if agent.status not in resumable_statuses:
                return None
            old_status=agent.status
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
                f"エージェント {display_name} を再開（前状態: {old_status}）",
            )
            return agent_repo.to_dict(agent)

    def get_retryable_agents(self,project_id:str)->List[Dict]:
        with session_scope() as session:
            agent_repo=AgentRepository(session)
            agents=agent_repo.get_by_project(project_id)
            retryable_statuses={"failed","interrupted"}
            return [a for a in agents if a["status"] in retryable_statuses]

    def get_interrupted_agents(
        self,project_id:Optional[str]=None
    )->List[Dict]:
        with session_scope() as session:
            agent_repo=AgentRepository(session)
            if project_id:
                agents=agent_repo.get_by_project(project_id)
            else:
                all_projects=ProjectRepository(session).get_all()
                agents=[]
                for p in all_projects:
                    agents.extend(agent_repo.get_by_project(p.id))
            return [a for a in agents if a["status"]=="interrupted"]

    def activate_agent_for_intervention(
        self,agent_id:str,intervention_id:str
    )->Dict:
        with session_scope() as session:
            agent_repo=AgentRepository(session)
            syslog_repo=SystemLogRepository(session)
            from repositories import InterventionRepository

            intervention_repo=InterventionRepository(session)
            agent=agent_repo.get(agent_id)
            if not agent:
                return {"activated":False,"reason":"agent_not_found"}
            intervention=intervention_repo.get(intervention_id)
            if not intervention:
                return {"activated":False,"reason":"intervention_not_found"}
            activatable_statuses={"completed","failed","paused","pending"}
            display_name=(
                agent.metadata_.get("displayName",agent.type)
                if agent.metadata_
                else agent.type
            )
            if agent.status in activatable_statuses:
                old_status=agent.status
                agent.status="running"
                agent.current_task=(
                    f"追加タスク: {intervention.message[:30]}..."
                )
                agent.updated_at=datetime.now()
                if not agent.started_at:
                    agent.started_at=datetime.now()
                session.flush()
                syslog_repo.add_log(
                    agent.project_id,
                    "info",
                    "System",
                    f"エージェント {display_name} を連絡により起動（前状態: {old_status}）",
                )
                paused_agents=self._pause_subsequent_agents(session,agent)
                return {
                    "activated":True,
                    "agent":agent_repo.to_dict(agent),
                    "previousStatus":old_status,
                    "pausedAgents":paused_agents,
                }
            elif agent.status=="running":
                return {
                    "activated":False,
                    "reason":"already_running",
                    "agent":agent_repo.to_dict(agent),
                }
            elif agent.status=="waiting_approval":
                return {
                    "activated":False,
                    "reason":"waiting_approval",
                    "agent":agent_repo.to_dict(agent),
                }
            elif agent.status=="waiting_response":
                agent.status="running"
                agent.current_task=(
                    f"追加タスク: {intervention.message[:30]}..."
                )
                agent.updated_at=datetime.now()
                session.flush()
                syslog_repo.add_log(
                    agent.project_id,
                    "info",
                    "System",
                    f"エージェント {display_name} が返答を受けて再開",
                )
                return {
                    "activated":True,
                    "agent":agent_repo.to_dict(agent),
                    "previousStatus":"waiting_response",
                    "pausedAgents":[],
                }
            return {
                "activated":False,
                "reason":"invalid_status",
                "currentStatus":agent.status,
            }

    def _pause_subsequent_agents(self,session,target_agent)->List[Dict]:
        agent_repo=AgentRepository(session)
        syslog_repo=SystemLogRepository(session)
        agents=agent_repo.get_by_project(target_agent.project_id)
        target_phase=target_agent.phase or 0
        paused_agents=[]
        for agent_dict in agents:
            agent_phase=agent_dict.get("phase",0)
            if agent_phase>target_phase and agent_dict["status"]=="running":
                agent=agent_repo.get(agent_dict["id"])
                agent.status="paused"
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
                    f"エージェント {display_name} を後続フェーズとして一時停止",
                )
                paused_agents.append(agent_repo.to_dict(agent))
        return paused_agents

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

    @property
    def agents(self)->Dict[str,Dict]:
        result={}
        with session_scope() as session:
            repo=AgentRepository(session)
            for agent in repo.get_all():
                result[agent.id]=repo.to_dict(agent)
        return result

    def create_agent_memory(
        self,
        category:str,
        agent_type:str,
        content:str,
        project_id:Optional[str]=None,
        source_project_id:Optional[str]=None,
        relevance_score:int=100,
    )->Dict:
        with session_scope() as session:
            repo=AgentMemoryRepository(session)
            existing=repo.find_duplicate(agent_type,content,category)
            if existing:
                existing.relevance_score=min(
                    existing.relevance_score+10,200
                )
                session.flush()
                return repo.to_dict(existing)
            return repo.create_memory(
                category,
                agent_type,
                content,
                project_id,
                source_project_id,
                relevance_score,
            )

    def get_agent_memories(
        self,
        agent_type:str,
        project_id:Optional[str]=None,
        categories:Optional[List[str]]=None,
        limit:int=10,
    )->List[Dict]:
        with session_scope() as session:
            repo=AgentMemoryRepository(session)
            return repo.get_memories_for_agent(
                agent_type,project_id,categories,limit
            )
