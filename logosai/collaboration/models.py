"""
Agent Collaboration Models

Data model definitions for inter-agent collaboration.
"""

from __future__ import annotations

import uuid
import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class CollaborationStatus(Enum):
    """Collaboration request status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    LOOP_DETECTED = "loop_detected"
    DEPTH_EXCEEDED = "depth_exceeded"


@dataclass
class AgentCapability:
    """Agent capability information"""
    agent_id: str
    agent_name: str
    capabilities: List[str]
    description: str = ""
    acp_endpoint: Optional[str] = None  # For distributed environment: http://host:port


@dataclass
class CollaborationRequest:
    """Inter-agent collaboration request"""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    caller_id: str = ""
    caller_name: str = ""
    capability: str = ""          # Required capability (e.g., "document_processing", "translation")
    query: str = ""               # Actual query to process
    context: Dict[str, Any] = field(default_factory=dict)
    timeout: float = 30.0         # Timeout in seconds
    parent_request_id: Optional[str] = None  # For chain tracking (A's request_id when A→B→C)
    depth: int = 0                # Current call depth
    max_depth: int = 5            # Maximum call depth
    call_chain: List[str] = field(default_factory=list)  # Call chain [A, B, C, ...]
    timestamp: float = field(default_factory=time.time)


@dataclass
class CollaborationResult:
    """Collaboration result"""
    request_id: str
    status: CollaborationStatus
    agent_id: str = ""            # Agent that actually processed the request
    agent_name: str = ""
    data: Any = None              # Result data
    error: Optional[str] = None   # Error message
    execution_time: float = 0.0   # Execution time in seconds
    depth: int = 0                # Call depth
    call_chain: List[str] = field(default_factory=list)
