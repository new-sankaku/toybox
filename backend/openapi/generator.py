from typing import Dict,Any,Type,get_type_hints,get_origin,get_args
from datetime import datetime
from pydantic import BaseModel
from schemas import (
 ProjectSchema,ProjectCreateSchema,ProjectUpdateSchema,
 AgentSchema,AgentCreateSchema,AgentUpdateSchema,
 CheckpointSchema,CheckpointCreateSchema,CheckpointResolveSchema,
 ApiErrorSchema,
 PromptComponentSchema,AgentSystemPromptSchema,
 GlobalCostSettingsSchema,GlobalCostSettingsUpdateSchema,
 BudgetStatusSchema,CostHistoryItemSchema,CostHistoryResponseSchema,
 CostSummarySchema,
)

def pydantic_to_openapi_schema(model:Type[BaseModel])->Dict[str,Any]:
 schema={"type":"object","properties":{},"required":[]}
 hints=get_type_hints(model)
 fields=model.model_fields
 for field_name,field_info in fields.items():
  alias=field_info.alias or field_name
  field_type=hints.get(field_name,str)
  prop=_type_to_schema(field_type)
  schema["properties"][alias]=prop
  if field_info.is_required():
   schema["required"].append(alias)
 if not schema["required"]:
  del schema["required"]
 return schema

def _type_to_schema(t)->Dict[str,Any]:
 origin=get_origin(t)
 if origin is None:
  if t is str:
   return {"type":"string"}
  elif t is int:
   return {"type":"integer"}
  elif t is float:
   return {"type":"number"}
  elif t is bool:
   return {"type":"boolean"}
  elif t is datetime:
   return {"type":"string","format":"date-time"}
  elif t is dict or t is Dict:
   return {"type":"object","additionalProperties":{}}
  else:
   return {"type":"string"}
 args=get_args(t)
 if origin is dict or origin is Dict:
  return {"type":"object","additionalProperties":{}}
 from typing import Union
 if origin is Union:
  non_none=[a for a in args if a is not type(None)]
  if len(non_none)==1:
   result=_type_to_schema(non_none[0])
   result["nullable"]=True
   return result
  return {"oneOf":[_type_to_schema(a) for a in non_none],"nullable":True}
 if origin is list:
  items_schema=_type_to_schema(args[0]) if args else {}
  return {"type":"array","items":items_schema}
 return {"type":"string"}

def generate_openapi_spec()->Dict[str,Any]:
 schemas_list=[
  ("ProjectSchema",ProjectSchema),
  ("ProjectCreateSchema",ProjectCreateSchema),
  ("ProjectUpdateSchema",ProjectUpdateSchema),
  ("AgentSchema",AgentSchema),
  ("AgentCreateSchema",AgentCreateSchema),
  ("AgentUpdateSchema",AgentUpdateSchema),
  ("CheckpointSchema",CheckpointSchema),
  ("CheckpointCreateSchema",CheckpointCreateSchema),
  ("CheckpointResolveSchema",CheckpointResolveSchema),
  ("ApiErrorSchema",ApiErrorSchema),
  ("PromptComponentSchema",PromptComponentSchema),
  ("AgentSystemPromptSchema",AgentSystemPromptSchema),
  ("GlobalCostSettingsSchema",GlobalCostSettingsSchema),
  ("GlobalCostSettingsUpdateSchema",GlobalCostSettingsUpdateSchema),
  ("BudgetStatusSchema",BudgetStatusSchema),
  ("CostHistoryItemSchema",CostHistoryItemSchema),
  ("CostHistoryResponseSchema",CostHistoryResponseSchema),
  ("CostSummarySchema",CostSummarySchema),
 ]
 schemas={name:pydantic_to_openapi_schema(model) for name,model in schemas_list}
 spec={
  "openapi":"3.0.3",
  "info":{"title":"Toybox API","version":"1.0.0","description":"AI Agent Game Development System API"},
  "paths":{},
  "components":{"schemas":schemas},
 }
 _add_project_paths(spec)
 _add_agent_paths(spec)
 _add_checkpoint_paths(spec)
 _add_cost_paths(spec)
 return spec

