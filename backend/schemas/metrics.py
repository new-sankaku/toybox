from typing import Dict, Any, Optional, List
from datetime import datetime
from .base import BaseSchema


class AiRequestStatsResponse(BaseSchema):
    total: int
    processing: int
    pending: int
    completed: int
    failed: int


class GenerationCountItem(BaseSchema):
    count: int
    unit: str
    calls: int


class ProjectMetricsResponse(BaseSchema):
    project_id: str
    total_tokens_used: int
    estimated_total_tokens: int
    elapsed_time_seconds: int
    estimated_remaining_seconds: int
    estimated_end_time: Optional[datetime] = None
    completed_tasks: int
    total_tasks: int
    progress_percent: int
    current_phase: int
    phase_name: str
    generation_counts: Dict[str, GenerationCountItem]


class AssetSchema(BaseSchema):
    id: str
    project_id: str
    type: str
    name: str
    status: Optional[str] = None
    url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SystemLogSchema(BaseSchema):
    id: str
    level: str
    source: str
    message: str
    timestamp: Optional[datetime] = None
    details: Optional[Dict[str, Any]] = None
