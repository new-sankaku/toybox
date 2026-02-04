from typing import Dict
from config_loaders import get_config_dir


_prompt_cache:Dict[str,str]={}


def load_prompt(agent_type:str)->str:
    global _prompt_cache
    if agent_type in _prompt_cache:
        return _prompt_cache[agent_type]
    prompts_dir=get_config_dir()/"prompts"
    prompt_file=prompts_dir/f"{agent_type}.md"
    if not prompt_file.exists():
        prompt_file=prompts_dir/"_default.md"
    if not prompt_file.exists():
        return""
    with open(prompt_file,"r",encoding="utf-8") as f:
        content=f.read()
    _prompt_cache[agent_type]=content
    return content


def get_all_prompts()->Dict[str,str]:
    prompts_dir=get_config_dir()/"prompts"
    if not prompts_dir.exists():
        return {}
    result={}
    for prompt_file in prompts_dir.glob("*.md"):
        if prompt_file.name.startswith("_"):
            continue
        agent_type=prompt_file.stem
        result[agent_type]=load_prompt(agent_type)
    return result
