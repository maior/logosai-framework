"""
LogosAI Simple Debate System - MVP 버전
에이전트들이 자율적으로 토론하여 역할을 결정하는 간단한 시스템
"""

import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

from .voting import VotingSystem, Vote


@dataclass
class AgentAnalysis:
    """에이전트의 쿼리 분석 결과"""
    agent_id: str
    understanding: str
    relevance_score: float  # 0.0 ~ 1.0
    can_contribute: bool
    proposed_role: Optional[str] = None
    reasoning: str = ""


@dataclass
class DebateResult:
    """토론 결과"""
    query: str
    workflow: List[Dict[str, Any]]
    participating_agents: List[str]
    debate_transcript: List[Dict[str, Any]] = field(default_factory=list)
    consensus_reached: bool = True
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class SimpleDebateSystem:
    """
    간단한 에이전트 토론 시스템

    프로세스:
    1. 쿼리 분석: 모든 에이전트가 쿼리 분석
    2. 역할 제안: 각 에이전트가 자신의 역할 제안
    3. 토론: 제안에 대해 간단히 의견 교환
    4. 투표: 워크플로우 투표
    5. 합의: 최종 결정
    """

    def __init__(self):
        self.voting_system = VotingSystem()
        self.transcript = []

    async def start_debate(
        self,
        query: str,
        agents: List[Any]  # LogosAIAgent 인스턴스들
    ) -> DebateResult:
        """
        토론 시작

        Args:
            query: 사용자 쿼리
            agents: 참여 가능한 에이전트 리스트

        Returns:
            토론 결과
        """
        self.transcript = []
        self._log(f"🎬 토론 시작: '{query}'")
        self._log(f"📋 참여 에이전트: {[a.name for a in agents]}")

        # Phase 1: 쿼리 분석
        analyses = await self._phase_query_analysis(query, agents)

        # Phase 2: 역할 제안
        proposals = await self._phase_role_proposal(query, analyses, agents)

        # Phase 3: 간단한 토론
        refined_proposals = await self._phase_discussion(proposals, agents)

        # Phase 4: 투표
        workflow = await self._phase_voting(refined_proposals, agents)

        # Phase 5: 합의
        final_result = self._phase_consensus(workflow, refined_proposals)

        return DebateResult(
            query=query,
            workflow=final_result["workflow"],
            participating_agents=final_result["participants"],
            debate_transcript=self.transcript,
            consensus_reached=final_result["consensus"]
        )

    async def _phase_query_analysis(
        self,
        query: str,
        agents: List[Any]
    ) -> List[AgentAnalysis]:
        """Phase 1: 모든 에이전트가 쿼리 분석"""
        self._log("\n📊 Phase 1: 쿼리 분석")

        analyses = []

        for agent in agents:
            # 에이전트에게 쿼리 분석 요청
            analysis = await self._ask_agent_to_analyze(agent, query)
            analyses.append(analysis)

            self._log(f"  [{agent.name}] 관련도: {analysis.relevance_score:.2f}, "
                     f"기여 가능: {analysis.can_contribute}")

        return analyses

    async def _phase_role_proposal(
        self,
        query: str,
        analyses: List[AgentAnalysis],
        agents: List[Any]
    ) -> List[AgentAnalysis]:
        """Phase 2: 각 에이전트가 자신의 역할 제안"""
        self._log("\n💡 Phase 2: 역할 제안")

        proposals = []

        for agent, analysis in zip(agents, analyses):
            if analysis.can_contribute:
                # 역할 제안 받기
                proposal = await self._ask_agent_for_role(agent, query, analyses)
                analysis.proposed_role = proposal["role"]
                analysis.reasoning = proposal["reasoning"]
                proposals.append(analysis)

                self._log(f"  [{agent.name}] 역할: {proposal['role']}")
                self._log(f"    이유: {proposal['reasoning']}")

        return proposals

    async def _phase_discussion(
        self,
        proposals: List[AgentAnalysis],
        agents: List[Any]
    ) -> List[AgentAnalysis]:
        """Phase 3: 간단한 토론 (MVP에서는 1라운드만)"""
        self._log("\n💬 Phase 3: 토론")

        # 각 에이전트가 다른 제안에 대해 간단히 코멘트
        for agent in agents:
            if any(p.agent_id == agent.agent_id for p in proposals):
                comment = await self._ask_agent_for_comment(agent, proposals)
                self._log(f"  [{agent.name}] {comment}")

        return proposals

    async def _phase_voting(
        self,
        proposals: List[AgentAnalysis],
        agents: List[Any]
    ) -> Dict[str, Any]:
        """Phase 4: 워크플로우 투표"""
        self._log("\n🗳️  Phase 4: 투표")

        # 가능한 워크플로우 생성
        workflows = self._generate_workflow_options(proposals)

        self._log(f"  후보 워크플로우 {len(workflows)}개 생성")

        # 각 워크플로우 옵션 설명
        for i, workflow in enumerate(workflows):
            self._log(f"\n  📋 Workflow {i}: {workflow['description']}")
            self._log(f"     이유: {workflow.get('reasoning', 'N/A')}")
            self._log(f"     순서: {' → '.join([step['agent_id'] for step in workflow['steps']])}")

        # 투표
        self.voting_system.reset()

        self._log(f"\n  🗳️  투표 진행:")
        for agent in agents:
            vote = await self._ask_agent_to_vote(agent, workflows)
            self.voting_system.cast_vote(vote)
            self._log(f"  [{agent.name}] 투표: {vote.choice} (확신도: {vote.confidence:.2f}) - {vote.reasoning}")

        # 집계
        result = self.voting_system.count_votes()
        winner_idx = int(result["winner"].replace("workflow_", ""))
        winner_workflow = workflows[winner_idx]

        self._log(f"\n✅ 선택된 워크플로우: {result['winner']}")
        self._log(f"   전략: {winner_workflow.get('strategy', 'N/A')}")
        self._log(f"   선택 이유: {winner_workflow.get('reasoning', 'N/A')}")

        return winner_workflow

    def _phase_consensus(
        self,
        workflow: Dict[str, Any],
        proposals: List[AgentAnalysis]
    ) -> Dict[str, Any]:
        """Phase 5: 합의 확정"""
        self._log("\n🎯 Phase 5: 합의 확정")

        participating_agents = [
            step["agent_id"] for step in workflow["steps"]
        ]

        self._log(f"  참여 에이전트: {participating_agents}")
        self._log(f"  실행 순서: {' → '.join([step['role'] for step in workflow['steps']])}")

        return {
            "workflow": workflow["steps"],
            "participants": participating_agents,
            "consensus": True
        }

    # ========== 에이전트 상호작용 헬퍼 메서드 ==========

    async def _ask_agent_to_analyze(
        self,
        agent: Any,
        query: str
    ) -> AgentAnalysis:
        """에이전트에게 쿼리 분석 요청 (간단한 휴리스틱)"""

        # MVP: 간단한 키워드 매칭으로 관련도 계산
        # 실제로는 LLM 호출해서 분석하면 됨

        agent_keywords = self._get_agent_keywords(agent)
        query_lower = query.lower()

        # 키워드 매칭
        relevance = 0.0
        for keyword in agent_keywords:
            if keyword.lower() in query_lower:
                relevance += 0.3

        relevance = min(relevance, 1.0)

        can_contribute = relevance > 0.2

        return AgentAnalysis(
            agent_id=agent.agent_id,
            understanding=f"'{query}' 쿼리 분석 완료",
            relevance_score=relevance,
            can_contribute=can_contribute
        )

    async def _ask_agent_for_role(
        self,
        agent: Any,
        query: str,
        analyses: List[AgentAnalysis]
    ) -> Dict[str, str]:
        """에이전트에게 역할 제안 요청"""

        # MVP: 에이전트 타입에 따라 역할 할당
        role_map = {
            "data_analyst": "데이터 분석 담당",
            "researcher": "정보 조사 담당",
            "writer": "문서 작성 담당"
        }

        role = role_map.get(agent.agent_id, "보조 담당")
        reasoning = f"{agent.name}의 전문성을 활용하여 {role}"

        return {
            "role": role,
            "reasoning": reasoning
        }

    async def _ask_agent_for_comment(
        self,
        agent: Any,
        proposals: List[AgentAnalysis]
    ) -> str:
        """에이전트에게 다른 제안에 대한 의견 요청"""

        # MVP: 간단한 코멘트
        other_proposals = [p for p in proposals if p.agent_id != agent.agent_id]

        if other_proposals:
            return f"다른 에이전트들의 역할 제안에 동의합니다."
        else:
            return "제 역할을 충실히 수행하겠습니다."

    async def _ask_agent_to_vote(
        self,
        agent: Any,
        workflows: List[Dict[str, Any]]
    ) -> Vote:
        """에이전트에게 워크플로우 투표 요청"""

        # MVP: 자신이 포함된 워크플로우에 투표
        for i, workflow in enumerate(workflows):
            agent_ids = [step["agent_id"] for step in workflow["steps"]]
            if agent.agent_id in agent_ids:
                return Vote(
                    voter_id=agent.agent_id,
                    choice=f"workflow_{i}",
                    reasoning=f"내가 참여하는 워크플로우",
                    confidence=0.8
                )

        # 자신이 없으면 첫 번째에 투표
        return Vote(
            voter_id=agent.agent_id,
            choice="workflow_0",
            reasoning="기본 워크플로우 선택",
            confidence=0.5
        )

    # ========== 유틸리티 메서드 ==========

    def _get_agent_keywords(self, agent: Any) -> List[str]:
        """에이전트의 키워드 추출"""
        keyword_map = {
            # Demo agents
            "data_analyst": ["데이터", "분석", "통계", "차트"],
            "researcher": ["조사", "검색", "정보", "연구"],
            "writer": ["작성", "문서", "보고서", "글"],
            # Banking agents
            "loan_reviewer": ["대출", "신용", "담보", "심사", "승인", "여신", "채무", "상환", "이자", "한도"],
            "fraud_detector": ["이상거래", "사기", "FDS", "보안", "의심", "부정", "탐지", "모니터링", "위험거래"],
            "compliance_officer": ["규제", "준법", "법규", "컴플라이언스", "감독", "금융당국", "제재", "위반", "감사"],
            "risk_analyst": ["리스크", "위험", "평가", "분석", "측정", "VaR", "손실", "변동성", "익스포저"],
            "customer_service": ["고객", "상담", "문의", "불만", "안내", "응대", "서비스", "민원", "요청"]
        }
        return keyword_map.get(agent.agent_id, [])

    def _generate_workflow_options(
        self,
        proposals: List[AgentAnalysis]
    ) -> List[Dict[str, Any]]:
        """제안을 바탕으로 워크플로우 후보 생성"""

        if not proposals:
            return [{"steps": [], "description": "빈 워크플로우", "reasoning": "참여 가능한 에이전트 없음"}]

        # MVP: 간단한 순차 워크플로우만 생성
        workflows = []

        # Option 1: 관련도 순으로 정렬 (높은 전문성 우선)
        sorted_by_relevance = sorted(
            proposals,
            key=lambda p: p.relevance_score,
            reverse=True
        )

        workflows.append({
            "steps": [
                {
                    "agent_id": p.agent_id,
                    "role": p.proposed_role,
                    "order": i,
                    "relevance": p.relevance_score
                }
                for i, p in enumerate(sorted_by_relevance)
            ],
            "description": "전문성 우선 순차 실행",
            "reasoning": f"가장 관련도 높은 '{sorted_by_relevance[0].agent_id}'부터 시작하여 순차 처리",
            "strategy": "expertise_first"
        })

        # Option 2: 역할 기반 논리적 순서
        # 논리적 순서 정의 (은행 업무 기준)
        logical_order = {
            # 고객 응대 관련
            "customer_service": 10,
            # 분석/검토 관련
            "fraud_detector": 20,
            "risk_analyst": 30,
            "loan_reviewer": 40,
            # 승인/감독 관련
            "compliance_officer": 50,
            # 기타 (demo agents)
            "researcher": 15,
            "data_analyst": 25,
            "writer": 60
        }

        sorted_by_logic = sorted(
            proposals,
            key=lambda p: logical_order.get(p.agent_id, 100)
        )

        if sorted_by_logic != sorted_by_relevance:
            workflows.append({
                "steps": [
                    {
                        "agent_id": p.agent_id,
                        "role": p.proposed_role,
                        "order": i,
                        "relevance": p.relevance_score
                    }
                    for i, p in enumerate(sorted_by_logic)
                ],
                "description": "업무 논리 순서 기반 실행",
                "reasoning": f"업무 프로세스 순서에 따라 '{sorted_by_logic[0].agent_id}'부터 '{sorted_by_logic[-1].agent_id}'까지 처리",
                "strategy": "logical_flow"
            })

        return workflows

    def _log(self, message: str) -> None:
        """토론 과정 로깅"""
        from loguru import logger
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        logger.info(entry)
        self.transcript.append({
            "timestamp": timestamp,
            "message": message
        })
