"""
LogosAI 어댑터 - 기존 에이전트 구조와 LogosAI SDK 사이의 호환성 제공
"""

import os
import sys
import asyncio
import importlib
from typing import Any, Dict, List, Optional, Callable, Type, Union
from dataclasses import dataclass, field

# 경로 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# LogosAI 에이전트 가져오기
from .agent import LogosAIAgent
from .types import AgentType, AgentResponseType, AgentResponse
from .config import AgentConfig
from .message_bus import MessageBus, Message, MessageType, MessagePriority

# 필요한 경우 기존 에이전트 모듈 가져오기
try:
    from agents.agent_template import AgentTemplate
    from agents.base_agent import BaseAgent, AgentConfig as OldAgentConfig
    from agents.agent_message_topics import AgentMessageTopics
    LEGACY_MODULES_AVAILABLE = True
except ImportError:
    LEGACY_MODULES_AVAILABLE = False


class LegacyAdapter:
    """기존 에이전트 구조를 LogosAI SDK와 호환되도록 하는 어댑터"""
    
    @staticmethod
    def convert_agent_type(agent_type_str: str) -> AgentType:
        """문자열 에이전트 유형을 LogosAI AgentType으로 변환"""
        type_mapping = {
            "UNKNOWN": AgentType.UNKNOWN,
            "TASK_CLASSIFIER": AgentType.TASK_CLASSIFIER,
            "INTERNET_SEARCH": AgentType.INTERNET_SEARCH,
            "LLM_SEARCH": AgentType.LLM_SEARCH,
            "RAG_SEARCH": AgentType.RAG_SEARCH,
            "SHOPPING": AgentType.SHOPPING,
            "ANALYSIS": AgentType.ANALYSIS,
            "CUSTOM": AgentType.CUSTOM
        }
        
        if agent_type_str.upper() in type_mapping:
            return type_mapping[agent_type_str.upper()]
        return AgentType.CUSTOM
    
    @staticmethod
    def convert_response_type(response_type_str: str) -> AgentResponseType:
        """문자열 응답 유형을 LogosAI AgentResponseType으로 변환"""
        type_mapping = {
            "TEXT": AgentResponseType.TEXT,
            "RAG_SEARCH": AgentResponseType.RAG_SEARCH,
            "LLM_SEARCH": AgentResponseType.LLM_SEARCH,
            "INTERNET_SEARCH": AgentResponseType.INTERNET_SEARCH,
            "SHOPPING": AgentResponseType.SHOPPING,
            "ANALYSIS": AgentResponseType.ANALYSIS,
            "ERROR": AgentResponseType.ERROR,
            "SUCCESS": AgentResponseType.SUCCESS,
            "PARTIAL": AgentResponseType.PARTIAL,
            "NONE": AgentResponseType.NONE
        }
        
        if response_type_str.upper() in type_mapping:
            return type_mapping[response_type_str.upper()]
        return AgentResponseType.TEXT
    
    @staticmethod
    def convert_to_logos_agent_config(old_config) -> AgentConfig:
        """기존 에이전트 설정을 LogosAI AgentConfig로 변환"""
        if not LEGACY_MODULES_AVAILABLE:
            raise ImportError("기존 에이전트 모듈을 가져올 수 없습니다.")
        
        # 에이전트 유형 변환
        if hasattr(old_config, 'agent_type') and hasattr(old_config.agent_type, 'value'):
            agent_type = LegacyAdapter.convert_agent_type(old_config.agent_type.value)
        else:
            agent_type = AgentType.CUSTOM
            
        # API 설정 변환
        api_config = {}
        if hasattr(old_config, 'api_config') and old_config.api_config:
            api_config = old_config.api_config
            
        # LLM 설정 변환
        llm_config = {}
        if hasattr(old_config, 'llm_config') and old_config.llm_config:
            llm_config = old_config.llm_config
            
        # 기타 설정 변환
        custom_config = {}
        if hasattr(old_config, 'execution_config') and old_config.execution_config:
            custom_config['execution_config'] = old_config.execution_config
            
        return AgentConfig(
            name=old_config.name,
            agent_type=agent_type,
            description=old_config.description if hasattr(old_config, 'description') else "",
            api_config=api_config,
            llm_config=llm_config,
            custom_config=custom_config
        )
    
    @staticmethod
    def convert_to_logos_response(old_response) -> AgentResponse:
        """기존 에이전트 응답을 LogosAI AgentResponse로 변환"""
        if not LEGACY_MODULES_AVAILABLE:
            raise ImportError("기존 에이전트 모듈을 가져올 수 없습니다.")
            
        if hasattr(old_response, 'type') and hasattr(old_response.type, 'value'):
            response_type = LegacyAdapter.convert_response_type(old_response.type.value)
        else:
            response_type = AgentResponseType.TEXT
            
        return AgentResponse(
            type=response_type,
            content=old_response.content if hasattr(old_response, 'content') else {},
            metadata=old_response.metadata if hasattr(old_response, 'metadata') else {}
        )


