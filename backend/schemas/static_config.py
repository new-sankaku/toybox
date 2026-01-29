from typing import Dict, Any, List
from .base import BaseSchema


class AgentUIInfoSchema(BaseSchema):
    label: str
    short_label: str
    phase: int
    role: str
    high_cost: bool


class UiSettingsResponse(BaseSchema):
    ui_phases: List[Dict[str, Any]]
    agent_service_map: Dict[str, str]  # agent_id -> output_type
    service_labels: Dict[str, str]
    status_labels: Dict[str, str]
    agent_status_labels: Dict[str, str]
    approval_status_labels: Dict[str, str]
    asset_type_labels: Dict[str, str]
    resolution_labels: Dict[str, str]
    role_labels: Dict[str, str]
    agent_roles: Dict[str, str]
    agents: Dict[str, AgentUIInfoSchema]


class CostSettingsDefaultsResponse(BaseSchema):
    global_enabled: bool
    global_monthly_limit: float
    alert_threshold: int
    stop_on_budget_exceeded: bool
    services: Dict[str, Any]


class OutputSettingsDefaultsResponse(BaseSchema):
    default_dir: str
