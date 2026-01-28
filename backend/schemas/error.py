from typing import Optional,Dict,Any
from .base import BaseSchema

class ApiErrorSchema(BaseSchema):
 error:str
 message:str
 status_code:int
 details:Optional[Dict[str,Any]]=None
