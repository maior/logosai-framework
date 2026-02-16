"""
Evolution System (v0.7.0) 단위 테스트

Tests:
- ProblemDetector: 에러/응답/기능부재 감지
- CircuitBreaker: 상태 전환, 쿨다운, 성공/실패 기록
- ConfidenceGate: 신뢰도별 액션 결정, 조건 조정
- FixHistoryTracker: 수정 기록, 순환 감지, 시도 제한
- EvolutionConfig: 생성, 직렬화, from_dict
- EvolutionSystem: 비활성 상태, 프로세스 흐름
"""

import asyncio
import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

# Evolution system imports
from logosai.evolution.types import (
    ProblemType, Severity, GateAction, EvolutionMode,
    DetectedProblem, Improvement, EvolutionResult
)
from logosai.evolution.config import (
    EvolutionConfig, SafetyConfig, DetectionConfig, LearningConfig
)
from logosai.evolution.detector import ProblemDetector
from logosai.evolution.safety.circuit_breaker import (
    EvolutionCircuitBreaker, CircuitBreakerConfig, CircuitState
)
from logosai.evolution.safety.confidence_gate import (
    ConfidenceGate, GateThresholds, GateDecision
)
from logosai.evolution.safety.history_tracker import (
    FixHistoryTracker, FixRecord
)
from logosai.evolution.system import EvolutionSystem, create_evolution_system


# ============================================================
# ProblemDetector Tests
# ============================================================

