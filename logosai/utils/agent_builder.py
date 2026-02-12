"""
에이전트 빌더 모듈

에이전트 인스턴스를 생성하고 관리하는 유틸리티 모듈입니다.
"""

import logging
from typing import Dict, Any, Optional, List, Type, Union
from logosai.types import AgentType, AgentConfig
from logosai.agent import LogosAIAgent
# Legacy imports - comment out for now
# from logosai.agents.llm import LLMAgent
# from logosai.agents.search import SearchAgent

# 로거 설정
logger = logging.getLogger(__name__)

# 에이전트 타입별 클래스 매핑
AGENT_CLASS_MAP: Dict[AgentType, Type[LogosAIAgent]] = {
    # Legacy mappings - commented out for now
    # AgentType.LLM_SEARCH: LLMAgent,
    # AgentType.INTERNET_SEARCH: SearchAgent,
}

def create_agent(agent_type: Union[AgentType, str], config: Optional[AgentConfig] = None) -> LogosAIAgent:
    """에이전트 생성
    
    Args:
        agent_type: 생성할 에이전트 유형
        config: 에이전트 설정
        
    Returns:
        LogosAIAgent: 생성된 에이전트
        
    Raises:
        ValueError: 지원하지 않는 에이전트 유형
    """
    if isinstance(agent_type, str):
        agent_type = AgentType.from_string(agent_type)
    
    if config is None:
        config = AgentConfig(
            name=f"{agent_type.value}_agent",
            agent_type=agent_type,
            description=f"{agent_type.value} 에이전트"
        )
    
    # 에이전트 클래스 가져오기
    agent_class = AGENT_CLASS_MAP.get(agent_type)
    if agent_class is None:
        raise ValueError(f"지원하지 않는 에이전트 유형: {agent_type}")
    
    # 에이전트 인스턴스 생성
    return agent_class(config) 