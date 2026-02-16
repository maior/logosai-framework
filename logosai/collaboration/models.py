"""
Agent Collaboration Models

에이전트 간 협업을 위한 데이터 모델 정의.
"""

from __future__ import annotations

import uuid
import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class CollaborationStatus(Enum):
    """협업 요청 상태"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    LOOP_DETECTED = "loop_detected"
    DEPTH_EXCEEDED = "depth_exceeded"


@dataclass
class AgentCapability:
    """에이전트가 제공하는 능력 정보"""
    agent_id: str
    agent_name: str
    capabilities: List[str]
    description: str = ""
    acp_endpoint: Optional[str] = None  # 분산 환경용: http://host:port


@dataclass
class CollaborationRequest:
    """에이전트 간 협업 요청"""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    caller_id: str = ""
    caller_name: str = ""
    capability: str = ""          # 필요한 능력 (예: "document_processing", "translation")
    query: str = ""               # 실제 처리할 쿼리
    context: Dict[str, Any] = field(default_factory=dict)
    timeout: float = 30.0         # 초 단위 타임아웃
    parent_request_id: Optional[str] = None  # 체인 추적용 (A→B→C일 때 A의 request_id)
    depth: int = 0                # 현재 호출 깊이
    max_depth: int = 5            # 최대 호출 깊이
    call_chain: List[str] = field(default_factory=list)  # 호출 체인 [A, B, C, ...]
    timestamp: float = field(default_factory=time.time)


@dataclass
class CollaborationResult:
    """협업 결과"""
    request_id: str
    status: CollaborationStatus
    agent_id: str = ""            # 실제 처리한 에이전트
    agent_name: str = ""
    data: Any = None              # 결과 데이터
    error: Optional[str] = None   # 에러 메시지
    execution_time: float = 0.0   # 실행 시간 (초)
    depth: int = 0                # 호출 깊이
    call_chain: List[str] = field(default_factory=list)
