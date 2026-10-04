"""구 logosai.workflow.WorkflowEngine 이 새 계획기(logosai.orchestration.planner) 위에서 돈다 (P4).

이전: QueryDecomposer 가 길이 20자 미만·키워드("그리고", "하고", "해줘" 개수)로 단순
쿼리를 먼저 거르고(하드코딩 라우팅), 나머지를 자기 LLM 프롬프트로 분해했다 —
SDK 안에 계획기가 두 벌이었다. 이제 판단은 플래너(LLM) 하나가 한다.

지키는 계약 (acp_server request_handlers·agent_selection):
  · process(query, available_agents, context) → WorkflowResult
  · 단순(에이전트 1개 이하)·gap·계획 실패 → total_tasks == 0, 실행 0건 (호스트가 단일 경로로)
  · 다음 단계 실행기는 context["dependency_results"] 로 앞 결과를 받는다
"""
import json

import pytest

from logosai.workflow import WorkflowEngine

AGENTS = [
    {"agent_id": "search_agent", "name": "검색", "description": "웹을 검색한다", "capabilities": ["search"]},
    {"agent_id": "excel_agent", "name": "엑셀", "description": "표를 엑셀로 만든다", "capabilities": []},
    {"agent_id": "weather_agent", "name": "날씨", "description": "날씨를 조회한다"},   # capabilities 없음
]
CRITIQUE_OK = '{"unnecessary_agents": [], "broken_chain": false, "reason": "ok"}'


def _plan(*stages, gap=None):
    return json.dumps({"workflow_strategy": "hybrid", "capability_gap": gap, "stages": [
        {"stage_id": i, "execution_type": kind,
         "agents": [{"agent_id": a, "sub_query": f"{a} 할 일", "input_from": inp} for a in agents]}
        for i, (kind, agents, inp) in enumerate(stages, 1)]}, ensure_ascii=False)


class FakeLLM:
    """LLMClient 모양 (async invoke(prompt) → .content)."""

    def __init__(self, plan):
        self.plan, self.prompts = plan, []

    async def invoke(self, prompt, **_):
        self.prompts.append(prompt)
        text = CRITIQUE_OK if "두 가지만 판정하라" in prompt else self.plan
        return type("Resp", (), {"content": text})()


def _recorder(log):
    async def executor(agent_id, query, context):
        log.append({"agent": agent_id, "query": query, "deps": (context or {}).get("dependency_results")})
        return {"success": True, "result": {"answer": f"{agent_id} 결과"}}
    return executor


@pytest.fixture(autouse=True)
def _gate_off(monkeypatch):
    monkeypatch.setenv("LOGOSAI_ARTIFACT_GATE", "off")


async def test_single_agent_plan_falls_back_to_host():
    log, llm = [], FakeLLM(_plan(("sequential", ["weather_agent"], None)))
    result = await WorkflowEngine(agent_executor=_recorder(log), llm=llm).process(
        "서울 날씨", AGENTS, context={"raw_query": "서울 날씨"})
    assert result.total_tasks == 0 and log == []
    assert llm.prompts and "weather_agent" in llm.prompts[0]     # 대조군 — 플래너가 실제로 판단했다


async def test_two_stage_plan_runs_in_order_with_dependency_results():
    log = []
    llm = FakeLLM(_plan(("sequential", ["search_agent"], None),
                        ("sequential", ["excel_agent"], ["stage_1"])))
    result = await WorkflowEngine(agent_executor=_recorder(log), llm=llm).process(
        "검색해서 엑셀로", AGENTS, context={"raw_query": "검색해서 엑셀로"})

    assert [x["agent"] for x in log] == ["search_agent", "excel_agent"]
    assert result.total_tasks == 2 and result.completed_tasks == 2 and result.success
    assert log[0]["deps"] in (None, {}, [])
    assert log[1]["deps"], "다음 단계가 앞 결과를 못 받았다 (acp_server 는 dependency_results 를 읽는다)"
    assert [r.agent_id for r in result.task_results] == ["search_agent", "excel_agent"]


async def test_parallel_stage_becomes_one_level():
    log = []
    llm = FakeLLM(_plan(("parallel", ["search_agent", "weather_agent"], None),
                        ("sequential", ["excel_agent"], ["stage_1"])))
    engine = WorkflowEngine(agent_executor=_recorder(log), llm=llm)
    analysis = await engine.analyze_query("둘 다 하고 엑셀로", AGENTS)
    order = analysis["plan"]["execution_order"]
    assert len(order) == 2 and len(order[0]) == 2 and len(order[1]) == 1


@pytest.mark.parametrize("reply", [
    _plan(gap={"detected": True, "missing_capabilities": ["x"], "reason": "없음"}),
    "JSON 이 아니다",
])
async def test_gap_or_planning_failure_falls_back_without_raising(reply):
    log = []
    result = await WorkflowEngine(agent_executor=_recorder(log), llm=FakeLLM(reply)).process(
        "무언가", AGENTS, context={})
    assert result.total_tasks == 0 and log == []


async def test_short_queries_are_judged_by_the_planner_not_by_length():
    """구 분해기는 20자 미만이면 LLM 없이 '단순'으로 버렸다 — 이제 플래너가 판단한다."""
    log = []
    llm = FakeLLM(_plan(("sequential", ["search_agent"], None),
                        ("sequential", ["excel_agent"], ["stage_1"])))
    result = await WorkflowEngine(agent_executor=_recorder(log), llm=llm).process("검색→엑셀", AGENTS)
    assert llm.prompts and result.total_tasks == 2


async def test_available_agents_do_not_leak_into_the_global_registry():
    from logosai.orchestration import get_registry
    before = set(get_registry().get_agent_ids())
    await WorkflowEngine(agent_executor=_recorder([]), llm=FakeLLM(
        _plan(("sequential", ["search_agent"], None)))).process("x", AGENTS)
    assert set(get_registry().get_agent_ids()) == before


async def test_analyze_query_keeps_its_keys():
    engine = WorkflowEngine(agent_executor=_recorder([]), llm=FakeLLM(
        _plan(("sequential", ["search_agent"], None))))
    out = await engine.analyze_query("x", AGENTS)
    assert set(out) == {"decomposition", "plan"} and out["plan"] is None
    assert out["decomposition"]["is_complex"] is False


def test_engine_no_longer_carries_the_keyword_decomposer():
    engine = WorkflowEngine(agent_executor=_recorder([]))
    assert not hasattr(engine, "decomposer")
