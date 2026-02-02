from typing import Optional,Dict,Any
from datetime import datetime
from sqlalchemy.orm import Session
from models.tables import Metric

class MetricsRepository:
 def __init__(self,session:Session):
  self.session=session

 def to_dict(self,m:Metric)->Dict[str,Any]:
  return {
   "projectId":m.project_id,
   "totalTokensUsed":m.total_tokens_used,
   "totalInputTokens":m.total_input_tokens,
   "totalOutputTokens":m.total_output_tokens,
   "estimatedTotalTokens":m.estimated_total_tokens,
   "tokensByType":m.tokens_by_type or {},
   "generationCounts":m.generation_counts or {},
   "elapsedTimeSeconds":m.elapsed_time_seconds,
   "estimatedRemainingSeconds":m.estimated_remaining_seconds,
   "estimatedEndTime":m.estimated_end_time.isoformat() if m.estimated_end_time else None,
   "completedTasks":m.completed_tasks,
   "totalTasks":m.total_tasks,
   "progressPercent":m.progress_percent,
   "currentPhase":m.current_phase,
   "phaseName":m.phase_name,
   "activeGenerations":m.active_generations,
  }

 def get(self,project_id:str)->Optional[Dict]:
  m=self.session.query(Metric).filter(Metric.project_id==project_id).first()
  return self.to_dict(m) if m else None

 def create_or_update(self,project_id:str,data:Dict)->Dict:
  m=self.session.query(Metric).filter(Metric.project_id==project_id).first()
  if not m:
   m=Metric(project_id=project_id)
   self.session.add(m)
  if"totalTokensUsed" in data:
   m.total_tokens_used=data["totalTokensUsed"]
  if"totalInputTokens" in data:
   m.total_input_tokens=data["totalInputTokens"]
  if"totalOutputTokens" in data:
   m.total_output_tokens=data["totalOutputTokens"]
  if"estimatedTotalTokens" in data:
   m.estimated_total_tokens=data["estimatedTotalTokens"]
  if"tokensByType" in data:
   m.tokens_by_type=data["tokensByType"]
  if"generationCounts" in data:
   m.generation_counts=data["generationCounts"]
  if"elapsedTimeSeconds" in data:
   m.elapsed_time_seconds=data["elapsedTimeSeconds"]
  if"estimatedRemainingSeconds" in data:
   m.estimated_remaining_seconds=data["estimatedRemainingSeconds"]
  if"estimatedEndTime" in data:
   m.estimated_end_time=datetime.fromisoformat(data["estimatedEndTime"]) if data["estimatedEndTime"] else None
  if"completedTasks" in data:
   m.completed_tasks=data["completedTasks"]
  if"totalTasks" in data:
   m.total_tasks=data["totalTasks"]
  if"progressPercent" in data:
   m.progress_percent=data["progressPercent"]
  if"currentPhase" in data:
   m.current_phase=data["currentPhase"]
  if"phaseName" in data:
   m.phase_name=data["phaseName"]
  if"activeGenerations" in data:
   m.active_generations=data["activeGenerations"]
  self.session.flush()
  return self.to_dict(m)

 def delete(self,project_id:str)->bool:
  count=self.session.query(Metric).filter(Metric.project_id==project_id).delete()
  self.session.flush()
  return count>0
