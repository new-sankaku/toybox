from typing import Dict,Any,Optional
from events.event_bus import EventBus
from events.events import SystemLogCreated
from repositories import AgentLogRepository,SystemLogRepository
from middleware.logger import get_logger


class BaseService:
    def __init__(self,event_bus:EventBus):
        self._event_bus=event_bus
        self._logger=get_logger()

    def _add_system_log(
        self,
        session,
        project_id:str,
        level:str,
        source:str,
        message:str,
    )->Dict[str,Any]:
        repo=SystemLogRepository(session)
        log_dict=repo.add_log(project_id,level,source,message)
        self._event_bus.publish(
            SystemLogCreated(project_id=project_id,log=log_dict)
        )
        return log_dict

    def _add_agent_log(
        self,
        session,
        agent_id:str,
        level:str,
        message:str,
        progress:Optional[int]=None,
    )->None:
        repo=AgentLogRepository(session)
        repo.add_log(agent_id,level,message,progress)
