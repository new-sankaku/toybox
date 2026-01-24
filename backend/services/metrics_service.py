from typing import Optional,Dict
from .base import BaseService
from models.database import session_scope
from repositories import MetricsRepository


class MetricsService(BaseService):

 def get(self,project_id:str)->Optional[Dict]:
  with session_scope() as session:
   repo = MetricsRepository(session)
   return repo.get(project_id)

 def update(self,project_id:str,data:Dict)->Dict:
  with session_scope() as session:
   repo = MetricsRepository(session)
   return repo.create_or_update(project_id,data)
