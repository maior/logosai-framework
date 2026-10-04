"""실행기가 AgentResponse 를 돌려줘도 dict 를 돌려준 것과 똑같이 다음 단계로 넘긴다.

발견 (2026-10-05, LLM 가이드 예제를 실제 LLM 으로 돌리다): 엔진의 핵심 결과 추출이
문자열·숫자·dict·list 만 알고 나머지 객체는 str() 로 떨어뜨려, 다음 단계 쿼리에
"<AgentResponse object at 0x...>" 가 실렸다. 그래서 SDK 자신의
AgentResponse 를 돌려주면 — `return await agent.process(...)`, 가장 자연스러운 실행기 —
단계 간 데이터가 조용히 끊겼다(요약 에이전트가 "텍스트를 붙여넣어 주세요"라고 답했다).
logos_api 는 ACP JSON 을 dict 로 넘겨 운영에선 드러나지 않았다.

대칭이 기준이다: 같은 내용을 dict 로 주든 AgentResponse 로 주든 다음 쿼리가 같은 것을 담는다.
실패도 마찬가지 — 돌려준 실패는 하류로 넘긴다(3-2 결정: 하류가 실패를 알아야 지어내지 않는다).
"""
import json

import pytest

from logosai import AgentResponse
from logosai.orchestration import (
    AgentRegistry, AgentRegistryEntry, AgentSchema, WorkflowOrchestrator,
)


def _registry():
    reg = AgentRegistry()
    for aid in ("first_agent", "second_agent"):
        reg.register_agent(AgentRegistryEntry(
            agent_id=aid, name=aid, description=aid, capabilities=[], tags=[],
            schema=AgentSchema(input_type="query", output_type="text")))
    return reg


def _llm(input_from):
    plan = json.dumps({"workflow_strategy": "sequential", "stages": [
        {"stage_id": 1, "execution_type": "sequential",
         "agents": [{"agent_id": "first_agent", "sub_query": "첫 일", "input_from": None}]},
        {"stage_id": 2, "execution_type": "sequential",
         "agents": [{"agent_id": "second_agent", "sub_query": "둘째 일", "input_from": input_from}]}]})

    async def invoke(prompt):
        if "두 가지만 판정하라" in prompt:
            return '{"unnecessary_agents": [], "broken_chain": false, "reason": "ok"}'
        return plan
    return invoke


FIRST = {
    "dict ok": {"success": True, "result": {"answer": "서울 21°C"}},
    "AgentResponse ok": AgentResponse.success(content={"answer": "서울 21°C"}),
    "dict fail": {"success": False, "error": "데이터 없음"},
    "AgentResponse fail": AgentResponse.error("데이터 없음"),
}


async def _second_query(first_result, input_from=("stage_1",)):
    seen = {}

    async def executor(agent_id, query, context):
        if agent_id == "first_agent":
            return first_result
        seen["query"] = query
        return {"success": True, "result": "ok"}

    await WorkflowOrchestrator(agent_executor=executor, registry=_registry(),
                               llm_invoke=_llm(list(input_from) if input_from else None)).run("x")
    return seen["query"]


@pytest.fixture(autouse=True)
def _gate_off(monkeypatch):
    monkeypatch.setenv("LOGOSAI_ARTIFACT_GATE", "off")


@pytest.mark.parametrize("kind", ["ok", "fail"])
async def test_agent_response_hands_off_like_a_dict(kind):
    from_dict = await _second_query(FIRST[f"dict {kind}"])
    from_response = await _second_query(FIRST[f"AgentResponse {kind}"])
    needle = "21°C" if kind == "ok" else "데이터 없음"
    assert needle in from_dict                               # 대조군 — dict 는 원래 넘어갔다
    assert needle in from_response, f"AgentResponse 결과가 다음 단계로 안 넘어갔다:\n{from_response}"


async def test_no_input_from_means_no_handoff_for_either_shape():
    """대조군 — 계획이 입력을 이어 주지 않으면 둘 다 넘기지 않는다 (추출만 고친 것)."""
    for first in (FIRST["dict ok"], FIRST["AgentResponse ok"]):
        assert "21°C" not in await _second_query(first, input_from=None)


async def test_empty_agent_response_does_not_leak_an_empty_shell():
    """내용 없는 성공 응답이 "{}" 같은 빈 껍데기 문자열로 새지 않는다."""
    query = await _second_query(AgentResponse.success(content={}))
    assert "{}" not in query
