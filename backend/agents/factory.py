import os
from typing import Optional
from .base import AgentRunner


AGENT_MODE=os.environ.get("AGENT_MODE","testdata")


def _load_task_limits()->dict:
    try:
        import yaml
        config_path=os.path.join(os.path.dirname(__file__),"..","config","agents.yaml")
        with open(config_path,"r",encoding="utf-8") as f:
            config=yaml.safe_load(f)
        return config.get("task_limits",{})
    except Exception:
        return {}


def create_agent_runner(mode:Optional[str]=None,**kwargs)->AgentRunner:
    actual_mode=mode or AGENT_MODE
    working_dir=kwargs.pop("working_dir",None)

    if actual_mode=="api":
        from .api_runner import ApiAgentRunner
        return ApiAgentRunner(**kwargs)

    elif actual_mode=="api_with_skills":
        from .api_runner import ApiAgentRunner
        from .skill_runner import SkillEnabledAgentRunner,DEFAULT_MAX_ITERATIONS
        if not working_dir:
            working_dir=os.environ.get("PROJECT_WORKING_DIR","/tmp/toybox/projects")
        task_limits=_load_task_limits()
        max_iterations=kwargs.get(
            "max_tool_iterations",
            task_limits.get("default_max_tool_iterations",DEFAULT_MAX_ITERATIONS)
        )
        base_runner=ApiAgentRunner(**kwargs)
        return SkillEnabledAgentRunner(
            base_runner=base_runner,
            working_dir=working_dir,
            max_tool_iterations=max_iterations,
        )

    elif actual_mode=="testdata" or actual_mode=="mock":
        if not working_dir:
            working_dir=os.environ.get("PROJECT_WORKING_DIR","/tmp/toybox/projects")
        from .mock_skill_runner import MockSkillRunner
        return MockSkillRunner(working_dir=working_dir,**kwargs)

    else:
        raise ValueError(f"Unknown agent mode: {actual_mode}. Use 'testdata', 'mock', 'api', or 'api_with_skills'")


def get_current_mode()->str:
    return AGENT_MODE


def get_available_modes()->list:
    return ["testdata","mock","api","api_with_skills"]
