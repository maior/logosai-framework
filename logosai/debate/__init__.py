"""
LogosAI Debate System - 에이전트 자율 토론 모듈
"""

from .debate_system import SimpleDebateSystem, DebateResult
from .voting import VotingSystem, Vote
from .llm_debate import LLMDebateSystem

__all__ = [
    'SimpleDebateSystem',
    'LLMDebateSystem',
    'DebateResult',
    'VotingSystem',
    'Vote',
]
