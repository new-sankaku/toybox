from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.dependencies import get_data_store
from config_loader import get_agents_config
from schemas import BrushupOptionsResponse

router = APIRouter()


@router.get("/brushup/options", response_model=BrushupOptionsResponse)
async def get_brushup_options():
    config = get_agents_config()
    return {
        "presets": config.get("brushup_presets", []),
        "agent_options": config.get("brushup_agent_options", {}),
    }


@router.get("/brushup/presets", response_model=List[Dict[str, Any]])
async def get_brushup_presets():
    config = get_agents_config()
    presets = config.get("brushup_presets", [])
    return presets


@router.get("/brushup/agent-options", response_model=Dict[str, List[Dict[str, Any]]])
async def get_agent_options():
    config = get_agents_config()
    options = config.get("brushup_agent_options", {})
    return options
