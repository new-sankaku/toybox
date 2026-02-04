from datetime import datetime
from sqlalchemy import Column,String,Integer,Text,DateTime,Boolean,ForeignKey,JSON
from sqlalchemy.orm import declarative_base,relationship

Base=declarative_base()

class Project(Base):
 __tablename__="projects"
 id=Column(String(50),primary_key=True)
 name=Column(String(255),nullable=False)
 description=Column(Text)
 concept=Column(JSON)
 status=Column(String(50),default="draft")
 current_phase=Column(Integer,default=1)
 state=Column(JSON)
 config=Column(JSON)
 ai_services=Column(JSON)
 created_at=Column(DateTime,default=datetime.now)
 updated_at=Column(DateTime,default=datetime.now,onupdate=datetime.now)
 agents=relationship("Agent",back_populates="project",cascade="all,delete-orphan")
 checkpoints=relationship("Checkpoint",back_populates="project",cascade="all,delete-orphan")
 system_logs=relationship("SystemLog",back_populates="project",cascade="all,delete-orphan")
 assets=relationship("Asset",back_populates="project",cascade="all,delete-orphan")
 interventions=relationship("Intervention",back_populates="project",cascade="all,delete-orphan")
 uploaded_files=relationship("UploadedFile",back_populates="project",cascade="all,delete-orphan")
 quality_settings=relationship("QualitySetting",back_populates="project",cascade="all,delete-orphan")

class Agent(Base):
 __tablename__="agents"
 id=Column(String(50),primary_key=True)
 project_id=Column(String(50),ForeignKey("projects.id"),nullable=False)
 type=Column(String(50),nullable=False)
 phase=Column(Integer,default=0)
 status=Column(String(50),default="pending")
 progress=Column(Integer,default=0)
 current_task=Column(Text)
 tokens_used=Column(Integer,default=0)
 input_tokens=Column(Integer,default=0)
 output_tokens=Column(Integer,default=0)
 started_at=Column(DateTime)
 completed_at=Column(DateTime)
 error=Column(Text)
 parent_agent_id=Column(String(50))
 metadata_=Column("metadata",JSON)
 created_at=Column(DateTime,default=datetime.now)
 project=relationship("Project",back_populates="agents")
 logs=relationship("AgentLog",back_populates="agent",cascade="all,delete-orphan")
 checkpoints=relationship("Checkpoint",back_populates="agent",cascade="all,delete-orphan")

class Checkpoint(Base):
 __tablename__="checkpoints"
 id=Column(String(50),primary_key=True)
 project_id=Column(String(50),ForeignKey("projects.id"),nullable=False)
 agent_id=Column(String(50),ForeignKey("agents.id"),nullable=False)
 type=Column(String(50))
 title=Column(String(255))
 description=Column(Text)
 content_category=Column(String(50))
 output=Column(JSON)
 status=Column(String(50),default="pending")
 feedback=Column(Text)
 resolved_at=Column(DateTime)
 created_at=Column(DateTime,default=datetime.now)
 updated_at=Column(DateTime,default=datetime.now,onupdate=datetime.now)
 project=relationship("Project",back_populates="checkpoints")
 agent=relationship("Agent",back_populates="checkpoints")

class AgentLog(Base):
 __tablename__="agent_logs"
 id=Column(String(50),primary_key=True)
 agent_id=Column(String(50),ForeignKey("agents.id"),nullable=False)
 level=Column(String(20))
 message=Column(Text)
 progress=Column(Integer)
 metadata_=Column("metadata",JSON)
 created_at=Column(DateTime,default=datetime.now)
 agent=relationship("Agent",back_populates="logs")

class SystemLog(Base):
 __tablename__="system_logs"
 id=Column(String(50),primary_key=True)
 project_id=Column(String(50),ForeignKey("projects.id"),nullable=False)
 level=Column(String(20))
 source=Column(String(100))
 message=Column(Text)
 details=Column(Text)
 created_at=Column(DateTime,default=datetime.now)
 project=relationship("Project",back_populates="system_logs")

class Asset(Base):
 __tablename__="assets"
 id=Column(String(50),primary_key=True)
 project_id=Column(String(50),ForeignKey("projects.id"),nullable=False)
 agent_id=Column(String(50),ForeignKey("agents.id"),nullable=True)
 name=Column(String(255))
 type=Column(String(50))
 agent=Column(String(100))
 size=Column(String(50))
 url=Column(Text)
 thumbnail=Column(Text)
 duration=Column(String(20))
 approval_status=Column(String(50),default="pending")
 created_at=Column(DateTime,default=datetime.now)
 project=relationship("Project",back_populates="assets")

