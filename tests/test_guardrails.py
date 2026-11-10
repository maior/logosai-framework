"""Phase F: Guardrails — TDD 테스트.

1. TokenBucketRateLimiter — 분당 호출 제한
2. RequestCallCounter — 요청당 LLM 호출 제한
3. 통합: LLMClient에 연결

두 가지로 돈다 (2026-11-10):
  - pytest: T1~T7 이 각각 `async def test_*` (asyncio_mode=auto). 예전엔
    `async def main()` 하나뿐이라 pytest 가 **0건을 수집**했다.
  - 직접 실행: python tests/test_guardrails.py  → 요약 블록으로 끝난다.

⚠️ T1~T6 이 검증하는 것은 **이 파일에 정의된 클래스**다 (TDD 당시의 원형).
   `logosai/utils/guardrails.py` 의 동명 클래스가 아니다.
⚠️ T7 은 실제 LLM 을 3회 호출한다 — pytest 에서는 `live` 마커, LOGOSAI_LIVE_TESTS=1 일 때만 돈다.
"""

import asyncio
import inspect
import time
import sys
import os


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

def _setup(mp):
    """`mp` = pytest monkeypatch 또는 `_ScriptPatch`. T7 의 실제 LLM 호출이
    운영 관측 DB(Pulse)에 기록을 남기지 않게 한다 — 끝나면 되돌려진다."""
    mp.delenv("LOGOSAI_PULSE_ALLOW_IN_TESTS", raising=False)
    mp.setenv("LOGOS_PULSE_DISABLED", "1")


async def test_t1_rate_limiter_fast_when_bucket_has_tokens():
    """T1: Rate Limiter — 기본 동작"""
    rl = TokenBucketRateLimiter(calls_per_minute=60)  # 1 call/sec

    t = time.time()
    for i in range(5):
        await rl.acquire()
    elapsed = time.time() - t

    print(f"  5 calls in {elapsed:.2f}s (available: {rl.available})")
    assert elapsed < 1.0, f"Should be fast with 60/min bucket, took {elapsed:.2f}s"
    print(f"  ✅ PASS — 빠른 호출 OK")


async def test_t2_rate_limiter_waits_when_bucket_drained():
    """T2: Rate Limiter — 속도 제한"""
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


async def test_t3_request_counter_allows_up_to_limit():
    """T3: Request Counter — 정상 범위"""
    counter = RequestCallCounter(max_calls=5)

    for i in range(5):
        counter.increment()

    print(f"  5/5 calls, remaining: {counter.remaining}")
    assert counter.remaining == 0
    print(f"  ✅ PASS")


async def test_t4_request_counter_blocks_fourth_call():
    """T4: Request Counter — 초과 차단"""
    # 원래는 예외가 안 나면 "❌ FAIL" 을 **출력만** 하고 통과했다 — 단언으로 바꿨다.
    counter2 = RequestCallCounter(max_calls=3)

    raised = None
    try:
        for i in range(10):
            counter2.increment()
    except LLMCallLimitExceeded as e:
        raised = e
    assert raised is not None, "should have raised"
    assert counter2.current_calls == 4, f"4번째가 아니라 {counter2.current_calls}번째에서 차단"
    print(f"  Exception: {raised}")
    print(f"  ✅ PASS — 4번째 호출에서 차단")


async def test_t5_request_counter_reset():
    """T5: Request Counter — 리셋"""
    counter3 = RequestCallCounter(max_calls=3)
    counter3.increment()
    counter3.increment()
    counter3.increment()
    counter3.reset()
    counter3.increment()  # Should work after reset
    print(f"  After reset: calls={counter3.current_calls}, remaining={counter3.remaining}")
    assert counter3.current_calls == 1
    print(f"  ✅ PASS")


