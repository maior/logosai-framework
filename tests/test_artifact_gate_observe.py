"""산출물 관문 — 실제로 돈다, 그리고 지금은 관찰만 한다.

2026-08-18 에 도입된 관문은 PlanValidator 가 레지스트리의 `list_agents()` 를 불렀는데
AgentRegistry 에는 그 메서드가 없다(`get_all_agents()`). 예외가 fail-open 으로 삼켜져
운영 로그에 "산출물 관문 건너뜀" 42건, 판정 0건 — 도입 이후 한 번도 돌지 않았다.
판정 함수만 직접 부르는 테스트 10개는 계속 초록이었다. 배선은 아무도 재지 않았다.

그래서 여기 배선 테스트는 **실제 AgentRegistry** 로 한다.

모드 (LOGOSAI_ARTIFACT_GATE, 값 기반):
  observe (기본) — 판정을 백그라운드로 돌려 기록만 한다. 계획을 막지 않는다.
  off            — 돌리지 않는다.
  enforce        — 판정이 누락이면 검증 오류로 올린다(상위 재계획 루프를 탄다).
측정되지 않은 LLM 판정기를 바로 켜지 않는다 — 판정을 쌓아 정밀도를 잰 뒤 정한다.
"""
import asyncio
import json

import pytest

from logosai.orchestration import (
    AgentRegistry, AgentRegistryEntry, AgentSchema, AgentTask, ExecutionPlan, ExecutionStage,
)
from logosai.orchestration import plan_validator as pv
from logosai.orchestration.plan_validator import PlanValidator, judge_artifact


def _registry():
    reg = AgentRegistry()
    for aid, desc in [
        ("internet_agent", "인터넷 검색"),
        ("xlsx_generator_agent", "표·수치 데이터를 실제 Excel 워크북(.xlsx)으로 만든다"),
    ]:
        reg.register_agent(AgentRegistryEntry(
            agent_id=aid, name=aid, description=desc, capabilities=[], tags=[],
            schema=AgentSchema(input_type="query", output_type="text")))
    return reg


def _plan(query="서울 인구 통계를 검색해서 엑셀 파일로 만들어줘"):
    return ExecutionPlan(query=query, workflow_strategy="sequential", stages=[
        ExecutionStage(stage_id=1, execution_type="sequential",
                       agents=[AgentTask(agent_id="internet_agent", sub_query="서울 인구 통계")])])


class FakeJudge:
    def __init__(self, answer):
        self.answer, self.prompts = answer, []

    async def __call__(self, prompt):
        self.prompts.append(prompt)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


MISSING = json.dumps({"artifact": "엑셀 파일", "missing_agent": "xlsx_generator_agent"})
NO_ARTIFACT = json.dumps({"artifact": "none", "missing_agent": None})


@pytest.fixture
def recorded(monkeypatch):
    """Pulse 로 가는 판정 기록을 가로챈다."""
    rows = []
    monkeypatch.setattr(pv, "_record_artifact_verdict", lambda **kw: rows.append(kw))
    return rows


# ── 배선: 실제 레지스트리로 판정기까지 닿는다 ─────────────────────────

async def test_gate_reaches_the_judge_with_a_real_registry(monkeypatch, recorded):
    monkeypatch.setenv("LOGOSAI_ARTIFACT_GATE", "observe")
    judge = FakeJudge(MISSING)
    validator = PlanValidator(registry=_registry(), llm_invoke=judge)

    await validator.validate(_plan())
    await validator.wait_observations()

    assert len(judge.prompts) == 1, "관문이 판정기를 부르지 않았다 — 배선이 끊겨 있다"
    assert "xlsx_generator_agent" in judge.prompts[0], "레지스트리의 에이전트가 판정기에 안 갔다"


# ── observe: 기록하되 막지 않는다 ───────────────────────────────────

async def test_observe_records_but_does_not_block(monkeypatch, recorded):
    monkeypatch.setenv("LOGOSAI_ARTIFACT_GATE", "observe")
    validator = PlanValidator(registry=_registry(), llm_invoke=FakeJudge(MISSING))

    result = await validator.validate(_plan())
    await validator.wait_observations()

    assert result.is_valid is True, "관찰 모드가 계획을 막았다"
    (row,) = recorded
    assert row["mode"] == "observe" and row["verdict"]["status"] == "missing"
    assert row["verdict"]["missing_agent"] == "xlsx_generator_agent"
    assert row["planned"] == ["internet_agent"] and "엑셀" in row["query"]


