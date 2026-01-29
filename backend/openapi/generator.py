from typing import Dict, Any, Type, get_type_hints, get_origin, get_args
from datetime import datetime
from pydantic import BaseModel
from schemas import (
    ProjectSchema,
    ProjectCreateSchema,
    ProjectUpdateSchema,
    AgentSchema,
    AgentCreateSchema,
    AgentUpdateSchema,
    CheckpointSchema,
    CheckpointCreateSchema,
    CheckpointResolveSchema,
    ApiErrorSchema,
)


def pydantic_to_openapi_schema(model: Type[BaseModel]) -> Dict[str, Any]:
    schema = {"type": "object", "properties": {}, "required": []}
    hints = get_type_hints(model)
    fields = model.model_fields
    for field_name, field_info in fields.items():
        alias = field_info.alias or field_name
        field_type = hints.get(field_name, str)
        prop = _type_to_schema(field_type)
        schema["properties"][alias] = prop
        if field_info.is_required():
            schema["required"].append(alias)
    if not schema["required"]:
        del schema["required"]
    return schema


def _type_to_schema(t) -> Dict[str, Any]:
    origin = get_origin(t)
    if origin is None:
        if t is str:
            return {"type": "string"}
        elif t is int:
            return {"type": "integer"}
        elif t is float:
            return {"type": "number"}
        elif t is bool:
            return {"type": "boolean"}
        elif t is datetime:
            return {"type": "string", "format": "date-time"}
        elif t is dict or t is Dict:
            return {"type": "object", "additionalProperties": {}}
        else:
            return {"type": "string"}
    args = get_args(t)
    if origin is dict or origin is Dict:
        return {"type": "object", "additionalProperties": {}}
    from typing import Union

    if origin is Union:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            result = _type_to_schema(non_none[0])
            result["nullable"] = True
            return result
        return {"oneOf": [_type_to_schema(a) for a in non_none], "nullable": True}
    if origin is list:
        items_schema = _type_to_schema(args[0]) if args else {}
        return {"type": "array", "items": items_schema}
    return {"type": "string"}


def generate_openapi_spec() -> Dict[str, Any]:
    schemas_list = [
        ("ProjectSchema", ProjectSchema),
        ("ProjectCreateSchema", ProjectCreateSchema),
        ("ProjectUpdateSchema", ProjectUpdateSchema),
        ("AgentSchema", AgentSchema),
        ("AgentCreateSchema", AgentCreateSchema),
        ("AgentUpdateSchema", AgentUpdateSchema),
        ("CheckpointSchema", CheckpointSchema),
        ("CheckpointCreateSchema", CheckpointCreateSchema),
        ("CheckpointResolveSchema", CheckpointResolveSchema),
        ("ApiErrorSchema", ApiErrorSchema),
    ]
    schemas = {name: pydantic_to_openapi_schema(model) for name, model in schemas_list}
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Toybox API", "version": "1.0.0", "description": "AI Agent Game Development System API"},
        "paths": {},
        "components": {"schemas": schemas},
    }
    _add_project_paths(spec)
    _add_agent_paths(spec)
    _add_checkpoint_paths(spec)
    return spec


def _add_project_paths(spec: Dict):
    spec["paths"]["/api/projects"] = {
        "get": {
            "summary": "Get all projects",
            "tags": ["Projects"],
            "responses": {
                "200": {
                    "description": "List of projects",
                    "content": {
                        "application/json": {
                            "schema": {"type": "array", "items": {"$ref": "#/components/schemas/ProjectSchema"}}
                        }
                    },
                }
            },
        },
        "post": {
            "summary": "Create a new project",
            "tags": ["Projects"],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ProjectCreateSchema"}}},
            },
            "responses": {
                "201": {
                    "description": "Created project",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ProjectSchema"}}},
                }
            },
        },
    }
    spec["paths"]["/api/projects/{projectId}"] = {
        "get": {
            "summary": "Get project by ID",
            "tags": ["Projects"],
            "parameters": [{"name": "projectId", "in": "path", "required": True, "schema": {"type": "string"}}],
            "responses": {
                "200": {
                    "description": "Project details",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ProjectSchema"}}},
                },
                "404": {
                    "description": "Project not found",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiErrorSchema"}}},
                },
            },
        },
        "put": {
            "summary": "Update project",
            "tags": ["Projects"],
            "parameters": [{"name": "projectId", "in": "path", "required": True, "schema": {"type": "string"}}],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ProjectUpdateSchema"}}},
            },
            "responses": {
                "200": {
                    "description": "Updated project",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ProjectSchema"}}},
                }
            },
        },
        "delete": {
            "summary": "Delete project",
            "tags": ["Projects"],
            "parameters": [{"name": "projectId", "in": "path", "required": True, "schema": {"type": "string"}}],
            "responses": {
                "200": {
                    "description": "Deletion result",
                    "content": {
                        "application/json": {
                            "schema": {"type": "object", "properties": {"success": {"type": "boolean"}}}
                        }
                    },
                }
            },
        },
    }


