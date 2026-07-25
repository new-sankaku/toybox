from typing import Optional,Dict,Any
from sqlalchemy.orm import Session
from models.tables import GlobalExecutionSettings
from datetime import datetime
from config_loaders.project_option_config import get_concurrent_limits,get_websocket_config

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

 def get_notification_settings(self)->Dict[str,Any]:
  defaults={"enabled":False,"categories":{"checkpoint":True,"completion":True,"error":True,"budget":True},"sound":False}
  settings=self.get()
  if settings and settings.notification_settings:
   return settings.notification_settings
  return defaults

 def update_notification_settings(self,data:Dict[str,Any])->GlobalExecutionSettings:
  settings=self.get_or_create_default()
  defaults={"enabled":False,"categories":{"checkpoint":True,"completion":True,"error":True,"budget":True},"sound":False}
  current=settings.notification_settings or defaults
  current.update(data)
  settings.notification_settings=current
  settings.updated_at=datetime.now()
  self.session.flush()
  return settings

 def get_display_settings(self)->Dict[str,Any]:
  defaults={"sequenceFormat":"detailed","dashboardAnimation":True}
  settings=self.get()
  if settings and settings.display_settings:
   return settings.display_settings
  return defaults

 def update_display_settings(self,data:Dict[str,Any])->GlobalExecutionSettings:
  settings=self.get_or_create_default()
  defaults={"sequenceFormat":"detailed","dashboardAnimation":True}
  current=settings.display_settings or defaults
  current.update(data)
  settings.display_settings=current
  settings.updated_at=datetime.now()
  self.session.flush()
  return settings
