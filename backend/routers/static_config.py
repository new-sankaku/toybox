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

router = APIRouter()


@router.get("/config/project-options")
async def get_project_options_api():
    return get_project_options_config()


@router.get("/config/file-extensions")
async def get_file_extensions_api():
    return get_file_extensions_config()


@router.get("/config/agents")
async def get_agents_config_api():
    return get_agent_definitions_config()


@router.get("/config/pricing")
async def get_pricing_config_api():
    return get_pricing_config()


@router.get("/config/ui-settings")
async def get_ui_settings_api():
    agents_config = get_agents_config()
    agents = agents_config.get("agents", {})
    agents_out = {}
    for agent_id, agent in agents.items():
        agents_out[agent_id] = {
            "label": agent.get("label", ""),
            "shortLabel": agent.get("short_label", ""),
            "phase": agent.get("phase", 0),
            "role": agent.get("role", "worker"),
            "highCost": agent.get("high_cost", False),
        }
    return {
        "uiPhases": get_ui_phases(),
        "agentServiceMap": get_agent_service_map(),
        "serviceLabels": get_service_labels(),
        "statusLabels": get_status_labels(),
        "agentStatusLabels": get_agent_status_labels(),
        "approvalStatusLabels": get_approval_status_labels(),
        "assetTypeLabels": get_asset_type_labels(),
        "resolutionLabels": get_resolution_labels(),
        "roleLabels": get_role_labels(),
        "agentRoles": get_agent_roles(),
        "agents": agents_out,
    }


@router.get("/config/websocket")
async def get_websocket_config_api():
    return get_websocket_config()
