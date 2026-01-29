from typing import Dict, Any, List
from fastapi import APIRouter
from config_loader import (
    get_project_options_config,
    get_file_extensions_config,
    get_agent_definitions_config,
    get_pricing_config,
    get_ui_phases,
    get_agent_service_map,
    get_status_labels,
    get_agent_status_labels,
    get_approval_status_labels,
    get_asset_type_labels,
    get_resolution_labels,
    get_role_labels,
    get_agent_roles,
    get_agents_config,
    get_websocket_config,
)
from ai_config import get_service_labels
from schemas import UiSettingsResponse, CostSettingsDefaultsResponse, OutputSettingsDefaultsResponse

router = APIRouter()


@router.get("/config/project-options", response_model=Dict[str, Any])
async def get_project_options_api():
    return get_project_options_config()


@router.get("/config/file-extensions", response_model=Dict[str, Any])
async def get_file_extensions_api():
    return get_file_extensions_config()


@router.get("/config/agents", response_model=Dict[str, Any])
async def get_agents_config_api():
    return get_agent_definitions_config()


@router.get("/config/pricing", response_model=Dict[str, Any])
async def get_pricing_config_api():
    return get_pricing_config()


@router.get("/config/ui-settings", response_model=UiSettingsResponse)
async def get_ui_settings_api():
    agents_config = get_agents_config()
    agents = agents_config.get("agents", {})
    agents_out = {}
    for agent_id, agent in agents.items():
        agents_out[agent_id] = {
            "label": agent.get("label", ""),
            "short_label": agent.get("short_label", ""),
            "phase": agent.get("phase", 0),
            "role": agent.get("role", "worker"),
            "high_cost": agent.get("high_cost", False),
        }
    return {
        "ui_phases": get_ui_phases(),
        "agent_service_map": get_agent_service_map(),
        "service_labels": get_service_labels(),
        "status_labels": get_status_labels(),
        "agent_status_labels": get_agent_status_labels(),
        "approval_status_labels": get_approval_status_labels(),
        "asset_type_labels": get_asset_type_labels(),
        "resolution_labels": get_resolution_labels(),
        "role_labels": get_role_labels(),
        "agent_roles": get_agent_roles(),
        "agents": agents_out,
    }


@router.get("/config/websocket", response_model=Dict[str, Any])
async def get_websocket_config_api():
    return get_websocket_config()


@router.get("/config/agent-service-map", response_model=Dict[str, str])
async def get_agent_service_map_api():
    return get_agent_service_map()


@router.get("/config/cost-settings/defaults", response_model=CostSettingsDefaultsResponse)
async def get_cost_settings_defaults():
    return {
        "global_enabled": True,
        "global_monthly_limit": 100.0,
        "alert_threshold": 80,
        "stop_on_budget_exceeded": False,
        "services": {},
    }


@router.get("/config/output-settings/defaults", response_model=OutputSettingsDefaultsResponse)
async def get_output_settings_defaults():
    return {
        "default_dir": "outputs",
    }
