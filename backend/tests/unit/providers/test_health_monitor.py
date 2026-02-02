import pytest
import time
from datetime import datetime
from providers.health_monitor import ProviderHealthMonitor,get_health_monitor
from providers.base import HealthCheckResult


class TestProviderHealthMonitor:
 def test_singleton(self):
  monitor1=get_health_monitor()
  monitor2=get_health_monitor()
  assert monitor1 is monitor2

 def test_get_all_health_status_empty(self):
  monitor=ProviderHealthMonitor.__new__(ProviderHealthMonitor)
  monitor._initialized=False
  monitor.__init__()
  monitor._health_states={}
  result=monitor.get_all_health_status()
  assert result=={}

 def test_update_health_state(self):
  monitor=ProviderHealthMonitor.__new__(ProviderHealthMonitor)
  monitor._initialized=False
  monitor.__init__()
  result=HealthCheckResult(
   available=True,
   latency_ms=100,
   checked_at=datetime.now(),
  )
  monitor._update_health_state("test-provider",result)
  status=monitor.get_health_status("test-provider")
  assert status.available is True
  assert status.latency_ms==100

 def test_health_change_callback(self):
  monitor=ProviderHealthMonitor.__new__(ProviderHealthMonitor)
  monitor._initialized=False
  monitor.__init__()
  callback_called=[]

  def on_change(provider_id:str,result:HealthCheckResult):
   callback_called.append((provider_id,result.available))

  monitor.set_health_change_callback(on_change)
  result=HealthCheckResult(available=True,checked_at=datetime.now())
  monitor._update_health_state("test",result)
  assert len(callback_called)==1
  assert callback_called[0]==("test",True)

 def test_socketio_emit(self,mock_sio):
  monitor=ProviderHealthMonitor.__new__(ProviderHealthMonitor)
  monitor._initialized=False
  monitor.__init__()
  monitor.set_socketio(mock_sio)
  result=HealthCheckResult(available=True,checked_at=datetime.now())
  monitor._update_health_state("anthropic",result)
  emitted=mock_sio.get_emitted("provider_health_changed")
  assert len(emitted)==1
  assert emitted[0]["data"]["provider_id"]=="anthropic"

 def test_check_interval(self):
  monitor=ProviderHealthMonitor.__new__(ProviderHealthMonitor)
  monitor._initialized=False
  monitor.__init__()
  monitor.set_check_interval(30)
  assert monitor._check_interval==30
  monitor.set_check_interval(3)
  assert monitor._check_interval==5
