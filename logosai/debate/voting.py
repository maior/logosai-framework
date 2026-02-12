"""
LogosAI Voting System - 에이전트 투표 메커니즘
"""

from typing import List, Dict, Any
from dataclasses import dataclass
from collections import Counter


@dataclass
class Vote:
    """투표"""
    voter_id: str
    choice: str
    reasoning: str
    confidence: float = 1.0


class VotingSystem:
    """간단한 투표 시스템"""

    def __init__(self):
        self.votes: List[Vote] = []

    def cast_vote(self, vote: Vote) -> None:
        """투표하기"""
        self.votes.append(vote)

    def count_votes(self) -> Dict[str, Any]:
        """투표 집계"""
        if not self.votes:
            return {"winner": None, "votes": {}}

        # 단순 다수결
        choices = [v.choice for v in self.votes]
        vote_counts = Counter(choices)

        # 가중치 적용 (confidence 고려)
        weighted_scores = {}
        for vote in self.votes:
            if vote.choice not in weighted_scores:
                weighted_scores[vote.choice] = 0
            weighted_scores[vote.choice] += vote.confidence

        winner = max(weighted_scores.items(), key=lambda x: x[1])[0]

        return {
            "winner": winner,
            "votes": dict(vote_counts),
            "weighted_scores": weighted_scores,
            "total_votes": len(self.votes)
        }

    def reset(self) -> None:
        """투표 초기화"""
        self.votes = []
