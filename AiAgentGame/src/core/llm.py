"""
LLM configuration and initialization.
"""

import os
import yaml
from pathlib import Path
from typing import Optional, Callable, Any
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain.chat_models.base import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

# Global config cache
_config_cache = None

# Runtime LLM config override (set from dashboard)
_runtime_config_override = None


def set_runtime_llm_config(config: dict):
    """Set runtime LLM config override from dashboard."""
    global _runtime_config_override
    _runtime_config_override = config


def get_runtime_llm_config() -> dict:
    """Get current runtime LLM config override."""
    return _runtime_config_override or {}


def load_config(config_path: str = "config/llm_config.yaml") -> dict:
    """Load LLM configuration from YAML file."""
    project_root = Path(__file__).parent.parent.parent
    config_file = project_root / config_path

    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    with open(config_file, 'r', encoding='utf-8') as f:
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

    # Apply runtime config override (from dashboard)
    runtime_override = get_runtime_llm_config()
    if runtime_override:
        llm_config.update(runtime_override)

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


def get_app_language() -> str:
    """Get configured language (ja or en)."""
    global _config_cache
    if _config_cache is None:
        _config_cache = load_config()
    return _config_cache.get("app", {}).get("language", "ja")


def get_output_dir() -> Path:
    """Get configured output directory."""
    global _config_cache
    if _config_cache is None:
        _config_cache = load_config()
    output_dir = _config_cache.get("app", {}).get("output_dir", "./output")
    project_root = Path(__file__).parent.parent.parent
    path = project_root / output_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


# LLM interaction tracking
_llm_callback = None
_total_tokens = {"input": 0, "output": 0}


def set_llm_callback(callback: Callable[[dict], None]):
    """Set callback for LLM interaction events."""
    global _llm_callback
    _llm_callback = callback


def get_total_tokens() -> dict:
    """Get total token usage."""
    return _total_tokens.copy()


def reset_tokens():
    """Reset token counters."""
    global _total_tokens
    _total_tokens = {"input": 0, "output": 0}


def track_llm_call(agent_name: str, prompt: str, response: str,
                   input_tokens: int = 0, output_tokens: int = 0,
                   model: str = None, temperature: float = None, max_tokens: int = None):
    """Track an LLM call and notify callback."""
    global _total_tokens, _llm_callback

    _total_tokens["input"] += input_tokens
    _total_tokens["output"] += output_tokens

    # Get config for model info if not provided
    if model is None or temperature is None or max_tokens is None:
        try:
            config = load_config()
            default_config = config.get("default", {})
            agent_config = config.get("agent_overrides", {}).get(agent_name, {})
            merged = {**default_config, **agent_config}
            model = model or merged.get("model", "unknown")
            temperature = temperature if temperature is not None else merged.get("temperature", 0.7)
            max_tokens = max_tokens if max_tokens is not None else merged.get("max_tokens", 4096)
        except Exception:
            model = model or "unknown"
            temperature = temperature if temperature is not None else 0.7
            max_tokens = max_tokens if max_tokens is not None else 4096

    if _llm_callback:
        _llm_callback({
            "agent": agent_name,
            "prompt": prompt,
            "response": response,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_input": _total_tokens["input"],
            "total_output": _total_tokens["output"],
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens
        })
