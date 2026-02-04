from typing import Dict,Any,List
from config_loaders.agent_config import get_agents_config


def get_workflow_dependencies()->Dict[str,List[str]]:
    raw=get_agents_config().get("workflow_dependencies",{})
    result={}
    for agent,deps in raw.items():
        if isinstance(deps,list):
            result[agent]=deps
        elif isinstance(deps,dict):
            result[agent]=deps.get("depends_on",[])
    return result


def is_dag_execution_enabled()->bool:
    config=get_agents_config()
    dag_config=config.get("dag_execution",{})
    return dag_config.get("enabled",True)


def get_dag_execution_settings()->Dict[str,Any]:
    config=get_agents_config()
    return config.get("dag_execution",{"enabled":True})


def get_workflow_context_policy(agent_type:str)->Dict[str,Any]:
    raw=get_agents_config().get("workflow_dependencies",{})
    entry=raw.get(agent_type)
    if isinstance(entry,dict):
        context_from=entry.get("context_from",{})
        result={}
        for dep_key,policy in context_from.items():
            if isinstance(policy,str):
                result[dep_key]={"level":policy}
            elif isinstance(policy,dict):
                result[dep_key]=policy
            else:
                result[dep_key]={"level":"full"}
        return result
    return {}


def get_context_policy_settings()->Dict[str,Any]:
    config=get_agents_config()
    return config.get("context_policy_settings",{})


def get_token_budget_settings()->Dict[str,Any]:
    config=get_agents_config()
    return config.get("token_budget",{})


def get_summary_directive()->str:
    config=get_agents_config()
    settings=config.get("context_policy_settings",{})
    return settings.get("summary_directive","")
