from datetime import datetime
from typing import Optional,Dict,List

from models.database import session_scope
from repositories import ProjectRepository,AgentRepository,SystemLogRepository
from events.event_bus import EventBus
from events.events import AgentRetried
from services.base_service import BaseService


def _get_display_name(agent)->str:
    if agent.metadata_:
        return agent.metadata_.get("displayName",agent.type)
    return agent.type


class AgentLifecycleManager(BaseService):
    def __init__(self,event_bus:EventBus):
        super().__init__(event_bus)

    def retry_agent(self,agent_id:str)->Optional[Dict]:
        with session_scope() as session:
            agent_repo=AgentRepository(session)
            syslog_repo=SystemLogRepository(session)
            agent=agent_repo.get(agent_id)
            if not agent:
                return None
            if agent.status not in {"failed","interrupted"}:
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
            syslog_repo.add_log(
                agent.project_id,"info","System",
                f"エージェント {_get_display_name(agent)} を再試行待ちに設定（前状態: {old_status}）",
            )
            result=agent_repo.to_dict(agent)
            self._event_bus.publish(AgentRetried(
                project_id=agent.project_id,agent_id=agent.id,
                agent=result,previous_status=old_status,
            ))
            return result

    def pause_agent(self,agent_id:str)->Optional[Dict]:
        with session_scope() as session:
            agent_repo=AgentRepository(session)
            syslog_repo=SystemLogRepository(session)
            agent=agent_repo.get(agent_id)
            if not agent or agent.status not in {"running","waiting_approval"}:
                return None
            old_status=agent.status
            agent.status="paused"
            agent.updated_at=datetime.now()
            session.flush()
            syslog_repo.add_log(
                agent.project_id,"info","System",
                f"エージェント {_get_display_name(agent)} を一時停止（前状態: {old_status}）",
            )
            return agent_repo.to_dict(agent)

    def resume_agent(self,agent_id:str)->Optional[Dict]:
        with session_scope() as session:
            agent_repo=AgentRepository(session)
            syslog_repo=SystemLogRepository(session)
            agent=agent_repo.get(agent_id)
            if not agent or agent.status not in {"paused","waiting_response"}:
                return None
            old_status=agent.status
            agent.status="running"
            agent.updated_at=datetime.now()
            session.flush()
            syslog_repo.add_log(
                agent.project_id,"info","System",
                f"エージェント {_get_display_name(agent)} を再開（前状態: {old_status}）",
            )
            return agent_repo.to_dict(agent)

    def get_retryable_agents(self,project_id:str)->List[Dict]:
        with session_scope() as session:
            agents=AgentRepository(session).get_by_project(project_id)
            return [a for a in agents if a["status"] in {"failed","interrupted"}]

    def get_interrupted_agents(self,project_id:Optional[str]=None)->List[Dict]:
        with session_scope() as session:
            agent_repo=AgentRepository(session)
            if project_id:
                agents=agent_repo.get_by_project(project_id)
            else:
                agents=[]
                for p in ProjectRepository(session).get_all():
                    agents.extend(agent_repo.get_by_project(p.id))
            return [a for a in agents if a["status"]=="interrupted"]

    def activate_agent_for_intervention(self,agent_id:str,intervention_id:str)->Dict:
        with session_scope() as session:
            agent_repo=AgentRepository(session)
            syslog_repo=SystemLogRepository(session)
            from repositories import InterventionRepository
            agent=agent_repo.get(agent_id)
            if not agent:
                return {"activated":False,"reason":"agent_not_found"}
            intervention=InterventionRepository(session).get(intervention_id)
            if not intervention:
                return {"activated":False,"reason":"intervention_not_found"}
            return self._handle_activation(
                session,agent_repo,syslog_repo,agent,intervention
            )

    def _handle_activation(self,session,agent_repo,syslog_repo,agent,intervention)->Dict:
        display_name=_get_display_name(agent)
        task_text=f"追加タスク: {intervention.message[:30]}..."
        if agent.status in {"completed","failed","paused","pending"}:
            old_status=agent.status
            agent.status="running"
            agent.current_task=task_text
            agent.updated_at=datetime.now()
            if not agent.started_at:
                agent.started_at=datetime.now()
            session.flush()
            syslog_repo.add_log(
                agent.project_id,"info","System",
                f"エージェント {display_name} を連絡により起動（前状態: {old_status}）",
            )
            paused=self._pause_subsequent_agents(session,agent)
            return {
                "activated":True,"agent":agent_repo.to_dict(agent),
                "previousStatus":old_status,"pausedAgents":paused,
            }
        if agent.status=="running":
            return {"activated":False,"reason":"already_running","agent":agent_repo.to_dict(agent)}
        if agent.status=="waiting_approval":
            return {"activated":False,"reason":"waiting_approval","agent":agent_repo.to_dict(agent)}
        if agent.status=="waiting_response":
            agent.status="running"
            agent.current_task=task_text
            agent.updated_at=datetime.now()
            session.flush()
            syslog_repo.add_log(
                agent.project_id,"info","System",
                f"エージェント {display_name} が返答を受けて再開",
            )
            return {
                "activated":True,"agent":agent_repo.to_dict(agent),
                "previousStatus":"waiting_response","pausedAgents":[],
            }
        return {"activated":False,"reason":"invalid_status","currentStatus":agent.status}

    def _pause_subsequent_agents(self,session,target_agent)->List[Dict]:
        agent_repo=AgentRepository(session)
        syslog_repo=SystemLogRepository(session)
        target_phase=target_agent.phase or 0
        paused=[]
        for ad in agent_repo.get_by_project(target_agent.project_id):
            if ad.get("phase",0)>target_phase and ad["status"]=="running":
                a=agent_repo.get(ad["id"])
                a.status="paused"
                a.updated_at=datetime.now()
                session.flush()
                syslog_repo.add_log(
                    a.project_id,"info","System",
                    f"エージェント {_get_display_name(a)} を後続フェーズとして一時停止",
                )
                paused.append(agent_repo.to_dict(a))
        return paused
