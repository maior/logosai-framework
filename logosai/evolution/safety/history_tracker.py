"""
Fix History Tracker (수정 이력 추적기)

동일 문제에 대한 반복 수정을 감지하고 방지합니다.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import hashlib
import json

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


@dataclass
class FixRecord:
    """수정 기록"""
    fix_id: str
    problem_signature: str
    fix_content: str  # 수정 내용 요약
    fix_type: str     # prompt_update, code_fix, new_function
    success: bool
    confidence: float
    error_message: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """딕셔너리로 변환"""
        return {
            "fix_id": self.fix_id,
            "problem_signature": self.problem_signature,
            "fix_content": self.fix_content,
            "fix_type": self.fix_type,
            "success": self.success,
            "confidence": self.confidence,
            "error_message": self.error_message,
            "timestamp": self.timestamp.isoformat()
        }


class FixHistoryTracker:
    """수정 이력 추적기"""

    def __init__(
        self,
        max_attempts_per_problem: int = 3,
        similar_fix_threshold: float = 0.85,
        history_retention_days: int = 30
    ):
        """
        이력 추적기 초기화

        Args:
            max_attempts_per_problem: 동일 문제 최대 시도 횟수
            similar_fix_threshold: 유사 수정 판단 임계값 (0.0~1.0)
            history_retention_days: 이력 보관 기간 (일)
        """
        self.max_attempts = max_attempts_per_problem
        self.similar_threshold = similar_fix_threshold
        self.retention_days = history_retention_days

        # 문제 시그니처 -> 수정 기록 리스트
        self._fix_history: Dict[str, List[FixRecord]] = defaultdict(list)

        # 수정 내용 해시 -> 수정 기록 (중복 검사용)
        self._fix_hashes: Dict[str, FixRecord] = {}

    def can_attempt_fix(self, problem_signature: str) -> Tuple[bool, str]:
        """
        수정 시도 가능 여부 확인

        Args:
            problem_signature: 문제 시그니처

        Returns:
            (가능 여부, 이유 메시지)
        """
        history = self._fix_history.get(problem_signature, [])

        # 최대 시도 횟수 확인
        recent_attempts = self._get_recent_attempts(history)
        if len(recent_attempts) >= self.max_attempts:
            return False, f"최대 시도 횟수 초과 ({len(recent_attempts)}/{self.max_attempts})"

        # 최근 성공한 수정이 있는지 확인
        recent_success = [r for r in recent_attempts if r.success]
        if recent_success:
            return False, f"최근 성공한 수정이 있음 (fix_id: {recent_success[-1].fix_id})"

        return True, "수정 시도 가능"

    def is_fix_cycle(
        self,
        problem_signature: str,
        proposed_fix: str
    ) -> Tuple[bool, Optional[FixRecord]]:
        """
        수정 순환 감지

        Args:
            problem_signature: 문제 시그니처
            proposed_fix: 제안된 수정 내용

        Returns:
            (순환 여부, 이전 유사 수정 기록)
        """
        history = self._fix_history.get(problem_signature, [])

        for past_fix in history:
            similarity = self._calculate_similarity(past_fix.fix_content, proposed_fix)
            if similarity >= self.similar_threshold:
                logger.warning(
                    f"수정 순환 감지: 유사도 {similarity:.2f} >= {self.similar_threshold}"
                )
                return True, past_fix

        return False, None

    def record_fix(
        self,
        problem_signature: str,
        fix_content: str,
        fix_type: str,
        success: bool,
        confidence: float = 0.0,
        error_message: Optional[str] = None
    ) -> FixRecord:
        """
        수정 기록 저장

        Args:
            problem_signature: 문제 시그니처
            fix_content: 수정 내용
            fix_type: 수정 유형
            success: 성공 여부
            confidence: 신뢰도
            error_message: 에러 메시지 (실패 시)

        Returns:
            생성된 수정 기록
        """
        fix_id = self._generate_fix_id(problem_signature, fix_content)

        record = FixRecord(
            fix_id=fix_id,
            problem_signature=problem_signature,
            fix_content=fix_content,
            fix_type=fix_type,
            success=success,
            confidence=confidence,
            error_message=error_message
        )

        self._fix_history[problem_signature].append(record)
        self._fix_hashes[self._hash_content(fix_content)] = record

        logger.info(
            f"수정 기록 저장: {fix_id} "
            f"(문제: {problem_signature[:30]}..., 성공: {success})"
        )

        # 오래된 기록 정리
        self._cleanup_old_records()

        return record

    def get_fix_attempts(self, problem_signature: str) -> int:
        """
        동일 문제 수정 시도 횟수

        Args:
            problem_signature: 문제 시그니처

        Returns:
            시도 횟수
        """
        return len(self._get_recent_attempts(
            self._fix_history.get(problem_signature, [])
        ))

    def get_history(self, problem_signature: str) -> List[FixRecord]:
        """
        특정 문제의 수정 이력 조회

        Args:
            problem_signature: 문제 시그니처

        Returns:
            수정 기록 리스트
        """
        return self._fix_history.get(problem_signature, [])

    def get_all_history(self) -> Dict[str, List[FixRecord]]:
        """
        전체 수정 이력 조회

        Returns:
            문제 시그니처 -> 수정 기록 리스트 딕셔너리
        """
        return dict(self._fix_history)

    def get_success_rate(self, problem_signature: Optional[str] = None) -> float:
        """
        성공률 계산

        Args:
            problem_signature: 문제 시그니처 (None이면 전체)

        Returns:
            성공률 (0.0 ~ 1.0)
        """
        if problem_signature:
            history = self._fix_history.get(problem_signature, [])
        else:
            history = [r for records in self._fix_history.values() for r in records]

        if not history:
            return 0.0

        success_count = sum(1 for r in history if r.success)
        return success_count / len(history)

    def get_statistics(self) -> dict:
        """
        전체 통계 정보

        Returns:
            통계 딕셔너리
        """
        all_records = [r for records in self._fix_history.values() for r in records]

        return {
            "total_problems": len(self._fix_history),
            "total_attempts": len(all_records),
            "total_successes": sum(1 for r in all_records if r.success),
            "total_failures": sum(1 for r in all_records if not r.success),
            "success_rate": self.get_success_rate(),
            "fix_types": self._count_by_type(all_records),
            "recent_activity": self._get_recent_activity(all_records)
        }

    def clear_history(self, problem_signature: Optional[str] = None) -> None:
        """
        이력 삭제

        Args:
            problem_signature: 삭제할 문제 시그니처 (None이면 전체)
        """
        if problem_signature:
            if problem_signature in self._fix_history:
                del self._fix_history[problem_signature]
                logger.info(f"수정 이력 삭제: {problem_signature}")
        else:
            self._fix_history.clear()
            self._fix_hashes.clear()
            logger.info("전체 수정 이력 삭제")

    def _get_recent_attempts(self, history: List[FixRecord]) -> List[FixRecord]:
        """보관 기간 내의 시도만 필터링"""
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        return [r for r in history if r.timestamp >= cutoff]

    def _calculate_similarity(self, content1: str, content2: str) -> float:
        """
        두 수정 내용의 유사도 계산 (간단한 Jaccard 유사도)

        Args:
            content1: 첫 번째 내용
            content2: 두 번째 내용

        Returns:
            유사도 (0.0 ~ 1.0)
        """
        # 단어 단위로 분리
        words1 = set(content1.lower().split())
        words2 = set(content2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union)

    def _generate_fix_id(self, problem_signature: str, fix_content: str) -> str:
        """수정 ID 생성"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        content_hash = self._hash_content(fix_content)[:8]
        return f"fix_{timestamp}_{content_hash}"

    def _hash_content(self, content: str) -> str:
        """내용 해시 생성"""
        return hashlib.md5(content.encode()).hexdigest()

    def _cleanup_old_records(self) -> None:
        """오래된 기록 정리"""
        cutoff = datetime.now() - timedelta(days=self.retention_days)

        for signature in list(self._fix_history.keys()):
            self._fix_history[signature] = [
                r for r in self._fix_history[signature]
                if r.timestamp >= cutoff
            ]
            if not self._fix_history[signature]:
                del self._fix_history[signature]

    def _count_by_type(self, records: List[FixRecord]) -> dict:
        """수정 유형별 카운트"""
        counts: Dict[str, int] = defaultdict(int)
        for r in records:
            counts[r.fix_type] += 1
        return dict(counts)

    def _get_recent_activity(self, records: List[FixRecord], days: int = 7) -> dict:
        """최근 활동 요약"""
        cutoff = datetime.now() - timedelta(days=days)
        recent = [r for r in records if r.timestamp >= cutoff]

        return {
            "period_days": days,
            "attempts": len(recent),
            "successes": sum(1 for r in recent if r.success),
            "failures": sum(1 for r in recent if not r.success)
        }
