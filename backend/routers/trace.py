from fastapi import APIRouter,HTTPException
from typing import Optional
from core.dependencies import get_data_store

router=APIRouter()


@router.get("/projects/{project_id}/traces")
async def get_project_traces(project_id:str,limit:int=100):
 data_store=get_data_store()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="Project not found")
 return data_store.get_traces_by_project(project_id,limit)


@router.get("/agents/{agent_id}/traces")
async def get_agent_traces(agent_id:str):
 data_store=get_data_store()
 agent=data_store.get_agent(agent_id)
 if not agent:
  raise HTTPException(status_code=404,detail="Agent not found")
 return data_store.get_traces_by_agent(agent_id)


@router.get("/traces/{trace_id}")
async def get_trace(trace_id:str):
 data_store=get_data_store()
 trace=data_store.get_trace(trace_id)
 if not trace:
  raise HTTPException(status_code=404,detail="Trace not found")
 return trace


@router.get("/agents/{agent_id}/sequence")
async def get_agent_sequence(agent_id:str):
 data_store=get_data_store()
 agent=data_store.get_agent(agent_id)
 if not agent:
  raise HTTPException(status_code=404,detail="Agent not found")
 return _build_sequence_data(data_store,agent_id,agent)


def _build_sequence_data(data_store,agent_id:str,agent:dict)->dict:
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
 for w in workers:
  w_display=w.get("metadata",{}).get("displayName",w["type"])
  participants.append({"id":w["id"],"label":w_display,"type":"worker"})
 events=[]
 for t in traces:
  model=t.get("modelUsed","")
  api_id=api_participant_map.get(model,api_participant_map.get("__default__","api:unknown"))
  if t.get("startedAt"):
   events.append({
    "timestamp":t["startedAt"],
    "from":agent_id,
    "to":api_id,
    "type":"request",
    "label":"プロンプト送信",
    "sourceId":t.get("id"),
    "sourceType":"trace"
   })
  if t.get("completedAt"):
   events.append({
    "timestamp":t["completedAt"],
    "from":api_id,
    "to":agent_id,
    "type":"response" if t.get("status")=="completed" else"error",
    "label":"LLM応答" if t.get("status")=="completed" else"エラー",
    "sourceId":t.get("id"),
    "sourceType":"trace"
   })
 events.sort(key=lambda x:x.get("timestamp",""))
 return {
  "participants":participants,
  "events":events,
  "summary":{
   "totalTraces":len(traces),
   "totalJobs":len(llm_jobs),
   "totalWorkers":len(workers)
  }
 }
