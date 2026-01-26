from flask import Flask,jsonify
from datastore import DataStore


def register_recovery_routes(app:Flask,data_store:DataStore):
 @app.route('/api/recovery/status',methods=['GET'])
 def get_recovery_status():
  """
  システム全体の中断されたAgent/Projectの状態を取得
  """
  interrupted_agents=data_store.get_interrupted_agents()
  return jsonify({
   "interruptedAgents":interrupted_agents,
   "count":len(interrupted_agents)
  })

 @app.route('/api/recovery/retry-all',methods=['POST'])
 def retry_all_interrupted():
  """
  全ての中断されたAgentをpending状態にリセット
  """
  interrupted_agents=data_store.get_interrupted_agents()
  retried=[]
  for agent in interrupted_agents:
   result=data_store.retry_agent(agent["id"])
   if result:
    retried.append(result)
  return jsonify({
   "success":True,
   "retriedCount":len(retried),
   "retriedAgents":retried
  })
