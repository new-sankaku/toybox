import uuid
from datetime import datetime
from typing import Optional,List,Dict,Any
from sqlalchemy.orm import Session
from sqlalchemy import and_,update
from .base import BaseRepository
from models.tables import WorkflowSnapshot


class WorkflowSnapshotRepository(BaseRepository[WorkflowSnapshot]):
 def __init__(self,session:Session):
  super().__init__(session,WorkflowSnapshot)

 def create_snapshot(
  self,
  project_id:str,
  agent_id:str,
  workflow_run_id:str,
  step_type:str,
  step_id:str,
  label:str,
  state_data:Dict[str,Any],
  worker_tasks:List[Dict[str,Any]],
 )->Dict[str,Any]:
  snapshot=WorkflowSnapshot(
   id=f"snap-{uuid.uuid4().hex[:12]}",
   project_id=project_id,
   agent_id=agent_id,
   workflow_run_id=workflow_run_id,
   step_type=step_type,
   step_id=step_id,
   label=label,
   state_data=state_data,
   worker_tasks=worker_tasks,
   status="active",
   created_at=datetime.now(),
  )
  self.session.add(snapshot)
  self.session.flush()
  return self.to_dict(snapshot)

 def get_by_workflow_run(self,workflow_run_id:str)->List[Dict[str,Any]]:
  snapshots=self.session.query(WorkflowSnapshot).filter(
   WorkflowSnapshot.workflow_run_id==workflow_run_id
  ).order_by(WorkflowSnapshot.created_at.asc()).all()
  return [self.to_dict(s) for s in snapshots]

 def get_by_agent(self,agent_id:str)->List[Dict[str,Any]]:
  snapshots=self.session.query(WorkflowSnapshot).filter(
   WorkflowSnapshot.agent_id==agent_id
  ).order_by(WorkflowSnapshot.created_at.desc()).all()
  return [self.to_dict(s) for s in snapshots]

 def get_latest_run_snapshots(self,agent_id:str)->List[Dict[str,Any]]:
  latest=self.session.query(WorkflowSnapshot).filter(
   WorkflowSnapshot.agent_id==agent_id
  ).order_by(WorkflowSnapshot.created_at.desc()).first()
  if not latest:
   return []
  return self.get_by_workflow_run(latest.workflow_run_id)

 def mark_restored(self,snapshot_id:str)->Optional[Dict[str,Any]]:
  snapshot=self.get(snapshot_id)
  if not snapshot:
   return None
  snapshot.status="restored"
  self.session.flush()
  return self.to_dict(snapshot)

 def invalidate_after(self,workflow_run_id:str,after_snapshot_id:str)->int:
  target=self.get(after_snapshot_id)
  if not target:
   return 0
  snapshots=self.session.query(WorkflowSnapshot).filter(
   and_(
    WorkflowSnapshot.workflow_run_id==workflow_run_id,
    WorkflowSnapshot.created_at>target.created_at,
    WorkflowSnapshot.status=="active",
   )
  ).all()
  count=0
  for s in snapshots:
   s.status="invalidated"
   count+=1
  self.session.flush()
  return count

 def delete_by_project(self,project_id:str)->int:
  snapshots=self.session.query(WorkflowSnapshot).filter(
   WorkflowSnapshot.project_id==project_id
  ).all()
  count=len(snapshots)
  for s in snapshots:
   self.session.delete(s)
  self.session.flush()
  return count

 def to_dict(self,snapshot:WorkflowSnapshot)->Dict[str,Any]:
  return {
   "id":snapshot.id,
   "projectId":snapshot.project_id,
   "agentId":snapshot.agent_id,
   "workflowRunId":snapshot.workflow_run_id,
   "stepType":snapshot.step_type,
   "stepId":snapshot.step_id,
   "label":snapshot.label,
   "stateData":snapshot.state_data,
   "workerTasks":snapshot.worker_tasks,
   "status":snapshot.status,
   "createdAt":snapshot.created_at.isoformat() if snapshot.created_at else None,
  }
