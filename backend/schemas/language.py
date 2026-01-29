from typing import Dict, Any
from .base import BaseSchema


class LanguageSchema(BaseSchema):
    code: str
    name: str
    native_name: str
