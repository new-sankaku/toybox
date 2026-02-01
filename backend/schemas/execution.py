from typing import Optional,Dict,Any,List
from pydantic import BaseModel,Field

class ConcurrentLimitsSchema(BaseModel):
 default_max_concurrent:int=5
 provider_overrides:Dict[str,int]=Field(default_factory=dict)

class WebSocketSettingsSchema(BaseModel):
 maxReconnectAttempts:int=10
 reconnectDelay:int=1000
 maxReconnectDelay:int=30000
 reconnectMultiplier:float=1.5
 heartbeatInterval:int=30000

class AdvancedQualityCheckSchema(BaseModel):
 quality_threshold:float=0.6
 escalation:Dict[str,Any]=Field(default_factory=dict)

class ToolExecutionLimitsSchema(BaseModel):
 max_iterations:int=50
 timeout_seconds:int=300
 loop_detection_threshold:int=3

class DagExecutionSettingsSchema(BaseModel):
 enabled:bool=True

class TemperatureDefaultsSchema(BaseModel):
 leader:float=0.7
 worker:float=0.5
 splitter:float=0.3
 integrator:float=0.4
 tester:float=0.3
 default:float=0.7

class TokenBudgetSettingsSchema(BaseModel):
 max_tokens_per_request:int=32768
 warning_threshold:float=0.8
 enforcement:str="soft"

class ContextPolicySettingsSchema(BaseModel):
 auto_downgrade_threshold:int=8000
 summary_max_tokens:int=2000
 summary_directive:str=""

class AdvancedSettingsSchema(BaseModel):
 qualityCheck:AdvancedQualityCheckSchema=Field(default_factory=AdvancedQualityCheckSchema)
 toolExecution:ToolExecutionLimitsSchema=Field(default_factory=ToolExecutionLimitsSchema)
 dagExecution:DagExecutionSettingsSchema=Field(default_factory=DagExecutionSettingsSchema)
 temperatureDefaults:TemperatureDefaultsSchema=Field(default_factory=TemperatureDefaultsSchema)
 tokenBudget:TokenBudgetSettingsSchema=Field(default_factory=TokenBudgetSettingsSchema)
 contextPolicy:ContextPolicySettingsSchema=Field(default_factory=ContextPolicySettingsSchema)

class UsageCategorySettingSchema(BaseModel):
 id:str
 label:str=""
 service_type:str=""
 provider:str=""
 model:str=""

class UsageCategoryUpdateSchema(BaseModel):
 provider:str
 model:str
