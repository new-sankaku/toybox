from typing import Optional,Dict,Any
from sqlalchemy.orm import Session
from models.tables import GlobalExecutionSettings
from datetime import datetime
from config_loader import get_concurrent_limits,get_websocket_config

class GlobalExecutionSettingsRepository:
 def __init__(self,session:Session):
  self.session=session

 def get(self)->Optional[GlobalExecutionSettings]:
  return self.session.query(GlobalExecutionSettings).first()

 def get_or_create_default(self)->GlobalExecutionSettings:
  settings=self.get()
  if settings:
   return settings
  settings=GlobalExecutionSettings(
   concurrent_limits=get_concurrent_limits(),
   websocket_settings=get_websocket_config()
  )
  self.session.add(settings)
  self.session.flush()
  return settings

 def update_concurrent_limits(self,data:Dict[str,Any])->GlobalExecutionSettings:
  settings=self.get_or_create_default()
  current=settings.concurrent_limits or get_concurrent_limits()
  current.update(data)
  settings.concurrent_limits=current
  settings.updated_at=datetime.now()
  self.session.flush()
  return settings

 def update_websocket_settings(self,data:Dict[str,Any])->GlobalExecutionSettings:
  settings=self.get_or_create_default()
  current=settings.websocket_settings or get_websocket_config()
  current.update(data)
  settings.websocket_settings=current
  settings.updated_at=datetime.now()
  self.session.flush()
  return settings

 def get_concurrent_limits(self)->Dict[str,Any]:
  settings=self.get()
  if settings and settings.concurrent_limits:
   return settings.concurrent_limits
  return get_concurrent_limits()

 def get_websocket_settings(self)->Dict[str,Any]:
  settings=self.get()
  if settings and settings.websocket_settings:
   return settings.websocket_settings
  return get_websocket_config()
