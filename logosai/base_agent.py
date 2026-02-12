"""
Enhanced LogosAI Base Agent Classes

이 모듈은 LogosAI 에이전트 개발을 위한 향상된 기본 클래스들을 제공합니다.
다양한 유형의 에이전트를 쉽게 만들 수 있도록 템플릿 메서드와 유틸리티를 포함합니다.
"""

import asyncio
import json
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Any, Optional, List, Union, Tuple
from loguru import logger

from .types import AgentType, AgentResponse, AgentResponseType
from .config import AgentConfig
from .agent import LogosAIAgent


class EnhancedLogosAIAgent(LogosAIAgent, ABC):
    """향상된 LogosAI 에이전트 기본 클래스
    
    이 클래스는 다음과 같은 추가 기능을 제공합니다:
    - 자동 초기화 관리
    - 에러 핸들링 및 재시도 로직
    - 성능 모니터링
    - 로깅 표준화
    - 요청/응답 검증
    """
    
    def __init__(self, config: Optional[AgentConfig] = None):
        """에이전트 초기화
        
        Args:
            config: 에이전트 설정 (없으면 기본값 사용)
        """
        # 기본 설정 생성
        if config is None:
            config = self._create_default_config()
        
        super().__init__(config)
        
        # 추가 속성
        self.name = config.name
        self.description = config.description
        self.metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_processing_time": 0.0,
            "average_processing_time": 0.0
        }
        self.initialized = False
        self._initialization_lock = asyncio.Lock()
        
        logger.info(f"🚀 {self.name} 에이전트 생성 완료")
    
    @abstractmethod
    def _create_default_config(self) -> AgentConfig:
        """기본 설정 생성 (하위 클래스에서 구현)"""
        pass
    
    async def initialize(self) -> bool:
        """에이전트 초기화 (중복 초기화 방지)"""
        async with self._initialization_lock:
            if self.initialized:
                return True
            
            try:
                logger.info(f"🔧 {self.name} 초기화 시작...")
                success = await self._initialize_resources()
                if success:
                    self.initialized = True
                    logger.info(f"✅ {self.name} 초기화 완료")
                else:
                    logger.error(f"❌ {self.name} 초기화 실패")
                return success
            except Exception as e:
                logger.error(f"❌ {self.name} 초기화 중 오류: {str(e)}")
                return False
    
    @abstractmethod
    async def _initialize_resources(self) -> bool:
        """리소스 초기화 (하위 클래스에서 구현)"""
        pass
    
    async def process(self, request: Union[str, Dict[str, Any]]) -> AgentResponse:
        """요청 처리 (자동 초기화, 에러 핸들링, 메트릭 수집 포함)"""
        start_time = time.time()
        self.metrics["total_requests"] += 1
        
        try:
            # 자동 초기화
            if not self.initialized:
                init_success = await self.initialize()
                if not init_success:
                    self.metrics["failed_requests"] += 1
                    return self._create_error_response(
                        "에이전트 초기화 실패",
                        {"initialization_error": True}
                    )
            
            # 요청 파싱
            query, context = self._parse_request(request)
            
            # 요청 검증
            validation_error = self._validate_request(query, context)
            if validation_error:
                self.metrics["failed_requests"] += 1
                return self._create_error_response(validation_error)
            
            # 실제 처리 로직 실행
            logger.info(f"🔄 {self.name} 처리 시작: {query[:50]}...")
            response = await self._process_logic(query, context)
            
            # 성공 메트릭 업데이트
            self.metrics["successful_requests"] += 1
            
            return response
            
        except Exception as e:
            self.metrics["failed_requests"] += 1
            logger.error(f"❌ {self.name} 처리 중 오류: {str(e)}")
            return self._create_error_response(str(e), {"error_type": type(e).__name__})
        
        finally:
            # 처리 시간 메트릭 업데이트
            processing_time = time.time() - start_time
            self.metrics["total_processing_time"] += processing_time
            self.metrics["average_processing_time"] = (
                self.metrics["total_processing_time"] / self.metrics["total_requests"]
            )
            logger.info(f"⏱️ {self.name} 처리 시간: {processing_time:.2f}초")
    
    def _parse_request(self, request: Union[str, Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
        """요청 파싱"""
        if isinstance(request, str):
            return request, {}
        elif isinstance(request, dict):
            query = request.get("query", request.get("prompt", ""))
            context = {k: v for k, v in request.items() if k not in ["query", "prompt"]}
            return query, context
        else:
            return str(request), {}
    
    def _validate_request(self, query: str, context: Dict[str, Any]) -> Optional[str]:
        """요청 검증 (기본 구현)"""
        if not query or not query.strip():
            return "빈 쿼리는 처리할 수 없습니다"
        return None
    
    @abstractmethod
    async def _process_logic(self, query: str, context: Dict[str, Any]) -> AgentResponse:
        """실제 처리 로직 (하위 클래스에서 구현)"""
        pass
    
    def _create_error_response(self, error_message: str, metadata: Dict[str, Any] = None) -> AgentResponse:
        """표준화된 에러 응답 생성"""
        return AgentResponse(
            type=AgentResponseType.ERROR,
            content={
                "error": error_message,
                "agent": self.name
            },
            metadata={
                "timestamp": datetime.now().isoformat(),
                "agent_name": self.name,
                **(metadata or {})
            }
        )
    
    def _create_success_response(
        self, 
        content: Dict[str, Any], 
        metadata: Dict[str, Any] = None
    ) -> AgentResponse:
        """표준화된 성공 응답 생성"""
        return AgentResponse(
            type=AgentResponseType.SUCCESS,
            content=content,
            metadata={
                "timestamp": datetime.now().isoformat(),
                "agent_name": self.name,
                **(metadata or {})
            }
        )
    
    async def shutdown(self):
        """에이전트 종료 및 리소스 정리"""
        logger.info(f"🛑 {self.name} 종료 중...")
        try:
            await self._cleanup_resources()
            self.initialized = False
            logger.info(f"✅ {self.name} 종료 완료")
        except Exception as e:
            logger.error(f"❌ {self.name} 종료 중 오류: {str(e)}")
    
    async def _cleanup_resources(self):
        """리소스 정리 (하위 클래스에서 필요시 오버라이드)"""
        pass
    
    def get_metrics(self) -> Dict[str, Any]:
        """성능 메트릭 반환"""
        return self.metrics.copy()
    
    def get_status(self) -> Dict[str, Any]:
        """에이전트 상태 반환"""
        return {
            "name": self.name,
            "type": str(self.config.agent_type),
            "initialized": self.initialized,
            "metrics": self.get_metrics(),
            "description": self.description
        }


class ServiceBasedAgent(EnhancedLogosAIAgent):
    """서비스 기반 에이전트 (비즈니스 로직 분리)
    
    이 클래스는 에이전트 로직을 별도의 서비스 클래스로 분리하여
    테스트와 유지보수를 용이하게 합니다.
    """
    
    def __init__(self, config: Optional[AgentConfig] = None, service_class=None):
        """초기화
        
        Args:
            config: 에이전트 설정
            service_class: 사용할 서비스 클래스 (None이면 _create_service 메서드 사용)
        """
        super().__init__(config)
        self.service_class = service_class
        self.service = None
    
    async def _initialize_resources(self) -> bool:
        """서비스 초기화"""
        try:
            if self.service_class:
                self.service = self.service_class()
            else:
                self.service = await self._create_service()
            
            # 서비스에 initialize 메서드가 있으면 호출
            if hasattr(self.service, 'initialize'):
                await self.service.initialize()
            
            return True
        except Exception as e:
            logger.error(f"서비스 초기화 실패: {str(e)}")
            return False
    
    async def _create_service(self):
        """서비스 인스턴스 생성 (하위 클래스에서 필요시 오버라이드)"""
        raise NotImplementedError("service_class가 제공되지 않은 경우 _create_service를 구현해야 합니다")
    
    async def _cleanup_resources(self):
        """서비스 정리"""
        if self.service and hasattr(self.service, 'cleanup'):
            await self.service.cleanup()


class LLMPoweredAgent(ServiceBasedAgent):
    """LLM 기반 에이전트
    
    LLM을 사용하여 자연어 처리를 수행하는 에이전트의 기본 클래스입니다.
    """
    
    def __init__(self, config: Optional[AgentConfig] = None, service_class=None):
        super().__init__(config, service_class)
        self.llm_client = None
    
    async def _initialize_resources(self) -> bool:
        """LLM 클라이언트 초기화"""
        if not await super()._initialize_resources():
            return False
        
        try:
            from logosai.utils.llm_client import LLMClient
            
            # 설정에서 LLM 파라미터 추출
            llm_config = self.config.config.get("llm", {})
            self.llm_client = LLMClient(
                provider=llm_config.get("provider", "openai"),
                model=llm_config.get("model", "gpt-4"),
                temperature=llm_config.get("temperature", 0.7)
            )
            
            return True
        except Exception as e:
            logger.error(f"LLM 클라이언트 초기화 실패: {str(e)}")
            return False
    
    async def _invoke_llm(self, prompt: str, system_prompt: str = None) -> str:
        """LLM 호출 헬퍼 메서드"""
        if not self.llm_client:
            raise RuntimeError("LLM 클라이언트가 초기화되지 않았습니다")
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        response = await self.llm_client.invoke(messages)
        return response.content if hasattr(response, 'content') else str(response)


class APIBasedAgent(ServiceBasedAgent):
    """외부 API 기반 에이전트
    
    외부 API를 호출하여 작업을 수행하는 에이전트의 기본 클래스입니다.
    """
    
    def __init__(self, config: Optional[AgentConfig] = None, service_class=None):
        super().__init__(config, service_class)
        self.session = None
        self.api_config = {}
    
    async def _initialize_resources(self) -> bool:
        """API 클라이언트 초기화"""
        if not await super()._initialize_resources():
            return False
        
        try:
            import aiohttp
            
            # API 설정 추출
            self.api_config = self.config.config.get("api", {})
            
            # aiohttp 세션 생성
            timeout = aiohttp.ClientTimeout(total=self.api_config.get("timeout", 30))
            self.session = aiohttp.ClientSession(timeout=timeout)
            
            return True
        except Exception as e:
            logger.error(f"API 클라이언트 초기화 실패: {str(e)}")
            return False
    
    async def _cleanup_resources(self):
        """API 클라이언트 정리"""
        await super()._cleanup_resources()
        if self.session:
            await self.session.close()
    
    async def _make_api_request(
        self, 
        method: str, 
        url: str, 
        headers: Dict[str, str] = None,
        params: Dict[str, Any] = None,
        json_data: Dict[str, Any] = None,
        retry_count: int = 3
    ) -> Dict[str, Any]:
        """API 요청 헬퍼 메서드 (재시도 로직 포함)"""
        if not self.session:
            raise RuntimeError("API 세션이 초기화되지 않았습니다")
        
        for attempt in range(retry_count):
            try:
                async with self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_data
                ) as response:
                    response.raise_for_status()
                    return await response.json()
            except Exception as e:
                if attempt == retry_count - 1:
                    raise
                logger.warning(f"API 요청 실패 (시도 {attempt + 1}/{retry_count}): {str(e)}")
                await asyncio.sleep(2 ** attempt)  # 지수 백오프


class GameAgent(EnhancedLogosAIAgent):
    """게임 에이전트 기본 클래스
    
    HTML5 게임을 생성하는 에이전트의 기본 클래스입니다.
    """
    
    def __init__(self, config: Optional[AgentConfig] = None):
        super().__init__(config)
        self.game_templates = {}
    
    def _create_game_response(
        self, 
        game_html: str, 
        difficulty: str = "medium",
        theme: str = "classic",
        custom_message: str = ""
    ) -> AgentResponse:
        """게임 응답 생성"""
        # HTML을 iframe으로 감싸기
        escaped_html = game_html.replace('"', '&quot;')
        iframe_html = f'<iframe srcdoc="{escaped_html}" style="width:100%; height:650px; border:none; border-radius:4px; overflow:hidden;"></iframe>'
        
        # 마크다운 형식의 응답 생성
        answer = f"{iframe_html}\n\n"
        if custom_message:
            answer += f"💬 **{custom_message}**\n\n"
        
        answer += f"""
**게임 정보:**
- 난이도: {difficulty}
- 테마: {theme}

**조작법:**
{self._get_game_controls()}

즐거운 게임 되세요! 🎮
"""
        
        return AgentResponse(
            type=AgentResponseType.SUCCESS,
            content={
                "answer": answer,
                "category": "game",
                "difficulty": difficulty,
                "theme": theme,
                "reasoning": f"{self.name} 게임이 성공적으로 생성되었습니다."
            },
            metadata={
                "agent_name": self.name,
                "game_type": self.name.lower().replace(" agent", "")
            }
        )
    
    @abstractmethod
    def _get_game_controls(self) -> str:
        """게임 조작법 반환 (하위 클래스에서 구현)"""
        pass


class SearchAgent(APIBasedAgent):
    """검색 에이전트 기본 클래스
    
    검색 기능을 제공하는 에이전트의 기본 클래스입니다.
    """
    
    async def _format_search_results(self, results: List[Dict[str, Any]]) -> str:
        """검색 결과 포맷팅"""
        if not results:
            return "검색 결과가 없습니다."
        
        formatted = "## 🔍 검색 결과\n\n"
        
        for i, result in enumerate(results, 1):
            title = result.get("title", "제목 없음")
            snippet = result.get("snippet", result.get("description", ""))
            url = result.get("url", "")
            
            formatted += f"### {i}. {title}\n"
            if snippet:
                formatted += f"{snippet}\n"
            if url:
                formatted += f"[더 보기]({url})\n"
            formatted += "\n"
        
        return formatted