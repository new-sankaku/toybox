from typing import Dict,Any,Optional,List
from config_loaders import get_config_dir
from config_loaders.agent_config import get_agents_config


_principle_cache:Dict[str,str]={}


def load_principle(name:str)->str:
    global _principle_cache
    if name in _principle_cache:
        return _principle_cache[name]
    principle_path=get_config_dir()/"principles"/f"{name}.md"
    if not principle_path.exists():
        return""
    with open(principle_path,"r",encoding="utf-8") as f:
        content=f.read()
    _principle_cache[name]=content
    return content


def get_agent_principles(agent_type:str,overrides:Optional[Dict[str,List[str]]]=None)->List[str]:
    if overrides and agent_type in overrides:
        return list(overrides[agent_type])
    config=get_agents_config()
    mapping=config.get("agent_principles",{})
    principles=mapping.get(agent_type)
    if principles is None:
        principles=mapping.get("_default",[])
    return principles


def load_principles_for_agent(agent_type:str,enabled_principles:Optional[List[str]]=None,principle_overrides:Optional[Dict[str,List[str]]]=None)->str:
    principle_names=get_agent_principles(agent_type,overrides=principle_overrides)
    if enabled_principles is not None:
        principle_names=[p for p in principle_names if p in enabled_principles]
    if not principle_names:
        return""
    config=get_agents_config()
    settings=config.get("principle_settings",{})
    max_chars=settings.get("max_chars_per_agent",12000)
    parts=[]
    total_len=0
    for name in principle_names:
        content=load_principle(name)
        if not content:
            continue
        if total_len+len(content)>max_chars:
            compact=_extract_compact_principle(content)
            if total_len+len(compact)<=max_chars:
                parts.append(compact)
                total_len+=len(compact)
        else:
            parts.append(content)
            total_len+=len(content)
    return"\n\n---\n\n".join(parts)


def _extract_compact_principle(content:str)->str:
    lines=content.split("\n")
    result=[]
    in_overview=False
    in_rubric=False
    for line in lines:
        if line.startswith("# 原則:"):
            result.append(line)
            continue
        if line.strip()=="## 概要":
            in_overview=True
            result.append(line)
            continue
        if in_overview:
            if line.startswith("## ") and line.strip()!="## 概要":
                in_overview=False
            else:
                result.append(line)
                continue
        if line.strip()=="## 評価ルーブリック":
            in_rubric=True
            result.append(line)
            continue
        if in_rubric:
            if line.startswith("## ") and line.strip()!="## 評価ルーブリック":
                in_rubric=False
            else:
                result.append(line)
                continue
    return"\n".join(result)


def get_principle_settings()->Dict[str,Any]:
    config=get_agents_config()
    return config.get("principle_settings",{})


def get_available_principles()->List[Dict[str,str]]:
    principles_dir=get_config_dir()/"principles"
    if not principles_dir.exists():
        return[]
    result=[]
    for f in principles_dir.glob("*.md"):
        name=f.stem
        content=load_principle(name)
        title=name
        description=""
        for line in content.split("\n"):
            if line.startswith("# 原則:"):
                title=line.replace("# 原則:","").strip()
            elif line.strip() and not line.startswith("#") and not description:
                description=line.strip()
                break
        result.append({"id":name,"label":title,"description":description})
    return result


def get_default_agent_principles()->Dict[str,List[str]]:
    config=get_agents_config()
    return config.get("agent_principles",{})
