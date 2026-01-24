from typing import TypeVar,Generic,Optional,List,Type
from sqlalchemy.orm import Session
from models.tables import Base

T=TypeVar("T",bound=Base)

class BaseRepository(Generic[T]):
 def __init__(self,session:Session,model:Type[T]):
  self.session=session
  self.model=model

 def get(self,id:str)->Optional[T]:
  return self.session.query(self.model).filter(self.model.id==id).first()

 def get_all(self)->List[T]:
  return self.session.query(self.model).all()

 def create(self,entity:T)->T:
  self.session.add(entity)
  self.session.flush()
  return entity

 def update(self,entity:T)->T:
  self.session.flush()
  return entity

 def delete(self,id:str)->bool:
  entity=self.get(id)
  if entity:
   self.session.delete(entity)
   self.session.flush()
   return True
  return False
