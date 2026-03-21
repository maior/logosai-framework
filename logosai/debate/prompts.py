"""
LLM Debate System — 프롬프트 모듈

도메인 지식과 분석 프롬프트를 관리합니다.
"""

import json
from typing import List, Dict, Any, Optional


SYSTEM_PROMPT = (
    "You are an intelligent multi-agent orchestrator. "
    "Your job is to analyze a user query and determine which agents should participate "
    "and what role each should play."
)

DOMAIN_KNOWLEDGE = {
    "banking": (
        "In financial/banking workflows, consider the FULL business process, "
        "not just the surface-level request:\n"
        "- Loan applications require: credit review + risk assessment + regulatory compliance check\n"
        "- Fraud/suspicious transactions require: fraud detection + risk assessment + customer verification\n"
        "- New financial products require: regulatory compliance + risk assessment\n"
        "- Customer complaints about financial decisions require: customer service + review of original decision + compliance check\n"
        "- Portfolio risk management requires: risk analysis + loan review + compliance reporting\n"
        "- When in doubt about compliance, INCLUDE the compliance agent — financial regulations apply to most banking operations\n"
        "- Think about who needs to SIGN OFF on the result, not just who does the primary work"
    ),
    "healthcare": (
        "In healthcare workflows, consider patient safety and regulatory requirements:\n"
        "- Diagnosis requires: specialist assessment + medical history review\n"
        "- Treatment plans require: specialist + pharmacy review + patient consent\n"
        "- Always include compliance for regulated procedures"
    ),
    "general": (
        "Consider the full task pipeline:\n"
        "- Who does the primary work?\n"
        "- Who provides supporting input?\n"
        "- Who needs to review or validate the result?\n"
        "- Include only agents that add clear value"
    ),
}


def build_analysis_prompt(
    query: str,
    agents_info: List[Dict[str, str]],
    domain: Optional[str] = None,
) -> str:
    """Phase 1 분석 프롬프트를 조립합니다.

    Args:
        query: 사용자 쿼리
        agents_info: [{"id": ..., "name": ..., "description": ...}, ...]
        domain: 도메인 키 ("banking", "healthcare", "general", None)

    Returns:
        LLM에 전달할 프롬프트 문자열
    """
    domain_section = ""
    if domain and domain in DOMAIN_KNOWLEDGE:
        domain_section = f"\n## Domain Knowledge (Important)\n{DOMAIN_KNOWLEDGE[domain]}"
    elif domain is None:
        # auto: include general knowledge
        domain_section = f"\n## Domain Knowledge\n{DOMAIN_KNOWLEDGE['general']}"

    agents_json = json.dumps(agents_info, ensure_ascii=False, indent=2)

    return f"""{SYSTEM_PROMPT}

## User Query
"{query}"

## Available Agents
{agents_json}
{domain_section}

## Instructions
For each agent, determine:
1. relevance_score (0.0 to 1.0): How relevant is this agent to the query?
2. can_contribute (true/false): Should this agent participate?
3. proposed_role: What specific role should this agent play for this query?
4. reasoning: Brief explanation (1 sentence)

Rules:
- Only agents directly relevant to the query should have high scores (>0.5)
- An agent with relevance < 0.3 should have can_contribute: false
- Consider the agent's description carefully

## Output Format (JSON only, no markdown)
{{"agents": [
  {{"id": "agent_id", "relevance_score": 0.85, "can_contribute": true, "proposed_role": "role description", "reasoning": "why"}}
]}}"""
