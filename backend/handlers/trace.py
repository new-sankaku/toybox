from datetime import datetime
from flask import Flask,jsonify,request
from datastore import DataStore
from middleware.logger import get_logger

def _build_sequence_data(data_store:DataStore,agent_id:str,agent:dict)->dict:
 traces=data_store.get_traces_by_agent(agent_id)
 llm_jobs=data_store.get_llm_jobs_by_agent(agent_id)
 workers=data_store.get_workers_by_parent(agent_id)
 agent_type=agent["type"]
 display_name=agent.get("metadata",{}).get("displayName",agent_type)
 participants=[{"id":"external","label":"入力","type":"external"}]
 participants.append({"id":agent_id,"label":display_name,"type":"leader" if workers else"agent"})
 api_models=set()
 for t in traces:
  if t.get("modelUsed"):
   api_models.add(t["modelUsed"])
 for j in llm_jobs:
  if j.get("model"):
   api_models.add(j["model"])
 api_participant_map={}
 for model in sorted(api_models):
  pid=f"api:{model}"
  short_label=model.split("/")[-1].split("(")[0].strip()
  api_participant_map[model]=pid
  participants.append({"id":pid,"label":short_label,"type":"api"})
 if not api_models:
  participants.append({"id":"api:unknown","label":"AI API","type":"api"})
  api_participant_map["__default__"]="api:unknown"
 worker_map={}
 for idx,w in enumerate(workers):
  w_display=w.get("metadata",{}).get("displayName",w["type"])
  w_id=w["id"]
  worker_map[w_id]=w_id
  participants.append({"id":w_id,"label":f"{w_display}","type":"worker"})
 def _trace_events(t,from_id,api_id):
  trace_id=t.get("id","")
  pair_id=f"pair-{trace_id}" if trace_id else None
  evs=[]
  if t.get("startedAt"):
   evs.append({
    "timestamp":t["startedAt"],
    "from":from_id,
    "to":api_id,
    "type":"request",
    "label":"プロンプト送信",
    "tokens":{"input":t.get("tokensInput",0)} if t.get("tokensInput") else None,
    "durationMs":None,
    "sourceId":trace_id,
    "sourceType":"trace",
    "pairId":pair_id
   })
  if t.get("completedAt") and t.get("status")=="completed":
   evs.append({
    "timestamp":t["completedAt"],
    "from":api_id,
    "to":from_id,
    "type":"response",
    "label":"LLM応答",
    "tokens":{"output":t.get("tokensOutput",0)} if t.get("tokensOutput") else None,
    "durationMs":t.get("durationMs"),
    "sourceId":trace_id,
    "sourceType":"trace",
    "pairId":pair_id
   })
  elif t.get("completedAt") and t.get("status")=="error":
   evs.append({
    "timestamp":t["completedAt"],
    "from":api_id,
    "to":from_id,
    "type":"error",
    "label":(t.get("errorMessage") or"エラー")[:40],
    "tokens":None,
    "durationMs":t.get("durationMs"),
    "sourceId":trace_id,
    "sourceType":"trace",
    "pairId":pair_id
   })
  return evs

 def _job_events(j,from_id,api_id):
  job_id=j.get("id","")
  pair_id=f"pair-{job_id}" if job_id else None
  evs=[]
  if j.get("createdAt"):
   evs.append({
    "timestamp":j["createdAt"],
    "from":from_id,
    "to":api_id,
    "type":"request",
    "label":"LLMジョブ送信",
    "tokens":{"input":j.get("tokensInput",0)} if j.get("tokensInput") else None,
    "durationMs":None,
    "sourceId":job_id,
    "sourceType":"job",
    "pairId":pair_id
   })
  if j.get("completedAt") and j.get("status")=="completed":
   evs.append({
    "timestamp":j["completedAt"],
    "from":api_id,
    "to":from_id,
    "type":"response",
    "label":"LLMジョブ応答",
    "tokens":{"output":j.get("tokensOutput",0)} if j.get("tokensOutput") else None,
    "durationMs":int((
     datetime.fromisoformat(j["completedAt"])-
     datetime.fromisoformat(j["createdAt"])
    ).total_seconds()*1000) if j.get("createdAt") and j.get("completedAt") else None,
    "sourceId":job_id,
    "sourceType":"job",
    "pairId":pair_id
   })
  elif j.get("completedAt") and j.get("status")=="failed":
   evs.append({
    "timestamp":j["completedAt"],
    "from":api_id,
    "to":from_id,
    "type":"error",
    "label":(j.get("errorMessage") or"失敗")[:40],
    "tokens":None,
    "durationMs":None,
    "sourceId":job_id,
    "sourceType":"job",
    "pairId":pair_id
   })
  return evs

 events=[]
 if agent.get("startedAt"):
  events.append({
   "timestamp":agent["startedAt"],
   "from":"external",
   "to":agent_id,
   "type":"input",
   "label":"入力コンテキスト受信",
   "tokens":None,
   "durationMs":None,
   "sourceId":None,
   "sourceType":None,
   "pairId":None
  })
 for t in sorted(traces,key=lambda x:x.get("startedAt") or""):
  model=t.get("modelUsed") or""
  api_id=api_participant_map.get(model,api_participant_map.get("__default__","api:unknown"))
  events.extend(_trace_events(t,agent_id,api_id))
 for j in sorted(llm_jobs,key=lambda x:x.get("createdAt") or""):
  model=j.get("model") or""
  api_id=api_participant_map.get(model,api_participant_map.get("__default__","api:unknown"))
  events.extend(_job_events(j,agent_id,api_id))
 for w in workers:
  w_id=w["id"]
  if w.get("startedAt"):
   events.append({
    "timestamp":w["startedAt"],
    "from":agent_id,
    "to":w_id,
    "type":"delegation",
    "label":"タスク委譲",
    "tokens":None,
    "durationMs":None,
    "sourceId":None,
    "sourceType":None,
    "pairId":None
   })
  w_traces=data_store.get_traces_by_agent(w_id)
  w_llm_jobs=data_store.get_llm_jobs_by_agent(w_id)
  for t in sorted(w_traces,key=lambda x:x.get("startedAt") or""):
   model=t.get("modelUsed") or""
   api_id=api_participant_map.get(model,api_participant_map.get("__default__","api:unknown"))
   events.extend(_trace_events(t,w_id,api_id))
  for j in sorted(w_llm_jobs,key=lambda x:x.get("createdAt") or""):
   model=j.get("model") or""
   api_id=api_participant_map.get(model,api_participant_map.get("__default__","api:unknown"))
   events.extend(_job_events(j,w_id,api_id))
  if w.get("completedAt"):
   events.append({
    "timestamp":w["completedAt"],
    "from":w_id,
    "to":agent_id,
    "type":"result",
    "label":"結果返却",
    "tokens":None,
    "durationMs":None,
    "sourceId":None,
    "sourceType":None,
    "pairId":None
   })
 if agent.get("completedAt"):
  events.append({
   "timestamp":agent["completedAt"],
   "from":agent_id,
   "to":"external",
   "type":"output",
   "label":"出力完了",
   "tokens":None,
   "durationMs":None,
   "sourceId":None,
   "sourceType":None,
   "pairId":None
  })
 events.sort(key=lambda x:x.get("timestamp") or"")
 messages=[]
 for idx,e in enumerate(events):
  messages.append({
   "id":f"msg-{idx+1}",
   "from":e["from"],
   "to":e["to"],
   "type":e["type"],
   "label":e["label"],
   "timestamp":e["timestamp"],
   "tokens":e["tokens"],
   "durationMs":e["durationMs"],
   "sourceId":e.get("sourceId"),
   "sourceType":e.get("sourceType"),
   "pairId":e.get("pairId")
  })
 total_input=sum(t.get("tokensInput",0) for t in traces)
 total_output=sum(t.get("tokensOutput",0) for t in traces)
 for w in workers:
  w_traces=data_store.get_traces_by_agent(w["id"])
  total_input+=sum(t.get("tokensInput",0) for t in w_traces)
  total_output+=sum(t.get("tokensOutput",0) for t in w_traces)
 total_duration=None
 if agent.get("startedAt") and agent.get("completedAt"):
  started=datetime.fromisoformat(agent["startedAt"])
  completed=datetime.fromisoformat(agent["completedAt"])
  total_duration=int((completed-started).total_seconds()*1000)
 return {
  "agentId":agent_id,
  "agentType":agent_type,
  "participants":participants,
  "messages":messages,
  "status":agent["status"],
  "totalDurationMs":total_duration,
  "totalTokens":{"input":total_input,"output":total_output}
 }

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

 @app.route('/api/llm-jobs/<job_id>',methods=['GET'])
 def get_llm_job(job_id:str):
  job=data_store.get_llm_job(job_id)
  if not job:
   return jsonify({"error":"LLM job not found"}),404
  return jsonify(job)

 @app.route('/api/agents/<agent_id>/sequence',methods=['GET'])
 def get_agent_sequence(agent_id:str):
  agent=data_store.get_agent(agent_id)
  if not agent:
   return jsonify({"error":"Agent not found"}),404
  try:
   sequence=_build_sequence_data(data_store,agent_id,agent)
   return jsonify(sequence)
  except Exception as e:
   get_logger().error(f"Error building sequence for agent {agent_id}: {e}",exc_info=True)
   return jsonify({"error":"Failed to build sequence data"}),500

 @app.route('/api/projects/<project_id>/traces',methods=['DELETE'])
 def delete_project_traces(project_id:str):
  project=data_store.get_project(project_id)
  if not project:
   return jsonify({"error":"Project not found"}),404
  count=data_store.delete_traces_by_project(project_id)
  return jsonify({"deleted":count})
