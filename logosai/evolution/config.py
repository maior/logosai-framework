"""
Self-Evolution System 설정

진화 시스템의 동작을 제어하는 설정 클래스입니다.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from .types import EvolutionMode


@dataclass
class LLMConfig:
    """LLM 설정"""
    provider: str = "google"
    model: str = "gemini-2.5-flash-lite"
    temperature: float = 0.3  # 진화 시스템은 낮은 창의성 권장
    max_tokens: int = 4096
    api_key: Optional[str] = None  # None이면 환경변수 사용


@dataclass
class SafetyConfig:
    """안전 설정"""
    # Circuit Breaker
    circuit_breaker_enabled: bool = True
    failure_threshold: int = 3          # 연속 실패 횟수 제한
    cooldown_period_seconds: int = 3600  # 쿨다운 기간 (1시간)

    # Fix History
    max_attempts_per_problem: int = 3   # 동일 문제 최대 시도 횟수
    similar_fix_threshold: float = 0.85  # 유사 수정 판단 임계값

    # Confidence Gates
    auto_apply_threshold: float = 0.95      # 자동 적용
    staged_rollout_threshold: float = 0.85  # 단계적 배포
    human_review_threshold: float = 0.70    # 사람 검토
    suggest_only_threshold: float = 0.50    # 제안만
    # 0.50 미만은 자동 거부

    # Validation
    require_syntax_check: bool = True
    require_unit_tests: bool = True
    require_regression_tests: bool = False  # 기본 비활성화 (리소스 고려)


@dataclass
class DetectionConfig:
    """문제 감지 설정"""
    intent_match_threshold: float = 0.7     # 의도 일치 임계값
    quality_threshold: float = 0.6          # 품질 임계값
    error_sensitivity: str = "medium"       # low, medium, high
    detect_missing_functions: bool = True   # 기능 부재 감지
    detect_intent_mismatch: bool = True     # 의도 불일치 감지


@dataclass
class LearningConfig:
    """학습 설정"""
    min_samples_for_pattern: int = 3        # 패턴 인식 최소 샘플 수
    pattern_confidence_threshold: float = 0.7
    max_patterns_stored: int = 1000         # 최대 저장 패턴 수
    pattern_expiry_days: int = 90           # 패턴 만료 기간


@dataclass
class EscalationConfig:
    """에스컬레이션 설정"""
    notify_on_circuit_open: bool = True
    notify_on_repeated_failures: bool = True
    human_review_timeout_hours: int = 24
    escalation_email: Optional[str] = None
    webhook_url: Optional[str] = None


@dataclass
class EvolutionConfig:
    """진화 시스템 메인 설정"""

    # 기본 설정
    enabled: bool = False  # 기본값: 비활성화 (사용자 요청대로)
    mode: EvolutionMode = field(default=EvolutionMode.BOTH)
    debug: bool = False
    log_level: str = "INFO"

    # LLM 설정
    llm_provider: str = "google"
    llm_model: str = "gemini-2.5-flash-lite"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 4096
    llm_api_key: Optional[str] = None

    # 하위 설정
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    learning: LearningConfig = field(default_factory=LearningConfig)
    escalation: EscalationConfig = field(default_factory=EscalationConfig)

    # 스토리지 설정
    storage_path: Optional[str] = None  # None이면 메모리 저장
    persist_patterns: bool = True
    persist_feedback: bool = True

    def get_llm_config(self) -> LLMConfig:
        """LLM 설정 객체 반환"""
        return LLMConfig(
            provider=self.llm_provider,
            model=self.llm_model,
            temperature=self.llm_temperature,
            max_tokens=self.llm_max_tokens,
            api_key=self.llm_api_key
        )

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "enabled": self.enabled,
            "mode": self.mode.value,
            "debug": self.debug,
            "log_level": self.log_level,
            "llm": {
                "provider": self.llm_provider,
                "model": self.llm_model,
                "temperature": self.llm_temperature,
                "max_tokens": self.llm_max_tokens
            },
            "safety": {
                "circuit_breaker_enabled": self.safety.circuit_breaker_enabled,
                "failure_threshold": self.safety.failure_threshold,
                "cooldown_period_seconds": self.safety.cooldown_period_seconds,
                "max_attempts_per_problem": self.safety.max_attempts_per_problem,
                "auto_apply_threshold": self.safety.auto_apply_threshold,
                "staged_rollout_threshold": self.safety.staged_rollout_threshold,
                "human_review_threshold": self.safety.human_review_threshold
            },
            "detection": {
                "intent_match_threshold": self.detection.intent_match_threshold,
                "quality_threshold": self.detection.quality_threshold,
                "error_sensitivity": self.detection.error_sensitivity
            },
            "learning": {
                "min_samples_for_pattern": self.learning.min_samples_for_pattern,
                "pattern_confidence_threshold": self.learning.pattern_confidence_threshold,
                "max_patterns_stored": self.learning.max_patterns_stored
            }
        }

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'EvolutionConfig':
        """딕셔너리에서 설정 생성"""
        # LLM 설정
        llm_config = config_dict.get("llm", {})

        # Safety 설정
        safety_dict = config_dict.get("safety", {})
        safety = SafetyConfig(
            circuit_breaker_enabled=safety_dict.get("circuit_breaker_enabled", True),
            failure_threshold=safety_dict.get("failure_threshold", 3),
            cooldown_period_seconds=safety_dict.get("cooldown_period_seconds", 3600),
            max_attempts_per_problem=safety_dict.get("max_attempts_per_problem", 3),
            auto_apply_threshold=safety_dict.get("auto_apply_threshold", 0.95),
            staged_rollout_threshold=safety_dict.get("staged_rollout_threshold", 0.85),
            human_review_threshold=safety_dict.get("human_review_threshold", 0.70),
            suggest_only_threshold=safety_dict.get("suggest_only_threshold", 0.50)
        )

        # Detection 설정
        detection_dict = config_dict.get("detection", {})
        detection = DetectionConfig(
            intent_match_threshold=detection_dict.get("intent_match_threshold", 0.7),
            quality_threshold=detection_dict.get("quality_threshold", 0.6),
            error_sensitivity=detection_dict.get("error_sensitivity", "medium")
        )

        # Learning 설정
        learning_dict = config_dict.get("learning", {})
        learning = LearningConfig(
            min_samples_for_pattern=learning_dict.get("min_samples_for_pattern", 3),
            pattern_confidence_threshold=learning_dict.get("pattern_confidence_threshold", 0.7),
            max_patterns_stored=learning_dict.get("max_patterns_stored", 1000)
        )

        # Mode 파싱
        mode_str = config_dict.get("mode", "both")
        try:
            mode = EvolutionMode(mode_str)
        except ValueError:
            mode = EvolutionMode.BOTH

        return cls(
            enabled=config_dict.get("enabled", False),
            mode=mode,
            debug=config_dict.get("debug", False),
            log_level=config_dict.get("log_level", "INFO"),
            llm_provider=llm_config.get("provider", "google"),
            llm_model=llm_config.get("model", "gemini-2.5-flash-lite"),
            llm_temperature=llm_config.get("temperature", 0.3),
            llm_max_tokens=llm_config.get("max_tokens", 4096),
            safety=safety,
            detection=detection,
            learning=learning
        )

    @classmethod
    def create_enabled(
        cls,
        llm_provider: str = "google",
        llm_model: str = "gemini-2.5-flash-lite",
        mode: EvolutionMode = EvolutionMode.BOTH,
        **kwargs
    ) -> 'EvolutionConfig':
        """활성화된 설정 생성 (편의 메서드)"""
        return cls(
            enabled=True,
            mode=mode,
            llm_provider=llm_provider,
            llm_model=llm_model,
            **kwargs
        )

    @classmethod
    def create_disabled(cls) -> 'EvolutionConfig':
        """비활성화된 설정 생성 (기본값)"""
        return cls(enabled=False)
