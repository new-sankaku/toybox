from flask import Flask,request,jsonify
from services.project_service import ProjectService
from config_loaders.project_option_config import (
 get_output_settings_defaults,
 get_cost_settings_defaults,
 get_websocket_config,
 get_concurrent_limits,
)
from config_loaders.agent_config import (
 get_agent_service_map,
 get_agents_config,
 get_ui_phases,
 get_advanced_quality_check_settings,
 get_tool_execution_limits,
 get_temperature_defaults,
)
from config_loaders.workflow_config import (
 get_dag_execution_settings,
 get_token_budget_settings,
 get_context_policy_settings,
)
from config_loaders.principle_config import (
 get_available_principles,
 get_default_agent_principles,
)
from config_loaders.ai_provider_config import get_usage_categories
from models.database import session_scope
from repositories.project_ai_config import ProjectAiConfigRepository
from repositories.global_execution_settings import GlobalExecutionSettingsRepository
from middleware.logger import get_logger


def register_project_settings_routes(app:Flask,project_service:ProjectService):

 @app.route('/api/config/output-settings/defaults',methods=['GET'])
 def get_output_defaults():
  return jsonify(get_output_settings_defaults())

 @app.route('/api/config/cost-settings/defaults',methods=['GET'])
 def get_cost_defaults():
  return jsonify(get_cost_settings_defaults())

 @app.route('/api/config/agent-service-map',methods=['GET'])
 def get_agent_service_map_endpoint():
  return jsonify(get_agent_service_map())

 @app.route('/api/projects/<project_id>/settings/output',methods=['GET'])
 def get_project_output_settings(project_id:str):
  project=project_service.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  config=project.get("config",{})
  settings=config.get("outputSettings",get_output_settings_defaults())
  return jsonify(settings)

 @app.route('/api/projects/<project_id>/settings/output',methods=['PUT'])
 def update_project_output_settings(project_id:str):
  project=project_service.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  data=request.json or {}
  config=project.get("config",{})
  output_settings=config.get("outputSettings",get_output_settings_defaults())
  output_settings.update(data)
  project_service.update_project(project_id,{"outputSettings":output_settings})
  return jsonify(output_settings)

 @app.route('/api/projects/<project_id>/settings/cost',methods=['GET'])
 def get_project_cost_settings(project_id:str):
  project=project_service.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  settings=project.get("costSettings",get_cost_settings_defaults())
  return jsonify(settings)

 @app.route('/api/projects/<project_id>/settings/cost',methods=['PUT'])
 def update_project_cost_settings(project_id:str):
  project=project_service.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  data=request.json or {}
  if"costSettings" not in project:
   project["costSettings"]=get_cost_settings_defaults()
  project["costSettings"].update(data)
  project_service.update_project(project_id,{"costSettings":project["costSettings"]})
  return jsonify(project["costSettings"])

 @app.route('/api/projects/<project_id>/settings/ai-providers',methods=['GET'])
 def get_project_ai_providers(project_id:str):
  project=project_service.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  settings=project.get("aiProviderSettings",[])
  return jsonify(settings)

 @app.route('/api/projects/<project_id>/settings/ai-providers',methods=['PUT'])
 def update_project_ai_providers(project_id:str):
  project=project_service.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  data=request.json or []
  project_service.update_project(project_id,{"aiProviderSettings":data})
  return jsonify(data)

 @app.route('/api/config/advanced-settings/defaults',methods=['GET'])
 def get_advanced_settings_defaults():
  return jsonify({
   "qualityCheck":get_advanced_quality_check_settings(),
   "toolExecution":get_tool_execution_limits(),
   "dagExecution":get_dag_execution_settings(),
   "temperatureDefaults":get_temperature_defaults(),
   "tokenBudget":get_token_budget_settings(),
   "contextPolicy":get_context_policy_settings()
  })

 @app.route('/api/config/concurrent-limits/defaults',methods=['GET'])
 def get_concurrent_limits_defaults():
  return jsonify(get_concurrent_limits())

 @app.route('/api/config/websocket/defaults',methods=['GET'])
 def get_websocket_defaults():
  return jsonify(get_websocket_config())

 @app.route('/api/projects/<project_id>/settings/advanced',methods=['GET'])
 def get_project_advanced_settings(project_id:str):
  project=project_service.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  defaults={
   "qualityCheck":get_advanced_quality_check_settings(),
   "toolExecution":get_tool_execution_limits(),
   "dagExecution":get_dag_execution_settings(),
   "temperatureDefaults":get_temperature_defaults(),
   "tokenBudget":get_token_budget_settings(),
   "contextPolicy":get_context_policy_settings()
  }
  settings=project.get("advancedSettings",defaults)
  for k,v in defaults.items():
   if k not in settings:
    settings[k]=v
  return jsonify(settings)

 @app.route('/api/projects/<project_id>/settings/advanced',methods=['PUT'])
 def update_project_advanced_settings(project_id:str):
  project=project_service.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  data=request.json or {}
  current=project.get("advancedSettings",{})
  current.update(data)
  project_service.update_project(project_id,{"advancedSettings":current})
  return jsonify(current)

 @app.route('/api/config/concurrent-limits',methods=['GET'])
 def get_global_concurrent_limits():
  try:
   with session_scope() as session:
    repo=GlobalExecutionSettingsRepository(session)
    return jsonify(repo.get_concurrent_limits())
  except Exception as e:
   get_logger().error(f"Failed to get concurrent limits: {e}",exc_info=True)
   return jsonify(get_concurrent_limits())

 @app.route('/api/config/concurrent-limits',methods=['PUT'])
 def update_global_concurrent_limits():
  try:
   data=request.json or {}
   with session_scope() as session:
    repo=GlobalExecutionSettingsRepository(session)
    repo.update_concurrent_limits(data)
    session.commit()
    return jsonify(repo.get_concurrent_limits())
  except Exception as e:
   get_logger().error(f"Failed to update concurrent limits: {e}",exc_info=True)
   return jsonify({"error":str(e)}),500

 @app.route('/api/config/websocket',methods=['GET'])
 def get_global_websocket_settings():
  try:
   with session_scope() as session:
    repo=GlobalExecutionSettingsRepository(session)
    return jsonify(repo.get_websocket_settings())
  except Exception as e:
   get_logger().error(f"Failed to get websocket settings: {e}",exc_info=True)
   return jsonify(get_websocket_config())

 @app.route('/api/config/websocket',methods=['PUT'])
 def update_global_websocket_settings():
  try:
   data=request.json or {}
   with session_scope() as session:
    repo=GlobalExecutionSettingsRepository(session)
    repo.update_websocket_settings(data)
    session.commit()
    return jsonify(repo.get_websocket_settings())
  except Exception as e:
   get_logger().error(f"Failed to update websocket settings: {e}",exc_info=True)
   return jsonify({"error":str(e)}),500

 @app.route('/api/projects/<project_id>/settings/usage-categories',methods=['GET'])
 def get_project_usage_categories(project_id:str):
  project=project_service.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  try:
   defaults=get_usage_categories()
   with session_scope() as session:
    repo=ProjectAiConfigRepository(session)
    configs=repo.get_by_project(project_id)
    result=[]
    config_map={c.usage_category:c for c in configs}
    for cat in defaults:
     cat_id=cat.get("id","")
     if cat_id in config_map:
      c=config_map[cat_id]
      result.append({
       "id":cat_id,
       "label":cat.get("label",""),
       "service_type":cat.get("service_type",""),
       "provider":c.provider_id,
       "model":c.model_id
      })
     else:
      default=cat.get("default",{})
      result.append({
       "id":cat_id,
       "label":cat.get("label",""),
       "service_type":cat.get("service_type",""),
       "provider":default.get("provider",""),
       "model":default.get("model","")
      })
    return jsonify(result)
  except Exception as e:
   get_logger().error(f"Failed to get usage categories: {e}",exc_info=True)
   return jsonify({"error":str(e)}),500

 @app.route('/api/projects/<project_id>/settings/usage-categories/<category_id>',methods=['PUT'])
 def update_project_usage_category(project_id:str,category_id:str):
  project=project_service.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  data=request.json or {}
  provider=data.get("provider","")
  model=data.get("model","")
  if not provider or not model:
   return jsonify({"error":"provider and model are required"}),400
  try:
   with session_scope() as session:
    repo=ProjectAiConfigRepository(session)
    config=repo.save(project_id,category_id,provider,model)
    return jsonify({
     "id":config.usage_category,
     "provider":config.provider_id,
     "model":config.model_id
    })
  except Exception as e:
   get_logger().error(f"Failed to update usage category: {e}",exc_info=True)
   return jsonify({"error":str(e)}),500

 @app.route('/api/projects/<project_id>/settings/usage-categories/<category_id>',methods=['DELETE'])
 def reset_project_usage_category(project_id:str,category_id:str):
  project=project_service.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  try:
   with session_scope() as session:
    repo=ProjectAiConfigRepository(session)
    repo.delete(project_id,category_id)
    defaults=get_usage_categories()
    for cat in defaults:
     if cat.get("id")==category_id:
      default=cat.get("default",{})
      return jsonify({
       "id":category_id,
       "provider":default.get("provider",""),
       "model":default.get("model","")
      })
    return jsonify({"id":category_id,"provider":"","model":""})
  except Exception as e:
   get_logger().error(f"Failed to reset usage category: {e}",exc_info=True)
   return jsonify({"error":str(e)}),500

 @app.route('/api/config/principles',methods=['GET'])
 def get_principles_list():
  try:
   principles=get_available_principles()
   defaults=get_default_agent_principles()
   config=get_agents_config()
   agents_raw=config.get("agents",{})
   agents_meta={}
   for agent_id,agent in agents_raw.items():
    agents_meta[agent_id]={
     "label":agent.get("label",agent_id),
     "shortLabel":agent.get("short_label",""),
     "phase":agent.get("phase",0),
    }
   ui_phases=get_ui_phases()
   return jsonify({"principles":principles,"defaults":defaults,"agents":agents_meta,"uiPhases":ui_phases})
  except Exception as e:
   get_logger().error(f"Failed to get principles: {e}",exc_info=True)
   return jsonify({"error":str(e)}),500

 @app.route('/api/projects/<project_id>/settings/principles',methods=['GET'])
 def get_project_principles(project_id:str):
  project=project_service.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  defaults=get_default_agent_principles()
  advanced=project.get("advancedSettings",{})
  overrides=advanced.get("principleOverrides",{})
  enabled=advanced.get("enabledPrinciples")
  return jsonify({"defaults":defaults,"overrides":overrides,"enabledPrinciples":enabled})

 @app.route('/api/projects/<project_id>/settings/principles',methods=['PUT'])
 def update_project_principles(project_id:str):
  project=project_service.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  data=request.json or {}
  advanced=project.get("advancedSettings",{})
  if"overrides" in data:
   advanced["principleOverrides"]=data["overrides"]
  if"enabledPrinciples" in data:
   advanced["enabledPrinciples"]=data["enabledPrinciples"]
  project_service.update_project(project_id,{"advancedSettings":advanced})
  return jsonify({"overrides":advanced.get("principleOverrides",{}),"enabledPrinciples":advanced.get("enabledPrinciples")})
