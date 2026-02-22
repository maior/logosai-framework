"""
통합 LLM 클라이언트 모듈

다양한 LLM 프로바이더(OpenAI, Google, Anthropic 등)를 통일된 인터페이스로 호출할 수 있게 해주는 모듈입니다.
에이전트들이 쉽게 LLM을 사용할 수 있도록 간편한 API를 제공합니다.

사용 예시:
    # 기본 사용법
    llm_client = LLMClient(provider="openai", model="gpt-4", temperature=0.7)
    response = await llm_client.invoke("안녕하세요")
    
    # Google Gemini 사용
    llm_client = LLMClient(provider="google", model="gemini-pro", temperature=0.5)
    response = await llm_client.invoke("Hello, world!")
    
    # 메시지 기반 호출
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the weather like?"}
    ]
    response = await llm_client.invoke_messages(messages)
"""

import os
import asyncio
from typing import Dict, Any, List, Optional, Union, Tuple
from enum import Enum
from dataclasses import dataclass
import json

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

# 프로바이더별 라이브러리 임포트 (선택적)
_PROVIDERS_AVAILABLE = {}

# OpenAI
try:
    from langchain_openai import ChatOpenAI
    from openai import AsyncOpenAI
    _PROVIDERS_AVAILABLE["openai"] = True
except ImportError:
    _PROVIDERS_AVAILABLE["openai"] = False

# Google
try:
    from google import genai
    from google.genai import types
    _PROVIDERS_AVAILABLE["google"] = True
except ImportError:
    _PROVIDERS_AVAILABLE["google"] = False

# Anthropic
try:
    from anthropic import AsyncAnthropic
    from langchain_anthropic import ChatAnthropic
    _PROVIDERS_AVAILABLE["anthropic"] = True
except ImportError:
    _PROVIDERS_AVAILABLE["anthropic"] = False

# Ollama (로컬 LLM)
try:
    from langchain_community.llms import Ollama
    from langchain_community.chat_models import ChatOllama
    _PROVIDERS_AVAILABLE["ollama"] = True
except ImportError:
    _PROVIDERS_AVAILABLE["ollama"] = False

from .llm_settings import get_provider_settings, get_default_llm_settings, get_api_key


class GoogleLangChainWrapper:
    """Google API를 LangChain 인터페이스로 래핑하는 클래스"""
    
    def __init__(self, llm_client):
        self.llm_client = llm_client
    
    async def ainvoke(self, messages):
        """LangChain 호환 비동기 호출"""
        # LangChain 메시지를 LLMMessage로 변환
        llm_messages = []
        for msg in messages:
            if hasattr(msg, 'type'):
                role = "system" if msg.type == "system" else "user" if msg.type == "human" else "assistant"
                llm_messages.append({"role": role, "content": msg.content})
            else:
                llm_messages.append({"role": "user", "content": str(msg)})
        
        response = await self.llm_client.invoke_messages(llm_messages)
        
        # LangChain 스타일 응답 객체 모방
        class LangChainResponse:
            def __init__(self, content):
                self.content = content
        
        return LangChainResponse(response.content)


class LLMProvider(Enum):
    """지원되는 LLM 프로바이더"""
    OPENAI = "openai"
    GOOGLE = "google"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"


@dataclass
class LLMMessage:
    """LLM 메시지 표준 구조"""
    role: str  # system, user, assistant
    content: str
    name: Optional[str] = None
    function_call: Optional[Dict[str, Any]] = None


@dataclass
class LLMResponse:
    """LLM 응답 표준 구조"""
    content: str
    provider: str
    model: str
    usage: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    raw_response: Optional[Any] = None
    
    def __str__(self) -> str:
        """문자열 표현 - content를 반환"""
        return self.content


