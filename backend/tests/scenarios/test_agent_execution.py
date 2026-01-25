"""エージェント実行のシナリオテスト"""
import pytest
from agents.base import AgentContext,AgentType,AgentStatus


class TestMockAgentExecution:
 """Mockエージェント実行のシナリオ"""

 @pytest.mark.asyncio
 async def test_simple_agent_execution(self,mock_agent_runner,sample_agent_context):
  output = await mock_agent_runner.run_agent(sample_agent_context)
  assert output.status == AgentStatus.COMPLETED
  assert output.agent_id == sample_agent_context.agent_id

 @pytest.mark.asyncio
 async def test_agent_stream_execution(self,mock_agent_runner,sample_agent_context):
  events = []
  async for event in mock_agent_runner.run_agent_stream(sample_agent_context):
   events.append(event)
  assert len(events) > 0
  event_types = [e["type"] for e in events]
  assert "progress" in event_types


class TestAgentRetryScenario:
 """エージェントリトライのシナリオ"""

 @pytest.mark.asyncio
 async def test_retry_on_transient_failure(self,retry_config):
  from agents.retry_strategy import retry_with_backoff

  attempt_count = 0

  async def flaky_operation():
   nonlocal attempt_count
   attempt_count += 1
   if attempt_count < 3:
    raise ConnectionError("Transient failure")
   return {"success":True}

  result = await retry_with_backoff(
   flaky_operation,
   config=retry_config
  )

  assert result["success"] is True
  assert attempt_count == 3


class TestHealthMonitorIntegration:
 """ヘルスモニター統合のシナリオ"""

 def test_health_status_tracking(self,mock_sio):
  from providers.health_monitor import ProviderHealthMonitor
  from providers.base import HealthCheckResult
  from datetime import datetime

  monitor = ProviderHealthMonitor.__new__(ProviderHealthMonitor)
  monitor._initialized = False
  monitor.__init__()
  monitor.set_socketio(mock_sio)

  monitor._update_health_state(
   "anthropic",
   HealthCheckResult(available=True,latency_ms=100,checked_at=datetime.now())
  )

  status = monitor.get_health_status("anthropic")
  assert status.available is True

  emitted = mock_sio.get_emitted("provider_health_changed")
  assert len(emitted) == 1
  assert emitted[0]["data"]["health"]["available"] is True

  monitor._update_health_state(
   "anthropic",
   HealthCheckResult(available=False,error="API Error",checked_at=datetime.now())
  )

  status = monitor.get_health_status("anthropic")
  assert status.available is False

  emitted = mock_sio.get_emitted("provider_health_changed")
  assert len(emitted) == 2
