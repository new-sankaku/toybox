from typing import Dict,Any,Optional,List
from config_loaders import load_yaml_config


def get_skills_config()->Dict[str,Any]:
    return load_yaml_config("skills.yaml")


def get_agent_skill_mapping()->Dict[str,List[str]]:
    config=get_skills_config()
    return config.get("agent_skill_mapping",{})


def get_mock_handlers_config()->Dict[str,Dict[str,Any]]:
    config=get_skills_config()
    return config.get("mock_handlers",{})


def get_mock_handler_config(skill_name:str)->Optional[Dict[str,Any]]:
    handlers=get_mock_handlers_config()
    return handlers.get(skill_name)
