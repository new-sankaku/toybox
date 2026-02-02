from typing import Any,Dict,List,Set
from pathlib import Path
import yaml
class FileCacheConfig:
    _instance=None
    _config:Dict[str,Any]={}
    def __new__(cls,config_path:str=None):
        if cls._instance is None:
            cls._instance=super().__new__(cls)
            cls._instance._initialized=False
        return cls._instance
    def __init__(self,config_path:str=None):
        if self._initialized:
            return
        if config_path is None:
            config_path=str(Path(__file__).parent.parent/"config"/"file_cache.yaml")
        self._config=self._load_config(config_path)
        self._initialized=True
    def _load_config(self,config_path:str)->Dict[str,Any]:
        try:
            with open(config_path,"r",encoding="utf-8") as f:
                data=yaml.safe_load(f)
            return data.get("file_cache",{}) if data else {}
        except FileNotFoundError:
            return self._get_defaults()
    def _get_defaults(self)->Dict[str,Any]:
        return {
            "enabled":True,
            "content_cache":{"max_size_mb":1024,"max_file_size_mb":10},
            "tree_cache":{"persist_to_db":True},
            "metadata":{"track_access_stats":True},
            "watcher":{"enabled":True,"debounce_ms":300},
            "binary_extensions":[".png",".jpg",".jpeg",".gif",".mp3",".wav",".mp4",".zip",".exe",".dll",".pdf"],
            "ignore_dirs":["node_modules","__pycache__",".git",".venv","dist","build"],
        }
    @property
    def enabled(self)->bool:
        return self._config.get("enabled",True)
    @property
    def content_max_size_mb(self)->int:
        return self._config.get("content_cache",{}).get("max_size_mb",1024)
    @property
    def content_max_size_bytes(self)->int:
        return self.content_max_size_mb*1024*1024
    @property
    def max_file_size_mb(self)->int:
        return self._config.get("content_cache",{}).get("max_file_size_mb",10)
    @property
    def max_file_size_bytes(self)->int:
        return self.max_file_size_mb*1024*1024
    @property
    def tree_persist_to_db(self)->bool:
        return self._config.get("tree_cache",{}).get("persist_to_db",True)
    @property
    def track_access_stats(self)->bool:
        return self._config.get("metadata",{}).get("track_access_stats",True)
    @property
    def watcher_enabled(self)->bool:
        return self._config.get("watcher",{}).get("enabled",True)
    @property
    def watcher_debounce_ms(self)->int:
        return self._config.get("watcher",{}).get("debounce_ms",300)
    @property
    def binary_extensions(self)->Set[str]:
        exts=self._config.get("binary_extensions",[])
        return set(exts)
    @property
    def ignore_dirs(self)->Set[str]:
        dirs=self._config.get("ignore_dirs",[])
        return set(dirs)
    @classmethod
    def reset(cls)->None:
        cls._instance=None
    def reload(self,config_path:str=None)->None:
        if config_path is None:
            config_path=str(Path(__file__).parent.parent/"config"/"file_cache.yaml")
        self._config=self._load_config(config_path)
def get_file_cache_config()->FileCacheConfig:
    return FileCacheConfig()