class LLMClient:
    """통합 LLM 클라이언트"""
    
    def __init__(
        self,
        provider: str = "google",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        timeout: Optional[int] = None,
        **kwargs
    ):
        """
        LLM 클라이언트 초기화
        
        Args:
            provider: LLM 프로바이더 이름 (openai, google, anthropic, ollama)
            model: 모델 이름 (None이면 프로바이더 기본값 사용)
            api_key: API 키 (None이면 환경변수에서 가져옴)
            temperature: 창의성 조절 (0.0-2.0)
            max_tokens: 최대 토큰 수
            top_p: top-p 샘플링
            timeout: 타임아웃(초)
            **kwargs: 기타 프로바이더별 설정
        """
        self.provider = provider.lower()
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.timeout = timeout
        self.extra_params = kwargs
        
        # 프로바이더 유효성 검사
        if self.provider not in [p.value for p in LLMProvider]:
            raise ValueError(f"지원되지 않는 프로바이더: {provider}")
        
        # 프로바이더 라이브러리 사용 가능성 검사
        if not _PROVIDERS_AVAILABLE.get(self.provider, False):
            raise ImportError(f"{provider} 프로바이더에 필요한 라이브러리가 설치되지 않았습니다.")
        
        # 기본 설정 사용 (설정 로딩 비활성화)
        # self._load_settings()  # 임시로 비활성화
        
        # 기본값 설정
        if not self.model:
            if self.provider == "openai":
                self.model = "gpt-4.1-mini"
            elif self.provider == "google":
                self.model = "gemini-2.5-flash-lite"
            else:
                self.model = "gemini-2.5-flash-lite"
        
        if not self.api_key:
            import os
            if self.provider == "openai":
                self.api_key = os.getenv("OPENAI_API_KEY")
            elif self.provider == "google":
                self.api_key = os.getenv("GOOGLE_API_KEY")
        
        if self.max_tokens is None:
            self.max_tokens = 2000
        
        self._client = None
        self._langchain_client = None
        self._initialized = False
    
    def _load_settings(self):
        """프로바이더 설정 로드"""
        try:
            # 프로바이더별 설정 가져오기
            provider_settings = get_provider_settings(self.provider)
            default_settings = get_default_llm_settings()
            
            # 모델 설정
            if not self.model:
                self.model = provider_settings.get("default_model") or default_settings.get("default_model", "gemini-2.5-flash-lite")
            
            # API 키 설정
            if not self.api_key:
                self.api_key = get_api_key(self.provider)
            
            # 기타 설정값들 기본값 적용
            if self.max_tokens is None:
                self.max_tokens = default_settings.get("max_tokens", 2000)
            
            if self.top_p is None:
                self.top_p = default_settings.get("top_p", 0.95)
            
            if self.timeout is None:
                self.timeout = default_settings.get("timeout", 60)
                
        except Exception as e:
            logger.warning(f"설정 로드 중 오류: {e}, 기본값 사용")
    
    async def initialize(self) -> bool:
        """클라이언트 초기화"""
        if self._initialized:
            return True
        
        try:
            if self.provider == "openai":
                # AsyncOpenAI 클라이언트 생성 (안전한 방식)
                try:
                    self._client = AsyncOpenAI(api_key=self.api_key)
                except Exception as e:
                    logger.warning(f"AsyncOpenAI 클라이언트 생성 중 오류 (무시): {e}")
                    self._client = None
                
                # LangChain ChatOpenAI 클라이언트 초기화 (안전한 방식)
                try:
                    self._langchain_client = ChatOpenAI(
                        model=self.model,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        api_key=self.api_key
                    )
                except Exception as e:
                    logger.error(f"ChatOpenAI 클라이언트 생성 실패: {e}")
                    # 최소한의 파라미터로 재시도
                    try:
                        self._langchain_client = ChatOpenAI(
                            model=self.model,
                            api_key=self.api_key
                        )
                        logger.info("최소 파라미터로 ChatOpenAI 클라이언트 생성 성공")
                    except Exception as e2:
                        logger.error(f"최소 파라미터 ChatOpenAI 클라이언트 생성도 실패: {e2}")
                        self._langchain_client = None
            
            elif self.provider == "google":
                # API 키가 설정되어 있는지 확인
                if not self.api_key:
                    raise ValueError("Google API 키가 설정되지 않았습니다. GOOGLE_API_KEY 환경변수를 설정하세요.")
                
                self._client = genai.Client(api_key=self.api_key)
                logger.info(f"Google genai 클라이언트 생성 완료 - API 키: {'***' + self.api_key[-4:] if len(self.api_key) > 4 else 'None'}")
                # Google은 별도의 LangChain 클라이언트 초기화 하지 않음 (직접 API 사용)
            
            elif self.provider == "anthropic":
                self._client = AsyncAnthropic(api_key=self.api_key)
                self._langchain_client = ChatAnthropic(
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    api_key=self.api_key
                )
            
            elif self.provider == "ollama":
                self._langchain_client = ChatOllama(
                    model=self.model,
                    temperature=self.temperature,
                    **self.extra_params
                )
            
            self._initialized = True
            logger.info(f"LLM 클라이언트 초기화 완료: {self.provider}/{self.model}")
            return True
            
        except Exception as e:
            logger.error(f"LLM 클라이언트 초기화 실패: {e}")
            return False
    
    async def invoke(self, message: str, **kwargs) -> LLMResponse:
        """단일 메시지로 LLM 호출"""
        messages = [LLMMessage(role="user", content=message)]
        return await self.invoke_messages(messages, **kwargs)
    
    async def ainvoke(self, messages, **kwargs) -> LLMResponse:
        """LangChain 호환 비동기 호출 (메인 클래스에 추가)"""
        # LangChain 메시지를 LLMMessage로 변환
        if hasattr(messages, '__iter__') and not isinstance(messages, str):
            # 메시지 리스트인 경우
            llm_messages = []
            for msg in messages:
                if hasattr(msg, 'type'):
                    # LangChain 메시지 객체
                    role = "system" if msg.type == "system" else "user" if msg.type == "human" else "assistant"
                    llm_messages.append(LLMMessage(role=role, content=msg.content))
                elif isinstance(msg, dict):
                    llm_messages.append(LLMMessage(**msg))
                else:
                    llm_messages.append(msg)
            return await self.invoke_messages(llm_messages, **kwargs)
        else:
            # 단일 메시지인 경우
            return await self.invoke(str(messages), **kwargs)
    
    async def invoke_messages(self, messages: List[Union[LLMMessage, Dict[str, str]]], **kwargs) -> LLMResponse:
        """메시지 리스트로 LLM 호출"""
        if not self._initialized:
            await self.initialize()
        
        # 메시지 형식 통일
        formatted_messages = []
        for msg in messages:
            if isinstance(msg, dict):
                formatted_messages.append(LLMMessage(**msg))
            else:
                formatted_messages.append(msg)
        
        try:
            if self.provider == "openai":
                return await self._call_openai(formatted_messages, **kwargs)
            elif self.provider == "google":
                return await self._call_google(formatted_messages, **kwargs)
            elif self.provider == "anthropic":
                return await self._call_anthropic(formatted_messages, **kwargs)
            elif self.provider == "ollama":
                return await self._call_ollama(formatted_messages, **kwargs)
            else:
                raise ValueError(f"지원되지 않는 프로바이더: {self.provider}")
                
        except Exception as e:
            logger.error(f"LLM 호출 실패: {e}")
            raise
    
    async def _call_openai(self, messages: List[LLMMessage], **kwargs) -> LLMResponse:
        """OpenAI API 호출 (직접 API 사용)"""
        
        # LangChain 클라이언트가 있으면 시도
        if self._langchain_client:
            try:
                from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
                
                lc_messages = []
                for msg in messages:
                    if msg.role == "system":
                        lc_messages.append(SystemMessage(content=msg.content))
                    elif msg.role == "user":
                        lc_messages.append(HumanMessage(content=msg.content))
                    elif msg.role == "assistant":
                        lc_messages.append(AIMessage(content=msg.content))
                
                response = await self._langchain_client.ainvoke(lc_messages)
                
                return LLMResponse(
                    content=response.content,
                    provider=self.provider,
                    model=self.model,
                    raw_response=response
                )
            except Exception as e:
                logger.warning(f"LangChain 호출 실패, 직접 API 호출로 대체: {e}")
        
        # 직접 OpenAI API 호출
        try:
            from openai import AsyncOpenAI
            import os
            
            # 프록시 환경변수 임시 제거
            proxy_env_vars = ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']
            old_proxy_values = {}
            
            for var in proxy_env_vars:
                if var in os.environ:
                    old_proxy_values[var] = os.environ[var]
                    del os.environ[var]
            
            try:
                # 새로운 클라이언트 생성 (프록시 설정 없이)
                direct_client = AsyncOpenAI(api_key=self.api_key)
                
                # 메시지 형식 변환
                api_messages = []
                for msg in messages:
                    api_messages.append({
                        "role": msg.role,
                        "content": msg.content
                    })
                
                # API 호출
                response = await direct_client.chat.completions.create(
                    model=self.model,
                    messages=api_messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens
                )
                
                return LLMResponse(
                    content=response.choices[0].message.content,
                    provider=self.provider,
                    model=self.model,
                    usage=response.usage.dict() if response.usage else None,
                    raw_response=response
                )
                
            finally:
                # 프록시 환경변수 복원
                for var, value in old_proxy_values.items():
                    os.environ[var] = value
            
        except Exception as e:
            logger.error(f"직접 OpenAI API 호출도 실패: {e}")
            raise
    
    async def _call_google(self, messages: List[LLMMessage], **kwargs) -> LLMResponse:
        """Google API 호출"""
        
        try:
            # 시스템 메시지와 사용자 메시지 분리
            system_instruction = None
            contents = []
            
            for msg in messages:
                if msg.role == "system":
                    system_instruction = msg.content
                elif msg.role == "user":
                    contents.append(msg.content)
                elif msg.role == "assistant":
                    # assistant 메시지는 대화 히스토리로 처리 (필요시 구현)
                    contents.append(f"Assistant: {msg.content}")
            
            # 마지막 사용자 메시지만 사용 (Google API는 단일 컨텐츠 전송)
            if contents:
                final_content = contents[-1]
            else:
                final_content = "안녕하세요"
            
            logger.debug(f"Google API 호출 - 모델: {self.model}, 내용: {final_content[:100]}...")
            
            # Google Gemini API 호출
            config = types.GenerateContentConfig(
                temperature=self.temperature,
                max_output_tokens=kwargs.get('max_tokens', self.max_tokens) or 8192,  # 기본값 8192
            )
            
            if system_instruction:
                config.system_instruction = system_instruction
                logger.debug(f"시스템 지시사항: {system_instruction[:100]}...")
            
            logger.debug(f"max_output_tokens 설정: {config.max_output_tokens}")
            
            # 동기 호출 (Google genai 라이브러리가 현재 비동기를 지원하지 않음)
            import asyncio
            loop = asyncio.get_event_loop()
            
            def sync_call():
                try:
                    return self._client.models.generate_content(
                        model=self.model,
                        config=config,
                        contents=final_content
                    )
                except Exception as e:
                    logger.error(f"Google API 직접 호출 오류: {e}")
                    logger.error(f"오류 타입: {type(e).__name__}")
                    logger.error(f"API 키 확인: {'***' + self.api_key[-4:] if self.api_key and len(self.api_key) > 4 else 'None'}")
                    logger.error(f"모델명: {self.model}")
                    raise
            
            response = await loop.run_in_executor(None, sync_call)
            
            # 응답 디버깅
            logger.debug(f"Google API 응답 타입: {type(response)}")
            
            # 응답에서 텍스트 추출
            response_text = ""
            
            # 먼저 text 속성 확인
            if hasattr(response, 'text') and response.text:
                response_text = response.text
                logger.debug(f"response.text 길이: {len(response_text)} chars")
                logger.debug(f"response.text 미리보기: {response_text[:200] if response_text else 'EMPTY'}")
            
            # text가 없으면 candidates 확인
            if not response_text and hasattr(response, 'candidates'):
                # candidates가 있는 경우
                logger.debug(f"response.text가 비어있음, candidates 확인 중...")
                logger.debug(f"candidates 수: {len(response.candidates) if response.candidates else 0}")
                if response.candidates and len(response.candidates) > 0:
                    candidate = response.candidates[0]
                    if hasattr(candidate, 'content'):
                        if hasattr(candidate.content, 'parts'):
                            parts = candidate.content.parts
                            if parts and len(parts) > 0:
                                response_text = parts[0].text if hasattr(parts[0], 'text') else str(parts[0])
                        else:
                            response_text = str(candidate.content)
                    elif hasattr(candidate, 'text'):
                        response_text = candidate.text
                    logger.debug(f"candidates에서 추출: {len(response_text)} chars")
            
            if not response_text:
                logger.warning(f"응답에서 텍스트를 추출할 수 없습니다. 전체 응답: {response}")
            else:
                logger.debug(f"Google API 응답 성공: {len(response_text)} chars")
            
            return LLMResponse(
                content=response_text or "",
                provider=self.provider,
                model=self.model,
                raw_response=response
            )
            
        except Exception as e:
            # 상세한 오류 정보 로깅
            logger.error(f"Google API 호출 중 오류 발생:")
            logger.error(f"  오류 타입: {type(e).__name__}")
            logger.error(f"  오류 메시지: {str(e)}")
            logger.error(f"  사용 모델: {self.model}")
            logger.error(f"  API 키 상태: {'설정됨' if self.api_key else '설정되지 않음'}")
            
            # 가능한 해결책 제안
            if "authentication" in str(e).lower() or "api_key" in str(e).lower():
                logger.error("  💡 해결책: GOOGLE_API_KEY 환경변수를 확인하세요.")
            elif "quota" in str(e).lower() or "limit" in str(e).lower():
                logger.error("  💡 해결책: API 사용량 제한에 걸렸을 수 있습니다. 잠시 후 다시 시도하세요.")
            elif "model" in str(e).lower():
                logger.error("  💡 해결책: 모델명이 올바른지 확인하세요.")
            else:
                logger.error("  💡 해결책: 네트워크 연결 상태나 Google AI Studio에서 API 키 상태를 확인하세요.")
            
            raise
    
    async def _call_anthropic(self, messages: List[LLMMessage], **kwargs) -> LLMResponse:
        """Anthropic API 호출"""
        from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
        
        lc_messages = []
        for msg in messages:
            if msg.role == "system":
                lc_messages.append(SystemMessage(content=msg.content))
            elif msg.role == "user":
                lc_messages.append(HumanMessage(content=msg.content))
            elif msg.role == "assistant":
                lc_messages.append(AIMessage(content=msg.content))
        
        response = await self._langchain_client.ainvoke(lc_messages)
        
        return LLMResponse(
            content=response.content,
            provider=self.provider,
            model=self.model,
            raw_response=response
        )
    
    async def _call_ollama(self, messages: List[LLMMessage], **kwargs) -> LLMResponse:
        """Ollama API 호출"""
        from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
        
        lc_messages = []
        for msg in messages:
            if msg.role == "system":
                lc_messages.append(SystemMessage(content=msg.content))
            elif msg.role == "user":
                lc_messages.append(HumanMessage(content=msg.content))
            elif msg.role == "assistant":
                lc_messages.append(AIMessage(content=msg.content))
        
        response = await self._langchain_client.ainvoke(lc_messages)
        
        return LLMResponse(
            content=response.content,
            provider=self.provider,
            model=self.model,
            raw_response=response
        )
    
    def get_langchain_client(self):
        """LangChain 클라이언트 반환 (기존 코드와의 호환성)"""
        if not self._initialized:
            raise ValueError("클라이언트가 초기화되지 않았습니다. initialize()를 먼저 호출하세요.")
        
        if self.provider == "google":
            # Google은 직접 API를 사용하므로 LangChain 호환 래퍼 제공
            return GoogleLangChainWrapper(self)
        
        return self._langchain_client
    
    @classmethod
    def create_openai(cls, model: str = "gpt-4o-mini", temperature: float = 0.7, **kwargs) -> 'LLMClient':
        """OpenAI 클라이언트 생성 단축 메서드"""
        return cls(provider="openai", model=model, temperature=temperature, **kwargs)
    
    @classmethod
    def create_google(cls, model: str = "gemini-2.5-flash-lite", temperature: float = 0.7, **kwargs) -> 'LLMClient':
        """Google 클라이언트 생성 단축 메서드"""
        return cls(provider="google", model=model, temperature=temperature, **kwargs)
    
    @classmethod
    def create_anthropic(cls, model: str = "claude-3.5-sonnet", temperature: float = 0.7, **kwargs) -> 'LLMClient':
        """Anthropic 클라이언트 생성 단축 메서드"""
        return cls(provider="anthropic", model=model, temperature=temperature, **kwargs)
    
    @classmethod
    def create_ollama(cls, model: str = "llama3.1", temperature: float = 0.7, **kwargs) -> 'LLMClient':
        """Ollama 클라이언트 생성 단축 메서드"""
        return cls(provider="ollama", model=model, temperature=temperature, **kwargs)