class LegacyAgentWrapper(LogosAIAgent):
    """기존 에이전트를 LogosAI 에이전트로 래핑하는 클래스"""
    
    def __init__(self, legacy_agent):
        """
        기존 에이전트를 래핑하는 초기화
        
        Args:
            legacy_agent: 기존 에이전트 인스턴스
        """
        self.legacy_agent = legacy_agent
        
        # 기존 에이전트 설정을 LogosAI 설정으로 변환
        if hasattr(legacy_agent, 'config'):
            config = LegacyAdapter.convert_to_logos_agent_config(legacy_agent.config)
        else:
            # 기본 설정 생성
            config = AgentConfig(
                name=getattr(legacy_agent, 'name', type(legacy_agent).__name__),
                agent_type=AgentType.CUSTOM,
                description=getattr(legacy_agent, 'description', "기존 에이전트 래퍼")
            )
        
        # 상위 클래스 초기화
        super().__init__(config)
        
        # 추가 속성 설정
        self.is_legacy_wrapper = True
    
    async def initialize(self) -> bool:
        """에이전트 초기화"""
        # 상위 클래스 초기화
        await super().initialize()
        
        # 기존 에이전트 초기화
        if hasattr(self.legacy_agent, 'initialize') and callable(self.legacy_agent.initialize):
            try:
                legacy_result = await self.legacy_agent.initialize()
                if isinstance(legacy_result, bool) and not legacy_result:
                    return False
            except Exception as e:
                print(f"기존 에이전트 초기화 중 오류: {str(e)}")
                return False
        
        return True
    
    async def shutdown(self) -> None:
        """에이전트 종료"""
        # 기존 에이전트 종료
        if hasattr(self.legacy_agent, 'close') and callable(self.legacy_agent.close):
            try:
                await self.legacy_agent.close()
            except Exception as e:
                print(f"기존 에이전트 종료 중 오류: {str(e)}")
        
        # 상위 클래스 종료
        await super().shutdown()
    
    async def process_query(self, query: str, context: Dict[str, Any] = None) -> AgentResponse:
        """
        문자열 쿼리 처리
        
        Args:
            query: 처리할 쿼리 문자열
            context: 추가 컨텍스트 데이터
            
        Returns:
            처리 결과
        """
        try:
            # 기존 에이전트의 process 메서드 호출
            if hasattr(self.legacy_agent, 'process') and callable(self.legacy_agent.process):
                legacy_response = await self.legacy_agent.process(query)
                
                # 응답 변환
                if legacy_response is not None:
                    return LegacyAdapter.convert_to_logos_response(legacy_response)
            
            # 처리 실패 시 기본 응답
            return AgentResponse.error("기존 에이전트에서 처리할 수 없습니다.")
            
        except Exception as e:
            return AgentResponse.error(f"기존 에이전트 처리 중 오류: {str(e)}")


