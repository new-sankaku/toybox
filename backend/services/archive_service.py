import os
import json
import zipfile
from datetime import datetime,timedelta
from typing import Optional,Dict,List
from pathlib import Path
from models.database import session_scope
from models.tables import AgentTrace,AgentLog,SystemLog


class ArchiveService:
 def __init__(self,retention_days:int=30,archive_dir:Optional[str]=None):
  self._retention_days=retention_days
  self._archive_dir=archive_dir or os.path.join(os.path.dirname(os.path.dirname(__file__)),"data","archives")
  Path(self._archive_dir).mkdir(parents=True,exist_ok=True)

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

 def export_traces_to_zip(self,project_id:str,agent_id:Optional[str]=None,include_logs:bool=True)->Optional[str]:
  timestamp=datetime.now().strftime("%Y%m%d_%H%M%S")
  agent_suffix=f"_{agent_id}" if agent_id else""
  zip_name=f"traces_{project_id}{agent_suffix}_{timestamp}.zip"
  zip_path=os.path.join(self._archive_dir,zip_name)
  with session_scope() as session:
   query=session.query(AgentTrace).filter(AgentTrace.project_id==project_id)
   if agent_id:
    query=query.filter(AgentTrace.agent_id==agent_id)
   traces=query.all()
   if not traces:
    return None
   trace_data=[]
   for t in traces:
    trace_data.append({
     "id":t.id,
     "projectId":t.project_id,
     "agentId":t.agent_id,
     "agentType":t.agent_type,
     "status":t.status,
     "inputContext":t.input_context,
     "promptSent":t.prompt_sent,
     "llmResponse":t.llm_response,
     "outputData":t.output_data,
     "tokensInput":t.tokens_input,
     "tokensOutput":t.tokens_output,
     "durationMs":t.duration_ms,
     "errorMessage":t.error_message,
     "modelUsed":t.model_used,
     "startedAt":t.started_at.isoformat() if t.started_at else None,
     "completedAt":t.completed_at.isoformat() if t.completed_at else None,
    })
   log_data=[]
   if include_logs:
    agent_ids=list(set(t.agent_id for t in traces))
    from models.tables import Agent
    for aid in agent_ids:
     logs=session.query(AgentLog).filter(AgentLog.agent_id==aid).all()
     for log in logs:
      log_data.append({
       "id":log.id,
       "agentId":log.agent_id,
       "level":log.level,
       "message":log.message,
       "progress":log.progress,
       "timestamp":log.timestamp.isoformat() if log.timestamp else None,
      })
   with zipfile.ZipFile(zip_path,"w",zipfile.ZIP_DEFLATED,compresslevel=9) as zf:
    zf.writestr("traces.json",json.dumps(trace_data,ensure_ascii=False,indent=2))
    if log_data:
     zf.writestr("agent_logs.json",json.dumps(log_data,ensure_ascii=False,indent=2))
    metadata={
     "projectId":project_id,
     "agentId":agent_id,
     "exportedAt":datetime.now().isoformat(),
     "traceCount":len(trace_data),
     "logCount":len(log_data),
    }
    zf.writestr("metadata.json",json.dumps(metadata,ensure_ascii=False,indent=2))
  print(f"[ArchiveService] Exported {len(trace_data)} traces to {zip_path}")
  return zip_path

 def archive_and_cleanup(self,project_id:str,agent_id:Optional[str]=None)->Dict[str,any]:
  zip_path=self.export_traces_to_zip(project_id,agent_id,include_logs=True)
  if not zip_path:
   return {"success":False,"error":"No traces to archive"}
  deleted={"traces":0,"agent_logs":0}
  with session_scope() as session:
   query=session.query(AgentTrace).filter(AgentTrace.project_id==project_id)
   if agent_id:
    query=query.filter(AgentTrace.agent_id==agent_id)
   deleted["traces"]=query.delete(synchronize_session=False)
   if agent_id:
    deleted["agent_logs"]=session.query(AgentLog).filter(AgentLog.agent_id==agent_id).delete(synchronize_session=False)
   session.commit()
  return {
   "success":True,
   "zipPath":zip_path,
   "zipSize":os.path.getsize(zip_path),
   "deleted":deleted,
  }

 def archive_old_traces(self,days_old:Optional[int]=None)->Dict[str,any]:
  days=days_old or self._retention_days
  cutoff_date=datetime.now()-timedelta(days=days)
  timestamp=datetime.now().strftime("%Y%m%d_%H%M%S")
  zip_name=f"archive_old_{timestamp}.zip"
  zip_path=os.path.join(self._archive_dir,zip_name)
  with session_scope() as session:
   traces=session.query(AgentTrace).filter(AgentTrace.created_at<cutoff_date).all()
   if not traces:
    return {"success":True,"message":"No old traces to archive","archived":0}
   trace_data=[]
   for t in traces:
    trace_data.append({
     "id":t.id,
     "projectId":t.project_id,
     "agentId":t.agent_id,
     "agentType":t.agent_type,
     "status":t.status,
     "inputContext":t.input_context,
     "promptSent":t.prompt_sent,
     "llmResponse":t.llm_response,
     "outputData":t.output_data,
     "tokensInput":t.tokens_input,
     "tokensOutput":t.tokens_output,
     "durationMs":t.duration_ms,
     "errorMessage":t.error_message,
     "modelUsed":t.model_used,
     "startedAt":t.started_at.isoformat() if t.started_at else None,
     "completedAt":t.completed_at.isoformat() if t.completed_at else None,
    })
   with zipfile.ZipFile(zip_path,"w",zipfile.ZIP_DEFLATED,compresslevel=9) as zf:
    zf.writestr("traces.json",json.dumps(trace_data,ensure_ascii=False,indent=2))
    metadata={
     "archivedAt":datetime.now().isoformat(),
     "cutoffDate":cutoff_date.isoformat(),
     "traceCount":len(trace_data),
    }
    zf.writestr("metadata.json",json.dumps(metadata,ensure_ascii=False,indent=2))
   deleted=session.query(AgentTrace).filter(AgentTrace.created_at<cutoff_date).delete(synchronize_session=False)
   session.commit()
  return {
   "success":True,
   "zipPath":zip_path,
   "zipSize":os.path.getsize(zip_path),
   "archived":len(trace_data),
   "deleted":deleted,
  }

 def list_archives(self)->List[Dict]:
  archives=[]
  if not os.path.exists(self._archive_dir):
   return archives
  for filename in os.listdir(self._archive_dir):
   if filename.endswith(".zip"):
    filepath=os.path.join(self._archive_dir,filename)
    stat=os.stat(filepath)
    archives.append({
     "name":filename,
     "path":filepath,
     "size":stat.st_size,
     "createdAt":datetime.fromtimestamp(stat.st_mtime).isoformat(),
    })
  archives.sort(key=lambda x:x["createdAt"],reverse=True)
  return archives

 def delete_archive(self,archive_name:str)->bool:
  archive_path=os.path.join(self._archive_dir,archive_name)
  if not os.path.exists(archive_path):
   return False
  try:
   os.remove(archive_path)
   return True
  except Exception:
   return False

 def get_archive_info(self)->Dict[str,any]:
  archives=self.list_archives()
  total_size=sum(a["size"] for a in archives)
  return {
   "archiveDir":self._archive_dir,
   "archiveCount":len(archives),
   "totalSizeBytes":total_size,
   "retentionDays":self._retention_days,
  }
