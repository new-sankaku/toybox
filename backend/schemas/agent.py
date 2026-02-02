from typing import Optional,Dict,Any
from datetime import datetime
from .base import BaseSchema

class AgentSchema(BaseSchema):
 id:str
 project_id:str
 type:str
 phase:int
 status:str
 progress:int
 current_task:Optional[str]=None
 tokens_used:int
 input_tokens:int
 output_tokens:int
 started_at:Optional[datetime]=None
 completed_at:Optional[datetime]=None
 error:Optional[str]=None
 parent_agent_id:Optional[str]=None
 metadata:Optional[Dict[str,Any]]=None
 created_at:Optional[datetime]=None

class AgentCreateSchema(BaseSchema):
 id:Optional[str]=None
 type:str
 phase:Optional[int]=0
 status:Optional[str]="pending"
 parent_agent_id:Optional[str]=None
 metadata:Optional[Dict[str,Any]]=None

class AgentUpdateSchema(BaseSchema):
 status:Optional[str]=None
 progress:Optional[int]=None
 current_task:Optional[str]=None
 tokens_used:Optional[int]=None
 input_tokens:Optional[int]=None
 output_tokens:Optional[int]=None
 started_at:Optional[datetime]=None
 completed_at:Optional[datetime]=None
 error:Optional[str]=None
 metadata:Optional[Dict[str,Any]]=None
