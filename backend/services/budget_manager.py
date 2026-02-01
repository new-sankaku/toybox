from typing import Dict,Any,Optional,Tuple
from datetime import datetime
from datastore import get_session
from repositories.global_cost_settings import GlobalCostSettingsRepository
from repositories.cost_history import CostHistoryRepository
from models.tables import CostHistory
from middleware.logger import get_logger
import uuid

class BudgetManager:
 def __init__(self,sio=None):
  self.sio=sio

 def get_current_month_usage(self)->float:
  now=datetime.now()
  with get_session() as session:
   repo=CostHistoryRepository(session)
   return repo.get_monthly_total(now.year,now.month)

 def get_budget_status(self)->Dict[str,Any]:
  with get_session() as session:
   settings_repo=GlobalCostSettingsRepository(session)
   settings=settings_repo.get_or_create_default()
   current_usage=self.get_current_month_usage()
   monthly_limit=float(settings.global_monthly_limit)
   usage_percent=0 if monthly_limit<=0 else(current_usage/monthly_limit)*100
   remaining=max(0,monthly_limit-current_usage)
   is_over_budget=current_usage>=monthly_limit
   is_warning=usage_percent>=settings.alert_threshold
   return {
    "current_usage":round(current_usage,4),
    "monthly_limit":monthly_limit,
    "remaining":round(remaining,4),
    "usage_percent":round(usage_percent,1),
    "alert_threshold":settings.alert_threshold,
    "is_over_budget":is_over_budget,
    "is_warning":is_warning,
    "stop_on_budget_exceeded":settings.stop_on_budget_exceeded,
    "global_enabled":settings.global_enabled
   }

 def check_budget(self)->Tuple[bool,Optional[str]]:
  with get_session() as session:
   settings_repo=GlobalCostSettingsRepository(session)
   settings=settings_repo.get_or_create_default()
   if not settings.global_enabled:
    return True,None
   current_usage=self.get_current_month_usage()
   monthly_limit=float(settings.global_monthly_limit)
   if current_usage>=monthly_limit:
    if settings.stop_on_budget_exceeded:
     return False,"budget_exceeded"
    return True,"budget_warning"
   usage_percent=(current_usage/monthly_limit)*100 if monthly_limit>0 else 0
   if usage_percent>=settings.alert_threshold:
    return True,"threshold_warning"
   return True,None

 def record_cost(self,project_id:str,service_type:str,cost_usd:float,agent_id:Optional[str]=None,agent_type:Optional[str]=None,provider_id:Optional[str]=None,model_id:Optional[str]=None,input_tokens:int=0,output_tokens:int=0,unit_count:int=1,metadata:Optional[Dict]=None)->CostHistory:
  with get_session() as session:
   repo=CostHistoryRepository(session)
   entry=CostHistory(
    id=str(uuid.uuid4()),
    project_id=project_id,
    agent_id=agent_id,
    agent_type=agent_type,
    service_type=service_type,
    provider_id=provider_id,
    model_id=model_id,
    input_tokens=input_tokens,
    output_tokens=output_tokens,
    unit_count=unit_count,
    cost_usd=str(round(cost_usd,6)),
    recorded_at=datetime.now(),
    metadata_=metadata
   )
   repo.create(entry)
   session.commit()
   self._check_and_notify_budget()
   return entry

 def _check_and_notify_budget(self)->None:
  if not self.sio:
   return
  can_proceed,warning_type=self.check_budget()
  if warning_type:
   status=self.get_budget_status()
   self.sio.emit("budget_warning",{
    "type":warning_type,
    "status":status
   })
   get_logger().warning(f"Budget warning: {warning_type}, usage: {status['usage_percent']}%")

_budget_manager:Optional[BudgetManager]=None

def get_budget_manager(sio=None)->BudgetManager:
 global _budget_manager
 if _budget_manager is None:
  _budget_manager=BudgetManager(sio)
 elif sio and _budget_manager.sio is None:
  _budget_manager.sio=sio
 return _budget_manager
