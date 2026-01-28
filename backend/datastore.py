import os
import uuid
import threading
import time
import random
from datetime import datetime,timedelta
from typing import Optional,Dict,List,Any

from sqlalchemy.orm.attributes import flag_modified
from models.database import get_session,session_scope,init_db
from repositories import (
 ProjectRepository,AgentRepository,CheckpointRepository,
 AgentLogRepository,SystemLogRepository,AssetRepository,
 InterventionRepository,UploadedFileRepository,MetricsRepository,
 QualitySettingsRepository,AgentTraceRepository,LlmJobRepository
)
from agent_settings import get_default_quality_settings,QualityCheckConfig
from ai_config import build_default_ai_services
from config_loader import (
 get_checkpoint_category_map,
 get_auto_approval_rules as get_config_auto_approval_rules,
 get_workflow_dependencies,
 get_initial_task,
 get_task_for_progress,
 get_milestones,
 get_generation_type_for_agent,
 get_agent_assets,
 get_agent_checkpoints,
 get_checkpoint_content,
)
from asset_scanner import get_testdata_path
from middleware.logger import get_logger


class DataStore:
 def __init__(self):
  init_db()
  self.subscriptions:Dict[str,set]={}
  self._simulation_running=False
  self._simulation_thread:Optional[threading.Thread]=None
  self._lock=threading.Lock()
  self._sio=None
  self._init_sample_data_if_empty()

 def set_sio(self,sio):
  self._sio=sio

 def _emit_event(self,event:str,data:Dict,project_id:str):
  if self._sio:
   try:
    self._sio.emit(event,data,room=f"project:{project_id}")
   except Exception as e:
    get_logger().warning(f"Error emitting {event}: {e}")

 def _init_sample_data_if_empty(self):
  with session_scope() as session:
   repo=ProjectRepository(session)
   if repo.get_all():
    return
   self._create_sample_project(session)

 def _create_sample_project(self,session):
  now=datetime.now()
  proj_id="proj-001"
  from models.tables import Project,Agent,Metric
  project=Project(
   id=proj_id,
   name="パズルアクションゲーム",
   description="物理演算を使ったパズルゲーム。ボールを転がして障害物を避けながらゴールを目指す。",
   concept={
    "description":"ボールを転がしてゴールを目指すパズル。重力や摩擦をリアルに再現。",
    "platform":"web",
    "scope":"demo",
    "genre":"Puzzle",
    "targetAudience":"全年齢"
   },
   status="draft",
   current_phase=1,
   state={},
   config={"maxTokensPerAgent":100000,"autoApprovalRules":get_config_auto_approval_rules()},
   ai_services=dict(build_default_ai_services()),
   created_at=now,
   updated_at=now
  )
  session.add(project)
  agents_data=[
   {"type":"concept","name":"コンセプト","phase":0},
   {"type":"task_split_1","name":"タスク分割1","phase":1},
   {"type":"concept_detail","name":"コンセプト詳細","phase":2},
   {"type":"scenario","name":"シナリオ","phase":2},
   {"type":"world","name":"世界観","phase":2},
   {"type":"game_design","name":"ゲームデザイン","phase":2},
   {"type":"tech_spec","name":"技術仕様","phase":2},
   {"type":"task_split_2","name":"タスク分割2","phase":3},
   {"type":"asset_character","name":"キャラ","phase":4},
   {"type":"asset_background","name":"背景","phase":4},
   {"type":"asset_ui","name":"UI","phase":4},
   {"type":"asset_effect","name":"エフェクト","phase":4},
   {"type":"asset_bgm","name":"BGM","phase":4},
   {"type":"asset_voice","name":"ボイス","phase":4},
   {"type":"asset_sfx","name":"効果音","phase":4},
   {"type":"task_split_3","name":"タスク分割3","phase":5},
   {"type":"code","name":"コード","phase":6},
   {"type":"event","name":"イベント","phase":6},
   {"type":"ui_integration","name":"UI統合","phase":6},
   {"type":"asset_integration","name":"アセット統合","phase":6},
   {"type":"task_split_4","name":"タスク分割4","phase":7},
   {"type":"unit_test","name":"単体テスト","phase":8},
   {"type":"integration_test","name":"統合テスト","phase":8},
  ]
  for data in agents_data:
   agent=Agent(
    id=f"agent-{proj_id}-{data['type']}",
    project_id=proj_id,
    type=data["type"],
    phase=data["phase"],
    status="pending",
    progress=0,
    tokens_used=0,
    input_tokens=0,
    output_tokens=0,
    metadata_={"displayName":data["name"]},
    created_at=now
   )
   session.add(agent)
  metric=Metric(
   project_id=proj_id,
   total_tokens_used=0,
   total_input_tokens=0,
   total_output_tokens=0,
   estimated_total_tokens=50000,
   tokens_by_type={},
   generation_counts={},
   elapsed_time_seconds=0,
   estimated_remaining_seconds=0,
   completed_tasks=0,
   total_tasks=6,
   progress_percent=0,
   current_phase=1,
   phase_name="Phase 1: 企画・設計",
   active_generations=0
  )
  session.add(metric)
  session.flush()
  get_logger().info(f"Sample project {proj_id} created")

 def start_simulation(self):
  if self._simulation_running:
   return
  self._simulation_running=True
  self._simulation_thread=threading.Thread(target=self._simulation_loop,daemon=True)
  self._simulation_thread.start()
  get_logger().info("Simulation started")

 def stop_simulation(self):
  self._simulation_running=False
  if self._simulation_thread:
   self._simulation_thread.join(timeout=2)
  get_logger().info("Simulation stopped")

 def _simulation_loop(self):
  while self._simulation_running:
   try:
    with self._lock:
     self._tick_simulation()
   except Exception as e:
    get_logger().error(f"Simulation tick error: {e}",exc_info=True)
   time.sleep(1)

 def _tick_simulation(self):
  with session_scope() as session:
   repo=ProjectRepository(session)
   for p in repo.get_all():
    if p.status=="running":
     self._simulate_project(session,p.id)

 def _can_start_agent(self,session,agent_type:str,project_id:str)->bool:
  workflow_deps=get_workflow_dependencies()
  dependencies=workflow_deps.get(agent_type,[])
  agent_repo=AgentRepository(session)
  agents=agent_repo.get_by_project(project_id)
  for dep_type in dependencies:
   dep_agent=next((a for a in agents if a["type"]==dep_type),None)
   if not dep_agent or dep_agent["status"]!="completed":
    return False
   cp_repo=CheckpointRepository(session)
   pending_cps=[c for c in cp_repo.get_by_agent(dep_agent["id"]) if c["status"]=="pending"]
   if pending_cps:
    return False
  return True

 def _get_next_agents_to_start(self,session,project_id:str)->List[Dict]:
  agent_repo=AgentRepository(session)
  agents=agent_repo.get_by_project(project_id)
  pending=[a for a in agents if a["status"]=="pending"]
  return [a for a in pending if self._can_start_agent(session,a["type"],project_id)]

 def _simulate_project(self,session,project_id:str):
  proj_repo=ProjectRepository(session)
  agent_repo=AgentRepository(session)
  project=proj_repo.get(project_id)
  if not project:
   return
  agents=agent_repo.get_by_project(project_id)
  running_agents=[a for a in agents if a["status"]=="running"]
  if running_agents:
   for agent in running_agents:
    self._simulate_agent(session,agent)
  else:
   ready_agents=self._get_next_agents_to_start(session,project_id)
   if ready_agents:
    for agent in ready_agents:
     self._start_agent(session,agent)
   else:
    completed=all(a["status"]=="completed" for a in agents)
    if completed:
     project.status="completed"
     project.updated_at=datetime.now()
     self._add_system_log_internal(session,project_id,"info","System","プロジェクト完了！")
  self._update_project_metrics(session,project_id)

 def _start_agent(self,session,agent_dict:Dict):
  agent_repo=AgentRepository(session)
  agent=agent_repo.get(agent_dict["id"])
  now=datetime.now()
  agent.status="running"
  agent.progress=0
  agent.started_at=now
  agent.current_task=get_initial_task(agent.type)
  session.flush()
  display_name=agent.metadata_.get("displayName",agent.type) if agent.metadata_ else agent.type
  self._add_agent_log_internal(session,agent.id,"info",f"{display_name}エージェント起動",0)
  self._add_system_log_internal(session,agent.project_id,"info",agent.type,f"{display_name}開始")
  self._emit_event("agent:started",{
   "agentId":agent.id,
   "projectId":agent.project_id,
   "agent":agent_repo.to_dict(agent)
  },agent.project_id)

 def _simulate_agent(self,session,agent_dict:Dict):
  if agent_dict["status"]=="waiting_approval":
   return
  agent_repo=AgentRepository(session)
  agent=agent_repo.get(agent_dict["id"])
  increment=random.randint(2,5)
  new_progress=min(100,agent.progress+increment)
  token_increment=random.randint(30,80)
  input_increment=int(token_increment*0.3)
  output_increment=token_increment-input_increment
  agent.tokens_used+=token_increment
  agent.input_tokens+=input_increment
  agent.output_tokens+=output_increment
  old_progress=agent.progress
  agent.progress=new_progress
  agent.current_task=get_task_for_progress(agent.type,new_progress)
  session.flush()
  self._check_milestone_logs(session,agent,old_progress,new_progress)
  self._check_checkpoint_creation(session,agent,old_progress,new_progress)
  self._check_asset_generation(session,agent,old_progress,new_progress)
  self._check_trace_generation(session,agent,old_progress,new_progress)
  agent=agent_repo.get(agent_dict["id"])
  if agent.status=="waiting_approval":
   self._emit_event("agent:progress",{
    "agentId":agent.id,
    "projectId":agent.project_id,
    "progress":new_progress,
    "currentTask":"承認待ち",
    "tokensUsed":agent.tokens_used,
    "message":f"承認待ち (進捗: {new_progress}%)"
   },agent.project_id)
   return
  self._emit_event("agent:progress",{
   "agentId":agent.id,
   "projectId":agent.project_id,
   "progress":new_progress,
   "currentTask":agent.current_task,
   "tokensUsed":agent.tokens_used,
   "message":f"進捗: {new_progress}%"
  },agent.project_id)
  if new_progress>=100:
   self._complete_agent(session,agent)

 def _complete_agent(self,session,agent):
  now=datetime.now()
  agent.status="completed"
  agent.progress=100
  agent.completed_at=now
  agent.current_task=None
  session.flush()
  display_name=agent.metadata_.get("displayName",agent.type) if agent.metadata_ else agent.type
  self._add_agent_log_internal(session,agent.id,"info",f"{display_name}完了",100)
  self._add_system_log_internal(session,agent.project_id,"info",agent.type,f"{display_name}完了")
  agent_repo=AgentRepository(session)
  self._emit_event("agent:completed",{
   "agentId":agent.id,
   "projectId":agent.project_id,
   "agent":agent_repo.to_dict(agent)
  },agent.project_id)
  self._resume_paused_subsequent_agents(session,agent)

 def _resume_paused_subsequent_agents(self,session,completed_agent):
  agent_repo=AgentRepository(session)
  syslog_repo=SystemLogRepository(session)
  agents=agent_repo.get_by_project(completed_agent.project_id)
  completed_phase=completed_agent.phase or 0
  for agent_dict in agents:
   if agent_dict["status"]!="paused":
    continue
   agent_phase=agent_dict.get("phase",0)
   if agent_phase<=completed_phase:
    continue
   if not self._can_start_agent(session,agent_dict["type"],completed_agent.project_id):
    continue
   agent=agent_repo.get(agent_dict["id"])
   agent.status="running"
   agent.updated_at=datetime.now()
   session.flush()
   display_name=agent.metadata_.get("displayName",agent.type) if agent.metadata_ else agent.type
   syslog_repo.add_log(agent.project_id,"info","System",f"エージェント {display_name} を自動再開")
   self._emit_event("agent:resumed",{
    "agentId":agent.id,
    "projectId":agent.project_id,
    "agent":agent_repo.to_dict(agent),
    "reason":"previous_agent_completed"
   },agent.project_id)

 def _check_milestone_logs(self,session,agent,old_progress:int,new_progress:int):
  milestones=get_milestones(agent.type)
  for milestone_progress,level,message in milestones:
   if old_progress<milestone_progress<=new_progress:
    self._add_agent_log_internal(session,agent.id,level,message,milestone_progress)
    if level in ("warn","error"):
     self._add_system_log_internal(session,agent.project_id,level,agent.type,message)

 def _check_checkpoint_creation(self,session,agent,old_progress:int,new_progress:int):
  checkpoint_points=self._get_checkpoint_points(agent.type)
  for cp_progress,cp_type,cp_title in checkpoint_points:
   if old_progress<cp_progress<=new_progress:
    cp_repo=CheckpointRepository(session)
    existing=[c for c in cp_repo.get_by_agent(agent.id) if c["type"]==cp_type]
    if not existing:
     self._create_agent_checkpoint(session,agent,cp_type,cp_title)

 def _should_auto_approve(self,session,project_id:str,cp_type:str)->bool:
  proj_repo=ProjectRepository(session)
  project=proj_repo.get(project_id)
  if not project:
   return False
  rules=(project.config or {}).get("autoApprovalRules",[])
  if not rules:
   return False
  category=get_checkpoint_category_map().get(cp_type,"document")
  for rule in rules:
   if rule.get("category")==category:
    return rule.get("enabled",False)
  return False

 def _create_agent_checkpoint(self,session,agent,cp_type:str,title:str):
  cp_id=f"cp-{uuid.uuid4().hex[:8]}"
  now=datetime.now()
  content=self._generate_checkpoint_content(agent.type,cp_type)
  auto_approve=self._should_auto_approve(session,agent.project_id,cp_type)
  category=get_checkpoint_category_map().get(cp_type,"document")
  from models.tables import Checkpoint
  checkpoint=Checkpoint(
   id=cp_id,
   project_id=agent.project_id,
   agent_id=agent.id,
   type=cp_type,
   title=title,
   description=f"{agent.metadata_.get('displayName',agent.type) if agent.metadata_ else agent.type}の成果物を確認してください",
   content_category=category,
   output={"type":"document","format":"markdown","content":content},
   status="approved" if auto_approve else"pending",
   resolved_at=now if auto_approve else None,
   created_at=now,
   updated_at=now
  )
  session.add(checkpoint)
  session.flush()
  if auto_approve:
   self._add_system_log_internal(session,agent.project_id,"info","System",f"自動承認: {title}")
  else:
   agent.status="waiting_approval"
   session.flush()
   self._add_system_log_internal(session,agent.project_id,"info","System",f"承認作成: {title}")
  cp_repo=CheckpointRepository(session)
  self._emit_event("checkpoint:created",{
   "checkpointId":cp_id,
   "projectId":agent.project_id,
   "agentId":agent.id,
   "checkpoint":cp_repo.to_dict(checkpoint),
   "autoApproved":auto_approve
  },agent.project_id)

 def _check_asset_generation(self,session,agent,old_progress:int,new_progress:int):
  asset_points=self._get_asset_points(agent.type)
  for point_progress,asset_type,asset_name,asset_size in asset_points:
   if old_progress<point_progress<=new_progress:
    asset_repo=AssetRepository(session)
    existing=[a for a in asset_repo.get_by_project(agent.project_id)
              if a["name"]==asset_name and a["agent"]==(agent.metadata_.get("displayName",agent.type) if agent.metadata_ else agent.type)]
    if not existing:
     self._create_asset(session,agent,asset_type,asset_name,asset_size)

 def _check_trace_generation(self,session,agent,old_progress:int,new_progress:int):
  trace_points=[20,50,80]
  for point in trace_points:
   if old_progress<point<=new_progress:
    self._create_simulation_trace(session,agent,point)

 def _create_simulation_trace(self,session,agent,progress:int):
  trace_repo=AgentTraceRepository(session)
  display_name=agent.metadata_.get("displayName",agent.type) if agent.metadata_ else agent.type
  input_tokens=random.randint(500,2000)
  output_tokens=random.randint(200,1000)
  duration_ms=random.randint(1000,5000)
  sample_prompt=f"""あなたは{display_name}エージェントです。
以下のタスクを実行してください。

## タスク
プロジェクトの{agent.type}フェーズの処理を行います。

## 入力
進捗:{progress}%
"""
  sample_response=f"""## 処理結果

{display_name}の処理が完了しました。

### 実行内容
-データ分析を実施
-結果を生成
-品質チェックを実行

### 出力
処理は正常に完了しました。次のステップに進む準備ができています。
"""
  trace_repo.create_trace(
   project_id=agent.project_id,
   agent_id=agent.id,
   agent_type=agent.type,
   input_context={"progress":progress,"phase":agent.phase},
   model_used="claude-sonnet-4-20250514 (simulation)"
  )
  traces=trace_repo.get_by_agent(agent.id)
  if traces:
   latest_trace_id=traces[0]["id"]
   trace_repo.update_prompt(latest_trace_id,sample_prompt)
   trace_repo.complete_trace(
    trace_id=latest_trace_id,
    llm_response=sample_response,
    output_data={"type":"document","progress":progress},
    tokens_input=input_tokens,
    tokens_output=output_tokens,
    status="completed"
   )

 def _should_auto_approve_asset(self,session,project_id:str,asset_type:str)->bool:
  proj_repo=ProjectRepository(session)
  project=proj_repo.get(project_id)
  if not project:
   return False
  rules=(project.config or {}).get("autoApprovalRules",[])
  if not rules:
   return False
  for rule in rules:
   if rule.get("category")==asset_type:
    return rule.get("enabled",False)
  return False

 def _create_asset(self,session,agent,asset_type:str,name:str,size:str):
  testdata_path=get_testdata_path()
  real_file=self._find_real_file(session,testdata_path,asset_type,agent.project_id)
  display_name=agent.metadata_.get("displayName",agent.type) if agent.metadata_ else agent.type
  actual_type=real_file["type"] if real_file else asset_type
  auto_approve=self._should_auto_approve_asset(session,agent.project_id,actual_type)
  approval_status="approved" if auto_approve else"pending"
  from models.tables import Asset
  if real_file:
   asset=Asset(
    id=f"asset-{uuid.uuid4().hex[:8]}",
    project_id=agent.project_id,
    name=real_file["name"],
    type=real_file["type"],
    agent=display_name,
    size=real_file["size"],
    url=real_file["url"],
    thumbnail=real_file["thumbnail"],
    duration=self._random_duration() if real_file["type"]=="audio" else None,
    approval_status=approval_status,
    created_at=datetime.now()
   )
   log_msg=f"アセット生成: {real_file['name']}"+(" (自動承認)" if auto_approve else"")
   self._add_system_log_internal(session,agent.project_id,"info",display_name,log_msg)
  else:
   url=f"/assets/{name}" if asset_type in ("image","audio") else None
   thumbnail=f"/thumbnails/{name}" if asset_type=="image" else None
   asset=Asset(
    id=f"asset-{uuid.uuid4().hex[:8]}",
    project_id=agent.project_id,
    name=name,
    type=asset_type,
    agent=display_name,
    size=size,
    url=url,
    thumbnail=thumbnail,
    duration=self._random_duration() if asset_type=="audio" else None,
    approval_status=approval_status,
    created_at=datetime.now()
   )
   log_msg=f"アセット生成: {name}"+(" (自動承認)" if auto_approve else"")
   self._add_system_log_internal(session,agent.project_id,"info",display_name,log_msg)
  session.add(asset)
  session.flush()
  asset_repo=AssetRepository(session)
  self._emit_event("asset:created",{
   "projectId":agent.project_id,
   "asset":asset_repo.to_dict(asset),
   "autoApproved":auto_approve
  },agent.project_id)

 def _find_real_file(self,session,testdata_path:str,asset_type:str,project_id:str)->Optional[Dict]:
  subdir_map={"image":"image","audio":"mp3","video":"movie"}
  subdir=subdir_map.get(asset_type)
  if not subdir:
   return None
  scan_path=os.path.join(testdata_path,subdir)
  if not os.path.exists(scan_path):
   return None
  all_files=[]
  for root,dirs,files in os.walk(scan_path):
   for filename in files:
    file_path=os.path.join(root,filename)
    relative_path=os.path.relpath(file_path,testdata_path)
    all_files.append({"path":file_path,"name":filename,"relative":relative_path.replace(os.sep,'/')})
  if not all_files:
   return None
  asset_repo=AssetRepository(session)
  used_files=set(a["url"] for a in asset_repo.get_by_project(project_id) if a.get("url"))
  available=[f for f in all_files if f"/testdata/{f['relative']}" not in used_files]
  if not available:
   available=all_files
  chosen=random.choice(available)
  try:
   stat=os.stat(chosen["path"])
   from asset_scanner import format_file_size,get_file_type
   file_type=get_file_type(chosen["name"])
   return {
    "name":chosen["name"],
    "type":file_type,
    "size":format_file_size(stat.st_size),
    "url":f"/testdata/{chosen['relative']}",
    "thumbnail":f"/testdata/{chosen['relative']}" if file_type=="image" else None
   }
  except Exception as e:
   get_logger().debug(f"Error reading file stat: {chosen['path']}: {e}")
   return None

 def _random_duration(self)->str:
  seconds=random.randint(5,180)
  mins=seconds//60
  secs=seconds%60
  return f"{mins}:{secs:02d}"

 def _get_asset_points(self,agent_type:str)->List[tuple]:
  assets=get_agent_assets(agent_type)
  return [(a.get("progress",0),a.get("type","document"),a.get("name",""),a.get("size","")) for a in assets]

 def _get_checkpoint_points(self,agent_type:str)->List[tuple]:
  checkpoints=get_agent_checkpoints(agent_type)
  return [(c.get("progress",90),c.get("type","review"),c.get("title","レビュー")) for c in checkpoints]

 def _generate_checkpoint_content(self,agent_type:str,cp_type:str)->str:
  return get_checkpoint_content(cp_type)

 def _add_agent_log_internal(self,session,agent_id:str,level:str,message:str,progress:int=None):
  repo=AgentLogRepository(session)
  repo.add_log(agent_id,level,message,progress)

 def _add_system_log_internal(self,session,project_id:str,level:str,source:str,message:str):
  repo=SystemLogRepository(session)
  repo.add_log(project_id,level,source,message)

 def _get_generation_type(self,agent_type:str)->str:
  return get_generation_type_for_agent(agent_type)

 def _calculate_generation_counts(self,agents:List[Dict])->Dict:
  counts={
   "characters":{"count":0,"unit":"体","calls":0},
   "backgrounds":{"count":0,"unit":"枚","calls":0},
   "ui":{"count":0,"unit":"点","calls":0},
   "effects":{"count":0,"unit":"種","calls":0},
   "music":{"count":0,"unit":"曲","calls":0},
   "sfx":{"count":0,"unit":"個","calls":0},
   "voice":{"count":0,"unit":"件","calls":0},
   "video":{"count":0,"unit":"本","calls":0},
   "scenarios":{"count":0,"unit":"本","calls":0},
   "code":{"count":0,"unit":"行","calls":0},
   "documents":{"count":0,"unit":"件","calls":0},
  }
  for agent in agents:
   if agent["status"] not in ["completed","waiting_approval"]:
    continue
   progress_factor=agent["progress"]/100.0
   agent_type=agent["type"]
   if agent_type=="asset_character":
    counts["characters"]["count"]+=int(random.randint(3,8)*progress_factor)
    counts["characters"]["calls"]+=int(random.randint(2,5)*progress_factor)
   elif agent_type=="asset_background":
    counts["backgrounds"]["count"]+=int(random.randint(3,6)*progress_factor)
    counts["backgrounds"]["calls"]+=int(random.randint(2,4)*progress_factor)
   elif agent_type=="asset_ui":
    counts["ui"]["count"]+=int(random.randint(5,15)*progress_factor)
    counts["ui"]["calls"]+=int(random.randint(3,8)*progress_factor)
   elif agent_type=="asset_effect":
    counts["effects"]["count"]+=int(random.randint(3,10)*progress_factor)
    counts["effects"]["calls"]+=int(random.randint(2,5)*progress_factor)
   elif agent_type=="asset_bgm":
    counts["music"]["count"]+=int(random.randint(2,5)*progress_factor)
    counts["music"]["calls"]+=int(random.randint(1,3)*progress_factor)
   elif agent_type=="asset_sfx":
    counts["sfx"]["count"]+=int(random.randint(10,25)*progress_factor)
    counts["sfx"]["calls"]+=int(random.randint(5,15)*progress_factor)
   elif agent_type=="asset_voice":
    counts["voice"]["count"]+=int(random.randint(20,50)*progress_factor)
    counts["voice"]["calls"]+=int(random.randint(10,30)*progress_factor)
   elif agent_type in ["code","event","ui_integration","asset_integration"]:
    counts["code"]["count"]+=int(random.randint(200,800)*progress_factor)
    counts["code"]["calls"]+=int(random.randint(5,15)*progress_factor)
   elif agent_type=="scenario":
    counts["scenarios"]["count"]+=int(random.randint(1,3)*progress_factor)
    counts["scenarios"]["calls"]+=int(random.randint(2,5)*progress_factor)
   elif agent_type in ["concept","concept_detail","game_design","tech_spec","world"]:
    counts["documents"]["count"]+=int(random.randint(1,3)*progress_factor)
    counts["documents"]["calls"]+=int(random.randint(3,8)*progress_factor)
  return counts

 def _update_project_metrics(self,session,project_id:str):
  agent_repo=AgentRepository(session)
  proj_repo=ProjectRepository(session)
  metrics_repo=MetricsRepository(session)
  agents=agent_repo.get_by_project(project_id)
  project=proj_repo.get(project_id)
  if not project:
   return
  total_input=sum(a.get("inputTokens",0) for a in agents)
  total_output=sum(a.get("outputTokens",0) for a in agents)
  completed_count=len([a for a in agents if a["status"]=="completed"])
  total_count=len(agents)
  total_progress=sum(a["progress"] for a in agents)
  overall_progress=int(total_progress/total_count) if total_count>0 else 0
  tokens_by_type={}
  for agent in agents:
   gen_type=self._get_generation_type(agent["type"])
   if gen_type not in tokens_by_type:
    tokens_by_type[gen_type]={"input":0,"output":0}
   tokens_by_type[gen_type]["input"]+=agent.get("inputTokens",0)
   tokens_by_type[gen_type]["output"]+=agent.get("outputTokens",0)
  running_agent=next((a for a in agents if a["status"]=="running"),None)
  estimated_remaining=0
  if running_agent and running_agent["progress"]>0:
   elapsed=(datetime.now()-datetime.fromisoformat(running_agent["startedAt"])).total_seconds()
   rate=running_agent["progress"]/elapsed if elapsed>0 else 1
   remaining_progress=100-running_agent["progress"]
   remaining_agents=len([a for a in agents if a["status"]=="pending"])
   estimated_remaining=(remaining_progress/rate)+(remaining_agents*100/rate) if rate>0 else 0
  active_generations=len([a for a in agents if a["status"]=="running"])
  generation_counts=self._calculate_generation_counts(agents)
  metrics_data={
   "projectId":project_id,
   "totalTokensUsed":total_input+total_output,
   "totalInputTokens":total_input,
   "totalOutputTokens":total_output,
   "estimatedTotalTokens":50000,
   "tokensByType":tokens_by_type,
   "generationCounts":generation_counts,
   "elapsedTimeSeconds":int((datetime.now()-project.created_at).total_seconds()),
   "estimatedRemainingSeconds":int(estimated_remaining),
   "estimatedEndTime":(datetime.now()+timedelta(seconds=estimated_remaining)).isoformat() if estimated_remaining>0 else None,
   "completedTasks":completed_count,
   "totalTasks":total_count,
   "progressPercent":overall_progress,
   "currentPhase":project.current_phase,
   "phaseName":f"Phase {project.current_phase}",
   "activeGenerations":active_generations
  }
  metrics_repo.create_or_update(project_id,metrics_data)
  self._emit_event("metrics:update",{"projectId":project_id,"metrics":metrics_data},project_id)

 def get_projects(self)->List[Dict]:
  with session_scope() as session:
   repo=ProjectRepository(session)
   return repo.get_all_dict()

 def get_project(self,project_id:str)->Optional[Dict]:
  with session_scope() as session:
   repo=ProjectRepository(session)
   return repo.get_dict(project_id)

 def create_project(self,data:Dict)->Dict:
  with session_scope() as session:
   repo=ProjectRepository(session)
   if"aiServices" not in data or not data["aiServices"]:
    data["aiServices"]=dict(build_default_ai_services())
   project=repo.create_from_dict(data)
   syslog_repo=SystemLogRepository(session)
   syslog_repo.add_log(project["id"],"info","System","プロジェクト作成")
   return project

 def update_project(self,project_id:str,data:Dict)->Optional[Dict]:
  with session_scope() as session:
   repo=ProjectRepository(session)
   return repo.update_from_dict(project_id,data)

 def delete_project(self,project_id:str)->bool:
  with session_scope() as session:
   repo=ProjectRepository(session)
   return repo.delete(project_id)

 def start_project(self,project_id:str)->Optional[Dict]:
  with session_scope() as session:
   repo=ProjectRepository(session)
   p=repo.get(project_id)
   if not p:
    return None
   if p.status in ("draft","paused"):
    p.status="running"
    p.updated_at=datetime.now()
    session.flush()
    self._add_system_log_internal(session,project_id,"info","System","プロジェクト開始")
   return repo.to_dict(p)

 def pause_project(self,project_id:str)->Optional[Dict]:
  with session_scope() as session:
   repo=ProjectRepository(session)
   p=repo.get(project_id)
   if not p:
    return None
   if p.status=="running":
    p.status="paused"
    p.updated_at=datetime.now()
    session.flush()
    self._add_system_log_internal(session,project_id,"info","System","プロジェクト一時停止")
   return repo.to_dict(p)

 def resume_project(self,project_id:str)->Optional[Dict]:
  with session_scope() as session:
   repo=ProjectRepository(session)
   p=repo.get(project_id)
   if not p:
    return None
   if p.status=="paused":
    p.status="running"
    p.updated_at=datetime.now()
    session.flush()
    self._add_system_log_internal(session,project_id,"info","System","プロジェクト再開")
   return repo.to_dict(p)

 def initialize_project(self,project_id:str)->Optional[Dict]:
  with session_scope() as session:
   proj_repo=ProjectRepository(session)
   agent_repo=AgentRepository(session)
   cp_repo=CheckpointRepository(session)
   syslog_repo=SystemLogRepository(session)
   asset_repo=AssetRepository(session)
   metrics_repo=MetricsRepository(session)
   project=proj_repo.get(project_id)
   if not project:
    return None
   now=datetime.now()
   project.status="draft"
   project.current_phase=1
   project.updated_at=now
   agent_repo.delete_by_project(project_id)
   cp_repo.delete_by_project(project_id)
   syslog_repo.delete_by_project(project_id)
   asset_repo.delete_by_project(project_id)
   agents_data=[
    {"type":"concept","name":"コンセプト","phase":0},
    {"type":"task_split_1","name":"タスク分割1","phase":1},
    {"type":"concept_detail","name":"コンセプト詳細","phase":2},
    {"type":"scenario","name":"シナリオ","phase":2},
    {"type":"world","name":"世界観","phase":2},
    {"type":"game_design","name":"ゲームデザイン","phase":2},
    {"type":"tech_spec","name":"技術仕様","phase":2},
    {"type":"task_split_2","name":"タスク分割2","phase":3},
    {"type":"asset_character","name":"キャラ","phase":4},
    {"type":"asset_background","name":"背景","phase":4},
    {"type":"asset_ui","name":"UI","phase":4},
    {"type":"asset_effect","name":"エフェクト","phase":4},
    {"type":"asset_bgm","name":"BGM","phase":4},
    {"type":"asset_voice","name":"ボイス","phase":4},
    {"type":"asset_sfx","name":"効果音","phase":4},
    {"type":"task_split_3","name":"タスク分割3","phase":5},
    {"type":"code","name":"コード","phase":6},
    {"type":"event","name":"イベント","phase":6},
    {"type":"ui_integration","name":"UI統合","phase":6},
    {"type":"asset_integration","name":"アセット統合","phase":6},
    {"type":"task_split_4","name":"タスク分割4","phase":7},
    {"type":"unit_test","name":"単体テスト","phase":8},
    {"type":"integration_test","name":"統合テスト","phase":8},
   ]
   for data in agents_data:
    agent_repo.create_from_dict(project_id,{"type":data["type"],"phase":data["phase"],"metadata":{"displayName":data["name"]}})
   metrics_repo.create_or_update(project_id,{
    "totalTokensUsed":0,"estimatedTotalTokens":50000,"elapsedTimeSeconds":0,
    "estimatedRemainingSeconds":0,"completedTasks":0,"totalTasks":6,
    "progressPercent":0,"currentPhase":1,"phaseName":"Phase 1: 企画・設計","activeGenerations":0
   })
   self._add_system_log_internal(session,project_id,"info","System","プロジェクト初期化完了")
   get_logger().info(f"Project {project_id} initialized")
   return proj_repo.to_dict(project)

 def brushup_project(self,project_id:str,options:Optional[Dict]=None)->Optional[Dict]:
  with session_scope() as session:
   proj_repo=ProjectRepository(session)
   agent_repo=AgentRepository(session)
   project=proj_repo.get(project_id)
   if not project or project.status!="completed":
    return None
   opts=options or {}
   selected_agents:List[str]=opts.get("selectedAgents",[])
   presets:List[str]=opts.get("presets",[])
   custom_instruction:str=opts.get("customInstruction","")
   reference_image_ids:List[str]=opts.get("referenceImageIds",[])
   project.status="draft"
   project.current_phase=1
   project.updated_at=datetime.now()
   if presets or custom_instruction or reference_image_ids:
    brushup_config={
     "presets":presets,
     "customInstruction":custom_instruction,
     "referenceImageIds":reference_image_ids
    }
    if project.config:
     import json
     config=json.loads(project.config) if isinstance(project.config,str) else project.config
     config["brushupConfig"]=brushup_config
     project.config=json.dumps(config) if isinstance(project.config,str) else config
   agents=agent_repo.get_by_project(project_id)
   for agent_dict in agents:
    should_reset=len(selected_agents)==0 or agent_dict["type"] in selected_agents
    if should_reset:
     agent=agent_repo.get(agent_dict["id"])
     agent.status="pending"
     agent.progress=0
     agent.current_task=None
     agent.started_at=None
     agent.completed_at=None
     agent.error=None
   session.flush()
   agent_names=",".join(selected_agents) if selected_agents else"全エージェント"
   preset_names=",".join(presets) if presets else"なし"
   log_msg=f"ブラッシュアップ開始: エージェント={agent_names}, プリセット={preset_names}"
   if custom_instruction:
    log_msg+=f", カスタム指示あり"
   self._add_system_log_internal(session,project_id,"info","System",log_msg)
   get_logger().info(f"Project {project_id} brushup started: {agent_names}")
   return proj_repo.to_dict(project)

 def get_agents_by_project(self,project_id:str,include_workers:bool=True)->List[Dict]:
  with session_scope() as session:
   repo=AgentRepository(session)
   return repo.get_by_project(project_id,include_workers=include_workers)

 def get_workers_by_parent(self,parent_agent_id:str)->List[Dict]:
  with session_scope() as session:
   repo=AgentRepository(session)
   return repo.get_workers_by_parent(parent_agent_id)

 def get_agent(self,agent_id:str)->Optional[Dict]:
  with session_scope() as session:
   repo=AgentRepository(session)
   return repo.get_dict(agent_id)

 def get_agent_logs(self,agent_id:str)->List[Dict]:
  with session_scope() as session:
   repo=AgentLogRepository(session)
   return repo.get_by_agent(agent_id)

 def create_agent(self,project_id:str,agent_type:str)->Dict:
  with session_scope() as session:
   repo=AgentRepository(session)
   return repo.create_from_dict(project_id,{"type":agent_type})

 def create_worker_agent(self,project_id:str,parent_agent_id:str,worker_type:str,task:str)->Dict:
  with session_scope() as session:
   repo=AgentRepository(session)
   return repo.create_worker(project_id,parent_agent_id,worker_type,task)

 def update_agent(self,agent_id:str,data:Dict)->Optional[Dict]:
  with session_scope() as session:
   repo=AgentRepository(session)
   return repo.update_from_dict(agent_id,data)

 def add_agent_log(self,agent_id:str,level:str,message:str,progress:Optional[int]=None):
  with session_scope() as session:
   repo=AgentLogRepository(session)
   repo.add_log(agent_id,level,message,progress)

 def get_checkpoints_by_project(self,project_id:str)->List[Dict]:
  with session_scope() as session:
   repo=CheckpointRepository(session)
   return repo.get_by_project(project_id)

 def get_checkpoint(self,checkpoint_id:str)->Optional[Dict]:
  with session_scope() as session:
   repo=CheckpointRepository(session)
   return repo.get_dict(checkpoint_id)

 def create_checkpoint(self,project_id:str,agent_id:str,data:Dict)->Dict:
  with session_scope() as session:
   repo=CheckpointRepository(session)
   return repo.create_from_dict({**data,"projectId":project_id,"agentId":agent_id})

 def resolve_checkpoint(self,checkpoint_id:str,resolution:str,feedback:Optional[str]=None)->Optional[Dict]:
  with session_scope() as session:
   cp_repo=CheckpointRepository(session)
   agent_repo=AgentRepository(session)
   cp=cp_repo.get(checkpoint_id)
   if not cp:
    return None
   result=cp_repo.resolve(checkpoint_id,resolution,feedback)
   project_id=cp.project_id
   status_text={"approved":"承認","rejected":"却下","revision_requested":"修正要求"}
   self._add_system_log_internal(session,project_id,"info","System",f"チェックポイント{status_text.get(resolution,resolution)}: {cp.title}")
   agent=agent_repo.get(cp.agent_id)
   if agent:
    if resolution=="rejected":
     agent.status="failed"
     agent.current_task="却下により中止"
     session.flush()
     self._add_system_log_internal(session,project_id,"warn","System",f"{agent.type}が却下されました")
     self._emit_event("agent:failed",{"agentId":agent.id,"projectId":project_id,"reason":"rejected"},project_id)
    elif resolution=="revision_requested":
     cp_repo.delete(checkpoint_id)
     agent.progress=80
     agent.status="running"
     agent.current_task="修正中..."
     session.flush()
     self._add_system_log_internal(session,project_id,"info","System",f"{agent.type}が修正を開始")
     self._emit_event("agent:progress",{
      "agentId":agent.id,
      "projectId":project_id,
      "progress":80,
      "currentTask":"修正中...",
      "tokensUsed":agent.tokens_used,
      "message":"修正要求により再実行"
     },project_id)
    else:
     other_pending=cp_repo.get_pending_by_agent(cp.agent_id)
     other_pending=[c for c in other_pending if c.id!=checkpoint_id]
     if not other_pending and agent.status=="waiting_approval":
      agent.status="completed"
      agent.progress=100
      agent.completed_at=datetime.now()
      agent.current_task=None
      session.flush()
      self._add_system_log_internal(session,project_id,"info","System",f"{agent.type}が承認されました")
      self._emit_event("agent:completed",{
       "agentId":agent.id,
       "projectId":project_id,
      },project_id)
   if resolution=="approved":
    self._check_phase_advancement(session,project_id)
   return result

 def _check_phase_advancement(self,session,project_id:str):
  proj_repo=ProjectRepository(session)
  cp_repo=CheckpointRepository(session)
  project=proj_repo.get(project_id)
  if not project:
   return
  current_phase=project.current_phase
  project_checkpoints=cp_repo.get_by_project(project_id)
  phase1_types={"concept_review","task_review_1","concept_detail_review","scenario_review","world_review","game_design_review","tech_spec_review"}
  if current_phase==1:
   phase1_checkpoints=[c for c in project_checkpoints if c["type"] in phase1_types]
   if phase1_checkpoints and all(c["status"]=="approved" for c in phase1_checkpoints):
    project.current_phase=2
    project.updated_at=datetime.now()
    session.flush()
    self._add_system_log_internal(session,project_id,"info","System","Phase 2: 実装 に移行しました")
    get_logger().info(f"Project {project_id} advanced to Phase 2")

 def get_system_logs(self,project_id:str)->List[Dict]:
  with session_scope() as session:
   repo=SystemLogRepository(session)
   return repo.get_by_project(project_id)

 def get_assets_by_project(self,project_id:str)->List[Dict]:
  with session_scope() as session:
   repo=AssetRepository(session)
   return repo.get_by_project(project_id)

 def update_asset(self,project_id:str,asset_id:str,data:Dict)->Optional[Dict]:
  with session_scope() as session:
   repo=AssetRepository(session)
   return repo.update_from_dict(project_id,asset_id,data)

 def get_project_metrics(self,project_id:str)->Optional[Dict]:
  with session_scope() as session:
   repo=MetricsRepository(session)
   return repo.get(project_id)

 def update_project_metrics(self,project_id:str,data:Dict)->Dict:
  with session_scope() as session:
   repo=MetricsRepository(session)
   return repo.create_or_update(project_id,data)

 def add_subscription(self,project_id:str,sid:str):
  with self._lock:
   if project_id not in self.subscriptions:
    self.subscriptions[project_id]=set()
   self.subscriptions[project_id].add(sid)

 def remove_subscription(self,project_id:str,sid:str):
  with self._lock:
   if project_id in self.subscriptions:
    self.subscriptions[project_id].discard(sid)

 def remove_all_subscriptions(self,sid:str):
  with self._lock:
   for project_id in self.subscriptions:
    self.subscriptions[project_id].discard(sid)

 def get_subscribers(self,project_id:str)->set:
  with self._lock:
   return self.subscriptions.get(project_id,set()).copy()

 def get_quality_settings(self,project_id:str)->Dict[str,QualityCheckConfig]:
  with session_scope() as session:
   repo=QualitySettingsRepository(session)
   return repo.get_all(project_id)

 def set_quality_setting(self,project_id:str,agent_type:str,config:QualityCheckConfig)->None:
  with session_scope() as session:
   repo=QualitySettingsRepository(session)
   repo.set(project_id,agent_type,config)

 def reset_quality_settings(self,project_id:str)->None:
  with session_scope() as session:
   repo=QualitySettingsRepository(session)
   repo.reset(project_id)

 def get_quality_setting_for_agent(self,project_id:str,agent_type:str)->QualityCheckConfig:
  settings=self.get_quality_settings(project_id)
  return settings.get(agent_type,QualityCheckConfig())

 def get_interventions_by_project(self,project_id:str)->List[Dict]:
  with session_scope() as session:
   repo=InterventionRepository(session)
   return repo.get_by_project(project_id)

 def get_intervention(self,intervention_id:str)->Optional[Dict]:
  with session_scope() as session:
   repo=InterventionRepository(session)
   return repo.get_dict(intervention_id)

 def create_intervention(self,project_id:str,target_type:str,target_agent_id:Optional[str],priority:str,message:str,attached_file_ids:List[str])->Dict:
  with session_scope() as session:
   repo=InterventionRepository(session)
   intervention=repo.create_from_dict({
    "projectId":project_id,"targetType":target_type,"targetAgentId":target_agent_id,
    "priority":priority,"message":message,"attachedFileIds":attached_file_ids
   })
   target_desc="全エージェント" if target_type=="all" else f"エージェント {target_agent_id}"
   priority_desc="緊急" if priority=="urgent" else"通常"
   self._add_system_log_internal(session,project_id,"info","Human",f"[{priority_desc}] {target_desc}への介入: {message[:50]}...")
   return intervention

 def acknowledge_intervention(self,intervention_id:str)->Optional[Dict]:
  with session_scope() as session:
   repo=InterventionRepository(session)
   return repo.acknowledge(intervention_id)

 def process_intervention(self,intervention_id:str)->Optional[Dict]:
  with session_scope() as session:
   repo=InterventionRepository(session)
   intervention=repo.process(intervention_id)
   if intervention:
    self._add_system_log_internal(session,intervention["projectId"],"info","System",f"介入処理完了: {intervention['message'][:30]}...")
   return intervention

 def deliver_intervention(self,intervention_id:str)->Optional[Dict]:
  with session_scope() as session:
   repo=InterventionRepository(session)
   return repo.deliver(intervention_id)

 def delete_intervention(self,intervention_id:str)->bool:
  with session_scope() as session:
   repo=InterventionRepository(session)
   intervention=repo.get(intervention_id)
   if not intervention:
    return False
   project_id=intervention.project_id
   result=repo.delete(intervention_id)
   if result:
    self._add_system_log_internal(session,project_id,"info","System",f"介入削除: {intervention.message[:30]}...")
   return result

 def activate_agent_for_intervention(self,agent_id:str,intervention_id:str)->Dict:
  with session_scope() as session:
   agent_repo=AgentRepository(session)
   syslog_repo=SystemLogRepository(session)
   intervention_repo=InterventionRepository(session)
   agent=agent_repo.get(agent_id)
   if not agent:
    return {"activated":False,"reason":"agent_not_found"}
   intervention=intervention_repo.get(intervention_id)
   if not intervention:
    return {"activated":False,"reason":"intervention_not_found"}
   activatable_statuses={"completed","failed","cancelled","paused","pending"}
   display_name=agent.metadata_.get("displayName",agent.type) if agent.metadata_ else agent.type
   if agent.status in activatable_statuses:
    old_status=agent.status
    agent.status="running"
    agent.current_task=f"追加タスク: {intervention.message[:30]}..."
    agent.updated_at=datetime.now()
    if not agent.started_at:
     agent.started_at=datetime.now()
    session.flush()
    syslog_repo.add_log(agent.project_id,"info","System",f"エージェント {display_name} を連絡により起動（前状態: {old_status}）")
    paused_agents=self._pause_subsequent_agents(session,agent)
    return {
     "activated":True,
     "agent":agent_repo.to_dict(agent),
     "previousStatus":old_status,
     "pausedAgents":paused_agents
    }
   elif agent.status=="running":
    return {"activated":False,"reason":"already_running","agent":agent_repo.to_dict(agent)}
   elif agent.status=="waiting_approval":
    return {"activated":False,"reason":"waiting_approval","agent":agent_repo.to_dict(agent)}
   elif agent.status=="waiting_response":
    agent.status="running"
    agent.current_task=f"追加タスク: {intervention.message[:30]}..."
    agent.updated_at=datetime.now()
    session.flush()
    syslog_repo.add_log(agent.project_id,"info","System",f"エージェント {display_name} が返答を受けて再開")
    return {"activated":True,"agent":agent_repo.to_dict(agent),"previousStatus":"waiting_response","pausedAgents":[]}
   return {"activated":False,"reason":"invalid_status","currentStatus":agent.status}

 def _pause_subsequent_agents(self,session,target_agent)->List[Dict]:
  agent_repo=AgentRepository(session)
  syslog_repo=SystemLogRepository(session)
  agents=agent_repo.get_by_project(target_agent.project_id)
  target_phase=target_agent.phase or 0
  paused_agents=[]
  for agent_dict in agents:
   agent_phase=agent_dict.get("phase",0)
   if agent_phase>target_phase and agent_dict["status"]=="running":
    agent=agent_repo.get(agent_dict["id"])
    agent.status="paused"
    agent.updated_at=datetime.now()
    session.flush()
    display_name=agent.metadata_.get("displayName",agent.type) if agent.metadata_ else agent.type
    syslog_repo.add_log(agent.project_id,"info","System",f"エージェント {display_name} を後続フェーズとして一時停止")
    paused_agents.append(agent_repo.to_dict(agent))
  return paused_agents

 def get_pending_interventions_for_agent(self,agent_id:str)->List[Dict]:
  with session_scope() as session:
   intervention_repo=InterventionRepository(session)
   agent_repo=AgentRepository(session)
   agent=agent_repo.get(agent_id)
   if not agent:
    return []
   all_interventions=intervention_repo.get_by_project(agent.project_id)
   pending_interventions=[]
   for iv in all_interventions:
    if iv["status"] not in ("pending","acknowledged"):
     continue
    if iv["targetType"]=="all":
     pending_interventions.append(iv)
    elif iv["targetType"]=="specific" and iv.get("targetAgentId")==agent_id:
     pending_interventions.append(iv)
   return pending_interventions

 def add_intervention_response(self,intervention_id:str,sender:str,message:str,agent_id:str=None)->Optional[Dict]:
  with session_scope() as session:
   intervention_repo=InterventionRepository(session)
   agent_repo=AgentRepository(session)
   syslog_repo=SystemLogRepository(session)
   intervention=intervention_repo.get(intervention_id)
   if not intervention:
    return None
   result=intervention_repo.add_response(intervention_id,sender,message,agent_id)
   if sender=="agent" and agent_id:
    agent=agent_repo.get(agent_id)
    if agent:
     agent.status="waiting_response"
     agent.current_task="オペレーターの返答待ち"
     agent.updated_at=datetime.now()
     session.flush()
     display_name=agent.metadata_.get("displayName",agent.type) if agent.metadata_ else agent.type
     syslog_repo.add_log(intervention.project_id,"info",display_name,f"質問: {message[:50]}...")
   elif sender=="operator":
    syslog_repo.add_log(intervention.project_id,"info","Human",f"返答: {message[:50]}...")
   return result

 def respond_to_intervention(self,intervention_id:str,message:str)->Optional[Dict]:
  with session_scope() as session:
   intervention_repo=InterventionRepository(session)
   agent_repo=AgentRepository(session)
   syslog_repo=SystemLogRepository(session)
   intervention=intervention_repo.get(intervention_id)
   if not intervention:
    return None
   result=intervention_repo.add_response(intervention_id,"operator",message)
   if intervention.target_agent_id:
    agent=agent_repo.get(intervention.target_agent_id)
    if agent and agent.status=="waiting_response":
     agent.status="running"
     agent.current_task=f"返答を受けて処理再開"
     agent.updated_at=datetime.now()
     session.flush()
     display_name=agent.metadata_.get("displayName",agent.type) if agent.metadata_ else agent.type
     syslog_repo.add_log(intervention.project_id,"info","System",f"エージェント {display_name} が返答を受けて再開")
   if result:
    intervention_repo.set_status(intervention_id,"acknowledged")
   return result

 def get_uploaded_files_by_project(self,project_id:str)->List[Dict]:
  with session_scope() as session:
   repo=UploadedFileRepository(session)
   return repo.get_by_project(project_id)

 def get_uploaded_file(self,file_id:str)->Optional[Dict]:
  with session_scope() as session:
   repo=UploadedFileRepository(session)
   return repo.get_dict(file_id)

 def create_uploaded_file(self,project_id:str,filename:str,original_filename:str,mime_type:str,category:str,size_bytes:int,description:str)->Dict:
  with session_scope() as session:
   repo=UploadedFileRepository(session)
   uf=repo.create_from_dict({
    "projectId":project_id,"filename":filename,"originalFilename":original_filename,
    "mimeType":mime_type,"category":category,"sizeBytes":size_bytes,"description":description
   })
   self._add_system_log_internal(session,project_id,"info","Upload",f"ファイルアップロード: {original_filename} ({category})")
   return uf

 def delete_uploaded_file(self,file_id:str)->bool:
  with session_scope() as session:
   repo=UploadedFileRepository(session)
   return repo.delete(file_id)

 def update_uploaded_file(self,file_id:str,data:Dict)->Optional[Dict]:
  with session_scope() as session:
   repo=UploadedFileRepository(session)
   return repo.update_from_dict(file_id,data)

 def get_auto_approval_rules(self,project_id:str)->List[Dict]:
  with session_scope() as session:
   repo=ProjectRepository(session)
   project=repo.get(project_id)
   if not project:
    return []
   return (project.config or {}).get("autoApprovalRules",get_config_auto_approval_rules())

 def set_auto_approval_rules(self,project_id:str,rules:List[Dict])->List[Dict]:
  with session_scope() as session:
   repo=ProjectRepository(session)
   project=repo.get(project_id)
   if not project:
    return []
   config=dict(project.config or {})
   config["autoApprovalRules"]=rules
   project.config=config
   flag_modified(project,"config")
   project.updated_at=datetime.now()
   session.flush()
   self._auto_approve_pending_checkpoints(session,project_id,rules)
   self._auto_approve_pending_assets(session,project_id,rules)
   return rules

 def _auto_approve_pending_checkpoints(self,session,project_id:str,rules:List[Dict]):
  enabled_categories={r["category"] for r in rules if r.get("enabled")}
  if not enabled_categories:
   return
  category_map=get_checkpoint_category_map()
  from models.tables import Checkpoint
  pending_cps=session.query(Checkpoint).filter(
   Checkpoint.project_id==project_id,
   Checkpoint.status=="pending"
  ).all()
  cp_repo=CheckpointRepository(session)
  agent_repo=AgentRepository(session)
  now=datetime.now()
  for cp in pending_cps:
   cp_category=category_map.get(cp.type,"document")
   if cp_category in enabled_categories:
    cp.status="approved"
    cp.resolved_at=now
    cp.updated_at=now
    session.flush()
    self._add_system_log_internal(session,project_id,"info","System",f"自動承認(設定変更): {cp.title}")
    self._emit_event("checkpoint:resolved",{
     "checkpointId":cp.id,
     "projectId":project_id,
     "checkpoint":cp_repo.to_dict(cp),
     "resolution":"approved"
    },project_id)
    agent=agent_repo.get(cp.agent_id)
    if agent and agent.status=="waiting_approval":
     other_pending=cp_repo.get_pending_by_agent(cp.agent_id)
     if not other_pending:
      agent.status="running"
      session.flush()

 def _auto_approve_pending_assets(self,session,project_id:str,rules:List[Dict]):
  enabled_categories={r["category"] for r in rules if r.get("enabled")}
  if not enabled_categories:
   return
  from models.tables import Asset
  pending_assets=session.query(Asset).filter(
   Asset.project_id==project_id,
   Asset.approval_status=="pending"
  ).all()
  asset_repo=AssetRepository(session)
  for asset in pending_assets:
   if asset.type in enabled_categories:
    asset.approval_status="approved"
    session.flush()
    self._add_system_log_internal(session,project_id,"info","System",f"アセット自動承認(設定変更): {asset.name}")
    self._emit_event("asset:updated",{
     "projectId":project_id,
     "asset":asset_repo.to_dict(asset),
     "autoApproved":True
    },project_id)

 def get_ai_services(self,project_id:str)->Dict[str,Dict]:
  with session_scope() as session:
   repo=ProjectRepository(session)
   project=repo.get(project_id)
   if not project:
    return {}
   return project.ai_services or dict(build_default_ai_services())

 def update_ai_service(self,project_id:str,service_type:str,config:Dict)->Optional[Dict]:
  with session_scope() as session:
   repo=ProjectRepository(session)
   project=repo.get(project_id)
   if not project:
    return None
   ai_services=dict(project.ai_services or build_default_ai_services())
   if service_type not in ai_services:
    return None
   ai_services[service_type]=dict(ai_services[service_type])
   ai_services[service_type].update(config)
   project.ai_services=ai_services
   flag_modified(project,"ai_services")
   project.updated_at=datetime.now()
   session.flush()
   return ai_services[service_type]

 def update_ai_services(self,project_id:str,ai_services:Dict[str,Dict])->Optional[Dict]:
  with session_scope() as session:
   repo=ProjectRepository(session)
   project=repo.get(project_id)
   if not project:
    return None
   project.ai_services=ai_services
   flag_modified(project,"ai_services")
   project.updated_at=datetime.now()
   session.flush()
   return project.ai_services

 @property
 def agents(self)->Dict[str,Dict]:
  result={}
  with session_scope() as session:
   repo=AgentRepository(session)
   for agent in repo.get_all():
    result[agent.id]=repo.to_dict(agent)
  return result

 @property
 def checkpoints(self)->Dict[str,Dict]:
  result={}
  with session_scope() as session:
   repo=CheckpointRepository(session)
   for cp in session.query(repo.model).all():
    result[cp.id]=repo.to_dict(cp)
  return result

 def get_traces_by_project(self,project_id:str,limit:int=100)->List[Dict]:
  with session_scope() as session:
   repo=AgentTraceRepository(session)
   return repo.get_by_project(project_id,limit)

 def get_traces_by_agent(self,agent_id:str)->List[Dict]:
  with session_scope() as session:
   repo=AgentTraceRepository(session)
   return repo.get_by_agent(agent_id)

 def retry_agent(self,agent_id:str)->Optional[Dict]:
  """
  失敗/中断/キャンセルされたAgentを再試行可能な状態にリセットする
  """
  with session_scope() as session:
   agent_repo=AgentRepository(session)
   syslog_repo=SystemLogRepository(session)
   agent=agent_repo.get(agent_id)
   if not agent:
    return None
   retryable_statuses={"failed","interrupted","cancelled"}
   if agent.status not in retryable_statuses:
    return None
   old_status=agent.status
   agent.status="pending"
   agent.progress=0
   agent.current_task=None
   agent.started_at=None
   agent.completed_at=None
   agent.error=None
   agent.updated_at=datetime.now()
   session.flush()
   display_name=agent.metadata_.get("displayName",agent.type) if agent.metadata_ else agent.type
   syslog_repo.add_log(agent.project_id,"info","System",f"エージェント {display_name} を再試行待ちに設定（前状態: {old_status}）")
   result=agent_repo.to_dict(agent)
   self._emit_event("agent:retry",{
    "agentId":agent.id,
    "projectId":agent.project_id,
    "agent":result,
    "previousStatus":old_status
   },agent.project_id)
   return result

 def pause_agent(self,agent_id:str)->Optional[Dict]:
  with session_scope() as session:
   agent_repo=AgentRepository(session)
   syslog_repo=SystemLogRepository(session)
   agent=agent_repo.get(agent_id)
   if not agent:
    return None
   pausable_statuses={"running","waiting_approval"}
   if agent.status not in pausable_statuses:
    return None
   old_status=agent.status
   agent.status="paused"
   agent.updated_at=datetime.now()
   session.flush()
   display_name=agent.metadata_.get("displayName",agent.type) if agent.metadata_ else agent.type
   syslog_repo.add_log(agent.project_id,"info","System",f"エージェント {display_name} を一時停止（前状態: {old_status}）")
   result=agent_repo.to_dict(agent)
   return result

 def resume_agent(self,agent_id:str)->Optional[Dict]:
  with session_scope() as session:
   agent_repo=AgentRepository(session)
   syslog_repo=SystemLogRepository(session)
   agent=agent_repo.get(agent_id)
   if not agent:
    return None
   resumable_statuses={"paused","waiting_response"}
   if agent.status not in resumable_statuses:
    return None
   old_status=agent.status
   agent.status="running"
   agent.updated_at=datetime.now()
   session.flush()
   display_name=agent.metadata_.get("displayName",agent.type) if agent.metadata_ else agent.type
   syslog_repo.add_log(agent.project_id,"info","System",f"エージェント {display_name} を再開（前状態: {old_status}）")
   result=agent_repo.to_dict(agent)
   return result

 def get_retryable_agents(self,project_id:str)->List[Dict]:
  """
  再試行可能なAgent（failed,interrupted,cancelled）の一覧を取得
  """
  with session_scope() as session:
   agent_repo=AgentRepository(session)
   agents=agent_repo.get_by_project(project_id)
   retryable_statuses={"failed","interrupted","cancelled"}
   return [a for a in agents if a["status"] in retryable_statuses]

 def get_interrupted_agents(self,project_id:Optional[str]=None)->List[Dict]:
  """
  中断されたAgentの一覧を取得
  """
  with session_scope() as session:
   agent_repo=AgentRepository(session)
   if project_id:
    agents=agent_repo.get_by_project(project_id)
   else:
    all_projects=ProjectRepository(session).get_all()
    agents=[]
    for p in all_projects:
     agents.extend(agent_repo.get_by_project(p.id))
   return [a for a in agents if a["status"]=="interrupted"]

 def get_trace(self,trace_id:str)->Optional[Dict]:
  with session_scope() as session:
   repo=AgentTraceRepository(session)
   trace=repo.get(trace_id)
   return repo.to_dict(trace) if trace else None

 def create_trace(self,project_id:str,agent_id:str,agent_type:str,input_context:Optional[Dict]=None,model_used:Optional[str]=None)->Dict:
  with session_scope() as session:
   repo=AgentTraceRepository(session)
   return repo.create_trace(project_id,agent_id,agent_type,input_context,model_used)

 def update_trace_prompt(self,trace_id:str,prompt:str)->Optional[Dict]:
  with session_scope() as session:
   repo=AgentTraceRepository(session)
   return repo.update_prompt(trace_id,prompt)

 def complete_trace(self,trace_id:str,llm_response:str,output_data:Optional[Dict]=None,tokens_input:int=0,tokens_output:int=0,status:str="completed",output_summary:Optional[str]=None)->Optional[Dict]:
  with session_scope() as session:
   repo=AgentTraceRepository(session)
   return repo.complete_trace(trace_id,llm_response,output_data,tokens_input,tokens_output,status,output_summary=output_summary)

 def fail_trace(self,trace_id:str,error_message:str)->Optional[Dict]:
  with session_scope() as session:
   repo=AgentTraceRepository(session)
   return repo.fail_trace(trace_id,error_message)

 def delete_traces_by_project(self,project_id:str)->int:
  with session_scope() as session:
   repo=AgentTraceRepository(session)
   return repo.delete_by_project(project_id)

 def get_llm_job(self,job_id:str)->Optional[Dict]:
  with session_scope() as session:
   repo=LlmJobRepository(session)
   job=repo.get(job_id)
   return repo.to_dict(job) if job else None

 def get_llm_jobs_by_agent(self,agent_id:str)->List[Dict]:
  with session_scope() as session:
   repo=LlmJobRepository(session)
   return repo.get_by_agent(agent_id)
