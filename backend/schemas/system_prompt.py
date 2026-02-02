from typing import List,Optional
from .base import BaseSchema

class PromptComponentSchema(BaseSchema):
 label:str
 content:str
 source:Optional[str]=None
 order:int

class AgentSystemPromptSchema(BaseSchema):
 agent_id:str
 agent_type:str
 system_prompt:str
 system_components:List[PromptComponentSchema]
 user_prompt:Optional[str]=None
 user_components:List[PromptComponentSchema]
 principles:List[str]
 base_prompt_file:Optional[str]=None
 has_quality_feedback:bool=False
