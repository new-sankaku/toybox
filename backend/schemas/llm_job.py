from typing import Optional, Dict, Any
from datetime import datetime
from .base import BaseSchema


class LlmJobSchema(BaseSchema):
    id: str
    project_id: str
    agent_id: str
    status: str
    model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
