"""
에이전트 설정 관리 모듈

이 모듈은 LogosAI 에이전트의 설정을 관리하는 클래스와 유틸리티를 제공합니다.
"""

from typing import Dict, Any, Optional, List, Union
from ..agent_types import AgentType


class AgentConfig:
    """에이전트 설정 클래스
    
    LogosAI 에이전트의 설정을 관리하는 클래스입니다.
    """
    
    def __init__(
        self,
        name: str,
        agent_type: Union[AgentType, str],
        description: str = "",
        config: Optional[Dict[str, Any]] = None,
        api_config: Optional[Dict[str, Any]] = None,
        llm_config: Optional[Dict[str, Any]] = None
    ):
        """에이전트 설정 초기화
        
        Args:
            name: 에이전트 이름
            agent_type: 에이전트 유형
            description: 에이전트 설명
            config: 에이전트 일반 설정
            api_config: API 연결 설정
            llm_config: LLM 모델 설정
        """
        self.name = name
        
        # 에이전트 유형 설정  
        if isinstance(agent_type, str):
            # 문자열을 AgentType enum으로 변환
            try:
                self.agent_type = AgentType(agent_type)
            except ValueError:
                self.agent_type = AgentType.UNKNOWN
        else:
            self.agent_type = agent_type
        
        self.description = description
        self.config = config or {}
        self.api_config = api_config or {}
        self.llm_config = llm_config or {}
    
    def update(self, **kwargs) -> 'AgentConfig':
        """설정 업데이트
        
        키워드 인자로 전달된 값으로 설정을 업데이트합니다.
            
        Returns:
            업데이트된 설정 객체 (self)
        """
        for key, value in kwargs.items():
            if key == 'name':
                self.name = value
            elif key == 'agent_type':
                if isinstance(value, str):
                    try:
                        self.agent_type = AgentType(value)
                    except ValueError:
                        self.agent_type = AgentType.UNKNOWN
                else:
                    self.agent_type = value
            elif key == 'description':
                self.description = value
            elif key == 'config':
                self.config.update(value)
            elif key == 'api_config':
                self.api_config.update(value)
            elif key == 'llm_config':
                self.llm_config.update(value)
        
        return self
    
    def to_dict(self) -> Dict[str, Any]:
        """설정을 딕셔너리로 변환
        
        Returns:
            설정 값을 담은 딕셔너리
        """
        return {
            "name": self.name,
            "agent_type": str(self.agent_type),
            "description": self.description,
            "config": self.config.copy(),
            "api_config": self.api_config.copy(),
            "llm_config": self.llm_config.copy()
        }
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'AgentConfig':
        """딕셔너리에서 설정 객체 생성
        
        Args:
            config_dict: 설정 값을 담은 딕셔너리
            
        Returns:
            생성된 AgentConfig 객체
        """
        return cls(
            name=config_dict.get("name", "Unknown Agent"),
            agent_type=config_dict.get("agent_type", AgentType.UNKNOWN),
            description=config_dict.get("description", ""),
            config=config_dict.get("config", {}),
            api_config=config_dict.get("api_config", {}),
            llm_config=config_dict.get("llm_config", {})
        )
    
    def __str__(self) -> str:
        """문자열 표현 반환"""
        return f"AgentConfig(name='{self.name}', type={self.agent_type})"
    
    def __repr__(self) -> str:
        """개발자용 표현 반환"""
        return (f"AgentConfig(name='{self.name}', type={self.agent_type}, "
                f"description='{self.description[:20]}...' if len(self.description) > 20 else self.description)") 