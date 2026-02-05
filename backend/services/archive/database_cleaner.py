from typing import Dict

from models.database import session_scope
from models.tables import Agent,AgentLog,AgentTrace,SystemLog
from middleware.logger import get_logger

from .retention_policy import DataRetentionPolicy


class DatabaseCleaner:
    def __init__(self,policy:DataRetentionPolicy):
        self._policy=policy
        self._logger=get_logger()

    def cleanup_old_records(
        self,project_id:str|None=None
    )->Dict[str,int]:
        cutoff_date=self._policy.get_cutoff_date()
        deleted_counts={"traces":0,"agent_logs":0,"system_logs":0}

        with session_scope() as session:
            trace_query=session.query(AgentTrace).filter(
                AgentTrace.started_at<cutoff_date
            )
            if project_id:
                trace_query=trace_query.filter(
                    AgentTrace.project_id==project_id
                )
            deleted_counts["traces"]=trace_query.delete(
                synchronize_session=False
            )

            log_query=session.query(AgentLog).filter(
                AgentLog.created_at<cutoff_date
            )
            deleted_counts["agent_logs"]=log_query.delete(
                synchronize_session=False
            )

            system_query=session.query(SystemLog).filter(
                SystemLog.created_at<cutoff_date
            )
            if project_id:
                system_query=system_query.filter(
                    SystemLog.project_id==project_id
                )
            deleted_counts["system_logs"]=system_query.delete(
                synchronize_session=False
            )

            session.commit()

        total=sum(deleted_counts.values())
        if total>0:
            self._logger.info(
                f"DatabaseCleaner: cleaned up {total} old records: {deleted_counts}"
            )
        return deleted_counts

    def cleanup_project_data(
        self,project_id:str,keep_recent_days:int=7
    )->Dict[str,int]:
        cutoff_date=self._policy.get_cutoff_date(keep_recent_days)
        deleted_counts={"traces":0,"agent_logs":0}

        with session_scope() as session:
            deleted_counts["traces"]=(
                session.query(AgentTrace)
                .filter(
                    AgentTrace.project_id==project_id,
                    AgentTrace.started_at<cutoff_date,
                )
                .delete(synchronize_session=False)
            )

            agent_ids=[
                a.id
                for a in session.query(Agent)
                .filter(Agent.project_id==project_id)
                .all()
            ]
            if agent_ids:
                deleted_counts["agent_logs"]=(
                    session.query(AgentLog)
                    .filter(
                        AgentLog.agent_id.in_(agent_ids),
                        AgentLog.created_at<cutoff_date,
                    )
                    .delete(synchronize_session=False)
                )

            session.commit()

        total=sum(deleted_counts.values())
        if total>0:
            self._logger.info(
                f"DatabaseCleaner: cleaned up project {project_id}: {deleted_counts}"
            )
        return deleted_counts

    def delete_traces(
        self,
        project_id:str,
        agent_id:str|None=None,
        cutoff_date=None,
    )->Dict[str,int]:
        deleted={"traces":0,"agent_logs":0}

        with session_scope() as session:
            trace_query=session.query(AgentTrace).filter(
                AgentTrace.project_id==project_id
            )
            if agent_id:
                trace_query=trace_query.filter(AgentTrace.agent_id==agent_id)
            if cutoff_date:
                trace_query=trace_query.filter(
                    AgentTrace.started_at<cutoff_date
                )
            deleted["traces"]=trace_query.delete(synchronize_session=False)

            if agent_id:
                deleted["agent_logs"]=(
                    session.query(AgentLog)
                    .filter(AgentLog.agent_id==agent_id)
                    .delete(synchronize_session=False)
                )

            session.commit()

        return deleted

    def get_statistics(
        self,project_id:str|None=None
    )->Dict[str,any]:
        with session_scope() as session:
            trace_query=session.query(AgentTrace)
            agent_log_query=session.query(AgentLog)
            system_log_query=session.query(SystemLog)

            if project_id:
                trace_query=trace_query.filter(
                    AgentTrace.project_id==project_id
                )
                system_log_query=system_log_query.filter(
                    SystemLog.project_id==project_id
                )

            trace_count=trace_query.count()
            agent_log_count=agent_log_query.count()
            system_log_count=system_log_query.count()

            cutoff_date=self._policy.get_cutoff_date()
            old_trace_count=trace_query.filter(
                AgentTrace.started_at<cutoff_date
            ).count()
            old_agent_log_count=agent_log_query.filter(
                AgentLog.created_at<cutoff_date
            ).count()
            old_system_log_count=system_log_query.filter(
                SystemLog.created_at<cutoff_date
            ).count()

            return {
                "total":{
                    "traces":trace_count,
                    "agent_logs":agent_log_count,
                    "system_logs":system_log_count,
                },
                "older_than_retention":{
                    "traces":old_trace_count,
                    "agent_logs":old_agent_log_count,
                    "system_logs":old_system_log_count,
                },
                "retention_days":self._policy.retention_days,
                "cutoff_date":cutoff_date.isoformat(),
            }
