"""Seed script for initializing test data in SQLite database"""
import os
import sys
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from models.database import engine,get_session,init_db
from models.tables import Base,Project,Agent,Metric
from config_loader import get_auto_approval_rules as get_config_auto_approval_rules
from ai_config import build_default_ai_services

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
  agents_data=[
   {"type":"concept","name":"コンセプト","phase":0,"input":1250000,"output":450000},
   {"type":"task_split_1","name":"タスク分割1","phase":1,"input":850000,"output":320000},
   {"type":"concept_detail","name":"コンセプト詳細","phase":2,"input":2300000,"output":950000},
   {"type":"scenario","name":"シナリオ","phase":2,"input":4500000,"output":1800000},
   {"type":"world","name":"世界観","phase":2,"input":1800000,"output":720000},
   {"type":"game_design","name":"ゲームデザイン","phase":2,"input":3200000,"output":1250000},
   {"type":"tech_spec","name":"技術仕様","phase":2,"input":2750000,"output":980000},
   {"type":"task_split_2","name":"タスク分割2","phase":3,"input":950000,"output":380000},
   {"type":"asset_character","name":"キャラ","phase":4,"input":520000,"output":180000},
   {"type":"asset_background","name":"背景","phase":4,"input":480000,"output":150000},
   {"type":"asset_ui","name":"UI","phase":4,"input":350000,"output":120000},
   {"type":"asset_effect","name":"エフェクト","phase":4,"input":280000,"output":95000},
   {"type":"asset_bgm","name":"BGM","phase":4,"input":150000,"output":52000},
   {"type":"asset_voice","name":"ボイス","phase":4,"input":420000,"output":140000},
   {"type":"asset_sfx","name":"効果音","phase":4,"input":180000,"output":65000},
   {"type":"task_split_3","name":"タスク分割3","phase":5,"input":720000,"output":280000},
   {"type":"code","name":"コード","phase":6,"input":8900000,"output":4200000},
   {"type":"event","name":"イベント","phase":6,"input":1850000,"output":750000},
   {"type":"ui_integration","name":"UI統合","phase":6,"input":1450000,"output":580000},
   {"type":"asset_integration","name":"アセット統合","phase":6,"input":950000,"output":380000},
   {"type":"task_split_4","name":"タスク分割4","phase":7,"input":550000,"output":220000},
   {"type":"unit_test","name":"単体テスト","phase":8,"input":3200000,"output":1450000},
   {"type":"integration_test","name":"統合テスト","phase":8,"input":2800000,"output":1150000},
  ]
  total_input=0
  total_output=0
  for data in agents_data:
   input_t=data.get("input",0)
   output_t=data.get("output",0)
   total_input+=input_t
   total_output+=output_t
   agent=Agent(
    id=f"agent-{proj_id}-{data['type']}",
    project_id=proj_id,
    type=data["type"],
    phase=data["phase"],
    status="completed" if data["phase"]<4 else"pending",
    progress=100 if data["phase"]<4 else 0,
    tokens_used=input_t+output_t,
    input_tokens=input_t,
    output_tokens=output_t,
    metadata_={"displayName":data["name"]},
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
    "documents":{"count":8,"unit":"件"}
   },
   elapsed_time_seconds=7245,
   estimated_remaining_seconds=3600,
   completed_tasks=8,
   total_tasks=23,
   progress_percent=35,
   current_phase=4,
   phase_name="Phase 4: アセット生成",
   active_generations=3
  )
  session.add(metric)
  session.commit()
  print(f"[Seed] Sample project {proj_id} created with {len(agents_data)} agents")
 except Exception as e:
  session.rollback()
  print(f"[Seed] Error: {e}")
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
 print("[Seed] Done")

if __name__=="__main__":
 main()
