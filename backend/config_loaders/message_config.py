from typing import Dict,Any,List
from config_loaders import load_yaml_config


def get_messages_config()->Dict[str,Any]:
    return load_yaml_config("messages.yaml")


def get_initial_task(agent_type:str)->str:
    config=get_messages_config()
    tasks=config.get("initial_tasks",{})
    return tasks.get(agent_type,tasks.get("default","[1/3] 初期化: 処理中..."))


def get_task_for_progress(agent_type:str,progress:int)->str:
    config=get_messages_config()
    progress_tasks=config.get("progress_tasks",{})
    agent_tasks=progress_tasks.get(agent_type,[])
    if not agent_tasks:
        return get_initial_task(agent_type)
    current_task=agent_tasks[0].get("task","")
    for item in agent_tasks:
        if progress>=item.get("progress",0):
            current_task=item.get("task","")
    return current_task


def get_milestones(agent_type:str)->List[tuple]:
    config=get_messages_config()
    milestones=config.get("milestones",{})
    agent_milestones=milestones.get(agent_type,[])
    return [(m.get("progress",0),m.get("level","info"),m.get("message","")) for m in agent_milestones]
