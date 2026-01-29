from typing import Dict, Any, List
from .base import BaseSchema


class OutputSettingsSchema(BaseSchema):
    default_dir: str


class CostServiceSettingsSchema(BaseSchema):
    enabled: bool = True
    monthly_limit: float = 10.0


class CostSettingsSchema(BaseSchema):
    global_enabled: bool = True
    global_monthly_limit: float = 100.0
    alert_threshold: int = 80
    stop_on_budget_exceeded: bool = False
    services: Dict[str, CostServiceSettingsSchema] = {}
