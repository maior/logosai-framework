"""Guardrails — Rate limiting + call counting for LLM safety.

Prevents:
- 429 Rate Limit errors (TokenBucketRateLimiter)
- Agent runaway / LLM call explosion (RequestCallCounter)

Integrated into LLMClient.invoke_messages() automatically.

Config via ~/.logosai/config.json:
    "guardrails": {
        "rate_limit_per_minute": 30,
        "max_calls_per_request": 15
    }
"""

import asyncio
import time
from loguru import logger


class LLMCallLimitExceeded(Exception):
    """Raised when per-request LLM call limit is exceeded."""
    pass


class TokenBucketRateLimiter:
    """Token bucket rate limiter — prevents 429 errors.

    Limits LLM calls per minute globally. If bucket is empty,
    waits until a token is available (instead of getting 429).
    """

    def __init__(self, calls_per_minute: int = 30):
        self.max_tokens = calls_per_minute
        self.tokens = float(calls_per_minute)
        self.refill_rate = calls_per_minute / 60.0
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Wait until a token is available, then consume one."""
        async with self._lock:
            self._refill()
            while self.tokens < 1:
                wait_time = (1 - self.tokens) / self.refill_rate
                logger.debug(f"Rate limiter: waiting {wait_time:.1f}s")
                await asyncio.sleep(min(wait_time, 2.0))
                self._refill()
            self.tokens -= 1

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now


class RequestCallCounter:
    """Per-request LLM call counter — prevents agent runaway.

    Each request gets a counter. Raises LLMCallLimitExceeded when limit hit.
    Agent should catch this and return partial results gracefully.
    """

    def __init__(self, max_calls: int = 15):
        self.max_calls = max_calls
        self.current_calls = 0

    def increment(self):
        self.current_calls += 1
        if self.current_calls > self.max_calls:
            raise LLMCallLimitExceeded(
                f"LLM call limit exceeded: {self.current_calls}/{self.max_calls}"
            )

    def reset(self):
        self.current_calls = 0

    @property
    def remaining(self) -> int:
        return max(0, self.max_calls - self.current_calls)


# ── Global singleton (shared across all LLMClient instances) ──

_rate_limiter = None
_request_counter = None


def get_rate_limiter() -> TokenBucketRateLimiter:
    """Get global rate limiter (created once, reused)."""
    global _rate_limiter
    if _rate_limiter is None:
        rate = _get_config("rate_limit_per_minute", 30)
        _rate_limiter = TokenBucketRateLimiter(calls_per_minute=rate)
    return _rate_limiter


def get_request_counter() -> RequestCallCounter:
    """Get global request counter (reset per request by caller)."""
    global _request_counter
    if _request_counter is None:
        max_calls = _get_config("max_calls_per_request", 15)
        _request_counter = RequestCallCounter(max_calls=max_calls)
    return _request_counter


def reset_request_counter():
    """Reset counter for new request."""
    global _request_counter
    if _request_counter:
        _request_counter.reset()


def _get_config(key: str, default):
    """Read guardrails config from ~/.logosai/config.json."""
    import json
    import os
    try:
        path = os.path.expanduser("~/.logosai/config.json")
        if os.path.exists(path):
            with open(path) as f:
                config = json.load(f)
            return config.get("guardrails", {}).get(key, default)
    except Exception:
        pass
    return default


# ── Per-execution 하네스 예산 (호출 수·토큰 상한) — P0-2 확장 (2026-07-06) ──
# 글로벌 RequestCallCounter 와 달리 ContextVar 로 실행별 격리한다.
# 하네스 래퍼(observability.observe_process)가 process() 진입 시 begin,
# 종료 시 reset. LLMClient 가 호출 전 precheck / 호출 후 record_tokens 를 부른다.
# caps 미설정(None)이면 완전 no-op → 비하네스 경로 성능/동작 불변.
from contextvars import ContextVar
from typing import Optional as _Optional, Tuple as _Tuple

_exec_calls: ContextVar[int] = ContextVar("_hb_exec_calls", default=0)
_exec_tokens: ContextVar[int] = ContextVar("_hb_exec_tokens", default=0)
_exec_max_calls: ContextVar[_Optional[int]] = ContextVar("_hb_max_calls", default=None)
_exec_max_tokens: ContextVar[_Optional[int]] = ContextVar("_hb_max_tokens", default=None)


class HarnessBudgetExceeded(Exception):
    """실행당 LLM 호출/토큰 상한 초과 — 하네스가 graceful error 로 변환한다."""
    pass


def begin_execution_budget(max_calls: _Optional[int],
                           max_tokens: _Optional[int]) -> _Tuple:
    """실행 예산 시작. 반환한 토큰을 reset_execution_budget 에 넘겨 복원한다."""
    return (
        _exec_calls.set(0),
        _exec_tokens.set(0),
        _exec_max_calls.set(max_calls),
        _exec_max_tokens.set(max_tokens),
    )


def reset_execution_budget(tokens: _Optional[_Tuple]) -> None:
    """begin_execution_budget 이 반환한 토큰으로 ContextVar 복원."""
    if not tokens:
        return
    c, t, mc, mt = tokens
    try:
        _exec_calls.reset(c)
        _exec_tokens.reset(t)
        _exec_max_calls.reset(mc)
        _exec_max_tokens.reset(mt)
    except (ValueError, LookupError):
        # 다른 context 에서 reset 시도(비정상) — 방어적 무시.
        pass


def precheck_llm_call() -> None:
    """각 LLM 호출 '전' 호출. 예산 미활성이면 no-op.

    누적 토큰이 상한 이상이면 즉시 차단. 아니면 호출 카운트 +1 후 상한 초과 시 차단.
    """
    mc = _exec_max_calls.get()
    mt = _exec_max_tokens.get()
    if mc is None and mt is None:
        return  # 예산 미활성
    if mt is not None and _exec_tokens.get() >= mt:
        raise HarnessBudgetExceeded(
            f"token budget exceeded: {_exec_tokens.get()}/{mt}")
    if mc is not None:
        n = _exec_calls.get() + 1
        _exec_calls.set(n)
        if n > mc:
            raise HarnessBudgetExceeded(
                f"LLM call budget exceeded: {n}/{mc}")


def record_llm_tokens(input_tokens: int, output_tokens: int) -> None:
    """LLM 호출 '후' 호출. 토큰 예산 미활성이면 no-op."""
    if _exec_max_tokens.get() is None:
        return
    try:
        used = int(input_tokens or 0) + int(output_tokens or 0)
    except (TypeError, ValueError):
        used = 0
    _exec_tokens.set(_exec_tokens.get() + used)
