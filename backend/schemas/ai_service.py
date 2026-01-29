from typing import Dict, Any, List, Optional
from .base import BaseSchema


class AiServiceInfoSchema(BaseSchema):
    label: str
    description: str
    provider: str
    model: str


class ModelInfoSchema(BaseSchema):
    id: str
    label: str
    recommended: bool = False
    max_tokens: Optional[int] = None
    supports_vision: Optional[bool] = None
    supports_tools: Optional[bool] = None
    pricing: Optional[Dict[str, Any]] = None


class ProviderDetailSchema(BaseSchema):
    label: str
    service_types: List[str]
    models: List[ModelInfoSchema]
    default_model: str


class ServiceProviderSchema(BaseSchema):
    id: str
    label: str
    models: List[Dict[str, Any]]
    defaultModel: str = ""


class ServiceDetailSchema(BaseSchema):
    label: str
    providers: List[ServiceProviderSchema]
    default: Dict[str, str]


class UsageCategorySchema(BaseSchema):
    id: str
    label: str
    service_type: str
    default: Optional[Dict[str, str]] = None


class AiServicesMasterResponse(BaseSchema):
    service_types: List[str]
    usage_categories: List[UsageCategorySchema]
    services: Dict[str, ServiceDetailSchema]
    providers: Dict[str, ProviderDetailSchema]
    provider_type_mapping: Dict[str, str]
    reverse_provider_type_mapping: Dict[str, str]