def _add_project_paths(spec:Dict):
 spec["paths"]["/api/projects"]={
  "get":{
   "summary":"Get all projects",
   "tags":["Projects"],
   "responses":{"200":{"description":"List of projects","content":{"application/json":{"schema":{"type":"array","items":{"$ref":"#/components/schemas/ProjectSchema"}}}}}},
  },
  "post":{
   "summary":"Create a new project",
   "tags":["Projects"],
   "requestBody":{"required":True,"content":{"application/json":{"schema":{"$ref":"#/components/schemas/ProjectCreateSchema"}}}},
   "responses":{"201":{"description":"Created project","content":{"application/json":{"schema":{"$ref":"#/components/schemas/ProjectSchema"}}}}},
  },
 }
 spec["paths"]["/api/projects/{projectId}"]={
  "get":{
   "summary":"Get project by ID",
   "tags":["Projects"],
   "parameters":[{"name":"projectId","in":"path","required":True,"schema":{"type":"string"}}],
   "responses":{"200":{"description":"Project details","content":{"application/json":{"schema":{"$ref":"#/components/schemas/ProjectSchema"}}}},"404":{"description":"Project not found","content":{"application/json":{"schema":{"$ref":"#/components/schemas/ApiErrorSchema"}}}}},
  },
  "put":{
   "summary":"Update project",
   "tags":["Projects"],
   "parameters":[{"name":"projectId","in":"path","required":True,"schema":{"type":"string"}}],
   "requestBody":{"required":True,"content":{"application/json":{"schema":{"$ref":"#/components/schemas/ProjectUpdateSchema"}}}},
   "responses":{"200":{"description":"Updated project","content":{"application/json":{"schema":{"$ref":"#/components/schemas/ProjectSchema"}}}}},
  },
  "delete":{
   "summary":"Delete project",
   "tags":["Projects"],
   "parameters":[{"name":"projectId","in":"path","required":True,"schema":{"type":"string"}}],
   "responses":{"200":{"description":"Deletion result","content":{"application/json":{"schema":{"type":"object","properties":{"success":{"type":"boolean"}}}}}}},
  },
 }

def _add_agent_paths(spec:Dict):
 spec["paths"]["/api/projects/{projectId}/agents"]={
  "get":{
   "summary":"Get agents for project",
   "tags":["Agents"],
   "parameters":[{"name":"projectId","in":"path","required":True,"schema":{"type":"string"}}],
   "responses":{"200":{"description":"List of agents","content":{"application/json":{"schema":{"type":"array","items":{"$ref":"#/components/schemas/AgentSchema"}}}}}},
  },
  "post":{
   "summary":"Create a new agent",
   "tags":["Agents"],
   "parameters":[{"name":"projectId","in":"path","required":True,"schema":{"type":"string"}}],
   "requestBody":{"required":True,"content":{"application/json":{"schema":{"$ref":"#/components/schemas/AgentCreateSchema"}}}},
   "responses":{"201":{"description":"Created agent","content":{"application/json":{"schema":{"$ref":"#/components/schemas/AgentSchema"}}}}},
  },
 }
 spec["paths"]["/api/agents/{agentId}"]={
  "get":{
   "summary":"Get agent by ID",
   "tags":["Agents"],
   "parameters":[{"name":"agentId","in":"path","required":True,"schema":{"type":"string"}}],
   "responses":{"200":{"description":"Agent details","content":{"application/json":{"schema":{"$ref":"#/components/schemas/AgentSchema"}}}},"404":{"description":"Agent not found"}},
  },
  "patch":{
   "summary":"Update agent",
   "tags":["Agents"],
   "parameters":[{"name":"agentId","in":"path","required":True,"schema":{"type":"string"}}],
   "requestBody":{"required":True,"content":{"application/json":{"schema":{"$ref":"#/components/schemas/AgentUpdateSchema"}}}},
   "responses":{"200":{"description":"Updated agent","content":{"application/json":{"schema":{"$ref":"#/components/schemas/AgentSchema"}}}}},
  },
 }
 spec["paths"]["/api/agents/{agentId}/system-prompt"]={
  "get":{
   "summary":"Get agent system prompt configuration",
   "tags":["Agents"],
   "parameters":[{"name":"agentId","in":"path","required":True,"schema":{"type":"string"}}],
   "responses":{"200":{"description":"Agent system prompt","content":{"application/json":{"schema":{"$ref":"#/components/schemas/AgentSystemPromptSchema"}}}},"404":{"description":"Agent not found"}},
  },
 }

