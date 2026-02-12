"""
LogosAI Agent Self-Evolution System (에이전트 자가 진화 시스템)

에이전트가 스스로 학습하고 개선하는 자가 진화 시스템입니다.

Components:
    - Self-Healing: 에러 및 버그 자동 수정
    - Self-Growing: 새로운 기능 추가 및 기존 기능 개선
    - Self-Evaluation: 응답 품질 평가 및 피드백

Usage:
    from logosai.evolution import EvolutionSystem, EvolutionConfig

    # 설정 생성 (기본값: 비활성화)
    config = EvolutionConfig(
        enabled=True,  # 활성화
        llm_provider="google",
        llm_model="gemini-2.5-flash-lite"
    )

    # 에이전트에 진화 시스템 적용
    evolution = EvolutionSystem(agent, config)
    await evolution.enable()

Version: 0.7.0
"""

from .config import EvolutionConfig
from .types import (
    ProblemType,
    Severity,
    GateAction,
    EvolutionMode,
    DetectedProblem,
    Feedback,
    LearnedPattern,
    Improvement,
    ValidationResult,
    EvolutionResult
)
from .detector import ProblemDetector
from .feedback import FeedbackCollector
from .learner import PatternLearner
from .improver import ImprovementGenerator
from .validator import ImprovementValidator
from .system import EvolutionSystem, create_evolution_system

# Safety mechanisms
from .safety.circuit_breaker import EvolutionCircuitBreaker
from .safety.history_tracker import FixHistoryTracker
from .safety.confidence_gate import ConfidenceGate

__all__ = [
    # Main classes
    "EvolutionSystem",
    "EvolutionConfig",
    "create_evolution_system",

    # Types
    "ProblemType",
    "Severity",
    "GateAction",
    "EvolutionMode",
    "DetectedProblem",
    "Feedback",
    "LearnedPattern",
    "Improvement",
    "ValidationResult",
    "EvolutionResult",

    # Components
    "ProblemDetector",
    "FeedbackCollector",
    "PatternLearner",
    "ImprovementGenerator",
    "ImprovementValidator",

    # Safety
    "EvolutionCircuitBreaker",
    "FixHistoryTracker",
    "ConfidenceGate",
]

__version__ = "0.7.0"
