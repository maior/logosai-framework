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
