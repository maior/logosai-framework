"""
Pattern Learner (패턴 학습기)

수집된 피드백에서 문제 패턴을 학습합니다.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
from collections import defaultdict
import hashlib
import re

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from .types import (
    Feedback,
    LearnedPattern,
    DetectedProblem,
    ProblemType
)
from .config import LearningConfig


class PatternLearner:
    """패턴 학습기"""

    def __init__(
        self,
        config: Optional[LearningConfig] = None,
        llm_client=None
    ):
        """
        학습기 초기화

        Args:
            config: 학습 설정
            llm_client: LLM 클라이언트 (패턴 분석용)
        """
        self.config = config or LearningConfig()
        self.llm_client = llm_client

        # 학습된 패턴 저장
        self._patterns: Dict[str, LearnedPattern] = {}

        # 쿼리 유형별 피드백 그룹
        self._query_groups: Dict[str, List[Feedback]] = defaultdict(list)

    async def learn_from_feedback(
        self,
        feedbacks: List[Feedback]
    ) -> List[LearnedPattern]:
        """
        피드백에서 패턴 학습

        Args:
            feedbacks: 피드백 리스트

        Returns:
            새로 학습된 패턴 리스트
        """
        new_patterns = []

        # 1. 쿼리 유형별로 그룹화
        for feedback in feedbacks:
            query_type = self._classify_query_type(feedback.query)
            self._query_groups[query_type].append(feedback)

        # 2. 각 그룹에서 반복 패턴 감지
        for query_type, group_feedbacks in self._query_groups.items():
            # 최소 샘플 수 확인
            if len(group_feedbacks) < self.config.min_samples_for_pattern:
                continue

            # 부정적 피드백 비율 확인
            negative_feedbacks = [f for f in group_feedbacks if not f.is_positive]
            negative_rate = len(negative_feedbacks) / len(group_feedbacks)

            if negative_rate >= 0.3:  # 30% 이상 부정적이면 패턴으로 인식
                pattern = await self._create_pattern(
                    query_type, group_feedbacks, negative_feedbacks
                )

                if pattern and pattern.confidence >= self.config.pattern_confidence_threshold:
                    self._add_pattern(pattern)
                    new_patterns.append(pattern)

        logger.info(f"패턴 학습 완료: {len(new_patterns)}개 새 패턴")
        return new_patterns

    async def learn_from_problems(
        self,
        problems: List[DetectedProblem]
    ) -> List[LearnedPattern]:
        """
        감지된 문제에서 패턴 학습

        Args:
            problems: 감지된 문제 리스트

        Returns:
            학습된 패턴 리스트
        """
        new_patterns = []

        # 문제 유형별 그룹화
        problem_groups: Dict[ProblemType, List[DetectedProblem]] = defaultdict(list)
        for p in problems:
            problem_groups[p.problem_type].append(p)

        for problem_type, group in problem_groups.items():
            if len(group) >= self.config.min_samples_for_pattern:
                pattern = await self._create_pattern_from_problems(problem_type, group)
                if pattern:
                    self._add_pattern(pattern)
                    new_patterns.append(pattern)

        return new_patterns

    def get_matching_patterns(
        self,
        query: str,
        problem: Optional[DetectedProblem] = None
    ) -> List[LearnedPattern]:
        """
        쿼리/문제와 일치하는 패턴 조회

        Args:
            query: 사용자 쿼리
            problem: 감지된 문제 (선택)

        Returns:
            일치하는 패턴 리스트
        """
        matching = []
        query_type = self._classify_query_type(query)

        for pattern in self._patterns.values():
            # 쿼리 유형 일치 확인
            if pattern.query_type == query_type:
                matching.append(pattern)
                continue

            # 문제 유형 일치 확인
            if problem and pattern.problem_type == problem.problem_type:
                matching.append(pattern)

        # 신뢰도 순으로 정렬
        matching.sort(key=lambda p: p.confidence, reverse=True)
        return matching

    def get_all_patterns(self) -> List[LearnedPattern]:
        """모든 학습된 패턴 조회"""
        return list(self._patterns.values())

    def get_pattern(self, pattern_id: str) -> Optional[LearnedPattern]:
        """특정 패턴 조회"""
        return self._patterns.get(pattern_id)

    def update_pattern_confidence(
        self,
        pattern_id: str,
        success: bool
    ) -> None:
        """
        패턴 신뢰도 업데이트

        Args:
            pattern_id: 패턴 ID
            success: 패턴 적용 성공 여부
        """
        pattern = self._patterns.get(pattern_id)
        if not pattern:
            return

        # 지수 이동 평균으로 신뢰도 조정
        alpha = 0.3
        if success:
            pattern.confidence = pattern.confidence + alpha * (1.0 - pattern.confidence)
        else:
            pattern.confidence = pattern.confidence - alpha * pattern.confidence

        pattern.frequency += 1
        pattern.updated_at = datetime.now()

        logger.debug(
            f"패턴 신뢰도 업데이트: {pattern_id} → {pattern.confidence:.2f}"
        )

    def remove_pattern(self, pattern_id: str) -> bool:
        """패턴 제거"""
        if pattern_id in self._patterns:
            del self._patterns[pattern_id]
            return True
        return False

    def get_statistics(self) -> dict:
        """통계 조회"""
        patterns = list(self._patterns.values())

        if not patterns:
            return {"total_patterns": 0}

        return {
            "total_patterns": len(patterns),
            "avg_confidence": sum(p.confidence for p in patterns) / len(patterns),
            "avg_frequency": sum(p.frequency for p in patterns) / len(patterns),
            "by_problem_type": self._count_by_problem_type(patterns),
            "by_fix_type": self._count_by_fix_type(patterns)
        }

    async def _create_pattern(
        self,
        query_type: str,
        all_feedbacks: List[Feedback],
        negative_feedbacks: List[Feedback]
    ) -> Optional[LearnedPattern]:
        """피드백에서 패턴 생성"""
        pattern_id = self._generate_pattern_id(query_type)

        # 공통 문제 추출
        common_issues = self._extract_common_issues(negative_feedbacks)

        # 수정 유형 결정
        fix_type = self._suggest_fix_type(common_issues, negative_feedbacks)

        # 예시 수집
        examples = [
            {"query": f.query, "response": f.response_summary[:200]}
            for f in negative_feedbacks[:5]
        ]

        # 신뢰도 계산
        negative_rate = len(negative_feedbacks) / len(all_feedbacks)
        base_confidence = min(0.9, negative_rate + 0.3)

        # LLM으로 패턴 분석 (선택적)
        if self.llm_client and len(negative_feedbacks) >= 3:
            analysis = await self._analyze_pattern_with_llm(
                query_type, common_issues, examples
            )
            if analysis:
                common_issues = analysis.get("issues", common_issues)
                base_confidence = analysis.get("confidence", base_confidence)

        # 기존 패턴 확인
        existing = self._patterns.get(pattern_id)
        if existing:
            existing.frequency += len(negative_feedbacks)
            existing.common_issues = list(set(existing.common_issues + common_issues))
            existing.updated_at = datetime.now()
            return None  # 업데이트만 했으므로 새 패턴 없음

        return LearnedPattern(
            pattern_id=pattern_id,
            query_type=query_type,
            problem_type=ProblemType.INTENT_MISMATCH,  # 기본값
            frequency=len(negative_feedbacks),
            common_issues=common_issues,
            suggested_fix_type=fix_type,
            confidence=base_confidence,
            examples=examples
        )

    async def _create_pattern_from_problems(
        self,
        problem_type: ProblemType,
        problems: List[DetectedProblem]
    ) -> Optional[LearnedPattern]:
        """문제에서 패턴 생성"""
        pattern_id = f"problem_{problem_type.value}_{len(self._patterns)}"

        common_issues = list(set(p.description for p in problems))[:5]

        fix_type_map = {
            ProblemType.SYNTAX_ERROR: "code_fix",
            ProblemType.IMPORT_ERROR: "code_fix",
            ProblemType.TYPE_ERROR: "code_fix",
            ProblemType.RUNTIME_ERROR: "code_fix",
            ProblemType.MISSING_FUNCTION: "new_function",
            ProblemType.INTENT_MISMATCH: "prompt_update",
            ProblemType.LOW_QUALITY: "prompt_update",
        }

        fix_type = fix_type_map.get(problem_type, "prompt_update")

        examples = [
            {
                "query": p.query or "",
                "error": p.error_message or p.description
            }
            for p in problems[:5]
        ]

        return LearnedPattern(
            pattern_id=pattern_id,
            query_type=f"error_{problem_type.value}",
            problem_type=problem_type,
            frequency=len(problems),
            common_issues=common_issues,
            suggested_fix_type=fix_type,
            confidence=0.7,  # 에러 기반은 기본 신뢰도 0.7
            examples=examples
        )

    def _classify_query_type(self, query: str) -> str:
        """쿼리 유형 분류 (간단한 키워드 기반)"""
        query_lower = query.lower()

        # 일정 관련
        if any(kw in query_lower for kw in ["일정", "스케줄", "약속", "calendar"]):
            if any(kw in query_lower for kw in ["월", "month"]):
                return "schedule_month"
            elif any(kw in query_lower for kw in ["주", "week"]):
                return "schedule_week"
            else:
                return "schedule_day"

        # 검색 관련
        if any(kw in query_lower for kw in ["검색", "찾아", "search", "find"]):
            return "search"

        # 계산 관련
        if any(kw in query_lower for kw in ["계산", "calculate", "환율", "변환"]):
            return "calculation"

        # 날씨 관련
        if any(kw in query_lower for kw in ["날씨", "weather", "기온"]):
            return "weather"

        return "general"

    def _extract_common_issues(self, feedbacks: List[Feedback]) -> List[str]:
        """공통 문제 추출"""
        issues = []

        # 명시적 피드백에서 추출
        for f in feedbacks:
            if f.explicit_feedback:
                issues.append(f.explicit_feedback[:100])

        # 응답 요약에서 패턴 추출
        response_keywords = defaultdict(int)
        for f in feedbacks:
            words = f.response_summary.split()
            for word in words:
                if len(word) > 3:
                    response_keywords[word] += 1

        # 빈도 높은 키워드
        common_keywords = sorted(
            response_keywords.items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]

        if common_keywords:
            issues.append(f"공통 키워드: {', '.join(kw for kw, _ in common_keywords)}")

        return issues[:5]

    def _suggest_fix_type(
        self,
        issues: List[str],
        feedbacks: List[Feedback]
    ) -> str:
        """수정 유형 제안"""
        issues_text = " ".join(issues).lower()

        if any(kw in issues_text for kw in ["error", "에러", "오류", "exception"]):
            return "code_fix"

        if any(kw in issues_text for kw in ["없", "not", "missing", "기능"]):
            return "new_function"

        # 의도 점수가 낮은 경우
        avg_intent = sum(f.intent_match_score for f in feedbacks) / len(feedbacks)
        if avg_intent < 0.7:
            return "prompt_update"

        return "prompt_update"

    async def _analyze_pattern_with_llm(
        self,
        query_type: str,
        issues: List[str],
        examples: List[dict]
    ) -> Optional[dict]:
        """LLM으로 패턴 분석"""
        if not self.llm_client:
            return None

        prompt = f"""다음 쿼리 유형의 문제 패턴을 분석하세요.

