import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class AgentConfig:
    mode: str = "testdata"  # "testdata" or "api"
    anthropic_api_key: Optional[str] = None
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 5000
    debug: bool = True
    cors_origins: str = "*"


@dataclass
class Config:
    agent: AgentConfig
    server: ServerConfig


def load_config() -> Config:
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


config = load_config()


def get_config() -> Config:
    return config


def reload_config():
    global config
    config = load_config()
