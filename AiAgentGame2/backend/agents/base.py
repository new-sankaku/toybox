"""
Agent Runner Base Interface

全てのエージェントランナーが実装すべき抽象インターフェース
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable, AsyncGenerator
from enum import Enum
from datetime import datetime


class AgentType(str, Enum):
    """エージェントタイプの定義"""

    # ========================================
    # Phase 1: Planning - Leaders
    # ========================================
    CONCEPT_LEADER = "concept_leader"
    DESIGN_LEADER = "design_leader"
    SCENARIO_LEADER = "scenario_leader"
    CHARACTER_LEADER = "character_leader"
    WORLD_LEADER = "world_leader"
    TASK_SPLIT_LEADER = "task_split_leader"

    # Phase 1: Planning - Workers (CONCEPT)
    RESEARCH_WORKER = "research_worker"
    IDEATION_WORKER = "ideation_worker"
    CONCEPT_VALIDATION_WORKER = "concept_validation_worker"

    # Phase 1: Planning - Workers (DESIGN)
    ARCHITECTURE_WORKER = "architecture_worker"
    COMPONENT_WORKER = "component_worker"
    DATAFLOW_WORKER = "dataflow_worker"

    # Phase 1: Planning - Workers (SCENARIO)
    STORY_WORKER = "story_worker"
    DIALOG_WORKER = "dialog_worker"
    EVENT_WORKER = "event_worker"

    # Phase 1: Planning - Workers (CHARACTER)
    MAIN_CHARACTER_WORKER = "main_character_worker"
    NPC_WORKER = "npc_worker"
    RELATIONSHIP_WORKER = "relationship_worker"

    # Phase 1: Planning - Workers (WORLD)
    GEOGRAPHY_WORKER = "geography_worker"
    LORE_WORKER = "lore_worker"
    SYSTEM_WORKER = "system_worker"

    # Phase 1: Planning - Workers (TASK_SPLIT)
    ANALYSIS_WORKER = "analysis_worker"
    DECOMPOSITION_WORKER = "decomposition_worker"
    SCHEDULE_WORKER = "schedule_worker"

    # ========================================
    # Phase 2: Development - Leaders
    # ========================================
    CODE_LEADER = "code_leader"
    ASSET_LEADER = "asset_leader"

    # Phase 2: Development - Workers
    CODE_WORKER = "code_worker"
    ASSET_WORKER = "asset_worker"

    # ========================================
    # Phase 3: Quality - Leaders
    # ========================================
    INTEGRATOR_LEADER = "integrator_leader"
    TESTER_LEADER = "tester_leader"
    REVIEWER_LEADER = "reviewer_leader"

    # Phase 3: Quality - Workers (INTEGRATOR)
    DEPENDENCY_WORKER = "dependency_worker"
    BUILD_WORKER = "build_worker"
    INTEGRATION_VALIDATION_WORKER = "integration_validation_worker"

    # Phase 3: Quality - Workers (TESTER)
    UNIT_TEST_WORKER = "unit_test_worker"
    INTEGRATION_TEST_WORKER = "integration_test_worker"
    E2E_TEST_WORKER = "e2e_test_worker"
    PERFORMANCE_TEST_WORKER = "performance_test_worker"

    # Phase 3: Quality - Workers (REVIEWER)
    CODE_REVIEW_WORKER = "code_review_worker"
    ASSET_REVIEW_WORKER = "asset_review_worker"
    GAMEPLAY_REVIEW_WORKER = "gameplay_review_worker"
    COMPLIANCE_WORKER = "compliance_worker"

    # ========================================
    # Backward Compatibility Aliases
    # ========================================
    # These map old names to new Leader types
    CONCEPT = "concept_leader"
    DESIGN = "design_leader"
    SCENARIO = "scenario_leader"
    CHARACTER = "character_leader"
    WORLD = "world_leader"
    TASK_SPLIT = "task_split_leader"
    INTEGRATOR = "integrator_leader"
    TESTER = "tester_leader"
    REVIEWER = "reviewer_leader"


class AgentStatus(str, Enum):
    """エージェントのステータス"""
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class QualityCheckSettings:
    """品質チェック設定"""
    enabled: bool = True
    max_retries: int = 3
    is_high_cost: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "maxRetries": self.max_retries,
            "isHighCost": self.is_high_cost,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QualityCheckSettings":
        return cls(
            enabled=data.get("enabled", True),
            max_retries=data.get("maxRetries", 3),
            is_high_cost=data.get("isHighCost", False),
        )


@dataclass
class AgentContext:
    """エージェント実行コンテキスト"""
    project_id: str
    agent_id: str
    agent_type: AgentType

    # 入力データ
    project_concept: Optional[str] = None
    previous_outputs: Dict[str, Any] = field(default_factory=dict)

    # 設定
    config: Dict[str, Any] = field(default_factory=dict)

    # 品質チェック設定
    quality_check: Optional[QualityCheckSettings] = None

    # コールバック（進捗通知用）
    on_progress: Optional[Callable[[int, str], None]] = None
    on_log: Optional[Callable[[str, str], None]] = None
    on_checkpoint: Optional[Callable[[str, Dict], None]] = None


@dataclass
class AgentOutput:
    """エージェントの出力"""
    agent_id: str
    agent_type: AgentType
    status: AgentStatus

    # 出力データ
    output: Dict[str, Any] = field(default_factory=dict)

    # メトリクス
    tokens_used: int = 0
    duration_seconds: float = 0

    # エラー情報（失敗時）
    error: Optional[str] = None

    # メタデータ
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class AgentRunner(ABC):
    """
    エージェントランナーの抽象基底クラス

    全ての実装（Mock, LangGraph）はこのインターフェースを実装する
    """

    @abstractmethod
    async def run_agent(
        self,
        context: AgentContext
    ) -> AgentOutput:
        """
        エージェントを実行

        Args:
            context: 実行コンテキスト（入力、設定、コールバック）

        Returns:
            AgentOutput: 実行結果
        """
        pass

    @abstractmethod
    async def run_agent_stream(
        self,
        context: AgentContext
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        エージェントをストリーミング実行

        進捗、ログ、チェックポイントをリアルタイムで yield

        Yields:
            Dict: イベントデータ
                - type: "progress" | "log" | "checkpoint" | "output" | "error"
                - data: イベント固有のデータ
        """
        pass

    @abstractmethod
    def get_supported_agents(self) -> List[AgentType]:
        """サポートしているエージェントタイプのリスト"""
        pass

    @abstractmethod
    def validate_context(self, context: AgentContext) -> bool:
        """コンテキストのバリデーション"""
        pass


class CheckpointHandler(ABC):
    """
    チェックポイントハンドラーの抽象基底クラス

    Human-in-the-loop のチェックポイント処理を担当
    """

    @abstractmethod
    async def create_checkpoint(
        self,
        project_id: str,
        agent_id: str,
        checkpoint_type: str,
        title: str,
        output: Dict[str, Any]
    ) -> str:
        """チェックポイントを作成し、IDを返す"""
        pass

    @abstractmethod
    async def wait_for_resolution(
        self,
        checkpoint_id: str,
        timeout_seconds: Optional[float] = None
    ) -> Dict[str, Any]:
        """チェックポイントの解決を待機"""
        pass

    @abstractmethod
    async def get_checkpoint_status(
        self,
        checkpoint_id: str
    ) -> Dict[str, Any]:
        """チェックポイントのステータスを取得"""
        pass
