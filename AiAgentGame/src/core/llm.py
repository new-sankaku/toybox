"""
LLM configuration and initialization.
"""

import os
import yaml
from pathlib import Path
from typing import Optional
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain.chat_models.base import BaseChatModel


def load_config(config_path: str = "config/llm_config.yaml") -> dict:
    """Load LLM configuration from YAML file."""
    project_root = Path(__file__).parent.parent.parent
    config_file = project_root / config_path

    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)

    # Replace environment variables
    config_str = yaml.dump(config)
    for key, value in os.environ.items():
        config_str = config_str.replace(f"${{{key}}}", value)

    return yaml.safe_load(config_str)


def get_llm(
    config: Optional[dict] = None,
    agent_name: Optional[str] = None,
    **kwargs
) -> BaseChatModel:
    """
    Get LLM instance based on configuration.

    Args:
        config: Optional configuration dict. If None, loads from default config file.
        agent_name: Optional agent name to apply agent-specific overrides.
        **kwargs: Additional arguments to override config (e.g., temperature, max_tokens)

    Returns:
        BaseChatModel: Initialized LLM instance
    """
    if config is None:
        config = load_config()

    # Start with default config
    llm_config = config.get("default", {}).copy()

    # Apply agent-specific overrides if present
    if agent_name and "agent_overrides" in config:
        agent_override = config["agent_overrides"].get(agent_name, {})
        llm_config.update(agent_override)

    # Apply kwargs overrides
    llm_config.update(kwargs)

    provider = llm_config.get("provider", "anthropic")
    model = llm_config.get("model")
    temperature = llm_config.get("temperature", 0.7)
    max_tokens = llm_config.get("max_tokens", 4096)

    # Get provider-specific config
    provider_config = config.get("providers", {}).get(provider, {})

    if provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")

        return ChatAnthropic(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key
        )

    elif provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")

        return ChatOpenAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key
        )

    elif provider == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = provider_config.get("base_url", "https://api.deepseek.com/v1")

        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY environment variable not set")

        return ChatOpenAI(
            base_url=base_url,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key
        )

    elif provider == "custom":
        api_key = os.getenv("CUSTOM_API_KEY", "dummy")
        base_url = provider_config.get("base_url")

        if not base_url:
            raise ValueError("Custom provider requires base_url in config")

        return ChatOpenAI(
            base_url=base_url,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key
        )

    else:
        raise ValueError(f"Unknown provider: {provider}")


def get_llm_for_agent(agent_name: str) -> BaseChatModel:
    """
    Convenience function to get LLM for a specific agent.

    Args:
        agent_name: Name of the agent (e.g., "planner", "coder")

    Returns:
        BaseChatModel: Initialized LLM instance with agent-specific config
    """
    return get_llm(agent_name=agent_name)
