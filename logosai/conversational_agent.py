"""
LogosAI 대화형 에이전트 시스템

이 모듈은 에이전트 개발을 간소화하는 통합 대화 시스템을 제공합니다.
"""

import asyncio
import logging
import inspect
from typing import Dict, Any, Optional, Union, List, Callable, Type
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps

from .agent import LogosAIAgent
from .agent_types import AgentType, AgentResponse, AgentResponseType
from .config import AgentConfig
from .types import MessageBusProtocol
from loguru import logger

# Django 서버 모듈들 (선택적 import)
import sys
import os

DJANGO_INTEGRATION_AVAILABLE = False
try:
    # Django 통합 — 환경변수로 명시적 활성화 시에만
    django_path = os.path.join(os.path.dirname(__file__), '../../logos_server')
    _want_django = os.getenv("LOGOSAI_DJANGO_INTEGRATION", "")
    if _want_django and os.path.isdir(os.path.join(django_path, 'app_agent')):
        if django_path not in sys.path:
            sys.path.append(django_path)

        from app_agent.agent_dialogue_protocol import (
            AgentDialogueMessage, MessageType, AgentCapabilityDiscovery
        )
        from app_agent.interactive_parameter_collector import (
            InteractiveParameterCollector, CollectionStrategy
        )
        DJANGO_INTEGRATION_AVAILABLE = True
except ImportError:
    DJANGO_INTEGRATION_AVAILABLE = False
    
    # 더미 클래스 정의
    class AgentDialogueMessage:
        def __init__(self, **kwargs):
            pass
    
    class MessageType:
        CAPABILITY_INQUIRY = "capability_inquiry"
        PARAMETER_CHECK = "parameter_check"
        EXECUTION_REQUEST = "execution_request"
    
    class AgentCapabilityDiscovery:
        def __init__(self):
            pass
    
    class InteractiveParameterCollector:
        def __init__(self):
            pass
    
    class CollectionStrategy:
        SMART_GROUPING = "smart_grouping"


@dataclass
class ConversationContext:
    """대화 컨텍스트 정보"""
    session_id: str = ""
    user_id: Optional[str] = None
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    collected_parameters: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass 
class ParameterDefinition:
    """파라미터 정의"""
    name: str
    description: str
    required: bool = True
    parameter_type: str = "string"
    default_value: Any = None
    validation_rules: Optional[Dict[str, Any]] = None
    collection_prompt: Optional[str] = None


@dataclass
class VisualizationConfig:
    """시각화 설정"""
    chart_type: str = "line"  # line, bar, pie, scatter 등
    x_axis: Optional[str] = None
    y_axis: Optional[str] = None
    title: Optional[str] = None
    auto_generate: bool = True
    chart_options: Dict[str, Any] = field(default_factory=dict)


