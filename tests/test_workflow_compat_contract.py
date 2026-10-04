"""`logosai.workflow.WorkflowEngine` 호환 계약 — acp_server 가 쓰는 모양.

소비자: acp_server/acp_modules/agent_selection.py (초기화),
request_handlers.py · websocket_handlers.py (`process` 호출).
그쪽은 `total_tasks == 0` 이면 워크플로우를 버리고 자기 단일 에이전트 경로로
간다. 따라서 "단순 쿼리는 실행 0건" 은 결함이 아니라 계약이다.

오케스트레이터 통합 후 이 클래스가 새 엔진 위의 래퍼가 되더라도
아래가 그대로여야 acp_server 를 고치지 않아도 된다.
"""
import inspect

import pytest

from logosai.workflow import WorkflowEngine

AGENTS = [
    {"agent_id": "upper_agent", "name": "u", "description": "텍스트를 대문자로 바꾼다"},
    {"agent_id": "count_agent", "name": "c", "description": "글자 수를 센다"},
]

#: acp_server 핸들러가 결과에서 읽는 필드와 그 타입
RESULT_FIELDS = {
    "success": bool,
    "plan_id": str,
    "total_tasks": int,
    "completed_tasks": int,
    "task_results": list,
}


def test_constructor_and_method_shapes():
    inspect.signature(WorkflowEngine).bind(agent_executor=lambda *a: None)
    assert inspect.iscoroutinefunction(WorkflowEngine.initialize)
    assert inspect.iscoroutinefunction(WorkflowEngine.process)
    # request_handlers.py:329 의 호출 모양 그대로
    inspect.signature(WorkflowEngine.process).bind(
        object(), "query", AGENTS, context={"raw_query": "query"}
    )


async def test_simple_query_yields_zero_tasks_so_host_falls_back():
    calls = []

    async def executor(agent_id, query, context):
        calls.append(agent_id)
        return {"success": True, "result": {"answer": "x"}}

    async def llm(prompt):          # 플래너가 에이전트 하나로 충분하다고 판단 (결정적)
        if "두 가지만 판정하라" in prompt:
            return '{"unnecessary_agents": [], "broken_chain": false, "reason": "ok"}'
        return ('{"workflow_strategy": "sequential", "stages": [{"stage_id": 1, '
                '"execution_type": "sequential", "agents": [{"agent_id": "count_agent", '
                '"sub_query": "1+1", "input_from": null}]}]}')

    engine = WorkflowEngine(agent_executor=executor, llm=llm)
    result = await engine.process("1+1", AGENTS, context={"raw_query": "1+1"})

    assert result.total_tasks == 0, "단순 쿼리가 워크플로우로 잡히면 acp_server 단일 경로가 막힌다"
    assert calls == [], "단순 쿼리에서 에이전트를 직접 실행하면 호스트와 이중 실행된다"
    _assert_result_shape(result)


def _assert_result_shape(result):
    for field, typ in RESULT_FIELDS.items():
        assert isinstance(getattr(result, field, None), typ), f"{field} 가 {typ.__name__} 가 아니다"
    assert hasattr(result, "final_result"), "final_result 가 없다"


def test_shape_check_rejects_an_empty_result():
    """대조군 — 모양 검사가 필드 없는 객체를 통과시키면 위 테스트는 공허하다."""
    with pytest.raises(AssertionError):
        _assert_result_shape(object())
