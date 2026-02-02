from datetime import datetime
from flask import Flask,jsonify,request
from datastore import DataStore
from middleware.logger import get_logger

def _extract_service_name(model:str)->str:
 provider_map={
  "anthropic":"Claude",
  "openai":"OpenAI",
  "google":"Gemini",
  "local-comfyui":"ComfyUI",
  "local":"Local",
  "azure":"Azure",
  "aws":"AWS",
  "cohere":"Cohere",
  "mistral":"Mistral"
 }
 if not model:
  return"API"
 provider=model.split("/")[0].lower() if"/"in model else""
 return provider_map.get(provider,"API")

def _extract_model_display_name(model:str)->str:
 if not model:
  return"Unknown"
 model_map={
  "anthropic/claude-opus-4":"Claude Opus",
  "anthropic/claude-sonnet-4":"Claude Sonnet",
  "anthropic/claude-3-5-sonnet-20241022":"Claude Sonnet 3.5",
  "anthropic/claude-3-opus-20240229":"Claude Opus 3",
  "openai/gpt-4o":"GPT-4o",
  "openai/gpt-4-turbo":"GPT-4 Turbo",
  "google/gemini-1.5-pro":"Gemini 1.5 Pro",
  "google/gemini-2.0-flash":"Gemini 2.0 Flash",
 }
 if model in model_map:
  return model_map[model]
 parts=model.split("/")
 if len(parts)>1:
  return parts[1]
 return model

