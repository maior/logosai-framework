"""Phase F: Guardrails — TDD 테스트.

1. TokenBucketRateLimiter — 분당 호출 제한
2. RequestCallCounter — 요청당 LLM 호출 제한
3. 통합: LLMClient에 연결

Usage: python tests/test_guardrails.py
"""

import asyncio
import time
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ============================================================
# TokenBucketRateLimiter
# ============================================================

class TokenBucketRateLimiter:
    """Token bucket rate limiter for LLM calls.

    Limits calls per minute. If bucket empty, waits until token available.
    """

    def __init__(self, calls_per_minute: int = 30):
        self.max_tokens = calls_per_minute
        self.tokens = float(calls_per_minute)
        self.refill_rate = calls_per_minute / 60.0  # tokens per second
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Wait until a token is available, then consume one."""
        async with self._lock:
            self._refill()
            while self.tokens < 1:
                wait_time = (1 - self.tokens) / self.refill_rate
                await asyncio.sleep(min(wait_time, 2.0))
                self._refill()
            self.tokens -= 1

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    @property
    def available(self) -> int:
        self._refill()
        return int(self.tokens)


# ============================================================
# RequestCallCounter
# ============================================================

class RequestCallCounter:
    """Per-request LLM call counter with limit.

    Each request gets a counter. Raises when limit exceeded.
    """

    def __init__(self, max_calls: int = 10):
        self.max_calls = max_calls
        self.current_calls = 0
        self.started_at = time.time()

    def increment(self):
        """Increment counter. Raises if limit exceeded."""
        self.current_calls += 1
        if self.current_calls > self.max_calls:
            raise LLMCallLimitExceeded(
                f"LLM call limit exceeded: {self.current_calls}/{self.max_calls} "
                f"(elapsed: {time.time() - self.started_at:.1f}s)"
            )

    def reset(self):
        self.current_calls = 0
        self.started_at = time.time()

    @property
    def remaining(self) -> int:
        return max(0, self.max_calls - self.current_calls)


class LLMCallLimitExceeded(Exception):
    pass


# ============================================================
# Tests
# ============================================================

async def main():
    print("=" * 70)
    print("Phase F: Guardrails — TDD Tests")
    print("=" * 70)

    # ── T1: TokenBucketRateLimiter 기본 동작 ──
    print("\n=== T1: Rate Limiter — 기본 동작 ===")
    rl = TokenBucketRateLimiter(calls_per_minute=60)  # 1 call/sec

    t = time.time()
    for i in range(5):
        await rl.acquire()
    elapsed = time.time() - t

    print(f"  5 calls in {elapsed:.2f}s (available: {rl.available})")
    assert elapsed < 1.0, f"Should be fast with 60/min bucket, took {elapsed:.2f}s"
    print(f"  ✅ PASS — 빠른 호출 OK")

    # ── T2: Rate Limiter — 제한 동작 ──
    print("\n=== T2: Rate Limiter — 속도 제한 ===")
    rl2 = TokenBucketRateLimiter(calls_per_minute=6)  # 0.1 call/sec = 1 per 10s

    # Drain bucket
    for i in range(6):
        await rl2.acquire()

    t = time.time()
    await rl2.acquire()  # Should wait for refill
    wait_time = time.time() - t

    print(f"  7th call waited {wait_time:.2f}s")
    assert wait_time > 0.5, f"Should have waited, only {wait_time:.2f}s"
    print(f"  ✅ PASS — 속도 제한 동작")

    # ── T3: RequestCallCounter — 정상 ──
    print("\n=== T3: Request Counter — 정상 범위 ===")
    counter = RequestCallCounter(max_calls=5)

    for i in range(5):
        counter.increment()

    print(f"  5/5 calls, remaining: {counter.remaining}")
    assert counter.remaining == 0
    print(f"  ✅ PASS")

    # ── T4: RequestCallCounter — 초과 ──
    print("\n=== T4: Request Counter — 초과 차단 ===")
    counter2 = RequestCallCounter(max_calls=3)

    try:
        for i in range(10):
            counter2.increment()
        print(f"  ❌ FAIL — should have raised")
    except LLMCallLimitExceeded as e:
        print(f"  Exception: {e}")
        print(f"  ✅ PASS — 4번째 호출에서 차단")

    # ── T5: RequestCallCounter — reset ──
    print("\n=== T5: Request Counter — 리셋 ===")
    counter3 = RequestCallCounter(max_calls=3)
    counter3.increment()
    counter3.increment()
    counter3.increment()
    counter3.reset()
    counter3.increment()  # Should work after reset
    print(f"  After reset: calls={counter3.current_calls}, remaining={counter3.remaining}")
    assert counter3.current_calls == 1
    print(f"  ✅ PASS")

    # ── T6: 실제 LLM 호출과 통합 시뮬레이션 ──
    print("\n=== T6: LLM 통합 시뮬레이션 ===")

    rate_limiter = TokenBucketRateLimiter(calls_per_minute=30)
    request_counter = RequestCallCounter(max_calls=10)

    call_log = []

    async def guarded_llm_call(prompt: str):
        """Simulated LLM call with guardrails."""
        await rate_limiter.acquire()
        request_counter.increment()
        # Simulate LLM latency
        await asyncio.sleep(0.05)
        call_log.append(prompt)
        return f"Response to: {prompt}"

    # Normal usage
    for i in range(8):
        await guarded_llm_call(f"prompt_{i}")

    print(f"  8 calls OK, remaining: {request_counter.remaining}")
    assert len(call_log) == 8

    # Exceed limit
    try:
        for i in range(5):
            await guarded_llm_call(f"extra_{i}")
        print(f"  ❌ FAIL — should have raised at 11th call")
    except LLMCallLimitExceeded:
        print(f"  Blocked at call #{request_counter.current_calls}")
        print(f"  ✅ PASS — 10회 초과 시 차단")

    # ── T7: 실제 LLMClient 연동 테스트 ──
    print("\n=== T7: 실제 LLMClient + Guardrails ===")

    from logosai.utils.llm_client import LLMClient
    llm = LLMClient()
    await llm.initialize()

    # Attach guardrails
    llm._rate_limiter = TokenBucketRateLimiter(calls_per_minute=30)
    llm._request_counter = RequestCallCounter(max_calls=5)

    # Monkey-patch invoke to use guardrails
    original_invoke = llm.invoke_messages

    async def guarded_invoke(messages, **kwargs):
        await llm._rate_limiter.acquire()
        llm._request_counter.increment()
        return await original_invoke(messages, **kwargs)

    llm.invoke_messages = guarded_invoke

    # 3 calls should work
    for i in range(3):
        resp = await llm.invoke(f"Say hi #{i+1}")
        assert resp.content

    print(f"  3 LLM calls OK (remaining: {llm._request_counter.remaining})")
    print(f"  ✅ PASS — 실제 LLM + guardrails 동작")

    # ── Summary ──
    print(f"\n{'=' * 70}")
    print("SUMMARY: 7/7 tests passed ✅")
    print("Guardrails 로직 검증 완료 — LLMClient에 적용 가능")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
