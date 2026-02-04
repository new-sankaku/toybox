from datetime import datetime
from typing import Optional,Dict,List

from models.database import session_scope
from repositories import (
    InterventionRepository,
    AgentRepository,
    SystemLogRepository,
    UploadedFileRepository,
)
from events.event_bus import EventBus
from services.base_service import BaseService


class InterventionService(BaseService):
    def __init__(self,event_bus:EventBus):
        super().__init__(event_bus)

    def get_interventions_by_project(self,project_id:str)->List[Dict]:
        with session_scope() as session:
            repo=InterventionRepository(session)
            return repo.get_by_project(project_id)

    def get_intervention(self,intervention_id:str)->Optional[Dict]:
        with session_scope() as session:
            repo=InterventionRepository(session)
            return repo.get_dict(intervention_id)

    def create_intervention(
        self,
        project_id:str,
        target_type:str,
        target_agent_id:Optional[str],
        priority:str,
        message:str,
        attached_file_ids:List[str],
    )->Dict:
        with session_scope() as session:
            repo=InterventionRepository(session)
            intervention=repo.create_from_dict(
                {
                    "projectId":project_id,
                    "targetType":target_type,
                    "targetAgentId":target_agent_id,
                    "priority":priority,
                    "message":message,
                    "attachedFileIds":attached_file_ids,
                }
            )
            target_desc=(
                "全エージェント"
                if target_type=="all"
                else f"エージェント {target_agent_id}"
            )
            priority_desc="緊急" if priority=="urgent" else"通常"
            self._add_system_log(
                session,
                project_id,
                "info",
                "Human",
                f"[{priority_desc}] {target_desc}への介入: {message[:50]}...",
            )
            return intervention

    def acknowledge_intervention(
        self,intervention_id:str
    )->Optional[Dict]:
        with session_scope() as session:
            repo=InterventionRepository(session)
            return repo.acknowledge(intervention_id)

    def process_intervention(self,intervention_id:str)->Optional[Dict]:
        with session_scope() as session:
            repo=InterventionRepository(session)
            intervention=repo.process(intervention_id)
            if intervention:
                self._add_system_log(
                    session,
                    intervention["projectId"],
                    "info",
                    "System",
                    f"介入処理完了: {intervention['message'][:30]}...",
                )
            return intervention

    def deliver_intervention(self,intervention_id:str)->Optional[Dict]:
        with session_scope() as session:
            repo=InterventionRepository(session)
            return repo.deliver(intervention_id)

    def delete_intervention(self,intervention_id:str)->bool:
        with session_scope() as session:
            repo=InterventionRepository(session)
            intervention=repo.get(intervention_id)
            if not intervention:
                return False
            project_id=intervention.project_id
            result=repo.delete(intervention_id)
            if result:
                self._add_system_log(
                    session,
                    project_id,
                    "info",
                    "System",
                    f"介入削除: {intervention.message[:30]}...",
                )
            return result

    def get_pending_interventions_for_agent(
        self,agent_id:str
    )->List[Dict]:
        with session_scope() as session:
            intervention_repo=InterventionRepository(session)
            agent_repo=AgentRepository(session)
            agent=agent_repo.get(agent_id)
            if not agent:
                return []
            all_interventions=intervention_repo.get_by_project(
                agent.project_id
            )
            pending_interventions=[]
            for iv in all_interventions:
                if iv["status"] not in ("pending","acknowledged"):
                    continue
                if iv["targetType"]=="all":
                    pending_interventions.append(iv)
                elif (
                    iv["targetType"]=="specific"
                    and iv.get("targetAgentId")==agent_id
                ):
                    pending_interventions.append(iv)
            return pending_interventions

    def add_intervention_response(
        self,
        intervention_id:str,
        sender:str,
        message:str,
        agent_id:str=None,
    )->Optional[Dict]:
        with session_scope() as session:
            intervention_repo=InterventionRepository(session)
            agent_repo=AgentRepository(session)
            syslog_repo=SystemLogRepository(session)
            intervention=intervention_repo.get(intervention_id)
            if not intervention:
                return None
            result=intervention_repo.add_response(
                intervention_id,sender,message,agent_id
            )
            if sender=="agent" and agent_id:
                agent=agent_repo.get(agent_id)
                if agent:
                    agent.status="waiting_response"
                    agent.current_task="オペレーターの返答待ち"
                    agent.updated_at=datetime.now()
                    session.flush()
                    display_name=(
                        agent.metadata_.get("displayName",agent.type)
                        if agent.metadata_
                        else agent.type
                    )
                    syslog_repo.add_log(
                        intervention.project_id,
                        "info",
                        display_name,
                        f"質問: {message[:50]}...",
                    )
            elif sender=="operator":
                syslog_repo.add_log(
                    intervention.project_id,
                    "info",
                    "Human",
                    f"返答: {message[:50]}...",
                )
            return result

    def respond_to_intervention(
        self,intervention_id:str,message:str
    )->Optional[Dict]:
        with session_scope() as session:
            intervention_repo=InterventionRepository(session)
            agent_repo=AgentRepository(session)
            syslog_repo=SystemLogRepository(session)
            intervention=intervention_repo.get(intervention_id)
            if not intervention:
                return None
            result=intervention_repo.add_response(
                intervention_id,"operator",message
            )
            if intervention.target_agent_id:
                agent=agent_repo.get(intervention.target_agent_id)
                if agent and agent.status=="waiting_response":
                    agent.status="running"
                    agent.current_task=f"返答を受けて処理再開"
                    agent.updated_at=datetime.now()
                    session.flush()
                    display_name=(
                        agent.metadata_.get("displayName",agent.type)
                        if agent.metadata_
                        else agent.type
                    )
                    syslog_repo.add_log(
                        intervention.project_id,
                        "info",
                        "System",
                        f"エージェント {display_name} が返答を受けて再開",
                    )
            if result:
                intervention_repo.set_status(intervention_id,"acknowledged")
            return result

    def get_uploaded_files_by_project(self,project_id:str)->List[Dict]:
        with session_scope() as session:
            repo=UploadedFileRepository(session)
            return repo.get_by_project(project_id)

    def get_uploaded_file(self,file_id:str)->Optional[Dict]:
        with session_scope() as session:
            repo=UploadedFileRepository(session)
            return repo.get_dict(file_id)

    def create_uploaded_file(
        self,
        project_id:str,
        filename:str,
        original_filename:str,
        mime_type:str,
        category:str,
        size_bytes:int,
        description:str,
    )->Dict:
        with session_scope() as session:
            repo=UploadedFileRepository(session)
            uf=repo.create_from_dict(
                {
                    "projectId":project_id,
                    "filename":filename,
                    "originalFilename":original_filename,
                    "mimeType":mime_type,
                    "category":category,
                    "sizeBytes":size_bytes,
                    "description":description,
                }
            )
            self._add_system_log(
                session,
                project_id,
                "info",
                "Upload",
                f"ファイルアップロード: {original_filename} ({category})",
            )
            return uf

    def delete_uploaded_file(self,file_id:str)->bool:
        with session_scope() as session:
            repo=UploadedFileRepository(session)
            return repo.delete(file_id)

    def update_uploaded_file(
        self,file_id:str,data:Dict
    )->Optional[Dict]:
        with session_scope() as session:
            repo=UploadedFileRepository(session)
            return repo.update_from_dict(file_id,data)
