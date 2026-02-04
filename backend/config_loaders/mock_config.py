from typing import Dict,Any,List
from config_loaders import load_yaml_config


def get_mock_data_config()->Dict[str,Any]:
    return load_yaml_config("mock_data.yaml")


def get_mock_skill_sequences(agent_type:str)->List[Dict[str,Any]]:
    config=get_mock_data_config()
    sequences=config.get("mock_skill_sequences",{})
    return sequences.get(agent_type,sequences.get("default",[]))


def get_mock_content(agent_type:str)->str:
    config=get_mock_data_config()
    mock_contents=config.get("mock_contents",{})
    content=mock_contents.get(agent_type)
    if content is None:
        default_content=mock_contents.get("default","# {agent_type}\n\nモックによる自動生成出力。")
        return default_content.replace("{agent_type}",agent_type)
    return content


def get_checkpoint_title_config(agent_type:str)->Dict[str,str]:
    config=get_mock_data_config()
    titles=config.get("checkpoint_titles",{})
    return titles.get(agent_type,titles.get("default",{"type":"review","title":"レビュー依頼"}))


def get_checkpoint_content(checkpoint_type:str)->str:
    config=get_mock_data_config()
    contents=config.get("checkpoint_contents",{})
    content=contents.get(checkpoint_type)
    if content is None:
        default_content=contents.get("default","# {checkpoint_type}\n\n内容を確認してください。")
        return default_content.replace("{checkpoint_type}",checkpoint_type)
    return content


def get_api_runner_checkpoint_config(agent_type:str)->Dict[str,str]:
    config=get_mock_data_config()
    configs=config.get("api_runner_checkpoint_config",{})
    return configs.get(agent_type,configs.get("default",{"type":"review","title":"レビュー依頼"}))
