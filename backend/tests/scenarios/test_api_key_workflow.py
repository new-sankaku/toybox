"""APIキー管理ワークフローのシナリオテスト"""
import pytest


class TestApiKeyWorkflow:
 """APIキー保存→検証→使用→削除の一連のフロー"""

 def test_complete_api_key_lifecycle(self,db_session):
  from repositories import ApiKeyRepository
  from providers.registry import register_all_providers,ProviderRegistry
  from providers.base import AIProviderConfig

  register_all_providers()
  repo=ApiKeyRepository(db_session)

  key_store=repo.save("mock","mock-api-key-12345")
  assert key_store.provider_id=="mock"
  assert key_store.is_valid is False

  api_key=repo.get_decrypted_key("mock")
  assert api_key=="mock-api-key-12345"

  config=AIProviderConfig(api_key=api_key)
  provider=ProviderRegistry.get_fresh("mock",config)
  result=provider.test_connection()
  is_valid=result.get("success",False)
  repo.update_validation_status("mock",is_valid)
  db_session.flush()

  key_store=repo.get("mock")
  assert key_store.is_valid is True

  hints=repo.get_all_hints()
  assert"mock" in hints
  assert hints["mock"]["isValid"] is True

  deleted=repo.delete("mock")
  assert deleted is True
  assert repo.get("mock") is None


class TestMultiProviderSetup:
 """複数プロバイダー設定のシナリオ"""

 def test_setup_multiple_providers(self,db_session,api_key_data):
  from repositories import ApiKeyRepository

  repo=ApiKeyRepository(db_session)

  for provider_id,api_key in api_key_data.items():
   repo.save(provider_id,api_key)

  all_keys=repo.get_all()
  assert len(all_keys)==len(api_key_data)

  hints=repo.get_all_hints()
  for provider_id in api_key_data:
   assert provider_id in hints
   assert"hint" in hints[provider_id]


class TestProjectAiConfigWorkflow:
 """プロジェクトAI設定のシナリオ"""

 def test_configure_project_ai_services(self,db_session,sample_project):
  from repositories import ProjectAiConfigRepository

  repo=ProjectAiConfigRepository(db_session)

  configs=[
   ("concept","openrouter","anthropic/claude-sonnet-4",{"temperature":0.7}),
   ("design","openrouter","anthropic/claude-sonnet-4",{"temperature":0.5}),
   ("code","openrouter","openai/gpt-4o",{"temperature":0.3}),
   ("test","mock","mock-model",None),
  ]

  for category,provider,model,params in configs:
   repo.save(
    project_id=sample_project.id,
    usage_category=category,
    provider_id=provider,
    model_id=model,
    custom_params=params,
   )

  project_configs=repo.get_by_project(sample_project.id)
  assert len(project_configs)==4

  concept_config=repo.get(sample_project.id,"concept")
  assert concept_config.provider_id=="openrouter"
  assert concept_config.custom_params["temperature"]==0.7

  repo.save(sample_project.id,"concept","openrouter","deepseek/deepseek-chat",{})
  updated=repo.get(sample_project.id,"concept")
  assert updated.provider_id=="openrouter"
