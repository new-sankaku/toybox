"""テスト共通フィクスチャ"""
import os
import sys
import pytest
from datetime import datetime
from typing import Generator

sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker,Session
from models.tables import Base


@pytest.fixture(scope="session")
def test_db_engine():
 """インメモリSQLiteエンジン"""
 engine = create_engine(
  "sqlite:///:memory:",
  echo=False,
  connect_args={"check_same_thread":False}
 )
 Base.metadata.create_all(engine)
 yield engine
 engine.dispose()


@pytest.fixture
def db_session(test_db_engine)->Generator[Session,None,None]:
 """テストごとにロールバックするセッション"""
 Session = sessionmaker(bind=test_db_engine)
 session = Session()
 try:
  yield session
  session.rollback()
 finally:
  session.close()


@pytest.fixture
def mock_provider():
 """MockProvider"""
 from providers.mock import MockProvider
 return MockProvider()


@pytest.fixture
def mock_provider_config():
 """MockProviderConfig"""
 from providers.base import AIProviderConfig
 return AIProviderConfig(api_key="test-api-key")


@pytest.fixture
def sample_project(db_session):
 """サンプルプロジェクト"""
 from models.tables import Project
 project = Project(
  id="test-project-001",
  name="テストプロジェクト",
  description="テスト用のプロジェクトです",
  status="draft",
  current_phase=1,
 )
 db_session.add(project)
 db_session.flush()
 return project


@pytest.fixture
def sample_agent_context():
 """サンプルエージェントコンテキスト"""
 from agents.base import AgentContext,AgentType
 return AgentContext(
  project_id="test-project-001",
  agent_id="test-agent-001",
  agent_type=AgentType.CONCEPT_LEADER,
  project_concept="テスト用のゲームコンセプト",
 )


@pytest.fixture
def mock_agent_runner():
 """MockAgentRunner"""
 from agents.mock_runner import MockAgentRunner
 return MockAgentRunner()


@pytest.fixture
def sample_messages():
 """サンプルチャットメッセージ"""
 from providers.base import ChatMessage,MessageRole
 return [
  ChatMessage(role=MessageRole.SYSTEM,content="あなたはテストアシスタントです"),
  ChatMessage(role=MessageRole.USER,content="こんにちは"),
 ]


@pytest.fixture
def api_key_data():
 """APIキーテストデータ"""
 return {
  "anthropic":"sk-ant-test-key-12345",
  "openai":"sk-openai-test-key-67890",
  "zhipu":"zhipu-test-key-abcde",
  "deepseek":"deepseek-test-key-fghij",
 }


class MockSocketIO:
 """SocketIOモック"""
 def __init__(self):
  self.emitted = []

 def emit(self,event:str,data:dict,**kwargs):
  self.emitted.append({"event":event,"data":data})

 def get_emitted(self,event:str = None)->list:
  if event:
   return [e for e in self.emitted if e["event"] == event]
  return self.emitted


@pytest.fixture
def mock_sio():
 """MockSocketIO"""
 return MockSocketIO()


@pytest.fixture
def retry_config():
 """リトライ設定"""
 from agents.retry_strategy import RetryConfig
 return RetryConfig(
  max_retries=3,
  base_delay=0.1,
  max_delay=1.0,
  jitter=False,
 )
