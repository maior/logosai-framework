"""agentic/core.py act() 실제 실행 연결 테스트.

수정 전: act()가 LLM에게 "Simulate the execution" 요청 (상상)
수정 후: act()가 tool_executor 콜백으로 실제 도구 실행

테스트 시나리오:
1. tool_executor 없이 — 기존 LLM 시뮬레이션 동작 유지
2. tool_executor 있고 + Action.requires_tool=True — 실제 도구 실행
3. tool_executor 있고 + Action.requires_tool=False — LLM 생성 (비도구 행동)
4. tool_executor 실패 시 — 에러 처리 + fallback
5. execute_cycle() 전체 사이클 — 실제 도구 실행 포함
6. agent.py와 연결 — _init_agentic_features에서 tool_executor 주입 확인
"""

import asyncio
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from logosai.agentic.core import AgenticCore, Action, AgenticState


# ── Mock LLM Client ──

class MockLLMResponse:
    def __init__(self, content):
        self.content = content


class MockLLMClient:
    """LLM 호출 없이 테스트하기 위한 Mock."""

    def __init__(self):
        self.call_count = 0
        self.last_prompt = ""

    async def invoke(self, prompt):
        self.call_count += 1
        self.last_prompt = prompt

        # think() 응답
        if "Analyze the following query" in prompt:
            return MockLLMResponse('{"understanding": "test query", "key_concepts": ["test"], "context_analysis": {}, "confidence": 0.9}')

        # plan() 응답 — requires_tool=True인 action 포함
        if "Create an action plan" in prompt:
            return MockLLMResponse('''{
                "strategy": "Use calculator",
                "actions": [
                    {"name": "calculate", "description": "Calculate 2+3", "priority": 0, "requires_tool": true, "tool_name": "calculator", "parameters": {"expression": "2+3"}, "expected_outcome": "5"}
                ],
                "success_criteria": ["correct answer"],
                "estimated_time": 1
            }''')

        # reflect() 응답
        if "Reflect on the following" in prompt:
            return MockLLMResponse('{"outcome": "success", "success": true, "lessons_learned": ["tool works"], "improvements": [], "confidence_adjustment": 0.1, "next_steps": []}')

        # act() 시뮬레이션 fallback 응답
        if "Simulate the execution" in prompt:
            return MockLLMResponse('{"success": true, "result": "SIMULATED result", "output": {}, "issues": []}')

        # 기타
        return MockLLMResponse('{"result": "ok"}')


# ── 테스트 1: tool_executor 없이 — 기존 시뮬레이션 동작 유지 ──

class TestActWithoutExecutor:
    """tool_executor를 넘기지 않으면 기존 LLM 시뮬레이션이 동작해야 함."""

    @pytest.mark.asyncio
    async def test_act_simulates_without_executor(self):
        llm = MockLLMClient()
        core = AgenticCore(llm_client=llm, agent_name="test")

        action = Action(
            name="search",
            description="Search the web",
            requires_tool=True,
            tool_name="web_search",
        )
        result = await core.act(action)

        assert result["success"] is True
        assert "SIMULATED" in result["result"]
        # LLM이 "Simulate" 프롬프트를 받았는지 확인
        assert "Simulate" in llm.last_prompt


# ── 테스트 2: tool_executor + requires_tool=True → 실제 실행 ──

class TestActWithExecutor:
    """tool_executor가 있고 requires_tool=True면 실제 도구를 실행해야 함."""

    @pytest.mark.asyncio
    async def test_act_executes_real_tool(self):
        llm = MockLLMClient()

        # 실제 도구 실행 기록
        executed = []

        async def mock_tool_executor(tool_name, parameters):
            executed.append({"tool": tool_name, "params": parameters})
            if tool_name == "calculator":
                expr = parameters.get("expression", "0")
                return str(eval(expr))
            return "unknown tool"

        core = AgenticCore(llm_client=llm, agent_name="test", tool_executor=mock_tool_executor)

        action = Action(
            name="calculate",
            description="Calculate 2+3",
            requires_tool=True,
            tool_name="calculator",
            parameters={"expression": "2+3"},
        )
        result = await core.act(action)

        # 실제 실행됨
        assert len(executed) == 1
        assert executed[0]["tool"] == "calculator"
        assert result["success"] is True
        assert "5" in result["result"]
        # LLM "Simulate" 프롬프트가 호출되지 않아야 함
        assert "Simulate" not in llm.last_prompt or llm.call_count == 0