class Metric(Base):
 __tablename__="metrics"
 project_id=Column(String(50),ForeignKey("projects.id"),primary_key=True)
 total_tokens_used=Column(Integer,default=0)
 total_input_tokens=Column(Integer,default=0)
 total_output_tokens=Column(Integer,default=0)
 estimated_total_tokens=Column(Integer,default=50000)
 tokens_by_type=Column(JSON)
 generation_counts=Column(JSON)
 elapsed_time_seconds=Column(Integer,default=0)
 estimated_remaining_seconds=Column(Integer,default=0)
 estimated_end_time=Column(DateTime)
 completed_tasks=Column(Integer,default=0)
 total_tasks=Column(Integer,default=0)
 progress_percent=Column(Integer,default=0)
 current_phase=Column(Integer,default=1)
 phase_name=Column(String(100))
 active_generations=Column(Integer,default=0)

class Intervention(Base):
 __tablename__="interventions"
 id=Column(String(50),primary_key=True)
 project_id=Column(String(50),ForeignKey("projects.id"),nullable=False)
 target_type=Column(String(50))
 target_agent_id=Column(String(50))
 priority=Column(String(20))
 message=Column(Text)
 attached_file_ids=Column(JSON)
 status=Column(String(50),default="pending")
 responses=Column(JSON,default=list)
 created_at=Column(DateTime,default=datetime.now)
 delivered_at=Column(DateTime)
 acknowledged_at=Column(DateTime)
 processed_at=Column(DateTime)
 project=relationship("Project",back_populates="interventions")

class UploadedFile(Base):
 __tablename__="uploaded_files"
 id=Column(String(50),primary_key=True)
 project_id=Column(String(50),ForeignKey("projects.id"),nullable=False)
 filename=Column(String(255))
 original_filename=Column(String(255))
 mime_type=Column(String(100))
 category=Column(String(50))
 size_bytes=Column(Integer)
 status=Column(String(50),default="ready")
 description=Column(Text)
 url=Column(Text)
 uploaded_at=Column(DateTime,default=datetime.now)
 project=relationship("Project",back_populates="uploaded_files")

class QualitySetting(Base):
 __tablename__="quality_settings"
 id=Column(Integer,primary_key=True,autoincrement=True)
 project_id=Column(String(50),ForeignKey("projects.id"),nullable=False)
 agent_type=Column(String(50),nullable=False)
 config=Column(JSON)
 project=relationship("Project",back_populates="quality_settings")


class ApiKeyStore(Base):
 __tablename__="api_key_store"
 provider_id=Column(String(50),primary_key=True)
 encrypted_key=Column(Text,nullable=False)
 key_hint=Column(String(20))
 is_valid=Column(Boolean,default=False)
 latency_ms=Column(Integer)
 last_validated_at=Column(DateTime)
 created_at=Column(DateTime,default=datetime.now)
 updated_at=Column(DateTime,default=datetime.now,onupdate=datetime.now)


class ProjectAiConfig(Base):
 __tablename__="project_ai_configs"
 id=Column(Integer,primary_key=True,autoincrement=True)
 project_id=Column(String(50),ForeignKey("projects.id"),nullable=False)
 usage_category=Column(String(50),nullable=False)
 provider_id=Column(String(50),nullable=False)
 model_id=Column(String(100),nullable=False)
 custom_params=Column(JSON)
 created_at=Column(DateTime,default=datetime.now)
 updated_at=Column(DateTime,default=datetime.now,onupdate=datetime.now)

class AgentTrace(Base):
 __tablename__="agent_traces"
 id=Column(String(50),primary_key=True)
 project_id=Column(String(50),ForeignKey("projects.id"),nullable=False)
 agent_id=Column(String(50),ForeignKey("agents.id"),nullable=False)
 agent_type=Column(String(50),nullable=False)
 status=Column(String(20),default="running")
 input_context=Column(JSON)
 prompt_sent=Column(Text)
 llm_response=Column(Text)
 output_summary=Column(Text)
 output_data=Column(JSON)
 tokens_input=Column(Integer,default=0)
 tokens_output=Column(Integer,default=0)
 duration_ms=Column(Integer,default=0)
 error_message=Column(Text)
 model_used=Column(String(100))
 started_at=Column(DateTime,default=datetime.now)
 completed_at=Column(DateTime)


class LlmJob(Base):
 __tablename__="llm_jobs"
 id=Column(String(50),primary_key=True)
 project_id=Column(String(50),ForeignKey("projects.id"),nullable=False)
 agent_id=Column(String(50),ForeignKey("agents.id"),nullable=False)
 provider_id=Column(String(50),nullable=False)
 model=Column(String(100),nullable=False)
 status=Column(String(20),default="pending")
 priority=Column(Integer,default=0)
 system_prompt=Column(Text)
 prompt=Column(Text,nullable=False)
 messages_json=Column(Text)
 max_tokens=Column(Integer,default=32768)
 temperature=Column(String(10))
 response_content=Column(Text)
 tokens_input=Column(Integer,default=0)
 tokens_output=Column(Integer,default=0)
 error_message=Column(Text)
 retry_count=Column(Integer,default=0)
 external_job_id=Column(String(100))
 tools_json=Column(Text)
 created_at=Column(DateTime,default=datetime.now)
 started_at=Column(DateTime)
 completed_at=Column(DateTime)


