"""
LogosAI SimpleAgent — Zero-boilerplate base class for LLM-based agents.

SimpleAgent extends LogosAIAgent and auto-handles:
  - AgentConfig creation from class attributes
  - LLMClient initialization (lazy)
  - publish_status() with safe message_bus guard
  - process() error handling wrapping handle()
  - initialize() / shutdown() lifecycle
  - process_query() compatibility wrapper

Subclasses implement only:
  - agent_name, agent_description (class attributes)
  - async def handle(self, query, context) -> AgentResponse

Usage:
    from logosai import SimpleAgent, AgentResponse

    class MyAgent(SimpleAgent):
        agent_name = "My Agent"
        agent_description = "Does something useful"
        llm_temperature = 0.3

        async def handle(self, query, context=None):
            answer = await self.ask_llm(f"Process: {query}")
            return AgentResponse.success(content={"answer": answer})

v0.9.0
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional, Union, Callable, Type

from .agent import LogosAIAgent
from .agent_types import AgentType, AgentResponse, AgentResponseType
from .config import AgentConfig

try:
    from loguru import logger as _loguru_logger
except ImportError:
    _loguru_logger = None

_logger = logging.getLogger(__name__)


class SimpleAgent(LogosAIAgent):
    """
    Simplified base class for LLM-based agents.

    Override class attributes for configuration and implement handle() for logic.
    Everything else (init, lifecycle, error handling, status publishing) is automatic.
    """

    # --- Override these in subclasses ---
    agent_name: str = "Unnamed Agent"
    agent_description: str = ""
    agent_type_value: Union[AgentType, str] = AgentType.CUSTOM

    # LLM configuration
    llm_provider: str = "google"
    llm_model: str = "gemini-2.5-flash-lite"
    llm_temperature: float = 0.7
    llm_max_tokens: int = 4000

    def __init__(self, config: Optional[AgentConfig] = None):
        """Initialize SimpleAgent.

        If config is None, auto-creates AgentConfig from class attributes.
        If config is provided (e.g. by ACP agent_loader), uses that instead.
        """
        if config is None:
            config = AgentConfig(
                name=self.agent_name,
                agent_type=self.agent_type_value,
                description=self.agent_description,
                config={
                    "provider": self.llm_provider,
                    "model": self.llm_model,
                    "temperature": self.llm_temperature,
                    "max_tokens": self.llm_max_tokens,
                },
            )

        super().__init__(config)

        # Extract config values (handles both class-attr and ACP-provided configs)
        self.name = getattr(config, "name", None) or self.agent_name
        self.description = getattr(config, "description", "") or self.agent_description
        self.agent_type = getattr(config, "agent_type", None) or self.agent_type_value
        params = getattr(config, "config", None) or {}

        # LLM settings from config dict (allows ACP override)
        self._llm_provider = params.get("provider", self.llm_provider)
        self._llm_model = params.get("model", self.llm_model)
        self._llm_temperature = params.get("temperature", self.llm_temperature)
        self._llm_max_tokens = params.get("max_tokens", self.llm_max_tokens)

        # State
        self.message_bus = None
        self.initialized = False
        self.parameters = params

        # Create LLM client (lazy-initialized on first use)
        self.llm_client = None
        self._llm_init_lock = asyncio.Lock()

    async def _ensure_llm(self):
        """Ensure LLM client is created and initialized."""
        if self.llm_client is not None and getattr(self.llm_client, "_initialized", False):
            return

        async with self._llm_init_lock:
            # Double-check after acquiring lock
            if self.llm_client is not None and getattr(self.llm_client, "_initialized", False):
                return

            try:
                from .utils.llm_client import LLMClient

                if self.llm_client is None:
                    self.llm_client = LLMClient(
                        provider=self._llm_provider,
                        model=self._llm_model,
                        temperature=self._llm_temperature,
                        max_tokens=self._llm_max_tokens,
                    )

                await self.llm_client.initialize()
                _logger.info(
                    f"[{self.name}] LLM initialized: {self._llm_provider}/{self._llm_model}"
                )
            except Exception as e:
                _logger.error(f"[{self.name}] LLM initialization failed: {e}")
                raise

    # ─── Core API: override this ────────────────────────

    async def handle(self, query: str, context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        """
        Business logic goes here. Override in subclasses.

        Args:
            query: User query string
            context: Optional context dict (may contain email, session info, etc.)

        Returns:
            AgentResponse with your result
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement handle()"
        )

    # ─── ACP-facing lifecycle ───────────────────────────

    async def initialize(self) -> bool:
        """Initialize agent. Idempotent."""
        if self.initialized:
            return True

        try:
            await super().initialize()
            await self._ensure_llm()
            self.initialized = True
            _logger.info(f"[{self.name}] initialized ({self._llm_provider}/{self._llm_model})")
            return True
        except Exception as e:
            _logger.error(f"[{self.name}] initialization failed: {e}")
            self.initialized = False
            return False

    async def process(self, query: str, context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        """
        ACP-facing process method. Wraps handle() with:
          - Auto-initialization
          - Status publishing (processing/completed/error)
          - Error handling → AgentResponse.error()
        """
        try:
            # Auto-init if needed
            if not self.initialized:
                await self.initialize()

            await self.publish_status("processing", {"query": query[:200]})

            # Ensure LLM is ready
            await self._ensure_llm()

            # Call user's business logic
            result = await self.handle(query, context)

            await self.publish_status("completed", {"query": query[:200]})
            return result

        except NotImplementedError:
            raise
        except Exception as e:
            _logger.error(f"[{self.name}] process error: {e}")
            await self.publish_status("error", {"query": query[:200], "error": str(e)})
            return AgentResponse(
                type=AgentResponseType.ERROR,
                content={"error": str(e)},
                message=f"Error: {e}",
                metadata={"error_type": type(e).__name__, "agent": self.name},
            )

    async def process_query(self, query: str, context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        """Compatibility wrapper for ACP server."""
        return await self.process(query, context)

    async def shutdown(self) -> bool:
        """Cleanup resources."""
        _logger.info(f"[{self.name}] shutting down...")
        self.initialized = False
        try:
            return await super().shutdown()
        except (AttributeError, NotImplementedError):
            return True

    # ─── Convenience: LLM helpers ───────────────────────

    async def ask_llm(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        """
        Call LLM and return content string.

        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            **kwargs: Extra params passed to LLMClient.invoke_messages()

        Returns:
            Response content as string
        """
        await self._ensure_llm()

        if system_prompt:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
            response = await self.llm_client.invoke_messages(messages, **kwargs)
        else:
            response = await self.llm_client.invoke(prompt, **kwargs)

        return response.content

    async def ask_llm_json(self, prompt: str, system_prompt: Optional[str] = None, fallback: Optional[Dict] = None, **kwargs) -> Dict[str, Any]:
        """
        Call LLM and parse JSON from response.

        Args:
            prompt: User prompt (should instruct LLM to respond in JSON)
            system_prompt: Optional system prompt
            fallback: Default dict if JSON parsing fails
            **kwargs: Extra params passed to LLMClient

        Returns:
            Parsed dict from LLM response
        """
        from .utils.text_utils import parse_llm_json

        content = await self.ask_llm(prompt, system_prompt=system_prompt, **kwargs)
        return parse_llm_json(content, fallback=fallback or {})

    # ─── Status publishing ──────────────────────────────

    async def publish_status(self, status: str, data: Optional[Dict[str, Any]] = None):
        """Safely publish status via message_bus (no-op if not connected)."""
        if not getattr(self, "message_bus", None):
            return
        try:
            await self.message_bus.publish(
                "agent/status",
                {
                    "agent_id": getattr(self, "id", self.name),
                    "agent_name": self.name,
                    "status": status,
                    **(data or {}),
                    "timestamp": datetime.now().isoformat(),
                },
            )
        except Exception as e:
            _logger.debug(f"[{self.name}] status publish failed: {e}")


# ─── @agent decorator ──────────────────────────────────


def agent(
    name: str,
    description: str = "",
    agent_type: Union[AgentType, str] = AgentType.CUSTOM,
    provider: str = "google",
    model: str = "gemini-2.5-flash-lite",
    temperature: float = 0.7,
    max_tokens: int = 4000,
):
    """
    Decorator: convert an async function into a full LogosAI agent.

    The decorated function receives (query, context, llm) where llm is
    the agent's auto-initialized LLMClient.

    Usage:
        @agent(name="Joke Agent", description="Tells jokes")
        async def joke_agent(query, context=None, llm=None):
            response = await llm.invoke(f"Tell a joke about: {query}")
            return AgentResponse.success(content={"answer": response.content})

        # Create instance and use
        instance = joke_agent()
        result = await instance.process("cats")

    Returns:
        A factory function that creates SimpleAgent instances.
    """

    def decorator(func: Callable):
        # Create a dynamic SimpleAgent subclass
        cls = type(
            func.__name__,
            (SimpleAgent,),
            {
                "agent_name": name,
                "agent_description": description or func.__doc__ or "",
                "agent_type_value": agent_type,
                "llm_provider": provider,
                "llm_model": model,
                "llm_temperature": temperature,
                "llm_max_tokens": max_tokens,
                "handle": _make_handle(func),
            },
        )

        def factory(config: Optional[AgentConfig] = None) -> SimpleAgent:
            return cls(config)

        factory.__name__ = func.__name__
        factory.__doc__ = func.__doc__
        factory._agent_class = cls
        return factory

    return decorator


def _make_handle(func: Callable):
    """Create a handle method that injects llm into the decorated function."""

    async def handle(self, query: str, context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        await self._ensure_llm()
        return await func(query, context=context, llm=self.llm_client)

    return handle


def create_simple_agent(
    name: str,
    handle_func: Callable,
    description: str = "",
    provider: str = "google",
    model: str = "gemini-2.5-flash-lite",
    temperature: float = 0.7,
    max_tokens: int = 4000,
    **kwargs,
) -> SimpleAgent:
    """
    Factory: create a SimpleAgent from a function.

    Args:
        name: Agent name
        handle_func: Async function(query, context=None, llm=None) -> AgentResponse
        description: Agent description
        provider: LLM provider
        model: LLM model name
        temperature: LLM temperature
        max_tokens: Max tokens
        **kwargs: Extra config params

    Returns:
        SimpleAgent instance ready to use

    Usage:
        async def my_handler(query, context=None, llm=None):
            resp = await llm.invoke(query)
            return AgentResponse.success(content={"answer": resp.content})

        agent = create_simple_agent("My Agent", my_handler, description="Test")
        result = await agent.process("hello")
    """
    cls = type(
        f"{name.replace(' ', '')}Agent",
        (SimpleAgent,),
        {
            "agent_name": name,
            "agent_description": description,
            "llm_provider": provider,
            "llm_model": model,
            "llm_temperature": temperature,
            "llm_max_tokens": max_tokens,
            "handle": _make_handle(handle_func),
        },
    )
    return cls()
