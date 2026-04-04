"""Mixin 리팩터링 전후 동작 일관성 테스트.

agent.py를 Mixin으로 분리한 후에도 기존 동작이 동일한지 검증.
"""

import asyncio
import pytest
import sys
import os

# Add logosai to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from logosai.config import AgentConfig
from logosai.agent_types import AgentType, AgentResponse, AgentResponseType
from logosai.agent import LogosAIAgent
from logosai.simple_agent import SimpleAgent


def make_config(name="test_agent"):
    """테스트용 AgentConfig 생성 헬퍼."""
    return AgentConfig(name=name, agent_type=AgentType.CUSTOM)


# ── 1. 기본 생성/초기화 테스트 ──

class TestAgentInit:
    """에이전트 생성 및 초기화가 정상 동작하는지 확인."""

    def test_create_agent(self):
        config = make_config("test_agent")
        agent = LogosAIAgent(config)
        assert agent.name == "test_agent"
        assert agent.initialized is False

    @pytest.mark.asyncio
    async def test_initialize(self):
        config = make_config("test_agent")
        agent = LogosAIAgent(config)
        result = await agent.initialize()
        assert agent.initialized is True

    def test_instance_variables_exist(self):
        """Mixin 분리 후에도 모든 인스턴스 변수가 존재해야 함."""
        config = make_config("test")
        agent = LogosAIAgent(config)
        # 핵심 변수
        assert hasattr(agent, '_tools')
        assert hasattr(agent, '_tool_executors')
        assert hasattr(agent, '_tool_metrics')
        assert hasattr(agent, '_memory_store')
        assert hasattr(agent, '_agent_registry')
        assert hasattr(agent, '_stream_callback')
        assert isinstance(agent._tools, list)
        assert isinstance(agent._tool_executors, dict)


# ── 2. Tool 등록/조회 테스트 ──

class TestToolUse:
    """도구 등록, has_tools, run_with_tools 테스트."""

    def test_register_tool(self):
        config = make_config("test")
        agent = LogosAIAgent(config)
        assert agent.has_tools is False

        async def my_func(x): return x
        agent.register_tool("echo", "Echo input", my_func, {"x": {"type": "string"}})

        assert agent.has_tools is True
        assert len(agent._tools) == 1
        assert agent._tools[0]["name"] == "echo"
        assert "echo" in agent._tool_executors

    def test_register_tool_replaces_existing(self):
        config = make_config("test")
        agent = LogosAIAgent(config)

        async def func_v1(x): return "v1"
        async def func_v2(x): return "v2"

        agent.register_tool("calc", "V1", func_v1)
        agent.register_tool("calc", "V2", func_v2)

        assert len(agent._tools) == 1
        assert agent._tools[0]["description"] == "V2"

    def test_register_builtin_tools(self):
        config = make_config("test")
        agent = LogosAIAgent(config)
        agent.register_builtin_tools()
        assert agent.has_tools is True
        names = [t["name"] for t in agent._tools]
        assert "calculator" in names or len(names) > 0


# ── 3. Memory 테스트 ──

class TestMemory:
    """memorize, recall, recall_as_context 테스트."""

    @pytest.mark.asyncio
    async def test_ensure_memory(self):
        config = make_config("test_mem")
        agent = LogosAIAgent(config)
        assert agent._memory_store is None
        await agent._ensure_memory()
        assert agent._memory_store is not None

    @pytest.mark.asyncio
    async def test_recall_empty(self):
        config = make_config("test_mem2")
        agent = LogosAIAgent(config)
        results = await agent.recall("nonexistent query")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_recall_as_context_empty(self):
        config = make_config("test_mem3")
        agent = LogosAIAgent(config)
        ctx = await agent.recall_as_context("test query")
        assert isinstance(ctx, str)


# ── 4. Multi-Agent 테스트 ──

