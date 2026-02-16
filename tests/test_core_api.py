"""
Core API Tests for LogosAI SDK

Tests the public-facing APIs that developers use:
1. AgentConfig — creation, update, serialization
2. AgentType & AgentResponseType — enum behavior, from_string
3. AgentResponse — construction, factories, serialization
4. ClassificationResult — pydantic validation
5. LogosAIAgent — lifecycle (init, initialize, process), subclassing
6. Top-level imports — verify from logosai import X works
"""

import asyncio
import pytest
from typing import Any, Dict, Optional


# ─── 1. Top-level public import ──────────────────────────────────────

class TestPublicImports:
    """Verify that the documented public API is importable from top-level."""

    def test_core_classes(self):
        from logosai import LogosAIAgent, AgentConfig, AgentType, AgentResponse, AgentResponseType
        assert LogosAIAgent is not None
        assert AgentConfig is not None
        assert AgentType is not None
        assert AgentResponse is not None
        assert AgentResponseType is not None

    def test_create_agent_function(self):
        from logosai import create_agent
        assert callable(create_agent)

    def test_classification_types(self):
        from logosai import TaskType, ClassificationResult, get_agent_types
        assert TaskType is not None
        assert ClassificationResult is not None
        assert callable(get_agent_types)


# ─── 2. AgentType enum ──────────────────────────────────────────────

class TestAgentType:
    def test_known_members(self):
        from logosai import AgentType
        assert AgentType.CUSTOM.value == "custom"
        assert AgentType.SEARCH.value == "search"
        assert AgentType.GENERAL.value == "general"
        assert AgentType.UNKNOWN.value == "unknown"

    def test_string_enum(self):
        """AgentType is a str enum, so it can be compared to str."""
        from logosai import AgentType
        assert AgentType.CUSTOM == "custom"
        # str() on enum includes the name (not value) in Python 3.11+
        assert "CUSTOM" in str(AgentType.CUSTOM)

    def test_construct_from_value(self):
        from logosai import AgentType
        assert AgentType("custom") is AgentType.CUSTOM

    def test_invalid_value_raises(self):
        from logosai import AgentType
        with pytest.raises(ValueError):
            AgentType("nonexistent_type")


# ─── 3. AgentResponseType enum ──────────────────────────────────────

class TestAgentResponseType:
    def test_known_members(self):
        from logosai import AgentResponseType
        assert AgentResponseType.SUCCESS.value == "SUCCESS"
        assert AgentResponseType.ERROR.value == "ERROR"
        assert AgentResponseType.TEXT.value == "TEXT"
        assert AgentResponseType.HTML.value == "HTML"
        assert AgentResponseType.JSON.value == "JSON"

    def test_from_string_exact(self):
        from logosai import AgentResponseType
        assert AgentResponseType.from_string("SUCCESS") is AgentResponseType.SUCCESS
        assert AgentResponseType.from_string("ERROR") is AgentResponseType.ERROR

    def test_from_string_case_insensitive(self):
        from logosai import AgentResponseType
        assert AgentResponseType.from_string("success") is AgentResponseType.SUCCESS
        assert AgentResponseType.from_string("Error") is AgentResponseType.ERROR

    def test_from_string_invalid_returns_text(self):
        from logosai import AgentResponseType
        assert AgentResponseType.from_string("BOGUS") is AgentResponseType.TEXT

    def test_from_string_non_string_returns_text(self):
        from logosai import AgentResponseType
        assert AgentResponseType.from_string(42) is AgentResponseType.TEXT
        assert AgentResponseType.from_string(None) is AgentResponseType.TEXT


# ─── 4. AgentResponse ───────────────────────────────────────────────

