from flask import Flask,request,jsonify
from datastore import DataStore
from config_loader import (
 get_output_settings_defaults,
 get_cost_settings_defaults,
 get_agent_service_map,
)


def register_project_settings_routes(app:Flask,data_store:DataStore):

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
  project=data_store.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  config=project.get("config",{})
  settings=config.get("outputSettings",get_output_settings_defaults())
  return jsonify(settings)

 @app.route('/api/projects/<project_id>/settings/output',methods=['PUT'])
 def update_project_output_settings(project_id:str):
  project=data_store.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  data=request.json or {}
  config=project.get("config",{})
  output_settings=config.get("outputSettings",get_output_settings_defaults())
  output_settings.update(data)
  data_store.update_project(project_id,{"outputSettings":output_settings})
  return jsonify(output_settings)

 @app.route('/api/projects/<project_id>/settings/cost',methods=['GET'])
 def get_project_cost_settings(project_id:str):
  project=data_store.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  settings=project.get("costSettings",get_cost_settings_defaults())
  return jsonify(settings)

 @app.route('/api/projects/<project_id>/settings/cost',methods=['PUT'])
 def update_project_cost_settings(project_id:str):
  project=data_store.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  data=request.json or {}
  if"costSettings" not in project:
   project["costSettings"]=get_cost_settings_defaults()
  project["costSettings"].update(data)
  data_store.update_project(project_id,{"costSettings":project["costSettings"]})
  return jsonify(project["costSettings"])

 @app.route('/api/projects/<project_id>/settings/ai-providers',methods=['GET'])
 def get_project_ai_providers(project_id:str):
  project=data_store.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  settings=project.get("aiProviderSettings",[])
  return jsonify(settings)

 @app.route('/api/projects/<project_id>/settings/ai-providers',methods=['PUT'])
 def update_project_ai_providers(project_id:str):
  project=data_store.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  data=request.json or []
  data_store.update_project(project_id,{"aiProviderSettings":data})
  return jsonify(data)
