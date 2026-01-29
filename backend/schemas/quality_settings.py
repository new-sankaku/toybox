from typing import Dict, Any, List
from .base import BaseSchema


class QualitySettingsResponse(BaseSchema):
    settings: Dict[str, Dict[str, Any]]
    phases: Dict[str, List[str]]
    display_names: Dict[str, str]


class QualitySettingUpdateResponse(BaseSchema):
    agent_type: str
    config: Dict[str, Any]


class BulkQualityUpdateResponse(BaseSchema):
    updated: Dict[str, Dict[str, Any]]
    count: int


class DefaultQualitySettingsResponse(BaseSchema):
    settings: Dict[str, Dict[str, Any]]
    phases: Dict[str, List[str]]
    display_names: Dict[str, str]
    high_cost_agents: List[str]


class QualitySettingsResetResponse(BaseSchema):
    message: str
    settings: Dict[str, Dict[str, Any]]


class AgentDefinitionsResponse(BaseSchema):
    agents: Dict[str, Dict[str, Any]]
    ui_phases: List[Dict[str, Any]]
    agent_asset_mapping: Dict[str, List[str]]
    workflow_dependencies: Dict[str, List[str]]
