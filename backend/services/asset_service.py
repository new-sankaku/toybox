from typing import Optional,Dict,List
from .base import BaseService
from models.database import session_scope
from repositories import AssetRepository


class AssetService(BaseService):

 def get_by_project(self,project_id:str)->List[Dict]:
  with session_scope() as session:
   repo = AssetRepository(session)
   return repo.get_by_project(project_id)

 def update(self,project_id:str,asset_id:str,data:Dict)->Optional[Dict]:
  with session_scope() as session:
   repo = AssetRepository(session)
   return repo.update_from_dict(project_id,asset_id,data)
