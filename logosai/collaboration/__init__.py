"""
LogosAI Agent Collaboration System

Integrated framework for inter-agent collaboration.
- GlobalCallGraph: Loop prevention and call tracking
- CollaborationService: Collaboration service interface implemented by ACP server
- Data models: CollaborationRequest, CollaborationResult, AgentCapability
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
