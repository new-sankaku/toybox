from flask import Flask,request,jsonify
from datastore import DataStore


def register_auto_approval_routes(app:Flask,data_store:DataStore):

 @app.route('/api/projects/<project_id>/auto-approval-rules',methods=['GET'])
 def get_auto_approval_rules(project_id:str):
  project = data_store.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  rules = data_store.get_auto_approval_rules(project_id)
  return jsonify({"rules":rules})

 @app.route('/api/projects/<project_id>/auto-approval-rules',methods=['PUT'])
 def update_auto_approval_rules(project_id:str):
  project = data_store.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  data = request.json or {}
  rules = data.get("rules",[])
  updated_rules = data_store.set_auto_approval_rules(project_id,rules)
  return jsonify({"rules":updated_rules})
