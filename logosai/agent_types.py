"""
LogosAI 에이전트 관련 타입 정의
"""

import os
import json
import logging
from enum import Enum, auto
from typing import Any, Dict, Optional, List, ClassVar, Set, Union, TypeVar, Type
from dataclasses import dataclass, field
from datetime import datetime
from pydantic import BaseModel, Field, validator
from loguru import logger

_cached_agent_types = None

JSON = Union[Dict[str, Any], List[Any], str, int, float, bool, None]

def get_agent_types(config_path: str = None, json_data: JSON = None) -> Dict[str, Dict[str, Any]]:
    """에이전트 정보를 로드 (캐시 적용)
    
    Args:
        config_path (str, optional): agents.json 파일의 경로. 기본값은 None이며, 이 경우 examples/configs/agents.json을 사용합니다.
        json_data (JSON, optional): 직접 전달할 JSON 데이터. JSON 형식이어야 합니다.
                                  단일 에이전트 정보 또는 여러 에이전트 정보('agents' 키)를 포함할 수 있습니다.
    
    Returns:
        Dict[str, Dict[str, Any]]: 에이전트 ID를 키로 하는 에이전트 정보 딕셔너리
    """
    global _cached_agent_types
    
    # json_data가 제공된 경우 먼저 처리
    if json_data is not None:
        try:
            if isinstance(json_data, str):
                config = json.loads(json_data)
            else:
                config = json_data
            
            # json_data로부터 에이전트 정보 추출
            new_agents = {}
            if isinstance(config, dict):
                if 'agents' in config:
                    new_agents = {agent['agent_id']: agent for agent in config.get('agents', [])}
                elif 'agent_id' in config:
                    new_agents = {config['agent_id']: config}
            
            # 캐시가 없는 경우 새로운 데이터로 초기화
            if _cached_agent_types is None:
                _cached_agent_types = new_agents
                return _cached_agent_types
            
            # 캐시가 있는 경우 새로운 데이터로 업데이트
            _cached_agent_types.update(new_agents)
            return _cached_agent_types
                
        except Exception as e:
            logger.error(f"JSON 데이터 처리 중 오류: {str(e)}")
            if _cached_agent_types is None:
                _cached_agent_types = {}
    
    # 캐시가 없고 config_path가 제공되지 않은 경우 기본 경로 사용
    if _cached_agent_types is None:
        try:
            if config_path is None:
                package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                config_path = os.path.join(package_dir, "examples", "configs", "agents.json")
            
            # 파일에서 에이전트 정보 로드
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    _cached_agent_types = {agent['agent_id']: agent for agent in config.get('agents', [])}
            else:
                logger.warning(f"에이전트 설정 파일을 찾을 수 없음: {config_path}")
                _cached_agent_types = {}
                
        except Exception as e:
            logger.error(f"에이전트 설정 파일 로드 중 오류: {str(e)}")
            _cached_agent_types = {}
    
    return _cached_agent_types


class AgentType(str, Enum):
    """에이전트 유형"""
    TASK_CLASSIFIER = "task_classifier"  # 작업 분류 에이전트
    MANAGED_SOURCE = "managed_source"    # 관리형 소스 에이전트
    SELF_HOSTED = "self_hosted"         # 자체 호스팅 에이전트
    LLM_INTEGRATION = "llm_integration"  # LLM 통합 에이전트
    UNKNOWN = "unknown"                 # 알 수 없는 유형
    GENERAL = "general"                 # 일반 대화형 에이전트
    SEARCH = "search"                   # 검색 에이전트
    CUSTOM = "custom"                   # 사용자 정의 에이전트

class AgentResponseType(str, Enum):
    """에이전트 응답 유형"""
    SUCCESS = "SUCCESS"  # 성공
    ERROR = "ERROR"     # 오류
    TEXT = "TEXT"       # 텍스트 응답
    HTML = "HTML"       # HTML 응답
    JSON = "JSON"       # JSON 응답


class TaskType(str):
    """작업 유형"""
    _values: Set[str] = None
    
    def __new__(cls, value):
        if cls._values is None:
            agent_types = get_agent_types()
            cls._values = set(agent_types.keys()) | {'unknown'}
        if value not in cls._values:
            value = 'unknown'
        return super().__new__(cls, value)


class ClassificationResult(BaseModel):
    """분류 결과를 위한 Pydantic 모델"""
    task_type: str = Field(description="작업의 유형")
    confidence: float = Field(description="분류 결과의 신뢰도 (0-1)", ge=0, le=1)
    reasoning: str = Field(description="작업 유형 선택의 근거")
    requires_analysis: bool = Field(description="추가 분석이 필요한지 여부")

    @validator('task_type', pre=True)
    def validate_task_type(cls, v):
        if isinstance(v, str):
            v = v.lower()
            agent_types = get_agent_types()
            if v not in agent_types and v != 'unknown':
                return 'unknown'
            return v
        return 'unknown'

    class Config:
        arbitrary_types_allowed = True


class AgentResponse:
    """에이전트 응답"""
    def __init__(self, type: AgentResponseType, content: Dict[str, Any], metadata: Dict[str, Any] = None, message: str = None):
        self.type = type
        self.content = content
        self.metadata = metadata or {}
        self.message = message or ""  # 응답 요약 또는 주요 메시지

    def to_dict(self) -> Dict[str, Any]:
        """응답을 딕셔너리로 변환"""
        return {
            "type": str(self.type),
            "content": self.content,
            "metadata": self.metadata,
            "message": self.message
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentResponse':
        """딕셔너리에서 응답 객체 생성"""
        return cls(
            type=AgentResponseType(data["type"]),
            content=data["content"],
            metadata=data.get("metadata", {}),
            message=data.get("message", "")
        )

    @classmethod
    def error(cls, message: str, content: Dict[str, Any] = None) -> 'AgentResponse':
        """오류 응답 생성"""
        return cls(
            type=AgentResponseType.ERROR,
            content=content or {"error": message},
            metadata={"error_message": message},
            message=message
        )

    @classmethod
    def success(cls, message: str = "", content: Dict[str, Any] = None) -> 'AgentResponse':
        """성공 응답 생성"""
        return cls(
            type=AgentResponseType.SUCCESS,
            content=content or {"message": message},
            metadata={"success_message": message},
            message=message
        )
