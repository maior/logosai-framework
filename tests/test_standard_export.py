"""StandardExportMixin 테스트 — 에이전트 → MCP tool / A2A skill 파생.

Usage: python tests/test_standard_export.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logosai.agent import LogosAIAgent
from logosai.config import AgentConfig


class _BareAgent(LogosAIAgent):
    """도구 없는 최소 에이전트 — 자연어 query-only."""
    async def process(self, query, context=None):
        return None


class _ToolAgent(LogosAIAgent):
    """도구 2개를 등록한 에이전트."""
    async def process(self, query, context=None):
        return None


def _bare():
    return _BareAgent(AgentConfig(name="요약 에이전트", agent_type="custom",
                                  description="텍스트를 요약합니다."))


def _with_tools():
    agent = _ToolAgent(AgentConfig(name="계산 에이전트", agent_type="custom",
                                   description="사칙연산을 수행합니다.",
                                   config={"tags": ["math", "calc"]}))
    agent.register_tool("add", "두 수를 더한다", lambda a, b: a + b,
                        parameters={"a": {"type": "number", "description": "첫 수"},
                                    "b": {"type": "number", "description": "둘째 수"}})
    agent.register_tool("negate", "부호를 뒤집는다", lambda x: -x,
                        parameters={"x": {"type": "number", "description": "값", "required": True}})
    return agent


def test_bare_agent_to_mcp_tool_is_query_only():
    tool = _bare().to_mcp_tool()
    assert tool["name"] == "요약_에이전트" or tool["name"].startswith("_") is False
    # 한글 이름은 MCP 규칙 위반 → sanitize (공백→_, 비허용문자 제거)
    import re
    assert re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", tool["name"]), f"MCP 이름 규칙 위반: {tool['name']}"
    assert "요약" in tool["description"]
    schema = tool["inputSchema"]
    assert schema["type"] == "object"
    assert list(schema["properties"].keys()) == ["query"]
    assert schema["required"] == ["query"]


def test_tool_agent_to_mcp_tool_promotes_parameters():
    tool = _with_tools().to_mcp_tool()
    props = tool["inputSchema"]["properties"]
    # 등록 도구 파라미터가 inputSchema로 승격 (query는 항상 유지)
    assert "query" in props
    assert props["a"]["type"] == "number"
    assert props["b"]["description"] == "둘째 수"
    # required=True 인 파라미터는 required 배열로 승격
    assert "x" in tool["inputSchema"]["required"]


def test_to_a2a_skill_shape_and_tags():
    skill = _with_tools().to_a2a_skill()
    assert skill["id"]
    assert skill["name"] == "계산 에이전트"
    assert "사칙연산" in skill["description"]
    # tags = config tags + 도구 이름
    assert "math" in skill["tags"] and "add" in skill["tags"] and "negate" in skill["tags"]
    assert skill["inputModes"] == ["text/plain"]
    assert "application/json" in skill["outputModes"]


def test_bare_agent_skill_has_empty_tags_not_crash():
    skill = _bare().to_a2a_skill()
    assert skill["tags"] == []
    assert skill["name"] == "요약 에이전트"


def test_mcp_tool_excludes_llm_config_keys():
    agent = _BareAgent(AgentConfig(name="x", agent_type="custom", description="d"))
    agent.register_tool("gen", "생성", lambda: None,
                        parameters={"model": {"type": "string"},
                                    "temperature": {"type": "number"},
                                    "topic": {"type": "string", "description": "주제"}})
    props = agent.to_mcp_tool()["inputSchema"]["properties"]
    assert "topic" in props
    for k in ("model", "temperature"):
        assert k not in props, f"LLM 설정 키 {k}는 제외되어야 함"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"PASS: {len(fns)} standard_export tests")
