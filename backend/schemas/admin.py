from typing import Dict, Any, List
from .base import BaseSchema


class AdminStatsResponse(BaseSchema):
    backups: Dict[str, Any]
    archives: Dict[str, Any]


class AdminArchiveResponse(BaseSchema):
    success: bool
    archived: Dict[str, Any]


class AdminCleanupResponse(BaseSchema):
    success: bool
    cleaned: Dict[str, Any]
