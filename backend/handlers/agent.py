import asyncio
from flask import Flask,jsonify,request
from datastore import DataStore
from middleware.error_handler import NotFoundError,ValidationError,ApiError
from middleware.rate_limiter import rate_limit


def register_agent_routes(app:Flask,data_store:DataStore,sio):
 _execution_service=None

 def _get_execution_service():
  nonlocal _execution_service
  if _execution_service is None:
   if hasattr(app,"agent_execution_service"):
    _execution_service=app.agent_execution_service
  return _execution_service

 @app.route('/api/projects/<project_id>/agents',methods=['GET'])
 def list_project_agents(project_id:str):
  project=data_store.get_project(project_id)
  if not project:
   raise NotFoundError("Project",project_id)
  agents=data_store.get_agents_by_project(project_id)
  return jsonify(agents)

 @app.route('/api/agents/<agent_id>/logs',methods=['GET'])
 def get_agent_logs(agent_id:str):
  agent=data_store.get_agent(agent_id)
  if not agent:
   raise NotFoundError("Agent",agent_id)
  logs=data_store.get_agent_logs(agent_id)
  return jsonify(logs)

 @app.route('/api/agents/<agent_id>/execute',methods=['POST'])
 @rate_limit(limit=10,window=60)
 def execute_agent(agent_id:str):
  execution_service=_get_execution_service()
  if not execution_service:
   raise ApiError("Agent execution service not available",code="SERVICE_UNAVAILABLE",status_code=503)
  agent=data_store.get_agent(agent_id)
  if not agent:
   raise NotFoundError("Agent",agent_id)
  project_id=agent.get("projectId")
  if not project_id:
   raise ValidationError("Agent has no project","projectId")
  try:
   loop=asyncio.new_event_loop()
   asyncio.set_event_loop(loop)
   result=loop.run_until_complete(execution_service.execute_agent(project_id,agent_id))
   loop.close()
  except Exception as e:
   raise ApiError(f"Execution failed: {str(e)}",code="EXECUTION_ERROR",status_code=500)
  if result.get("success"):
   return jsonify({"success":True,"output":result.get("output")})
  else:
   raise ApiError(result.get("error","Unknown error"),code="EXECUTION_FAILED",status_code=400)

 @app.route('/api/agents/<agent_id>/execute-with-workers',methods=['POST'])
 @rate_limit(limit=5,window=60)
 def execute_leader_with_workers(agent_id:str):
  execution_service=_get_execution_service()
  if not execution_service:
   raise ApiError("Agent execution service not available",code="SERVICE_UNAVAILABLE",status_code=503)
  agent=data_store.get_agent(agent_id)
  if not agent:
   raise NotFoundError("Agent",agent_id)
  project_id=agent.get("projectId")
  if not project_id:
   raise ValidationError("Agent has no project","projectId")
  agent_type=agent.get("type","")
  if not agent_type.endswith("_leader"):
   raise ValidationError("Agent must be a leader type","type")
  try:
   loop=asyncio.new_event_loop()
   asyncio.set_event_loop(loop)
   result=loop.run_until_complete(execution_service.execute_leader_with_workers(project_id,agent_id))
   loop.close()
  except Exception as e:
   raise ApiError(f"Execution failed: {str(e)}",code="EXECUTION_ERROR",status_code=500)
  if result.get("success"):
   return jsonify({"success":True,"results":result.get("results")})
  else:
   raise ApiError(result.get("error","Unknown error"),code="EXECUTION_FAILED",status_code=400)

 @app.route('/api/agents/<agent_id>/cancel',methods=['POST'])
 def cancel_agent(agent_id:str):
  execution_service=_get_execution_service()
  if not execution_service:
   raise ApiError("Agent execution service not available",code="SERVICE_UNAVAILABLE",status_code=503)
  agent=data_store.get_agent(agent_id)
  if not agent:
   raise NotFoundError("Agent",agent_id)
  try:
   loop=asyncio.new_event_loop()
   asyncio.set_event_loop(loop)
   cancelled=loop.run_until_complete(execution_service.cancel_agent(agent_id))
   loop.close()
  except Exception as e:
   raise ApiError(f"Cancel failed: {str(e)}",code="CANCEL_ERROR",status_code=500)
  if cancelled:
   data_store.update_agent(agent_id,{"status":"cancelled","currentTask":None})
   return jsonify({"success":True,"message":"Agent cancelled"})
  else:
   return jsonify({"success":False,"message":"Agent not running or already completed"})
