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
    # Phase 1: Planning
    CONCEPT = "concept"
    DESIGN = "design"
    SCENARIO = "scenario"
    CHARACTER = "character"
    WORLD = "world"
    TASK_SPLIT = "task_split"

    # Phase 2: Development
    CODE_LEADER = "code_leader"
    ASSET_LEADER = "asset_leader"
    CODE_WORKER = "code_worker"
    ASSET_WORKER = "asset_worker"

    # Phase 3: Quality
    INTEGRATOR = "integrator"
    TESTER = "tester"
    REVIEWER = "reviewer"


class AgentStatus(str, Enum):
    """エージェントのステータス"""
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


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
