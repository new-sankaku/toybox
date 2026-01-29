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
    total_input_tokens: Optional[int] = None
    total_output_tokens: Optional[int] = None
    estimated_total_tokens: int
    tokens_by_type: Optional[Dict[str, Any]] = None
    generation_counts: Dict[str, Any]
    elapsed_time_seconds: int
    estimated_remaining_seconds: int
    estimated_end_time: Optional[str] = None
    completed_tasks: int
    total_tasks: int
    progress_percent: int
    current_phase: int
    phase_name: str
    active_generations: Optional[int] = None


class AssetSchema(BaseSchema):
    id: str
    name: str
    type: str
    agent: Optional[str] = None
    size: Optional[str] = None
    url: Optional[str] = None
    thumbnail: Optional[str] = None
    duration: Optional[str] = None
    approval_status: Optional[str] = None
    created_at: Optional[str] = None


class SystemLogSchema(BaseSchema):
    id: str
    level: str
    source: str
    message: str
    timestamp: Optional[datetime] = None
    details: Optional[Dict[str, Any]] = None


class AgentLogSchema(BaseSchema):
    id: str
    level: str
    message: str
    timestamp: Optional[str] = None
    progress: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