쿼리 유형: {query_type}
발견된 문제: {issues}
예시:
{examples[:3]}

분석 결과를 다음 형식으로 제공하세요:
- 핵심 문제: [문제 설명]
- 권장 수정: [수정 방향]
- 신뢰도: [0.0 ~ 1.0]
"""

        try:
            await self.llm_client.initialize()
            result = await self.llm_client.invoke(prompt)
            content = str(result.content) if hasattr(result, 'content') else str(result)

            # 간단한 파싱
            confidence = 0.7
            match = re.search(r"신뢰도[:\s]*([0-9.]+)", content)
            if match:
                confidence = float(match.group(1))

            return {
                "analysis": content,
                "confidence": min(0.95, max(0.5, confidence))
            }

        except Exception as e:
            logger.warning(f"LLM 패턴 분석 실패: {e}")
            return None

    def _generate_pattern_id(self, query_type: str) -> str:
        """패턴 ID 생성"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"pattern_{query_type}_{timestamp}"

    def _add_pattern(self, pattern: LearnedPattern) -> None:
        """패턴 추가 (용량 관리 포함)"""
        self._patterns[pattern.pattern_id] = pattern

        # 최대 용량 확인
        if len(self._patterns) > self.config.max_patterns_stored:
            self._remove_oldest_patterns()

    def _remove_oldest_patterns(self) -> None:
        """가장 오래된 패턴 제거"""
        patterns = list(self._patterns.values())
        patterns.sort(key=lambda p: p.updated_at)

        # 10% 제거
        remove_count = max(1, len(patterns) // 10)
        for p in patterns[:remove_count]:
            del self._patterns[p.pattern_id]

    def _count_by_problem_type(self, patterns: List[LearnedPattern]) -> dict:
        """문제 유형별 카운트"""
        counts: Dict[str, int] = defaultdict(int)
        for p in patterns:
            counts[p.problem_type.value] += 1
        return dict(counts)

    def _count_by_fix_type(self, patterns: List[LearnedPattern]) -> dict:
        """수정 유형별 카운트"""
        counts: Dict[str, int] = defaultdict(int)
        for p in patterns:
            counts[p.suggested_fix_type] += 1
        return dict(counts)
