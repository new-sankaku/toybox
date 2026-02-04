from typing import Dict,Any,List
from config_loaders import load_yaml_config


def get_checkpoints_config()->Dict[str,Any]:
    return load_yaml_config("checkpoints.yaml")


def get_checkpoint_category_map()->Dict[str,str]:
    return get_checkpoints_config().get("category_map",{})


def get_auto_approval_rules()->List[Dict[str,Any]]:
    return get_checkpoints_config().get("auto_approval_rules",[])


def get_status_labels()->Dict[str,str]:
    return get_checkpoints_config().get("status_labels",{})


def get_resolution_labels()->Dict[str,str]:
    return get_checkpoints_config().get("resolution_labels",{})


def get_agent_status_labels()->Dict[str,str]:
    return get_checkpoints_config().get("agent_status_labels",{})


def get_approval_status_labels()->Dict[str,str]:
    return get_checkpoints_config().get("approval_status_labels",{})


def get_asset_type_labels()->Dict[str,str]:
    return get_checkpoints_config().get("asset_type_labels",{})


def get_role_labels()->Dict[str,str]:
    return get_checkpoints_config().get("role_labels",{})


def get_checkpoint_type_labels()->Dict[str,str]:
    return get_checkpoints_config().get("checkpoint_type_labels",{})
