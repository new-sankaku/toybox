from typing import Optional,Dict,Any
from sqlalchemy.orm import Session
from models.tables import GlobalCostSettings
from datetime import datetime
from config_loaders.project_option_config import get_cost_settings_defaults

class GlobalCostSettingsRepository:
 def __init__(self,session:Session):
  self.session=session

 def get(self)->Optional[GlobalCostSettings]:
  return self.session.query(GlobalCostSettings).first()

 def get_or_create_default(self)->GlobalCostSettings:
  settings=self.get()
  if settings:
   return settings
  defaults=get_cost_settings_defaults()
  settings=GlobalCostSettings(
   global_enabled=defaults.get("global_enabled",True),
   global_monthly_limit=str(defaults.get("global_monthly_limit",100.0)),
   alert_threshold=defaults.get("alert_threshold",80),
   stop_on_budget_exceeded=defaults.get("stop_on_budget_exceeded",False),
   services=defaults.get("services",{})
  )
  self.session.add(settings)
  self.session.flush()
  return settings

 def update(self,data:Dict[str,Any])->GlobalCostSettings:
  settings=self.get_or_create_default()
  if"global_enabled" in data:
   settings.global_enabled=data["global_enabled"]
  if"global_monthly_limit" in data:
   settings.global_monthly_limit=str(data["global_monthly_limit"])
  if"alert_threshold" in data:
   settings.alert_threshold=data["alert_threshold"]
  if"stop_on_budget_exceeded" in data:
   settings.stop_on_budget_exceeded=data["stop_on_budget_exceeded"]
  if"services" in data:
   settings.services=data["services"]
  settings.updated_at=datetime.now()
  self.session.flush()
  return settings

 def to_dict(self,settings:GlobalCostSettings)->Dict[str,Any]:
  return {
   "global_enabled":settings.global_enabled,
   "global_monthly_limit":float(settings.global_monthly_limit),
   "alert_threshold":settings.alert_threshold,
   "stop_on_budget_exceeded":settings.stop_on_budget_exceeded,
   "services":settings.services or {},
   "updated_at":settings.updated_at.isoformat() if settings.updated_at else None
  }