def _calculate_cost(tokens_input:int,tokens_output:int,model:str)->float:
 pricing={
  "anthropic/claude-opus-4":{"input":15.0,"output":75.0},
  "anthropic/claude-sonnet-4":{"input":3.0,"output":15.0},
  "anthropic/claude-3-5-sonnet-20241022":{"input":3.0,"output":15.0},
  "anthropic/claude-3-opus-20240229":{"input":15.0,"output":75.0},
  "openai/gpt-4o":{"input":2.5,"output":10.0},
  "openai/gpt-4-turbo":{"input":10.0,"output":30.0},
  "google/gemini-1.5-pro":{"input":1.25,"output":5.0},
  "google/gemini-2.0-flash":{"input":0.1,"output":0.4},
 }
 rates=pricing.get(model,{"input":3.0,"output":15.0})
 cost=(tokens_input*rates["input"]+tokens_output*rates["output"])/1_000_000
 return round(cost,4)

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
  service_label=_extract_service_name(model)
  api_participant_map[model]=pid
  participants.append({"id":pid,"label":service_label,"type":"api"})
 if not api_models:
  participants.append({"id":"api:unknown","label":"AI API","type":"api"})
  api_participant_map["__default__"]="api:unknown"
 worker_map={}
 for idx,w in enumerate(workers):
  w_display=w.get("metadata",{}).get("displayName",w["type"])
  w_id=w["id"]
  worker_map[w_id]=w_id
  participants.append({"id":w_id,"label":f"{w_display}","type":"worker"})
 def _trace_events(t,from_id,api_id,call_idx):
  trace_id=t.get("id","")
  pair_id=f"pair-{trace_id}" if trace_id else None
  summary=t.get("outputSummary") or""
  model=t.get("modelUsed") or""
  model_display=_extract_model_display_name(model)
  tokens_in=t.get("tokensInput",0)
  tokens_out=t.get("tokensOutput",0)
  cost=_calculate_cost(tokens_in,tokens_out,model)
  evs=[]
  if t.get("startedAt"):
   evs.append({
    "timestamp":t["startedAt"],
    "from":from_id,
    "to":api_id,
    "type":"request",
    "label":"",
    "tokens":{"input":tokens_in} if tokens_in else None,
    "durationMs":None,
    "sourceId":trace_id,
    "sourceType":"trace",
    "pairId":pair_id,
    "model":model_display,
    "cost":None,
    "callIndex":call_idx
   })
  if t.get("completedAt") and t.get("status")=="completed":
   resp_label=summary[:80] if summary else""
   evs.append({
    "timestamp":t["completedAt"],
    "from":api_id,
    "to":from_id,
    "type":"response",
    "label":resp_label,
    "tokens":{"output":tokens_out} if tokens_out else None,
    "durationMs":t.get("durationMs"),
    "sourceId":trace_id,
    "sourceType":"trace",
    "pairId":pair_id,
    "model":model_display,
    "cost":cost if tokens_out>0 else None,
    "callIndex":call_idx
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
    "pairId":pair_id,
    "model":model_display,
    "cost":None,
    "callIndex":call_idx
   })
  return evs

 def _job_events(j,from_id,api_id,call_idx):
  job_id=j.get("id","")
  pair_id=f"pair-{job_id}" if job_id else None
  resp_content=j.get("responseContent") or""
  model=j.get("model") or""
  model_display=_extract_model_display_name(model)
  tokens_in=j.get("tokensInput",0)
  tokens_out=j.get("tokensOutput",0)
  cost=_calculate_cost(tokens_in,tokens_out,model)
  evs=[]
  if j.get("createdAt"):
   evs.append({
    "timestamp":j["createdAt"],
    "from":from_id,
    "to":api_id,
    "type":"request",
    "label":"",
    "tokens":{"input":tokens_in} if tokens_in else None,
    "durationMs":None,
    "sourceId":job_id,
    "sourceType":"job",
    "pairId":pair_id,
    "model":model_display,
    "cost":None,
    "callIndex":call_idx
   })
  if j.get("completedAt") and j.get("status")=="completed":
   resp_label=resp_content[:80] if resp_content else""
   evs.append({
    "timestamp":j["completedAt"],
    "from":api_id,
    "to":from_id,
    "type":"response",
    "label":resp_label,
    "tokens":{"output":tokens_out} if tokens_out else None,
    "durationMs":int((
     datetime.fromisoformat(j["completedAt"])-
     datetime.fromisoformat(j["createdAt"])
    ).total_seconds()*1000) if j.get("createdAt") and j.get("completedAt") else None,
    "sourceId":job_id,
    "sourceType":"job",
    "pairId":pair_id,
    "model":model_display,
    "cost":cost if tokens_out>0 else None,
    "callIndex":call_idx
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
    "pairId":pair_id,
    "model":model_display,
    "cost":None,
    "callIndex":call_idx
   })
  return evs

 events=[]
 call_counter={"idx":0}
 def next_call_idx():
  call_counter["idx"]+=1
  return call_counter["idx"]
 if agent.get("startedAt"):
  events.append({
   "timestamp":agent["startedAt"],
   "from":"external",
   "to":agent_id,
   "type":"input",
   "label":"入力コンテキスト受信",
   "tokens":None,
   "durationMs":None,
   "sourceId":agent_id,
   "sourceType":"agent",
   "pairId":None,
   "model":None,
   "cost":None,
   "callIndex":None
  })
 for t in sorted(traces,key=lambda x:x.get("startedAt") or""):
  model=t.get("modelUsed") or""
  api_id=api_participant_map.get(model,api_participant_map.get("__default__","api:unknown"))
  events.extend(_trace_events(t,agent_id,api_id,next_call_idx()))
 for j in sorted(llm_jobs,key=lambda x:x.get("createdAt") or""):
  model=j.get("model") or""
  api_id=api_participant_map.get(model,api_participant_map.get("__default__","api:unknown"))
  events.extend(_job_events(j,agent_id,api_id,next_call_idx()))
 for w in workers:
  w_id=w["id"]
  w_task_name=w.get("metadata",{}).get("task","")
  w_pair_id=f"worker-{w_id}"
  if w.get("startedAt"):
   events.append({
    "timestamp":w["startedAt"],
    "from":agent_id,
    "to":w_id,
    "type":"delegation",
    "label":w_task_name,
    "tokens":None,
    "durationMs":None,
    "sourceId":None,
    "sourceType":None,
    "pairId":w_pair_id,
    "model":None,
    "cost":None,
    "callIndex":None
   })
  w_traces=data_store.get_traces_by_agent(w_id)
  w_llm_jobs=data_store.get_llm_jobs_by_agent(w_id)
  for t in sorted(w_traces,key=lambda x:x.get("startedAt") or""):
   model=t.get("modelUsed") or""
   api_id=api_participant_map.get(model,api_participant_map.get("__default__","api:unknown"))
   events.extend(_trace_events(t,w_id,api_id,next_call_idx()))
  for j in sorted(w_llm_jobs,key=lambda x:x.get("createdAt") or""):
   model=j.get("model") or""
   api_id=api_participant_map.get(model,api_participant_map.get("__default__","api:unknown"))
   events.extend(_job_events(j,w_id,api_id,next_call_idx()))
  if w.get("completedAt"):
   events.append({
    "timestamp":w["completedAt"],
    "from":w_id,
    "to":agent_id,
    "type":"result",
    "label":w_task_name,
    "tokens":None,
    "durationMs":None,
    "sourceId":None,
    "sourceType":None,
    "pairId":w_pair_id,
    "model":None,
    "cost":None,
    "callIndex":None
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
   "sourceId":agent_id,
   "sourceType":"agent",
   "pairId":None,
   "model":None,
   "cost":None,
   "callIndex":None
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
   "pairId":e.get("pairId"),
   "model":e.get("model"),
   "cost":e.get("cost"),
   "callIndex":e.get("callIndex")
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
