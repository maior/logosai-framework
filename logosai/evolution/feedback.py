"""
Feedback Collector (피드백 수집기)

다양한 소스에서 피드백을 수집하고 저장합니다.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from collections import defaultdict
import json
import hashlib

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from .types import Feedback, DetectedProblem


class FeedbackStore:
    """피드백 저장소 (인메모리)"""

    def __init__(self, max_entries: int = 10000):
        """
        저장소 초기화

        Args:
            max_entries: 최대 저장 개수
        """
        self.max_entries = max_entries
        self._feedbacks: Dict[str, List[Feedback]] = defaultdict(list)
        self._total_count = 0

    async def save(self, feedback: Feedback) -> str:
        """
        피드백 저장

        Args:
            feedback: 저장할 피드백

        Returns:
            피드백 ID
        """
        feedback_id = self._generate_id(feedback)
        self._feedbacks[feedback.agent_id].append(feedback)
        self._total_count += 1

        # 용량 초과 시 오래된 것부터 제거
        if self._total_count > self.max_entries:
            self._cleanup_oldest()

        return feedback_id

    async def get_by_agent(
        self,
        agent_id: str,
        limit: int = 100,
        since: Optional[datetime] = None
    ) -> List[Feedback]:
        """
        에이전트별 피드백 조회

        Args:
            agent_id: 에이전트 ID
            limit: 최대 조회 개수
            since: 이 시간 이후 피드백만

        Returns:
            피드백 리스트
        """
        feedbacks = self._feedbacks.get(agent_id, [])

        if since:
            feedbacks = [f for f in feedbacks if f.timestamp >= since]

        return feedbacks[-limit:]

    async def get_negative(
        self,
        agent_id: Optional[str] = None,
        limit: int = 50
    ) -> List[Feedback]:
        """
        부정적 피드백 조회

        Args:
            agent_id: 에이전트 ID (None이면 전체)
            limit: 최대 조회 개수

        Returns:
            부정적 피드백 리스트
        """
        if agent_id:
            feedbacks = self._feedbacks.get(agent_id, [])
        else:
            feedbacks = [f for flist in self._feedbacks.values() for f in flist]

        negative = [f for f in feedbacks if not f.is_positive]
        return negative[-limit:]

    def get_statistics(self, agent_id: Optional[str] = None) -> dict:
        """통계 조회"""
        if agent_id:
            feedbacks = self._feedbacks.get(agent_id, [])
        else:
            feedbacks = [f for flist in self._feedbacks.values() for f in flist]

        if not feedbacks:
            return {"total": 0}

        positive_count = sum(1 for f in feedbacks if f.is_positive)
        avg_intent_score = sum(f.intent_match_score for f in feedbacks) / len(feedbacks)
        avg_quality_score = sum(f.quality_score for f in feedbacks) / len(feedbacks)

        return {
            "total": len(feedbacks),
            "positive_count": positive_count,
            "negative_count": len(feedbacks) - positive_count,
            "positive_rate": positive_count / len(feedbacks),
            "avg_intent_score": avg_intent_score,
            "avg_quality_score": avg_quality_score
        }

    def _generate_id(self, feedback: Feedback) -> str:
        """피드백 ID 생성"""
        content = f"{feedback.agent_id}:{feedback.query}:{feedback.timestamp.isoformat()}"
        return hashlib.md5(content.encode()).hexdigest()[:16]

    def _cleanup_oldest(self) -> None:
        """가장 오래된 피드백 제거"""
        all_feedbacks = []
        for agent_id, flist in self._feedbacks.items():
            for f in flist:
                all_feedbacks.append((agent_id, f))

        # 시간순 정렬
        all_feedbacks.sort(key=lambda x: x[1].timestamp)

        # 10% 제거
        remove_count = max(1, self.max_entries // 10)
        to_remove = all_feedbacks[:remove_count]

        for agent_id, feedback in to_remove:
            self._feedbacks[agent_id].remove(feedback)
            self._total_count -= 1


class FeedbackCollector:
    """피드백 수집기"""

    def __init__(self, store: Optional[FeedbackStore] = None):
        """
        수집기 초기화

        Args:
            store: 피드백 저장소 (None이면 새로 생성)
        """
        self.store = store or FeedbackStore()
        self._pending_analysis: List[str] = []  # 분석 대기 중인 에이전트 ID

    async def collect(
        self,
        agent_id: str,
        query: str,
        response: Any,
        explicit_feedback: Optional[str] = None,
        implicit_signals: Optional[Dict[str, Any]] = None,
        detected_problems: Optional[List[DetectedProblem]] = None
    ) -> Feedback:
        """
        피드백 수집

        Args:
            agent_id: 에이전트 ID
            query: 사용자 쿼리
            response: 에이전트 응답
            explicit_feedback: 명시적 피드백 (좋아요/싫어요, 코멘트)
            implicit_signals: 암묵적 신호 (재시도 여부, 세션 종료 등)
            detected_problems: 감지된 문제들

        Returns:
            생성된 피드백 객체
        """
        # 응답 요약
        response_summary = self._summarize_response(response)

        # 긍정/부정 판단
        is_positive = self._determine_positivity(
            explicit_feedback, implicit_signals, detected_problems
        )

        # 품질 점수 계산
        intent_score, quality_score = self._calculate_scores(
            response, implicit_signals, detected_problems
        )

        feedback = Feedback(
            agent_id=agent_id,
            query=query,
            response_summary=response_summary,
            is_positive=is_positive,
            explicit_feedback=explicit_feedback,
            implicit_signals=implicit_signals,
            intent_match_score=intent_score,
            quality_score=quality_score
        )

        # 저장
        await self.store.save(feedback)

        # 부정적 피드백이면 분석 대기열에 추가
        if not is_positive and agent_id not in self._pending_analysis:
            self._pending_analysis.append(agent_id)

        logger.debug(
            f"피드백 수집: agent={agent_id}, positive={is_positive}, "
            f"intent={intent_score:.2f}, quality={quality_score:.2f}"
        )

        return feedback

    async def collect_explicit(
        self,
        agent_id: str,
        query: str,
        response: Any,
        rating: int,  # 1-5
        comment: Optional[str] = None
    ) -> Feedback:
        """
        명시적 피드백 수집 (별점 형태)

        Args:
            agent_id: 에이전트 ID
            query: 사용자 쿼리
            response: 에이전트 응답
            rating: 평점 (1-5)
            comment: 코멘트

        Returns:
            피드백 객체
        """
        explicit_feedback = f"Rating: {rating}/5"
        if comment:
            explicit_feedback += f", Comment: {comment}"

        return await self.collect(
            agent_id=agent_id,
            query=query,
            response=response,
            explicit_feedback=explicit_feedback,
            implicit_signals={"rating": rating}
        )

    async def record_retry(
        self,
        agent_id: str,
        original_query: str,
        retry_query: str,
        original_response: Any
    ) -> None:
        """
        재시도 기록 (암묵적 부정 신호)

        Args:
            agent_id: 에이전트 ID
            original_query: 원래 쿼리
            retry_query: 재시도 쿼리
            original_response: 원래 응답
        """
        await self.collect(
            agent_id=agent_id,
            query=original_query,
            response=original_response,
            implicit_signals={
                "is_retry": True,
                "retry_query": retry_query
            }
        )

    async def get_feedback_history(
        self,
        agent_id: str,
        days: int = 7
    ) -> List[Feedback]:
        """
        피드백 이력 조회

        Args:
            agent_id: 에이전트 ID
            days: 조회 기간 (일)

        Returns:
            피드백 리스트
        """
        since = datetime.now() - timedelta(days=days)
        return await self.store.get_by_agent(agent_id, since=since)

    async def get_agents_needing_analysis(self) -> List[str]:
        """
        분석이 필요한 에이전트 목록

        Returns:
            에이전트 ID 리스트
        """
        agents = self._pending_analysis.copy()
        self._pending_analysis.clear()
        return agents

    def get_statistics(self, agent_id: Optional[str] = None) -> dict:
        """통계 조회"""
        return self.store.get_statistics(agent_id)

    def _summarize_response(self, response: Any) -> str:
        """응답 요약"""
        if isinstance(response, str):
            text = response
        elif hasattr(response, "content"):
            text = str(response.content)
        elif isinstance(response, dict):
            text = str(response.get("content", response.get("message", str(response))))
        else:
            text = str(response)

        # 최대 500자로 제한
        if len(text) > 500:
            return text[:497] + "..."
        return text

    def _determine_positivity(
        self,
        explicit: Optional[str],
        implicit: Optional[Dict],
        problems: Optional[List[DetectedProblem]]
    ) -> bool:
        """긍정/부정 판단"""
        # 문제가 감지되면 부정
        if problems and len(problems) > 0:
            return False

        # 명시적 피드백 분석
        if explicit:
            negative_keywords = ["bad", "wrong", "틀", "잘못", "아니", "싫", "최악"]
            if any(kw in explicit.lower() for kw in negative_keywords):
                return False

            # Rating 추출
            if "Rating:" in explicit:
                try:
                    rating = int(explicit.split("Rating:")[1].split("/")[0].strip())
                    return rating >= 3
                except:
                    pass

        # 암묵적 신호 분석
        if implicit:
            if implicit.get("is_retry", False):
                return False
            if implicit.get("session_abandoned", False):
                return False
            rating = implicit.get("rating")
            if rating is not None and rating < 3:
                return False

        return True  # 기본값: 긍정

    def _calculate_scores(
        self,
        response: Any,
        implicit: Optional[Dict],
        problems: Optional[List[DetectedProblem]]
    ) -> tuple:
        """점수 계산 (intent_score, quality_score)"""
        intent_score = 1.0
        quality_score = 1.0

        # 문제 기반 감점
        if problems:
            for p in problems:
                if p.problem_type.value == "intent_mismatch":
                    intent_score = min(intent_score, p.details.get("score", 0.5))
                elif p.problem_type.value in ["syntax_error", "runtime_error"]:
                    quality_score -= 0.3
                else:
                    quality_score -= 0.1

        # 암묵적 신호 기반 조정
        if implicit:
            if implicit.get("is_retry"):
                intent_score -= 0.2
            rating = implicit.get("rating")
            if rating:
                quality_score = (quality_score + rating / 5) / 2

        return (
            max(0.0, min(1.0, intent_score)),
            max(0.0, min(1.0, quality_score))
        )
