from typing import Dict, Any, List
from .base import BaseSchema


class RecoveryStatusResponse(BaseSchema):
    interrupted_agents: int
    interrupted_projects: int


class RecoveryRetryAllResponse(BaseSchema):
    recovered_agents: List[str]
    recovered_projects: List[str]
