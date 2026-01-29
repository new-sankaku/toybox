from fastapi import APIRouter,HTTPException
from typing import List,Dict
from pydantic import BaseModel
from core.dependencies import get_data_store
from config_loader import get_agents_config

router=APIRouter()


@router.get("/brushup/presets")
async def get_brushup_presets():
 config=get_agents_config()
 presets=config.get("brushup_presets",[])
 return presets


@router.get("/brushup/agent-options")
async def get_agent_options():
 config=get_agents_config()
 options=config.get("brushup_agent_options",{})
 return options
