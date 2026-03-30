"""
LogosAI SDK - Conversational Agent Development Platform

A Python framework for building, orchestrating, and evolving AI agents.
"""

import logging as _logging
import os as _os

__version__ = "0.10.0"
__author__ = "LogosAI Team"
__license__ = "MIT"
__description__ = "Conversational Agent Development Platform"

_logger = _logging.getLogger(__name__)

# === Core exports (always available) ===
from .agent import LogosAIAgent, create_agent
from .agent_types import (
    AgentType,
    AgentResponseType,
    AgentResponse,
    TaskType,
    ClassificationResult,
    get_agent_types,
)
from .config import AgentConfig

__all__ = [
    "LogosAIAgent",
    "create_agent",
    "AgentType",
    "AgentResponseType",
    "AgentResponse",
    "AgentConfig",
    "TaskType",
    "ClassificationResult",
    "get_agent_types",
]

# === SimpleAgent (v0.9.0) ===
try:
    from .simple_agent import SimpleAgent, agent, create_simple_agent
    __all__ += ["SimpleAgent", "agent", "create_simple_agent"]
except ImportError as e:
    _logger.debug("SimpleAgent not available: %s", e)

# === LLM Client — promoted to top-level (v0.9.0) ===
try:
    from .utils.llm_client import LLMClient, LLMResponse, LLMMessage, create_llm_client, quick_llm
    __all__ += ["LLMClient", "LLMResponse", "LLMMessage", "create_llm_client", "quick_llm"]
except ImportError as e:
    _logger.debug("LLMClient not available: %s", e)

# === Text Utilities (v0.9.0) ===
try:
    from .utils.text_utils import parse_llm_json, clean_markdown_code, extract_code_block, truncate_for_prompt
    __all__ += ["parse_llm_json", "clean_markdown_code", "extract_code_block", "truncate_for_prompt"]
except ImportError as e:
    _logger.debug("Text utilities not available: %s", e)

# === Bundler & Router ===
try:
    from .agent_bundler import AgentBundler, BundleType, BundleConfig
    from .agent_router import AgentRouter, get_router, route_error, process_with_fallback
    __all__ += [
        "AgentBundler", "BundleType", "BundleConfig",
        "AgentRouter", "get_router", "route_error", "process_with_fallback",
    ]
except ImportError as e:
    _logger.debug("Bundler/Router not available: %s", e)

# === Enhanced base classes (v0.2.0) ===
try:
    from .base_agent import (
        EnhancedLogosAIAgent,
        ServiceBasedAgent,
        LLMPoweredAgent,
        APIBasedAgent,
        GameAgent,
        SearchAgent,
    )
    __all__ += [
        "EnhancedLogosAIAgent", "ServiceBasedAgent", "LLMPoweredAgent",
        "APIBasedAgent", "GameAgent", "SearchAgent",
    ]
except ImportError as e:
    _logger.debug("Enhanced base classes not available: %s", e)

# === Agent utilities (v0.2.0) ===
try:
    from .agent_utils import (
        MarkdownFormatter,
        ResponseBuilder,
        QueryParser,
        APIClient,
        ConfigValidator,
        PerformanceMonitor,
        create_test_harness,
    )
    __all__ += [
        "MarkdownFormatter", "ResponseBuilder", "QueryParser",
        "APIClient", "ConfigValidator", "PerformanceMonitor",
        "create_test_harness",
    ]
except ImportError as e:
    _logger.debug("Agent utilities not available: %s", e)

# === Message Bus ===
try:
    from .message_bus import MessageBus
    __all__ += ["MessageBus"]
except ImportError as e:
    _logger.debug("MessageBus not available: %s", e)

# === ACP module (optional) ===
try:
    from .acp import SimpleACPServer, ACPServer, ACPClient
    __all__ += ["SimpleACPServer", "ACPServer", "ACPClient"]
except ImportError as e:
    _logger.debug("ACP module not available: %s", e)

# === Agent Market (optional) ===
try:
    from .market import AgentMarket, AgentMarketTools, get_market
    __all__ += ["AgentMarket", "AgentMarketTools", "get_market"]
except ImportError as e:
    _logger.debug("Agent Market not available: %s", e)

