"""
Debate System (v0.5.0) 단위 테스트

Tests:
- VotingSystem: 투표, 집계, 가중치 점수, 리셋
- SimpleDebateSystem: 5-phase 토론 흐름 (mock agents)
- AgentAnalysis / DebateResult 데이터 클래스
"""

import asyncio
import pytest
from unittest.mock import MagicMock
from datetime import datetime

# Debate system imports
from logosai.debate import SimpleDebateSystem, DebateResult, VotingSystem, Vote
from logosai.debate.debate_system import AgentAnalysis


# ============================================================
# Helper: Mock Agent
# ============================================================

def make_mock_agent(agent_id: str, name: str):
    """테스트용 Mock 에이전트 생성"""
    agent = MagicMock()
    agent.agent_id = agent_id
    agent.name = name
    agent.description = f"{name} description"
    return agent


# ============================================================
# VotingSystem Tests
# ============================================================

class TestVotingSystem:
    """VotingSystem 단위 테스트"""

    def setup_method(self):
        self.vs = VotingSystem()

    def test_initial_empty(self):
        assert len(self.vs.votes) == 0

    def test_cast_vote(self):
        vote = Vote(voter_id="agent_1", choice="workflow_0", reasoning="best option", confidence=0.9)
        self.vs.cast_vote(vote)
        assert len(self.vs.votes) == 1

    def test_count_votes_empty(self):
        result = self.vs.count_votes()
        assert result["winner"] is None
        assert result["votes"] == {}

    def test_count_votes_single(self):
        self.vs.cast_vote(Vote("a1", "workflow_0", "reason", 1.0))
        result = self.vs.count_votes()
        assert result["winner"] == "workflow_0"
        assert result["total_votes"] == 1

    def test_count_votes_majority(self):
        self.vs.cast_vote(Vote("a1", "workflow_0", "reason", 1.0))
        self.vs.cast_vote(Vote("a2", "workflow_1", "reason", 1.0))
        self.vs.cast_vote(Vote("a3", "workflow_0", "reason", 1.0))
        result = self.vs.count_votes()
        assert result["winner"] == "workflow_0"
        assert result["votes"]["workflow_0"] == 2
        assert result["votes"]["workflow_1"] == 1

    def test_weighted_scoring(self):
        # workflow_0 has 2 votes but low confidence
        self.vs.cast_vote(Vote("a1", "workflow_0", "reason", 0.3))
        self.vs.cast_vote(Vote("a2", "workflow_0", "reason", 0.3))
        # workflow_1 has 1 vote but high confidence
        self.vs.cast_vote(Vote("a3", "workflow_1", "reason", 0.9))

        result = self.vs.count_votes()
        # workflow_1 wins by weighted score: 0.9 > 0.6
        assert result["winner"] == "workflow_1"
        assert result["weighted_scores"]["workflow_0"] == pytest.approx(0.6)
        assert result["weighted_scores"]["workflow_1"] == pytest.approx(0.9)

    def test_reset(self):
        self.vs.cast_vote(Vote("a1", "workflow_0", "reason", 1.0))
        self.vs.reset()
        assert len(self.vs.votes) == 0

    def test_vote_dataclass(self):
        vote = Vote(voter_id="a1", choice="w0", reasoning="test", confidence=0.75)
        assert vote.voter_id == "a1"
        assert vote.choice == "w0"
        assert vote.confidence == 0.75


# ============================================================
# AgentAnalysis Tests
# ============================================================

class TestAgentAnalysis:
    """AgentAnalysis 데이터 클래스 테스트"""

    def test_creation(self):
        analysis = AgentAnalysis(
            agent_id="test_agent",
            understanding="Query understood",
            relevance_score=0.8,
            can_contribute=True,
            proposed_role="데이터 분석 담당",
            reasoning="전문성 활용"
        )
        assert analysis.agent_id == "test_agent"
        assert analysis.relevance_score == 0.8
        assert analysis.can_contribute is True

    def test_default_values(self):
        analysis = AgentAnalysis(
            agent_id="test",
            understanding="test",
            relevance_score=0.5,
            can_contribute=False
        )
        assert analysis.proposed_role is None
        assert analysis.reasoning == ""


# ============================================================
# DebateResult Tests
# ============================================================

class TestDebateResult:
    """DebateResult 데이터 클래스 테스트"""

    def test_creation(self):
        result = DebateResult(
            query="테스트 쿼리",
            workflow=[{"agent_id": "a1", "role": "분석", "order": 0}],
            participating_agents=["a1"],
            consensus_reached=True
        )
        assert result.query == "테스트 쿼리"
        assert len(result.workflow) == 1
        assert result.consensus_reached is True

    def test_default_values(self):
        result = DebateResult(
            query="test",
            workflow=[],
            participating_agents=[]
        )
        assert result.debate_transcript == []
        assert result.consensus_reached is True
        assert result.timestamp is not None


# ============================================================
# SimpleDebateSystem Tests
# ============================================================

class TestSimpleDebateSystem:
    """SimpleDebateSystem 단위 테스트"""

    def setup_method(self):
        self.debate = SimpleDebateSystem()

    # --- Keyword matching ---

    def test_get_agent_keywords_data_analyst(self):
        agent = make_mock_agent("data_analyst", "DataAnalyst")
        keywords = self.debate._get_agent_keywords(agent)
        assert "데이터" in keywords
        assert "분석" in keywords

    def test_get_agent_keywords_researcher(self):
        agent = make_mock_agent("researcher", "Researcher")
        keywords = self.debate._get_agent_keywords(agent)
        assert "조사" in keywords

    def test_get_agent_keywords_unknown(self):
        agent = make_mock_agent("unknown_agent", "Unknown")
        keywords = self.debate._get_agent_keywords(agent)
        assert keywords == []

    def test_get_agent_keywords_banking(self):
        agent = make_mock_agent("loan_reviewer", "LoanReviewer")
        keywords = self.debate._get_agent_keywords(agent)
        assert "대출" in keywords
        assert "심사" in keywords

    # --- Query analysis ---

    @pytest.mark.asyncio
    async def test_query_analysis_relevant(self):
        agent = make_mock_agent("data_analyst", "DataAnalyst")
        analysis = await self.debate._ask_agent_to_analyze(
            agent, "데이터 분석해줘"
        )
        assert analysis.can_contribute is True
        assert analysis.relevance_score > 0.2

    @pytest.mark.asyncio
    async def test_query_analysis_irrelevant(self):
        agent = make_mock_agent("data_analyst", "DataAnalyst")
        analysis = await self.debate._ask_agent_to_analyze(
            agent, "날씨 알려줘"
        )
        assert analysis.can_contribute is False
        assert analysis.relevance_score <= 0.2

    @pytest.mark.asyncio
    async def test_query_analysis_multiple_keywords(self):
        agent = make_mock_agent("data_analyst", "DataAnalyst")
        analysis = await self.debate._ask_agent_to_analyze(
            agent, "데이터 분석 통계 차트 만들어줘"
        )
        assert analysis.relevance_score > 0.5

    @pytest.mark.asyncio
    async def test_relevance_capped_at_1(self):
        agent = make_mock_agent("data_analyst", "DataAnalyst")
        # All 4 keywords match
        analysis = await self.debate._ask_agent_to_analyze(
            agent, "데이터 분석 통계 차트"
        )
        assert analysis.relevance_score <= 1.0

    # --- Role proposal ---

    @pytest.mark.asyncio
    async def test_role_proposal_known_agent(self):
        agent = make_mock_agent("data_analyst", "DataAnalyst")
        proposal = await self.debate._ask_agent_for_role(agent, "test", [])
        assert proposal["role"] == "데이터 분석 담당"

    @pytest.mark.asyncio
    async def test_role_proposal_unknown_agent(self):
        agent = make_mock_agent("unknown", "Unknown")
        proposal = await self.debate._ask_agent_for_role(agent, "test", [])
        assert proposal["role"] == "보조 담당"

    # --- Comment ---

    @pytest.mark.asyncio
    async def test_comment_with_others(self):
        agent = make_mock_agent("data_analyst", "DataAnalyst")
        other = AgentAnalysis(
            agent_id="researcher",
            understanding="test",
            relevance_score=0.8,
            can_contribute=True
        )
        comment = await self.debate._ask_agent_for_comment(agent, [other])
        assert "동의" in comment

    @pytest.mark.asyncio
    async def test_comment_alone(self):
        agent = make_mock_agent("data_analyst", "DataAnalyst")
        me = AgentAnalysis(
            agent_id="data_analyst",
            understanding="test",
            relevance_score=0.8,
            can_contribute=True
        )
        comment = await self.debate._ask_agent_for_comment(agent, [me])
        assert "충실히" in comment

    # --- Voting ---

    @pytest.mark.asyncio
    async def test_vote_for_included_workflow(self):
        agent = make_mock_agent("data_analyst", "DataAnalyst")
        workflows = [
            {"steps": [{"agent_id": "data_analyst", "role": "분석"}]},
            {"steps": [{"agent_id": "researcher", "role": "조사"}]}
        ]
        vote = await self.debate._ask_agent_to_vote(agent, workflows)
        assert vote.choice == "workflow_0"
        assert vote.confidence == 0.8

    @pytest.mark.asyncio
    async def test_vote_fallback_to_first(self):
        agent = make_mock_agent("unknown", "Unknown")
        workflows = [
            {"steps": [{"agent_id": "data_analyst", "role": "분석"}]}
        ]
        vote = await self.debate._ask_agent_to_vote(agent, workflows)
        assert vote.choice == "workflow_0"
        assert vote.confidence == 0.5

    # --- Workflow generation ---

    def test_generate_workflow_empty_proposals(self):
        workflows = self.debate._generate_workflow_options([])
        assert len(workflows) == 1
        assert workflows[0]["steps"] == []

    def test_generate_workflow_single_proposal(self):
        proposals = [
            AgentAnalysis(
                agent_id="data_analyst",
                understanding="test",
                relevance_score=0.8,
                can_contribute=True,
                proposed_role="분석"
            )
        ]
        workflows = self.debate._generate_workflow_options(proposals)
        assert len(workflows) >= 1
        assert workflows[0]["steps"][0]["agent_id"] == "data_analyst"

    def test_generate_workflow_multiple_proposals(self):
        proposals = [
            AgentAnalysis("researcher", "test", 0.6, True, "조사"),
            AgentAnalysis("data_analyst", "test", 0.9, True, "분석"),
            AgentAnalysis("writer", "test", 0.4, True, "작성"),
        ]
        workflows = self.debate._generate_workflow_options(proposals)
        # expertise_first: sorted by relevance desc
        assert workflows[0]["strategy"] == "expertise_first"
        assert workflows[0]["steps"][0]["agent_id"] == "data_analyst"

    def test_generate_workflow_logical_order_differs(self):
        proposals = [
            AgentAnalysis("writer", "test", 0.9, True, "작성"),
            AgentAnalysis("researcher", "test", 0.5, True, "조사"),
        ]
        workflows = self.debate._generate_workflow_options(proposals)
        # Should have 2 options if logical order differs
        if len(workflows) == 2:
            assert workflows[1]["strategy"] == "logical_flow"

    # --- Full debate flow ---

    @pytest.mark.asyncio
    async def test_full_debate_flow(self):
        """3개 에이전트로 전체 5-phase 토론 테스트"""
        agents = [
            make_mock_agent("data_analyst", "DataAnalyst"),
            make_mock_agent("researcher", "Researcher"),
            make_mock_agent("writer", "Writer"),
        ]

        result = await self.debate.start_debate(
            "데이터를 분석하고 조사해서 보고서를 작성해줘",
            agents
        )

        assert isinstance(result, DebateResult)
        assert result.consensus_reached is True
        assert len(result.participating_agents) > 0
        assert len(result.workflow) > 0
        assert len(result.debate_transcript) > 0

    @pytest.mark.asyncio
    async def test_debate_with_no_relevant_agents(self):
        """관련 없는 에이전트만 있을 때"""
        agents = [
            make_mock_agent("unknown1", "Unknown1"),
            make_mock_agent("unknown2", "Unknown2"),
        ]

        result = await self.debate.start_debate(
            "특수한 작업을 수행해줘",
            agents
        )

        assert isinstance(result, DebateResult)
        # Should still complete, possibly with empty workflow
        assert result.consensus_reached is True

    @pytest.mark.asyncio
    async def test_debate_single_agent(self):
        """단일 에이전트 토론"""
        agents = [
            make_mock_agent("data_analyst", "DataAnalyst"),
        ]

        result = await self.debate.start_debate(
            "데이터 분석해줘",
            agents
        )

        assert isinstance(result, DebateResult)
        assert result.consensus_reached is True

    @pytest.mark.asyncio
    async def test_debate_banking_scenario(self):
        """은행 도메인 토론"""
        agents = [
            make_mock_agent("loan_reviewer", "대출심사원"),
            make_mock_agent("risk_analyst", "리스크분석가"),
            make_mock_agent("compliance_officer", "준법감시인"),
        ]

        result = await self.debate.start_debate(
            "대출 심사 리스크 평가",
            agents
        )

        assert isinstance(result, DebateResult)
        assert result.consensus_reached is True
        assert len(result.participating_agents) > 0

    @pytest.mark.asyncio
    async def test_debate_transcript_recorded(self):
        """토론 과정이 transcript에 기록되는지 확인"""
        agents = [
            make_mock_agent("data_analyst", "DataAnalyst"),
            make_mock_agent("researcher", "Researcher"),
        ]

        result = await self.debate.start_debate(
            "데이터 조사 분석",
            agents
        )

        # Transcript should have entries from all phases
        assert len(result.debate_transcript) > 5
        messages = [t["message"] for t in result.debate_transcript]
        assert any("Phase 1" in m for m in messages)
        assert any("Phase 2" in m for m in messages)
        assert any("Phase 4" in m for m in messages)
        assert any("Phase 5" in m for m in messages)

    # --- Logging ---

    def test_log_appends_to_transcript(self):
        self.debate._log("Test message")
        assert len(self.debate.transcript) == 1
        assert "Test message" in self.debate.transcript[0]["message"]


# ============================================================
# Run Tests
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
