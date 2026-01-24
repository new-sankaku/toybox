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
