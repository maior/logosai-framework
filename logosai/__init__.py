"""
LogosAI SDK - 대화형 에이전트 개발 플랫폼

에이전트 개발을 간소화하는 통합 SDK를 제공합니다.
"""

__version__ = "0.7.1"
__author__ = "LogosAI Team"
__license__ = "MIT"
__description__ = "Conversational Agent Development Platform"

from .agent import LogosAIAgent
from .agent_types import (
    AgentType,
    AgentResponseType,
    AgentResponse,
    TaskType,
    ClassificationResult,
    get_agent_types
)
from .config import AgentConfig
from .agent_bundler import AgentBundler, BundleType, BundleConfig
from .agent_router import AgentRouter, get_router, route_error, process_with_fallback

# Initialize __all__ first
__all__ = [
    "LogosAIAgent",
    "AgentType",
    "AgentResponseType",
    "AgentResponse",
    "AgentConfig",
    "AgentBundler",
    "BundleType",
    "BundleConfig",
    "TaskType",
    "ClassificationResult",
    "get_agent_types",
    "AgentRouter",
    "get_router",
    "route_error",
    "process_with_fallback",
]

# Enhanced base classes (v0.2.0)
try:
    from .base_agent import (
        EnhancedLogosAIAgent,
        ServiceBasedAgent,
        LLMPoweredAgent,
        APIBasedAgent,
        GameAgent,
        SearchAgent
    )
    __all__ += [
        "EnhancedLogosAIAgent",
        "ServiceBasedAgent",
        "LLMPoweredAgent",
        "APIBasedAgent",
        "GameAgent",
        "SearchAgent"
    ]
except ImportError:
    pass

# Agent utilities (v0.2.0)
try:
    from .agent_utils import (
        MarkdownFormatter,
        ResponseBuilder,
        QueryParser,
        APIClient,
        ConfigValidator,
        PerformanceMonitor,
        create_test_harness
    )
    __all__ += [
        "MarkdownFormatter",
        "ResponseBuilder",
        "QueryParser",
        "APIClient",
        "ConfigValidator",
        "PerformanceMonitor",
        "create_test_harness"
    ]
except ImportError:
    pass

# 타입 및 기본 클래스 가져오기
from .agent_types import AgentType, AgentResponseType

# 순환 참조 문제 해결을 위해 import 순서 변경 
# 먼저 .config에서 AgentConfig를 사용하는 파일들 가져오기 전에 AgentConfig를 가져옴
import sys
import os

# config.py 파일 경로 확인
package_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(package_dir, "config.py")
if not os.path.exists(config_path):
    # config.py 파일이 없는 경우 대안으로 AgentConfig 클래스 정의
    class AgentConfig:
        def __init__(self, name, agent_type, description="", **kwargs):
            self.name = name
            self.agent_type = agent_type
            self.description = description
            for key, value in kwargs.items():
                setattr(self, key, value)
else:
    # 직접 config.py의 AgentConfig 가져오기
    from .config import AgentConfig

from .agent import LogosAIAgent, AgentResponse, create_agent

# 유틸리티 및 기타 모듈
from .message_bus import MessageBus

# ACP 모듈 가져오기 (선택적)
try:
    from .acp import ACPServer, ACPClient
    __all__ += ["ACPServer", "ACPClient"]
except ImportError:
    # ACP 모듈을 가져올 수 없는 경우 (예: 아직 설치되지 않음)
    pass

# Agent Market 모듈 가져오기 (선택적)
try:
    from .market import AgentMarket, AgentMarketTools, get_market
    __all__ += ["AgentMarket", "AgentMarketTools", "get_market"]
except ImportError:
    # Market 모듈을 가져올 수 없는 경우
    pass

