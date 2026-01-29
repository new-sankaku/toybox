from typing import Dict, Any, List, Optional
from .base import BaseSchema


class ArchiveStatsResponse(BaseSchema):
    traces: int
    agents: int
    checkpoints: int
    total_size_bytes: Optional[int] = None


class ArchiveCleanupResponse(BaseSchema):
    success: bool
    deleted: Dict[str, Any]


class ArchiveEstimateResponse(BaseSchema):
    traces: Optional[int] = None
    agent_logs: Optional[int] = None
    system_logs: Optional[int] = None


class ArchiveRetentionResponse(BaseSchema):
    retention_days: int


class ArchiveExportResponse(BaseSchema):
    filename: str


class ArchiveExportAndCleanupResponse(BaseSchema):
    filename: str
    deleted: int


class AutoArchiveResponse(BaseSchema):
    archived: int


class ArchiveInfoSchema(BaseSchema):
    name: str
    size: int
    created_at: str
    project_id: Optional[str] = None


class ArchiveListResponse(BaseSchema):
    archives: List[ArchiveInfoSchema]
