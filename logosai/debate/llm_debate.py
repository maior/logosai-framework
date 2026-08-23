"""
LLM-Based Debate System

SimpleDebateSystem의 Phase 1(쿼리 분석)을 LLM 기반으로 교체하여
키워드 매칭 대비 에이전트 선택 정확도를 향상시킵니다.

Usage:
    from logosai.debate import LLMDebateSystem

    debate = LLMDebateSystem(domain="banking")
    result = await debate.start_debate(query, agents)
"""

import asyncio
import json
from typing import List, Dict, Any, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from .debate_system import SimpleDebateSystem, AgentAnalysis
from .prompts import build_analysis_prompt

from ..utils.llm_client import LLMClient
from ..utils.text_utils import parse_llm_json


class LLMDebateSystem(SimpleDebateSystem):
    """LLM 기반 쿼리 분석을 사용하는 Debate System.

    SimpleDebateSystem을 상속하며, Phase 1(쿼리 분석)만 LLM으로 교체합니다.
    LLM 호출 실패 시 자동으로 키워드 기반 분석으로 폴백합니다.

    Args:
        provider: LLM 프로바이더 ("google", "openai", "anthropic", "ollama")
        model: 모델명 (기본: "gemini-2.5-flash-lite")
        temperature: 분석 일관성을 위해 낮은 값 권장 (기본: 0.1)
        domain: 도메인 지식 키 ("banking", "healthcare", "general", None=auto)
        timeout: LLM 호출 타임아웃 초 (기본: 30)

    Example:
        debate = LLMDebateSystem(domain="banking")
        result = await debate.start_debate(
            "고객이 5억원 주택담보대출을 신청했습니다.",
            agents
        )
    """

    def __init__(
        self,
        provider: str = "google",
        model: str = "gemini-2.5-flash-lite",
        temperature: float = 0.1,
        domain: Optional[str] = None,
        timeout: int = 30,
    ):
        super().__init__()
        self.llm_client = LLMClient(
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=2000,
        )
        self.domain = domain
        self.timeout = timeout
        self._initialized = False

    def _get_agent_info(self, agents: List[Any]) -> List[Dict[str, str]]:
        """에이전트 메타데이터를 LLM 프롬프트용 딕셔너리 리스트로 추출.

        Args:
            agents: LogosAIAgent 인스턴스 리스트

        Returns:
            [{"id": ..., "name": ..., "description": ...}, ...]
        """
        info = []
        for agent in agents:
            desc = ""
            if hasattr(agent, "config") and hasattr(agent.config, "description"):
                desc = agent.config.description
            elif hasattr(agent, "description"):
                desc = agent.description

            info.append({
                "id": agent.agent_id,
                "name": agent.name,
                "description": desc,
            })
        return info

    async def _ensure_initialized(self) -> None:
        """LLM 클라이언트 초기화 (최초 1회)."""
        if not self._initialized:
            await self.llm_client.initialize()
            self._initialized = True

    async def _phase_query_analysis(
        self,
        query: str,
        agents: List[Any],
    ) -> List[AgentAnalysis]:
        """Phase 1: LLM 기반 쿼리 분석.

        모든 에이전트의 메타데이터와 도메인 지식을 포함한 프롬프트로
        LLM을 1회 호출하여 각 에이전트의 관련도, 역할, 근거를 판단합니다.
        실패 시 키워드 기반 분석으로 자동 폴백합니다.
        """
        self._log("\n📊 Phase 1: LLM 기반 쿼리 분석")

        # 1. 에이전트 정보 수집
        agents_info = self._get_agent_info(agents)

        # 2. 프롬프트 조립
        prompt = build_analysis_prompt(query, agents_info, self.domain)

        # 3. LLM 호출
        try:
            await self._ensure_initialized()
            response = await asyncio.wait_for(
                self.llm_client.invoke(prompt),
                timeout=self.timeout,
            )

            # 4. JSON 파싱
            result = parse_llm_json(response.content)
            if not result or "agents" not in result:
                raise ValueError(f"Unexpected LLM response format: {response.content[:200]}")

            agent_scores = {a["id"]: a for a in result["agents"]}

        except Exception as e:
            self._log(f"  ⚠️ LLM 분석 실패: {e} — 키워드 기반 폴백")
            logger.warning(f"LLM debate analysis failed, falling back to keywords: {e}")
            return await super()._phase_query_analysis(query, agents)

        # 5. AgentAnalysis 객체 생성
        analyses = []
        for agent in agents:
            score_data = agent_scores.get(agent.agent_id, {})
            relevance = float(score_data.get("relevance_score", 0.0))
            can_contribute = bool(score_data.get("can_contribute", False))
            proposed_role = str(score_data.get("proposed_role", ""))
            reasoning = str(score_data.get("reasoning", ""))

            analysis = AgentAnalysis(
                agent_id=agent.agent_id,
                understanding=f"LLM 분석: {reasoning}",
                relevance_score=relevance,
                can_contribute=can_contribute,
                proposed_role=proposed_role,
                reasoning=reasoning,
            )
            analyses.append(analysis)

            self._log(
                f"  [{agent.name}] 관련도: {relevance:.2f}, "
                f"기여: {can_contribute}, 역할: {proposed_role}"
            )

        return analyses

    async def _ask_agent_for_role(
        self,
        agent: Any,
        query: str,
        analyses: List[AgentAnalysis],
    ) -> Dict[str, str]:
        """Phase 2: Phase 1에서 LLM이 이미 할당한 역할을 재사용.

        추가 LLM 호출 없이 Phase 1 결과의 proposed_role과 reasoning을 반환합니다.
        """
        for a in analyses:
            if a.agent_id == agent.agent_id and a.proposed_role:
                return {
                    "role": a.proposed_role,
                    "reasoning": a.reasoning,
                }
        return await super()._ask_agent_for_role(agent, query, analyses)