# ConversationalAgent 시스템 (v2.0.0)
try:
    from .conversational_agent import (
        ConversationalAgent,
        ConversationContext,
        ParameterDefinition,
        VisualizationConfig,
        auto_param_collection,
        visualizable,
        conversational_agent,
        create_simple_conversational_agent
    )
    
    from .dialogue_manager import (
        DialogueManager,
        DialogueSession,
        DialogueState,
        get_dialogue_manager,
        initialize_dialogue_system,
        quick_dialogue,
        register_agent
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
        ValidationRule
    )
    
    from .visualization import (
        VisualizationEngine,
        ChartConfig,
        DataPattern,
        get_visualization_engine,
        auto_chart,
        weather_chart,
        comparison_chart
    )
    
    __all__ += [
        # ConversationalAgent 시스템
        "ConversationalAgent",
        "ConversationContext", 
        "ParameterDefinition",
        "VisualizationConfig",
        "auto_param_collection",
        "visualizable",
        "conversational_agent",
        "create_simple_conversational_agent",
        
        # 대화 관리
        "DialogueManager",
        "DialogueSession",
        "DialogueState", 
        "get_dialogue_manager",
        "initialize_dialogue_system",
        "quick_dialogue",
        "register_agent",
        
        # 데코레이터
        "parameter",
        "auto_validate",
        "smart_caching",
        "retry_on_failure",
        "rate_limit",
        "type_aware_parameters",
        "monitoring",
        "production_ready",
        "ValidationRule",
        
        # 시각화
        "VisualizationEngine",
        "ChartConfig",
        "DataPattern",
        "get_visualization_engine",
        "auto_chart",
        "weather_chart",
        "comparison_chart"
    ]
    
    # 빠른 시작 도우미
    def quick_agent(name: str, execute_func, **kwargs):
        """빠른 에이전트 생성 도우미
        
        Args:
            name: 에이전트 이름
            execute_func: 실행 함수
            **kwargs: 추가 설정
        
        Returns:
            ConversationalAgent: 생성된 에이전트
        
        Example:
            >>> async def my_func(query, params):
            ...     return f"Hello {params.get('name', 'World')}"
            >>> 
            >>> agent = quick_agent("Hello Agent", my_func, 
            ...                    parameters=['name'])
            >>> await agent.initialize()
        """
        return create_simple_conversational_agent(
            name=name,
            execute_func=execute_func,
            **kwargs
        )
    
    __all__ += ["quick_agent"]
    
    # SDK 정보 출력
    def sdk_info():
        """SDK 정보 출력"""
        info = f"""
    ╔══════════════════════════════════════════╗
    ║             LogosAI SDK v{__version__}              ║
    ╠══════════════════════════════════════════╣
    ║  🤖 대화형 에이전트 개발 플랫폼          ║
    ║                                          ║
    ║  주요 기능:                              ║
    ║  • 자동 파라미터 수집                   ║
    ║  • 시각화 지원                          ║
    ║  • 프로덕션 준비 도구                   ║
    ║  • Django 서버 통합                     ║
    ║                                          ║
    ║  문서: https://docs.logosai.com          ║
    ║  예제: logosai/examples/                 ║
    ╚══════════════════════════════════════════╝
        """
        print(info)
    
    __all__ += ["sdk_info"]
    
    # 백워드 호환성을 위한 별칭
    Agent = LogosAIAgent
    ConvAgent = ConversationalAgent
    __all__ += ["Agent", "ConvAgent"]
    
except ImportError as e:
    # ConversationalAgent 모듈을 가져올 수 없는 경우
    print(f"Warning: ConversationalAgent 시스템을 로드할 수 없습니다: {e}")
    pass

# Debate System (v0.5.0)
try:
    from .debate import (
        SimpleDebateSystem,
        DebateResult,
        VotingSystem,
        Vote
    )
    __all__ += [
        "SimpleDebateSystem",
        "DebateResult",
        "VotingSystem",
        "Vote"
    ]
except ImportError:
    pass

# Template System (v0.4.0)
try:
    from .templates import (
        TemplateEngine,
        TemplateLoader,
        TemplateRenderer,
        TemplateValidator,
        TemplateRegistry,
        TemplateMetadata
    )
    __all__ += [
        "TemplateEngine",
        "TemplateLoader",
        "TemplateRenderer",
        "TemplateValidator",
        "TemplateRegistry",
        "TemplateMetadata"
    ]
except ImportError:
    pass

# Evolution System (v0.7.0) - Agent Self-Evolution
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
        create_evolution_system
    )
    __all__ += [
        "EvolutionSystem",
        "EvolutionConfig",
        "EvolutionMode",
        "EvolutionResult",
        "ProblemType",
        "Severity",
        "GateAction",
        "DetectedProblem",
        "Improvement",
        "create_evolution_system"
    ]
except ImportError:
    pass

# Collaboration System (v0.8.0) - Agent-to-Agent Communication
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
        "CollaborationService",
        "CollaborationRequest",
        "CollaborationResult",
        "CollaborationStatus",
        "AgentCapability",
        "GlobalCallGraph",
    ]
except ImportError:
    pass

# 개발 모드에서 SDK 정보 출력
if os.getenv("LOGOSAI_SHOW_INFO", "").lower() == "true":
    try:
        sdk_info()
    except:
        pass 
