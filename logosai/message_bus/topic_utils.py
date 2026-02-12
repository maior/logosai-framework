"""
LogosAI SDK 메시지 버스 토픽 유틸리티

이 모듈은 메시지 버스 토픽을 생성하고 분석하는 유틸리티 함수를 제공합니다.
"""

import logging
from typing import Dict, List, Tuple, Optional, Set
import re

from .message_types import AgentMessageType, WorkflowMessageType

# 로거 설정
logger = logging.getLogger(__name__)

# 토픽 패턴 정규식
AGENT_TOPIC_PATTERN = r"agent\.([^.]+)\.([^.]+)"
WORKFLOW_TOPIC_PATTERN = r"workflow\.([^.]+)\.?([^.]*)"

def create_agent_topic(agent_id: str, message_type: str) -> str:
    """
    에이전트 토픽 생성
    
    Args:
        agent_id: 에이전트 ID
        message_type: 메시지 타입
        
    Returns:
        str: 생성된 토픽
    """
    # 메시지 타입이 AgentMessageType 열거형인 경우 값 추출
    if hasattr(message_type, 'value'):
        message_type = message_type.value
    
    # 특수한 메시지 타입 처리
    if message_type in ["inference_request", "knowledge_request", "retrieval_request",
                        "tool_request", "internet_request", "image_request", "analysis_request"]:
        return f"agent.{agent_id}.request"
    
    elif message_type in ["inference_response", "knowledge_response", "retrieval_response",
                          "tool_response", "internet_response", "image_response", "analysis_response"]:
        return f"agent.{agent_id}.response"
    
    elif message_type == "agent_error":
        return f"agent.{agent_id}.error"
    
    elif message_type == "agent_status":
        return "agent.status"
    
    # 기본 토픽 형식
    return f"agent.{agent_id}.{message_type}"

def create_workflow_topic(workflow_id: str, message_type: str, node_id: str = None) -> str:
    """
    워크플로우 토픽 생성
    
    Args:
        workflow_id: 워크플로우 ID
        message_type: 메시지 타입
        node_id: 노드 ID (선택적)
        
    Returns:
        str: 생성된 토픽
    """
    # 메시지 타입이 WorkflowMessageType 열거형인 경우 값 추출
    if hasattr(message_type, 'value'):
        message_type = message_type.value
    
    # 워크플로우 이벤트 토픽
    if message_type in ["workflow_start", "workflow_end", "workflow_error"]:
        return f"workflow.{workflow_id}.event.{message_type.replace('workflow_', '')}"
    
    # 노드 이벤트 토픽
    elif message_type in ["node_entry", "node_exit", "node_error"]:
        if node_id:
            return f"workflow.{workflow_id}.node.{node_id}.{message_type.replace('node_', '')}"
        else:
            return f"workflow.{workflow_id}.node.{message_type.replace('node_', '')}"
    
    # 엣지 이벤트 토픽
    elif message_type == "edge_traversal":
        return f"workflow.{workflow_id}.edge.traversal"
    
    # 상태 업데이트 토픽
    elif message_type == "state_update":
        return f"workflow.{workflow_id}.state"
    
    # 기본 토픽 형식
    return f"workflow.{workflow_id}.{message_type}"

def parse_topic(topic: str) -> Tuple[Optional[str], Optional[str]]:
    """
    토픽 분석
    
    Args:
        topic: 토픽 문자열
        
    Returns:
        Tuple[Optional[str], Optional[str]]: (ID, 메시지 타입) 튜플
    """
    # 에이전트 토픽 패턴 매칭
    agent_match = re.match(AGENT_TOPIC_PATTERN, topic)
    if agent_match:
        agent_id = agent_match.group(1)
        message_type = agent_match.group(2)
        return agent_id, message_type
    
    # 워크플로우 토픽 패턴 매칭
    workflow_match = re.match(WORKFLOW_TOPIC_PATTERN, topic)
    if workflow_match:
        workflow_id = workflow_match.group(1)
        message_type = workflow_match.group(2) if workflow_match.group(2) else "custom"
        return workflow_id, message_type
    
    # 매칭되지 않는 경우
    logger.warning(f"토픽 '{topic}'이 표준 패턴과 일치하지 않습니다.")
    return None, None

def get_standard_topics() -> Dict[str, List[str]]:
    """
    표준 토픽 패턴 목록 반환
    
    Returns:
        Dict[str, List[str]]: 카테고리별 표준 토픽 패턴 목록
    """
    return {
        "agent": [
            "agent.<agent_id>.request",     # 에이전트 요청
            "agent.<agent_id>.response",    # 에이전트 응답
            "agent.<agent_id>.error",       # 에이전트 오류
            "agent.status",                 # 에이전트 상태 업데이트
            "agent.discovery"               # 에이전트 검색
        ],
        "workflow": [
            "workflow.<workflow_id>.event.start",       # 워크플로우 시작
            "workflow.<workflow_id>.event.end",         # 워크플로우 종료
            "workflow.<workflow_id>.event.error",       # 워크플로우 오류
            "workflow.<workflow_id>.node.entry",        # 노드 진입
            "workflow.<workflow_id>.node.exit",         # 노드 종료
            "workflow.<workflow_id>.node.<node_id>.entry",  # 특정 노드 진입
            "workflow.<workflow_id>.node.<node_id>.exit",   # 특정 노드 종료
            "workflow.<workflow_id>.edge.traversal",    # 엣지 이동
            "workflow.<workflow_id>.state"              # 상태 업데이트
        ],
        "system": [
            "system.status",                # 시스템 상태
            "system.config.update",         # 설정 업데이트
            "system.shutdown",              # 시스템 종료
            "system.error"                  # 시스템 오류
        ]
    } 