def _add_checkpoint_paths(spec:Dict):
 spec["paths"]["/api/projects/{projectId}/checkpoints"]={
  "get":{
   "summary":"Get checkpoints for project",
   "tags":["Checkpoints"],
   "parameters":[{"name":"projectId","in":"path","required":True,"schema":{"type":"string"}}],
   "responses":{"200":{"description":"List of checkpoints","content":{"application/json":{"schema":{"type":"array","items":{"$ref":"#/components/schemas/CheckpointSchema"}}}}}},
  },
  "post":{
   "summary":"Create a new checkpoint",
   "tags":["Checkpoints"],
   "parameters":[{"name":"projectId","in":"path","required":True,"schema":{"type":"string"}}],
   "requestBody":{"required":True,"content":{"application/json":{"schema":{"$ref":"#/components/schemas/CheckpointCreateSchema"}}}},
   "responses":{"201":{"description":"Created checkpoint","content":{"application/json":{"schema":{"$ref":"#/components/schemas/CheckpointSchema"}}}}},
  },
 }
 spec["paths"]["/api/checkpoints/{checkpointId}"]={
  "get":{
   "summary":"Get checkpoint by ID",
   "tags":["Checkpoints"],
   "parameters":[{"name":"checkpointId","in":"path","required":True,"schema":{"type":"string"}}],
   "responses":{"200":{"description":"Checkpoint details","content":{"application/json":{"schema":{"$ref":"#/components/schemas/CheckpointSchema"}}}},"404":{"description":"Checkpoint not found"}},
  },
 }
 spec["paths"]["/api/checkpoints/{checkpointId}/resolve"]={
  "post":{
   "summary":"Resolve a checkpoint",
   "tags":["Checkpoints"],
   "parameters":[{"name":"checkpointId","in":"path","required":True,"schema":{"type":"string"}}],
   "requestBody":{"required":True,"content":{"application/json":{"schema":{"$ref":"#/components/schemas/CheckpointResolveSchema"}}}},
   "responses":{"200":{"description":"Resolved checkpoint","content":{"application/json":{"schema":{"$ref":"#/components/schemas/CheckpointSchema"}}}}},
  },
 }

def _add_cost_paths(spec:Dict):
 spec["paths"]["/api/config/global-cost-settings"]={
  "get":{
   "summary":"Get global cost settings",
   "tags":["Cost"],
   "responses":{"200":{"description":"Global cost settings","content":{"application/json":{"schema":{"$ref":"#/components/schemas/GlobalCostSettingsSchema"}}}}},
  },
  "put":{
   "summary":"Update global cost settings",
   "tags":["Cost"],
   "requestBody":{"required":True,"content":{"application/json":{"schema":{"$ref":"#/components/schemas/GlobalCostSettingsUpdateSchema"}}}},
   "responses":{"200":{"description":"Updated settings","content":{"application/json":{"schema":{"$ref":"#/components/schemas/GlobalCostSettingsSchema"}}}}},
  },
 }
 spec["paths"]["/api/cost/budget-status"]={
  "get":{
   "summary":"Get current budget status",
   "tags":["Cost"],
   "responses":{"200":{"description":"Budget status","content":{"application/json":{"schema":{"$ref":"#/components/schemas/BudgetStatusSchema"}}}}},
  },
 }
 spec["paths"]["/api/cost/history"]={
  "get":{
   "summary":"Get cost history",
   "tags":["Cost"],
   "parameters":[
    {"name":"project_id","in":"query","schema":{"type":"string"}},
    {"name":"year","in":"query","schema":{"type":"integer"}},
    {"name":"month","in":"query","schema":{"type":"integer"}},
    {"name":"limit","in":"query","schema":{"type":"integer","default":100}},
    {"name":"offset","in":"query","schema":{"type":"integer","default":0}},
   ],
   "responses":{"200":{"description":"Cost history","content":{"application/json":{"schema":{"$ref":"#/components/schemas/CostHistoryResponseSchema"}}}}},
  },
 }
 spec["paths"]["/api/cost/summary"]={
  "get":{
   "summary":"Get cost summary",
   "tags":["Cost"],
   "parameters":[
    {"name":"year","in":"query","schema":{"type":"integer"}},
    {"name":"month","in":"query","schema":{"type":"integer"}},
   ],
   "responses":{"200":{"description":"Cost summary","content":{"application/json":{"schema":{"$ref":"#/components/schemas/CostSummarySchema"}}}}},
  },
 }
 spec["paths"]["/api/cost/export/csv"]={
  "get":{
   "summary":"Export cost history as CSV",
   "tags":["Cost"],
   "parameters":[
    {"name":"year","in":"query","schema":{"type":"integer"}},
    {"name":"month","in":"query","schema":{"type":"integer"}},
    {"name":"project_id","in":"query","schema":{"type":"string"}},
   ],
   "responses":{"200":{"description":"CSV file","content":{"text/csv":{"schema":{"type":"string"}}}}},
  },
 }
 spec["paths"]["/api/cost/export/json"]={
  "get":{
   "summary":"Export cost history as JSON",
   "tags":["Cost"],
   "parameters":[
    {"name":"year","in":"query","schema":{"type":"integer"}},
    {"name":"month","in":"query","schema":{"type":"integer"}},
    {"name":"project_id","in":"query","schema":{"type":"string"}},
   ],
   "responses":{"200":{"description":"JSON file","content":{"application/json":{"schema":{"type":"object"}}}}},
  },
 }

def get_openapi_json()->Dict[str,Any]:
 return generate_openapi_spec()
