"""Seed script for initializing test data in SQLite database"""
import os
import sys
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from models.database import engine,get_session,init_db
from models.tables import Base,Project,Agent,Metric,Intervention,Asset
from config_loader import get_auto_approval_rules as get_config_auto_approval_rules,get_ui_phases,get_agent_definitions
from ai_config import build_default_ai_services
from asset_scanner import scan_all_testdata,get_testdata_path

def reset_database():
 Base.metadata.drop_all(bind=engine)
 Base.metadata.create_all(bind=engine)
 print("[Seed] Database reset complete")

def seed_sample_project():
 session=get_session()
 try:
  existing=session.query(Project).filter(Project.id=="proj-001").first()
  if existing:
   print("[Seed] Sample project already exists, skipping")
   return
  now=datetime.now()
  proj_id="proj-001"
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
  ui_phases=get_ui_phases()
  agent_defs=get_agent_definitions()
  completed_before_phase=4
  total_input=0
  total_output=0
  for phase_idx,phase in enumerate(ui_phases):
   for agent_type in phase.get("agents",[]):
    agent_def=agent_defs.get(agent_type,{})
    display_name=agent_def.get("shortLabel") or agent_def.get("label") or agent_type
    is_completed=phase_idx<completed_before_phase
    input_t=500000 if is_completed else 0
    output_t=200000 if is_completed else 0
    total_input+=input_t
    total_output+=output_t
    agent=Agent(
     id=f"agent-{proj_id}-{agent_type}",
     project_id=proj_id,
     type=agent_type,
     phase=phase_idx,
     status="completed" if is_completed else"pending",
     progress=100 if is_completed else 0,
     tokens_used=input_t+output_t,
     input_tokens=input_t,
     output_tokens=output_t,
     metadata_={"displayName":display_name},
     created_at=now
    )
    session.add(agent)
  metric=Metric(
   project_id=proj_id,
   total_tokens_used=total_input+total_output,
   total_input_tokens=total_input,
   total_output_tokens=total_output,
   estimated_total_tokens=80000000,
   tokens_by_type={},
   generation_counts={
    "characters":{"count":12,"unit":"体"},
    "backgrounds":{"count":8,"unit":"枚"},
    "ui":{"count":24,"unit":"点"},
    "effects":{"count":6,"unit":"種"},
    "music":{"count":5,"unit":"曲"},
    "sfx":{"count":18,"unit":"個"},
    "voice":{"count":45,"unit":"件"},
    "scenarios":{"count":3,"unit":"本"},
    "code":{"count":4500,"unit":"行"},
    "documents":{"count":10,"unit":"件"}
   },
   elapsed_time_seconds=7245,
   estimated_remaining_seconds=3600,
   completed_tasks=10,
   total_tasks=25,
   progress_percent=35,
   current_phase=4,
   phase_name="Phase 4: アセット生成",
   active_generations=3
  )
  session.add(metric)
  interventions_data=[
   {
    "id":"intv-001",
    "target_type":"specific",
    "target_agent_id":"agent-proj-001-asset_character",
    "priority":"normal",
    "message":"キャラクターのデザインについて確認です。主人公の髪の色は設定資料では茶色ですが、青にした方がゲームの世界観に合うと思います。変更してもよろしいでしょうか？",
    "status":"waiting_response",
    "responses":[
     {"sender":"agent","agentId":"agent-proj-001-asset_character","message":"キャラクターのデザインについて確認です。主人公の髪の色は設定資料では茶色ですが、青にした方がゲームの世界観に合うと思います。変更してもよろしいでしょうか？","createdAt":now.isoformat()}
    ]
   },
   {
    "id":"intv-002",
    "target_type":"all",
    "target_agent_id":None,
    "priority":"urgent",
    "message":"全エージェントへ: 本日18時までにフェーズ4のタスクを完了してください。",
    "status":"delivered",
    "responses":[]
   },
   {
    "id":"intv-003",
    "target_type":"specific",
    "target_agent_id":"agent-proj-001-game_design",
    "priority":"normal",
    "message":"ゲームバランスの調整について相談があります。",
    "status":"processed",
    "responses":[
     {"sender":"operator","agentId":None,"message":"ゲームバランスの調整について相談があります。","createdAt":now.isoformat()},
     {"sender":"agent","agentId":"agent-proj-001-game_design","message":"承知しました。現在のバランス設定を確認し、調整案を作成します。","createdAt":now.isoformat()},
     {"sender":"operator","agentId":None,"message":"よろしくお願いします。","createdAt":now.isoformat()}
    ]
   }
  ]
  for data in interventions_data:
   intervention=Intervention(
    id=data["id"],
    project_id=proj_id,
    target_type=data["target_type"],
    target_agent_id=data["target_agent_id"],
    priority=data["priority"],
    message=data["message"],
    attached_file_ids=[],
    status=data["status"],
    responses=data["responses"],
    created_at=now,
    delivered_at=now if data["status"] in ("delivered","acknowledged","processed","waiting_response") else None,
    acknowledged_at=now if data["status"] in ("acknowledged","processed") else None,
    processed_at=now if data["status"]=="processed" else None
   )
   session.add(intervention)
  session.commit()
  print(f"[Seed] Sample project {proj_id} created with {len(agents_data)} agents and {len(interventions_data)} interventions")
 except Exception as e:
  session.rollback()
  print(f"[Seed] Error: {e}")
  raise
 finally:
  session.close()

def seed_testdata_assets(project_id:str="proj-001"):
 testdata_path=get_testdata_path()
 if not os.path.exists(testdata_path):
  print(f"[Seed] testdata directory not found: {testdata_path}")
  return
 scanned_assets=scan_all_testdata(testdata_path)
 if not scanned_assets:
  print("[Seed] No assets found in testdata")
  return
 session=get_session()
 try:
  existing_names={a.name for a in session.query(Asset).filter(Asset.project_id==project_id).all()}
  now=datetime.now()
  added=0
  for data in scanned_assets:
   if data["name"] in existing_names:
    continue
   asset=Asset(
    id=data["id"],
    project_id=project_id,
    name=data["name"],
    type=data["type"],
    agent=data["agent"],
    size=data["size"],
    url=data["url"],
    thumbnail=data.get("thumbnail"),
    duration=data.get("duration"),
    approval_status=data.get("approvalStatus","approved"),
    created_at=now
   )
   session.add(asset)
   added+=1
  session.commit()
  if added>0:
   print(f"[Seed] Added {added} new assets from testdata to {project_id}")
  else:
   print(f"[Seed] No new assets to add for {project_id}")
 except Exception as e:
  session.rollback()
  print(f"[Seed] Error seeding assets: {e}")
  raise
 finally:
  session.close()

def main():
 import argparse
 parser=argparse.ArgumentParser(description="Seed test data")
 parser.add_argument("--reset",action="store_true",help="Reset database before seeding")
 args=parser.parse_args()
 if args.reset:
  reset_database()
 else:
  init_db()
 seed_sample_project()
 seed_testdata_assets()
 print("[Seed] Done")

if __name__=="__main__":
 main()
