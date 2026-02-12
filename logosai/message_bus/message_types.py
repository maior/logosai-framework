"""
LogosAI SDK 메시지 타입 정의

이 모듈은 LogosAI SDK에서 사용되는 에이전트 및 워크플로우 특화 메시지 타입을 정의합니다.
"""

from enum import Enum, auto
import logging

# 로거 설정
logger = logging.getLogger(__name__)

class AgentMessageType(Enum):
    """에이전트 특화 메시지 타입"""
    
    # 쿼리 처리 관련
    INFERENCE_REQUEST = "inference_request"      # 추론 요청
    INFERENCE_RESPONSE = "inference_response"    # 추론 응답
    
    # 지식 검색 관련
    KNOWLEDGE_REQUEST = "knowledge_request"      # 지식 검색 요청
    KNOWLEDGE_RESPONSE = "knowledge_response"    # 지식 검색 응답
    
    # RAG 관련
    RETRIEVAL_REQUEST = "retrieval_request"      # 문서 검색 요청
    RETRIEVAL_RESPONSE = "retrieval_response"    # 문서 검색 응답
    
    # 도구 사용 관련
    TOOL_REQUEST = "tool_request"                # 도구 사용 요청
    TOOL_RESPONSE = "tool_response"              # 도구 사용 응답
    
    # 인터넷 검색 관련
    INTERNET_REQUEST = "internet_request"        # 인터넷 검색 요청
    INTERNET_RESPONSE = "internet_response"      # 인터넷 검색 응답
    
    # 에이전트 상태 관련
    AGENT_STATUS = "agent_status"                # 에이전트 상태 업데이트
    AGENT_ERROR = "agent_error"                  # 에이전트 오류 보고
    
    # 이미지 생성 관련
    IMAGE_REQUEST = "image_request"              # 이미지 생성 요청
    IMAGE_RESPONSE = "image_response"            # 이미지 생성 응답
    
    # 분석 관련
    ANALYSIS_REQUEST = "analysis_request"        # 데이터 분석 요청
    ANALYSIS_RESPONSE = "analysis_response"      # 데이터 분석 응답
    
    # 기타
    CUSTOM = "custom"                            # 커스텀 메시지 타입
    
    @classmethod
    def from_string(cls, value):
        """문자열에서 메시지 타입 반환"""
        try:
            for member in cls:
                if member.value == value:
                    return member
            
            # 해당하는 타입이 없으면 CUSTOM 반환
            logger.warning(f"알 수 없는 에이전트 메시지 타입 '{value}', CUSTOM으로 처리합니다.")
            return cls.CUSTOM
        except Exception as e:
            logger.error(f"메시지 타입 변환 중 오류: {str(e)}")
            return cls.CUSTOM


class WorkflowMessageType(Enum):
    """워크플로우 특화 메시지 타입"""
    
    # 워크플로우 이벤트
    WORKFLOW_START = "workflow_start"              # 워크플로우 시작
    WORKFLOW_END = "workflow_end"                  # 워크플로우 종료
    WORKFLOW_ERROR = "workflow_error"              # 워크플로우 오류
    
    # 노드 이벤트
    NODE_ENTRY = "node_entry"                      # 노드 진입
    NODE_EXIT = "node_exit"                        # 노드 종료
    NODE_ERROR = "node_error"                      # 노드 오류
    
    # 엣지 이벤트
    EDGE_TRAVERSAL = "edge_traversal"              # 엣지 이동
    
    # 상태 이벤트
    STATE_UPDATE = "state_update"                  # 상태 업데이트
    
    # 기타
    CUSTOM = "custom"                              # 커스텀 메시지 타입
    
    @classmethod
    def from_string(cls, value):
        """문자열에서 메시지 타입 반환"""
        try:
            for member in cls:
                if member.value == value:
                    return member
            
            # 해당하는 타입이 없으면 CUSTOM 반환
            logger.warning(f"알 수 없는 워크플로우 메시지 타입 '{value}', CUSTOM으로 처리합니다.")
            return cls.CUSTOM
        except Exception as e:
            logger.error(f"메시지 타입 변환 중 오류: {str(e)}")
            return cls.CUSTOM 