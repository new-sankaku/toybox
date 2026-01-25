from flask import Flask,jsonify,request
from datastore import DataStore

def register_trace_routes(app:Flask,data_store:DataStore,sio):

 @app.route('/api/projects/<project_id>/traces',methods=['GET'])
 def list_project_traces(project_id:str):
  project=data_store.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  limit=request.args.get('limit',100,type=int)
  traces=data_store.get_traces_by_project(project_id,limit)
  return jsonify(traces)

 @app.route('/api/agents/<agent_id>/traces',methods=['GET'])
 def get_agent_traces(agent_id:str):
  agent=data_store.get_agent(agent_id)
  if not agent:
   return jsonify({"error":"Agent not found"}),404
  traces=data_store.get_traces_by_agent(agent_id)
  return jsonify(traces)

 @app.route('/api/traces/<trace_id>',methods=['GET'])
 def get_trace(trace_id:str):
  trace=data_store.get_trace(trace_id)
  if not trace:
   return jsonify({"error":"Trace not found"}),404
  return jsonify(trace)

 @app.route('/api/projects/<project_id>/traces',methods=['DELETE'])
 def delete_project_traces(project_id:str):
  project=data_store.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  count=data_store.delete_traces_by_project(project_id)
  return jsonify({"deleted":count})