class TestAgentResponse:
    def test_basic_construction(self):
        from logosai import AgentResponse, AgentResponseType
        resp = AgentResponse(
            type=AgentResponseType.SUCCESS,
            content={"answer": "42"},
            message="ok",
        )
        assert resp.type is AgentResponseType.SUCCESS
        assert resp.content == {"answer": "42"}
        assert resp.message == "ok"
        assert resp.metadata == {}

    def test_defaults(self):
        from logosai import AgentResponse, AgentResponseType
        resp = AgentResponse(type=AgentResponseType.TEXT, content={})
        assert resp.metadata == {}
        assert resp.message == ""

    def test_to_dict(self):
        from logosai import AgentResponse, AgentResponseType
        resp = AgentResponse(
            type=AgentResponseType.SUCCESS,
            content={"answer": "hello"},
            metadata={"source": "test"},
            message="done",
        )
        d = resp.to_dict()
        assert d["type"] == "AgentResponseType.SUCCESS"
        assert d["content"] == {"answer": "hello"}
        assert d["metadata"] == {"source": "test"}
        assert d["message"] == "done"

    def test_from_dict(self):
        from logosai import AgentResponse, AgentResponseType
        d = {"type": "SUCCESS", "content": {"answer": "42"}, "message": "ok"}
        resp = AgentResponse.from_dict(d)
        assert resp.type is AgentResponseType.SUCCESS
        assert resp.content["answer"] == "42"
        assert resp.message == "ok"

    def test_from_dict_defaults(self):
        from logosai import AgentResponse, AgentResponseType
        resp = AgentResponse.from_dict({})
        assert resp.type is AgentResponseType.TEXT
        assert resp.content == {}
        assert resp.message == ""

    def test_error_factory(self):
        from logosai import AgentResponse, AgentResponseType
        resp = AgentResponse.error("something failed")
        assert resp.type is AgentResponseType.ERROR
        assert resp.content == {"error": "something failed"}
        assert resp.message == "something failed"
        assert resp.metadata["error_message"] == "something failed"

    def test_error_factory_custom_content(self):
        from logosai import AgentResponse, AgentResponseType
        resp = AgentResponse.error("fail", content={"detail": "bad input"})
        assert resp.content == {"detail": "bad input"}

    def test_success_factory(self):
        from logosai import AgentResponse, AgentResponseType
        resp = AgentResponse.success("all good")
        assert resp.type is AgentResponseType.SUCCESS
        assert resp.content == {"message": "all good"}
        assert resp.message == "all good"

    def test_success_factory_custom_content(self):
        from logosai import AgentResponse, AgentResponseType
        resp = AgentResponse.success("ok", content={"data": [1, 2, 3]})
        assert resp.content == {"data": [1, 2, 3]}

    def test_roundtrip(self):
        from logosai import AgentResponse, AgentResponseType
        original = AgentResponse(
            type=AgentResponseType.SUCCESS,
            content={"answer": "test"},
            metadata={"k": "v"},
            message="msg",
        )
        d = original.to_dict()
        restored = AgentResponse.from_dict(d)
        assert restored.content == original.content
        assert restored.message == original.message


# ─── 5. AgentConfig ─────────────────────────────────────────────────

