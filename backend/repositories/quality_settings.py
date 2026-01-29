from typing import Dict
from sqlalchemy.orm import Session
from models.tables import QualitySetting
from agent_settings import QualityCheckConfig, get_default_quality_settings


class QualitySettingsRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_all(self, project_id: str) -> Dict[str, QualityCheckConfig]:
        settings = self.session.query(QualitySetting).filter(QualitySetting.project_id == project_id).all()
        if not settings:
            return get_default_quality_settings()
        result = {}
        for s in settings:
            cfg = s.config or {}
            result[s.agent_type] = QualityCheckConfig(
                enabled=cfg.get("enabled", True),
                max_retries=cfg.get("maxRetries", 3),
                is_high_cost=cfg.get("isHighCost", False),
            )
        defaults = get_default_quality_settings()
        for k, v in defaults.items():
            if k not in result:
                result[k] = v
        return result

    def set(self, project_id: str, agent_type: str, config: QualityCheckConfig) -> None:
        existing = (
            self.session.query(QualitySetting)
            .filter(QualitySetting.project_id == project_id, QualitySetting.agent_type == agent_type)
            .first()
        )
        cfg_dict = config.to_dict()
        if existing:
            existing.config = cfg_dict
        else:
            qs = QualitySetting(project_id=project_id, agent_type=agent_type, config=cfg_dict)
            self.session.add(qs)
        self.session.flush()

    def reset(self, project_id: str) -> None:
        self.session.query(QualitySetting).filter(QualitySetting.project_id == project_id).delete()
        self.session.flush()
