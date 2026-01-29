from typing import Optional, List, Dict, Any
from .base import BaseSchema


class TreeItemSchema(BaseSchema):
    name: str
    path: str
    type: str
    size: Optional[int] = None
    modified: Optional[float] = None
    children: Optional[List["TreeItemSchema"]] = None


TreeItemSchema.model_rebuild()


class ProjectTreeResponse(BaseSchema):
    tree: List[TreeItemSchema]
    project_id: str


class TreeReplaceResponse(BaseSchema):
    success: bool
    path: str
