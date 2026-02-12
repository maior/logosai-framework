"""
LogosAI 에이전트 기본 클래스 모듈

이 모듈은 모든 LogosAI 에이전트의 기본이 되는 클래스를 정의합니다.
"""

import asyncio
import json
from typing import Any, Dict, List, Optional, Union, Callable
from datetime import datetime
import uuid
import logging

from ..config import AgentConfig
from ..types import AgentType, AgentResponseType, AgentResponse
from ..message_bus import MessageBus, Message

# 로깅 설정
logger = logging.getLogger(__name__)


class AgentResponse:
    """에이전트 응답 클래스
    
    LogosAI 에이전트의 응답을 표현하는 클래스입니다.
    """
    
    def __init__(
        self,
        type: AgentResponseType,
        content: Dict[str, Any],
        message: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ):
        """에이전트 응답 초기화
        
        Args:
            type: 응답 유형
            content: 응답 내용 (딕셔너리)
            message: 응답 메시지 (사람이 읽을 수 있는 형태)
            metadata: 추가 메타데이터
        """
        self.type = type
        self.content = content
        self.message = message
        self.metadata = metadata or {}
    
    @classmethod
    def error(cls, message: str, content: Optional[Dict[str, Any]] = None) -> 'AgentResponse':
        """오류 응답 생성
        
        Args:
            message: 오류 메시지
            content: 추가 오류 내용 (선택 사항)
            
        Returns:
            생성된 오류 응답 객체
        """
        return cls(
            type=AgentResponseType.ERROR,
            content=content or {"error": message},
            message=message,
            metadata={"is_error": True}
        )
    
    @classmethod
    def success(cls, message: str, content: Optional[Dict[str, Any]] = None) -> 'AgentResponse':
        """성공 응답 생성
        
        Args:
            message: 성공 메시지
            content: 응답 내용 (선택 사항)
            
        Returns:
            생성된 성공 응답 객체
        """
        return cls(
            type=AgentResponseType.SUCCESS,
            content=content or {"result": message},
            message=message,
            metadata={"is_error": False}
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """응답을 딕셔너리로 변환
        
        Returns:
            응답 데이터를 담은 딕셔너리
        """
        return {
            "type": str(self.type),
            "content": self.content,
            "message": self.message,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentResponse':
        """딕셔너리에서 응답 객체 생성
        
        Args:
            data: 응답 데이터를 담은 딕셔너리
            
        Returns:
            생성된 응답 객체
        """
        return cls(
            type=AgentResponseType.from_string(data.get("type", "UNKNOWN")),
            content=data.get("content", {}),
            message=data.get("message", ""),
            metadata=data.get("metadata", {})
        )
    
    def __str__(self) -> str:
        """문자열 표현 반환"""
        return f"AgentResponse({self.type}, message='{self.message}')"


class LogosAIAgent:
    """
    LogosAI 에이전트 기본 클래스 - 이 클래스를 상속받아 커스텀 에이전트를 만듭니다.
    
    예제:
    ```python
    from logosai import LogosAIAgent
    
    class MySearchAgent(LogosAIAgent):
        def __init__(self, name="검색 에이전트", api_key=None):
            config = AgentConfig(
                name=name,
                agent_type=AgentType.INTERNET_SEARCH,
                description="인터넷에서 정보를 검색하는 에이전트",
                api_config={"api_key": api_key} if api_key else {}
            )
            super().__init__(config)
        
        async def process_query(self, query, context=None):
            # 검색 로직 구현
            result = {"result": f"검색 결과: {query}"}
            return AgentResponse(
                type=AgentResponseType.TEXT,
                content=result,
                message="검색을 완료했습니다"
            )
    ```
    """
    
    def __init__(self, config: AgentConfig):
        """
        에이전트 초기화
        
        Args:
            config: 에이전트 설정 객체
        """
        self.config = config
        self.agent_id = config.name.lower().replace(" ", "_")
        self.name = config.name
        self.description = config.description
        self.agent_type = config.agent_type
        self.api_config = config.api_config
        self.llm_config = config.llm_config
        
        # 내부 상태 관리
        self.initialized = False
        self.message_bus = None
        self.history = []
        self._subscriptions = {}
        
    def add_to_history(self, entry: Dict[str, Any]) -> None:
        """
        에이전트 히스토리에 항목 추가
        
        Args:
            entry: 히스토리에 추가할 항목
        """
        if not isinstance(entry, dict):
            entry = {"data": entry, "timestamp": datetime.now().isoformat()}
        elif "timestamp" not in entry:
            entry["timestamp"] = datetime.now().isoformat()
            
        self.history.append(entry)
        
        # 히스토리 크기 제한 (기본 100개)
        max_history = 100
        if len(self.history) > max_history:
            self.history = self.history[-max_history:]
    
    async def initialize(self) -> bool:
        """
        에이전트 초기화 - 필요한 리소스를 설정합니다.
        
        Returns:
            초기화 성공 여부
        """
        if self.initialized:
            return True
            
        try:
            # 메시지 버스 초기화
            self.message_bus = MessageBus()
            await self.message_bus.start()
            
            # 초기화 성공
            self.initialized = True
            return True
        except Exception as e:
            print(f"에이전트 초기화 오류: {str(e)}")
            return False
    
    async def shutdown(self) -> None:
        """
        에이전트 종료 - 리소스를 정리합니다.
        """
        # 메시지 버스 구독 해제
        if self.message_bus and self._subscriptions:
            for subscription_id in self._subscriptions.values():
                await self.message_bus.unsubscribe(subscription_id)
            self._subscriptions = {}
            
        # 메시지 버스 종료
        if self.message_bus:
            await self.message_bus.stop()
            self.message_bus = None
            
        self.initialized = False
    
    def validate_input(self, input_data: Any) -> bool:
        """
        입력 데이터 유효성 검사
        
        Args:
            input_data: 검증할 입력 데이터
            
        Returns:
            데이터 유효성 여부
        """
        # None이면 유효하지 않음
        if input_data is None:
            return False
            
        # 문자열이면 비어있지 않은지 확인
        if isinstance(input_data, str):
            return bool(input_data.strip())
            
        # 딕셔너리/리스트면 비어있지 않은지 확인
        if isinstance(input_data, (dict, list)):
            return bool(input_data)
            
        # 그 외 객체는 기본적으로 유효함
        return True
    
    async def process(self, input_data: Any, context: Dict[str, Any] = None) -> AgentResponse:
        """
        입력 데이터 처리 메인 로직
        
        Args:
            input_data: 처리할 입력 데이터
            context: 추가 컨텍스트 데이터
            
        Returns:
            처리 결과
        """
        if not self.initialized:
            await self.initialize()
            
        start_time = datetime.now()
        
        try:
            # 입력 유효성 검사
            if not self.validate_input(input_data):
                return AgentResponse.error("유효하지 않은 입력입니다")
                
            # 전처리
            processed_input = self._preprocess_input(input_data)
            
            # 문자열 입력을 처리하는 경우
            if isinstance(processed_input, str):
                # process_query 호출
                result = await self.process_query(processed_input, context)
                
                # 결과가 이미 AgentResponse인 경우 그대로 반환
                if isinstance(result, AgentResponse):
                    self._update_history(input_data, result)
                    return result
                    
                # 결과가 dict인 경우 AgentResponse로 변환
                if isinstance(result, dict):
                    response = AgentResponse(
                        type=AgentResponseType.TEXT,
                        content=result,
                        message=result.get("message", "")
                    )
                    self._update_history(input_data, response)
                    return response
                    
                # 그 외 결과는 TEXT 타입으로 감싸서 반환
                response = AgentResponse(
                    type=AgentResponseType.TEXT,
                    content={"result": result},
                    message=str(result)
                )
                self._update_history(input_data, response)
                return response
                
            # 딕셔너리 입력을 처리하는 경우
            elif isinstance(processed_input, dict):
                # 입력에 query 필드가 있는 경우 process_query 호출
                if "query" in processed_input:
                    result = await self.process_query(
                        processed_input["query"], 
                        {**processed_input, **(context or {})}
                    )
                else:
                    # 그 외 경우 process_data 호출
                    result = await self.process_data(processed_input, context)
                    
                # 결과 처리
                if isinstance(result, AgentResponse):
                    self._update_history(input_data, result)
                    return result
                    
                if isinstance(result, dict):
                    response = AgentResponse(
                        type=AgentResponseType.TEXT,
                        content=result,
                        message=result.get("message", "")
                    )
                    self._update_history(input_data, response)
                    return response
                    
                response = AgentResponse(
                    type=AgentResponseType.TEXT,
                    content={"result": result},
                    message=str(result)
                )
                self._update_history(input_data, response)
                return response
            
            # 그 외 타입의 입력은 process_data로 처리
            else:
                result = await self.process_data(processed_input, context)
                
                # 결과 처리
                if isinstance(result, AgentResponse):
                    self._update_history(input_data, result)
                    return result
                    
                if isinstance(result, dict):
                    response = AgentResponse(
                        type=AgentResponseType.TEXT,
                        content=result,
                        message=result.get("message", "")
                    )
                    self._update_history(input_data, response)
                    return response
                    
                response = AgentResponse(
                    type=AgentResponseType.TEXT,
                    content={"result": result},
                    message=str(result)
                )
                self._update_history(input_data, response)
                return response
                
        except Exception as e:
            # 오류 처리
            error_message = f"처리 중 오류 발생: {str(e)}"
            error_response = AgentResponse.error(error_message)
            self._update_history(input_data, error_response)
            return error_response
            
        finally:
            # 처리 시간 계산 및 로깅
            processing_time = (datetime.now() - start_time).total_seconds()
            print(f"[{self.name}] 처리 시간: {processing_time:.2f}초")
    
    async def process_query(self, query: str, context: Dict[str, Any] = None) -> Union[Dict[str, Any], AgentResponse]:
        """
        문자열 쿼리 처리 - 하위 클래스에서 재정의합니다.
        
        Args:
            query: 처리할 쿼리 문자열
            context: 추가 컨텍스트 데이터
            
        Returns:
            처리 결과
        """
        # 상속받은 클래스에서 구현해야 함
        return AgentResponse(
            type=AgentResponseType.TEXT,
            content={"query": query, "message": "이 메서드는 하위 클래스에서 구현해야 합니다."},
            message="이 메서드는 하위 클래스에서 구현해야 합니다."
        )
    
    async def process_data(self, data: Any, context: Dict[str, Any] = None) -> Union[Dict[str, Any], AgentResponse]:
        """
        일반 데이터 처리 - 하위 클래스에서 재정의합니다.
        
        Args:
            data: 처리할 데이터
            context: 추가 컨텍스트 데이터
            
        Returns:
            처리 결과
        """
        # 기본적으로 process_query로 위임 (문자열로 변환)
        try:
            if isinstance(data, dict) and "query" in data:
                return await self.process_query(data["query"], context or data)
                
            # 딕셔너리를 JSON 문자열로 변환
            if isinstance(data, dict):
                query = json.dumps(data, ensure_ascii=False)
            else:
                query = str(data)
                
            return await self.process_query(query, context)
        except Exception as e:
            return AgentResponse.error(f"데이터 처리 오류: {str(e)}")
    
    def _preprocess_input(self, input_data: Any) -> Any:
        """
        입력 데이터 전처리
        
        Args:
            input_data: 전처리할 입력 데이터
            
        Returns:
            전처리된 데이터
        """
        if isinstance(input_data, str):
            return input_data.strip()
            
        if isinstance(input_data, dict):
            return input_data
            
        return input_data
    
    def _update_history(self, input_data: Any, result: AgentResponse) -> None:
        """
        처리 결과를 히스토리에 기록
        
        Args:
            input_data: 입력 데이터
            result: 처리 결과
        """
        try:
            # 입력 처리
            if isinstance(input_data, str):
                input_value = input_data
            elif isinstance(input_data, dict):
                input_value = json.dumps(input_data, ensure_ascii=False)
            else:
                input_value = str(input_data)
                
            # 결과 처리
            if isinstance(result, AgentResponse):
                result_value = result.to_dict()
            elif isinstance(result, dict):
                result_value = result
            else:
                result_value = {"result": str(result)}
                
            # 히스토리 항목 구성
            entry = {
                "timestamp": datetime.now().isoformat(),
                "input": input_value,
                "result": result_value,
                "type": getattr(result, "type", "unknown").value if hasattr(result, "type") else "unknown"
            }
            
            # 히스토리에 추가
            self.add_to_history(entry)
        except Exception as e:
            print(f"히스토리 업데이트 오류: {str(e)}")
    
    def run_async(self, coroutine):
        """
        비동기 함수를 동기적으로 실행하는 유틸리티 메소드
        
        Args:
            coroutine: 실행할 코루틴
            
        Returns:
            코루틴 실행 결과
        """
        try:
            # 현재 이벤트 루프 가져오기 시도
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # 이벤트 루프가 없으면 새로 생성
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        # 이벤트 루프 실행 여부에 따라 처리
        if loop.is_running():
            # 루프가 실행 중이면 future 사용
            future = asyncio.run_coroutine_threadsafe(coroutine, loop)
            return future.result()
        else:
            # 루프가 실행 중이 아니면 직접 실행
            return loop.run_until_complete(coroutine)

    # 동기 메소드 - 비동기 메소드를 감싸서 편리하게 사용할 수 있게 함
    def sync_process(self, input_data: Any, context: Dict[str, Any] = None) -> AgentResponse:
        """
        동기 방식으로 입력 처리 (비동기 process 메소드의 동기 래퍼)
        
        Args:
            input_data: 처리할 입력 데이터
            context: 추가 컨텍스트 데이터
            
        Returns:
            처리 결과
        """
        return self.run_async(self.process(input_data, context))
        
    def sync_initialize(self) -> bool:
        """
        동기 방식으로 에이전트 초기화 (비동기 initialize 메소드의 동기 래퍼)
        
        Returns:
            초기화 성공 여부
        """
        return self.run_async(self.initialize())
        
    def sync_shutdown(self) -> None:
        """
        동기 방식으로 에이전트 종료 (비동기 shutdown 메소드의 동기 래퍼)
        """
        return self.run_async(self.shutdown()) 

    def get_info(self) -> Dict[str, Any]:
        """에이전트 정보 조회
        
        Returns:
            에이전트 정보를 담은 딕셔너리
        """
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "type": str(self.agent_type),
            "description": self.description,
            "initialized": self.initialized
        }


def create_agent(
    agent_type: Union[AgentType, str],
    config: Optional[AgentConfig] = None,
    **kwargs
) -> LogosAIAgent:
    """에이전트 생성 함수
    
    지정된 유형과 설정으로 에이전트를 생성합니다.
    
    Args:
        agent_type: 에이전트 유형
        config: 에이전트 설정 (없으면 자동 생성)
        **kwargs: 추가 설정 매개변수
        
    Returns:
        생성된 에이전트 객체
        
    Raises:
        ValueError: 지원하지 않는 에이전트 유형
    """
    # 문자열인 경우 AgentType으로 변환
    if isinstance(agent_type, str):
        agent_type = AgentType.from_string(agent_type)
    
    # 설정이 없으면 자동 생성
    if config is None:
        agent_name = kwargs.pop("name", f"{str(agent_type).capitalize()} Agent")
        config = AgentConfig(
            name=agent_name,
            agent_type=agent_type,
            description=kwargs.pop("description", f"LogosAI {str(agent_type)} 에이전트"),
            config=kwargs.pop("config", {}),
            api_config=kwargs.pop("api_config", {}),
            llm_config=kwargs.pop("llm_config", {})
        )
    
    # 에이전트 유형에 따라 적절한 클래스 선택
    if agent_type == AgentType.LLM_SEARCH:
        # 순환 참조를 방지하기 위해 여기서 임포트
        try:
            from .agents.llm_search import LLMSearchAgent
            return LLMSearchAgent(config=config, **kwargs)
        except ImportError:
            logger.warning("LLMSearchAgent를 가져올 수 없습니다. 기본 에이전트를 사용합니다.")
    
    elif agent_type == AgentType.INTERNET_SEARCH:
        try:
            from .agents.internet_search import InternetSearchAgent
            return InternetSearchAgent(config=config, **kwargs)
        except ImportError:
            logger.warning("InternetSearchAgent를 가져올 수 없습니다. 기본 에이전트를 사용합니다.")
    
    elif agent_type == AgentType.RAG_SEARCH:
        try:
            from .agents.rag_search import RAGSearchAgent
            return RAGSearchAgent(config=config, **kwargs)
        except ImportError:
            logger.warning("RAGSearchAgent를 가져올 수 없습니다. 기본 에이전트를 사용합니다.")
    
    elif agent_type == AgentType.CUSTOM:
        # 사용자 정의 에이전트의 경우 커스텀 클래스 필요
        custom_class = kwargs.pop("agent_class", None)
        if custom_class and issubclass(custom_class, LogosAIAgent):
            return custom_class(config=config, **kwargs)
        logger.warning("사용자 정의 에이전트 클래스가 제공되지 않았습니다. 기본 에이전트를 사용합니다.")
    
    # 기본 에이전트 반환
    return LogosAIAgent(config) 