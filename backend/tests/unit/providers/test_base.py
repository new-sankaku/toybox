import pytest
from datetime import datetime
from providers.base import (
    ChatMessage,
    ChatResponse,
    StreamChunk,
    AIProviderConfig,
    ModelInfo,
    HealthCheckResult,
    MessageRole,
)


class TestChatMessage:
    def test_to_dict(self):
        msg = ChatMessage(role=MessageRole.USER, content="テスト")
        result = msg.to_dict()
        assert result == {"role": "user", "content": "テスト"}

    def test_system_role(self):
        msg = ChatMessage(role=MessageRole.SYSTEM, content="システム")
        assert msg.role == MessageRole.SYSTEM


class TestChatResponse:
    def test_creation(self):
        response = ChatResponse(
            content="テスト応答",
            model="test-model",
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
        )
        assert response.content == "テスト応答"
        assert response.total_tokens == 30


class TestHealthCheckResult:
    def test_available(self):
        result = HealthCheckResult(
            available=True,
            latency_ms=150,
            checked_at=datetime.now(),
        )
        assert result.available is True
        assert result.latency_ms == 150

    def test_unavailable_with_error(self):
        result = HealthCheckResult(
            available=False,
            error="接続エラー",
            checked_at=datetime.now(),
        )
        assert result.available is False
        assert result.error == "接続エラー"

    def test_to_dict(self):
        now = datetime.now()
        result = HealthCheckResult(
            available=True,
            latency_ms=100,
            checked_at=now,
        )
        d = result.to_dict()
        assert d["available"] is True
        assert d["latency_ms"] == 100
        assert d["checked_at"] == now.isoformat()


class TestModelInfo:
    def test_basic_model(self):
        model = ModelInfo(
            id="test-model",
            name="Test Model",
            max_tokens=4096,
        )
        assert model.id == "test-model"
        assert model.supports_vision is False

    def test_vision_model(self):
        model = ModelInfo(
            id="vision-model",
            name="Vision Model",
            max_tokens=8192,
            supports_vision=True,
        )
        assert model.supports_vision is True


class TestAIProviderConfig:
    def test_defaults(self):
        config = AIProviderConfig()
        assert config.api_key is None
        assert config.timeout == 60
        assert config.max_retries == 2

    def test_custom_config(self):
        config = AIProviderConfig(
            api_key="test-key",
            base_url="https://api.test.com",
            timeout=120,
        )
        assert config.api_key == "test-key"
        assert config.timeout == 120
