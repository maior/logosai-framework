"""LLM Default Configuration — single source of truth for framework LLM settings.

Reads from (in priority order):
  1. ~/.logosai/config.json  (user config, created by `logosai init`)
  2. Environment variables    (LOGOSAI_LLM_PROVIDER, LOGOSAI_LLM_MODEL)
  3. Hardcoded fallback       (google / gemini-2.5-flash-lite)

Usage:
    from logosai.config.llm_defaults import get_default_provider, get_default_model

    # In any framework file — replaces hardcoded "gemini-2.5-flash-lite"
    llm = LLMClient(provider=get_default_provider(), model=get_default_model())

    # Or get all defaults at once
    defaults = get_llm_defaults()
    # {"provider": "google", "model": "gemini-2.5-flash-lite", "temperature": 0.7, ...}
"""

import json
import os
from typing import Dict, Any

# Hardcoded fallback (used only when no config file and no env vars)
_FALLBACK = {
    "provider": "google",
    "model": "gemini-2.5-flash-lite",
    "temperature": 0.7,
    "max_tokens": 4096,
}

# Cache (loaded once per process)
_cache: Dict[str, Any] = {}


def _load_config() -> Dict[str, Any]:
    """Load LLM config from file or env, with caching."""
    global _cache
    if _cache:
        return _cache

    config = dict(_FALLBACK)

    # Priority 1: ~/.logosai/config.json
    config_path = os.path.expanduser("~/.logosai/config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                user_config = json.load(f)
            llm_section = user_config.get("llm", {})
            if llm_section.get("provider"):
                config["provider"] = llm_section["provider"]
            if llm_section.get("model"):
                config["model"] = llm_section["model"]
            if llm_section.get("temperature") is not None:
                config["temperature"] = llm_section["temperature"]
            if llm_section.get("max_tokens") is not None:
                config["max_tokens"] = llm_section["max_tokens"]
        except Exception:
            pass

    # Priority 2: Environment variables (override config file)
    env_provider = os.environ.get("LOGOSAI_LLM_PROVIDER")
    env_model = os.environ.get("LOGOSAI_LLM_MODEL")
    env_temp = os.environ.get("LOGOSAI_LLM_TEMPERATURE")
    if env_provider:
        config["provider"] = env_provider
    if env_model:
        config["model"] = env_model
    if env_temp:
        try:
            config["temperature"] = float(env_temp)
        except ValueError:
            pass

    _cache = config
    return config


def get_default_provider() -> str:
    """Get default LLM provider (e.g., 'google', 'openai', 'anthropic')."""
    return _load_config()["provider"]


def get_default_model() -> str:
    """Get default LLM model name (e.g., 'gemini-2.5-flash-lite')."""
    return _load_config()["model"]


def get_default_temperature() -> float:
    """Get default temperature."""
    return _load_config()["temperature"]


def get_default_max_tokens() -> int:
    """Get default max tokens."""
    return _load_config()["max_tokens"]


def get_llm_defaults() -> Dict[str, Any]:
    """Get all LLM defaults as dict."""
    return dict(_load_config())


def reload_config():
    """Force reload config (e.g., after config file change)."""
    global _cache
    _cache = {}
    return _load_config()
