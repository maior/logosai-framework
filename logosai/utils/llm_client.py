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

def _get_default_model():
    try:
        from ..config.llm_defaults import get_default_model
        return get_default_model()
    except Exception:
        return "gemini-2.5-flash-lite"

def _get_default_provider():
    try:
        from ..config.llm_defaults import get_default_provider
        return get_default_provider()
    except Exception:
        return "google"


def _get_base_url():
    """온-프렘 OpenAI-호환 endpoint base_url (config/env). 없으면 None."""
    try:
        from ..config.llm_defaults import get_base_url
        return get_base_url()
    except Exception:
        return None


# 프로바이더별 라이브러리 임포트 (선택적)
_PROVIDERS_AVAILABLE = {}

# OpenAI — native SDK 만 필요 (langchain 미사용, 2026-07-07 전면 native 화)
try:
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

# Anthropic — native SDK 만 필요
try:
    from anthropic import AsyncAnthropic
    _PROVIDERS_AVAILABLE["anthropic"] = True
except ImportError:
    _PROVIDERS_AVAILABLE["anthropic"] = False

# Ollama (로컬 LLM) — OpenAI-호환 /v1 endpoint 를 openai SDK 로 호출
# (LangChain 커뮤니티 패키지 불필요 — 온-프렘 base_url 설계와 동일 메커니즘)
_PROVIDERS_AVAILABLE["ollama"] = _PROVIDERS_AVAILABLE["openai"]

# ── OpenAI-호환 프로바이더 레지스트리 (2026-07-07 진화) ─────────────────
# 업계 표준이 된 OpenAI-호환 API 를 지렛대로 프로바이더 폭을 흡수한다.
# 항목: base_url + api_key_env (키 불요 로컬 서버는 api_key_env=None).
# config(~/.logosai/config.json llm.providers.<name>)로 코드 수정 없이 확장.
_COMPAT_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "ollama":     {"base_url": "http://localhost:11434/v1", "api_key_env": None},
    "groq":       {"base_url": "https://api.groq.com/openai/v1", "api_key_env": "GROQ_API_KEY"},
    "deepseek":   {"base_url": "https://api.deepseek.com/v1", "api_key_env": "DEEPSEEK_API_KEY"},
    "together":   {"base_url": "https://api.together.xyz/v1", "api_key_env": "TOGETHER_API_KEY"},
    "fireworks":  {"base_url": "https://api.fireworks.ai/inference/v1", "api_key_env": "FIREWORKS_API_KEY"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY"},
    "mistral":    {"base_url": "https://api.mistral.ai/v1", "api_key_env": "MISTRAL_API_KEY"},
    "xai":        {"base_url": "https://api.x.ai/v1", "api_key_env": "XAI_API_KEY"},
    "perplexity": {"base_url": "https://api.perplexity.ai", "api_key_env": "PERPLEXITY_API_KEY"},
}


def _get_extra_providers() -> Dict[str, Dict[str, Any]]:
    """config(llm.providers) 로 정의된 사용자 확장 프로바이더 (없으면 {})."""
    try:
        from ..config.llm_defaults import get_extra_providers
        return get_extra_providers() or {}
    except Exception:
        return {}


def _resolve_compat_provider(name: str) -> Optional[Dict[str, Any]]:
    """내장 ∪ config 레지스트리에서 OpenAI-호환 프로바이더 정의 조회."""
    merged = dict(_COMPAT_PROVIDERS)
    merged.update(_get_extra_providers())
    return merged.get(name)

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
class ToolCall:
    """LLM이 호출을 요청한 도구 정보."""
    name: str
    args: Dict[str, Any]
    id: str = ""


@dataclass
class LLMResponse:
    """LLM 응답 표준 구조"""
    content: str
    provider: str
    model: str
    usage: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    raw_response: Optional[Any] = None
    tool_calls: Optional[List['ToolCall']] = None  # LLM이 호출을 요청한 도구들

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    def __str__(self) -> str:
        """문자열 표현 - content를 반환"""
        return self.content


