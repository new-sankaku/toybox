import pytest
from agents.base import (
    AgentType,
    AgentStatus,
    AgentContext,
    AgentOutput,
    QualityCheckSettings,
)


class TestAgentType:
    def test_leader_types(self):
        assert AgentType.CONCEPT_LEADER.value == "concept_leader"
        assert AgentType.DESIGN_LEADER.value == "design_leader"

    def test_worker_types(self):
        assert AgentType.RESEARCH_WORKER.value == "research_worker"
        assert AgentType.CODE_WORKER.value == "code_worker"


class TestAgentStatus:
    def test_all_statuses(self):
        assert AgentStatus.PENDING.value == "pending"
        assert AgentStatus.RUNNING.value == "running"
        assert AgentStatus.WAITING_APPROVAL.value == "waiting_approval"
        assert AgentStatus.WAITING_PROVIDER.value == "waiting_provider"
        assert AgentStatus.COMPLETED.value == "completed"
        assert AgentStatus.FAILED.value == "failed"


class TestAgentContext:
    def test_basic_context(self):
        ctx = AgentContext(
            project_id="proj-001",
            agent_id="agent-001",
            agent_type=AgentType.CONCEPT_LEADER,
        )
        assert ctx.project_id == "proj-001"
        assert ctx.agent_type == AgentType.CONCEPT_LEADER

    def test_context_with_options(self):
        ctx = AgentContext(
            project_id="proj-001",
            agent_id="agent-001",
            agent_type=AgentType.CODE_LEADER,
            project_concept="テストゲーム",
            previous_outputs={"concept": "概要"},
        )
        assert ctx.project_concept == "テストゲーム"
        assert "concept" in ctx.previous_outputs


class TestAgentOutput:
    def test_completed_output(self):
        output = AgentOutput(
            agent_id="agent-001",
            agent_type=AgentType.CONCEPT_LEADER,
            status=AgentStatus.COMPLETED,
            output={"content": "結果"},
            tokens_used=1000,
        )
        assert output.status == AgentStatus.COMPLETED
        assert output.error is None

    def test_failed_output(self):
        output = AgentOutput(
            agent_id="agent-001",
            agent_type=AgentType.CODE_LEADER,
            status=AgentStatus.FAILED,
            error="エラーが発生しました",
        )
        assert output.status == AgentStatus.FAILED
        assert output.error is not None


class TestQualityCheckSettings:
    def test_defaults(self):
        settings = QualityCheckSettings()
        assert settings.enabled is True
        assert settings.max_retries == 3

    def test_to_dict(self):
        settings = QualityCheckSettings(enabled=False, max_retries=5)
        d = settings.to_dict()
        assert d["enabled"] is False
        assert d["maxRetries"] == 5

    def test_from_dict(self):
        data = {"enabled": True, "maxRetries": 2, "isHighCost": True}
        settings = QualityCheckSettings.from_dict(data)
        assert settings.max_retries == 2
        assert settings.is_high_cost is True
