"""
LogosAI Agent Collaboration System

에이전트 간 협업을 위한 통합 프레임워크.
- GlobalCallGraph: 루프 방지 및 호출 추적
- CollaborationService: ACP 서버가 구현하는 협업 서비스 인터페이스
- 데이터 모델: CollaborationRequest, CollaborationResult, AgentCapability
"""

from .models import (
    AgentCapability,
    CollaborationRequest,
    CollaborationResult,
    CollaborationStatus,
)
from .call_graph import GlobalCallGraph
from .service import CollaborationService

__all__ = [
    "AgentCapability",
    "CollaborationRequest",
    "CollaborationResult",
    "CollaborationStatus",
    "GlobalCallGraph",
    "CollaborationService",
]
