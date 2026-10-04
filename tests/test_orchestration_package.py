"""`logosai.orchestration` — 워크플로 실행부의 정본.

ontology/orchestrator 에서 옮겨 왔다(2026-10-04, orchestrator-unify). 그 전에는
SDK 에 엔진이 따로 있었고(logosai.workflow), 운영에서 고친 핸드오프가 SDK 로
건너오지 않아 순차 2단계가 `agent_query=None` 으로 실패했다. 정본을 하나로
만든 이유다.

이 패키지는 SDK 가 자기 테스트를 소유한다 — ontology 없이 선다.
"""
import asyncio
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

EXPORTED = [
    # models
    "AgentSchema", "AgentRegistryEntry", "AgentTask", "ExecutionStage", "ExecutionPlan",
    "AgentResult", "StageResult", "WorkflowResult", "ProgressEvent", "ProgressEventType",
    "AgentStatus",
    # exceptions
    "OrchestratorError", "PlanValidationError", "ExecutionError", "TransformationError",
    "AgentNotFoundError", "CircularDependencyError", "SchemaCompatibilityError",
    # components
    "AgentRegistry", "get_registry", "ProgressStreamer", "PlanValidator",
    "DataTransformer", "ExecutionEngine", "ResultAggregator",
]


@pytest.mark.parametrize("name", EXPORTED)
def test_public_names(name):
    import logosai.orchestration as orch
    assert hasattr(orch, name), f"logosai.orchestration.{name} 이 없다"
    assert name in orch.__all__


def test_does_not_pull_ontology():
    """SDK 는 ontology 에 의존하지 않는다 — 방향이 반대면 SDK 가 무거워진다."""
    code = (
        "import sys, logosai.orchestration as o, logosai.orchestration.execution_engine; "
        "bad=[m for m in sys.modules if m == 'ontology' or m.startswith('ontology.')]; "
        "print('BAD' if bad else 'OK', bad[:5])"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert out.stdout.startswith("OK"), out.stdout + out.stderr[-500:]
    # 대조군 — 검사가 실제로 sys.modules 를 보고 있다
    assert "logosai.orchestration" in subprocess.run(
        [sys.executable, "-c", "import sys, logosai.orchestration; print(list(sys.modules))"],
        cwd=ROOT, capture_output=True, text=True).stdout


# ── 실행 엔진 행동 — SDK 경로로 직접 검증 ─────────────────────────────

STEP = 0.3


def _executor(outputs, log):
    async def run(agent_id, sub_query, context):
        start = time.monotonic()
        await asyncio.sleep(STEP)
        log[agent_id] = {"start": start, "end": time.monotonic(),
                         "query": sub_query, "context": dict(context or {})}
        return {"success": True, "result": {"answer": outputs[agent_id]}}
    return run


def _plan(query, stages):
    from logosai.orchestration import AgentTask, ExecutionPlan, ExecutionStage

    built = [
        ExecutionStage(stage_id=i, execution_type=kind,
                       agents=[AgentTask(agent_id=a, sub_query=q) for a, q in tasks],
                       depends_on=[i - 1] if i > 1 else None)
        for i, (kind, tasks) in enumerate(stages, 1)
    ]
    return ExecutionPlan(query=query, workflow_strategy="hybrid", stages=built)


async def test_parallel_stage_then_handoff():
    from logosai.orchestration import ExecutionEngine

    log = {}
    out = {"a_agent": "A-OUT-11", "b_agent": "B-OUT-22", "c_agent": "C-FINAL"}
    plan = _plan("두 값을 합쳐줘", [
        ("parallel", [("a_agent", "a 를 구해"), ("b_agent", "b 를 구해")]),
        ("sequential", [("c_agent", "둘을 합쳐")]),
    ])
    result = await ExecutionEngine(agent_executor=_executor(out, log)).execute(plan)

    a, b, c = log["a_agent"], log["b_agent"], log["c_agent"]
    assert b["start"] < a["end"] and a["start"] < b["end"]          # 병렬
    assert c["start"] >= max(a["end"], b["end"]) - 0.01              # 대조군: 다음 stage 는 기다린다
    assert "A-OUT-11" in c["query"] and "B-OUT-22" in c["query"] and "둘을 합쳐" in c["query"]
    assert "A-OUT-11" not in a["query"]                              # 대조군
    assert c["context"].get("original_query") == "두 값을 합쳐줘"
    assert result.success is True and "C-FINAL" in str(result.final_output)


async def test_sequential_second_step_receives_first_result():
    """구 SDK 엔진(logosai.workflow)이 실패하던 바로 그 모양."""
    from logosai.orchestration import ExecutionEngine

    log = {}
    out = {"upper_agent": "HELLO WORLD", "reverse_agent": "DLROW OLLEH"}
    plan = _plan("대문자로 바꾼 뒤 뒤집어줘", [
        ("sequential", [("upper_agent", "대문자로: hello world")]),
        ("sequential", [("reverse_agent", "그 결과를 뒤집어라")]),
    ])
    result = await ExecutionEngine(agent_executor=_executor(out, log)).execute(plan)

    second = log["reverse_agent"]["query"]
    assert result.success is True
    assert "HELLO WORLD" in second and "그 결과를 뒤집어라" in second
