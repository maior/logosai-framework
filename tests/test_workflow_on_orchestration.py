"""구 `logosai.workflow` 실행이 새 엔진(`logosai.orchestration`) 위에서 돈다.

구 엔진은 의존 태스크의 `agent_query` 가 None 이면 그대로 실행기에 넘겨
순차 2단계가 실패했다(2026-10-04 실측: LLM 분해기가 task_2 의 agent_query 를
null 로 낸다 — "앞 결과를 쓰라"는 뜻이다). 실행부를 새 엔진에 맡기고, 결과
모양과 판정 규칙(acp_server 계약)은 그대로 둔다.
"""
import asyncio
import time

import pytest

from logosai.workflow.models import (
    DecompositionResult, ExecutionStrategy, QueryComplexity, TaskInfo,
)
from logosai.workflow.orchestrator import WorkflowEngine, WorkflowOrchestrator
from logosai.workflow.workflow_planner import WorkflowPlanner

STEP = 0.3


def _plan(tasks, strategy=ExecutionStrategy.SEQUENTIAL, query="원 질문"):
    decomposition = DecompositionResult(
        original_query=query, is_complex=True, complexity=QueryComplexity.MODERATE,
        complexity_score=0.8, tasks=tasks, suggested_strategy=strategy,
    )
    return WorkflowPlanner().create_plan(decomposition)


def _recorder(outputs, log, fail=(), raise_on=()):
    async def executor(agent_id, query, context):
        start = time.monotonic()
        await asyncio.sleep(STEP)
        tid = (context or {}).get("task_id")
        log.append({"agent": agent_id, "task_id": tid, "query": query,
                    "deps": dict((context or {}).get("dependency_results") or {}),
                    "start": start, "end": time.monotonic()})
        if tid in raise_on:
            raise RuntimeError(f"{tid} 폭발")
        if tid in fail:
            return {"success": False, "error": f"{tid} 실패"}
        return {"success": True, "result": outputs[tid]}
    return executor


async def test_sequential_second_task_with_null_query_runs():
    """구 엔진이 실패하던 바로 그 모양 — task_2.agent_query 가 None."""
    log = []
    plan = _plan([
        TaskInfo(task_id="task_1", agent_id="upper_agent", agent_query="hello world",
                 description="대문자로 바꾼다"),
        TaskInfo(task_id="task_2", agent_id="reverse_agent", agent_query=None,
                 description="그 결과를 뒤집는다", depends_on=["task_1"]),
    ])
    orch = WorkflowOrchestrator(agent_executor=_recorder(
        {"task_1": "HELLO WORLD", "task_2": "DLROW OLLEH"}, log))

    result = await orch.execute(plan)

    second = next(c for c in log if c["task_id"] == "task_2")
    assert isinstance(second["query"], str) and second["query"], "2단계가 빈 쿼리를 받았다"
    assert "HELLO WORLD" in second["query"], "앞 결과가 쿼리에 실리지 않았다"
    assert second["deps"] == {"task_1": "HELLO WORLD"}, "acp_server 계약 dependency_results 가 없다"
    assert result.success is True
    assert result.completed_tasks == 2 and result.total_tasks == 2
    assert [r.task_id for r in result.task_results] == ["task_1", "task_2"]


@pytest.mark.parametrize("agent_query,expected", [
    ({"text": "hello world"}, "hello world"),           # 값 하나짜리 dict → 그 값
    ({"text_upper": "hello world"}, "hello world"),      # 실측: 능력 이름을 키로 쓴다
    ({"a": "x", "b": "y"}, '{"a": "x", "b": "y"}'),     # 여러 값 → JSON (정보를 버리지 않는다)
    (["x", "y"], '["x", "y"]'),
    ("hello world", "hello world"),                      # 대조군 — 문자열은 그대로
])
async def test_non_string_agent_query_reaches_executor_as_text(agent_query, expected):
    """LLM 분해기는 agent_query 를 dict 로 낼 때가 있다 (2026-10-04 실측, 5회 중 2회).

    문자열로 시켜도 객체가 온다 — 정규화는 소비하는 쪽(실행 경계)에서 한다.
    정규화가 없으면 실행기가 dict 를 받아 `query.split` 에서 죽는다.
    """
    log = []
    plan = _plan([TaskInfo(task_id="task_1", agent_id="upper_agent", agent_query=agent_query)])
    orch = WorkflowOrchestrator(agent_executor=_recorder({"task_1": "OK"}, log))

    result = await orch.execute(plan)

    assert log[0]["query"] == expected
    assert result.success is True