class TestProblemDetector:
    """ProblemDetector 단위 테스트"""

    def setup_method(self):
        self.detector = ProblemDetector()

    # --- 예외에서 문제 감지 ---

    def test_detect_syntax_error(self):
        error = SyntaxError("invalid syntax")
        problems = self.detector.detect_from_error(error, query="test")
        assert len(problems) == 1
        assert problems[0].problem_type == ProblemType.SYNTAX_ERROR
        assert problems[0].severity == Severity.HIGH

    def test_detect_import_error(self):
        error = ImportError("No module named 'nonexistent'")
        problems = self.detector.detect_from_error(error, query="test")
        assert len(problems) == 1
        assert problems[0].problem_type == ProblemType.IMPORT_ERROR

    def test_detect_type_error(self):
        error = TypeError("unsupported operand type")
        problems = self.detector.detect_from_error(error, query="test")
        assert len(problems) == 1
        assert problems[0].problem_type == ProblemType.TYPE_ERROR

    def test_detect_runtime_error(self):
        error = ValueError("invalid value")
        problems = self.detector.detect_from_error(error, query="test")
        assert len(problems) == 1
        assert problems[0].problem_type == ProblemType.RUNTIME_ERROR

    def test_detect_attribute_error(self):
        error = AttributeError("'NoneType' object has no attribute 'foo'")
        problems = self.detector.detect_from_error(error, query="test")
        assert len(problems) == 1
        assert problems[0].problem_type == ProblemType.TYPE_ERROR

    def test_critical_severity_detection(self):
        error = RuntimeError("critical data loss occurred")
        problems = self.detector.detect_from_error(error, query="test")
        assert len(problems) == 1
        assert problems[0].severity == Severity.CRITICAL

    def test_error_includes_stack_trace(self):
        try:
            raise ValueError("test error")
        except ValueError as e:
            problems = self.detector.detect_from_error(e, query="test")
            assert problems[0].stack_trace is not None
            assert "ValueError" in problems[0].stack_trace

    # --- 응답 텍스트에서 에러 감지 ---

    def test_detect_response_syntax_error(self):
        response = "결과: SyntaxError: unexpected EOF"
        problems = self.detector.detect_from_response("test", response)
        assert len(problems) >= 1
        assert any(p.problem_type == ProblemType.SYNTAX_ERROR for p in problems)

    def test_detect_response_import_error(self):
        response = "ModuleNotFoundError: No module named 'pandas'"
        problems = self.detector.detect_from_response("test", response)
        assert len(problems) >= 1
        assert any(p.problem_type == ProblemType.IMPORT_ERROR for p in problems)

    def test_clean_response_no_problems(self):
        response = "계산 결과: 100 + 200 = 300입니다."
        problems = self.detector.detect_from_response("test", response)
        assert len(problems) == 0

    # --- 기능 부재 감지 ---

    def test_detect_missing_function_korean(self):
        response = "이 기능은 지원하지 않습니다."
        problems = self.detector.detect_from_response("파일 변환해줘", response)
        assert len(problems) >= 1
        assert any(p.problem_type == ProblemType.MISSING_FUNCTION for p in problems)

    def test_detect_missing_function_english(self):
        response = "This feature is not implemented yet."
        problems = self.detector.detect_from_response("convert file", response)
        assert len(problems) >= 1
        assert any(p.problem_type == ProblemType.MISSING_FUNCTION for p in problems)

    # --- 사용자 피드백 분석 ---

    def test_negative_feedback_detection(self):
        response = "서울 날씨는 맑음입니다."
        problems = self.detector.detect_from_response(
            "부산 날씨 알려줘", response, user_feedback="잘못된 결과야"
        )
        assert any(p.problem_type == ProblemType.INTENT_MISMATCH for p in problems)

    def test_negative_feedback_english(self):
        response = "The answer is 42."
        problems = self.detector.detect_from_response(
            "What is 2+2?", response, user_feedback="That's wrong"
        )
        assert any(p.problem_type == ProblemType.INTENT_MISMATCH for p in problems)

    def test_positive_feedback_no_problems(self):
        response = "결과: 4"
        problems = self.detector.detect_from_response(
            "2+2=?", response, user_feedback="고마워요"
        )
        # No intent mismatch should be detected for positive feedback
        assert not any(p.problem_type == ProblemType.INTENT_MISMATCH for p in problems)

    # --- 응답 텍스트 추출 ---

    def test_extract_response_text_string(self):
        assert self.detector._extract_response_text("hello") == "hello"

    def test_extract_response_text_dict(self):
        result = self.detector._extract_response_text({"content": "hello"})
        assert "hello" in result

    def test_extract_response_text_object_with_content(self):
        obj = MagicMock()
        obj.content = "hello from object"
        assert "hello from object" in self.detector._extract_response_text(obj)

    # --- 중복 제거 ---

    def test_deduplication(self):
        problems = [
            DetectedProblem(
                problem_type=ProblemType.SYNTAX_ERROR,
                severity=Severity.HIGH,
                description="SyntaxError: invalid syntax in line 1",
                query="test"
            ),
            DetectedProblem(
                problem_type=ProblemType.SYNTAX_ERROR,
                severity=Severity.HIGH,
                description="SyntaxError: invalid syntax in line 1",
                query="test"
            ),
        ]
        unique = self.detector._deduplicate_problems(problems)
        assert len(unique) == 1

    # --- 비동기 detect ---

    @pytest.mark.asyncio
    async def test_async_detect_with_error(self):
        error = ValueError("bad value")
        problems = await self.detector.detect(
            query="test",
            response="error occurred",
            error=error,
            mode=EvolutionMode.HEALING
        )
        assert len(problems) >= 1
        assert any(p.problem_type == ProblemType.RUNTIME_ERROR for p in problems)

    @pytest.mark.asyncio
    async def test_async_detect_no_problems(self):
        problems = await self.detector.detect(
            query="2+2는?",
            response="4입니다.",
            mode=EvolutionMode.BOTH
        )
        assert len(problems) == 0

    @pytest.mark.asyncio
    async def test_async_detect_missing_function(self):
        problems = await self.detector.detect(
            query="PDF 변환해줘",
            response="이 기능이 없습니다",
            mode=EvolutionMode.GROWING
        )
        assert any(p.problem_type == ProblemType.MISSING_FUNCTION for p in problems)


# ============================================================
# CircuitBreaker Tests
# ============================================================

