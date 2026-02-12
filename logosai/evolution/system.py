"""
Evolution System (진화 시스템)

에이전트 자가 진화의 모든 컴포넌트를 통합하는 메인 시스템입니다.
"""

import time
from typing import Optional, Dict, Any, List
from datetime import datetime

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from .config import EvolutionConfig
from .types import (
    EvolutionMode,
    EvolutionResult,
    DetectedProblem,
    Improvement,
    GateAction,
    ProblemType
)
from .detector import ProblemDetector
from .feedback import FeedbackCollector, FeedbackStore
from .learner import PatternLearner
from .improver import ImprovementGenerator
from .validator import ImprovementValidator
from .safety.circuit_breaker import EvolutionCircuitBreaker, CircuitBreakerConfig
from .safety.history_tracker import FixHistoryTracker
from .safety.confidence_gate import ConfidenceGate, GateThresholds


class EvolutionSystem:
    """에이전트 자가 진화 시스템"""

    def __init__(
        self,
        agent=None,
        config: Optional[EvolutionConfig] = None
    ):
        """
        진화 시스템 초기화

        Args:
            agent: 대상 에이전트 (선택)
            config: 진화 설정 (None이면 비활성화 상태로 생성)
        """
        self.agent = agent
        self.config = config or EvolutionConfig()

        # LLM 클라이언트 초기화 (설정된 경우)
        self._llm_client = None

        # 컴포넌트 초기화
        self._detector = ProblemDetector(
            config=self.config.detection
        )
        self._feedback_collector = FeedbackCollector()
        self._learner = PatternLearner(
            config=self.config.learning
        )
        self._improver = ImprovementGenerator(
            config=self.config
        )
        self._validator = ImprovementValidator(
            config=self.config.safety
        )

        # 안전 메커니즘
        self._circuit_breaker = EvolutionCircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=self.config.safety.failure_threshold,
                cooldown_period_seconds=self.config.safety.cooldown_period_seconds
            )
        )
        self._history_tracker = FixHistoryTracker(
            max_attempts_per_problem=self.config.safety.max_attempts_per_problem,
            similar_fix_threshold=self.config.safety.similar_fix_threshold
        )
        self._confidence_gate = ConfidenceGate(
            GateThresholds(
                auto_apply=self.config.safety.auto_apply_threshold,
                staged_rollout=self.config.safety.staged_rollout_threshold,
                human_review=self.config.safety.human_review_threshold,
                suggest_only=self.config.safety.suggest_only_threshold
            )
        )

        self._enabled = self.config.enabled
        self._initialized = False

        logger.info(
            f"EvolutionSystem 생성: enabled={self._enabled}, "
            f"mode={self.config.mode.value}, "
            f"llm={self.config.llm_provider}/{self.config.llm_model}"
        )

    async def initialize(self) -> bool:
        """
        시스템 초기화 (LLM 클라이언트 등)

        Returns:
            초기화 성공 여부
        """
        if self._initialized:
            return True

        if not self._enabled:
            logger.info("진화 시스템이 비활성화되어 있습니다.")
            return True

        try:
            # LLM 클라이언트 생성
            from ..utils.llm_client import LLMClient

            self._llm_client = LLMClient(
                provider=self.config.llm_provider,
                model=self.config.llm_model,
                temperature=self.config.llm_temperature,
                max_tokens=self.config.llm_max_tokens,
                api_key=self.config.llm_api_key
            )
            await self._llm_client.initialize()

            # 컴포넌트에 LLM 클라이언트 주입
            self._detector.llm_client = self._llm_client
            self._learner.llm_client = self._llm_client
            self._improver.llm_client = self._llm_client
            self._validator.llm_client = self._llm_client

            self._initialized = True
            logger.info("진화 시스템 초기화 완료")
            return True

        except Exception as e:
            logger.error(f"진화 시스템 초기화 실패: {e}")
            return False

    async def enable(self) -> bool:
        """시스템 활성화"""
        self._enabled = True
        return await self.initialize()

    def disable(self) -> None:
        """시스템 비활성화"""
        self._enabled = False
        logger.info("진화 시스템 비활성화됨")

    @property
    def is_enabled(self) -> bool:
        """활성화 상태"""
        return self._enabled

    @property
    def is_initialized(self) -> bool:
        """초기화 상태"""
        return self._initialized

    async def process(
        self,
        query: str,
        response: Any,
        error: Optional[Exception] = None,
        user_feedback: Optional[str] = None,
        agent_source: Optional[str] = None
    ) -> EvolutionResult:
        """
        진화 프로세스 실행

        Args:
            query: 사용자 쿼리
            response: 에이전트 응답
            error: 발생한 예외 (선택)
            user_feedback: 사용자 피드백 (선택)
            agent_source: 에이전트 소스 코드 (선택)

        Returns:
            진화 결과
        """
        start_time = time.time()

        # 비활성화 상태면 빈 결과 반환
        if not self._enabled:
            return EvolutionResult(
                success=True,
                mode=self.config.mode,
                message="진화 시스템이 비활성화되어 있습니다."
            )

        # 초기화 확인
        if not self._initialized:
            await self.initialize()

        # 회로 차단기 확인
        if not self._circuit_breaker.can_execute():
            return EvolutionResult(
                success=False,
                mode=self.config.mode,
                message="회로 차단기가 열려 있습니다. 쿨다운 대기 중.",
                execution_time_ms=(time.time() - start_time) * 1000
            )

        try:
            # 1. 문제 감지
            problems = await self._detector.detect(
                query=query,
                response=response,
                error=error,
                user_feedback=user_feedback,
                mode=self.config.mode
            )

            # 문제가 없으면 종료
            if not problems:
                # 피드백 수집 (긍정적)
                await self._feedback_collector.collect(
                    agent_id=self._get_agent_id(),
                    query=query,
                    response=response,
                    detected_problems=[]
                )

                return EvolutionResult(
                    success=True,
                    mode=self.config.mode,
                    message="문제가 감지되지 않았습니다.",
                    execution_time_ms=(time.time() - start_time) * 1000
                )

            # 피드백 수집 (부정적)
            await self._feedback_collector.collect(
                agent_id=self._get_agent_id(),
                query=query,
                response=response,
                explicit_feedback=user_feedback,
                detected_problems=problems
            )

            # 2. 패턴 학습
            patterns = await self._learner.learn_from_problems(problems)

            # 3. 개선안 생성
            improvements = await self._improver.generate_multiple(
                problems=problems,
                patterns=patterns,
                agent_source=agent_source
            )

            applied = []
            suggested = []
            rejected = []
            validation_results = []

            # 4. 각 개선안 검증 및 적용
            for improvement in improvements:
                # 수정 순환 확인
                is_cycle, past_fix = self._history_tracker.is_fix_cycle(
                    improvement.problem.signature,
                    str(improvement.suggested_changes)
                )

                if is_cycle:
                    logger.warning(f"수정 순환 감지 - 건너뜀: {improvement.improvement_id}")
                    rejected.append(improvement)
                    continue

                # 시도 횟수 확인
                can_attempt, reason = self._history_tracker.can_attempt_fix(
                    improvement.problem.signature
                )

                if not can_attempt:
                    logger.warning(f"수정 시도 불가: {reason}")
                    rejected.append(improvement)
                    continue

                # 검증
                results = await self._validator.validate(improvement, agent_source)
                validation_results.extend(results)

                all_passed = all(r.passed for r in results)

                if not all_passed:
                    logger.warning(f"검증 실패: {improvement.improvement_id}")
                    self._history_tracker.record_fix(
                        problem_signature=improvement.problem.signature,
                        fix_content=str(improvement.suggested_changes),
                        fix_type=improvement.improvement_type,
                        success=False,
                        confidence=improvement.confidence
                    )
                    rejected.append(improvement)
                    continue

                # 신뢰도 게이트 확인
                decision = self._confidence_gate.determine_action(improvement)

                if decision.action == GateAction.AUTO_APPLY:
                    # 자동 적용
                    apply_success = await self._apply_improvement(improvement)
                    if apply_success:
                        applied.append(improvement)
                        self._history_tracker.record_fix(
                            problem_signature=improvement.problem.signature,
                            fix_content=str(improvement.suggested_changes),
                            fix_type=improvement.improvement_type,
                            success=True,
                            confidence=improvement.confidence
                        )
                        self._learner.update_pattern_confidence(
                            improvement.pattern_id, success=True
                        )
                    else:
                        rejected.append(improvement)

                elif decision.action == GateAction.REJECT:
                    rejected.append(improvement)

                else:
                    # STAGED_ROLLOUT, HUMAN_REVIEW, SUGGEST_ONLY
                    suggested.append(improvement)

            # 성공 기록
            if applied or suggested:
                self._circuit_breaker.record_success()
            elif rejected and not improvements:
                self._circuit_breaker.record_failure()

            execution_time = (time.time() - start_time) * 1000

            return EvolutionResult(
                success=True,
                mode=self.config.mode,
                problems_detected=problems,
                improvements_applied=applied,
                improvements_suggested=suggested,
                improvements_rejected=rejected,
                validation_results=validation_results,
                message=self._generate_result_message(applied, suggested, rejected),
                execution_time_ms=execution_time
            )

        except Exception as e:
            self._circuit_breaker.record_failure(e)
            execution_time = (time.time() - start_time) * 1000

            logger.error(f"진화 프로세스 오류: {e}")

            return EvolutionResult(
                success=False,
                mode=self.config.mode,
                message=f"진화 프로세스 오류: {str(e)}",
                execution_time_ms=execution_time
            )

    async def analyze_only(
        self,
        query: str,
        response: Any,
        error: Optional[Exception] = None,
        user_feedback: Optional[str] = None
    ) -> EvolutionResult:
        """
        문제 분석만 수행 (개선안 생성 없음)

        Args:
            query: 사용자 쿼리
            response: 에이전트 응답
            error: 발생한 예외
            user_feedback: 사용자 피드백 (선택)

        Returns:
            분석 결과 (EvolutionResult)
        """
        start_time = time.time()

        if not self._initialized:
            await self.initialize()

        try:
            problems = await self._detector.detect(
                query=query,
                response=response,
                error=error,
                user_feedback=user_feedback,
                mode=self.config.mode
            )

            execution_time = (time.time() - start_time) * 1000

            return EvolutionResult(
                success=True,
                mode=self.config.mode,
                problems_detected=problems,
                message=f"{len(problems)}개 문제 감지됨" if problems else "문제가 감지되지 않았습니다.",
                execution_time_ms=execution_time
            )

        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            logger.error(f"분석 오류: {e}")

            return EvolutionResult(
                success=False,
                mode=self.config.mode,
                message=f"분석 오류: {str(e)}",
                execution_time_ms=execution_time
            )

    async def suggest_improvements(
        self,
        problems: List[DetectedProblem],
        agent_source: Optional[str] = None
    ) -> List[Improvement]:
        """
        개선안만 생성 (적용 없음)

        Args:
            problems: 문제 리스트
            agent_source: 에이전트 소스 코드

        Returns:
            개선안 리스트
        """
        if not self._initialized:
            await self.initialize()

        patterns = await self._learner.learn_from_problems(problems)

        return await self._improver.generate_multiple(
            problems=problems,
            patterns=patterns,
            agent_source=agent_source
        )

    async def apply_improvement(
        self,
        improvement: Improvement,
        force: bool = False
    ) -> bool:
        """
        개선안 수동 적용

        Args:
            improvement: 적용할 개선안
            force: 검증 건너뛰기

        Returns:
            적용 성공 여부
        """
        if not force:
            results = await self._validator.validate(improvement)
            if not all(r.passed for r in results):
                logger.warning("검증 실패로 적용 불가")
                return False

        return await self._apply_improvement(improvement)

    async def _apply_improvement(self, improvement: Improvement) -> bool:
        """
        개선안 실제 적용 (내부 메서드)

        실제 구현에서는 에이전트 코드/설정을 수정합니다.
        """
        logger.info(f"개선안 적용: {improvement.improvement_id}")

        # TODO: 실제 적용 로직 구현
        # - code_fix: 코드 파일 수정
        # - prompt_update: 프롬프트 설정 수정
        # - new_function: 새 함수 추가
        # - config_change: 설정 변경

        improvement_type = improvement.improvement_type
        changes = improvement.suggested_changes

        if improvement_type == "prompt_update":
            logger.info(f"프롬프트 업데이트 제안: {changes.get('summary', 'N/A')}")
            # 실제로는 에이전트의 프롬프트를 수정

        elif improvement_type == "code_fix":
            logger.info(f"코드 수정 제안: {changes.get('summary', 'N/A')}")
            # 실제로는 코드 파일을 수정

        elif improvement_type == "new_function":
            logger.info(f"새 기능 추가 제안: {changes.get('summary', 'N/A')}")
            # 실제로는 새 함수를 추가

        elif improvement_type == "config_change":
            logger.info(f"설정 변경 제안: {changes.get('summary', 'N/A')}")
            # 실제로는 설정을 변경

        # 현재는 로깅만 수행 (실제 적용은 추후 구현)
        return True

    def get_status(self) -> Dict[str, Any]:
        """시스템 상태 조회"""
        return {
            "enabled": self._enabled,
            "initialized": self._initialized,
            "mode": self.config.mode.value,
            "circuit_breaker": self._circuit_breaker.get_status(),
            "history": self._history_tracker.get_statistics(),
            "gate": self._confidence_gate.get_statistics(),
            "feedback": self._feedback_collector.get_statistics(),
            "patterns": self._learner.get_statistics(),
            "config": {
                "llm_provider": self.config.llm_provider,
                "llm_model": self.config.llm_model
            }
        }

    def reset(self) -> None:
        """시스템 리셋"""
        self._circuit_breaker.reset()
        self._history_tracker.clear_history()
        logger.info("진화 시스템 리셋 완료")

    def _get_agent_id(self) -> str:
        """에이전트 ID 반환"""
        if self.agent:
            if hasattr(self.agent, 'agent_id'):
                return self.agent.agent_id
            elif hasattr(self.agent, 'name'):
                return self.agent.name
        return "unknown_agent"

    def _generate_result_message(
        self,
        applied: List[Improvement],
        suggested: List[Improvement],
        rejected: List[Improvement]
    ) -> str:
        """결과 메시지 생성"""
        parts = []

        if applied:
            parts.append(f"{len(applied)}개 개선안 적용됨")
        if suggested:
            parts.append(f"{len(suggested)}개 개선안 제안됨 (검토 필요)")
        if rejected:
            parts.append(f"{len(rejected)}개 개선안 거부됨")

        if not parts:
            return "처리할 개선안이 없습니다."

        return ", ".join(parts)


# 편의 함수
def create_evolution_system(
    agent=None,
    enabled: bool = False,
    llm_provider: str = "google",
    llm_model: str = "gemini-2.5-flash-lite",
    **kwargs
) -> EvolutionSystem:
    """
    진화 시스템 생성 편의 함수

    Args:
        agent: 대상 에이전트
        enabled: 활성화 여부 (기본: False)
        llm_provider: LLM 프로바이더
        llm_model: LLM 모델
        **kwargs: 추가 설정

    Returns:
        EvolutionSystem 인스턴스
    """
    config = EvolutionConfig(
        enabled=enabled,
        llm_provider=llm_provider,
        llm_model=llm_model,
        **kwargs
    )
    return EvolutionSystem(agent=agent, config=config)