async def test_same_agent_twice_in_one_level_maps_back_to_its_task():
    """같은 에이전트가 한 레벨에 두 번 — 결과가 자기 태스크로 돌아가야 한다."""
    log = []
    plan = _plan([
        TaskInfo(task_id="seoul", agent_id="weather_agent", agent_query="서울 날씨"),
        TaskInfo(task_id="busan", agent_id="weather_agent", agent_query="부산 날씨"),
    ], strategy=ExecutionStrategy.PARALLEL)
    orch = WorkflowOrchestrator(agent_executor=_recorder(
        {"seoul": "서울 21도", "busan": "부산 23도"}, log))

    result = await orch.execute(plan)

    by_task = {r.task_id: r for r in result.task_results}
    assert by_task["seoul"].result == "서울 21도" and by_task["busan"].result == "부산 23도"
    a, b = log
    assert b["start"] < a["end"] and a["start"] < b["end"], "같은 레벨이 순차로 돌았다"


async def test_failed_task_keeps_old_semantics():
    log = []
    plan = _plan([
        TaskInfo(task_id="task_1", agent_id="a_agent", agent_query="a"),
        TaskInfo(task_id="task_2", agent_id="b_agent", agent_query="b", depends_on=["task_1"]),
    ])
    orch = WorkflowOrchestrator(agent_executor=_recorder({"task_2": "B"}, log, fail={"task_1"}))

    result = await orch.execute(plan)

    by_task = {r.task_id: r for r in result.task_results}
    assert by_task["task_1"].success is False                # 실행기의 success=False 를 존중
    assert by_task["task_2"].success is True                 # 대조군
    assert next(c for c in log if c["task_id"] == "task_2")["deps"] == {}, \
        "실패한 의존 결과가 dependency_results 로 넘어갔다"
    assert result.success is False and result.failed_tasks == 1


async def test_executor_exception_becomes_a_failed_result():
    log = []
    plan = _plan([TaskInfo(task_id="task_1", agent_id="a_agent", agent_query="a", max_retries=0)])
    orch = WorkflowOrchestrator(agent_executor=_recorder({}, log, raise_on={"task_1"}))

    result = await orch.execute(plan)

    (only,) = result.task_results
    assert only.task_id == "task_1" and only.success is False and "폭발" in (only.error or "")
    assert result.success is False


async def test_engine_passes_task_id_only_when_the_plan_sets_it():
    """운영 플래너는 AgentTask.task_id 를 설정하지 않는다 — ACP 요청이 바뀌면 안 된다."""
    from logosai.orchestration import AgentTask, ExecutionEngine, ExecutionPlan, ExecutionStage

    seen = []

    async def executor(agent_id, query, context):
        seen.append(dict(context))
        return {"success": True, "result": "x"}

    plan = ExecutionPlan(query="q", workflow_strategy="sequential", stages=[
        ExecutionStage(stage_id=1, execution_type="sequential", agents=[
            AgentTask(agent_id="a_agent", sub_query="q"),
            AgentTask(agent_id="b_agent", sub_query="q", task_id="t-b"),
        ])])
    await ExecutionEngine(agent_executor=executor).execute(plan)

    assert "task_id" not in seen[0], "task_id 없는 운영 계획에 task_id 가 실렸다"
    assert seen[1].get("task_id") == "t-b"                    # 대조군


async def test_workflow_engine_process_runs_a_two_step_plan(monkeypatch):
    """WorkflowEngine.process 전체 경로 — LLM 만 고정하고 나머지는 실제.

    P4(2026-10-05)부터 계획은 플래너가 한다. 이전엔 분해기를 고정했다.
    """
    import json
    monkeypatch.setenv("LOGOSAI_ARTIFACT_GATE", "off")
    plan = json.dumps({"workflow_strategy": "sequential", "stages": [
        {"stage_id": 1, "execution_type": "sequential",
         "agents": [{"agent_id": "upper_agent", "sub_query": "hello world", "input_from": None}]},
        {"stage_id": 2, "execution_type": "sequential",
         "agents": [{"agent_id": "reverse_agent", "sub_query": "앞 결과를 뒤집기",
                     "input_from": ["stage_1"]}]}]})

    async def llm(prompt):
        if "두 가지만 판정하라" in prompt:
            return '{"unnecessary_agents": [], "broken_chain": false, "reason": "ok"}'
        return plan

    outputs = {"upper_agent": "HELLO WORLD", "reverse_agent": "DLROW OLLEH"}
    log = []

    async def executor(agent_id, query, context):
        log.append({"agent": agent_id, "query": query,
                    "deps": dict((context or {}).get("dependency_results") or {})})
        return {"success": True, "result": outputs[agent_id]}

    engine = WorkflowEngine(agent_executor=executor, llm=llm)
    result = await engine.process("hello world 를 대문자로 바꾼 다음, 그 결과를 뒤집어줘",
                                  [{"agent_id": "upper_agent"}, {"agent_id": "reverse_agent"}])

    assert result.total_tasks == 2 and result.completed_tasks == 2 and result.success is True
    assert [x["agent"] for x in log] == ["upper_agent", "reverse_agent"]
    assert "HELLO WORLD" in log[1]["query"]