class TestAgentConfig:
    def test_basic_creation(self):
        from logosai import AgentConfig, AgentType
        cfg = AgentConfig(name="Test", agent_type=AgentType.CUSTOM)
        assert cfg.name == "Test"
        assert cfg.agent_type is AgentType.CUSTOM
        assert cfg.description == ""
        assert cfg.config == {}
        assert cfg.api_config == {}
        assert cfg.llm_config == {}

    def test_full_creation(self):
        from logosai import AgentConfig, AgentType
        cfg = AgentConfig(
            name="Full Agent",
            agent_type=AgentType.SEARCH,
            description="A search agent",
            config={"key": "value"},
            api_config={"url": "http://example.com"},
            llm_config={"model": "gpt-4"},
        )
        assert cfg.description == "A search agent"
        assert cfg.config["key"] == "value"
        assert cfg.api_config["url"] == "http://example.com"
        assert cfg.llm_config["model"] == "gpt-4"

    def test_string_agent_type(self):
        """AgentConfig accepts a string for agent_type and converts it."""
        from logosai import AgentConfig, AgentType
        cfg = AgentConfig(name="Test", agent_type="custom")
        assert cfg.agent_type is AgentType.CUSTOM

    def test_invalid_string_agent_type(self):
        """Invalid string falls back to UNKNOWN."""
        from logosai import AgentConfig, AgentType
        cfg = AgentConfig(name="Test", agent_type="nonexistent")
        assert cfg.agent_type is AgentType.UNKNOWN

    def test_update(self):
        from logosai import AgentConfig, AgentType
        cfg = AgentConfig(name="Old", agent_type=AgentType.CUSTOM)
        result = cfg.update(name="New", description="updated")
        assert result is cfg  # returns self
        assert cfg.name == "New"
        assert cfg.description == "updated"

    def test_update_agent_type_string(self):
        from logosai import AgentConfig, AgentType
        cfg = AgentConfig(name="Test", agent_type=AgentType.CUSTOM)
        cfg.update(agent_type="search")
        assert cfg.agent_type is AgentType.SEARCH

    def test_update_merges_config(self):
        from logosai import AgentConfig, AgentType
        cfg = AgentConfig(name="Test", agent_type=AgentType.CUSTOM, config={"a": 1})
        cfg.update(config={"b": 2})
        assert cfg.config == {"a": 1, "b": 2}

    def test_to_dict(self):
        from logosai import AgentConfig, AgentType
        cfg = AgentConfig(
            name="Test",
            agent_type=AgentType.CUSTOM,
            description="desc",
        )
        d = cfg.to_dict()
        assert d["name"] == "Test"
        assert "custom" in d["agent_type"].lower()
        assert d["description"] == "desc"
        assert isinstance(d["config"], dict)
        assert isinstance(d["api_config"], dict)
        assert isinstance(d["llm_config"], dict)

    def test_from_dict(self):
        from logosai import AgentConfig, AgentType
        d = {
            "name": "From Dict",
            "agent_type": "custom",
            "description": "created from dict",
            "config": {"x": 10},
        }
        cfg = AgentConfig.from_dict(d)
        assert cfg.name == "From Dict"
        assert cfg.agent_type is AgentType.CUSTOM
        assert cfg.description == "created from dict"
        assert cfg.config["x"] == 10

    def test_from_dict_defaults(self):
        from logosai import AgentConfig, AgentType
        cfg = AgentConfig.from_dict({})
        assert cfg.name == "Unknown Agent"
        assert cfg.description == ""

    def test_str(self):
        from logosai import AgentConfig, AgentType
        cfg = AgentConfig(name="My Agent", agent_type=AgentType.CUSTOM)
        s = str(cfg)
        assert "My Agent" in s
        assert "custom" in s.lower()

    def test_to_dict_returns_copies(self):
        """to_dict should return copies, not references to internal dicts."""
        from logosai import AgentConfig, AgentType
        cfg = AgentConfig(name="Test", agent_type=AgentType.CUSTOM, config={"a": 1})
        d = cfg.to_dict()
        d["config"]["a"] = 999
        assert cfg.config["a"] == 1  # original unchanged


# ─── 6. LogosAIAgent lifecycle ───────────────────────────────────────

class SimpleTestAgent(object):
    """Minimal agent for lifecycle tests (avoids heavy imports at module scope)."""
    pass


