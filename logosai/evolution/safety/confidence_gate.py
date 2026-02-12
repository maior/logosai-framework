"""
Confidence Gate (신뢰도 기반 게이트)

개선안의 신뢰도에 따라 적용 방식을 결정합니다.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from datetime import datetime

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from ..types import GateAction, Improvement


@dataclass
class GateThresholds:
    """게이트 임계값 설정"""
    auto_apply: float = 0.95        # 자동 적용
    staged_rollout: float = 0.85    # 단계적 배포
    human_review: float = 0.70      # 사람 검토
    suggest_only: float = 0.50      # 제안만
    # suggest_only 미만은 자동 거부


@dataclass
class GateDecision:
    """게이트 결정 결과"""
    action: GateAction
    confidence: float
    reasoning: str
    conditions: Dict[str, bool]
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def to_dict(self) -> dict:
        """딕셔너리로 변환"""
        return {
            "action": self.action.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "conditions": self.conditions,
            "timestamp": self.timestamp.isoformat()
        }


class ConfidenceGate:
    """신뢰도 기반 적용 게이트"""

    def __init__(self, thresholds: Optional[GateThresholds] = None):
        """
        게이트 초기화

        Args:
            thresholds: 게이트 임계값 (None이면 기본값 사용)
        """
        self.thresholds = thresholds or GateThresholds()
        self._decision_history: List[GateDecision] = []

    def determine_action(
        self,
        improvement: Improvement,
        additional_factors: Optional[Dict[str, Any]] = None
    ) -> GateDecision:
        """
        개선안에 대한 액션 결정

        Args:
            improvement: 개선안
            additional_factors: 추가 고려 요소 (선택)

        Returns:
            게이트 결정 결과
        """
        confidence = improvement.confidence
        conditions = self._evaluate_conditions(improvement, additional_factors)

        # 신뢰도 기반 기본 액션 결정
        if confidence >= self.thresholds.auto_apply:
            base_action = GateAction.AUTO_APPLY
            reasoning = f"높은 신뢰도 ({confidence:.2f} >= {self.thresholds.auto_apply})"

        elif confidence >= self.thresholds.staged_rollout:
            base_action = GateAction.STAGED_ROLLOUT
            reasoning = f"중상 신뢰도 ({confidence:.2f} >= {self.thresholds.staged_rollout})"

        elif confidence >= self.thresholds.human_review:
            base_action = GateAction.HUMAN_REVIEW
            reasoning = f"중간 신뢰도 ({confidence:.2f} >= {self.thresholds.human_review})"

        elif confidence >= self.thresholds.suggest_only:
            base_action = GateAction.SUGGEST_ONLY
            reasoning = f"낮은 신뢰도 ({confidence:.2f} >= {self.thresholds.suggest_only})"

        else:
            base_action = GateAction.REJECT
            reasoning = f"매우 낮은 신뢰도 ({confidence:.2f} < {self.thresholds.suggest_only})"

        # 추가 조건에 따른 액션 조정
        final_action = self._adjust_action(base_action, conditions)

        if final_action != base_action:
            reasoning += f" → 조건에 따라 {final_action.value}로 조정"

        decision = GateDecision(
            action=final_action,
            confidence=confidence,
            reasoning=reasoning,
            conditions=conditions
        )

        self._decision_history.append(decision)
        self._log_decision(decision, improvement)

        return decision

    def _evaluate_conditions(
        self,
        improvement: Improvement,
        additional_factors: Optional[Dict[str, Any]]
    ) -> Dict[str, bool]:
        """
        추가 조건 평가

        Args:
            improvement: 개선안
            additional_factors: 추가 요소

        Returns:
            조건 평가 결과
        """
        conditions = {
            "has_rollback_plan": improvement.rollback_plan is not None,
            "has_impact_analysis": improvement.impact_analysis is not None,
            "is_critical_change": self._is_critical_change(improvement),
            "affects_core_functionality": self._affects_core(improvement),
            "has_tests": self._has_tests(improvement)
        }

        if additional_factors:
            conditions["is_production"] = additional_factors.get("is_production", False)
            conditions["has_recent_failures"] = additional_factors.get("has_recent_failures", False)
            conditions["is_peak_hours"] = additional_factors.get("is_peak_hours", False)

        return conditions

    def _adjust_action(
        self,
        base_action: GateAction,
        conditions: Dict[str, bool]
    ) -> GateAction:
        """
        조건에 따라 액션 조정

        Args:
            base_action: 기본 액션
            conditions: 조건 평가 결과

        Returns:
            조정된 액션
        """
        # 프로덕션 환경에서는 더 보수적으로
        if conditions.get("is_production", False):
            if base_action == GateAction.AUTO_APPLY:
                return GateAction.STAGED_ROLLOUT
            elif base_action == GateAction.STAGED_ROLLOUT:
                return GateAction.HUMAN_REVIEW

        # 핵심 기능 영향 시 사람 검토 필요
        if conditions.get("affects_core_functionality", False):
            if base_action in [GateAction.AUTO_APPLY, GateAction.STAGED_ROLLOUT]:
                return GateAction.HUMAN_REVIEW

        # 롤백 계획 없이 자동 적용 불가
        if not conditions.get("has_rollback_plan", False):
            if base_action == GateAction.AUTO_APPLY:
                return GateAction.STAGED_ROLLOUT

        # 최근 실패가 있었다면 더 보수적으로
        if conditions.get("has_recent_failures", False):
            if base_action in [GateAction.AUTO_APPLY, GateAction.STAGED_ROLLOUT]:
                return GateAction.HUMAN_REVIEW

        return base_action

    def _is_critical_change(self, improvement: Improvement) -> bool:
        """핵심 변경 여부 확인"""
        critical_types = ["core_logic", "security", "authentication", "database"]
        return improvement.improvement_type in critical_types

    def _affects_core(self, improvement: Improvement) -> bool:
        """핵심 기능 영향 여부 확인"""
        if improvement.impact_analysis:
            affected = improvement.impact_analysis.get("affected_components", [])
            core_components = ["agent", "config", "llm", "process"]
            return any(c in str(affected).lower() for c in core_components)
        return False

    def _has_tests(self, improvement: Improvement) -> bool:
        """테스트 포함 여부 확인"""
        if improvement.suggested_changes:
            return "tests" in improvement.suggested_changes
        return False

    def _log_decision(self, decision: GateDecision, improvement: Improvement) -> None:
        """결정 로깅"""
        action_emoji = {
            GateAction.AUTO_APPLY: "✅",
            GateAction.STAGED_ROLLOUT: "🔄",
            GateAction.HUMAN_REVIEW: "👤",
            GateAction.SUGGEST_ONLY: "💡",
            GateAction.REJECT: "❌"
        }

        emoji = action_emoji.get(decision.action, "❓")
        logger.info(
            f"{emoji} Gate Decision: {decision.action.value} "
            f"(confidence: {decision.confidence:.2f})"
        )
        logger.debug(f"  Reasoning: {decision.reasoning}")
        logger.debug(f"  Conditions: {decision.conditions}")

    def get_decision_history(self, limit: int = 100) -> List[GateDecision]:
        """
        결정 이력 조회

        Args:
            limit: 최대 조회 개수

        Returns:
            최근 결정 리스트
        """
        return self._decision_history[-limit:]

    def get_statistics(self) -> dict:
        """
        결정 통계

        Returns:
            통계 딕셔너리
        """
        if not self._decision_history:
            return {"total_decisions": 0}

        action_counts = {}
        for decision in self._decision_history:
            action = decision.action.value
            action_counts[action] = action_counts.get(action, 0) + 1

        avg_confidence = sum(d.confidence for d in self._decision_history) / len(self._decision_history)

        return {
            "total_decisions": len(self._decision_history),
            "action_distribution": action_counts,
            "average_confidence": avg_confidence,
            "auto_apply_rate": action_counts.get("auto_apply", 0) / len(self._decision_history),
            "reject_rate": action_counts.get("reject", 0) / len(self._decision_history)
        }

    def update_thresholds(
        self,
        auto_apply: Optional[float] = None,
        staged_rollout: Optional[float] = None,
        human_review: Optional[float] = None,
        suggest_only: Optional[float] = None
    ) -> None:
        """
        임계값 업데이트

        Args:
            auto_apply: 자동 적용 임계값
            staged_rollout: 단계적 배포 임계값
            human_review: 사람 검토 임계값
            suggest_only: 제안만 임계값
        """
        if auto_apply is not None:
            self.thresholds.auto_apply = auto_apply
        if staged_rollout is not None:
            self.thresholds.staged_rollout = staged_rollout
        if human_review is not None:
            self.thresholds.human_review = human_review
        if suggest_only is not None:
            self.thresholds.suggest_only = suggest_only

        logger.info(
            f"Gate thresholds updated: "
            f"auto={self.thresholds.auto_apply}, "
            f"staged={self.thresholds.staged_rollout}, "
            f"review={self.thresholds.human_review}, "
            f"suggest={self.thresholds.suggest_only}"
        )
