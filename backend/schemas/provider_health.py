from typing import Optional, List
from .base import BaseSchema


class ProviderHealthSchema(BaseSchema):
    provider_id: str
    healthy: bool
    latency_ms: Optional[int] = None
    last_checked: Optional[str] = None
    error: Optional[str] = None