# 편의 함수들
async def create_llm_client(
    provider: str = "google",
    model: Optional[str] = None,
    temperature: float = 0.7,
    **kwargs
) -> LLMClient:
    """LLM 클라이언트 생성 및 초기화 (기본값: Google)"""
    client = LLMClient(provider=provider, model=model, temperature=temperature, **kwargs)
    await client.initialize()
    return client


def get_available_providers() -> List[str]:
    """사용 가능한 프로바이더 목록 반환"""
    return [provider for provider, available in _PROVIDERS_AVAILABLE.items() if available]


def is_provider_available(provider: str) -> bool:
    """특정 프로바이더 사용 가능 여부 확인"""
    return _PROVIDERS_AVAILABLE.get(provider.lower(), False)


# 설정 관리 함수들
def register_google_provider(api_key_env: str = "GOOGLE_API_KEY"):
    """Google 프로바이더 등록"""
    from .llm_settings import register_provider
    return register_provider(
        provider_name="google",
        api_key_env=api_key_env,
        default_model="gemini-2.5-flash-lite",
        fallback_model="gemini-2.5-flash-lite"
    )


def register_anthropic_provider(api_key_env: str = "ANTHROPIC_API_KEY"):
    """Anthropic 프로바이더 등록"""
    from .llm_settings import register_provider
    return register_provider(
        provider_name="anthropic",
        api_key_env=api_key_env,
        default_model="claude-3.5-sonnet",
        fallback_model="claude-3.5-sonnet"
    )