class TestCircuitBreaker:
    """CircuitBreaker 단위 테스트"""

    def setup_method(self):
        self.config = CircuitBreakerConfig(
            failure_threshold=3,
            cooldown_period_seconds=2,  # 테스트용 짧은 쿨다운
            half_open_max_calls=1,
            success_threshold=2
        )
        self.cb = EvolutionCircuitBreaker(self.config)

    def test_initial_state_closed(self):
        assert self.cb.state == CircuitState.CLOSED
        assert self.cb.failure_count == 0

    def test_can_execute_when_closed(self):
        assert self.cb.can_execute() is True

    def test_stays_closed_under_threshold(self):
        self.cb.record_failure()
        self.cb.record_failure()
        assert self.cb.state == CircuitState.CLOSED
        assert self.cb.can_execute() is True

    def test_opens_at_threshold(self):
        for _ in range(3):
            self.cb.record_failure()
        assert self.cb.state == CircuitState.OPEN
        assert self.cb.can_execute() is False

    def test_success_resets_failure_count(self):
        self.cb.record_failure()
        self.cb.record_failure()
        self.cb.record_success()
        assert self.cb.failure_count == 0
        assert self.cb.state == CircuitState.CLOSED

    def test_cooldown_transitions_to_half_open(self):
        # Open the circuit
        for _ in range(3):
            self.cb.record_failure()
        assert self.cb.state == CircuitState.OPEN

        # Simulate cooldown elapsed
        self.cb._last_failure_time = datetime.now() - timedelta(seconds=3)
        assert self.cb.can_execute() is True
        assert self.cb.state == CircuitState.HALF_OPEN

    def test_half_open_failure_reopens(self):
        # Get to HALF_OPEN
        for _ in range(3):
            self.cb.record_failure()
        self.cb._last_failure_time = datetime.now() - timedelta(seconds=3)
        self.cb.can_execute()  # transitions to HALF_OPEN

        # Failure in HALF_OPEN → back to OPEN
        self.cb.record_failure()
        assert self.cb.state == CircuitState.OPEN

    def test_half_open_success_needs_threshold(self):
        # Get to HALF_OPEN
        for _ in range(3):
            self.cb.record_failure()
        self.cb._last_failure_time = datetime.now() - timedelta(seconds=3)
        self.cb.can_execute()

        # 1 success not enough (threshold=2)
        self.cb.record_success()
        assert self.cb.state == CircuitState.HALF_OPEN

        # 2nd success → CLOSED
        self.cb.record_success()
        assert self.cb.state == CircuitState.CLOSED

    def test_manual_reset(self):
        for _ in range(3):
            self.cb.record_failure()
        assert self.cb.state == CircuitState.OPEN

        self.cb.reset()
        assert self.cb.state == CircuitState.CLOSED
        assert self.cb.failure_count == 0

    def test_get_status(self):
        status = self.cb.get_status()
        assert status["state"] == "closed"
        assert status["failure_count"] == 0
        assert "config" in status

    def test_get_status_when_open(self):
        for _ in range(3):
            self.cb.record_failure()
        status = self.cb.get_status()
        assert status["state"] == "open"
        assert status["remaining_cooldown_seconds"] is not None
        assert status["remaining_cooldown_seconds"] > 0

    def test_record_failure_with_exception(self):
        error = RuntimeError("test error")
        self.cb.record_failure(error)
        assert self.cb.failure_count == 1


# ============================================================
# ConfidenceGate Tests
# ============================================================

