"""SDK WorkflowOrchestrator — 계획 → 검증 → 실행 → 집계를 SDK 만으로.

ontology 의 운영 오케스트레이터는 이 클래스를 상속해 플래너만 Logos 것으로 바꾼다
(_make_planner). SDK 사용자는 LLM 을 llm_invoke 로 주입하거나 LLMClient 를 쓴다.
구 logosai.workflow.WorkflowOrchestrator 와는 다른 클래스다 — 그 관계는 P4 에서 정리.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from logosai.orchestration import (
    AgentRegistry, AgentRegistryEntry, AgentSchema, ProgressEventType, WorkflowOrchestrator,
)
from logosai.orchestration.exceptions import PlanValidationError
from logosai.orchestration.planner import QueryPlanner

ROOT = Path(__file__).resolve().parents[1]
CRITIQUE_OK = '{"unnecessary_agents": [], "broken_chain": false, "reason": "ok"}'


def _registry(*ids):
    reg = AgentRegistry()
    for aid in ids:
        reg.register_agent(AgentRegistryEntry(
            agent_id=aid, name=aid, description=f"{aid} 설명", capabilities=[], tags=[],
            schema=AgentSchema(input_type="query", output_type="text")))
    return reg


def _llm(plan, prompts=None):
    async def invoke(prompt):
        if prompts is not None:
            prompts.append(prompt)
        return CRITIQUE_OK if "두 가지만 판정하라" in prompt else plan
    return invoke


def _plan(*stages):
    return json.dumps({"workflow_strategy": "hybrid", "stages": [
        {"stage_id": i, "execution_type": kind,
         "agents": [{"agent_id": a, "sub_query": f"{a} 일", "input_from": inp} for a in agents]}
        for i, (kind, agents, inp) in enumerate(stages, 1)]}, ensure_ascii=False)


async def _executor(agent_id, query, context):
    return {"success": True, "result": {"answer": f"{agent_id} 결과"}}


async def test_streams_a_full_workflow_with_an_injected_llm(monkeypatch):
    monkeypatch.setenv("LOGOSAI_ARTIFACT_GATE", "off")
    prompts = []
    orch = WorkflowOrchestrator(
        agent_executor=_executor, registry=_registry("alpha_agent", "beta_agent"),
        llm_invoke=_llm(_plan(("parallel", ["alpha_agent", "beta_agent"], None)), prompts))
    types = [ev.type async for ev in orch.run_streaming("둘 다")]

    assert types[-1] == ProgressEventType.WORKFLOW_COMPLETE
    assert prompts and "alpha_agent" in prompts[0]            # 주입한 LLM 이 실제로 쓰였다


async def test_run_returns_a_result(monkeypatch):
    monkeypatch.setenv("LOGOSAI_ARTIFACT_GATE", "off")
    orch = WorkflowOrchestrator(agent_executor=_executor, registry=_registry("alpha_agent"),
                                llm_invoke=_llm(_plan(("sequential", ["alpha_agent"], None))))
    result = await orch.run("하나")
    assert result.success and result.successful_agents == 1


async def test_validation_rejects_unregistered_agents(monkeypatch):
    monkeypatch.setenv("LOGOSAI_ARTIFACT_GATE", "off")
    orch = WorkflowOrchestrator(agent_executor=_executor, registry=_registry("alpha_agent"),
                                llm_invoke=_llm(_plan(("sequential", ["ghost_agent"], None))))
    with pytest.raises(PlanValidationError):
        await orch.run("유령")


def test_planner_is_built_by_an_overridable_hook():
    """조직별 오케스트레이터는 _make_planner 만 바꾼다."""
    class Mine(QueryPlanner):
        pass

    class MyOrchestrator(WorkflowOrchestrator):
        def _make_planner(self, streamer):
            return Mine(registry=self.registry, streamer=streamer, llm_invoke=self._llm_invoke)

    orch = MyOrchestrator(agent_executor=_executor, registry=_registry("alpha_agent"))
    orch._init_components(None)
    assert type(orch._planner) is Mine
    plain = WorkflowOrchestrator(agent_executor=_executor, registry=_registry("alpha_agent"))
    plain._init_components(None)
    assert type(plain._planner) is QueryPlanner                # 대조군 — 기본은 SDK 플래너


def test_workflow_orchestrator_does_not_pull_ontology():
    code = ("import sys, logosai.orchestration.workflow_orchestrator; "
            "bad=[m for m in sys.modules if m=='ontology' or m.startswith('ontology.')]; "
            "print('BAD' if bad else 'OK', bad[:5])")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert out.stdout.startswith("OK"), out.stdout + out.stderr[-400:]


def test_exported_from_the_orchestration_package():
    import logosai.orchestration as orch
    from logosai.orchestration import workflow_orchestrator as wo
    assert orch.WorkflowOrchestrator is wo.WorkflowOrchestrator
    assert "WorkflowOrchestrator" in orch.__all__
