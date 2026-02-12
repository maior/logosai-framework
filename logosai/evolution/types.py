"""
Self-Evolution System 타입 정의

이 모듈은 진화 시스템에서 사용되는 모든 타입과 데이터 클래스를 정의합니다.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from datetime import datetime


class ProblemType(Enum):
    """문제 유형"""
    # Self-Healing 관련
    SYNTAX_ERROR = "syntax_error"           # 구문 오류
    RUNTIME_ERROR = "runtime_error"         # 런타임 오류
    IMPORT_ERROR = "import_error"           # 임포트 오류
    TYPE_ERROR = "type_error"               # 타입 오류

    # Self-Growing 관련
    MISSING_FUNCTION = "missing_function"   # 기능 부재
    INTENT_MISMATCH = "intent_mismatch"     # 의도 불일치
    INCOMPLETE_RESPONSE = "incomplete_response"  # 불완전한 응답

    # Self-Evaluation 관련
    LOW_QUALITY = "low_quality"             # 낮은 품질
    USER_DISSATISFACTION = "user_dissatisfaction"  # 사용자 불만족
    PERFORMANCE_ISSUE = "performance_issue"  # 성능 문제

    # 기타
    UNKNOWN = "unknown"                     # 알 수 없는 문제


class Severity(Enum):
    """문제 심각도"""
    CRITICAL = "critical"   # 즉시 수정 필요 (시스템 중단 가능)
    HIGH = "high"           # 빠른 수정 필요 (기능 영향)
    MEDIUM = "medium"       # 수정 권장 (사용자 경험 영향)
    LOW = "low"             # 개선 사항 (품질 향상)
    INFO = "info"           # 정보성 (모니터링용)


class GateAction(Enum):
    """신뢰도 게이트 액션"""
    AUTO_APPLY = "auto_apply"           # 자동 적용 (confidence >= 0.95)
    STAGED_ROLLOUT = "staged_rollout"   # 단계적 배포 (0.85 <= confidence < 0.95)
    HUMAN_REVIEW = "human_review"       # 사람 검토 필요 (0.70 <= confidence < 0.85)
    SUGGEST_ONLY = "suggest_only"       # 제안만 (0.50 <= confidence < 0.70)
    REJECT = "reject"                   # 자동 거부 (confidence < 0.50)


class EvolutionMode(Enum):
    """진화 모드"""
    HEALING = "healing"     # 에러 수정 모드
    GROWING = "growing"     # 기능 추가 모드
    BOTH = "both"           # 통합 모드 (기본값)


@dataclass
class DetectedProblem:
    """감지된 문제"""
    problem_type: ProblemType
    severity: Severity
    description: str
    details: Optional[Dict[str, Any]] = None
    query: Optional[str] = None
    response: Optional[str] = None
    error_message: Optional[str] = None
    stack_trace: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def signature(self) -> str:
        """문제 시그니처 (동일 문제 식별용)"""
        return f"{self.problem_type.value}:{self.description[:50]}"

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "problem_type": self.problem_type.value,
            "severity": self.severity.value,
            "description": self.description,
            "details": self.details,
            "query": self.query,
            "response": self.response,
            "error_message": self.error_message,
            "stack_trace": self.stack_trace,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class Feedback:
    """피드백 데이터"""
    agent_id: str
    query: str
    response_summary: str
    is_positive: bool = True
    explicit_feedback: Optional[str] = None  # 사용자 명시적 피드백
    implicit_signals: Optional[Dict[str, Any]] = None  # 암묵적 신호
    intent_match_score: float = 1.0  # 0.0 ~ 1.0
    quality_score: float = 1.0  # 0.0 ~ 1.0
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "agent_id": self.agent_id,
            "query": self.query,
            "response_summary": self.response_summary,
            "is_positive": self.is_positive,
            "explicit_feedback": self.explicit_feedback,
            "implicit_signals": self.implicit_signals,
            "intent_match_score": self.intent_match_score,
            "quality_score": self.quality_score,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class LearnedPattern:
    """학습된 패턴"""
    pattern_id: str
    query_type: str                         # 쿼리 유형 (예: "월간_일정_조회")
    problem_type: ProblemType
    frequency: int = 1                      # 발생 빈도
    common_issues: List[str] = field(default_factory=list)
    suggested_fix_type: str = "prompt_update"  # prompt_update, code_fix, new_function
    confidence: float = 0.0                 # 패턴 신뢰도
    examples: List[Dict[str, str]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "pattern_id": self.pattern_id,
            "query_type": self.query_type,
            "problem_type": self.problem_type.value,
            "frequency": self.frequency,
            "common_issues": self.common_issues,
            "suggested_fix_type": self.suggested_fix_type,
            "confidence": self.confidence,
            "examples": self.examples,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }


@dataclass
class Improvement:
    """개선안"""
    improvement_id: str
    pattern_id: Optional[str]
    problem: DetectedProblem
    improvement_type: str  # prompt_update, code_fix, new_function, config_change
    suggested_changes: Dict[str, Any]  # 변경 내용
    confidence: float  # 0.0 ~ 1.0
    impact_analysis: Optional[Dict[str, Any]] = None
    reasoning: Optional[str] = None  # 개선 이유
    rollback_plan: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "improvement_id": self.improvement_id,
            "pattern_id": self.pattern_id,
            "problem": self.problem.to_dict(),
            "improvement_type": self.improvement_type,
            "suggested_changes": self.suggested_changes,
            "confidence": self.confidence,
            "impact_analysis": self.impact_analysis,
            "reasoning": self.reasoning,
            "rollback_plan": self.rollback_plan,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class ValidationResult:
    """검증 결과"""
    passed: bool
    stage: str  # syntax, unit_test, regression, integration
    details: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metrics: Optional[Dict[str, float]] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "passed": self.passed,
            "stage": self.stage,
            "details": self.details,
            "errors": self.errors,
            "warnings": self.warnings,
            "metrics": self.metrics,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class EvolutionResult:
    """진화 실행 결과"""
    success: bool
    mode: EvolutionMode
    problems_detected: List[DetectedProblem] = field(default_factory=list)
    improvements_applied: List[Improvement] = field(default_factory=list)
    improvements_suggested: List[Improvement] = field(default_factory=list)
    improvements_rejected: List[Improvement] = field(default_factory=list)
    validation_results: List[ValidationResult] = field(default_factory=list)
    gate_action: Optional[GateAction] = None
    message: str = ""
    execution_time_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "success": self.success,
            "mode": self.mode.value,
            "problems_detected": [p.to_dict() for p in self.problems_detected],
            "improvements_applied": [i.to_dict() for i in self.improvements_applied],
            "improvements_suggested": [i.to_dict() for i in self.improvements_suggested],
            "improvements_rejected": [i.to_dict() for i in self.improvements_rejected],
            "validation_results": [v.to_dict() for v in self.validation_results],
            "gate_action": self.gate_action.value if self.gate_action else None,
            "message": self.message,
            "execution_time_ms": self.execution_time_ms,
            "timestamp": self.timestamp.isoformat()
        }