class TestConfidenceGate:
    """ConfidenceGate 단위 테스트"""

    def setup_method(self):
        self.gate = ConfidenceGate(GateThresholds(
            auto_apply=0.95,
            staged_rollout=0.85,
            human_review=0.70,
            suggest_only=0.50
        ))

    def _make_improvement(self, confidence: float, **kwargs) -> Improvement:
        """테스트용 Improvement 생성"""
        problem = DetectedProblem(
            problem_type=ProblemType.RUNTIME_ERROR,
            severity=Severity.MEDIUM,
            description="test problem",
            query="test"
        )
        return Improvement(
            improvement_id=f"test_imp_{confidence}",
            pattern_id=None,
            problem=problem,
            improvement_type=kwargs.get("improvement_type", "code_fix"),
            suggested_changes=kwargs.get("suggested_changes", {"fix": "test"}),
            confidence=confidence,
            rollback_plan=kwargs.get("rollback_plan", None),
            impact_analysis=kwargs.get("impact_analysis", None),
        )

    def test_auto_apply_high_confidence(self):
        imp = self._make_improvement(0.97, rollback_plan="revert change")
        decision = self.gate.determine_action(imp)
        assert decision.action == GateAction.AUTO_APPLY

    def test_staged_rollout_medium_high_confidence(self):
        imp = self._make_improvement(0.90)
        decision = self.gate.determine_action(imp)
        assert decision.action == GateAction.STAGED_ROLLOUT

    def test_human_review_medium_confidence(self):
        imp = self._make_improvement(0.75)
        decision = self.gate.determine_action(imp)
        assert decision.action == GateAction.HUMAN_REVIEW

    def test_suggest_only_low_confidence(self):
        imp = self._make_improvement(0.55)
        decision = self.gate.determine_action(imp)
        assert decision.action == GateAction.SUGGEST_ONLY

    def test_reject_very_low_confidence(self):
        imp = self._make_improvement(0.30)
        decision = self.gate.determine_action(imp)
        assert decision.action == GateAction.REJECT

    def test_boundary_auto_apply(self):
        imp = self._make_improvement(0.95, rollback_plan="revert")
        decision = self.gate.determine_action(imp)
        assert decision.action == GateAction.AUTO_APPLY

    def test_boundary_below_suggest(self):
        imp = self._make_improvement(0.49)
        decision = self.gate.determine_action(imp)
        assert decision.action == GateAction.REJECT

    # --- 조건 조정 테스트 ---

    def test_production_downgrade(self):
        imp = self._make_improvement(0.97, rollback_plan="revert")
        decision = self.gate.determine_action(
            imp, additional_factors={"is_production": True}
        )
        # AUTO_APPLY → STAGED_ROLLOUT in production
        assert decision.action == GateAction.STAGED_ROLLOUT

    def test_no_rollback_plan_downgrade(self):
        imp = self._make_improvement(0.97)  # no rollback_plan
        decision = self.gate.determine_action(imp)
        # AUTO_APPLY → STAGED_ROLLOUT without rollback
        assert decision.action == GateAction.STAGED_ROLLOUT

    def test_core_functionality_downgrade(self):
        imp = self._make_improvement(
            0.97,
            rollback_plan="revert",
            impact_analysis={"affected_components": ["agent config"]}
        )
        decision = self.gate.determine_action(imp)
        # affects_core → HUMAN_REVIEW
        assert decision.action == GateAction.HUMAN_REVIEW

    def test_recent_failures_downgrade(self):
        imp = self._make_improvement(0.90)
        decision = self.gate.determine_action(
            imp, additional_factors={"has_recent_failures": True}
        )
        # STAGED_ROLLOUT → HUMAN_REVIEW
        assert decision.action == GateAction.HUMAN_REVIEW

    # --- 통계 ---

    def test_statistics_empty(self):
        stats = self.gate.get_statistics()
        assert stats["total_decisions"] == 0

    def test_statistics_after_decisions(self):
        for conf in [0.97, 0.90, 0.75, 0.55, 0.30]:
            imp = self._make_improvement(conf, rollback_plan="revert")
            self.gate.determine_action(imp)

        stats = self.gate.get_statistics()
        assert stats["total_decisions"] == 5
        assert "action_distribution" in stats

    def test_decision_history(self):
        imp = self._make_improvement(0.80)
        self.gate.determine_action(imp)
        history = self.gate.get_decision_history()
        assert len(history) == 1
        assert isinstance(history[0], GateDecision)

    def test_update_thresholds(self):
        self.gate.update_thresholds(auto_apply=0.99)
        assert self.gate.thresholds.auto_apply == 0.99

        # Now 0.97 should not auto-apply
        imp = self._make_improvement(0.97, rollback_plan="revert")
        decision = self.gate.determine_action(imp)
        assert decision.action != GateAction.AUTO_APPLY


