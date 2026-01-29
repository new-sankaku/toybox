from typing import Optional, Dict, Any
from datetime import datetime
from .base import BaseSchema


class ProjectSchema(BaseSchema):
    id: str
    name: str
    description: Optional[str] = None
    concept: Optional[Dict[str, Any]] = None
    status: str
    current_phase: int
    state: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None
    ai_services: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    output_settings: Optional[Dict[str, Any]] = None


class ProjectCreateSchema(BaseSchema):
    name: str
    description: Optional[str] = None
    concept: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None
    ai_services: Optional[Dict[str, Any]] = None


class ProjectUpdateSchema(BaseSchema):
    name: Optional[str] = None
    description: Optional[str] = None
    concept: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    current_phase: Optional[int] = None
    state: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None
    ai_services: Optional[Dict[str, Any]] = None
    output_settings: Optional[Dict[str, Any]] = None
