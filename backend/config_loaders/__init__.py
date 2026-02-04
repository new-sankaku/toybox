import json
from typing import Dict,Any,Optional
from pathlib import Path
import yaml


_config_cache:Dict[str,Any]={}
_config_dir:Optional[Path]=None


def get_config_dir()->Path:
    global _config_dir
    if _config_dir is None:
        _config_dir=Path(__file__).parent.parent/"config"
    return _config_dir


def load_json_config(filename:str,use_cache:bool=True)->Dict[str,Any]:
    global _config_cache

    if use_cache and filename in _config_cache:
        return _config_cache[filename]

    config_path=get_config_dir()/filename
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path,"r",encoding="utf-8") as f:
        data=json.load(f)

    if use_cache:
        _config_cache[filename]=data

    return data


def load_yaml_config(filename:str,use_cache:bool=True)->Dict[str,Any]:
    global _config_cache

    if use_cache and filename in _config_cache:
        return _config_cache[filename]

    config_path=get_config_dir()/filename
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path,"r",encoding="utf-8") as f:
        data=yaml.safe_load(f)

    if use_cache:
        _config_cache[filename]=data

    return data or {}


def reload_config(filename:Optional[str]=None):
    global _config_cache
    if filename:
        _config_cache.pop(filename,None)
    else:
        _config_cache.clear()
