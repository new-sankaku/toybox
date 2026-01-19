"""
Agent Runner Factory

設定に基づいてAgentRunnerインスタンスを生成
"""

import os
from typing import Optional
from .base import AgentRunner


# 環境変数からモード取得（デフォルトはtestdata）
AGENT_MODE = os.environ.get("AGENT_MODE", "testdata")


def create_agent_runner(
    mode: Optional[str] = None,
    **kwargs
) -> AgentRunner:
    """
    AgentRunnerのインスタンスを生成

    Args:
        mode: "testdata" or "api" (Noneの場合は環境変数から)
        **kwargs: ランナー固有の設定

    Returns:
        AgentRunner: 適切なランナーインスタンス

    Raises:
        ValueError: 不明なモードが指定された場合
    """
    actual_mode = mode or AGENT_MODE

    if actual_mode == "api":
        from .api_runner import ApiAgentRunner
        return ApiAgentRunner(**kwargs)

    else:
        raise ValueError(f"Unknown agent mode: {actual_mode}. Use 'testdata' or 'api'")


def get_current_mode() -> str:
    """現在のエージェントモードを取得"""
    return AGENT_MODE
