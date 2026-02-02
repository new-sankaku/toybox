from flask import Flask,request,jsonify
from datastore import DataStore
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


def register_quality_settings_routes(app:Flask,data_store:DataStore):

 @app.route('/api/projects/<project_id>/settings/quality-check',methods=['GET'])
 def get_quality_settings(project_id:str):
  project=data_store.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  settings=data_store.get_quality_settings(project_id)
  settings_dict={}
  for agent_type,config in settings.items():
   settings_dict[agent_type]=config.to_dict()
  return jsonify({
   "settings":settings_dict,
   "phases":AGENT_PHASES,
   "displayNames":AGENT_DISPLAY_NAMES,
  })

 @app.route('/api/projects/<project_id>/settings/quality-check/<agent_type>',methods=['PATCH'])
 def update_quality_setting(project_id:str,agent_type:str):
  project=data_store.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  data=request.json or {}
  current_settings=data_store.get_quality_settings(project_id)
  if agent_type not in current_settings:
   return jsonify({"error":f"Unknown agent type: {agent_type}"}),400
  current_config=current_settings[agent_type]
  updated_config=QualityCheckConfig(
   enabled=data.get("enabled",current_config.enabled),
   max_retries=data.get("maxRetries",current_config.max_retries),
   is_high_cost=current_config.is_high_cost,
  )
  data_store.set_quality_setting(project_id,agent_type,updated_config)
  return jsonify({
   "agentType":agent_type,
   "config":updated_config.to_dict(),
  })

 @app.route('/api/projects/<project_id>/settings/quality-check/bulk',methods=['PATCH'])
 def bulk_update_quality_settings(project_id:str):
  project=data_store.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  data=request.json or {}
  settings_updates=data.get("settings",{})
  if not settings_updates:
   return jsonify({"error":"No settings provided"}),400
  current_settings=data_store.get_quality_settings(project_id)
  updated_results={}
  for agent_type,update_data in settings_updates.items():
   if agent_type not in current_settings:
    continue
   current_config=current_settings[agent_type]
   updated_config=QualityCheckConfig(
    enabled=update_data.get("enabled",current_config.enabled),
    max_retries=update_data.get("maxRetries",current_config.max_retries),
    is_high_cost=current_config.is_high_cost,
   )
   data_store.set_quality_setting(project_id,agent_type,updated_config)
   updated_results[agent_type]=updated_config.to_dict()
  return jsonify({
   "updated":updated_results,
   "count":len(updated_results),
  })

 @app.route('/api/settings/quality-check/defaults',methods=['GET'])
 def get_default_settings():
  default_settings=get_default_quality_settings()
  settings_dict={}
  for agent_type,config in default_settings.items():
   settings_dict[agent_type]=config.to_dict()
  return jsonify({
   "settings":settings_dict,
   "phases":AGENT_PHASES,
   "displayNames":AGENT_DISPLAY_NAMES,
   "highCostAgents":list(HIGH_COST_AGENTS),
  })

 @app.route('/api/projects/<project_id>/settings/quality-check/reset',methods=['POST'])
 def reset_quality_settings(project_id:str):
  project=data_store.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  default_settings=get_default_quality_settings()
  data_store.reset_quality_settings(project_id)
  settings_dict={}
  for agent_type,config in default_settings.items():
   settings_dict[agent_type]=config.to_dict()
  return jsonify({
   "message":"Settings reset to default",
   "settings":settings_dict,
  })

 @app.route('/api/agent-definitions',methods=['GET'])
 def get_agent_definitions():
  return jsonify({
   "agents":AGENT_DEFINITIONS,
   "uiPhases":UI_PHASES,
   "agentAssetMapping":AGENT_ASSET_MAPPING,
   "workflowDependencies":WORKFLOW_DEPENDENCIES,
  })
