from datetime import datetime
from typing import Dict,List

from models.database import session_scope
from models.tables import AgentLog,AgentTrace
from middleware.logger import get_logger

from .archive import (
    DataRetentionPolicy,
    DatabaseCleaner,
    ZipArchiver,
    serialize_logs,
    serialize_traces,
)


class ArchiveService:
    def __init__(
        self,
        retention_days:int=30,
        archive_dir:str|None=None,
        policy:DataRetentionPolicy|None=None,
        cleaner:DatabaseCleaner|None=None,
        archiver:ZipArchiver|None=None,
    ):
        self._policy=policy or DataRetentionPolicy(retention_days)
        self._cleaner=cleaner or DatabaseCleaner(self._policy)
        self._archiver=archiver or ZipArchiver(archive_dir)
        self._logger=get_logger()

    def set_retention_days(self,days:int)->None:
        self._policy.retention_days=days

    def cleanup_old_traces(
        self,project_id:str|None=None
    )->Dict[str,int]:
        return self._cleaner.cleanup_old_records(project_id)

    def cleanup_completed_project_data(
        self,project_id:str,keep_recent_days:int=7
    )->Dict[str,int]:
        return self._cleaner.cleanup_project_data(project_id,keep_recent_days)

    def get_data_statistics(
        self,project_id:str|None=None
    )->Dict[str,any]:
        return self._cleaner.get_statistics(project_id)

    def estimate_cleanup_size(
        self,project_id:str|None=None
    )->Dict[str,int]:
        stats=self.get_data_statistics(project_id)
        return stats.get("older_than_retention",{})

    def export_traces_to_zip(
        self,
        project_id:str,
        agent_id:str|None=None,
        include_logs:bool=True,
    )->str|None:
        with session_scope() as session:
            query=session.query(AgentTrace).filter(
                AgentTrace.project_id==project_id
            )
            if agent_id:
                query=query.filter(AgentTrace.agent_id==agent_id)
            traces=query.all()

            if not traces:
                return None

            trace_data=serialize_traces(traces)

            log_data=[]
            if include_logs:
                agent_ids=list(set(t.agent_id for t in traces))
                for aid in agent_ids:
                    logs=(
                        session.query(AgentLog)
                        .filter(AgentLog.agent_id==aid)
                        .all()
                    )
                    log_data.extend(serialize_logs(logs))

            files={"traces.json":trace_data}
            if log_data:
                files["agent_logs.json"]=log_data

            files["metadata.json"]={
                "projectId":project_id,
                "agentId":agent_id,
                "exportedAt":datetime.now().isoformat(),
                "traceCount":len(trace_data),
                "logCount":len(log_data),
            }

            filename=self._archiver.generate_filename(
                "traces",project_id,agent_id
            )
            zip_path=self._archiver.create_archive(filename,files)

            self._logger.info(
                f"ArchiveService: exported {len(trace_data)} traces to {zip_path}"
            )
            return zip_path

    def archive_and_cleanup(
        self,project_id:str,agent_id:str|None=None
    )->Dict[str,any]:
        zip_path=self.export_traces_to_zip(project_id,agent_id,include_logs=True)
        if not zip_path:
            return {"success":False,"error":"No traces to archive"}

        deleted=self._cleaner.delete_traces(project_id,agent_id)

        return {
            "success":True,
            "zipPath":zip_path,
            "zipSize":self._archiver.get_archive_size(zip_path),
            "deleted":deleted,
        }

    def archive_old_traces(
        self,days_old:int|None=None
    )->Dict[str,any]:
        cutoff_date=self._policy.get_cutoff_date(days_old)

        with session_scope() as session:
            traces=(
                session.query(AgentTrace)
                .filter(AgentTrace.started_at<cutoff_date)
                .all()
            )

            if not traces:
                return {
                    "success":True,
                    "message":"No old traces to archive",
                    "archived":0,
                }

            trace_data=serialize_traces(traces)

            files={
                "traces.json":trace_data,
                "metadata.json":{
                    "archivedAt":datetime.now().isoformat(),
                    "cutoffDate":cutoff_date.isoformat(),
                    "traceCount":len(trace_data),
                },
            }

            filename=self._archiver.generate_filename("archive_old")
            zip_path=self._archiver.create_archive(filename,files)

            deleted=(
                session.query(AgentTrace)
                .filter(AgentTrace.started_at<cutoff_date)
                .delete(synchronize_session=False)
            )
            session.commit()

        return {
            "success":True,
            "zipPath":zip_path,
            "zipSize":self._archiver.get_archive_size(zip_path),
            "archived":len(trace_data),
            "deleted":deleted,
        }

    def list_archives(self)->List[Dict]:
        return self._archiver.list_archives()

    def delete_archive(self,archive_name:str)->bool:
        return self._archiver.delete_archive(archive_name)

    def get_archive_info(self)->Dict[str,any]:
        info=self._archiver.get_info()
        info["retentionDays"]=self._policy.retention_days
        return info
