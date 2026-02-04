from typing import Dict,Any,Set,List
from config_loaders import load_json_config


def get_file_extensions_config()->Dict[str,Any]:
    return load_json_config("file_extensions.json")


def get_all_extension_categories()->Dict[str,Set[str]]:
    config=get_file_extensions_config()
    categories=config.get("categories",{})
    return {
        cat:set(data.get("extensions",[]))
        for cat,data in categories.items()
    }


def get_scan_directories()->List[str]:
    config=get_file_extensions_config()
    return config.get("scanDirectories",["image","mp3","movie"])