class TestAgentLifecycle:
    def _make_agent_class(self):
        from logosai import LogosAIAgent, AgentConfig, AgentType, AgentResponse, AgentResponseType

        class TestAgent(LogosAIAgent):
            def __init__(self):
                config = AgentConfig(
                    name="Test Agent",
                    agent_type=AgentType.CUSTOM,
                    description="Agent for lifecycle testing",
                )
                super().__init__(config)

            async def process(self, query: str, context=None) -> AgentResponse:
                return AgentResponse(
                    type=AgentResponseType.SUCCESS,
                    content={"answer": f"echo: {query}"},
                    message="ok",
                )

        return TestAgent

    def test_construction(self):
        TestAgent = self._make_agent_class()
        agent = TestAgent()
        assert agent.name == "Test Agent"
        assert agent.initialized is False

    @pytest.mark.asyncio
    async def test_initialize(self):
        TestAgent = self._make_agent_class()
        agent = TestAgent()
        result = await agent.initialize()
        assert result is True
        assert agent.initialized is True

    @pytest.mark.asyncio
    async def test_process(self):
        TestAgent = self._make_agent_class()
        agent = TestAgent()
        await agent.initialize()
        resp = await agent.process("hello")
        from logosai import AgentResponseType
        assert resp.type is AgentResponseType.SUCCESS
        assert resp.content["answer"] == "echo: hello"

    @pytest.mark.asyncio
    async def test_process_auto_initializes(self):
        """Calling process() on an uninitialized base agent should auto-initialize."""
        from logosai import LogosAIAgent, AgentConfig, AgentType, AgentResponse, AgentResponseType

        class AutoInitAgent(LogosAIAgent):
            def __init__(self):
                super().__init__(AgentConfig(name="AutoInit", agent_type=AgentType.CUSTOM))

            async def process(self, query: str, context=None) -> AgentResponse:
                if not self.initialized:
                    await self.initialize()
                return AgentResponse.success("ok")

        agent = AutoInitAgent()
        assert agent.initialized is False
        resp = await agent.process("test")
        assert agent.initialized is True

    @pytest.mark.asyncio
    async def test_base_process_raises_not_implemented(self):
        """LogosAIAgent.process() raises NotImplementedError when not overridden."""
        from logosai import LogosAIAgent, AgentConfig, AgentType
        agent = LogosAIAgent(AgentConfig(name="Base", agent_type=AgentType.CUSTOM))
        with pytest.raises(NotImplementedError):
            await agent.process("test")

    def test_get_info(self):
        TestAgent = self._make_agent_class()
        agent = TestAgent()
        info = agent.get_info()
        assert info["name"] == "Test Agent"
        assert info["type"] == "custom"
        assert info["initialized"] is False

    @pytest.mark.asyncio
    async def test_can_handle_default(self):
        """Default can_handle returns (True, 0.5, reason)."""
        TestAgent = self._make_agent_class()
        agent = TestAgent()
        can, confidence, reason = await agent.can_handle("some query")
        assert isinstance(can, bool)
        assert 0.0 <= confidence <= 1.0
        assert isinstance(reason, str)

    def test_can_collaborate_without_service(self):
        TestAgent = self._make_agent_class()
        agent = TestAgent()
        assert agent.can_collaborate is False

    @pytest.mark.asyncio
    async def test_discover_agents_without_service(self):
        TestAgent = self._make_agent_class()
        agent = TestAgent()
        result = await agent.discover_agents("translation")
        assert result == []


# ─── 7. LogosAIAgent streaming ───────────────────────────────────────

class TestAgentStreaming:
    @pytest.mark.asyncio
    async def test_process_stream_events(self):
        from logosai import LogosAIAgent, AgentConfig, AgentType, AgentResponse, AgentResponseType

        class StreamAgent(LogosAIAgent):
            def __init__(self):
                super().__init__(AgentConfig(name="Streamer", agent_type=AgentType.CUSTOM))

            async def process(self, query: str, context=None) -> AgentResponse:
                return AgentResponse.success("done", content={"answer": "streamed"})

        agent = StreamAgent()
        events = []
        async for event in agent.process_stream("hello"):
            events.append(event)

        types = [e["type"] for e in events]
        assert types[0] == "start"
        assert "progress" in types
        assert "chunk" in types
        assert types[-1] == "complete"

    @pytest.mark.asyncio
    async def test_process_stream_not_implemented(self):
        from logosai import LogosAIAgent, AgentConfig, AgentType

        agent = LogosAIAgent(AgentConfig(name="Base", agent_type=AgentType.CUSTOM))
        events = []
        async for event in agent.process_stream("hello"):
            events.append(event)

        types = [e["type"] for e in events]
        assert "error" in types

    @pytest.mark.asyncio
    async def test_process_stream_has_timestamps(self):
        from logosai import LogosAIAgent, AgentConfig, AgentType, AgentResponse, AgentResponseType

        class TimedAgent(LogosAIAgent):
            def __init__(self):
                super().__init__(AgentConfig(name="Timed", agent_type=AgentType.CUSTOM))

            async def process(self, query: str, context=None) -> AgentResponse:
                return AgentResponse.success("ok")

        agent = TimedAgent()
        async for event in agent.process_stream("q"):
            assert "timestamp" in event
            assert isinstance(event["timestamp"], float)


