"""
LogosAI 유틸리티 모듈
"""

from logosai.utils.config_loader import (
    ConfigLoader,
    get_config_loader,
    load_config,
    get_config_value,
    set_config_value,
    register_custom_config,
    set_user_config_dir,
    get_agent_type_config,
    get_response_type_config,
    get_agent_config_template,
    load_agent_types
)

from logosai.utils.agent_builder import create_agent

from logosai.utils.llm_settings import (
    get_default_llm_settings,
    get_provider_settings,
    get_api_key,
    register_provider,
    set_default_provider,
    update_default_llm_settings,
    get_model_info,
    get_available_llm_providers
)

# LLMClient
try:
    from logosai.utils.llm_client import LLMClient, LLMMessage, LLMResponse, quick_llm
    __llm_client_exports__ = ['LLMClient', 'LLMMessage', 'LLMResponse', 'quick_llm']
except ImportError:
    __llm_client_exports__ = []

# Text Utilities (v0.9.0)
try:
    from logosai.utils.text_utils import parse_llm_json, clean_markdown_code, extract_code_block, truncate_for_prompt
    __text_utils_exports__ = ['parse_llm_json', 'clean_markdown_code', 'extract_code_block', 'truncate_for_prompt']
except ImportError:
    __text_utils_exports__ = []

__all__ = [
    # Config Loader
    'ConfigLoader',
    'get_config_loader',
    'load_config',
    'get_config_value',
    'set_config_value',
    'register_custom_config',
    'set_user_config_dir',
    'get_agent_type_config',
    'get_response_type_config',
    'get_agent_config_template',
    'load_agent_types',
    # Agent Builder
    'create_agent',
    # LLM Settings
    'get_default_llm_settings',
    'get_provider_settings',
    'get_api_key',
    'register_provider',
    'set_default_provider',
    'update_default_llm_settings',
    'get_model_info',
    'get_available_llm_providers',
] + __llm_client_exports__ + __text_utils_exports__
