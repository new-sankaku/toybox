from typing import Optional, List, Dict, Any
from datetime import datetime
from .base import BaseSchema


class UploadedFileSchema(BaseSchema):
    id: str
    project_id: str
    filename: str
    original_filename: str
    mime_type: str
    category: str
    size_bytes: int
    description: Optional[str] = None
    created_at: Optional[datetime] = None


class FileBatchUploadResponse(BaseSchema):
    success: List[UploadedFileSchema]
    errors: List[Dict[str, Any]]
    total_uploaded: int
    total_errors: int
