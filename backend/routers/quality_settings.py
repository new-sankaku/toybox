from fastapi import APIRouter,HTTPException
from typing import Dict,Any,Optional
from pydantic import BaseModel
from core.dependencies import get_data_store
from agent_settings import (
 get_default_quality_settings,
 QualityCheckConfig,
 AGENT_PHASES,
 AGENT_DISPLAY_NAMES,
 HIGH_COST_AGENTS,
 AGENT_DEFINITIONS,
 UI_PHASES,
 AGENT_ASSET_MAPPING,
 WORKFLOW_DEPENDENCIES,
)

router=APIRouter()


class QualitySettingUpdate(BaseModel):
 enabled:Optional[bool]=None
 maxRetries:Optional[int]=None


class BulkQualityUpdate(BaseModel):
 settings:Dict[str,QualitySettingUpdate]


@router.get("/projects/{project_id}/settings/quality-check")
async def get_quality_settings(project_id:str):
 data_store=get_data_store()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="Project not found")
 settings=data_store.get_quality_settings(project_id)
 settings_dict={}
 for agent_type,config in settings.items():
  settings_dict[agent_type]=config.to_dict()
 return {
  "settings":settings_dict,
  "phases":AGENT_PHASES,
  "displayNames":AGENT_DISPLAY_NAMES,
 }


@router.patch("/projects/{project_id}/settings/quality-check/{agent_type}")
async def update_quality_setting(project_id:str,agent_type:str,data:QualitySettingUpdate):
 data_store=get_data_store()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="Project not found")
 current_settings=data_store.get_quality_settings(project_id)
 if agent_type not in current_settings:
  raise HTTPException(status_code=400,detail=f"Unknown agent type: {agent_type}")
 current_config=current_settings[agent_type]
 updated_config=QualityCheckConfig(
  enabled=data.enabled if data.enabled is not None else current_config.enabled,
  max_retries=data.maxRetries if data.maxRetries is not None else current_config.max_retries,
  is_high_cost=current_config.is_high_cost,
 )
 data_store.set_quality_setting(project_id,agent_type,updated_config)
 return {
  "agentType":agent_type,
  "config":updated_config.to_dict(),
 }


@router.patch("/projects/{project_id}/settings/quality-check/bulk")
async def bulk_update_quality_settings(project_id:str,data:BulkQualityUpdate):
 data_store=get_data_store()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="Project not found")
 if not data.settings:
  raise HTTPException(status_code=400,detail="No settings provided")
 current_settings=data_store.get_quality_settings(project_id)
 updated_results={}
 for agent_type,update_data in data.settings.items():
  if agent_type not in current_settings:
   continue
  current_config=current_settings[agent_type]
  updated_config=QualityCheckConfig(
   enabled=update_data.enabled if update_data.enabled is not None else current_config.enabled,
   max_retries=update_data.maxRetries if update_data.maxRetries is not None else current_config.max_retries,
   is_high_cost=current_config.is_high_cost,
  )
  data_store.set_quality_setting(project_id,agent_type,updated_config)
  updated_results[agent_type]=updated_config.to_dict()
 return {
  "updated":updated_results,
  "count":len(updated_results),
 }


@router.get("/settings/quality-check/defaults")
async def get_default_settings():
 default_settings=get_default_quality_settings()
 settings_dict={}
 for agent_type,config in default_settings.items():
  settings_dict[agent_type]=config.to_dict()
 return {
  "settings":settings_dict,
  "phases":AGENT_PHASES,
  "displayNames":AGENT_DISPLAY_NAMES,
  "highCostAgents":list(HIGH_COST_AGENTS),
 }


@router.post("/projects/{project_id}/settings/quality-check/reset")
async def reset_quality_settings(project_id:str):
 data_store=get_data_store()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="Project not found")
 default_settings=get_default_quality_settings()
 data_store.reset_quality_settings(project_id)
 settings_dict={}
 for agent_type,config in default_settings.items():
  settings_dict[agent_type]=config.to_dict()
 return {
  "message":"Settings reset to default",
  "settings":settings_dict,
 }


@router.get("/agent-definitions")
async def get_agent_definitions():
 return {
  "agents":AGENT_DEFINITIONS,
  "uiPhases":UI_PHASES,
  "agentAssetMapping":AGENT_ASSET_MAPPING,
  "workflowDependencies":WORKFLOW_DEPENDENCIES,
 }
