"""SDK AgentRegistry 는 빈 상태로 시작한다 — 기본 에이전트는 호출자가 넣는다.

2단계 이전 때 Logos 에이전트 12개가 DEFAULT_AGENTS 로 따라왔다. SDK 를 설치한
외부 사용자의 레지스트리에도 samsung_gateway_agent 같은 것이 들어갔고, 그중
rag_search_agent 는 어디에도 실체가 없는 유령이라 운영 플래너 프롬프트에 후보로
실렸다(운영 DB 87개가 나머지 11개는 덮지만 이것만 못 덮었다). Logos 목록은
ontology.orchestrator.logos_agents 로 옮겼다 (2026-10-05).
"""
from pathlib import Path

from logosai.orchestration import AgentRegistry, AgentRegistryEntry, AgentSchema
from logosai.orchestration import agent_registry as registry_module

SOURCE = Path(registry_module.__file__)

#: 이전 기본 목록에 있던 Logos 에이전트들 — SDK 소스에서 사라져야 한다
LOGOS_IDS = ["internet_agent", "weather_agent", "samsung_gateway_agent", "rag_search_agent",
             "shopping_agent", "currency_exchange_agent"]


def _entry(aid):
    return AgentRegistryEntry(agent_id=aid, name=aid, description=f"{aid} 설명",
                              capabilities=[], tags=[],
                              schema=AgentSchema(input_type="query", output_type="text"))


def test_new_registry_starts_empty():
    reg = AgentRegistry()
    assert reg.get_agent_ids() == []
    reg.register_agent(_entry("alpha_agent"))            # 대조군 — 등록은 된다
    assert reg.get_agent_ids() == ["alpha_agent"]


def test_defaults_are_injected_by_the_caller():
    reg = AgentRegistry(defaults=[_entry("alpha_agent"), _entry("beta_agent")])
    assert reg.get_agent_ids() == ["alpha_agent", "beta_agent"]


def test_injected_defaults_are_not_shared_between_registries():
    defaults = [_entry("alpha_agent")]
    a, b = AgentRegistry(defaults=defaults), AgentRegistry(defaults=defaults)
    a.unregister_agent("alpha_agent")
    assert not a.has_agent("alpha_agent") and b.has_agent("alpha_agent")
    assert len(defaults) == 1


def test_defaults_come_before_later_registrations():
    """등록 순서가 프롬프트 나열 순서다 — 운영(기본 먼저, DB 나중)과 같은 모양을 유지할 수 있어야 한다."""
    reg = AgentRegistry(defaults=[_entry("alpha_agent")])
    reg.register_agent(_entry("zeta_agent"))
    reg.register_agent(_entry("alpha_agent"))            # 덮어써도 자리는 그대로
    assert reg.get_agent_ids() == ["alpha_agent", "zeta_agent"]


def test_sdk_source_carries_no_logos_agents():
    src = SOURCE.read_text(encoding="utf-8")
    leaked = [a for a in LOGOS_IDS if a in src]
    assert leaked == [], f"SDK 레지스트리 소스에 Logos 에이전트가 있다: {leaked}"
    assert "agent_id" in src                             # 대조군 — 엉뚱한 파일을 읽고 있지 않다


def test_global_registry_starts_empty(monkeypatch):
    monkeypatch.setattr(registry_module, "_default_registry", None)
    assert registry_module.get_registry().get_agent_ids() == []


# ── 빈 레지스트리도 '있는 레지스트리'다 ───────────────────────────────
# AgentRegistry 에는 __len__ 이 있어 비면 거짓이 된다. 기본 12개가 있던 동안엔 늘
# 참이라 아무도 몰랐다. 비우자 `registry or get_registry()` 가 호출자가 넘긴 빈
# 레지스트리를 버리고 전역을 썼고(logos_api 는 빈 레지스트리를 넘긴 뒤 DB 로 채운다),
# agent_sync_service 의 `if not self.agent_registry:` 는 동기화를 건너뛰었다.


def test_empty_registry_is_truthy():
    reg = AgentRegistry()
    assert len(reg) == 0 and bool(reg) is True


def test_components_keep_an_injected_empty_registry(monkeypatch):
    """결선 시험 — 각 구성 요소가 넘겨받은 빈 레지스트리를 그대로 쓴다."""
    from logosai.orchestration.data_transformer import DataTransformer
    from logosai.orchestration.execution_engine import ExecutionEngine
    from logosai.orchestration.plan_validator import PlanValidator
    from logosai.orchestration.planner import QueryPlanner

    sentinel = AgentRegistry(defaults=[_entry("sentinel_agent")])
    monkeypatch.setattr(registry_module, "_default_registry", sentinel)   # 전역은 다른 객체
    mine = AgentRegistry()
    made = {
        "planner": QueryPlanner(registry=mine, llm_invoke=lambda p: None),
        "engine": ExecutionEngine(agent_executor=lambda *a: None, registry=mine),
        "validator": PlanValidator(registry=mine),
        "transformer": DataTransformer(registry=mine),
    }
    wrong = [k for k, v in made.items() if v.registry is not mine]
    assert wrong == [], f"넘긴 빈 레지스트리를 버리고 전역을 쓴다: {wrong}"
    assert QueryPlanner(llm_invoke=lambda p: None).registry is sentinel   # 대조군 — 안 넘기면 전역
