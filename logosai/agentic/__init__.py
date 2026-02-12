"""
LogosAI Agentic AI 모듈

템플릿과 에이전트가 공통으로 사용할 수 있는 Agentic AI 핵심 기능을 제공합니다.

주요 모듈:
- AgenticCore: Think-Plan-Act-Reflect 사이클
- AgenticReasoning: Chain of Thought, ReAct 패턴
- AgenticTools: 도구 사용 프레임워크
- AgenticMemory: 장단기 메모리 시스템
- AgenticLearning: 자율 학습 시스템
"""

from .core import (
    AgenticCore,
    ThoughtProcess,
    ActionPlan,
    Action,
    Reflection,
    AgenticState
)

from .reasoning import (
    AgenticReasoning,
    ReasoningType,
    ReasoningResult,
    ChainOfThought,
    ReActPattern,
    TreeOfThoughts
)

from .tools import (
    AgenticTools,
    Tool,
    ToolResult,
    ToolRegistry,
    tool_decorator,
    ToolCategory
)

from .memory import (
    AgenticMemory,
    MemoryType,
    Memory,
    ShortTermMemory,
    LongTermMemory,
    MemoryImportance
)

from .learning import (
    AgenticLearning,
    Experience,
    Feedback,
    LearningStrategy,
    PerformanceMetrics,
    FeedbackType
)

__all__ = [
    # Core
    'AgenticCore',
    'ThoughtProcess',
    'ActionPlan',
    'Action',
    'Reflection',
    'AgenticState',
    
    # Reasoning
    'AgenticReasoning',
    'ReasoningType',
    'ReasoningResult',
    'ChainOfThought',
    'ReActPattern',
    'TreeOfThoughts',
    
    # Tools
    'AgenticTools',
    'Tool',
    'ToolResult',
    'ToolRegistry',
    'tool_decorator',
    'ToolCategory',
    
    # Memory
    'AgenticMemory',
    'MemoryType',
    'Memory',
    'ShortTermMemory',
    'LongTermMemory',
    'MemoryImportance',
    
    # Learning
    'AgenticLearning',
    'Experience',
    'Feedback',
    'LearningStrategy',
    'PerformanceMetrics',
    'FeedbackType',
]