from typing import Optional, Dict, Any, List
from datetime import datetime
from .base import BaseSchema


class TraceSchema(BaseSchema):
    id: str
    project_id: str
    agent_id: str
    type: Optional[str] = None
    status: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    model_used: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