def _add_agent_paths(spec: Dict):
    spec["paths"]["/api/projects/{projectId}/agents"] = {
        "get": {
            "summary": "Get agents for project",
            "tags": ["Agents"],
            "parameters": [{"name": "projectId", "in": "path", "required": True, "schema": {"type": "string"}}],
            "responses": {
                "200": {
                    "description": "List of agents",
                    "content": {
                        "application/json": {
                            "schema": {"type": "array", "items": {"$ref": "#/components/schemas/AgentSchema"}}
                        }
                    },
                }
            },
        },
        "post": {
            "summary": "Create a new agent",
            "tags": ["Agents"],
            "parameters": [{"name": "projectId", "in": "path", "required": True, "schema": {"type": "string"}}],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/AgentCreateSchema"}}},
            },
            "responses": {
                "201": {
                    "description": "Created agent",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/AgentSchema"}}},
                }
            },
        },
    }
    spec["paths"]["/api/agents/{agentId}"] = {
        "get": {
            "summary": "Get agent by ID",
            "tags": ["Agents"],
            "parameters": [{"name": "agentId", "in": "path", "required": True, "schema": {"type": "string"}}],
            "responses": {
                "200": {
                    "description": "Agent details",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/AgentSchema"}}},
                },
                "404": {"description": "Agent not found"},
            },
        },
        "patch": {
            "summary": "Update agent",
            "tags": ["Agents"],
            "parameters": [{"name": "agentId", "in": "path", "required": True, "schema": {"type": "string"}}],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/AgentUpdateSchema"}}},
            },
            "responses": {
                "200": {
                    "description": "Updated agent",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/AgentSchema"}}},
                }
            },
        },
    }


def _add_checkpoint_paths(spec: Dict):
    spec["paths"]["/api/projects/{projectId}/checkpoints"] = {
        "get": {
            "summary": "Get checkpoints for project",
            "tags": ["Checkpoints"],
            "parameters": [{"name": "projectId", "in": "path", "required": True, "schema": {"type": "string"}}],
            "responses": {
                "200": {
                    "description": "List of checkpoints",
                    "content": {
                        "application/json": {
                            "schema": {"type": "array", "items": {"$ref": "#/components/schemas/CheckpointSchema"}}
                        }
                    },
                }
            },
        },
        "post": {
            "summary": "Create a new checkpoint",
            "tags": ["Checkpoints"],
            "parameters": [{"name": "projectId", "in": "path", "required": True, "schema": {"type": "string"}}],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CheckpointCreateSchema"}}},
            },
            "responses": {
                "201": {
                    "description": "Created checkpoint",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CheckpointSchema"}}},
                }
            },
        },
    }
    spec["paths"]["/api/checkpoints/{checkpointId}"] = {
        "get": {
            "summary": "Get checkpoint by ID",
            "tags": ["Checkpoints"],
            "parameters": [{"name": "checkpointId", "in": "path", "required": True, "schema": {"type": "string"}}],
            "responses": {
                "200": {
                    "description": "Checkpoint details",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CheckpointSchema"}}},
                },
                "404": {"description": "Checkpoint not found"},
            },
        },
    }
    spec["paths"]["/api/checkpoints/{checkpointId}/resolve"] = {
        "post": {
            "summary": "Resolve a checkpoint",
            "tags": ["Checkpoints"],
            "parameters": [{"name": "checkpointId", "in": "path", "required": True, "schema": {"type": "string"}}],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CheckpointResolveSchema"}}},
            },
            "responses": {
                "200": {
                    "description": "Resolved checkpoint",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CheckpointSchema"}}},
                }
            },
        },
    }


def get_openapi_json() -> Dict[str, Any]:
    return generate_openapi_spec()