# === ConversationalAgent system (v2.0.0) ===
try:
    from .conversational_agent import (
        ConversationalAgent,
        ConversationContext,
        ParameterDefinition,
        VisualizationConfig,
        auto_param_collection,
        visualizable,
        conversational_agent,
        create_simple_conversational_agent,
    )
    from .dialogue_manager import (
        DialogueManager,
        DialogueSession,
        DialogueState,
        get_dialogue_manager,
        initialize_dialogue_system,
        quick_dialogue,
        register_agent,
    )
    from .decorators import (
        parameter,
        auto_validate,
        smart_caching,
        retry_on_failure,
        rate_limit,
        type_aware_parameters,
        monitoring,
        production_ready,
        ValidationRule,
    )
    from .visualization import (
        VisualizationEngine,
        ChartConfig,
        DataPattern,
        get_visualization_engine,
        auto_chart,
        weather_chart,
        comparison_chart,
    )

    __all__ += [
        # ConversationalAgent
        "ConversationalAgent", "ConversationContext",
        "ParameterDefinition", "VisualizationConfig",
        "auto_param_collection", "visualizable",
        "conversational_agent", "create_simple_conversational_agent",
        # Dialogue
        "DialogueManager", "DialogueSession", "DialogueState",
        "get_dialogue_manager", "initialize_dialogue_system",
        "quick_dialogue", "register_agent",
        # Decorators
        "parameter", "auto_validate", "smart_caching",
        "retry_on_failure", "rate_limit", "type_aware_parameters",
        "monitoring", "production_ready", "ValidationRule",
        # Visualization
        "VisualizationEngine", "ChartConfig", "DataPattern",
        "get_visualization_engine", "auto_chart",
        "weather_chart", "comparison_chart",
    ]

    def quick_agent(name: str, execute_func, **kwargs):
        """Quick helper to create a simple conversational agent.

        Args:
            name: Agent name.
            execute_func: Async function(query, params) -> result.
            **kwargs: Additional settings passed to create_simple_conversational_agent.

        Returns:
            ConversationalAgent instance.
        """
        return create_simple_conversational_agent(
            name=name, execute_func=execute_func, **kwargs
        )

    def sdk_info():
        """Print SDK version and feature summary."""
        info = f"""
    ╔══════════════════════════════════════════╗
    ║           LogosAI SDK v{__version__}                ║
    ╠══════════════════════════════════════════╣
    ║  Conversational Agent Development        ║
    ║                                          ║
    ║  Features:                               ║
    ║  • Auto parameter collection             ║
    ║  • Visualization support                 ║
    ║  • Production-ready tooling              ║
    ║  • Agent collaboration & evolution       ║
    ║                                          ║
    ║  Docs: https://github.com/maior/         ║
    ║        logosai-framework                 ║
    ╚══════════════════════════════════════════╝
        """
        _logger.info(info)

    # Backward-compatible aliases
    Agent = LogosAIAgent
    ConvAgent = ConversationalAgent
    __all__ += ["quick_agent", "sdk_info", "Agent", "ConvAgent"]

except ImportError as e:
    _logger.debug("ConversationalAgent system not available: %s", e)

# === Debate System (v0.5.0) ===
try:
    from .debate import (
        SimpleDebateSystem,
        LLMDebateSystem,
        DebateResult,
        VotingSystem,
        Vote,
    )
    __all__ += ["SimpleDebateSystem", "LLMDebateSystem", "DebateResult", "VotingSystem", "Vote"]
except ImportError as e:
    _logger.debug("Debate system not available: %s", e)

# === Template System (v0.4.0) ===
try:
    from .templates import (
        TemplateEngine,
        TemplateLoader,
        TemplateRenderer,
        TemplateValidator,
        TemplateRegistry,
        TemplateMetadata,
    )
    __all__ += [
        "TemplateEngine", "TemplateLoader", "TemplateRenderer",
        "TemplateValidator", "TemplateRegistry", "TemplateMetadata",
    ]
except ImportError as e:
    _logger.debug("Template system not available: %s", e)

# === Evolution System (v0.7.0) ===
try:
    from .evolution import (
        EvolutionSystem,
        EvolutionConfig,
        EvolutionMode,
        EvolutionResult,
        ProblemType,
        Severity,
        GateAction,
        DetectedProblem,
        Improvement,
        create_evolution_system,
    )
    __all__ += [
        "EvolutionSystem", "EvolutionConfig", "EvolutionMode",
        "EvolutionResult", "ProblemType", "Severity", "GateAction",
        "DetectedProblem", "Improvement", "create_evolution_system",
    ]
except ImportError as e:
    _logger.debug("Evolution system not available: %s", e)

# === Collaboration System (v0.8.0) ===
try:
    from .collaboration import (
        CollaborationService,
        CollaborationRequest,
        CollaborationResult,
        CollaborationStatus,
        AgentCapability,
        GlobalCallGraph,
    )
    __all__ += [
        "CollaborationService", "CollaborationRequest",
        "CollaborationResult", "CollaborationStatus",
        "AgentCapability", "GlobalCallGraph",
    ]
except ImportError as e:
    _logger.debug("Collaboration system not available: %s", e)

# ── Local Storage (Personal Mode) ──
try:
    from .storage import LocalStore
    __all__ += ["LocalStore"]
except ImportError as e:
    _logger.debug("LocalStore not available: %s", e)

# Show SDK info only when explicitly requested
if _os.getenv("LOGOSAI_SHOW_INFO", "").lower() == "true":
    try:
        sdk_info()
    except Exception:
        pass