class ConversationalAgent(LogosAIAgent):
    """
    대화형 에이전트 베이스 클래스
    
    자동 파라미터 수집, 대화 프로토콜, 시각화 지원 등을 제공하는
    고급 에이전트 기본 클래스입니다.
    
    Features:
    - 자동 파라미터 수집 및 검증
    - 대화 프로토콜 자동 처리
    - 시각화 데이터 자동 생성
    - 메시지 버스 통합
    - 상태 관리 및 라이프사이클
    """
    
    def __init__(self, config: Optional[AgentConfig] = None, **kwargs):
        """대화형 에이전트 초기화
        
        Args:
            config: 에이전트 설정
            **kwargs: 추가 설정 (parameters, visualization 등)
        """
        if config is None:
            config = AgentConfig(
                name="ConversationalAgent",
                agent_type=AgentType.GENERAL,
                description="대화형 에이전트",
                config={}
            )
        
        super().__init__(config)
        
        # 대화 관련 속성
        self.conversation_context: Optional[ConversationContext] = None
        self.parameters: Dict[str, ParameterDefinition] = {}
        self.visualization_config: Optional[VisualizationConfig] = None
        self.message_bus: Optional[MessageBusProtocol] = None
        
        # Django 통합 컴포넌트
        if DJANGO_INTEGRATION_AVAILABLE:
            self.dialogue_protocol = AgentCapabilityDiscovery()
            self.parameter_collector = InteractiveParameterCollector()
        else:
            self.dialogue_protocol = None
            self.parameter_collector = None
        
        # 설정에서 파라미터 및 시각화 구성 로드
        self._load_from_kwargs(kwargs)
        
        logger.info(f"ConversationalAgent 초기화: {self.config.name}")
    
    def _load_from_kwargs(self, kwargs: Dict[str, Any]):
        """kwargs에서 설정 로드"""
        # 파라미터 정의 로드
        if 'parameters' in kwargs:
            for param_name, param_config in kwargs['parameters'].items():
                if isinstance(param_config, dict):
                    self.parameters[param_name] = ParameterDefinition(
                        name=param_name,
                        **param_config
                    )
                elif isinstance(param_config, ParameterDefinition):
                    self.parameters[param_name] = param_config
        
        # 시각화 설정 로드
        if 'visualization' in kwargs:
            viz_config = kwargs['visualization']
            if isinstance(viz_config, dict):
                self.visualization_config = VisualizationConfig(**viz_config)
            elif isinstance(viz_config, VisualizationConfig):
                self.visualization_config = viz_config
    
    async def initialize(self) -> bool:
        """에이전트 초기화"""
        try:
            # 부모 클래스 초기화
            if not await super().initialize():
                return False
            
            # 메시지 버스 연결
            await self._connect_message_bus()
            
            # 대화 프로토콜 등록
            await self._register_dialogue_capabilities()
            
            logger.info(f"ConversationalAgent {self.config.name} 초기화 완료")
            return True
            
        except Exception as e:
            logger.error(f"ConversationalAgent 초기화 실패: {e}")
            return False
    
    async def _connect_message_bus(self):
        """메시지 버스 연결"""
        try:
            # MessageBus 동적 import
            from .message_bus import MessageBus
            self.message_bus = MessageBus.get_instance()
            
            # 에이전트 상태 토픽 구독
            await self.message_bus.subscribe(
                f"agent/{self.id}/status",
                self._handle_status_message
            )
            
            logger.info(f"메시지 버스 연결 완료: {self.id}")
            
        except ImportError:
            logger.warning("MessageBus를 찾을 수 없습니다. 메시지 버스 기능이 비활성화됩니다.")
            self.message_bus = None
        except Exception as e:
            logger.error(f"메시지 버스 연결 실패: {e}")
            self.message_bus = None
    
    async def _register_dialogue_capabilities(self):
        """대화 능력 등록"""
        if not DJANGO_INTEGRATION_AVAILABLE or not self.dialogue_protocol:
            return
        
        try:
            # 에이전트 능력 정보 구성
            capabilities = {
                "parameters": {
                    name: {
                        "type": param.parameter_type,
                        "required": param.required,
                        "description": param.description,
                        "default": param.default_value
                    }
                    for name, param in self.parameters.items()
                },
                "visualization": self.visualization_config.__dict__ if self.visualization_config else None,
                "conversation_support": True,
                "auto_parameter_collection": len(self.parameters) > 0
            }
            
            # 대화 프로토콜에 등록
            # TODO: 실제 구현에서는 dialogue_protocol.register_agent() 호출
            logger.info(f"대화 능력 등록 완료: {self.config.name}")
            
        except Exception as e:
            logger.error(f"대화 능력 등록 실패: {e}")
    
    async def _handle_status_message(self, message: Dict[str, Any]):
        """상태 메시지 처리"""
        try:
            logger.debug(f"상태 메시지 수신: {message}")
            # 상태 메시지 처리 로직 구현
        except Exception as e:
            logger.error(f"상태 메시지 처리 실패: {e}")
    
    async def start_conversation(self, 
                               session_id: str,
                               user_id: Optional[str] = None,
                               initial_context: Optional[Dict[str, Any]] = None) -> ConversationContext:
        """대화 세션 시작
        
        Args:
            session_id: 세션 ID
            user_id: 사용자 ID
            initial_context: 초기 컨텍스트
        
        Returns:
            ConversationContext: 대화 컨텍스트
        """
        self.conversation_context = ConversationContext(
            session_id=session_id,
            user_id=user_id,
            metadata=initial_context or {}
        )
        
        logger.info(f"대화 세션 시작: {session_id}")
        return self.conversation_context
    
    async def collect_missing_parameters(self, 
                                       query: str,
                                       existing_params: Optional[Dict[str, Any]] = None,
                                       websocket_handler: Optional[Callable] = None) -> Dict[str, Any]:
        """누락된 파라미터 자동 수집
        
        Args:
            query: 사용자 쿼리
            existing_params: 기존 파라미터
            websocket_handler: WebSocket 핸들러
        
        Returns:
            Dict[str, Any]: 수집된 파라미터
        """
        if not self.parameters:
            return existing_params or {}
        
        # 기존 파라미터와 병합
        collected_params = existing_params.copy() if existing_params else {}
        
        # 필수 파라미터 중 누락된 것들 찾기
        missing_params = []
        for name, param_def in self.parameters.items():
            if param_def.required and name not in collected_params:
                missing_params.append(param_def)
        
        if not missing_params:
            logger.info("모든 필수 파라미터가 제공되었습니다")
            return collected_params
        
        # Django 통합 파라미터 수집기 사용
        if DJANGO_INTEGRATION_AVAILABLE and self.parameter_collector and websocket_handler:
            try:
                # QueryAnalysis 모킹 (실제로는 쿼리 분석 결과 사용)
                from dataclasses import dataclass
                
                @dataclass
                class MockQueryAnalysis:
                    missing_parameters: List[str]
                    complexity_score: float = 0.5
                    requires_interaction: bool = True
                
                analysis = MockQueryAnalysis(
                    missing_parameters=[p.name for p in missing_params]
                )
                
                # 파라미터 수집 실행
                additional_params = await self.parameter_collector.collect_parameters(
                    session_id=self.conversation_context.session_id if self.conversation_context else "default",
                    analysis=analysis,
                    strategy=CollectionStrategy.SMART_GROUPING,
                    websocket_handler=websocket_handler
                )
                
                collected_params.update(additional_params)
                logger.info(f"파라미터 수집 완료: {list(additional_params.keys())}")
                
            except Exception as e:
                logger.error(f"자동 파라미터 수집 실패: {e}")
                # 폴백: 기본값 사용
                for param_def in missing_params:
                    if param_def.default_value is not None:
                        collected_params[param_def.name] = param_def.default_value
        else:
            # 기본값으로 폴백
            for param_def in missing_params:
                if param_def.default_value is not None:
                    collected_params[param_def.name] = param_def.default_value
                    logger.info(f"기본값 사용: {param_def.name} = {param_def.default_value}")
        
        return collected_params
    
    async def generate_visualization_data(self, 
                                        data: Any,
                                        chart_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """시각화 데이터 자동 생성
        
        Args:
            data: 원본 데이터
            chart_type: 차트 타입 (선택사항)
        
        Returns:
            Dict[str, Any]: Chart.js 호환 차트 데이터
        """
        if not self.visualization_config and not chart_type:
            return None
        
        try:
            # 설정에서 차트 타입 결정
            final_chart_type = chart_type or (
                self.visualization_config.chart_type if self.visualization_config else "line"
            )
            
            # 데이터 구조 분석
            chart_data = await self._analyze_and_format_data(data, final_chart_type)
            
            if chart_data:
                logger.info(f"시각화 데이터 생성 완료: {final_chart_type}")
                return chart_data
            
        except Exception as e:
            logger.error(f"시각화 데이터 생성 실패: {e}")
        
        return None
    
    async def _analyze_and_format_data(self, data: Any, chart_type: str) -> Optional[Dict[str, Any]]:
        """데이터 분석 및 포맷팅"""
        # 기본 구현 - 서브클래스에서 오버라이드 가능
        if isinstance(data, dict):
            if 'labels' in data and 'datasets' in data:
                # 이미 Chart.js 형식
                return {
                    "type": chart_type,
                    "data": data,
                    "options": self._get_default_chart_options()
                }
            
            # 간단한 키-값 데이터를 차트로 변환
            if len(data) > 0:
                labels = list(data.keys())
                values = list(data.values())
                
                return {
                    "type": chart_type,
                    "data": {
                        "labels": labels,
                        "datasets": [{
                            "label": "Data",
                            "data": values,
                            "backgroundColor": "rgba(75, 192, 192, 0.2)",
                            "borderColor": "rgba(75, 192, 192, 1)",
                            "borderWidth": 1
                        }]
                    },
                    "options": self._get_default_chart_options()
                }
        
        return None
    
    def _get_default_chart_options(self) -> Dict[str, Any]:
        """기본 차트 옵션"""
        options = {
            "responsive": True,
            "plugins": {
                "legend": {
                    "position": "top"
                }
            }
        }
        
        if self.visualization_config:
            if self.visualization_config.title:
                options["plugins"]["title"] = {
                    "display": True,
                    "text": self.visualization_config.title
                }
            
            # 추가 옵션 병합
            if self.visualization_config.chart_options:
                options.update(self.visualization_config.chart_options)
        
        return options
    
    async def process_with_conversation(self, 
                                      request: Union[str, Dict[str, Any]],
                                      websocket_handler: Optional[Callable] = None) -> AgentResponse:
        """대화형 처리 (자동 파라미터 수집 포함)
        
        Args:
            request: 사용자 요청
            websocket_handler: WebSocket 핸들러
        
        Returns:
            AgentResponse: 처리 결과
        """
        try:
            # 쿼리 추출
            query = request if isinstance(request, str) else request.get("query", "")
            existing_params = request.get("parameters", {}) if isinstance(request, dict) else {}
            
            # 파라미터 수집
            collected_params = await self.collect_missing_parameters(
                query=query,
                existing_params=existing_params,
                websocket_handler=websocket_handler
            )
            
            # 실제 처리 (서브클래스에서 구현)
            result = await self.execute_with_parameters(query, collected_params)
            
            # 시각화 데이터 생성 (필요한 경우)
            if self.visualization_config and self.visualization_config.auto_generate:
                chart_data = await self.generate_visualization_data(result)
                if chart_data:
                    # 결과에 차트 데이터 추가
                    if isinstance(result, dict):
                        result["chart_data"] = chart_data
                        result["visualization_type"] = chart_data["type"]
            
            return AgentResponse(
                type=AgentResponseType.SUCCESS,
                content=result,
                message="처리 완료",
                metadata={
                    "parameters_used": collected_params,
                    "conversation_enabled": True
                }
            )
            
        except Exception as e:
            logger.error(f"대화형 처리 실패: {e}")
            return AgentResponse(
                type=AgentResponseType.ERROR,
                content={"error": str(e)},
                message=f"처리 중 오류 발생: {e}",
                metadata={"error": True}
            )
    
    async def execute_with_parameters(self, query: str, parameters: Dict[str, Any]) -> Any:
        """파라미터를 사용한 실제 실행 (서브클래스에서 구현)
        
        Args:
            query: 사용자 쿼리
            parameters: 수집된 파라미터
        
        Returns:
            Any: 실행 결과
        """
        # 기본 구현 - 서브클래스에서 오버라이드 필요
        return {
            "message": "ConversationalAgent.execute_with_parameters()를 오버라이드하세요",
            "query": query,
            "parameters": parameters
        }
    
    async def process(self, request: Union[str, Dict[str, Any]]) -> AgentResponse:
        """표준 처리 메서드 (LogosAIAgent 호환성)"""
        return await self.process_with_conversation(request)
    
    async def shutdown(self):
        """에이전트 종료"""
        try:
            # 메시지 버스 연결 해제
            if self.message_bus:
                await self.message_bus.unsubscribe_all(f"agent/{self.id}")
            
            # 대화 세션 정리
            self.conversation_context = None
            
            logger.info(f"ConversationalAgent {self.config.name} 종료 완료")
            
        except Exception as e:
            logger.error(f"ConversationalAgent 종료 중 오류: {e}")
        
        return await super().shutdown()


# 편의 데코레이터들

def auto_param_collection(parameters: List[Union[str, ParameterDefinition]]):
    """자동 파라미터 수집 데코레이터
    
    Args:
        parameters: 파라미터 리스트
    
    Usage:
        @auto_param_collection(['location', 'period'])
        class WeatherAgent(ConversationalAgent):
            pass
    """
    def decorator(cls: Type[ConversationalAgent]):
        # 클래스 초기화 시 파라미터 자동 설정
        original_init = cls.__init__
        
        @wraps(original_init)
        def new_init(self, *args, **kwargs):
            # 파라미터 정의 추가
            param_defs = {}
            for param in parameters:
                if isinstance(param, str):
                    param_defs[param] = ParameterDefinition(
                        name=param,
                        description=f"{param} parameter",
                        required=True
                    )
                elif isinstance(param, ParameterDefinition):
                    param_defs[param.name] = param
            
            kwargs.setdefault('parameters', {}).update(param_defs)
            original_init(self, *args, **kwargs)
        
        cls.__init__ = new_init
        return cls
    
    return decorator


def visualizable(chart_type: str = "line", 
                x_axis: Optional[str] = None,
                y_axis: Optional[str] = None,
                title: Optional[str] = None,
                auto_generate: bool = True,
                **chart_options):
    """시각화 지원 데코레이터
    
    Args:
        chart_type: 차트 타입
        x_axis: X축 필드명
        y_axis: Y축 필드명  
        title: 차트 제목
        auto_generate: 자동 생성 여부
        **chart_options: 추가 차트 옵션
    
    Usage:
        @visualizable(chart_type='line', x_axis='time', y_axis='temperature')
        class WeatherAgent(ConversationalAgent):
            pass
    """
    def decorator(cls: Type[ConversationalAgent]):
        original_init = cls.__init__
        
        @wraps(original_init)
        def new_init(self, *args, **kwargs):
            # 시각화 설정 추가
            viz_config = VisualizationConfig(
                chart_type=chart_type,
                x_axis=x_axis,
                y_axis=y_axis,
                title=title,
                auto_generate=auto_generate,
                chart_options=chart_options
            )
            
            kwargs['visualization'] = viz_config
            original_init(self, *args, **kwargs)
        
        cls.__init__ = new_init
        return cls
    
    return decorator


def conversational_agent(name: Optional[str] = None,
                        agent_type: AgentType = AgentType.GENERAL,
                        description: Optional[str] = None):
    """대화형 에이전트 클래스 데코레이터
    
    Args:
        name: 에이전트 이름
        agent_type: 에이전트 타입
        description: 에이전트 설명
    
    Usage:
        @conversational_agent(name="Weather Agent", agent_type=AgentType.WEATHER)
        class WeatherAgent(ConversationalAgent):
            pass
    """
    def decorator(cls: Type[ConversationalAgent]):
        original_init = cls.__init__
        
        @wraps(original_init)
        def new_init(self, config: Optional[AgentConfig] = None, *args, **kwargs):
            if config is None:
                config = AgentConfig(
                    name=name or cls.__name__,
                    agent_type=agent_type,
                    description=description or f"{cls.__name__} conversational agent",
                    config={}
                )
            
            original_init(self, config, *args, **kwargs)
        
        cls.__init__ = new_init
        return cls
    
    return decorator


# 예제 및 편의 함수

async def create_simple_conversational_agent(
    name: str,
    execute_func: Callable[[str, Dict[str, Any]], Any],
    parameters: Optional[List[Union[str, ParameterDefinition]]] = None,
    visualization: Optional[VisualizationConfig] = None
) -> ConversationalAgent:
    """간단한 대화형 에이전트 생성 헬퍼
    
    Args:
        name: 에이전트 이름
        execute_func: 실행 함수
        parameters: 파라미터 정의
        visualization: 시각화 설정
    
    Returns:
        ConversationalAgent: 생성된 에이전트
    """
    
    class SimpleConversationalAgent(ConversationalAgent):
        async def execute_with_parameters(self, query: str, parameters: Dict[str, Any]) -> Any:
            return await execute_func(query, parameters)
    
    # 파라미터 설정 변환
    param_kwargs = {}
    if parameters:
        param_defs = {}
        for param in parameters:
            if isinstance(param, str):
                param_defs[param] = ParameterDefinition(
                    name=param,
                    description=f"{param} parameter",
                    required=True
                )
            elif isinstance(param, ParameterDefinition):
                param_defs[param.name] = param
        param_kwargs['parameters'] = param_defs
    
    # 시각화 설정
    if visualization:
        param_kwargs['visualization'] = visualization
    
    # 에이전트 설정
    config = AgentConfig(
        name=name,
        agent_type=AgentType.GENERAL,
        description=f"Simple conversational agent: {name}",
        config={}
    )
    
    agent = SimpleConversationalAgent(config, **param_kwargs)
    await agent.initialize()
    return agent


if __name__ == "__main__":
    # 사용 예제
    async def example_usage():
        """ConversationalAgent 사용 예제"""
        
        # 예제 1: 데코레이터 사용
        @conversational_agent(name="Example Agent")
        @auto_param_collection(['location', 'period'])
        @visualizable(chart_type='line', title='Temperature Trend')
        class ExampleAgent(ConversationalAgent):
            async def execute_with_parameters(self, query: str, parameters: Dict[str, Any]) -> Any:
                return {
                    "message": f"Query: {query}",
                    "location": parameters.get('location'),
                    "period": parameters.get('period'),
                    "data": [20, 22, 24, 23, 21, 19, 18]  # 예제 데이터
                }
        
        # 에이전트 생성 및 초기화
        agent = ExampleAgent()
        await agent.initialize()
        
        # 대화 세션 시작
        context = await agent.start_conversation("session_123")
        
        # 처리 실행 (파라미터가 자동으로 수집됨)
        result = await agent.process_with_conversation("서울의 일주일 날씨를 보여줘")

        logger.info(f"결과: {result.message}")
        logger.info(f"내용: {result.content}")
        
        await agent.shutdown()
    
    # 예제 실행
    asyncio.run(example_usage())