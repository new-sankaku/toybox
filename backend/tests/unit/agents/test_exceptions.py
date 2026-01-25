import pytest
from agents.exceptions import (
 AgentException,
 ProviderUnavailableError,
 ContextValidationError,
 CheckpointTimeoutError,
 QualityCheckFailedError,
 MaxRetriesExceededError,
 RateLimitError,
)


class TestProviderUnavailableError:
 def test_basic(self):
  error = ProviderUnavailableError("anthropic")
  assert "anthropic" in str(error)
  assert error.recoverable is True
  assert error.provider_id == "anthropic"

 def test_with_reason(self):
  error = ProviderUnavailableError("openai","APIキーが無効")
  assert "APIキーが無効" in str(error)
  assert error.reason == "APIキーが無効"


class TestContextValidationError:
 def test_basic(self):
  error = ContextValidationError("コンテキストが不正です")
  assert error.recoverable is False

 def test_with_missing_fields(self):
  error = ContextValidationError(
   "必須フィールドが不足",
   missing_fields=["project_id","agent_type"]
  )
  assert "project_id" in error.missing_fields


class TestCheckpointTimeoutError:
 def test_basic(self):
  error = CheckpointTimeoutError("cp-001",300)
  assert "cp-001" in str(error)
  assert "300" in str(error)
  assert error.recoverable is True
  assert error.checkpoint_id == "cp-001"
  assert error.timeout_seconds == 300


class TestQualityCheckFailedError:
 def test_recoverable(self):
  error = QualityCheckFailedError(
   "concept_leader",
   issues=["品質が低い"],
   retry_count=1
  )
  assert error.recoverable is True

 def test_not_recoverable(self):
  error = QualityCheckFailedError(
   "concept_leader",
   issues=["品質が低い"],
   retry_count=3
  )
  assert error.recoverable is False


class TestMaxRetriesExceededError:
 def test_basic(self):
  error = MaxRetriesExceededError("LLM呼び出し",3)
  assert "LLM呼び出し" in str(error)
  assert error.recoverable is False
  assert error.max_retries == 3


class TestRateLimitError:
 def test_basic(self):
  error = RateLimitError("anthropic")
  assert error.recoverable is True
  assert error.retry_after is None

 def test_with_retry_after(self):
  error = RateLimitError("openai",retry_after=60)
  assert "60秒後" in str(error)
  assert error.retry_after == 60