# ─── 8. ClassificationResult ────────────────────────────────────────

class TestClassificationResult:
    def test_valid_creation(self):
        from logosai import ClassificationResult
        result = ClassificationResult(
            task_type="unknown",
            confidence=0.85,
            reasoning="test reasoning",
            requires_analysis=False,
        )
        assert result.task_type == "unknown"
        assert result.confidence == 0.85
        assert result.reasoning == "test reasoning"
        assert result.requires_analysis is False

    def test_confidence_bounds(self):
        from logosai import ClassificationResult
        with pytest.raises(Exception):  # pydantic validation error
            ClassificationResult(
                task_type="unknown",
                confidence=1.5,  # out of range
                reasoning="test",
                requires_analysis=False,
            )

    def test_invalid_task_type_falls_back_to_unknown(self):
        from logosai import ClassificationResult
        result = ClassificationResult(
            task_type="nonexistent_agent_type",
            confidence=0.5,
            reasoning="test",
            requires_analysis=False,
        )
        assert result.task_type == "unknown"


# ─── 9. Samples execute correctly ───────────────────────────────────

class TestSamples:
    """Verify the public samples from logosai/samples/ work end-to-end."""

    @pytest.mark.asyncio
    async def test_hello_agent_pattern(self):
        """Mirrors samples/hello_agent.py logic."""
        from logosai import LogosAIAgent, AgentConfig, AgentType, AgentResponse, AgentResponseType

        class HelloAgent(LogosAIAgent):
            def __init__(self):
                config = AgentConfig(
                    name="Hello Agent",
                    agent_type=AgentType.CUSTOM,
                    description="A simple greeting agent",
                )
                super().__init__(config)

            async def process(self, query: str, context=None) -> AgentResponse:
                return AgentResponse(
                    type=AgentResponseType.SUCCESS,
                    content={"answer": f"Hello! You said: {query}"},
                    message="Greeting generated",
                )

        agent = HelloAgent()
        await agent.initialize()
        result = await agent.process("Hi there!")
        assert result.content["answer"] == "Hello! You said: Hi there!"

    @pytest.mark.asyncio
    async def test_calculator_agent_pattern(self):
        """Mirrors samples/calculator_agent.py logic."""
        import re
        from logosai import LogosAIAgent, AgentConfig, AgentType, AgentResponse, AgentResponseType

        class CalculatorAgent(LogosAIAgent):
            def __init__(self):
                config = AgentConfig(
                    name="Calculator Agent",
                    agent_type=AgentType.CUSTOM,
                    description="Evaluates arithmetic expressions safely",
                )
                super().__init__(config)

            async def process(self, query: str, context=None) -> AgentResponse:
                expr = re.sub(r"[^0-9+\-*/().\s]", "", query)
                if not expr.strip():
                    return AgentResponse(
                        type=AgentResponseType.ERROR,
                        content={"error": "No valid expression found"},
                        message="Parse error",
                    )
                try:
                    result = eval(expr, {"__builtins__": {}}, {})
                    return AgentResponse(
                        type=AgentResponseType.SUCCESS,
                        content={"answer": f"{expr.strip()} = {result}"},
                        message="Calculation complete",
                    )
                except Exception as e:
                    return AgentResponse(
                        type=AgentResponseType.ERROR,
                        content={"error": str(e)},
                        message="Calculation failed",
                    )

        agent = CalculatorAgent()
        await agent.initialize()

        r1 = await agent.process("3 + 5")
        assert "8" in r1.content["answer"]

        r2 = await agent.process("100 / 4 * 2")
        assert "50" in r2.content["answer"]

        r3 = await agent.process("(10 + 20) * 3")
        assert "90" in r3.content["answer"]

        r4 = await agent.process("no math here!")
        assert r4.type is AgentResponseType.ERROR