# ============================================================
# FixHistoryTracker Tests
# ============================================================

class TestFixHistoryTracker:
    """FixHistoryTracker 단위 테스트"""

    def setup_method(self):
        self.tracker = FixHistoryTracker(
            max_attempts_per_problem=3,
            similar_fix_threshold=0.85,
            history_retention_days=30
        )

    def test_can_attempt_fix_initially(self):
        can, reason = self.tracker.can_attempt_fix("problem_1")
        assert can is True

    def test_max_attempts_exceeded(self):
        sig = "problem_1"
        for i in range(3):
            self.tracker.record_fix(sig, f"fix attempt {i}", "code_fix", False)

        can, reason = self.tracker.can_attempt_fix(sig)
        assert can is False
        assert "최대 시도 횟수" in reason

    def test_recent_success_blocks_attempts(self):
        sig = "problem_2"
        self.tracker.record_fix(sig, "successful fix", "code_fix", True)

        can, reason = self.tracker.can_attempt_fix(sig)
        assert can is False
        assert "성공한 수정" in reason

    def test_fix_cycle_detection(self):
        sig = "problem_3"
        # Record a fix
        self.tracker.record_fix(sig, "add error handling for null check", "code_fix", False)

        # Try very similar fix
        is_cycle, past = self.tracker.is_fix_cycle(
            sig, "add error handling for null check"
        )
        assert is_cycle is True
        assert past is not None

    def test_no_cycle_for_different_fix(self):
        sig = "problem_4"
        self.tracker.record_fix(sig, "add try-catch block", "code_fix", False)

        is_cycle, past = self.tracker.is_fix_cycle(
            sig, "completely different approach using retry logic with exponential backoff"
        )
        assert is_cycle is False

    def test_record_fix_returns_record(self):
        record = self.tracker.record_fix(
            "problem_5", "fix content", "prompt_update", True, 0.9
        )
        assert isinstance(record, FixRecord)
        assert record.success is True
        assert record.confidence == 0.9

    def test_get_fix_attempts(self):
        sig = "problem_6"
        self.tracker.record_fix(sig, "attempt 1", "code_fix", False)
        self.tracker.record_fix(sig, "attempt 2", "code_fix", False)
        assert self.tracker.get_fix_attempts(sig) == 2

    def test_get_history(self):
        sig = "problem_7"
        self.tracker.record_fix(sig, "fix 1", "code_fix", True)
        history = self.tracker.get_history(sig)
        assert len(history) == 1

    def test_success_rate(self):
        sig = "problem_8"
        self.tracker.record_fix(sig, "fix 1", "code_fix", True)
        self.tracker.record_fix(sig, "fix 2", "code_fix", False)
        rate = self.tracker.get_success_rate(sig)
        assert rate == 0.5

    def test_overall_success_rate(self):
        self.tracker.record_fix("p1", "fix", "code_fix", True)
        self.tracker.record_fix("p2", "fix", "code_fix", False)
        rate = self.tracker.get_success_rate()
        assert rate == 0.5

    def test_get_statistics(self):
        self.tracker.record_fix("p1", "fix", "code_fix", True)
        self.tracker.record_fix("p2", "fix", "prompt_update", False)
        stats = self.tracker.get_statistics()
        assert stats["total_problems"] == 2
        assert stats["total_attempts"] == 2
        assert stats["total_successes"] == 1

    def test_clear_history_specific(self):
        self.tracker.record_fix("p1", "fix", "code_fix", True)
        self.tracker.record_fix("p2", "fix", "code_fix", True)
        self.tracker.clear_history("p1")
        assert self.tracker.get_fix_attempts("p1") == 0
        assert self.tracker.get_fix_attempts("p2") == 1

    def test_clear_all_history(self):
        self.tracker.record_fix("p1", "fix", "code_fix", True)
        self.tracker.record_fix("p2", "fix", "code_fix", True)
        self.tracker.clear_history()
        assert self.tracker.get_statistics()["total_problems"] == 0

    def test_similarity_calculation(self):
        sim = self.tracker._calculate_similarity(
            "hello world foo bar",
            "hello world foo baz"
        )
        assert 0.5 < sim < 1.0  # partially similar

        sim_identical = self.tracker._calculate_similarity(
            "exact same text",
            "exact same text"
        )
        assert sim_identical == 1.0

        sim_empty = self.tracker._calculate_similarity("", "")
        assert sim_empty == 0.0


