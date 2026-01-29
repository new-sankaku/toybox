from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class SkillCategory(str, Enum):
    FILE = "file"
    EXECUTE = "execute"
    PROJECT = "project"
    ASSET = "asset"
    BUILD = "build"


@dataclass
class SkillContext:
    project_id: str
    agent_id: str
    working_dir: str
    allowed_paths: List[str] = field(default_factory=list)
    denied_paths: List[str] = field(default_factory=list)
    timeout_seconds: int = 60
    max_output_size: int = 100000
    sandbox_enabled: bool = True
    restrictions: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillResult:
    success: bool
    output: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class SkillParameter:
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None


class Skill(ABC):
    name: str = ""
    description: str = ""
    category: SkillCategory = SkillCategory.FILE
    parameters: List[SkillParameter] = field(default_factory=list)

    def __init__(self):
        if not self.name:
            self.name = self.__class__.__name__
        if not hasattr(self, "parameters") or self.parameters is None:
            self.parameters = []

    @abstractmethod
    async def execute(self, context: SkillContext, **kwargs) -> SkillResult:
        pass

    def validate_params(self, **kwargs) -> Optional[str]:
        for param in self.parameters:
            if param.required and param.name not in kwargs:
                return f"Missing required parameter: {param.name}"
        return None

    def get_schema(self) -> Dict[str, Any]:
        properties = {}
        required = []
        for param in self.parameters:
            properties[param.name] = {
                "type": param.type,
                "description": param.description,
            }
            if param.default is not None:
                properties[param.name]["default"] = param.default
            if param.required:
                required.append(param.name)
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }
