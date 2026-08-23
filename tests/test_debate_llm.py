"""
LLM Debate System — 모듈별 + 통합 테스트

Usage:
    # 모듈 테스트만 (LLM 호출 없음)
    pytest tests/test_debate_llm.py -k "TestPrompts or TestLLMDebateUnit" -v

    # 통합 테스트 (LLM 호출 포함, GOOGLE_API_KEY 필요)
    pytest tests/test_debate_llm.py -k "TestLLMDebateIntegration" -v

    # 전체
    pytest tests/test_debate_llm.py -v
"""

import asyncio
import json
import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from logosai.debate.prompts import build_analysis_prompt, DOMAIN_KNOWLEDGE, SYSTEM_PROMPT
from logosai.debate.llm_debate import LLMDebateSystem
from logosai.debate.debate_system import SimpleDebateSystem, AgentAnalysis
from logosai.agent import LogosAIAgent
from logosai.config import AgentConfig
from logosai.agent_types import AgentType, AgentResponse, AgentResponseType


# ========== 테스트용 에이전트 ==========

def _make_agent(agent_id, name, description):
    """테스트용 간단한 에이전트 생성"""
    config = AgentConfig(
        name=name,
        agent_type=AgentType.CUSTOM,
        description=description,
    )
    agent = LogosAIAgent(config)
    agent.agent_id = agent_id
    return agent


def create_banking_agents():
    return [
        _make_agent("loan_reviewer", "대출심사역", "신용평가, 담보평가, 대출 승인/거절 판단"),
        _make_agent("fraud_detector", "FDS전문가", "이상거래 탐지, 사기 방지, 보안 위협 분석"),
        _make_agent("compliance_officer", "준법감시인", "금융 규제 준수, 법규 검토, 컴플라이언스 체크"),
        _make_agent("risk_analyst", "리스크분석가", "시장 리스크, 신용 리스크, 운영 리스크 평가"),
        _make_agent("customer_service", "고객상담사", "고객 응대, 불만 처리, 상품 안내, 문의 응답"),
    ]


BANKING_SCENARIOS = [
    {
        "name": "주택담보대출",
        "query": "고객이 5억원 주택담보대출을 신청했습니다. 신용평가하고 심사해주세요.",
        "expected": {"loan_reviewer", "risk_analyst", "compliance_officer"},
    },
    {
        "name": "고액 이체 사기",
        "query": "새벽 3시에 해외로 1억원 이체 요청이 들어왔습니다. 이상거래 여부를 확인해주세요.",
        "expected": {"fraud_detector", "risk_analyst", "customer_service"},
    },
    {
        "name": "신규 금융상품 규제",
        "query": "새로운 가상자산 연계 예금 상품을 출시하려고 합니다. 금융당국 규제를 검토해주세요.",
        "expected": {"compliance_officer", "risk_analyst"},
    },
    {
        "name": "고객 불만 처리",
        "query": "고객이 대출 승인이 거절되어 민원을 제기했습니다. 처리하고 보상 여부를 검토해주세요.",
        "expected": {"customer_service", "loan_reviewer", "compliance_officer"},
    },
    {
        "name": "종합 리스크 관리",
        "query": "대규모 기업대출 포트폴리오의 신용리스크와 시장리스크를 평가하고 보고서를 작성해주세요.",
        "expected": {"risk_analyst", "loan_reviewer", "compliance_officer"},
    },
]


# ========== 모듈 테스트: prompts.py ==========

