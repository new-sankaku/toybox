from typing import Dict,Any,List
from config_loaders import load_json_config,load_yaml_config


def get_project_options_config()->Dict[str,Any]:
    return load_json_config("project_options.json")


def get_project_settings_config()->Dict[str,Any]:
    return load_yaml_config("project_settings.yaml")


def get_output_settings_defaults()->Dict[str,Any]:
    config=get_project_settings_config()
    return config.get("output",{"default_dir":"./output"})


def get_websocket_config()->Dict[str,Any]:
    config=get_project_settings_config()
    return config.get("websocket",{})


def get_cost_settings_defaults()->Dict[str,Any]:
    config=get_project_settings_config()
    return config.get("cost",{})


def get_concurrent_limits()->Dict[str,Any]:
    config=get_project_settings_config()
    return config.get("concurrent_limits",{
        "default_max_concurrent":5,
        "provider_overrides":{}
    })
