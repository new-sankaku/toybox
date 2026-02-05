from typing import Dict

from agent_settings import QualityCheckConfig
from repositories import QualitySettingsRepository


class QualitySettingsManager:
    def get_all(self,session,project_id:str)->Dict[str,QualityCheckConfig]:
        repo=QualitySettingsRepository(session)
        return repo.get_all(project_id)

    def set(
        self,
        session,
        project_id:str,
        agent_type:str,
        config:QualityCheckConfig,
    )->None:
        repo=QualitySettingsRepository(session)
        repo.set(project_id,agent_type,config)

    def reset(self,session,project_id:str)->None:
        repo=QualitySettingsRepository(session)
        repo.reset(project_id)

    def get_for_agent(
        self,
        session,
        project_id:str,
        agent_type:str,
    )->QualityCheckConfig:
        settings=self.get_all(session,project_id)
        return settings.get(agent_type,QualityCheckConfig())