class LLMClient:
    """통합 LLM 클라이언트"""
    
    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        timeout: Optional[int] = None,
        base_url: Optional[str] = None,
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
        # 프로바이더 config-driven (2026-07-07): 미지정 시 ~/.logosai/config.json
        # (llm.provider) / env(LOGOSAI_LLM_PROVIDER)에서 결정. 명시 인자는 우선.
        # 온-프렘 등 프로바이더 전환을 설정만으로 가능하게 한다.
        if provider is None:
            provider = _get_default_provider()
        self.provider = provider.lower()
        self.model = model
        # 온-프렘 OpenAI-호환 endpoint (2026-07-07): 미지정 시 config/env 에서.
        # vLLM/LMStudio/Ollama(/v1)/TGI/LocalAI 를 openai 프로바이더로 사용.
        self.base_url = base_url if base_url is not None else _get_base_url()
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.timeout = timeout
        self.extra_params = kwargs
        
        # 프로바이더 해석 (2026-07-07 진화): 1군 native(openai/google/anthropic)
        # → 2군 OpenAI-호환 레지스트리(내장 ∪ config llm.providers)
        # → base_url 단독 generic. enum 제약 제거로 "다양한 LLM 소화".
        self._compat = False
        self._compat_api_key_env: Optional[str] = None
        if self.provider in ("openai", "google", "anthropic"):
            pass  # 1군 native
        else:
            compat_def = _resolve_compat_provider(self.provider)
            if compat_def is not None:
                self._compat = True
                self._compat_api_key_env = compat_def.get("api_key_env")
                # 명시 base_url > extra_params.base_url > 레지스트리 기본
                # (config llm.base_url 은 기본 프로바이더 온-프렘용 — 여기 미적용)
                self.base_url = (
                    base_url
                    or self.extra_params.get("base_url")
                    or compat_def.get("base_url")
                )
            elif self.base_url:
                self._compat = True  # 이름 없는 generic 호환 서버
            else:
                _known = sorted(
                    {"openai", "google", "anthropic"}
                    | set(_COMPAT_PROVIDERS)
                    | set(_get_extra_providers())
                )
                raise ValueError(
                    f"지원되지 않는 프로바이더: {provider}. "
                    f"가용: {', '.join(_known)} (또는 base_url 로 OpenAI-호환 서버 직접 지정, "
                    f"config llm.providers 로 확장 가능)"
                )

        # 프로바이더 라이브러리 사용 가능성 검사 (호환 계열은 openai SDK 필요)
        _lib_key = "openai" if self._compat else self.provider
        if not _PROVIDERS_AVAILABLE.get(_lib_key, False):
            raise ImportError(f"{provider} 프로바이더에 필요한 라이브러리가 설치되지 않았습니다.")
        
        # 기본 설정 사용 (설정 로딩 비활성화)
        # self._load_settings()  # 임시로 비활성화
        
        # 기본값 설정 — 모델은 프로바이더 무관 config-driven(2026-07-07).
        # 과거엔 openai 만 "gpt-4.1-mini" 로 하드코딩돼 config/env 모델(온-프렘
        # Qwen 등)이 무시됐다. 이제 미지정 시 항상 _get_default_model()(config/env).
        if not self.model:
            self.model = _get_default_model()
        
        if not self.api_key:
            import os
            if self.provider == "openai":
                self.api_key = os.getenv("OPENAI_API_KEY")
            elif self.provider == "google":
                self.api_key = os.getenv("GOOGLE_API_KEY")
            elif self.provider == "anthropic":
                self.api_key = os.getenv("ANTHROPIC_API_KEY")
            elif self._compat and self._compat_api_key_env:
                self.api_key = os.getenv(self._compat_api_key_env)

        # 호환 계열: 키 불요 서버(ollama 등, api_key_env=None)는 placeholder —
        # openai SDK 가 None 키로 실패하는 것 방지 (로컬 서버는 아무 키나 허용)
        if self._compat and not self.api_key and not self._compat_api_key_env:
            self.api_key = "sk-compat-local"

        # 온-프렘: base_url 설정 + openai + 키 없음 → placeholder(로컬 서버는
        # 대개 아무 키나 허용). AsyncOpenAI 가 None 키로 실패하는 것 방지.
        if self.provider == "openai" and self.base_url and not self.api_key:
            self.api_key = "sk-local-onprem"
        
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
                self.model = provider_settings.get("default_model") or default_settings.get("default_model", _get_default_model())
            
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
                # native AsyncOpenAI 단일 경로 (base_url 설정 시 온-프렘 endpoint).
                # LangChain 챗 래퍼는 2026-07-07 제거 — 직접 구현이 설계 의도.
                _oai_kwargs = {"api_key": self.api_key}
                if self.base_url:
                    _oai_kwargs["base_url"] = self.base_url
                self._client = AsyncOpenAI(**_oai_kwargs)
                self._langchain_client = None
                if self.base_url:
                    logger.info(f"LLM 클라이언트 초기화(온-프렘): {self.provider}/{self.model} @ {self.base_url}")

            elif self.provider == "google":
                # API 키가 설정되어 있는지 확인
                if not self.api_key:
                    raise ValueError("Google API 키가 설정되지 않았습니다. GOOGLE_API_KEY 환경변수를 설정하세요.")
                
                self._client = genai.Client(api_key=self.api_key)
                logger.info(f"Google genai 클라이언트 생성 완료 - API 키: {'***' + self.api_key[-4:] if len(self.api_key) > 4 else 'None'}")
                # Google은 별도의 LangChain 클라이언트 초기화 하지 않음 (직접 API 사용)
            
            elif self.provider == "anthropic":
                # native AsyncAnthropic 단일 경로 (LangChain 챗 래퍼 제거)
                self._client = AsyncAnthropic(api_key=self.api_key)
                self._langchain_client = None

            elif self._compat:
                # OpenAI-호환 계열 (ollama/groq/deepseek/... + config 확장 + generic)
                # — 전부 openai SDK 하나로 소화 (레지스트리가 base_url/키 규약 제공)
                self._client = AsyncOpenAI(
                    api_key=self.api_key or "sk-compat-local",
                    base_url=self.base_url,
                )
                self._langchain_client = None
                logger.info(f"LLM 클라이언트 초기화(OpenAI-호환): {self.provider}/{self.model} @ {self.base_url}")
            
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

    async def invoke_stream(self, message: str, system_prompt: str = None):
        """Stream LLM response token by token.

        Yields chunks of text as they arrive from the LLM.

        Args:
            message: User prompt
            system_prompt: Optional system instruction

        Yields:
            str: Text chunk

        Example:
            async for chunk in llm.invoke_stream("Tell me about AI"):
                print(chunk, end="", flush=True)
        """
        if not self._initialized:
            await self.initialize()

        if self.provider == "google":
            async for chunk in self._stream_google(message, system_prompt):
                yield chunk
        elif self.provider == "openai" or self._compat:
            # OpenAI-호환 진짜 토큰 스트리밍 (2026-07-07 — 기존엔 google 전용)
            async for chunk in self._stream_openai_compat(message, system_prompt):
                yield chunk
        elif self.provider == "anthropic":
            # Anthropic native 토큰 스트리밍 (2026-07-19 — 기존엔 전문 1회 폴백)
            async for chunk in self._stream_anthropic(message, system_prompt):
                yield chunk
        else:
            # Fallback: non-streaming (yield full response)
            msgs = []
            if system_prompt:
                msgs.append(LLMMessage(role="system", content=system_prompt))
            msgs.append(LLMMessage(role="user", content=message))
            response = await self.invoke_messages(msgs)
            yield response.content

    async def _stream_openai_compat(self, message: str, system_prompt: str = None):
        """OpenAI-호환 chat.completions 토큰 스트리밍."""
        api_messages = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        api_messages.append({"role": "user", "content": message})
        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=api_messages,
            temperature=self.temperature,
            stream=True,
        )
        async for chunk in stream:
            try:
                delta = chunk.choices[0].delta.content
            except (AttributeError, IndexError):
                delta = None
            if delta:
                yield delta

    async def _stream_anthropic(self, message: str, system_prompt: str = None):
        """Anthropic Messages API 토큰 스트리밍.

        SDK 계약(anthropic>=0.96): `messages.stream(...)` 이 async context
        manager 를 돌려주고 `.text_stream` 이 텍스트 델타를 준다.
        _call_anthropic 과 동일하게 system 은 messages 배열이 아니라 top-level
        파라미터로 보낸다.
        """
        _kwargs = {
            "model": self.model,
            "messages": [{"role": "user", "content": message}],
            "max_tokens": self.max_tokens or 1024,
            "temperature": self.temperature,
        }
        if system_prompt:
            _kwargs["system"] = system_prompt

        async with self._client.messages.stream(**_kwargs) as stream:
            async for text in stream.text_stream:
                if text:
                    yield text

    async def _stream_google(self, message: str, system_prompt: str = None):
        """Google Gemini streaming."""
        import asyncio
        from google.genai import types

        config = types.GenerateContentConfig(
            temperature=self.temperature,
            max_output_tokens=self.max_tokens or 4096,
        )
        if system_prompt:
            config.system_instruction = system_prompt

        def sync_stream():
            chunks = []
            for chunk in self._client.models.generate_content_stream(
                model=self.model,
                config=config,
                contents=message,
            ):
                text = chunk.text if hasattr(chunk, 'text') else ""
                if text:
                    chunks.append(text)
            return chunks

        loop = asyncio.get_event_loop()
        chunks = await loop.run_in_executor(None, sync_stream)
        for chunk in chunks:
            yield chunk
    
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
    
    # Observability: metrics callback (set by ACP server)
    _metrics_callback = None

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

        import asyncio as _aio
        import time as _time

        # Guardrails: rate limit + call counter
        try:
            from .guardrails import get_rate_limiter, get_request_counter
            await get_rate_limiter().acquire()
            get_request_counter().increment()
        except ImportError:
            pass  # guardrails not available
        except Exception as guard_err:
            # LLMCallLimitExceeded → propagate
            if "limit exceeded" in str(guard_err).lower():
                raise
            logger.debug(f"Guardrail check: {guard_err}")

        # Harness per-execution budget: 호출 상한 사전 점검 (예산 미활성 시 no-op).
        # HarnessBudgetExceeded 는 상위 하네스 래퍼로 전파되어 graceful error 로.
        try:
            from .guardrails import precheck_llm_call
        except ImportError:
            precheck_llm_call = None
        if precheck_llm_call is not None:
            precheck_llm_call()

        max_retries = kwargs.pop("_max_retries", 2)
        last_error = None
        _start_time = _time.time()

        # Extract prompt preview for metrics
        _prompt_preview = ""
        for msg in formatted_messages:
            if msg.role == "user":
                _prompt_preview = msg.content[:200] if msg.content else ""
                break

        for attempt in range(max_retries + 1):
            try:
                if self.provider == "openai" or self._compat:
                    # native openai + OpenAI-호환 계열(ollama/groq/... /generic)
                    response = await self._call_openai(formatted_messages, **kwargs)
                elif self.provider == "google":
                    response = await self._call_google(formatted_messages, **kwargs)
                elif self.provider == "anthropic":
                    response = await self._call_anthropic(formatted_messages, **kwargs)
                else:
                    raise ValueError(f"지원되지 않는 프로바이더: {self.provider}")

                # Harness per-execution budget: 토큰(비용) 누적 (예산 미활성 시 no-op).
                try:
                    from .guardrails import record_llm_tokens
                    _bt = self._extract_token_usage(response)
                    record_llm_tokens(_bt.get("input", 0), _bt.get("output", 0))
                except Exception:
                    pass  # 예산 계측이 LLM 응답을 절대 훼손하지 않도록

                # Observability: report metrics
                _duration = (_time.time() - _start_time) * 1000
                if LLMClient._metrics_callback:
                    try:
                        tokens = self._extract_token_usage(response)
                        LLMClient._metrics_callback({
                            "model": self.model,
                            "provider": self.provider,
                            "input_tokens": tokens.get("input", 0),
                            "output_tokens": tokens.get("output", 0),
                            "duration_ms": _duration,
                            "success": True,
                            "prompt_preview": _prompt_preview,
                        })
                    except Exception:
                        pass  # Never block on metrics

                # Tracing: LLM 호출 Span (이미 측정된 _duration 사용)
                try:
                    from logosai.utils.trace_span import TraceSpan
                    tokens = self._extract_token_usage(response)
                    _llm_span = TraceSpan.start(
                        name=f"llm.{self.model}",
                        agent_id="",
                        input_text=_prompt_preview,
                        stage="llm",
                    )
                    # start_time을 실제 호출 시작으로 보정
                    _llm_span.start_time = _start_time
                    _llm_span.end(
                        success=True,
                        output=response.content[:200] if hasattr(response, 'content') else "",
                        metadata={
                            "model": self.model,
                            "provider": self.provider,
                            "input_tokens": tokens.get("input", 0),
                            "output_tokens": tokens.get("output", 0),
                        },
                    )
                except Exception:
                    pass

                return response

            except (ValueError, TypeError, NotImplementedError) as e:
                raise  # Non-retryable
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    delay = min(1.0 * (2 ** attempt), 5.0)
                    logger.debug(f"LLM retry {attempt+1}/{max_retries}: {type(e).__name__} (delay={delay:.1f}s)")
                    await _aio.sleep(delay)
                    continue
                logger.error(f"LLM 호출 실패 ({max_retries+1}회 시도): {e}")
                raise
    
    async def invoke_with_tools(
        self,
        messages: List[Union[LLMMessage, Dict[str, str]]],
        tools: List[Dict[str, Any]],
        **kwargs,
    ) -> LLMResponse:
        """LLM 호출 with function calling (도구 사용).

        Args:
            messages: 대화 메시지 리스트
            tools: 도구 정의 리스트. 각 도구는:
                {
                    "name": "calculator",
                    "description": "수학 계산을 수행합니다",
                    "parameters": {
                        "expression": {"type": "string", "description": "계산할 수식"}
                    }
                }

        Returns:
            LLMResponse — content에 텍스트, tool_calls에 호출 요청
        """
        if not self._initialized:
            await self.initialize()

        formatted = [LLMMessage(**m) if isinstance(m, dict) else m for m in messages]

        if self.provider == "google":
            return await self._call_google_with_tools(formatted, tools, **kwargs)
        if self.provider == "openai" or self._compat:
            # OpenAI-호환 native function calling (2026-07-07 — 기존엔 프롬프트 폴백).
            # 일부 호환 서버는 tools 미지원 → 실패 시 기존 폴백으로 강등.
            try:
                return await self._call_openai_with_tools(formatted, tools, **kwargs)
            except Exception as e:
                logger.warning(f"native tool calling 실패, 프롬프트 폴백: {e}")
                return await self._call_with_tools_fallback(formatted, tools, **kwargs)
        if self.provider == "anthropic":
            # Anthropic native tool use (2026-07-19 — 기존엔 프롬프트 폴백).
            # openai 경로와 동일하게, 실패 시 조용히 폴백으로 강등한다.
            try:
                return await self._call_anthropic_with_tools(formatted, tools, **kwargs)
            except Exception as e:
                logger.warning(f"anthropic native tool calling 실패, 프롬프트 폴백: {e}")
                return await self._call_with_tools_fallback(formatted, tools, **kwargs)
        # 그 외: 도구 설명을 시스템 프롬프트에 포함하는 폴백
        return await self._call_with_tools_fallback(formatted, tools, **kwargs)

    async def _call_openai_with_tools(
        self,
        messages: List[LLMMessage],
        tools: List[Dict[str, Any]],
        **kwargs,
    ) -> LLMResponse:
        """OpenAI-호환 native function calling."""
        import json as _json

        oai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": {
                        "type": "object",
                        "properties": t.get("parameters", {}),
                    },
                },
            }
            for t in tools
        ]
        api_messages = [{"role": m.role, "content": m.content} for m in messages]
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=api_messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            tools=oai_tools,
        )
        msg = response.choices[0].message
        tool_calls = []
        for tc in (getattr(msg, "tool_calls", None) or []):
            try:
                args = _json.loads(tc.function.arguments or "{}")
            except (ValueError, TypeError):
                args = {}
            tool_calls.append(ToolCall(name=tc.function.name, args=args, id=getattr(tc, "id", "")))
        return LLMResponse(
            content=msg.content or "",
            provider=self.provider,
            model=self.model,
            tool_calls=tool_calls or None,
            raw_response=response,
        )

    async def _call_anthropic_with_tools(
        self,
        messages: List[LLMMessage],
        tools: List[Dict[str, Any]],
        **kwargs,
    ) -> LLMResponse:
        """Anthropic native tool use.

        스키마 차이 주의: OpenAI 는 function.parameters, Anthropic 은
        top-level `input_schema` 를 쓴다. 프레임워크 공통 tools 계약
        (name/description/parameters=properties dict) 을 여기서 변환한다.
        응답의 content 는 블록 배열이며 tool_use 블록에 {id, name, input} 이 온다.
        """
        anthropic_tools = [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": {
                    "type": "object",
                    "properties": t.get("parameters", {}) or {},
                },
            }
            for t in tools
        ]

        system_parts = [m.content for m in messages if m.role == "system"]
        api_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant")
        ]
        _kwargs = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": self.max_tokens or 1024,
            "temperature": self.temperature,
            "tools": anthropic_tools,
        }
        if system_parts:
            _kwargs["system"] = "\n\n".join(system_parts)

        response = await self._client.messages.create(**_kwargs)

        text_parts, tool_calls = [], []
        for block in (getattr(response, "content", None) or []):
            btype = getattr(block, "type", None)
            if btype == "tool_use":
                tool_calls.append(ToolCall(
                    name=getattr(block, "name", ""),
                    args=getattr(block, "input", None) or {},
                    id=getattr(block, "id", ""),
                ))
            else:
                text = getattr(block, "text", "")
                if text:
                    text_parts.append(text)

        usage = getattr(response, "usage", None)
        return LLMResponse(
            content="".join(text_parts),
            provider=self.provider,
            model=self.model,
            usage={
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
            } if usage else None,
            tool_calls=tool_calls or None,
            raw_response=response,
        )

    async def _call_google_with_tools(
        self,
        messages: List[LLMMessage],
        tools: List[Dict[str, Any]],
        **kwargs,
    ) -> LLMResponse:
        """Google Gemini function calling."""
        import asyncio
        from google.genai import types

        system_instruction = None
        contents = []
        for msg in messages:
            if msg.role == "system":
                system_instruction = msg.content
            elif msg.role == "user":
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=msg.content)],
                ))
            elif msg.role == "assistant":
                contents.append(types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=msg.content)],
                ))
            elif msg.role == "tool":
                # Tool result injection
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=f"[Tool Result] {msg.content}")],
                ))

        # Convert tool definitions to Gemini function declarations
        function_declarations = []
        for tool in tools:
            params = tool.get("parameters", {})
            properties = {}
            required = []
            for pname, pdef in params.items():
                properties[pname] = types.Schema(
                    type=pdef.get("type", "STRING").upper(),
                    description=pdef.get("description", ""),
                )
                if pdef.get("required", True):
                    required.append(pname)

            function_declarations.append(types.FunctionDeclaration(
                name=tool["name"],
                description=tool.get("description", ""),
                parameters=types.Schema(
                    type="OBJECT",
                    properties=properties,
                    required=required,
                ) if properties else None,
            ))

        config = types.GenerateContentConfig(
            temperature=kwargs.get("temperature", self.temperature),
            max_output_tokens=kwargs.get("max_tokens", self.max_tokens) or 4096,
            tools=[types.Tool(function_declarations=function_declarations)],
        )
        if system_instruction:
            config.system_instruction = system_instruction

        def sync_call():
            return self._client.models.generate_content(
                model=self.model,
                config=config,
                contents=contents if contents else "Hello",
            )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, sync_call)

        # Parse response — check for function calls
        tool_calls = []
        text_content = ""

        if hasattr(response, 'candidates') and response.candidates:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'function_call') and part.function_call:
                    fc = part.function_call
                    tool_calls.append(ToolCall(
                        name=fc.name,
                        args=dict(fc.args) if fc.args else {},
                        id=fc.name,
                    ))
                elif hasattr(part, 'text') and part.text:
                    text_content += part.text

        if not text_content and hasattr(response, 'text'):
            text_content = response.text or ""

        return LLMResponse(
            content=text_content,
            provider=self.provider,
            model=self.model,
            tool_calls=tool_calls if tool_calls else None,
        )

    async def _call_with_tools_fallback(
        self,
        messages: List[LLMMessage],
        tools: List[Dict[str, Any]],
        **kwargs,
    ) -> LLMResponse:
        """Non-Google providers: embed tool descriptions in system prompt."""
        import json

        tools_desc = "\n".join([
            f"- {t['name']}: {t.get('description', '')} "
            f"(params: {json.dumps(t.get('parameters', {}), ensure_ascii=False)})"
            for t in tools
        ])

        tool_prompt = (
            f"\n\nAvailable tools:\n{tools_desc}\n\n"
            f"To use a tool, respond with ONLY this JSON:\n"
            f'{{"tool_call": {{"name": "tool_name", "args": {{"param": "value"}}}}}}\n'
            f"If no tool is needed, respond normally."
        )

        # Inject into system message
        for msg in messages:
            if msg.role == "system":
                msg.content += tool_prompt
                break
        else:
            messages.insert(0, LLMMessage(role="system", content=tool_prompt))

        response = await self.invoke_messages(messages, **kwargs)

        # Parse tool_call from JSON response
        import re
        tc_match = re.search(r'\{"tool_call":\s*\{.*?\}\}', response.content, re.DOTALL)
        if tc_match:
            try:
                tc_data = json.loads(tc_match.group())["tool_call"]
                response.tool_calls = [ToolCall(
                    name=tc_data["name"],
                    args=tc_data.get("args", {}),
                )]
                response.content = ""  # Tool call, no text
            except Exception:
                pass

        return response

    async def _call_openai(self, messages: List[LLMMessage], **kwargs) -> LLMResponse:
        """OpenAI API 호출 — native chat.completions 단일 경로 (langchain 제거)."""
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
                # initialize()의 클라이언트 재사용 (없으면 생성 — 테스트 주입 용이)
                if self._client is not None:
                    direct_client = self._client
                else:
                    _dc_kwargs = {"api_key": self.api_key}
                    if self.base_url:
                        _dc_kwargs["base_url"] = self.base_url
                    direct_client = AsyncOpenAI(**_dc_kwargs)
                
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
    
    @staticmethod
    def _extract_token_usage(response: LLMResponse) -> Dict[str, int]:
        """LLM 응답에서 토큰 사용량 추출.

        Google Gemini: response.raw_response.usage_metadata
        OpenAI: response.raw_response.usage
        Anthropic: response.raw_response.usage
        """
        result = {"input": 0, "output": 0}
        try:
            raw = response.raw_response if hasattr(response, 'raw_response') else None
            if raw is None:
                return result

            # Google Gemini
            if hasattr(raw, 'usage_metadata'):
                um = raw.usage_metadata
                result["input"] = getattr(um, 'prompt_token_count', 0) or 0
                result["output"] = getattr(um, 'candidates_token_count', 0) or 0
                return result

            # OpenAI / Anthropic
            if hasattr(raw, 'usage'):
                usage = raw.usage
                if hasattr(usage, 'prompt_tokens'):
                    result["input"] = usage.prompt_tokens or 0
                    result["output"] = usage.completion_tokens or 0
                elif hasattr(usage, 'input_tokens'):
                    result["input"] = usage.input_tokens or 0
                    result["output"] = usage.output_tokens or 0
                return result

            # Dict fallback
            if isinstance(raw, dict):
                usage = raw.get('usage', {})
                result["input"] = usage.get('prompt_tokens', usage.get('input_tokens', 0))
                result["output"] = usage.get('completion_tokens', usage.get('output_tokens', 0))

        except Exception:
            pass
        return result

    async def _call_anthropic(self, messages: List[LLMMessage], **kwargs) -> LLMResponse:
        """Anthropic API 호출 — native AsyncAnthropic (langchain 제거).

        Anthropic Messages API 계약: system 은 messages 배열이 아니라
        별도 top-level 파라미터로 전달한다.
        """
        system_parts = [m.content for m in messages if m.role == "system"]
        api_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant")
        ]
        _kwargs = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": self.max_tokens or 1024,
            "temperature": self.temperature,
        }
        if system_parts:
            _kwargs["system"] = "\n\n".join(system_parts)

        response = await self._client.messages.create(**_kwargs)
        content = "".join(
            getattr(block, "text", "") for block in (response.content or [])
        )
        usage = getattr(response, "usage", None)
        return LLMResponse(
            content=content,
            provider=self.provider,
            model=self.model,
            usage={
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
            } if usage else None,
            raw_response=response,
        )

    # (구 _call_ollama 는 OpenAI-호환 통합으로 _call_openai 에 흡수 — 2026-07-07)
    
    def get_langchain_client(self):
        """LangChain 호환 래퍼 반환 (deprecated — 하위 호환용).

        2026-07-07 전면 native 화 이후 내부에 langchain 클라이언트는 없다.
        모든 프로바이더에 대해 ainvoke 호환 래퍼(GoogleLangChainWrapper —
        이름과 달리 langchain 미의존 duck-typing)를 반환한다.
        신규 코드는 invoke/invoke_messages 를 직접 사용할 것.
        """
        if not self._initialized:
            raise ValueError("클라이언트가 초기화되지 않았습니다. initialize()를 먼저 호출하세요.")
        return GoogleLangChainWrapper(self)
    
    @classmethod
    def create_openai(cls, model: str = "gpt-4o-mini", temperature: float = 0.7, **kwargs) -> 'LLMClient':
        """OpenAI 클라이언트 생성 단축 메서드"""
        return cls(provider="openai", model=model, temperature=temperature, **kwargs)
    
    @classmethod
    def create_google(cls, model: str = None, temperature: float = 0.7, **kwargs) -> 'LLMClient':
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
        default_model=_get_default_model(),
        fallback_model=_get_default_model()
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
    model: str = None,
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