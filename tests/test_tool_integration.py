"""도구 시스템 통합 테스트.

수정 전: agentic/tools.py의 Tool/ToolRegistry가 별도로 존재하지만 사용 안 됨
수정 후: mixins/tool_use.py에서 Tool dataclass를 사용하고, @tool_decorator 지원

테스트 시나리오:
1. 기존 register_tool(name, desc, func, params) API 호환
2. Tool dataclass로도 등록 가능
3. @tool_decorator로 등록 가능
4. 파라미터 검증 동작
5. has_tools, tool_metrics 기존 동작 유지
6. SimpleAgent에서도 동작
"""

import asyncio
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from logosai.agentic.tools import Tool, ToolParameter, ToolCategory, ToolResult, tool_decorator
from logosai.simple_agent import SimpleAgent


# ── 1. 기존 API 호환 ──

class TestLegacyAPI:
    """기존 register_tool(name, desc, func, params) 방식이 그대로 동작해야 함."""

    def test_register_with_strings(self):
        class MyAgent(SimpleAgent):
            agent_name = "test"
            async def handle(self, query, context=None):
                return "ok"

        agent = MyAgent()
        async def calc(expression): return eval(expression)

        agent.register_tool("calc", "계산기", calc, {"expression": {"type": "string"}})
        assert agent.has_tools is True
        assert len(agent._tools) == 1
        assert agent._tools[0]["name"] == "calc"
        assert "calc" in agent._tool_executors

    def test_register_replaces_existing(self):
        class MyAgent(SimpleAgent):
            agent_name = "test"
            async def handle(self, query, context=None):
                return "ok"

        agent = MyAgent()
        async def v1(x): return "v1"
        async def v2(x): return "v2"

        agent.register_tool("tool", "V1", v1)
        agent.register_tool("tool", "V2", v2)
        assert len(agent._tools) == 1
        assert agent._tools[0]["description"] == "V2"


# ── 2. Tool dataclass로 등록 ──

class TestToolDataclass:
    """Tool 객체를 직접 만들어서 등록할 수 있어야 함."""

    def test_register_tool_object(self):
        class MyAgent(SimpleAgent):
            agent_name = "test"
            async def handle(self, query, context=None):
                return "ok"

        agent = MyAgent()

        async def search(query: str) -> str:
            return f"results for {query}"

        tool = Tool(
            name="search",
            description="웹 검색",
            category=ToolCategory.WEB_ACCESS,
            function=search,
            parameters=[ToolParameter("query", "str", "검색어")],
        )
        agent.register_tool_object(tool)

        assert agent.has_tools is True
        assert agent._tools[0]["name"] == "search"
        assert "search" in agent._tool_executors

    def test_tool_preserves_metadata(self):
        """Tool 객체의 category, parameters 정보가 보존되어야 함."""
        class MyAgent(SimpleAgent):
            agent_name = "test"
            async def handle(self, query, context=None):
                return "ok"

        agent = MyAgent()

        tool = Tool(
            name="db_query",
            description="DB 조회",
            category=ToolCategory.DATABASE,
            function=lambda sql: "result",
            parameters=[ToolParameter("sql", "str", "SQL 쿼리", required=True)],
        )
        agent.register_tool_object(tool)

        registered = agent._tools[0]
        assert registered["name"] == "db_query"
        assert registered["category"] == "database"
        assert registered["parameters"]["sql"]["type"] == "str"
        assert registered["parameters"]["sql"]["required"] is True


# ── 3. @tool_decorator로 등록 ──

class TestToolDecorator:
    """@tool_decorator로 만든 Tool 객체를 등록할 수 있어야 함."""

    def test_decorator_creates_tool(self):
        @tool_decorator("my_tool", "테스트 도구", ToolCategory.CUSTOM)
        async def my_function(param1: str, param2: int = 10) -> str:
            return f"{param1}-{param2}"

        assert isinstance(my_function, Tool)
        assert my_function.name == "my_tool"
        assert len(my_function.parameters) == 2

    def test_register_decorated_tool(self):
        class MyAgent(SimpleAgent):
            agent_name = "test"
            async def handle(self, query, context=None):
                return "ok"

        agent = MyAgent()

        @tool_decorator("formatter", "텍스트 포맷팅", ToolCategory.TEXT_ANALYSIS)
        async def format_text(text: str, style: str = "bold") -> str:
            return f"<{style}>{text}</{style}>"

        agent.register_tool_object(format_text)
        assert agent.has_tools is True
        assert agent._tools[0]["name"] == "formatter"


# ── 4. 파라미터 검증 ──

class TestParameterValidation:
    """Tool.execute()에서 필수 파라미터 누락 시 에러를 반환해야 함."""

    @pytest.mark.asyncio
    async def test_missing_required_param(self):
        async def search(query: str) -> str:
            return f"results for {query}"

        tool = Tool(
            name="search",
            description="검색",
            category=ToolCategory.WEB_ACCESS,
            function=search,
            parameters=[ToolParameter("query", "str", "검색어", required=True)],
        )
        result = await tool.execute()  # query 누락
        assert result.success is False
        assert "Required parameter" in result.error

    @pytest.mark.asyncio
    async def test_default_param_used(self):
        async def greet(name: str, greeting: str = "Hello") -> str:
            return f"{greeting}, {name}!"

        tool = Tool(
            name="greet",
            description="인사",
            category=ToolCategory.CUSTOM,
            function=greet,
            parameters=[
                ToolParameter("name", "str", "이름", required=True),
                ToolParameter("greeting", "str", "인사말", required=False, default="Hello"),
            ],
        )
        result = await tool.execute(name="World")
        assert result.success is True
        assert result.result == "Hello, World!"


# ── 5. tool_metrics 기존 동작 유지 ──

class TestMetricsCompat:
    """tool_metrics 속성이 기존대로 동작해야 함."""

    def test_metrics_empty_initial(self):
        class MyAgent(SimpleAgent):
            agent_name = "test"
            async def handle(self, query, context=None):
                return "ok"

        agent = MyAgent()
        assert agent.tool_metrics == {}

    def test_has_tools_false_initially(self):
        class MyAgent(SimpleAgent):
            agent_name = "test"
            async def handle(self, query, context=None):
                return "ok"

        agent = MyAgent()
        assert agent.has_tools is False


# ── 6. 기존 19개 테스트 깨지지 않는지 (import 확인) ──

class TestBackwardsCompat:
    """기존 테스트가 영향받지 않는지 import 레벨 확인."""

    def test_import_tool_classes(self):
        from logosai.agentic.tools import Tool, ToolParameter, ToolCategory, ToolResult, tool_decorator
        assert Tool is not None
        assert ToolParameter is not None

    def test_mixin_still_works(self):
        from logosai.mixins.tool_use import ToolUseMixin
        assert hasattr(ToolUseMixin, 'register_tool')
        assert hasattr(ToolUseMixin, 'run_with_tools')
        assert hasattr(ToolUseMixin, 'has_tools')


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