# ── 테스트 3: requires_tool=False → LLM 생성 (비도구 행동) ──

class TestActNonToolAction:
    """requires_tool=False면 tool_executor가 있어도 LLM으로 처리해야 함."""

    @pytest.mark.asyncio
    async def test_act_uses_llm_for_non_tool_action(self):
        llm = MockLLMClient()
        executed = []

        async def mock_executor(tool_name, parameters):
            executed.append(tool_name)
            return "should not be called"

        core = AgenticCore(llm_client=llm, agent_name="test", tool_executor=mock_executor)

        action = Action(
            name="summarize",
            description="Summarize the results",
            requires_tool=False,  # 도구 불필요
        )
        result = await core.act(action)

        assert result["success"] is True
        assert len(executed) == 0  # executor 호출 안 됨


# ── 테스트 4: tool_executor 실패 시 에러 처리 ──

class TestActExecutorFailure:
    """tool_executor가 에러를 발생시키면 graceful하게 처리해야 함."""

    @pytest.mark.asyncio
    async def test_act_handles_executor_error(self):
        llm = MockLLMClient()

        async def failing_executor(tool_name, parameters):
            raise RuntimeError("DB connection failed")

        core = AgenticCore(llm_client=llm, agent_name="test", tool_executor=failing_executor)

        action = Action(
            name="db_query",
            description="Query database",
            requires_tool=True,
            tool_name="database",
        )
        result = await core.act(action)

        assert result["success"] is False
        assert "DB connection failed" in result["result"] or "Error" in result["result"]


# ── 테스트 5: execute_cycle 전체 사이클 — 실제 도구 포함 ──

class TestExecuteCycleWithTools:
    """전체 TPAR 사이클에서 act()가 실제 도구를 실행하는지."""

    @pytest.mark.asyncio
    async def test_full_cycle_uses_real_tools(self):
        llm = MockLLMClient()
        executed = []

        async def mock_executor(tool_name, parameters):
            executed.append(tool_name)
            return "42"

        core = AgenticCore(llm_client=llm, agent_name="test", tool_executor=mock_executor)
        result = await core.execute_cycle("2+3을 계산해줘")

        # 전체 사이클 완료
        assert result["success"] is True
        assert result["thought"]["confidence"] == 0.9
        assert len(result["plan"]["actions"]) >= 1

        # 실제 도구 실행됨
        assert len(executed) > 0
        assert "calculator" in executed

        # 이력 추적
        assert len(core.thought_history) == 1
        assert len(core.action_history) >= 1
        assert len(core.reflection_history) == 1


# ── 테스트 6: 상태 전이 확인 ──

class TestStateTransitions:
    """TPAR 사이클 중 상태가 올바르게 전이되는지."""

    @pytest.mark.asyncio
    async def test_state_returns_to_idle(self):
        llm = MockLLMClient()
        core = AgenticCore(llm_client=llm, agent_name="test")

        assert core.state == AgenticState.IDLE

        await core.think("test")
        assert core.state == AgenticState.IDLE

        action = Action(name="test", description="test")
        await core.act(action)
        assert core.state == AgenticState.IDLE

    @pytest.mark.asyncio
    async def test_history_tracking(self):
        llm = MockLLMClient()
        core = AgenticCore(llm_client=llm, agent_name="test")

        await core.think("query1")
        await core.think("query2")
        assert len(core.thought_history) == 2

        core.reset()
        assert len(core.thought_history) == 0
        assert core.current_confidence == 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
