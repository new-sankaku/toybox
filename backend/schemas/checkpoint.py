from typing import Optional, Dict, Any
from datetime import datetime
from .base import BaseSchema


class CheckpointSchema(BaseSchema):
    id: str
    project_id: str
    agent_id: str
    type: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    content_category: Optional[str] = None
    output: Optional[Dict[str, Any]] = None
    status: str
    feedback: Optional[str] = None
    resolved_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CheckpointCreateSchema(BaseSchema):
    id: Optional[str] = None
    project_id: str
    agent_id: str
    type: Optional[str] = "review"
    title: Optional[str] = None
    description: Optional[str] = None
    content_category: Optional[str] = "document"
    output: Optional[Dict[str, Any]] = None
    status: Optional[str] = "pending"


class CheckpointResolveSchema(BaseSchema):
    resolution: str
    feedback: Optional[str] = None
