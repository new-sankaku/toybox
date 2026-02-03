import threading
from typing import Any,Dict,List,Optional,TYPE_CHECKING
from .base import Skill,SkillResult,SkillContext,SkillCategory,SkillParameter

if TYPE_CHECKING:
 from datastore import DataStore


class AgentMemorySkill(Skill):
 name="agent_memory"
 description="エージェント実行中のキー・バリューメモリを管理します（store/retrieve/search/list/delete）"
 category=SkillCategory.KNOWLEDGE
 parameters=[
  SkillParameter(name="operation",type="string",description="操作: store, retrieve, search, list, delete"),
  SkillParameter(name="key",type="string",description="メモリキー",required=False),
  SkillParameter(name="value",type="string",description="保存する値（store時）",required=False),
  SkillParameter(name="tags",type="array",description="タグ（store時の分類、search時のフィルタ）",required=False,default=[]),
 ]

 _storage:Dict[tuple,Dict[str,Dict[str,Any]]]={}
 _lock=threading.Lock()

 def __init__(self):
  super().__init__()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  operation=kwargs.get("operation","")
  key=kwargs.get("key","")
  value=kwargs.get("value","")
  tags=kwargs.get("tags",[])
  scope=(context.project_id,context.agent_id)
  if operation=="store":
   if not key:
    return SkillResult(success=False,error="key is required for store")
   with self._lock:
    if scope not in self._storage:
     self._storage[scope]={}
    self._storage[scope][key]={"value":value,"tags":tags}
   return SkillResult(success=True,output=f"Stored key: {key}",metadata={"key":key})
  elif operation=="retrieve":
   if not key:
    return SkillResult(success=False,error="key is required for retrieve")
   with self._lock:
    store=self._storage.get(scope,{})
    entry=store.get(key)
   if entry is None:
    return SkillResult(success=False,error=f"Key not found: {key}")
   return SkillResult(success=True,output=entry["value"],metadata={"key":key,"tags":entry["tags"]})
  elif operation=="search":
   with self._lock:
    store=self._storage.get(scope,{})
    if tags:
     tag_set=set(tags)
     results={k:v for k,v in store.items() if tag_set.intersection(set(v.get("tags",[])))}
    else:
     results=dict(store)
   return SkillResult(success=True,output={k:v["value"] for k,v in results.items()},metadata={"count":len(results)})
  elif operation=="list":
   with self._lock:
    store=self._storage.get(scope,{})
    keys=[{"key":k,"tags":v["tags"]} for k,v in store.items()]
   return SkillResult(success=True,output=keys,metadata={"count":len(keys)})
  elif operation=="delete":
   if not key:
    return SkillResult(success=False,error="key is required for delete")
   with self._lock:
    store=self._storage.get(scope,{})
    if key not in store:
     return SkillResult(success=False,error=f"Key not found: {key}")
    del store[key]
   return SkillResult(success=True,output=f"Deleted key: {key}",metadata={"key":key})
  else:
   return SkillResult(success=False,error=f"Unknown operation: {operation}. Use: store, retrieve, search, list, delete")


class AgentOutputQuerySkill(Skill):
 name="agent_output_query"
 description="他のエージェントの出力結果を参照します（read-only）"
 category=SkillCategory.KNOWLEDGE
 parameters=[
  SkillParameter(name="operation",type="string",description="操作: get_agent_output, list_agents, get_traces"),
  SkillParameter(name="agent_type",type="string",description="対象エージェントのタイプ",required=False),
  SkillParameter(name="agent_id",type="string",description="対象エージェントのID",required=False),
  SkillParameter(name="limit",type="integer",description="取得件数上限",required=False,default=10),
 ]

 def __init__(self,data_store:"DataStore"):
  super().__init__()
  self._data_store=data_store

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  operation=kwargs.get("operation","")
  agent_type=kwargs.get("agent_type","")
  agent_id=kwargs.get("agent_id","")
  limit=kwargs.get("limit",10)
  if operation=="list_agents":
   agents=self._data_store.get_agents_by_project(context.project_id)
   summary=[{"id":a["id"],"type":a["type"],"status":a["status"],"progress":a["progress"]} for a in agents]
   return SkillResult(success=True,output=summary,metadata={"count":len(summary)})
  elif operation=="get_agent_output":
   if not agent_type and not agent_id:
    return SkillResult(success=False,error="agent_type or agent_id is required")
   if agent_id:
    traces=self._data_store.get_traces_by_agent(agent_id)
   else:
    agents=self._data_store.get_agents_by_project(context.project_id)
    target=next((a for a in agents if a["type"]==agent_type),None)
    if not target:
     return SkillResult(success=False,error=f"Agent not found: {agent_type}")
    traces=self._data_store.get_traces_by_agent(target["id"])
   if not traces:
    return SkillResult(success=True,output=None,metadata={"message":"No traces found"})
   latest=traces[0]
   return SkillResult(success=True,output={
    "agentType":latest.get("agentType",""),
    "status":latest.get("status",""),
    "response":latest.get("llmResponse","")[:context.max_output_size],
    "summary":latest.get("outputSummary",""),
   },metadata={"traceId":latest.get("id","")})
  elif operation=="get_traces":
   if not agent_id:
    traces=self._data_store.get_traces_by_project(context.project_id,limit=limit)
   else:
    traces=self._data_store.get_traces_by_agent(agent_id)
   summaries=[{
    "id":t.get("id",""),
    "agentType":t.get("agentType",""),
    "status":t.get("status",""),
    "summary":t.get("outputSummary",""),
    "tokensInput":t.get("tokensInput",0),
    "tokensOutput":t.get("tokensOutput",0),
   } for t in traces[:limit]]
   return SkillResult(success=True,output=summaries,metadata={"count":len(summaries)})
  else:
   return SkillResult(success=False,error=f"Unknown operation: {operation}. Use: get_agent_output, list_agents, get_traces")
