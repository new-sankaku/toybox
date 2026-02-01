from typing import Any,Dict
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
   "content_cache":{"max_size_mb":100,"max_items":500,"max_age_seconds":3600},
   "tree_cache":{"ttl_seconds":300,"persist_to_db":True},
   "metadata":{"auto_analyze_dependencies":True,"track_access_stats":True},
   "watcher":{"enabled":False,"debounce_ms":500},
   "export":{"default_format":"json","include_hidden":False},
  }
 @property
 def enabled(self)->bool:
  return self._config.get("enabled",True)
 @property
 def content_max_size_mb(self)->int:
  return self._config.get("content_cache",{}).get("max_size_mb",100)
 @property
 def content_max_items(self)->int:
  return self._config.get("content_cache",{}).get("max_items",500)
 @property
 def content_max_age_seconds(self)->int:
  return self._config.get("content_cache",{}).get("max_age_seconds",3600)
 @property
 def tree_ttl_seconds(self)->int:
  return self._config.get("tree_cache",{}).get("ttl_seconds",300)
 @property
 def tree_persist_to_db(self)->bool:
  return self._config.get("tree_cache",{}).get("persist_to_db",True)
 @property
 def auto_analyze_dependencies(self)->bool:
  return self._config.get("metadata",{}).get("auto_analyze_dependencies",True)
 @property
 def track_access_stats(self)->bool:
  return self._config.get("metadata",{}).get("track_access_stats",True)
 @property
 def watcher_enabled(self)->bool:
  return self._config.get("watcher",{}).get("enabled",False)
 @property
 def watcher_debounce_ms(self)->int:
  return self._config.get("watcher",{}).get("debounce_ms",500)
 @property
 def export_default_format(self)->str:
  return self._config.get("export",{}).get("default_format","json")
 @property
 def export_include_hidden(self)->bool:
  return self._config.get("export",{}).get("include_hidden",False)
 @classmethod
 def reset(cls)->None:
  cls._instance=None
 def reload(self,config_path:str=None)->None:
  if config_path is None:
   config_path=str(Path(__file__).parent.parent/"config"/"file_cache.yaml")
  self._config=self._load_config(config_path)
def get_file_cache_config()->FileCacheConfig:
 return FileCacheConfig()