class LogosToLegacyAdapter:
    """LogosAI 에이전트를 기존 에이전트 구조와 호환되도록 하는 어댑터"""
    
    @staticmethod
    def convert_to_legacy_agent_config(logos_config) -> 'OldAgentConfig':
        """LogosAI AgentConfig를 기존 에이전트 설정으로 변환"""
        if not LEGACY_MODULES_AVAILABLE:
            raise ImportError("기존 에이전트 모듈을 가져올 수 없습니다.")
        
        from agents.base_agent import AgentType as OldAgentType
        
        # 에이전트 유형 매핑
        type_mapping = {
            AgentType.UNKNOWN: OldAgentType.UNKNOWN,
            AgentType.TASK_CLASSIFIER: OldAgentType.TASK_CLASSIFIER,
            AgentType.INTERNET_SEARCH: OldAgentType.INTERNET_SEARCH,
            AgentType.LLM_SEARCH: OldAgentType.LLM_SEARCH,
            AgentType.RAG_SEARCH: OldAgentType.RAG_SEARCH,
            AgentType.SHOPPING: OldAgentType.SHOPPING,
            AgentType.ANALYSIS: OldAgentType.ANALYSIS,
            AgentType.CUSTOM: OldAgentType.CUSTOM
        }
        
        # 에이전트 유형 결정
        if logos_config.agent_type in type_mapping:
            agent_type = type_mapping[logos_config.agent_type]
        else:
            agent_type = OldAgentType.CUSTOM
        
        return OldAgentConfig(
            name=logos_config.name,
            agent_type=agent_type,
            description=logos_config.description,
            api_config=logos_config.api_config,
            llm_config=logos_config.llm_config
        )

    @staticmethod
    def convert_to_legacy_response(logos_response) -> 'AgentTemplate.AgentResponse':
        """LogosAI AgentResponse를 기존 에이전트 응답으로 변환"""
        if not LEGACY_MODULES_AVAILABLE:
            raise ImportError("기존 에이전트 모듈을 가져올 수 없습니다.")
            
        from agents.agent_template import AgentResponse as OldAgentResponse
        from agents.agent_template import AgentResponseType as OldAgentResponseType
        
        # 응답 유형 매핑
        type_mapping = {
            AgentResponseType.TEXT: OldAgentResponseType.TEXT,
            AgentResponseType.RAG_SEARCH: OldAgentResponseType.RAG_SEARCH,
            AgentResponseType.LLM_SEARCH: OldAgentResponseType.LLM_SEARCH,
            AgentResponseType.INTERNET_SEARCH: OldAgentResponseType.INTERNET_SEARCH,
            AgentResponseType.SHOPPING: OldAgentResponseType.SHOPPING,
            AgentResponseType.ANALYSIS: OldAgentResponseType.ANALYSIS,
            AgentResponseType.ERROR: OldAgentResponseType.ERROR,
            AgentResponseType.SUCCESS: OldAgentResponseType.SUCCESS,
            AgentResponseType.PARTIAL: OldAgentResponseType.PARTIAL,
            AgentResponseType.NONE: OldAgentResponseType.NONE
        }
        
        # 응답 유형 결정
        if logos_response.type in type_mapping:
            response_type = type_mapping[logos_response.type]
        else:
            response_type = OldAgentResponseType.TEXT
            
        return OldAgentResponse(
            type=response_type,
            content=logos_response.content,
            metadata=logos_response.metadata,
            message=""
        )


class LogosAgentWrapper(AgentTemplate if LEGACY_MODULES_AVAILABLE else object):
    """LogosAI 에이전트를 기존 에이전트 구조로 래핑하는 클래스"""
    
    def __init__(self, logos_agent: LogosAIAgent):
        """
        LogosAI 에이전트를 래핑하는 초기화
        
        Args:
            logos_agent: LogosAI 에이전트 인스턴스
        """
        if not LEGACY_MODULES_AVAILABLE:
            raise ImportError("기존 에이전트 모듈을 가져올 수 없습니다.")
            
        # LogosAI 에이전트 저장
        self.logos_agent = logos_agent
        
        # 기존 에이전트 설정 변환
        legacy_config = LogosToLegacyAdapter.convert_to_legacy_agent_config(logos_agent.config)
        
        # 상위 클래스 초기화
        super().__init__(legacy_config)
        
        # 추가 속성 설정
        self.is_logos_wrapper = True
    
    async def initialize(self) -> bool:
        """에이전트 초기화"""
        # 상위 클래스 초기화
        await super().initialize()
        
        # LogosAI 에이전트 초기화
        return await self.logos_agent.initialize()
    
    async def close(self) -> None:
        """에이전트 종료"""
        # LogosAI 에이전트 종료
        await self.logos_agent.shutdown()
        
        # 상위 클래스 종료
        await super().close()
    
    async def process(self, input_data: Any) -> 'AgentTemplate.AgentResponse':
        """입력 처리"""
        logos_response = await self.logos_agent.process(input_data)
        return LogosToLegacyAdapter.convert_to_legacy_response(logos_response)


def wrap_legacy_agent(legacy_agent) -> LogosAIAgent:
    """기존 에이전트를 LogosAI 에이전트로 래핑"""
    return LegacyAgentWrapper(legacy_agent)


def wrap_logos_agent(logos_agent: LogosAIAgent):
    """LogosAI 에이전트를 기존 에이전트로 래핑"""
    if not LEGACY_MODULES_AVAILABLE:
        raise ImportError("기존 에이전트 모듈을 가져올 수 없습니다.")
    return LogosAgentWrapper(logos_agent) 