async def test_observe_does_not_wait_for_the_judge(monkeypatch, recorded):
    """판정은 응답 경로 밖에서 돈다 — 느린 판정기가 검증을 늦추지 않는다."""
    monkeypatch.setenv("LOGOSAI_ARTIFACT_GATE", "observe")

    async def slow(prompt):
        await asyncio.sleep(0.5)
        return MISSING

    validator = PlanValidator(registry=_registry(), llm_invoke=slow)
    loop = asyncio.get_running_loop()
    start = loop.time()
    await validator.validate(_plan())
    assert loop.time() - start < 0.3, "관찰 모드 검증이 판정기를 기다렸다"
    await validator.wait_observations()
    assert recorded and recorded[0]["verdict"]["status"] == "missing"   # 대조군 — 결국 기록된다


# ── enforce: 설계된 원래 동작 ────────────────────────────────────────

async def test_enforce_blocks_a_missing_artifact(monkeypatch, recorded):
    monkeypatch.setenv("LOGOSAI_ARTIFACT_GATE", "enforce")
    validator = PlanValidator(registry=_registry(), llm_invoke=FakeJudge(MISSING))

    result = await validator.validate(_plan())

    assert result.is_valid is False
    assert any("xlsx_generator_agent" in e for e in result.errors)
    assert recorded and recorded[0]["mode"] == "enforce"


async def test_enforce_passes_when_nothing_is_missing(monkeypatch, recorded):
    """대조군 — 집행 모드가 아무 계획이나 막지 않는다."""
    monkeypatch.setenv("LOGOSAI_ARTIFACT_GATE", "enforce")
    validator = PlanValidator(registry=_registry(), llm_invoke=FakeJudge(NO_ARTIFACT))

    result = await validator.validate(_plan("서울 인구 알려줘"))

    assert result.is_valid is True


# ── off ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["off", "false", "0", "no"])
async def test_off_values_do_not_call_the_judge(monkeypatch, recorded, value):
    monkeypatch.setenv("LOGOSAI_ARTIFACT_GATE", value)
    judge = FakeJudge(MISSING)
    validator = PlanValidator(registry=_registry(), llm_invoke=judge)

    result = await validator.validate(_plan())
    await validator.wait_observations()

    assert judge.prompts == [] and recorded == [] and result.is_valid is True


async def test_unknown_mode_falls_back_to_observe(monkeypatch, recorded):
    """오타가 관문을 집행으로 켜거나 조용히 끄지 않는다 — 가장 안전한 관찰로."""
    monkeypatch.setenv("LOGOSAI_ARTIFACT_GATE", "enforec")
    validator = PlanValidator(registry=_registry(), llm_invoke=FakeJudge(MISSING))

    result = await validator.validate(_plan())
    await validator.wait_observations()

    assert result.is_valid is True and recorded[0]["mode"] == "observe"


# ── 판정 세분화: '모름'을 '없음'으로 뭉개지 않는다 ─────────────────────

@pytest.mark.parametrize("answer,status", [
    (MISSING, "missing"),
    (NO_ARTIFACT, "none"),
    (json.dumps({"artifact": "엑셀 파일", "missing_agent": None}), "ok"),
    (json.dumps({"artifact": "엑셀", "missing_agent": "internet_agent"}), "self_contradiction"),
    (json.dumps({"artifact": "엑셀", "missing_agent": "ghost_agent"}), "hallucinated"),
    ("판정할 수 없습니다", "unparsable"),
    (RuntimeError("429"), "error"),
])
async def test_judge_artifact_keeps_unknown_apart_from_none(answer, status):
    info = {"internet_agent": "검색", "xlsx_generator_agent": "엑셀"}
    verdict = await judge_artifact("엑셀로 만들어줘", {"internet_agent"}, info, FakeJudge(answer))
    assert verdict["status"] == status


async def test_compat_wrapper_still_returns_error_list():
    """기존 check_artifact_capability 소비자(ontology 테스트 10개)는 그대로다."""
    from logosai.orchestration.plan_validator import check_artifact_capability

    info = {"internet_agent": "검색", "xlsx_generator_agent": "엑셀"}
    errs = await check_artifact_capability("엑셀로 만들어줘", {"internet_agent"}, info, FakeJudge(MISSING))
    assert len(errs) == 1 and "xlsx_generator_agent" in errs[0]
    assert await check_artifact_capability("x", {"internet_agent"}, info, FakeJudge(NO_ARTIFACT)) == []


async def test_unset_mode_is_observe(monkeypatch, recorded):
    """기본값은 observe — 판정기로 주입되는 플래너 LLM 호출이 비차단이 됐다
    (asyncio.to_thread, 2026-10-04). 그 전엔 루프를 0.92s 막아 off 였다."""
    monkeypatch.delenv("LOGOSAI_ARTIFACT_GATE", raising=False)
    judge = FakeJudge(MISSING)
    validator = PlanValidator(registry=_registry(), llm_invoke=judge)

    result = await validator.validate(_plan())
    await validator.wait_observations()

    assert result.is_valid is True and len(judge.prompts) == 1
    assert recorded and recorded[0]["mode"] == "observe"
