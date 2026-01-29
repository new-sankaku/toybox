from typing import Optional, List, Dict, Any
from .base import BaseSchema


class SuccessResponse(BaseSchema):
    success: bool


class SuccessMessageResponse(BaseSchema):
    success: bool
    message: str


class SuccessOutputResponse(BaseSchema):
    success: bool
    output: Optional[Dict[str, Any]] = None


class SuccessResultsResponse(BaseSchema):
    success: bool
    results: Optional[List[Dict[str, Any]]] = None


class SuccessAgentResponse(BaseSchema):
    success: bool
    agent: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


class SuccessBackupResponse(BaseSchema):
    success: bool
    backup: Optional[Dict[str, Any]] = None
