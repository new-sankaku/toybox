from pydantic import BaseModel,ConfigDict

def to_camel(s:str)->str:
 parts=s.split('_')
 return parts[0]+''.join(w.capitalize() for w in parts[1:])

class BaseSchema(BaseModel):
 model_config=ConfigDict(
  populate_by_name=True,
  alias_generator=to_camel,
  from_attributes=True,
 )
