from flask import Flask,request,jsonify


def register_auto_approval_routes(app:Flask,project_service,workflow_service):

 @app.route('/api/projects/<project_id>/auto-approval-rules',methods=['GET'])
 def get_auto_approval_rules(project_id:str):
  project=project_service.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  rules=workflow_service.get_auto_approval_rules(project_id)
  return jsonify({"rules":rules})

 @app.route('/api/projects/<project_id>/auto-approval-rules',methods=['PUT'])
 def update_auto_approval_rules(project_id:str):
  project=project_service.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  data=request.json or {}
  rules=data.get("rules",[])
  updated_rules=workflow_service.set_auto_approval_rules(project_id,rules)
  return jsonify({"rules":updated_rules})