def register_ollama_provider():
    """Ollama 프로바이더 등록"""
    from .llm_settings import register_provider
    return register_provider(
        provider_name="ollama",
        api_key_env="",  # Ollama는 API 키가 필요 없음
        default_model="llama2",
        fallback_model="mistral"
    )


# ─── Convenience: one-shot LLM call ─────────────────


async def quick_llm(
    prompt: str,
    provider: str = "google",
    model: str = "gemini-2.5-flash-lite",
    temperature: float = 0.7,
    system_prompt: Optional[str] = None,
    max_tokens: int = 4000,
) -> str:
    """
    One-shot LLM call. Creates client, initializes, calls, returns content string.

    No setup required. Perfect for services that just need a quick LLM call
    without managing client lifecycle.

    Args:
        prompt: User prompt
        provider: LLM provider (google, openai, anthropic, ollama)
        model: Model name
        temperature: Creativity (0.0-2.0)
        system_prompt: Optional system instruction
        max_tokens: Maximum response tokens

    Returns:
        Response content as string

    Usage:
        from logosai.utils.llm_client import quick_llm

        answer = await quick_llm("What is 2+2?")
        answer = await quick_llm("Translate: hello", provider="openai", model="gpt-4o-mini")
    """
    client = LLMClient(
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    await client.initialize()

    if system_prompt:
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=prompt),
        ]
        response = await client.invoke_messages(messages)
    else:
        response = await client.invoke(prompt)

    return response.content


# 하위 호환성을 위한 별칭
LLM = LLMClient  # 기존 코드에서 LLM으로 사용하던 경우