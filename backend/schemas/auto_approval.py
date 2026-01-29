from typing import List, Dict, Any
from .base import BaseSchema


class AutoApprovalRulesResponse(BaseSchema):
    rules: List[Dict[str, Any]]
