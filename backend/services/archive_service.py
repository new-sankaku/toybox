from datetime import datetime,timedelta
from typing import Optional,Dict,List
from models.database import session_scope
from models.tables import AgentTrace,AgentLog,SystemLog


class ArchiveService:
 def __init__(self,retention_days:int=30):
  self._retention_days=retention_days

 def set_retention_days(self,days:int)->None:
  self._retention_days=days

 def cleanup_old_traces(self,project_id:Optional[str]=None)->Dict[str,int]:
  cutoff_date=datetime.now()-timedelta(days=self._retention_days)
  deleted_counts={"traces":0,"agent_logs":0,"system_logs":0}
  with session_scope() as session:
   query=session.query(AgentTrace).filter(AgentTrace.created_at<cutoff_date)
   if project_id:
    query=query.filter(AgentTrace.project_id==project_id)
   deleted_counts["traces"]=query.delete(synchronize_session=False)
   query=session.query(AgentLog).filter(AgentLog.timestamp<cutoff_date)
   deleted_counts["agent_logs"]=query.delete(synchronize_session=False)
   query=session.query(SystemLog).filter(SystemLog.timestamp<cutoff_date)
   if project_id:
    query=query.filter(SystemLog.project_id==project_id)
   deleted_counts["system_logs"]=query.delete(synchronize_session=False)
   session.commit()
  total=sum(deleted_counts.values())
  if total>0:
   print(f"[ArchiveService] Cleaned up {total} old records: {deleted_counts}")
  return deleted_counts

 def cleanup_completed_project_data(self,project_id:str,keep_recent_days:int=7)->Dict[str,int]:
  cutoff_date=datetime.now()-timedelta(days=keep_recent_days)
  deleted_counts={"traces":0,"agent_logs":0}
  with session_scope() as session:
   deleted_counts["traces"]=session.query(AgentTrace).filter(
    AgentTrace.project_id==project_id,
    AgentTrace.created_at<cutoff_date
   ).delete(synchronize_session=False)
   from models.tables import Agent
   agent_ids=[a.id for a in session.query(Agent).filter(Agent.project_id==project_id).all()]
   if agent_ids:
    deleted_counts["agent_logs"]=session.query(AgentLog).filter(
     AgentLog.agent_id.in_(agent_ids),
     AgentLog.timestamp<cutoff_date
    ).delete(synchronize_session=False)
   session.commit()
  total=sum(deleted_counts.values())
  if total>0:
   print(f"[ArchiveService] Cleaned up project {project_id}: {deleted_counts}")
  return deleted_counts

 def get_data_statistics(self,project_id:Optional[str]=None)->Dict[str,any]:
  with session_scope() as session:
   trace_query=session.query(AgentTrace)
   agent_log_query=session.query(AgentLog)
   system_log_query=session.query(SystemLog)
   if project_id:
    trace_query=trace_query.filter(AgentTrace.project_id==project_id)
    system_log_query=system_log_query.filter(SystemLog.project_id==project_id)
   trace_count=trace_query.count()
   agent_log_count=agent_log_query.count()
   system_log_count=system_log_query.count()
   cutoff_date=datetime.now()-timedelta(days=self._retention_days)
   old_trace_count=trace_query.filter(AgentTrace.created_at<cutoff_date).count()
   old_agent_log_count=agent_log_query.filter(AgentLog.timestamp<cutoff_date).count()
   old_system_log_count=system_log_query.filter(SystemLog.timestamp<cutoff_date).count()
   return {
    "total":{
     "traces":trace_count,
     "agent_logs":agent_log_count,
     "system_logs":system_log_count,
    },
    "older_than_retention":{
     "traces":old_trace_count,
     "agent_logs":old_agent_log_count,
     "system_logs":old_system_log_count,
    },
    "retention_days":self._retention_days,
    "cutoff_date":cutoff_date.isoformat(),
   }

 def estimate_cleanup_size(self,project_id:Optional[str]=None)->Dict[str,int]:
  stats=self.get_data_statistics(project_id)
  return stats.get("older_than_retention",{})
