"""
LogosAI 에이전트 기본 클래스 모듈 — Re-export.

이 모듈은 하위 호환성을 위해 유지됩니다.
실제 구현은 logosai/agent.py에 있습니다.

기존 코드:
    from logosai.agents.base import LogosAIAgent  # 이전 경로
신규 코드:
    from logosai.agent import LogosAIAgent         # 권장 경로
    from logosai import LogosAIAgent               # 최상위 import

두 경로 모두 동일한 클래스를 반환합니다.

원본 구버전 코드는 agents/base_legacy.py에 보존되어 있습니다.
"""

# Re-export from the canonical location
from ..agent import LogosAIAgent, create_agent
from ..agent_types import AgentType, AgentResponse, AgentResponseType
from ..config import AgentConfig

__all__ = [
    "LogosAIAgent",
    "create_agent",
    "AgentType",
    "AgentResponse",
    "AgentResponseType",
    "AgentConfig",
]
