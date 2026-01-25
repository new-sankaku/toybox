"""AIプロバイダーAPIルートの統合テスト"""
import pytest
import json
from flask import Flask


@pytest.fixture
def app(db_session):
 """テスト用Flaskアプリ"""
 from flask import Flask
 from handlers.ai_provider import register_ai_provider_routes
 app=Flask(__name__)
 app.config["TESTING"]=True
 register_ai_provider_routes(app)
 return app


@pytest.fixture
def client(app):
 """テストクライアント"""
 return app.test_client()


class TestProviderRoutes:
 def test_get_providers(self,client):
  response=client.get("/api/ai-providers")
  assert response.status_code==200
  data=json.loads(response.data)
  assert isinstance(data,list)
  provider_ids=[p["id"] for p in data]
  assert"anthropic" in provider_ids
  assert"mock" in provider_ids

 def test_get_provider_detail(self,client):
  response=client.get("/api/ai-providers/mock")
  assert response.status_code==200
  data=json.loads(response.data)
  assert data["id"]=="mock"
  assert"models" in data

 def test_get_provider_not_found(self,client):
  response=client.get("/api/ai-providers/nonexistent")
  assert response.status_code==404

 def test_get_provider_models(self,client):
  response=client.get("/api/ai-providers/mock/models")
  assert response.status_code==200
  data=json.loads(response.data)
  assert isinstance(data,list)


class TestProviderTestConnection:
 def test_test_mock_provider(self,client):
  response=client.post(
   "/api/ai-providers/test",
   data=json.dumps({"providerType":"mock"}),
   content_type="application/json"
  )
  assert response.status_code==200
  data=json.loads(response.data)
  assert data["success"] is True

 def test_test_missing_provider_type(self,client):
  response=client.post(
   "/api/ai-providers/test",
   data=json.dumps({}),
   content_type="application/json"
  )
  assert response.status_code==400


class TestHealthRoutes:
 def test_get_all_health(self,client):
  response=client.get("/api/providers/health")
  assert response.status_code==200
  data=json.loads(response.data)
  assert isinstance(data,dict)

 def test_get_provider_health(self,client):
  response=client.get("/api/providers/mock/health")
  assert response.status_code==200
  data=json.loads(response.data)
  assert"available" in data
