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
 QualitySettingsRepository
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
)
from asset_scanner import get_testdata_path


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
    print(f"[DataStore] Error emitting {event}: {e}")

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
  print(f"[DataStore] Sample project {proj_id} created")

 def start_simulation(self):
  if self._simulation_running:
   return
  self._simulation_running=True
  self._simulation_thread=threading.Thread(target=self._simulation_loop,daemon=True)
  self._simulation_thread.start()
  print("[Simulation] Started")

 def stop_simulation(self):
  self._simulation_running=False
  if self._simulation_thread:
   self._simulation_thread.join(timeout=2)
  print("[Simulation] Stopped")

 def _simulation_loop(self):
  while self._simulation_running:
   try:
    with self._lock:
     self._tick_simulation()
   except Exception as e:
    print(f"[Simulation] Error: {e}")
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
   status="approved" if auto_approve else "pending",
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
  approval_status="approved" if auto_approve else "pending"
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
   log_msg=f"アセット生成: {real_file['name']}" + (" (自動承認)" if auto_approve else "")
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
   log_msg=f"アセット生成: {name}" + (" (自動承認)" if auto_approve else "")
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
  except Exception:
   return None

 def _random_duration(self)->str:
  seconds=random.randint(5,180)
  mins=seconds//60
  secs=seconds%60
  return f"{mins}:{secs:02d}"

 def _get_asset_points(self,agent_type:str)->List[tuple]:
  assets={
   "concept":[(50,"document","concept_draft.md","12KB"),(90,"document","concept_final.md","28KB")],
   "task_split_1":[(50,"document","task_breakdown.md","25KB"),(90,"document","iteration_plan.md","35KB")],
   "concept_detail":[(50,"document","concept_detail_draft.md","18KB"),(90,"document","concept_detail.md","32KB")],
   "scenario":[(40,"document","story_outline.md","15KB"),(70,"document","stage_design.md","22KB"),(90,"document","dialogue_script.md","35KB")],
   "world":[(25,"image","bg_grassland.png","1.8MB"),(45,"image","bg_cave.png","2.1MB"),(60,"image","bg_sky.png","1.6MB"),(75,"audio","bgm_grassland.wav","3.2MB"),(85,"audio","bgm_cave.wav","2.8MB"),(95,"audio","bgm_sky.wav","3.5MB")],
   "game_design":[(30,"document","mechanics_spec.md","18KB"),(45,"image","ui_wireframe_01.png","245KB"),(55,"image","ui_wireframe_02.png","312KB"),(70,"document","sound_spec.md","8KB"),(95,"document","game_design.md","42KB")],
   "tech_spec":[(50,"document","tech_spec_draft.md","20KB"),(90,"document","tech_spec.md","38KB")],
   "asset_character":[(35,"image","ball_concept.png","156KB"),(50,"image","ball_sprite_sheet.png","512KB"),(65,"image","guide_character.png","234KB"),(80,"image","boss_enemy.png","445KB"),(95,"document","character_specs.md","18KB")],
   "code":[(30,"document","main.ts","8KB"),(60,"document","utils.ts","4KB"),(90,"document","game.ts","12KB")],
  }
  return assets.get(agent_type,[])

 def _get_checkpoint_points(self,agent_type:str)->List[tuple]:
  checkpoints={
   "concept":[(90,"concept_review","ゲームコンセプトの承認")],
   "task_split_1":[(90,"task_review_1","タスク分割1のレビュー")],
   "concept_detail":[(90,"concept_detail_review","コンセプト詳細のレビュー")],
   "scenario":[(90,"scenario_review","シナリオ構成のレビュー")],
   "world":[(90,"world_review","世界観設計のレビュー")],
   "game_design":[(90,"game_design_review","ゲームデザインのレビュー")],
   "tech_spec":[(90,"tech_spec_review","技術仕様のレビュー")],
   "task_split_2":[(90,"task_review_2","タスク分割2のレビュー")],
   "asset_character":[(90,"character_review","キャラアセットのレビュー")],
   "asset_ui":[(90,"ui_review","UIアセットのレビュー")],
   "task_split_3":[(90,"task_review_3","タスク分割3のレビュー")],
   "code":[(90,"code_review","コード実装のレビュー")],
   "ui_integration":[(90,"ui_integration_review","UI統合のレビュー")],
   "task_split_4":[(90,"task_review_4","タスク分割4のレビュー")],
   "unit_test":[(90,"unit_test_review","単体テスト結果のレビュー")],
   "integration_test":[(90,"integration_test_review","統合テスト結果のレビュー")],
  }
  return checkpoints.get(agent_type,[])

 def _generate_checkpoint_content(self,agent_type:str,cp_type:str)->str:
  contents={
   "concept_review":"# ゲームコンセプト\n\n## 概要\nボールを操作してゴールを目指すシンプルなパズルゲーム。\n\n## 特徴\n- 物理演算ベースのリアルな挙動\n- 全30ステージ\n- スコアシステム（タイム + コイン収集）\n\n## ターゲット\n全年齢向け、カジュアルゲーマー",
   "design_review":"# ゲームデザイン\n\n## 操作方法\n- 矢印キー: ボールの移動\n- スペースキー: ジャンプ\n- R: リスタート\n\n## 物理パラメータ\n- 重力: 9.8 m/s²\n- 摩擦係数: 0.3\n- 反発係数: 0.7",
  }
  return contents.get(cp_type,f"# {cp_type}\n\n内容を確認してください。")

 def _add_agent_log_internal(self,session,agent_id:str,level:str,message:str,progress:int=None):
  repo=AgentLogRepository(session)
  repo.add_log(agent_id,level,message,progress)

 def _add_system_log_internal(self,session,project_id:str,level:str,source:str,message:str):
  repo=SystemLogRepository(session)
  repo.add_log(project_id,level,source,message)

 def _get_generation_type(self,agent_type:str)->str:
  llm_types=['concept','task_split_1','concept_detail','game_design','tech_spec','code','event','ui_integration','asset_integration','unit_test','integration_test']
  image_types=['asset_character','asset_background','asset_ui','asset_effect']
  audio_types=['world','asset_bgm','asset_voice','asset_sfx']
  dialogue_types=['scenario']
  if agent_type in dialogue_types:
   return 'dialogue'
  if agent_type in audio_types:
   return 'audio'
  if agent_type in image_types:
   return 'image'
  return 'llm'

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
   if "aiServices" not in data or not data["aiServices"]:
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
   print(f"[DataStore] Project {project_id} initialized")
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
   project.status="draft"
   project.current_phase=1
   project.updated_at=datetime.now()
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
   agent_names=",".join(selected_agents) if selected_agents else "全エージェント"
   self._add_system_log_internal(session,project_id,"info","System",f"ブラッシュアップ開始: {agent_names}")
   print(f"[DataStore] Project {project_id} brushup started: {agent_names}")
   return proj_repo.to_dict(project)

 def get_agents_by_project(self,project_id:str)->List[Dict]:
  with session_scope() as session:
   repo=AgentRepository(session)
   return repo.get_by_project(project_id)

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
    other_pending=cp_repo.get_pending_by_agent(cp.agent_id)
    other_pending=[c for c in other_pending if c.id!=checkpoint_id]
    if not other_pending and agent.status=="waiting_approval":
     agent.status="running"
     session.flush()
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
    print(f"[DataStore] Project {project_id} advanced to Phase 2")

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
   priority_desc="緊急" if priority=="urgent" else "通常"
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
