"""
LogosAI 에이전트 관련 타입 정의
"""

import os
import json
import logging
from enum import Enum
from typing import Any, Dict, Optional, List, ClassVar, Set, Union, Protocol, Callable, Awaitable
from dataclasses import dataclass, field
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator


# 로거 설정
logger = logging.getLogger(__name__)


# 설정 로더 참조 오류 방지를 위해 직접 파일 로드 함수 정의
def _load_json_config(filename: str) -> Dict[str, Any]:
    """
    JSON 설정 파일 로드
    
    Args:
        filename: 설정 파일 이름
    
    Returns:
        설정 데이터
    """
    # 패키지 경로 설정
    package_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.join(package_dir, "config")
    
    # 파일 경로 생성
    config_file = os.path.join(config_dir, filename)
    
    # 파일 존재 확인
    if not os.path.exists(config_file):
        return {}
    
    try:
        # JSON 파일 로드
        with open(config_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


class AgentType(Enum):
    """에이전트 유형 열거형"""
    UNKNOWN = "unknown"
    TASK_CLASSIFIER = "task_classifier"
    INTERNET_SEARCH = "internet_search"
    LLM_SEARCH = "llm_search"
    RAG_SEARCH = "rag_search"
    SHOPPING = "shopping"
    ANALYSIS = "analysis"
    FORECASTING = "forecasting"
    WEATHER = "weather"
    CUSTOM = "custom"
    GENERAL = "general"  # 일반 대화형 에이전트
    
    # 사용자 정의 에이전트 유형 저장소
    _custom_types: ClassVar[Dict[str, Dict[str, Any]]] = {}
    
    @classmethod
    def _load_from_config(cls) -> Dict[str, Dict[str, Any]]:
        """설정 파일에서 에이전트 유형 로드"""
        config = _load_json_config("agent_types.json")
        return config.get("types", {})
    
    @classmethod
    def get_description(cls, agent_type: 'AgentType') -> str:
        """에이전트 유형 설명 가져오기"""
        # 내장 유형인 경우
        if isinstance(agent_type, cls):
            types = cls._load_from_config()
            type_info = types.get(agent_type.name, {})
            return type_info.get("description", "")
        # 사용자 정의 유형인 경우
        elif isinstance(agent_type, str) and agent_type.upper() in cls._custom_types:
            return cls._custom_types[agent_type.upper()].get("description", "")
        return ""
    
    @classmethod
    def register_custom_type(cls, name: str, value: str, description: str, capabilities: List[str] = None) -> bool:
        """사용자 정의 에이전트 유형 등록
        
        Args:
            name: 유형 이름 (대문자로 변환됨)
            value: 유형 값 (소문자로 변환됨)
            description: 유형 설명
            capabilities: 기능 목록
            
        Returns:
            등록 성공 여부
        """
        name = name.upper()
        value = value.lower()
        
        # 이미 존재하는 유형인지 확인
        for agent_type in cls:
            if agent_type.name == name or agent_type.value == value:
                logger.warning(f"이미 존재하는 에이전트 유형입니다: {name} ({value})")
                return False
        
        # 사용자 정의 유형 저장
        cls._custom_types[name] = {
            "id": value,
            "description": description,
            "capabilities": capabilities or []
        }
        
        # 설정 파일에도 저장 시도
        try:
            # logosai.utils 모듈 임포트 (순환 참조 방지)
            from .utils.config_loader import register_custom_config, load_config
            
            # 기존 설정 로드
            config = load_config("agent_types")
            
            # 유형 추가
            if "types" not in config:
                config["types"] = {}
            
            config["types"][name] = {
                "id": value,
                "description": description,
                "capabilities": capabilities or []
            }
            
            # 설정 등록 (메모리에만 저장)
            register_custom_config("agent_types", config)
            
            logger.info(f"사용자 정의 에이전트 유형 등록 완료: {name} ({value})")
            return True
        except Exception as e:
            logger.error(f"사용자 정의 에이전트 유형 등록 중 오류: {str(e)}")
            return False
    
    @classmethod
    def get_all_types(cls) -> Dict[str, Dict[str, Any]]:
        """모든 에이전트 유형 가져오기 (내장 + 사용자 정의)
        
        Returns:
            모든 에이전트 유형 정보
        """
        # 내장 유형 로드
        types = cls._load_from_config()
        
        # 사용자 정의 유형 추가
        for name, info in cls._custom_types.items():
            types[name] = info
            
        return types
    
    @classmethod
    def from_string(cls, agent_type_str: str) -> 'AgentType':
        """문자열에서 에이전트 유형 변환"""
        try:
            # 정확한 이름 매칭 시도
            return cls[agent_type_str.upper()]
        except KeyError:
            # 사용자 정의 유형 확인
            if agent_type_str.upper() in cls._custom_types:
                # 사용자 정의 유형은 CUSTOM으로 반환하고, 메타데이터에 실제 유형 저장
                custom_type = cls.CUSTOM
                custom_type._custom_name = agent_type_str.upper()
                custom_type._custom_value = cls._custom_types[agent_type_str.upper()]["id"]
                return custom_type
                
            # 값 매칭 시도
            for agent_type in cls:
                if agent_type.value == agent_type_str.lower():
                    return agent_type
            
            # 설정 파일에서 매핑 확인
            config = _load_json_config("agent_types.json")
            mapping = config.get("mapping", {})
            
            if agent_type_str.upper() in mapping:
                return cls[mapping[agent_type_str.upper()]]
            
            # 기본값 반환
            return cls.UNKNOWN
    
    @property
    def custom_name(self) -> Optional[str]:
        """사용자 정의 유형 이름 반환"""
        return getattr(self, "_custom_name", None)
    
    @property
    def custom_value(self) -> Optional[str]:
        """사용자 정의 유형 값 반환"""
        return getattr(self, "_custom_value", None)
    
    def __str__(self) -> str:
        """문자열 표현"""
        if self == self.CUSTOM and hasattr(self, "_custom_name"):
            return f"AgentType.{self._custom_name}"
        return f"AgentType.{self.name}"
    
    def __repr__(self) -> str:
        """개발자용 표현"""
        if self == self.CUSTOM and hasattr(self, "_custom_name"):
            return f"AgentType.{self._custom_name}"
        return f"AgentType.{self.name}"
        

class AgentResponseType(Enum):
    """에이전트 응답 유형 열거형"""
    TEXT = "text"
    RAG_SEARCH = "rag_search"
    LLM_SEARCH = "llm_search"
    INTERNET_SEARCH = "internet_search"
    SHOPPING = "shopping"
    MATH = "math"
    CALCULATOR = "calculator"
    REPORT = "report"
    QNA = "qna"
    SUMMARY = "summary"
    ANALYSIS = "analysis"
    ERROR = "error"
    SUCCESS = "success"
    PARTIAL = "partial"
    NONE = "none"
    
    # 사용자 정의 응답 유형 저장소
    _custom_types: ClassVar[Dict[str, Dict[str, Any]]] = {}
    
    @classmethod
    def _load_from_config(cls) -> Dict[str, Dict[str, Any]]:
        """설정 파일에서 응답 유형 로드"""
        config = _load_json_config("response_types.json")
        return config.get("types", {})
    
    @classmethod
    def get_description(cls, response_type: 'AgentResponseType') -> str:
        """응답 유형 설명 가져오기"""
        # 내장 유형인 경우
        if isinstance(response_type, cls):
            types = cls._load_from_config()
            type_info = types.get(response_type.name, {})
            return type_info.get("description", "")
        # 사용자 정의 유형인 경우
        elif isinstance(response_type, str) and response_type.upper() in cls._custom_types:
            return cls._custom_types[response_type.upper()].get("description", "")
        return ""
    
    @classmethod
    def register_custom_type(cls, name: str, value: str, description: str, format_spec: Dict[str, str] = None) -> bool:
        """사용자 정의 응답 유형 등록
        
        Args:
            name: 유형 이름 (대문자로 변환됨)
            value: 유형 값 (소문자로 변환됨)
            description: 유형 설명
            format_spec: 응답 형식 명세
            
        Returns:
            등록 성공 여부
        """
        name = name.upper()
        value = value.lower()
        
        # 이미 존재하는 유형인지 확인
        for response_type in cls:
            if response_type.name == name or response_type.value == value:
                logger.warning(f"이미 존재하는 응답 유형입니다: {name} ({value})")
                return False
        
        # 사용자 정의 유형 저장
        cls._custom_types[name] = {
            "id": value,
            "description": description,
            "format": format_spec or {}
        }
        
        # 설정 파일에도 저장 시도
        try:
            # logosai.utils 모듈 임포트 (순환 참조 방지)
            from .utils.config_loader import register_custom_config, load_config
            
            # 기존 설정 로드
            config = load_config("response_types")
            
            # 유형 추가
            if "types" not in config:
                config["types"] = {}
            
            config["types"][name] = {
                "id": value,
                "description": description,
                "format": format_spec or {}
            }
            
            # 설정 등록 (메모리에만 저장)
            register_custom_config("response_types", config)
            
            logger.info(f"사용자 정의 응답 유형 등록 완료: {name} ({value})")
            return True
        except Exception as e:
            logger.error(f"사용자 정의 응답 유형 등록 중 오류: {str(e)}")
            return False
    
    @classmethod
    def get_all_types(cls) -> Dict[str, Dict[str, Any]]:
        """모든 응답 유형 가져오기 (내장 + 사용자 정의)
        
        Returns:
            모든 응답 유형 정보
        """
        # 내장 유형 로드
        types = cls._load_from_config()
        
        # 사용자 정의 유형 추가
        for name, info in cls._custom_types.items():
            types[name] = info
            
        return types
    
    @classmethod
    def from_string(cls, response_type_str: str) -> 'AgentResponseType':
        """문자열에서 응답 유형 변환"""
        try:
            # 정확한 이름 매칭 시도
            return cls[response_type_str.upper()]
        except KeyError:
            # 사용자 정의 유형 확인
            if response_type_str.upper() in cls._custom_types:
                # 사용자 정의 유형은 TEXT로 반환하고, 메타데이터에 실제 유형 저장
                custom_type = cls.TEXT
                custom_type._custom_name = response_type_str.upper()
                custom_type._custom_value = cls._custom_types[response_type_str.upper()]["id"]
                return custom_type
                
            # 값 매칭 시도
            for response_type in cls:
                if response_type.value == response_type_str.lower():
                    return response_type
            
            # 설정 파일에서 매핑 확인
            config = _load_json_config("response_types.json")
            mapping = config.get("mapping", {})
            
            if response_type_str.upper() in mapping:
                return cls[mapping[response_type_str.upper()]]
            
            # 기본값 반환
            return cls.TEXT
    
    @property
    def custom_name(self) -> Optional[str]:
        """사용자 정의 유형 이름 반환"""
        return getattr(self, "_custom_name", None)
    
    @property
    def custom_value(self) -> Optional[str]:
        """사용자 정의 유형 값 반환"""
        return getattr(self, "_custom_value", None)
    
    def __str__(self) -> str:
        """문자열 표현"""
        if self == self.TEXT and hasattr(self, "_custom_name"):
            return f"AgentResponseType.{self._custom_name}"
        return f"AgentResponseType.{self.name}"
    
    def __repr__(self) -> str:
        """개발자용 표현"""
        if self == self.TEXT and hasattr(self, "_custom_name"):
            return f"AgentResponseType.{self._custom_name}"
        return f"AgentResponseType.{self.name}"


@dataclass
class AgentResponse:
    """에이전트 응답 데이터 클래스
    
    Args:
        type: 응답 유형
        content: 응답 내용
        message: 사용자에게 표시할 메시지
        metadata: 추가 메타데이터
    """
    type: AgentResponseType
    content: Any
    message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """응답을 딕셔너리로 변환
        
        Returns:
            딕셔너리 형태의 응답
        """
        # 사용자 정의 유형 처리
        type_value = self.type.value
        if self.type.custom_value:
            type_value = self.type.custom_value
            
        return {
            "type": type_value,
            "content": self.content,
            "message": self.message,
            "metadata": self.metadata,
            "timestamp": self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentResponse':
        """딕셔너리에서 응답 객체 생성
        
        Args:
            data: 응답 데이터 딕셔너리
            
        Returns:
            AgentResponse 인스턴스
        """
        return cls(
            type=AgentResponseType.from_string(data["type"]),
            content=data["content"],
            message=data.get("message", ""),
            metadata=data.get("metadata", {}),
            timestamp=data.get("timestamp", datetime.now().isoformat())
        )
    
    @classmethod
    def text(cls, content: Any, message: str = "") -> 'AgentResponse':
        """텍스트 응답 생성
        
        Args:
            content: 응답 내용
            message: 사용자에게 표시할 메시지
            
        Returns:
            AgentResponse 인스턴스
        """
        if isinstance(content, str):
            content = {"result": content}
        return cls(
            type=AgentResponseType.TEXT,
            content=content,
            message=message or str(content)
        )
    
    @classmethod
    def error(cls, message: str, content: Dict[str, Any] = None) -> 'AgentResponse':
        """오류 응답 생성
        
        Args:
            message: 오류 메시지
            content: 추가 내용
            
        Returns:
            AgentResponse 인스턴스
        """
        return cls(
            type=AgentResponseType.ERROR,
            content=content or {"error": message},
            message=message
        )
    
    @classmethod
    def success(cls, content: Any, message: str = "") -> 'AgentResponse':
        """성공 응답 생성
        
        Args:
            content: 응답 내용
            message: 성공 메시지
            
        Returns:
            AgentResponse 인스턴스
        """
        if not message and isinstance(content, dict) and "message" in content:
            message = content["message"]
        elif not message:
            message = "성공적으로 처리되었습니다."
            
        return cls(
            type=AgentResponseType.SUCCESS,
            content=content,
            message=message
        )
    
    @classmethod
    def with_custom_type(cls, type_name: str, content: Any, message: str = "") -> 'AgentResponse':
        """사용자 정의 유형 응답 생성
        
        Args:
            type_name: 유형 이름
            content: 응답 내용
            message: 메시지
            
        Returns:
            AgentResponse 인스턴스
        """
        response_type = AgentResponseType.from_string(type_name)
        return cls(
            type=response_type,
            content=content,
            message=message
        )


class AgentConfig(BaseModel):
    """에이전트 설정"""
    name: str
    agent_type: AgentType
    description: str
    config: Dict[str, Any] = Field(default_factory=dict)


class ClassificationResult(BaseModel):
    """분류 결과를 위한 Pydantic 모델"""
    task_type: str = Field(description="작업의 유형")
    confidence: float = Field(description="분류 결과의 신뢰도 (0-1)", ge=0, le=1)
    reasoning: str = Field(description="작업 유형 선택의 근거")
    requires_analysis: bool = Field(description="추가 분석이 필요한지 여부")
    agent_not_found_message: Optional[str] = Field(default=None, description="적절한 에이전트를 찾지 못했을 때 사용자에게 제공할 안내 메시지")
    llm_answer: Optional[str] = Field(default=None, description="적절한 에이전트를 찾지 못했을 때 제공할 LLM 기반 답변")

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator('task_type', mode='before')
    @classmethod
    def validate_task_type(cls, v):
        if isinstance(v, str):
            v = v.lower()
            from .agent_types import agent_types
            if v in agent_types:
                return v
            return "llm_search"  # 기본값으로 llm_search 반환
        return "llm_search"


# Message Bus 관련 타입 정의
@dataclass
class Message:
    """메시지 버스에서 사용되는 메시지"""
    topic: str
    payload: Any
    sender: Optional[str] = None
    correlation_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    priority: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """메시지를 딕셔너리로 변환"""
        return {
            "topic": self.topic,
            "payload": self.payload,
            "sender": self.sender,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp.isoformat(),
            "priority": self.priority
        }


class MessageHandler(Protocol):
    """메시지 핸들러 프로토콜"""
    async def handle(self, message: Message) -> None:
        """메시지 처리"""
        ...


class MessageBusProtocol(Protocol):
    """메시지 버스 프로토콜 정의"""
    
    async def publish(self, topic: str, payload: Any, sender: Optional[str] = None, 
                     correlation_id: Optional[str] = None, priority: int = 0) -> None:
        """메시지 발행"""
        ...
    
    async def subscribe(self, topic: str, handler: Callable[[Message], Awaitable[None]]) -> str:
        """토픽 구독"""
        ...
    
    async def unsubscribe(self, subscription_id: str) -> None:
        """구독 취소"""
        ...
    
    async def request(self, topic: str, payload: Any, timeout: float = 30.0) -> Any:
        """요청-응답 패턴"""
        ...
    
    def get_stats(self) -> Dict[str, Any]:
        """통계 정보 가져오기"""
        ...


@dataclass
class MessageBusConfig:
    """메시지 버스 설정"""
    max_queue_size: int = 1000
    max_handlers_per_topic: int = 100
    default_timeout: float = 30.0
    enable_logging: bool = True
    enable_metrics: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """설정을 딕셔너리로 변환"""
        return {
            "max_queue_size": self.max_queue_size,
            "max_handlers_per_topic": self.max_handlers_per_topic,
            "default_timeout": self.default_timeout,
            "enable_logging": self.enable_logging,
            "enable_metrics": self.enable_metrics
        } 