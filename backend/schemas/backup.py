from typing import Optional, Dict, Any, List
from datetime import datetime
from .base import BaseSchema


class BackupInfoSchema(BaseSchema):
    name: str
    path: str
    size: int
    created_at: str


class CreateBackupResponse(BaseSchema):
    success: bool
    backup: str


class RestoreBackupResponse(BaseSchema):
    success: bool
    message: str
