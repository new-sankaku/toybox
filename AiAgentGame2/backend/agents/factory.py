import os
from typing import Optional
from .base import AgentRunner


AGENT_MODE = os.environ.get("AGENT_MODE", "testdata")


def create_agent_runner(mode: Optional[str] = None, **kwargs) -> AgentRunner:
    actual_mode = mode or AGENT_MODE

    if actual_mode == "api":
        from .api_runner import ApiAgentRunner
        return ApiAgentRunner(**kwargs)

    else:
        raise ValueError(f"Unknown agent mode: {actual_mode}. Use 'testdata' or 'api'")


def get_current_mode() -> str:
    return AGENT_MODE
