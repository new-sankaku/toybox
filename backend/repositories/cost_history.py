from typing import List,Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func,and_,Float
from models.tables import CostHistory

class CostHistoryRepository:
 def __init__(self,session:Session):
  self.session=session

 def create(self,entry:CostHistory)->CostHistory:
  self.session.add(entry)
  self.session.flush()
  return entry

 def get_by_project(self,project_id:str,limit:int=100)->List[CostHistory]:
  return self.session.query(CostHistory).filter(
   CostHistory.project_id==project_id
  ).order_by(CostHistory.recorded_at.desc()).limit(limit).all()

 def get_by_date_range(self,start_date:datetime,end_date:datetime,project_id:Optional[str]=None)->List[CostHistory]:
  query=self.session.query(CostHistory).filter(
   and_(CostHistory.recorded_at>=start_date,CostHistory.recorded_at<=end_date)
  )
  if project_id:
   query=query.filter(CostHistory.project_id==project_id)
  return query.order_by(CostHistory.recorded_at.desc()).all()

 def get_monthly_total(self,year:int,month:int,project_id:Optional[str]=None)->float:
  start=datetime(year,month,1)
  if month==12:
   end=datetime(year+1,1,1)
  else:
   end=datetime(year,month+1,1)
  query=self.session.query(func.sum(func.cast(CostHistory.cost_usd,Float))).filter(
   and_(CostHistory.recorded_at>=start,CostHistory.recorded_at<end)
  )
  if project_id:
   query=query.filter(CostHistory.project_id==project_id)
  result=query.scalar()
  return float(result) if result else 0.0

 def get_summary_by_service(self,year:int,month:int)->dict:
  start=datetime(year,month,1)
  if month==12:
   end=datetime(year+1,1,1)
  else:
   end=datetime(year,month+1,1)
  results=self.session.query(
   CostHistory.service_type,
   func.sum(CostHistory.input_tokens).label("total_input"),
   func.sum(CostHistory.output_tokens).label("total_output"),
   func.count(CostHistory.id).label("call_count")
  ).filter(
   and_(CostHistory.recorded_at>=start,CostHistory.recorded_at<end)
  ).group_by(CostHistory.service_type).all()
  return {r.service_type:{"input_tokens":r.total_input or 0,"output_tokens":r.total_output or 0,"call_count":r.call_count} for r in results}

 def get_summary_by_project(self,year:int,month:int)->dict:
  start=datetime(year,month,1)
  if month==12:
   end=datetime(year+1,1,1)
  else:
   end=datetime(year,month+1,1)
  results=self.session.query(
   CostHistory.project_id,
   func.count(CostHistory.id).label("call_count")
  ).filter(
   and_(CostHistory.recorded_at>=start,CostHistory.recorded_at<end)
  ).group_by(CostHistory.project_id).all()
  return {r.project_id:{"call_count":r.call_count} for r in results}

 def delete_before(self,before_date:datetime)->int:
  count=self.session.query(CostHistory).filter(CostHistory.recorded_at<before_date).delete()
  self.session.flush()
  return count
