from typing import Optional, List, Dict, Any
from datetime import datetime
from .base import BaseSchema


class InterventionSchema(BaseSchema):
    id: str
    project_id: str
    target_type: str
    target_agent_id: Optional[str] = None
    priority: str
    message: str
    attached_file_ids: List[str] = []
    status: str
    acknowledged_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
    response: Optional[str] = None
    activation_result: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
