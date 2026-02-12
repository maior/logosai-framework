"""
Self-Evolution Safety Mechanisms (안전 메커니즘)

무한 루프 방지 및 안전한 진화를 위한 메커니즘들입니다.
"""

from .circuit_breaker import EvolutionCircuitBreaker, CircuitState
from .history_tracker import FixHistoryTracker, FixRecord
from .confidence_gate import ConfidenceGate

__all__ = [
    "EvolutionCircuitBreaker",
    "CircuitState",
    "FixHistoryTracker",
    "FixRecord",
    "ConfidenceGate",
]
