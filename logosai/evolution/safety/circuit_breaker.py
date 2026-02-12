"""
Evolution Circuit Breaker (회로 차단기)

연속 실패 시 자동으로 진화 시스템을 중단하여 무한 루프를 방지합니다.
"""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Callable, Awaitable

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """회로 상태"""
    CLOSED = "closed"       # 정상 작동 (진화 가능)
    OPEN = "open"           # 차단됨 (진화 불가)
    HALF_OPEN = "half_open" # 테스트 모드 (제한적 진화)


@dataclass
class CircuitBreakerConfig:
    """회로 차단기 설정"""
    failure_threshold: int = 3          # 연속 실패 횟수 제한
    cooldown_period_seconds: int = 3600  # 쿨다운 기간 (초)
    half_open_max_calls: int = 1        # HALF_OPEN 상태에서 최대 시도 횟수
    success_threshold: int = 2          # HALF_OPEN에서 CLOSED로 가기 위한 성공 횟수


class EvolutionCircuitBreaker:
    """진화 시스템 회로 차단기"""

    def __init__(self, config: Optional[CircuitBreakerConfig] = None):
        """
        회로 차단기 초기화

        Args:
            config: 회로 차단기 설정 (None이면 기본값 사용)
        """
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[datetime] = None
        self._last_state_change: datetime = datetime.now()
        self._half_open_calls = 0
        self._on_state_change: Optional[Callable[[CircuitState, CircuitState], Awaitable[None]]] = None

    @property
    def state(self) -> CircuitState:
        """현재 회로 상태"""
        return self._state

    @property
    def failure_count(self) -> int:
        """현재 연속 실패 횟수"""
        return self._failure_count

    def can_execute(self) -> bool:
        """
        진화 실행 가능 여부 확인

        Returns:
            True if 진화 실행 가능
        """
        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN:
            # 쿨다운 기간이 지났는지 확인
            if self._cooldown_elapsed():
                self._transition_to(CircuitState.HALF_OPEN)
                return True
            return False

        if self._state == CircuitState.HALF_OPEN:
            # HALF_OPEN 상태에서는 제한된 횟수만 허용
            return self._half_open_calls < self.config.half_open_max_calls

        return False

    def record_success(self) -> None:
        """
        성공 기록

        CLOSED 상태로 복귀하거나 유지합니다.
        """
        logger.debug(f"Circuit breaker: 성공 기록 (현재 상태: {self._state.value})")

        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                self._transition_to(CircuitState.CLOSED)
                self._reset_counters()
        else:
            self._reset_counters()

    def record_failure(self, error: Optional[Exception] = None) -> None:
        """
        실패 기록

        연속 실패가 임계값에 도달하면 OPEN 상태로 전환합니다.

        Args:
            error: 발생한 예외 (선택)
        """
        self._failure_count += 1
        self._last_failure_time = datetime.now()

        logger.warning(
            f"Circuit breaker: 실패 기록 #{self._failure_count} "
            f"(임계값: {self.config.failure_threshold}, 상태: {self._state.value})"
        )

        if error:
            logger.warning(f"  오류: {type(error).__name__}: {str(error)[:100]}")

        if self._state == CircuitState.HALF_OPEN:
            # HALF_OPEN에서 실패하면 다시 OPEN으로
            self._transition_to(CircuitState.OPEN)
            self._half_open_calls = 0

        elif self._failure_count >= self.config.failure_threshold:
            self._transition_to(CircuitState.OPEN)
            self._alert_circuit_open()

    def reset(self) -> None:
        """
        회로 차단기 수동 리셋

        CLOSED 상태로 강제 복귀합니다.
        """
        logger.info("Circuit breaker: 수동 리셋")
        self._transition_to(CircuitState.CLOSED)
        self._reset_counters()

    def get_status(self) -> dict:
        """
        현재 상태 정보 반환

        Returns:
            상태 정보 딕셔너리
        """
        remaining_cooldown = None
        if self._state == CircuitState.OPEN and self._last_failure_time:
            elapsed = (datetime.now() - self._last_failure_time).total_seconds()
            remaining = self.config.cooldown_period_seconds - elapsed
            remaining_cooldown = max(0, remaining)

        return {
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure_time": self._last_failure_time.isoformat() if self._last_failure_time else None,
            "last_state_change": self._last_state_change.isoformat(),
            "remaining_cooldown_seconds": remaining_cooldown,
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "cooldown_period_seconds": self.config.cooldown_period_seconds
            }
        }

    def set_on_state_change(
        self,
        callback: Callable[[CircuitState, CircuitState], Awaitable[None]]
    ) -> None:
        """
        상태 변경 콜백 설정

        Args:
            callback: 상태 변경 시 호출될 비동기 함수
        """
        self._on_state_change = callback

    def _cooldown_elapsed(self) -> bool:
        """쿨다운 기간 경과 여부 확인"""
        if not self._last_failure_time:
            return True

        elapsed = datetime.now() - self._last_failure_time
        return elapsed >= timedelta(seconds=self.config.cooldown_period_seconds)

    def _transition_to(self, new_state: CircuitState) -> None:
        """상태 전환"""
        old_state = self._state
        if old_state != new_state:
            self._state = new_state
            self._last_state_change = datetime.now()

            logger.info(f"Circuit breaker: 상태 전환 {old_state.value} → {new_state.value}")

            if new_state == CircuitState.HALF_OPEN:
                self._half_open_calls = 0
                self._success_count = 0

    def _reset_counters(self) -> None:
        """카운터 리셋"""
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0

    def _alert_circuit_open(self) -> None:
        """회로 차단 알림"""
        logger.error(
            f"🚨 Circuit breaker OPEN: 연속 {self._failure_count}회 실패 "
            f"(쿨다운: {self.config.cooldown_period_seconds}초)"
        )
        logger.error("  → 진화 시스템이 일시 중단됩니다. 사람의 검토가 필요할 수 있습니다.")
