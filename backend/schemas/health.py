from typing import Dict, Any
from .base import BaseSchema


class HealthResponse(BaseSchema):
    status: str
    service: str
    agent_mode: str


class SystemStatsResponse(BaseSchema):
    backup_info: Dict[str, Any]
    archive_stats: Dict[str, Any]
