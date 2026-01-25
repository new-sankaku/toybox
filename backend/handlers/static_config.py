from flask import Flask,jsonify
from config_loader import (
 get_models_config,
 get_project_options_config,
 get_file_extensions_config,
 get_agent_definitions_config,
 get_token_pricing,
 get_pricing_config,
 get_brushup_presets,
)


def register_static_config_routes(app:Flask):

 @app.route('/api/config/models',methods=['GET'])
 def get_models_config_api():
  return jsonify(get_models_config())

 @app.route('/api/config/models/pricing/<model_id>',methods=['GET'])
 def get_model_pricing_api(model_id:str):
  pricing = get_token_pricing(model_id)
  return jsonify({
   "modelId":model_id,
   "pricing":pricing,
  })

 @app.route('/api/config/project-options',methods=['GET'])
 def get_project_options_api():
  return jsonify(get_project_options_config())

 @app.route('/api/config/file-extensions',methods=['GET'])
 def get_file_extensions_api():
  return jsonify(get_file_extensions_config())

 @app.route('/api/config/agents',methods=['GET'])
 def get_agents_config_api():
  return jsonify(get_agent_definitions_config())

 @app.route('/api/config/pricing',methods=['GET'])
 def get_pricing_config_api():
  return jsonify(get_pricing_config())

 @app.route('/api/config/brushup-presets',methods=['GET'])
 def get_brushup_presets_api():
  return jsonify({"presets":get_brushup_presets()})