class TestPrompts:
    """prompts.py 단위 테스트 (LLM 호출 없음)"""

    def test_build_prompt_includes_query(self):
        agents = [{"id": "t", "name": "T", "description": "test"}]
        prompt = build_analysis_prompt("대출 신청", agents)
        assert "대출 신청" in prompt

    def test_build_prompt_includes_agents(self):
        agents = [{"id": "loan_reviewer", "name": "대출심사역", "description": "신용평가"}]
        prompt = build_analysis_prompt("test", agents)
        assert "loan_reviewer" in prompt
        assert "대출심사역" in prompt
        assert "신용평가" in prompt

    def test_build_prompt_with_banking_domain(self):
        agents = [{"id": "t", "name": "T", "description": "test"}]
        prompt = build_analysis_prompt("test", agents, domain="banking")
        assert "Loan applications require" in prompt

    def test_build_prompt_with_general_domain(self):
        agents = [{"id": "t", "name": "T", "description": "test"}]
        prompt = build_analysis_prompt("test", agents, domain=None)
        assert "full task pipeline" in prompt

    def test_build_prompt_with_unknown_domain(self):
        agents = [{"id": "t", "name": "T", "description": "test"}]
        prompt = build_analysis_prompt("test", agents, domain="unknown_xyz")
        assert "Domain Knowledge" not in prompt

    def test_domain_knowledge_keys(self):
        assert "banking" in DOMAIN_KNOWLEDGE
        assert "general" in DOMAIN_KNOWLEDGE
        assert "healthcare" in DOMAIN_KNOWLEDGE

    def test_system_prompt_exists(self):
        assert len(SYSTEM_PROMPT) > 0
        assert "orchestrator" in SYSTEM_PROMPT.lower()

    def test_output_format_in_prompt(self):
        agents = [{"id": "t", "name": "T", "description": "test"}]
        prompt = build_analysis_prompt("test", agents)
        assert "relevance_score" in prompt
        assert "can_contribute" in prompt
        assert "proposed_role" in prompt


# ========== 모듈 테스트: llm_debate.py ==========

class TestLLMDebateUnit:
    """llm_debate.py 단위 테스트 (LLM 호출 없음)"""

    def test_init_default(self):
        system = LLMDebateSystem()
        assert system.domain is None
        assert system.timeout == 30
        assert system._initialized is False
        assert isinstance(system, SimpleDebateSystem)

    def test_init_custom(self):
        system = LLMDebateSystem(
            provider="google",
            model="gemini-2.5-flash-lite",
            temperature=0.2,
            domain="banking",
            timeout=15,
        )
        assert system.domain == "banking"
        assert system.timeout == 15

    def test_get_agent_info(self):
        system = LLMDebateSystem()
        agents = create_banking_agents()
        info = system._get_agent_info(agents)

        assert len(info) == 5
        assert info[0]["id"] == "loan_reviewer"
        assert info[0]["name"] == "대출심사역"
        assert "신용평가" in info[0]["description"]

    def test_get_agent_info_no_description(self):
        system = LLMDebateSystem()

        class BareAgent:
            agent_id = "bare"
            name = "Bare"

        info = system._get_agent_info([BareAgent()])
        assert info[0]["description"] == ""

    def test_role_reuse_from_phase1(self):
        """Phase 2에서 Phase 1의 역할 재사용 확인"""
        system = LLMDebateSystem()
        agents = create_banking_agents()

        analyses = [
            AgentAnalysis(
                agent_id="loan_reviewer",
                understanding="test",
                relevance_score=0.9,
                can_contribute=True,
                proposed_role="대출 심사 수행",
                reasoning="대출 관련 쿼리",
            )
        ]

        result = asyncio.run(
            system._ask_agent_for_role(agents[0], "test", analyses)
        )
        assert result["role"] == "대출 심사 수행"
        assert result["reasoning"] == "대출 관련 쿼리"


# ========== 통합 테스트 (실제 LLM 호출) ==========

def _calc_f1(actual, expected):
    matched = actual & expected
    precision = len(matched) / len(actual) if actual else 0
    recall = len(matched) / len(expected) if expected else 0
    return 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0


@pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="GOOGLE_API_KEY not set"
)
class TestLLMDebateIntegration:
    """실제 LLM 호출 통합 테스트"""

    @pytest.fixture
    def agents(self):
        return create_banking_agents()

    @pytest.fixture
    def llm_system(self):
        return LLMDebateSystem(domain="banking")

    @pytest.fixture
    def keyword_system(self):
        return SimpleDebateSystem()

    @pytest.mark.asyncio
    async def test_banking_scenario_loan(self, llm_system, agents):
        """시나리오 1: 대출 — loan_reviewer, risk_analyst, compliance_officer"""
        result = await llm_system.start_debate(BANKING_SCENARIOS[0]["query"], agents)
        actual = set(result.participating_agents)
        expected = BANKING_SCENARIOS[0]["expected"]

        f1 = _calc_f1(actual, expected)
        print(f"\n대출: actual={sorted(actual)}, expected={sorted(expected)}, F1={f1:.0%}")
        assert f1 >= 0.6, f"F1 too low: {f1:.0%}"

    @pytest.mark.asyncio
    async def test_banking_scenario_fraud(self, llm_system, agents):
        """시나리오 2: 사기 — fraud_detector, risk_analyst, customer_service"""
        result = await llm_system.start_debate(BANKING_SCENARIOS[1]["query"], agents)
        actual = set(result.participating_agents)
        expected = BANKING_SCENARIOS[1]["expected"]

        f1 = _calc_f1(actual, expected)
        print(f"\n사기: actual={sorted(actual)}, expected={sorted(expected)}, F1={f1:.0%}")
        assert f1 >= 0.5, f"F1 too low: {f1:.0%}"

    @pytest.mark.asyncio
    async def test_banking_all_scenarios_f1(self, llm_system, agents):
        """전체 5개 시나리오 평균 F1 ≥ 85%"""
        total_f1 = 0
        for scenario in BANKING_SCENARIOS:
            result = await llm_system.start_debate(scenario["query"], agents)
            actual = set(result.participating_agents)
            f1 = _calc_f1(actual, scenario["expected"])
            total_f1 += f1
            print(f"\n  {scenario['name']}: actual={sorted(actual)}, F1={f1:.0%}")

        avg_f1 = total_f1 / len(BANKING_SCENARIOS)
        print(f"\n  평균 F1: {avg_f1:.1%}")
        assert avg_f1 >= 0.85, f"Average F1 too low: {avg_f1:.1%}"

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self, agents):
        """LLM 실패 시 키워드 기반 폴백"""
        system = LLMDebateSystem(
            provider="google",
            model="nonexistent-model-xyz",
            timeout=5,
        )
        # 잘못된 모델이지만 폴백으로 키워드 분석이 동작해야 함
        result = await system.start_debate(
            "고객이 대출을 신청했습니다.",
            agents,
        )
        assert result.consensus_reached
        assert len(result.participating_agents) > 0
        print(f"\n  폴백 결과: {result.participating_agents}")

    @pytest.mark.asyncio
    async def test_keyword_vs_llm_comparison(self, keyword_system, llm_system, agents):
        """키워드 vs LLM 비교 (정보 출력용)"""
        print("\n\n" + "=" * 70)
        print("  키워드 vs LLM 비교")
        print("=" * 70)

        keyword_f1_total = 0
        llm_f1_total = 0

        for scenario in BANKING_SCENARIOS:
            # 키워드
            kr = await keyword_system.start_debate(scenario["query"], agents)
            k_actual = set(kr.participating_agents)
            k_f1 = _calc_f1(k_actual, scenario["expected"])
            keyword_f1_total += k_f1

            # LLM
            lr = await llm_system.start_debate(scenario["query"], agents)
            l_actual = set(lr.participating_agents)
            l_f1 = _calc_f1(l_actual, scenario["expected"])
            llm_f1_total += l_f1

            print(f"\n  {scenario['name']}:")
            print(f"    키워드: {sorted(k_actual)} F1={k_f1:.0%}")
            print(f"    LLM:   {sorted(l_actual)} F1={l_f1:.0%}")

        n = len(BANKING_SCENARIOS)
        k_avg = keyword_f1_total / n
        l_avg = llm_f1_total / n
        print(f"\n  {'─' * 50}")
        print(f"  키워드 평균 F1: {k_avg:.1%}")
        print(f"  LLM 평균 F1:   {l_avg:.1%}")
        print(f"  개선:           {l_avg - k_avg:+.1%}")
        print(f"{'=' * 70}")

        # LLM이 키워드보다 나아야 함
        assert l_avg > k_avg, f"LLM ({l_avg:.1%}) should beat keyword ({k_avg:.1%})"
