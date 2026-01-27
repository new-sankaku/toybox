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
  include_workers=request.args.get("includeWorkers","true").lower()=="true"
  agents=data_store.get_agents_by_project(project_id,include_workers=include_workers)
  return jsonify(agents)

 @app.route('/api/projects/<project_id>/agents/leaders',methods=['GET'])
 def list_project_leaders(project_id:str):
  project=data_store.get_project(project_id)
  if not project:
   raise NotFoundError("Project",project_id)
  agents=data_store.get_agents_by_project(project_id,include_workers=False)
  return jsonify(agents)

 @app.route('/api/agents/<agent_id>/workers',methods=['GET'])
 def list_agent_workers(agent_id:str):
  agent=data_store.get_agent(agent_id)
  if not agent:
   raise NotFoundError("Agent",agent_id)
  workers=data_store.get_workers_by_parent(agent_id)
  return jsonify(workers)

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
  cancelled=execution_service.cancel_agent(agent_id)
  if cancelled:
   return jsonify({"success":True,"message":"Agent cancelled"})
  else:
   return jsonify({"success":False,"message":"Agent not running or already completed"})

 @app.route('/api/agents/<agent_id>/retry',methods=['POST'])
 def retry_agent(agent_id:str):
  agent=data_store.get_agent(agent_id)
  if not agent:
   raise NotFoundError("Agent",agent_id)
  retryable_statuses={"failed","interrupted","cancelled"}
  if agent.get("status") not in retryable_statuses:
   raise ValidationError(f"Agent status must be one of {retryable_statuses} to retry","status")
  result=data_store.retry_agent(agent_id)
  if result:
   return jsonify({"success":True,"agent":result})
  else:
   raise ApiError("Failed to retry agent",code="RETRY_ERROR",status_code=500)

 @app.route('/api/agents/<agent_id>/pause',methods=['POST'])
 def pause_agent(agent_id:str):
  agent=data_store.get_agent(agent_id)
  if not agent:
   raise NotFoundError("Agent",agent_id)
  pausable_statuses={"running","waiting_approval"}
  if agent.get("status") not in pausable_statuses:
   raise ValidationError(f"Agent status must be one of {pausable_statuses} to pause","status")
  result=data_store.pause_agent(agent_id)
  if result:
   sio.emit('agent:paused',{
    "agentId":agent_id,
    "projectId":result["projectId"],
    "agent":result
   },room=f"project:{result['projectId']}")
   return jsonify({"success":True,"agent":result})
  else:
   raise ApiError("Failed to pause agent",code="PAUSE_ERROR",status_code=500)

 @app.route('/api/agents/<agent_id>/resume',methods=['POST'])
 def resume_agent(agent_id:str):
  agent=data_store.get_agent(agent_id)
  if not agent:
   raise NotFoundError("Agent",agent_id)
  resumable_statuses={"paused","waiting_response"}
  if agent.get("status") not in resumable_statuses:
   raise ValidationError(f"Agent status must be one of {resumable_statuses} to resume","status")
  result=data_store.resume_agent(agent_id)
  if result:
   sio.emit('agent:resumed',{
    "agentId":agent_id,
    "projectId":result["projectId"],
    "agent":result
   },room=f"project:{result['projectId']}")
   return jsonify({"success":True,"agent":result})
  else:
   raise ApiError("Failed to resume agent",code="RESUME_ERROR",status_code=500)

 @app.route('/api/projects/<project_id>/agents/retryable',methods=['GET'])
 def get_retryable_agents(project_id:str):
  project=data_store.get_project(project_id)
  if not project:
   raise NotFoundError("Project",project_id)
  agents=data_store.get_retryable_agents(project_id)
  return jsonify(agents)

 @app.route('/api/projects/<project_id>/agents/interrupted',methods=['GET'])
 def get_interrupted_agents(project_id:str):
  project=data_store.get_project(project_id)
  if not project:
   raise NotFoundError("Project",project_id)
  agents=data_store.get_interrupted_agents(project_id)
  return jsonify(agents)
