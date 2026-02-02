import pytest
from repositories.project_ai_config import ProjectAiConfigRepository
from models.tables import ProjectAiConfig


class TestProjectAiConfigRepository:
 def test_save_new_config(self,db_session,sample_project):
  repo=ProjectAiConfigRepository(db_session)
  config=repo.save(
   project_id=sample_project.id,
   usage_category="concept",
   provider_id="anthropic",
   model_id="claude-sonnet-4",
  )
  assert config.project_id==sample_project.id
  assert config.provider_id=="anthropic"

 def test_save_update_existing(self,db_session,sample_project):
  repo=ProjectAiConfigRepository(db_session)
  repo.save(sample_project.id,"concept","anthropic","claude-3")
  repo.save(sample_project.id,"concept","openai","gpt-4")
  config=repo.get(sample_project.id,"concept")
  assert config.provider_id=="openai"
  assert config.model_id=="gpt-4"

 def test_get_nonexistent(self,db_session,sample_project):
  repo=ProjectAiConfigRepository(db_session)
  result=repo.get(sample_project.id,"nonexistent")
  assert result is None

 def test_get_by_project(self,db_session,sample_project):
  repo=ProjectAiConfigRepository(db_session)
  repo.save(sample_project.id,"concept","anthropic","claude-3")
  repo.save(sample_project.id,"code","openai","gpt-4")
  configs=repo.get_by_project(sample_project.id)
  assert len(configs)==2

 def test_delete(self,db_session,sample_project):
  repo=ProjectAiConfigRepository(db_session)
  repo.save(sample_project.id,"concept","anthropic","claude-3")
  deleted=repo.delete(sample_project.id,"concept")
  assert deleted is True
  assert repo.get(sample_project.id,"concept") is None

 def test_delete_nonexistent(self,db_session,sample_project):
  repo=ProjectAiConfigRepository(db_session)
  deleted=repo.delete(sample_project.id,"nonexistent")
  assert deleted is False

 def test_delete_all_for_project(self,db_session,sample_project):
  repo=ProjectAiConfigRepository(db_session)
  repo.save(sample_project.id,"concept","anthropic","claude-3")
  repo.save(sample_project.id,"code","openai","gpt-4")
  count=repo.delete_all_for_project(sample_project.id)
  assert count==2
  assert len(repo.get_by_project(sample_project.id))==0

 def test_custom_params(self,db_session,sample_project):
  repo=ProjectAiConfigRepository(db_session)
  custom={"temperature":0.8,"max_tokens":4096}
  repo.save(
   sample_project.id,"concept","anthropic","claude-3",
   custom_params=custom
  )
  config=repo.get(sample_project.id,"concept")
  assert config.custom_params["temperature"]==0.8