class LocalProviderConfig(Base):
 __tablename__="local_provider_configs"
 provider_id=Column(String(50),primary_key=True)
 base_url=Column(String(500),nullable=False)
 is_validated=Column(Boolean,default=False)
 last_validated_at=Column(DateTime)
 created_at=Column(DateTime,default=datetime.now)
 updated_at=Column(DateTime,default=datetime.now,onupdate=datetime.now)

class CostHistory(Base):
 __tablename__="cost_history"
 id=Column(String(50),primary_key=True)
 project_id=Column(String(50),ForeignKey("projects.id"),nullable=False)
 agent_id=Column(String(50),nullable=True)
 agent_type=Column(String(50))
 service_type=Column(String(50),nullable=False)
 provider_id=Column(String(50))
 model_id=Column(String(100))
 input_tokens=Column(Integer,default=0)
 output_tokens=Column(Integer,default=0)
 unit_count=Column(Integer,default=1)
 cost_usd=Column(String(20))
 recorded_at=Column(DateTime,default=datetime.now)
 metadata_=Column("metadata",JSON)

class GlobalCostSettings(Base):
 __tablename__="global_cost_settings"
 id=Column(Integer,primary_key=True,autoincrement=True)
 global_enabled=Column(Boolean,default=True)
 global_monthly_limit=Column(String(20),default="100.0")
 alert_threshold=Column(Integer,default=80)
 stop_on_budget_exceeded=Column(Boolean,default=False)
 services=Column(JSON)
 updated_at=Column(DateTime,default=datetime.now,onupdate=datetime.now)

class GlobalExecutionSettings(Base):
 __tablename__="global_execution_settings"
 id=Column(Integer,primary_key=True,autoincrement=True)
 concurrent_limits=Column(JSON)
 websocket_settings=Column(JSON)
 updated_at=Column(DateTime,default=datetime.now,onupdate=datetime.now)

class FileMetadata(Base):
 __tablename__="file_metadata"
 id=Column(Integer,primary_key=True,autoincrement=True)
 project_id=Column(String(50),nullable=False,index=True)
 path=Column(String(1000),nullable=False)
 file_type=Column(String(50))
 mime_type=Column(String(100))
 size=Column(Integer,default=0)
 hash=Column(String(64))
 encoding=Column(String(20),default="utf-8")
 language=Column(String(50))
 line_count=Column(Integer,default=0)
 dependencies=Column(JSON)
 dependents=Column(JSON)
 tags=Column(JSON)
 description=Column(Text)
 agent_modified=Column(String(50))
 access_count=Column(Integer,default=0)
 created_at=Column(DateTime,default=datetime.now)
 modified_at=Column(DateTime,default=datetime.now,onupdate=datetime.now)
 last_accessed_at=Column(DateTime,default=datetime.now)

class WorkflowSnapshot(Base):
 __tablename__="workflow_snapshots"
 id=Column(String(50),primary_key=True)
 project_id=Column(String(50),ForeignKey("projects.id"),nullable=False)
 agent_id=Column(String(50),ForeignKey("agents.id"),nullable=False)
 workflow_run_id=Column(String(50),nullable=False,index=True)
 step_type=Column(String(50),nullable=False)
 step_id=Column(String(100),nullable=False)
 label=Column(String(255))
 state_data=Column(JSON)
 worker_tasks=Column(JSON)
 status=Column(String(20),default="active")
 created_at=Column(DateTime,default=datetime.now)

class AgentMemory(Base):
 __tablename__="agent_memories"
 id=Column(Integer,primary_key=True,autoincrement=True)
 project_id=Column(String(50),nullable=True,index=True)
 category=Column(String(50),nullable=False)
 agent_type=Column(String(50),nullable=False)
 content=Column(Text,nullable=False)
 source_project_id=Column(String(50))
 relevance_score=Column(Integer,default=100)
 access_count=Column(Integer,default=0)
 created_at=Column(DateTime,default=datetime.now)

class FileTreeCacheTable(Base):
 __tablename__="file_tree_cache"
 id=Column(Integer,primary_key=True,autoincrement=True)
 project_id=Column(String(50),nullable=False,index=True)
 cache_key=Column(String(2000),nullable=False)
 items_json=Column(Text,nullable=False)
 created_at=Column(DateTime,default=datetime.now)