# ============================================================
# EvolutionConfig Tests
# ============================================================

class TestEvolutionConfig:
    """EvolutionConfig 단위 테스트"""

    def test_default_config_disabled(self):
        config = EvolutionConfig()
        assert config.enabled is False
        assert config.mode == EvolutionMode.BOTH

    def test_create_enabled(self):
        config = EvolutionConfig.create_enabled()
        assert config.enabled is True

    def test_create_disabled(self):
        config = EvolutionConfig.create_disabled()
        assert config.enabled is False

    def test_custom_config(self):
        config = EvolutionConfig(
            enabled=True,
            mode=EvolutionMode.HEALING,
            llm_provider="openai",
            llm_model="gpt-4",
            llm_temperature=0.1
        )
        assert config.enabled is True
        assert config.mode == EvolutionMode.HEALING
        assert config.llm_provider == "openai"

    def test_safety_defaults(self):
        config = EvolutionConfig()
        assert config.safety.failure_threshold == 3
        assert config.safety.auto_apply_threshold == 0.95
        assert config.safety.max_attempts_per_problem == 3

    def test_to_dict(self):
        config = EvolutionConfig(enabled=True)
        d = config.to_dict()
        assert d["enabled"] is True
        assert "llm" in d
        assert "safety" in d

    def test_from_dict(self):
        original = EvolutionConfig(
            enabled=True,
            mode=EvolutionMode.HEALING,
            llm_provider="openai"
        )
        d = original.to_dict()
        d["mode"] = "healing"  # from_dict expects string
        d["enabled"] = True
        d["llm"] = {"provider": "openai", "model": "gpt-4"}

        restored = EvolutionConfig.from_dict(d)
        assert restored.enabled is True
        assert restored.mode == EvolutionMode.HEALING
        assert restored.llm_provider == "openai"

    def test_from_dict_invalid_mode_defaults(self):
        restored = EvolutionConfig.from_dict({"mode": "invalid_mode"})
        assert restored.mode == EvolutionMode.BOTH

    def test_get_llm_config(self):
        config = EvolutionConfig(llm_provider="google", llm_model="gemini-2.5-flash-lite")
        llm = config.get_llm_config()
        assert llm.provider == "google"
        assert llm.model == "gemini-2.5-flash-lite"


# ============================================================
# EvolutionSystem Tests
# ============================================================

