"""リトライ戦略のテスト"""
import pytest
import asyncio
from agents.retry_strategy import (
 RetryConfig,
 is_retryable_error,
 calculate_delay,
 retry_with_backoff,
 retry_sync_with_backoff,
 RetryContext,
)
from agents.exceptions import (
 ProviderUnavailableError,
 RateLimitError,
 MaxRetriesExceededError,
 ContextValidationError,
)


class TestRetryConfig:
 def test_defaults(self):
  config = RetryConfig()
  assert config.max_retries == 3
  assert config.base_delay == 1.0
  assert config.jitter is True

 def test_custom_config(self):
  config = RetryConfig(max_retries=5,base_delay=2.0,jitter=False)
  assert config.max_retries == 5
  assert config.base_delay == 2.0


class TestIsRetryableError:
 def test_retryable_exceptions(self):
  assert is_retryable_error(ProviderUnavailableError("test"))
  assert is_retryable_error(RateLimitError("test"))
  assert is_retryable_error(ConnectionError())
  assert is_retryable_error(TimeoutError())

 def test_non_retryable_exception(self):
  assert not is_retryable_error(ContextValidationError("test"))
  assert not is_retryable_error(ValueError("test"))

 def test_retryable_by_message(self):
  assert is_retryable_error(Exception("rate limit exceeded"))
  assert is_retryable_error(Exception("connection timeout"))
  assert is_retryable_error(Exception("service unavailable 503"))


class TestCalculateDelay:
 def test_exponential_backoff(self):
  config = RetryConfig(base_delay=1.0,exponential_base=2.0,jitter=False)
  assert calculate_delay(0,config) == 1.0
  assert calculate_delay(1,config) == 2.0
  assert calculate_delay(2,config) == 4.0

 def test_max_delay(self):
  config = RetryConfig(base_delay=10.0,max_delay=30.0,jitter=False)
  assert calculate_delay(5,config) == 30.0

 def test_retry_after(self):
  config = RetryConfig()
  assert calculate_delay(0,config,retry_after=60) == 60.0


class TestRetryWithBackoff:
 @pytest.mark.asyncio
 async def test_success_first_try(self,retry_config):
  call_count = 0
  async def operation():
   nonlocal call_count
   call_count += 1
   return "success"
  result = await retry_with_backoff(operation,config=retry_config)
  assert result == "success"
  assert call_count == 1

 @pytest.mark.asyncio
 async def test_success_after_retry(self,retry_config):
  call_count = 0
  async def operation():
   nonlocal call_count
   call_count += 1
   if call_count < 2:
    raise ConnectionError("temporary failure")
   return "success"
  result = await retry_with_backoff(operation,config=retry_config)
  assert result == "success"
  assert call_count == 2

 @pytest.mark.asyncio
 async def test_max_retries_exceeded(self,retry_config):
  async def operation():
   raise ConnectionError("always fails")
  with pytest.raises(MaxRetriesExceededError):
   await retry_with_backoff(operation,config=retry_config)

 @pytest.mark.asyncio
 async def test_non_retryable_error(self,retry_config):
  async def operation():
   raise ValueError("non-retryable")
  with pytest.raises(ValueError):
   await retry_with_backoff(operation,config=retry_config)

 @pytest.mark.asyncio
 async def test_on_retry_callback(self,retry_config):
  callbacks = []
  async def operation():
   if len(callbacks) < 1:
    raise ConnectionError("fail")
   return "success"
  def on_retry(attempt,error,delay):
   callbacks.append((attempt,type(error).__name__))
  result = await retry_with_backoff(
   operation,
   config=retry_config,
   on_retry=on_retry
  )
  assert len(callbacks) == 1
  assert callbacks[0][0] == 1


class TestRetrySyncWithBackoff:
 def test_success_first_try(self,retry_config):
  call_count = 0
  def operation():
   nonlocal call_count
   call_count += 1
   return "success"
  result = retry_sync_with_backoff(operation,config=retry_config)
  assert result == "success"

 def test_success_after_retry(self,retry_config):
  call_count = 0
  def operation():
   nonlocal call_count
   call_count += 1
   if call_count < 2:
    raise TimeoutError()
   return "success"
  result = retry_sync_with_backoff(operation,config=retry_config)
  assert result == "success"


class TestRetryContext:
 def test_record_error(self):
  ctx = RetryContext()
  ctx.record_error(ConnectionError("test"),1.0)
  assert ctx.attempt == 1
  assert ctx.total_delay == 1.0
  assert len(ctx.errors) == 1

 def test_should_retry(self):
  ctx = RetryContext(RetryConfig(max_retries=2))
  assert ctx.should_retry()
  ctx.attempt = 2
  assert not ctx.should_retry()

 def test_get_summary(self):
  ctx = RetryContext()
  ctx.record_error(ConnectionError(),0.5)
  ctx.record_error(TimeoutError(),1.0)
  summary = ctx.get_summary()
  assert summary["total_attempts"] == 2
  assert summary["total_delay_seconds"] == 1.5
  assert "ConnectionError" in summary["errors"]
