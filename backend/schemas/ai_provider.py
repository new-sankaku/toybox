from typing import Optional, Dict, Any, List
from .base import BaseSchema


class ProviderListItemSchema(BaseSchema):
    id: str
    name: str
    models: List[str]


class ModelSchema(BaseSchema):
    id: str
    name: str
    max_tokens: Optional[int] = None
    supports_vision: bool = False
    supports_tools: bool = False
    input_cost_per_1k: Optional[float] = None
    output_cost_per_1k: Optional[float] = None


class ProviderDetailResponse(BaseSchema):
    id: str
    name: str
    models: List[ModelSchema]


class TestProviderResponse(BaseSchema):
    success: bool
    message: Optional[str] = None
    latency: Optional[int] = None


class ChatUsageSchema(BaseSchema):
    input_tokens: int
    output_tokens: int


class ChatResponse(BaseSchema):
    content: str
    model: str
    usage: ChatUsageSchema
    finish_reason: Optional[str] = None


class HealthStatusResponse(BaseSchema):
    pass
