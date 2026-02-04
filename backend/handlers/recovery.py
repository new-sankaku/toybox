from flask import Flask,jsonify
from services.agent_service import AgentService


def register_recovery_routes(app:Flask,agent_service:AgentService):
 @app.route('/api/recovery/status',methods=['GET'])
 def get_recovery_status():
  """
  システム全体の中断されたAgent/Projectの状態を取得
  """
  interrupted_agents=agent_service.get_interrupted_agents()
  return jsonify({
   "interruptedAgents":interrupted_agents,
   "count":len(interrupted_agents)
  })

 @app.route('/api/recovery/retry-all',methods=['POST'])
 def retry_all_interrupted():
  """
  全ての中断されたAgentをpending状態にリセット
  """
  interrupted_agents=agent_service.get_interrupted_agents()
  retried=[]
  for agent in interrupted_agents:
   result=agent_service.retry_agent(agent["id"])
   if result:
    retried.append(result)
  return jsonify({
   "success":True,
   "retriedCount":len(retried),
   "retriedAgents":retried
  })
