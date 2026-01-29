from typing import Optional, Dict, Any, List, Literal
from datetime import datetime
from pydantic import Field
from .base import BaseSchema


class SequenceParticipantSchema(BaseSchema):
    id: str
    label: str
    type: Literal["external", "leader", "agent", "worker", "api"]


class SequenceMessageSchema(BaseSchema):
    id: str
    timestamp: Optional[str] = None
    from_field: str = Field(alias="from")
    to: str
    type: Literal["input", "output", "request", "response", "error", "delegation", "result"]
    label: str
    source_id: Optional[str] = None
    source_type: Optional[str] = None
    pair_id: Optional[str] = None
    duration_ms: Optional[int] = None
    tokens: Optional[Dict[str, int]] = None

    model_config = {"populate_by_name": True}


class SequenceDataSchema(BaseSchema):
    agent_id: str
    agent_type: str
    participants: List[SequenceParticipantSchema]
    messages: List[SequenceMessageSchema]
    status: str
    total_duration_ms: Optional[int] = None
    total_tokens: Optional[Dict[str, int]] = None


class AgentSchema(BaseSchema):
    id: str
    project_id: str
    type: str
    phase: int
    status: str
    progress: int
    current_task: Optional[str] = None
    tokens_used: int
    input_tokens: int
    output_tokens: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    parent_agent_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None


class AgentCreateSchema(BaseSchema):
    id: Optional[str] = None
    type: str
    phase: Optional[int] = 0
    status: Optional[str] = "pending"
    parent_agent_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class AgentUpdateSchema(BaseSchema):
    status: Optional[str] = None
    progress: Optional[int] = None
    current_task: Optional[str] = None
    tokens_used: Optional[int] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
