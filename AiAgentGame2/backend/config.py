"""
Backend Configuration

環境変数とデフォルト値の管理
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class AgentConfig:
    """エージェント設定"""
    mode: str = "testdata"  # "testdata" or "api"
    anthropic_api_key: Optional[str] = None
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096


@dataclass
class ServerConfig:
    """サーバー設定"""
    host: str = "127.0.0.1"
    port: int = 5000
    debug: bool = True
    cors_origins: str = "*"


@dataclass
class Config:
    """全体設定"""
    agent: AgentConfig
    server: ServerConfig


def load_config() -> Config:
    """環境変数から設定をロード"""
    return Config(
        agent=AgentConfig(
            mode=os.environ.get("AGENT_MODE", "testdata"),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
            model=os.environ.get("AGENT_MODEL", "claude-sonnet-4-20250514"),
            max_tokens=int(os.environ.get("AGENT_MAX_TOKENS", "4096")),
        ),
        server=ServerConfig(
            host=os.environ.get("SERVER_HOST", "127.0.0.1"),
            port=int(os.environ.get("SERVER_PORT", "5000")),
            debug=os.environ.get("DEBUG", "true").lower() == "true",
            cors_origins=os.environ.get("CORS_ORIGINS", "*"),
        ),
    )


# グローバル設定インスタンス
config = load_config()


def get_config() -> Config:
    """設定を取得"""
    return config


def reload_config():
    """設定を再読み込み"""
    global config
    config = load_config()
