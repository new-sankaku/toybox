from typing import Optional,Dict,Any,List
from datetime import datetime
from pydantic import BaseModel,Field

class GlobalCostSettingsSchema(BaseModel):
 global_enabled:bool=True
 global_monthly_limit:float=100.0
 alert_threshold:int=80
 stop_on_budget_exceeded:bool=False
 services:Dict[str,Any]=Field(default_factory=dict)
 updated_at:Optional[str]=None

class GlobalCostSettingsUpdateSchema(BaseModel):
 global_enabled:Optional[bool]=None
 global_monthly_limit:Optional[float]=None
 alert_threshold:Optional[int]=None
 stop_on_budget_exceeded:Optional[bool]=None
 services:Optional[Dict[str,Any]]=None

class BudgetStatusSchema(BaseModel):
 current_usage:float
 monthly_limit:float
 remaining:float
 usage_percent:float
 alert_threshold:int
 is_over_budget:bool
 is_warning:bool
 stop_on_budget_exceeded:bool
 global_enabled:bool

class CostHistoryItemSchema(BaseModel):
 id:str
 project_id:str
 agent_id:Optional[str]=None
 agent_type:Optional[str]=None
 service_type:str
 provider_id:Optional[str]=None
 model_id:Optional[str]=None
 input_tokens:int=0
 output_tokens:int=0
 unit_count:int=1
 cost_usd:float=0.0
 recorded_at:Optional[str]=None
 metadata:Optional[Dict[str,Any]]=None

class CostHistoryResponseSchema(BaseModel):
 items:List[CostHistoryItemSchema]
 total:int
 limit:int
 offset:int

class CostSummaryByServiceSchema(BaseModel):
 input_tokens:int=0
 output_tokens:int=0
 call_count:int=0

class CostSummaryByProjectSchema(BaseModel):
 call_count:int=0

class CostSummarySchema(BaseModel):
 year:int
 month:int
 total_cost:float
 by_service:Dict[str,CostSummaryByServiceSchema]
 by_project:Dict[str,CostSummaryByProjectSchema]

class DailyCostItemSchema(BaseModel):
 date:str
 cost:float=0.0
 input_tokens:int=0
 output_tokens:int=0
 call_count:int=0

class DailyCostByServiceItemSchema(BaseModel):
 date:str
 service_type:str
 cost:float=0.0

class DailyCostResponseSchema(BaseModel):
 year:int
 month:int
 daily:List[DailyCostItemSchema]
 by_service:List[DailyCostByServiceItemSchema]
 service_types:List[str]

class CostPredictionSchema(BaseModel):
 current_usage:float
 daily_average:float
 projected_total:float
 monthly_limit:float
 projected_percent:float
 will_exceed_budget:bool
 remaining_days:int
 elapsed_days:int
 days_in_month:int
 days_until_limit:float