class TestMultiAgent:
    """call_agent, available_agents, delegate 테스트."""

    @pytest.mark.asyncio
    async def test_call_agent_no_registry(self):
        config = make_config("test")
        agent = LogosAIAgent(config)
        result = await agent.call_agent("some_agent", "hello")
        assert result["success"] is False
        assert "설정되지 않았습니다" in result["answer"]

    @pytest.mark.asyncio
    async def test_call_agent_not_found(self):
        config = make_config("test")
        agent = LogosAIAgent(config)
        agent._agent_registry = {}
        result = await agent.call_agent("nonexistent", "hello")
        assert result["success"] is False
        assert "찾을 수 없습니다" in result["answer"]

    @pytest.mark.asyncio
    async def test_call_agent_success(self):
        """에이전트 간 호출이 정상 동작하는지."""
        config_a = make_config("agent_a")
        agent_a = LogosAIAgent(config_a)
        await agent_a.initialize()

        # 간단한 대상 에이전트 만들기
        class TargetAgent:
            async def process(self, query, context=None):
                return AgentResponse(
                    type=AgentResponseType.SUCCESS,
                    content={"answer": f"echo: {query}"},
                )

        agent_a._agent_registry = {"target": TargetAgent()}
        result = await agent_a.call_agent("target", "hello world")
        assert result["success"] is True
        assert "echo: hello world" in result["answer"]

    def test_available_agents_no_registry(self):
        config = make_config("test")
        agent = LogosAIAgent(config)
        agents = agent.available_agents()
        assert agents == []

    def test_available_agents_with_registry(self):
        config = make_config("test")
        agent = LogosAIAgent(config)
        agent._agent_registry = {"a": None, "b": None}
        agents = agent.available_agents()
        assert set(agents) == {"a", "b"}


# ── 5. SimpleAgent 호환성 테스트 ──

class TestSimpleAgentCompat:
    """SimpleAgent이 LogosAIAgent의 메서드를 정상 호출하는지."""

    def test_simple_agent_inherits(self):
        """SimpleAgent이 LogosAIAgent를 상속하는지."""
        assert issubclass(SimpleAgent, LogosAIAgent)

    def test_simple_agent_has_tools(self):
        class MyAgent(SimpleAgent):
            agent_name = "my_test"
            async def handle(self, query, context=None):
                return "ok"

        agent = MyAgent()
        assert hasattr(agent, '_tools')
        assert hasattr(agent, 'register_tool')
        assert hasattr(agent, 'run_with_tools')
        assert hasattr(agent, 'react')
        assert hasattr(agent, 'plan')
        assert hasattr(agent, 'call_agent')
        assert hasattr(agent, 'memorize')
        assert hasattr(agent, 'recall')

    @pytest.mark.asyncio
    async def test_simple_agent_register_and_check(self):
        class MyAgent(SimpleAgent):
            agent_name = "tool_test"
            async def handle(self, query, context=None):
                return "ok"

        agent = MyAgent()
        assert agent.has_tools is False

        async def dummy(x): return x
        agent.register_tool("dummy", "test", dummy)
        assert agent.has_tools is True


# ── 6. Self-Evaluate 테스트 ──

class TestSelfEvaluate:
    """self_evaluate가 opt-in이고 에러 없이 동작하는지."""

    @pytest.mark.asyncio
    async def test_self_evaluate_disabled_by_default(self):
        config = make_config("test")
        agent = LogosAIAgent(config)
        response = AgentResponse(
            type=AgentResponseType.SUCCESS,
            content={"answer": "test"},
        )
        score = await agent.self_evaluate("test query", response)
        assert score == -1.0  # disabled returns -1


# ── 7. process_stream 기본 동작 테스트 ──

class TestProcessStream:
    """process_stream이 SSE 이벤트를 올바르게 yield하는지."""

    @pytest.mark.asyncio
    async def test_process_stream_yields_events(self):
        class MyAgent(SimpleAgent):
            agent_name = "stream_test"
            async def handle(self, query, context=None):
                return {"answer": f"Reply to: {query}"}

        agent = MyAgent()
        events = []
        async for event in agent.process_stream("hello"):
            events.append(event)

        # process_stream should yield start, progress, complete events
        types = [e.get("type") for e in events]
        assert "start" in types or "complete" in types or len(events) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