async def test_t6_guarded_llm_call_simulation_blocks_eleventh_call():
    """T6: LLM 통합 시뮬레이션"""
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

    # Exceed limit — 원래는 예외가 안 나면 "❌ FAIL" 을 출력만 했다.
    raised = False
    try:
        for i in range(5):
            await guarded_llm_call(f"extra_{i}")
    except LLMCallLimitExceeded:
        raised = True
    assert raised, "should have raised at 11th call"
    assert request_counter.current_calls == 11
    assert len(call_log) == 10, "차단된 호출이 LLM 까지 갔다"
    print(f"  Blocked at call #{request_counter.current_calls}")
    print(f"  ✅ PASS — 10회 초과 시 차단")


async def test_t7_real_llm_client_with_guardrails_attached():
    """T7: 실제 LLMClient + Guardrails"""
    from logosai.utils.llm_client import LLMClient
    llm = LLMClient()
    await llm.initialize()

    # Attach guardrails
    llm._rate_limiter = TokenBucketRateLimiter(calls_per_minute=30)
    llm._request_counter = RequestCallCounter(max_calls=5)

    # Monkey-patch invoke to use guardrails (이 인스턴스에만 — 전역 아님)
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
    assert llm._request_counter.remaining == 2, "가드레일을 거치지 않고 LLM 이 호출됐다"
    print(f"  ✅ PASS — 실제 LLM + guardrails 동작")


# ══ pytest 배선 ═══════════════════════════════════════════════════════════

if "pytest" in sys.modules:
    import pytest

    @pytest.fixture(autouse=True)
    def _guardrails_env(monkeypatch):
        _setup(monkeypatch)

    # live: T7 은 진짜 LLM 을 3회 호출한다 — LOGOSAI_LIVE_TESTS=1 로만 돈다 (tests/conftest.py).
    # 예전엔 GOOGLE_API_KEY 가 있기만 하면 돌아서, 키가 있는 개발 기기에서는 매 실행마다 과금됐다.
    test_t7_real_llm_client_with_guardrails_attached = pytest.mark.live(
        test_t7_real_llm_client_with_guardrails_attached)


# ══ 스크립트 모드 러너 (pytest 없이도 돈다) ════════════════════════════════

class _ScriptPatch:
    """pytest monkeypatch 의 최소 대역 — 세운 것을 `undo()` 로 전부 되돌린다."""

    def __init__(self):
        self._undo = []

    def setenv(self, key, value):
        self._remember_env(key)
        os.environ[key] = str(value)

    def delenv(self, key, raising=True):
        if key not in os.environ:
            if raising:
                raise KeyError(key)
            return
        self._remember_env(key)
        del os.environ[key]

    def setattr(self, obj, name, value):
        old = getattr(obj, name)
        self._undo.append(lambda: setattr(obj, name, old))
        setattr(obj, name, value)

    def _remember_env(self, key):
        old = os.environ.get(key)

        def restore():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old

        self._undo.append(restore)

    def undo(self):
        while self._undo:
            self._undo.pop()()


def _script_tests():
    """이 모듈의 `test_*` 를 정의 순서대로 — 목록을 따로 두지 않아 빠뜨릴 수 없다."""
    return [fn for name, fn in list(globals().items())
            if name.startswith("test_") and inspect.isfunction(fn)]


async def main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    print("=" * 70)
    print("Phase F: Guardrails — TDD Tests")
    print("=" * 70)

    tests = _script_tests()
    failed = []
    for fn in tests:
        label = (fn.__doc__ or fn.__name__).strip().splitlines()[0]
        print(f"\n=== {label} ===")
        mp = _ScriptPatch()
        try:
            _setup(mp)
            await fn()
        except AssertionError as e:
            print(f"  ❌ FAIL — {e}")
            failed.append(label)
        finally:
            mp.undo()

    # ── Summary ──
    passed = len(tests) - len(failed)
    print(f"\n{'=' * 70}")
    print(f"SUMMARY: {passed}/{len(tests)} tests passed {'✅' if not failed else '❌'}")
    if failed:
        print(f"FAILED: {failed}")
    else:
        print("Guardrails 로직 검증 완료 — LLMClient에 적용 가능")
    print(f"{'=' * 70}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
