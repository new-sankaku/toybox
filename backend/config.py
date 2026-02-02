import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class AgentConfig:
 mode:str="testdata"
 openrouter_api_key:Optional[str]=None
 model:str=""
 max_tokens:int=4096


@dataclass
class ServerConfig:
 host:str="127.0.0.1"
 port:int=5000
 debug:bool=True
 cors_origins:str="*"


@dataclass
class DatabaseConfig:
 db_name:str="testdata.db"
 data_dir:str="data"

 @property
 def db_path(self)->str:
  return os.path.join(self.data_dir,self.db_name)

 @property
 def database_url(self)->str:
  return f"sqlite:///{self.db_path}"


@dataclass
class Config:
 agent:AgentConfig
 server:ServerConfig
 database:DatabaseConfig


def load_config()->Config:
 agent_mode=os.environ.get("AGENT_MODE","testdata")
 db_name="testdata.db" if agent_mode=="testdata" else"production.db"
 return Config(
  agent=AgentConfig(
   mode=agent_mode,
   openrouter_api_key=os.environ.get("OPENROUTER_API_KEY"),
   model=os.environ.get("AGENT_MODEL",""),
   max_tokens=int(os.environ.get("AGENT_MAX_TOKENS","4096")),
  ),
  server=ServerConfig(
   host=os.environ.get("SERVER_HOST","127.0.0.1"),
   port=int(os.environ.get("SERVER_PORT","5000")),
   debug=os.environ.get("DEBUG","true").lower()=="true",
   cors_origins=os.environ.get("CORS_ORIGINS","*"),
  ),
  database=DatabaseConfig(
   db_name=db_name,
   data_dir=os.path.join(os.path.dirname(__file__),"data"),
  ),
 )


config=load_config()


def get_config()->Config:
    return config


def reload_config():
    global config
    config=load_config()
