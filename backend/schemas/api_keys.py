from typing import Optional, Dict, Any, List
from .base import BaseSchema


class ApiKeyHintSchema(BaseSchema):
    provider_id: str
    hint: Optional[str] = None
    validated: Optional[bool] = None
    last_validated: Optional[str] = None


class ApiKeySaveResponse(BaseSchema):
    success: bool
    provider_id: str
    hint: str


class ApiKeySetResponse(BaseSchema):
    provider_id: str
    hint: str
    validated: bool


class ApiKeyValidationResponse(BaseSchema):
    success: bool
    message: Optional[str] = None
    latency: Optional[int] = None
