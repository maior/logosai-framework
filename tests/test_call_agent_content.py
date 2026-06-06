"""
call_agent content 보존 테스트 (TDD, Phase 0).

문제: MultiAgentMixin.call_agent 가 하위 에이전트의 AgentResponse.content 에서
`answer` 문자열만 추출하고 products/citations/breakdown/weights 등 구조화 데이터를
버린다(lossy). → 협업 오케스트레이터(recommendation_orchestrator)가 ranker 의
products[] 를 받지 못함.

수정: content(dict) 전체를 보존하되 success/agent_id/answer 하위호환 키 유지.
기존 소비자(auto_report: r["success"], restaurant_map: return r 통째)는 영향 없음.
"""

import asyncio

from logosai import SimpleAgent, AgentResponse


def _make_caller_with_target(target_response: AgentResponse):
    """target_response 를 반환하는 하위 에이전트를 registry 에 등록한 caller 생성."""

    class _Target(SimpleAgent):
        agent_name = "타깃"
        agent_description = "테스트용 하위 에이전트"

        async def handle(self, query, context=None):
            return target_response

    class _Caller(SimpleAgent):
        agent_name = "콜러"
        agent_description = "call_agent 테스트용 오케스트레이터"

        async def handle(self, query, context=None):
            return AgentResponse.success(content={})

    caller = _Caller()
    target = _Target()
    target.id = "ranker"
    caller._agent_registry = {"ranker": target}
    return caller


def test_call_agent_preserves_structured_content():
    """하위 에이전트 content 의 products/weights 등 구조화 키가 보존된다(non-lossy)."""
    resp = AgentResponse.success(
        content={"answer": "추천 완료", "products": [{"label": "A", "utility": 0.8}], "weights": {"breadth": 0.3}},
        message="추천 완료",
    )
    caller = _make_caller_with_target(resp)

    r = asyncio.run(caller.call_agent("ranker", "암보험 추천"))

    assert isinstance(r, dict)
    assert r["products"] == [{"label": "A", "utility": 0.8}], f"products 손실: {r}"
    assert r["weights"] == {"breadth": 0.3}, f"weights 손실: {r}"


def test_call_agent_backward_compat_answer_and_success():
    """기존 소비자 계약 유지: answer/success/agent_id 키가 항상 존재."""
    resp = AgentResponse.success(content={"answer": "hi", "products": []}, message="hi")
    caller = _make_caller_with_target(resp)

    r = asyncio.run(caller.call_agent("ranker", "q"))

    assert r["success"] is True, f"success 키 누락/변경: {r}"
    assert r["answer"] == "hi", f"answer 하위호환 깨짐: {r}"
    assert r["agent_id"] == "ranker", f"agent_id 누락: {r}"


def test_call_agent_non_dict_content_still_str():
    """content 가 dict 가 아니면 기존처럼 str 로 answer 채움(회귀 방지)."""
    resp = AgentResponse.success(message="plain")
    resp.content = "그냥 문자열"  # dict 아님
    caller = _make_caller_with_target(resp)

    r = asyncio.run(caller.call_agent("ranker", "q"))

    assert r["success"] is True
    assert r["answer"] == "그냥 문자열", f"non-dict content 처리 회귀: {r}"


def test_call_agent_content_cannot_override_success_false():
    """content 에 success 키가 있어도 call_agent 가 True 로 보장(명시 키 우선)."""
    resp = AgentResponse.success(content={"answer": "x", "success": False, "agent_id": "spoof"})
    caller = _make_caller_with_target(resp)

    r = asyncio.run(caller.call_agent("ranker", "q"))

    assert r["success"] is True, f"content.success 가 override 함: {r}"
    assert r["agent_id"] == "ranker", f"content.agent_id 가 override 함: {r}"


def test_call_agent_unknown_agent_returns_failure():
    """없는 에이전트 호출 시 success=False (기존 동작 유지)."""
    caller = _make_caller_with_target(AgentResponse.success(content={}))

    r = asyncio.run(caller.call_agent("nope", "q"))

    assert r["success"] is False
    assert "answer" in r