class TestEvolutionSystem:
    """EvolutionSystem 단위 테스트 (LLM 미사용)"""

    def test_create_disabled_by_default(self):
        system = EvolutionSystem()
        assert system.is_enabled is False

    def test_create_with_config(self):
        config = EvolutionConfig(enabled=True)
        system = EvolutionSystem(config=config)
        assert system.is_enabled is True

    def test_disable(self):
        config = EvolutionConfig(enabled=True)
        system = EvolutionSystem(config=config)
        system.disable()
        assert system.is_enabled is False

    @pytest.mark.asyncio
    async def test_process_when_disabled(self):
        system = EvolutionSystem()
        result = await system.process(
            query="test", response="test response"
        )
        assert result.success is True
        assert "비활성화" in result.message

    @pytest.mark.asyncio
    async def test_process_circuit_breaker_open(self):
        config = EvolutionConfig(enabled=True)
        system = EvolutionSystem(config=config)
        system._enabled = True
        system._initialized = True

        # Force circuit breaker open
        for _ in range(3):
            system._circuit_breaker.record_failure()

        result = await system.process(query="test", response="test")
        assert result.success is False
        assert "회로 차단기" in result.message

    def test_create_evolution_system_convenience(self):
        system = create_evolution_system(enabled=False)
        assert isinstance(system, EvolutionSystem)
        assert system.is_enabled is False

    def test_get_status(self):
        system = EvolutionSystem()
        status = system.get_status()
        assert "enabled" in status
        assert "circuit_breaker" in status
        assert "history" in status
        assert "gate" in status

    def test_reset(self):
        system = EvolutionSystem()
        # Record some failures
        system._circuit_breaker.record_failure()
        system._circuit_breaker.record_failure()
        system._history_tracker.record_fix("p1", "fix", "code_fix", False)

        system.reset()
        assert system._circuit_breaker.failure_count == 0

    def test_agent_id_extraction(self):
        # No agent
        system = EvolutionSystem()
        assert system._get_agent_id() == "unknown_agent"

        # Agent with agent_id
        agent = MagicMock()
        agent.agent_id = "test_agent"
        system.agent = agent
        assert system._get_agent_id() == "test_agent"

        # Agent with only name
        agent2 = MagicMock(spec=[])
        agent2.name = "Test Agent"
        system.agent = agent2
        assert system._get_agent_id() == "Test Agent"

    def test_result_message_generation(self):
        system = EvolutionSystem()

        problem = DetectedProblem(
            problem_type=ProblemType.RUNTIME_ERROR,
            severity=Severity.MEDIUM,
            description="test",
            query="test"
        )
        imp = Improvement(
            improvement_id="test_msg",
            pattern_id=None,
            problem=problem,
            improvement_type="code_fix",
            suggested_changes={},
            confidence=0.9,
        )

        msg = system._generate_result_message([imp], [], [])
        assert "1개 개선안 적용됨" in msg

        msg = system._generate_result_message([], [imp], [])
        assert "제안됨" in msg

        msg = system._generate_result_message([], [], [imp])
        assert "거부됨" in msg

        msg = system._generate_result_message([], [], [])
        assert "처리할 개선안이 없습니다" in msg


# ============================================================
# DetectedProblem / Improvement / EvolutionResult Type Tests
# ============================================================

class TestEvolutionTypes:
    """Evolution 타입 클래스 테스트"""

    def test_detected_problem_signature(self):
        p = DetectedProblem(
            problem_type=ProblemType.SYNTAX_ERROR,
            severity=Severity.HIGH,
            description="SyntaxError at line 10",
            query="test"
        )
        sig = p.signature
        assert isinstance(sig, str)
        assert len(sig) > 0

    def test_detected_problem_to_dict(self):
        p = DetectedProblem(
            problem_type=ProblemType.IMPORT_ERROR,
            severity=Severity.HIGH,
            description="Missing module",
            query="test",
            error_message="ModuleNotFoundError"
        )
        d = p.to_dict()
        assert d["problem_type"] == "import_error"
        assert d["severity"] == "high"

    def test_improvement_to_dict(self):
        problem = DetectedProblem(
            problem_type=ProblemType.RUNTIME_ERROR,
            severity=Severity.MEDIUM,
            description="ValueError",
            query="test"
        )
        imp = Improvement(
            improvement_id="imp_test",
            pattern_id=None,
            problem=problem,
            improvement_type="code_fix",
            suggested_changes={"fix": "add validation"},
            confidence=0.85,
        )
        d = imp.to_dict()
        assert d["improvement_type"] == "code_fix"
        assert d["confidence"] == 0.85
        assert "improvement_id" in d

    def test_evolution_result_to_dict(self):
        result = EvolutionResult(
            success=True,
            mode=EvolutionMode.BOTH,
            message="All good",
            execution_time_ms=150.5
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["mode"] == "both"
        assert d["execution_time_ms"] == 150.5

    def test_evolution_mode_values(self):
        assert EvolutionMode.HEALING.value == "healing"
        assert EvolutionMode.GROWING.value == "growing"
        assert EvolutionMode.BOTH.value == "both"

    def test_gate_action_values(self):
        assert GateAction.AUTO_APPLY.value == "auto_apply"
        assert GateAction.REJECT.value == "reject"


# ============================================================
# Run Tests
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
