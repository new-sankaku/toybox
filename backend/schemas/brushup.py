from typing import Dict, Any, List
from .base import BaseSchema


class BrushupOptionsResponse(BaseSchema):
    presets: List[Dict[str, Any]]
    agent_options: Dict[str, List[Dict[str, Any]]]


class BrushupImageSchema(BaseSchema):
    id: str
    url: str
    prompt: str


class BrushupSuggestImagesResponse(BaseSchema):
    images: List[BrushupImageSchema]
