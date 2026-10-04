"""SDK 기본 플래너 — 계획 수립 메커니즘. 특정 조직의 에이전트 지식은 없다.

ontology 의 운영 플래너(Logos 프롬프트·Gemini·하이브리드 선택기·배제 관문·키워드
안전망)는 이 클래스를 상속해 훅을 재정의한다. 기본 구현은:
  · 프롬프트 — 등록된 에이전트만으로 만든 일반 프롬프트 (특정 agent_id 없음)
  · LLM — 주입한 llm_invoke, 없으면 logosai LLMClient
  · 힌트·배제 관문·키워드 gap — 없음
  · 계획 비평·gap 백필·단계 병합 — 일반 메커니즘이라 기본에 포함
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from logosai.orchestration import (
    AgentRegistry, AgentRegistryEntry, AgentSchema, ExecutionPlan,
)
from logosai.orchestration.planner import QueryPlanner

ROOT = Path(__file__).resolve().parents[1]

#: Logos 운영 프롬프트에 박혀 있던 것들 — SDK 기본 프롬프트에는 없어야 한다
LOGOS_SPECIFIC = ["internet_agent", "llm_search_agent", "weather_agent",
                  "samsung_gateway_agent", "삼성", "NAND"]


def _registry(*agents):
    reg = AgentRegistry()      # SDK 레지스트리는 빈 상태로 시작한다 (2026-10-05)
    for aid, desc in agents:
        reg.register_agent(AgentRegistryEntry(
            agent_id=aid, name=aid, description=desc, capabilities=[], tags=[],
            schema=AgentSchema(input_type="query", output_type="text")))
    return reg


class FakeLLM:
    def __init__(self, *plans, critique='{"unnecessary_agents": [], "broken_chain": false, "reason": "ok"}'):
        self.plans, self.critique, self.prompts = list(plans), critique, []

    async def __call__(self, prompt):
        self.prompts.append(prompt)
        if "두 가지만 판정하라" in prompt:
            return self.critique
        return self.plans.pop(0) if len(self.plans) > 1 else self.plans[0]


def _plan(*stages):
    return json.dumps({"workflow_strategy": "hybrid", "stages": [
        {"stage_id": i, "execution_type": kind,
         "agents": [{"agent_id": a, "sub_query": f"{a} 일", "input_from": inp} for a in agents]}
        for i, (kind, agents, inp) in enumerate(stages, 1)]}, ensure_ascii=False)


REG = [("alpha_agent", "상품 가격을 조회한다"), ("beta_agent", "표를 엑셀로 만든다")]


async def test_plans_end_to_end_with_an_injected_llm():
    llm = FakeLLM(_plan(("sequential", ["alpha_agent"], None),
                        ("sequential", ["beta_agent"], ["stage_1"])))
    plan = await QueryPlanner(registry=_registry(*REG), llm_invoke=llm).create_plan("가격 조회해서 엑셀로")

    assert isinstance(plan, ExecutionPlan)
    assert [[t.agent_id for t in s.agents] for s in plan.stages] == [["alpha_agent"], ["beta_agent"]]
    assert plan.capability_gap is None


async def test_default_prompt_carries_registered_agents_only():
    llm = FakeLLM(_plan(("sequential", ["alpha_agent"], None)))
    await QueryPlanner(registry=_registry(*REG), llm_invoke=llm).create_plan("가격 알려줘")

    prompt = llm.prompts[0]
    assert "alpha_agent" in prompt and "상품 가격을 조회한다" in prompt       # 대조군 — 등록된 건 있다
    leaked = [w for w in LOGOS_SPECIFIC if w in prompt]
    assert leaked == [], f"SDK 기본 프롬프트에 특정 조직의 지식이 있다: {leaked}"
    assert "가격 알려줘" in prompt


async def test_critique_runs_for_multi_agent_plans():
    llm = FakeLLM(_plan(("parallel", ["alpha_agent", "beta_agent"], None)))
    await QueryPlanner(registry=_registry(*REG), llm_invoke=llm).create_plan("둘 다")
    assert any("두 가지만 판정하라" in p for p in llm.prompts)


async def test_single_agent_plan_makes_one_llm_call():
    """대조군 — 기본에는 배제 관문이 없고 비평은 단일 에이전트에서 돌지 않는다."""
    llm = FakeLLM(_plan(("sequential", ["alpha_agent"], None)))
    await QueryPlanner(registry=_registry(*REG), llm_invoke=llm).create_plan("가격")
    assert len(llm.prompts) == 1


async def test_empty_plan_is_backfilled_as_a_gap():
    llm = FakeLLM(json.dumps({"workflow_strategy": "sequential", "stages": []}))
    plan = await QueryPlanner(registry=_registry(*REG), llm_invoke=llm).create_plan("불가능한 일")
    assert plan.capability_gap and plan.capability_gap["detected"] is True


async def test_no_keyword_gap_by_default():
    """키워드 안전망('에이전트 만들어줘')은 Logos 인스턴스의 것 — 기본에는 없다."""
    llm = FakeLLM(_plan(("sequential", ["alpha_agent"], None)))
    plan = await QueryPlanner(registry=_registry(*REG), llm_invoke=llm).create_plan("에이전트 만들어줘")
    assert plan.capability_gap is None


def test_planner_does_not_pull_ontology():
    code = ("import sys, logosai.orchestration.planner; "
            "bad=[m for m in sys.modules if m=='ontology' or m.startswith('ontology.')]; "
            "print('BAD' if bad else 'OK', bad[:5])")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert out.stdout.startswith("OK"), out.stdout + out.stderr[-400:]


def test_planner_is_exported():
    import logosai.orchestration as orch
    assert orch.QueryPlanner is QueryPlanner and "QueryPlanner" in orch.__all__
